#!/usr/bin/env python3
"""Freeze and run the bounded S0 fixture / S1 visibility pilot; never train."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from v13_task_fixture import generate_fixture, validate_fixture


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_new(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def utc() -> str:
    return datetime.now(UTC).isoformat()


def require_idle_gpu() -> str:
    result = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        raise RuntimeError("GPU already has compute clients; do not interfere with another job")
    return "NO_COMPUTE_CLIENTS_AT_CHECK"


def child_environment(root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    for legacy in (
        "PYTORCH_CUDA_ALLOC_CONF",
        "PYTORCH_HIP_ALLOC_CONF",
        "PYTORCH_NO_CUDA_MEMORY_CACHING",
    ):
        environment.pop(legacy, None)
    environment.update(
        {
            "PYTHONPATH": str(root / "src"),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "OMP_NUM_THREADS": "2",
            "MKL_NUM_THREADS": "2",
            "TOKENIZERS_PARALLELISM": "false",
            "PYTORCH_ALLOC_CONF": "backend:native,expandable_segments:True",
        }
    )
    return environment


def validate_plan(plan: dict[str, Any], root: Path) -> list[Path]:
    if plan.get("format") != "latent-workspace-v13-visibility-run-plan-v1":
        raise ValueError("Unsupported visibility plan")
    if plan.get("status") != "BOUNDED_DIAGNOSTIC_AUTHORIZED_BY_USER":
        raise ValueError("Bounded diagnostic scope must be explicit")
    expected = {
        "offline_model_loading": True,
        "base_frozen": True,
        "workspace_frozen": True,
        "engine_unchanged": True,
        "training": False,
        "s0_fully_qualified": False,
        "deferred_sufficiency_claim": False,
        "content_specific_success_claim": False,
        "v14_bridge_claim": False,
        "scale_up_14b": False,
        "checkpoint_deletion_in_diagnostic": False,
    }
    if plan.get("guards") != expected or any(
        type(plan["guards"][key]) is not bool for key in expected
    ):
        raise ValueError("Diagnostic scope guards changed")
    for relative, key in (
        ("configs/v13/DESIGN_CONTRACT.json", "design_contract_sha256"),
        ("src/latent_workspace_ft_v10/engine.py", "historical_engine_sha256"),
        ("data/v10/functional_eval.jsonl", "eval_sha256"),
    ):
        if digest(root / relative) != plan.get(key):
            raise ValueError(f"Input hash changed: {relative}")
    if plan.get("eval_file") != "data/v10/functional_eval.jsonl":
        raise ValueError("Unexpected evaluation source")
    if plan.get("input_lane") != "retained_inline_diagnostic":
        raise ValueError("Only retained-inline diagnostics are implemented")
    for key, value in {
        "max_worlds": 2,
        "raw_query_limit": 2,
        "seed": 271828,
    }.items():
        if type(plan.get(key)) is not int or plan[key] != value:
            raise ValueError(f"Bounded run value changed: {key}")
    if plan.get("post_adapter_gain_grid") != [1.0, 4.0, 16.0]:
        raise ValueError("Diagnostic gain grid changed")
    if plan.get("modes") != [
        "intact",
        "zero",
        "fixed_carrier",
        "norm_matched_random",
        "counterfactual_twin",
        "hard_bypass",
    ]:
        raise ValueError("Required controls changed")
    if plan.get("s0_fixture") != {
        "seed": 1301,
        "families": 8,
        "scope": "SYNTHETIC_FALSIFICATION_ONLY_NOT_QUALIFIED_CORPUS",
    }:
        raise ValueError("Fixture selection changed")
    parent = Path(plan["checkpoint_root"])
    if not parent.is_absolute() or parent.is_symlink() or not parent.is_dir():
        raise ValueError("Checkpoint root must be an existing non-symlink absolute directory")
    entries = plan.get("checkpoints", [])
    if [row.get("id") for row in entries] != ["task_seed43_step16", "semantic_seed43_step16"]:
        raise ValueError("Pilot must preserve the two pinned comparison checkpoints")
    paths = []
    for row, branch in zip(entries, ("task", "semantic"), strict=True):
        relative = f"runs/v12/calibrated_route/refinement16/{branch}_lr_1e_5_seed43_step16/final"
        if row.get("path") != relative:
            raise ValueError("Unexpected checkpoint target")
        target = parent / relative
        if target.is_symlink() or not target.is_dir() or not (target / "COMPLETED").is_file():
            raise ValueError("Incomplete checkpoint")
        if target.resolve() != target or not target.resolve().is_relative_to(parent.resolve()):
            raise ValueError("Checkpoint aliases or escaped parent")
        for file_name, key in (
            ("manifest.json", "manifest_sha256"),
            ("workspace_state.pt", "workspace_sha256"),
        ):
            if (target / file_name).is_symlink() or digest(target / file_name) != row.get(key):
                raise ValueError(f"Checkpoint binding changed: {row['id']}/{file_name}")
        paths.append(target)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=Path("configs/v13/VISIBILITY_RUN_PLAN.json"))
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    plan_path = args.plan.resolve()
    plan = json.loads(plan_path.read_text())
    checkpoints = validate_plan(plan, root)
    output = args.output_dir.absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("Output exists; use a fresh run directory")
    if not output.resolve().is_relative_to(root / "runs/v13"):
        raise ValueError("Output must stay in this worktree's runs/v13 directory")
    if shutil.disk_usage(root).free < 10 * 1024**3:
        raise ValueError("Less than 10 GiB free; no diagnostic launch")
    fixture = generate_fixture(**{key: plan["s0_fixture"][key] for key in ("seed", "families")})
    audit = validate_fixture(fixture)
    if audit.get("passed") is not True:
        raise ValueError(f"S0 fixture failed: {audit}")
    source_paths = [
        "scripts/execute_v13_visibility.py",
        "scripts/v13_visibility_trace.py",
        "scripts/v13_paired_metrics.py",
        "scripts/v13_task_fixture.py",
        "scripts/run_v11_gate0.py",
        "src/latent_workspace_ft_v10/engine.py",
        "configs/v13/DESIGN_CONTRACT.json",
        "configs/v13/VISIBILITY_RUN_PLAN.json",
        "data/v10/functional_eval.jsonl",
    ]
    bindings = {relative: digest(root / relative) for relative in source_paths}
    commands = []
    for row, checkpoint in zip(plan["checkpoints"], checkpoints, strict=True):
        commands.append(
            [
                sys.executable,
                "scripts/v13_visibility_trace.py",
                "--checkpoint",
                str(checkpoint),
                "--eval-file",
                str(root / plan["eval_file"]),
                "--output-dir",
                str(output / row["id"]),
                "--device",
                "cuda",
                "--max-worlds",
                str(plan["max_worlds"]),
                "--raw-query-limit",
                str(plan["raw_query_limit"]),
                "--modes",
                ",".join(plan["modes"]),
                "--gains",
                ",".join(map(str, plan["post_adapter_gain_grid"])),
                "--seed",
                str(plan["seed"]),
                "--expected-engine-sha256",
                plan["historical_engine_sha256"],
                "--expected-workspace-sha256",
                row["workspace_sha256"],
            ]
        )
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / "S0_FIXTURE.json", fixture)
    write_new(output / "S0_FIXTURE_AUDIT.json", audit)
    write_new(
        output / "LAUNCH.json",
        {
            "format": "latent-workspace-v13-s0-s1-launch-v1",
            "created_utc": utc(),
            "plan": plan,
            "plan_sha256": digest(plan_path),
            "source_bindings": bindings,
            "commands": commands,
            "preflight_only": args.preflight_only,
            "scientific_success": False,
            "training": False,
        },
    )
    print(json.dumps({"event": "PREFLIGHT_PASSED", "output": str(output)}), flush=True)
    if args.preflight_only:
        return 0
    environment = child_environment(root)
    runs = []
    for row, command in zip(plan["checkpoints"], commands, strict=True):
        if any(digest(root / path) != value for path, value in bindings.items()):
            raise ValueError("Source changed after launch freeze")
        validate_plan(plan, root)
        require_idle_gpu()
        print(json.dumps({"event": "DIAGNOSTIC_START", "checkpoint": row["id"]}), flush=True)
        start = utc()
        with (output / f"{row['id']}.log").open("x") as log:
            completed = subprocess.run(
                command,
                cwd=root,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        runs.append(
            {
                "id": row["id"],
                "started_utc": start,
                "ended_utc": utc(),
                "returncode": completed.returncode,
            }
        )
        print(json.dumps({"event": "DIAGNOSTIC_EXIT", **runs[-1]}), flush=True)
        if completed.returncode:
            break
    success = len(runs) == 2 and all(row["returncode"] == 0 for row in runs)
    write_new(
        output / "EXECUTION.json",
        {
            "format": "latent-workspace-v13-s0-s1-execution-v1",
            "status": "CHILD_PROCESSES_COMPLETED" if success else "FAILED",
            "runs": runs,
            "launch_sha256": digest(output / "LAUNCH.json"),
            "scientific_success": False,
            "s0_fully_qualified": False,
            "claim_boundary": plan["claim_boundary"],
        },
    )
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
