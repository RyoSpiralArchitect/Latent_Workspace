#!/usr/bin/env python3
"""Prepare, execute, and verify the exact transport-v2 weight cleanup.

The command is intentionally narrower than the formal verified-run pruner.
Transport-v2 artifacts are one-step engineering pilots, so the receipt uses a
distinct ``transport_pilot_weights_pruned`` state and never upgrades them to a
scientifically verified run.
"""

from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

INTENT_FORMAT = "latent-workspace-v10-transport-v2-weight-prune-intent-v1"
RECEIPT_FORMAT = "latent-workspace-v10-transport-v2-weight-prune-receipt-v1"
TRANSPORT_ROOT = PurePosixPath("runs/v10/transport_v2")
MODEL_CACHE_ROOT = PurePosixPath("runs/v10/model_cache")
EXPECTED_RUN_NAMES = (
    "B_cpu_accumulate_seed42_step1",
    "B_cuda_merge_reference_seed42_step1",
    "F0_all_base_seed42_step1_attempt2",
    "F0_cpu_accumulate_seed42_step1",
    "F0_cuda_merge_reference_seed42_step1",
    "F0_legacy_reference_seed42_step1",
    "F1_cpu_accumulate_seed42_step1",
    "F1_cuda_merge_reference_seed42_step1",
    "O3_cpu_accumulate_seed42_step1",
    "O3_cuda_merge_reference_seed42_step1",
)
EXPECTED_ROLES = ("checkpoint-1", "final")
SHARD_NAMES = tuple(f"model-{index:05d}-of-00004.safetensors" for index in range(1, 5))
EXPECTED_TARGET_COUNT = len(EXPECTED_RUN_NAMES) * len(EXPECTED_ROLES) * len(SHARD_NAMES)
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
SHARD_RE = re.compile(r"model-\d{5}-of-\d{5}\.safetensors\Z")
AT_FDCWD = -100
RENAME_NOREPLACE = 1

EVIDENCE_ROOT = "provenance/pilots/transport_v2_cpu_accumulate"
EVIDENCE_PATHS = (
    f"{EVIDENCE_ROOT}/BEHAVIOR_OBSERVATIONS.md",
    f"{EVIDENCE_ROOT}/B/B_CPU_ACCUMULATE_STEP1_TRANSPORT_ORACLE.json",
    f"{EVIDENCE_ROOT}/F0/F0_CPU_ACCUMULATE_STEP1_TRANSPORT_ORACLE.json",
    f"{EVIDENCE_ROOT}/F0/F0_CPU_ACCUMULATE_VS_CUDA_MERGE_STEP1_ORACLE.json",
    f"{EVIDENCE_ROOT}/negative_evidence/F0_STEP1_TRANSPORT_ORACLE.json",
    f"{EVIDENCE_ROOT}/F1/F1_CPU_ACCUMULATE_STEP1_TRANSPORT_ORACLE.json",
    f"{EVIDENCE_ROOT}/GENERATION_BEHAVIOR_V1.json",
    f"{EVIDENCE_ROOT}/O3/O3_CPU_ACCUMULATE_STEP1_TRANSPORT_ORACLE.json",
    f"{EVIDENCE_ROOT}/negative_evidence/GENERATION_BEHAVIOR_V1_UNBALANCED_SELECTION.json",
)


