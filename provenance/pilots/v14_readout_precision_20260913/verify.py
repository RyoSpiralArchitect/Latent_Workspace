#!/usr/bin/env python3
"""Verify the V14 dual-head readout-precision evidence bundle."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

BUNDLE = Path(__file__).resolve().parent
REPO = BUNDLE.parents[2]
MODELS = {"task", "semantic"}
CONTROLS = {"learned_pair", "gram_matched_random", "unrelated_family", "sham"}
HORIZONS = {0, 1, 2, 3, 4}
LANES = {
    "full_route",
    "answer_boundary_only",
    "non_boundary_only",
    "current_query_only",
    "prior_history_only",
    "oracle_global_answer_axis",
    "oracle_answer_orthogonal",
}
READOUTS = ("native_bf16_head", "fp32_choice_head")


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def close(observed: float, expected: float) -> bool:
    return math.isclose(float(observed), float(expected), rel_tol=0.0, abs_tol=1e-15)


def describe(values: list[float]) -> dict[str, Any]:
    if not values or not all(math.isfinite(value) for value in values):
        raise ValueError("Cannot summarize empty or nonfinite values")
    return {
        "mean": sum(values) / len(values),
        "positive_zero_negative": [
            sum(value > 0 for value in values),
            sum(value == 0 for value in values),
            sum(value < 0 for value in values),
        ],
        "minimum": min(values),
        "maximum": max(values),
    }


def selected_rows(
    rows: list[dict[str, Any]],
    *,
    model: str,
    control: str = "learned_pair",
    affected: bool,
    horizon: int,
) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row["model"] == model
        and row["control"] == control
        and row["affected"] is affected
        and row["horizon"] == horizon
    ]


def lane_stats(rows: list[dict[str, Any]], lane: str, readout: str) -> dict[str, Any]:
    return describe([float(row["lanes"][lane][readout]["signed_pair_effect"]) for row in rows])


def verify_focus(report: dict[str, Any], summary: dict[str, Any]) -> dict[str, bool]:
    focus = selected_rows(report["rows"], model="semantic", affected=True, horizon=4)
    target = summary["measurement_1_predeclared_semantic_affected_horizon_4"]["learned_pair"]
    checks: dict[str, bool] = {"focus_has_four_rows": len(focus) == 4}
    for lane in ("full_route", "answer_boundary_only", "non_boundary_only"):
        for readout, prefix in (
            ("native_bf16_head", "native"),
            ("fp32_choice_head", "fp32"),
        ):
            observed = lane_stats(focus, lane, readout)
            expected = target[lane]
            checks[f"focus_{lane}_{prefix}"] = close(
                observed["mean"], expected[f"{prefix}_mean_signed_pair_effect"]
            ) and (
                observed["positive_zero_negative"] == expected[f"{prefix}_positive_zero_negative"]
            )
    for readout, prefix in (
        ("native_bf16_head", "native"),
        ("fp32_choice_head", "fp32"),
    ):
        observed = describe(
            [float(row["interactions"][readout]["boundary_non_boundary"]) for row in focus]
        )
        expected = target["boundary_non_boundary_interaction"]
        checks[f"focus_interaction_{prefix}"] = (
            close(observed["mean"], expected[f"{prefix}_mean"])
            and observed["positive_zero_negative"] == expected[f"{prefix}_positive_zero_negative"]
            and close(observed["minimum"], expected[f"{prefix}_minimum"])
            and close(observed["maximum"], expected[f"{prefix}_maximum"])
        )
    prediction_changes = sum(
        row["lanes"][lane][readout]["prediction_changed"]
        for row in focus
        for lane in LANES
        for readout in READOUTS
    )
    precision_disagreements = sum(
        row["lanes"][lane][member]["native_bf16_head"]["prediction"]
        != row["lanes"][lane][member]["fp32_choice_head"]["prediction"]
        for row in focus
        for lane in LANES
        for member in ("intact", "twin")
    )
    checks["focus_prediction_changes"] = (
        prediction_changes
        == target["intact_twin_prediction_changes_in_every_position_lane_and_both_heads"]
    )
    checks["focus_precision_prediction_disagreements"] = (
        precision_disagreements
        == target["native_fp32_prediction_disagreements_in_every_position_lane_and_member"]
    )
    return checks


def verify_controls(report: dict[str, Any], summary: dict[str, Any]) -> dict[str, bool]:
    target = summary["measurement_3_controls_and_specificity"]
    affected_target = target["semantic_affected_horizon_4_fp32"]
    checks: dict[str, bool] = {}
    for control, prefix in (
        ("learned_pair", "learned"),
        ("gram_matched_random", "gram_matched_random"),
        ("unrelated_family", "unrelated_family"),
        ("sham", "sham"),
    ):
        chosen = selected_rows(
            report["rows"],
            model="semantic",
            control=control,
            affected=True,
            horizon=4,
        )
        checks[f"control_{control}_full"] = close(
            lane_stats(chosen, "full_route", "fp32_choice_head")["mean"],
            affected_target[f"{prefix}_full_route_mean"],
        )
        checks[f"control_{control}_boundary"] = close(
            lane_stats(chosen, "answer_boundary_only", "fp32_choice_head")["mean"],
            affected_target[f"{prefix}_answer_boundary_mean"],
        )
    unaffected = selected_rows(report["rows"], model="semantic", affected=False, horizon=4)
    for lane, expected in target["semantic_unaffected_horizon_4_fp32_mean_absolute"].items():
        values = [
            float(row["lanes"][lane]["fp32_choice_head"]["signed_pair_effect"])
            for row in unaffected
        ]
        checks[f"unaffected_{lane}"] = close(
            sum(abs(value) for value in values) / len(values), expected
        )
    return checks


def main() -> int:
    index = load(BUNDLE / "ARTIFACT_INDEX.json")
    artifact_checks: dict[str, bool] = {}
    for artifact in index["artifacts"]:
        path = (REPO / artifact["path"]).resolve()
        path.relative_to(REPO)
        artifact_checks[artifact["path"]] = (
            path.is_file()
            and not path.is_symlink()
            and path.stat().st_size == artifact["bytes"]
            and digest(path) == artifact["sha256"]
        )

    report = load(BUNDLE / "raw/report.json")
    summary = load(BUNDLE / "SUMMARY.json")
    rows = report["rows"]
    dimensional_cells = {
        (row["model"], row["case_id"], row["control"], row["horizon"]) for row in rows
    }
    checks = {
        "all_indexed_artifacts_match": all(artifact_checks.values()),
        "qualified_raw_execution": (
            report.get("status") == "QUALIFIED_EXECUTION"
            and report.get("mechanical_execution_qualified") is True
        ),
        "raw_row_closure": len(rows) == 320 and len(dimensional_cells) == 320,
        "dimension_contract": (
            {row["model"] for row in rows} == MODELS
            and {row["control"] for row in rows} == CONTROLS
            and {row["horizon"] for row in rows} == HORIZONS
            and all(set(row["lanes"]) == LANES for row in rows)
        ),
        "same_hidden_and_dtype_contract": all(
            row["base"]["same_normalized_hidden_for_both_heads"]
            and row["base"]["native_logits_dtype"] == "torch.bfloat16"
            and row["base"]["fp32_choice_dtype"] == "torch.float32"
            and all(
                row["lanes"][lane][member]["same_normalized_hidden_for_both_heads"]
                and row["lanes"][lane][member]["native_logits_dtype"] == "torch.bfloat16"
                and row["lanes"][lane][member]["fp32_choice_dtype"] == "torch.float32"
                for lane in LANES
                for member in ("intact", "twin")
            )
            for row in rows
        ),
        "native_predecessor_replication_exact": all(
            row["predecessor_replication"]["base_native_readout_exact"]
            and all(all(row["predecessor_replication"]["lanes"][lane].values()) for lane in LANES)
            for row in rows
        ),
        "raw_integrity_held": all(
            all(identity["integrity"].values()) for identity in report["model_identities"].values()
        ),
        "all_mechanical_checks_true": all(
            all(model_checks.values())
            for model_checks in report["model_mechanical_checks"].values()
        ),
        "summary_execution_matches": (
            summary["execution"]["rows"] == len(rows)
            and close(summary["execution"]["elapsed_seconds"], report["elapsed_seconds"])
            and summary["execution"]["cuda_peak_allocated_bytes"]
            == report["cuda_peak_allocated_bytes"]
            and summary["integrity"]["raw_report_sha256"] == digest(BUNDLE / "raw/report.json")
            and summary["integrity"]["plan_sha256"]
            == digest(REPO / "configs/v14/READOUT_PRECISION_PLAN.json")
        ),
        "precision_localization_preserves_no_winner": (
            report.get("winner") == "none"
            and report.get("semantic_effect_qualified") is False
            and summary.get("winner") == "none"
            and summary.get("semantic_effect_qualified") is False
        ),
        **verify_focus(report, summary),
        **verify_controls(report, summary),
    }
    result = {
        "format": "latent-workspace-v14-readout-precision-bundle-verification-v1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "artifact_checks": artifact_checks,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
