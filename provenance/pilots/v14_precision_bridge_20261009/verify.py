#!/usr/bin/env python3
"""Verify compact V14 precision-bridge evidence without loading any model.

Default verification checks published checkpoint metadata, not absent weight
bodies. Add --verify-weights on Furnace to hash the retained checkpoint bodies.
No GPU work or file writes are performed.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import random
import sys
from pathlib import Path
from typing import Any

BUNDLE = Path(__file__).resolve().parent
REPO = BUNDLE.parents[2]
PLAN = "configs/v14/PRECISION_BRIDGE_PLAN.json"
HISTORIES = ("teacher_forced_fixed_history", "free_history")
READOUTS = ("native_bf16_head", "fp32_choice_head")
CONTROLS = ("intact", "twin", "zero", "fixed_carrier", "norm_matched_random", "unrelated")
SCENARIOS = ("w0_s0", "w0_s1", "w1_s0", "w1_s1")
REGIMES = ("greedy", "sample_211", "sample_212", "sample_213")
CELLS = ("task", "semantic")
CONDITIONS = ("base_query_only", "base_inline") + tuple(
    f"{cell}_{control}" for cell in CELLS for control in CONTROLS
)
QUERIES = (0, 2, 0, 2)


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def reject_constant(value: str) -> None:
    raise ValueError(f"Nonfinite JSON constant: {value}")


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    require(isinstance(value, dict), f"Expected JSON object: {path}")
    return value


def inside(root: Path, relative: str) -> Path:
    require(not Path(relative).is_absolute(), f"Expected relative path: {relative}")
    path = (root / relative).resolve()
    path.relative_to(root)
    return path


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def check_dual(value: dict[str, Any], *, zero: bool = False) -> None:
    require(set(value) == {*READOUTS, "delta_l2", "delta_rms"}, "Unknown readout fields")
    norm, rms = value["delta_l2"], value["delta_rms"]
    require(math.isfinite(norm) and 0 <= norm <= 1.0, "Residual norm exceeds frozen bound")
    require(math.isfinite(rms) and rms >= 0, "Invalid residual RMS")
    require(not zero or (norm == 0.0 and rms == 0.0), "Zero lane has a nonzero delta")
    for readout in READOUTS:
        row = value[readout]
        scores = row["scores"]
        require(len(scores) == 2 and all(math.isfinite(v) for v in scores), "Invalid scores")
        require(row["yes_minus_no"] == scores[1] - scores[0], "Choice margin mismatch")
        require(row["greedy_choice"] == int(scores[1] > scores[0]), "Greedy choice mismatch")


def verify_single(
    result: dict[str, Any], records: list[dict[str, Any]], *, step0: bool
) -> dict[tuple[int, int, int, str], dict[str, Any]]:
    rows = result["rows"]
    index = {(r["world_index"], r["side"], r["query_index"], r["control"]): r for r in rows}
    expected = set(itertools.product(range(64), range(2), range(8), CONTROLS))
    require(len(rows) == len(index) == result["row_count"] == 6144, "Single row closure")
    require(set(index) == expected and result["world_count"] == 64, "Single dimension closure")
    require(result["winner"] == "none" and result["semantic_promotion"] is False, "Promotion")
    for key, row in index.items():
        world, side, query, control = key
        source = records[world]
        original, donor = source["answers"][side][query], source["answers"][1 - side][query]
        require(row["pair_id"] == source["metadata"]["pair_id"], "Pair ID drift")
        require(row["original_label"] == original and row["donor_label"] == donor, "Label drift")
        require(row["affected"] == (original != donor), "Affected mask drift")
        require(row["heldout_template"] == source["heldout_queries"][query], "Template drift")
        require(row["target_label"] == (donor if control == "twin" else original), "Target drift")
        check_dual(row["dual_readout"], zero=step0 or control == "zero")
        check_dual(row["base_dual_readout"], zero=True)
        if step0 or control == "zero":
            require(row["dual_readout"] == row["base_dual_readout"], "Zero/base mismatch")
        require(
            row["base_dual_readout"] == index[(world, 0, query, "intact")]["base_dual_readout"],
            "Base scores depend on side/control",
        )
        if control == "twin":
            require(
                row["dual_readout"] == index[(world, 1 - side, query, "intact")]["dual_readout"],
                "Twin swap does not select the opposite intact memory",
            )
    return index


def uniform(seed: int, scenario: str, turn: int) -> float:
    integer = int.from_bytes(
        hashlib.sha256(f"{seed}|{scenario}|{turn}".encode()).digest()[:8], "big"
    )
    return (integer + 0.5) / 2**64


def verify_multi(result: dict[str, Any], records: list[dict[str, Any]]) -> None:
    rows = result["rows"]
    index = {
        (r["condition"], r["scenario"], r["history_mode"], r["selected_readout"], r["regime"]): r
        for r in rows
    }
    expected = set(itertools.product(CONDITIONS, SCENARIOS, HISTORIES, READOUTS, REGIMES))
    require(len(rows) == len(index) == result["trajectory_count"] == 896, "Trajectory closure")
    require(set(index) == expected, "Multi-turn dimensions changed")
    require(sum(len(r["turns"]) for r in rows) == result["turn_count"] == 3584, "Turn closure")
    require(result["independent_world_count"] == 2 and result["kv_cache"] is False, "World/KV")
    require(result["winner"] == "none" and result["semantic_promotion"] is False, "Promotion")
    memo: dict[Any, Any] = {}
    for key, row in index.items():
        condition, scenario, history, readout, regime = key
        world, side = int(scenario[1]), int(scenario[4])
        source = records[world]
        require(row["world_index"] == world and row["side"] == side, "Scenario coordinates")
        require(row["pair_id"] == source["metadata"]["pair_id"], "Scenario pair ID")
        seed = 0 if regime == "greedy" else int(regime.split("_")[1])
        temperature = 0.0 if regime == "greedy" else 0.7
        require(row["seed"] == seed and row["temperature"] == temperature, "Sampling regime")
        require(len(row["turns"]) == 4, "Four turns required")
        generated, appended = [], []
        for t, turn in enumerate(row["turns"]):
            query = QUERIES[t]
            original, donor = source["answers"][side][query], source["answers"][1 - side][query]
            require(turn["turn_index"] == t and turn["query_index"] == query, "Query schedule")
            require(turn["query_text"] == source["queries"][query], "Query text drift")
            require(turn["original_label"] == original and turn["donor_label"] == donor, "Labels")
            require(turn["affected"] == (original != donor), "Turn affected mask")
            require(turn["heldout"] == source["heldout_queries"][query], "Turn heldout mask")
            zero = row["model"] == "base" or row["control"] == "zero"
            check_dual(turn["dual_readout"], zero=zero)
            selected = turn["dual_readout"][readout]["scores"]
            require(turn["selected_scores"] == selected, "Selected head mismatch")
            expected_uniform = None if regime == "greedy" else uniform(seed, scenario, t)
            require(turn["matched_uniform"] == expected_uniform, "Matched uniform drift")
            scaled = [v / (temperature or 1.0) for v in selected]
            exp = [math.exp(v - max(scaled)) for v in scaled]
            probabilities = [v / sum(exp) for v in exp]
            require(
                all(
                    math.isclose(a, b, rel_tol=0, abs_tol=1e-15)
                    for a, b in zip(turn["selected_probabilities"], probabilities, strict=True)
                ),
                "Sampling probabilities mismatch",
            )
            choice = (
                int(selected[1] > selected[0])
                if expected_uniform is None
                else int(expected_uniform >= turn["selected_probabilities"][0])
            )
            require(turn["choice_label"] == choice, "Choice does not follow selected scores")
            target = donor if row["control"] == "twin" else original
            require(turn["target_label"] == target, "Turn target drift")
            require(turn["target_correct"] == (choice == target), "Target accuracy drift")
            require(turn["original_correct"] == (choice == original), "Original accuracy drift")
            require(turn["history_generated_labels_before_turn"] == generated, "Generated history")
            require(turn["history_appended_labels_before_turn"] == appended, "Appended history")
            history_label = original if history == HISTORIES[0] else choice
            require(turn["appended_history_label"] == history_label, "History-mode contract")
            generated.append(choice)
            appended.append(history_label)
            memo_key = (condition, scenario, turn["prefix_token_sha256"])
            observed = (turn["prefix_token_count"], turn["dual_readout"])
            require(memo.setdefault(memo_key, observed) == observed, "Same prefix changed scores")
            if row["control"] == "intact" and history == HISTORIES[0]:
                twin = index[(f"{row['model']}_twin", scenario, history, readout, regime)]["turns"][
                    t
                ]
                require(
                    (turn["prefix_token_sha256"], turn["prefix_token_count"])
                    == (twin["prefix_token_sha256"], twin["prefix_token_count"]),
                    "Fixed-history intact/twin prefixes differ",
                )
            if row["control"] == "zero":
                base = index[("base_query_only", scenario, history, readout, regime)]["turns"][t]
                require(turn["dual_readout"] == base["dual_readout"], "Zero/base multi scores")
                require(turn["prefix_token_sha256"] == base["prefix_token_sha256"], "Zero prefix")
        require(row["generated_labels"] == generated, "Generated labels disagree with turns")
        require(row["appended_history_labels"] == appended, "Appended labels disagree with turns")
        require(row["generated_text"] == [["no", "yes"][v] for v in generated], "Generated text")


def verify_training(report: dict[str, Any], plan: dict[str, Any], repo: Path, weights: bool) -> int:
    training = report["training"]
    require(set(training) == set(CELLS), "Training cell inventory")
    task, semantic = (training[c] for c in CELLS)
    require(task["initial_state_sha256"] == semantic["initial_state_sha256"], "Initial state drift")
    require(task["schedule_sha256"] == semantic["schedule_sha256"], "Schedule mismatch")
    contract = plan["training"]
    require(contract["steps"] == 256 and contract["save_steps"] == [128, 256], "Step budget")
    require(contract["batch_size"] == 16 and contract["seed"] == 47, "Batch/seed budget")
    schedule, rng = [], random.Random(47)
    examples = list(itertools.product(range(256), range(8)))
    while len(schedule) < 4096:
        epoch = list(examples)
        rng.shuffle(epoch)
        schedule.extend(epoch)
    require(task["schedule_sha256"] == stable_hash(schedule[:4096]), "Schedule recomputation")
    total_bytes = 0
    for cell, result in training.items():
        require(result["initial_state_sha256"] != result["final_state_sha256"], "No state update")
        require(result["writer_gradient_nonzero_after_step1"] is True, "Missing writer gradient")
        require(result["final_checkpoint_reload_exact"] is True, "Reload identity missing")
        rows = result["rows"]
        require(len(rows) == 256 and [r["step"] for r in rows] == list(range(1, 257)), "Train rows")
        for row in rows:
            require(row["loss_parameter_step"] == row["step"] - 1, "Loss/parameter step offset")
            require(row["world_query_count"] == 16, "Batch denominator")
            require(all(math.isfinite(v) for v in row.values()), "Nonfinite training receipt")
        saves = result["checkpoints"]
        require(len(saves) == 2, "Exactly two retained checkpoint receipts per condition required")
        require(
            [s["path"] for s in saves]
            == [f"{plan['output']}/{cell}_step{step}.pt" for step in (128, 256)],
            "Checkpoint path/step inventory changed",
        )
        require(
            result["trainable_parameters"] == task["trainable_parameters"], "Parameter mismatch"
        )
        for save in saves:
            require(0 < save["bytes"] < 100_000_000, "Bridge checkpoint unexpectedly large")
            require(len(save["sha256"]) == 64, "Missing checkpoint digest")
            total_bytes += save["bytes"]
            if weights:
                path = inside(repo, save["path"])
                require(path.stat().st_size == save["bytes"], "Checkpoint byte mismatch")
                require(digest(path) == save["sha256"], "Checkpoint hash mismatch")
    return total_bytes


def verify(bundle: Path, repo: Path, *, verify_weights: bool) -> dict[str, Any]:
    artifact_index = load(bundle / "ARTIFACT_INDEX.json")
    artifacts = artifact_index["artifacts"]
    by_path = {item["path"]: item for item in artifacts}
    require(len(artifacts) == len(by_path) > 0, "Empty/duplicate artifact index")
    for relative, artifact in by_path.items():
        path = inside(repo, relative)
        require(path.is_file() and not path.is_symlink(), f"Artifact absent: {relative}")
        require(path.stat().st_size == artifact["bytes"], f"Artifact byte mismatch: {relative}")
        require(digest(path) == artifact["sha256"], f"Artifact hash mismatch: {relative}")
    required = [
        bundle / "raw" / name
        for name in (
            "report.json",
            "single_step0.json",
            "single_task.json",
            "single_semantic.json",
            "multiturn.json",
        )
    ]
    required += [
        bundle / "BASE_IDENTITY_RECEIPT.json",
        repo / PLAN,
        Path(__file__).resolve(),
        bundle / "SUMMARY.json",
        repo / "scripts/summarize_v14_precision_bridge.py",
    ]
    require(all(str(path.relative_to(repo)) in by_path for path in required), "Unindexed evidence")
    plan = load(repo / PLAN)
    report, step0, task, semantic, multi = (load(path) for path in required[:5])
    require(report["status"] == "QUALIFIED_EXECUTION", "Formal run did not qualify")
    require(report["winner"] == "none" and report["semantic_promotion"] is False, "Promotion")
    require(plan["semantic_promotion"] is False, "Plan promotion")
    require(report["plan_sha256"] == digest(repo / PLAN), "Plan hash drift")
    require(report["source_identity"] == plan["source_identity"], "Source identity map drift")
    for relative, sha in report["source_identity"].items():
        require(digest(inside(repo, relative)) == sha, f"Source hash mismatch: {relative}")
    require(report["runtime"] == plan["expected_runtime"], "Runtime drift")
    require(report["base_state_sha256_before"] == report["base_state_sha256_after"], "Base mutated")
    require(
        report["base_unchanged"] is True and report["base_native_split_exact"] is True, "Base gate"
    )
    require(
        report["base_control"] == "independently_loaded_pinned_original_not_old_task_checkpoint",
        "Original model lane provenance",
    )
    data = {}
    for split, item in plan["data"].items():
        path = inside(repo, item["path"])
        require(digest(path) == item["sha256"], f"Data hash changed: {split}")
        data[split] = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    require(len(data["train"]) == 256 and len(data["eval"]) == 64, "Dataset count drift")
    audit = report["split_audit"]
    require(
        audit["train_world_pairs"] == 256 and audit["eval_world_pairs"] == 64, "Split denominator"
    )
    require(
        set(audit["overlaps"]) == {"pair_ids", "orders", "unordered_twins", "contexts"},
        "Split keys",
    )
    require(all(v == 0 for v in audit["overlaps"].values()), "Train/eval overlap")
    require(audit["entity_heldout"] is False, "Unsupported entity heldout claim")
    weights_bytes = verify_training(report, plan, repo, verify_weights)
    singles = {"step0": step0, "task": task, "semantic": semantic}
    indices = {
        name: verify_single(raw, data["eval"], step0=name == "step0")
        for name, raw in singles.items()
    }
    for key in indices["step0"]:
        require(
            indices["step0"][key]["base_dual_readout"]
            == indices["task"][key]["base_dual_readout"]
            == indices["semantic"][key]["base_dual_readout"],
            "Frozen base scores drift across learned cells",
        )
    verify_multi(multi, data["eval"])
    sys.path.insert(0, str(repo / "src"))
    sys.path.insert(0, str(repo / "scripts"))
    from v14_precision_bridge_eval import summarize_multiturn, summarize_single

    for name, raw in singles.items():
        rebuilt = summarize_single(raw["rows"])
        require(rebuilt == raw["summary"], f"Single summary drift: {name}")
        target = report["step0_summary"] if name == "step0" else report["single_summary"][name]
        require(rebuilt == target, f"Report single summary drift: {name}")
    rebuilt_multi = summarize_multiturn(multi["rows"])
    require(rebuilt_multi == multi["summary"] == report["multiturn_summary"], "Multi summary drift")
    from summarize_v14_precision_bridge import summarize

    require(summarize(bundle) == load(bundle / "SUMMARY.json"), "Post-hoc summary drift")
    base_identity = load(bundle / "BASE_IDENTITY_RECEIPT.json")
    require(
        base_identity["status"] == "QUALIFIED_EXECUTION", "Historical identity audit incomplete"
    )
    require(base_identity["contents_unchanged_after_rehash"] is True, "Historical input integrity")
    require(
        base_identity["gpu_used"] is False and base_identity["weight_write_or_delete"] is False,
        "Audit side effects",
    )
    require(
        digest(repo / "scripts/audit_v14_base_identity.py") == base_identity["audit_source_sha256"],
        "Audit source mismatch",
    )
    for cell in CELLS:
        observed = base_identity["cells"][cell]
        require(observed["tensor_count"] == 291, "Base identity tensor count")
        require(
            observed["changed_tensor_count"] == len(observed["changed_tensor_keys"]) == 234,
            "Changed tensor count",
        )
        require(
            observed["equal_tensor_count"] == len(observed["equal_tensor_keys"]) == 57,
            "Equal tensor count",
        )
        require(
            observed["dtype_pairs"] == [["torch.bfloat16", "torch.bfloat16"]], "Base identity dtype"
        )
    require(
        base_identity["interpretation"]["historical_base_is_pinned_original"] is False,
        "Historical base correction",
    )
    return {
        "format": "latent-workspace-v14-precision-bridge-bundle-verification-v1",
        "status": "PASS",
        "single_rows_per_cell": 6144,
        "single_cells": 3,
        "trajectories": 896,
        "turns": 3584,
        "checkpoint_count": 4,
        "checkpoint_bytes": weights_bytes,
        "checkpoint_payload_validation": "sha256_and_size"
        if verify_weights
        else "receipt_metadata_only",
        "artifact_hashes_checked": len(artifacts),
        "source_hashes_checked": len(report["source_identity"]),
        "step0_and_zero_exact_base": True,
        "maximum_delta_norm_bound": 1.0,
        "fixed_history_intact_twin_prefixes_equal": True,
        "matched_uniforms_recomputed": True,
        "summaries_recomputed": True,
        "winner": "none",
        "semantic_promotion": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=BUNDLE)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--verify-weights", action="store_true")
    args = parser.parse_args()
    try:
        result = verify(
            args.bundle.resolve(), args.repo.resolve(), verify_weights=args.verify_weights
        )
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        print(json.dumps({"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
