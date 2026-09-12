#!/usr/bin/env python3
"""Verify the V14 position-composition evidence bundle."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

BUNDLE = Path(__file__).resolve().parent
REPO = BUNDLE.parents[2]
MODELS = ("task", "semantic")
CONTROLS = ("learned_pair", "gram_matched_random", "unrelated_family", "sham")
HORIZONS = (0, 1, 2, 3, 4)
LANES = (
    "full_route",
    "answer_boundary_only",
    "non_boundary_only",
    "current_query_only",
    "prior_history_only",
    "oracle_global_answer_axis",
    "oracle_answer_orthogonal",
)


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
        "count": len(values),
        "mean": sum(values) / len(values),
        "mean_absolute": sum(abs(value) for value in values) / len(values),
        "positive": sum(value > 0.0 for value in values),
        "zero": sum(value == 0.0 for value in values),
        "negative": sum(value < 0.0 for value in values),
        "minimum": min(values),
        "maximum": max(values),
    }


def selected_rows(
    rows: list[dict[str, Any]],
    *,
    model: str,
    control: str = "learned_pair",
    horizon: int,
    affected: bool,
) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row["model"] == model
        and row["control"] == control
        and row["horizon"] == horizon
        and row["affected"] is affected
    ]


def lane_stats(rows: list[dict[str, Any]], lane: str) -> dict[str, Any]:
    return describe([float(row["lanes"][lane]["signed_pair_effect"]) for row in rows])


def signs(value: dict[str, Any]) -> list[int]:
    return [int(value["positive"]), int(value["zero"]), int(value["negative"])]


def verify_primary(report: dict[str, Any], summary: dict[str, Any]) -> dict[str, bool]:
    rows = report["rows"]
    focus = selected_rows(rows, model="semantic", horizon=4, affected=True)
    target = summary["measurement_1_predeclared_semantic_affected_horizon_4"]["learned_pair"]
    checks: dict[str, bool] = {"focus_has_four_rows": len(focus) == 4}
    mapping = {
        "full_route": "full_route",
        "answer_boundary_only": "answer_boundary_only",
        "non_boundary_only": "non_boundary_only",
        "current_query_only": "current_query_only",
        "prior_history_only": "prior_history_only",
    }
    for name, lane in mapping.items():
        observed = lane_stats(focus, lane)
        expected = target[name]
        checks[f"focus_{name}"] = (
            close(observed["mean"], expected["mean_signed_pair_effect"])
            and signs(observed) == expected["positive_zero_negative"]
        )
    changes = sum(
        row["lanes"][lane]["intact"]["readout"]["prediction"]
        != row["lanes"][lane]["twin"]["readout"]["prediction"]
        for row in focus
        for lane in LANES
    )
    checks["focus_no_prediction_changes"] = (
        changes == target["intact_twin_prediction_changes_in_every_lane"]
    )

    interaction = describe(
        [float(row["composition"]["boundary_non_boundary_observed_interaction"]) for row in focus]
    )
    interaction_target = summary["measurement_2_composition_interaction"][
        "semantic_affected_horizon_4"
    ]
    checks["focus_nonadditive_interaction"] = (
        close(
            interaction["mean"],
            interaction_target["boundary_non_boundary_observed_interaction_mean"],
        )
        and signs(interaction)
        == interaction_target["boundary_non_boundary_observed_interaction_positive_zero_negative"]
        and close(
            interaction["minimum"],
            interaction_target["boundary_non_boundary_observed_interaction_minimum"],
        )
        and close(
            interaction["maximum"],
            interaction_target["boundary_non_boundary_observed_interaction_maximum"],
        )
    )
    reversal_count = sum(
        bool(row["composition"]["positive_boundary_to_negative_full_reversal"]) for row in focus
    )
    checks["focus_reversal_count"] = (
        reversal_count == interaction_target["positive_boundary_to_negative_full_reversal_cases"]
    )
    checks["focus_linear_partition_exact"] = all(
        close(
            row["composition"]["boundary_non_boundary_local_linear_reconstruction_error"],
            0.0,
        )
        and close(
            row["composition"]["current_history_local_linear_reconstruction_error"],
            0.0,
        )
        for row in focus
    )
    return checks


def verify_oracle(report: dict[str, Any], summary: dict[str, Any]) -> dict[str, bool]:
    focus = selected_rows(report["rows"], model="semantic", horizon=4, affected=True)
    target = summary["measurement_3_local_answer_axis_oracle"]["semantic_affected_horizon_4"]
    observed = lane_stats(focus, "oracle_global_answer_axis")

    def linear_mean(lane: str) -> float:
        return sum(
            float(row["lanes"][lane]["local_linear_pair_prediction"]) for row in focus
        ) / len(focus)

    return {
        "oracle_is_ineligible": (
            summary["measurement_3_local_answer_axis_oracle"][
                "oracle_is_label_aware_and_architecture_selection_ineligible"
            ]
            is True
            and report["oracle_lanes_architecture_selection_eligible"] is False
        ),
        "oracle_endpoint_observed": (
            close(observed["mean"], target["oracle_axis_observed_mean_signed_pair_effect"])
            and signs(observed) == target["oracle_axis_observed_positive_zero_negative"]
        ),
        "oracle_endpoint_linear": (
            close(
                linear_mean("full_route"),
                target["full_route_local_linear_pair_prediction_mean"],
            )
            and close(
                linear_mean("answer_boundary_only"),
                target["answer_boundary_local_linear_pair_prediction_mean"],
            )
            and close(
                linear_mean("non_boundary_only"),
                target["non_boundary_local_linear_pair_prediction_mean"],
            )
            and close(
                linear_mean("oracle_global_answer_axis"),
                target["oracle_axis_local_linear_pair_prediction_mean"],
            )
        ),
    }


def verify_controls(report: dict[str, Any], summary: dict[str, Any]) -> dict[str, bool]:
    rows = report["rows"]
    target = summary["measurement_4_specificity_and_stability"]
    endpoint_target = target["semantic_affected_horizon_4_answer_boundary_only"]
    checks: dict[str, bool] = {}
    for control, name in (
        ("learned_pair", "learned_pair_mean"),
        ("gram_matched_random", "gram_matched_random_mean"),
        ("unrelated_family", "unrelated_family_mean"),
        ("sham", "sham_mean"),
    ):
        chosen = selected_rows(
            rows,
            model="semantic",
            control=control,
            horizon=4,
            affected=True,
        )
        checks[f"endpoint_{control}"] = close(
            lane_stats(chosen, "answer_boundary_only")["mean"], endpoint_target[name]
        )
    unaffected = selected_rows(rows, model="semantic", horizon=4, affected=False)
    stability_target = target["semantic_unaffected_horizon_4"]
    for lane in ("full_route", "answer_boundary_only", "non_boundary_only", "current_query_only"):
        observed = lane_stats(unaffected, lane)
        checks[f"unaffected_{lane}"] = close(
            observed["mean"], stability_target[f"{lane}_mean"]
        ) and close(observed["mean_absolute"], stability_target[f"{lane}_mean_absolute"])
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
    rows = report.get("rows", [])
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
            {row["model"] for row in rows} == set(MODELS)
            and {row["control"] for row in rows} == set(CONTROLS)
            and {row["horizon"] for row in rows} == set(HORIZONS)
            and all(set(row["lanes"]) == set(LANES) for row in rows)
        ),
        "raw_integrity_held": all(
            all(identity["integrity"].values()) for identity in report["model_identities"].values()
        ),
        "all_mechanical_checks_true": all(
            all(model_checks.values())
            for model_checks in report["model_mechanical_checks"].values()
        ),
        "no_winner_preserved": (
            report.get("winner") == "none"
            and report.get("semantic_effect_qualified") is False
            and summary.get("winner") == "none"
            and summary.get("semantic_effect_qualified") is False
        ),
        "summary_execution_matches": (
            summary["execution"]["rows"] == len(rows)
            and close(summary["execution"]["elapsed_seconds"], report["elapsed_seconds"])
            and summary["execution"]["cuda_peak_allocated_bytes"]
            == report["cuda_peak_allocated_bytes"]
            and summary["integrity"]["raw_report_sha256"] == digest(BUNDLE / "raw/report.json")
        ),
        "predecessor_replication_exact": all(
            row["predecessor_replication"]["answer_boundary_effect_exact"]
            and row["predecessor_replication"]["full_route_effect_exact"]
            and row["predecessor_replication"]["base_readout_exact"]
            for row in rows
            if row["control"] == "learned_pair"
        ),
        "native_partitions_exact": all(
            row["member_mechanics"][member]["full_equals_boundary_plus_non_boundary_native_exact"]
            and row["member_mechanics"][member]["full_equals_current_plus_history_native_exact"]
            for row in rows
            for member in ("intact", "twin")
        ),
        **verify_primary(report, summary),
        **verify_oracle(report, summary),
        **verify_controls(report, summary),
    }
    result = {
        "format": "latent-workspace-v14-position-composition-bundle-verification-v1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "artifact_checks": artifact_checks,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
