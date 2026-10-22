#!/usr/bin/env python3
"""Explicitly authorized whole-P-on recovery, not a resume of the failed arm."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from qualification_isolation import (  # noqa: E402
    IsolatedQualificationMixin,
    isolate_cli_before_imports,
)

isolate_cli_before_imports()
import run_v23_comparison as original  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402

ENTRY = "scripts/run_v23_comparison_recovery.py"
PLAN = "configs/v23/COMPARISON_RECOVERY_01.json"
HISTORICAL = ROOT / "provenance/pilots/v23_comparison01_20261022/furnace"


def reference(plan):
    ex.require(plan["reference_plan"] == original.PLAN, "Original evaluation only")
    value = ex.read(ROOT / original.PLAN)
    original.validate(value)
    return value


def validate(plan):
    parent = reference(plan)
    ex.require(
        plan["schema"] == "ltws-v23-pon-whole-arm-recovery-01"
        and plan["roles"] == ["on"]
        and plan["no_retry"]
        and plan["original_source"] == "84073310cd7b2c56b5e3de046fb3bdc99e461bfb",
        "Distinct whole P-on recovery only",
    )
    ex.require(plan["resources"] == parent["resources"], "Unchanged resource limits")
    ex.require(
        plan["planned"] == {k: v // 3 for k, v in parent["planned"].items()},
        "Exactly one complete arm, no other activity",
    )
    ex.require(plan["pass_status"] == "V23_PON_RECOVERY_COMPLETE_NOT_RELEASE", "Recovery gate")


def verify_original(plan, folder=None):
    folder = Path(plan["original_bundle"]) if folder is None else Path(folder)
    end = ex.read(folder / "raw/FINISHED.json")
    files = ex.manifest(folder / "raw")
    files.pop("FINISHED.json")
    ex.require(files == end["files"], "All original dispatcher bytes remain unchanged")
    ex.require(
        ex.read(folder / "SOURCE_SEAL.json")["source_commit"] == plan["original_source"]
        and end["status"] == ex.INCOMPLETE
        and end["completed_roles"] == ["base", "off"],
        "Original incomplete dispatcher stays incomplete",
    )
    for name in ("SOURCE_SEAL.json", "raw/FINISHED.json"):
        ex.require(ex.digest(folder / name) == ex.digest(HISTORICAL / name), "Historical identity")
    return dict(
        source=plan["original_source"],
        terminal_sha256=ex.digest(folder / "raw/FINISHED.json"),
        source_seal_sha256=ex.digest(folder / "SOURCE_SEAL.json"),
        excluded_partial_arm="on",
        retained_completed_arms=["base", "off"],
    )


def run(core, args, plan, seal):
    ex.require(args.role == "on", "Never regenerate completed base/off")
    ex.write_new(args.output / "ORIGINAL_PROVENANCE.json", verify_original(plan))
    # Deliberately pass the original numerical and input plan, not merged recovery metadata.
    return original.run(core, args, reference(plan), seal)


def summary(folder, plan):
    end = ex.read(folder / "on/FINISHED.json")["outcome"]
    ex.require(
        (end["new_sequences"], end["mmlu_rows"], end["world_rows"], end["free_rows"])
        == (216, 570, 192, 24),
        "Whole arm, no partial-row reuse",
    )
    ex.require(not list((folder.parent / "checkpoints").iterdir()), "No saved weights")
    return dict(
        new_sequences=216,
        generated_tokens=end["generated_tokens"],
        native_weight_updates=0,
        checkpoint_saves=0,
        completed_arms=["on"],
        original=verify_original(plan),
    )


class RecoveryRun(IsolatedQualificationMixin, original.previous.EvaluationRun):
    pass


RUN = RecoveryRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass="TINY_V23_RECOVERY_PASS_NOT_7B",
    roles=("on",),
    role_status={"on": "V23_EVALUATION_ARM_COMPLETE"},
    validate=validate,
    load=original.common.load,
)

if __name__ == "__main__":
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    os.environ["LTWS_CPU_SDPA_BACKEND"] = "math"
    raise SystemExit(RUN.main({"on": run}, summary))
