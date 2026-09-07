#!/usr/bin/env python3
"""Run the grouped-world necessity comparison after the flat-choice screen failed closed."""

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

PLAN_PATH = REPO / "configs/v14/GROUPED_EVALUATION_PLAN.json"
FORMAT = "latent-workspace-v14-grouped-evaluation-execution-v1"
CELL_ORDER = ("task", "semantic")
MODES = (
    "intact",
    "hard_bypass",
    "zero",
    "fixed_carrier",
    "norm_matched_random",
    "counterfactual_twin",
    "cross_world_shuffle",
)


class GroupedEvaluationError(RuntimeError):
    """Raised when the grouped-world comparison cannot be executed exactly."""


def validate_plan(
    root: Path,
    plan: dict[str, Any],
    *,
    require_fresh: bool,
    verify_bundles: bool = True,
) -> list[dict[str, Any]]:
    expected = {
        "format": "latent-workspace-v14-grouped-evaluation-plan-v1",
        "frozen_before_target_evaluation": True,
        "cell_order": list(CELL_ORDER),
        "modes": list(MODES),
        "expected_queries_per_mode": 1024,
        "flat_choice_retry": False,
    }
    mismatches = {
        key: {"observed": plan.get(key), "expected": value}
        for key, value in expected.items()
        if plan.get(key) != value
    }
    if mismatches:
        raise GroupedEvaluationError(f"Frozen grouped plan mismatch: {mismatches}")
    for key in ("training_execution", "failed_flat_choice_execution"):
        artifact = plan[key]
        path = resolve_inside(root, artifact["path"], label=key)
        if not path.is_file() or digest(path) != artifact["sha256"]:
            raise GroupedEvaluationError(f"Bound predecessor changed: {key}")
    failed_path = resolve_inside(
        root, plan["failed_flat_choice_execution"]["path"], label="failure"
    )
    failed = load_json(failed_path)
    if failed.get("status") != "FAILED" or "records=0" not in str(failed.get("error", "")):
        raise GroupedEvaluationError("The preserved zero-record flat-choice failure is missing")
    for relative, expected_hash in plan["source_identity"].items():
        path = resolve_inside(root, relative, label="source_identity")
        if not path.is_file() or path.is_symlink() or digest(path) != expected_hash:
            raise GroupedEvaluationError(f"Source identity mismatch: {relative}")
    cells = plan.get("cells")
    if not isinstance(cells, list) or [cell.get("id") for cell in cells] != list(CELL_ORDER):
        raise GroupedEvaluationError("Exactly the ordered task and semantic finals are required")
    validated: list[dict[str, Any]] = []
    for cell in cells:
        checkpoint = resolve_inside(root, cell["checkpoint"], label="checkpoint")
        manifest = checkpoint / "manifest.json"
        workspace = checkpoint / "workspace_state.pt"
        if verify_bundles:
            if not (checkpoint / "COMPLETED").is_file():
                raise GroupedEvaluationError(f"Incomplete final bundle: {cell['id']}")
            if digest(manifest) != cell["manifest_sha256"]:
                raise GroupedEvaluationError(f"Manifest changed: {cell['id']}")
            if digest(workspace) != cell["workspace_sha256"]:
                raise GroupedEvaluationError(f"Workspace changed: {cell['id']}")
        output = resolve_inside(root, cell["output"], label="output")
        if require_fresh and output.exists():
            raise GroupedEvaluationError(f"Output already exists: {cell['id']}")
        validated.append({"id": cell["id"], "checkpoint": checkpoint, "output": output})
    return validated


