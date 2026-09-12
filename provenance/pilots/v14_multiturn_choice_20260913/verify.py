#!/usr/bin/env python3
"""Verify the V14 constrained multi-turn evidence bundle."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

BUNDLE = Path(__file__).resolve().parent
REPO = BUNDLE.parents[2]
HISTORY_MODES = ("teacher_forced_fixed_history", "free_history")
READOUTS = ("native_bf16_head", "fp32_choice_head")
ROUTES = ("full_route", "answer_boundary_only", "non_boundary_only")
SCENARIOS = ("w0_s0", "w0_s1", "w1_s0", "w1_s1")
REGIMES = ("greedy", "sample_211", "sample_212", "sample_213")


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


def _pair(
    report: dict[str, Any],
    model: str,
    route: str,
    history: str,
    readout: str,
) -> dict[str, Any]:
    return report["summary"]["intact_twin_trajectory_pairs"][f"{model}|{route}|{history}|{readout}"]


def verify_turn_zero(report: dict[str, Any], precision: dict[str, Any]) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    source = precision["summary"]["signed_pair_effects_by_horizon"]
    for model in ("task", "semantic"):
        for route in ROUTES:
            for readout in READOUTS:
                expected = source[model]["learned_pair"]["affected"]["0"][route][readout]["mean"]
                observed = _pair(
                    report,
                    model,
                    route,
                    HISTORY_MODES[0],
                    readout,
                )["signed_pair_effect_by_turn"]["0"]["mean"]
                checks[f"turn0_{model}_{route}_{readout}"] = close(observed, expected)
    return checks


def verify_semantic(report: dict[str, Any], summary: dict[str, Any]) -> dict[str, bool]:
    target = summary["measurement_2_semantic_intact_twin_trajectories"]
    checks: dict[str, bool] = {}
    route_keys = {
        "full_route": "full_route",
        "answer_boundary_only": "answer_boundary_only",
        "non_boundary_only": "non_boundary_only",
    }
    for route, key in route_keys.items():
        for history in HISTORY_MODES:
            history_target = target[key][history]
            for readout, prefix in (
                (READOUTS[0], "native"),
                (READOUTS[1], "fp32"),
            ):
                observed = _pair(report, "semantic", route, history, readout)
                checks[f"semantic_{route}_{history}_{prefix}_count"] = (
                    observed["pair_count"] == target["pair_denominator_per_cell"]
                )
                checks[f"semantic_{route}_{history}_{prefix}_changed"] = (
                    observed["trajectory_changed_pairs"]
                    == history_target[f"{prefix}_changed_pairs"]
                )
            checks[f"semantic_{route}_{history}_affected_unchanged"] = (
                _pair(report, "semantic", route, history, READOUTS[0])["affected_changed_slots"]
                + _pair(report, "semantic", route, history, READOUTS[1])["affected_changed_slots"]
                == history_target["affected_changed_slots_both_heads"]
            )
        expected_effects = target[key]["fixed_history_fp32_signed_pair_effect_by_turn"]
        observed_effects = _pair(
            report,
            "semantic",
            route,
            HISTORY_MODES[0],
            READOUTS[1],
        )["signed_pair_effect_by_turn"]
        checks[f"semantic_{route}_fixed_fp32_effects"] = all(
            close(observed_effects[str(turn)]["mean"], expected)
            for turn, expected in enumerate(expected_effects)
        )

    boundary = target["answer_boundary_only"]["free_history"]
    for readout in READOUTS:
        observed = _pair(
            report,
            "semantic",
            "answer_boundary_only",
            HISTORY_MODES[1],
            readout,
        )
        checks[f"semantic_boundary_free_{readout}_late"] = (
            observed["first_turn_same_then_later_changed_pairs"]
            == boundary["first_turn_same_then_later_changed_pairs_each_head"]
            and observed["unaffected_same_slots"] == boundary["unaffected_same_slots_each_head"]
            and observed["unaffected_slot_count"]
            == boundary["unaffected_slot_denominator_each_head"]
        )
    non_boundary = target["non_boundary_only"]["free_history"]
    observed_non = _pair(
        report,
        "semantic",
        "non_boundary_only",
        HISTORY_MODES[1],
        READOUTS[1],
    )
    checks["semantic_non_boundary_free_fp32_late"] = (
        observed_non["first_turn_same_then_later_changed_pairs"]
        == non_boundary["fp32_first_turn_same_then_later_changed_pairs"]
        and observed_non["unaffected_same_slots"] == non_boundary["fp32_unaffected_same_slots"]
        and observed_non["unaffected_slot_count"]
        == non_boundary["unaffected_slot_denominator_per_head"]
    )
    greedy_pairs = []
    for route in ROUTES:
        stem = {
            "full_route": "full",
            "answer_boundary_only": "boundary",
            "non_boundary_only": "non_boundary",
        }[route]
        for history in HISTORY_MODES:
            for readout in READOUTS:
                for scenario in SCENARIOS:
                    intact = next(
                        row
                        for row in report["rows"]
                        if row["condition"] == f"semantic_{stem}_intact"
                        and row["scenario"] == scenario
                        and row["history_mode"] == history
                        and row["regime"] == "greedy"
                        and row["selected_readout"] == readout
                    )
                    twin = next(
                        row
                        for row in report["rows"]
                        if row["condition"] == f"semantic_{stem}_twin"
                        and row["scenario"] == scenario
                        and row["history_mode"] == history
                        and row["regime"] == "greedy"
                        and row["selected_readout"] == readout
                    )
                    greedy_pairs.append(intact["generated_labels"] == twin["generated_labels"])
    checks["all_semantic_greedy_pairs_identical"] = (
        all(greedy_pairs)
        and target["all_semantic_greedy_intact_twin_trajectories_identical"] is True
    )
    return checks


def verify_delayed_divergence(report: dict[str, Any], summary: dict[str, Any]) -> dict[str, bool]:
    indexed = {
        (
            row["condition"],
            row["scenario"],
            row["history_mode"],
            row["regime"],
            row["selected_readout"],
        ): row
        for row in report["rows"]
    }
    target = summary["measurement_3_delayed_divergence_audit"]
    checks: dict[str, bool] = {}
    for readout in READOUTS:
        intact = indexed[
            (
                "semantic_boundary_intact",
                target["scenario"],
                HISTORY_MODES[1],
                target["regime"],
                readout,
            )
        ]
        twin = indexed[
            (
                "semantic_boundary_twin",
                target["scenario"],
                HISTORY_MODES[1],
                target["regime"],
                readout,
            )
        ]
        expected = target["answer_boundary_both_heads"]
        checks[f"delayed_boundary_{readout}"] = (
            intact["generated_text"] == expected["intact"]
            and twin["generated_text"] == expected["twin"]
            and intact["turns"][1]["affected"] is expected["first_difference_affected"]
            and intact["turns"][1]["prefix_token_sha256"] == twin["turns"][1]["prefix_token_sha256"]
            and intact["turns"][3]["prefix_token_sha256"] != twin["turns"][3]["prefix_token_sha256"]
        )
    intact = indexed[
        (
            "semantic_non_boundary_intact",
            target["scenario"],
            HISTORY_MODES[1],
            target["regime"],
            READOUTS[1],
        )
    ]
    twin = indexed[
        (
            "semantic_non_boundary_twin",
            target["scenario"],
            HISTORY_MODES[1],
            target["regime"],
            READOUTS[1],
        )
    ]
    expected = target["non_boundary_fp32"]
    checks["delayed_non_boundary_fp32"] = (
        intact["generated_text"] == expected["intact"]
        and twin["generated_text"] == expected["twin"]
        and intact["turns"][1]["affected"] is expected["first_difference_affected"]
    )
    return checks


def verify_history_controls(report: dict[str, Any], summary: dict[str, Any]) -> dict[str, bool]:
    source = report["summary"]["fixed_free_history_pairs"]
    target = summary["measurement_4_generic_history_feedback_control"]
    checks = {
        "base_inline_native_history": source[f"base_inline|{READOUTS[0]}"][
            "trajectory_changed_pairs"
        ]
        == target["base_inline_fixed_vs_free_changed_pairs"]["native"],
        "base_inline_fp32_history": source[f"base_inline|{READOUTS[1]}"]["trajectory_changed_pairs"]
        == target["base_inline_fixed_vs_free_changed_pairs"]["fp32"],
        "base_query_native_history": source[f"base_query_only|{READOUTS[0]}"][
            "trajectory_changed_pairs"
        ]
        == target["base_query_only_fixed_vs_free_changed_pairs"]["native"],
        "base_query_fp32_history": source[f"base_query_only|{READOUTS[1]}"][
            "trajectory_changed_pairs"
        ]
        == target["base_query_only_fixed_vs_free_changed_pairs"]["fp32"],
    }
    semantic_counts = [
        value["trajectory_changed_pairs"]
        for key, value in source.items()
        if key.startswith("semantic_")
    ]
    checks["semantic_history_range"] = [min(semantic_counts), max(semantic_counts)] == target[
        "semantic_condition_fixed_vs_free_changed_pair_range"
    ]
    return checks


def target_accuracy(report: dict[str, Any], condition: str, history: str, readout: str) -> float:
    turns = [
        turn
        for row in report["rows"]
        if row["condition"] == condition
        and row["history_mode"] == history
        and row["selected_readout"] == readout
        for turn in row["turns"]
    ]
    return sum(bool(turn["target_correct"]) for turn in turns) / len(turns)


def verify_behavior(report: dict[str, Any], summary: dict[str, Any]) -> dict[str, bool]:
    target = summary["measurement_6_behavior_reference"]["all_regimes_all_turns_target_accuracy"]
    checks: dict[str, bool] = {}
    for history, key in (
        (HISTORY_MODES[0], "teacher_forced_fixed_history_fp32"),
        (HISTORY_MODES[1], "free_history_fp32"),
    ):
        for condition, expected in target[key].items():
            checks[f"accuracy_{key}_{condition}"] = close(
                target_accuracy(report, condition, history, READOUTS[1]), expected
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
    precision = load(REPO / "provenance/pilots/v14_readout_precision_20260913/raw/report.json")
    rows = report["rows"]
    dimensional_cells = {
        (
            row["condition"],
            row["scenario"],
            row["history_mode"],
            row["regime"],
            row["selected_readout"],
        )
        for row in rows
    }
    checks = {
        "all_indexed_artifacts_match": all(artifact_checks.values()),
        "qualified_raw_execution": (
            report.get("status") == "QUALIFIED_EXECUTION"
            and report.get("mechanical_execution_qualified") is True
        ),
        "raw_trajectory_closure": len(rows) == 896 and len(dimensional_cells) == 896,
        "raw_turn_closure": sum(len(row["turns"]) for row in rows) == 3584,
        "dimension_contract": (
            {row["scenario"] for row in rows} == set(SCENARIOS)
            and {row["history_mode"] for row in rows} == set(HISTORY_MODES)
            and {row["regime"] for row in rows} == set(REGIMES)
            and {row["selected_readout"] for row in rows} == set(READOUTS)
        ),
        "raw_integrity_held": all(
            all(identity["integrity"].values()) for identity in report["model_identities"].values()
        ),
        "all_mechanical_checks_true": all(
            all(model_checks.values())
            for model_checks in report["model_mechanical_checks"].values()
        ),
        "summary_execution_matches": (
            summary["execution"]["trajectories"] == report["trajectory_count"]
            and summary["execution"]["turn_rows"] == report["turn_row_count"]
            and close(summary["execution"]["elapsed_seconds"], report["elapsed_seconds"])
            and summary["execution"]["cuda_peak_allocated_bytes"]
            == report["cuda_peak_allocated_bytes"]
            and summary["integrity"]["raw_report_sha256"] == digest(BUNDLE / "raw/report.json")
            and summary["integrity"]["plan_sha256"]
            == digest(REPO / "configs/v14/MULTITURN_CHOICE_PLAN.json")
        ),
        "no_winner_or_promotion": (
            report.get("winner") == "none"
            and report.get("semantic_effect_qualified") is False
            and report.get("semantic_promotion_performed") is False
            and summary.get("winner") == "none"
            and summary.get("semantic_effect_qualified") is False
        ),
        **verify_turn_zero(report, precision),
        **verify_semantic(report, summary),
        **verify_delayed_divergence(report, summary),
        **verify_history_controls(report, summary),
        **verify_behavior(report, summary),
    }
    result = {
        "format": "latent-workspace-v14-multiturn-choice-bundle-verification-v1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "artifact_checks": artifact_checks,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
