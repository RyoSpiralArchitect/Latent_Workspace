from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/v14_cache_trajectory_metrics.py"
SPEC = importlib.util.spec_from_file_location("v14_cache_trajectory_metrics", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
metrics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metrics)

HORIZONS = (0, 1, 2)
CELL_PROTOCOL = {
    "A": ("base", 0, "none", "carry"),
    "B": ("intact", 1, "one_pulse", "carry"),
    "C": ("twin", 1, "one_pulse", "carry"),
    "D": ("intact", 1, "one_pulse", "matched_no_pulse_history_replacement"),
    "E": ("twin", 1, "one_pulse", "matched_no_pulse_history_replacement"),
}


def _direction(kind: str) -> dict:
    sham = kind == "sham"
    return {
        "kind": kind,
        "direction_id": f"direction:{kind}",
        "pulse_norm": 0.0 if sham else 1.0,
        "reference_norm": 1.0,
        "equal_norm_tolerance": 1e-6,
        "equal_norm_verified": not sham,
    }


def _cell(name: str, *, margin: float, horizon: int, unaffected: bool) -> dict:
    intervention, pulse_count, forcing, history = CELL_PROTOCOL[name]
    logits = [1.0, 0.0] if unaffected else [0.0, margin]
    tokens = [101, 200 + horizon]
    return {
        "intervention_kind": intervention,
        "pulse_count": pulse_count,
        "forcing_mode": forcing,
        "history_mode": history,
        "candidate_logits": logits,
        "token_ids": tokens,
        "position_ids": [0, 1],
        "attention_mask": [1, 1],
        "state_displacement": 0.0 if name == "A" else 0.1 * (horizon + 1),
        "kv_displacement": 0.0 if name in ("A", "D", "E") else 0.2 * (horizon + 1),
    }


def _row(family: int, probe: str, kind: str, horizon: int) -> dict:
    unaffected = probe == "unaffected"
    if kind == "semantic":
        effect = 2.0 * horizon
    elif kind == "equal_norm_random":
        effect = 0.25 * horizon
    else:
        effect = 0.0
    margins = {"A": -1.0, "B": -1.0, "C": -1.0 + effect, "D": -1.0, "E": -1.0}
    return {
        "family_id": f"family-{family}",
        "probe_id": probe,
        "query_id": f"query:{probe}",
        "horizon": horizon,
        "original_label": 0,
        "donor_label": 0 if unaffected else 1,
        "affected": not unaffected,
        "query_token_ids": [31, 32],
        "probe_token_ids": [41],
        "pulse_horizon": 0,
        "fixed_continuation": True,
        "probe_is_read_only": True,
        "direction": _direction(kind),
        "cells": {
            name: _cell(name, margin=margins[name], horizon=horizon, unaffected=unaffected)
            for name in metrics.CELL_NAMES
        },
    }


def _rows(
    *,
    families: int = 2,
    probes: tuple[str, ...] = ("affected", "unaffected"),
    directions: tuple[str, ...] = ("equal_norm_random", "sham"),
) -> list[dict]:
    return [
        _row(family, probe, kind, horizon)
        for family in range(families)
        for probe in probes
        for kind in directions
        for horizon in HORIZONS
    ]


def _summary(
    rows: list[dict],
    *,
    families: int = 2,
    probes: int = 2,
    directions: tuple[str, ...] = ("equal_norm_random", "sham"),
) -> dict:
    return metrics.summarize(
        rows,
        expected_horizons=HORIZONS,
        endpoint_horizon=2,
        frozen_floor=1e-5,
        expected_families=families,
        expected_probes_per_family=probes,
        expected_direction_kinds=directions,
    )


def _thresholds(*, frozen: bool = True) -> dict:
    return {
        "plan_id": "signed-plan-v1",
        "frozen_before_measurement": frozen,
        "endpoint_ci_lower_strictly_above": 0.0,
        "signed_auc_ci_lower_strictly_above": 0.0,
        "semantic_minus_control_endpoint_ci_lower_strictly_above": 0.0,
        "semantic_minus_control_auc_ci_lower_strictly_above": 0.0,
        "unaffected_retention_ci_lower_at_least": 1.0,
    }


