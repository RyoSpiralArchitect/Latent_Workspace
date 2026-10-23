"""One spent V24 canary, only after complete exact replay and published ledger.

This helper does not train, retry or select a scientific checkpoint. Body bytes
cannot be recovered from the metadata ledger. No wildcard/recursive deletion.
"""

import argparse
import datetime
import importlib.util
import json
import re
import shutil
from pathlib import Path

_utilities = Path(__file__).resolve().parents[1] / "v24_intermediates_20261022/retire.py"
_spec = importlib.util.spec_from_file_location("one_canary_primitives", _utilities)
common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(common)
require, read, digest, write, identity = (
    common.require,
    common.read,
    common.digest,
    common.write,
    common.identity,
)
PROJECT = common.ROOT
ROOT = PROJECT / "latent-v24-recruitment-ft01-20261023"
TARGET = ROOT / "checkpoints/canary_step1.pt"
RECEIPT = ROOT / "raw/canary/CHECKPOINT_canary_step1.pt.json"
SOURCE = "d43382833f6dc85787720bda80aec511c66f58be"
KEPT = [
    (
        PROJECT / "latent-v22-full-ft-recovery01-20261021/checkpoints/training_step32.pt",
        29004418636,
    ),
    (PROJECT / "latent-v23-preservation-ft01-20261022/checkpoints/off_step32.pt", 29004418636),
    (PROJECT / "latent-v23-preservation-ft01-20261022/checkpoints/on_step32.pt", 29004428108),
    (PROJECT / "tmp/latent-v18-native-pilot-20261015/checkpoints/primary/step1.pt", 29083263908),
    (PROJECT / "tmp/latent-v18-native-pilot-20261015/checkpoints/primary/step2.pt", 29083263908),
]
EVIDENCE = [
    ROOT / name
    for name in (
        "SOURCE_SEAL.json",
        "checks/STARTED.json",
        "checks/FINISHED.json",
        "raw/canary/STARTED.json",
        "raw/canary/FINISHED.json",
        "raw/canary/STEP2_PAYLOAD.json",
        "raw/replay/STARTED.json",
        "raw/replay/FINISHED.json",
        "raw/replay/REPLAY.json",
        "qualification/cpu/FINISHED.json",
        "qualification/cuda/FINISHED.json",
        "qualification/CPU_ISOLATION.json",
    )
] + [RECEIPT]


