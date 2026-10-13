#!/usr/bin/env python3
"""Offline replay of source-bound tiny-model qualification, including failures."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "provenance/pilots/v15_adapter_owner_20261013"
PASS = "SYNTHETIC_ENGINEERING_PASS_NOT_7B_QUALIFICATION"
PLAN = "configs/v15/ADAPTER_OWNER_QUALIFICATION_PLAN.json"


def read(path):
    return json.loads(path.read_text())


def receipt(path):
    return {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def require(value, message):
    if not value:
        raise ValueError(message)


def write_new(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def expected_cases():
    """Coordinates from the sealed two test files, not a successful-row filter."""
    result = set()

    def add(module, name, *axes):
        for parts in itertools.product(*axes):
            suffix = f"[{'-'.join(parts)}]" if parts else ""
            result.add((module, name + suffix))

    first, second = "tests.test_training_readout", "tests.test_adapter_native_learner"
    boolean, dtype = ("False", "True"), ("dtype0", "dtype1")
    family = ("mistral", "gpt2", "olmo2", "gemma2")
    add(
        first,
        "test_complete_pair_loss_and_every_gradient_matches_historical",
        ("0", "2"),
        boolean,
        dtype,
    )
    add(first, "test_prepared_zero_and_nonzero_keep_native_outer_transform", dtype, family)
    add(
        first,
        "test_new_backend_all_gradients_against_independent_native_hook_reference",
        boolean,
        dtype,
        family,
    )
    add(first, "test_independent_forward_negative_control_localizes_graph_rounding", boolean, dtype)
    for name in (
        "test_scopes_reject_missing_preparation_recursion_concurrency_and_updates",
        "test_mode_and_buffer_changes_are_not_a_paired_intervention",
        "test_mixed_submodule_dropout_and_global_hooks_are_rejected",
        "test_no_grad_preparation_cannot_be_relabelled_live_and_scope_cleans_on_error",
    ):
        add(first, name)
    for name in (
        "test_matched_windows_equal_legacy_base_bridge_master_and_optimizer",
        "test_saved_next_update_exact_including_all_owned_state_and_rng",
    ):
        add(second, name, boolean, boolean, dtype)
    add(
        second,
        "test_live_policy_mutations_fail_before_begin_window",
        ("mode", "checkpointing", "reader", "optimizer", "run", "buffer", "pipeline"),
    )
    add(
        second,
        "test_resume_fails_closed_for_wrong_contract_or_state",
        (
            "receipt",
            "metadata",
            "execution",
            "optimizer",
            "reference",
            "buffer",
            "original_weights",
        ),
    )
    add(second, "test_window_boundaries_and_frozen_original_identity")
    require(len(result) == 71, "Verifier case contract")
    return result


def tests(path):
    root = ElementTree.parse(path).getroot()
    cases = list(root.iter("testcase"))
    coordinates = [(c.attrib["classname"], c.attrib["name"]) for c in cases]
    require(len(set(coordinates)) == len(coordinates), "Duplicate test coordinate")
    counts = {
        "tests": len(cases),
        "failures": sum(c.find("failure") is not None for c in cases),
        "errors": sum(c.find("error") is not None for c in cases),
        "skipped": sum(c.find("skipped") is not None for c in cases),
    }
    suites = list(root.iter("testsuite"))
    require(
        counts == {key: sum(int(s.attrib.get(key, 0)) for s in suites) for key in counts},
        "JUnit denominator disagreement",
    )
    failures = [
        {"case": c.attrib["name"], "kind": tag, "message": c.find(tag).attrib.get("message", "")}
        for c in cases
        for tag in ("failure", "error", "skipped")
        if c.find(tag) is not None
    ]
    controls = [
        json.loads(p.attrib["value"])
        for p in root.iter("property")
        if p.attrib["name"] == "negative_control"
    ]
    return counts, set(coordinates), controls, failures


def replay(bundle):
    seal, inventory = read(bundle / "SOURCE_SEAL.json"), read(bundle / "RUNS.json")
    require(len(seal["source_hashes"]) == 299, "Frozen source denominator")
    for name, digest in seal["source_hashes"].items():
        require(receipt(ROOT / name)["sha256"] == digest, f"Sealed source changed: {name}")
    plan = read(ROOT / PLAN)
    require(set(inventory) >= {"cpu", "cuda"}, "Original attempts must remain visible")
    require(set(inventory) == {p.name for p in (bundle / "raw").iterdir()}, "Attempt inventory")
    runs = {}
    for name, intent in inventory.items():
        path = bundle / "raw" / name
        start, end = read(path / "STARTED.json"), read(path / "FINISHED.json")
        require(all(start[k] == seal[k] for k in seal), "Execution source mismatch")
        require(start["plan"] == plan, "Execution plan mismatch")
        require(start["device"] == end["device"] == intent["device"], "Device mismatch")
        guard = start["source_check"]
        require(
            guard["source_commit"] == seal["source_commit"]
            and guard["source_files"] == 299
            and guard["untracked_check"] == "all"
            and guard["isolated_python"] is True
            and guard["fresh_bytecode_cache"] is True,
            "Pre-import source guard missing",
        )
        require(
            set(end["files"]) == {p.name for p in path.iterdir()} - {"FINISHED.json"},
            "Terminal file coverage",
        )
        for filename, expected in end["files"].items():
            require(
                receipt(path / filename) == expected, f"Raw artifact changed: {name}/{filename}"
            )
        require(
            all(
                end[k] == 0
                for k in ("real_model_updates", "new_sequences", "judge_calls", "weight_deletions")
            )
            and end["old_expression_gate"] == "FAIL"
            and end["winner"] == "none",
            "Execution scope/claim drift",
        )
        row = {
            "device": end["device"],
            "status": end["status"],
            "elapsed_seconds": end["elapsed_seconds"],
            "peak_cuda_allocated_bytes": end.get("peak_cuda_allocated_bytes"),
            "runtime": end.get("runtime"),
            "error": end.get("error"),
            "negative_controls": [],
            "counts": {"tests": 0, "failures": 0, "errors": 0, "skipped": 0},
            "test_failures": [],
            "matched_update_conditions_passed": 0,
            "exact_resume_conditions_passed": 0,
        }
        if (path / "TESTS.xml").exists():
            counts, coordinates, controls, failures = tests(path / "TESTS.xml")
            require(counts == end["counts"], "Terminal/JUnit disagreement")
            require(coordinates <= expected_cases(), "Unexpected test case")
            row.update(counts=counts, test_failures=failures)
            if end["status"] == PASS:
                require(
                    coordinates == expected_cases()
                    and counts == {"tests": 71, "failures": 0, "errors": 0, "skipped": 0}
                    and end["pytest_exit_code"] == 0,
                    "Incomplete qualification cannot pass",
                )
                require(len(controls) == 4, "Missing negative controls")
                require(
                    {(c["full_update"], c["dtype"]) for c in controls}
                    == set(itertools.product((False, True), ("torch.float32", "torch.bfloat16"))),
                    "Negative-control coverage",
                )
                for control in controls:
                    differences = control["gradient_differences"]
                    require(control["loss_exact"] is True, "Negative loss control")
                    require(control["device"].split(":")[0] == end["device"], "Control device")
                    require(
                        control["eligible_tensors"] == (47 if control["full_update"] else 26),
                        "Gradient denominator",
                    )
                    require(bool(differences) == control["full_update"], "Negative-control outcome")
                    if end["device"] == "cpu":
                        require(
                            len(differences) == (20 if control["full_update"] else 0),
                            "CPU control tensor count",
                        )
                    require(
                        len({d["name"] for d in differences}) == len(differences),
                        "Duplicate gradient tensor",
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
                    row["negative_controls"].append(
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
                require(end["imported_project_sources"], "Imported source receipts missing")
                require(
                    all(
                        p in seal["source_hashes"] for p in end["imported_project_sources"].values()
                    ),
                    "Unsealed project import",
                )
                if end["device"] == "cuda":
                    require(
                        0
                        < end["peak_cuda_allocated_bytes"]
                        <= plan["gpu_memory_limit_gib"] * 2**30,
                        "GPU allocation ceiling",
                    )
                row.update(matched_update_conditions_passed=8, exact_resume_conditions_passed=8)
        else:
            require(end["status"] == "FAILED" and end.get("error"), "Missing tests cannot pass")
        runs[name] = row
    require(runs["cpu"]["status"] == PASS, "Frozen CPU result changed")
    require(
        runs["cuda"]["status"] == "FAILED"
        and runs["cuda"]["error"] == "ModuleNotFoundError: No module named 'pytest'"
        and runs["cuda"]["counts"]["tests"] == 0,
        "Original CUDA environment failure must remain visible",
    )
    cuda_pass = any(r["device"] == "cuda" and r["status"] == PASS for r in runs.values())
    return {
        "schema": "v15-adapter-owner-offline-qualification-v1",
        "source_commit": seal["source_commit"],
        "source_files": len(seal["source_hashes"]),
        "status": "CPU_CUDA_SYNTHETIC_QUALIFIED"
        if cuda_pass
        else "CPU_SYNTHETIC_QUALIFIED_CUDA_NOT_QUALIFIED",
        "runs": runs,
        "real_model_updates": 0,
        "new_sequences": 0,
        "judge_calls": 0,
        "weight_deletions": 0,
        "old_expression_gate": "FAIL",
        "winner": "none",
        "non_regression": "NOT_ESTABLISHED",
        "claim_ceiling": (
            "Per-runtime tiny engineering comparisons; not cross-device bit equality "
            "or 7B/model-quality qualification"
        ),
    }


def artifacts(bundle):
    files = [bundle / "SOURCE_SEAL.json", bundle / "RUNS.json", *(bundle / "raw").rglob("*")]
    return {str(p.relative_to(bundle)): receipt(p) for p in sorted(files) if p.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("write-analysis", "verify"))
    parser.add_argument("--bundle", type=Path, default=DEFAULT)
    args = parser.parse_args()
    result = replay(args.bundle)
    index = artifacts(args.bundle)
    if args.command == "write-analysis":
        require(
            not (args.bundle / "ARTIFACT_INDEX.json").exists()
            and not (args.bundle / "SUMMARY.json").exists(),
            "Analysis already exists",
        )
        write_new(args.bundle / "ARTIFACT_INDEX.json", index)
        write_new(args.bundle / "SUMMARY.json", result)
    else:
        require(read(args.bundle / "ARTIFACT_INDEX.json") == index, "Artifact index mismatch")
        require(
            read(args.bundle / "SUMMARY.json") == result, "Stored summary differs from raw replay"
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
