#!/usr/bin/env python3
"""Record, publish, then unlink exactly 44 explicitly authorized V14 weights.

No tensor deserialization, recursive deletion, retention-policy inference or
automatic retry. Metadata is copied byte-for-byte and must be in the supplied
Git commit before deletion. Hashes cannot reconstruct deleted weights.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
from pathlib import Path

HELPER_SHA256 = "d268cc14ce0fcd2e569d63ad31ee6b2fff0578f2cb36c36f89a19427028dcda4"
helper_path = Path(__file__).with_name("prune_v12_recorded_weights.py")
if hashlib.sha256(helper_path.read_bytes()).hexdigest() != HELPER_SHA256:
    raise ValueError("historical filesystem helper changed")
spec = importlib.util.spec_from_file_location("v12_prune_helpers", helper_path)
fs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fs)

WORKTREES = Path("/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees")
REPO = WORKTREES / "latent-workspace-ft-v14-semantic-chat"
ROOT = REPO / "runs/v14"
TMP = WORKTREES.parent / "tmp"
EVIDENCE = TMP / "latent-v14-prune-record-20261014"
PUBLICATION = "provenance/inventory/v14_weight_prune_20261014"
ORIGIN = "https://github.com/RyoSpiralArchitect/Latent_Workspace.git"
HISTORICAL = TMP / "latent-checkpoint-v2-20261014/WEIGHT_SIZE_INVENTORY.json"
HISTORICAL_SHA256 = "2200eb0caa6e37c245e3d826a60eae84865146580f9d313a288e30adeb15fe34"
TOTAL_BYTES = 88_946_458_314
AUTHORIZATION = (
    "なるほど、V14は、これを回すと前々世代になるわけだから、これらも大腸に記録して"
    "git管理だけして本体は消しておこうか🐈‍⬛ それで行ける容量が空くか見ににいこう☯️"
)


def expected_paths():
    names = ["trainer_state.pt", "workspace_state.pt"] + [
        f"base_model/model-{i:05d}-of-00004.safetensors" for i in range(1, 5)
    ]
    paths = {
        f"boundary_training/{condition}_seed47_step8/{checkpoint}/{name}"
        for condition in ("semantic", "task")
        for checkpoint in ("checkpoint-4", "checkpoint-8", "final")
        for name in names
    }
    paths.update(
        f"{experiment}_20261009/{condition}_step{step}.pt"
        for experiment in ("centered_bridge", "precision_bridge")
        for condition in ("semantic", "task")
        for step in (128, 256)
    )
    return paths


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git(*args):
    return subprocess.check_output(["git", "-C", str(REPO), *args])


def available():
    s = os.statvfs(ROOT)
    return s.f_bavail * s.f_frsize


def service_visibility_gap(comm):
    return comm in {"systemd", "(sd-pam)", "sshd-session"} or comm.startswith("smbd[")


def no_open_targets():
    """Visible same-user handles only; privileged service handles stay UNKNOWN.

    Linux denies ptrace-style fd inspection of some normal session services even
    when their effective UID matches. Do not claim a complete handle audit or
    escalate privileges. An unknown non-service process still blocks dispatch.
    """
    open_handles, errors, blocking_errors = [], [], []
    target_paths = {str(ROOT / relative) for relative in expected_paths()}
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit() or proc.name == str(os.getpid()):
            continue
        try:
            if proc.stat().st_uid != os.getuid():
                continue
            for fd in (proc / "fd").iterdir():
                try:
                    if os.readlink(fd) in target_paths:
                        open_handles.append({"pid": int(proc.name), "fd": fd.name})
                except FileNotFoundError:
                    pass
        except (FileNotFoundError, ProcessLookupError):
            pass
        except PermissionError:
            try:
                comm = (proc / "comm").read_text().strip()
            except (FileNotFoundError, ProcessLookupError):
                continue
            gap = {"pid": int(proc.name), "comm": comm, "target_handles": "UNKNOWN"}
            errors.append(gap)
            if not service_visibility_gap(comm):
                blocking_errors.append(gap)
    fs.require(not open_handles and not blocking_errors,
               "open targets or unreadable non-service processes")
    return {"same_user_open_target_handles": open_handles, "permission_errors": errors,
            "service_handle_visibility": "UNKNOWN" if errors else "NO_PERMISSION_ERRORS",
            "all_process_handles_verified": False}


def protected_other():
    fs.require(sha(HISTORICAL) == HISTORICAL_SHA256, "historical inventory changed")
    result = {}
    for e in json.loads(HISTORICAL.read_bytes())["weights"]:
        path = Path(e["path"])
        if path.is_relative_to(ROOT):
            continue
        if path.is_relative_to(fs.ROOT):
            fs.require(not path.exists(), "previously pruned V12 weight reappeared")
            continue
        s = path.lstat()
        fs.require(stat.S_ISREG(s.st_mode), "protected weight is not regular")
        result[str(path)] = fs.signature(s)
    fs.require(len(result) == 94, "unexpected historical protected-weight count")
    for name, scope in (
        ("latent-v16-adapter-migration-20261014", "frozen"),
        ("latent-v16-adapter-recovery-02-20261014", "full"),
    ):
        for step in (1, 2):
            path = TMP / name / "checkpoints" / f"{scope}_step{step}.pt"
            s = path.lstat()
            fs.require(stat.S_ISREG(s.st_mode), "protected V16 checkpoint is not regular")
            result[str(path)] = fs.signature(s)
    return result


def inspect_and_copy(relative, backup=None):
    with fs.parent_fd(ROOT, relative) as (fd, name):
        before = fs.checked_stat(fd, name, {})
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "rb") as stream:
            fs.require(fs.signature(os.fstat(stream.fileno())) == before, "changed during open")
            if backup is None:
                for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                    digest.update(chunk)
            else:
                with backup.open("xb") as out:
                    for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                        digest.update(chunk)
                        out.write(chunk)
                    out.flush()
                    os.fsync(out.fileno())
            fs.require(fs.signature(os.fstat(stream.fileno())) == before, "changed during read")
        fs.checked_stat(fd, name, before)
    entry = {"relative_path": relative, **before, "sha256": digest.hexdigest()}
    if backup is not None:
        fs.require(sha(backup) == entry["sha256"], "metadata copy hash mismatch")
        entry["backup_relative_path"] = backup.relative_to(EVIDENCE).as_posix()
    return entry


def inventory():
    fs.require(git("remote", "get-url", "origin").decode().strip() == ORIGIN, "wrong repository")
    fs.require(ROOT == ROOT.resolve(strict=True), "unsafe root")
    before = fs.tree_files(ROOT)
    fs.require(all(stat.S_ISREG(e["mode"]) and e["nlink"] == 1 for e in before.values()),
               "symlink, special file or hardlink in scope")
    targets = expected_paths()
    fs.require({p for p in before if Path(p).suffix in fs.WEIGHT_SUFFIXES} == targets,
               "live weights differ from exact authorized set")
    fs.require(sum(before[p]["size_bytes"] for p in targets) == TOTAL_BYTES, "wrong total bytes")
    metadata_paths = sorted(set(before) - targets)
    fs.require(len(metadata_paths) == 502, "metadata count changed; inspect before proceeding")
    fs.require(all(Path(p).suffix in {".json", ".jsonl", ".jinja", ""} for p in metadata_paths),
               "unexpected metadata type")
    handles = no_open_targets()
    others = protected_other()
    EVIDENCE.mkdir(exist_ok=False)
    (EVIDENCE / "metadata").mkdir()
    weights = []
    for i, relative in enumerate(sorted(targets), 1):
        weights.append(inspect_and_copy(relative))
        print(json.dumps({"hashed_weights": i, "total": len(targets)}), flush=True)
    metadata = []
    for i, relative in enumerate(metadata_paths):
        # Flatten names to avoid generated-checkpoint ignore rules. Content stays literal.
        backup = EVIDENCE / "metadata" / f"{i:04d}_{Path(relative).name}"
        metadata.append(inspect_and_copy(relative, backup))
    fs.require(fs.tree_files(ROOT) == before, "source tree changed during inventory")
    fs.require(protected_other() == others, "protected weights changed during inventory")
    record = {
        "format": "latent-v14-explicit-weight-inventory-v1",
        "status": "COMPLETE_RECORDED_NOT_DELETED", "observed_utc": fs.now(),
        "root": str(ROOT), "output_dir": str(EVIDENCE), "remote": ORIGIN,
        "source_worktree_head": git("rev-parse", "HEAD").decode().strip(),
        "script_sha256": sha(Path(__file__)), "helper_sha256": HELPER_SHA256,
        "authorization": AUTHORIZATION, "weights": weights, "metadata": metadata,
        "target_count": len(weights), "target_logical_bytes": TOTAL_BYTES,
        "metadata_count": len(metadata),
        "metadata_bytes": sum(e["size_bytes"] for e in metadata),
        "protected_other_weights": others, "open_handle_screen": handles,
        "available_bytes": available(), "deletion_performed": False,
        "weight_backups_created": False, "hashes_reconstruct_weights": False,
        "old_gate": "FAIL", "winner": "none", "non_regression": "NOT_ESTABLISHED",
    }
    fs.durable_json(EVIDENCE / "INVENTORY.json", record)
    print(json.dumps({"inventory_sha256": sha(EVIDENCE / "INVENTORY.json"),
                      "weights": len(weights), "metadata": len(metadata), "deleted": 0}))


def load_inventory(bundle, expected_sha):
    fs.require(len(expected_sha) == 64 and sha(bundle / "INVENTORY.json") == expected_sha,
               "inventory seal changed")
    inv = json.loads((bundle / "INVENTORY.json").read_bytes())
    fs.require(inv["root"] == str(ROOT) and inv["output_dir"] == str(EVIDENCE), "wrong scope")
    fs.require(inv["script_sha256"] == sha(Path(__file__)), "pruner source changed")
    fs.require(inv["helper_sha256"] == HELPER_SHA256, "helper source changed")
    weights = inv["weights"]
    fs.require(len(weights) == 44 and {e["relative_path"] for e in weights} == expected_paths(),
               "wrong exact target set")
    fs.require(sum(e["size_bytes"] for e in weights) == TOTAL_BYTES, "wrong total bytes")
    fs.require(len(inv["metadata"]) == 502, "wrong metadata count")
    fs.require(len({e["relative_path"] for e in inv["metadata"]}) == 502, "duplicate metadata")
    fs.require(not ({e["relative_path"] for e in inv["metadata"]} & expected_paths()),
               "weight in metadata")
    return inv


def verify_backup(bundle, inv):
    expected = {e["backup_relative_path"] for e in inv["metadata"]}
    fs.require(len(expected) == 502, "duplicate backup")
    actual = {"metadata/" + p for p in fs.tree_files(bundle / "metadata")}
    fs.require(actual == expected, "backup file set changed")
    for e in inv["metadata"]:
        with fs.parent_fd(bundle, e["backup_relative_path"]) as (fd, name):
            fs.checked_hash(fd, name, {"sha256": e["sha256"], "size_bytes": e["size_bytes"]})


def verify_published(commit, inv, inventory_sha):
    fs.require(len(commit) == 40 and all(c in "0123456789abcdef" for c in commit), "bad commit")
    fs.require(git("remote", "get-url", "origin").decode().strip() == ORIGIN, "wrong repository")
    checks = {
        f"{PUBLICATION}/INVENTORY.json": inventory_sha,
        "scripts/prune_v14_recorded_weights.py": inv["script_sha256"],
        "scripts/prune_v12_recorded_weights.py": HELPER_SHA256,
        **{f"{PUBLICATION}/{e['backup_relative_path']}": e["sha256"] for e in inv["metadata"]},
    }
    for name, digest in checks.items():
        fs.require(hashlib.sha256(git("show", f"{commit}:{name}")).hexdigest() == digest,
                   f"published bytes mismatch: {name}")


def execute(inventory_sha, published_commit):
    fs.require(not any((EVIDENCE / p).exists() for p in
                       ("DELETE_STARTED.json", "DELETIONS.jsonl", "DELETE_FINISHED.json",
                        "DELETE_FAILED.json")), "already started; inspect receipts; no retry")
    inv = load_inventory(EVIDENCE, inventory_sha)
    verify_backup(EVIDENCE, inv)
    verify_published(published_commit, inv, inventory_sha)
    fs.require(protected_other() == inv["protected_other_weights"], "protected weights changed")
    expected_tree = {e["relative_path"]: {k: e[k] for k in fs.signature(ROOT.stat())}
                     for e in inv["weights"] + inv["metadata"]}
    fs.require(fs.tree_files(ROOT) == expected_tree, "source tree changed")
    for e in inv["metadata"] + inv["weights"]:
        with fs.parent_fd(ROOT, e["relative_path"]) as (fd, name):
            fs.checked_hash(fd, name, e)
    handles = no_open_targets()
    start = {"format": "latent-v14-explicit-weight-prune-v1", "started_utc": fs.now(),
             "root": str(ROOT), "authorization": AUTHORIZATION,
             "inventory_sha256": inventory_sha, "published_record_commit": published_commit,
             "published_metadata_hashes_verified": len(inv["metadata"]),
             "script_sha256": sha(Path(__file__)), "target_count": 44,
             "target_logical_bytes": TOTAL_BYTES, "available_bytes_before": available(),
             "open_handle_screen": handles, "exclusive_use_required": True,
             "global_transaction_atomic": False, "weight_backups_created": False,
             "recoverability": "Permanent unlink. Hashes/metadata cannot reconstruct weights."}
    fs.durable_json(EVIDENCE / "DELETE_STARTED.json", start)
    deleted = []
    try:
        with (EVIDENCE / "DELETIONS.jsonl").open("x") as log:
            for e in inv["weights"]:
                with fs.parent_fd(ROOT, e["relative_path"]) as (fd, name):
                    fs.checked_stat(fd, name, e)
                    os.unlink(name, dir_fd=fd)
                    os.fsync(fd)
                row = {"relative_path": e["relative_path"], "bytes": e["size_bytes"],
                       "sha256": e["sha256"], "deleted_utc": fs.now()}
                deleted.append(row)
                log.write(json.dumps(row, sort_keys=True) + "\n")
                log.flush()
                os.fsync(log.fileno())
        remaining = {p: s for p, s in expected_tree.items() if p not in expected_paths()}
        fs.require(fs.tree_files(ROOT) == remaining, "protected source entries changed")
        fs.require(protected_other() == inv["protected_other_weights"], "other weights changed")
        for e in inv["metadata"]:
            with fs.parent_fd(ROOT, e["relative_path"]) as (fd, name):
                fs.checked_hash(fd, name, e)
        terminal = {"status": "COMPLETE", "finished_utc": fs.now(),
                    "deleted_count": len(deleted),
                    "deleted_logical_bytes": sum(e["bytes"] for e in deleted),
                    "available_bytes_before": start["available_bytes_before"],
                    "available_bytes_after": available(), "metadata_hashes_preserved": 502,
                    "other_experiment_weights_stat_unchanged": len(inv["protected_other_weights"]),
                    "published_record_commit": published_commit, "inventory_sha256": inventory_sha,
                    "no_weight_backups": True, "new_training_calls": 0, "new_model_calls": 0}
        fs.durable_json(EVIDENCE / "DELETE_FINISHED.json", terminal)
    except BaseException as exc:
        fs.durable_json(EVIDENCE / "DELETE_FAILED.json",
                        {"status": "PARTIAL_OR_POSTCHECK_FAILED", "utc": fs.now(),
                         "confirmed_deletions": len(deleted), "error": repr(exc),
                         "automatic_retry_allowed": False})
        raise
    print(json.dumps(terminal, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inventory")
    verify = sub.add_parser("verify-backup")
    verify.add_argument("--bundle", type=Path, required=True)
    verify.add_argument("--inventory-sha256", required=True)
    delete = sub.add_parser("execute-authorized-v14-deletion")
    delete.add_argument("--inventory-sha256", required=True)
    delete.add_argument("--published-record-commit", required=True)
    args = parser.parse_args()
    if args.command == "inventory":
        inventory()
    elif args.command == "verify-backup":
        inv = load_inventory(args.bundle, args.inventory_sha256)
        verify_backup(args.bundle.resolve(), inv)
        print(json.dumps({"status": "BACKUP_VERIFIED", "metadata": len(inv["metadata"]),
                          "deleted": 0}))
    else:
        execute(args.inventory_sha256, args.published_record_commit)


if __name__ == "__main__":
    main()
