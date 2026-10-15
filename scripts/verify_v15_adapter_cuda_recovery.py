#!/usr/bin/env python3
"""Offline replay of the authorized CUDA attempt; original records stay immutable."""

from __future__ import annotations

import argparse
import itertools
import json
import math
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import verify_v15_adapter_owner as original
from verify_v15_adapter_owner import read, receipt, require, write_new

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "provenance/pilots/v15_adapter_owner_cuda_02_20261013"


def file_index(folder):
    return {
        str(p.relative_to(folder)): receipt(p)
        for p in sorted(folder.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


def artifacts(bundle):
    paths = [bundle / "EXECUTION_DECISION.json", bundle / "SOURCE_SEAL.json"]
    paths.extend((bundle / "cuda_attempt02").iterdir())
    return {str(p.relative_to(bundle)): receipt(p) for p in sorted(paths) if p.is_file()}


def replay(bundle):
    old = original.replay(original.DEFAULT)
    require(old == read(original.DEFAULT / "SUMMARY.json"), "Historical summary changed")
    require(
        original.artifacts(original.DEFAULT) == read(original.DEFAULT / "ARTIFACT_INDEX.json"),
        "Historical artifacts changed",
    )
    seal = read(bundle / "SOURCE_SEAL.json")
    require(seal == read(original.DEFAULT / "SOURCE_SEAL.json"), "Recovery changed source seal")
    decision = read(bundle / "EXECUTION_DECISION.json")
    require(
        decision["schema"] == "v15-adapter-owner-cuda-recovery-decision-v1"
        and decision["source_commit"] == seal["source_commit"]
        and decision["source_and_tests_changed"] is False
        and decision["expected_test_cases"] == 71
        and decision["max_cuda_allocated_gib"] == 6
        and decision["wall_limit_seconds"] == 180,
        "Recovery scope changed",
    )
    raw = bundle / "cuda_attempt02"
    start, end = read(raw / "STARTED.json"), read(raw / "FINISHED.json")
    require(all(start[k] == seal[k] for k in seal), "Execution seal mismatch")
    require(start["plan"] == read(ROOT / original.PLAN), "Execution plan mismatch")
    require(start["device"] == end["device"] == "cuda", "Device mismatch")
    guard = start["source_check"]
    require(
        guard["source_commit"] == seal["source_commit"]
        and guard["source_files"] == 299
        and guard["untracked_check"] == "all"
        and guard["isolated_python"] is True
        and guard["fresh_bytecode_cache"] is True,
        "Pre-import guard mismatch",
    )
    require(
        set(p.name for p in raw.iterdir()) == {"STARTED.json", "FINISHED.json", "TESTS.xml"},
        "Raw file coverage",
    )
    require(set(end["files"]) == {"STARTED.json", "TESTS.xml"}, "Terminal file coverage")
    for name, expected in end["files"].items():
        require(receipt(raw / name) == expected, f"Raw artifact changed: {name}")
    require(
        end["status"] == original.PASS and end["pytest_exit_code"] == 0 and not end.get("error"),
        "Not a successful qualification",
    )
    require(
        all(
            end[k] == decision[k] == 0
            for k in ("real_model_updates", "new_sequences", "judge_calls", "weight_deletions")
        )
        and end["old_expression_gate"] == "FAIL"
        and end["winner"] == "none",
        "Scope or claim drift",
    )
    require(
        all(
            end["runtime"][k] == decision["runtime"][k]
            for k in ("python", "torch", "transformers", "pytest")
        ),
        "Runtime differs from decision",
    )
    require(
        start["python"] == end["runtime"]["python"] and end["runtime"]["cuda"] == "13.2",
        "Runtime mismatch",
    )
    counts, coordinates, controls, failures = original.tests(raw / "TESTS.xml")
    require(
        counts == end["counts"] == dict(tests=71, failures=0, errors=0, skipped=0), "Test counts"
    )
    require(coordinates == original.expected_cases() and not failures, "Test coverage")
    require(
        len(controls) == 4
        and {(c["full_update"], c["dtype"]) for c in controls}
        == set(itertools.product((False, True), ("torch.float32", "torch.bfloat16"))),
        "Negative control coverage",
    )
    control_rows = []
    for control in controls:
        differences = control["gradient_differences"]
        require(
            control["device"] == "cuda:0" and control["loss_exact"] is True,
            "Negative control device/loss",
        )
        require(
            control["eligible_tensors"] == (47 if control["full_update"] else 26),
            "Gradient denominator",
        )
        require(bool(differences) == control["full_update"], "Negative-control direction")
        require(
            len({d["name"] for d in differences}) == len(differences), "Duplicate gradient tensor"
        )
        require(
            all(
                d["name"].startswith("base.")
                and type(d["different_elements"]) is int
                and d["different_elements"] > 0
                and math.isfinite(d["max_abs"])
                and d["max_abs"] > 0
                for d in differences
            ),
            "Gradient control receipt",
        )
        control_rows.append(
            {
                **{
                    k: control[k]
                    for k in ("dtype", "full_update", "eligible_tensors", "loss_exact")
                },
                "different_base_tensors": len(differences),
                "different_bridge_tensors": 0,
                "max_abs": max((d["max_abs"] for d in differences), default=0.0),
            }
        )
    require(
        end["imported_project_sources"]
        and all(p in seal["source_hashes"] for p in end["imported_project_sources"].values()),
        "Imported source mismatch",
    )
    peak, elapsed = end["peak_cuda_allocated_bytes"], end["elapsed_seconds"]
    require(type(peak) is int and 0 < peak <= 6 * 2**30, "Allocation envelope")
    require(math.isfinite(elapsed) and 0 < elapsed <= 180, "Elapsed envelope")
    suite = next(ElementTree.parse(raw / "TESTS.xml").getroot().iter("testsuite"))
    timestamp = datetime.fromisoformat(suite.attrib["timestamp"])
    require(timestamp.tzinfo is not None, "Ambiguous test timestamp")
    return {
        "schema": "v15-adapter-owner-cuda-recovery-offline-v1",
        "status": "CPU_CUDA_TINY_UPDATE_REPLAY_PASS_REVIEW_FINDINGS_OPEN",
        "source_commit": seal["source_commit"],
        "source_files": 299,
        "original_environment_failure_preserved": True,
        "execution_started_jst": timestamp.astimezone(ZoneInfo("Asia/Tokyo")).isoformat(),
        "cuda": {
            "counts": counts,
            "matched_update_conditions_passed": 8,
            "exact_resume_conditions_passed": 8,
            "negative_controls": control_rows,
            "elapsed_seconds": elapsed,
            "pytest_seconds": float(suite.attrib["time"]),
            "peak_cuda_allocated_bytes": peak,
            "peak_cuda_allocated_mib": peak / 2**20,
            "runtime": end["runtime"],
        },
        "cpu_counts": old["runs"]["cpu"]["counts"],
        "review_findings_open": decision["known_review_findings_before_dispatch"],
        "review_findings_closed_by_this_run": 0,
        "real_model_updates": 0,
        "new_sequences": 0,
        "judge_calls": 0,
        "weight_deletions": 0,
        "old_expression_gate": "FAIL",
        "winner": "none",
        "non_regression": "NOT_ESTABLISHED",
        "claim_ceiling": (
            "Tiny per-runtime update and valid serialized-resume parity; "
            "not snapshot immutability, restore atomicity, cross-device equality, "
            "7B or semantic qualification"
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("write-analysis", "verify"))
    parser.add_argument("--bundle", type=Path, default=DEFAULT)
    args = parser.parse_args()
    result, index, old_index = (
        replay(args.bundle),
        artifacts(args.bundle),
        file_index(original.DEFAULT),
    )
    outputs = {
        "SUMMARY.json": result,
        "ARTIFACT_INDEX.json": index,
        "ORIGINAL_BUNDLE_INDEX.json": old_index,
    }
    if args.command == "write-analysis":
        require(
            not any((args.bundle / name).exists() for name in outputs), "Analysis already exists"
        )
        for name, value in outputs.items():
            write_new(args.bundle / name, value)
    else:
        for name, value in outputs.items():
            require(read(args.bundle / name) == value, f"Published artifact differs: {name}")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