def _run(command: list[str], *, root: Path, log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists():
        raise GroupedEvaluationError(f"Refusing to overwrite log: {log_path}")
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


def verify_report(path: Path, expected_queries: int) -> dict[str, Any]:
    report = load_json(path)
    if report.get("format") != "latent-workspace-v8-semantic-necessity-v2":
        raise GroupedEvaluationError(f"Unexpected report format: {report.get('format')}")
    if report.get("modes") != list(MODES):
        raise GroupedEvaluationError(f"Mode order changed: {report.get('modes')}")
    metrics = report.get("metrics")
    if not isinstance(metrics, dict) or list(metrics) != list(MODES):
        raise GroupedEvaluationError("Grouped necessity metrics omitted or reordered modes")
    counts = {mode: int(metrics[mode].get("functional_query_count", -1)) for mode in MODES}
    if any(value != expected_queries for value in counts.values()):
        raise GroupedEvaluationError(f"Query coverage mismatch: {counts}")
    twin = metrics["counterfactual_twin"]
    return {
        "sha256": digest(path),
        "query_counts": counts,
        "intact": {
            "accuracy": metrics["intact"].get("functional_query_accuracy"),
            "affected_accuracy": metrics["intact"].get("functional_affected_accuracy"),
            "unaffected_accuracy": metrics["intact"].get("functional_unaffected_accuracy"),
            "choice_margin": metrics["intact"].get("functional_choice_margin"),
        },
        "counterfactual_twin": {
            "accuracy": twin.get("functional_query_accuracy"),
            "affected_donor_accuracy": twin.get("functional_affected_donor_accuracy"),
            "unaffected_original_stability": twin.get(
                "functional_unaffected_original_stability"
            ),
            "choice_margin": twin.get("functional_choice_margin"),
        },
        "effects": report.get("effects"),
        "intervention_coverage": report.get("intervention_coverage"),
        "cross_minus_within_world_specificity": report.get(
            "cross_minus_within_world_specificity"
        ),
        "evidence_ladder": report.get("evidence_ladder"),
        "flat_choice_component": report.get("choice"),
    }


def execute(root: Path, plan_path: Path, output_path: Path, *, dry_run: bool) -> dict[str, Any]:
    plan = load_json(plan_path)
    cells = validate_plan(root, plan, require_fresh=not dry_run)
    receipt: dict[str, Any] = {
        "format": FORMAT,
        "status": "DRY_RUN" if dry_run else "RUNNING",
        "started_utc": datetime.now(UTC).isoformat(),
        "plan": {"path": plan_path.relative_to(root).as_posix(), "sha256": digest(plan_path)},
        "runs": [],
        "flat_choice_retry_performed": False,
        "optimizer_or_weight_write": False,
    }
    if not dry_run:
        atomic_write(output_path, receipt)
    for cell in cells:
        row: dict[str, Any] = {
            "id": cell["id"],
            "checkpoint": cell["checkpoint"].relative_to(root).as_posix(),
            "started_utc": datetime.now(UTC).isoformat(),
        }
        receipt["runs"].append(row)
        if dry_run:
            row["status"] = "DRY_RUN"
            continue
        command = [
            sys.executable,
            "-m",
            "latent_workspace_ft_v10",
            "necessity",
            "--checkpoint",
            str(cell["checkpoint"]),
            "--output",
            str(cell["output"]),
            "--device",
            "cuda",
        ]
        row["returncode"] = _run(
            command,
            root=root,
            log_path=output_path.parent / "logs" / f"{cell['id']}_grouped.log",
        )
        if row["returncode"] != 0:
            row["status"] = "FAILED"
            atomic_write(output_path, receipt)
            raise GroupedEvaluationError(f"Grouped necessity failed: {cell['id']}")
        row["report"] = verify_report(cell["output"], int(plan["expected_queries_per_mode"]))
        row["status"] = "COMPLETED"
        row["completed_utc"] = datetime.now(UTC).isoformat()
        atomic_write(output_path, receipt)
    receipt["status"] = "DRY_RUN" if dry_run else "COMPLETED"
    receipt["completed_utc"] = datetime.now(UTC).isoformat()
    receipt["claim_boundary"] = (
        "The grouped necessity lane covers all 1,024 side-query decisions per mode and keeps "
        "affected donor direction separate from unaffected stability. Its nested flat-choice "
        "component remains structurally inapplicable and is not used as evidence."
    )
    if not dry_run:
        atomic_write(output_path, receipt)
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
        raise GroupedEvaluationError(f"Execution receipt already exists: {output_path}")
    try:
        plan_path.relative_to(root)
        output_path.relative_to(root)
    except ValueError as exc:
        raise GroupedEvaluationError("Plan and receipt must stay inside the repository") from exc
    try:
        report = execute(root, plan_path, output_path, dry_run=args.dry_run)
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
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
