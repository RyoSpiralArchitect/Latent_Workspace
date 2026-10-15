"""Offline verifier negative controls use synthetic receipts, never model calls."""

import json
from xml.etree import ElementTree as ET

import pytest

from scripts import verify_v16_slot_state as verify


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True))


def fixture(tmp_path):
    repo, bundle = tmp_path / "source", tmp_path / "bundle" / "cuda"
    bundle.mkdir(parents=True)
    for name in verify.CRITICAL:
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("offline synthetic fixture, not execution evidence")
    plan = {
        "test_files": [verify.TEST],
        "expected_test_cases": 145,
        "gpu_memory_limit_gib": 4,
        "wall_limit_seconds": 900,
    }
    write(repo / verify.PLAN, plan)
    seal = {
        "source_commit": "a" * 40,
        "source_hashes": {name: verify.digest(repo / name) for name in verify.CRITICAL},
    }
    write(bundle.parent / "SOURCE_SEAL.json", seal)
    started = {
        **seal,
        "plan": plan,
        "device": "cuda",
        "source_check": {
            "schema": "pre-import-source-check-v1",
            "source_commit": seal["source_commit"],
            "entry": verify.ENTRY,
            "source_files": len(seal["source_hashes"]),
            "untracked_check": "all",
            "isolated_python": True,
            "fresh_bytecode_cache": True,
        },
    }
    write(bundle / "STARTED.json", started)
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", tests="145", failures="0", errors="0", skipped="0")
    for i in range(145):
        ET.SubElement(suite, "testcase", name=f"test_{i}", classname="slot", file=verify.TEST)
    ET.ElementTree(root).write(bundle / "TESTS.xml")
    finished = {
        "status": verify.PASS,
        "device": "cuda",
        "pytest_exit_code": 0,
        "counts": {"tests": 145, "failures": 0, "errors": 0, "skipped": 0},
        "peak_cuda_allocated_bytes": 123456,
        "elapsed_seconds": 30,
        "real_model_updates": 0,
        "new_sequences": 0,
        "judge_calls": 0,
        "weight_deletions": 0,
        "old_expression_gate": "FAIL",
        "winner": "none",
        "non_regression": "NOT_ESTABLISHED",
        "imported_project_sources": {
            "state": verify.STATE,
            "owner": verify.OWNER,
            "test": verify.TEST,
        },
    }
    reseal(bundle, finished)
    return repo, bundle, finished


def reseal(bundle, finished):
    finished["files"] = {
        name: {"bytes": (bundle / name).stat().st_size, "sha256": verify.digest(bundle / name)}
        for name in ("STARTED.json", "TESTS.xml")
    }
    write(bundle / "FINISHED.json", finished)


def test_valid_synthetic_receipt_can_be_replayed(tmp_path):
    repo, bundle, _ = fixture(tmp_path)
    assert verify.verify(bundle, repo)["counts"]["tests"] == 145


@pytest.mark.parametrize(
    "mutation",
    [
        "bytes",
        "source",
        "scope",
        "duplicate",
        "counts",
        "source_receipt",
        "import",
        "gate",
        "status",
        "calls",
        "peak",
        "wall",
        "extra",
    ],
)
def test_corrupt_receipt_fails_even_if_terminal_hashes_are_reissued(tmp_path, mutation):
    repo, bundle, finished = fixture(tmp_path)
    if mutation == "bytes":
        (bundle / "TESTS.xml").write_text("changed")
    elif mutation == "source":
        (repo / verify.STATE).write_text("changed")
    elif mutation in ("scope", "duplicate"):
        tree = ET.parse(bundle / "TESTS.xml")
        cases = list(tree.getroot().iter("testcase"))
        if mutation == "scope":
            cases[0].set("file", "tests/unselected.py")
        else:
            cases[1].set("name", cases[0].get("name"))
        tree.write(bundle / "TESTS.xml")
    elif mutation == "counts":
        finished["counts"]["tests"] = 144
    elif mutation == "source_receipt":
        started = verify.read(bundle / "STARTED.json")
        started["source_check"]["isolated_python"] = False
        write(bundle / "STARTED.json", started)
    elif mutation == "import":
        finished["imported_project_sources"].pop("state")
    elif mutation == "gate":
        finished["old_expression_gate"] = "PASS"
    elif mutation == "status":
        finished["status"] = "INCOMPLETE"
    elif mutation == "calls":
        finished["judge_calls"] = 1
    elif mutation == "peak":
        finished["peak_cuda_allocated_bytes"] = 5 * 2**30
    elif mutation == "wall":
        finished["elapsed_seconds"] = 1000
    else:
        (bundle / "UNOWNED.json").write_text("{}")
    if mutation != "bytes":
        reseal(bundle, finished)
    with pytest.raises(ValueError):
        verify.verify(bundle, repo)
