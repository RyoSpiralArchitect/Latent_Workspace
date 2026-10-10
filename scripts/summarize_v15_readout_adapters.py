#!/usr/bin/env python3
"""Offline, fail-closed replay of the read-only adapter audit. No Torch required."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATES = (
    ("reader", "legacy", 8),
    ("reader", "query_modulated", 8),
    ("full", "frozen", 2),
    ("full", "full", 2),
)
STAGES = (
    "intended_linear_gap_change_fp64",
    "after_input_cast_linear_gap_change_fp64",
    "native_head_gap_change",
    "native_published_gap_change",
)


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(test, message):
    if not test:
        raise ValueError(message)


def analyze(bundle):
    raw = bundle / "raw"
    require(not (raw / "ERROR.json").exists(), "Execution has an error receipt")
    finish = read(raw / "FINISHED.json")
    start = read(raw / "STARTED.json")
    seal = read(bundle / "SOURCE_SEAL.json")
    require(finish["status"] == "COMPLETED_READ_ONLY_ADAPTER_AUDIT", "Not completed")
    require(
        start["source_commit"] == finish["source_commit"] == seal["source_commit"],
        "Source commit mismatch",
    )
    require(start["source_hashes"] == seal["source_hashes"], "Execution source mismatch")
    for name, sha in seal["source_hashes"].items():
        require(digest(REPO / name) == sha, f"Source/input changed: {name}")
    require(
        {k: finish[k] for k in ("adapter_forwards", "memory_pairs", "affected_pairs")}
        == dict(adapter_forwards=192, memory_pairs=64, affected_pairs=16),
        "Terminal denominators",
    )
    require(
        all(finish[k] == 0 for k in ("optimizer_steps", "new_sequences", "judge_calls")),
        "Not read-only",
    )
    require(finish["old_expression_gate"] == "FAIL" and finish["winner"] == "none", "Claim drift")
    prior = REPO / "provenance/pilots/v15_native_learner_20261010"
    for name, receipt in read(prior / "ARTIFACT_INDEX.json").items():
        path = prior / name
        require(
            path.stat().st_size == receipt["bytes"] and digest(path) == receipt["sha256"],
            f"Historical raw input changed: {name}",
        )
    results = []
    for phase, arm, step in STATES:
        path = raw / f"{phase}_{arm}.json"
        panel = read(path)
        require(
            (panel["phase"], panel["arm"], panel["step"]) == (phase, arm, step), "State mismatch"
        )
        require(panel["weights_unchanged"] is True, "Weight mutation")
        require(
            panel["checkpoint"] == read(prior / "raw" / phase / f"{arm}_{step}_checkpoint.json"),
            "Checkpoint receipt mismatch",
        )
        old = {
            (r["world"], r["query"], r["control"]): r
            for r in read(prior / "raw" / phase / f"{arm}_{step}_evaluation.json")["rows"]
        }
        rows = {(r["world"], r["query"], r["condition"]): r for r in panel["rows"]}
        coordinates = {
            (w, q, c) for w in range(2) for q in range(8) for c in ("intact", "twin", "zero")
        }
        require(len(rows) == len(panel["rows"]) == 48 and set(rows) == coordinates, "Row coverage")
        for key, row in rows.items():
            require(
                row["full_logits_exact"] is True and row["historical_choices_exact"] is True,
                "Native parity failure",
            )
            require(row["native_scores"] == old[key]["native_scores"], "Historical scores differ")
            require(row["zero_exact"] == (key[2] == "zero"), "Zero coverage")
            require(len(row["logits_sha256"]) == 64, "Missing full output hash")
        pairs = {(r["world"], r["query"]): r for r in panel["pairs"]}
        require(
            len(pairs) == len(panel["pairs"]) == 16
            and set(pairs) == {(w, q) for w in range(2) for q in range(8)},
            "Pair coverage",
        )
        affected = []
        for (w, q), pair in pairs.items():
            a, b = old[w, q, "intact"], old[w, q, "twin"]
            require(
                pair["affected"] == (a["target_label"] != b["target_label"])
                and pair["donor_sign"] == 2 * b["target_label"] - 1,
                "Post-hoc direction labels",
            )
            probe = pair["transport"]
            require(
                probe["fp64_probe_is_native_logits"] is False
                and probe["candidate_ids"] == [1476, 5849],
                "Diagnostic axis semantics",
            )
            scalars = (
                *STAGES,
                "input_cast_gap_residual",
                "head_arithmetic_gap_residual",
                "model_postprocessing_gap_residual",
                "intended_delta_difference_l2",
                "applied_delta_difference_l2",
            )
            for name in scalars:
                require(
                    len(probe[name]) == 1
                    and type(probe[name][0]) in (float, int)
                    and math.isfinite(probe[name][0]),
                    "Finite scalar probe required",
                )
            native = [rows[w, q, c]["native_scores"] for c in ("intact", "twin")]
            difference = (native[1][1] - native[1][0]) - (native[0][1] - native[0][0])
            require(probe[STAGES[-1]][0] == difference, "Published gap differs from native scores")
            require(
                probe["changed_last_vocab_elements"][0] in range(32769)
                and type(probe["greedy_token_changed"][0]) is bool,
                "Native change counters",
            )
            for first, second, error in zip(STAGES, STAGES[1:], scalars[4:7]):
                require(
                    probe[error][0] == probe[second][0] - probe[first][0], "Stage residual mismatch"
                )
            if pair["affected"]:
                affected.append(pair)
        require(len(affected) == 4, "Affected denominator")
        stage_counts = []
        for stage in STAGES:
            values = [r["transport"][stage][0] for r in affected]
            stage_counts.append(
                dict(
                    stage=stage,
                    affected_denominator=4,
                    positive_donor=sum(r["donor_sign"] * v > 0 for r, v in zip(affected, values)),
                    nonzero=sum(v != 0 for v in values),
                    mean_abs=sum(abs(v) for v in values) / 4,
                    max_abs=max(abs(v) for v in values),
                )
            )
        results.append(
            dict(
                phase=phase,
                arm=arm,
                step=step,
                source=str(path.relative_to(bundle)),
                old_new_full_logits_exact=48,
                zero_exact=16,
                paired_probes=16,
                affected_probes=4,
                stages=stage_counts,
                affected_input_cast_sign_reversals=sum(
                    p["transport"][STAGES[0]][0] * p["transport"][STAGES[1]][0] < 0
                    for p in affected
                ),
                affected_nonzero_applied_hidden=sum(
                    p["transport"]["applied_delta_difference_l2"][0] > 0 for p in affected
                ),
                affected_changed_full_vocab=sum(
                    p["transport"]["changed_last_vocab_elements"][0] > 0 for p in affected
                ),
                affected_greedy_token_changes=sum(
                    p["transport"]["greedy_token_changed"][0] for p in affected
                ),
                all_pair_changed_full_vocab=sum(
                    p["transport"]["changed_last_vocab_elements"][0] > 0 for p in pairs.values()
                ),
                all_pair_native_gap_changes=sum(
                    p["transport"][STAGES[-1]][0] != 0 for p in pairs.values()
                ),
                affected_examples=affected,
            )
        )
    return dict(
        schema="v15-readout-adapter-offline-summary-v1",
        source_commit=finish["source_commit"],
        status="READOUT_PLUMBING_QUALIFIED_SEMANTIC_GATE_UNCHANGED",
        planned_adapter_forwards=192,
        completed_adapter_forwards=192,
        memory_pairs=64,
        affected_pairs=16,
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
        optimizer_steps=0,
        new_sequences=0,
        judge_calls=0,
        elapsed_seconds=finish["elapsed_seconds"],
        peak_cuda_allocated_bytes=finish["peak_cuda_allocated_bytes"],
        results=results,
    )


def inventory(bundle):
    return {
        str(p.relative_to(bundle)): dict(bytes=p.stat().st_size, sha256=digest(p))
        for p in sorted((bundle / "raw").iterdir())
        if p.is_file()
    }


def publication_table(summary):
    lines = [
        "| Retained state | Intended donor-aligned | After hidden cast | "
        "Native donor-aligned | Changed vocabulary |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in summary["results"]:
        counts = [stage["positive_donor"] for stage in row["stages"]]
        lines.append(
            f"| {row['phase']}/{row['arm']} step {row['step']} | {counts[0]}/4 | "
            f"{counts[1]}/4 | {counts[3]}/4 | {row['all_pair_changed_full_vocab']}/16 |"
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    result = analyze(args.bundle)
    for name, value in (("SUMMARY.json", result), ("ARTIFACT_INDEX.json", inventory(args.bundle))):
        text = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
        path = args.bundle / name
        if args.write:
            with path.open("x") as stream:
                stream.write(text)
        else:
            require(path.read_text() == text, f"Publication replay differs: {name}")
    print(json.dumps({k: v for k, v in result.items() if k != "results"}))


if __name__ == "__main__":
    main()