def test_complete_mechanical_screen_preserves_five_cells_and_family_bootstrap() -> None:
    rows = _rows()
    original = copy.deepcopy(rows)
    result = _summary(rows)
    assert result["coverage"] == {
        "complete": True,
        "expected_rows": 24,
        "observed_rows": 24,
        "missing_rows": 0,
        "expected_families": 2,
        "observed_families": 2,
        "expected_probes": 4,
        "observed_probes": 4,
    }
    assert result["protocol"]["valid"] is True
    assert result["measurements"]["complete"] is True
    assert result["mechanical_screen_complete"] is True
    assert result["bootstrap"]["draws"] == 4096
    assert result["bootstrap"]["seed"] == 1414
    assert result["bootstrap"]["unit"] == "FAMILY_CLUSTER"
    assert result["directions"]["equal_norm_random"]["affected"]["endpoint"][
        "observed_family_count"
    ] == 2
    assert result["measurements"]["state_and_kv_displacement_are_separate"]
    assert set(result["measurements"]["displacement"]) == {
        "state_displacement",
        "kv_displacement",
    }
    assert rows == original
    json.dumps(result, allow_nan=False)


def test_signed_central_contrast_endpoint_auc_and_floor_guarded_secondary_ratio() -> None:
    result = _summary(_rows(families=1, probes=("affected",)), families=1, probes=1)
    trajectory = next(
        item
        for item in result["trajectories"]
        if item["direction_kind"] == "equal_norm_random"
    )
    assert [point["central_contrast"] for point in trajectory["trajectory"]["points"]] == [
        0.0,
        0.25,
        0.5,
    ]
    assert trajectory["endpoint"] == 0.5
    assert trajectory["signed_auc"] == 0.5
    assert trajectory["trajectory"]["points"][2]["cells"]["C"]["donor_margin"] == -0.5
    assert trajectory["trajectory"]["points"][2]["cells"]["B"]["donor_margin"] == -1.0
    ratios = trajectory["trajectory"]["amplification_ratios"]
    assert ratios[0]["status"] == "UNKNOWN_BELOW_FROZEN_FLOOR"
    assert ratios[0]["value"] is None
    assert ratios[1]["status"] == "SECONDARY_DESCRIPTIVE"
    assert ratios[1]["value"] == 2.0
    assert trajectory["trajectory"]["absolute_magnitude_is_semantic_qualification"] is False


def test_negative_signed_effect_does_not_become_positive_through_absolute_value() -> None:
    directions = ("semantic", "equal_norm_random", "sham", "unrelated")
    rows = _rows(directions=directions)
    for row in rows:
        if row["direction"]["kind"] == "semantic" and row["affected"]:
            row["cells"]["C"]["candidate_logits"] = [0.0, -1.0 - 2.0 * row["horizon"]]
    result = _summary(rows, directions=directions)
    semantic = result["directions"]["semantic"]["affected"]
    assert semantic["endpoint"]["value"] == -4.0
    assert semantic["signed_auc"]["value"] == -4.0
    gate = metrics.semantic_qualification(result, threshold_plan=_thresholds())
    assert gate["qualified"] is False
    assert gate["checks"]["signed_endpoint_family_ci"] is False
    assert gate["absolute_only_semantic_pass"] is False


def test_positive_semantic_direction_must_beat_all_controls_and_retain_unaffected() -> None:
    directions = ("semantic", "equal_norm_random", "sham", "unrelated")
    result = _summary(_rows(directions=directions), directions=directions)
    gate = metrics.semantic_qualification(result, threshold_plan=_thresholds())
    assert gate["status"] == "QUALIFIED_SIGNED_SEMANTIC_TRAJECTORY"
    assert gate["qualified"] is True
    assert all(gate["checks"].values())
    assert result["unaffected_retention"]["row_count"] > 0
    for check in result["unaffected_retention"]["checks"].values():
        assert check["value"] == 1.0
        assert check["family_cluster"]["ci95"] == [1.0, 1.0]


def test_nonsemantic_mechanical_screen_is_never_semantically_qualified() -> None:
    result = _summary(_rows())
    gate = metrics.semantic_qualification(result, threshold_plan=_thresholds())
    assert gate["status"] == "NOT_APPLICABLE_NON_SEMANTIC_SCREEN"
    assert gate["qualified"] is False


