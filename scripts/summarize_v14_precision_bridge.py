#!/usr/bin/env python3
"""Recompute compact pilot results and explicitly post-hoc reversal diagnostics."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BUNDLE = REPO / "provenance/pilots/v14_precision_bridge_20261009"


def summarize(bundle=BUNDLE):
    raw = bundle / "raw"
    report = json.loads((raw / "report.json").read_text())
    result = {
        "format": "latent-workspace-v14-precision-bridge-summary-v1",
        "status": report["status"],
        "winner": "none",
        "semantic_promotion": False,
        "elapsed_seconds": report["elapsed_seconds"],
        "peak_cuda_bytes": report["peak_cuda_bytes"],
        "split_audit": report["split_audit"],
        "step0": report["step0_summary"],
        "single": report["single_summary"],
        "multiturn": {
            key: {k: v for k, v in value.items() if k != "pairs"}
            for key, value in report["multiturn_summary"]["intact_twin_pairs"].items()
        },
        "new_weight_bytes": sum(
            s["bytes"] for cell in report["training"].values() for s in cell["checkpoints"]
        ),
        "posthoc_reversal_diagnostic": {},
        "posthoc_claim": (
            "Output-level query-insensitive bias; internal cause not localized. No tuning or rerun."
        ),
    }
    for cell in ("task", "semantic"):
        rows = json.loads((raw / f"single_{cell}.json").read_text())["rows"]
        index = {(r["world_index"], r["side"], r["query_index"], r["control"]): r for r in rows}
        world_effects = []
        reversal_difference, antisymmetry_error, spreads = [], [], []
        for world in range(64):

            def gap(query, control):
                return index[(world, 0, query, control)]["dual_readout"]["fp32_choice_head"][
                    "yes_minus_no"
                ]

            effects = [gap(q, "twin") - gap(q, "intact") for q in range(8)]
            world_effects.append({"world_index": world, "effects_by_query": effects})
            reversal_difference.append(abs(effects[0] - effects[1]))
            antisymmetry_error.append(abs(effects[0] + effects[1]))
            spreads.append(max(effects) - min(effects))
        absolutes = [abs(x["effects_by_query"][0]) for x in world_effects]
        largest = max(range(64), key=lambda i: absolutes[i])
        result["posthoc_reversal_diagnostic"][cell] = {
            "world_count": 64,
            "reverse_query_same_sign_worlds": sum(
                w["effects_by_query"][0] * w["effects_by_query"][1] > 0 for w in world_effects
            ),
            "mean_reverse_difference": statistics.mean(reversal_difference),
            "max_reverse_difference": max(reversal_difference),
            "mean_antisymmetry_error": statistics.mean(antisymmetry_error),
            "mean_eight_query_effect_range": statistics.mean(spreads),
            "max_eight_query_effect_range": max(spreads),
            "median_absolute_q0_effect": statistics.median(absolutes),
            "maximum_absolute_q0_effect": max(absolutes),
            "largest_absolute_effect_world": largest,
            "largest_world_share_absolute_effect": max(absolutes) / sum(absolutes)
            if sum(absolutes)
            else None,
            "world_effects": world_effects,
        }
    return result


if __name__ == "__main__":
    destination = BUNDLE / "SUMMARY.json"
    with destination.open("x") as handle:
        json.dump(summarize(), handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    print(destination)
