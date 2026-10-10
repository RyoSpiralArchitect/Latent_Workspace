#!/usr/bin/env python3
"""Offline scalar/identity replay; does not independently recompute model tensors."""

from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path

from summarize_v15_reader_modulation import digest, read, require, stats

REPO = Path(__file__).resolve().parents[1]
ARMS = ("legacy", "query_modulated")
VARIANTS = ("actual", "common_slots", "same_memory", "random_pair")
NAMES = ("common", "question", "memory", "interaction")
STAGES = ("r", "z", "x", "d")


def close(a, b):
    return math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-15)


def summarize_cell(panel, arm, historical):
    rows, blocks, zero = panel["rows"], panel["blocks"], panel["written_zero"]
    coordinates = [(r["world"], r["query"], r["variant"], r["side"]) for r in rows]
    require(
        sorted(coordinates) == sorted(itertools.product(range(2), range(8), VARIANTS, range(2))),
        "Row coordinates",
    )
    require(
        sorted((b["world"], b["even_query"], b["variant"]) for b in blocks)
        == sorted(itertools.product(range(2), (0, 2, 4, 6), VARIANTS)),
        "Block coordinates",
    )
    require(
        sorted((z["world"], z["query"]) for z in zero)
        == list(itertools.product(range(2), range(8)))
        and all(z["full_logits_exact"] for z in zero),
        "Written zero",
    )
    lookup = dict(zip(coordinates, rows, strict=True))
    prior = {(r["world"], r["query"], r["control"]): r for r in historical}
    for r in rows:
        scores = r["native_scores"]
        prediction = None if scores[0] == scores[1] else int(scores[1] > scores[0])
        truth = r["variant"] == "actual"
        require(r["prior_native_exact"] == truth, "Historical parity scope")
        require(
            r["prediction"] == prediction
            and r["correct"] == (prediction == r["label"] if truth else None),
            "Truth replay",
        )
        require(0 <= r["delta_l2"] < 1, "Cap scope")
        require(set(r["trace_sha256"]) == {"q", "r", "z", "x", "d", "gate"}, "Trace scope")
        require(all(len(v) == 64 for v in r["trace_sha256"].values()), "Trace hash")
        if truth:
            h = prior[r["world"], r["query"], "twin" if r["side"] else "intact"]
            require(
                r["label"] == h["label"] and scores == h["native_scores"],
                "Historical vector changed",
            )
        else:
            require(r["label"] is None, "Synthetic factual label")
    for b in blocks:
        require(
            b["binding_label_interpretation"]
            == (b["variant"] == "actual" and b["even_query"] == 0),
            "Binding scope",
        )
        require(max(b["reconstruction_max_abs"].values()) <= 1e-12, "FP64 reconstruction")
        m, i = (b["factors"]["d"][k]["axis_dot"] for k in ("memory", "interaction"))
        sign = b["odd_donor_sign"]
        binding = b["binding"]
        require(binding["both_donor_margins_positive"] == (sign * i > abs(m)), "Binding algebra")
        require(
            close(binding["memory_axis"], m) and close(binding["interaction_axis"], i),
            "Binding factors",
        )
        for offset, cap in enumerate(b["cap"]):
            require(
                cap["query_offset"] == offset
                and close(cap["radial_scale"], cap["tangential_scale"] ** 3),
                "Cap derivative",
            )
            expected = 2 * (m + (-1 if offset == 0 else 1) * i)
            require(
                close(cap["production_axis_gap_change"], expected),
                "Axis finite-difference reconstruction",
            )
            if b["binding_label_interpretation"]:
                donor = (1 if offset else -1) * sign * expected
                require(
                    close(binding["odd_donor_margin" if offset else "even_donor_margin"], donor),
                    "Donor sign",
                )
        if b["variant"] == "same_memory":
            require(
                all(
                    b["factors"][stage][name]["l2"] == 0
                    for stage in STAGES
                    for name in ("memory", "interaction")
                ),
                "Same-memory factor null",
            )
            for q in (b["even_query"], b["even_query"] + 1):
                a, c = [lookup[b["world"], q, "same_memory", s] for s in (0, 1)]
                require(
                    a["trace_sha256"] == c["trace_sha256"]
                    and a["native_scores"] == c["native_scores"],
                    "Same-memory corner null",
                )
        if arm == "query_modulated":
            sources = b["modulation_sources"]
            require(
                sources["rounding_error_max_abs"] <= sources["rounding_bound_max_abs"],
                "Modulation rounding",
            )
        else:
            require("modulation_sources" not in b, "Legacy source scope")
    affected = []
    for w, q in itertools.product(range(2), (0, 1)):
        a, b = [lookup[w, q, "actual", s] for s in (0, 1)]
        require(a["label"] != b["label"], "Affected scope")
        gap = lambda r: r["native_scores"][1] - r["native_scores"][0]  # noqa: E731
        affected.append(
            {
                "world": w,
                "query": q,
                "donor_native": (2 * b["label"] - 1) * (gap(b) - gap(a)),
                "correct_donor_flip": a["correct"] and b["correct"],
            }
        )
    truth = [r for r in rows if r["label"] is not None]
    return {
        "rows": len(rows),
        "blocks": len(blocks),
        "truth_rows": len(truth),
        "correct": sum(r["correct"] for r in truth),
        "ties": sum(r["prediction"] is None for r in truth),
        "written_zero": len(zero),
        "prior_native_exact": len(truth),
        "affected": affected,
        "correct_donor_flips": sum(r["correct_donor_flip"] for r in affected),
        "by_variant": {
            variant: {
                "blocks": 8,
                "factors": {
                    stage: {
                        name: {
                            metric: stats(
                                [
                                    b["factors"][stage][name][metric]
                                    for b in blocks
                                    if b["variant"] == variant
                                ]
                            )
                            for metric in (
                                "l2",
                                "axis_dot",
                                "axis_alignment",
                                "top1_energy_fraction",
                                "top8_energy_fraction",
                            )
                        }
                        for name in NAMES
                    }
                    for stage in STAGES
                },
                "cap": {
                    key: stats(
                        [c[key] for b in blocks if b["variant"] == variant for c in b["cap"]]
                    )
                    for key in (
                        "tangential_scale",
                        "radial_scale",
                        "raw_memory_difference_l2",
                        "production_memory_difference_l2",
                        "ideal64_minus_linearization_l2",
                        "production_minus_ideal64_l2",
                    )
                },
            }
            for variant in VARIANTS
        },
        "actual_affected_binding": [
            {"world": b["world"], **b["binding"]}
            for b in blocks
            if b["binding_label_interpretation"]
        ],
    }


