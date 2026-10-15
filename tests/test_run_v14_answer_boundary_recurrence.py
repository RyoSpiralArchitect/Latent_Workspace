from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
import torch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import run_v14_answer_boundary_recurrence as recurrence  # noqa: E402
import verify_v14_answer_boundary_recurrence as recovery  # noqa: E402


def test_frozen_plan_validates_without_remote_checkpoints() -> None:
    plan = json.loads(recurrence.PLAN_PATH.read_text(encoding="utf-8"))
    paths = recurrence.validate_plan(
        REPO,
        plan,
        require_fresh=False,
        verify_checkpoints=False,
    )
    assert paths["output"] == REPO / plan["output"]
    assert set(paths["models"]) == {"task", "semantic"}


def test_plan_rejects_lane_drift() -> None:
    plan = json.loads(recurrence.PLAN_PATH.read_text(encoding="utf-8"))
    changed = copy.deepcopy(plan)
    changed["lanes"]["cache"].remove("one_shot_reset")
    with pytest.raises(recurrence.RecurrenceError, match="Frozen plan mismatch"):
        recurrence.validate_plan(
            REPO,
            changed,
            require_fresh=True,
            verify_checkpoints=False,
        )


def test_readout_and_pair_effect_keep_donor_sign() -> None:
    intact = recurrence._readout(
        torch.tensor([0.0, 3.0, 1.0, 4.0]),
        (1, 3),
        original_label=0,
        donor_label=1,
        affected=True,
    )
    twin = recurrence._readout(
        torch.tensor([0.0, 2.0, 1.0, 6.0]),
        (1, 3),
        original_label=0,
        donor_label=1,
        affected=True,
    )
    assert intact["donor_margin"] == 1.0
    assert twin["donor_margin"] == 4.0
    assert recurrence._pair_effect(intact, twin, affected=True) == 3.0


def test_gram_matched_random_pair_preserves_full_gram() -> None:
    intact = torch.tensor([1.0, -2.0, 0.5, 4.0])
    twin = torch.tensor([-0.5, 1.0, 3.0, 2.0])
    random_intact, random_twin, receipt = recurrence._gram_matched_random_pair(
        intact, twin, seed=17
    )
    assert random_intact.shape == intact.shape
    assert random_twin.shape == twin.shape
    assert receipt["relative_error"]["maximum"] < 1e-6


class _TinyRMSNorm(torch.nn.Module):
    def __init__(self, width: int) -> None:
        super().__init__()
        self.weight = torch.nn.Parameter(torch.ones(width, dtype=torch.bfloat16))
        self.variance_epsilon = 1e-5

    def forward(self, hidden: torch.Tensor) -> torch.Tensor:
        value = hidden.float()
        value = value * torch.rsqrt(value.pow(2).mean(dim=-1, keepdim=True) + self.variance_epsilon)
        return (value * self.weight.float()).to(hidden.dtype)


def test_visibility_separates_requested_and_native_bf16_delta() -> None:
    hidden = torch.tensor([[[1.0, 2.0, 4.0, 8.0]]], dtype=torch.bfloat16)
    requested = torch.tensor([0.001, 0.02, 0.0, -0.2])
    modified, receipt = recurrence._compose_and_visibility(hidden, requested, _TinyRMSNorm(4))
    assert modified.dtype == torch.bfloat16
    assert receipt["requested_nonzero_components"] == 3
    assert 0 < receipt["lost_requested_components"] < 3
    assert receipt["actual_native_delta"]["nonzero"] is True
    assert receipt["rmsnorm"]["native_delta"]["finite"] is True


def _pair(value: float) -> dict[str, object]:
    return {
        "intact": {},
        "twin": {},
        "signed_pair_effect": value,
    }


def _synthetic_rows() -> list[dict[str, object]]:
    visibility = {
        "lost_requested_fraction": 0.25,
        "actual_native_delta": {"rms": 0.01},
        "rmsnorm": {"native_delta": {"rms": 0.02}},
        "ulp_ratio": {"q50": 0.75},
    }
    rows: list[dict[str, object]] = []
    for model in recurrence.MODEL_ORDER:
        for case_index in range(8):
            affected = case_index < 4
            for control in recurrence.CONTROLS:
                for horizon in recurrence.HORIZONS:
                    value = float(horizon + 1) if control == "learned_pair" else 0.0
                    full_route = _pair(value) if control == "learned_pair" else None
                    repeated = _pair(value)
                    repeated["intact"] = {"visibility": visibility}
                    repeated["twin"] = {"visibility": visibility}
                    rows.append(
                        {
                            "model": model,
                            "case_id": f"case-{case_index}",
                            "control": control,
                            "affected": affected,
                            "horizon": horizon,
                            "no_cache": {
                                "one_shot_last_token": _pair(value if horizon == 0 else 0.0),
                                "repeated_last_token": repeated,
                                "repeated_full_route_reference": full_route,
                                "answer_projection_at_horizon_zero": (
                                    {
                                        "observed_pair_effect": value,
                                        "local_linear_pair_prediction": value / 2,
                                        "raw_unembedding_pair_projection": value / 4,
                                    }
                                    if horizon == 0
                                    else None
                                ),
                            },
                            "cache": {
                                "one_shot_carry": _pair(value),
                                "one_shot_reset": _pair(0.0),
                                "repeated_carry": _pair(value),
                                "repeated_reset_before_current_read": _pair(value / 2),
                                "one_shot_history_effect": value,
                                "repeated_history_effect": value / 2,
                            },
                        }
                    )
    return rows


def test_summary_consumes_all_320_frozen_rows() -> None:
    rows = _synthetic_rows()
    assert len(rows) == 320
    summary = recurrence._summarize(rows)
    selected = summary["signed_contrasts_by_horizon"]["semantic"]["learned_pair"]
    assert selected["affected"]["4"]["no_cache_repeated_last_token"]["count"] == 4
    assert (
        summary["affected_endpoint_and_auc"]["task"]["learned_pair"]["cache_repeated_history"][
            "trapezoid_auc"
        ]["count"]
        == 4
    )
    assert summary["winner"] == "none"


def test_verifier_recovery_preserves_raw_no_winner_report() -> None:
    plan = json.loads(recovery.PLAN_PATH.read_text(encoding="utf-8"))
    result = recovery.recover(plan, require_fresh=False)
    assert result["status"] == "QUALIFIED_VERIFIER_RECOVERY"
    assert result["recovered_mechanical_execution_qualified"] is True
    assert result["target_model_reexecuted"] is False
    assert result["scientific_values_recomputed_or_selected"] is False
    assert result["winner"] == "none"
