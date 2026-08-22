from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

prepare = importlib.import_module("prepare_v11_update_response_surface")


def flatten(value: object, prefix: str = "") -> dict[str, object]:
    if not isinstance(value, dict):
        return {prefix: value}
    result: dict[str, object] = {}
    for key, item in value.items():
        child = f"{prefix}.{key}" if prefix else str(key)
        result.update(flatten(item, child))
    return result


def test_one_step_condition_changes_only_frozen_train_fields() -> None:
    parent = json.loads(
        (REPO / "configs/v11/conditions/config_F1_inline_symmetric_choice_repair.json")
        .read_text(encoding="utf-8")
    )
    candidate = prepare.make_condition(
        parent,
        condition_id="lr_test",
        learning_rate=2e-6,
        max_steps=1,
    )
    parent_flat = flatten(parent)
    candidate_flat = flatten(candidate)
    changed = {
        key for key in parent_flat if parent_flat[key] != candidate_flat[key]
    }
    assert changed == {
        "train.eval_every",
        "train.learning_rate",
        "train.max_steps",
        "train.output_dir",
        "train.save_every",
    }
    assert candidate["train"]["save_every_minutes"] == 0.0
    assert candidate["train"]["eval_at_start"] is True
    assert candidate["train"]["eval_batches"] == 0


def test_learning_rate_grid_is_strictly_descending() -> None:
    values = [value for _condition_id, value in prepare.LEARNING_RATES]
    assert len(values) == len(set(values)) == 5
    assert values == sorted(values, reverse=True)
    assert all(left > right for left, right in zip(values, values[1:]))