def build(bundle):
    raw = bundle / "raw"
    require(not (raw / "FAILED.json").exists(), "Failure cannot become completion")
    expected_names = {
        "STARTED.json",
        "BASE_IDENTITY.json",
        "FEATURES.json",
        "SPECTRUM.json",
        "REPORT.json",
        "RESOURCES.jsonl",
        *(f"{arm}_FACTORS.json" for arm in ARMS),
    }
    require({p.name for p in raw.iterdir() if p.is_file()} == expected_names, "Raw inventory")
    seal, started, report = (
        read(p) for p in (bundle / "SOURCE_SEAL.json", raw / "STARTED.json", raw / "REPORT.json")
    )
    require(
        started["source_hashes"] == seal["source_hashes"]
        and started["source_commit"] == seal["source_commit"],
        "Source seal identity",
    )
    for name, expected in seal["source_hashes"].items():
        require(digest(REPO / name) == expected, f"Source changed: {name}")
    require(report["status"] == "COMPLETED_READER_FACTOR_AUDIT_NO_UPDATE", "Terminal status")
    require(
        report["optimizer_steps"] == report["new_generations"] == report["new_judge_calls"] == 0
        and report["optimizer_constructed"] is False
        and report["autograd_enabled"] is False,
        "No-update contract",
    )
    require(
        report["old_expression_gate"] == "FAIL"
        and report["winner"] == "none"
        and report["non_regression"] == "NOT_ESTABLISHED",
        "Gates",
    )
    prior = REPO / "provenance/pilots/v15_reader_modulation_20261010"
    old_report = read(prior / "raw/REPORT.json")
    require(
        report["base_sha256_before"]
        == report["base_sha256_after"]
        == old_report["base_sha256_after"]
        == read(raw / "BASE_IDENTITY.json")["before_sha256"],
        "Base identity",
    )
    require(
        report["parameter_grad_fields_none"]
        and [r["arm"] for r in report["results"]] == list(ARMS),
        "Arms/gradients",
    )
    for r in report["results"]:
        h = next(
            x
            for x in old_report["results"]
            if x["state"] == "retained_answer_step8" and x["arm"] == r["arm"]
        )
        require(
            r["before_sha256"] == r["after_sha256"] == h["after_sha256"]
            and r["parameter_grad_fields_none"],
            "Bridge identity",
        )
        require(r["rows"] == 128 and r["blocks"] == 32, "Cell denominator")
    features = read(raw / "FEATURES.json")
    require(features == read(prior / "raw/FEATURES.json"), "Frozen feature identity")
    require(
        len(features["native_parity"]) == 48
        and all(p["full_logits_exact"] for p in features["native_parity"]),
        "Full-head parity",
    )
    cells = {
        arm: summarize_cell(
            read(raw / f"{arm}_FACTORS.json"),
            arm,
            read(prior / "raw" / f"retained_answer_step8_{arm}_EVAL.json")["rows"],
        )
        for arm in ARMS
    }
    spectrum = read(raw / "SPECTRUM.json")
    require(
        len(spectrum["singular_values"]) == 256 and spectrum["candidate_ids"] == [1476, 5849],
        "Spectrum scope",
    )
    require(
        all(
            a >= b >= 0
            for a, b in zip(spectrum["singular_values"], spectrum["singular_values"][1:])
        ),
        "Ordered spectrum",
    )
    resources = [json.loads(line) for line in (raw / "RESOURCES.jsonl").read_text().splitlines()]
    require(
        resources[0]["phase"] == "admission" and resources[-1]["phase"] == "terminal",
        "Resource envelope",
    )
    require(
        all(not [p for p in r["processes"] if p["pid"] != started["pid"]] for r in resources),
        "Concurrent client",
    )
    limits = started["plan"]["resources"]
    require(
        resources[0]["free_bytes"] >= limits["admission_free_gib"] * 2**30
        and min(r["free_bytes"] for r in resources) >= limits["abort_free_gib"] * 2**30,
        "Resource floor",
    )
    require(
        report["elapsed_seconds"] < limits["max_elapsed_seconds"]
        and report["peak_cuda_allocated_bytes"] <= limits["allocator_cap_gib"] * 2**30,
        "Resource ceiling",
    )
    return {
        "status": "VERIFIED_READER_FACTOR_SCALAR_RECEIPTS",
        "source_commit": seal["source_commit"],
        "cells": cells,
        "spectrum": spectrum,
        "source_files": len(seal["source_hashes"]),
        "raw_files": len(expected_names),
        "elapsed_seconds": report["elapsed_seconds"],
        "peak_cuda_allocated_gib": report["peak_cuda_allocated_bytes"] / 2**30,
        "peak_cuda_reserved_gib": report["peak_cuda_reserved_bytes"] / 2**30,
        "sampled_min_free_gib": min(r["free_bytes"] for r in resources) / 2**30,
        "resource_samples": len(resources),
        "old_expression_gate": "FAIL",
        "winner": "none",
        "non_regression": "NOT_ESTABLISHED",
        "scope": (
            "Two exposed worlds, scalar receipt replay; "
            "no independent model recomputation or causal repair"
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--write-new", action="store_true")
    args = parser.parse_args()
    result = build(args.bundle)
    if args.write_new:
        # Exclusive artifact construction, never overwrites an existing receipt.
        for name, value in (
            ("SUMMARY.json", result),
            (
                "ARTIFACT_INDEX.json",
                {
                    p.name: {"sha256": digest(p), "bytes": p.stat().st_size}
                    for p in sorted((args.bundle / "raw").iterdir())
                    if p.is_file()
                },
            ),
        ):
            with (args.bundle / name).open("x") as stream:
                stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    else:
        if (args.bundle / "SUMMARY.json").exists():
            require(result == read(args.bundle / "SUMMARY.json"), "Frozen summary differs")
        if (args.bundle / "ARTIFACT_INDEX.json").exists():
            require(
                read(args.bundle / "ARTIFACT_INDEX.json")
                == {
                    p.name: {"sha256": digest(p), "bytes": p.stat().st_size}
                    for p in sorted((args.bundle / "raw").iterdir())
                    if p.is_file()
                },
                "Frozen raw index differs",
            )
    print(json.dumps({k: v for k, v in result.items() if k not in ("cells", "spectrum")}))


if __name__ == "__main__":
    main()
