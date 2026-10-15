#!/usr/bin/env python3
"""Measure answer alignment, normalization visibility, and cache recurrence."""

from __future__ import annotations

import argparse
import dataclasses
import gc
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import traceback
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
from run_v14_experimental_chat import _case_features  # noqa: E402
from v13_visibility_trace import checkpoint_inventory  # noqa: E402

from latent_workspace_ft_v10 import engine  # noqa: E402
from latent_workspace_ft_v10.cache_binding import (  # noqa: E402
    ActivationPulse,
    MistralDynamicCacheAdapter,
)

PLAN_PATH = REPO / "configs/v14/ANSWER_BOUNDARY_RECURRENCE_PLAN.json"
FORMAT = "latent-workspace-v14-answer-boundary-recurrence-v1"
MODEL_ORDER = ("task", "semantic")
CONTROLS = ("learned_pair", "gram_matched_random", "unrelated_family", "sham")
HORIZONS = (0, 1, 2, 3, 4)
CONTRASTS = (
    "no_cache_one_shot",
    "no_cache_repeated_last_token",
    "no_cache_full_route",
    "cache_one_shot_carry",
    "cache_one_shot_reset",
    "cache_repeated_carry",
    "cache_repeated_reset",
    "cache_one_shot_history",
    "cache_repeated_history",
)


class RecurrenceError(RuntimeError):
    """Raised when the frozen recurrence microscope cannot execute exactly."""


@dataclasses.dataclass(frozen=True, slots=True)
class CaseSpec:
    case_id: str
    world_index: int
    pair_id: str
    side: int
    query_index: int
    query_text: str
    affected: bool
    heldout: bool
    hop_distance: int
    query_prefix: tuple[int, ...]
    contexts: tuple[tuple[int, ...], tuple[int, ...]]
    candidate_ids: tuple[int, int]
    original_label: int
    donor_label: int
    turn_chunk: tuple[int, ...]


