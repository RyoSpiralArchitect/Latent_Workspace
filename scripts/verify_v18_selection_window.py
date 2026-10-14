#!/usr/bin/env python3
"""Offline source/file/receipt verification; no model or checkpoint execution."""

import argparse
import importlib.util
import json
import re
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "selection_window_receipt_contract",
    Path(__file__).with_name("qualify_v18_selection_window.py"),
)
CONTRACT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CONTRACT)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def same(left, right):
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(
        right, sort_keys=True, allow_nan=False,
    )


def read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate JSON field")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError(f"Nonfinite JSON: {value}")
    return json.loads(path.read_text(), object_pairs_hook=unique, parse_constant=invalid)


def file_manifest(folder, expected):
    require(type(expected) is dict, "Manifest mapping required")
    for name, item in expected.items():
        pure = PurePosixPath(name)
        require(str(pure) == name and not pure.is_absolute() and ".." not in pure.parts,
                "Invalid manifest path")
        path = folder / name
        require(path.is_file() and not path.is_symlink(), "Missing/nonregular artifact")
        require(path.resolve().is_relative_to(folder.resolve()), "Artifact escaped bundle")
        require(same(item, {"bytes": path.stat().st_size, "sha256": CONTRACT.digest(path)}),
                f"Artifact hash mismatch: {name}")
    actual = set(CONTRACT.files(folder)) - {"FINISHED.json"}
    require(actual == set(expected), "Missing/extra terminal artifact")


def verify(bundle, seal_path, repo=ROOT):
    seal = read(seal_path)
    require(set(seal) == {"source_commit", "source_hashes"}
            and re.fullmatch(r"[0-9a-f]{40}", seal["source_commit"]), "Source seal schema")
    require(CONTRACT.CRITICAL | {CONTRACT.ENTRY, "scripts/run_source_sealed.py",
                                "scripts/verify_v18_selection_window.py"}
            <= set(seal["source_hashes"]), "Critical source missing")
    for name, sha in seal["source_hashes"].items():
        pure = PurePosixPath(name)
        require(not pure.is_absolute() and ".." not in pure.parts and str(pure) == name,
                "Invalid source path")
        path = repo / name
        require(path.resolve().is_relative_to(repo.resolve()) and not path.is_symlink(),
                "Source escaped checkout")
        require(CONTRACT.digest(path) == sha, f"Source content changed: {name}")
    started, finished = read(bundle / "STARTED.json"), read(bundle / "FINISHED.json")
    require(same(started["source_seal"], seal), "Coordinator seal mismatch")
    require(same(started["plan"], CONTRACT.PLAN) and same(finished["plan"], CONTRACT.PLAN),
            "Frozen plan mismatch")
    require(finished["status"] == CONTRACT.PASS, "Qualification incomplete/failed")
    device = started["device"]
    require(device in ("cpu", "cuda") and device == finished["device"], "Device mismatch")
    check = {"schema": "pre-import-source-check-v1", "source_commit": seal["source_commit"],
             "entry": CONTRACT.ENTRY, "source_files": len(seal["source_hashes"]),
             "untracked_check": "all", "isolated_python": True, "fresh_bytecode_cache": True}
    require(same(started["source_check"], check), "Coordinator source admission mismatch")
    file_manifest(bundle, finished["files"])
    jobs = [("tests", -1, "tests")]
    jobs += [(role, i, f"case-{i:02d}/{role}") for i in range(len(CONTRACT.CASES))
             for role in ("producer", "resumer")]
    require(len(finished["children"]) == len(jobs), "Incomplete child population")
    pids, launches, receipts = set(), set(), {}
    for entry, (role, i, path) in zip(finished["children"], jobs, strict=True):
        require(set(entry) == {"role", "case_index", "relative_path", "launcher_pid", "returncode"},
                "Child dispatch fields")
        require((entry["role"], entry["case_index"], entry["relative_path"]) == (role, i, path)
                and type(entry["returncode"]) is int and entry["returncode"] == 0,
                "Wrong/failed/reordered child")
        require(type(entry["launcher_pid"]) is int and entry["launcher_pid"] > 0,
                "Invalid launcher PID")
        launches.add(entry["launcher_pid"])
        folder = bundle / path
        child_start, child_end = read(folder / "STARTED.json"), read(folder / "FINISHED.json")
        require(same(child_start["source_check"], check)
                and same(child_start["plan"], CONTRACT.PLAN), "Child source/plan mismatch")
        require(child_start["role"] == child_end["role"] == role
                and child_start["device"] == child_end["device"] == device
                and child_start["case_index"] == child_end["case_index"] == i
                and child_start["pid"] == child_end["pid"]
                and type(child_end["pid"]) is int and child_end["pid"] > 0
                and child_end["status"] == "PASS", "Child identity/outcome mismatch")
        pids.add(child_end["pid"])
        file_manifest(folder, child_end["files"])
        require(CONTRACT.CRITICAL <= set(child_end["imported_sources"].values())
                <= set(seal["source_hashes"]), "Incomplete imported source evidence")
        runtime = child_end["runtime"]
        require(runtime["device"] == device and runtime["threads"] == 2
                and runtime["interop_threads"] == 1 and runtime["tf32"] is False,
                "Runtime/thread/TF32 policy mismatch")
        require(0 <= child_end["elapsed_seconds"] <= (600 if role == "tests" else 60),
                "Child elapsed bound")
        peak = child_end["peak_cuda_allocated_bytes"]
        require((type(peak) is int and 0 < peak <= 4 * 2**30) if device == "cuda"
                else peak is None, "CUDA budget receipt mismatch")
        if role == "tests":
            require(child_end["pytest_exit_code"] == 0, "Unit exit mismatch")
            require(same(child_end["counts"], CONTRACT.test_report(folder / "TESTS.xml")),
                    "Unit count mismatch")
        else:
            require(same(child_end["case"], CONTRACT.CASES[i]), "Wrong restart case")
            require(child_end["window2"]["completed_steps"] == 2, "Incomplete restart window")
        receipts[(role, i)] = child_end
    require(len(pids) == len(launches) == len(jobs), "Child process reuse")
    for i in range(len(CONTRACT.CASES)):
        producer, resumer = receipts[("producer", i)], receipts[("resumer", i)]
        checkpoint = bundle / f"case-{i:02d}/producer/window1.pt"
        require(same(producer["window2"], resumer["window2"])
                and same(producer["runtime"], resumer["runtime"]), "Restart result differs")
        require(resumer["producer_pid"] == producer["pid"]
                and resumer["checkpoint_payload_unchanged"] is True, "Restart ownership receipt")
        require(producer["checkpoint_file_sha256"] == resumer["checkpoint_file_sha256"]
                == CONTRACT.digest(checkpoint)
                and producer["checkpoint_receipt"]["bytes"] == checkpoint.stat().st_size
                and producer["checkpoint_receipt"]["completed_steps"] == 1
                and producer["checkpoint_receipt"]["format"]
                == "v18-selection-window-reference-resume-v1", "Checkpoint binding mismatch")
    require(0 <= finished["elapsed_seconds"] <= CONTRACT.PLAN["wall_seconds_per_device"],
            "Coordinator elapsed bound")
    return {"status": "OFFLINE_SOURCE_AND_RECEIPT_PASS", "device": device,
            "source_commit": seal["source_commit"], "source_files": len(seal["source_hashes"]),
            "unit_cases": CONTRACT.PLAN["test_cases"], "restart_cases": len(CONTRACT.CASES),
            "independent_child_processes": len(pids), "forward_calls": 0,
            "tensor_payload_replayed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--source-seal", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.bundle, args.source_seal), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
