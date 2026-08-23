from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

finalize = importlib.import_module("finalize_v11_seed_robustness")


def cell(
    seed: int,
    *,
    eligible: bool = True,
    choice_loss: float = 0.60,
    accuracy: float = 0.77,
    minimum_recall: float = 0.74,
    behavior_accuracy: float = 0.80,
    changed_fraction: float = 0.01,
) -> dict[str, object]:
    return {
        "seed": seed,
        "eligible": eligible,
        "final_metrics": {
            "functional_choice_loss": choice_loss,
            "functional_full_vocab_loss": 0.78,
            "functional_query_accuracy": accuracy,
            "functional_label_0_recall": minimum_recall,
            "functional_label_1_recall": 0.82,
        },
        "behavior": {"task_accuracy": behavior_accuracy},
        "delta": {"changed_element_fraction": changed_fraction},
    }


def summary(
    learning_rate_id: str,
    learning_rate: float,
    *,
    behavior_accuracy: float,
    eval_accuracy: float,
    choice_loss: float,
) -> dict[str, object]:
    cells = [
        cell(
            seed,
            behavior_accuracy=behavior_accuracy,
            accuracy=eval_accuracy,
            choice_loss=choice_loss,
        )
        for seed in (43, 44, 45)
    ]
    return finalize.build_learning_rate_summary(
        learning_rate_id, learning_rate, cells, [43, 44, 45]
    )


def test_learning_rate_summary_requires_every_seed() -> None:
    cells = [cell(43), cell(44), cell(45, eligible=False)]
    result = finalize.build_learning_rate_summary("lr_1e_7", 1e-7, cells, [43, 44, 45])
    assert result["robust"] is False
    assert result["passed_seed_fraction"] == 2 / 3
    assert result["passed_seeds"] == [43, 44]


def test_selection_prioritizes_worst_seed_behavior_accuracy() -> None:
    lower_loss = summary(
        "lr_2e_7",
        2e-7,
        behavior_accuracy=0.75,
        eval_accuracy=0.78,
        choice_loss=0.55,
    )
    safer_behavior = summary(
        "lr_1e_7",
        1e-7,
        behavior_accuracy=0.81,
        eval_accuracy=0.76,
        choice_loss=0.62,
    )
    assert sorted([lower_loss, safer_behavior], key=finalize.selection_key)[0] is safer_behavior


def test_selection_uses_lower_learning_rate_as_final_tie_break() -> None:
    lower = summary(
        "lr_1e_7",
        1e-7,
        behavior_accuracy=0.80,
        eval_accuracy=0.77,
        choice_loss=0.60,
    )
    higher = summary(
        "lr_2e_7",
        2e-7,
        behavior_accuracy=0.80,
        eval_accuracy=0.77,
        choice_loss=0.60,
    )
    assert sorted([higher, lower], key=finalize.selection_key)[0] is lower
