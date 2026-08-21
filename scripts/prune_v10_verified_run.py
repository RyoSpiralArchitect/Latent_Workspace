#!/usr/bin/env python3
"""Fail-closed retention transition for one verified v10 run.

Dry-run is the default.  Execution requires ``--execute``, a non-empty reason,
and a compact-evidence export root.  Deletion targets are derived exclusively
from the verified run artifacts; callers cannot supply target paths or globs.

The resulting state is intentionally named ``verified_pruned`` rather than
``verified_completed``.  Its receipts preserve a historical verification
chain, but the trained weights are no longer loadable or reconstructible.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

RUN_VERIFICATION_FORMAT = "latent-workspace-v10-run-verification-v1"
ASSAY_VERIFICATION_FORMAT = "latent-workspace-v10-assay-verification-v1"
RESUME_VERIFICATION_FORMAT = "latent-workspace-v10-resume-verification-v1"
RESUME_EQUIVALENCE_FORMAT = "latent-workspace-v10-resume-equivalence-v1"
BUNDLE_IDENTITY_FORMAT = "latent-workspace-v10-bundle-identity-v1"
COMPACT_EXPORT_FORMAT = "latent-workspace-v10-compact-evidence-export-v1"
PRUNE_INTENT_FORMAT = "latent-workspace-v10-prune-intent-v1"
PRUNE_RECEIPT_FORMAT = "latent-workspace-v10-verified-run-prune-v1"

RUN_VERIFICATION_NAME = "RUN_VERIFICATION.json"
FULL_UPDATE_DELTA_NAME = "FULL_UPDATE_DELTA.json"
ASSAY_VERIFICATION_NAME = "ASSAY_VERIFICATION.json"
RESUME_VERIFICATION_NAME = "RESUME_VERIFICATION.json"
LAUNCHED_CONFIG_NAME = "LAUNCHED_CONFIG.json"
METRICS_NAME = "metrics.jsonl"
AMPUTATION_REPORT_NAME = "amputation_report.json"
RESUME_EQUIVALENCE_NAME = "resume_equivalence_result.json"
RESUME_CONTROL_ENVIRONMENT_NAME = "resume_control_environment.json"
RESUME_RESUMED_ENVIRONMENT_NAME = "resume_resumed_environment.json"
ENVIRONMENT_NAME = "environment.json"
GRADIENT_ACCUMULATION_OFFLOAD_RECEIPT_NAME = (
    "gradient_accumulation_offload.json"
)
RESUME_CONTROL_GRADIENT_OFFLOAD_NAME = (
    "resume_control_gradient_accumulation_offload.json"
)
RESUME_RESUMED_GRADIENT_OFFLOAD_NAME = (
    "resume_resumed_gradient_accumulation_offload.json"
)
GRADIENT_ACCUMULATION_OFFLOAD = "cpu"
GRADIENT_OFFLOAD_SCHEMA_VERSION = 2
GRADIENT_OFFLOAD_ALGORITHM = "pageable_cpu_storage_cuda_native_order_add_v1"
GRADIENT_OFFLOAD_COUNTER_FIELDS = (
    "windows_started",
    "windows_restored",
    "windows_discarded",
    "single_microbatch_windows",
    "microbatch_spills",
    "parameter_first_spills",
    "parameter_merges",
    "cumulative_current_gradient_bytes",
    "peak_cpu_accumulator_bytes",
)
GRADIENT_OFFLOAD_SCHEMA_FIELDS = (
    "name",
    "shape",
    "stride",
    "dtype",
    "device",
    "numel",
    "logical_bytes",
)
GRADIENT_OFFLOAD_SEMANTIC_FIELDS = (
    "schema_version",
    "mode",
    "algorithm",
    "source_sha256",
    "resume_signature",
    "configured_gradient_accumulation_steps",
    "trainable_parameter_count",
    "trainable_parameter_total_numel",
    "trainable_gradient_capacity_bytes",
    "trainable_parameter_schema_sha256",
    "trainable_parameter_schema_fields",
)
PRUNE_INTENT_NAME = "PRUNE_INTENT.json"
PRUNE_RECEIPT_NAME = "PRUNE_RECEIPT.json"
EXPORT_RECEIPT_NAME = "EXPORT_RECEIPT.json"

EXTERNAL_ASSAY_RESULTS = {
    "necessity": "necessity_result.json",
    "choice_eval": "choice_eval_result.json",
    "recruitment": "recruitment_result.json",
}
EXTERNAL_ASSAY_FORMATS = {
    "necessity": {
        "latent-workspace-v8-semantic-necessity-v2",
        "latent-workspace-v9-functional-necessity-v1",
    },
    "choice_eval": {"latent-workspace-v8-semantic-choice-eval-v2"},
    "recruitment": {"latent-workspace-v8-recruitability-v2"},
}

SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
CHECKPOINT_RE = re.compile(r"^checkpoint-([0-9]+)$")
PHASE_POINTER_RE = re.compile(r"^phase-boundary-step-([0-9]+)\.json$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
POINTER_NAMES = ("latest_checkpoint.json", "best_checkpoint.json")


class PruneError(RuntimeError):
    """A retention validation or transaction error."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


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
        raise PruneError(f"Could not read JSON receipt {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PruneError(f"JSON receipt must contain an object: {path}")
    return value


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_create_json(path: Path, value: Any) -> None:
    """Create a durable JSON file without ever replacing an existing path."""

    if path.exists() or path.is_symlink():
        raise PruneError(f"Refusing to overwrite existing evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise PruneError(f"Refusing to overwrite existing evidence: {path}") from exc
        temporary.unlink()
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _safe_relative(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise PruneError(f"{label} must be a non-empty POSIX relative path.")
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise PruneError(f"Unsafe {label}: {value!r}")
    if relative.as_posix() != value:
        raise PruneError(f"Non-canonical {label}: {value!r}")
    return value


def _safe_join(root: Path, relative: str, *, label: str) -> Path:
    relative = _safe_relative(relative, label=label)
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    try:
        candidate.resolve(strict=False).relative_to(root.resolve())
    except ValueError as exc:
        raise PruneError(f"{label} escapes its run root: {relative!r}") from exc
    return candidate


def _validate_sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise PruneError(f"{label} must be a lowercase SHA-256 digest.")
    return value


def _require_plain_directory(path: Path, *, label: str) -> None:
    try:
        observed = path.lstat()
    except FileNotFoundError as exc:
        raise PruneError(f"Missing {label}: {path}") from exc
    if stat.S_ISLNK(observed.st_mode) or not stat.S_ISDIR(observed.st_mode):
        raise PruneError(f"{label} must be a non-symlink directory: {path}")


def _resolve_run_dir(path: Path, *, label: str) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise PruneError(f"{label} must not be a symlink: {expanded}")
    resolved = expanded.resolve()
    _require_plain_directory(resolved, label=label)
    return resolved


def _regular_file_record(path: Path, *, relative: str) -> dict[str, Any]:
    relative = _safe_relative(relative, label="artifact path")
    try:
        observed = path.lstat()
    except FileNotFoundError as exc:
        raise PruneError(f"Missing artifact: {path}") from exc
    if stat.S_ISLNK(observed.st_mode) or not stat.S_ISREG(observed.st_mode):
        raise PruneError(f"Artifact must be a regular non-symlink file: {path}")
    if observed.st_nlink != 1:
        raise PruneError(f"Hard-linked artifacts are forbidden: {path}")
    return {
        "path": relative,
        "bytes": int(observed.st_size),
        "sha256": sha256_file(path),
    }


def _directory_layout(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Return a hash inventory and exact directory list without following links."""

    _require_plain_directory(root, label="artifact directory")
    inventory: list[dict[str, Any]] = []
    directories: list[str] = []
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        directory_names.sort()
        file_names.sort()
        for name in directory_names:
            path = current_path / name
            observed = path.lstat()
            if stat.S_ISLNK(observed.st_mode) or not stat.S_ISDIR(observed.st_mode):
                raise PruneError(f"Symlink or non-directory found in artifact tree: {path}")
            directories.append(path.relative_to(root).as_posix())
        for name in file_names:
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            inventory.append(_regular_file_record(path, relative=relative))
    inventory.sort(key=lambda item: str(item["path"]))
    directories.sort()
    return inventory, directories


def _inventory_sha256(inventory: Sequence[Mapping[str, Any]]) -> str:
    return sha256_bytes(canonical_json_bytes(list(inventory)))


def _validate_inventory_records(
    raw: Any,
    *,
    label: str,
) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise PruneError(f"{label} must be a non-empty inventory list.")
    records: list[dict[str, Any]] = []
    names: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise PruneError(f"Malformed record in {label}.")
        relative = _safe_relative(item.get("path"), label=f"{label} path")
        size = item.get("bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise PruneError(f"Invalid byte count for {relative!r} in {label}.")
        digest = _validate_sha256(item.get("sha256"), label=f"{label} sha256")
        if relative in names:
            raise PruneError(f"Duplicate path in {label}: {relative!r}")
        names.add(relative)
        records.append({"path": relative, "bytes": size, "sha256": digest})
    return sorted(records, key=lambda item: str(item["path"]))


def _stable_json_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_trainer_state_identity(path: Path) -> Mapping[str, Any]:
    """Load trainer metadata without materializing tensor storage when supported."""

    try:
        import torch
    except ImportError as exc:  # pragma: no cover - project runtime dependency
        raise PruneError("Bundle identity validation requires torch.") from exc
    try:
        try:
            value = torch.load(
                path,
                map_location="cpu",
                weights_only=False,
                mmap=True,
            )
        except TypeError:  # pragma: no cover - older supported torch
            value = torch.load(path, map_location="cpu", weights_only=False)
    except Exception as exc:
        raise PruneError(f"Could not load trainer identity from {path}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise PruneError(f"Trainer state must contain a mapping: {path}")
    return value


def validate_bundle_identity(
    bundle_dir: Path,
    *,
    bundle_path: str,
    expected_global_step: int,
) -> dict[str, Any]:
    """Cross-bind one bundle's manifest, trainer state, and persisted config."""

    bundle_path = _safe_relative(bundle_path, label="bundle identity path")
    expected_global_step = _require_nonnegative_integer(
        expected_global_step,
        label="expected bundle global_step",
    )
    _require_plain_directory(bundle_dir, label="bundle identity directory")
    artifacts = {
        name: _regular_file_record(bundle_dir / name, relative=name)
        for name in ("manifest.json", "trainer_state.pt", "experiment_config.json")
    }
    manifest = read_json(bundle_dir / "manifest.json")
    experiment_config = read_json(bundle_dir / "experiment_config.json")
    trainer = _load_trainer_state_identity(bundle_dir / "trainer_state.pt")
    run_state = _require_mapping(
        trainer.get("run_state"), label="bundle trainer_state.run_state"
    )

    run_id = manifest.get("run_id")
    manifest_step = manifest.get("global_step")
    trainer_step = trainer.get("global_step")
    run_state_step = run_state.get("global_step")
    manifest_resume = manifest.get("resume_signature")
    trainer_resume = trainer.get("resume_signature")
    manifest_structural = manifest.get("structural_resume_signature")
    trainer_structural = trainer.get("structural_resume_signature")
    manifest_world_size = manifest.get("world_size")
    trainer_world_size = trainer.get("world_size")
    manifest_fingerprint = manifest.get("data_fingerprint")
    trainer_fingerprint = trainer.get("data_fingerprint")
    manifest_config_sha256 = manifest.get("config_sha256")
    computed_config_sha256 = _stable_json_sha256(experiment_config)

    if not isinstance(run_id, str) or not run_id:
        raise PruneError("Bundle manifest run_id is incomplete.")
    if run_state.get("run_id") != run_id:
        raise PruneError("Bundle manifest/trainer run_id binding is not exact.")
    for value, label in (
        (manifest_step, "manifest global_step"),
        (trainer_step, "trainer global_step"),
        (run_state_step, "run_state global_step"),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise PruneError(f"Bundle {label} must be an integer.")
    if not (
        manifest_step == trainer_step == run_state_step == expected_global_step
    ):
        raise PruneError("Bundle manifest/trainer global_step binding is not exact.")
    for value, label in (
        (manifest_resume, "manifest resume_signature"),
        (trainer_resume, "trainer resume_signature"),
        (manifest_structural, "manifest structural_resume_signature"),
        (trainer_structural, "trainer structural_resume_signature"),
        (manifest_config_sha256, "manifest config_sha256"),
    ):
        _validate_sha256(value, label=f"bundle {label}")
    if manifest_resume != trainer_resume:
        raise PruneError("Bundle manifest/trainer resume_signature binding is not exact.")
    if manifest_structural != trainer_structural:
        raise PruneError(
            "Bundle manifest/trainer structural_resume_signature binding is not exact."
        )
    if manifest_config_sha256 != computed_config_sha256:
        raise PruneError("Bundle manifest/experiment_config hash binding is not exact.")
    if (
        isinstance(manifest_world_size, bool)
        or not isinstance(manifest_world_size, int)
        or manifest_world_size < 1
        or trainer_world_size != manifest_world_size
    ):
        raise PruneError("Bundle manifest/trainer world_size binding is not exact.")
    if not isinstance(manifest_fingerprint, Mapping) or not isinstance(
        trainer_fingerprint, Mapping
    ):
        raise PruneError("Bundle manifest/trainer data_fingerprint is malformed.")
    if dict(manifest_fingerprint) != dict(trainer_fingerprint):
        raise PruneError("Bundle manifest/trainer data_fingerprint binding is not exact.")

    return {
        "format": BUNDLE_IDENTITY_FORMAT,
        "passed": True,
        "bundle_path": bundle_path,
        "artifacts": artifacts,
        "run_id": run_id,
        "global_step": expected_global_step,
        "resume_signature": manifest_resume,
        "structural_resume_signature": manifest_structural,
        "config_sha256": computed_config_sha256,
        "world_size": manifest_world_size,
        "data_fingerprint_sha256": _stable_json_sha256(
            dict(manifest_fingerprint)
        ),
        "bindings": {
            "manifest_trainer_run_id_exact": True,
            "manifest_trainer_global_step_exact": True,
            "manifest_trainer_resume_signature_exact": True,
            "manifest_trainer_structural_resume_signature_exact": True,
            "manifest_experiment_config_sha256_exact": True,
            "manifest_trainer_world_size_exact": True,
            "manifest_trainer_data_fingerprint_exact": True,
        },
    }


def validate_bundle_identity_summary(
    value: Any,
    *,
    expected_bundle_path: str,
    expected_global_step: int,
    expected_inventory: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate a persisted bundle identity and bind its three source files."""

    summary = _require_mapping(value, label="bundle identity summary")
    expected_keys = {
        "format",
        "passed",
        "bundle_path",
        "artifacts",
        "run_id",
        "global_step",
        "resume_signature",
        "structural_resume_signature",
        "config_sha256",
        "world_size",
        "data_fingerprint_sha256",
        "bindings",
    }
    _require_exact_keys(summary, expected_keys, label="bundle identity summary")
    expected_bundle_path = _safe_relative(
        expected_bundle_path, label="expected bundle identity path"
    )
    if (
        summary.get("format") != BUNDLE_IDENTITY_FORMAT
        or summary.get("passed") is not True
        or summary.get("bundle_path") != expected_bundle_path
        or summary.get("global_step") != expected_global_step
        or not isinstance(summary.get("run_id"), str)
        or not summary.get("run_id")
        or isinstance(summary.get("world_size"), bool)
        or not isinstance(summary.get("world_size"), int)
        or int(summary["world_size"]) < 1
    ):
        raise PruneError("Bundle identity summary scalar bindings are not exact.")
    for field in (
        "resume_signature",
        "structural_resume_signature",
        "config_sha256",
        "data_fingerprint_sha256",
    ):
        _validate_sha256(summary.get(field), label=f"bundle identity {field}")
    expected_bindings = {
        "manifest_trainer_run_id_exact": True,
        "manifest_trainer_global_step_exact": True,
        "manifest_trainer_resume_signature_exact": True,
        "manifest_trainer_structural_resume_signature_exact": True,
        "manifest_experiment_config_sha256_exact": True,
        "manifest_trainer_world_size_exact": True,
        "manifest_trainer_data_fingerprint_exact": True,
    }
    if summary.get("bindings") != expected_bindings:
        raise PruneError("Bundle identity summary checks are not exact.")

    artifacts = _require_mapping(
        summary.get("artifacts"), label="bundle identity artifacts"
    )
    required_artifacts = {
        "manifest.json",
        "trainer_state.pt",
        "experiment_config.json",
    }
    _require_exact_keys(
        artifacts, required_artifacts, label="bundle identity artifacts"
    )
    inventory_by_path = {
        str(record["path"]): record
        for record in _validate_inventory_records(
            list(expected_inventory), label="bundle identity inventory"
        )
    }
    normalized_artifacts: dict[str, dict[str, Any]] = {}
    for name in sorted(required_artifacts):
        records = _validate_inventory_records(
            [artifacts[name]], label=f"bundle identity artifact {name}"
        )
        record = records[0]
        if record["path"] != name or inventory_by_path.get(name) != record:
            raise PruneError(
                f"Bundle identity artifact {name} is not exact in its inventory."
            )
        normalized_artifacts[name] = record
    normalized = dict(summary)
    normalized["artifacts"] = normalized_artifacts
    return normalized


def _artifact_matches(path: Path, expected: Mapping[str, Any]) -> None:
    actual = _regular_file_record(path, relative=str(expected["path"]))
    if actual != dict(expected):
        raise PruneError(f"Artifact inventory/hash mismatch: {path}")


def _require_mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PruneError(f"{label} must be a JSON object.")
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    *,
    label: str,
) -> None:
    observed = set(value)
    if observed != expected:
        raise PruneError(
            f"{label} keys are not exact: missing={sorted(expected - observed)}, "
            f"unexpected={sorted(observed - expected)}."
        )


def _require_nonnegative_number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise PruneError(f"{label} must be a non-negative finite number.")
    observed = float(value)
    if observed != observed or observed in {float("inf"), float("-inf")}:
        raise PruneError(f"{label} must be a non-negative finite number.")
    return observed


def _require_nonnegative_integer(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PruneError(f"{label} must be a non-negative integer.")
    return value


def gradient_accumulation_offload_receipt_self_hash(
    receipt: Mapping[str, Any],
) -> str:
    """Recompute the engine's self-hash with only receipt_sha256 nulled."""

    payload = dict(receipt)
    payload["receipt_sha256"] = None
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def gradient_offload_inventory_identity(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return the engine-stable compact hash/count/bytes for sorted records."""

    normalized = _validate_inventory_records(
        list(records), label="gradient-offload checkpoint inventory"
    )
    compact = json.dumps(normalized, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return {
        "bundle_inventory_sha256": hashlib.sha256(compact).hexdigest(),
        "file_count": len(normalized),
        "logical_bytes": sum(int(record["bytes"]) for record in normalized),
    }


def gradient_offload_checkpoint_bundle_inventory(checkpoint: Path) -> dict[str, Any]:
    """Recompute the engine's compact-hash checkpoint inventory identity."""

    _require_plain_directory(checkpoint, label="gradient-offload checkpoint")
    for required_name in ("COMPLETED", "manifest.json", "workspace_state.pt"):
        _regular_file_record(
            checkpoint / required_name,
            relative=required_name,
        )
    records, _directories = _directory_layout(checkpoint)
    manifest_records = [record for record in records if record["path"] == "manifest.json"]
    if len(manifest_records) != 1:
        raise PruneError(
            "Gradient-offload checkpoint inventory has no unique manifest."
        )
    return gradient_offload_inventory_identity(records)


def gradient_offload_checkpoint_descriptor(
    checkpoint: Path,
    *,
    output_dir: Path,
) -> dict[str, Any]:
    """Recompute the engine's portable checkpoint descriptor from live bytes."""

    checkpoint = checkpoint.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    inventory = gradient_offload_checkpoint_bundle_inventory(checkpoint)
    manifest_path = checkpoint / "manifest.json"
    manifest = read_json(manifest_path)
    identity = {
        "run_id": manifest.get("run_id"),
        "global_step": manifest.get("global_step"),
        "source_sha256": manifest.get("source_sha256"),
        "resume_signature": manifest.get("resume_signature"),
    }
    if (
        not isinstance(identity["run_id"], str)
        or not identity["run_id"]
        or isinstance(identity["global_step"], bool)
        or not isinstance(identity["global_step"], int)
        or not isinstance(identity["source_sha256"], str)
        or SHA256_RE.fullmatch(identity["source_sha256"]) is None
        or not isinstance(identity["resume_signature"], str)
        or SHA256_RE.fullmatch(identity["resume_signature"]) is None
    ):
        raise PruneError(
            "Gradient-offload checkpoint manifest identity is incomplete."
        )
    common = {
        "manifest_sha256": sha256_file(manifest_path),
        "manifest_identity": identity,
        **inventory,
    }
    if checkpoint.parent == output_dir:
        return {
            "scope": "output_dir",
            "relative_path": checkpoint.name,
            **common,
        }
    return {"scope": "external", "basename": checkpoint.name, **common}


def _gradient_offload_counter_snapshot(
    value: Any,
    *,
    label: str,
) -> dict[str, int]:
    mapping = _require_mapping(value, label=label)
    _require_exact_keys(
        mapping,
        set(GRADIENT_OFFLOAD_COUNTER_FIELDS),
        label=label,
    )
    return {
        field: _require_nonnegative_integer(mapping.get(field), label=f"{label}.{field}")
        for field in GRADIENT_OFFLOAD_COUNTER_FIELDS
    }


def _gradient_offload_checkpoint_descriptor(
    value: Any,
    *,
    label: str,
    expected_run_id: str,
    expected_step: int,
    expected_source_sha256: str,
    expected_resume_signature: str,
    required_scope: str | None = None,
) -> dict[str, Any]:
    descriptor = _require_mapping(value, label=label)
    scope = descriptor.get("scope")
    common_keys = {
        "scope",
        "manifest_sha256",
        "manifest_identity",
        "bundle_inventory_sha256",
        "file_count",
        "logical_bytes",
    }
    if scope == "output_dir":
        _require_exact_keys(
            descriptor,
            common_keys | {"relative_path"},
            label=label,
        )
        checkpoint_name = _safe_relative(
            descriptor.get("relative_path"), label=f"{label}.relative_path"
        )
        if PurePosixPath(checkpoint_name).name != checkpoint_name:
            raise PruneError(f"{label}.relative_path must be one checkpoint basename.")
    elif scope == "external":
        _require_exact_keys(
            descriptor,
            common_keys | {"basename"},
            label=label,
        )
        checkpoint_name = descriptor.get("basename")
        if (
            not isinstance(checkpoint_name, str)
            or not checkpoint_name
            or "/" in checkpoint_name
            or "\\" in checkpoint_name
            or checkpoint_name in {".", ".."}
        ):
            raise PruneError(f"{label}.basename is unsafe.")
    else:
        raise PruneError(f"{label}.scope is unsupported: {scope!r}.")
    if required_scope is not None and scope != required_scope:
        raise PruneError(f"{label}.scope must be {required_scope!r}.")
    if CHECKPOINT_RE.fullmatch(str(checkpoint_name)) is None:
        raise PruneError(f"{label} does not name a canonical checkpoint.")
    _validate_sha256(descriptor.get("manifest_sha256"), label=f"{label}.manifest_sha256")
    _validate_sha256(
        descriptor.get("bundle_inventory_sha256"),
        label=f"{label}.bundle_inventory_sha256",
    )
    file_count = _require_nonnegative_integer(
        descriptor.get("file_count"), label=f"{label}.file_count"
    )
    if file_count < 1:
        raise PruneError(f"{label}.file_count must be positive.")
    _require_nonnegative_integer(
        descriptor.get("logical_bytes"), label=f"{label}.logical_bytes"
    )
    identity = _require_mapping(
        descriptor.get("manifest_identity"), label=f"{label}.manifest_identity"
    )
    _require_exact_keys(
        identity,
        {"run_id", "global_step", "source_sha256", "resume_signature"},
        label=f"{label}.manifest_identity",
    )
    if dict(identity) != {
        "run_id": expected_run_id,
        "global_step": expected_step,
        "source_sha256": expected_source_sha256,
        "resume_signature": expected_resume_signature,
    }:
        raise PruneError(f"{label}.manifest_identity is not exact.")
    return dict(descriptor)


def _validate_gradient_offload_counter_equations(
    counters: Mapping[str, int],
    *,
    label: str,
    configured_accumulation_steps: int,
    parameter_count: int,
    gradient_capacity_bytes: int,
    validate_peak: bool = True,
) -> None:
    windows = counters["windows_started"]
    multi_windows = counters["windows_restored"] + counters["windows_discarded"]
    if windows != multi_windows + counters["single_microbatch_windows"]:
        raise PruneError(f"{label} window counters do not balance.")
    if (
        counters["windows_discarded"] != 0
        or counters["single_microbatch_windows"] != 0
        or counters["windows_restored"] != windows
    ):
        raise PruneError(
            f"{label} is not skip-free: discarded, nonfinite, skipped, and "
            "single-microbatch windows are rejected."
        )
    spills = counters["microbatch_spills"]
    if spills != configured_accumulation_steps * windows:
        raise PruneError(f"{label} does not prove every contracted microbatch spill.")
    first_spills = counters["parameter_first_spills"]
    if multi_windows == 0:
        if any(
            counters[field] != 0
            for field in (
                "microbatch_spills",
                "parameter_first_spills",
                "parameter_merges",
                "cumulative_current_gradient_bytes",
                "peak_cpu_accumulator_bytes",
            )
        ):
            raise PruneError(f"{label} records spill work without a multi-window.")
        return
    if not (multi_windows <= first_spills <= parameter_count * multi_windows):
        raise PruneError(f"{label} first-spill count is impossible.")
    merge_limit = parameter_count * (spills - multi_windows)
    if counters["parameter_merges"] > merge_limit:
        raise PruneError(f"{label} parameter merge count is impossible.")
    gradient_bytes = counters["cumulative_current_gradient_bytes"]
    if not (0 < gradient_bytes <= gradient_capacity_bytes * spills):
        raise PruneError(f"{label} cumulative gradient bytes are impossible.")
    peak_bytes = counters["peak_cpu_accumulator_bytes"]
    if validate_peak:
        if not (0 < peak_bytes <= gradient_capacity_bytes):
            raise PruneError(f"{label} peak CPU accumulator bytes are impossible.")
    elif peak_bytes > gradient_capacity_bytes:
        raise PruneError(f"{label} peak CPU accumulator delta is impossible.")


def validate_gradient_accumulation_offload_receipt_file(
    path: Path,
    *,
    receipt_path: str,
    expected_run_id: str,
    expected_source_sha256: str,
    expected_resume_signature: str,
    expected_initial_global_step: int,
    expected_final_global_step: int,
    expected_configured_accumulation_steps: int,
    expected_initial_resume_checkpoint: Mapping[str, Any] | None,
    expected_trainable_parameter_count: int,
    expected_trainable_parameter_total_numel: int,
) -> dict[str, Any]:
    """Deeply validate one completed v2 CPU accumulation-offload receipt."""

    if not isinstance(expected_run_id, str) or not expected_run_id:
        raise PruneError("Expected gradient-offload run_id is incomplete.")
    _validate_sha256(
        expected_source_sha256,
        label="expected gradient-offload source_sha256",
    )
    _validate_sha256(
        expected_resume_signature,
        label="expected gradient-offload resume_signature",
    )
    for expected_value, expected_label in (
        (expected_initial_global_step, "expected initial global step"),
        (expected_final_global_step, "expected final global step"),
        (
            expected_configured_accumulation_steps,
            "expected configured accumulation steps",
        ),
        (expected_trainable_parameter_count, "expected trainable parameter count"),
        (expected_trainable_parameter_total_numel, "expected trainable total numel"),
    ):
        _require_nonnegative_integer(expected_value, label=expected_label)
    relative = _safe_relative(receipt_path, label="gradient-offload receipt path")
    record = _regular_file_record(path, relative=relative)
    receipt = read_json(path)
    expected_top_keys = {
        "schema_version",
        "mode",
        "algorithm",
        "claim_boundary",
        "run_id",
        "source_sha256",
        "resume_signature",
        "configured_gradient_accumulation_steps",
        "initial_global_step",
        "last_observed_global_step",
        "last_restored_global_step",
        "final_global_step",
        "trainable_parameter_count",
        "trainable_parameter_total_numel",
        "trainable_gradient_capacity_bytes",
        "trainable_parameter_schema_sha256",
        "trainable_parameter_schema_fields",
        *GRADIENT_OFFLOAD_COUNTER_FIELDS,
        "live_cpu_buffer_count",
        "live_cpu_buffer_bytes",
        "active_window",
        "continuations",
        "segments",
        "status",
        "updated_at",
        "receipt_sha256",
    }
    _require_exact_keys(receipt, expected_top_keys, label="gradient-offload receipt")
    if (
        receipt.get("schema_version") != GRADIENT_OFFLOAD_SCHEMA_VERSION
        or receipt.get("mode") != GRADIENT_ACCUMULATION_OFFLOAD
        or receipt.get("algorithm") != GRADIENT_OFFLOAD_ALGORITHM
    ):
        raise PruneError("Gradient-offload receipt schema/mode/algorithm is unsupported.")
    boundary = _require_mapping(
        receipt.get("claim_boundary"), label="gradient-offload claim_boundary"
    )
    _require_exact_keys(
        boundary,
        {"execution_proof", "numerical_proof", "unsupported"},
        label="gradient-offload claim_boundary",
    )
    if any(not isinstance(value, str) or not value for value in boundary.values()):
        raise PruneError("Gradient-offload claim boundary is incomplete.")
    source_sha256 = _validate_sha256(
        receipt.get("source_sha256"), label="gradient-offload source_sha256"
    )
    resume_signature = _validate_sha256(
        receipt.get("resume_signature"), label="gradient-offload resume_signature"
    )
    if (
        receipt.get("run_id") != expected_run_id
        or source_sha256 != expected_source_sha256
        or resume_signature != expected_resume_signature
    ):
        raise PruneError("Gradient-offload run/source/resume binding is not exact.")
    configured = _require_nonnegative_integer(
        receipt.get("configured_gradient_accumulation_steps"),
        label="configured gradient accumulation steps",
    )
    if configured != expected_configured_accumulation_steps or configured < 2:
        raise PruneError("Gradient-offload accumulation-step binding is not exact.")
    initial_step = _require_nonnegative_integer(
        receipt.get("initial_global_step"), label="gradient-offload initial_global_step"
    )
    final_step = _require_nonnegative_integer(
        receipt.get("final_global_step"), label="gradient-offload final_global_step"
    )
    if (
        initial_step != expected_initial_global_step
        or final_step != expected_final_global_step
        or final_step <= initial_step
        or receipt.get("last_observed_global_step") != final_step
        or receipt.get("status") != "completed"
        or receipt.get("active_window") is not None
        or receipt.get("live_cpu_buffer_count") != 0
        or receipt.get("live_cpu_buffer_bytes") != 0
    ):
        raise PruneError("Gradient-offload terminal status/step/buffer state is invalid.")
    _require_nonnegative_number(receipt.get("updated_at"), label="gradient-offload updated_at")
    stored_self_hash = _validate_sha256(
        receipt.get("receipt_sha256"), label="gradient-offload receipt_sha256"
    )
    if stored_self_hash != gradient_accumulation_offload_receipt_self_hash(receipt):
        raise PruneError("Gradient-offload receipt self-hash mismatch.")

    parameter_count = _require_nonnegative_integer(
        receipt.get("trainable_parameter_count"), label="trainable parameter count"
    )
    total_numel = _require_nonnegative_integer(
        receipt.get("trainable_parameter_total_numel"), label="trainable total numel"
    )
    capacity_bytes = _require_nonnegative_integer(
        receipt.get("trainable_gradient_capacity_bytes"),
        label="trainable gradient capacity bytes",
    )
    if (
        not (0 < parameter_count <= total_numel <= capacity_bytes)
        or parameter_count != expected_trainable_parameter_count
        or total_numel != expected_trainable_parameter_total_numel
    ):
        raise PruneError("Gradient-offload trainable schema counts are not positive/plausible.")
    schema_sha256 = _validate_sha256(
        receipt.get("trainable_parameter_schema_sha256"),
        label="trainable parameter schema sha256",
    )
    if receipt.get("trainable_parameter_schema_fields") != list(
        GRADIENT_OFFLOAD_SCHEMA_FIELDS
    ):
        raise PruneError("Gradient-offload trainable schema fields are not exact.")
    counters = {
        field: _require_nonnegative_integer(
            receipt.get(field), label=f"gradient-offload {field}"
        )
        for field in GRADIENT_OFFLOAD_COUNTER_FIELDS
    }
    if counters["windows_started"] != final_step - initial_step:
        raise PruneError("Gradient-offload window count disagrees with the step range.")
    if counters["windows_restored"] < 1:
        raise PruneError("Gradient-offload receipt proves no restored multi-window.")
    _validate_gradient_offload_counter_equations(
        counters,
        label="gradient-offload cumulative counters",
        configured_accumulation_steps=configured,
        parameter_count=parameter_count,
        gradient_capacity_bytes=capacity_bytes,
    )
    last_restored = _require_nonnegative_integer(
        receipt.get("last_restored_global_step"),
        label="gradient-offload last_restored_global_step",
    )
    if not initial_step <= last_restored < final_step:
        raise PruneError("Gradient-offload last restored step is outside the run range.")
    if last_restored != final_step - 1:
        raise PruneError("Gradient-offload final window was not restored exactly.")

    raw_segments = receipt.get("segments")
    raw_continuations = receipt.get("continuations")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise PruneError("Gradient-offload receipt has no segments.")
    if not isinstance(raw_continuations, list) or len(raw_continuations) != len(
        raw_segments
    ) - 1:
        raise PruneError("Gradient-offload continuation/segment count is inconsistent.")
    zero_counters = {field: 0 for field in GRADIENT_OFFLOAD_COUNTER_FIELDS}
    segment_summaries: list[dict[str, Any]] = []
    previous_segment: Mapping[str, Any] | None = None
    for index, raw_segment in enumerate(raw_segments):
        segment = _require_mapping(raw_segment, label=f"gradient-offload segments[{index}]")
        expected_segment_keys = {
            "segment_index",
            "previous_receipt_sha256",
            "resume_checkpoint",
            "initial_global_step",
            "last_observed_global_step",
            "final_global_step",
            "initial_cumulative_counters",
            "latest_cumulative_counters",
            "final_cumulative_counters",
            "status",
        }
        if index < len(raw_segments) - 1:
            expected_segment_keys.add("terminal_checkpoint")
        _require_exact_keys(
            segment, expected_segment_keys, label=f"gradient-offload segments[{index}]"
        )
        segment_initial = _require_nonnegative_integer(
            segment.get("initial_global_step"),
            label=f"gradient-offload segments[{index}].initial_global_step",
        )
        segment_final = _require_nonnegative_integer(
            segment.get("final_global_step"),
            label=f"gradient-offload segments[{index}].final_global_step",
        )
        expected_status = "completed" if index == len(raw_segments) - 1 else "preempted"
        if (
            segment.get("segment_index") != index
            or segment.get("status") != expected_status
            or segment.get("last_observed_global_step") != segment_final
            or segment_final <= segment_initial
        ):
            raise PruneError(f"Gradient-offload segment {index} terminal state is invalid.")
        initial_counters = _gradient_offload_counter_snapshot(
            segment.get("initial_cumulative_counters"),
            label=f"gradient-offload segments[{index}].initial counters",
        )
        latest_counters = _gradient_offload_counter_snapshot(
            segment.get("latest_cumulative_counters"),
            label=f"gradient-offload segments[{index}].latest counters",
        )
        final_counters = _gradient_offload_counter_snapshot(
            segment.get("final_cumulative_counters"),
            label=f"gradient-offload segments[{index}].final counters",
        )
        if latest_counters != final_counters or any(
            final_counters[field] < initial_counters[field]
            for field in GRADIENT_OFFLOAD_COUNTER_FIELDS
        ):
            raise PruneError(f"Gradient-offload segment {index} counters moved backwards.")
        counter_delta = {
            field: final_counters[field] - initial_counters[field]
            for field in GRADIENT_OFFLOAD_COUNTER_FIELDS
        }
        if counter_delta["windows_started"] != segment_final - segment_initial:
            raise PruneError(f"Gradient-offload segment {index} step/window delta differs.")
        _validate_gradient_offload_counter_equations(
            counter_delta,
            label=f"gradient-offload segment {index} counter delta",
            configured_accumulation_steps=configured,
            parameter_count=parameter_count,
            gradient_capacity_bytes=capacity_bytes,
            validate_peak=False,
        )
        resume_checkpoint = segment.get("resume_checkpoint")
        if index == 0:
            if segment.get("previous_receipt_sha256") is not None:
                raise PruneError("Gradient-offload first segment has a previous receipt hash.")
            if initial_counters != zero_counters:
                raise PruneError("Gradient-offload first segment counters do not start at zero.")
            if expected_initial_resume_checkpoint is None:
                if resume_checkpoint is not None:
                    raise PruneError("Gradient-offload first segment unexpectedly resumed.")
            else:
                observed_checkpoint = _gradient_offload_checkpoint_descriptor(
                    resume_checkpoint,
                    label="gradient-offload initial resume checkpoint",
                    expected_run_id=expected_run_id,
                    expected_step=segment_initial,
                    expected_source_sha256=expected_source_sha256,
                    expected_resume_signature=expected_resume_signature,
                    required_scope="external",
                )
                if observed_checkpoint != dict(expected_initial_resume_checkpoint):
                    raise PruneError("Gradient-offload initial resume descriptor differs.")
        else:
            assert previous_segment is not None
            continuation = _require_mapping(
                raw_continuations[index - 1],
                label=f"gradient-offload continuations[{index - 1}]",
            )
            _require_exact_keys(
                continuation,
                {
                    "event",
                    "previous_segment_index",
                    "next_segment_index",
                    "previous_receipt_sha256",
                    "checkpoint",
                    "global_step",
                    "previous_cumulative_counters",
                    "continued_at",
                },
                label=f"gradient-offload continuations[{index - 1}]",
            )
            previous_hash = _validate_sha256(
                continuation.get("previous_receipt_sha256"),
                label=f"gradient-offload continuations[{index - 1}].previous hash",
            )
            checkpoint = _gradient_offload_checkpoint_descriptor(
                continuation.get("checkpoint"),
                label=f"gradient-offload continuations[{index - 1}].checkpoint",
                expected_run_id=expected_run_id,
                expected_step=segment_initial,
                expected_source_sha256=expected_source_sha256,
                expected_resume_signature=expected_resume_signature,
                required_scope="output_dir",
            )
            _require_nonnegative_number(
                continuation.get("continued_at"),
                label=f"gradient-offload continuations[{index - 1}].continued_at",
            )
            if (
                continuation.get("event") != "resume_continuation"
                or continuation.get("previous_segment_index") != index - 1
                or continuation.get("next_segment_index") != index
                or continuation.get("global_step") != segment_initial
                or continuation.get("previous_cumulative_counters")
                != previous_segment.get("final_cumulative_counters")
                or segment.get("previous_receipt_sha256") != previous_hash
                or segment.get("resume_checkpoint") != checkpoint
                or segment_initial != previous_segment.get("final_global_step")
                or initial_counters != previous_segment.get("final_cumulative_counters")
                or previous_segment.get("terminal_checkpoint") != checkpoint
            ):
                raise PruneError(f"Gradient-offload continuation {index - 1} is broken.")
        segment_summaries.append(
            {
                "segment_index": index,
                "status": expected_status,
                "initial_global_step": segment_initial,
                "final_global_step": segment_final,
            }
        )
        previous_segment = segment
    if (
        raw_segments[0].get("initial_global_step") != initial_step
        or raw_segments[-1].get("final_global_step") != final_step
        or raw_segments[-1].get("final_cumulative_counters") != counters
    ):
        raise PruneError("Gradient-offload root/segment terminal bindings differ.")

    return {
        "passed": True,
        **record,
        "receipt_sha256": stored_self_hash,
        "schema_version": GRADIENT_OFFLOAD_SCHEMA_VERSION,
        "mode": GRADIENT_ACCUMULATION_OFFLOAD,
        "algorithm": GRADIENT_OFFLOAD_ALGORITHM,
        "run_id": expected_run_id,
        "source_sha256": expected_source_sha256,
        "resume_signature": expected_resume_signature,
        "configured_gradient_accumulation_steps": configured,
        "initial_global_step": initial_step,
        "final_global_step": final_step,
        "initial_resume_checkpoint": (
            dict(expected_initial_resume_checkpoint)
            if expected_initial_resume_checkpoint is not None
            else None
        ),
        "trainable_parameter_count": parameter_count,
        "trainable_parameter_total_numel": total_numel,
        "trainable_gradient_capacity_bytes": capacity_bytes,
        "trainable_parameter_schema_sha256": schema_sha256,
        "trainable_parameter_schema_fields": list(GRADIENT_OFFLOAD_SCHEMA_FIELDS),
        "counters": counters,
        "optimizer_coverage_binding": {
            "model_trainable_unique_physical_parameters": parameter_count,
            "model_trainable_numel": total_numel,
        },
        "skip_free_windows": True,
        "continuation_chain": {
            "passed": True,
            "segment_count": len(raw_segments),
            "continuation_count": len(raw_continuations),
            "same_output_continuation_observed": bool(raw_continuations),
            "segments": segment_summaries,
        },
        "status": "completed",
    }


def _records_by_path(
    records: Sequence[Mapping[str, Any]],
    *,
    label: str,
) -> dict[str, Mapping[str, Any]]:
    result = {str(record["path"]): record for record in records}
    if len(result) != len(records):
        raise PruneError(f"{label} contains duplicate artifact paths.")
    return result


def _derive_required_assays(launched: Mapping[str, Any]) -> list[str]:
    assays = _require_mapping(launched.get("assays"), label="LAUNCHED_CONFIG.assays")
    amputation = assays.get("amputation_eval")
    if not isinstance(amputation, bool):
        raise PruneError("LAUNCHED_CONFIG assays.amputation_eval must be a boolean.")
    required = ["heldout_eval"]
    if amputation:
        required.append("amputation")
    for section in ("necessity", "choice_eval", "recruitment"):
        settings = _require_mapping(
            assays.get(section), label=f"LAUNCHED_CONFIG.assays.{section}"
        )
        enabled = settings.get("enabled")
        if not isinstance(enabled, bool):
            raise PruneError(
                f"LAUNCHED_CONFIG assays.{section}.enabled must be a boolean."
            )
        if enabled:
            required.append(section)
    return required


def _validate_assay_receipt(
    run_dir: Path,
    assay: Mapping[str, Any],
    *,
    provenance: Mapping[str, Any],
) -> list[dict[str, Any]]:
    run_id = provenance.get("run_id")
    if (
        assay.get("format") != ASSAY_VERIFICATION_FORMAT
        or assay.get("verified") is not True
        or assay.get("run_id") != run_id
        or assay.get("provenance") != provenance
    ):
        raise PruneError("ASSAY_VERIFICATION.json is incomplete or provenance-mismatched.")

    artifacts = _validate_receipt_artifacts(
        run_dir, assay, receipt_name=ASSAY_VERIFICATION_NAME
    )
    artifacts_by_path = _records_by_path(
        artifacts, label=f"{ASSAY_VERIFICATION_NAME} artifacts"
    )
    launched_path = run_dir / LAUNCHED_CONFIG_NAME
    launched_record = _regular_file_record(
        launched_path, relative=LAUNCHED_CONFIG_NAME
    )
    launched = read_json(launched_path)
    hashes = _require_mapping(provenance.get("hashes"), label="provenance.hashes")
    if hashes.get("materialized_config_sha256") != launched_record["sha256"]:
        raise PruneError("LAUNCHED_CONFIG hash disagrees with RUN_VERIFICATION provenance.")
    expected_assays = _derive_required_assays(launched)
    if assay.get("required_assays") != expected_assays:
        raise PruneError("ASSAY_VERIFICATION required assays differ from LAUNCHED_CONFIG.")
    if assay.get("completed_assays") != expected_assays:
        raise PruneError("ASSAY_VERIFICATION completed assays are not exact and ordered.")

    expected_artifact_paths = {
        RUN_VERIFICATION_NAME,
        LAUNCHED_CONFIG_NAME,
        METRICS_NAME,
    }
    if "amputation" in expected_assays:
        expected_artifact_paths.add(AMPUTATION_REPORT_NAME)
    expected_artifact_paths.update(
        EXTERNAL_ASSAY_RESULTS[name]
        for name in expected_assays
        if name in EXTERNAL_ASSAY_RESULTS
    )
    if set(artifacts_by_path) != expected_artifact_paths:
        raise PruneError(
            "ASSAY_VERIFICATION artifact paths do not exactly cover the configured assays."
        )
    if artifacts_by_path[LAUNCHED_CONFIG_NAME] != launched_record:
        raise PruneError("ASSAY_VERIFICATION does not exactly bind LAUNCHED_CONFIG.json.")

    verification_sha256 = sha256_file(run_dir / RUN_VERIFICATION_NAME)
    metrics_sha256 = sha256_file(run_dir / METRICS_NAME)
    manifest = read_json(run_dir / "final" / "manifest.json")
    engine_run_id = manifest.get("run_id")
    global_step = manifest.get("global_step")
    if not isinstance(engine_run_id, str) or not engine_run_id:
        raise PruneError("Final manifest has no engine run_id for assay binding.")
    if (
        isinstance(global_step, bool)
        or not isinstance(global_step, int)
        or global_step < 1
        or global_step != provenance.get("max_steps")
    ):
        raise PruneError("Final manifest global_step is not exact for assay binding.")
    expected_inputs = {
        "run_verification_sha256": verification_sha256,
        "launched_config_sha256": launched_record["sha256"],
        "metrics_sha256": metrics_sha256,
        "engine_run_id": engine_run_id,
        "global_step": global_step,
    }
    if assay.get("input_bindings") != expected_inputs:
        raise PruneError("ASSAY_VERIFICATION input bindings are not exact.")
    if artifacts_by_path[RUN_VERIFICATION_NAME]["sha256"] != verification_sha256:
        raise PruneError("ASSAY_VERIFICATION RUN_VERIFICATION artifact hash is not exact.")
    if artifacts_by_path[METRICS_NAME]["sha256"] != metrics_sha256:
        raise PruneError("ASSAY_VERIFICATION metrics artifact hash is not exact.")

    integrity = _require_mapping(
        assay.get("execution_integrity"), label="ASSAY_VERIFICATION execution_integrity"
    )
    _require_exact_keys(
        integrity,
        {"status", "required_equals_completed", "assays"},
        label="ASSAY_VERIFICATION execution_integrity",
    )
    results = _require_mapping(
        integrity.get("assays"), label="ASSAY_VERIFICATION execution assays"
    )
    if (
        integrity.get("status") != "PASS"
        or integrity.get("required_equals_completed") is not True
        or set(results) != set(expected_assays)
    ):
        raise PruneError("ASSAY_VERIFICATION execution-integrity gates are not exact.")
    for name in expected_assays:
        result = _require_mapping(results.get(name), label=f"assay result {name}")
        if result.get("execution_integrity") != "PASS":
            raise PruneError(f"Assay {name} has no exact execution-integrity PASS.")
        if name in EXTERNAL_ASSAY_RESULTS:
            if (
                result.get("artifact") != EXTERNAL_ASSAY_RESULTS[name]
                or result.get("format") not in EXTERNAL_ASSAY_FORMATS[name]
            ):
                raise PruneError(f"Assay {name} external artifact binding is unsupported.")
        else:
            evidence = _require_mapping(
                result.get("evidence"), label=f"assay result {name}.evidence"
            )
            if (
                evidence.get("artifact") != METRICS_NAME
                or evidence.get("step") != global_step
            ):
                raise PruneError(f"Assay {name} metric evidence is not exact.")
            _validate_sha256(
                evidence.get("record_sha256"), label=f"assay result {name} record sha256"
            )
            line = evidence.get("jsonl_line")
            if isinstance(line, bool) or not isinstance(line, int) or line < 1:
                raise PruneError(f"Assay {name} has no positive metrics line number.")
            _require_nonnegative_number(
                evidence.get("task_loss"), label=f"assay result {name} task_loss"
            )

    scientific = _require_mapping(
        assay.get("scientific_direction"), label="ASSAY_VERIFICATION scientific_direction"
    )
    _require_exact_keys(
        scientific,
        {"authoritative", "not_an_integrity_gate", "by_assay"},
        label="ASSAY_VERIFICATION scientific_direction",
    )
    directions = _require_mapping(
        scientific.get("by_assay"), label="ASSAY_VERIFICATION scientific directions"
    )
    if (
        scientific.get("authoritative") is not False
        or scientific.get("not_an_integrity_gate") is not True
        or set(directions) != set(expected_assays)
        or any(not isinstance(value, str) or not value for value in directions.values())
    ):
        raise PruneError("ASSAY_VERIFICATION scientific-direction boundary is malformed.")
    return artifacts


def _validate_exact_resume_comparisons(
    comparisons: Mapping[str, Any],
    *,
    split_step: int,
) -> None:
    _require_exact_keys(
        comparisons,
        {"passed", "base", "workspace", "trainer", "metrics", "resume_event", "elapsed_seconds"},
        label="resume equivalence comparisons",
    )
    if comparisons.get("passed") is not True:
        raise PruneError("Resume equivalence detailed comparisons did not pass.")
    _require_nonnegative_number(
        comparisons.get("elapsed_seconds"), label="resume comparison elapsed_seconds"
    )

    pair_keys = {"save_non_perturbation_A_B", "resume_B_C"}
    base = _require_mapping(comparisons.get("base"), label="resume base comparisons")
    workspace = _require_mapping(
        comparisons.get("workspace"), label="resume workspace comparisons"
    )
    trainer = _require_mapping(
        comparisons.get("trainer"), label="resume trainer comparisons"
    )
    for group_name, group in (
        ("base", base),
        ("workspace", workspace),
        ("trainer", trainer),
    ):
        if set(group) != pair_keys:
            raise PruneError(f"Resume {group_name} comparison keys are not exact.")

    for name, result_raw in base.items():
        result = _require_mapping(result_raw, label=f"resume base comparison {name}")
        for key in ("tensor_count", "total_numel"):
            value = result.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise PruneError(f"Resume base comparison {name} has invalid {key}.")
        if (
            result.get("bitwise_exact") is not True
            or result.get("changed_tensor_count") != 0
            or result.get("changed_element_count") != 0
        ):
            raise PruneError(f"Resume base comparison {name} is not bitwise exact.")
        _validate_sha256(
            result.get("tensor_schema_sha256"),
            label=f"resume base comparison {name} tensor schema sha256",
        )

    for name, result_raw in workspace.items():
        result = _require_mapping(result_raw, label=f"resume workspace comparison {name}")
        if result.get("exact") is not True:
            raise PruneError(f"Resume workspace comparison {name} is not exact.")
        for side in ("left_sha256", "right_sha256"):
            _validate_sha256(result.get(side), label=f"resume workspace {name} {side}")

    trainer_expectations = {
        "save_non_perturbation_A_B": (True, None),
        "resume_B_C": (False, True),
    }
    for name, result_raw in trainer.items():
        result = _require_mapping(result_raw, label=f"resume trainer comparison {name}")
        independent, run_id_preserved = trainer_expectations[name]
        if (
            result.get("exact") is not True
            or result.get("independent_runs") is not independent
            or result.get("run_id_preserved") is not run_id_preserved
        ):
            raise PruneError(f"Resume trainer comparison {name} is not exact.")
        for side in ("left_sha256", "right_sha256"):
            _validate_sha256(result.get(side), label=f"resume trainer {name} {side}")

    metrics = _require_mapping(comparisons.get("metrics"), label="resume metric comparisons")
    expected_metrics = {"train_A_B", "train_B_C", "final_A_B", "final_B_C"}
    if set(metrics) != expected_metrics:
        raise PruneError("Resume metric comparison keys are not exact.")
    for name, result_raw in metrics.items():
        result = _require_mapping(result_raw, label=f"resume metric comparison {name}")
        record_count = result.get("record_count")
        if (
            result.get("exact") is not True
            or isinstance(record_count, bool)
            or not isinstance(record_count, int)
            or record_count < 1
        ):
            raise PruneError(f"Resume metric comparison {name} is not exact.")

    resume_event = _require_mapping(
        comparisons.get("resume_event"), label="resume event comparison"
    )
    if (
        resume_event.get("step") != split_step
        or resume_event.get("run_id_preserved") is not True
    ):
        raise PruneError("Resume event does not prove exact checkpoint continuity.")


def _validate_published_resume_environment(
    run_dir: Path,
    *,
    name: str,
    local_name: str,
    expected_child_root: str,
    artifact_record: Mapping[str, Any],
    binding: Mapping[str, Any],
    expected_configured: Any,
    expected_source_sha256: Any,
) -> None:
    """Recompute one published child environment binding from retained bytes."""

    expected_source = _validate_sha256(
        expected_source_sha256,
        label=f"resume {name} expected engine source sha256",
    )
    expected_child_root = _safe_relative(
        expected_child_root, label=f"resume {name} output"
    )
    expected_binding_path = f"{expected_child_root}/{ENVIRONMENT_NAME}"
    binding_path = _safe_relative(
        binding.get("path"), label=f"resume {name} allocator environment path"
    )
    if binding_path != expected_binding_path:
        raise PruneError(
            f"Resume {name} allocator environment path is not canonical."
        )

    _require_exact_keys(
        binding,
        {
            "path",
            "sha256",
            "configured",
            "observed_primary",
            "observed_legacy_alias",
            "observed_hip_legacy_alias",
            "observed_caching_allocator_disable",
            "active_backend",
            "parsed_settings",
            "snapshot_settings",
            "allocator_initialized",
            "cuda_memory_allocated_bytes",
            "cuda_memory_reserved_bytes",
            "runtime_identity",
            "checks",
            "passed",
        },
        label=f"resume {name} allocator binding",
    )
    local_path = _safe_join(
        run_dir, local_name, label=f"resume {name} published environment"
    )
    actual_record = _regular_file_record(local_path, relative=local_name)
    if actual_record != dict(artifact_record):
        raise PruneError(
            f"Resume {name} published environment artifact record is not exact."
        )
    if binding.get("sha256") != actual_record["sha256"]:
        raise PruneError(
            f"Resume {name} published environment hash disagrees with its binding."
        )

    environment = read_json(local_path)
    runtime_identity_keys = {
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
    }
    runtime_identity = _require_mapping(
        binding.get("runtime_identity"),
        label=f"resume {name} runtime identity",
    )
    _require_exact_keys(
        runtime_identity,
        runtime_identity_keys,
        label=f"resume {name} runtime identity",
    )
    environment_snapshot = _require_mapping(
        environment.get("allocator_snapshot_settings"),
        label=f"resume {name} published allocator snapshot",
    )
    binding_snapshot = _require_mapping(
        binding.get("snapshot_settings"),
        label=f"resume {name} allocator snapshot binding",
    )
    allocated = environment.get("cuda_memory_allocated_bytes")
    runtime_complete = (
        runtime_identity_keys.issubset(environment)
        and all(
            environment.get(key) is not None
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
        and isinstance(environment.get("cuda_devices"), list)
        and len(environment["cuda_devices"]) > 0
    )
    recomputed_checks = {
        "configured_policy_exact": binding.get("configured") == expected_configured,
        "primary_environment_exact": (
            environment.get("pytorch_alloc_conf") == expected_configured
        ),
        "legacy_alias_absent": (
            "pytorch_cuda_alloc_conf_legacy" in environment
            and environment.get("pytorch_cuda_alloc_conf_legacy") is None
        ),
        "hip_legacy_alias_absent": (
            "pytorch_hip_alloc_conf_legacy" in environment
            and environment.get("pytorch_hip_alloc_conf_legacy") is None
        ),
        "caching_allocator_enabled": (
            "pytorch_no_cuda_memory_caching" in environment
            and environment.get("pytorch_no_cuda_memory_caching") is None
        ),
        "native_backend_reported": environment.get("allocator_backend") == "native",
        "parsed_settings_roundtrip_exact": (
            environment.get("allocator_settings") == expected_configured
        ),
        "snapshot_expandable_segments_enabled": (
            environment_snapshot.get("expandable_segments") is True
        ),
        "allocator_initialized": environment.get("allocator_initialized") is True,
        "live_cuda_allocation_observed": (
            isinstance(allocated, int)
            and not isinstance(allocated, bool)
            and allocated > 0
        ),
        "runtime_identity_complete": runtime_complete,
        "source_identity_exact": environment.get("source_sha256") == expected_source,
    }
    recorded_checks = _require_mapping(
        binding.get("checks"), label=f"resume {name} allocator checks"
    )
    _require_exact_keys(
        recorded_checks,
        set(recomputed_checks),
        label=f"resume {name} allocator checks",
    )

    content_bindings = {
        "observed_primary": environment.get("pytorch_alloc_conf"),
        "observed_legacy_alias": environment.get(
            "pytorch_cuda_alloc_conf_legacy"
        ),
        "observed_hip_legacy_alias": environment.get(
            "pytorch_hip_alloc_conf_legacy"
        ),
        "observed_caching_allocator_disable": environment.get(
            "pytorch_no_cuda_memory_caching"
        ),
        "active_backend": environment.get("allocator_backend"),
        "parsed_settings": environment.get("allocator_settings"),
        "snapshot_settings": dict(environment_snapshot),
        "allocator_initialized": environment.get("allocator_initialized"),
        "cuda_memory_allocated_bytes": allocated,
        "cuda_memory_reserved_bytes": environment.get(
            "cuda_memory_reserved_bytes"
        ),
        "runtime_identity": {
            key: environment.get(key) for key in runtime_identity_keys
        },
    }
    if (
        binding.get("passed") is not True
        or dict(recorded_checks) != recomputed_checks
        or not all(recomputed_checks.values())
        or dict(binding_snapshot) != dict(environment_snapshot)
        or any(binding.get(key) != value for key, value in content_bindings.items())
        or runtime_identity.get("source_sha256") != expected_source
    ):
        raise PruneError(
            f"Resume {name} published allocator environment is inconsistent."
        )


def _validate_resume_equivalence(
    run_dir: Path,
    equivalence: Mapping[str, Any],
    *,
    provenance: Mapping[str, Any],
    verification_sha256: str,
    published_artifacts: Sequence[Mapping[str, Any]],
) -> None:
    if (
        equivalence.get("format") != RESUME_EQUIVALENCE_FORMAT
        or equivalence.get("passed") is not True
    ):
        raise PruneError("Resume equivalence artifact is unsupported or did not pass.")
    design = _require_mapping(equivalence.get("design"), label="resume equivalence design")
    _require_exact_keys(
        design,
        {
            "baseline_A",
            "control_B",
            "resumed_C",
            "split_step",
            "total_steps",
            "scheduler_horizon_held_fixed",
            "comparison",
        },
        label="resume equivalence design",
    )
    split_step = design.get("split_step")
    total_steps = design.get("total_steps")
    if (
        design.get("baseline_A") != provenance.get("output_dir")
        or design.get("comparison") != "bitwise_exact_zero_tolerance"
        or design.get("scheduler_horizon_held_fixed") is not True
        or isinstance(split_step, bool)
        or not isinstance(split_step, int)
        or isinstance(total_steps, bool)
        or not isinstance(total_steps, int)
        or total_steps != provenance.get("max_steps")
        or not 0 < split_step < total_steps
    ):
        raise PruneError("Resume equivalence design is not exact for this run.")
    control_output = _safe_relative(
        design.get("control_B"), label="resume control output"
    )
    resumed_output = _safe_relative(
        design.get("resumed_C"), label="resume resumed output"
    )

    input_bindings = _require_mapping(
        equivalence.get("input_bindings"), label="resume equivalence input_bindings"
    )
    _require_exact_keys(
        input_bindings,
        {
            "baseline_RUN_VERIFICATION_sha256",
            "baseline_LAUNCHED_CONFIG_sha256",
            "control_config_sha256",
            "resumed_config_sha256",
            "checkpoint_resume_signature",
            "validated_baseline_provenance_hashes",
        },
        label="resume equivalence input_bindings",
    )
    launched_sha256 = sha256_file(run_dir / LAUNCHED_CONFIG_NAME)
    hashes = _require_mapping(provenance.get("hashes"), label="provenance.hashes")
    checkpoint_signature = input_bindings.get("checkpoint_resume_signature")
    if (
        input_bindings.get("baseline_RUN_VERIFICATION_sha256") != verification_sha256
        or input_bindings.get("baseline_LAUNCHED_CONFIG_sha256") != launched_sha256
        or input_bindings.get("validated_baseline_provenance_hashes") != hashes
        or not isinstance(checkpoint_signature, str)
        or not checkpoint_signature
    ):
        raise PruneError("Resume equivalence input bindings are not exact for this run.")
    _validate_sha256(input_bindings.get("control_config_sha256"), label="control config sha256")
    _validate_sha256(input_bindings.get("resumed_config_sha256"), label="resumed config sha256")

    inventories = _require_mapping(
        equivalence.get("artifact_inventories"), label="resume artifact inventories"
    )
    inventory_keys = {"checkpoint_B_split", "final_A", "final_B", "final_C"}
    _require_exact_keys(inventories, inventory_keys, label="resume artifact inventories")
    normalized_inventories = {
        name: _validate_inventory_records(raw, label=f"resume inventory {name}")
        for name, raw in inventories.items()
    }
    checkpoint_inventory = normalized_inventories["checkpoint_B_split"]
    checkpoint_manifest_records = [
        record for record in checkpoint_inventory if record["path"] == "manifest.json"
    ]
    if len(checkpoint_manifest_records) != 1:
        raise PruneError("Resume split-checkpoint inventory has no unique manifest.")
    checkpoint_descriptor_inventory = gradient_offload_inventory_identity(
        checkpoint_inventory
    )
    checkpoint_descriptor_inventory["manifest_sha256"] = (
        checkpoint_manifest_records[0]["sha256"]
    )
    verification = read_json(run_dir / RUN_VERIFICATION_NAME)
    expected_final = _validate_inventory_records(
        verification.get("final_inventory"), label="RUN_VERIFICATION final_inventory"
    )
    if normalized_inventories["final_A"] != expected_final:
        raise PruneError("Resume equivalence final_A inventory is not this verified run.")

    bundle_identity_bindings = _require_mapping(
        equivalence.get("bundle_identity_bindings"),
        label="resume bundle identity bindings",
    )
    _require_exact_keys(
        bundle_identity_bindings,
        {
            "passed",
            "bundles",
            "exact_cross_run_fields",
            "semantic_identities",
            "all_semantic_identities_equal",
            "control_resume_run_id_preserved",
        },
        label="resume bundle identity bindings",
    )
    recorded_bundles = _require_mapping(
        bundle_identity_bindings.get("bundles"),
        label="resume bundle identities",
    )
    _require_exact_keys(
        recorded_bundles,
        {"baseline", "control", "resumed"},
        label="resume bundle identities",
    )
    expected_bundle_paths = {
        "baseline": f"{provenance['output_dir']}/final",
        "control": f"{control_output}/final",
        "resumed": f"{resumed_output}/final",
    }
    expected_bundle_inventories = {
        "baseline": normalized_inventories["final_A"],
        "control": normalized_inventories["final_B"],
        "resumed": normalized_inventories["final_C"],
    }
    validated_bundles = {
        name: validate_bundle_identity_summary(
            recorded_bundles.get(name),
            expected_bundle_path=expected_bundle_paths[name],
            expected_global_step=total_steps,
            expected_inventory=expected_bundle_inventories[name],
        )
        for name in ("baseline", "control", "resumed")
    }
    baseline_bundle_identity = _require_mapping(
        verification.get("bundle_identity"),
        label="RUN_VERIFICATION bundle identity",
    )
    expected_baseline_identity = dict(validated_bundles["baseline"])
    expected_baseline_identity["bundle_path"] = "final"
    if dict(baseline_bundle_identity) != expected_baseline_identity:
        raise PruneError("Resume baseline bundle identity is not this verified run.")
    bundle_cross_run_fields = (
        "resume_signature",
        "structural_resume_signature",
        "world_size",
        "data_fingerprint_sha256",
    )
    bundle_semantic_identities = {
        name: {
            field: binding.get(field) for field in bundle_cross_run_fields
        }
        for name, binding in validated_bundles.items()
    }
    if (
        bundle_identity_bindings.get("passed") is not True
        or bundle_identity_bindings.get("exact_cross_run_fields")
        != list(bundle_cross_run_fields)
        or bundle_identity_bindings.get("semantic_identities")
        != bundle_semantic_identities
        or bundle_identity_bindings.get("all_semantic_identities_equal") is not True
        or bundle_identity_bindings.get("control_resume_run_id_preserved") is not True
        or not (
            bundle_semantic_identities["baseline"]
            == bundle_semantic_identities["control"]
            == bundle_semantic_identities["resumed"]
        )
        or validated_bundles["control"].get("run_id")
        != validated_bundles["resumed"].get("run_id")
        or checkpoint_signature
        != validated_bundles["control"].get("resume_signature")
    ):
        raise PruneError("Resume A/B/C bundle identity chain is not exact.")

    allocator_bindings = _require_mapping(
        equivalence.get("allocator_environment_bindings"),
        label="resume allocator environment bindings",
    )
    _require_exact_keys(
        allocator_bindings,
        {"control", "resumed"},
        label="resume allocator environment bindings",
    )
    artifacts_by_path = {str(item["path"]): item for item in published_artifacts}
    if set(artifacts_by_path) != {
        RESUME_EQUIVALENCE_NAME,
        RESUME_CONTROL_ENVIRONMENT_NAME,
        RESUME_RESUMED_ENVIRONMENT_NAME,
        RESUME_CONTROL_GRADIENT_OFFLOAD_NAME,
        RESUME_RESUMED_GRADIENT_OFFLOAD_NAME,
    }:
        raise PruneError("Resume published artifact set is not exact.")
    expected_environment_artifacts = {
        "control": RESUME_CONTROL_ENVIRONMENT_NAME,
        "resumed": RESUME_RESUMED_ENVIRONMENT_NAME,
    }
    expected_gradient_offload_artifacts = {
        "control": RESUME_CONTROL_GRADIENT_OFFLOAD_NAME,
        "resumed": RESUME_RESUMED_GRADIENT_OFFLOAD_NAME,
    }
    expected_engine_source = _require_mapping(
        _require_mapping(provenance.get("hashes"), label="provenance hashes").get(
            "source_files_sha256"
        ),
        label="provenance source files",
    ).get("src/latent_workspace_ft_v10/engine.py")
    launched = read_json(run_dir / LAUNCHED_CONFIG_NAME)
    train = _require_mapping(
        launched.get("train"), label="LAUNCHED_CONFIG train"
    )
    accumulation_offload = _require_mapping(
        equivalence.get("gradient_accumulation_offload_binding"),
        label="resume gradient-accumulation offload binding",
    )
    expected_accumulation_offload = {
        "passed": True,
        "required": GRADIENT_ACCUMULATION_OFFLOAD,
        "all_equal": True,
        "observed": {
            "baseline": GRADIENT_ACCUMULATION_OFFLOAD,
            "control": GRADIENT_ACCUMULATION_OFFLOAD,
            "resumed": GRADIENT_ACCUMULATION_OFFLOAD,
        },
    }
    if (
        train.get("gradient_accumulation_offload")
        != GRADIENT_ACCUMULATION_OFFLOAD
        or dict(accumulation_offload) != expected_accumulation_offload
    ):
        raise PruneError(
            "Resume gradient-accumulation offload binding is not exact."
        )

    receipt_bindings = _require_mapping(
        equivalence.get("gradient_accumulation_offload_receipt_bindings"),
        label="resume gradient-offload receipt bindings",
    )
    _require_exact_keys(
        receipt_bindings,
        {
            "passed",
            "receipts",
            "expected_step_ranges",
            "exact_semantic_fields",
            "semantic_identities",
            "all_semantic_identities_equal",
            "control_resume_run_id_preserved",
        },
        label="resume gradient-offload receipt bindings",
    )
    recorded_receipts = _require_mapping(
        receipt_bindings.get("receipts"),
        label="resume gradient-offload receipts",
    )
    _require_exact_keys(
        recorded_receipts,
        {"baseline", "control", "resumed"},
        label="resume gradient-offload receipts",
    )
    baseline_gradient_offload = _require_mapping(
        verification.get("gradient_accumulation_offload"),
        label="baseline gradient-offload binding",
    )
    if dict(recorded_receipts["baseline"]) != dict(baseline_gradient_offload):
        raise PruneError("Resume baseline gradient-offload receipt is not this run.")
    accumulation_steps = train.get("gradient_accumulation_steps")
    baseline_parameter_count = baseline_gradient_offload.get(
        "trainable_parameter_count"
    )
    baseline_parameter_numel = baseline_gradient_offload.get(
        "trainable_parameter_total_numel"
    )
    if (
        isinstance(accumulation_steps, bool)
        or not isinstance(accumulation_steps, int)
        or isinstance(baseline_parameter_count, bool)
        or not isinstance(baseline_parameter_count, int)
        or isinstance(baseline_parameter_numel, bool)
        or not isinstance(baseline_parameter_numel, int)
    ):
        raise PruneError("Resume gradient-offload schema/config binding is invalid.")
    expected_ranges = {
        "baseline": {"initial_global_step": 0, "final_global_step": total_steps},
        "control": {"initial_global_step": 0, "final_global_step": total_steps},
        "resumed": {
            "initial_global_step": split_step,
            "final_global_step": total_steps,
        },
    }
    expected_receipt_paths = {
        "control": f"{control_output}/{GRADIENT_ACCUMULATION_OFFLOAD_RECEIPT_NAME}",
        "resumed": f"{resumed_output}/{GRADIENT_ACCUMULATION_OFFLOAD_RECEIPT_NAME}",
    }
    recomputed_receipts: dict[str, Mapping[str, Any]] = {
        "baseline": baseline_gradient_offload
    }
    for name in ("control", "resumed"):
        recorded = _require_mapping(
            recorded_receipts.get(name),
            label=f"resume {name} gradient-offload binding",
        )
        local_name = expected_gradient_offload_artifacts[name]
        artifact_record = artifacts_by_path.get(local_name)
        if not isinstance(artifact_record, Mapping):
            raise PruneError(
                f"Resume {name} published gradient-offload artifact is missing."
            )
        actual_record = _regular_file_record(
            run_dir / local_name,
            relative=local_name,
        )
        if (
            dict(artifact_record) != actual_record
            or recorded.get("bytes") != actual_record["bytes"]
            or recorded.get("sha256") != actual_record["sha256"]
            or recorded.get("path") != expected_receipt_paths[name]
        ):
            raise PruneError(
                f"Resume {name} published gradient-offload path/hash is not exact."
            )
        initial_checkpoint = (
            _require_mapping(
                recorded.get("initial_resume_checkpoint"),
                label="resume resumed initial checkpoint descriptor",
            )
            if name == "resumed"
            else None
        )
        recorded_run_id = recorded.get("run_id")
        if not isinstance(recorded_run_id, str) or not recorded_run_id:
            raise PruneError(
                f"Resume {name} gradient-offload run_id is incomplete."
            )
        recomputed = validate_gradient_accumulation_offload_receipt_file(
            run_dir / local_name,
            receipt_path=expected_receipt_paths[name],
            expected_run_id=recorded_run_id,
            expected_source_sha256=_validate_sha256(
                expected_engine_source,
                label="resume gradient-offload engine source sha256",
            ),
            expected_resume_signature=_validate_sha256(
                checkpoint_signature,
                label="resume checkpoint resume_signature",
            ),
            expected_initial_global_step=(0 if name == "control" else split_step),
            expected_final_global_step=total_steps,
            expected_configured_accumulation_steps=accumulation_steps,
            expected_initial_resume_checkpoint=initial_checkpoint,
            expected_trainable_parameter_count=baseline_parameter_count,
            expected_trainable_parameter_total_numel=baseline_parameter_numel,
        )
        if recomputed != dict(recorded):
            raise PruneError(
                f"Resume {name} gradient-offload receipt summary differs."
            )
        if name == "resumed":
            descriptor = _require_mapping(
                recomputed.get("initial_resume_checkpoint"),
                label="resumed gradient-offload checkpoint descriptor",
            )
            if (
                descriptor.get("scope") != "external"
                or descriptor.get("basename") != f"checkpoint-{split_step}"
                or any(
                    descriptor.get(field) != expected
                    for field, expected in checkpoint_descriptor_inventory.items()
                )
            ):
                raise PruneError(
                    "Resumed gradient-offload checkpoint descriptor is not the exact "
                    "split inventory."
                )
        recomputed_receipts[name] = recomputed
    semantic_identities = {
        name: {field: binding.get(field) for field in GRADIENT_OFFLOAD_SEMANTIC_FIELDS}
        for name, binding in recomputed_receipts.items()
    }
    if (
        receipt_bindings.get("passed") is not True
        or receipt_bindings.get("expected_step_ranges") != expected_ranges
        or receipt_bindings.get("exact_semantic_fields")
        != list(GRADIENT_OFFLOAD_SEMANTIC_FIELDS)
        or receipt_bindings.get("semantic_identities") != semantic_identities
        or receipt_bindings.get("all_semantic_identities_equal") is not True
        or receipt_bindings.get("control_resume_run_id_preserved") is not True
        or not (
            semantic_identities["baseline"]
            == semantic_identities["control"]
            == semantic_identities["resumed"]
        )
        or recomputed_receipts["control"].get("run_id")
        != recomputed_receipts["resumed"].get("run_id")
        or any(
            recomputed_receipts[name].get("run_id")
            != validated_bundles[name].get("run_id")
            or recomputed_receipts[name].get("resume_signature")
            != validated_bundles[name].get("resume_signature")
            for name in ("baseline", "control", "resumed")
        )
    ):
        raise PruneError("Resume gradient-offload A/B/C semantics are not exact.")

    expected_child_roots = {
        "control": control_output,
        "resumed": resumed_output,
    }
    for name, local_name in expected_environment_artifacts.items():
        binding = _require_mapping(
            allocator_bindings.get(name), label=f"resume {name} allocator binding"
        )
        local_record = artifacts_by_path.get(local_name)
        if not isinstance(local_record, Mapping):
            raise PruneError(
                f"Resume {name} published environment artifact is missing."
            )
        _validate_published_resume_environment(
            run_dir,
            name=name,
            local_name=local_name,
            expected_child_root=expected_child_roots[name],
            artifact_record=local_record,
            binding=binding,
            expected_configured=train.get("cuda_allocator_conf"),
            expected_source_sha256=expected_engine_source,
        )

    allocator_equivalence = _require_mapping(
        equivalence.get("allocator_runtime_equivalence"),
        label="resume allocator runtime equivalence",
    )
    identities = _require_mapping(
        allocator_equivalence.get("identities"),
        label="resume allocator runtime identities",
    )
    baseline_allocator = _require_mapping(
        verification.get("allocator_environment"),
        label="baseline allocator environment",
    )
    baseline_identity = {
        key: baseline_allocator.get(key)
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
    expected_identities = {
        "baseline": baseline_identity,
        "control": {
            key: allocator_bindings["control"].get(key)
            for key in baseline_identity
        },
        "resumed": {
            key: allocator_bindings["resumed"].get(key)
            for key in baseline_identity
        },
    }
    if (
        allocator_equivalence.get("passed") is not True
        or allocator_equivalence.get("all_equal") is not True
        or identities != expected_identities
        or not (
            expected_identities["baseline"]
            == expected_identities["control"]
            == expected_identities["resumed"]
        )
    ):
        raise PruneError("Resume allocator/runtime equivalence is not exact.")

    comparisons = _require_mapping(
        equivalence.get("comparisons"), label="resume equivalence comparisons"
    )
    _validate_exact_resume_comparisons(comparisons, split_step=split_step)

    environment = _require_mapping(
        equivalence.get("environment"), label="resume equivalence environment"
    )
    source_files = _require_mapping(
        hashes.get("source_files_sha256"), label="provenance source_files_sha256"
    )
    if (
        environment.get("engine_sha256")
        != source_files.get("src/latent_workspace_ft_v10/engine.py")
        or environment.get("matrix_runner_sha256") != hashes.get("runner_sha256")
        or environment.get("cuda_available") is not True
    ):
        raise PruneError("Resume equivalence runtime is not provenance-bound CUDA.")
    _validate_sha256(
        environment.get("resume_harness_sha256"), label="resume harness sha256"
    )
    launches = _require_mapping(
        equivalence.get("launches"), label="resume equivalence launches"
    )
    for name in ("control", "resumed"):
        launch = _require_mapping(launches.get(name), label=f"resume launch {name}")
        if launch.get("returncode") != 0:
            raise PruneError(f"Resume launch {name} did not complete successfully.")
    performance = _require_mapping(
        equivalence.get("performance_boundary"), label="resume performance boundary"
    )
    if (
        performance.get("training_optimizer_steps_executed")
        != total_steps + (total_steps - split_step)
        or performance.get("comparison_scope")
        != "same_host_same_single_gpu_same_source_and_runtime"
    ):
        raise PruneError("Resume equivalence performance boundary is not exact.")
    boundary = equivalence.get("claim_boundary")
    if not isinstance(boundary, str) or not boundary:
        raise PruneError("Resume equivalence claim boundary is missing.")


def _validate_receipt_artifacts(
    run_dir: Path,
    receipt: Mapping[str, Any],
    *,
    receipt_name: str,
) -> list[dict[str, Any]]:
    records = _validate_inventory_records(
        receipt.get("artifacts"), label=f"{receipt_name} artifacts"
    )
    for record in records:
        relative = str(record["path"])
        if (
            relative == PRUNE_RECEIPT_NAME
            or relative == PRUNE_INTENT_NAME
            or relative.startswith("final/base_model/")
            or CHECKPOINT_RE.fullmatch(PurePosixPath(relative).parts[0]) is not None
        ):
            raise PruneError(
                f"{receipt_name} references a non-compact or prune-controlled artifact: {relative}"
            )
        _artifact_matches(
            _safe_join(run_dir, relative, label=f"{receipt_name} artifact"),
            record,
        )
    return records


def _validate_evidence_receipts(
    run_dir: Path,
    *,
    provenance: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    run_id = provenance.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise PruneError("RUN_VERIFICATION provenance has no run_id.")

    assay_path = run_dir / ASSAY_VERIFICATION_NAME
    assay = read_json(assay_path)
    assay_artifacts = _validate_assay_receipt(
        run_dir, assay, provenance=provenance
    )

    resume_path = run_dir / RESUME_VERIFICATION_NAME
    resume = read_json(resume_path)
    comparison = resume.get("comparison")
    if (
        resume.get("format") != RESUME_VERIFICATION_FORMAT
        or resume.get("verified") is not True
        or resume.get("run_id") != run_id
        or resume.get("provenance") != provenance
        or not isinstance(comparison, dict)
        or comparison.get("passed") is not True
    ):
        raise PruneError("RESUME_VERIFICATION.json is incomplete or provenance-mismatched.")
    resume_artifacts = _validate_receipt_artifacts(
        run_dir, resume, receipt_name=RESUME_VERIFICATION_NAME
    )
    if (
        comparison.get("mode") != "bitwise_exact_zero_tolerance"
        or comparison.get("equivalence_format") != RESUME_EQUIVALENCE_FORMAT
        or comparison.get("equivalence_artifact") != RESUME_EQUIVALENCE_NAME
    ):
        raise PruneError("RESUME_VERIFICATION comparison scope is unsupported.")
    equivalence_path = _safe_relative(
        comparison["equivalence_artifact"],
        label="resume equivalence artifact",
    )
    matching_artifacts = [
        item for item in resume_artifacts if item["path"] == equivalence_path
    ]
    if len(matching_artifacts) != 1:
        raise PruneError("RESUME_VERIFICATION has no unique equivalence artifact.")
    equivalence = read_json(
        _safe_join(run_dir, equivalence_path, label="resume equivalence artifact")
    )
    verification_sha256 = sha256_file(run_dir / RUN_VERIFICATION_NAME)
    if (
        comparison.get("equivalence_sha256") != matching_artifacts[0]["sha256"]
        or comparison.get("baseline_run_verification_sha256")
        != verification_sha256
    ):
        raise PruneError("Resume equivalence artifact is not exactly bound to this run.")
    _validate_resume_equivalence(
        run_dir,
        equivalence,
        provenance=provenance,
        verification_sha256=verification_sha256,
        published_artifacts=resume_artifacts,
    )
    return assay, resume, assay_artifacts + resume_artifacts


def _validate_allocator_environment_binding(
    run_dir: Path,
    verification: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    binding = _require_mapping(
        verification.get("allocator_environment"),
        label="RUN_VERIFICATION allocator_environment",
    )
    if binding.get("passed") is not True or binding.get("path") != ENVIRONMENT_NAME:
        raise PruneError("RUN_VERIFICATION allocator binding is not passing/canonical.")
    record = _regular_file_record(
        run_dir / ENVIRONMENT_NAME, relative=ENVIRONMENT_NAME
    )
    if record["sha256"] != binding.get("sha256"):
        raise PruneError("environment.json hash disagrees with RUN_VERIFICATION.")
    environment = read_json(run_dir / ENVIRONMENT_NAME)
    launched = read_json(run_dir / LAUNCHED_CONFIG_NAME)
    train = _require_mapping(launched.get("train"), label="LAUNCHED_CONFIG train")
    runtime_policy = _require_mapping(
        provenance.get("runtime_policy"), label="provenance runtime_policy"
    )
    if (
        train.get("gradient_accumulation_offload")
        != GRADIENT_ACCUMULATION_OFFLOAD
        or runtime_policy.get("gradient_accumulation_offload")
        != GRADIENT_ACCUMULATION_OFFLOAD
    ):
        raise PruneError(
            "RUN_VERIFICATION gradient-accumulation offload binding is not exact."
        )
    source_files = _require_mapping(
        _require_mapping(provenance.get("hashes"), label="provenance hashes").get(
            "source_files_sha256"
        ),
        label="provenance source files",
    )
    expected_source = source_files.get("src/latent_workspace_ft_v10/engine.py")
    runtime_identity = _require_mapping(
        binding.get("runtime_identity"), label="allocator runtime identity"
    )
    snapshot = _require_mapping(
        binding.get("snapshot_settings"), label="allocator snapshot settings"
    )
    checks = _require_mapping(binding.get("checks"), label="allocator checks")
    required_checks = {
        "configured_policy_exact",
        "primary_environment_exact",
        "legacy_alias_absent",
        "hip_legacy_alias_absent",
        "caching_allocator_enabled",
        "native_backend_reported",
        "parsed_settings_roundtrip_exact",
        "snapshot_expandable_segments_enabled",
        "allocator_initialized",
        "live_cuda_allocation_observed",
        "runtime_identity_complete",
        "source_identity_exact",
    }
    required_environment_keys = {
        "pytorch_alloc_conf",
        "pytorch_cuda_alloc_conf_legacy",
        "pytorch_hip_alloc_conf_legacy",
        "pytorch_no_cuda_memory_caching",
        "allocator_backend",
        "allocator_settings",
        "allocator_snapshot_settings",
        "allocator_initialized",
        "cuda_memory_allocated_bytes",
        "cuda_memory_reserved_bytes",
    }
    allocated = environment.get("cuda_memory_allocated_bytes")
    if (
        not required_checks.issubset(checks)
        or not required_environment_keys.issubset(environment)
        or any(checks.get(key) is not True for key in required_checks)
        or binding.get("configured") != train.get("cuda_allocator_conf")
        or binding.get("observed_primary") != environment.get("pytorch_alloc_conf")
        or binding.get("observed_legacy_alias") is not None
        or binding.get("observed_hip_legacy_alias") is not None
        or binding.get("observed_caching_allocator_disable") is not None
        or environment.get("pytorch_cuda_alloc_conf_legacy") is not None
        or environment.get("pytorch_hip_alloc_conf_legacy") is not None
        or environment.get("pytorch_no_cuda_memory_caching") is not None
        or binding.get("active_backend") != environment.get("allocator_backend")
        or binding.get("active_backend") != "native"
        or binding.get("parsed_settings") != environment.get("allocator_settings")
        or dict(snapshot) != environment.get("allocator_snapshot_settings")
        or snapshot.get("expandable_segments") is not True
        or binding.get("allocator_initialized") is not True
        or environment.get("allocator_initialized") is not True
        or binding.get("cuda_memory_allocated_bytes") != allocated
        or isinstance(allocated, bool)
        or not isinstance(allocated, int)
        or allocated <= 0
        or binding.get("cuda_memory_reserved_bytes")
        != environment.get("cuda_memory_reserved_bytes")
        or runtime_identity.get("source_sha256") != expected_source
        or any(environment.get(key) != value for key, value in runtime_identity.items())
    ):
        raise PruneError("RUN_VERIFICATION allocator environment binding is inconsistent.")
    return record


def _validate_gradient_accumulation_offload_binding(
    run_dir: Path,
    verification: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    binding = _require_mapping(
        verification.get("gradient_accumulation_offload"),
        label="RUN_VERIFICATION gradient_accumulation_offload",
    )
    if (
        binding.get("passed") is not True
        or binding.get("path") != GRADIENT_ACCUMULATION_OFFLOAD_RECEIPT_NAME
    ):
        raise PruneError(
            "RUN_VERIFICATION gradient-offload receipt path/status is not canonical."
        )
    manifest = read_json(run_dir / "final/manifest.json")
    if verification.get("final_manifest") != manifest:
        raise PruneError("RUN_VERIFICATION final manifest binding is not exact.")
    launched = read_json(run_dir / LAUNCHED_CONFIG_NAME)
    train = _require_mapping(launched.get("train"), label="LAUNCHED_CONFIG train")
    source_files = _require_mapping(
        _require_mapping(provenance.get("hashes"), label="provenance hashes").get(
            "source_files_sha256"
        ),
        label="provenance source files",
    )
    expected_source = _validate_sha256(
        source_files.get("src/latent_workspace_ft_v10/engine.py"),
        label="provenance engine source sha256",
    )
    run_id = manifest.get("run_id")
    resume_signature = manifest.get("resume_signature")
    accumulation_steps = train.get("gradient_accumulation_steps")
    final_step = manifest.get("global_step")
    optimizer_coverage = read_json(run_dir / "final/optimizer_coverage.json")
    trainable_parameter_count = optimizer_coverage.get(
        "model_trainable_unique_physical_parameters"
    )
    trainable_parameter_total_numel = optimizer_coverage.get(
        "model_trainable_numel"
    )
    if (
        not isinstance(run_id, str)
        or not run_id
        or manifest.get("source_sha256") != expected_source
        or not isinstance(resume_signature, str)
        or SHA256_RE.fullmatch(resume_signature) is None
        or isinstance(accumulation_steps, bool)
        or not isinstance(accumulation_steps, int)
        or isinstance(final_step, bool)
        or not isinstance(final_step, int)
        or isinstance(trainable_parameter_count, bool)
        or not isinstance(trainable_parameter_count, int)
        or isinstance(trainable_parameter_total_numel, bool)
        or not isinstance(trainable_parameter_total_numel, int)
    ):
        raise PruneError("Gradient-offload manifest/config binding is incomplete.")
    recomputed = validate_gradient_accumulation_offload_receipt_file(
        run_dir / GRADIENT_ACCUMULATION_OFFLOAD_RECEIPT_NAME,
        receipt_path=GRADIENT_ACCUMULATION_OFFLOAD_RECEIPT_NAME,
        expected_run_id=run_id,
        expected_source_sha256=expected_source,
        expected_resume_signature=resume_signature,
        expected_initial_global_step=0,
        expected_final_global_step=final_step,
        expected_configured_accumulation_steps=accumulation_steps,
        expected_initial_resume_checkpoint=None,
        expected_trainable_parameter_count=trainable_parameter_count,
        expected_trainable_parameter_total_numel=trainable_parameter_total_numel,
    )
    if dict(binding) != recomputed:
        raise PruneError(
            "RUN_VERIFICATION gradient-offload receipt summary/hash differs."
        )
    return recomputed


def _validate_run_verification(
    run_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    verification_path = run_dir / RUN_VERIFICATION_NAME
    verification = read_json(verification_path)
    if (
        verification.get("format") != RUN_VERIFICATION_FORMAT
        or verification.get("verified") is not True
    ):
        raise PruneError("RUN_VERIFICATION.json is unsupported or not verified.")
    provenance = verification.get("provenance")
    if not isinstance(provenance, dict):
        raise PruneError("RUN_VERIFICATION.json has no provenance object.")
    _safe_relative(provenance.get("run_id"), label="provenance run_id")
    max_steps = _require_nonnegative_integer(
        provenance.get("max_steps"), label="provenance max_steps"
    )
    _validate_allocator_environment_binding(run_dir, verification, provenance)
    _validate_gradient_accumulation_offload_binding(
        run_dir, verification, provenance
    )

    expected_final = _validate_inventory_records(
        verification.get("final_inventory"), label="RUN_VERIFICATION final_inventory"
    )
    final_dir = run_dir / "final"
    actual_final, _directories = _directory_layout(final_dir)
    if actual_final != expected_final:
        raise PruneError("RUN_VERIFICATION final inventory/hash differs from final/.")
    recorded_bundle_identity = validate_bundle_identity_summary(
        verification.get("bundle_identity"),
        expected_bundle_path="final",
        expected_global_step=max_steps,
        expected_inventory=expected_final,
    )
    live_bundle_identity = validate_bundle_identity(
        final_dir,
        bundle_path="final",
        expected_global_step=max_steps,
    )
    if recorded_bundle_identity != live_bundle_identity:
        raise PruneError("RUN_VERIFICATION bundle identity differs from live final bytes.")
    completed = final_dir / "COMPLETED"
    if completed.read_text(encoding="utf-8").strip() != "ok":
        raise PruneError("Final COMPLETED marker is invalid.")
    manifest = read_json(final_dir / "manifest.json")
    if manifest.get("complete") is not True:
        raise PruneError("Final manifest is not complete.")

    delta = verification.get("full_update_delta")
    if not isinstance(delta, dict) or delta.get("passed") is not True:
        raise PruneError("RUN_VERIFICATION has no passing full-update delta binding.")
    if delta.get("path") != FULL_UPDATE_DELTA_NAME:
        raise PruneError("RUN_VERIFICATION full-update delta path is not canonical.")
    delta_record = _regular_file_record(
        run_dir / FULL_UPDATE_DELTA_NAME, relative=FULL_UPDATE_DELTA_NAME
    )
    if delta_record["sha256"] != delta.get("sha256"):
        raise PruneError("FULL_UPDATE_DELTA.json hash disagrees with RUN_VERIFICATION.")

    base_prefix = "base_model/"
    base_inventory = [
        {**item, "path": str(item["path"])[len(base_prefix) :]}
        for item in expected_final
        if str(item["path"]).startswith(base_prefix)
    ]
    if not base_inventory:
        raise PruneError("RUN_VERIFICATION final inventory has no base_model payload.")
    base_dir = final_dir / "base_model"
    actual_base, _base_directories = _directory_layout(base_dir)
    if actual_base != base_inventory:
        raise PruneError("Exact final/base_model inventory differs from RUN_VERIFICATION.")
    if not any(str(item["path"]).endswith(".safetensors") for item in base_inventory):
        raise PruneError("Verified final/base_model contains no safetensors weights.")
    return verification, expected_final, base_inventory


def _validate_checkpoint(run_dir: Path, checkpoint: Path) -> dict[str, Any]:
    match = CHECKPOINT_RE.fullmatch(checkpoint.name)
    if match is None:
        raise PruneError(f"Unexpected checkpoint-like path: {checkpoint.name}")
    _require_plain_directory(checkpoint, label="checkpoint")
    for relative in (
        "COMPLETED",
        "manifest.json",
        "experiment_config.json",
        "workspace_state.pt",
        "trainer_state.pt",
    ):
        _regular_file_record(checkpoint / relative, relative=relative)
    if (checkpoint / "COMPLETED").read_text(encoding="utf-8").strip() != "ok":
        raise PruneError(f"Incomplete checkpoint marker: {checkpoint.name}")
    manifest = read_json(checkpoint / "manifest.json")
    step = int(match.group(1))
    if manifest.get("complete") is not True or int(manifest.get("global_step", -1)) != step:
        raise PruneError(f"Checkpoint manifest/step mismatch: {checkpoint.name}")
    base_dir = checkpoint / "base_model"
    base_inventory, _base_directories = _directory_layout(base_dir)
    if not any(str(item["path"]).endswith(".safetensors") for item in base_inventory):
        raise PruneError(f"Checkpoint has no safetensors base weights: {checkpoint.name}")
    inventory, directories = _directory_layout(checkpoint)
    return {
        "source": checkpoint.name,
        "kind": "directory",
        "checkpoint_step": step,
        "inventory": inventory,
        "inventory_sha256": _inventory_sha256(inventory),
        "directories": directories,
        "logical_bytes": sum(int(item["bytes"]) for item in inventory),
    }


def _pointer_target(raw: Mapping[str, Any], *, name: str) -> tuple[str, int | None]:
    phase_match = PHASE_POINTER_RE.fullmatch(name)
    key = "checkpoint" if phase_match is not None else "path"
    value = raw.get(key)
    if not isinstance(value, str) or PurePosixPath(value).name != value:
        raise PruneError(f"Checkpoint pointer {name} has a non-local target.")
    match = CHECKPOINT_RE.fullmatch(value)
    if match is None:
        raise PruneError(f"Checkpoint pointer {name} has an invalid target: {value!r}")
    target_step = int(match.group(1))
    declared = raw.get("step", raw.get("global_step"))
    declared_step: int | None = None
    if declared is not None:
        if isinstance(declared, bool) or not isinstance(declared, int):
            raise PruneError(f"Checkpoint pointer {name} has an invalid step.")
        declared_step = declared
        if declared_step != target_step:
            raise PruneError(f"Checkpoint pointer {name} step disagrees with its target.")
    if phase_match is not None and int(phase_match.group(1)) != target_step:
        raise PruneError(f"Phase-boundary pointer name/target step mismatch: {name}")
    return value, declared_step


def _discover_targets(
    run_dir: Path,
    *,
    base_inventory: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    base_dir = run_dir / "final" / "base_model"
    _actual_base, base_directories = _directory_layout(base_dir)
    targets: list[dict[str, Any]] = [
        {
            "source": "final/base_model",
            "kind": "directory",
            "inventory": list(base_inventory),
            "inventory_sha256": _inventory_sha256(base_inventory),
            "directories": base_directories,
            "logical_bytes": sum(int(item["bytes"]) for item in base_inventory),
        }
    ]

    checkpoints: dict[str, dict[str, Any]] = {}
    for entry in sorted(run_dir.iterdir(), key=lambda path: path.name):
        if entry.name.startswith("checkpoint-"):
            if CHECKPOINT_RE.fullmatch(entry.name) is None:
                raise PruneError(f"Unexpected checkpoint-like path: {entry.name}")
            checkpoint = _validate_checkpoint(run_dir, entry)
            checkpoints[entry.name] = checkpoint
            targets.append(checkpoint)

    pointer_paths: list[Path] = []
    for name in POINTER_NAMES:
        path = run_dir / name
        if path.exists() or path.is_symlink():
            pointer_paths.append(path)
    pointer_paths.extend(sorted(run_dir.glob("phase-boundary-step-*.json")))
    seen_pointers: set[str] = set()
    for path in pointer_paths:
        if path.name in seen_pointers:
            continue
        seen_pointers.add(path.name)
        record = _regular_file_record(path, relative=path.name)
        target, declared_step = _pointer_target(read_json(path), name=path.name)
        target_is_live = target in checkpoints
        if not target_is_live and PHASE_POINTER_RE.fullmatch(path.name) is None:
            raise PruneError(
                f"Checkpoint pointer {path.name} refers to absent/incomplete {target}."
            )
        targets.append(
            {
                "source": path.name,
                "kind": "file",
                "pointer_target": target,
                "pointer_step": declared_step,
                "pointer_target_state": (
                    "live" if target_is_live else "historically_dangling"
                ),
                "inventory": [record],
                "inventory_sha256": _inventory_sha256([record]),
                "directories": [],
                "logical_bytes": int(record["bytes"]),
            }
        )

    allowed_roots = {"final/base_model", *checkpoints}
    for current, directory_names, file_names in os.walk(run_dir, followlinks=False):
        current_path = Path(current)
        directory_names.sort()
        file_names.sort()
        for name in directory_names:
            path = current_path / name
            observed = path.lstat()
            if stat.S_ISLNK(observed.st_mode):
                raise PruneError(f"Symlink directories are forbidden in a prune candidate: {path}")
        for name in file_names:
            path = current_path / name
            observed = path.lstat()
            if stat.S_ISLNK(observed.st_mode):
                raise PruneError(f"Symlink files are forbidden in a prune candidate: {path}")
            if not stat.S_ISREG(observed.st_mode):
                raise PruneError(f"Non-regular file found in prune candidate: {path}")
            if observed.st_nlink != 1:
                raise PruneError(f"Hard-linked files are forbidden in a prune candidate: {path}")
            relative = path.relative_to(run_dir).as_posix()
            if name.endswith(".safetensors") and not any(
                relative == root or relative.startswith(root + "/") for root in allowed_roots
            ):
                raise PruneError(f"Unexpected safetensors file outside derived targets: {relative}")
    return targets


def _receipt_record(run_dir: Path, name: str) -> dict[str, Any]:
    return _regular_file_record(run_dir / name, relative=name)


def build_prune_plan(run_dir: Path) -> dict[str, Any]:
    """Validate an unpruned run and return an immutable, internally-derived plan."""

    run_dir = _resolve_run_dir(run_dir, label="run directory")
    if (run_dir / PRUNE_RECEIPT_NAME).exists() or (run_dir / PRUNE_INTENT_NAME).exists():
        raise PruneError("Run already has a prune receipt or incomplete prune intent.")

    verification, final_inventory, base_inventory = _validate_run_verification(run_dir)
    provenance = verification["provenance"]
    assay, resume, referenced_evidence = _validate_evidence_receipts(run_dir, provenance=provenance)
    targets = _discover_targets(run_dir, base_inventory=base_inventory)

    evidence_paths: set[str] = {
        RUN_VERIFICATION_NAME,
        FULL_UPDATE_DELTA_NAME,
        ASSAY_VERIFICATION_NAME,
        RESUME_VERIFICATION_NAME,
        ENVIRONMENT_NAME,
        GRADIENT_ACCUMULATION_OFFLOAD_RECEIPT_NAME,
        "final/COMPLETED",
        "final/manifest.json",
        "final/experiment_config.json",
        "final/optimizer_coverage.json",
        "final/base_update_coverage.json",
    }
    evidence_paths.update(str(item["path"]) for item in referenced_evidence)
    for item in base_inventory:
        relative = str(item["path"])
        if not relative.endswith(".safetensors"):
            evidence_paths.add(f"final/base_model/{relative}")
    evidence_inventory = [
        _regular_file_record(
            _safe_join(run_dir, relative, label="compact evidence path"),
            relative=relative,
        )
        for relative in sorted(evidence_paths)
    ]

    preconditions = {
        "run_verification": _receipt_record(run_dir, RUN_VERIFICATION_NAME),
        "full_update_delta": _receipt_record(run_dir, FULL_UPDATE_DELTA_NAME),
        "assay_verification": _receipt_record(run_dir, ASSAY_VERIFICATION_NAME),
        "resume_verification": _receipt_record(run_dir, RESUME_VERIFICATION_NAME),
        "assay_required": sorted(assay["required_assays"]),
        "assay_completed": sorted(assay["completed_assays"]),
        "resume_comparison_passed": bool(resume["comparison"]["passed"]),
    }
    return {
        "format": "latent-workspace-v10-prune-plan-v1",
        "created_utc": utc_now(),
        "provenance": provenance,
        "preconditions": preconditions,
        "pre_prune_final_inventory": final_inventory,
        "pre_prune_final_inventory_sha256": _inventory_sha256(final_inventory),
        "targets": targets,
        "target_count": len(targets),
        "total_logical_bytes": sum(int(item["logical_bytes"]) for item in targets),
        "compact_evidence_inventory": evidence_inventory,
        "compact_evidence_inventory_sha256": _inventory_sha256(evidence_inventory),
    }


def _safe_export_destination(export_root: Path, provenance: Mapping[str, Any]) -> Path:
    parts: list[str] = []
    for label, value in (
        ("profile", provenance.get("profile")),
        ("condition", provenance.get("condition")),
        ("seed", f"seed_{provenance.get('seed')}"),
    ):
        if not isinstance(value, str) or SAFE_COMPONENT_RE.fullmatch(value) is None:
            raise PruneError(f"Provenance {label} is unsafe for an export destination.")
        parts.append(value)
    return export_root.joinpath(*parts)


def _export_compact_evidence(
    run_dir: Path,
    *,
    export_root: Path,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    expanded_export_root = export_root.expanduser()
    if expanded_export_root.is_symlink():
        raise PruneError("Compact export root must not be a symlink.")
    export_root = expanded_export_root.resolve()
    if export_root == run_dir or run_dir in export_root.parents or export_root in run_dir.parents:
        raise PruneError("Compact export root must be outside the run directory tree.")
    destination = _safe_export_destination(export_root, plan["provenance"])
    if destination.exists() or destination.is_symlink():
        raise PruneError(f"Compact export destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.incomplete-{uuid.uuid4().hex}"
    temporary.mkdir(parents=False, exist_ok=False)
    try:
        expected = _validate_inventory_records(
            plan["compact_evidence_inventory"], label="compact evidence plan"
        )
        for item in expected:
            relative = str(item["path"])
            source = _safe_join(run_dir, relative, label="compact evidence source")
            _artifact_matches(source, item)
            target = _safe_join(temporary, relative, label="compact evidence destination")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            _artifact_matches(target, item)
        actual, _directories = _directory_layout(temporary)
        if actual != expected:
            raise PruneError("Compact export inventory differs after copy.")
        receipt = {
            "format": COMPACT_EXPORT_FORMAT,
            "created_utc": utc_now(),
            "provenance": plan["provenance"],
            "inventory": actual,
            "inventory_sha256": _inventory_sha256(actual),
            "file_count": len(actual),
            "total_bytes": sum(int(item["bytes"]) for item in actual),
        }
        atomic_write_json(temporary / EXPORT_RECEIPT_NAME, receipt)
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    export_receipt = _regular_file_record(
        destination / EXPORT_RECEIPT_NAME,
        relative=EXPORT_RECEIPT_NAME,
    )
    return {
        "destination": str(destination),
        "receipt": export_receipt,
        "inventory": plan["compact_evidence_inventory"],
        "inventory_sha256": plan["compact_evidence_inventory_sha256"],
        "reverified": True,
    }


def _quarantine_relative(index: int, target: Mapping[str, Any]) -> str:
    source_name = str(target["source"]).replace("/", "__")
    return f"targets/{index:04d}-{source_name}"


def _verify_target_at(path: Path, target: Mapping[str, Any]) -> None:
    expected = _validate_inventory_records(target.get("inventory"), label="prune target")
    if target.get("kind") == "directory":
        actual, directories = _directory_layout(path)
        if actual != expected or directories != target.get("directories"):
            raise PruneError(f"Prune target mutated: {path}")
    elif target.get("kind") == "file":
        if len(expected) != 1:
            raise PruneError("File prune target must have exactly one inventory record.")
        _artifact_matches(path, expected[0])
    else:
        raise PruneError("Unsupported prune target kind.")
    if _inventory_sha256(expected) != target.get("inventory_sha256"):
        raise PruneError(f"Prune target inventory digest mismatch: {path}")


def _delete_exact_target(path: Path, target: Mapping[str, Any]) -> None:
    _verify_target_at(path, target)
    expected = _validate_inventory_records(target["inventory"], label="delete target")
    if target["kind"] == "file":
        path.unlink()
        _fsync_directory(path.parent)
        return
    for item in expected:
        child = _safe_join(path, str(item["path"]), label="quarantined target file")
        child.unlink()
    directories = target.get("directories")
    if not isinstance(directories, list):
        raise PruneError("Directory target has no exact directory list.")
    for relative in sorted(
        directories,
        key=lambda value: (len(PurePosixPath(str(value)).parts), str(value)),
        reverse=True,
    ):
        child = _safe_join(path, str(relative), label="quarantined target directory")
        child.rmdir()
    path.rmdir()
    _fsync_directory(path.parent)


def _inventory_run_after_prune(run_dir: Path) -> list[dict[str, Any]]:
    inventory, _directories = _directory_layout(run_dir)
    return [item for item in inventory if item["path"] != PRUNE_RECEIPT_NAME]


def _directories_run_after_prune(run_dir: Path) -> list[str]:
    _inventory, directories = _directory_layout(run_dir)
    return directories


def _receipt_with_report_hash(payload: Mapping[str, Any]) -> dict[str, Any]:
    receipt = dict(payload)
    receipt["report_sha256"] = sha256_bytes(canonical_json_bytes(receipt))
    return receipt


def _runner_lock_path(run_dir: Path, provenance: Mapping[str, Any]) -> Path:
    output_relative = _safe_relative(provenance.get("output_dir"), label="provenance output_dir")
    relative_parts = PurePosixPath(output_relative).parts
    repo_root = run_dir
    for _part in relative_parts:
        repo_root = repo_root.parent
    if (repo_root / output_relative).resolve() != run_dir:
        raise PruneError(
            "Run directory does not match provenance.output_dir; runner lock scope "
            "cannot be established safely."
        )
    return repo_root / "runs/v10/_control/RUNNER.lock"


@contextlib.contextmanager
def _exclusive_runner_lock(path: Path) -> Any:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise PruneError(f"Unsafe or inaccessible runner/pruner lock {path}: {exc}") from exc
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
            raise PruneError(
                "Runner/pruner lock must be a regular, non-symlink, "
                f"single-link file: {path}"
            )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PruneError(f"Runner/pruner lock is held: {path}") from exc
        metadata = canonical_json_bytes(
            {
                "operation": "verified_run_prune",
                "pid": os.getpid(),
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


def execute_prune(
    run_dir: Path,
    *,
    reason: str,
    compact_export_root: Path,
    fault_phase: str | None = None,
) -> dict[str, Any]:
    """Acquire the matrix-wide lock and execute one retention transition."""

    resolved_run_dir = _resolve_run_dir(run_dir, label="run directory")
    verification = read_json(resolved_run_dir / RUN_VERIFICATION_NAME)
    provenance = verification.get("provenance")
    if not isinstance(provenance, dict):
        raise PruneError("RUN_VERIFICATION.json has no provenance object.")
    lock_path = _runner_lock_path(resolved_run_dir, provenance)
    with _exclusive_runner_lock(lock_path):
        return _execute_prune_locked(
            resolved_run_dir,
            reason=reason,
            compact_export_root=compact_export_root,
            fault_phase=fault_phase,
        )


def _finalize_prune_receipt(
    run_dir: Path,
    *,
    intent: Mapping[str, Any],
    intent_record: Mapping[str, Any],
    disk_before_delete: int,
    recovery: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    provenance = _require_mapping(intent.get("provenance"), label="prune intent provenance")
    targets_raw = intent.get("targets")
    if not isinstance(targets_raw, list) or not targets_raw:
        raise PruneError("Prune intent has no targets for finalization.")
    targets = [dict(_require_mapping(item, label="prune target")) for item in targets_raw]
    for target in targets:
        source = _safe_join(run_dir, str(target["source"]), label="deleted target")
        if source.exists() or source.is_symlink():
            raise PruneError(f"Derived prune target reappeared after deletion: {source}")
    quarantine_name = intent.get("quarantine")
    if (
        not isinstance(quarantine_name, str)
        or PurePosixPath(quarantine_name).name != quarantine_name
    ):
        raise PruneError("Prune intent has an unsafe quarantine name.")
    quarantine = run_dir.parent / quarantine_name
    if quarantine.exists() or quarantine.is_symlink():
        raise PruneError("Prune quarantine remains before receipt finalization.")
    export = _require_mapping(intent.get("compact_export"), label="compact export")
    _verify_export(export, provenance=provenance)

    retained = _inventory_run_after_prune(run_dir)
    retained_directories = _directories_run_after_prune(run_dir)
    disk_after_delete = shutil.disk_usage(run_dir).free
    receipt_payload: dict[str, Any] = {
        "format": PRUNE_RECEIPT_FORMAT,
        "transaction_id": intent["transaction_id"],
        "completed": True,
        "started_utc": intent["created_utc"],
        "completed_utc": utc_now(),
        "explicit_opt_in": True,
        "reason": intent["reason"],
        "provenance": provenance,
        "intent": dict(intent_record),
        "preconditions": intent["preconditions"],
        "pre_prune_final_inventory_sha256": intent[
            "pre_prune_final_inventory_sha256"
        ],
        "deleted_targets": targets,
        "deleted_target_count": len(targets),
        "logical_bytes_removed": intent["total_logical_bytes"],
        "observed_free_disk_bytes_before_delete": disk_before_delete,
        "observed_free_disk_bytes_after_delete": disk_after_delete,
        "observed_free_disk_delta_bytes": disk_after_delete - disk_before_delete,
        "compact_export": export,
        "retained_inventory": retained,
        "retained_inventory_sha256": _inventory_sha256(retained),
        "retained_directories": retained_directories,
        "post_prune_checks": {
            "all_derived_targets_absent": True,
            "quarantine_absent": True,
            "retained_inventory_rehashed": True,
            "retained_directories_rehashed": True,
            "compact_export_rehashed": True,
        },
        "recoverability": {
            "pinned_initial_model": "recoverable_from_pinned_model_revision",
            "trained_final_weights": "not_recoverable_without_external_weight_backup",
            "completed_checkpoints": "not_recoverable_without_external_weight_backup",
            "integrity_evidence_is_a_backup": False,
        },
        "state": "verified_pruned",
        "claim_boundary": (
            "This receipt preserves the hash-bound history of a previously verified "
            "run and proves the recorded local targets are absent after an explicit "
            "retention transition. It does not make the trained weights loadable or "
            "reconstructible and does not prove training quality or scientific success."
        ),
    }
    if recovery is not None:
        receipt_payload["recovery"] = dict(recovery)
    receipt = _receipt_with_report_hash(receipt_payload)
    atomic_create_json(run_dir / PRUNE_RECEIPT_NAME, receipt)
    verify_pruned(run_dir, expected_provenance=provenance)
    return receipt


def _execute_prune_locked(
    run_dir: Path,
    *,
    reason: str,
    compact_export_root: Path,
    fault_phase: str | None = None,
) -> dict[str, Any]:
    """Execute one exact verified-run retention transition.

    ``fault_phase`` exists solely for deterministic local fault-injection tests.
    An injected or real failure after intent creation deliberately leaves a
    protected ``prune_incomplete`` state. It is never finalized implicitly;
    ``--execute --recover`` must explicitly continue the intent-bound deletion.
    """

    reason = reason.strip()
    if not reason:
        raise PruneError("Execution requires a non-empty pruning reason.")
    run_dir = _resolve_run_dir(run_dir, label="run directory")
    plan = build_prune_plan(run_dir)
    export = _export_compact_evidence(
        run_dir,
        export_root=compact_export_root,
        plan=plan,
    )
    transaction_id = uuid.uuid4().hex
    quarantine = run_dir.parent / f".{run_dir.name}.prune-quarantine-{transaction_id}"
    if quarantine.exists() or quarantine.is_symlink():
        raise PruneError(f"Quarantine path already exists: {quarantine}")
    if run_dir.stat().st_dev != quarantine.parent.stat().st_dev:
        raise PruneError("Prune quarantine must be on the run directory filesystem.")

    targets: list[dict[str, Any]] = []
    for index, raw in enumerate(plan["targets"]):
        target = dict(raw)
        target["quarantine"] = _quarantine_relative(index, target)
        targets.append(target)
    intent = {
        "format": PRUNE_INTENT_FORMAT,
        "transaction_id": transaction_id,
        "created_utc": utc_now(),
        "state": "prepared",
        "explicit_opt_in": True,
        "reason": reason,
        "provenance": plan["provenance"],
        "preconditions": plan["preconditions"],
        "pre_prune_final_inventory_sha256": plan["pre_prune_final_inventory_sha256"],
        "targets": targets,
        "target_count": len(targets),
        "total_logical_bytes": plan["total_logical_bytes"],
        "compact_export": export,
        "quarantine": quarantine.name,
    }
    intent_path = run_dir / PRUNE_INTENT_NAME
    atomic_create_json(intent_path, intent)
    intent_record = _regular_file_record(intent_path, relative=PRUNE_INTENT_NAME)
    if fault_phase == "after_intent":
        raise PruneError("Injected failure after intent creation.")

    quarantine.mkdir(parents=False, exist_ok=False)
    moved = 0
    for target in targets:
        source = _safe_join(run_dir, str(target["source"]), label="derived prune target")
        _verify_target_at(source, target)
        destination = _safe_join(
            quarantine,
            str(target["quarantine"]),
            label="quarantine target",
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)
        _fsync_directory(source.parent)
        _fsync_directory(destination.parent)
        moved += 1
        if fault_phase == "after_first_quarantine" and moved == 1:
            raise PruneError("Injected failure after first quarantine move.")
    if fault_phase == "after_quarantine":
        raise PruneError("Injected failure after quarantine completion.")

    for target in targets:
        destination = _safe_join(
            quarantine,
            str(target["quarantine"]),
            label="quarantined target",
        )
        _verify_target_at(destination, target)

    disk_before_delete = shutil.disk_usage(run_dir).free
    deleted = 0
    for target in targets:
        destination = _safe_join(
            quarantine,
            str(target["quarantine"]),
            label="quarantined target",
        )
        _delete_exact_target(destination, target)
        deleted += 1
        if fault_phase == "after_first_delete" and deleted == 1:
            raise PruneError("Injected failure after first exact deletion.")
    targets_dir = quarantine / "targets"
    if targets_dir.exists():
        targets_dir.rmdir()
    quarantine.rmdir()
    _fsync_directory(quarantine.parent)
    if fault_phase == "after_delete":
        raise PruneError("Injected failure after deletion before final receipt.")

    return _finalize_prune_receipt(
        run_dir,
        intent=intent,
        intent_record=intent_record,
        disk_before_delete=disk_before_delete,
    )


def _validate_remaining_target(path: Path, target: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a crash-partially-deleted quarantine target as an exact subset."""

    expected = _validate_inventory_records(target.get("inventory"), label="prune target")
    if _inventory_sha256(expected) != target.get("inventory_sha256"):
        raise PruneError(f"Prune target inventory digest mismatch: {path}")
    kind = target.get("kind")
    if kind == "file":
        if len(expected) != 1:
            raise PruneError("File prune target must have exactly one inventory record.")
        _artifact_matches(path, expected[0])
        return {"remaining_files": 1, "partial": False}
    if kind != "directory":
        raise PruneError("Unsupported prune target kind.")
    actual, actual_directories = _directory_layout(path)
    expected_by_path = {str(item["path"]): item for item in expected}
    for item in actual:
        if expected_by_path.get(str(item["path"])) != item:
            raise PruneError(f"Unexpected or mutated remaining quarantine file: {path}")
    expected_directories = target.get("directories")
    if (
        not isinstance(expected_directories, list)
        or any(not isinstance(item, str) for item in expected_directories)
        or not set(actual_directories) <= set(expected_directories)
    ):
        raise PruneError(f"Unexpected remaining quarantine directory: {path}")
    return {
        "remaining_files": len(actual),
        "partial": actual != expected or actual_directories != expected_directories,
    }


def _delete_remaining_target(path: Path, target: Mapping[str, Any]) -> None:
    if not path.exists() and not path.is_symlink():
        return
    _validate_remaining_target(path, target)
    if target["kind"] == "file":
        path.unlink()
        _fsync_directory(path.parent)
        return
    actual, directories = _directory_layout(path)
    for item in actual:
        child = _safe_join(path, str(item["path"]), label="remaining quarantine file")
        child.unlink()
    for relative in sorted(
        directories,
        key=lambda value: (len(PurePosixPath(value).parts), value),
        reverse=True,
    ):
        _safe_join(path, relative, label="remaining quarantine directory").rmdir()
    path.rmdir()
    _fsync_directory(path.parent)


def _require_plain_parent_chain(root: Path, relative_parent: PurePosixPath) -> Path:
    current = root
    for part in relative_parent.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            _require_plain_directory(current, label="quarantine parent")
        else:
            current.mkdir()
            _fsync_directory(current.parent)
    return current


def _remove_empty_quarantine(quarantine: Path) -> None:
    if not quarantine.exists() and not quarantine.is_symlink():
        return
    _require_plain_directory(quarantine, label="prune quarantine")
    inventory, directories = _directory_layout(quarantine)
    if inventory:
        raise PruneError("Unexpected files remain outside validated quarantine targets.")
    for relative in sorted(
        directories,
        key=lambda value: (len(PurePosixPath(value).parts), value),
        reverse=True,
    ):
        _safe_join(quarantine, relative, label="empty quarantine directory").rmdir()
    quarantine.rmdir()
    _fsync_directory(quarantine.parent)


def _validate_recovery_intent(
    run_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], Path]:
    if (run_dir / PRUNE_RECEIPT_NAME).exists() or (run_dir / PRUNE_RECEIPT_NAME).is_symlink():
        raise PruneError("A prune receipt already exists; recovery cannot replace it.")
    intent_path = run_dir / PRUNE_INTENT_NAME
    intent_record = _regular_file_record(intent_path, relative=PRUNE_INTENT_NAME)
    intent = read_json(intent_path)
    transaction_id = intent.get("transaction_id")
    if (
        intent.get("format") != PRUNE_INTENT_FORMAT
        or intent.get("state") != "prepared"
        or intent.get("explicit_opt_in") is not True
        or not isinstance(transaction_id, str)
        or re.fullmatch(r"[0-9a-f]{32}", transaction_id) is None
        or not isinstance(intent.get("reason"), str)
        or not str(intent["reason"]).strip()
    ):
        raise PruneError("PRUNE_INTENT.json is unsupported or incomplete.")
    provenance = _require_mapping(intent.get("provenance"), label="intent provenance")
    verification = read_json(run_dir / RUN_VERIFICATION_NAME)
    if (
        verification.get("format") != RUN_VERIFICATION_FORMAT
        or verification.get("verified") is not True
        or verification.get("provenance") != provenance
    ):
        raise PruneError("Recovery intent does not bind the retained verified run.")
    _validate_allocator_environment_binding(run_dir, verification, provenance)
    _validate_gradient_accumulation_offload_binding(
        run_dir, verification, provenance
    )
    preconditions = _require_mapping(intent.get("preconditions"), label="intent preconditions")
    for key in (
        "run_verification",
        "full_update_delta",
        "assay_verification",
        "resume_verification",
    ):
        record = _require_mapping(preconditions.get(key), label=f"precondition {key}")
        relative = _safe_relative(record.get("path"), label=f"precondition {key} path")
        _artifact_matches(_safe_join(run_dir, relative, label=f"precondition {key}"), record)
    _validate_evidence_receipts(run_dir, provenance=provenance)
    expected_final = _validate_inventory_records(
        verification.get("final_inventory"), label="RUN_VERIFICATION final inventory"
    )
    if intent.get("pre_prune_final_inventory_sha256") != _inventory_sha256(expected_final):
        raise PruneError("Recovery intent pre-prune final inventory binding is invalid.")
    export = _require_mapping(intent.get("compact_export"), label="intent compact export")
    _verify_export(export, provenance=provenance)

    raw_targets = intent.get("targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise PruneError("Recovery intent has no target list.")
    targets: list[dict[str, Any]] = []
    sources: set[str] = set()
    quarantines: set[str] = set()
    base_count = 0
    logical_bytes = 0
    for index, raw in enumerate(raw_targets):
        target = dict(_require_mapping(raw, label="recovery target"))
        source = _safe_relative(target.get("source"), label="recovery target source")
        if source in sources:
            raise PruneError(f"Duplicate recovery target source: {source}")
        sources.add(source)
        if source == "final/base_model":
            base_count += 1
        elif CHECKPOINT_RE.fullmatch(source) is None and (
            source not in POINTER_NAMES and PHASE_POINTER_RE.fullmatch(source) is None
        ):
            raise PruneError(f"Recovery target is outside the closed scope: {source}")
        quarantine_relative = _safe_relative(
            target.get("quarantine"), label="recovery quarantine target"
        )
        if quarantine_relative != _quarantine_relative(index, target):
            raise PruneError("Recovery quarantine target does not match its deterministic path.")
        if quarantine_relative in quarantines:
            raise PruneError(f"Duplicate recovery quarantine path: {quarantine_relative}")
        quarantines.add(quarantine_relative)
        inventory = _validate_inventory_records(
            target.get("inventory"), label=f"recovery target {source}"
        )
        if target.get("inventory_sha256") != _inventory_sha256(inventory):
            raise PruneError(f"Recovery target inventory hash is invalid: {source}")
        target_bytes = sum(int(item["bytes"]) for item in inventory)
        if target.get("logical_bytes") != target_bytes:
            raise PruneError(f"Recovery target byte count is invalid: {source}")
        logical_bytes += target_bytes
        kind = target.get("kind")
        directories = target.get("directories")
        if kind not in {"file", "directory"} or not isinstance(directories, list):
            raise PruneError(f"Recovery target kind/directory list is invalid: {source}")
        targets.append(target)
    if (
        base_count != 1
        or intent.get("target_count") != len(targets)
        or intent.get("total_logical_bytes") != logical_bytes
    ):
        raise PruneError("Recovery target aggregate counts are invalid.")
    quarantine_name = intent.get("quarantine")
    expected_quarantine_name = f".{run_dir.name}.prune-quarantine-{transaction_id}"
    if quarantine_name != expected_quarantine_name:
        raise PruneError("Recovery quarantine name is not transaction-derived.")
    quarantine = run_dir.parent / expected_quarantine_name
    if quarantine.exists() or quarantine.is_symlink():
        _require_plain_directory(quarantine, label="prune quarantine")
    if run_dir.stat().st_dev != quarantine.parent.stat().st_dev:
        raise PruneError("Recovery quarantine is not on the run filesystem.")
    return intent, intent_record, targets, quarantine


def recover_prune(run_dir: Path) -> dict[str, Any]:
    """Explicitly continue and finalize one interrupted prune transaction."""

    resolved_run_dir = _resolve_run_dir(run_dir, label="run directory")
    verification = read_json(resolved_run_dir / RUN_VERIFICATION_NAME)
    provenance = _require_mapping(
        verification.get("provenance"), label="RUN_VERIFICATION provenance"
    )
    lock_path = _runner_lock_path(resolved_run_dir, provenance)
    with _exclusive_runner_lock(lock_path):
        return _recover_prune_locked(resolved_run_dir)


def _recover_prune_locked(run_dir: Path) -> dict[str, Any]:
    intent, intent_record, targets, quarantine = _validate_recovery_intent(run_dir)
    disk_before_delete = shutil.disk_usage(run_dir).free
    initial_states: dict[str, str] = {}
    if not quarantine.exists():
        quarantine.mkdir(parents=False, exist_ok=False)
        _fsync_directory(quarantine.parent)

    for target in targets:
        source = _safe_join(run_dir, str(target["source"]), label="recovery source")
        destination = _safe_join(
            quarantine,
            str(target["quarantine"]),
            label="recovery quarantine target",
        )
        source_exists = source.exists() or source.is_symlink()
        destination_exists = destination.exists() or destination.is_symlink()
        if source_exists and destination_exists:
            raise PruneError(f"Recovery target exists in source and quarantine: {source}")
        if source_exists:
            _verify_target_at(source, target)
            initial_states[str(target["source"])] = "source"
            relative_parent = PurePosixPath(str(target["quarantine"])).parent
            _require_plain_parent_chain(quarantine, relative_parent)
            os.replace(source, destination)
            _fsync_directory(source.parent)
            _fsync_directory(destination.parent)
            _verify_target_at(destination, target)
        elif destination_exists:
            remaining = _validate_remaining_target(destination, target)
            initial_states[str(target["source"])] = (
                "quarantine_partial" if remaining["partial"] else "quarantine_complete"
            )
        else:
            initial_states[str(target["source"])] = "already_deleted"

    for target in targets:
        destination = _safe_join(
            quarantine,
            str(target["quarantine"]),
            label="recovery quarantine target",
        )
        _delete_remaining_target(destination, target)
    _remove_empty_quarantine(quarantine)
    return _finalize_prune_receipt(
        run_dir,
        intent=intent,
        intent_record=intent_record,
        disk_before_delete=disk_before_delete,
        recovery={
            "mode": "explicit_continue_and_finalize",
            "recovered_utc": utc_now(),
            "initial_target_states": initial_states,
            "automatic_recovery": False,
            "claim_boundary": (
                "Recovery revalidated exact live or remaining target subsets and explicitly "
                "continued the already-authorized deletion. Already absent bytes cannot be "
                "rehash-verified after deletion; their pre-delete hashes remain intent-bound."
            ),
        },
    )


def _verify_export(export: Mapping[str, Any], *, provenance: Mapping[str, Any]) -> None:
    destination_raw = export.get("destination")
    if not isinstance(destination_raw, str) or not destination_raw:
        raise PruneError("Prune receipt has no compact export destination.")
    expanded_destination = Path(destination_raw).expanduser()
    if expanded_destination.is_symlink():
        raise PruneError("Compact export destination must not be a symlink.")
    destination = expanded_destination.resolve()
    _require_plain_directory(destination, label="compact export destination")
    receipt_record = export.get("receipt")
    if not isinstance(receipt_record, dict):
        raise PruneError("Prune receipt has no compact export receipt binding.")
    _artifact_matches(destination / EXPORT_RECEIPT_NAME, receipt_record)
    export_receipt = read_json(destination / EXPORT_RECEIPT_NAME)
    expected_inventory = _validate_inventory_records(
        export.get("inventory"), label="prune compact export inventory"
    )
    actual_inventory, _directories = _directory_layout(destination)
    actual_without_receipt = [
        item for item in actual_inventory if item["path"] != EXPORT_RECEIPT_NAME
    ]
    if (
        export_receipt.get("format") != COMPACT_EXPORT_FORMAT
        or export_receipt.get("provenance") != provenance
        or export_receipt.get("inventory") != expected_inventory
        or export_receipt.get("inventory_sha256") != _inventory_sha256(expected_inventory)
        or export.get("inventory_sha256") != _inventory_sha256(expected_inventory)
        or actual_without_receipt != expected_inventory
    ):
        raise PruneError("Compact evidence export failed exact re-verification.")


def verify_pruned(
    run_dir: Path,
    *,
    expected_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    run_dir = _resolve_run_dir(run_dir, label="pruned run directory")
    receipt_path = run_dir / PRUNE_RECEIPT_NAME
    _regular_file_record(receipt_path, relative=PRUNE_RECEIPT_NAME)
    receipt = read_json(receipt_path)
    unsigned = dict(receipt)
    report_sha256 = unsigned.pop("report_sha256", None)
    if (
        receipt.get("format") != PRUNE_RECEIPT_FORMAT
        or receipt.get("completed") is not True
        or receipt.get("explicit_opt_in") is not True
        or receipt.get("state") != "verified_pruned"
        or not isinstance(receipt.get("reason"), str)
        or not str(receipt["reason"]).strip()
        or report_sha256 != sha256_bytes(canonical_json_bytes(unsigned))
    ):
        raise PruneError("PRUNE_RECEIPT.json is incomplete or has a bad report hash.")
    provenance = receipt.get("provenance")
    if not isinstance(provenance, dict):
        raise PruneError("PRUNE_RECEIPT.json has no provenance object.")
    if expected_provenance is not None and provenance != dict(expected_provenance):
        raise PruneError(
            "Prune provenance does not match the current prepared run; "
            "historical/future provenance is never treated as stale output."
        )

    intent_record = receipt.get("intent")
    if not isinstance(intent_record, dict):
        raise PruneError("PRUNE_RECEIPT.json has no intent binding.")
    _artifact_matches(run_dir / PRUNE_INTENT_NAME, intent_record)
    intent = read_json(run_dir / PRUNE_INTENT_NAME)
    if (
        intent.get("format") != PRUNE_INTENT_FORMAT
        or intent.get("transaction_id") != receipt.get("transaction_id")
        or intent.get("provenance") != provenance
        or intent.get("targets") != receipt.get("deleted_targets")
    ):
        raise PruneError("Prune intent/final receipt binding mismatch.")

    preconditions = receipt.get("preconditions")
    if not isinstance(preconditions, dict) or preconditions != intent.get("preconditions"):
        raise PruneError("Prune preconditions do not match the immutable intent.")
    for key in (
        "run_verification",
        "full_update_delta",
        "assay_verification",
        "resume_verification",
    ):
        record = preconditions.get(key)
        if not isinstance(record, dict):
            raise PruneError(f"Prune precondition {key} is missing.")
        relative = _safe_relative(record.get("path"), label=f"{key} receipt path")
        _artifact_matches(_safe_join(run_dir, relative, label=key), record)
    run_verification = read_json(run_dir / RUN_VERIFICATION_NAME)
    if (
        run_verification.get("format") != RUN_VERIFICATION_FORMAT
        or run_verification.get("verified") is not True
        or run_verification.get("provenance") != provenance
    ):
        raise PruneError("Retained RUN_VERIFICATION.json is no longer exact.")
    _validate_allocator_environment_binding(run_dir, run_verification, provenance)
    _validate_gradient_accumulation_offload_binding(
        run_dir, run_verification, provenance
    )
    max_steps = _require_nonnegative_integer(
        provenance.get("max_steps"), label="retained provenance max_steps"
    )
    retained_final_inventory = _validate_inventory_records(
        run_verification.get("final_inventory"),
        label="retained RUN_VERIFICATION final inventory",
    )
    recorded_bundle_identity = validate_bundle_identity_summary(
        run_verification.get("bundle_identity"),
        expected_bundle_path="final",
        expected_global_step=max_steps,
        expected_inventory=retained_final_inventory,
    )
    live_bundle_identity = validate_bundle_identity(
        run_dir / "final",
        bundle_path="final",
        expected_global_step=max_steps,
    )
    if recorded_bundle_identity != live_bundle_identity:
        raise PruneError("Retained bundle identity differs from live final metadata.")
    _validate_evidence_receipts(run_dir, provenance=provenance)

    targets = receipt.get("deleted_targets")
    if not isinstance(targets, list) or not targets:
        raise PruneError("Prune receipt has no deleted target list.")
    target_sources: set[str] = set()
    target_logical_bytes = 0
    base_target_count = 0
    for target in targets:
        if not isinstance(target, dict):
            raise PruneError("Malformed deleted target record.")
        relative = _safe_relative(target.get("source"), label="deleted target")
        if relative in target_sources:
            raise PruneError(f"Duplicate deleted target path: {relative}")
        target_sources.add(relative)
        if relative == "final/base_model":
            base_target_count += 1
        elif CHECKPOINT_RE.fullmatch(relative) is None and (
            relative not in POINTER_NAMES and PHASE_POINTER_RE.fullmatch(relative) is None
        ):
            raise PruneError(f"Deleted target is outside the closed retention scope: {relative}")
        source = _safe_join(run_dir, relative, label="deleted target")
        if source.exists() or source.is_symlink():
            raise PruneError(f"Deleted target is present again: {relative}")
        target_inventory = _validate_inventory_records(
            target.get("inventory"), label="deleted target inventory"
        )
        if target.get("inventory_sha256") != _inventory_sha256(target_inventory):
            raise PruneError(f"Deleted target inventory hash is inconsistent: {relative}")
        logical_bytes = sum(int(item["bytes"]) for item in target_inventory)
        if target.get("logical_bytes") != logical_bytes:
            raise PruneError(f"Deleted target byte count is inconsistent: {relative}")
        target_logical_bytes += logical_bytes
    if base_target_count != 1:
        raise PruneError("Prune receipt must contain exactly one final/base_model target.")
    if (
        receipt.get("deleted_target_count") != len(targets)
        or receipt.get("logical_bytes_removed") != target_logical_bytes
    ):
        raise PruneError("Prune target aggregate counts are inconsistent.")
    final_inventory = _validate_inventory_records(
        run_verification.get("final_inventory"),
        label="retained RUN_VERIFICATION final inventory",
    )
    if receipt.get("pre_prune_final_inventory_sha256") != _inventory_sha256(
        final_inventory
    ) or intent.get("pre_prune_final_inventory_sha256") != _inventory_sha256(final_inventory):
        raise PruneError("Pre-prune final inventory binding is inconsistent.")
    quarantine_name = intent.get("quarantine")
    if (
        not isinstance(quarantine_name, str)
        or PurePosixPath(quarantine_name).name != quarantine_name
    ):
        raise PruneError("Prune intent has an unsafe quarantine name.")
    quarantine = run_dir.parent / quarantine_name
    if quarantine.exists() or quarantine.is_symlink():
        raise PruneError("Prune quarantine remains after a completed receipt.")

    expected_retained = _validate_inventory_records(
        receipt.get("retained_inventory"), label="retained inventory"
    )
    actual_retained = _inventory_run_after_prune(run_dir)
    if actual_retained != expected_retained or receipt.get(
        "retained_inventory_sha256"
    ) != _inventory_sha256(expected_retained):
        raise PruneError("Retained run inventory/hash mismatch after pruning.")
    expected_directories = receipt.get("retained_directories")
    if (
        not isinstance(expected_directories, list)
        or any(not isinstance(item, str) for item in expected_directories)
        or expected_directories != sorted(set(expected_directories))
        or _directories_run_after_prune(run_dir) != expected_directories
    ):
        raise PruneError("Retained run directory layout mismatch after pruning.")
    export = receipt.get("compact_export")
    if not isinstance(export, dict):
        raise PruneError("Prune receipt has no compact export binding.")
    _verify_export(export, provenance=provenance)
    recoverability = receipt.get("recoverability")
    if (
        not isinstance(recoverability, dict)
        or recoverability.get("trained_final_weights")
        != "not_recoverable_without_external_weight_backup"
        or recoverability.get("completed_checkpoints")
        != "not_recoverable_without_external_weight_backup"
        or recoverability.get("integrity_evidence_is_a_backup") is not False
    ):
        raise PruneError("Prune recoverability boundary is missing or weakened.")
    return {
        "state": "verified_pruned",
        "reason": "Verified prune receipt, retained evidence, export, and target absence.",
        "receipt_sha256": sha256_file(receipt_path),
        "report_sha256": report_sha256,
        "logical_bytes_removed": receipt.get("logical_bytes_removed"),
    }


def classify_prune_state(
    run_dir: Path,
    *,
    expected_provenance: Mapping[str, Any] | None = None,
) -> tuple[str | None, str]:
    """Classify only retention states; return ``None`` for ordinary runs."""

    expanded = run_dir.expanduser()
    if expanded.is_symlink():
        return "invalid_prune_receipt", f"Run directory is a symlink: {expanded}"
    run_dir = expanded.resolve()
    receipt = run_dir / PRUNE_RECEIPT_NAME
    intent = run_dir / PRUNE_INTENT_NAME
    if receipt.exists() or receipt.is_symlink():
        try:
            result = verify_pruned(run_dir, expected_provenance=expected_provenance)
        except (PruneError, OSError, ValueError, TypeError) as exc:
            return "invalid_prune_receipt", str(exc)
        return "verified_pruned", str(result["reason"])
    if intent.exists() or intent.is_symlink():
        return (
            "prune_incomplete",
            "PRUNE_INTENT.json exists without a completed, valid PRUNE_RECEIPT.json; "
            "explicit recovery is required.",
        )
    return None, "no prune state"


def _plan_summary(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "mode": "dry_run",
        "would_execute": False,
        "provenance": plan["provenance"],
        "preconditions": plan["preconditions"],
        "targets": [
            {
                "source": item["source"],
                "kind": item["kind"],
                "file_count": len(item["inventory"]),
                "logical_bytes": item["logical_bytes"],
                "inventory_sha256": item["inventory_sha256"],
            }
            for item in plan["targets"]
        ],
        "target_count": plan["target_count"],
        "total_logical_bytes": plan["total_logical_bytes"],
        "compact_evidence_file_count": len(plan["compact_evidence_inventory"]),
        "compact_evidence_inventory_sha256": plan["compact_evidence_inventory_sha256"],
        "claim_boundary": (
            "Dry-run validates and reports internally-derived targets only. It creates "
            "no export, intent, quarantine, deletion, or prune receipt."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate or explicitly prune one verified v10 run."
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--compact-export-root", type=Path, default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--recover",
        action="store_true",
        help="With --execute, explicitly continue and finalize an existing prune intent.",
    )
    parser.add_argument("--reason", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.recover:
            if not args.execute:
                raise PruneError("--recover requires --execute.")
            if args.compact_export_root is not None or args.reason:
                raise PruneError(
                    "Recovery uses the intent-bound export and reason; do not resupply them."
                )
            receipt = recover_prune(args.run_dir)
            print(json.dumps(receipt, indent=2, sort_keys=True))
        elif args.execute:
            if args.compact_export_root is None:
                raise PruneError("--execute requires --compact-export-root.")
            receipt = execute_prune(
                args.run_dir,
                reason=args.reason,
                compact_export_root=args.compact_export_root,
            )
            print(json.dumps(receipt, indent=2, sort_keys=True))
        else:
            state, reason = classify_prune_state(args.run_dir)
            if state is not None:
                print(json.dumps({"state": state, "reason": reason}, indent=2, sort_keys=True))
            else:
                print(
                    json.dumps(
                        _plan_summary(build_prune_plan(args.run_dir)), indent=2, sort_keys=True
                    )
                )
    except PruneError as exc:
        print(f"prune blocked: {exc}", file=os.sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
