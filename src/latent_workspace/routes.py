"""Routes: where a workspace speaks to its host.

- ``LogitResidualRoute`` (v4): ``base + sigmoid(gate(host state)) * adapter(workspace state)``.
- ``AnswerResidualRoute`` (V15-V19): an FP32 residual on the last normalized
  state, read by the frozen native head.
- ``CutResidualRoute`` (v9): a residual added at cut N; the host's own remaining
  layers, final norm and head continue.

``LowRankWorkspaceLogitAdapter`` is promoted verbatim from ``workspace_core.py``
in ``latent_workspace_ft_v10`` at ``d4cd1ee0340a``; the historical file is frozen.
Parity: ``test_logit_adapter_and_operators_are_historical``.
"""

from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F

from .operators import NormalizationSpec


class LowRankWorkspaceLogitAdapter(nn.Module):
    """Maps the final workspace state to a low-rank residual over vocabulary."""

    def __init__(
        self,
        workspace_dim: int,
        vocab_size: int,
        rank: int,
        norm_spec: NormalizationSpec = NormalizationSpec(),
    ) -> None:
        super().__init__()
        if rank < 1:
            raise ValueError("rank must be positive.")
        self.norm = norm_spec.build(workspace_dim)
        self.down = nn.Linear(workspace_dim, rank, bias=False)
        self.up = nn.Linear(rank, vocab_size, bias=False)
        nn.init.normal_(self.down.weight, mean=0.0, std=0.02)
        nn.init.zeros_(self.up.weight)

    def forward(self, final_state: torch.Tensor) -> torch.Tensor:
        return self.up(F.gelu(self.down(self.norm(final_state))))


LowRankLogitAdapter = LowRankWorkspaceLogitAdapter


class LogitResidualRoute(nn.Module):
    """v4's gated low-rank vocabulary residual; zero at initialization."""

    def __init__(self, workspace_dim, vocab_size, host_dim, *, rank=32, gate_init_bias=-2.0):
        super().__init__()
        self.adapter = LowRankWorkspaceLogitAdapter(workspace_dim, vocab_size, rank)
        self.gate_norm = nn.LayerNorm(host_dim)
        self.gate = nn.Linear(host_dim, 1)
        nn.init.zeros_(self.gate.weight)
        nn.init.constant_(self.gate.bias, gate_init_bias)

    def forward(self, host_state, workspace_state, candidate_ids=None):
        """Gated residual logits, all columns or only ``candidate_ids``."""
        gate = torch.sigmoid(self.gate(self.gate_norm(host_state)))
        projected = F.gelu(self.adapter.down(self.adapter.norm(workspace_state)))
        weight = self.adapter.up.weight
        if candidate_ids is not None:
            weight = weight[candidate_ids]
        return gate * (projected @ weight.T), gate


class AnswerResidualRoute:
    """The V15-V19 path: the frozen native head reads ``state + delta`` at the last position."""

    def __init__(self, readout):
        self.readout = readout

    def __call__(self, normalized, delta):
        return self.readout(normalized, delta)


class CutResidualRoute:
    """The v9 path: add ``delta`` to the residual stream at cut N and let the host continue."""

    def __init__(self, host, cut):
        if not 0 <= int(cut) <= host.layer_count:
            raise ValueError("Cut must lie between 0 and the host's layer count")
        self.host, self.cut = host, int(cut)

    def __call__(self, input_ids, attention_mask, delta):
        """``delta`` is [B, L, H] (zero where nothing is written)."""
        hidden = self.host.to_cut(input_ids, attention_mask, self.cut)
        if delta.shape != hidden.shape:
            raise ValueError("Residual must match the cut's hidden shape")
        return self.host.from_cut(hidden + delta.to(hidden.dtype), attention_mask, self.cut)
