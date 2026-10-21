#!/usr/bin/env python3
"""Recovery 02: same whole-arm scope, separately sealed qualification repair."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
from qualification_isolation import isolate_cli_before_imports  # noqa: E402

isolate_cli_before_imports()
import run_v23_comparison_recovery as previous  # noqa: E402

ENTRY = "scripts/run_v23_comparison_recovery02.py"
PLAN = "configs/v23/COMPARISON_RECOVERY_02.json"


def validate(plan):
    previous.validate(plan)
    previous.ex.require(
        plan["attempt_id"] == "v23-comparison-recovery02-20261022"
        and plan["prior_attempt_source"] == "106e12314d72a16a0515a5961989ed49a193a4f8",
        "Separate recovery identity",
    )


RUN = previous.RecoveryRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass="TINY_V23_RECOVERY_PASS_NOT_7B",
    roles=("on",),
    role_status={"on": "V23_EVALUATION_ARM_COMPLETE"},
    validate=validate,
    load=previous.original.common.load,
)

if __name__ == "__main__":
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    os.environ["LTWS_CPU_SDPA_BACKEND"] = "math"
    raise SystemExit(RUN.main({"on": previous.run}, previous.summary))
