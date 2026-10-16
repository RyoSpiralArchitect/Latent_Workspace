"""Composition: a workspace over host states, speaking through a route.

``DeliberationRoute`` is promoted verbatim from ``v20_deliberation.py`` in
``latent_workspace_ft_v10`` at ``d4cd1ee0340a``: v5's causal-broadcast lattice
over host states feeding v4's gated low-rank logit residual, as in V19.5 D1.
The historical file is frozen; this module is the living home
(docs/ARCHITECTURE.md). Parity: ``test_deliberation_route_is_the_d1_route``.
"""

from __future__ import annotations

import contextlib

import torch
from torch import nn
from torch.nn import functional as F

from .lattice import CausalBroadcastLatentWorkspace
from .routes import LowRankWorkspaceLogitAdapter
from .training import component_seed, seeded

MAX_STEPS = 4


class DeliberationRoute(nn.Module):
    """v4 route: lattice over final hidden states, gated low-rank vocabulary residual."""

    def __init__(
        self,
        hidden_dim,
        vocab_size,
        candidate_ids,
        *,
        steps,
        seed,
        workspace_dim=256,
        heads=8,
        ff_multiplier=2.0,
        dropout=0.05,
        rank=32,
        gate_init_bias=-2.0,
    ):
        super().__init__()
        if steps not in range(MAX_STEPS + 1):
            raise ValueError("steps must be 0..4")
        if len(candidate_ids) != 2 or len(set(candidate_ids)) != 2:
            raise ValueError("Two distinct candidate ids required")
        self.steps = int(steps)
        self.register_buffer(
            "candidate_ids", torch.tensor(list(candidate_ids), dtype=torch.long), persistent=False
        )
        with seeded(component_seed(seed, "lattice")):
            self.lattice = CausalBroadcastLatentWorkspace(
                hidden_dim,
                workspace_dim,
                max(self.steps, 1),
                ff_multiplier=ff_multiplier,
                dropout=dropout,
                anchor_refresh="initial_only",
                attention_heads=heads,
                attention_dropout=0.0,
                causal_window=0,
            )
        generator = torch.Generator().manual_seed(component_seed(seed, "step_embeddings"))
        shared = torch.randn(MAX_STEPS, workspace_dim, generator=generator) * 0.02
        with torch.no_grad():
            self.lattice.step_embeddings.copy_(shared[: max(self.steps, 1)])
        with seeded(component_seed(seed, "adapter")):
            self.adapter = LowRankWorkspaceLogitAdapter(workspace_dim, vocab_size, rank)
        with seeded(component_seed(seed, "gate")):
            self.gate_norm = nn.LayerNorm(hidden_dim)
            self.gate = nn.Linear(hidden_dim, 1)
        nn.init.zeros_(self.gate.weight)
        nn.init.constant_(self.gate.bias, gate_init_bias)

    @contextlib.contextmanager
    def truncated(self, steps):
        """Run the first ``steps`` latent steps of the same weights (inference only)."""
        if steps is None:
            yield
            return
        if self.steps == 0 or not 1 <= steps <= self.steps:
            raise ValueError("Truncation needs a lattice and 1 <= steps <= configured steps")
        old = self.lattice.steps
        self.lattice.steps = int(steps)
        try:
            yield
        finally:
            self.lattice.steps = old

    def forward(self, hidden, mask):
        """Return (candidate logit deltas at the last valid position, latents, anchor, gate)."""
        if hidden.ndim != 3 or mask.shape != hidden.shape[:2]:
            raise ValueError("Expected hidden [B, L, H] and mask [B, L]")
        last = mask.long().sum(1) - 1
        if (last < 0).any():
            raise ValueError("Empty row")
        rows = torch.arange(hidden.shape[0], device=hidden.device)
        if self.steps == 0:
            latents = None
            anchor = self.lattice.input_projection(self.lattice.input_norm(hidden))
            final = anchor[rows, last]
        else:
            latents, anchor = self.lattice(hidden, mask)
            final = latents[rows, last, -1]
        gate = torch.sigmoid(self.gate(self.gate_norm(hidden[rows, last])))
        projected = F.gelu(self.adapter.down(self.adapter.norm(final)))
        delta = projected @ self.adapter.up.weight[self.candidate_ids].T
        return gate * delta, latents, anchor, gate
