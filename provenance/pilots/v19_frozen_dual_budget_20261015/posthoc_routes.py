#!/usr/bin/env python3
"""Post-hoc, descriptive route and transport tables for the frozen diagnostics.

Chosen after seeing the results; not a pre-registered test. Reads only saved
gzip evaluation records and window journals (no model, no network):

- mean residual norms per memory condition (total, applied, common, workspace);
- for the ``actual`` (intact versus twin) contrast on affected questions: the
  FP64 intended gap change (median magnitude, donor-directed count), how many
  published native bf16 gaps changed at all, and the intact-minus-twin
  difference of the injected delta before and after the bf16 input cast;
- the training journal's donor hinge: how many affected pairs per epoch still
  sit at the hinge maximum, the mean answer CE, and each objective term's
  weighted per-window mean (weights from the run contract).

Usage: posthoc_routes.py ARM_DIR [ARM_DIR ...] > POSTHOC.json
"""

from __future__ import annotations

import gzip
import json
import statistics
import sys
from pathlib import Path

ROUTES = ("delta_l2", "applied_delta_l2", "common_l2", "interaction_l2")
HINGE_MAX = 0.0625  # squared 0.25 margin with zero donor-directed movement
EPOCH = 128


def mean(values):
    return round(statistics.fmean(values), 6) if values else None


def routes(report):
    by_condition = {}
    for row in report["rows"]:
        by_condition.setdefault(row["condition"], []).append(row)
    return {
        condition: {key: mean([r[key] for r in rows]) for key in ROUTES}
        for condition, rows in sorted(by_condition.items())
    }


def transport(report):
    rows = [c for c in report["contrasts"] if c["factor"] == "actual" and c["affected"]]
    intended, directed, published = [], 0, 0
    transport_rows = [c["transport"] for c in rows]
    for contrast in rows:
        change = contrast["transport"]["intended_linear_gap_change_fp64"][0]
        # The gap is candidate 1 minus candidate 0; moving toward the twin's label
        # (the right-hand label) is donor-directed.
        toward = 1 if contrast["labels"][1] == 1 else -1
        intended.append(abs(change))
        directed += change * toward > 0
        published += contrast["transport"]["native_published_gap_change"][0] != 0
    return {
        "affected_questions": len(rows),
        "intended_fp64_median_abs": round(statistics.median(intended), 6),
        "intended_donor_directed": directed,
        "intended_not_donor_directed": len(rows) - directed,
        "published_gap_changed": published,
        **{
            f"median_{key}": round(statistics.median(abs(t[key][0]) for t in transport_rows), 6)
            for key in (
                "intended_delta_difference_l2",
                "applied_delta_difference_l2",
                "after_input_cast_linear_gap_change_fp64",
                "input_cast_gap_residual",
            )
        },
    }


def weights(folder):
    terms = json.loads((folder / "CONTEXT.json").read_text())["contract"]["objective"]["terms"]
    return {
        "answer_ce": terms["answer_ce_coefficient"],
        "donor_hinge": terms["direction_weight"],
        "unaffected_gap_square": terms["stability_weight"],
        "unrelated_gap_square": terms["unrelated_weight"],
        "residual_norm_square": terms["residual_penalty"],
    }


def training(windows, weight):
    epochs = []
    for start in range(0, len(windows), EPOCH):
        block = windows[start : start + EPOCH]
        pairs = [p["components"] for w in block for p in w["pairs"]]
        hinged = [p["donor_hinge"] for p in pairs if p["donor_hinge"] > 0]
        epochs.append(
            {
                "windows": f"{start + 1}-{start + len(block)}",
                "pairs": len(pairs),
                "donor_hinge_positive": len(hinged),
                "donor_hinge_at_max": sum(h >= HINGE_MAX for h in hinged),
                "mean_answer_ce": mean([p["answer_ce"] for p in pairs]),
                "weighted_per_window": {
                    key: round(factor * sum(p[key] for p in pairs) / len(block), 6)
                    for key, factor in weight.items()
                },
            }
        )
    return epochs


def arm(folder):
    folder = Path(folder)
    result = {"evaluations": {}}
    for path in sorted(folder.glob("eval_*_step*.json.gz")):
        split, step = path.name[len("eval_") : -len(".json.gz")].split("_step")
        if step == "0":
            continue
        report = json.load(gzip.open(path))
        result["evaluations"][f"{split}:{step}"] = {
            "routes": routes(report),
            "actual_affected_transport": transport(report),
        }
    lines = (folder / "windows.jsonl").read_text().splitlines()
    result["training"] = training([json.loads(line) for line in lines], weights(folder))
    return result


def main():
    out = {Path(folder).name: arm(folder) for folder in sys.argv[1:]}
    out["scope"] = "post-hoc descriptive; not a pre-registered endpoint"
    print(json.dumps(out, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
