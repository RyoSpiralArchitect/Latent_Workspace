#!/usr/bin/env python3
"""Select a symmetric functional elicitation on a frozen train-only subset."""

from __future__ import annotations

import argparse
import dataclasses
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_v11_gate0 as gate0
import torch
import torch.nn.functional as F
from torch.utils.data import Subset

from latent_workspace_ft_v10.engine import (
    CausalFineTuningCollator,
    ExperimentConfig,
    JsonlFineTuningDataset,
    autocast_context,
    build_eval_dataloader,
    build_workspace_model,
    configure_runtime_math,
    move_batch_to_device,
    require_cuda_allocator_policy,
    resolve_device,
    resolve_mixed_precision,
    runtime_environment,
    set_global_seed,
)

FORMAT = "latent-workspace-ft-v11-elicitation-calibration-receipt-v1"
CONTRACT_FORMAT = "latent-workspace-ft-v11-elicitation-calibration-contract-v1"


class CalibrationError(RuntimeError):
    """The frozen train-only calibration surface is invalid."""


def _read_contract(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("format") != CONTRACT_FORMAT:
        raise CalibrationError(f"Contract format must be {CONTRACT_FORMAT!r}.")
    if value.get("frozen_before_execution") is not True:
        raise CalibrationError("Calibration contract was not frozen before execution.")
    if value.get("candidate_styles") != [
        "legacy",
        "explicit_labels",
        "symmetric_instruction",
        "symmetric_instruction_explicit_labels",
    ]:
        raise CalibrationError("Calibration candidate order changed.")
    return value


def _resolve(contract_path: Path, raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = contract_path.parent / path
    resolved = path.resolve()
    if not resolved.is_file():
        raise CalibrationError(f"Calibration input is missing: {resolved}")
    return resolved


@torch.inference_mode()
def evaluate_direct(
    model: Any,
    dataloader: Any,
    *,
    route_mode: str,
    device: torch.device,
    precision: str,
    wilson_z: float,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    choice_nll_sum = 0.0
    full_vocab_nll_sum = 0.0
    candidate_token_rows: set[tuple[int, ...]] = set()
    for raw_batch in dataloader:
        batch = move_batch_to_device(raw_batch, device)
        flat = gate0.flatten_functional_batch(batch, route_mode)
        with autocast_context(device, precision):
            output = model.base_model(
                input_ids=flat["input_ids"],
                attention_mask=flat["attention_mask"],
                use_cache=False,
                return_dict=True,
            )
        full_vocab_nll, choice_logits, _targets, _positions = (
            model._functional_answer_rows(
                output.logits,
                flat["labels"],
                flat["candidate_ids"],
            )
        )
        predictions = choice_logits.argmax(dim=1)
        choice_nll = F.cross_entropy(
            choice_logits.float(),
            flat["answer_classes"],
            reduction="none",
        )
        choice_nll_sum += float(choice_nll.sum().item())
        full_vocab_nll_sum += float(full_vocab_nll.float().sum().item())
        row_indices = torch.arange(choice_logits.shape[0], device=device)
        correct_logits = choice_logits[row_indices, flat["answer_classes"]]
        masked = choice_logits.clone()
        masked[row_indices, flat["answer_classes"]] = float("-inf")
        margins = correct_logits - masked.max(dim=1).values
        if choice_logits.shape[1] != 2:
            raise CalibrationError("Calibration requires exactly two choices.")
        signed_gaps = choice_logits[:, 1].float() - choice_logits[:, 0].float()
        for index in range(predictions.numel()):
            candidate_token_rows.add(
                tuple(
                    int(value)
                    for value in flat["candidate_ids"][index].cpu().tolist()
                )
            )
            rows.append(
                {
                    "sample_index": int(flat["sample_indices"][index].item()),
                    "side": int(flat["side_indices"][index].item()),
                    "query_index": int(flat["query_indices"][index].item()),
                    "target": int(flat["answer_classes"][index].item()),
                    "prediction": int(predictions[index].item()),
                    "hop_distance": int(flat["hop_distances"][index].item()),
                    "affected": bool(flat["affected"][index].item()),
                    "heldout": bool(flat["heldout"][index].item()),
                    "target_margin": float(margins[index].float().item()),
                    "yes_minus_no_gap": float(signed_gaps[index].item()),
                }
            )
        del output
    summary = gate0._summarize_cases(
        rows,
        choice_nll_sum=choice_nll_sum,
        full_vocab_nll_sum=full_vocab_nll_sum,
        wilson_z=wilson_z,
    )
    summary["candidate_token_id_rows"] = [
        list(values) for values in sorted(candidate_token_rows)
    ]
    return summary


def candidate_qualification(
    metrics: Mapping[str, Any],
    gates: Mapping[str, Any],
) -> tuple[bool, list[str]]:
    f0 = metrics["F0_query_only"]
    f1 = metrics["F1_inline"]
    failures: list[str] = []
    if float(f1["accuracy_wilson_lower_bound"]) <= float(
        gates["minimum_f1_overall_wilson_lower_bound"]
    ):
        failures.append("f1_overall_wilson")
    hop1 = f1.get("per_hop", {}).get("1", {})
    if float(hop1.get("accuracy_wilson_lower_bound", 0.0)) <= float(
        gates["minimum_f1_hop1_wilson_lower_bound"]
    ):
        failures.append("f1_hop1_wilson")
    recalls = [
        float(value["recall"])
        for value in f1.get("per_label", {}).values()
        if isinstance(value, Mapping)
    ]
    if len(recalls) != 2 or min(recalls) < float(gates["minimum_f1_label_recall"]):
        failures.append("f1_label_recall")
    if int(f1["distinct_predicted_classes"]) < int(
        gates["minimum_f1_distinct_predicted_classes"]
    ):
        failures.append("f1_distinct_predictions")
    if float(f1["accuracy"]) - float(f0["accuracy"]) < float(
        gates["minimum_f1_minus_f0_accuracy"]
    ):
        failures.append("f1_minus_f0")
    if f0["target_counts"] != f1["target_counts"] or len(
        set(f1["target_counts"].values())
    ) != 1:
        failures.append("balanced_targets")
    return not failures, failures


def select_candidate(
    results: Mapping[str, Mapping[str, Any]],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    eligible: list[dict[str, Any]] = []
    decisions: dict[str, Any] = {}
    order = list(contract["candidate_styles"])
    for index, style in enumerate(order):
        metrics = results[style]
        qualified, failures = candidate_qualification(metrics, contract["gates"])
        f1 = metrics["F1_inline"]
        recalls = [
            float(value["recall"]) for value in f1["per_label"].values()
        ]
        prediction_fraction_zero = float(f1["prediction_counts"].get("0", 0)) / max(
            int(f1["examples"]), 1
        )
        score = [
            min(recalls),
            float(f1["accuracy"]),
            -abs(prediction_fraction_zero - 0.5),
            -index,
        ]
        decisions[style] = {
            "qualified": qualified,
            "failures": failures,
            "selection_score": score,
        }
        if qualified:
            eligible.append({"style": style, "score": score})
    eligible.sort(key=lambda item: item["score"], reverse=True)
    return {
        "selected_style": eligible[0]["style"] if eligible else None,
        "eligible_styles": [item["style"] for item in eligible],
        "candidate_decisions": decisions,
        "selection_rule": contract["selection_rule"],
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    started_at = datetime.now(UTC).isoformat()
    contract_path = args.contract.expanduser().resolve()
    contract = _read_contract(contract_path)
    config_path = _resolve(contract_path, contract["config"]["path"])
    dataset_path = _resolve(contract_path, contract["dataset"]["path"])
    if gate0.sha256_file(config_path) != contract["config"]["sha256"]:
        raise CalibrationError("Calibration config hash changed.")
    if gate0.sha256_file(dataset_path) != contract["dataset"]["sha256"]:
        raise CalibrationError("Calibration dataset hash changed.")
    config = ExperimentConfig.from_json(config_path)
    if [Path(path).resolve() for path in config.data.train_files] != [dataset_path]:
        raise CalibrationError("Calibration config train path changed.")
    require_cuda_allocator_policy(config.train)
    configure_runtime_math(config.train)
    device = resolve_device(args.device)
    precision = resolve_mixed_precision(config.train.mixed_precision, device)
    set_global_seed(config.train.seed)
    model, tokenizer = build_workspace_model(config)
    model.to(device).eval()
    indices = list(contract["dataset"]["record_indices"])
    results: dict[str, dict[str, Any]] = {}
    for style in contract["candidate_styles"]:
        data_config = dataclasses.replace(
            config.data,
            functional_elicitation=style,
            pin_memory=config.data.pin_memory and device.type == "cuda",
        )
        dataset = JsonlFineTuningDataset(
            config.data.train_files,
            tokenizer,
            data_config,
        )
        if len(dataset) != int(contract["dataset"]["record_count"]):
            raise CalibrationError("Calibration dataset record count changed.")
        subset = Subset(dataset, indices)
        collator = CausalFineTuningCollator(
            pad_token_id=int(tokenizer.pad_token_id),
            pad_to_multiple_of=data_config.pad_to_multiple_of,
        )
        style_metrics: dict[str, Any] = {}
        for condition_id, route_mode in (
            ("F0_query_only", "query_only"),
            ("F1_inline", "inline"),
        ):
            loader = build_eval_dataloader(
                subset,
                collator,
                config=data_config,
                batch_size=config.train.eval_batch_size,
                seed=config.train.seed + 29_000_003,
            )
            style_metrics[condition_id] = evaluate_direct(
                model,
                loader,
                route_mode=route_mode,
                device=device,
                precision=precision,
                wilson_z=float(contract["gates"]["wilson_z"]),
            )
        results[style] = style_metrics
    selection = select_candidate(results, contract)
    passed = selection["selected_style"] is not None
    receipt = {
        "format": FORMAT,
        "schema_version": 1,
        "status": "selected" if passed else "blocked",
        "passed": passed,
        "started_at": started_at,
        "completed_at": datetime.now(UTC).isoformat(),
        "contract": {
            "path": str(contract_path),
            "sha256": gate0.sha256_file(contract_path),
            "payload": contract,
        },
        "source": gate0.git_snapshot(args.repo_root.expanduser().resolve()),
        "runtime": {
            **runtime_environment(),
            "device": str(device),
            "mixed_precision": precision,
        },
        "results": results,
        "selection": selection,
        "claim_boundary": (
            "This train-only calibration selects one frozen prompt style for a "
            "single subsequent eval qualification. It does not qualify eval, "
            "training, or the V11 objective-repair hypothesis."
        ),
    }
    gate0.atomic_write_json(args.output.expanduser().resolve(), receipt)
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
    receipt = run(args)
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    if not receipt["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
