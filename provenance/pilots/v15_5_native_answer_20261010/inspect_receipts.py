#!/usr/bin/env python3
"""Post-result descriptive audit; stored receipts only, no model/API execution.

This does not change the frozen verifier, gate, source, or scoring contract.
It checks the published artifact index before computing additional observations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent
ARMS = ("native_answer", "native_answer_eos")


def read(path):
    return json.loads(path.read_text())


def build():
    index = read(BUNDLE / "ARTIFACT_INDEX.json")
    for name, expected in index.items():
        if hashlib.sha256((BUNDLE / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Raw artifact changed: {name}")
    report = read(BUNDLE / "raw/REPORT.json")
    start = read(BUNDLE / "raw/STARTED.json")
    result = {
        "scope": "post-result descriptive audit of frozen scalar/token receipts",
        "raw_files": len(index),
        "source_hashes": len(start["source_hashes"]),
        "source_commit": report["source_commit"],
        "arms": {},
        "memory_gib": {
            name: report[name] / 2**30
            for name in (
                "peak_cuda_allocated_bytes",
                "peak_cuda_reserved_bytes",
                "sampled_own_process_peak_bytes",
                "minimum_sampled_device_free_bytes",
            )
        },
        "checkpoint_files": [c for arm in report["results"] for c in arm["checkpoints"]],
        "old_expression_gate": "FAIL",
        "winner": "none",
        "non_regression": "NOT_ESTABLISHED",
    }
    for arm in ARMS:
        generations = {
            step: {
                (r["world"], r["query"], r["condition"]): r
                for r in read(BUNDLE / f"raw/{arm}_{step}_generation.json")["rows"]
            }
            for step in (0, 8)
        }
        before, after = generations[0], generations[8]
        eval_rows = read(BUNDLE / f"raw/{arm}_8_evaluation.json")["rows"]
        evaluated = {(r["world"], r["query"], r["control"]): r for r in eval_rows}
        logs = [
            json.loads(line)
            for line in (BUNDLE / f"raw/{arm}_training.jsonl").read_text().splitlines()
        ]
        pairs = [(w, q) for w in range(2) for q in range(8)]
        generated_pairs = [(w, q) for w in range(2) for q in range(2)]
        nonzero = [r["delta_l2"] for r in eval_rows if r["control"] != "zero"]
        result["arms"][arm] = {
            "generation": {
                "changed_sequences_step0_to_step8": sum(
                    before[key]["generated_ids"] != row["generated_ids"]
                    for key, row in after.items()
                ),
                "sequence_denominator": len(after),
                "workspace_changed_vs_base": sum(
                    after[w, q, "workspace"]["generated_ids"]
                    != after[w, q, "base"]["generated_ids"]
                    for w, q in generated_pairs
                ),
                "workspace_twin_token_equal": sum(
                    after[w, q, "workspace"]["generated_ids"]
                    == after[w, q, "twin"]["generated_ids"]
                    for w, q in generated_pairs
                ),
                "pair_denominator": len(generated_pairs),
            },
            "step8_evaluation": {
                "intact_twin_choice_score_vectors_equal": sum(
                    evaluated[w, q, "intact"]["native_scores"]
                    == evaluated[w, q, "twin"]["native_scores"]
                    for w, q in pairs
                ),
                "intact_unrelated_choice_score_vectors_equal": sum(
                    evaluated[w, q, "intact"]["native_scores"]
                    == evaluated[w, q, "unrelated"]["native_scores"]
                    for w, q in pairs
                ),
                "pair_denominator": len(pairs),
                "nonzero_memory_rows": len(nonzero),
                "fp32_delta_l2_min": min(nonzero),
                "fp32_delta_l2_max": max(nonzero),
                "native_applied_delta_l2_max": max(
                    r["applied_native_delta_l2"] for r in eval_rows
                ),
            },
            "gradient_tensor_counts": {
                str(row["step"]): {
                    "present": sum(g["present"] for g in row["gradients"].values()),
                    "nonzero_l2": sum(g["l2"] > 0 for g in row["gradients"].values()),
                    "denominator": len(row["gradients"]),
                }
                for row in (logs[0], logs[-1])
            },
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(build(), indent=2, sort_keys=True, allow_nan=False) + "\n"
    path = BUNDLE / "OBSERVATIONS.json"
    if args.write:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(rendered)
    elif path.read_text() != rendered:
        raise ValueError("Descriptive observation replay differs")
    print("VERIFIED_POST_RESULT_OBSERVATIONS (no model or API calls)")


if __name__ == "__main__":
    main()
