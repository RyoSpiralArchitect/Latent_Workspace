#!/usr/bin/env python3
"""Derive the MI/repair publication summary from saved JSON, without model execution."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from run_v14_boundary_training import atomic_write, digest

REPO = Path(__file__).resolve().parents[1]
BUNDLE = REPO / "provenance/pilots/v14_mech_repair_20261009"
READOUTS = ("native_bf16_head", "fp32_choice_head")
FAMILIES = ("legacy", "centered")
CELLS = ("task", "semantic")
NAMES = tuple(f"{family}_{cell}" for family in FAMILIES for cell in CELLS)


def describe(values: list[float]) -> dict[str, Any]:
    if not values or not all(math.isfinite(value) for value in values):
        raise ValueError("Expected a nonempty finite sequence")
    return {
        "count": len(values),
        "mean": statistics.mean(values),
        "mean_absolute": statistics.mean(abs(value) for value in values),
        "median": statistics.median(values),
        "minimum": min(values),
        "maximum": max(values),
        "positive": sum(value > 0 for value in values),
        "negative": sum(value < 0 for value in values),
        "zero": sum(value == 0 for value in values),
    }


def _single_index(rows):
    index = {
        (row["world_index"], row["side"], row["query_index"], row["control"]): row for row in rows
    }
    if len(index) != len(rows) or len(rows) != 6144:
        raise ValueError("Single-turn row inventory changed")
    return index


def reversal_diagnostic(rows, readout):
    index = _single_index(rows)
    worlds = sorted({row["world_index"] for row in rows})
    if worlds != list(range(64)):
        raise ValueError("Post-hoc reversal world inventory changed")
    effects, donor_effects, spreads = [], [], []
    for world in worlds:
        per_query, signed = [], []
        for query in range(8):
            original = index[(world, 0, query, "intact")]
            twin = index[(world, 0, query, "twin")]
            difference = (
                twin["dual_readout"][readout]["yes_minus_no"]
                - original["dual_readout"][readout]["yes_minus_no"]
            )
            per_query.append(difference)
            signed.append((2 * original["donor_label"] - 1) * difference)
        effects.append(per_query[:2])
        donor_effects.append(signed[:2])
        spreads.append(max(per_query) - min(per_query))
    return {
        "posthoc": True,
        "side": 0,
        "query_indices": [0, 1],
        "world_count": len(worlds),
        "same_nonzero_sign_worlds": sum(first * second > 0 for first, second in effects),
        "opposite_nonzero_sign_worlds": sum(first * second < 0 for first, second in effects),
        "one_or_more_zero_effect_worlds": sum(
            first == 0 or second == 0 for first, second in effects
        ),
        "both_donor_directed_positive_worlds": sum(
            first > 0 and second > 0 for first, second in donor_effects
        ),
        "both_donor_directed_negative_worlds": sum(
            first < 0 and second < 0 for first, second in donor_effects
        ),
        "q0_twin_minus_intact_gap": describe([pair[0] for pair in effects]),
        "q1_twin_minus_intact_gap": describe([pair[1] for pair in effects]),
        "reverse_gap_effect_difference": describe([second - first for first, second in effects]),
        "antisymmetry_sum": describe([first + second for first, second in effects]),
        "eight_query_effect_range": describe(spreads),
    }


def control_effects(rows, readout):
    result = {}
    for control in sorted({row["control"] for row in rows}):
        selected = [row for row in rows if row["control"] == control and row["side"] == 0]
        if len(selected) != 512:
            raise ValueError("Control side0 denominator changed")
        effects = [
            row["dual_readout"][readout]["yes_minus_no"]
            - row["base_dual_readout"][readout]["yes_minus_no"]
            for row in selected
        ]
        result[control] = {
            "side": 0,
            "row_count": len(selected),
            "gap_change_from_base": describe(effects),
            "residual_l2": describe([row["dual_readout"]["delta_l2"] for row in selected]),
            "greedy_answer_changes_from_base": sum(
                row["dual_readout"][readout]["greedy_choice"]
                != row["base_dual_readout"][readout]["greedy_choice"]
                for row in selected
            ),
        }
    return result


def generation_comparison(legacy_rows, centered_rows):
    def index(rows):
        result = {
            (
                row["condition"],
                row["scenario"],
                row["history_mode"],
                row["selected_readout"],
                row["regime"],
            ): row
            for row in rows
        }
        if len(result) != len(rows) or len(rows) != 896:
            raise ValueError("Multi-turn trajectory inventory changed")
        return result

    legacy, centered = index(legacy_rows), index(centered_rows)
    if legacy.keys() != centered.keys():
        raise ValueError("Legacy/centered matched generation keys differ")
    groups = defaultdict(list)
    by_model = defaultdict(list)
    observations = []
    base_exact = True
    for key, first in legacy.items():
        second = centered[key]
        if first["pair_id"] != second["pair_id"]:
            raise ValueError("Matched generation world identity changed")
        left, right = first["generated_labels"], second["generated_labels"]
        if len(left) != len(right) or len(left) != 4:
            raise ValueError("Matched generation turn count changed")
        item = {
            "identical": left == right,
            "identical_turn_count": sum(a == b for a, b in zip(left, right, strict=True)),
            "appended_history_identical": first["appended_history_labels"]
            == second["appended_history_labels"],
        }
        observations.append(item)
        grouping = "|".join(
            first[field] for field in ("model", "control", "history_mode", "selected_readout")
        )
        groups[grouping].append(item)
        by_model[first["model"]].append(item)
        if first["model"] == "base":
            base_exact &= first == second

    def count(items):
        return {
            "trajectory_pairs": len(items),
            "identical_generated_label_sequences": sum(item["identical"] for item in items),
            "changed_generated_label_sequences": sum(not item["identical"] for item in items),
            "turn_pairs": 4 * len(items),
            "identical_generated_turn_labels": sum(item["identical_turn_count"] for item in items),
            "identical_appended_history_sequences": sum(
                item["appended_history_identical"] for item in items
            ),
        }

    return {
        "comparison": "legacy versus centered; same model/control/scenario/history/head/regime",
        "global": count(observations),
        "by_model": {name: count(items) for name, items in sorted(by_model.items())},
        "by_model_control_history_readout": {
            name: count(items) for name, items in sorted(groups.items())
        },
        "base_raw_trajectories_exact_between_families": base_exact,
    }


def mechanistic_table(mi):
    result = []
    for state, summary in mi["summary"].items():
        rows = [row for row in mi["rows"] if row["state"] == state]
        result.append(
            {
                "state": state,
                "training_world_count": len({row["world_index"] for row in rows}),
                "row_count": len(rows),
                "reverse_stages": summary["reverse_stages"],
                "original_gap_absolute_mean": statistics.mean(
                    abs(row["delta_gap"]) for row in rows
                ),
                "centered_intervention_gap_absolute_mean": statistics.mean(
                    abs(row["delta_gap"] + row["interventions"]["centered_values"]["gap_change"])
                    for row in rows
                ),
                "uniform_intervention_gap_absolute_change_mean": summary["interventions"][
                    "uniform_attention"
                ]["gap_change_abs"]["mean"],
                "normalized_memory_centered_l2_fraction_mean": statistics.mean(
                    row["metrics"]["normalized_memory"]["centered_l2_fraction"] for row in rows
                ),
                "value_centered_l2_fraction_mean": statistics.mean(
                    row["metrics"]["values"]["centered_l2_fraction"] for row in rows
                ),
                "raw_delta_l2_mean": summary["metrics"]["raw_delta_l2_mean"]["mean"],
                "slot_mean_raw_delta_l2_mean": summary["metrics"]["mean_value_raw_delta_l2_mean"][
                    "mean"
                ],
                "centered_value_raw_delta_l2_mean": summary["metrics"][
                    "centered_value_raw_delta_l2_mean"
                ]["mean"],
                "cap_scale_mean": summary["metrics"]["cap_scale_mean"]["mean"],
            }
        )
    return result


def summarize(bundle=BUNDLE):
    bundle = Path(bundle)
    receipts = {}

    def load(relative):
        path = bundle / relative
        receipts[relative] = {"sha256": digest(path), "bytes": path.stat().st_size}
        return json.loads(path.read_text())

    mi = load("mechanistic/report.json")
    report = load("repair/report.json")
    panels = load("repair/reader_panels.json")
    if mi["status"] != "QUALIFIED_EXECUTION" or report["status"] != "QUALIFIED_EXECUTION":
        raise ValueError("Input experiment is not qualified")
    result = {
        "format": "latent-workspace-v14-mech-repair-summary-v1",
        "status": report["status"],
        "winner": "none",
        "semantic_promotion": False,
        "mechanistic_summary": mi["summary"],
        "single_summary": report["single_summary"],
        "multiturn_summary": report["multiturn_summary"],
        "panel_summary": report["panel_summary"],
        "mechanistic_table": mechanistic_table(mi),
        "single_table": [],
        "reader_reverse_measures": {},
        "posthoc_reversal_diagnostic": {},
        "control_effects": {},
        "multiturn_counters": {
            family: {
                key: {field: value for field, value in row.items() if field != "pairs"}
                for key, row in report["multiturn_summary"][family]["intact_twin_pairs"].items()
            }
            for family in FAMILIES
        },
        "elapsed_seconds": {
            "mechanistic": mi["elapsed_seconds"],
            "repair": report["elapsed_seconds"],
        },
        "peak_cuda_bytes": {
            "mechanistic": mi["peak_cuda_bytes"],
            "repair": report["peak_cuda_bytes"],
        },
        "denominators": report["denominators"],
        "split_audit": report["split_audit"],
        "new_weight_bytes": sum(
            save["bytes"] for cell in report["training"].values() for save in cell["checkpoints"]
        ),
        "definitions": {
            "posthoc_reversal": "side0 twin-minus-intact gaps; q0 and q1 are reversed questions",
            "single_control_effects": "side0 only; 64 worlds times8 queries per control",
            "reader_reverse_measures": "first16 training worlds, both sides, four reversal pairs",
            "primary_summaries": "verbatim machine-readable copies; no scientific inference added",
            "generation_comparison": "label sequence equality, not equality of model scores",
        },
    }
    for name in NAMES:
        raw = load(f"repair/single_{name}.json")
        if raw["summary"] != report["single_summary"][name]:
            raise ValueError(f"Single summary mismatch: {name}")
        single_index = _single_index(raw["rows"])
        result["posthoc_reversal_diagnostic"][name] = {}
        result["control_effects"][name] = {}
        for readout in READOUTS:
            summary = report["single_summary"][name][readout]
            flip_coordinates = []
            for row in raw["rows"]:
                if row["side"] != 0 or row["control"] != "intact" or not row["affected"]:
                    continue
                twin = single_index[(row["world_index"], 0, row["query_index"], "twin")]
                if (
                    row["dual_readout"][readout]["greedy_choice"] == row["original_label"]
                    and twin["dual_readout"][readout]["greedy_choice"] == row["donor_label"]
                ):
                    flip_coordinates.append([row["world_index"], row["query_index"]])
            flip_coordinates.sort()
            if len(flip_coordinates) != summary["affected_correct_flip"]["positive"]:
                raise ValueError("Correct-flip coordinates differ from primary summary")
            result["single_table"].append(
                {
                    "condition": name,
                    "readout": readout,
                    "intact_accuracy": summary["intact_accuracy"],
                    "base_query_only_accuracy": summary["base_query_only_accuracy"]["all"],
                    "correct_affected_flips": summary["affected_correct_flip"]["positive"],
                    "correct_flip_coordinates_world_query_side0": flip_coordinates,
                    "affected_pair_count": summary["affected_correct_flip"]["count"],
                    "affected_donor_signed_gap_change": summary["affected_donor_signed_gap_change"],
                    "affected_world_mean_donor_gap_change": summary[
                        "affected_world_mean_donor_gap_change"
                    ],
                    "unaffected_gap_change": summary["unaffected_gap_change"],
                    "unrelated_gap_change_from_base": summary["unrelated_gap_change_from_base"],
                }
            )
            result["posthoc_reversal_diagnostic"][name][readout] = reversal_diagnostic(
                raw["rows"], readout
            )
            result["control_effects"][name][readout] = control_effects(raw["rows"], readout)
        panel = panels[name]
        if panel["summary"] != report["panel_summary"][name]:
            raise ValueError(f"Reader panel summary mismatch: {name}")
        pair_metrics, row_metrics = (
            panel["summary"]["pair_metrics"],
            panel["summary"]["row_metrics"],
        )
        result["reader_reverse_measures"][name] = {
            "protocol": panel["protocol"],
            "pair_count": panel["summary"]["pair_count"],
            "relative_stage_measures": {
                key: value for key, value in pair_metrics.items() if key.endswith("relative_l2")
            },
            "absolute_head_axis_reverse_gap": describe(
                [abs(pair["head_axis_gap_difference"]) for pair in panel["pairs"]]
            ),
            "signed_head_axis_reverse_gap": describe(
                [pair["head_axis_gap_difference"] for pair in panel["pairs"]]
            ),
            "raw_delta_l2": row_metrics["raw_delta_l2"],
            "delta_l2": row_metrics["delta_l2"],
            "head_axis_gap": row_metrics["head_axis_gap"],
            "uniform_delta_l2": row_metrics["uniform_delta_l2"],
            "uniform_head_axis_gap": row_metrics["uniform_head_axis_gap"],
        }
    trajectories = {}
    for family in FAMILIES:
        trajectories[family] = load(f"repair/multiturn_{family}.json")
        if trajectories[family]["summary"] != report["multiturn_summary"][family]:
            raise ValueError(f"Multiturn summary mismatch: {family}")
    result["matched_generation_labels"] = generation_comparison(
        trajectories["legacy"]["rows"], trajectories["centered"]["rows"]
    )
    result["input_artifacts"] = receipts
    # Reject nonfinite nested inputs/derived values before publishing or checking.
    json.dumps(result, allow_nan=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=BUNDLE)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--check", action="store_true", help="Compare saved summary without writing"
    )
    args = parser.parse_args()
    output = args.output or args.bundle / "SUMMARY.json"
    result = summarize(args.bundle)
    if args.check:
        if json.loads(output.read_text()) != result:
            raise ValueError(f"Derived summary differs from {output}")
        print(json.dumps({"status": "PASS", "summary": str(output), "read_only": True}))
    else:
        atomic_write(output, result)
        print(json.dumps({"status": "WRITTEN", "summary": str(output), "sha256": digest(output)}))


if __name__ == "__main__":
    main()
