from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/validate_v13_design_contract.py"
SPEC = importlib.util.spec_from_file_location("validate_v13_design_contract", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


@pytest.fixture
def contract() -> dict:
    return json.loads((REPO / "configs/v13/DESIGN_CONTRACT.json").read_text(encoding="utf-8"))


def _stage(contract: dict, name: str) -> dict:
    return next(stage for stage in contract["stages"] if stage["id"] == name)


def _cli(root: Path, path: str = "configs/v13/DESIGN_CONTRACT.json") -> subprocess.CompletedProcess:
    # -I -S proves the CLI requires only stdlib, not installed scientific packages.
    return subprocess.run(
        [sys.executable, "-I", "-S", str(SCRIPT), "--repo-root", str(root), "--contract", path],
        capture_output=True,
        text=True,
        check=False,
    )


def test_current_design_is_valid_but_never_execution_ready(contract: dict) -> None:
    before = copy.deepcopy(contract)
    assert validator.validate_contract(contract, REPO) == []
    assert contract == before
    completed = _cli(REPO)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["design_status"] == "DESIGN_VALID"
    assert result["execution_ready"] is False
    assert result["execution_status"] == "BLOCKED_DESIGN_ONLY"
    assert len(result["execution_blockers"]) >= 4
    assert "not scientific evidence" in result["claim_boundary"]
    assert "production fail-closed" in result["claim_boundary"]
    assert "passed" not in result


def test_harmless_documentation_additions_are_allowed(contract: dict) -> None:
    contract["design_notes"] = {"comment": "No execution or qualification claim."}
    contract["state_contract"]["additional_design_note"] = "Future clarification."
    assert validator.validate_contract(contract, REPO) == []


@pytest.mark.parametrize("value", [True, "false", "true", 0, 1, None])
def test_authority_requires_literal_false(contract: dict, value: object) -> None:
    contract["execution_authority"]["training"] = value
    assert validator.validate_contract(contract, REPO)


@pytest.mark.parametrize("field", sorted(validator.AUTHORITY_FIELDS))
def test_no_authority_flag_can_be_removed_or_enabled(contract: dict, field: str) -> None:
    contract["execution_authority"].pop(field)
    assert validator.validate_contract(contract, REPO)
    contract["execution_authority"][field] = True
    assert validator.validate_contract(contract, REPO)


@pytest.mark.parametrize(
    "section,key,value",
    [
        (None, "status", "PASS"),
        (None, "frozen_for_execution", True),
        (None, "frozen_for_execution", "false"),
        (None, "schema_version", True),
        (None, "execution_ready", True),
        ("model_anchor", "base_weights", "TRAINABLE"),
        ("model_anchor", "native_normalizer", "LayerNorm"),
        ("implementation_status", "scientific_runs", "PASS"),
        ("implementation_status", "coordinate_interventions", "IMPLEMENTED"),
        ("state_contract", "factorization_uses_normalizer_epsilon", True),
        ("state_contract", "degenerate_radius_policy", "IMPUTE_ZERO_DIRECTION"),
        ("state_contract", "coordinate_source", "POST_AFFINE_STATE"),
        ("state_contract", "bridge_claim_in_v13", True),
        ("state_contract", "update_means", "OPTIMIZER_STEP"),
        ("input_lanes", "pool_metrics_across_lanes", True),
        ("input_lanes", "requalify_reader_and_sufficiency_on_each_route", "true"),
        ("measurement_contract", "uncertainty_unit", "PAIRED_WORLD_CLUSTER"),
        ("measurement_contract", "donor_accuracy_alone_is_causal_evidence", True),
        ("measurement_contract", "missing_or_degenerate_measurement", "PASS"),
        ("data_contract", "adjacent_only_twins_allowed_for_primary_claim", True),
        ("claim_gates", "numerical_thresholds", {"accuracy": 0.75}),
        ("v14_handoff", "status", "QUALIFIED_BRIDGE"),
    ],
)
def test_design_fences_cannot_be_promoted_or_reinterpreted(
    contract: dict,
    section: str | None,
    key: str,
    value: object,
) -> None:
    target = contract if section is None else contract[section]
    target[key] = value
    assert validator.validate_contract(contract, REPO)


@pytest.mark.parametrize(
    "section,key",
    [
        ("state_contract", "hybrid_slot_map_frozen_across_all_cells_and_patch_modes"),
        ("state_contract", "architecture_fingerprint_includes_non_tensor_attributes"),
        ("state_contract", "mean_shift_under_current_pre_norm_architecture"),
        ("state_contract", "actual_layernorm_formula"),
        ("state_contract", "readable_now"),
        ("state_contract", "transition_effective"),
        ("measurement_contract", "per_case_predictions_and_logits_required"),
        ("measurement_contract", "paired_donor_logodds_gain"),
        ("measurement_contract", "intact_correct_to_donor_correct_required"),
        ("measurement_contract", "report_intact_wrong_rows_and_all_affected_denominator"),
        ("measurement_contract", "unaffected_prediction_agreement_required"),
        ("measurement_contract", "unaffected_ground_truth_accuracy_separate"),
        ("measurement_contract", "content_control_effect_required"),
        ("measurement_contract", "require_each_claim_gate_not_f3_f4_only"),
        ("data_contract", "heldout_template_crosses_affected_status"),
        ("data_contract", "same_original_world_query_has_both_affected_statuses_across_edits"),
        ("data_contract", "sampling_order"),
        ("claim_gates", "numerical_thresholds"),
    ],
)
def test_required_measurement_and_state_fields_cannot_be_removed(
    contract: dict,
    section: str,
    key: str,
) -> None:
    contract[section].pop(key)
    assert validator.validate_contract(contract, REPO)


@pytest.mark.parametrize(
    "section,key",
    [
        ("measurement_contract", "null_controls"),
        ("measurement_contract", "matched_eval_surface"),
        ("measurement_contract", "artifact_binding"),
        ("measurement_contract", "cluster_includes"),
        ("claim_gates", "content_specific_requires_all"),
        ("data_contract", "primary_task_shortcut_oracles"),
        ("v14_handoff", "future_bridge_proof_requires"),
        ("v14_handoff", "required_exports"),
    ],
)
def test_every_required_list_member_is_protected(contract: dict, section: str, key: str) -> None:
    for index in range(len(contract[section][key])):
        changed = copy.deepcopy(contract)
        changed[section][key].pop(index)
        assert validator.validate_contract(changed, REPO), (section, key, index)


def test_f3_f4_only_summary_is_not_a_valid_contract(contract: dict) -> None:
    contract["claim_gates"]["content_specific_requires_all"] = ["F3", "F4"]
    assert validator.validate_contract(contract, REPO)
    for summary in (True, {"passed": True}, {"design_status": "PASS"}, [], None):
        assert validator.validate_contract(summary, REPO)


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "duplicate",
        "cycle",
        "unknown",
        "implemented",
        "missing_lane",
        "wrong_lane",
    ],
)
def test_stage_graph_and_input_lanes_are_explicit(contract: dict, case: str) -> None:
    if case == "missing":
        contract["stages"].pop()
    elif case == "duplicate":
        contract["stages"].append(copy.deepcopy(contract["stages"][0]))
    elif case == "cycle":
        contract["stages"][0]["depends_on"] = ["S3_TRANSITIONS"]
    elif case == "unknown":
        contract["stages"][0]["depends_on"] = ["UNKNOWN"]
    elif case == "implemented":
        contract["stages"][0]["status"] = "IMPLEMENTED"
    elif case == "missing_lane":
        _stage(contract, "S3_TRANSITIONS").pop("input_lanes")
    else:
        _stage(contract, "S3_TRANSITIONS")["input_lanes"] = ["retained_inline_diagnostic"]
    assert validator.validate_contract(contract, REPO)


