#!/usr/bin/env python3
"""Finalize the frozen V11 low-LR, new-seed robustness matrix."""

from __future__ import annotations

import argparse
import math
import re
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from finalize_v11_step4_promotion import (
    _delta_summary,
    _exact_metric_sequence,
    learning_rate_chain,
    promotion_gate_evaluation,
)
from finalize_v11_update_response_surface import (
    BEHAVIOR_FORMAT,
    EVAL_KEYS,
    PREUPDATE_KEYS,
    FinalizeError,
    atomic_write,
    behavior_evaluation,
    load_json,
    load_jsonl,
    metric_view,
    one_row,
    plain_directory,
    regular_file,
    relative,
    repo_path,
    sha256_file,
    stable_hash,
)

FORMAT = "latent-workspace-ft-v11-seed-robustness-receipt-v1"
CONTRACT_FORMAT = "latent-workspace-ft-v11-seed-robustness-contract-v1"
PROMOTION_FORMAT = "latent-workspace-ft-v11-step4-promotion-receipt-v1"


def _metric_summary(values: list[float]) -> dict[str, float]:
    return {
        "minimum": min(values),
        "maximum": max(values),
        "mean": statistics.fmean(values),
        "sample_standard_deviation": statistics.stdev(values),
    }


def build_learning_rate_summary(
    learning_rate_id: str,
    learning_rate: float,
    cells: list[dict[str, Any]],
    required_seeds: list[int],
) -> dict[str, Any]:
    observed_seeds = sorted(int(cell["seed"]) for cell in cells)
    if observed_seeds != sorted(required_seeds):
        raise FinalizeError(f"Seed coverage differs for {learning_rate_id}.")
    choice_losses = [float(cell["final_metrics"]["functional_choice_loss"]) for cell in cells]
    full_vocab_losses = [
        float(cell["final_metrics"]["functional_full_vocab_loss"]) for cell in cells
    ]
    accuracies = [float(cell["final_metrics"]["functional_query_accuracy"]) for cell in cells]
    minimum_recalls = [
        min(
            float(cell["final_metrics"]["functional_label_0_recall"]),
            float(cell["final_metrics"]["functional_label_1_recall"]),
        )
        for cell in cells
    ]
    behavior_accuracies = [float(cell["behavior"]["task_accuracy"]) for cell in cells]
    changed_fractions = [float(cell["delta"]["changed_element_fraction"]) for cell in cells]
    robust = all(bool(cell["eligible"]) for cell in cells)
    return {
        "learning_rate_id": learning_rate_id,
        "learning_rate": learning_rate,
        "seeds": observed_seeds,
        "passed_seeds": [int(cell["seed"]) for cell in cells if cell["eligible"]],
        "passed_seed_fraction": sum(bool(cell["eligible"]) for cell in cells) / len(cells),
        "robust": robust,
        "worst_seed_behavior_task_accuracy": min(behavior_accuracies),
        "worst_seed_complete_eval_accuracy": min(accuracies),
        "worst_seed_minimum_label_recall": min(minimum_recalls),
        "worst_seed_choice_loss": max(choice_losses),
        "metrics": {
            "choice_loss": _metric_summary(choice_losses),
            "full_vocab_loss": _metric_summary(full_vocab_losses),
            "complete_eval_accuracy": _metric_summary(accuracies),
            "minimum_label_recall": _metric_summary(minimum_recalls),
            "behavior_task_accuracy": _metric_summary(behavior_accuracies),
            "changed_element_fraction": _metric_summary(changed_fractions),
        },
    }


def selection_key(summary: dict[str, Any]) -> tuple[float, ...]:
    return (
        -float(summary["worst_seed_behavior_task_accuracy"]),
        -float(summary["worst_seed_complete_eval_accuracy"]),
        -float(summary["worst_seed_minimum_label_recall"]),
        float(summary["worst_seed_choice_loss"]),
        float(summary["metrics"]["choice_loss"]["mean"]),
        float(summary["learning_rate"]),
    )


