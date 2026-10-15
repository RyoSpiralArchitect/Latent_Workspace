"""Additive split-query prototype for the V18 selection factor.

The writer, common route, interaction arithmetic and parameter layout match V16.
Only the interaction query is a separate inference input. Query construction and
operand binding belong to the pipeline, not this reader. This prototype has no
qualified learner/checkpoint owner and establishes no semantic improvement.
"""

from __future__ import annotations

import math

import torch
from torch import nn

from .precision_bridge import _finite
from .v15_native_learner import reader_descriptor


class SelectionWorkspaceBridge(nn.Module):
    """Keep common-query output and budget independent of interaction selection.

    The two query inputs accept the historical one-position geometry, including
    native BF16 values; computation remains FP32. Their normalized shapes must
    agree. Passing the same tensor twice retains V16 forward/backward arithmetic.
    No label, candidate, donor identity or selection-mode input is accepted here.
    """

    def __init__(self, common, *, mode="slot_contrast", interaction_fraction=0.25):
        super().__init__()
        if mode not in ("slot_contrast", "raw_matched_control"):
            raise ValueError("Unknown V18 interaction factor")
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
            "schema": "v18-selection-prototype-v1",
            "mode": self.mode,
            "interaction_fraction": self.interaction_fraction,
            "common": dict(self.common_descriptor),
            "total_cap": self.max_delta_norm,
            "budget": "interaction_fraction * remaining common-route norm budget",
            "inference_inputs": [
                "common_question_features",
                "interaction_question_features",
                "written_memory",
                "mask",
            ],
            "query_routes": {
                "common": "common_query only",
                "interaction": "interaction_query only; budget from common output",
            },
            "checkpoint_qualification": "NOT_ADMITTED_BY_V18_OWNER",
        }

    def write_memory(self, context, mask):
        # No question, answer or donor-side input can enter the writer.
        return self.common.write_memory(context, mask)

    def _validate_queries(self, common_query, interaction_query, memory):
        if not isinstance(memory, torch.Tensor):
            raise ValueError("Reader memory must be a tensor")
        shapes = []
        for name, query in (
            ("Common query", common_query),
            ("Interaction query", interaction_query),
        ):
            if not isinstance(query, torch.Tensor):
                raise ValueError(f"{name} must be a tensor")
            shape = tuple(query.shape)
            if query.ndim == 2:
                shape = (query.shape[0], 1, query.shape[1])
            if len(shape) != 3 or shape[1:] != (1, self.hidden_dim) or shape[0] < 1:
                raise ValueError(f"{name} must have shape [B,1,hidden_dim] or [B,hidden_dim]")
            if not query.is_floating_point() or query.device != memory.device:
                raise ValueError(f"{name} must be floating point on the memory device")
            _finite(query, name)
            # A finite FP64 input can still overflow the historical FP32 cast.
            _finite(query.float(), f"{name} after FP32 conversion")
            shapes.append(shape)
        if shapes[0] != shapes[1]:
            raise ValueError("Common and interaction query geometry must match")

    def parts(self, common_query, interaction_query, memory, mask):
        self.describe()
        # Validate both routes before allowing the common reader to compute.
        self._validate_queries(common_query, interaction_query, memory)
        if any(p.dtype != torch.float32 or p.device != memory.device for p in self.parameters()):
            raise ValueError("All reader parameters must be FP32 on the input device")
        common = self.common.read_delta(common_query, memory, mask)
        query = interaction_query
        if query.ndim == 2:
            query = query.unsqueeze(1)
        with torch.autocast(device_type=query.device.type, enabled=False):
            values = self.common.memory_norm(memory.float())
            if self.mode == "slot_contrast":
                # Preserve V16 anchor-first centering and masked-slot geometry.
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
        _finite(delta, "V18 selection residual")
        return {"common": common, "interaction": interaction, "delta": delta}

    def read_delta(self, common_query, interaction_query, memory, mask):
        return self.parts(common_query, interaction_query, memory, mask)["delta"]
