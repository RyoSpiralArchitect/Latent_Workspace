from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "completion_portability_test", ROOT / "scripts/audit_v15_completion_portability.py"
)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_exact_values_record_matches_without_qualification():
    value = {"count": 3, "correct": True, "prediction": None, "mass": 0.2, "name": "yes"}
    result = audit.compare_exact(value, value)
    assert result["status"] == "EXACT_REPLAY_MATCH"
    assert result["counts"]["exact_scalar_matches"] == 5
    assert result["differences"] == []
    assert "accepted" not in result


@pytest.mark.parametrize("value", [0.1, -0.1, 1.0, -1.0, 1e-300, -1e-300])
def test_one_ulp_is_still_exact_mismatch(value):
    observed = math.nextafter(value, math.inf)
    result = audit.compare_exact({"x": value}, {"x": observed})
    assert result["status"] == "EXACT_REPLAY_MISMATCH"
    assert result["differences"][0]["ulp_distance"] == 1
    assert result["counts"]["float64_differences"] == 1
    assert result["counts"]["other_differences"] == 0


def test_signed_zero_distinct_binary64():
    result = audit.compare_exact(0.0, -0.0)
    assert result["status"] == "EXACT_REPLAY_MISMATCH"
    assert result["differences"][0]["ulp_distance"] == 1


@pytest.mark.parametrize(
    "expected,observed,kind",
    [
        (1, 2, "scalar_value"),
        (True, False, "scalar_value"),
        (1, 1.0, "type_mismatch"),
        (True, 1, "type_mismatch"),
        (None, "None", "type_mismatch"),
        ([1], [1, 2], "list_length"),
        ({"x": 1}, {"y": 1}, "mapping_keys"),
        ("PASS", "FAIL", "scalar_value"),
    ],
)
def test_non_float_and_structural_changes_flagged(expected, observed, kind):
    result = audit.compare_exact(expected, observed)
    assert result["status"] == "EXACT_REPLAY_MISMATCH"
    assert result["counts"]["other_differences"] == 1
    assert result["differences"][0]["kind"] == kind
    assert result["structure_types_and_non_float_values_exact"] is False


def test_all_nested_differences_listed_without_early_return():
    result = audit.compare_exact(
        {"a/b": [1, 0.1], "z": 2}, {"a/b": [3, math.nextafter(0.1, math.inf)], "z": 2}
    )
    assert [d["path"] for d in result["differences"]] == ["/a~1b/0", "/a~1b/1"]
    assert result["counts"]["exact_scalar_matches"] == 1


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 1, True])
def test_invalid_float_bits_rejected(value):
    with pytest.raises(ValueError):
        audit.float64_bits(value)


def test_original_failure_recorded_not_converted_to_pass(monkeypatch, tmp_path):
    data = {
        "REPORT.json": {"summary": {"mass": 0.1, "prediction": 1}},
        "STARTED.json": {"runtime": {"python": "origin"}, "source_commit": "a" * 40},
        "SCORES.json": [],
        "VALIDATION.json": {"status": "VERIFIED_RECEIPTS"},
    }
    monkeypatch.setattr(audit, "load", lambda path: data[path.name])
    monkeypatch.setattr(audit, "digest", lambda path: "b" * 64)
    monkeypatch.setattr(
        audit, "summarize", lambda rows: {"mass": math.nextafter(0.1, math.inf), "prediction": 1}
    )

    def failed(bundle):
        raise ValueError("Completion summary mismatch")

    monkeypatch.setattr(audit, "verify_bundle", failed)
    result = audit.audit_bundle(tmp_path, tmp_path / "VALIDATION.json")
    assert result["status"] == "EXACT_REPLAY_MISMATCH"
    assert result["local_strict_verifier"]["status"] == "FAILED"
    assert result["local_strict_verifier"]["message"] == "Completion summary mismatch"
    assert result["remote_validation"]["status"] == "SEPARATE_RECORDED_RECEIPT_NOT_REEXECUTED_HERE"
    assert result["replacement_validation"] is False
    assert result["tolerance_acceptance_performed"] is False
    assert result["local"]["math_library_identity"] == "UNKNOWN"


def test_unexpected_verifier_exception_propagates(monkeypatch, tmp_path):
    data = {"REPORT.json": {"summary": {}}, "STARTED.json": {}, "SCORES.json": []}
    monkeypatch.setattr(audit, "load", lambda path: data[path.name])
    monkeypatch.setattr(audit, "summarize", lambda rows: {})

    def failed(bundle):
        raise RuntimeError("not a validation mismatch")

    monkeypatch.setattr(audit, "verify_bundle", failed)
    with pytest.raises(RuntimeError, match="not a validation mismatch"):
        audit.audit_bundle(tmp_path)
