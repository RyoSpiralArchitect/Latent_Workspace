#!/usr/bin/env python3
"""Fail-closed checkpoint/save/reload/resume equivalence pilot for v10.

The ordinary matrix runner intentionally launches only fresh runs.  This
separate harness reuses one already-verified matrix run as baseline A, creates
an uninterrupted checkpointing control B, resumes a new run C from B's
mid-schedule checkpoint, and compares the durable states exactly.

Dry-run is the default.  Training is possible only with ``--execute`` and only
into a wholly new output root.  Existing artifacts are never overwritten or
deleted.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import platform
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import prefetch_v10_model as model_cache
import run_v10_matrix as matrix_runner

RECEIPT_FORMAT = "latent-workspace-v10-resume-equivalence-v1"
BASELINE_VERIFICATION_FORMAT = "latent-workspace-v10-run-verification-v1"
PRUNE_RESUME_VERIFICATION_FORMAT = "latent-workspace-v10-resume-verification-v1"
PRUNE_RESUME_VERIFICATION_NAME = "RESUME_VERIFICATION.json"
PUBLISHED_EQUIVALENCE_NAME = "resume_equivalence_result.json"
PUBLISHED_CONTROL_ENVIRONMENT_NAME = "resume_control_environment.json"
PUBLISHED_RESUMED_ENVIRONMENT_NAME = "resume_resumed_environment.json"
DEFAULT_BASELINE = Path("runs/v10/smoke/F0_query_only/seed_42")
DEFAULT_OUTPUT = Path("runs/v10/resume_equivalence/F0_query_only/seed_42_step4")

# These are the complete runtime-only fields currently emitted by the engine.
# Deliberately do not use a broad prefix/suffix filter: a newly introduced
# metric remains part of the exact comparison until it is reviewed explicitly.
METRIC_RUNTIME_EXCLUSIONS = frozenset(
    {
        "time",
        "tokens_per_second",
        "cuda_allocated_gb",
        "cuda_reserved_gb",
        "cuda_peak_allocated_gb",
        "cuda_max_allocated_gb",
        "cuda_max_reserved_gb",
    }
)
TRAINER_REQUIRED_KEYS = frozenset(
    {
        "optimizer",
        "scheduler",
        "scaler",
        "sampler_state",
        "rng_by_rank",
        "data_fingerprint",
        "run_state",
        "global_step",
        "world_size",
        "resume_signature",
        "structural_resume_signature",
    }
)
CONFIG_DIFFERENCE_ALLOWLIST = frozenset(
    {
        "train.output_dir",
        "train.resume_from",
        "train.save_every",
        "train.save_every_minutes",
        "train.keep_last_checkpoints",
    }
)


class EquivalenceError(RuntimeError):
    """A required provenance, execution, or equality gate failed."""


@dataclass(frozen=True)
class Baseline:
    run_dir: Path
    launched_config_path: Path
    launched_config: Mapping[str, Any]
    verification_path: Path
    verification: Mapping[str, Any]
    final_dir: Path


@dataclass(frozen=True)
class PilotPlan:
    repo_root: Path
    baseline: Baseline
    output_root: Path
    control_output: Path
    resumed_output: Path
    control_config_path: Path
    resumed_config_path: Path
    split_step: int
    total_steps: int
    python: str
    engine_module: str
    max_working_set_bytes: int


@dataclass(frozen=True)
class LaunchResult:
    command: tuple[str, ...]
    returncode: int
    elapsed_seconds: float
    stdout_path: Path
    stderr_path: Path


LaunchFunction = Callable[
    [Sequence[str], Path, Path, Path, Mapping[str, str]],
    LaunchResult,
]


def _require_mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EquivalenceError(f"{label} must be a JSON object.")
    return value


def _require_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise EquivalenceError(f"{label} must be a non-empty string.")
    return value


def _inside(root: Path, value: Path, *, label: str) -> Path:
    root = root.resolve()
    value = value.resolve()
    try:
        value.relative_to(root)
    except ValueError as exc:
        raise EquivalenceError(f"{label} escapes repository root: {value}") from exc
    return value


def _repo_path(root: Path, value: str | Path, *, label: str) -> Path:
    raw = Path(value)
    candidate = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    return _inside(root, candidate, label=label)


def _relative(root: Path, value: Path) -> str:
    return _inside(root, value, label="artifact path").relative_to(root.resolve()).as_posix()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EquivalenceError(f"Could not read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EquivalenceError(f"Expected a JSON object: {path}")
    return value


def _assert_sha256(path: Path, expected: Any, *, label: str) -> str:
    expected_text = _require_string(expected, label=f"{label} expected SHA256")
    if not path.is_file():
        raise EquivalenceError(f"Missing {label}: {path}")
    observed = matrix_runner.sha256_file(path)
    if observed != expected_text:
        raise EquivalenceError(
            f"{label} hash mismatch for {path}: expected {expected_text}, observed {observed}."
        )
    return observed


def validate_current_hash_bindings(
    repo_root: Path,
    run_dir: Path,
    verification: Mapping[str, Any],
) -> dict[str, Any]:
    """Revalidate every current file binding required by the baseline run."""

    provenance = _require_mapping(verification.get("provenance"), label="provenance")
    hashes = _require_mapping(provenance.get("hashes"), label="provenance.hashes")
    observed: dict[str, Any] = {}

    launched = run_dir / "LAUNCHED_CONFIG.json"
    observed["materialized_config_sha256"] = _assert_sha256(
        launched,
        hashes.get("materialized_config_sha256"),
        label="baseline LAUNCHED_CONFIG",
    )

    condition_relative = _require_string(
        provenance.get("condition_config"), label="provenance.condition_config"
    )
    observed["condition_config_sha256"] = _assert_sha256(
        _repo_path(repo_root, condition_relative, label="condition config"),
        hashes.get("condition_config_sha256"),
        label="current condition config",
    )
    observed["runner_sha256"] = _assert_sha256(
        repo_root / "scripts" / "run_v10_matrix.py",
        hashes.get("runner_sha256"),
        label="current matrix runner",
    )

    expected_sources = _require_mapping(
        hashes.get("source_files_sha256"), label="source_files_sha256"
    )
    current_sources, current_tree = matrix_runner.source_hashes(repo_root)
    if dict(expected_sources) != current_sources:
        raise EquivalenceError("Current engine source files differ from baseline provenance.")
    expected_tree = _require_string(hashes.get("source_tree_sha256"), label="source_tree_sha256")
    if current_tree != expected_tree:
        raise EquivalenceError(
            f"Current source tree hash mismatch: expected {expected_tree}, observed {current_tree}."
        )
    observed["source_files_sha256"] = current_sources
    observed["source_tree_sha256"] = current_tree

    for map_name in ("run_data_sha256", "contract_data_sha256"):
        expected_map = _require_mapping(hashes.get(map_name), label=map_name)
        current_map: dict[str, str] = {}
        for relative, expected in sorted(expected_map.items()):
            relative_text = _require_string(relative, label=f"{map_name} path")
            current_map[relative_text] = _assert_sha256(
                _repo_path(repo_root, relative_text, label=f"{map_name} file"),
                expected,
                label=f"current {map_name} file",
            )
        observed[map_name] = current_map

    profile = _require_string(provenance.get("profile"), label="provenance.profile")
    static_bindings = (
        (
            "contract_sha256",
            repo_root / "configs" / "v10" / "CONTRACT.json",
            "current contract",
        ),
        (
            "matrix_sha256",
            repo_root / "configs" / "v10" / "profiles" / profile / "MATRIX.json",
            "current profile matrix",
        ),
        (
            "model_receipt_sha256",
            repo_root / "runs" / "v10" / "model_cache" / "MODEL_PREFETCH_RECEIPT.json",
            "current model prefetch receipt",
        ),
    )
    for key, path, label in static_bindings:
        observed[key] = _assert_sha256(path, hashes.get(key), label=label)

    return observed


def _prepared_baseline(
    repo_root: Path,
    run_dir: Path,
    config: Mapping[str, Any],
    verification: Mapping[str, Any],
) -> matrix_runner.PreparedRun:
    provenance = _require_mapping(verification.get("provenance"), label="provenance")
    condition_relative = _require_string(
        provenance.get("condition_config"), label="provenance.condition_config"
    )
    output_relative = _require_string(provenance.get("output_dir"), label="provenance.output_dir")
    expected_output = _repo_path(repo_root, output_relative, label="baseline output")
    if expected_output != run_dir.resolve():
        raise EquivalenceError(
            f"Baseline path disagrees with receipt: {run_dir} != {expected_output}."
        )
    run_id = _require_string(provenance.get("run_id"), label="provenance.run_id")
    condition = _require_string(provenance.get("condition"), label="provenance.condition")
    seed = provenance.get("seed")
    max_steps = provenance.get("max_steps")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise EquivalenceError("Baseline seed must be an integer.")
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < 1:
        raise EquivalenceError("Baseline max_steps must be a positive integer.")
    spec = matrix_runner.RunSpec(
        run_id=run_id,
        condition=condition,
        condition_config=_repo_path(repo_root, condition_relative, label="condition config"),
        condition_config_relative=condition_relative,
        seed=seed,
        max_steps=max_steps,
        output_dir=run_dir.resolve(),
        output_dir_relative=output_relative,
        raw={},
    )
    launched_bytes = (run_dir / "LAUNCHED_CONFIG.json").read_bytes()
    return matrix_runner.PreparedRun(
        spec=spec,
        materialized=config,
        materialized_bytes=launched_bytes,
        provenance=provenance,
    )


def validate_baseline(repo_root: Path, run_dir: Path) -> Baseline:
    repo_root = repo_root.resolve()
    run_dir = _inside(repo_root, run_dir, label="baseline run")
    verification_path = run_dir / "RUN_VERIFICATION.json"
    launched_path = run_dir / "LAUNCHED_CONFIG.json"
    verification = _read_json(verification_path)
    if (
        verification.get("format") != BASELINE_VERIFICATION_FORMAT
        or verification.get("verified") is not True
    ):
        raise EquivalenceError("Baseline RUN_VERIFICATION is unsupported or not verified.")
    launched = _read_json(launched_path)
    matrix_runner.validate_materialized_full_update(launched, label="baseline config")
    validate_current_hash_bindings(repo_root, run_dir, verification)
    prepared = _prepared_baseline(repo_root, run_dir, launched, verification)
    complete, reason = matrix_runner.verify_completed(prepared)
    if not complete:
        raise EquivalenceError(f"Baseline full verification failed: {reason}")
    return Baseline(
        run_dir=run_dir,
        launched_config_path=launched_path,
        launched_config=launched,
        verification_path=verification_path,
        verification=verification,
        final_dir=run_dir / "final",
    )


def _resolve_config_file(value: str, source_config: Path, repo_root: Path) -> str:
    raw = Path(value)
    resolved = raw.resolve() if raw.is_absolute() else (source_config.parent / raw).resolve()
    resolved = _inside(repo_root, resolved, label="configured data file")
    if not resolved.is_file():
        raise EquivalenceError(f"Configured data file does not exist: {resolved}")
    return str(resolved)


def _absolutize_data_paths(config: dict[str, Any], source_config: Path, repo_root: Path) -> None:
    data = _require_mapping(config.get("data"), label="config.data")
    for key in ("train_files", "eval_files"):
        values = data.get(key)
        if not isinstance(values, list):
            raise EquivalenceError(f"config.data.{key} must be a list.")
        data[key] = [
            _resolve_config_file(
                _require_string(value, label=f"config.data.{key} entry"),
                source_config,
                repo_root,
            )
            for value in values
        ]
    assays = config.get("assays")
    if isinstance(assays, Mapping):
        recruitment = assays.get("recruitment")
        if isinstance(recruitment, Mapping):
            for key in ("train_files", "eval_files"):
                values = recruitment.get(key)
                if isinstance(values, list) and values:
                    recruitment[key] = [
                        _resolve_config_file(
                            _require_string(value, label=f"config.assays.recruitment.{key} entry"),
                            source_config,
                            repo_root,
                        )
                        for value in values
                    ]


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {prefix: value}
    result: dict[str, Any] = {}
    for key in sorted(value):
        path = f"{prefix}.{key}" if prefix else str(key)
        child = value[key]
        if isinstance(child, Mapping):
            result.update(_flatten(child, path))
        else:
            result[path] = child
    return result


def _assert_only_allowed_config_differences(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> None:
    left_flat = _flatten(left)
    right_flat = _flatten(right)
    paths = set(left_flat) | set(right_flat)
    differences = sorted(path for path in paths if left_flat.get(path) != right_flat.get(path))
    unexpected = [path for path in differences if path not in CONFIG_DIFFERENCE_ALLOWLIST]
    if unexpected:
        raise EquivalenceError(
            "Control/resume configs differ outside the resume-signature allowlist: "
            + ", ".join(unexpected[:16])
        )


def derive_pilot_configs(
    baseline: Baseline,
    repo_root: Path,
    output_root: Path,
    *,
    split_step: int,
    total_steps: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Derive B/C configs without ever shortening the scheduler horizon."""

    if split_step < 1 or total_steps < 2 or split_step >= total_steps:
        raise EquivalenceError("Require 0 < split_step < total_steps.")
    base = copy.deepcopy(dict(baseline.launched_config))
    train = _require_mapping(base.get("train"), label="baseline config.train")
    baseline_steps = train.get("max_steps")
    if (
        isinstance(baseline_steps, bool)
        or not isinstance(baseline_steps, int)
        or baseline_steps != total_steps
    ):
        raise EquivalenceError(
            "Scheduler horizon mismatch: total_steps must equal the verified baseline "
            f"max_steps ({baseline_steps!r}), not {total_steps}."
        )
    required_true = (
        "strict_resume",
        "strict_source_resume",
        "strict_torch_resume",
        "save_optimizer",
    )
    for key in required_true:
        if train.get(key) is not True:
            raise EquivalenceError(f"Baseline train.{key}=true is required.")
    if train.get("allow_schedule_extension") is not False:
        raise EquivalenceError("Baseline allow_schedule_extension=false is required.")
    if train.get("device") != "cuda":
        raise EquivalenceError("Resume pilot is contracted for train.device='cuda'.")
    model = _require_mapping(base.get("model"), label="baseline config.model")
    if model.get("local_files_only") is not True or model.get("trust_remote_code") is not False:
        raise EquivalenceError("Baseline must be local-files-only with trust_remote_code=false.")

    _absolutize_data_paths(base, baseline.launched_config_path, repo_root)
    control = copy.deepcopy(base)
    control_train = _require_mapping(control["train"], label="control train")
    control_train["max_steps"] = total_steps
    control_train["output_dir"] = str((output_root / "control_uninterrupted").resolve())
    control_train["resume_from"] = "none"
    control_train["save_every"] = split_step
    control_train["save_every_minutes"] = 0.0
    # Retain checkpoint-split even if later scheduled checkpoints are created.
    scheduled_saves = max(1, total_steps // split_step)
    control_train["keep_last_checkpoints"] = max(
        int(control_train.get("keep_last_checkpoints", 1)), scheduled_saves
    )

    resumed = copy.deepcopy(control)
    resumed_train = _require_mapping(resumed["train"], label="resumed train")
    resumed_train["output_dir"] = str((output_root / "resumed_from_split").resolve())
    resumed_train["resume_from"] = str(
        (output_root / "control_uninterrupted" / f"checkpoint-{split_step}").resolve()
    )
    resumed_train["save_every"] = 0
    resumed_train["save_every_minutes"] = 0.0
    resumed_train["keep_last_checkpoints"] = 1

    _assert_only_allowed_config_differences(control, resumed)
    if control_train["max_steps"] != resumed_train["max_steps"]:
        raise EquivalenceError("Control/resume scheduler horizons differ.")
    return control, resumed


def require_new_output_root(repo_root: Path, output_root: Path) -> Path:
    output_root = _inside(repo_root, output_root, label="resume pilot output")
    if output_root == repo_root.resolve():
        raise EquivalenceError("Repository root cannot be used as pilot output.")
    if output_root.exists():
        raise EquivalenceError(f"Pilot output already exists; refusing overwrite: {output_root}")
    return output_root


def build_plan(args: argparse.Namespace) -> PilotPlan:
    repo_root = Path(args.repo_root).expanduser().resolve()
    if not repo_root.is_dir():
        raise EquivalenceError(f"Repository root does not exist: {repo_root}")
    baseline_path = _repo_path(repo_root, args.baseline_run, label="baseline run")
    baseline = validate_baseline(repo_root, baseline_path)
    total_steps = (
        int(args.total_steps)
        if args.total_steps is not None
        else int(
            _require_mapping(baseline.launched_config.get("train"), label="baseline config.train")[
                "max_steps"
            ]
        )
    )
    output_root = _repo_path(repo_root, args.output_root, label="resume pilot output")
    output_root = require_new_output_root(repo_root, output_root)
    max_working_set_bytes = int(args.max_working_set_mib) * 1024 * 1024
    if max_working_set_bytes < 1:
        raise EquivalenceError("--max-working-set-mib must be positive.")
    plan = PilotPlan(
        repo_root=repo_root,
        baseline=baseline,
        output_root=output_root,
        control_output=output_root / "control_uninterrupted",
        resumed_output=output_root / "resumed_from_split",
        control_config_path=output_root / "CONTROL_CONFIG.json",
        resumed_config_path=output_root / "RESUME_CONFIG.json",
        split_step=int(args.split_step),
        total_steps=total_steps,
        python=str(args.python),
        engine_module=str(args.engine_module),
        max_working_set_bytes=max_working_set_bytes,
    )
    derive_pilot_configs(
        baseline,
        repo_root,
        output_root,
        split_step=plan.split_step,
        total_steps=plan.total_steps,
    )
    return plan


def _default_launch(
    command: Sequence[str],
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    environment: Mapping[str, str],
) -> LaunchResult:
    started = time.perf_counter()
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            check=False,
        )
    return LaunchResult(
        command=tuple(command),
        returncode=int(completed.returncode),
        elapsed_seconds=time.perf_counter() - started,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )


