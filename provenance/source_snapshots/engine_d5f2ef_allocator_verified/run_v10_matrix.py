#!/usr/bin/env python3
"""Portable, fail-closed v10 CUDA matrix runner.

The runner is deliberately a control plane. It never downloads a model, deletes
weights, or resumes an unverified partial output. Model network access belongs to
``prefetch_v10_model.py``; training subprocesses are forced offline.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import prefetch_v10_model as model_cache
import prune_v10_verified_run as verified_pruning

MATRIX_FORMAT = "latent-workspace-v10-profile-matrix-v1"
CONTRACT_FORMAT = "latent-workspace-v10-matrix-contract-v1"
QUALIFICATION_FORMAT = "latent-workspace-v10-qualification-v1"
VERIFICATION_FORMAT = "latent-workspace-v10-run-verification-v1"
PROGRESS_FORMAT = "latent-workspace-v10-runner-progress-v1"
STATUS_FORMAT = "latent-workspace-v10-run-status-v1"
FULL_UPDATE_DELTA_FORMAT = "latent-workspace-v10-full-update-delta-v2"
OPTIMIZER_COVERAGE_FORMAT = "latent-workspace-ft-optimizer-coverage-v1"
BASE_UPDATE_COVERAGE_FORMAT = "latent-workspace-ft-base-update-coverage-v1"
UNCHANGED_UPDATE_EVIDENCE_CLASS = (
    "verified_update_attempt_zero_persisted_net_delta"
)
CHANGED_UPDATE_EVIDENCE_CLASS = "verified_update_attempt_persisted_delta"
DELTA_COMPARE_MAX_WORKING_SET_BYTES = 64 * 1024 * 1024
# Two source tensors, an exact inequality mask, and indexing/conversion overhead.
# This deliberately overestimates BF16/FP32 comparison memory.
DELTA_COMPARE_ESTIMATED_BYTES_PER_ELEMENT = 32
PROFILES = ("smoke", "n3", "n10")
PROFILE_GATE = {"n3": "smoke", "n10": "n3"}
CUDA_ALLOCATOR_ENV = "PYTORCH_ALLOC_CONF"
CUDA_ALLOCATOR_LEGACY_ENV = "PYTORCH_CUDA_ALLOC_CONF"
CUDA_ALLOCATOR_HIP_LEGACY_ENV = "PYTORCH_HIP_ALLOC_CONF"
CUDA_ALLOCATOR_DISABLE_ENV = "PYTORCH_NO_CUDA_MEMORY_CACHING"
CUDA_ALLOCATOR_CONF = "backend:native,expandable_segments:True"
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

# The v10 comparison is specifically contracted as an unquantized, full-scope
# CUDA/BF16 update.  Keep the contract vocabulary separate from the engine
# config vocabulary where the persisted field names intentionally differ.
FULL_UPDATE_REQUIREMENTS = (
    (
        "model.train_mode",
        ("model", "train_mode"),
        "full",
        ("model", "train_mode"),
        "full",
    ),
    (
        "train.optimizer",
        ("runtime", "optimizer"),
        "adafactor",
        ("train", "optimizer"),
        "adafactor",
    ),
    (
        "train.device",
        ("runtime", "backend"),
        "cuda",
        ("train", "device"),
        "cuda",
    ),
    (
        "train.mixed_precision",
        ("model", "dtype"),
        "bfloat16",
        ("train", "mixed_precision"),
        "bf16",
    ),
    (
        "model.attn_implementation",
        ("model", "attention_implementation"),
        "sdpa",
        ("model", "attn_implementation"),
        "sdpa",
    ),
    (
        "train.cuda_allocator_conf",
        ("runtime", "cuda_allocator_conf"),
        CUDA_ALLOCATOR_CONF,
        ("train", "cuda_allocator_conf"),
        CUDA_ALLOCATOR_CONF,
    ),
)


class RunnerError(RuntimeError):
    """A fail-closed runner validation or execution error."""


@dataclass(frozen=True)
class RunSpec:
    run_id: str
    condition: str
    condition_config: Path
    condition_config_relative: str
    seed: int
    max_steps: int
    output_dir: Path
    output_dir_relative: str
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class PreparedRun:
    spec: RunSpec
    materialized: Mapping[str, Any]
    materialized_bytes: bytes
    provenance: Mapping[str, Any]


@dataclass(frozen=True)
class SafeTensorEntry:
    name: str
    path: Path
    relative_file: str
    shape: tuple[int, ...]
    dtype: str
    numel: int


@dataclass(frozen=True)
class RunnerOptions:
    repo_root: Path
    profile: str
    matrix_path: Path
    contract_path: Path
    model_receipt: Path
    model_snapshot: Path | None = None
    cache_dir: Path | None = None
    qualification_root: Path = Path("runs/v10/qualifications")
    python: str = sys.executable
    engine_module: str = "latent_workspace_ft_v10.engine"
    minimum_free_disk_gib: float = 100.0
    minimum_free_vram_gib: float = 28.0
    maximum_gpu_utilization_percent: int = 10
    dry_run: bool = False
    max_runs: int | None = None


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunnerError(f"Could not read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RunnerError(f"Expected a JSON object: {path}")
    return value


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, canonical_json_bytes(value))


def append_jsonl_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    encoded = (payload + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o644)
    try:
        written = os.write(descriptor, encoded)
        if written != len(encoded):
            raise RunnerError(f"Short atomic journal write: {written}/{len(encoded)}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _repo_relative(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise RunnerError(f"Path escapes repository root: {path}") from exc


def resolve_repo_path(repo_root: Path, value: str | Path, *, label: str) -> Path:
    raw = Path(value)
    if raw.is_absolute():
        candidate = raw.resolve()
    else:
        if any(part == ".." for part in raw.parts):
            raise RunnerError(f"{label} contains parent traversal: {value}")
        candidate = (repo_root / raw).resolve()
    _repo_relative(repo_root, candidate)
    return candidate


def _validate_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RunnerError(f"{label} must be a non-empty string.")
    return value


def _nested_value(value: Mapping[str, Any], path: tuple[str, str]) -> Any:
    parent = value.get(path[0])
    return parent.get(path[1]) if isinstance(parent, Mapping) else None


def validate_full_update_contract(contract: Mapping[str, Any]) -> None:
    """Reject a contract that no longer describes the declared v10 update lane."""

    for canonical, contract_path, expected, _config_path, _config_expected in (
        FULL_UPDATE_REQUIREMENTS
    ):
        observed = _nested_value(contract, contract_path)
        if observed != expected:
            source = ".".join(contract_path)
            raise RunnerError(
                f"Full-update contract requires {canonical} via "
                f"{source}={expected!r}; observed {observed!r}."
            )


def validate_materialized_full_update(
    config: Mapping[str, Any],
    *,
    label: str,
) -> None:
    """Reject any run config that would weaken the contracted update scope."""

    for canonical, _contract_path, _expected, config_path, expected in (
        FULL_UPDATE_REQUIREMENTS
    ):
        observed = _nested_value(config, config_path)
        if observed != expected:
            raise RunnerError(
                f"Full-update {label} requires {canonical}={expected!r}; "
                f"observed {observed!r}."
            )


def load_matrix(repo_root: Path, path: Path, profile: str) -> tuple[dict[str, Any], list[RunSpec]]:
    matrix = read_json(path)
    if matrix.get("format") != MATRIX_FORMAT:
        raise RunnerError(f"Unsupported matrix format in {path}")
    if matrix.get("profile") != profile:
        raise RunnerError(f"Matrix profile {matrix.get('profile')!r} != {profile!r}")
    if matrix.get("path_base") != "repository_root":
        raise RunnerError("Matrix path_base must be 'repository_root'.")
    runs = matrix.get("runs")
    if not isinstance(runs, list) or not runs:
        raise RunnerError("Matrix runs must be a non-empty list.")
    if matrix.get("expected_run_count") != len(runs):
        raise RunnerError("Matrix expected_run_count does not equal len(runs).")

    specs: list[RunSpec] = []
    run_ids: set[str] = set()
    output_dirs: set[str] = set()
    for index, raw in enumerate(runs):
        if not isinstance(raw, dict):
            raise RunnerError(f"Matrix run {index} is not an object.")
        run_id = _validate_string(raw.get("run_id"), label=f"runs[{index}].run_id")
        condition = _validate_string(
            raw.get("condition"), label=f"runs[{index}].condition"
        )
        if not SAFE_NAME_RE.fullmatch(condition):
            raise RunnerError(f"Unsafe condition name: {condition!r}")
        if run_id != f"{condition}/seed_{raw.get('seed')}":
            raise RunnerError(f"Run id is not canonical: {run_id}")
        if run_id in run_ids:
            raise RunnerError(f"Duplicate run_id: {run_id}")
        run_ids.add(run_id)
        try:
            seed = int(raw["seed"])
            max_steps = int(raw["max_steps"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RunnerError(f"Invalid seed/max_steps for {run_id}") from exc
        if seed < 0 or max_steps < 1:
            raise RunnerError(f"Invalid seed/max_steps for {run_id}")
        config_relative = _validate_string(
            raw.get("condition_config"), label=f"{run_id}.condition_config"
        )
        output_relative = _validate_string(
            raw.get("output_dir"), label=f"{run_id}.output_dir"
        )
        config_path = resolve_repo_path(repo_root, config_relative, label="condition_config")
        output_path = resolve_repo_path(repo_root, output_relative, label="output_dir")
        if not config_path.is_file():
            raise RunnerError(f"Missing condition config: {config_relative}")
        expected_prefix = f"runs/v10/{profile}/"
        if not output_relative.startswith(expected_prefix):
            raise RunnerError(
                f"Output {output_relative!r} is outside profile prefix {expected_prefix!r}."
            )
        if output_relative in output_dirs:
            raise RunnerError(f"Duplicate output_dir: {output_relative}")
        output_dirs.add(output_relative)
        specs.append(
            RunSpec(
                run_id=run_id,
                condition=condition,
                condition_config=config_path,
                condition_config_relative=config_relative,
                seed=seed,
                max_steps=max_steps,
                output_dir=output_path,
                output_dir_relative=output_relative,
                raw=raw,
            )
        )
    return matrix, specs


def source_hashes(repo_root: Path) -> tuple[dict[str, str], str]:
    source_root = repo_root / "src" / "latent_workspace_ft_v10"
    paths = sorted(source_root.glob("*.py"))
    manifest = source_root / "source_manifest.json"
    if manifest.is_file():
        paths.append(manifest)
    if not paths:
        raise RunnerError(f"No v10 source files at {source_root}")
    mapping = {_repo_relative(repo_root, path): sha256_file(path) for path in paths}
    source_manifest = read_json(manifest)
    patched = source_manifest.get("patched_engine")
    if not isinstance(patched, dict):
        raise RunnerError("source_manifest.json has no patched_engine object.")
    engine_relative = _validate_string(patched.get("path"), label="patched_engine.path")
    if mapping.get(engine_relative) != patched.get("sha256"):
        raise RunnerError("Patched engine hash disagrees with source_manifest.json.")
    return mapping, sha256_bytes(canonical_json_bytes(mapping))


def _resolve_config_data_path(repo_root: Path, config_path: Path, value: str) -> Path:
    raw = Path(value)
    candidate = raw.resolve() if raw.is_absolute() else (config_path.parent / raw).resolve()
    _repo_relative(repo_root, candidate)
    if not candidate.is_file():
        raise RunnerError(f"Configured data file does not exist: {value}")
    return candidate


def data_hashes_for_config(repo_root: Path, config_path: Path) -> dict[str, str]:
    config = read_json(config_path)
    data = config.get("data")
    if not isinstance(data, dict):
        raise RunnerError(f"Config has no data object: {config_path}")
    paths: set[Path] = set()
    for key in ("train_files", "eval_files"):
        values = data.get(key)
        if not isinstance(values, list) or not values:
            raise RunnerError(f"Config data.{key} must be a non-empty list.")
        for value in values:
            if not isinstance(value, str):
                raise RunnerError(f"Config data.{key} contains a non-string path.")
            paths.add(_resolve_config_data_path(repo_root, config_path, value))
    return {_repo_relative(repo_root, path): sha256_file(path) for path in sorted(paths)}


def _rebase_path_list(
    values: Any,
    *,
    repo_root: Path,
    source_config: Path,
    destination_dir: Path,
    label: str,
) -> list[str]:
    if not isinstance(values, list):
        raise RunnerError(f"{label} must be a list.")
    rebased: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise RunnerError(f"{label} contains a non-string path.")
        target = _resolve_config_data_path(repo_root, source_config, value)
        rebased.append(Path(os.path.relpath(target, destination_dir)).as_posix())
    return rebased


def materialize_config(
    repo_root: Path,
    matrix: Mapping[str, Any],
    spec: RunSpec,
) -> tuple[dict[str, Any], bytes]:
    config = copy.deepcopy(read_json(spec.condition_config))
    model = config.get("model")
    train = config.get("train")
    data = config.get("data")
    if not isinstance(model, dict) or not isinstance(train, dict) or not isinstance(data, dict):
        raise RunnerError(f"Condition config is missing model/train/data: {spec.condition_config}")
    validate_materialized_full_update(
        config,
        label=f"condition config for {spec.run_id}",
    )
    matrix_model = matrix.get("model")
    if not isinstance(matrix_model, dict):
        raise RunnerError("Matrix has no model object.")
    for key in ("name_or_path", "revision"):
        if model.get(key) != matrix_model.get(key):
            raise RunnerError(f"Condition config model.{key} disagrees with matrix.")
    model["local_files_only"] = True
    model["trust_remote_code"] = False
    train["seed"] = spec.seed
    train["max_steps"] = spec.max_steps
    train["output_dir"] = "."
    train["resume_from"] = "none"
    train["device"] = "cuda"
    destination_dir = spec.output_dir
    for key in ("train_files", "eval_files"):
        data[key] = _rebase_path_list(
            data.get(key),
            repo_root=repo_root,
            source_config=spec.condition_config,
            destination_dir=destination_dir,
            label=f"data.{key}",
        )
    assays = config.get("assays")
    if isinstance(assays, dict):
        recruitment = assays.get("recruitment")
        if isinstance(recruitment, dict):
            for key in ("train_files", "eval_files"):
                values = recruitment.get(key)
                if isinstance(values, list) and values:
                    recruitment[key] = _rebase_path_list(
                        values,
                        repo_root=repo_root,
                        source_config=spec.condition_config,
                        destination_dir=destination_dir,
                        label=f"assays.recruitment.{key}",
                    )
    validate_materialized_full_update(
        config,
        label=f"materialized config for {spec.run_id}",
    )
    payload = canonical_json_bytes(config)
    return config, payload


def _verify_hash_mapping(repo_root: Path, mapping: Mapping[str, Any], *, label: str) -> None:
    for relative, expected in mapping.items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise RunnerError(f"Invalid {label} hash mapping entry.")
        path = resolve_repo_path(repo_root, relative, label=label)
        if not path.is_file() or sha256_file(path) != expected:
            raise RunnerError(f"{label} hash mismatch: {relative}")


def validate_contract(
    repo_root: Path,
    contract_path: Path,
    contract: Mapping[str, Any],
    matrix: Mapping[str, Any],
    profile: str,
) -> dict[str, str]:
    if contract.get("format") != CONTRACT_FORMAT:
        raise RunnerError(f"Unsupported contract format in {contract_path}")
    validate_full_update_contract(contract)
    contract_model = contract.get("model")
    matrix_model = matrix.get("model")
    if not isinstance(contract_model, dict) or not isinstance(matrix_model, dict):
        raise RunnerError("Contract/matrix model object is missing.")
    for key in ("name_or_path", "revision"):
        if contract_model.get(key) != matrix_model.get(key):
            raise RunnerError(f"Contract model.{key} disagrees with matrix.")
    contract_runtime = contract.get("runtime")
    matrix_runtime = matrix.get("runtime")
    if not isinstance(contract_runtime, dict) or not isinstance(matrix_runtime, dict):
        raise RunnerError("Contract/matrix runtime object is missing.")
    if contract_runtime.get("cuda_allocator_conf") != CUDA_ALLOCATOR_CONF:
        raise RunnerError("Contract CUDA allocator policy is not the pinned value.")
    if matrix_runtime.get("cuda_allocator_conf") != CUDA_ALLOCATOR_CONF:
        raise RunnerError("Matrix CUDA allocator policy is not the pinned value.")
    contract_matrix = contract.get("matrix")
    profiles = (
        contract_matrix.get("profiles") if isinstance(contract_matrix, dict) else None
    )
    if not isinstance(profiles, dict) or not isinstance(profiles.get(profile), dict):
        raise RunnerError(f"Contract has no profile declaration for {profile}.")
    profile_contract = profiles[profile]
    if profile_contract.get("run_count") != matrix.get("expected_run_count"):
        raise RunnerError("Contract profile run_count disagrees with matrix.")
    if profile_contract.get("max_steps") != matrix.get("max_steps"):
        raise RunnerError("Contract profile max_steps disagrees with matrix.")

    source = contract.get("source")
    if not isinstance(source, dict):
        raise RunnerError("Contract source object is missing.")
    for key in ("preparation_scripts", "runtime_sources", "v9_reference_files"):
        mapping = source.get(key)
        if not isinstance(mapping, dict):
            raise RunnerError(f"Contract source.{key} is missing.")
        _verify_hash_mapping(repo_root, mapping, label=f"contract source.{key}")

    data_contract = contract.get("data")
    if not isinstance(data_contract, dict):
        raise RunnerError("Contract data object is missing.")
    manifest_relative = _validate_string(data_contract.get("manifest"), label="data.manifest")
    manifest_path = resolve_repo_path(repo_root, manifest_relative, label="data.manifest")
    if sha256_file(manifest_path) != data_contract.get("manifest_sha256"):
        raise RunnerError("Contract data manifest hash mismatch.")
    remapped = data_contract.get("remapped_output_sha256")
    if not isinstance(remapped, dict):
        raise RunnerError("Contract remapped_output_sha256 is missing.")
    data_hashes = {
        "data/v10/functional_train.jsonl": str(remapped.get("train", "")),
        "data/v10/functional_eval.jsonl": str(remapped.get("eval", "")),
    }
    _verify_hash_mapping(repo_root, data_hashes, label="contract remapped data")
    return data_hashes


def prepare_runs(
    *,
    repo_root: Path,
    profile: str,
    matrix: Mapping[str, Any],
    specs: Sequence[RunSpec],
    contract_path: Path,
    matrix_path: Path,
    model_receipt_path: Path,
    source_files: Mapping[str, str],
    source_tree_sha256: str,
    contract_data_hashes: Mapping[str, str],
    model_snapshot_inventory_sha256: str,
    model_snapshot_tensor_schema_sha256: str,
) -> list[PreparedRun]:
    common_hashes: dict[str, Any] = {
        "contract_sha256": sha256_file(contract_path),
        "matrix_sha256": sha256_file(matrix_path),
        "model_receipt_sha256": sha256_file(model_receipt_path),
        "model_snapshot_inventory_sha256": model_snapshot_inventory_sha256,
        "model_snapshot_tensor_schema_sha256": (
            model_snapshot_tensor_schema_sha256
        ),
        "source_tree_sha256": source_tree_sha256,
        "source_files_sha256": dict(source_files),
        "contract_data_sha256": dict(contract_data_hashes),
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "prefetch_script_sha256": sha256_file(
            Path(model_cache.__file__).resolve()
        ),
    }
    prepared: list[PreparedRun] = []
    for spec in specs:
        materialized, materialized_bytes = materialize_config(repo_root, matrix, spec)
        run_data_hashes = data_hashes_for_config(repo_root, spec.condition_config)
        if run_data_hashes != dict(contract_data_hashes):
            raise RunnerError(f"Run data hashes disagree with contract: {spec.run_id}")
        hashes = {
            **common_hashes,
            "condition_config_sha256": sha256_file(spec.condition_config),
            "materialized_config_sha256": sha256_bytes(materialized_bytes),
            "run_data_sha256": run_data_hashes,
        }
        provenance = {
            "profile": profile,
            "run_id": spec.run_id,
            "condition": spec.condition,
            "condition_config": spec.condition_config_relative,
            "seed": spec.seed,
            "max_steps": spec.max_steps,
            "output_dir": spec.output_dir_relative,
            "runtime_policy": {
                "environment_variable": CUDA_ALLOCATOR_ENV,
                "pytorch_alloc_conf": CUDA_ALLOCATOR_CONF,
                "forbidden_environment_variables": [
                    CUDA_ALLOCATOR_LEGACY_ENV,
                    CUDA_ALLOCATOR_HIP_LEGACY_ENV,
                    CUDA_ALLOCATOR_DISABLE_ENV,
                ],
            },
            "hashes": hashes,
        }
        prepared.append(
            PreparedRun(
                spec=spec,
                materialized=materialized,
                materialized_bytes=materialized_bytes,
                provenance=provenance,
            )
        )
    return prepared


def qualification_requirements(
    *,
    repo_root: Path,
    gate_profile: str,
    contract_sha256: str,
    model_receipt_sha256: str,
    source_tree_sha256: str,
    data_hashes: Mapping[str, str],
    runner_sha256: str,
) -> dict[str, Any]:
    gate_matrix = repo_root / "configs" / "v10" / "profiles" / gate_profile / "MATRIX.json"
    raw = read_json(gate_matrix)
    return {
        "format": QUALIFICATION_FORMAT,
        "profile": gate_profile,
        "qualified": True,
        "matrix_sha256": sha256_file(gate_matrix),
        "contract_sha256": contract_sha256,
        "model_receipt_sha256": model_receipt_sha256,
        "source_tree_sha256": source_tree_sha256,
        "runner_sha256": runner_sha256,
        "data_sha256": dict(data_hashes),
        "completed_runs": int(raw.get("expected_run_count", -1)),
        "expected_runs": int(raw.get("expected_run_count", -2)),
    }


def require_qualification(
    *,
    repo_root: Path,
    profile: str,
    qualification_root: Path,
    expected: Mapping[str, Any],
) -> None:
    gate_profile = PROFILE_GATE.get(profile)
    if gate_profile is None:
        return
    path = qualification_root / gate_profile / "QUALIFICATION.json"
    if not path.is_file():
        raise RunnerError(
            f"{profile} is blocked: missing {gate_profile} qualification receipt at "
            f"{_repo_relative(repo_root, path)}"
        )
    observed = read_json(path)
    for key, value in expected.items():
        if observed.get(key) != value:
            raise RunnerError(
                f"{profile} is blocked: qualification field {key!r} does not match "
                "the current contract/source/data/model state."
            )


def cuda_disk_preflight(options: RunnerOptions) -> dict[str, Any]:
    free_disk = shutil.disk_usage(options.repo_root).free
    required_disk = int(options.minimum_free_disk_gib * 1024**3)
    if free_disk < required_disk:
        raise RunnerError(
            f"Disk preflight failed: {free_disk / 1024**3:.2f} GiB free, "
            f"{options.minimum_free_disk_gib:.2f} GiB required."
        )
    try:
        import torch
    except ImportError as exc:
        raise RunnerError("CUDA preflight requires torch.") from exc
    if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
        raise RunnerError("CUDA preflight failed: torch reports no CUDA GPU.")
    if not torch.cuda.is_bf16_supported():
        raise RunnerError("CUDA preflight failed: BF16 is not supported.")
    command = [
        "nvidia-smi",
        "--query-gpu=index,name,memory.free,memory.total,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RunnerError(f"CUDA preflight could not run nvidia-smi: {exc}") from exc
    rows = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(rows) != 1:
        raise RunnerError(f"CUDA preflight requires exactly one visible GPU, saw {len(rows)}.")
    parts = [part.strip() for part in rows[0].split(",")]
    if len(parts) != 5:
        raise RunnerError(f"Could not parse nvidia-smi output: {rows[0]!r}")
    try:
        free_vram_mib = int(parts[2])
        total_vram_mib = int(parts[3])
        utilization = int(parts[4])
    except ValueError as exc:
        raise RunnerError(f"Could not parse nvidia-smi numeric fields: {rows[0]!r}") from exc
    required_vram_mib = int(options.minimum_free_vram_gib * 1024)
    if free_vram_mib < required_vram_mib:
        raise RunnerError(
            f"GPU preflight failed: {free_vram_mib} MiB free, "
            f"{required_vram_mib} MiB required."
        )
    if utilization > options.maximum_gpu_utilization_percent:
        raise RunnerError(
            f"GPU preflight failed: utilization is {utilization}%, above the "
            f"configured {options.maximum_gpu_utilization_percent}% contention limit."
        )
    return {
        "checked_utc": utc_now(),
        "disk_free_bytes": free_disk,
        "disk_required_bytes": required_disk,
        "gpu_index": int(parts[0]),
        "gpu_name": parts[1],
        "gpu_memory_free_mib": free_vram_mib,
        "gpu_memory_total_mib": total_vram_mib,
        "gpu_utilization_percent": utilization,
        "torch_version": str(torch.__version__),
        "torch_cuda_runtime": str(torch.version.cuda),
        "bf16_supported": True,
    }


@contextlib.contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o644)
    except OSError as exc:
        raise RunnerError(f"Unsafe or inaccessible runner lock {path}: {exc}") from exc
    try:
        path_stat = path.lstat()
        descriptor_stat = os.fstat(descriptor)
        if (
            stat.S_ISLNK(path_stat.st_mode)
            or not stat.S_ISREG(path_stat.st_mode)
            or not stat.S_ISREG(descriptor_stat.st_mode)
            or path_stat.st_nlink != 1
            or descriptor_stat.st_nlink != 1
            or (path_stat.st_dev, path_stat.st_ino)
            != (descriptor_stat.st_dev, descriptor_stat.st_ino)
        ):
            raise RunnerError(
                f"Runner lock must be a regular, non-symlink, single-link file: {path}"
            )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RunnerError(f"Runner lock is held: {path}") from exc
        metadata = canonical_json_bytes(
            {
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "acquired_utc": utc_now(),
            }
        )
        os.ftruncate(descriptor, 0)
        os.write(descriptor, metadata)
        os.fsync(descriptor)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _inventory_with_sha256(root: Path) -> tuple[list[dict[str, Any]], str]:
    inventory = model_cache.snapshot_inventory(root)
    return inventory, sha256_bytes(canonical_json_bytes(inventory))


def _tree_stat_fingerprint(root: Path) -> list[dict[str, Any]]:
    root = root.resolve()
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            stat = path.stat()
            records.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "bytes": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "inode": stat.st_ino,
                }
            )
    return records


def _safe_indexed_path(root: Path, index_path: Path, value: str) -> Path:
    relative = Path(value)
    if (
        relative.is_absolute()
        or not value
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise RunnerError(f"Unsafe safetensors index path in {index_path}: {value!r}")
    # Keep the indexed shard path lexical. Hugging Face snapshots represent
    # immutable model files as symlinks into the cache's sibling ``blobs``
    # directory, so resolving the symlink here would make every valid shard
    # appear to escape ``root``. Parent traversal and absolute paths were
    # rejected above; the remaining containment check therefore constrains the
    # name recorded by the index while still allowing the standard cache
    # layout.
    candidate = index_path.parent / relative
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise RunnerError(
            f"Safetensors index escapes its model root: {index_path}: {value!r}"
        ) from exc
    return candidate


def inspect_semantic_safetensors(
    root: Path,
) -> tuple[dict[str, SafeTensorEntry], dict[str, Any]]:
    """Open every safetensors header and return a canonical tensor schema.

    Indexed shards must contain exactly the keys assigned to them. Additional
    unindexed ``*.safetensors`` files are treated as standalone files, but tensor
    names must remain globally unique across both layouts.
    """

    try:
        from safetensors import safe_open
    except ImportError as exc:
        raise RunnerError(
            "Semantic final validation requires the safetensors package."
        ) from exc

    root = root.resolve()
    if not root.is_dir():
        raise RunnerError(f"Safetensors model root is not a directory: {root}")
    # Do not resolve file symlinks: indexed paths and ``all_files`` must share
    # the same lexical namespace for Hugging Face snapshot caches.
    all_files = {
        path
        for path in sorted(root.rglob("*.safetensors"))
        if path.is_file()
    }
    if not all_files:
        raise RunnerError(f"No safetensors weight files found under {root}")

    expected_by_shard: dict[Path, set[str]] = {}
    indexed_names: dict[str, Path] = {}
    index_records: list[dict[str, Any]] = []
    for index_path in sorted(root.rglob("*.safetensors.index.json")):
        raw = read_json(index_path)
        weight_map = raw.get("weight_map")
        if not isinstance(weight_map, dict) or not weight_map:
            raise RunnerError(f"Missing non-empty weight_map in {index_path}")
        index_shards: set[str] = set()
        for tensor_name, shard_name in weight_map.items():
            if not isinstance(tensor_name, str) or not isinstance(shard_name, str):
                raise RunnerError(f"Invalid weight_map entry in {index_path}")
            shard = _safe_indexed_path(root, index_path, shard_name)
            if shard not in all_files or shard.stat().st_size <= 0:
                raise RunnerError(
                    f"Safetensors index references a missing/empty shard: {shard}"
                )
            previous = indexed_names.get(tensor_name)
            if previous is not None:
                raise RunnerError(
                    "Duplicate tensor name across safetensors indices: "
                    f"{tensor_name!r} in {previous} and {index_path}"
                )
            indexed_names[tensor_name] = index_path
            expected_by_shard.setdefault(shard, set()).add(tensor_name)
            index_shards.add(shard.relative_to(root).as_posix())
        index_records.append(
            {
                "path": index_path.relative_to(root).as_posix(),
                "tensor_count": len(weight_map),
                "shards": sorted(index_shards),
            }
        )

    entries: dict[str, SafeTensorEntry] = {}
    file_records: list[dict[str, Any]] = []
    for path in sorted(all_files):
        relative_file = path.relative_to(root).as_posix()
        try:
            with safe_open(str(path), framework="pt", device="cpu") as handle:
                actual_names = set(handle.keys())
                if not actual_names:
                    raise RunnerError(f"Safetensors file has no tensors: {path}")
                expected_names = expected_by_shard.get(path)
                if expected_names is not None and actual_names != expected_names:
                    missing = sorted(expected_names - actual_names)
                    extra = sorted(actual_names - expected_names)
                    raise RunnerError(
                        "Safetensors index/header key mismatch for "
                        f"{relative_file}: missing={missing[:8]}, extra={extra[:8]}"
                    )
                names = sorted(expected_names if expected_names is not None else actual_names)
                for name in names:
                    if name in entries:
                        raise RunnerError(
                            f"Duplicate tensor name across safetensors files: {name!r}"
                        )
                    tensor_slice = handle.get_slice(name)
                    shape = tuple(int(value) for value in tensor_slice.get_shape())
                    dtype = str(tensor_slice.get_dtype())
                    entries[name] = SafeTensorEntry(
                        name=name,
                        path=path,
                        relative_file=relative_file,
                        shape=shape,
                        dtype=dtype,
                        numel=int(math.prod(shape)),
                    )
        except RunnerError:
            raise
        except Exception as exc:
            raise RunnerError(
                f"Could not semantically open safetensors file {path}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        file_records.append(
            {
                "path": relative_file,
                "indexed": path in expected_by_shard,
                "tensor_count": len(
                    expected_by_shard.get(
                        path,
                        {name for name, entry in entries.items() if entry.path == path},
                    )
                ),
            }
        )

    schema_records = [
        {
            "name": name,
            "shape": list(entries[name].shape),
            "dtype": entries[name].dtype,
            "numel": entries[name].numel,
        }
        for name in sorted(entries)
    ]
    summary = {
        "tensor_count": len(entries),
        "total_numel": sum(entry.numel for entry in entries.values()),
        "tensor_schema_sha256": sha256_bytes(canonical_json_bytes(schema_records)),
        "index_files": index_records,
        "weight_files": file_records,
    }
    return entries, summary


def _count_changed_elements(
    initial: SafeTensorEntry,
    final: SafeTensorEntry,
    *,
    max_working_set_bytes: int,
) -> int:
    try:
        import torch
        from safetensors import safe_open
    except ImportError as exc:
        raise RunnerError(
            "Tensor delta comparison requires torch and safetensors."
        ) from exc

    if max_working_set_bytes <= 0:
        raise RunnerError("Delta comparison working-set budget must be positive.")
    if initial.numel == 0:
        return 0

    def exact_changed(left: Any, right: Any) -> int:
        if left.shape != right.shape or left.dtype != right.dtype:
            raise RunnerError(
                f"Tensor chunk schema changed during comparison for {initial.name!r}."
            )
        element_bytes = int(left.element_size())
        left_bytes = left.reshape(-1).contiguous().view(torch.uint8)
        right_bytes = right.reshape(-1).contiguous().view(torch.uint8)
        left_elements = left_bytes.reshape(-1, element_bytes)
        right_elements = right_bytes.reshape(-1, element_bytes)
        return int(left_elements.ne(right_elements).any(dim=1).sum().item())

    row_elements = int(math.prod(initial.shape[1:])) if initial.shape else 1
    estimated_row_bytes = (
        row_elements * DELTA_COMPARE_ESTIMATED_BYTES_PER_ELEMENT
    )
    if estimated_row_bytes > max_working_set_bytes:
        raise RunnerError(
            f"Tensor row for {initial.name!r} exceeds the bounded comparison "
            f"working set: {estimated_row_bytes} > {max_working_set_bytes} bytes."
        )
    rows_per_chunk = max(1, max_working_set_bytes // max(1, estimated_row_bytes))

    try:
        with (
            safe_open(str(initial.path), framework="pt", device="cpu") as left_handle,
            safe_open(str(final.path), framework="pt", device="cpu") as right_handle,
        ):
            if not initial.shape:
                left = left_handle.get_tensor(initial.name)
                right = right_handle.get_tensor(final.name)
                return exact_changed(left, right)

            left_slice = left_handle.get_slice(initial.name)
            right_slice = right_handle.get_slice(final.name)
            changed = 0
            for start in range(0, initial.shape[0], rows_per_chunk):
                end = min(initial.shape[0], start + rows_per_chunk)
                left = left_slice[start:end]
                right = right_slice[start:end]
                changed += exact_changed(left, right)
                del left, right
            return changed
    except Exception as exc:
        raise RunnerError(
            f"Could not compare tensor {initial.name!r}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


def compare_full_update_safetensors(
    initial_root: Path,
    final_root: Path,
    *,
    max_working_set_bytes: int = DELTA_COMPARE_MAX_WORKING_SET_BYTES,
) -> dict[str, Any]:
    """Compare two model trees exactly, one tensor and bounded row chunk at a time."""

    started = time.perf_counter()
    initial_entries, initial_summary = inspect_semantic_safetensors(initial_root)
    final_entries, final_summary = inspect_semantic_safetensors(final_root)
    initial_names = set(initial_entries)
    final_names = set(final_entries)
    if initial_names != final_names:
        raise RunnerError(
            "Initial/final safetensors key set mismatch: "
            f"missing_final={sorted(initial_names - final_names)[:8]}, "
            f"unexpected_final={sorted(final_names - initial_names)[:8]}"
        )

    records: list[dict[str, Any]] = []
    changed_tensor_count = 0
    total_changed_elements = 0
    for name in sorted(initial_names):
        initial = initial_entries[name]
        final = final_entries[name]
        if initial.shape != final.shape:
            raise RunnerError(
                f"Initial/final tensor shape mismatch for {name!r}: "
                f"{initial.shape} != {final.shape}"
            )
        if initial.dtype != final.dtype:
            raise RunnerError(
                f"Initial/final tensor dtype mismatch for {name!r}: "
                f"{initial.dtype} != {final.dtype}"
            )
        changed_elements = _count_changed_elements(
            initial,
            final,
            max_working_set_bytes=max_working_set_bytes,
        )
        changed = changed_elements > 0
        changed_tensor_count += int(changed)
        total_changed_elements += changed_elements
        records.append(
            {
                "name": name,
                "shape": list(initial.shape),
                "dtype": initial.dtype,
                "numel": initial.numel,
                "initial_file": initial.relative_file,
                "final_file": final.relative_file,
                "changed": changed,
                "changed_elements": changed_elements,
            }
        )

    tensor_count = len(records)
    all_changed = tensor_count > 0 and changed_tensor_count == tensor_count
    return {
        "passed": all_changed,
        "initial_semantic": initial_summary,
        "final_semantic": final_summary,
        "tensor_count": tensor_count,
        "changed_tensor_count": changed_tensor_count,
        "unchanged_tensor_count": tensor_count - changed_tensor_count,
        "total_changed_elements": total_changed_elements,
        "all_base_weight_tensors_changed": all_changed,
        "tensors": records,
        "performance": {
            "strategy": "cpu_exact_one_tensor_first_axis_chunks",
            "max_estimated_working_set_bytes": max_working_set_bytes,
            "estimated_bytes_per_compared_element": (
                DELTA_COMPARE_ESTIMATED_BYTES_PER_ELEMENT
            ),
            "elapsed_seconds": time.perf_counter() - started,
            "complexity": "linear_in_total_persisted_weight_elements",
        },
    }


def final_inventory(final_dir: Path) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for path in sorted(final_dir.rglob("*")):
        if path.is_file():
            inventory.append(
                {
                    "path": path.relative_to(final_dir).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    return inventory


def _optimizer_coverage_binding(
    final_dir: Path,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    path = final_dir / "optimizer_coverage.json"
    if not path.is_file() or path.stat().st_size <= 0:
        raise RunnerError(f"Missing final optimizer coverage receipt: {path}")
    coverage = read_json(path)
    checks = coverage.get("checks")
    if (
        coverage.get("format") != OPTIMIZER_COVERAGE_FORMAT
        or coverage.get("passed") is not True
        or coverage.get("train_mode") != "full"
        or not isinstance(checks, dict)
        or any(
            checks.get(key) is not True
            for key in (
                "unique_membership_exact",
                "duplicate_membership_free",
                "full_mode_base_all_trainable",
            )
        )
        or coverage.get("base_all_trainable") is not True
        or int(coverage.get("optimizer_duplicate_memberships", -1)) != 0
        or coverage.get("missing_parameters") != []
        or coverage.get("unexpected_parameters") != []
        or coverage.get("duplicate_parameters") != []
        or coverage.get("frozen_base_parameters") != []
    ):
        raise RunnerError("Final optimizer coverage receipt is not exact/full-scope.")
    report_sha256 = coverage.get("report_sha256")
    if not isinstance(report_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", report_sha256
    ):
        raise RunnerError("Final optimizer coverage receipt has no canonical report hash.")
    if manifest.get("optimizer_coverage_passed") is not True:
        raise RunnerError("Final manifest does not declare passed optimizer coverage.")
    if manifest.get("optimizer_coverage_sha256") != report_sha256:
        raise RunnerError("Final manifest/optimizer coverage report hash mismatch.")
    return {
        "path": "final/optimizer_coverage.json",
        "file_sha256": sha256_file(path),
        "report_sha256": report_sha256,
        "train_mode": "full",
        "passed": True,
    }


def _base_update_coverage_binding(
    final_dir: Path,
    manifest: Mapping[str, Any],
    final_entries: Mapping[str, SafeTensorEntry],
) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]]]:
    """Validate and bind per-base-tensor dynamic optimizer-step evidence."""

    path = final_dir / "base_update_coverage.json"
    if not path.is_file() or path.stat().st_size <= 0:
        raise RunnerError(f"Missing final base update coverage receipt: {path}")
    coverage = read_json(path)
    required_checks = (
        "all_base_parameters_trainable",
        "optimizer_membership_exact",
        "all_gradients_present",
        "all_gradients_finite",
        "all_gradients_nonzero",
        "positive_base_learning_rate",
        "optimizer_step_performed",
        "optimizer_step_not_skipped",
        "all_optimizer_states_advanced",
    )
    checks = coverage.get("checks")
    if (
        coverage.get("format") != BASE_UPDATE_COVERAGE_FORMAT
        or coverage.get("passed") is not True
        or coverage.get("train_mode") != "full"
        or not isinstance(checks, dict)
        or any(checks.get(key) is not True for key in required_checks)
        or any(value is not True for value in checks.values())
    ):
        raise RunnerError("Final base update coverage receipt checks did not pass.")

    parameters = coverage.get("parameters")
    if not isinstance(parameters, list):
        raise RunnerError("Final base update coverage parameters must be a list.")
    expected_count = len(final_entries)
    expected_numel = sum(entry.numel for entry in final_entries.values())
    base_parameter_count = coverage.get("base_parameter_count")
    base_parameter_numel = coverage.get("base_parameter_numel")
    if (
        isinstance(base_parameter_count, bool)
        or not isinstance(base_parameter_count, int)
        or base_parameter_count != expected_count
        or isinstance(base_parameter_numel, bool)
        or not isinstance(base_parameter_numel, int)
        or base_parameter_numel != expected_numel
        or len(parameters) != expected_count
        or expected_count <= 0
    ):
        raise RunnerError("Final base update coverage count/numel is not exact.")

    evidence: dict[str, Mapping[str, Any]] = {}
    for item in parameters:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise RunnerError("Malformed base update coverage parameter record.")
        name = item["name"]
        if name in evidence:
            raise RunnerError(f"Duplicate base update coverage record: {name!r}")
        entry = final_entries.get(name)
        if entry is None:
            raise RunnerError(
                f"Base update coverage name is not an exact final artifact key: {name!r}"
            )
        gradient_nonzero_elements = item.get("gradient_nonzero_elements")
        learning_rate = item.get("learning_rate")
        state_step = item.get("state_step")
        if (
            item.get("shape") != list(entry.shape)
            or item.get("numel") != entry.numel
            or item.get("gradient_present") is not True
            or item.get("gradient_nonzero") is not True
            or isinstance(gradient_nonzero_elements, bool)
            or not isinstance(gradient_nonzero_elements, int)
            or gradient_nonzero_elements <= 0
            or gradient_nonzero_elements > entry.numel
            or item.get("gradient_finite") is not True
            or item.get("update_attempted") is not True
            or item.get("optimizer_family") != "base"
            or isinstance(learning_rate, bool)
            or not isinstance(learning_rate, (int, float))
            or not math.isfinite(float(learning_rate))
            or float(learning_rate) <= 0.0
            or isinstance(state_step, bool)
            or not isinstance(state_step, (int, float))
            or not math.isfinite(float(state_step))
            or float(state_step) < 1.0
        ):
            raise RunnerError(
                f"Base update coverage has incomplete dynamic evidence: {name!r}"
            )
        evidence[name] = item
    if set(evidence) != set(final_entries):
        missing = sorted(set(final_entries) - set(evidence))
        unexpected = sorted(set(evidence) - set(final_entries))
        raise RunnerError(
            "Base update coverage does not exactly cover final artifact tensors: "
            f"missing={missing[:8]}, unexpected={unexpected[:8]}"
        )

    report_sha256 = coverage.get("report_sha256")
    if not isinstance(report_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", report_sha256
    ):
        raise RunnerError("Final base update coverage has no canonical report hash.")
    unsigned_coverage = dict(coverage)
    unsigned_coverage.pop("report_sha256", None)
    actual_report_sha256 = sha256_bytes(
        json.dumps(
            unsigned_coverage,
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    )
    if report_sha256 != actual_report_sha256:
        raise RunnerError("Final base update coverage canonical report hash mismatch.")
    if manifest.get("base_update_coverage_passed") is not True:
        raise RunnerError("Final manifest does not declare passed base update coverage.")
    if manifest.get("base_update_coverage_sha256") != report_sha256:
        raise RunnerError("Final manifest/base update coverage report hash mismatch.")
    return (
        {
            "path": "final/base_update_coverage.json",
            "file_sha256": sha256_file(path),
            "report_sha256": report_sha256,
            "base_parameter_count": expected_count,
            "base_parameter_numel": expected_numel,
            "passed": True,
        },
        evidence,
    )


def _classify_full_update_comparison(
    comparison: Mapping[str, Any],
    dynamic_evidence: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Classify persisted deltas without conflating zero net delta with no attempt."""

    classified = copy.deepcopy(dict(comparison))
    tensors = classified.get("tensors")
    if not isinstance(tensors, list):
        raise RunnerError("Full-update comparison has no tensor records.")
    names: set[str] = set()
    changed_count = 0
    unchanged_count = 0
    changed_elements_total = 0
    for item in tensors:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise RunnerError("Malformed tensor record in full-update comparison.")
        name = item["name"]
        if name in names or name not in dynamic_evidence:
            raise RunnerError(
                f"Full-update comparison/dynamic evidence mismatch for {name!r}."
            )
        names.add(name)
        changed_elements = item.get("changed_elements")
        if isinstance(changed_elements, bool) or not isinstance(changed_elements, int):
            raise RunnerError(f"Invalid changed-element count for {name!r}.")
        changed = changed_elements > 0
        if item.get("changed") is not changed:
            raise RunnerError(f"Inconsistent persisted-delta flag for {name!r}.")
        changed_count += int(changed)
        unchanged_count += int(not changed)
        changed_elements_total += changed_elements
        item["update_evidence_class"] = (
            CHANGED_UPDATE_EVIDENCE_CLASS
            if changed
            else UNCHANGED_UPDATE_EVIDENCE_CLASS
        )
    if names != set(dynamic_evidence):
        raise RunnerError("Dynamic evidence names do not equal comparison tensor names.")
    at_least_one_changed = changed_elements_total > 0
    all_unchanged_classified = all(
        item.get("changed") is True
        or item.get("update_evidence_class") == UNCHANGED_UPDATE_EVIDENCE_CLASS
        for item in tensors
    )
    evaluation = {
        "schema_exact": True,
        "optimizer_coverage_exact": True,
        "dynamic_base_update_coverage_exact": True,
        "full_scope_optimization_attempts_verified": True,
        "at_least_one_persisted_element_changed": at_least_one_changed,
        "all_unchanged_tensors_classified": all_unchanged_classified,
        "persisted_change_tensor_count": changed_count,
        "verified_zero_net_delta_tensor_count": unchanged_count,
        "passed": at_least_one_changed and all_unchanged_classified,
    }
    return classified, evaluation


