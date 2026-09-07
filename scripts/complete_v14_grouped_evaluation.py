#!/usr/bin/env python3
"""Complete only the missing semantic grouped assay and compare it to preserved task output."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from run_v14_boundary_training import (  # noqa: E402
    atomic_write,
    digest,
    load_json,
    resolve_inside,
)
from run_v14_grouped_evaluation import MODES  # noqa: E402

PLAN_PATH = REPO / "configs/v14/GROUPED_EVALUATION_RECOVERY_PLAN.json"
FORMAT = "latent-workspace-v14-grouped-evaluation-recovery-v1"
NATIVE_FORMAT = "latent-workspace-v9-functional-necessity-v1"


class RecoveryError(RuntimeError):
    """Raised when the one-sided fail-closed recovery cannot stay exact."""


def _verify_native_report(path: Path, expected_queries: int) -> dict[str, Any]:
    report = load_json(path)
    if report.get("format") != NATIVE_FORMAT:
        raise RecoveryError(f"Unexpected native report format: {report.get('format')}")
    if report.get("modes") != list(MODES):
        raise RecoveryError(f"Mode order changed: {report.get('modes')}")
    metrics = report.get("metrics")
    if not isinstance(metrics, dict) or list(metrics) != list(MODES):
        raise RecoveryError("Native metrics omitted or reordered modes")
    counts = {mode: int(metrics[mode].get("functional_query_count", -1)) for mode in MODES}
    if any(value != expected_queries for value in counts.values()):
        raise RecoveryError(f"Query coverage mismatch: {counts}")
    ladder = report.get("evidence_ladder")
    if not isinstance(ladder, dict) or list(ladder) != [
        "F0_engineering",
        "F1_deferred_sufficiency",
        "F2_carrier_insufficiency",
        "F3_counterfactual_direction",
        "F4_local_causal_specificity",
        "F5_heldout_query_generalization",
    ]:
        raise RecoveryError("Evidence ladder is incomplete or reordered")
    return report


def validate_plan(
    root: Path,
    plan: dict[str, Any],
    *,
    require_fresh: bool,
    verify_bundle: bool = True,
) -> dict[str, Path]:
    expected = {
        "format": "latent-workspace-v14-grouped-evaluation-recovery-plan-v1",
        "frozen_before_semantic_evaluation": True,
        "task_reexecution": False,
        "semantic_execution_count": 1,
        "modes": list(MODES),
        "expected_queries_per_mode": 1024,
    }
    mismatches = {
        key: {"observed": plan.get(key), "expected": value}
        for key, value in expected.items()
        if plan.get(key) != value
    }
    if mismatches:
        raise RecoveryError(f"Recovery plan mismatch: {mismatches}")
    artifacts: dict[str, Path] = {}
    for key in ("failed_grouped_execution", "completed_task_report"):
        item = plan[key]
        path = resolve_inside(root, item["path"], label=key)
        if not path.is_file() or digest(path) != item["sha256"]:
            raise RecoveryError(f"Bound recovery input changed: {key}")
        artifacts[key] = path
    failure = load_json(artifacts["failed_grouped_execution"])
    if (
        failure.get("status") != "FAILED"
        or failure.get("error")
        != "Unexpected report format: latent-workspace-v9-functional-necessity-v1"
    ):
        raise RecoveryError("Expected verifier-only grouped failure is missing")
    task = _verify_native_report(
        artifacts["completed_task_report"], int(plan["expected_queries_per_mode"])
    )
    if task.get("primary_gate_passed") is not False:
        raise RecoveryError("Preserved task result changed its primary-gate disposition")
    for relative, expected_hash in plan["source_identity"].items():
        path = resolve_inside(root, relative, label="source_identity")
        if not path.is_file() or path.is_symlink() or digest(path) != expected_hash:
            raise RecoveryError(f"Source identity mismatch: {relative}")
    semantic = plan["semantic"]
    checkpoint = resolve_inside(root, semantic["checkpoint"], label="semantic checkpoint")
    if verify_bundle:
        if not (checkpoint / "COMPLETED").is_file():
            raise RecoveryError("Semantic final is incomplete")
        if digest(checkpoint / "manifest.json") != semantic["manifest_sha256"]:
            raise RecoveryError("Semantic manifest changed")
        if digest(checkpoint / "workspace_state.pt") != semantic["workspace_sha256"]:
            raise RecoveryError("Semantic workspace changed")
    output = resolve_inside(root, semantic["output"], label="semantic output")
    comparison = resolve_inside(root, plan["comparison_output"], label="comparison output")
    if require_fresh and (output.exists() or comparison.exists()):
        raise RecoveryError("Semantic or comparison output already exists")
    artifacts.update(
        {
            "semantic_checkpoint": checkpoint,
            "semantic_output": output,
            "comparison_output": comparison,
        }
    )
    return artifacts


def _run(command: list[str], *, root: Path, log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists():
        raise RecoveryError(f"Refusing to overwrite log: {log_path}")
    with log_path.open("x", encoding="utf-8") as handle:
        process = subprocess.Popen(
            command,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            handle.write(line)
            handle.flush()
        return int(process.wait())


def _cell_view(report: dict[str, Any]) -> dict[str, Any]:
    metrics = report["metrics"]
    intact = metrics["intact"]
    twin = metrics["counterfactual_twin"]
    return {
        "primary_gate_passed": report["primary_gate_passed"],
        "intact_accuracy": intact["functional_query_accuracy"],
        "intact_affected_accuracy": intact["functional_affected_accuracy"],
        "intact_unaffected_accuracy": intact["functional_unaffected_accuracy"],
        "intact_choice_margin": intact["functional_choice_margin"],
        "twin_accuracy": twin["functional_query_accuracy"],
        "twin_affected_donor_accuracy": twin["functional_affected_donor_accuracy"],
        "twin_unaffected_original_stability": twin[
            "functional_unaffected_original_stability"
        ],
        "twin_task_loss_increase_vs_intact": report["effects"]["counterfactual_twin"][
            "task_loss_increase_vs_intact"
        ],
        "cross_world_task_loss_increase_vs_intact": report["effects"][
            "cross_world_shuffle"
        ]["task_loss_increase_vs_intact"],
        "fixed_carrier_accuracy": metrics["fixed_carrier"]["functional_query_accuracy"],
        "random_carrier_accuracy": metrics["norm_matched_random"][
            "functional_query_accuracy"
        ],
        "hard_bypass_accuracy": metrics["hard_bypass"]["functional_query_accuracy"],
        "heldout_accuracy": intact["functional_heldout_query_accuracy"],
        "evidence_ladder": report["evidence_ladder"],
    }


def _comparison(task: dict[str, Any], semantic: dict[str, Any]) -> dict[str, Any]:
    task_view = _cell_view(task)
    semantic_view = _cell_view(semantic)
    numeric_keys = [
        key
        for key, value in task_view.items()
        if isinstance(value, (float, int)) and not isinstance(value, bool)
    ]
    return {
        "format": "latent-workspace-v14-grouped-cell-comparison-v1",
        "task": task_view,
        "semantic": semantic_view,
        "semantic_minus_task": {
            key: float(semantic_view[key]) - float(task_view[key]) for key in numeric_keys
        },
        "winner_rule": (
            "No winner unless semantic passes F4 and exceeds task on donor direction "
            "without reducing unaffected stability."
        ),
        "winner": (
            "semantic"
            if semantic["evidence_ladder"]["F4_local_causal_specificity"]["passed"]
            and semantic_view["twin_affected_donor_accuracy"]
            > task_view["twin_affected_donor_accuracy"]
            and semantic_view["twin_unaffected_original_stability"]
            >= task_view["twin_unaffected_original_stability"]
            else "none"
        ),
        "claim_boundary": (
            "The comparison uses every grouped eval decision and a frozen winner rule. None "
            "means the eight-step pilot supplied no qualifying semantic branch."
        ),
    }


def execute(root: Path, plan_path: Path, receipt_path: Path, *, dry_run: bool) -> dict[str, Any]:
    plan = load_json(plan_path)
    paths = validate_plan(root, plan, require_fresh=not dry_run)
    receipt: dict[str, Any] = {
        "format": FORMAT,
        "status": "DRY_RUN" if dry_run else "RUNNING",
        "started_utc": datetime.now(UTC).isoformat(),
        "plan": {"path": plan_path.relative_to(root).as_posix(), "sha256": digest(plan_path)},
        "task_reexecution_performed": False,
        "semantic_execution_count": 0,
        "optimizer_or_weight_write": False,
    }
    if dry_run:
        return receipt
    atomic_write(receipt_path, receipt)
    command = [
        sys.executable,
        "-m",
        "latent_workspace_ft_v10",
        "necessity",
        "--checkpoint",
        str(paths["semantic_checkpoint"]),
        "--output",
        str(paths["semantic_output"]),
        "--device",
        "cuda",
    ]
    returncode = _run(
        command,
        root=root,
        log_path=receipt_path.parent / "semantic_recovery.log",
    )
    receipt["semantic_execution_count"] = 1
    receipt["returncode"] = returncode
    if returncode != 0:
        atomic_write(receipt_path, receipt)
        raise RecoveryError("Semantic grouped evaluation failed")
    expected_queries = int(plan["expected_queries_per_mode"])
    task = _verify_native_report(paths["completed_task_report"], expected_queries)
    semantic = _verify_native_report(paths["semantic_output"], expected_queries)
    comparison = _comparison(task, semantic)
    atomic_write(paths["comparison_output"], comparison)
    receipt.update(
        {
            "status": "COMPLETED",
            "completed_utc": datetime.now(UTC).isoformat(),
            "task_report_sha256": digest(paths["completed_task_report"]),
            "semantic_report_sha256": digest(paths["semantic_output"]),
            "comparison_sha256": digest(paths["comparison_output"]),
            "winner": comparison["winner"],
            "claim_boundary": comparison["claim_boundary"],
        }
    )
    atomic_write(receipt_path, receipt)
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO)
    parser.add_argument("--plan", type=Path, default=PLAN_PATH)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.repo_root.expanduser().resolve()
    plan_path = args.plan.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    if output_path.exists():
        raise RecoveryError(f"Recovery receipt already exists: {output_path}")
    try:
        plan_path.relative_to(root)
        output_path.relative_to(root)
    except ValueError as exc:
        raise RecoveryError("Plan and receipt must stay inside the repository") from exc
    try:
        receipt = execute(root, plan_path, output_path, dry_run=args.dry_run)
    except Exception as exc:
        if not args.dry_run:
            prior = load_json(output_path) if output_path.is_file() else {"format": FORMAT}
            prior.update(
                {
                    "status": "FAILED",
                    "completed_utc": datetime.now(UTC).isoformat(),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            atomic_write(output_path, prior)
        raise
    print(json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
