"""Workspace algorithm modules, independent of a host transformer layout.

Legacy defaults preserve parameter names and operation order. Normalization
replacement is explicit and does not change native backbone normalization.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn
from torch.nn import functional as F

from .normalization import NormalizationSpec


@dataclass(frozen=True)
class ReaderState:
    """Different finite-precision objects; never substitute one for another."""

    initial_state: torch.Tensor
    final_state: torch.Tensor
    per_step_updates: tuple[torch.Tensor, ...]
    gate_mean: torch.Tensor
    read_norm: torch.Tensor

    @property
    def recovered_delta(self) -> torch.Tensor:
        return self.final_state - self.initial_state

    @property
    def cumulative_update(self) -> torch.Tensor:
        if not self.per_step_updates:
            return torch.zeros_like(self.initial_state)
        result = self.per_step_updates[0]
        for update in self.per_step_updates[1:]:
            result = result + update
        return result


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
        norm_spec: NormalizationSpec = NormalizationSpec(),
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
        self.slot_norm = norm_spec.build(workspace_dim)
        self.context_norm = norm_spec.build(workspace_dim)
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
        self.ff_norm = norm_spec.build(workspace_dim)
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
            trajectory = memory.unsqueeze(2).expand(-1, -1, self.steps, -1).contiguous()
            return memory, valid.to(context_attention_mask.dtype), trajectory, memory

        if self.mode == "fixed_carrier":
            positions = torch.arange(
                self.slot_count * self.workspace_dim,
                device=context_hidden.device,
                dtype=torch.float32,
            ).reshape(self.slot_count, self.workspace_dim)
            carrier = torch.sin(positions * 0.017) + torch.cos(positions * 0.031)
            carrier = F.layer_norm(carrier, (self.workspace_dim,))
            memory = (
                carrier.to(context_hidden.dtype)
                .unsqueeze(0)
                .expand(context_hidden.shape[0], -1, -1)
            )
            mask = torch.ones(
                (context_hidden.shape[0], self.slot_count),
                device=context_hidden.device,
                dtype=context_attention_mask.dtype,
            )
            trajectory = memory.unsqueeze(2).expand(-1, -1, self.steps, -1).contiguous()
            return memory, mask, trajectory, memory

        if self.mode != "slots":
            raise ValueError(f"Unsupported functional memory mode: {self.mode}")

        context = self.context_projection(context_hidden)
        context = self.context_norm(context)
        state = self.slot_seed.to(context.dtype).unsqueeze(0).expand(context.shape[0], -1, -1)
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
        zero_initialize_output: bool = True,
        norm_spec: NormalizationSpec = NormalizationSpec(),
    ) -> None:
        super().__init__()
        if hidden_dim % heads != 0:
            raise ValueError("hidden_dim must be divisible by functional reader heads.")
        self.hidden_dim = int(hidden_dim)
        self.memory_dim = int(memory_dim)
        self.steps = int(steps)
        self.injection_scale = float(injection_scale)
        self.query_norm = norm_spec.build(hidden_dim)
        self.memory_norm = norm_spec.build(memory_dim)
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
        if zero_initialize_output:
            # Exact query-only equality at initialization; the route opens only
            # when task or counterfactual supervision finds useful memory.
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
        result = self.read_state(query_hidden, query_attention_mask, memory, memory_attention_mask)
        return result.final_state, result.gate_mean, result.read_norm

    def read_state(
        self,
        query_hidden: torch.Tensor,
        query_attention_mask: torch.Tensor,
        memory: torch.Tensor,
        memory_attention_mask: torch.Tensor,
    ) -> ReaderState:
        if query_hidden.ndim != 3 or memory.ndim != 3:
            raise ValueError("Functional reader expects rank-3 query and memory tensors.")
        state = query_hidden
        projected_memory = self.memory_projection(self.memory_norm(memory))
        key_padding = ~memory_attention_mask.to(torch.bool)
        gate_values: list[torch.Tensor] = []
        read_norms: list[torch.Tensor] = []
        updates: list[torch.Tensor] = []
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
            applied_update = route_update * valid_query
            state = state + applied_update
            updates.append(applied_update)
            gate_values.append(gate)
            read_norms.append(read.float().norm(dim=-1).mean())
        return ReaderState(
            initial_state=query_hidden,
            final_state=state,
            per_step_updates=tuple(updates),
            gate_mean=torch.stack(gate_values).mean(),
            read_norm=torch.stack(read_norms).mean(),
        )