def _prepared_hashes(prepared: PreparedRun) -> Mapping[str, Any]:
    hashes = prepared.provenance.get("hashes")
    if not isinstance(hashes, Mapping):
        raise RunnerError("Prepared run has no provenance hash mapping.")
    return hashes


def write_full_update_delta(
    prepared: PreparedRun,
    *,
    initial_snapshot: Path,
) -> Path:
    """Create the post-run exact initial-to-final base-weight delta receipt."""

    final_dir = prepared.spec.output_dir / "final"
    final_base = final_dir / "base_model"
    manifest_path = final_dir / "manifest.json"
    if not manifest_path.is_file():
        raise RunnerError(
            f"Cannot compare full-update weights without final manifest: {manifest_path}"
        )
    manifest = read_json(manifest_path)
    coverage = _optimizer_coverage_binding(final_dir, manifest)
    hashes = _prepared_hashes(prepared)
    final_entries, _ = inspect_semantic_safetensors(final_base)
    base_update_coverage, dynamic_evidence = _base_update_coverage_binding(
        final_dir,
        manifest,
        final_entries,
    )

    initial_stats_before = _tree_stat_fingerprint(initial_snapshot)
    final_stats_before = _tree_stat_fingerprint(final_base)
    comparison = compare_full_update_safetensors(initial_snapshot, final_base)
    initial_inventory, initial_inventory_sha256 = _inventory_with_sha256(
        initial_snapshot
    )
    final_inventory, final_inventory_sha256 = _inventory_with_sha256(final_base)
    if initial_stats_before != _tree_stat_fingerprint(initial_snapshot):
        raise RunnerError("Pinned initial snapshot mutated during tensor comparison.")
    if final_stats_before != _tree_stat_fingerprint(final_base):
        raise RunnerError("Final base-model artifact mutated during tensor comparison.")
    if initial_inventory_sha256 != hashes.get("model_snapshot_inventory_sha256"):
        raise RunnerError(
            "Pinned initial snapshot inventory changed after launch preparation."
        )

    initial_semantic = comparison.pop("initial_semantic")
    final_semantic = comparison.pop("final_semantic")
    comparison, evaluation = _classify_full_update_comparison(
        comparison,
        dynamic_evidence,
    )
    if initial_semantic.get("tensor_schema_sha256") != hashes.get(
        "model_snapshot_tensor_schema_sha256"
    ):
        raise RunnerError("Pinned initial tensor schema changed after launch preparation.")

    model = prepared.materialized.get("model")
    if not isinstance(model, Mapping):
        raise RunnerError("Prepared run has no model mapping for delta receipt.")
    receipt = {
        "format": FULL_UPDATE_DELTA_FORMAT,
        "created_utc": utc_now(),
        "passed": bool(evaluation["passed"]),
        "run_id": prepared.spec.run_id,
        "model": {
            "name_or_path": model.get("name_or_path"),
            "revision": model.get("revision"),
            "train_mode": model.get("train_mode"),
        },
        "model_receipt_sha256": hashes.get("model_receipt_sha256"),
        "optimizer_coverage": coverage,
        "base_update_coverage": base_update_coverage,
        "initial": {
            "snapshot_inventory_sha256": initial_inventory_sha256,
            "snapshot_file_count": len(initial_inventory),
            "snapshot_total_bytes": sum(
                int(item["bytes"]) for item in initial_inventory
            ),
            **initial_semantic,
        },
        "final": {
            "base_model_inventory_sha256": final_inventory_sha256,
            "base_model_file_count": len(final_inventory),
            "base_model_total_bytes": sum(
                int(item["bytes"]) for item in final_inventory
            ),
            **final_semantic,
        },
        "comparison": comparison,
        "evaluation": evaluation,
        "claim_boundary": (
            "Passing mechanically proves exact initial/final base-model key/shape/dtype "
            "schemas, exact static optimizer membership, full-scope finite nonzero "
            "gradient and optimizer-step attempts for every persisted base tensor, and "
            "at least one exact stored-element change. An unchanged tensor is accepted "
            "only as a verified update attempt with zero persisted net delta. It does "
            "not prove that every stored parameter moved, training quality, causal "
            "memory, generalization, or scientific success."
        ),
        "performance_boundary": (
            "The value comparison is one post-run O(total persisted weight elements) "
            "CPU pass using one tensor and bounded first-axis chunks at a time. Dry-run "
            "never performs this comparison; later receipt verification reopens headers "
            "and performs O(total artifact bytes) inventory hashing without repeating "
            "the elementwise initial-to-final value scan."
        ),
    }
    path = prepared.spec.output_dir / "FULL_UPDATE_DELTA.json"
    atomic_write_json(path, receipt)
    return path


