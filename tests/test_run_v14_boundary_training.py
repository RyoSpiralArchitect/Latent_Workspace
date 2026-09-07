"""Model-free contracts for the V14 layer-16 training executor."""

from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

runner = importlib.import_module("run_v14_boundary_training")


def _configs() -> dict[str, dict]:
    directory = REPO / "configs/v14/boundary_training"
    return {
        branch: json.loads(
            (directory / f"config_{branch}_boundary16_seed47_step8.json").read_text(
                encoding="utf-8"
            )
        )
        for branch in runner.CELL_ORDER
    }


def test_pair_is_matched_outside_declared_objectives_and_output() -> None:
    runner._validate_pair(_configs())


def test_pair_rejects_hidden_learning_rate_difference() -> None:
    configs = _configs()
    configs["semantic"]["train"]["learning_rate"] = 2e-7
    with pytest.raises(runner.TrainingGateError, match="differ outside"):
        runner._validate_pair(configs)


def test_plan_and_bound_sources_are_self_consistent() -> None:
    plan = runner.load_json(runner.PLAN_PATH)
    cells = runner.validate_plan(REPO, plan, require_fresh=False)
    assert [cell["id"] for cell in cells] == list(runner.CELL_ORDER)


def test_plan_rejects_changed_retention_contract() -> None:
    plan = runner.load_json(runner.PLAN_PATH)
    changed = copy.deepcopy(plan)
    changed["minimum_start_free_gib"] = 1
    with pytest.raises(runner.TrainingGateError, match="header mismatch"):
        runner.validate_plan(REPO, changed, require_fresh=False)
