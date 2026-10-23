"""Retire only the explicitly approved FT04 spent and FT03 superseded canaries.

Separate inventory/publish/execute. No training, retries, recursive deletion,
or rewriting of FT03 failure. Scientific finals and original base stay protected.
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
VERIFIER = HERE / "verify_v24_recruitment_ft04.py"
OLD_VERIFIER = HERE / "verify_v24_recruitment_ft03.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


common = load("ft04_retirement_primitives", PRIMITIVES)
require, read, digest, write, identity = (
    common.require,
    common.read,
    common.digest,
    common.write,
    common.identity,
)
PROJECT = common.ROOT
ROOT = PROJECT / "latent-v24-recruitment-ft04-20261023"
OLD = PROJECT / "latent-v24-recruitment-ft03-20261023"
SOURCE_TREE = PROJECT / "worktrees/latent-v24-recruitment-ft04-20261023"
SOURCE = "4b69c6b0d604f4947b7075e40430b9b8f113f4ad"
SIZE = 29004378444
SHA = "c18804e64d48c94f8046dffba7907bacb6863fddc3434223bbd03438c3682699"
OLD_SHA = "471776810c42359141b59e7bb7f1dc607668a63114b69d4c9af8d7351b413418"
HELPERS = [Path(__file__).resolve(), PRIMITIVES, VERIFIER, OLD_VERIFIER]


def targets():
    result = []
    for root, sha in ((ROOT, SHA), (OLD, OLD_SHA)):
        receipt = root / "raw/canary/CHECKPOINT_canary_step1.pt.json"
        saved = read(receipt)
        require(saved["bytes"] == SIZE and saved["sha256"] == sha, "Exact approved save receipt")
        result.append((root / "checkpoints/canary_step1.pt", saved, receipt))
    require(result[0][0] != result[1][0], "Two distinct exact bodies")
    return result


def unused():
    common.TARGETS = [
        (p, saved["bytes"], saved["sha256"], receipt) for p, saved, receipt in targets()
    ]
    common.unused()


def verifier(path, name):
    sys.path[:0] = [str(SOURCE_TREE / "src"), str(SOURCE_TREE / "scripts")]
    module = load(name, path)
    module.ROOT = SOURCE_TREE
    module.PREP = (
        SOURCE_TREE
        / "provenance/engineering/v24_recruitment_preparation01_20261023/furnace/raw/data/bank"
    )
    require(
        Path(module.ex.__file__).resolve() == SOURCE_TREE / "src/latent_workspace/execution.py",
        "Exact verifier utility import",
    )
    isolation = sys.modules[module.validate_audit.__module__]
    require(
        Path(isolation.__file__).resolve() == SOURCE_TREE / "scripts/qualification_isolation_v2.py",
        "Exact qualification audit import",
    )
    return module


def gates():
    current = verifier(VERIFIER, "ft04_retirement_verifier").verify(ROOT, "checks")
    require(
        current["source_commit"] == SOURCE
        and current["exact_next_update_replay"] is True
        and current["both_canary_updates_exactly_match_ft03"] is True,
        "FT04 source, qualification, exact replay and both historical numerical updates",
    )
    failed = verifier(OLD_VERIFIER, "ft03_historical_verifier").verify(OLD, "storage-stopped")
    require(
        failed["terminal_native_weight_updates"] is None
        and failed["observed_completed_canary_updates"] == 2
        and failed["exact_next_update_replay"] == "NOT_RUN"
        and failed["scientific_updates"] == 0,
        "FT03 remains historically incomplete without replay or scientific training",
    )
    for step in (1, 2):
        require(
            read(OLD / f"raw/canary/step{step}.json") == read(ROOT / f"raw/canary/step{step}.json"),
            "Both numerical records reproduced; source-bound payload hashes remain distinct",
        )
    require(
        not (ROOT / "training").exists()
        and not any((ROOT / "raw" / r).exists() for r in ("inline", "workspace")),
        "Scientific arms have not begun",
    )
    return [identity(p, size) for p, size in common.KEPT]


def evidence():
    paths = list(HELPERS)
    for root in (ROOT, OLD):
        entries = list(root.rglob("*"))
        require(not any(p.is_symlink() for p in entries), "No artifact symlinks")
        paths.extend(
            p
            for p in entries
            if p.is_file()
            and p.relative_to(root).parts[0] != "checkpoints"
            and p != ROOT / "CANARY_RETIREMENT.json"
        )
    require(not any(p.is_symlink() for p in paths), "No helper symlinks")
    return {str(p): digest(p) for p in sorted(paths)}


def inventory(output):
    require(not (ROOT / "CANARY_RETIREMENT.json").exists(), "No prior spent-canary retirement")
    output.mkdir(exist_ok=False)
    retained = gates()
    unused()
    bodies = []
    for path, saved, receipt in targets():
        before = identity(path, saved["bytes"])
        require(
            digest(path) == saved["sha256"] and identity(path, saved["bytes"]) == before,
            "Whole static checkpoint hash",
        )
        bodies.append(dict(identity=before, checkpoint=saved, receipt_path=str(receipt)))
    value = dict(
        schema="ltws-ft04-spent-and-ft03-superseded-canaries-v1",
        source_commit=SOURCE,
        targets=bodies,
        retained=retained,
        evidence=evidence(),
        available_before_bytes=shutil.disk_usage(ROOT).free,
        total_bytes=sum(t["checkpoint"]["bytes"] for t in bodies),
        utc=datetime.datetime.now(datetime.UTC).isoformat(),
        authority="Ryō explicitly approved only the FT03 and FT04 engineering canary bodies.",
        reason="FT04 completed exact replay and reproduced both FT03 numerical updates. "
        "Scientific arms start from original Mistral. FT03 failure and missing replay remain.",
        protected="Original Mistral, V22 step32, V23 off/on step32, all other weights and data.",
        recoverability="No tensor backup in Git; deleted bodies cannot be restored from Git.",
    )
    write(output / "INVENTORY.json", value)
    print(json.dumps(value), flush=True)


def execute(output, ledger_sha, published_commit):
    require(re.fullmatch(r"[0-9a-f]{40}", published_commit or ""), "Published ledger commit")
    require(digest(output / "INVENTORY.json") == ledger_sha, "Published exact ledger hash")
    value = read(output / "INVENTORY.json")
    require(
        not (output / "DELETE_STARTED.json").exists()
        and not (ROOT / "CANARY_RETIREMENT.json").exists(),
        "Exclusive deletion; no retry",
    )
    require(value["source_commit"] == SOURCE and len(value["targets"]) == 2, "Exact bounded scope")
    require(
        gates() == value["retained"] and evidence() == value["evidence"],
        "Protected finals, helpers and complete historical evidence unchanged",
    )
    selected = targets()
    require(
        value["total_bytes"] == sum(saved["bytes"] for _, saved, _ in selected),
        "Exact deletion byte denominator",
    )
    unused()
    for entry, (path, saved, receipt) in zip(value["targets"], selected, strict=True):
        before = identity(path, saved["bytes"])
        require(
            entry["identity"] == before
            and entry["checkpoint"] == saved
            and entry["receipt_path"] == str(receipt)
            and digest(path) == saved["sha256"]
            and identity(path, saved["bytes"]) == before,
            "Final exact whole-body identity",
        )
    before = shutil.disk_usage(ROOT).free
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
    for i, (entry, (path, saved, _)) in enumerate(zip(value["targets"], selected, strict=True)):
        require(identity(path, saved["bytes"]) == entry["identity"], "Immediate unlink identity")
        path.unlink()
        write(output / f"DELETED_{i}.json", dict(path=str(path), sha256=saved["sha256"]))
    require(
        gates() == value["retained"]
        and evidence() == value["evidence"]
        and all(not p.exists() for p, _, _ in selected),
        "Only two bodies removed",
    )
    result = dict(
        status="RETIRED_FT04_SPENT_AND_FT03_SUPERSEDED_CANARIES",
        files_deleted=2,
        bytes_deleted=value["total_bytes"],
        ledger_sha256=ledger_sha,
        published_commit=published_commit,
        available_before_bytes=before,
        available_after_bytes=shutil.disk_usage(ROOT).free,
        recoverability=value["recoverability"],
        utc=datetime.datetime.now(datetime.UTC).isoformat(),
    )
    write(output / "DELETE_FINISHED.json", result)
    new_path, saved, _ = selected[0]
    write(
        ROOT / "CANARY_RETIREMENT.json",
        dict(
            status="SPENT_CANARY_RETIRED_AFTER_EXACT_REPLAY",
            source_commit=SOURCE,
            checkpoint=saved,
            path=str(new_path),
            files_deleted=1,
            replay_receipt_sha256=digest(ROOT / "raw/replay/REPLAY.json"),
            published_ledger_commit=published_commit,
            ledger_sha256=ledger_sha,
            combined_retirement_terminal_sha256=digest(output / "DELETE_FINISHED.json"),
        ),
    )
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("inventory", "execute"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ledger-sha256")
    parser.add_argument("--published-commit")
    args = parser.parse_args()
    require(args.output.is_absolute() and args.output.resolve() == args.output, "Exact output")
    require(
        not any(args.output.is_relative_to(p) for p in (ROOT, OLD, SOURCE_TREE)),
        "Separate retirement journal outside historical runs and source",
    )
    if args.mode == "inventory":
        inventory(args.output)
    else:
        execute(args.output, args.ledger_sha256, args.published_commit)
