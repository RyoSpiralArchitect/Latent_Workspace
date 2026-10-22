"""Frozen matched-comparison orchestration; no real-model dispatch in tests."""

import copy
from pathlib import Path

import pytest
import run_v23_preservation_ft as run


def test_frozen_plan_and_same_numerical_recipe():
    plan = run.ex.read(run.ROOT / run.PLAN)
    run.validate(plan)
    old = run.ex.read(run.ROOT / plan["reference_plan"])
    new = run.numerical_plan(plan, "test objective")
    assert {k: v for k, v in new.items() if k not in ("objective", "checkpoint_names")} == {
        k: v for k, v in old.items() if k not in ("objective", "checkpoint_names")
    }
    assert new["seed"] == 47 and new["optimizer"]["learning_rate"] == 2e-7
    assert (
        plan["qualification_test_files"][: len(old["qualification_test_files"])]
        == old["qualification_test_files"]
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("coefficients", {"off": 0, "on": 0.5}),
        ("no_retry", False),
        ("new_sequences", 1),
        ("training_updates_per_arm", 64),
        ("target_dtype", "bfloat16"),
    ],
)
def test_unfrozen_comparison_is_rejected(field, value):
    plan = run.ex.read(run.ROOT / run.PLAN)
    plan[field] = value
    with pytest.raises(ValueError):
        run.validate(plan)


def test_registry_does_not_treat_empty_world_memory_as_preservation():
    rows = [
        dict(key="world", role="world", memory_ids=[], supervised_tokens=3),
        dict(key="ordinary", role="prose", memory_ids=[], supervised_tokens=2),
    ]
    rows = [dict(r, language="en", split="train") for r in rows]
    schedule = {"training": [["world", "ordinary"]], "canary": [["ordinary"]]}
    plan = dict(
        registered_rows=2,
        teacher_rows=1,
        teacher_positions=2,
        training_preservation_tokens=2,
        canary_preservation_tokens=2,
    )
    registered, keys = run.registry(rows, schedule, plan)
    assert keys == ["ordinary"] and len(registered) == 2
    bad = copy.deepcopy(rows)
    bad[1]["split"] = "dev"
    with pytest.raises(ValueError, match="Train-only"):
        run.registry(bad, schedule, plan)


def test_roles_and_resource_budget_are_finite():
    plan = run.ex.read(run.ROOT / run.PLAN)
    assert run.ROLES == ("teacher", "canary", "replay", "off", "on")
    assert run.RUN.updates_native
    assert plan["checkpoint_max_bytes"] == 28 * 2**30
    assert 3 * plan["checkpoint_max_bytes"] + plan["target_file_max_bytes"] == int(86.5 * 2**30)
    assert plan["teacher_tensor_bytes"] == 18727 * 32768 * 4
    assert plan["resources"]["disk_free_gib"] == 50


def test_launch_is_one_exclusive_pipeline_not_retry():
    text = (run.ROOT / "scripts/launch_v23_preservation_ft.sh").read_text()
    assert "set -euo pipefail" in text and "test ! -e" in text
    assert "for task_device in cpu cuda" in text
    assert " dispatch " in text and "while " not in text
    assert Path(run.ENTRY).name == "run_v23_preservation_ft.py"
