#!/usr/bin/env python3
"""Offline source/artifact/case-coordinate replay for the v2 checkpoint repair."""

import argparse
import itertools
import json
import math
from pathlib import Path

import verify_v15_adapter_cuda_recovery as recovery
import verify_v15_adapter_owner as old
from verify_v15_adapter_owner import read, receipt, require, write_new

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "provenance/pilots/v15_adapter_owner_v2_20261014"
PLAN = "configs/v15/ADAPTER_OWNER_V2_QUALIFICATION_PLAN.json"
SOURCE = "8359635cc443271407763601fc3c619cc79777f4"
PASS = "SYNTHETIC_CHECKPOINT_V2_PASS_NOT_7B_QUALIFICATION"


def expected_cases():
    cases = old.expected_cases()
    module = "tests.test_adapter_native_learner_v2"
    boolean, dtype = ("False", "True"), ("dtype0", "dtype1")

    def add(name, *axes):
        for values in itertools.product(*axes):
            suffix = "[" + "-".join(values) + "]" if values else ""
            cases.add((module, name + suffix))

    for name in ("test_v2_matched_two_window_updates", "test_v2_serialized_next_update_and_rng"):
        add(name, boolean, boolean, dtype)
    add("test_retained_snapshot_survives_owner_update_and_metadata_edit", dtype, boolean)
    add("test_snapshot_mutation_cannot_change_any_owner_state_or_caller_metadata", boolean)
    failures = (
        "receipt",
        "old_format",
        "metadata",
        "execution",
        "reader",
        "run_contract",
        "base_aliases",
        "native_schema",
        "boundary",
        "completed_steps",
        "reference_role",
        "current_base_sha",
        "buffer",
        "bridge_keys",
        "bridge_shape",
        "bridge_dtype",
        "nonfinite",
        "bridge_policy",
        "bridge_ids",
        "bridge_coverage",
        "bridge_moment",
        "bridge_step",
        "bridge_negative_variance",
        "base_policy",
        "base_masters",
        "rng_keys",
        "rng_python",
        "rng_numpy",
        "rng_cpu",
        "rng_cuda",
    )
    add(
        "test_rejected_restore_leaves_values_versions_pointers_guards_rng_unchanged",
        boolean,
        failures,
    )
    add("test_step_zero_payload_restores_without_inventing_optimizer_state", boolean)
    for name in (
        "test_snapshot_detaches_nonleaf_metadata_and_deep_copies_containers",
        "test_historical_snapshot_negative_control_detects_original_alias",
        "test_historical_restore_negative_control_detects_original_target_mutation",
        "test_persistent_and_nonpersistent_buffers_are_snapshot_owned",
    ):
        add(name)
    add(
        "test_base_optimizer_malformed_state_rejected_before_target_write",
        ("shape", "dtype", "step", "negative", "keys"),
    )
    require(len(cases) == 164, "Verifier coordinate contract")
    return cases


def artifacts(bundle):
    paths = [bundle / "SOURCE_SEAL.json", bundle / "REGRESSIONS.xml", *(bundle / "raw").rglob("*")]
    return {str(p.relative_to(bundle)): receipt(p) for p in sorted(paths) if p.is_file()}