def validate_full_update_delta(
    prepared: PreparedRun,
    *,
    final_dir: Path,
    manifest: Mapping[str, Any],
    final_entries: Mapping[str, SafeTensorEntry],
    final_semantic: Mapping[str, Any],
    final_base_inventory_sha256: str,
) -> dict[str, Any]:
    path = prepared.spec.output_dir / "FULL_UPDATE_DELTA.json"
    if not path.is_file() or path.stat().st_size <= 0:
        raise RunnerError(f"Missing FULL_UPDATE_DELTA.json for {prepared.spec.run_id}")
    receipt = read_json(path)
    if (
        receipt.get("format") != FULL_UPDATE_DELTA_FORMAT
        or receipt.get("passed") is not True
        or receipt.get("run_id") != prepared.spec.run_id
    ):
        raise RunnerError(
            f"Full-update delta receipt is incomplete/failed for {prepared.spec.run_id}"
        )

    expected_model = prepared.materialized.get("model")
    observed_model = receipt.get("model")
    if not isinstance(expected_model, Mapping) or not isinstance(observed_model, dict):
        raise RunnerError("Full-update delta model binding is malformed.")
    for key in ("name_or_path", "revision", "train_mode"):
        if observed_model.get(key) != expected_model.get(key):
            raise RunnerError(f"Full-update delta model.{key} mismatch.")
    if observed_model.get("train_mode") != "full":
        raise RunnerError("Full-update delta is not bound to train_mode='full'.")

    hashes = _prepared_hashes(prepared)
    if receipt.get("model_receipt_sha256") != hashes.get("model_receipt_sha256"):
        raise RunnerError("Full-update delta/model prefetch receipt hash mismatch.")
    initial = receipt.get("initial")
    final = receipt.get("final")
    comparison = receipt.get("comparison")
    evaluation = receipt.get("evaluation")
    if not isinstance(initial, dict) or not isinstance(final, dict) or not isinstance(
        comparison, dict
    ) or not isinstance(evaluation, dict):
        raise RunnerError("Full-update delta receipt sections are malformed.")
    if initial.get("snapshot_inventory_sha256") != hashes.get(
        "model_snapshot_inventory_sha256"
    ):
        raise RunnerError("Full-update delta initial inventory binding mismatch.")
    if initial.get("tensor_schema_sha256") != hashes.get(
        "model_snapshot_tensor_schema_sha256"
    ):
        raise RunnerError("Full-update delta initial tensor-schema binding mismatch.")

    if final.get("base_model_inventory_sha256") != final_base_inventory_sha256:
        raise RunnerError("Full-update delta final inventory binding mismatch.")
    if final.get("tensor_schema_sha256") != final_semantic.get(
        "tensor_schema_sha256"
    ):
        raise RunnerError("Full-update delta final tensor-schema binding mismatch.")

    coverage = _optimizer_coverage_binding(final_dir, manifest)
    if receipt.get("optimizer_coverage") != coverage:
        raise RunnerError("Full-update delta optimizer-coverage binding mismatch.")
    base_update_coverage, dynamic_evidence = _base_update_coverage_binding(
        final_dir,
        manifest,
        final_entries,
    )
    if receipt.get("base_update_coverage") != base_update_coverage:
        raise RunnerError("Full-update delta base-update-coverage binding mismatch.")

    tensors = comparison.get("tensors")
    if not isinstance(tensors, list) or len(tensors) != int(
        final_semantic.get("tensor_count", -1)
    ):
        raise RunnerError("Full-update delta tensor records/count mismatch.")
    expected_names: set[str] = set()
    changed_total = 0
    changed_count = 0
    unchanged_count = 0
    for item in tensors:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise RunnerError("Malformed tensor record in full-update delta receipt.")
        name = item["name"]
        if name in expected_names:
            raise RunnerError(f"Duplicate tensor delta record: {name!r}")
        expected_names.add(name)
        entry = final_entries.get(name)
        if entry is None:
            raise RunnerError(f"Tensor delta record is absent from final weights: {name!r}")
        numel = int(item.get("numel", -1))
        changed_elements = int(item.get("changed_elements", -1))
        changed = changed_elements > 0
        expected_class = (
            CHANGED_UPDATE_EVIDENCE_CLASS
            if changed
            else UNCHANGED_UPDATE_EVIDENCE_CLASS
        )
        if (
            item.get("shape") != list(entry.shape)
            or item.get("dtype") != entry.dtype
            or numel != entry.numel
            or numel <= 0
            or changed_elements < 0
            or changed_elements > numel
            or item.get("changed") is not changed
            or item.get("update_evidence_class") != expected_class
        ):
            raise RunnerError(f"Tensor did not pass exact update evidence: {name!r}")
        changed_count += int(changed)
        unchanged_count += int(not changed)
        changed_total += changed_elements
    if expected_names != set(final_entries):
        raise RunnerError("Full-update delta names do not equal final tensor names.")
    all_changed = len(tensors) > 0 and changed_count == len(tensors)
    if (
        comparison.get("passed") is not all_changed
        or comparison.get("all_base_weight_tensors_changed") is not all_changed
        or int(comparison.get("tensor_count", -1)) != len(tensors)
        or int(comparison.get("changed_tensor_count", -1)) != changed_count
        or int(comparison.get("unchanged_tensor_count", -1)) != unchanged_count
        or int(comparison.get("total_changed_elements", -1)) != changed_total
    ):
        raise RunnerError("Full-update delta aggregate fields are inconsistent.")
    recomputed_comparison, recomputed_evaluation = _classify_full_update_comparison(
        comparison,
        dynamic_evidence,
    )
    if recomputed_comparison != comparison or recomputed_evaluation != evaluation:
        raise RunnerError("Full-update delta evidence classes/evaluation are inconsistent.")
    if receipt.get("passed") is not recomputed_evaluation["passed"]:
        raise RunnerError("Full-update delta primary PASS is inconsistent.")
    if recomputed_evaluation["passed"] is not True:
        raise RunnerError(
            f"Full-update delta receipt is incomplete/failed for {prepared.spec.run_id}"
        )

    return {
        "path": "FULL_UPDATE_DELTA.json",
        "sha256": sha256_file(path),
        "passed": True,
        "model_revision": observed_model["revision"],
        "initial_inventory_sha256": initial["snapshot_inventory_sha256"],
        "final_inventory_sha256": final["base_model_inventory_sha256"],
        "initial_tensor_schema_sha256": initial["tensor_schema_sha256"],
        "final_tensor_schema_sha256": final["tensor_schema_sha256"],
        "optimizer_coverage_file_sha256": coverage["file_sha256"],
        "base_update_coverage_file_sha256": base_update_coverage["file_sha256"],
        "base_update_coverage_report_sha256": base_update_coverage["report_sha256"],
        "tensor_count": len(tensors),
        "changed_tensor_count": changed_count,
        "unchanged_tensor_count": unchanged_count,
        "all_base_weight_tensors_changed": all_changed,
        "total_changed_elements": changed_total,
    }


