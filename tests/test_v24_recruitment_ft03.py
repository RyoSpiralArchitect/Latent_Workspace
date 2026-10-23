"""The new source changes the observer, not the scientific contrast or safety floors."""

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_v24_recruitment_ft as old  # noqa: E402
import run_v24_recruitment_ft03 as new  # noqa: E402


def test_recovery_keeps_all_numerical_bodies_and_phase_gates():
    plan = new.ex.read(ROOT / new.PLAN)
    new.validate(plan)
    for name in ("prepare", "canary", "replay", "train", "phase", "validate_retirement", "summary"):
        assert inspect.getsource(getattr(new.body, name)) == inspect.getsource(getattr(old, name))
    assert new.body is not old and new.body.RUN is new.RUN
    assert old.RUN is not new.RUN and old.ENTRY == "scripts/run_v24_recruitment_ft.py"
    assert new.body.numerical_plan(plan) == old.numerical_plan(new.ex.read(ROOT / old.PLAN))


@pytest.mark.parametrize(
    "field,value",
    [
        ("resources", {}),
        ("training_tokens_per_arm", 1),
        ("qualification_cases", 570),
        ("qualification_test_files", []),
        ("data_manifest_sha256", "b" * 64),
        ("audit_recovery", {}),
        ("old_expression_gate", "PASS"),
        ("training_rows_per_arm", 539),
    ],
)
def test_scope_or_qualification_change_rejected(field, value):
    plan = new.ex.read(ROOT / new.PLAN)
    plan[field] = value
    with pytest.raises((ValueError, KeyError)):
        new.validate(plan)