def _run_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "metrics": regular_file(output_dir / "metrics.jsonl", label="metrics"),
        "resolved_config": regular_file(
            output_dir / "resolved_config.json", label="resolved config"
        ),
        "environment": regular_file(output_dir / "environment.json", label="environment"),
        "optimizer_coverage": regular_file(
            output_dir / "optimizer_coverage.json", label="optimizer coverage"
        ),
        "base_update_coverage": regular_file(
            output_dir / "base_update_coverage.json", label="base update coverage"
        ),
        "offload": regular_file(output_dir / "gradient_accumulation_offload.json", label="offload"),
        "manifest": regular_file(output_dir / "final" / "manifest.json", label="manifest"),
        "experiment_config": regular_file(
            output_dir / "final" / "experiment_config.json",
            label="experiment config",
        ),
        "completed": regular_file(output_dir / "final" / "COMPLETED", label="COMPLETED"),
    }


def _train_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "step": int(row["step"]),
        "functional_choice_loss": float(row["functional_choice_loss"]),
        "functional_full_vocab_loss": float(row["functional_full_vocab_loss"]),
        "functional_query_accuracy": float(row["functional_query_accuracy"]),
        "functional_label_0_recall": float(row["functional_label_0_recall"]),
        "functional_label_1_recall": float(row["functional_label_1_recall"]),
        "grad_norm": float(row["grad_norm"]),
        "base_grad_norm": float(row["base_grad_norm"]),
        "base_clip_coefficient": float(row["base_clip_coefficient"]),
        "applied_lr_base": float(row["applied_lr_base"]),
        "post_scheduler_lr_base": float(row["lr_base"]),
        "window_metrics_phase": row["window_metrics_phase"],
    }


