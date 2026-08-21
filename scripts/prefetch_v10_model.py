#!/usr/bin/env python3
"""Prefetch and verify an immutable Hugging Face model snapshot.

This is the only v10 control-plane command that is allowed to contact the Hub.
The matrix runner consumes the resulting receipt with local-files-only semantics.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FORMAT = "latent-workspace-v10-model-prefetch-receipt-v1"
DEFAULT_MODEL = "mistralai/Mistral-7B-Instruct-v0.3"
DEFAULT_REVISION = "c170c708c41dac9275d15a8fff4eca08d52bab71"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SNAPSHOT_ALLOW_PATTERNS = (
    "*.json",
    "*.model",
    "*.py",
    # Prefer standard Transformers model shards and avoid downloading a
    # duplicate consolidated export when both layouts are published.
    "model*.safetensors",
    "*.tiktoken",
    "*.txt",
)


class PrefetchError(RuntimeError):
    """A fail-closed model prefetch or receipt validation error."""


def sha256_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


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
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PrefetchError(f"Could not read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PrefetchError(f"Expected a JSON object: {path}")
    return value


def require_exact_revision(revision: str) -> str:
    normalized = revision.strip().lower()
    if not COMMIT_RE.fullmatch(normalized):
        raise PrefetchError(
            "Model revision must be an exact 40-character lowercase commit SHA, "
            f"not a branch or tag: {revision!r}"
        )
    return normalized


def _safe_relative_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not value or any(part in {"", ".", ".."} for part in path.parts):
        raise PrefetchError(f"Unsafe snapshot-relative path: {value!r}")
    return path


def snapshot_inventory(snapshot: Path) -> list[dict[str, Any]]:
    snapshot = snapshot.resolve()
    if not snapshot.is_dir():
        raise PrefetchError(f"Model snapshot is not a directory: {snapshot}")
    inventory: list[dict[str, Any]] = []
    for path in sorted(snapshot.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(snapshot).as_posix()
        inventory.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    if not inventory:
        raise PrefetchError(f"Model snapshot is empty: {snapshot}")
    return inventory


def inspect_safetensors_layout(snapshot: Path) -> dict[str, Any]:
    """Validate both single-file and arbitrarily sharded safetensors layouts."""

    snapshot = snapshot.resolve()
    all_weights = {
        path.relative_to(snapshot).as_posix(): path
        for path in sorted(snapshot.rglob("*.safetensors"))
        if path.is_file()
    }
    if not all_weights:
        raise PrefetchError("Snapshot contains no safetensors weight files.")

    referenced: set[str] = set()
    indices: list[dict[str, Any]] = []
    for index_path in sorted(snapshot.rglob("*.safetensors.index.json")):
        raw = read_json(index_path)
        weight_map = raw.get("weight_map")
        if not isinstance(weight_map, dict) or not weight_map:
            raise PrefetchError(f"Missing non-empty weight_map in {index_path}")
        shards: set[str] = set()
        for tensor_name, shard_name in weight_map.items():
            if not isinstance(tensor_name, str) or not isinstance(shard_name, str):
                raise PrefetchError(f"Invalid weight_map entry in {index_path}")
            shard_relative_to_index = _safe_relative_path(shard_name)
            # Keep the lexical snapshot path for the containment check. Hugging
            # Face snapshots normally expose files as symlinks into the cache's
            # blob store, so resolving the final symlink would incorrectly make
            # every valid shard appear to escape the snapshot directory.
            shard = index_path.parent / shard_relative_to_index
            try:
                relative = shard.relative_to(snapshot).as_posix()
            except ValueError as exc:
                raise PrefetchError(
                    f"Safetensors index escapes the snapshot: {shard_name}"
                ) from exc
            if relative not in all_weights or not shard.is_file() or shard.stat().st_size <= 0:
                raise PrefetchError(
                    f"Safetensors index references a missing/empty shard: {relative}"
                )
            shards.add(relative)
            referenced.add(relative)
        indices.append(
            {
                "path": index_path.relative_to(snapshot).as_posix(),
                "tensor_count": len(weight_map),
                "shards": sorted(shards),
            }
        )

    for relative, path in all_weights.items():
        if path.stat().st_size <= 0:
            raise PrefetchError(f"Empty safetensors file: {relative}")

    return {
        "index_files": indices,
        "weight_files": sorted(all_weights),
        "indexed_weight_files": sorted(referenced),
        "standalone_weight_files": sorted(set(all_weights) - referenced),
        "weight_file_count": len(all_weights),
        "weight_bytes": sum(path.stat().st_size for path in all_weights.values()),
    }


def _distribution_versions(names: Iterable[str]) -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def build_receipt(
    *,
    snapshot: Path,
    model_id: str,
    requested_revision: str,
    resolved_revision: str,
    validation: Mapping[str, Any],
) -> dict[str, Any]:
    requested_revision = require_exact_revision(requested_revision)
    resolved_revision = require_exact_revision(resolved_revision)
    if resolved_revision != requested_revision:
        raise PrefetchError(
            f"Resolved revision {resolved_revision} does not equal requested "
            f"revision {requested_revision}."
        )
    config_path = snapshot / "config.json"
    if not config_path.is_file():
        raise PrefetchError("Snapshot is missing config.json.")
    inventory = snapshot_inventory(snapshot)
    tokenizer_candidates = [
        path
        for path in inventory
        if (
            "tokenizer" in Path(str(path["path"])).name
            or Path(str(path["path"])).name
            in {"tokenizer.model", "vocab.json", "merges.txt", "special_tokens_map.json"}
        )
    ]
    if not tokenizer_candidates:
        raise PrefetchError("Snapshot has no recognizable tokenizer assets.")
    return {
        "format": FORMAT,
        "complete": True,
        "created_utc": datetime.now(UTC).isoformat(),
        "model": {
            "name_or_path": model_id,
            "requested_revision": requested_revision,
            "resolved_revision": resolved_revision,
        },
        "snapshot": {
            "file_count": len(inventory),
            "total_bytes": sum(int(item["bytes"]) for item in inventory),
            "files": inventory,
        },
        "weights": inspect_safetensors_layout(snapshot),
        "validation": dict(validation),
        "environment": _distribution_versions(
            ["huggingface-hub", "safetensors", "torch", "transformers", "tokenizers"]
        ),
        "claim_boundary": (
            "This receipt proves byte hashes for one locally cached immutable snapshot "
            "and successful local config/tokenizer loading. It does not prove that "
            "training fits, converges, or reproduces any earlier model result."
        ),
    }


def _resolve_cached_snapshot(
    model_id: str,
    revision: str,
    *,
    cache_dir: Path | None,
) -> Path:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise PrefetchError("huggingface_hub is required to resolve the cached model.") from exc
    try:
        result = snapshot_download(
            repo_id=model_id,
            revision=revision,
            cache_dir=str(cache_dir) if cache_dir is not None else None,
            local_files_only=True,
            allow_patterns=list(SNAPSHOT_ALLOW_PATTERNS),
        )
    except Exception as exc:
        raise PrefetchError(
            f"Pinned snapshot is not available locally for {model_id}@{revision}: {exc}"
        ) from exc
    return Path(result).resolve()


def verify_prefetch_receipt(
    receipt_path: Path,
    *,
    expected_model: str | None = None,
    expected_revision: str | None = None,
    snapshot_path: Path | None = None,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    receipt_path = receipt_path.resolve()
    receipt = read_json(receipt_path)
    if receipt.get("format") != FORMAT or receipt.get("complete") is not True:
        raise PrefetchError(f"Incomplete or unsupported model receipt: {receipt_path}")
    model = receipt.get("model")
    if not isinstance(model, dict):
        raise PrefetchError("Model receipt has no model object.")
    model_id = str(model.get("name_or_path", ""))
    requested = require_exact_revision(str(model.get("requested_revision", "")))
    resolved = require_exact_revision(str(model.get("resolved_revision", "")))
    if requested != resolved:
        raise PrefetchError("Model receipt requested/resolved revisions differ.")
    if expected_model is not None and model_id != expected_model:
        raise PrefetchError(f"Model receipt mismatch: {model_id!r} != {expected_model!r}")
    if expected_revision is not None and requested != require_exact_revision(expected_revision):
        raise PrefetchError(
            f"Model revision receipt mismatch: {requested} != {expected_revision}"
        )

    snapshot = (
        snapshot_path.resolve()
        if snapshot_path is not None
        else _resolve_cached_snapshot(model_id, requested, cache_dir=cache_dir)
    )
    expected_snapshot = receipt.get("snapshot")
    if not isinstance(expected_snapshot, dict):
        raise PrefetchError("Model receipt has no snapshot object.")
    expected_files = expected_snapshot.get("files")
    if not isinstance(expected_files, list):
        raise PrefetchError("Model receipt snapshot.files is not a list.")
    observed_files = snapshot_inventory(snapshot)
    if observed_files != expected_files:
        raise PrefetchError(
            "Cached model snapshot inventory/hash differs from the prefetch receipt."
        )
    observed_weights = inspect_safetensors_layout(snapshot)
    if observed_weights != receipt.get("weights"):
        raise PrefetchError("Cached safetensors layout differs from the receipt.")
    return {
        "receipt": receipt,
        "receipt_path": receipt_path,
        "receipt_sha256": sha256_file(receipt_path),
        "snapshot_path": snapshot,
        "model_id": model_id,
        "revision": requested,
    }


def prefetch(
    *,
    model_id: str,
    revision: str,
    receipt_path: Path,
    cache_dir: Path | None,
    local_files_only: bool,
) -> dict[str, Any]:
    revision = require_exact_revision(revision)
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise PrefetchError("huggingface_hub is required for model prefetch.") from exc

    try:
        downloaded = snapshot_download(
            repo_id=model_id,
            revision=revision,
            cache_dir=str(cache_dir) if cache_dir is not None else None,
            local_files_only=local_files_only,
            allow_patterns=list(SNAPSHOT_ALLOW_PATTERNS),
        )
    except Exception as exc:
        raise PrefetchError(f"Pinned snapshot download failed: {exc}") from exc
    snapshot = Path(downloaded).resolve()
    resolved_revision = snapshot.name.lower()
    if not COMMIT_RE.fullmatch(resolved_revision):
        raise PrefetchError(
            f"Could not prove immutable resolved revision from snapshot path: {snapshot}"
        )

    try:
        from transformers import AutoConfig, AutoTokenizer
    except ImportError as exc:
        raise PrefetchError("transformers is required to validate config/tokenizer.") from exc
    try:
        config = AutoConfig.from_pretrained(
            snapshot,
            local_files_only=True,
            trust_remote_code=False,
        )
        tokenizer = AutoTokenizer.from_pretrained(
            snapshot,
            local_files_only=True,
            trust_remote_code=False,
        )
    except Exception as exc:
        raise PrefetchError(f"Local config/tokenizer validation failed: {exc}") from exc

    validation = {
        "config_loaded": True,
        "tokenizer_loaded": True,
        "model_type": str(getattr(config, "model_type", "")),
        "tokenizer_class": type(tokenizer).__name__,
        "trust_remote_code": False,
    }
    receipt = build_receipt(
        snapshot=snapshot,
        model_id=model_id,
        requested_revision=revision,
        resolved_revision=resolved_revision,
        validation=validation,
    )
    atomic_write_json(receipt_path, receipt)
    return verify_prefetch_receipt(
        receipt_path,
        expected_model=model_id,
        expected_revision=revision,
        snapshot_path=snapshot,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prefetch one immutable v10 model snapshot and hash every file."
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path("runs/v10/model_cache/MODEL_PREFETCH_RECEIPT.json"),
    )
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument(
        "--local-files-only",
        action="store_true",
        help="Do not contact the Hub; rebuild the receipt from an existing cache.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify an existing receipt/cache without downloading or rewriting it.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.verify_only:
            result = verify_prefetch_receipt(
                args.receipt,
                expected_model=args.model,
                expected_revision=args.revision,
                cache_dir=args.cache_dir,
            )
        else:
            result = prefetch(
                model_id=args.model,
                revision=args.revision,
                receipt_path=args.receipt,
                cache_dir=args.cache_dir,
                local_files_only=args.local_files_only,
            )
    except PrefetchError as exc:
        print(f"prefetch blocked: {exc}", file=sys.stderr)
        return 2
    receipt = result["receipt"]
    print(
        json.dumps(
            {
                "status": "verified",
                "model": result["model_id"],
                "revision": result["revision"],
                "receipt": str(args.receipt),
                "receipt_sha256": result["receipt_sha256"],
                "snapshot_file_count": receipt["snapshot"]["file_count"],
                "weight_file_count": receipt["weights"]["weight_file_count"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
