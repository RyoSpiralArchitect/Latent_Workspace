#!/usr/bin/env python3
"""Finalize the preauthorized four-update promotion of the selected V11 F1 run."""

from __future__ import annotations

import argparse
import math
import re
import sys
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

from finalize_v11_update_response_surface import (
    BEHAVIOR_FORMAT,
    CONTRACT_FORMAT,
    EVAL_KEYS,
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
from run_v10_matrix import compare_full_update_safetensors

FORMAT = "latent-workspace-ft-v11-step4-promotion-receipt-v1"
SURFACE_FORMAT = "latent-workspace-ft-v11-update-response-receipt-v1"


def promotion_gate_evaluation(
    step0: dict[str, Any],
    final: dict[str, Any],
    *,
    behavior_passed: bool,
    gates: dict[str, Any],
) -> list[dict[str, Any]]:
    """Evaluate only the step-4 gates frozen before the response surface ran."""
    accuracy = float(final["functional_query_accuracy"])
    recalls = [
        float(final["functional_label_0_recall"]),
        float(final["functional_label_1_recall"]),
    ]
    distinct = int(final["functional_distinct_predicted_classes"])
    choice_loss = float(final["functional_choice_loss"])
    full_vocab_loss = float(final["functional_full_vocab_loss"])
    return [
        {
            "id": "minimum_accuracy",
            "criterion": f">= {float(gates['minimum_accuracy'])}",
            "observed": accuracy,
            "passed": accuracy >= float(gates["minimum_accuracy"]),
        },
        {
            "id": "minimum_distinct_predicted_classes",
            "criterion": f">= {int(gates['minimum_distinct_predicted_classes'])}",
            "observed": distinct,
            "passed": distinct >= int(gates["minimum_distinct_predicted_classes"]),
        },
        {
            "id": "minimum_label_recall",
            "criterion": f">= {float(gates['minimum_label_recall'])} each",
            "observed": recalls,
            "passed": min(recalls) >= float(gates["minimum_label_recall"]),
        },
        {
            "id": "final_choice_loss_below_step0",
            "criterion": f"< {float(step0['functional_choice_loss'])}",
            "observed": choice_loss,
            "passed": choice_loss < float(step0["functional_choice_loss"]),
        },
        {
            "id": "maximum_final_full_vocab_loss",
            "criterion": f"<= {float(gates['maximum_final_full_vocab_loss'])}",
            "observed": full_vocab_loss,
            "passed": full_vocab_loss <= float(gates["maximum_final_full_vocab_loss"]),
        },
        {
            "id": "behavior_veto",
            "criterion": "PASS",
            "observed": behavior_passed,
            "passed": behavior_passed if bool(gates["require_behavior_veto_pass"]) else True,
        },
    ]


def learning_rate_chain(rows: list[dict[str, Any]], base_lr: float) -> dict[str, Any]:
    """Describe continuity between applied and post-scheduler learning rates."""
    applied = [float(row["applied_lr_base"]) for row in rows]
    post_scheduler = [float(row["lr_base"]) for row in rows]
    continuity = all(applied[index] == post_scheduler[index - 1] for index in range(1, len(rows)))
    passed = (
        len(rows) == 4
        and applied[0] == base_lr
        and all(value > 0.0 for value in applied)
        and continuity
        and post_scheduler[-1] == 0.0
    )
    return {
        "passed": passed,
        "configured_base_learning_rate": base_lr,
        "applied_learning_rates": applied,
        "post_scheduler_learning_rates": post_scheduler,
        "adjacent_schedule_continuity": continuity,
    }


def _selected_condition(surface: dict[str, Any], condition_id: str) -> dict[str, Any]:
    matches = [
        condition
        for condition in surface.get("conditions", [])
        if condition.get("condition_id") == condition_id
    ]
    if len(matches) != 1:
        raise FinalizeError("Selected condition is missing or duplicated in surface receipt.")
    return matches[0]


def _exact_metric_sequence(rows: list[dict[str, Any]]) -> None:
    expected = [("eval-step0", 0)]
    for step in range(1, 5):
        expected.extend((("train", step), ("eval", step)))
    expected.append(("eval-final", 4))
    try:
        observed = [(str(row["split"]), int(row["step"])) for row in rows]
    except (KeyError, TypeError, ValueError) as exc:
        raise FinalizeError("Step-4 metrics contain malformed split/step fields.") from exc
    if observed != expected:
        raise FinalizeError("Step-4 metrics do not have the exact frozen row sequence.")


def _delta_summary(initial_snapshot: Path, final_model: Path) -> dict[str, Any]:
    delta = compare_full_update_safetensors(initial_snapshot, final_model)
    total_numel = int(delta["initial_semantic"]["total_numel"])
    changed_elements = int(delta["total_changed_elements"])
    if changed_elements <= 0:
        raise FinalizeError("Step-4 persisted base model has no exact changed elements.")
    return {
        "tensor_count": int(delta["tensor_count"]),
        "changed_tensor_count": int(delta["changed_tensor_count"]),
        "unchanged_tensor_count": int(delta["unchanged_tensor_count"]),
        "total_numel": total_numel,
        "total_changed_elements": changed_elements,
        "changed_element_fraction": changed_elements / total_numel,
        "tensor_schema_sha256": delta["initial_semantic"]["tensor_schema_sha256"],
        "performance": delta["performance"],
        "tensors": delta["tensors"],
    }


def finalize(args: argparse.Namespace) -> dict[str, Any]:
    root = plain_directory(args.repo_root.expanduser().resolve(), label="repo root")
    contract_path = regular_file(repo_path(root, args.contract, label="contract"), label="contract")
    surface_path = regular_file(
        repo_path(root, args.surface_receipt, label="surface receipt"),
        label="surface receipt",
    )
    behavior_path = regular_file(
        repo_path(root, args.behavior_receipt, label="behavior receipt"),
        label="behavior receipt",
    )
    initial_snapshot = plain_directory(
        args.initial_snapshot.expanduser().resolve(), label="initial snapshot"
    )
    contract = load_json(contract_path)
    surface = load_json(surface_path)
    behavior = load_json(behavior_path)
    if contract.get("format") != CONTRACT_FORMAT:
        raise FinalizeError("Unexpected update-response contract format.")
    if surface.get("format") != SURFACE_FORMAT:
        raise FinalizeError("Unexpected response-surface receipt format.")
    if behavior.get("format") != BEHAVIOR_FORMAT or behavior.get("status") != "PASS":
        raise FinalizeError("Step-4 behavior capture did not complete with PASS integrity.")
    for label, commit in (
        ("--source-commit", args.source_commit),
        ("--finalizer-commit", args.finalizer_commit),
    ):
        if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
            raise FinalizeError(f"{label} must be a full lowercase Git commit.")

    surface_contract = surface.get("contract", {})
    if (
        surface.get("integrity_status") != "PASS"
        or surface.get("scientific_status") != "SELECTED"
        or surface.get("step4_launch_authorized") is not True
    ):
        raise FinalizeError("Surface receipt did not authorize a step-4 run.")
    if (
        surface_contract.get("sha256") != sha256_file(contract_path)
        or surface.get("source_commit_at_launch") != args.source_commit
    ):
        raise FinalizeError("Surface contract or launch-source binding changed.")
    condition_id = str(surface.get("selected_condition_id"))
    selected = _selected_condition(surface, condition_id)
    if selected.get("eligible") is not True:
        raise FinalizeError("Selected surface condition is not eligible.")

    artifact = contract["artifacts"].get(condition_id)
    if not isinstance(artifact, dict) or "step4" not in artifact:
        raise FinalizeError("Frozen contract has no step-4 artifact for selection.")
    config_binding = artifact["step4"]
    config_path = regular_file(
        (contract_path.parent / str(config_binding["path"])).resolve(),
        label="step-4 config",
    )
    if sha256_file(config_path) != str(config_binding["sha256"]):
        raise FinalizeError("Frozen step-4 config changed.")
    config = load_json(config_path)
    train_config = config["train"]
    learning_rate = float(artifact["learning_rate"])
    frozen_config_checks = {
        "learning_rate": float(train_config["learning_rate"]) == learning_rate,
        "max_steps": int(train_config["max_steps"]) == 4,
        "eval_at_start": train_config.get("eval_at_start") is True,
        "eval_every": int(train_config["eval_every"]) == 1,
        "eval_batches": int(train_config["eval_batches"]) == 0,
        "save_every": int(train_config["save_every"]) == 0,
    }
    if not all(frozen_config_checks.values()):
        raise FinalizeError("Step-4 config no longer matches the frozen promotion design.")

    output_dir = (config_path.parent / str(train_config["output_dir"])).resolve()
    try:
        output_dir.relative_to(root)
    except ValueError as exc:
        raise FinalizeError("Step-4 output escapes repo root.") from exc
    output_dir = plain_directory(output_dir, label="step-4 run")
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
            output_dir / "final" / "experiment_config.json",
            label="experiment config",
        ),
        "completed": regular_file(output_dir / "final" / "COMPLETED", label="COMPLETED"),
    }
    metrics = load_jsonl(paths["metrics"])
    _exact_metric_sequence(metrics)
    step0 = metric_view(one_row(metrics, split="eval-step0", step=0))
    train_rows = [one_row(metrics, split="train", step=step) for step in range(1, 5)]
    eval_rows = [metric_view(one_row(metrics, split="eval", step=step)) for step in range(1, 5)]
    final_eval = metric_view(one_row(metrics, split="eval-final", step=4))
    if final_eval != eval_rows[-1]:
        raise FinalizeError("Step-4 eval and eval-final metrics differ.")
    if step0 != selected["step0"]:
        raise FinalizeError("Step-4 step-0 metrics differ from the selected surface run.")
    if eval_rows[0] != selected["post_update"]:
        raise FinalizeError("Step-4 step-1 eval does not replay the selected one-update run.")
    selected_preupdate = selected["pre_update_window"]
    if any(train_rows[0].get(key) != value for key, value in selected_preupdate.items()):
        raise FinalizeError("Step-4 first pre-update window differs from the surface run.")
    if any(
        not math.isfinite(float(row[key]))
        for row in (step0, *eval_rows)
        for key in EVAL_KEYS
        if key != "functional_distinct_predicted_classes"
    ):
        raise FinalizeError("Step-4 decision metrics contain a non-finite value.")
    if any(row.get("window_metrics_phase") != "pre_update_forward" for row in train_rows):
        raise FinalizeError("Step-4 train rows do not identify pre-update metrics.")

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
    expected_source_hash = surface["matched_surface"]["runtime_source_sha256"]
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
            "passed": source_hashes == {expected_source_hash},
            "observed": sorted(source_hashes),
            "expected": expected_source_hash,
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
        raise FinalizeError(f"Step-4 integrity failed: {failed}")

    delta = _delta_summary(initial_snapshot, output_dir / "final" / "base_model")
    behavior_models = behavior.get("models")
    behavior_label = f"{condition_id}_step4"
    if not isinstance(behavior_models, dict) or behavior_label not in behavior_models:
        raise FinalizeError("Behavior receipt omitted the selected step-4 model.")
    behavior_result = behavior_evaluation(
        behavior_models[behavior_label], contract["behavior_veto"]
    )
    gates = contract["preauthorized_followup"]["step4_gates"]
    promotion_checks = promotion_gate_evaluation(
        step0,
        final_eval,
        behavior_passed=bool(behavior_result["passed"]),
        gates=gates,
    )
    promoted = all(bool(check["passed"]) for check in promotion_checks)
    choice_curve = [float(row["functional_choice_loss"]) for row in (step0, *eval_rows)]
    return {
        "format": FORMAT,
        "schema_version": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "integrity_status": "PASS",
        "scientific_status": "PROMOTED" if promoted else "BLOCKED",
        "v11_baseline_ready": promoted,
        "selected_condition_id": condition_id,
        "learning_rate": learning_rate,
        "contract": {
            "path": relative(root, contract_path),
            "sha256": sha256_file(contract_path),
        },
        "surface_receipt": {
            "path": relative(root, surface_path),
            "sha256": sha256_file(surface_path),
        },
        "behavior_receipt": {
            "path": relative(root, behavior_path),
            "sha256": sha256_file(behavior_path),
            "model_label": behavior_label,
        },
        "source_commit_at_launch": args.source_commit,
        "finalizer_commit": args.finalizer_commit,
        "run": {
            "path": relative(root, output_dir),
            "run_id": manifest.get("run_id"),
            "runtime_source_sha256": manifest.get("source_sha256"),
            "artifact_hashes": {name: sha256_file(path) for name, path in paths.items()},
        },
        "frozen_config_checks": frozen_config_checks,
        "integrity_checks": integrity_checks,
        "exact_replay": {
            "step0_matches_surface": True,
            "first_pre_update_window_matches_surface": True,
            "step1_eval_matches_surface": True,
        },
        "evaluation_curve": {
            "step0": step0,
            "steps": [
                {"step": step, "metrics": row} for step, row in enumerate(eval_rows, start=1)
            ],
            "choice_loss_monotone_nonincreasing": all(
                later <= earlier for earlier, later in pairwise(choice_curve)
            ),
            "diagnostic_not_a_promotion_gate": True,
        },
        "applied_learning_rate_schedule": lr_chain,
        "delta": delta,
        "behavior": behavior_result,
        "promotion_checks": promotion_checks,
        "weights_retained": True,
        "further_training_authorized": False,
        "claim_boundary": {
            "supported": (
                "The selected F1 symmetric, choice-normalized Mistral-7B branch "
                "passed the frozen four-update metric and behavior gates for seed 42."
            ),
            "not_supported": [
                "Active-workspace or O0 superiority",
                "Pure-native B/F1/O3 equivalence",
                "Multi-seed robustness",
                "Sixteen-step stability",
                "14B scale transfer",
                "General capability improvement",
            ],
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument(
        "--contract", type=Path, default=Path("configs/v11/UPDATE_RESPONSE_CONTRACT.json")
    )
    parser.add_argument("--surface-receipt", type=Path, required=True)
    parser.add_argument("--behavior-receipt", type=Path, required=True)
    parser.add_argument("--initial-snapshot", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--finalizer-commit", required=True)
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
    print(f"v11_baseline_ready={receipt['v11_baseline_ready']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
