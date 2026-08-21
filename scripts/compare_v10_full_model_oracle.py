#!/usr/bin/env python3
"""Fail-closed, byte-exact comparison of two indexed safetensors model trees.

The verifier is intentionally independent of the training engine.  It validates
each shard index against every shard header, compares every tensor through
bounded CPU slices, binds both complete model-tree inventories and explicit
config/source/run evidence files, and publishes one atomic JSON receipt.

Only a ``PASS`` receipt returns zero.  A model difference returns one; invalid
or unstable evidence returns two.  Existing receipts are never replaced unless
``--overwrite`` is explicit.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import stat
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any

RECEIPT_FORMAT = "latent-workspace-v10-full-model-oracle-comparison-v1"
DEFAULT_MAX_WORKING_SET_BYTES = 64 * 1024 * 1024
OLD_D5_ENGINE_SHA256 = "d5f2ef1d137f5db1a4746a370758f39b62d7d128d7d0bf0101948226186be69b"
SAFETENSORS_DTYPE_BYTES = {
    "BOOL": 1,
    "F8_E4M3": 1,
    "F8_E4M3FN": 1,
    "F8_E5M2": 1,
    "I8": 1,
    "U8": 1,
    "BF16": 2,
    "F16": 2,
    "I16": 2,
    "U16": 2,
    "F32": 4,
    "I32": 4,
    "U32": 4,
    "F64": 8,
    "I64": 8,
    "U64": 8,
}
TENSOR_COMPARISON_FIXED_REDUCTION_BYTES = 8
RESUME_SIGNATURE_TRAIN_EXCLUSIONS = frozenset(
    {
        "output_dir",
        "device",
        "log_every",
        "eval_every",
        "save_every",
        "save_every_minutes",
        "eval_batches",
        "resume_from",
        "keep_last_checkpoints",
        "heartbeat_every_seconds",
        "minimum_free_disk_gb",
        "save_best",
        "best_metric",
        "greater_is_better",
        "log_memory",
        "allow_schedule_extension",
        "strict_source_resume",
        "strict_torch_resume",
        "save_optimizer",
        "save_frozen_base",
        "max_shard_size",
        "checkpoint_headroom_ratio",
        "nonfinite_policy",
        "max_nonfinite_skips",
    }
)
RESUME_SIGNATURE_DATA_EXCLUSIONS = frozenset(
    {
        "train_files",
        "eval_files",
        "verify_samples",
        "validate_json_on_index",
        "num_workers",
        "pin_memory",
        "persistent_workers",
        "prefetch_factor",
        "loader_timeout_seconds",
        "fingerprint_mode",
        "fingerprint_bytes",
    }
)
CROSS_OFFLOAD_CONFIG_DIFF_ALLOWLIST = frozenset(
    {
        "train.gradient_accumulation_offload",
        "train.output_dir",
        "train.resume_from",
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
# This is deliberately explicit rather than prefix-based. A newly introduced
# metric remains equality-gated until this list is reviewed and changed.
METRIC_DYNAMIC_FIELDS = frozenset(
    {
        "checkpoint",
        "cuda_allocated_gb",
        "cuda_max_allocated_gb",
        "cuda_max_reserved_gb",
        "cuda_peak_allocated_gb",
        "cuda_reserved_gb",
        "elapsed_seconds",
        "output_dir",
        "path",
        "resume_from",
        "run_id",
        "time",
        "tokens_per_second",
    }
)


class OracleVerificationError(RuntimeError):
    """A required model, provenance, stability, or publication gate failed."""


class ExistingOutputError(OracleVerificationError):
    """The requested output already exists without explicit overwrite consent."""


@dataclass(frozen=True)
class TensorEntry:
    name: str
    shard: Path
    relative_shard: str
    dtype: str
    shape: tuple[int, ...]
    numel: int
    element_size: int


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def engine_stable_hash(value: Mapping[str, Any]) -> str:
    """Reproduce engine.stable_hash without importing the training engine."""

    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def engine_resume_signature(config: Mapping[str, Any], *, ignore_schedule_horizon: bool) -> str:
    """Reproduce engine.resume_signature over a saved experiment config."""

    required = {
        "model",
        "data",
        "workspace",
        "functional",
        "train",
        "attribution",
        "induction",
    }
    missing = required - set(config)
    if missing or any(not isinstance(config.get(key), Mapping) for key in required):
        raise OracleVerificationError(
            "Experiment config lacks the complete mapping surface required for resume signatures."
        )
    train = copy.deepcopy(dict(config["train"]))
    for key in RESUME_SIGNATURE_TRAIN_EXCLUSIONS:
        train.pop(key, None)
    if ignore_schedule_horizon:
        train.pop("epochs", None)
        train.pop("max_steps", None)
    data = {
        key: value
        for key, value in config["data"].items()
        if key not in RESUME_SIGNATURE_DATA_EXCLUSIONS
    }
    payload = {
        "model": dict(config["model"]),
        "data": data,
        "workspace": dict(config["workspace"]),
        "functional": dict(config["functional"]),
        "train": train,
        "attribution": dict(config["attribution"]),
        "induction": dict(config["induction"]),
    }
    return engine_stable_hash(payload)


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


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise OracleVerificationError(f"JSON object contains duplicate key {key!r}.")
        value[key] = item
    return value


def read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_duplicate_rejecting_object,
        )
    except OracleVerificationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OracleVerificationError(
            f"Could not read {label} JSON: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise OracleVerificationError(f"{label} JSON must contain an object.")
    return value


def _relative(repo_root: Path, path: Path, *, label: str) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise OracleVerificationError(f"{label} escapes --repo-root.") from exc


def _resolve_inside(repo_root: Path, value: str | Path, *, label: str) -> Path:
    raw = Path(value)
    candidate = raw.resolve() if raw.is_absolute() else (repo_root / raw).resolve()
    _relative(repo_root, candidate, label=label)
    return candidate


def _resolve_output(repo_root: Path, value: str | Path) -> Path:
    """Resolve the output parent without following the final path component."""

    raw = Path(value)
    if raw.name in {"", ".", ".."}:
        raise OracleVerificationError("Receipt output must name a JSON file.")
    lexical = raw if raw.is_absolute() else repo_root / raw
    parent = lexical.parent.resolve()
    _relative(repo_root, parent, label="receipt output parent")
    return parent / lexical.name


def _require_plain_directory(repo_root: Path, value: str | Path, *, label: str) -> Path:
    path = _resolve_inside(repo_root, value, label=label)
    if path.is_symlink() or not path.is_dir():
        raise OracleVerificationError(f"{label} must be a non-symlink directory.")
    return path


def _require_plain_file(repo_root: Path, value: str | Path, *, label: str) -> Path:
    path = _resolve_inside(repo_root, value, label=label)
    if path.is_symlink() or not path.is_file():
        raise OracleVerificationError(f"{label} must be a regular non-symlink file.")
    mode = path.stat().st_mode
    if not stat.S_ISREG(mode):
        raise OracleVerificationError(f"{label} is not a regular file.")
    return path


def file_record(repo_root: Path, path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise OracleVerificationError(f"{label} must remain a regular non-symlink file.")
    file_stat = path.stat()
    return {
        "path": _relative(repo_root, path, label=label),
        "bytes": file_stat.st_size,
        "sha256": sha256_file(path),
    }


def model_tree_inventory(root: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    directory_count = 1
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        mode = path.lstat().st_mode
        relative = path.relative_to(root).as_posix()
        if stat.S_ISLNK(mode):
            raise OracleVerificationError(f"Model tree contains symlink: {relative}")
        if stat.S_ISDIR(mode):
            directory_count += 1
            continue
        if not stat.S_ISREG(mode):
            raise OracleVerificationError(f"Model tree contains special file: {relative}")
        file_stat = path.stat()
        if file_stat.st_nlink != 1:
            raise OracleVerificationError(f"Model tree contains multiply linked file: {relative}")
        records.append(
            {
                "path": relative,
                "bytes": file_stat.st_size,
                "sha256": sha256_file(path),
            }
        )
    if not records:
        raise OracleVerificationError("Model tree contains no regular files.")
    return {
        "algorithm": (
            "Recursive regular files sorted by relative path; each record contains path, "
            "bytes, and SHA-256; inventory SHA-256 covers canonical JSON records."
        ),
        "file_count": len(records),
        "directory_count_including_root": directory_count,
        "logical_bytes": sum(int(record["bytes"]) for record in records),
        "inventory_sha256": sha256_bytes(canonical_json_bytes(records)),
        "files": records,
    }


def _safe_index_shard(root: Path, index_path: Path, raw: str) -> Path:
    relative = PurePosixPath(raw)
    if (
        not raw
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.suffix != ".safetensors"
    ):
        raise OracleVerificationError(f"Unsafe shard path in safetensors index: {raw!r}")
    candidate = index_path.parent.joinpath(*relative.parts)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise OracleVerificationError("Safetensors index shard path escapes model tree.") from exc
    return candidate


def inspect_indexed_model(
    root: Path,
    *,
    tree_inventory: Mapping[str, Any],
) -> tuple[dict[str, TensorEntry], dict[str, Any]]:
    try:
        from safetensors import safe_open
    except ImportError as exc:
        raise OracleVerificationError("The safetensors package is required.") from exc

    index_paths = sorted(root.rglob("*.safetensors.index.json"))
    if len(index_paths) != 1:
        raise OracleVerificationError(
            "Model tree must contain exactly one *.safetensors.index.json file; "
            f"observed {len(index_paths)}."
        )
    index_path = index_paths[0]
    if index_path.is_symlink() or not index_path.is_file():
        raise OracleVerificationError("Safetensors index must be a regular non-symlink file.")
    index = read_json_object(index_path, label="safetensors index")
    inventory_records = {
        str(record["path"]): record
        for record in tree_inventory.get("files", [])
        if isinstance(record, Mapping) and isinstance(record.get("path"), str)
    }
    if len(inventory_records) != tree_inventory.get("file_count"):
        raise OracleVerificationError("Model-tree inventory records are incomplete or duplicate.")
    index_relative = index_path.relative_to(root).as_posix()
    if index_relative not in inventory_records:
        raise OracleVerificationError("Safetensors index is absent from model-tree inventory.")
    weight_map = index.get("weight_map")
    if not isinstance(weight_map, Mapping) or not weight_map:
        raise OracleVerificationError("Safetensors index must contain a non-empty weight_map.")

    expected_by_shard: dict[Path, set[str]] = {}
    for tensor_name, shard_name in weight_map.items():
        if not isinstance(tensor_name, str) or not tensor_name:
            raise OracleVerificationError("Safetensors index contains an invalid tensor name.")
        if not isinstance(shard_name, str):
            raise OracleVerificationError(
                f"Safetensors index shard for {tensor_name!r} is not a string."
            )
        shard = _safe_index_shard(root, index_path, shard_name)
        if shard.is_symlink() or not shard.is_file() or shard.stat().st_size <= 0:
            raise OracleVerificationError(
                f"Safetensors index references missing, empty, or symlink shard: {shard_name!r}"
            )
        expected_by_shard.setdefault(shard, set()).add(tensor_name)

    actual_shards = {
        path for path in root.rglob("*.safetensors") if path.is_file() and not path.is_symlink()
    }
    symlink_shards = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*.safetensors")
        if path.is_symlink()
    ]
    if symlink_shards:
        raise OracleVerificationError(
            f"Model tree contains symlink safetensors shard: {symlink_shards[0]}"
        )
    referenced_shards = set(expected_by_shard)
    if actual_shards != referenced_shards:
        missing = len(referenced_shards - actual_shards)
        unexpected = len(actual_shards - referenced_shards)
        raise OracleVerificationError(
            "Safetensors index/shard set mismatch: "
            f"missing_shards={missing}, unexpected_shards={unexpected}."
        )

    entries: dict[str, TensorEntry] = {}
    shard_records: list[dict[str, Any]] = []
    for shard in sorted(referenced_shards, key=lambda item: item.relative_to(root).as_posix()):
        relative_shard = shard.relative_to(root).as_posix()
        if relative_shard not in inventory_records:
            raise OracleVerificationError(
                f"Safetensors shard is absent from model-tree inventory: {relative_shard}"
            )
        expected_names = expected_by_shard[shard]
        try:
            with safe_open(str(shard), framework="pt", device="cpu") as handle:
                actual_names = set(handle.keys())
                if actual_names != expected_names:
                    raise OracleVerificationError(
                        "Safetensors index/header key mismatch for "
                        f"{relative_shard}: missing={len(expected_names - actual_names)}, "
                        f"unexpected={len(actual_names - expected_names)}."
                    )
                for name in sorted(actual_names):
                    tensor_slice = handle.get_slice(name)
                    shape = tuple(int(value) for value in tensor_slice.get_shape())
                    dtype = str(tensor_slice.get_dtype())
                    element_size = SAFETENSORS_DTYPE_BYTES.get(dtype)
                    if element_size is None:
                        raise OracleVerificationError(
                            f"Unsupported safetensors dtype {dtype!r} for {name!r}."
                        )
                    entries[name] = TensorEntry(
                        name=name,
                        shard=shard,
                        relative_shard=relative_shard,
                        dtype=dtype,
                        shape=shape,
                        numel=int(math.prod(shape)),
                        element_size=element_size,
                    )
        except OracleVerificationError:
            raise
        except Exception as exc:
            raise OracleVerificationError(
                f"Could not inspect safetensors shard {relative_shard}: {type(exc).__name__}: {exc}"
            ) from exc
        shard_records.append(
            {
                "path": relative_shard,
                "bytes": shard.stat().st_size,
                "sha256": inventory_records[relative_shard]["sha256"],
                "tensor_count": len(expected_names),
            }
        )

    schema = [
        {
            "name": name,
            "dtype": entries[name].dtype,
            "shape": list(entries[name].shape),
            "numel": entries[name].numel,
            "element_size_bytes": entries[name].element_size,
        }
        for name in sorted(entries)
    ]
    weight_map_records = [
        {"tensor": name, "shard": str(weight_map[name])} for name in sorted(weight_map)
    ]
    return entries, {
        "index_path": index_relative,
        "index_sha256": inventory_records[index_relative]["sha256"],
        "weight_map_sha256": sha256_bytes(canonical_json_bytes(weight_map_records)),
        "tensor_count": len(entries),
        "total_numel": sum(entry.numel for entry in entries.values()),
        "tensor_schema_sha256": sha256_bytes(canonical_json_bytes(schema)),
        "shard_count": len(shard_records),
        "shards": shard_records,
    }


def _tensor_comparison_buffer_budget(element_count: int, element_size: int) -> dict[str, int]:
    input_slice_bytes = 2 * element_count * element_size
    contiguous_copy_bytes = 2 * element_count * element_size
    byte_inequality_mask_bytes = element_count * element_size
    per_element_changed_mask_bytes = element_count
    total = (
        input_slice_bytes
        + contiguous_copy_bytes
        + byte_inequality_mask_bytes
        + per_element_changed_mask_bytes
        + TENSOR_COMPARISON_FIXED_REDUCTION_BYTES
    )
    return {
        "input_slice_bytes": input_slice_bytes,
        "worst_case_contiguous_copy_bytes": contiguous_copy_bytes,
        "byte_inequality_mask_bytes": byte_inequality_mask_bytes,
        "per_element_changed_mask_bytes": per_element_changed_mask_bytes,
        "fixed_scalar_reduction_bytes": TENSOR_COMPARISON_FIXED_REDUCTION_BYTES,
        "total_bytes": total,
    }


def _first_true_index(mask: Any) -> int:
    """Locate the first true entry using scalar reductions, never an index vector."""

    lower = 0
    upper = int(mask.numel())
    if upper <= 0 or not bool(mask.any().item()):
        raise OracleVerificationError("First-mismatch search received an empty/false mask.")
    while upper - lower > 1:
        midpoint = lower + (upper - lower) // 2
        if bool(mask[lower:midpoint].any().item()):
            upper = midpoint
        else:
            lower = midpoint
    return lower


def _byte_mismatch_count(
    candidate: TensorEntry,
    oracle: TensorEntry,
    *,
    max_working_set_bytes: int,
) -> tuple[int, int | None, int]:
    try:
        import torch
        from safetensors import safe_open
    except ImportError as exc:
        raise OracleVerificationError("torch and safetensors are required.") from exc

    if max_working_set_bytes <= 0:
        raise OracleVerificationError("--max-working-set-bytes must be positive.")
    if candidate.numel == 0:
        return 0, None, 0

    def compare_chunk(left: Any, right: Any, *, element_offset: int) -> tuple[int, int | None, int]:
        if tuple(left.shape) != tuple(right.shape) or left.dtype != right.dtype:
            raise OracleVerificationError(
                f"Tensor schema changed while reading {candidate.name!r}."
            )
        element_size = int(left.element_size())
        if element_size != candidate.element_size:
            raise OracleVerificationError(
                f"Tensor element size changed while reading {candidate.name!r}."
            )
        element_count = int(left.numel())
        budget = _tensor_comparison_buffer_budget(element_count, element_size)
        if budget["total_bytes"] > max_working_set_bytes:
            raise OracleVerificationError(
                "Tensor comparison chunk exceeds --max-working-set-bytes for "
                f"{candidate.name!r}: {budget['total_bytes']} > {max_working_set_bytes}."
            )
        left_contiguous = left.contiguous()
        right_contiguous = right.contiguous()
        left_bytes = left_contiguous.view(torch.uint8).reshape(-1, element_size)
        right_bytes = right_contiguous.view(torch.uint8).reshape(-1, element_size)
        byte_differences = left_bytes.ne(right_bytes)
        changed = byte_differences.any(dim=1)
        count = int(changed.sum().item())
        first: int | None = None
        if count:
            first = element_offset + _first_true_index(changed)
        return count, first, budget["total_bytes"]

    try:
        with (
            safe_open(str(candidate.shard), framework="pt", device="cpu") as candidate_handle,
            safe_open(str(oracle.shard), framework="pt", device="cpu") as oracle_handle,
        ):
            if not candidate.shape:
                scalar_budget = _tensor_comparison_buffer_budget(1, candidate.element_size)
                if scalar_budget["total_bytes"] > max_working_set_bytes:
                    raise OracleVerificationError(
                        "Scalar tensor comparison exceeds --max-working-set-bytes for "
                        f"{candidate.name!r}: {scalar_budget['total_bytes']} > "
                        f"{max_working_set_bytes}."
                    )
                return compare_chunk(
                    candidate_handle.get_tensor(candidate.name),
                    oracle_handle.get_tensor(oracle.name),
                    element_offset=0,
                )

            candidate_slice = candidate_handle.get_slice(candidate.name)
            oracle_slice = oracle_handle.get_slice(oracle.name)
            row_elements = int(math.prod(candidate.shape[1:]))
            variable_bytes_per_row = row_elements * (5 * candidate.element_size + 1)
            estimated_bytes_per_row = (
                variable_bytes_per_row + TENSOR_COMPARISON_FIXED_REDUCTION_BYTES
            )
            if estimated_bytes_per_row > max_working_set_bytes:
                raise OracleVerificationError(
                    "A single tensor row exceeds --max-working-set-bytes for "
                    f"{candidate.name!r}: {estimated_bytes_per_row} > "
                    f"{max_working_set_bytes}."
                )
            rows_per_chunk = max(
                1,
                (max_working_set_bytes - TENSOR_COMPARISON_FIXED_REDUCTION_BYTES)
                // variable_bytes_per_row,
            )
            mismatch_count = 0
            first_mismatch: int | None = None
            max_chunk_budget = 0
            for start in range(0, candidate.shape[0], rows_per_chunk):
                end = min(candidate.shape[0], start + rows_per_chunk)
                count, first, chunk_budget = compare_chunk(
                    candidate_slice[start:end],
                    oracle_slice[start:end],
                    element_offset=start * row_elements,
                )
                max_chunk_budget = max(max_chunk_budget, chunk_budget)
                mismatch_count += count
                if first_mismatch is None and first is not None:
                    first_mismatch = first
            return mismatch_count, first_mismatch, max_chunk_budget
    except OracleVerificationError:
        raise
    except Exception as exc:
        raise OracleVerificationError(
            f"Could not compare tensor {candidate.name!r}: {type(exc).__name__}: {exc}"
        ) from exc


def compare_models(
    candidate_root: Path,
    oracle_root: Path,
    *,
    candidate_tree_inventory: Mapping[str, Any],
    oracle_tree_inventory: Mapping[str, Any],
    max_working_set_bytes: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    candidate_entries, candidate_summary = inspect_indexed_model(
        candidate_root,
        tree_inventory=candidate_tree_inventory,
    )
    oracle_entries, oracle_summary = inspect_indexed_model(
        oracle_root,
        tree_inventory=oracle_tree_inventory,
    )
    names = sorted(set(candidate_entries) | set(oracle_entries))
    counts = {
        "candidate_tensor_count": len(candidate_entries),
        "oracle_tensor_count": len(oracle_entries),
        "shared_tensor_count": len(set(candidate_entries) & set(oracle_entries)),
        "missing_candidate_tensor_count": 0,
        "unexpected_candidate_tensor_count": 0,
        "schema_mismatch_tensor_count": 0,
        "shape_mismatch_tensor_count": 0,
        "dtype_mismatch_tensor_count": 0,
        "byte_compared_tensor_count": 0,
        "byte_compared_element_count": 0,
        "byte_exact_tensor_count": 0,
        "byte_mismatch_tensor_count": 0,
        "byte_mismatch_element_count": 0,
        "total_mismatch_tensor_count": 0,
    }
    first_mismatch: dict[str, Any] | None = None
    max_estimated_tensor_buffer_bytes = 0

    for name in names:
        candidate = candidate_entries.get(name)
        oracle = oracle_entries.get(name)
        if candidate is None:
            counts["missing_candidate_tensor_count"] += 1
            counts["total_mismatch_tensor_count"] += 1
            if first_mismatch is None:
                first_mismatch = {"kind": "missing_candidate_tensor", "tensor": name}
            continue
        if oracle is None:
            counts["unexpected_candidate_tensor_count"] += 1
            counts["total_mismatch_tensor_count"] += 1
            if first_mismatch is None:
                first_mismatch = {"kind": "unexpected_candidate_tensor", "tensor": name}
            continue

        shape_mismatch = candidate.shape != oracle.shape
        dtype_mismatch = candidate.dtype != oracle.dtype
        if shape_mismatch or dtype_mismatch:
            counts["schema_mismatch_tensor_count"] += 1
            counts["shape_mismatch_tensor_count"] += int(shape_mismatch)
            counts["dtype_mismatch_tensor_count"] += int(dtype_mismatch)
            counts["total_mismatch_tensor_count"] += 1
            if first_mismatch is None:
                first_mismatch = {
                    "kind": "tensor_schema",
                    "tensor": name,
                    "candidate_dtype": candidate.dtype,
                    "oracle_dtype": oracle.dtype,
                    "candidate_shape": list(candidate.shape),
                    "oracle_shape": list(oracle.shape),
                }
            continue

        mismatch_count, first_element, tensor_buffer_bytes = _byte_mismatch_count(
            candidate,
            oracle,
            max_working_set_bytes=max_working_set_bytes,
        )
        max_estimated_tensor_buffer_bytes = max(
            max_estimated_tensor_buffer_bytes, tensor_buffer_bytes
        )
        counts["byte_compared_tensor_count"] += 1
        counts["byte_compared_element_count"] += candidate.numel
        if mismatch_count:
            counts["byte_mismatch_tensor_count"] += 1
            counts["byte_mismatch_element_count"] += mismatch_count
            counts["total_mismatch_tensor_count"] += 1
            if first_mismatch is None:
                first_mismatch = {
                    "kind": "tensor_bytes",
                    "tensor": name,
                    "first_flat_element_index": first_element,
                }
        else:
            counts["byte_exact_tensor_count"] += 1

    passed = counts["total_mismatch_tensor_count"] == 0
    result = {
        "passed": passed,
        "comparison": "tensor_name_dtype_shape_and_all_element_bytes_exact",
        "tensor_buffer_budget": {
            "scope": "comparison_tensor_payloads_and_byte_masks",
            "max_working_set_bytes": max_working_set_bytes,
            "worst_case_equation": (
                "elements * (2 * element_bytes input_slices + 2 * element_bytes "
                "contiguous_copies + element_bytes byte_inequality_mask + 1 "
                "per_element_changed_mask) + 8 scalar_reduction_bytes"
            ),
            "max_estimated_tensor_buffer_bytes": max_estimated_tensor_buffer_bytes,
            "within_budget": max_estimated_tensor_buffer_bytes <= max_working_set_bytes,
            "first_mismatch_search": (
                "binary_any_scalar_reductions_over_existing_mask_no_index_vector"
            ),
        },
        "counts": counts,
        "first_mismatch": first_mismatch,
    }
    return result, candidate_summary, oracle_summary


def _load_torch_state(path: Path, *, weights_only: bool, label: str) -> Any:
    try:
        import torch
    except ImportError as exc:
        raise OracleVerificationError("Bundle state comparison requires torch.") from exc
    try:
        return torch.load(path, map_location="cpu", weights_only=weights_only)
    except TypeError:  # pragma: no cover - compatibility with older torch
        return torch.load(path, map_location="cpu")
    except Exception as exc:
        raise OracleVerificationError(
            f"Could not load {label}: {type(exc).__name__}: {exc}"
        ) from exc


def _new_state_counts() -> dict[str, int]:
    return {
        "visited_node_count": 0,
        "excluded_path_count": 0,
        "tensor_count": 0,
        "tensor_element_count": 0,
        "mapping_key_mismatch_count": 0,
        "sequence_length_mismatch_count": 0,
        "type_mismatch_count": 0,
        "tensor_schema_mismatch_count": 0,
        "tensor_byte_mismatch_count": 0,
        "scalar_mismatch_count": 0,
        "total_mismatch_count": 0,
    }


def compare_nested_state(
    candidate: Any,
    oracle: Any,
    *,
    excluded_paths: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Compare nested torch state exactly while returning only counts and the first mismatch."""

    try:
        import torch
    except ImportError as exc:
        raise OracleVerificationError("Bundle state comparison requires torch.") from exc

    counts = _new_state_counts()
    first_mismatch: dict[str, Any] | None = None

    def mismatch(path: str, kind: str) -> None:
        nonlocal first_mismatch
        counts["total_mismatch_count"] += 1
        if first_mismatch is None:
            first_mismatch = {"path": path, "kind": kind}

    def visit(left: Any, right: Any, path: str) -> None:
        counts["visited_node_count"] += 1
        if path in excluded_paths:
            counts["excluded_path_count"] += 1
            return
        if isinstance(left, torch.Tensor) or isinstance(right, torch.Tensor):
            counts["tensor_count"] += 1
            if not isinstance(left, torch.Tensor) or not isinstance(right, torch.Tensor):
                counts["type_mismatch_count"] += 1
                mismatch(path, "type")
                return
            counts["tensor_element_count"] += int(left.numel())
            if (
                left.shape != right.shape
                or left.dtype != right.dtype
                or left.layout != right.layout
            ):
                counts["tensor_schema_mismatch_count"] += 1
                mismatch(path, "tensor_schema")
                return
            left_contiguous = left.detach().cpu().contiguous()
            right_contiguous = right.detach().cpu().contiguous()
            if left_contiguous.dim() == 0:
                left_contiguous = left_contiguous.reshape(1)
                right_contiguous = right_contiguous.reshape(1)
            left_bytes = left_contiguous.view(torch.uint8).reshape(-1)
            right_bytes = right_contiguous.view(torch.uint8).reshape(-1)
            if not torch.equal(left_bytes, right_bytes):
                counts["tensor_byte_mismatch_count"] += 1
                mismatch(path, "tensor_bytes")
            return
        if isinstance(left, Mapping) or isinstance(right, Mapping):
            if not isinstance(left, Mapping) or not isinstance(right, Mapping):
                counts["type_mismatch_count"] += 1
                mismatch(path, "type")
                return
            left_keys = set(left)
            right_keys = set(right)
            different_keys = left_keys ^ right_keys
            if different_keys:
                counts["mapping_key_mismatch_count"] += len(different_keys)
                first_key = min(different_keys, key=lambda item: (type(item).__name__, repr(item)))
                mismatch(f"{path}.{first_key}", "mapping_key")
            for key in sorted(
                left_keys & right_keys,
                key=lambda item: (type(item).__name__, repr(item)),
            ):
                visit(left[key], right[key], f"{path}.{key}")
            return
        if isinstance(left, (list, tuple)) or isinstance(right, (list, tuple)):
            if type(left) is not type(right):
                counts["type_mismatch_count"] += 1
                mismatch(path, "sequence_type")
                return
            if len(left) != len(right):
                counts["sequence_length_mismatch_count"] += 1
                mismatch(path, "sequence_length")
            for index, (left_item, right_item) in enumerate(zip(left, right, strict=False)):
                visit(left_item, right_item, f"{path}[{index}]")
            return
        if type(left) is not type(right):
            counts["type_mismatch_count"] += 1
            mismatch(path, "type")
        elif left != right:
            counts["scalar_mismatch_count"] += 1
            mismatch(path, "scalar")

    visit(candidate, oracle, "$")
    return {
        "passed": counts["total_mismatch_count"] == 0,
        "comparison": "recursive_type_schema_and_tensor_bytes_exact",
        "excluded_paths": sorted(excluded_paths),
        "counts": counts,
        "first_mismatch": first_mismatch,
    }


