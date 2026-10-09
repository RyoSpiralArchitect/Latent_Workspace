import copy
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ft_beta_verifier", ROOT / "scripts/verify_ft_beta_learner_audit.py"
)
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)
RAW = ROOT / "provenance/pilots/ft_beta_learner_audit_20261009/raw"


def test_real_receipt_contracts_without_models():
    summary = verify.verify_contracts(RAW.parent)
    assert summary["denominators"]["training_worlds"] == 2
    assert set(summary["states"]) == set(verify.STATES)
    assert summary["states"]["initial"]["reciprocal_hinge_gradient_geometry"]["writer"][
        "combined_over_mean_direction_norm"
    ] is None


def test_new_seal_read_only_verify_tamper_and_no_overwrite(tmp_path):
    shutil.copytree(RAW, tmp_path / "raw")
    assert verify.seal_bundle(tmp_path)["raw_artifacts"] == 15
    before = (tmp_path / "ARTIFACT_INDEX.json").read_bytes()
    assert verify.verify_bundle(tmp_path)["gradients_recomputed"] is False
    with pytest.raises(ValueError, match="collision"):
        verify.seal_bundle(tmp_path)
    assert (tmp_path / "ARTIFACT_INDEX.json").read_bytes() == before
    path = tmp_path / "raw/FEATURES.json"
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify.verify_bundle(tmp_path)


def test_control_denominator_and_zero_identity_fail_closed():
    controls = verify.load(RAW / "legacy_semantic256_controls.json")
    records = [json.loads(line) for line in
               (ROOT / "data/v10/functional_train.jsonl").read_text().splitlines()][:2]
    missing = copy.deepcopy(controls)
    missing["rows"].pop()
    with pytest.raises(ValueError, match="denominator"):
        verify.verify_controls(missing, records)
    broken = copy.deepcopy(controls)
    next(row for row in broken["rows"] if row["control"] == "zero")["delta_l2"] = 0.01
    with pytest.raises(ValueError, match="Exact zero"):
        verify.verify_controls(broken, records)


@pytest.mark.parametrize("key,value", [
    ("optimizer_steps", 1), ("parameter_grads_unchanged", False),
    ("bridge_state_unchanged", False),
])
def test_gradient_false_claim_guards(key, value):
    gradients = verify.load(RAW / "legacy_semantic256_gradients.json")
    gradients[key] = value
    with pytest.raises(ValueError):
        verify.verify_gradients(gradients, "semantic")


def test_reconstruction_failure_and_diagnostic_weight_fail_closed():
    gradients = verify.load(RAW / "legacy_semantic256_gradients.json")
    gradients["reconstruction"]["passed"] = False
    with pytest.raises(ValueError, match="reconstruction receipt"):
        verify.verify_gradients(gradients, "semantic")
    gradients = verify.load(RAW / "legacy_semantic256_gradients.json")
    gradients["terms"]["donor_even_hinge"]["weight"] = 0.25
    with pytest.raises(ValueError, match="Diagnostic entered"):
        verify.verify_gradients(gradients, "semantic")


def test_report_promotion_and_cuda_claim_guards(tmp_path):
    shutil.copytree(RAW, tmp_path / "raw")
    report = verify.load(tmp_path / "raw/REPORT.json")
    report["statistical_or_quality_qualification"] = True
    (tmp_path / "raw/REPORT.json").write_text(json.dumps(report))
    with pytest.raises(ValueError, match="Claim ceiling"):
        verify.verify_contracts(tmp_path)
    report["statistical_or_quality_qualification"] = False
    report["cuda_initialized"] = True
    (tmp_path / "raw/REPORT.json").write_text(json.dumps(report))
    with pytest.raises(ValueError, match="CPU execution"):
        verify.verify_contracts(tmp_path)
