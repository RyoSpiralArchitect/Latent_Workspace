#!/usr/bin/env python3
"""Original MMLU-Pro recipe after the explicit whole-arm recovered bank gate."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
from qualification_isolation import (  # noqa: E402
    IsolatedQualificationMixin,
    isolate_cli_before_imports,
)

isolate_cli_before_imports()
import run_v23_mmlu_pro as original  # noqa: E402
import v23_recovered_bank as bank  # noqa: E402

ex = bank.ex
ENTRY = "scripts/run_v23_recovered_mmlu_pro.py"
PLAN = "configs/v23/RECOVERED_MMLU_PRO_01.json"


def reference(plan):
    ex.require(plan["reference_plan"] == original.PLAN, "Original MMLU-Pro plan")
    parent = ex.read(ROOT / original.PLAN)
    ex.require(ex.plan_hash(parent) == plan["reference_plan_sha256"], "Frozen benchmark policy")
    original.validate(parent)
    return parent


def validate(plan):
    parent = reference(plan)
    ex.require(
        plan["roles"] == parent["roles"]
        and plan["planned"] == parent["planned"]
        and plan["resources"] == parent["resources"]
        and plan["no_retry"]
        and plan["bank_plan"] == bank.PLAN,
        "Same finite evaluation, explicit new predecessor",
    )


def run(core, args, plan, seal):
    return original.run(
        core,
        args,
        reference(plan),
        seal,
        predecessor_fn=lambda _: bank.verify()[1],
    )


class RecoveredRun(IsolatedQualificationMixin, original.previous.previous.EvaluationRun):
    pass


RUN = RecoveredRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass="TINY_V23_RECOVERED_MMLU_PRO_PASS_NOT_7B",
    roles=original.ROLES,
    role_status={r: "V23_MMLU_PRO_ARM_COMPLETE" for r in original.ROLES},
    validate=validate,
    load=original.previous.common.load,
)

if __name__ == "__main__":
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    os.environ["LTWS_CPU_SDPA_BACKEND"] = "math"
    raise SystemExit(RUN.main({r: run for r in original.ROLES}, original.summary))