def test_single_random_direction_first_canary_is_complete_but_nonsemantic() -> None:
    rows = _rows(families=1, probes=("affected",), directions=("equal_norm_random",))
    result = _summary(
        rows,
        families=1,
        probes=1,
        directions=("equal_norm_random",),
    )
    assert result["mechanical_screen_complete"] is True
    assert metrics.mechanical_return_gate(
        result, instrument_ok=True, integrity_ok=True
    )["return_allowed"]
    assert metrics.semantic_qualification(
        result, threshold_plan=_thresholds()
    )["status"] == "NOT_APPLICABLE_NON_SEMANTIC_SCREEN"


def test_mechanical_return_gate_ignores_directional_outcome_but_not_integrity() -> None:
    result = _summary(_rows())
    passed = metrics.mechanical_return_gate(result, instrument_ok=True, integrity_ok=True)
    assert passed["return_allowed"] is True
    assert passed["semantic_accuracy_or_directionality_is_prerequisite"] is False
    blocked = metrics.mechanical_return_gate(result, instrument_ok=False, integrity_ok=True)
    assert blocked["return_allowed"] is False
    assert blocked["blocking_checks"] == ["instrument_ok"]


def test_finite_ties_are_categorical_unknown_but_keep_continuous_trajectory() -> None:
    rows = _rows()
    rows[0]["cells"]["B"]["candidate_logits"] = [0.0, 0.0]
    result = _summary(rows)
    assert result["measurements"]["categorical_unknown_count"] == 1
    assert result["measurements"]["categorical_unknown_reason_counts"] == {"TIE_FP32": 1}
    assert result["measurements"]["complete"] is True
    assert result["mechanical_screen_complete"] is True


@pytest.mark.parametrize("value", [None, [float("nan"), 0.0], [float("inf"), 0.0], []])
def test_missing_nonfinite_logits_remain_unknown_and_block_mechanical_completion(
    value: object,
) -> None:
    rows = _rows()
    rows[0]["cells"]["C"]["candidate_logits"] = value
    result = _summary(rows)
    assert result["measurements"]["complete"] is False
    assert result["mechanical_screen_complete"] is False
    gate = metrics.mechanical_return_gate(result, instrument_ok=True, integrity_ok=True)
    assert gate["return_allowed"] is False
    assert "measurements_complete" in gate["blocking_checks"]
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("field", ["state_displacement", "kv_displacement"])
def test_state_and_kv_missingness_are_independent_unknowns(field: str) -> None:
    rows = _rows()
    rows[0]["cells"]["B"][field] = None
    result = _summary(rows)
    assert result["measurements"]["displacement"][field]["B"]["unknown_count"] == 1
    other = "kv_displacement" if field == "state_displacement" else "state_displacement"
    assert result["measurements"]["displacement"][other]["B"]["unknown_count"] == 0
    assert result["measurements"]["complete"] is False


def test_changed_tokens_positions_or_masks_fail_matched_protocol() -> None:
    for field, changed in (
        ("token_ids", [101, 999]),
        ("position_ids", [0, 2]),
        ("attention_mask", [1, 0]),
    ):
        rows = _rows()
        rows[0]["cells"]["E"][field] = changed
        result = _summary(rows)
        assert result["protocol"]["valid"] is False
        assert any(field in error for error in result["protocol"]["errors"][0]["errors"])
        assert result["mechanical_screen_complete"] is False


def test_continuous_forcing_cannot_be_relabelled_as_one_pulse() -> None:
    rows = _rows()
    rows[0]["cells"]["C"]["forcing_mode"] = "continuous"
    rows[0]["cells"]["C"]["pulse_count"] = 3
    result = _summary(rows)
    assert result["protocol"]["valid"] is False
    errors = result["protocol"]["errors"][0]["errors"]
    assert any("forcing_mode" in error for error in errors)
    assert any("pulse_count" in error for error in errors)
    assert result["protocol"]["continuous_forcing_permitted"] is False


def test_query_probe_change_across_horizon_or_direction_is_protocol_failure() -> None:
    rows = _rows()
    target = next(
        row
        for row in rows
        if row["direction"]["kind"] == "equal_norm_random" and row["horizon"] == 1
    )
    target["probe_token_ids"] = [999]
    result = _summary(rows)
    assert result["protocol"]["valid"] is False
    flattened = [error for item in result["protocol"]["errors"] for error in item["errors"]]
    assert "query_probe_direction_metadata_changed_across_horizons" in flattened
    assert "query_probe_metadata_changed_across_directions" in flattened


