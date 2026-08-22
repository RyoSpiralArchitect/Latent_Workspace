#!/usr/bin/env python3
"""Finalize the gated V12 inline-sidecar experiment without inferring success."""

from __future__ import annotations

import argparse
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from finalize_v11_f1_o0_refinement import necessity_summary
from finalize_v11_update_response_surface import (
    BEHAVIOR_FORMAT,
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

CONTRACT_FORMAT = "latent-workspace-ft-v12-calibrated-route-contract-v1"
NOOP_FORMAT = "latent-workspace-ft-v12-noop-gate-receipt-v1"
STEP1_FORMAT = "latent-workspace-ft-v12-step1-response-receipt-v1"
STAGE4_FORMAT = "latent-workspace-ft-v12-stage4-comparison-receipt-v1"
FINAL_FORMAT = "latent-workspace-ft-v12-refinement-receipt-v1"
NEXT_FORMAT = "latent-workspace-ft-v13-design-handoff-v1"
BRANCHES = ("task", "semantic")


def _source_commit(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise FinalizeError("--source-commit must be a full lowercase Git commit.")
    return value


def _minimum_recall(metrics: dict[str, Any]) -> float:
    return min(
        float(metrics["functional_label_0_recall"]),
        float(metrics["functional_label_1_recall"]),
    )


def _exact_metric_sequence(rows: list[dict[str, Any]], *, max_steps: int, eval_every: int) -> None:
    expected: list[tuple[str, int]] = [("eval-step0", 0)]
    for step in range(1, max_steps + 1):
        expected.append(("train", step))
        if step % eval_every == 0:
            expected.append(("eval", step))
    expected.extend(
        [
            ("eval-final", max_steps),
            ("eval-final-amputated", max_steps),
        ]
    )
    events = [row for row in rows if "split" not in row]
    if (
        len(events) != 1
        or rows[0] is not events[0]
        or events[0].get("event") != "start"
        or int(events[0].get("step", -1)) != 0
    ):
        raise FinalizeError("Metrics require exactly one leading start event.")
    observed = [(str(row["split"]), int(row["step"])) for row in rows if "split" in row]
    if observed != expected:
        raise FinalizeError(
            f"Metric sequence differs from the frozen {max_steps}-step design: {observed!r}."
        )


def _delta_summary(initial_snapshot: Path, final_model: Path) -> dict[str, Any]:
    delta = compare_full_update_safetensors(initial_snapshot, final_model)
    total_numel = int(delta["initial_semantic"]["total_numel"])
    changed = int(delta["total_changed_elements"])
    return {
        "tensor_count": int(delta["tensor_count"]),
        "changed_tensor_count": int(delta["changed_tensor_count"]),
        "unchanged_tensor_count": int(delta["unchanged_tensor_count"]),
        "total_numel": total_numel,
        "total_changed_elements": changed,
        "changed_element_fraction": changed / max(total_numel, 1),
        "tensor_schema_sha256": delta["initial_semantic"]["tensor_schema_sha256"],
        "performance": delta["performance"],
        "tensors": delta["tensors"],
    }


def _artifact_config(
    root: Path,
    contract_path: Path,
    artifact: dict[str, Any],
) -> tuple[Path, dict[str, Any], Path]:
    config_path = regular_file(
        (contract_path.parent / str(artifact["path"])).resolve(),
        label=f"{artifact['condition_id']} config",
    )
    if sha256_file(config_path) != str(artifact["sha256"]):
        raise FinalizeError(f"Frozen config changed for {artifact['condition_id']}.")
    config = load_json(config_path)
    output_dir = (config_path.parent / str(config["train"]["output_dir"])).resolve()
    try:
        output_dir.relative_to(root)
    except ValueError as exc:
        raise FinalizeError("Run output escapes the repository.") from exc
    return config_path, config, output_dir


def _ownership_summary(
    rows: list[dict[str, Any]],
    *,
    max_steps: int,
    base_release_step: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if len(rows) != max_steps:
        raise FinalizeError("Update-ownership row count differs from max_steps.")
    checks: list[dict[str, Any]] = []
    expected_steps = list(range(1, max_steps + 1))
    observed_steps = [int(row.get("step", -1)) for row in rows]
    checks.append(
        {
            "id": "ownership_step_sequence",
            "passed": observed_steps == expected_steps,
            "observed": observed_steps,
            "criterion": expected_steps,
        }
    )
    frozen_rows: list[dict[str, Any]] = []
    released_rows: list[dict[str, Any]] = []
    for row in rows:
        step = int(row["step"])
        expected_active = step > base_release_step
        sentinels = row.get("sentinels", {})
        base = sentinels.get("base", {})
        workspace = sentinels.get("workspace", {})
        states = row.get("optimizer_state_entries", {})
        if expected_active:
            released_rows.append(row)
            passed = bool(
                row.get("base_update_active") is True
                and float(row.get("applied_lr_base", 0.0)) > 0.0
                and int(states.get("base", 0)) > 0
            )
        else:
            frozen_rows.append(row)
            passed = bool(
                row.get("base_update_active") is False
                and float(row.get("applied_lr_base", -1.0)) == 0.0
                and int(states.get("base", -1)) == 0
                and base.get("updated") is False
                and workspace.get("updated") is True
                and int(states.get("workspace", 0)) > 0
                and int(row.get("cleared_base_gradients", 0)) > 0
            )
        checks.append(
            {
                "id": f"ownership_step_{step}",
                "passed": passed,
                "observed": {
                    "base_update_active": row.get("base_update_active"),
                    "applied_lr_base": row.get("applied_lr_base"),
                    "optimizer_state_entries": states,
                    "base_sentinel_updated": base.get("updated"),
                    "workspace_sentinel_updated": workspace.get("updated"),
                },
                "criterion": "released" if expected_active else "exactly frozen base",
            }
        )
    return (
        {
            "passed": all(bool(check["passed"]) for check in checks),
            "base_release_step": base_release_step,
            "frozen_updates": len(frozen_rows),
            "released_updates": len(released_rows),
            "checks": checks,
        },
        rows,
    )


def _run_cell(
    *,
    root: Path,
    contract_path: Path,
    artifact: dict[str, Any],
    initial_snapshot: Path,
    expected_source_sha256: str,
) -> dict[str, Any]:
    condition_id = str(artifact["condition_id"])
    _config_path, config, output_dir = _artifact_config(root, contract_path, artifact)
    output_dir = plain_directory(output_dir, label=f"{condition_id} run")
    max_steps = int(artifact["max_steps"])
    base_release_step = int(artifact["base_release_step"])
    eval_every = int(config["train"]["eval_every"])
    frozen_config_checks = {
        "inline_sidecar": config["functional"].get("route_mode") == "inline_sidecar",
        "branch": (float(config["functional"].get("counterfactual_weight", 0.0)) > 0.0)
        == (artifact["branch"] == "semantic"),
        "seed": int(config["train"]["seed"]) == int(artifact["seed"]),
        "max_steps": int(config["train"]["max_steps"]) == max_steps,
        "base_release_step": int(config["train"]["base_release_step"]) == base_release_step,
        "base_lr": float(config["train"]["learning_rate"]) == float(artifact["base_learning_rate"]),
        "workspace_lr": float(config["train"]["workspace_learning_rate"])
        == float(artifact["workspace_learning_rate"]),
        "fresh": config["train"].get("resume_from") == "none"
        and config["train"].get("allow_schedule_extension") is False,
        "cpu_accumulate": config["train"].get("gradient_accumulation_offload") == "cpu_accumulate",
        "amputation": config["assays"].get("amputation_eval") is True,
    }
    if not all(frozen_config_checks.values()):
        failed = [name for name, passed in frozen_config_checks.items() if not passed]
        raise FinalizeError(f"Frozen config checks failed for {condition_id}: {failed}")

    files = {
        "metrics": regular_file(output_dir / "metrics.jsonl", label="metrics"),
        "ownership": regular_file(output_dir / "update_ownership.jsonl", label="ownership"),
        "resolved_config": regular_file(
            output_dir / "resolved_config.json", label="resolved config"
        ),
        "environment": regular_file(output_dir / "environment.json", label="environment"),
        "optimizer_coverage": regular_file(
            output_dir / "optimizer_coverage.json", label="optimizer coverage"
        ),
        "offload": regular_file(output_dir / "gradient_accumulation_offload.json", label="offload"),
        "amputation": regular_file(output_dir / "amputation_report.json", label="amputation"),
        "manifest": regular_file(output_dir / "final/manifest.json", label="manifest"),
        "experiment_config": regular_file(
            output_dir / "final/experiment_config.json", label="experiment config"
        ),
        "workspace_state": regular_file(
            output_dir / "final/workspace_state.pt", label="workspace state"
        ),
        "completed": regular_file(output_dir / "final/COMPLETED", label="COMPLETED"),
    }
    metrics = load_jsonl(files["metrics"])
    _exact_metric_sequence(metrics, max_steps=max_steps, eval_every=eval_every)
    step0 = metric_view(one_row(metrics, split="eval-step0", step=0))
    final_metrics = metric_view(one_row(metrics, split="eval-final", step=max_steps))
    amputated_metrics = metric_view(one_row(metrics, split="eval-final-amputated", step=max_steps))
    train_rows = [one_row(metrics, split="train", step=step) for step in range(1, max_steps + 1)]
    if any(row.get("window_metrics_phase") != "pre_update_forward" for row in train_rows):
        raise FinalizeError(f"Ambiguous training metric phase for {condition_id}.")
    if any(
        not math.isfinite(float(final_metrics[key]))
        for key in EVAL_KEYS
        if key != "functional_distinct_predicted_classes"
    ):
        raise FinalizeError(f"Non-finite final metric for {condition_id}.")

    resolved = load_json(files["resolved_config"])
    final_config = load_json(files["experiment_config"])
    environment = load_json(files["environment"])
    optimizer_coverage = load_json(files["optimizer_coverage"])
    offload = load_json(files["offload"])
    manifest = load_json(files["manifest"])
    ownership, ownership_rows = _ownership_summary(
        load_jsonl(files["ownership"]),
        max_steps=max_steps,
        base_release_step=base_release_step,
    )
    source_values = {
        str(environment.get("source_sha256")),
        str(offload.get("source_sha256")),
        str(manifest.get("source_sha256")),
    }
    base_coverage_path = output_dir / "base_update_coverage.json"
    base_coverage = load_json(base_coverage_path) if base_coverage_path.is_file() else None
    expected_released = max_steps - base_release_step
    integrity_checks = [
        {
            "id": "resolved_and_final_config_exact",
            "passed": resolved == final_config == config,
            "observed": resolved == final_config == config,
        },
        {
            "id": "manifest_config_binding",
            "passed": manifest.get("config_sha256") == stable_hash(final_config),
            "observed": manifest.get("config_sha256"),
        },
        {
            "id": "complete_bundle",
            "passed": manifest.get("complete") is True
            and int(manifest.get("global_step", -1)) == max_steps
            and files["completed"].read_text(encoding="utf-8") == "ok\n",
            "observed": {
                "complete": manifest.get("complete"),
                "global_step": manifest.get("global_step"),
            },
        },
        {
            "id": "runtime_source_binding",
            "passed": source_values == {expected_source_sha256},
            "observed": sorted(source_values),
        },
        {
            "id": "optimizer_coverage",
            "passed": optimizer_coverage.get("passed") is True,
            "observed": optimizer_coverage.get("checks"),
        },
        {
            "id": "ownership",
            "passed": ownership["passed"],
            "observed": ownership,
        },
        {
            "id": "base_update_coverage_phase",
            "passed": (
                base_coverage is None
                if expected_released == 0
                else bool(base_coverage and base_coverage.get("passed") is True)
            ),
            "observed": None if base_coverage is None else base_coverage.get("checks"),
        },
        {
            "id": "cpu_accumulate_complete",
            "passed": offload.get("status") == "completed"
            and int(offload.get("windows_started", -1)) == max_steps
            and int(offload.get("windows_restored", -1)) == max_steps
            and int(offload.get("live_cpu_buffer_count", -1)) == 0
            and offload.get("active_window") is None,
            "observed": {
                "status": offload.get("status"),
                "windows_started": offload.get("windows_started"),
                "windows_restored": offload.get("windows_restored"),
            },
        },
    ]
    failed = [check["id"] for check in integrity_checks if not check["passed"]]
    if failed:
        raise FinalizeError(f"Integrity failed for {condition_id}: {failed}")
    delta = _delta_summary(initial_snapshot, output_dir / "final/base_model")
    return {
        "condition_id": condition_id,
        "branch": artifact["branch"],
        "seed": int(artifact["seed"]),
        "workspace_learning_rate": float(artifact["workspace_learning_rate"]),
        "base_release_step": base_release_step,
        "run": {
            "path": relative(root, output_dir),
            "run_id": manifest.get("run_id"),
            "artifact_hashes": {name: sha256_file(path) for name, path in files.items()},
        },
        "frozen_config_checks": frozen_config_checks,
        "integrity_status": "PASS",
        "integrity_checks": integrity_checks,
        "step0": step0,
        "final_metrics": final_metrics,
        "amputated_metrics": amputated_metrics,
        "ownership": ownership,
        "ownership_rows": ownership_rows,
        "delta": delta,
    }


def _metric_gate(metrics: dict[str, Any], gates: dict[str, Any]) -> list[dict[str, Any]]:
    recalls = [
        float(metrics["functional_label_0_recall"]),
        float(metrics["functional_label_1_recall"]),
    ]
    checks = [
        (
            "minimum_accuracy",
            float(metrics["functional_query_accuracy"]) >= float(gates["minimum_accuracy"]),
            metrics["functional_query_accuracy"],
            f">= {gates['minimum_accuracy']}",
        ),
        (
            "minimum_label_recall",
            min(recalls) >= float(gates["minimum_label_recall"]),
            recalls,
            f">= {gates['minimum_label_recall']} each",
        ),
        (
            "minimum_distinct_predicted_classes",
            int(metrics["functional_distinct_predicted_classes"])
            >= int(gates["minimum_distinct_predicted_classes"]),
            metrics["functional_distinct_predicted_classes"],
            f">= {gates['minimum_distinct_predicted_classes']}",
        ),
        (
            "maximum_full_vocab_loss",
            float(metrics["functional_full_vocab_loss"]) <= float(gates["maximum_full_vocab_loss"]),
            metrics["functional_full_vocab_loss"],
            f"<= {gates['maximum_full_vocab_loss']}",
        ),
    ]
    return [
        {"id": name, "passed": passed, "observed": observed, "criterion": criterion}
        for name, passed, observed, criterion in checks
    ]


def _load_common(
    args: argparse.Namespace,
) -> tuple[Path, Path, dict[str, Any], Path, str, str]:
    root = plain_directory(args.repo_root.expanduser().resolve(), label="repo root")
    contract_path = regular_file(repo_path(root, args.contract, label="contract"), label="contract")
    contract = load_json(contract_path)
    if contract.get("format") != CONTRACT_FORMAT:
        raise FinalizeError("Unexpected V12 contract format.")
    initial_snapshot = plain_directory(
        args.initial_snapshot.expanduser().resolve(), label="initial snapshot"
    )
    source_commit = _source_commit(args.source_commit)
    source_sha256 = sha256_file(root / "src/latent_workspace_ft_v10/engine.py")
    return (
        root,
        contract_path,
        contract,
        initial_snapshot,
        source_commit,
        source_sha256,
    )


def finalize_step1(args: argparse.Namespace) -> dict[str, Any]:
    root, contract_path, contract, initial, source_commit, source_hash = _load_common(args)
    noop_path = regular_file(
        repo_path(root, args.noop_receipt, label="no-op receipt"),
        label="no-op receipt",
    )
    noop = load_json(noop_path)
    if (
        noop.get("format") != NOOP_FORMAT
        or noop.get("passed") is not True
        or noop.get("contract", {}).get("sha256") != sha256_file(contract_path)
        or noop.get("source", {}).get("commit") != source_commit
    ):
        raise FinalizeError("No-op receipt does not authorize V12.1 selection.")
    stage = contract["v12_1_step1_response"]
    order = [str(value) for value in stage["condition_order"]]
    cells: list[dict[str, Any]] = []
    for lr_id in order:
        artifact = stage["artifacts"][lr_id]
        cell = _run_cell(
            root=root,
            contract_path=contract_path,
            artifact=artifact,
            initial_snapshot=initial,
            expected_source_sha256=source_hash,
        )
        checks = _metric_gate(cell["final_metrics"], stage["gates"])
        checks.extend(
            [
                {
                    "id": "base_exactly_unchanged",
                    "passed": int(cell["delta"]["total_changed_elements"]) == 0,
                    "observed": cell["delta"]["total_changed_elements"],
                    "criterion": 0,
                },
                {
                    "id": "one_frozen_ownership_record",
                    "passed": cell["ownership"]["frozen_updates"] == 1
                    and cell["ownership"]["released_updates"] == 0,
                    "observed": cell["ownership"],
                    "criterion": "one frozen update",
                },
            ]
        )
        cell["gate_checks"] = checks
        cell["eligible"] = all(bool(check["passed"]) for check in checks)
        cells.append(cell)
    eligible = [cell for cell in cells if cell["eligible"]]
    selected = (
        min(
            eligible,
            key=lambda cell: (
                -float(cell["final_metrics"]["functional_query_accuracy"]),
                float(cell["final_metrics"]["functional_choice_loss"]),
                float(cell["workspace_learning_rate"]),
            ),
        )
        if eligible
        else None
    )
    return {
        "format": STEP1_FORMAT,
        "schema_version": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "integrity_status": "PASS",
        "scientific_status": (
            "WORKSPACE_LR_SELECTED" if selected is not None else "NO_STEP1_CELL_PASSED"
        ),
        "contract": {
            "path": relative(root, contract_path),
            "sha256": sha256_file(contract_path),
        },
        "source_commit_at_launch": source_commit,
        "runtime_source_sha256": source_hash,
        "noop_receipt": {
            "path": relative(root, noop_path),
            "sha256": sha256_file(noop_path),
        },
        "cells": cells,
        "selected_learning_rate": (
            None if selected is None else selected["workspace_learning_rate"]
        ),
        "selected_condition_id": (None if selected is None else selected["condition_id"]),
        "stage4_execution_authorized": selected is not None,
        "claim_boundary": contract["claim_boundary"],
    }


def _behavior_models(
    *,
    behavior_path: Path,
    expected_labels: set[str],
    contract: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    receipt = load_json(behavior_path)
    models = receipt.get("models")
    if (
        receipt.get("format") != BEHAVIOR_FORMAT
        or receipt.get("status") != "PASS"
        or not isinstance(models, dict)
        or set(models) != {"original", *expected_labels}
    ):
        raise FinalizeError("Behavior receipt model set or integrity differs from stage.")
    prompt = receipt.get("prompt_suite", {})
    checks = {
        "prompt_suite": prompt.get("sha256") == contract["behavior_veto"]["prompt_suite"]["sha256"],
        "task_dataset": prompt.get("task_dataset_sha256") == contract["data"]["eval"]["sha256"],
        "greedy": receipt.get("decoding", {}).get("freeform", {}).get("do_sample") is False,
    }
    if not all(checks.values()):
        raise FinalizeError("Behavior receipt binding failed.")
    return models, checks


def _attach_behavior(
    *,
    root: Path,
    cell: dict[str, Any],
    model_result: dict[str, Any],
    contract: dict[str, Any],
    expected_source_sha256: str,
) -> None:
    run_path = root / str(cell["run"]["path"])
    binding = model_result.get("binding", {})
    binding_checks = {
        "checkpoint": binding.get("checkpoint") == relative(root, run_path / "final"),
        "manifest": binding.get("manifest_sha256") == sha256_file(run_path / "final/manifest.json"),
        "experiment_config": binding.get("experiment_config_sha256")
        == sha256_file(run_path / "final/experiment_config.json"),
        "workspace_state": binding.get("workspace_state_sha256")
        == sha256_file(run_path / "final/workspace_state.pt"),
        "runtime_source": binding.get("source_sha256") == expected_source_sha256,
        "run_id": binding.get("run_id") == cell["run"]["run_id"],
    }
    if not all(binding_checks.values()):
        failed = [name for name, passed in binding_checks.items() if not passed]
        raise FinalizeError(f"Behavior binding failed for {cell['condition_id']}: {failed}")
    cell["behavior"] = behavior_evaluation(model_result, contract["behavior_veto"])
    cell["behavior_binding_checks"] = binding_checks


def finalize_stage4(args: argparse.Namespace) -> dict[str, Any]:
    root, contract_path, contract, initial, source_commit, source_hash = _load_common(args)
    step1_path = regular_file(
        repo_path(root, args.step1_receipt, label="step-1 receipt"),
        label="step-1 receipt",
    )
    step1 = load_json(step1_path)
    if (
        step1.get("format") != STEP1_FORMAT
        or step1.get("stage4_execution_authorized") is not True
        or step1.get("source_commit_at_launch") != source_commit
        or step1.get("contract", {}).get("sha256") != sha256_file(contract_path)
    ):
        raise FinalizeError("Step-1 receipt does not authorize V12.2.")
    selected_lr = float(step1["selected_learning_rate"])
    artifacts = [
        artifact
        for artifact in contract["v12_2_stage4"]["artifacts"].values()
        if float(artifact["workspace_learning_rate"]) == selected_lr
    ]
    if len(artifacts) != 6:
        raise FinalizeError("Selected stage-4 surface must contain exactly six cells.")
    labels = {str(artifact["condition_id"]) for artifact in artifacts}
    behavior_path = regular_file(
        repo_path(root, args.behavior_receipt, label="behavior receipt"),
        label="behavior receipt",
    )
    models, behavior_checks = _behavior_models(
        behavior_path=behavior_path,
        expected_labels=labels,
        contract=contract,
    )
    cells: list[dict[str, Any]] = []
    stage = contract["v12_2_stage4"]
    for artifact in sorted(artifacts, key=lambda row: str(row["condition_id"])):
        cell = _run_cell(
            root=root,
            contract_path=contract_path,
            artifact=artifact,
            initial_snapshot=initial,
            expected_source_sha256=source_hash,
        )
        _attach_behavior(
            root=root,
            cell=cell,
            model_result=models[cell["condition_id"]],
            contract=contract,
            expected_source_sha256=source_hash,
        )
        checks = _metric_gate(cell["final_metrics"], stage["gates"])
        checks.extend(
            [
                {
                    "id": "base_exactly_unchanged",
                    "passed": int(cell["delta"]["total_changed_elements"]) == 0,
                    "observed": cell["delta"]["total_changed_elements"],
                    "criterion": 0,
                },
                {
                    "id": "four_frozen_ownership_records",
                    "passed": cell["ownership"]["frozen_updates"] == 4
                    and cell["ownership"]["released_updates"] == 0,
                    "observed": cell["ownership"],
                    "criterion": "four frozen updates",
                },
                {
                    "id": "minimum_behavior_task_accuracy",
                    "passed": float(cell["behavior"]["task_accuracy"])
                    >= float(stage["gates"]["minimum_behavior_task_accuracy"])
                    and bool(cell["behavior"]["passed"]),
                    "observed": cell["behavior"],
                    "criterion": stage["gates"]["minimum_behavior_task_accuracy"],
                },
            ]
        )
        cell["gate_checks"] = checks
        cell["eligible"] = all(bool(check["passed"]) for check in checks)
        cells.append(cell)
    branch_promoted = {
        branch: all(cell["eligible"] for cell in cells if cell["branch"] == branch)
        for branch in BRANCHES
    }
    promoted = [branch for branch in BRANCHES if branch_promoted[branch]]
    return {
        "format": STAGE4_FORMAT,
        "schema_version": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "integrity_status": "PASS",
        "scientific_status": ("BRANCH_PROMOTED" if promoted else "NO_STAGE4_BRANCH_PROMOTED"),
        "contract": {
            "path": relative(root, contract_path),
            "sha256": sha256_file(contract_path),
        },
        "source_commit_at_launch": source_commit,
        "runtime_source_sha256": source_hash,
        "step1_receipt": {
            "path": relative(root, step1_path),
            "sha256": sha256_file(step1_path),
        },
        "behavior_receipt": {
            "path": relative(root, behavior_path),
            "sha256": sha256_file(behavior_path),
            "binding_checks": behavior_checks,
        },
        "selected_learning_rate": selected_lr,
        "cells": cells,
        "branch_promoted": branch_promoted,
        "promoted_branches": promoted,
        "refinement16_execution_authorized": bool(promoted),
        "claim_boundary": contract["claim_boundary"],
    }


def _parse_labeled_paths(values: list[str], *, label: str) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise FinalizeError(f"--{label} requires LABEL=PATH values.")
        key, raw_path = value.split("=", 1)
        if not key or not raw_path or key in result:
            raise FinalizeError(f"--{label} contains a duplicate or empty label.")
        result[key] = Path(raw_path)
    return result


def choose_next_design(
    *,
    task_robust: bool,
    semantic_robust: bool,
    semantic_content_specific_seeds: int,
) -> str:
    if semantic_robust and semantic_content_specific_seeds >= 2:
        return "promote_semantic_sidecar"
    if semantic_robust:
        return "stable_redundant_sidecar"
    if task_robust:
        return "task_only_survives"
    return "revisit_route"


def finalize_refinement(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    root, contract_path, contract, initial, source_commit, source_hash = _load_common(args)
    stage4_path = regular_file(
        repo_path(root, args.stage4_receipt, label="stage-4 receipt"),
        label="stage-4 receipt",
    )
    stage4 = load_json(stage4_path)
    promoted = [str(value) for value in stage4.get("promoted_branches", [])]
    if (
        stage4.get("format") != STAGE4_FORMAT
        or stage4.get("refinement16_execution_authorized") is not True
        or stage4.get("source_commit_at_launch") != source_commit
        or stage4.get("contract", {}).get("sha256") != sha256_file(contract_path)
        or not promoted
    ):
        raise FinalizeError("Stage-4 receipt does not authorize V12.3.")
    selected_lr = float(stage4["selected_learning_rate"])
    artifacts = [
        artifact
        for artifact in contract["v12_3_refinement16"]["artifacts"].values()
        if float(artifact["workspace_learning_rate"]) == selected_lr
        and str(artifact["branch"]) in promoted
    ]
    expected_count = 3 * len(promoted)
    if len(artifacts) != expected_count:
        raise FinalizeError("Refinement artifact set differs from promoted branches.")
    labels = {str(artifact["condition_id"]) for artifact in artifacts}
    behavior_path = regular_file(
        repo_path(root, args.behavior_receipt, label="behavior receipt"),
        label="behavior receipt",
    )
    models, behavior_checks = _behavior_models(
        behavior_path=behavior_path,
        expected_labels=labels,
        contract=contract,
    )
    necessity_paths = _parse_labeled_paths(args.necessity, label="necessity")
    if set(necessity_paths) != labels:
        raise FinalizeError("Necessity receipts do not cover every promoted cell.")
    stage = contract["v12_3_refinement16"]
    cells: list[dict[str, Any]] = []
    necessity_rows: list[dict[str, Any]] = []
    for artifact in sorted(artifacts, key=lambda row: str(row["condition_id"])):
        cell = _run_cell(
            root=root,
            contract_path=contract_path,
            artifact=artifact,
            initial_snapshot=initial,
            expected_source_sha256=source_hash,
        )
        _attach_behavior(
            root=root,
            cell=cell,
            model_result=models[cell["condition_id"]],
            contract=contract,
            expected_source_sha256=source_hash,
        )
        checks = _metric_gate(cell["final_metrics"], stage["gates"])
        checks.extend(
            [
                {
                    "id": "four_frozen_then_twelve_joint_updates",
                    "passed": cell["ownership"]["frozen_updates"] == 4
                    and cell["ownership"]["released_updates"] == 12,
                    "observed": cell["ownership"],
                    "criterion": {"frozen": 4, "released": 12},
                },
                {
                    "id": "nonzero_persisted_base_update",
                    "passed": int(cell["delta"]["total_changed_elements"]) > 0,
                    "observed": cell["delta"]["total_changed_elements"],
                    "criterion": "> 0",
                },
                {
                    "id": "minimum_behavior_task_accuracy",
                    "passed": float(cell["behavior"]["task_accuracy"])
                    >= float(stage["gates"]["minimum_behavior_task_accuracy"])
                    and bool(cell["behavior"]["passed"]),
                    "observed": cell["behavior"],
                    "criterion": stage["gates"]["minimum_behavior_task_accuracy"],
                },
            ]
        )
        cell["gate_checks"] = checks
        cell["eligible"] = all(bool(check["passed"]) for check in checks)
        cells.append(cell)

        necessity_path = regular_file(
            repo_path(
                root,
                necessity_paths[cell["condition_id"]],
                label=f"necessity {cell['condition_id']}",
            ),
            label=f"necessity {cell['condition_id']}",
        )
        necessity_value = load_json(necessity_path)
        expected_checkpoint = str((root / cell["run"]["path"] / "final").resolve())
        if (
            necessity_value.get("source_sha256") != source_hash
            or str(Path(str(necessity_value.get("checkpoint"))).resolve()) != expected_checkpoint
        ):
            raise FinalizeError(f"Necessity binding failed for {cell['condition_id']}.")
        necessity_rows.append(
            {
                "condition_id": cell["condition_id"],
                "branch": cell["branch"],
                "seed": cell["seed"],
                "path": relative(root, necessity_path),
                "sha256": sha256_file(necessity_path),
                **necessity_summary(necessity_value),
            }
        )
    branch_robust = {
        branch: (
            branch in promoted
            and all(cell["eligible"] for cell in cells if cell["branch"] == branch)
        )
        for branch in BRANCHES
    }
    semantic_specific = sum(
        int(row["content_specific"]) for row in necessity_rows if row["branch"] == "semantic"
    )
    decision = choose_next_design(
        task_robust=branch_robust["task"],
        semantic_robust=branch_robust["semantic"],
        semantic_content_specific_seeds=semantic_specific,
    )
    receipt = {
        "format": FINAL_FORMAT,
        "schema_version": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "integrity_status": "PASS",
        "scientific_status": "REFINEMENT_COMPARED",
        "contract": {
            "path": relative(root, contract_path),
            "sha256": sha256_file(contract_path),
        },
        "source_commit_at_launch": source_commit,
        "runtime_source_sha256": source_hash,
        "stage4_receipt": {
            "path": relative(root, stage4_path),
            "sha256": sha256_file(stage4_path),
        },
        "behavior_receipt": {
            "path": relative(root, behavior_path),
            "sha256": sha256_file(behavior_path),
            "binding_checks": behavior_checks,
        },
        "selected_learning_rate": selected_lr,
        "promoted_branches": promoted,
        "cells": cells,
        "branch_robust": branch_robust,
        "necessity": necessity_rows,
        "semantic_content_specific_seed_count": semantic_specific,
        "selected_next_rule": decision,
        "claim_boundary": contract["claim_boundary"],
    }
    handoff = {
        "format": NEXT_FORMAT,
        "schema_version": 1,
        "created_utc": receipt["created_utc"],
        "status": "DESIGN_ONLY",
        "selected_rule": decision,
        "decision_inputs": {
            "task_branch_robust": branch_robust["task"],
            "semantic_branch_robust": branch_robust["semantic"],
            "semantic_content_specific_seed_count": semantic_specific,
        },
        "execution_authority": {
            "v13_training_authorized": False,
            "14b_scale_up_authorized": False,
            "broader_sweep_authorized": False,
        },
        "claim_boundary": contract["claim_boundary"],
    }
    return receipt, handoff


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--repo-root", type=Path, default=Path("."))
        subparser.add_argument("--contract", type=Path, default=Path("configs/v12/CONTRACT.json"))
        subparser.add_argument("--initial-snapshot", type=Path, required=True)
        subparser.add_argument("--source-commit", required=True)
        subparser.add_argument("--output", type=Path, required=True)
        subparser.add_argument("--overwrite", action="store_true")

    step1 = subparsers.add_parser("step1")
    common(step1)
    step1.add_argument("--noop-receipt", type=Path, required=True)

    stage4 = subparsers.add_parser("stage4")
    common(stage4)
    stage4.add_argument("--step1-receipt", type=Path, required=True)
    stage4.add_argument("--behavior-receipt", type=Path, required=True)

    refinement = subparsers.add_parser("refinement")
    common(refinement)
    refinement.add_argument("--stage4-receipt", type=Path, required=True)
    refinement.add_argument("--behavior-receipt", type=Path, required=True)
    refinement.add_argument("--necessity", action="append", default=[])
    refinement.add_argument("--next-output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.repo_root.expanduser().resolve()
    output = repo_path(root, args.output, label="output")
    if args.command == "step1":
        receipt = finalize_step1(args)
        atomic_write(output, receipt, overwrite=args.overwrite)
        print(f"WROTE {relative(root, output)}")
        print(f"selected_learning_rate={receipt['selected_learning_rate']}")
        return 0 if receipt["stage4_execution_authorized"] else 2
    if args.command == "stage4":
        receipt = finalize_stage4(args)
        atomic_write(output, receipt, overwrite=args.overwrite)
        print(f"WROTE {relative(root, output)}")
        print(f"promoted_branches={receipt['promoted_branches']}")
        return 0 if receipt["refinement16_execution_authorized"] else 2
    receipt, handoff = finalize_refinement(args)
    atomic_write(output, receipt, overwrite=args.overwrite)
    handoff["refinement_receipt"] = {
        "path": relative(root, output),
        "sha256": sha256_file(output),
    }
    next_output = repo_path(root, args.next_output, label="next output")
    atomic_write(next_output, handoff, overwrite=args.overwrite)
    print(f"WROTE {relative(root, output)}")
    print(f"WROTE {relative(root, next_output)}")
    print(f"selected_next_rule={receipt['selected_next_rule']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
