"""Retire exactly two superseded V18 engineering bodies after ledger publication.

Never delete scientific V22/V23 finals, the interrupted V24 canary, or base.
The historic V18 execution and negative results remain byte-for-byte intact.
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
V18 = ROOT / "tmp/latent-v18-native-pilot-20261015"
RAW = V18 / "raw"
TARGETS = [
    (
        V18 / "checkpoints/primary/step1.pt",
        29083263908,
        "ed0bac210d5d89ecb1c58545f1e609c701ab6003914771e45c3feb1bea6115c4",
        RAW / "primary/CHECKPOINT_step1.json",
    ),
    (
        V18 / "checkpoints/primary/step2.pt",
        29083263908,
        "8293eb6d808532c8703792bb1077da96b7e86ee278b0dd002ea460da452facb8",
        RAW / "primary/CHECKPOINT_step2.json",
    ),
]
KEPT = [
    (ROOT / "latent-v24-recruitment-ft01-20261023/checkpoints/canary_step1.pt", 29004378444),
    (ROOT / "latent-v22-full-ft-recovery01-20261021/checkpoints/training_step32.pt", 29004418636),
    (ROOT / "latent-v23-preservation-ft01-20261022/checkpoints/off_step32.pt", 29004418636),
    (ROOT / "latent-v23-preservation-ft01-20261022/checkpoints/on_step32.pt", 29004428108),
]
EVIDENCE = [V18 / "SOURCE_SEAL.json"] + [
    p for folder in (RAW, V18 / "qualification") for p in sorted(folder.rglob("*")) if p.is_file()
]


def manifest(folder):
    return {
        str(p.relative_to(folder)): dict(bytes=p.stat().st_size, sha256=digest(p))
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def unused():
    common.TARGETS = TARGETS
    common.unused()


def gates():
    require(
        read(V18 / "SOURCE_SEAL.json")["source_commit"]
        == "fb409ed2ba6ff3b2be209f7a97894b02637f5b2f",
        "V18 source",
    )
    end = read(RAW / "FINISHED.json")
    files = manifest(RAW)
    files.pop("FINISHED.json")
    require(
        end["files"] == files
        and end["status"] == "BOUNDED_V18_NATIVE_PILOT_COMPLETE_NOT_SEMANTIC_QUALIFICATION"
        and end["completed_roles"] == ["probe", "primary", "replay"]
        and end["winner"] == "none"
        and end["old_expression_gate"] == "FAIL",
        "Complete unchanged negative pilot",
    )
    replay = read(RAW / "replay/REPLAY.json")
    require(
        read(RAW / "replay/FINISHED.json")["status"] == "V18_FRESH_PROCESS_EXACT_NEXT_WINDOW_REPLAY"
        and replay["exact"] is True
        and replay["from_step"] == 1
        and replay["execute_step"] == 2
        and replay["compared_pairs"] == 16
        and replay["primary_pid"] != replay["replay_pid"]
        and replay["state_sha256"] == read(TARGETS[1][3])["state_sha256"],
        "Historical exact fresh-process replay",
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
        schema="ltws-v18-superseded-engineering-retirement-v1",
        targets=entries,
        retained=kept,
        evidence={str(p): digest(p) for p in EVIDENCE},
        script_sha256=digest(Path(__file__)),
        utilities_sha256=digest(_utilities),
        total_bytes=sum(t[1] for t in TARGETS),
        available_before_bytes=shutil.disk_usage(ROOT).free,
        utc=datetime.datetime.now(datetime.UTC).isoformat(),
        reason="Closed two-update V18 engineering pair; superseded by native V22/V23. "
        "Current V24 training and comparisons do not consume these bodies. Retire this whole old "
        "engineering condition, not a scientific winner selection.",
        authority="2026-10-23: Ryō authorized removing no-longer-needed artifacts for capacity.",
        recoverability="No tensor backup in Git; deleted bodies cannot be restored from Git.",
        protected="Original Mistral; V24 interrupted canary; V22 final; V23 off/on finals; "
        "teacher bank; all other tensor files, datasets, source worktrees and project assets.",
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
    require(len(ledger["targets"]) == len(TARGETS) == 2, "Exactly two V18 engineering files")
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
            status="RETIRED_TWO_SUPERSEDED_V18_ENGINEERING_BODIES",
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
