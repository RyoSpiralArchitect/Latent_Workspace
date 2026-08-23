from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

gate0 = importlib.import_module("run_v11_gate0")


def _summary(
    *,
    accuracy: float,
    wilson: float,
    hop1_wilson: float,
    predictions: dict[str, int],
    recalls: tuple[float, float],
) -> dict[str, object]:
    total = 1000
    return {
        "accuracy": accuracy,
        "accuracy_wilson_lower_bound": wilson,
        "target_counts": {"0": 500, "1": 500},
        "prediction_counts": predictions,
        "distinct_predicted_classes": len(predictions),
        "per_label": {
            "0": {"examples": 500, "correct": int(recalls[0] * 500), "recall": recalls[0]},
            "1": {"examples": 500, "correct": int(recalls[1] * 500), "recall": recalls[1]},
        },
        "per_hop": {
            "1": {
                "examples": total // 2,
                "correct": int(accuracy * total / 2),
                "accuracy": accuracy,
                "accuracy_wilson_lower_bound": hop1_wilson,
            }
        },
        "direct_wrapper_parity": {
            "exact_logits": True,
            "exact_predictions": True,
            "max_abs_logit_difference": 0.0,
        },
    }


def test_wilson_lower_bound_is_conservative_and_monotonic() -> None:
    assert gate0.wilson_lower_bound(0, 0, 1.96) == 0.0
    assert gate0.wilson_lower_bound(50, 100, 1.96) < 0.5
    assert gate0.wilson_lower_bound(80, 100, 1.96) > 0.7
    assert gate0.wilson_lower_bound(90, 100, 1.96) > gate0.wilson_lower_bound(
        80, 100, 1.96
    )


def test_frozen_repository_gate_contract_loads_with_exact_gate_set() -> None:
    contract = gate0.load_contract(REPO / "configs" / "v11" / "GATE0_CONTRACT.json")
    assert contract["frozen_before_execution"] is True
    assert contract["execution"]["optimizer_steps"] == 0
    assert contract["elicitation"]["prompt_separator"] == "\n\n"


def test_gate_checks_pass_usable_inline_positive_control() -> None:
    contract = gate0.load_contract(REPO / "configs" / "v11" / "GATE0_CONTRACT.json")
    f0 = _summary(
        accuracy=0.5,
        wilson=0.47,
        hop1_wilson=0.45,
        predictions={"0": 500, "1": 500},
        recalls=(0.5, 0.5),
    )
    f1 = _summary(
        accuracy=0.8,
        wilson=0.77,
        hop1_wilson=0.74,
        predictions={"0": 480, "1": 520},
        recalls=(0.78, 0.82),
    )
    checks, comparison = gate0.build_gate_checks(contract, f0, f1)
    assert all(check["passed"] for check in checks)
    assert comparison["f1_minus_f0_accuracy"] == pytest.approx(0.3)


def test_gate_checks_block_constant_choice_even_with_inflated_accuracy() -> None:
    contract = gate0.load_contract(REPO / "configs" / "v11" / "GATE0_CONTRACT.json")
    f0 = _summary(
        accuracy=0.5,
        wilson=0.47,
        hop1_wilson=0.45,
        predictions={"0": 500, "1": 500},
        recalls=(0.5, 0.5),
    )
    f1 = _summary(
        accuracy=0.75,
        wilson=0.72,
        hop1_wilson=0.7,
        predictions={"1": 1000},
        recalls=(0.0, 1.0),
    )
    checks, _comparison = gate0.build_gate_checks(contract, f0, f1)
    failures = {check["id"] for check in checks if not check["passed"]}
    assert "f1_predicts_both_classes" in failures
    assert "f1_minimum_label_recall" in failures
