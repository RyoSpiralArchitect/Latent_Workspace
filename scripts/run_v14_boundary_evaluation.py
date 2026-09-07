#!/usr/bin/env python3
"""Evaluate the frozen V14 boundary-training finals under matched interventions."""

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
    TrainingGateError,
    atomic_write,
    digest,
    load_json,
    resolve_inside,
)

PLAN_PATH = REPO / "configs/v14/BOUNDARY_EVALUATION_PLAN.json"
FORMAT = "latent-workspace-v14-boundary-evaluation-execution-v1"
CELL_ORDER = ("task", "semantic")


class EvaluationGateError(RuntimeError):
    """Raised when the frozen comparison cannot be evaluated faithfully."""


def validate_plan(
    root: Path,
    plan: dict[str, Any],
    *,
    require_fresh: bool,
    verify_bundles: bool = True,
) -> list[dict[str, Any]]:
    expected = {
        "format": "latent-workspace-v14-boundary-evaluation-plan-v1",
        "frozen_before_target_evaluation": True,
        "cell_order": list(CELL_ORDER),
        "choice_modes": [
            "intact",
            "hard_bypass",
            "counterfactual_twin",
            "norm_matched_random",
            "fixed_carrier",
            "cross_world_shuffle",
        ],
        "run_necessity": True,
    }
    mismatches = {
        key: {"observed": plan.get(key), "expected": value}
        for key, value in expected.items()
        if plan.get(key) != value
    }
    if mismatches:
        raise EvaluationGateError(f"Frozen evaluation header mismatch: {mismatches}")
    execution = plan["training_execution"]
    execution_path = resolve_inside(root, execution["path"], label="training_execution")
    if not execution_path.is_file() or digest(execution_path) != execution["sha256"]:
        raise EvaluationGateError("Training execution receipt changed")
    execution_value = load_json(execution_path)
    if execution_value.get("status") != "COMPLETED":
        raise EvaluationGateError("Training execution is not complete")

    for relative, expected_hash in plan["source_identity"].items():
        path = resolve_inside(root, relative, label="source_identity")
        if not path.is_file() or path.is_symlink() or digest(path) != expected_hash:
            raise EvaluationGateError(f"Source identity mismatch: {relative}")

    cells = plan.get("cells")
    if not isinstance(cells, list) or [cell.get("id") for cell in cells] != list(CELL_ORDER):
        raise EvaluationGateError("Exactly the ordered task and semantic finals are required")
    validated: list[dict[str, Any]] = []
    for cell in cells:
        final = resolve_inside(root, cell["checkpoint"], label="checkpoint")
        manifest = final / "manifest.json"
        workspace = final / "workspace_state.pt"
        completed = final / "COMPLETED"
        if verify_bundles:
            if not completed.is_file() or not manifest.is_file() or not workspace.is_file():
                raise EvaluationGateError(f"Incomplete final bundle: {cell['id']}")
            if digest(manifest) != cell["manifest_sha256"]:
                raise EvaluationGateError(f"Final manifest changed: {cell['id']}")
            if digest(workspace) != cell["workspace_sha256"]:
                raise EvaluationGateError(f"Final workspace changed: {cell['id']}")
        outputs = {
            kind: resolve_inside(root, cell[f"{kind}_output"], label=f"{kind}_output")
            for kind in ("choice", "necessity")
        }
        if require_fresh and any(path.exists() for path in outputs.values()):
            raise EvaluationGateError(f"Evaluation output already exists: {cell['id']}")
        validated.append({"id": cell["id"], "final": final, "outputs": outputs})
    return validated