def validate_allocator_environment_file(
    path: Path,
    *,
    configured: Any,
    expected_source_sha256: str,
    label: str,
    receipt_path: str,
) -> dict[str, Any]:
    """Validate and hash one child process's observed allocator policy."""

    if not path.is_file() or path.stat().st_size <= 0:
        raise RunnerError(f"Missing environment.json for {label}")
    environment = read_json(path)
    snapshot_settings = environment.get("allocator_snapshot_settings")
    allocated_bytes = environment.get("cuda_memory_allocated_bytes")
    runtime_identity = {
        key: environment.get(key)
        for key in (
            "harness_version",
            "python",
            "platform",
            "hostname",
            "torch",
            "cuda_runtime",
            "cudnn",
            "source_sha256",
            "cuda_devices",
            "transformers",
            "peft",
            "safetensors",
        )
    }
    checks = {
        "configured_policy_exact": configured == CUDA_ALLOCATOR_CONF,
        "primary_environment_exact": (
            environment.get("pytorch_alloc_conf") == CUDA_ALLOCATOR_CONF
        ),
        "legacy_alias_absent": (
            "pytorch_cuda_alloc_conf_legacy" in environment
            and
            environment.get("pytorch_cuda_alloc_conf_legacy") is None
        ),
        "hip_legacy_alias_absent": (
            "pytorch_hip_alloc_conf_legacy" in environment
            and
            environment.get("pytorch_hip_alloc_conf_legacy") is None
        ),
        "caching_allocator_enabled": (
            "pytorch_no_cuda_memory_caching" in environment
            and
            environment.get("pytorch_no_cuda_memory_caching") is None
        ),
        "native_backend_reported": environment.get("allocator_backend") == "native",
        "parsed_settings_roundtrip_exact": (
            environment.get("allocator_settings") == CUDA_ALLOCATOR_CONF
        ),
        "snapshot_expandable_segments_enabled": (
            isinstance(snapshot_settings, Mapping)
            and snapshot_settings.get("expandable_segments") is True
        ),
        "allocator_initialized": environment.get("allocator_initialized") is True,
        "live_cuda_allocation_observed": (
            isinstance(allocated_bytes, int)
            and not isinstance(allocated_bytes, bool)
            and allocated_bytes > 0
        ),
        "runtime_identity_complete": (
            all(key in environment for key in runtime_identity)
            and all(
                runtime_identity.get(key) is not None
                for key in (
                    "harness_version",
                    "python",
                    "platform",
                    "hostname",
                    "torch",
                    "cuda_runtime",
                    "cudnn",
                    "source_sha256",
                    "transformers",
                    "safetensors",
                )
            )
            and isinstance(runtime_identity.get("cuda_devices"), list)
            and len(runtime_identity["cuda_devices"]) > 0
        ),
        "source_identity_exact": (
            runtime_identity.get("source_sha256") == expected_source_sha256
        ),
    }
    if not all(checks.values()):
        failed = sorted(key for key, passed in checks.items() if not passed)
        raise RunnerError(
            "Allocator environment did not satisfy the pinned policy for "
            f"{label}: {failed}"
        )
    return {
        "path": receipt_path,
        "sha256": sha256_file(path),
        "configured": configured,
        "observed_primary": environment["pytorch_alloc_conf"],
        "observed_legacy_alias": environment.get(
            "pytorch_cuda_alloc_conf_legacy"
        ),
        "observed_hip_legacy_alias": environment.get(
            "pytorch_hip_alloc_conf_legacy"
        ),
        "observed_caching_allocator_disable": environment.get(
            "pytorch_no_cuda_memory_caching"
        ),
        "active_backend": environment["allocator_backend"],
        "parsed_settings": environment["allocator_settings"],
        "snapshot_settings": snapshot_settings,
        "allocator_initialized": environment["allocator_initialized"],
        "cuda_memory_allocated_bytes": allocated_bytes,
        "cuda_memory_reserved_bytes": environment.get(
            "cuda_memory_reserved_bytes"
        ),
        "runtime_identity": runtime_identity,
        "checks": checks,
        "passed": True,
    }


