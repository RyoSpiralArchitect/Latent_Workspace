from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
import torch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import run_v14_position_composition as composition  # noqa: E402


def test_frozen_plan_validates_without_remote_checkpoints() -> None:
    plan = json.loads(composition.PLAN_PATH.read_text(encoding="utf-8"))
    paths = composition.validate_plan(
        REPO,
        plan,
        require_fresh=False,
        verify_checkpoints=False,
    )
    assert paths["output"] == REPO / plan["output"]
    assert set(paths["models"]) == {"task", "semantic"}


def test_plan_rejects_oracle_promotion_drift() -> None:
    plan = json.loads(composition.PLAN_PATH.read_text(encoding="utf-8"))
    changed = copy.deepcopy(plan)
    changed["oracle_lanes_eligible_for_architecture_selection"] = True
    with pytest.raises(composition.CompositionError, match="Frozen plan mismatch"):
        composition.validate_plan(
            REPO,
            changed,
            require_fresh=False,
            verify_checkpoints=False,
        )


def test_position_masks_form_both_frozen_partitions() -> None:
    length = 9
    start = 5
    full = composition._lane_mask("full_route", sequence_length=length, current_query_start=start)
    boundary = composition._lane_mask(
        "answer_boundary_only", sequence_length=length, current_query_start=start
    )
    non_boundary = composition._lane_mask(
        "non_boundary_only", sequence_length=length, current_query_start=start
    )
    current = composition._lane_mask(
        "current_query_only", sequence_length=length, current_query_start=start
    )
    history = composition._lane_mask(
        "prior_history_only", sequence_length=length, current_query_start=start
    )
    torch.testing.assert_close(boundary + non_boundary, full, rtol=0.0, atol=0.0)
    torch.testing.assert_close(current + history, full, rtol=0.0, atol=0.0)
    assert int(boundary.sum().item()) == 1
    assert int(current.sum().item()) == length - start


def test_horizon_zero_current_query_is_full_and_history_is_empty() -> None:
    full = composition._lane_mask("full_route", sequence_length=7, current_query_start=0)
    current = composition._lane_mask("current_query_only", sequence_length=7, current_query_start=0)
    history = composition._lane_mask("prior_history_only", sequence_length=7, current_query_start=0)
    assert torch.equal(full, current)
    assert int(history.sum().item()) == 0


def test_global_answer_axis_and_residual_reconstruct_and_are_orthogonal() -> None:
    request = torch.tensor([[1.0, -2.0, 0.5], [4.0, 1.0, -3.0]])
    gradient = torch.tensor([[2.0, 0.25, -1.0], [0.5, -2.0, 3.0]])
    axis, residual, receipt = composition._axis_decomposition(request, gradient)
    torch.testing.assert_close(axis + residual, request, rtol=0.0, atol=1e-7)
    assert receipt["residual_normalized_orthogonality_error"] < 1e-7
    assert receipt["architecture_selection_eligible"] is False


def test_positionwise_random_pair_preserves_every_token_gram() -> None:
    intact = torch.tensor([[1.0, -2.0, 0.5, 4.0], [3.0, 0.5, -1.0, 2.0], [0.2, 0.4, 0.7, -0.8]])
    twin = torch.tensor([[-0.5, 1.0, 3.0, 2.0], [0.2, -1.5, 2.5, 0.5], [1.2, -0.7, 0.1, 0.4]])
    random_intact, random_twin, receipt = composition._positionwise_gram_random_pair(
        intact, twin, seed=31
    )
    assert random_intact.shape == intact.shape
    assert random_twin.shape == twin.shape
    assert receipt["maximum_normalized_gram_error"] < 1e-6


def test_positionwise_unrelated_rms_match_preserves_each_token_norm() -> None:
    source = torch.tensor([[1.0, 2.0, 3.0], [0.5, -1.0, 0.25]])
    target = torch.tensor([[4.0, 0.0, -2.0], [3.0, 1.0, 2.0]])
    matched, receipt = composition._positionwise_rms_match(source, target)
    torch.testing.assert_close(
        torch.linalg.vector_norm(matched, dim=-1),
        torch.linalg.vector_norm(target, dim=-1),
        rtol=1e-6,
        atol=1e-6,
    )
    assert receipt["maximum_relative_rms_error"] < 1e-6


def _member(effect: float) -> dict[str, object]:
    return {
        "signed_pair_effect": effect,
        "local_linear_pair_prediction": effect / 2,
    }


def _synthetic_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for model in composition.MODEL_ORDER:
        for case_index in range(8):
            affected = case_index < 4
            for control in composition.CONTROLS:
                for horizon in composition.HORIZONS:
                    value = float(horizon + 1) if control == "learned_pair" else 0.0
                    rows.append(
                        {
                            "model": model,
                            "case_id": f"case-{case_index}",
                            "control": control,
                            "affected": affected,
                            "horizon": horizon,
                            "lanes": {lane: _member(value) for lane in composition.LANES},
                            "composition": {
                                "boundary_non_boundary_observed_interaction": value,
                                "boundary_non_boundary_local_linear_reconstruction_error": 0.0,
                                "current_history_observed_interaction": value,
                                "current_history_local_linear_reconstruction_error": 0.0,
                                "oracle_axis_residual_observed_interaction": value,
                                "boundary_minus_full_effect": 0.0,
                                "positive_boundary_to_negative_full_reversal": False,
                            },
                        }
                    )
    return rows


def test_summary_consumes_all_320_rows_without_promotion() -> None:
    rows = _synthetic_rows()
    assert len(rows) == 320
    summary = composition._summarize(rows)
    focus = summary["predeclared_predecessor_focus_semantic_affected_h4"]
    assert focus["answer_boundary_only"]["count"] == 4
    assert summary["winner"] == "none"
    assert summary["oracle_lanes"]["architecture_selection_eligible"] is False
