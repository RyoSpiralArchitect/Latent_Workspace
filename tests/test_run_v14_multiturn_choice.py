from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import run_v14_multiturn_choice as multiturn  # noqa: E402


def test_frozen_plan_validates_without_remote_checkpoints() -> None:
    plan = json.loads(multiturn.PLAN_PATH.read_text(encoding="utf-8"))
    paths = multiturn.validate_plan(
        REPO,
        plan,
        require_fresh=False,
        verify_checkpoints=False,
    )
    assert paths["output"] == REPO / plan["output"]
    assert set(paths["models"]) == {"task", "semantic"}
    assert plan["expected_trajectories"] == 896
    assert plan["expected_turn_rows"] == 3584


def test_plan_rejects_history_cache_or_promotion_drift() -> None:
    plan = json.loads(multiturn.PLAN_PATH.read_text(encoding="utf-8"))
    for key, value in (
        ("history_modes", ["free_history"]),
        ("kv_cache", True),
        ("semantic_promotion", True),
    ):
        changed = copy.deepcopy(plan)
        changed[key] = value
        with pytest.raises(multiturn.MultiTurnError, match="Frozen plan mismatch"):
            multiturn.validate_plan(
                REPO,
                changed,
                require_fresh=False,
                verify_checkpoints=False,
            )


def test_matched_uniform_and_choice_sampler_are_deterministic() -> None:
    first = multiturn._matched_uniform(211, "w0_s0", 2)
    assert first == multiturn._matched_uniform(211, "w0_s0", 2)
    assert first != multiturn._matched_uniform(212, "w0_s0", 2)
    assert first != multiturn._matched_uniform(211, "w0_s1", 2)
    choice, probabilities = multiturn._sample_choice([0.0, 2.0], temperature=0.0, uniform=None)
    assert choice == 1
    assert sum(probabilities) == pytest.approx(1.0)
    low, _ = multiturn._sample_choice([0.0, 0.0], temperature=0.7, uniform=0.25)
    high, _ = multiturn._sample_choice([0.0, 0.0], temperature=0.7, uniform=0.75)
    assert (low, high) == (0, 1)


def _synthetic_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    scenarios = ("w0_s0", "w0_s1", "w1_s0", "w1_s1")
    for condition in multiturn.CONDITIONS:
        for scenario in scenarios:
            for history_mode in multiturn.HISTORY_MODES:
                for regime in multiturn.REGIMES:
                    for readout in multiturn.READOUTS:
                        labels = [1, 1, 1, 1]
                        if (
                            condition["id"] == "semantic_full_twin"
                            and history_mode == "free_history"
                            and readout == "fp32_choice_head"
                        ):
                            labels[2] = 0
                        turns = []
                        for turn_index, choice in enumerate(labels):
                            affected = turn_index in (0, 2)
                            original = 1
                            donor = 0 if affected else 1
                            target = donor if condition["memory"] == "twin" else original
                            turns.append(
                                {
                                    "turn_index": turn_index,
                                    "choice_label": choice,
                                    "target_correct": choice == target,
                                    "original_correct": choice == original,
                                    "donor_correct": choice == donor,
                                    "donor_label": donor,
                                    "analysis_margin": (
                                        0.5 if condition["memory"] == "twin" else 0.0
                                    ),
                                }
                            )
                        rows.append(
                            {
                                "condition": condition["id"],
                                "model": condition["model"],
                                "route": condition["route"],
                                "memory": condition["memory"],
                                "scenario": scenario,
                                "history_mode": history_mode,
                                "regime": regime["id"],
                                "selected_readout": readout,
                                "generated_labels": labels,
                                "generated_text": ["yes" if value else "no" for value in labels],
                                "turns": turns,
                            }
                        )
    return rows


def test_summary_closes_every_predeclared_pair_without_promotion() -> None:
    rows = _synthetic_rows()
    assert len(rows) == 896
    summary = multiturn._summarize(rows)
    pair = summary["intact_twin_trajectory_pairs"][
        "semantic|full_route|free_history|fp32_choice_head"
    ]
    assert pair["pair_count"] == 16
    assert pair["trajectory_changed_pairs"] == 16
    assert pair["first_turn_same_then_later_changed_pairs"] == 16
    precision_pair = summary["native_fp32_trajectory_pairs"]["semantic_full_twin|free_history"]
    assert precision_pair["trajectory_changed_pairs"] == 16
    assert summary["winner"] == "none"