def validate_allocator_environment(prepared: PreparedRun) -> dict[str, Any]:
    """Bind the matrix child's observed allocator policy to verification."""

    train = prepared.materialized.get("train")
    if not isinstance(train, Mapping):
        raise RunnerError("Prepared train config is malformed.")
    hashes = _prepared_hashes(prepared)
    source_files = hashes.get("source_files_sha256")
    if not isinstance(source_files, Mapping):
        raise RunnerError("Prepared source hash mapping is malformed.")
    expected_source_sha256 = source_files.get(
        "src/latent_workspace_ft_v10/engine.py"
    )
    if not isinstance(expected_source_sha256, str):
        raise RunnerError("Prepared engine source hash is missing.")
    return validate_allocator_environment_file(
        prepared.spec.output_dir / "environment.json",
        configured=train.get("cuda_allocator_conf"),
        expected_source_sha256=expected_source_sha256,
        label=prepared.spec.run_id,
        receipt_path="environment.json",
    )


def validate_final(prepared: PreparedRun) -> dict[str, Any]:
    final_dir = prepared.spec.output_dir / "final"
    completed = final_dir / "COMPLETED"
    manifest_path = final_dir / "manifest.json"
    config_path = final_dir / "experiment_config.json"
    for required in (
        completed,
        manifest_path,
        config_path,
        final_dir / "workspace_state.pt",
        final_dir / "trainer_state.pt",
        final_dir / "base_model" / "config.json",
        final_dir / "optimizer_coverage.json",
        final_dir / "base_update_coverage.json",
    ):
        if not required.is_file() or required.stat().st_size <= 0:
            raise RunnerError(f"Incomplete final artifact for {prepared.spec.run_id}: {required}")
    if completed.read_text(encoding="utf-8").strip() != "ok":
        raise RunnerError(f"Invalid COMPLETED marker for {prepared.spec.run_id}")
    manifest = read_json(manifest_path)
    if manifest.get("complete") is not True:
        raise RunnerError(f"Final manifest is not complete for {prepared.spec.run_id}")
    if int(manifest.get("global_step", -1)) != prepared.spec.max_steps:
        raise RunnerError(f"Final global_step mismatch for {prepared.spec.run_id}")
    final_config = read_json(config_path)
    final_model = final_config.get("model")
    final_train = final_config.get("train")
    expected_model = prepared.materialized.get("model")
    if not isinstance(final_model, dict) or not isinstance(final_train, dict):
        raise RunnerError(f"Final experiment config is malformed for {prepared.spec.run_id}")
    if not isinstance(expected_model, dict):
        raise RunnerError("Prepared model config is malformed.")
    for key in ("name_or_path", "revision", "train_mode"):
        if final_model.get(key) != expected_model.get(key):
            raise RunnerError(f"Final model.{key} mismatch for {prepared.spec.run_id}")
    if int(final_train.get("seed", -1)) != prepared.spec.seed:
        raise RunnerError(f"Final seed mismatch for {prepared.spec.run_id}")
    if int(final_train.get("max_steps", -1)) != prepared.spec.max_steps:
        raise RunnerError(f"Final max_steps mismatch for {prepared.spec.run_id}")
    if final_train.get("cuda_allocator_conf") != CUDA_ALLOCATOR_CONF:
        raise RunnerError(
            f"Final allocator config mismatch for {prepared.spec.run_id}"
        )
    allocator_environment = validate_allocator_environment(prepared)
    weights = model_cache.inspect_safetensors_layout(final_dir / "base_model")
    semantic_entries, semantic_weights = inspect_semantic_safetensors(
        final_dir / "base_model"
    )
    inventory = final_inventory(final_dir)
    if not inventory:
        raise RunnerError(f"Empty final artifact inventory for {prepared.spec.run_id}")
    base_inventory = [
        {
            **item,
            "path": str(item["path"])[len("base_model/") :],
        }
        for item in inventory
        if str(item.get("path", "")).startswith("base_model/")
    ]
    final_base_inventory_sha256 = sha256_bytes(
        canonical_json_bytes(base_inventory)
    )
    full_update_delta = validate_full_update_delta(
        prepared,
        final_dir=final_dir,
        manifest=manifest,
        final_entries=semantic_entries,
        final_semantic=semantic_weights,
        final_base_inventory_sha256=final_base_inventory_sha256,
    )
    return {
        "manifest": manifest,
        "weights": weights,
        "semantic_weights": semantic_weights,
        "full_update_delta": full_update_delta,
        "allocator_environment": allocator_environment,
        "inventory": inventory,
    }


