from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

finalize = importlib.import_module("finalize_v11_f1_pilot")


def row(loss: float, accuracy: float, recall0: float, recall1: float, distinct: int):
    return {
        "functional_choice_loss": loss,
        "functional_query_accuracy": accuracy,
        "functional_label_0_recall": recall0,
        "functional_label_1_recall": recall1,
        "functional_distinct_predicted_classes": distinct,
        "functional_prediction_entropy_nats": 0.6,
        "functional_yes_minus_no_gap": 0.1,
    }


def gates() -> dict[str, object]:
    return {
        "minimum_distinct_predicted_classes": 2,
        "minimum_final_accuracy": 0.7,
        "minimum_final_label_recall": 0.6,
    }


def test_f1_scientific_gates_pass_together() -> None:
    checks = finalize.evaluate_f1_gates(
        row(0.7, 0.75, 0.7, 0.8, 2),
        row(0.5, 0.8, 0.72, 0.88, 2),
        gates(),
    )
    assert all(check["passed"] for check in checks)


def test_constant_choice_blocks_even_with_finite_loss() -> None:
    checks = finalize.evaluate_f1_gates(
        row(0.675, 0.779, 0.67, 0.88, 2),
        row(0.693, 0.5, 0.0, 1.0, 1),
        gates(),
    )
    failed = {check["id"] for check in checks if not check["passed"]}
    assert failed == {
        "final_choice_loss_below_step0",
        "minimum_final_accuracy",
        "minimum_final_label_recall",
        "minimum_distinct_predicted_classes",
        "forbid_nonfinite_or_constant_choice",
    }
