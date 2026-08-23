from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

finalize = importlib.import_module("finalize_v11_update_response_surface")


def eval_row(
    loss: float = 0.67,
    full_vocab: float = 0.9,
    accuracy: float = 0.78,
    recall0: float = 0.7,
    recall1: float = 0.86,
    distinct: int = 2,
) -> dict[str, float]:
    return {
        "functional_choice_loss": loss,
        "functional_full_vocab_loss": full_vocab,
        "functional_query_accuracy": accuracy,
        "functional_label_0_recall": recall0,
        "functional_label_1_recall": recall1,
        "functional_distinct_predicted_classes": float(distinct),
        "functional_prediction_entropy_nats": 0.67,
        "functional_yes_minus_no_gap": 1.0,
        "functional_hop_1_accuracy": 0.68,
    }


def gates() -> dict[str, float | int]:
    return {
        "minimum_distinct_predicted_classes": 2,
        "minimum_accuracy": 0.75,
        "minimum_label_recall": 0.6,
        "maximum_choice_loss_increase": 0.02,
        "maximum_full_vocab_loss_increase": 0.25,
    }


def test_gate_evaluation_rejects_constant_choice_and_noop() -> None:
    checks = finalize.gate_evaluation(
        eval_row(loss=0.675, full_vocab=0.843),
        eval_row(loss=0.693, full_vocab=1.0, accuracy=0.5, recall0=0.0, recall1=1.0, distinct=1),
        changed_elements=0,
        gates=gates(),
    )
    failed = {check["id"] for check in checks if not check["passed"]}
    assert failed == {
        "nonzero_persisted_base_update",
        "minimum_distinct_predicted_classes",
        "minimum_accuracy",
        "minimum_label_recall",
    }


def test_completion_diagnostics_detects_repetition() -> None:
    result = finalize.completion_diagnostics([7] * 30 + [8, 9])
    assert result["maximum_single_token_run"] == 30
    assert result["top_token_fraction"] == 30 / 32
    assert result["unique_tokens"] == 3


def test_selection_prefers_lower_loss_before_update_fraction() -> None:
    base = {
        "learning_rate": 2e-6,
        "post_update": eval_row(loss=0.66),
        "delta": {"changed_element_fraction": 0.01},
    }
    higher_change = {
        "learning_rate": 2e-5,
        "post_update": eval_row(loss=0.67),
        "delta": {"changed_element_fraction": 0.20},
    }
    assert sorted([higher_change, base], key=finalize.selection_key)[0] is base
