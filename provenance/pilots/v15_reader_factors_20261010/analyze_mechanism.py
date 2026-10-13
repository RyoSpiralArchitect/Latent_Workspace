#!/usr/bin/env python3
"""Post-result, offline derived contrasts. No new model calls or success gate."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import summarize_v15_reader_factors as replay  # noqa: E402


def build():
    summary = replay.build(HERE)
    derived = {}
    for arm in replay.ARMS:
        cell = summary["cells"][arm]
        variants = cell["by_variant"]
        blocks = replay.read(HERE / "raw" / f"{arm}_FACTORS.json")["blocks"]
        affected = []
        for b in blocks:
            if not b["binding_label_interpretation"]:
                continue
            # Cauchy-Schwarz bounds the head projection of production-vs-FP64
            # memory-difference errors; I is a quarter of their difference.
            bound = (
                sum(c["production_minus_ideal64_l2"] for c in b["cap"])
                * summary["spectrum"]["head_axis_l2"]
                / 4
            )
            value = b["binding"]["interaction_axis"]
            raw = b["factors"]["x"]
            affected.append(
                {
                    "world": b["world"],
                    "raw_signed_axis_interaction_over_memory_bias": b["odd_donor_sign"]
                    * raw["interaction"]["axis_dot"]
                    / abs(raw["memory"]["axis_dot"]),
                    "capped_binding": b["binding"],
                    "cap64_interaction_axis_interval": [value - bound, value + bound],
                    "cap32_vs_cap64_interaction_axis_error_bound": bound,
                    "bound_scope": "arithmetic diagnostic, not a statistical confidence interval",
                }
            )
        actual = variants["actual"]["factors"]
        actual_i = actual["d"]["interaction"]["l2"]["mean"]
        derived[arm] = {
            "mean_factor_l2": {
                stage: {name: actual[stage][name]["l2"]["mean"] for name in replay.NAMES}
                for stage in replay.STAGES
            },
            "mean_common_output_top1_energy_fraction": actual["d"]["common"][
                "top1_energy_fraction"
            ]["mean"],
            "common_slot_over_actual_mean_interaction_l2": variants["common_slots"]["factors"]["d"][
                "interaction"
            ]["l2"]["mean"]
            / actual_i,
            "random_over_actual_mean_interaction_l2": variants["random_pair"]["factors"]["d"][
                "interaction"
            ]["l2"]["mean"]
            / actual_i,
            "affected": affected,
            "max_factor_reconstruction_error": max(
                max(b["reconstruction_max_abs"].values()) for b in blocks
            ),
            "max_projection_production_error": max(
                v["fp64_projection_vs_production_max_abs"]
                for b in blocks
                for v in b["projection"].values()
            ),
        }
        if arm == "query_modulated":
            derived[arm]["mean_modulation_sources_actual"] = {
                name: {
                    key: statistics.mean(
                        b["modulation_sources"]["sources"][name][key]
                        for b in blocks
                        if b["variant"] == "actual"
                    )
                    for key in ("z_l2", "projected_l2", "projected_axis_dot")
                }
                for name in ("propagated_interaction", "memory_question_coupling")
            }
            derived[arm]["max_modulation_rounding_error"] = max(
                b["modulation_sources"]["rounding_error_max_abs"] for b in blocks
            )
            derived[arm]["max_modulation_error_over_bound"] = max(
                b["modulation_sources"]["rounding_error_max_abs"]
                / b["modulation_sources"]["rounding_bound_max_abs"]
                for b in blocks
            )
    return {
        "status": "POST_RESULT_OFFLINE_MECHANISM_CONTRASTS",
        "source_commit": summary["source_commit"],
        "arms": derived,
        "new_model_calls": 0,
        "old_expression_gate": "FAIL",
        "winner": "none",
        "non_regression": "NOT_ESTABLISHED",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-new", action="store_true")
    args = parser.parse_args()
    result = build()
    path = HERE / "MECHANISM.json"
    if args.write_new:
        with path.open("x") as stream:
            stream.write(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    else:
        replay.require(replay.read(path) == result, "Derived mechanism replay")
    print(
        json.dumps({"status": result["status"], "arms": list(result["arms"]), "new_model_calls": 0})
    )


if __name__ == "__main__":
    main()
