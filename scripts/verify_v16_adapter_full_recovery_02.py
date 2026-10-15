#!/usr/bin/env python3
"""Offline receipt replay for repair 02. No Torch/model/checkpoint/API load."""

import argparse
import json
from pathlib import Path

import run_v16_adapter_full_recovery_02 as run


def verify(bundle):
    old = run.load("continue_v16_adapter_full")
    previous = run.load("verify_v16_adapter_migration")
    core = run.load("run_v16_adapter_migration")
    history = run.verify_history()
    started, finished = [run.read(bundle / f"{s}.json") for s in ("STARTED", "FINISHED")]
    actual = old.manifest(bundle)
    actual.pop("FINISHED.json")
    run.exact(actual, finished["files"], "terminal bytes/file set")
    seal = started["seal"]
    run.exact(seal, run.read(bundle.parent / "SOURCE_SEAL.json"), "source seal")
    critical = {
        run.ENTRY,
        run.PLAN,
        core.ENTRY,
        core.PLAN,
        "scripts/run_source_sealed.py",
        "scripts/verify_v16_adapter_full_recovery_02.py",
        "src/latent_workspace_ft_v10/native_training_preparation.py",
        *run.TESTS,
    }
    run.require(critical.issubset(seal["source_hashes"]), "missing critical source")
    for name, sha in seal["source_hashes"].items():
        path = run.ROOT / name
        run.require(
            path.resolve().is_relative_to(run.ROOT) and run.digest(path) == sha,
            f"source changed: {name}",
        )
    run.exact(
        started["source_check"],
        {
            "schema": "pre-import-source-check-v1",
            "source_commit": seal["source_commit"],
            "entry": run.ENTRY,
            "source_files": len(seal["source_hashes"]),
            "untracked_check": "all",
            "isolated_python": True,
            "fresh_bytecode_cache": True,
        },
        "source receipt",
    )
    run.validate_selection(started["selection"])
    run.exact(started["selection"], run.read(run.ROOT / run.PLAN), "selection")
    core.validate_plan(started["plan"])
    run.exact(started["plan"], run.read(run.ROOT / core.PLAN), "parent plan")
    run.exact(started["history"], history, "retained historical proof")
    run.exact(
        started["qualification"],
        run.verify_qualification(bundle.parent / "tiny_cuda", seal),
        "tiny proof",
    )
    for key, value in run.CEILING.items():
        run.exact(finished[key], value, key)
    stems = {"full_adapter_v2_step1", "full_adapter_v2_step2", "full_replay_step2"}
    allowed = {
        "STARTED.json",
        "RESOURCES.jsonl",
        "HOST_RESOURCES.jsonl",
        "full_EQUIVALENCE.json",
        "full_REPLAY.json",
        "full_adapter_v2_INITIAL.json",
        "full_adapter_v2_CONTEXT.json",
        "full_adapter_v2_step1_CHECKPOINT.json",
        "full_adapter_v2_step2_CHECKPOINT.json",
    } | {f"{s}{suffix}" for s in stems for suffix in (".json", "_pairs.jsonl")}
    run.require(set(actual).issubset(allowed), "unexpected/unselected recovery work")
    pairs, windows, replays = 0, 0, 0
    for path in bundle.glob("*_pairs.jsonl"):
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        run.require(len(rows) <= 16, "over-budget window")
        run.exact(
            [[r["world"], r["query"]] for r in rows],
            [list(p) for p in core.PAIRS][: len(rows)],
            "journal order",
        )
        pairs += len(rows)
    run.require(pairs <= 48, "over-budget recovery")
    for stem in stems:
        path = bundle / f"{stem}.json"
        if not path.exists():
            continue
        row = run.read(path)
        previous.verify_window(row)
        run.exact(
            row["pairs"],
            [
                json.loads(line)
                for line in (bundle / f"{stem}_pairs.jsonl").read_text().splitlines()
            ],
            "complete journal",
        )
        run.require(row["state"]["completed_steps"] == int(stem[-1]), "window step")
        if "replay" in stem:
            replays += 1
        else:
            windows += 1
    matched, replayed = [], []
    if (bundle / "full_EQUIVALENCE.json").exists():
        run.exact(
            run.read(bundle / "full_EQUIVALENCE.json"),
            {
                "exact": True,
                "steps": [1, 2],
                "ordered_backward_pairs_per_arm": 32,
                "reference_bundle_sha256": run.PREVIOUS_HASH,
                "reference_recomputed": False,
                "candidate": "adapter_v2",
                "provenance_differences": ["source_commit", "preparation"],
            },
            "retained reference equivalence",
        )
        ref = run.reference()
        run.exact(ref["initial"], run.read(bundle / "full_adapter_v2_INITIAL.json"), "initial")
        context = run.read(bundle / "full_adapter_v2_CONTEXT.json")
        run.compare_context(ref["context"], context, seal["source_commit"])
        run.exact(
            context["metadata"],
            {
                "source_commit": seal["source_commit"],
                "seal_sha256": run.digest(bundle.parent / "SOURCE_SEAL.json"),
                "plan_sha256": run.digest(run.ROOT / core.PLAN),
                "selection_sha256": run.digest(run.ROOT / run.PLAN),
                "reference_bundle_sha256": run.PREVIOUS_HASH,
                "mode": "full",
                "implementation": "adapter_v2",
            },
            "checkpoint ownership metadata",
        )
        for step in (1, 2):
            run.exact(
                ref["windows"][step - 1],
                run.read(bundle / f"full_adapter_v2_step{step}.json"),
                f"step {step}",
            )
        matched = ["full"]
    if (bundle / "full_REPLAY.json").exists():
        run.exact(
            run.read(bundle / "full_replay_step2.json"),
            run.read(bundle / "full_adapter_v2_step2.json"),
            "full replay window",
        )
        run.exact(
            run.read(bundle / "full_REPLAY.json"),
            {
                "exact": True,
                "from_step": 1,
                "execute_step": 2,
                "compared_pairs": 16,
                "state_sha256": run.read(bundle / "full_adapter_v2_step2_CHECKPOINT.json")[
                    "state_sha256"
                ],
            },
            "replayed payload",
        )
        replayed = ["full"]
    if finished["status"] == run.PASS:
        run.require(set(actual) == allowed, "PASS file set incomplete")
        run.require(
            matched == replayed == finished["completed_modes"] == ["full"], "incomplete PASS"
        )
        run.require((windows, replays, pairs) == (2, 1, 48), "PASS denominators")
        for key, value in {
            "complete_unique_windows": 2,
            "complete_replay_windows": 1,
            "complete_backward_pairs": 48,
        }.items():
            run.exact(finished[key], value, key)
    else:
        run.require(
            finished["status"] == "INCOMPLETE_NO_RETRY" and finished.get("error"),
            "unknown terminal status",
        )
    return {
        "receipt_verification": "PASS",
        "run_status": finished["status"],
        "original_status": history["original_status"],
        "previous_status": history["run_status"],
        "previous_bundle_sha256": run.PREVIOUS_HASH,
        "matched_modes": matched,
        "replayed_modes": replayed,
        "complete_unique_windows": windows,
        "complete_replay_windows": replays,
        "journaled_backward_pairs": pairs,
        "planned_backward_pairs": 48,
        "combined_backward_pairs": 112 + pairs,
        "combined_planned_backward_pairs": 160,
        "combined_unique_windows": 6 + windows,
        "combined_replay_windows": 1 + replays,
        "combined_engineering_status": (
            "EXACT_7B_MIGRATION_PASS_WITH_OWNED_PREPARATION_ACROSS_THREE_PROCESSES"
            if finished["status"] == run.PASS
            else "INCOMPLETE"
        ),
        "checkpoint_bytes_reloaded_offline": False,
        **run.CEILING,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    print(json.dumps(verify(parser.parse_args().bundle), indent=2, sort_keys=True))
