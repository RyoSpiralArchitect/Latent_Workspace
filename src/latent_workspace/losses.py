"""v4's LatentWorkspaceLoss: keep the latent trajectory recoverable without collapse.

Promoted verbatim from ``engine.py`` in ``latent_workspace_ft_v10`` at
``d4cd1ee0340a``. The historical files are frozen; this module is the living home
(docs/ARCHITECTURE.md). Parity: ``test_workspace_loss_is_the_historical_loss``.
"""

from __future__ import annotations

import math

import torch
from torch import nn
from torch.nn import functional as F


class LatentWorkspaceLoss(nn.Module):
    """Regularizes a latent workspace so that information remains recoverable
    without allowing the representation geometry to collapse.

    The module is intentionally monolithic: geometry, retention, identity,
    relational structure, temporal continuity, and spectral rank are evaluated
    together from a latent trajectory ``h_1 ... h_K``.

    Notes
    -----
    * Batch statistics require B >= 2. With B == 1, batch-geometric terms are
      returned as zero because variance/covariance/rank are not identifiable.
    * ``h0`` is always used as a stop-gradient target.
    * Expensive spectral terms can be skipped per call with
      ``compute_spectral=False``.
    """

    def __init__(
        self,
        hidden_dim: int,
        projection_dim: int | None = None,
        *,
        variance_target: float = 1.0,
        eps: float = 1e-4,
        contrastive_temperature: float = 0.10,
        worst_step_temperature: float = 0.10,
        temporal_drift_margin: float = 0.20,
        probe_dropout: float = 0.10,
        lambda_var: float = 1.0,
        lambda_cov: float = 1.0,
        lambda_info: float = 0.5,
        lambda_contrast: float = 0.25,
        lambda_relation: float = 0.10,
        lambda_temporal: float = 0.10,
        lambda_worst: float = 0.25,
        lambda_rank: float = 0.05,
    ) -> None:
        super().__init__()

        if hidden_dim <= 1:
            raise ValueError("hidden_dim must be greater than 1.")

        projection_dim = projection_dim or min(hidden_dim, 256)
        if projection_dim <= 1:
            raise ValueError("projection_dim must be greater than 1.")
        if variance_target <= 0:
            raise ValueError("variance_target must be positive.")
        if eps <= 0:
            raise ValueError("eps must be positive.")
        if contrastive_temperature <= 0:
            raise ValueError("contrastive_temperature must be positive.")
        if worst_step_temperature <= 0:
            raise ValueError("worst_step_temperature must be positive.")
        if not 0.0 <= temporal_drift_margin <= 2.0:
            raise ValueError("temporal_drift_margin must be in [0, 2].")
        if not 0.0 <= probe_dropout < 1.0:
            raise ValueError("probe_dropout must be in [0, 1).")

        lambdas = {
            "lambda_var": lambda_var,
            "lambda_cov": lambda_cov,
            "lambda_info": lambda_info,
            "lambda_contrast": lambda_contrast,
            "lambda_relation": lambda_relation,
            "lambda_temporal": lambda_temporal,
            "lambda_worst": lambda_worst,
            "lambda_rank": lambda_rank,
        }
        for name, value in lambdas.items():
            if value < 0:
                raise ValueError(f"{name} must be non-negative.")

        self.hidden_dim = hidden_dim
        self.projection_dim = projection_dim
        self.variance_target = variance_target
        self.eps = eps
        self.contrastive_temperature = contrastive_temperature
        self.worst_step_temperature = worst_step_temperature
        self.temporal_drift_margin = temporal_drift_margin

        self.lambda_var = lambda_var
        self.lambda_cov = lambda_cov
        self.lambda_info = lambda_info
        self.lambda_contrast = lambda_contrast
        self.lambda_relation = lambda_relation
        self.lambda_temporal = lambda_temporal
        self.lambda_worst = lambda_worst
        self.lambda_rank = lambda_rank

        # Geometry is regularized in a separate projection space so semantic
        # coordinates in the original hidden state are not forced to decorrelate.
        self.geometry_projector = nn.Sequential(
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, projection_dim, bias=False),
            nn.GELU(),
            nn.Linear(projection_dim, projection_dim, bias=False),
        )

        # One shared readout across all latent steps. Dropout makes exact
        # recovery rely on distributed information rather than a tiny feature slot.
        self.probe_norm = nn.LayerNorm(hidden_dim)
        self.probe_dropout = nn.Dropout(probe_dropout)
        self.probe = nn.Linear(hidden_dim, hidden_dim)

        # Starting from an identity map prevents the auxiliary task from being
        # unnecessarily chaotic at initialization.
        nn.init.eye_(self.probe.weight)
        nn.init.zeros_(self.probe.bias)

    @staticmethod
    def _validate_inputs(latents: torch.Tensor, h0: torch.Tensor) -> None:
        if latents.ndim != 3:
            raise ValueError("latents must have shape [B, K, D].")
        if h0.ndim != 2:
            raise ValueError("h0 must have shape [B, D].")
        if latents.shape[0] != h0.shape[0]:
            raise ValueError("latents and h0 must share the batch dimension.")
        if latents.shape[2] != h0.shape[1]:
            raise ValueError("latents and h0 must share the hidden dimension.")
        if latents.shape[1] <= 0:
            raise ValueError("K_steps must be positive.")
        if not latents.is_floating_point() or not h0.is_floating_point():
            raise TypeError("latents and h0 must be floating-point tensors.")
        if latents.device != h0.device:
            raise ValueError("latents and h0 must be on the same device.")

    @staticmethod
    def _normalized_weights(
        K: int,
        device: torch.device,
        step_weights: torch.Tensor | None,
    ) -> torch.Tensor:
        if step_weights is None:
            return torch.full((K,), 1.0 / K, device=device, dtype=torch.float32)

        if step_weights.ndim != 1 or step_weights.numel() != K:
            raise ValueError("step_weights must have shape [K].")

        weights = step_weights.detach().to(device=device, dtype=torch.float32)
        if not torch.isfinite(weights).all():
            raise ValueError("step_weights must contain only finite values.")
        if (weights < 0).any():
            raise ValueError("step_weights must be non-negative.")

        total = weights.sum()
        if total <= 0:
            raise ValueError("step_weights must have a positive sum.")
        return weights / total

    @staticmethod
    def _weighted_mean(values: torch.Tensor, weights: torch.Tensor) -> torch.Tensor:
        if values.ndim != 1 or weights.ndim != 1 or values.shape != weights.shape:
            raise ValueError("values and weights must be one-dimensional and aligned.")
        return torch.sum(values * weights)

    def _weighted_smooth_max(
        self,
        values: torch.Tensor,
        weights: torch.Tensor,
    ) -> torch.Tensor:
        # Weighted log-mean-exp. It equals x when all values are x and smoothly
        # approaches max(values) as temperature -> 0.
        tau = self.worst_step_temperature
        log_w = torch.log(weights.clamp_min(self.eps))
        return tau * torch.logsumexp(log_w + values / tau, dim=0)

    def _spectral_rank(
        self,
        centered: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Returns rank loss, effective rank, and relative effective rank.

        Args:
            centered: [B, K, P], centered over the batch axis.
        """
        B, K, P = centered.shape
        max_rank = min(B - 1, P)

        if max_rank <= 1:
            zero = centered.sum() * 0.0
            one = zero + 1.0
            return zero.expand(K), one.expand(K), one.expand(K)

        # Autocast would demote the Gram matmul to BF16 even after ``.float()``.
        # CUDA eigvalsh has no BF16 kernel, and spectral statistics are more
        # stable in FP32 regardless, so keep this small square calculation out
        # of the surrounding mixed-precision region.
        with torch.autocast(device_type=centered.device.type, enabled=False):
            x = centered.permute(1, 0, 2).float()  # [K, B, P]

            # Work in the smaller square space. Eigenvalues are squared singular
            # values, so sqrt recovers the singular-value spectrum used by e-rank.
            if B <= P:
                gram = x @ x.transpose(-1, -2)  # [K, B, B]
            else:
                gram = x.transpose(-1, -2) @ x  # [K, P, P]

            eigvals = torch.linalg.eigvalsh(gram).clamp_min(0.0)
        eigvals = eigvals[..., -max_rank:]

        # sqrt(e + eps) - sqrt(eps) keeps an exact zero at zero while avoiding
        # the singular derivative of sqrt at the origin.
        singular_values = (torch.sqrt(eigvals + self.eps) - math.sqrt(self.eps)).clamp_min(0.0)
        probabilities = singular_values / singular_values.sum(dim=-1, keepdim=True).clamp_min(
            self.eps
        )

        entropy = -torch.sum(
            probabilities * torch.log(probabilities.clamp_min(self.eps)),
            dim=-1,
        )
        max_entropy = math.log(float(max_rank))

        normalized_entropy = (entropy / max_entropy).clamp(0.0, 1.0)
        rank_loss = 1.0 - normalized_entropy
        effective_rank = torch.exp(entropy)
        relative_effective_rank = (effective_rank / max_rank).clamp(0.0, 1.0)

        return rank_loss, effective_rank, relative_effective_rank

    def forward(
        self,
        latents: torch.Tensor,
        h0: torch.Tensor,
        *,
        step_weights: torch.Tensor | None = None,
        compute_spectral: bool = True,
        contrastive_group_ids: torch.Tensor | None = None,
    ) -> dict[str, torch.Tensor]:
        """Compute latent-workspace regularization.

        Args:
            latents:
                Tensor [B, K, D], latent states h_1 ... h_K.
            h0:
                Tensor [B, D], state immediately before entering the workspace.
                It is always detached internally.
            step_weights:
                Optional non-negative tensor [K]. Uniform by default. A bell
                curve can emphasize the middle of the latent trajectory.
            compute_spectral:
                Skip the eigendecomposition when False. Useful for computing
                effective-rank loss only every N optimization steps.

        Returns:
            Dictionary of differentiable total loss and detached diagnostics.
        """
        self._validate_inputs(latents, h0)

        B, K, D = latents.shape
        if D != self.hidden_dim:
            raise ValueError(f"Expected hidden_dim={self.hidden_dim}, got D={D}.")

        weights = self._normalized_weights(K, latents.device, step_weights)

        # ------------------------------------------------------------------
        # 1. Geometry: variance and covariance in a projection space
        # ------------------------------------------------------------------
        z = self.geometry_projector(latents).float()  # [B, K, P]
        z_centered = z - z.mean(dim=0, keepdim=True)

        if B >= 2:
            # correction=0 semantics, written explicitly as a mean. This avoids
            # undefined B-1 variance while keeping the scale predictable.
            variance = z_centered.square().mean(dim=0)  # [K, P]
            std = torch.sqrt(variance + self.eps)
            var_by_step = F.relu(self.variance_target - std).mean(dim=-1)
            loss_var = self._weighted_mean(var_by_step, weights)

            covariance = torch.einsum("bkp,bkq->kpq", z_centered, z_centered) / float(B - 1)

            diagonal = torch.diag_embed(torch.diagonal(covariance, dim1=-2, dim2=-1))
            off_diagonal = covariance - diagonal
            denom = float(self.projection_dim * (self.projection_dim - 1))
            cov_by_step = off_diagonal.square().sum(dim=(-2, -1)) / denom
            loss_cov = self._weighted_mean(cov_by_step, weights)
        else:
            zero = z.sum() * 0.0
            std = torch.zeros(
                K,
                self.projection_dim,
                device=z.device,
                dtype=z.dtype,
            )
            var_by_step = torch.zeros(K, device=z.device, dtype=z.dtype)
            cov_by_step = torch.zeros(K, device=z.device, dtype=z.dtype)
            loss_var = zero
            loss_cov = zero

        # ------------------------------------------------------------------
        # 2. Information retention: shared backward-consistency probe
        # ------------------------------------------------------------------
        h0_target = F.layer_norm(h0.detach().float(), normalized_shape=(D,))  # [B, D]

        probe_input = self.probe_dropout(self.probe_norm(latents))
        h0_pred = self.probe(probe_input).float()  # [B, K, D]
        h0_pred = F.layer_norm(h0_pred, normalized_shape=(D,))

        target_expanded = h0_target[:, None, :].expand(B, K, D)
        info_per_item = F.smooth_l1_loss(
            h0_pred,
            target_expanded,
            reduction="none",
        ).mean(dim=-1)  # [B, K]
        info_by_step = info_per_item.mean(dim=0)
        loss_info = self._weighted_mean(info_by_step, weights)

        # The average can hide a single forgetting rupture. This term charges
        # only the excess of smooth-max over the mean, so it detects a fracture
        # without silently increasing the base reconstruction weight.
        smooth_worst = self._weighted_smooth_max(info_by_step, weights)
        loss_worst = (smooth_worst - loss_info).clamp_min(0.0)

        # ------------------------------------------------------------------
        # 3. Sample identity: group-masked contrastive recovery
        # ------------------------------------------------------------------
        pred_unit = F.normalize(h0_pred, dim=-1)
        target_unit = F.normalize(h0_target, dim=-1)

        if contrastive_group_ids is not None:
            if contrastive_group_ids.ndim != 1 or contrastive_group_ids.numel() != B:
                raise ValueError("contrastive_group_ids must have shape [B].")
            contrastive_group_ids = contrastive_group_ids.to(
                device=latents.device, dtype=torch.long
            )

        if B >= 2:
            pred_kbd = pred_unit.permute(1, 0, 2)  # [K, B, D]
            logits = (
                torch.einsum("kbd,cd->kbc", pred_kbd, target_unit) / self.contrastive_temperature
            )

            eye = torch.eye(B, device=latents.device, dtype=torch.bool)
            if contrastive_group_ids is None:
                allowed = torch.ones(B, B, device=latents.device, dtype=torch.bool)
            else:
                allowed = (contrastive_group_ids[:, None] != contrastive_group_ids[None, :]) | eye

            # Positives are always retained. Same-group off-diagonal items are
            # false negatives and receive no probability mass. Samples with no
            # external negative are excluded instead of manufacturing a loss.
            masked_logits = logits.masked_fill(~allowed.unsqueeze(0), float("-inf"))
            labels = torch.arange(B, device=latents.device)
            labels = labels.expand(K, B)
            valid_rows = allowed.sum(dim=-1) > 1

            forward_raw = F.cross_entropy(
                masked_logits.reshape(K * B, B),
                labels.reshape(K * B),
                reduction="none",
            ).view(K, B)
            reverse_raw = F.cross_entropy(
                masked_logits.transpose(-1, -2).reshape(K * B, B),
                labels.reshape(K * B),
                reduction="none",
            ).view(K, B)

            valid_weight = valid_rows.to(forward_raw.dtype).unsqueeze(0)
            denominator = valid_weight.sum(dim=-1).clamp_min(1.0)
            forward_mean = (forward_raw * valid_weight).sum(dim=-1) / denominator
            reverse_mean = (reverse_raw * valid_weight).sum(dim=-1) / denominator
            contrast_by_step = 0.5 * (forward_mean + reverse_mean)
            loss_contrast = self._weighted_mean(contrast_by_step, weights)
            contrastive_valid_fraction = valid_rows.float().mean()
            contrastive_negative_pairs = (allowed & ~eye).sum().float()
        else:
            contrast_by_step = torch.zeros(K, device=z.device, dtype=z.dtype)
            loss_contrast = z.sum() * 0.0
            contrastive_valid_fraction = z.sum() * 0.0
            contrastive_negative_pairs = z.sum() * 0.0

        # ------------------------------------------------------------------
        # 4. Relational retention: preserve batchwise semantic geometry
        # ------------------------------------------------------------------
        if B >= 2:
            target_gram = target_unit @ target_unit.transpose(0, 1)  # [B, B]
            pred_gram = pred_kbd @ pred_kbd.transpose(-1, -2)  # [K, B, B]

            relation_error = (pred_gram - target_gram.unsqueeze(0)).square()
            eye = torch.eye(B, device=latents.device, dtype=torch.bool)
            relation_by_step = relation_error[:, ~eye].mean(dim=-1)
            loss_relation = self._weighted_mean(relation_by_step, weights)
        else:
            relation_by_step = torch.zeros(K, device=z.device, dtype=z.dtype)
            loss_relation = z.sum() * 0.0

        # ------------------------------------------------------------------
        # 5. Temporal continuity: allow motion, penalize only abrupt drift
        # ------------------------------------------------------------------
        if K >= 2:
            z_unit = F.normalize(z, dim=-1)
            cosine_adjacent = torch.sum(z_unit[:, 1:, :] * z_unit[:, :-1, :], dim=-1)  # [B, K-1]
            drift = 1.0 - cosine_adjacent
            temporal_by_transition = F.relu(drift - self.temporal_drift_margin).square().mean(dim=0)

            transition_weights = 0.5 * (weights[1:] + weights[:-1])
            transition_weights = transition_weights / transition_weights.sum()
            loss_temporal = self._weighted_mean(temporal_by_transition, transition_weights)
            mean_temporal_drift = drift.mean()
            max_temporal_drift = drift.max()
        else:
            temporal_by_transition = torch.zeros(0, device=z.device, dtype=z.dtype)
            loss_temporal = z.sum() * 0.0
            mean_temporal_drift = z.sum() * 0.0
            max_temporal_drift = z.sum() * 0.0

        # ------------------------------------------------------------------
        # 6. Effective rank: a low-frequency global spectral guard
        # ------------------------------------------------------------------
        if compute_spectral and self.lambda_rank > 0 and B >= 2:
            rank_by_step, effective_rank_by_step, relative_rank_by_step = self._spectral_rank(
                z_centered
            )
            loss_rank = self._weighted_mean(rank_by_step, weights)
        else:
            rank_by_step = torch.zeros(K, device=z.device, dtype=z.dtype)
            effective_rank_by_step = torch.zeros(K, device=z.device, dtype=z.dtype)
            relative_rank_by_step = torch.zeros(K, device=z.device, dtype=z.dtype)
            loss_rank = z.sum() * 0.0

        total_loss = (
            self.lambda_var * loss_var
            + self.lambda_cov * loss_cov
            + self.lambda_info * loss_info
            + self.lambda_contrast * loss_contrast
            + self.lambda_relation * loss_relation
            + self.lambda_temporal * loss_temporal
            + self.lambda_worst * loss_worst
            + self.lambda_rank * loss_rank
        )

        with torch.no_grad():
            retention_cosine_by_step = torch.sum(pred_unit * target_unit[:, None, :], dim=-1).mean(
                dim=0
            )

            # Probe recovery can be perfect for a trajectory that never moved.
            # These raw-state diagnostics keep retention and departure separate.
            anchor_raw = h0.detach().float()
            latent_raw = latents.detach().float()
            anchor_unit_raw = F.normalize(anchor_raw, dim=-1)
            latent_unit_raw = F.normalize(latent_raw, dim=-1)
            state_anchor_cosine_by_step = torch.sum(
                latent_unit_raw * anchor_unit_raw[:, None, :], dim=-1
            ).mean(dim=0)
            departure_l2_by_step = (
                (latent_raw - anchor_raw[:, None, :]).norm(dim=-1) / math.sqrt(float(D))
            ).mean(dim=0)
            previous = torch.cat([anchor_raw[:, None, :], latent_raw[:, :-1, :]], dim=1)
            update_l2_by_step = ((latent_raw - previous).norm(dim=-1) / math.sqrt(float(D))).mean(
                dim=0
            )
            path_length = update_l2_by_step.sum()
            net_displacement = departure_l2_by_step[-1]
            tortuosity = path_length / net_displacement.clamp_min(self.eps)

            diagnostics = {
                "loss": total_loss,
                "loss_var": loss_var.detach(),
                "loss_cov": loss_cov.detach(),
                "loss_info": loss_info.detach(),
                "loss_contrast": loss_contrast.detach(),
                "loss_relation": loss_relation.detach(),
                "loss_temporal": loss_temporal.detach(),
                "loss_worst": loss_worst.detach(),
                "loss_rank": loss_rank.detach(),
                "mean_std": std.mean().detach(),
                "min_std": std.min().detach(),
                "retention_cosine": retention_cosine_by_step.mean().detach(),
                "mean_temporal_drift": mean_temporal_drift.detach(),
                "max_temporal_drift": max_temporal_drift.detach(),
                "effective_rank": effective_rank_by_step.mean().detach(),
                "relative_effective_rank": relative_rank_by_step.mean().detach(),
                "state_anchor_cosine": state_anchor_cosine_by_step.mean().detach(),
                "final_state_anchor_cosine": state_anchor_cosine_by_step[-1].detach(),
                "mean_departure_l2": departure_l2_by_step.mean().detach(),
                "final_departure_l2": departure_l2_by_step[-1].detach(),
                "mean_update_l2": update_l2_by_step.mean().detach(),
                "path_length": path_length.detach(),
                "net_displacement": net_displacement.detach(),
                "tortuosity": tortuosity.detach(),
                "contrastive_valid_fraction": contrastive_valid_fraction.detach(),
                "contrastive_negative_pairs": contrastive_negative_pairs.detach(),
                "spectral_computed": torch.tensor(
                    float(compute_spectral and self.lambda_rank > 0 and B >= 2),
                    device=latents.device,
                ),
                "info_by_step": info_by_step.detach(),
                "retention_cosine_by_step": retention_cosine_by_step.detach(),
                "state_anchor_cosine_by_step": state_anchor_cosine_by_step.detach(),
                "departure_l2_by_step": departure_l2_by_step.detach(),
                "update_l2_by_step": update_l2_by_step.detach(),
                "var_by_step": var_by_step.detach(),
                "cov_by_step": cov_by_step.detach(),
                "rank_by_step": rank_by_step.detach(),
                "temporal_by_transition": temporal_by_transition.detach(),
            }

        return diagnostics
