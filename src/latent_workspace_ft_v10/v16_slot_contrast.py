"""V16 candidate: preserve the common route, isolate slot-contrast capacity.

This is a reader prototype, not a qualified trainer/checkpoint format. It uses
only question features, written slots and their mask. Equal-slot carriers must
not drive its contrast route; that invariant is not factual grounding. A raw
slot control has identical parameters, initialization and norm/update budgets;
centering adds arithmetic and is not a proved FLOP/runtime match.
"""

from __future__ import annotations

import math

import torch
from torch import nn

from .precision_bridge import _finite
from .v15_native_learner import reader_descriptor


class SlotContrastWorkspaceBridge(nn.Module):
    def __init__(self, common, *, mode="slot_contrast", interaction_fraction=0.25):
        super().__init__()
        if mode not in ("slot_contrast", "raw_matched_control"):
            raise ValueError("Unknown V16 interaction factor")
        if (
            type(interaction_fraction) not in (int, float)
            or not math.isfinite(interaction_fraction)
            or not 0 < interaction_fraction <= 1
        ):
            raise ValueError("Interaction fraction must be finite in (0,1]")
        self.common_descriptor = reader_descriptor(common)
        self.common, self.mode = common, mode
        self.interaction_fraction = float(interaction_fraction)
        self.hidden_dim, self.workspace_dim = common.hidden_dim, common.workspace_dim
        self.max_delta_norm = common.max_delta_norm
        self.slots = common.slots
        self.query_projection = nn.Linear(self.hidden_dim, self.workspace_dim, bias=False)
        self.query_norm = nn.LayerNorm(self.workspace_dim)
        self.attention = nn.MultiheadAttention(
            self.workspace_dim,
            common.attention.num_heads,
            bias=False,
            dropout=0,
            batch_first=True,
        )
        self.up = nn.Linear(self.workspace_dim, self.hidden_dim, bias=False)
        nn.init.zeros_(self.up.weight)
        self.to(device=next(common.parameters()).device, dtype=torch.float32)

    def describe(self):
        if reader_descriptor(self.common) != self.common_descriptor:
            raise ValueError("Common reader policy changed")
        return {
            "schema": "v16-slot-contrast-prototype-v1",
            "mode": self.mode,
            "interaction_fraction": self.interaction_fraction,
            "common": dict(self.common_descriptor),
            "total_cap": self.max_delta_norm,
            "budget": "interaction_fraction * remaining common-route norm budget",
            "inference_inputs": ["question_features", "written_memory", "mask"],
            "checkpoint_qualification": "NOT_ADMITTED_BY_V15_OWNER",
        }

    def write_memory(self, context, mask):
        # No question, answer or donor-side input can enter the writer.
        return self.common.write_memory(context, mask)

    def parts(self, query, memory, mask):
        self.describe()
        if any(p.dtype != torch.float32 or p.device != memory.device for p in self.parameters()):
            raise ValueError("All reader parameters must be FP32 on the input device")
        common = self.common.read_delta(query, memory, mask)  # Reuses input validation.
        if query.ndim == 2:
            query = query.unsqueeze(1)
        with torch.autocast(device_type=query.device.type, enabled=False):
            values = self.common.memory_norm(memory.float())
            if self.mode == "slot_contrast":
                # Anchor subtraction first makes identical slots EXACTLY zero,
                # including non-power-of-two slot counts and masked padding.
                first = mask.bool().long().argmax(dim=1)
                anchor = values.gather(1, first[:, None, None].expand(-1, 1, self.workspace_dim))
                offsets = (values - anchor).masked_fill(~mask.bool().unsqueeze(-1), 0)
                mean = offsets.sum(dim=1, keepdim=True) / mask.sum(dim=1)[:, None, None]
                values = (offsets - mean).masked_fill(~mask.bool().unsqueeze(-1), 0)
            projected = self.query_norm(self.query_projection(query.float()))
            read, _ = self.attention(
                projected, values, values, key_padding_mask=~mask.bool(), need_weights=False
            )
            raw = self.up(read)
            cap = self.max_delta_norm
            bounded = raw * (cap / torch.sqrt(cap**2 + raw.square().sum(-1, keepdim=True)))
            remaining_fraction = (1 - common.norm(dim=-1, keepdim=True) / cap).clamp(0, 1)
            interaction = self.interaction_fraction * remaining_fraction * bounded
            delta = common + interaction
        _finite(delta, "V16 residual")
        return {"common": common, "interaction": interaction, "delta": delta}

    def read_delta(self, query, memory, mask):
        return self.parts(query, memory, mask)["delta"]
