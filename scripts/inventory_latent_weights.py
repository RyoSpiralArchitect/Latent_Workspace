#!/usr/bin/env python3
"""Inventory explicitly scoped experiment weights; copy metadata, never weights.

No deletion or retention-selection API exists in this module. SHA-256 records
are fingerprints, NOT reconstructible backups of the original weight files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FORMAT = "latent-workspace-weight-inventory-v1"
WEIGHT_EXTENSIONS = frozenset({".pt", ".pth", ".safetensors", ".bin"})
METADATA_EXTENSIONS = frozenset({".json", ".jsonl", ".md", ".txt", ".yaml", ".yml", ".csv"})
EXCLUDED_DIRECTORIES = frozenset(
    {
        "cache",
        ".cache",
        "model_cache",
        "hf",
        "huggingface",
        ".venv",
        "hf_cache",
    }
)
SCOPE_COMPONENTS = frozenset({"experiments", "resume_gates", "runs"})
MAX_METADATA_BYTES = 50 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024


class InventoryError(ValueError):
    """The requested inventory scope or evidence destination is unsafe."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InventoryError(message)


def _scopes(root: str | Path, output_dir: str | Path) -> tuple[Path, Path]:
    requested_root, requested_output = Path(root), Path(output_dir)
    _require(requested_root.is_absolute(), "--root must be an explicit absolute path")
    _require(requested_output.is_absolute(), "--output-dir must be an explicit absolute path")
    _require(not requested_root.is_symlink(), "source root may not be a symlink")
    _require(requested_root.is_dir(), "source root must already be a directory")
    source = requested_root.resolve(strict=True)
    home = Path.home().resolve()
    _require(
        source != Path(source.anchor) and source != home and source not in home.parents,
        "a filesystem root, home directory, or home ancestor is not an experiment scope",
    )
    _require(
        any(part in SCOPE_COMPONENTS for part in source.parts),
        "source must be scoped under an experiments, resume_gates, or runs directory",
    )
    _require(
        not any(part.casefold() in EXCLUDED_DIRECTORIES for part in source.parts),
        "a cache/environment directory cannot be an inventory source",
    )
    _require(
        not requested_output.exists() and not requested_output.is_symlink(),
        "evidence output must be a fresh, nonexistent directory",
    )
    _require(requested_output.parent.is_dir(), "evidence parent must already exist")
    destination = requested_output.parent.resolve(strict=True) / requested_output.name
    _require(
        destination != source and source not in destination.parents,
        "evidence output must be outside the source root",
    )
    _require(
        not destination.exists() and not destination.is_symlink(),
        "resolved evidence output must be nonexistent",
    )
    _require(
        hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY"),
        "this read-only helper requires no-follow directory/file opens (macOS/Linux)",
    )
    return source, destination


def _stat_values(value: os.stat_result) -> dict[str, Any]:
    return {
        "size_bytes": value.st_size,
        "allocated_bytes": value.st_blocks * 512 if hasattr(value, "st_blocks") else None,
        "nlink": value.st_nlink,
        "inode": value.st_ino,
        "device": value.st_dev,
        "mtime_ns": value.st_mtime_ns,
        "mtime_utc": datetime.fromtimestamp(value.st_mtime, UTC).isoformat(),
        "ctime_ns": value.st_ctime_ns,
    }


def _stat_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        getattr(value, "st_blocks", -1),
    )