@dataclasses.dataclass(slots=True)
class HorizonState:
    horizon: int
    history: tuple[int, ...]
    attention_mask: torch.Tensor
    boundary: torch.Tensor
    base_logits: torch.Tensor
    base_readout: dict[str, Any]
    updates: dict[str, torch.Tensor]
    native_updates: dict[str, torch.Tensor]
    full_route_readouts: dict[str, dict[str, Any]]
    reader_receipts: dict[str, dict[str, float]]


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _tensor_hash(value: torch.Tensor) -> str:
    tensor = value.detach().cpu().contiguous()
    header = json.dumps(
        {"dtype": str(tensor.dtype), "shape": list(tensor.shape)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    hasher = hashlib.sha256(header)
    hasher.update(tensor.view(torch.uint8).numpy().tobytes())
    return hasher.hexdigest()


def _runtime() -> dict[str, Any]:
    import transformers

    return {
        "python": ".".join(str(value) for value in sys.version_info[:3]),
        "torch": str(torch.__version__),
        "transformers": str(transformers.__version__),
        "cuda": torch.version.cuda,
    }


def _require_idle_gpu() -> str:
    result = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        raise RecurrenceError("GPU already has compute clients; refusing to interfere")
    return "NO_COMPUTE_CLIENTS_AT_CHECK"


def _source_identity(root: Path, plan: dict[str, Any]) -> dict[str, str]:
    expected = plan.get("source_identity")
    if not isinstance(expected, dict) or not expected:
        raise RecurrenceError("Frozen source_identity must be a nonempty mapping")
    observed = {}
    for relative in expected:
        path = resolve_inside(root, relative, label="source identity")
        if not path.is_file() or path.is_symlink():
            raise RecurrenceError(f"Source identity is not a plain file: {relative}")
        observed[relative] = digest(path)
    return observed


def validate_plan(
    root: Path,
    plan: dict[str, Any],
    *,
    require_fresh: bool,
    verify_checkpoints: bool = True,
) -> dict[str, Any]:
    expected = {
        "format": "latent-workspace-v14-answer-boundary-recurrence-plan-v1",
        "frozen_before_target_model_scoring": True,
        "model_order": list(MODEL_ORDER),
        "controls": list(CONTROLS),
        "horizons": list(HORIZONS),
        "expected_cases_per_model": 8,
        "expected_rows": 320,
        "boundary_layer": 16,
        "fixed_tokens_across_all_cells": True,
        "free_generation": False,
    }
    mismatches = {
        key: {"observed": plan.get(key), "expected": value}
        for key, value in expected.items()
        if plan.get(key) != value
    }
    expected_lanes = {
        "no_cache": [
            "base",
            "one_shot_last_token",
            "repeated_last_token",
            "repeated_full_route_reference",
        ],
        "cache": [
            "base",
            "one_shot_carry",
            "one_shot_reset",
            "repeated_carry",
            "repeated_reset_before_current_read",
        ],
    }
    if plan.get("lanes") != expected_lanes:
        mismatches["lanes"] = {
            "observed": plan.get("lanes"),
            "expected": expected_lanes,
        }
    expected_actions = {
        "checkpoint_load": True,
        "answer_margin_and_local_gradient": True,
        "rmsnorm_and_bf16_visibility": True,
        "teacher_forced_no_cache_and_native_cache_trajectory": True,
        "optimizer_or_training": False,
        "free_generation": False,
        "model_download": False,
        "weight_write_or_delete": False,
        "gain_layer_case_horizon_or_threshold_selection": False,
        "semantic_promotion": False,
    }
    if plan.get("authorized_actions") != expected_actions:
        mismatches["authorized_actions"] = {
            "observed": plan.get("authorized_actions"),
            "expected": expected_actions,
        }
    if mismatches:
        raise RecurrenceError(f"Frozen plan mismatch: {mismatches}")

    predecessors = {}
    for name, artifact in plan["predecessors"].items():
        path = resolve_inside(root, artifact["path"], label=f"predecessor {name}")
        if not path.is_file() or digest(path) != artifact["sha256"]:
            raise RecurrenceError(f"Predecessor changed: {name}")
        predecessors[name] = path
    comparison = load_json(predecessors["grouped_comparison"])
    if comparison.get("winner") != "none":
        raise RecurrenceError("This microscope is bound to the no-winner comparison")
    no_cache = load_json(predecessors["no_cache_generation"])
    if (
        no_cache.get("status") != "COMPLETED"
        or no_cache.get("generation_protocol", {}).get("kv_cache") is not False
        or no_cache.get("generation_count") != 192
    ):
        raise RecurrenceError("The required completed no-cache control is absent")

    eval_spec = plan["eval"]
    eval_path = resolve_inside(root, eval_spec["path"], label="eval")
    if not eval_path.is_file() or digest(eval_path) != eval_spec["sha256"]:
        raise RecurrenceError("Frozen evaluation file changed")
    cases = plan.get("cases")
    if not isinstance(cases, list) or len(cases) != 8:
        raise RecurrenceError("Exactly eight frozen cases are required")
    if len({str(case.get("id")) for case in cases}) != 8:
        raise RecurrenceError("Frozen case IDs must be unique")

    models = plan.get("models")
    if not isinstance(models, list) or [model.get("id") for model in models] != list(MODEL_ORDER):
        raise RecurrenceError("Ordered task and semantic checkpoints are required")
    resolved_models = {}
    for model in models:
        checkpoint = resolve_inside(root, model["checkpoint"], label="checkpoint")
        if verify_checkpoints:
            if not (checkpoint / "COMPLETED").is_file():
                raise RecurrenceError(f"Incomplete checkpoint: {model['id']}")
            if digest(checkpoint / "manifest.json") != model["manifest_sha256"]:
                raise RecurrenceError(f"Checkpoint manifest changed: {model['id']}")
            if digest(checkpoint / "workspace_state.pt") != model["workspace_sha256"]:
                raise RecurrenceError(f"Workspace state changed: {model['id']}")
        resolved_models[str(model["id"])] = {**model, "path": checkpoint}

    observed_source = _source_identity(root, plan)
    if observed_source != plan["source_identity"]:
        raise RecurrenceError("Frozen source identity changed")
    output = resolve_inside(root, plan["output"], label="output")
    if require_fresh and output.exists():
        raise RecurrenceError(f"Output already exists: {output}")
    return {
        "predecessors": predecessors,
        "eval": eval_path,
        "models": resolved_models,
        "output": output,
    }


def _validate_runtime(plan: dict[str, Any]) -> dict[str, Any]:
    observed = _runtime()
    if observed != plan["expected_runtime"]:
        raise RecurrenceError(
            f"Runtime mismatch: observed={observed}, expected={plan['expected_runtime']}"
        )
    environment = {key: os.environ.get(key) for key in plan["required_environment"]}
    if environment != plan["required_environment"]:
        raise RecurrenceError(f"Environment mismatch: {environment}")
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RecurrenceError("Exactly one visible CUDA device is required")
    observed["gpu"] = torch.cuda.get_device_name(0)
    observed["environment"] = environment
    return observed


def _validate_model_config(config: Any, plan: dict[str, Any], model_id: str) -> None:
    observed = {
        "name_or_path": config.model.name_or_path,
        "revision": config.model.revision,
        "dtype": config.model.dtype,
        "attn_implementation": config.model.attn_implementation,
        "route_mode": config.functional.route_mode,
        "boundary_layer": config.functional.boundary_layer,
        "reader_steps": config.functional.reader_steps,
        "workspace_norm_kind": config.functional.workspace_norm_kind,
        "workspace_norm_eps": config.functional.workspace_norm_eps,
        "use_chat_template": config.data.use_chat_template,
        "functional_elicitation": config.data.functional_elicitation,
        "mixed_precision": config.train.mixed_precision,
    }
    expected = plan["model_contract"]
    if observed != expected:
        raise RecurrenceError(f"Model protocol changed for {model_id}: {observed}")


def _direction_stats(value: torch.Tensor) -> dict[str, Any]:
    tensor = value.detach().float().cpu().contiguous()
    finite = bool(torch.isfinite(tensor).all())
    return {
        "shape": list(tensor.shape),
        "finite": finite,
        "nonzero": bool(finite and torch.count_nonzero(tensor).item()),
        "rms": float(torch.sqrt(torch.mean(tensor * tensor)).item()),
        "l2": float(torch.linalg.vector_norm(tensor).item()),
        "max_abs": float(tensor.abs().max().item()),
        "sha256": _tensor_hash(tensor),
    }


def _rms(value: torch.Tensor) -> float:
    tensor = value.detach().float()
    return float(torch.sqrt(torch.mean(tensor * tensor)).item())


def _cosine(left: torch.Tensor, right: torch.Tensor) -> float | None:
    first = left.detach().double().flatten()
    second = right.detach().double().flatten()
    denominator = torch.linalg.vector_norm(first) * torch.linalg.vector_norm(second)
    if not bool(torch.isfinite(denominator)) or float(denominator.item()) == 0.0:
        return None
    return float((torch.dot(first, second) / denominator).item())


def _projection(vector: torch.Tensor, basis: torch.Tensor) -> dict[str, Any]:
    first = vector.detach().double().flatten()
    second = basis.detach().double().flatten()
    if first.shape != second.shape or not bool(
        torch.isfinite(first).all() and torch.isfinite(second).all()
    ):
        raise RecurrenceError("Projection vectors must be finite and shape matched")
    return {
        "dot": float(torch.dot(first, second).item()),
        "cosine": _cosine(first, second),
        "vector_l2": float(torch.linalg.vector_norm(first).item()),
        "basis_l2": float(torch.linalg.vector_norm(second).item()),
    }


def _scale_to_rms(value: torch.Tensor, target_rms: float) -> torch.Tensor:
    tensor = value.detach().double().cpu().contiguous()
    observed = torch.sqrt(torch.mean(tensor * tensor))
    if (
        not bool(torch.isfinite(tensor).all())
        or not bool(torch.isfinite(observed))
        or float(observed.item()) == 0.0
        or not math.isfinite(target_rms)
        or target_rms <= 0.0
    ):
        raise RecurrenceError("Cannot RMS-match a zero or nonfinite vector")
    return (tensor * (target_rms / float(observed.item()))).float()


def _gram(left: torch.Tensor, right: torch.Tensor) -> dict[str, float]:
    first = left.detach().double().cpu().flatten()
    second = right.detach().double().cpu().flatten()
    aa = float(torch.dot(first, first).item())
    bb = float(torch.dot(second, second).item())
    ab = float(torch.dot(first, second).item())
    if aa <= 0.0 or bb <= 0.0:
        raise RecurrenceError("Gram matrix requires nonzero vectors")
    return {"aa": aa, "bb": bb, "ab": ab, "cosine": ab / math.sqrt(aa * bb)}


def _gram_matched_random_pair(
    intact: torch.Tensor,
    twin: torch.Tensor,
    *,
    seed: int,
) -> tuple[torch.Tensor, torch.Tensor, dict[str, Any]]:
    reference = _gram(intact, twin)
    width = intact.numel()
    generator = torch.Generator(device="cpu").manual_seed(seed)
    q1 = torch.randn(width, generator=generator, dtype=torch.float64)
    q1 = q1 / torch.linalg.vector_norm(q1)
    q2 = torch.randn(width, generator=generator, dtype=torch.float64)
    q2 = q2 - torch.dot(q2, q1) * q1
    q2 = q2 / torch.linalg.vector_norm(q2)
    norm_a = math.sqrt(reference["aa"])
    norm_b = math.sqrt(reference["bb"])
    cosine = max(-1.0, min(1.0, reference["cosine"]))
    sine = math.sqrt(max(0.0, 1.0 - cosine * cosine))
    random_a = (norm_a * q1).float()
    random_b = (norm_b * (cosine * q1 + sine * q2)).float()
    observed = _gram(random_a, random_b)
    relative = {
        key: abs(observed[key] - reference[key]) / max(abs(reference[key]), 1e-12)
        for key in ("aa", "bb", "ab")
    }
    relative["cosine_absolute"] = abs(observed["cosine"] - reference["cosine"])
    relative["maximum"] = max(relative.values())
    return (
        random_a,
        random_b,
        {
            "seed": seed,
            "reference": reference,
            "observed": observed,
            "relative_error": relative,
        },
    )


def _readout(
    logits: torch.Tensor,
    candidate_ids: tuple[int, int],
    *,
    original_label: int,
    donor_label: int,
    affected: bool,
) -> dict[str, Any]:
    values = logits.detach().float()
    if values.ndim == 3:
        values = values[0, -1]
    elif values.ndim == 2:
        values = values[-1]
    if values.ndim != 1 or not bool(torch.isfinite(values).all()):
        raise RecurrenceError("Answer-boundary logits must be one finite vocabulary vector")
    if len(candidate_ids) != 2 or candidate_ids[0] == candidate_ids[1]:
        raise RecurrenceError("Exactly two distinct answer-token IDs are required")
    choices = [float(values[token].item()) for token in candidate_ids]
    prediction = None if choices[0] == choices[1] else int(choices[1] > choices[0])
    alternative_label = 1 - original_label
    original_margin = choices[original_label] - choices[alternative_label]
    if affected:
        if donor_label == original_label:
            raise RecurrenceError("Affected readout must have a distinct donor label")
        target_label = donor_label
        reference_label = original_label
        target_name = "donor_minus_original"
        donor_margin: float | None = choices[donor_label] - choices[original_label]
    else:
        if donor_label != original_label:
            raise RecurrenceError("Unaffected readout must preserve the donor label")
        target_label = original_label
        reference_label = alternative_label
        target_name = "original_minus_alternative"
        donor_margin = None
    return {
        "candidate_token_ids": list(candidate_ids),
        "candidate_logits": choices,
        "yes_minus_no": choices[1] - choices[0],
        "prediction": prediction,
        "original_label": original_label,
        "donor_label": donor_label,
        "original_margin": original_margin,
        "donor_margin": donor_margin,
        "analysis_target": target_name,
        "analysis_target_label": target_label,
        "analysis_reference_label": reference_label,
        "analysis_margin": choices[target_label] - choices[reference_label],
    }


def _pair_effect(
    intact: dict[str, Any],
    twin: dict[str, Any],
    *,
    affected: bool,
) -> float:
    key = "donor_margin" if affected else "original_margin"
    left = intact[key]
    right = twin[key]
    if left is None or right is None:
        raise RecurrenceError("Pair effect received an undefined signed margin")
    return float(right) - float(left)


def _member_pair(
    intact: dict[str, Any],
    twin: dict[str, Any],
    *,
    affected: bool,
) -> dict[str, Any]:
    return {
        "intact": intact,
        "twin": twin,
        "signed_pair_effect": _pair_effect(intact, twin, affected=affected),
        "effect_definition": (
            "twin_donor_margin_minus_intact_donor_margin"
            if affected
            else "twin_original_margin_minus_intact_original_margin"
        ),
    }


def _quantiles(value: torch.Tensor) -> dict[str, float | None]:
    tensor = value.detach().float().cpu().flatten()
    tensor = tensor[torch.isfinite(tensor)]
    if tensor.numel() == 0:
        return {"q50": None, "q90": None, "maximum": None}
    return {
        "q50": float(torch.quantile(tensor, 0.5).item()),
        "q90": float(torch.quantile(tensor, 0.9).item()),
        "maximum": float(tensor.max().item()),
    }


def _fp32_rmsnorm(hidden: torch.Tensor, module: torch.nn.Module) -> torch.Tensor:
    eps = getattr(module, "variance_epsilon", getattr(module, "eps", None))
    weight = getattr(module, "weight", None)
    if eps is None or not isinstance(weight, torch.Tensor):
        raise RecurrenceError("Layer-16 input normalization is not a supported RMSNorm")
    value = hidden.float()
    normalized = value * torch.rsqrt(value.pow(2).mean(dim=-1, keepdim=True) + float(eps))
    return normalized * weight.detach().float()


@torch.no_grad()
def _compose_and_visibility(
    hidden: torch.Tensor,
    requested: torch.Tensor | None,
    input_rmsnorm: torch.nn.Module,
) -> tuple[torch.Tensor, dict[str, Any]]:
    if hidden.ndim != 3 or hidden.shape[0] != 1 or hidden.shape[1] != 1:
        raise RecurrenceError("Visibility microscope requires one last-token boundary vector")
    base = hidden.detach()
    if requested is None:
        request = torch.zeros_like(base, dtype=torch.float32)
    else:
        request = requested.detach().to(device=base.device, dtype=torch.float32).reshape_as(base)
    modified = (base.float() + request).to(dtype=base.dtype)
    actual = modified.float() - base.float()

    base_cpu = base.detach().to(device="cpu", dtype=torch.bfloat16)
    request_cpu = request.detach().float().cpu()
    toward = torch.where(
        request_cpu >= 0,
        torch.full_like(request_cpu, float("inf"), dtype=torch.bfloat16),
        torch.full_like(request_cpu, float("-inf"), dtype=torch.bfloat16),
    )
    neighbor = torch.nextafter(base_cpu, toward)
    ulp = (neighbor.float() - base_cpu.float()).abs()
    valid_ulp = torch.isfinite(ulp) & (ulp > 0)
    ratio = torch.full_like(request_cpu, float("nan"))
    ratio[valid_ulp] = request_cpu.abs()[valid_ulp] / ulp[valid_ulp]
    requested_nonzero = request_cpu != 0
    actual_nonzero = actual.detach().cpu() != 0

    native_before = input_rmsnorm(base)
    native_after = input_rmsnorm(modified)
    reference_before = _fp32_rmsnorm(base, input_rmsnorm)
    reference_after = _fp32_rmsnorm(modified, input_rmsnorm)
    native_delta = native_after.float() - native_before.float()
    reference_cast = reference_after.to(native_after.dtype).float()
    exact_reference = bool(torch.equal(native_after.float(), reference_cast))
    visible_count = int(torch.count_nonzero(actual_nonzero).item())
    request_count = int(torch.count_nonzero(requested_nonzero).item())
    lost_count = int(torch.count_nonzero(requested_nonzero & ~actual_nonzero).item())
    return modified, {
        "hidden_dtype": str(base.dtype),
        "requested": _direction_stats(request),
        "actual_native_delta": _direction_stats(actual),
        "requested_actual_cosine": _cosine(request, actual),
        "requested_nonzero_components": request_count,
        "actual_nonzero_components": visible_count,
        "lost_requested_components": lost_count,
        "lost_requested_fraction": lost_count / max(request_count, 1),
        "ulp_ratio": _quantiles(ratio),
        "ulp_ratio_at_least_half_fraction": float(
            torch.count_nonzero(ratio >= 0.5).item() / max(int(valid_ulp.sum().item()), 1)
        ),
        "ulp_ratio_at_least_one_fraction": float(
            torch.count_nonzero(ratio >= 1.0).item() / max(int(valid_ulp.sum().item()), 1)
        ),
        "rmsnorm": {
            "before": _direction_stats(native_before),
            "after": _direction_stats(native_after),
            "native_delta": _direction_stats(native_delta),
            "requested_native_delta_projection": _projection(actual, request)
            if request_count
            else None,
            "native_after_matches_fp32_reference_cast_exactly": exact_reference,
            "native_after_vs_fp32_reference_cast_max_abs": float(
                (native_after.float() - reference_cast).abs().max().item()
            ),
            "fp32_reference_delta_rms": _rms(reference_after - reference_before),
        },
    }


def _compact_cache_difference(value: dict[str, Any], layer: int) -> dict[str, Any]:
    row = value["per_layer"][layer]
    return {
        "aggregate_l2": value["aggregate_l2"],
        "aggregate_max_abs": value["aggregate_max_abs"],
        "nonzero_count": value["nonzero_count"],
        "exact_equal": value["exact_equal"],
        "layer16": {
            key: row[key]
            for key in (
                "key_l2",
                "value_l2",
                "key_last_position_l2",
                "value_last_position_l2",
            )
        },
    }


def _full_logit_l2(left: torch.Tensor, right: torch.Tensor) -> float:
    delta = left.detach().float() - right.detach().float()
    if left.shape != right.shape or not bool(torch.isfinite(delta).all()):
        raise RecurrenceError("Full-logit displacement must be finite and shape matched")
    return float(torch.linalg.vector_norm(delta).item())


def _cache_receipt(
    result: Any,
    base: Any,
    adapter: MistralDynamicCacheAdapter,
    case: CaseSpec,
    *,
    layer: int,
) -> dict[str, Any]:
    return {
        "readout": _readout(
            result.logits,
            case.candidate_ids,
            original_label=case.original_label,
            donor_label=case.donor_label,
            affected=case.affected,
        ),
        "full_logit_l2_from_base": _full_logit_l2(result.logits[:, -1:], base.logits[:, -1:]),
        "cache_from_base": _compact_cache_difference(
            adapter.difference(result.cache, base.cache), layer
        ),
        "pulse": result.receipt.get("pulse"),
    }


def _extend_chunk(
    adapter: MistralDynamicCacheAdapter,
    cache: Any,
    token_ids: tuple[int, ...],
) -> Any:
    if not token_ids:
        raise RecurrenceError("Fixed turn chunk cannot be empty")
    past = adapter._cache_length(cache)
    device = next(adapter.model.parameters()).device
    tokens = torch.tensor([token_ids], device=device, dtype=torch.long)
    positions = torch.arange(past, past + len(token_ids), device=device)[None, :]
    mask = torch.ones((1, past + len(token_ids)), device=device, dtype=torch.long)
    adapter._validate_forward_inputs(tokens, mask, positions, past_length=past, one_token=False)
    return adapter._forward(
        input_ids=tokens,
        attention_mask=mask,
        position_ids=positions,
        cache=cache,
        pulse=None,
        clone_cache=True,
    )


def _pulse_step(
    adapter: MistralDynamicCacheAdapter,
    cache: Any,
    token_id: int,
    direction: torch.Tensor | None,
    *,
    layer: int,
) -> Any:
    past = adapter._cache_length(cache)
    device = next(adapter.model.parameters()).device
    token = torch.tensor([[token_id]], device=device, dtype=torch.long)
    mask = torch.ones((1, past + 1), device=device, dtype=torch.long)
    position = torch.tensor([[past]], device=device, dtype=torch.long)
    pulse = None
    if direction is not None:
        amplitude = _rms(direction)
        if amplitude <= 0.0:
            raise RecurrenceError("A non-sham cache pulse must be nonzero")
        pulse = ActivationPulse(layer_index=layer, direction=direction, scale=amplitude)
    return adapter.step(token, cache, mask, position, pulse=pulse)


@torch.no_grad()
def _context_memory(
    model: Any,
    context: tuple[int, ...],
    *,
    device: torch.device,
    precision: str,
    boundary_layer: int,
) -> tuple[torch.Tensor, torch.Tensor]:
    if model.functional_boundary_adapter is None or model.functional_writer is None:
        raise RecurrenceError("Functional writer and boundary adapter are required")
    ids = torch.tensor([context], device=device, dtype=torch.long)
    attention = torch.ones_like(ids)
    with engine.autocast_context(device, precision):
        hidden = model.functional_boundary_adapter.encode(ids, attention, boundary_layer)
        memory, memory_mask, trajectory, _anchor = model.functional_writer(hidden, attention)
    if model.functional_config.readout_step != -1:
        memory = trajectory[:, :, model.functional_config.readout_step - 1, :]
    return memory.detach(), memory_mask.detach()


def _build_cases(dataset: Any, tokenizer: Any, plan: dict[str, Any]) -> list[CaseSpec]:
    features = _case_features(dataset, plan["cases"])
    cases: list[CaseSpec] = []
    for frozen, feature in zip(plan["cases"], features, strict=True):
        world = int(feature["world_index"])
        source = dataset._read_record(dataset.locations[world])
        query_index = int(feature["query_index"])
        query_text = str(source["queries"][query_index])
        pair_id = str(source.get("metadata", {}).get("pair_id", f"world-{world}"))
        original_label = int(feature["original_answer"])
        donor_label = int(feature["donor_answer"])
        candidate_ids = tuple(int(value) for value in feature["choice_token_ids"])
        suffix = tuple(
            int(value) for value in tokenizer.encode("\n" + query_text, add_special_tokens=False)
        )
        if not suffix:
            raise RecurrenceError(f"Repeated query tokenization is empty: {frozen['id']}")
        affected = bool(feature["affected"])
        if affected != (donor_label != original_label):
            raise RecurrenceError(f"Affected flag and donor answer disagree: {frozen['id']}")
        cases.append(
            CaseSpec(
                case_id=str(feature["id"]),
                world_index=world,
                pair_id=pair_id,
                side=int(feature["side"]),
                query_index=query_index,
                query_text=query_text,
                affected=affected,
                heldout=bool(feature["heldout"]),
                hop_distance=int(feature["hop_distance"]),
                query_prefix=tuple(int(value) for value in feature["query_prefix"]),
                contexts=tuple(
                    tuple(int(token) for token in context) for context in feature["contexts"]
                ),
                candidate_ids=(candidate_ids[0], candidate_ids[1]),
                original_label=original_label,
                donor_label=donor_label,
                turn_chunk=(candidate_ids[original_label], *suffix),
            )
        )
    if len(cases) != 8 or len({case.case_id for case in cases}) != 8:
        raise RecurrenceError("Exactly eight unique cases must be projected")
    if sum(case.affected for case in cases) != 4:
        raise RecurrenceError("The frozen matrix must contain four affected controls")
    return cases


@torch.no_grad()
def _precompute_horizons(
    model: Any,
    cases: list[CaseSpec],
    *,
    device: torch.device,
    precision: str,
    boundary_layer: int,
) -> dict[str, list[HorizonState]]:
    if model.functional_boundary_adapter is None or model.functional_reader is None:
        raise RecurrenceError("Functional reader and split decoder are required")
    memories: dict[tuple[int, int], tuple[torch.Tensor, torch.Tensor]] = {}
    for case in cases:
        for source_side in (case.side, 1 - case.side):
            key = (case.world_index, source_side)
            if key not in memories:
                memories[key] = _context_memory(
                    model,
                    case.contexts[source_side],
                    device=device,
                    precision=precision,
                    boundary_layer=boundary_layer,
                )

    output: dict[str, list[HorizonState]] = {}
    for case_index, case in enumerate(cases):
        print(f"precompute boundary case {case_index + 1}/{len(cases)} {case.case_id}", flush=True)
        history = case.query_prefix
        states: list[HorizonState] = []
        for horizon in HORIZONS:
            ids = torch.tensor([history], device=device, dtype=torch.long)
            attention = torch.ones_like(ids)
            with engine.autocast_context(device, precision):
                boundary = model.functional_boundary_adapter.encode(ids, attention, boundary_layer)
                base_logits = model.functional_boundary_adapter.decode(
                    boundary, attention, boundary_layer
                )
            updates: dict[str, torch.Tensor] = {}
            native_updates: dict[str, torch.Tensor] = {}
            full_route_readouts: dict[str, dict[str, Any]] = {}
            reader_receipts: dict[str, dict[str, float]] = {}
            for member, source_side in (
                ("intact", case.side),
                ("twin", 1 - case.side),
            ):
                memory, memory_mask = memories[(case.world_index, source_side)]
                with engine.autocast_context(device, precision):
                    reader_state = model.functional_reader.read_state(
                        boundary, attention, memory, memory_mask
                    )
                    full_logits = model.functional_boundary_adapter.decode(
                        reader_state.final_state, attention, boundary_layer
                    )
                if len(reader_state.per_step_updates) != 1:
                    raise RecurrenceError("This frozen microscope requires one reader step")
                requested = reader_state.per_step_updates[0][0, -1].detach().float().cpu()
                native = (
                    reader_state.final_state[0, -1].detach().float()
                    - reader_state.initial_state[0, -1].detach().float()
                ).cpu()
                if not bool(torch.isfinite(requested).all() and torch.isfinite(native).all()):
                    raise RecurrenceError("Learned boundary update became nonfinite")
                updates[member] = requested.contiguous()
                native_updates[member] = native.contiguous()
                full_route_readouts[member] = _readout(
                    full_logits,
                    case.candidate_ids,
                    original_label=case.original_label,
                    donor_label=case.donor_label,
                    affected=case.affected,
                )
                reader_receipts[member] = {
                    "gate_mean": float(reader_state.gate_mean.detach().float().item()),
                    "read_norm": float(reader_state.read_norm.detach().float().item()),
                }
            states.append(
                HorizonState(
                    horizon=horizon,
                    history=history,
                    attention_mask=attention.detach(),
                    boundary=boundary.detach(),
                    base_logits=base_logits.detach(),
                    base_readout=_readout(
                        base_logits,
                        case.candidate_ids,
                        original_label=case.original_label,
                        donor_label=case.donor_label,
                        affected=case.affected,
                    ),
                    updates=updates,
                    native_updates=native_updates,
                    full_route_readouts=full_route_readouts,
                    reader_receipts=reader_receipts,
                )
            )
            history = (*history, *case.turn_chunk)
        output[case.case_id] = states
    return output


def _control_pairs(
    case: CaseSpec,
    horizon: HorizonState,
    unrelated: HorizonState,
    *,
    seed: int,
) -> tuple[dict[str, dict[str, torch.Tensor | None]], dict[str, Any]]:
    intact = horizon.updates["intact"]
    twin = horizon.updates["twin"]
    if _rms(intact) <= 0.0 or _rms(twin) <= 0.0:
        raise RecurrenceError("Learned intact/twin update is zero; matched controls are undefined")
    random_intact, random_twin, random_receipt = _gram_matched_random_pair(intact, twin, seed=seed)
    unrelated_intact = _scale_to_rms(unrelated.updates["intact"], _rms(intact))
    unrelated_twin = _scale_to_rms(unrelated.updates["twin"], _rms(twin))
    controls = {
        "learned_pair": {"intact": intact, "twin": twin},
        "gram_matched_random": {"intact": random_intact, "twin": random_twin},
        "unrelated_family": {"intact": unrelated_intact, "twin": unrelated_twin},
        "sham": {"intact": None, "twin": None},
    }
    metadata = {
        "learned_pair": {
            "intact": _direction_stats(intact),
            "twin": _direction_stats(twin),
            "gram": _gram(intact, twin),
        },
        "gram_matched_random": {
            "intact": _direction_stats(random_intact),
            "twin": _direction_stats(random_twin),
            "gram_receipt": random_receipt,
        },
        "unrelated_family": {
            "source_case_id": (
                f"world{1 - case.world_index}:side{case.side}:query{case.query_index}"
            ),
            "distinct_world_family": True,
            "intact": _direction_stats(unrelated_intact),
            "twin": _direction_stats(unrelated_twin),
            "target_rms": {"intact": _rms(intact), "twin": _rms(twin)},
        },
        "sham": {"pulse": False},
    }
    return controls, metadata


def _answer_basis(
    base_model: Any,
    case: CaseSpec,
) -> tuple[torch.Tensor, int, int]:
    target_label = case.donor_label if case.affected else case.original_label
    reference_label = case.original_label if case.affected else 1 - case.original_label
    target_id = case.candidate_ids[target_label]
    reference_id = case.candidate_ids[reference_label]
    weight = base_model.lm_head.weight.detach().float()
    return (weight[target_id] - weight[reference_id]).cpu(), target_id, reference_id


def _local_answer_gradient(
    model: Any,
    state: HorizonState,
    case: CaseSpec,
    *,
    precision: str,
    boundary_layer: int,
) -> tuple[torch.Tensor, dict[str, Any]]:
    if model.functional_boundary_adapter is None:
        raise RecurrenceError("Split decoder is absent")
    target_label = case.donor_label if case.affected else case.original_label
    reference_label = case.original_label if case.affected else 1 - case.original_label
    target_id = case.candidate_ids[target_label]
    reference_id = case.candidate_ids[reference_label]
    with torch.enable_grad():
        probe = state.boundary.detach().clone().requires_grad_(True)
        with engine.autocast_context(probe.device, precision):
            logits = model.functional_boundary_adapter.decode(
                probe, state.attention_mask, boundary_layer
            )
        margin = logits[0, -1, target_id].float() - logits[0, -1, reference_id].float()
        gradient = torch.autograd.grad(margin, probe, retain_graph=False)[0][0, -1]
    gradient = gradient.detach().float().cpu().contiguous()
    if not bool(torch.isfinite(gradient).all()) or _rms(gradient) <= 0.0:
        raise RecurrenceError("Local answer-margin gradient is zero or nonfinite")
    return gradient, {
        "target_token_id": target_id,
        "reference_token_id": reference_id,
        "base_margin": float(margin.detach().item()),
        "gradient": _direction_stats(gradient),
    }


@torch.no_grad()
def _last_token_decode(
    model: Any,
    state: HorizonState,
    case: CaseSpec,
    requested: torch.Tensor | None,
    input_rmsnorm: torch.nn.Module,
    *,
    precision: str,
    boundary_layer: int,
) -> tuple[dict[str, Any], dict[str, Any], torch.Tensor]:
    if model.functional_boundary_adapter is None:
        raise RecurrenceError("Split decoder is absent")
    modified_last, visibility = _compose_and_visibility(
        state.boundary[:, -1:], requested, input_rmsnorm
    )
    modified = state.boundary.detach().clone()
    modified[:, -1:] = modified_last
    with engine.autocast_context(modified.device, precision):
        logits = model.functional_boundary_adapter.decode(
            modified, state.attention_mask, boundary_layer
        )
    readout = _readout(
        logits,
        case.candidate_ids,
        original_label=case.original_label,
        donor_label=case.donor_label,
        affected=case.affected,
    )
    actual = (modified_last.float() - state.boundary[:, -1:].float()).cpu().contiguous()
    return (
        {
            "readout": readout,
            "full_logit_l2_from_base": _full_logit_l2(logits, state.base_logits),
            "visibility": visibility,
        },
        visibility,
        actual,
    )


def _receipt_pair(
    receipts: dict[str, dict[str, Any]],
    *,
    affected: bool,
) -> dict[str, Any]:
    return {
        "intact": receipts["intact"],
        "twin": receipts["twin"],
        "signed_pair_effect": _pair_effect(
            receipts["intact"]["readout"],
            receipts["twin"]["readout"],
            affected=affected,
        ),
        "effect_definition": (
            "twin_donor_margin_minus_intact_donor_margin"
            if affected
            else "twin_original_margin_minus_intact_original_margin"
        ),
    }


def _cache_pair(
    results: dict[str, Any],
    base: Any,
    adapter: MistralDynamicCacheAdapter,
    case: CaseSpec,
    *,
    layer: int,
) -> dict[str, Any]:
    receipts = {
        member: _cache_receipt(result, base, adapter, case, layer=layer)
        for member, result in results.items()
    }
    return _receipt_pair(receipts, affected=case.affected)


def _run_cache_case(
    adapter: MistralDynamicCacheAdapter,
    case: CaseSpec,
    directions: dict[int, dict[str, dict[str, torch.Tensor | None]]],
    *,
    layer: int,
) -> dict[tuple[str, int], dict[str, Any]]:
    if len(case.query_prefix) < 2 or len(case.turn_chunk) < 2:
        raise RecurrenceError("Prefix and fixed turn must each contain at least two tokens")
    device = next(adapter.model.parameters()).device
    prefix = torch.tensor([case.query_prefix[:-1]], device=device, dtype=torch.long)
    prefill = adapter.prefill(
        prefix,
        torch.ones_like(prefix),
        torch.arange(prefix.shape[1], device=device, dtype=torch.long)[None, :],
    )
    base: list[Any] = [
        _pulse_step(
            adapter,
            prefill.cache,
            case.query_prefix[-1],
            None,
            layer=layer,
        )
    ]
    for _horizon in HORIZONS[1:]:
        base.append(_extend_chunk(adapter, base[-1].cache, case.turn_chunk))

    output: dict[tuple[str, int], dict[str, Any]] = {}
    for control in CONTROLS:
        initial = {
            member: _pulse_step(
                adapter,
                prefill.cache,
                case.query_prefix[-1],
                directions[0][control][member],
                layer=layer,
            )
            for member in ("intact", "twin")
        }
        one_shot = dict(initial)
        repeated = dict(initial)
        immediate = _cache_pair(initial, base[0], adapter, case, layer=layer)
        output[(control, 0)] = {
            "base": _readout(
                base[0].logits,
                case.candidate_ids,
                original_label=case.original_label,
                donor_label=case.donor_label,
                affected=case.affected,
            ),
            "one_shot_carry": immediate,
            "one_shot_reset": immediate,
            "repeated_carry": immediate,
            "repeated_reset_before_current_read": immediate,
            "one_shot_history_effect": 0.0,
            "repeated_history_effect": 0.0,
            "history_effect_definition": "carry_pair_effect_minus_current_read_with_base_history",
        }
        for horizon in HORIZONS[1:]:
            one_shot = {
                member: _extend_chunk(adapter, result.cache, case.turn_chunk)
                for member, result in one_shot.items()
            }
            repeated_next: dict[str, Any] = {}
            reset_next: dict[str, Any] = {}
            for member, result in repeated.items():
                carried_prefix = _extend_chunk(adapter, result.cache, case.turn_chunk[:-1])
                repeated_next[member] = _pulse_step(
                    adapter,
                    carried_prefix.cache,
                    case.turn_chunk[-1],
                    directions[horizon][control][member],
                    layer=layer,
                )
                reset_prefix = _extend_chunk(adapter, base[horizon - 1].cache, case.turn_chunk[:-1])
                reset_next[member] = _pulse_step(
                    adapter,
                    reset_prefix.cache,
                    case.turn_chunk[-1],
                    directions[horizon][control][member],
                    layer=layer,
                )
            repeated = repeated_next
            one_carry_receipt = _cache_pair(one_shot, base[horizon], adapter, case, layer=layer)
            repeated_carry_receipt = _cache_pair(
                repeated, base[horizon], adapter, case, layer=layer
            )
            reset_receipt = _cache_pair(
                {"intact": base[horizon], "twin": base[horizon]},
                base[horizon],
                adapter,
                case,
                layer=layer,
            )
            repeated_reset_receipt = _cache_pair(
                reset_next, base[horizon], adapter, case, layer=layer
            )
            output[(control, horizon)] = {
                "base": _readout(
                    base[horizon].logits,
                    case.candidate_ids,
                    original_label=case.original_label,
                    donor_label=case.donor_label,
                    affected=case.affected,
                ),
                "one_shot_carry": one_carry_receipt,
                "one_shot_reset": reset_receipt,
                "repeated_carry": repeated_carry_receipt,
                "repeated_reset_before_current_read": repeated_reset_receipt,
                "one_shot_history_effect": (
                    one_carry_receipt["signed_pair_effect"] - reset_receipt["signed_pair_effect"]
                ),
                "repeated_history_effect": (
                    repeated_carry_receipt["signed_pair_effect"]
                    - repeated_reset_receipt["signed_pair_effect"]
                ),
                "history_effect_definition": (
                    "carry_pair_effect_minus_current_read_with_base_history"
                ),
            }
    return output


def _projection_receipt(
    requested: torch.Tensor | None,
    actual: torch.Tensor,
    readout: dict[str, Any],
    base_readout: dict[str, Any],
    local_gradient: torch.Tensor,
    unembedding: torch.Tensor,
) -> dict[str, Any]:
    request = torch.zeros_like(actual) if requested is None else requested.reshape_as(actual)
    observed = float(readout["analysis_margin"]) - float(base_readout["analysis_margin"])
    local_requested = _projection(request, local_gradient)
    local_actual = _projection(actual, local_gradient)
    raw_requested = _projection(request, unembedding)
    raw_actual = _projection(actual, unembedding)
    return {
        "observed_analysis_margin_shift": observed,
        "local_gradient_requested": local_requested,
        "local_gradient_actual_native": local_actual,
        "local_linear_prediction": local_actual["dot"],
        "local_linear_residual": observed - float(local_actual["dot"]),
        "raw_unembedding_requested": raw_requested,
        "raw_unembedding_actual_native": raw_actual,
        "raw_unembedding_is_descriptive_only": True,
    }


def _build_no_cache_row(
    model: Any,
    case: CaseSpec,
    state: HorizonState,
    control: str,
    pair: dict[str, torch.Tensor | None],
    input_rmsnorm: torch.nn.Module,
    *,
    precision: str,
    boundary_layer: int,
    local_gradient: torch.Tensor | None,
    unembedding: torch.Tensor | None,
) -> dict[str, Any]:
    repeated_receipts: dict[str, dict[str, Any]] = {}
    actuals: dict[str, torch.Tensor] = {}
    for member in ("intact", "twin"):
        receipt, _visibility, actual = _last_token_decode(
            model,
            state,
            case,
            pair[member],
            input_rmsnorm,
            precision=precision,
            boundary_layer=boundary_layer,
        )
        if control == "learned_pair":
            expected = state.native_updates[member].reshape_as(actual)
            receipt["learned_reader_native_delta_exact"] = bool(torch.equal(actual, expected))
            receipt["learned_reader_native_delta_max_abs_error"] = float(
                (actual - expected).abs().max().item()
            )
            receipt["reader"] = state.reader_receipts[member]
        repeated_receipts[member] = receipt
        actuals[member] = actual
    repeated = _receipt_pair(repeated_receipts, affected=case.affected)

    if state.horizon == 0:
        one_shot = repeated
    else:
        base_receipt = {
            "readout": state.base_readout,
            "full_logit_l2_from_base": 0.0,
            "visibility": None,
        }
        one_shot = _receipt_pair(
            {"intact": base_receipt, "twin": base_receipt},
            affected=case.affected,
        )
    full_route = None
    if control == "learned_pair":
        full_route = _member_pair(
            state.full_route_readouts["intact"],
            state.full_route_readouts["twin"],
            affected=case.affected,
        )

    projection = None
    if state.horizon == 0:
        if local_gradient is None or unembedding is None:
            raise RecurrenceError("Horizon-zero local answer bases are missing")
        projection_members = {
            member: _projection_receipt(
                pair[member],
                actuals[member],
                repeated_receipts[member]["readout"],
                state.base_readout,
                local_gradient,
                unembedding,
            )
            for member in ("intact", "twin")
        }
        projection = {
            "members": projection_members,
            "observed_pair_effect": repeated["signed_pair_effect"],
            "local_linear_pair_prediction": (
                projection_members["twin"]["local_linear_prediction"]
                - projection_members["intact"]["local_linear_prediction"]
            ),
            "raw_unembedding_pair_projection": (
                projection_members["twin"]["raw_unembedding_actual_native"]["dot"]
                - projection_members["intact"]["raw_unembedding_actual_native"]["dot"]
            ),
        }
    return {
        "base": state.base_readout,
        "one_shot_last_token": one_shot,
        "repeated_last_token": repeated,
        "repeated_full_route_reference": full_route,
        "answer_projection_at_horizon_zero": projection,
    }


def _describe(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "mean": None,
            "mean_absolute": None,
            "positive": 0,
            "zero": 0,
            "negative": 0,
            "minimum": None,
            "maximum": None,
        }
    if not all(math.isfinite(value) for value in values):
        raise RecurrenceError("A summary contrast is nonfinite")
    return {
        "count": len(values),
        "mean": sum(values) / len(values),
        "mean_absolute": sum(abs(value) for value in values) / len(values),
        "positive": sum(value > 0.0 for value in values),
        "zero": sum(value == 0.0 for value in values),
        "negative": sum(value < 0.0 for value in values),
        "minimum": min(values),
        "maximum": max(values),
    }


def _contrast_value(row: dict[str, Any], contrast: str) -> float | None:
    if contrast == "no_cache_one_shot":
        return row["no_cache"]["one_shot_last_token"]["signed_pair_effect"]
    if contrast == "no_cache_repeated_last_token":
        return row["no_cache"]["repeated_last_token"]["signed_pair_effect"]
    if contrast == "no_cache_full_route":
        route = row["no_cache"]["repeated_full_route_reference"]
        return None if route is None else route["signed_pair_effect"]
    if contrast == "cache_one_shot_carry":
        return row["cache"]["one_shot_carry"]["signed_pair_effect"]
    if contrast == "cache_one_shot_reset":
        return row["cache"]["one_shot_reset"]["signed_pair_effect"]
    if contrast == "cache_repeated_carry":
        return row["cache"]["repeated_carry"]["signed_pair_effect"]
    if contrast == "cache_repeated_reset":
        return row["cache"]["repeated_reset_before_current_read"]["signed_pair_effect"]
    if contrast == "cache_one_shot_history":
        return row["cache"]["one_shot_history_effect"]
    if contrast == "cache_repeated_history":
        return row["cache"]["repeated_history_effect"]
    raise RecurrenceError(f"Unknown frozen contrast: {contrast}")


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str, bool, int, str], list[float]] = defaultdict(list)
    for row in rows:
        for contrast in CONTRASTS:
            value = _contrast_value(row, contrast)
            if value is not None:
                grouped[
                    (
                        row["model"],
                        row["control"],
                        bool(row["affected"]),
                        int(row["horizon"]),
                        contrast,
                    )
                ].append(float(value))
    by_horizon: dict[str, Any] = {}
    for model_id in MODEL_ORDER:
        by_horizon[model_id] = {}
        for control in CONTROLS:
            by_horizon[model_id][control] = {}
            for population, affected in (("affected", True), ("unaffected", False)):
                by_horizon[model_id][control][population] = {
                    str(horizon): {
                        contrast: _describe(
                            grouped[(model_id, control, affected, horizon, contrast)]
                        )
                        for contrast in CONTRASTS
                    }
                    for horizon in HORIZONS
                }

    auc: dict[str, Any] = {}
    affected_rows = [row for row in rows if row["affected"]]
    for model_id in MODEL_ORDER:
        auc[model_id] = {}
        for control in CONTROLS:
            auc[model_id][control] = {}
            selected = [
                row
                for row in affected_rows
                if row["model"] == model_id and row["control"] == control
            ]
            case_ids = sorted({row["case_id"] for row in selected})
            for contrast in CONTRASTS:
                values: list[float] = []
                endpoints: list[float] = []
                for case_id in case_ids:
                    trajectory = sorted(
                        (row for row in selected if row["case_id"] == case_id),
                        key=lambda row: row["horizon"],
                    )
                    samples = [_contrast_value(row, contrast) for row in trajectory]
                    if any(value is None for value in samples):
                        continue
                    numeric = [float(value) for value in samples if value is not None]
                    if len(numeric) != len(HORIZONS):
                        raise RecurrenceError("Affected contrast trajectory lost a horizon")
                    values.append(
                        sum(0.5 * (numeric[index] + numeric[index + 1]) for index in range(4))
                    )
                    endpoints.append(numeric[-1])
                auc[model_id][control][contrast] = {
                    "trapezoid_auc": _describe(values),
                    "endpoint": _describe(endpoints),
                }

    projection: dict[str, Any] = {}
    for model_id in MODEL_ORDER:
        projection[model_id] = {}
        for control in CONTROLS:
            selected = [
                row["no_cache"]["answer_projection_at_horizon_zero"]
                for row in rows
                if row["model"] == model_id and row["control"] == control and row["horizon"] == 0
            ]
            projection[model_id][control] = {
                "observed_pair_effect": _describe(
                    [float(value["observed_pair_effect"]) for value in selected]
                ),
                "local_linear_pair_prediction": _describe(
                    [float(value["local_linear_pair_prediction"]) for value in selected]
                ),
                "raw_unembedding_pair_projection": _describe(
                    [float(value["raw_unembedding_pair_projection"]) for value in selected]
                ),
            }

    visibility: dict[str, Any] = {}
    for model_id in MODEL_ORDER:
        visibility[model_id] = {}
        for population, affected in (("affected", True), ("unaffected", False)):
            visibility[model_id][population] = {}
            for horizon in HORIZONS:
                samples = [
                    row["no_cache"]["repeated_last_token"][member]["visibility"]
                    for row in rows
                    if row["model"] == model_id
                    and row["control"] == "learned_pair"
                    and bool(row["affected"]) == affected
                    and row["horizon"] == horizon
                    for member in ("intact", "twin")
                ]
                visibility[model_id][population][str(horizon)] = {
                    "lost_requested_fraction": _describe(
                        [float(value["lost_requested_fraction"]) for value in samples]
                    ),
                    "actual_native_delta_rms": _describe(
                        [float(value["actual_native_delta"]["rms"]) for value in samples]
                    ),
                    "post_rmsnorm_delta_rms": _describe(
                        [float(value["rmsnorm"]["native_delta"]["rms"]) for value in samples]
                    ),
                    "ulp_ratio_q50": _describe(
                        [
                            float(value["ulp_ratio"]["q50"])
                            for value in samples
                            if value["ulp_ratio"]["q50"] is not None
                        ]
                    ),
                }
    return {
        "signed_contrasts_by_horizon": by_horizon,
        "affected_endpoint_and_auc": auc,
        "horizon_zero_projection": projection,
        "learned_pair_bf16_and_rmsnorm_visibility": visibility,
        "semantic_assessment": "DESCRIPTIVE_MICROSCOPE_NO_PROMOTION_THRESHOLD",
        "winner": "none",
    }


