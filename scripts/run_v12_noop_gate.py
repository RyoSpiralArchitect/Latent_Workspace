#!/usr/bin/env python3
"""Prove exact V12 inline-sidecar no-op equivalence before training."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F
from run_v11_gate0 import flatten_functional_batch, stable_hash

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

FORMAT = "latent-workspace-ft-v12-noop-gate-receipt-v1"
CONTRACT_FORMAT = "latent-workspace-ft-v12-calibrated-route-contract-v1"


class NoopGateError(RuntimeError):
    """The frozen no-op contract or its execution surface is invalid."""


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


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


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NoopGateError(f"{label} is not readable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise NoopGateError(f"{label} must contain a JSON object.")
    return value


def _resolve(contract_path: Path, raw: str, *, label: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = contract_path.parent / path
    resolved = path.resolve()
    if not resolved.is_file():
        raise NoopGateError(f"{label} is missing: {resolved}")
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


def _tensor_bytes(tensor: torch.Tensor) -> bytes:
    contiguous = tensor.detach().contiguous().cpu()
    return contiguous.view(torch.uint8).numpy().tobytes()


def bitwise_equal(left: torch.Tensor, right: torch.Tensor) -> bool:
    return (
        left.shape == right.shape
        and left.dtype == right.dtype
        and torch.equal(
            left.detach().contiguous().view(torch.uint8),
            right.detach().contiguous().view(torch.uint8),
        )
    )


def _maximum_absolute_difference(left: torch.Tensor, right: torch.Tensor) -> float:
    if left.numel() == 0:
        return 0.0
    return float((left.float() - right.float()).abs().max().item())


def _metric_summary(
    rows: list[dict[str, Any]],
    *,
    choice_nll_sum: float,
    full_vocab_nll_sum: float,
) -> dict[str, Any]:
    total = len(rows)
    correct = sum(int(row["prediction"] == row["target"]) for row in rows)
    target_counts: dict[str, int] = {}
    prediction_counts: dict[str, int] = {}
    label_correct: dict[str, int] = {}
    hop_counts: dict[str, int] = {}
    hop_correct: dict[str, int] = {}
    for row in rows:
        target = str(row["target"])
        prediction = str(row["prediction"])
        hop = str(row["hop_distance"])
        is_correct = int(target == prediction)
        target_counts[target] = target_counts.get(target, 0) + 1
        prediction_counts[prediction] = prediction_counts.get(prediction, 0) + 1
        label_correct[target] = label_correct.get(target, 0) + is_correct
        hop_counts[hop] = hop_counts.get(hop, 0) + 1
        hop_correct[hop] = hop_correct.get(hop, 0) + is_correct
    return {
        "examples": total,
        "correct": correct,
        "accuracy": correct / max(total, 1),
        "choice_loss": choice_nll_sum / max(total, 1),
        "full_vocab_loss": full_vocab_nll_sum / max(total, 1),
        "distinct_predicted_classes": len(prediction_counts),
        "target_counts": dict(sorted(target_counts.items())),
        "prediction_counts": dict(sorted(prediction_counts.items())),
        "per_label": {
            label: {
                "examples": target_counts[label],
                "correct": label_correct.get(label, 0),
                "recall": label_correct.get(label, 0) / target_counts[label],
            }
            for label in sorted(target_counts)
        },
        "per_hop": {
            hop: {
                "examples": hop_counts[hop],
                "correct": hop_correct.get(hop, 0),
                "accuracy": hop_correct.get(hop, 0) / hop_counts[hop],
            }
            for hop in sorted(hop_counts)
        },
        "prediction_rows_sha256": stable_hash(rows),
    }


def _check(check_id: str, passed: bool, observed: Any, criterion: Any) -> dict[str, Any]:
    return {
        "id": check_id,
        "passed": bool(passed),
        "observed": observed,
        "criterion": criterion,
    }


def build_checks(
    *,
    expected_cases: int,
    observed_cases: int,
    full_logits_bitwise: bool,
    choice_logits_bitwise: bool,
    predictions_exact: bool,
    metrics_exact: bool,
    zero_delta: bool,
    initialized_zero: bool,
) -> list[dict[str, Any]]:
    return [
        _check(
            "complete_eval_cases", observed_cases == expected_cases, observed_cases, expected_cases
        ),
        _check("sidecar_up_projection_zero_initialized", initialized_zero, initialized_zero, True),
        _check("full_logits_bitwise", full_logits_bitwise, full_logits_bitwise, True),
        _check("choice_logits_bitwise", choice_logits_bitwise, choice_logits_bitwise, True),
        _check("predictions_exact", predictions_exact, predictions_exact, True),
        _check("complete_metrics_exact", metrics_exact, metrics_exact, True),
        _check("zero_sidecar_delta_logit_norm", zero_delta, zero_delta, True),
        _check(
            "routed_amputated_exact",
            full_logits_bitwise and choice_logits_bitwise and predictions_exact,
            {
                "full_logits": full_logits_bitwise,
                "choice_logits": choice_logits_bitwise,
                "predictions": predictions_exact,
            },
            "all exact",
        ),
    ]


@torch.inference_mode()
def evaluate_noop(
    model: Any,
    dataloader: Any,
    *,
    device: torch.device,
    precision: str,
) -> dict[str, Any]:
    model.eval()
    routed_rows: list[dict[str, Any]] = []
    amputated_rows: list[dict[str, Any]] = []
    routed_choice_nll_sum = 0.0
    amputated_choice_nll_sum = 0.0
    routed_full_nll_sum = 0.0
    amputated_full_nll_sum = 0.0
    full_logits_bitwise = True
    choice_logits_bitwise = True
    predictions_exact = True
    zero_delta = True
    max_abs_full_logit_difference = 0.0
    max_abs_choice_logit_difference = 0.0
    compared_full_logit_elements = 0
    compared_choice_logit_elements = 0
    routed_choice_digest = hashlib.sha256()
    amputated_choice_digest = hashlib.sha256()

    for raw_batch in dataloader:
        batch = move_batch_to_device(raw_batch, device)
        flat = flatten_functional_batch(batch, "inline")
        common = {
            "input_ids": batch["input_ids"],
            "attention_mask": batch["attention_mask"],
            "labels": batch["labels"],
            "prompt_mask": batch["prompt_mask"],
            "context_mask": batch.get("context_mask"),
            "query_mask": batch.get("query_mask"),
            "example_group_ids": batch.get("example_group_ids"),
            "world_group_ids": batch.get("world_group_ids"),
            "counterfactual_group_ids": batch.get("counterfactual_group_ids"),
            "answer_classes": batch.get("answer_classes"),
            **functional_batch_kwargs(batch),
            "compute_workspace_loss": False,
            "compute_spectral": False,
        }
        with autocast_context(device, precision):
            routed = model(**common, bypass_workspace=False)
            amputated = model(**common, bypass_workspace=True)
        routed_logits = routed["logits"]
        amputated_logits = amputated["logits"]
        batch_full_exact = bitwise_equal(routed_logits, amputated_logits)
        full_logits_bitwise = full_logits_bitwise and batch_full_exact
        if not batch_full_exact:
            max_abs_full_logit_difference = max(
                max_abs_full_logit_difference,
                _maximum_absolute_difference(routed_logits, amputated_logits),
            )
        compared_full_logit_elements += int(routed_logits.numel())

        routed_full_nll, routed_choices, _targets, _positions = model._functional_answer_rows(
            routed_logits,
            flat["labels"],
            flat["candidate_ids"],
        )
        amputated_full_nll, amputated_choices, _targets, _positions = model._functional_answer_rows(
            amputated_logits,
            flat["labels"],
            flat["candidate_ids"],
        )
        batch_choice_exact = bitwise_equal(routed_choices, amputated_choices)
        choice_logits_bitwise = choice_logits_bitwise and batch_choice_exact
        if not batch_choice_exact:
            max_abs_choice_logit_difference = max(
                max_abs_choice_logit_difference,
                _maximum_absolute_difference(routed_choices, amputated_choices),
            )
        routed_choice_bytes = _tensor_bytes(routed_choices)
        amputated_choice_bytes = _tensor_bytes(amputated_choices)
        routed_choice_digest.update(routed_choice_bytes)
        amputated_choice_digest.update(amputated_choice_bytes)
        compared_choice_logit_elements += int(routed_choices.numel())

        routed_predictions = routed_choices.argmax(dim=1)
        amputated_predictions = amputated_choices.argmax(dim=1)
        predictions_exact = predictions_exact and torch.equal(
            routed_predictions, amputated_predictions
        )
        routed_choice_nll = F.cross_entropy(
            routed_choices.float(), flat["answer_classes"], reduction="none"
        )
        amputated_choice_nll = F.cross_entropy(
            amputated_choices.float(), flat["answer_classes"], reduction="none"
        )
        routed_choice_nll_sum += float(routed_choice_nll.sum().item())
        amputated_choice_nll_sum += float(amputated_choice_nll.sum().item())
        routed_full_nll_sum += float(routed_full_nll.float().sum().item())
        amputated_full_nll_sum += float(amputated_full_nll.float().sum().item())
        zero_delta = zero_delta and bitwise_equal(
            routed["delta_logit_norm"], torch.zeros_like(routed["delta_logit_norm"])
        )

        for name, predictions, choices, rows in (
            ("routed", routed_predictions, routed_choices, routed_rows),
            ("amputated", amputated_predictions, amputated_choices, amputated_rows),
        ):
            del name
            target_rows = torch.arange(choices.shape[0], device=device)
            target_logits = choices[target_rows, flat["answer_classes"]]
            masked = choices.clone()
            masked[target_rows, flat["answer_classes"]] = float("-inf")
            target_margins = target_logits - masked.max(dim=1).values
            signed_gaps = choices[:, 1].float() - choices[:, 0].float()
            for row_index in range(predictions.numel()):
                rows.append(
                    {
                        "sample_index": int(flat["sample_indices"][row_index].item()),
                        "side": int(flat["side_indices"][row_index].item()),
                        "query_index": int(flat["query_indices"][row_index].item()),
                        "target": int(flat["answer_classes"][row_index].item()),
                        "prediction": int(predictions[row_index].item()),
                        "hop_distance": int(flat["hop_distances"][row_index].item()),
                        "affected": bool(flat["affected"][row_index].item()),
                        "heldout": bool(flat["heldout"][row_index].item()),
                        "target_margin": float(target_margins[row_index].float().item()),
                        "yes_minus_no_gap": float(signed_gaps[row_index].item()),
                    }
                )
        del routed, amputated, routed_logits, amputated_logits

    routed_metrics = _metric_summary(
        routed_rows,
        choice_nll_sum=routed_choice_nll_sum,
        full_vocab_nll_sum=routed_full_nll_sum,
    )
    amputated_metrics = _metric_summary(
        amputated_rows,
        choice_nll_sum=amputated_choice_nll_sum,
        full_vocab_nll_sum=amputated_full_nll_sum,
    )
    return {
        "observed_cases": len(routed_rows),
        "full_logits_bitwise": full_logits_bitwise,
        "choice_logits_bitwise": choice_logits_bitwise,
        "predictions_exact": predictions_exact,
        "metrics_exact": routed_metrics == amputated_metrics,
        "zero_delta": zero_delta,
        "max_abs_full_logit_difference": max_abs_full_logit_difference,
        "max_abs_choice_logit_difference": max_abs_choice_logit_difference,
        "compared_full_logit_elements": compared_full_logit_elements,
        "compared_choice_logit_elements": compared_choice_logit_elements,
        "routed_choice_logits_sha256": routed_choice_digest.hexdigest(),
        "amputated_choice_logits_sha256": amputated_choice_digest.hexdigest(),
        "routed_metrics": routed_metrics,
        "amputated_metrics": amputated_metrics,
    }


def run_gate(args: argparse.Namespace) -> dict[str, Any]:
    started_at = utc_now()
    repo_root = args.repo_root.expanduser().resolve()
    contract_path = args.contract.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    contract = _read_json(contract_path, label="V12 contract")
    if contract.get("format") != CONTRACT_FORMAT:
        raise NoopGateError(f"Contract format must be {CONTRACT_FORMAT!r}.")
    if contract.get("frozen_before_execution") is not True:
        raise NoopGateError("The V12 contract was not frozen before execution.")
    gate = contract.get("v12_0_noop_gate")
    if not isinstance(gate, dict) or int(gate.get("optimizer_steps", -1)) != 0:
        raise NoopGateError("V12.0 must run before every optimizer step.")
    config_descriptor = gate.get("config")
    if not isinstance(config_descriptor, dict):
        raise NoopGateError("V12.0 has no pinned config descriptor.")
    config_path = _resolve(contract_path, str(config_descriptor["path"]), label="V12.0 config")
    dataset_descriptor = contract.get("data", {}).get("eval")
    if not isinstance(dataset_descriptor, dict):
        raise NoopGateError("V12 contract has no pinned eval dataset.")
    dataset_path = _resolve(
        contract_path, str(dataset_descriptor["path"]), label="V12 eval dataset"
    )
    config_hash = sha256_file(config_path)
    dataset_hash = sha256_file(dataset_path)
    if config_hash != config_descriptor["sha256"]:
        raise NoopGateError("V12.0 config changed after contract freeze.")
    if dataset_hash != dataset_descriptor["sha256"]:
        raise NoopGateError("V12 eval dataset changed after contract freeze.")

    config = ExperimentConfig.from_json(config_path)
    if config.functional.route_mode != "inline_sidecar":
        raise NoopGateError("V12.0 config is not the inline-sidecar route.")
    if config.model.name_or_path != contract["model"]["name_or_path"]:
        raise NoopGateError("V12.0 model id differs from the contract.")
    if config.model.revision != contract["model"]["revision"]:
        raise NoopGateError("V12.0 model revision differs from the contract.")
    if [Path(path).resolve() for path in config.data.eval_files] != [dataset_path]:
        raise NoopGateError("V12.0 config does not bind the frozen eval dataset.")

    require_cuda_allocator_policy(config.train)
    configure_runtime_math(config.train)
    device = resolve_device(args.device)
    precision = resolve_mixed_precision(config.train.mixed_precision, device)
    set_global_seed(config.train.seed)
    model, tokenizer = build_workspace_model(config)
    model.to(device)
    adapter = model.functional_sidecar_adapter
    if adapter is None:
        raise NoopGateError("The V12 sidecar adapter was not constructed.")
    initialized_zero = bool(
        torch.count_nonzero(adapter.up.weight.detach()).item() == 0
        and (adapter.up.bias is None or torch.count_nonzero(adapter.up.bias.detach()).item() == 0)
    )
    dataset = JsonlFineTuningDataset(config.data.eval_files, tokenizer, config.data)
    collator = CausalFineTuningCollator(
        pad_token_id=int(tokenizer.pad_token_id),
        pad_to_multiple_of=config.data.pad_to_multiple_of,
    )
    loader_config = dataclasses.replace(
        config.data,
        pin_memory=config.data.pin_memory and device.type == "cuda",
    )
    dataloader = build_eval_dataloader(
        dataset,
        collator,
        config=loader_config,
        batch_size=config.train.eval_batch_size,
        seed=config.train.seed + 23_000_003,
    )
    result = evaluate_noop(model, dataloader, device=device, precision=precision)
    checks = build_checks(
        expected_cases=int(gate["complete_eval_cases"]),
        observed_cases=int(result["observed_cases"]),
        full_logits_bitwise=bool(result["full_logits_bitwise"]),
        choice_logits_bitwise=bool(result["choice_logits_bitwise"]),
        predictions_exact=bool(result["predictions_exact"]),
        metrics_exact=bool(result["metrics_exact"]),
        zero_delta=bool(result["zero_delta"]),
        initialized_zero=initialized_zero,
    )
    passed = all(bool(check["passed"]) for check in checks)
    receipt = {
        "format": FORMAT,
        "schema_version": 1,
        "status": "qualified" if passed else "blocked",
        "passed": passed,
        "started_at": started_at,
        "completed_at": utc_now(),
        "contract": {
            "path": str(contract_path),
            "sha256": sha256_file(contract_path),
        },
        "source": git_snapshot(repo_root),
        "inputs": {
            "config": {"path": str(config_path), "sha256": config_hash},
            "dataset": {
                "path": str(dataset_path),
                "sha256": dataset_hash,
                "records": len(dataset),
            },
            "model": contract["model"],
        },
        "runtime": {
            **runtime_environment(),
            "device": str(device),
            "mixed_precision": precision,
        },
        "initialization": {
            "sidecar_up_projection_zero": initialized_zero,
            "optimizer_steps": 0,
        },
        "comparison": result,
        "checks": checks,
        "failed_checks": [check["id"] for check in checks if not bool(check["passed"])],
        "claim_boundary": (
            "A qualified receipt proves exact step-0 equivalence for the pinned "
            "Mistral-7B model, 1,024 grouped eval cases, and this sidecar build. "
            "It does not prove that any update is useful or that later base release "
            "preserves behavior."
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
