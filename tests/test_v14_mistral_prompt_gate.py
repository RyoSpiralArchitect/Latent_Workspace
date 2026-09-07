from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
gate = importlib.import_module("run_v14_mistral_prompt_gate")


def _metric(*, accuracy: float, recall: float, unknown: int = 0) -> dict:
    correct = round(accuracy * 100)
    return {
        "correct": correct,
        "denominator": 100,
        "unknown_count": unknown,
        "accuracy": accuracy if unknown == 0 else None,
        "accuracy_bounds": [correct / 100, (correct + unknown) / 100],
        "prediction_counts": {"0": 50, "1": 50},
        "target_counts": {"0": 50, "1": 50},
        "distinct_predicted_classes": 2,
        "label_recall": {
            "0": {"value": recall if unknown == 0 else None},
            "1": {"value": recall if unknown == 0 else None},
        },
    }


def _summary(query_accuracy: float, inline_accuracy: float, *, recall: float) -> dict:
    return {
        "query_only": {
            "roles": {
                "easy": _metric(accuracy=query_accuracy, recall=0.5),
                "primary": _metric(accuracy=0.5, recall=0.5),
            }
        },
        "inline": {
            "roles": {
                "easy": _metric(accuracy=inline_accuracy, recall=recall),
                "primary": _metric(accuracy=0.6, recall=0.55),
            }
        },
    }


def test_checked_in_prompt_gate_plan_binds_implementation_and_corpora() -> None:
    repo = Path(__file__).resolve().parents[1]
    plan = json.loads((repo / "configs/v14/MISTRAL_PROMPT_GATE_PLAN.json").read_text())
    assert gate._source_identity(plan) == plan["source_identity"]
    for split in ("calibration", "holdout"):
        binding = plan["data"][split]
        assert gate._digest(repo / binding["path"]) == binding["sha256"]
    assert plan["authorized_actions"]["optimizer_or_training"] is False
    assert plan["authorized_actions"]["single_selected_holdout_scoring"] is True


def test_gate_requires_context_gain_both_labels_and_known_measurements() -> None:
    thresholds = {
        "minimum_inline_easy_accuracy": 0.7,
        "minimum_inline_easy_label_recall": 0.6,
        "minimum_inline_minus_query_easy_accuracy": 0.1,
    }
    assert gate._gate(_summary(0.5, 0.8, recall=0.75), thresholds)["qualified"] is True
    assert gate._gate(_summary(0.72, 0.8, recall=0.75), thresholds)["qualified"] is False
    assert gate._gate(_summary(0.5, 0.8, recall=0.55), thresholds)["qualified"] is False


def test_selection_uses_only_qualified_candidates_and_frozen_order_tiebreak() -> None:
    summaries = _summary(0.5, 0.8, recall=0.75)
    candidates = {
        "first": {
            "summaries": summaries,
            "calibration_gate": {"qualified": True},
        },
        "second": {
            "summaries": summaries,
            "calibration_gate": {"qualified": True},
        },
        "blocked": {
            "summaries": _summary(0.5, 0.99, recall=0.99),
            "calibration_gate": {"qualified": False},
        },
    }
    selected = gate._selection(candidates, ["first", "second", "blocked"])
    assert selected["selected_candidate"] == "first"
    assert "blocked" not in selected["eligible_candidates"]