def _offline_environment(repo_root: Path) -> dict[str, str]:
    environment = dict(os.environ)
    for forbidden in (
        matrix_runner.CUDA_ALLOCATOR_LEGACY_ENV,
        matrix_runner.CUDA_ALLOCATOR_HIP_LEGACY_ENV,
        matrix_runner.CUDA_ALLOCATOR_DISABLE_ENV,
    ):
        environment.pop(forbidden, None)
    environment.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "HF_HUB_CACHE": str((repo_root / "runs/v10/model_cache/hf").resolve()),
            "TOKENIZERS_PARALLELISM": "false",
            matrix_runner.CUDA_ALLOCATOR_ENV: matrix_runner.CUDA_ALLOCATOR_CONF,
        }
    )
    source = str(repo_root / "src")
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = source if not existing else source + os.pathsep + existing
    return environment


def _verify_pinned_model_cache(plan: PilotPlan) -> dict[str, Any]:
    """Rehash the exact offline snapshot and bind the child cache to it."""

    model = _require_mapping(
        plan.baseline.launched_config.get("model"), label="baseline config.model"
    )
    model_id = _require_string(model.get("name_or_path"), label="model.name_or_path")
    revision = _require_string(model.get("revision"), label="model.revision")
    receipt_path = plan.repo_root / "runs/v10/model_cache/MODEL_PREFETCH_RECEIPT.json"
    cache_dir = plan.repo_root / "runs/v10/model_cache/hf"
    try:
        verified = model_cache.verify_prefetch_receipt(
            receipt_path,
            expected_model=model_id,
            expected_revision=revision,
            cache_dir=cache_dir,
        )
    except model_cache.PrefetchError as exc:
        raise EquivalenceError(f"Pinned model cache verification failed: {exc}") from exc
    snapshot_path = _inside(
        cache_dir,
        Path(verified["snapshot_path"]),
        label="verified model snapshot",
    )
    receipt = _require_mapping(verified.get("receipt"), label="model cache receipt")
    snapshot = _require_mapping(receipt.get("snapshot"), label="model cache snapshot")
    files = snapshot.get("files")
    if not isinstance(files, list) or not files:
        raise EquivalenceError("Model cache receipt has no snapshot file inventory.")
    inventory_sha256 = matrix_runner.sha256_bytes(
        matrix_runner.canonical_json_bytes(files)
    )
    provenance = _require_mapping(
        plan.baseline.verification.get("provenance"), label="baseline provenance"
    )
    hashes = _require_mapping(provenance.get("hashes"), label="baseline provenance hashes")
    if inventory_sha256 != hashes.get("model_snapshot_inventory_sha256"):
        raise EquivalenceError(
            "Verified model snapshot inventory disagrees with baseline provenance."
        )
    return {
        "model_id": model_id,
        "revision": revision,
        "hf_hub_cache": _relative(plan.repo_root, cache_dir),
        "snapshot": _relative(plan.repo_root, snapshot_path),
        "snapshot_file_count": len(files),
        "snapshot_total_bytes": sum(int(item["bytes"]) for item in files),
        "snapshot_inventory_sha256": inventory_sha256,
        "receipt_sha256": matrix_runner.sha256_file(receipt_path),
    }


