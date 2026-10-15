"""Offline tamper/coverage checks; no model or GPU computation."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "adapter_owner_receipts", ROOT / "scripts/verify_v15_adapter_owner.py"
)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_replay_binds_cpu_cases_and_preserves_cuda_failure():
    result = audit.replay(audit.DEFAULT)
    assert result["runs"]["cpu"]["counts"] == dict(tests=71, failures=0, errors=0, skipped=0)
    assert result["runs"]["cpu"]["matched_update_conditions_passed"] == 8
    assert result["runs"]["cpu"]["exact_resume_conditions_passed"] == 8
    assert result["runs"]["cuda"]["counts"]["tests"] == 0
    assert result["runs"]["cuda"]["status"] == "FAILED"
    assert result["old_expression_gate"] == "FAIL"
    assert result["non_regression"] == "NOT_ESTABLISHED"


@pytest.mark.parametrize("field", ["source", "guard", "plan", "scope", "denominator", "failure"])
def test_mutated_json_is_not_accepted(monkeypatch, field):
    original = audit.read

    def changed(path):
        value = copy.deepcopy(original(path))
        if path.name == "SOURCE_SEAL.json" and field == "source":
            value["source_hashes"][next(iter(value["source_hashes"]))] = "0" * 64
        if path.name == "STARTED.json" and field == "guard":
            value["source_check"]["untracked_check"] = "no"
        if path.name == "STARTED.json" and field == "plan":
            value["plan"]["expected_test_cases"] = 70
        if path.name == "FINISHED.json":
            if field == "scope":
                value["real_model_updates"] = 1
            if field == "denominator" and path.parent.name == "cpu":
                value["counts"]["tests"] = 70
            if field == "failure" and path.parent.name == "cuda":
                value["status"] = audit.PASS
        return value

    monkeypatch.setattr(audit, "read", changed)
    with pytest.raises(ValueError):
        audit.replay(audit.DEFAULT)


def test_junit_duplicate_case_and_wrong_counts_fail(tmp_path):
    path = tmp_path / "TESTS.xml"
    case = '<testcase classname="tests.test_training_readout" name="x"/>'
    path.write_text(f'<testsuites><testsuite tests="2">{case}{case}</testsuite></testsuites>')
    with pytest.raises(ValueError, match="Duplicate"):
        audit.tests(path)
    path.write_text(f'<testsuites><testsuite tests="2">{case}</testsuite></testsuites>')
    with pytest.raises(ValueError, match="denominator"):
        audit.tests(path)


def test_artifact_index_covers_original_failure():
    index = audit.artifacts(audit.DEFAULT)
    assert "raw/cuda/FINISHED.json" in index
    assert "raw/cpu/TESTS.xml" in index
    assert len(audit.expected_cases()) == 71
    # Plain JSON serialization is portable, including all failed attempt metadata.
    assert json.loads(json.dumps(index)) == index
