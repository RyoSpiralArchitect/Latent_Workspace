from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

prepare = importlib.import_module("prepare_v11_seed_robustness")


def flatten(value: object, prefix: str = "") -> dict[str, object]:
    if not isinstance(value, dict):
        return {prefix: value}
    result: dict[str, object] = {}
    for key, item in value.items():
        child = f"{prefix}.{key}" if prefix else str(key)
        result.update(flatten(item, child))
    return result


def test_condition_changes_only_learning_rate_seed_and_output() -> None:
    parent = json.loads(
        (REPO / "configs/v11/conditions/config_F1_update_response_lr_2e_7_step4.json").read_text(
            encoding="utf-8"
        )
    )
    candidate = prepare.make_condition(
        parent,
        learning_rate_id="lr_1e_7",
        learning_rate=1e-7,
        seed=43,
    )
    parent_flat = flatten(parent)
    candidate_flat = flatten(candidate)
    changed = {key for key in parent_flat if parent_flat[key] != candidate_flat[key]}
    assert changed == {
        "train.learning_rate",
        "train.output_dir",
        "train.seed",
    }
    assert candidate["train"]["max_steps"] == 4
    assert candidate["train"]["eval_every"] == 1
    assert candidate["train"]["eval_batches"] == 0
    assert candidate["train"]["save_every"] == 0


def test_execution_order_is_complete_paired_and_alternating() -> None:
    assert len(prepare.EXECUTION_ORDER) == 6
    assert len(set(prepare.EXECUTION_ORDER)) == 6
    for seed in prepare.SEEDS:
        pair = [value for value in prepare.EXECUTION_ORDER if value.endswith(f"seed{seed}")]
        assert {value.rsplit("_seed", maxsplit=1)[0] for value in pair} == {
            "lr_1e_7",
            "lr_2e_7",
        }
    assert prepare.EXECUTION_ORDER[:2] == (
        "lr_1e_7_seed43",
        "lr_2e_7_seed43",
    )
    assert prepare.EXECUTION_ORDER[2:4] == (
        "lr_2e_7_seed44",
        "lr_1e_7_seed44",
    )