@pytest.mark.parametrize(
    "key,value",
    [
        ("factorial_cells", 7),
        ("factorial_cells", "8"),
        ("factorial_cells", True),
        ("factors", ["shape", "radius"]),
        ("factors", ["shape", "shape", "mean"]),
        ("donor_levels", ["original"]),
        ("both_swap_directions_required", False),
        ("identity_and_self_reconstruction_required", "true"),
    ],
)
def test_factorial_coverage_is_not_just_an_eight_label(
    contract: dict, key: str, value: object
) -> None:
    _stage(contract, "S2_COORDINATES")[key] = value
    assert validator.validate_contract(contract, REPO)


@pytest.mark.parametrize(
    "key,value",
    [
        ("modulation_head_output_init", "RANDOM"),
        ("outer_gain_init", "ZERO"),
        ("native_normalizer_replaced", True),
        ("controls", ["no_op", "memory_conditioned"]),
    ],
)
def test_optional_modulation_stays_zero_head_nonzero_gain(
    contract: dict,
    key: str,
    value: object,
) -> None:
    _stage(contract, "S4_MODULATION_OPTIONAL")[key] = value
    assert validator.validate_contract(contract, REPO)


def test_unresolved_fields_must_remain_explicit(contract: dict) -> None:
    contract["unresolved_execution_fields"] = []
    assert validator.validate_contract(contract, REPO)