def _run(command: list[str], *, root: Path, log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists():
        raise EvaluationGateError(f"Refusing to overwrite log: {log_path}")
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


def _verify_choice(path: Path, modes: list[str]) -> dict[str, Any]:
    report = load_json(path)
    if report.get("format") != "latent-workspace-v8-semantic-choice-eval-v2":
        raise EvaluationGateError("Unexpected choice report format")
    choice = report.get("choice", {})
    observed_modes = list(choice.get("modes", {}))
    if int(choice.get("records", -1)) != 128 or observed_modes != modes:
        record_count = choice.get("records")
        raise EvaluationGateError(
            f"Choice report coverage mismatch: records={record_count}, modes={observed_modes}"
        )
    return {
        "sha256": digest(path),
        "records": choice["records"],
        "mode_accuracy": {
            mode: choice["modes"][mode]["accuracy"] for mode in modes
        },
        "mode_counterfactual_answer_accuracy": {
            mode: choice["modes"][mode]["counterfactual_answer_accuracy"] for mode in modes
        },
    }


def _verify_necessity(path: Path) -> dict[str, Any]:
    report = load_json(path)
    if report.get("format") != "latent-workspace-v8-semantic-necessity-v2":
        raise EvaluationGateError(f"Unexpected necessity report format: {report.get('format')}")
    modes = report.get("metrics")
    if not isinstance(modes, dict) or "intact" not in modes or "counterfactual_twin" not in modes:
        raise EvaluationGateError("Necessity report omitted required modes")
    return {
        "sha256": digest(path),
        "cross_minus_within_world_specificity": report.get(
            "cross_minus_within_world_specificity"
        ),
        "counterfactual_twin_effect": report.get("counterfactual_twin_effect"),
        "evidence_ladder": report.get("evidence_ladder"),
        "mode_accuracy": {
            mode: values.get("functional_query_accuracy") for mode, values in modes.items()
        },
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
        "optimizer_or_weight_write": False,
    }
    if not dry_run:
        atomic_write(output_path, receipt)
    modes = list(plan["choice_modes"])
    mode_argument = ",".join(modes)
    for cell in cells:
        row: dict[str, Any] = {
            "id": cell["id"],
            "checkpoint": cell["final"].relative_to(root).as_posix(),
            "started_utc": datetime.now(UTC).isoformat(),
        }
        receipt["runs"].append(row)
        if dry_run:
            row["status"] = "DRY_RUN"
            continue
        logs = output_path.parent / "logs"
        choice_command = [
            sys.executable,
            "-m",
            "latent_workspace_ft_v10",
            "choice-eval",
            "--checkpoint",
            str(cell["final"]),
            "--output",
            str(cell["outputs"]["choice"]),
            "--device",
            "cuda",
            "--modes",
            mode_argument,
        ]
        row["choice_returncode"] = _run(
            choice_command, root=root, log_path=logs / f"{cell['id']}_choice.log"
        )
        if row["choice_returncode"] != 0:
            row["status"] = "CHOICE_FAILED"
            atomic_write(output_path, receipt)
            raise EvaluationGateError(f"Choice evaluation failed: {cell['id']}")
        row["choice"] = _verify_choice(cell["outputs"]["choice"], modes)
        necessity_command = [
            sys.executable,
            "-m",
            "latent_workspace_ft_v10",
            "necessity",
            "--checkpoint",
            str(cell["final"]),
            "--output",
            str(cell["outputs"]["necessity"]),
            "--device",
            "cuda",
        ]
        row["necessity_returncode"] = _run(
            necessity_command, root=root, log_path=logs / f"{cell['id']}_necessity.log"
        )
        if row["necessity_returncode"] != 0:
            row["status"] = "NECESSITY_FAILED"
            atomic_write(output_path, receipt)
            raise EvaluationGateError(f"Necessity evaluation failed: {cell['id']}")
        row["necessity"] = _verify_necessity(cell["outputs"]["necessity"])
        row["completed_utc"] = datetime.now(UTC).isoformat()
        row["status"] = "COMPLETED"
        atomic_write(output_path, receipt)
    receipt["status"] = "DRY_RUN" if dry_run else "COMPLETED"
    receipt["completed_utc"] = datetime.now(UTC).isoformat()
    receipt["claim_boundary"] = (
        "Matched choice and necessity reports measure constrained candidate behavior and memory "
        "interventions on the retained eval fixture. They do not establish natural chat quality, "
        "generalization, or semantic causality when donor directionality is absent."
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
    try:
        plan_path.relative_to(root)
        output_path.relative_to(root)
    except ValueError as exc:
        raise EvaluationGateError("Plan and receipt must stay inside the repository") from exc
    if output_path.exists():
        raise EvaluationGateError(f"Execution receipt already exists: {output_path}")
    try:
        report = execute(root, plan_path, output_path, dry_run=args.dry_run)
    except (EvaluationGateError, TrainingGateError) as exc:
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
