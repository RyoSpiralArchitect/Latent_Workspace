"""Fail-closed predecessor receipt admission; no model loading or GPU calls."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "_v14_return_receipt_runner", SCRIPTS / "run_v14_instrument_screen.py"
)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


@pytest.fixture
def predecessor(tmp_path):
    bindings = {
        "plan_sha256": "a" * 64,
        "source_identity": {"package": {"sha256": "b" * 64}, "scripts": {"runner": "c" * 64}},
        "commit": "d" * 40,
    }
    artifacts = {}
    for name in ("cases.jsonl", "input_parity.jsonl"):
        payload = json.dumps({"fixture_only": name}).encode() + b"\n"
        (tmp_path / name).write_bytes(payload)
        artifacts[name] = hashlib.sha256(payload).hexdigest()
    receipt = {
        "format": "v14-instrument-screen-v1",
        "model_key": "olmo",
        "status": "COMPLETE",
        "return_to_mistral": True,
        "instrument": {"instrument_checks_passed": True},
        "coverage_ok": True,
        "integrity_ok": True,
        "completed_cases": 480,
        "base_parameter_identity_versions_unchanged": True,
        "artifact_sha256": artifacts,
        **copy.deepcopy(bindings),
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(receipt))
    return path, receipt, bindings


def test_matching_complete_predecessor_returns_actual_receipt_digest(predecessor):
    path, receipt, bindings = predecessor
    before = copy.deepcopy(bindings)
    assert runner.check_predecessor(path, bindings) == hashlib.sha256(path.read_bytes()).hexdigest()
    assert bindings == before
    assert json.loads(path.read_text()) == receipt


@pytest.mark.parametrize(
    "field,value",
    [
        ("model_key", "mistral"),
        ("status", "FAILED"),
        ("status", "RUNNING"),
        ("status", "MISMATCH"),
        ("completed_cases", 479),
        ("completed_cases", 481),
        ("completed_cases", "480"),
        ("plan_sha256", "wrong-plan"),
        ("source_identity", {"package": "wrong-source", "scripts": {}}),
        ("commit", "wrong-commit"),
    ],
)
def test_inconsistent_provenance_status_and_counts_reject(predecessor, field, value):
    path, receipt, bindings = predecessor
    receipt[field] = value
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="Predecessor does not admit"):
        runner.check_predecessor(path, bindings)


@pytest.mark.parametrize(
    "field",
    [
        "return_to_mistral",
        "coverage_ok",
        "integrity_ok",
        "base_parameter_identity_versions_unchanged",
    ],
)
@pytest.mark.parametrize("value", [False, None, 1, "true"])
def test_admission_booleans_must_be_explicit_true(predecessor, field, value):
    path, receipt, bindings = predecessor
    receipt[field] = value
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="Predecessor does not admit"):
        runner.check_predecessor(path, bindings)


@pytest.mark.parametrize("value", [False, None, 1, "true"])
def test_instrument_flag_cannot_be_laundered_by_top_level_success(predecessor, value):
    path, receipt, bindings = predecessor
    receipt["instrument"]["instrument_checks_passed"] = value
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="Predecessor does not admit"):
        runner.check_predecessor(path, bindings)


@pytest.mark.parametrize(
    "field",
    [
        "model_key",
        "status",
        "return_to_mistral",
        "instrument",
        "coverage_ok",
        "integrity_ok",
        "completed_cases",
        "base_parameter_identity_versions_unchanged",
        "plan_sha256",
        "source_identity",
        "commit",
    ],
)
def test_missing_required_binding_rejects(predecessor, field):
    path, receipt, bindings = predecessor
    del receipt[field]
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="Predecessor does not admit"):
        runner.check_predecessor(path, bindings)


@pytest.mark.parametrize("name", ["cases.jsonl", "input_parity.jsonl"])
def test_altered_artifact_rejects_even_if_summary_still_says_complete(predecessor, name):
    path, _receipt, bindings = predecessor
    (path.parent / name).write_text("changed after receipt\n")
    with pytest.raises(ValueError, match="artifact identity mismatch"):
        runner.check_predecessor(path, bindings)


@pytest.mark.parametrize("name", ["cases.jsonl", "input_parity.jsonl"])
def test_missing_artifact_rejects(predecessor, name):
    path, _receipt, bindings = predecessor
    (path.parent / name).unlink()
    with pytest.raises(FileNotFoundError):
        runner.check_predecessor(path, bindings)


@pytest.mark.parametrize("name", ["cases.jsonl", "input_parity.jsonl"])
def test_missing_artifact_hash_rejects(predecessor, name):
    path, receipt, bindings = predecessor
    del receipt["artifact_sha256"][name]
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="artifact identity mismatch"):
        runner.check_predecessor(path, bindings)


def test_new_callers_source_does_not_inherit_old_receipt_admission(predecessor):
    path, _receipt, bindings = predecessor
    bindings["source_identity"]["scripts"]["runner"] = "e" * 64
    with pytest.raises(ValueError, match="Predecessor does not admit"):
        runner.check_predecessor(path, bindings)
