"""Model-free contracts for the one-sided grouped-evaluation recovery."""

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

recovery = importlib.import_module("complete_v14_grouped_evaluation")


def test_plan_reuses_task_and_authorizes_one_semantic_execution() -> None:
    plan = recovery.load_json(recovery.PLAN_PATH)
    paths = recovery.validate_plan(
        REPO, plan, require_fresh=False, verify_bundle=False
    )
    assert paths["completed_task_report"].is_file()
    assert plan["task_reexecution"] is False
    assert plan["semantic_execution_count"] == 1


def test_task_native_report_has_full_grouped_coverage() -> None:
    plan = recovery.load_json(recovery.PLAN_PATH)
    task = recovery._verify_native_report(
        REPO / plan["completed_task_report"]["path"],
        plan["expected_queries_per_mode"],
    )
    assert task["primary_gate_passed"] is False
    assert task["evidence_ladder"]["F0_engineering"]["passed"] is True


def test_task_reexecution_cannot_be_enabled() -> None:
    plan = recovery.load_json(recovery.PLAN_PATH)
    changed = copy.deepcopy(plan)
    changed["task_reexecution"] = True
    with pytest.raises(recovery.RecoveryError, match="plan mismatch"):
        recovery.validate_plan(
            REPO, changed, require_fresh=False, verify_bundle=False
        )
