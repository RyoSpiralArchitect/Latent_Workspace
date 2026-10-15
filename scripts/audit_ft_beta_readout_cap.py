#!/usr/bin/env python3
"""CPU-only, posthoc geometric capacity audit; never changes a training gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

import torch

REVISION = "c170c708c41dac9275d15a8fff4eca08d52bab71"
BASE_HASH = "54d161755862ebf00d8acbca083d5f290a5de44d33af82ca885f3bd8f9c94312"
PARENT_PLAN = "configs/v14/PRECISION_BRIDGE_PLAN.json"
PARENT_PLAN_HASH = "f4951afb8772dc3806e00ed308b896a4c9d345afccceb9828fa3f5d330eea3f1"
CANDIDATE_IDS = (1476, 5849)
CAP = 1.0
ARITHMETIC_GUARD = 1e-4
FP32 = "fp32_choice_head"
NATIVE = "native_bf16_head"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite numeric data")
    return float(value)


def _gap(state):
    scores = state["scores"]
    if not isinstance(scores, list) or len(scores) != 2:
        raise ValueError("Expected exactly two candidate scores")
    left, right = (_finite(value, "score") for value in scores)
    gap = _finite(state["yes_minus_no"], "gap")
    choice = None if gap == 0 else int(gap > 0)
    if right - left != gap or state["greedy_choice"] != choice or state["tie"] != (gap == 0):
        raise ValueError("Score, gap, tie, and greedy-choice receipts disagree")
    return gap


def analyze_rows(rows, *, axis_norm, cap=CAP, arithmetic_guard=ARITHMETIC_GUARD):
    """Audit 32 intact rows, conditional on a real-arithmetic linear readout.

    FP32 receipts are observations, not exact-real base logits. The numerical
    guard is a diagnostic exclusion band, NOT a rigorous floating-point error
    bound. A geometric ceiling under these assumptions is not a BF16 bound.
    """
    axis_norm = _finite(axis_norm, "axis norm")
    cap = _finite(cap, "cap")
    arithmetic_guard = _finite(arithmetic_guard, "arithmetic guard")
    if axis_norm <= 0 or cap <= 0 or arithmetic_guard < 0:
        raise ValueError("Axis norm and cap must be positive; arithmetic guard nonnegative")
    expected = {(world, query, side) for world in range(2) for query in range(8) for side in (0, 1)}
    intact = [row for row in rows if row["control"] == "intact"]
    indexed = {}
    for row in intact:
        key = tuple(row[name] for name in ("world_index", "query_index", "side"))
        if any(isinstance(value, bool) or not isinstance(value, int) for value in key):
            raise ValueError("Row identity must contain integer indices")
        if key in indexed:
            raise ValueError("Duplicate intact row")
        indexed[key] = row
    if set(indexed) != expected:
        raise ValueError("Expected exactly 32 intact world/query/side rows")
    bound = cap * axis_norm
    if not math.isfinite(bound):
        raise ValueError("Nonfinite geometric bound")
    details = []
    for key, row in sorted(indexed.items()):
        target = row["target_label"]
        if type(target) is not int or target not in (0, 1) or target != row["original_label"]:
            raise ValueError("Intact target must equal the binary original label")
        sign = 2 * target - 1
        base_gap = _gap(row["base_dual_readout"][FP32])
        observed_gap = _gap(row["dual_readout"][FP32])
        native_base_gap = _gap(row["base_dual_readout"][NATIVE])
        native_gap = _gap(row["dual_readout"][NATIVE])
        delta_l2 = _finite(row["delta_l2"], "delta L2")
        native_delta_l2 = _finite(row["native_applied_delta_l2"], "native applied delta L2")
        if min(delta_l2, native_delta_l2) < 0 or delta_l2 > cap + arithmetic_guard:
            raise ValueError("Residual norm is negative or exceeds the recorded cap plus guard")
        signed_base = sign * base_gap
        upper = signed_base + bound
        observed_correct = sign * observed_gap > 0
        conditional_impossible = upper < -arithmetic_guard
        details.append(
            {
                "world_index": key[0],
                "query_index": key[1],
                "side": key[2],
                "target_label": target,
                "fp32_base_gap": base_gap,
                "fp32_target_signed_base_gap": signed_base,
                "real_arithmetic_gap_shift_absolute_bound": bound,
                "real_arithmetic_target_margin_upper_bound": upper,
                "conditionally_impossible_with_diagnostic_guard": conditional_impossible,
                "cap_to_reach_zero_margin_necessary_lower_bound": max(
                    0.0, -signed_base / axis_norm
                ),
                "fp32_observed_gap": observed_gap,
                "fp32_observed_gap_shift": observed_gap - base_gap,
                "fp32_observed_shift_exceeds_bound_plus_guard": abs(observed_gap - base_gap)
                > bound + arithmetic_guard,
                "fp32_observed_correct": observed_correct,
                "fp32_observed_tie": observed_gap == 0,
                "delta_l2": delta_l2,
                "native_observation_only": {
                    "base_gap": native_base_gap,
                    "gap": native_gap,
                    "correct": sign * native_gap > 0,
                    "tie": native_gap == 0,
                    "applied_delta_l2": native_delta_l2,
                    "geometric_bound_applied": False,
                },
            }
        )
    impossible = [row for row in details if row["conditionally_impossible_with_diagnostic_guard"]]
    errors = [row for row in details if not row["fp32_observed_correct"]]
    return {
        "intact_row_count": len(details),
        "axis_norm_fp64": axis_norm,
        "cap": cap,
        "arithmetic_guard": arithmetic_guard,
        "real_arithmetic_gap_shift_absolute_bound": bound,
        "conditionally_impossible_count": len(impossible),
        "conditional_fp32_geometric_correct_count_ceiling": len(details) - len(impossible),
        "fp32_observed_correct_count": len(details) - len(errors),
        "fp32_observed_error_count_including_ties": len(errors),
        "fp32_observed_tie_count": sum(row["fp32_observed_tie"] for row in details),
        "all_observed_errors_in_conditionally_impossible_rows": all(
            row["conditionally_impossible_with_diagnostic_guard"] for row in errors
        ),
        "conditionally_impossible_but_observed_correct_count": sum(
            row["fp32_observed_correct"] for row in impossible
        ),
        "fp32_shift_exceeds_bound_plus_guard_count": sum(
            row["fp32_observed_shift_exceeds_bound_plus_guard"] for row in details
        ),
        "max_cap_to_reach_zero_margin_necessary_lower_bound": max(
            row["cap_to_reach_zero_margin_necessary_lower_bound"] for row in details
        ),
        "native_observed_correct_count": sum(
            row["native_observation_only"]["correct"] for row in details
        ),
        "native_bound_claim": False,
        "rows": details,
    }


def require_cpu_only():
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "":
        raise RuntimeError("Run with CUDA_VISIBLE_DEVICES='' explicitly; this audit is CPU-only")
    if torch.cuda.is_initialized():
        raise RuntimeError("CUDA was initialized; refuse CPU-only audit")


def read_head_rows(snapshot):
    """Read only two BF16 head rows from a pinned local safetensors snapshot."""
    require_cpu_only()
    from safetensors import safe_open

    snapshot = Path(snapshot)
    if snapshot.name != REVISION or not snapshot.is_dir():
        raise ValueError("Local snapshot directory must identify the pinned revision")
    index_path = snapshot / "model.safetensors.index.json"
    index = json.loads(index_path.read_text())
    shard_name = index["weight_map"]["lm_head.weight"]
    if not isinstance(shard_name, str) or Path(shard_name).name != shard_name:
        raise ValueError("Head shard must be a local snapshot filename")
    rows = []
    with safe_open(snapshot / shard_name, framework="pt", device="cpu") as handle:
        tensor = handle.get_slice("lm_head.weight")
        shape = tuple(tensor.get_shape())
        if shape != (32768, 4096):
            raise ValueError("Pinned Mistral head shape mismatch")
        for token in CANDIDATE_IDS:
            rows.append(tensor[token : token + 1].contiguous())
    weight = torch.cat(rows)
    if weight.dtype != torch.bfloat16 or weight.device.type != "cpu":
        raise ValueError("Pinned head rows must be CPU BF16")
    if not bool(torch.isfinite(weight).all()):
        raise ValueError("Nonfinite head rows")
    axis = weight[1].double() - weight[0].double()
    norm = float(axis.norm())
    return norm, {
        "snapshot_revision": snapshot.name,
        "head_key": "lm_head.weight",
        "head_shape": list(shape),
        "selected_shape": list(weight.shape),
        "selected_ids_no_yes": list(CANDIDATE_IDS),
        "storage_dtype": str(weight.dtype),
        "computation_dtype": "torch.float64",
        "head_shard_filename": shard_name,
        "safetensors_index_sha256": sha256(index_path),
        "selected_head_rows_byte_sha256": hashlib.sha256(
            weight.view(torch.uint8).numpy().tobytes()
        ).hexdigest(),
        "per_row_byte_sha256": [
            hashlib.sha256(row.view(torch.uint8).numpy().tobytes()).hexdigest() for row in rows
        ],
        "head_row_byte_order": "no row then yes row, native BF16 storage bytes",
        "full_model_rehashed": False,
    }


def execute(raw, model_snapshot, output):
    require_cpu_only()
    raw, output = Path(raw), Path(output)
    if output.exists():
        raise FileExistsError(output)
    names = [
        "REPORT.json",
        "STARTED.json",
        "FEATURES.json",
        "final_256_evaluation.json",
        "mean_span_256_evaluation.json",
    ]
    hashes = {name: sha256(raw / name) for name in names}
    values = {name: json.loads((raw / name).read_text()) for name in names}
    report, started, features = (values[name] for name in names[:3])
    if (
        report["status"] != "COMPLETED_TINY_TRAIN_ONLY"
        or report["base_state_sha256_before"] != BASE_HASH
        or report["base_state_sha256_after"] != BASE_HASH
        or report["base_unchanged"] is not True
        or report["source_unchanged"] is not True
        or report["semantic_promotion"] is not False
        or report["winner"] != "none"
    ):
        raise ValueError("Raw completion/base identity/claim receipt mismatch")
    if (
        started["source_hashes"].get(PARENT_PLAN) != PARENT_PLAN_HASH
        or started["plan"]["parent_plan"] != PARENT_PLAN
        or features["candidate_ids"] != list(CANDIDATE_IDS)
    ):
        raise ValueError("Pinned parent-plan or candidate identity mismatch")
    script_hash = sha256(__file__)
    axis_norm, head_identity = read_head_rows(model_snapshot)
    modes = {}
    for mode in ("final", "mean_span"):
        evaluation = values[f"{mode}_256_evaluation.json"]
        if (
            evaluation["gates"]["tiny_feasibility"] is not False
            or evaluation["semantic_promotion"] is not False
            or evaluation["winner"] != "none"
            or any(row["reader_mode"] != mode for row in evaluation["rows"])
        ):
            raise ValueError("Original mode/failed gate/claim receipt mismatch")
        modes[mode] = analyze_rows(evaluation["rows"], axis_norm=axis_norm)
        modes[mode]["original_tiny_feasibility_gate"] = False
    result = {
        "format": "ft-beta-posthoc-readout-cap-audit-v1",
        "status": "POSTHOC_DIAGNOSTIC_NOT_GATE_RELAXATION",
        "model_id": "mistralai/Mistral-7B-Instruct-v0.3",
        "model_revision": REVISION,
        "head_identity": head_identity,
        "raw_run_base_hash_matches_expected": True,
        "raw_run_base_state_sha256": BASE_HASH,
        "parent_plan_sha256": PARENT_PLAN_HASH,
        "raw_receipt_sha256": hashes,
        "source_script_sha256": script_hash,
        "torch_version": str(torch.__version__),
        "cuda_initialized": False,
        "cuda_visible_devices": os.environ["CUDA_VISIBLE_DEVICES"],
        "modes": modes,
        "formula": "a=w_yes-w_no; |a dot delta| <= ||a||_2 ||delta||_2 <= cap*||a||_2; "
        "target_margin_upper=(2*y-1)*base_gap+cap*||a||_2",
        "claim_boundary": [
            "Conditional real-arithmetic linear-readout bound using measured FP32 base gaps.",
            "The 1e-4 arithmetic guard is diagnostic, not a rigorous floating-point error bound.",
            "A cap-to-zero lower bound is necessary, not sufficient; strict correctness requires "
            "positive margin, and the bridge cannot necessarily attain every norm-bounded vector.",
            "The lower bound is not a recommended cap, tuning instruction, or new success gate.",
            "Native BF16 composition/rounding changes the mapping; no native bound is claimed.",
            "Only local head rows are read; existing raw run reports a pinned unchanged base. "
            "This script does not independently rehash the full model.",
            "Two exposed training worlds, two modes, one seed; no heldout non-regression claim.",
            "Original tiny-feasibility failure, winner none, and semantic promotion false remain.",
        ],
        "winner": "none",
        "semantic_promotion": False,
        "training_or_generation_performed": False,
    }
    require_cpu_only()
    if hashes != {name: sha256(raw / name) for name in names} or script_hash != sha256(__file__):
        raise RuntimeError("Raw receipts or audit source changed while auditing")
    with output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--model-snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = execute(args.raw, args.model_snapshot, args.output)
    print(
        json.dumps(
            {
                "status": result["status"],
                "cuda_initialized": result["cuda_initialized"],
                "output": str(args.output),
            }
        )
    )