def _finalize_cell(
    *,
    root: Path,
    contract_path: Path,
    condition_id: str,
    artifact: dict[str, Any],
    initial_snapshot: Path,
    behavior_models: dict[str, Any],
    behavior_veto: dict[str, Any],
    cell_gates: dict[str, Any],
    expected_step0: dict[str, Any],
    expected_runtime_source: str,
) -> dict[str, Any]:
    config_path = regular_file(
        (contract_path.parent / str(artifact["path"])).resolve(),
        label=f"{condition_id} config",
    )
    if sha256_file(config_path) != str(artifact["sha256"]):
        raise FinalizeError(f"Frozen config changed for {condition_id}.")
    config = load_json(config_path)
    train_config = config["train"]
    learning_rate = float(artifact["learning_rate"])
    seed = int(artifact["seed"])
    frozen_config_checks = {
        "learning_rate": float(train_config["learning_rate"]) == learning_rate,
        "seed": int(train_config["seed"]) == seed,
        "max_steps": int(train_config["max_steps"]) == 4,
        "eval_at_start": train_config.get("eval_at_start") is True,
        "eval_every": int(train_config["eval_every"]) == 1,
        "eval_batches": int(train_config["eval_batches"]) == 0,
        "save_every": int(train_config["save_every"]) == 0,
    }
    if not all(frozen_config_checks.values()):
        raise FinalizeError(f"Frozen config fields changed for {condition_id}.")

    output_dir = (config_path.parent / str(train_config["output_dir"])).resolve()
    try:
        output_dir.relative_to(root)
    except ValueError as exc:
        raise FinalizeError(f"Run output escapes repo for {condition_id}.") from exc
    output_dir = plain_directory(output_dir, label=f"{condition_id} run")
    paths = _run_paths(output_dir)
    metrics = load_jsonl(paths["metrics"])
    _exact_metric_sequence(metrics)
    step0 = metric_view(one_row(metrics, split="eval-step0", step=0))
    train_rows = [one_row(metrics, split="train", step=step) for step in range(1, 5)]
    eval_rows = [metric_view(one_row(metrics, split="eval", step=step)) for step in range(1, 5)]
    final_eval = metric_view(one_row(metrics, split="eval-final", step=4))
    if final_eval != eval_rows[-1]:
        raise FinalizeError(f"Eval/eval-final mismatch for {condition_id}.")
    if step0 != expected_step0:
        raise FinalizeError(f"Step-0 differs from qualified baseline for {condition_id}.")
    if any(
        not math.isfinite(float(row[key]))
        for row in (step0, *eval_rows)
        for key in EVAL_KEYS
        if key != "functional_distinct_predicted_classes"
    ):
        raise FinalizeError(f"Non-finite decision metric for {condition_id}.")
    if any(row.get("window_metrics_phase") != "pre_update_forward" for row in train_rows):
        raise FinalizeError(f"Ambiguous train metric phase for {condition_id}.")

    resolved = load_json(paths["resolved_config"])
    final_config = load_json(paths["experiment_config"])
    environment = load_json(paths["environment"])
    optimizer_coverage = load_json(paths["optimizer_coverage"])
    base_coverage = load_json(paths["base_update_coverage"])
    offload = load_json(paths["offload"])
    manifest = load_json(paths["manifest"])
    source_hashes = {
        str(environment.get("source_sha256")),
        str(offload.get("source_sha256")),
        str(manifest.get("source_sha256")),
    }
    applied_lrs = {
        float(parameter["learning_rate"]) for parameter in base_coverage.get("parameters", [])
    }
    base_checks = base_coverage.get("checks", {})
    lr_chain = learning_rate_chain(train_rows, learning_rate)
    integrity_checks = [
        {
            "id": "resolved_final_config_exact",
            "passed": resolved == final_config,
            "observed": resolved == final_config,
        },
        {
            "id": "manifest_config_binding",
            "passed": stable_hash(final_config) == manifest.get("config_sha256"),
            "observed": stable_hash(final_config),
            "expected": manifest.get("config_sha256"),
        },
        {
            "id": "complete_four_step_bundle",
            "passed": (
                manifest.get("complete") is True
                and int(manifest.get("global_step", -1)) == 4
                and paths["completed"].read_text(encoding="utf-8") == "ok\n"
            ),
            "observed": {
                "complete": manifest.get("complete"),
                "global_step": manifest.get("global_step"),
            },
        },
        {
            "id": "runtime_source_binding",
            "passed": source_hashes == {expected_runtime_source},
            "observed": sorted(source_hashes),
            "expected": expected_runtime_source,
        },
        {
            "id": "optimizer_coverage",
            "passed": optimizer_coverage.get("passed") is True,
            "observed": optimizer_coverage.get("checks"),
        },
        {
            "id": "base_update_coverage",
            "passed": bool(base_checks)
            and all(value is True for value in base_checks.values())
            and applied_lrs == {learning_rate},
            "observed": {
                "checks": base_checks,
                "coverage_learning_rates": sorted(applied_lrs),
            },
        },
        {
            "id": "learning_rate_schedule_continuity",
            "passed": lr_chain["passed"],
            "observed": lr_chain,
        },
        {
            "id": "cpu_accumulate_complete",
            "passed": (
                offload.get("status") == "completed"
                and int(offload.get("windows_started", -1)) == 4
                and int(offload.get("windows_restored", -1)) == 4
                and int(offload.get("microbatch_spills", -1)) == 32
                and int(offload.get("live_cpu_buffer_count", -1)) == 0
                and offload.get("active_window") is None
            ),
            "observed": {
                "status": offload.get("status"),
                "windows_started": offload.get("windows_started"),
                "windows_restored": offload.get("windows_restored"),
                "microbatch_spills": offload.get("microbatch_spills"),
            },
        },
    ]
    if not all(bool(check["passed"]) for check in integrity_checks):
        failed = [check["id"] for check in integrity_checks if not check["passed"]]
        raise FinalizeError(f"Integrity failed for {condition_id}: {failed}")

    delta = _delta_summary(initial_snapshot, output_dir / "final" / "base_model")
    if condition_id not in behavior_models:
        raise FinalizeError(f"Behavior capture omitted {condition_id}.")
    behavior = behavior_evaluation(behavior_models[condition_id], behavior_veto)
    promotion_checks = promotion_gate_evaluation(
        step0,
        final_eval,
        behavior_passed=bool(behavior["passed"]),
        gates=cell_gates,
    )
    eligible = all(bool(check["passed"]) for check in promotion_checks)
    return {
        "condition_id": condition_id,
        "learning_rate_id": artifact["learning_rate_id"],
        "learning_rate": learning_rate,
        "seed": seed,
        "run": {
            "path": relative(root, output_dir),
            "run_id": manifest.get("run_id"),
            "runtime_source_sha256": manifest.get("source_sha256"),
            "artifact_hashes": {name: sha256_file(path) for name, path in paths.items()},
        },
        "frozen_config_checks": frozen_config_checks,
        "integrity_status": "PASS",
        "integrity_checks": integrity_checks,
        "step0": step0,
        "first_pre_update_window": metric_view(train_rows[0], PREUPDATE_KEYS),
        "train_curve": [_train_view(row) for row in train_rows],
        "evaluation_curve": [
            {"step": step, "metrics": row} for step, row in enumerate(eval_rows, start=1)
        ],
        "final_metrics": final_eval,
        "applied_learning_rate_schedule": lr_chain,
        "delta": delta,
        "behavior": behavior,
        "cell_checks": promotion_checks,
        "eligible": eligible,
    }


