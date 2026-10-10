#!/usr/bin/env python3
"""Offline identity/receipt replay, not independent gradient or model computation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent
REPO = BUNDLE.parents[2]
STATES = ("initial_seed47", "retained_answer_step8")
PAIRS = ((0, 0), (0, 1), (0, 2))


def require(value, message):
    if not value:
        raise ValueError(message)


def finite(value):
    if isinstance(value, float):
        require(math.isfinite(value), "Nonfinite scalar")
    elif isinstance(value, dict):
        for item in value.values():
            finite(item)
    elif isinstance(value, list):
        for item in value:
            finite(item)


def read(path):
    value = json.loads(path.read_text())
    finite(value)
    return value


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gradients(rows):
    require(len(rows) == len({r["name"] for r in rows}) == 317, "Parameter inventory")
    base = [r for r in rows if r["name"].startswith("base.")]
    bridge = [r for r in rows if r["name"].startswith("bridge.")]
    require(len(base) == 291 and sum(r["elements"] for r in base) == 7248023552, "Base inventory")
    require(len(bridge) == 26 and sum(r["elements"] for r in bridge) == 4200192, "Bridge inventory")
    require(all(r["present"] for r in rows), "Missing gradient")
    require(all(r["nonzero_elements"] > 0 for r in base), "Base gradient coverage")
    return {
        "base_tensors_present_nonzero": len(base),
        "base_elements": sum(r["elements"] for r in base),
        "bridge_tensors_nonzero": sum(r["nonzero_elements"] > 0 for r in bridge),
        "bridge_tensors_present": len(bridge),
    }


def build():
    raw = BUNDLE / "raw"
    seal = read(BUNDLE / "SOURCE_SEAL.json")
    for name, expected in seal["source_hashes"].items():
        require(sha(REPO / name) == expected, f"Source changed: {name}")
    started_path = raw / "STARTED.json"
    if started_path.exists():
        started = read(started_path)
        require(started["source_commit"] == seal["source_commit"], "Source commit mismatch")
        require(started["source_hashes"] == seal["source_hashes"], "Source file seal mismatch")
        require(started["seal_sha256"] == sha(BUNDLE / "SOURCE_SEAL.json"), "Seal bytes mismatch")
        require(
            started["plan"] == read(REPO / "configs/v15/FULL_UPDATE_BACKWARD_PLAN.json"),
            "Frozen plan mismatch",
        )
    terminals = [p for p in (raw / "REPORT.json", raw / "FAILED.json") if p.exists()]
    require(len(terminals) == 1, "Need exactly one terminal receipt")
    terminal = read(terminals[0])
    complete = terminal["status"] == "COMPLETED_FULL_BACKWARD_NO_STEP"
    require(complete or terminal["status"] == "FAILED_NO_RETRY", "Unknown terminal status")
    require(
        terminal["optimizer_steps"]
        == terminal["new_generations"]
        == terminal["new_judge_calls"]
        == 0,
        "Scope violation",
    )
    prior = read(REPO / "provenance/pilots/v15_5_native_answer_20261010/raw/REPORT.json")
    expected_base = prior["base_state_sha256_before"]
    initial, retained = (
        prior["results"][0]["initial_state_sha256"],
        prior["results"][0]["final_state_sha256"],
    )
    states, completed_pairs, forwards = {}, 0, 0
    for state, state_hash in zip(STATES, (initial, retained), strict=True):
        observed, forward_rows = [], 0
        for world, query in PAIRS:
            prefix = f"{state}_w{world}q{query}"
            forward_path, pair_path = raw / f"{prefix}_FORWARD.json", raw / f"{prefix}.json"
            if forward_path.exists():
                forward = read(forward_path)
                require(
                    (forward["world"], forward["query"]) == (world, query), "Forward coordinate"
                )
                forward_rows += 1
            if pair_path.exists():
                require(forward_path.exists(), "Backward receipt missing forward")
                row = read(pair_path)
                require((row["world"], row["query"]) == (world, query), "Pair coordinate")
                require(
                    row["components"] == forward["components"] and row["loss"] == forward["loss"],
                    "Forward/backward scalar mismatch",
                )
                coverage = gradients(row["gradients"])
                route_summary = {}
                for route, count in (
                    ("context_to_writer", 3),
                    ("query_or_completion", 3),
                    ("query_to_reader", 5),
                ):
                    subset = [r for r in row["route_gradients"] if r["route"] == route]
                    require(
                        len(subset) == count and all(r["backward_calls"] == 1 for r in subset),
                        "Gradient route accounting",
                    )
                    route_summary[route] = {
                        "observations": count,
                        "nonzero": sum(r["nonzero_elements"] > 0 for r in subset),
                        "l2": [r["l2"] for r in subset],
                    }
                observed.append(
                    {
                        "world": world,
                        "query": query,
                        "coverage": coverage,
                        "routes": route_summary,
                        "loss": row["loss"],
                        "peak_cpu_total_bytes": row["spill"]["peak_cpu_total_bytes"],
                    }
                )
        forwards += forward_rows
        completed_pairs += len(observed)
        state_path = raw / f"{state}.json"
        state_complete = state_path.exists()
        if state_complete:
            value = read(state_path)
            require(value["before_sha256"] == value["after_sha256"] == state_hash, "Bridge changed")
            require(value["pairs"] == [list(p) for p in PAIRS], "Pair plan")
            require(
                value["restore"]["spill_count"] == 3 and len(observed) == forward_rows == 3,
                "Window completeness",
            )
            require(value["restore"]["live_cpu_buffer_count"] == 0, "Live buffers after restore")
            coverage = gradients(value["accumulated_gradients"])
            checks = value["cpu_reference_exact"]
            require(
                {r["name"] for r in checks} == {r["name"] for r in value["accumulated_gradients"]}
                and len(checks) == 317
                and all(r["exact"] for r in checks),
                "CPU reference accounting",
            )
            parity = read(raw / f"{state}_PARITY.json")["rows"]
            require(parity == value["parity"] and len(parity) == 3, "Parity accounting")
            require(
                all(
                    r["ordinary_zero_full_logits_exact"]
                    and r["written_zero_full_logits_exact"]
                    and r["historical_scores_exact"]
                    for r in parity
                ),
                "Native parity",
            )
        states[state] = {
            "complete": state_complete,
            "backward_pairs": observed,
            "forward_pairs": forward_rows,
        }
    if complete:
        require(started_path.exists() and terminal["states"] == list(STATES), "States incomplete")
        require(
            terminal["base_sha256_before"] == terminal["base_sha256_after"] == expected_base,
            "Base changed",
        )
        require(all(s["complete"] for s in states.values()), "Missing state receipt")
        require(terminal["optimizer_constructed"] is False, "Unexpected optimizer")
        require(terminal["old_expression_gate"] == "FAIL" and terminal["winner"] == "none", "Claim")
    summary = {
        "status": "VERIFIED_NO_STEP_RECEIPTS" if complete else "VERIFIED_BOUNDED_FAILURE_RECEIPTS",
        "source_commit": seal["source_commit"],
        "source_files_checked": len(seal["source_hashes"]),
        "terminal_status": terminal["status"],
        "planned_states": 2,
        "planned_backward_pairs": 6,
        "completed_backward_pairs": completed_pairs,
        "completed_forward_pairs": forwards,
        "states": states,
        "optimizer_steps": 0,
        "new_generations": 0,
        "new_judge_calls": 0,
        "elapsed_seconds": terminal["elapsed_seconds"],
        "peak_cuda_allocated_gib": (
            terminal["peak_cuda_allocated_bytes"] / 2**30
            if "peak_cuda_allocated_bytes" in terminal
            else None
        ),
        "peak_cuda_reserved_gib": (
            terminal["peak_cuda_reserved_bytes"] / 2**30
            if "peak_cuda_reserved_bytes" in terminal
            else None
        ),
        "old_expression_gate": "FAIL",
        "winner": "none",
        "non_regression": "NOT_ESTABLISHED",
        "scope": "identity/scalar/receipt replay; not independent model or gradient recomputation",
        "full_16_pair_window": "NOT_TESTED",
        "gpu_add_gradient_oracle": "NOT_TESTED",
    }
    for name in ("RESOURCES.jsonl", "HOST_RESOURCES.jsonl"):
        path = raw / name
        if path.exists():
            for line in path.read_text().splitlines():
                finite(json.loads(line))
    index = {str(p.relative_to(BUNDLE)): sha(p) for p in sorted(raw.iterdir()) if p.is_file()}
    return summary, index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    summary, index = build()
    if args.write:
        require(
            not any((BUNDLE / name).exists() for name in ("SUMMARY.json", "ARTIFACT_INDEX.json")),
            "Derived artifacts already exist",
        )
    for name, value in (("SUMMARY.json", summary), ("ARTIFACT_INDEX.json", index)):
        text = json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
        if args.write:
            with (BUNDLE / name).open("x") as stream:
                stream.write(text)
        else:
            require((BUNDLE / name).read_text() == text, f"Replay differs: {name}")
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "status",
                    "terminal_status",
                    "completed_backward_pairs",
                    "planned_backward_pairs",
                    "optimizer_steps",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