def _model_mechanical_checks(
    rows: list[dict[str, Any]],
    *,
    parameter_identity_ok: bool,
    checkpoint_unchanged: bool,
    source_unchanged: bool,
    eval_unchanged: bool,
    tolerance: float,
) -> dict[str, bool]:
    sham = [row for row in rows if row["control"] == "sham"]
    learned = [row for row in rows if row["control"] == "learned_pair"]
    random = [row for row in rows if row["control"] == "gram_matched_random"]
    unrelated = [row for row in rows if row["control"] == "unrelated_family"]
    nonsham = [row for row in rows if row["control"] != "sham"]
    return {
        "row_count_complete": len(rows) == 160,
        "fixed_history_identical_across_controls": all(
            len(
                {
                    row["history_sha256"]
                    for row in rows
                    if row["case_id"] == selected["case_id"]
                    and row["horizon"] == selected["horizon"]
                }
            )
            == 1
            for selected in rows
        ),
        "learned_reader_native_delta_replayed_exactly": all(
            row["no_cache"]["repeated_last_token"][member]["learned_reader_native_delta_exact"]
            for row in learned
            for member in ("intact", "twin")
        ),
        "nonsham_native_cache_pulses_applied_once": all(
            row["cache"][lane][member]["pulse"]["applied"]
            and row["cache"][lane][member]["pulse"]["call_count"] == 1
            for row in nonsham
            for lane in (
                "repeated_carry",
                "repeated_reset_before_current_read",
            )
            for member in ("intact", "twin")
        ),
        "sham_no_cache_exact_noop": all(
            row["no_cache"]["repeated_last_token"][member]["full_logit_l2_from_base"] == 0.0
            for row in sham
            for member in ("intact", "twin")
        ),
        "sham_cache_exact_noop": all(
            row["cache"][lane][member]["cache_from_base"]["exact_equal"]
            and row["cache"][lane][member]["full_logit_l2_from_base"] == 0.0
            for row in sham
            for lane in (
                "one_shot_carry",
                "one_shot_reset",
                "repeated_carry",
                "repeated_reset_before_current_read",
            )
            for member in ("intact", "twin")
        ),
        "gram_control_within_tolerance": all(
            row["control_metadata"]["gram_receipt"]["relative_error"]["maximum"] <= tolerance
            for row in random
        ),
        "unrelated_control_distinct_and_rms_matched": all(
            row["control_metadata"]["distinct_world_family"]
            and all(
                abs(
                    row["control_metadata"][member]["rms"]
                    - row["control_metadata"]["target_rms"][member]
                )
                <= tolerance
                for member in ("intact", "twin")
            )
            for row in unrelated
        ),
        "inputs_sources_parameters_unchanged": bool(
            parameter_identity_ok and checkpoint_unchanged and source_unchanged and eval_unchanged
        ),
    }