def _paired_deltas(cells: list[dict[str, Any]], seeds: list[int]) -> list[dict[str, Any]]:
    by_key = {(str(cell["learning_rate_id"]), int(cell["seed"])): cell for cell in cells}
    rows: list[dict[str, Any]] = []
    for seed in seeds:
        lower = by_key[("lr_1e_7", seed)]
        higher = by_key[("lr_2e_7", seed)]
        lower_metrics = lower["final_metrics"]
        higher_metrics = higher["final_metrics"]
        rows.append(
            {
                "seed": seed,
                "direction": "lr_1e_7_minus_lr_2e_7",
                "choice_loss": float(lower_metrics["functional_choice_loss"])
                - float(higher_metrics["functional_choice_loss"]),
                "full_vocab_loss": float(lower_metrics["functional_full_vocab_loss"])
                - float(higher_metrics["functional_full_vocab_loss"]),
                "complete_eval_accuracy": float(lower_metrics["functional_query_accuracy"])
                - float(higher_metrics["functional_query_accuracy"]),
                "minimum_label_recall": min(
                    float(lower_metrics["functional_label_0_recall"]),
                    float(lower_metrics["functional_label_1_recall"]),
                )
                - min(
                    float(higher_metrics["functional_label_0_recall"]),
                    float(higher_metrics["functional_label_1_recall"]),
                ),
                "behavior_task_accuracy": float(lower["behavior"]["task_accuracy"])
                - float(higher["behavior"]["task_accuracy"]),
                "changed_element_fraction": float(lower["delta"]["changed_element_fraction"])
                - float(higher["delta"]["changed_element_fraction"]),
            }
        )
    return rows


