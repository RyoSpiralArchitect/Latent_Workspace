"""LatentWorkspace FT v11: portable query-deferred workspace harness.

The file intentionally keeps the latent workspace, regularizer, data path,
trainer, checkpoint protocol, distributed launcher integration, diagnostics,
and generation loader in one auditable implementation.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

import argparse
import copy
import contextlib
from collections import deque
import dataclasses
import datetime as _datetime
import glob
import hashlib
import inspect
import json
import math
import os
import platform
import random
import re
import shutil
import signal
import socket
import stat as stat_module
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, MutableMapping, Optional, Sequence

from torch.utils.data import BatchSampler, DataLoader, Dataset, Sampler, Subset


__version__ = "11.0.0"


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
        projection_dim: Optional[int] = None,
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
        step_weights: Optional[torch.Tensor],
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
        singular_values = (
            torch.sqrt(eigvals + self.eps) - math.sqrt(self.eps)
        ).clamp_min(0.0)
        probabilities = singular_values / singular_values.sum(
            dim=-1, keepdim=True
        ).clamp_min(self.eps)

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
        step_weights: Optional[torch.Tensor] = None,
        compute_spectral: bool = True,
        contrastive_group_ids: Optional[torch.Tensor] = None,
    ) -> Dict[str, torch.Tensor]:
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
            raise ValueError(
                f"Expected hidden_dim={self.hidden_dim}, got D={D}."
            )

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

            covariance = torch.einsum(
                "bkp,bkq->kpq", z_centered, z_centered
            ) / float(B - 1)

            diagonal = torch.diag_embed(
                torch.diagonal(covariance, dim1=-2, dim2=-1)
            )
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
        h0_target = F.layer_norm(
            h0.detach().float(), normalized_shape=(D,)
        )  # [B, D]

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
            logits = torch.einsum(
                "kbd,cd->kbc", pred_kbd, target_unit
            ) / self.contrastive_temperature

            eye = torch.eye(B, device=latents.device, dtype=torch.bool)
            if contrastive_group_ids is None:
                allowed = torch.ones(B, B, device=latents.device, dtype=torch.bool)
            else:
                allowed = (
                    contrastive_group_ids[:, None]
                    != contrastive_group_ids[None, :]
                ) | eye

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
            cosine_adjacent = torch.sum(
                z_unit[:, 1:, :] * z_unit[:, :-1, :], dim=-1
            )  # [B, K-1]
            drift = 1.0 - cosine_adjacent
            temporal_by_transition = F.relu(
                drift - self.temporal_drift_margin
            ).square().mean(dim=0)

            transition_weights = 0.5 * (weights[1:] + weights[:-1])
            transition_weights = transition_weights / transition_weights.sum()
            loss_temporal = self._weighted_mean(
                temporal_by_transition, transition_weights
            )
            mean_temporal_drift = drift.mean()
            max_temporal_drift = drift.max()
        else:
            temporal_by_transition = torch.zeros(
                0, device=z.device, dtype=z.dtype
            )
            loss_temporal = z.sum() * 0.0
            mean_temporal_drift = z.sum() * 0.0
            max_temporal_drift = z.sum() * 0.0

        # ------------------------------------------------------------------
        # 6. Effective rank: a low-frequency global spectral guard
        # ------------------------------------------------------------------
        if compute_spectral and self.lambda_rank > 0 and B >= 2:
            rank_by_step, effective_rank_by_step, relative_rank_by_step = (
                self._spectral_rank(z_centered)
            )
            loss_rank = self._weighted_mean(rank_by_step, weights)
        else:
            rank_by_step = torch.zeros(K, device=z.device, dtype=z.dtype)
            effective_rank_by_step = torch.zeros(
                K, device=z.device, dtype=z.dtype
            )
            relative_rank_by_step = torch.zeros(
                K, device=z.device, dtype=z.dtype
            )
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
            retention_cosine_by_step = torch.sum(
                pred_unit * target_unit[:, None, :], dim=-1
            ).mean(dim=0)

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
                (latent_raw - anchor_raw[:, None, :]).norm(dim=-1)
                / math.sqrt(float(D))
            ).mean(dim=0)
            previous = torch.cat([anchor_raw[:, None, :], latent_raw[:, :-1, :]], dim=1)
            update_l2_by_step = (
                (latent_raw - previous).norm(dim=-1) / math.sqrt(float(D))
            ).mean(dim=0)
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


# =============================================================================
# Fine-tuning configuration
# =============================================================================


@dataclass
class ModelConfig:
    name_or_path: str = "HuggingFaceTB/SmolLM2-135M-Instruct"
    revision: str = "main"
    trust_remote_code: bool = False
    dtype: str = "auto"  # auto | float32 | float16 | bfloat16
    train_mode: str = "full"  # full | workspace_only | lora
    gradient_checkpointing: bool = True
    hidden_capture: str = "hook"  # hook | hidden_states
    local_files_only: bool = False
    attn_implementation: str = "auto"  # auto | eager | sdpa | flash_attention_2

    # Optional PEFT LoRA path. Imported only when train_mode == "lora".
    lora_r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    lora_target_modules: str | list[str] = "all-linear"
    lora_use_rslora: bool = False


@dataclass
class DataConfig:
    train_files: list[str] = field(default_factory=lambda: ["demo_train.jsonl"])
    eval_files: list[str] = field(default_factory=lambda: ["demo_eval.jsonl"])
    max_length: int = 256
    train_on_prompt: bool = False
    use_chat_template: bool = True
    add_bos: bool = False
    add_eos: bool = True
    prompt_separator: str = "\n\n"
    response_prefix: str = ""
    pad_to_multiple_of: int = 8

    # Loader durability and throughput.
    num_workers: int = 0
    pin_memory: bool = True
    persistent_workers: bool = False
    prefetch_factor: int = 2
    loader_timeout_seconds: float = 0.0

    # Deterministic sortish batching. Length is estimated from JSONL byte size,
    # so startup does not require tokenizing the whole corpus.
    length_bucketing: bool = True
    bucket_size_multiplier: int = 50
    drop_last: bool = False
    shuffle_buffer_seed: int = 17

    # Cheap preflight and provenance fingerprinting. JSON syntax is checked
    # while offsets are indexed, before a multi-hour run can reach a bad line.
    validate_json_on_index: bool = True
    verify_samples: int = 32
    fingerprint_mode: str = "sampled"  # sampled | full
    fingerprint_bytes: int = 65536

    # v7 deferred-memory bridge tensors are derived by the collator from the
    # explicit context/query masks. Keeping them in every batch makes topology
    # switches auditable without changing the underlying tokenized corpus.
    emit_bridge_tensors: bool = True

    # v9 grouped-world records compute one context memory and reuse it across
    # several future queries. Context and query budgets are independent so a
    # truncation cannot silently erase the world while preserving the answer.
    functional_context_max_length: int = 192
    functional_query_max_length: int = 96
    functional_inline_max_length: int = 256
    functional_max_queries: int = 8
    functional_require_one_token_answer: bool = True


@dataclass
class WorkspaceLossConfig:
    projection_dim: int = 128
    variance_target: float = 1.0
    eps: float = 1e-4
    contrastive_temperature: float = 0.10
    worst_step_temperature: float = 0.10
    temporal_drift_margin: float = 0.20
    probe_dropout: float = 0.10
    lambda_var: float = 1.0
    lambda_cov: float = 1.0
    lambda_info: float = 0.5
    lambda_contrast: float = 0.25
    lambda_relation: float = 0.10
    lambda_temporal: float = 0.10
    lambda_worst: float = 0.25
    lambda_rank: float = 0.05


@dataclass
class WorkspaceConfig:
    steps: int = 4
    workspace_dim: int = 256
    ff_multiplier: float = 2.0
    dropout: float = 0.10

    # v5 can retain the v4.1 token-local refiner or activate a recurrent causal
    # broadcast channel over sequence positions. ``causal_window=1`` is a
    # parameter-matched self-only control; 0 means the full causal prefix.
    architecture: str = "causal_broadcast"  # token_local | causal_broadcast
    attention_heads: int = 8
    attention_dropout: float = 0.0
    causal_window: int = 0

    logit_rank: int = 32
    logit_residual_scale: float = 1.0
    gate_init_bias: float = -2.0

    # v7 separates the ordinary inline residual route from a deferred-memory
    # bridge. In deferred_bridge mode the query/response branch never receives
    # raw context tokens through the base transformer; context can affect task
    # logits only through workspace memory and the cross-attention bridge.
    route_topology: str = "inline"  # inline | deferred_bridge
    bridge_heads: int = 8
    bridge_dropout: float = 0.0

    # v8 separates the existence of a route from the semantic source carried
    # through it. ``workspace`` uses the final recurrent context state,
    # ``anchor`` uses the one-shot projected context state, and
    # ``fixed_carrier`` supplies a deterministic context-independent carrier.
    deferred_memory_source: str = "workspace"  # workspace | anchor | fixed_carrier
    # 1-based recurrent state exposed to the deferred bridge; -1 selects the
    # final state. Keeping K fixed while changing this index yields a
    # parameter-matched early-readout control.
    deferred_memory_step: int = -1
    fixed_carrier_tokens: int = 1

    # Diagnostic controls. The token-local v4 architecture can repeatedly
    # reread its initial anchor unless this is ablated. ``aux_backprop_to_base``
    # separates a local workspace regularizer from a regularizer that also
    # reshapes the base transformer's hidden states.
    anchor_refresh: str = "initial_only"  # every_step | first_step | initial_only
    aux_backprop_to_base: bool = True
    contrastive_negative_scope: str = "cross_world"  # all | cross_example | cross_world

    # Where auxiliary workspace states are sampled from. Deferred records add
    # context/query masks, so the auxiliary loss can be applied before the query.
    # all | prompt | prompt_tail | boundary | response | supervised |
    # context | context_tail | prequery_boundary | query
    scope: str = "prompt_tail"
    prompt_tail_tokens: int = 24
    tokens_per_example: int = 32
    max_tokens_per_batch: int = 256

    loss_weight: float = 0.02
    loss_warmup_steps: int = 100
    spectral_every: int = 8
    step_weighting: str = "uniform"  # uniform | middle
    middle_sigma: float = 0.45
    loss: WorkspaceLossConfig = field(default_factory=WorkspaceLossConfig)


@dataclass
class FunctionalWorkspaceConfig:
    """v9 query-deferred functional-memory contract.

    One paired world record contains two locally counterfactual contexts and a
    shared set of future queries. The context branch is evaluated once per
    world side; every query reuses the resulting memory.
    """

    enabled: bool = False
    route_mode: str = "deferred"  # query_only | deferred | inline
    boundary_layer: int = 6
    memory_mode: str = "raw_sequence"  # raw_sequence | projected_sequence | slots | fixed_carrier
    slot_count: int = 4
    writer_steps: int = 1
    reader_steps: int = 1
    writer_heads: int = 8
    reader_heads: int = 8
    dropout: float = 0.0
    readout_step: int = -1
    injection_scale: float = 1.0
    gate_init_bias: float = -2.0

    # v11 repairs the supervised objective without changing the functional
    # prompt, route, optimizer, or dataset. ``full_vocab`` is the v10 objective;
    # ``choice_normalized`` trains only the constrained answer decision; and
    # ``hybrid`` adds a preregistered amount of the old full-vocabulary NLL.
    task_objective: str = "full_vocab"  # full_vocab | choice_normalized | hybrid
    full_vocab_loss_weight: float = 0.0

    # O0/O1/O2/O3 objective matrix. Intact multi-query CE is always active.
    # Counterfactual CE applies only to queries whose answer changes under the
    # local twin edit; stability KL applies only to unaffected queries.
    counterfactual_weight: float = 0.0
    stability_weight: float = 0.0
    stability_temperature: float = 1.0

    minimum_queries_per_world: int = 4
    require_paired_worlds: bool = True
    require_affected_and_unaffected: bool = True

    # Fixed claim gates used by the v9 summarizer. They are screening
    # thresholds rather than natural constants and remain visible in reports.
    world_accuracy_threshold: float = 0.75
    affected_flip_threshold: float = 0.75
    unaffected_stability_threshold: float = 0.90
    heldout_query_threshold: float = 0.80


@dataclass
class TrainConfig:
    output_dir: str = "runs/latent-workspace-ft"
    seed: int = 42
    device: str = "auto"  # auto | cuda | mps | cpu
    epochs: int = 1
    max_steps: int = -1
    batch_size: int = 4
    eval_batch_size: int = 4
    gradient_accumulation_steps: int = 4
    gradient_accumulation_offload: str = "none"  # none | cpu | cpu_accumulate
    base_activation_offload: str = "legacy_functional"  # disabled | legacy_functional | all_base

    learning_rate: float = 2e-5
    workspace_learning_rate: float = 1e-4
    weight_decay: float = 0.10
    optimizer: str = "adamw"  # adamw | adafactor
    adam_beta1: float = 0.9
    adam_beta2: float = 0.95
    adam_eps: float = 1e-8
    fused_adamw: str = "auto"  # auto | true | false
    warmup_ratio: float = 0.03
    max_grad_norm: float = 1.0
    mixed_precision: str = "auto"  # auto | no | fp16 | bf16

    # CUDA math policy. These are applied before model construction.
    allow_tf32: bool = True
    matmul_precision: str = "high"  # highest | high | medium
    deterministic_algorithms: bool = False
    # Empty preserves the general-purpose engine default. Contracted CUDA runs
    # pin the exact PYTORCH_ALLOC_CONF value here so it becomes resume-bound.
    cuda_allocator_conf: str = ""

    # torchrun-aware single-node DDP. "auto" activates only when WORLD_SIZE>1.
    distributed: str = "auto"  # auto | none | ddp
    ddp_backend: str = "auto"  # auto | nccl | gloo
    ddp_timeout_minutes: int = 30
    ddp_find_unused_parameters: str = "auto"  # auto | true | false
    ddp_static_graph: bool = False

    log_every: int = 10
    eval_every: int = 100
    eval_at_start: bool = False
    save_every: int = 100
    save_every_minutes: float = 30.0
    eval_batches: int = 32

    # Resume/checkpoint policy.
    resume_from: str = "auto"  # none | auto | /path/to/checkpoint-N
    strict_resume: bool = True
    allow_schedule_extension: bool = False
    strict_source_resume: bool = True
    strict_torch_resume: bool = True
    keep_last_checkpoints: int = 3
    save_optimizer: bool = True
    save_frozen_base: bool = False
    max_shard_size: str = "5GB"
    minimum_free_disk_gb: float = 2.0
    checkpoint_headroom_ratio: float = 1.15

    # Long-run health policy.
    heartbeat_every_seconds: float = 60.0
    nonfinite_policy: str = "stop"  # stop | skip
    max_nonfinite_skips: int = 3
    log_memory: bool = True

    # Validation selection. Lower task loss is the default notion of "best".
    save_best: bool = True
    best_metric: str = "task_loss"
    greater_is_better: bool = False


@dataclass
class AttributionConfig:
    """Controls v6.0 attribution locks.

    Workspace and auxiliary stochastic operations can be assigned stateless RNG
    streams derived from (seed, rank, optimizer step, microbatch). This prevents
    an auxiliary forward from advancing the base model dropout stream. Gradient
    clipping can likewise be separated by parameter family so a local workspace
    gradient cannot silently rescale the base-model update.
    """

    isolate_rng_streams: bool = True
    # The deferred topology performs an additional base-model context pass.
    # It receives its own stateless stream so enabling the route cannot advance
    # the continuation branch's dropout sequence on the next microbatch.
    context_seed_offset: int = 500_009
    route_seed_offset: int = 1_000_003
    auxiliary_seed_offset: int = 2_000_003
    assay_seed_offset: int = 3_000_017
    clip_mode: str = "per_family"  # global | per_family
    base_max_grad_norm: float = 1.0
    workspace_max_grad_norm: float = 1.0


@dataclass
class InductionConfig:
    """Schedules a workspace-forming intervention and its subsequent washout."""

    enabled: bool = False
    schedule: str = "constant"  # constant | early_pulse | late_pulse | window
    start_fraction: float = 0.0
    end_fraction: float = 1.0
    start_step: int = -1
    end_step: int = -1
    ramp_up_steps: int = 0
    ramp_down_steps: int = 0
    bypass_workspace_when_inactive: bool = True
    save_phase_boundaries: bool = True


@dataclass
class RecruitmentConfig:
    """Frozen-trunk recruitability assay with an identifiability gate.

    v8 refuses to interpret a probe whose selected causal prefix maps the same
    token sequence to incompatible labels. The dataset-level Bayes ceiling is
    computed before hidden-state fitting, so a chance result cannot masquerade
    as evidence that a reserve is absent.
    """

    enabled: bool = False
    target: str = "rank_distance"  # rank_distance | answer_class
    scope: str = "prequery_boundary"  # prequery_boundary | context_mean | query_end
    ranks: list[int] = field(default_factory=lambda: [4, 16, 64])
    max_steps: int = 100
    batch_size: int = 32
    learning_rate: float = 1e-3
    weight_decay: float = 0.0
    eval_every: int = 10
    threshold: float = 0.75
    seed: int = 314_159
    train_files: list[str] = field(default_factory=list)
    eval_files: list[str] = field(default_factory=list)
    max_train_examples: int = 0
    max_eval_examples: int = 0
    save_probe_states: bool = False
    fail_on_nonidentifying: bool = True
    minimum_bayes_ceiling: float = 0.80
    minimum_ceiling_over_chance: float = 0.05


@dataclass
class NecessityConfig:
    """Evaluation-time causal interventions over deferred workspace memory.

    v8 distinguishes removal of semantic content from removal of the carrier
    itself. Counterfactual-twin replacement is enabled explicitly by the twin
    matrix rather than by every legacy deferred-memory experiment.
    """

    enabled: bool = False
    modes: list[str] = field(
        default_factory=lambda: [
            "intact",
            "hard_bypass",
            "zero",
            "mean",
            "global_mean",
            "fixed_carrier",
            "norm_matched_random",
            "sign_flip",
            "signed_permutation",
            "scale_025",
            "scale_050",
            "scale_100",
            "scale_200",
            "scale_400",
            "token_shuffle",
            "within_world_shuffle",
            "cross_world_shuffle",
        ]
    )
    seed: int = 271_828
    eval_batches: int = 0
    batch_size: int = 8
    mix_worlds: bool = True
    minimum_changed_fraction: float = 0.50
    require_deferred_bridge: bool = True
    run_choice_eval: bool = True
    require_counterfactual_pairs: bool = False


@dataclass
class ChoiceEvalConfig:
    """Constrained candidate scoring for exact task-level accuracy."""

    enabled: bool = True
    batch_size: int = 8
    max_records: int = 0
    score_normalization: str = "mean"  # mean | sum


@dataclass
class TransitionConfig:
    """v7 linear-response, dose-ledger, and transition-audit controls."""

    enabled: bool = True
    reference_weight: float = 0.02
    dose_multipliers: list[float] = field(
        default_factory=lambda: [0.25, 0.5, 1.0, 2.0, 4.0]
    )
    low_dose_max_multiplier: float = 1.0
    minimum_breakpoint_points: int = 3
    ledger_enabled: bool = True


@dataclass
class AssayConfig:
    """Post-training and in-training assays spanning induction and necessity."""

    amputation_eval: bool = True
    amputation_eval_every: int = 0
    gradient_alignment_every: int = 0
    gradient_alignment_eval_mode: bool = True
    gradient_alignment_max_groups: int = 128
    recruitment: RecruitmentConfig = field(default_factory=RecruitmentConfig)
    necessity: NecessityConfig = field(default_factory=NecessityConfig)
    choice_eval: ChoiceEvalConfig = field(default_factory=ChoiceEvalConfig)


@dataclass
class ExperimentConfig:
    model: ModelConfig = field(default_factory=ModelConfig)
    data: DataConfig = field(default_factory=DataConfig)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    functional: FunctionalWorkspaceConfig = field(default_factory=FunctionalWorkspaceConfig)
    train: TrainConfig = field(default_factory=TrainConfig)
    attribution: AttributionConfig = field(default_factory=AttributionConfig)
    induction: InductionConfig = field(default_factory=InductionConfig)
    transition: TransitionConfig = field(default_factory=TransitionConfig)
    assays: AssayConfig = field(default_factory=AssayConfig)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ExperimentConfig":
        allowed = {f.name for f in fields(cls)}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"Unknown top-level config keys: {sorted(unknown)}")

        model = _dataclass_from_dict(ModelConfig, raw.get("model", {}))
        data = _dataclass_from_dict(DataConfig, raw.get("data", {}))
        train = _dataclass_from_dict(TrainConfig, raw.get("train", {}))
        attribution = _dataclass_from_dict(
            AttributionConfig, raw.get("attribution", {})
        )
        induction = _dataclass_from_dict(InductionConfig, raw.get("induction", {}))
        transition = _dataclass_from_dict(
            TransitionConfig, raw.get("transition", {})
        )

        workspace_raw = dict(raw.get("workspace", {}))
        loss_raw = workspace_raw.pop("loss", {})
        workspace = _dataclass_from_dict(WorkspaceConfig, workspace_raw)
        workspace.loss = _dataclass_from_dict(WorkspaceLossConfig, loss_raw)
        functional = _dataclass_from_dict(
            FunctionalWorkspaceConfig, raw.get("functional", {})
        )

        assays_raw = dict(raw.get("assays", {}))
        recruitment_raw = assays_raw.pop("recruitment", {})
        necessity_raw = assays_raw.pop("necessity", {})
        choice_raw = assays_raw.pop("choice_eval", {})
        assays = _dataclass_from_dict(AssayConfig, assays_raw)
        assays.recruitment = _dataclass_from_dict(
            RecruitmentConfig, recruitment_raw
        )
        assays.necessity = _dataclass_from_dict(NecessityConfig, necessity_raw)
        assays.choice_eval = _dataclass_from_dict(ChoiceEvalConfig, choice_raw)

        cfg = cls(
            model=model,
            data=data,
            workspace=workspace,
            functional=functional,
            train=train,
            attribution=attribution,
            induction=induction,
            transition=transition,
            assays=assays,
        )
        cfg.validate()
        return cfg

    @classmethod
    def from_json(cls, path: str | os.PathLike[str]) -> "ExperimentConfig":
        config_path = Path(path).expanduser().resolve()
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        cfg = cls.from_dict(raw)
        cfg.resolve_paths(config_path.parent)
        return cfg

    def to_json(self, path: str | os.PathLike[str]) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def resolve_paths(self, base_dir: Path) -> None:
        self.data.train_files = [
            str(_resolve_relative_path(p, base_dir)) for p in self.data.train_files
        ]
        self.data.eval_files = [
            str(_resolve_relative_path(p, base_dir)) for p in self.data.eval_files
        ]
        self.train.output_dir = str(_resolve_relative_path(self.train.output_dir, base_dir))
        self.assays.recruitment.train_files = [
            str(_resolve_relative_path(p, base_dir))
            for p in self.assays.recruitment.train_files
        ]
        self.assays.recruitment.eval_files = [
            str(_resolve_relative_path(p, base_dir))
            for p in self.assays.recruitment.eval_files
        ]
        resume = str(self.train.resume_from).strip()
        if resume not in {"", "none", "auto"}:
            self.train.resume_from = str(_resolve_relative_path(resume, base_dir))

    def validate(self) -> None:
        if self.model.train_mode not in {"full", "workspace_only", "lora"}:
            raise ValueError("model.train_mode must be full, workspace_only, or lora.")
        if self.model.hidden_capture not in {"hook", "hidden_states"}:
            raise ValueError("model.hidden_capture must be hook or hidden_states.")
        if self.model.attn_implementation not in {
            "auto",
            "eager",
            "sdpa",
            "flash_attention_2",
        }:
            raise ValueError("Unsupported model.attn_implementation.")
        if self.data.max_length < 8:
            raise ValueError("data.max_length must be at least 8.")
        if self.data.pad_to_multiple_of < 1:
            raise ValueError("data.pad_to_multiple_of must be positive.")
        if self.data.num_workers < 0:
            raise ValueError("data.num_workers must be non-negative.")
        if self.data.prefetch_factor < 1:
            raise ValueError("data.prefetch_factor must be positive.")
        if self.data.loader_timeout_seconds < 0:
            raise ValueError("data.loader_timeout_seconds must be non-negative.")
        if self.data.bucket_size_multiplier < 1:
            raise ValueError("data.bucket_size_multiplier must be positive.")
        if self.data.verify_samples < 0:
            raise ValueError("data.verify_samples must be non-negative.")
        if self.data.fingerprint_mode not in {"sampled", "full"}:
            raise ValueError("data.fingerprint_mode must be sampled or full.")
        if self.data.fingerprint_mode == "sampled" and self.data.fingerprint_bytes < 1:
            raise ValueError("sampled fingerprints require fingerprint_bytes >= 1.")
        if self.data.fingerprint_bytes < 0:
            raise ValueError("data.fingerprint_bytes must be non-negative.")
        if self.workspace.steps < 1:
            raise ValueError("workspace.steps must be positive.")
        if self.workspace.workspace_dim < 2:
            raise ValueError("workspace.workspace_dim must be at least 2.")
        if self.workspace.architecture not in {"token_local", "causal_broadcast"}:
            raise ValueError(
                "workspace.architecture must be token_local or causal_broadcast."
            )
        if self.workspace.attention_heads < 1:
            raise ValueError("workspace.attention_heads must be positive.")
        if self.workspace.workspace_dim % self.workspace.attention_heads != 0:
            raise ValueError(
                "workspace.workspace_dim must be divisible by attention_heads."
            )
        if not 0.0 <= self.workspace.attention_dropout < 1.0:
            raise ValueError("workspace.attention_dropout must be in [0, 1).")
        if self.workspace.causal_window < 0:
            raise ValueError("workspace.causal_window must be non-negative.")
        if self.workspace.logit_rank < 1:
            raise ValueError("workspace.logit_rank must be positive.")
        if self.workspace.logit_residual_scale < 0:
            raise ValueError("workspace.logit_residual_scale must be non-negative.")
        if self.workspace.route_topology not in {
            "inline", "deferred_bridge", "functional_workspace"
        }:
            raise ValueError(
                "workspace.route_topology must be inline, deferred_bridge, or "
                "functional_workspace."
            )
        if self.workspace.bridge_heads < 1:
            raise ValueError("workspace.bridge_heads must be positive.")
        if self.workspace.workspace_dim % self.workspace.bridge_heads != 0:
            raise ValueError(
                "workspace.workspace_dim must be divisible by bridge_heads."
            )
        if not 0.0 <= self.workspace.bridge_dropout < 1.0:
            raise ValueError("workspace.bridge_dropout must be in [0, 1).")
        if self.workspace.deferred_memory_source not in {
            "workspace", "anchor", "fixed_carrier"
        }:
            raise ValueError(
                "workspace.deferred_memory_source must be workspace, anchor, "
                "or fixed_carrier."
            )
        if self.workspace.deferred_memory_step != -1 and not (
            1 <= self.workspace.deferred_memory_step <= self.workspace.steps
        ):
            raise ValueError(
                "workspace.deferred_memory_step must be -1 or a 1-based "
                "step no greater than workspace.steps."
            )
        if self.workspace.fixed_carrier_tokens < 1:
            raise ValueError("workspace.fixed_carrier_tokens must be positive.")
        if self.workspace.anchor_refresh not in {
            "every_step",
            "first_step",
            "initial_only",
        }:
            raise ValueError(
                "workspace.anchor_refresh must be every_step, first_step, or initial_only."
            )
        if self.workspace.contrastive_negative_scope not in {
            "all",
            "cross_example",
            "cross_world",
        }:
            raise ValueError(
                "workspace.contrastive_negative_scope must be all, "
                "cross_example, or cross_world."
            )
        if self.workspace.scope not in {
            "all",
            "prompt",
            "prompt_tail",
            "boundary",
            "response",
            "supervised",
            "context",
            "context_tail",
            "prequery_boundary",
            "query",
        }:
            raise ValueError("Unsupported workspace.scope.")
        if self.workspace.step_weighting not in {"uniform", "middle"}:
            raise ValueError("workspace.step_weighting must be uniform or middle.")
        if self.workspace.loss_weight < 0:
            raise ValueError("workspace.loss_weight must be non-negative.")
        if (
            self.model.train_mode == "workspace_only"
            and self.workspace.loss_weight == 0.0
            and self.workspace.logit_residual_scale == 0.0
            and not self.functional.enabled
        ):
            raise ValueError(
                "workspace_only has no trainable objective when both workspace "
                "loss and logit residual are disabled."
            )
        if self.data.functional_context_max_length < 2:
            raise ValueError("functional_context_max_length must be at least 2.")
        if self.data.functional_query_max_length < 2:
            raise ValueError("functional_query_max_length must be at least 2.")
        if self.data.functional_inline_max_length < 2:
            raise ValueError("functional_inline_max_length must be at least 2.")
        if self.data.functional_max_queries < 1:
            raise ValueError("functional_max_queries must be positive.")
        if self.functional.route_mode not in {"query_only", "deferred", "inline"}:
            raise ValueError("functional.route_mode must be query_only, deferred, or inline.")
        if self.functional.memory_mode not in {
            "raw_sequence", "projected_sequence", "slots", "fixed_carrier"
        }:
            raise ValueError(
                "functional.memory_mode must be raw_sequence, projected_sequence, "
                "slots, or fixed_carrier."
            )
        if self.functional.boundary_layer < 0:
            raise ValueError("functional.boundary_layer must be non-negative.")
        if self.functional.slot_count < 1:
            raise ValueError("functional.slot_count must be positive.")
        if self.functional.writer_steps < 1 or self.functional.reader_steps < 1:
            raise ValueError("functional writer/reader steps must be positive.")
        if self.functional.writer_heads < 1 or self.functional.reader_heads < 1:
            raise ValueError("functional writer/reader heads must be positive.")
        if self.workspace.workspace_dim % self.functional.writer_heads != 0:
            raise ValueError("workspace_dim must be divisible by functional.writer_heads.")
        if not 0.0 <= self.functional.dropout < 1.0:
            raise ValueError("functional.dropout must be in [0, 1).")
        if self.functional.readout_step != -1 and not (
            1 <= self.functional.readout_step <= self.functional.writer_steps
        ):
            raise ValueError(
                "functional.readout_step must be -1 or a 1-based writer step."
            )
        if self.functional.injection_scale < 0:
            raise ValueError("functional.injection_scale must be non-negative.")
        if self.functional.task_objective not in {
            "full_vocab",
            "choice_normalized",
            "hybrid",
        }:
            raise ValueError(
                "functional.task_objective must be full_vocab, "
                "choice_normalized, or hybrid."
            )
        if self.functional.full_vocab_loss_weight < 0:
            raise ValueError(
                "functional.full_vocab_loss_weight must be non-negative."
            )
        if (
            self.functional.task_objective == "hybrid"
            and self.functional.full_vocab_loss_weight <= 0
        ):
            raise ValueError(
                "functional.task_objective='hybrid' requires a positive "
                "full_vocab_loss_weight."
            )
        if self.functional.counterfactual_weight < 0 or self.functional.stability_weight < 0:
            raise ValueError("functional objective weights must be non-negative.")
        if self.functional.stability_temperature <= 0:
            raise ValueError("functional.stability_temperature must be positive.")
        if self.functional.minimum_queries_per_world < 1:
            raise ValueError("functional.minimum_queries_per_world must be positive.")
        for name, value in {
            "world_accuracy_threshold": self.functional.world_accuracy_threshold,
            "affected_flip_threshold": self.functional.affected_flip_threshold,
            "unaffected_stability_threshold": self.functional.unaffected_stability_threshold,
            "heldout_query_threshold": self.functional.heldout_query_threshold,
        }.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"functional.{name} must be in [0, 1].")
        if self.workspace.route_topology == "functional_workspace" and not self.functional.enabled:
            raise ValueError(
                "route_topology='functional_workspace' requires functional.enabled=true."
            )
        if self.functional.enabled and self.workspace.route_topology != "functional_workspace":
            raise ValueError(
                "functional.enabled=true requires workspace.route_topology='functional_workspace'."
            )
        if self.train.batch_size < 1 or self.train.eval_batch_size < 1:
            raise ValueError("Batch sizes must be positive.")
        if self.train.learning_rate <= 0 or self.train.workspace_learning_rate <= 0:
            raise ValueError("Learning rates must be positive.")
        if self.train.weight_decay < 0:
            raise ValueError("weight_decay must be non-negative.")
        if self.train.optimizer not in {"adamw", "adafactor"}:
            raise ValueError("train.optimizer must be adamw or adafactor.")
        if not 0.0 <= self.train.warmup_ratio <= 1.0:
            raise ValueError("warmup_ratio must be in [0, 1].")
        if self.train.max_grad_norm <= 0:
            raise ValueError("max_grad_norm must be positive.")
        if self.train.gradient_accumulation_steps < 1:
            raise ValueError("gradient_accumulation_steps must be positive.")
        if self.train.gradient_accumulation_offload not in {
            "none",
            "cpu",
            "cpu_accumulate",
        }:
            raise ValueError(
                "train.gradient_accumulation_offload must be none, cpu, "
                "or cpu_accumulate."
            )
        if self.train.base_activation_offload not in {
            "disabled",
            "legacy_functional",
            "all_base",
        }:
            raise ValueError(
                "train.base_activation_offload must be disabled, "
                "legacy_functional, or all_base."
            )
        if self.train.epochs < 1 and self.train.max_steps < 1:
            raise ValueError("Set epochs >= 1 or max_steps >= 1.")
        if self.train.fused_adamw not in {"auto", "true", "false"}:
            raise ValueError("train.fused_adamw must be auto, true, or false.")
        if self.train.optimizer == "adafactor" and self.train.fused_adamw == "true":
            raise ValueError(
                "train.fused_adamw=true is valid only with train.optimizer='adamw'."
            )
        if self.train.matmul_precision not in {"highest", "high", "medium"}:
            raise ValueError("Unsupported train.matmul_precision.")
        if not isinstance(self.train.cuda_allocator_conf, str):
            raise ValueError("train.cuda_allocator_conf must be a string.")
        if self.train.cuda_allocator_conf != self.train.cuda_allocator_conf.strip():
            raise ValueError(
                "train.cuda_allocator_conf must not contain surrounding whitespace."
            )
        if self.train.distributed not in {"auto", "none", "ddp"}:
            raise ValueError("train.distributed must be auto, none, or ddp.")
        if self.train.ddp_backend not in {"auto", "nccl", "gloo"}:
            raise ValueError("Unsupported train.ddp_backend.")
        if self.train.ddp_timeout_minutes < 1:
            raise ValueError("ddp_timeout_minutes must be positive.")
        if self.train.ddp_find_unused_parameters not in {"auto", "true", "false"}:
            raise ValueError(
                "ddp_find_unused_parameters must be auto, true, or false."
            )
        if self.train.save_every_minutes < 0:
            raise ValueError("save_every_minutes must be non-negative.")
        if self.train.keep_last_checkpoints < 0:
            raise ValueError("keep_last_checkpoints must be non-negative.")
        if self.train.minimum_free_disk_gb < 0:
            raise ValueError("minimum_free_disk_gb must be non-negative.")
        if self.train.checkpoint_headroom_ratio < 1.0:
            raise ValueError("checkpoint_headroom_ratio must be at least 1.0.")
        if self.train.heartbeat_every_seconds < 0:
            raise ValueError("heartbeat_every_seconds must be non-negative.")
        if self.train.nonfinite_policy not in {"stop", "skip"}:
            raise ValueError("nonfinite_policy must be stop or skip.")
        if self.train.max_nonfinite_skips < 0:
            raise ValueError("max_nonfinite_skips must be non-negative.")
        if self.attribution.clip_mode not in {"global", "per_family"}:
            raise ValueError("attribution.clip_mode must be global or per_family.")
        if self.attribution.base_max_grad_norm <= 0:
            raise ValueError("attribution.base_max_grad_norm must be positive.")
        if self.attribution.workspace_max_grad_norm <= 0:
            raise ValueError("attribution.workspace_max_grad_norm must be positive.")
        if self.induction.schedule not in {
            "constant", "early_pulse", "late_pulse", "window"
        }:
            raise ValueError("Unsupported induction.schedule.")
        if not 0.0 <= self.induction.start_fraction <= 1.0:
            raise ValueError("induction.start_fraction must be in [0, 1].")
        if not 0.0 <= self.induction.end_fraction <= 1.0:
            raise ValueError("induction.end_fraction must be in [0, 1].")
        if self.induction.start_step < -1 or self.induction.end_step < -1:
            raise ValueError("induction start/end steps must be -1 or non-negative.")
        if self.induction.ramp_up_steps < 0 or self.induction.ramp_down_steps < 0:
            raise ValueError("induction ramp steps must be non-negative.")
        dynamic_induction_graph = bool(
            self.induction.enabled
            and (
                self.induction.schedule != "constant"
                or self.induction.start_step >= 0
                or self.induction.end_step >= 0
            )
        )
        if dynamic_induction_graph and self.train.ddp_static_graph:
            raise ValueError(
                "Scheduled induction changes parameter usage across the run and is "
                "incompatible with train.ddp_static_graph=true."
            )
        if (
            dynamic_induction_graph
            and self.train.ddp_find_unused_parameters == "false"
        ):
            raise ValueError(
                "Scheduled induction requires DDP unused-parameter detection during "
                "inactive phases; use ddp_find_unused_parameters='auto' or 'true'."
            )
        if self.assays.amputation_eval_every < 0:
            raise ValueError("assays.amputation_eval_every must be non-negative.")
        if self.assays.gradient_alignment_every < 0:
            raise ValueError("gradient_alignment_every must be non-negative.")
        if self.assays.gradient_alignment_max_groups < 1:
            raise ValueError("gradient_alignment_max_groups must be positive.")
        supported_interventions = {
            "intact",
            "hard_bypass",
            "zero",
            "mean",
            "global_mean",
            "fixed_carrier",
            "global_fixed",  # backward-compatible alias
            "norm_matched_random",
            "random_matched",  # backward-compatible alias
            "sign_flip",
            "signed_permutation",
            "feature_permute",  # backward-compatible alias
            "scale_025",
            "scale_050",
            "scale_100",
            "scale_200",
            "scale_400",
            "token_shuffle",
            "within_world_shuffle",
            "cross_world_shuffle",
            "counterfactual_twin",
        }
        unknown_interventions = set(self.assays.necessity.modes) - supported_interventions
        if unknown_interventions:
            raise ValueError(
                f"Unsupported necessity modes: {sorted(unknown_interventions)}"
            )
        if "intact" not in self.assays.necessity.modes:
            raise ValueError("necessity.modes must include intact.")
        if self.assays.necessity.eval_batches < 0:
            raise ValueError("necessity.eval_batches must be non-negative.")
        if self.assays.necessity.batch_size < 2:
            raise ValueError("necessity.batch_size must be at least 2.")
        if not 0.0 <= self.assays.necessity.minimum_changed_fraction <= 1.0:
            raise ValueError(
                "necessity.minimum_changed_fraction must be in [0, 1]."
            )
        if self.assays.choice_eval.batch_size < 1:
            raise ValueError("choice_eval.batch_size must be positive.")
        if self.assays.choice_eval.max_records < 0:
            raise ValueError("choice_eval.max_records must be non-negative.")
        if self.assays.choice_eval.score_normalization not in {"mean", "sum"}:
            raise ValueError("choice_eval.score_normalization must be mean or sum.")
        if self.transition.reference_weight < 0:
            raise ValueError("transition.reference_weight must be non-negative.")
        if any(value < 0 for value in self.transition.dose_multipliers):
            raise ValueError("transition.dose_multipliers must be non-negative.")
        if self.transition.low_dose_max_multiplier < 0:
            raise ValueError(
                "transition.low_dose_max_multiplier must be non-negative."
            )
        if self.transition.minimum_breakpoint_points < 2:
            raise ValueError(
                "transition.minimum_breakpoint_points must be at least 2."
            )

        recruitment = self.assays.recruitment
        if recruitment.target not in {"rank_distance", "answer_class"}:
            raise ValueError(
                "recruitment.target must be rank_distance or answer_class."
            )
        if recruitment.scope not in {
            "prequery_boundary", "context_mean", "query_end"
        }:
            raise ValueError("Unsupported recruitment.scope.")
        if not recruitment.ranks or any(rank < 0 for rank in recruitment.ranks):
            raise ValueError("recruitment.ranks must contain non-negative integers.")
        if recruitment.max_steps < 1 or recruitment.batch_size < 1:
            raise ValueError("Recruitment steps and batch size must be positive.")
        if recruitment.learning_rate <= 0 or recruitment.weight_decay < 0:
            raise ValueError("Invalid recruitment optimizer settings.")
        if recruitment.eval_every < 1:
            raise ValueError("recruitment.eval_every must be positive.")
        if not 0.0 <= recruitment.threshold <= 1.0:
            raise ValueError("recruitment.threshold must be in [0, 1].")
        if not 0.0 <= recruitment.minimum_bayes_ceiling <= 1.0:
            raise ValueError("minimum_bayes_ceiling must be in [0, 1].")
        if not 0.0 <= recruitment.minimum_ceiling_over_chance <= 1.0:
            raise ValueError("minimum_ceiling_over_chance must be in [0, 1].")


def _dataclass_from_dict(cls: type[Any], raw: Mapping[str, Any]) -> Any:
    valid = {f.name for f in fields(cls)}
    unknown = set(raw) - valid
    if unknown:
        raise ValueError(f"Unknown {cls.__name__} keys: {sorted(unknown)}")
    return cls(**dict(raw))


def _resolve_relative_path(value: str, base_dir: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base_dir / path).resolve()


def stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_write_text(
        path,
        json.dumps(dict(payload), indent=2, ensure_ascii=False) + "\n",
    )


def _fsync_directory(path: Path) -> None:
    """Best-effort directory metadata flush after an atomic rename."""
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _full_file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(8 * 1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _sampled_file_digest(path: Path, sample_bytes: int) -> str:
    """Hash deterministic windows across a potentially large file.

    Unlike a head/tail-only fingerprint, this samples four evenly spaced
    regions.  It remains a probabilistic identity check; set
    ``fingerprint_mode='full'`` when exact corpus provenance is worth the
    startup I/O.
    """
    stat = path.stat()
    hasher = hashlib.sha256()
    hasher.update(str(stat.st_size).encode("ascii"))
    if stat.st_size == 0:
        return hasher.hexdigest()

    width = min(int(sample_bytes), int(stat.st_size))
    maximum_offset = max(0, int(stat.st_size) - width)
    offsets = sorted(
        {
            0,
            maximum_offset // 3,
            (2 * maximum_offset) // 3,
            maximum_offset,
        }
    )
    with path.open("rb") as handle:
        for offset in offsets:
            handle.seek(offset)
            hasher.update(str(offset).encode("ascii"))
            hasher.update(handle.read(width))
    return hasher.hexdigest()


def fingerprint_files(
    paths: Sequence[Path],
    sample_bytes: int,
    mode: str = "sampled",
) -> dict[str, Any]:
    if mode not in {"sampled", "full"}:
        raise ValueError("fingerprint mode must be sampled or full.")

    provenance: list[dict[str, Any]] = []
    identity: list[dict[str, Any]] = []
    for index, path in enumerate(paths):
        resolved = path.expanduser().resolve()
        stat = resolved.stat()
        digest = (
            _full_file_digest(resolved)
            if mode == "full"
            else _sampled_file_digest(resolved, sample_bytes)
        )
        item_identity = {
            "index": index,
            "size": int(stat.st_size),
            "content_sha256": digest,
        }
        identity.append(item_identity)
        provenance.append(
            {
                **item_identity,
                "path": str(resolved),
                "mtime_ns": int(stat.st_mtime_ns),
            }
        )
    return {
        "files": provenance,
        "identity_sha256": stable_hash({"files": identity, "mode": mode}),
        "mode": mode,
        "sample_bytes": int(sample_bytes),
    }


def _same_data_fingerprint(
    saved: Mapping[str, Any],
    current: Mapping[str, Any],
) -> bool:
    saved_identity = saved.get("identity_sha256") or saved.get("aggregate_sha256")
    current_identity = current.get("identity_sha256") or current.get("aggregate_sha256")
    return bool(saved_identity) and saved_identity == current_identity


def source_sha256() -> str:
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError:
        return "unavailable"


def allocator_runtime_environment() -> dict[str, Any]:
    """Observe the allocator policy without silently mutating it.

    PyTorch 2.13 documents ``PYTORCH_ALLOC_CONF`` as the primary setting while
    retaining device-specific compatibility aliases. Those aliases can win
    when several variables are present, and disabling the caching allocator
    bypasses the policy entirely, so contracted runs require all three override
    channels below to be absent.
    """

    result: dict[str, Any] = {
        "pytorch_alloc_conf": os.environ.get("PYTORCH_ALLOC_CONF"),
        "pytorch_cuda_alloc_conf_legacy": os.environ.get(
            "PYTORCH_CUDA_ALLOC_CONF"
        ),
        "pytorch_hip_alloc_conf_legacy": os.environ.get(
            "PYTORCH_HIP_ALLOC_CONF"
        ),
        "pytorch_no_cuda_memory_caching": os.environ.get(
            "PYTORCH_NO_CUDA_MEMORY_CACHING"
        ),
        "allocator_backend": None,
        "allocator_settings": None,
        "allocator_initialized": None,
        "allocator_snapshot_settings": None,
        "cuda_memory_allocated_bytes": None,
        "cuda_memory_reserved_bytes": None,
    }
    try:
        result["allocator_backend"] = torch.cuda.memory.get_allocator_backend()
    except Exception as exc:
        result["allocator_backend_error"] = f"{type(exc).__name__}: {exc}"
    try:
        getter = getattr(torch._C, "_accelerator_getAllocatorSettings", None)
        if getter is not None:
            result["allocator_settings"] = getter()
    except Exception as exc:
        result["allocator_settings_error"] = f"{type(exc).__name__}: {exc}"
    try:
        initialized = getattr(torch._C, "_accelerator_isAllocatorInitialized", None)
        if initialized is not None:
            result["allocator_initialized"] = bool(initialized())
    except Exception as exc:
        result["allocator_initialized_error"] = f"{type(exc).__name__}: {exc}"
    if result["allocator_initialized"] is True:
        try:
            snapshot = torch.cuda.memory._snapshot()
            settings = snapshot.get("allocator_settings")
            if isinstance(settings, Mapping):
                result["allocator_snapshot_settings"] = {
                    "expandable_segments": settings.get("expandable_segments"),
                    "max_split_size": settings.get("max_split_size"),
                    "garbage_collection_threshold": settings.get(
                        "garbage_collection_threshold"
                    ),
                }
            result["cuda_memory_allocated_bytes"] = int(
                torch.cuda.memory_allocated()
            )
            result["cuda_memory_reserved_bytes"] = int(
                torch.cuda.memory_reserved()
            )
        except Exception as exc:
            result["allocator_snapshot_error"] = f"{type(exc).__name__}: {exc}"
    return result


def require_cuda_allocator_policy(train: TrainConfig) -> None:
    """Fail closed before CUDA initialization when a config pins a policy."""

    expected = train.cuda_allocator_conf
    if not expected:
        return
    forbidden = {
        name: os.environ.get(name)
        for name in (
            "PYTORCH_CUDA_ALLOC_CONF",
            "PYTORCH_HIP_ALLOC_CONF",
            "PYTORCH_NO_CUDA_MEMORY_CACHING",
        )
        if os.environ.get(name) is not None
    }
    if forbidden:
        raise RuntimeError(
            "Contracted CUDA allocator policy forbids compatibility aliases and "
            "the caching-allocator disable switch because they can override or "
            f"disable PYTORCH_ALLOC_CONF: {sorted(forbidden)}."
        )
    actual = os.environ.get("PYTORCH_ALLOC_CONF")
    if actual != expected:
        raise RuntimeError(
            "Contracted CUDA allocator policy mismatch: "
            f"PYTORCH_ALLOC_CONF={actual!r}, expected {expected!r}."
        )


def require_effective_cuda_allocator_policy(
    train: TrainConfig,
    device: torch.device,
) -> dict[str, Any]:
    """Verify the CUDA allocator after live model allocations exist."""

    observation = allocator_runtime_environment()
    if not train.cuda_allocator_conf or device.type != "cuda":
        return observation
    configured: dict[str, str] = {}
    for item in train.cuda_allocator_conf.split(","):
        key, separator, value = item.partition(":")
        if separator:
            configured[key.strip()] = value.strip()
    snapshot = observation.get("allocator_snapshot_settings")
    failures: list[str] = []
    if observation.get("pytorch_alloc_conf") != train.cuda_allocator_conf:
        failures.append("primary_environment")
    for key in (
        "pytorch_cuda_alloc_conf_legacy",
        "pytorch_hip_alloc_conf_legacy",
        "pytorch_no_cuda_memory_caching",
    ):
        if observation.get(key) is not None:
            failures.append(key)
    expected_backend = configured.get("backend")
    if expected_backend and observation.get("allocator_backend") != expected_backend:
        failures.append("allocator_backend")
    if observation.get("allocator_settings") != train.cuda_allocator_conf:
        failures.append("parsed_settings")
    expected_expandable = configured.get("expandable_segments")
    if expected_expandable is not None:
        expected_enabled = expected_expandable.lower() == "true"
        if not isinstance(snapshot, Mapping) or snapshot.get(
            "expandable_segments"
        ) is not expected_enabled:
            failures.append("snapshot_expandable_segments")
    allocated = observation.get("cuda_memory_allocated_bytes")
    if (
        observation.get("allocator_initialized") is not True
        or isinstance(allocated, bool)
        or not isinstance(allocated, int)
        or allocated <= 0
    ):
        failures.append("live_cuda_allocation")
    if failures:
        raise RuntimeError(
            "Effective CUDA allocator policy validation failed after model allocation: "
            f"{sorted(set(failures))}."
        )
    return observation


def runtime_environment() -> dict[str, Any]:
    result: dict[str, Any] = {
        "harness_version": __version__,
        "python": sys.version,
        "platform": platform.platform(),
        "hostname": socket.gethostname(),
        "torch": torch.__version__,
        "cuda_runtime": getattr(torch.version, "cuda", None),
        "cudnn": (
            torch.backends.cudnn.version()
            if getattr(torch.backends, "cudnn", None) is not None
            else None
        ),
        "source_sha256": source_sha256(),
        **allocator_runtime_environment(),
    }
    if torch.cuda.is_available():
        result["cuda_devices"] = [
            {
                "index": index,
                "name": torch.cuda.get_device_name(index),
                "capability": list(torch.cuda.get_device_capability(index)),
                "total_memory": int(torch.cuda.get_device_properties(index).total_memory),
            }
            for index in range(torch.cuda.device_count())
        ]
    for package_name in ("transformers", "peft", "safetensors"):
        try:
            module = __import__(package_name)
            result[package_name] = getattr(module, "__version__", "unknown")
        except Exception:
            result[package_name] = None
    return result


def resume_signature(
    config: "ExperimentConfig",
    *,
    ignore_schedule_horizon: bool = False,
) -> str:
    """Hash fields that must remain stable for optimizer continuation.

    The exact signature includes the schedule horizon.  A second structural
    signature may deliberately ignore ``epochs`` and ``max_steps`` so a run can
    be extended without relaxing source/data/runtime guards.
    """
    train = asdict(config.train)
    for key in (
        "output_dir",
        "device",
        "log_every",
        "eval_every",
        "save_every",
        "save_every_minutes",
        "eval_batches",
        "resume_from",
        "keep_last_checkpoints",
        "heartbeat_every_seconds",
        "minimum_free_disk_gb",
        "save_best",
        "best_metric",
        "greater_is_better",
        "log_memory",
        "allow_schedule_extension",
        "strict_source_resume",
        "strict_torch_resume",
        "save_optimizer",
        "save_frozen_base",
        "max_shard_size",
        "checkpoint_headroom_ratio",
        "nonfinite_policy",
        "max_nonfinite_skips",
    ):
        train.pop(key, None)
    if ignore_schedule_horizon:
        train.pop("epochs", None)
        train.pop("max_steps", None)
    payload = {
        "model": asdict(config.model),
        "data": {
            key: value
            for key, value in asdict(config.data).items()
            if key not in {
                "train_files",
                "eval_files",
                "verify_samples",
                "validate_json_on_index",
                "num_workers",
                "pin_memory",
                "persistent_workers",
                "prefetch_factor",
                "loader_timeout_seconds",
                "fingerprint_mode",
                "fingerprint_bytes",
            }
        },
        "workspace": asdict(config.workspace),
        "functional": asdict(config.functional),
        "train": train,
        "attribution": asdict(config.attribution),
        "induction": asdict(config.induction),
    }
    return stable_hash(payload)


# =============================================================================
# JSONL data pipeline
# =============================================================================


@dataclass(frozen=True)
class JsonlLocation:
    path: str
    offset: int
    line_number: int
    byte_length: int


class JsonlFineTuningDataset(Dataset[dict[str, Any]]):
    """Random-access JSONL dataset with lazy tokenization.

    Supported record shapes:

    1. {"text": "full causal-LM sequence"}
    2. {"prompt": "...", "response": "...", "system": "optional"}
    3. {"messages": [{"role": "user", ...}, {"role": "assistant", ...}]}

    Files are indexed by byte offset once. Each DataLoader worker opens its own
    file handles lazily, so the dataset remains pickle-safe.
    """

    def __init__(
        self,
        files: Sequence[str],
        tokenizer: Any,
        config: DataConfig,
    ) -> None:
        if not files:
            raise ValueError("At least one JSONL file is required.")
        self.files = _expand_file_patterns(files)
        if not self.files:
            raise FileNotFoundError(f"No files matched: {list(files)}")

        self.tokenizer = tokenizer
        self.config = config
        self.locations: list[JsonlLocation] = []
        self._handles: dict[str, Any] = {}
        self._build_index()
        if not self.locations:
            raise ValueError("The JSONL dataset contains no non-empty records.")

    def _build_index(self) -> None:
        for path in self.files:
            with open(path, "rb") as handle:
                line_number = 0
                while True:
                    offset = handle.tell()
                    raw = handle.readline()
                    if not raw:
                        break
                    line_number += 1
                    if raw.strip():
                        if self.config.validate_json_on_index:
                            try:
                                parsed = json.loads(raw.decode("utf-8"))
                            except Exception as exc:
                                raise ValueError(
                                    f"Invalid JSON at {path}:{line_number}: {exc}"
                                ) from exc
                            if not isinstance(parsed, dict):
                                raise TypeError(
                                    f"Record at {path}:{line_number} must be an object."
                                )
                        self.locations.append(
                            JsonlLocation(
                                path=str(path),
                                offset=offset,
                                line_number=line_number,
                                byte_length=len(raw),
                            )
                        )

    def __len__(self) -> int:
        return len(self.locations)

    def estimated_lengths(self) -> list[int]:
        """Return a deterministic, tokenizer-free length proxy.

        JSONL byte length is imperfect, especially across scripts, but it is
        cheap, stable across restarts, and sufficient for sortish bucketing.
        The hard max_length cap keeps pathological metadata records from
        dominating a bucket.
        """
        maximum = int(self.config.max_length)
        return [
            min(maximum, max(2, int(location.byte_length)))
            for location in self.locations
        ]

    def __getstate__(self) -> dict[str, Any]:
        state = dict(self.__dict__)
        state["_handles"] = {}
        return state

    def __del__(self) -> None:
        for handle in getattr(self, "_handles", {}).values():
            try:
                handle.close()
            except Exception:
                pass

    def _read_record(self, location: JsonlLocation) -> dict[str, Any]:
        handle = self._handles.get(location.path)
        if handle is None or handle.closed:
            handle = open(location.path, "rb")
            self._handles[location.path] = handle

        handle.seek(location.offset)
        raw = handle.readline()
        try:
            record = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ValueError(
                f"Invalid JSON at {location.path}:{location.line_number}: {exc}"
            ) from exc
        if not isinstance(record, dict):
            raise TypeError(
                f"Record at {location.path}:{location.line_number} must be an object."
            )
        return record

    def __getitem__(self, index: int) -> dict[str, Any]:
        location = self.locations[index]
        record = self._read_record(location)
        try:
            encoded = encode_finetuning_record(record, self.tokenizer, self.config)
        except Exception as exc:
            raise ValueError(
                f"Failed to encode {location.path}:{location.line_number}: {exc}"
            ) from exc
        encoded["sample_index"] = index
        if bool(encoded.get("functional_pair", False)):
            encoded["example_group_id"] = index
            encoded["world_group_id"] = int(encoded["functional_pair_id"])
            encoded["counterfactual_group_id"] = int(encoded["functional_pair_id"])
            encoded["rank_distance"] = -1
            encoded["answer_index"] = -1
            encoded["answer_class"] = -1
            encoded["twin_side"] = -1
            return encoded
        metadata = record.get("metadata", {})
        if not isinstance(metadata, Mapping):
            metadata = {}

        # Stable group IDs let the contrastive term exclude adjacent tokens from
        # the same example, or all queries derived from the same synthetic world.
        encoded["example_group_id"] = index
        world_value = metadata.get("world_id")
        if world_value is None:
            encoded["world_group_id"] = -(index + 1)
        else:
            material = f"{location.path}::{world_value}".encode("utf-8")
            encoded["world_group_id"] = int.from_bytes(
                hashlib.sha256(material).digest()[:8],
                byteorder="big",
                signed=False,
            ) & ((1 << 63) - 1)
        try:
            encoded["rank_distance"] = int(metadata.get("rank_distance", -1))
        except (TypeError, ValueError):
            encoded["rank_distance"] = -1
        try:
            encoded["answer_index"] = int(record.get("answer_index", -1))
        except (TypeError, ValueError):
            encoded["answer_index"] = -1
        try:
            encoded["answer_class"] = int(
                metadata.get("answer_class", record.get("answer_index", -1))
            )
        except (TypeError, ValueError):
            encoded["answer_class"] = -1
        try:
            encoded["twin_side"] = int(metadata.get("twin_side", -1))
        except (TypeError, ValueError):
            encoded["twin_side"] = -1
        pair_value = metadata.get("counterfactual_pair_id")
        if pair_value is None:
            encoded["counterfactual_group_id"] = -(index + 1)
        else:
            material = f"{location.path}::counterfactual::{pair_value}".encode(
                "utf-8"
            )
            encoded["counterfactual_group_id"] = int.from_bytes(
                hashlib.sha256(material).digest()[:8],
                byteorder="big",
                signed=False,
            ) & ((1 << 63) - 1)
        return encoded

    def world_group_ids(self) -> list[int]:
        """Read stable world IDs without tokenizing every record."""
        result: list[int] = []
        for index, location in enumerate(self.locations):
            record = self._read_record(location)
            metadata = record.get("metadata", {})
            if not isinstance(metadata, Mapping):
                metadata = {}
            world_value = metadata.get("world_id")
            if world_value is None:
                result.append(-(index + 1))
            else:
                material = f"{location.path}::{world_value}".encode("utf-8")
                result.append(
                    int.from_bytes(
                        hashlib.sha256(material).digest()[:8],
                        byteorder="big",
                        signed=False,
                    )
                    & ((1 << 63) - 1)
                )
        return result

    def counterfactual_group_ids(self) -> list[int]:
        """Read stable counterfactual-pair IDs without tokenizing records."""
        result: list[int] = []
        for index, location in enumerate(self.locations):
            record = self._read_record(location)
            metadata = record.get("metadata", {})
            if not isinstance(metadata, Mapping):
                metadata = {}
            pair_value = metadata.get("counterfactual_pair_id")
            if pair_value is None:
                result.append(-(index + 1))
            else:
                material = (
                    f"{location.path}::counterfactual::{pair_value}".encode("utf-8")
                )
                result.append(
                    int.from_bytes(
                        hashlib.sha256(material).digest()[:8],
                        byteorder="big",
                        signed=False,
                    )
                    & ((1 << 63) - 1)
                )
        return result


def _expand_file_patterns(patterns: Sequence[str]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for pattern in patterns:
        matches = sorted(glob.glob(str(Path(pattern).expanduser())))
        if not matches and Path(pattern).expanduser().is_file():
            matches = [str(Path(pattern).expanduser())]
        for match in matches:
            resolved = str(Path(match).resolve())
            if resolved not in seen:
                seen.add(resolved)
                result.append(Path(resolved))
    return result


def _tokenizer_encode(tokenizer: Any, text: str) -> list[int]:
    ids = tokenizer.encode(text, add_special_tokens=False)
    if isinstance(ids, torch.Tensor):
        ids = ids.tolist()
    return [int(x) for x in ids]


def _longest_common_prefix_length(a: Sequence[int], b: Sequence[int]) -> int:
    length = min(len(a), len(b))
    for i in range(length):
        if int(a[i]) != int(b[i]):
            return i
    return length


def _ensure_terminal_eos(ids: list[int], tokenizer: Any, add_eos: bool) -> list[int]:
    if not add_eos:
        return ids
    eos_id = getattr(tokenizer, "eos_token_id", None)
    if eos_id is not None and (not ids or ids[-1] != int(eos_id)):
        ids = [*ids, int(eos_id)]
    return ids


def _plain_prompt_response(
    record: Mapping[str, Any],
    tokenizer: Any,
    config: DataConfig,
) -> tuple[list[int], list[int], list[bool]]:
    prompt = str(record.get("prompt", ""))
    if not prompt and "context" in record:
        context = str(record.get("context", ""))
        query = str(record.get("query", ""))
        prompt = f"{context}{config.prompt_separator}{query}".strip()

    response = record.get("response", record.get("answer"))
    if response is None:
        raise ValueError("prompt records require a response or answer field.")
    response = str(response)

    system = str(record.get("system", "")).strip()
    if system:
        prompt = f"{system}{config.prompt_separator}{prompt}"

    prompt_ids = _tokenizer_encode(tokenizer, prompt)
    if config.add_bos:
        bos_id = getattr(tokenizer, "bos_token_id", None)
        if bos_id is not None and (not prompt_ids or prompt_ids[0] != int(bos_id)):
            prompt_ids = [int(bos_id), *prompt_ids]

    response_ids = _tokenizer_encode(
        tokenizer,
        f"{config.response_prefix}{response}",
    )
    response_ids = _ensure_terminal_eos(response_ids, tokenizer, config.add_eos)

    input_ids = [*prompt_ids, *response_ids]
    prompt_mask = [True] * len(prompt_ids) + [False] * len(response_ids)
    if config.train_on_prompt:
        labels = list(input_ids)
    else:
        labels = [-100] * len(prompt_ids) + list(response_ids)
    return input_ids, labels, prompt_mask



def _plain_deferred_record(
    record: Mapping[str, Any],
    tokenizer: Any,
    config: DataConfig,
) -> tuple[list[int], list[int], list[bool], list[bool], list[bool]]:
    """Encode context -> query -> response with explicit causal segment masks.

    Cumulative-prefix tokenization is used for the boundaries so BPE merges at
    segment edges cannot silently shift the masks by more than the final shared
    token. Chat-template records retain ordinary prompt masks; the exact deferred
    masks are guaranteed for this plain context/query representation.
    """
    context = str(record.get("context", ""))
    query = str(record.get("query", ""))
    response = record.get("response", record.get("answer"))
    if response is None:
        raise ValueError("deferred records require a response or answer field.")

    system = str(record.get("system", "")).strip()
    prefix = f"{system}{config.prompt_separator}" if system else ""
    context_text = f"{prefix}{context}"
    prompt_text = f"{context_text}{config.prompt_separator}{query}".strip()

    prompt_ids = _tokenizer_encode(tokenizer, prompt_text)
    prefix_ids = _tokenizer_encode(tokenizer, prefix)
    context_prefix_ids = _tokenizer_encode(tokenizer, context_text)
    context_start = _longest_common_prefix_length(prompt_ids, prefix_ids)
    context_end = _longest_common_prefix_length(prompt_ids, context_prefix_ids)

    if config.add_bos:
        bos_id = getattr(tokenizer, "bos_token_id", None)
        if bos_id is not None and (not prompt_ids or prompt_ids[0] != int(bos_id)):
            prompt_ids = [int(bos_id), *prompt_ids]
            context_start += 1
            context_end += 1

    response_ids = _tokenizer_encode(
        tokenizer, f"{config.response_prefix}{str(response)}"
    )
    response_ids = _ensure_terminal_eos(response_ids, tokenizer, config.add_eos)
    input_ids = [*prompt_ids, *response_ids]
    prompt_length = len(prompt_ids)
    prompt_mask = [True] * prompt_length + [False] * len(response_ids)
    context_mask = [False] * len(input_ids)
    query_mask = [False] * len(input_ids)
    for index in range(max(0, context_start), min(context_end, prompt_length)):
        context_mask[index] = True
    for index in range(max(0, context_end), prompt_length):
        query_mask[index] = True

    if config.train_on_prompt:
        labels = list(input_ids)
    else:
        labels = [-100] * prompt_length + list(response_ids)
    return input_ids, labels, prompt_mask, context_mask, query_mask

def _fallback_messages_to_pair(
    messages: Sequence[Mapping[str, Any]],
    tokenizer: Any,
    config: DataConfig,
) -> tuple[list[int], list[int], list[bool]]:
    if not messages or str(messages[-1].get("role", "")) != "assistant":
        raise ValueError("messages records must end with an assistant message.")

    prompt_parts: list[str] = []
    for message in messages[:-1]:
        role = str(message.get("role", "unknown")).upper()
        content = str(message.get("content", ""))
        prompt_parts.append(f"<{role}>\n{content}")
    prompt_parts.append("<ASSISTANT>\n")

    pair = {
        "prompt": "\n\n".join(prompt_parts),
        "response": str(messages[-1].get("content", "")),
    }
    return _plain_prompt_response(pair, tokenizer, config)


def _chat_messages(
    messages: Sequence[Mapping[str, Any]],
    tokenizer: Any,
    config: DataConfig,
) -> tuple[list[int], list[int], list[bool]]:
    if not messages or str(messages[-1].get("role", "")) != "assistant":
        raise ValueError("messages records must end with an assistant message.")

    try:
        full_ids = tokenizer.apply_chat_template(
            list(messages),
            tokenize=True,
            add_generation_prompt=False,
        )
        prefix_ids = tokenizer.apply_chat_template(
            list(messages[:-1]),
            tokenize=True,
            add_generation_prompt=True,
        )
        if isinstance(full_ids, torch.Tensor):
            full_ids = full_ids.tolist()
        if isinstance(prefix_ids, torch.Tensor):
            prefix_ids = prefix_ids.tolist()
        full_ids = [int(x) for x in full_ids]
        prefix_ids = [int(x) for x in prefix_ids]
    except Exception:
        return _fallback_messages_to_pair(messages, tokenizer, config)

    prompt_length = _longest_common_prefix_length(full_ids, prefix_ids)
    input_ids = _ensure_terminal_eos(full_ids, tokenizer, config.add_eos)
    prompt_length = min(prompt_length, len(input_ids))
    prompt_mask = [True] * prompt_length + [False] * (len(input_ids) - prompt_length)

    if config.train_on_prompt:
        labels = list(input_ids)
    else:
        labels = [-100] * prompt_length + input_ids[prompt_length:]
    return input_ids, labels, prompt_mask


def _prompt_response_via_chat_template(
    record: Mapping[str, Any],
    tokenizer: Any,
    config: DataConfig,
) -> tuple[list[int], list[int], list[bool]]:
    prompt = str(record.get("prompt", ""))
    if not prompt and "context" in record:
        context = str(record.get("context", ""))
        query = str(record.get("query", ""))
        prompt = f"{context}{config.prompt_separator}{query}".strip()

    response = record.get("response", record.get("answer"))
    if response is None:
        raise ValueError("prompt records require a response or answer field.")

    messages: list[dict[str, str]] = []
    system = str(record.get("system", "")).strip()
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    messages.append({"role": "assistant", "content": str(response)})
    return _chat_messages(messages, tokenizer, config)


def _truncate_encoded(
    input_ids: list[int],
    labels: list[int],
    prompt_mask: list[bool],
    max_length: int,
    tokenizer: Any,
    add_eos: bool,
    *,
    extra_masks: Optional[Sequence[list[bool]]] = None,
) -> tuple[list[int], list[int], list[bool], list[list[bool]]]:
    masks = [list(mask) for mask in (extra_masks or [])]
    if not (len(input_ids) == len(labels) == len(prompt_mask)):
        raise ValueError("Encoded fields must have identical lengths.")
    if any(len(mask) != len(input_ids) for mask in masks):
        raise ValueError("All extra masks must align with input_ids.")
    if len(input_ids) <= max_length:
        return input_ids, labels, prompt_mask, masks

    supervised = [i for i, label in enumerate(labels) if label != -100]
    if supervised and supervised[0] > 0:
        first_target = supervised[0]
        response_length = len(input_ids) - first_target
        if response_length < max_length:
            prompt_keep = max_length - response_length
            start = max(0, first_target - prompt_keep)
            stop = len(input_ids)
        else:
            start = first_target
            stop = first_target + max_length
    else:
        start = 0
        stop = max_length

    input_ids = input_ids[start:stop]
    labels = labels[start:stop]
    prompt_mask = prompt_mask[start:stop]
    masks = [mask[start:stop] for mask in masks]

    eos_id = getattr(tokenizer, "eos_token_id", None)
    if add_eos and eos_id is not None and labels and labels[-1] != -100:
        input_ids[-1] = int(eos_id)
        labels[-1] = int(eos_id)
        prompt_mask[-1] = False
        for mask in masks:
            mask[-1] = False
    return input_ids, labels, prompt_mask, masks



def _functional_suffix_token_ids(
    tokenizer: Any,
    prefix: str,
    suffix: str,
    *,
    require_one: bool,
) -> tuple[list[int], list[int], list[int]]:
    prefix_ids = _tokenizer_encode(tokenizer, prefix)
    full_ids = _tokenizer_encode(tokenizer, f"{prefix}{suffix}")
    boundary = _longest_common_prefix_length(prefix_ids, full_ids)
    answer_ids = full_ids[boundary:]
    if not answer_ids:
        raise ValueError(
            f"Functional answer suffix {suffix!r} produced no new token after {prefix!r}."
        )
    if require_one and len(answer_ids) != 1:
        raise ValueError(
            f"Functional answer {suffix!r} must be exactly one token, got {answer_ids}."
        )
    labels = [-100] * boundary + list(answer_ids)
    return full_ids, labels, answer_ids


def _encode_functional_world_pair(
    record: Mapping[str, Any],
    tokenizer: Any,
    config: DataConfig,
) -> dict[str, Any]:
    """Encode one v9 paired world with a shared future-query set.

    The returned feature preserves the pair and query axes. The collator pads
    them without flattening, so the model can encode each context exactly once
    and reuse its memory across every query.
    """
    contexts_raw = record.get("contexts", record.get("context_pair"))
    queries_raw = record.get("queries")
    answers_raw = record.get("answers")
    choices_raw = record.get("choices", [" 0", " 1"])
    if not isinstance(contexts_raw, Sequence) or isinstance(contexts_raw, (str, bytes)):
        raise TypeError("functional_world_pair requires contexts=[context0, context1].")
    contexts = [str(value) for value in contexts_raw]
    if len(contexts) != 2:
        raise ValueError("functional_world_pair requires exactly two contexts.")
    if not isinstance(queries_raw, Sequence) or isinstance(queries_raw, (str, bytes)):
        raise TypeError("functional_world_pair requires a queries list.")
    queries = [str(value) for value in queries_raw]
    if not queries:
        raise ValueError("functional_world_pair requires at least one query.")
    if len(queries) > int(config.functional_max_queries):
        raise ValueError(
            f"Record has {len(queries)} queries but functional_max_queries="
            f"{config.functional_max_queries}."
        )
    if not isinstance(answers_raw, Sequence) or len(answers_raw) != 2:
        raise TypeError("functional_world_pair requires answers=[[...], [...]].")
    answers: list[list[int]] = []
    for side_values in answers_raw:
        if not isinstance(side_values, Sequence) or isinstance(side_values, (str, bytes)):
            raise TypeError("Each functional answer side must be a list.")
        if len(side_values) != len(queries):
            raise ValueError("Each functional answer side must align with queries.")
        side: list[int] = []
        for value in side_values:
            try:
                answer = int(value)
            except (TypeError, ValueError) as exc:
                raise TypeError("Functional answers must be integer choice indices.") from exc
            side.append(answer)
        answers.append(side)

    if not isinstance(choices_raw, Sequence) or isinstance(choices_raw, (str, bytes)):
        raise TypeError("functional choices must be a sequence of answer suffixes.")
    choices = [str(value) for value in choices_raw]
    if len(choices) < 2:
        raise ValueError("functional tasks require at least two choices.")
    if any(answer < 0 or answer >= len(choices) for side in answers for answer in side):
        raise ValueError("Functional answer index is outside the choice vocabulary.")

    affected_raw = record.get("affected")
    if affected_raw is None:
        affected = [answers[0][j] != answers[1][j] for j in range(len(queries))]
    else:
        if not isinstance(affected_raw, Sequence) or len(affected_raw) != len(queries):
            raise ValueError("affected must align with queries.")
        affected = [bool(value) for value in affected_raw]
        derived = [answers[0][j] != answers[1][j] for j in range(len(queries))]
        if affected != derived:
            raise ValueError(
                "affected mask must exactly equal the answer differences between twins."
            )

    metadata = record.get("metadata", {})
    if not isinstance(metadata, Mapping):
        metadata = {}
    hop_raw = record.get("hop_distances", metadata.get("hop_distances", []))
    heldout_raw = record.get("heldout_queries", metadata.get("heldout_queries", []))
    hop_distances = [int(value) for value in hop_raw] if hop_raw else [-1] * len(queries)
    heldout = [bool(value) for value in heldout_raw] if heldout_raw else [False] * len(queries)
    if len(hop_distances) != len(queries) or len(heldout) != len(queries):
        raise ValueError("hop_distances and heldout_queries must align with queries.")

    context_ids: list[list[int]] = []
    for text in contexts:
        ids = _tokenizer_encode(tokenizer, text)
        if config.add_bos:
            bos_id = getattr(tokenizer, "bos_token_id", None)
            if bos_id is not None and (not ids or ids[0] != int(bos_id)):
                ids = [int(bos_id), *ids]
        ids = _ensure_terminal_eos(ids, tokenizer, config.add_eos)
        if len(ids) > int(config.functional_context_max_length):
            raise ValueError(
                "Functional context exceeds functional_context_max_length; "
                "v9 refuses silent world truncation."
            )
        if len(ids) < 2:
            raise ValueError("Functional context must contain at least two tokens.")
        context_ids.append(ids)

    query_ids: list[list[list[int]]] = [[], []]
    query_labels: list[list[list[int]]] = [[], []]
    query_choice_ids: list[list[list[list[int]]]] = [[], []]
    inline_ids: list[list[list[int]]] = [[], []]
    inline_labels: list[list[list[int]]] = [[], []]
    inline_choice_ids: list[list[list[list[int]]]] = [[], []]

    require_one = bool(config.functional_require_one_token_answer)
    for side in range(2):
        for query_index, query in enumerate(queries):
            answer_suffix = choices[answers[side][query_index]]
            ids, labels, answer_token_ids = _functional_suffix_token_ids(
                tokenizer,
                query,
                answer_suffix,
                require_one=require_one,
            )
            if len(ids) > int(config.functional_query_max_length):
                raise ValueError(
                    "Functional query exceeds functional_query_max_length; "
                    "v9 refuses silent query truncation."
                )
            if not any(label != -100 for label in labels[1:]):
                raise ValueError("Functional query lost its supervised answer token.")
            query_ids[side].append(ids)
            query_labels[side].append(labels)

            candidates: list[list[int]] = []
            for choice in choices:
                _candidate_full, _candidate_labels, candidate_answer = (
                    _functional_suffix_token_ids(
                        tokenizer,
                        query,
                        choice,
                        require_one=require_one,
                    )
                )
                candidates.append(candidate_answer)
            query_choice_ids[side].append(candidates)

            inline_prefix = f"{contexts[side]}{config.prompt_separator}{query}"
            full_inline, labels_inline, _ = _functional_suffix_token_ids(
                tokenizer,
                inline_prefix,
                answer_suffix,
                require_one=require_one,
            )
            if config.add_bos:
                bos_id = getattr(tokenizer, "bos_token_id", None)
                if bos_id is not None and (
                    not full_inline or full_inline[0] != int(bos_id)
                ):
                    full_inline = [int(bos_id), *full_inline]
                    labels_inline = [-100, *labels_inline]
            if len(full_inline) > int(config.functional_inline_max_length):
                raise ValueError(
                    "Functional inline sequence exceeds functional_inline_max_length."
                )
            inline_ids[side].append(full_inline)
            inline_labels[side].append(labels_inline)
            inline_candidates: list[list[int]] = []
            for choice in choices:
                _candidate_full, _candidate_labels, candidate_answer = (
                    _functional_suffix_token_ids(
                        tokenizer,
                        inline_prefix,
                        choice,
                        require_one=require_one,
                    )
                )
                inline_candidates.append(candidate_answer)
            inline_choice_ids[side].append(inline_candidates)

            if require_one and len(answer_token_ids) != 1:
                raise AssertionError("one-token functional answer contract drifted.")

    pair_value = metadata.get("pair_id", metadata.get("world_pair_id", record.get("pair_id", 0)))
    pair_material = json.dumps(pair_value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    pair_id = int.from_bytes(hashlib.sha256(pair_material).digest()[:8], "big") & ((1 << 63) - 1)

    return {
        "functional_pair": True,
        "functional_context_ids": context_ids,
        "functional_query_ids": query_ids,
        "functional_query_labels": query_labels,
        "functional_query_choice_ids": query_choice_ids,
        "functional_inline_ids": inline_ids,
        "functional_inline_labels": inline_labels,
        "functional_inline_choice_ids": inline_choice_ids,
        "functional_answers": answers,
        "functional_affected": affected,
        "functional_hop_distances": hop_distances,
        "functional_heldout_queries": heldout,
        "functional_pair_id": pair_id,
        "functional_query_count": len(queries),
        "functional_choice_count": len(choices),
        "functional_edit_type": str(metadata.get("edit_type", "local_swap")),
    }


def encode_finetuning_record(
    record: Mapping[str, Any],
    tokenizer: Any,
    config: DataConfig,
) -> dict[str, Any]:
    context_mask: list[bool]
    query_mask: list[bool]

    if record.get("format") == "functional_world_pair_v9" or (
        "contexts" in record and "queries" in record and "answers" in record
    ):
        return _encode_functional_world_pair(record, tokenizer, config)

    if (
        "context" in record
        and "query" in record
        and not (
            config.use_chat_template
            and hasattr(tokenizer, "apply_chat_template")
        )
    ):
        (
            input_ids,
            labels,
            prompt_mask,
            context_mask,
            query_mask,
        ) = _plain_deferred_record(record, tokenizer, config)
    elif "messages" in record:
        messages = record["messages"]
        if not isinstance(messages, list):
            raise TypeError("messages must be a list.")
        if config.use_chat_template and hasattr(tokenizer, "apply_chat_template"):
            input_ids, labels, prompt_mask = _chat_messages(messages, tokenizer, config)
        else:
            input_ids, labels, prompt_mask = _fallback_messages_to_pair(
                messages, tokenizer, config
            )
        context_mask = [False] * len(input_ids)
        query_mask = list(prompt_mask)
    elif "prompt" in record or "context" in record:
        if config.use_chat_template and hasattr(tokenizer, "apply_chat_template"):
            input_ids, labels, prompt_mask = _prompt_response_via_chat_template(
                record, tokenizer, config
            )
        else:
            input_ids, labels, prompt_mask = _plain_prompt_response(
                record, tokenizer, config
            )
        context_mask = [False] * len(input_ids)
        query_mask = list(prompt_mask)
    elif "text" in record:
        input_ids = _tokenizer_encode(tokenizer, str(record["text"]))
        if config.add_bos:
            bos_id = getattr(tokenizer, "bos_token_id", None)
            if bos_id is not None and (not input_ids or input_ids[0] != int(bos_id)):
                input_ids = [int(bos_id), *input_ids]
        input_ids = _ensure_terminal_eos(input_ids, tokenizer, config.add_eos)
        labels = list(input_ids)
        prompt_mask = [False] * len(input_ids)
        context_mask = [False] * len(input_ids)
        query_mask = [False] * len(input_ids)
    else:
        raise ValueError("Record must contain text, prompt/context, or messages.")

    input_ids, labels, prompt_mask, extra_masks = _truncate_encoded(
        input_ids,
        labels,
        prompt_mask,
        config.max_length,
        tokenizer,
        config.add_eos,
        extra_masks=[context_mask, query_mask],
    )
    context_mask, query_mask = extra_masks

    if len(input_ids) < 2:
        raise ValueError("A training sequence must contain at least two tokens.")
    if not any(label != -100 for label in labels[1:]):
        raise ValueError("No supervised next-token targets remain after tokenization.")

    return {
        "input_ids": input_ids,
        "labels": labels,
        "prompt_mask": prompt_mask,
        "context_mask": context_mask,
        "query_mask": query_mask,
    }


class CausalFineTuningCollator:
    """Pad ordinary causal tensors and v7 deferred-bridge views together.

    The bridge view is a deterministic projection of the same encoded record:

    * context branch: system/context prompt tokens, excluding the query;
    * continuation branch: query plus teacher-forced response tokens.

    No second tokenizer pass is performed, so BPE boundary decisions and corpus
    provenance remain identical across inline and bridge topologies.
    """

    def __init__(
        self,
        pad_token_id: int,
        pad_to_multiple_of: int = 8,
    ) -> None:
        self.pad_token_id = int(pad_token_id)
        self.pad_to_multiple_of = int(pad_to_multiple_of)
        if self.pad_to_multiple_of < 1:
            raise ValueError("pad_to_multiple_of must be positive.")

    def _padded_length(self, length: int) -> int:
        multiple = self.pad_to_multiple_of
        return max(1, ((max(1, length) + multiple - 1) // multiple) * multiple)

    def _collate_functional_pairs(
        self,
        features: Sequence[Mapping[str, Any]],
    ) -> dict[str, torch.Tensor]:
        if not all(bool(feature.get("functional_pair", False)) for feature in features):
            raise ValueError("Functional and ordinary records cannot share a batch.")
        batch_size = len(features)
        sides = 2
        max_queries = max(int(feature["functional_query_count"]) for feature in features)
        max_choices = max(int(feature["functional_choice_count"]) for feature in features)
        context_length = self._padded_length(
            max(len(side) for feature in features for side in feature["functional_context_ids"])
        )
        query_length = self._padded_length(
            max(
                len(query)
                for feature in features
                for side in feature["functional_query_ids"]
                for query in side
            )
        )
        inline_length = self._padded_length(
            max(
                len(query)
                for feature in features
                for side in feature["functional_inline_ids"]
                for query in side
            )
        )

        context_ids = torch.full(
            (batch_size, sides, context_length), self.pad_token_id, dtype=torch.long
        )
        context_attention = torch.zeros_like(context_ids)
        query_ids = torch.full(
            (batch_size, sides, max_queries, query_length),
            self.pad_token_id,
            dtype=torch.long,
        )
        query_attention = torch.zeros_like(query_ids)
        query_labels = torch.full_like(query_ids, -100)
        inline_ids = torch.full(
            (batch_size, sides, max_queries, inline_length),
            self.pad_token_id,
            dtype=torch.long,
        )
        inline_attention = torch.zeros_like(inline_ids)
        inline_labels = torch.full_like(inline_ids, -100)
        query_choice_ids = torch.full(
            (batch_size, sides, max_queries, max_choices), -1, dtype=torch.long
        )
        inline_choice_ids = torch.full_like(query_choice_ids, -1)
        answers = torch.full(
            (batch_size, sides, max_queries), -1, dtype=torch.long
        )
        query_valid = torch.zeros((batch_size, max_queries), dtype=torch.bool)
        affected = torch.zeros((batch_size, max_queries), dtype=torch.bool)
        heldout = torch.zeros((batch_size, max_queries), dtype=torch.bool)
        hop_distances = torch.full(
            (batch_size, max_queries), -1, dtype=torch.long
        )
        pair_ids = torch.full((batch_size,), -1, dtype=torch.long)
        sample_indices = torch.full((batch_size,), -1, dtype=torch.long)

        for row, feature in enumerate(features):
            query_count = int(feature["functional_query_count"])
            choice_count = int(feature["functional_choice_count"])
            query_valid[row, :query_count] = True
            affected[row, :query_count] = torch.as_tensor(
                feature["functional_affected"], dtype=torch.bool
            )
            heldout[row, :query_count] = torch.as_tensor(
                feature["functional_heldout_queries"], dtype=torch.bool
            )
            hop_distances[row, :query_count] = torch.as_tensor(
                feature["functional_hop_distances"], dtype=torch.long
            )
            answers[row, :, :query_count] = torch.as_tensor(
                feature["functional_answers"], dtype=torch.long
            )
            pair_ids[row] = int(feature["functional_pair_id"])
            sample_indices[row] = int(feature.get("sample_index", row))

            for side in range(sides):
                context = torch.as_tensor(
                    feature["functional_context_ids"][side], dtype=torch.long
                )
                context_ids[row, side, : context.numel()] = context
                context_attention[row, side, : context.numel()] = 1
                for query_index in range(query_count):
                    q_ids = torch.as_tensor(
                        feature["functional_query_ids"][side][query_index],
                        dtype=torch.long,
                    )
                    q_labels = torch.as_tensor(
                        feature["functional_query_labels"][side][query_index],
                        dtype=torch.long,
                    )
                    query_ids[row, side, query_index, : q_ids.numel()] = q_ids
                    query_attention[row, side, query_index, : q_ids.numel()] = 1
                    query_labels[row, side, query_index, : q_labels.numel()] = q_labels

                    i_ids = torch.as_tensor(
                        feature["functional_inline_ids"][side][query_index],
                        dtype=torch.long,
                    )
                    i_labels = torch.as_tensor(
                        feature["functional_inline_labels"][side][query_index],
                        dtype=torch.long,
                    )
                    inline_ids[row, side, query_index, : i_ids.numel()] = i_ids
                    inline_attention[row, side, query_index, : i_ids.numel()] = 1
                    inline_labels[row, side, query_index, : i_labels.numel()] = i_labels

                    q_choices = feature["functional_query_choice_ids"][side][query_index]
                    i_choices = feature["functional_inline_choice_ids"][side][query_index]
                    for choice_index in range(choice_count):
                        q_answer = q_choices[choice_index]
                        i_answer = i_choices[choice_index]
                        if len(q_answer) != 1 or len(i_answer) != 1:
                            raise ValueError(
                                "Functional collator requires one-token choices."
                            )
                        query_choice_ids[
                            row, side, query_index, choice_index
                        ] = int(q_answer[0])
                        inline_choice_ids[
                            row, side, query_index, choice_index
                        ] = int(i_answer[0])

        # Compatibility tensors keep the legacy trainer and checkpoint audit
        # surface stable. Functional forward ignores them and consumes the
        # explicitly grouped tensors below.
        input_ids = query_ids[:, 0, 0, :].clone()
        attention_mask = query_attention[:, 0, 0, :].clone()
        labels = query_labels[:, 0, 0, :].clone()
        prompt_mask = labels.eq(-100) & attention_mask.to(torch.bool)
        false_mask = torch.zeros_like(prompt_mask)

        return {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "labels": labels,
            "prompt_mask": prompt_mask,
            "context_mask": false_mask,
            "query_mask": prompt_mask,
            "sample_indices": sample_indices,
            "example_group_ids": pair_ids,
            "world_group_ids": pair_ids,
            "counterfactual_group_ids": pair_ids,
            "rank_distances": torch.full((batch_size,), -1, dtype=torch.long),
            "answer_indices": torch.full((batch_size,), -1, dtype=torch.long),
            "answer_classes": torch.full((batch_size,), -1, dtype=torch.long),
            "twin_sides": torch.full((batch_size,), -1, dtype=torch.long),
            "functional_context_input_ids": context_ids,
            "functional_context_attention_mask": context_attention,
            "functional_query_input_ids": query_ids,
            "functional_query_attention_mask": query_attention,
            "functional_query_labels": query_labels,
            "functional_inline_input_ids": inline_ids,
            "functional_inline_attention_mask": inline_attention,
            "functional_inline_labels": inline_labels,
            "functional_query_choice_ids": query_choice_ids,
            "functional_inline_choice_ids": inline_choice_ids,
            "functional_answer_classes": answers,
            "functional_query_valid_mask": query_valid,
            "functional_affected_mask": affected,
            "functional_heldout_mask": heldout,
            "functional_hop_distances": hop_distances,
            "functional_pair_ids": pair_ids,
        }

    def __call__(self, features: Sequence[Mapping[str, Any]]) -> dict[str, torch.Tensor]:
        if not features:
            raise ValueError("Cannot collate an empty feature list.")
        if any(bool(feature.get("functional_pair", False)) for feature in features):
            return self._collate_functional_pairs(features)

        prepared: list[dict[str, torch.Tensor]] = []
        for feature in features:
            ids = torch.as_tensor(feature["input_ids"], dtype=torch.long)
            target = torch.as_tensor(feature["labels"], dtype=torch.long)
            prompt = torch.as_tensor(feature["prompt_mask"], dtype=torch.bool)
            context = torch.as_tensor(
                feature.get("context_mask", [False] * ids.numel()), dtype=torch.bool
            )
            query = torch.as_tensor(
                feature.get("query_mask", feature["prompt_mask"]), dtype=torch.bool
            )
            length = ids.numel()
            if any(field.numel() != length for field in (target, prompt, context, query)):
                raise ValueError("Feature fields must have identical lengths.")

            # The bridge context includes any system prefix plus the explicit
            # context, while the continuation excludes all raw context tokens.
            bridge_context_select = prompt & ~query
            bridge_continuation_select = query | ~prompt
            if not bridge_continuation_select.any():
                bridge_continuation_select = torch.ones_like(prompt)

            prepared.append(
                {
                    "ids": ids,
                    "target": target,
                    "prompt": prompt,
                    "context": context,
                    "query": query,
                    "bridge_context_ids": ids[bridge_context_select],
                    "bridge_ids": ids[bridge_continuation_select],
                    "bridge_labels": target[bridge_continuation_select],
                    "bridge_query": query[bridge_continuation_select],
                }
            )

        batch_size = len(features)
        padded_length = self._padded_length(
            max(item["ids"].numel() for item in prepared)
        )
        context_length = self._padded_length(
            max(item["bridge_context_ids"].numel() for item in prepared)
        )
        bridge_length = self._padded_length(
            max(item["bridge_ids"].numel() for item in prepared)
        )

        input_ids = torch.full(
            (batch_size, padded_length), self.pad_token_id, dtype=torch.long
        )
        labels = torch.full((batch_size, padded_length), -100, dtype=torch.long)
        attention_mask = torch.zeros((batch_size, padded_length), dtype=torch.long)
        prompt_mask = torch.zeros((batch_size, padded_length), dtype=torch.bool)
        context_mask = torch.zeros((batch_size, padded_length), dtype=torch.bool)
        query_mask = torch.zeros((batch_size, padded_length), dtype=torch.bool)

        bridge_context_input_ids = torch.full(
            (batch_size, context_length), self.pad_token_id, dtype=torch.long
        )
        bridge_context_attention_mask = torch.zeros(
            (batch_size, context_length), dtype=torch.long
        )
        bridge_input_ids = torch.full(
            (batch_size, bridge_length), self.pad_token_id, dtype=torch.long
        )
        bridge_attention_mask = torch.zeros(
            (batch_size, bridge_length), dtype=torch.long
        )
        bridge_labels = torch.full(
            (batch_size, bridge_length), -100, dtype=torch.long
        )
        bridge_prompt_mask = torch.zeros(
            (batch_size, bridge_length), dtype=torch.bool
        )
        bridge_query_mask = torch.zeros(
            (batch_size, bridge_length), dtype=torch.bool
        )

        sample_indices = torch.full((batch_size,), -1, dtype=torch.long)
        example_group_ids = torch.full((batch_size,), -1, dtype=torch.long)
        world_group_ids = torch.full((batch_size,), -1, dtype=torch.long)
        counterfactual_group_ids = torch.full(
            (batch_size,), -1, dtype=torch.long
        )
        rank_distances = torch.full((batch_size,), -1, dtype=torch.long)
        answer_indices = torch.full((batch_size,), -1, dtype=torch.long)
        answer_classes = torch.full((batch_size,), -1, dtype=torch.long)
        twin_sides = torch.full((batch_size,), -1, dtype=torch.long)

        for row, (feature, item) in enumerate(zip(features, prepared)):
            length = item["ids"].numel()
            input_ids[row, :length] = item["ids"]
            labels[row, :length] = item["target"]
            attention_mask[row, :length] = 1
            prompt_mask[row, :length] = item["prompt"]
            context_mask[row, :length] = item["context"]
            query_mask[row, :length] = item["query"]

            context_count = item["bridge_context_ids"].numel()
            if context_count:
                bridge_context_input_ids[row, :context_count] = item[
                    "bridge_context_ids"
                ]
                bridge_context_attention_mask[row, :context_count] = 1

            bridge_count = item["bridge_ids"].numel()
            bridge_input_ids[row, :bridge_count] = item["bridge_ids"]
            bridge_attention_mask[row, :bridge_count] = 1
            bridge_labels[row, :bridge_count] = item["bridge_labels"]
            bridge_query_mask[row, :bridge_count] = item["bridge_query"]
            bridge_prompt_mask[row, :bridge_count] = item["bridge_query"]

            if "sample_index" in feature:
                sample_indices[row] = int(feature["sample_index"])
            example_group_ids[row] = int(
                feature.get("example_group_id", feature.get("sample_index", row))
            )
            world_group_ids[row] = int(
                feature.get("world_group_id", example_group_ids[row].item())
            )
            counterfactual_group_ids[row] = int(
                feature.get(
                    "counterfactual_group_id", example_group_ids[row].item()
                )
            )
            rank_distances[row] = int(feature.get("rank_distance", -1))
            answer_indices[row] = int(feature.get("answer_index", -1))
            answer_classes[row] = int(feature.get("answer_class", -1))
            twin_sides[row] = int(feature.get("twin_side", -1))

        return {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "labels": labels,
            "prompt_mask": prompt_mask,
            "context_mask": context_mask,
            "query_mask": query_mask,
            "bridge_context_input_ids": bridge_context_input_ids,
            "bridge_context_attention_mask": bridge_context_attention_mask,
            "bridge_input_ids": bridge_input_ids,
            "bridge_attention_mask": bridge_attention_mask,
            "bridge_labels": bridge_labels,
            "bridge_prompt_mask": bridge_prompt_mask,
            "bridge_query_mask": bridge_query_mask,
            "sample_indices": sample_indices,
            "example_group_ids": example_group_ids,
            "world_group_ids": world_group_ids,
            "counterfactual_group_ids": counterfactual_group_ids,
            "rank_distances": rank_distances,
            "answer_indices": answer_indices,
            "answer_classes": answer_classes,
            "twin_sides": twin_sides,
        }


def _seed_dataloader_worker(worker_id: int) -> None:
    del worker_id
    worker_seed = torch.initial_seed() % (2**32)
    random.seed(worker_seed)
    torch.manual_seed(worker_seed)


class ResumableDistributedBatchSampler(Sampler[list[int]]):
    """Deterministic, rank-aware, mid-epoch resumable batch sampler.

    A global batch is constructed first and then sliced across ranks. Every rank
    therefore executes the same number of forward passes, which is essential for
    DDP. Optional sortish bucketing uses a cheap length proxy while preserving a
    fresh deterministic permutation for every epoch.
    """

    def __init__(
        self,
        *,
        dataset_size: int,
        batch_size: int,
        num_replicas: int = 1,
        rank: int = 0,
        seed: int = 0,
        shuffle: bool = True,
        drop_last: bool = False,
        lengths: Optional[Sequence[int]] = None,
        bucket_size_multiplier: int = 50,
    ) -> None:
        if dataset_size < 1:
            raise ValueError("dataset_size must be positive.")
        if batch_size < 1:
            raise ValueError("batch_size must be positive.")
        if num_replicas < 1:
            raise ValueError("num_replicas must be positive.")
        if not 0 <= rank < num_replicas:
            raise ValueError("rank must be in [0, num_replicas).")
        if bucket_size_multiplier < 1:
            raise ValueError("bucket_size_multiplier must be positive.")
        if lengths is not None and len(lengths) != dataset_size:
            raise ValueError("lengths must align with dataset_size.")

        self.dataset_size = int(dataset_size)
        self.batch_size = int(batch_size)
        self.num_replicas = int(num_replicas)
        self.rank = int(rank)
        self.seed = int(seed)
        self.shuffle = bool(shuffle)
        self.drop_last = bool(drop_last)
        self.lengths = list(lengths) if lengths is not None else None
        self.bucket_size_multiplier = int(bucket_size_multiplier)
        self.epoch = 0
        self.start_batch = 0

        if self.drop_last and self.dataset_size < self.global_batch_size:
            raise ValueError(
                "drop_last=True would produce zero global batches for this dataset."
            )

    @property
    def global_batch_size(self) -> int:
        return self.batch_size * self.num_replicas

    @property
    def full_batches_per_epoch(self) -> int:
        if self.drop_last:
            return self.dataset_size // self.global_batch_size
        return math.ceil(self.dataset_size / self.global_batch_size)

    def set_epoch(self, epoch: int, start_batch: int = 0) -> None:
        if epoch < 0:
            raise ValueError("epoch must be non-negative.")
        if not 0 <= start_batch <= self.full_batches_per_epoch:
            raise ValueError("start_batch lies outside this epoch.")
        self.epoch = int(epoch)
        self.start_batch = int(start_batch)

    def state_dict(self) -> dict[str, int]:
        return {"epoch": self.epoch, "start_batch": self.start_batch}

    def load_state_dict(self, state: Mapping[str, Any]) -> None:
        self.set_epoch(
            int(state.get("epoch", 0)),
            int(state.get("start_batch", 0)),
        )

    def _ordered_indices(self) -> list[int]:
        generator = torch.Generator()
        generator.manual_seed(self.seed + self.epoch)
        if self.shuffle:
            order = torch.randperm(self.dataset_size, generator=generator).tolist()
        else:
            order = list(range(self.dataset_size))

        if self.lengths is not None and self.shuffle:
            bucket_width = max(
                self.global_batch_size,
                self.global_batch_size * self.bucket_size_multiplier,
            )
            sort_descending = bool(self.epoch % 2)
            bucketed: list[int] = []
            for offset in range(0, len(order), bucket_width):
                bucket = order[offset : offset + bucket_width]
                bucket.sort(
                    key=lambda index: self.lengths[index],
                    reverse=sort_descending,
                )
                sort_descending = not sort_descending
                bucketed.extend(bucket)
            order = bucketed

        target = self.full_batches_per_epoch * self.global_batch_size
        if self.drop_last:
            return order[:target]
        if len(order) < target:
            repeats = target - len(order)
            order.extend(order[index % len(order)] for index in range(repeats))
        return order

    def __iter__(self) -> Iterator[list[int]]:
        order = self._ordered_indices()
        width = self.global_batch_size
        local_start = self.rank * self.batch_size
        local_stop = local_start + self.batch_size
        for batch_index in range(self.start_batch, self.full_batches_per_epoch):
            global_batch = order[batch_index * width : (batch_index + 1) * width]
            yield global_batch[local_start:local_stop]

    def __len__(self) -> int:
        return self.full_batches_per_epoch - self.start_batch


def _loader_worker_kwargs(
    *,
    num_workers: int,
    persistent_workers: bool,
    prefetch_factor: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "num_workers": int(num_workers),
        "persistent_workers": bool(persistent_workers and num_workers > 0),
        "timeout": float(timeout_seconds),
    }
    if num_workers > 0:
        kwargs["worker_init_fn"] = _seed_dataloader_worker
        kwargs["prefetch_factor"] = int(prefetch_factor)
    return kwargs


def _make_loader_generator(seed: int) -> torch.Generator:
    """Create a DataLoader-only RNG stream.

    Constructing a DataLoader iterator consumes a base seed even when
    ``num_workers == 0``.  A private generator prevents that bookkeeping from
    perturbing the model RNG stream, which is essential for bitwise-equivalent
    mid-epoch resume when the workspace contains dropout or random sampling.
    """
    generator = torch.Generator()
    generator.manual_seed(int(seed) % (2**63 - 1))
    return generator


def build_train_dataloader(
    dataset: JsonlFineTuningDataset,
    collator: Callable[[Sequence[Mapping[str, Any]]], dict[str, torch.Tensor]],
    *,
    config: DataConfig,
    batch_size: int,
    seed: int,
    num_replicas: int,
    rank: int,
) -> tuple[DataLoader[Any], ResumableDistributedBatchSampler]:
    lengths = dataset.estimated_lengths() if config.length_bucketing else None
    sampler = ResumableDistributedBatchSampler(
        dataset_size=len(dataset),
        batch_size=batch_size,
        num_replicas=num_replicas,
        rank=rank,
        seed=seed,
        shuffle=True,
        drop_last=config.drop_last,
        lengths=lengths,
        bucket_size_multiplier=config.bucket_size_multiplier,
    )
    loader = DataLoader(
        dataset,
        batch_sampler=sampler,
        collate_fn=collator,
        pin_memory=bool(config.pin_memory),
        generator=_make_loader_generator(seed + 5_000_003 + rank),
        **_loader_worker_kwargs(
            num_workers=config.num_workers,
            persistent_workers=config.persistent_workers,
            prefetch_factor=config.prefetch_factor,
            timeout_seconds=config.loader_timeout_seconds,
        ),
    )
    return loader, sampler


def build_eval_dataloader(
    dataset: Dataset[Any],
    collator: Callable[[Sequence[Mapping[str, Any]]], dict[str, torch.Tensor]],
    *,
    config: DataConfig,
    batch_size: int,
    seed: int = 0,
) -> DataLoader[Any]:
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=False,
        drop_last=False,
        collate_fn=collator,
        pin_memory=bool(config.pin_memory),
        generator=_make_loader_generator(seed + 9_000_001),
        **_loader_worker_kwargs(
            num_workers=config.num_workers,
            persistent_workers=config.persistent_workers,
            prefetch_factor=config.prefetch_factor,
            timeout_seconds=config.loader_timeout_seconds,
        ),
    )


def _partition_world_groups(
    groups: Sequence[int],
    worlds_per_batch: int,
) -> list[list[int]]:
    chunks = [
        list(groups[start : start + worlds_per_batch])
        for start in range(0, len(groups), worlds_per_batch)
    ]
    if len(chunks) >= 2 and len(chunks[-1]) == 1:
        chunks[-1].insert(0, chunks[-2].pop())
    return [chunk for chunk in chunks if chunk]


def world_mixed_eval_batches(
    dataset: JsonlFineTuningDataset,
    *,
    batch_size: int,
) -> list[list[int]]:
    """Create batches containing same-world siblings and cross-world donors.

    Two records per world are placed into a batch whenever possible. This makes
    within-world shuffle a semantic no-op control while ensuring cross-world
    shuffle has a genuine donor. The ordering is deterministic and each record
    appears exactly once.
    """
    if batch_size < 2:
        raise ValueError("world-mixed evaluation requires batch_size >= 2.")
    by_world: dict[int, list[int]] = {}
    for index, group in enumerate(dataset.world_group_ids()):
        by_world.setdefault(int(group), []).append(index)
    worlds = sorted(by_world)
    if not worlds:
        return []
    per_world = 2 if batch_size >= 4 and any(len(by_world[w]) >= 2 for w in worlds) else 1
    worlds_per_batch = max(2, batch_size // per_world)
    world_chunks = _partition_world_groups(worlds, worlds_per_batch)
    batches: list[list[int]] = []
    for chunk in world_chunks:
        maximum = max(len(by_world[world]) for world in chunk)
        for offset in range(0, maximum, per_world):
            batch: list[int] = []
            for world in chunk:
                batch.extend(by_world[world][offset : offset + per_world])
            if batch:
                batches.append(batch[:batch_size])
    flattened = [index for batch in batches for index in batch]
    if sorted(flattened) != list(range(len(dataset))):
        raise RuntimeError("World-mixed batch construction lost or duplicated records.")
    return batches


def counterfactual_mixed_eval_batches(
    dataset: JsonlFineTuningDataset,
    *,
    batch_size: int,
) -> list[list[int]]:
    """Pack exact twin pairs together while retaining cross-pair donors.

    Every counterfactual group must contain exactly two records with opposite
    answer classes. Batches contain at least two pairs whenever possible, so the
    same assay can also evaluate generic cross-world donor controls.
    """
    if batch_size < 4:
        raise ValueError(
            "counterfactual necessity requires batch_size >= 4 (two twin pairs)."
        )
    by_pair: dict[int, list[int]] = {}
    for index, group in enumerate(dataset.counterfactual_group_ids()):
        by_pair.setdefault(int(group), []).append(index)
    pairs = sorted(by_pair)
    malformed = {pair: rows for pair, rows in by_pair.items() if len(rows) != 2}
    if malformed:
        preview = list(malformed.items())[:4]
        raise ValueError(
            "Every counterfactual_pair_id must occur exactly twice; malformed "
            f"groups include {preview}."
        )
    if len(pairs) < 2:
        raise ValueError(
            "Counterfactual necessity requires at least two complete twin pairs."
        )
    bad_labels: dict[int, list[int]] = {}
    for pair, rows in by_pair.items():
        labels = sorted(int(dataset[index].get("answer_class", -1)) for index in rows)
        if labels != [0, 1]:
            bad_labels[pair] = labels
    if bad_labels:
        raise ValueError(
            "Each counterfactual pair must contain answer_class 0 and 1; "
            f"malformed groups include {list(bad_labels.items())[:4]}."
        )
    pairs_per_batch = max(2, batch_size // 2)
    batches: list[list[int]] = []
    for start in range(0, len(pairs), pairs_per_batch):
        chunk = pairs[start : start + pairs_per_batch]
        if len(chunk) == 1 and batches:
            # Keep at least two semantic pairs in the final batch by moving one
            # pair from the previous batch. No record is duplicated.
            prior = batches.pop()
            moved = prior[-2:]
            prior = prior[:-2]
            if prior:
                batches.append(prior)
            batch = moved + by_pair[chunk[0]]
        else:
            batch = [index for pair in chunk for index in by_pair[pair]]
        batches.append(batch)
    flattened = [index for batch in batches for index in batch]
    if sorted(flattened) != list(range(len(dataset))):
        raise RuntimeError(
            "Counterfactual batch construction lost or duplicated records."
        )
    return batches


def build_necessity_dataloader(
    dataset: JsonlFineTuningDataset,
    collator: Callable[[Sequence[Mapping[str, Any]]], dict[str, torch.Tensor]],
    *,
    config: DataConfig,
    batch_size: int,
    seed: int,
    mix_worlds: bool,
    mix_counterfactual_pairs: bool = False,
) -> DataLoader[Any]:
    if mix_counterfactual_pairs:
        batches = counterfactual_mixed_eval_batches(
            dataset, batch_size=batch_size
        )
        return DataLoader(
            dataset,
            batch_sampler=batches,
            collate_fn=collator,
            pin_memory=bool(config.pin_memory),
            generator=_make_loader_generator(seed + 9_700_003),
            **_loader_worker_kwargs(
                num_workers=config.num_workers,
                persistent_workers=config.persistent_workers,
                prefetch_factor=config.prefetch_factor,
                timeout_seconds=config.loader_timeout_seconds,
            ),
        )
    if not mix_worlds:
        return build_eval_dataloader(
            dataset, collator, config=config, batch_size=batch_size, seed=seed
        )
    batches = world_mixed_eval_batches(dataset, batch_size=batch_size)
    return DataLoader(
        dataset,
        batch_sampler=batches,
        collate_fn=collator,
        pin_memory=bool(config.pin_memory),
        generator=_make_loader_generator(seed + 9_500_001),
        **_loader_worker_kwargs(
            num_workers=config.num_workers,
            persistent_workers=config.persistent_workers,
            prefetch_factor=config.prefetch_factor,
            timeout_seconds=config.loader_timeout_seconds,
        ),
    )


# =============================================================================
# Causal latent workspace and language-model wrapper
# =============================================================================


class CausalLatentWorkspace(nn.Module):
    """The v4.1 token-local recurrent control retained for ablation."""

    def __init__(
        self,
        input_dim: int,
        workspace_dim: int,
        steps: int,
        *,
        ff_multiplier: float = 2.0,
        dropout: float = 0.10,
        anchor_refresh: str = "every_step",
        **_: Any,
    ) -> None:
        super().__init__()
        if input_dim < 2 or workspace_dim < 2:
            raise ValueError("input_dim and workspace_dim must be at least 2.")
        if steps < 1:
            raise ValueError("steps must be positive.")
        if ff_multiplier <= 0:
            raise ValueError("ff_multiplier must be positive.")
        if not 0.0 <= dropout < 1.0:
            raise ValueError("dropout must be in [0, 1).")
        if anchor_refresh not in {"every_step", "first_step", "initial_only"}:
            raise ValueError("Unsupported anchor_refresh mode.")

        inner_dim = max(workspace_dim, int(round(workspace_dim * ff_multiplier)))
        self.input_dim = input_dim
        self.workspace_dim = workspace_dim
        self.steps = steps
        self.anchor_refresh = anchor_refresh

        self.input_norm = nn.LayerNorm(input_dim)
        self.input_projection = nn.Linear(input_dim, workspace_dim, bias=False)
        self.state_norm = nn.LayerNorm(workspace_dim)
        self.anchor_norm = nn.LayerNorm(workspace_dim)
        self.candidate_in = nn.Linear(workspace_dim, inner_dim)
        self.candidate_out = nn.Linear(inner_dim, workspace_dim)
        self.anchor_projection = nn.Linear(workspace_dim, workspace_dim, bias=False)
        self.gate_state = nn.Linear(workspace_dim, workspace_dim)
        self.gate_anchor = nn.Linear(workspace_dim, workspace_dim, bias=False)
        self.step_embeddings = nn.Parameter(torch.zeros(steps, workspace_dim))
        self.step_scales = nn.Parameter(torch.full((steps,), -1.5))
        self.dropout = nn.Dropout(dropout)

        nn.init.zeros_(self.candidate_out.weight)
        nn.init.zeros_(self.candidate_out.bias)
        nn.init.zeros_(self.anchor_projection.weight)
        nn.init.normal_(self.step_embeddings, mean=0.0, std=0.02)

    def _refresh_enabled(self, step: int) -> bool:
        if self.anchor_refresh == "every_step":
            return True
        if self.anchor_refresh == "first_step":
            return step == 0
        return False

    def forward(
        self,
        hidden_states: torch.Tensor,
        attention_mask: Optional[torch.Tensor] = None,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        del attention_mask
        if hidden_states.ndim != 3 or hidden_states.shape[-1] != self.input_dim:
            raise ValueError("hidden_states must have shape [B, L, input_dim].")
        anchor = self.input_projection(self.input_norm(hidden_states))
        state = anchor
        trajectory: list[torch.Tensor] = []
        normalized_anchor = self.anchor_norm(anchor)
        anchor_signal = self.anchor_projection(normalized_anchor)

        for step in range(self.steps):
            state_normalized = self.state_norm(state)
            step_signal = self.step_embeddings[step].view(1, 1, -1)
            refresh_scale = float(self._refresh_enabled(step))
            candidate = self.candidate_out(
                F.gelu(self.candidate_in(state_normalized + step_signal))
            )
            candidate = candidate + refresh_scale * anchor_signal
            gate_logits = (
                self.gate_state(state_normalized)
                + step_signal
                + refresh_scale * self.gate_anchor(normalized_anchor)
            )
            gate = torch.sigmoid(gate_logits)
            scale = torch.sigmoid(self.step_scales[step])
            state = state + scale * gate * self.dropout(candidate)
            trajectory.append(state)
        return torch.stack(trajectory, dim=2), anchor


class CausalBroadcastAttention(nn.Module):
    """Shared multi-head causal read over workspace states.

    The additive mask combines prefix causality, optional finite receptive field,
    and key padding. Padded query outputs are explicitly zeroed after SDPA.
    """

    def __init__(
        self,
        workspace_dim: int,
        heads: int,
        *,
        dropout: float = 0.0,
        causal_window: int = 0,
    ) -> None:
        super().__init__()
        if workspace_dim % heads != 0:
            raise ValueError("workspace_dim must be divisible by heads.")
        self.workspace_dim = workspace_dim
        self.heads = heads
        self.head_dim = workspace_dim // heads
        self.dropout = dropout
        self.causal_window = causal_window
        self.qkv = nn.Linear(workspace_dim, 3 * workspace_dim, bias=False)
        self.out = nn.Linear(workspace_dim, workspace_dim, bias=False)
        nn.init.zeros_(self.out.weight)

    def _allowed_mask(
        self,
        attention_mask: torch.Tensor,
        length: int,
    ) -> torch.Tensor:
        positions = torch.arange(length, device=attention_mask.device)
        query = positions[:, None]
        key = positions[None, :]
        allowed = key <= query
        if self.causal_window > 0:
            allowed = allowed & (key >= query - self.causal_window + 1)
        allowed = allowed[None, None, :, :]
        key_valid = attention_mask.to(torch.bool)[:, None, None, :]
        allowed = allowed & key_valid
        # A padded query in a finite window can otherwise have no legal key,
        # producing an all -inf SDPA row. Give such rows a harmless fallback;
        # their outputs are zeroed after attention.
        row_has_key = allowed.any(dim=-1, keepdim=True)
        fallback = torch.zeros_like(allowed)
        fallback[..., 0] = True
        return torch.where(row_has_key, allowed, fallback)

    def forward(
        self,
        state: torch.Tensor,
        attention_mask: torch.Tensor,
    ) -> torch.Tensor:
        B, L, W = state.shape
        qkv = self.qkv(state).view(B, L, 3, self.heads, self.head_dim)
        q, k, v = qkv.unbind(dim=2)
        q = q.transpose(1, 2)
        k = k.transpose(1, 2)
        v = v.transpose(1, 2)

        allowed = self._allowed_mask(attention_mask, L)
        additive = torch.zeros(
            (B, 1, L, L), device=state.device, dtype=q.dtype
        ).masked_fill(~allowed, float("-inf"))
        attended = F.scaled_dot_product_attention(
            q,
            k,
            v,
            attn_mask=additive,
            dropout_p=self.dropout if self.training else 0.0,
            is_causal=False,
        )
        attended = attended.transpose(1, 2).contiguous().view(B, L, W)
        output = self.out(attended)
        return output * attention_mask.to(output.dtype).unsqueeze(-1)


class CausalBroadcastLatentWorkspace(nn.Module):
    """A recurrent sequence-time × latent-time causal workspace.

    At each latent step, token t may read workspace states from positions <= t.
    The same attention/FFN weights are shared over K; learned step embeddings and
    scales index latent time without turning K into K separate transformer blocks.
    """

    def __init__(
        self,
        input_dim: int,
        workspace_dim: int,
        steps: int,
        *,
        ff_multiplier: float = 2.0,
        dropout: float = 0.10,
        anchor_refresh: str = "initial_only",
        attention_heads: int = 8,
        attention_dropout: float = 0.0,
        causal_window: int = 0,
    ) -> None:
        super().__init__()
        if input_dim < 2 or workspace_dim < 2 or steps < 1:
            raise ValueError("Invalid causal-broadcast workspace dimensions.")
        if anchor_refresh not in {"every_step", "first_step", "initial_only"}:
            raise ValueError("Unsupported anchor_refresh mode.")
        inner_dim = max(workspace_dim, int(round(workspace_dim * ff_multiplier)))
        self.input_dim = input_dim
        self.workspace_dim = workspace_dim
        self.steps = steps
        self.anchor_refresh = anchor_refresh

        self.input_norm = nn.LayerNorm(input_dim)
        self.input_projection = nn.Linear(input_dim, workspace_dim, bias=False)
        self.anchor_norm = nn.LayerNorm(workspace_dim)
        self.anchor_projection = nn.Linear(workspace_dim, workspace_dim, bias=False)

        self.attention_norm = nn.LayerNorm(workspace_dim)
        self.attention = CausalBroadcastAttention(
            workspace_dim,
            attention_heads,
            dropout=attention_dropout,
            causal_window=causal_window,
        )
        self.attention_gate = nn.Linear(workspace_dim, workspace_dim)
        self.attention_anchor_gate = nn.Linear(
            workspace_dim, workspace_dim, bias=False
        )
        self.attention_step_scales = nn.Parameter(torch.full((steps,), -1.5))

        self.ff_norm = nn.LayerNorm(workspace_dim)
        self.candidate_in = nn.Linear(workspace_dim, inner_dim)
        self.candidate_out = nn.Linear(inner_dim, workspace_dim)
        self.ff_gate = nn.Linear(workspace_dim, workspace_dim)
        self.ff_anchor_gate = nn.Linear(workspace_dim, workspace_dim, bias=False)
        self.ff_step_scales = nn.Parameter(torch.full((steps,), -1.5))

        self.step_embeddings = nn.Parameter(torch.zeros(steps, workspace_dim))
        self.dropout = nn.Dropout(dropout)
        nn.init.zeros_(self.attention.out.weight)
        nn.init.zeros_(self.candidate_out.weight)
        nn.init.zeros_(self.candidate_out.bias)
        nn.init.zeros_(self.anchor_projection.weight)
        nn.init.normal_(self.step_embeddings, mean=0.0, std=0.02)

    def _refresh_enabled(self, step: int) -> bool:
        if self.anchor_refresh == "every_step":
            return True
        if self.anchor_refresh == "first_step":
            return step == 0
        return False

    def forward(
        self,
        hidden_states: torch.Tensor,
        attention_mask: Optional[torch.Tensor] = None,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        if hidden_states.ndim != 3 or hidden_states.shape[-1] != self.input_dim:
            raise ValueError("hidden_states must have shape [B, L, input_dim].")
        if attention_mask is None:
            attention_mask = torch.ones(
                hidden_states.shape[:2],
                device=hidden_states.device,
                dtype=torch.long,
            )
        if attention_mask.shape != hidden_states.shape[:2]:
            raise ValueError("attention_mask must have shape [B, L].")

        anchor = self.input_projection(self.input_norm(hidden_states))
        state = anchor
        normalized_anchor = self.anchor_norm(anchor)
        anchor_signal = self.anchor_projection(normalized_anchor)
        valid = attention_mask.to(anchor.dtype).unsqueeze(-1)
        trajectory: list[torch.Tensor] = []

        for step in range(self.steps):
            step_signal = self.step_embeddings[step].view(1, 1, -1)
            refresh_scale = float(self._refresh_enabled(step))

            attention_input = self.attention_norm(state) + step_signal
            attention_update = self.attention(attention_input, attention_mask)
            attention_gate_logits = (
                self.attention_gate(attention_input)
                + refresh_scale * self.attention_anchor_gate(normalized_anchor)
            )
            attention_gate = torch.sigmoid(attention_gate_logits)
            attention_scale = torch.sigmoid(self.attention_step_scales[step])
            state = state + (
                attention_scale
                * attention_gate
                * self.dropout(attention_update)
            )

            ff_input = self.ff_norm(state) + step_signal
            ff_update = (
                self.candidate_out(F.gelu(self.candidate_in(ff_input)))
                + refresh_scale * anchor_signal
            )
            ff_gate_logits = (
                self.ff_gate(ff_input)
                + refresh_scale * self.ff_anchor_gate(normalized_anchor)
            )
            ff_gate = torch.sigmoid(ff_gate_logits)
            ff_scale = torch.sigmoid(self.ff_step_scales[step])
            state = state + ff_scale * ff_gate * self.dropout(ff_update)
            state = state * valid + anchor * (1.0 - valid)
            trajectory.append(state)

        return torch.stack(trajectory, dim=2), anchor


class LowRankWorkspaceLogitAdapter(nn.Module):
    """Maps the final workspace state to a low-rank residual over vocabulary."""

    def __init__(
        self,
        workspace_dim: int,
        vocab_size: int,
        rank: int,
    ) -> None:
        super().__init__()
        if rank < 1:
            raise ValueError("rank must be positive.")
        self.norm = nn.LayerNorm(workspace_dim)
        self.down = nn.Linear(workspace_dim, rank, bias=False)
        self.up = nn.Linear(rank, vocab_size, bias=False)
        nn.init.normal_(self.down.weight, mean=0.0, std=0.02)
        nn.init.zeros_(self.up.weight)

    def forward(self, final_state: torch.Tensor) -> torch.Tensor:
        return self.up(F.gelu(self.down(self.norm(final_state))))



class WorkspaceMemoryBridge(nn.Module):
    """Cross-attend a context-free continuation branch to workspace memory.

    Query states determine *where* to read, but all value content comes from the
    context workspace. There is deliberately no query residual inside the bridge
    state; a zero/mean/shuffled memory intervention therefore has a direct causal
    interpretation instead of leaving a hidden query-only bypass in this module.
    """

    def __init__(
        self,
        hidden_dim: int,
        workspace_dim: int,
        heads: int,
        *,
        dropout: float = 0.0,
    ) -> None:
        super().__init__()
        if workspace_dim % heads != 0:
            raise ValueError("workspace_dim must be divisible by bridge heads.")
        self.hidden_dim = int(hidden_dim)
        self.workspace_dim = int(workspace_dim)
        self.heads = int(heads)
        self.head_dim = workspace_dim // heads
        self.dropout = float(dropout)

        self.query_norm = nn.LayerNorm(hidden_dim)
        self.memory_norm = nn.LayerNorm(workspace_dim)
        self.query_projection = nn.Linear(hidden_dim, workspace_dim, bias=False)
        self.key_projection = nn.Linear(workspace_dim, workspace_dim, bias=False)
        self.value_projection = nn.Linear(workspace_dim, workspace_dim, bias=False)
        self.output_projection = nn.Linear(workspace_dim, workspace_dim, bias=False)

    def forward(
        self,
        query_hidden: torch.Tensor,
        query_attention_mask: torch.Tensor,
        memory: torch.Tensor,
        memory_attention_mask: torch.Tensor,
    ) -> torch.Tensor:
        if query_hidden.ndim != 3 or memory.ndim != 3:
            raise ValueError("query_hidden and memory must be rank-3 tensors.")
        B, Q, _ = query_hidden.shape
        Bm, M, W = memory.shape
        if Bm != B or W != self.workspace_dim:
            raise ValueError("Memory batch/dimension does not match bridge config.")
        if query_attention_mask.shape != (B, Q):
            raise ValueError("query_attention_mask must have shape [B, Q].")
        if memory_attention_mask.shape != (B, M):
            raise ValueError("memory_attention_mask must have shape [B, M].")

        q = self.query_projection(self.query_norm(query_hidden))
        k = self.key_projection(self.memory_norm(memory))
        v = self.value_projection(self.memory_norm(memory))
        q = q.view(B, Q, self.heads, self.head_dim).transpose(1, 2)
        k = k.view(B, M, self.heads, self.head_dim).transpose(1, 2)
        v = v.view(B, M, self.heads, self.head_dim).transpose(1, 2)

        allowed = memory_attention_mask.to(torch.bool)[:, None, None, :]
        row_has_key = allowed.any(dim=-1, keepdim=True)
        fallback = torch.zeros_like(allowed)
        fallback[..., 0] = True
        allowed = torch.where(row_has_key, allowed, fallback)
        additive = torch.zeros(
            (B, 1, Q, M), device=query_hidden.device, dtype=q.dtype
        ).masked_fill(~allowed.expand(B, 1, Q, M), float("-inf"))
        attended = F.scaled_dot_product_attention(
            q,
            k,
            v,
            attn_mask=additive,
            dropout_p=self.dropout if self.training else 0.0,
            is_causal=False,
        )
        attended = attended.transpose(1, 2).contiguous().view(B, Q, W)
        output = self.output_projection(attended)
        return output * query_attention_mask.to(output.dtype).unsqueeze(-1)



class FunctionalMemoryWriter(nn.Module):
    """Query-independent v9 memory writer.

    ``raw_sequence`` and ``projected_sequence`` preserve one memory token per
    context token. ``slots`` compresses the world into a fixed number of shared
    recurrent slots. The writer never receives a query tensor.
    """

    def __init__(
        self,
        hidden_dim: int,
        workspace_dim: int,
        *,
        mode: str,
        slot_count: int,
        steps: int,
        heads: int,
        dropout: float,
    ) -> None:
        super().__init__()
        self.hidden_dim = int(hidden_dim)
        self.workspace_dim = int(workspace_dim)
        self.mode = str(mode)
        self.slot_count = int(slot_count)
        self.steps = int(steps)
        if mode == "raw_sequence":
            self.output_dim = hidden_dim
            self.context_projection: nn.Module = nn.Identity()
        else:
            self.output_dim = workspace_dim
            self.context_projection = nn.Linear(hidden_dim, workspace_dim, bias=False)

        self.slot_seed = nn.Parameter(torch.zeros(slot_count, workspace_dim))
        nn.init.normal_(self.slot_seed, mean=0.0, std=0.02)
        self.slot_norm = nn.LayerNorm(workspace_dim)
        self.context_norm = nn.LayerNorm(workspace_dim)
        self.cross_attention = nn.MultiheadAttention(
            workspace_dim,
            heads,
            dropout=dropout,
            batch_first=True,
        )
        self.self_attention = nn.MultiheadAttention(
            workspace_dim,
            heads,
            dropout=dropout,
            batch_first=True,
        )
        self.ff_norm = nn.LayerNorm(workspace_dim)
        self.ff = nn.Sequential(
            nn.Linear(workspace_dim, workspace_dim * 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(workspace_dim * 2, workspace_dim),
        )
        self.dropout = nn.Dropout(dropout)

    def forward(
        self,
        context_hidden: torch.Tensor,
        context_attention_mask: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        if context_hidden.ndim != 3 or context_attention_mask.ndim != 2:
            raise ValueError("Functional writer expects [B,C,H] and [B,C].")
        valid = context_attention_mask.to(torch.bool)
        if not valid.any(dim=1).all():
            raise ValueError("Every functional context requires at least one token.")

        if self.mode in {"raw_sequence", "projected_sequence"}:
            memory = self.context_projection(context_hidden)
            memory = memory * valid.to(memory.dtype).unsqueeze(-1)
            trajectory = memory.unsqueeze(2).expand(
                -1, -1, self.steps, -1
            ).contiguous()
            return memory, valid.to(context_attention_mask.dtype), trajectory, memory

        if self.mode == "fixed_carrier":
            positions = torch.arange(
                self.slot_count * self.workspace_dim,
                device=context_hidden.device,
                dtype=torch.float32,
            ).reshape(self.slot_count, self.workspace_dim)
            carrier = torch.sin(positions * 0.017) + torch.cos(positions * 0.031)
            carrier = F.layer_norm(carrier, (self.workspace_dim,))
            memory = carrier.to(context_hidden.dtype).unsqueeze(0).expand(
                context_hidden.shape[0], -1, -1
            )
            mask = torch.ones(
                (context_hidden.shape[0], self.slot_count),
                device=context_hidden.device,
                dtype=context_attention_mask.dtype,
            )
            trajectory = memory.unsqueeze(2).expand(
                -1, -1, self.steps, -1
            ).contiguous()
            return memory, mask, trajectory, memory

        if self.mode != "slots":
            raise ValueError(f"Unsupported functional memory mode: {self.mode}")

        context = self.context_projection(context_hidden)
        context = self.context_norm(context)
        state = self.slot_seed.to(context.dtype).unsqueeze(0).expand(
            context.shape[0], -1, -1
        )
        anchor = state
        trajectory: list[torch.Tensor] = []
        key_padding = ~valid
        for _step in range(self.steps):
            cross, _ = self.cross_attention(
                self.slot_norm(state),
                context,
                context,
                key_padding_mask=key_padding,
                need_weights=False,
            )
            state = state + self.dropout(cross)
            self_read, _ = self.self_attention(
                self.slot_norm(state),
                self.slot_norm(state),
                self.slot_norm(state),
                need_weights=False,
            )
            state = state + self.dropout(self_read)
            state = state + self.dropout(self.ff(self.ff_norm(state)))
            trajectory.append(state)
        memory = trajectory[-1]
        mask = torch.ones(
            (context.shape[0], self.slot_count),
            device=context.device,
            dtype=context_attention_mask.dtype,
        )
        return memory, mask, torch.stack(trajectory, dim=2), anchor


class FunctionalMemoryReader(nn.Module):
    """Inject query-conditioned reads at a fixed transformer boundary."""

    def __init__(
        self,
        hidden_dim: int,
        memory_dim: int,
        *,
        heads: int,
        steps: int,
        dropout: float,
        injection_scale: float,
        gate_init_bias: float,
    ) -> None:
        super().__init__()
        if hidden_dim % heads != 0:
            raise ValueError("hidden_dim must be divisible by functional reader heads.")
        self.hidden_dim = int(hidden_dim)
        self.memory_dim = int(memory_dim)
        self.steps = int(steps)
        self.injection_scale = float(injection_scale)
        self.query_norm = nn.LayerNorm(hidden_dim)
        self.memory_norm = nn.LayerNorm(memory_dim)
        self.memory_projection = nn.Linear(memory_dim, hidden_dim, bias=False)
        self.attention = nn.MultiheadAttention(
            hidden_dim,
            heads,
            dropout=dropout,
            batch_first=True,
        )
        self.gate = nn.Linear(hidden_dim, 1)
        nn.init.zeros_(self.gate.weight)
        nn.init.constant_(self.gate.bias, gate_init_bias)
        # Exact query-only equality at initialization; the route opens only when
        # task or counterfactual supervision finds useful memory content.
        nn.init.zeros_(self.attention.out_proj.weight)
        if self.attention.out_proj.bias is not None:
            nn.init.zeros_(self.attention.out_proj.bias)

    def forward(
        self,
        query_hidden: torch.Tensor,
        query_attention_mask: torch.Tensor,
        memory: torch.Tensor,
        memory_attention_mask: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        if query_hidden.ndim != 3 or memory.ndim != 3:
            raise ValueError("Functional reader expects rank-3 query and memory tensors.")
        state = query_hidden
        projected_memory = self.memory_projection(self.memory_norm(memory))
        key_padding = ~memory_attention_mask.to(torch.bool)
        gate_values: list[torch.Tensor] = []
        read_norms: list[torch.Tensor] = []
        for _step in range(self.steps):
            read, _ = self.attention(
                self.query_norm(state),
                projected_memory,
                projected_memory,
                key_padding_mask=key_padding,
                need_weights=False,
            )
            gate = torch.sigmoid(self.gate(self.query_norm(state)))
            valid_query = query_attention_mask.to(state.dtype).unsqueeze(-1)
            route_update = self.injection_scale * gate.to(read.dtype) * read
            state = state + route_update * valid_query
            gate_values.append(gate)
            read_norms.append(read.float().norm(dim=-1).mean())
        return (
            state,
            torch.stack(gate_values).mean(),
            torch.stack(read_norms).mean(),
        )


class FunctionalBoundaryAdapter:
    """No-cache split decoder for the supported causal-LM layouts.

    GPT-2 remains the compatibility path used by the v9 harness. Mistral is a
    strict adapter because its mask and decoder-layer APIs changed between the
    two Transformers releases supported by this source. Unknown Mistral API
    versions fail closed instead of silently changing the split computation.

    Decoder layers are invoked through ``module(...)`` rather than ``forward``.
    Transformers' ``GradientCheckpointingLayer.__call__`` can therefore retain
    activation checkpointing while the model is split at an internal boundary.
    """

    _MISTRAL_TRANSFORMERS_VERSIONS = frozenset({"4.57.6", "5.15.0"})

    def __init__(self, base_model: nn.Module) -> None:
        self.base_model = base_model
        custom_to = getattr(base_model, "functional_forward_to_boundary", None)
        custom_from = getattr(base_model, "functional_forward_from_boundary", None)
        custom_layers = getattr(base_model, "functional_num_layers", None)
        if callable(custom_to) and callable(custom_from) and custom_layers is not None:
            self._kind = "custom"
            return

        model_type = str(getattr(getattr(base_model, "config", None), "model_type", ""))
        if model_type == "mistral":
            self._kind = "mistral"
            self._validate_mistral_layout()
            return

        transformer = getattr(base_model, "transformer", None)
        if model_type == "gpt2" or (
            transformer is not None and getattr(transformer, "h", None) is not None
        ):
            self._kind = "gpt2"
            return

        raise TypeError(
            "functional_workspace requires model_type='gpt2', "
            "model_type='mistral', or a complete custom functional split interface."
        )

    @staticmethod
    def _validate_boundary(boundary_layer: int, layer_count: int) -> int:
        boundary = int(boundary_layer)
        if not 0 <= boundary <= layer_count:
            raise ValueError(
                f"boundary_layer={boundary} outside [0, {layer_count}]."
            )
        return boundary

    def _validate_mistral_layout(self) -> None:
        try:
            import transformers
        except ImportError as exc:
            raise RuntimeError(
                "The Mistral functional boundary adapter requires Transformers."
            ) from exc

        version = str(transformers.__version__)
        if version not in self._MISTRAL_TRANSFORMERS_VERSIONS:
            supported = ", ".join(sorted(self._MISTRAL_TRANSFORMERS_VERSIONS))
            raise RuntimeError(
                "Unsupported Transformers version for the strict Mistral split "
                f"adapter: {version!r}; expected exactly one of {supported}."
            )

        decoder = getattr(self.base_model, "model", None)
        required = ("embed_tokens", "layers", "rotary_emb", "norm")
        missing = [name for name in required if getattr(decoder, name, None) is None]
        if missing:
            raise TypeError(
                "Mistral split adapter could not locate decoder components: "
                + ", ".join(missing)
            )
        configured_layers = getattr(getattr(decoder, "config", None), "num_hidden_layers", None)
        if configured_layers is None or int(configured_layers) != len(decoder.layers):
            raise ValueError(
                "Mistral decoder layer count does not match config.num_hidden_layers."
            )
        if self._lm_head() is None:
            raise ValueError("Mistral split adapter could not locate lm_head.")
        self._mistral_transformers_version = version

    def _lm_head(self) -> Optional[nn.Module]:
        head = getattr(self.base_model, "lm_head", None)
        if head is not None:
            return head
        getter = getattr(self.base_model, "get_output_embeddings", None)
        return getter() if callable(getter) else None

    def layer_count(self) -> int:
        if self._kind == "custom":
            return int(self.base_model.functional_num_layers)
        if self._kind == "mistral":
            return len(self.base_model.model.layers)
        transformer = getattr(self.base_model, "transformer", None)
        blocks = getattr(transformer, "h", None)
        if blocks is None:
            raise TypeError("GPT-2 split adapter could not locate transformer.h.")
        return len(blocks)

    @staticmethod
    def _legacy_gpt2_attention_mask(
        attention_mask: torch.Tensor,
        dtype: torch.dtype,
    ) -> torch.Tensor:
        expanded = attention_mask[:, None, None, :].to(dtype=dtype)
        return (1.0 - expanded) * torch.finfo(dtype).min

    @staticmethod
    def _position_tensors(hidden: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        cache_position = torch.arange(hidden.shape[1], device=hidden.device)
        return cache_position, cache_position.unsqueeze(0)

    @classmethod
    def _gpt2_causal_mask(
        cls,
        transformer: nn.Module,
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
        cache_position: torch.Tensor,
        position_ids: torch.Tensor,
    ) -> torch.Tensor:
        try:
            from transformers.masking_utils import create_causal_mask

            parameters = inspect.signature(create_causal_mask).parameters
            kwargs: dict[str, Any] = {
                "config": transformer.config,
                "attention_mask": attention_mask,
                "past_key_values": None,
                "position_ids": position_ids,
            }
            if "inputs_embeds" in parameters:
                kwargs["inputs_embeds"] = hidden
            elif "input_embeds" in parameters:
                kwargs["input_embeds"] = hidden
            else:
                raise TypeError("Unknown Transformers causal-mask embedding API.")
            if "cache_position" in parameters:
                kwargs["cache_position"] = cache_position
            return create_causal_mask(**kwargs)
        except (ImportError, TypeError):
            # Compatibility with the pre-mask-utils GPT-2 releases used by v9.
            return cls._legacy_gpt2_attention_mask(attention_mask, hidden.dtype)

    @staticmethod
    def _call_gpt2_block(
        block: nn.Module,
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
        cache_position: torch.Tensor,
        position_ids: torch.Tensor,
    ) -> torch.Tensor:
        parameters = inspect.signature(block.forward).parameters
        attempts: tuple[dict[str, Any], ...]
        if "cache_position" in parameters:
            attempts = ({
                "past_key_values": None,
                "cache_position": cache_position,
                "attention_mask": attention_mask,
                "head_mask": None,
                "encoder_hidden_states": None,
                "encoder_attention_mask": None,
                "use_cache": False,
                "output_attentions": False,
            }, {
                "layer_past": None,
                "attention_mask": attention_mask,
                "head_mask": None,
                "encoder_hidden_states": None,
                "encoder_attention_mask": None,
                "use_cache": False,
                "output_attentions": False,
            }, {
                "attention_mask": attention_mask,
                "use_cache": False,
                "output_attentions": False,
            }, {"attention_mask": attention_mask})
        else:
            # Transformers 5.x GPT-2 passes the already combined causal mask
            # and sequential position IDs to each block. Avoid sending legacy
            # head/cache keywords through ``**kwargs`` into the attention API.
            attempts = ({
                "past_key_values": None,
                "attention_mask": attention_mask,
                "encoder_hidden_states": None,
                "encoder_attention_mask": None,
                "use_cache": False,
                "position_ids": position_ids,
            },)
        last_error: Optional[Exception] = None
        for kwargs in attempts:
            try:
                output = block(hidden, **kwargs)
                return output[0] if isinstance(output, (tuple, list)) else output
            except TypeError as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    def _gpt2_encode(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor,
        boundary_layer: int,
    ) -> torch.Tensor:
        transformer = self.base_model.transformer
        blocks = transformer.h
        boundary = self._validate_boundary(boundary_layer, len(blocks))
        token_embeddings = transformer.wte(input_ids)
        cache_position, position_ids = self._position_tensors(token_embeddings)
        hidden = token_embeddings + transformer.wpe(position_ids).to(token_embeddings.device)
        hidden = transformer.drop(hidden)
        causal_mask = self._gpt2_causal_mask(
            transformer, token_embeddings, attention_mask, cache_position, position_ids
        )
        for block in blocks[:boundary]:
            hidden = self._call_gpt2_block(
                block, hidden, causal_mask, cache_position, position_ids
            )
        return hidden

    def _gpt2_decode(
        self,
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
        boundary_layer: int,
    ) -> torch.Tensor:
        transformer = self.base_model.transformer
        blocks = transformer.h
        boundary = self._validate_boundary(boundary_layer, len(blocks))
        cache_position, position_ids = self._position_tensors(hidden)
        causal_mask = self._gpt2_causal_mask(
            transformer, hidden, attention_mask, cache_position, position_ids
        )
        for block in blocks[boundary:]:
            hidden = self._call_gpt2_block(
                block, hidden, causal_mask, cache_position, position_ids
            )
        head = self._lm_head()
        if head is None:
            raise ValueError("GPT-2 split adapter could not locate lm_head.")
        return head(transformer.ln_f(hidden))

    def _mistral_runtime(
        self,
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, tuple[torch.Tensor, torch.Tensor]]:
        from transformers.masking_utils import (
            create_causal_mask,
            create_sliding_window_causal_mask,
        )

        decoder = self.base_model.model
        cache_position, position_ids = self._position_tensors(hidden)
        mask_function = (
            create_causal_mask
            if decoder.config.sliding_window is None
            else create_sliding_window_causal_mask
        )
        common = {
            "config": decoder.config,
            "attention_mask": attention_mask,
            "past_key_values": None,
            "position_ids": position_ids,
        }
        if self._mistral_transformers_version == "4.57.6":
            causal_mask = mask_function(
                input_embeds=hidden,
                cache_position=cache_position,
                **common,
            )
        else:
            causal_mask = mask_function(inputs_embeds=hidden, **common)
        position_embeddings = decoder.rotary_emb(
            hidden, position_ids=position_ids
        )
        return causal_mask, position_ids, position_embeddings

    def _run_mistral_layers(
        self,
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
        layers: Sequence[nn.Module],
    ) -> torch.Tensor:
        causal_mask, position_ids, position_embeddings = self._mistral_runtime(
            hidden, attention_mask
        )
        cache_position = torch.arange(hidden.shape[1], device=hidden.device)
        for layer in layers:
            kwargs: dict[str, Any] = {
                "attention_mask": causal_mask,
                "position_ids": position_ids,
                "past_key_values": None,
                "use_cache": False,
                "position_embeddings": position_embeddings,
            }
            if self._mistral_transformers_version == "4.57.6":
                kwargs["cache_position"] = cache_position
            output = layer(hidden, **kwargs)
            hidden = output[0] if isinstance(output, (tuple, list)) else output
        return hidden

    def _mistral_encode(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor,
        boundary_layer: int,
    ) -> torch.Tensor:
        decoder = self.base_model.model
        boundary = self._validate_boundary(boundary_layer, len(decoder.layers))
        hidden = decoder.embed_tokens(input_ids)
        return self._run_mistral_layers(
            hidden, attention_mask, decoder.layers[:boundary]
        )

    def _mistral_decode(
        self,
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
        boundary_layer: int,
    ) -> torch.Tensor:
        decoder = self.base_model.model
        boundary = self._validate_boundary(boundary_layer, len(decoder.layers))
        hidden = self._run_mistral_layers(
            hidden, attention_mask, decoder.layers[boundary:]
        )
        head = self._lm_head()
        assert head is not None
        return head(decoder.norm(hidden))

    def encode(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor,
        boundary_layer: int,
    ) -> torch.Tensor:
        if self._kind == "custom":
            boundary = self._validate_boundary(boundary_layer, self.layer_count())
            return self.base_model.functional_forward_to_boundary(
                input_ids, attention_mask, boundary
            )
        if self._kind == "mistral":
            return self._mistral_encode(input_ids, attention_mask, boundary_layer)
        return self._gpt2_encode(input_ids, attention_mask, boundary_layer)

    def decode(
        self,
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
        boundary_layer: int,
    ) -> torch.Tensor:
        if self._kind == "custom":
            boundary = self._validate_boundary(boundary_layer, self.layer_count())
            return self.base_model.functional_forward_from_boundary(
                hidden, attention_mask, boundary
            )
        if self._kind == "mistral":
            return self._mistral_decode(hidden, attention_mask, boundary_layer)
        return self._gpt2_decode(hidden, attention_mask, boundary_layer)


class LatentWorkspaceCausalLM(nn.Module):
    """Wraps a causal LM with a configurable recurrent latent workspace.

    The base model produces its ordinary logits. A forward hook captures the
    exact hidden tensor entering the model's output embedding, avoiding the
    memory cost of returning every layer's hidden state. The workspace then
    creates a zero-initialized low-rank residual over the vocabulary.
    """

    def __init__(
        self,
        base_model: nn.Module,
        hidden_dim: int,
        vocab_size: int,
        config: WorkspaceConfig,
        *,
        functional_config: Optional[FunctionalWorkspaceConfig] = None,
        hidden_capture: str = "hook",
        base_activation_offload: str = "legacy_functional",
    ) -> None:
        super().__init__()
        if hidden_capture not in {"hook", "hidden_states"}:
            raise ValueError("hidden_capture must be hook or hidden_states.")
        if base_activation_offload not in {
            "disabled",
            "legacy_functional",
            "all_base",
        }:
            raise ValueError(
                "base_activation_offload must be disabled, legacy_functional, "
                "or all_base."
            )

        self.base_model = base_model
        self.hidden_dim = hidden_dim
        self.vocab_size = vocab_size
        self.workspace_config = config
        self.functional_config = functional_config or FunctionalWorkspaceConfig()
        self.hidden_capture = hidden_capture
        self.base_activation_offload = base_activation_offload

        workspace_cls: type[nn.Module]
        if config.architecture == "causal_broadcast":
            workspace_cls = CausalBroadcastLatentWorkspace
        else:
            workspace_cls = CausalLatentWorkspace
        self.workspace = workspace_cls(
            input_dim=hidden_dim,
            workspace_dim=config.workspace_dim,
            steps=config.steps,
            ff_multiplier=config.ff_multiplier,
            dropout=config.dropout,
            anchor_refresh=config.anchor_refresh,
            attention_heads=config.attention_heads,
            attention_dropout=config.attention_dropout,
            causal_window=config.causal_window,
        )
        self.logit_adapter = LowRankWorkspaceLogitAdapter(
            workspace_dim=config.workspace_dim,
            vocab_size=vocab_size,
            rank=config.logit_rank,
        )
        self.memory_bridge = WorkspaceMemoryBridge(
            hidden_dim=hidden_dim,
            workspace_dim=config.workspace_dim,
            heads=config.bridge_heads,
            dropout=config.bridge_dropout,
        )
        if self.functional_config.enabled:
            self.functional_writer: Optional[FunctionalMemoryWriter] = (
                FunctionalMemoryWriter(
                    hidden_dim=hidden_dim,
                    workspace_dim=config.workspace_dim,
                    mode=self.functional_config.memory_mode,
                    slot_count=self.functional_config.slot_count,
                    steps=self.functional_config.writer_steps,
                    heads=self.functional_config.writer_heads,
                    dropout=self.functional_config.dropout,
                )
            )
            functional_memory_dim = self.functional_writer.output_dim
            self.functional_reader: Optional[FunctionalMemoryReader] = (
                FunctionalMemoryReader(
                    hidden_dim=hidden_dim,
                    memory_dim=functional_memory_dim,
                    heads=self.functional_config.reader_heads,
                    steps=self.functional_config.reader_steps,
                    dropout=self.functional_config.dropout,
                    injection_scale=self.functional_config.injection_scale,
                    gate_init_bias=self.functional_config.gate_init_bias,
                )
            )
            self.functional_loss_projection: Optional[nn.Module]
            if functional_memory_dim == config.workspace_dim:
                self.functional_loss_projection = nn.Identity()
            else:
                self.functional_loss_projection = nn.Linear(
                    functional_memory_dim, config.workspace_dim, bias=False
                )
            self.functional_boundary_adapter: Optional[FunctionalBoundaryAdapter] = (
                FunctionalBoundaryAdapter(base_model)
            )
        else:
            self.functional_writer = None
            self.functional_reader = None
            self.functional_loss_projection = None
            self.functional_boundary_adapter = None
        self.gate_norm = nn.LayerNorm(hidden_dim)
        self.gate = nn.Linear(hidden_dim, 1)
        nn.init.zeros_(self.gate.weight)
        nn.init.constant_(self.gate.bias, config.gate_init_bias)

        loss_cfg = config.loss
        projection_dim = min(loss_cfg.projection_dim, config.workspace_dim)
        self.workspace_loss = LatentWorkspaceLoss(
            hidden_dim=config.workspace_dim,
            projection_dim=projection_dim,
            variance_target=loss_cfg.variance_target,
            eps=loss_cfg.eps,
            contrastive_temperature=loss_cfg.contrastive_temperature,
            worst_step_temperature=loss_cfg.worst_step_temperature,
            temporal_drift_margin=loss_cfg.temporal_drift_margin,
            probe_dropout=loss_cfg.probe_dropout,
            lambda_var=loss_cfg.lambda_var,
            lambda_cov=loss_cfg.lambda_cov,
            lambda_info=loss_cfg.lambda_info,
            lambda_contrast=loss_cfg.lambda_contrast,
            lambda_relation=loss_cfg.lambda_relation,
            lambda_temporal=loss_cfg.lambda_temporal,
            lambda_worst=loss_cfg.lambda_worst,
            lambda_rank=loss_cfg.lambda_rank,
        )

        step_weights = self._make_step_weights(config)
        self.register_buffer("workspace_step_weights", step_weights, persistent=True)

    @staticmethod
    def _make_step_weights(config: WorkspaceConfig) -> torch.Tensor:
        if config.step_weighting == "uniform":
            return torch.ones(config.steps, dtype=torch.float32)
        position = torch.linspace(-1.0, 1.0, config.steps)
        sigma = max(float(config.middle_sigma), 1e-4)
        return torch.exp(-0.5 * (position / sigma).square())

    def get_base_output_embeddings(self) -> nn.Module:
        getter = getattr(self.base_model, "get_output_embeddings", None)
        if getter is None:
            raise AttributeError("The base model has no get_output_embeddings method.")
        head = getter()
        if head is None:
            raise ValueError("The base model returned no output embedding module.")
        return head

    def _base_activation_offload_context(
        self,
        device: torch.device,
        *,
        legacy_region: bool = False,
    ) -> Any:
        enabled = self.base_activation_offload == "all_base" or (
            self.base_activation_offload == "legacy_functional" and legacy_region
        )
        if not enabled:
            return contextlib.nullcontext()
        return _cuda_base_activation_offload(device)

    def _base_forward_with_hidden_capture(
        self,
        input_ids: torch.Tensor,
        attention_mask: Optional[torch.Tensor],
    ) -> tuple[Any, torch.Tensor]:
        common_kwargs = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "use_cache": False,
            "return_dict": True,
        }

        if self.hidden_capture == "hidden_states":
            with self._base_activation_offload_context(input_ids.device):
                outputs = self.base_model(output_hidden_states=True, **common_kwargs)
            hidden_states = getattr(outputs, "hidden_states", None)
            if not hidden_states:
                raise RuntimeError("The base model did not return hidden_states.")
            return outputs, hidden_states[-1]

        captured: dict[str, torch.Tensor] = {}

        def capture_input(
            _module: nn.Module,
            args: tuple[Any, ...],
        ) -> None:
            if not args or not isinstance(args[0], torch.Tensor):
                raise RuntimeError("Could not capture the output-head input tensor.")
            captured["hidden"] = args[0]

        head = self.get_base_output_embeddings()
        handle = head.register_forward_pre_hook(capture_input)
        try:
            with self._base_activation_offload_context(input_ids.device):
                outputs = self.base_model(output_hidden_states=False, **common_kwargs)
        finally:
            handle.remove()

        hidden = captured.get("hidden")
        if hidden is None:
            raise RuntimeError(
                "The output embedding hook did not fire. Set model.hidden_capture "
                "to 'hidden_states' for this architecture."
            )
        return outputs, hidden

    def _supervised_task_loss(
        self,
        base_logits: torch.Tensor,
        final_state: torch.Tensor,
        gate: torch.Tensor,
        labels: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        if base_logits.ndim != 3 or labels.ndim != 2:
            raise ValueError("base_logits must be [B, L, V] and labels must be [B, L].")
        targets = labels[:, 1:]
        supervised = targets.ne(-100)
        supervised_tokens = supervised.sum()
        if int(supervised_tokens.item()) == 0:
            raise ValueError("The batch contains no supervised next-token targets.")

        selected_base = base_logits[:, :-1, :][supervised]
        selected_state = final_state[:, :-1, :][supervised]
        selected_gate = gate[:, :-1, :][supervised]
        selected_targets = targets[supervised]

        base_token_nll = F.cross_entropy(
            selected_base, selected_targets, reduction="none"
        )
        base_nll_sum = base_token_nll.sum()

        scale = float(self.workspace_config.logit_residual_scale)
        selected_delta: Optional[torch.Tensor]
        if scale == 0.0:
            selected_delta = None
            adapted_token_nll = base_token_nll
        else:
            selected_delta = self.logit_adapter(selected_state)
            adapted = (
                selected_base
                + scale * selected_gate.to(selected_delta.dtype) * selected_delta
            )
            adapted_token_nll = F.cross_entropy(
                adapted, selected_targets, reduction="none"
            )
        nll_sum = adapted_token_nll.sum()
        mean_loss = nll_sum / supervised_tokens.to(nll_sum.dtype)

        B = labels.shape[0]
        token_rows = torch.nonzero(supervised, as_tuple=False)[:, 0]
        per_example_nll = torch.zeros(B, device=nll_sum.device, dtype=nll_sum.dtype)
        per_example_base_nll = torch.zeros_like(per_example_nll)
        per_example_tokens = torch.zeros(B, device=nll_sum.device, dtype=torch.long)
        per_example_nll.scatter_add_(0, token_rows, adapted_token_nll)
        per_example_base_nll.scatter_add_(0, token_rows, base_token_nll)
        per_example_tokens.scatter_add_(
            0, token_rows, torch.ones_like(token_rows, dtype=torch.long)
        )

        if selected_delta is None:
            delta_norm = nll_sum.detach() * 0.0
            gated_delta_norm = nll_sum.detach() * 0.0
        else:
            delta_norm = selected_delta.float().norm(dim=-1).mean()
            gated_delta_norm = (
                scale * selected_gate.float() * selected_delta.float()
            ).norm(dim=-1).mean()

        return {
            "task_loss": mean_loss,
            "task_nll_sum": nll_sum,
            "base_nll_sum": base_nll_sum,
            "supervised_tokens": supervised_tokens,
            "per_example_nll": per_example_nll,
            "per_example_base_nll": per_example_base_nll,
            "per_example_tokens": per_example_tokens,
            "delta_logit_norm": delta_norm,
            "gated_delta_logit_norm": gated_delta_norm,
        }

    def _base_only_task_loss(
        self,
        base_logits: torch.Tensor,
        labels: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        """Compute the ordinary causal-LM objective without touching workspace."""
        targets = labels[:, 1:]
        supervised = targets.ne(-100)
        supervised_tokens = supervised.sum()
        if int(supervised_tokens.item()) == 0:
            raise ValueError("The batch contains no supervised next-token targets.")
        selected_base = base_logits[:, :-1, :][supervised]
        selected_targets = targets[supervised]
        token_nll = F.cross_entropy(selected_base, selected_targets, reduction="none")
        nll_sum = token_nll.sum()
        mean_loss = nll_sum / supervised_tokens.to(nll_sum.dtype)

        B = labels.shape[0]
        token_rows = torch.nonzero(supervised, as_tuple=False)[:, 0]
        per_example_nll = torch.zeros(B, device=nll_sum.device, dtype=nll_sum.dtype)
        per_example_tokens = torch.zeros(B, device=nll_sum.device, dtype=torch.long)
        per_example_nll.scatter_add_(0, token_rows, token_nll)
        per_example_tokens.scatter_add_(
            0, token_rows, torch.ones_like(token_rows, dtype=torch.long)
        )
        zero = nll_sum.detach() * 0.0
        return {
            "task_loss": mean_loss,
            "task_nll_sum": nll_sum,
            "base_nll_sum": nll_sum,
            "supervised_tokens": supervised_tokens,
            "per_example_nll": per_example_nll,
            "per_example_base_nll": per_example_nll,
            "per_example_tokens": per_example_tokens,
            "delta_logit_norm": zero,
            "gated_delta_logit_norm": zero,
        }

    @staticmethod
    def _zero_workspace_stats(reference: torch.Tensor) -> dict[str, torch.Tensor]:
        zero = reference.detach().sum() * 0.0
        return {
            "loss": zero,
            "loss_var": zero,
            "loss_cov": zero,
            "loss_info": zero,
            "loss_contrast": zero,
            "loss_relation": zero,
            "loss_temporal": zero,
            "loss_worst": zero,
            "loss_rank": zero,
            "retention_cosine": zero,
            "relative_effective_rank": zero,
            "mean_temporal_drift": zero,
            "state_anchor_cosine": zero,
            "final_state_anchor_cosine": zero,
            "mean_departure_l2": zero,
            "final_departure_l2": zero,
            "mean_update_l2": zero,
            "path_length": zero,
            "net_displacement": zero,
            "tortuosity": zero,
            "contrastive_valid_fraction": zero,
            "contrastive_negative_pairs": zero,
        }

    def _adapt_logit_slice(
        self,
        base_logits: torch.Tensor,
        final_state: torch.Tensor,
        gate: torch.Tensor,
    ) -> torch.Tensor:
        scale = float(self.workspace_config.logit_residual_scale)
        if scale == 0.0:
            return base_logits
        delta = self.logit_adapter(final_state)
        return base_logits + scale * gate.to(delta.dtype) * delta

    def _workspace_scope_mask(
        self,
        attention_mask: torch.Tensor,
        labels: Optional[torch.Tensor],
        prompt_mask: Optional[torch.Tensor],
        context_mask: Optional[torch.Tensor] = None,
        query_mask: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        valid = attention_mask.to(torch.bool)
        scope = self.workspace_config.scope

        if scope == "all":
            return valid

        if prompt_mask is None:
            prompt = torch.zeros_like(valid)
        else:
            prompt = prompt_mask.to(device=valid.device, dtype=torch.bool) & valid

        context = (
            torch.zeros_like(valid)
            if context_mask is None
            else context_mask.to(device=valid.device, dtype=torch.bool) & valid
        )
        query = (
            torch.zeros_like(valid)
            if query_mask is None
            else query_mask.to(device=valid.device, dtype=torch.bool) & valid
        )

        if scope == "prompt":
            mask = prompt
        elif scope == "context":
            mask = context
        elif scope == "context_tail":
            mask = torch.zeros_like(valid)
            tail = max(1, int(self.workspace_config.prompt_tail_tokens))
            for row in range(valid.shape[0]):
                indices = torch.nonzero(context[row], as_tuple=False).flatten()
                if indices.numel() > 0:
                    mask[row, indices[-tail:]] = True
        elif scope == "prequery_boundary":
            mask = torch.zeros_like(valid)
            for row in range(valid.shape[0]):
                indices = torch.nonzero(context[row], as_tuple=False).flatten()
                if indices.numel() > 0:
                    mask[row, indices[-1]] = True
        elif scope == "query":
            mask = query
        elif scope == "response":
            mask = valid & ~prompt
        elif scope == "boundary":
            mask = torch.zeros_like(valid)
            for row in range(valid.shape[0]):
                indices = torch.nonzero(prompt[row], as_tuple=False).flatten()
                if indices.numel() > 0:
                    mask[row, indices[-1]] = True
        elif scope == "prompt_tail":
            mask = torch.zeros_like(valid)
            tail = max(1, int(self.workspace_config.prompt_tail_tokens))
            for row in range(valid.shape[0]):
                indices = torch.nonzero(prompt[row], as_tuple=False).flatten()
                if indices.numel() > 0:
                    mask[row, indices[-tail:]] = True
        elif scope == "supervised":
            if labels is None:
                mask = valid
            else:
                mask = torch.zeros_like(valid)
                mask[:, :-1] = labels[:, 1:].ne(-100) & valid[:, :-1]
        else:
            raise RuntimeError(f"Unsupported workspace scope: {scope}")

        empty_rows = ~mask.any(dim=1)
        deferred_scopes = {"context", "context_tail", "prequery_boundary", "query"}
        if empty_rows.any() and scope in deferred_scopes:
            rows = torch.nonzero(empty_rows, as_tuple=False).flatten().tolist()
            raise ValueError(
                f"Deferred workspace scope {scope!r} has no marked tokens for "
                f"batch rows {rows}. Use plain context/query records, preserve "
                "the segment through truncation, or choose a non-deferred scope."
            )
        # Generic text records may not expose a prompt region. Only non-deferred
        # scopes retain the historical fallback to all valid causal states.
        if empty_rows.any():
            mask[empty_rows] = valid[empty_rows]
        return mask

    def _sample_workspace_states(
        self,
        latents: torch.Tensor,
        anchor: torch.Tensor,
        mask: torch.Tensor,
        group_ids: Optional[torch.Tensor] = None,
    ) -> tuple[torch.Tensor, torch.Tensor, Optional[torch.Tensor]]:
        if latents.ndim != 4 or anchor.ndim != 3 or mask.ndim != 2:
            raise ValueError("Unexpected workspace sampling shapes.")
        B, L, K, W = latents.shape
        if anchor.shape != (B, L, W) or mask.shape != (B, L):
            raise ValueError("Workspace sampling tensors are not aligned.")
        if group_ids is not None and (group_ids.ndim != 1 or group_ids.numel() != B):
            raise ValueError("group_ids must have shape [B].")

        selected_rows: list[torch.Tensor] = []
        selected_cols: list[torch.Tensor] = []
        per_example = max(1, int(self.workspace_config.tokens_per_example))

        for row in range(B):
            indices = torch.nonzero(mask[row], as_tuple=False).flatten()
            if indices.numel() == 0:
                continue
            if indices.numel() > per_example:
                if self.training:
                    permutation = torch.randperm(indices.numel(), device=indices.device)
                    indices = indices[permutation[:per_example]]
                else:
                    positions = torch.linspace(
                        0, indices.numel() - 1, per_example, device=indices.device
                    ).round().long()
                    indices = indices[positions]
            selected_rows.append(torch.full_like(indices, row))
            selected_cols.append(indices)

        if not selected_rows:
            sampled_groups = None if group_ids is None else group_ids[:1].repeat(B)
            return (
                latents[:, :1].reshape(-1, K, W),
                anchor[:, :1].reshape(-1, W),
                sampled_groups,
            )

        row_index = torch.cat(selected_rows)
        col_index = torch.cat(selected_cols)
        maximum = max(1, int(self.workspace_config.max_tokens_per_batch))
        if row_index.numel() > maximum:
            if self.training:
                permutation = torch.randperm(row_index.numel(), device=row_index.device)
                keep = permutation[:maximum]
            else:
                keep = torch.linspace(
                    0, row_index.numel() - 1, maximum, device=row_index.device
                ).round().long()
            row_index = row_index[keep]
            col_index = col_index[keep]

        sampled_groups = None if group_ids is None else group_ids[row_index]
        return latents[row_index, col_index], anchor[row_index, col_index], sampled_groups

    def _bridge_scope_mask(self, attention_mask: torch.Tensor) -> torch.Tensor:
        valid = attention_mask.to(torch.bool)
        scope = self.workspace_config.scope
        if scope in {"all", "context"}:
            return valid
        if scope in {"context_tail", "prompt_tail"}:
            mask = torch.zeros_like(valid)
            tail = max(1, int(self.workspace_config.prompt_tail_tokens))
            for row in range(valid.shape[0]):
                indices = torch.nonzero(valid[row], as_tuple=False).flatten()
                if indices.numel() > 0:
                    mask[row, indices[-tail:]] = True
            return mask
        if scope in {"prequery_boundary", "boundary"}:
            mask = torch.zeros_like(valid)
            for row in range(valid.shape[0]):
                indices = torch.nonzero(valid[row], as_tuple=False).flatten()
                if indices.numel() > 0:
                    mask[row, indices[-1]] = True
            return mask
        raise ValueError(
            f"Workspace scope {scope!r} is not defined for deferred_bridge. "
            "Use all, context, context_tail, prompt_tail, boundary, or "
            "prequery_boundary."
        )

    @staticmethod
    def _memory_donor_indices(
        world_group_ids: torch.Tensor,
        *,
        mode: str,
        seed: int,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        groups = [int(value) for value in world_group_ids.detach().cpu().tolist()]
        batch = len(groups)
        donors: list[int] = []
        changed: list[bool] = []
        rng = random.Random(int(seed))
        for row, group in enumerate(groups):
            if mode == "cross_world_shuffle":
                candidates = [index for index, other in enumerate(groups) if other != group]
            elif mode == "within_world_shuffle":
                candidates = [
                    index
                    for index, other in enumerate(groups)
                    if other == group and index != row
                ]
            else:
                raise ValueError(f"Unsupported donor mode: {mode}")
            if candidates:
                donor = candidates[rng.randrange(len(candidates))]
            else:
                donor = row
            donors.append(donor)
            changed.append(donor != row)
        return (
            torch.tensor(donors, device=world_group_ids.device, dtype=torch.long),
            torch.tensor(changed, device=world_group_ids.device, dtype=torch.bool),
        )

    @staticmethod
    def _counterfactual_donor_indices(
        counterfactual_group_ids: torch.Tensor,
        answer_classes: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        groups = [
            int(value)
            for value in counterfactual_group_ids.detach().cpu().tolist()
        ]
        answers = [int(value) for value in answer_classes.detach().cpu().tolist()]
        donors: list[int] = []
        changed: list[bool] = []
        for row, (group, answer) in enumerate(zip(groups, answers)):
            candidates = [
                index
                for index, (other_group, other_answer) in enumerate(
                    zip(groups, answers)
                )
                if index != row
                and other_group == group
                and other_answer >= 0
                and answer >= 0
                and other_answer != answer
            ]
            donor = candidates[0] if len(candidates) == 1 else row
            donors.append(donor)
            changed.append(donor != row)
        return (
            torch.tensor(
                donors, device=counterfactual_group_ids.device, dtype=torch.long
            ),
            torch.tensor(
                changed, device=counterfactual_group_ids.device, dtype=torch.bool
            ),
        )

    def _intervene_memory(
        self,
        memory: torch.Tensor,
        memory_attention_mask: torch.Tensor,
        world_group_ids: Optional[torch.Tensor],
        counterfactual_group_ids: Optional[torch.Tensor],
        answer_classes: Optional[torch.Tensor],
        *,
        mode: str,
        seed: int,
    ) -> tuple[torch.Tensor, torch.Tensor, dict[str, torch.Tensor]]:
        """Apply an auditable intervention to deferred workspace memory.

        Several interventions deliberately preserve a non-zero carrier while
        destroying content. This distinguishes semantic necessity from the
        degenerate observation that an all-zero tensor disables a LayerNorm-fed
        route.
        """
        valid = memory_attention_mask.to(torch.bool)
        hard_bypass = False

        if mode == "intact":
            intervened = memory
            new_mask = memory_attention_mask
            changed = torch.zeros(
                memory.shape[0], device=memory.device, dtype=torch.bool
            )
        elif mode == "zero":
            intervened = torch.zeros_like(memory)
            changed = valid.any(dim=1)
            new_mask = memory_attention_mask
        elif mode == "mean":
            weights = valid.to(memory.dtype).unsqueeze(-1)
            mean = (memory * weights).sum(dim=1, keepdim=True) / weights.sum(
                dim=1, keepdim=True
            ).clamp_min(1.0)
            intervened = mean.expand_as(memory) * weights
            changed = valid.any(dim=1)
            new_mask = memory_attention_mask
        elif mode == "global_mean":
            weights = valid.to(memory.dtype).unsqueeze(-1)
            global_mean = (memory * weights).sum(dim=(0, 1), keepdim=True) / weights.sum(
                dim=(0, 1), keepdim=True
            ).clamp_min(1.0)
            intervened = global_mean.expand_as(memory) * weights
            changed = valid.any(dim=1)
            new_mask = memory_attention_mask
        elif mode in {"fixed_carrier", "global_fixed"}:
            # Deterministic and context-independent. Match the batch-average
            # valid-token norm so the control does not win or lose by scale.
            positions = torch.arange(
                memory.shape[-1], device=memory.device, dtype=torch.float32
            )
            carrier = torch.sin(positions * 0.017) + torch.cos(positions * 0.031)
            carrier = carrier / carrier.norm().clamp_min(1e-12)
            source_tokens = memory.float()[valid]
            target_norm = (
                source_tokens.norm(dim=-1).mean()
                if source_tokens.numel()
                else memory.new_tensor(1.0, dtype=torch.float32)
            )
            carrier = (carrier * target_norm).to(memory.dtype)
            intervened = carrier.view(1, 1, -1).expand_as(memory).clone()
            intervened = intervened * valid.to(memory.dtype).unsqueeze(-1)
            changed = valid.any(dim=1)
            new_mask = memory_attention_mask
        elif mode in {"norm_matched_random", "random_matched"}:
            # One random, context-independent carrier direction is shared by
            # every row and token. Per-row random tensors would leak row index
            # as pseudo-content in paired batches, invalidating this control.
            generator = torch.Generator(device="cpu")
            generator.manual_seed(int(seed) % (2**63 - 1))
            random_carrier = torch.randn(
                (memory.shape[-1],), generator=generator, dtype=torch.float32
            ).to(device=memory.device)
            random_carrier = F.layer_norm(
                random_carrier, (memory.shape[-1],)
            )
            random_carrier = random_carrier / random_carrier.norm().clamp_min(1e-12)
            source_tokens = memory.float()[valid]
            target_norm = (
                source_tokens.norm(dim=-1).mean()
                if source_tokens.numel()
                else memory.new_tensor(1.0, dtype=torch.float32)
            )
            random_carrier = (random_carrier * target_norm).to(memory.dtype)
            intervened = random_carrier.view(1, 1, -1).expand_as(memory).clone()
            intervened = intervened * valid.to(memory.dtype).unsqueeze(-1)
            changed = valid.any(dim=1)
            new_mask = memory_attention_mask
        elif mode == "sign_flip":
            intervened = -memory
            changed = valid.any(dim=1)
            new_mask = memory_attention_mask
        elif mode in {"signed_permutation", "feature_permute"}:
            generator = torch.Generator(device="cpu")
            generator.manual_seed(int(seed) % (2**63 - 1))
            order = torch.randperm(memory.shape[-1], generator=generator).to(
                memory.device
            )
            intervened = memory.index_select(-1, order)
            if mode == "signed_permutation":
                signs = torch.randint(
                    0,
                    2,
                    (memory.shape[-1],),
                    generator=generator,
                    dtype=torch.long,
                ).mul_(2).sub_(1).to(memory.device, memory.dtype)
                intervened = intervened * signs
            changed = valid.any(dim=1)
            new_mask = memory_attention_mask
        elif mode in {
            "scale_025", "scale_050", "scale_100", "scale_200", "scale_400"
        }:
            scale = {
                "scale_025": 0.25,
                "scale_050": 0.50,
                "scale_100": 1.00,
                "scale_200": 2.00,
                "scale_400": 4.00,
            }[mode]
            intervened = memory * scale
            changed = valid.any(dim=1) & bool(scale != 1.0)
            new_mask = memory_attention_mask
        elif mode == "hard_bypass":
            intervened = memory
            changed = valid.any(dim=1)
            new_mask = memory_attention_mask
            hard_bypass = True
        elif mode == "token_shuffle":
            intervened = memory.clone()
            generator = torch.Generator(device="cpu")
            generator.manual_seed(int(seed) % (2**63 - 1))
            changed_rows: list[bool] = []
            for row in range(memory.shape[0]):
                indices = torch.nonzero(valid[row], as_tuple=False).flatten()
                if indices.numel() > 1:
                    order = torch.randperm(indices.numel(), generator=generator)
                    order = order.to(indices.device)
                    intervened[row, indices] = memory[row, indices[order]]
                    changed_rows.append(True)
                else:
                    changed_rows.append(False)
            changed = torch.tensor(
                changed_rows, device=memory.device, dtype=torch.bool
            )
            new_mask = memory_attention_mask
        elif mode in {"within_world_shuffle", "cross_world_shuffle"}:
            if world_group_ids is None:
                raise ValueError(f"{mode} requires world_group_ids.")
            donors, changed = self._memory_donor_indices(
                world_group_ids, mode=mode, seed=seed
            )
            intervened = memory.index_select(0, donors)
            new_mask = memory_attention_mask.index_select(0, donors)
        elif mode == "counterfactual_twin":
            if counterfactual_group_ids is None or answer_classes is None:
                raise ValueError(
                    "counterfactual_twin requires pair IDs and answer classes."
                )
            donors, changed = self._counterfactual_donor_indices(
                counterfactual_group_ids, answer_classes
            )
            intervened = memory.index_select(0, donors)
            new_mask = memory_attention_mask.index_select(0, donors)
        else:
            raise ValueError(f"Unsupported memory intervention: {mode}")

        overlap = valid & new_mask.to(torch.bool)
        if bool(overlap.any().item()):
            source_flat = memory.float()[overlap]
            intervened_flat = intervened.float()[overlap]
            cosine = F.cosine_similarity(
                source_flat, intervened_flat, dim=-1, eps=1e-8
            ).mean()
            source_ln = F.layer_norm(source_flat, (memory.shape[-1],))
            intervened_ln = F.layer_norm(intervened_flat, (memory.shape[-1],))
            postnorm_cosine = F.cosine_similarity(
                source_ln, intervened_ln, dim=-1, eps=1e-8
            ).mean()
        else:
            cosine = memory.new_zeros((), dtype=torch.float32)
            postnorm_cosine = memory.new_zeros((), dtype=torch.float32)

        source_valid = memory.float()[valid]
        intervened_valid = intervened.float()[new_mask.to(torch.bool)]
        source_norm = (
            source_valid.norm(dim=-1).mean()
            if source_valid.numel()
            else memory.new_zeros((), dtype=torch.float32)
        )
        intervened_norm = (
            intervened_valid.norm(dim=-1).mean()
            if intervened_valid.numel()
            else memory.new_zeros((), dtype=torch.float32)
        )
        row_presence = (
            intervened.float().norm(dim=-1)
            * new_mask.to(intervened.dtype)
        ).amax(dim=1).gt(1e-8)

        # ``changed`` records donor assignment or the declared intervention.
        # It is not enough for content attribution: a fixed carrier can be
        # reassigned to another row while the tensor remains byte-identical.
        # Report both raw and LayerNorm-effective changes so the assay cannot
        # launder a nominal swap into a semantic perturbation.
        union = valid | new_mask.to(torch.bool)
        raw_delta = (intervened.float() - memory.float()).abs()
        raw_row_delta = (
            raw_delta * union.to(raw_delta.dtype).unsqueeze(-1)
        ).amax(dim=(1, 2))
        mask_row_delta = valid.ne(new_mask.to(torch.bool)).any(dim=1)
        tensor_changed = raw_row_delta.gt(1e-7) | mask_row_delta

        source_effective = F.layer_norm(memory.float(), (memory.shape[-1],))
        intervened_effective = F.layer_norm(
            intervened.float(), (memory.shape[-1],)
        )
        effective_delta = (source_effective - intervened_effective).abs()
        effective_row_delta = (
            effective_delta * union.to(effective_delta.dtype).unsqueeze(-1)
        ).amax(dim=(1, 2))
        effective_changed = effective_row_delta.gt(1e-6) | mask_row_delta
        valid_rows = union.any(dim=1)
        if bool(valid_rows.any().item()):
            content_delta_l2 = (
                (intervened.float() - memory.float())
                .square()
                .sum(dim=-1)
                .sqrt()
                .masked_select(union)
                .mean()
            )
            effective_delta_l2 = (
                (intervened_effective - source_effective)
                .square()
                .sum(dim=-1)
                .sqrt()
                .masked_select(union)
                .mean()
            )
        else:
            content_delta_l2 = memory.new_zeros((), dtype=torch.float32)
            effective_delta_l2 = memory.new_zeros((), dtype=torch.float32)

        return intervened, new_mask, {
            # Backward-compatible alias. New reports state explicitly that this
            # is assignment/declaration coverage, not tensor change coverage.
            "memory_changed_fraction": changed.float().mean(),
            "memory_assignment_changed_fraction": changed.float().mean(),
            "memory_tensor_changed_fraction": tensor_changed.float().mean(),
            "memory_effective_changed_fraction": effective_changed.float().mean(),
            "memory_content_delta_l2": content_delta_l2,
            "memory_effective_delta_l2": effective_delta_l2,
            "memory_source_norm": source_norm,
            "memory_intervened_norm": intervened_norm,
            "memory_raw_cosine": cosine,
            "memory_layernorm_cosine": postnorm_cosine,
            "memory_carrier_presence_fraction": row_presence.float().mean(),
            "hard_bypass_fraction": torch.tensor(
                float(hard_bypass), device=memory.device, dtype=torch.float32
            ),
        }

    @staticmethod
    def _functional_answer_rows(
        logits: torch.Tensor,
        labels: torch.Tensor,
        candidate_ids: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        """Return answer-token NLL, candidate logits, targets, and source rows."""
        if logits.ndim != 3 or labels.ndim != 2 or candidate_ids.ndim != 2:
            raise ValueError("Unexpected functional task tensor rank.")
        targets = labels[:, 1:]
        supervised = targets.ne(-100)
        counts = supervised.sum(dim=1)
        if not counts.eq(1).all():
            raise ValueError(
                "v9 functional contract requires exactly one supervised token per query."
            )
        source_positions = supervised.to(torch.long).argmax(dim=1)
        rows = torch.arange(logits.shape[0], device=logits.device)
        source_logits = logits[rows, source_positions]
        target_tokens = targets[rows, source_positions]
        token_nll = F.cross_entropy(source_logits, target_tokens, reduction="none")
        if (candidate_ids < 0).any():
            raise ValueError("Functional candidate token IDs contain padding.")
        choice_logits = source_logits.gather(1, candidate_ids)
        return token_nll, choice_logits, target_tokens, source_positions

    @staticmethod
    def _functional_margin(
        choice_logits: torch.Tensor,
        answer_classes: torch.Tensor,
    ) -> torch.Tensor:
        rows = torch.arange(choice_logits.shape[0], device=choice_logits.device)
        correct = choice_logits[rows, answer_classes]
        masked = choice_logits.clone()
        masked[rows, answer_classes] = float("-inf")
        return correct - masked.max(dim=1).values

    def _functional_objective_rows(
        self,
        full_vocab_nll: torch.Tensor,
        choice_nll: torch.Tensor,
    ) -> torch.Tensor:
        """Select the preregistered v11 functional supervision objective."""
        mode = self.functional_config.task_objective
        if mode == "full_vocab":
            return full_vocab_nll
        if mode == "choice_normalized":
            return choice_nll
        if mode == "hybrid":
            return choice_nll + (
                float(self.functional_config.full_vocab_loss_weight)
                * full_vocab_nll
            )
        raise RuntimeError(f"Unsupported functional task objective: {mode}")

    def _functional_task_result(
        self,
        logits: torch.Tensor,
        labels: torch.Tensor,
        candidate_ids: torch.Tensor,
        answer_classes: torch.Tensor,
        *,
        batch_size: int,
        side_indices: torch.Tensor,
        world_indices: torch.Tensor,
        query_indices: torch.Tensor,
        affected: torch.Tensor,
        heldout: torch.Tensor,
        hop_distances: torch.Tensor,
        donor_answer_classes: Optional[torch.Tensor] = None,
    ) -> dict[str, torch.Tensor]:
        full_vocab_nll, choice_logits, _target_tokens, _source_positions = (
            self._functional_answer_rows(logits, labels, candidate_ids)
        )
        choice_nll = F.cross_entropy(
            choice_logits.float(),
            answer_classes,
            reduction="none",
        )
        objective_nll = self._functional_objective_rows(
            full_vocab_nll,
            choice_nll,
        )
        predicted = choice_logits.argmax(dim=1)
        correct = predicted.eq(answer_classes)
        margin = self._functional_margin(choice_logits, answer_classes)
        nll_sum = objective_nll.sum()
        full_vocab_nll_sum = full_vocab_nll.sum()
        choice_nll_sum = choice_nll.sum()
        token_count = torch.tensor(
            objective_nll.numel(), device=logits.device, dtype=torch.long
        )

        world_side = world_indices * 2 + side_indices
        world_total = torch.zeros(
            batch_size * 2, device=logits.device, dtype=torch.long
        )
        world_correct = torch.zeros_like(world_total)
        ones = torch.ones_like(world_side, dtype=torch.long)
        world_total.scatter_add_(0, world_side, ones)
        world_correct.scatter_add_(0, world_side, correct.to(torch.long))
        valid_worlds = world_total.gt(0)
        all_query = world_correct.eq(world_total) & valid_worlds

        affected_values = affected[world_indices, query_indices]
        heldout_values = heldout[world_indices, query_indices]
        hop_values = hop_distances[world_indices, query_indices]
        zero = nll_sum.detach() * 0.0
        query_count = torch.tensor(
            correct.numel(), device=logits.device, dtype=torch.float32
        )
        choice_count = int(choice_logits.shape[1])
        predicted_counts = torch.bincount(predicted, minlength=choice_count)
        prediction_probabilities = predicted_counts.float() / query_count.clamp_min(1.0)
        positive_prediction_probabilities = prediction_probabilities[
            prediction_probabilities > 0
        ]
        prediction_entropy = -(
            positive_prediction_probabilities
            * positive_prediction_probabilities.log()
        ).sum()
        if choice_count == 2:
            signed_choice_gap = (
                choice_logits[:, 1].float() - choice_logits[:, 0].float()
            )
            signed_choice_gap_sum = signed_choice_gap.sum()
            signed_choice_gap_mean = signed_choice_gap.mean()
        else:
            signed_choice_gap_sum = zero
            signed_choice_gap_mean = zero

        affected_count = affected_values.sum().to(torch.float32)
        unaffected_count = (~affected_values).sum().to(torch.float32)
        heldout_count = heldout_values.sum().to(torch.float32)

        result: dict[str, torch.Tensor] = {
            "task_loss": nll_sum / token_count.to(nll_sum.dtype),
            "task_nll_sum": nll_sum,
            "base_nll_sum": nll_sum,
            "full_vocab_nll_sum": full_vocab_nll_sum,
            "choice_nll_sum": choice_nll_sum,
            "functional_full_vocab_loss": (
                full_vocab_nll_sum / token_count.to(full_vocab_nll_sum.dtype)
            ),
            "functional_choice_loss": (
                choice_nll_sum / token_count.to(choice_nll_sum.dtype)
            ),
            "supervised_tokens": token_count,
            "per_example_nll": objective_nll,
            "per_example_base_nll": objective_nll,
            "per_example_full_vocab_nll": full_vocab_nll,
            "per_example_choice_nll": choice_nll,
            "per_example_tokens": torch.ones_like(objective_nll, dtype=torch.long),
            "delta_logit_norm": zero,
            "gated_delta_logit_norm": zero,
            "functional_query_accuracy": correct.float().mean(),
            "functional_query_correct": correct.sum().to(torch.float32),
            "functional_all_query_world_accuracy": (
                all_query[valid_worlds].float().mean() if valid_worlds.any() else zero
            ),
            "functional_all_query_world_examples": valid_worlds.sum().to(torch.float32),
            "functional_all_query_world_correct": (
                all_query[valid_worlds].sum().to(torch.float32)
            ),
            "functional_choice_margin": margin.mean(),
            "functional_yes_minus_no_gap": signed_choice_gap_mean,
            "functional_yes_minus_no_gap_sum": signed_choice_gap_sum,
            "functional_prediction_entropy_nats": prediction_entropy,
            "functional_distinct_predicted_classes": (
                predicted_counts.gt(0).sum().to(torch.float32)
            ),
            "functional_choice_count": torch.tensor(
                choice_count, device=logits.device, dtype=torch.float32
            ),
            "functional_affected_accuracy": (
                correct[affected_values].float().mean()
                if affected_values.any()
                else zero
            ),
            "functional_affected_examples": affected_count,
            "functional_affected_correct": (
                correct[affected_values].sum().to(torch.float32)
            ),
            "functional_unaffected_accuracy": (
                correct[~affected_values].float().mean()
                if (~affected_values).any()
                else zero
            ),
            "functional_unaffected_examples": unaffected_count,
            "functional_unaffected_correct": (
                correct[~affected_values].sum().to(torch.float32)
            ),
            "functional_heldout_query_accuracy": (
                correct[heldout_values].float().mean()
                if heldout_values.any()
                else zero
            ),
            "functional_heldout_query_examples": heldout_count,
            "functional_heldout_query_correct": (
                correct[heldout_values].sum().to(torch.float32)
            ),
            "functional_query_count": query_count,
        }
        for label in range(choice_count):
            label_mask = answer_classes.eq(label)
            label_examples = label_mask.sum().to(torch.float32)
            label_correct = (correct & label_mask).sum().to(torch.float32)
            label_predictions = predicted_counts[label].to(torch.float32)
            result[f"functional_label_{label}_examples"] = label_examples
            result[f"functional_label_{label}_correct"] = label_correct
            result[f"functional_label_{label}_predictions"] = label_predictions
            result[f"functional_label_{label}_recall"] = (
                label_correct / label_examples.clamp_min(1.0)
            )
            result[f"functional_label_{label}_prediction_fraction"] = (
                label_predictions / query_count.clamp_min(1.0)
            )
        if donor_answer_classes is not None:
            donor_correct = predicted.eq(donor_answer_classes)
            result["functional_donor_accuracy"] = donor_correct.float().mean()
            result["functional_affected_donor_accuracy"] = (
                donor_correct[affected_values].float().mean()
                if affected_values.any()
                else zero
            )
            result["functional_unaffected_original_stability"] = (
                correct[~affected_values].float().mean()
                if (~affected_values).any()
                else zero
            )
        else:
            result["functional_donor_accuracy"] = zero
            result["functional_affected_donor_accuracy"] = zero
            result["functional_unaffected_original_stability"] = zero

        for hop in range(1, 9):
            mask = hop_values.eq(hop)
            if mask.any():
                result[f"functional_hop_{hop}_accuracy"] = correct[mask].float().mean()
                result[f"functional_hop_{hop}_examples"] = mask.float().sum()
                result[f"functional_hop_{hop}_correct"] = (
                    correct[mask].sum().to(torch.float32)
                )
        return result

    def _functional_workspace_regularizer(
        self,
        trajectory: torch.Tensor,
        anchor: torch.Tensor,
        memory_mask: torch.Tensor,
        pair_ids: torch.Tensor,
        *,
        compute_spectral: bool,
    ) -> tuple[dict[str, torch.Tensor], int]:
        if self.functional_loss_projection is None:
            raise RuntimeError("Functional loss projection is unavailable.")
        projected_trajectory = self.functional_loss_projection(trajectory)
        projected_anchor = self.functional_loss_projection(anchor)
        valid = memory_mask.to(torch.bool)
        selected_trajectory = projected_trajectory[valid]
        selected_anchor = projected_anchor[valid]
        if selected_trajectory.numel() == 0:
            raise ValueError("Functional workspace regularizer received no memory tokens.")
        expanded_groups = pair_ids.repeat_interleave(2)
        group_grid = expanded_groups[:, None].expand_as(valid)
        selected_groups = group_grid[valid]
        stats = self.workspace_loss(
            selected_trajectory,
            selected_anchor,
            step_weights=torch.ones(
                selected_trajectory.shape[1],
                device=selected_trajectory.device,
                dtype=torch.float32,
            ),
            compute_spectral=compute_spectral,
            contrastive_group_ids=selected_groups,
        )
        return stats, int(selected_trajectory.shape[0])

    def _functional_decode_with_memory(
        self,
        query_boundary: torch.Tensor,
        query_attention_mask: torch.Tensor,
        memory: torch.Tensor,
        memory_mask: torch.Tensor,
        *,
        boundary_layer: int,
        hard_bypass: bool,
        route_rng_seed: Optional[int] = None,
        isolate_route_rng: bool = False,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        if self.functional_reader is None or self.functional_boundary_adapter is None:
            raise RuntimeError("Functional reader/boundary adapter is unavailable.")
        zero = query_boundary.detach().sum() * 0.0
        if hard_bypass:
            injected = query_boundary
            gate_mean = zero
            read_norm = zero
        else:
            # Reader-side dropout belongs to the route stream. Restore the
            # global RNG before upper base layers run, so a zero route cannot
            # perturb the base-model dropout trajectory.
            with isolated_torch_rng(
                isolate_route_rng,
                route_rng_seed,
                query_boundary.device,
            ):
                injected, gate_mean, read_norm = self.functional_reader(
                    query_boundary,
                    query_attention_mask,
                    memory,
                    memory_mask,
                )
        with self._base_activation_offload_context(injected.device):
            logits = self.functional_boundary_adapter.decode(
                injected,
                query_attention_mask,
                boundary_layer,
            )
        return logits, gate_mean, read_norm

    def _forward_functional_workspace(
        self,
        *,
        functional_context_input_ids: Optional[torch.Tensor],
        functional_context_attention_mask: Optional[torch.Tensor],
        functional_query_input_ids: Optional[torch.Tensor],
        functional_query_attention_mask: Optional[torch.Tensor],
        functional_query_labels: Optional[torch.Tensor],
        functional_inline_input_ids: Optional[torch.Tensor],
        functional_inline_attention_mask: Optional[torch.Tensor],
        functional_inline_labels: Optional[torch.Tensor],
        functional_query_choice_ids: Optional[torch.Tensor],
        functional_inline_choice_ids: Optional[torch.Tensor],
        functional_answer_classes: Optional[torch.Tensor],
        functional_query_valid_mask: Optional[torch.Tensor],
        functional_affected_mask: Optional[torch.Tensor],
        functional_heldout_mask: Optional[torch.Tensor],
        functional_hop_distances: Optional[torch.Tensor],
        functional_pair_ids: Optional[torch.Tensor],
        compute_workspace_loss: bool,
        compute_spectral: bool,
        bypass_workspace: bool,
        rng_streams: Optional[Mapping[str, int]],
        memory_intervention: str,
        memory_intervention_seed: int,
    ) -> dict[str, Any]:
        required = {
            "functional_context_input_ids": functional_context_input_ids,
            "functional_context_attention_mask": functional_context_attention_mask,
            "functional_query_input_ids": functional_query_input_ids,
            "functional_query_attention_mask": functional_query_attention_mask,
            "functional_query_labels": functional_query_labels,
            "functional_inline_input_ids": functional_inline_input_ids,
            "functional_inline_attention_mask": functional_inline_attention_mask,
            "functional_inline_labels": functional_inline_labels,
            "functional_query_choice_ids": functional_query_choice_ids,
            "functional_inline_choice_ids": functional_inline_choice_ids,
            "functional_answer_classes": functional_answer_classes,
            "functional_query_valid_mask": functional_query_valid_mask,
            "functional_affected_mask": functional_affected_mask,
            "functional_heldout_mask": functional_heldout_mask,
            "functional_hop_distances": functional_hop_distances,
            "functional_pair_ids": functional_pair_ids,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError(
                "functional_workspace requires grouped collator tensors; missing "
                + ", ".join(missing)
            )
        assert functional_context_input_ids is not None
        assert functional_context_attention_mask is not None
        assert functional_query_input_ids is not None
        assert functional_query_attention_mask is not None
        assert functional_query_labels is not None
        assert functional_inline_input_ids is not None
        assert functional_inline_attention_mask is not None
        assert functional_inline_labels is not None
        assert functional_query_choice_ids is not None
        assert functional_inline_choice_ids is not None
        assert functional_answer_classes is not None
        assert functional_query_valid_mask is not None
        assert functional_affected_mask is not None
        assert functional_heldout_mask is not None
        assert functional_hop_distances is not None
        assert functional_pair_ids is not None

        if self.functional_writer is None or self.functional_boundary_adapter is None:
            raise RuntimeError("Functional workspace modules were not initialized.")
        B, sides, context_length = functional_context_input_ids.shape
        if sides != 2:
            raise ValueError("v9 requires exactly two local-counterfactual world sides.")
        _, query_sides, J, query_length = functional_query_input_ids.shape
        if query_sides != 2:
            raise ValueError("Functional query side axis must have length two.")
        valid_grid = functional_query_valid_mask[:, None, :].expand(B, 2, J)
        flat_valid = valid_grid.reshape(-1)
        if int(flat_valid.sum().item()) == 0:
            raise ValueError("Functional batch contains no valid queries.")
        flat_positions = torch.nonzero(flat_valid, as_tuple=False).flatten()
        all_world = torch.arange(B, device=flat_valid.device)[:, None, None].expand(B, 2, J)
        all_side = torch.arange(2, device=flat_valid.device)[None, :, None].expand(B, 2, J)
        all_query = torch.arange(J, device=flat_valid.device)[None, None, :].expand(B, 2, J)
        world_indices = all_world.reshape(-1)[flat_positions]
        side_indices = all_side.reshape(-1)[flat_positions]
        query_indices = all_query.reshape(-1)[flat_positions]
        world_side_indices = world_indices * 2 + side_indices

        mode = self.functional_config.route_mode
        if bypass_workspace and mode == "deferred":
            mode = "query_only"
        if mode == "inline":
            flat_ids = functional_inline_input_ids.reshape(B * 2 * J, -1)[flat_positions]
            flat_mask = functional_inline_attention_mask.reshape(B * 2 * J, -1)[flat_positions]
            flat_labels = functional_inline_labels.reshape(B * 2 * J, -1)[flat_positions]
            flat_choices = functional_inline_choice_ids.reshape(
                B * 2 * J, -1
            )[flat_positions]
            with self._base_activation_offload_context(flat_ids.device):
                outputs = self.base_model(
                    input_ids=flat_ids,
                    attention_mask=flat_mask,
                    use_cache=False,
                    return_dict=True,
                )
            logits = getattr(outputs, "logits", None)
            if logits is None:
                raise RuntimeError("Inline functional base model returned no logits.")
            gate_mean = logits.detach().sum() * 0.0
            read_norm = gate_mean
            memory_metrics = {
                "memory_changed_fraction": gate_mean,
                "memory_assignment_changed_fraction": gate_mean,
                "memory_tensor_changed_fraction": gate_mean,
                "memory_effective_changed_fraction": gate_mean,
                "memory_content_delta_l2": gate_mean,
                "memory_effective_delta_l2": gate_mean,
                "memory_source_norm": gate_mean,
                "memory_intervened_norm": gate_mean,
                "memory_raw_cosine": gate_mean,
                "memory_layernorm_cosine": gate_mean,
                "memory_carrier_presence_fraction": gate_mean,
                "hard_bypass_fraction": gate_mean,
            }
            writer_trajectory = None
            writer_anchor = None
            writer_mask = None
            intact_memory = None
            intact_memory_mask = None
        else:
            flat_ids = functional_query_input_ids.reshape(B * 2 * J, -1)[flat_positions]
            flat_mask = functional_query_attention_mask.reshape(B * 2 * J, -1)[flat_positions]
            flat_labels = functional_query_labels.reshape(B * 2 * J, -1)[flat_positions]
            flat_choices = functional_query_choice_ids.reshape(
                B * 2 * J, -1
            )[flat_positions]
            if mode == "query_only":
                with self._base_activation_offload_context(flat_ids.device):
                    outputs = self.base_model(
                        input_ids=flat_ids,
                        attention_mask=flat_mask,
                        use_cache=False,
                        return_dict=True,
                    )
                logits = getattr(outputs, "logits", None)
                if logits is None:
                    raise RuntimeError("Query-only functional model returned no logits.")
                gate_mean = logits.detach().sum() * 0.0
                read_norm = gate_mean
                memory_metrics = {
                    "memory_changed_fraction": gate_mean,
                    "memory_assignment_changed_fraction": gate_mean,
                    "memory_tensor_changed_fraction": gate_mean,
                    "memory_effective_changed_fraction": gate_mean,
                    "memory_content_delta_l2": gate_mean,
                    "memory_effective_delta_l2": gate_mean,
                    "memory_source_norm": gate_mean,
                    "memory_intervened_norm": gate_mean,
                    "memory_raw_cosine": gate_mean,
                    "memory_layernorm_cosine": gate_mean,
                    "memory_carrier_presence_fraction": gate_mean,
                    "hard_bypass_fraction": gate_mean,
                }
                writer_trajectory = None
                writer_anchor = None
                writer_mask = None
                intact_memory = None
                intact_memory_mask = None
            elif mode == "deferred":
                boundary = int(self.functional_config.boundary_layer)
                layer_count = self.functional_boundary_adapter.layer_count()
                if boundary > layer_count:
                    raise ValueError(
                        f"functional boundary {boundary} exceeds {layer_count} layers."
                    )
                context_flat_ids = functional_context_input_ids.reshape(
                    B * 2, context_length
                )
                context_flat_mask = functional_context_attention_mask.reshape(
                    B * 2, context_length
                )
                isolate = rng_streams is not None
                context_seed = None if rng_streams is None else rng_streams.get("context")
                route_seed = None if rng_streams is None else rng_streams.get("route")
                with isolated_torch_rng(
                    isolate, context_seed, context_flat_ids.device
                ):
                    with self._base_activation_offload_context(
                        context_flat_ids.device,
                        legacy_region=True,
                    ):
                        context_boundary = self.functional_boundary_adapter.encode(
                            context_flat_ids,
                            context_flat_mask,
                            boundary,
                        )
                with isolated_torch_rng(
                    isolate, route_seed, context_boundary.device
                ):
                    memory, writer_mask, writer_trajectory, writer_anchor = (
                        self.functional_writer(
                            context_boundary,
                            context_flat_mask,
                        )
                    )
                if self.functional_config.readout_step != -1:
                    memory = writer_trajectory[
                        :, :, self.functional_config.readout_step - 1, :
                    ]
                intact_memory = memory
                intact_memory_mask = writer_mask
                pair_groups = functional_pair_ids.repeat_interleave(2)
                side_classes = torch.arange(2, device=memory.device).repeat(B)
                memory, memory_mask, memory_metrics = self._intervene_memory(
                    memory,
                    writer_mask,
                    pair_groups,
                    pair_groups,
                    side_classes,
                    mode=memory_intervention,
                    seed=memory_intervention_seed,
                )
                with self._base_activation_offload_context(
                    flat_ids.device,
                    legacy_region=True,
                ):
                    query_boundary = self.functional_boundary_adapter.encode(
                        flat_ids,
                        flat_mask,
                        boundary,
                    )
                expanded_memory = memory.index_select(0, world_side_indices)
                expanded_memory_mask = memory_mask.index_select(0, world_side_indices)
                logits, gate_mean, read_norm = self._functional_decode_with_memory(
                    query_boundary,
                    flat_mask,
                    expanded_memory,
                    expanded_memory_mask,
                    boundary_layer=boundary,
                    hard_bypass=memory_intervention == "hard_bypass",
                    route_rng_seed=route_seed,
                    isolate_route_rng=isolate,
                )
            else:
                raise RuntimeError(f"Unsupported functional route mode: {mode}")

        flat_answers = functional_answer_classes.reshape(B * 2 * J)[flat_positions]
        donor_answers = functional_answer_classes.flip(1).reshape(B * 2 * J)[
            flat_positions
        ]
        task_result = self._functional_task_result(
            logits,
            flat_labels,
            flat_choices,
            flat_answers,
            batch_size=B,
            side_indices=side_indices,
            world_indices=world_indices,
            query_indices=query_indices,
            affected=functional_affected_mask,
            heldout=functional_heldout_mask,
            hop_distances=functional_hop_distances,
            donor_answer_classes=(
                donor_answers if memory_intervention == "counterfactual_twin" else None
            ),
        )

        zero = task_result["task_nll_sum"].detach() * 0.0
        counterfactual_nll_sum = zero
        counterfactual_tokens = torch.zeros((), device=logits.device, dtype=torch.long)
        stability_kl_sum = zero
        stability_items = torch.zeros((), device=logits.device, dtype=torch.long)
        if (
            mode == "deferred"
            and memory_intervention == "intact"
            and intact_memory is not None
            and intact_memory_mask is not None
            and (
                self.functional_config.counterfactual_weight > 0.0
                or self.functional_config.stability_weight > 0.0
            )
        ):
            boundary = int(self.functional_config.boundary_layer)
            swapped_memory = intact_memory.reshape(B, 2, *intact_memory.shape[1:]).flip(1)
            swapped_memory = swapped_memory.reshape_as(intact_memory)
            swapped_mask = intact_memory_mask.reshape(
                B, 2, intact_memory_mask.shape[1]
            ).flip(1).reshape_as(intact_memory_mask)
            expanded_swapped = swapped_memory.index_select(0, world_side_indices)
            expanded_swapped_mask = swapped_mask.index_select(0, world_side_indices)
            # Reuse the already-computed lower query representation. No second
            # query/base dropout stream is introduced by the causal objective.
            if 'query_boundary' not in locals():
                with self._base_activation_offload_context(
                    flat_ids.device,
                    legacy_region=True,
                ):
                    query_boundary = self.functional_boundary_adapter.encode(
                        flat_ids, flat_mask, boundary
                    )
            swapped_logits, _cf_gate, _cf_read = self._functional_decode_with_memory(
                query_boundary,
                flat_mask,
                expanded_swapped,
                expanded_swapped_mask,
                boundary_layer=boundary,
                hard_bypass=False,
                route_rng_seed=(
                    None if rng_streams is None else rng_streams.get("route")
                ),
                isolate_route_rng=rng_streams is not None,
            )
            _intact_nll, intact_choices, _it, _ip = self._functional_answer_rows(
                logits, flat_labels, flat_choices
            )
            _swapped_nll, swapped_choices, _st, _sp = self._functional_answer_rows(
                swapped_logits,
                flat_labels,
                flat_choices,
            )
            affected_values = functional_affected_mask[world_indices, query_indices]
            if affected_values.any():
                donor_rows = torch.arange(
                    swapped_choices.shape[0], device=swapped_choices.device
                )
                donor_target_tokens = flat_choices[donor_rows, donor_answers]
                source_positions = flat_labels[:, 1:].ne(-100).long().argmax(dim=1)
                swapped_source_logits = swapped_logits[
                    donor_rows, source_positions
                ]
                cf_full_vocab_nll = F.cross_entropy(
                    swapped_source_logits[affected_values],
                    donor_target_tokens[affected_values],
                    reduction="none",
                )
                cf_choice_nll = F.cross_entropy(
                    swapped_choices[affected_values].float(),
                    donor_answers[affected_values],
                    reduction="none",
                )
                counterfactual_nll_sum = self._functional_objective_rows(
                    cf_full_vocab_nll,
                    cf_choice_nll,
                ).sum()
                counterfactual_tokens = affected_values.sum().to(torch.long)
            unaffected_values = ~affected_values
            if unaffected_values.any():
                temperature = float(self.functional_config.stability_temperature)
                target_prob = F.softmax(
                    intact_choices.detach()[unaffected_values] / temperature,
                    dim=-1,
                )
                swap_log_prob = F.log_softmax(
                    swapped_choices[unaffected_values] / temperature,
                    dim=-1,
                )
                stability_kl_sum = (
                    F.kl_div(
                        swap_log_prob,
                        target_prob,
                        reduction="sum",
                    ) * (temperature**2)
                ).clamp_min(0.0)
                stability_items = unaffected_values.sum().to(torch.long)

        if compute_workspace_loss and writer_trajectory is not None:
            assert writer_anchor is not None and writer_mask is not None
            regularizer_trajectory = writer_trajectory
            regularizer_anchor = writer_anchor
            regularizer_mask = writer_mask
            if (
                mode == "deferred"
                and not self.workspace_config.aux_backprop_to_base
            ):
                # Recompute through the same writer parameters from a detached
                # boundary state. This preserves local auxiliary learning while
                # proving that its gradient cannot enter the base transformer.
                auxiliary_seed = (
                    None if rng_streams is None else rng_streams.get("auxiliary")
                )
                with isolated_torch_rng(
                    rng_streams is not None,
                    auxiliary_seed,
                    context_boundary.device,
                ):
                    (
                        _aux_memory,
                        regularizer_mask,
                        regularizer_trajectory,
                        regularizer_anchor,
                    ) = self.functional_writer(
                        context_boundary.detach(),
                        context_flat_mask,
                    )
            workspace_stats, workspace_token_count = (
                self._functional_workspace_regularizer(
                    regularizer_trajectory,
                    regularizer_anchor,
                    regularizer_mask,
                    functional_pair_ids,
                    compute_spectral=compute_spectral,
                )
            )
        else:
            workspace_stats = self._zero_workspace_stats(task_result["task_nll_sum"])
            workspace_token_count = 0

        output: dict[str, Any] = {
            "logits": logits,
            **task_result,
            "counterfactual_nll_sum": counterfactual_nll_sum,
            "counterfactual_tokens": counterfactual_tokens,
            "stability_kl_sum": stability_kl_sum,
            "stability_items": stability_items,
            "workspace_loss": workspace_stats["loss"],
            "workspace_stats": workspace_stats,
            "gate_mean": gate_mean.detach(),
            "gate_max": gate_mean.detach(),
            "workspace_tokens": torch.tensor(
                workspace_token_count, device=logits.device, dtype=torch.long
            ),
            "workspace_bypassed": torch.tensor(
                bool(bypass_workspace), device=logits.device
            ),
            "bridge_state_norm": read_norm.detach(),
            "delta_logit_norm": task_result.get("delta_logit_norm", zero),
            "gated_delta_logit_norm": task_result.get(
                "gated_delta_logit_norm", zero
            ),
        }
        output.update(memory_metrics)
        return output


    def _forward_deferred_bridge(
        self,
        *,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor,
        labels: Optional[torch.Tensor],
        prompt_mask: Optional[torch.Tensor],
        context_mask: Optional[torch.Tensor],
        query_mask: Optional[torch.Tensor],
        bridge_context_input_ids: Optional[torch.Tensor],
        bridge_context_attention_mask: Optional[torch.Tensor],
        bridge_input_ids: Optional[torch.Tensor],
        bridge_attention_mask: Optional[torch.Tensor],
        bridge_labels: Optional[torch.Tensor],
        bridge_prompt_mask: Optional[torch.Tensor],
        bridge_query_mask: Optional[torch.Tensor],
        example_group_ids: Optional[torch.Tensor],
        world_group_ids: Optional[torch.Tensor],
        counterfactual_group_ids: Optional[torch.Tensor],
        answer_classes: Optional[torch.Tensor],
        compute_workspace_loss: bool,
        compute_spectral: bool,
        return_full_logits: bool,
        logits_to_keep: int,
        bypass_workspace: bool,
        rng_streams: Optional[Mapping[str, int]],
        memory_intervention: str,
        memory_intervention_seed: int,
    ) -> dict[str, Any]:
        del input_ids, attention_mask, labels, prompt_mask, context_mask, query_mask
        del bridge_prompt_mask, bridge_query_mask
        required = {
            "bridge_context_input_ids": bridge_context_input_ids,
            "bridge_context_attention_mask": bridge_context_attention_mask,
            "bridge_input_ids": bridge_input_ids,
            "bridge_attention_mask": bridge_attention_mask,
            "bridge_labels": bridge_labels,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError(
                "deferred_bridge requires collator bridge tensors; missing "
                + ", ".join(missing)
            )
        assert bridge_context_input_ids is not None
        assert bridge_context_attention_mask is not None
        assert bridge_input_ids is not None
        assert bridge_attention_mask is not None
        assert bridge_labels is not None
        if not bridge_context_attention_mask.to(torch.bool).any(dim=1).all():
            raise ValueError(
                "Every deferred_bridge row requires at least one context token."
            )

        # Continuation first: its base dropout stream is identical whether the
        # context route is enabled or not. Context computation happens second.
        base_outputs, continuation_hidden = self._base_forward_with_hidden_capture(
            bridge_input_ids, bridge_attention_mask
        )
        base_logits = getattr(base_outputs, "logits", None)
        if base_logits is None:
            raise RuntimeError("The continuation base model returned no logits.")

        route_scale = float(self.workspace_config.logit_residual_scale)
        need_route = (not bypass_workspace) and route_scale != 0.0
        need_auxiliary = (not bypass_workspace) and bool(compute_workspace_loss)
        context_seed = None if rng_streams is None else rng_streams.get("context")
        route_seed = None if rng_streams is None else rng_streams.get("route")
        auxiliary_seed = None if rng_streams is None else rng_streams.get("auxiliary")
        isolate = rng_streams is not None

        route_latents: Optional[torch.Tensor] = None
        route_anchor: Optional[torch.Tensor] = None
        context_hidden: Optional[torch.Tensor] = None
        route_needs_context = bool(
            need_route
            and self.workspace_config.deferred_memory_source != "fixed_carrier"
        )
        if route_needs_context or need_auxiliary:
            # A deferred route performs an extra base-model pass over context.
            # Isolating that pass is essential: otherwise its dropout calls
            # advance the global base RNG and silently change the continuation
            # branch on the next microbatch in N1/N2/N3 but not N0.
            with isolated_torch_rng(
                isolate, context_seed, bridge_context_input_ids.device
            ):
                _context_outputs, context_hidden = self._base_forward_with_hidden_capture(
                    bridge_context_input_ids, bridge_context_attention_mask
                )

        memory_metrics: dict[str, torch.Tensor]
        if need_route:
            memory_source = self.workspace_config.deferred_memory_source
            route_device = continuation_hidden.device
            # Keep recurrent-workspace and bridge dropout in the route stream.
            # A fixed carrier deliberately removes context content while leaving
            # the same bridge/logit path available as a carrier-only control.
            with isolated_torch_rng(isolate, route_seed, route_device):
                if memory_source == "fixed_carrier":
                    tokens = int(self.workspace_config.fixed_carrier_tokens)
                    positions = torch.arange(
                        tokens * self.workspace_config.workspace_dim,
                        device=route_device,
                        dtype=torch.float32,
                    ).reshape(tokens, self.workspace_config.workspace_dim)
                    carrier = torch.sin(positions * 0.017) + torch.cos(
                        positions * 0.031
                    )
                    memory = carrier.to(continuation_hidden.dtype).unsqueeze(0)
                    memory = memory.expand(continuation_hidden.shape[0], -1, -1)
                    memory_mask = torch.ones(
                        (continuation_hidden.shape[0], tokens),
                        device=route_device,
                        dtype=bridge_attention_mask.dtype,
                    )
                else:
                    assert context_hidden is not None
                    route_latents, route_anchor = self.workspace(
                        context_hidden, bridge_context_attention_mask
                    )
                    if memory_source == "anchor":
                        memory = route_anchor
                    else:
                        readout_step = int(
                            self.workspace_config.deferred_memory_step
                        )
                        readout_index = -1 if readout_step == -1 else readout_step - 1
                        memory = route_latents[:, :, readout_index, :]
                    memory_mask = bridge_context_attention_mask
                memory, memory_mask, memory_metrics = self._intervene_memory(
                    memory,
                    memory_mask,
                    world_group_ids,
                    counterfactual_group_ids,
                    answer_classes,
                    mode=memory_intervention,
                    seed=memory_intervention_seed,
                )
                bridge_state = self.memory_bridge(
                    continuation_hidden,
                    bridge_attention_mask,
                    memory,
                    memory_mask,
                )
                if memory_intervention == "hard_bypass":
                    bridge_state = torch.zeros_like(bridge_state)
            gate = torch.sigmoid(self.gate(self.gate_norm(continuation_hidden)))
        else:
            bridge_state = None
            gate = torch.zeros(
                (*continuation_hidden.shape[:2], 1),
                device=continuation_hidden.device,
                dtype=continuation_hidden.dtype,
            )
            zero = base_logits.detach().sum() * 0.0
            memory_metrics = {
                "memory_changed_fraction": zero,
                "memory_assignment_changed_fraction": zero,
                "memory_tensor_changed_fraction": zero,
                "memory_effective_changed_fraction": zero,
                "memory_content_delta_l2": zero,
                "memory_effective_delta_l2": zero,
                "memory_source_norm": zero,
                "memory_intervened_norm": zero,
                "memory_raw_cosine": zero,
                "memory_layernorm_cosine": zero,
                "memory_carrier_presence_fraction": zero,
                "hard_bypass_fraction": zero,
            }

        task_result: dict[str, torch.Tensor] = {}
        task_loss: Optional[torch.Tensor] = None
        task_nll_sum: Optional[torch.Tensor] = None
        supervised_tokens = torch.zeros((), device=base_logits.device, dtype=torch.long)
        if bridge_labels is not None:
            if need_route:
                assert bridge_state is not None
                task_result = self._supervised_task_loss(
                    base_logits, bridge_state, gate, bridge_labels
                )
            else:
                task_result = self._base_only_task_loss(base_logits, bridge_labels)
            task_loss = task_result["task_loss"]
            task_nll_sum = task_result["task_nll_sum"]
            supervised_tokens = task_result["supervised_tokens"]

        logits: Optional[torch.Tensor]
        if bridge_labels is not None and not return_full_logits:
            logits = None
        else:
            keep = base_logits.shape[1] if logits_to_keep == 0 else min(
                logits_to_keep, base_logits.shape[1]
            )
            if need_route:
                assert bridge_state is not None
                logits = self._adapt_logit_slice(
                    base_logits[:, -keep:, :],
                    bridge_state[:, -keep:, :],
                    gate[:, -keep:, :],
                )
            else:
                logits = base_logits[:, -keep:, :]

        if need_auxiliary:
            assert context_hidden is not None
            scope_mask = self._bridge_scope_mask(bridge_context_attention_mask)
            if route_latents is not None and self.workspace_config.aux_backprop_to_base:
                aux_latents = route_latents
                assert route_anchor is not None
                aux_anchor = route_anchor
            else:
                aux_hidden = (
                    context_hidden
                    if self.workspace_config.aux_backprop_to_base
                    else context_hidden.detach()
                )
                with isolated_torch_rng(isolate, auxiliary_seed, context_hidden.device):
                    aux_latents, aux_anchor = self.workspace(
                        aux_hidden, bridge_context_attention_mask
                    )

            negative_scope = self.workspace_config.contrastive_negative_scope
            if negative_scope == "all":
                contrastive_groups = None
            elif negative_scope == "cross_example":
                contrastive_groups = example_group_ids
            else:
                contrastive_groups = world_group_ids
            sample_seed = (
                None
                if auxiliary_seed is None
                else (int(auxiliary_seed) + 1) % (2**63 - 1)
            )
            with isolated_torch_rng(isolate, sample_seed, context_hidden.device):
                sampled_latents, sampled_anchor, sampled_groups = (
                    self._sample_workspace_states(
                        aux_latents,
                        aux_anchor,
                        scope_mask,
                        contrastive_groups,
                    )
                )
                workspace_stats = self.workspace_loss(
                    sampled_latents,
                    sampled_anchor,
                    step_weights=self.workspace_step_weights,
                    compute_spectral=compute_spectral,
                    contrastive_group_ids=sampled_groups,
                )
            workspace_token_count = sampled_latents.shape[0]
        else:
            workspace_stats = self._zero_workspace_stats(base_logits)
            workspace_token_count = 0

        zero = base_logits.detach().sum() * 0.0
        bridge_norm = (
            zero if bridge_state is None else bridge_state.float().norm(dim=-1).mean()
        )
        return {
            "logits": logits,
            "task_loss": task_loss,
            "task_nll_sum": task_nll_sum,
            "base_nll_sum": task_result.get("base_nll_sum"),
            "per_example_nll": task_result.get("per_example_nll"),
            "per_example_base_nll": task_result.get("per_example_base_nll"),
            "per_example_tokens": task_result.get("per_example_tokens"),
            "delta_logit_norm": task_result.get("delta_logit_norm", zero),
            "gated_delta_logit_norm": task_result.get(
                "gated_delta_logit_norm", zero
            ),
            "supervised_tokens": supervised_tokens,
            "workspace_loss": workspace_stats["loss"],
            "workspace_stats": workspace_stats,
            "gate_mean": gate.detach().mean(),
            "gate_max": gate.detach().max(),
            "workspace_tokens": torch.tensor(
                workspace_token_count, device=base_logits.device, dtype=torch.long
            ),
            "workspace_bypassed": torch.tensor(
                bool(bypass_workspace), device=base_logits.device
            ),
            "bridge_state_norm": bridge_norm,
            "memory_changed_fraction": memory_metrics[
                "memory_changed_fraction"
            ],
            "memory_assignment_changed_fraction": memory_metrics[
                "memory_assignment_changed_fraction"
            ],
            "memory_tensor_changed_fraction": memory_metrics[
                "memory_tensor_changed_fraction"
            ],
            "memory_effective_changed_fraction": memory_metrics[
                "memory_effective_changed_fraction"
            ],
            "memory_content_delta_l2": memory_metrics[
                "memory_content_delta_l2"
            ],
            "memory_effective_delta_l2": memory_metrics[
                "memory_effective_delta_l2"
            ],
            "memory_source_norm": memory_metrics["memory_source_norm"],
            "memory_intervened_norm": memory_metrics[
                "memory_intervened_norm"
            ],
            "memory_raw_cosine": memory_metrics["memory_raw_cosine"],
            "memory_layernorm_cosine": memory_metrics[
                "memory_layernorm_cosine"
            ],
            "memory_carrier_presence_fraction": memory_metrics[
                "memory_carrier_presence_fraction"
            ],
            "hard_bypass_fraction": memory_metrics["hard_bypass_fraction"],
        }

    def forward(
        self,
        input_ids: torch.Tensor,
        attention_mask: Optional[torch.Tensor] = None,
        labels: Optional[torch.Tensor] = None,
        prompt_mask: Optional[torch.Tensor] = None,
        context_mask: Optional[torch.Tensor] = None,
        query_mask: Optional[torch.Tensor] = None,
        example_group_ids: Optional[torch.Tensor] = None,
        world_group_ids: Optional[torch.Tensor] = None,
        counterfactual_group_ids: Optional[torch.Tensor] = None,
        answer_classes: Optional[torch.Tensor] = None,
        bridge_context_input_ids: Optional[torch.Tensor] = None,
        bridge_context_attention_mask: Optional[torch.Tensor] = None,
        bridge_input_ids: Optional[torch.Tensor] = None,
        bridge_attention_mask: Optional[torch.Tensor] = None,
        bridge_labels: Optional[torch.Tensor] = None,
        bridge_prompt_mask: Optional[torch.Tensor] = None,
        bridge_query_mask: Optional[torch.Tensor] = None,
        functional_context_input_ids: Optional[torch.Tensor] = None,
        functional_context_attention_mask: Optional[torch.Tensor] = None,
        functional_query_input_ids: Optional[torch.Tensor] = None,
        functional_query_attention_mask: Optional[torch.Tensor] = None,
        functional_query_labels: Optional[torch.Tensor] = None,
        functional_inline_input_ids: Optional[torch.Tensor] = None,
        functional_inline_attention_mask: Optional[torch.Tensor] = None,
        functional_inline_labels: Optional[torch.Tensor] = None,
        functional_query_choice_ids: Optional[torch.Tensor] = None,
        functional_inline_choice_ids: Optional[torch.Tensor] = None,
        functional_answer_classes: Optional[torch.Tensor] = None,
        functional_query_valid_mask: Optional[torch.Tensor] = None,
        functional_affected_mask: Optional[torch.Tensor] = None,
        functional_heldout_mask: Optional[torch.Tensor] = None,
        functional_hop_distances: Optional[torch.Tensor] = None,
        functional_pair_ids: Optional[torch.Tensor] = None,
        *,
        compute_workspace_loss: bool = True,
        compute_spectral: bool = True,
        return_full_logits: bool = False,
        logits_to_keep: int = 0,
        bypass_workspace: bool = False,
        rng_streams: Optional[Mapping[str, int]] = None,
        memory_intervention: str = "intact",
        memory_intervention_seed: int = 0,
    ) -> dict[str, Any]:
        if attention_mask is None:
            attention_mask = torch.ones_like(input_ids, dtype=torch.long)
        if logits_to_keep < 0:
            raise ValueError("logits_to_keep must be non-negative.")
        if self.workspace_config.route_topology == "functional_workspace":
            return self._forward_functional_workspace(
                functional_context_input_ids=functional_context_input_ids,
                functional_context_attention_mask=functional_context_attention_mask,
                functional_query_input_ids=functional_query_input_ids,
                functional_query_attention_mask=functional_query_attention_mask,
                functional_query_labels=functional_query_labels,
                functional_inline_input_ids=functional_inline_input_ids,
                functional_inline_attention_mask=functional_inline_attention_mask,
                functional_inline_labels=functional_inline_labels,
                functional_query_choice_ids=functional_query_choice_ids,
                functional_inline_choice_ids=functional_inline_choice_ids,
                functional_answer_classes=functional_answer_classes,
                functional_query_valid_mask=functional_query_valid_mask,
                functional_affected_mask=functional_affected_mask,
                functional_heldout_mask=functional_heldout_mask,
                functional_hop_distances=functional_hop_distances,
                functional_pair_ids=functional_pair_ids,
                compute_workspace_loss=compute_workspace_loss,
                compute_spectral=compute_spectral,
                bypass_workspace=bypass_workspace,
                rng_streams=rng_streams,
                memory_intervention=memory_intervention,
                memory_intervention_seed=memory_intervention_seed,
            )
        if self.workspace_config.route_topology == "deferred_bridge":
            return self._forward_deferred_bridge(
                input_ids=input_ids,
                attention_mask=attention_mask,
                labels=labels,
                prompt_mask=prompt_mask,
                context_mask=context_mask,
                query_mask=query_mask,
                bridge_context_input_ids=bridge_context_input_ids,
                bridge_context_attention_mask=bridge_context_attention_mask,
                bridge_input_ids=bridge_input_ids,
                bridge_attention_mask=bridge_attention_mask,
                bridge_labels=bridge_labels,
                bridge_prompt_mask=bridge_prompt_mask,
                bridge_query_mask=bridge_query_mask,
                example_group_ids=example_group_ids,
                world_group_ids=world_group_ids,
                counterfactual_group_ids=counterfactual_group_ids,
                answer_classes=answer_classes,
                compute_workspace_loss=compute_workspace_loss,
                compute_spectral=compute_spectral,
                return_full_logits=return_full_logits,
                logits_to_keep=logits_to_keep,
                bypass_workspace=bypass_workspace,
                rng_streams=rng_streams,
                memory_intervention=memory_intervention,
                memory_intervention_seed=memory_intervention_seed,
            )
        if memory_intervention != "intact":
            raise ValueError(
                "Context-memory interventions require deferred_bridge or functional_workspace."
            )

        base_outputs, causal_hidden = self._base_forward_with_hidden_capture(
            input_ids,
            attention_mask,
        )
        base_logits = getattr(base_outputs, "logits", None)
        if base_logits is None:
            raise RuntimeError("The base causal LM did not return logits.")
        if causal_hidden.shape[-1] != self.hidden_dim:
            raise RuntimeError(
                f"Captured hidden size {causal_hidden.shape[-1]} does not match "
                f"configured hidden size {self.hidden_dim}."
            )

        route_scale = float(self.workspace_config.logit_residual_scale)
        need_route = (not bypass_workspace) and route_scale != 0.0
        need_auxiliary = (not bypass_workspace) and bool(compute_workspace_loss)
        route_seed = None if rng_streams is None else rng_streams.get("route")
        auxiliary_seed = None if rng_streams is None else rng_streams.get("auxiliary")
        isolate = rng_streams is not None

        route_latents: Optional[torch.Tensor] = None
        route_anchor: Optional[torch.Tensor] = None
        if need_route:
            with isolated_torch_rng(isolate, route_seed, causal_hidden.device):
                route_latents, route_anchor = self.workspace(
                    causal_hidden, attention_mask
                )
            final_state = route_latents[:, :, -1, :]
            gate = torch.sigmoid(self.gate(self.gate_norm(causal_hidden)))
        else:
            final_state = None
            gate = torch.zeros(
                (*causal_hidden.shape[:2], 1),
                device=causal_hidden.device,
                dtype=causal_hidden.dtype,
            )

        task_result: dict[str, torch.Tensor] = {}
        task_loss: Optional[torch.Tensor] = None
        task_nll_sum: Optional[torch.Tensor] = None
        supervised_tokens = torch.zeros((), device=base_logits.device, dtype=torch.long)
        if labels is not None:
            if need_route:
                assert final_state is not None
                task_result = self._supervised_task_loss(
                    base_logits, final_state, gate, labels
                )
            else:
                task_result = self._base_only_task_loss(base_logits, labels)
            task_loss = task_result["task_loss"]
            task_nll_sum = task_result["task_nll_sum"]
            supervised_tokens = task_result["supervised_tokens"]

        logits: Optional[torch.Tensor]
        if labels is not None and not return_full_logits:
            logits = None
        else:
            keep = base_logits.shape[1] if logits_to_keep == 0 else min(
                logits_to_keep, base_logits.shape[1]
            )
            if need_route:
                assert final_state is not None
                logits = self._adapt_logit_slice(
                    base_logits[:, -keep:, :],
                    final_state[:, -keep:, :],
                    gate[:, -keep:, :],
                )
            else:
                logits = base_logits[:, -keep:, :]

        if need_auxiliary:
            scope_mask = self._workspace_scope_mask(
                attention_mask,
                labels,
                prompt_mask,
                context_mask,
                query_mask,
            )

            if route_latents is not None and self.workspace_config.aux_backprop_to_base:
                aux_latents = route_latents
                assert route_anchor is not None
                aux_anchor = route_anchor
            else:
                aux_hidden = (
                    causal_hidden
                    if self.workspace_config.aux_backprop_to_base
                    else causal_hidden.detach()
                )
                with isolated_torch_rng(isolate, auxiliary_seed, causal_hidden.device):
                    aux_latents, aux_anchor = self.workspace(
                        aux_hidden, attention_mask
                    )

            negative_scope = self.workspace_config.contrastive_negative_scope
            if negative_scope == "all":
                contrastive_groups = None
            elif negative_scope == "cross_example":
                contrastive_groups = example_group_ids
            else:
                contrastive_groups = world_group_ids

            sample_seed = (
                None
                if auxiliary_seed is None
                else (int(auxiliary_seed) + 1) % (2**63 - 1)
            )
            with isolated_torch_rng(isolate, sample_seed, causal_hidden.device):
                sampled_latents, sampled_anchor, sampled_groups = (
                    self._sample_workspace_states(
                        aux_latents,
                        aux_anchor,
                        scope_mask,
                        contrastive_groups,
                    )
                )
                workspace_stats = self.workspace_loss(
                    sampled_latents,
                    sampled_anchor,
                    step_weights=self.workspace_step_weights,
                    compute_spectral=compute_spectral,
                    contrastive_group_ids=sampled_groups,
                )
            workspace_token_count = sampled_latents.shape[0]
        else:
            workspace_stats = self._zero_workspace_stats(base_logits)
            workspace_token_count = 0

        return {
            "logits": logits,
            "task_loss": task_loss,
            "task_nll_sum": task_nll_sum,
            "base_nll_sum": task_result.get("base_nll_sum"),
            "per_example_nll": task_result.get("per_example_nll"),
            "per_example_base_nll": task_result.get("per_example_base_nll"),
            "per_example_tokens": task_result.get("per_example_tokens"),
            "delta_logit_norm": task_result.get(
                "delta_logit_norm", base_logits.detach().sum() * 0.0
            ),
            "gated_delta_logit_norm": task_result.get(
                "gated_delta_logit_norm", base_logits.detach().sum() * 0.0
            ),
            "supervised_tokens": supervised_tokens,
            "workspace_loss": workspace_stats["loss"],
            "workspace_stats": workspace_stats,
            "gate_mean": gate.detach().mean(),
            "gate_max": gate.detach().max(),
            "workspace_tokens": torch.tensor(
                workspace_token_count,
                device=base_logits.device,
                dtype=torch.long,
            ),
            "workspace_bypassed": torch.tensor(
                bool(bypass_workspace), device=base_logits.device
            ),
            "bridge_state_norm": base_logits.detach().sum() * 0.0,
            "memory_changed_fraction": base_logits.detach().sum() * 0.0,
            "memory_assignment_changed_fraction": base_logits.detach().sum() * 0.0,
            "memory_tensor_changed_fraction": base_logits.detach().sum() * 0.0,
            "memory_effective_changed_fraction": base_logits.detach().sum() * 0.0,
            "memory_content_delta_l2": base_logits.detach().sum() * 0.0,
            "memory_effective_delta_l2": base_logits.detach().sum() * 0.0,
            "memory_source_norm": base_logits.detach().sum() * 0.0,
            "memory_intervened_norm": base_logits.detach().sum() * 0.0,
            "memory_raw_cosine": base_logits.detach().sum() * 0.0,
            "memory_layernorm_cosine": base_logits.detach().sum() * 0.0,
            "memory_carrier_presence_fraction": base_logits.detach().sum() * 0.0,
            "hard_bypass_fraction": base_logits.detach().sum() * 0.0,
        }

    def custom_state_dict(self) -> dict[str, torch.Tensor]:
        result: dict[str, torch.Tensor] = {}
        for name, tensor in self.state_dict().items():
            if not name.startswith("base_model."):
                result[name] = tensor.detach().cpu()
        return result

    def load_custom_state_dict(self, state: Mapping[str, torch.Tensor]) -> None:
        missing, unexpected = self.load_state_dict(dict(state), strict=False)
        invalid_missing = [name for name in missing if not name.startswith("base_model.")]
        if invalid_missing or unexpected:
            raise RuntimeError(
                f"Custom checkpoint mismatch. Missing={invalid_missing}, "
                f"unexpected={list(unexpected)}"
            )


# =============================================================================
# Model loading and trainability
# =============================================================================


def _import_transformers() -> tuple[Any, Any]:
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as exc:
        raise RuntimeError(
            "transformers is required for CLI training. Install requirements.txt."
        ) from exc
    return AutoModelForCausalLM, AutoTokenizer


def _torch_dtype_from_name(name: str) -> torch.dtype | str:
    mapping: dict[str, torch.dtype | str] = {
        "auto": "auto",
        "float32": torch.float32,
        "fp32": torch.float32,
        "float16": torch.float16,
        "fp16": torch.float16,
        "bfloat16": torch.bfloat16,
        "bf16": torch.bfloat16,
    }
    normalized = name.lower()
    if normalized not in mapping:
        raise ValueError(f"Unsupported dtype: {name}")
    return mapping[normalized]


def load_tokenizer(config: ModelConfig) -> Any:
    _, AutoTokenizer = _import_transformers()
    tokenizer = AutoTokenizer.from_pretrained(
        config.name_or_path,
        revision=config.revision,
        trust_remote_code=config.trust_remote_code,
        local_files_only=config.local_files_only,
    )
    if getattr(tokenizer, "pad_token_id", None) is None:
        eos_id = getattr(tokenizer, "eos_token_id", None)
        if eos_id is None:
            raise ValueError("Tokenizer has neither pad_token_id nor eos_token_id.")
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"
    return tokenizer


def _load_hf_model(config: ModelConfig) -> nn.Module:
    AutoModelForCausalLM, _ = _import_transformers()
    dtype = _torch_dtype_from_name(config.dtype)
    kwargs: dict[str, Any] = {
        "revision": config.revision,
        "trust_remote_code": config.trust_remote_code,
        "local_files_only": config.local_files_only,
    }
    if dtype != "auto":
        kwargs["dtype"] = dtype
    if config.attn_implementation != "auto":
        kwargs["attn_implementation"] = config.attn_implementation

    try:
        model = AutoModelForCausalLM.from_pretrained(config.name_or_path, **kwargs)
    except TypeError:
        # Transformers 4.x used torch_dtype while 5.x documents dtype.
        if "dtype" not in kwargs:
            raise
        kwargs["torch_dtype"] = kwargs.pop("dtype")
        model = AutoModelForCausalLM.from_pretrained(config.name_or_path, **kwargs)

    if hasattr(model.config, "use_cache"):
        model.config.use_cache = False
    return model


def _apply_lora(model: nn.Module, config: ModelConfig) -> nn.Module:
    try:
        from peft import LoraConfig, get_peft_model
    except ImportError as exc:
        raise RuntimeError(
            "train_mode='lora' requires peft. Install the optional dependency."
        ) from exc

    lora_config = LoraConfig(
        task_type="CAUSAL_LM",
        inference_mode=False,
        r=config.lora_r,
        lora_alpha=config.lora_alpha,
        lora_dropout=config.lora_dropout,
        target_modules=config.lora_target_modules,
        bias="none",
        use_rslora=config.lora_use_rslora,
    )
    return get_peft_model(model, lora_config)


def infer_hidden_size(model: nn.Module) -> int:
    config = getattr(model, "config", None)
    candidates = []
    if config is not None:
        candidates.extend(
            [
                getattr(config, "hidden_size", None),
                getattr(config, "n_embd", None),
                getattr(config, "d_model", None),
            ]
        )
        text_config = getattr(config, "text_config", None)
        if text_config is not None:
            candidates.append(getattr(text_config, "hidden_size", None))
    for candidate in candidates:
        if isinstance(candidate, int) and candidate > 0:
            return candidate
    raise ValueError("Could not infer the base model hidden size.")


def infer_vocab_size(model: nn.Module) -> int:
    config = getattr(model, "config", None)
    candidates = []
    if config is not None:
        candidates.append(getattr(config, "vocab_size", None))
        text_config = getattr(config, "text_config", None)
        if text_config is not None:
            candidates.append(getattr(text_config, "vocab_size", None))
    for candidate in candidates:
        if isinstance(candidate, int) and candidate > 0:
            return candidate

    getter = getattr(model, "get_output_embeddings", None)
    head = getter() if getter is not None else None
    out_features = getattr(head, "out_features", None)
    if isinstance(out_features, int) and out_features > 0:
        return out_features
    weight = getattr(head, "weight", None)
    if isinstance(weight, torch.Tensor):
        return int(weight.shape[0])
    raise ValueError("Could not infer the base model vocabulary size.")


def configure_trainability(model: LatentWorkspaceCausalLM, mode: str) -> None:
    if mode == "workspace_only":
        for parameter in model.base_model.parameters():
            parameter.requires_grad_(False)
    elif mode in {"full", "lora"}:
        # PEFT has already frozen non-LoRA parameters. Do not undo that here.
        if mode == "full":
            for parameter in model.base_model.parameters():
                parameter.requires_grad_(True)
    else:
        raise ValueError(f"Unsupported train mode: {mode}")

    for module in (
        model.workspace,
        model.logit_adapter,
        model.gate_norm,
        model.gate,
        model.workspace_loss,
    ):
        for parameter in module.parameters():
            parameter.requires_grad_(True)


def enable_gradient_checkpointing(model: nn.Module) -> None:
    method = getattr(model, "gradient_checkpointing_enable", None)
    if method is None:
        return
    try:
        method(gradient_checkpointing_kwargs={"use_reentrant": False})
    except TypeError:
        method()
    input_grad_method = getattr(model, "enable_input_require_grads", None)
    if input_grad_method is not None:
        input_grad_method()


def build_workspace_model(config: ExperimentConfig) -> tuple[LatentWorkspaceCausalLM, Any]:
    tokenizer = load_tokenizer(config.model)
    base_model = _load_hf_model(config.model)
    if config.model.train_mode == "lora":
        base_model = _apply_lora(base_model, config.model)
    if (
        config.model.gradient_checkpointing
        and config.model.train_mode != "workspace_only"
    ):
        enable_gradient_checkpointing(base_model)

    wrapper = LatentWorkspaceCausalLM(
        base_model=base_model,
        hidden_dim=infer_hidden_size(base_model),
        vocab_size=infer_vocab_size(base_model),
        config=config.workspace,
        functional_config=config.functional,
        hidden_capture=config.model.hidden_capture,
        base_activation_offload=config.train.base_activation_offload,
    )
    configure_trainability(wrapper, config.model.train_mode)
    return wrapper, tokenizer


# =============================================================================
# Training engine
# =============================================================================


@dataclass
class DistributedContext:
    enabled: bool
    rank: int
    local_rank: int
    world_size: int
    backend: str
    device: torch.device

    @property
    def is_main(self) -> bool:
        return self.rank == 0

    def barrier(self) -> None:
        if self.enabled:
            torch.distributed.barrier()

    def all_reduce_sum_int(self, value: int) -> int:
        if not self.enabled:
            return int(value)
        tensor = torch.tensor(value, device=self.device, dtype=torch.long)
        torch.distributed.all_reduce(tensor, op=torch.distributed.ReduceOp.SUM)
        return int(tensor.item())

    def all_true(self, value: bool) -> bool:
        if not self.enabled:
            return bool(value)
        tensor = torch.tensor(
            1 if value else 0,
            device=self.device,
            dtype=torch.int32,
        )
        torch.distributed.all_reduce(tensor, op=torch.distributed.ReduceOp.MIN)
        return bool(tensor.item())

    def any_true(self, value: bool) -> bool:
        if not self.enabled:
            return bool(value)
        tensor = torch.tensor(
            1 if value else 0,
            device=self.device,
            dtype=torch.int32,
        )
        torch.distributed.all_reduce(tensor, op=torch.distributed.ReduceOp.MAX)
        return bool(tensor.item())

    def all_gather_objects(self, value: Any) -> list[Any]:
        if not self.enabled:
            return [value]
        gathered: list[Any] = [None for _ in range(self.world_size)]
        torch.distributed.all_gather_object(gathered, value)
        return gathered

    def broadcast_object(self, value: Any, source: int = 0) -> Any:
        if not self.enabled:
            return value
        payload = [value if self.rank == source else None]
        torch.distributed.broadcast_object_list(payload, src=source)
        return payload[0]

    def close(self) -> None:
        if self.enabled and torch.distributed.is_initialized():
            torch.distributed.destroy_process_group()


def _require_gradient_accumulation_offload_context(
    train: TrainConfig,
    context: DistributedContext,
) -> None:
    if train.gradient_accumulation_offload not in {"cpu", "cpu_accumulate"}:
        return
    if context.enabled or context.world_size != 1:
        raise RuntimeError(
            "train.gradient_accumulation_offload='cpu' is single-process only; "
            "clearing gradients between no_sync microbatches would break DDP's "
            "final reduction."
        )
    if context.device.type != "cuda":
        raise RuntimeError(
            "train.gradient_accumulation_offload='cpu' requires a CUDA device."
        )


def initialize_distributed(config: TrainConfig) -> DistributedContext:
    world_size = int(os.environ.get("WORLD_SIZE", "1"))
    rank = int(os.environ.get("RANK", "0"))
    local_rank = int(os.environ.get("LOCAL_RANK", "0"))

    if config.distributed == "none" and world_size > 1:
        raise RuntimeError(
            "WORLD_SIZE>1 but train.distributed='none'. Refusing to launch "
            "independent writers into one output directory."
        )
    enabled = config.distributed == "ddp" or (
        config.distributed == "auto" and world_size > 1
    )
    if enabled and world_size <= 1:
        raise RuntimeError(
            "train.distributed='ddp' requires torchrun (WORLD_SIZE must exceed 1)."
        )

    if not enabled:
        return DistributedContext(
            enabled=False,
            rank=0,
            local_rank=0,
            world_size=1,
            backend="none",
            device=resolve_device(config.device),
        )

    if torch.cuda.is_available():
        torch.cuda.set_device(local_rank)
        device = torch.device("cuda", local_rank)
        backend = "nccl" if config.ddp_backend == "auto" else config.ddp_backend
    else:
        device = torch.device("cpu")
        backend = "gloo" if config.ddp_backend == "auto" else config.ddp_backend
    if backend == "nccl" and device.type != "cuda":
        raise RuntimeError("NCCL requires CUDA devices.")

    torch.distributed.init_process_group(
        backend=backend,
        timeout=_datetime.timedelta(minutes=config.ddp_timeout_minutes),
    )
    return DistributedContext(
        enabled=True,
        rank=rank,
        local_rank=local_rank,
        world_size=world_size,
        backend=backend,
        device=device,
    )


def configure_runtime_math(config: TrainConfig) -> None:
    torch.set_float32_matmul_precision(config.matmul_precision)
    torch.use_deterministic_algorithms(config.deterministic_algorithms)
    if torch.cuda.is_available():
        torch.backends.cuda.matmul.allow_tf32 = bool(config.allow_tf32)
        if getattr(torch.backends, "cudnn", None) is not None:
            torch.backends.cudnn.allow_tf32 = bool(config.allow_tf32)
            torch.backends.cudnn.benchmark = not config.deterministic_algorithms


def set_global_seed(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def deterministic_stream_seed(
    base_seed: int,
    rank: int,
    global_step: int,
    microbatch_index: int,
    stream_offset: int,
    *,
    substream: int = 0,
) -> int:
    """Derive a stable stateless RNG seed without Python's randomized hash()."""
    payload = (
        f"{int(base_seed)}:{int(rank)}:{int(global_step)}:"
        f"{int(microbatch_index)}:{int(stream_offset)}:{int(substream)}"
    ).encode("utf-8")
    value = int.from_bytes(hashlib.sha256(payload).digest()[:8], "little")
    return value % (2**63 - 1)


@contextlib.contextmanager
def isolated_torch_rng(
    enabled: bool,
    seed: Optional[int],
    device: torch.device,
) -> Iterator[None]:
    """Run stochastic workspace code without advancing the base RNG stream.

    The context saves/restores the CPU RNG and the active CUDA device RNG. It is
    deliberately stateless across steps: the caller derives a seed from run
    coordinates, so exact resume requires no additional mutable stream state.
    """
    if not enabled or seed is None:
        yield
        return
    devices: list[int] = []
    if device.type == "cuda":
        devices = [
            int(device.index)
            if device.index is not None
            else int(torch.cuda.current_device())
        ]
    with torch.random.fork_rng(devices=devices, enabled=True):
        torch.manual_seed(int(seed))
        if device.type == "cuda":
            torch.cuda.manual_seed(int(seed))
        yield


def _cuda_base_activation_offload(device: torch.device) -> Any:
    """Offload only tensors saved by a CUDA base-encoder graph.

    Full-update gradient accumulation keeps base gradients resident while the
    next microbatch recomputes its activations. Functional context/query split
    transformer calls are the narrow graph regions whose saved activations can
    safely be packed to host memory without changing graph connectivity,
    parameter gradients, RNG streams, or optimizer semantics. Reader/writer
    operations remain outside this context so persistent workspace parameters
    are never duplicated by the saved-tensor hook.
    """

    if device.type != "cuda" or not torch.is_grad_enabled():
        return contextlib.nullcontext()
    return torch.autograd.graph.save_on_cpu(
        pin_memory=True,
        device_type=device.type,
    )


def make_rng_streams(
    config: AttributionConfig,
    *,
    base_seed: int,
    rank: int,
    global_step: int,
    microbatch_index: int,
) -> dict[str, int]:
    return {
        "context": deterministic_stream_seed(
            base_seed,
            rank,
            global_step,
            microbatch_index,
            config.context_seed_offset,
        ),
        "route": deterministic_stream_seed(
            base_seed,
            rank,
            global_step,
            microbatch_index,
            config.route_seed_offset,
        ),
        "auxiliary": deterministic_stream_seed(
            base_seed,
            rank,
            global_step,
            microbatch_index,
            config.auxiliary_seed_offset,
        ),
        "assay": deterministic_stream_seed(
            base_seed,
            rank,
            global_step,
            microbatch_index,
            config.assay_seed_offset,
        ),
    }


def resolve_device(name: str) -> torch.device:
    normalized = name.lower()
    if normalized == "auto":
        if torch.cuda.is_available():
            return torch.device("cuda")
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")
    device = torch.device(normalized)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable.")
    if device.type == "mps":
        mps = getattr(torch.backends, "mps", None)
        if mps is None or not mps.is_available():
            raise RuntimeError("MPS was requested but is unavailable.")
    return device


def resolve_mixed_precision(name: str, device: torch.device) -> str:
    normalized = name.lower()
    if normalized == "auto":
        if device.type == "cuda":
            return "bf16" if torch.cuda.is_bf16_supported() else "fp16"
        return "no"
    if normalized not in {"no", "fp16", "bf16"}:
        raise ValueError("mixed_precision must be auto, no, fp16, or bf16.")
    if device.type != "cuda" and normalized != "no":
        return "no"
    if normalized == "bf16" and device.type == "cuda" and not torch.cuda.is_bf16_supported():
        raise RuntimeError("bf16 was requested but this CUDA device does not support it.")
    return normalized


def autocast_context(device: torch.device, precision: str) -> Any:
    if precision == "no":
        return contextlib.nullcontext()
    dtype = torch.float16 if precision == "fp16" else torch.bfloat16
    return torch.autocast(device_type=device.type, dtype=dtype)


def make_grad_scaler(device: torch.device, precision: str) -> Any:
    enabled = device.type == "cuda" and precision == "fp16"
    try:
        return torch.amp.GradScaler("cuda", enabled=enabled)
    except (AttributeError, TypeError):
        return torch.cuda.amp.GradScaler(enabled=enabled)


def unwrap_model(model: nn.Module) -> LatentWorkspaceCausalLM:
    current = model
    while hasattr(current, "module"):
        current = current.module  # type: ignore[assignment]
    if not isinstance(current, LatentWorkspaceCausalLM):
        raise TypeError("Expected a LatentWorkspaceCausalLM after unwrapping.")
    return current


def _auto_find_unused_parameters(config: ExperimentConfig) -> bool:
    # Any scheduled intervention can make the regularizer branch disappear for
    # part of the run. Even when the runtime route remains active, probe and
    # geometry parameters are unused during washout. DDP must be told to expect
    # that dynamic graph.
    return (
        config.workspace.loss_weight == 0.0
        or config.workspace.logit_residual_scale == 0.0
        or config.induction.enabled
        or config.functional.enabled
    )


def wrap_distributed_model(
    model: LatentWorkspaceCausalLM,
    context: DistributedContext,
    config: ExperimentConfig,
) -> nn.Module:
    if not context.enabled:
        return model

    setting = config.train.ddp_find_unused_parameters
    if setting == "auto":
        find_unused = _auto_find_unused_parameters(config)
    else:
        find_unused = setting == "true"

    kwargs: dict[str, Any] = {
        "broadcast_buffers": False,
        "find_unused_parameters": find_unused,
        "gradient_as_bucket_view": True,
        "static_graph": bool(config.train.ddp_static_graph),
    }
    if context.device.type == "cuda":
        kwargs["device_ids"] = [context.local_rank]
        kwargs["output_device"] = context.local_rank
    return torch.nn.parallel.DistributedDataParallel(model, **kwargs)


def count_parameters(model: nn.Module) -> dict[str, int]:
    raw = unwrap_model(model) if not isinstance(model, LatentWorkspaceCausalLM) else model
    total = sum(parameter.numel() for parameter in raw.parameters())
    trainable = sum(
        parameter.numel() for parameter in raw.parameters() if parameter.requires_grad
    )
    workspace = sum(
        parameter.numel()
        for name, parameter in raw.named_parameters()
        if not name.startswith("base_model.")
    )
    return {"total": total, "trainable": trainable, "workspace": workspace}


def _uses_weight_decay(name: str, parameter: nn.Parameter) -> bool:
    lowered = name.lower()
    if parameter.ndim < 2:
        return False
    return not (
        lowered.endswith(".bias")
        or "norm" in lowered
        or "layernorm" in lowered
        or "embedding" in lowered
    )


def build_optimizer(
    model: LatentWorkspaceCausalLM,
    config: TrainConfig,
    device: Optional[torch.device] = None,
) -> torch.optim.Optimizer:
    buckets: dict[tuple[str, bool], list[nn.Parameter]] = {
        ("base", True): [],
        ("base", False): [],
        ("workspace", True): [],
        ("workspace", False): [],
    }

    seen: set[int] = set()
    for name, parameter in model.named_parameters():
        if not parameter.requires_grad or id(parameter) in seen:
            continue
        seen.add(id(parameter))
        family = "base" if name.startswith("base_model.") else "workspace"
        buckets[(family, _uses_weight_decay(name, parameter))].append(parameter)

    groups: list[dict[str, Any]] = []
    for family in ("base", "workspace"):
        learning_rate = (
            config.learning_rate
            if family == "base"
            else config.workspace_learning_rate
        )
        for decay in (True, False):
            parameters = buckets[(family, decay)]
            if parameters:
                groups.append(
                    {
                        "params": parameters,
                        "lr": learning_rate,
                        "weight_decay": config.weight_decay if decay else 0.0,
                        "family": family,
                    }
                )

    if not groups:
        raise RuntimeError("No trainable parameters were found.")

    if config.optimizer == "adafactor":
        try:
            from transformers.optimization import Adafactor
        except ImportError as exc:
            raise RuntimeError(
                "train.optimizer='adafactor' requires Transformers Adafactor."
            ) from exc
        # No first-moment state and factored second moments keep full-parameter
        # updating materially smaller than AdamW. Explicit step-size mode keeps
        # the configured base/workspace learning rates authoritative.
        return Adafactor(
            groups,
            lr=config.learning_rate,
            eps=(1e-30, 1e-3),
            clip_threshold=1.0,
            decay_rate=-0.8,
            beta1=None,
            weight_decay=0.0,
            scale_parameter=False,
            relative_step=False,
            warmup_init=False,
        )

    if config.optimizer != "adamw":
        raise ValueError(f"Unsupported optimizer: {config.optimizer!r}.")

    kwargs: dict[str, Any] = {
        "betas": (config.adam_beta1, config.adam_beta2),
        "eps": config.adam_eps,
    }
    request_fused = config.fused_adamw == "true" or (
        config.fused_adamw == "auto" and device is not None and device.type == "cuda"
    )
    if request_fused:
        kwargs["fused"] = True
    try:
        return torch.optim.AdamW(groups, **kwargs)
    except (TypeError, RuntimeError):
        if config.fused_adamw == "true":
            raise
        kwargs.pop("fused", None)
        return torch.optim.AdamW(groups, **kwargs)


def _named_parameter_aliases(
    module: nn.Module,
    *,
    prefix: str = "",
) -> dict[int, dict[str, Any]]:
    """Index physical parameters while retaining deterministic alias names."""
    try:
        iterator = module.named_parameters(remove_duplicate=False)
    except TypeError:
        iterator = module.named_parameters()
    records: dict[int, dict[str, Any]] = {}
    for name, parameter in iterator:
        physical_id = id(parameter)
        record = records.setdefault(
            physical_id,
            {"parameter": parameter, "names": set()},
        )
        record["names"].add(f"{prefix}{name}")
    return records


@dataclass(frozen=True)
class _CPUGradientAccumulatorSpec:
    name: str
    parameter: nn.Parameter = field(repr=False, compare=False)
    shape: tuple[int, ...]
    stride: tuple[int, ...]
    dtype: torch.dtype
    device: torch.device


class _CPUGradientAccumulator:
    """Store one accumulation window's gradients on host memory.

    ``merge_device='cuda'`` is the original exact-spill path: prior host state
    returns to CUDA for every merge. ``merge_device='cpu'`` keeps the same
    microbatch order and dtype but performs only the cross-microbatch ``add_``
    on pinned host tensors. The latter needs one D2H gradient volume per
    microbatch and one final H2D restore instead of a round trip per merge.
    """

    def __init__(
        self,
        parameters: Iterable[tuple[str, nn.Parameter]],
        *,
        require_cuda: bool = False,
        merge_device: str = "cuda",
    ) -> None:
        if merge_device not in {"cuda", "cpu"}:
            raise RuntimeError(
                "CPU gradient accumulation merge_device must be cuda or cpu."
            )
        specs: list[_CPUGradientAccumulatorSpec] = []
        names: set[str] = set()
        physical_ids: set[int] = set()
        for name, parameter in parameters:
            if not isinstance(name, str) or not name:
                raise RuntimeError(
                    "CPU gradient accumulation requires non-empty parameter names."
                )
            if name in names:
                raise RuntimeError(
                    f"Duplicate CPU gradient accumulation parameter name: {name!r}."
                )
            if not isinstance(parameter, nn.Parameter):
                raise RuntimeError(
                    f"CPU gradient accumulation entry {name!r} is not a Parameter."
                )
            physical_id = id(parameter)
            if physical_id in physical_ids:
                raise RuntimeError(
                    "CPU gradient accumulation received a duplicate physical "
                    f"parameter at {name!r}."
                )
            if not parameter.requires_grad:
                raise RuntimeError(
                    f"CPU gradient accumulation parameter {name!r} is not trainable."
                )
            if parameter.layout is not torch.strided:
                raise RuntimeError(
                    f"CPU gradient accumulation parameter {name!r} is not strided."
                )
            if not torch.is_floating_point(parameter):
                raise RuntimeError(
                    f"CPU gradient accumulation parameter {name!r} is not floating point."
                )
            if require_cuda and parameter.device.type != "cuda":
                raise RuntimeError(
                    "CPU gradient accumulation offload requires every trainable "
                    f"parameter on CUDA; {name!r} is on {parameter.device}."
                )
            names.add(name)
            physical_ids.add(physical_id)
            specs.append(
                _CPUGradientAccumulatorSpec(
                    name=name,
                    parameter=parameter,
                    shape=tuple(parameter.shape),
                    stride=tuple(parameter.stride()),
                    dtype=parameter.dtype,
                    device=parameter.device,
                )
            )
        if not specs:
            raise RuntimeError(
                "CPU gradient accumulation offload found no trainable parameters."
            )

        # Releasing small current gradients before a large merge bounds the
        # transient device allocation to one parameter-sized tensor.
        self._specs = tuple(
            sorted(specs, key=lambda spec: (spec.parameter.numel(), spec.name))
        )
        self._specs_by_id = {id(spec.parameter): spec for spec in self._specs}
        self._merge_device = merge_device
        self._pin_memory = bool(
            merge_device == "cpu"
            and self._specs
            and all(spec.device.type == "cuda" for spec in self._specs)
        )
        self._buffers: dict[int, torch.Tensor] = {}
        self._staging_buffers: dict[int, torch.Tensor] = {}
        self._seen_parameter_ids: set[int] = set()
        self._buffer_strides: dict[int, tuple[int, ...]] = {}
        self._spill_count = 0
        self._merge_count = 0
        self._first_spill_count = 0
        self._cumulative_current_gradient_bytes = 0
        self._peak_cpu_accumulator_bytes = 0
        self._peak_cpu_staging_bytes = 0
        self._peak_cpu_total_bytes = 0
        self._active = True

    def schema_records(self) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "shape": list(spec.shape),
                "stride": list(spec.stride),
                "dtype": str(spec.dtype),
                "device": str(spec.device),
                "numel": int(spec.parameter.numel()),
                "logical_bytes": int(
                    spec.parameter.numel() * spec.parameter.element_size()
                ),
            }
            for spec in sorted(self._specs, key=lambda spec: spec.name)
        ]

    @staticmethod
    def _storage_bytes(tensor: torch.Tensor) -> int:
        try:
            return int(tensor.untyped_storage().nbytes())
        except (AttributeError, RuntimeError):
            return int(tensor.numel() * tensor.element_size())

    def _buffer_bytes(self) -> int:
        return sum(self._storage_bytes(buffer) for buffer in self._buffers.values())

    def _staging_bytes(self) -> int:
        return sum(
            self._storage_bytes(buffer) for buffer in self._staging_buffers.values()
        )

    def _live_cpu_buffer_count(self) -> int:
        return len(self._buffers) + len(self._staging_buffers)

    def _live_cpu_buffer_bytes(self) -> int:
        return self._buffer_bytes() + self._staging_bytes()

    def _empty_cpu_like(self, tensor: torch.Tensor) -> torch.Tensor:
        return torch.empty_strided(
            tuple(tensor.shape),
            tuple(tensor.stride()),
            dtype=tensor.dtype,
            device="cpu",
            pin_memory=self._pin_memory,
        )

    def _require_active(self) -> None:
        if not self._active:
            raise RuntimeError("CPU gradient accumulator is no longer active.")

    @staticmethod
    def _has_internal_overlap(tensor: torch.Tensor) -> bool:
        checker = getattr(torch, "_debug_has_internal_overlap", None)
        if checker is None:
            return False
        return int(checker(tensor)) != 0

    def _validate_parameter(self, spec: _CPUGradientAccumulatorSpec) -> None:
        parameter = spec.parameter
        failures: list[str] = []
        if not parameter.requires_grad:
            failures.append("requires_grad")
        if tuple(parameter.shape) != spec.shape:
            failures.append("shape")
        if parameter.layout is not torch.strided:
            failures.append("layout")
        elif tuple(parameter.stride()) != spec.stride:
            failures.append("stride")
        if parameter.dtype != spec.dtype:
            failures.append("dtype")
        if parameter.device != spec.device:
            failures.append("device")
        if failures:
            raise RuntimeError(
                "CPU gradient accumulation parameter schema changed for "
                f"{spec.name!r}: {sorted(failures)}."
            )

    def _validate_gradient(
        self,
        spec: _CPUGradientAccumulatorSpec,
        gradient: torch.Tensor,
    ) -> None:
        failures: list[str] = []
        if tuple(gradient.shape) != spec.shape:
            failures.append("shape")
        if gradient.layout is not torch.strided:
            failures.append("layout")
        elif self._has_internal_overlap(gradient):
            failures.append("internal_overlap")
        if gradient.dtype != spec.dtype:
            failures.append("dtype")
        if gradient.device != spec.device:
            failures.append("device")
        if gradient.requires_grad or gradient.grad_fn is not None:
            failures.append("autograd_history")
        if failures:
            raise RuntimeError(
                "CPU gradient accumulation gradient schema mismatch for "
                f"{spec.name!r}: {sorted(failures)}."
            )

    def _validate_buffer(
        self,
        spec: _CPUGradientAccumulatorSpec,
        buffer: torch.Tensor,
    ) -> None:
        failures: list[str] = []
        if tuple(buffer.shape) != spec.shape:
            failures.append("shape")
        if buffer.layout is not torch.strided:
            failures.append("layout")
        elif self._has_internal_overlap(buffer):
            failures.append("internal_overlap")
        if buffer.dtype != spec.dtype:
            failures.append("dtype")
        if buffer.device.type != "cpu":
            failures.append("device")
        if bool(buffer.is_pinned()) != self._pin_memory:
            failures.append("pin_memory")
        expected_stride = self._buffer_strides.get(id(spec.parameter))
        if expected_stride is None:
            failures.append("missing_stride_schema")
        elif tuple(buffer.stride()) != expected_stride:
            failures.append("stride")
        if failures:
            raise RuntimeError(
                "CPU gradient accumulation buffer schema mismatch for "
                f"{spec.name!r}: {sorted(failures)}."
            )

    def _synchronize_host_copies(
        self,
        specs: Iterable[_CPUGradientAccumulatorSpec],
    ) -> None:
        if not self._pin_memory:
            return
        devices = {spec.device for spec in specs}
        for device in sorted(devices, key=str):
            torch.cuda.current_stream(device).synchronize()

    @torch.no_grad()
    def spill(self) -> dict[str, int]:
        """Merge current grads in microbatch order, then clear them."""

        self._require_active()
        current_gradient_count = 0
        current_gradient_bytes = 0
        new_parameter_count = 0
        merged_parameter_count = 0
        try:
            cpu_merge_copies: list[
                tuple[
                    _CPUGradientAccumulatorSpec,
                    torch.Tensor,
                    torch.Tensor,
                    bool,
                ]
            ] = []
            for spec in self._specs:
                self._validate_parameter(spec)
                physical_id = id(spec.parameter)
                buffer = self._buffers.get(physical_id)
                if buffer is not None:
                    self._validate_buffer(spec, buffer)
                gradient = spec.parameter.grad
                if gradient is None:
                    continue
                self._validate_gradient(spec, gradient)
                gradient_bytes = self._storage_bytes(gradient)
                current_gradient_count += 1
                current_gradient_bytes += gradient_bytes

                if buffer is None:
                    buffer = self._empty_cpu_like(gradient)
                    self._buffers[physical_id] = buffer
                    self._seen_parameter_ids.add(physical_id)
                    self._buffer_strides[physical_id] = tuple(buffer.stride())
                    new_parameter_count += 1
                    if self._merge_device == "cuda":
                        buffer.copy_(gradient.detach(), non_blocking=False)
                    else:
                        buffer.copy_(
                            gradient.detach(),
                            non_blocking=self._pin_memory,
                        )
                        cpu_merge_copies.append((spec, buffer, buffer, True))
                elif self._merge_device == "cuda":
                    previous_device = torch.empty_strided(
                        tuple(buffer.shape),
                        tuple(buffer.stride()),
                        dtype=buffer.dtype,
                        device=spec.device,
                    )
                    previous_device.copy_(buffer, non_blocking=False)
                    previous_device.add_(gradient.detach())
                    buffer.copy_(previous_device, non_blocking=False)
                    del previous_device
                    merged_parameter_count += 1
                else:
                    staging = self._staging_buffers.get(physical_id)
                    if staging is None:
                        staging = self._empty_cpu_like(gradient)
                        self._staging_buffers[physical_id] = staging
                    else:
                        self._validate_buffer(spec, staging)
                    staging.copy_(
                        gradient.detach(),
                        non_blocking=self._pin_memory,
                    )
                    cpu_merge_copies.append((spec, buffer, staging, False))
                    merged_parameter_count += 1

                if self._merge_device == "cuda":
                    # Clear only after the synchronous host copy has succeeded.
                    spec.parameter.grad = None

            if self._merge_device == "cpu":
                self._synchronize_host_copies(
                    spec for spec, _buffer, _staging, _is_new in cpu_merge_copies
                )
                # Host copies are now complete, so device gradients can be
                # released before CPU accumulation begins.
                for spec, _buffer, _staging, _is_new in cpu_merge_copies:
                    spec.parameter.grad = None
                for _spec, buffer, staging, is_new in cpu_merge_copies:
                    if not is_new:
                        buffer.add_(staging)

            if not self._buffers:
                raise RuntimeError(
                    "CPU gradient accumulation spill observed no trainable gradients."
                )
            if set(self._buffers) != self._seen_parameter_ids:
                raise RuntimeError(
                    "CPU gradient accumulation buffer accounting is incomplete."
                )
            if set(self._buffer_strides) != self._seen_parameter_ids:
                raise RuntimeError(
                    "CPU gradient accumulation stride accounting is incomplete."
                )
            self._spill_count += 1
            self._merge_count += merged_parameter_count
            self._first_spill_count += new_parameter_count
            self._cumulative_current_gradient_bytes += current_gradient_bytes
            self._peak_cpu_accumulator_bytes = max(
                self._peak_cpu_accumulator_bytes,
                self._buffer_bytes(),
            )
            self._peak_cpu_staging_bytes = max(
                self._peak_cpu_staging_bytes,
                self._staging_bytes(),
            )
            self._peak_cpu_total_bytes = max(
                self._peak_cpu_total_bytes,
                self._live_cpu_buffer_bytes(),
            )
            return {
                "spill_count": self._spill_count,
                "current_gradient_count": current_gradient_count,
                "current_gradient_bytes": current_gradient_bytes,
                "new_parameter_count": new_parameter_count,
                "merged_parameter_count": merged_parameter_count,
                "accumulated_parameter_count": len(self._buffers),
                "cpu_accumulator_bytes": self._buffer_bytes(),
                "peak_cpu_accumulator_bytes": self._peak_cpu_accumulator_bytes,
                "cpu_staging_buffer_count": len(self._staging_buffers),
                "cpu_staging_bytes": self._staging_bytes(),
                "peak_cpu_staging_bytes": self._peak_cpu_staging_bytes,
                "live_cpu_buffer_count": self._live_cpu_buffer_count(),
                "live_cpu_buffer_bytes": self._live_cpu_buffer_bytes(),
                "peak_cpu_total_bytes": self._peak_cpu_total_bytes,
                "cumulative_merge_count": self._merge_count,
                "cumulative_first_spill_count": self._first_spill_count,
                "cumulative_current_gradient_bytes": (
                    self._cumulative_current_gradient_bytes
                ),
            }
        except Exception:
            self.discard()
            raise

    @torch.no_grad()
    def restore(self) -> dict[str, int]:
        """Restore the complete window to original devices for optimizer use."""

        self._require_active()
        try:
            buffer_ids = set(self._buffers)
            if buffer_ids != self._seen_parameter_ids:
                missing = sorted(self._seen_parameter_ids - buffer_ids)
                unexpected = sorted(buffer_ids - self._seen_parameter_ids)
                raise RuntimeError(
                    "CPU gradient accumulation restore buffer accounting mismatch: "
                    f"missing={missing}, unexpected={unexpected}."
                )
            if not buffer_ids:
                raise RuntimeError(
                    "CPU gradient accumulation restore has no spilled gradients."
                )
            if set(self._buffer_strides) != self._seen_parameter_ids:
                raise RuntimeError(
                    "CPU gradient accumulation restore stride accounting mismatch."
                )
            if not buffer_ids <= set(self._specs_by_id):
                raise RuntimeError(
                    "CPU gradient accumulation restore found an unknown parameter buffer."
                )
            staging_ids = set(self._staging_buffers)
            if not staging_ids <= buffer_ids:
                raise RuntimeError(
                    "CPU gradient accumulation restore found an unknown staging buffer."
                )

            for spec in self._specs:
                self._validate_parameter(spec)
                if spec.parameter.grad is not None:
                    raise RuntimeError(
                        "CPU gradient accumulation restore would duplicate an existing "
                        f"gradient for {spec.name!r}."
                    )
                buffer = self._buffers.get(id(spec.parameter))
                if buffer is not None:
                    self._validate_buffer(spec, buffer)
                staging = self._staging_buffers.get(id(spec.parameter))
                if staging is not None:
                    self._validate_buffer(spec, staging)

            cpu_accumulator_bytes = self._buffer_bytes()
            cpu_staging_bytes = self._staging_bytes()
            restored_parameter_count = 0
            pending_restores: list[
                tuple[_CPUGradientAccumulatorSpec, torch.Tensor]
            ] = []
            for spec in self._specs:
                buffer = self._buffers.get(id(spec.parameter))
                if buffer is None:
                    continue
                restored = torch.empty_strided(
                    tuple(buffer.shape),
                    tuple(buffer.stride()),
                    dtype=buffer.dtype,
                    device=spec.device,
                )
                restored.copy_(buffer, non_blocking=self._pin_memory)
                pending_restores.append((spec, restored))
                restored_parameter_count += 1

            self._synchronize_host_copies(spec for spec, _restored in pending_restores)
            for spec, restored in pending_restores:
                spec.parameter.grad = restored

            self._buffers.clear()
            self._staging_buffers.clear()
            self._seen_parameter_ids.clear()
            self._buffer_strides.clear()
            self._active = False
            return {
                "spill_count": self._spill_count,
                "merge_count": self._merge_count,
                "first_spill_count": self._first_spill_count,
                "cumulative_current_gradient_bytes": (
                    self._cumulative_current_gradient_bytes
                ),
                "restored_parameter_count": restored_parameter_count,
                "cpu_accumulator_bytes_before_restore": cpu_accumulator_bytes,
                "cpu_staging_bytes_before_restore": cpu_staging_bytes,
                "peak_cpu_accumulator_bytes": self._peak_cpu_accumulator_bytes,
                "peak_cpu_staging_bytes": self._peak_cpu_staging_bytes,
                "peak_cpu_total_bytes": self._peak_cpu_total_bytes,
                "live_cpu_buffer_count": 0,
                "live_cpu_buffer_bytes": 0,
            }
        except Exception:
            self.discard()
            raise

    @torch.no_grad()
    def discard(self) -> None:
        """Drop host state and all managed device gradients after failure."""

        for spec in self._specs:
            spec.parameter.grad = None
        self._buffers.clear()
        self._staging_buffers.clear()
        self._seen_parameter_ids.clear()
        self._buffer_strides.clear()
        self._active = False

    def statistics(self) -> dict[str, int]:
        return {
            "spill_count": self._spill_count,
            "merge_count": self._merge_count,
            "first_spill_count": self._first_spill_count,
            "cumulative_current_gradient_bytes": (
                self._cumulative_current_gradient_bytes
            ),
            "peak_cpu_accumulator_bytes": self._peak_cpu_accumulator_bytes,
            "peak_cpu_staging_bytes": self._peak_cpu_staging_bytes,
            "peak_cpu_total_bytes": self._peak_cpu_total_bytes,
            "live_cpu_buffer_count": self._live_cpu_buffer_count(),
            "live_cpu_buffer_bytes": self._live_cpu_buffer_bytes(),
        }


_GRADIENT_OFFLOAD_COUNTER_FIELDS = (
    "windows_started",
    "windows_restored",
    "windows_discarded",
    "single_microbatch_windows",
    "microbatch_spills",
    "parameter_first_spills",
    "parameter_merges",
    "cumulative_current_gradient_bytes",
    "peak_cpu_accumulator_bytes",
)


def _gradient_offload_counter_snapshot(
    receipt: Mapping[str, Any],
) -> dict[str, int]:
    result: dict[str, int] = {}
    for field_name in _GRADIENT_OFFLOAD_COUNTER_FIELDS:
        value = receipt.get(field_name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RuntimeError(
                "CPU gradient accumulation receipt counter is invalid: "
                f"{field_name}={value!r}."
            )
        result[field_name] = int(value)
    return result


def _gradient_offload_schema_identity(
    schema_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    records = [dict(record) for record in schema_records]
    names = [str(record.get("name", "")) for record in records]
    if not records or any(not name for name in names) or len(names) != len(set(names)):
        raise RuntimeError(
            "CPU gradient accumulation receipt requires a unique non-empty schema."
        )
    return {
        "trainable_parameter_count": len(records),
        "trainable_parameter_total_numel": sum(
            int(record["numel"]) for record in records
        ),
        "trainable_gradient_capacity_bytes": sum(
            int(record["logical_bytes"]) for record in records
        ),
        "trainable_parameter_schema_sha256": stable_hash(records),
    }


def _gradient_offload_receipt_hash(receipt: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(dict(receipt))
    payload["receipt_sha256"] = None
    return stable_hash(payload)


def _require_valid_gradient_offload_receipt_hash(
    receipt: Mapping[str, Any],
) -> str:
    stored_digest = receipt.get("receipt_sha256")
    if not isinstance(stored_digest, str) or not stored_digest:
        raise RuntimeError(
            "CPU gradient accumulation receipt has no self-hash."
        )
    actual_digest = _gradient_offload_receipt_hash(receipt)
    if actual_digest != stored_digest:
        raise RuntimeError(
            "CPU gradient accumulation receipt self-hash mismatch."
        )
    return stored_digest


def _current_gradient_offload_segment(
    receipt: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    segments = receipt.get("segments")
    if not isinstance(segments, list) or not segments:
        raise RuntimeError(
            "CPU gradient accumulation receipt has no execution segment."
        )
    segment = segments[-1]
    if not isinstance(segment, MutableMapping):
        raise RuntimeError(
            "CPU gradient accumulation receipt segment is malformed."
        )
    if int(segment.get("segment_index", -1)) != len(segments) - 1:
        raise RuntimeError(
            "CPU gradient accumulation receipt segment index is not contiguous."
        )
    return segment


def _gradient_offload_checkpoint_bundle_inventory(
    checkpoint: Path,
) -> tuple[dict[str, Any], bytes]:
    try:
        checkpoint_stat = checkpoint.lstat()
    except OSError as exc:
        raise RuntimeError(
            "CPU gradient accumulation checkpoint inventory root is unreadable."
        ) from exc
    if stat_module.S_ISLNK(checkpoint_stat.st_mode):
        raise RuntimeError(
            "CPU gradient accumulation checkpoint inventory rejects a symbolic-link "
            "root."
        )
    if not stat_module.S_ISDIR(checkpoint_stat.st_mode):
        raise RuntimeError(
            "CPU gradient accumulation checkpoint inventory root is not a directory."
        )
    if not _is_complete_checkpoint(checkpoint):
        raise RuntimeError(
            "CPU gradient accumulation checkpoint inventory requires a completed "
            "checkpoint."
        )

    records: list[dict[str, Any]] = []
    manifest_bytes: Optional[bytes] = None
    pending: list[tuple[Path, str]] = [(checkpoint, "")]
    while pending:
        directory, relative_directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name, reverse=True)
        except OSError as exc:
            raise RuntimeError(
                "CPU gradient accumulation checkpoint inventory directory is "
                "unreadable."
            ) from exc
        for entry in entries:
            relative_path = (
                f"{relative_directory}/{entry.name}"
                if relative_directory
                else entry.name
            )
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise RuntimeError(
                    "CPU gradient accumulation checkpoint inventory entry is "
                    f"unreadable: {relative_path!r}."
                ) from exc
            if stat_module.S_ISLNK(entry_stat.st_mode):
                raise RuntimeError(
                    "CPU gradient accumulation checkpoint inventory rejects symbolic "
                    f"links: {relative_path!r}."
                )
            if stat_module.S_ISDIR(entry_stat.st_mode):
                pending.append((Path(entry.path), relative_path))
                continue
            if not stat_module.S_ISREG(entry_stat.st_mode):
                raise RuntimeError(
                    "CPU gradient accumulation checkpoint inventory rejects special "
                    f"files: {relative_path!r}."
                )
            if int(entry_stat.st_nlink) != 1:
                raise RuntimeError(
                    "CPU gradient accumulation checkpoint inventory rejects hard-linked "
                    f"regular files: {relative_path!r}."
                )

            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            try:
                file_descriptor = os.open(entry.path, flags)
            except OSError as exc:
                raise RuntimeError(
                    "CPU gradient accumulation checkpoint inventory file is unreadable: "
                    f"{relative_path!r}."
                ) from exc
            digest = hashlib.sha256()
            captured_blocks: Optional[list[bytes]] = (
                [] if relative_path == "manifest.json" else None
            )
            try:
                opened_stat = os.fstat(file_descriptor)
                if (
                    not stat_module.S_ISREG(opened_stat.st_mode)
                    or int(opened_stat.st_nlink) != 1
                    or int(opened_stat.st_dev) != int(entry_stat.st_dev)
                    or int(opened_stat.st_ino) != int(entry_stat.st_ino)
                ):
                    raise RuntimeError(
                        "CPU gradient accumulation checkpoint inventory file changed "
                        f"during inspection: {relative_path!r}."
                    )
                while True:
                    block = os.read(file_descriptor, 1024 * 1024)
                    if not block:
                        break
                    digest.update(block)
                    if captured_blocks is not None:
                        captured_blocks.append(block)
                final_stat = os.fstat(file_descriptor)
                stable_fields = (
                    "st_dev",
                    "st_ino",
                    "st_mode",
                    "st_nlink",
                    "st_size",
                )
                if any(
                    getattr(opened_stat, field_name) != getattr(final_stat, field_name)
                    for field_name in stable_fields
                ) or any(
                    getattr(opened_stat, field_name, None)
                    != getattr(final_stat, field_name, None)
                    for field_name in ("st_mtime_ns", "st_ctime_ns")
                ):
                    raise RuntimeError(
                        "CPU gradient accumulation checkpoint inventory file changed "
                        f"while hashing: {relative_path!r}."
                    )
            finally:
                os.close(file_descriptor)
            if captured_blocks is not None:
                manifest_bytes = b"".join(captured_blocks)
            records.append(
                {
                    "path": relative_path,
                    "bytes": int(opened_stat.st_size),
                    "sha256": digest.hexdigest(),
                }
            )

    records.sort(key=lambda record: str(record["path"]))
    if manifest_bytes is None or sum(
        record["path"] == "manifest.json" for record in records
    ) != 1:
        raise RuntimeError(
            "CPU gradient accumulation checkpoint inventory has no unique manifest."
        )
    return (
        {
            "bundle_inventory_sha256": stable_hash(records),
            "file_count": len(records),
            "logical_bytes": sum(int(record["bytes"]) for record in records),
        },
        manifest_bytes,
    )


def _gradient_offload_checkpoint_descriptor(
    checkpoint: Path,
    *,
    output_dir: Path,
) -> dict[str, Any]:
    expanded_checkpoint = checkpoint.expanduser()
    inventory, manifest_bytes = (
        _gradient_offload_checkpoint_bundle_inventory(expanded_checkpoint)
    )
    resolved_checkpoint = expanded_checkpoint.resolve()
    resolved_output = output_dir.expanduser().resolve()
    try:
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "CPU gradient accumulation checkpoint has no readable manifest."
        ) from exc
    if not isinstance(manifest, Mapping):
        raise RuntimeError(
            "CPU gradient accumulation checkpoint manifest is not a JSON object."
        )
    manifest_identity = {
        "run_id": manifest.get("run_id"),
        "global_step": manifest.get("global_step"),
        "source_sha256": manifest.get("source_sha256"),
        "resume_signature": manifest.get("resume_signature"),
    }
    if (
        not isinstance(manifest_identity["run_id"], str)
        or not manifest_identity["run_id"]
        or isinstance(manifest_identity["global_step"], bool)
        or not isinstance(manifest_identity["global_step"], int)
        or not isinstance(manifest_identity["source_sha256"], str)
        or not manifest_identity["source_sha256"]
        or not isinstance(manifest_identity["resume_signature"], str)
        or not manifest_identity["resume_signature"]
    ):
        raise RuntimeError(
            "CPU gradient accumulation checkpoint manifest identity is incomplete."
        )
    if resolved_checkpoint.parent == resolved_output:
        return {
            "scope": "output_dir",
            "relative_path": resolved_checkpoint.name,
            "manifest_sha256": manifest_sha256,
            "manifest_identity": manifest_identity,
            **inventory,
        }
    return {
        "scope": "external",
        "basename": resolved_checkpoint.name,
        "manifest_sha256": manifest_sha256,
        "manifest_identity": manifest_identity,
        **inventory,
    }


def _gradient_accumulation_offload_profile(mode: str) -> dict[str, Any]:
    if mode == "cpu":
        return {
            "schema_version": 2,
            "mode": "cpu",
            "algorithm": "pageable_cpu_storage_cuda_native_order_add_v1",
            "execution_proof": (
                "This receipt proves that the single-process CUDA spill/merge/restore "
                "path executed with exact schema accounting and no live host buffers "
                "after each recorded restore."
            ),
            "numerical_proof": (
                "Additions run on each parameter's original CUDA device and dtype in "
                "microbatch order; model-level bitwise parity remains an external "
                "oracle comparison."
            ),
        }
    if mode == "cpu_accumulate":
        return {
            "schema_version": 3,
            "mode": "cpu_accumulate",
            "algorithm": "pinned_cpu_staging_cpu_dtype_ordered_add_v1",
            "execution_proof": (
                "This receipt proves that the single-process CUDA D2H/CPU-add/H2D "
                "path executed in microbatch order with exact schema accounting and "
                "no live host buffers after each recorded restore."
            ),
            "numerical_proof": (
                "Cross-microbatch additions run on CPU in each parameter's original "
                "dtype and order. Model-level bitwise parity with the CUDA-add spill "
                "reference remains an external oracle comparison."
            ),
        }
    raise RuntimeError(
        "Gradient accumulation offload receipt mode must be cpu or cpu_accumulate."
    )


def _new_gradient_accumulation_offload_receipt(
    schema_records: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    source_digest: str,
    resume_digest: str,
    initial_global_step: int,
    configured_accumulation_steps: int,
    offload_mode: str = "cpu",
    resume_checkpoint: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> dict[str, Any]:
    profile = _gradient_accumulation_offload_profile(offload_mode)
    schema_identity = _gradient_offload_schema_identity(schema_records)
    counters = {field_name: 0 for field_name in _GRADIENT_OFFLOAD_COUNTER_FIELDS}
    if resume_checkpoint is not None and output_dir is None:
        raise RuntimeError(
            "An external CPU gradient accumulation resume requires output_dir."
        )
    checkpoint = (
        _gradient_offload_checkpoint_descriptor(
            resume_checkpoint,
            output_dir=output_dir,
        )
        if resume_checkpoint is not None and output_dir is not None
        else None
    )
    receipt: dict[str, Any] = {
        "schema_version": profile["schema_version"],
        "mode": profile["mode"],
        "algorithm": profile["algorithm"],
        "claim_boundary": {
            "execution_proof": profile["execution_proof"],
            "numerical_proof": profile["numerical_proof"],
            "unsupported": (
                "DDP, non-CUDA execution, and schedule-extension resumes are rejected."
            ),
        },
        "run_id": str(run_id),
        "source_sha256": str(source_digest),
        "resume_signature": str(resume_digest),
        "configured_gradient_accumulation_steps": int(
            configured_accumulation_steps
        ),
        "initial_global_step": int(initial_global_step),
        "last_observed_global_step": int(initial_global_step),
        "last_restored_global_step": None,
        "final_global_step": None,
        **schema_identity,
        "trainable_parameter_schema_fields": [
            "name",
            "shape",
            "stride",
            "dtype",
            "device",
            "numel",
            "logical_bytes",
        ],
        **counters,
        "live_cpu_buffer_count": 0,
        "live_cpu_buffer_bytes": 0,
        "active_window": None,
        "continuations": [],
        "segments": [
            {
                "segment_index": 0,
                "previous_receipt_sha256": None,
                "resume_checkpoint": checkpoint,
                "initial_global_step": int(initial_global_step),
                "last_observed_global_step": int(initial_global_step),
                "final_global_step": None,
                "initial_cumulative_counters": copy.deepcopy(counters),
                "latest_cumulative_counters": copy.deepcopy(counters),
                "final_cumulative_counters": None,
                "status": "initialized",
            }
        ],
        "status": "initialized",
        "updated_at": None,
        "receipt_sha256": None,
    }
    return receipt


def _require_exact_gradient_offload_resume_signature(
    checkpoint: Path,
    config: ExperimentConfig,
) -> None:
    if config.train.allow_schedule_extension:
        raise RuntimeError(
            "CPU gradient accumulation offload does not support schedule extension "
            "during resume. Exact resume_signature equality is required."
        )
    manifest = _read_bundle_manifest(checkpoint)
    expected = manifest.get("resume_signature")
    actual = resume_signature(config)
    if not isinstance(expected, str) or not expected or expected != actual:
        raise RuntimeError(
            "CPU gradient accumulation offload requires an exact checkpoint "
            "resume_signature; schedule or optimizer semantics changed."
        )


def _continue_gradient_accumulation_offload_receipt(
    receipt_path: Path,
    schema_records: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    source_digest: str,
    resume_digest: str,
    resume_checkpoint: Path,
    resume_step: int,
    configured_accumulation_steps: int,
    offload_mode: str = "cpu",
) -> dict[str, Any]:
    profile = _gradient_accumulation_offload_profile(offload_mode)
    try:
        loaded = json.loads(receipt_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(
            "Cannot read the existing CPU gradient accumulation receipt."
        ) from exc
    if not isinstance(loaded, dict):
        raise RuntimeError(
            "Existing CPU gradient accumulation receipt is not a JSON object."
        )
    previous_receipt_sha256 = _require_valid_gradient_offload_receipt_hash(loaded)
    schema_identity = _gradient_offload_schema_identity(schema_records)
    checkpoint = resume_checkpoint.expanduser().resolve()
    receipt_output_dir = receipt_path.parent.expanduser().resolve()
    checkpoint_descriptor = _gradient_offload_checkpoint_descriptor(
        checkpoint,
        output_dir=receipt_output_dir,
    )
    manifest = _read_bundle_manifest(checkpoint)
    counters = _gradient_offload_counter_snapshot(loaded)
    failures: list[str] = []

    expected_scalars: dict[str, Any] = {
        "schema_version": profile["schema_version"],
        "mode": profile["mode"],
        "algorithm": profile["algorithm"],
        "run_id": str(run_id),
        "source_sha256": str(source_digest),
        "resume_signature": str(resume_digest),
        "configured_gradient_accumulation_steps": int(
            configured_accumulation_steps
        ),
        "status": "preempted",
        "last_observed_global_step": int(resume_step),
        "final_global_step": int(resume_step),
        "preempted_global_step": int(resume_step),
        "preempted_checkpoint": checkpoint_descriptor,
        "live_cpu_buffer_count": 0,
        "live_cpu_buffer_bytes": 0,
    }
    expected_scalars.update(schema_identity)
    for field_name, expected_value in expected_scalars.items():
        if loaded.get(field_name) != expected_value:
            failures.append(field_name)
    if loaded.get("active_window") is not None:
        failures.append("active_window")
    if checkpoint.parent != receipt_output_dir:
        failures.append("checkpoint_output_containment")
    initial_step = loaded.get("initial_global_step")
    if (
        isinstance(initial_step, bool)
        or not isinstance(initial_step, int)
        or initial_step > int(resume_step)
    ):
        failures.append("initial_global_step")

    manifest_expected = {
        "run_id": str(run_id),
        "global_step": int(resume_step),
        "source_sha256": str(source_digest),
        "resume_signature": str(resume_digest),
    }
    for field_name, expected_value in manifest_expected.items():
        if manifest.get(field_name) != expected_value:
            failures.append(f"checkpoint_manifest.{field_name}")

    segments = loaded.get("segments")
    continuations = loaded.get("continuations")
    if not isinstance(segments, list) or not segments:
        failures.append("segments")
    if not isinstance(continuations, list):
        failures.append("continuations")
    elif isinstance(segments, list) and len(continuations) != len(segments) - 1:
        failures.append("continuation_count")
    last_segment: Optional[Mapping[str, Any]] = None
    if isinstance(segments, list) and segments:
        if loaded.get("initial_global_step") != (
            segments[0].get("initial_global_step")
            if isinstance(segments[0], Mapping)
            else None
        ):
            failures.append("segments[0].initial_global_step")
        for segment_index, candidate_segment in enumerate(segments):
            if not isinstance(candidate_segment, Mapping):
                failures.append(f"segments[{segment_index}]")
                continue
            if candidate_segment.get("segment_index") != segment_index:
                failures.append(f"segments[{segment_index}].segment_index")
            if segment_index == 0:
                if candidate_segment.get("previous_receipt_sha256") is not None:
                    failures.append("segments[0].previous_receipt_sha256")
                continue
            if not isinstance(continuations, list) or len(continuations) < segment_index:
                failures.append(f"continuations[{segment_index - 1}]")
                continue
            continuation = continuations[segment_index - 1]
            previous_segment = segments[segment_index - 1]
            if not isinstance(continuation, Mapping) or not isinstance(
                previous_segment, Mapping
            ):
                failures.append(f"continuations[{segment_index - 1}]")
                continue
            expected_link = {
                "event": "resume_continuation",
                "previous_segment_index": segment_index - 1,
                "next_segment_index": segment_index,
                "checkpoint": candidate_segment.get("resume_checkpoint"),
                "global_step": candidate_segment.get("initial_global_step"),
                "previous_cumulative_counters": previous_segment.get(
                    "final_cumulative_counters"
                ),
            }
            for field_name, expected_value in expected_link.items():
                if continuation.get(field_name) != expected_value:
                    failures.append(
                        f"continuations[{segment_index - 1}].{field_name}"
                    )
            previous_link_hash = continuation.get("previous_receipt_sha256")
            if (
                not isinstance(previous_link_hash, str)
                or not previous_link_hash
                or candidate_segment.get("previous_receipt_sha256")
                != previous_link_hash
            ):
                failures.append(
                    f"segments[{segment_index}].previous_receipt_sha256"
                )
            if candidate_segment.get("initial_cumulative_counters") != (
                previous_segment.get("final_cumulative_counters")
            ):
                failures.append(
                    f"segments[{segment_index}].initial_cumulative_counters"
                )
            if previous_segment.get("status") != "preempted":
                failures.append(f"segments[{segment_index - 1}].status")
        candidate_segment = segments[-1]
        if isinstance(candidate_segment, Mapping):
            last_segment = candidate_segment
            expected_segment = {
                "segment_index": len(segments) - 1,
                "status": "preempted",
                "last_observed_global_step": int(resume_step),
                "final_global_step": int(resume_step),
                "terminal_checkpoint": checkpoint_descriptor,
                "latest_cumulative_counters": counters,
                "final_cumulative_counters": counters,
            }
            for field_name, expected_value in expected_segment.items():
                if last_segment.get(field_name) != expected_value:
                    failures.append(f"segments[-1].{field_name}")
        else:
            failures.append("segments[-1]")
    if failures:
        raise RuntimeError(
            "Existing CPU gradient accumulation receipt cannot continue because "
            f"bindings changed: {sorted(set(failures))}."
        )

    receipt = copy.deepcopy(loaded)
    receipt_continuations = receipt["continuations"]
    receipt_segments = receipt["segments"]
    next_segment_index = len(receipt_segments)
    continuation = {
        "event": "resume_continuation",
        "previous_segment_index": next_segment_index - 1,
        "next_segment_index": next_segment_index,
        "previous_receipt_sha256": previous_receipt_sha256,
        "checkpoint": copy.deepcopy(checkpoint_descriptor),
        "global_step": int(resume_step),
        "previous_cumulative_counters": copy.deepcopy(counters),
        "continued_at": time.time(),
    }
    receipt_continuations.append(continuation)
    receipt_segments.append(
        {
            "segment_index": next_segment_index,
            "previous_receipt_sha256": previous_receipt_sha256,
            "resume_checkpoint": copy.deepcopy(checkpoint_descriptor),
            "initial_global_step": int(resume_step),
            "last_observed_global_step": int(resume_step),
            "final_global_step": None,
            "initial_cumulative_counters": copy.deepcopy(counters),
            "latest_cumulative_counters": copy.deepcopy(counters),
            "final_cumulative_counters": None,
            "status": "initialized",
        }
    )
    receipt["status"] = "initialized"
    receipt["last_observed_global_step"] = int(resume_step)
    receipt["final_global_step"] = None
    receipt["active_window"] = None
    receipt["live_cpu_buffer_count"] = 0
    receipt["live_cpu_buffer_bytes"] = 0
    for stale_field in (
        "preempted_checkpoint",
        "preempted_global_step",
        "failed_active_window",
        "failed_window_statistics",
        "last_error_type",
        "last_error",
    ):
        receipt.pop(stale_field, None)
    receipt["updated_at"] = None
    receipt["receipt_sha256"] = None
    return receipt


def _start_gradient_accumulation_offload_window(
    receipt: MutableMapping[str, Any],
    *,
    global_step: int,
    batch_start: int,
    microbatch_count: int,
) -> None:
    if receipt.get("active_window") is not None:
        raise RuntimeError(
            "CPU gradient accumulation receipt already has an active window."
        )
    if microbatch_count < 1:
        raise RuntimeError(
            "CPU gradient accumulation receipt cannot start an empty window."
        )
    receipt["windows_started"] = int(receipt["windows_started"]) + 1
    receipt["last_observed_global_step"] = int(global_step)
    receipt["active_window"] = {
        "global_step": int(global_step),
        "batch_start": int(batch_start),
        "microbatch_count": int(microbatch_count),
        "spills_completed": 0,
        "last_microbatch_index": None,
        "latest_cpu_accumulator_bytes": 0,
    }
    receipt["status"] = "running"
    segment = _current_gradient_offload_segment(receipt)
    segment_initial_step = segment.get("initial_global_step")
    if (
        isinstance(segment_initial_step, bool)
        or not isinstance(segment_initial_step, int)
        or int(global_step) < segment_initial_step
    ):
        raise RuntimeError(
            "CPU gradient accumulation segment step moved backwards."
        )
    if segment.get("status") not in {"initialized", "running"}:
        raise RuntimeError(
            "CPU gradient accumulation cannot start a terminal segment."
        )
    segment["status"] = "running"
    segment["last_observed_global_step"] = int(global_step)


def _record_gradient_accumulation_offload_spill(
    receipt: MutableMapping[str, Any],
    *,
    global_step: int,
    microbatch_index: int,
    statistics: Mapping[str, int],
) -> None:
    active_window = receipt.get("active_window")
    if not isinstance(active_window, MutableMapping):
        raise RuntimeError(
            "CPU gradient accumulation receipt has no active spill window."
        )
    if int(active_window.get("global_step", -1)) != int(global_step):
        raise RuntimeError(
            "CPU gradient accumulation spill global-step binding changed."
        )
    expected_spill_count = int(microbatch_index) + 1
    if int(statistics["spill_count"]) != expected_spill_count:
        raise RuntimeError(
            "CPU gradient accumulation spill order is not contiguous."
        )
    if expected_spill_count > int(active_window["microbatch_count"]):
        raise RuntimeError(
            "CPU gradient accumulation recorded more spills than microbatches."
        )
    accumulator_count = int(statistics["accumulated_parameter_count"])
    accumulator_bytes = int(statistics["cpu_accumulator_bytes"])
    live_count = int(statistics.get("live_cpu_buffer_count", accumulator_count))
    live_bytes = int(statistics.get("live_cpu_buffer_bytes", accumulator_bytes))
    if accumulator_count < 1 or accumulator_bytes < 1:
        raise RuntimeError(
            "CPU gradient accumulation spill did not retain a host accumulator."
        )
    if live_count < accumulator_count or live_bytes < accumulator_bytes:
        raise RuntimeError(
            "CPU gradient accumulation live host accounting is incomplete."
        )
    active_window["spills_completed"] = expected_spill_count
    active_window["last_microbatch_index"] = int(microbatch_index)
    active_window["latest_cpu_accumulator_bytes"] = accumulator_bytes
    active_window["latest_cpu_staging_bytes"] = int(
        statistics.get("cpu_staging_bytes", 0)
    )
    active_window["latest_live_cpu_buffer_bytes"] = live_bytes
    active_window["cumulative_parameter_merges"] = int(
        statistics["cumulative_merge_count"]
    )
    active_window["cumulative_current_gradient_bytes"] = int(
        statistics["cumulative_current_gradient_bytes"]
    )
    receipt["last_observed_global_step"] = int(global_step)
    receipt["live_cpu_buffer_count"] = live_count
    receipt["live_cpu_buffer_bytes"] = live_bytes
    receipt["peak_cpu_accumulator_bytes"] = max(
        int(receipt["peak_cpu_accumulator_bytes"]),
        int(statistics["peak_cpu_accumulator_bytes"]),
    )


def _finish_gradient_accumulation_offload_window(
    receipt: MutableMapping[str, Any],
    *,
    global_step: int,
    statistics: Optional[Mapping[str, int]],
    restored: bool,
    single_microbatch: bool = False,
) -> None:
    active_window = receipt.get("active_window")
    if not isinstance(active_window, Mapping):
        raise RuntimeError(
            "CPU gradient accumulation receipt has no active window to finish."
        )
    if int(active_window.get("global_step", -1)) != int(global_step):
        raise RuntimeError(
            "CPU gradient accumulation receipt global-step binding changed."
        )
    if single_microbatch:
        if int(active_window.get("microbatch_count", -1)) != 1:
            raise RuntimeError(
                "CPU gradient accumulation single-microbatch accounting mismatch."
            )
        if statistics is not None or restored:
            raise RuntimeError(
                "A single-microbatch window cannot record spill statistics."
            )
        receipt["single_microbatch_windows"] = (
            int(receipt["single_microbatch_windows"]) + 1
        )
    else:
        if statistics is None:
            raise RuntimeError(
                "CPU gradient accumulation window is missing spill statistics."
            )
        live_count = int(statistics["live_cpu_buffer_count"])
        live_bytes = int(statistics["live_cpu_buffer_bytes"])
        if live_count != 0 or live_bytes != 0:
            raise RuntimeError(
                "CPU gradient accumulation window finished with live host buffers."
            )
        spill_count = int(statistics["spill_count"])
        if spill_count != int(active_window.get("microbatch_count", -1)):
            raise RuntimeError(
                "CPU gradient accumulation spill count does not match the window."
            )
        if spill_count != int(active_window.get("spills_completed", -1)):
            raise RuntimeError(
                "CPU gradient accumulation durable spill receipt is incomplete."
            )
        receipt["microbatch_spills"] = int(receipt["microbatch_spills"]) + spill_count
        receipt["parameter_first_spills"] = int(
            receipt["parameter_first_spills"]
        ) + int(statistics["first_spill_count"])
        receipt["parameter_merges"] = int(receipt["parameter_merges"]) + int(
            statistics["merge_count"]
        )
        receipt["cumulative_current_gradient_bytes"] = int(
            receipt["cumulative_current_gradient_bytes"]
        ) + int(statistics["cumulative_current_gradient_bytes"])
        receipt["peak_cpu_accumulator_bytes"] = max(
            int(receipt["peak_cpu_accumulator_bytes"]),
            int(statistics["peak_cpu_accumulator_bytes"]),
        )
        receipt["live_cpu_buffer_count"] = live_count
        receipt["live_cpu_buffer_bytes"] = live_bytes
        if restored:
            receipt["windows_restored"] = int(receipt["windows_restored"]) + 1
            receipt["last_restored_global_step"] = int(global_step)
        else:
            receipt["windows_discarded"] = int(receipt["windows_discarded"]) + 1
    receipt["last_observed_global_step"] = int(global_step)
    receipt["active_window"] = None
    segment = _current_gradient_offload_segment(receipt)
    segment["last_observed_global_step"] = int(global_step)
    segment["latest_cumulative_counters"] = (
        _gradient_offload_counter_snapshot(receipt)
    )


def _mark_gradient_accumulation_offload_terminal(
    receipt: MutableMapping[str, Any],
    *,
    status: str,
    global_step: int,
    checkpoint: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> None:
    if status not in {"preempted", "completed", "failed"}:
        raise RuntimeError(
            f"Unsupported CPU gradient accumulation terminal status: {status!r}."
        )
    if receipt.get("active_window") is not None:
        raise RuntimeError(
            "CPU gradient accumulation terminal receipt has an active window."
        )
    if int(receipt.get("live_cpu_buffer_count", -1)) != 0 or int(
        receipt.get("live_cpu_buffer_bytes", -1)
    ) != 0:
        raise RuntimeError(
            "CPU gradient accumulation terminal receipt has live host buffers."
        )
    checkpoint_descriptor: Optional[dict[str, Any]] = None
    if status == "preempted":
        if checkpoint is None or output_dir is None:
            raise RuntimeError(
                "A preempted CPU gradient accumulation receipt requires a checkpoint "
                "and output_dir."
            )
        checkpoint_descriptor = _gradient_offload_checkpoint_descriptor(
            checkpoint,
            output_dir=output_dir,
        )
        if checkpoint_descriptor.get("scope") != "output_dir":
            raise RuntimeError(
                "A preemption checkpoint must be contained directly in output_dir."
            )
    elif checkpoint is not None or output_dir is not None:
        raise RuntimeError(
            "Only a preempted CPU gradient accumulation segment binds a checkpoint."
        )

    counters = _gradient_offload_counter_snapshot(receipt)
    segment = _current_gradient_offload_segment(receipt)
    if segment.get("status") not in {"initialized", "running"}:
        raise RuntimeError(
            "CPU gradient accumulation segment is already terminal."
        )
    segment["status"] = status
    segment["last_observed_global_step"] = int(global_step)
    segment["final_global_step"] = int(global_step)
    segment["latest_cumulative_counters"] = copy.deepcopy(counters)
    segment["final_cumulative_counters"] = copy.deepcopy(counters)
    if checkpoint_descriptor is not None:
        segment["terminal_checkpoint"] = copy.deepcopy(checkpoint_descriptor)

    receipt["status"] = status
    receipt["last_observed_global_step"] = int(global_step)
    receipt["final_global_step"] = int(global_step)
    if status == "preempted":
        receipt["preempted_checkpoint"] = copy.deepcopy(checkpoint_descriptor)
        receipt["preempted_global_step"] = int(global_step)


def _write_gradient_accumulation_offload_receipt(
    path: Path,
    receipt: MutableMapping[str, Any],
) -> None:
    receipt["updated_at"] = time.time()
    receipt["receipt_sha256"] = None
    receipt["receipt_sha256"] = stable_hash(receipt)
    _atomic_write_json(path, dict(receipt))


def _parameter_identity_record(
    parameter: nn.Parameter,
    names: Sequence[str],
) -> dict[str, Any]:
    ordered_names = sorted(str(name) for name in names)
    return {
        "canonical_name": ordered_names[0],
        "aliases": ordered_names,
        "shape": list(parameter.shape),
        "numel": int(parameter.numel()),
        "dtype": str(parameter.dtype),
        "requires_grad": bool(parameter.requires_grad),
    }


def optimizer_coverage_report(
    model: nn.Module,
    optimizer: torch.optim.Optimizer,
    *,
    train_mode: str,
) -> dict[str, Any]:
    """Return a canonical, fail-closed optimizer membership receipt.

    Runtime equality uses Python object identity for physical parameters. Raw
    process-local IDs are never persisted; deterministic names, aliases,
    shapes, dtypes, counts, and hashes form the durable receipt instead.
    """
    model_records = _named_parameter_aliases(model)
    trainable_ids = {
        physical_id
        for physical_id, record in model_records.items()
        if bool(record["parameter"].requires_grad)
    }

    optimizer_occurrences: dict[int, list[dict[str, Any]]] = {}
    optimizer_parameters: dict[int, nn.Parameter] = {}
    for group_index, group in enumerate(optimizer.param_groups):
        family = str(group.get("family", f"group_{group_index}"))
        for parameter_index, parameter in enumerate(group["params"]):
            physical_id = id(parameter)
            optimizer_parameters[physical_id] = parameter
            optimizer_occurrences.setdefault(physical_id, []).append(
                {
                    "group_index": int(group_index),
                    "parameter_index": int(parameter_index),
                    "family": family,
                }
            )

    optimizer_ids = set(optimizer_occurrences)
    missing_ids = trainable_ids - optimizer_ids
    unexpected_ids = optimizer_ids - trainable_ids
    duplicate_ids = {
        physical_id
        for physical_id, occurrences in optimizer_occurrences.items()
        if len(occurrences) > 1
    }

    def descriptor(physical_id: int) -> dict[str, Any]:
        model_record = model_records.get(physical_id)
        if model_record is not None:
            return _parameter_identity_record(
                model_record["parameter"], sorted(model_record["names"])
            )
        parameter = optimizer_parameters[physical_id]
        first = optimizer_occurrences[physical_id][0]
        generated_name = (
            "<optimizer-only:"
            f"group-{first['group_index']}:parameter-{first['parameter_index']}>"
        )
        return _parameter_identity_record(parameter, [generated_name])

    expected_records = sorted(
        (descriptor(physical_id) for physical_id in trainable_ids),
        key=lambda item: item["canonical_name"],
    )
    optimizer_records = sorted(
        (descriptor(physical_id) for physical_id in optimizer_ids),
        key=lambda item: item["canonical_name"],
    )
    missing_records = sorted(
        (descriptor(physical_id) for physical_id in missing_ids),
        key=lambda item: item["canonical_name"],
    )
    unexpected_records = sorted(
        (descriptor(physical_id) for physical_id in unexpected_ids),
        key=lambda item: item["canonical_name"],
    )
    duplicate_records = []
    for physical_id in duplicate_ids:
        item = descriptor(physical_id)
        item["optimizer_occurrences"] = optimizer_occurrences[physical_id]
        duplicate_records.append(item)
    duplicate_records.sort(key=lambda item: item["canonical_name"])

    base_module = getattr(model, "base_model", None)
    base_records = (
        _named_parameter_aliases(base_module)
        if isinstance(base_module, nn.Module)
        else {}
    )
    frozen_base_records = sorted(
        (
            _parameter_identity_record(record["parameter"], sorted(record["names"]))
            for record in base_records.values()
            if not bool(record["parameter"].requires_grad)
        ),
        key=lambda item: item["canonical_name"],
    )
    base_all_trainable = not frozen_base_records
    base_optimizer_bindings: dict[str, dict[str, Any]] = {}
    for physical_id, base_record in sorted(
        base_records.items(),
        key=lambda item: sorted(str(name) for name in item[1]["names"])[0],
    ):
        parameter = base_record["parameter"]
        aliases = sorted(str(name) for name in base_record["names"])
        artifact_name = aliases[0]
        occurrences = optimizer_occurrences.get(physical_id, [])
        exact_occurrence = occurrences[0] if len(occurrences) == 1 else None
        base_optimizer_bindings[artifact_name] = {
            "artifact_name": artifact_name,
            "aliases": aliases,
            "shape": list(parameter.shape),
            "numel": int(parameter.numel()),
            "dtype": str(parameter.dtype),
            "requires_grad": bool(parameter.requires_grad),
            "optimizer_group_index": (
                exact_occurrence["group_index"]
                if exact_occurrence is not None
                else None
            ),
            "optimizer_parameter_index": (
                exact_occurrence["parameter_index"]
                if exact_occurrence is not None
                else None
            ),
            "optimizer_family": (
                exact_occurrence["family"]
                if exact_occurrence is not None
                else None
            ),
        }

    membership_exact = trainable_ids == optimizer_ids
    duplicate_membership_count = sum(
        max(0, len(occurrences) - 1)
        for occurrences in optimizer_occurrences.values()
    )
    duplicate_free = duplicate_membership_count == 0
    full_base_all_trainable = train_mode != "full" or base_all_trainable
    checks = {
        "unique_membership_exact": bool(membership_exact),
        "duplicate_membership_free": bool(duplicate_free),
        "full_mode_base_all_trainable": bool(full_base_all_trainable),
    }
    report: dict[str, Any] = {
        "format": "latent-workspace-ft-optimizer-coverage-v1",
        "identity_method_runtime": "python_object_identity",
        "identity_method_persistent": "canonical_name_alias_shape_dtype",
        "train_mode": str(train_mode),
        "checks": checks,
        "passed": all(checks.values()),
        "model_trainable_unique_physical_parameters": len(trainable_ids),
        "model_trainable_numel": sum(
            int(model_records[physical_id]["parameter"].numel())
            for physical_id in trainable_ids
        ),
        "optimizer_unique_physical_parameters": len(optimizer_ids),
        "optimizer_membership_occurrences": sum(
            len(occurrences) for occurrences in optimizer_occurrences.values()
        ),
        "optimizer_duplicate_memberships": int(duplicate_membership_count),
        "optimizer_unique_numel": sum(
            int(optimizer_parameters[physical_id].numel())
            for physical_id in optimizer_ids
        ),
        "base_unique_physical_parameters": len(base_records),
        "base_trainable_unique_physical_parameters": sum(
            bool(record["parameter"].requires_grad)
            for record in base_records.values()
        ),
        "base_all_trainable": bool(base_all_trainable),
        "base_optimizer_bindings": base_optimizer_bindings,
        "expected_membership_sha256": stable_hash(
            {"parameters": expected_records}
        ),
        "optimizer_membership_sha256": stable_hash(
            {"parameters": optimizer_records}
        ),
        "missing_parameters": missing_records,
        "unexpected_parameters": unexpected_records,
        "duplicate_parameters": duplicate_records,
        "frozen_base_parameters": frozen_base_records if train_mode == "full" else [],
    }
    report["report_sha256"] = stable_hash(report)
    return report


def require_exact_optimizer_coverage(report: Mapping[str, Any]) -> None:
    unsigned = dict(report)
    claimed_sha256 = str(unsigned.pop("report_sha256", ""))
    actual_sha256 = stable_hash(unsigned)
    if (
        report.get("format") == "latent-workspace-ft-optimizer-coverage-v1"
        and bool(report.get("passed", False))
        and claimed_sha256 == actual_sha256
    ):
        return
    raise RuntimeError(
        "Optimizer coverage is not exact: "
        f"missing={len(report.get('missing_parameters', []))}, "
        f"unexpected={len(report.get('unexpected_parameters', []))}, "
        f"duplicate_memberships={report.get('optimizer_duplicate_memberships')}, "
        f"full_mode_base_all_trainable="
        f"{report.get('checks', {}).get('full_mode_base_all_trainable')}, "
        f"sha256_valid={bool(claimed_sha256 and claimed_sha256 == actual_sha256)}."
    )


def _load_optimizer_coverage(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not load optimizer coverage from {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"Optimizer coverage at {path} is not a JSON object.")
    require_exact_optimizer_coverage(raw)
    return raw


def _require_resume_optimizer_mapping(
    checkpoint: Path,
    current_coverage: Mapping[str, Any],
) -> None:
    """Require canonical name/group/index identity before positional state load."""

    saved = _load_optimizer_coverage(checkpoint / "optimizer_coverage.json")
    require_exact_optimizer_coverage(current_coverage)
    if saved != dict(current_coverage):
        raise RuntimeError(
            "Checkpoint optimizer name/group/index mapping differs from the live model."
        )


def _optimizer_state_step(state: Mapping[str, Any]) -> Optional[int]:
    raw_step = state.get("step")
    if isinstance(raw_step, torch.Tensor):
        if raw_step.numel() != 1:
            return None
        raw_step = raw_step.detach().cpu().item()
    try:
        return int(raw_step)
    except (TypeError, ValueError, OverflowError):
        return None


def base_update_coverage_report(
    model: nn.Module,
    optimizer: torch.optim.Optimizer,
    *,
    train_mode: str,
    global_clip_grad_norm: torch.Tensor | float,
    optimizer_step_performed: bool,
    optimizer_step_skipped: bool,
) -> dict[str, Any]:
    """Prove first-step dynamic update eligibility for every base parameter.

    This receipt is intentionally evaluated after a successful optimizer step
    and before gradients are cleared. That boundary is the only point where
    clipped gradients and newly advanced Adafactor state coexist. Durable
    identity uses base-model artifact names; no process-local object IDs are
    persisted.
    """
    base_model = getattr(model, "base_model", None)
    if not isinstance(base_model, nn.Module):
        raise RuntimeError("Base update coverage requires model.base_model.")

    base_records = _named_parameter_aliases(base_model)
    optimizer_occurrences: dict[int, list[dict[str, Any]]] = {}
    for group_index, group in enumerate(optimizer.param_groups):
        family = str(group.get("family", f"group_{group_index}"))
        for parameter_index, parameter in enumerate(group["params"]):
            optimizer_occurrences.setdefault(id(parameter), []).append(
                {
                    "group_index": int(group_index),
                    "parameter_index": int(parameter_index),
                    "family": family,
                    "learning_rate": float(group.get("lr", 0.0)),
                    "weight_decay": float(group.get("weight_decay", 0.0)),
                }
            )

    step_performed = bool(optimizer_step_performed)
    step_skipped = bool(optimizer_step_skipped)
    optimizer_is_adafactor = (
        optimizer.__class__.__name__ == "Adafactor"
        and optimizer.__class__.__module__.startswith("transformers")
    )
    parameters: list[dict[str, Any]] = []
    for physical_id, base_record in sorted(
        base_records.items(),
        key=lambda item: sorted(str(name) for name in item[1]["names"])[0],
    ):
        parameter = base_record["parameter"]
        aliases = sorted(str(name) for name in base_record["names"])
        occurrences = optimizer_occurrences.get(physical_id, [])
        occurrence = occurrences[0] if len(occurrences) == 1 else None
        gradient = parameter.grad
        gradient_present = isinstance(gradient, torch.Tensor)
        gradient_shape_matches = bool(
            gradient_present and tuple(gradient.shape) == tuple(parameter.shape)
        )
        gradient_finite = bool(
            gradient_shape_matches
            and torch.isfinite(gradient.detach()).all().item()  # type: ignore[union-attr]
        )
        gradient_nonzero_elements = (
            int(torch.count_nonzero(gradient.detach()).item())  # type: ignore[union-attr]
            if gradient_shape_matches
            else 0
        )
        learning_rate = (
            float(occurrence["learning_rate"])
            if occurrence is not None
            else 0.0
        )
        optimizer_state = optimizer.state.get(parameter)
        state_step = (
            _optimizer_state_step(optimizer_state)
            if isinstance(optimizer_state, Mapping)
            else None
        )
        update_attempted = bool(
            step_performed
            and not step_skipped
            and occurrence is not None
            and gradient_present
            and learning_rate > 0.0
        )
        parameters.append(
            {
                "name": aliases[0],
                "aliases": aliases,
                "shape": list(parameter.shape),
                "dtype": str(parameter.dtype),
                "numel": int(parameter.numel()),
                "requires_grad": bool(parameter.requires_grad),
                "optimizer_group_index": (
                    occurrence["group_index"] if occurrence is not None else None
                ),
                "optimizer_parameter_index": (
                    occurrence["parameter_index"]
                    if occurrence is not None
                    else None
                ),
                "optimizer_family": (
                    occurrence["family"] if occurrence is not None else None
                ),
                "learning_rate": learning_rate,
                "weight_decay": (
                    float(occurrence["weight_decay"])
                    if occurrence is not None
                    else 0.0
                ),
                "gradient_present": gradient_present,
                "gradient_shape_matches": gradient_shape_matches,
                "gradient_finite": gradient_finite,
                "gradient_nonzero": gradient_nonzero_elements > 0,
                "gradient_nonzero_elements": gradient_nonzero_elements,
                "state_step": state_step,
                "update_attempted": update_attempted,
            }
        )

    try:
        raw_clip_grad_norm = float(
            global_clip_grad_norm.detach().float().cpu().item()
            if isinstance(global_clip_grad_norm, torch.Tensor)
            else global_clip_grad_norm
        )
    except (TypeError, ValueError, OverflowError):
        raw_clip_grad_norm = float("nan")
    clip_grad_norm_finite = math.isfinite(raw_clip_grad_norm)
    clip_grad_norm: Optional[float] = (
        raw_clip_grad_norm if clip_grad_norm_finite else None
    )
    exact_membership = all(
        parameter["optimizer_group_index"] is not None
        and parameter["optimizer_parameter_index"] is not None
        and parameter["optimizer_family"] == "base"
        for parameter in parameters
    ) and len(base_records) == sum(
        len(occurrences)
        for physical_id, occurrences in optimizer_occurrences.items()
        if physical_id in base_records
    )
    checks = {
        "all_base_parameters_trainable": bool(
            parameters
            and all(parameter["requires_grad"] for parameter in parameters)
        ),
        "optimizer_membership_exact": bool(exact_membership),
        "all_gradients_present": bool(
            parameters
            and all(
                parameter["gradient_present"]
                and parameter["gradient_shape_matches"]
                for parameter in parameters
            )
        ),
        "all_gradients_finite": bool(
            parameters
            and clip_grad_norm_finite
            and all(parameter["gradient_finite"] for parameter in parameters)
        ),
        "all_gradients_nonzero": bool(
            parameters
            and all(parameter["gradient_nonzero"] for parameter in parameters)
        ),
        "positive_base_learning_rate": bool(
            parameters
            and all(parameter["learning_rate"] > 0.0 for parameter in parameters)
        ),
        "optimizer_step_performed": step_performed,
        "optimizer_step_not_skipped": not step_skipped,
        "all_optimizer_states_advanced": bool(
            parameters
            and optimizer_is_adafactor
            and all(
                parameter["state_step"] is not None
                and int(parameter["state_step"]) >= 1
                for parameter in parameters
            )
        ),
    }
    report: dict[str, Any] = {
        "format": "latent-workspace-ft-base-update-coverage-v1",
        "train_mode": str(train_mode),
        "optimizer_class": (
            f"{optimizer.__class__.__module__}.{optimizer.__class__.__name__}"
        ),
        "global_clip_grad_norm": clip_grad_norm,
        "global_clip_grad_norm_finite": clip_grad_norm_finite,
        "base_parameter_count": len(parameters),
        "base_parameter_numel": sum(
            int(parameter["numel"]) for parameter in parameters
        ),
        "checks": checks,
        "parameters": parameters,
    }
    report["passed"] = bool(train_mode == "full" and all(checks.values()))
    report["report_sha256"] = stable_hash(report)
    return report


def require_base_update_coverage(report: Mapping[str, Any]) -> None:
    unsigned = dict(report)
    claimed_sha256 = str(unsigned.pop("report_sha256", ""))
    actual_sha256 = stable_hash(unsigned)
    if (
        report.get("format") == "latent-workspace-ft-base-update-coverage-v1"
        and bool(report.get("passed", False))
        and claimed_sha256 == actual_sha256
    ):
        return
    failed_checks = sorted(
        str(name)
        for name, passed in dict(report.get("checks", {})).items()
        if not bool(passed)
    )
    raise RuntimeError(
        "Base update coverage failed: "
        f"failed_checks={failed_checks}, "
        f"sha256_valid={bool(claimed_sha256 and claimed_sha256 == actual_sha256)}."
    )


def _load_base_update_coverage(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Could not load base update coverage from {path}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"Base update coverage at {path} is not a JSON object.")
    require_base_update_coverage(raw)
    return raw


def _first_nonzero_gradient_index(
    gradient: torch.Tensor,
    *,
    chunk_size: int = 4096,
) -> Optional[int]:
    flat = gradient.detach().reshape(-1)
    for start in range(0, flat.numel(), chunk_size):
        chunk = flat[start : start + chunk_size]
        valid = torch.isfinite(chunk) & chunk.ne(0)
        if bool(valid.any().item()):
            local = int(valid.to(torch.uint8).argmax().item())
            return start + local
    return None


def _base_gradient_sentinel(
    model: nn.Module,
    *,
    preferred_output_rows: Sequence[int] = (),
) -> tuple[nn.Parameter, dict[str, Any], torch.Tensor]:
    """Select a deterministic, bounded-memory nonzero-gradient base sentinel."""
    base_model = getattr(model, "base_model", None)
    if not isinstance(base_model, nn.Module):
        raise RuntimeError("Base-gradient sentinel requires model.base_model.")
    base_records = _named_parameter_aliases(base_model, prefix="base_model.")

    candidates: list[tuple[str, nn.Parameter, str]] = []
    getter = getattr(base_model, "get_output_embeddings", None)
    output_module = getter() if callable(getter) else None
    output_weight = getattr(output_module, "weight", None)
    if isinstance(output_weight, nn.Parameter):
        record = base_records.get(id(output_weight))
        output_name = (
            sorted(record["names"])[0]
            if record is not None
            else "base_model.<output_embeddings>.weight"
        )
        candidates.append((output_name, output_weight, "output_embedding"))

    remaining = sorted(
        (
            (sorted(record["names"])[0], record["parameter"], "base_parameter")
            for record in base_records.values()
            if id(record["parameter"]) != id(output_weight)
        ),
        key=lambda item: (int(item[1].numel()), item[0]),
    )
    candidates.extend(remaining)

    selected: Optional[tuple[str, nn.Parameter, str, int]] = None
    for name, parameter, source in candidates:
        gradient = parameter.grad
        if (
            gradient is None
            or not parameter.requires_grad
            or gradient.numel() == 0
        ):
            continue
        if source == "output_embedding" and gradient.ndim == 2:
            width = int(gradient.shape[1])
            for row in sorted(set(int(value) for value in preferred_output_rows)):
                if not 0 <= row < int(gradient.shape[0]):
                    continue
                row_gradient = gradient[row].detach()
                valid = torch.isfinite(row_gradient) & row_gradient.ne(0)
                if not bool(valid.any().item()):
                    continue
                magnitudes = row_gradient.detach().float().abs()
                magnitudes = magnitudes.masked_fill(~valid, -1.0)
                column = int(magnitudes.argmax().item())
                selected = (
                    name,
                    parameter,
                    "supervised_output_row_max_abs_gradient",
                    row * width + column,
                )
                break
        if selected is None:
            flat_index = _first_nonzero_gradient_index(gradient)
            if flat_index is not None:
                selected = (name, parameter, f"{source}_first_nonzero_gradient", flat_index)
        if selected is not None:
            break

    if selected is None:
        raise RuntimeError(
            "No deterministic nonzero-gradient base parameter was available "
            "for the optimizer-step sentinel."
        )

    name, parameter, selection, flat_index = selected
    flat_parameter = parameter.detach().reshape(-1)
    flat_gradient = parameter.grad.detach().reshape(-1)  # type: ignore[union-attr]
    sample_start = max(0, flat_index - 64)
    sample_stop = min(flat_parameter.numel(), sample_start + 128)
    before_sample = (
        flat_parameter[sample_start:sample_stop].float().cpu().clone()
    )
    sentinel = {
        "parameter_name": name,
        "selection": selection,
        "parameter_shape": list(parameter.shape),
        "parameter_dtype": str(parameter.dtype),
        "flat_index": int(flat_index),
        "sample_start": int(sample_start),
        "sample_length": int(sample_stop - sample_start),
        "gradient_value": float(flat_gradient[flat_index].float().item()),
        "gradient_nonzero": bool(flat_gradient[flat_index].ne(0).item()),
        "before_value": float(flat_parameter[flat_index].float().item()),
    }
    return parameter, sentinel, before_sample


def optimizer_step_with_base_sentinel(
    model: nn.Module,
    optimizer: torch.optim.Optimizer,
    *,
    scaler: Optional[Any] = None,
    preferred_output_rows: Sequence[int] = (),
) -> dict[str, Any]:
    """Perform one optimizer step and report a deterministic base delta."""
    parameter, report, before_sample = _base_gradient_sentinel(
        model,
        preferred_output_rows=preferred_output_rows,
    )
    before_scale = (
        float(scaler.get_scale())
        if scaler is not None and hasattr(scaler, "get_scale")
        else 1.0
    )
    if scaler is None:
        optimizer.step()
    else:
        scaler.step(optimizer)
        scaler.update()
    after_scale = (
        float(scaler.get_scale())
        if scaler is not None and hasattr(scaler, "get_scale")
        else before_scale
    )

    flat_parameter = parameter.detach().reshape(-1)
    sample_start = int(report["sample_start"])
    sample_stop = sample_start + int(report["sample_length"])
    after_sample = flat_parameter[sample_start:sample_stop].float().cpu().clone()
    delta = after_sample - before_sample
    flat_index = int(report["flat_index"])
    after_value = float(flat_parameter[flat_index].float().item())
    report.update(
        {
            "format": "latent-workspace-ft-base-step-sentinel-v1",
            "after_value": after_value,
            "delta": after_value - float(report["before_value"]),
            "sample_max_abs_delta": float(delta.abs().max().item()),
            "sample_l2_delta": float(delta.norm().item()),
            "sample_nonzero_delta_elements": int(delta.ne(0).sum().item()),
            "updated": bool(delta.ne(0).any().item()),
            "grad_scale_before": before_scale,
            "grad_scale_after": after_scale,
            "optimizer_step_skipped": bool(after_scale < before_scale),
        }
    )
    report["report_sha256"] = stable_hash(report)
    return report


def build_scheduler(
    optimizer: torch.optim.Optimizer,
    total_steps: int,
    warmup_ratio: float,
) -> torch.optim.lr_scheduler.LambdaLR:
    warmup_steps = int(round(total_steps * max(0.0, warmup_ratio)))

    def schedule(step: int) -> float:
        if warmup_steps > 0 and step < warmup_steps:
            return float(step + 1) / float(warmup_steps)
        remaining = max(1, total_steps - warmup_steps)
        progress = min(1.0, max(0.0, (step - warmup_steps) / remaining))
        return 0.5 * (1.0 + math.cos(math.pi * progress))

    return torch.optim.lr_scheduler.LambdaLR(optimizer, schedule)


@dataclass(frozen=True)
class InductionStatus:
    weight: float
    phase: str
    active: bool
    start_step: int
    end_step: int
    progress: float


def _induction_bounds(
    config: InductionConfig,
    total_steps: int,
) -> tuple[int, int]:
    total = max(1, int(total_steps))
    schedule = config.schedule
    start_fraction = float(config.start_fraction)
    end_fraction = float(config.end_fraction)
    if schedule == "constant":
        start_fraction, end_fraction = 0.0, 1.0
    elif schedule == "early_pulse":
        start_fraction = 0.0
    elif schedule == "late_pulse":
        end_fraction = 1.0

    start = (
        int(config.start_step)
        if config.start_step >= 0
        else int(math.floor(start_fraction * total))
    )
    end = (
        int(config.end_step)
        if config.end_step >= 0
        else int(math.ceil(end_fraction * total))
    )
    start = min(max(start, 0), total)
    end = min(max(end, start), total)
    if config.enabled and end == start and start < total:
        end = start + 1
    return start, end


def induction_status(
    workspace: WorkspaceConfig,
    induction: Optional[InductionConfig],
    global_step: int,
    total_steps: int,
) -> InductionStatus:
    target = float(workspace.loss_weight)
    if induction is None or not induction.enabled:
        warmup = int(workspace.loss_warmup_steps)
        factor = (
            1.0
            if warmup <= 0
            else min(1.0, float(global_step + 1) / float(warmup))
        )
        return InductionStatus(
            weight=target * factor,
            phase="constant",
            active=target > 0.0,
            start_step=0,
            end_step=max(1, int(total_steps)),
            progress=min(1.0, max(0.0, float(global_step + 1) / max(total_steps, 1))),
        )

    start, end = _induction_bounds(induction, total_steps)
    step = int(global_step)
    if step < start:
        return InductionStatus(0.0, "pre_induction", False, start, end, 0.0)
    if step >= end:
        phase = "washout" if end < max(1, int(total_steps)) else "post_induction"
        return InductionStatus(0.0, phase, False, start, end, 1.0)

    span = max(1, end - start)
    local = step - start
    factor = 1.0
    ramp_up = max(int(induction.ramp_up_steps), int(workspace.loss_warmup_steps))
    if ramp_up > 0:
        factor = min(factor, float(local + 1) / float(ramp_up))
    ramp_down = int(induction.ramp_down_steps)
    if ramp_down > 0:
        remaining = end - step
        factor = min(factor, float(remaining) / float(ramp_down))
    factor = min(1.0, max(0.0, factor))
    return InductionStatus(
        weight=target * factor,
        phase="induction",
        active=target > 0.0 and factor > 0.0,
        start_step=start,
        end_step=end,
        progress=min(1.0, max(0.0, float(local + 1) / float(span))),
    )


def workspace_weight(
    config: WorkspaceConfig,
    global_step: int,
    total_steps: int = 1,
    induction: Optional[InductionConfig] = None,
) -> float:
    return induction_status(config, induction, global_step, total_steps).weight


def _parameter_families(
    model: LatentWorkspaceCausalLM,
) -> tuple[list[nn.Parameter], list[nn.Parameter]]:
    base: list[nn.Parameter] = []
    workspace: list[nn.Parameter] = []
    seen: set[int] = set()
    for name, parameter in model.named_parameters():
        if not parameter.requires_grad or parameter.grad is None or id(parameter) in seen:
            continue
        seen.add(id(parameter))
        (base if name.startswith("base_model.") else workspace).append(parameter)
    return base, workspace


def _clip_one_family(
    parameters: Sequence[nn.Parameter],
    maximum: float,
) -> tuple[torch.Tensor, float]:
    if not parameters:
        return torch.zeros((), dtype=torch.float32), 1.0
    norm = torch.nn.utils.clip_grad_norm_(parameters, float(maximum))
    value = float(norm.detach().float().item())
    coefficient = min(1.0, float(maximum) / max(value, 1e-12))
    return norm, coefficient


def clip_gradients(
    model: LatentWorkspaceCausalLM,
    train_config: TrainConfig,
    attribution: AttributionConfig,
) -> dict[str, Any]:
    base_parameters, workspace_parameters = _parameter_families(model)
    if attribution.clip_mode == "global":
        all_parameters = [*base_parameters, *workspace_parameters]
        norm, coefficient = _clip_one_family(all_parameters, train_config.max_grad_norm)
        return {
            "grad_norm_tensor": norm,
            "grad_norm": float(norm.detach().float().item()),
            "base_grad_norm": float("nan"),
            "workspace_grad_norm": float("nan"),
            "base_clip_coefficient": coefficient,
            "workspace_clip_coefficient": coefficient,
        }

    base_norm, base_coefficient = _clip_one_family(
        base_parameters, attribution.base_max_grad_norm
    )
    workspace_norm, workspace_coefficient = _clip_one_family(
        workspace_parameters, attribution.workspace_max_grad_norm
    )
    combined = torch.sqrt(base_norm.float().square() + workspace_norm.float().square())
    return {
        "grad_norm_tensor": combined,
        "grad_norm": float(combined.detach().item()),
        "base_grad_norm": float(base_norm.detach().float().item()),
        "workspace_grad_norm": float(workspace_norm.detach().float().item()),
        "base_clip_coefficient": base_coefficient,
        "workspace_clip_coefficient": workspace_coefficient,
    }


def move_batch_to_device(
    batch: Mapping[str, torch.Tensor],
    device: torch.device,
) -> dict[str, torch.Tensor]:
    result: dict[str, torch.Tensor] = {}
    for key, value in batch.items():
        if isinstance(value, torch.Tensor):
            result[key] = value.to(device=device, non_blocking=device.type == "cuda")
    return result


def bridge_batch_kwargs(
    batch: Mapping[str, torch.Tensor],
) -> dict[str, torch.Tensor]:
    keys = (
        "bridge_context_input_ids",
        "bridge_context_attention_mask",
        "bridge_input_ids",
        "bridge_attention_mask",
        "bridge_labels",
        "bridge_prompt_mask",
        "bridge_query_mask",
    )
    return {key: batch[key] for key in keys if key in batch}


def functional_batch_kwargs(
    batch: Mapping[str, torch.Tensor],
) -> dict[str, torch.Tensor]:
    keys = (
        "functional_context_input_ids",
        "functional_context_attention_mask",
        "functional_query_input_ids",
        "functional_query_attention_mask",
        "functional_query_labels",
        "functional_inline_input_ids",
        "functional_inline_attention_mask",
        "functional_inline_labels",
        "functional_query_choice_ids",
        "functional_inline_choice_ids",
        "functional_answer_classes",
        "functional_query_valid_mask",
        "functional_affected_mask",
        "functional_heldout_mask",
        "functional_hop_distances",
        "functional_pair_ids",
    )
    return {key: batch[key] for key in keys if key in batch}


def batch_supervised_token_count(batch: Mapping[str, torch.Tensor]) -> int:
    labels = batch.get("functional_query_labels")
    valid = batch.get("functional_query_valid_mask")
    if isinstance(labels, torch.Tensor) and isinstance(valid, torch.Tensor):
        expanded = valid[:, None, :, None].expand_as(labels)
        return int((labels[:, :, :, 1:].ne(-100) & expanded[:, :, :, 1:]).sum().item())
    ordinary = batch["labels"]
    return int(ordinary[:, 1:].ne(-100).sum().item())


def batch_counterfactual_token_count(batch: Mapping[str, torch.Tensor]) -> int:
    labels = batch.get("functional_query_labels")
    valid = batch.get("functional_query_valid_mask")
    affected = batch.get("functional_affected_mask")
    if not all(isinstance(value, torch.Tensor) for value in (labels, valid, affected)):
        return 0
    assert isinstance(labels, torch.Tensor)
    assert isinstance(valid, torch.Tensor)
    assert isinstance(affected, torch.Tensor)
    selected = (valid & affected)[:, None, :, None].expand_as(labels)
    return int((labels[:, :, :, 1:].ne(-100) & selected[:, :, :, 1:]).sum().item())


def batch_stability_item_count(batch: Mapping[str, torch.Tensor]) -> int:
    valid = batch.get("functional_query_valid_mask")
    affected = batch.get("functional_affected_mask")
    if not isinstance(valid, torch.Tensor) or not isinstance(affected, torch.Tensor):
        return 0
    return int(((valid & ~affected).sum() * 2).item())


def _scalar_workspace_metrics(output: Mapping[str, Any]) -> dict[str, float]:
    stats = output["workspace_stats"]
    task_loss = output.get("task_loss")
    result = {
        "task_loss": (
            float(task_loss.detach().float().item())
            if isinstance(task_loss, torch.Tensor)
            else float("nan")
        ),
        "workspace_loss": float(output["workspace_loss"].detach().float().item()),
        "gate_mean": float(output["gate_mean"].float().item()),
        "gate_max": float(output["gate_max"].float().item()),
        "workspace_tokens": float(output["workspace_tokens"].item()),
        "supervised_tokens": float(output["supervised_tokens"].item()),
        "delta_logit_norm": float(output["delta_logit_norm"].detach().float().item()),
        "gated_delta_logit_norm": float(
            output["gated_delta_logit_norm"].detach().float().item()
        ),
        "bridge_state_norm": float(
            output.get("bridge_state_norm", output["workspace_loss"] * 0.0)
            .detach()
            .float()
            .item()
        ),
        "memory_changed_fraction": float(
            output.get("memory_changed_fraction", output["workspace_loss"] * 0.0)
            .detach()
            .float()
            .item()
        ),
        "memory_assignment_changed_fraction": float(
            output.get(
                "memory_assignment_changed_fraction",
                output["workspace_loss"] * 0.0,
            ).detach().float().item()
        ),
        "memory_tensor_changed_fraction": float(
            output.get(
                "memory_tensor_changed_fraction",
                output["workspace_loss"] * 0.0,
            ).detach().float().item()
        ),
        "memory_effective_changed_fraction": float(
            output.get(
                "memory_effective_changed_fraction",
                output["workspace_loss"] * 0.0,
            ).detach().float().item()
        ),
        "memory_content_delta_l2": float(
            output.get(
                "memory_content_delta_l2", output["workspace_loss"] * 0.0
            ).detach().float().item()
        ),
        "memory_effective_delta_l2": float(
            output.get(
                "memory_effective_delta_l2", output["workspace_loss"] * 0.0
            ).detach().float().item()
        ),
        "memory_source_norm": float(
            output.get("memory_source_norm", output["workspace_loss"] * 0.0)
            .detach()
            .float()
            .item()
        ),
        "memory_intervened_norm": float(
            output.get(
                "memory_intervened_norm", output["workspace_loss"] * 0.0
            )
            .detach()
            .float()
            .item()
        ),
        "memory_raw_cosine": float(
            output.get(
                "memory_raw_cosine", output["workspace_loss"] * 0.0
            )
            .detach()
            .float()
            .item()
        ),
        "memory_layernorm_cosine": float(
            output.get(
                "memory_layernorm_cosine", output["workspace_loss"] * 0.0
            )
            .detach()
            .float()
            .item()
        ),
        "memory_carrier_presence_fraction": float(
            output.get(
                "memory_carrier_presence_fraction",
                output["workspace_loss"] * 0.0,
            )
            .detach()
            .float()
            .item()
        ),
        "hard_bypass_fraction": float(
            output.get("hard_bypass_fraction", output["workspace_loss"] * 0.0)
            .detach()
            .float()
            .item()
        ),
    }
    counterfactual_nll_sum = output.get("counterfactual_nll_sum")
    counterfactual_tokens = output.get("counterfactual_tokens")
    if isinstance(counterfactual_nll_sum, torch.Tensor) and isinstance(
        counterfactual_tokens, torch.Tensor
    ):
        count = max(float(counterfactual_tokens.item()), 1.0)
        result["counterfactual_loss"] = float(
            counterfactual_nll_sum.detach().float().item()
        ) / count
        result["counterfactual_tokens"] = float(counterfactual_tokens.item())
    stability_kl_sum = output.get("stability_kl_sum")
    stability_items = output.get("stability_items")
    if isinstance(stability_kl_sum, torch.Tensor) and isinstance(
        stability_items, torch.Tensor
    ):
        count = max(float(stability_items.item()), 1.0)
        result["stability_loss"] = float(
            stability_kl_sum.detach().float().item()
        ) / count
        result["stability_items"] = float(stability_items.item())
    for key in (
        "functional_full_vocab_loss",
        "functional_choice_loss",
        "functional_query_accuracy",
        "functional_all_query_world_accuracy",
        "functional_all_query_world_examples",
        "functional_choice_margin",
        "functional_yes_minus_no_gap",
        "functional_prediction_entropy_nats",
        "functional_distinct_predicted_classes",
        "functional_choice_count",
        "functional_affected_accuracy",
        "functional_affected_examples",
        "functional_unaffected_accuracy",
        "functional_unaffected_examples",
        "functional_heldout_query_accuracy",
        "functional_heldout_query_examples",
        "functional_donor_accuracy",
        "functional_affected_donor_accuracy",
        "functional_unaffected_original_stability",
        "functional_query_count",
    ):
        value = output.get(key)
        if isinstance(value, torch.Tensor) and value.numel() == 1:
            result[key] = float(value.detach().float().item())
    for key, value in output.items():
        if not key.startswith("functional_label_"):
            continue
        if isinstance(value, torch.Tensor) and value.numel() == 1:
            result[key] = float(value.detach().float().item())
    for hop in range(1, 9):
        for suffix in ("accuracy", "examples"):
            key = f"functional_hop_{hop}_{suffix}"
            value = output.get(key)
            if isinstance(value, torch.Tensor) and value.numel() == 1:
                result[key] = float(value.detach().float().item())

    base_nll_sum = output.get("base_nll_sum")
    task_nll_sum = output.get("task_nll_sum")
    if isinstance(base_nll_sum, torch.Tensor) and isinstance(task_nll_sum, torch.Tensor):
        tokens = max(float(output["supervised_tokens"].item()), 1.0)
        result["base_task_loss"] = float(base_nll_sum.detach().float().item()) / tokens
        result["task_gain_nats"] = (
            float(base_nll_sum.detach().float().item())
            - float(task_nll_sum.detach().float().item())
        ) / tokens
    for key in (
        "loss_var",
        "loss_cov",
        "loss_info",
        "loss_contrast",
        "loss_relation",
        "loss_temporal",
        "loss_worst",
        "loss_rank",
        "retention_cosine",
        "relative_effective_rank",
        "mean_temporal_drift",
        "state_anchor_cosine",
        "final_state_anchor_cosine",
        "mean_departure_l2",
        "final_departure_l2",
        "mean_update_l2",
        "path_length",
        "net_displacement",
        "tortuosity",
        "contrastive_valid_fraction",
        "contrastive_negative_pairs",
    ):
        value = stats.get(key)
        if isinstance(value, torch.Tensor) and value.numel() == 1:
            result[key] = float(value.float().item())
    return result


def _release_unconsumed_training_logits(output: MutableMapping[str, Any]) -> int:
    """Drop dense logits once scalar objectives have captured their graph.

    Functional training builds its losses from a small set of indexed answer
    rows. The corresponding backward node retains the indices and source
    shape, not the dense logits storage itself. Keeping the public ``logits``
    entry alive until after backward therefore costs memory without changing
    the objective or its gradients.

    Returns the number of tensor bytes whose final Python reference may have
    been released. The return value is diagnostic only and is deliberately
    excluded from the training state and metric stream.
    """

    logits = output.pop("logits", None)
    if not isinstance(logits, torch.Tensor):
        return 0
    return int(logits.numel() * logits.element_size())


class MetricAccumulator:
    def __init__(self) -> None:
        self.sums: dict[str, float] = {}
        self.weights: dict[str, float] = {}

    def add(
        self,
        metrics: Mapping[str, float],
        *,
        weights: Optional[Mapping[str, float]] = None,
    ) -> None:
        weights = weights or {}
        for key, value in metrics.items():
            if not math.isfinite(value):
                continue
            weight = float(weights.get(key, 1.0))
            if weight <= 0 or not math.isfinite(weight):
                continue
            self.sums[key] = self.sums.get(key, 0.0) + float(value) * weight
            self.weights[key] = self.weights.get(key, 0.0) + weight

    def merge(self, other: Mapping[str, Mapping[str, float]]) -> None:
        for key, value in other.get("sums", {}).items():
            self.sums[key] = self.sums.get(key, 0.0) + float(value)
        for key, value in other.get("weights", {}).items():
            self.weights[key] = self.weights.get(key, 0.0) + float(value)

    def state_dict(self) -> dict[str, dict[str, float]]:
        return {"sums": dict(self.sums), "weights": dict(self.weights)}

    def mean(self) -> dict[str, float]:
        return {
            key: value / max(self.weights.get(key, 0.0), 1e-12)
            for key, value in self.sums.items()
            if self.weights.get(key, 0.0) > 0
        }

    def reset(self) -> None:
        self.sums.clear()
        self.weights.clear()


def _distributed_accumulator_mean(
    accumulator: MetricAccumulator,
    context: DistributedContext,
) -> dict[str, float]:
    merged = MetricAccumulator()
    for state in context.all_gather_objects(accumulator.state_dict()):
        merged.merge(state)
    return merged.mean()


def _format_metrics(prefix: str, step: int, metrics: Mapping[str, float]) -> str:
    preferred = [
        "loss",
        "task_loss",
        "functional_choice_loss",
        "functional_full_vocab_loss",
        "perplexity",
        "workspace_loss",
        "counterfactual_loss",
        "stability_loss",
        "functional_query_accuracy",
        "functional_label_0_recall",
        "functional_label_1_recall",
        "functional_prediction_entropy_nats",
        "functional_yes_minus_no_gap",
        "functional_all_query_world_accuracy",
        "functional_affected_donor_accuracy",
        "functional_unaffected_original_stability",
        "loss_info",
        "loss_worst",
        "retention_cosine",
        "final_state_anchor_cosine",
        "final_departure_l2",
        "path_length",
        "task_gain_nats",
        "gate_mean",
        "grad_norm",
        "lr_base",
        "lr_workspace",
        "tokens_per_second",
        "cuda_allocated_gb",
    ]
    parts = [f"{prefix} step={step}"]
    for key in preferred:
        if key in metrics:
            value = metrics[key]
            if "tokens" in key:
                parts.append(f"{key}={value:.1f}")
            else:
                parts.append(f"{key}={value:.5f}")
    return " | ".join(parts)


def _optimizer_learning_rates(optimizer: torch.optim.Optimizer) -> dict[str, float]:
    result: dict[str, float] = {}
    for group in optimizer.param_groups:
        family = str(group.get("family", "group"))
        result[f"lr_{family}"] = float(group["lr"])
    return result


def _memory_metrics(device: torch.device) -> dict[str, float]:
    if device.type != "cuda":
        return {}
    gib = float(1024**3)
    return {
        "cuda_allocated_gb": torch.cuda.memory_allocated(device) / gib,
        "cuda_reserved_gb": torch.cuda.memory_reserved(device) / gib,
        "cuda_peak_allocated_gb": torch.cuda.max_memory_allocated(device) / gib,
    }


@torch.no_grad()
def evaluate(
    model: LatentWorkspaceCausalLM,
    dataloader: DataLoader[Any],
    *,
    device: torch.device,
    precision: str,
    workspace_loss_weight: float,
    max_batches: int,
    compute_spectral: bool = True,
    compute_workspace_loss: bool = True,
    bypass_workspace: bool = False,
    memory_intervention: str = "intact",
    memory_intervention_seed: int = 0,
) -> dict[str, float]:
    was_training = model.training
    model.eval()
    accumulator = MetricAccumulator()
    total_nll = 0.0
    total_tokens = 0
    functional_totals: dict[str, float] = {}

    for batch_index, raw_batch in enumerate(dataloader):
        if max_batches > 0 and batch_index >= max_batches:
            break
        batch = move_batch_to_device(raw_batch, device)
        with autocast_context(device, precision):
            output = model(
                input_ids=batch["input_ids"],
                attention_mask=batch["attention_mask"],
                labels=batch["labels"],
                prompt_mask=batch["prompt_mask"],
                context_mask=batch.get("context_mask"),
                query_mask=batch.get("query_mask"),
                example_group_ids=batch.get("example_group_ids"),
                world_group_ids=batch.get("world_group_ids"),
                counterfactual_group_ids=batch.get("counterfactual_group_ids"),
                answer_classes=batch.get("answer_classes"),
                **bridge_batch_kwargs(batch),
                **functional_batch_kwargs(batch),
                compute_workspace_loss=compute_workspace_loss,
                compute_spectral=(compute_spectral and batch_index == 0),
                bypass_workspace=bypass_workspace,
                memory_intervention=memory_intervention,
                memory_intervention_seed=memory_intervention_seed + batch_index,
            )

        task_nll_sum = output["task_nll_sum"]
        if task_nll_sum is None:
            raise RuntimeError("Evaluation requires task_nll_sum.")
        token_count = int(output["supervised_tokens"].item())
        total_nll += float(task_nll_sum.detach().float().item())
        total_tokens += token_count
        for key, value in output.items():
            aggregate = key in {
                "choice_nll_sum",
                "full_vocab_nll_sum",
                "functional_yes_minus_no_gap_sum",
                "functional_query_count",
                "functional_query_correct",
                "functional_all_query_world_examples",
                "functional_all_query_world_correct",
                "functional_affected_examples",
                "functional_affected_correct",
                "functional_unaffected_examples",
                "functional_unaffected_correct",
                "functional_heldout_query_examples",
                "functional_heldout_query_correct",
            } or (
                key.startswith("functional_label_")
                and key.endswith(("_examples", "_correct", "_predictions"))
            ) or (
                key.startswith("functional_hop_")
                and key.endswith(("_examples", "_correct"))
            )
            if aggregate and isinstance(value, torch.Tensor) and value.numel() == 1:
                functional_totals[key] = functional_totals.get(key, 0.0) + float(
                    value.detach().float().item()
                )
        scalar = _scalar_workspace_metrics(output)
        query_count = float(scalar.get("functional_query_count", 0.0))
        weights = {
            "task_loss": float(token_count),
            "base_task_loss": float(token_count),
            "functional_full_vocab_loss": float(token_count),
            "functional_choice_loss": float(token_count),
        }
        for key in (
            "functional_query_accuracy",
            "functional_choice_margin",
            "functional_yes_minus_no_gap",
        ):
            weights[key] = query_count
        weights["functional_all_query_world_accuracy"] = float(
            scalar.get("functional_all_query_world_examples", 0.0)
        )
        for stem in (
            "functional_affected",
            "functional_unaffected",
            "functional_heldout_query",
        ):
            weights[f"{stem}_accuracy"] = float(
                scalar.get(f"{stem}_examples", 0.0)
            )
        for key in tuple(scalar):
            if key.startswith("functional_label_") and key.endswith("_recall"):
                weights[key] = float(
                    scalar.get(key.removesuffix("_recall") + "_examples", 0.0)
                )
            elif key.startswith("functional_label_") and key.endswith(
                "_prediction_fraction"
            ):
                weights[key] = query_count
        for hop in range(1, 9):
            weights[f"functional_hop_{hop}_accuracy"] = float(
                scalar.get(f"functional_hop_{hop}_examples", 0.0)
            )
        accumulator.add(scalar, weights=weights)

        per_example_nll = output.get("per_example_nll")
        per_example_base_nll = output.get("per_example_base_nll")
        per_example_tokens = output.get("per_example_tokens")
        distances = batch.get("rank_distances")
        if (
            "functional_query_valid_mask" not in batch
            and isinstance(per_example_nll, torch.Tensor)
            and isinstance(per_example_base_nll, torch.Tensor)
            and isinstance(per_example_tokens, torch.Tensor)
            and isinstance(distances, torch.Tensor)
        ):
            for row in range(per_example_nll.numel()):
                distance = int(distances[row].item())
                count = int(per_example_tokens[row].item())
                if distance < 0 or count <= 0:
                    continue
                key = f"distance_{distance}"
                row_loss = float(per_example_nll[row].float().item()) / count
                row_base = float(per_example_base_nll[row].float().item()) / count
                accumulator.add(
                    {
                        f"{key}_task_loss": row_loss,
                        f"{key}_base_task_loss": row_base,
                        f"{key}_task_gain_nats": row_base - row_loss,
                        f"{key}_examples": 1.0,
                    },
                    weights={
                        f"{key}_task_loss": float(count),
                        f"{key}_base_task_loss": float(count),
                        f"{key}_task_gain_nats": float(count),
                    },
                )

    metrics = accumulator.mean()
    functional_query_count = functional_totals.get("functional_query_count", 0.0)
    if functional_query_count > 0:
        metrics["functional_query_count"] = functional_query_count
        metrics["functional_query_accuracy"] = (
            functional_totals.get("functional_query_correct", 0.0)
            / functional_query_count
        )
        metrics["functional_choice_loss"] = (
            functional_totals.get("choice_nll_sum", 0.0)
            / functional_query_count
        )
        metrics["functional_full_vocab_loss"] = (
            functional_totals.get("full_vocab_nll_sum", 0.0)
            / functional_query_count
        )
        metrics["functional_yes_minus_no_gap"] = (
            functional_totals.get("functional_yes_minus_no_gap_sum", 0.0)
            / functional_query_count
        )
        world_examples = functional_totals.get(
            "functional_all_query_world_examples", 0.0
        )
        metrics["functional_all_query_world_examples"] = world_examples
        if world_examples > 0:
            metrics["functional_all_query_world_accuracy"] = (
                functional_totals.get("functional_all_query_world_correct", 0.0)
                / world_examples
            )
        for stem in (
            "functional_affected",
            "functional_unaffected",
            "functional_heldout_query",
        ):
            examples = functional_totals.get(f"{stem}_examples", 0.0)
            metrics[f"{stem}_examples"] = examples
            if examples > 0:
                metrics[f"{stem}_accuracy"] = (
                    functional_totals.get(f"{stem}_correct", 0.0) / examples
                )

        label_ids = sorted(
            {
                int(key.split("_")[2])
                for key in functional_totals
                if key.startswith("functional_label_")
                and key.endswith("_examples")
            }
        )
        prediction_counts: list[float] = []
        for label in label_ids:
            prefix = f"functional_label_{label}"
            examples = functional_totals.get(f"{prefix}_examples", 0.0)
            correct = functional_totals.get(f"{prefix}_correct", 0.0)
            predictions = functional_totals.get(f"{prefix}_predictions", 0.0)
            prediction_counts.append(predictions)
            metrics[f"{prefix}_examples"] = examples
            metrics[f"{prefix}_correct"] = correct
            metrics[f"{prefix}_predictions"] = predictions
            metrics[f"{prefix}_recall"] = correct / max(examples, 1.0)
            metrics[f"{prefix}_prediction_fraction"] = (
                predictions / functional_query_count
            )
        prediction_probabilities = [
            count / functional_query_count
            for count in prediction_counts
            if count > 0
        ]
        metrics["functional_prediction_entropy_nats"] = -sum(
            probability * math.log(probability)
            for probability in prediction_probabilities
        )
        metrics["functional_distinct_predicted_classes"] = float(
            sum(count > 0 for count in prediction_counts)
        )
        for hop in range(1, 9):
            prefix = f"functional_hop_{hop}"
            examples = functional_totals.get(f"{prefix}_examples", 0.0)
            if examples <= 0:
                continue
            metrics[f"{prefix}_examples"] = examples
            metrics[f"{prefix}_accuracy"] = (
                functional_totals.get(f"{prefix}_correct", 0.0) / examples
            )
    task_loss = total_nll / max(total_tokens, 1)
    metrics["task_loss"] = task_loss
    metrics["perplexity"] = math.exp(min(task_loss, 20.0))
    metrics["loss"] = task_loss + workspace_loss_weight * metrics.get(
        "workspace_loss", 0.0
    )
    metrics["supervised_tokens"] = float(total_tokens)
    if was_training:
        model.train()
    return metrics


def _base_layer_group(name: str) -> str:
    """Map heterogeneous transformer parameter names to auditable layer groups."""
    stripped = name.removeprefix("base_model.")
    patterns = (
        r"(?:^|\.)(?:h|layers|blocks|block|layer)\.(\d+)(?:\.|$)",
        r"(?:^|\.)encoder\.layer\.(\d+)(?:\.|$)",
        r"(?:^|\.)decoder\.layer\.(\d+)(?:\.|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, stripped)
        if match:
            return f"block.{int(match.group(1)):04d}"
    lowered = stripped.lower()
    if any(token in lowered for token in ("wte", "wpe", "embed", "embedding")):
        return "embeddings"
    if "lm_head" in lowered or "output_projection" in lowered:
        return "lm_head"
    if any(token in lowered for token in ("ln_f", "final_layer_norm", "final_norm")):
        return "final_norm"
    return "other"


def _alignment_record(
    dot: torch.Tensor,
    task_sq: torch.Tensor,
    auxiliary_sq: torch.Tensor,
) -> dict[str, float]:
    task_norm = torch.sqrt(task_sq.clamp_min(0.0))
    auxiliary_norm = torch.sqrt(auxiliary_sq.clamp_min(0.0))
    denominator = task_norm * auxiliary_norm
    cosine = torch.where(
        denominator > 0,
        dot / denominator.clamp_min(1e-30),
        torch.zeros_like(dot),
    )
    return {
        "dot": float(dot.detach().double().item()),
        "task_norm": float(task_norm.detach().double().item()),
        "auxiliary_norm": float(auxiliary_norm.detach().double().item()),
        "cosine": float(cosine.detach().double().item()),
    }


def compute_gradient_alignment(
    model: LatentWorkspaceCausalLM,
    batch: Mapping[str, torch.Tensor],
    *,
    device: torch.device,
    precision: str,
    attribution: AttributionConfig,
    assays: AssayConfig,
    seed: int,
) -> dict[str, Any]:
    """Measure task/auxiliary gradient alignment without mutating parameters.

    This is a deterministic assay forward. By default the model is placed in
    eval mode so dropout does not turn the layer map into another stochastic
    treatment. ``torch.autograd.grad`` returns gradients directly and leaves
    ``parameter.grad`` untouched.
    """
    named_parameters = [
        (name, parameter)
        for name, parameter in model.named_parameters()
        if name.startswith("base_model.") and parameter.requires_grad
    ]
    if not named_parameters:
        return {
            "global": {"dot": 0.0, "task_norm": 0.0, "auxiliary_norm": 0.0, "cosine": 0.0},
            "groups": {},
            "base_parameters": 0,
        }

    was_training = model.training
    if assays.gradient_alignment_eval_mode:
        model.eval()
    local_batch = move_batch_to_device(batch, device)
    route_seed = deterministic_stream_seed(seed, 0, 0, 0, attribution.assay_seed_offset)
    streams = {
        "route": route_seed,
        "auxiliary": (route_seed + 1) % (2**63 - 1),
        "assay": (route_seed + 2) % (2**63 - 1),
    }
    try:
        with isolated_torch_rng(True, streams["assay"], device):
            with torch.enable_grad():
                with autocast_context(device, precision):
                    output = model(
                        input_ids=local_batch["input_ids"],
                        attention_mask=local_batch["attention_mask"],
                        labels=local_batch["labels"],
                        prompt_mask=local_batch["prompt_mask"],
                        context_mask=local_batch.get("context_mask"),
                        query_mask=local_batch.get("query_mask"),
                        example_group_ids=local_batch.get("example_group_ids"),
                        world_group_ids=local_batch.get("world_group_ids"),
                        counterfactual_group_ids=local_batch.get(
                            "counterfactual_group_ids"
                        ),
                        answer_classes=local_batch.get("answer_classes"),
                        **bridge_batch_kwargs(local_batch),
                        **functional_batch_kwargs(local_batch),
                        compute_workspace_loss=True,
                        compute_spectral=False,
                        bypass_workspace=False,
                        rng_streams=streams,
                    )
                    task_sum = output.get("task_nll_sum")
                    if not isinstance(task_sum, torch.Tensor):
                        raise RuntimeError("Gradient alignment requires supervised tokens.")
                    token_count = output["supervised_tokens"].to(task_sum.dtype)
                    task_objective = task_sum / token_count.clamp_min(1.0)
                    auxiliary_objective = output["workspace_loss"]

                parameters = [parameter for _, parameter in named_parameters]
                task_gradients = torch.autograd.grad(
                    task_objective,
                    parameters,
                    retain_graph=True,
                    allow_unused=True,
                )
                auxiliary_gradients = torch.autograd.grad(
                    auxiliary_objective,
                    parameters,
                    retain_graph=False,
                    allow_unused=True,
                )
    finally:
        if was_training:
            model.train()
        else:
            model.eval()

    zero = torch.zeros((), device=device, dtype=torch.float64)
    global_dot = zero.clone()
    global_task_sq = zero.clone()
    global_auxiliary_sq = zero.clone()
    grouped: dict[str, list[torch.Tensor]] = {}
    used = 0
    for (name, _parameter), task_gradient, auxiliary_gradient in zip(
        named_parameters, task_gradients, auxiliary_gradients
    ):
        if task_gradient is None and auxiliary_gradient is None:
            continue
        task_tensor = (
            torch.zeros_like(auxiliary_gradient)
            if task_gradient is None and auxiliary_gradient is not None
            else task_gradient
        )
        auxiliary_tensor = (
            torch.zeros_like(task_gradient)
            if auxiliary_gradient is None and task_gradient is not None
            else auxiliary_gradient
        )
        assert task_tensor is not None and auxiliary_tensor is not None
        task_flat = task_tensor.detach().double().reshape(-1)
        auxiliary_flat = auxiliary_tensor.detach().double().reshape(-1)
        dot = torch.dot(task_flat, auxiliary_flat)
        task_sq = torch.dot(task_flat, task_flat)
        auxiliary_sq = torch.dot(auxiliary_flat, auxiliary_flat)
        global_dot = global_dot + dot
        global_task_sq = global_task_sq + task_sq
        global_auxiliary_sq = global_auxiliary_sq + auxiliary_sq
        group = _base_layer_group(name)
        if group not in grouped:
            grouped[group] = [zero.clone(), zero.clone(), zero.clone()]
        grouped[group][0] = grouped[group][0] + dot
        grouped[group][1] = grouped[group][1] + task_sq
        grouped[group][2] = grouped[group][2] + auxiliary_sq
        used += 1

    group_records = {
        name: _alignment_record(*values)
        for name, values in grouped.items()
    }
    limit = max(1, int(assays.gradient_alignment_max_groups))
    if len(group_records) > limit:
        ordered = sorted(
            group_records.items(),
            key=lambda item: item[1]["task_norm"] + item[1]["auxiliary_norm"],
            reverse=True,
        )[:limit]
        group_records = dict(sorted(ordered))
    return {
        "global": _alignment_record(
            global_dot, global_task_sq, global_auxiliary_sq
        ),
        "groups": dict(sorted(group_records.items())),
        "base_parameters": used,
        "task_loss": float(task_objective.detach().float().item()),
        "workspace_loss": float(auxiliary_objective.detach().float().item()),
        "eval_mode": bool(assays.gradient_alignment_eval_mode),
    }


@dataclass
class RunState:
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    global_step: int = 0
    epoch: int = 0
    next_batch_in_epoch: int = 0
    total_supervised_tokens: int = 0
    optimizer_steps_skipped: int = 0
    nonfinite_skips: int = 0
    auxiliary_dose: float = 0.0
    lr_weighted_auxiliary_dose: float = 0.0
    clip_adjusted_base_auxiliary_exposure: float = 0.0
    clip_adjusted_workspace_auxiliary_exposure: float = 0.0
    induction_steps: int = 0
    last_induction_phase: str = "uninitialized"
    best_metric: Optional[float] = None
    best_step: int = -1

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "RunState":
        valid = {item.name for item in fields(cls)}
        return cls(**{key: value for key, value in raw.items() if key in valid})


def dose_ledger(state: RunState) -> dict[str, float]:
    return {
        "nominal_auxiliary_dose": float(state.auxiliary_dose),
        "lr_weighted_auxiliary_dose": float(
            state.lr_weighted_auxiliary_dose
        ),
        "clip_adjusted_base_auxiliary_exposure": float(
            state.clip_adjusted_base_auxiliary_exposure
        ),
        "clip_adjusted_workspace_auxiliary_exposure": float(
            state.clip_adjusted_workspace_auxiliary_exposure
        ),
        "induction_steps": float(state.induction_steps),
    }


def _capture_rng_state(device: torch.device) -> dict[str, Any]:
    result: dict[str, Any] = {
        "python": random.getstate(),
        "torch_cpu": torch.get_rng_state(),
    }
    if device.type == "cuda":
        result["torch_cuda"] = torch.cuda.get_rng_state(device)
    return result


def _restore_rng_state(state: Mapping[str, Any], device: torch.device) -> None:
    if "python" in state:
        random.setstate(state["python"])
    if "torch_cpu" in state:
        torch.set_rng_state(state["torch_cpu"])
    if device.type == "cuda" and "torch_cuda" in state:
        torch.cuda.set_rng_state(state["torch_cuda"], device=device)


def _torch_load(path: Path, *, weights_only: bool) -> Any:
    try:
        return torch.load(path, map_location="cpu", weights_only=weights_only)
    except TypeError:
        return torch.load(path, map_location="cpu")


def _save_base_model(
    base_model: nn.Module,
    path: Path,
    *,
    config: ExperimentConfig,
    force_frozen_base: bool = False,
) -> str:
    if (
        config.model.train_mode == "workspace_only"
        and not config.train.save_frozen_base
        and not force_frozen_base
    ):
        _atomic_write_json(
            path.parent / "base_reference.json",
            {
                "name_or_path": config.model.name_or_path,
                "revision": config.model.revision,
                "local_files_only": config.model.local_files_only,
            },
        )
        return "reference"

    path.mkdir(parents=True, exist_ok=True)
    method = getattr(base_model, "save_pretrained", None)
    if method is None:
        torch.save(base_model.state_dict(), path / "pytorch_model.bin")
        return "state_dict"
    kwargs: dict[str, Any] = {
        "safe_serialization": True,
        "max_shard_size": config.train.max_shard_size,
    }
    try:
        method(path, **kwargs)
    except TypeError:
        kwargs.pop("max_shard_size", None)
        try:
            method(path, **kwargs)
        except TypeError:
            method(path)
    return "pretrained"


def _directory_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for root, _directories, filenames in os.walk(path):
        for filename in filenames:
            try:
                total += (Path(root) / filename).stat().st_size
            except FileNotFoundError:
                # A concurrently pruned stale checkpoint is irrelevant to the
                # headroom estimate.
                continue
    return total


def _checkpoint_size_estimate(output_dir: Path) -> int:
    candidates = [
        path
        for path in [find_latest_checkpoint(output_dir), output_dir / "final"]
        if path is not None and _is_complete_checkpoint(path)
    ]
    return max((_directory_size_bytes(path) for path in candidates), default=0)


def _ensure_disk_space(
    path: Path,
    minimum_gb: float,
    *,
    estimated_checkpoint_bytes: int = 0,
    headroom_ratio: float = 1.0,
) -> None:
    gib = float(1024**3)
    free_bytes = shutil.disk_usage(path).free
    required_bytes = max(
        int(max(0.0, minimum_gb) * gib),
        int(max(0, estimated_checkpoint_bytes) * max(1.0, headroom_ratio)),
    )
    if free_bytes < required_bytes:
        raise RuntimeError(
            f"Only {free_bytes / gib:.2f} GiB is free at {path}; "
            f"checkpoint save requires about {required_bytes / gib:.2f} GiB "
            "including configured headroom."
        )


def _commit_directory(temporary: Path, destination: Path) -> None:
    backup: Optional[Path] = None
    if destination.exists():
        backup = destination.with_name(
            f".{destination.name}.old-{os.getpid()}-{uuid.uuid4().hex}"
        )
        os.replace(destination, backup)
    try:
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    except Exception:
        if backup is not None and backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise
    if backup is not None:
        shutil.rmtree(backup, ignore_errors=True)


def save_bundle(
    path: str | os.PathLike[str],
    *,
    model: nn.Module,
    tokenizer: Any,
    config: ExperimentConfig,
    global_step: int,
    optimizer: Optional[torch.optim.Optimizer] = None,
    scheduler: Optional[torch.optim.lr_scheduler.LRScheduler] = None,
    scaler: Optional[Any] = None,
    run_state: Optional[RunState] = None,
    sampler_state: Optional[Mapping[str, Any]] = None,
    data_fingerprint: Optional[Mapping[str, Any]] = None,
    base_update_coverage: Optional[Mapping[str, Any]] = None,
    distributed: Optional[DistributedContext] = None,
    force_frozen_base: bool = False,
) -> Path:
    context = distributed or DistributedContext(
        enabled=False,
        rank=0,
        local_rank=0,
        world_size=1,
        backend="none",
        device=next(unwrap_model(model).parameters()).device,
    )
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)

    local_rng = _capture_rng_state(context.device)
    rng_by_rank = context.all_gather_objects(local_rng)
    context.barrier()

    error: Optional[str] = None
    if context.is_main:
        temporary = destination.with_name(
            f".{destination.name}.incomplete-{os.getpid()}-{uuid.uuid4().hex}"
        )
        try:
            _ensure_disk_space(
                destination.parent,
                config.train.minimum_free_disk_gb,
                estimated_checkpoint_bytes=_checkpoint_size_estimate(destination.parent),
                headroom_ratio=config.train.checkpoint_headroom_ratio,
            )
            if temporary.exists():
                shutil.rmtree(temporary)
            temporary.mkdir(parents=True)

            raw_model = unwrap_model(model)
            optimizer_coverage: Optional[dict[str, Any]] = None
            if optimizer is not None:
                optimizer_coverage = optimizer_coverage_report(
                    raw_model,
                    optimizer,
                    train_mode=config.model.train_mode,
                )
                _atomic_write_json(
                    temporary / "optimizer_coverage.json",
                    optimizer_coverage,
                )
                require_exact_optimizer_coverage(optimizer_coverage)
            durable_base_update_coverage: Optional[dict[str, Any]] = None
            if base_update_coverage is not None:
                durable_base_update_coverage = dict(base_update_coverage)
                require_base_update_coverage(durable_base_update_coverage)
                _atomic_write_json(
                    temporary / "base_update_coverage.json",
                    durable_base_update_coverage,
                )
            base_storage = _save_base_model(
                raw_model.base_model,
                temporary / "base_model",
                config=config,
                force_frozen_base=force_frozen_base,
            )
            tokenizer.save_pretrained(temporary / "tokenizer")
            torch.save(raw_model.custom_state_dict(), temporary / "workspace_state.pt")
            config.to_json(temporary / "experiment_config.json")

            state = run_state or RunState(global_step=int(global_step))
            trainer_state: dict[str, Any] = {
                "run_state": asdict(state),
                "global_step": int(global_step),
                "sampler_state": dict(sampler_state or {}),
                "rng_by_rank": rng_by_rank,
                "world_size": context.world_size,
                "data_fingerprint": dict(data_fingerprint or {}),
                "resume_signature": resume_signature(config),
                "structural_resume_signature": resume_signature(
                    config, ignore_schedule_horizon=True
                ),
            }
            if optimizer is not None and config.train.save_optimizer:
                trainer_state["optimizer"] = optimizer.state_dict()
            if scheduler is not None:
                trainer_state["scheduler"] = scheduler.state_dict()
            if scaler is not None:
                trainer_state["scaler"] = scaler.state_dict()
            torch.save(trainer_state, temporary / "trainer_state.pt")

            manifest = {
                "format": "latent-workspace-ft-bundle-v4",
                "complete": True,
                "global_step": int(global_step),
                "run_id": state.run_id,
                "train_mode": config.model.train_mode,
                "base_storage": base_storage,
                "base_model_name_or_path": config.model.name_or_path,
                "config_sha256": stable_hash(asdict(config)),
                "resume_signature": resume_signature(config),
                "structural_resume_signature": resume_signature(
                    config, ignore_schedule_horizon=True
                ),
                "data_fingerprint": dict(data_fingerprint or {}),
                "world_size": context.world_size,
                "harness_version": __version__,
                "torch_version": torch.__version__,
                "source_sha256": source_sha256(),
                "optimizer_saved": bool(
                    optimizer is not None and config.train.save_optimizer
                ),
                "optimizer_coverage_sha256": (
                    optimizer_coverage["report_sha256"]
                    if optimizer_coverage is not None
                    else None
                ),
                "optimizer_coverage_passed": bool(
                    optimizer_coverage is not None
                    and optimizer_coverage["passed"]
                ),
                "base_update_coverage_sha256": (
                    durable_base_update_coverage["report_sha256"]
                    if durable_base_update_coverage is not None
                    else None
                ),
                "base_update_coverage_passed": bool(
                    durable_base_update_coverage is not None
                    and durable_base_update_coverage["passed"]
                ),
                "scheduler_saved": scheduler is not None,
                "scaler_saved": scaler is not None,
                "created_unix": time.time(),
            }
            _atomic_write_json(temporary / "manifest.json", manifest)
            _atomic_write_text(temporary / "COMPLETED", "ok\n")
            _commit_directory(temporary, destination)
            if destination.name.startswith("checkpoint-"):
                _atomic_write_json(
                    destination.parent / "latest_checkpoint.json",
                    {
                        "path": destination.name,
                        "global_step": int(global_step),
                        "run_id": state.run_id,
                    },
                )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            shutil.rmtree(temporary, ignore_errors=True)

    error = context.broadcast_object(error, source=0)
    context.barrier()
    if error is not None:
        raise RuntimeError(f"Checkpoint save failed: {error}")
    return destination


def _is_complete_checkpoint(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "COMPLETED").exists()
        and (path / "manifest.json").exists()
        and (path / "workspace_state.pt").exists()
    )


def _read_bundle_manifest(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def find_latest_checkpoint(
    output_dir: Path,
    *,
    require_optimizer: bool = False,
) -> Optional[Path]:
    candidates: dict[Path, tuple[int, int]] = {}

    pointer = output_dir / "latest_checkpoint.json"
    if pointer.exists():
        try:
            raw = json.loads(pointer.read_text(encoding="utf-8"))
            path = (output_dir / str(raw["path"])).resolve()
            if _is_complete_checkpoint(path):
                manifest = _read_bundle_manifest(path)
                if not require_optimizer or bool(manifest.get("optimizer_saved", False)):
                    candidates[path] = (
                        int(manifest.get("global_step", raw.get("global_step", 0))),
                        0,
                    )
        except Exception:
            pass

    paths = list(output_dir.glob("checkpoint-*"))
    final = output_dir / "final"
    if final.exists():
        paths.append(final)

    for path in paths:
        if not _is_complete_checkpoint(path):
            continue
        manifest = _read_bundle_manifest(path)
        if require_optimizer and not bool(manifest.get("optimizer_saved", False)):
            continue
        try:
            if path.name == "final":
                step = int(manifest.get("global_step", 0))
                preference = 1
            else:
                step = int(manifest.get("global_step", path.name.rsplit("-", 1)[-1]))
                preference = 0
        except (TypeError, ValueError):
            continue
        candidates[path.resolve()] = (step, preference)

    if not candidates:
        return None
    return max(candidates, key=lambda path: candidates[path])


def resolve_resume_checkpoint(config: ExperimentConfig) -> Optional[Path]:
    request = str(config.train.resume_from).strip()
    if request in {"", "none"}:
        return None
    if request == "auto":
        return find_latest_checkpoint(
            Path(config.train.output_dir),
            require_optimizer=config.train.strict_resume,
        )
    candidate = Path(request).expanduser().resolve()
    if not _is_complete_checkpoint(candidate):
        raise FileNotFoundError(f"Not a complete checkpoint: {candidate}")
    manifest = _read_bundle_manifest(candidate)
    if config.train.strict_resume and not bool(manifest.get("optimizer_saved", False)):
        raise RuntimeError(
            f"Strict resume requires optimizer state, but {candidate} was saved "
            "without it. Set strict_resume=false only for an intentional warm restart."
        )
    return candidate


def prune_checkpoints(output_dir: Path, keep: int) -> None:
    if keep <= 0:
        return
    protected: set[Path] = set()
    best_pointer = output_dir / "best_checkpoint.json"
    if best_pointer.exists():
        try:
            protected.add((output_dir / json.loads(best_pointer.read_text())["path"]).resolve())
        except Exception:
            pass

    checkpoints: list[tuple[int, Path]] = []
    for path in output_dir.glob("checkpoint-*"):
        if not _is_complete_checkpoint(path):
            continue
        try:
            step = int(path.name.rsplit("-", 1)[-1])
        except ValueError:
            continue
        checkpoints.append((step, path))
    checkpoints.sort()
    removable = [path for _, path in checkpoints[:-keep] if path.resolve() not in protected]
    for path in removable:
        shutil.rmtree(path, ignore_errors=True)


def _write_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(record), ensure_ascii=False) + "\n")
        handle.flush()


def _write_heartbeat(
    output_dir: Path,
    state: RunState,
    *,
    status: str,
    context: DistributedContext,
    extra: Optional[Mapping[str, Any]] = None,
) -> None:
    if not context.is_main:
        return
    payload: dict[str, Any] = {
        "status": status,
        "run_id": state.run_id,
        "global_step": state.global_step,
        "epoch": state.epoch,
        "next_batch_in_epoch": state.next_batch_in_epoch,
        "total_supervised_tokens": state.total_supervised_tokens,
        "auxiliary_dose": state.auxiliary_dose,
        "induction_phase": state.last_induction_phase,
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "updated_unix": time.time(),
    }
    if extra:
        payload.update(dict(extra))
    _atomic_write_json(output_dir / "heartbeat.json", payload)


class PreemptionController:
    def __init__(self) -> None:
        self.requested = False
        self.signal_name: Optional[str] = None
        self._old_handlers: dict[int, Any] = {}

    def _handler(self, signum: int, _frame: Any) -> None:
        self.requested = True
        try:
            self.signal_name = signal.Signals(signum).name
        except Exception:
            self.signal_name = str(signum)

    def install(self) -> None:
        for signum in (signal.SIGINT, signal.SIGTERM):
            self._old_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, self._handler)

    def restore(self) -> None:
        for signum, handler in self._old_handlers.items():
            signal.signal(signum, handler)
        self._old_handlers.clear()


def _iter_windows(
    iterator: Iterator[Any],
    window_size: int,
) -> Iterator[list[Any]]:
    while True:
        window: list[Any] = []
        for _ in range(window_size):
            try:
                window.append(next(iterator))
            except StopIteration:
                break
        if not window:
            return
        yield window


def _optimizer_state_value_to_device(value: Any, device: torch.device) -> Any:
    """Copy checkpoint optimizer state to a device without changing dtype."""

    if isinstance(value, torch.Tensor):
        return value.detach().to(device=device, copy=True)
    if isinstance(value, Mapping):
        return {
            key: _optimizer_state_value_to_device(child, device)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_optimizer_state_value_to_device(child, device) for child in value]
    if isinstance(value, tuple):
        return tuple(_optimizer_state_value_to_device(child, device) for child in value)
    return copy.deepcopy(value)


def _restore_optimizer_state_exact(
    optimizer: torch.optim.Optimizer,
    saved_optimizer_state: Mapping[str, Any],
) -> None:
    """Undo PyTorch's parameter-dtype cast while preserving loaded groups.

    ``Optimizer.load_state_dict`` intentionally casts floating optimizer state
    tensors to each parameter's dtype.  That is lossy for BF16 full updates
    whose Adafactor moments were accumulated and checkpointed in FP32.  Re-map
    the already validated saved parameter IDs to the live parameters and copy
    the original tensor values/dtypes directly to their parameter devices.
    """

    saved_groups = saved_optimizer_state.get("param_groups")
    saved_states = saved_optimizer_state.get("state")
    if not isinstance(saved_groups, list) or not isinstance(saved_states, Mapping):
        raise RuntimeError("Checkpoint optimizer state is malformed.")
    if len(saved_groups) != len(optimizer.param_groups):
        raise RuntimeError("Checkpoint optimizer group count changed during exact restore.")
    restored_parameter_count = 0
    for group_index, (saved_group, current_group) in enumerate(
        zip(saved_groups, optimizer.param_groups, strict=True)
    ):
        if not isinstance(saved_group, Mapping):
            raise RuntimeError(f"Checkpoint optimizer group {group_index} is malformed.")
        saved_parameter_ids = saved_group.get("params")
        current_parameters = current_group.get("params")
        if not isinstance(saved_parameter_ids, list) or not isinstance(
            current_parameters, list
        ):
            raise RuntimeError(f"Checkpoint optimizer group {group_index} has no params.")
        if len(saved_parameter_ids) != len(current_parameters):
            raise RuntimeError(
                f"Checkpoint optimizer group {group_index} parameter count changed."
            )
        for saved_id, parameter in zip(
            saved_parameter_ids, current_parameters, strict=True
        ):
            if saved_id not in saved_states:
                optimizer.state.pop(parameter, None)
                continue
            optimizer.state[parameter] = _optimizer_state_value_to_device(
                saved_states[saved_id], parameter.device
            )
            restored_parameter_count += 1
    if restored_parameter_count != len(saved_states):
        raise RuntimeError(
            "Checkpoint optimizer state contains entries not mapped to live parameters."
        )


def _load_training_model(
    checkpoint: Path,
    current_config: ExperimentConfig,
) -> tuple[LatentWorkspaceCausalLM, Any, ExperimentConfig]:
    config_path = checkpoint / "experiment_config.json"
    saved_config = ExperimentConfig.from_json(config_path)
    if current_config.train.strict_resume:
        manifest = _read_bundle_manifest(checkpoint)
        expected = str(manifest.get("resume_signature", ""))
        actual = resume_signature(current_config)
        signature_matches = not expected or expected == actual
        if not signature_matches and current_config.train.allow_schedule_extension:
            expected_structural = str(
                manifest.get("structural_resume_signature", "")
            )
            actual_structural = resume_signature(
                current_config, ignore_schedule_horizon=True
            )
            signature_matches = bool(expected_structural) and (
                expected_structural == actual_structural
            )
        if not signature_matches:
            raise RuntimeError(
                "The current config changes structural/optimizer fields that are "
                "frozen by strict_resume. For an intentional epochs/max_steps "
                "extension, set allow_schedule_extension=true; otherwise use the "
                "checkpoint config or set strict_resume=false deliberately."
            )
        saved_source = str(manifest.get("source_sha256", ""))
        current_source = source_sha256()
        if (
            current_config.train.strict_source_resume
            and saved_source
            and saved_source != "unavailable"
            and current_source != "unavailable"
            and saved_source != current_source
        ):
            raise RuntimeError(
                "Training source changed since the checkpoint. Exact resume is "
                "blocked by strict_source_resume; preserve the original monolith "
                "or disable this guard deliberately."
            )
        saved_torch = str(manifest.get("torch_version", ""))
        if (
            current_config.train.strict_torch_resume
            and saved_torch
            and saved_torch != str(torch.__version__)
        ):
            raise RuntimeError(
                f"PyTorch changed from {saved_torch} to {torch.__version__}; "
                "strict_torch_resume blocks a numerically ambiguous continuation."
            )

    _, AutoTokenizer = _import_transformers()
    tokenizer = AutoTokenizer.from_pretrained(
        checkpoint / "tokenizer",
        local_files_only=True,
    )
    if getattr(tokenizer, "pad_token_id", None) is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    base_model = _load_saved_base_model(
        checkpoint,
        saved_config,
        is_trainable=True,
        fallback_model_config=current_config.model,
    )
    wrapper = LatentWorkspaceCausalLM(
        base_model=base_model,
        hidden_dim=infer_hidden_size(base_model),
        vocab_size=infer_vocab_size(base_model),
        config=current_config.workspace,
        functional_config=current_config.functional,
        hidden_capture=current_config.model.hidden_capture,
        base_activation_offload=current_config.train.base_activation_offload,
    )
    custom_state = _torch_load(checkpoint / "workspace_state.pt", weights_only=True)
    wrapper.load_custom_state_dict(custom_state)
    configure_trainability(wrapper, current_config.model.train_mode)
    if (
        current_config.model.gradient_checkpointing
        and current_config.model.train_mode != "workspace_only"
    ):
        enable_gradient_checkpointing(wrapper.base_model)
    return wrapper, tokenizer, saved_config


def _verify_dataset(dataset: JsonlFineTuningDataset, count: int) -> None:
    if count <= 0:
        return
    number = min(count, len(dataset))
    if number == 1:
        indices = [0]
    else:
        indices = sorted(
            {
                int(round(position))
                for position in torch.linspace(0, len(dataset) - 1, number).tolist()
            }
        )
    for index in indices:
        dataset[index]


def _is_better(value: float, best: Optional[float], greater: bool) -> bool:
    if not math.isfinite(value):
        return False
    if best is None:
        return True
    return value > best if greater else value < best


def _load_resume_state(
    checkpoint: Path,
    *,
    optimizer: torch.optim.Optimizer,
    scheduler: torch.optim.lr_scheduler.LRScheduler,
    scaler: Any,
    sampler: ResumableDistributedBatchSampler,
    context: DistributedContext,
    current_fingerprint: Mapping[str, Any],
    strict: bool,
) -> tuple[RunState, Optional[Mapping[str, Any]]]:
    trainer_state = _torch_load(checkpoint / "trainer_state.pt", weights_only=False)
    saved_world_size = int(trainer_state.get("world_size", 1))
    if strict and saved_world_size != context.world_size:
        raise RuntimeError(
            f"Checkpoint world_size={saved_world_size}, current={context.world_size}."
        )
    saved_fingerprint = trainer_state.get("data_fingerprint", {})
    if strict and saved_fingerprint and not _same_data_fingerprint(
        saved_fingerprint, current_fingerprint
    ):
        raise RuntimeError("Training data content/order changed since the checkpoint.")

    if "optimizer" in trainer_state:
        saved_optimizer_state = trainer_state["optimizer"]
        optimizer.load_state_dict(saved_optimizer_state)
        _restore_optimizer_state_exact(optimizer, saved_optimizer_state)
    elif strict:
        raise RuntimeError("Checkpoint has no optimizer state for strict resume.")
    if "scheduler" in trainer_state:
        scheduler.load_state_dict(trainer_state["scheduler"])
    if "scaler" in trainer_state:
        scaler.load_state_dict(trainer_state["scaler"])

    state = RunState.from_dict(trainer_state.get("run_state", {}))
    sampler.load_state_dict(
        trainer_state.get(
            "sampler_state",
            {"epoch": state.epoch, "start_batch": state.next_batch_in_epoch},
        )
    )
    rng_by_rank = trainer_state.get("rng_by_rank", [])
    rank_rng: Optional[Mapping[str, Any]] = None
    if rng_by_rank:
        rng_index = min(context.rank, len(rng_by_rank) - 1)
        rank_rng = rng_by_rank[rng_index]
    return state, rank_rng


def train_experiment(config: ExperimentConfig) -> Path:
    config.validate()
    require_cuda_allocator_policy(config.train)
    configure_runtime_math(config.train)
    context = initialize_distributed(config.train)
    gradient_accumulation_offload_enabled = (
        config.train.gradient_accumulation_offload in {"cpu", "cpu_accumulate"}
    )
    try:
        _require_gradient_accumulation_offload_context(config.train, context)
    except Exception:
        context.close()
        raise
    controller = PreemptionController()
    controller.install()
    active_gradient_accumulator: Optional[_CPUGradientAccumulator] = None
    gradient_offload_parameters: tuple[tuple[str, nn.Parameter], ...] = ()
    gradient_offload_receipt: Optional[dict[str, Any]] = None
    gradient_offload_receipt_path: Optional[Path] = None

    try:
        output_dir = Path(config.train.output_dir)
        if context.is_main:
            output_dir.mkdir(parents=True, exist_ok=True)
        context.barrier()

        resume_checkpoint = resolve_resume_checkpoint(config)
        if gradient_accumulation_offload_enabled and resume_checkpoint is not None:
            _require_exact_gradient_offload_resume_signature(
                resume_checkpoint,
                config,
            )
        set_global_seed(config.train.seed)
        if resume_checkpoint is None:
            model, tokenizer = build_workspace_model(config)
        else:
            model, tokenizer, _ = _load_training_model(resume_checkpoint, config)
        model.to(context.device)
        require_effective_cuda_allocator_policy(config.train, context.device)

        train_dataset = JsonlFineTuningDataset(
            config.data.train_files,
            tokenizer,
            config.data,
        )
        eval_dataset: Optional[JsonlFineTuningDataset]
        if config.data.eval_files:
            eval_dataset = JsonlFineTuningDataset(
                config.data.eval_files,
                tokenizer,
                config.data,
            )
        else:
            eval_dataset = None
        _verify_dataset(train_dataset, config.data.verify_samples)
        if eval_dataset is not None:
            _verify_dataset(eval_dataset, min(config.data.verify_samples, 8))

        train_fingerprint = fingerprint_files(
            train_dataset.files,
            config.data.fingerprint_bytes,
            config.data.fingerprint_mode,
        )
        collator = CausalFineTuningCollator(
            pad_token_id=int(tokenizer.pad_token_id),
            pad_to_multiple_of=config.data.pad_to_multiple_of,
        )
        loader_config = dataclasses.replace(
            config.data,
            pin_memory=config.data.pin_memory and context.device.type == "cuda",
        )
        train_loader, train_sampler = build_train_dataloader(
            train_dataset,
            collator,
            config=loader_config,
            batch_size=config.train.batch_size,
            seed=config.train.seed + config.data.shuffle_buffer_seed,
            num_replicas=context.world_size,
            rank=context.rank,
        )
        eval_loader = (
            build_eval_dataloader(
                eval_dataset,
                collator,
                config=loader_config,
                batch_size=config.train.eval_batch_size,
                seed=config.train.seed + 17_000_003,
            )
            if eval_dataset is not None and context.is_main
            else None
        )

        optimizer_steps_per_epoch = math.ceil(
            train_sampler.full_batches_per_epoch
            / config.train.gradient_accumulation_steps
        )
        total_steps = (
            config.train.max_steps
            if config.train.max_steps > 0
            else config.train.epochs * optimizer_steps_per_epoch
        )
        if total_steps <= 0:
            raise RuntimeError("Training has zero optimizer steps.")

        optimizer = build_optimizer(model, config.train, context.device)
        optimizer_coverage = optimizer_coverage_report(
            model,
            optimizer,
            train_mode=config.model.train_mode,
        )
        if context.is_main:
            _atomic_write_json(
                output_dir / "optimizer_coverage.json",
                optimizer_coverage,
            )
        context.barrier()
        require_exact_optimizer_coverage(optimizer_coverage)
        if resume_checkpoint is not None:
            _require_resume_optimizer_mapping(resume_checkpoint, optimizer_coverage)
        scheduler = build_scheduler(
            optimizer,
            total_steps=total_steps,
            warmup_ratio=config.train.warmup_ratio,
        )
        precision = resolve_mixed_precision(config.train.mixed_precision, context.device)
        scaler = make_grad_scaler(context.device, precision)

        resume_rng: Optional[Mapping[str, Any]] = None
        if resume_checkpoint is not None:
            state, resume_rng = _load_resume_state(
                resume_checkpoint,
                optimizer=optimizer,
                scheduler=scheduler,
                scaler=scaler,
                sampler=train_sampler,
                context=context,
                current_fingerprint=train_fingerprint,
                strict=config.train.strict_resume,
            )
        else:
            state = RunState()
            train_sampler.set_epoch(0, 0)
            # Parameters must initialize identically; stochastic training may now
            # use a rank-specific stream.
            set_global_seed(config.train.seed + context.rank * 100_003)

        base_update_coverage: Optional[dict[str, Any]] = None
        if resume_checkpoint is not None:
            saved_base_update_coverage = (
                resume_checkpoint / "base_update_coverage.json"
            )
            if saved_base_update_coverage.exists():
                base_update_coverage = _load_base_update_coverage(
                    saved_base_update_coverage
                )
                if context.is_main:
                    _atomic_write_json(
                        output_dir / "base_update_coverage.json",
                        base_update_coverage,
                    )
        context.barrier()

        training_model = wrap_distributed_model(model, context, config)
        raw_model = unwrap_model(training_model)
        if gradient_accumulation_offload_enabled:
            gradient_offload_receipt_path = (
                output_dir / "gradient_accumulation_offload.json"
            )
            gradient_offload_parameters = tuple(
                (name, parameter)
                for name, parameter in raw_model.named_parameters()
                if parameter.requires_grad
            )
            schema_probe = _CPUGradientAccumulator(
                gradient_offload_parameters,
                require_cuda=True,
            )
            schema_records = schema_probe.schema_records()
            schema_probe.discard()
            current_source_digest = source_sha256()
            current_resume_digest = resume_signature(config)
            if gradient_offload_receipt_path.exists():
                if resume_checkpoint is None:
                    raise RuntimeError(
                        "An existing CPU gradient accumulation receipt cannot be "
                        "overwritten by a fresh run."
                    )
                gradient_offload_receipt = (
                    _continue_gradient_accumulation_offload_receipt(
                        gradient_offload_receipt_path,
                        schema_records,
                        run_id=state.run_id,
                        source_digest=current_source_digest,
                        resume_digest=current_resume_digest,
                        resume_checkpoint=resume_checkpoint,
                        resume_step=state.global_step,
                        configured_accumulation_steps=(
                            config.train.gradient_accumulation_steps
                        ),
                        offload_mode=config.train.gradient_accumulation_offload,
                    )
                )
            else:
                same_output_checkpoint = bool(
                    resume_checkpoint is not None
                    and resume_checkpoint.expanduser().resolve().parent
                    == output_dir.expanduser().resolve()
                )
                if same_output_checkpoint:
                    raise RuntimeError(
                        "Same-output CPU gradient accumulation resume is missing its "
                        "root gradient_accumulation_offload.json receipt."
                    )
                gradient_offload_receipt = _new_gradient_accumulation_offload_receipt(
                    schema_records,
                    run_id=state.run_id,
                    source_digest=current_source_digest,
                    resume_digest=current_resume_digest,
                    initial_global_step=state.global_step,
                    configured_accumulation_steps=(
                        config.train.gradient_accumulation_steps
                    ),
                    offload_mode=config.train.gradient_accumulation_offload,
                    resume_checkpoint=resume_checkpoint,
                    output_dir=output_dir,
                )
        # Restore stochastic state only after model construction, optimizer
        # creation, DataLoader setup, and DDP wrapping. None of those setup
        # operations may perturb the resumed dropout/sampling trajectory.
        if resume_rng is not None:
            _restore_rng_state(resume_rng, context.device)

        metrics_path = output_dir / "metrics.jsonl"
        microbatch_memory_path = output_dir / "microbatch_memory.jsonl"
        if context.is_main:
            if resume_checkpoint is None and metrics_path.exists():
                raise RuntimeError(
                    f"{metrics_path} already exists without a resumable checkpoint. "
                    "Choose a new output_dir or set resume_from explicitly."
                )
            config.to_json(output_dir / "resolved_config.json")
            _atomic_write_json(output_dir / "environment.json", runtime_environment())
            _atomic_write_json(output_dir / "data_fingerprint.json", train_fingerprint)
            if (
                gradient_offload_receipt is not None
                and gradient_offload_receipt_path is not None
            ):
                _write_gradient_accumulation_offload_receipt(
                    gradient_offload_receipt_path,
                    gradient_offload_receipt,
                )
            _write_jsonl(
                metrics_path,
                {
                    "event": "resume" if resume_checkpoint else "start",
                    "run_id": state.run_id,
                    "step": state.global_step,
                    "checkpoint": str(resume_checkpoint) if resume_checkpoint else None,
                    "time": time.time(),
                },
            )
            summary = {
                "harness_version": __version__,
                "device": str(context.device),
                "distributed": context.enabled,
                "backend": context.backend,
                "world_size": context.world_size,
                "mixed_precision": precision,
                "train_records": len(train_dataset),
                "eval_records": len(eval_dataset) if eval_dataset is not None else 0,
                "global_batches_per_epoch": train_sampler.full_batches_per_epoch,
                "optimizer_steps": total_steps,
                "optimizer_coverage_passed": optimizer_coverage["passed"],
                "optimizer_coverage_sha256": optimizer_coverage["report_sha256"],
                "gradient_accumulation_offload": (
                    config.train.gradient_accumulation_offload
                ),
                "resume_checkpoint": str(resume_checkpoint) if resume_checkpoint else None,
                **count_parameters(raw_model),
            }
            print(json.dumps(summary, indent=2))

        if (
            config.train.eval_at_start
            and resume_checkpoint is None
            and state.global_step == 0
            and eval_dataset is not None
        ):
            context.barrier()
            if context.is_main:
                assert eval_loader is not None
                starting_induction = induction_status(
                    config.workspace,
                    config.induction,
                    0,
                    total_steps,
                )
                step0_eval = evaluate(
                    raw_model,
                    eval_loader,
                    device=context.device,
                    precision=precision,
                    workspace_loss_weight=starting_induction.weight,
                    max_batches=config.train.eval_batches,
                    compute_spectral=config.workspace.spectral_every != 0,
                    compute_workspace_loss=config.workspace.loss_weight > 0.0,
                )
                step0_eval["step"] = 0.0
                step0_eval["optimizer_steps"] = 0.0
                print(_format_metrics("eval-step0", 0, step0_eval))
                _write_jsonl(
                    metrics_path,
                    {
                        "split": "eval-step0",
                        "run_id": state.run_id,
                        "induction_phase": starting_induction.phase,
                        "functional_task_objective": (
                            config.functional.task_objective
                        ),
                        **step0_eval,
                    },
                )
            context.barrier()

        training_model.train()
        if config.model.train_mode == "workspace_only":
            raw_model.base_model.eval()
        optimizer.zero_grad(set_to_none=True)

        log_accumulator = MetricAccumulator()
        interval_started = time.perf_counter()
        interval_tokens_local = 0
        last_save_time = time.monotonic()
        last_heartbeat = 0.0
        last_checkpoint_path: Optional[Path] = resume_checkpoint
        stop_training = False
        preempted = False

        while state.global_step < total_steps:
            if config.train.max_steps <= 0 and state.epoch >= config.train.epochs:
                break
            train_sampler.set_epoch(state.epoch, state.next_batch_in_epoch)
            iterator = iter(train_loader)
            batch_cursor = state.next_batch_in_epoch
            consumed_any = False

            for window in _iter_windows(
                iterator,
                config.train.gradient_accumulation_steps,
            ):
                consumed_any = True
                window_start = batch_cursor
                batch_cursor += len(window)
                if gradient_offload_receipt is not None:
                    _start_gradient_accumulation_offload_window(
                        gradient_offload_receipt,
                        global_step=state.global_step,
                        batch_start=window_start,
                        microbatch_count=len(window),
                    )
                    if gradient_offload_receipt_path is None:
                        raise RuntimeError(
                            "CPU gradient accumulation receipt path is unavailable."
                        )
                    _write_gradient_accumulation_offload_receipt(
                        gradient_offload_receipt_path,
                        gradient_offload_receipt,
                    )
                if gradient_accumulation_offload_enabled and len(window) > 1:
                    if active_gradient_accumulator is not None:
                        raise RuntimeError(
                            "A prior CPU gradient accumulation window is still active."
                        )
                    active_gradient_accumulator = _CPUGradientAccumulator(
                        gradient_offload_parameters,
                        require_cuda=True,
                        merge_device=(
                            "cpu"
                            if config.train.gradient_accumulation_offload
                            == "cpu_accumulate"
                            else "cuda"
                        ),
                    )
                current_induction = induction_status(
                    config.workspace,
                    config.induction,
                    state.global_step,
                    total_steps,
                )
                current_workspace_weight = current_induction.weight
                functional_runtime_route = bool(
                    config.functional.enabled
                    and config.functional.route_mode == "deferred"
                    and config.functional.injection_scale != 0.0
                )
                bypass_workspace = bool(
                    not functional_runtime_route
                    and current_workspace_weight == 0.0
                    and config.workspace.logit_residual_scale == 0.0
                    and (
                        not config.induction.enabled
                        or config.induction.bypass_workspace_when_inactive
                    )
                )
                local_window_tokens = sum(
                    batch_supervised_token_count(batch) for batch in window
                )
                global_window_tokens = context.all_reduce_sum_int(local_window_tokens)
                if global_window_tokens <= 0:
                    raise RuntimeError("Accumulation window contains no supervised tokens.")
                local_counterfactual_tokens = (
                    sum(batch_counterfactual_token_count(batch) for batch in window)
                    if config.functional.counterfactual_weight > 0.0
                    else 0
                )
                global_counterfactual_tokens = context.all_reduce_sum_int(
                    local_counterfactual_tokens
                )
                local_stability_items = (
                    sum(batch_stability_item_count(batch) for batch in window)
                    if config.functional.stability_weight > 0.0
                    else 0
                )
                global_stability_items = context.all_reduce_sum_int(
                    local_stability_items
                )
                if (
                    config.functional.counterfactual_weight > 0.0
                    and global_counterfactual_tokens <= 0
                ):
                    raise RuntimeError(
                        "Counterfactual objective is active but the window has no affected query."
                    )
                if (
                    config.functional.stability_weight > 0.0
                    and global_stability_items <= 0
                ):
                    raise RuntimeError(
                        "Stability objective is active but the window has no unaffected query."
                    )

                window_accumulator = MetricAccumulator()
                window_failed = False
                optimizer.zero_grad(set_to_none=True)

                for micro_index, raw_batch in enumerate(window):
                    batch = move_batch_to_device(raw_batch, context.device)
                    is_last_microbatch = micro_index + 1 == len(window)
                    sync_context = (
                        contextlib.nullcontext()
                        if is_last_microbatch or not context.enabled
                        else training_model.no_sync()  # type: ignore[attr-defined]
                    )
                    spectral_every = int(config.workspace.spectral_every)
                    compute_spectral = (
                        current_workspace_weight > 0.0
                        and spectral_every > 0
                        and state.global_step % spectral_every == 0
                        and micro_index == 0
                    )

                    if (
                        context.is_main
                        and config.train.log_memory
                        and context.device.type == "cuda"
                    ):
                        _write_jsonl(
                            microbatch_memory_path,
                            {
                                "event": "pre_forward",
                                "peak_scope": "run_since_process_start",
                                "run_id": state.run_id,
                                "step": state.global_step,
                                "microbatch_index": micro_index,
                                "accumulation_window_size": len(window),
                                **_memory_metrics(context.device),
                            },
                        )

                    with sync_context:
                        with autocast_context(context.device, precision):
                            output = training_model(
                                input_ids=batch["input_ids"],
                                attention_mask=batch["attention_mask"],
                                labels=batch["labels"],
                                prompt_mask=batch["prompt_mask"],
                                context_mask=batch.get("context_mask"),
                                query_mask=batch.get("query_mask"),
                                example_group_ids=batch.get("example_group_ids"),
                                world_group_ids=batch.get("world_group_ids"),
                                counterfactual_group_ids=batch.get(
                                    "counterfactual_group_ids"
                                ),
                                answer_classes=batch.get("answer_classes"),
                                **bridge_batch_kwargs(batch),
                                **functional_batch_kwargs(batch),
                                compute_workspace_loss=current_workspace_weight > 0.0,
                                compute_spectral=compute_spectral,
                                bypass_workspace=bypass_workspace,
                                rng_streams=(
                                    make_rng_streams(
                                        config.attribution,
                                        base_seed=config.train.seed,
                                        rank=context.rank,
                                        global_step=state.global_step,
                                        microbatch_index=micro_index,
                                    )
                                    if config.attribution.isolate_rng_streams
                                    else None
                                ),
                            )
                            task_nll_sum = output["task_nll_sum"]
                            if task_nll_sum is None:
                                raise RuntimeError("Training requires task_nll_sum.")
                            task_objective = (
                                task_nll_sum
                                * float(context.world_size)
                                / float(global_window_tokens)
                            )
                            workspace_objective = (
                                current_workspace_weight
                                * output["workspace_loss"]
                                / float(len(window))
                            )
                            counterfactual_objective = task_objective.detach() * 0.0
                            counterfactual_sum = output.get("counterfactual_nll_sum")
                            if (
                                config.functional.counterfactual_weight > 0.0
                                and isinstance(counterfactual_sum, torch.Tensor)
                            ):
                                counterfactual_objective = (
                                    config.functional.counterfactual_weight
                                    * counterfactual_sum
                                    * float(context.world_size)
                                    / float(global_counterfactual_tokens)
                                )
                            stability_objective = task_objective.detach() * 0.0
                            stability_sum = output.get("stability_kl_sum")
                            if (
                                config.functional.stability_weight > 0.0
                                and isinstance(stability_sum, torch.Tensor)
                            ):
                                stability_objective = (
                                    config.functional.stability_weight
                                    * stability_sum
                                    * float(context.world_size)
                                    / float(global_stability_items)
                                )
                            objective = (
                                task_objective
                                + workspace_objective
                                + counterfactual_objective
                                + stability_objective
                            )

                        finite = bool(torch.isfinite(objective.detach()).item())
                        finite = context.all_true(finite)
                        if not finite:
                            window_failed = True

                        _release_unconsumed_training_logits(output)
                        if (
                            context.is_main
                            and config.train.log_memory
                            and context.device.type == "cuda"
                        ):
                            _write_jsonl(
                                microbatch_memory_path,
                                {
                                    "event": "pre_backward",
                                    "peak_scope": "run_since_process_start",
                                    "run_id": state.run_id,
                                    "step": state.global_step,
                                    "microbatch_index": micro_index,
                                    "accumulation_window_size": len(window),
                                    **_memory_metrics(context.device),
                                },
                            )

                        # DDP requires every forward to be paired with a backward.
                        # Once a window is poisoned, run a zero-gradient surrogate
                        # through the remaining microbatches so the reducer reaches
                        # its final synchronized backward without updating weights.
                        if window_failed:
                            safe_objective = torch.where(
                                torch.isfinite(objective),
                                objective * 0.0,
                                torch.zeros_like(objective),
                            )
                            scaler.scale(safe_objective).backward()
                        else:
                            scaler.scale(objective).backward()

                        if (
                            context.is_main
                            and config.train.log_memory
                            and context.device.type == "cuda"
                        ):
                            _write_jsonl(
                                microbatch_memory_path,
                                {
                                    "event": "post_backward",
                                    "peak_scope": "run_since_process_start",
                                    "run_id": state.run_id,
                                    "step": state.global_step,
                                    "microbatch_index": micro_index,
                                    "accumulation_window_size": len(window),
                                    **_memory_metrics(context.device),
                                },
                            )

                        if active_gradient_accumulator is not None:
                            spill_statistics = active_gradient_accumulator.spill()
                            if (
                                gradient_offload_receipt is None
                                or gradient_offload_receipt_path is None
                            ):
                                raise RuntimeError(
                                    "CPU gradient accumulation receipt is unavailable."
                                )
                            _record_gradient_accumulation_offload_spill(
                                gradient_offload_receipt,
                                global_step=state.global_step,
                                microbatch_index=micro_index,
                                statistics=spill_statistics,
                            )
                            _write_gradient_accumulation_offload_receipt(
                                gradient_offload_receipt_path,
                                gradient_offload_receipt,
                            )
                            if (
                                context.is_main
                                and config.train.log_memory
                                and context.device.type == "cuda"
                            ):
                                _write_jsonl(
                                    microbatch_memory_path,
                                    {
                                        "event": (
                                            "post_gradient_accumulation_offload"
                                        ),
                                        "peak_scope": "run_since_process_start",
                                        "run_id": state.run_id,
                                        "step": state.global_step,
                                        "microbatch_index": micro_index,
                                        "accumulation_window_size": len(window),
                                        "gradient_accumulation_offload": (
                                            config.train.gradient_accumulation_offload
                                        ),
                                        **spill_statistics,
                                        **_memory_metrics(context.device),
                                    },
                                )

                    scalar = _scalar_workspace_metrics(output)
                    token_count = max(1.0, scalar["supervised_tokens"])
                    scalar["loss"] = (
                        scalar["task_loss"]
                        + current_workspace_weight * scalar["workspace_loss"]
                        + config.functional.counterfactual_weight
                        * scalar.get("counterfactual_loss", 0.0)
                        + config.functional.stability_weight
                        * scalar.get("stability_loss", 0.0)
                    )
                    scalar["workspace_weight"] = current_workspace_weight
                    scalar["induction_active"] = float(current_induction.active)
                    scalar["induction_progress"] = current_induction.progress
                    scalar["workspace_bypassed"] = float(bypass_workspace)
                    window_accumulator.add(
                        scalar,
                        weights={
                            "task_loss": token_count,
                            "loss": token_count,
                        },
                    )
                    interval_tokens_local += int(token_count)

                if active_gradient_accumulator is not None:
                    if window_failed:
                        active_gradient_accumulator.discard()
                        offload_window_statistics = (
                            active_gradient_accumulator.statistics()
                        )
                        active_gradient_accumulator = None
                        offload_window_restored = False
                    else:
                        active_gradient_accumulator.restore()
                        offload_window_statistics = (
                            active_gradient_accumulator.statistics()
                        )
                        active_gradient_accumulator = None
                        offload_window_restored = True
                    if gradient_offload_receipt is None:
                        raise RuntimeError(
                            "CPU gradient accumulation receipt is unavailable."
                        )
                    _finish_gradient_accumulation_offload_window(
                        gradient_offload_receipt,
                        global_step=state.global_step,
                        statistics=offload_window_statistics,
                        restored=offload_window_restored,
                    )
                    if gradient_offload_receipt_path is None:
                        raise RuntimeError(
                            "CPU gradient accumulation receipt path is unavailable."
                        )
                    _write_gradient_accumulation_offload_receipt(
                        gradient_offload_receipt_path,
                        gradient_offload_receipt,
                    )
                elif gradient_offload_receipt is not None:
                    _finish_gradient_accumulation_offload_window(
                        gradient_offload_receipt,
                        global_step=state.global_step,
                        statistics=None,
                        restored=False,
                        single_microbatch=True,
                    )
                    if gradient_offload_receipt_path is None:
                        raise RuntimeError(
                            "CPU gradient accumulation receipt path is unavailable."
                        )
                    _write_gradient_accumulation_offload_receipt(
                        gradient_offload_receipt_path,
                        gradient_offload_receipt,
                    )

                state.next_batch_in_epoch = batch_cursor
                if batch_cursor >= train_sampler.full_batches_per_epoch:
                    state.epoch += 1
                    state.next_batch_in_epoch = 0

                if window_failed:
                    optimizer.zero_grad(set_to_none=True)
                    state.nonfinite_skips += 1
                    message = {
                        "event": "nonfinite_loss",
                        "step": state.global_step,
                        "epoch": state.epoch,
                        "batch_start": window_start,
                        "nonfinite_skips": state.nonfinite_skips,
                        "time": time.time(),
                    }
                    if context.is_main:
                        _write_jsonl(metrics_path, message)
                    must_stop = (
                        config.train.nonfinite_policy == "stop"
                        or state.nonfinite_skips > config.train.max_nonfinite_skips
                    )
                    must_stop = context.any_true(must_stop)
                    if must_stop:
                        save_bundle(
                            output_dir / f"checkpoint-{state.global_step}",
                            model=training_model,
                            tokenizer=tokenizer,
                            config=config,
                            global_step=state.global_step,
                            optimizer=optimizer,
                            scheduler=scheduler,
                            scaler=scaler,
                            run_state=state,
                            sampler_state={
                                "epoch": state.epoch,
                                "start_batch": state.next_batch_in_epoch,
                            },
                            data_fingerprint=train_fingerprint,
                            base_update_coverage=base_update_coverage,
                            distributed=context,
                        )
                        raise FloatingPointError("Non-finite training objective detected.")
                    continue

                scaler.unscale_(optimizer)
                clip_metrics = clip_gradients(
                    raw_model,
                    config.train,
                    config.attribution,
                )
                grad_norm = clip_metrics["grad_norm_tensor"]
                gradients_finite = context.all_true(
                    bool(torch.isfinite(grad_norm.detach()).item())
                )
                if not gradients_finite:
                    # GradScaler tracks the unscale result internally. Let it
                    # consume the found-inf state so the next iteration starts
                    # clean; the optimizer step is skipped by GradScaler.
                    if bool(getattr(scaler, "is_enabled", lambda: False)()):
                        scaler.step(optimizer)
                        scaler.update()
                    optimizer.zero_grad(set_to_none=True)
                    state.nonfinite_skips += 1
                    if context.is_main:
                        _write_jsonl(
                            metrics_path,
                            {
                                "event": "nonfinite_gradient",
                                "step": state.global_step,
                                "epoch": state.epoch,
                                "batch_start": window_start,
                                "nonfinite_skips": state.nonfinite_skips,
                                "time": time.time(),
                            },
                        )
                    must_stop = context.any_true(
                        config.train.nonfinite_policy == "stop"
                        or state.nonfinite_skips > config.train.max_nonfinite_skips
                    )
                    if must_stop:
                        last_checkpoint_path = save_bundle(
                            output_dir / f"checkpoint-{state.global_step}",
                            model=training_model,
                            tokenizer=tokenizer,
                            config=config,
                            global_step=state.global_step,
                            optimizer=optimizer,
                            scheduler=scheduler,
                            scaler=scaler,
                            run_state=state,
                            sampler_state={
                                "epoch": state.epoch,
                                "start_batch": state.next_batch_in_epoch,
                            },
                            data_fingerprint=train_fingerprint,
                            base_update_coverage=base_update_coverage,
                            distributed=context,
                        )
                        raise FloatingPointError("Non-finite gradient norm detected.")
                    continue

                step_learning_rates = _optimizer_learning_rates(optimizer)
                step_base_lr = float(step_learning_rates.get("lr_base", 0.0))
                step_workspace_lr = float(
                    step_learning_rates.get("lr_workspace", 0.0)
                )
                previous_scale = float(scaler.get_scale())
                scaler.step(optimizer)
                scaler.update()
                new_scale = float(scaler.get_scale())
                scaler_skipped = precision == "fp16" and new_scale < previous_scale
                if (
                    not scaler_skipped
                    and config.model.train_mode == "full"
                    and step_base_lr > 0.0
                    and base_update_coverage is None
                ):
                    base_update_coverage = base_update_coverage_report(
                        raw_model,
                        optimizer,
                        train_mode=config.model.train_mode,
                        global_clip_grad_norm=grad_norm,
                        optimizer_step_performed=True,
                        optimizer_step_skipped=False,
                    )
                    if context.is_main:
                        _atomic_write_json(
                            output_dir / "base_update_coverage.json",
                            base_update_coverage,
                        )
                    context.barrier()
                    require_base_update_coverage(base_update_coverage)
                optimizer.zero_grad(set_to_none=True)
                if scaler_skipped:
                    state.optimizer_steps_skipped += 1
                    continue

                scheduler.step()
                state.global_step += 1
                state.total_supervised_tokens += global_window_tokens
                state.auxiliary_dose += float(current_workspace_weight)
                state.lr_weighted_auxiliary_dose += (
                    float(current_workspace_weight) * step_base_lr
                )
                state.clip_adjusted_base_auxiliary_exposure += (
                    float(current_workspace_weight)
                    * step_base_lr
                    * float(clip_metrics["base_clip_coefficient"])
                )
                state.clip_adjusted_workspace_auxiliary_exposure += (
                    float(current_workspace_weight)
                    * step_workspace_lr
                    * float(clip_metrics["workspace_clip_coefficient"])
                )
                if current_workspace_weight > 0.0:
                    state.induction_steps += 1
                state.last_induction_phase = current_induction.phase
                log_accumulator.merge(window_accumulator.state_dict())

                due_alignment = bool(
                    config.assays.gradient_alignment_every > 0
                    and state.global_step
                    % config.assays.gradient_alignment_every
                    == 0
                )
                if due_alignment:
                    context.barrier()
                    if context.is_main:
                        alignment = compute_gradient_alignment(
                            raw_model,
                            window[0],
                            device=context.device,
                            precision=precision,
                            attribution=config.attribution,
                            assays=config.assays,
                            seed=deterministic_stream_seed(
                                config.train.seed,
                                context.rank,
                                state.global_step,
                                0,
                                config.attribution.assay_seed_offset,
                            ),
                        )
                        alignment_record = {
                            "event": "gradient_alignment",
                            "run_id": state.run_id,
                            "step": state.global_step,
                            "induction_phase": current_induction.phase,
                            "auxiliary_dose": state.auxiliary_dose,
                            **alignment,
                        }
                        _write_jsonl(
                            output_dir / "gradient_alignment.jsonl",
                            alignment_record,
                        )
                        _write_jsonl(metrics_path, alignment_record)
                    context.barrier()
                    training_model.train()
                    if config.model.train_mode == "workspace_only":
                        raw_model.base_model.eval()

                now = time.monotonic()
                signal_requested = context.any_true(controller.requested)
                due_log = state.global_step % max(1, config.train.log_every) == 0
                if due_log:
                    elapsed = max(time.perf_counter() - interval_started, 1e-6)
                    log_metrics = _distributed_accumulator_mean(
                        log_accumulator,
                        context,
                    )
                    global_interval_tokens = context.all_reduce_sum_int(
                        interval_tokens_local
                    )
                    log_metrics.update(_optimizer_learning_rates(optimizer))
                    log_metrics["grad_norm"] = float(clip_metrics["grad_norm"])
                    log_metrics["base_grad_norm"] = float(clip_metrics["base_grad_norm"])
                    log_metrics["workspace_grad_norm"] = float(
                        clip_metrics["workspace_grad_norm"]
                    )
                    log_metrics["base_clip_coefficient"] = float(
                        clip_metrics["base_clip_coefficient"]
                    )
                    log_metrics["workspace_clip_coefficient"] = float(
                        clip_metrics["workspace_clip_coefficient"]
                    )
                    log_metrics["auxiliary_dose"] = state.auxiliary_dose
                    log_metrics.update(dose_ledger(state))
                    log_metrics["tokens_per_second"] = global_interval_tokens / elapsed
                    log_metrics["epoch"] = state.epoch + (
                        state.next_batch_in_epoch
                        / max(train_sampler.full_batches_per_epoch, 1)
                    )
                    log_metrics["step"] = state.global_step
                    log_metrics["perplexity"] = math.exp(
                        min(log_metrics.get("task_loss", 0.0), 20.0)
                    )
                    if config.train.log_memory:
                        log_metrics.update(_memory_metrics(context.device))
                    if context.is_main:
                        print(_format_metrics("train", state.global_step, log_metrics))
                        _write_jsonl(
                            metrics_path,
                            {
                                "split": "train",
                                "run_id": state.run_id,
                                "induction_phase": current_induction.phase,
                                **log_metrics,
                            },
                        )
                    log_accumulator.reset()
                    interval_tokens_local = 0
                    interval_started = time.perf_counter()

                next_induction = induction_status(
                    config.workspace,
                    config.induction,
                    state.global_step,
                    total_steps,
                )
                phase_changed = next_induction.phase != current_induction.phase

                eval_metrics: Optional[dict[str, float]] = None
                due_eval = (
                    eval_dataset is not None
                    and config.train.eval_every > 0
                    and state.global_step % config.train.eval_every == 0
                )
                if due_eval:
                    context.barrier()
                    if context.is_main:
                        assert eval_loader is not None
                        eval_metrics = evaluate(
                            raw_model,
                            eval_loader,
                            device=context.device,
                            precision=precision,
                            workspace_loss_weight=next_induction.weight,
                            max_batches=config.train.eval_batches,
                            compute_spectral=config.workspace.spectral_every != 0,
                            compute_workspace_loss=config.workspace.loss_weight > 0.0,
                        )
                        eval_metrics["step"] = state.global_step
                        eval_metrics["auxiliary_dose"] = state.auxiliary_dose
                        eval_metrics.update(dose_ledger(state))
                        print(_format_metrics("eval", state.global_step, eval_metrics))
                        _write_jsonl(
                            metrics_path,
                            {
                                "split": "eval",
                                "run_id": state.run_id,
                                "induction_phase": next_induction.phase,
                                **eval_metrics,
                            },
                        )
                        due_amputation = bool(
                            config.assays.amputation_eval
                            and config.assays.amputation_eval_every > 0
                            and state.global_step
                            % config.assays.amputation_eval_every
                            == 0
                        )
                        if due_amputation:
                            amputated = evaluate(
                                raw_model,
                                eval_loader,
                                device=context.device,
                                precision=precision,
                                workspace_loss_weight=0.0,
                                max_batches=config.train.eval_batches,
                                compute_spectral=False,
                                compute_workspace_loss=False,
                                bypass_workspace=True,
                            )
                            amputated["step"] = state.global_step
                            print(
                                _format_metrics(
                                    "eval-amputated", state.global_step, amputated
                                )
                            )
                            _write_jsonl(
                                metrics_path,
                                {
                                    "split": "eval-amputated",
                                    "run_id": state.run_id,
                                    "induction_phase": next_induction.phase,
                                    **amputated,
                                },
                            )
                    eval_metrics = context.broadcast_object(eval_metrics, source=0)
                    context.barrier()
                    training_model.train()
                    if config.model.train_mode == "workspace_only":
                        raw_model.base_model.eval()

                improved = False
                if eval_metrics is not None and config.train.best_metric in eval_metrics:
                    value = float(eval_metrics[config.train.best_metric])
                    improved = _is_better(
                        value,
                        state.best_metric,
                        config.train.greater_is_better,
                    )
                    if improved:
                        state.best_metric = value
                        state.best_step = state.global_step

                due_step_save = (
                    config.train.save_every > 0
                    and state.global_step % config.train.save_every == 0
                )
                due_time_save = (
                    config.train.save_every_minutes > 0
                    and now - last_save_time
                    >= config.train.save_every_minutes * 60.0
                )
                due_best_save = bool(config.train.save_best and improved)
                due_phase_save = bool(
                    config.induction.enabled
                    and config.induction.save_phase_boundaries
                    and phase_changed
                )
                if (
                    due_step_save
                    or due_time_save
                    or due_best_save
                    or due_phase_save
                    or signal_requested
                ):
                    checkpoint = output_dir / f"checkpoint-{state.global_step}"
                    last_checkpoint_path = save_bundle(
                        checkpoint,
                        model=training_model,
                        tokenizer=tokenizer,
                        config=config,
                        global_step=state.global_step,
                        optimizer=optimizer,
                        scheduler=scheduler,
                        scaler=scaler,
                        run_state=state,
                        sampler_state={
                            "epoch": state.epoch,
                            "start_batch": state.next_batch_in_epoch,
                        },
                        data_fingerprint=train_fingerprint,
                        base_update_coverage=base_update_coverage,
                        distributed=context,
                    )
                    last_save_time = time.monotonic()
                    if context.is_main:
                        if due_phase_save:
                            _atomic_write_json(
                                output_dir
                                / f"phase-boundary-step-{state.global_step}.json",
                                {
                                    "checkpoint": checkpoint.name,
                                    "step": state.global_step,
                                    "from": current_induction.phase,
                                    "to": next_induction.phase,
                                    "auxiliary_dose": state.auxiliary_dose,
                                    "dose_ledger": dose_ledger(state),
                                },
                            )
                        if improved:
                            _atomic_write_json(
                                output_dir / "best_checkpoint.json",
                                {
                                    "path": checkpoint.name,
                                    "step": state.global_step,
                                    "metric": config.train.best_metric,
                                    "value": state.best_metric,
                                },
                            )
                        prune_checkpoints(
                            output_dir,
                            config.train.keep_last_checkpoints,
                        )
                    context.barrier()

                if (
                    config.train.heartbeat_every_seconds == 0
                    or now - last_heartbeat >= config.train.heartbeat_every_seconds
                    or due_log
                ):
                    _write_heartbeat(
                        output_dir,
                        state,
                        status="preempting" if signal_requested else "running",
                        context=context,
                        extra={"last_checkpoint_unix": time.time() if due_step_save else None},
                    )
                    last_heartbeat = now

                if signal_requested:
                    preempted = True
                    stop_training = True
                    break
                if state.global_step >= total_steps:
                    stop_training = True
                    break

            if stop_training:
                break
            if not consumed_any or state.next_batch_in_epoch == 0:
                # The epoch was exhausted and RunState was already advanced.
                continue

        if log_accumulator.sums:
            elapsed = max(time.perf_counter() - interval_started, 1e-6)
            log_metrics = _distributed_accumulator_mean(log_accumulator, context)
            global_interval_tokens = context.all_reduce_sum_int(interval_tokens_local)
            log_metrics.update(_optimizer_learning_rates(optimizer))
            log_metrics["tokens_per_second"] = global_interval_tokens / elapsed
            log_metrics["step"] = state.global_step
            if context.is_main:
                print(_format_metrics("train", state.global_step, log_metrics))
                _write_jsonl(
                    metrics_path,
                    {"split": "train", "run_id": state.run_id, **log_metrics},
                )

        if preempted:
            # The signal path checkpoints at the preceding optimizer boundary.
            # Avoid a second, expensive "final" serialization during a short
            # scheduler/preemption grace period.
            if last_checkpoint_path is None:
                last_checkpoint_path = save_bundle(
                    output_dir / f"checkpoint-{state.global_step}",
                    model=training_model,
                    tokenizer=tokenizer,
                    config=config,
                    global_step=state.global_step,
                    optimizer=optimizer,
                    scheduler=scheduler,
                    scaler=scaler,
                    run_state=state,
                    sampler_state={
                        "epoch": state.epoch,
                        "start_batch": state.next_batch_in_epoch,
                    },
                    data_fingerprint=train_fingerprint,
                    base_update_coverage=base_update_coverage,
                    distributed=context,
                )
            if gradient_offload_receipt is not None:
                if active_gradient_accumulator is not None:
                    raise RuntimeError(
                        "CPU gradient accumulation preempted with an active accumulator."
                    )
                _mark_gradient_accumulation_offload_terminal(
                    gradient_offload_receipt,
                    status="preempted",
                    global_step=state.global_step,
                    checkpoint=last_checkpoint_path,
                    output_dir=output_dir,
                )
                if gradient_offload_receipt_path is None:
                    raise RuntimeError(
                        "CPU gradient accumulation receipt path is unavailable."
                    )
                _write_gradient_accumulation_offload_receipt(
                    gradient_offload_receipt_path,
                    gradient_offload_receipt,
                )
            _write_heartbeat(
                output_dir,
                state,
                status="preempted",
                context=context,
                extra={"resume_path": str(last_checkpoint_path)},
            )
            return last_checkpoint_path

        if eval_dataset is not None:
            context.barrier()
            final_eval: Optional[dict[str, float]] = None
            if context.is_main:
                assert eval_loader is not None
                final_status = induction_status(
                    config.workspace,
                    config.induction,
                    state.global_step,
                    total_steps,
                )
                final_eval = evaluate(
                    raw_model,
                    eval_loader,
                    device=context.device,
                    precision=precision,
                    workspace_loss_weight=final_status.weight,
                    max_batches=config.train.eval_batches,
                    compute_spectral=config.workspace.spectral_every != 0,
                    compute_workspace_loss=config.workspace.loss_weight > 0.0,
                )
                final_eval["step"] = state.global_step
                final_eval["auxiliary_dose"] = state.auxiliary_dose
                final_eval.update(dose_ledger(state))
                print(_format_metrics("eval-final", state.global_step, final_eval))
                _write_jsonl(
                    metrics_path,
                    {
                        "split": "eval-final",
                        "run_id": state.run_id,
                        "induction_phase": final_status.phase,
                        **final_eval,
                    },
                )
                if config.assays.amputation_eval:
                    amputated_eval = evaluate(
                        raw_model,
                        eval_loader,
                        device=context.device,
                        precision=precision,
                        workspace_loss_weight=0.0,
                        max_batches=config.train.eval_batches,
                        compute_spectral=False,
                        compute_workspace_loss=False,
                        bypass_workspace=True,
                    )
                    amputated_eval["step"] = state.global_step
                    print(
                        _format_metrics(
                            "eval-final-amputated", state.global_step, amputated_eval
                        )
                    )
                    _write_jsonl(
                        metrics_path,
                        {
                            "split": "eval-final-amputated",
                            "run_id": state.run_id,
                            "induction_phase": final_status.phase,
                            **amputated_eval,
                        },
                    )
                    _atomic_write_json(
                        output_dir / "amputation_report.json",
                        {
                            "step": state.global_step,
                            "induction_phase": final_status.phase,
                            "auxiliary_dose": state.auxiliary_dose,
                            "dose_ledger": dose_ledger(state),
                            "full": final_eval,
                            "amputated": amputated_eval,
                            "task_loss_delta_full_minus_amputated": (
                                float(final_eval["task_loss"])
                                - float(amputated_eval["task_loss"])
                            ),
                        },
                    )
            context.barrier()

        if gradient_offload_receipt is not None:
            if active_gradient_accumulator is not None:
                raise RuntimeError(
                    "CPU gradient accumulation completed with an active accumulator."
                )
            if gradient_offload_receipt.get("active_window") is not None:
                raise RuntimeError(
                    "CPU gradient accumulation completed with an active receipt window."
                )
            if int(gradient_offload_receipt["live_cpu_buffer_count"]) != 0 or int(
                gradient_offload_receipt["live_cpu_buffer_bytes"]
            ) != 0:
                raise RuntimeError(
                    "CPU gradient accumulation completed with live host buffers."
                )
            if int(gradient_offload_receipt["windows_restored"]) < 1:
                raise RuntimeError(
                    "CPU gradient accumulation was configured but no multi-microbatch "
                    "window executed the spill/restore path."
                )

        final_path = save_bundle(
            output_dir / "final",
            model=training_model,
            tokenizer=tokenizer,
            config=config,
            global_step=state.global_step,
            optimizer=optimizer,
            scheduler=scheduler,
            scaler=scaler,
            run_state=state,
            sampler_state={
                "epoch": state.epoch,
                "start_batch": state.next_batch_in_epoch,
            },
            data_fingerprint=train_fingerprint,
            base_update_coverage=base_update_coverage,
            distributed=context,
        )
        if gradient_offload_receipt is not None:
            _mark_gradient_accumulation_offload_terminal(
                gradient_offload_receipt,
                status="completed",
                global_step=state.global_step,
            )
            if gradient_offload_receipt_path is None:
                raise RuntimeError(
                    "CPU gradient accumulation receipt path is unavailable."
                )
            _write_gradient_accumulation_offload_receipt(
                gradient_offload_receipt_path,
                gradient_offload_receipt,
            )
        _write_heartbeat(
            output_dir,
            state,
            status="completed",
            context=context,
            extra={"final_path": str(final_path)},
        )
        return final_path

    except Exception as exc:
        try:
            failed_window_statistics: Optional[dict[str, int]] = None
            if active_gradient_accumulator is not None:
                active_gradient_accumulator.discard()
                failed_window_statistics = active_gradient_accumulator.statistics()
                active_gradient_accumulator = None
            if (
                gradient_offload_receipt is not None
                and gradient_offload_receipt_path is not None
            ):
                try:
                    current_segment = _current_gradient_offload_segment(
                        gradient_offload_receipt
                    )
                    if current_segment.get("status") in {"initialized", "running"}:
                        gradient_offload_receipt["failed_active_window"] = (
                            copy.deepcopy(
                                gradient_offload_receipt.get("active_window")
                            )
                        )
                        gradient_offload_receipt["active_window"] = None
                        gradient_offload_receipt["live_cpu_buffer_count"] = 0
                        gradient_offload_receipt["live_cpu_buffer_bytes"] = 0
                        gradient_offload_receipt["last_error_type"] = type(exc).__name__
                        gradient_offload_receipt["last_error"] = str(exc)
                        if failed_window_statistics is not None:
                            gradient_offload_receipt["failed_window_statistics"] = (
                                failed_window_statistics
                            )
                        _mark_gradient_accumulation_offload_terminal(
                            gradient_offload_receipt,
                            status="failed",
                            global_step=int(
                                gradient_offload_receipt.get(
                                    "last_observed_global_step", 0
                                )
                            ),
                        )
                        _write_gradient_accumulation_offload_receipt(
                            gradient_offload_receipt_path,
                            gradient_offload_receipt,
                        )
                except Exception:
                    # Preserve the training failure as the primary exception.
                    pass
            if context.is_main:
                output_dir = Path(config.train.output_dir)
                output_dir.mkdir(parents=True, exist_ok=True)
                _atomic_write_json(
                    output_dir / "FAILED.json",
                    {
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "time": time.time(),
                        "hostname": socket.gethostname(),
                        "pid": os.getpid(),
                        "allocator": allocator_runtime_environment(),
                    },
                )
        finally:
            raise
    finally:
        try:
            if active_gradient_accumulator is not None:
                active_gradient_accumulator.discard()
        finally:
            controller.restore()
            context.close()


# =============================================================================
# Bundle loading and generation
# =============================================================================


def _load_saved_base_model(
    checkpoint: Path,
    config: ExperimentConfig,
    *,
    is_trainable: bool = False,
    fallback_model_config: Optional[ModelConfig] = None,
) -> nn.Module:
    base_dir = checkpoint / "base_model"

    if config.model.train_mode == "lora":
        if not base_dir.exists():
            raise FileNotFoundError(f"Missing LoRA adapter directory: {base_dir}")
        base_config = fallback_model_config or config.model
        base = _load_hf_model(base_config)
        try:
            from peft import PeftModel
        except ImportError as exc:
            raise RuntimeError("Loading a LoRA bundle requires peft.") from exc
        return PeftModel.from_pretrained(
            base,
            base_dir,
            is_trainable=is_trainable,
        )

    if not base_dir.exists():
        reference = checkpoint / "base_reference.json"
        if not reference.exists():
            raise FileNotFoundError(
                f"Missing both base model directory and reference in {checkpoint}."
            )
        base_config = fallback_model_config or config.model
        return _load_hf_model(base_config)

    saved_config = dataclasses.replace(
        config.model,
        name_or_path=str(base_dir),
        revision="main",
        train_mode="full",
        local_files_only=True,
        gradient_checkpointing=False,
    )
    return _load_hf_model(saved_config)


def load_bundle(
    checkpoint: str | os.PathLike[str],
    *,
    device: Optional[torch.device] = None,
) -> tuple[LatentWorkspaceCausalLM, Any, ExperimentConfig]:
    checkpoint_path = Path(checkpoint).expanduser().resolve()
    config_path = checkpoint_path / "experiment_config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Missing experiment_config.json in {checkpoint_path}")

    config = ExperimentConfig.from_json(config_path)
    _, AutoTokenizer = _import_transformers()
    tokenizer = AutoTokenizer.from_pretrained(
        checkpoint_path / "tokenizer",
        local_files_only=True,
    )
    if getattr(tokenizer, "pad_token_id", None) is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    base_model = _load_saved_base_model(checkpoint_path, config, is_trainable=False)
    wrapper = LatentWorkspaceCausalLM(
        base_model=base_model,
        hidden_dim=infer_hidden_size(base_model),
        vocab_size=infer_vocab_size(base_model),
        config=config.workspace,
        functional_config=config.functional,
        hidden_capture=config.model.hidden_capture,
        base_activation_offload=config.train.base_activation_offload,
    )
    custom_state = _torch_load(
        checkpoint_path / "workspace_state.pt",
        weights_only=True,
    )
    wrapper.load_custom_state_dict(custom_state)
    if device is not None:
        wrapper.to(device)
    wrapper.eval()
    return wrapper, tokenizer, config



def _read_jsonl_objects(files: Sequence[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in _expand_file_patterns(files):
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise TypeError(f"{path}:{line_number} is not a JSON object.")
                records.append(value)
    return records



def audit_counterfactual_dataset(
    files: Sequence[str],
    tokenizer: Any,
    data_config: DataConfig,
) -> dict[str, Any]:
    """Fail-closed semantic audit for matched counterfactual twin records."""
    records = _read_jsonl_objects(files)
    groups: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    warnings: list[str] = []

    # The v8 task is intentionally one-token and answer-critical. Merely
    # counting one supervised position is insufficient: two choice strings
    # could alias to the same token, or the encoded response could disagree
    # with metadata.answer_class. Fail closed before any expensive run.
    choice_token_sequences = {
        choice: list(tokenizer.encode(choice, add_special_tokens=False))
        for choice in ("0", "1")
    }
    for choice, token_ids in choice_token_sequences.items():
        if len(token_ids) != 1:
            errors.append(
                f"choice {choice!r}: expected exactly one tokenizer token, "
                f"found {token_ids}"
            )
    distinct_choice_token_ids = bool(
        all(len(ids) == 1 for ids in choice_token_sequences.values())
        and choice_token_sequences["0"][0] != choice_token_sequences["1"][0]
    )
    if not distinct_choice_token_ids:
        errors.append(
            "choice strings '0' and '1' must map to distinct single-token IDs"
        )

    label_counts: dict[int, int] = {}
    semantic_family_counts: dict[str, int] = {}
    query_label_counts: dict[str, dict[int, int]] = {}
    response_token_histogram: dict[int, int] = {}
    for index, record in enumerate(records):
        metadata = record.get("metadata", {})
        if not isinstance(metadata, Mapping):
            metadata = {}
        pair = metadata.get("counterfactual_pair_id")
        if pair is None:
            errors.append(f"record {index}: missing metadata.counterfactual_pair_id")
            pair = f"__missing_{index}"
        groups.setdefault(str(pair), []).append(record)
        try:
            label = int(metadata.get("answer_class", record.get("answer_index", -1)))
        except (TypeError, ValueError):
            label = -1
        label_counts[label] = label_counts.get(label, 0) + 1
        semantic_family = str(metadata.get("semantic_family", "unknown"))
        semantic_family_counts[semantic_family] = (
            semantic_family_counts.get(semantic_family, 0) + 1
        )
        query = str(record.get("query", ""))
        qcounts = query_label_counts.setdefault(query, {})
        qcounts[label] = qcounts.get(label, 0) + 1

    audited_pairs = 0
    for pair, twins in sorted(groups.items()):
        if len(twins) != 2:
            errors.append(f"pair {pair}: expected 2 records, found {len(twins)}")
            continue
        left, right = twins
        lm = left.get("metadata", {}) if isinstance(left.get("metadata"), Mapping) else {}
        rm = right.get("metadata", {}) if isinstance(right.get("metadata"), Mapping) else {}
        left_label = int(lm.get("answer_class", left.get("answer_index", -1)))
        right_label = int(rm.get("answer_class", right.get("answer_index", -1)))
        labels = {left_label, right_label}
        if labels != {0, 1}:
            errors.append(f"pair {pair}: labels must be {{0,1}}, found {sorted(labels)}")
        if int(left.get("answer_index", -1)) != left_label or int(
            right.get("answer_index", -1)
        ) != right_label:
            errors.append(f"pair {pair}: answer_index disagrees with answer_class")
        twin_sides = {int(lm.get("twin_side", -1)), int(rm.get("twin_side", -1))}
        if twin_sides != {0, 1}:
            errors.append(
                f"pair {pair}: twin_side must be {{0,1}}, found {sorted(twin_sides)}"
            )
        if str(lm.get("world_id", "")) == str(rm.get("world_id", "")):
            errors.append(f"pair {pair}: world_id must differ across twins")
        query_text = str(left.get("query", ""))
        expected_signature = hashlib.sha256(query_text.encode("utf-8")).hexdigest()
        if lm.get("query_signature") != expected_signature or rm.get(
            "query_signature"
        ) != expected_signature:
            errors.append(f"pair {pair}: query_signature mismatch")
        if str(left.get("query", "")) != str(right.get("query", "")):
            errors.append(f"pair {pair}: queries differ")
        if list(left.get("choices", [])) != ["0", "1"] or list(
            right.get("choices", [])
        ) != ["0", "1"]:
            errors.append(f"pair {pair}: choices must be fixed [0, 1]")
        if str(left.get("context", "")) == str(right.get("context", "")):
            errors.append(f"pair {pair}: contexts are identical")
        if str(left.get("response", "")) == str(right.get("response", "")):
            errors.append(f"pair {pair}: responses must be opposite")
        left_context_tokens = tokenizer.encode(str(left.get("context", "")), add_special_tokens=False)
        right_context_tokens = tokenizer.encode(str(right.get("context", "")), add_special_tokens=False)
        if len(left_context_tokens) != len(right_context_tokens):
            errors.append(f"pair {pair}: context token lengths differ")
        left_response_tokens = tokenizer.encode(str(left.get("response", "")), add_special_tokens=False)
        right_response_tokens = tokenizer.encode(str(right.get("response", "")), add_special_tokens=False)
        if len(left_response_tokens) != len(right_response_tokens):
            errors.append(f"pair {pair}: response token lengths differ")
        for side_name, record, metadata, token_ids in (
            ("left", left, lm, left_response_tokens),
            ("right", right, rm, right_response_tokens),
        ):
            try:
                label = int(metadata.get("answer_class", record.get("answer_index", -1)))
            except (TypeError, ValueError):
                label = -1
            expected = choice_token_sequences.get(str(label), [])
            if list(token_ids) != list(expected):
                errors.append(
                    f"pair {pair}: {side_name} response tokens {list(token_ids)} "
                    f"do not match answer_class={label} choice tokens {list(expected)}"
                )
        # Exercise the real collator contract, including truncation and masks.
        try:
            lf = encode_finetuning_record(left, tokenizer, data_config)
            rf = encode_finetuning_record(right, tokenizer, data_config)
            collator = CausalFineTuningCollator(tokenizer.pad_token_id, 1)
            batch = collator([lf, rf])
            prompt0 = batch["bridge_attention_mask"][0].bool() & batch["bridge_labels"][0].eq(-100)
            prompt1 = batch["bridge_attention_mask"][1].bool() & batch["bridge_labels"][1].eq(-100)
            q0 = batch["bridge_input_ids"][0][prompt0]
            q1 = batch["bridge_input_ids"][1][prompt1]
            c0 = batch["bridge_context_input_ids"][0][batch["bridge_context_attention_mask"][0].bool()]
            c1 = batch["bridge_context_input_ids"][1][batch["bridge_context_attention_mask"][1].bool()]
            if not torch.equal(q0, q1):
                errors.append(f"pair {pair}: deferred query branches differ")
            if torch.equal(c0, c1):
                errors.append(f"pair {pair}: deferred context branches are identical")
            supervised0 = int(batch["bridge_labels"][0].ne(-100).sum().item())
            supervised1 = int(batch["bridge_labels"][1].ne(-100).sum().item())
            response_token_histogram[supervised0] = (
                response_token_histogram.get(supervised0, 0) + 1
            )
            response_token_histogram[supervised1] = (
                response_token_histogram.get(supervised1, 0) + 1
            )
            if supervised0 == 0 or supervised1 == 0:
                errors.append(f"pair {pair}: response supervision vanished after truncation")
            if supervised0 != supervised1:
                errors.append(
                    f"pair {pair}: supervised answer token counts differ "
                    f"({supervised0} vs {supervised1})"
                )
            if supervised0 != 1 or supervised1 != 1:
                errors.append(
                    f"pair {pair}: v8 requires one answer-critical supervised token "
                    f"per row, found ({supervised0}, {supervised1})"
                )
            else:
                supervised_ids0 = batch["bridge_labels"][0][
                    batch["bridge_labels"][0].ne(-100)
                ].tolist()
                supervised_ids1 = batch["bridge_labels"][1][
                    batch["bridge_labels"][1].ne(-100)
                ].tolist()
                label0 = int(lm.get("answer_class", left.get("answer_index", -1)))
                label1 = int(rm.get("answer_class", right.get("answer_index", -1)))
                expected0 = choice_token_sequences.get(str(label0), [])
                expected1 = choice_token_sequences.get(str(label1), [])
                if supervised_ids0 != expected0:
                    errors.append(
                        f"pair {pair}: left collated supervised token "
                        f"{supervised_ids0} != expected {expected0}"
                    )
                if supervised_ids1 != expected1:
                    errors.append(
                        f"pair {pair}: right collated supervised token "
                        f"{supervised_ids1} != expected {expected1}"
                    )
        except Exception as exc:
            errors.append(f"pair {pair}: encoding failed: {exc}")
        audited_pairs += 1

    total = max(sum(label_counts.values()), 1)
    prior_ceiling = max(label_counts.values(), default=0) / total
    bayes_correct = 0
    for counts in query_label_counts.values():
        bayes_correct += max(counts.values(), default=0)
    query_only_bayes_ceiling = bayes_correct / total
    report = {
        "format": "latent-workspace-v8-counterfactual-audit-v1",
        "harness_version": __version__,
        "files": [str(path) for path in files],
        "records": len(records),
        "pairs": len(groups),
        "audited_pairs": audited_pairs,
        "label_counts": {str(k): v for k, v in sorted(label_counts.items())},
        "semantic_family_counts": {
            str(k): v for k, v in sorted(semantic_family_counts.items())
        },
        "prior_ceiling": prior_ceiling,
        "query_only_bayes_ceiling": query_only_bayes_ceiling,
        "response_token_count_histogram": {
            str(key): value for key, value in sorted(response_token_histogram.items())
        },
        "answer_only_supervision": not bool(data_config.add_eos),
        "choice_token_ids": {
            key: value for key, value in sorted(choice_token_sequences.items())
        },
        "distinct_choice_token_ids": distinct_choice_token_ids,
        "response_matches_answer_class": not any(
            "do not match answer_class" in error
            or "collated supervised token" in error
            for error in errors
        ),
        "single_token_answer_contract": bool(
            response_token_histogram
            and set(response_token_histogram) == {1}
            and sum(response_token_histogram.values()) == len(records)
        ),
        "errors": errors,
        "warnings": warnings,
        "passed": bool(
            not errors
            and audited_pairs == len(groups)
            and abs(prior_ceiling - 0.5) < 1e-12
            and abs(query_only_bayes_ceiling - 0.5) < 1e-12
        ),
    }
    return report


def _choice_feature(
    record: Mapping[str, Any],
    *,
    response: str,
    index: int,
    tokenizer: Any,
    data_config: DataConfig,
) -> dict[str, Any]:
    candidate = dict(record)
    candidate["response"] = response
    feature = encode_finetuning_record(candidate, tokenizer, data_config)
    feature["sample_index"] = int(index)
    feature["example_group_id"] = int(index)
    metadata = record.get("metadata", {})
    if not isinstance(metadata, Mapping):
        metadata = {}
    world_value = metadata.get("world_id", index)
    material = f"choice-assay::{world_value}".encode("utf-8")
    feature["world_group_id"] = int.from_bytes(
        hashlib.sha256(material).digest()[:8], byteorder="big", signed=False
    ) & ((1 << 63) - 1)
    try:
        feature["rank_distance"] = int(metadata.get("rank_distance", -1))
    except (TypeError, ValueError):
        feature["rank_distance"] = -1
    try:
        feature["answer_index"] = int(record.get("answer_index", -1))
    except (TypeError, ValueError):
        feature["answer_index"] = -1
    try:
        feature["answer_class"] = int(
            metadata.get("answer_class", feature["answer_index"])
        )
    except (TypeError, ValueError):
        feature["answer_class"] = -1
    try:
        feature["twin_side"] = int(metadata.get("twin_side", -1))
    except (TypeError, ValueError):
        feature["twin_side"] = -1
    pair_value = metadata.get("counterfactual_pair_id")
    if pair_value is None:
        feature["counterfactual_group_id"] = -(index + 1)
    else:
        pair_material = f"choice-assay::pair::{pair_value}".encode("utf-8")
        feature["counterfactual_group_id"] = int.from_bytes(
            hashlib.sha256(pair_material).digest()[:8],
            byteorder="big",
            signed=False,
        ) & ((1 << 63) - 1)
    return feature


def _choice_assay_batches(
    records: Sequence[Mapping[str, Any]],
    *,
    batch_size: int,
    require_counterfactual_pairs: bool,
) -> list[list[int]]:
    """Build deterministic candidate-scoring batches with twin coverage.

    The ordinary choice path can use contiguous chunks. Counterfactual memory
    replacement is only meaningful when both members of each twin pair occur in
    the same model call, so v8 packs exact pairs and at least two pairs per batch.
    """
    if not require_counterfactual_pairs:
        return [
            list(range(start, min(len(records), start + batch_size)))
            for start in range(0, len(records), batch_size)
        ]
    if batch_size < 4:
        raise ValueError(
            "Counterfactual choice evaluation requires batch_size >= 4."
        )
    by_pair: dict[str, list[int]] = {}
    for index, record in enumerate(records):
        metadata = record.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise ValueError(
                f"choice record {index} has non-object metadata"
            )
        pair_id = metadata.get("counterfactual_pair_id")
        if pair_id is None:
            raise ValueError(
                "counterfactual_twin choice evaluation requires every record "
                "to have metadata.counterfactual_pair_id"
            )
        by_pair.setdefault(str(pair_id), []).append(index)
    malformed = {key: value for key, value in by_pair.items() if len(value) != 2}
    if malformed:
        raise ValueError(
            "Every counterfactual choice pair must contain exactly two records; "
            f"malformed={list(malformed.items())[:4]}"
        )
    ordered_pairs = sorted(by_pair)
    pairs_per_batch = max(2, batch_size // 2)
    batches: list[list[int]] = []
    for start in range(0, len(ordered_pairs), pairs_per_batch):
        chunk = ordered_pairs[start : start + pairs_per_batch]
        if len(chunk) == 1 and batches:
            prior = batches.pop()
            moved = prior[-2:]
            prior = prior[:-2]
            if prior:
                batches.append(prior)
            batches.append(moved + by_pair[chunk[0]])
        else:
            batches.append([row for pair in chunk for row in by_pair[pair]])
    flattened = [row for batch in batches for row in batch]
    if sorted(flattened) != list(range(len(records))):
        raise RuntimeError(
            "Counterfactual choice batching lost or duplicated records."
        )
    return batches


@torch.no_grad()
def evaluate_choices_loaded(
    model: LatentWorkspaceCausalLM,
    tokenizer: Any,
    config: ExperimentConfig,
    *,
    device: torch.device,
    precision: str,
    intervention_modes: Sequence[str],
    intervention_seed: int,
) -> dict[str, Any]:
    records = _read_jsonl_objects(config.data.eval_files)
    maximum = int(config.assays.choice_eval.max_records)
    if maximum > 0:
        records = records[:maximum]
    eligible: list[dict[str, Any]] = []
    for record in records:
        choices = record.get("choices")
        answer_index = record.get("answer_index")
        if (
            isinstance(choices, list)
            and len(choices) >= 2
            and isinstance(answer_index, int)
            and 0 <= answer_index < len(choices)
        ):
            eligible.append(record)
    if not eligible:
        return {
            "records": 0,
            "warning": "No records contained choices plus a valid answer_index.",
            "modes": {},
        }

    choice_count = len(eligible[0]["choices"])
    if any(len(record["choices"]) != choice_count for record in eligible):
        raise ValueError("Choice evaluation currently requires a fixed choice count.")
    collator = CausalFineTuningCollator(
        pad_token_id=int(tokenizer.pad_token_id),
        pad_to_multiple_of=config.data.pad_to_multiple_of,
    )
    batch_size = max(1, int(config.assays.choice_eval.batch_size))
    normalization = config.assays.choice_eval.score_normalization
    answer_indices = torch.tensor(
        [int(record["answer_index"]) for record in eligible], dtype=torch.long
    )
    distances = torch.tensor(
        [
            int(record.get("metadata", {}).get("rank_distance", -1))
            if isinstance(record.get("metadata", {}), Mapping)
            else -1
            for record in eligible
        ],
        dtype=torch.long,
    )
    twin_eligible = torch.tensor(
        [
            bool(
                isinstance(record.get("metadata", {}), Mapping)
                and record.get("metadata", {}).get("counterfactual_pair_id")
                is not None
                and choice_count == 2
            )
            for record in eligible
        ],
        dtype=torch.bool,
    )
    counterfactual_answers = torch.where(
        twin_eligible, 1 - answer_indices, answer_indices
    )

    require_counterfactual_batches = "counterfactual_twin" in set(
        intervention_modes
    )
    assay_batches = _choice_assay_batches(
        eligible,
        batch_size=batch_size,
        require_counterfactual_pairs=require_counterfactual_batches,
    )

    mode_reports: dict[str, Any] = {}
    for mode_index, mode in enumerate(intervention_modes):
        scores = torch.full((len(eligible), choice_count), float("nan"))
        for choice_index in range(choice_count):
            for batch_index, record_indices in enumerate(assay_batches):
                features = [
                    _choice_feature(
                        eligible[index],
                        response=str(eligible[index]["choices"][choice_index]),
                        index=index,
                        tokenizer=tokenizer,
                        data_config=config.data,
                    )
                    for index in record_indices
                ]
                batch = move_batch_to_device(collator(features), device)
                with autocast_context(device, precision):
                    output = model(
                        input_ids=batch["input_ids"],
                        attention_mask=batch["attention_mask"],
                        labels=batch["labels"],
                        prompt_mask=batch["prompt_mask"],
                        context_mask=batch.get("context_mask"),
                        query_mask=batch.get("query_mask"),
                        example_group_ids=batch.get("example_group_ids"),
                        world_group_ids=batch.get("world_group_ids"),
                        counterfactual_group_ids=batch.get(
                            "counterfactual_group_ids"
                        ),
                        answer_classes=batch.get("answer_classes"),
                        **bridge_batch_kwargs(batch),
                        **functional_batch_kwargs(batch),
                        compute_workspace_loss=False,
                        compute_spectral=False,
                        bypass_workspace=False,
                        memory_intervention=mode,
                        memory_intervention_seed=(
                            int(intervention_seed)
                            + mode_index * 1_000_003
                            + batch_index
                        ),
                    )
                per_nll = output.get("per_example_nll")
                per_tokens = output.get("per_example_tokens")
                if not isinstance(per_nll, torch.Tensor) or not isinstance(
                    per_tokens, torch.Tensor
                ):
                    raise RuntimeError("Choice evaluation requires per-example NLL.")
                value = per_nll.detach().float().cpu()
                if normalization == "mean":
                    value = value / per_tokens.detach().float().cpu().clamp_min(1.0)
                scores[record_indices, choice_index] = value

        predicted = scores.argmin(dim=1)
        correct = predicted.eq(answer_indices)
        correct_score = scores.gather(1, answer_indices[:, None]).squeeze(1)
        masked = scores.clone()
        masked.scatter_(1, answer_indices[:, None], float("inf"))
        best_wrong = masked.min(dim=1).values
        margins = best_wrong - correct_score
        distance_report: dict[str, Any] = {}
        for distance in sorted(set(int(value) for value in distances.tolist() if value >= 0)):
            selection = distances.eq(distance)
            distance_report[str(distance)] = {
                "records": int(selection.sum().item()),
                "accuracy": float(correct[selection].float().mean().item()),
                "mean_margin": float(margins[selection].mean().item()),
            }
        twin_counterfactual_accuracy = None
        if bool(twin_eligible.any().item()):
            twin_counterfactual_accuracy = float(
                predicted[twin_eligible]
                .eq(counterfactual_answers[twin_eligible])
                .float()
                .mean()
                .item()
            )
        mode_reports[mode] = {
            "records": len(eligible),
            "accuracy": float(correct.float().mean().item()),
            "mean_margin": float(margins.mean().item()),
            "score_normalization": normalization,
            "distance": distance_report,
            "predictions": [int(value) for value in predicted.tolist()],
            "twin_records": int(twin_eligible.sum().item()),
            "counterfactual_answer_accuracy": twin_counterfactual_accuracy,
        }

    intact = mode_reports.get("intact")
    if intact is not None:
        intact_predictions = torch.tensor(
            intact["predictions"], dtype=torch.long
        )
        for mode, report in mode_reports.items():
            report["accuracy_delta_vs_intact"] = (
                float(report["accuracy"]) - float(intact["accuracy"])
            )
            report["margin_delta_vs_intact"] = (
                float(report["mean_margin"]) - float(intact["mean_margin"])
            )
            mode_predictions = torch.tensor(
                report["predictions"], dtype=torch.long
            )
            flipped = mode_predictions.ne(intact_predictions)
            report["prediction_flips_vs_intact"] = int(flipped.sum().item())
            report["prediction_flip_fraction_vs_intact"] = float(
                flipped.float().mean().item()
            )
            if bool(twin_eligible.any().item()):
                flipped_to_twin = (
                    flipped
                    & twin_eligible
                    & mode_predictions.eq(counterfactual_answers)
                )
                report["flips_to_counterfactual_answer"] = int(
                    flipped_to_twin.sum().item()
                )
                report["flip_to_counterfactual_fraction"] = float(
                    flipped_to_twin[twin_eligible].float().mean().item()
                )
    return {
        "records": len(eligible),
        "choice_count": choice_count,
        "modes": mode_reports,
    }


def run_choice_evaluation(
    checkpoint: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
    *,
    device: torch.device,
    modes: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    model, tokenizer, config = load_bundle(checkpoint, device=device)
    precision = resolve_mixed_precision(config.train.mixed_precision, device)
    selected_modes = list(modes or ["intact"])
    report = {
        "format": "latent-workspace-v8-semantic-choice-eval-v2",
        "harness_version": __version__,
        "checkpoint": str(Path(checkpoint).expanduser().resolve()),
        "source_sha256": source_sha256(),
        "route_topology": config.workspace.route_topology,
        "choice": evaluate_choices_loaded(
            model,
            tokenizer,
            config,
            device=device,
            precision=precision,
            intervention_modes=selected_modes,
            intervention_seed=config.assays.necessity.seed,
        ),
        "claim_boundary": (
            "Candidate scoring establishes task-level directionality only when "
            "a content intervention changes exact choices or margins toward the "
            "matched counterfactual answer. Route removal alone demonstrates "
            "carrier dependence, not semantic memory use."
        ),
    }
    _atomic_write_json(Path(output_path), report)
    return report


def _run_functional_necessity_loaded(
    model: LatentWorkspaceCausalLM,
    tokenizer: Any,
    config: ExperimentConfig,
    checkpoint: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
    *,
    device: torch.device,
) -> dict[str, Any]:
    necessity = config.assays.necessity
    if config.functional.route_mode != "deferred":
        raise ValueError(
            "v9 functional necessity requires functional.route_mode='deferred'."
        )
    if float(config.functional.injection_scale) == 0.0:
        raise ValueError("v9 functional necessity requires a nonzero injection scale.")
    if not config.data.eval_files:
        raise ValueError("v9 functional necessity requires evaluation files.")

    dataset = JsonlFineTuningDataset(config.data.eval_files, tokenizer, config.data)
    collator = CausalFineTuningCollator(
        pad_token_id=int(tokenizer.pad_token_id),
        pad_to_multiple_of=config.data.pad_to_multiple_of,
    )
    loader = build_eval_dataloader(
        dataset,
        collator,
        config=config.data,
        batch_size=int(necessity.batch_size),
        seed=config.train.seed + config.attribution.assay_seed_offset,
    )
    precision = resolve_mixed_precision(config.train.mixed_precision, device)
    modes = list(necessity.modes)
    if "intact" not in modes:
        modes.insert(0, "intact")
    if "counterfactual_twin" not in modes:
        modes.append("counterfactual_twin")

    results: dict[str, dict[str, float]] = {}
    for mode_index, mode in enumerate(modes):
        results[mode] = evaluate(
            model,
            loader,
            device=device,
            precision=precision,
            workspace_loss_weight=0.0,
            max_batches=(
                necessity.eval_batches
                if necessity.eval_batches > 0
                else config.train.eval_batches
            ),
            compute_spectral=False,
            compute_workspace_loss=False,
            bypass_workspace=False,
            memory_intervention=mode,
            memory_intervention_seed=(
                int(necessity.seed) + mode_index * 1_000_003
            ),
        )

    intact = results["intact"]
    effects: dict[str, dict[str, float]] = {}
    for mode, metrics in results.items():
        effects[mode] = {
            "task_loss_increase_vs_intact": (
                float(metrics["task_loss"]) - float(intact["task_loss"])
            ),
            "query_accuracy_delta_vs_intact": (
                float(metrics.get("functional_query_accuracy", 0.0))
                - float(intact.get("functional_query_accuracy", 0.0))
            ),
            "world_accuracy_delta_vs_intact": (
                float(metrics.get("functional_all_query_world_accuracy", 0.0))
                - float(intact.get("functional_all_query_world_accuracy", 0.0))
            ),
            "choice_margin_delta_vs_intact": (
                float(metrics.get("functional_choice_margin", 0.0))
                - float(intact.get("functional_choice_margin", 0.0))
            ),
            "memory_assignment_changed_fraction": float(
                metrics.get("memory_assignment_changed_fraction", 0.0)
            ),
            "memory_tensor_changed_fraction": float(
                metrics.get("memory_tensor_changed_fraction", 0.0)
            ),
            "memory_effective_changed_fraction": float(
                metrics.get("memory_effective_changed_fraction", 0.0)
            ),
        }

    twin = results["counterfactual_twin"]
    fixed = results.get("fixed_carrier", results.get("global_fixed", {}))
    random_carrier = results.get(
        "norm_matched_random", results.get("random_matched", {})
    )
    hard = results.get("hard_bypass", {})
    query_accuracy = float(intact.get("functional_query_accuracy", 0.0))
    world_accuracy = float(
        intact.get("functional_all_query_world_accuracy", 0.0)
    )
    heldout_accuracy = float(
        intact.get("functional_heldout_query_accuracy", 0.0)
    )
    affected_donor = float(
        twin.get("functional_affected_donor_accuracy", 0.0)
    )
    unaffected_stability = float(
        twin.get("functional_unaffected_original_stability", 0.0)
    )
    fixed_accuracy = float(fixed.get("functional_query_accuracy", 0.0))
    random_accuracy = float(
        random_carrier.get("functional_query_accuracy", 0.0)
    )
    hard_accuracy = float(hard.get("functional_query_accuracy", 0.0))

    coverage = float(
        twin.get(
            "memory_effective_changed_fraction",
            twin.get("memory_changed_fraction", 0.0),
        )
    )
    if coverage < float(necessity.minimum_changed_fraction):
        raise RuntimeError(
            "v9 counterfactual_twin intervention changed only "
            f"{coverage:.3f} of functional memories; required >= "
            f"{necessity.minimum_changed_fraction:.3f}."
        )

    f1 = world_accuracy >= float(config.functional.world_accuracy_threshold)
    f2 = bool(
        query_accuracy > fixed_accuracy
        and query_accuracy > random_accuracy
        and query_accuracy > hard_accuracy
    )
    f3 = affected_donor >= float(config.functional.affected_flip_threshold)
    f4 = bool(
        f3
        and unaffected_stability
        >= float(config.functional.unaffected_stability_threshold)
    )
    f5 = bool(
        heldout_accuracy >= float(config.functional.heldout_query_threshold)
    )
    report = {
        "format": "latent-workspace-v9-functional-necessity-v1",
        "harness_version": __version__,
        "checkpoint": str(Path(checkpoint).expanduser().resolve()),
        "source_sha256": source_sha256(),
        "functional_config": dataclasses.asdict(config.functional),
        "modes": modes,
        "metrics": results,
        "effects": effects,
        "evidence_ladder": {
            "F0_engineering": {
                "counterfactual_effective_coverage": coverage,
                "passed": coverage >= float(necessity.minimum_changed_fraction),
            },
            "F1_deferred_sufficiency": {
                "query_accuracy": query_accuracy,
                "all_query_world_accuracy": world_accuracy,
                "threshold": float(config.functional.world_accuracy_threshold),
                "passed": f1,
            },
            "F2_carrier_insufficiency": {
                "intact_accuracy": query_accuracy,
                "fixed_carrier_accuracy": fixed_accuracy,
                "random_carrier_accuracy": random_accuracy,
                "hard_bypass_accuracy": hard_accuracy,
                "passed": f2,
            },
            "F3_counterfactual_direction": {
                "affected_donor_accuracy": affected_donor,
                "threshold": float(config.functional.affected_flip_threshold),
                "passed": f3,
            },
            "F4_local_causal_specificity": {
                "affected_donor_accuracy": affected_donor,
                "unaffected_original_stability": unaffected_stability,
                "affected_threshold": float(
                    config.functional.affected_flip_threshold
                ),
                "stability_threshold": float(
                    config.functional.unaffected_stability_threshold
                ),
                "passed": f4,
            },
            "F5_heldout_query_generalization": {
                "heldout_query_accuracy": heldout_accuracy,
                "threshold": float(config.functional.heldout_query_threshold),
                "passed": f5,
            },
        },
        "primary_gate_passed": bool(f1 and f2 and f4),
        "claim_boundary": (
            "F4 supports local content-specific causal load-bearing only for "
            "the controlled paired-world task: affected answers must move to "
            "the donor world while unaffected answers remain stable. It does "
            "not establish recurrent necessity, general reasoning, a global "
            "workspace, consciousness, or AGI."
        ),
    }
    _atomic_write_json(Path(output_path), report)
    return report

def run_necessity_assay(
    checkpoint: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
    *,
    device: torch.device,
) -> dict[str, Any]:
    model, tokenizer, config = load_bundle(checkpoint, device=device)
    if config.functional.enabled:
        return _run_functional_necessity_loaded(
            model, tokenizer, config, checkpoint, output_path, device=device
        )
    necessity = config.assays.necessity
    if necessity.require_deferred_bridge and config.workspace.route_topology != "deferred_bridge":
        raise ValueError(
            "Causal context-memory necessity requires route_topology='deferred_bridge'."
        )
    if config.workspace.logit_residual_scale == 0.0:
        raise ValueError("Necessity assay requires a nonzero runtime route.")
    if not config.data.eval_files:
        raise ValueError("Necessity assay requires evaluation files.")

    dataset = JsonlFineTuningDataset(config.data.eval_files, tokenizer, config.data)
    collator = CausalFineTuningCollator(
        pad_token_id=int(tokenizer.pad_token_id),
        pad_to_multiple_of=config.data.pad_to_multiple_of,
    )
    loader = build_necessity_dataloader(
        dataset,
        collator,
        config=config.data,
        batch_size=int(necessity.batch_size),
        seed=config.train.seed + config.attribution.assay_seed_offset,
        mix_worlds=bool(necessity.mix_worlds),
        mix_counterfactual_pairs=(
            bool(necessity.require_counterfactual_pairs)
            or "counterfactual_twin" in necessity.modes
        ),
    )
    precision = resolve_mixed_precision(config.train.mixed_precision, device)
    modes = list(necessity.modes)
    results: dict[str, dict[str, float]] = {}
    for mode_index, mode in enumerate(modes):
        results[mode] = evaluate(
            model,
            loader,
            device=device,
            precision=precision,
            workspace_loss_weight=0.0,
            max_batches=(
                necessity.eval_batches
                if necessity.eval_batches > 0
                else config.train.eval_batches
            ),
            compute_spectral=False,
            compute_workspace_loss=False,
            bypass_workspace=False,
            memory_intervention=mode,
            memory_intervention_seed=(
                int(necessity.seed) + mode_index * 1_000_003
            ),
        )

    intact = results["intact"]
    effects: dict[str, Any] = {}
    for mode, metrics in results.items():
        effects[mode] = {
            "task_loss_increase_vs_intact": (
                float(metrics["task_loss"]) - float(intact["task_loss"])
            ),
            "task_gain_change_vs_intact": (
                float(metrics.get("task_gain_nats", 0.0))
                - float(intact.get("task_gain_nats", 0.0))
            ),
            "memory_changed_fraction": float(
                metrics.get("memory_changed_fraction", 0.0)
            ),
            "memory_assignment_changed_fraction": float(
                metrics.get("memory_assignment_changed_fraction", 0.0)
            ),
            "memory_tensor_changed_fraction": float(
                metrics.get("memory_tensor_changed_fraction", 0.0)
            ),
            "memory_effective_changed_fraction": float(
                metrics.get("memory_effective_changed_fraction", 0.0)
            ),
            "memory_content_delta_l2": float(
                metrics.get("memory_content_delta_l2", 0.0)
            ),
            "memory_effective_delta_l2": float(
                metrics.get("memory_effective_delta_l2", 0.0)
            ),
            "memory_source_norm": float(
                metrics.get("memory_source_norm", 0.0)
            ),
            "memory_intervened_norm": float(
                metrics.get("memory_intervened_norm", 0.0)
            ),
            "memory_raw_cosine": float(
                metrics.get("memory_raw_cosine", 0.0)
            ),
            "memory_layernorm_cosine": float(
                metrics.get("memory_layernorm_cosine", 0.0)
            ),
            "memory_carrier_presence_fraction": float(
                metrics.get("memory_carrier_presence_fraction", 0.0)
            ),
            "hard_bypass_fraction": float(
                metrics.get("hard_bypass_fraction", 0.0)
            ),
        }
        distance_effects: dict[str, float] = {}
        for key, value in metrics.items():
            match = re.fullmatch(r"distance_(\d+)_task_loss", key)
            if match and key in intact:
                distance_effects[match.group(1)] = float(value) - float(intact[key])
        effects[mode]["distance_task_loss_increase"] = distance_effects

    coverage: dict[str, float] = {}
    for mode in (
        "within_world_shuffle",
        "cross_world_shuffle",
        "counterfactual_twin",
    ):
        if mode not in results:
            continue
        changed_fraction = float(results[mode].get("memory_changed_fraction", 0.0))
        coverage[mode] = changed_fraction
        if changed_fraction < float(necessity.minimum_changed_fraction):
            raise RuntimeError(
                f"Necessity intervention {mode!r} changed only "
                f"{changed_fraction:.3f} of rows; required >= "
                f"{necessity.minimum_changed_fraction:.3f}. Increase "
                "necessity.batch_size, keep mix_worlds=true, or provide at "
                "least two queries per world and two worlds per assay batch."
            )

    specificity = None
    if "cross_world_shuffle" in effects and "within_world_shuffle" in effects:
        specificity = (
            effects["cross_world_shuffle"]["task_loss_increase_vs_intact"]
            - effects["within_world_shuffle"]["task_loss_increase_vs_intact"]
        )

    choice = None
    if necessity.run_choice_eval and config.assays.choice_eval.enabled:
        choice = evaluate_choices_loaded(
            model,
            tokenizer,
            config,
            device=device,
            precision=precision,
            intervention_modes=modes,
            intervention_seed=necessity.seed,
        )

    choice_modes = (
        choice.get("modes", {})
        if isinstance(choice, Mapping)
        else {}
    )
    twin_choice = (
        choice_modes.get("counterfactual_twin", {})
        if isinstance(choice_modes, Mapping)
        else {}
    )
    hard_choice = (
        choice_modes.get("hard_bypass", {})
        if isinstance(choice_modes, Mapping)
        else {}
    )
    fixed_choice = (
        choice_modes.get("global_fixed", choice_modes.get("fixed_carrier", {}))
        if isinstance(choice_modes, Mapping)
        else {}
    )
    random_choice = (
        choice_modes.get(
            "random_matched", choice_modes.get("norm_matched_random", {})
        )
        if isinstance(choice_modes, Mapping)
        else {}
    )

    # This ladder records increasingly semantic evidence without silently
    # upgrading a weaker carrier result into a content claim. Replication and
    # uncertainty remain the responsibility of the matrix summarizer.
    evidence_ladder = {
        "level_0_engineering": {
            "counterfactual_pairs_required": bool(
                necessity.require_counterfactual_pairs
            ),
            "coverage": coverage,
        },
        "level_1_route_presence": {
            "hard_bypass_task_loss_increase": effects.get(
                "hard_bypass", {}
            ).get("task_loss_increase_vs_intact"),
            "hard_bypass_choice_accuracy_delta": (
                hard_choice.get("accuracy_delta_vs_intact")
                if isinstance(hard_choice, Mapping)
                else None
            ),
        },
        "level_2_carrier_insufficiency": {
            "fixed_carrier_task_loss_increase": effects.get(
                "global_fixed", effects.get("fixed_carrier", {})
            ).get("task_loss_increase_vs_intact"),
            "random_carrier_task_loss_increase": effects.get(
                "random_matched", effects.get("norm_matched_random", {})
            ).get("task_loss_increase_vs_intact"),
            "fixed_carrier_choice_accuracy_delta": (
                fixed_choice.get("accuracy_delta_vs_intact")
                if isinstance(fixed_choice, Mapping)
                else None
            ),
            "random_carrier_choice_accuracy_delta": (
                random_choice.get("accuracy_delta_vs_intact")
                if isinstance(random_choice, Mapping)
                else None
            ),
        },
        "level_3_content_sensitivity": {
            "cross_minus_within_world_specificity": specificity,
            "counterfactual_twin_task_loss_increase": effects.get(
                "counterfactual_twin", {}
            ).get("task_loss_increase_vs_intact"),
            "counterfactual_twin_margin_delta": (
                twin_choice.get("margin_delta_vs_intact")
                if isinstance(twin_choice, Mapping)
                else None
            ),
        },
        "level_4_counterfactual_directionality": {
            "prediction_flips": (
                twin_choice.get("prediction_flips_vs_intact")
                if isinstance(twin_choice, Mapping)
                else None
            ),
            "flips_to_counterfactual_answer": (
                twin_choice.get("flips_to_counterfactual_answer")
                if isinstance(twin_choice, Mapping)
                else None
            ),
            "flip_to_counterfactual_fraction": (
                twin_choice.get("flip_to_counterfactual_fraction")
                if isinstance(twin_choice, Mapping)
                else None
            ),
        },
    }

    report = {
        "format": "latent-workspace-v8-semantic-necessity-v2",
        "harness_version": __version__,
        "checkpoint": str(Path(checkpoint).expanduser().resolve()),
        "source_sha256": source_sha256(),
        "route_topology": config.workspace.route_topology,
        "modes": modes,
        "metrics": results,
        "effects": effects,
        "intervention_coverage": coverage,
        "cross_minus_within_world_specificity": specificity,
        "counterfactual_twin_effect": (
            effects.get("counterfactual_twin")
        ),
        "choice": choice,
        "evidence_ladder": evidence_ladder,
        "claim_boundary": (
            "Route removal or zero-memory damage establishes carrier dependence "
            "only. Content-specific necessity additionally requires fixed/random "
            "carrier insufficiency and matched counterfactual memory to move loss, "
            "margin, or exact choices toward the donor twin answer. It does not "
            "by itself establish general reasoning or consciousness."
        ),
    }
    _atomic_write_json(Path(output_path), report)
    return report


class LowRankRecruitmentProbe(nn.Module):
    """Small frozen-trunk readout used to measure conditional recruitability."""

    def __init__(self, hidden_dim: int, rank: int, num_classes: int) -> None:
        super().__init__()
        if hidden_dim < 1 or rank < 0 or num_classes < 2:
            raise ValueError("Invalid recruitment probe dimensions.")
        self.hidden_dim = hidden_dim
        self.rank = rank
        self.num_classes = num_classes
        self.norm = nn.LayerNorm(hidden_dim)
        if rank == 0:
            self.readout = nn.Linear(hidden_dim, num_classes)
        else:
            self.readout = nn.Sequential(
                nn.Linear(hidden_dim, rank, bias=False),
                nn.GELU(),
                nn.Linear(rank, num_classes),
            )

    def forward(self, hidden: torch.Tensor) -> torch.Tensor:
        return self.readout(self.norm(hidden))


def _select_recruitment_rows(
    hidden: torch.Tensor,
    batch: Mapping[str, torch.Tensor],
    scope: str,
    target_name: str,
) -> tuple[torch.Tensor, torch.Tensor]:
    if hidden.ndim != 3:
        raise ValueError("Recruitment hidden states must be [B, L, D].")
    target_key = {
        "rank_distance": "rank_distances",
        "answer_class": "answer_classes",
    }.get(target_name)
    if target_key is None:
        raise ValueError(f"Unsupported recruitment target: {target_name}")
    targets = batch.get(target_key)
    if not isinstance(targets, torch.Tensor):
        raise ValueError(
            f"{target_name} recruitment requires {target_key} metadata."
        )
    context = batch.get("context_mask")
    query = batch.get("query_mask")
    if not isinstance(context, torch.Tensor):
        raise ValueError("Recruitment requires context_mask from deferred records.")

    features: list[torch.Tensor] = []
    labels: list[torch.Tensor] = []
    for row in range(hidden.shape[0]):
        target = int(targets[row].item())
        if target < 0:
            continue
        if scope == "context_mean":
            indices = torch.nonzero(context[row], as_tuple=False).flatten()
            if indices.numel() == 0:
                continue
            feature = hidden[row, indices].mean(dim=0)
        elif scope == "prequery_boundary":
            indices = torch.nonzero(context[row], as_tuple=False).flatten()
            if indices.numel() == 0:
                continue
            feature = hidden[row, indices[-1]]
        elif scope == "query_end":
            if not isinstance(query, torch.Tensor):
                raise ValueError("query_end recruitment requires query_mask.")
            indices = torch.nonzero(query[row], as_tuple=False).flatten()
            if indices.numel() == 0:
                continue
            feature = hidden[row, indices[-1]]
        else:
            raise ValueError(f"Unsupported recruitment scope: {scope}")
        features.append(feature.detach())
        labels.append(targets[row].detach())
    if not features:
        return (
            hidden.new_zeros((0, hidden.shape[-1])),
            targets.new_zeros((0,), dtype=torch.long),
        )
    return torch.stack(features), torch.stack(labels).long()


def _recruitment_feature_target(
    feature: Mapping[str, Any],
    target_name: str,
) -> int:
    key = {
        "rank_distance": "rank_distance",
        "answer_class": "answer_class",
    }.get(target_name)
    if key is None:
        raise ValueError(f"Unsupported recruitment target: {target_name}")
    try:
        return int(feature.get(key, -1))
    except (TypeError, ValueError):
        return -1


def _recruitment_prefix_signature(
    feature: Mapping[str, Any],
    scope: str,
) -> tuple[int, ...]:
    ids = [int(value) for value in feature["input_ids"]]
    context = [bool(value) for value in feature.get("context_mask", [])]
    query = [bool(value) for value in feature.get("query_mask", [])]
    if len(context) != len(ids):
        context = [False] * len(ids)
    if len(query) != len(ids):
        query = [False] * len(ids)
    if scope in {"prequery_boundary", "context_mean"}:
        indices = [index for index, value in enumerate(context) if value]
    elif scope == "query_end":
        indices = [index for index, value in enumerate(query) if value]
    else:
        raise ValueError(f"Unsupported recruitment scope: {scope}")
    if not indices:
        return tuple()
    return tuple(ids[: indices[-1] + 1])


def recruitment_identifiability_report(
    dataset: JsonlFineTuningDataset,
    *,
    scope: str,
    target_name: str,
    max_examples: int = 0,
) -> dict[str, Any]:
    """Compute the dataset-level Bayes ceiling for a causal probe prefix."""
    grouped: dict[str, dict[int, int]] = {}
    class_counts: dict[int, int] = {}
    examples = min(len(dataset), max_examples) if max_examples > 0 else len(dataset)
    valid = 0
    empty_prefixes = 0
    for index in range(examples):
        feature = dataset[index]
        target = _recruitment_feature_target(feature, target_name)
        if target < 0:
            continue
        signature = _recruitment_prefix_signature(feature, scope)
        if not signature:
            empty_prefixes += 1
            continue
        digest = hashlib.sha256(
            json.dumps(signature, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        counts = grouped.setdefault(digest, {})
        counts[target] = counts.get(target, 0) + 1
        class_counts[target] = class_counts.get(target, 0) + 1
        valid += 1
    if valid == 0 or len(class_counts) < 2:
        raise ValueError(
            "Recruitment identifiability requires valid examples from at least "
            "two classes."
        )
    majority_correct = sum(max(counts.values()) for counts in grouped.values())
    bayes_ceiling = majority_correct / valid
    prior_ceiling = max(class_counts.values()) / valid
    conflicting_groups = sum(1 for counts in grouped.values() if len(counts) > 1)
    conflicting_examples = sum(
        sum(counts.values()) for counts in grouped.values() if len(counts) > 1
    )
    return {
        "scope": scope,
        "target": target_name,
        "examples": valid,
        "classes": sorted(class_counts),
        "class_counts": {str(key): value for key, value in sorted(class_counts.items())},
        "unique_prefixes": len(grouped),
        "conflicting_prefix_groups": conflicting_groups,
        "conflicting_examples": conflicting_examples,
        "empty_prefixes": empty_prefixes,
        "prior_ceiling": prior_ceiling,
        "bayes_ceiling": bayes_ceiling,
        "ceiling_over_prior": bayes_ceiling - prior_ceiling,
        "identifiable_above_prior": bayes_ceiling > prior_ceiling,
    }


@torch.no_grad()
def collect_recruitment_features(
    model: LatentWorkspaceCausalLM,
    dataloader: DataLoader[Any],
    *,
    device: torch.device,
    precision: str,
    scope: str,
    target_name: str,
    max_examples: int = 0,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Collect base-only features; no workspace module is evaluated."""
    was_training = model.training
    model.eval()
    features: list[torch.Tensor] = []
    labels: list[torch.Tensor] = []
    collected = 0
    for raw_batch in dataloader:
        batch = move_batch_to_device(raw_batch, device)
        with autocast_context(device, precision):
            _outputs, hidden = model._base_forward_with_hidden_capture(
                batch["input_ids"], batch["attention_mask"]
            )
        selected, target = _select_recruitment_rows(
            hidden, batch, scope, target_name
        )
        if selected.numel() == 0:
            continue
        if max_examples > 0 and collected + selected.shape[0] > max_examples:
            keep = max_examples - collected
            selected = selected[:keep]
            target = target[:keep]
        features.append(selected.float().cpu())
        labels.append(target.cpu())
        collected += selected.shape[0]
        if max_examples > 0 and collected >= max_examples:
            break
    if was_training:
        model.train()
    if not features:
        raise RuntimeError("Recruitment feature collection produced no examples.")
    return torch.cat(features, dim=0), torch.cat(labels, dim=0)


def _evaluate_recruitment_probe(
    probe: LowRankRecruitmentProbe,
    features: torch.Tensor,
    labels: torch.Tensor,
    *,
    device: torch.device,
    batch_size: int,
) -> dict[str, float]:
    probe.eval()
    total_loss = 0.0
    total_correct = 0
    total = 0
    with torch.no_grad():
        for start in range(0, features.shape[0], batch_size):
            stop = min(features.shape[0], start + batch_size)
            x = features[start:stop].to(device)
            y = labels[start:stop].to(device)
            logits = probe(x)
            total_loss += float(F.cross_entropy(logits, y, reduction="sum").item())
            total_correct += int(logits.argmax(dim=-1).eq(y).sum().item())
            total += y.numel()
    return {
        "loss": total_loss / max(total, 1),
        "accuracy": total_correct / max(total, 1),
        "examples": float(total),
    }


def fit_recruitment_probe(
    train_features: torch.Tensor,
    train_targets: torch.Tensor,
    eval_features: torch.Tensor,
    eval_targets: torch.Tensor,
    *,
    rank: int,
    config: RecruitmentConfig,
    device: torch.device,
) -> tuple[dict[str, Any], dict[str, torch.Tensor]]:
    if train_features.ndim != 2 or eval_features.ndim != 2:
        raise ValueError("Recruitment features must be matrices.")
    classes = sorted(set(int(value) for value in train_targets.tolist()))
    if len(classes) < 2:
        raise ValueError("Recruitment requires at least two target classes.")
    class_to_index = {value: index for index, value in enumerate(classes)}
    if any(int(value) not in class_to_index for value in eval_targets.tolist()):
        raise ValueError("Evaluation contains target classes absent from training.")
    mapped_train = torch.tensor(
        [class_to_index[int(value)] for value in train_targets.tolist()],
        dtype=torch.long,
    )
    mapped_eval = torch.tensor(
        [class_to_index[int(value)] for value in eval_targets.tolist()],
        dtype=torch.long,
    )

    seed = deterministic_stream_seed(
        config.seed, 0, rank, 0, 7_000_001
    )
    with isolated_torch_rng(True, seed, device):
        probe = LowRankRecruitmentProbe(
            train_features.shape[1], rank, len(classes)
        ).to(device)
    optimizer = torch.optim.AdamW(
        probe.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    generator = torch.Generator().manual_seed(seed)
    order = torch.randperm(train_features.shape[0], generator=generator)
    cursor = 0
    curve: list[dict[str, float]] = []

    def record(step: int) -> None:
        metrics = _evaluate_recruitment_probe(
            probe,
            eval_features,
            mapped_eval,
            device=device,
            batch_size=config.batch_size,
        )
        curve.append({"step": float(step), **metrics})

    record(0)
    probe.train()
    for step in range(1, config.max_steps + 1):
        if cursor + config.batch_size > order.numel():
            order = torch.randperm(train_features.shape[0], generator=generator)
            cursor = 0
        indices = order[cursor : cursor + config.batch_size]
        cursor += indices.numel()
        x = train_features[indices].to(device)
        y = mapped_train[indices].to(device)
        optimizer.zero_grad(set_to_none=True)
        logits = probe(x)
        loss = F.cross_entropy(logits, y)
        loss.backward()
        optimizer.step()
        if step % config.eval_every == 0 or step == config.max_steps:
            record(step)
            probe.train()

    auc = 0.0
    for left, right in zip(curve, curve[1:]):
        width = right["step"] - left["step"]
        auc += width * 0.5 * (left["accuracy"] + right["accuracy"])
    auc /= max(float(config.max_steps), 1.0)
    threshold_step: Optional[int] = None
    for point in curve:
        if point["accuracy"] >= config.threshold:
            threshold_step = int(point["step"])
            break
    final = curve[-1]
    report = {
        "rank": rank,
        "classes": classes,
        "parameters": sum(parameter.numel() for parameter in probe.parameters()),
        "curve": curve,
        "accuracy_auc": auc,
        "steps_to_threshold": threshold_step,
        "threshold": config.threshold,
        "final_accuracy": final["accuracy"],
        "final_loss": final["loss"],
        "train_examples": int(train_features.shape[0]),
        "eval_examples": int(eval_features.shape[0]),
    }
    state = {name: tensor.detach().cpu() for name, tensor in probe.state_dict().items()}
    return report, state


def run_recruitment_assay(
    checkpoint: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
    *,
    device: torch.device,
    scope_override: Optional[str] = None,
    target_override: Optional[str] = None,
    ranks_override: Optional[Sequence[int]] = None,
    allow_nonidentifying: bool = False,
) -> dict[str, Any]:
    model, tokenizer, experiment = load_bundle(checkpoint, device=device)
    recruitment = dataclasses.replace(experiment.assays.recruitment)
    if scope_override is not None:
        recruitment.scope = str(scope_override)
    if target_override is not None:
        recruitment.target = str(target_override)
    if ranks_override is not None:
        recruitment.ranks = [int(value) for value in ranks_override]
    if allow_nonidentifying:
        recruitment.fail_on_nonidentifying = False
    precision = resolve_mixed_precision(experiment.train.mixed_precision, device)
    train_files = recruitment.train_files or experiment.data.train_files
    eval_files = recruitment.eval_files or experiment.data.eval_files
    if not eval_files:
        raise ValueError("Recruitment assay requires evaluation files.")
    train_dataset = JsonlFineTuningDataset(train_files, tokenizer, experiment.data)
    eval_dataset = JsonlFineTuningDataset(eval_files, tokenizer, experiment.data)
    train_identifiability = recruitment_identifiability_report(
        train_dataset,
        scope=recruitment.scope,
        target_name=recruitment.target,
        max_examples=recruitment.max_train_examples,
    )
    eval_identifiability = recruitment_identifiability_report(
        eval_dataset,
        scope=recruitment.scope,
        target_name=recruitment.target,
        max_examples=recruitment.max_eval_examples,
    )
    chance = float(train_identifiability["prior_ceiling"])
    ceiling = float(train_identifiability["bayes_ceiling"])
    identifying = bool(
        ceiling >= float(recruitment.minimum_bayes_ceiling)
        and ceiling - chance >= float(recruitment.minimum_ceiling_over_chance)
    )
    if recruitment.fail_on_nonidentifying and not identifying:
        raise RuntimeError(
            "Recruitment assay is structurally non-identifying: "
            f"scope={recruitment.scope!r}, target={recruitment.target!r}, "
            f"Bayes ceiling={ceiling:.4f}, prior ceiling={chance:.4f}. "
            "Use a query-visible scope or a target defined by the selected "
            "causal prefix; override only for diagnostic reproduction."
        )
    collator = CausalFineTuningCollator(
        tokenizer.pad_token_id,
        experiment.data.pad_to_multiple_of,
    )
    train_loader = build_eval_dataloader(
        train_dataset,
        collator,
        config=experiment.data,
        batch_size=experiment.train.eval_batch_size,
        seed=recruitment.seed,
    )
    eval_loader = build_eval_dataloader(
        eval_dataset,
        collator,
        config=experiment.data,
        batch_size=experiment.train.eval_batch_size,
        seed=recruitment.seed + 1,
    )
    train_features, train_targets = collect_recruitment_features(
        model,
        train_loader,
        device=device,
        precision=precision,
        scope=recruitment.scope,
        target_name=recruitment.target,
        max_examples=recruitment.max_train_examples,
    )
    eval_features, eval_targets = collect_recruitment_features(
        model,
        eval_loader,
        device=device,
        precision=precision,
        scope=recruitment.scope,
        target_name=recruitment.target,
        max_examples=recruitment.max_eval_examples,
    )

    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    rank_reports: list[dict[str, Any]] = []
    for rank in recruitment.ranks:
        report, state = fit_recruitment_probe(
            train_features,
            train_targets,
            eval_features,
            eval_targets,
            rank=rank,
            config=recruitment,
            device=device,
        )
        rank_reports.append(report)
        if recruitment.save_probe_states:
            torch.save(state, output / f"probe_rank_{rank}.pt")
    recruitment_paths = [
        *_expand_file_patterns(train_files),
        *_expand_file_patterns(eval_files),
    ]
    result = {
        "format": "latent-workspace-v8-recruitability-v2",
        "checkpoint": str(Path(checkpoint).expanduser().resolve()),
        "harness_version": __version__,
        "source_sha256": source_sha256(),
        "data_fingerprint": fingerprint_files(
            recruitment_paths,
            experiment.data.fingerprint_bytes,
            mode="full",
        ),
        "train_files": [str(path) for path in _expand_file_patterns(train_files)],
        "eval_files": [str(path) for path in _expand_file_patterns(eval_files)],
        "scope": recruitment.scope,
        "target": recruitment.target,
        "base_only": True,
        "workspace_evaluated": False,
        "identifiability": {
            "passed": identifying,
            "train": train_identifiability,
            "eval": eval_identifiability,
            "minimum_bayes_ceiling": recruitment.minimum_bayes_ceiling,
            "minimum_ceiling_over_chance": (
                recruitment.minimum_ceiling_over_chance
            ),
        },
        "ranks": rank_reports,
    }
    _atomic_write_json(output / "recruitment_report.json", result)
    return result


def layer_displacement_map(
    baseline: LatentWorkspaceCausalLM,
    induced: LatentWorkspaceCausalLM,
) -> dict[str, Any]:
    baseline_parameters = dict(baseline.base_model.named_parameters())
    induced_parameters = dict(induced.base_model.named_parameters())
    if baseline_parameters.keys() != induced_parameters.keys():
        missing_left = sorted(induced_parameters.keys() - baseline_parameters.keys())
        missing_right = sorted(baseline_parameters.keys() - induced_parameters.keys())
        raise ValueError(
            "Base-model parameter names differ. "
            f"baseline_missing={missing_left[:8]}, induced_missing={missing_right[:8]}"
        )

    totals: dict[str, dict[str, float]] = {}
    for name, baseline_parameter in baseline_parameters.items():
        induced_parameter = induced_parameters[name]
        if baseline_parameter.shape != induced_parameter.shape:
            raise ValueError(f"Parameter shape mismatch for {name}.")
        group = _base_layer_group(f"base_model.{name}")
        record = totals.setdefault(
            group,
            {
                "delta_sq": 0.0,
                "baseline_sq": 0.0,
                "induced_sq": 0.0,
                "dot": 0.0,
                "parameters": 0.0,
                "tensors": 0.0,
            },
        )
        left = baseline_parameter.detach().double().cpu().reshape(-1)
        right = induced_parameter.detach().double().cpu().reshape(-1)
        delta = right - left
        record["delta_sq"] += float(torch.dot(delta, delta).item())
        record["baseline_sq"] += float(torch.dot(left, left).item())
        record["induced_sq"] += float(torch.dot(right, right).item())
        record["dot"] += float(torch.dot(left, right).item())
        record["parameters"] += float(left.numel())
        record["tensors"] += 1.0

    groups: dict[str, Any] = {}
    global_record = {
        "delta_sq": 0.0,
        "baseline_sq": 0.0,
        "induced_sq": 0.0,
        "dot": 0.0,
        "parameters": 0.0,
        "tensors": 0.0,
    }
    for name, record in sorted(totals.items()):
        for key in global_record:
            global_record[key] += record[key]
        baseline_norm = math.sqrt(max(record["baseline_sq"], 0.0))
        induced_norm = math.sqrt(max(record["induced_sq"], 0.0))
        delta_norm = math.sqrt(max(record["delta_sq"], 0.0))
        denominator = baseline_norm * induced_norm
        groups[name] = {
            "delta_l2": delta_norm,
            "relative_delta_l2": delta_norm / max(baseline_norm, 1e-30),
            "baseline_l2": baseline_norm,
            "induced_l2": induced_norm,
            "cosine": record["dot"] / max(denominator, 1e-30),
            "parameters": int(record["parameters"]),
            "tensors": int(record["tensors"]),
        }
    baseline_norm = math.sqrt(max(global_record["baseline_sq"], 0.0))
    induced_norm = math.sqrt(max(global_record["induced_sq"], 0.0))
    delta_norm = math.sqrt(max(global_record["delta_sq"], 0.0))
    return {
        "global": {
            "delta_l2": delta_norm,
            "relative_delta_l2": delta_norm / max(baseline_norm, 1e-30),
            "baseline_l2": baseline_norm,
            "induced_l2": induced_norm,
            "cosine": global_record["dot"]
            / max(baseline_norm * induced_norm, 1e-30),
            "parameters": int(global_record["parameters"]),
            "tensors": int(global_record["tensors"]),
        },
        "groups": groups,
    }


def _group_parameter_names(
    model: LatentWorkspaceCausalLM,
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for name, _parameter in model.base_model.named_parameters():
        group = _base_layer_group(f"base_model.{name}")
        result.setdefault(group, []).append(name)
    return result


def _copy_parameter_group(
    source: LatentWorkspaceCausalLM,
    target: LatentWorkspaceCausalLM,
    names: Sequence[str],
) -> dict[str, torch.Tensor]:
    source_parameters = dict(source.base_model.named_parameters())
    target_parameters = dict(target.base_model.named_parameters())
    backup: dict[str, torch.Tensor] = {}
    with torch.no_grad():
        for name in names:
            backup[name] = target_parameters[name].detach().clone()
            target_parameters[name].copy_(
                source_parameters[name].detach().to(
                    device=target_parameters[name].device,
                    dtype=target_parameters[name].dtype,
                )
            )
    return backup


def _restore_parameter_group(
    target: LatentWorkspaceCausalLM,
    backup: Mapping[str, torch.Tensor],
) -> None:
    parameters = dict(target.base_model.named_parameters())
    with torch.no_grad():
        for name, tensor in backup.items():
            parameters[name].copy_(
                tensor.to(device=parameters[name].device, dtype=parameters[name].dtype)
            )


def run_influence_map(
    baseline_checkpoint: str | os.PathLike[str],
    induced_checkpoint: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
    *,
    device: torch.device,
    eval_batches: int = 0,
    max_groups: int = 0,
    causal_swaps: bool = True,
) -> dict[str, Any]:
    baseline, _baseline_tokenizer, baseline_config = load_bundle(
        baseline_checkpoint, device=device
    )
    induced, tokenizer, induced_config = load_bundle(
        induced_checkpoint, device=device
    )
    if baseline_config.model.train_mode != induced_config.model.train_mode:
        raise ValueError("Influence mapping requires matching train modes.")
    displacement = layer_displacement_map(baseline, induced)
    ordered_groups = sorted(
        displacement["groups"],
        key=lambda name: displacement["groups"][name]["relative_delta_l2"],
        reverse=True,
    )
    if max_groups > 0:
        ordered_groups = ordered_groups[:max_groups]

    report: dict[str, Any] = {
        "format": "latent-workspace-influence-map-v1",
        "baseline": str(Path(baseline_checkpoint).expanduser().resolve()),
        "induced": str(Path(induced_checkpoint).expanduser().resolve()),
        "harness_version": __version__,
        "source_sha256": source_sha256(),
        "displacement": displacement,
        "group_order": ordered_groups,
        "causal_swaps": {},
    }
    if causal_swaps:
        eval_files = induced_config.data.eval_files
        if not eval_files:
            raise ValueError("Causal influence mapping requires evaluation files.")
        dataset = JsonlFineTuningDataset(
            eval_files, tokenizer, induced_config.data
        )
        collator = CausalFineTuningCollator(
            tokenizer.pad_token_id, induced_config.data.pad_to_multiple_of
        )
        dataloader = build_eval_dataloader(
            dataset,
            collator,
            config=induced_config.data,
            batch_size=induced_config.train.eval_batch_size,
            seed=induced_config.train.seed + 17,
        )
        precision = resolve_mixed_precision(
            induced_config.train.mixed_precision, device
        )
        limit = eval_batches if eval_batches > 0 else induced_config.train.eval_batches
        baseline_metrics = evaluate(
            baseline,
            dataloader,
            device=device,
            precision=precision,
            workspace_loss_weight=0.0,
            max_batches=limit,
            compute_spectral=False,
            compute_workspace_loss=False,
            bypass_workspace=True,
        )
        induced_metrics = evaluate(
            induced,
            dataloader,
            device=device,
            precision=precision,
            workspace_loss_weight=0.0,
            max_batches=limit,
            compute_spectral=False,
            compute_workspace_loss=False,
            bypass_workspace=True,
        )
        names_by_group = _group_parameter_names(baseline)
        group_results: dict[str, Any] = {}
        for group in ordered_groups:
            names = names_by_group[group]
            transplant_backup = _copy_parameter_group(induced, baseline, names)
            try:
                transplant = evaluate(
                    baseline,
                    dataloader,
                    device=device,
                    precision=precision,
                    workspace_loss_weight=0.0,
                    max_batches=limit,
                    compute_spectral=False,
                    compute_workspace_loss=False,
                    bypass_workspace=True,
                )
            finally:
                _restore_parameter_group(baseline, transplant_backup)

            swap_backup = _copy_parameter_group(baseline, induced, names)
            try:
                swap_back = evaluate(
                    induced,
                    dataloader,
                    device=device,
                    precision=precision,
                    workspace_loss_weight=0.0,
                    max_batches=limit,
                    compute_spectral=False,
                    compute_workspace_loss=False,
                    bypass_workspace=True,
                )
            finally:
                _restore_parameter_group(induced, swap_backup)

            group_results[group] = {
                "baseline_task_loss": baseline_metrics["task_loss"],
                "induced_task_loss": induced_metrics["task_loss"],
                "transplant_task_loss": transplant["task_loss"],
                "swap_back_task_loss": swap_back["task_loss"],
                "transplant_sufficiency": (
                    baseline_metrics["task_loss"] - transplant["task_loss"]
                ),
                "swap_back_necessity": (
                    swap_back["task_loss"] - induced_metrics["task_loss"]
                ),
            }
        report["causal_swaps"] = {
            "base_only": True,
            "baseline": baseline_metrics,
            "induced": induced_metrics,
            "groups": group_results,
        }

    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(output / "influence_map.json", report)
    return report


# =============================================================================
# Paired attribution audit (v6.0 invariant runner)
# =============================================================================


def _base_parameter_digest(model: LatentWorkspaceCausalLM) -> str:
    """Hash only the base-model parameters in a deterministic name order."""
    digest = hashlib.sha256()
    for name, parameter in sorted(model.base_model.named_parameters()):
        tensor = parameter.detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(tensor.dtype).encode("ascii"))
        digest.update(str(tuple(tensor.shape)).encode("ascii"))
        digest.update(tensor.view(torch.uint8).numpy().tobytes())
    return digest.hexdigest()


def _compare_base_parameters(
    left: LatentWorkspaceCausalLM,
    right: LatentWorkspaceCausalLM,
) -> dict[str, Any]:
    left_parameters = dict(left.base_model.named_parameters())
    right_parameters = dict(right.base_model.named_parameters())
    if left_parameters.keys() != right_parameters.keys():
        return {
            "equal": False,
            "reason": "parameter_name_mismatch",
            "left_only": sorted(left_parameters.keys() - right_parameters.keys())[:16],
            "right_only": sorted(right_parameters.keys() - left_parameters.keys())[:16],
            "max_abs_diff": float("inf"),
            "mismatched_tensors": -1,
        }
    maximum = 0.0
    mismatched = 0
    first_mismatches: list[str] = []
    for name in sorted(left_parameters):
        left_tensor = left_parameters[name].detach()
        right_tensor = right_parameters[name].detach()
        if left_tensor.shape != right_tensor.shape:
            return {
                "equal": False,
                "reason": f"shape_mismatch:{name}",
                "max_abs_diff": float("inf"),
                "mismatched_tensors": -1,
            }
        if not torch.equal(left_tensor, right_tensor):
            mismatched += 1
            if len(first_mismatches) < 16:
                first_mismatches.append(name)
            difference = (left_tensor.float() - right_tensor.float()).abs().max()
            maximum = max(maximum, float(difference.item()))
    return {
        "equal": mismatched == 0,
        "reason": "equal" if mismatched == 0 else "value_mismatch",
        "max_abs_diff": maximum,
        "mismatched_tensors": mismatched,
        "first_mismatches": first_mismatches,
    }


def _paired_audit_compatibility(
    left: ExperimentConfig,
    right: ExperimentConfig,
) -> None:
    """Reject pairings whose base update cannot be meaningfully compared."""
    checks = {
        "model": {
            "name_or_path": (left.model.name_or_path, right.model.name_or_path),
            "revision": (left.model.revision, right.model.revision),
            "train_mode": (left.model.train_mode, right.model.train_mode),
            "dtype": (left.model.dtype, right.model.dtype),
            "hidden_capture": (left.model.hidden_capture, right.model.hidden_capture),
        },
        "data": {
            "train_files": (left.data.train_files, right.data.train_files),
            "max_length": (left.data.max_length, right.data.max_length),
            "train_on_prompt": (left.data.train_on_prompt, right.data.train_on_prompt),
            "use_chat_template": (left.data.use_chat_template, right.data.use_chat_template),
            "add_bos": (left.data.add_bos, right.data.add_bos),
            "add_eos": (left.data.add_eos, right.data.add_eos),
        },
        "train": {
            "seed": (left.train.seed, right.train.seed),
            "optimizer": (left.train.optimizer, right.train.optimizer),
            "batch_size": (left.train.batch_size, right.train.batch_size),
            "gradient_accumulation_steps": (
                left.train.gradient_accumulation_steps,
                right.train.gradient_accumulation_steps,
            ),
            "learning_rate": (left.train.learning_rate, right.train.learning_rate),
            "weight_decay": (left.train.weight_decay, right.train.weight_decay),
            "adam_beta1": (left.train.adam_beta1, right.train.adam_beta1),
            "adam_beta2": (left.train.adam_beta2, right.train.adam_beta2),
            "adam_eps": (left.train.adam_eps, right.train.adam_eps),
            "warmup_ratio": (left.train.warmup_ratio, right.train.warmup_ratio),
            "mixed_precision": (
                left.train.mixed_precision,
                right.train.mixed_precision,
            ),
        },
        "attribution": {
            "clip_mode": (
                left.attribution.clip_mode,
                right.attribution.clip_mode,
            ),
            "base_max_grad_norm": (
                left.attribution.base_max_grad_norm,
                right.attribution.base_max_grad_norm,
            ),
        },
    }
    mismatches: list[str] = []
    for section, values in checks.items():
        for name, (left_value, right_value) in values.items():
            if left_value != right_value:
                mismatches.append(
                    f"{section}.{name}: {left_value!r} != {right_value!r}"
                )
    if mismatches:
        raise ValueError(
            "Paired attribution audit requires matching base-training inputs:\n- "
            + "\n- ".join(mismatches)
        )
    if left.train.distributed not in {"auto", "none"} or right.train.distributed not in {
        "auto",
        "none",
    }:
        raise ValueError("Paired attribution audit is a single-process diagnostic.")
    if not left.attribution.isolate_rng_streams or not right.attribution.isolate_rng_streams:
        raise ValueError("Both configs must enable attribution.isolate_rng_streams.")
    if left.attribution.clip_mode != "per_family" or right.attribution.clip_mode != "per_family":
        raise ValueError("Both configs must use attribution.clip_mode='per_family'.")


def _paired_audit_forward(
    model: LatentWorkspaceCausalLM,
    batch: Mapping[str, torch.Tensor],
    config: ExperimentConfig,
    *,
    device: torch.device,
    precision: str,
    global_step: int,
    microbatch_index: int,
    total_steps: int,
) -> tuple[dict[str, Any], float, bool]:
    status = induction_status(
        config.workspace,
        config.induction,
        global_step,
        total_steps,
    )
    bypass = bool(
        status.weight == 0.0
        and config.workspace.logit_residual_scale == 0.0
        and (
            not config.induction.enabled
            or config.induction.bypass_workspace_when_inactive
        )
    )
    streams = make_rng_streams(
        config.attribution,
        base_seed=config.train.seed,
        rank=0,
        global_step=global_step,
        microbatch_index=microbatch_index,
    )
    # The production runner obtains identical base-dropout streams by launching
    # paired configs independently with the same run seed. Inside this single
    # process audit, explicitly fork/reset that stream for each member.
    base_seed = deterministic_stream_seed(
        config.train.seed,
        0,
        global_step,
        microbatch_index,
        97_000_003,
    )
    with isolated_torch_rng(True, base_seed, device):
        with autocast_context(device, precision):
            output = model(
                input_ids=batch["input_ids"],
                attention_mask=batch["attention_mask"],
                labels=batch["labels"],
                prompt_mask=batch["prompt_mask"],
                context_mask=batch.get("context_mask"),
                query_mask=batch.get("query_mask"),
                example_group_ids=batch.get("example_group_ids"),
                world_group_ids=batch.get("world_group_ids"),
                counterfactual_group_ids=batch.get("counterfactual_group_ids"),
                answer_classes=batch.get("answer_classes"),
                **bridge_batch_kwargs(batch),
                **functional_batch_kwargs(batch),
                compute_workspace_loss=status.weight > 0.0,
                compute_spectral=False,
                bypass_workspace=bypass,
                rng_streams=streams,
            )
    return output, status.weight, bypass


def run_paired_attribution_audit(
    left_config: ExperimentConfig,
    right_config: ExperimentConfig,
    output_path: str | os.PathLike[str],
    *,
    device: torch.device,
    steps: int = 2,
    require_base_equality: bool = True,
) -> dict[str, Any]:
    """Run two configs in lockstep and audit v6.0 attribution invariants.

    The canonical use is A baseline versus B-local: route=0, auxiliary loss
    detached from the base, isolated RNG streams, and per-family clipping. Under
    those conditions, pre-update task NLL and every base parameter must remain
    bitwise equal after each optimizer step. Other pairs can be inspected with
    ``require_base_equality=False``.
    """
    if steps < 1:
        raise ValueError("steps must be positive.")
    _paired_audit_compatibility(left_config, right_config)
    configure_runtime_math(left_config.train)
    precision = resolve_mixed_precision(left_config.train.mixed_precision, device)
    if require_base_equality and precision == "fp16":
        raise ValueError(
            "Strict paired equality does not support fp16 because a shared "
            "GradScaler can couple workspace overflow to the base optimizer step. "
            "Use bf16 or full precision for the attribution audit."
        )

    set_global_seed(left_config.train.seed)
    left_model, tokenizer = build_workspace_model(left_config)
    set_global_seed(right_config.train.seed)
    right_model, _right_tokenizer = build_workspace_model(right_config)
    left_model.to(device)
    right_model.to(device)
    left_model.train()
    right_model.train()
    if left_config.model.train_mode == "workspace_only":
        left_model.base_model.eval()
        right_model.base_model.eval()

    initial_comparison = _compare_base_parameters(left_model, right_model)
    if not initial_comparison["equal"]:
        raise RuntimeError(
            "Paired models did not begin from identical base parameters: "
            + json.dumps(initial_comparison, ensure_ascii=False)
        )

    dataset = JsonlFineTuningDataset(
        left_config.data.train_files,
        tokenizer,
        left_config.data,
    )
    collator = CausalFineTuningCollator(
        tokenizer.pad_token_id,
        left_config.data.pad_to_multiple_of,
    )
    loader, sampler = build_train_dataloader(
        dataset,
        collator,
        config=left_config.data,
        batch_size=left_config.train.batch_size,
        seed=left_config.train.seed + left_config.data.shuffle_buffer_seed,
        num_replicas=1,
        rank=0,
    )
    left_optimizer = build_optimizer(left_model, left_config.train, device)
    right_optimizer = build_optimizer(right_model, right_config.train, device)
    left_scheduler = build_scheduler(left_optimizer, steps, left_config.train.warmup_ratio)
    right_scheduler = build_scheduler(right_optimizer, steps, right_config.train.warmup_ratio)
    left_scaler = make_grad_scaler(device, precision)
    right_scaler = make_grad_scaler(device, precision)

    rows: list[dict[str, Any]] = []
    epoch = 0
    completed = 0
    try:
        while completed < steps:
            sampler.set_epoch(epoch, 0)
            for window in _iter_windows(
                iter(loader),
                left_config.train.gradient_accumulation_steps,
            ):
                if completed >= steps:
                    break
                tokens = sum(
                    int(batch["labels"][:, 1:].ne(-100).sum().item())
                    for batch in window
                )
                if tokens <= 0:
                    raise RuntimeError("Audit window contains no supervised tokens.")
                left_optimizer.zero_grad(set_to_none=True)
                right_optimizer.zero_grad(set_to_none=True)
                preupdate_differences: list[float] = []
                left_workspace_weights: list[float] = []
                right_workspace_weights: list[float] = []
                bypass_pairs: list[list[bool]] = []

                for microbatch_index, raw_batch in enumerate(window):
                    batch = move_batch_to_device(raw_batch, device)
                    left_output, left_weight, left_bypass = _paired_audit_forward(
                        left_model,
                        batch,
                        left_config,
                        device=device,
                        precision=precision,
                        global_step=completed,
                        microbatch_index=microbatch_index,
                        total_steps=steps,
                    )
                    right_output, right_weight, right_bypass = _paired_audit_forward(
                        right_model,
                        batch,
                        right_config,
                        device=device,
                        precision=precision,
                        global_step=completed,
                        microbatch_index=microbatch_index,
                        total_steps=steps,
                    )
                    left_nll = left_output["task_nll_sum"]
                    right_nll = right_output["task_nll_sum"]
                    if left_nll is None or right_nll is None:
                        raise RuntimeError("Audit forward produced no task NLL.")
                    preupdate_differences.append(
                        abs(float(left_nll.detach().float().item()) - float(right_nll.detach().float().item()))
                    )
                    left_objective = (
                        left_nll / float(tokens)
                        + left_weight * left_output["workspace_loss"] / float(len(window))
                    )
                    right_objective = (
                        right_nll / float(tokens)
                        + right_weight * right_output["workspace_loss"] / float(len(window))
                    )
                    if not torch.isfinite(left_objective) or not torch.isfinite(right_objective):
                        raise FloatingPointError("Non-finite objective during paired audit.")
                    left_scaler.scale(left_objective).backward()
                    right_scaler.scale(right_objective).backward()
                    left_workspace_weights.append(left_weight)
                    right_workspace_weights.append(right_weight)
                    bypass_pairs.append([left_bypass, right_bypass])

                left_scaler.unscale_(left_optimizer)
                right_scaler.unscale_(right_optimizer)
                left_clip = clip_gradients(
                    left_model, left_config.train, left_config.attribution
                )
                right_clip = clip_gradients(
                    right_model, right_config.train, right_config.attribution
                )
                left_scaler.step(left_optimizer)
                right_scaler.step(right_optimizer)
                left_scaler.update()
                right_scaler.update()
                left_scheduler.step()
                right_scheduler.step()
                completed += 1

                comparison = _compare_base_parameters(left_model, right_model)
                row = {
                    "step": completed,
                    "maximum_preupdate_task_nll_abs_diff": max(preupdate_differences, default=0.0),
                    "preupdate_task_nll_bitwise_equal": all(value == 0.0 for value in preupdate_differences),
                    "base_parameters": comparison,
                    "left_base_sha256": _base_parameter_digest(left_model),
                    "right_base_sha256": _base_parameter_digest(right_model),
                    "left_workspace_weights": left_workspace_weights,
                    "right_workspace_weights": right_workspace_weights,
                    "workspace_bypassed_pairs": bypass_pairs,
                    "left_clip": {
                        key: value for key, value in left_clip.items() if key != "grad_norm_tensor"
                    },
                    "right_clip": {
                        key: value for key, value in right_clip.items() if key != "grad_norm_tensor"
                    },
                }
                rows.append(row)
                if require_base_equality and (
                    not row["preupdate_task_nll_bitwise_equal"]
                    or not comparison["equal"]
                ):
                    raise AssertionError(
                        "Paired attribution invariant failed at step "
                        f"{completed}: {json.dumps(row, ensure_ascii=False)}"
                    )
            epoch += 1

        report = {
            "format": "latent-workspace-paired-attribution-audit-v1",
            "harness_version": __version__,
            "source_sha256": source_sha256(),
            "left_output_dir": left_config.train.output_dir,
            "right_output_dir": right_config.train.output_dir,
            "device": str(device),
            "precision": precision,
            "steps": steps,
            "require_base_equality": require_base_equality,
            "initial_base_parameters": initial_comparison,
            "passed": all(
                row["preupdate_task_nll_bitwise_equal"]
                and row["base_parameters"]["equal"]
                for row in rows
            ),
            "rows": rows,
        }
        output = Path(output_path).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(output, report)
        return report
    finally:
        del left_optimizer, right_optimizer, left_model, right_model
        if device.type == "cuda":
            torch.cuda.empty_cache()


def _top_p_sample(
    logits: torch.Tensor,
    *,
    temperature: float,
    top_p: float,
) -> torch.Tensor:
    if temperature <= 0:
        return torch.argmax(logits, dim=-1, keepdim=True)

    logits = logits / temperature
    if top_p < 1.0:
        sorted_logits, sorted_indices = torch.sort(logits, descending=True, dim=-1)
        probabilities = F.softmax(sorted_logits, dim=-1)
        cumulative = torch.cumsum(probabilities, dim=-1)
        remove = cumulative > top_p
        remove[..., 1:] = remove[..., :-1].clone()
        remove[..., 0] = False
        sorted_logits = sorted_logits.masked_fill(remove, float("-inf"))
        probabilities = F.softmax(sorted_logits, dim=-1)
        sampled = torch.multinomial(probabilities, num_samples=1)
        return sorted_indices.gather(-1, sampled)

    probabilities = F.softmax(logits, dim=-1)
    return torch.multinomial(probabilities, num_samples=1)


@torch.no_grad()
def generate_text(
    model: LatentWorkspaceCausalLM,
    tokenizer: Any,
    prompt: str,
    *,
    device: torch.device,
    max_new_tokens: int = 128,
    temperature: float = 0.0,
    top_p: float = 0.95,
) -> str:
    if model.workspace_config.route_topology == "deferred_bridge":
        raise ValueError(
            "Free-form generation is not defined for deferred_bridge because it "
            "requires separately encoded context and continuation branches. Use "
            "choice-eval or the necessity assay for v8 bridge checkpoints."
        )
    input_ids_list = _tokenizer_encode(tokenizer, prompt)
    bos_id = getattr(tokenizer, "bos_token_id", None)
    if bos_id is not None and not input_ids_list:
        input_ids_list = [int(bos_id)]
    if not input_ids_list:
        raise ValueError("The prompt produced no tokens.")

    input_ids = torch.tensor([input_ids_list], dtype=torch.long, device=device)
    attention_mask = torch.ones_like(input_ids)
    eos_id = getattr(tokenizer, "eos_token_id", None)

    for _ in range(max_new_tokens):
        output = model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            compute_workspace_loss=False,
            compute_spectral=False,
            logits_to_keep=1,
        )
        if output["logits"] is None:
            raise RuntimeError("Generation requested logits but received none.")
        next_token = _top_p_sample(
            output["logits"][:, -1, :].float(),
            temperature=temperature,
            top_p=top_p,
        )
        input_ids = torch.cat([input_ids, next_token], dim=1)
        attention_mask = torch.cat(
            [attention_mask, torch.ones_like(next_token)],
            dim=1,
        )
        if eos_id is not None and int(next_token.item()) == int(eos_id):
            break

    return tokenizer.decode(input_ids[0].tolist(), skip_special_tokens=True)


# =============================================================================
# Synthetic deferred-relation data for a first FT smoke experiment
# =============================================================================


_DEMO_NAMES = [
    "Aster",
    "Beryl",
    "Cyra",
    "Doran",
    "Eris",
    "Fenn",
    "Galen",
    "Hira",
]


def _make_relation_world(rng: random.Random, width: int = 5) -> tuple[list[str], list[str]]:
    names = rng.sample(_DEMO_NAMES, width)
    ordered = names[:]
    rng.shuffle(ordered)
    facts = [
        f"{ordered[index]} is ranked above {ordered[index + 1]}."
        for index in range(width - 1)
    ]
    rng.shuffle(facts)
    return ordered, facts


def make_demo_records(
    *,
    worlds: int,
    queries_per_world: int,
    seed: int,
    balanced_by_distance: bool = False,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    records: list[dict[str, Any]] = []
    system = (
        "Maintain the relation structure until the query is resolved. "
        "Answer accurately and briefly."
    )

    for world_index in range(worlds):
        ordered, facts = _make_relation_world(rng)
        context = "World facts:\n" + "\n".join(f"- {fact}" for fact in facts)

        if balanced_by_distance:
            pairs: list[tuple[str, str]] = []
            distances = list(range(1, len(ordered)))
            for query_index in range(queries_per_world):
                distance = distances[query_index % len(distances)]
                left_rank = rng.randrange(0, len(ordered) - distance)
                right_rank = left_rank + distance
                left, right = ordered[left_rank], ordered[right_rank]
                if rng.random() < 0.5:
                    left, right = right, left
                pairs.append((left, right))
        else:
            pairs = [
                (left, right)
                for left in ordered
                for right in ordered
                if left != right
            ]
            rng.shuffle(pairs)
            pairs = pairs[:queries_per_world]

        for query_index, (left, right) in enumerate(pairs):
            left_rank = ordered.index(left)
            right_rank = ordered.index(right)
            higher = left if left_rank < right_rank else right
            lower = right if higher == left else left
            distance = abs(left_rank - right_rank)

            query = f"Which is ranked higher, {left} or {right}?"
            correct = (
                f"{higher} is ranked higher than {lower}. "
                f"Their rank distance is {distance}."
            )
            incorrect = (
                f"{lower} is ranked higher than {higher}. "
                f"Their rank distance is {distance}."
            )
            if rng.random() < 0.5:
                choices = [correct, incorrect]
                answer_index = 0
            else:
                choices = [incorrect, correct]
                answer_index = 1
            records.append(
                {
                    "system": system,
                    "context": context,
                    "query": query,
                    "response": correct,
                    "choices": choices,
                    "answer_index": answer_index,
                    "metadata": {
                        "world_id": world_index,
                        "query_id": query_index,
                        "rank_distance": distance,
                    },
                }
            )
    return records


def make_counterfactual_twin_records(
    *,
    pairs: int,
    seed: int,
    width: int = 6,
    balanced_by_distance: bool = True,
    family: str = "semantic_bit",
) -> list[dict[str, Any]]:
    """Generate matched twins with identical query and opposite one-token labels.

    ``semantic_bit`` is the load-bearing positive-control task. The two twins
    differ only in a sealed context bit; a query-only or fixed-carrier route has
    a Bayes ceiling of 50%, while exact twin-memory replacement should reverse
    every answer once content is genuinely carried.

    ``direct_relation`` is the next semantic rung. It replaces the explicit bit
    with a mirrored natural-language relation plus matched distractors. It is a
    harder stress plane, not the foundational route-wiring check.
    """
    if pairs < 1:
        raise ValueError("pairs must be positive.")
    if width < 5 or width > 8:
        raise ValueError("width must be between 5 and 8.")
    if family not in {"semantic_bit", "direct_relation"}:
        raise ValueError("family must be semantic_bit or direct_relation.")

    rng = random.Random(seed)
    alphabet = list("ABCDEFGH")
    records: list[dict[str, Any]] = []
    for pair_index in range(pairs):
        nonce = f"vault-{pair_index:05d}"
        if family == "semantic_bit":
            system = ""
            query = "bit?"
            # Keep this foundational plane intentionally minimal. It proves
            # content transport and answer reversal before the relation plane
            # adds language understanding as a separate burden.
            contexts = (
                f"bit 0 id{pair_index:05d}",
                f"bit 1 id{pair_index:05d}",
            )
            semantic_depth = 0
        else:
            entities = rng.sample(alphabet, width)
            left, right = entities[0], entities[1]
            distractor_pairs = list(zip(entities[2::2], entities[3::2]))
            distractors = " ".join(
                f"{a} is higher than {b}." for a, b in distractor_pairs
            )
            system = (
                "Use only the context facts. Reply with exactly 0 when the "
                "first queried item is higher, otherwise reply with exactly 1."
            )
            query = (
                f"Compare {left} and {right}. If {left} is higher, answer 0. "
                f"If {right} is higher, answer 1."
            )
            contexts = (
                f"Key fact: {left} is higher than {right}. Other facts: {distractors}",
                f"Key fact: {right} is higher than {left}. Other facts: {distractors}",
            )
            semantic_depth = 1

        query_signature = hashlib.sha256(query.encode("utf-8")).hexdigest()
        for side, context in enumerate(contexts):
            answer_class = side
            response = str(answer_class)
            records.append(
                {
                    "system": system,
                    "context": context,
                    "query": query,
                    "response": response,
                    "choices": ["0", "1"],
                    "answer_index": answer_class,
                    "metadata": {
                        "world_id": f"{family}-{pair_index}-side-{side}",
                        "counterfactual_pair_id": f"{family}-{pair_index}",
                        "twin_side": side,
                        "answer_class": answer_class,
                        "rank_distance": semantic_depth + 1,
                        "semantic_depth": semantic_depth,
                        "semantic_family": family,
                        "query_signature": query_signature,
                    },
                }
            )
    return records


_FUNCTIONAL_RELATION_NAMES = [
    "Aster",
    "Beryl",
    "Cyra",
    "Doran",
    "Eris",
    "Fenn",
    "Galen",
    "Hira",
    "Ione",
    "Joren",
    "Kestrel",
    "Luma",
]


def _functional_relation_context(order: Sequence[str], rng: random.Random) -> str:
    facts = [
        f"{order[index]} is ranked above {order[index + 1]}."
        for index in range(len(order) - 1)
    ]
    rng.shuffle(facts)
    return (
        "World facts. The ranking is transitive.\n"
        + "\n".join(f"- {fact}" for fact in facts)
    )


def _functional_relation_answer(order: Sequence[str], left: str, right: str) -> int:
    if left == right:
        raise ValueError("A relation query requires two distinct entities.")
    rank = {name: index for index, name in enumerate(order)}
    return int(rank[left] < rank[right])


def make_functional_relation_pair_records(
    *,
    worlds: int,
    seed: int,
    width: int = 6,
    queries_per_world: int = 8,
    query_template: str = "Is {left} ranked above {right}? Answer:",
    heldout_template: Optional[str] = None,
    heldout_fraction: float = 0.0,
) -> list[dict[str, Any]]:
    """Create v9 local-counterfactual worlds with reusable future queries.

    Each JSONL row contains two worlds. The second world is produced by one
    adjacent swap. Queries compare the same entity pairs under both worlds.
    Exactly the two directed queries about the swapped pair are affected; the
    remaining queries must stay invariant under the local edit.
    """
    if worlds < 1:
        raise ValueError("worlds must be positive.")
    if width < 6 or width > len(_FUNCTIONAL_RELATION_NAMES):
        raise ValueError(
            f"width must be in [6, {len(_FUNCTIONAL_RELATION_NAMES)}]."
        )
    if queries_per_world != 8:
        raise ValueError(
            "The canonical v9 local-edit contract currently fixes "
            "queries_per_world=8 so affected and unaffected strata remain "
            "identical across runs."
        )
    if not 0.0 <= heldout_fraction <= 1.0:
        raise ValueError("heldout_fraction must be in [0, 1].")

    rng = random.Random(seed)
    records: list[dict[str, Any]] = []
    for world_index in range(worlds):
        order0 = rng.sample(_FUNCTIONAL_RELATION_NAMES, width)
        # Keep the edit internal. This prevents the twin from being reducible
        # to a trivial top/bottom marker while preserving a strict local swap.
        swap_index = rng.randrange(1, width - 2)
        order1 = list(order0)
        order1[swap_index], order1[swap_index + 1] = (
            order1[swap_index + 1],
            order1[swap_index],
        )
        swapped_left = order0[swap_index]
        swapped_right = order0[swap_index + 1]

        # Two affected directions plus three unaffected relation pairs in both
        # directions. Adjacent swaps preserve every pairwise relation except
        # the relation between the two swapped entities themselves.
        unaffected_adjacent_index = 0
        if {order0[0], order0[1]} == {swapped_left, swapped_right}:
            unaffected_adjacent_index = width - 2
        query_pairs: list[tuple[str, str]] = [
            (swapped_left, swapped_right),
            (swapped_right, swapped_left),
            (order0[0], order0[-1]),
            (order0[-1], order0[0]),
            (
                order0[unaffected_adjacent_index],
                order0[unaffected_adjacent_index + 1],
            ),
            (
                order0[unaffected_adjacent_index + 1],
                order0[unaffected_adjacent_index],
            ),
            (swapped_left, order0[-1]),
            (order0[-1], swapped_left),
        ]
        if len(set(query_pairs)) != queries_per_world:
            raise AssertionError("Canonical v9 query construction produced duplicates.")

        queries: list[str] = []
        heldout_queries: list[bool] = []
        heldout_count = int(round(queries_per_world * heldout_fraction))
        heldout_indices = set(range(queries_per_world - heldout_count, queries_per_world))
        for query_index, (left, right) in enumerate(query_pairs):
            is_heldout = query_index in heldout_indices and heldout_template is not None
            template = heldout_template if is_heldout else query_template
            assert template is not None
            queries.append(template.format(left=left, right=right))
            heldout_queries.append(bool(is_heldout))

        answers0 = [
            _functional_relation_answer(order0, left, right)
            for left, right in query_pairs
        ]
        answers1 = [
            _functional_relation_answer(order1, left, right)
            for left, right in query_pairs
        ]
        affected = [a != b for a, b in zip(answers0, answers1)]
        if sum(affected) != 2:
            raise AssertionError(
                "An adjacent order swap must affect exactly the two directed "
                "queries between the swapped entities."
            )
        if not any(affected) or all(affected):
            raise AssertionError("v9 records require affected and unaffected queries.")

        rank0 = {name: index for index, name in enumerate(order0)}
        hop_distances = [abs(rank0[left] - rank0[right]) for left, right in query_pairs]
        pair_id = f"functional-relation-{seed}-{world_index:06d}"
        records.append(
            {
                "format": "functional_world_pair_v9",
                "contexts": [
                    _functional_relation_context(order0, random.Random(seed * 31 + world_index * 2)),
                    _functional_relation_context(order1, random.Random(seed * 31 + world_index * 2 + 1)),
                ],
                "queries": queries,
                "answers": [answers0, answers1],
                "choices": [" 0", " 1"],
                "affected": affected,
                "hop_distances": hop_distances,
                "heldout_queries": heldout_queries,
                "metadata": {
                    "pair_id": pair_id,
                    "world_pair_id": pair_id,
                    "edit_type": "local_adjacent_swap",
                    "swap_index": swap_index,
                    "swapped_entities": [swapped_left, swapped_right],
                    "orders": [list(order0), list(order1)],
                    "query_pairs": [list(pair) for pair in query_pairs],
                    "data_seed": seed,
                    "world_index": world_index,
                },
            }
        )
    return records


def audit_functional_world_pair_dataset(
    files: Sequence[str],
    tokenizer: Any,
    data_config: DataConfig,
    *,
    minimum_queries: int = 4,
    require_affected_and_unaffected: bool = True,
) -> dict[str, Any]:
    """Fail closed on v9 grouped-world and local-counterfactual contracts."""
    records = _read_jsonl_objects(files)
    errors: list[str] = []
    warnings: list[str] = []
    query_counts: list[int] = []
    affected_counts: list[int] = []
    unaffected_counts: list[int] = []
    heldout_counts: list[int] = []
    pair_ids: set[str] = set()
    context_hashes: set[str] = set()
    query_only_affected_correct = 0
    query_only_affected_total = 0
    encoded_features: list[dict[str, Any]] = []

    for index, record in enumerate(records):
        if record.get("format") != "functional_world_pair_v9":
            errors.append(f"record {index}: format must be functional_world_pair_v9")
            continue
        contexts = record.get("contexts")
        queries = record.get("queries")
        answers = record.get("answers")
        affected = record.get("affected")
        metadata = record.get("metadata", {})
        if not isinstance(metadata, Mapping):
            metadata = {}
        pair_id = str(metadata.get("pair_id", metadata.get("world_pair_id", "")))
        if not pair_id:
            errors.append(f"record {index}: missing metadata.pair_id")
        elif pair_id in pair_ids:
            errors.append(f"record {index}: duplicate pair_id {pair_id!r}")
        else:
            pair_ids.add(pair_id)

        if not isinstance(contexts, Sequence) or isinstance(contexts, (str, bytes)) or len(contexts) != 2:
            errors.append(f"record {index}: contexts must contain exactly two strings")
            continue
        if str(contexts[0]) == str(contexts[1]):
            errors.append(f"record {index}: twin contexts are identical")
        for context in contexts:
            digest = hashlib.sha256(str(context).encode("utf-8")).hexdigest()
            context_hashes.add(digest)

        if not isinstance(queries, Sequence) or isinstance(queries, (str, bytes)):
            errors.append(f"record {index}: queries must be a sequence")
            continue
        qcount = len(queries)
        query_counts.append(qcount)
        if qcount < minimum_queries:
            errors.append(
                f"record {index}: {qcount} queries, requires at least {minimum_queries}"
            )
        if len(set(str(query) for query in queries)) != qcount:
            errors.append(f"record {index}: duplicate future queries")

        if not isinstance(answers, Sequence) or len(answers) != 2:
            errors.append(f"record {index}: answers must have two sides")
            continue
        try:
            side0 = [int(value) for value in answers[0]]
            side1 = [int(value) for value in answers[1]]
        except Exception:
            errors.append(f"record {index}: answers must be integer lists")
            continue
        if len(side0) != qcount or len(side1) != qcount:
            errors.append(f"record {index}: answers do not align with queries")
            continue
        derived_affected = [left != right for left, right in zip(side0, side1)]
        if affected is None:
            affected_values = derived_affected
        else:
            affected_values = [bool(value) for value in affected]
            if affected_values != derived_affected:
                errors.append(f"record {index}: affected mask disagrees with twin answers")
        affected_count = sum(affected_values)
        unaffected_count = qcount - affected_count
        affected_counts.append(affected_count)
        unaffected_counts.append(unaffected_count)
        if require_affected_and_unaffected and (
            affected_count == 0 or unaffected_count == 0
        ):
            errors.append(
                f"record {index}: requires both affected and unaffected queries"
            )
        query_only_affected_correct += affected_count
        query_only_affected_total += affected_count * 2

        heldout = record.get("heldout_queries", [])
        heldout_values = [bool(value) for value in heldout] if heldout else [False] * qcount
        if len(heldout_values) != qcount:
            errors.append(f"record {index}: heldout_queries does not align")
        heldout_counts.append(sum(heldout_values))

        orders = metadata.get("orders")
        query_pairs = metadata.get("query_pairs")
        if isinstance(orders, Sequence) and len(orders) == 2 and isinstance(query_pairs, Sequence):
            try:
                recomputed = [
                    [
                        _functional_relation_answer(orders[side], str(pair[0]), str(pair[1]))
                        for pair in query_pairs
                    ]
                    for side in range(2)
                ]
                if recomputed != [side0, side1]:
                    errors.append(f"record {index}: answers disagree with declared world orders")
            except Exception as exc:
                errors.append(f"record {index}: invalid order/query metadata: {exc}")

        try:
            feature = _encode_functional_world_pair(record, tokenizer, data_config)
            encoded_features.append(feature)
        except Exception as exc:
            errors.append(
                f"record {index}: tokenization/encoding failed: {type(exc).__name__}: {exc}"
            )

    collated_shape: dict[str, Any] = {}
    if encoded_features:
        try:
            collator = CausalFineTuningCollator(
                pad_token_id=int(tokenizer.pad_token_id),
                pad_to_multiple_of=max(1, int(data_config.pad_to_multiple_of)),
            )
            sample = collator(encoded_features[: min(4, len(encoded_features))])
            collated_shape = {
                "context": list(sample["functional_context_input_ids"].shape),
                "query": list(sample["functional_query_input_ids"].shape),
                "answers": list(sample["functional_answer_classes"].shape),
            }
            if int(sample["functional_query_valid_mask"].sum().item()) <= 0:
                errors.append("collated functional batch has no valid queries")
        except Exception as exc:
            errors.append(
                f"functional collator failed: {type(exc).__name__}: {exc}"
            )

    # For every affected query the exact same query is paired with opposite
    # labels across the two worlds. A query-only classifier therefore has a
    # strict 50% paired ceiling on the affected subset.
    affected_query_only_ceiling = (
        query_only_affected_correct / query_only_affected_total
        if query_only_affected_total
        else 1.0
    )
    if query_only_affected_total and not math.isclose(
        affected_query_only_ceiling, 0.5, abs_tol=1e-12
    ):
        errors.append(
            "affected paired-query ceiling must be exactly 0.5, found "
            f"{affected_query_only_ceiling:.6f}"
        )

    return {
        "format": "latent-workspace-v9-functional-world-audit-v1",
        "harness_version": __version__,
        "passed": not errors,
        "records": len(records),
        "unique_pair_ids": len(pair_ids),
        "unique_contexts": len(context_hashes),
        "query_count_min": min(query_counts) if query_counts else 0,
        "query_count_max": max(query_counts) if query_counts else 0,
        "affected_count_min": min(affected_counts) if affected_counts else 0,
        "affected_count_max": max(affected_counts) if affected_counts else 0,
        "unaffected_count_min": min(unaffected_counts) if unaffected_counts else 0,
        "unaffected_count_max": max(unaffected_counts) if unaffected_counts else 0,
        "heldout_query_total": sum(heldout_counts),
        "affected_query_only_bayes_ceiling": affected_query_only_ceiling,
        "collated_shape": collated_shape,
        "errors": errors,
        "warnings": warnings,
        "claim_boundary": (
            "Passing proves grouped multi-query structure, exact local-twin "
            "answer direction, affected/unaffected coverage, and tokenization "
            "integrity. It does not prove that a trained model uses memory."
        ),
    }

def write_jsonl_records(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(dict(record), ensure_ascii=False) + "\n")


def _configure_loss_family(config: ExperimentConfig, family: str) -> None:
    loss = config.workspace.loss
    values = {
        "lambda_var": 0.0,
        "lambda_cov": 0.0,
        "lambda_info": 0.0,
        "lambda_contrast": 0.0,
        "lambda_relation": 0.0,
        "lambda_temporal": 0.0,
        "lambda_worst": 0.0,
        "lambda_rank": 0.0,
    }
    if family == "full":
        values.update(
            lambda_var=1.0,
            lambda_cov=1.0,
            lambda_info=0.5,
            lambda_contrast=0.25,
            lambda_relation=0.10,
            lambda_temporal=0.10,
            lambda_worst=0.25,
            lambda_rank=0.05,
        )
    elif family == "geometry":
        values.update(lambda_var=1.0, lambda_cov=1.0, lambda_rank=0.05)
    elif family == "structure":
        values.update(lambda_contrast=0.25, lambda_relation=0.10)
    elif family == "formation":
        values.update(
            lambda_var=1.0,
            lambda_cov=1.0,
            lambda_rank=0.05,
            lambda_contrast=0.25,
            lambda_relation=0.10,
        )
    elif family == "retention":
        values.update(lambda_info=0.5, lambda_temporal=0.10, lambda_worst=0.25)
    elif family == "none":
        pass
    else:
        raise ValueError(f"Unknown loss family: {family}")
    for name, value in values.items():
        setattr(loss, name, value)


def _scheduler_multiplier(total_steps: int, warmup_ratio: float, step: int) -> float:
    warmup_steps = int(round(total_steps * max(0.0, warmup_ratio)))
    if warmup_steps > 0 and step < warmup_steps:
        return float(step + 1) / float(warmup_steps)
    remaining = max(1, total_steps - warmup_steps)
    progress = min(1.0, max(0.0, (step - warmup_steps) / remaining))
    return 0.5 * (1.0 + math.cos(math.pi * progress))


def _window_lr_exposure(
    *,
    total_steps: int,
    warmup_ratio: float,
    start: int,
    end: int,
) -> float:
    return sum(
        _scheduler_multiplier(total_steps, warmup_ratio, step)
        for step in range(max(0, start), min(total_steps, end))
    )


def initialize_v7_transition_directory(
    directory: str | os.PathLike[str],
    *,
    model_name: str,
) -> Path:
    """Create the v7 transition, route, and causal-necessity matrices."""
    root = Path(directory).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    train_path = root / "demo_train.jsonl"
    eval_path = root / "demo_eval.jsonl"
    write_jsonl_records(
        train_path,
        make_demo_records(
            worlds=64,
            queries_per_world=4,
            seed=71,
            balanced_by_distance=True,
        ),
    )
    write_jsonl_records(
        eval_path,
        make_demo_records(
            worlds=16,
            queries_per_world=4,
            seed=911,
            balanced_by_distance=True,
        ),
    )

    base = ExperimentConfig()
    base.model.name_or_path = model_name
    base.data.train_files = [train_path.name]
    base.data.eval_files = [eval_path.name]
    base.data.use_chat_template = False
    base.data.fingerprint_mode = "full"
    base.workspace.architecture = "causal_broadcast"
    base.workspace.route_topology = "inline"
    base.workspace.anchor_refresh = "initial_only"
    base.workspace.scope = "context_tail"
    base.workspace.logit_residual_scale = 0.0
    base.workspace.loss_weight = base.transition.reference_weight
    base.workspace.loss_warmup_steps = 0
    base.workspace.spectral_every = 8
    base.train.epochs = 3
    base.train.resume_from = "auto"
    base.train.strict_resume = True
    base.train.log_every = 1
    base.train.eval_every = 8
    base.train.save_every = 8
    base.attribution.isolate_rng_streams = True
    base.attribution.clip_mode = "per_family"
    base.attribution.base_max_grad_norm = 1.0
    base.attribution.workspace_max_grad_norm = 1.0
    base.induction.enabled = True
    base.induction.schedule = "early_pulse"
    base.induction.start_fraction = 0.0
    base.induction.end_fraction = 0.25
    base.induction.bypass_workspace_when_inactive = True
    base.induction.save_phase_boundaries = True
    base.assays.amputation_eval = True
    base.assays.amputation_eval_every = 8
    base.assays.gradient_alignment_every = 0
    base.assays.recruitment.enabled = True
    base.assays.recruitment.train_files = [train_path.name]
    base.assays.recruitment.eval_files = [eval_path.name]
    base.assays.recruitment.ranks = [4, 16, 64]
    base.assays.recruitment.max_steps = 100
    base.assays.recruitment.eval_every = 10
    base.assays.choice_eval.enabled = True
    base.assays.choice_eval.batch_size = 8

    train_records = 64 * 4
    global_batches = math.ceil(train_records / base.train.batch_size)
    optimizer_steps_per_epoch = math.ceil(
        global_batches / base.train.gradient_accumulation_steps
    )
    total_steps = base.train.epochs * optimizer_steps_per_epoch
    early_start, early_end = 0, int(math.ceil(0.25 * total_steps))
    late_start, late_end = int(math.floor(0.50 * total_steps)), int(
        math.ceil(0.75 * total_steps)
    )
    reference_weight = float(base.transition.reference_weight)
    early_lr_sum = _window_lr_exposure(
        total_steps=total_steps,
        warmup_ratio=base.train.warmup_ratio,
        start=early_start,
        end=early_end,
    )
    late_lr_sum = _window_lr_exposure(
        total_steps=total_steps,
        warmup_ratio=base.train.warmup_ratio,
        start=late_start,
        end=late_end,
    )
    all_lr_sum = _window_lr_exposure(
        total_steps=total_steps,
        warmup_ratio=base.train.warmup_ratio,
        start=0,
        end=total_steps,
    )
    late_matched_weight = reference_weight * early_lr_sum / max(late_lr_sum, 1e-12)
    constant_matched_weight = reference_weight * early_lr_sum / max(all_lr_sum, 1e-12)

    variants: dict[str, dict[str, Any]] = {
        "A_baseline": {
            "family": "none", "weight": 0.0, "route": 0.0,
            "aux_base": False, "induction": False, "schedule": "constant",
        },
        "B_local_invariance": {
            "family": "full", "weight": reference_weight, "route": 0.0,
            "aux_base": False, "induction": True, "schedule": "constant",
        },
        # Complete the ordinary inline 2x2: A, J, C100, I.
        "J_route_only_inline": {
            "family": "none", "weight": 0.0, "route": 1.0,
            "aux_base": False, "induction": False, "schedule": "constant",
        },
        "I_induced_route_inline": {
            "family": "full", "weight": reference_weight, "route": 1.0,
            "aux_base": True, "induction": True, "schedule": "early_pulse",
            "start": 0.0, "end": 0.25,
        },
        # LR-weighted timing controls with washout after both pulses.
        "D_late_washout_lrmatched": {
            "family": "full", "weight": late_matched_weight, "route": 0.0,
            "aux_base": True, "induction": True, "schedule": "window",
            "start": 0.50, "end": 0.75,
        },
        "E_constant_lrmatched": {
            "family": "full", "weight": constant_matched_weight, "route": 0.0,
            "aux_base": True, "induction": True, "schedule": "constant",
        },
    }

    for multiplier in base.transition.dose_multipliers:
        label = f"{int(round(multiplier * 100)):03d}"
        variants[f"C_dose_{label}"] = {
            "family": "full",
            "weight": reference_weight * float(multiplier),
            "route": 0.0,
            "aux_base": True,
            "induction": True,
            "schedule": "early_pulse",
            "start": 0.0,
            "end": 0.25,
            "dose_multiplier": float(multiplier),
        }

    # Component decomposition at the linear reference and a high-dose probe.
    for multiplier in (1.0, 4.0):
        label = f"{int(round(multiplier * 100)):03d}"
        for prefix, family in (
            ("F_geometry", "geometry"),
            ("G_structure", "structure"),
            ("H_retention", "retention"),
        ):
            variants[f"{prefix}_{label}"] = {
                "family": family,
                "weight": reference_weight * multiplier,
                "route": 0.0,
                "aux_base": True,
                "induction": True,
                "schedule": "early_pulse",
                "start": 0.0,
                "end": 0.25,
                "dose_multiplier": multiplier,
            }

    # Deferred-memory plane. Query/response tokens are encoded without context;
    # the route is the only context-bearing path into task logits.
    bridge_variants = {
        "N0_bridge_base": ("none", 0.0, 0.0, False),
        "N1_bridge_route_only": ("none", 0.0, 1.0, False),
        "N2_bridge_aux_only": ("full", reference_weight, 0.0, True),
        "N3_bridge_aux_route": ("full", reference_weight, 1.0, True),
    }
    for name, (family, weight, route, induction) in bridge_variants.items():
        variants[name] = {
            "family": family,
            "weight": weight,
            "route": route,
            "aux_base": induction,
            "induction": induction,
            "schedule": "early_pulse" if induction else "constant",
            "start": 0.0,
            "end": 0.25,
            "route_topology": "deferred_bridge",
            "necessity": route > 0.0,
        }

    expected: dict[str, Any] = {}
    # Engineering-only attribution pair. It is not part of the semantic 2x2:
    # the auxiliary objective is active locally, but detached from the base.
    # Under isolated RNG streams and per-family clipping, its base trajectory
    # must remain bitwise identical to A in the paired lockstep audit.
    attribution_local = ExperimentConfig.from_dict(asdict(base))
    _configure_loss_family(attribution_local, "full")
    attribution_local.workspace.route_topology = "deferred_bridge"
    attribution_local.workspace.deferred_memory_source = "workspace"
    attribution_local.workspace.logit_residual_scale = 0.0
    attribution_local.workspace.loss_weight = 0.02
    attribution_local.workspace.aux_backprop_to_base = False
    attribution_local.induction.enabled = True
    attribution_local.induction.schedule = "early_pulse"
    attribution_local.induction.start_fraction = 0.0
    attribution_local.induction.end_fraction = 0.25
    attribution_local.assays.necessity.enabled = False
    attribution_local.train.output_dir = "run_B_local_invariance"
    attribution_local.to_json(root / "config_B_local_invariance.json")

    for name, settings in variants.items():
        variant = ExperimentConfig.from_dict(asdict(base))
        _configure_loss_family(variant, str(settings["family"]))
        variant.workspace.loss_weight = float(settings["weight"])
        variant.workspace.logit_residual_scale = float(settings["route"])
        variant.workspace.aux_backprop_to_base = bool(settings["aux_base"])
        variant.workspace.route_topology = str(
            settings.get("route_topology", "inline")
        )
        variant.induction.enabled = bool(settings["induction"])
        variant.induction.schedule = str(settings["schedule"])
        variant.induction.start_fraction = float(settings.get("start", 0.0))
        variant.induction.end_fraction = float(settings.get("end", 1.0))
        variant.assays.necessity.enabled = bool(settings.get("necessity", False))
        variant.train.output_dir = f"run_{name}"
        variant.to_json(root / f"config_{name}.json")

        start, end = _induction_bounds(variant.induction, total_steps)
        scheduler_weighted_dose = float(settings["weight"]) * _window_lr_exposure(
            total_steps=total_steps,
            warmup_ratio=variant.train.warmup_ratio,
            start=start,
            end=end,
        )
        expected[name] = {
            "loss_family": settings["family"],
            "weight": float(settings["weight"]),
            "route": float(settings["route"]),
            "route_topology": variant.workspace.route_topology,
            "start_step": start,
            "end_step": end,
            "nominal_dose": float(settings["weight"]) * max(0, end - start),
            # Kept as an alias for pre-v7 analysis notebooks. This is weighted
            # by the unitless scheduler multiplier, not by the absolute LR.
            "lr_weighted_exposure": scheduler_weighted_dose,
            "scheduler_weighted_dose": scheduler_weighted_dose,
            "expected_lr_weighted_base_dose": (
                scheduler_weighted_dose * float(variant.train.learning_rate)
            ),
            "expected_lr_weighted_workspace_dose": (
                scheduler_weighted_dose
                * float(variant.train.workspace_learning_rate)
            ),
            "dose_multiplier": settings.get("dose_multiplier"),
        }

    trace = ExperimentConfig.from_json(root / "config_C_dose_100.json")
    trace.data.train_files = [train_path.name]
    trace.data.eval_files = [eval_path.name]
    trace.assays.recruitment.train_files = [train_path.name]
    trace.assays.recruitment.eval_files = [eval_path.name]
    trace.assays.gradient_alignment_every = 4
    trace.train.output_dir = "run_C_dose_100_trace"
    trace.to_json(root / "config_C_dose_100_trace.json")

    primary = ExperimentConfig.from_json(root / "config_C_dose_100.json")
    primary.data.train_files = [train_path.name]
    primary.data.eval_files = [eval_path.name]
    primary.assays.recruitment.train_files = [train_path.name]
    primary.assays.recruitment.eval_files = [eval_path.name]
    primary.train.output_dir = "run_C_dose_100"
    primary.to_json(root / "config.json")

    canonical_order = list(variants)
    matrix = {
        "format": "latent-workspace-v7-matrix-v1",
        "harness_version": __version__,
        "model": model_name,
        "total_steps": total_steps,
        "balanced_distance_counts": {"1": 16, "2": 16, "3": 16, "4": 16},
        "canonical_order": canonical_order,
        "attribution_pair": {
            "left": "A_baseline",
            "right": "B_local_invariance",
            "strict_base_equality": True,
        },
        "condition_groups": {
            "attribution": ["A_baseline", "B_local_invariance"],
            "inline_2x2": [
                "A_baseline", "J_route_only_inline", "C_dose_100",
                "I_induced_route_inline",
            ],
            "dose_sweep": [
                name for name in canonical_order if name.startswith("C_dose_")
            ],
            "timing_lrmatched": [
                "C_dose_100", "D_late_washout_lrmatched", "E_constant_lrmatched"
            ],
            "components_reference": [
                "C_dose_100", "F_geometry_100", "G_structure_100", "H_retention_100"
            ],
            "components_high": [
                "C_dose_400", "F_geometry_400", "G_structure_400", "H_retention_400"
            ],
            "deferred_bridge_2x2": list(bridge_variants),
        },
        "expected_exposure": expected,
        "primary_claim": (
            "Locate departures from the v6.5 linear-response regime, measure "
            "washout persistence/recruitability, and test content-specific "
            "causal use of deferred workspace memory."
        ),
    }
    _atomic_write_json(root / "MATRIX.json", matrix)
    return root


# =============================================================================
# CLI
# =============================================================================




def _v9_clone_config(config: ExperimentConfig) -> ExperimentConfig:
    return ExperimentConfig.from_dict(asdict(config))


def initialize_v9_directory(
    directory: str | os.PathLike[str],
    *,
    model_name: str,
) -> Path:
    """Create the canonical v9 functional-world matrix and JSONL corpus."""
    root = Path(directory).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    train_path = root / "functional_train.jsonl"
    eval_path = root / "functional_eval.jsonl"
    write_jsonl_records(
        train_path,
        make_functional_relation_pair_records(
            worlds=256,
            seed=90_071,
            width=6,
            queries_per_world=8,
        ),
    )
    write_jsonl_records(
        eval_path,
        make_functional_relation_pair_records(
            worlds=64,
            seed=90_911,
            width=6,
            queries_per_world=8,
            heldout_template="Does {left} outrank {right}? Answer:",
            heldout_fraction=0.50,
        ),
    )

    base = ExperimentConfig()
    base.model.name_or_path = model_name
    base.model.train_mode = "full"
    base.model.hidden_capture = "hidden_states"
    base.model.gradient_checkpointing = False
    base.model.use_cache = False
    base.model.attn_implementation = "eager"
    base.data.train_files = [train_path.name]
    base.data.eval_files = [eval_path.name]
    base.data.use_chat_template = False
    base.data.train_on_prompt = False
    base.data.add_bos = False
    base.data.add_eos = False
    base.data.pad_to_multiple_of = 8
    base.data.fingerprint_mode = "full"
    base.data.functional_context_max_length = 192
    base.data.functional_query_max_length = 96
    base.data.functional_inline_max_length = 256
    base.data.functional_max_queries = 8
    base.data.functional_require_one_token_answer = True

    base.workspace.architecture = "causal_broadcast"
    base.workspace.route_topology = "functional_workspace"
    base.workspace.workspace_dim = 256
    base.workspace.steps = 4
    base.workspace.dropout = 0.05
    base.workspace.logit_residual_scale = 0.0
    base.workspace.aux_backprop_to_base = True
    base.workspace.loss_weight = 0.0
    base.workspace.loss_warmup_steps = 0
    base.workspace.spectral_every = 16
    base.workspace.loss.projection_dim = 128
    base.workspace.loss.probe_dropout = 0.05

    base.functional.enabled = True
    base.functional.route_mode = "deferred"
    base.functional.boundary_layer = 6
    base.functional.memory_mode = "slots"
    base.functional.slot_count = 4
    base.functional.writer_steps = 1
    base.functional.reader_steps = 1
    base.functional.writer_heads = 8
    base.functional.reader_heads = 8
    base.functional.dropout = 0.05
    base.functional.readout_step = -1
    base.functional.injection_scale = 1.0
    base.functional.gate_init_bias = -1.0
    base.functional.counterfactual_weight = 0.0
    base.functional.stability_weight = 0.0
    base.functional.minimum_queries_per_world = 8
    base.functional.require_paired_worlds = True
    base.functional.require_affected_and_unaffected = True

    base.train.seed = 42
    base.train.device = "auto"
    base.train.epochs = 99
    base.train.max_steps = 512
    base.train.batch_size = 2
    base.train.eval_batch_size = 2
    base.train.gradient_accumulation_steps = 4
    base.train.learning_rate = 2e-5
    base.train.workspace_learning_rate = 3e-4
    base.train.weight_decay = 0.10
    base.train.warmup_ratio = 0.03
    base.train.mixed_precision = "auto"
    base.train.log_every = 1
    base.train.eval_every = 64
    base.train.save_every = 64
    base.train.keep_last_checkpoints = 3
    base.train.resume_from = "auto"
    base.train.strict_resume = True
    base.train.strict_source_resume = True
    base.train.strict_torch_resume = True

    base.attribution.isolate_rng_streams = True
    base.attribution.clip_mode = "per_family"
    base.attribution.base_max_grad_norm = 1.0
    base.attribution.workspace_max_grad_norm = 1.0
    base.induction.enabled = False
    base.induction.schedule = "constant"
    base.induction.bypass_workspace_when_inactive = False
    base.transition.enabled = False

    base.assays.amputation_eval = True
    base.assays.amputation_eval_every = 64
    base.assays.gradient_alignment_every = 0
    base.assays.recruitment.enabled = False
    base.assays.choice_eval.enabled = False
    base.assays.necessity.enabled = True
    base.assays.necessity.require_deferred_bridge = False
    base.assays.necessity.require_counterfactual_pairs = False
    base.assays.necessity.run_choice_eval = False
    base.assays.necessity.batch_size = 4
    base.assays.necessity.minimum_changed_fraction = 0.95
    base.assays.necessity.modes = [
        "intact",
        "hard_bypass",
        "zero",
        "global_mean",
        "fixed_carrier",
        "norm_matched_random",
        "token_shuffle",
        "counterfactual_twin",
        "cross_world_shuffle",
    ]

    variants: dict[str, dict[str, Any]] = {
        # v9.0 failure localization.
        "F0_query_only": {
            "route_mode": "query_only",
            "memory_mode": "slots",
            "boundary": 6,
            "slots": 4,
            "writer_steps": 1,
            "injection": 0.0,
        },
        "B_local_invariance": {
            "route_mode": "deferred",
            "memory_mode": "slots",
            "boundary": 6,
            "slots": 4,
            "writer_steps": 1,
            "injection": 0.0,
            "workspace_weight": 0.02,
            "aux_base": False,
        },
        "F1_inline_upper": {
            "route_mode": "inline",
            "memory_mode": "raw_sequence",
            "boundary": 6,
            "injection": 0.0,
        },
        "F2_raw_b3": {
            "route_mode": "deferred", "memory_mode": "raw_sequence",
            "boundary": 3,
        },
        "F3_raw_b6": {
            "route_mode": "deferred", "memory_mode": "raw_sequence",
            "boundary": 6,
        },
        "F4_raw_b9": {
            "route_mode": "deferred", "memory_mode": "raw_sequence",
            "boundary": 9,
        },
        "F5_projected_b6": {
            "route_mode": "deferred", "memory_mode": "projected_sequence",
            "boundary": 6,
        },
        # v9.1 objective matrix at a fixed slot budget.
        "O0_slots4_k1": {
            "route_mode": "deferred", "memory_mode": "slots",
            "boundary": 6, "slots": 4, "writer_steps": 1,
        },
        "O1_slots4_k1_lw": {
            "route_mode": "deferred", "memory_mode": "slots",
            "boundary": 6, "slots": 4, "writer_steps": 1,
            "workspace_weight": 0.02,
        },
        "O2_slots4_k1_cf": {
            "route_mode": "deferred", "memory_mode": "slots",
            "boundary": 6, "slots": 4, "writer_steps": 1,
            "counterfactual_weight": 1.0,
            "stability_weight": 0.25,
        },
        "O3_slots4_k1_lw_cf": {
            "route_mode": "deferred", "memory_mode": "slots",
            "boundary": 6, "slots": 4, "writer_steps": 1,
            "workspace_weight": 0.02,
            "counterfactual_weight": 1.0,
            "stability_weight": 0.25,
        },
        # v9.2 slot-budget × recurrent-consolidation frontier.
        "R_slots1_k1": {"route_mode": "deferred", "memory_mode": "slots", "boundary": 6, "slots": 1, "writer_steps": 1},
        "R_slots1_k4": {"route_mode": "deferred", "memory_mode": "slots", "boundary": 6, "slots": 1, "writer_steps": 4},
        "R_slots2_k1": {"route_mode": "deferred", "memory_mode": "slots", "boundary": 6, "slots": 2, "writer_steps": 1},
        "R_slots2_k4": {"route_mode": "deferred", "memory_mode": "slots", "boundary": 6, "slots": 2, "writer_steps": 4},
        "R_slots4_k4": {"route_mode": "deferred", "memory_mode": "slots", "boundary": 6, "slots": 4, "writer_steps": 4},
        "R_slots4_k4_step1": {"route_mode": "deferred", "memory_mode": "slots", "boundary": 6, "slots": 4, "writer_steps": 4, "readout_step": 1},
        "R_slots8_k1": {"route_mode": "deferred", "memory_mode": "slots", "boundary": 6, "slots": 8, "writer_steps": 1},
        "R_slots8_k4": {"route_mode": "deferred", "memory_mode": "slots", "boundary": 6, "slots": 8, "writer_steps": 4},
    }

    for name, settings in variants.items():
        cfg = _v9_clone_config(base)
        cfg.functional.route_mode = str(settings.get("route_mode", "deferred"))
        cfg.functional.memory_mode = str(settings.get("memory_mode", "slots"))
        cfg.functional.boundary_layer = int(settings.get("boundary", 6))
        cfg.functional.slot_count = int(settings.get("slots", 4))
        cfg.functional.writer_steps = int(settings.get("writer_steps", 1))
        cfg.functional.readout_step = int(settings.get("readout_step", -1))
        cfg.functional.injection_scale = float(settings.get("injection", 1.0))
        cfg.functional.counterfactual_weight = float(
            settings.get("counterfactual_weight", 0.0)
        )
        cfg.functional.stability_weight = float(
            settings.get("stability_weight", 0.0)
        )
        cfg.workspace.loss_weight = float(settings.get("workspace_weight", 0.0))
        cfg.workspace.aux_backprop_to_base = bool(settings.get("aux_base", True))
        cfg.assays.necessity.enabled = bool(
            cfg.functional.route_mode == "deferred"
            and cfg.functional.injection_scale != 0.0
        )
        cfg.train.output_dir = f"runs/{name}"
        cfg.to_json(root / f"config_{name}.json")

    primary = _v9_clone_config(base)
    primary.functional.route_mode = "deferred"
    primary.functional.memory_mode = "slots"
    primary.functional.boundary_layer = 6
    primary.functional.slot_count = 4
    primary.functional.writer_steps = 1
    primary.workspace.loss_weight = 0.02
    primary.functional.counterfactual_weight = 1.0
    primary.functional.stability_weight = 0.25
    primary.train.output_dir = "runs/O3_slots4_k1_lw_cf"
    primary.to_json(root / "config.json")

    order = list(variants)
    matrix = {
        "format": "latent-workspace-v9-matrix-v1",
        "harness_version": __version__,
        "model": model_name,
        "train_world_pairs": 256,
        "eval_world_pairs": 64,
        "queries_per_world": 8,
        "canonical_order": order,
        "attribution_pair": {
            "left": "F0_query_only",
            "right": "B_local_invariance",
            "strict_base_equality": True,
        },
        "condition_groups": {
            "attribution": ["F0_query_only", "B_local_invariance"],
            "localization": [
                "F0_query_only", "F1_inline_upper", "F2_raw_b3",
                "F3_raw_b6", "F4_raw_b9", "F5_projected_b6",
            ],
            "objective_matrix": [
                "O0_slots4_k1", "O1_slots4_k1_lw",
                "O2_slots4_k1_cf", "O3_slots4_k1_lw_cf",
            ],
            "frontier": [
                "R_slots1_k1", "R_slots1_k4", "R_slots2_k1",
                "R_slots2_k4", "O0_slots4_k1", "R_slots4_k4",
                "R_slots4_k4_step1", "R_slots8_k1", "R_slots8_k4",
            ],
        },
        "fixed_contract": {
            "query_deferred": True,
            "context_encoded_once_per_world_side": True,
            "raw_context_query_bypass": False,
            "affected_queries_per_pair": 2,
            "unaffected_queries_per_pair": 6,
            "counterfactual_direction_required": True,
            "unaffected_stability_required": True,
        },
        "primary_claim": (
            "Test whether one query-independent memory can implement a reusable "
            "relation function across multiple future queries and whether a "
            "local counterfactual memory edit flips only affected answers."
        ),
    }
    _atomic_write_json(root / "MATRIX.json", matrix)
    return root

def initialize_demo_directory(
    directory: str | os.PathLike[str],
    *,
    model_name: str,
) -> Path:
    """Create the v8 counterfactual semantic-load-bearing matrix.

    Every synthetic pair presents the same query and fixed 0/1 answer
    vocabulary under two matched contexts with opposite labels. The deferred
    query branch therefore has a Bayes ceiling of 50% unless context-bearing
    memory is actually used.
    """
    root = Path(directory).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    train_path = root / "twin_train.jsonl"
    eval_path = root / "twin_eval.jsonl"
    train_pairs = 128
    eval_pairs = 64
    write_jsonl_records(
        train_path,
        make_counterfactual_twin_records(
            pairs=train_pairs,
            seed=8_071,
            width=6,
            balanced_by_distance=True,
            family="semantic_bit",
        ),
    )
    write_jsonl_records(
        eval_path,
        make_counterfactual_twin_records(
            pairs=eval_pairs,
            seed=8_911,
            width=6,
            balanced_by_distance=True,
            family="semantic_bit",
        ),
    )

    # A shared, held-out recruitability assay. Unlike the semantic-bit plane,
    # the target is not written directly into the selected feature. The probe
    # sees the full causal prefix through the end of the query and must recover
    # the 1--4 hop rank distance. This preserves the v7 repair requested by the
    # experiment: query-visible features paired with a query-defined target.
    recruit_train_path = root / "recruit_train.jsonl"
    recruit_eval_path = root / "recruit_eval.jsonl"
    write_jsonl_records(
        recruit_train_path,
        make_demo_records(
            worlds=64,
            queries_per_world=4,
            seed=28_071,
            balanced_by_distance=True,
        ),
    )
    write_jsonl_records(
        recruit_eval_path,
        make_demo_records(
            worlds=32,
            queries_per_world=4,
            seed=28_911,
            balanced_by_distance=True,
        ),
    )

    base = ExperimentConfig()
    base.model.name_or_path = model_name
    base.data.train_files = [train_path.name]
    base.data.eval_files = [eval_path.name]
    # 192 is still cheap for the one-token bit task, while keeping the shared
    # relation-recruitment prefix intact under byte-level validation. A shorter
    # cap can silently collapse query-end signatures and recreate the v7
    # non-identifiability bug through truncation.
    base.data.max_length = 192
    base.data.use_chat_template = False
    base.data.train_on_prompt = False
    base.data.response_prefix = ""
    # The semantic task supervises only 0/1. Removing EOS keeps every
    # task token answer-critical, so a route cannot win by calibrating template
    # prose or sequence termination while leaving the decision unchanged.
    base.data.add_eos = False
    base.data.fingerprint_mode = "full"
    base.workspace.architecture = "causal_broadcast"
    base.workspace.route_topology = "deferred_bridge"
    base.workspace.deferred_memory_source = "workspace"
    base.workspace.anchor_refresh = "initial_only"
    base.workspace.scope = "context_tail"
    base.workspace.logit_residual_scale = 0.0
    # v8 deliberately gives the semantic bridge enough optimization runway to
    # become load-bearing rather than interpreting an unopened zero-init route.
    base.workspace.gate_init_bias = -1.0
    base.workspace.loss_weight = 0.02
    base.workspace.loss_warmup_steps = 0
    base.workspace.spectral_every = 8
    base.train.epochs = 12
    base.train.resume_from = "auto"
    base.train.strict_resume = True
    base.train.batch_size = 4
    base.train.eval_batch_size = 8
    base.train.gradient_accumulation_steps = 4
    base.train.workspace_learning_rate = 5e-4
    base.train.log_every = 1
    base.train.eval_every = 16
    base.train.save_every = 16
    base.attribution.isolate_rng_streams = True
    base.attribution.clip_mode = "per_family"
    base.attribution.base_max_grad_norm = 1.0
    base.attribution.workspace_max_grad_norm = 1.0
    base.induction.enabled = False
    base.induction.schedule = "constant"
    base.induction.bypass_workspace_when_inactive = True
    base.assays.amputation_eval = True
    base.assays.amputation_eval_every = 16
    base.assays.gradient_alignment_every = 0
    base.assays.recruitment.enabled = True
    base.assays.recruitment.target = "rank_distance"
    base.assays.recruitment.scope = "query_end"
    base.assays.recruitment.train_files = [recruit_train_path.name]
    base.assays.recruitment.eval_files = [recruit_eval_path.name]
    base.assays.recruitment.ranks = [4, 16, 64]
    base.assays.recruitment.max_steps = 150
    base.assays.recruitment.eval_every = 10
    base.assays.recruitment.fail_on_nonidentifying = True
    base.assays.recruitment.minimum_bayes_ceiling = 0.95
    base.assays.recruitment.minimum_ceiling_over_chance = 0.40
    base.assays.choice_eval.enabled = True
    base.assays.choice_eval.batch_size = 8
    base.assays.necessity.modes = [
        "intact",
        "hard_bypass",
        "zero",
        "mean",
        "global_mean",
        "fixed_carrier",
        "norm_matched_random",
        "sign_flip",
        "signed_permutation",
        "scale_025",
        "scale_050",
        "scale_100",
        "scale_200",
        "scale_400",
        "token_shuffle",
        "counterfactual_twin",
        "cross_world_shuffle",
    ]
    base.assays.necessity.batch_size = 8
    base.assays.necessity.mix_worlds = True
    base.assays.necessity.minimum_changed_fraction = 0.99
    base.assays.necessity.require_counterfactual_pairs = True

    variants: dict[str, dict[str, Any]] = {
        "Q0_query_only": {
            "topology": "deferred_bridge", "source": "workspace", "route": 0.0,
            "loss": 0.0, "aux_base": False, "induction": False, "steps": 4,
            "necessity": False,
        },
        "Q1_fixed_carrier": {
            "topology": "deferred_bridge", "source": "fixed_carrier", "route": 1.0,
            "loss": 0.0, "aux_base": False, "induction": False, "steps": 4,
            "necessity": True,
        },
        "Q2_anchor_route": {
            "topology": "deferred_bridge", "source": "anchor", "route": 1.0,
            "loss": 0.0, "aux_base": False, "induction": False, "steps": 4,
            "necessity": True,
        },
        "Q3_workspace_route": {
            "topology": "deferred_bridge", "source": "workspace", "route": 1.0,
            "loss": 0.0, "aux_base": False, "induction": False, "steps": 4,
            "necessity": True,
        },
        "Q4_aux_only": {
            "topology": "deferred_bridge", "source": "workspace", "route": 0.0,
            "loss": 0.02, "aux_base": True, "induction": True, "steps": 4,
            "necessity": False,
        },
        "Q5_workspace_aux_route": {
            "topology": "deferred_bridge", "source": "workspace", "route": 1.0,
            "loss": 0.02, "aux_base": True, "induction": True, "steps": 4,
            "necessity": True,
        },
        "Q6_workspace_step1_readout": {
            "topology": "deferred_bridge", "source": "workspace", "route": 1.0,
            "loss": 0.0, "aux_base": False, "induction": False, "steps": 4,
            "readout_step": 1, "necessity": True,
        },
        "Q7_inline_context": {
            "topology": "inline", "source": "workspace", "route": 0.0,
            "loss": 0.0, "aux_base": False, "induction": False, "steps": 4,
            "necessity": False,
        },
    }

    # Engineering-only attribution pair. It is excluded from the 12-condition
    # scientific matrix: the auxiliary objective is active locally, but its
    # hidden input is detached from the base trunk. With isolated RNG streams
    # and per-family clipping, Q0 and B must retain bitwise-identical base
    # updates in the paired lockstep audit.
    attribution_local = ExperimentConfig.from_dict(asdict(base))
    _configure_loss_family(attribution_local, "full")
    attribution_local.workspace.route_topology = "deferred_bridge"
    attribution_local.workspace.deferred_memory_source = "workspace"
    attribution_local.workspace.logit_residual_scale = 0.0
    attribution_local.workspace.loss_weight = 0.02
    attribution_local.workspace.aux_backprop_to_base = False
    attribution_local.workspace.steps = 4
    attribution_local.induction.enabled = True
    attribution_local.induction.schedule = "early_pulse"
    attribution_local.induction.start_fraction = 0.0
    attribution_local.induction.end_fraction = 0.25
    attribution_local.assays.necessity.enabled = False
    attribution_local.train.output_dir = "run_B_local_invariance"
    attribution_local.to_json(root / "config_B_local_invariance.json")

    for name, settings in variants.items():
        variant = ExperimentConfig.from_dict(asdict(base))
        _configure_loss_family(variant, "full" if settings["loss"] > 0 else "none")
        variant.workspace.route_topology = str(settings["topology"])
        variant.workspace.deferred_memory_source = str(settings["source"])
        variant.workspace.logit_residual_scale = float(settings["route"])
        variant.workspace.loss_weight = float(settings["loss"])
        variant.workspace.aux_backprop_to_base = bool(settings["aux_base"])
        variant.workspace.steps = int(settings["steps"])
        variant.workspace.deferred_memory_step = int(
            settings.get("readout_step", -1)
        )
        variant.induction.enabled = bool(settings["induction"])
        variant.induction.schedule = "early_pulse" if settings["induction"] else "constant"
        variant.induction.start_fraction = 0.0
        variant.induction.end_fraction = 0.25 if settings["induction"] else 1.0
        variant.assays.necessity.enabled = bool(settings["necessity"])
        variant.assays.necessity.require_deferred_bridge = (
            variant.workspace.route_topology == "deferred_bridge"
        )
        variant.assays.necessity.require_counterfactual_pairs = bool(settings["necessity"])
        variant.train.output_dir = f"run_{name}"
        variant.to_json(root / f"config_{name}.json")

    # A separate relation plane climbs one semantic rung without weakening
    # the foundational bit-level positive control. It reuses the same route
    # contracts but is interpreted only when the inline upper bound solves it.
    relation_train_path = root / "relation_train.jsonl"
    relation_eval_path = root / "relation_eval.jsonl"
    write_jsonl_records(
        relation_train_path,
        make_counterfactual_twin_records(
            pairs=train_pairs,
            seed=18_071,
            width=6,
            family="direct_relation",
        ),
    )
    write_jsonl_records(
        relation_eval_path,
        make_counterfactual_twin_records(
            pairs=eval_pairs,
            seed=18_911,
            width=6,
            family="direct_relation",
        ),
    )
    relation_variants = {
        "R0_relation_query_only": "Q0_query_only",
        "R1_relation_fixed_carrier": "Q1_fixed_carrier",
        "R3_relation_workspace_route": "Q3_workspace_route",
        "R7_relation_inline_context": "Q7_inline_context",
    }
    for relation_name, source_name in relation_variants.items():
        relation = ExperimentConfig.from_json(root / f"config_{source_name}.json")
        relation.data.train_files = [relation_train_path.name]
        relation.data.eval_files = [relation_eval_path.name]
        relation.train.output_dir = f"run_{relation_name}"
        relation.to_json(root / f"config_{relation_name}.json")
        variants[relation_name] = {
            "derived_from": source_name,
            "semantic_family": "direct_relation",
        }

    primary = ExperimentConfig.from_json(root / "config_Q5_workspace_aux_route.json")
    primary.train.output_dir = "run_Q5_workspace_aux_route"
    primary.to_json(root / "config.json")

    canonical_order = list(variants)
    matrix = {
        "format": "latent-workspace-v8-semantic-matrix-v1",
        "harness_version": __version__,
        "model": model_name,
        "canonical_order": canonical_order,
        "attribution_pair": {
            "left": "Q0_query_only",
            "right": "B_local_invariance",
            "strict_base_equality": True,
        },
        "condition_groups": {
            "semantic_2x2": [
                "Q0_query_only", "Q3_workspace_route",
                "Q4_aux_only", "Q5_workspace_aux_route",
            ],
            "carrier_controls": [
                "Q0_query_only", "Q1_fixed_carrier",
                "Q2_anchor_route", "Q3_workspace_route",
            ],
            "recurrence_controls": [
                "Q2_anchor_route", "Q6_workspace_step1_readout",
                "Q3_workspace_route",
            ],
            "solvability_upper_bound": ["Q0_query_only", "Q7_inline_context"],
            "relation_stress": [
                "R0_relation_query_only",
                "R1_relation_fixed_carrier",
                "R3_relation_workspace_route",
                "R7_relation_inline_context",
            ],
        },
        "records": {
            "semantic_family": "semantic_bit",
            "train_pairs": train_pairs,
            "train_records": train_pairs * 2,
            "eval_pairs": eval_pairs,
            "eval_records": eval_pairs * 2,
            "recruitment_target": "rank_distance",
            "recruitment_scope": "query_end",
            "recruitment_train_records": 64 * 4,
            "recruitment_eval_records": 32 * 4,
            "recruitment_distance_counts": {
                "train": {"1": 64, "2": 64, "3": 64, "4": 64},
                "eval": {"1": 32, "2": 32, "3": 32, "4": 32},
            },
        },
        "identifiability_contract": {
            "query_is_identical_within_twin_pair": True,
            "labels_are_opposite_within_twin_pair": True,
            "choice_order_is_fixed": ["0", "1"],
            "query_only_bayes_ceiling": 0.5,
            "primary_task": "semantic_bit",
            "stress_task": "direct_relation",
            "counterfactual_twin_expected_effect": (
                "A content-bearing route should move predictions toward the "
                "opposite twin answer; a fixed carrier cannot identify it."
            ),
        },
        "primary_claim": (
            "Test whether deferred workspace content, rather than the mere "
            "presence of a nonzero carrier, becomes causally load-bearing for "
            "an answer-critical binary decision."
        ),
    }
    _atomic_write_json(root / "MATRIX.json", matrix)
    return root


def _command_init(args: argparse.Namespace) -> None:
    root = initialize_v9_directory(args.directory, model_name=args.model)
    print(f"Created v9 functional experiment at: {root}")
    print(f"Train with: python {Path(__file__).name} train --config {root / 'config.json'}")


def _command_train(args: argparse.Namespace) -> None:
    config = ExperimentConfig.from_json(args.config)
    if args.fresh:
        config.train.resume_from = "none"
    elif args.resume_from is not None:
        config.train.resume_from = args.resume_from
    final_path = train_experiment(config)
    print(f"Training bundle: {final_path}")


def _doctor_warnings(config: ExperimentConfig) -> list[str]:
    warnings: list[str] = [
        "Generation currently disables the base-model KV cache and recomputes "
        "the full prefix for every new token; long-form decoding is intentionally "
        "a diagnostic path, not a throughput-optimized serving path."
    ]
    if (
        config.workspace.scope
        in {"context", "context_tail", "prequery_boundary", "query"}
        and config.data.use_chat_template
    ):
        warnings.append(
            "Deferred context/query masks are exact only for the plain encoder. "
            "Set data.use_chat_template=false for deferred-scope experiments."
        )
    if config.data.fingerprint_mode == "sampled":
        warnings.append(
            "Corpus fingerprinting is sampled, not a full-file hash. Use "
            "data.fingerprint_mode='full' for archival provenance."
        )
    if not config.train.save_optimizer:
        warnings.append(
            "save_optimizer=false prevents strict continuation from new bundles."
        )
    if config.train.resume_from == "auto" and not config.train.strict_resume:
        warnings.append(
            "Automatic resume is configured as a warm restart rather than an exact resume."
        )
    if config.model.train_mode == "workspace_only" and not config.train.save_frozen_base:
        warnings.append(
            "workspace_only bundles reference the original base model; set "
            "save_frozen_base=true for a self-contained archive."
        )
    if config.data.num_workers == 0:
        warnings.append(
            "num_workers=0 is deterministic and safe, but tokenization may become the throughput bottleneck."
        )
    if config.workspace.route_topology == "deferred_bridge":
        warnings.append(
            "deferred_bridge intentionally has no free-form generate path. Use "
            "choice-eval and necessity to inspect the context-memory route."
        )
    if config.workspace.route_topology == "functional_workspace":
        warnings.append(
            "functional_workspace encodes each paired context once and reuses it "
            "across grouped queries. Free-form generation is intentionally disabled; "
            "use eval and functional necessity assays."
        )
    if (
        config.attribution.clip_mode == "per_family"
        and config.train.mixed_precision == "fp16"
    ):
        warnings.append(
            "fp16 still uses one GradScaler for both parameter families. A workspace "
            "overflow can skip the base step; use bf16 or full precision for strict "
            "A/B-local attribution invariance."
        )
    return warnings


def _functional_split_equivalence_check(
    model: nn.Module,
    common_kwargs: Mapping[str, Any],
    *,
    device: torch.device,
    precision: str,
) -> dict[str, float | bool]:
    """Check fresh routed/amputated parity under the training autocast policy."""
    was_training = model.training
    model.eval()
    try:
        with torch.no_grad(), autocast_context(device, precision):
            routed_check = model(**common_kwargs, bypass_workspace=False)
            amputated_check = model(**common_kwargs, bypass_workspace=True)
    finally:
        if was_training:
            model.train()
    routed_logits = routed_check.get("logits")
    amputated_logits = amputated_check.get("logits")
    if not isinstance(routed_logits, torch.Tensor) or not isinstance(
        amputated_logits, torch.Tensor
    ):
        raise RuntimeError("Functional split equivalence check received no logits.")
    maximum = float(
        (routed_logits.float() - amputated_logits.float()).abs().max().item()
    )
    tolerance = 1e-6
    report: dict[str, float | bool] = {
        "max_abs_logit_difference": maximum,
        "tolerance": tolerance,
        "passed": maximum <= tolerance,
    }
    if maximum > tolerance:
        raise RuntimeError(
            "Fresh zero-initialized functional route does not match true "
            f"amputation: max_abs={maximum:.6g} > {tolerance:.1e}. "
            "Do not launch until the split decoder is equivalent."
        )
    return report


def _doctor_smoke_step(
    config: ExperimentConfig,
    dataset: JsonlFineTuningDataset,
    *,
    batch_size: int,
) -> dict[str, Any]:
    configure_runtime_math(config.train)
    device = resolve_device(config.train.device)
    precision = resolve_mixed_precision(config.train.mixed_precision, device)
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)

    model, tokenizer = build_workspace_model(config)
    model.to(device)
    effective_allocator_environment = require_effective_cuda_allocator_policy(
        config.train, device
    )
    model.train()
    if config.model.train_mode == "workspace_only":
        model.base_model.eval()

    collator = CausalFineTuningCollator(
        pad_token_id=int(tokenizer.pad_token_id),
        pad_to_multiple_of=config.data.pad_to_multiple_of,
    )
    count = min(max(1, int(batch_size)), len(dataset))
    raw_batch = collator([dataset[index] for index in range(count)])
    batch = move_batch_to_device(raw_batch, device)
    split_equivalence: Optional[dict[str, float | bool]] = None
    if config.functional.enabled and config.functional.route_mode == "deferred":
        common_kwargs = dict(
            input_ids=batch["input_ids"],
            attention_mask=batch["attention_mask"],
            labels=batch["labels"],
            prompt_mask=batch["prompt_mask"],
            context_mask=batch.get("context_mask"),
            query_mask=batch.get("query_mask"),
            **functional_batch_kwargs(batch),
            compute_workspace_loss=False,
            compute_spectral=False,
        )
        split_equivalence = _functional_split_equivalence_check(
            model,
            common_kwargs,
            device=device,
            precision=precision,
        )
    optimizer = build_optimizer(model, config.train, device)
    optimizer_coverage = optimizer_coverage_report(
        model,
        optimizer,
        train_mode=config.model.train_mode,
    )
    require_exact_optimizer_coverage(optimizer_coverage)
    scaler = make_grad_scaler(device, precision)
    optimizer.zero_grad(set_to_none=True)

    cuda_phase_memory: dict[str, dict[str, float]] = {}
    if device.type == "cuda":
        torch.cuda.synchronize(device)
        cuda_phase_memory["setup_and_equivalence"] = _memory_metrics(device)
        torch.cuda.reset_peak_memory_stats(device)

    started = time.perf_counter()
    with autocast_context(device, precision):
        output = model(
            input_ids=batch["input_ids"],
            attention_mask=batch["attention_mask"],
            labels=batch["labels"],
            prompt_mask=batch["prompt_mask"],
            context_mask=batch.get("context_mask"),
            query_mask=batch.get("query_mask"),
            example_group_ids=batch.get("example_group_ids"),
            world_group_ids=batch.get("world_group_ids"),
            counterfactual_group_ids=batch.get("counterfactual_group_ids"),
            answer_classes=batch.get("answer_classes"),
            **bridge_batch_kwargs(batch),
            **functional_batch_kwargs(batch),
            compute_workspace_loss=config.workspace.loss_weight > 0.0,
            compute_spectral=config.workspace.spectral_every != 0,
        )
        task_loss = output["task_loss"]
        if task_loss is None:
            raise RuntimeError("Smoke step produced no supervised task loss.")
        objective = task_loss + config.workspace.loss_weight * output["workspace_loss"]
        cf_sum = output.get("counterfactual_nll_sum")
        cf_tokens = output.get("counterfactual_tokens")
        if (
            config.functional.counterfactual_weight > 0.0
            and isinstance(cf_sum, torch.Tensor)
            and isinstance(cf_tokens, torch.Tensor)
            and int(cf_tokens.item()) > 0
        ):
            objective = objective + config.functional.counterfactual_weight * (
                cf_sum / cf_tokens.to(cf_sum.dtype)
            )
        stability_sum = output.get("stability_kl_sum")
        stability_items = output.get("stability_items")
        if (
            config.functional.stability_weight > 0.0
            and isinstance(stability_sum, torch.Tensor)
            and isinstance(stability_items, torch.Tensor)
            and int(stability_items.item()) > 0
        ):
            objective = objective + config.functional.stability_weight * (
                stability_sum / stability_items.to(stability_sum.dtype)
            )
    if device.type == "cuda":
        torch.cuda.synchronize(device)
        cuda_phase_memory["forward"] = _memory_metrics(device)
        torch.cuda.reset_peak_memory_stats(device)
    if not bool(torch.isfinite(objective.detach()).item()):
        raise FloatingPointError("Smoke-step objective is non-finite.")

    _release_unconsumed_training_logits(output)
    scaler.scale(objective).backward()
    scaler.unscale_(optimizer)
    grad_norm = torch.nn.utils.clip_grad_norm_(
        [parameter for parameter in model.parameters() if parameter.requires_grad],
        config.train.max_grad_norm,
    )
    if not bool(torch.isfinite(grad_norm.detach()).item()):
        raise FloatingPointError("Smoke-step gradient norm is non-finite.")
    if device.type == "cuda":
        torch.cuda.synchronize(device)
        cuda_phase_memory["backward"] = _memory_metrics(device)
        torch.cuda.reset_peak_memory_stats(device)

    preferred_output_rows: set[int] = set()
    for label_name in (
        "labels",
        "functional_query_labels",
        "functional_inline_labels",
    ):
        labels = batch.get(label_name)
        if isinstance(labels, torch.Tensor):
            supervised = labels.detach()[labels.ne(-100)]
            preferred_output_rows.update(
                int(value) for value in supervised.cpu().tolist()
            )
    sentinel = optimizer_step_with_base_sentinel(
        model,
        optimizer,
        scaler=scaler,
        preferred_output_rows=sorted(preferred_output_rows),
    )
    base_update_coverage = base_update_coverage_report(
        model,
        optimizer,
        train_mode=config.model.train_mode,
        global_clip_grad_norm=grad_norm,
        optimizer_step_performed=not bool(sentinel["optimizer_step_skipped"]),
        optimizer_step_skipped=bool(sentinel["optimizer_step_skipped"]),
    )
    require_base_update_coverage(base_update_coverage)
    if device.type == "cuda":
        torch.cuda.synchronize(device)
        cuda_phase_memory["optimizer_step"] = _memory_metrics(device)
    elapsed = time.perf_counter() - started

    report: dict[str, Any] = {
        "device": str(device),
        "mixed_precision": precision,
        "batch_size": count,
        "sequence_length": int(batch["input_ids"].shape[1]),
        "functional_queries": int(
            batch.get("functional_query_valid_mask", torch.zeros(1)).sum().item()
        ),
        "supervised_tokens": int(output["supervised_tokens"].item()),
        "task_loss": float(task_loss.detach().float().item()),
        "workspace_loss": float(output["workspace_loss"].detach().float().item()),
        "objective": float(objective.detach().float().item()),
        "grad_norm": float(grad_norm.detach().float().item()),
        "elapsed_seconds": elapsed,
        "parameters": count_parameters(model),
        "optimizer_coverage": optimizer_coverage,
        "optimizer_step_performed": True,
        "base_step_sentinel": sentinel,
        "base_update_coverage": base_update_coverage,
        "cuda_phase_memory": cuda_phase_memory,
        "functional_split_equivalence": split_equivalence,
        "allocator_environment": effective_allocator_environment,
    }
    optimizer.zero_grad(set_to_none=True)
    final_memory = _memory_metrics(device)
    if final_memory:
        phase_peaks = [
            float(metrics.get("cuda_peak_allocated_gb", 0.0))
            for metrics in cuda_phase_memory.values()
        ]
        final_memory["cuda_peak_allocated_gb"] = max(
            [float(final_memory.get("cuda_peak_allocated_gb", 0.0)), *phase_peaks]
        )
    report.update(final_memory)
    del optimizer, model
    if device.type == "cuda":
        torch.cuda.empty_cache()
    return report


def _tail_jsonl(path: Path, count: int) -> list[dict[str, Any]]:
    if count <= 0 or not path.exists():
        return []
    tail: deque[str] = deque(maxlen=count)
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                tail.append(line)
    records: list[dict[str, Any]] = []
    for line in tail:
        try:
            raw = json.loads(line)
            records.append(raw if isinstance(raw, dict) else {"value": raw})
        except json.JSONDecodeError:
            records.append({"raw": line.rstrip("\n")})
    return records


def _read_optional_json(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {"value": raw}
    except Exception as exc:
        return {"read_error": f"{type(exc).__name__}: {exc}"}


def _command_status(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir).expanduser().resolve()
    heartbeat = _read_optional_json(run_dir / "heartbeat.json")
    if heartbeat is not None and "updated_unix" in heartbeat:
        heartbeat["age_seconds"] = max(0.0, time.time() - float(heartbeat["updated_unix"]))
    latest = find_latest_checkpoint(run_dir)
    report: dict[str, Any] = {
        "run_dir": str(run_dir),
        "exists": run_dir.exists(),
        "heartbeat": heartbeat,
        "latest_resumable_bundle": str(latest) if latest is not None else None,
        "latest_manifest": _read_bundle_manifest(latest) if latest is not None else None,
        "best": _read_optional_json(run_dir / "best_checkpoint.json"),
        "failure": _read_optional_json(run_dir / "FAILED.json"),
        "metrics_tail": _tail_jsonl(run_dir / "metrics.jsonl", args.lines),
    }
    if run_dir.exists():
        usage = shutil.disk_usage(run_dir)
        report["disk_free_gb"] = usage.free / float(1024**3)
        report["run_size_gb"] = _directory_size_bytes(run_dir) / float(1024**3)
    print(json.dumps(report, indent=2, ensure_ascii=False))


def _command_doctor(args: argparse.Namespace) -> None:
    config = ExperimentConfig.from_json(args.config)
    require_cuda_allocator_policy(config.train)
    output_dir = Path(config.train.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _ensure_disk_space(
        output_dir,
        config.train.minimum_free_disk_gb,
        estimated_checkpoint_bytes=_checkpoint_size_estimate(output_dir),
        headroom_ratio=config.train.checkpoint_headroom_ratio,
    )
    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=output_dir,
        prefix=".doctor-write-test-",
        delete=True,
    ) as handle:
        handle.write("ok\n")
        handle.flush()

    tokenizer = load_tokenizer(config.model)
    train_dataset = JsonlFineTuningDataset(
        config.data.train_files,
        tokenizer,
        config.data,
    )
    scan_count = len(train_dataset) if args.full_data_scan else config.data.verify_samples
    scan_started = time.perf_counter()
    _verify_dataset(train_dataset, scan_count)
    scan_seconds = time.perf_counter() - scan_started
    resume_candidate = resolve_resume_checkpoint(config)
    report: dict[str, Any] = {
        "harness_version": __version__,
        "environment": runtime_environment(),
        "train_records": len(train_dataset),
        "verified_train_records": min(scan_count, len(train_dataset)),
        "verification_seconds": scan_seconds,
        "train_fingerprint": fingerprint_files(
            train_dataset.files,
            config.data.fingerprint_bytes,
            config.data.fingerprint_mode,
        ),
        "resume_candidate": str(resume_candidate) if resume_candidate is not None else None,
        "resume_signature": resume_signature(config),
        "output_dir": str(output_dir.resolve()),
        "disk_free_gb": shutil.disk_usage(output_dir).free / float(1024**3),
        "warnings": _doctor_warnings(config),
    }

    # v8 treats dataset identifiability as part of engineering validity, not
    # as a post-hoc interpretation choice. Counterfactual twin experiments must
    # prove that the query-only branch is genuinely ambiguous while the paired
    # contexts carry opposite answer labels. Recruitment probes must likewise
    # prove that their selected causal prefix can identify the requested target
    # before any hidden-state fitting begins.
    requires_twin_contract = bool(
        not config.functional.enabled
        and (
            config.assays.necessity.require_counterfactual_pairs
            or "counterfactual_twin" in config.assays.necessity.modes
        )
    )
    if config.functional.enabled:
        functional_train_audit = audit_functional_world_pair_dataset(
            config.data.train_files,
            tokenizer,
            config.data,
            minimum_queries=config.functional.minimum_queries_per_world,
            require_affected_and_unaffected=(
                config.functional.require_affected_and_unaffected
            ),
        )
        report["functional_train_audit"] = functional_train_audit
        if not functional_train_audit["passed"]:
            raise RuntimeError(
                "Training v9 grouped-world contract failed; inspect "
                "functional_train_audit for local-twin, query, and "
                "tokenization diagnostics."
            )
    if requires_twin_contract:
        train_twin_audit = audit_counterfactual_dataset(
            config.data.train_files,
            tokenizer,
            config.data,
        )
        report["counterfactual_train_audit"] = train_twin_audit
        if not train_twin_audit["passed"]:
            raise RuntimeError(
                "Training counterfactual twin contract failed; see doctor report "
                "fields for pair, tokenization, and Bayes-ceiling diagnostics."
            )

    if config.data.eval_files:
        eval_dataset = JsonlFineTuningDataset(
            config.data.eval_files,
            tokenizer,
            config.data,
        )
        eval_scan_count = (
            len(eval_dataset)
            if args.full_data_scan
            else min(config.data.verify_samples, 8)
        )
        _verify_dataset(eval_dataset, eval_scan_count)
        report["eval_records"] = len(eval_dataset)
        report["verified_eval_records"] = min(eval_scan_count, len(eval_dataset))
        if config.functional.enabled:
            functional_eval_audit = audit_functional_world_pair_dataset(
                config.data.eval_files,
                tokenizer,
                config.data,
                minimum_queries=config.functional.minimum_queries_per_world,
                require_affected_and_unaffected=(
                    config.functional.require_affected_and_unaffected
                ),
            )
            report["functional_eval_audit"] = functional_eval_audit
            if not functional_eval_audit["passed"]:
                raise RuntimeError(
                    "Evaluation v9 grouped-world contract failed; inspect "
                    "functional_eval_audit for local-twin, query, and "
                    "tokenization diagnostics."
                )
        if requires_twin_contract:
            eval_twin_audit = audit_counterfactual_dataset(
                config.data.eval_files,
                tokenizer,
                config.data,
            )
            report["counterfactual_eval_audit"] = eval_twin_audit
            if not eval_twin_audit["passed"]:
                raise RuntimeError(
                    "Evaluation counterfactual twin contract failed; see doctor "
                    "report fields for pair, tokenization, and Bayes-ceiling "
                    "diagnostics."
                )

    recruitment = config.assays.recruitment
    if recruitment.enabled:
        recruit_train_files = recruitment.train_files or config.data.train_files
        recruit_eval_files = recruitment.eval_files or config.data.eval_files
        recruit_train_dataset = JsonlFineTuningDataset(
            recruit_train_files,
            tokenizer,
            config.data,
        )
        train_identifiability = recruitment_identifiability_report(
            recruit_train_dataset,
            scope=recruitment.scope,
            target_name=recruitment.target,
            max_examples=recruitment.max_train_examples,
        )
        report["recruitment_train_identifiability"] = train_identifiability
        if recruit_eval_files:
            recruit_eval_dataset = JsonlFineTuningDataset(
                recruit_eval_files,
                tokenizer,
                config.data,
            )
            eval_identifiability = recruitment_identifiability_report(
                recruit_eval_dataset,
                scope=recruitment.scope,
                target_name=recruitment.target,
                max_examples=recruitment.max_eval_examples,
            )
            report["recruitment_eval_identifiability"] = eval_identifiability
        else:
            eval_identifiability = None

        if recruitment.fail_on_nonidentifying:
            for split_name, identity in (
                ("train", train_identifiability),
                ("eval", eval_identifiability),
            ):
                if identity is None:
                    continue
                if (
                    float(identity["bayes_ceiling"])
                    < float(recruitment.minimum_bayes_ceiling)
                    or float(identity["ceiling_over_prior"])
                    < float(recruitment.minimum_ceiling_over_chance)
                ):
                    raise RuntimeError(
                        f"Recruitment {split_name} prefix is not sufficiently "
                        "identifying: bayes_ceiling="
                        f"{identity['bayes_ceiling']:.6f}, ceiling_over_prior="
                        f"{identity['ceiling_over_prior']:.6f}. Change the scope "
                        "or target before interpreting probe accuracy."
                    )
    if args.smoke_step:
        report["smoke_step"] = _doctor_smoke_step(
            config,
            train_dataset,
            batch_size=args.smoke_batch_size,
        )
    elif args.load_model:
        model, _ = build_workspace_model(config)
        report["parameters"] = count_parameters(model)
        del model
    print(json.dumps(report, indent=2, ensure_ascii=False))


def _command_generate(args: argparse.Namespace) -> None:
    device = resolve_device(args.device)
    model, tokenizer, _ = load_bundle(args.checkpoint, device=device)
    text = generate_text(
        model,
        tokenizer,
        args.prompt,
        device=device,
        max_new_tokens=args.max_new_tokens,
        temperature=args.temperature,
        top_p=args.top_p,
    )
    print(text)


def _command_inspect_data(args: argparse.Namespace) -> None:
    config = ExperimentConfig.from_json(args.config)
    tokenizer = load_tokenizer(config.model)
    dataset = JsonlFineTuningDataset(config.data.train_files, tokenizer, config.data)
    count = min(args.count, len(dataset))
    for index in range(count):
        feature = dataset[index]
        if bool(feature.get("functional_pair", False)):
            query_count = int(feature["functional_query_count"])
            affected = sum(bool(value) for value in feature["functional_affected"])
            print(
                f"\n=== functional world {index} | queries={query_count} "
                f"| affected={affected} | unaffected={query_count - affected} ==="
            )
            for side in range(2):
                context = tokenizer.decode(
                    feature["functional_context_ids"][side],
                    skip_special_tokens=False,
                )
                answers = feature["functional_answers"][side]
                print(f"\n[side {side}] answers={answers}\n{context}")
            continue
        supervised = sum(label != -100 for label in feature["labels"])
        context_tokens = sum(bool(value) for value in feature.get("context_mask", []))
        query_tokens = sum(bool(value) for value in feature.get("query_mask", []))
        print(
            f"\n=== sample {index} | tokens={len(feature['input_ids'])} "
            f"| supervised={supervised} | context={context_tokens} "
            f"| query={query_tokens} ==="
        )
        print(tokenizer.decode(feature["input_ids"], skip_special_tokens=False))




def _command_identifiability(args: argparse.Namespace) -> None:
    config = ExperimentConfig.from_json(args.config)
    tokenizer = load_tokenizer(config.model)
    files = config.data.train_files if args.split == "train" else config.data.eval_files
    if not files:
        raise ValueError(f"No {args.split} files configured.")
    report = (
        audit_functional_world_pair_dataset(
            files,
            tokenizer,
            config.data,
            minimum_queries=config.functional.minimum_queries_per_world,
            require_affected_and_unaffected=(
                config.functional.require_affected_and_unaffected
            ),
        )
        if config.functional.enabled
        else audit_counterfactual_dataset(files, tokenizer, config.data)
    )
    payload = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    if not report["passed"]:
        raise RuntimeError("Counterfactual identifiability audit failed.")


def _command_recruit(args: argparse.Namespace) -> None:
    device = resolve_device(args.device)
    ranks = None
    if args.ranks:
        ranks = [int(value) for value in args.ranks.split(",") if value.strip()]
    report = run_recruitment_assay(
        args.checkpoint,
        args.output_dir,
        device=device,
        scope_override=args.scope,
        target_override=args.target,
        ranks_override=ranks,
        allow_nonidentifying=args.allow_nonidentifying,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


def _command_necessity(args: argparse.Namespace) -> None:
    device = resolve_device(args.device)
    report = run_necessity_assay(
        args.checkpoint,
        args.output,
        device=device,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


def _command_choice_eval(args: argparse.Namespace) -> None:
    device = resolve_device(args.device)
    modes = [value.strip() for value in args.modes.split(",") if value.strip()]
    report = run_choice_evaluation(
        args.checkpoint,
        args.output,
        device=device,
        modes=modes,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


def _command_influence_map(args: argparse.Namespace) -> None:
    device = resolve_device(args.device)
    report = run_influence_map(
        args.baseline,
        args.induced,
        args.output_dir,
        device=device,
        eval_batches=args.eval_batches,
        max_groups=args.max_groups,
        causal_swaps=not args.displacement_only,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


def _command_audit_pair(args: argparse.Namespace) -> None:
    left = ExperimentConfig.from_json(args.left_config)
    right = ExperimentConfig.from_json(args.right_config)
    device = resolve_device(args.device)
    report = run_paired_attribution_audit(
        left,
        right,
        args.output,
        device=device,
        steps=args.steps,
        require_base_equality=not args.allow_divergence,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="LatentWorkspace FT v10 portable functional-memory, local counterfactual, and recurrence-frontier harness."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init",
        help="Create a runnable config and synthetic JSONL dataset.",
    )
    init_parser.add_argument("--directory", default="latent_workspace_demo")
    init_parser.add_argument(
        "--model",
        default="HuggingFaceTB/SmolLM2-135M-Instruct",
    )
    init_parser.set_defaults(function=_command_init)

    train_parser = subparsers.add_parser("train", help="Run fine-tuning.")
    train_parser.add_argument("--config", required=True)
    resume_group = train_parser.add_mutually_exclusive_group()
    resume_group.add_argument(
        "--resume-from",
        default=None,
        help="Override config: auto, none, or a checkpoint directory.",
    )
    resume_group.add_argument(
        "--fresh",
        action="store_true",
        help="Disable automatic resume for this launch.",
    )
    train_parser.set_defaults(function=_command_train)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Validate config, data, provenance, and optionally model loading.",
    )
    doctor_parser.add_argument("--config", required=True)
    doctor_parser.add_argument("--load-model", action="store_true")
    doctor_parser.add_argument(
        "--full-data-scan",
        action="store_true",
        help="Tokenize and validate every training/eval record before launch.",
    )
    doctor_parser.add_argument(
        "--smoke-step",
        action="store_true",
        help="Run one real forward/backward pass without updating weights.",
    )
    doctor_parser.add_argument("--smoke-batch-size", type=int, default=1)
    doctor_parser.set_defaults(function=_command_doctor)

    status_parser = subparsers.add_parser(
        "status",
        help="Read heartbeat, checkpoints, failures, and recent metrics.",
    )
    status_parser.add_argument("--run-dir", required=True)
    status_parser.add_argument("--lines", type=int, default=5)
    status_parser.set_defaults(function=_command_status)

    generate_parser = subparsers.add_parser(
        "generate",
        help="Generate from a saved final/checkpoint bundle.",
    )
    generate_parser.add_argument("--checkpoint", required=True)
    generate_parser.add_argument("--prompt", required=True)
    generate_parser.add_argument("--device", default="auto")
    generate_parser.add_argument("--max-new-tokens", type=int, default=128)
    generate_parser.add_argument("--temperature", type=float, default=0.0)
    generate_parser.add_argument("--top-p", type=float, default=0.95)
    generate_parser.set_defaults(function=_command_generate)

    inspect_parser = subparsers.add_parser(
        "inspect-data",
        help="Decode a few tokenized training samples.",
    )
    inspect_parser.add_argument("--config", required=True)
    inspect_parser.add_argument("--count", type=int, default=3)
    inspect_parser.set_defaults(function=_command_inspect_data)

    audit_parser = subparsers.add_parser(
        "audit-pair",
        help="Run two configs in lockstep and verify v6.0 attribution invariants.",
    )
    audit_parser.add_argument("--left-config", required=True)
    audit_parser.add_argument("--right-config", required=True)
    audit_parser.add_argument("--output", required=True)
    audit_parser.add_argument("--device", default="auto")
    audit_parser.add_argument("--steps", type=int, default=2)
    audit_parser.add_argument(
        "--allow-divergence",
        action="store_true",
        help="Record rather than raise when task NLL or base parameters diverge.",
    )
    audit_parser.set_defaults(function=_command_audit_pair)


    ident_parser = subparsers.add_parser(
        "identifiability",
        help="Audit matched counterfactual twins before training or interpretation.",
    )
    ident_parser.add_argument("--config", required=True)
    ident_parser.add_argument("--split", choices=["train", "eval"], default="eval")
    ident_parser.add_argument("--output", default="")
    ident_parser.set_defaults(function=_command_identifiability)

    recruit_parser = subparsers.add_parser(
        "recruit",
        help="Freeze a saved base trunk and fit low-rank downstream probes.",
    )
    recruit_parser.add_argument("--checkpoint", required=True)
    recruit_parser.add_argument("--output-dir", required=True)
    recruit_parser.add_argument("--device", default="auto")
    recruit_parser.add_argument(
        "--scope",
        choices=["prequery_boundary", "context_mean", "query_end"],
        default=None,
        help="Override the checkpoint recruitment scope.",
    )
    recruit_parser.add_argument(
        "--target",
        choices=["rank_distance", "answer_class"],
        default=None,
        help="Override the checkpoint recruitment target.",
    )
    recruit_parser.add_argument(
        "--ranks",
        default="",
        help="Comma-separated low-rank probe widths, for example 4,16,64.",
    )
    recruit_parser.add_argument(
        "--allow-nonidentifying",
        action="store_true",
        help="Run despite a dataset-level Bayes-ceiling failure; diagnostic only.",
    )
    recruit_parser.set_defaults(function=_command_recruit)

    necessity_parser = subparsers.add_parser(
        "necessity",
        help="Run paired workspace-memory interventions on a deferred bridge bundle.",
    )
    necessity_parser.add_argument("--checkpoint", required=True)
    necessity_parser.add_argument("--output", required=True)
    necessity_parser.add_argument("--device", default="auto")
    necessity_parser.set_defaults(function=_command_necessity)

    choice_parser = subparsers.add_parser(
        "choice-eval",
        help="Score constrained candidate answers and report exact accuracy.",
    )
    choice_parser.add_argument("--checkpoint", required=True)
    choice_parser.add_argument("--output", required=True)
    choice_parser.add_argument("--device", default="auto")
    choice_parser.add_argument("--modes", default="intact")
    choice_parser.set_defaults(function=_command_choice_eval)

    influence_parser = subparsers.add_parser(
        "influence-map",
        help="Compare baseline/induced trunks and optionally run layer swaps.",
    )
    influence_parser.add_argument("--baseline", required=True)
    influence_parser.add_argument("--induced", required=True)
    influence_parser.add_argument("--output-dir", required=True)
    influence_parser.add_argument("--device", default="auto")
    influence_parser.add_argument("--eval-batches", type=int, default=0)
    influence_parser.add_argument("--max-groups", type=int, default=0)
    influence_parser.add_argument(
        "--displacement-only",
        action="store_true",
        help="Skip transplant/swap-back causal evaluations.",
    )
    influence_parser.set_defaults(function=_command_influence_map)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    args.function(args)


if __name__ == "__main__":
    main()
