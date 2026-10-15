from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
import torch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import run_v14_readout_precision as precision  # noqa: E402


def test_frozen_plan_validates_without_remote_checkpoints() -> None:
    plan = json.loads(precision.PLAN_PATH.read_text(encoding="utf-8"))
    paths = precision.validate_plan(
        REPO,
        plan,
        require_fresh=False,
        verify_checkpoints=False,
    )
    assert paths["output"] == REPO / plan["output"]
    assert paths["position_report"]["row_count"] == 320
    assert set(paths["models"]) == {"task", "semantic"}


def test_plan_rejects_head_or_generation_drift() -> None:
    plan = json.loads(precision.PLAN_PATH.read_text(encoding="utf-8"))
    for key, value in (
        ("same_normalized_hidden_for_both_heads", False),
        ("free_generation", True),
        ("lane_selection_after_scoring", True),
    ):
        changed = copy.deepcopy(plan)
        changed[key] = value
        with pytest.raises(precision.PrecisionAssayError, match="Frozen plan mismatch"):
            precision.validate_plan(
                REPO,
                changed,
                require_fresh=False,
                verify_checkpoints=False,
            )


def test_fp32_choice_readout_preserves_direction_contract() -> None:
    affected = precision._choice_readout(
        torch.tensor([[[1.25, 2.5]]]),
        (17, 29),
        original_label=0,
        donor_label=1,
        affected=True,
    )
    assert affected["candidate_token_ids"] == [17, 29]
    assert affected["prediction"] == 1
    assert affected["donor_margin"] == 1.25
    assert affected["analysis_margin"] == 1.25

    unaffected = precision._choice_readout(
        torch.tensor([[[2.5, 1.25]]]),
        (17, 29),
        original_label=0,
        donor_label=0,
        affected=False,
    )
    assert unaffected["prediction"] == 0
    assert unaffected["donor_margin"] is None
    assert unaffected["analysis_margin"] == 1.25


def _synthetic_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for model in precision.MODEL_ORDER:
        for case_index in range(8):
            affected = case_index < 4
            for control in precision.CONTROLS:
                for horizon in precision.HORIZONS:
                    value = float(horizon + 1) if control == "learned_pair" else 0.0
                    lanes = {
                        lane: {
                            readout: {"signed_pair_effect": value} for readout in precision.READOUTS
                        }
                        for lane in precision.LANES
                    }
                    interactions = {
                        readout: {
                            "boundary_non_boundary": value,
                            "current_query_prior_history": value,
                            "oracle_axis_orthogonal": value,
                        }
                        for readout in precision.READOUTS
                    }
                    interactions["native_minus_fp32_boundary_non_boundary"] = 0.0
                    rows.append(
                        {
                            "model": model,
                            "case_id": f"case-{case_index}",
                            "control": control,
                            "affected": affected,
                            "horizon": horizon,
                            "lanes": lanes,
                            "interactions": interactions,
                        }
                    )
    return rows


def test_summary_consumes_all_cells_and_requires_multi_turn_followup() -> None:
    rows = _synthetic_rows()
    assert len(rows) == 320
    summary = precision._summarize(rows)
    focus = summary["predeclared_semantic_affected_h4"]
    assert focus["full_route"]["native_bf16_head"]["count"] == 4
    assert focus["full_route"]["fp32_choice_head"]["mean"] == 5.0
    assert summary["multi_turn_followup_required_regardless_of_result"] is True
    assert summary["winner"] == "none"
