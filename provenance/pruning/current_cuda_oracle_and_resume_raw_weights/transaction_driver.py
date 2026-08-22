#!/usr/bin/env python3
"""Execute the exact, evidence-gated raw-weight cleanup recorded in PRUNE_INTENT.json."""

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
from pathlib import Path, PurePosixPath
from typing import Any

EXPECTED_INTENT_SHA256 = "3ea1f1cc58b029e8241cac0074d32460e152f91ef72f6d0603afec43516ad636"
EXPECTED_TARGET_INVENTORY_SHA256 = (
    "6e6ac9eec344f34cad0e54f77caa92ddfc158ab186c0a6d5ad6049bceab0e3ca"
)
EXPECTED_TARGET_COUNT = 76
EXPECTED_LOGICAL_BYTES = 275_425_537_480
EXPECTED_ALLOCATED_BYTES = 275_426_062_336
SHARD_NAMES = tuple(f"model-{index:05d}-of-00004.safetensors" for index in range(1, 5))
SHARD_RE = re.compile(r"model-\d{5}-of-\d{5}\.safetensors\Z")
AT_FDCWD = -100
RENAME_NOREPLACE = 1

ALLOWED_BUNDLE_DIRS = {
    "runs/v10/_historical_source/engine_d5f2ef1d137f5db1_runner_afd045c4dfa2c899_allocator_verified_successor_replacement/resume_equivalence/F0_query_only/seed_42_step4/control_uninterrupted/final/base_model",
    "runs/v10/parity/B_local_invariance_reduced_native/seed_42/final/base_model",
    "runs/v10/parity/F0_query_only_native/seed_42/final/base_model",
}
for _variant in (
    "B_local_invariance",
    "F0_query_only",
    "F1_inline_upper",
    "O3_slots4_k1_lw_cf",
):
    _resume_root = f"runs/v10/resume_equivalence/{_variant}/seed_42_step4"
    ALLOWED_BUNDLE_DIRS.update(
        {
            f"{_resume_root}/control_uninterrupted/checkpoint-4/base_model",
            f"{_resume_root}/control_uninterrupted/checkpoint-8/base_model",
            f"{_resume_root}/control_uninterrupted/final/base_model",
            f"{_resume_root}/resumed_from_split/final/base_model",
        }
    )


class CleanupError(RuntimeError):
    """A fail-closed validation or transaction error."""


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CleanupError(message)


