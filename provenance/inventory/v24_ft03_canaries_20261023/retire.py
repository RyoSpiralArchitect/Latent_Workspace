"""Retire exactly the replayed FT03 canary and superseded interrupted FT01 body.

No automatic training, retries, directory deletion or rewrite of FT01 failure.
Inventory/publish/execute are separate. All scientific finals stay protected.
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


common = load("ft03_retirement_primitives", PRIMITIVES)
require, read, digest, write, identity = (
    common.require,
    common.read,
    common.digest,
    common.write,
    common.identity,
)
PROJECT = common.ROOT
ROOT = PROJECT / "latent-v24-recruitment-ft03-20261023"
OLD = PROJECT / "latent-v24-recruitment-ft01-20261023"
SOURCE_TREE = PROJECT / "worktrees/latent-v24-recruitment-ft03-20261023"
SOURCE = "09addc856ba6f10da31054f1674c7547b1ab91ad"
OLD_SHA = "19a09fcccc84960795bd02aa563a6e64d1d7061eac02e3dafaa5a780b9c4d4a8"
HELPERS = [Path(__file__).resolve(), PRIMITIVES, VERIFIER]


def targets():
    result = []
    for root in (ROOT, OLD):
        receipt = root / "raw/canary/CHECKPOINT_canary_step1.pt.json"
        saved = read(receipt)
        require(
            0 < saved["bytes"] <= 28 * 2**30 and re.fullmatch(r"[0-9a-f]{64}", saved["sha256"]),
            "Bounded save receipt",
        )
        if root == OLD:
            require(
                saved["bytes"] == 29004378444 and saved["sha256"] == OLD_SHA,
                "Exact interrupted FT01 body",
            )
        result.append((root / "checkpoints/canary_step1.pt", saved, receipt))
    require(result[0][0] != result[1][0], "Two distinct exact bodies")
    return result


def unused():
    common.TARGETS = [
        (p, saved["bytes"], saved["sha256"], receipt) for p, saved, receipt in targets()
    ]
    common.unused()


def gates():
    sys.path[:0] = [str(SOURCE_TREE / "src"), str(SOURCE_TREE / "scripts")]
    new = load("ft03_retirement_verifier", VERIFIER)
    new.ROOT = SOURCE_TREE
    new.PREP = (
        SOURCE_TREE
        / "provenance/engineering/v24_recruitment_preparation01_20261023/furnace/raw/data/bank"
    )
    require(
        Path(new.ex.__file__).resolve() == SOURCE_TREE / "src/latent_workspace/execution.py",
        "Exact verifier utility imports",
    )
    current = new.verify(ROOT, "checks")
    require(
        current["source_commit"] == SOURCE and current["exact_next_update_replay"] is True,
        "Full FT03 source, qualification, checks and exact replay",
    )
    old = load("ft01_retirement_verifier", SOURCE_TREE / "scripts/verify_v24_recruitment_ft.py")
    failed = old.verify(OLD, "stopped")
    require(
        failed["terminal_native_weight_updates"] is None
        and failed["observed_completed_canary_updates"] == 1
        and failed["exact_next_update_replay"] == "NOT_RUN",
        "FT01 remains failed",
    )
    first = read(OLD / "raw/canary/step1.json")
    replacement = read(ROOT / "raw/canary/step1.json")
    # Payload source identity differs; compare measured numerical state/rows,
    # not the whole source-bound payload digest across two source commits.
    require(
        first["rows"] == replacement["rows"] and first["update"] == replacement["update"],
        "Identical first-window losses, gradients and native update",
    )
    for key in (
        "native",
        "masters",
        "optimizer",
        "rng",
        "buffers",
        "history",
        "completed_steps",
        "tokens_seen",
    ):
        require(first["state"][key] == replacement["state"][key], f"Replacement state: {key}")
    require(
        not (ROOT / "training").exists()
        and not any((ROOT / "raw" / r).exists() for r in ("inline", "workspace")),
        "Scientific arms have not begun",
    )
    return [identity(p, size) for p, size in common.KEPT]


def evidence():
    paths = list(HELPERS)
    for root in (ROOT, OLD):
        paths.extend(
            p
            for p in root.rglob("*")
            if p.is_file()
            and p.relative_to(root).parts[0] != "checkpoints"
            and p.name != "CANARY_RETIREMENT.json"
        )
    require(not any(p.is_symlink() for p in paths), "No evidence symlinks")
    return {str(p): digest(p) for p in sorted(paths)}


def inventory(output):
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
        schema="ltws-ft03-spent-and-superseded-canaries-v1",
        source_commit=SOURCE,
        targets=bodies,
        retained=retained,
        evidence=evidence(),
        available_before_bytes=shutil.disk_usage(ROOT).free,
        total_bytes=sum(t["checkpoint"]["bytes"] for t in bodies),
        utc=datetime.datetime.now(datetime.UTC).isoformat(),
        authority="Ryō authorized obsolete-body cleanup and the separate FT03 recovery.",
        reason="FT03 completed exact replay; FT01 first-window numerical result is reproduced. "
        "Both scientific arms restart from original Mistral. FT01 failure is unchanged.",
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
    unused()
    for entry, (path, saved, _) in zip(value["targets"], targets(), strict=True):
        require(
            entry["identity"] == identity(path, saved["bytes"])
            and entry["checkpoint"] == saved
            and digest(path) == saved["sha256"],
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
    for i, (entry, (path, saved, _)) in enumerate(zip(value["targets"], targets(), strict=True)):
        require(identity(path, saved["bytes"]) == entry["identity"], "Immediate unlink identity")
        path.unlink()
        write(output / f"DELETED_{i}.json", dict(path=str(path), sha256=saved["sha256"]))
    require(
        gates() == value["retained"]
        and evidence() == value["evidence"]
        and all(not p.exists() for p, _, _ in targets()),
        "Only two bodies removed",
    )
    result = dict(
        status="RETIRED_FT03_SPENT_AND_FT01_SUPERSEDED_CANARIES",
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
    new_path, saved, _ = targets()[0]
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
    if args.mode == "inventory":
        inventory(args.output)
    else:
        execute(args.output, args.ledger_sha256, args.published_commit)
