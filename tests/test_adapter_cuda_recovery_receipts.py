"""No models or APIs: verify retained CUDA evidence and claim boundaries."""

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "adapter_cuda_receipts", ROOT / "scripts/verify_v15_adapter_cuda_recovery.py"
)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_complete_cuda_replay_keeps_failures_and_review_open():
    result = audit.replay(audit.DEFAULT)
    assert result["cuda"]["counts"] == dict(tests=71, failures=0, errors=0, skipped=0)
    assert result["cuda"]["matched_update_conditions_passed"] == 8
    assert result["cuda"]["exact_resume_conditions_passed"] == 8
    assert result["original_environment_failure_preserved"] is True
    assert len(result["review_findings_open"]) == 2
    assert result["review_findings_closed_by_this_run"] == 0
    assert result["old_expression_gate"] == "FAIL"


@pytest.mark.parametrize(
    "field", ["source", "guard", "scope", "counts", "runtime", "peak", "decision"]
)
def test_altered_json_is_rejected(monkeypatch, field):
    original = audit.read

    def changed(path):
        value = copy.deepcopy(original(path))
        if path.name == "SOURCE_SEAL.json" and path.parent == audit.DEFAULT and field == "source":
            value["source_commit"] = "0" * 40
        if path.name == "EXECUTION_DECISION.json" and field == "decision":
            value["source_and_tests_changed"] = True
        if path.name == "STARTED.json" and field == "guard":
            value["source_check"]["fresh_bytecode_cache"] = False
        if path.name == "FINISHED.json":
            if field == "scope":
                value["new_sequences"] = 1
            if field == "counts":
                value["counts"]["tests"] = 70
            if field == "runtime":
                value["runtime"]["torch"] = "other"
            if field == "peak":
                value["peak_cuda_allocated_bytes"] = 7 * 2**30
        return value

    monkeypatch.setattr(audit, "read", changed)
    with pytest.raises(ValueError):
        audit.replay(audit.DEFAULT)


def test_original_bundle_index_includes_failure_and_historical_prose():
    index = audit.file_index(audit.original.DEFAULT)
    assert "raw/cuda/FINISHED.json" in index
    assert "README.md" in index
    assert "SUMMARY.json" in index
    assert "validation/REGRESSION_TESTS.xml" in index