def _write_configs(plan: PilotPlan, control: Mapping[str, Any], resumed: Mapping[str, Any]) -> None:
    matrix_runner.atomic_write_json(plan.control_config_path, control)
    matrix_runner.atomic_write_json(plan.resumed_config_path, resumed)


def _require_complete_bundle(
    path: Path,
    *,
    expected_step: int,
    expected_source_sha256: str,
    require_optimizer: bool = True,
) -> dict[str, Any]:
    required = (
        path / "COMPLETED",
        path / "manifest.json",
        path / "experiment_config.json",
        path / "workspace_state.pt",
        path / "trainer_state.pt",
    )
    for item in required:
        if not item.is_file() or item.stat().st_size <= 0:
            raise EquivalenceError(f"Incomplete bundle, missing/empty {item}")
    if (path / "COMPLETED").read_text(encoding="utf-8").strip() != "ok":
        raise EquivalenceError(f"Invalid COMPLETED marker: {path}")
    manifest = _read_json(path / "manifest.json")
    if (
        manifest.get("complete") is not True
        or int(manifest.get("global_step", -1)) != expected_step
    ):
        raise EquivalenceError(f"Bundle step/completeness mismatch: {path}")
    if require_optimizer and manifest.get("optimizer_saved") is not True:
        raise EquivalenceError(f"Bundle lacks required optimizer state: {path}")
    if manifest.get("source_sha256") != expected_source_sha256:
        raise EquivalenceError(f"Bundle source hash mismatch: {path}")
    if not (path / "base_model").is_dir():
        raise EquivalenceError(f"Bundle has no saved base_model: {path}")
    matrix_runner.inspect_semantic_safetensors(path / "base_model")
    return manifest


def _tensor_bytes(tensor: Any) -> Any:
    import torch

    contiguous = tensor.detach().cpu().contiguous()
    if contiguous.dim() == 0:
        contiguous = contiguous.reshape(1)
    return contiguous.view(torch.uint8).reshape(-1)


def recursive_mismatches(
    left: Any,
    right: Any,
    *,
    path: str = "$",
    excluded_paths: frozenset[str] = frozenset(),
    limit: int = 32,
) -> list[dict[str, str]]:
    """Return bounded exact/bitwise mismatches for nested torch state."""

    if path in excluded_paths:
        return []
    mismatches: list[dict[str, str]] = []

    def add(reason: str) -> None:
        if len(mismatches) < limit:
            mismatches.append({"path": path, "reason": reason})

    try:
        import torch
    except ImportError as exc:  # pragma: no cover - project dependency
        raise EquivalenceError("Recursive state comparison requires torch.") from exc

    if isinstance(left, torch.Tensor) or isinstance(right, torch.Tensor):
        if not isinstance(left, torch.Tensor) or not isinstance(right, torch.Tensor):
            add(f"type mismatch: {type(left).__name__} != {type(right).__name__}")
            return mismatches
        if left.shape != right.shape:
            add(f"shape mismatch: {tuple(left.shape)} != {tuple(right.shape)}")
        elif left.dtype != right.dtype:
            add(f"dtype mismatch: {left.dtype} != {right.dtype}")
        elif left.layout != right.layout:
            add(f"layout mismatch: {left.layout} != {right.layout}")
        elif not torch.equal(_tensor_bytes(left), _tensor_bytes(right)):
            add("tensor bytes differ")
        return mismatches

    if isinstance(left, Mapping) or isinstance(right, Mapping):
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            add(f"type mismatch: {type(left).__name__} != {type(right).__name__}")
            return mismatches
        left_keys = set(left)
        right_keys = set(right)
        if left_keys != right_keys:
            add(
                "mapping keys differ: "
                f"missing_right={sorted(map(str, left_keys - right_keys))[:8]}, "
                f"missing_left={sorted(map(str, right_keys - left_keys))[:8]}"
            )
            if len(mismatches) >= limit:
                return mismatches
        for key in sorted(
            left_keys & right_keys, key=lambda value: (type(value).__name__, repr(value))
        ):
            child_path = f"{path}.{key}"
            mismatches.extend(
                recursive_mismatches(
                    left[key],
                    right[key],
                    path=child_path,
                    excluded_paths=excluded_paths,
                    limit=max(0, limit - len(mismatches)),
                )
            )
            if len(mismatches) >= limit:
                break
        return mismatches

    sequence_types = (list, tuple)
    if isinstance(left, sequence_types) or isinstance(right, sequence_types):
        if type(left) is not type(right):
            add(f"sequence type mismatch: {type(left).__name__} != {type(right).__name__}")
            return mismatches
        if len(left) != len(right):
            add(f"sequence length mismatch: {len(left)} != {len(right)}")
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=False)):
            mismatches.extend(
                recursive_mismatches(
                    left_item,
                    right_item,
                    path=f"{path}[{index}]",
                    excluded_paths=excluded_paths,
                    limit=max(0, limit - len(mismatches)),
                )
            )
            if len(mismatches) >= limit:
                break
        return mismatches

    if type(left) is not type(right):
        add(f"type mismatch: {type(left).__name__} != {type(right).__name__}")
    elif left != right:
        add(f"value differs: {left!r} != {right!r}")
    return mismatches


