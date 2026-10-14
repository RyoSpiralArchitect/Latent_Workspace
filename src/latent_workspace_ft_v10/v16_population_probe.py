"""Read-only, model-neutral slot/selection/amplitude decomposition.

The attention weights below are an observer recomputation, not replacements for
the production SDPA output. No attention hook, activation patch, gain, precision
override, optimizer or inference-label input is installed.
"""

from __future__ import annotations

import torch

from .v16_slot_contrast import SlotContrastWorkspaceBridge


@torch.no_grad()
def slot_trace(bridge, query, memory, mask):
    if not isinstance(bridge, SlotContrastWorkspaceBridge):
        return {"interaction_present": False}
    if query.ndim == 2:
        query = query.unsqueeze(1)
    valid = mask.bool().unsqueeze(-1)
    normed = bridge.common.memory_norm(memory.float())
    first = mask.bool().long().argmax(1)
    anchor = normed.gather(1, first[:, None, None].expand(-1, 1, bridge.workspace_dim))
    offsets = (normed - anchor).masked_fill(~valid, 0)
    centered = offsets - offsets.sum(1, keepdim=True) / mask.sum(1)[:, None, None]
    centered = centered.masked_fill(~valid, 0)
    values = centered if bridge.mode == "slot_contrast" else normed
    projected = bridge.query_norm(bridge.query_projection(query.float()))
    read, _ = bridge.attention(
        projected, values, values, key_padding_mask=~mask.bool(), need_weights=False
    )
    # Shadow observer only: weights=True may select a different kernel.
    shadow_read, weights = bridge.attention(
        projected,
        values,
        values,
        key_padding_mask=~mask.bool(),
        need_weights=True,
        average_attn_weights=False,
    )
    uniform_read, _ = bridge.attention(
        torch.zeros_like(projected),
        values,
        values,
        key_padding_mask=~mask.bool(),
        need_weights=False,
    )
    uniform = mask.float() / mask.sum(-1, keepdim=True)
    raw = bridge.up(read)
    cap = bridge.max_delta_norm
    bounded = raw * (cap / torch.sqrt(cap**2 + raw.square().sum(-1, keepdim=True)))
    parts = bridge.parts(query, memory, mask)
    remaining = (1 - parts["common"].norm(dim=-1, keepdim=True) / cap).clamp(0, 1)
    reconstructed = bridge.interaction_fraction * remaining * bounded
    if not torch.equal(reconstructed, parts["interaction"]):
        raise ValueError("Trace changed the production interaction arithmetic")
    total = normed.masked_fill(~valid, 0).norm()
    return {
        "interaction_present": True,
        "mode": bridge.mode,
        "memory_l2": float(memory.masked_fill(~valid, 0).norm()),
        "normalized_slots_l2": float(total),
        "centered_slots_l2": float(centered.norm()),
        "centered_fraction": float(centered.norm() / total) if total else None,
        "projected_query_l2": float(projected.norm()),
        "attention_weights_shadow": weights.cpu().double().tolist(),
        "attention_uniform_l1_mean": float((weights - uniform[:, None, None]).abs().sum(-1).mean()),
        "attention_entropy_mean": float(-(weights * weights.clamp_min(1e-30).log()).sum(-1).mean()),
        "shadow_read_disagreement_l2": float((shadow_read - read).norm()),
        "production_read_l2": float(read.norm()),
        "uniform_query_read_l2": float(uniform_read.norm()),
        "read_minus_uniform_l2": float((read - uniform_read).norm()),
        "up_raw_l2": float(raw.norm()),
        "up_bounded_l2": float(bounded.norm()),
        "remaining_budget_fraction": float(remaining.item()),
        "common_l2": float(parts["common"].norm()),
        "interaction_l2": float(parts["interaction"].norm()),
        "interaction_reconstruction_exact": True,
        "shadow_weights_are_production_output": False,
    }


def choice4(scores):
    if len(scores) != 4 or not all(torch.isfinite(torch.tensor(x)) for x in scores):
        raise ValueError("Four finite native candidate scores required")
    best = max(scores)
    selected = [i for i, value in enumerate(scores) if value == best]
    return {
        "prediction": selected[0],
        "strict_prediction": selected[0] if len(selected) == 1 else None,
        "tie": len(selected) != 1,
        "scores": list(scores),
    }
