#!/usr/bin/env python3
"""Finalize the frozen V11 F1-versus-O0 stage-4 and refinement comparison."""

from __future__ import annotations

import argparse
import math
import re
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from finalize_v11_step4_promotion import _delta_summary, promotion_gate_evaluation
from finalize_v11_update_response_surface import (
    BEHAVIOR_FORMAT,
    EVAL_KEYS,
    PREUPDATE_KEYS,
    FinalizeError,
    atomic_write,
    behavior_evaluation,
    completion_diagnostics,
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

CONTRACT_FORMAT = "latent-workspace-ft-v11-f1-o0-refinement-contract-v1"
STAGE4_FORMAT = "latent-workspace-ft-v11-f1-o0-stage4-receipt-v1"
REFINEMENT_FORMAT = "latent-workspace-ft-v11-f1-o0-refinement-receipt-v1"
V12_FORMAT = "latent-workspace-ft-v12-design-decision-v1"
PRIOR_F1_FORMAT = "latent-workspace-ft-v11-seed-robustness-receipt-v1"
NECESSITY_FORMAT = "latent-workspace-v9-functional-necessity-v1"
ROUTES = ("F1", "O0")


def exact_metric_sequence(
    rows: list[dict[str, Any]],
    *,
    max_steps: int,
    eval_every: int,
    amputated: bool,
) -> None:
    """Require the exact frozen metric row sequence and no hidden extra events."""
    expected: list[tuple[str, int]] = [("eval-step0", 0)]
    for step in range(1, max_steps + 1):
        expected.append(("train", step))
        if step % eval_every == 0:
            expected.append(("eval", step))
    expected.append(("eval-final", max_steps))
    if amputated:
        expected.append(("eval-final-amputated", max_steps))
    event_rows = [row for row in rows if "split" not in row]
    if (
        len(event_rows) != 1
        or rows[0] is not event_rows[0]
        or event_rows[0].get("event") != "start"
        or int(event_rows[0].get("step", -1)) != 0
    ):
        raise FinalizeError("Metrics must contain exactly one leading step-0 start event.")
    try:
        observed = [(str(row["split"]), int(row["step"])) for row in rows if "split" in row]
    except (KeyError, TypeError, ValueError) as exc:
        raise FinalizeError("Metrics contain malformed split/step fields.") from exc
    if observed != expected:
        raise FinalizeError(f"Metric sequence differs from the frozen {max_steps}-step design.")


def schedule_chain(
    rows: list[dict[str, Any]],
    *,
    configured: float,
    applied_key: str,
    post_key: str,
    max_steps: int,
) -> dict[str, Any]:
    """Describe exact continuity from applied LR to the next scheduled LR."""
    try:
        applied = [float(row[applied_key]) for row in rows]
        post = [float(row[post_key]) for row in rows]
    except (KeyError, TypeError, ValueError) as exc:
        raise FinalizeError(f"Training rows lack a valid {applied_key}/{post_key} chain.") from exc
    adjacent = all(applied[index] == post[index - 1] for index in range(1, len(rows)))
    passed = bool(
        len(rows) == max_steps
        and applied[0] == configured
        and all(value > 0.0 for value in applied)
        and adjacent
        and post[-1] == 0.0
    )
    return {
        "passed": passed,
        "configured_learning_rate": configured,
        "applied_learning_rates": applied,
        "post_scheduler_learning_rates": post,
        "adjacent_schedule_continuity": adjacent,
    }


def _minimum_recall(metrics: dict[str, Any]) -> float:
    return min(
        float(metrics["functional_label_0_recall"]),
        float(metrics["functional_label_1_recall"]),
    )


def paired_noninferiority(
    f1: dict[str, Any],
    o0: dict[str, Any],
    margins: dict[str, Any],
) -> dict[str, Any]:
    """Apply the frozen one-sided O0-versus-paired-F1 margins."""
    comparisons = [
        {
            "id": "behavior_task_accuracy",
            "f1": float(f1["behavior"]["task_accuracy"]),
            "o0": float(o0["behavior"]["task_accuracy"]),
            "margin": float(margins["behavior_task_accuracy"]),
        },
        {
            "id": "complete_eval_accuracy",
            "f1": float(f1["final_metrics"]["functional_query_accuracy"]),
            "o0": float(o0["final_metrics"]["functional_query_accuracy"]),
            "margin": float(margins["complete_eval_accuracy"]),
        },
        {
            "id": "minimum_label_recall",
            "f1": _minimum_recall(f1["final_metrics"]),
            "o0": _minimum_recall(o0["final_metrics"]),
            "margin": float(margins["minimum_label_recall"]),
        },
    ]
    for row in comparisons:
        row["o0_minus_f1"] = row["o0"] - row["f1"]
        row["criterion"] = f"O0 >= F1 - {row['margin']}"
        row["passed"] = row["o0"] >= row["f1"] - row["margin"]
    return {"passed": all(bool(row["passed"]) for row in comparisons), "checks": comparisons}


def choose_v12_design(
    *,
    f1_robust: bool,
    o0_robust: bool,
    o0_competitive: bool,
    content_specific_replicated: bool,
) -> dict[str, str]:
    """Resolve the mutually exclusive V12 handoff frozen before execution."""
    if not f1_robust and not o0_robust:
        return {
            "rule_id": "repair_shared_optimizer",
            "v12_focus": "repair shared long-horizon optimizer dynamics before architecture claims",
        }
    if o0_competitive and content_specific_replicated:
        return {
            "rule_id": "scale_content_specific_o0",
            "v12_focus": "scale and efficiency while preserving intervention receipts",
        }
    if o0_competitive:
        return {
            "rule_id": "sharpen_semantics",
            "v12_focus": "separate semantic content from nonzero carrier availability",
        }
    if content_specific_replicated:
        return {
            "rule_id": "stabilize_active_route",
            "v12_focus": "optimize ownership, warm start, gating, and LR curriculum",
        }
    if f1_robust:
        return {
            "rule_id": "redesign_route",
            "v12_focus": "redesign injection and workspace training before scale-up",
        }
    raise FinalizeError("Frozen V12 rules did not cover the observed state.")


def necessity_summary(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("format") != NECESSITY_FORMAT:
        raise FinalizeError("Unexpected functional necessity receipt format.")
    ladder = value.get("evidence_ladder")
    if not isinstance(ladder, dict):
        raise FinalizeError("Necessity receipt has no evidence ladder.")
    required = (
        "F0_engineering",
        "F1_deferred_sufficiency",
        "F2_carrier_insufficiency",
        "F3_counterfactual_direction",
        "F4_local_causal_specificity",
        "F5_heldout_query_generalization",
    )
    if set(ladder) != set(required):
        raise FinalizeError("Necessity evidence ladder differs from F0-F5.")
    passed = {name: bool(ladder[name].get("passed")) for name in required}
    if not passed["F0_engineering"]:
        raise FinalizeError("Necessity engineering intervention coverage failed.")
    modes = value.get("modes")
    required_modes = {
        "intact",
        "hard_bypass",
        "zero",
        "global_mean",
        "fixed_carrier",
        "norm_matched_random",
        "token_shuffle",
        "counterfactual_twin",
        "cross_world_shuffle",
    }
    if not isinstance(modes, list) or set(str(mode) for mode in modes) != required_modes:
        raise FinalizeError("Necessity intervention modes differ from the full frozen set.")
    content_specific = bool(
        passed["F3_counterfactual_direction"] and passed["F4_local_causal_specificity"]
    )
    return {
        "passed_by_level": passed,
        "primary_gate_passed": bool(value.get("primary_gate_passed")),
        "content_specific": content_specific,
        "classification": (
            "content_specific" if content_specific else "carrier_or_route_only_not_content_specific"
        ),
        "evidence_ladder": ladder,
        "modes": modes,
        "effects": value.get("effects"),
        "claim_boundary": value.get("claim_boundary"),
    }


def _train_view(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "functional_choice_loss",
        "functional_full_vocab_loss",
        "functional_query_accuracy",
        "functional_label_0_recall",
        "functional_label_1_recall",
        "grad_norm",
        "base_grad_norm",
        "workspace_grad_norm",
        "base_clip_coefficient",
        "workspace_clip_coefficient",
        "applied_lr_base",
        "applied_lr_workspace",
        "lr_base",
        "lr_workspace",
        "window_metrics_phase",
    )
    missing = [key for key in keys if key not in row]
    if missing:
        raise FinalizeError(f"Training metric row is missing required keys: {missing}")
    result = {key: row[key] for key in keys}
    result["step"] = int(row["step"])
    return result


def _run_paths(output_dir: Path, *, route: str) -> dict[str, Path]:
    paths = {
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
            output_dir / "final" / "experiment_config.json", label="experiment config"
        ),
        "completed": regular_file(output_dir / "final" / "COMPLETED", label="COMPLETED"),
        "workspace_state": regular_file(
            output_dir / "final" / "workspace_state.pt", label="workspace state"
        ),
    }
    amputation_path = output_dir / "amputation_report.json"
    if route == "O0":
        paths["amputation_report"] = regular_file(amputation_path, label="amputation report")
    elif amputation_path.exists():
        raise FinalizeError("F1 run unexpectedly contains an amputation report.")
    return paths


def _verify_binding(
    *,
    root: Path,
    contract_path: Path,
    binding: dict[str, Any],
    label: str,
) -> dict[str, str]:
    path = regular_file((contract_path.parent / str(binding["path"])).resolve(), label=label)
    digest = sha256_file(path)
    if digest != str(binding["sha256"]):
        raise FinalizeError(f"Pinned input changed: {label}.")
    return {"path": relative(root, path), "sha256": digest}


def _validate_behavior_receipt(
    *,
    receipt: dict[str, Any],
    contract: dict[str, Any],
    stage: dict[str, Any],
    expected_models: set[str],
) -> tuple[dict[str, Any], dict[str, bool]]:
    if receipt.get("format") != BEHAVIOR_FORMAT or receipt.get("status") != "PASS":
        raise FinalizeError("Behavior capture did not complete with PASS integrity.")
    models = receipt.get("models")
    if not isinstance(models, dict) or set(models) != expected_models:
        raise FinalizeError("Behavior model set differs from the frozen stage.")
    prompt = receipt.get("prompt_suite", {})
    capture = receipt.get("capture", {})
    decoding = receipt.get("decoding", {}).get("freeform", {})
    original = models["original"].get("binding", {})
    checks = {
        "prompt_suite_sha256": prompt.get("sha256")
        == contract["behavior_veto"]["prompt_suite"]["sha256"],
        "task_dataset_sha256": prompt.get("task_dataset_sha256")
        == contract["data"]["eval"]["sha256"],
        "capture_seed": int(capture.get("seed", -1))
        == int(stage["behavior_capture"]["capture_seed"]),
        "max_new_tokens": int(decoding.get("max_new_tokens", -1))
        == int(stage["behavior_capture"]["max_new_tokens"]),
        "greedy_decoding": decoding.get("do_sample") is False,
        "original_model_id": original.get("model_id") == contract["model"]["name_or_path"],
        "original_revision": original.get("revision") == contract["model"]["revision"],
    }
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise FinalizeError(f"Behavior binding failed: {failed}")
    return models, checks


def _amputation_summary(
    report: dict[str, Any],
    *,
    final_eval: dict[str, Any],
    amputated_eval: dict[str, Any],
    max_steps: int,
) -> dict[str, Any]:
    if int(report.get("step", -1)) != max_steps:
        raise FinalizeError("Amputation report step differs from the final step.")
    full = report.get("full")
    amputated = report.get("amputated")
    if not isinstance(full, dict) or not isinstance(amputated, dict):
        raise FinalizeError("Amputation report lacks full/amputated metric objects.")
    if metric_view(full) != final_eval or metric_view(amputated) != amputated_eval:
        raise FinalizeError("Amputation report does not bind to final metric rows.")
    return {
        "intact": final_eval,
        "amputated": amputated_eval,
        "intact_minus_amputated": {
            "choice_loss": float(final_eval["functional_choice_loss"])
            - float(amputated_eval["functional_choice_loss"]),
            "full_vocab_loss": float(final_eval["functional_full_vocab_loss"])
            - float(amputated_eval["functional_full_vocab_loss"]),
            "complete_eval_accuracy": float(final_eval["functional_query_accuracy"])
            - float(amputated_eval["functional_query_accuracy"]),
            "minimum_label_recall": _minimum_recall(final_eval) - _minimum_recall(amputated_eval),
        },
        "task_loss_delta_full_minus_amputated": report.get("task_loss_delta_full_minus_amputated"),
    }


def _finalize_cell(
    *,
    root: Path,
    contract_path: Path,
    condition_id: str,
    artifact: dict[str, Any],
    initial_snapshot: Path,
    behavior_model: dict[str, Any],
    behavior_veto: dict[str, Any],
    cell_gates: dict[str, Any],
    expected_runtime_source: str,
) -> dict[str, Any]:
    route = str(artifact["route_id"])
    seed = int(artifact["seed"])
    max_steps = int(artifact["max_steps"])
    eval_every = int(artifact["eval_every"])
    base_lr = float(artifact["base_learning_rate"])
    workspace_lr = float(artifact["workspace_learning_rate"])
    if route not in ROUTES:
        raise FinalizeError(f"Unknown route for {condition_id}.")
    config_path = regular_file(
        (contract_path.parent / str(artifact["path"])).resolve(),
        label=f"{condition_id} config",
    )
    if sha256_file(config_path) != str(artifact["sha256"]):
        raise FinalizeError(f"Frozen config changed for {condition_id}.")
    config = load_json(config_path)
    train = config["train"]
    functional = config["functional"]
    frozen_checks = {
        "base_learning_rate": float(train["learning_rate"]) == base_lr,
        "workspace_learning_rate": float(train["workspace_learning_rate"]) == workspace_lr,
        "seed": int(train["seed"]) == seed,
        "max_steps": int(train["max_steps"]) == max_steps,
        "eval_every": int(train["eval_every"]) == eval_every,
        "eval_at_start": train.get("eval_at_start") is True,
        "complete_eval": int(train["eval_batches"]) == 0,
        "fresh_schedule": train.get("resume_from") == "none"
        and train.get("allow_schedule_extension") is False,
        "cpu_accumulate_eight": train.get("gradient_accumulation_offload") == "cpu_accumulate"
        and int(train["gradient_accumulation_steps"]) == 8,
        "route": (functional.get("route_mode") == ("inline" if route == "F1" else "deferred")),
        "memory": functional.get("memory_mode") == ("raw_sequence" if route == "F1" else "slots"),
        "injection": float(functional.get("injection_scale")) == (0.0 if route == "F1" else 1.0),
        "amputation": config["assays"].get("amputation_eval") is (route == "O0"),
    }
    if not all(frozen_checks.values()):
        failed = [name for name, passed in frozen_checks.items() if not passed]
        raise FinalizeError(f"Frozen config checks failed for {condition_id}: {failed}")

    output_dir = (config_path.parent / str(train["output_dir"])).resolve()
    try:
        output_dir.relative_to(root)
    except ValueError as exc:
        raise FinalizeError(f"Run output escapes repo for {condition_id}.") from exc
    output_dir = plain_directory(output_dir, label=f"{condition_id} run")
    paths = _run_paths(output_dir, route=route)
    metrics = load_jsonl(paths["metrics"])
    exact_metric_sequence(
        metrics,
        max_steps=max_steps,
        eval_every=eval_every,
        amputated=route == "O0",
    )
    step0 = metric_view(one_row(metrics, split="eval-step0", step=0))
    train_rows = [one_row(metrics, split="train", step=step) for step in range(1, max_steps + 1)]
    eval_steps = list(range(eval_every, max_steps + 1, eval_every))
    eval_rows = [metric_view(one_row(metrics, split="eval", step=step)) for step in eval_steps]
    final_eval = metric_view(one_row(metrics, split="eval-final", step=max_steps))
    if final_eval != eval_rows[-1]:
        raise FinalizeError(f"Eval/eval-final mismatch for {condition_id}.")
    for row in (step0, *eval_rows):
        for key in EVAL_KEYS:
            if key != "functional_distinct_predicted_classes" and not math.isfinite(
                float(row[key])
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
    base_coverage_checks = base_coverage.get("checks", {})
    applied_base_lrs = {
        float(parameter["learning_rate"]) for parameter in base_coverage.get("parameters", [])
    }
    base_schedule = schedule_chain(
        train_rows,
        configured=base_lr,
        applied_key="applied_lr_base",
        post_key="lr_base",
        max_steps=max_steps,
    )
    workspace_schedule = schedule_chain(
        train_rows,
        configured=workspace_lr,
        applied_key="applied_lr_workspace",
        post_key="lr_workspace",
        max_steps=max_steps,
    )
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
            "id": "complete_bundle",
            "passed": manifest.get("complete") is True
            and int(manifest.get("global_step", -1)) == max_steps
            and paths["completed"].read_text(encoding="utf-8") == "ok\n",
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
            "passed": bool(base_coverage_checks)
            and all(value is True for value in base_coverage_checks.values())
            and applied_base_lrs == {base_lr},
            "observed": {
                "checks": base_coverage_checks,
                "learning_rates": sorted(applied_base_lrs),
            },
        },
        {
            "id": "base_schedule_continuity",
            "passed": base_schedule["passed"],
            "observed": base_schedule,
        },
        {
            "id": "workspace_schedule_continuity",
            "passed": workspace_schedule["passed"],
            "observed": workspace_schedule,
        },
        {
            "id": "cpu_accumulate_complete",
            "passed": offload.get("status") == "completed"
            and int(offload.get("windows_started", -1)) == max_steps
            and int(offload.get("windows_restored", -1)) == max_steps
            and int(offload.get("microbatch_spills", -1)) == max_steps * 8
            and int(offload.get("live_cpu_buffer_count", -1)) == 0
            and offload.get("active_window") is None,
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
    behavior = behavior_evaluation(behavior_model, behavior_veto)
    binding = behavior_model.get("binding", {})
    behavior_binding_checks = {
        "checkpoint": binding.get("checkpoint") == relative(root, output_dir / "final"),
        "manifest": binding.get("manifest_sha256") == sha256_file(paths["manifest"]),
        "experiment_config": binding.get("experiment_config_sha256")
        == sha256_file(paths["experiment_config"]),
        "workspace_state": binding.get("workspace_state_sha256")
        == sha256_file(paths["workspace_state"]),
        "runtime_source": binding.get("source_sha256") == expected_runtime_source,
        "global_step": int(binding.get("global_step", -1)) == max_steps,
        "run_id": binding.get("run_id") == manifest.get("run_id"),
    }
    if not all(behavior_binding_checks.values()):
        failed = [name for name, passed in behavior_binding_checks.items() if not passed]
        raise FinalizeError(f"Behavior checkpoint binding failed for {condition_id}: {failed}")
    cell_checks = promotion_gate_evaluation(
        step0,
        final_eval,
        behavior_passed=bool(behavior["passed"]),
        gates=cell_gates,
    )
    amputated_summary = None
    if route == "O0":
        amputated_eval = metric_view(one_row(metrics, split="eval-final-amputated", step=max_steps))
        amputated_summary = _amputation_summary(
            load_json(paths["amputation_report"]),
            final_eval=final_eval,
            amputated_eval=amputated_eval,
            max_steps=max_steps,
        )
    eligible = all(bool(check["passed"]) for check in cell_checks)
    return {
        "condition_id": condition_id,
        "route_id": route,
        "seed": seed,
        "run": {
            "path": relative(root, output_dir),
            "run_id": manifest.get("run_id"),
            "runtime_source_sha256": manifest.get("source_sha256"),
            "artifact_hashes": {name: sha256_file(path) for name, path in paths.items()},
        },
        "frozen_config_checks": frozen_checks,
        "integrity_status": "PASS",
        "integrity_checks": integrity_checks,
        "step0": step0,
        "first_pre_update_window": metric_view(train_rows[0], PREUPDATE_KEYS),
        "train_curve": [_train_view(row) for row in train_rows],
        "evaluation_curve": [
            {"step": step, "metrics": row} for step, row in zip(eval_steps, eval_rows)
        ],
        "final_metrics": final_eval,
        "schedules": {"base": base_schedule, "workspace": workspace_schedule},
        "delta": delta,
        "workspace_state": {
            "sha256": sha256_file(paths["workspace_state"]),
            "bytes": paths["workspace_state"].stat().st_size,
        },
        "behavior": behavior,
        "behavior_binding_checks": behavior_binding_checks,
        "amputation": amputated_summary,
        "cell_checks": cell_checks,
        "eligible": eligible,
    }


def _compact_prior_f1(cell: dict[str, Any]) -> dict[str, Any]:
    return {
        "condition_id": cell["condition_id"],
        "route_id": "F1",
        "seed": int(cell["seed"]),
        "integrity_status": cell["integrity_status"],
        "step0": cell["step0"],
        "first_pre_update_window": cell["first_pre_update_window"],
        "final_metrics": cell["final_metrics"],
        "behavior": cell["behavior"],
        "delta": {
            key: cell["delta"][key]
            for key in (
                "total_numel",
                "total_changed_elements",
                "changed_element_fraction",
                "tensor_schema_sha256",
            )
        },
        "run": cell["run"],
        "eligible": bool(cell["eligible"]),
        "reused_verified_evidence": True,
    }


def _pair_deltas(f1: dict[str, Any], o0: dict[str, Any]) -> dict[str, Any]:
    return {
        "seed": int(f1["seed"]),
        "direction": "O0_minus_F1",
        "choice_loss": float(o0["final_metrics"]["functional_choice_loss"])
        - float(f1["final_metrics"]["functional_choice_loss"]),
        "full_vocab_loss": float(o0["final_metrics"]["functional_full_vocab_loss"])
        - float(f1["final_metrics"]["functional_full_vocab_loss"]),
        "complete_eval_accuracy": float(o0["final_metrics"]["functional_query_accuracy"])
        - float(f1["final_metrics"]["functional_query_accuracy"]),
        "minimum_label_recall": _minimum_recall(o0["final_metrics"])
        - _minimum_recall(f1["final_metrics"]),
        "behavior_task_accuracy": float(o0["behavior"]["task_accuracy"])
        - float(f1["behavior"]["task_accuracy"]),
        "changed_element_fraction": float(o0["delta"]["changed_element_fraction"])
        - float(f1["delta"]["changed_element_fraction"]),
    }


def _route_summary(route: str, cells: list[dict[str, Any]]) -> dict[str, Any]:
    if not cells:
        raise FinalizeError(f"No cells supplied for route {route}.")
    cells = sorted(cells, key=lambda cell: int(cell["seed"]))
    values = {
        "behavior_task_accuracy": [float(cell["behavior"]["task_accuracy"]) for cell in cells],
        "complete_eval_accuracy": [
            float(cell["final_metrics"]["functional_query_accuracy"]) for cell in cells
        ],
        "minimum_label_recall": [_minimum_recall(cell["final_metrics"]) for cell in cells],
        "choice_loss": [float(cell["final_metrics"]["functional_choice_loss"]) for cell in cells],
    }
    return {
        "route_id": route,
        "seeds": [int(cell["seed"]) for cell in cells],
        "passed_seeds": [int(cell["seed"]) for cell in cells if cell["eligible"]],
        "robust": all(bool(cell["eligible"]) for cell in cells),
        "metrics": {
            name: {
                "minimum": min(rows),
                "maximum": max(rows),
                "mean": statistics.fmean(rows),
                "sample_standard_deviation": statistics.stdev(rows),
            }
            for name, rows in values.items()
        },
    }


def _source_commit(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise FinalizeError("--source-commit must be a full lowercase Git commit.")
    return value


def _load_common(args: argparse.Namespace) -> tuple[Path, Path, dict[str, Any], Path]:
    root = plain_directory(args.repo_root.expanduser().resolve(), label="repo root")
    contract_path = regular_file(repo_path(root, args.contract, label="contract"), label="contract")
    contract = load_json(contract_path)
    if contract.get("format") != CONTRACT_FORMAT:
        raise FinalizeError("Unexpected F1/O0 comparison contract format.")
    initial_snapshot = plain_directory(
        args.initial_snapshot.expanduser().resolve(), label="initial snapshot"
    )
    _source_commit(args.source_commit)
    return root, contract_path, contract, initial_snapshot


def _pinned_f1(
    *, root: Path, contract_path: Path, contract: dict[str, Any]
) -> tuple[dict[str, Any], Path, dict[str, dict[str, str]]]:
    verified: dict[str, dict[str, str]] = {}
    control = contract["verified_f1_stage4_control"]
    for label, binding in (
        ("f1_contract", control["contract"]),
        ("f1_behavior", control["behavior"]),
        ("train_data", contract["data"]["train"]),
        ("eval_data", contract["data"]["eval"]),
        ("prompt_suite", contract["behavior_veto"]["prompt_suite"]),
    ):
        verified[label] = _verify_binding(
            root=root,
            contract_path=contract_path,
            binding=binding,
            label=label,
        )
    receipt_binding = control["receipt"]
    receipt_record = _verify_binding(
        root=root,
        contract_path=contract_path,
        binding=receipt_binding,
        label="F1 stage-4 receipt",
    )
    verified["f1_receipt"] = receipt_record
    receipt_path = root / receipt_record["path"]
    receipt = load_json(receipt_path)
    if (
        receipt.get("format") != PRIOR_F1_FORMAT
        or receipt.get("integrity_status") != "PASS"
        or receipt.get("scientific_status") != "ROBUST_BASELINE_SELECTED"
        or receipt.get("selected_learning_rate") != control["selected_learning_rate"]
    ):
        raise FinalizeError("Pinned F1 control is no longer a qualified robust baseline.")
    return receipt, receipt_path, verified


def _cells_by_seed(cells: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    result = {int(cell["seed"]): cell for cell in cells}
    if len(result) != len(cells):
        raise FinalizeError("Duplicate seed cell detected.")
    return result


def finalize_stage4(args: argparse.Namespace) -> dict[str, Any]:
    root, contract_path, contract, initial_snapshot = _load_common(args)
    prior, prior_path, verified = _pinned_f1(
        root=root, contract_path=contract_path, contract=contract
    )
    behavior_path = regular_file(
        repo_path(root, args.behavior_receipt, label="behavior receipt"),
        label="behavior receipt",
    )
    behavior_receipt = load_json(behavior_path)
    order = [str(value) for value in contract["stage4"]["condition_order"]]
    if set(contract["stage4"]["artifacts"]) != set(order):
        raise FinalizeError("Stage-4 artifact set differs from execution order.")
    behavior_models, behavior_checks = _validate_behavior_receipt(
        receipt=behavior_receipt,
        contract=contract,
        stage=contract["stage4"],
        expected_models={"original", *order},
    )
    runtime_source = str(prior["runtime_source_sha256"])
    o0_cells = [
        _finalize_cell(
            root=root,
            contract_path=contract_path,
            condition_id=condition_id,
            artifact=contract["stage4"]["artifacts"][condition_id],
            initial_snapshot=initial_snapshot,
            behavior_model=behavior_models[condition_id],
            behavior_veto=contract["behavior_veto"],
            cell_gates=contract["cell_gates"],
            expected_runtime_source=runtime_source,
        )
        for condition_id in order
    ]
    required_seeds = [int(value) for value in contract["branch_robustness_gate"]["required_seeds"]]
    prior_cells = [
        cell
        for cell in prior["cells"]
        if cell.get("learning_rate_id") == prior["selected_learning_rate_id"]
        and int(cell.get("seed", -1)) in required_seeds
    ]
    f1_cells = [_compact_prior_f1(cell) for cell in prior_cells]
    f1_by_seed = _cells_by_seed(f1_cells)
    o0_by_seed = _cells_by_seed(o0_cells)
    if sorted(f1_by_seed) != sorted(required_seeds) or sorted(o0_by_seed) != sorted(required_seeds):
        raise FinalizeError("Stage-4 seed coverage differs from the frozen design.")
    noninferiority = [
        {
            "seed": seed,
            **paired_noninferiority(
                f1_by_seed[seed],
                o0_by_seed[seed],
                contract["noninferiority_margins"],
            ),
        }
        for seed in required_seeds
    ]
    o0_summary = _route_summary("O0", o0_cells)
    f1_summary = _route_summary("F1", f1_cells)
    competitive = bool(o0_summary["robust"] and all(bool(row["passed"]) for row in noninferiority))
    return {
        "format": STAGE4_FORMAT,
        "schema_version": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "integrity_status": "PASS",
        "scientific_status": (
            "O0_4STEP_COMPETITIVE" if competitive else "O0_4STEP_NOT_COMPETITIVE"
        ),
        "question": contract["stage4"]["purpose"],
        "contract": {"path": relative(root, contract_path), "sha256": sha256_file(contract_path)},
        "source_commit_at_launch": args.source_commit,
        "runtime_source_sha256": runtime_source,
        "verified_design_inputs": verified,
        "prior_f1_receipt": {
            "path": relative(root, prior_path),
            "sha256": sha256_file(prior_path),
        },
        "behavior_receipt": {
            "path": relative(root, behavior_path),
            "sha256": sha256_file(behavior_path),
            "binding_checks": behavior_checks,
        },
        "cells": {"F1_reused": f1_cells, "O0_new": o0_cells},
        "route_summaries": {"F1": f1_summary, "O0": o0_summary},
        "paired_deltas": [
            _pair_deltas(f1_by_seed[seed], o0_by_seed[seed]) for seed in required_seeds
        ],
        "paired_noninferiority": noninferiority,
        "o0_competitive": competitive,
        "refinement_execution_authorized": True,
        "refinement_authority_basis": (
            "Integrity PASS authorizes the predeclared diagnostic refinement even when "
            "the O0 competitive gate is negative."
        ),
        "claim_boundary": contract["claim_boundary"],
    }


def _parse_necessity_args(values: list[str]) -> dict[int, Path]:
    result: dict[int, Path] = {}
    for value in values:
        if "=" not in value:
            raise FinalizeError("--necessity values must use SEED=PATH syntax.")
        raw_seed, raw_path = value.split("=", 1)
        try:
            seed = int(raw_seed)
        except ValueError as exc:
            raise FinalizeError("Necessity seed must be an integer.") from exc
        if seed in result or not raw_path:
            raise FinalizeError("Necessity seed is duplicated or has an empty path.")
        result[seed] = Path(raw_path)
    return result


def _generation_original_summary(original: dict[str, Any]) -> dict[str, Any]:
    baselines = original.get("task_native_baselines")
    freeform = original.get("freeform")
    if not isinstance(baselines, dict) or not isinstance(freeform, list) or not freeform:
        raise FinalizeError("Original behavior capture lacks baselines or free-form traces.")
    return {
        "task_native_accuracy_by_route": {
            name: float(value["accuracy"]) for name, value in baselines.items()
        },
        "freeform_diagnostics": [
            {"prompt_id": row.get("id"), **completion_diagnostics(row["completion_token_ids"])}
            for row in freeform
        ],
    }


def finalize_refinement(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    root, contract_path, contract, initial_snapshot = _load_common(args)
    prior, _prior_path, verified = _pinned_f1(
        root=root, contract_path=contract_path, contract=contract
    )
    stage4_path = regular_file(
        repo_path(root, args.stage4_receipt, label="stage-4 receipt"), label="stage-4 receipt"
    )
    stage4 = load_json(stage4_path)
    if (
        stage4.get("format") != STAGE4_FORMAT
        or stage4.get("integrity_status") != "PASS"
        or stage4.get("refinement_execution_authorized") is not True
        or stage4.get("contract", {}).get("sha256") != sha256_file(contract_path)
    ):
        raise FinalizeError("Stage-4 receipt did not authorize refinement.")
    behavior_path = regular_file(
        repo_path(root, args.behavior_receipt, label="behavior receipt"),
        label="behavior receipt",
    )
    behavior_receipt = load_json(behavior_path)
    order = [str(value) for value in contract["refinement16"]["condition_order"]]
    if set(contract["refinement16"]["artifacts"]) != set(order):
        raise FinalizeError("Refinement artifact set differs from execution order.")
    behavior_models, behavior_checks = _validate_behavior_receipt(
        receipt=behavior_receipt,
        contract=contract,
        stage=contract["refinement16"],
        expected_models={"original", *order},
    )
    runtime_source = str(prior["runtime_source_sha256"])
    cells = [
        _finalize_cell(
            root=root,
            contract_path=contract_path,
            condition_id=condition_id,
            artifact=contract["refinement16"]["artifacts"][condition_id],
            initial_snapshot=initial_snapshot,
            behavior_model=behavior_models[condition_id],
            behavior_veto=contract["behavior_veto"],
            cell_gates=contract["cell_gates"],
            expected_runtime_source=runtime_source,
        )
        for condition_id in order
    ]
    by_route_seed = {(str(cell["route_id"]), int(cell["seed"])): cell for cell in cells}
    required_seeds = [int(value) for value in contract["branch_robustness_gate"]["required_seeds"]]
    if set(by_route_seed) != {(route, seed) for route in ROUTES for seed in required_seeds}:
        raise FinalizeError("Refinement route/seed coverage differs from the frozen matrix.")

    prior_f1_by_seed = {
        int(cell["seed"]): cell
        for cell in prior["cells"]
        if cell.get("learning_rate_id") == prior["selected_learning_rate_id"]
        and int(cell.get("seed", -1)) in required_seeds
    }
    stage4_o0_by_seed = _cells_by_seed(stage4["cells"]["O0_new"])
    replay_checks: list[dict[str, Any]] = []
    for seed in required_seeds:
        for route, reference in (
            ("F1", prior_f1_by_seed[seed]),
            ("O0", stage4_o0_by_seed[seed]),
        ):
            cell = by_route_seed[(route, seed)]
            check = {
                "route_id": route,
                "seed": seed,
                "step0_exact": cell["step0"] == reference["step0"],
                "first_pre_update_window_exact": cell["first_pre_update_window"]
                == reference["first_pre_update_window"],
            }
            check["passed"] = check["step0_exact"] and check["first_pre_update_window_exact"]
            replay_checks.append(check)
    if not all(bool(check["passed"]) for check in replay_checks):
        failed = [(row["route_id"], row["seed"]) for row in replay_checks if not row["passed"]]
        raise FinalizeError(f"Fresh refinement did not replay its matched prefix: {failed}")

    necessity_args = _parse_necessity_args(args.necessity)
    if set(necessity_args) != set(required_seeds):
        raise FinalizeError("Necessity receipts do not cover every frozen O0 seed.")
    necessity: list[dict[str, Any]] = []
    for seed in required_seeds:
        path = regular_file(
            repo_path(root, necessity_args[seed], label=f"necessity seed {seed}"),
            label=f"necessity seed {seed}",
        )
        value = load_json(path)
        cell = by_route_seed[("O0", seed)]
        expected_checkpoint = str((root / cell["run"]["path"] / "final").resolve())
        if value.get("source_sha256") != runtime_source:
            raise FinalizeError(f"Necessity runtime source differs for seed {seed}.")
        if str(Path(str(value.get("checkpoint"))).resolve()) != expected_checkpoint:
            raise FinalizeError(f"Necessity checkpoint binding differs for seed {seed}.")
        necessity.append(
            {
                "seed": seed,
                "path": relative(root, path),
                "sha256": sha256_file(path),
                **necessity_summary(value),
            }
        )

    route_summaries = {
        route: _route_summary(route, [cell for cell in cells if cell["route_id"] == route])
        for route in ROUTES
    }
    noninferiority = [
        {
            "seed": seed,
            **paired_noninferiority(
                by_route_seed[("F1", seed)],
                by_route_seed[("O0", seed)],
                contract["noninferiority_margins"],
            ),
        }
        for seed in required_seeds
    ]
    o0_competitive = bool(
        route_summaries["O0"]["robust"] and all(bool(row["passed"]) for row in noninferiority)
    )
    content_specific_replicated = all(bool(row["content_specific"]) for row in necessity)
    decision = choose_v12_design(
        f1_robust=bool(route_summaries["F1"]["robust"]),
        o0_robust=bool(route_summaries["O0"]["robust"]),
        o0_competitive=o0_competitive,
        content_specific_replicated=content_specific_replicated,
    )
    paired_deltas = [
        _pair_deltas(by_route_seed[("F1", seed)], by_route_seed[("O0", seed)])
        for seed in required_seeds
    ]
    receipt = {
        "format": REFINEMENT_FORMAT,
        "schema_version": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "integrity_status": "PASS",
        "scientific_status": "REFINEMENT_COMPARED",
        "question": contract["question"],
        "contract": {"path": relative(root, contract_path), "sha256": sha256_file(contract_path)},
        "source_commit_at_launch": args.source_commit,
        "runtime_source_sha256": runtime_source,
        "verified_design_inputs": verified,
        "stage4_receipt": {"path": relative(root, stage4_path), "sha256": sha256_file(stage4_path)},
        "behavior_receipt": {
            "path": relative(root, behavior_path),
            "sha256": sha256_file(behavior_path),
            "binding_checks": behavior_checks,
        },
        "matched_fresh_prefix_replay": replay_checks,
        "cells": cells,
        "route_summaries": route_summaries,
        "paired_deltas": paired_deltas,
        "paired_noninferiority": noninferiority,
        "o0_competitive": o0_competitive,
        "necessity": necessity,
        "content_specific_necessity_replicated": content_specific_replicated,
        "generation_contrast": {
            "original": _generation_original_summary(behavior_models["original"]),
            "trained_models": {
                cell["condition_id"]: {
                    "route_id": cell["route_id"],
                    "seed": cell["seed"],
                    "task_accuracy": cell["behavior"]["task_accuracy"],
                    "task_choices": cell["behavior"]["task_choices"],
                    "freeform_diagnostics": cell["behavior"]["freeform_diagnostics"],
                }
                for cell in cells
            },
        },
        "v12_rule_id": decision["rule_id"],
        "v12_design_derivation_authorized": True,
        "v12_training_execution_authorized": False,
        "claim_boundary": contract["claim_boundary"],
    }
    v12 = {
        "format": V12_FORMAT,
        "schema_version": 1,
        "created_utc": receipt["created_utc"],
        "status": "DESIGN_ONLY",
        "selected_rule": decision,
        "decision_inputs": {
            "f1_robust_at_16": route_summaries["F1"]["robust"],
            "o0_robust_at_16": route_summaries["O0"]["robust"],
            "o0_performance_competitive": o0_competitive,
            "o0_content_specific_necessity_replicated": content_specific_replicated,
        },
        "failure_mode_handoff": {
            "failed_f1_seeds": [
                seed for seed in required_seeds if not by_route_seed[("F1", seed)]["eligible"]
            ],
            "failed_o0_seeds": [
                seed for seed in required_seeds if not by_route_seed[("O0", seed)]["eligible"]
            ],
            "necessity_classification_by_seed": {
                str(row["seed"]): row["classification"] for row in necessity
            },
            "paired_noninferiority": noninferiority,
        },
        "next_contract_requirements": [
            "Preserve the pinned elicitation, complete eval, behavior veto, and F0-F5 receipts.",
            "Address the selected failure mode before adding model scale or broad sweeps.",
            "Freeze a new V12 execution contract before any training run.",
        ],
        "execution_authority": {
            "v12_design_complete": True,
            "v12_training_authorized": False,
            "14b_scale_up_authorized": False,
            "optimizer_sweep_authorized": False,
        },
        "claim_boundary": contract["claim_boundary"],
    }
    return receipt, v12


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--repo-root", type=Path, default=Path("."))
        subparser.add_argument(
            "--contract",
            type=Path,
            default=Path("configs/v11/F1_O0_REFINEMENT_CONTRACT.json"),
        )
        subparser.add_argument("--behavior-receipt", type=Path, required=True)
        subparser.add_argument("--initial-snapshot", type=Path, required=True)
        subparser.add_argument("--source-commit", required=True)
        subparser.add_argument("--output", type=Path, required=True)
        subparser.add_argument("--overwrite", action="store_true")

    stage4 = subparsers.add_parser("stage4")
    common(stage4)

    refinement = subparsers.add_parser("refinement")
    common(refinement)
    refinement.add_argument("--stage4-receipt", type=Path, required=True)
    refinement.add_argument(
        "--necessity",
        action="append",
        default=[],
        metavar="SEED=PATH",
        help="One O0 necessity receipt per frozen seed.",
    )
    refinement.add_argument("--v12-output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.repo_root.expanduser().resolve()
    output = repo_path(root, args.output, label="output")
    try:
        if args.command == "stage4":
            receipt = finalize_stage4(args)
            atomic_write(output, receipt, overwrite=args.overwrite)
            print(f"WROTE {relative(root, output)}")
            print(f"scientific_status={receipt['scientific_status']}")
            return 0
        receipt, v12 = finalize_refinement(args)
        atomic_write(output, receipt, overwrite=args.overwrite)
        v12["refinement_receipt"] = {
            "path": relative(root, output),
            "sha256": sha256_file(output),
        }
        v12_output = repo_path(root, args.v12_output, label="V12 output")
        atomic_write(v12_output, v12, overwrite=args.overwrite)
        print(f"WROTE {relative(root, output)}")
        print(f"WROTE {relative(root, v12_output)}")
        print(f"v12_rule_id={receipt['v12_rule_id']}")
        return 0
    except Exception as exc:
        message = str(exc) if isinstance(exc, FinalizeError) else type(exc).__name__
        print(f"ERROR: {message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
