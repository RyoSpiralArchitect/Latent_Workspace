"""Frozen recovery scope and explicit operation dispatch; no pretrained models."""

import ast
import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_v24_recruitment_ft as old  # noqa: E402
import run_v24_recruitment_ft04 as new  # noqa: E402


def test_same_numerical_plan_phase_gates_and_private_dispatch():
    plan = new.ex.read(ROOT / new.PLAN)
    new.validate(plan)
    assert new.body is not old and new.body.RUN is new.RUN
    assert old.RUN is not new.RUN
    assert new.body.numerical_plan(plan) == old.numerical_plan(new.ex.read(ROOT / old.PLAN))
    for name in ("prepare", "phase", "validate_retirement", "summary", "load_data", "predecessor"):
        assert inspect.getsource(getattr(new.body, name)) == inspect.getsource(getattr(old, name))
    assert new.body.BODIES == dict(
        canary=new.canary, replay=new.replay, inline=new.train, workspace=new.train
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("resources", {}),
        ("training_tokens_per_arm", 1),
        ("qualification_cases", 608),
        ("qualification_test_files", []),
        ("data_manifest_sha256", "b" * 64),
        ("storage_recovery", {}),
        ("storage_policy", "relax"),
        ("old_expression_gate", "PASS"),
    ],
)
def test_scope_or_safety_drift_is_rejected(field, value):
    plan = new.ex.read(ROOT / new.PLAN)
    plan[field] = value
    with pytest.raises((ValueError, KeyError)):
        new.validate(plan)


@pytest.mark.parametrize(
    "name,expected",
    [
        (
            "canary",
            {"snapshots.future_write_bytes", "snapshots.checkpoint", "snapshots.payload_sha"},
        ),
        ("replay", {"snapshots.restore", "snapshots.payload_sha"}),
        ("train", {"snapshots.future_write_bytes", "snapshots.checkpoint"}),
    ],
)
def test_all_snapshot_calls_use_explicit_operation_adapter(name, expected):
    tree = ast.parse(inspect.getsource(getattr(new, name)))
    calls = [ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)]
    assert {s for s in calls if s.startswith("snapshots.")} == expected
    assert not {"core.snapshot_admission", "prior.checkpoint", "prior.restore"}.intersection(calls)
