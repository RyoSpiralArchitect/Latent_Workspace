#!/usr/bin/env python3
"""Separate authorized MMLU-Pro attempt with inactive-allocation reclamation."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
from qualification_isolation import isolate_cli_before_imports  # noqa: E402

isolate_cli_before_imports()
import run_v23_recovered_mmlu_pro as previous  # noqa: E402
import v23_generation_cache as cache  # noqa: E402

ex, original, bank = previous.ex, previous.original, previous.bank
ENTRY = "scripts/run_v23_recovered_mmlu_pro02.py"
PLAN = "configs/v23/RECOVERED_MMLU_PRO_02.json"


def validate(plan):
    previous.validate(plan)
    ex.require(
        plan["schema"] == "ltws-v23-recovered-mmlu-pro-02"
        and plan["prior_source"] == "cda0a8ae8c3648c41fae2be45b3208c9a5f1a9b6"
        and plan["cache_policy"] == "synchronize_then_empty_cache_before_each_generation_guard",
        "Separate unchanged-numerics cache-reclamation attempt",
    )


def run(core, args, plan, seal):
    with (args.output / "GENERATION_CACHE.jsonl").open("x") as journal:
        return original.run(
            core,
            args,
            previous.reference(plan),
            seal,
            predecessor_fn=lambda _: bank.verify()[1],
            generation_fn=lambda *a, **kw: cache.generate(*a, journal=journal, **kw),
        )


RUN = previous.RecoveredRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass="TINY_V23_RECLAIMED_MMLU_PRO_PASS_NOT_7B",
    roles=original.ROLES,
    role_status={r: "V23_MMLU_PRO_ARM_COMPLETE" for r in original.ROLES},
    validate=validate,
    load=original.previous.common.load,
)

if __name__ == "__main__":
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    os.environ["LTWS_CPU_SDPA_BACKEND"] = "math"
    raise SystemExit(RUN.main({r: run for r in original.ROLES}, original.summary))
