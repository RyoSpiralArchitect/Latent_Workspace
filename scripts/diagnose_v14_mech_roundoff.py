#!/usr/bin/env python3
"""Read-only CPU diagnostic for the sealed collapsed-slot FP32 exact-zero test.

Prints one JSON receipt; writes no artifacts and changes no test tolerances.
The fixture and intervention are imported from their actual source files.
Float64 is a numerical reference, not an alternative production implementation.
"""

from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path

import torch
from torch.nn import functional as F

from latent_workspace_ft_v10.bridge_mechanistic import intervention_delta, trace_reader


def gamma(count: int, unit_roundoff: float) -> float:
    return count * unit_roundoff / (1 - count * unit_roundoff)


def slot_max_difference(value: torch.Tensor) -> float:
    return float((value - value[..., :1, :]).abs().max())


@torch.no_grad()
def main() -> None:
    root = Path(__file__).resolve().parents[1]
    fixture_path = root / "tests/test_bridge_mechanistic.py"
    bridge, query, memory, mask = runpy.run_path(str(fixture_path))["_fixture"]()
    assert query.device.type == "cpu"
    memory = memory[:, :1].expand(-1, 4, -1).clone()
    trace = trace_reader(bridge, query, memory, mask)
    normalized = trace["normalized_memory"]
    value_weight = bridge.attention.in_proj_weight.chunk(3, dim=0)[2]
    width, heads, slots = bridge.workspace_dim, bridge.attention.num_heads, memory.shape[1]
    assert slots == 4 and mask.bool().all()

    def as_heads(value):
        return value.reshape(value.shape[0], slots, heads, width // heads).transpose(1, 2)

    projected64 = as_heads(F.linear(normalized.double(), value_weight.double()))
    projected32 = trace["v_heads"]
    unit32, unit64 = torch.finfo(torch.float32).eps / 2, torch.finfo(torch.float64).eps / 2
    # Standard componentwise dot-product bound, also accounting for rounding
    # in the FP64 reference: |fl32(xW)-fl64(xW)| <= (gamma32_D+gamma64_D)|x||W|.
    absolute_products = as_heads(F.linear(normalized.double().abs(), value_weight.double().abs()))
    projection_bound = (gamma(width, unit32) + gamma(width, unit64)) * absolute_products
    projection_error = (projected32.double() - projected64).abs()
    values64 = projected32.double()
    mean32 = projected32.sum(-2, keepdim=True) / slots
    mean64 = values64.mean(-2, keepdim=True)
    centered32, centered64 = projected32 - mean32, values64 - mean64
    delta = intervention_delta(bridge, trace, "centered_values")

    # For identical mathematical projected slots, each centered component is
    # bounded by its projection error plus mean projection/reduction errors.
    # Division by four is exact for these normal numbers. Propagate this bound
    # through the actual nonnegative weights and two bias-free linear maps.
    center_bound = (
        projection_bound
        + projection_bound.mean(-2, keepdim=True)
        + gamma(slots - 1, unit32) * values64.abs().mean(-2, keepdim=True)
    ) * (1 + unit32)
    weighted_bound = torch.matmul(trace["attention_weights"].double().abs(), center_bound)
    weighted_bound *= 1 + gamma(slots, unit32)
    joined_bound = weighted_bound.transpose(1, 2).reshape(query.shape[0], 1, width)
    output_bound = F.linear(joined_bound, bridge.attention.out_proj.weight.double().abs())
    output_bound *= 1 + gamma(width, unit32)
    delta_bound = F.linear(output_bound, bridge.up.weight.double().abs())
    delta_bound *= (1 + gamma(width, unit32)) * (1 + 5 * unit32)

    checks = {
        "input_slots_exact": slot_max_difference(memory) == 0,
        "normalized_slots_exact": slot_max_difference(normalized) == 0,
        "fp64_projection_slots_exact": slot_max_difference(projected64) == 0,
        "projection_error_within_analytic_bound": bool(
            (projection_error <= projection_bound).all()
        ),
        "centered_values_within_analytic_bound": bool(
            (centered32.double().abs() <= center_bound).all()
        ),
        "bounded_delta_within_propagated_bound": bool((delta.double().abs() <= delta_bound).all()),
        "finite": bool(torch.isfinite(delta_bound).all() and torch.isfinite(delta).all()),
    }
    receipt = {
        "format": "v14-collapsed-slot-projection-roundoff-diagnostic-v1",
        "torch_version": torch.__version__,
        "device": "cpu",
        "float32_matmul_precision": torch.get_float32_matmul_precision(),
        "cpu_threads": torch.get_num_threads(),
        "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "input_slot_max_difference": slot_max_difference(memory),
        "normalized_slot_max_difference": slot_max_difference(normalized),
        "projected_fp32_slot_max_difference": slot_max_difference(projected32),
        "projected_fp64_slot_max_difference": slot_max_difference(projected64),
        "projection_error_max": float(projection_error.max()),
        "projection_analytic_bound_max": float(projection_bound.max()),
        "unit_roundoff_fp32": unit32,
        "projection_dot_dimension": width,
        "projection_gamma_dim": gamma(width, unit32),
        "fp32_mean_vs_same_values_fp64_mean_max": float((mean32.double() - mean64).abs().max()),
        "centered_fp32_max_abs": float(centered32.abs().max()),
        "same_values_centered_fp64_max_abs": float(centered64.abs().max()),
        "centered_delta_max_abs": float(delta.abs().max()),
        "propagated_delta_analytic_bound_max": float(delta_bound.max()),
        "exact_zero_assertion_holds_on_this_runtime": bool(torch.count_nonzero(delta) == 0),
        "formal_tolerances_changed": False,
        "claim_boundary": (
            "Toy CPU arithmetic diagnosis only; sealed test result remains unchanged."
        ),
    }
    print(json.dumps(receipt, indent=2, allow_nan=False))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
