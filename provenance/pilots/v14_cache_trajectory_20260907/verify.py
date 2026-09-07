#!/usr/bin/env python3
"""Verify the copied V14-T0 evidence without rerunning the target model."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

from run_v14_cache_trajectory_canary import _digest, _source_identity  # noqa: E402
from v14_cache_trajectory_metrics import summarize  # noqa: E402


def main() -> int:
    manifest = json.loads((HERE / "ARTIFACT_INDEX.json").read_text())
    summary = json.loads((HERE / "SUMMARY.json").read_text())
    report = json.loads((HERE / "raw/report.json").read_text())
    plan_path = REPO / "configs/v14/CACHE_TRAJECTORY_PLAN.json"
    plan = json.loads(plan_path.read_text())
    rows = [
        json.loads(line)
        for line in (HERE / "raw/trajectory.jsonl").read_text().splitlines()
        if line.strip()
    ]

    file_checks = {}
    for relative, expected in manifest["files"].items():
        payload = (HERE / relative).read_bytes()
        file_checks[relative] = {
            "bytes": len(payload) == expected["bytes"],
            "sha256": hashlib.sha256(payload).hexdigest() == expected["sha256"],
        }

    recomputed = summarize(
        rows,
        expected_horizons=tuple(plan["trajectory"]["horizons"]),
        endpoint_horizon=plan["metrics"]["endpoint_horizon"],
        frozen_floor=plan["metrics"]["frozen_floor"],
        expected_families=1,
        expected_probes_per_family=1,
        expected_direction_kinds=("equal_norm_random",),
    )

    new_position_l2 = {"B": [], "C": []}
    first_changed_layers: dict[str, dict[str, list[int]]] = {"0": {}, "1": {}}
    for horizon in plan["trajectory"]["horizons"]:
        differences = report["horizon_differences"][str(horizon)]
        for cell in ("B", "C"):
            per_layer = differences[cell]["per_layer"]
            new_position_l2[cell].append(
                math.sqrt(
                    math.fsum(
                        row[field] ** 2
                        for row in per_layer
                        for field in ("key_last_position_l2", "value_last_position_l2")
                    )
                )
            )
            if horizon in (0, 1):
                first_changed_layers[str(horizon)][cell] = [
                    row["layer"]
                    for row in per_layer
                    if row["key_last_position_l2"] > 0.0
                    or row["value_last_position_l2"] > 0.0
                ]

    checks = {
        "manifest_files": all(
            all(values.values()) for values in file_checks.values()
        ),
        "plan_hash": _digest(plan_path) == report["plan_sha256"],
        "source_identity": _source_identity() == report["source_identity"],
        "trajectory_hash_bound_by_report": (
            _digest(HERE / "raw/trajectory.jsonl") == report["trajectory_sha256"]
        ),
        "metrics_exact_recompute": recomputed == report["metrics"],
        "mechanical_gate_passed": (
            report["mechanical_return_gate"]["return_allowed"] is True
            and all(report["structural_checks"].values())
        ),
        "semantic_not_applicable": (
            report["semantic_qualification"]["status"]
            == "NOT_APPLICABLE_NON_SEMANTIC_SCREEN"
        ),
        "summary_positive_new_position_l2": (
            new_position_l2["B"]
            == summary["trajectory"]["positive_new_position_kv_l2_vs_base"]
        ),
        "summary_negative_new_position_l2": (
            new_position_l2["C"]
            == summary["trajectory"]["negative_new_position_kv_l2_vs_base"]
        ),
        "summary_pulse_changed_layers": (
            first_changed_layers["0"]["B"]
            == summary["structural_result"]["pulse_position_changed_layers"]["positive"]
            and first_changed_layers["0"]["C"]
            == summary["structural_result"]["pulse_position_changed_layers"]["negative"]
        ),
        "summary_future_changed_layers": (
            first_changed_layers["1"]["B"]
            == summary["structural_result"]["horizon_1_new_position_changed_layers"][
                "positive"
            ]
            and first_changed_layers["1"]["C"]
            == summary["structural_result"]["horizon_1_new_position_changed_layers"][
                "negative"
            ]
        ),
    }
    result = {
        "status": "VERIFIED" if all(checks.values()) else "FAILED",
        "checks": checks,
        "file_checks": file_checks,
        "target_model_rerun": False,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
