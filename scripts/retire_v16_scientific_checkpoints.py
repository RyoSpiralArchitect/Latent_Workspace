#!/usr/bin/env python3
"""One authorized retirement of six V16 scientific checkpoint bodies.

Fixed paths only. Reuse audited filesystem primitives, not the historical
four-file plan. No tensors, model calls, recursive deletion or automatic retry.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
from pathlib import Path

import retire_v16_engineering_checkpoints as safe

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "scripts/retire_v16_scientific_checkpoints.py"
HELPER = "scripts/retire_v16_engineering_checkpoints.py"
PUBLICATION = "provenance/inventory/v16_scientific_retirement_20261020"
BRANCH = "SpiralReality/latent-memory-full-ft"
RUN = safe.REMOTE_ROOT / "tmp/latent-v16-full-comparison-20261014"
TARGETS = tuple(
    (str(RUN / "checkpoints" / arm / name), size, sha)
    for arm, name, size, sha in (
        (
            "common",
            "step1.pt",
            29054822748,
            "a3978765526ad1bd10cca2c49af6a570b8075a905c6c43faafe70905924e1153",
        ),
        (
            "common",
            "step2.pt",
            29054822748,
            "a65768bba08a630c6c82a8feb72faca8d5eb34c383674a7234f2448c40669a66",
        ),
        (
            "raw_matched_control",
            "step1.pt",
            29083160804,
            "69f0321ce3590f508ae409ff53d09a9d3f8b5a7661aaf65240eb2ebb0845a9f1",
        ),
        (
            "raw_matched_control",
            "step2.pt",
            29083160804,
            "758579bd6d4137301c89572797e88ce8eacf1f1da7f99ac69d9093b5706784dc",
        ),
        (
            "slot_contrast",
            "step1.pt",
            29083160804,
            "f94bbf8373e17d5ca839c5d549044873d364728b418e0187a9c3c9e807764bb5",
        ),
        (
            "slot_contrast",
            "step2.pt",
            29083160804,
            "a038e27c4e9e5e3e45b2f95711ecad8bd7968131c8f3839b14995508d67f0db9",
        ),
    )
)
TOTAL = 174442288712
PROTECTED = tuple(
    (str(safe.REMOTE_ROOT / "tmp" / name), size)
    for name, size in (
        ("latent-v18-native-pilot-20261015/checkpoints/primary/step1.pt", 29083263908),
        ("latent-v18-native-pilot-20261015/checkpoints/primary/step2.pt", 29083263908),
        (
            "latent-v20-a2-depth-ladder-20261016/raw/extract_cut4/FEATURES_final.safetensors",
            3709862144,
        ),
        (
            "latent-v20-a2-depth-ladder-20261016/raw/extract_cut4/FEATURES_train.safetensors",
            1855553792,
        ),
        (
            "latent-v20-a4-gated-route-20261017/raw/extract_mismatch/FEATURES_mismatch.safetensors",
            1855553792,
        ),
    )
)
EVIDENCE_ROOTS = (
    "provenance/pilots/v16_full_comparison_20261014",
    "provenance/pilots/v16_population_diagnostics_20261015",
    "provenance/inventory/native_ft_candidates_20261020",
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def plan():
    names = safe.git("ls-files", "--", *EVIDENCE_ROOTS).decode().splitlines()
    safe.require(names, "No historical evidence")
    for path, size, sha in TARGETS:
        p = Path(path)
        receipt = safe.read_json(
            ROOT / EVIDENCE_ROOTS[0] / "raw" / p.parent.name / f"CHECKPOINT_{p.stem}.json"
        )
        safe.require(
            (receipt["path"], receipt["bytes"], receipt["sha256"]) == (p.name, size, sha),
            "Fixed target differs from historical receipt",
        )
    return {
        "schema": "v16-scientific-retirement-plan-v1",
        "remote": safe.REMOTE,
        "branch": BRANCH,
        "publication": PUBLICATION,
        "targets": [{"path": p, "bytes": size, "sha256": sha} for p, size, sha in TARGETS],
        "total_bytes": TOTAL,
        "protected": [{"path": p, "bytes": size} for p, size in PROTECTED],
        "protected_base_snapshot": str(safe.BASE_SNAPSHOT),
        "source_sha256": {name: digest(ROOT / name) for name in (ENTRY, HELPER)},
        "historical_evidence_sha256": {name: digest(ROOT / name) for name in names},
        "authorization": (
            "Ryō explicitly approved recording and retiring the V16 candidates on 2026-10-20"
        ),
        "retention_exception": (
            "Whole-condition retirement of common/raw_matched_control/slot_contrast"
        ),
        "excluded": "All other weights, beta, features, source, evaluations and receipts",
        "weights_reconstructible_from_git": False,
        "old_gate": "FAIL",
        "winner": "none",
        "non_regression": "NOT_ESTABLISHED",
    }


def protected_state():
    safe.require(
        safe.BASE_SNAPSHOT.is_dir() and not safe.BASE_SNAPSHOT.is_symlink(),
        "Pinned original Mistral snapshot missing",
    )
    return {
        "files": {p: safe.regular(p, size) for p, size in PROTECTED},
        "base_snapshot": str(safe.BASE_SNAPSHOT),
        "base_snapshot_stat": safe.signature(safe.BASE_SNAPSHOT.stat()),
        "scope": "Exact V18/feature stat signatures and base directory, not a content audit",
    }


def output_directory(path):
    path = Path(path)
    safe.require(path.is_absolute() and ".." not in path.parts, "Absolute output required")
    for parent in path.parents:
        if parent.exists() or parent.is_symlink():
            safe.require(stat.S_ISDIR(parent.lstat().st_mode), "Symlink/non-directory ancestor")
    forbidden = (ROOT, RUN, safe.BASE_SNAPSHOT, *(Path(p).parent for p, _ in PROTECTED))
    safe.require(
        not any(path.resolve().is_relative_to(p.resolve()) for p in forbidden),
        "Output overlaps source/target/protected directories",
    )
    path.mkdir(parents=True, exist_ok=False)
    return path


def inventory(output):
    output = output_directory(output)
    safe.write_new(output / "STARTED.json", {"time": safe.stamp(), "pid": os.getpid()})
    try:
        safe.require(not safe.git("status", "--porcelain").strip(), "Dirty source")
        safe.write_new(output / "PLAN.json", plan())
        paths = [p for p, _, _ in TARGETS]
        before = safe.available_space(paths)
        handles_before = safe.visible_handles(paths)
        protected = protected_state()
        records = []
        for index, target in enumerate(TARGETS, 1):
            print(f"Hashing inventory {index}/{len(TARGETS)}: {target[0]}", flush=True)
            records.append(safe.inspect_weight(*target))
            print(f"Verified inventory {index}/{len(TARGETS)}", flush=True)
        handles_after = safe.visible_handles(paths)
        safe.require(protected_state() == protected, "Protected metadata changed")
        safe.write_new(
            output / "INVENTORY.json",
            {
                "schema": "v16-scientific-retirement-inventory-v1",
                "source_commit": safe.git("rev-parse", "HEAD").decode().strip(),
                "time": safe.stamp(),
                "weights": records,
                "protected": protected,
                "deletion_performed": False,
                "plan_sha256": digest(output / "PLAN.json"),
                "handles_before": handles_before,
                "handles_after": handles_after,
                "space_before": before,
                "space_after": safe.available_space(paths),
                "allocated_bytes": sum(r["stat"]["allocated_blocks_512"] * 512 for r in records),
            },
        )
        safe.write_new(
            output / "FINISHED.json",
            {
                "status": "INVENTORY_COMPLETE",
                "files": len(TARGETS),
                "time": safe.stamp(),
            },
        )
    except BaseException as error:
        safe.write_new(
            output / "FINISHED.json",
            {
                "status": "FAILED_NO_DELETION",
                "error": str(error),
                "time": safe.stamp(),
            },
        )
        raise


def published_ledger(ledger, commit):
    safe.require(re.fullmatch(r"[0-9a-f]{40}", commit), "Exact commit required")
    safe.require(safe.git("rev-parse", "HEAD").decode().strip() == commit, "HEAD mismatch")
    safe.require(not safe.git("status", "--porcelain").strip(), "Dirty execution source")
    safe.require(
        safe.git("remote", "get-url", "origin").decode().strip() == safe.REMOTE, "Unexpected remote"
    )
    ref = f"refs/heads/{BRANCH}"
    advertised = safe.git("ls-remote", "--exit-code", "origin", ref).decode().strip()
    safe.require(advertised == f"{commit}\t{ref}", "Ledger not exact published branch HEAD")
    frozen = plan()
    for name in (
        ENTRY,
        HELPER,
        *frozen["historical_evidence_sha256"],
        *(f"{PUBLICATION}/{n}" for n in ("PLAN.json", "INVENTORY.json", "README.md")),
    ):
        safe.require(
            safe.git("show", f"{commit}:{name}") == (ROOT / name).read_bytes(),
            "Committed source/evidence/ledger differs",
        )
    for name in ("PLAN.json", "INVENTORY.json"):
        safe.require(
            (Path(ledger) / name).read_bytes() == (ROOT / PUBLICATION / name).read_bytes(),
            "External ledger differs",
        )
    safe.require(safe.read_json(Path(ledger) / "PLAN.json") == frozen, "Plan differs")
    observed = safe.read_json(Path(ledger) / "INVENTORY.json")
    safe.require(
        observed["schema"] == "v16-scientific-retirement-inventory-v1"
        and observed["deletion_performed"] is False
        and observed["plan_sha256"] == digest(Path(ledger) / "PLAN.json"),
        "Invalid inventory",
    )
    return observed, {"commit": commit, "ref": ref, "remote": safe.REMOTE, "advertised": advertised}


def delete(ledger, output, commit):
    output = output_directory(output)
    safe.write_new(
        output / "DELETE_STARTED.json",
        {
            "time": safe.stamp(),
            "pid": os.getpid(),
            "ledger_commit": commit,
        },
    )
    try:
        observed, publication = published_ledger(ledger, commit)
        safe.require(protected_state() == observed["protected"], "Protected metadata changed")
        handles = safe.preflight(observed["weights"], TARGETS, safe.visible_handles)
        paths = [p for p, _, _ in TARGETS]
        before = safe.available_space(paths)
        safe.write_new(
            output / "PREDELETE.json",
            {
                "publication": publication,
                "handles": handles,
                "all_six_hashes_verified": True,
                "protected": observed["protected"],
                "source_sha256": plan()["source_sha256"],
                "space_before": before,
            },
        )
        with (output / "DELETIONS.jsonl").open("x") as journal:
            safe.unlink_recorded(observed["weights"], journal)
        safe.require(protected_state() == observed["protected"], "Protected metadata changed")
        safe.write_new(
            output / "DELETE_FINISHED.json",
            {
                "status": "COMPLETE",
                "deleted": len(TARGETS),
                "logical_bytes": TOTAL,
                "allocated_bytes": observed["allocated_bytes"],
                "protected_unchanged": True,
                "time": safe.stamp(),
                "space_before": before,
                "space_after": safe.available_space(paths),
                "target_presence": {p: os.path.lexists(p) for p in paths},
                "recoverability": "No backup; Git hashes/metadata cannot reconstruct weights",
                "space_change_caveat": "Filesystem-wide observation, not an exclusive reservation",
            },
        )
    except BaseException as error:
        safe.write_new(
            output / "DELETE_FINISHED.json",
            {
                "status": "FAILED_OR_PARTIAL_NO_RETRY",
                "error": str(error),
                "time": safe.stamp(),
                "target_presence": {p: os.path.lexists(p) for p, _, _ in TARGETS},
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
        safe.require(args.ledger is None and args.ledger_commit is None, "Inventory is read-only")
        inventory(args.output)
    else:
        safe.require(args.ledger is not None and args.ledger_commit is not None, "Ledger required")
        delete(args.ledger, args.output, args.ledger_commit)


if __name__ == "__main__":
    main()
