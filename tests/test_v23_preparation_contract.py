import importlib.util
from pathlib import Path

import pytest

from latent_workspace import execution as ex

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "v23_preparation_contract", ROOT / "scripts/run_v23_preparation.py"
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_complete_plan_validates_before_dispatch():
    runner.validate(ex.read(ROOT / runner.PLAN))


@pytest.mark.parametrize("status", [None, "WRONG_PASS"])
def test_missing_or_inconsistent_status_rejected_before_qualification(status):
    plan = ex.read(ROOT / runner.PLAN)
    if status is None:
        plan.pop("pass_status")
    else:
        plan["pass_status"] = status
    with pytest.raises(ValueError, match="pass_status"):
        runner.validate(plan)
