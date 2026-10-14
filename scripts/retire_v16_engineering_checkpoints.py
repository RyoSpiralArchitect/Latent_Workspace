#!/usr/bin/env python3
"""Retire exactly four closed V16 engineering checkpoints after Git publication.

No model imports, tensor deserialization, recursive deletion, inferred retention,
or automatic retry. A receipt directory is exclusive even after failure. This
requires exclusive use; filesystem races/crash atomicity are not guaranteed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "scripts/retire_v16_engineering_checkpoints.py"
PUBLICATION = "provenance/inventory/v16_engineering_retirement_20261015"
REMOTE = "https://github.com/RyoSpiralArchitect/Latent_Workspace.git"
BRANCH = "SpiralReality/v18-operand-selection"
REMOTE_ROOT = Path("/home/ryospiralarchitect/spiralreality/SpiralReality")
MIGRATION = REMOTE_ROOT / "tmp/latent-v16-adapter-migration-20261014/checkpoints"
RECOVERY = REMOTE_ROOT / "tmp/latent-v16-adapter-recovery-02-20261014/checkpoints"
TARGETS = (
    (
        str(MIGRATION / "frozen_step1.pt"),
        50547559,
        "97b141c3bf66deea074facbad18d3a4c6631bf8957af8176442b1d352d39df7b",
    ),
    (
        str(MIGRATION / "frozen_step2.pt"),
        50547559,
        "8b82ce8e0f3cb34e4b51b5762a00831b2c10adc9755eb5fec1dfc7974a018573",
    ),
    (
        str(RECOVERY / "full_step1.pt"),
        29054823004,
        "42e40bf7a33bc62a351f80e873031d9f92ad86a191441a30b2d7a20da43344cc",
    ),
    (
        str(RECOVERY / "full_step2.pt"),
        29054823004,
        "5435c5fe12c3a91bc5ff67dda09d86a0f5a1a77b1e53dfe5b10cb8797c22e6cd",
    ),
)
MAIN = REMOTE_ROOT / "tmp/latent-v16-full-comparison-20261014/checkpoints"
PROTECTED = tuple(
    (str(MAIN / arm / f"step{step}.pt"), size)
    for arm, size in (
        ("common", 29054822748),
        ("raw_matched_control", 29083160804),
        ("slot_contrast", 29083160804),
    )
    for step in (1, 2)
)
BASE_SNAPSHOT = Path(
    "/home/ryospiralarchitect/.cache/huggingface/hub/"
    "models--mistralai--Mistral-7B-Instruct-v0.3/snapshots/"
    "c170c708c41dac9275d15a8fff4eca08d52bab71"
)
EVIDENCE = tuple(
    f"provenance/pilots/{bundle}/{name}"
    for bundle, role, versions in (
        ("v16_adapter_migration_20261014", "frozen", ("legacy", "adapter_v2")),
        ("v16_adapter_full_recovery_02_20261014", "full", ("adapter_v2",)),
    )
    for name in (
        "SOURCE_SEAL.json",
        "README.md",
        "OFFLINE_VERIFY.json",
        "raw/STARTED.json",
        "raw/FINISHED.json",
        f"raw/{role}_EQUIVALENCE.json",
        f"raw/{role}_REPLAY.json",
        f"raw/{role}_replay_step2.json",
        f"raw/{role}_replay_step2_pairs.jsonl",
        *(
            f"raw/{role}_{version}_{suffix}"
            for version in versions
            for suffix in (
                "CONTEXT.json",
                "INITIAL.json",
                "step1.json",
                "step2.json",
                "step1_pairs.jsonl",
                "step2_pairs.jsonl",
            )
        ),
        *(f"raw/{role}_adapter_v2_step{step}_CHECKPOINT.json" for step in (1, 2)),
    )
)


def require(value, message):
    if not value:
        raise ValueError(message)


def stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result

    def finite(text):
        value = float(text)
        require(math.isfinite(value), "Nonfinite JSON")
        return value

    return json.loads(
        Path(path).read_bytes(),
        object_pairs_hook=unique,
        parse_float=finite,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")),
    )


def write_new(path, value):
    with Path(path).open("xb") as stream:
        stream.write(encode(value))
        stream.flush()
        os.fsync(stream.fileno())


def signature(value):
    return {
        name: int(getattr(value, source))
        for name, source in (
            ("device", "st_dev"),
            ("inode", "st_ino"),
            ("mode", "st_mode"),
            ("nlink", "st_nlink"),
            ("size_bytes", "st_size"),
            ("mtime_ns", "st_mtime_ns"),
            ("ctime_ns", "st_ctime_ns"),
            ("allocated_blocks_512", "st_blocks"),
        )
    }


def regular(path, size=None):
    path = Path(path)
    require(path.is_absolute() and ".." not in path.parts, "Absolute nonescaping path required")
    for parent in path.parents:
        require(stat.S_ISDIR(parent.lstat().st_mode), "Symlink/non-directory ancestor")
    info = path.lstat()
    require(
        stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
        "Target must be a regular single-link file, not a symlink",
    )
    if size is not None:
        require(info.st_size == size, "Weight size differs from historical receipt")
    return signature(info)


def inspect_weight(path, size, expected_hash):
    """Internal helper accepts test fixtures; CLI targets are fixed constants."""
    before = regular(path, size)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        require(signature(os.fstat(stream.fileno())) == before, "File changed before hash")
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        require(signature(os.fstat(stream.fileno())) == before, "File changed while hashing")
    require(regular(path, size) == before, "File changed after hash")
    require(digest == expected_hash, "Weight SHA256 differs from historical receipt")
    return {"path": str(path), "sha256": digest, "stat": before}


def protected_state():
    weights = {path: regular(path, size) for path, size in PROTECTED}
    require(
        BASE_SNAPSHOT.is_dir() and not BASE_SNAPSHOT.is_symlink(),
        "Pinned original Mistral snapshot is absent/not a regular directory",
    )
    return {
        "current_v16_six": weights,
        "base_snapshot_path": str(BASE_SNAPSHOT),
        "base_snapshot_stat": signature(BASE_SNAPSHOT.stat()),
        "scope": "Six weight stat signatures and pinned snapshot existence, not content audit",
    }


def available_space(paths):
    result = {}
    for parent in sorted({str(Path(path).parent) for path in paths}):
        info = os.statvfs(parent)
        result[parent] = {
            "available_bytes": info.f_bavail * info.f_frsize,
            "fragment_size": info.f_frsize,
            "time": stamp(),
        }
    return result


def visible_handles(paths):
    """Same-user visible handles only; privileged service visibility is UNKNOWN."""
    require(Path("/proc").is_dir(), "Linux /proc handle screen required")
    lsof = shutil.which("lsof")
    require(lsof is not None, "lsof is required; no unchecked deletion")
    result = subprocess.run(
        [lsof, "-nP", "-Fpn", "--", *paths], text=True, capture_output=True, check=False, timeout=60
    )
    require(
        result.returncode == 1 and not result.stdout.strip() and not result.stderr.strip(),
        "Open target handle or incomplete lsof screen",
    )
    unknown = screen_processes(paths, Path("/proc"))
    return {
        "lsof_returncode": 1,
        "visible_open_targets": [],
        "visible_target_commands": [],
        "service_visibility_unknown": unknown,
        "scope": "Visible handles only; not proof of global closedness or concurrency safety",
    }


def screen_processes(paths, proc):
    """Internal fixture-testable same-user screen; never treats UNKNOWN as absent."""
    unknown = []
    command_markers = tuple({*paths, *(str(Path(p).parent.parent) for p in paths)})
    for process in proc.iterdir():
        if not process.name.isdigit() or int(process.name) == os.getpid():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            command = (
                (process / "cmdline")
                .read_bytes()
                .replace(b"\0", b" ")
                .decode("utf-8", errors="replace")
            )
            require(
                not any(marker in command for marker in command_markers),
                "Visible process command references a retired target/run",
            )
            for fd in (process / "fd").iterdir():
                try:
                    target = os.readlink(fd)
                except FileNotFoundError:
                    continue
                require(
                    target.removesuffix(" (deleted)") not in paths, "Visible active target handle"
                )
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError:
            try:
                comm = (process / "comm").read_text().strip()
            except (FileNotFoundError, ProcessLookupError):
                continue
            require(
                comm in {"systemd", "(sd-pam)", "sshd-session"} or comm.startswith("smbd["),
                "Unreadable non-service process; handle status unknown",
            )
            unknown.append({"pid": int(process.name), "comm": comm, "target_handles": "UNKNOWN"})
    return unknown


def plan():
    evidence = {}
    for name in EVIDENCE:
        regular(ROOT / name)
        evidence[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    return {
        "schema": "v16-closed-engineering-retirement-v1",
        "remote": REMOTE,
        "branch": BRANCH,
        "publication": PUBLICATION,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "targets": [{"path": p, "bytes": size, "sha256": sha} for p, size, sha in TARGETS],
        "total_bytes": 58210741126,
        "protected_current_v16": [p for p, _ in PROTECTED],
        "protected_base_snapshot": str(BASE_SNAPSHOT),
        "historical_evidence_sha256": evidence,
        "rationale": (
            "Retire completed engineering qualification roles, "
            "not duplicate-weight or latest-two rotation"
        ),
        "latest_two_per_scientific_condition": "UNCHANGED",
        "weights_reconstructible_from_hashes": False,
        "old_gate": "FAIL",
        "winner": "none",
        "non_regression": "NOT_ESTABLISHED",
    }


def output_directory(path):
    path = Path(path)
    require(path.is_absolute() and ".." not in path.parts, "Absolute external output required")
    for ancestor in path.parents:
        if ancestor.exists() or ancestor.is_symlink():
            require(stat.S_ISDIR(ancestor.lstat().st_mode), "Symlink/non-directory output ancestor")
    forbidden = (
        ROOT,
        BASE_SNAPSHOT,
        *(Path(p).parent for p, _, _ in TARGETS),
        *(Path(p).parent for p, _ in PROTECTED),
    )
    require(
        not any(path.resolve().is_relative_to(root.resolve()) for root in forbidden),
        "Receipts must be external to source and protected/target directories",
    )
    path.mkdir(parents=True, exist_ok=False)
    return path


def inventory(output):
    output = output_directory(output)
    write_new(output / "STARTED.json", {"mode": "inventory", "time": stamp(), "pid": os.getpid()})
    try:
        write_new(output / "PLAN.json", plan())
        space_before = available_space([p for p, _, _ in TARGETS])
        handles_before = visible_handles([p for p, _, _ in TARGETS])
        protected = protected_state()
        records = []
        for index, target in enumerate(TARGETS, 1):
            print(f"Hashing inventory {index}/4: {target[0]}", flush=True)
            records.append(inspect_weight(*target))
            print(f"Verified inventory {index}/4", flush=True)
        handles_after = visible_handles([p for p, _, _ in TARGETS])
        require(protected_state() == protected, "Protected metadata changed during inventory")
        write_new(
            output / "INVENTORY.json",
            {
                "schema": "v16-retirement-inventory-v1",
                "time": stamp(),
                "weights": records,
                "protected": protected,
                "handles_before": handles_before,
                "handles_after": handles_after,
                "deletion_performed": False,
                "space_before": space_before,
                "space_after": available_space([p for p, _, _ in TARGETS]),
                "allocated_bytes": sum(r["stat"]["allocated_blocks_512"] * 512 for r in records),
                "plan_sha256": hashlib.sha256((output / "PLAN.json").read_bytes()).hexdigest(),
            },
        )
        write_new(
            output / "FINISHED.json", {"status": "INVENTORY_COMPLETE", "files": 4, "time": stamp()}
        )
    except BaseException as error:
        write_new(
            output / "FINISHED.json",
            {"status": "FAILED_NO_DELETION", "error": str(error), "time": stamp()},
        )
        raise


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], timeout=60)


def published_ledger(ledger, commit):
    require(re.fullmatch(r"[0-9a-f]{40}", commit) is not None, "Exact ledger commit required")
    require(
        git("rev-parse", "HEAD").decode().strip() == commit,
        "Execution HEAD differs from ledger commit",
    )
    require(git("remote", "get-url", "origin").decode().strip() == REMOTE, "Unexpected origin URL")
    ref = f"refs/heads/{BRANCH}"
    advertised = git("ls-remote", "--exit-code", "origin", ref).decode().strip()
    require(advertised == f"{commit}\t{ref}", "Ledger commit is not exact published branch HEAD")
    for name, local in (
        (ENTRY, Path(__file__)),
        (f"{PUBLICATION}/PLAN.json", Path(ledger) / "PLAN.json"),
        (f"{PUBLICATION}/INVENTORY.json", Path(ledger) / "INVENTORY.json"),
        *((name, ROOT / name) for name in EVIDENCE),
    ):
        regular(local)
        require(
            git("show", f"{commit}:{name}") == local.read_bytes(),
            "Committed ledger/source bytes differ",
        )
    require(
        read_json(Path(ledger) / "PLAN.json") == plan(),
        "Plan differs from exact fixed retirement scope",
    )
    observed = read_json(Path(ledger) / "INVENTORY.json")
    require(
        observed["schema"] == "v16-retirement-inventory-v1"
        and observed["deletion_performed"] is False,
        "Invalid inventory schema/status",
    )
    require(
        observed["plan_sha256"]
        == hashlib.sha256((Path(ledger) / "PLAN.json").read_bytes()).hexdigest(),
        "Inventory plan hash mismatch",
    )
    return observed, {"commit": commit, "remote": REMOTE, "ref": ref, "advertised": advertised}


def preflight(records, targets, handle_screen):
    """Validate ALL target content before the first deletion; fixture-testable."""
    require(len(records) == len(targets), "Inventory target denominator differs")
    require(
        [r["path"] for r in records] == [p for p, _, _ in targets],
        "Inventory path allowlist differs",
    )
    for index, (recorded, target) in enumerate(zip(records, targets), 1):
        print(f"Hashing predelete {index}/{len(targets)}: {target[0]}", flush=True)
        require(inspect_weight(*target) == recorded, "Live weight differs from inventory")
        print(f"Verified predelete {index}/{len(targets)}", flush=True)
    return handle_screen([p for p, _, _ in targets])


def unlink_recorded(records, journal):
    """Internal exact-file helper; callers must finish the all-target preflight."""
    for index, record in enumerate(records):
        path = Path(record["path"])
        require(regular(path) == record["stat"], "Target changed immediately before unlink")
        for event in ("UNLINK_INTENT", "UNLINK_CONFIRMED"):
            if event == "UNLINK_CONFIRMED":
                require(regular(path) == record["stat"], "Target changed after unlink intent")
                path.unlink()
                require(
                    not path.exists() and not path.is_symlink(),
                    "Unlink did not remove exact target",
                )
            journal.write(
                json.dumps(
                    {
                        "event": event,
                        "index": index,
                        "path": str(path),
                        "sha256": record["sha256"],
                        "bytes": record["stat"]["size_bytes"],
                        "time": stamp(),
                    },
                    sort_keys=True,
                )
                + "\n"
            )
            journal.flush()
            os.fsync(journal.fileno())


def delete(ledger, output, commit):
    output = output_directory(output)
    write_new(
        output / "DELETE_STARTED.json",
        {"time": stamp(), "pid": os.getpid(), "ledger_commit": commit},
    )
    try:
        observed, publication = published_ledger(ledger, commit)
        require(
            protected_state() == observed["protected"], "Protected metadata differs before deletion"
        )
        handles = preflight(observed["weights"], TARGETS, visible_handles)
        space_before = available_space([p for p, _, _ in TARGETS])
        write_new(
            output / "PREDELETE.json",
            {
                "publication": publication,
                "handles": handles,
                "all_four_hashes_verified": True,
                "protected": observed["protected"],
                "script_sha256": plan()["script_sha256"],
                "space_before": space_before,
            },
        )
        with (output / "DELETIONS.jsonl").open("x") as journal:
            unlink_recorded(observed["weights"], journal)
        require(
            protected_state() == observed["protected"], "Protected metadata differs after deletion"
        )
        write_new(
            output / "DELETE_FINISHED.json",
            {
                "status": "COMPLETE",
                "deleted": 4,
                "logical_bytes": 58210741126,
                "protected_unchanged": True,
                "time": stamp(),
                "allocated_bytes": observed["allocated_bytes"],
                "space_before": space_before,
                "space_after": available_space([p for p, _, _ in TARGETS]),
                "space_change_caveat": (
                    "Filesystem-wide observation; other processes may change free space"
                ),
                "recoverability": (
                    "No weight backups; hashes and metadata cannot reconstruct weights"
                ),
            },
        )
    except BaseException as error:
        write_new(
            output / "DELETE_FINISHED.json",
            {
                "status": "FAILED_OR_PARTIAL_NO_RETRY",
                "error": str(error),
                "time": stamp(),
                "target_presence": {p: os.path.lexists(p) for p, _, _ in TARGETS},
                "instruction": (
                    "Preserve journal; no automatic rerun or inferred successful deletion"
                ),
            },
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("inventory", "delete"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--ledger-commit")
    args = parser.parse_args()
    if args.mode == "inventory":
        require(
            args.ledger is None and args.ledger_commit is None, "Inventory takes no deletion ledger"
        )
        inventory(args.output)
    else:
        require(
            args.ledger is not None and args.ledger_commit is not None,
            "Delete requires ledger and published commit",
        )
        delete(args.ledger, args.output, args.ledger_commit)


if __name__ == "__main__":
    main()