def _read_regular(
    directory_fd: int,
    name: str,
    observed_stat: os.stat_result,
    relative: Path,
    destination: Path | None,
) -> dict[str, Any]:
    """Read through a held no-follow directory descriptor and check source stability."""
    entry: dict[str, Any] = {
        "relative_path": relative.as_posix(),
        **_stat_values(observed_stat),
        "sha256": None,
        "status": "READ_ERROR",
        "backup_status": "NOT_COPIED_WEIGHT" if destination is None else "COPY_NOT_COMPLETED",
    }
    source_fd: int | None = None
    backup_handle = None
    copied_path: Path | None = None
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
        source_fd = os.open(name, flags, dir_fd=directory_fd)
        before = os.fstat(source_fd)
        _require(stat.S_ISREG(before.st_mode), "opened source is not a regular file")
        _require(
            _stat_identity(before) == _stat_identity(observed_stat),
            "source changed between directory inspection and opening",
        )
        if destination is not None:
            copied_path = destination / "metadata" / relative
            copied_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            backup_handle = copied_path.open("xb")
            entry["backup_relative_path"] = copied_path.relative_to(destination).as_posix()

        digest = hashlib.sha256()
        remaining = before.st_size
        bytes_read = 0
        while remaining:
            chunk = os.read(source_fd, min(CHUNK_BYTES, remaining))
            if not chunk:
                break
            digest.update(chunk)
            if backup_handle is not None:
                backup_handle.write(chunk)
            bytes_read += len(chunk)
            remaining -= len(chunk)
        grew = bool(os.read(source_fd, 1))
        after = os.fstat(source_fd)
        entry["bytes_hashed"] = bytes_read
        entry["observed_sha256"] = digest.hexdigest()
        entry["stat_after_hash"] = _stat_values(after)
        stable = (
            not grew
            and bytes_read == before.st_size
            and _stat_identity(before) == _stat_identity(after)
        )
        entry["source_static_during_hash"] = stable
        if backup_handle is not None:
            backup_handle.flush()
            os.fsync(backup_handle.fileno())
            backup_handle.close()
            backup_handle = None
            assert copied_path is not None
            with copied_path.open("rb") as copied:
                entry["backup_sha256"] = hashlib.file_digest(copied, "sha256").hexdigest()
            _require(
                entry["backup_sha256"] == entry["observed_sha256"],
                "metadata copy hash differs from bytes read",
            )
        if stable:
            entry["status"] = "STATIC_VERIFIED"
            entry["sha256"] = entry["observed_sha256"]
            if destination is not None:
                entry["backup_status"] = "COPIED_AND_HASH_VERIFIED"
        else:
            entry["status"] = "SOURCE_CHANGED_DURING_HASH"
            entry["error"] = "observed hash is not a verified static-source fingerprint"
            if destination is not None:
                entry["backup_status"] = "UNSTABLE_COPY_RETAINED_DO_NOT_TRUST"
    except (OSError, InventoryError) as exc:
        entry["error"] = f"{type(exc).__name__}: {exc}"
        if copied_path is not None:
            entry["backup_status"] = "PARTIAL_COPY_RETAINED_DO_NOT_TRUST"
    finally:
        if backup_handle is not None:
            backup_handle.close()
        if source_fd is not None:
            os.close(source_fd)
    return entry


