"""Latent lattices: v4.1's token-local recurrence and v5's causal broadcast.

Promoted verbatim from ``engine.py`` in ``latent_workspace_ft_v10`` at
``d4cd1ee0340a``. The historical files are frozen; this module is the living home
(docs/ARCHITECTURE.md). Parity: ``test_lattices_are_the_historical_lattices``.
"""

from __future__ import annotations

from typing import Any

import torch
from torch import nn
from torch.nn import functional as F


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
        attention_mask: torch.Tensor | None = None,
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
        additive = torch.zeros((B, 1, L, L), device=state.device, dtype=q.dtype).masked_fill(
            ~allowed, float("-inf")
        )
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
        self.attention_anchor_gate = nn.Linear(workspace_dim, workspace_dim, bias=False)
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
        attention_mask: torch.Tensor | None = None,
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
            attention_gate_logits = self.attention_gate(
                attention_input
            ) + refresh_scale * self.attention_anchor_gate(normalized_anchor)
            attention_gate = torch.sigmoid(attention_gate_logits)
            attention_scale = torch.sigmoid(self.attention_step_scales[step])
            state = state + (attention_scale * attention_gate * self.dropout(attention_update))

            ff_input = self.ff_norm(state) + step_signal
            ff_update = (
                self.candidate_out(F.gelu(self.candidate_in(ff_input)))
                + refresh_scale * anchor_signal
            )
            ff_gate_logits = self.ff_gate(ff_input) + refresh_scale * self.ff_anchor_gate(
                normalized_anchor
            )
            ff_gate = torch.sigmoid(ff_gate_logits)
            ff_scale = torch.sigmoid(self.ff_step_scales[step])
            state = state + ff_scale * ff_gate * self.dropout(ff_update)
            state = state * valid + anchor * (1.0 - valid)
            trajectory.append(state)

        return torch.stack(trajectory, dim=2), anchor


TokenLocalLattice = CausalLatentWorkspace
CausalBroadcastLattice = CausalBroadcastLatentWorkspace