def replay(bundle):
    # Re-check historical bytes; the old review-open summary remains historical.
    recovery.replay(recovery.DEFAULT)
    seal, plan = read(bundle / "SOURCE_SEAL.json"), read(ROOT / PLAN)
    require(
        seal["source_commit"] == SOURCE and len(seal["source_hashes"]) == 306,
        "V2 execution source identity",
    )
    for name, digest in seal["source_hashes"].items():
        require(receipt(ROOT / name)["sha256"] == digest, f"Source changed: {name}")
    require(plan["expected_test_cases"] == 164 and plan["v2_tests"] == 93, "Plan denominator")
    require({p.name for p in (bundle / "raw").iterdir()} == {"cpu", "cuda"}, "Runtime coverage")
    runs = {}
    for device in ("cpu", "cuda"):
        folder = bundle / "raw" / device
        start, end = read(folder / "STARTED.json"), read(folder / "FINISHED.json")
        require(
            {p.name for p in folder.iterdir()} == {"STARTED.json", "TESTS.xml", "FINISHED.json"},
            "Raw artifact coverage",
        )
        require(all(start[k] == v for k, v in seal.items()), "Started source mismatch")
        require(start["plan"] == plan, "Started plan mismatch")
        require(start["device"] == end["device"] == device, "Runtime device mismatch")
        guard = start["source_check"]
        require(
            guard["source_commit"] == SOURCE
            and guard["source_files"] == 306
            and guard["isolated_python"] is True
            and guard["fresh_bytecode_cache"] is True
            and guard["untracked_check"] == "all",
            "Pre-import guard mismatch",
        )
        require(set(end["files"]) == {"STARTED.json", "TESTS.xml"}, "Terminal coverage")
        for name, expected in end["files"].items():
            require(receipt(folder / name) == expected, f"Raw file changed: {device}/{name}")
        counts, coordinates, controls, failures = old.tests(folder / "TESTS.xml")
        require(
            counts == end["counts"] == dict(tests=164, failures=0, errors=0, skipped=0)
            and coordinates == expected_cases()
            and not failures,
            "Incomplete test coverage",
        )
        require(
            end["status"] == PASS and end["pytest_exit_code"] == 0 and not end.get("error"),
            "No passing terminal receipt",
        )
        require(
            len(controls) == 4 and all(c["loss_exact"] is True for c in controls),
            "Historical graph negative controls",
        )
        require(
            all(
                end[k] == 0
                for k in ("real_model_updates", "new_sequences", "judge_calls", "weight_deletions")
            )
            and end["old_expression_gate"] == "FAIL"
            and end["winner"] == "none",
            "Scope/claim changed",
        )
        require(
            end["imported_project_sources"]
            and all(p in seal["source_hashes"] for p in end["imported_project_sources"].values()),
            "Imported source mismatch",
        )
        require(
            math.isfinite(end["elapsed_seconds"]) and 0 < end["elapsed_seconds"] <= 180,
            "Wall envelope",
        )
        peak = end["peak_cuda_allocated_bytes"]
        require(
            (device == "cpu" and peak is None)
            or (device == "cuda" and type(peak) is int and 0 < peak <= 6 * 2**30),
            "Allocation envelope",
        )
        runs[device] = {
            "counts": counts,
            "new_v2_cases": 93,
            "v2_matched_update_cells": 8,
            "v2_serialized_replay_cells": 8,
            "nonmutating_rejections": 65,
            "historical_checkpoint_defect_controls": 2,
            "elapsed_seconds": end["elapsed_seconds"],
            "peak_cuda_allocated_bytes": peak,
            "runtime": end["runtime"],
        }
    regression_counts, regression_cases, _, regression_failures = old.tests(
        bundle / "REGRESSIONS.xml"
    )
    require(
        regression_counts == dict(tests=609, failures=0, errors=0, skipped=0)
        and len(regression_cases) == 609
        and not regression_failures,
        "Local regression denominator/failure",
    )
    return {
        "schema": "v15-checkpoint-v2-replay-v1",
        "source_commit": SOURCE,
        "source_files": 306,
        "status": "TINY_CHECKPOINT_V2_REPAIR_PASS_NOT_7B_QUALIFICATION",
        "runs": runs,
        "additional_local_regression_counts": regression_counts,
        "old_source_and_failure_preserved": True,
        "old_expression_gate": "FAIL",
        "winner": "none",
        "non_regression": "NOT_ESTABLISHED",
        "real_model_updates": 0,
        "new_sequences": 0,
        "judge_calls": 0,
        "weight_deletions": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("write", "verify"))
    parser.add_argument("--bundle", type=Path, default=DEFAULT)
    args = parser.parse_args()
    value, index = replay(args.bundle), artifacts(args.bundle)
    if args.command == "write":
        require(
            not (args.bundle / "SUMMARY.json").exists()
            and not (args.bundle / "ARTIFACT_INDEX.json").exists(),
            "Outputs already exist",
        )
        write_new(args.bundle / "SUMMARY.json", value)
        write_new(args.bundle / "ARTIFACT_INDEX.json", index)
    else:
        require(value == read(args.bundle / "SUMMARY.json"), "Summary mismatch")
        require(index == read(args.bundle / "ARTIFACT_INDEX.json"), "Artifact index mismatch")
    print(json.dumps(value, sort_keys=True))


if __name__ == "__main__":
    main()
