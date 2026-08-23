from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

calibration = importlib.import_module("calibrate_v11_elicitation")


def _condition(
    accuracy: float,
    recall_no: float,
    recall_yes: float,
    *,
    wilson: float = 0.6,
) -> dict[str, object]:
    return {
        "examples": 100,
        "accuracy": accuracy,
        "accuracy_wilson_lower_bound": wilson,
        "target_counts": {"0": 50, "1": 50},
        "prediction_counts": {"0": 50, "1": 50},
        "distinct_predicted_classes": 2,
        "per_label": {
            "0": {"recall": recall_no},
            "1": {"recall": recall_yes},
        },
        "per_hop": {"1": {"accuracy_wilson_lower_bound": wilson}},
    }


def _candidate(
    f1_accuracy: float,
    recall_no: float,
    recall_yes: float,
) -> dict[str, object]:
    return {
        "F0_query_only": _condition(0.5, 0.5, 0.5, wilson=0.4),
        "F1_inline": _condition(f1_accuracy, recall_no, recall_yes),
    }


def test_selection_prioritizes_worst_label_recall_before_accuracy() -> None:
    contract = calibration._read_contract(
        REPO / "configs" / "v11" / "ELICITATION_CALIBRATION_CONTRACT.json"
    )
    results = {
        "legacy": _candidate(0.9, 0.56, 0.95),
        "explicit_labels": _candidate(0.82, 0.75, 0.76),
        "symmetric_instruction": _candidate(0.84, 0.7, 0.8),
        "symmetric_instruction_explicit_labels": _candidate(0.8, 0.65, 0.7),
    }
    selection = calibration.select_candidate(results, contract)
    assert selection["selected_style"] == "explicit_labels"


def test_selection_blocks_when_every_candidate_keeps_label_collapse() -> None:
    contract = calibration._read_contract(
        REPO / "configs" / "v11" / "ELICITATION_CALIBRATION_CONTRACT.json"
    )
    results = {
        style: _candidate(0.7, 0.3, 1.0)
        for style in contract["candidate_styles"]
    }
    selection = calibration.select_candidate(results, contract)
    assert selection["selected_style"] is None
    assert selection["eligible_styles"] == []
