#!/usr/bin/env python3
"""Check selected publication numbers, raw inventory and local links offline."""

from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import summarize_v15_reader_modulation as audit  # noqa: E402


def main():
    result = audit.build(HERE)
    audit.require(result == audit.read(HERE / "SUMMARY.json"), "Summary differs")
    index = audit.read(HERE / "ARTIFACT_INDEX.json")
    actual = {
        p.name: {"sha256": audit.digest(p), "bytes": p.stat().st_size}
        for p in sorted((HERE / "raw").iterdir())
        if p.is_file()
    }
    audit.require(index == actual, "Raw inventory differs")
    audit.require(
        len(index) == 13 and sum(r["bytes"] for r in index.values()) == 1164045,
        "Raw file/byte denominator",
    )
    cells = result["cells"]
    a, b = (cells[f"retained_answer_step8/{arm}"] for arm in audit.ARMS)
    gradient_ratio = b["query_gradient_l2"]["mean"] / a["query_gradient_l2"]["mean"]
    distance_ratio = (
        b["reciprocal_by_control"]["intact"]["difference_l2"]["mean"]
        / a["reciprocal_by_control"]["intact"]["difference_l2"]["mean"]
    )
    documents = {
        p: p.read_text()
        for p in (
            HERE / "README.md",
            HERE / "EXECUTION_HANDOFF.md",
            REPO / "docs/v15/READER_MODULATION.md",
        )
    }
    documents[REPO / "README.md"] = (
        (REPO / "README.md").read_text().split("## V14.5 to full-update V15:")[0]
    )
    documents[REPO / "docs/v15/NEXT_STEPS.md"] = (
        (REPO / "docs/v15/NEXT_STEPS.md").read_text().split("## Prior completed unit:")[0]
    )
    text = documents[HERE / "README.md"]
    for document in (
        text,
        documents[REPO / "README.md"],
        documents[REPO / "docs/v15/NEXT_STEPS.md"],
    ):
        for ratio in (gradient_ratio, distance_ratio):
            audit.require(f"{ratio:.2f}×" in document, "Ratio rounding/publication")
    for key in (
        "elapsed_seconds",
        "peak_cuda_allocated_gib",
        "peak_cuda_reserved_gib",
        "sampled_min_free_gib",
    ):
        audit.require(f"{result[key]:.6f}" in text, f"Resource number: {key}")
    for arm in audit.ARMS:
        c = cells[f"retained_answer_step8/{arm}"]
        for key in ("mean", "min", "max"):
            audit.require(f"{c['query_gradient_l2'][key]:.6e}" in text, "Gradient number")
        for control in ("intact", "common_intact", "unrelated", "carrier", "random", "zero"):
            value = c["reciprocal_by_control"][control]["difference_l2"]["mean"]
            audit.require(f"{value:.6e}" in text, "Control distance")
        for value in (
            c["reciprocal_by_control"]["intact"]["equal_norm_difference_l2"]["mean"],
            c["mixed_delta_difference_l2"]["mean"],
        ):
            audit.require(f"{value:.6e}" in text, "Direction/mixed number")
        for value in c["affected_donor_fp32"]:
            audit.require(str(value) in text, "Literal FP32 donor margin")
        rows = audit.read(HERE / "raw" / f"retained_answer_step8_{arm}_EVAL.json")["rows"]
        value = statistics.mean(r["delta_l2"] for r in rows if r["control"] == "intact")
        audit.require(f"{value:.10f}" in text, "Intact norm")
        audit.require(
            c["correct"] == 16
            and c["truth_rows"] == 32
            and c["correct_donor_flips"] == 0
            and c["affected_pairs"] == 4,
            "Truth counts",
        )
        audit.require(
            c["unrelated_absolute_base_native_gap_shift"]["mean"] == 0.0703125
            and c["unrelated_absolute_base_native_gap_shift"]["max"] == 0.125,
            "Unrelated native disturbance",
        )
    for c in cells.values():
        audit.require(f"{c['donor_up_cancellation_ratio']:.10f}" in text, "Cancellation fraction")
    old, new = [
        audit.read(HERE / "raw" / f"retained_answer_step8_{arm}_EVAL.json")["rows"]
        for arm in audit.ARMS
    ]
    matched = [(x, y) for x, y in zip(old, new, strict=True) if x["label"] is not None]
    audit.require(
        len(matched) == 32 and all(x["native_scores"] == y["native_scores"] for x, y in matched),
        "Matched native-vector count",
    )
    links = 0
    for path, content in documents.items():
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", content):
            if not target.startswith(("https://", "http://", "#")):
                audit.require(
                    (path.parent / target.split("#", 1)[0]).resolve().is_file(),
                    f"Broken local link: {target}",
                )
                links += 1
    print(
        json.dumps(
            {
                "status": "VERIFIED_SELECTED_PUBLICATION_NUMBERS_AND_LINKS",
                "raw_files": len(index),
                "local_links": links,
                "gradient_ratio": gradient_ratio,
                "reciprocal_distance_ratio": distance_ratio,
                "scope": "offline receipts and selected prose; not independent model recomputation",
            }
        )
    )


if __name__ == "__main__":
    main()
