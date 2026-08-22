from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

finalize = importlib.import_module("finalize_v11_f1_o0_refinement")


def _metric_rows(max_steps: int, eval_every: int, *, amputated: bool) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [{"event": "start", "step": 0}]
    rows.append({"split": "eval-step0", "step": 0})
    for step in range(1, max_steps + 1):
        rows.append({"split": "train", "step": step})
        if step % eval_every == 0:
            rows.append({"split": "eval", "step": step})
    rows.append({"split": "eval-final", "step": max_steps})
    if amputated:
        rows.append({"split": "eval-final-amputated", "step": max_steps})
    return rows


def test_exact_metric_sequence_supports_stage4_and_refinement() -> None:
    finalize.exact_metric_sequence(
        _metric_rows(4, 1, amputated=True),
        max_steps=4,
        eval_every=1,
        amputated=True,
    )
    finalize.exact_metric_sequence(
        _metric_rows(16, 4, amputated=False),
        max_steps=16,
        eval_every=4,
        amputated=False,
    )


def test_exact_metric_sequence_rejects_hidden_extra_event() -> None:
    rows = _metric_rows(16, 4, amputated=True)
    rows.insert(3, {"event": "unfrozen", "step": 1})
    with pytest.raises(finalize.FinalizeError, match="leading step-0 start event"):
        finalize.exact_metric_sequence(
            rows,
            max_steps=16,
            eval_every=4,
            amputated=True,
        )


def test_schedule_chain_accepts_exact_cosine_chain() -> None:
    rows = [
        {"applied": 1.0, "post": 0.75},
        {"applied": 0.75, "post": 0.25},
        {"applied": 0.25, "post": 0.1},
        {"applied": 0.1, "post": 0.0},
    ]
    result = finalize.schedule_chain(
        rows,
        configured=1.0,
        applied_key="applied",
        post_key="post",
        max_steps=4,
    )
    assert result["passed"] is True


def _cell(*, behavior: float, accuracy: float, recall: float) -> dict[str, object]:
    return {
        "behavior": {"task_accuracy": behavior},
        "final_metrics": {
            "functional_query_accuracy": accuracy,
            "functional_label_0_recall": recall,
            "functional_label_1_recall": recall + 0.1,
        },
    }


def test_paired_noninferiority_uses_frozen_one_sided_margins() -> None:
    margins = {
        "behavior_task_accuracy": 0.03125,
        "complete_eval_accuracy": 0.02,
        "minimum_label_recall": 0.03,
    }
    result = finalize.paired_noninferiority(
        _cell(behavior=0.84, accuracy=0.78, recall=0.72),
        _cell(behavior=0.82, accuracy=0.765, recall=0.70),
        margins,
    )
    assert result["passed"] is True
    failed = finalize.paired_noninferiority(
        _cell(behavior=0.84, accuracy=0.78, recall=0.72),
        _cell(behavior=0.80, accuracy=0.765, recall=0.70),
        margins,
    )
    assert failed["passed"] is False


@pytest.mark.parametrize(
    ("f1", "o0", "competitive", "specific", "rule"),
    [
        (True, True, True, True, "scale_content_specific_o0"),
        (True, True, True, False, "sharpen_semantics"),
        (True, True, False, True, "stabilize_active_route"),
        (True, False, False, False, "redesign_route"),
        (False, False, False, False, "repair_shared_optimizer"),
        (False, False, False, True, "repair_shared_optimizer"),
    ],
)
def test_v12_decision_rules_are_mutually_resolved(
    f1: bool, o0: bool, competitive: bool, specific: bool, rule: str
) -> None:
    result = finalize.choose_v12_design(
        f1_robust=f1,
        o0_robust=o0,
        o0_competitive=competitive,
        content_specific_replicated=specific,
    )
    assert result["rule_id"] == rule


def test_necessity_summary_requires_f0_and_classifies_content() -> None:
    ladder = {
        "F0_engineering": {"passed": True},
        "F1_deferred_sufficiency": {"passed": True},
        "F2_carrier_insufficiency": {"passed": True},
        "F3_counterfactual_direction": {"passed": True},
        "F4_local_causal_specificity": {"passed": True},
        "F5_heldout_query_generalization": {"passed": False},
    }
    receipt = {
        "format": finalize.NECESSITY_FORMAT,
        "modes": [
            "intact",
            "hard_bypass",
            "zero",
            "global_mean",
            "fixed_carrier",
            "norm_matched_random",
            "token_shuffle",
            "counterfactual_twin",
            "cross_world_shuffle",
        ],
        "evidence_ladder": ladder,
        "primary_gate_passed": True,
    }
    assert finalize.necessity_summary(receipt)["content_specific"] is True
    ladder["F0_engineering"]["passed"] = False
    with pytest.raises(finalize.FinalizeError, match="coverage failed"):
        finalize.necessity_summary(receipt)