def safe_path(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    require(not pure.is_absolute(), f"absolute path rejected: {relative}")
    require(
        pure.parts and all(part not in {"", ".", ".."} for part in pure.parts),
        f"unsafe path: {relative}",
    )
    current = root
    for part in pure.parts[:-1]:
        current = current / part
        info = os.lstat(current)
        require(stat.S_ISDIR(info.st_mode), f"non-directory or symlink in parent chain: {current}")
    return root.joinpath(*pure.parts)


def regular_single_link(path: Path) -> os.stat_result:
    info = os.lstat(path)
    require(stat.S_ISREG(info.st_mode), f"target is not a regular file: {path}")
    require(info.st_nlink == 1, f"target link count is not one: {path}")
    return info


def canonical_target_inventory_sha256(targets: list[dict[str, Any]]) -> str:
    payload = (json.dumps(targets, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()
    return hashlib.sha256(payload).hexdigest()


def evidence_records(intent: dict[str, Any]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for binding in intent["evidence_bindings"]:
        if "path" in binding:
            records.append({"path": binding["path"], "sha256": binding["sha256"]})
        for artifact in binding.get("artifacts", []):
            records.append({"path": artifact["path"], "sha256": artifact["sha256"]})
    return records


def target_group(targets: list[dict[str, Any]], directory: str) -> list[dict[str, Any]]:
    group = [item for item in targets if str(PurePosixPath(item["path"]).parent) == directory]
    group.sort(key=lambda item: item["path"])
    return group


def receipt_weight_records(receipt: dict[str, Any], key: str) -> list[dict[str, Any]]:
    records = [
        item
        for item in receipt["artifact_inventories"][key]
        if re.search(r"base_model/model-.*\.safetensors\Z", item["path"])
    ]
    records.sort(key=lambda item: item["path"])
    return records


def same_shards(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> bool:
    return [(PurePosixPath(item["path"]).name, item["bytes"], item["sha256"]) for item in left] == [
        (PurePosixPath(item["path"]).name, item["bytes"], item["sha256"]) for item in right
    ]


def verify_resume_receipt(
    root: Path,
    intent: dict[str, Any],
    variant: str,
    receipt_path: str,
) -> None:
    receipt = load_json(safe_path(root, receipt_path))
    resume_root = f"runs/v10/resume_equivalence/{variant}/seed_42_step4"
    require(receipt.get("passed") is True, f"resume receipt not passed: {variant}")
    require(
        receipt.get("comparisons", {}).get("passed") is True,
        f"resume comparisons not passed: {variant}",
    )
    require(
        receipt.get("bundle_identity_bindings", {}).get("passed") is True,
        f"bundle binding not passed: {variant}",
    )
    require(
        receipt.get("gradient_accumulation_offload_receipt_bindings", {}).get("passed") is True,
        f"offload receipt binding not passed: {variant}",
    )
    require(
        receipt.get("gradient_accumulation_offload_binding", {}).get("required") == "cpu",
        f"resume offload mode is not CPU: {variant}",
    )
    require(
        receipt["design"]["control_B"] == f"{resume_root}/control_uninterrupted",
        f"control path mismatch: {variant}",
    )
    require(
        receipt["design"]["resumed_C"] == f"{resume_root}/resumed_from_split",
        f"resumed path mismatch: {variant}",
    )

    checkpoint4 = target_group(
        intent["targets"], f"{resume_root}/control_uninterrupted/checkpoint-4/base_model"
    )
    checkpoint8 = target_group(
        intent["targets"], f"{resume_root}/control_uninterrupted/checkpoint-8/base_model"
    )
    control_final = target_group(
        intent["targets"], f"{resume_root}/control_uninterrupted/final/base_model"
    )
    resumed_final = target_group(
        intent["targets"], f"{resume_root}/resumed_from_split/final/base_model"
    )
    require(
        same_shards(checkpoint4, receipt_weight_records(receipt, "checkpoint_B_split")),
        f"checkpoint-4 receipt mismatch: {variant}",
    )
    require(
        same_shards(control_final, receipt_weight_records(receipt, "final_B")),
        f"control final receipt mismatch: {variant}",
    )
    require(
        same_shards(resumed_final, receipt_weight_records(receipt, "final_C")),
        f"resumed final receipt mismatch: {variant}",
    )
    require(
        same_shards(checkpoint8, receipt_weight_records(receipt, "final_B")),
        f"checkpoint-8 is not byte-identical to bound final_B: {variant}",
    )


def verify_evidence(root: Path, intent: dict[str, Any]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for record in evidence_records(intent):
        path = safe_path(root, record["path"])
        info = os.lstat(path)
        require(stat.S_ISREG(info.st_mode), f"evidence is not a regular file: {record['path']}")
        actual = sha256_file(path)
        require(actual == record["sha256"], f"evidence hash mismatch: {record['path']}")
        observed[record["path"]] = actual

    old_path = (
        "runs/v10/oracles/F0_query_only/seed_42_cpu_spill_vs_d5_native/FULL_MODEL_ORACLE.json"
    )
    old = load_json(safe_path(root, old_path))
    old_model_root = next(
        item for item in intent["targets"] if item["classification"].startswith("retired_d5")
    )["path"].rsplit("/", 1)[0]
    require(old.get("status") == "PASS", "old d5 oracle status is not PASS")
    require(old.get("result", {}).get("passed") is True, "old d5 oracle result is not passed")
    require(
        old["result"]["base_model"].get("passed") is True, "old d5 base comparison is not passed"
    )
    require(
        old["inputs"]["oracle"]["model_root"] == old_model_root,
        "old d5 oracle path binding mismatch",
    )
    counts = old["result"]["base_model"]["counts"]
    require(counts["byte_compared_tensor_count"] == 291, "old d5 tensor count mismatch")
    require(counts["byte_compared_element_count"] == 7_248_023_552, "old d5 element count mismatch")
    require(counts["total_mismatch_tensor_count"] == 0, "old d5 oracle has mismatches")
    require(
        same_shards(
            target_group(intent["targets"], old_model_root),
            old["inputs"]["oracle"]["indexed_safetensors"]["shards"],
        ),
        "old d5 shard binding mismatch",
    )

    current_path = (
        "runs/v10/oracles/F0_query_only/seed_42_cpu_spill_vs_native_current/FULL_MODEL_ORACLE.json"
    )
    current = load_json(safe_path(root, current_path))
    current_root = "runs/v10/parity/F0_query_only_native/seed_42/final/base_model"
    require(current.get("status") == "PASS", "current F0 oracle status is not PASS")
    require(
        current.get("result", {}).get("passed") is True, "current F0 oracle result is not passed"
    )
    require(
        current["result"]["base_model"].get("passed") is True,
        "current F0 base comparison is not passed",
    )
    require(
        current["result"]["run_bundle"].get("passed") is True, "current F0 run bundle is not passed"
    )
    require(
        current["claims"]["source_evidence"].get("current_source_matched") is True,
        "current F0 source is not matched",
    )
    require(
        current["inputs"]["oracle"]["model_root"] == current_root,
        "current F0 oracle path binding mismatch",
    )
    require(
        same_shards(
            target_group(intent["targets"], current_root),
            current["inputs"]["oracle"]["indexed_safetensors"]["shards"],
        ),
        "current F0 shard binding mismatch",
    )

    for variant in ("F0_query_only", "B_local_invariance", "F1_inline_upper", "O3_slots4_k1_lw_cf"):
        verify_resume_receipt(
            root,
            intent,
            variant,
            f"runs/v10/resume_equivalence/{variant}/seed_42_step4/RESUME_EQUIVALENCE.json",
        )

    for path in (
        "runs/v10/compact_exports/smoke/F0_query_only/seed_42/RUN_VERIFICATION.json",
        "runs/v10/compact_exports/smoke/B_local_invariance/seed_42/RUN_VERIFICATION.json",
        "runs/v10/compact_exports/smoke/F1_inline_upper/seed_42/RUN_VERIFICATION.json",
        "runs/v10/compact_exports/smoke/O3_slots4_k1_lw_cf/seed_42/smoke/O3_slots4_k1_lw_cf/seed_42/RUN_VERIFICATION.json",
    ):
        require(
            load_json(safe_path(root, path)).get("verified") is True,
            f"compact verification is not verified: {path}",
        )
    for path in (
        "runs/v10/smoke/F0_query_only/seed_42/PRUNE_RECEIPT.json",
        "runs/v10/smoke/B_local_invariance/seed_42/PRUNE_RECEIPT.json",
        "runs/v10/smoke/F1_inline_upper/seed_42/PRUNE_RECEIPT.json",
        "runs/v10/smoke/O3_slots4_k1_lw_cf/seed_42/PRUNE_RECEIPT.json",
    ):
        receipt = load_json(safe_path(root, path))
        require(
            receipt.get("state") == "verified_pruned" and receipt.get("completed") is True,
            f"formal prune receipt invalid: {path}",
        )

    b_manifest = load_json(
        safe_path(
            root, "runs/v10/parity/B_local_invariance_reduced_native/seed_42/final/manifest.json"
        )
    )
    b_config = load_json(
        safe_path(
            root,
            "runs/v10/parity/B_local_invariance_reduced_native/seed_42/final/experiment_config.json",
        )
    )
    require(
        b_manifest.get("complete") is True and b_manifest.get("global_step") == 2,
        "B diagnostic manifest is not complete at step 2",
    )
    require(
        b_manifest.get("source_sha256")
        == "755ddaee835cd6cf0d30269212226250a5aeed14e5457385ceca60db0f39aa3c",
        "B diagnostic source mismatch",
    )
    train = b_config.get("train", {})
    require(train.get("gradient_accumulation_steps") == 1, "B diagnostic gradacc mismatch")
    require(train.get("gradient_accumulation_offload") == "none", "B diagnostic offload mismatch")
    require(train.get("max_steps") == 2, "B diagnostic step horizon mismatch")
    require(
        safe_path(
            root, "runs/v10/parity/B_local_invariance_reduced_native/seed_42/final/COMPLETED"
        ).read_bytes()
        == b"ok\n",
        "B diagnostic completion marker mismatch",
    )

    for audit in intent["failed_parity_attempt_audit"]:
        attempt = safe_path(root, audit["path"] + "/sentinel").parent
        require(
            attempt.is_dir() and not attempt.is_symlink(),
            f"failed parity root invalid: {audit['path']}",
        )
        require(
            not (attempt / "final").exists(), f"failed parity attempt has a final: {audit['path']}"
        )
        require(
            not any(attempt.rglob("*.safetensors")),
            f"failed parity attempt has weights: {audit['path']}",
        )
    return observed


def snapshot_tree_metadata(path: Path) -> list[dict[str, Any]]:
    require(path.is_dir() and not path.is_symlink(), f"protected tree invalid: {path}")
    records: list[dict[str, Any]] = []
    for child in sorted(path.rglob("*"), key=lambda item: str(item)):
        info = os.lstat(child)
        record: dict[str, Any] = {
            "path": str(child.relative_to(path)),
            "mode": info.st_mode,
            "size": info.st_size,
            "mtime_ns": info.st_mtime_ns,
            "inode": info.st_ino,
            "device": info.st_dev,
        }
        if stat.S_ISLNK(info.st_mode):
            record["symlink_target"] = os.readlink(child)
        records.append(record)
    return records


def validate_targets(
    root: Path, intent: dict[str, Any]
) -> tuple[dict[str, dict[str, int]], int, int]:
    targets = intent["targets"]
    require(len(targets) == EXPECTED_TARGET_COUNT, "target count mismatch")
    require(
        len({item["path"] for item in targets}) == EXPECTED_TARGET_COUNT, "duplicate target path"
    )
    require(
        sum(item["bytes"] for item in targets) == EXPECTED_LOGICAL_BYTES,
        "intent logical-byte mismatch",
    )
    require(
        canonical_target_inventory_sha256(targets) == EXPECTED_TARGET_INVENTORY_SHA256,
        "target inventory hash mismatch",
    )
    grouped_dirs = {str(PurePosixPath(item["path"]).parent) for item in targets}
    require(grouped_dirs == ALLOWED_BUNDLE_DIRS, "target bundle directory set mismatch")
    for directory in ALLOWED_BUNDLE_DIRS:
        group = target_group(targets, directory)
        require(
            tuple(PurePosixPath(item["path"]).name for item in group) == SHARD_NAMES,
            f"bundle shard names mismatch: {directory}",
        )

    snapshots: dict[str, dict[str, int]] = {}
    logical_bytes = 0
    allocated_bytes = 0
    seen_inodes: set[tuple[int, int]] = set()
    for index, item in enumerate(targets, start=1):
        relative = item["path"]
        require(
            SHARD_RE.fullmatch(PurePosixPath(relative).name) is not None,
            f"unsafe target basename: {relative}",
        )
        path = safe_path(root, relative)
        before = regular_single_link(path)
        require(before.st_size == item["bytes"], f"target size mismatch: {relative}")
        inode_key = (before.st_dev, before.st_ino)
        require(inode_key not in seen_inodes, f"duplicate target inode: {relative}")
        seen_inodes.add(inode_key)
        digest = sha256_file(path)
        after = regular_single_link(path)
        require(
            (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_nlink,
                before.st_blocks,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            == (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_nlink,
                after.st_blocks,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ),
            f"target changed during hash: {relative}",
        )
        require(digest == item["sha256"], f"target hash mismatch: {relative}")
        snapshots[relative] = {
            "device": before.st_dev,
            "inode": before.st_ino,
            "size": before.st_size,
            "blocks": before.st_blocks,
            "nlink": before.st_nlink,
            "mtime_ns": before.st_mtime_ns,
        }
        logical_bytes += before.st_size
        allocated_bytes += before.st_blocks * 512
        if index % 4 == 0:
            print(f"REVALIDATED {index}/{len(targets)} shards", file=sys.stderr, flush=True)
    require(logical_bytes == EXPECTED_LOGICAL_BYTES, "observed logical-byte mismatch")
    require(allocated_bytes == EXPECTED_ALLOCATED_BYTES, "observed allocated-byte mismatch")
    return snapshots, logical_bytes, allocated_bytes


def rename_noreplace(source: Path, destination: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    require(hasattr(libc, "renameat2"), "libc renameat2 is unavailable")
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


def same_inode_snapshot(info: os.stat_result, expected: dict[str, int]) -> bool:
    return (
        info.st_dev == expected["device"]
        and info.st_ino == expected["inode"]
        and info.st_size == expected["size"]
        and info.st_blocks == expected["blocks"]
        and info.st_nlink == expected["nlink"]
        and info.st_mtime_ns == expected["mtime_ns"]
    )


def rollback(
    root: Path, quarantine_payload: Path, moved: list[str], snapshots: dict[str, dict[str, int]]
) -> None:
    failures: list[str] = []
    for relative in reversed(moved):
        source = root / relative
        destination = quarantine_payload / relative
        try:
            require(
                not source.exists() and not source.is_symlink(),
                f"rollback source unexpectedly exists: {source}",
            )
            info = regular_single_link(destination)
            require(
                same_inode_snapshot(info, snapshots[relative]),
                f"rollback inode mismatch: {destination}",
            )
            source.parent.mkdir(parents=True, exist_ok=True)
            rename_noreplace(destination, source)
        except Exception as error:  # noqa: BLE001 - retain every rollback failure
            failures.append(f"{relative}: {error}")
    if failures:
        raise CleanupError("rollback failures: " + "; ".join(failures))


def remaining_safetensors(root: Path, quarantine_root: Path) -> dict[str, Any]:
    cache_root = root / "runs/v10/model_cache"
    records: list[dict[str, Any]] = []
    for path in sorted((root / "runs/v10").rglob("*.safetensors"), key=lambda item: str(item)):
        if quarantine_root in path.parents:
            continue
        info = os.lstat(path)
        relative = str(path.relative_to(root))
        if cache_root in path.parents:
            category = "protected_model_cache"
        else:
            category = "outside_model_cache"
        records.append(
            {
                "category": category,
                "path": relative,
                "kind": "symlink"
                if stat.S_ISLNK(info.st_mode)
                else "regular"
                if stat.S_ISREG(info.st_mode)
                else "other",
                "bytes": info.st_size,
            }
        )
    outside = [item for item in records if item["category"] == "outside_model_cache"]
    cache = [item for item in records if item["category"] == "protected_model_cache"]
    return {
        "outside_model_cache_file_count": len(outside),
        "protected_model_cache_named_safetensor_entry_count": len(cache),
        "protected_model_cache_named_safetensor_entries": cache,
        "all_records": records,
    }


def execute(root: Path, intent_path: Path, quarantine_root: Path) -> dict[str, Any]:
    started_utc = utc_now()
    require(root == root.resolve(), "root must be absolute and resolved")
    require(intent_path.is_file() and not intent_path.is_symlink(), "intent is not a plain file")
    require(sha256_file(intent_path) == EXPECTED_INTENT_SHA256, "intent file hash mismatch")
    intent = load_json(intent_path)
    require(
        intent.get("target_inventory_sha256") == EXPECTED_TARGET_INVENTORY_SHA256,
        "intent target hash field mismatch",
    )
    require(
        intent.get("scope", {}).get("target_file_count") == EXPECTED_TARGET_COUNT,
        "intent scope count mismatch",
    )

    quarantine_info = os.lstat(quarantine_root)
    require(stat.S_ISDIR(quarantine_info.st_mode), "quarantine root is not a plain directory")
    quarantine_intent = quarantine_root / "PRUNE_INTENT.json"
    require(
        quarantine_intent.is_file() and not quarantine_intent.is_symlink(),
        "quarantine intent copy missing",
    )
    require(
        sha256_file(quarantine_intent) == EXPECTED_INTENT_SHA256,
        "quarantine intent copy hash mismatch",
    )
    require(
        sorted(item.name for item in quarantine_root.iterdir()) == ["PRUNE_INTENT.json"],
        "quarantine root is not pristine",
    )
    require(
        root.stat().st_dev == quarantine_root.stat().st_dev,
        "quarantine is not on the worktree filesystem",
    )

    model_cache = root / "runs/v10/model_cache"
    cache_before = snapshot_tree_metadata(model_cache)
    evidence_before = verify_evidence(root, intent)
    snapshots, logical_bytes, allocated_bytes = validate_targets(root, intent)

    before_remaining = remaining_safetensors(root, quarantine_root)
    require(
        before_remaining["outside_model_cache_file_count"] == EXPECTED_TARGET_COUNT,
        "unclassified safetensors exist outside the protected model cache before cleanup",
    )
    require(
        {
            item["path"]
            for item in before_remaining["all_records"]
            if item["category"] == "outside_model_cache"
        }
        == {item["path"] for item in intent["targets"]},
        "outside-model-cache safetensor set is not the exact target set",
    )

    available_before = shutil.disk_usage(root).free
    payload = quarantine_root / "payload"
    payload.mkdir(mode=0o700, parents=False, exist_ok=False)
    moved: list[str] = []
    quarantine_verified_utc: str | None = None
    try:
        for item in intent["targets"]:
            relative = item["path"]
            source = root / relative
            destination = payload / relative
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            require(
                not destination.exists() and not destination.is_symlink(),
                f"quarantine destination exists: {destination}",
            )
            require(
                source.stat().st_dev == destination.parent.stat().st_dev,
                f"cross-filesystem target: {relative}",
            )
            rename_noreplace(source, destination)
            moved.append(relative)
            info = regular_single_link(destination)
            require(
                same_inode_snapshot(info, snapshots[relative]),
                f"inode identity changed during rename: {relative}",
            )

        for relative in moved:
            source = root / relative
            destination = payload / relative
            require(
                not source.exists() and not source.is_symlink(),
                f"source remains after rename: {relative}",
            )
            info = regular_single_link(destination)
            require(
                same_inode_snapshot(info, snapshots[relative]),
                f"quarantine target changed: {relative}",
            )

        quarantined_files = sorted(
            str(path.relative_to(payload))
            for path in payload.rglob("*")
            if stat.S_ISREG(os.lstat(path).st_mode)
        )
        require(quarantined_files == sorted(moved), "quarantine file manifest mismatch")
        require(
            verify_evidence(root, intent) == evidence_before,
            "evidence changed after quarantine rename",
        )
        require(
            snapshot_tree_metadata(model_cache) == cache_before,
            "protected model cache metadata changed",
        )
        quarantine_verified_utc = utc_now()
    except Exception:
        rollback(root, payload, moved, snapshots)
        raise

    available_after_quarantine = shutil.disk_usage(root).free

    # The destructive phase starts only after every destination was batch-validated.
    for relative in moved:
        destination = payload / relative
        info = regular_single_link(destination)
        require(
            same_inode_snapshot(info, snapshots[relative]), f"pre-unlink inode mismatch: {relative}"
        )
    for relative in moved:
        os.unlink(payload / relative)

    for relative in moved:
        require(
            not (root / relative).exists() and not (root / relative).is_symlink(),
            f"source reappeared: {relative}",
        )
        require(
            not (payload / relative).exists() and not (payload / relative).is_symlink(),
            f"quarantine target remains: {relative}",
        )
    require(
        not any(path.is_file() or path.is_symlink() for path in payload.rglob("*")),
        "files remain in quarantine payload",
    )
    require(verify_evidence(root, intent) == evidence_before, "evidence changed after unlink")
    require(
        snapshot_tree_metadata(model_cache) == cache_before,
        "protected model cache metadata changed after unlink",
    )

    after_remaining = remaining_safetensors(root, quarantine_root)
    require(
        after_remaining["outside_model_cache_file_count"] == 0,
        "trained safetensors remain outside protected model cache",
    )
    available_after_unlink = shutil.disk_usage(root).free

    return {
        "format": (
            "latent-workspace-v10-current-cuda-oracle-and-resume-raw-weight-"
            "prune-transaction-result-v1"
        ),
        "status": "verified_pruned",
        "completed": True,
        "started_utc": started_utc,
        "quarantine_verified_utc": quarantine_verified_utc,
        "completed_utc": utc_now(),
        "intent": {
            "path": str(intent_path.relative_to(root)),
            "sha256": EXPECTED_INTENT_SHA256,
            "quarantine_copy": str(quarantine_intent.relative_to(root)),
            "target_inventory_sha256": EXPECTED_TARGET_INVENTORY_SHA256,
        },
        "transaction": {
            "quarantine_root": str(quarantine_root.relative_to(root)),
            "payload_root": str(payload.relative_to(root)),
            "rename_method": "Linux renameat2(RENAME_NOREPLACE), same filesystem",
            "all_rename_inode_identities_preserved": True,
            "second_full_sha256_revalidation_before_rename": True,
            "quarantine_manifest_and_inode_identity_verified_before_unlink": True,
            "unlink_method": "os.unlink on each literal, intent-bound quarantined path",
            "deleted_file_count": len(moved),
            "deleted_logical_bytes": logical_bytes,
            "deleted_allocated_bytes": allocated_bytes,
            "no_directory_removal": True,
            "no_unlisted_file_removal": True,
            "payload_file_count_after": 0,
        },
        "storage": {
            "available_bytes_before_transaction": available_before,
            "available_bytes_after_quarantine_rename": available_after_quarantine,
            "available_bytes_after_unlink": available_after_unlink,
            "observed_unlink_free_delta_bytes": available_after_unlink - available_after_quarantine,
            "observed_net_transaction_free_delta_bytes": available_after_unlink - available_before,
            "expected_target_allocated_bytes": allocated_bytes,
            "observed_unlink_delta_matches_expected_target_allocation": available_after_unlink
            - available_after_quarantine
            == allocated_bytes,
        },
        "evidence": {
            "artifact_count": len(evidence_before),
            "all_hashes_and_semantic_predicates_reverified_before_and_after": True,
            "artifacts": [
                {"path": path, "sha256": digest} for path, digest in sorted(evidence_before.items())
            ],
            "failed_parity_attempts_have_no_weights_or_final": True,
            "formal_compact_exports_preserved": True,
        },
        "remaining_safetensors": after_remaining,
        "recoverability": {
            "loadable_trained_base_model_copy_remaining": False,
            "deleted_trained_weight_bodies": "not_recoverable_without_an_external_weight_backup",
            "hashes_and_receipts_are_a_backup": False,
            "formal_compact_exports": "evidence_only_not_loadable_base_weights",
            "protected_model_cache": (
                "pinned_upstream_initial_model_not_equivalent_to_deleted_trained_states"
            ),
            "resume_non_weight_state": (
                "retained_for_audit_but_deleted_checkpoints_are_not_loadable"
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--intent", required=True)
    parser.add_argument("--quarantine", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    intent_path = Path(args.intent).resolve()
    quarantine_root = Path(args.quarantine).resolve()
    result = execute(root, intent_path, quarantine_root)
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