def _validate_trainer_state(state: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(state, Mapping):
        raise OracleVerificationError(f"{label} trainer_state.pt must contain a mapping.")
    missing = TRAINER_REQUIRED_KEYS - set(state)
    if missing:
        raise OracleVerificationError(
            f"{label} trainer_state.pt lacks {len(missing)} required stable fields."
        )
    global_step = state.get("global_step")
    if isinstance(global_step, bool) or not isinstance(global_step, int) or global_step < 0:
        raise OracleVerificationError(f"{label} trainer global_step is invalid.")
    run_state = state.get("run_state")
    if not isinstance(run_state, Mapping):
        raise OracleVerificationError(f"{label} trainer run_state is invalid.")
    if run_state.get("global_step") != global_step:
        raise OracleVerificationError(f"{label} trainer/run_state global_step differs.")
    if not isinstance(run_state.get("run_id"), str) or not run_state.get("run_id"):
        raise OracleVerificationError(f"{label} trainer run_state.run_id is invalid.")
    world_size = state.get("world_size")
    if isinstance(world_size, bool) or not isinstance(world_size, int) or world_size < 1:
        raise OracleVerificationError(f"{label} trainer world_size is invalid.")
    if not isinstance(state.get("data_fingerprint"), Mapping):
        raise OracleVerificationError(f"{label} trainer data_fingerprint is invalid.")
    for field in ("resume_signature", "structural_resume_signature"):
        value = state.get(field)
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise OracleVerificationError(f"{label} trainer {field} is not a SHA-256 value.")
    return state


def _read_metrics(path: Path, *, label: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                value = json.loads(line, object_pairs_hook=_duplicate_rejecting_object)
                if not isinstance(value, dict):
                    raise OracleVerificationError(
                        f"{label} metrics line {line_number} is not an object."
                    )
                records.append(value)
    except OracleVerificationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OracleVerificationError(
            f"Could not read {label} metrics: {type(exc).__name__}: {exc}"
        ) from exc
    return records


def _stable_metric_index(
    records: Sequence[Mapping[str, Any]], *, label: str
) -> dict[tuple[str, int], dict[str, Any]]:
    result: dict[tuple[str, int], dict[str, Any]] = {}
    for record in records:
        split = record.get("split")
        step = record.get("step")
        if not isinstance(split, str):
            continue
        if isinstance(step, bool) or not isinstance(step, int):
            raise OracleVerificationError(f"{label} metric split record has invalid step.")
        key = (split, step)
        if key in result:
            raise OracleVerificationError(f"{label} metrics contain duplicate split/step key.")
        result[key] = {
            name: value for name, value in record.items() if name not in METRIC_DYNAMIC_FIELDS
        }
    if not result:
        raise OracleVerificationError(f"{label} metrics contain no stable split/step records.")
    return result


def compare_stable_metrics(candidate_path: Path, oracle_path: Path) -> dict[str, Any]:
    candidate_records = _read_metrics(candidate_path, label="candidate")
    oracle_records = _read_metrics(oracle_path, label="oracle")
    candidate = _stable_metric_index(candidate_records, label="candidate")
    oracle = _stable_metric_index(oracle_records, label="oracle")
    keys = sorted(set(candidate) | set(oracle))
    counts = {
        "candidate_raw_record_count": len(candidate_records),
        "oracle_raw_record_count": len(oracle_records),
        "candidate_stable_record_count": len(candidate),
        "oracle_stable_record_count": len(oracle),
        "missing_candidate_record_count": 0,
        "unexpected_candidate_record_count": 0,
        "value_mismatch_record_count": 0,
        "total_mismatch_record_count": 0,
    }
    first_mismatch: dict[str, Any] | None = None
    for key in keys:
        candidate_record = candidate.get(key)
        oracle_record = oracle.get(key)
        if candidate_record is None:
            counts["missing_candidate_record_count"] += 1
            counts["total_mismatch_record_count"] += 1
            if first_mismatch is None:
                first_mismatch = {"kind": "missing_candidate_record", "key": list(key)}
            continue
        if oracle_record is None:
            counts["unexpected_candidate_record_count"] += 1
            counts["total_mismatch_record_count"] += 1
            if first_mismatch is None:
                first_mismatch = {"kind": "unexpected_candidate_record", "key": list(key)}
            continue
        if candidate_record != oracle_record:
            counts["value_mismatch_record_count"] += 1
            counts["total_mismatch_record_count"] += 1
            fields = sorted(
                name
                for name in set(candidate_record) | set(oracle_record)
                if candidate_record.get(name) != oracle_record.get(name)
            )
            if first_mismatch is None:
                first_mismatch = {
                    "kind": "stable_record_values",
                    "key": list(key),
                    "mismatched_field_count": len(fields),
                    "first_mismatched_field": fields[0],
                }
    return {
        "passed": counts["total_mismatch_record_count"] == 0,
        "comparison": "split_step_records_exact_after_explicit_dynamic_field_exclusion",
        "ignored_dynamic_fields": sorted(METRIC_DYNAMIC_FIELDS),
        "counts": counts,
        "first_mismatch": first_mismatch,
    }


def _bundle_paths(repo_root: Path, run: str | Path, *, label: str) -> dict[str, Any]:
    root = _require_plain_directory(repo_root, run, label=f"{label} run root")
    final = _require_plain_directory(repo_root, root / "final", label=f"{label} final bundle")
    paths = {
        "root": root,
        "final": final,
        "base_model": _require_plain_directory(
            repo_root,
            final / "base_model",
            label=f"{label} final base_model",
        ),
        "completed": _require_plain_file(
            repo_root,
            final / "COMPLETED",
            label=f"{label} COMPLETED",
        ),
        "manifest": _require_plain_file(
            repo_root,
            final / "manifest.json",
            label=f"{label} manifest",
        ),
        "experiment_config": _require_plain_file(
            repo_root,
            final / "experiment_config.json",
            label=f"{label} experiment config",
        ),
        "workspace_state": _require_plain_file(
            repo_root,
            final / "workspace_state.pt",
            label=f"{label} workspace state",
        ),
        "trainer_state": _require_plain_file(
            repo_root,
            final / "trainer_state.pt",
            label=f"{label} trainer state",
        ),
        "metrics": _require_plain_file(
            repo_root,
            root / "metrics.jsonl",
            label=f"{label} metrics",
        ),
    }
    if paths["completed"].read_text(encoding="utf-8").strip() != "ok":
        raise OracleVerificationError(f"{label} final COMPLETED marker is invalid.")
    manifest = read_json_object(paths["manifest"], label=f"{label} manifest")
    if manifest.get("complete") is not True:
        raise OracleVerificationError(f"{label} final manifest is not complete.")
    paths["manifest_document"] = manifest
    return paths


def _bundle_artifact_inventory(
    repo_root: Path, paths: Mapping[str, Any], *, label: str
) -> dict[str, Any]:
    names = (
        "completed",
        "manifest",
        "experiment_config",
        "workspace_state",
        "trainer_state",
        "metrics",
    )
    records = [file_record(repo_root, paths[name], label=f"{label} {name}") for name in names]
    return {
        "file_count": len(records),
        "logical_bytes": sum(int(record["bytes"]) for record in records),
        "inventory_sha256": sha256_bytes(canonical_json_bytes(records)),
        "files": records,
    }


def _require_sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise OracleVerificationError(f"{label} is not a SHA-256 value.")
    return value


def _validate_bundle_manifest_and_config(paths: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    manifest = paths["manifest_document"]
    if not isinstance(manifest, Mapping):
        raise OracleVerificationError(f"{label} final manifest is not an object.")
    if manifest.get("format") != "latent-workspace-ft-bundle-v4":
        raise OracleVerificationError(f"{label} final manifest format is not bundle-v4.")
    if manifest.get("complete") is not True:
        raise OracleVerificationError(f"{label} final manifest complete is not exactly true.")
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise OracleVerificationError(f"{label} final manifest run_id is invalid.")
    global_step = manifest.get("global_step")
    if isinstance(global_step, bool) or not isinstance(global_step, int) or global_step < 0:
        raise OracleVerificationError(f"{label} final manifest global_step is invalid.")
    world_size = manifest.get("world_size")
    if isinstance(world_size, bool) or not isinstance(world_size, int) or world_size < 1:
        raise OracleVerificationError(f"{label} final manifest world_size is invalid.")
    data_fingerprint = manifest.get("data_fingerprint")
    if not isinstance(data_fingerprint, Mapping):
        raise OracleVerificationError(f"{label} final manifest data_fingerprint is invalid.")
    source_sha256 = _require_sha256(
        manifest.get("source_sha256"), label=f"{label} final manifest source_sha256"
    )
    manifest_config_sha256 = _require_sha256(
        manifest.get("config_sha256"), label=f"{label} final manifest config_sha256"
    )
    manifest_resume_signature = _require_sha256(
        manifest.get("resume_signature"),
        label=f"{label} final manifest resume_signature",
    )
    manifest_structural_signature = _require_sha256(
        manifest.get("structural_resume_signature"),
        label=f"{label} final manifest structural_resume_signature",
    )
    config = read_json_object(paths["experiment_config"], label=f"{label} final experiment config")
    computed_config_sha256 = engine_stable_hash(config)
    if manifest_config_sha256 != computed_config_sha256:
        raise OracleVerificationError(
            f"{label} final manifest config_sha256 does not bind experiment_config.json."
        )
    computed_resume_signature = engine_resume_signature(config, ignore_schedule_horizon=False)
    computed_structural_signature = engine_resume_signature(config, ignore_schedule_horizon=True)
    if manifest_resume_signature != computed_resume_signature:
        raise OracleVerificationError(
            f"{label} final manifest resume_signature does not bind experiment_config.json."
        )
    if manifest_structural_signature != computed_structural_signature:
        raise OracleVerificationError(
            f"{label} final manifest structural_resume_signature does not bind "
            "experiment_config.json."
        )
    return {
        "manifest": {
            "format": "latent-workspace-ft-bundle-v4",
            "complete": True,
            "run_id": run_id,
            "global_step": global_step,
            "world_size": world_size,
            "data_fingerprint_sha256": engine_stable_hash(dict(data_fingerprint)),
            "data_fingerprint_sha256_algorithm": (
                "sha256(json.dumps(object,sort_keys=True,ensure_ascii=False).utf8)"
            ),
            "source_sha256": source_sha256,
            "config_sha256": manifest_config_sha256,
            "resume_signature": manifest_resume_signature,
            "structural_resume_signature": manifest_structural_signature,
        },
        "experiment_config": {
            "semantic_hash_algorithm": (
                "sha256(json.dumps(object,sort_keys=True,ensure_ascii=False).utf8)"
            ),
            "computed_config_sha256": computed_config_sha256,
            "manifest_config_sha256_exact": True,
            "computed_resume_signature": computed_resume_signature,
            "manifest_resume_signature_exact": True,
            "computed_structural_resume_signature": computed_structural_signature,
            "manifest_structural_resume_signature_exact": True,
        },
        "_manifest_data_fingerprint": dict(data_fingerprint),
    }


def _bind_trainer_to_manifest(
    trainer: Mapping[str, Any],
    provenance: Mapping[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    manifest = provenance["manifest"]
    run_state = trainer["run_state"]
    checks = {
        "global_step_exact": trainer["global_step"] == manifest["global_step"],
        "run_state_run_id_exact": run_state["run_id"] == manifest["run_id"],
        "world_size_exact": trainer["world_size"] == manifest["world_size"],
        "data_fingerprint_exact": (
            trainer["data_fingerprint"] == provenance["_manifest_data_fingerprint"]
        ),
        "resume_signature_exact": (trainer["resume_signature"] == manifest["resume_signature"]),
        "structural_resume_signature_exact": (
            trainer["structural_resume_signature"] == manifest["structural_resume_signature"]
        ),
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        raise OracleVerificationError(
            f"{label} trainer_state.pt does not bind its final manifest: {failed[0]}."
        )
    return {"passed": True, "checks": checks}


_MISSING = object()


def _semantic_json_differences(
    candidate: Any,
    oracle: Any,
    *,
    path: tuple[str, ...] = (),
) -> list[tuple[tuple[str, ...], Any, Any]]:
    """Return leaf-level semantic JSON differences without serializing values."""

    if candidate is _MISSING or oracle is _MISSING:
        return [(path, candidate, oracle)]
    if isinstance(candidate, Mapping) and isinstance(oracle, Mapping):
        differences: list[tuple[tuple[str, ...], Any, Any]] = []
        for key in sorted(set(candidate) | set(oracle)):
            differences.extend(
                _semantic_json_differences(
                    candidate.get(key, _MISSING),
                    oracle.get(key, _MISSING),
                    path=(*path, str(key)),
                )
            )
        return differences
    if type(candidate) is not type(oracle) or candidate != oracle:
        return [(path, candidate, oracle)]
    return []


def _json_value_binding(value: Any, *, disclose: bool) -> dict[str, Any]:
    if value is _MISSING:
        return {"present": False, "canonical_json_sha256": None}
    result = {
        "present": True,
        "canonical_json_sha256": sha256_bytes(canonical_json_bytes(value)),
    }
    if disclose:
        result["value"] = value
    else:
        result["value_disclosure"] = "sha256_only_to_keep_receipt_path_free"
    return result


def _cross_offload_config_comparison(
    candidate_path: Path,
    oracle_path: Path,
    *,
    oracle_old_d5_bound: bool,
) -> dict[str, Any]:
    candidate = read_json_object(candidate_path, label="candidate experiment config")
    oracle = read_json_object(oracle_path, label="oracle experiment config")
    candidate_train = candidate.get("train")
    oracle_train = oracle.get("train")
    if not isinstance(candidate_train, Mapping):
        raise OracleVerificationError("Candidate experiment config train must be an object.")
    if not isinstance(oracle_train, Mapping):
        raise OracleVerificationError("Oracle experiment config train must be an object.")
    candidate_offload = candidate_train.get("gradient_accumulation_offload", _MISSING)
    if candidate_offload != "cpu":
        raise OracleVerificationError(
            "Cross-offload parity requires candidate train.gradient_accumulation_offload='cpu'."
        )
    oracle_offload = oracle_train.get("gradient_accumulation_offload", _MISSING)
    legacy_none_applied = oracle_offload is _MISSING
    if legacy_none_applied and not oracle_old_d5_bound:
        raise OracleVerificationError(
            "A missing oracle train.gradient_accumulation_offload is allowed only when "
            "the oracle final manifest.source_sha256 is the legacy d5 engine and bound "
            "oracle run/source evidence contains that same identity."
        )
    if not legacy_none_applied and oracle_offload != "none":
        raise OracleVerificationError(
            "Cross-offload parity requires oracle train.gradient_accumulation_offload='none'."
        )

    effective_oracle = copy.deepcopy(oracle)
    if legacy_none_applied:
        effective_oracle["train"]["gradient_accumulation_offload"] = "none"
    raw_differences = _semantic_json_differences(candidate, effective_oracle)
    observed_paths = {".".join(path) for path, _, _ in raw_differences}
    unexpected = sorted(observed_paths - CROSS_OFFLOAD_CONFIG_DIFF_ALLOWLIST)
    if unexpected:
        raise OracleVerificationError(
            "Cross-offload experiment configs contain "
            f"{len(unexpected)} non-allowlisted semantic difference(s); "
            f"first={unexpected[0]}."
        )

    differences: list[dict[str, Any]] = []
    for path, candidate_value, effective_oracle_value in raw_differences:
        dotted = ".".join(path)
        disclose = dotted == "train.gradient_accumulation_offload"
        original_oracle_value = (
            oracle_offload
            if dotted == "train.gradient_accumulation_offload"
            else effective_oracle_value
        )
        record = {
            "path": dotted,
            "candidate": _json_value_binding(candidate_value, disclose=disclose),
            "oracle": _json_value_binding(original_oracle_value, disclose=disclose),
        }
        if dotted == "train.gradient_accumulation_offload" and legacy_none_applied:
            record["oracle_effective"] = _json_value_binding("none", disclose=True)
            record["oracle_effective_value_source"] = "legacy_d5_missing_field_default"
        differences.append(record)

    return {
        "passed": True,
        "comparison": "semantic_exact_except_explicit_cross_offload_allowlist",
        "allowed_difference_paths": sorted(CROSS_OFFLOAD_CONFIG_DIFF_ALLOWLIST),
        "observed_difference_count": len(differences),
        "observed_differences": differences,
        "candidate_offload": "cpu",
        "oracle_effective_offload": "none",
        "oracle_offload_field_present": not legacy_none_applied,
        "oracle_legacy_d5_missing_field_default_applied": legacy_none_applied,
        "oracle_legacy_d5_missing_field_authorized": oracle_old_d5_bound,
    }


def _trainer_signature_bindings(
    candidate: Mapping[str, Any], oracle: Mapping[str, Any]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in ("resume_signature", "structural_resume_signature"):
        candidate_value = str(candidate[field])
        oracle_value = str(oracle[field])
        result[field] = {
            "candidate_value": candidate_value,
            "candidate_value_utf8_sha256": sha256_bytes(candidate_value.encode("utf-8")),
            "oracle_value": oracle_value,
            "oracle_value_utf8_sha256": sha256_bytes(oracle_value.encode("utf-8")),
            "values_equal": candidate_value == oracle_value,
        }
    return result


def compare_run_bundles(
    repo_root: Path,
    *,
    candidate_run: str | Path,
    oracle_run: str | Path,
    candidate_model_root: Path,
    oracle_model_root: Path,
    cross_offload_parity: bool,
    candidate_source_evidence_paths: Sequence[Path],
    oracle_source_evidence_paths: Sequence[Path],
) -> dict[str, Any]:
    candidate = _bundle_paths(repo_root, candidate_run, label="candidate")
    oracle = _bundle_paths(repo_root, oracle_run, label="oracle")
    if candidate["root"] == oracle["root"]:
        raise OracleVerificationError("Candidate and oracle run roots must be distinct.")
    if candidate["base_model"] != candidate_model_root:
        raise OracleVerificationError(
            "--candidate-model must equal --candidate-run/final/base_model."
        )
    if oracle["base_model"] != oracle_model_root:
        raise OracleVerificationError("--oracle-model must equal --oracle-run/final/base_model.")

    candidate_inventory_before = _bundle_artifact_inventory(
        repo_root, candidate, label="candidate bundle"
    )
    oracle_inventory_before = _bundle_artifact_inventory(repo_root, oracle, label="oracle bundle")
    candidate_provenance = _validate_bundle_manifest_and_config(candidate, label="candidate")
    oracle_provenance = _validate_bundle_manifest_and_config(oracle, label="oracle")
    candidate_source_bindings = _require_unambiguous_source_identity(
        repo_root,
        candidate_source_evidence_paths,
        expected_sha256=candidate_provenance["manifest"]["source_sha256"],
        label="candidate",
    )
    oracle_source_bindings = _require_unambiguous_source_identity(
        repo_root,
        oracle_source_evidence_paths,
        expected_sha256=oracle_provenance["manifest"]["source_sha256"],
        label="oracle",
    )
    candidate_provenance["manifest"]["source_identity_evidence_bindings"] = (
        candidate_source_bindings
    )
    oracle_provenance["manifest"]["source_identity_evidence_bindings"] = oracle_source_bindings
    candidate_global_step = candidate_provenance["manifest"]["global_step"]
    oracle_global_step = oracle_provenance["manifest"]["global_step"]
    if candidate_global_step != oracle_global_step:
        raise OracleVerificationError(
            "Candidate and oracle final manifests do not bind the same intended global_step."
        )
    oracle_manifest_is_legacy_d5 = (
        oracle_provenance["manifest"]["source_sha256"] == OLD_D5_ENGINE_SHA256
    )
    legacy_d5_missing_offload_authorized = bool(
        oracle_manifest_is_legacy_d5 and oracle_source_bindings
    )
    if cross_offload_parity:
        config_comparison: dict[str, Any] | None = _cross_offload_config_comparison(
            candidate["experiment_config"],
            oracle["experiment_config"],
            oracle_old_d5_bound=legacy_d5_missing_offload_authorized,
        )
        config_comparison["oracle_final_manifest_source_sha256"] = oracle_provenance["manifest"][
            "source_sha256"
        ]
        config_comparison["oracle_final_manifest_is_legacy_d5"] = oracle_manifest_is_legacy_d5
        config_comparison["oracle_legacy_d5_engine_evidence_bindings"] = list(
            oracle_source_bindings if oracle_manifest_is_legacy_d5 else []
        )
    else:
        config_comparison = None
    candidate_workspace = _load_torch_state(
        candidate["workspace_state"], weights_only=True, label="candidate workspace_state.pt"
    )
    oracle_workspace = _load_torch_state(
        oracle["workspace_state"], weights_only=True, label="oracle workspace_state.pt"
    )
    workspace = compare_nested_state(candidate_workspace, oracle_workspace)
    del candidate_workspace, oracle_workspace

    candidate_trainer = _validate_trainer_state(
        _load_torch_state(
            candidate["trainer_state"],
            weights_only=False,
            label="candidate trainer_state.pt",
        ),
        label="candidate",
    )
    oracle_trainer = _validate_trainer_state(
        _load_torch_state(
            oracle["trainer_state"],
            weights_only=False,
            label="oracle trainer_state.pt",
        ),
        label="oracle",
    )
    candidate_provenance["trainer_manifest_binding"] = _bind_trainer_to_manifest(
        candidate_trainer, candidate_provenance, label="candidate"
    )
    oracle_provenance["trainer_manifest_binding"] = _bind_trainer_to_manifest(
        oracle_trainer, oracle_provenance, label="oracle"
    )
    candidate_provenance.pop("_manifest_data_fingerprint")
    oracle_provenance.pop("_manifest_data_fingerprint")
    signature_bindings = (
        _trainer_signature_bindings(candidate_trainer, oracle_trainer)
        if cross_offload_parity
        else None
    )
    excluded_paths = {"$.run_state.run_id"}
    if cross_offload_parity:
        excluded_paths.update({"$.resume_signature", "$.structural_resume_signature"})
    trainer = compare_nested_state(
        candidate_trainer,
        oracle_trainer,
        excluded_paths=frozenset(excluded_paths),
    )
    trainer["required_stable_fields"] = sorted(TRAINER_REQUIRED_KEYS)
    trainer["scope"] = (
        "optimizer_including_adafactor_state_scheduler_scaler_rng_sampler_and_run_state"
    )
    del candidate_trainer, oracle_trainer
    metrics = compare_stable_metrics(candidate["metrics"], oracle["metrics"])

    candidate_inventory_after = _bundle_artifact_inventory(
        repo_root, candidate, label="candidate bundle"
    )
    oracle_inventory_after = _bundle_artifact_inventory(repo_root, oracle, label="oracle bundle")
    if candidate_inventory_before != candidate_inventory_after:
        raise OracleVerificationError("Candidate bundle artifacts changed during comparison.")
    if oracle_inventory_before != oracle_inventory_after:
        raise OracleVerificationError("Oracle bundle artifacts changed during comparison.")

    comparisons = {
        "workspace_state": workspace,
        "trainer_state": trainer,
        "stable_metrics": metrics,
    }
    first_mismatch: dict[str, Any] | None = None
    for name in ("workspace_state", "trainer_state", "stable_metrics"):
        comparison = comparisons[name]
        if not comparison["passed"] and first_mismatch is None:
            first_mismatch = {"scope": name, "detail": comparison["first_mismatch"]}
    return {
        "enabled": True,
        "passed": all(value["passed"] for value in comparisons.values()),
        "mode": "cross_offload_parity" if cross_offload_parity else "strict_general",
        "candidate_run_root": _relative(repo_root, candidate["root"], label="candidate run"),
        "oracle_run_root": _relative(repo_root, oracle["root"], label="oracle run"),
        "candidate_artifact_inventory": candidate_inventory_after,
        "oracle_artifact_inventory": oracle_inventory_after,
        "artifact_inventories_stable": True,
        "bundle_provenance": {
            "candidate": candidate_provenance,
            "oracle": oracle_provenance,
            "intended_global_step": {
                "source": "each_final_manifest.global_step",
                "candidate": candidate_global_step,
                "oracle": oracle_global_step,
                "equal": True,
            },
        },
        "cross_offload_config_comparison": config_comparison,
        "cross_offload_trainer_signature_bindings": signature_bindings,
        "comparisons": comparisons,
        "first_mismatch": first_mismatch,
    }


def _bind_evidence(
    repo_root: Path,
    raw_paths: Sequence[str],
    *,
    label: str,
) -> tuple[list[Path], list[dict[str, Any]]]:
    paths = [_require_plain_file(repo_root, raw, label=f"{label} evidence") for raw in raw_paths]
    if len(set(paths)) != len(paths):
        raise OracleVerificationError(f"{label} evidence paths contain duplicates.")
    records = [file_record(repo_root, path, label=f"{label} evidence") for path in paths]
    return paths, records


def _engine_identity_bindings(
    repo_root: Path,
    paths: Sequence[Path],
) -> list[dict[str, str]]:
    """Return every valid SHA-256 value in a recognized engine-identity field."""

    recognized_keys = {
        "engine.py",
        "engine_sha256",
        "source_sha256",
        "src/latent_workspace_ft_v10/engine.py",
    }
    bindings: list[dict[str, str]] = []

    def visit(value: Any, *, json_path: str, evidence_path: Path) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                child_path = f"{json_path}.{key}"
                recognized_identity_field = key in recognized_keys or child_path.endswith(
                    ".patched_engine.sha256"
                )
                if (
                    recognized_identity_field
                    and isinstance(child, str)
                    and re.fullmatch(r"[0-9a-f]{64}", child) is not None
                ):
                    bindings.append(
                        {
                            "evidence_path": _relative(
                                repo_root,
                                evidence_path,
                                label="source identity evidence",
                            ),
                            "json_path": child_path,
                            "engine_sha256": child,
                        }
                    )
                visit(child, json_path=child_path, evidence_path=evidence_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, json_path=f"{json_path}[{index}]", evidence_path=evidence_path)

    for path in paths:
        try:
            value = json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=_duplicate_rejecting_object,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, OracleVerificationError):
            continue
        visit(value, json_path="$", evidence_path=path)
    return sorted(bindings, key=lambda item: (item["evidence_path"], item["json_path"]))


def _require_unambiguous_source_identity(
    repo_root: Path,
    paths: Sequence[Path],
    *,
    expected_sha256: str,
    label: str,
) -> list[dict[str, str]]:
    """Bind one run manifest to one unambiguous identity in its source evidence."""

    _require_sha256(expected_sha256, label=f"{label} expected engine identity")
    bindings = _engine_identity_bindings(repo_root, paths)
    observed = sorted({binding["engine_sha256"] for binding in bindings})
    if expected_sha256 not in observed:
        raise OracleVerificationError(
            f"{label.capitalize()} final manifest source_sha256 is absent from its "
            "bound source evidence."
        )
    unexpected = [value for value in observed if value != expected_sha256]
    if unexpected:
        raise OracleVerificationError(
            f"{label.capitalize()} source evidence contains multiple recognized engine "
            "identities and does not unambiguously bind its final manifest source_sha256."
        )
    return [binding for binding in bindings if binding["engine_sha256"] == expected_sha256]


def _source_evidence_claim(
    candidate_records: Sequence[Mapping[str, Any]],
    oracle_records: Sequence[Mapping[str, Any]],
    *,
    candidate_validated_source_sha256: str | None,
    oracle_validated_source_sha256: str | None,
) -> dict[str, Any]:
    candidate_hashes = sorted(str(record["sha256"]) for record in candidate_records)
    oracle_hashes = sorted(str(record["sha256"]) for record in oracle_records)
    documents_matched = candidate_hashes == oracle_hashes
    identity_verified = (
        candidate_validated_source_sha256 is not None
        and oracle_validated_source_sha256 is not None
    )
    current_source_matched = (
        candidate_validated_source_sha256 == oracle_validated_source_sha256
        if identity_verified
        else None
    )
    if current_source_matched is True:
        comparison_mode = "current_source_matched"
    elif current_source_matched is False:
        comparison_mode = "cross_source_identity"
    else:
        comparison_mode = "base_model_only_source_identity_unverified"
    return {
        "source_identity_verified": identity_verified,
        "current_source_matched": current_source_matched,
        "source_comparison_mode": comparison_mode,
        "identity_match_rule": (
            "equality_of_each_run_bundle_validated_final_manifest_source_sha256"
        ),
        "candidate_validated_source_sha256": candidate_validated_source_sha256,
        "oracle_validated_source_sha256": oracle_validated_source_sha256,
        "source_evidence_documents_sha256_matched": documents_matched,
        "document_match_rule": "exact_multiset_equality_of_bound_source_evidence_sha256",
        "candidate_source_evidence_sha256": candidate_hashes,
        "oracle_source_evidence_sha256": oracle_hashes,
    }


def _evidence_stable(
    repo_root: Path,
    paths: Sequence[Path],
    expected: Sequence[Mapping[str, Any]],
    *,
    label: str,
) -> bool:
    observed = [file_record(repo_root, path, label=f"{label} evidence") for path in paths]
    return observed == list(expected)


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def run_verification(
    *,
    repo_root: Path,
    candidate_model: str | Path,
    oracle_model: str | Path,
    candidate_config_evidence: Sequence[str],
    oracle_config_evidence: Sequence[str],
    candidate_source_evidence: Sequence[str],
    oracle_source_evidence: Sequence[str],
    candidate_run_evidence: Sequence[str],
    oracle_run_evidence: Sequence[str],
    candidate_run: str | Path | None,
    oracle_run: str | Path | None,
    cross_offload_parity: bool,
    output: Path,
    max_working_set_bytes: int,
) -> dict[str, Any]:
    candidate_root = _require_plain_directory(
        repo_root, candidate_model, label="candidate model root"
    )
    oracle_root = _require_plain_directory(repo_root, oracle_model, label="oracle model root")
    if candidate_root == oracle_root:
        raise OracleVerificationError("Candidate and oracle model roots must be distinct.")
    if candidate_root in oracle_root.parents or oracle_root in candidate_root.parents:
        raise OracleVerificationError("Candidate and oracle model roots must be disjoint.")
    if output == candidate_root or candidate_root in output.parents:
        raise OracleVerificationError("Receipt output must not be inside candidate model tree.")
    if output == oracle_root or oracle_root in output.parents:
        raise OracleVerificationError("Receipt output must not be inside oracle model tree.")
    if max_working_set_bytes <= 0:
        raise OracleVerificationError("--max-working-set-bytes must be positive.")
    implementation = Path(__file__).resolve()
    if output == implementation:
        raise OracleVerificationError(
            "Receipt output must not replace the verifier implementation."
        )
    if implementation.is_symlink() or not implementation.is_file():
        raise OracleVerificationError(
            "Verifier implementation must be a regular non-symlink file."
        )
    implementation_sha256_before = sha256_file(implementation)

    evidence_paths: dict[str, dict[str, list[Path]]] = {"candidate": {}, "oracle": {}}
    evidence_records: dict[str, dict[str, list[dict[str, Any]]]] = {
        "candidate": {},
        "oracle": {},
    }
    evidence_arguments = {
        "candidate": {
            "config": candidate_config_evidence,
            "source": candidate_source_evidence,
            "run": candidate_run_evidence,
        },
        "oracle": {
            "config": oracle_config_evidence,
            "source": oracle_source_evidence,
            "run": oracle_run_evidence,
        },
    }
    for side, categories in evidence_arguments.items():
        for category, raw_paths in categories.items():
            paths, records = _bind_evidence(
                repo_root,
                raw_paths,
                label=f"{side} {category}",
            )
            evidence_paths[side][category] = paths
            evidence_records[side][category] = records

    if (candidate_run is None) != (oracle_run is None):
        raise OracleVerificationError("--candidate-run and --oracle-run must be supplied together.")
    if cross_offload_parity and candidate_run is None:
        raise OracleVerificationError(
            "--cross-offload-parity requires --candidate-run and --oracle-run."
        )
    candidate_inventory_before = model_tree_inventory(candidate_root)
    oracle_inventory_before = model_tree_inventory(oracle_root)
    base_result, candidate_indexed, oracle_indexed = compare_models(
        candidate_root,
        oracle_root,
        candidate_tree_inventory=candidate_inventory_before,
        oracle_tree_inventory=oracle_inventory_before,
        max_working_set_bytes=max_working_set_bytes,
    )
    if candidate_run is None:
        bundle_result: dict[str, Any] = {
            "enabled": False,
            "passed": None,
            "reason": "not_requested_base_model_only",
        }
    else:
        bundle_result = compare_run_bundles(
            repo_root,
            candidate_run=candidate_run,
            oracle_run=oracle_run,
            candidate_model_root=candidate_root,
            oracle_model_root=oracle_root,
            cross_offload_parity=cross_offload_parity,
            candidate_source_evidence_paths=evidence_paths["candidate"]["source"],
            oracle_source_evidence_paths=evidence_paths["oracle"]["source"],
        )
    candidate_inventory_after = model_tree_inventory(candidate_root)
    oracle_inventory_after = model_tree_inventory(oracle_root)
    if candidate_inventory_after != candidate_inventory_before:
        raise OracleVerificationError("Candidate model tree changed during comparison.")
    if oracle_inventory_after != oracle_inventory_before:
        raise OracleVerificationError("Oracle model tree changed during comparison.")
    for side in ("candidate", "oracle"):
        for category in ("config", "source", "run"):
            if not _evidence_stable(
                repo_root,
                evidence_paths[side][category],
                evidence_records[side][category],
                label=f"{side} {category}",
            ):
                raise OracleVerificationError(
                    f"{side} {category} evidence changed during comparison."
                )

    if bundle_result["enabled"]:
        bundle_provenance = bundle_result["bundle_provenance"]
        candidate_validated_source_sha256 = bundle_provenance["candidate"]["manifest"][
            "source_sha256"
        ]
        oracle_validated_source_sha256 = bundle_provenance["oracle"]["manifest"][
            "source_sha256"
        ]
    else:
        candidate_validated_source_sha256 = None
        oracle_validated_source_sha256 = None
    source_claim = _source_evidence_claim(
        evidence_records["candidate"]["source"],
        evidence_records["oracle"]["source"],
        candidate_validated_source_sha256=candidate_validated_source_sha256,
        oracle_validated_source_sha256=oracle_validated_source_sha256,
    )

    passed = base_result["passed"] and (
        not bundle_result["enabled"] or bundle_result["passed"] is True
    )
    first_mismatch: dict[str, Any] | None = None
    if not base_result["passed"]:
        first_mismatch = {"scope": "base_model", "detail": base_result["first_mismatch"]}
    elif bundle_result["enabled"] and not bundle_result["passed"]:
        first_mismatch = {"scope": "run_bundle", "detail": bundle_result["first_mismatch"]}
    result = {
        "passed": passed,
        "base_model": base_result,
        "run_bundle": bundle_result,
        "first_mismatch": first_mismatch,
    }

    implementation_sha256_after = sha256_file(implementation)
    if implementation_sha256_after != implementation_sha256_before:
        raise OracleVerificationError(
            "Verifier implementation changed during comparison; no result is publishable."
        )
    comparison_mode = (
        "cross_offload_parity"
        if cross_offload_parity
        else ("strict_general_bundle" if bundle_result["enabled"] else "base_model_only")
    )
    if not bundle_result["enabled"]:
        bundle_claim = "Run-bundle state comparison was not requested."
    elif cross_offload_parity:
        bundle_claim = (
            "Cross-offload bundle PASS excludes run_id, resume_signature, and "
            "structural_resume_signature from trainer-state equality; both signatures remain "
            "explicitly bound, and final experiment-config differences are limited to the "
            "three receipt-listed paths."
        )
    else:
        bundle_claim = (
            "General bundle PASS excludes only run_state.run_id from trainer-state equality."
        )
    return {
        "format": RECEIPT_FORMAT,
        "status": "PASS" if passed else "FAIL",
        "created_utc": utc_now(),
        "verifier": {
            "implementation": "scripts/compare_v10_full_model_oracle.py",
            "implementation_sha256": implementation_sha256_after,
            "implementation_pre_post_sha256_equal": True,
            "python": sys.version.split()[0],
            "torch": _package_version("torch"),
            "safetensors": _package_version("safetensors"),
            "max_working_set_bytes": max_working_set_bytes,
            "streaming_axis": "tensor_dimension_0",
        },
        "inputs": {
            "candidate": {
                "model_root": _relative(repo_root, candidate_root, label="candidate model root"),
                "tree_inventory": candidate_inventory_after,
                "indexed_safetensors": candidate_indexed,
                "evidence": evidence_records["candidate"],
            },
            "oracle": {
                "model_root": _relative(repo_root, oracle_root, label="oracle model root"),
                "tree_inventory": oracle_inventory_after,
                "indexed_safetensors": oracle_indexed,
                "evidence": evidence_records["oracle"],
            },
        },
        "stability": {
            "candidate_tree_pre_post_inventory_equal": True,
            "oracle_tree_pre_post_inventory_equal": True,
            "all_config_source_run_evidence_pre_post_hashes_equal": True,
            "run_bundle_artifact_inventories_equal": (True if bundle_result["enabled"] else None),
        },
        "claims": {
            "comparison_mode": comparison_mode,
            "source_evidence": source_claim,
        },
        "result": result,
        "claim_boundary": (
            "PASS proves byte-exact equality of every indexed tensor name, dtype, shape, "
            "and element payload for these two bound model trees. When run-bundle mode is "
            "enabled, PASS additionally proves exact workspace and trainer state under its "
            "documented exclusions and exact split/step metrics after only the explicit "
            "dynamic-field exclusions. Each enabled bundle also binds its final manifest to "
            "the saved experiment config, trainer identity/signatures, and bound source "
            f"identity evidence, with equal final global_step. {bundle_claim} Current-source "
            "identity is claimed only in run-bundle mode when the two validated final-manifest "
            "source_sha256 values are equal and each is unambiguously bound by that side's "
            "source evidence. Source-evidence document-hash equality is reported separately "
            "and never substitutes for source identity; base-model-only mode leaves source "
            "identity unverified. It does not establish model quality, "
            "behavioral "
            "equivalence outside the bound artifacts, training-mechanism equivalence, or a "
            "scientific result. FAIL or ERROR must not be interpreted as a passing comparison."
        ),
    }


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_receipt(path: Path, receipt: Mapping[str, Any], *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(receipt))
            handle.flush()
            os.fsync(handle.fileno())
        if overwrite:
            if path.is_dir() and not path.is_symlink():
                raise OracleVerificationError("Receipt output is an existing directory.")
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise ExistingOutputError(
                    "Receipt output appeared during publication; refusing to overwrite it."
                ) from exc
            temporary.unlink()
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--candidate-model", required=True)
    parser.add_argument("--oracle-model", required=True)
    parser.add_argument(
        "--candidate-run",
        help="Optional run root containing final/ and metrics.jsonl; requires --oracle-run.",
    )
    parser.add_argument(
        "--oracle-run",
        help="Optional run root containing final/ and metrics.jsonl; requires --candidate-run.",
    )
    parser.add_argument(
        "--cross-offload-parity",
        action="store_true",
        help=(
            "Compare a candidate cpu-offload run against a native oracle, allowing only "
            "the documented config and trainer-signature differences. Requires both run roots."
        ),
    )
    parser.add_argument("--candidate-config-evidence", action="append", required=True)
    parser.add_argument("--oracle-config-evidence", action="append", required=True)
    parser.add_argument("--candidate-source-evidence", action="append", required=True)
    parser.add_argument("--oracle-source-evidence", action="append", required=True)
    parser.add_argument("--candidate-run-evidence", action="append", required=True)
    parser.add_argument("--oracle-run-evidence", action="append", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--max-working-set-bytes",
        type=int,
        default=DEFAULT_MAX_WORKING_SET_BYTES,
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def _error_receipt(exc: BaseException) -> dict[str, Any]:
    message = str(exc)
    if not isinstance(exc, OracleVerificationError):
        message = "Unexpected verifier failure; no comparison claim is available."
    return {
        "format": RECEIPT_FORMAT,
        "status": "ERROR",
        "created_utc": utc_now(),
        "result": {
            "passed": False,
            "error": {
                "type": type(exc).__name__,
                "message": message,
            },
        },
        "claim_boundary": (
            "This ERROR receipt is negative engineering evidence only. It contains no "
            "successful full-model equality, model-quality, or scientific claim."
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    if repo_root.is_symlink() or not repo_root.is_dir():
        print("ERROR: --repo-root must be a non-symlink directory.", file=sys.stderr)
        return 2
    try:
        output = _resolve_output(repo_root, args.output)
        if output == Path(__file__).resolve():
            raise OracleVerificationError(
                "Receipt output must not replace the verifier implementation."
            )
        requested_models = [
            _resolve_inside(repo_root, args.candidate_model, label="candidate model root"),
            _resolve_inside(repo_root, args.oracle_model, label="oracle model root"),
        ]
        if any(output == root or root in output.parents for root in requested_models):
            raise OracleVerificationError("Receipt output must not be inside a model tree.")
        requested_runs = [
            _resolve_inside(repo_root, raw, label="run root")
            for raw in (args.candidate_run, args.oracle_run)
            if raw is not None
        ]
        if any(output == root or root in output.parents for root in requested_runs):
            raise OracleVerificationError("Receipt output must not be inside a run tree.")
        requested_evidence = (
            args.candidate_config_evidence
            + args.oracle_config_evidence
            + args.candidate_source_evidence
            + args.oracle_source_evidence
            + args.candidate_run_evidence
            + args.oracle_run_evidence
        )
        if any(
            output == _resolve_inside(repo_root, raw, label="evidence path")
            for raw in requested_evidence
        ):
            raise OracleVerificationError("Receipt output must not replace an evidence file.")
    except OracleVerificationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if output.is_dir() and not output.is_symlink():
        print("ERROR: receipt output is an existing directory.", file=sys.stderr)
        return 2
    if (output.exists() or output.is_symlink()) and not args.overwrite:
        print(
            "ERROR: receipt output already exists; pass --overwrite to replace it.",
            file=sys.stderr,
        )
        return 2

    try:
        receipt = run_verification(
            repo_root=repo_root,
            candidate_model=args.candidate_model,
            oracle_model=args.oracle_model,
            candidate_config_evidence=args.candidate_config_evidence,
            oracle_config_evidence=args.oracle_config_evidence,
            candidate_source_evidence=args.candidate_source_evidence,
            oracle_source_evidence=args.oracle_source_evidence,
            candidate_run_evidence=args.candidate_run_evidence,
            oracle_run_evidence=args.oracle_run_evidence,
            candidate_run=args.candidate_run,
            oracle_run=args.oracle_run,
            cross_offload_parity=args.cross_offload_parity,
            output=output,
            max_working_set_bytes=args.max_working_set_bytes,
        )
    except Exception as exc:
        receipt = _error_receipt(exc)
        try:
            atomic_write_receipt(output, receipt, overwrite=args.overwrite)
        except Exception as write_exc:
            print(f"ERROR: could not publish ERROR receipt: {write_exc}", file=sys.stderr)
            return 2
        print(f"ERROR: {receipt['result']['error']['message']}", file=sys.stderr)
        return 2

    try:
        atomic_write_receipt(output, receipt, overwrite=args.overwrite)
    except Exception as exc:
        print(f"ERROR: could not publish comparison receipt: {exc}", file=sys.stderr)
        return 2
    print(f"{receipt['status']}: {_relative(repo_root, output, label='receipt output')}")
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
