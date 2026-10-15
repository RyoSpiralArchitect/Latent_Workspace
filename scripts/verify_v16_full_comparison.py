#!/usr/bin/env python3
"""Offline receipt replay; never loads weights, a model, or dispatches work."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import run_v16_full_comparison as run


def require(ok, message):
    if not ok:
        raise ValueError(message)


def verify_evaluation(value, plan, step):
    from latent_workspace_ft_v10.v16_comparison_eval import CONDITIONS, FACTORS, summarize

    require(
        value["step"] == step
        and value["rng_unchanged"] is True
        and value["owned_state_fingerprint_unchanged"] is True,
        "Evaluation state receipt",
    )
    coordinates = [(w, q) for w in plan["worlds"] for q in plan["queries"]]
    require(
        [(r["world"], r["query"], r["condition"]) for r in value["rows"]]
        == [(w, q, c) for w, q in coordinates for c in CONDITIONS],
        "Evaluation row coverage/order",
    )
    require(
        [(r["world"], r["query"], r["factor"]) for r in value["contrasts"]]
        == [(w, q, f) for w, q in coordinates for f in FACTORS],
        "Factor coverage/order",
    )
    require(
        [(r["world"], r["query"]) for r in value["direct_base"]] == coordinates,
        "Direct-base coverage",
    )
    require(
        [(r["world"], r["query"]) for r in value["original_base"]] == coordinates,
        "Original-base coverage",
    )
    rows = {(r["world"], r["query"], r["condition"]): r for r in value["rows"]}
    bases = {(r["world"], r["query"]): r for r in value["direct_base"]}
    for r in [*value["rows"], *value["direct_base"], *value["original_base"]]:
        gap = r["scores"][1] - r["scores"][0]
        require(
            r["gap"] == gap and r["prediction"] == (None if gap == 0 else int(gap > 0)),
            "Choice score/gap/tie arithmetic",
        )
    for r in value["rows"]:
        condition = r["condition"]
        labels = bases[r["world"], r["query"]]["labels"]
        expected = (
            labels[int(condition in ("twin", "reverse_twin"))]
            if condition in CONDITIONS[:4]
            else None
        )
        require(r["target"] == expected, "Control assigned a semantic target")
        require(
            r["correct"] == (r["prediction"] == expected if expected is not None else None),
            "Correctness mismatch",
        )
        if condition == "zero" or step == 0:
            require(
                r["full_logits_equal_current_base"] and r["delta_l2"] == 0,
                "Zero/initial full-logit parity",
            )
    for r in value["contrasts"]:
        left, right = FACTORS[r["factor"]]
        a, b = [rows[r["world"], r["query"], c] for c in (left, right)]
        labels = bases[r["world"], r["query"]]["labels"]
        affected = labels[0] != labels[1]
        change = b["gap"] - a["gap"]
        require(r["labels"] == labels and r["affected"] == affected, "Factor label geometry")
        require(r["transport"]["native_published_gap_change"] == [change], "Transport gap replay")
        require(
            r["donor_directed_gap_change"] == ((2 * labels[1] - 1) * change if affected else None),
            "Donor direction arithmetic",
        )
        require(
            r["left_prediction"] == a["prediction"] and r["right_prediction"] == b["prediction"],
            "Factor predictions",
        )
        if r["factor"] == "same_memory":
            require(change == 0, "Same-memory control changed")
    require(value["summary"] == summarize(value), "Summary replay mismatch")
    return value["summary"]


def verify_arm(path, seal, plan):
    start, end = [run.read(path / f"{s}.json") for s in ("STARTED", "FINISHED")]
    files = run.manifest(path)
    files.pop("FINISHED.json")
    require(files == end["files"], "Arm artifact hash/size manifest")
    require(start["seal"] == seal and start["plan"] == plan, "Arm source/plan")
    require(start["arm"] == end["arm"] == path.name, "Arm identity")
    require(all(end[k] == v for k, v in run.CEILING.items()), "Claim ceiling changed")
    require(end["status"] == run.PASS, "Arm incomplete; retain missingness, no retry")
    require(
        (
            end["complete_unique_windows"],
            end["complete_replay_windows"],
            end["complete_backward_pairs"],
        )
        == (2, 1, 48),
        "Arm denominators",
    )
    windows = [run.read(path / f"{name}.json") for name in ("step1", "step2", "replay_step2")]
    pairs = [(w, q) for w in plan["worlds"] for q in plan["queries"]]
    for name, step, window in zip(
        ("step1", "step2", "replay_step2"), (1, 2, 2), windows, strict=True
    ):
        require([(r["world"], r["query"]) for r in window["pairs"]] == pairs, "Backward pair order")
        require(window["state"]["completed_steps"] == step, "Update step")
        journal = [
            json.loads(line) for line in (path / f"{name}_pairs.jsonl").read_text().splitlines()
        ]
        require(journal == window["pairs"], "Pair journal disagreement")
    require(windows[1] == windows[2], "Complete update replay differs")
    replay = run.read(path / "REPLAY.json")
    checkpoints = [run.read(path / f"CHECKPOINT_step{s}.json") for s in (1, 2)]
    require(
        replay
        == dict(
            exact=True,
            state_sha256=checkpoints[1]["state_sha256"],
            from_step=1,
            execute_step=2,
            compared_pairs=16,
        ),
        "Checkpoint replay",
    )
    evaluations = [run.read(path / f"evaluation_step{s}.json") for s in (0, 1, 2)]
    summaries = [verify_evaluation(value, plan, step) for step, value in enumerate(evaluations)]
    require(
        all(v["original_base"] == evaluations[0]["direct_base"] for v in evaluations),
        "Original-base reference changed",
    )
    if path.name == "slot_contrast":
        require(
            all(
                r["interaction_exact_zero"]
                for v in evaluations
                for r in v["rows"]
                if r["condition"].startswith("common_")
            ),
            "Equal-slot contrast null failed",
        )
    budget = start["budget"]["resources"]
    require(
        end["peak_cuda_reserved_bytes"] <= budget["allocator_cap_gib"] * 2**30
        and end["minimum_sampled_device_free_bytes"] >= budget["abort_free_gib"] * 2**30
        and end["minimum_sampled_host_available_bytes"]
        >= budget["host_abort_available_gib"] * 2**30
        and end["elapsed_seconds"] <= budget["max_elapsed_seconds"],
        "Resource envelope exceeded",
    )
    return dict(
        arm=path.name,
        complete_backward_pairs=48,
        summaries=summaries,
        checkpoint_bytes=sum(r["bytes"] for r in checkpoints),
        peak_cuda_allocated_bytes=end["peak_cuda_allocated_bytes"],
        peak_cuda_reserved_bytes=end["peak_cuda_reserved_bytes"],
        elapsed_seconds=end["elapsed_seconds"],
    )


def verify(path, seal, qualification_path):
    start, end = [run.read(path / f"{s}.json") for s in ("STARTED", "FINISHED")]
    plan = start["plan"]
    run.validate_plan(plan)
    require(start["seal"] == seal, "Dispatch source seal")
    files = run.manifest(path)
    files.pop("FINISHED.json")
    require(files == end["files"], "Dispatch artifact manifest")
    require(
        end["status"] == run.PASS and end["completed_arms"] == list(run.ARMS),
        "Matrix incomplete; retain missingness, no retry",
    )
    require(all(end[k] == v for k, v in run.CEILING.items()), "Matrix claim ceiling")
    require(
        run.qualification(qualification_path, seal, plan) == start["qualification"],
        "Qualification replay",
    )
    core = run.load("run_v16_adapter_migration")
    require(
        all(core.digest(run.ROOT / p) == h for p, h in seal["source_hashes"].items()),
        "Current source differs from execution seal",
    )
    rows = [verify_arm(path / arm, seal, plan) for arm in run.ARMS]
    initial = [run.read(path / arm / "INITIAL.json") for arm in run.ARMS]
    for key in ("native_state", "masters", "rng"):
        require(initial[0][key] == initial[1][key] == initial[2][key], f"Initial {key} differs")
    common = {
        k.removeprefix("common."): v
        for k, v in initial[1]["bridge_state"].items()
        if k.startswith("common.")
    }
    require(common == initial[0]["bridge_state"], "Common reader initialization differs")
    require(
        initial[1]["bridge_state"] == initial[2]["bridge_state"],
        "Capacity-control initialization differs",
    )
    base_rows = [run.read(path / arm / "evaluation_step0.json")["direct_base"] for arm in run.ARMS]
    require(base_rows[0] == base_rows[1] == base_rows[2], "Original base evaluation differs")
    return dict(
        status=run.PASS,
        arms=rows,
        complete_unique_windows=6,
        complete_replay_windows=3,
        complete_backward_pairs=144,
        workspace_evaluation_rows=1440,
        direct_base_evaluation_rows=144,
        factor_rows=720,
        **run.CEILING,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--seal", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    import sys

    sys.path.insert(0, str(run.ROOT / "src"))
    result = verify(args.bundle, run.read(args.seal), args.qualification)
    if args.output:
        run.load("run_v16_adapter_migration").write_new(args.output, result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
