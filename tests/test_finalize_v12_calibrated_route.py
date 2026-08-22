from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

finalize = importlib.import_module("finalize_v12_calibrated_route")


def _ownership_row(step: int, *, active: bool) -> dict[str, object]:
    return {
        "step": step,
        "base_update_active": active,
        "applied_lr_base": 1e-7 if active else 0.0,
        "cleared_base_gradients": 0 if active else 291,
        "optimizer_state_entries": {
            "base": 291 if active else 0,
            "workspace": 8,
        },
        "sentinels": {
            "base": {"updated": active},
            "workspace": {"updated": True},
        },
    }


def test_ownership_requires_four_frozen_then_twelve_joint_updates() -> None:
    rows = [_ownership_row(step, active=step > 4) for step in range(1, 17)]
    summary, returned = finalize._ownership_summary(rows, max_steps=16, base_release_step=4)
    assert returned == rows
    assert summary["passed"] is True
    assert summary["frozen_updates"] == 4
    assert summary["released_updates"] == 12

    rows[0]["optimizer_state_entries"]["base"] = 1
    summary, _returned = finalize._ownership_summary(rows, max_steps=16, base_release_step=4)
    assert summary["passed"] is False


def test_next_design_rules_are_mutually_exclusive() -> None:
    assert (
        finalize.choose_next_design(
            task_robust=True,
            semantic_robust=True,
            semantic_content_specific_seeds=2,
        )
        == "promote_semantic_sidecar"
    )
    assert (
        finalize.choose_next_design(
            task_robust=False,
            semantic_robust=True,
            semantic_content_specific_seeds=1,
        )
        == "stable_redundant_sidecar"
    )
    assert (
        finalize.choose_next_design(
            task_robust=True,
            semantic_robust=False,
            semantic_content_specific_seeds=3,
        )
        == "task_only_survives"
    )
    assert (
        finalize.choose_next_design(
            task_robust=False,
            semantic_robust=False,
            semantic_content_specific_seeds=0,
        )
        == "revisit_route"
    )
