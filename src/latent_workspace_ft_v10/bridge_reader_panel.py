"""Production-path reverse-query panel for both uncentered and centered readers.

This training-world diagnostic hooks the actual MHA Q/K/V arguments. It does
not reconstruct attention or assume that K and V have identical inputs.
Uniform attention is induced with zero projected Q in bias-free MHA; slot
permutation moves K, V, and the key-padding mask together. Neither intervenes
on the language-model head or uses answer labels.
"""

from __future__ import annotations

import math
from typing import Any

import torch


def _capture(bridge, query, memory, mask):
    result = {"query": query.detach().clone()}

    def output(name):
        def hook(_module, _args, value):
            result[name] = (value[0] if isinstance(value, tuple) else value).detach().clone()

        return hook

    def inputs(_module, args, kwargs):
        for name, value in zip(("attention_q", "keys", "values"), args[:3]):
            result[name] = value.detach().clone()
        result["padding_mask"] = kwargs["key_padding_mask"].detach().clone()

    handles = [
        bridge.query_norm.register_forward_hook(output("projected_query")),
        bridge.attention.register_forward_pre_hook(inputs, with_kwargs=True),
        bridge.attention.register_forward_hook(output("attention_output")),
        bridge.up.register_forward_hook(output("raw_delta")),
    ]
    try:
        result["delta"] = bridge.read_delta(query, memory, mask).detach().clone()
    finally:
        for handle in handles:
            handle.remove()
    return result


def _control(bridge, trace, permutation=False):
    q = trace["attention_q"] if permutation else torch.zeros_like(trace["attention_q"])
    k, v, mask = (trace[name] for name in ("keys", "values", "padding_mask"))
    if permutation:
        k, v, mask = k.flip(1), v.flip(1), mask.flip(1)
    with torch.autocast(device_type=q.device.type, enabled=False):
        output, _ = bridge.attention(q, k, v, key_padding_mask=mask, need_weights=False)
        raw = bridge.up(output)
        scale = bridge.max_delta_norm / torch.sqrt(
            bridge.max_delta_norm**2 + raw.square().sum(dim=-1, keepdim=True)
        )
    return raw, raw * scale


def _norm(tensor):
    return float(torch.linalg.vector_norm(tensor.float()))


def _relative(first, second):
    return _norm(first.float() - second.float()) / (0.5 * (_norm(first) + _norm(second)) + 1e-12)


def _aggregate(rows, excluded):
    return {
        key: {
            "mean": sum(row[key] for row in rows) / len(rows),
            "mean_abs": sum(abs(row[key]) for row in rows) / len(rows),
            "max": max(row[key] for row in rows),
        }
        for key in rows[0]
        if key not in excluded
    }


@torch.no_grad()
def capture_reverse_panel(
    bridge,
    store,
    candidate_head_weight: torch.Tensor,
    device,
    world_count: int = 16,
) -> dict[str, Any]:
    """Capture first N worlds, sides 0/1, q0..7; pair q0/1, q2/3, q4/5, q6/7.

    ``store.query`` returns frozen [1,L,H] final-normalized features, and
    ``store.context`` returns [1,C,H] writer features. The model must already
    be in eval mode. Parameters, gradients, training mode and storage are not
    modified. Calling the same bridge concurrently is unsupported.
    Relative L2 uses mean endpoint norm plus 1e-12; zero/zero is reported as 0.
    These same-training-world traces are descriptive, not held-out evidence.
    """
    if any(module.training for module in bridge.modules()):
        raise ValueError("Reader panel requires bridge.eval()")
    if (
        int(world_count) != world_count
        or world_count < 1
        or world_count > len(store.records)
        or world_count > len(store.features)
    ):
        raise ValueError("world_count must select a nonempty available prefix of worlds")
    if (
        candidate_head_weight.shape != (2, bridge.hidden_dim)
        or not torch.isfinite(candidate_head_weight).all()
    ):
        raise ValueError("candidate_head_weight must be finite [2,H]")
    if bridge.attention.in_proj_bias is not None or bridge.attention.dropout != 0:
        raise ValueError("Uniform control requires bias-free, dropout-free attention")
    axis = (candidate_head_weight[1].float() - candidate_head_weight[0].float()).to(device)
    rows, pairs = [], []
    stages = (
        "query",
        "projected_query",
        "keys",
        "values",
        "attention_output",
        "raw_delta",
        "delta",
    )
    for world in range(int(world_count)):
        for side in (0, 1):
            context = store.context(world, side).to(device=device, dtype=torch.float32)
            memory, mask = bridge.write_memory(
                context, torch.ones(context.shape[:2], device=device)
            )
            previous = None
            for query_index in range(8):
                query = store.query(world, query_index)[:, -1:].to(device=device)
                trace = _capture(bridge, query, memory, mask)
                uniform_raw, uniform_delta = _control(bridge, trace)
                permutation_raw, permutation_delta = _control(bridge, trace, permutation=True)
                active = (~trace["padding_mask"]).float().unsqueeze(-1)
                values = trace["values"]
                mean = (values * active).sum(1, keepdim=True) / active.sum(1, keepdim=True)
                value_norm = _norm(values * active)
                row = {"world": world, "side": side, "query_index": query_index}
                row.update({f"{name}_l2": _norm(trace[name]) for name in stages})
                row.update(
                    {
                        "value_mean_fraction": _norm(mean * active) / (value_norm + 1e-12),
                        "value_centered_fraction": _norm((values - mean) * active)
                        / (value_norm + 1e-12),
                        "head_axis_gap": float((trace["delta"] * axis).sum()),
                        "uniform_raw_l2": _norm(uniform_raw),
                        "uniform_delta_l2": _norm(uniform_delta),
                        "uniform_head_axis_gap": float((uniform_delta * axis).sum()),
                        "uniform_vs_actual_relative_l2": _relative(uniform_delta, trace["delta"]),
                        "permutation_raw_max_abs_error": float(
                            (permutation_raw - trace["raw_delta"]).abs().max()
                        ),
                        "permutation_delta_max_abs_error": float(
                            (permutation_delta - trace["delta"]).abs().max()
                        ),
                    }
                )
                if not all(math.isfinite(value) for value in row.values()):
                    raise ValueError("Reader panel produced a nonfinite metric")
                rows.append(row)
                if query_index % 2:
                    pair = {
                        "world": world,
                        "side": side,
                        "even_query": query_index - 1,
                        "odd_query": query_index,
                    }
                    pair.update(
                        {
                            f"{name}_relative_l2": _relative(previous[name], trace[name])
                            for name in stages
                        }
                    )
                    pair["head_axis_gap_difference"] = float(
                        ((trace["delta"] - previous["delta"]) * axis).sum()
                    )
                    pairs.append(pair)
                else:
                    previous = trace
    return {
        "protocol": {
            "world_selection": "first_training_worlds",
            "world_count": int(world_count),
            "sides": [0, 1],
            "query_indices": list(range(8)),
            "relative_l2_denominator": "0.5 * (norm(a) + norm(b)) + 1e-12",
            "attention_path": "actual_Q_K_V_production_need_weights_false",
            "manual_reconstruction": False,
            "held_out_evidence": False,
        },
        "rows": rows,
        "pairs": pairs,
        "summary": {
            "row_count": len(rows),
            "pair_count": len(pairs),
            "row_metrics": _aggregate(rows, {"world", "side", "query_index"}),
            "pair_metrics": _aggregate(pairs, {"world", "side", "even_query", "odd_query"}),
        },
    }
