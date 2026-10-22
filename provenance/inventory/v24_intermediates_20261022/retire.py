"""Explicitly authorized two-file intermediate retirement, never final weights.

Inventory -> publish ledger -> execute once. Tensor bodies have NO Git backup.
No recursive operation, wildcard, model load, retry or historical receipt edit.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

ROOT = Path("/home/ryospiralarchitect/spiralreality/SpiralReality")
V22 = ROOT / "latent-v22-full-ft-recovery01-20261021"
V23 = ROOT / "latent-v23-preservation-ft01-20261022"
TARGETS = [
    (
        V23 / "checkpoints/canary_step1.pt",
        29004386444,
        "481267fc217d034e908707d501546cd7f1107225c9fac24d937d62e39498b8a7",
        V23 / "raw/canary/CHECKPOINT_canary_step1.pt.json",
    ),
    (
        V22 / "checkpoints/training_step16.pt",
        29004396428,
        "49a5e6721963c3581a5c471556d1196f329c12868d496148066d65aa21386de2",
        V22 / "raw/train_a/CHECKPOINT_training_step16.pt.json",
    ),
]
KEPT = [
    (V22 / "checkpoints/training_step32.pt", 29004418636),
    (V23 / "checkpoints/off_step32.pt", 29004418636),
    (V23 / "checkpoints/on_step32.pt", 29004428108),
]
EVIDENCE = [
    V22 / "SOURCE_SEAL.json",
    V23 / "SOURCE_SEAL.json",
    V23 / "raw/replay/REPLAY.json",
    V23 / "raw/replay/FINISHED.json",
    V22 / "raw/train_b/RESTORE.json",
    V22 / "raw/train_b/FINISHED.json",
    V23 / "raw/off/FINISHED.json",
    V23 / "raw/on/FINISHED.json",
    *(t[3] for t in TARGETS),
]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text())


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def identity(path, size):
    require(path.is_absolute() and path.resolve() == path, "Canonical absolute path")
    require(not any(p.is_symlink() for p in (path, *path.parents)), "No symlinks")
    info = path.lstat()
    require(
        stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size == size,
        "One-link regular body of exact size",
    )
    return dict(
        path=str(path),
        bytes=info.st_size,
        inode=info.st_ino,
        device=info.st_dev,
        mtime_ns=str(info.st_mtime_ns),
        ctime_ns=str(info.st_ctime_ns),
        links=info.st_nlink,
    )


def unused():
    paths = [str(t[0]) for t in TARGETS]
    require(all(p.startswith("/") for p in paths), "Absolute fuser operands only")
    # PSmisc 23.7 treats `--` as an empty process specification, not getopt's
    # end-of-options marker. Absolute operands cannot be interpreted as flags.
    result = subprocess.run(["fuser", *paths], capture_output=True, text=True, check=False)
    require(
        result.returncode == 1 and not result.stdout.strip() and not result.stderr.strip(),
        "Target in use or open-file check failed",
    )


def gates():
    require(
        read(V23 / "SOURCE_SEAL.json")["source_commit"]
        == "b46f04caefcfd596ccde3b0af8fd886d859f11b7",
        "V23 source",
    )
    require(
        read(V22 / "SOURCE_SEAL.json")["source_commit"]
        == "13c1192fc2727d8ca61ee215a927c0cd77f75b16",
        "V22 source",
    )
    require(read(V23 / "raw/replay/REPLAY.json")["exact"] is True, "Exact canary replay")
    require(
        read(V23 / "raw/replay/FINISHED.json")["status"] == "V23_PRESERVATION_REPLAY_COMPLETE",
        "Completed canary replay",
    )
    restore = read(V22 / "raw/train_b/RESTORE.json")
    require(
        restore["exact"] is True and restore["checkpoint"] == read(TARGETS[1][3]),
        "Exact continuation from intermediate checkpoint",
    )
    require(
        read(V22 / "raw/train_b/FINISHED.json")["status"] == "V22_TRAINING_STEP32_SAVED",
        "Later V22 final completed",
    )
    for arm in ("off", "on"):
        require(
            read(V23 / f"raw/{arm}/FINISHED.json")["status"]
            == f"V23_PRESERVATION_{arm.upper()}_COMPLETE",
            "V23 final completed",
        )
    return [identity(p, n) for p, n in KEPT]


def inventory(output):
    output.mkdir(exist_ok=False)
    kept = gates()
    unused()
    entries = []
    for path, size, expected, receipt in TARGETS:
        before = identity(path, size)
        require(digest(path) == expected, "Full checkpoint hash")
        require(identity(path, size) == before, "Static checkpoint body")
        saved = read(receipt)
        require(saved["sha256"] == expected and saved["bytes"] == size, "Original receipt")
        entries.append(
            dict(
                **before,
                sha256=expected,
                checkpoint_receipt=saved,
                receipt_path=str(receipt),
                receipt_sha256=digest(receipt),
            )
        )
    ledger = dict(
        schema="ltws-two-superseded-intermediates-v1",
        targets=entries,
        retained=kept,
        evidence={str(p): digest(p) for p in EVIDENCE},
        script_sha256=digest(Path(__file__)),
        total_bytes=sum(t[1] for t in TARGETS),
        available_before_bytes=shutil.disk_usage(ROOT).free,
        utc=datetime.datetime.now(datetime.UTC).isoformat(),
        reason=(
            "Exact canary replay and V22 step16-to-step32 continuation completed. "
            "Current comparisons use only scientific final weights."
        ),
        recoverability=(
            "No tensor backup in Git; only metadata and receipts remain. "
            "Deleted bodies cannot be restored from Git."
        ),
        protected=(
            "Original Mistral; V22 step32; V23 off/on step32; "
            "all other weights, activations, datasets and projects."
        ),
    )
    write(output / "INVENTORY.json", ledger)
    print(json.dumps(ledger), flush=True)


def execute(output, ledger_sha, published_commit):
    require(re.fullmatch(r"[0-9a-f]{40}", published_commit or ""), "Published ledger commit")
    require(digest(output / "INVENTORY.json") == ledger_sha, "Published ledger hash")
    ledger = read(output / "INVENTORY.json")
    require(digest(Path(__file__)) == ledger["script_sha256"], "Published script hash")
    require(len(ledger["targets"]) == len(TARGETS) == 2, "Exactly two intermediate files")
    require(not (output / "DELETE_STARTED.json").exists(), "No repeated deletion attempt")
    require(gates() == ledger["retained"], "Retained scientific finals stable")
    for path, sha in ledger["evidence"].items():
        require(digest(Path(path)) == sha, "Historical evidence remains unchanged")
    unused()
    for saved, (path, size, sha, _) in zip(ledger["targets"], TARGETS, strict=True):
        observed = identity(path, size)
        require(
            {k: saved[k] for k in observed} == observed and saved["sha256"] == sha,
            "Exact static allowlist",
        )
        require(digest(path) == sha, "Final full-body hash")
    before = shutil.disk_usage(ROOT).free
    write(
        output / "DELETE_STARTED.json",
        dict(
            ledger_sha256=ledger_sha,
            published_commit=published_commit,
            targets=ledger["targets"],
            utc=datetime.datetime.now(datetime.UTC).isoformat(),
        ),
    )
    unused()
    for index, (saved, (path, size, _, _)) in enumerate(
        zip(ledger["targets"], TARGETS, strict=True)
    ):
        observed = identity(path, size)
        require({k: saved[k] for k in observed} == observed, "Immediate pre-unlink identity")
        path.unlink()
        write(output / f"DELETED_{index}.json", dict(path=str(path), sha256=saved["sha256"]))
    require(gates() == ledger["retained"], "Retained scientific finals unchanged")
    write(
        output / "DELETE_FINISHED.json",
        dict(
            status="RETIRED_TWO_SUPERSEDED_INTERMEDIATES",
            files_deleted=2,
            bytes_deleted=ledger["total_bytes"],
            available_before_bytes=before,
            available_after_bytes=shutil.disk_usage(ROOT).free,
            published_commit=published_commit,
            recoverability=ledger["recoverability"],
            utc=datetime.datetime.now(datetime.UTC).isoformat(),
        ),
    )
    print(json.dumps(read(output / "DELETE_FINISHED.json")), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("inventory", "execute"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ledger-sha256")
    parser.add_argument("--published-commit")
    args = parser.parse_args()
    require(args.output.is_absolute() and args.output.resolve() == args.output, "Explicit output")
    if args.mode == "inventory":
        inventory(args.output)
    else:
        execute(args.output, args.ledger_sha256, args.published_commit)
