"""Model-free contracts for the V14 grouped-world evaluation."""

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

grouped = importlib.import_module("run_v14_grouped_evaluation")


def test_plan_preserves_failed_flat_lane_and_grouped_coverage() -> None:
    plan = grouped.load_json(grouped.PLAN_PATH)
    cells = grouped.validate_plan(
        REPO, plan, require_fresh=False, verify_bundles=False
    )
    assert [cell["id"] for cell in cells] == list(grouped.CELL_ORDER)
    assert plan["flat_choice_retry"] is False
    assert plan["expected_queries_per_mode"] == 1024


def test_mode_order_cannot_be_changed() -> None:
    plan = grouped.load_json(grouped.PLAN_PATH)
    changed = copy.deepcopy(plan)
    changed["modes"] = changed["modes"][:-1]
    with pytest.raises(grouped.GroupedEvaluationError, match="plan mismatch"):
        grouped.validate_plan(
            REPO, changed, require_fresh=False, verify_bundles=False
        )


def test_zero_record_failure_is_a_required_predecessor() -> None:
    plan = grouped.load_json(grouped.PLAN_PATH)
    changed = copy.deepcopy(plan)
    changed["failed_flat_choice_execution"]["sha256"] = "0" * 64
    with pytest.raises(grouped.GroupedEvaluationError, match="predecessor changed"):
        grouped.validate_plan(
            REPO, changed, require_fresh=False, verify_bundles=False
        )
