"""Model-free contracts for the V14 boundary evaluation executor."""

from __future__ import annotations

import copy
import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

evaluation = importlib.import_module("run_v14_boundary_evaluation")


def test_frozen_plan_and_retained_final_hashes_are_self_consistent() -> None:
    plan = evaluation.load_json(evaluation.PLAN_PATH)
    cells = evaluation.validate_plan(
        REPO, plan, require_fresh=False, verify_bundles=False
    )
    assert [cell["id"] for cell in cells] == list(evaluation.CELL_ORDER)


def test_mode_order_is_frozen() -> None:
    plan = evaluation.load_json(evaluation.PLAN_PATH)
    changed = copy.deepcopy(plan)
    changed["choice_modes"] = list(reversed(changed["choice_modes"]))
    with pytest.raises(evaluation.EvaluationGateError, match="header mismatch"):
        evaluation.validate_plan(
            REPO, changed, require_fresh=False, verify_bundles=False
        )


def test_missing_final_completion_is_rejected() -> None:
    plan = evaluation.load_json(evaluation.PLAN_PATH)
    changed = copy.deepcopy(plan)
    changed["cells"][0]["checkpoint"] = "runs/v14/boundary_training/missing/final"
    with pytest.raises(evaluation.EvaluationGateError, match="Incomplete final"):
        evaluation.validate_plan(REPO, changed, require_fresh=False)