def _closest_references(
    weight: dict[str, Any], metadata: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {"manifest": [], "config": []}
    parent = Path(weight["relative_path"]).parent
    for category in result:
        for directory in (parent, *parent.parents):
            matches = [
                entry
                for entry in metadata
                if Path(entry["relative_path"]).parent == directory
                and category in Path(entry["relative_path"]).name.casefold()
            ]
            if matches:
                result[category] = [
                    {
                        key: entry.get(key)
                        for key in (
                            "relative_path",
                            "sha256",
                            "status",
                            "backup_status",
                            "backup_relative_path",
                        )
                    }
                    for entry in matches
                ]
                break
    return result


def inventory_weights(root: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Inventory a scoped source and create a fresh metadata-only evidence directory.

    Source paths are never modified. No retention inference is made. A PARTIAL
    receipt retains errors and any partial copies rather than deleting evidence.
    """
    source, destination = _scopes(root, output_dir)
    started = _utc_now()
    weights: list[dict[str, Any]] = []
    metadata: list[dict[str, Any]] = []
    excluded: list[str] = []
    rejected: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    ignored: Counter[str] = Counter()
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    root_fd = os.open(source, directory_flags)
    try:
        destination.mkdir(mode=0o700, parents=False, exist_ok=False)

        def walk(directory_fd: int, relative_dir: Path) -> None:
            try:
                with os.scandir(directory_fd) as iterator:
                    for entry in sorted(iterator, key=lambda item: item.name):
                        relative = relative_dir / entry.name
                        try:
                            observed = entry.stat(follow_symlinks=False)
                            if stat.S_ISLNK(observed.st_mode):
                                rejected.append(
                                    {
                                        "relative_path": relative.as_posix(),
                                        "reason": "SYMLINK_NOT_FOLLOWED",
                                    }
                                )
                                continue
                            if stat.S_ISDIR(observed.st_mode):
                                if entry.name.casefold() in EXCLUDED_DIRECTORIES:
                                    excluded.append(relative.as_posix())
                                    continue
                                child_fd = os.open(entry.name, directory_flags, dir_fd=directory_fd)
                                try:
                                    _require(
                                        _stat_identity(os.fstat(child_fd))
                                        == _stat_identity(observed),
                                        "directory changed before opening",
                                    )
                                    walk(child_fd, relative)
                                finally:
                                    os.close(child_fd)
                                continue
                            if not stat.S_ISREG(observed.st_mode):
                                rejected.append(
                                    {
                                        "relative_path": relative.as_posix(),
                                        "reason": "NON_REGULAR_FILE_NOT_READ",
                                    }
                                )
                                continue
                            suffix = relative.suffix.casefold()
                            if suffix in WEIGHT_EXTENSIONS:
                                record = _read_regular(
                                    directory_fd,
                                    entry.name,
                                    observed,
                                    relative,
                                    None,
                                )
                                record["classification"] = "WEIGHT_LIKE_FILE_ROLE_UNVERIFIED"
                                record["reconstructible_weight_backup"] = False
                                weights.append(record)
                            elif suffix in METADATA_EXTENSIONS or entry.name == "COMPLETED":
                                if observed.st_size > MAX_METADATA_BYTES:
                                    metadata.append(
                                        {
                                            "relative_path": relative.as_posix(),
                                            **_stat_values(observed),
                                            "status": "NOT_HASHED_METADATA_SIZE_LIMIT",
                                            "sha256": None,
                                            "backup_status": "NOT_COPIED_EXCEEDS_50_MIB",
                                        }
                                    )
                                    continue
                                record = _read_regular(
                                    directory_fd,
                                    entry.name,
                                    observed,
                                    relative,
                                    destination,
                                )
                                metadata.append(record)
                            else:
                                ignored[suffix or "<no_extension>"] += 1
                                continue
                            if record["status"] != "STATIC_VERIFIED":
                                errors.append(
                                    {
                                        "relative_path": relative.as_posix(),
                                        "reason": record.get("error", record["status"]),
                                    }
                                )
                        except (OSError, InventoryError) as exc:
                            errors.append(
                                {
                                    "relative_path": relative.as_posix(),
                                    "reason": f"{type(exc).__name__}: {exc}",
                                }
                            )
            except OSError as exc:
                errors.append({"relative_path": relative_dir.as_posix(), "reason": str(exc)})

        walk(root_fd, Path())
    finally:
        os.close(root_fd)

    for entry in weights:
        entry["closest_references"] = _closest_references(entry, metadata)
    unique_weights = {(entry["device"], entry["inode"]): entry for entry in weights}
    report = {
        "format": FORMAT,
        "status": "COMPLETE_WITH_DECLARED_EXCLUSIONS" if not errors and not rejected else "PARTIAL",
        "started_utc": started,
        "completed_utc": _utc_now(),
        "root": str(source),
        "output_dir": str(destination),
        "source_mutations_performed": False,
        "retention_policy_selected": False,
        "deletion_performed": False,
        "weight_backups_created": False,
        "metadata_size_limit_bytes": MAX_METADATA_BYTES,
        "weights": weights,
        "metadata": metadata,
        "excluded_directories": excluded,
        "rejected_paths": rejected,
        "errors": errors,
        "ignored_non_metadata_files_by_extension": dict(sorted(ignored.items())),
        "summary": {
            "weight_paths": len(weights),
            "static_weight_hashes": sum(entry["status"] == "STATIC_VERIFIED" for entry in weights),
            "weight_path_logical_bytes": sum(entry["size_bytes"] for entry in weights),
            "unique_weight_inodes": len(unique_weights),
            "unique_inode_logical_bytes": sum(
                entry["size_bytes"] for entry in unique_weights.values()
            ),
            "unique_inode_allocated_bytes": (
                sum(entry["allocated_bytes"] for entry in unique_weights.values())
                if all(entry["allocated_bytes"] is not None for entry in unique_weights.values())
                else None
            ),
            "metadata_copied": sum(
                entry["backup_status"] == "COPIED_AND_HASH_VERIFIED" for entry in metadata
            ),
            "metadata_not_copied_size_limit": sum(
                entry["backup_status"] == "NOT_COPIED_EXCEEDS_50_MIB" for entry in metadata
            ),
            "reclaimable_bytes": None,
        },
        "claim_boundary": (
            "Weight SHA-256 values are fingerprints, NOT reconstructible backups. Only listed "
            "small metadata files were copied. Weight roles and retention eligibility are "
            "unverified; no latest/previous selection or deletion is authorized or performed. "
            "Individual static "
            "reads are not an atomic experiment snapshot. Inode/block totals do not establish "
            "reclaimable space: out-of-scope hardlinks, filesystem clones and compression "
            "may matter."
        ),
    }
    inventory_path = destination / "INVENTORY.json"
    payload = (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with inventory_path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return {
        **report,
        "inventory_path": str(inventory_path),
        "inventory_sha256": hashlib.sha256(payload).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    try:
        report = inventory_weights(args.root, args.output_dir)
    except (InventoryError, OSError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc), "deletion_performed": False}))
        return 1
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "status",
                    "root",
                    "output_dir",
                    "inventory_path",
                    "inventory_sha256",
                    "summary",
                    "weight_backups_created",
                    "retention_policy_selected",
                    "deletion_performed",
                    "claim_boundary",
                )
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "COMPLETE_WITH_DECLARED_EXCLUSIONS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
