#!/usr/bin/env python3
"""Finalize the frozen V11 one-update F1 learning-rate response surface."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from run_v10_matrix import compare_full_update_safetensors

FORMAT = "latent-workspace-ft-v11-update-response-receipt-v1"
CONTRACT_FORMAT = "latent-workspace-ft-v11-update-response-contract-v1"
BEHAVIOR_FORMAT = "latent-workspace-v10-generation-behavior-v1"

EVAL_KEYS = (
    "functional_choice_loss",
    "functional_full_vocab_loss",
    "functional_query_accuracy",
    "functional_label_0_recall",
    "functional_label_1_recall",
    "functional_distinct_predicted_classes",
    "functional_prediction_entropy_nats",
    "functional_yes_minus_no_gap",
    "functional_hop_1_accuracy",
)
PREUPDATE_KEYS = (
    *EVAL_KEYS,
    "functional_choice_margin",
    "grad_norm",
    "base_grad_norm",
    "base_clip_coefficient",
    "window_metrics_phase",
)


class FinalizeError(RuntimeError):
    """The frozen response surface cannot be finalized fail-closed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FinalizeError(f"Unreadable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FinalizeError(f"Expected a JSON object: {path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise FinalizeError(
                        f"Metrics line {line_number} is not a JSON object."
                    )
                rows.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FinalizeError(f"Unreadable metrics JSONL: {path}") from exc
    if not rows:
        raise FinalizeError(f"Metrics JSONL is empty: {path}")
    return rows


def repo_path(root: Path, value: str | Path, *, label: str) -> Path:
    path = Path(value).expanduser()
    resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise FinalizeError(f"{label} must stay inside --repo-root.") from exc
    return resolved


def regular_file(path: Path, *, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise FinalizeError(f"{label} must be a regular non-symlink file.")
    return path


def plain_directory(path: Path, *, label: str) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise FinalizeError(f"{label} must be a non-symlink directory.")
    return path


def relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def one_row(rows: list[dict[str, Any]], *, split: str, step: int) -> dict[str, Any]:
    matches = [
        row
        for row in rows
        if row.get("split") == split and int(row.get("step", -1)) == step
    ]
    if len(matches) != 1:
        raise FinalizeError(f"Expected exactly one {split} row at step {step}.")
    return matches[0]


def metric_view(row: dict[str, Any], keys: tuple[str, ...] = EVAL_KEYS) -> dict[str, Any]:
    missing = [key for key in keys if key not in row]
    if missing:
        raise FinalizeError(f"Metric row is missing required keys: {missing}")
    return {key: row[key] for key in keys}


def gate_evaluation(
    step0: dict[str, Any],
    final: dict[str, Any],
    *,
    changed_elements: int,
    gates: dict[str, Any],
) -> list[dict[str, Any]]:
    choice_loss = float(final["functional_choice_loss"])
    full_vocab_loss = float(final["functional_full_vocab_loss"])
    accuracy = float(final["functional_query_accuracy"])
    recalls = [
        float(final["functional_label_0_recall"]),
        float(final["functional_label_1_recall"]),
    ]
    distinct = int(final["functional_distinct_predicted_classes"])
    finite = all(
        math.isfinite(float(final[key]))
        for key in EVAL_KEYS
        if key != "functional_distinct_predicted_classes"
    )
    max_choice = float(step0["functional_choice_loss"]) + float(
        gates["maximum_choice_loss_increase"]
    )
    max_full_vocab = float(step0["functional_full_vocab_loss"]) + float(
        gates["maximum_full_vocab_loss_increase"]
    )
    return [
        {
            "id": "nonzero_persisted_base_update",
            "criterion": "> 0 exact changed elements",
            "observed": changed_elements,
            "passed": changed_elements > 0,
        },
        {
            "id": "minimum_distinct_predicted_classes",
            "criterion": f">= {int(gates['minimum_distinct_predicted_classes'])}",
            "observed": distinct,
            "passed": distinct >= int(gates["minimum_distinct_predicted_classes"]),
        },
        {
            "id": "minimum_accuracy",
            "criterion": f">= {float(gates['minimum_accuracy'])}",
            "observed": accuracy,
            "passed": accuracy >= float(gates["minimum_accuracy"]),
        },
        {
            "id": "minimum_label_recall",
            "criterion": f">= {float(gates['minimum_label_recall'])} each",
            "observed": recalls,
            "passed": min(recalls) >= float(gates["minimum_label_recall"]),
        },
        {
            "id": "maximum_choice_loss_increase",
            "criterion": f"<= {max_choice}",
            "observed": choice_loss,
            "passed": choice_loss <= max_choice,
        },
        {
            "id": "maximum_full_vocab_loss_increase",
            "criterion": f"<= {max_full_vocab}",
            "observed": full_vocab_loss,
            "passed": full_vocab_loss <= max_full_vocab,
        },
        {
            "id": "finite_decision_metrics",
            "criterion": "all required decision metrics finite",
            "observed": finite,
            "passed": finite,
        },
    ]


def completion_diagnostics(token_ids: list[int]) -> dict[str, Any]:
    if not token_ids:
        return {
            "tokens": 0,
            "unique_tokens": 0,
            "unique_token_fraction": 0.0,
            "top_token_fraction": 0.0,
            "maximum_single_token_run": 0,
        }
    counts: dict[int, int] = {}
    maximum_run = 1
    current_run = 1
    for index, token in enumerate(token_ids):
        counts[token] = counts.get(token, 0) + 1
        if index > 0 and token == token_ids[index - 1]:
            current_run += 1
            maximum_run = max(maximum_run, current_run)
        else:
            current_run = 1
    return {
        "tokens": len(token_ids),
        "unique_tokens": len(counts),
        "unique_token_fraction": len(counts) / len(token_ids),
        "top_token_fraction": max(counts.values()) / len(token_ids),
        "maximum_single_token_run": maximum_run,
    }


def behavior_evaluation(
    model_result: dict[str, Any],
    veto: dict[str, Any],
) -> dict[str, Any]:
    task = model_result.get("task_native")
    freeform = model_result.get("freeform")
    if not isinstance(task, dict) or not isinstance(freeform, list) or not freeform:
        raise FinalizeError("Behavior receipt lacks task-native or free-form results.")
    cases = task.get("cases")
    if not isinstance(cases, list) or not cases:
        raise FinalizeError("Behavior receipt has no task-native cases.")
    choices = {str(case.get("generated_choice")) for case in cases}
    diagnostics: list[dict[str, Any]] = []
    for row in freeform:
        token_ids = row.get("completion_token_ids")
        if not isinstance(token_ids, list) or any(not isinstance(v, int) for v in token_ids):
            raise FinalizeError("Behavior completion token ids are malformed.")
        diagnostics.append(
            {"prompt_id": row.get("id"), **completion_diagnostics(token_ids)}
        )
    checks = [
        {
            "id": "minimum_task_subset_accuracy",
            "observed": float(task["accuracy"]),
            "criterion": f">= {float(veto['minimum_task_subset_accuracy'])}",
            "passed": float(task["accuracy"])
            >= float(veto["minimum_task_subset_accuracy"]),
        },
        {
            "id": "minimum_distinct_task_choices",
            "observed": sorted(choices),
            "criterion": f">= {int(veto['minimum_distinct_task_choices'])} choices",
            "passed": len(choices) >= int(veto["minimum_distinct_task_choices"]),
        },
        {
            "id": "maximum_single_token_run",
            "observed": max(row["maximum_single_token_run"] for row in diagnostics),
            "criterion": f"<= {int(veto['maximum_single_token_run'])}",
            "passed": max(row["maximum_single_token_run"] for row in diagnostics)
            <= int(veto["maximum_single_token_run"]),
        },
        {
            "id": "maximum_top_token_fraction",
            "observed": max(row["top_token_fraction"] for row in diagnostics),
            "criterion": f"<= {float(veto['maximum_top_token_fraction'])}",
            "passed": max(row["top_token_fraction"] for row in diagnostics)
            <= float(veto["maximum_top_token_fraction"]),
        },
    ]
    return {
        "passed": all(bool(check["passed"]) for check in checks),
        "task_accuracy": float(task["accuracy"]),
        "task_choices": sorted(choices),
        "checks": checks,
        "freeform_diagnostics": diagnostics,
    }


def selection_key(condition: dict[str, Any]) -> tuple[float, ...]:
    final = condition["post_update"]
    return (
        float(final["functional_choice_loss"]),
        -float(final["functional_query_accuracy"]),
        -min(
            float(final["functional_label_0_recall"]),
            float(final["functional_label_1_recall"]),
        ),
        float(final["functional_full_vocab_loss"]),
        -float(condition["delta"]["changed_element_fraction"]),
        -float(condition["learning_rate"]),
    )


def atomic_write(path: Path, value: dict[str, Any], *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists() and not overwrite:
            raise FinalizeError("Output exists; pass --overwrite to replace it.")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def finalize(args: argparse.Namespace) -> dict[str, Any]:
    root = plain_directory(args.repo_root.expanduser().resolve(), label="repo root")
    contract_path = regular_file(
        repo_path(root, args.contract, label="contract"), label="contract"
    )
    behavior_path = regular_file(
        repo_path(root, args.behavior_receipt, label="behavior receipt"),
        label="behavior receipt",
    )
    initial_snapshot = plain_directory(
        args.initial_snapshot.expanduser().resolve(), label="initial snapshot"
    )
    contract = load_json(contract_path)
    behavior = load_json(behavior_path)
    if contract.get("format") != CONTRACT_FORMAT:
        raise FinalizeError("Unexpected update-response contract format.")
    if re.fullmatch(r"[0-9a-f]{40}", args.source_commit) is None:
        raise FinalizeError("--source-commit must be a full lowercase Git commit.")
    if behavior.get("format") != BEHAVIOR_FORMAT or behavior.get("status") != "PASS":
        raise FinalizeError("Behavior capture did not complete with PASS integrity.")

    gate_binding = contract["no_update_control"]
    gate_path = regular_file(
        (contract_path.parent / str(gate_binding["path"])).resolve(),
        label="Gate-0 control receipt",
    )
    if sha256_file(gate_path) != str(gate_binding["sha256"]):
        raise FinalizeError("Gate-0 control receipt changed.")
    gate = load_json(gate_path)
    gate_f1 = gate["conditions"]["F1_inline"]
    control_view = {
        "functional_choice_loss": gate_f1["choice_loss"],
        "functional_full_vocab_loss": gate_f1["full_vocab_loss"],
        "functional_query_accuracy": gate_f1["accuracy"],
        "functional_label_0_recall": gate_f1["per_label"]["0"]["recall"],
        "functional_label_1_recall": gate_f1["per_label"]["1"]["recall"],
        "functional_distinct_predicted_classes": gate_f1[
            "distinct_predicted_classes"
        ],
        "functional_prediction_entropy_nats": gate_f1["prediction_entropy_nats"],
        "functional_yes_minus_no_gap": gate_f1["mean_yes_minus_no_gap"],
        "functional_hop_1_accuracy": gate_f1["per_hop"]["1"]["accuracy"],
    }

    behavior_models = behavior.get("models")
    if not isinstance(behavior_models, dict):
        raise FinalizeError("Behavior receipt has no models mapping.")
    conditions: list[dict[str, Any]] = []
    step0_hashes: set[str] = set()
    preupdate_hashes: set[str] = set()
    source_hashes: set[str] = set()

    for condition_id in contract["execution"]["condition_order"]:
        artifact = contract["artifacts"][condition_id]
        learning_rate = float(artifact["learning_rate"])
        config_binding = artifact["step1"]
        config_path = regular_file(
            (contract_path.parent / str(config_binding["path"])).resolve(),
            label=f"{condition_id} config",
        )
        if sha256_file(config_path) != str(config_binding["sha256"]):
            raise FinalizeError(f"Frozen config changed for {condition_id}.")
        config = load_json(config_path)
        output_dir = (config_path.parent / str(config["train"]["output_dir"])).resolve()
        try:
            output_dir.relative_to(root)
        except ValueError as exc:
            raise FinalizeError(f"Run output escapes repo for {condition_id}.") from exc
        output_dir = plain_directory(output_dir, label=f"{condition_id} run")

        paths = {
            "metrics": regular_file(output_dir / "metrics.jsonl", label="metrics"),
            "resolved_config": regular_file(
                output_dir / "resolved_config.json", label="resolved config"
            ),
            "environment": regular_file(
                output_dir / "environment.json", label="environment"
            ),
            "optimizer_coverage": regular_file(
                output_dir / "optimizer_coverage.json", label="optimizer coverage"
            ),
            "base_update_coverage": regular_file(
                output_dir / "base_update_coverage.json", label="base update coverage"
            ),
            "offload": regular_file(
                output_dir / "gradient_accumulation_offload.json", label="offload"
            ),
            "manifest": regular_file(
                output_dir / "final" / "manifest.json", label="manifest"
            ),
            "experiment_config": regular_file(
                output_dir / "final" / "experiment_config.json",
                label="experiment config",
            ),
            "completed": regular_file(
                output_dir / "final" / "COMPLETED", label="COMPLETED"
            ),
        }
        metrics = load_jsonl(paths["metrics"])
        step0 = one_row(metrics, split="eval-step0", step=0)
        train = one_row(metrics, split="train", step=1)
        post_update = one_row(metrics, split="eval", step=1)
        final_eval = one_row(metrics, split="eval-final", step=1)
        step0_view = metric_view(step0)
        post_update_view = metric_view(post_update)
        final_view = metric_view(final_eval)
        if post_update_view != final_view:
            raise FinalizeError(f"Post-update/final eval mismatch for {condition_id}.")
        step0_hashes.add(stable_hash(step0_view))
        preupdate_view = metric_view(train, PREUPDATE_KEYS)
        preupdate_hashes.add(stable_hash(preupdate_view))

        resolved = load_json(paths["resolved_config"])
        final_config = load_json(paths["experiment_config"])
        environment = load_json(paths["environment"])
        optimizer_coverage = load_json(paths["optimizer_coverage"])
        base_coverage = load_json(paths["base_update_coverage"])
        offload = load_json(paths["offload"])
        manifest = load_json(paths["manifest"])
        source_hashes.update(
            str(value)
            for value in (
                environment.get("source_sha256"),
                offload.get("source_sha256"),
                manifest.get("source_sha256"),
            )
        )
        applied_lrs = {
            float(parameter["learning_rate"])
            for parameter in base_coverage.get("parameters", [])
        }
        base_checks = base_coverage.get("checks", {})
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
                "id": "complete_one_step_bundle",
                "passed": (
                    manifest.get("complete") is True
                    and int(manifest.get("global_step", -1)) == 1
                    and paths["completed"].read_text(encoding="utf-8") == "ok\n"
                ),
                "observed": {
                    "complete": manifest.get("complete"),
                    "global_step": manifest.get("global_step"),
                },
            },
            {
                "id": "optimizer_coverage",
                "passed": optimizer_coverage.get("passed") is True,
                "observed": optimizer_coverage.get("checks"),
            },
            {
                "id": "base_update_coverage",
                "passed": bool(base_checks)
                and all(value is True for value in base_checks.values()),
                "observed": base_checks,
            },
            {
                "id": "applied_learning_rate",
                "passed": applied_lrs == {learning_rate}
                and float(train["applied_lr_base"]) == learning_rate,
                "observed": {
                    "coverage_learning_rates": sorted(applied_lrs),
                    "train_applied_lr_base": train.get("applied_lr_base"),
                    "post_scheduler_lr_base": train.get("lr_base"),
                },
                "expected": learning_rate,
            },
            {
                "id": "cpu_accumulate_complete",
                "passed": (
                    offload.get("status") == "completed"
                    and int(offload.get("windows_started", -1)) == 1
                    and int(offload.get("windows_restored", -1)) == 1
                    and int(offload.get("microbatch_spills", -1)) == 8
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

        delta = compare_full_update_safetensors(
            initial_snapshot,
            output_dir / "final" / "base_model",
        )
        total_numel = int(delta["initial_semantic"]["total_numel"])
        changed_elements = int(delta["total_changed_elements"])
        delta_summary = {
            "tensor_count": int(delta["tensor_count"]),
            "changed_tensor_count": int(delta["changed_tensor_count"]),
            "unchanged_tensor_count": int(delta["unchanged_tensor_count"]),
            "total_numel": total_numel,
            "total_changed_elements": changed_elements,
            "changed_element_fraction": changed_elements / total_numel,
            "tensor_schema_sha256": delta["initial_semantic"][
                "tensor_schema_sha256"
            ],
            "performance": delta["performance"],
            "tensors": delta["tensors"],
        }
        scientific_checks = gate_evaluation(
            step0_view,
            post_update_view,
            changed_elements=changed_elements,
            gates=contract["post_update_eligibility_gates"],
        )
        if condition_id not in behavior_models:
            raise FinalizeError(f"Behavior capture omitted {condition_id}.")
        behavior_result = behavior_evaluation(
            behavior_models[condition_id],
            contract["behavior_veto"],
        )
        eligible = all(bool(check["passed"]) for check in scientific_checks) and bool(
            behavior_result["passed"]
        )
        conditions.append(
            {
                "condition_id": condition_id,
                "learning_rate": learning_rate,
                "run": {
                    "path": relative(root, output_dir),
                    "run_id": manifest.get("run_id"),
                    "source_sha256": manifest.get("source_sha256"),
                    "artifact_hashes": {
                        name: sha256_file(path) for name, path in paths.items()
                    },
                },
                "integrity_status": "PASS",
                "step0": step0_view,
                "pre_update_window": preupdate_view,
                "post_update": post_update_view,
                "delta": delta_summary,
                "scientific_checks": scientific_checks,
                "behavior": behavior_result,
                "eligible": eligible,
            }
        )

    if len(step0_hashes) != 1:
        raise FinalizeError("Step-0 metrics differ across learning-rate conditions.")
    if metric_view(conditions[0]["step0"]) != control_view:
        raise FinalizeError("Response-surface step 0 differs from qualified Gate-0.")
    if len(preupdate_hashes) != 1:
        raise FinalizeError("Pre-update window metrics differ across conditions.")
    if len(source_hashes) != 1:
        raise FinalizeError("Runtime source digests differ across conditions.")

    eligible_conditions = [condition for condition in conditions if condition["eligible"]]
    ranked = sorted(eligible_conditions, key=selection_key)
    selected = ranked[0]["condition_id"] if ranked else None
    return {
        "format": FORMAT,
        "schema_version": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "integrity_status": "PASS",
        "scientific_status": "SELECTED" if selected is not None else "BLOCKED",
        "question": contract["question"],
        "contract": {
            "path": relative(root, contract_path),
            "sha256": sha256_file(contract_path),
        },
        "source_commit_at_launch": args.source_commit,
        "source_commit_binding": (
            "Remote clean HEAD observed before the first condition and rechecked "
            "after the surface; engine bytes are independently bound by the "
            "single matched runtime_source_sha256."
        ),
        "behavior_receipt": {
            "path": relative(root, behavior_path),
            "sha256": sha256_file(behavior_path),
        },
        "no_update_control": {
            "receipt_path": relative(root, gate_path),
            "receipt_sha256": sha256_file(gate_path),
            "metrics": control_view,
        },
        "matched_surface": {
            "step0_metrics_sha256": next(iter(step0_hashes)),
            "pre_update_window_metrics_sha256": next(iter(preupdate_hashes)),
            "runtime_source_sha256": next(iter(source_hashes)),
            "exact_step0_parity": True,
            "exact_pre_update_window_metrics": True,
        },
        "conditions": conditions,
        "eligible_condition_ids": [condition["condition_id"] for condition in ranked],
        "selected_condition_id": selected,
        "step4_launch_authorized": selected is not None,
        "claim_boundary": contract["claim_boundary"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument(
        "--contract", type=Path, default=Path("configs/v11/UPDATE_RESPONSE_CONTRACT.json")
    )
    parser.add_argument("--initial-snapshot", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--behavior-receipt", type=Path, required=True)
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
        print(f"ERROR: {message}", file=os.sys.stderr)
        return 2
    print(f"WROTE {relative(root, output)}")
    print(f"scientific_status={receipt['scientific_status']}")
    print(f"selected_condition_id={receipt['selected_condition_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
