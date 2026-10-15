#!/usr/bin/env python3
"""Freeze a qualified enlarged-cap study plan; no network or credentials."""

from __future__ import annotations

import argparse
from pathlib import Path

import probe_v14_budget_panel as probe
import run_v14_budget_panel as run

BUNDLE = "provenance/pilots/v14_judge_capacity_20261009"


def build(provider, cap, qualification):
    root = run.REPO
    qualification = Path(qualification).resolve()
    gate = probe.verify(qualification.parent)
    if (
        not gate["qualified"]
        or gate["provider"] != provider
        or gate["config"] != run.config_for(provider, cap)
    ):
        raise ValueError("Capacity panel is not qualified for the requested method")
    parent_path = root / "configs/v14/JUDGE_PANEL_PLAN.json"
    parent = run.prior.load_json(parent_path)
    sources = (
        *run.SOURCE_FILES,
        "scripts/prepare_v14_budget_panel.py",
        "tests/test_v14_budget_panel.py",
        f"{BUNDLE}/PROTOCOL.md",
        f"{BUNDLE}/SCOPE_UPDATE.md",
    )
    plan = {
        "format": "latent-workspace-v14-budget-panel-plan-v1",
        "created_date": "2026-10-09",
        "method_id": f"{provider}_cap{cap}",
        "parent_panel_plan": {
            "path": str(parent_path.relative_to(root)),
            "sha256": run.prior.file_sha(parent_path),
        },
        "dataset": parent["dataset"],
        "source_identity": {p: run.prior.file_sha(root / p) for p in sources},
        "qualification": {
            "path": str(qualification.relative_to(root)),
            "sha256": run.prior.file_sha(qualification),
        },
        "replicates": list(range(5)),
        "max_calls_per_cell": 28,
        "planned_requests": 140,
        "providers": {provider: gate["config"]},
        "study_scope": "Same selected pairs/rubric/strict validator; no training or generation.",
        "attempt_policy": "No automatic retransmission; preserve incomplete/invalid/missing votes.",
        "model_identity_ceiling": "Exact API ID only; immutable remote weights UNKNOWN.",
    }
    for replicate in range(5):
        run.validate_plan(plan, provider, replicate)
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=sorted(run.PROVIDERS), required=True)
    parser.add_argument("--cap", type=int, choices=run.CAPS, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan = build(args.provider, args.cap, args.qualification)
    run.prior.write_json(args.output, plan, exclusive=True)
    print("FROZEN_NOT_DISPATCHED", plan["method_id"], plan["planned_requests"])


if __name__ == "__main__":
    main()
