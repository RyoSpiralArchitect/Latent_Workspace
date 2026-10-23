"""One explicitly authorized FT01 body, without claiming successful replay.

Inventory, publication, and one-shot deletion are separate. FT03 is protected.
Never writes a canary-training retirement receipt or edits historical failures.
"""

import argparse
import datetime
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRIMITIVES = HERE.parent / "v24_intermediates_20261022/retire.py"
VERIFIER = HERE / "verify_v24_recruitment_ft03.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


common = load("ft01_superseded_primitives", PRIMITIVES)
require, read, digest, write, identity = (
    common.require,
    common.read,
    common.digest,
    common.write,
    common.identity,
)
PROJECT = common.ROOT
OLD = PROJECT / "latent-v24-recruitment-ft01-20261023"
RETAINED = PROJECT / "latent-v24-recruitment-ft03-20261023"
SOURCE_TREE = PROJECT / "worktrees/latent-v24-recruitment-ft03-20261023"
TARGET = OLD / "checkpoints/canary_step1.pt"
RECEIPT = OLD / "raw/canary/CHECKPOINT_canary_step1.pt.json"
SIZE = 29004378444
SHA = "19a09fcccc84960795bd02aa563a6e64d1d7061eac02e3dafaa5a780b9c4d4a8"
KEPT_CANARY = RETAINED / "checkpoints/canary_step1.pt"
KEPT_SHA = "471776810c42359141b59e7bb7f1dc607668a63114b69d4c9af8d7351b413418"
HELPERS = [Path(__file__).resolve(), PRIMITIVES, VERIFIER]


def target():
    receipt = read(RECEIPT)
    require(receipt["bytes"] == SIZE and receipt["sha256"] == SHA, "Exact FT01 save receipt")
    return dict(identity=identity(TARGET, SIZE), checkpoint=receipt, receipt_path=str(RECEIPT))


def unused():
    common.TARGETS = [(TARGET, SIZE, SHA, RECEIPT)]
    common.unused()


def gates():
    sys.path[:0] = [str(SOURCE_TREE / "src"), str(SOURCE_TREE / "scripts")]
    verifier = load("ft03_retained_failure_verifier", VERIFIER)
    verifier.ROOT = SOURCE_TREE
    verifier.PREP = (
        SOURCE_TREE
        / "provenance/engineering/v24_recruitment_preparation01_20261023/furnace/raw/data/bank"
    )
    require(
        Path(verifier.ex.__file__).resolve() == SOURCE_TREE / "src/latent_workspace/execution.py",
        "Exact offline verifier imports",
    )
    current = verifier.verify(RETAINED, "storage-stopped")
    old = load("ft01_failure_verifier", SOURCE_TREE / "scripts/verify_v24_recruitment_ft.py")
    failed = old.verify(OLD, "stopped")
    require(
        current["exact_next_update_replay"] == failed["exact_next_update_replay"] == "NOT_RUN"
        and current["terminal_native_weight_updates"] is None
        and failed["terminal_native_weight_updates"] is None,
        "Neither failure is upgraded to replay success",
    )
    require(
        read(OLD / "raw/canary/step1.json") == read(RETAINED / "raw/canary/step1.json"),
        "Entire first update numerical state matches retained FT03",
    )
    return [*(identity(p, n) for p, n in common.KEPT), identity(KEPT_CANARY, SIZE)]


def evidence():
    paths = list(HELPERS)
    for root in (OLD, RETAINED):
        paths.extend(
            p
            for p in root.rglob("*")
            if p.is_file() and p.relative_to(root).parts[0] != "checkpoints"
        )
    require(not any(p.is_symlink() for p in paths), "No evidence symlinks")
    return {str(p): digest(p) for p in sorted(paths)}


def inventory(output):
    output.mkdir(exist_ok=False)
    kept = gates()
    unused()
    selected = target()
    require(digest(TARGET) == SHA and target() == selected, "Whole static FT01 body hash")
    require(digest(KEPT_CANARY) == KEPT_SHA and gates() == kept, "Retained FT03 full body hash")
    value = dict(
        schema="ltws-ft01-superseded-without-replay-v1",
        targets=[selected],
        retained=kept,
        retained_ft03_sha256=KEPT_SHA,
        evidence=evidence(),
        total_bytes=SIZE,
        available_before_bytes=shutil.disk_usage(PROJECT).free,
        utc=datetime.datetime.now(datetime.UTC).isoformat(),
        authority=(
            "Ryō explicitly approved: old FT01 canary only; "
            "keep FT03, original Mistral and V22/V23 finals."
        ),
        reason=(
            "FT01 and FT03 first-update numerical records match; retain newer FT03 body. "
            "Neither fresh-process replay was run."
        ),
        exact_next_update_replay="NOT_RUN",
        training_gate_satisfied=False,
        recoverability="No tensor backup in Git; deleted body cannot be restored from Git.",
    )
    write(output / "INVENTORY.json", value)
    print(json.dumps(value), flush=True)


def execute(output, ledger_sha, published_commit):
    require(re.fullmatch(r"[0-9a-f]{40}", published_commit or ""), "Published ledger commit")
    require(digest(output / "INVENTORY.json") == ledger_sha, "Published exact ledger hash")
    value = read(output / "INVENTORY.json")
    require(not (output / "DELETE_STARTED.json").exists(), "Exclusive deletion; no retry")
    require(
        value["schema"] == "ltws-ft01-superseded-without-replay-v1"
        and value["targets"] == [target()]
        and value["total_bytes"] == SIZE
        and value["exact_next_update_replay"] == "NOT_RUN"
        and value["training_gate_satisfied"] is False,
        "Exactly the authorized FT01 body",
    )
    require(
        gates() == value["retained"] and evidence() == value["evidence"],
        "Protected bodies, helpers and all historical evidence unchanged",
    )
    unused()
    require(digest(TARGET) == SHA and target() == value["targets"][0], "Final complete target hash")
    require(
        digest(KEPT_CANARY) == value["retained_ft03_sha256"] == KEPT_SHA,
        "Protected FT03 body unchanged",
    )
    before = shutil.disk_usage(PROJECT).free
    write(
        output / "DELETE_STARTED.json",
        dict(
            ledger_sha256=ledger_sha,
            published_commit=published_commit,
            targets=value["targets"],
            utc=datetime.datetime.now(datetime.UTC).isoformat(),
        ),
    )
    unused()
    require(target() == value["targets"][0], "Immediate unlink identity")
    TARGET.unlink()
    write(output / "DELETED_0.json", dict(path=str(TARGET), sha256=SHA))
    require(
        not TARGET.exists() and gates() == value["retained"] and evidence() == value["evidence"],
        "Only FT01 body removed; no historical or retained-body change",
    )
    result = dict(
        status="RETIRED_FT01_SUPERSEDED_WITHOUT_REPLAY",
        files_deleted=1,
        bytes_deleted=SIZE,
        available_before_bytes=before,
        available_after_bytes=shutil.disk_usage(PROJECT).free,
        ledger_sha256=ledger_sha,
        published_commit=published_commit,
        exact_next_update_replay="NOT_RUN",
        training_gate_satisfied=False,
        recoverability=value["recoverability"],
        utc=datetime.datetime.now(datetime.UTC).isoformat(),
    )
    write(output / "DELETE_FINISHED.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("inventory", "execute"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ledger-sha256")
    parser.add_argument("--published-commit")
    args = parser.parse_args()
    require(args.output.is_absolute() and args.output.resolve() == args.output, "Exact output")
    if args.mode == "inventory":
        inventory(args.output)
    else:
        execute(args.output, args.ledger_sha256, args.published_commit)