@pytest.mark.parametrize(
    "section",
    [
        "state_contract",
        "measurement_contract",
        "model_anchor",
        "implementation_status",
        "execution_authority",
        "input_lanes",
        "claim_gates",
        "data_contract",
        "v14_handoff",
    ],
)
def test_malformed_sections_report_errors_without_crashing(contract: dict, section: str) -> None:
    contract[section] = None
    assert validator.validate_contract(contract, REPO)


@pytest.mark.parametrize(
    "path",
    [
        "../engine.py",
        "/tmp/engine.py",
        "src/../engine.py",
        "src\\engine.py",
        "./engine.py",
    ],
)
def test_unsafe_anchor_paths_fail(contract: dict, path: str) -> None:
    contract["historical_anchors"][0]["path"] = path
    assert validator.validate_contract(contract, REPO)


def test_exact_anchor_set_and_hashes_are_required(contract: dict) -> None:
    changed = copy.deepcopy(contract)
    changed["historical_anchors"].pop()
    assert validator.validate_contract(changed, REPO)
    changed = copy.deepcopy(contract)
    changed["historical_anchors"][1] = copy.deepcopy(changed["historical_anchors"][0])
    assert validator.validate_contract(changed, REPO)
    changed = copy.deepcopy(contract)
    changed["historical_anchors"][0]["sha256"] = "0" * 64
    assert validator.validate_contract(changed, REPO)


def test_changed_or_symlinked_anchor_is_not_accepted(contract: dict, tmp_path: Path) -> None:
    for anchor in contract["historical_anchors"]:
        destination = tmp_path / anchor["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / anchor["path"], destination)
    assert validator.validate_contract(contract, tmp_path) == []
    anchor_path = tmp_path / contract["historical_anchors"][0]["path"]
    anchor_path.write_bytes(anchor_path.read_bytes() + b"\nchanged\n")
    assert any(
        "content SHA-256 changed" in error
        for error in validator.validate_contract(contract, tmp_path)
    )
    anchor_path.unlink()
    anchor_path.symlink_to(REPO / contract["historical_anchors"][0]["path"])
    assert any("symlink" in error for error in validator.validate_contract(contract, tmp_path))


@pytest.mark.parametrize(
    "payload",
    [
        b"{",
        b"true",
        b'{"passed":true}',
        b'{"status":"DESIGN_ONLY","status":"PASS"}',
        b'{"value":NaN}',
        b'{"value":1e999}',
        b"\xff",
    ],
)
def test_malformed_cli_input_fails_cleanly(tmp_path: Path, payload: bytes) -> None:
    (tmp_path / "contract.json").write_bytes(payload)
    completed = _cli(tmp_path, "contract.json")
    assert completed.returncode == 1
    assert "Traceback" not in completed.stderr
    result = json.loads(completed.stdout)
    assert result["design_status"] == "DESIGN_INVALID"
    assert result["execution_ready"] is False
    assert result["errors"]


@pytest.mark.parametrize("path", ["missing.json", "../contract.json", "/tmp/contract.json", "."])
def test_missing_or_unsafe_cli_reference_fails_cleanly(tmp_path: Path, path: str) -> None:
    completed = _cli(tmp_path, path)
    assert completed.returncode == 1
    assert "Traceback" not in completed.stderr
    assert json.loads(completed.stdout)["execution_ready"] is False
