"""Frozen cut-state factorization; never a detached-state training interface.

Memory writer, query/continuation encoder and upper reader are independent
*interventions*, not independent parameter groups of the shared native host.
"""

from __future__ import annotations

import torch

from . import execution as ex
from .composition import pack_memory


def cut_state_logits(graph, query, memory=None):
    """Continue unpadded batch-one states through the native reader/full head.

    All query tokens, including the fixed continuation, must come from one
    encoder at the exact observed prefix extent. No re-encoding, parameters,
    cache, precision change, token selection or position adjustment is hidden
    here. Empty memory uses split-native inference and MUST be qualified
    against the ordinary native bypass before scientific interpretation.
    """
    ex.require(not graph.training and not torch.is_grad_enabled(), "Read-only state factorial")
    weight = graph.host.head.weight
    for name, value in (("query", query), ("memory", memory)):
        if value is None:
            ex.require(name == "memory", "Query states required")
            continue
        ex.require(
            isinstance(value, torch.Tensor)
            and value.ndim == 3
            and value.shape[0] == 1
            and value.shape[1] > 0
            and value.shape[2] == graph.host.hidden_size
            and value.dtype == weight.dtype
            and value.device == weight.device
            and not value.requires_grad
            and bool(torch.isfinite(value).all()),
            f"Invalid {name} cut states",
        )
    mask = torch.ones(query.shape[:2], dtype=torch.long, device=query.device)
    if memory is None:
        final = graph.host.from_cut_states(query, mask, graph.cut)
    else:
        mm = torch.ones(memory.shape[:2], dtype=torch.long, device=query.device)
        packed, packed_mask = pack_memory(memory, mm, query, mask)
        states = graph.host.from_cut_states(packed, packed_mask, graph.cut)
        # Same gather/head shape as NativeMemoryCausalLM, including BF16 GEMM.
        columns = memory.shape[1] + torch.arange(query.shape[1], device=query.device)[None]
        final = states[torch.arange(1, device=query.device)[:, None], columns]
    return graph.host.head(final)
