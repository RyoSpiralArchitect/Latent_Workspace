from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

finalize = importlib.import_module("finalize_v11_step4_promotion")


def eval_row(
    *,
    loss: float = 0.57,
    full_vocab: float = 0.75,
    accuracy: float = 0.76,
    recall0: float = 0.77,
    recall1: float = 0.74,
    distinct: int = 2,
) -> dict[str, float]:
    return {
        "functional_choice_loss": loss,
        "functional_full_vocab_loss": full_vocab,
        "functional_query_accuracy": accuracy,
        "functional_label_0_recall": recall0,
        "functional_label_1_recall": recall1,
        "functional_distinct_predicted_classes": float(distinct),
        "functional_prediction_entropy_nats": 0.69,
        "functional_yes_minus_no_gap": 0.14,
        "functional_hop_1_accuracy": 0.68,
    }


def gates() -> dict[str, float | int | bool]:
    return {
        "minimum_accuracy": 0.7,
        "minimum_distinct_predicted_classes": 2,
        "minimum_label_recall": 0.6,
        "require_behavior_veto_pass": True,
        "require_final_choice_loss_below_step0": True,
        "maximum_final_full_vocab_loss": 1.5,
    }


def test_promotion_gate_evaluation_passes_frozen_thresholds() -> None:
    checks = finalize.promotion_gate_evaluation(
        eval_row(loss=0.675, full_vocab=0.843),
        eval_row(),
        behavior_passed=True,
        gates=gates(),
    )
    assert all(check["passed"] for check in checks)


def test_promotion_gate_evaluation_rejects_metric_and_behavior_failures() -> None:
    checks = finalize.promotion_gate_evaluation(
        eval_row(loss=0.675, full_vocab=0.843),
        eval_row(loss=0.7, full_vocab=1.6, accuracy=0.69, recall1=0.59, distinct=1),
        behavior_passed=False,
        gates=gates(),
    )
    assert {check["id"] for check in checks if not check["passed"]} == {
        "minimum_accuracy",
        "minimum_distinct_predicted_classes",
        "minimum_label_recall",
        "final_choice_loss_below_step0",
        "maximum_final_full_vocab_loss",
        "behavior_veto",
    }


def test_learning_rate_chain_requires_exact_scheduler_continuity() -> None:
    rows = [
        {"applied_lr_base": 2e-7, "lr_base": 1.7e-7},
        {"applied_lr_base": 1.7e-7, "lr_base": 1e-7},
        {"applied_lr_base": 1e-7, "lr_base": 3e-8},
        {"applied_lr_base": 3e-8, "lr_base": 0.0},
    ]
    assert finalize.learning_rate_chain(rows, 2e-7)["passed"] is True
    rows[2]["applied_lr_base"] = 9e-8
    assert finalize.learning_rate_chain(rows, 2e-7)["passed"] is False


def test_exact_metric_sequence_accepts_only_one_leading_start_event() -> None:
    rows: list[dict[str, object]] = [{"event": "start", "step": 0}]
    rows.append({"split": "eval-step0", "step": 0})
    for step in range(1, 5):
        rows.extend(
            (
                {"split": "train", "step": step},
                {"split": "eval", "step": step},
            )
        )
    rows.append({"split": "eval-final", "step": 4})
    finalize._exact_metric_sequence(rows)

    rows.insert(1, {"event": "unexpected", "step": 0})
    try:
        finalize._exact_metric_sequence(rows)
    except finalize.FinalizeError:
        pass
    else:
        raise AssertionError("unknown telemetry must fail closed")