def finalize(args: argparse.Namespace) -> dict[str, Any]:
    root = plain_directory(args.repo_root.expanduser().resolve(), label="repo root")
    contract_path = regular_file(repo_path(root, args.contract, label="contract"), label="contract")
    behavior_path = regular_file(
        repo_path(root, args.behavior_receipt, label="behavior receipt"),
        label="behavior receipt",
    )
    initial_snapshot = plain_directory(
        args.initial_snapshot.expanduser().resolve(), label="initial snapshot"
    )
    contract = load_json(contract_path)
    behavior_receipt = load_json(behavior_path)
    if contract.get("format") != CONTRACT_FORMAT:
        raise FinalizeError("Unexpected seed-robustness contract format.")
    if (
        behavior_receipt.get("format") != BEHAVIOR_FORMAT
        or behavior_receipt.get("status") != "PASS"
    ):
        raise FinalizeError("Behavior capture did not complete with PASS integrity.")
    if re.fullmatch(r"[0-9a-f]{40}", args.source_commit) is None:
        raise FinalizeError("--source-commit must be a full lowercase Git commit.")

    verified_design_inputs: dict[str, dict[str, str]] = {}
    for label, binding in (
        ("parent_contract", contract["prior_selected_baseline"]["contract"]),
        ("surface_receipt", contract["prior_selected_baseline"]["surface_receipt"]),
        (
            "promotion_behavior",
            contract["prior_selected_baseline"]["promotion_behavior"],
        ),
        ("train_data", contract["data"]["train"]),
        ("eval_data", contract["data"]["eval"]),
    ):
        path = regular_file((contract_path.parent / str(binding["path"])).resolve(), label=label)
        observed = sha256_file(path)
        if observed != str(binding["sha256"]):
            raise FinalizeError(f"Pinned design input changed: {label}.")
        verified_design_inputs[label] = {
            "path": relative(root, path),
            "sha256": observed,
        }

    prior_binding = contract["prior_selected_baseline"]["promotion_receipt"]
    prior_path = regular_file(
        (contract_path.parent / str(prior_binding["path"])).resolve(),
        label="prior promotion receipt",
    )
    if sha256_file(prior_path) != str(prior_binding["sha256"]):
        raise FinalizeError("Prior promotion receipt changed.")
    prior = load_json(prior_path)
    if (
        prior.get("format") != PROMOTION_FORMAT
        or prior.get("integrity_status") != "PASS"
        or prior.get("scientific_status") != "PROMOTED"
        or prior.get("v11_baseline_ready") is not True
    ):
        raise FinalizeError("Prior seed-42 baseline is not a qualified design input.")
    expected_step0 = prior["evaluation_curve"]["step0"]
    expected_runtime_source = str(prior["run"]["runtime_source_sha256"])
    behavior_models = behavior_receipt.get("models")
    if not isinstance(behavior_models, dict):
        raise FinalizeError("Behavior receipt has no models mapping.")
    condition_order = contract["execution"]["condition_order"]
    if set(contract["artifacts"]) != set(condition_order):
        raise FinalizeError("Contract artifact set differs from execution order.")
    if set(behavior_models) != {"original", *condition_order}:
        raise FinalizeError("Behavior model set differs from the frozen matrix.")
    prompt_binding = contract["behavior_veto"]["prompt_suite"]
    prompt_path = regular_file(
        (contract_path.parent / str(prompt_binding["path"])).resolve(),
        label="behavior prompt suite",
    )
    if sha256_file(prompt_path) != str(prompt_binding["sha256"]):
        raise FinalizeError("Behavior prompt suite changed.")
    behavior_prompt = behavior_receipt.get("prompt_suite", {})
    behavior_capture = behavior_receipt.get("capture", {})
    behavior_decoding = behavior_receipt.get("decoding", {}).get("freeform", {})
    original_binding = behavior_models["original"].get("binding", {})
    behavior_binding_checks = {
        "prompt_suite_sha256": behavior_prompt.get("sha256") == prompt_binding["sha256"],
        "task_dataset_sha256": behavior_prompt.get("task_dataset_sha256")
        == contract["data"]["eval"]["sha256"],
        "capture_seed": int(behavior_capture.get("seed", -1))
        == int(contract["behavior_veto"]["capture_seed"]),
        "max_new_tokens": int(behavior_decoding.get("max_new_tokens", -1))
        == int(contract["behavior_veto"]["max_new_tokens"]),
        "greedy_decoding": behavior_decoding.get("do_sample") is False,
        "original_model_id": original_binding.get("model_id") == contract["model"]["name_or_path"],
        "original_revision": original_binding.get("revision") == contract["model"]["revision"],
    }
    if not all(behavior_binding_checks.values()):
        failed = [key for key, passed in behavior_binding_checks.items() if not passed]
        raise FinalizeError(f"Behavior binding failed: {failed}")

    cells: list[dict[str, Any]] = []
    for condition_id in condition_order:
        artifact = contract["artifacts"][condition_id]
        cells.append(
            _finalize_cell(
                root=root,
                contract_path=contract_path,
                condition_id=condition_id,
                artifact=artifact,
                initial_snapshot=initial_snapshot,
                behavior_models=behavior_models,
                behavior_veto=contract["behavior_veto"],
                cell_gates=contract["cell_gates"],
                expected_step0=expected_step0,
                expected_runtime_source=expected_runtime_source,
            )
        )

    step0_hashes = {stable_hash(cell["step0"]) for cell in cells}
    if len(step0_hashes) != 1:
        raise FinalizeError("Step-0 metrics differ across robustness cells.")
    preupdate_pair_hashes: dict[str, str] = {}
    for seed in contract["matched_design"]["new_seeds"]:
        pair = [cell for cell in cells if int(cell["seed"]) == int(seed)]
        hashes = {stable_hash(cell["first_pre_update_window"]) for cell in pair}
        if len(pair) != 2 or len(hashes) != 1:
            raise FinalizeError(f"Pre-update matched pair differs for seed {seed}.")
        preupdate_pair_hashes[str(seed)] = next(iter(hashes))

    required_seeds = [
        int(seed) for seed in contract["learning_rate_robustness_gate"]["required_new_seeds"]
    ]
    summaries: list[dict[str, Any]] = []
    for row in contract["matched_design"]["learning_rates"]:
        learning_rate_id = str(row["id"])
        lr_cells = [cell for cell in cells if cell["learning_rate_id"] == learning_rate_id]
        summaries.append(
            build_learning_rate_summary(
                learning_rate_id,
                float(row["value"]),
                lr_cells,
                required_seeds,
            )
        )
    robust = [summary for summary in summaries if summary["robust"]]
    ranked = sorted(robust, key=selection_key)
    selected = ranked[0] if ranked else None
    return {
        "format": FORMAT,
        "schema_version": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "integrity_status": "PASS",
        "scientific_status": ("ROBUST_BASELINE_SELECTED" if selected is not None else "BLOCKED"),
        "candidate_f1_baseline_ready": selected is not None,
        "question": contract["question"],
        "contract": {
            "path": relative(root, contract_path),
            "sha256": sha256_file(contract_path),
        },
        "source_commit_at_launch": args.source_commit,
        "runtime_source_sha256": expected_runtime_source,
        "behavior_receipt": {
            "path": relative(root, behavior_path),
            "sha256": sha256_file(behavior_path),
            "binding_checks": behavior_binding_checks,
        },
        "verified_design_inputs": verified_design_inputs,
        "prior_seed42_context": {
            "receipt_path": relative(root, prior_path),
            "receipt_sha256": sha256_file(prior_path),
            "excluded_from_robustness_aggregation": True,
        },
        "matched_integrity": {
            "exact_step0_metrics_sha256": next(iter(step0_hashes)),
            "exact_first_pre_update_window_sha256_by_seed": preupdate_pair_hashes,
            "new_seeds": required_seeds,
        },
        "cells": cells,
        "learning_rate_summaries": summaries,
        "paired_deltas": _paired_deltas(cells, required_seeds),
        "robust_learning_rate_ids": [summary["learning_rate_id"] for summary in ranked],
        "selected_learning_rate_id": (
            selected["learning_rate_id"] if selected is not None else None
        ),
        "selected_learning_rate": (selected["learning_rate"] if selected is not None else None),
        "next_contract_design_authorized": selected is not None,
        "further_training_or_o0_execution_authorized": False,
        "claim_boundary": contract["claim_boundary"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument(
        "--contract", type=Path, default=Path("configs/v11/SEED_ROBUSTNESS_CONTRACT.json")
    )
    parser.add_argument("--behavior-receipt", type=Path, required=True)
    parser.add_argument("--initial-snapshot", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.repo_root.expanduser().resolve()
    output = repo_path(root, args.output, label="output")
    try:
        receipt = finalize(args)
        atomic_write(output, receipt, overwrite=args.overwrite)
    except Exception as exc:
        message = str(exc) if isinstance(exc, FinalizeError) else type(exc).__name__
        print(f"ERROR: {message}", file=sys.stderr)
        return 2
    print(f"WROTE {relative(root, output)}")
    print(f"scientific_status={receipt['scientific_status']}")
    print(f"selected_learning_rate_id={receipt['selected_learning_rate_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
