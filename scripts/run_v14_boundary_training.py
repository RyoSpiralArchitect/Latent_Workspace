#!/usr/bin/env python3
"""Run the frozen V14 layer-16 task/semantic training pair sequentially."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
PLAN_PATH = REPO / "configs/v14/BOUNDARY_TRAINING_PLAN.json"
FORMAT = "latent-workspace-v14-boundary-training-execution-v1"
CELL_ORDER = ("task", "semantic")


class TrainingGateError(RuntimeError):
    """Raised when the frozen comparison cannot be launched or completed."""


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TrainingGateError(f"Unreadable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise TrainingGateError(f"Expected a JSON object: {path}")
    return value


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def resolve_inside(root: Path, relative: str, *, label: str) -> Path:
    value = Path(relative)
    if value.is_absolute():
        raise TrainingGateError(f"{label} must be repository-relative")
    resolved = (root / value).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise TrainingGateError(f"{label} escapes repository: {relative}") from exc
    return resolved


def _validated_config(root: Path, cell: dict[str, Any]) -> tuple[Path, dict[str, Any], Path]:
    config_path = resolve_inside(root, str(cell["config"]), label="config")
    if not config_path.is_file() or config_path.is_symlink():
        raise TrainingGateError(f"Config is not a plain file: {config_path}")
    if digest(config_path) != str(cell["config_sha256"]):
        raise TrainingGateError(f"Frozen config hash mismatch: {cell['id']}")
    config = load_json(config_path)
    output_dir = (config_path.parent / str(config["train"]["output_dir"])).resolve()
    try:
        output_dir.relative_to(root)
    except ValueError as exc:
        raise TrainingGateError(f"Output directory escapes repository: {cell['id']}") from exc
    expected_output = resolve_inside(root, str(cell["output_dir"]), label="output_dir")
    if output_dir != expected_output:
        raise TrainingGateError(f"Output directory binding mismatch: {cell['id']}")

    expected = {
        "model.name_or_path": "mistralai/Mistral-7B-Instruct-v0.3",
        "model.revision": "c170c708c41dac9275d15a8fff4eca08d52bab71",
        "model.train_mode": "full",
        "model.dtype": "bfloat16",
        "model.attn_implementation": "sdpa",
        "functional.route_mode": "deferred",
        "functional.boundary_layer": 16,
        "functional.task_objective": "choice_normalized",
        "train.seed": 47,
        "train.max_steps": 8,
        "train.base_release_step": 4,
        "train.batch_size": 1,
        "train.gradient_accumulation_steps": 8,
        "train.gradient_accumulation_offload": "cpu_accumulate",
        "train.base_activation_offload": "legacy_functional",
        "train.optimizer": "adafactor",
        "train.learning_rate": 1e-7,
        "train.workspace_learning_rate": 1e-5,
        "train.save_every": 4,
        "train.keep_last_checkpoints": 2,
        "train.save_optimizer": True,
        "train.resume_from": "none",
    }
    observed: dict[str, Any] = {}
    for dotted in expected:
        section, key = dotted.split(".", 1)
        observed[dotted] = config[section][key]
    mismatches = {
        key: {"observed": observed[key], "expected": value}
        for key, value in expected.items()
        if observed[key] != value
    }
    objective_expected = {
        "task": (0.0, 0.0),
        "semantic": (1.0, 0.25),
    }[str(cell["id"])]
    objective_observed = (
        float(config["functional"]["counterfactual_weight"]),
        float(config["functional"]["stability_weight"]),
    )
    if objective_observed != objective_expected:
        mismatches["functional.objective_weights"] = {
            "observed": objective_observed,
            "expected": objective_expected,
        }
    if mismatches:
        raise TrainingGateError(f"Frozen config contract mismatch: {mismatches}")
    return config_path, config, output_dir


def _validate_pair(configs: dict[str, dict[str, Any]]) -> None:
    left = copy.deepcopy(configs["task"])
    right = copy.deepcopy(configs["semantic"])
    for value in (left, right):
        value["functional"].pop("counterfactual_weight")
        value["functional"].pop("stability_weight")
        value["train"].pop("output_dir")
    if left != right:
        raise TrainingGateError("Cells differ outside objective weights and output_dir")


def validate_plan(root: Path, plan: dict[str, Any], *, require_fresh: bool) -> list[dict[str, Any]]:
    expected_header = {
        "format": "latent-workspace-v14-boundary-training-plan-v1",
        "frozen_before_target_training": True,
        "cell_order": list(CELL_ORDER),
        "minimum_start_free_gib": 120,
    }
    mismatches = {
        key: {"observed": plan.get(key), "expected": value}
        for key, value in expected_header.items()
        if plan.get(key) != value
    }
    if mismatches:
        raise TrainingGateError(f"Frozen plan header mismatch: {mismatches}")

    for artifact_key in ("trajectory_report", "preparation"):
        artifact = plan[artifact_key]
        path = resolve_inside(root, str(artifact["path"]), label=artifact_key)
        if not path.is_file() or digest(path) != str(artifact["sha256"]):
            raise TrainingGateError(f"Bound predecessor changed: {artifact_key}")

    for relative, expected_hash in plan["source_identity"].items():
        path = resolve_inside(root, relative, label="source_identity")
        if not path.is_file() or path.is_symlink() or digest(path) != expected_hash:
            raise TrainingGateError(f"Source identity mismatch: {relative}")

    cells = plan.get("cells")
    if not isinstance(cells, list) or [cell.get("id") for cell in cells] != list(CELL_ORDER):
        raise TrainingGateError("Exactly the ordered task and semantic cells are required")
    configs: dict[str, dict[str, Any]] = {}
    validated: list[dict[str, Any]] = []
    for cell in cells:
        config_path, config, output_dir = _validated_config(root, cell)
        if require_fresh and output_dir.exists():
            raise TrainingGateError(f"Fresh output already exists: {output_dir}")
        configs[str(cell["id"])] = config
        validated.append(
            {
                "id": str(cell["id"]),
                "config_path": config_path,
                "config": config,
                "output_dir": output_dir,
            }
        )
    _validate_pair(configs)
    return validated


def validate_runtime(plan: dict[str, Any]) -> dict[str, Any]:
    import torch
    import transformers

    observed = {
        "python": ".".join(str(value) for value in sys.version_info[:3]),
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "cuda": torch.version.cuda,
    }
    if observed != plan["expected_runtime"]:
        raise TrainingGateError(
            f"Pinned runtime mismatch: observed={observed}, expected={plan['expected_runtime']}"
        )
    environment = {key: os.environ.get(key) for key in plan["required_environment"]}
    if environment != plan["required_environment"]:
        raise TrainingGateError(
            f"Required environment mismatch: observed={environment}, "
            f"expected={plan['required_environment']}"
        )
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise TrainingGateError("Exactly one visible CUDA device is required")
    observed["gpu"] = torch.cuda.get_device_name(0)
    observed["environment"] = environment
    return observed


def _run_logged(command: list[str], *, cwd: Path, log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists():
        raise TrainingGateError(f"Refusing to overwrite log: {log_path}")
    with log_path.open("x", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
            log.flush()
        return int(process.wait())


def _bundle_receipt(output_dir: Path) -> dict[str, Any]:
    expected = [output_dir / "checkpoint-4", output_dir / "checkpoint-8", output_dir / "final"]
    missing = [str(path) for path in expected if not (path / "COMPLETED").is_file()]
    if missing:
        raise TrainingGateError(f"Completed training is missing retained bundles: {missing}")
    checkpoints = sorted(path.name for path in output_dir.glob("checkpoint-*") if path.is_dir())
    if checkpoints != ["checkpoint-4", "checkpoint-8"]:
        raise TrainingGateError(f"Checkpoint retention mismatch: {checkpoints}")
    bundles: dict[str, Any] = {}
    for path in expected:
        manifest = path / "manifest.json"
        workspace = path / "workspace_state.pt"
        if not manifest.is_file() or not workspace.is_file():
            raise TrainingGateError(f"Incomplete bundle contents: {path}")
        bundles[path.name] = {
            "manifest_sha256": digest(manifest),
            "workspace_sha256": digest(workspace),
            "bytes": sum(item.stat().st_size for item in path.rglob("*") if item.is_file()),
        }
    return {"checkpoints": checkpoints, "bundles": bundles}


def execute(root: Path, plan_path: Path, output_path: Path, *, dry_run: bool) -> dict[str, Any]:
    started = datetime.now(UTC).isoformat()
    plan = load_json(plan_path)
    cells = validate_plan(root, plan, require_fresh=not dry_run)
    runtime = None if dry_run else validate_runtime(plan)
    free_bytes = shutil.disk_usage(root).free
    required = int(plan["minimum_start_free_gib"]) * 1024**3
    if not dry_run and free_bytes < required:
        observed_gib = free_bytes / 1024**3
        required_gib = required / 1024**3
        raise TrainingGateError(
            f"Insufficient start disk: {observed_gib:.2f} GiB < {required_gib:.2f} GiB"
        )

    receipt: dict[str, Any] = {
        "format": FORMAT,
        "status": "DRY_RUN" if dry_run else "RUNNING",
        "started_utc": started,
        "plan": {"path": plan_path.relative_to(root).as_posix(), "sha256": digest(plan_path)},
        "runtime": runtime,
        "free_disk_bytes_at_start": free_bytes,
        "runs": [],
        "weight_deletion_performed": False,
    }
    if not dry_run:
        atomic_write(output_path, receipt)

    for cell in cells:
        config_path = cell["config_path"]
        row: dict[str, Any] = {
            "id": cell["id"],
            "config": config_path.relative_to(root).as_posix(),
            "config_sha256": digest(config_path),
            "output_dir": cell["output_dir"].relative_to(root).as_posix(),
            "started_utc": datetime.now(UTC).isoformat(),
        }
        receipt["runs"].append(row)
        if dry_run:
            row["status"] = "DRY_RUN"
            continue
        log_dir = output_path.parent / "logs"
        doctor_command = [
            sys.executable,
            "-m",
            "latent_workspace_ft_v10",
            "doctor",
            "--config",
            str(config_path),
            "--load-model",
            "--full-data-scan",
            "--smoke-step",
        ]
        row["doctor_command"] = doctor_command
        row["doctor_returncode"] = _run_logged(
            doctor_command, cwd=root, log_path=log_dir / f"{cell['id']}_doctor.log"
        )
        if row["doctor_returncode"] != 0:
            row["status"] = "DOCTOR_FAILED"
            atomic_write(output_path, receipt)
            raise TrainingGateError(f"Doctor failed: {cell['id']}")
        train_command = [
            sys.executable,
            "-m",
            "latent_workspace_ft_v10",
            "train",
            "--config",
            str(config_path),
            "--fresh",
        ]
        row["train_command"] = train_command
        row["train_returncode"] = _run_logged(
            train_command, cwd=root, log_path=log_dir / f"{cell['id']}_train.log"
        )
        row["completed_utc"] = datetime.now(UTC).isoformat()
        if row["train_returncode"] != 0:
            row["status"] = "TRAIN_FAILED"
            atomic_write(output_path, receipt)
            raise TrainingGateError(f"Training failed: {cell['id']}")
        row.update(_bundle_receipt(cell["output_dir"]))
        row["free_disk_bytes_after"] = shutil.disk_usage(root).free
        row["status"] = "COMPLETED"
        atomic_write(output_path, receipt)

    receipt["status"] = "DRY_RUN" if dry_run else "COMPLETED"
    receipt["completed_utc"] = datetime.now(UTC).isoformat()
    receipt["claim_boundary"] = (
        "COMPLETED proves only that the frozen matched cells passed doctor, finished eight "
        "updates, and retained step 4, step 8, and final bundles. Training benefit, semantic "
        "specificity, generation quality, and V14 task qualification require separate evaluation."
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
        output_path.relative_to(root)
        plan_path.relative_to(root)
    except ValueError as exc:
        raise TrainingGateError("Plan and receipt must stay inside the repository") from exc
    if output_path.exists():
        raise TrainingGateError(f"Execution receipt already exists: {output_path}")
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
