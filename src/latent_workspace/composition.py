"""Composition: a workspace over host states, speaking through a route.

``DeliberationRoute`` is promoted verbatim from ``v20_deliberation.py`` in
``latent_workspace_ft_v10`` at ``d4cd1ee0340a``: v5's causal-broadcast lattice
over host states feeding v4's gated low-rank logit residual, as in V19.5 D1.
The historical file is frozen; this module is the living home
(docs/ARCHITECTURE.md). Parity: ``test_deliberation_route_is_the_d1_route``.

Option added in the engine (V20 A2), an explicit change with its own tests:
**deferred memory**. ``forward(hidden, mask, memory, memory_mask)`` places each
row's valid memory states before its valid query states (``pack_memory``), so
query positions attend to a memory the host never saw with the query. Without
``memory`` the forward is the promoted one, bit for bit.
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


def pack_memory(memory, memory_mask, hidden, mask):
    """Per row: its valid memory states, then its valid query states, then padding.

    Both inputs must be left-aligned (valid states first), as ``FeatureBank``
    batches them. Returns the packed states [B, M + L, H] and their mask.
    """
    if memory.ndim != 3 or memory_mask is None or memory_mask.shape != memory.shape[:2]:
        raise ValueError("Expected memory [B, M, H] and memory_mask [B, M]")
    if memory.shape[0] != hidden.shape[0] or memory.shape[2] != hidden.shape[2]:
        raise ValueError("Memory and query differ in batch or width")
    counts = []
    for values, name in ((memory_mask, "memory"), (mask, "query")):
        count = values.long().sum(1)
        positions = torch.arange(values.shape[1], device=values.device)
        if not torch.equal(values.long(), (positions[None] < count[:, None]).long()):
            raise ValueError(f"The {name} mask must be left-aligned")
        counts.append(count)
    if (counts[1] < 1).any():
        raise ValueError("Empty row")
    width = memory.shape[1] + hidden.shape[1]
    packed = hidden.new_zeros(hidden.shape[0], width, hidden.shape[2])
    packed_mask = mask.new_zeros(hidden.shape[0], width)
    for row, (m, q) in enumerate(zip(counts[0].tolist(), counts[1].tolist(), strict=True)):
        packed[row, :m] = memory[row, :m]
        packed[row, m : m + q] = hidden[row, :q]
        packed_mask[row, : m + q] = 1
    return packed, packed_mask


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

    def forward(self, hidden, mask, memory=None, memory_mask=None):
        """Return (candidate logit deltas at the last valid position, latents, anchor, gate).

        With ``memory``, the lattice runs over the packed [memory; query] sequence;
        the gate and the residual still come from the query's last position.
        """
        if hidden.ndim != 3 or mask.shape != hidden.shape[:2]:
            raise ValueError("Expected hidden [B, L, H] and mask [B, L]")
        if memory is not None:
            hidden, mask = pack_memory(memory, memory_mask, hidden, mask)
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
