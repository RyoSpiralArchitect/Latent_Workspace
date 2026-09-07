"""Contracts for the V14 layer-16 boundary training pair."""

from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

prepare = importlib.import_module("prepare_v14_boundary_training")


def _parents() -> dict[str, dict]:
    return {
        name: json.loads(path.read_text(encoding="utf-8"))
        for name, path in prepare.PARENTS.items()
    }


def test_generated_pair_differs_only_in_objective_and_output() -> None:
    parents = _parents()
    configs = {
        branch: prepare.make_config(parents[branch], branch)
        for branch in ("task", "semantic")
    }
    prepare.validate_pair(configs)
    assert configs["task"]["functional"]["counterfactual_weight"] == 0.0
    assert configs["task"]["functional"]["stability_weight"] == 0.0
    assert configs["semantic"]["functional"]["counterfactual_weight"] == 1.0
    assert configs["semantic"]["functional"]["stability_weight"] == 0.25


def test_boundary_full_update_and_retention_are_frozen() -> None:
    config = prepare.make_config(_parents()["task"], "task")
    assert config["functional"]["route_mode"] == "deferred"
    assert config["functional"]["boundary_layer"] == 16
    assert config["model"]["train_mode"] == "full"
    assert config["train"]["max_steps"] == 8
    assert config["train"]["base_release_step"] == 4
    assert config["train"]["gradient_accumulation_offload"] == "cpu_accumulate"
    assert config["train"]["save_every"] == 4
    assert config["train"]["keep_last_checkpoints"] == 2


def test_pair_validator_rejects_hidden_schedule_difference() -> None:
    parents = _parents()
    configs = {
        branch: prepare.make_config(parents[branch], branch)
        for branch in ("task", "semantic")
    }
    broken = copy.deepcopy(configs)
    broken["semantic"]["train"]["learning_rate"] = 2e-7
    with pytest.raises(prepare.PrepareError, match="differ outside"):
        prepare.validate_pair(broken)


def test_unknown_branch_is_rejected() -> None:
    with pytest.raises(prepare.PrepareError, match="Unknown branch"):
        prepare.make_config(_parents()["task"], "other")