def write_verification(prepared: PreparedRun, validated: Mapping[str, Any]) -> Path:
    receipt = {
        "format": VERIFICATION_FORMAT,
        "verified": True,
        "verified_utc": utc_now(),
        "provenance": prepared.provenance,
        "final_manifest": validated["manifest"],
        "weights": validated["weights"],
        "semantic_weights": validated["semantic_weights"],
        "full_update_delta": validated["full_update_delta"],
        "allocator_environment": validated["allocator_environment"],
        "final_inventory": validated["inventory"],
        "claim_boundary": (
            "This verifies artifact completeness and byte identity plus the bound "
            "mechanical full-scope optimizer membership, per-base-tensor optimization "
            "attempt evidence, exact persisted-delta classification, and the child "
            "process's reported native allocator backend, parsed policy, effective "
            "expandable_segments=true snapshot setting, and live CUDA allocation for "
            "one contracted run. It does not prove that any particular allocation "
            "expanded, that every stored parameter moved, training quality, or "
            "scientific success."
        ),
    }
    path = prepared.spec.output_dir / "RUN_VERIFICATION.json"
    atomic_write_json(path, receipt)
    return path


def verify_completed(prepared: PreparedRun) -> tuple[bool, str]:
    receipt_path = prepared.spec.output_dir / "RUN_VERIFICATION.json"
    if not receipt_path.is_file():
        return False, "missing RUN_VERIFICATION.json"
    try:
        receipt = read_json(receipt_path)
        if receipt.get("format") != VERIFICATION_FORMAT or receipt.get("verified") is not True:
            return False, "unsupported/incomplete verification receipt"
        if receipt.get("provenance") != prepared.provenance:
            return False, "provenance mismatch"
        validated = validate_final(prepared)
        if receipt.get("final_inventory") != validated["inventory"]:
            return False, "final inventory/hash mismatch"
        if receipt.get("weights") != validated["weights"]:
            return False, "safetensors layout mismatch"
        if receipt.get("semantic_weights") != validated["semantic_weights"]:
            return False, "safetensors semantic-schema mismatch"
        if receipt.get("full_update_delta") != validated["full_update_delta"]:
            return False, "full-update delta receipt/hash mismatch"
        if receipt.get("allocator_environment") != validated["allocator_environment"]:
            return False, "allocator environment receipt/hash mismatch"
    except (RunnerError, OSError, ValueError, TypeError) as exc:
        return False, str(exc)
    return True, "verified"


