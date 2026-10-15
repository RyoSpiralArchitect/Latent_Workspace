"""V19 reader: separate norm budgets for the common and workspace routes.

The V18 selection reader gave its interaction ("workspace") route
``interaction_fraction * (1 - |common| / cap)`` of a shared budget. The frozen
V18 diagnostic showed the common route saturating that cap for any real memory,
which starves the workspace route. This additive reader keeps the common route
unchanged (its own soft cap) and bounds the workspace route by its own
independent soft cap. Writer, centering, queries, parameter layout and
initialization order match V18, so matched arms start from identical tensors.
Nothing here is admitted by a V18 owner or checkpoint format.
"""

from __future__ import annotations

import math

import torch
from torch import nn

from .precision_bridge import _finite
from .v15_native_learner import reader_descriptor


class DualBudgetWorkspaceBridge(nn.Module):
    """Common route as before; workspace route with its own bounded norm.

    ``delta = common + workspace`` with ``|common| < common_cap`` (the common
    reader's unchanged soft cap) and ``|workspace| < workspace_cap``. The
    workspace output never depends on the common output's norm. No label,
    candidate, donor identity or selection-mode input is accepted here.
    """

    MODES = ("slot_contrast", "raw_matched_control")

    def __init__(self, common, *, mode="slot_contrast", workspace_cap=0.25):
        super().__init__()
        if mode not in self.MODES:
            raise ValueError("Unknown V19 workspace value factor")
        if (
            type(workspace_cap) not in (int, float)
            or not math.isfinite(workspace_cap)
            or workspace_cap <= 0
        ):
            raise ValueError("Workspace cap must be finite and positive")
        self.common_descriptor = reader_descriptor(common)
        self.common, self.mode = common, mode
        self.workspace_cap = float(workspace_cap)
        self.hidden_dim, self.workspace_dim = common.hidden_dim, common.workspace_dim
        self.common_cap = common.max_delta_norm
        self.slots = common.slots
        # Creation order matches the V16/V18 interaction route exactly.
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
            "schema": "v19-dual-budget-reader-v1",
            "mode": self.mode,
            "common": dict(self.common_descriptor),
            "common_cap": self.common_cap,
            "workspace_cap": self.workspace_cap,
            "budget": "independent soft caps; workspace norm never scaled by common norm",
            "total_bound": "strictly below common_cap + workspace_cap",
            "inference_inputs": [
                "common_question_features",
                "workspace_question_features",
                "written_memory",
                "mask",
            ],
            "query_routes": {
                "common": "common_query only",
                "workspace": "workspace_query only; separate budget",
            },
            "checkpoint_qualification": "V19_OWNER_ONLY",
        }

    def write_memory(self, context, mask):
        # No question, answer or donor-side input can enter the writer.
        return self.common.write_memory(context, mask)

    def _validate_queries(self, common_query, workspace_query, memory):
        if not isinstance(memory, torch.Tensor):
            raise ValueError("Reader memory must be a tensor")
        shapes = []
        for name, query in (("Common query", common_query), ("Workspace query", workspace_query)):
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
            _finite(query.float(), f"{name} after FP32 conversion")
            shapes.append(shape)
        if shapes[0] != shapes[1]:
            raise ValueError("Common and workspace query geometry must match")

    def parts(self, common_query, workspace_query, memory, mask):
        self.describe()
        self._validate_queries(common_query, workspace_query, memory)
        if any(p.dtype != torch.float32 or p.device != memory.device for p in self.parameters()):
            raise ValueError("All reader parameters must be FP32 on the input device")
        common = self.common.read_delta(common_query, memory, mask)
        query = workspace_query
        if query.ndim == 2:
            query = query.unsqueeze(1)
        with torch.autocast(device_type=query.device.type, enabled=False):
            values = self.common.memory_norm(memory.float())
            if self.mode == "slot_contrast":
                # Same anchor-first centering and masked-slot geometry as V16/V18.
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
            cap = self.workspace_cap
            workspace = raw * (cap / torch.sqrt(cap**2 + raw.square().sum(-1, keepdim=True)))
            delta = common + workspace
        _finite(delta, "V19 dual-budget residual")
        return {"common": common, "interaction": workspace, "delta": delta}

    def read_delta(self, common_query, workspace_query, memory, mask):
        return self.parts(common_query, workspace_query, memory, mask)["delta"]
