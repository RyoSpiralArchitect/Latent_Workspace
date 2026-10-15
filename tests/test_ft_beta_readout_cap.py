"""CPU toy evidence and failure contracts for the posthoc cap audit."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import audit_ft_beta_readout_cap as audit  # noqa: E402


def state(gap):
    return {
        "scores": [0.0, gap],
        "yes_minus_no": gap,
        "greedy_choice": None if gap == 0 else int(gap > 0),
        "tie": gap == 0,
    }


def toy_rows():
    rows = []
    for world in range(2):
        for query in range(8):
            for side in (0, 1):
                base = -0.5 if len(rows) < 7 else 0.2
                gap = base + 0.3
                rows.append(
                    {
                        "world_index": world,
                        "query_index": query,
                        "side": side,
                        "control": "intact",
                        "target_label": 1,
                        "original_label": 1,
                        "delta_l2": 0.99,
                        "native_applied_delta_l2": 1.2,
                        "base_dual_readout": {audit.FP32: state(base), audit.NATIVE: state(-3)},
                        "dual_readout": {audit.FP32: state(gap), audit.NATIVE: state(4)},
                    }
                )
    return rows


def test_conditional_ceiling_and_errors_not_native_bound():
    result = audit.analyze_rows(toy_rows(), axis_norm=0.32372028157961014)
    assert result["conditionally_impossible_count"] == 7
    assert result["conditional_fp32_geometric_correct_count_ceiling"] == 25
    assert result["fp32_observed_correct_count"] == 25
    assert result["all_observed_errors_in_conditionally_impossible_rows"]
    assert result["fp32_shift_exceeds_bound_plus_guard_count"] == 0
    assert result["native_observed_correct_count"] == 32
    assert result["native_bound_claim"] is False
    assert result["max_cap_to_reach_zero_margin_necessary_lower_bound"] == pytest.approx(
        0.5 / 0.32372028157961014
    )


def test_negative_target_sign_and_ties_are_not_correct():
    rows = toy_rows()
    rows[0]["original_label"] = rows[0]["target_label"] = 0
    rows[0]["base_dual_readout"][audit.FP32] = state(0.5)
    rows[0]["dual_readout"][audit.FP32] = state(0)
    result = audit.analyze_rows(rows, axis_norm=0.3)
    first = result["rows"][0]
    assert first["fp32_target_signed_base_gap"] == -0.5
    assert first["fp32_observed_tie"] is True and first["fp32_observed_correct"] is False
    assert result["fp32_observed_tie_count"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("cap", -1),
        ("cap", 0),
        ("cap", float("nan")),
        ("axis_norm", 0),
        ("axis_norm", -0.1),
        ("axis_norm", float("inf")),
        ("arithmetic_guard", -0.1),
        ("arithmetic_guard", float("nan")),
    ],
)
def test_invalid_geometry_rejected(field, value):
    kwargs = {"axis_norm": 0.3, "cap": 1.0, "arithmetic_guard": 1e-4, field: value}
    with pytest.raises(ValueError):
        audit.analyze_rows(toy_rows(), **kwargs)


@pytest.mark.parametrize("problem", ["missing", "duplicate", "nan", "mismatch", "label", "norm"])
def test_invalid_observations_rejected(problem):
    rows = toy_rows()
    if problem == "missing":
        rows.pop()
    elif problem == "duplicate":
        rows[-1] = copy.deepcopy(rows[0])
    elif problem == "nan":
        rows[0]["dual_readout"][audit.FP32] = state(float("nan"))
    elif problem == "mismatch":
        rows[0]["dual_readout"][audit.FP32]["greedy_choice"] = 1
    elif problem == "label":
        rows[0]["target_label"] = True
    else:
        rows[0]["delta_l2"] = 1.1
    with pytest.raises(ValueError):
        audit.analyze_rows(rows, axis_norm=0.3)


def test_strict_diagnostic_guard_boundary_is_not_impossible():
    rows = toy_rows()
    rows[0]["base_dual_readout"][audit.FP32] = state(-0.3001)
    result = audit.analyze_rows(rows, axis_norm=0.3)
    assert result["rows"][0]["conditionally_impossible_with_diagnostic_guard"] is False


@pytest.mark.parametrize("environment", [None, "0", "-1"])
def test_cpu_only_requires_explicit_empty_cuda_visibility(monkeypatch, environment):
    if environment is None:
        monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    else:
        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", environment)
    with pytest.raises(RuntimeError, match="CPU-only"):
        audit.require_cpu_only()


def test_cpu_only_refuses_already_initialized_cuda(monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    monkeypatch.setattr(audit.torch.cuda, "is_initialized", lambda: True)
    with pytest.raises(RuntimeError, match="initialized"):
        audit.require_cpu_only()


def test_real_raw_receipts_analyze_to_same_ceiling_without_loading_model():
    raw = Path(__file__).resolve().parents[1] / "provenance/pilots/ft_beta_query_pool_20261010/raw"
    for mode in ("final", "mean_span"):
        evaluation = json.loads((raw / f"{mode}_256_evaluation.json").read_text())
        result = audit.analyze_rows(evaluation["rows"], axis_norm=0.32372028157961014)
        assert evaluation["gates"]["tiny_feasibility"] is False
        assert result["conditional_fp32_geometric_correct_count_ceiling"] == 25
        assert result["fp32_observed_correct_count"] == 25
        assert result["all_observed_errors_in_conditionally_impossible_rows"] is True
        assert result["conditionally_impossible_but_observed_correct_count"] == 0
        assert result["max_cap_to_reach_zero_margin_necessary_lower_bound"] == pytest.approx(
            1.5323, abs=0.0001
        )


def test_exclusive_output_and_receipt_identity_fail_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    monkeypatch.setattr(audit.torch.cuda, "is_initialized", lambda: False)
    output = tmp_path / "existing.json"
    output.write_text("preserve")
    with pytest.raises(FileExistsError):
        audit.execute(tmp_path / "missing", tmp_path / "no-model", output)
    assert output.read_text() == "preserve"


def test_execute_preserves_failed_gate_and_records_hashes(monkeypatch, tmp_path):
    raw = Path(__file__).resolve().parents[1] / "provenance/pilots/ft_beta_query_pool_20261010/raw"
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    monkeypatch.setattr(audit.torch.cuda, "is_initialized", lambda: False)
    monkeypatch.setattr(audit, "read_head_rows", lambda p: (0.32372028157961014, {"toy": True}))
    output = tmp_path / "audit.json"
    result = audit.execute(raw, tmp_path, output)
    assert json.loads(output.read_text()) == result
    assert result["cuda_initialized"] is False
    assert result["source_script_sha256"] == audit.sha256(audit.__file__)
    assert len(result["raw_receipt_sha256"]) == 5
    assert result["winner"] == "none" and result["semantic_promotion"] is False
    assert all(mode["original_tiny_feasibility_gate"] is False for mode in result["modes"].values())


def test_saved_cpu_head_audit_reconstructs_and_retains_provenance():
    bundle = Path(__file__).resolve().parents[1] / "provenance/pilots/ft_beta_query_pool_20261010"
    result = json.loads((bundle / "READOUT_CAP_AUDIT.json").read_text())
    assert result["source_script_sha256"] == audit.sha256(audit.__file__)
    assert result["cuda_initialized"] is False
    assert result["head_identity"]["full_model_rehashed"] is False
    for name, digest in result["raw_receipt_sha256"].items():
        assert audit.sha256(bundle / "raw" / name) == digest
    for mode, saved in result["modes"].items():
        rows = json.loads((bundle / "raw" / f"{mode}_256_evaluation.json").read_text())["rows"]
        reconstructed = audit.analyze_rows(rows, axis_norm=saved["axis_norm_fp64"])
        assert saved == {**reconstructed, "original_tiny_feasibility_gate": False}
        assert reconstructed["conditional_fp32_geometric_correct_count_ceiling"] == 25