def classify_prepared_run(prepared: PreparedRun) -> tuple[str, str]:
    """Classify retention markers before ordinary live-artifact validation.

    A prune receipt or intent is a protected state transition.  It must never
    fall through to ``stale_incomplete``, where the normal runner would archive
    the output and launch a fresh training process.  In particular, a valid
    historical prune receipt with provenance different from the currently
    prepared run is ``invalid_prune_receipt``, not stale output.
    """

    prune_state, prune_reason = verified_pruning.classify_prune_state(
        prepared.spec.output_dir,
        expected_provenance=prepared.provenance,
    )
    if prune_state is not None:
        return prune_state, prune_reason
    complete, reason = verify_completed(prepared)
    if complete:
        return "verified_completed", reason
    if prepared.spec.output_dir.exists():
        return "stale_incomplete", reason
    return "pending", reason


def archive_incomplete(repo_root: Path, prepared: PreparedRun, archive_root: Path) -> Path:
    output = prepared.spec.output_dir
    if not output.exists():
        raise RunnerError(f"Cannot archive missing output: {output}")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    destination = (
        archive_root
        / prepared.spec.condition
        / f"seed_{prepared.spec.seed}"
        / f"{stamp}-{uuid.uuid4().hex[:12]}"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(output, destination)
    return destination


def _status_path(control_dir: Path, prepared: PreparedRun) -> Path:
    return (
        control_dir
        / "run_status"
        / prepared.spec.condition
        / f"seed_{prepared.spec.seed}.json"
    )


def write_status(
    control_dir: Path,
    prepared: PreparedRun,
    *,
    state: str,
    detail: str,
    extra: Mapping[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "format": STATUS_FORMAT,
        "updated_utc": utc_now(),
        "state": state,
        "detail": detail,
        "provenance": prepared.provenance,
    }
    if extra:
        payload.update(extra)
    atomic_write_json(_status_path(control_dir, prepared), payload)


def write_progress(
    path: Path,
    *,
    profile: str,
    total: int,
    states: Mapping[str, str],
    current: str | None,
    stopped_by_max_runs: bool = False,
) -> None:
    counts: dict[str, int] = {}
    for state in states.values():
        counts[state] = counts.get(state, 0) + 1
    atomic_write_json(
        path,
        {
            "format": PROGRESS_FORMAT,
            "updated_utc": utc_now(),
            "profile": profile,
            "total_runs": total,
            "counts": counts,
            "current_run": current,
            "stopped_by_max_runs": stopped_by_max_runs,
        },
    )


def _default_child_command(options: RunnerOptions, config_path: Path) -> list[str]:
    return [
        options.python,
        "-m",
        options.engine_module,
        "train",
        "--config",
        str(config_path),
        "--fresh",
    ]


def run_child(
    command: Sequence[str],
    *,
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    environment: Mapping[str, str],
) -> tuple[int, int | None]:
    child: subprocess.Popen[bytes] | None = None
    received_signal: int | None = None
    old_handlers: dict[int, Any] = {}

    def forward(signum: int, _frame: Any) -> None:
        nonlocal received_signal
        received_signal = signum
        if child is not None and child.poll() is None:
            try:
                os.killpg(child.pid, signum)
            except ProcessLookupError:
                pass

    for signum in (signal.SIGINT, signal.SIGTERM):
        old_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, forward)
    try:
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            child = subprocess.Popen(
                list(command),
                cwd=cwd,
                env=dict(environment),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
                close_fds=True,
            )
            return child.wait(), received_signal
    finally:
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)


def offline_environment(
    repo_root: Path,
    *,
    cache_dir: Path | None = None,
) -> dict[str, str]:
    environment = dict(os.environ)
    for forbidden in (
        CUDA_ALLOCATOR_LEGACY_ENV,
        CUDA_ALLOCATOR_HIP_LEGACY_ENV,
        CUDA_ALLOCATOR_DISABLE_ENV,
    ):
        environment.pop(forbidden, None)
    environment.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "TOKENIZERS_PARALLELISM": "false",
            CUDA_ALLOCATOR_ENV: CUDA_ALLOCATOR_CONF,
        }
    )
    if cache_dir is not None:
        environment["HF_HUB_CACHE"] = str(cache_dir.resolve())
    source = str(repo_root / "src")
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = source if not existing else source + os.pathsep + existing
    return environment


