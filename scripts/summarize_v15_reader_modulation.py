#!/usr/bin/env python3
"""Offline denominator/identity replay of the frozen reader intervention."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import statistics
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATES = ("initial_seed47", "retained_answer_step8")
ARMS = ("legacy", "query_modulated")
CONTROLS = (
    "intact",
    "twin",
    "zero",
    "unrelated",
    "carrier",
    "random",
    "permuted_intact",
    "common_intact",
)
ROLES = ("intact_answer", "intact_eos", "twin_answer", "twin_eos", "unrelated")


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    value = json.loads(path.read_text())

    def finite(item):
        if isinstance(item, dict):
            return all(finite(v) for v in item.values())
        if isinstance(item, list):
            return all(finite(v) for v in item)
        return not isinstance(item, float) or math.isfinite(item)

    require(finite(value), f"Nonfinite artifact: {path}")
    return value


def stats(values):
    usable = [v for v in values if v is not None]
    return {
        "n": len(values),
        "defined": len(usable),
        "mean": statistics.mean(usable) if usable else None,
        "min": min(usable) if usable else None,
        "max": max(usable) if usable else None,
    }


def cell(evaluation, gradient, state, arm):
    rows = evaluation["rows"]
    coordinates = [(r["world"], r["query"], r["control"]) for r in rows]
    require(
        sorted(coordinates) == sorted(itertools.product(range(2), range(8), CONTROLS)),
        "Evaluation duplicate/missing coordinates",
    )
    lookup = dict(zip(coordinates, rows, strict=True))
    require(all(r["delta_l2"] <= 1.000001 for r in rows), "Output cap")
    for r in rows:
        scores, label = r["native_scores"], r["label"]
        prediction = None if scores[0] == scores[1] else int(scores[1] > scores[0])
        require(r["prediction"] == prediction, "Prediction replay")
        require(
            r["correct"] == (prediction == label if label is not None else None), "Truth replay"
        )
        require(r["strength_zero_delta_exact"] == (arm == "legacy"), "Strength-zero control")
        require(
            r["legacy_source_score_exact"] == (arm == "legacy" and label is not None),
            "Historical parity denominator",
        )
        if state == STATES[0] or r["control"] == "zero":
            require(r["delta_l2"] == 0 and r["full_logits_equal_base"], "Zero parity")
    reciprocal = evaluation["reciprocal"]
    require(
        sorted((r["world"], r["even_query"], r["control"]) for r in reciprocal)
        == sorted(itertools.product(range(2), (0, 2, 4, 6), CONTROLS)),
        "Reciprocal scope",
    )
    require(
        sorted((r["world"], r["even_query"]) for r in evaluation["interactions"])
        == list(itertools.product(range(2), (0, 2, 4, 6))),
        "Mixed-effect scope",
    )
    permutations = evaluation["permutations"]
    require(
        sorted((r["world"], r["query"]) for r in permutations)
        == list(itertools.product(range(2), range(8))),
        "Permutation scope",
    )
    require(max(r["delta_max_abs_error"] for r in permutations) <= 1e-5, "Permutation tolerance")
    pairs = gradient["pairs"]
    require(
        [(r["world"], r["query"]) for r in pairs] == list(itertools.product(range(2), range(8))),
        "Gradient coordinates",
    )
    for pair in pairs:
        require([r["role"] for r in pair["routes"]] == list(ROLES), "Gradient route scope")
        require(len({r["name"] for r in pair["parameters"]}) == 26, "Parameter denominator")
    routes = [r for pair in pairs for r in pair["routes"]]
    require(all(r["l2"] == 0 for r in routes if r["role"].endswith("eos")), "EOS zero weight")
    if state == STATES[0]:
        require(all(r["l2"] == 0 for r in routes), "Initial closed output gradient")
    semantics = []
    for w, q in itertools.product(range(2), range(8)):
        a, b = lookup[w, q, "intact"], lookup[w, q, "twin"]
        affected = a["label"] != b["label"]
        require(affected == (q < 2), "Affected denominator")
        gap = lambda scores: scores[1] - scores[0]  # noqa: E731
        semantics.append(
            {
                "world": w,
                "query": q,
                "affected": affected,
                "native_gap_change": gap(b["native_scores"]) - gap(a["native_scores"]),
                "donor_native": (2 * b["label"] - 1)
                * (gap(b["native_scores"]) - gap(a["native_scores"])),
                "donor_fp32": (2 * b["label"] - 1)
                * (gap(b["fp32_scores"]) - gap(a["fp32_scores"])),
                "correct_donor_flip": affected and a["correct"] and b["correct"],
            }
        )
    affected = [r for r in semantics if r["affected"]]
    truth = [r for r in rows if r["label"] is not None]
    eligible = [r for r in routes if not r["role"].endswith("eos")]
    return {
        "evaluation_rows": len(rows),
        "truth_rows": len(truth),
        "correct": sum(r["correct"] for r in truth),
        "ties": sum(r["prediction"] is None for r in truth),
        "affected_pairs": len(affected),
        "correct_donor_flips": sum(r["correct_donor_flip"] for r in affected),
        "affected_donor_native": [r["donor_native"] for r in affected],
        "affected_donor_fp32": [r["donor_fp32"] for r in affected],
        "unaffected_absolute_native_gap_change": stats(
            [abs(r["native_gap_change"]) for r in semantics if not r["affected"]]
        ),
        "unrelated_absolute_base_native_gap_shift": stats(
            [
                abs(gap(r["native_scores"]) - gap(r["base_native_scores"]))
                for r in rows
                if r["control"] == "unrelated"
            ]
        ),
        "query_routes": len(routes),
        "eligible_query_routes": len(eligible),
        "nonzero_eligible_query_routes": sum(r["l2"] > 0 for r in eligible),
        "query_gradient_l2": stats([r["l2"] for r in eligible]),
        "query_gradient_by_role": {
            role: stats([r["l2"] for r in routes if r["role"] == role]) for role in ROLES
        },
        "donor_up_cancellation_ratio": gradient["donor_up_cancellation_ratio"],
        "permutation_max_abs_error": max(r["delta_max_abs_error"] for r in permutations),
        "reciprocal_by_control": {
            control: {
                key: stats([r["delta"][key] for r in reciprocal if r["control"] == control])
                for key in (
                    "difference_l2",
                    "relative_l2",
                    "unit_direction_difference_l2",
                    "equal_norm_difference_l2",
                    "tangential_difference_l2",
                )
            }
            for control in CONTROLS
        },
        "mixed_delta_difference_l2": stats(
            [r["mixed_delta_difference_l2"] for r in evaluation["interactions"]]
        ),
    }


def build(bundle):
    raw = bundle / "raw"
    seal, started, report = (
        read(p) for p in (bundle / "SOURCE_SEAL.json", raw / "STARTED.json", raw / "REPORT.json")
    )
    require(not (raw / "FAILED.json").exists(), "Run has a failure receipt")
    require(
        started["source_commit"] == seal["source_commit"]
        and started["source_hashes"] == seal["source_hashes"],
        "Source receipt",
    )
    for name, expected in seal["source_hashes"].items():
        require(digest(REPO / name) == expected, f"Sealed source changed: {name}")
    require(
        started["plan"] == read(REPO / "configs/v15/READER_MODULATION_PLAN.json"), "Plan receipt"
    )
    require(report["status"] == "COMPLETED_READER_INTERVENTION_NO_STEP", "Terminal status")
    require(
        report["base_sha256_before"]
        == report["base_sha256_after"]
        == "54d161755862ebf00d8acbca083d5f290a5de44d33af82ca885f3bd8f9c94312",
        "Base identity",
    )
    require(
        report["optimizer_steps"] == report["new_generations"] == report["new_judge_calls"] == 0
        and report["optimizer_constructed"] is False,
        "No-step receipt",
    )
    require(
        report["old_expression_gate"] == "FAIL"
        and report["winner"] == "none"
        and report["non_regression"] == "NOT_ESTABLISHED",
        "Claim ceiling",
    )
    require(
        [(r["state"], r["arm"]) for r in report["results"]]
        == list(itertools.product(STATES, ARMS)),
        "Completed cells",
    )
    prior = read(REPO / "provenance/pilots/v15_5_native_answer_20261010/raw/REPORT.json")[
        "results"
    ][0]
    for result in report["results"]:
        expected = prior[
            "initial_state_sha256" if result["state"] == STATES[0] else "final_state_sha256"
        ]
        require(result["before_sha256"] == result["after_sha256"] == expected, "Bridge identity")
        require(
            result["parameter_tensors"] == 26 and result["parameter_elements"] == 4200192,
            "Bridge inventory",
        )
    features = read(raw / "FEATURES.json")
    require(
        len(features["native_parity"]) == 48
        and all(r["full_logits_exact"] for r in features["native_parity"]),
        "Feature parity",
    )
    cells = {
        f"{state}/{arm}": cell(
            read(raw / f"{state}_{arm}_EVAL.json"),
            read(raw / f"{state}_{arm}_GRAD.json"),
            state,
            arm,
        )
        for state, arm in itertools.product(STATES, ARMS)
    }
    resources = [json.loads(line) for line in (raw / "RESOURCES.jsonl").read_text().splitlines()]
    return {
        "source_commit": seal["source_commit"],
        "cells": cells,
        "evaluation_rows": sum(c["evaluation_rows"] for c in cells.values()),
        "truth_rows": sum(c["truth_rows"] for c in cells.values()),
        "query_routes": sum(c["query_routes"] for c in cells.values()),
        "elapsed_seconds": report["elapsed_seconds"],
        "peak_cuda_allocated_gib": report["peak_cuda_allocated_bytes"] / 2**30,
        "peak_cuda_reserved_gib": report["peak_cuda_reserved_bytes"] / 2**30,
        "sampled_min_free_gib": min(r["free_bytes"] for r in resources) / 2**30,
        "resource_samples": len(resources),
        "old_expression_gate": "FAIL",
        "winner": "none",
        "non_regression": "NOT_ESTABLISHED",
        "semantic_promotion": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    summary = build(args.bundle)
    index = {
        p.name: {"sha256": digest(p), "bytes": p.stat().st_size}
        for p in sorted((args.bundle / "raw").iterdir())
        if p.is_file()
    }
    for name, value in (("SUMMARY.json", summary), ("ARTIFACT_INDEX.json", index)):
        target = args.bundle / name
        if args.write:
            with target.open("x") as stream:
                json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
                stream.write("\n")
        else:
            require(read(target) == value, f"Replay differs: {name}")
    print(
        json.dumps(
            {
                "replay": "PASS",
                "rows": summary["evaluation_rows"],
                "raw_files": len(index),
                "semantic_promotion": False,
            }
        )
    )


if __name__ == "__main__":
    main()
