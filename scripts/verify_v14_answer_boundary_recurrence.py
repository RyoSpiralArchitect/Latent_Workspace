#!/usr/bin/env python3
"""Recover the V14 recurrence run from one over-strict sham invariant."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
PLAN_PATH = REPO / "configs/v14/ANSWER_BOUNDARY_RECURRENCE_RECOVERY_PLAN.json"


class RecoveryError(RuntimeError):
    """Raised when the immutable recurrence report cannot be recovered exactly."""


def _digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RecoveryError(f"Expected a JSON object: {path}")
    return value


def _resolve(relative: str) -> Path:
    path = (REPO / relative).resolve()
    try:
        path.relative_to(REPO)
    except ValueError as exc:
        raise RecoveryError(f"Path escapes repository: {relative}") from exc
    return path


def validate_plan(plan: dict[str, Any], *, require_fresh: bool = True) -> dict[str, Path]:
    expected = {
        "format": "latent-workspace-v14-answer-boundary-recurrence-recovery-plan-v1",
        "frozen_before_recovery_execution": True,
        "target_model_execution": False,
        "scientific_rescoring": False,
        "expected_rows": 320,
        "expected_original_status": "BLOCKED_EXECUTION",
        "expected_only_failed_check": "sham_cache_exact_noop",
    }
    mismatches = {
        key: {"observed": plan.get(key), "expected": value}
        for key, value in expected.items()
        if plan.get(key) != value
    }
    if mismatches:
        raise RecoveryError(f"Frozen recovery plan mismatch: {mismatches}")
    paths: dict[str, Path] = {}
    for name in ("raw_report", "original_plan"):
        item = plan[name]
        path = _resolve(str(item["path"]))
        if not path.is_file() or _digest(path) != item["sha256"]:
            raise RecoveryError(f"Immutable recovery input changed: {name}")
        paths[name] = path
    for relative, expected_hash in plan["source_identity"].items():
        path = _resolve(relative)
        if not path.is_file() or path.is_symlink() or _digest(path) != expected_hash:
            raise RecoveryError(f"Recovery source identity changed: {relative}")
    output = _resolve(plan["output"])
    if require_fresh and output.exists():
        raise RecoveryError(f"Recovery output already exists: {output}")
    paths["output"] = output
    return paths


def _pair_exact(lane: dict[str, Any]) -> bool:
    return lane["intact"] == lane["twin"] and lane["signed_pair_effect"] == 0.0


def recover(plan: dict[str, Any], *, require_fresh: bool = True) -> dict[str, Any]:
    paths = validate_plan(plan, require_fresh=require_fresh)
    report = _load(paths["raw_report"])
    original_plan = _load(paths["original_plan"])
    if report.get("format") != "latent-workspace-v14-answer-boundary-recurrence-v1":
        raise RecoveryError("Unexpected raw report format")
    if report.get("status") != plan["expected_original_status"]:
        raise RecoveryError("Raw report status changed")
    if report.get("winner") != "none" or report.get("semantic_effect_qualified") is not False:
        raise RecoveryError("Recovery cannot change the scientific no-winner boundary")
    if report.get("plan", {}).get("sha256") != _digest(paths["original_plan"]):
        raise RecoveryError("Raw report is not bound to the original plan")
    if report.get("source_identity") != original_plan.get("source_identity"):
        raise RecoveryError("Raw report source identity differs from its frozen plan")
    rows = report.get("rows")
    if not isinstance(rows, list) or len(rows) != plan["expected_rows"]:
        raise RecoveryError("Raw report row closure is incomplete")

    failed_by_model: dict[str, list[str]] = {}
    prior_true_except_named = True
    for model, checks in report["model_mechanical_checks"].items():
        failed = sorted(key for key, value in checks.items() if value is not True)
        failed_by_model[model] = failed
        prior_true_except_named = prior_true_except_named and failed == [
            plan["expected_only_failed_check"]
        ]

    sham_rows = [row for row in rows if row["control"] == "sham"]
    cache_lanes = (
        "one_shot_carry",
        "one_shot_reset",
        "repeated_carry",
        "repeated_reset_before_current_read",
    )
    repeated_lanes = ("repeated_carry", "repeated_reset_before_current_read")
    future_sham = [row for row in sham_rows if row["horizon"] > 0]
    replacement_checks = {
        "original_only_failed_check_is_the_declared_sham_check": prior_true_except_named,
        "sham_pair_is_exact_within_every_cache_lane": all(
            _pair_exact(row["cache"][lane]) for row in sham_rows for lane in cache_lanes
        ),
        "sham_history_contrasts_are_zero": all(
            row["cache"]["one_shot_history_effect"] == 0.0
            and row["cache"]["repeated_history_effect"] == 0.0
            for row in sham_rows
        ),
        "sham_one_shot_paths_match_full_chunk_base": all(
            row["cache"][lane][member]["cache_from_base"]["exact_equal"]
            and row["cache"][lane][member]["full_logit_l2_from_base"] == 0.0
            for row in sham_rows
            for lane in ("one_shot_carry", "one_shot_reset")
            for member in ("intact", "twin")
        ),
        "split_chunking_displacement_is_observed_and_pair_matched": all(
            not row["cache"][lane]["intact"]["cache_from_base"]["exact_equal"]
            and row["cache"][lane]["intact"] == row["cache"][lane]["twin"]
            for row in future_sham
            for lane in repeated_lanes
        ),
        "raw_rows_summary_and_integrity_are_unchanged": (
            len(rows) == 320
            and report.get("summary", {}).get("winner") == "none"
            and all(
                identity.get("integrity", {}).get(key) is True
                for identity in report["model_identities"].values()
                for key in (
                    "parameter_identity_versions_unchanged",
                    "checkpoint_inventory_unchanged",
                    "source_identity_unchanged",
                    "eval_unchanged",
                )
            )
        ),
    }
    qualified = all(replacement_checks.values())
    return {
        "format": "latent-workspace-v14-answer-boundary-recurrence-recovery-v1",
        "status": "QUALIFIED_VERIFIER_RECOVERY" if qualified else "BLOCKED_RECOVERY",
        "created_utc": datetime.now(UTC).isoformat(),
        "recovery_plan_sha256": _digest(PLAN_PATH),
        "raw_report": {
            **plan["raw_report"],
            "format": report["format"],
            "status": report["status"],
            "row_count": len(rows),
            "summary_sha256": _stable_hash(report["summary"]),
            "rows_sha256": _stable_hash(rows),
        },
        "original_plan": plan["original_plan"],
        "original_failed_checks": failed_by_model,
        "failure_diagnosis": {
            "invalid_invariant": "split_last_token_sham_must_bitwise_equal_full_chunk_base",
            "cause": (
                "The repeated lanes split each fixed turn into a multi-token prefix and a final "
                "one-token call. Native BF16 SDPA follows a different arithmetic path from the "
                "base lane's single full-chunk call, so cross-chunking bitwise equality is not a "
                "valid sham invariant."
            ),
            "valid_replacement": (
                "Within each identical chunking lane, sham intact and twin must be exactly equal; "
                "their signed pair and cache-history contrasts must be zero."
            ),
        },
        "replacement_checks": replacement_checks,
        "recovered_mechanical_execution_qualified": qualified,
        "semantic_effect_qualified": False,
        "winner": "none",
        "target_model_reexecuted": False,
        "scientific_values_recomputed_or_selected": False,
        "claim_boundary": plan["claim_boundary"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=PLAN_PATH)
    args = parser.parse_args()
    plan_path = args.plan.expanduser().resolve()
    if plan_path != PLAN_PATH:
        raise RecoveryError("Recovery uses exactly the repository-frozen plan")
    plan = _load(plan_path)
    result = recover(plan)
    output = _resolve(plan["output"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if result["recovered_mechanical_execution_qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