def run_matrix(
    options: RunnerOptions,
    *,
    child_command_factory: Callable[[RunnerOptions, Path], Sequence[str]] | None = None,
    preflight_fn: Callable[[RunnerOptions], Mapping[str, Any]] = cuda_disk_preflight,
) -> dict[str, Any]:
    repo_root = options.repo_root.resolve()
    if options.profile not in PROFILES:
        raise RunnerError(f"Unknown profile: {options.profile}")
    if options.max_runs is not None and options.max_runs < 1:
        raise RunnerError("--max-runs must be >= 1.")
    if not 0 <= options.maximum_gpu_utilization_percent <= 100:
        raise RunnerError("--maximum-gpu-utilization-percent must be between 0 and 100.")
    if options.minimum_free_disk_gib < 0 or options.minimum_free_vram_gib < 0:
        raise RunnerError("Free disk/VRAM thresholds must be non-negative.")
    matrix_path = resolve_repo_path(repo_root, options.matrix_path, label="matrix")
    contract_path = resolve_repo_path(repo_root, options.contract_path, label="contract")
    model_receipt = resolve_repo_path(repo_root, options.model_receipt, label="model receipt")
    qualification_root = resolve_repo_path(
        repo_root, options.qualification_root, label="qualification root"
    )
    matrix, specs = load_matrix(repo_root, matrix_path, options.profile)
    contract = read_json(contract_path)
    contract_data_hashes = validate_contract(
        repo_root, contract_path, contract, matrix, options.profile
    )
    source_files, source_tree_sha256 = source_hashes(repo_root)

    cache_dir = options.cache_dir
    if cache_dir is not None:
        cache_dir = cache_dir.expanduser()
        if not cache_dir.is_absolute():
            cache_dir = repo_root / cache_dir
        cache_dir = cache_dir.resolve()

    matrix_model = matrix.get("model")
    if not isinstance(matrix_model, dict):
        raise RunnerError("Matrix model object is missing.")
    try:
        verified_model = model_cache.verify_prefetch_receipt(
            model_receipt,
            expected_model=str(matrix_model["name_or_path"]),
            expected_revision=str(matrix_model["revision"]),
            snapshot_path=options.model_snapshot,
            cache_dir=cache_dir,
        )
    except model_cache.PrefetchError as exc:
        raise RunnerError(f"Model prefetch receipt/cache verification failed: {exc}") from exc

    initial_snapshot = Path(verified_model["snapshot_path"]).resolve()
    verified_receipt = verified_model.get("receipt")
    verified_snapshot = (
        verified_receipt.get("snapshot")
        if isinstance(verified_receipt, Mapping)
        else None
    )
    verified_inventory = (
        verified_snapshot.get("files")
        if isinstance(verified_snapshot, Mapping)
        else None
    )
    if not isinstance(verified_inventory, list):
        raise RunnerError("Verified model receipt has no snapshot inventory.")
    initial_inventory_sha256 = sha256_bytes(
        canonical_json_bytes(verified_inventory)
    )
    _initial_entries, initial_semantic = inspect_semantic_safetensors(
        initial_snapshot
    )

    prepared = prepare_runs(
        repo_root=repo_root,
        profile=options.profile,
        matrix=matrix,
        specs=specs,
        contract_path=contract_path,
        matrix_path=matrix_path,
        model_receipt_path=model_receipt,
        source_files=source_files,
        source_tree_sha256=source_tree_sha256,
        contract_data_hashes=contract_data_hashes,
        model_snapshot_inventory_sha256=initial_inventory_sha256,
        model_snapshot_tensor_schema_sha256=str(
            initial_semantic["tensor_schema_sha256"]
        ),
    )
    common_hashes = prepared[0].provenance["hashes"]
    if not isinstance(common_hashes, dict):
        raise RunnerError("Prepared provenance hashes are malformed.")
    gate_profile = PROFILE_GATE.get(options.profile)
    if gate_profile is not None:
        expected_gate = qualification_requirements(
            repo_root=repo_root,
            gate_profile=gate_profile,
            contract_sha256=str(common_hashes["contract_sha256"]),
            model_receipt_sha256=str(common_hashes["model_receipt_sha256"]),
            source_tree_sha256=str(common_hashes["source_tree_sha256"]),
            data_hashes=contract_data_hashes,
            runner_sha256=str(common_hashes["runner_sha256"]),
        )
        require_qualification(
            repo_root=repo_root,
            profile=options.profile,
            qualification_root=qualification_root,
            expected=expected_gate,
        )

    states: dict[str, str] = {}
    reasons: dict[str, str] = {}
    for item in prepared:
        state, reason = classify_prepared_run(item)
        states[item.spec.run_id] = state
        reasons[item.spec.run_id] = reason

    plan = {
        "profile": options.profile,
        "matrix": _repo_relative(repo_root, matrix_path),
        "matrix_sha256": sha256_file(matrix_path),
        "contract_sha256": sha256_file(contract_path),
        "model_receipt_sha256": verified_model["receipt_sha256"],
        "source_tree_sha256": source_tree_sha256,
        "model_snapshot_inventory_sha256": initial_inventory_sha256,
        "model_snapshot_tensor_schema_sha256": initial_semantic[
            "tensor_schema_sha256"
        ],
        "states": states,
        "reasons": reasons,
        "offline_training": True,
        "pytorch_alloc_conf": CUDA_ALLOCATOR_CONF,
        "pytorch_cuda_alloc_conf_legacy": None,
        "pytorch_hip_alloc_conf_legacy": None,
        "pytorch_no_cuda_memory_caching": None,
        "dry_run": options.dry_run,
        "max_runs": options.max_runs,
    }
    if options.dry_run:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return plan

    control_dir = repo_root / "runs" / "v10" / "_control" / options.profile
    progress_path = control_dir / "PROGRESS.json"
    journal_path = control_dir / "JOURNAL.jsonl"
    archive_root = repo_root / "runs" / "v10" / "_archived_incomplete" / options.profile
    lock_path = repo_root / "runs" / "v10" / "_control" / "RUNNER.lock"
    command_factory = child_command_factory or _default_child_command
    launched = 0

    with exclusive_lock(lock_path):
        # The dry-run snapshot above is informational only.  A standalone
        # pruner shares this lock and may have completed or faulted after that
        # snapshot.  Never archive or launch from a pre-lock classification.
        for item in prepared:
            state, reason = classify_prepared_run(item)
            states[item.spec.run_id] = state
            reasons[item.spec.run_id] = reason
        protected_prune_states = {
            run_id: state
            for run_id, state in states.items()
            if state in {"prune_incomplete", "invalid_prune_receipt"}
        }
        if protected_prune_states:
            details = ", ".join(
                f"{run_id}={state}: {reasons[run_id]}"
                for run_id, state in sorted(protected_prune_states.items())
            )
            raise RunnerError(
                "Matrix contains a protected prune state; automatic archive and rerun "
                f"are forbidden until explicit recovery: {details}"
            )
        preflight = dict(preflight_fn(options))
        append_jsonl_atomic(
            journal_path,
            {
                "event": "runner_started",
                "time": utc_now(),
                "profile": options.profile,
                "preflight": preflight,
                "hashes": common_hashes,
            },
        )
        write_progress(
            progress_path,
            profile=options.profile,
            total=len(prepared),
            states=states,
            current=None,
        )
        for item in prepared:
            run_id = item.spec.run_id
            if states[run_id] in {"verified_completed", "verified_pruned"}:
                state = states[run_id]
                detail = (
                    "Skipped after full receipt and artifact hash verification."
                    if state == "verified_completed"
                    else (
                        "Skipped after exact verification of the intentional prune "
                        "receipt, retained evidence, compact export, and target absence."
                    )
                )
                write_status(
                    control_dir,
                    item,
                    state=state,
                    detail=detail,
                )
                append_jsonl_atomic(
                    journal_path,
                    {
                        "event": "run_skipped",
                        "time": utc_now(),
                        "run_id": run_id,
                        "state": state,
                    },
                )
                continue
            if options.max_runs is not None and launched >= options.max_runs:
                write_progress(
                    progress_path,
                    profile=options.profile,
                    total=len(prepared),
                    states=states,
                    current=None,
                    stopped_by_max_runs=True,
                )
                append_jsonl_atomic(
                    journal_path,
                    {
                        "event": "runner_stopped_by_max_runs",
                        "time": utc_now(),
                        "launched": launched,
                    },
                )
                return {**plan, "states": states, "launched": launched}

            if item.spec.output_dir.exists():
                archived = archive_incomplete(repo_root, item, archive_root)
                states[run_id] = "archived_incomplete"
                write_status(
                    control_dir,
                    item,
                    state="archived_incomplete",
                    detail=(
                        "Existing output was not fully verified and was archived "
                        "before fresh rerun."
                    ),
                    extra={"archived_to": _repo_relative(repo_root, archived)},
                )
                append_jsonl_atomic(
                    journal_path,
                    {
                        "event": "stale_output_archived",
                        "time": utc_now(),
                        "run_id": run_id,
                        "archived_to": _repo_relative(repo_root, archived),
                    },
                )

            latest_preflight = dict(preflight_fn(options))
            item.spec.output_dir.mkdir(parents=True, exist_ok=False)
            config_path = item.spec.output_dir / "LAUNCHED_CONFIG.json"
            atomic_write_bytes(config_path, item.materialized_bytes)
            states[run_id] = "running"
            write_status(
                control_dir,
                item,
                state="running",
                detail="Fresh offline subprocess launched.",
                extra={"preflight": latest_preflight},
            )
            write_progress(
                progress_path,
                profile=options.profile,
                total=len(prepared),
                states=states,
                current=run_id,
            )
            append_jsonl_atomic(
                journal_path,
                {"event": "run_started", "time": utc_now(), "run_id": run_id},
            )
            command = list(command_factory(options, config_path))
            launched += 1
            try:
                returncode, received_signal = run_child(
                    command,
                    cwd=repo_root,
                    stdout_path=item.spec.output_dir / "subprocess.stdout.log",
                    stderr_path=item.spec.output_dir / "subprocess.stderr.log",
                    environment=offline_environment(repo_root, cache_dir=cache_dir),
                )
            except OSError as exc:
                states[run_id] = "launch_failed"
                write_status(
                    control_dir,
                    item,
                    state="launch_failed",
                    detail=f"Could not launch the training subprocess: {exc}",
                )
                write_progress(
                    progress_path,
                    profile=options.profile,
                    total=len(prepared),
                    states=states,
                    current=None,
                )
                append_jsonl_atomic(
                    journal_path,
                    {
                        "event": "run_launch_failed",
                        "time": utc_now(),
                        "run_id": run_id,
                        "error": str(exc),
                    },
                )
                raise RunnerError(f"Could not launch {run_id}: {exc}") from exc
            if received_signal is not None:
                states[run_id] = "interrupted"
                write_status(
                    control_dir,
                    item,
                    state="interrupted",
                    detail=f"Runner forwarded signal {received_signal} to the child process group.",
                    extra={"returncode": returncode, "signal": received_signal},
                )
                write_progress(
                    progress_path,
                    profile=options.profile,
                    total=len(prepared),
                    states=states,
                    current=None,
                )
                append_jsonl_atomic(
                    journal_path,
                    {
                        "event": "run_interrupted",
                        "time": utc_now(),
                        "run_id": run_id,
                        "signal": received_signal,
                        "returncode": returncode,
                    },
                )
                raise RunnerError(f"Run interrupted by signal {received_signal}: {run_id}")
            if returncode != 0:
                states[run_id] = "failed"
                write_status(
                    control_dir,
                    item,
                    state="failed",
                    detail="Training subprocess exited nonzero; output is preserved.",
                    extra={"returncode": returncode},
                )
                write_progress(
                    progress_path,
                    profile=options.profile,
                    total=len(prepared),
                    states=states,
                    current=None,
                )
                append_jsonl_atomic(
                    journal_path,
                    {
                        "event": "run_failed",
                        "time": utc_now(),
                        "run_id": run_id,
                        "returncode": returncode,
                    },
                )
                raise RunnerError(f"Training subprocess failed ({returncode}): {run_id}")

            try:
                write_full_update_delta(
                    item,
                    initial_snapshot=initial_snapshot,
                )
                validated = validate_final(item)
            except RunnerError as exc:
                states[run_id] = "invalid_final"
                write_status(
                    control_dir,
                    item,
                    state="invalid_final",
                    detail=str(exc),
                )
                write_progress(
                    progress_path,
                    profile=options.profile,
                    total=len(prepared),
                    states=states,
                    current=None,
                )
                append_jsonl_atomic(
                    journal_path,
                    {
                        "event": "run_invalid_final",
                        "time": utc_now(),
                        "run_id": run_id,
                        "error": str(exc),
                    },
                )
                raise
            verification_path = write_verification(item, validated)
            complete, reason = verify_completed(item)
            if not complete:
                states[run_id] = "invalid_final"
                write_status(
                    control_dir,
                    item,
                    state="invalid_final",
                    detail=reason,
                )
                raise RunnerError(f"Post-run verification failed for {run_id}: {reason}")
            states[run_id] = "verified_completed"
            write_status(
                control_dir,
                item,
                state="verified_completed",
                detail="Subprocess completed and all contracted artifact hashes verified.",
                extra={
                    "verification_receipt": _repo_relative(repo_root, verification_path),
                    "verification_sha256": sha256_file(verification_path),
                },
            )
            write_progress(
                progress_path,
                profile=options.profile,
                total=len(prepared),
                states=states,
                current=None,
            )
            append_jsonl_atomic(
                journal_path,
                {"event": "run_completed", "time": utc_now(), "run_id": run_id},
            )

        append_jsonl_atomic(
            journal_path,
            {
                "event": "runner_finished",
                "time": utc_now(),
                "profile": options.profile,
                "launched": launched,
            },
        )
    return {**plan, "states": states, "launched": launched}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one fail-closed v10 CUDA matrix profile.")
    parser.add_argument("--profile", required=True, choices=PROFILES)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--matrix", type=Path, default=None)
    parser.add_argument("--contract", type=Path, default=Path("configs/v10/CONTRACT.json"))
    parser.add_argument(
        "--model-receipt",
        type=Path,
        default=Path("runs/v10/model_cache/MODEL_PREFETCH_RECEIPT.json"),
    )
    parser.add_argument("--model-snapshot", type=Path, default=None)
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument(
        "--qualification-root",
        type=Path,
        default=Path("runs/v10/qualifications"),
    )
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--engine-module", default="latent_workspace_ft_v10.engine")
    parser.add_argument("--minimum-free-disk-gib", type=float, default=100.0)
    parser.add_argument("--minimum-free-vram-gib", type=float, default=28.0)
    parser.add_argument("--maximum-gpu-utilization-percent", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-runs", type=int, default=None)
    return parser


def options_from_args(args: argparse.Namespace) -> RunnerOptions:
    repo_root = args.repo_root.resolve()
    matrix = args.matrix or Path(f"configs/v10/profiles/{args.profile}/MATRIX.json")
    return RunnerOptions(
        repo_root=repo_root,
        profile=args.profile,
        matrix_path=matrix,
        contract_path=args.contract,
        model_receipt=args.model_receipt,
        model_snapshot=args.model_snapshot,
        cache_dir=args.cache_dir,
        qualification_root=args.qualification_root,
        python=args.python,
        engine_module=args.engine_module,
        minimum_free_disk_gib=args.minimum_free_disk_gib,
        minimum_free_vram_gib=args.minimum_free_vram_gib,
        maximum_gpu_utilization_percent=args.maximum_gpu_utilization_percent,
        dry_run=args.dry_run,
        max_runs=args.max_runs,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_matrix(options_from_args(args))
    except RunnerError as exc:
        print(f"matrix blocked: {exc}", file=sys.stderr)
        return 2
    if not args.dry_run:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