def manifest(folder):
    return {
        str(p.relative_to(folder)): dict(bytes=p.stat().st_size, sha256=digest(p))
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def gates():
    seal = read(ROOT / "SOURCE_SEAL.json")
    require(seal["source_commit"] == SOURCE, "Pinned checks source")
    start, end = read(ROOT / "checks/STARTED.json"), read(ROOT / "checks/FINISHED.json")
    files = manifest(ROOT / "checks")
    files.pop("FINISHED.json")
    require(
        start["seal"] == seal
        and end["files"] == files
        and end["status"] == "V24_ROUTE_CHECKS_COMPLETE_NOT_TRAINING"
        and end["completed_roles"] == ["canary", "replay"]
        and end["native_weight_updates"] == 3,
        "Complete checks phase",
    )
    for role in ("canary", "replay"):
        folder = ROOT / "raw" / role
        result = read(folder / "FINISHED.json")
        require(end["role_manifests"][role] == manifest(folder), "Original role manifests")
        require(result["status"] == f"V24_RECRUITMENT_{role.upper()}_COMPLETE", "Passed role")
        require(read(folder / "STARTED.json")["seal"] == seal, "Same-source role")
    replay = read(ROOT / "raw/replay/REPLAY.json")
    require(
        replay["exact"] is True
        and replay["state_sha256"] == read(ROOT / "raw/canary/STEP2_PAYLOAD.json")["state_sha256"],
        "Exact next-update payload",
    )
    for device in ("cpu", "cuda"):
        result = read(ROOT / "qualification" / device / "FINISHED.json")
        require(
            result["status"] == "V24_ROUTE_FT_TINY_PASS_NOT_7B"
            and result["counts"] == dict(tests=570, failures=0, errors=0, skipped=0),
            "570/device qualification",
        )
    require(
        read(ROOT / "qualification/CPU_ISOLATION.json")["status"] == "CPU_GPU_ISOLATION_PASS",
        "Isolation",
    )
    require(
        not any((ROOT / "raw" / r).exists() for r in ("inline", "workspace")),
        "Scientific FT has not begun",
    )
    return [identity(path, size) for path, size in KEPT]


def unused():
    common.TARGETS = [(TARGET, 0, "", None)]
    common.unused()


def inventory(output):
    output.mkdir(exist_ok=False)
    kept = gates()
    saved = read(RECEIPT)
    require(
        0 < saved["bytes"] <= 28 * 2**30 and re.fullmatch(r"[0-9a-f]{64}", saved["sha256"]),
        "Bounded saved checkpoint",
    )
    before = identity(TARGET, saved["bytes"])
    unused()
    require(
        digest(TARGET) == saved["sha256"] and identity(TARGET, saved["bytes"]) == before,
        "Complete static body",
    )
    value = dict(
        schema="ltws-spent-canary-retirement-v1",
        source_commit=SOURCE,
        target=before,
        checkpoint=saved,
        retained=kept,
        evidence={str(p): digest(p) for p in EVIDENCE},
        script_sha256=digest(Path(__file__)),
        utilities_sha256=digest(_utilities),
        available_before_bytes=shutil.disk_usage(ROOT).free,
        utc=datetime.datetime.now(datetime.UTC).isoformat(),
        reason=(
            "Two canary updates and exact fresh replay completed. Scientific arms restart "
            "from original base. This engineering body is spent."
        ),
        authority=(
            "Ryō authorized unused-artifact cleanup and continuation toward full FT on 2026-10-23."
        ),
        recoverability=(
            "Tensor body has no Git backup; only hashes, exact replay and metadata remain."
        ),
    )
    write(output / "INVENTORY.json", value)
    print(json.dumps(value), flush=True)


def execute(output, ledger_sha, published_commit):
    require(re.fullmatch(r"[0-9a-f]{40}", published_commit or ""), "Published ledger commit")
    require(digest(output / "INVENTORY.json") == ledger_sha, "Published exact ledger")
    value = read(output / "INVENTORY.json")
    require(
        digest(Path(__file__)) == value["script_sha256"]
        and digest(_utilities) == value["utilities_sha256"],
        "Pinned helpers",
    )
    require(
        not (output / "DELETE_STARTED.json").exists()
        and not (ROOT / "CANARY_RETIREMENT.json").exists(),
        "Exclusive deletion",
    )
    require(gates() == value["retained"], "Protected comparisons unchanged")
    require(
        all(digest(Path(p)) == sha for p, sha in value["evidence"].items()),
        "Historical receipts unchanged",
    )
    saved = value["checkpoint"]
    require(
        read(RECEIPT) == saved and identity(TARGET, saved["bytes"]) == value["target"],
        "Exact target identity",
    )
    unused()
    require(
        digest(TARGET) == saved["sha256"] and identity(TARGET, saved["bytes"]) == value["target"],
        "Final body hash",
    )
    before = shutil.disk_usage(ROOT).free
    write(
        output / "DELETE_STARTED.json",
        dict(
            ledger_sha256=ledger_sha,
            published_commit=published_commit,
            path=str(TARGET),
            checkpoint=saved,
            utc=datetime.datetime.now(datetime.UTC).isoformat(),
        ),
    )
    unused()
    require(identity(TARGET, saved["bytes"]) == value["target"], "Immediate unlink identity")
    TARGET.unlink()
    write(output / "DELETED_0.json", dict(path=str(TARGET), sha256=saved["sha256"]))
    require(gates() == value["retained"] and not TARGET.exists(), "Exactly one canary removed")
    result = dict(
        status="SPENT_CANARY_RETIRED_AFTER_EXACT_REPLAY",
        source_commit=SOURCE,
        checkpoint=saved,
        path=str(TARGET),
        files_deleted=1,
        bytes_deleted=saved["bytes"],
        replay_receipt_sha256=digest(ROOT / "raw/replay/REPLAY.json"),
        published_ledger_commit=published_commit,
        ledger_sha256=ledger_sha,
        available_before_bytes=before,
        available_after_bytes=shutil.disk_usage(ROOT).free,
        recoverability=value["recoverability"],
        utc=datetime.datetime.now(datetime.UTC).isoformat(),
    )
    write(output / "DELETE_FINISHED.json", result)
    write(ROOT / "CANARY_RETIREMENT.json", result)
    print(json.dumps(result), flush=True)


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
