#!/usr/bin/env python3
"""Qualify the exact F0/F1 step-0 instrument before any v11 update.

The gate uses the current grouped-world collator and
``LatentWorkspaceCausalLM`` wrapper, then independently calls the wrapped base
model on the exact flattened tensors. It writes a receipt even when a gate
fails and exits non-zero without starting training.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F

from latent_workspace_ft_v10.engine import (
    CausalFineTuningCollator,
    ExperimentConfig,
    JsonlFineTuningDataset,
    autocast_context,
    build_eval_dataloader,
    build_workspace_model,
    configure_runtime_math,
    functional_batch_kwargs,
    move_batch_to_device,
    require_cuda_allocator_policy,
    resolve_device,
    resolve_mixed_precision,
    runtime_environment,
    set_global_seed,
)

FORMAT = "latent-workspace-ft-v11-gate0-receipt-v1"
CONTRACT_FORMAT = "latent-workspace-ft-v11-gate0-contract-v1"


class Gate0Error(RuntimeError):
    """The frozen gate contract or execution surface is invalid."""


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def wilson_lower_bound(correct: int, total: int, z: float) -> float:
    if total <= 0:
        return 0.0
    proportion = float(correct) / float(total)
    z_squared = float(z) ** 2
    denominator = 1.0 + z_squared / float(total)
    center = proportion + z_squared / (2.0 * float(total))
    radius = float(z) * math.sqrt(
        (proportion * (1.0 - proportion) / float(total))
        + z_squared / (4.0 * float(total) ** 2)
    )
    return (center - radius) / denominator


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Gate0Error(f"{label} is not readable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise Gate0Error(f"{label} must contain a JSON object.")
    return value


def load_contract(path: Path) -> dict[str, Any]:
    contract = _read_json(path, label="Gate-0 contract")
    if contract.get("format") != CONTRACT_FORMAT:
        raise Gate0Error(f"Gate-0 contract format must be {CONTRACT_FORMAT!r}.")
    if contract.get("frozen_before_execution") is not True:
        raise Gate0Error("Gate-0 thresholds were not frozen before execution.")
    conditions = contract.get("conditions")
    if conditions != [
        {"id": "F0_query_only", "route_mode": "query_only"},
        {"id": "F1_inline", "route_mode": "inline"},
    ]:
        raise Gate0Error("Gate-0 conditions must be the exact F0/F1 pair.")
    gates = contract.get("gates")
    if not isinstance(gates, dict):
        raise Gate0Error("Gate-0 contract has no gates object.")
    required = {
        "wilson_z",
        "minimum_f1_overall_wilson_lower_bound",
        "minimum_f1_hop1_wilson_lower_bound",
        "minimum_f1_minus_f0_accuracy",
        "minimum_f1_label_recall",
        "minimum_f1_distinct_predicted_classes",
        "require_balanced_targets",
        "require_exact_direct_wrapper_logits",
        "require_exact_direct_wrapper_predictions",
    }
    if set(gates) != required:
        raise Gate0Error(
            "Gate-0 gate set changed; "
            f"missing={sorted(required - set(gates))}, "
            f"extra={sorted(set(gates) - required)}."
        )
    return contract


def _resolve_from_contract(contract_path: Path, raw: str, *, label: str) -> Path:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = contract_path.parent / candidate
    resolved = candidate.resolve()
    if not resolved.is_file():
        raise Gate0Error(f"{label} is missing: {resolved}")
    return resolved


def git_snapshot(repo_root: Path) -> dict[str, Any]:
    def run(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    try:
        commit = run("rev-parse", "HEAD")
        branch = run("branch", "--show-current")
        status = run("status", "--porcelain=v1")
        remote = run("remote", "get-url", "origin")
    except (OSError, subprocess.CalledProcessError) as exc:
        return {"available": False, "error": type(exc).__name__}
    return {
        "available": True,
        "commit": commit,
        "branch": branch,
        "remote": remote,
        "clean": status == "",
        "status_porcelain": status.splitlines(),
    }


def flatten_functional_batch(
    batch: Mapping[str, torch.Tensor],
    route_mode: str,
) -> dict[str, torch.Tensor]:
    valid = batch["functional_query_valid_mask"]
    answers = batch["functional_answer_classes"]
    batch_size, query_count = valid.shape
    flat_valid = valid[:, None, :].expand(batch_size, 2, query_count).reshape(-1)
    positions = torch.nonzero(flat_valid, as_tuple=False).flatten()
    world_grid = (
        torch.arange(batch_size, device=valid.device)[:, None, None]
        .expand(batch_size, 2, query_count)
        .reshape(-1)
    )
    side_grid = (
        torch.arange(2, device=valid.device)[None, :, None]
        .expand(batch_size, 2, query_count)
        .reshape(-1)
    )
    query_grid = (
        torch.arange(query_count, device=valid.device)[None, None, :]
        .expand(batch_size, 2, query_count)
        .reshape(-1)
    )
    worlds = world_grid[positions]
    sides = side_grid[positions]
    queries = query_grid[positions]
    if route_mode == "inline":
        input_key = "functional_inline_input_ids"
        mask_key = "functional_inline_attention_mask"
        label_key = "functional_inline_labels"
        choice_key = "functional_inline_choice_ids"
    elif route_mode == "query_only":
        input_key = "functional_query_input_ids"
        mask_key = "functional_query_attention_mask"
        label_key = "functional_query_labels"
        choice_key = "functional_query_choice_ids"
    else:
        raise Gate0Error(f"Gate-0 does not admit route_mode={route_mode!r}.")
    return {
        "input_ids": batch[input_key].reshape(batch_size * 2 * query_count, -1)[
            positions
        ],
        "attention_mask": batch[mask_key].reshape(
            batch_size * 2 * query_count, -1
        )[positions],
        "labels": batch[label_key].reshape(batch_size * 2 * query_count, -1)[
            positions
        ],
        "candidate_ids": batch[choice_key].reshape(
            batch_size * 2 * query_count, -1
        )[positions],
        "answer_classes": answers.reshape(batch_size * 2 * query_count)[positions],
        "world_indices": worlds,
        "side_indices": sides,
        "query_indices": queries,
        "sample_indices": batch["sample_indices"].index_select(0, worlds),
        "hop_distances": batch["functional_hop_distances"][worlds, queries],
        "affected": batch["functional_affected_mask"][worlds, queries],
        "heldout": batch["functional_heldout_mask"][worlds, queries],
    }


def _maximum_absolute_difference(left: torch.Tensor, right: torch.Tensor) -> float:
    maximum = 0.0
    for row in range(left.shape[0]):
        observed = float(
            (left[row].float() - right[row].float()).abs().max().item()
        )
        maximum = max(maximum, observed)
    return maximum


def _summarize_cases(
    rows: Sequence[Mapping[str, Any]],
    *,
    choice_nll_sum: float,
    full_vocab_nll_sum: float,
    wilson_z: float,
) -> dict[str, Any]:
    total = len(rows)
    correct = sum(int(row["prediction"] == row["target"]) for row in rows)
    target_counts: dict[int, int] = {}
    prediction_counts: dict[int, int] = {}
    label_correct: dict[int, int] = {}
    hop_counts: dict[int, int] = {}
    hop_correct: dict[int, int] = {}
    margin_sum = 0.0
    signed_gap_sum = 0.0
    for row in rows:
        target = int(row["target"])
        prediction = int(row["prediction"])
        hop = int(row["hop_distance"])
        is_correct = int(target == prediction)
        target_counts[target] = target_counts.get(target, 0) + 1
        prediction_counts[prediction] = prediction_counts.get(prediction, 0) + 1
        label_correct[target] = label_correct.get(target, 0) + is_correct
        hop_counts[hop] = hop_counts.get(hop, 0) + 1
        hop_correct[hop] = hop_correct.get(hop, 0) + is_correct
        margin_sum += float(row["target_margin"])
        signed_gap_sum += float(row["yes_minus_no_gap"])
    probabilities = [count / total for count in prediction_counts.values() if count]
    return {
        "examples": total,
        "correct": correct,
        "accuracy": correct / max(total, 1),
        "accuracy_wilson_lower_bound": wilson_lower_bound(correct, total, wilson_z),
        "choice_loss": choice_nll_sum / max(total, 1),
        "full_vocab_loss": full_vocab_nll_sum / max(total, 1),
        "mean_target_margin": margin_sum / max(total, 1),
        "mean_yes_minus_no_gap": signed_gap_sum / max(total, 1),
        "prediction_entropy_nats": -sum(
            probability * math.log(probability) for probability in probabilities
        ),
        "distinct_predicted_classes": len(prediction_counts),
        "target_counts": {str(key): target_counts[key] for key in sorted(target_counts)},
        "prediction_counts": {
            str(key): prediction_counts[key] for key in sorted(prediction_counts)
        },
        "per_label": {
            str(label): {
                "examples": target_counts[label],
                "correct": label_correct.get(label, 0),
                "recall": label_correct.get(label, 0) / target_counts[label],
            }
            for label in sorted(target_counts)
        },
        "per_hop": {
            str(hop): {
                "examples": hop_counts[hop],
                "correct": hop_correct.get(hop, 0),
                "accuracy": hop_correct.get(hop, 0) / hop_counts[hop],
                "accuracy_wilson_lower_bound": wilson_lower_bound(
                    hop_correct.get(hop, 0), hop_counts[hop], wilson_z
                ),
            }
            for hop in sorted(hop_counts)
        },
        "prediction_rows_sha256": stable_hash(list(rows)),
    }


@torch.inference_mode()
def evaluate_condition(
    model: Any,
    dataloader: Any,
    *,
    condition_id: str,
    route_mode: str,
    device: torch.device,
    precision: str,
    max_batches: int,
    wilson_z: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    model.functional_config.route_mode = route_mode
    model.eval()
    rows: list[dict[str, Any]] = []
    choice_nll_sum = 0.0
    full_vocab_nll_sum = 0.0
    exact_logits = True
    exact_predictions = True
    max_abs_logit_difference = 0.0
    compared_logit_elements = 0
    candidate_token_rows: set[tuple[int, ...]] = set()

    for batch_index, raw_batch in enumerate(dataloader):
        if max_batches > 0 and batch_index >= max_batches:
            break
        batch = move_batch_to_device(raw_batch, device)
        flat = flatten_functional_batch(batch, route_mode)
        with autocast_context(device, precision):
            wrapper_output = model(
                input_ids=batch["input_ids"],
                attention_mask=batch["attention_mask"],
                labels=batch["labels"],
                prompt_mask=batch["prompt_mask"],
                context_mask=batch.get("context_mask"),
                query_mask=batch.get("query_mask"),
                example_group_ids=batch.get("example_group_ids"),
                world_group_ids=batch.get("world_group_ids"),
                counterfactual_group_ids=batch.get("counterfactual_group_ids"),
                answer_classes=batch.get("answer_classes"),
                **functional_batch_kwargs(batch),
                compute_workspace_loss=False,
                compute_spectral=False,
                bypass_workspace=False,
            )
            direct_output = model.base_model(
                input_ids=flat["input_ids"],
                attention_mask=flat["attention_mask"],
                use_cache=False,
                return_dict=True,
            )
        wrapper_logits = wrapper_output["logits"]
        direct_logits = direct_output.logits
        if wrapper_logits.shape != direct_logits.shape:
            raise Gate0Error(
                f"{condition_id}: wrapper/direct logit shapes differ: "
                f"{tuple(wrapper_logits.shape)} != {tuple(direct_logits.shape)}"
            )
        batch_exact = torch.equal(wrapper_logits, direct_logits)
        exact_logits = exact_logits and batch_exact
        if not batch_exact:
            max_abs_logit_difference = max(
                max_abs_logit_difference,
                _maximum_absolute_difference(wrapper_logits, direct_logits),
            )
        compared_logit_elements += int(wrapper_logits.numel())

        wrapper_full_nll, wrapper_choices, _targets, _positions = (
            model._functional_answer_rows(
                wrapper_logits,
                flat["labels"],
                flat["candidate_ids"],
            )
        )
        direct_full_nll, direct_choices, _targets, _positions = (
            model._functional_answer_rows(
                direct_logits,
                flat["labels"],
                flat["candidate_ids"],
            )
        )
        wrapper_predictions = wrapper_choices.argmax(dim=1)
        direct_predictions = direct_choices.argmax(dim=1)
        exact_predictions = exact_predictions and torch.equal(
            wrapper_predictions, direct_predictions
        )
        if not torch.equal(wrapper_full_nll, direct_full_nll):
            exact_logits = False
        choice_nll = F.cross_entropy(
            wrapper_choices.float(),
            flat["answer_classes"],
            reduction="none",
        )
        choice_nll_sum += float(choice_nll.sum().item())
        full_vocab_nll_sum += float(wrapper_full_nll.float().sum().item())
        target_rows = torch.arange(wrapper_choices.shape[0], device=device)
        target_logits = wrapper_choices[target_rows, flat["answer_classes"]]
        masked = wrapper_choices.clone()
        masked[target_rows, flat["answer_classes"]] = float("-inf")
        target_margins = target_logits - masked.max(dim=1).values
        if wrapper_choices.shape[1] != 2:
            raise Gate0Error("Gate-0 requires exactly two constrained choices.")
        signed_gaps = wrapper_choices[:, 1].float() - wrapper_choices[:, 0].float()

        for row_index in range(wrapper_predictions.numel()):
            candidate_tuple = tuple(
                int(value)
                for value in flat["candidate_ids"][row_index].detach().cpu().tolist()
            )
            candidate_token_rows.add(candidate_tuple)
            rows.append(
                {
                    "sample_index": int(flat["sample_indices"][row_index].item()),
                    "side": int(flat["side_indices"][row_index].item()),
                    "query_index": int(flat["query_indices"][row_index].item()),
                    "target": int(flat["answer_classes"][row_index].item()),
                    "prediction": int(wrapper_predictions[row_index].item()),
                    "hop_distance": int(flat["hop_distances"][row_index].item()),
                    "affected": bool(flat["affected"][row_index].item()),
                    "heldout": bool(flat["heldout"][row_index].item()),
                    "target_margin": float(target_margins[row_index].float().item()),
                    "yes_minus_no_gap": float(signed_gaps[row_index].item()),
                }
            )
        del direct_output, direct_logits, wrapper_output, wrapper_logits

    summary = _summarize_cases(
        rows,
        choice_nll_sum=choice_nll_sum,
        full_vocab_nll_sum=full_vocab_nll_sum,
        wilson_z=wilson_z,
    )
    summary.update(
        {
            "condition_id": condition_id,
            "route_mode": route_mode,
            "direct_wrapper_parity": {
                "exact_logits": exact_logits,
                "exact_predictions": exact_predictions,
                "max_abs_logit_difference": max_abs_logit_difference,
                "compared_logit_elements": compared_logit_elements,
            },
            "candidate_token_id_rows": [
                list(values) for values in sorted(candidate_token_rows)
            ],
        }
    )
    return summary, rows


def _check(check_id: str, passed: bool, observed: Any, criterion: Any) -> dict[str, Any]:
    return {
        "id": check_id,
        "passed": bool(passed),
        "observed": observed,
        "criterion": criterion,
    }


def build_gate_checks(
    contract: Mapping[str, Any],
    f0: Mapping[str, Any],
    f1: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    gates = contract["gates"]
    f0_targets = f0["target_counts"]
    f1_targets = f1["target_counts"]
    target_values = list(f1_targets.values())
    balanced_targets = (
        f0_targets == f1_targets
        and len(target_values) == 2
        and len(set(target_values)) == 1
    )
    f1_hop1 = f1.get("per_hop", {}).get("1")
    if not isinstance(f1_hop1, Mapping):
        f1_hop1 = {
            "accuracy_wilson_lower_bound": 0.0,
            "examples": 0,
        }
    label_recalls = [
        float(item["recall"])
        for item in f1.get("per_label", {}).values()
        if isinstance(item, Mapping)
    ]
    accuracy_delta = float(f1["accuracy"]) - float(f0["accuracy"])
    comparison = {
        "f1_minus_f0_accuracy": accuracy_delta,
        "same_target_counts": f0_targets == f1_targets,
        "target_counts": f1_targets,
    }
    checks = [
        _check(
            "balanced_targets",
            (not gates["require_balanced_targets"]) or balanced_targets,
            {"f0": f0_targets, "f1": f1_targets},
            "two classes with equal counts in both paired conditions",
        ),
        _check(
            "f0_direct_wrapper_logits",
            (not gates["require_exact_direct_wrapper_logits"])
            or bool(f0["direct_wrapper_parity"]["exact_logits"]),
            f0["direct_wrapper_parity"],
            "exact tensor equality",
        ),
        _check(
            "f1_direct_wrapper_logits",
            (not gates["require_exact_direct_wrapper_logits"])
            or bool(f1["direct_wrapper_parity"]["exact_logits"]),
            f1["direct_wrapper_parity"],
            "exact tensor equality",
        ),
        _check(
            "direct_wrapper_predictions",
            (not gates["require_exact_direct_wrapper_predictions"])
            or (
                bool(f0["direct_wrapper_parity"]["exact_predictions"])
                and bool(f1["direct_wrapper_parity"]["exact_predictions"])
            ),
            {
                "f0": f0["direct_wrapper_parity"]["exact_predictions"],
                "f1": f1["direct_wrapper_parity"]["exact_predictions"],
            },
            "exact prediction equality in both conditions",
        ),
        _check(
            "f1_overall_above_chance",
            float(f1["accuracy_wilson_lower_bound"])
            > float(gates["minimum_f1_overall_wilson_lower_bound"]),
            f1["accuracy_wilson_lower_bound"],
            f"> {gates['minimum_f1_overall_wilson_lower_bound']}",
        ),
        _check(
            "f1_hop1_above_chance",
            float(f1_hop1["accuracy_wilson_lower_bound"])
            > float(gates["minimum_f1_hop1_wilson_lower_bound"]),
            dict(f1_hop1),
            f"Wilson lower bound > {gates['minimum_f1_hop1_wilson_lower_bound']}",
        ),
        _check(
            "f1_predicts_both_classes",
            int(f1["distinct_predicted_classes"])
            >= int(gates["minimum_f1_distinct_predicted_classes"]),
            {
                "distinct": f1["distinct_predicted_classes"],
                "counts": f1["prediction_counts"],
            },
            f">= {gates['minimum_f1_distinct_predicted_classes']} classes",
        ),
        _check(
            "f1_minimum_label_recall",
            len(label_recalls) == 2
            and min(label_recalls) >= float(gates["minimum_f1_label_recall"]),
            label_recalls,
            f">= {gates['minimum_f1_label_recall']} for each label",
        ),
        _check(
            "f1_improves_over_f0",
            accuracy_delta >= float(gates["minimum_f1_minus_f0_accuracy"]),
            accuracy_delta,
            f">= {gates['minimum_f1_minus_f0_accuracy']}",
        ),
    ]
    return checks, comparison


def run_gate(args: argparse.Namespace) -> dict[str, Any]:
    started_at = utc_now()
    repo_root = args.repo_root.expanduser().resolve()
    contract_path = args.contract.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    contract = load_contract(contract_path)
    config_path = _resolve_from_contract(
        contract_path,
        str(contract["config"]["path"]),
        label="Gate-0 config",
    )
    dataset_path = _resolve_from_contract(
        contract_path,
        str(contract["dataset"]["path"]),
        label="Gate-0 dataset",
    )
    observed_config_hash = sha256_file(config_path)
    observed_dataset_hash = sha256_file(dataset_path)
    if observed_config_hash != contract["config"]["sha256"]:
        raise Gate0Error("Gate-0 config hash changed after threshold freeze.")
    if observed_dataset_hash != contract["dataset"]["sha256"]:
        raise Gate0Error("Gate-0 dataset hash changed after threshold freeze.")

    config = ExperimentConfig.from_json(config_path)
    if config.model.name_or_path != contract["model"]["name_or_path"]:
        raise Gate0Error("Gate-0 model identity differs from the frozen contract.")
    if config.model.revision != contract["model"]["revision"]:
        raise Gate0Error("Gate-0 model revision differs from the frozen contract.")
    if config.data.use_chat_template is not False:
        raise Gate0Error("Gate-0 must qualify the legacy non-chat elicitation.")
    if config.data.prompt_separator != contract["elicitation"]["prompt_separator"]:
        raise Gate0Error("Gate-0 prompt separator differs from the frozen contract.")
    resolved_eval_files = [Path(path).resolve() for path in config.data.eval_files]
    if resolved_eval_files != [dataset_path]:
        raise Gate0Error("Gate-0 config does not point only to the frozen eval corpus.")

    require_cuda_allocator_policy(config.train)
    configure_runtime_math(config.train)
    device = resolve_device(args.device)
    precision = resolve_mixed_precision(config.train.mixed_precision, device)
    set_global_seed(config.train.seed)
    model, tokenizer = build_workspace_model(config)
    model.to(device)
    model.eval()
    dataset = JsonlFineTuningDataset(
        config.data.eval_files,
        tokenizer,
        config.data,
    )
    if len(dataset) != int(contract["dataset"]["record_count"]):
        raise Gate0Error("Gate-0 eval record count changed.")
    collator = CausalFineTuningCollator(
        pad_token_id=int(tokenizer.pad_token_id),
        pad_to_multiple_of=config.data.pad_to_multiple_of,
    )
    loader_config = dataclasses.replace(
        config.data,
        pin_memory=config.data.pin_memory and device.type == "cuda",
    )

    results: dict[str, dict[str, Any]] = {}
    internal_rows: dict[str, list[dict[str, Any]]] = {}
    for condition in contract["conditions"]:
        dataloader = build_eval_dataloader(
            dataset,
            collator,
            config=loader_config,
            batch_size=config.train.eval_batch_size,
            seed=config.train.seed + 23_000_003,
        )
        summary, rows = evaluate_condition(
            model,
            dataloader,
            condition_id=str(condition["id"]),
            route_mode=str(condition["route_mode"]),
            device=device,
            precision=precision,
            max_batches=int(contract["execution"]["max_batches"]),
            wilson_z=float(contract["gates"]["wilson_z"]),
        )
        results[str(condition["id"])] = summary
        internal_rows[str(condition["id"])] = rows

    f0_rows = internal_rows["F0_query_only"]
    f1_rows = internal_rows["F1_inline"]
    f0_keys = [
        (row["sample_index"], row["side"], row["query_index"], row["target"])
        for row in f0_rows
    ]
    f1_keys = [
        (row["sample_index"], row["side"], row["query_index"], row["target"])
        for row in f1_rows
    ]
    if f0_keys != f1_keys:
        raise Gate0Error("F0/F1 evaluation cases are not positionally paired.")
    checks, comparison = build_gate_checks(
        contract,
        results["F0_query_only"],
        results["F1_inline"],
    )
    comparison["paired_case_keys_sha256"] = stable_hash(f0_keys)
    passed = all(bool(check["passed"]) for check in checks)
    receipt = {
        "format": FORMAT,
        "schema_version": 1,
        "status": "qualified" if passed else "blocked",
        "passed": passed,
        "started_at": started_at,
        "completed_at": utc_now(),
        "question": (
            "Does the pinned base model, under the exact current grouped-world "
            "F0/F1 wrapper path and legacy raw elicitation, show usable inline "
            "one-hop discrimination before any optimizer update?"
        ),
        "contract": {
            "path": str(contract_path),
            "sha256": sha256_file(contract_path),
            "payload": contract,
        },
        "source": git_snapshot(repo_root),
        "inputs": {
            "config": {"path": str(config_path), "sha256": observed_config_hash},
            "dataset": {
                "path": str(dataset_path),
                "sha256": observed_dataset_hash,
                "records": len(dataset),
            },
            "model": contract["model"],
        },
        "runtime": {
            **runtime_environment(),
            "device": str(device),
            "mixed_precision": precision,
        },
        "conditions": results,
        "paired_comparison": comparison,
        "checks": checks,
        "failed_checks": [
            check["id"] for check in checks if not bool(check["passed"])
        ],
        "claim_boundary": (
            "A qualified receipt validates this pinned model, dataset, raw prompt "
            "separator, constrained choices, and exact F0/F1 wrapper implementation. "
            "It does not establish that training, deferred workspace routing, or "
            "the v11 objective repair succeeds."
        ),
    }
    atomic_write_json(output_path, receipt)
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--device", default="cuda")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        receipt = run_gate(args)
    except Exception as exc:
        failure = {
            "format": FORMAT,
            "schema_version": 1,
            "status": "execution_error",
            "passed": False,
            "completed_at": utc_now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        atomic_write_json(args.output.expanduser().resolve(), failure)
        raise
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    if not receipt["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