def _process_model(
    model_id: str,
    checkpoint: Path,
    eval_path: Path,
    plan: dict[str, Any],
    *,
    device: torch.device,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, bool]]:
    inventory_before = checkpoint_inventory(checkpoint)
    model, tokenizer, config = engine.load_bundle(checkpoint, device=device)
    _validate_model_config(config, plan, model_id)
    precision = engine.resolve_mixed_precision(config.train.mixed_precision, device)
    boundary_layer = int(config.functional.boundary_layer)
    base_model = model.base_model.eval()
    parameter_dtypes = sorted({str(parameter.dtype) for parameter in base_model.parameters()})
    if parameter_dtypes != ["torch.bfloat16"]:
        raise RecurrenceError(f"Loaded base parameter dtype changed: {parameter_dtypes}")
    identities = {
        name: (id(parameter), parameter._version, parameter.dtype, parameter.requires_grad)
        for name, parameter in model.named_parameters()
    }
    dataset = engine.JsonlFineTuningDataset([str(eval_path)], tokenizer, config.data)
    cases = _build_cases(dataset, tokenizer, plan)
    horizon_states = _precompute_horizons(
        model,
        cases,
        device=device,
        precision=precision,
        boundary_layer=boundary_layer,
    )
    adapter = MistralDynamicCacheAdapter(base_model)
    input_rmsnorm = base_model.model.layers[boundary_layer].input_layernorm
    lookup = {(case.world_index, case.side, case.query_index): case for case in cases}
    if len({case.pair_id for case in cases}) != 2:
        raise RecurrenceError("Unrelated control requires two distinct world families")

    rows: list[dict[str, Any]] = []
    case_receipts: list[dict[str, Any]] = []
    for case_index, case in enumerate(cases):
        print(
            f"measure recurrence case {case_index + 1}/{len(cases)} {model_id}/{case.case_id}",
            flush=True,
        )
        unrelated_world = 1 - case.world_index
        unrelated_case = lookup[(unrelated_world, case.side, case.query_index)]
        directions: dict[int, dict[str, dict[str, torch.Tensor | None]]] = {}
        metadata: dict[int, dict[str, Any]] = {}
        for horizon in HORIZONS:
            control_pairs, control_metadata = _control_pairs(
                case,
                horizon_states[case.case_id][horizon],
                horizon_states[unrelated_case.case_id][horizon],
                seed=int(plan["random_seed"]) + case_index * 100 + horizon,
            )
            control_metadata["unrelated_family"]["source_case_id"] = unrelated_case.case_id
            control_metadata["unrelated_family"]["source_pair_id"] = unrelated_case.pair_id
            control_metadata["unrelated_family"]["distinct_world_family"] = (
                unrelated_case.pair_id != case.pair_id
            )
            directions[horizon] = control_pairs
            metadata[horizon] = control_metadata

        cache_rows = _run_cache_case(adapter, case, directions, layer=boundary_layer)
        gradient, gradient_receipt = _local_answer_gradient(
            model,
            horizon_states[case.case_id][0],
            case,
            precision=precision,
            boundary_layer=boundary_layer,
        )
        unembedding, target_id, reference_id = _answer_basis(base_model, case)
        case_receipts.append(
            {
                "case_id": case.case_id,
                "world_index": case.world_index,
                "pair_id": case.pair_id,
                "side": case.side,
                "query_index": case.query_index,
                "query_text_sha256": hashlib.sha256(case.query_text.encode()).hexdigest(),
                "affected": case.affected,
                "heldout": case.heldout,
                "hop_distance": case.hop_distance,
                "candidate_ids": list(case.candidate_ids),
                "original_label": case.original_label,
                "donor_label": case.donor_label,
                "query_prefix_sha256": _stable_hash(case.query_prefix),
                "turn_chunk_sha256": _stable_hash(case.turn_chunk),
                "local_answer_gradient": gradient_receipt,
                "raw_unembedding": {
                    "target_token_id": target_id,
                    "reference_token_id": reference_id,
                    "direction": _direction_stats(unembedding),
                    "interpretation": "descriptive_only_before_upper_layers_and_final_rmsnorm",
                },
            }
        )
        for horizon in HORIZONS:
            state = horizon_states[case.case_id][horizon]
            for control in CONTROLS:
                no_cache = _build_no_cache_row(
                    model,
                    case,
                    state,
                    control,
                    directions[horizon][control],
                    input_rmsnorm,
                    precision=precision,
                    boundary_layer=boundary_layer,
                    local_gradient=gradient if horizon == 0 else None,
                    unembedding=unembedding if horizon == 0 else None,
                )
                cache = cache_rows[(control, horizon)]
                rows.append(
                    {
                        "model": model_id,
                        "case_id": case.case_id,
                        "world_index": case.world_index,
                        "pair_id": case.pair_id,
                        "side": case.side,
                        "query_index": case.query_index,
                        "affected": case.affected,
                        "heldout": case.heldout,
                        "hop_distance": case.hop_distance,
                        "horizon": horizon,
                        "history_token_count": len(state.history),
                        "history_sha256": _stable_hash(state.history),
                        "turn_chunk_sha256": _stable_hash(case.turn_chunk),
                        "fixed_tokens_identical_across_cells": True,
                        "control": control,
                        "control_metadata": metadata[horizon][control],
                        "no_cache": no_cache,
                        "cache": cache,
                        "base_no_cache_vs_native_cache_analysis_margin_delta": (
                            float(cache["base"]["analysis_margin"])
                            - float(no_cache["base"]["analysis_margin"])
                        ),
                    }
                )
        del cache_rows, directions, metadata, gradient, unembedding
        torch.cuda.empty_cache()

    parameter_identity_ok = identities == {
        name: (id(parameter), parameter._version, parameter.dtype, parameter.requires_grad)
        for name, parameter in model.named_parameters()
    }
    checkpoint_unchanged = checkpoint_inventory(checkpoint) == inventory_before
    source_unchanged = _source_identity(REPO, plan) == plan["source_identity"]
    eval_unchanged = digest(eval_path) == plan["eval"]["sha256"]
    checks = _model_mechanical_checks(
        rows,
        parameter_identity_ok=parameter_identity_ok,
        checkpoint_unchanged=checkpoint_unchanged,
        source_unchanged=source_unchanged,
        eval_unchanged=eval_unchanged,
        tolerance=float(plan["control_tolerance"]),
    )
    identity = {
        "checkpoint": checkpoint.relative_to(REPO).as_posix(),
        "manifest_sha256": digest(checkpoint / "manifest.json"),
        "workspace_sha256": digest(checkpoint / "workspace_state.pt"),
        "checkpoint_inventory_sha256": _stable_hash(inventory_before),
        "checkpoint_inventory_entries": len(inventory_before),
        "parameter_dtypes": parameter_dtypes,
        "precision": precision,
        "adapter": adapter.describe(),
        "case_prompt_sha256": _stable_hash(
            [
                {
                    "id": case.case_id,
                    "query_prefix": case.query_prefix,
                    "turn_chunk": case.turn_chunk,
                }
                for case in cases
            ]
        ),
        "cases": case_receipts,
        "integrity": {
            "parameter_identity_versions_unchanged": parameter_identity_ok,
            "checkpoint_inventory_unchanged": checkpoint_unchanged,
            "source_identity_unchanged": source_unchanged,
            "eval_unchanged": eval_unchanged,
        },
    }
    del horizon_states, cases, dataset, tokenizer, adapter, base_model, model
    gc.collect()
    torch.cuda.empty_cache()
    return rows, identity, checks


