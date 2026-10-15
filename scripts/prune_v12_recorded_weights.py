#!/usr/bin/env python3
"""One-shot, explicitly authorized V12 weight deletion; not a retention policy.

Only the exact 90 paths in the pinned inventory are eligible. Metadata and all
other experiments are protected. Hashes are fingerprints, not weight backups.
The caller must ensure exclusive use; this is not an atomic filesystem snapshot.
No automatic retry/resume is provided after a partial destructive operation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

ROOT = Path(
    "/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/"
    "latent-workspace-ft-v12-calibrated-route/runs/v12/calibrated_route"
)
EVIDENCE = Path(
    "/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-v12-prune-record-20261014"
)
INVENTORY_SHA256 = "543743d61d97599d182db2c7d0af6a9d38d4473b7e96b0f664a8d457e80fefe3"
SIZE_INVENTORY = Path(
    "/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/"
    "latent-checkpoint-v2-20261014/WEIGHT_SIZE_INVENTORY.json"
)
TOTAL_BYTES = 222_055_662_879
WEIGHT_SUFFIXES = {".pt", ".pth", ".bin", ".safetensors"}
USER_AUTHORIZATION = "かなりあるね! まずV12は全部消して、これで進めようか!!"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def expected_paths():
    runs = [
        f"{stage}/{condition}_lr_1e_5_seed{seed}_step{step}/final"
        for stage, step in (("refinement16", 16), ("stage4", 4))
        for condition in ("semantic", "task")
        for seed in (43, 44, 45)
    ] + [f"step1/task_lr_{lr}_seed43_step1/final" for lr in ("1e_4", "1e_5", "3e_5")]
    names = ["trainer_state.pt", "workspace_state.pt"] + [
        f"base_model/model-{i:05d}-of-00004.safetensors" for i in range(1, 5)
    ]
    return {f"{run}/{name}" for run in runs for name in names}


def now():
    return datetime.now(UTC).isoformat()


def signature(s):
    return {
        "device": s.st_dev,
        "inode": s.st_ino,
        "size_bytes": s.st_size,
        "mtime_ns": s.st_mtime_ns,
        "ctime_ns": s.st_ctime_ns,
        "nlink": s.st_nlink,
        "mode": s.st_mode,
    }


@contextmanager
def parent_fd(root, relative):
    """Hold all no-follow directory descriptors through the final operation."""
    pure = PurePosixPath(relative)
    require(not pure.is_absolute() and bool(pure.parts), "relative path required")
    require(all(p not in ("", ".", "..") for p in pure.parts), "unsafe relative path")
    require(root.is_absolute() and root == root.resolve(strict=True), "unsafe root")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with ExitStack() as stack:
        fd = os.open(root.anchor, flags)
        stack.callback(os.close, fd)
        for part in (*root.parts[1:], *pure.parts[:-1]):
            fd = os.open(part, flags, dir_fd=fd)
            stack.callback(os.close, fd)
        yield fd, pure.name


def checked_stat(fd, name, entry):
    s = os.stat(name, dir_fd=fd, follow_symlinks=False)
    require(stat.S_ISREG(s.st_mode) and s.st_nlink == 1, "not a single-link regular file")
    actual = signature(s)
    require(all(actual[k] == entry[k] for k in actual if k in entry), f"changed: {name}")
    return actual


def checked_hash(fd, name, entry):
    before = checked_stat(fd, name, entry)
    source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
    with os.fdopen(source, "rb") as stream:
        require(signature(os.fstat(stream.fileno())) == before, "changed during open")
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        require(signature(os.fstat(stream.fileno())) == before, "changed during hash")
    require(digest == entry["sha256"], f"hash mismatch: {name}")
    require(checked_stat(fd, name, entry) == before, "changed after hash")
    return before


def durable_json(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def available():
    s = os.statvfs(ROOT)
    return s.f_bavail * s.f_frsize


def tree_files(root):
    result = {}
    for folder, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            p = Path(folder) / name
            s = p.lstat()
            # Directory mtimes can change when the eligible children are unlinked.
            if not stat.S_ISDIR(s.st_mode):
                result[p.relative_to(root).as_posix()] = signature(s)
    return result


def run(execute):
    inventory_path = EVIDENCE / "INVENTORY.json"
    raw = inventory_path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == INVENTORY_SHA256, "inventory seal changed")
    inv = json.loads(raw)
    require(inv["root"] == str(ROOT), "wrong root")
    require(inv["status"] == "COMPLETE_WITH_DECLARED_EXCLUSIONS", "incomplete inventory")
    require(not inv["errors"] and not inv["rejected_paths"], "inventory errors")
    require(inv["excluded_directories"] == ["model_cache"], "unexpected exclusion")
    weights = inv["weights"]
    require(len(weights) == 90, "wrong weight count")
    targets = {e["relative_path"] for e in weights}
    require(targets == expected_paths(), "wrong exact target set")
    require(sum(e["size_bytes"] for e in weights) == TOTAL_BYTES, "wrong total bytes")
    require(len(inv["metadata"]) == 315, "wrong metadata count")
    for e in inv["metadata"]:
        require(e["backup_status"] == "COPIED_AND_HASH_VERIFIED", "metadata not backed up")
        require(e["backup_relative_path"] == "metadata/" + e["relative_path"], "unsafe backup")
        with parent_fd(EVIDENCE, e["backup_relative_path"]) as (fd, name):
            checked_hash(fd, name, {"sha256": e["sha256"], "size_bytes": e["size_bytes"]})
        with parent_fd(ROOT, e["relative_path"]) as (fd, name):
            checked_hash(fd, name, e)

    before_tree = tree_files(ROOT)
    live_weights = {
        p
        for p in before_tree
        if Path(p).suffix in WEIGHT_SUFFIXES and not p.startswith("model_cache/")
    }
    require(live_weights == targets, "live weights differ from exact authorized set")
    protected_tree = {p: s for p, s in before_tree.items() if p not in targets}
    other = json.loads(SIZE_INVENTORY.read_bytes())
    protected_other = {}
    for e in other["weights"]:
        p = Path(e["path"])
        if ROOT in p.parents:
            continue
        s = signature(p.lstat())
        require(
            (s["size_bytes"], s["device"], s["inode"]) == (e["bytes"], e["device"], e["inode"]),
            "other experiment changed",
        )
        protected_other[str(p)] = s
    require(len(protected_other) == 138, "unexpected other-experiment count")

    # An all-target read-only validation precedes any deletion. No implicit
    # retry is possible once the exclusive DELETE_STARTED receipt exists.
    require(not (EVIDENCE / "DELETE_STARTED.json").exists(), "already started; inspect receipts")
    for i, e in enumerate(weights, 1):
        require(e["status"] == "STATIC_VERIFIED", "unverified target")
        with parent_fd(ROOT, e["relative_path"]) as (fd, name):
            checked_hash(fd, name, e)
        if i % 6 == 0:
            print(json.dumps({"validated_weights": i, "total": 90}), flush=True)
    start = {
        "format": "latent-v12-explicit-weight-prune-v1",
        "started_utc": now(),
        "root": str(ROOT),
        "inventory_sha256": INVENTORY_SHA256,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "authorization": USER_AUTHORIZATION,
        "target_count": 90,
        "target_logical_bytes": TOTAL_BYTES,
        "available_bytes_before": available(),
        "protected_source_entries": protected_tree,
        "protected_other_weights": protected_other,
        "metadata_backups": 315,
        "local_metadata_copy_verified_before_dispatch": True,
        "recoverability": "No weight backups. SHA256 is not reconstructible.",
        "exclusive_use_required": True,
        "global_transaction_atomic": False,
    }
    if not execute:
        print(
            json.dumps(
                {
                    "status": "DRY_RUN_PASS",
                    "target_count": 90,
                    "target_bytes": TOTAL_BYTES,
                    "deleted": 0,
                }
            )
        )
        return
    durable_json(EVIDENCE / "DELETE_STARTED.json", start)
    deleted = []
    try:
        with (EVIDENCE / "DELETIONS.jsonl").open("x") as log:
            for e in weights:
                with parent_fd(ROOT, e["relative_path"]) as (fd, name):
                    checked_stat(fd, name, e)
                    os.unlink(name, dir_fd=fd)
                    os.fsync(fd)
                record = {
                    "path": e["relative_path"],
                    "bytes": e["size_bytes"],
                    "sha256": e["sha256"],
                    "deleted_utc": now(),
                }
                deleted.append(record)
                log.write(json.dumps(record, sort_keys=True) + "\n")
                log.flush()
                os.fsync(log.fileno())
        require(tree_files(ROOT) == protected_tree, "protected source entries changed")
        require(
            {p: signature(Path(p).lstat()) for p in protected_other} == protected_other,
            "other experiment weights changed",
        )
        for e in inv["metadata"]:
            with parent_fd(ROOT, e["relative_path"]) as (fd, name):
                checked_hash(fd, name, e)
        durable_json(
            EVIDENCE / "DELETE_FINISHED.json",
            {
                "status": "COMPLETE",
                "finished_utc": now(),
                "deleted_count": len(deleted),
                "deleted_logical_bytes": sum(e["bytes"] for e in deleted),
                "available_bytes_before": start["available_bytes_before"],
                "available_bytes_after": available(),
                "metadata_hashes_preserved": 315,
                "other_experiment_weights_stat_unchanged": 138,
                "remaining_source_entries_stat_unchanged": len(protected_tree),
                "model_cache_untouched": True,
                "no_weight_backups": True,
                "inventory_sha256": INVENTORY_SHA256,
            },
        )
    except BaseException as exc:
        durable_json(
            EVIDENCE / "DELETE_FAILED.json",
            {
                "status": "PARTIAL_OR_POSTCHECK_FAILED",
                "utc": now(),
                "confirmed_deletions": len(deleted),
                "error": repr(exc),
                "automatic_retry_allowed": False,
            },
        )
        raise
    print((EVIDENCE / "DELETE_FINISHED.json").read_text())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-authorized-v12-deletion", action="store_true")
    run(parser.parse_args().execute_authorized_v12_deletion)