class TransportPruneError(RuntimeError):
    """An input, evidence, scope, or transaction invariant failed."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise TransportPruneError(message)


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TransportPruneError(f"Could not read JSON evidence: {path.name}") from exc


def _plain_root(path: Path) -> Path:
    expanded = path.expanduser()
    resolved = expanded.resolve()
    require(not expanded.is_symlink(), "Root must not be a symlink.")
    require(resolved.is_dir(), "Root must be a directory.")
    return resolved


def _pure_relative(value: str, *, label: str) -> PurePosixPath:
    pure = PurePosixPath(value)
    require(not pure.is_absolute(), f"{label} must be relative.")
    require(
        bool(pure.parts) and all(part not in {"", ".", ".."} for part in pure.parts),
        f"{label} is unsafe.",
    )
    return pure


def safe_existing(root: Path, relative: str, *, label: str) -> Path:
    pure = _pure_relative(relative, label=label)
    current = root
    for index, part in enumerate(pure.parts):
        current = current / part
        try:
            info = os.lstat(current)
        except OSError as exc:
            raise TransportPruneError(f"Missing {label}: {relative}") from exc
        if index < len(pure.parts) - 1:
            require(stat.S_ISDIR(info.st_mode), f"Symlink/non-directory in {label} path.")
    return current


def relative_inside(root: Path, path: Path, *, label: str) -> str:
    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise TransportPruneError(f"{label} must stay inside root.") from exc


def regular_single_link(path: Path, *, label: str) -> os.stat_result:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise TransportPruneError(f"Missing {label}.") from exc
    require(stat.S_ISREG(info.st_mode), f"{label} must be a regular file.")
    require(info.st_nlink == 1, f"{label} must have exactly one hard link.")
    return info


def path_entry_exists(path: Path) -> bool:
    """Return true for regular entries and dangling symlinks."""
    return path.exists() or path.is_symlink()


def target_inventory_sha256(targets: Sequence[Mapping[str, Any]]) -> str:
    return sha256_bytes(canonical_json_bytes(list(targets)))


def expected_target_paths() -> set[str]:
    return {
        (TRANSPORT_ROOT / run / role / "base_model" / shard).as_posix()
        for run in EXPECTED_RUN_NAMES
        for role in EXPECTED_ROLES
        for shard in SHARD_NAMES
    }


def _target_fields(relative: str) -> tuple[str, str, str]:
    pure = _pure_relative(relative, label="target path")
    require(
        len(pure.parts) == 7
        and PurePosixPath(*pure.parts[:3]) == TRANSPORT_ROOT
        and pure.parts[3] in EXPECTED_RUN_NAMES
        and pure.parts[4] in EXPECTED_ROLES
        and pure.parts[5] == "base_model"
        and pure.parts[6] in SHARD_NAMES
        and SHARD_RE.fullmatch(pure.name) is not None,
        f"Target is outside the frozen transport-v2 shard layout: {relative}",
    )
    return pure.parts[3], pure.parts[4], pure.parts[6]


def inventory_live_targets(
    root: Path,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]]]:
    transport = safe_existing(root, TRANSPORT_ROOT.as_posix(), label="transport root")
    require(transport.is_dir() and not transport.is_symlink(), "Transport root is invalid.")
    paths = sorted(transport.rglob("*.safetensors"), key=lambda item: item.as_posix())
    records: list[dict[str, Any]] = []
    runtime: dict[str, dict[str, int]] = {}
    seen_inodes: set[tuple[int, int]] = set()
    for path in paths:
        relative = relative_inside(root, path, label="target")
        run, role, _shard = _target_fields(relative)
        before = regular_single_link(path, label=f"target {relative}")
        inode_key = (before.st_dev, before.st_ino)
        require(inode_key not in seen_inodes, f"Duplicate target inode: {relative}")
        seen_inodes.add(inode_key)
        digest = sha256_file(path)
        after = regular_single_link(path, label=f"target {relative}")
        stable = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_blocks,
            before.st_nlink,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) == (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_blocks,
            after.st_nlink,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        require(stable, f"Target changed while hashing: {relative}")
        records.append(
            {
                "path": relative,
                "bytes": int(before.st_size),
                "allocated_bytes": int(before.st_blocks * 512),
                "sha256": digest,
                "run": run,
                "role": role,
            }
        )
        runtime[relative] = {
            "device": int(before.st_dev),
            "inode": int(before.st_ino),
            "bytes": int(before.st_size),
            "blocks": int(before.st_blocks),
            "nlink": int(before.st_nlink),
            "mtime_ns": int(before.st_mtime_ns),
        }
    require(len(records) == EXPECTED_TARGET_COUNT, "Live target count is not the frozen 80.")
    require(
        {record["path"] for record in records} == expected_target_paths(),
        "Live safetensor set is not the exact frozen transport-v2 target set.",
    )
    return records, runtime


def _validate_generation_receipt(value: Any) -> None:
    require(isinstance(value, dict), "Generation receipt must be an object.")
    require(value.get("status") == "PASS", "Generation behavior receipt did not pass.")
    profile = value.get("prompt_suite", {}).get("task_case_profile", {})
    require(profile.get("case_count") == 32, "Generation receipt case count mismatch.")
    require(
        profile.get("expected_choice_counts") == {"0": 16, "1": 16},
        "Generation receipt is not choice-balanced.",
    )
    parity = value.get("transport_behavior_parity")
    require(
        isinstance(parity, list)
        and len(parity) == 1
        and parity[0].get("left") == "B"
        and parity[0].get("right") == "B_reference"
        and parity[0].get("passed") is True,
        "Generation receipt lacks the passing B transport sentinel.",
    )


def validate_and_inventory_evidence(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for relative in EVIDENCE_PATHS:
        path = safe_existing(root, relative, label="evidence")
        info = regular_single_link(path, label=f"evidence {relative}")
        if relative.endswith("GENERATION_BEHAVIOR_V1.json") and "negative_evidence" not in relative:
            _validate_generation_receipt(load_json(path))
        elif relative.endswith("ORACLE.json"):
            value = load_json(path)
            require(
                isinstance(value, dict)
                and value.get("status") == "PASS"
                and value.get("result", {}).get("passed") is True,
                f"Oracle evidence did not pass: {relative}",
            )
        records.append(
            {
                "path": relative,
                "bytes": int(info.st_size),
                "sha256": sha256_file(path),
            }
        )
    return records


def verify_evidence_bindings(root: Path, expected: Sequence[Mapping[str, Any]]) -> None:
    actual = validate_and_inventory_evidence(root)
    require(actual == list(expected), "Bound evidence changed or is incomplete.")


def prepare_intent(
    root: Path,
    *,
    github_evidence_commit: str,
    implementation: Path,
) -> dict[str, Any]:
    require(COMMIT_RE.fullmatch(github_evidence_commit) is not None, "Bad evidence commit.")
    implementation_relative = relative_inside(root, implementation, label="implementation")
    implementation_info = regular_single_link(implementation, label="prune implementation")
    del implementation_info
    engine = safe_existing(
        root,
        "src/latent_workspace_ft_v10/engine.py",
        label="engine source",
    )
    regular_single_link(engine, label="engine source")
    evidence = validate_and_inventory_evidence(root)
    targets, _runtime = inventory_live_targets(root)
    return {
        "format": INTENT_FORMAT,
        "status": "prepared",
        "created_utc": utc_now(),
        "scope": {
            "root": TRANSPORT_ROOT.as_posix(),
            "run_names": list(EXPECTED_RUN_NAMES),
            "roles": list(EXPECTED_ROLES),
            "target_file_count": len(targets),
            "logical_bytes": sum(int(item["bytes"]) for item in targets),
            "allocated_bytes": sum(int(item["allocated_bytes"]) for item in targets),
            "target_inventory_sha256": target_inventory_sha256(targets),
        },
        "targets": targets,
        "evidence_bindings": evidence,
        "implementation": {
            "path": implementation_relative,
            "sha256": sha256_file(implementation),
            "engine_sha256": sha256_file(engine),
            "github_evidence_commit": github_evidence_commit,
        },
        "authorization_and_reason": {
            "operator_authorized_weight_cleanup": True,
            "reason": (
                "The user authorized recorded old-weight cleanup. Tensor/state parity, "
                "deterministic generation behavior, qualitative negative results, and "
                "the exact live shard inventory are durable before deletion."
            ),
        },
        "recoverability": {
            "deleted_trained_weights_recoverable_from_retained_hashes": False,
            "hashes_and_receipts_are_a_weight_backup": False,
            "upstream_pinned_model_cache_is_protected": True,
            "non_weight_run_metadata_is_retained": True,
        },
        "claim_boundary": (
            "This intent records exact one-step transport-pilot shard bodies. It does "
            "not classify the pilots as scientifically verified, and deletion cannot "
            "be reversed from the retained hashes or decoded outputs."
        ),
    }


def atomic_create(path: Path, payload: bytes) -> None:
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
            os.link(temporary, path)
        except FileExistsError as exc:
            raise TransportPruneError(f"Refusing to replace existing file: {path.name}") from exc
        temporary.unlink()
    finally:
        temporary.unlink(missing_ok=True)


def atomic_create_json(path: Path, value: Mapping[str, Any]) -> None:
    atomic_create(path, canonical_json_bytes(value))


def snapshot_tree_metadata(path: Path) -> list[dict[str, Any]]:
    require(path.is_dir() and not path.is_symlink(), "Protected model cache is invalid.")
    records: list[dict[str, Any]] = []
    for child in sorted(path.rglob("*"), key=lambda item: item.as_posix()):
        info = os.lstat(child)
        record: dict[str, Any] = {
            "path": child.relative_to(path).as_posix(),
            "mode": int(info.st_mode),
            "size": int(info.st_size),
            "mtime_ns": int(info.st_mtime_ns),
            "inode": int(info.st_ino),
            "device": int(info.st_dev),
        }
        if stat.S_ISLNK(info.st_mode):
            record["symlink_target"] = os.readlink(child)
        records.append(record)
    require(records, "Protected model cache metadata is empty.")
    return records


def _same_runtime(info: os.stat_result, expected: Mapping[str, int]) -> bool:
    return (
        int(info.st_dev) == expected["device"]
        and int(info.st_ino) == expected["inode"]
        and int(info.st_size) == expected["bytes"]
        and int(info.st_blocks) == expected["blocks"]
        and int(info.st_nlink) == expected["nlink"]
        and int(info.st_mtime_ns) == expected["mtime_ns"]
    )


def rename_noreplace(source: Path, destination: Path) -> str:
    if sys.platform == "linux":
        libc = ctypes.CDLL(None, use_errno=True)
        require(hasattr(libc, "renameat2"), "Linux renameat2 is unavailable.")
        renameat2 = libc.renameat2
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(
            AT_FDCWD,
            os.fsencode(source),
            AT_FDCWD,
            os.fsencode(destination),
            RENAME_NOREPLACE,
        )
        if result != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(source), str(destination))
        return "Linux renameat2(RENAME_NOREPLACE)"
    require(not destination.exists() and not destination.is_symlink(), "Destination exists.")
    os.rename(source, destination)
    return "os.rename with prevalidated absent destination (non-Linux test fallback)"


def rollback(
    root: Path,
    payload_root: Path,
    moved: Sequence[str],
    runtime: Mapping[str, Mapping[str, int]],
) -> None:
    failures: list[str] = []
    for relative in reversed(moved):
        original = root / relative
        quarantined = payload_root / relative
        try:
            require(not path_entry_exists(original), "Rollback source exists.")
            info = regular_single_link(quarantined, label="rollback target")
            require(_same_runtime(info, runtime[relative]), "Rollback inode changed.")
            original.parent.mkdir(parents=True, exist_ok=True)
            rename_noreplace(quarantined, original)
        except Exception as exc:  # noqa: BLE001 - aggregate every rollback failure
            failures.append(f"{relative}: {exc}")
    require(not failures, "Rollback failed: " + "; ".join(failures))


def _validate_intent(intent: Any) -> dict[str, Any]:
    require(isinstance(intent, dict), "Intent must be an object.")
    require(intent.get("format") == INTENT_FORMAT, "Intent format mismatch.")
    require(intent.get("status") == "prepared", "Intent is not prepared.")
    targets = intent.get("targets")
    require(isinstance(targets, list), "Intent targets must be a list.")
    require(len(targets) == EXPECTED_TARGET_COUNT, "Intent target count mismatch.")
    target_paths: list[str] = []
    for target in targets:
        require(isinstance(target, dict), "Intent target must be an object.")
        relative = str(target.get("path", ""))
        run, role, _shard = _target_fields(relative)
        target_paths.append(relative)
        require(
            isinstance(target.get("bytes"), int)
            and target["bytes"] >= 0
            and isinstance(target.get("allocated_bytes"), int)
            and target["allocated_bytes"] >= 0
            and isinstance(target.get("sha256"), str)
            and SHA256_RE.fullmatch(target["sha256"]) is not None,
            "Intent target record is invalid.",
        )
        require(
            target.get("run") == run and target.get("role") == role,
            "Intent target run/role fields do not match its path.",
        )
    require(
        target_paths == sorted(expected_target_paths()),
        "Intent target list is not the exact sorted frozen target set.",
    )
    scope = intent.get("scope", {})
    require(scope.get("root") == TRANSPORT_ROOT.as_posix(), "Intent scope root mismatch.")
    require(
        scope.get("run_names") == list(EXPECTED_RUN_NAMES)
        and scope.get("roles") == list(EXPECTED_ROLES)
        and scope.get("target_file_count") == EXPECTED_TARGET_COUNT,
        "Intent scope inventory dimensions mismatch.",
    )
    require(
        scope.get("target_inventory_sha256") == target_inventory_sha256(targets),
        "Intent target inventory hash mismatch.",
    )
    require(
        scope.get("logical_bytes") == sum(target["bytes"] for target in targets)
        and scope.get("allocated_bytes") == sum(target["allocated_bytes"] for target in targets),
        "Intent target byte totals mismatch.",
    )
    evidence = intent.get("evidence_bindings")
    require(isinstance(evidence, list), "Intent evidence bindings must be a list.")
    require(
        [item.get("path") for item in evidence if isinstance(item, dict)] == list(EVIDENCE_PATHS),
        "Intent evidence path list mismatch.",
    )
    require(
        all(
            isinstance(item, dict)
            and isinstance(item.get("bytes"), int)
            and item["bytes"] >= 0
            and isinstance(item.get("sha256"), str)
            and SHA256_RE.fullmatch(item["sha256"]) is not None
            for item in evidence
        ),
        "Intent evidence binding is invalid.",
    )
    implementation = intent.get("implementation", {})
    require(
        implementation.get("path") == "scripts/prune_transport_v2_weights.py"
        and isinstance(implementation.get("sha256"), str)
        and SHA256_RE.fullmatch(implementation["sha256"]) is not None
        and isinstance(implementation.get("engine_sha256"), str)
        and SHA256_RE.fullmatch(implementation["engine_sha256"]) is not None
        and isinstance(implementation.get("github_evidence_commit"), str)
        and COMMIT_RE.fullmatch(implementation["github_evidence_commit"]) is not None,
        "Intent implementation binding is invalid.",
    )
    require(
        intent.get("authorization_and_reason", {}).get("operator_authorized_weight_cleanup")
        is True,
        "Intent does not record cleanup authorization.",
    )
    recoverability = intent.get("recoverability", {})
    require(
        recoverability.get("deleted_trained_weights_recoverable_from_retained_hashes") is False
        and recoverability.get("hashes_and_receipts_are_a_weight_backup") is False
        and recoverability.get("upstream_pinned_model_cache_is_protected") is True
        and recoverability.get("non_weight_run_metadata_is_retained") is True,
        "Intent recoverability boundary is invalid.",
    )
    return intent


def execute_transaction(
    root: Path,
    *,
    intent_path: Path,
    expected_intent_sha256: str,
    published_intent_commit: str,
    quarantine_root: Path,
    implementation: Path,
) -> dict[str, Any]:
    require(SHA256_RE.fullmatch(expected_intent_sha256) is not None, "Bad intent hash.")
    require(COMMIT_RE.fullmatch(published_intent_commit) is not None, "Bad publish commit.")
    require(relative_inside(root, intent_path, label="intent"), "Intent path is empty.")
    intent_info = regular_single_link(intent_path, label="prune intent")
    del intent_info
    require(sha256_file(intent_path) == expected_intent_sha256, "Intent hash mismatch.")
    intent = _validate_intent(load_json(intent_path))
    implementation_relative = relative_inside(root, implementation, label="implementation")
    require(
        implementation_relative == intent["implementation"]["path"]
        and sha256_file(implementation) == intent["implementation"]["sha256"],
        "Prune implementation changed after intent preparation.",
    )
    engine = safe_existing(
        root,
        "src/latent_workspace_ft_v10/engine.py",
        label="engine source",
    )
    regular_single_link(engine, label="engine source")
    require(
        sha256_file(engine) == intent["implementation"]["engine_sha256"],
        "Engine source changed after intent preparation.",
    )
    verify_evidence_bindings(root, intent["evidence_bindings"])

    live_targets, runtime = inventory_live_targets(root)
    require(live_targets == intent["targets"], "Live targets differ from the published intent.")
    model_cache = safe_existing(root, MODEL_CACHE_ROOT.as_posix(), label="model cache")
    model_cache_before = snapshot_tree_metadata(model_cache)
    model_cache_snapshot_sha256 = sha256_bytes(canonical_json_bytes(model_cache_before))

    quarantine_candidate = quarantine_root.expanduser()
    require(not quarantine_candidate.is_symlink(), "Quarantine must not be a symlink.")
    quarantine = quarantine_candidate.resolve()
    require(quarantine != root and root not in quarantine.parents, "Unsafe quarantine root.")
    require(quarantine.is_dir() and not quarantine.is_symlink(), "Quarantine is invalid.")
    require(not any(quarantine.iterdir()), "Quarantine must start empty.")
    require(quarantine.stat().st_dev == root.stat().st_dev, "Quarantine must share filesystem.")
    quarantine_intent = quarantine / "PRUNE_INTENT.json"
    atomic_create(quarantine_intent, intent_path.read_bytes())
    require(sha256_file(quarantine_intent) == expected_intent_sha256, "Intent copy mismatch.")

    started_utc = utc_now()
    available_before = shutil.disk_usage(root).free
    payload_root = quarantine / "payload"
    payload_root.mkdir(mode=0o700)
    moved: list[str] = []
    rename_method: str | None = None
    try:
        for target in intent["targets"]:
            relative = target["path"]
            source = root / relative
            destination = payload_root / relative
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            require(
                not path_entry_exists(destination),
                f"Quarantine destination exists: {relative}",
            )
            require(
                source.stat().st_dev == destination.parent.stat().st_dev,
                "Cross-filesystem target.",
            )
            method = rename_noreplace(source, destination)
            rename_method = method if rename_method is None else rename_method
            require(rename_method == method, "Rename method changed during transaction.")
            moved.append(relative)
            info = regular_single_link(destination, label="quarantined target")
            require(_same_runtime(info, runtime[relative]), "Quarantined inode changed.")
        for relative in moved:
            require(
                not path_entry_exists(root / relative),
                "Source remains after quarantine rename.",
            )
            info = regular_single_link(payload_root / relative, label="quarantined target")
            require(_same_runtime(info, runtime[relative]), "Quarantined target changed.")
        require(len(moved) == EXPECTED_TARGET_COUNT, "Not all targets reached quarantine.")
        verify_evidence_bindings(root, intent["evidence_bindings"])
        require(
            snapshot_tree_metadata(model_cache) == model_cache_before,
            "Protected model cache changed during quarantine.",
        )
    except Exception:
        rollback(root, payload_root, moved, runtime)
        raise

    quarantine_verified_utc = utc_now()
    quarantine_state = {
        "format": "latent-workspace-v10-transport-v2-quarantine-state-v1",
        "status": "verified_before_unlink",
        "intent_sha256": expected_intent_sha256,
        "target_inventory_sha256": intent["scope"]["target_inventory_sha256"],
        "target_file_count": len(moved),
        "verified_utc": quarantine_verified_utc,
    }
    atomic_create_json(quarantine / "QUARANTINE_VERIFIED.json", quarantine_state)
    available_after_quarantine = shutil.disk_usage(root).free

    for relative in moved:
        destination = payload_root / relative
        info = regular_single_link(destination, label="pre-unlink target")
        require(_same_runtime(info, runtime[relative]), "Pre-unlink target changed.")
    for relative in moved:
        os.unlink(payload_root / relative)

    for relative in moved:
        require(not path_entry_exists(root / relative), "Deleted source reappeared.")
        require(
            not path_entry_exists(payload_root / relative),
            "Quarantine target remains.",
        )
    require(
        not any(path.is_file() or path.is_symlink() for path in payload_root.rglob("*")),
        "Quarantine payload still contains files.",
    )
    transport = root / TRANSPORT_ROOT
    require(not any(transport.rglob("*.safetensors")), "Transport-v2 weights remain.")
    verify_evidence_bindings(root, intent["evidence_bindings"])
    require(
        snapshot_tree_metadata(model_cache) == model_cache_before,
        "Protected model cache changed after unlink.",
    )
    available_after_unlink = shutil.disk_usage(root).free

    receipt: dict[str, Any] = {
        "format": RECEIPT_FORMAT,
        "status": "transport_pilot_weights_pruned",
        "completed": True,
        "started_utc": started_utc,
        "quarantine_verified_utc": quarantine_verified_utc,
        "completed_utc": utc_now(),
        "intent": {
            "path": relative_inside(root, intent_path, label="intent"),
            "sha256": expected_intent_sha256,
            "target_inventory_sha256": intent["scope"]["target_inventory_sha256"],
            "github_evidence_commit": intent["implementation"]["github_evidence_commit"],
            "github_published_intent_commit": published_intent_commit,
        },
        "implementation": {
            "path": implementation_relative,
            "sha256": sha256_file(implementation),
        },
        "transaction": {
            "quarantine": {
                "location_scope": "same_filesystem_outside_repository",
                "basename": quarantine.name,
            },
            "rename_method": rename_method,
            "all_inode_identities_preserved_through_quarantine": True,
            "all_targets_rehashed_after_published_intent": True,
            "deleted_paths": moved,
            "deleted_file_count": len(moved),
            "deleted_logical_bytes": intent["scope"]["logical_bytes"],
            "deleted_allocated_bytes": intent["scope"]["allocated_bytes"],
            "no_directory_removal": True,
            "no_unlisted_file_removal": True,
        },
        "evidence": {
            "bindings": intent["evidence_bindings"],
            "all_reverified_before_quarantine_and_after_unlink": True,
        },
        "post_prune_checks": {
            "transport_v2_safetensor_count": 0,
            "protected_model_cache_metadata_unchanged": True,
            "protected_model_cache_snapshot_sha256": model_cache_snapshot_sha256,
            "non_weight_run_metadata_retained": True,
        },
        "storage": {
            "available_bytes_before": available_before,
            "available_bytes_after_quarantine": available_after_quarantine,
            "available_bytes_after_unlink": available_after_unlink,
            "observed_unlink_free_delta_bytes": available_after_unlink - available_after_quarantine,
            "expected_allocated_bytes": intent["scope"]["allocated_bytes"],
            "unlink_delta_matches_expected_allocation": available_after_unlink
            - available_after_quarantine
            == intent["scope"]["allocated_bytes"],
        },
        "recoverability": intent["recoverability"],
        "claim_boundary": (
            "This receipt proves exact deletion of the published transport-v2 "
            "safetensor paths after evidence and cache protection checks. It does not "
            "upgrade the one-step pilots to a positive scientific result."
        ),
    }
    receipt["report_sha256"] = sha256_bytes(canonical_json_bytes(receipt))
    return receipt


def verify_receipt(root: Path, receipt_path: Path) -> dict[str, Any]:
    receipt_info = regular_single_link(receipt_path, label="prune receipt")
    del receipt_info
    receipt = load_json(receipt_path)
    require(isinstance(receipt, dict), "Receipt must be an object.")
    require(
        receipt.get("format") == RECEIPT_FORMAT
        and receipt.get("status") == "transport_pilot_weights_pruned"
        and receipt.get("completed") is True,
        "Receipt status is invalid.",
    )
    report_hash = receipt.pop("report_sha256", None)
    require(
        isinstance(report_hash, str) and report_hash == sha256_bytes(canonical_json_bytes(receipt)),
        "Receipt report hash mismatch.",
    )
    receipt["report_sha256"] = report_hash
    intent_relative = receipt["intent"]["path"]
    intent_path = safe_existing(root, intent_relative, label="bound intent")
    require(
        sha256_file(intent_path) == receipt["intent"]["sha256"],
        "Bound intent hash mismatch.",
    )
    intent = _validate_intent(load_json(intent_path))
    require(
        intent["scope"]["target_inventory_sha256"] == receipt["intent"]["target_inventory_sha256"],
        "Bound target inventory mismatch.",
    )
    require(
        receipt["intent"].get("github_evidence_commit")
        == intent["implementation"]["github_evidence_commit"]
        and isinstance(receipt["intent"].get("github_published_intent_commit"), str)
        and COMMIT_RE.fullmatch(receipt["intent"]["github_published_intent_commit"]) is not None,
        "Receipt GitHub commit bindings are invalid.",
    )
    expected_paths = [target["path"] for target in intent["targets"]]
    transaction = receipt.get("transaction", {})
    quarantine = transaction.get("quarantine", {})
    require(
        quarantine.get("location_scope") == "same_filesystem_outside_repository"
        and isinstance(quarantine.get("basename"), str)
        and quarantine["basename"] not in {"", ".", ".."}
        and "/" not in quarantine["basename"],
        "Receipt quarantine description is invalid.",
    )
    require(
        transaction.get("deleted_paths") == expected_paths
        and transaction.get("deleted_file_count") == EXPECTED_TARGET_COUNT
        and transaction.get("deleted_logical_bytes") == intent["scope"]["logical_bytes"]
        and transaction.get("deleted_allocated_bytes") == intent["scope"]["allocated_bytes"]
        and transaction.get("all_inode_identities_preserved_through_quarantine") is True
        and transaction.get("all_targets_rehashed_after_published_intent") is True
        and transaction.get("no_directory_removal") is True
        and transaction.get("no_unlisted_file_removal") is True,
        "Receipt deletion transaction does not match the bound intent.",
    )
    require(
        receipt.get("recoverability") == intent["recoverability"],
        "Receipt recoverability boundary differs from the intent.",
    )
    verify_evidence_bindings(root, receipt["evidence"]["bindings"])
    require(
        all(not path_entry_exists(root / target["path"]) for target in intent["targets"]),
        "A deleted target exists.",
    )
    require(
        not any((root / TRANSPORT_ROOT).rglob("*.safetensors")),
        "Transport-v2 safetensors remain.",
    )
    cache_snapshot = snapshot_tree_metadata(root / MODEL_CACHE_ROOT)
    require(
        sha256_bytes(canonical_json_bytes(cache_snapshot))
        == receipt["post_prune_checks"]["protected_model_cache_snapshot_sha256"],
        "Protected model cache metadata differs from the receipt.",
    )
    return {
        "status": "PASS",
        "state": "transport_pilot_weights_pruned",
        "receipt_sha256": sha256_file(receipt_path),
        "deleted_file_count": receipt["transaction"]["deleted_file_count"],
        "deleted_logical_bytes": receipt["transaction"]["deleted_logical_bytes"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--root", type=Path, required=True)
    prepare.add_argument("--github-evidence-commit", required=True)
    prepare.add_argument("--output", type=Path, required=True)

    execute = subparsers.add_parser("execute")
    execute.add_argument("--root", type=Path, required=True)
    execute.add_argument("--intent", type=Path, required=True)
    execute.add_argument("--expected-intent-sha256", required=True)
    execute.add_argument("--published-intent-commit", required=True)
    execute.add_argument("--quarantine", type=Path, required=True)
    execute.add_argument("--receipt", type=Path, required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--root", type=Path, required=True)
    verify.add_argument("--receipt", type=Path, required=True)
    return parser


def _root_path(root: Path, value: Path, *, label: str) -> Path:
    candidate = value if value.is_absolute() else root / value
    relative_inside(root, candidate, label=label)
    return candidate.resolve()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = _plain_root(args.root)
        implementation = Path(__file__).resolve()
        if args.command == "prepare":
            output = _root_path(root, args.output, label="intent output")
            intent = prepare_intent(
                root,
                github_evidence_commit=args.github_evidence_commit,
                implementation=implementation,
            )
            atomic_create_json(output, intent)
            print(f"PREPARED: {relative_inside(root, output, label='intent output')}")
            print(f"INTENT_SHA256: {sha256_file(output)}")
        elif args.command == "execute":
            intent_path = _root_path(root, args.intent, label="intent")
            receipt_path = _root_path(root, args.receipt, label="receipt output")
            require(not receipt_path.exists(), "Receipt output already exists.")
            receipt = execute_transaction(
                root,
                intent_path=intent_path,
                expected_intent_sha256=args.expected_intent_sha256,
                published_intent_commit=args.published_intent_commit,
                quarantine_root=args.quarantine,
                implementation=implementation,
            )
            atomic_create_json(receipt_path, receipt)
            result = verify_receipt(root, receipt_path)
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            receipt_path = _root_path(root, args.receipt, label="receipt")
            print(json.dumps(verify_receipt(root, receipt_path), indent=2, sort_keys=True))
    except Exception as exc:
        message = str(exc) if isinstance(exc, TransportPruneError) else type(exc).__name__
        print(f"ERROR: {message}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
