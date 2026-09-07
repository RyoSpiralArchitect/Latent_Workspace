#!/usr/bin/env python3
"""Run matched free-form diagnostics for base, task, and semantic V14 models."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import torch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from run_v14_boundary_training import (  # noqa: E402
    atomic_write,
    digest,
    load_json,
    resolve_inside,
)

from latent_workspace_ft_v10 import engine  # noqa: E402

PLAN_PATH = REPO / "configs/v14/EXPERIMENTAL_CHAT_PLAN.json"
FORMAT = "latent-workspace-v14-experimental-chat-v1"
MODEL_ORDER = ("base", "task", "semantic")


class ChatHarnessError(RuntimeError):
    """Raised when the frozen free-form diagnostic cannot be executed exactly."""


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _prompt_prefix(ids: list[int], labels: list[int]) -> list[int]:
    if len(ids) != len(labels):
        raise ChatHarnessError("Prompt ids and labels differ in length")
    supervised = [index for index, label in enumerate(labels) if int(label) != -100]
    if len(supervised) != 1 or supervised[0] != len(ids) - 1:
        raise ChatHarnessError(
            f"Expected one terminal answer token, observed positions={supervised}"
        )
    return [int(value) for value in ids[: supervised[0]]]


def validate_plan(
    root: Path,
    plan: dict[str, Any],
    *,
    require_fresh: bool,
    verify_bundles: bool = True,
) -> dict[str, Any]:
    expected = {
        "format": "latent-workspace-v14-experimental-chat-plan-v1",
        "frozen_before_generation": True,
        "model_order": list(MODEL_ORDER),
        "max_new_tokens": 16,
        "expected_cases": 8,
        "expected_generations": 192,
        "kv_cache": False,
        "pinned_base_model": {
            "name_or_path": "mistralai/Mistral-7B-Instruct-v0.3",
            "revision": "c170c708c41dac9275d15a8fff4eca08d52bab71",
        },
        "prompt_protocol": {
            "functional_elicitation": "symmetric_instruction",
            "use_chat_template": False,
            "response_prefix": "",
            "add_bos": False,
            "add_eos": False,
        },
    }
    mismatches = {
        key: {"observed": plan.get(key), "expected": value}
        for key, value in expected.items()
        if plan.get(key) != value
    }
    if mismatches:
        raise ChatHarnessError(f"Frozen chat plan mismatch: {mismatches}")
    grouped_execution = plan["grouped_execution"]
    grouped_execution_path = resolve_inside(
        root, grouped_execution["path"], label="grouped execution"
    )
    if (
        not grouped_execution_path.is_file()
        or digest(grouped_execution_path) != grouped_execution["sha256"]
    ):
        raise ChatHarnessError("Grouped execution receipt changed")
    execution_receipt = load_json(grouped_execution_path)
    if execution_receipt.get("status") != "COMPLETED":
        raise ChatHarnessError("Grouped execution did not complete")
    comparison = plan["grouped_comparison"]
    comparison_path = resolve_inside(root, comparison["path"], label="comparison")
    if not comparison_path.is_file() or digest(comparison_path) != comparison["sha256"]:
        raise ChatHarnessError("Grouped comparison changed")
    if load_json(comparison_path).get("winner") != "none":
        raise ChatHarnessError("This diagnostic plan is bound to the no-winner comparison")
    if execution_receipt.get("comparison_sha256") != comparison["sha256"]:
        raise ChatHarnessError("Grouped execution does not bind the frozen comparison")
    eval_artifact = plan["eval_data"]
    eval_path = resolve_inside(root, eval_artifact["path"], label="eval data")
    if not eval_path.is_file() or digest(eval_path) != eval_artifact["sha256"]:
        raise ChatHarnessError("Evaluation fixture changed")
    for relative, expected_hash in plan["source_identity"].items():
        path = resolve_inside(root, relative, label="source_identity")
        if not path.is_file() or path.is_symlink() or digest(path) != expected_hash:
            raise ChatHarnessError(f"Source identity mismatch: {relative}")
    cases = plan.get("cases")
    if not isinstance(cases, list) or len(cases) != 8:
        raise ChatHarnessError("Exactly eight frozen cases are required")
    observed_ids = [str(case.get("id")) for case in cases]
    if len(set(observed_ids)) != len(observed_ids):
        raise ChatHarnessError("Case identifiers must be unique")
    regimes = plan.get("regimes")
    if not isinstance(regimes, list) or len(regimes) != 4:
        raise ChatHarnessError("Exactly one greedy and three sampled regimes are required")
    if regimes[0] != {"id": "greedy", "seed": 0, "temperature": 0.0, "top_p": 1.0}:
        raise ChatHarnessError("Greedy regime changed")
    expected_sample_seeds = [101, 102, 103]
    if [row.get("seed") for row in regimes[1:]] != expected_sample_seeds:
        raise ChatHarnessError("Sample seeds changed")
    if any(row.get("temperature") != 0.7 or row.get("top_p") != 0.9 for row in regimes[1:]):
        raise ChatHarnessError("Sample temperature/top-p changed")
    model_specs = plan.get("models")
    if not isinstance(model_specs, list) or [row.get("id") for row in model_specs] != list(
        MODEL_ORDER
    ):
        raise ChatHarnessError("Model order changed")
    resolved_models: dict[str, dict[str, Any]] = {}
    for spec in model_specs:
        model_id = str(spec["id"])
        if model_id == "base":
            if spec.get("lanes") != ["inline", "query_only"]:
                raise ChatHarnessError("Base lanes changed")
            resolved_models[model_id] = dict(spec)
            continue
        if spec.get("lanes") != ["deferred_intact", "deferred_twin"]:
            raise ChatHarnessError(f"Deferred lanes changed: {model_id}")
        checkpoint = resolve_inside(root, spec["checkpoint"], label=f"{model_id} checkpoint")
        if verify_bundles:
            if not (checkpoint / "COMPLETED").is_file():
                raise ChatHarnessError(f"Incomplete checkpoint: {model_id}")
            if digest(checkpoint / "manifest.json") != spec["manifest_sha256"]:
                raise ChatHarnessError(f"Manifest changed: {model_id}")
            if digest(checkpoint / "workspace_state.pt") != spec["workspace_sha256"]:
                raise ChatHarnessError(f"Workspace changed: {model_id}")
        resolved = dict(spec)
        resolved["checkpoint_path"] = checkpoint
        resolved_models[model_id] = resolved
    generation_count = sum(len(spec["lanes"]) for spec in model_specs) * len(cases) * len(
        regimes
    )
    if generation_count != int(plan["expected_generations"]):
        raise ChatHarnessError(
            "Frozen model/case/regime grid no longer matches expected_generations"
        )
    output = resolve_inside(root, plan["output"], label="output")
    if require_fresh and output.exists():
        raise ChatHarnessError(f"Generation output already exists: {output}")
    return {
        "grouped_execution_path": grouped_execution_path,
        "comparison_path": comparison_path,
        "eval_path": eval_path,
        "models": resolved_models,
        "output": output,
    }


def _validate_runtime(plan: dict[str, Any]) -> dict[str, Any]:
    import transformers

    observed = {
        "python": ".".join(str(value) for value in sys.version_info[:3]),
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "cuda": torch.version.cuda,
    }
    if observed != plan["expected_runtime"]:
        raise ChatHarnessError(
            f"Runtime mismatch: observed={observed}, expected={plan['expected_runtime']}"
        )
    environment = {key: os.environ.get(key) for key in plan["required_environment"]}
    if environment != plan["required_environment"]:
        raise ChatHarnessError(
            f"Environment mismatch: observed={environment}, expected={plan['required_environment']}"
        )
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise ChatHarnessError("Exactly one visible CUDA device is required")
    observed["gpu"] = torch.cuda.get_device_name(0)
    observed["environment"] = environment
    return observed


def _validate_config_protocol(config: Any, plan: dict[str, Any], model_id: str) -> None:
    observed_model = {
        "name_or_path": config.model.name_or_path,
        "revision": config.model.revision,
    }
    if observed_model != plan["pinned_base_model"]:
        raise ChatHarnessError(
            f"Pinned base model changed for {model_id}: {observed_model}"
        )
    expected_prompt = plan["prompt_protocol"]
    observed_prompt = {
        "functional_elicitation": config.data.functional_elicitation,
        "use_chat_template": config.data.use_chat_template,
        "response_prefix": config.data.response_prefix,
        "add_bos": config.data.add_bos,
        "add_eos": config.data.add_eos,
    }
    if observed_prompt != expected_prompt:
        raise ChatHarnessError(
            f"Frozen prompt protocol changed for {model_id}: {observed_prompt}"
        )
    if config.train.mixed_precision != "bf16":
        raise ChatHarnessError(f"Generation precision changed for {model_id}")


def _case_features(
    dataset: Any,
    cases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for case in cases:
        world = int(case["world_index"])
        side = int(case["side"])
        query = int(case["query_index"])
        feature = dataset[world]
        if side not in (0, 1) or not 0 <= query < int(feature["functional_query_count"]):
            raise ChatHarnessError(f"Case lies outside the functional grid: {case['id']}")
        affected = bool(feature["functional_affected"][query])
        if affected is not bool(case["affected"]):
            raise ChatHarnessError(f"Case affected flag changed: {case['id']}")
        query_prefix = _prompt_prefix(
            feature["functional_query_ids"][side][query],
            feature["functional_query_labels"][side][query],
        )
        inline_prefix = _prompt_prefix(
            feature["functional_inline_ids"][side][query],
            feature["functional_inline_labels"][side][query],
        )
        choices = feature["functional_query_choice_ids"][side][query]
        if any(len(value) != 1 for value in choices):
            raise ChatHarnessError("Chat choice classification requires one-token choices")
        prepared.append(
            {
                "id": str(case["id"]),
                "world_index": world,
                "side": side,
                "query_index": query,
                "affected": affected,
                "heldout": bool(feature["functional_heldout_queries"][query]),
                "hop_distance": int(feature["functional_hop_distances"][query]),
                "query_prefix": query_prefix,
                "inline_prefix": inline_prefix,
                "contexts": [
                    [int(value) for value in feature["functional_context_ids"][0]],
                    [int(value) for value in feature["functional_context_ids"][1]],
                ],
                "choice_token_ids": [int(value[0]) for value in choices],
                "original_answer": int(feature["functional_answers"][side][query]),
                "donor_answer": int(feature["functional_answers"][1 - side][query]),
            }
        )
    return prepared


def _sample_token(
    logits: torch.Tensor,
    *,
    temperature: float,
    top_p: float,
    generator: torch.Generator | None,
) -> int:
    values = logits.detach().float()
    if values.ndim != 1 or not bool(torch.isfinite(values).all()):
        raise ChatHarnessError("Next-token logits must be a finite vector")
    if temperature <= 0.0:
        return int(values.argmax().item())
    probabilities = torch.softmax(values / temperature, dim=-1)
    sorted_probabilities, sorted_indices = torch.sort(probabilities, descending=True)
    cumulative = torch.cumsum(sorted_probabilities, dim=-1)
    remove = cumulative - sorted_probabilities > top_p
    sorted_probabilities = sorted_probabilities.masked_fill(remove, 0.0)
    total = sorted_probabilities.sum()
    if not bool(torch.isfinite(total)) or float(total.item()) <= 0.0:
        raise ChatHarnessError("Top-p filtering removed every token")
    sorted_probabilities = sorted_probabilities / total
    selected = torch.multinomial(sorted_probabilities, 1, generator=generator)
    return int(sorted_indices[selected].item())


def _generator(device: torch.device, seed: int, temperature: float) -> torch.Generator | None:
    if temperature <= 0.0:
        return None
    return torch.Generator(device=device).manual_seed(int(seed))


def _step_receipt(
    logits: torch.Tensor,
    token: int,
    *,
    gate_mean: float | None,
    read_norm: float | None,
) -> dict[str, Any]:
    log_probability = torch.log_softmax(logits.detach().float(), dim=-1)[token]
    return {
        "token_id": token,
        "chosen_log_probability": float(log_probability.item()),
        "gate_mean": gate_mean,
        "read_norm": read_norm,
    }


@torch.inference_mode()
def _generate_base(
    model: Any,
    prefix: list[int],
    *,
    device: torch.device,
    precision: str,
    regime: dict[str, Any],
    max_new_tokens: int,
    eos_token_id: int | None,
) -> tuple[list[int], list[dict[str, Any]], str]:
    generated: list[int] = []
    receipts: list[dict[str, Any]] = []
    generator = _generator(device, int(regime["seed"]), float(regime["temperature"]))
    finish_reason = "length"
    for _ in range(max_new_tokens):
        current = torch.tensor([prefix + generated], device=device, dtype=torch.long)
        attention = torch.ones_like(current)
        with engine.autocast_context(device, precision):
            output = model(
                input_ids=current,
                attention_mask=attention,
                use_cache=False,
                return_dict=True,
            )
        logits = output.logits[0, -1]
        token = _sample_token(
            logits,
            temperature=float(regime["temperature"]),
            top_p=float(regime["top_p"]),
            generator=generator,
        )
        generated.append(token)
        receipts.append(_step_receipt(logits, token, gate_mean=None, read_norm=None))
        if eos_token_id is not None and token == eos_token_id:
            finish_reason = "eos"
            break
    return generated, receipts, finish_reason


@torch.inference_mode()
def _context_memory(
    model: Any,
    context: list[int],
    *,
    device: torch.device,
    precision: str,
    boundary: int,
) -> tuple[torch.Tensor, torch.Tensor]:
    if model.functional_boundary_adapter is None or model.functional_writer is None:
        raise ChatHarnessError("Functional boundary writer is unavailable")
    ids = torch.tensor([context], device=device, dtype=torch.long)
    attention = torch.ones_like(ids)
    with engine.autocast_context(device, precision):
        hidden = model.functional_boundary_adapter.encode(ids, attention, boundary)
        memory, memory_mask, trajectory, _anchor = model.functional_writer(hidden, attention)
    if model.functional_config.readout_step != -1:
        memory = trajectory[:, :, model.functional_config.readout_step - 1, :]
    return memory, memory_mask


@torch.inference_mode()
def _generate_deferred(
    model: Any,
    prefix: list[int],
    memory: torch.Tensor,
    memory_mask: torch.Tensor,
    *,
    device: torch.device,
    precision: str,
    regime: dict[str, Any],
    max_new_tokens: int,
    eos_token_id: int | None,
    boundary: int,
) -> tuple[list[int], list[dict[str, Any]], str]:
    if model.functional_boundary_adapter is None:
        raise ChatHarnessError("Functional boundary adapter is unavailable")
    generated: list[int] = []
    receipts: list[dict[str, Any]] = []
    generator = _generator(device, int(regime["seed"]), float(regime["temperature"]))
    finish_reason = "length"
    for _ in range(max_new_tokens):
        current = torch.tensor([prefix + generated], device=device, dtype=torch.long)
        attention = torch.ones_like(current)
        with engine.autocast_context(device, precision):
            hidden = model.functional_boundary_adapter.encode(current, attention, boundary)
            logits, gate_mean, read_norm = model._functional_decode_with_memory(
                hidden,
                attention,
                memory,
                memory_mask,
                boundary_layer=boundary,
                hard_bypass=False,
            )
        next_logits = logits[0, -1]
        token = _sample_token(
            next_logits,
            temperature=float(regime["temperature"]),
            top_p=float(regime["top_p"]),
            generator=generator,
        )
        generated.append(token)
        receipts.append(
            _step_receipt(
                next_logits,
                token,
                gate_mean=float(gate_mean.detach().float().item()),
                read_norm=float(read_norm.detach().float().item()),
            )
        )
        if eos_token_id is not None and token == eos_token_id:
            finish_reason = "eos"
            break
    return generated, receipts, finish_reason


def _row(
    *,
    model_id: str,
    lane: str,
    case: dict[str, Any],
    regime: dict[str, Any],
    prefix: list[int],
    generated: list[int],
    receipts: list[dict[str, Any]],
    finish_reason: str,
    tokenizer: Any,
    context_source_side: int | None,
) -> dict[str, Any]:
    first = generated[0] if generated else None
    choices = case["choice_token_ids"]
    choice_class = choices.index(first) if first in choices else None
    target = case["donor_answer"] if lane == "deferred_twin" else case["original_answer"]
    return {
        "model": model_id,
        "lane": lane,
        "case_id": case["id"],
        "world_index": case["world_index"],
        "side": case["side"],
        "query_index": case["query_index"],
        "affected": case["affected"],
        "heldout": case["heldout"],
        "hop_distance": case["hop_distance"],
        "context_source_side": context_source_side,
        "original_answer": case["original_answer"],
        "donor_answer": case["donor_answer"],
        "target_answer": target,
        "choice_token_ids": choices,
        "regime": regime["id"],
        "seed": regime["seed"],
        "temperature": regime["temperature"],
        "top_p": regime["top_p"],
        "prefix_token_count": len(prefix),
        "prefix_token_sha256": _stable_hash(prefix),
        "prompt_text": tokenizer.decode(prefix, skip_special_tokens=False),
        "generated_token_ids": generated,
        "generated_text": tokenizer.decode(generated, skip_special_tokens=False),
        "generated_text_clean": tokenizer.decode(generated, skip_special_tokens=True),
        "finish_reason": finish_reason,
        "first_token_choice": choice_class,
        "target_correct": choice_class == target,
        "original_correct": choice_class == case["original_answer"],
        "donor_correct": choice_class == case["donor_answer"],
        "step_receipts": receipts,
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str, str, bool], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["model"], row["lane"], row["regime"], row["affected"])].append(row)
    group_reports: dict[str, Any] = {}
    for key, values in sorted(groups.items()):
        model_id, lane, regime, affected = key
        valid = [value for value in values if value["first_token_choice"] is not None]
        name = f"{model_id}/{lane}/{regime}/{'affected' if affected else 'unaffected'}"
        group_reports[name] = {
            "generations": len(values),
            "valid_choice_first_tokens": len(valid),
            "valid_choice_fraction": len(valid) / len(values),
            "target_accuracy_all": sum(bool(value["target_correct"]) for value in values)
            / len(values),
            "original_accuracy_all": sum(bool(value["original_correct"]) for value in values)
            / len(values),
            "donor_accuracy_all": sum(bool(value["donor_correct"]) for value in values)
            / len(values),
        }
    indexed = {
        (row["model"], row["case_id"], row["regime"], row["lane"]): row for row in rows
    }
    twin_reports: dict[str, Any] = {}
    for model_id in ("task", "semantic"):
        pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for row in rows:
            if row["model"] != model_id or row["lane"] != "deferred_intact":
                continue
            twin = indexed[(model_id, row["case_id"], row["regime"], "deferred_twin")]
            pairs.append((row, twin))
        comparable = [
            pair
            for pair in pairs
            if pair[0]["first_token_choice"] is not None
            and pair[1]["first_token_choice"] is not None
        ]
        affected = [pair for pair in comparable if pair[0]["affected"]]
        unaffected = [pair for pair in comparable if not pair[0]["affected"]]
        twin_reports[model_id] = {
            "pairs": len(pairs),
            "choice_comparable_pairs": len(comparable),
            "affected_changed_fraction": (
                sum(
                    pair[0]["first_token_choice"] != pair[1]["first_token_choice"]
                    for pair in affected
                )
                / max(len(affected), 1)
            ),
            "affected_changed_to_donor_fraction": (
                sum(
                    pair[0]["first_token_choice"] != pair[1]["first_token_choice"]
                    and pair[1]["first_token_choice"] == pair[1]["donor_answer"]
                    for pair in affected
                )
                / max(len(affected), 1)
            ),
            "unaffected_same_fraction": (
                sum(
                    pair[0]["first_token_choice"] == pair[1]["first_token_choice"]
                    for pair in unaffected
                )
                / max(len(unaffected), 1)
            ),
        }
    return {"groups": group_reports, "intact_twin_pairs": twin_reports}


def _process_base(
    config: Any,
    plan: dict[str, Any],
    *,
    device: torch.device,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    _validate_config_protocol(config, plan, "base")
    tokenizer = engine.load_tokenizer(config.model)
    dataset = engine.JsonlFineTuningDataset(config.data.eval_files, tokenizer, config.data)
    cases = _case_features(dataset, plan["cases"])
    model = engine._load_hf_model(config.model).to(device)
    model.eval()
    precision = engine.resolve_mixed_precision(config.train.mixed_precision, device)
    rows: list[dict[str, Any]] = []
    for case in cases:
        for lane, prefix_key in (("inline", "inline_prefix"), ("query_only", "query_prefix")):
            prefix = case[prefix_key]
            for regime in plan["regimes"]:
                generated, receipts, finish = _generate_base(
                    model,
                    prefix,
                    device=device,
                    precision=precision,
                    regime=regime,
                    max_new_tokens=int(plan["max_new_tokens"]),
                    eos_token_id=tokenizer.eos_token_id,
                )
                rows.append(
                    _row(
                        model_id="base",
                        lane=lane,
                        case=case,
                        regime=regime,
                        prefix=prefix,
                        generated=generated,
                        receipts=receipts,
                        finish_reason=finish,
                        tokenizer=tokenizer,
                        context_source_side=case["side"] if lane == "inline" else None,
                    )
                )
    identity = {
        "model_id": config.model.name_or_path,
        "revision": config.model.revision,
        "case_prompt_sha256": _stable_hash(
            [{key: case[key] for key in ("id", "query_prefix", "inline_prefix")} for case in cases]
        ),
    }
    del model, dataset, tokenizer
    gc.collect()
    torch.cuda.empty_cache()
    return rows, identity


def _process_functional(
    model_id: str,
    checkpoint: Path,
    plan: dict[str, Any],
    *,
    device: torch.device,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    model, tokenizer, config = engine.load_bundle(checkpoint, device=device)
    _validate_config_protocol(config, plan, model_id)
    if config.functional.route_mode != "deferred" or config.functional.boundary_layer != 16:
        raise ChatHarnessError(f"Unexpected functional route: {model_id}")
    dataset = engine.JsonlFineTuningDataset(config.data.eval_files, tokenizer, config.data)
    cases = _case_features(dataset, plan["cases"])
    precision = engine.resolve_mixed_precision(config.train.mixed_precision, device)
    boundary = int(config.functional.boundary_layer)
    memory_cache: dict[tuple[int, int], tuple[torch.Tensor, torch.Tensor]] = {}
    rows: list[dict[str, Any]] = []
    for case in cases:
        for lane in ("deferred_intact", "deferred_twin"):
            source_side = case["side"] if lane == "deferred_intact" else 1 - case["side"]
            memory_key = (case["world_index"], source_side)
            if memory_key not in memory_cache:
                memory_cache[memory_key] = _context_memory(
                    model,
                    case["contexts"][source_side],
                    device=device,
                    precision=precision,
                    boundary=boundary,
                )
            memory, memory_mask = memory_cache[memory_key]
            for regime in plan["regimes"]:
                generated, receipts, finish = _generate_deferred(
                    model,
                    case["query_prefix"],
                    memory,
                    memory_mask,
                    device=device,
                    precision=precision,
                    regime=regime,
                    max_new_tokens=int(plan["max_new_tokens"]),
                    eos_token_id=tokenizer.eos_token_id,
                    boundary=boundary,
                )
                rows.append(
                    _row(
                        model_id=model_id,
                        lane=lane,
                        case=case,
                        regime=regime,
                        prefix=case["query_prefix"],
                        generated=generated,
                        receipts=receipts,
                        finish_reason=finish,
                        tokenizer=tokenizer,
                        context_source_side=source_side,
                    )
                )
    identity = {
        "checkpoint": checkpoint.relative_to(REPO).as_posix(),
        "manifest_sha256": digest(checkpoint / "manifest.json"),
        "workspace_sha256": digest(checkpoint / "workspace_state.pt"),
        "case_prompt_sha256": _stable_hash(
            [{key: case[key] for key in ("id", "query_prefix", "inline_prefix")} for case in cases]
        ),
    }
    del memory_cache, model, dataset, tokenizer
    gc.collect()
    torch.cuda.empty_cache()
    return rows, identity


def execute(root: Path, plan_path: Path, *, dry_run: bool) -> dict[str, Any]:
    plan = load_json(plan_path)
    paths = validate_plan(root, plan, require_fresh=not dry_run)
    report: dict[str, Any] = {
        "format": FORMAT,
        "status": "DRY_RUN" if dry_run else "RUNNING",
        "started_utc": datetime.now(UTC).isoformat(),
        "plan": {"path": plan_path.relative_to(root).as_posix(), "sha256": digest(plan_path)},
        "runtime": None,
        "generation_protocol": {
            "kv_cache": False,
            "full_prefix_recompute_per_token": True,
            "max_new_tokens": int(plan["max_new_tokens"]),
            "regimes": plan["regimes"],
        },
        "model_identities": {},
        "rows": [],
    }
    if dry_run:
        return report
    report["runtime"] = _validate_runtime(plan)
    config = engine.ExperimentConfig.from_json(
        paths["models"]["task"]["checkpoint_path"] / "experiment_config.json"
    )
    engine.require_cuda_allocator_policy(config.train)
    engine.configure_runtime_math(config.train)
    atomic_write(paths["output"], report)
    for model_id in MODEL_ORDER:
        if model_id == "base":
            rows, identity = _process_base(config, plan, device=torch.device("cuda"))
        else:
            rows, identity = _process_functional(
                model_id,
                paths["models"][model_id]["checkpoint_path"],
                plan,
                device=torch.device("cuda"),
            )
        report["rows"].extend(rows)
        report["model_identities"][model_id] = identity
        report["last_completed_model"] = model_id
        atomic_write(paths["output"], report)
    if len(report["rows"]) != int(plan["expected_generations"]):
        raise ChatHarnessError(
            f"Generation count mismatch: {len(report['rows'])} != {plan['expected_generations']}"
        )
    prompt_hashes = {
        value["case_prompt_sha256"] for value in report["model_identities"].values()
    }
    if len(prompt_hashes) != 1:
        raise ChatHarnessError("Tokenized prompt projections differ across models")
    report.update(
        {
            "status": "COMPLETED",
            "completed_utc": datetime.now(UTC).isoformat(),
            "generation_count": len(report["rows"]),
            "summary": _summary(report["rows"]),
            "claim_boundary": (
                "This is a fixed-prompt free-form behavior diagnostic. Greedy and three seeded "
                "samples expose hand-feel and trajectory bifurcation, but cannot rescue a failed "
                "constrained semantic gate or establish general chat quality. Full-prefix "
                "recomputation is matched across lanes and is not a serving-speed result."
            ),
        }
    )
    atomic_write(paths["output"], report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO)
    parser.add_argument("--plan", type=Path, default=PLAN_PATH)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.repo_root.expanduser().resolve()
    plan_path = args.plan.expanduser().resolve()
    try:
        plan_path.relative_to(root)
    except ValueError as exc:
        raise ChatHarnessError("Plan must stay inside the repository") from exc
    plan = load_json(plan_path)
    output = resolve_inside(root, plan["output"], label="output")
    if output.exists():
        raise ChatHarnessError(f"Generation output already exists: {output}")
    try:
        report = execute(root, plan_path, dry_run=args.dry_run)
    except Exception as exc:
        if not args.dry_run:
            prior = load_json(output) if output.is_file() else {"format": FORMAT, "rows": []}
            prior.update(
                {
                    "status": "FAILED",
                    "completed_utc": datetime.now(UTC).isoformat(),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            atomic_write(output, prior)
        raise
    printable = {key: value for key, value in report.items() if key != "rows"}
    print(json.dumps(printable, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