def execute(root: Path, plan_path: Path, *, dry_run: bool) -> dict[str, Any]:
    started = time.monotonic()
    plan = load_json(plan_path)
    paths = validate_plan(
        root,
        plan,
        require_fresh=not dry_run,
        verify_checkpoints=not dry_run,
    )
    report: dict[str, Any] = {
        "format": FORMAT,
        "status": "DRY_RUN" if dry_run else "RUNNING",
        "started_utc": datetime.now(UTC).isoformat(),
        "plan": {
            "path": plan_path.relative_to(root).as_posix(),
            "sha256": digest(plan_path),
        },
        "source_identity": _source_identity(root, plan),
        "runtime": None,
        "gpu_admission": None,
        "model_identities": {},
        "model_mechanical_checks": {},
        "rows": [],
        "training_performed": False,
        "optimizer_constructed": False,
        "free_generation_performed": False,
        "weights_written_or_deleted": False,
        "predecessor_grouped_winner": "none",
    }
    if dry_run:
        return report
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip():
        raise RecurrenceError("Formal execution requires a clean isolated worktree")
    report["runtime"] = _validate_runtime(plan)
    report["gpu_admission"] = _require_idle_gpu()
    first_config = engine.ExperimentConfig.from_json(
        paths["models"][MODEL_ORDER[0]]["path"] / "experiment_config.json"
    )
    engine.require_cuda_allocator_policy(first_config.train)
    engine.configure_runtime_math(first_config.train)
    engine.set_global_seed(int(plan["seed"]))
    torch.set_num_threads(int(plan["cpu_threads"]))
    torch.set_num_interop_threads(int(plan["cpu_threads"]))
    torch.cuda.set_per_process_memory_fraction(float(plan["cuda_allocator_fraction"]))
    torch.cuda.reset_peak_memory_stats()
    atomic_write(paths["output"], report)

    device = engine.resolve_device("cuda")
    for model_id in MODEL_ORDER:
        model_rows, identity, checks = _process_model(
            model_id,
            paths["models"][model_id]["path"],
            paths["eval"],
            plan,
            device=device,
        )
        report["rows"].extend(model_rows)
        report["model_identities"][model_id] = identity
        report["model_mechanical_checks"][model_id] = checks
        report["last_completed_model"] = model_id
        atomic_write(paths["output"], report)

    if len(report["rows"]) != int(plan["expected_rows"]):
        raise RecurrenceError(
            f"Row count mismatch: {len(report['rows'])} != {plan['expected_rows']}"
        )
    prompt_hashes = {
        identity["case_prompt_sha256"] for identity in report["model_identities"].values()
    }
    if len(prompt_hashes) != 1:
        raise RecurrenceError("Tokenized fixed histories differ across model checkpoints")
    all_mechanical = all(
        all(checks.values()) for checks in report["model_mechanical_checks"].values()
    )
    report.update(
        {
            "status": "QUALIFIED_EXECUTION" if all_mechanical else "BLOCKED_EXECUTION",
            "completed_utc": datetime.now(UTC).isoformat(),
            "elapsed_seconds": time.monotonic() - started,
            "row_count": len(report["rows"]),
            "summary": _summarize(report["rows"]),
            "mechanical_execution_qualified": all_mechanical,
            "semantic_effect_qualified": False,
            "winner": "none",
            "cuda_peak_allocated_bytes": int(torch.cuda.max_memory_allocated()),
            "claim_boundary": plan["claim_boundary"],
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
        raise RecurrenceError("Plan must stay inside the repository") from exc
    plan = load_json(plan_path)
    output = resolve_inside(root, plan["output"], label="output")
    if output.exists():
        raise RecurrenceError(f"Output already exists: {output}")
    try:
        report = execute(root, plan_path, dry_run=args.dry_run)
    except BaseException as exc:
        if not args.dry_run:
            prior = load_json(output) if output.is_file() else {"format": FORMAT, "rows": []}
            prior.update(
                {
                    "status": "FAILED",
                    "completed_utc": datetime.now(UTC).isoformat(),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                    "training_performed": False,
                    "free_generation_performed": False,
                    "weights_written_or_deleted": False,
                }
            )
            atomic_write(output, prior)
        raise
    printable = {key: value for key, value in report.items() if key != "rows"}
    print(json.dumps(printable, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
