#!/usr/bin/env python3
"""Execute one authorized V12 training stage sequentially and fail closed."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CONTRACT_FORMAT = "latent-workspace-ft-v12-calibrated-route-contract-v1"
STEP1_FORMAT = "latent-workspace-ft-v12-step1-response-receipt-v1"
STAGE4_FORMAT = "latent-workspace-ft-v12-stage4-comparison-receipt-v1"
FORMAT = "latent-workspace-ft-v12-stage-execution-v1"


class ExecuteError(RuntimeError):
    """Execution authorization, input binding, or a child run failed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExecuteError(f"Unreadable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ExecuteError(f"Expected a JSON object: {path}")
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


def _resolve(root: Path, value: str | Path, *, label: str) -> Path:
    path = Path(value).expanduser()
    resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ExecuteError(f"{label} must stay inside the repository.") from exc
    return resolved


def _selected_artifacts(
    *,
    root: Path,
    contract_path: Path,
    contract: dict[str, Any],
    stage: str,
    authorization_path: Path | None,
) -> list[dict[str, Any]]:
    if stage == "step1":
        stage_contract = contract["v12_1_step1_response"]
        return [stage_contract["artifacts"][lr_id] for lr_id in stage_contract["condition_order"]]
    if authorization_path is None:
        raise ExecuteError(f"{stage} requires --authorization.")
    authorization = load_json(authorization_path)
    contract_hash = sha256_file(contract_path)
    if stage == "stage4":
        if (
            authorization.get("format") != STEP1_FORMAT
            or authorization.get("stage4_execution_authorized") is not True
            or authorization.get("contract", {}).get("sha256") != contract_hash
        ):
            raise ExecuteError("Step-1 receipt does not authorize stage4.")
        selected_lr = float(authorization["selected_learning_rate"])
        artifacts = contract["v12_2_stage4"]["artifacts"].values()
        selected = [
            artifact
            for artifact in artifacts
            if float(artifact["workspace_learning_rate"]) == selected_lr
        ]
        if len(selected) != 6:
            raise ExecuteError("Stage4 authorization did not resolve six cells.")
        return sorted(selected, key=lambda row: str(row["condition_id"]))
    if (
        authorization.get("format") != STAGE4_FORMAT
        or authorization.get("refinement16_execution_authorized") is not True
        or authorization.get("contract", {}).get("sha256") != contract_hash
    ):
        raise ExecuteError("Stage-4 receipt does not authorize refinement16.")
    selected_lr = float(authorization["selected_learning_rate"])
    promoted = {str(value) for value in authorization["promoted_branches"]}
    artifacts = contract["v12_3_refinement16"]["artifacts"].values()
    selected = [
        artifact
        for artifact in artifacts
        if float(artifact["workspace_learning_rate"]) == selected_lr
        and str(artifact["branch"]) in promoted
    ]
    if len(selected) != 3 * len(promoted) or not selected:
        raise ExecuteError("Refinement authorization resolved an invalid cell set.")
    return sorted(selected, key=lambda row: str(row["condition_id"]))


def execute(args: argparse.Namespace) -> dict[str, Any]:
    started = datetime.now(UTC).isoformat()
    root = args.repo_root.expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise ExecuteError("--repo-root must be a plain directory.")
    contract_path = _resolve(root, args.contract, label="contract")
    contract = load_json(contract_path)
    if (
        contract.get("format") != CONTRACT_FORMAT
        or contract.get("frozen_before_execution") is not True
    ):
        raise ExecuteError("V12 contract is missing or was not frozen.")
    authorization_path = (
        None
        if args.authorization is None
        else _resolve(root, args.authorization, label="authorization")
    )
    artifacts = _selected_artifacts(
        root=root,
        contract_path=contract_path,
        contract=contract,
        stage=args.stage,
        authorization_path=authorization_path,
    )
    output_path = _resolve(root, args.output, label="execution receipt")
    if output_path.exists() and not args.dry_run:
        raise ExecuteError("Execution receipt already exists.")

    runs: list[dict[str, Any]] = []
    for artifact in artifacts:
        config_path = (contract_path.parent / str(artifact["path"])).resolve()
        if sha256_file(config_path) != str(artifact["sha256"]):
            raise ExecuteError(f"Frozen config changed: {artifact['condition_id']}")
        config = load_json(config_path)
        output_dir = (config_path.parent / str(config["train"]["output_dir"])).resolve()
        try:
            output_dir.relative_to(root)
        except ValueError as exc:
            raise ExecuteError("Training output escapes the repository.") from exc
        command = [
            sys.executable,
            "-m",
            "latent_workspace_ft_v10",
            "train",
            "--config",
            str(config_path),
            "--fresh",
        ]
        row = {
            "condition_id": artifact["condition_id"],
            "config": config_path.relative_to(root).as_posix(),
            "config_sha256": sha256_file(config_path),
            "output_dir": output_dir.relative_to(root).as_posix(),
            "command": command,
            "started_utc": datetime.now(UTC).isoformat(),
        }
        runs.append(row)
        if args.dry_run:
            row["status"] = "DRY_RUN"
            continue
        if output_dir.exists():
            raise ExecuteError(f"Fresh output already exists for {artifact['condition_id']}.")
        completed = subprocess.run(command, cwd=root, check=False)
        row["returncode"] = int(completed.returncode)
        row["completed_utc"] = datetime.now(UTC).isoformat()
        final_marker = output_dir / "final/COMPLETED"
        row["completed_marker"] = final_marker.is_file()
        if completed.returncode != 0 or not final_marker.is_file():
            row["status"] = "FAILED"
            raise ExecuteError(f"Training failed for {artifact['condition_id']}.")
        row["status"] = "COMPLETED"

    return {
        "format": FORMAT,
        "schema_version": 1,
        "status": "DRY_RUN" if args.dry_run else "COMPLETED",
        "stage": args.stage,
        "started_utc": started,
        "completed_utc": datetime.now(UTC).isoformat(),
        "contract": {
            "path": contract_path.relative_to(root).as_posix(),
            "sha256": sha256_file(contract_path),
        },
        "authorization": (
            None
            if authorization_path is None
            else {
                "path": authorization_path.relative_to(root).as_posix(),
                "sha256": sha256_file(authorization_path),
            }
        ),
        "runs": runs,
        "claim_boundary": (
            "COMPLETED proves only that every authorized child process returned "
            "success and wrote a final marker. Scientific and artifact integrity "
            "remain unqualified until the stage finalizer passes."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("step1", "stage4", "refinement16"))
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--contract", type=Path, default=Path("configs/v12/CONTRACT.json"))
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.repo_root.expanduser().resolve()
    output = _resolve(root, args.output, label="execution receipt")
    try:
        receipt = execute(args)
    except Exception as exc:
        failure = {
            "format": FORMAT,
            "schema_version": 1,
            "status": "FAILED",
            "stage": args.stage,
            "completed_utc": datetime.now(UTC).isoformat(),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        atomic_write(output, failure)
        raise
    atomic_write(output, receipt)
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
