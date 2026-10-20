#!/usr/bin/env python3
"""One explicitly authorized file only; no recursive operation and no retry."""

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import stat
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEDGER_SHA256 = "9f852ff658ade6a594ec6c7dd3f59930e53ae5b31ef9b172c825a120b83cf08f"
TARGET = Path(
    "/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v22-full-ft01-20261021/checkpoints/canary_step1.pt"
)
NEW_BUNDLE = Path(
    "/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v22-full-ft-recovery01-20261021"
)


def require(ok, why):
    if not ok:
        raise ValueError(why)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def write_new(path, record):
    with path.open("x") as stream:
        json.dump(record, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def metadata(path, expected):
    require(str(path) == expected["path"] and path.resolve() == path, "Exact canonical target")
    require(not any(p.is_symlink() for p in [path, *path.parents]), "No symlink component")
    s = path.lstat()
    require(stat.S_ISREG(s.st_mode) and s.st_nlink == expected["links"] == 1, "One regular body")
    require(s.st_size == expected["bytes"] and s.st_ino == expected["inode"], "Size/inode")
    require(s.st_mtime_ns == int(expected["mtime_ns_exact"]), "Weight body changed")
    return s


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", required=True)
    parser.add_argument("--published-ledger-commit", required=True)
    args = parser.parse_args()
    require(re.fullmatch("[0-9a-f]{40}", args.published_ledger_commit), "Published Git commit")
    require(digest(HERE / "INVENTORY.json") == LEDGER_SHA256, "Pinned approval ledger")
    ledger = read(HERE / "INVENTORY.json")
    require(not (HERE / "DELETE_STARTED.json").exists(), "Operation already attempted")
    require(not (HERE / "DELETE_FINISHED.json").exists(), "Operation already terminal")
    phase = NEW_BUNDLE / "checks/FINISHED.json"
    require(digest(phase) == ledger["gate"]["checks_finished_sha256"], "New phase receipt")
    end = read(phase)
    require(end["status"] == ledger["gate"]["status"], "New replay did not pass")
    require(
        read(NEW_BUNDLE / "SOURCE_SEAL.json")["source_commit"]
        == ledger["replacement"]["execution_source_commit"],
        "New execution source",
    )
    for role in ("canary", "replay"):
        root = NEW_BUNDLE / "raw" / role
        files = {
            p.relative_to(root).as_posix(): dict(bytes=p.stat().st_size, sha256=digest(p))
            for p in root.rglob("*")
            if p.is_file()
        }
        require(files == end["role_manifests"][role], "Qualified role changed")
    replay = read(NEW_BUNDLE / "raw/replay/REPLAY.json")
    require(
        replay["exact"] is True
        and replay["state_sha256"] == ledger["gate"]["replay_payload_sha256"],
        "Exact payload replay",
    )
    retained = NEW_BUNDLE / "checkpoints/canary_step1.pt"
    metadata(retained, ledger["replacement"])
    old = metadata(TARGET, ledger["target"])
    before = shutil.disk_usage(NEW_BUNDLE).free
    with os.fdopen(os.open(TARGET, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        require(
            hashlib.file_digest(stream, "sha256").hexdigest() == ledger["target"]["sha256"],
            "Final old-body hash",
        )
        current = metadata(TARGET, ledger["target"])
        held = os.fstat(stream.fileno())
        require(
            (held.st_dev, held.st_ino, held.st_size, held.st_mtime_ns)
            == (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns),
            "Target changed while hashing",
        )
        require(current.st_ino == old.st_ino, "Original inode")
        metadata(retained, ledger["replacement"])
        started = dict(
            status="DELETE_STARTED",
            target=ledger["target"],
            retained=ledger["replacement"],
            ledger_sha256=LEDGER_SHA256,
            published_ledger_commit=args.published_ledger_commit,
            script_sha256=digest(Path(__file__)),
            checks_sha256=digest(phase),
            utc=datetime.datetime.now(datetime.UTC).isoformat(),
            available_before_bytes=before,
        )
        write_new(HERE / "DELETE_STARTED.json", started)
        # Exactly one stat/hash-validated file. No parent directory is removed.
        TARGET.unlink()
    require(not TARGET.exists() and retained.is_file(), "Expected one-file retirement")
    finished = dict(
        status="RETIRED_ONE_APPROVED_OLD_CANARY",
        files_deleted=1,
        bytes_deleted=old.st_size,
        target=str(TARGET),
        retained=str(retained),
        sha256=ledger["target"]["sha256"],
        published_ledger_commit=args.published_ledger_commit,
        available_before_bytes=before,
        available_after_bytes=shutil.disk_usage(NEW_BUNDLE).free,
        finished_utc=datetime.datetime.now(datetime.UTC).isoformat(),
        recoverability=(
            "Old body not backed up; Git retains metadata, not reconstructable weight bytes."
        ),
    )
    write_new(HERE / "DELETE_FINISHED.json", finished)
    print(json.dumps(finished, sort_keys=True))


if __name__ == "__main__":
    main()