@pytest.mark.parametrize(
    "kind,pulse,verified",
    [
        ("equal_norm_random", 2.0, True),
        ("unrelated", 1.0, False),
        ("sham", 1.0, False),
        ("sham", 0.0, True),
    ],
)
def test_invalid_equal_norm_or_sham_metadata_fails_protocol(
    kind: str, pulse: float, verified: bool
) -> None:
    directions = (kind,) if kind != "unrelated" else ("unrelated",)
    rows = _rows(directions=directions)
    for row in rows:
        row["direction"]["pulse_norm"] = pulse
        row["direction"]["equal_norm_verified"] = verified
    result = _summary(rows, directions=directions)
    assert result["protocol"]["valid"] is False
    assert result["mechanical_screen_complete"] is False


def test_equal_norm_metadata_is_matched_across_direction_controls() -> None:
    directions = ("semantic", "equal_norm_random", "sham", "unrelated")
    rows = _rows(directions=directions)
    for row in rows:
        if row["direction"]["kind"] == "equal_norm_random":
            row["direction"]["pulse_norm"] = 2.0
            row["direction"]["reference_norm"] = 2.0
    result = _summary(rows, directions=directions)
    assert result["protocol"]["valid"] is False
    flattened = [error for item in result["protocol"]["errors"] for error in item["errors"]]
    assert "reference_norm_not_matched_across_directions" in flattened
    assert "pulse_norm_not_matched_across_directions" in flattened


def test_missing_whole_row_preserves_expected_denominator_and_unknown_interval() -> None:
    rows = _rows()
    rows.pop()
    result = _summary(rows)
    assert result["coverage"]["complete"] is False
    assert result["coverage"]["missing_rows"] == 1
    assert result["mechanical_screen_complete"] is False
    interval = result["directions"]["sham"]["affected"]["endpoint"]
    assert interval["status"] == "UNKNOWN_INCOMPLETE_FAMILY_COVERAGE"
    assert interval["ci95"] is None


def test_duplicate_row_and_observations_outside_frozen_plan_are_rejected() -> None:
    rows = _rows()
    with pytest.raises(ValueError, match="duplicate trajectory row"):
        _summary([*rows, copy.deepcopy(rows[0])])
    rows = _rows()
    rows[0]["horizon"] = 7
    with pytest.raises(ValueError, match="outside frozen plan"):
        _summary(rows)


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda row: row.update(affected=False), "affected disagrees"),
        (lambda row: row.update(fixed_continuation="yes"), "fixed_continuation"),
        (lambda row: row["cells"].pop("E"), "exactly A, B, C, D, E"),
        (lambda row: row["cells"]["B"].update(token_ids=[True, 2]), "integer sequence"),
    ],
)
def test_malformed_structural_schema_is_rejected(mutation, match: str) -> None:
    rows = _rows()
    mutation(rows[0])
    with pytest.raises(ValueError, match=match):
        _summary(rows)


def test_bootstrap_is_deterministic_under_row_reversal() -> None:
    rows = _rows(directions=("semantic", "equal_norm_random", "sham", "unrelated"))
    direct = _summary(
        rows, directions=("semantic", "equal_norm_random", "sham", "unrelated")
    )
    reversed_result = _summary(
        list(reversed(rows)),
        directions=("semantic", "equal_norm_random", "sham", "unrelated"),
    )
    assert direct == reversed_result


def test_unfrozen_semantic_threshold_plan_cannot_qualify() -> None:
    directions = ("semantic", "equal_norm_random", "sham", "unrelated")
    result = _summary(_rows(directions=directions), directions=directions)
    gate = metrics.semantic_qualification(result, threshold_plan=_thresholds(frozen=False))
    assert gate["status"] == "UNKNOWN_NOT_PREDECLARED"
    assert gate["qualified"] is False
    assert gate["checks"]["plan_frozen_before_measurement"] is False


def test_fp32_operands_are_used_before_subtraction() -> None:
    rows = _rows(families=1, probes=("affected",))
    row = rows[0]
    row["cells"]["B"]["candidate_logits"] = [16777216.0, 16777217.0]
    row["cells"]["C"]["candidate_logits"] = [16777216.0, 16777218.0]
    result = _summary(rows, families=1, probes=1)
    first = next(
        item
        for item in result["trajectories"]
        if item["direction_kind"] == "equal_norm_random"
    )["trajectory"]["points"][0]
    # B rounds to a tie/margin zero, while C rounds to a margin two in FP32.
    assert first["central_contrast"] == 2.0