def _load_torch_state(path: Path, *, weights_only: bool) -> Any:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - project dependency
        raise EquivalenceError("State comparison requires torch.") from exc
    try:
        return torch.load(path, map_location="cpu", weights_only=weights_only)
    except TypeError:  # pragma: no cover - compatibility with older torch
        return torch.load(path, map_location="cpu")


def compare_torch_state_files(
    left: Path,
    right: Path,
    *,
    label: str,
    excluded_paths: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    weights_only = left.name == "workspace_state.pt" and right.name == "workspace_state.pt"
    left_state = _load_torch_state(left, weights_only=weights_only)
    right_state = _load_torch_state(right, weights_only=weights_only)
    mismatches = recursive_mismatches(
        left_state,
        right_state,
        excluded_paths=excluded_paths,
    )
    if mismatches:
        raise EquivalenceError(f"{label} mismatch: {mismatches[:4]}")
    return {
        "exact": True,
        "left_sha256": matrix_runner.sha256_file(left),
        "right_sha256": matrix_runner.sha256_file(right),
        "excluded_paths": sorted(excluded_paths),
    }


def _validate_trainer_state(state: Any, *, expected_step: int, label: str) -> Mapping[str, Any]:
    trainer = _require_mapping(state, label=label)
    missing = sorted(TRAINER_REQUIRED_KEYS - set(trainer))
    if missing:
        raise EquivalenceError(f"{label} lacks required fields: {missing}")
    if int(trainer.get("global_step", -1)) != expected_step:
        raise EquivalenceError(f"{label} global_step mismatch.")
    run_state = _require_mapping(trainer.get("run_state"), label=f"{label}.run_state")
    if int(run_state.get("global_step", -1)) != expected_step:
        raise EquivalenceError(f"{label}.run_state global_step mismatch.")
    _require_string(run_state.get("run_id"), label=f"{label}.run_state.run_id")
    return trainer


def compare_trainer_states(
    left: Path,
    right: Path,
    *,
    expected_step: int,
    independent_runs: bool,
    label: str,
) -> dict[str, Any]:
    left_state = _validate_trainer_state(
        _load_torch_state(left, weights_only=False),
        expected_step=expected_step,
        label=f"{label}.left",
    )
    right_state = _validate_trainer_state(
        _load_torch_state(right, weights_only=False),
        expected_step=expected_step,
        label=f"{label}.right",
    )
    excluded = frozenset({"$.run_state.run_id"}) if independent_runs else frozenset()
    mismatches = recursive_mismatches(
        left_state,
        right_state,
        excluded_paths=excluded,
    )
    if mismatches:
        raise EquivalenceError(f"{label} mismatch: {mismatches[:4]}")
    left_id = str(_require_mapping(left_state["run_state"], label="left run_state")["run_id"])
    right_id = str(_require_mapping(right_state["run_state"], label="right run_state")["run_id"])
    if not independent_runs and left_id != right_id:
        raise EquivalenceError(f"{label} did not preserve run_id across resume.")
    return {
        "exact": True,
        "independent_runs": independent_runs,
        "excluded_paths": sorted(excluded),
        "run_id_preserved": None if independent_runs else True,
        "left_sha256": matrix_runner.sha256_file(left),
        "right_sha256": matrix_runner.sha256_file(right),
    }


def compare_base_models(
    left: Path,
    right: Path,
    *,
    max_working_set_bytes: int,
    label: str,
) -> dict[str, Any]:
    raw = matrix_runner.compare_full_update_safetensors(
        left,
        right,
        max_working_set_bytes=max_working_set_bytes,
    )
    mismatched = [item for item in raw["tensors"] if item["changed"]]
    if raw["changed_tensor_count"] != 0 or raw["total_changed_elements"] != 0:
        names = [item["name"] for item in mismatched[:8]]
        raise EquivalenceError(
            f"{label} base tensors are not bitwise identical: "
            f"changed_tensors={raw['changed_tensor_count']}, "
            f"changed_elements={raw['total_changed_elements']}, names={names}."
        )
    return {
        "bitwise_exact": True,
        "tensor_count": raw["tensor_count"],
        "total_numel": raw["initial_semantic"]["total_numel"],
        "tensor_schema_sha256": raw["initial_semantic"]["tensor_schema_sha256"],
        "changed_tensor_count": 0,
        "changed_element_count": 0,
        "performance": raw["performance"],
    }


def _read_metrics(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise EquivalenceError(f"{path}:{line_number} is not an object.")
                records.append(value)
    except (OSError, json.JSONDecodeError) as exc:
        raise EquivalenceError(f"Could not read metrics {path}: {exc}") from exc
    return records


def normalize_metric_record(record: Mapping[str, Any], *, ignore_run_id: bool) -> dict[str, Any]:
    excluded = set(METRIC_RUNTIME_EXCLUSIONS)
    if ignore_run_id:
        excluded.add("run_id")
    return {key: value for key, value in record.items() if key not in excluded}


def _indexed_metrics(
    records: Sequence[Mapping[str, Any]],
    *,
    splits: frozenset[str],
    label: str,
) -> dict[tuple[str, int], Mapping[str, Any]]:
    result: dict[tuple[str, int], Mapping[str, Any]] = {}
    for record in records:
        split = record.get("split")
        if split not in splits:
            continue
        step = record.get("step")
        if isinstance(step, bool) or not isinstance(step, int):
            raise EquivalenceError(f"{label} has a non-integer step for split {split!r}.")
        key = (str(split), step)
        if key in result:
            raise EquivalenceError(f"{label} has duplicate metric record {key}.")
        result[key] = record
    return result


def compare_metric_records(
    left_records: Sequence[Mapping[str, Any]],
    right_records: Sequence[Mapping[str, Any]],
    *,
    keys: Sequence[tuple[str, int]],
    ignore_run_id: bool,
    label: str,
) -> dict[str, Any]:
    left = _indexed_metrics(
        left_records,
        splits=frozenset(split for split, _step in keys),
        label=f"{label}.left",
    )
    right = _indexed_metrics(
        right_records,
        splits=frozenset(split for split, _step in keys),
        label=f"{label}.right",
    )
    expected = set(keys)
    if not expected <= set(left) or not expected <= set(right):
        raise EquivalenceError(
            f"{label} lacks required records: "
            f"left_missing={sorted(expected - set(left))}, "
            f"right_missing={sorted(expected - set(right))}."
        )
    for key in keys:
        left_normalized = normalize_metric_record(left[key], ignore_run_id=ignore_run_id)
        right_normalized = normalize_metric_record(right[key], ignore_run_id=ignore_run_id)
        if left_normalized != right_normalized:
            mismatch_keys = sorted(
                item
                for item in set(left_normalized) | set(right_normalized)
                if left_normalized.get(item) != right_normalized.get(item)
            )
            raise EquivalenceError(f"{label} stable metrics differ at {key}: {mismatch_keys[:8]}")
    return {
        "exact": True,
        "record_count": len(keys),
        "ignored_fields": sorted(
            METRIC_RUNTIME_EXCLUSIONS | ({"run_id"} if ignore_run_id else set())
        ),
    }


def _require_resume_event(
    records: Sequence[Mapping[str, Any]], *, split_step: int, expected_run_id: str
) -> dict[str, Any]:
    events = [record for record in records if record.get("event") == "resume"]
    if len(events) != 1:
        raise EquivalenceError(f"Expected exactly one resume event, observed {len(events)}.")
    event = events[0]
    if event.get("step") != split_step or event.get("run_id") != expected_run_id:
        raise EquivalenceError("Resume event step/run_id does not bind to checkpoint continuity.")
    if not isinstance(event.get("checkpoint"), str) or not event.get("checkpoint"):
        raise EquivalenceError("Resume event has no checkpoint path.")
    return {"step": split_step, "run_id_preserved": True}


def compare_all_artifacts(plan: PilotPlan) -> dict[str, Any]:
    started = time.perf_counter()
    baseline_final = plan.baseline.final_dir
    control_final = plan.control_output / "final"
    resumed_final = plan.resumed_output / "final"

    base_ab = compare_base_models(
        baseline_final / "base_model",
        control_final / "base_model",
        max_working_set_bytes=plan.max_working_set_bytes,
        label="A/B save non-perturbation",
    )
    base_bc = compare_base_models(
        control_final / "base_model",
        resumed_final / "base_model",
        max_working_set_bytes=plan.max_working_set_bytes,
        label="B/C resume",
    )
    workspace_ab = compare_torch_state_files(
        baseline_final / "workspace_state.pt",
        control_final / "workspace_state.pt",
        label="A/B workspace state",
    )
    workspace_bc = compare_torch_state_files(
        control_final / "workspace_state.pt",
        resumed_final / "workspace_state.pt",
        label="B/C workspace state",
    )
    trainer_ab = compare_trainer_states(
        baseline_final / "trainer_state.pt",
        control_final / "trainer_state.pt",
        expected_step=plan.total_steps,
        independent_runs=True,
        label="A/B trainer state",
    )
    trainer_bc = compare_trainer_states(
        control_final / "trainer_state.pt",
        resumed_final / "trainer_state.pt",
        expected_step=plan.total_steps,
        independent_runs=False,
        label="B/C trainer state",
    )

    baseline_metrics = _read_metrics(plan.baseline.run_dir / "metrics.jsonl")
    control_metrics = _read_metrics(plan.control_output / "metrics.jsonl")
    resumed_metrics = _read_metrics(plan.resumed_output / "metrics.jsonl")
    train_ab_keys = [("train", step) for step in range(1, plan.total_steps + 1)]
    train_bc_keys = [("train", step) for step in range(plan.split_step + 1, plan.total_steps + 1)]
    final_keys = [("eval-final", plan.total_steps), ("eval-final-amputated", plan.total_steps)]
    metrics = {
        "train_A_B": compare_metric_records(
            baseline_metrics,
            control_metrics,
            keys=train_ab_keys,
            ignore_run_id=True,
            label="A/B train metrics",
        ),
        "train_B_C": compare_metric_records(
            control_metrics,
            resumed_metrics,
            keys=train_bc_keys,
            ignore_run_id=False,
            label="B/C train metrics",
        ),
        "final_A_B": compare_metric_records(
            baseline_metrics,
            control_metrics,
            keys=final_keys,
            ignore_run_id=True,
            label="A/B final eval",
        ),
        "final_B_C": compare_metric_records(
            control_metrics,
            resumed_metrics,
            keys=final_keys,
            ignore_run_id=False,
            label="B/C final eval",
        ),
    }
    control_trainer = _validate_trainer_state(
        _load_torch_state(control_final / "trainer_state.pt", weights_only=False),
        expected_step=plan.total_steps,
        label="control trainer",
    )
    control_run_id = str(
        _require_mapping(control_trainer["run_state"], label="control run_state")["run_id"]
    )
    resume_event = _require_resume_event(
        resumed_metrics,
        split_step=plan.split_step,
        expected_run_id=control_run_id,
    )
    return {
        "passed": True,
        "base": {"save_non_perturbation_A_B": base_ab, "resume_B_C": base_bc},
        "workspace": {
            "save_non_perturbation_A_B": workspace_ab,
            "resume_B_C": workspace_bc,
        },
        "trainer": {
            "save_non_perturbation_A_B": trainer_ab,
            "resume_B_C": trainer_bc,
        },
        "metrics": metrics,
        "resume_event": resume_event,
        "elapsed_seconds": time.perf_counter() - started,
    }


def _inventory(path: Path) -> list[dict[str, Any]]:
    return matrix_runner.final_inventory(path)


def _runtime_environment(repo_root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "python": sys.version,
        "platform": platform.platform(),
        "hostname": socket.gethostname(),
        "engine_sha256": matrix_runner.sha256_file(
            repo_root / "src" / "latent_workspace_ft_v10" / "engine.py"
        ),
        "matrix_runner_sha256": matrix_runner.sha256_file(
            repo_root / "scripts" / "run_v10_matrix.py"
        ),
        "resume_harness_sha256": matrix_runner.sha256_file(Path(__file__).resolve()),
    }
    try:
        import torch

        result["torch"] = torch.__version__
        result["cuda_runtime"] = getattr(torch.version, "cuda", None)
        result["cuda_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            result["cuda_device"] = torch.cuda.get_device_name(0)
    except ImportError:
        result["torch"] = None
        result["cuda_available"] = False
    return result


def _child_allocator_environment_binding(
    plan: PilotPlan,
    *,
    output_dir: Path,
    config_path: Path,
    label: str,
) -> dict[str, Any]:
    config = _read_json(config_path)
    train = _require_mapping(config.get("train"), label=f"{label} config.train")
    configured = train.get("cuda_allocator_conf")
    try:
        return matrix_runner.validate_allocator_environment_file(
            output_dir / "environment.json",
            configured=configured,
            expected_source_sha256=matrix_runner.sha256_file(
                plan.repo_root / "src/latent_workspace_ft_v10/engine.py"
            ),
            label=label,
            receipt_path=_relative(
                plan.repo_root, output_dir / "environment.json"
            ),
        )
    except matrix_runner.RunnerError as exc:
        raise EquivalenceError(str(exc)) from exc


def _allocator_identity(binding: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    if binding.get("passed") is not True:
        raise EquivalenceError(f"{label} allocator binding is not passing.")
    return {
        key: binding.get(key)
        for key in (
            "configured",
            "observed_primary",
            "observed_legacy_alias",
            "observed_hip_legacy_alias",
            "observed_caching_allocator_disable",
            "active_backend",
            "parsed_settings",
            "snapshot_settings",
            "runtime_identity",
        )
    }


def _allocator_runtime_equivalence(
    plan: PilotPlan,
    child_bindings: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    baseline_binding = _require_mapping(
        plan.baseline.verification.get("allocator_environment"),
        label="baseline allocator_environment",
    )
    identities = {
        "baseline": _allocator_identity(
            baseline_binding, label="baseline allocator_environment"
        ),
        "control": _allocator_identity(
            child_bindings["control"], label="control allocator_environment"
        ),
        "resumed": _allocator_identity(
            child_bindings["resumed"], label="resumed allocator_environment"
        ),
    }
    all_equal = identities["baseline"] == identities["control"] == identities["resumed"]
    if not all_equal:
        raise EquivalenceError(
            "Baseline/control/resumed allocator and runtime identities differ."
        )
    return {
        "passed": True,
        "comparison": "selected_runtime_fields_exact",
        "all_equal": True,
        "identities": identities,
        "excluded_dynamic_fields": [
            "path",
            "sha256",
            "cuda_memory_allocated_bytes",
            "cuda_memory_reserved_bytes",
        ],
    }


def _execution_preflight(plan: PilotPlan) -> dict[str, Any]:
    verified_model_cache = _verify_pinned_model_cache(plan)
    try:
        import torch
    except ImportError as exc:
        raise EquivalenceError("Execution requires torch.") from exc
    if not torch.cuda.is_available():
        raise EquivalenceError("--execute requires an available CUDA device.")
    world_size = int(os.environ.get("WORLD_SIZE", "1"))
    if world_size != 1:
        raise EquivalenceError("This pilot is contracted for one process/GPU only.")
    baseline_bytes = sum(
        item.stat().st_size for item in plan.baseline.final_dir.rglob("*") if item.is_file()
    )
    # B writes checkpoint-split, a later scheduled checkpoint, and final; C
    # writes final. Use four baseline-sized bundles plus 15 percent headroom.
    estimated_bytes = int(baseline_bytes * 4 * 1.15)
    disk_anchor = plan.output_root.parent
    while not disk_anchor.exists() and disk_anchor != disk_anchor.parent:
        disk_anchor = disk_anchor.parent
    free_bytes = shutil.disk_usage(disk_anchor).free
    if free_bytes < estimated_bytes:
        raise EquivalenceError(
            f"Insufficient free disk for bounded pilot: {free_bytes} < {estimated_bytes} bytes."
        )
    return {
        "cuda_device": torch.cuda.get_device_name(0),
        "world_size": world_size,
        "baseline_bundle_bytes": baseline_bytes,
        "estimated_required_free_bytes": estimated_bytes,
        "observed_free_bytes": free_bytes,
        "model_cache": verified_model_cache,
    }


def _require_new_baseline_evidence_paths(plan: PilotPlan) -> None:
    for name in (
        PRUNE_RESUME_VERIFICATION_NAME,
        PUBLISHED_EQUIVALENCE_NAME,
        PUBLISHED_CONTROL_ENVIRONMENT_NAME,
        PUBLISHED_RESUMED_ENVIRONMENT_NAME,
    ):
        path = plan.baseline.run_dir / name
        if path.exists() or path.is_symlink():
            raise EquivalenceError(
                f"Refusing to overwrite existing baseline resume evidence: {path}"
            )


def _regular_single_link(path: Path, *, label: str) -> None:
    try:
        observed = path.lstat()
    except FileNotFoundError as exc:
        raise EquivalenceError(f"Missing {label}: {path}") from exc
    if (
        stat.S_ISLNK(observed.st_mode)
        or not stat.S_ISREG(observed.st_mode)
        or observed.st_nlink != 1
    ):
        raise EquivalenceError(
            f"{label} must be a regular, non-symlink, single-link file: {path}"
        )


def _atomic_create_bytes(path: Path, payload: bytes) -> None:
    """Create one byte-exact artifact without an overwrite race."""
    if path.exists() or path.is_symlink():
        raise EquivalenceError(f"Refusing to overwrite existing resume evidence: {path}")
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
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise EquivalenceError(
                f"Refusing to overwrite existing resume evidence: {path}"
            ) from exc
        temporary.unlink()
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_create_json(path: Path, value: Mapping[str, Any]) -> None:
    """Create one canonical JSON artifact without an overwrite race."""

    _atomic_create_bytes(path, matrix_runner.canonical_json_bytes(value))


def _require_exact_comparison_receipt(plan: PilotPlan, receipt: Mapping[str, Any]) -> None:
    """Validate the complete producer receipt before publishing a prune bridge."""

    if receipt.get("format") != RECEIPT_FORMAT or receipt.get("passed") is not True:
        raise EquivalenceError("Resume equivalence receipt is unsupported or not passing.")
    design = _require_mapping(receipt.get("design"), label="receipt.design")
    expected_design = {
        "baseline_A": _relative(plan.repo_root, plan.baseline.run_dir),
        "control_B": _relative(plan.repo_root, plan.control_output),
        "resumed_C": _relative(plan.repo_root, plan.resumed_output),
        "split_step": plan.split_step,
        "total_steps": plan.total_steps,
        "scheduler_horizon_held_fixed": True,
        "comparison": "bitwise_exact_zero_tolerance",
    }
    if dict(design) != expected_design:
        raise EquivalenceError("Resume equivalence design does not match the pilot plan.")

    bindings = _require_mapping(receipt.get("input_bindings"), label="input_bindings")
    expected_bindings = {
        "baseline_RUN_VERIFICATION_sha256": matrix_runner.sha256_file(
            plan.baseline.verification_path
        ),
        "baseline_LAUNCHED_CONFIG_sha256": matrix_runner.sha256_file(
            plan.baseline.launched_config_path
        ),
        "control_config_sha256": matrix_runner.sha256_file(plan.control_config_path),
        "resumed_config_sha256": matrix_runner.sha256_file(plan.resumed_config_path),
        "validated_baseline_provenance_hashes": _require_mapping(
            _require_mapping(
                plan.baseline.verification.get("provenance"), label="baseline provenance"
            ).get("hashes"),
            label="baseline provenance hashes",
        ),
    }
    for key, expected in expected_bindings.items():
        if bindings.get(key) != expected:
            raise EquivalenceError(f"Resume equivalence binding mismatch: {key}.")
    _require_string(
        bindings.get("checkpoint_resume_signature"),
        label="checkpoint_resume_signature",
    )

    environment = _require_mapping(receipt.get("environment"), label="environment")
    current_environment = _runtime_environment(plan.repo_root)
    for key in ("engine_sha256", "matrix_runner_sha256", "resume_harness_sha256"):
        if environment.get(key) != current_environment.get(key):
            raise EquivalenceError(f"Resume equivalence environment mismatch: {key}.")
    if environment.get("cuda_available") is not True:
        raise EquivalenceError("Resume equivalence receipt is not from an available CUDA runtime.")

    allocator_bindings = _require_mapping(
        receipt.get("allocator_environment_bindings"),
        label="allocator_environment_bindings",
    )
    expected_allocator_bindings = {
        "control": _child_allocator_environment_binding(
            plan,
            output_dir=plan.control_output,
            config_path=plan.control_config_path,
            label="resume control child",
        ),
        "resumed": _child_allocator_environment_binding(
            plan,
            output_dir=plan.resumed_output,
            config_path=plan.resumed_config_path,
            label="resume resumed child",
        ),
    }
    if dict(allocator_bindings) != expected_allocator_bindings:
        raise EquivalenceError(
            "Resume equivalence child allocator environment bindings differ."
        )
    expected_allocator_equivalence = _allocator_runtime_equivalence(
        plan, expected_allocator_bindings
    )
    recorded_allocator_equivalence = _require_mapping(
        receipt.get("allocator_runtime_equivalence"),
        label="allocator_runtime_equivalence",
    )
    if dict(recorded_allocator_equivalence) != expected_allocator_equivalence:
        raise EquivalenceError(
            "Resume equivalence allocator/runtime identity comparison differs."
        )

    launches = _require_mapping(receipt.get("launches"), label="launches")
    for name in ("control", "resumed"):
        launch = _require_mapping(launches.get(name), label=f"launches.{name}")
        if launch.get("returncode") != 0:
            raise EquivalenceError(f"Resume equivalence {name} launch did not succeed.")

    comparisons = _require_mapping(receipt.get("comparisons"), label="comparisons")
    if comparisons.get("passed") is not True:
        raise EquivalenceError("Resume equivalence comparisons are not passing.")
    for group in ("base", "workspace", "trainer"):
        values = _require_mapping(comparisons.get(group), label=f"comparisons.{group}")
        for name in ("save_non_perturbation_A_B", "resume_B_C"):
            result = _require_mapping(values.get(name), label=f"comparisons.{group}.{name}")
            exact_key = "bitwise_exact" if group == "base" else "exact"
            if result.get(exact_key) is not True:
                raise EquivalenceError(f"Resume comparison is not exact: {group}.{name}.")
            if group == "base" and (
                result.get("changed_tensor_count") != 0
                or result.get("changed_element_count") != 0
            ):
                raise EquivalenceError(f"Resume base comparison changed values: {name}.")
        if group == "trainer":
            resumed = _require_mapping(values.get("resume_B_C"), label="trainer resume_B_C")
            if resumed.get("run_id_preserved") is not True:
                raise EquivalenceError("Resume trainer state did not preserve run_id.")
    metrics = _require_mapping(comparisons.get("metrics"), label="comparisons.metrics")
    for name in ("train_A_B", "train_B_C", "final_A_B", "final_B_C"):
        if _require_mapping(metrics.get(name), label=f"metrics.{name}").get("exact") is not True:
            raise EquivalenceError(f"Resume metric comparison is not exact: {name}.")
    resume_event = _require_mapping(
        comparisons.get("resume_event"), label="comparisons.resume_event"
    )
    if (
        resume_event.get("step") != plan.split_step
        or resume_event.get("run_id_preserved") is not True
    ):
        raise EquivalenceError("Resume event does not prove checkpoint continuity.")

    inventories = _require_mapping(
        receipt.get("artifact_inventories"), label="artifact_inventories"
    )
    expected_inventories = {
        "checkpoint_B_split": _inventory(
            plan.control_output / f"checkpoint-{plan.split_step}"
        ),
        "final_A": _inventory(plan.baseline.final_dir),
        "final_B": _inventory(plan.control_output / "final"),
        "final_C": _inventory(plan.resumed_output / "final"),
    }
    for key, expected in expected_inventories.items():
        if inventories.get(key) != expected:
            raise EquivalenceError(f"Resume equivalence inventory mismatch: {key}.")
    boundary = _require_mapping(
        receipt.get("performance_boundary"), label="performance_boundary"
    )
    if (
        boundary.get("training_optimizer_steps_executed")
        != plan.total_steps + (plan.total_steps - plan.split_step)
        or boundary.get("comparison_scope")
        != "same_host_same_single_gpu_same_source_and_runtime"
    ):
        raise EquivalenceError("Resume equivalence performance boundary is malformed.")
    _require_string(receipt.get("claim_boundary"), label="claim_boundary")


def _validate_published_wrapper(
    plan: PilotPlan,
    wrapper: Mapping[str, Any],
    artifact_records: Sequence[Mapping[str, Any]],
) -> None:
    if len(artifact_records) != 3:
        raise EquivalenceError("Published resume artifact set is incomplete.")
    result_record = artifact_records[0]
    provenance = _require_mapping(
        plan.baseline.verification.get("provenance"), label="baseline provenance"
    )
    run_id = _require_string(provenance.get("run_id"), label="baseline run_id")
    comparison = _require_mapping(wrapper.get("comparison"), label="published comparison")
    if (
        wrapper.get("format") != PRUNE_RESUME_VERIFICATION_FORMAT
        or wrapper.get("verified") is not True
        or wrapper.get("run_id") != run_id
        or wrapper.get("provenance") != provenance
        or comparison.get("passed") is not True
        or comparison.get("mode") != "bitwise_exact_zero_tolerance"
        or comparison.get("equivalence_format") != RECEIPT_FORMAT
        or comparison.get("equivalence_artifact") != PUBLISHED_EQUIVALENCE_NAME
        or comparison.get("equivalence_sha256") != result_record["sha256"]
        or comparison.get("baseline_run_verification_sha256")
        != matrix_runner.sha256_file(plan.baseline.verification_path)
        or wrapper.get("artifacts") != [dict(item) for item in artifact_records]
    ):
        raise EquivalenceError("Existing RESUME_VERIFICATION.json is not exactly valid.")


def _publish_prune_resume_verification(
    plan: PilotPlan,
    receipt: Mapping[str, Any],
    *,
    allow_existing_recovery: bool = False,
) -> Path:
    """Publish a compact, run-local bridge consumed by the prune contract."""

    _require_exact_comparison_receipt(plan, receipt)
    result_path = plan.baseline.run_dir / PUBLISHED_EQUIVALENCE_NAME
    wrapper_path = plan.baseline.run_dir / PRUNE_RESUME_VERIFICATION_NAME
    environment_publications = (
        (
            plan.control_output / "environment.json",
            plan.baseline.run_dir / PUBLISHED_CONTROL_ENVIRONMENT_NAME,
        ),
        (
            plan.resumed_output / "environment.json",
            plan.baseline.run_dir / PUBLISHED_RESUMED_ENVIRONMENT_NAME,
        ),
    )
    evidence_paths = [
        result_path,
        *(destination for _source, destination in environment_publications),
    ]
    existing_result = result_path.exists() or result_path.is_symlink()
    existing_wrapper = wrapper_path.exists() or wrapper_path.is_symlink()
    existing_evidence = [
        path for path in evidence_paths if path.exists() or path.is_symlink()
    ]
    if (existing_evidence or existing_wrapper) and not allow_existing_recovery:
        existing = existing_evidence[0] if existing_evidence else wrapper_path
        raise EquivalenceError(
            f"Refusing to overwrite existing baseline resume evidence: {existing}"
        )
    if existing_wrapper and len(existing_evidence) != len(evidence_paths):
        raise EquivalenceError("Resume wrapper exists without its complete evidence set.")
    expected_result_bytes = matrix_runner.canonical_json_bytes(receipt)
    if existing_result:
        _regular_single_link(result_path, label="published equivalence result")
        if result_path.read_bytes() != expected_result_bytes:
            raise EquivalenceError("Existing equivalence result differs from recovery input.")
    else:
        _atomic_create_json(result_path, receipt)
    for source, destination in environment_publications:
        _regular_single_link(source, label="resume child environment source")
        expected = source.read_bytes()
        if destination.exists() or destination.is_symlink():
            _regular_single_link(destination, label="published child environment")
            if destination.read_bytes() != expected:
                raise EquivalenceError(
                    "Published child environment differs from its bound source."
                )
        else:
            _atomic_create_bytes(destination, expected)
    artifact_records = [
        {
            "path": path.name,
            "bytes": path.stat().st_size,
            "sha256": matrix_runner.sha256_file(path),
        }
        for path in evidence_paths
    ]
    result_record = artifact_records[0]
    provenance = _require_mapping(
        plan.baseline.verification.get("provenance"),
        label="baseline provenance",
    )
    run_id = _require_string(provenance.get("run_id"), label="baseline run_id")
    verification_sha256 = matrix_runner.sha256_file(
        plan.baseline.verification_path
    )
    wrapper = {
        "format": PRUNE_RESUME_VERIFICATION_FORMAT,
        "verified": True,
        "created_utc": matrix_runner.utc_now(),
        "run_id": run_id,
        "provenance": provenance,
        "comparison": {
            "passed": True,
            "mode": "bitwise_exact_zero_tolerance",
            "equivalence_format": RECEIPT_FORMAT,
            "equivalence_artifact": PUBLISHED_EQUIVALENCE_NAME,
            "equivalence_sha256": result_record["sha256"],
            "baseline_run_verification_sha256": verification_sha256,
        },
        "artifacts": artifact_records,
        "claim_boundary": (
            "This bridges the hash-bound F0 resume-equivalence receipt into the "
            "verified run retention chain. It does not extend the same-host, "
            "single-GPU, fixed-schedule F0 claim boundary of that receipt."
        ),
    }
    if existing_wrapper:
        _regular_single_link(wrapper_path, label="published resume wrapper")
        _validate_published_wrapper(plan, _read_json(wrapper_path), artifact_records)
    else:
        _atomic_create_json(wrapper_path, wrapper)
    return wrapper_path


def _build_recovery_plan(args: argparse.Namespace) -> PilotPlan:
    repo_root = Path(args.repo_root).expanduser().resolve()
    if not repo_root.is_dir():
        raise EquivalenceError(f"Repository root does not exist: {repo_root}")
    baseline = validate_baseline(
        repo_root,
        _repo_path(repo_root, args.baseline_run, label="baseline run"),
    )
    train = _require_mapping(baseline.launched_config.get("train"), label="train")
    total_steps = int(
        args.total_steps if args.total_steps is not None else train["max_steps"]
    )
    output_root = _repo_path(repo_root, args.output_root, label="resume pilot output")
    if output_root.is_symlink() or not output_root.is_dir():
        raise EquivalenceError("Recovery requires an existing non-symlink pilot output root.")
    max_working_set_bytes = int(args.max_working_set_mib) * 1024 * 1024
    if max_working_set_bytes < 1:
        raise EquivalenceError("--max-working-set-mib must be positive.")
    return PilotPlan(
        repo_root=repo_root,
        baseline=baseline,
        output_root=output_root,
        control_output=output_root / "control_uninterrupted",
        resumed_output=output_root / "resumed_from_split",
        control_config_path=output_root / "CONTROL_CONFIG.json",
        resumed_config_path=output_root / "RESUME_CONFIG.json",
        split_step=int(args.split_step),
        total_steps=total_steps,
        python=str(args.python),
        engine_module=str(args.engine_module),
        max_working_set_bytes=max_working_set_bytes,
    )


def recover_publication(plan: PilotPlan) -> Path:
    """Recompute an existing pilot and finish only its interrupted publication."""

    receipt_path = plan.output_root / "RESUME_EQUIVALENCE.json"
    _regular_single_link(receipt_path, label="resume equivalence recovery receipt")
    receipt = _read_json(receipt_path)
    recomputed = compare_all_artifacts(plan)
    recorded = _require_mapping(receipt.get("comparisons"), label="comparisons")
    def without_elapsed(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                key: without_elapsed(child)
                for key, child in value.items()
                if key != "elapsed_seconds"
            }
        if isinstance(value, list):
            return [without_elapsed(child) for child in value]
        return value

    recorded_stable = without_elapsed(recorded)
    recomputed_stable = without_elapsed(recomputed)
    if recorded_stable != recomputed_stable:
        raise EquivalenceError("Recovery recomputation differs from the stored comparisons.")
    return _publish_prune_resume_verification(
        plan,
        receipt,
        allow_existing_recovery=True,
    )


def execute_plan(plan: PilotPlan, *, launch: LaunchFunction = _default_launch) -> Path:
    preflight = _execution_preflight(plan)
    require_new_output_root(plan.repo_root, plan.output_root)
    _require_new_baseline_evidence_paths(plan)
    plan.output_root.parent.mkdir(parents=True, exist_ok=True)
    plan.output_root.mkdir(exist_ok=False)
    control, resumed = derive_pilot_configs(
        plan.baseline,
        plan.repo_root,
        plan.output_root,
        split_step=plan.split_step,
        total_steps=plan.total_steps,
    )
    _write_configs(plan, control, resumed)
    environment = _offline_environment(plan.repo_root)
    control_command = (
        plan.python,
        "-m",
        plan.engine_module,
        "train",
        "--config",
        str(plan.control_config_path),
        "--fresh",
    )
    control_launch = launch(
        control_command,
        plan.repo_root,
        plan.output_root / "control.stdout.log",
        plan.output_root / "control.stderr.log",
        environment,
    )
    if control_launch.returncode != 0:
        raise EquivalenceError(
            f"Control training failed with {control_launch.returncode}; see "
            f"{control_launch.stderr_path}."
        )
    control_allocator_environment = _child_allocator_environment_binding(
        plan,
        output_dir=plan.control_output,
        config_path=plan.control_config_path,
        label="resume control child",
    )

    expected_engine_sha = matrix_runner.sha256_file(
        plan.repo_root / "src" / "latent_workspace_ft_v10" / "engine.py"
    )
    checkpoint = plan.control_output / f"checkpoint-{plan.split_step}"
    checkpoint_manifest = _require_complete_bundle(
        checkpoint,
        expected_step=plan.split_step,
        expected_source_sha256=expected_engine_sha,
    )
    control_manifest = _require_complete_bundle(
        plan.control_output / "final",
        expected_step=plan.total_steps,
        expected_source_sha256=expected_engine_sha,
    )
    if checkpoint_manifest.get("resume_signature") != control_manifest.get("resume_signature"):
        raise EquivalenceError("Control checkpoint/final resume signatures differ.")
    checkpoint_inventory = _inventory(checkpoint)

    resumed_command = (
        plan.python,
        "-m",
        plan.engine_module,
        "train",
        "--config",
        str(plan.resumed_config_path),
        "--resume-from",
        str(checkpoint),
    )
    resumed_launch = launch(
        resumed_command,
        plan.repo_root,
        plan.output_root / "resumed.stdout.log",
        plan.output_root / "resumed.stderr.log",
        environment,
    )
    if resumed_launch.returncode != 0:
        raise EquivalenceError(
            f"Resumed training failed with {resumed_launch.returncode}; see "
            f"{resumed_launch.stderr_path}."
        )
    resumed_allocator_environment = _child_allocator_environment_binding(
        plan,
        output_dir=plan.resumed_output,
        config_path=plan.resumed_config_path,
        label="resume resumed child",
    )
    allocator_environment_bindings = {
        "control": control_allocator_environment,
        "resumed": resumed_allocator_environment,
    }
    allocator_runtime_equivalence = _allocator_runtime_equivalence(
        plan, allocator_environment_bindings
    )
    resumed_manifest = _require_complete_bundle(
        plan.resumed_output / "final",
        expected_step=plan.total_steps,
        expected_source_sha256=expected_engine_sha,
    )
    if checkpoint_manifest.get("resume_signature") != resumed_manifest.get("resume_signature"):
        raise EquivalenceError("Checkpoint/resumed-final resume signatures differ.")

    comparisons = compare_all_artifacts(plan)
    receipt = {
        "format": RECEIPT_FORMAT,
        "passed": True,
        "created_utc": matrix_runner.utc_now(),
        "design": {
            "baseline_A": _relative(plan.repo_root, plan.baseline.run_dir),
            "control_B": _relative(plan.repo_root, plan.control_output),
            "resumed_C": _relative(plan.repo_root, plan.resumed_output),
            "split_step": plan.split_step,
            "total_steps": plan.total_steps,
            "scheduler_horizon_held_fixed": True,
            "comparison": "bitwise_exact_zero_tolerance",
        },
        "input_bindings": {
            "baseline_RUN_VERIFICATION_sha256": matrix_runner.sha256_file(
                plan.baseline.verification_path
            ),
            "baseline_LAUNCHED_CONFIG_sha256": matrix_runner.sha256_file(
                plan.baseline.launched_config_path
            ),
            "control_config_sha256": matrix_runner.sha256_file(plan.control_config_path),
            "resumed_config_sha256": matrix_runner.sha256_file(plan.resumed_config_path),
            "checkpoint_resume_signature": checkpoint_manifest.get("resume_signature"),
            "validated_baseline_provenance_hashes": _require_mapping(
                _require_mapping(
                    plan.baseline.verification.get("provenance"),
                    label="baseline provenance",
                ).get("hashes"),
                label="baseline provenance hashes",
            ),
        },
        "environment": _runtime_environment(plan.repo_root),
        "allocator_environment_bindings": {
            "control": control_allocator_environment,
            "resumed": resumed_allocator_environment,
        },
        "allocator_runtime_equivalence": allocator_runtime_equivalence,
        "preflight": preflight,
        "launches": {
            "control": {
                "returncode": control_launch.returncode,
                "elapsed_seconds": control_launch.elapsed_seconds,
                "stdout": _relative(plan.repo_root, control_launch.stdout_path),
                "stderr": _relative(plan.repo_root, control_launch.stderr_path),
            },
            "resumed": {
                "returncode": resumed_launch.returncode,
                "elapsed_seconds": resumed_launch.elapsed_seconds,
                "stdout": _relative(plan.repo_root, resumed_launch.stdout_path),
                "stderr": _relative(plan.repo_root, resumed_launch.stderr_path),
            },
        },
        "artifact_inventories": {
            "checkpoint_B_split": checkpoint_inventory,
            "final_A": _inventory(plan.baseline.final_dir),
            "final_B": _inventory(plan.control_output / "final"),
            "final_C": _inventory(plan.resumed_output / "final"),
        },
        "comparisons": comparisons,
        "performance_boundary": {
            "max_estimated_comparison_working_set_bytes": plan.max_working_set_bytes,
            "training_optimizer_steps_executed": plan.total_steps
            + (plan.total_steps - plan.split_step),
            "comparison_scope": "same_host_same_single_gpu_same_source_and_runtime",
        },
        "claim_boundary": (
            "This verifies one F0 seed-42 single-GPU run on the recorded host/runtime: "
            "a step-boundary checkpoint saved under the original eight-step schedule, "
            "then reloaded with strict resume, produced bitwise-identical durable base, "
            "workspace, optimizer, scheduler, scaler, sampler, RNG, and RunState state "
            "plus exact stable metrics. It does not verify signal-preemption behavior, "
            "multi-GPU resume, schedule extension, cross-hardware/runtime reproducibility, "
            "or the active stochastic workspace route; F0 bypasses that route."
        ),
    }
    receipt_path = plan.output_root / "RESUME_EQUIVALENCE.json"
    matrix_runner.atomic_write_json(receipt_path, receipt)
    _publish_prune_resume_verification(plan, receipt)
    return receipt_path


def plan_summary(plan: PilotPlan) -> dict[str, Any]:
    return {
        "format": RECEIPT_FORMAT,
        "execute": False,
        "baseline_verified": True,
        "baseline": _relative(plan.repo_root, plan.baseline.run_dir),
        "output_root": _relative(plan.repo_root, plan.output_root),
        "control_output": _relative(plan.repo_root, plan.control_output),
        "resumed_output": _relative(plan.repo_root, plan.resumed_output),
        "split_step": plan.split_step,
        "total_steps": plan.total_steps,
        "comparison": "bitwise_exact_zero_tolerance",
        "would_execute_optimizer_steps": plan.total_steps + (plan.total_steps - plan.split_step),
        "note": "Dry-run only. Pass --execute to create outputs and launch CUDA training.",
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail-closed v10 checkpoint/save/reload/resume equivalence pilot."
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--baseline-run", default=str(DEFAULT_BASELINE))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--split-step", type=int, default=4)
    parser.add_argument(
        "--total-steps",
        type=int,
        default=None,
        help="Must equal the verified baseline max_steps; it cannot extend the schedule.",
    )
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--engine-module", default="latent_workspace_ft_v10.engine")
    parser.add_argument("--max-working-set-mib", type=int, default=64)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Explicitly create exclusive outputs and run the two CUDA subprocesses.",
    )
    parser.add_argument(
        "--recover-publish",
        action="store_true",
        help=(
            "With --execute, recompute an existing pilot and finish only an "
            "interrupted final evidence publication."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    try:
        if args.recover_publish:
            if not args.execute:
                raise EquivalenceError("--recover-publish requires --execute.")
            plan = _build_recovery_plan(args)
            lock_path = plan.repo_root / "runs/v10/_control/RUNNER.lock"
            with matrix_runner.exclusive_lock(lock_path):
                plan = _build_recovery_plan(args)
                wrapper = recover_publication(plan)
            print(json.dumps({"passed": True, "recovered": str(wrapper)}, indent=2))
            return
        plan = build_plan(args)
        if not args.execute:
            print(json.dumps(plan_summary(plan), indent=2, sort_keys=True))
            return
        lock_path = plan.repo_root / "runs/v10/_control/RUNNER.lock"
        with matrix_runner.exclusive_lock(lock_path):
            plan = build_plan(args)
            receipt = execute_plan(plan)
        print(json.dumps({"passed": True, "receipt": str(receipt)}, indent=2))
    except (EquivalenceError, matrix_runner.RunnerError) as exc:
        raise SystemExit(f"resume-equivalence: {exc}") from exc


if __name__ == "__main__":
    main()
