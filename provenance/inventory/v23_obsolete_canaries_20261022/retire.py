"""Retire exactly three completed engineering canaries; never scientific weights.

Inventory first, publish it, then execute with its exact digest and commit.
Fingerprints/receipts are NOT a backup. All original evidence directories stay.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import stat
from pathlib import Path

ROOT = Path("/home/ryospiralarchitect/spiralreality/SpiralReality")
OLD = ROOT / "tmp/latent-native-7b-identity-recovery01-20261020"
V22 = ROOT / "latent-v22-full-ft-recovery01-20261021"
TARGETS = [
    (
        OLD / "checkpoints/step1.pt",
        29004378188,
        "cd084da7c6f08dfd275a7f34e8c735f96bb0481de1b5696acc9fd22616a5a331",
        OLD / "raw/primary/CHECKPOINT_step1.json",
    ),
    (
        OLD / "checkpoints/step2.pt",
        29004378252,
        "1b0e5bfabef997d89775474b7ad43b897b13259692e02fa1b4ad8ce8e10ff5be",
        OLD / "raw/primary/CHECKPOINT_step2.json",
    ),
    (
        V22 / "checkpoints/canary_step1.pt",
        29004378380,
        "795b96b53811f5b886f071f72203d01db4afe79489b724e481c10549d88d86e6",
        V22 / "raw/canary/CHECKPOINT_canary_step1.pt.json",
    ),
]
KEPT = [
    (V22 / "checkpoints/training_step16.pt", 29004396428),
    (V22 / "checkpoints/training_step32.pt", 29004418636),
]


def require(ok, why):
    if not ok:
        raise ValueError(why)


def read(path):
    return json.loads(path.read_text())


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def write(path, value):
    with path.open("x") as f:
        json.dump(value, f, indent=2, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())


def identity(path, size):
    require(path.is_absolute() and path.resolve() == path, "Canonical path")
    require(not any(p.is_symlink() for p in (path, *path.parents)), "No symlinks")
    s = path.lstat()
    require(
        stat.S_ISREG(s.st_mode) and s.st_nlink == 1 and s.st_size == size, "Regular one-link body"
    )
    return dict(
        path=str(path),
        bytes=s.st_size,
        inode=s.st_ino,
        device=s.st_dev,
        mtime_ns=str(s.st_mtime_ns),
        ctime_ns=str(s.st_ctime_ns),
        links=s.st_nlink,
    )


def gates():
    for root in (OLD, V22):
        require(read(root / "raw/replay/REPLAY.json")["exact"] is True, "Completed exact replay")
    require(
        read(V22 / "training/FINISHED.json")["status"]
        == "V22_NATIVE_TRAINING_32_STEPS_COMPLETE_NOT_QUALITY",
        "V22 training completed",
    )
    return [identity(p, n) for p, n in KEPT]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["inventory", "execute"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ledger-sha256")
    parser.add_argument("--published-commit")
    args = parser.parse_args()
    require(args.output.is_absolute(), "Explicit evidence destination")
    if args.mode == "inventory":
        args.output.mkdir(exist_ok=False)
        kept = gates()
        entries = []
        for path, size, expected, receipt in TARGETS:
            print(f"hashing {path}", flush=True)
            before = identity(path, size)
            require(digest(path) == expected, "Recorded checkpoint full SHA256")
            require(identity(path, size) == before, "Static body")
            checkpoint = read(receipt)
            require(
                checkpoint["sha256"] == expected and checkpoint["bytes"] == size,
                "Checkpoint receipt",
            )
            entries.append(
                dict(
                    **before,
                    sha256=expected,
                    checkpoint_receipt=checkpoint,
                    receipt_path=str(receipt),
                    receipt_sha256=digest(receipt),
                )
            )
        evidence = {}
        for root in (OLD, V22):
            for rel in ("SOURCE_SEAL.json", "raw/replay/REPLAY.json", "raw/replay/FINISHED.json"):
                p = root / rel
                evidence[str(p)] = dict(sha256=digest(p), bytes=p.stat().st_size)
        write(
            args.output / "INVENTORY.json",
            dict(
                schema="ltws-three-obsolete-canaries-v1",
                targets=entries,
                retained=kept,
                evidence=evidence,
                total_bytes=sum(e["bytes"] for e in entries),
                reason=(
                    "Completed engineering replay only; superseded by successful V22 replay and "
                    "scientific step16/32. No future comparison consumes these canaries."
                ),
                excluded=(
                    "Base Mistral, V22 step16/32, all scientific V18-V20 branches, "
                    "activation banks, data and every other project."
                ),
                recoverability=(
                    "No weight backup. Git preserves metadata/hashes, not recoverable tensor bytes."
                ),
                utc=datetime.datetime.now(datetime.UTC).isoformat(),
                available_before_bytes=shutil.disk_usage(ROOT).free,
            ),
        )
        return
    require(re.fullmatch(r"[0-9a-f]{40}", args.published_commit or ""), "Published commit")
    ledger_path = args.output / "INVENTORY.json"
    require(digest(ledger_path) == args.ledger_sha256, "Pinned published ledger")
    ledger = read(ledger_path)
    require(len(ledger["targets"]) == len(TARGETS) == 3, "Exactly three targets")
    require(not (args.output / "DELETE_STARTED.json").exists(), "No repeat attempt")
    require(gates() == ledger["retained"], "Retained files stable")
    for path, info in ledger["evidence"].items():
        require(digest(Path(path)) == info["sha256"], "Historical evidence unchanged")
    # Validate every body before deleting any. Revalidate identity immediately before unlink.
    for expected, (path, size, sha, _) in zip(ledger["targets"], TARGETS, strict=True):
        require(
            {k: expected[k] for k in identity(path, size)} == identity(path, size), "Static target"
        )
        require(expected["path"] == str(path) and expected["sha256"] == sha, "Exact allowlist")
        require(digest(path) == sha, "Final full SHA256")
    before = shutil.disk_usage(ROOT).free
    write(
        args.output / "DELETE_STARTED.json",
        dict(
            ledger_sha256=args.ledger_sha256,
            published_commit=args.published_commit,
            script_sha256=digest(Path(__file__)),
            targets=ledger["targets"],
            utc=datetime.datetime.now(datetime.UTC).isoformat(),
        ),
    )
    for index, (expected, (path, size, _, _)) in enumerate(
        zip(ledger["targets"], TARGETS, strict=True)
    ):
        require(
            {k: expected[k] for k in identity(path, size)} == identity(path, size),
            "Pre-unlink identity",
        )
        path.unlink()  # One explicit validated file; no parent directory operation.
        write(
            args.output / f"DELETED_{index}.json", dict(path=str(path), sha256=expected["sha256"])
        )
    require(gates() == ledger["retained"], "Retained weights unchanged")
    write(
        args.output / "DELETE_FINISHED.json",
        dict(
            status="RETIRED_THREE_OBSOLETE_ENGINEERING_CANARIES",
            files_deleted=3,
            bytes_deleted=ledger["total_bytes"],
            available_before_bytes=before,
            available_after_bytes=shutil.disk_usage(ROOT).free,
            utc=datetime.datetime.now(datetime.UTC).isoformat(),
            recoverability=ledger["recoverability"],
            published_commit=args.published_commit,
        ),
    )
    print(json.dumps(read(args.output / "DELETE_FINISHED.json")), flush=True)


if __name__ == "__main__":
    main()
