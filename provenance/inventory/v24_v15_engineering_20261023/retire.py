"""Retire exactly two superseded V15 engineering bodies after ledger publication.

Never delete scientific V22/V23 finals, the retained V18 comparator, or base.
The historic V15 execution and negative results remain byte-for-byte intact.
"""

import argparse
import datetime
import importlib.util
import json
import re
import shutil
from pathlib import Path

_utilities = Path(__file__).resolve().parents[1] / "v24_intermediates_20261022/retire.py"
_spec = importlib.util.spec_from_file_location("retirement_primitives", _utilities)
common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(common)
require, read, digest, write, identity = (
    common.require,
    common.read,
    common.digest,
    common.write,
    common.identity,
)
ROOT = common.ROOT
V15 = ROOT / "worktrees/latent-workspace-v15-native-learner-20261010"
RAW = V15 / "runs/v15_native_full_20261010"
TARGETS = [
    (
        V15 / "runs/checkpoints_v15_native_full_20261010/full/step1.pt",
        29054758918,
        "df0382eed7c1f657858699f26027ed67a04baebc8d621d1c48b3c2a0d2269b19",
        RAW / "full_1_checkpoint.json",
    ),
    (
        V15 / "runs/checkpoints_v15_native_full_20261010/full/step2.pt",
        29054758918,
        "60e7de1b43a8599bcc616b1ba1aef5c410035cc9cfe2131dcc84bbe8d9f0b2ce",
        RAW / "full_2_checkpoint.json",
    ),
]
KEPT = [
    (ROOT / "latent-v22-full-ft-recovery01-20261021/checkpoints/training_step32.pt", 29004418636),
    (ROOT / "latent-v23-preservation-ft01-20261022/checkpoints/off_step32.pt", 29004418636),
    (ROOT / "latent-v23-preservation-ft01-20261022/checkpoints/on_step32.pt", 29004428108),
    (ROOT / "tmp/latent-v18-native-pilot-20261015/checkpoints/primary/step1.pt", 29083263908),
    (ROOT / "tmp/latent-v18-native-pilot-20261015/checkpoints/primary/step2.pt", 29083263908),
]
EVIDENCE = [
    V15 / "runs/input/SOURCE_SEAL.json",
    V15 / "runs/CHECKPOINT_AUDIT.json",
    RAW / "FINISHED.json",
    RAW / "REPORT.json",
    RAW / "full_RESUME.json",
    *(t[3] for t in TARGETS),
]


def unused():
    common.TARGETS = TARGETS
    common.unused()


def gates():
    report = read(RAW / "REPORT.json")
    require(report["source_commit"] == "3ee78fbd157174059cc3bbd52f05ea02938ec754", "V15 source")
    require(
        read(RAW / "FINISHED.json")["report_sha256"] == digest(RAW / "REPORT.json"),
        "Historical terminal/report hash",
    )
    require(report["status"] == "COMPLETED_ENGINEERING_PILOT", "Completed V15 pilot")
    require(read(RAW / "full_RESUME.json")["exact"] is True, "Exact V15 replay")
    require(
        report["winner"] == "none" and report["old_expression_gate"] == "FAIL",
        "Retain negative result",
    )
    audit = read(V15 / "runs/CHECKPOINT_AUDIT.json")
    require(audit["status"] == "VERIFIED_RETAINED_CHECKPOINT_FILES_AND_NATIVE_CAST", "V15 audit")
    for path, size, sha, _ in TARGETS:
        matches = [
            r
            for r in audit["rows"]
            if r["phase"] == "full" and r["arm"] == "full" and r["path"] == path.name
        ]
        require(
            len(matches) == 1 and matches[0]["sha256"] == sha and matches[0]["bytes"] == size,
            "Historical audited body",
        )
    return [identity(p, n) for p, n in KEPT]


def inventory(output):
    output.mkdir(exist_ok=False)
    kept = gates()
    unused()
    entries = []
    for path, size, sha, receipt in TARGETS:
        before = identity(path, size)
        require(digest(path) == sha and identity(path, size) == before, "Static full-body hash")
        saved = read(receipt)
        require(saved["sha256"] == sha and saved["bytes"] == size, "Original receipt")
        entries.append(dict(**before, sha256=sha, checkpoint_receipt=saved))
    ledger = dict(
        schema="ltws-v15-superseded-engineering-retirement-v1",
        targets=entries,
        retained=kept,
        evidence={str(p): digest(p) for p in EVIDENCE},
        script_sha256=digest(Path(__file__)),
        utilities_sha256=digest(_utilities),
        total_bytes=sum(t[1] for t in TARGETS),
        available_before_bytes=shutil.disk_usage(ROOT).free,
        utc=datetime.datetime.now(datetime.UTC).isoformat(),
        reason="Closed two-update V15 engineering pair; superseded by V18 and native V22/V23. "
        "No current configs/scripts/src refer to these bodies. Retire this whole old "
        "engineering condition, not a scientific winner selection.",
        authority="2026-10-23: Ryō authorized removing no-longer-needed artifacts for capacity.",
        recoverability="No tensor backup in Git; deleted bodies cannot be restored from Git.",
        protected="Original Mistral; V18 pair; V22 final; V23 off/on finals and teacher bank; "
        "all other tensor files, datasets, source worktrees and project assets.",
    )
    write(output / "INVENTORY.json", ledger)
    print(json.dumps(ledger), flush=True)


def execute(output, ledger_sha, published_commit):
    require(re.fullmatch(r"[0-9a-f]{40}", published_commit or ""), "Published ledger commit")
    require(digest(output / "INVENTORY.json") == ledger_sha, "Published ledger hash")
    ledger = read(output / "INVENTORY.json")
    require(
        digest(Path(__file__)) == ledger["script_sha256"]
        and digest(_utilities) == ledger["utilities_sha256"],
        "Published helper hashes",
    )
    require(len(ledger["targets"]) == len(TARGETS) == 2, "Exactly two V15 engineering files")
    require(not (output / "DELETE_STARTED.json").exists(), "No repeated deletion attempt")
    require(gates() == ledger["retained"], "Retained comparator identities")
    for path, sha in ledger["evidence"].items():
        require(digest(Path(path)) == sha, "Historical evidence unchanged")
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
    for i, (saved, (path, size, _, _)) in enumerate(zip(ledger["targets"], TARGETS, strict=True)):
        observed = identity(path, size)
        require({k: saved[k] for k in observed} == observed, "Immediate pre-unlink identity")
        path.unlink()
        write(output / f"DELETED_{i}.json", dict(path=str(path), sha256=saved["sha256"]))
    require(gates() == ledger["retained"], "Protected comparisons unchanged")
    write(
        output / "DELETE_FINISHED.json",
        dict(
            status="RETIRED_TWO_SUPERSEDED_V15_ENGINEERING_BODIES",
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
