#!/usr/bin/env python3
"""Offline tiny slot-state receipt replay; no Torch, checkpoint or API load."""

import argparse
import hashlib
import json
import math
import re
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "scripts/qualify_v16_slot_state.py"
PLAN = "configs/v16/SLOT_STATE_QUALIFICATION_PLAN.json"
TEST = "tests/test_slot_contrast_learner.py"
STATE = "src/latent_workspace_ft_v10/slot_contrast_state.py"
OWNER = "src/latent_workspace_ft_v10/slot_contrast_learner.py"
CRITICAL = {
    ENTRY,
    PLAN,
    TEST,
    STATE,
    OWNER,
    "scripts/run_source_sealed.py",
    "scripts/verify_v16_slot_state.py",
    "src/latent_workspace_ft_v10/v16_slot_contrast.py",
    "src/latent_workspace_ft_v10/native_training_preparation.py",
}
PASS = "TINY_SLOT_STATE_PASS_NOT_7B_OR_SEMANTIC"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(bundle, repo=ROOT):
    started, finished = (read(bundle / f"{name}.json") for name in ("STARTED", "FINISHED"))
    require(
        {p.name for p in bundle.iterdir()} == {"STARTED.json", "TESTS.xml", "FINISHED.json"},
        "Unexpected qualification artifact",
    )
    actual = {
        name: {"bytes": (bundle / name).stat().st_size, "sha256": digest(bundle / name)}
        for name in ("STARTED.json", "TESTS.xml")
    }
    require(actual == finished["files"], "Terminal artifact bytes mismatch")
    seal = read(bundle.parent / "SOURCE_SEAL.json")
    require(
        set(seal) == {"source_commit", "source_hashes"}
        and re.fullmatch(r"[0-9a-f]{40}", seal["source_commit"]),
        "Source seal schema",
    )
    require(CRITICAL <= set(seal["source_hashes"]), "Missing critical sealed source")
    require(all(started[key] == value for key, value in seal.items()), "Source identity mismatch")
    for name, sha in seal["source_hashes"].items():
        path = PurePosixPath(name)
        require(not path.is_absolute() and ".." not in path.parts, "Source path escape")
        target = repo / name
        require(target.resolve().is_relative_to(repo.resolve()), "Source symlink escape")
        require(digest(target) == sha, f"Source changed: {name}")
    require(
        started["source_check"]
        == {
            "schema": "pre-import-source-check-v1",
            "source_commit": seal["source_commit"],
            "entry": ENTRY,
            "source_files": len(seal["source_hashes"]),
            "untracked_check": "all",
            "isolated_python": True,
            "fresh_bytecode_cache": True,
        },
        "Pre-import source receipt mismatch",
    )
    plan = read(repo / PLAN)
    require(started["plan"] == plan, "Qualification plan mismatch")
    require(plan["expected_test_cases"] == 145 and plan["test_files"] == [TEST], "Test selection")
    counts = {"tests": 145, "failures": 0, "errors": 0, "skipped": 0}
    root = ElementTree.parse(bundle / "TESTS.xml").getroot()
    require(
        {key: sum(int(s.attrib.get(key, 0)) for s in root.iter("testsuite")) for key in counts}
        == finished["counts"]
        == counts,
        "Test denominators mismatch",
    )
    cases = list(root.iter("testcase"))
    require(
        len(cases) == len({(case.get("classname"), case.get("name")) for case in cases}) == 145
        and all(case.get("file") == TEST for case in cases),
        "Test identity mismatch",
    )
    require(finished["status"] == PASS and finished["pytest_exit_code"] == 0, "Not a passed run")
    require(finished["device"] == started["device"] in ("cpu", "cuda"), "Device mismatch")
    for key, expected in {
        "real_model_updates": 0,
        "new_sequences": 0,
        "judge_calls": 0,
        "weight_deletions": 0,
        "old_expression_gate": "FAIL",
        "winner": "none",
        "non_regression": "NOT_ESTABLISHED",
    }.items():
        require(finished[key] == expected, f"Claim ceiling changed: {key}")
    peak = finished["peak_cuda_allocated_bytes"]
    if finished["device"] == "cuda":
        require(type(peak) is int and 0 < peak <= plan["gpu_memory_limit_gib"] * 2**30, "CUDA peak")
    else:
        require(peak is None, "CPU run has CUDA peak")
    elapsed = finished["elapsed_seconds"]
    require(math.isfinite(elapsed) and 0 < elapsed <= plan["wall_limit_seconds"] + 60, "Wall limit")
    imports = finished["imported_project_sources"]
    require({STATE, OWNER, TEST} <= set(imports.values()), "Missing reader/owner/test import proof")
    require(set(imports.values()) <= set(seal["source_hashes"]), "Unsealed imported module")
    return {
        "status": PASS,
        "device": finished["device"],
        "counts": counts,
        "source_commit": seal["source_commit"],
        "source_files": len(seal["source_hashes"]),
        "elapsed_seconds": elapsed,
        "peak_cuda_allocated_bytes": peak,
        "old_expression_gate": "FAIL",
        "winner": "none",
        "non_regression": "NOT_ESTABLISHED",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    print(json.dumps(verify(parser.parse_args().bundle), indent=2, sort_keys=True))
