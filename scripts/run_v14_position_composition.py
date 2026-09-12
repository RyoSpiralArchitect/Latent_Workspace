#!/usr/bin/env python3
"""Factor the V14 reader update by token position and local answer axis."""

from __future__ import annotations

import argparse
import dataclasses
import gc
import json
import math
import os
import subprocess
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import torch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import run_v14_answer_boundary_recurrence as predecessor  # noqa: E402
from run_v14_boundary_training import (  # noqa: E402
    atomic_write,
    digest,
    load_json,
    resolve_inside,
)
from v13_visibility_trace import checkpoint_inventory  # noqa: E402

from latent_workspace_ft_v10 import engine  # noqa: E402

PLAN_PATH = REPO / "configs/v14/POSITION_COMPOSITION_PLAN.json"
FORMAT = "latent-workspace-v14-position-composition-v1"
MODEL_ORDER = ("task", "semantic")
CONTROLS = ("learned_pair", "gram_matched_random", "unrelated_family", "sham")
HORIZONS = (0, 1, 2, 3, 4)
LANES = (
    "full_route",
    "answer_boundary_only",
    "non_boundary_only",
    "current_query_only",
    "prior_history_only",
    "oracle_global_answer_axis",
    "oracle_answer_orthogonal",
)


class CompositionError(RuntimeError):
    """Raised when the frozen position-composition assay cannot run exactly."""


@dataclasses.dataclass(slots=True)
class PositionState:
    horizon: int
    history: tuple[int, ...]
    current_query_start: int
    attention_mask: torch.Tensor
    boundary: torch.Tensor
    base_logits: torch.Tensor
    base_readout: dict[str, Any]
    learned_requested: dict[str, torch.Tensor]
    learned_native: dict[str, torch.Tensor]
    learned_full_readouts: dict[str, dict[str, Any]]
    unrelated_requested: dict[str, torch.Tensor]
    reader_receipts: dict[str, dict[str, dict[str, float]]]


def _source_identity(root: Path, plan: dict[str, Any]) -> dict[str, str]:
    expected = plan.get("source_identity")
    if not isinstance(expected, dict) or not expected:
        raise CompositionError("Frozen source_identity must be a nonempty mapping")
    observed: dict[str, str] = {}
    for relative in expected:
        path = resolve_inside(root, relative, label="source identity")
        if not path.is_file() or path.is_symlink():
            raise CompositionError(f"Source identity is not a plain file: {relative}")
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
        "format": "latent-workspace-v14-position-composition-plan-v1",
        "frozen_before_target_model_scoring": True,
        "model_order": list(MODEL_ORDER),
        "controls": list(CONTROLS),
        "horizons": list(HORIZONS),
        "lanes": list(LANES),
        "expected_cases_per_model": 8,
        "expected_rows": 320,
        "boundary_layer": 16,
        "fixed_tokens_across_all_cells": True,
        "free_generation": False,
        "oracle_lanes_eligible_for_architecture_selection": False,
    }
    mismatches = {
        key: {"observed": plan.get(key), "expected": value}
        for key, value in expected.items()
        if plan.get(key) != value
    }
    expected_actions = {
        "checkpoint_load": True,
        "full_sequence_local_answer_gradient": True,
        "position_masked_native_bf16_replay": True,
        "label_aware_oracle_diagnostic": True,
        "optimizer_or_training": False,
        "free_generation": False,
        "model_download": False,
        "weight_write_or_delete": False,
        "layer_case_horizon_threshold_or_lane_selection": False,
        "semantic_promotion": False,
    }
    if plan.get("authorized_actions") != expected_actions:
        mismatches["authorized_actions"] = {
            "observed": plan.get("authorized_actions"),
            "expected": expected_actions,
        }
    if mismatches:
        raise CompositionError(f"Frozen plan mismatch: {mismatches}")

    predecessors: dict[str, Path] = {}
    for name, artifact in plan["predecessors"].items():
        path = resolve_inside(root, artifact["path"], label=f"predecessor {name}")
        if not path.is_file() or digest(path) != artifact["sha256"]:
            raise CompositionError(f"Predecessor changed: {name}")
        predecessors[name] = path
    grouped = load_json(predecessors["grouped_comparison"])
    recurrence = load_json(predecessors["answer_boundary_recurrence"])
    recovery = load_json(predecessors["mechanical_recovery"])
    if grouped.get("winner") != "none":
        raise CompositionError("Position assay requires the frozen no-winner comparison")
    if (
        recurrence.get("winner") != "none"
        or recurrence.get("status") != "BLOCKED_EXECUTION"
        or recurrence.get("row_count") != 320
    ):
        raise CompositionError("Answer-boundary predecessor contract changed")
    if (
        recovery.get("status") != "QUALIFIED_VERIFIER_RECOVERY"
        or recovery.get("recovered_mechanical_execution_qualified") is not True
        or recovery.get("target_model_reexecuted") is not False
        or recovery.get("winner") != "none"
    ):
        raise CompositionError("Mechanical recovery predecessor contract changed")

    eval_path = resolve_inside(root, plan["eval"]["path"], label="eval")
    if not eval_path.is_file() or digest(eval_path) != plan["eval"]["sha256"]:
        raise CompositionError("Frozen evaluation file changed")
    cases = plan.get("cases")
    if not isinstance(cases, list) or len(cases) != 8:
        raise CompositionError("Exactly eight frozen cases are required")
    if len({str(case.get("id")) for case in cases}) != 8:
        raise CompositionError("Frozen case IDs must be unique")
    if sum(bool(case.get("affected")) for case in cases) != 4:
        raise CompositionError("Exactly four affected cases are required")

    models = plan.get("models")
    if not isinstance(models, list) or [item.get("id") for item in models] != list(MODEL_ORDER):
        raise CompositionError("Ordered task and semantic checkpoints are required")
    resolved_models: dict[str, dict[str, Any]] = {}
    for model in models:
        checkpoint = resolve_inside(root, model["checkpoint"], label="checkpoint")
        if verify_checkpoints:
            if not (checkpoint / "COMPLETED").is_file():
                raise CompositionError(f"Incomplete checkpoint: {model['id']}")
            if digest(checkpoint / "manifest.json") != model["manifest_sha256"]:
                raise CompositionError(f"Checkpoint manifest changed: {model['id']}")
            if digest(checkpoint / "workspace_state.pt") != model["workspace_sha256"]:
                raise CompositionError(f"Workspace state changed: {model['id']}")
        resolved_models[str(model["id"])] = {**model, "path": checkpoint}

    observed_source = _source_identity(root, plan)
    if observed_source != plan["source_identity"]:
        raise CompositionError("Frozen source identity changed")
    output = resolve_inside(root, plan["output"], label="output")
    if require_fresh and output.exists():
        raise CompositionError(f"Output already exists: {output}")
    return {
        "predecessors": predecessors,
        "recurrence_report": recurrence,
        "eval": eval_path,
        "models": resolved_models,
        "output": output,
    }


def _runtime() -> dict[str, Any]:
    import transformers

    return {
        "python": ".".join(str(value) for value in sys.version_info[:3]),
        "torch": str(torch.__version__),
        "transformers": str(transformers.__version__),
        "cuda": torch.version.cuda,
    }


def _validate_runtime(plan: dict[str, Any]) -> dict[str, Any]:
    observed = _runtime()
    if observed != plan["expected_runtime"]:
        raise CompositionError(
            f"Runtime mismatch: observed={observed}, expected={plan['expected_runtime']}"
        )
    environment = {key: os.environ.get(key) for key in plan["required_environment"]}
    if environment != plan["required_environment"]:
        raise CompositionError(f"Environment mismatch: {environment}")
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise CompositionError("Exactly one visible CUDA device is required")
    observed["gpu"] = torch.cuda.get_device_name(0)
    observed["environment"] = environment
    return observed


def _require_idle_gpu() -> str:
    result = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        raise CompositionError("GPU already has compute clients; refusing to interfere")
    return "NO_COMPUTE_CLIENTS_AT_CHECK"


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
    if observed != plan["model_contract"]:
        raise CompositionError(f"Model protocol changed for {model_id}: {observed}")


def _positionwise_gram(left: torch.Tensor, right: torch.Tensor) -> dict[str, torch.Tensor]:
    first = left.detach().double().cpu()
    second = right.detach().double().cpu()
    if first.ndim != 2 or first.shape != second.shape:
        raise CompositionError("Positionwise Gram tensors must be shape-matched rank 2")
    aa = torch.sum(first * first, dim=-1)
    bb = torch.sum(second * second, dim=-1)
    ab = torch.sum(first * second, dim=-1)
    if bool((aa <= 0).any() or (bb <= 0).any()):
        raise CompositionError("Positionwise Gram requires nonzero vectors at every token")
    cosine = ab / torch.sqrt(aa * bb)
    return {"aa": aa, "bb": bb, "ab": ab, "cosine": cosine}


def _positionwise_gram_random_pair(
    intact: torch.Tensor,
    twin: torch.Tensor,
    *,
    seed: int,
) -> tuple[torch.Tensor, torch.Tensor, dict[str, Any]]:
    reference = _positionwise_gram(intact, twin)
    rows, width = intact.shape
    generator = torch.Generator(device="cpu").manual_seed(seed)
    q1 = torch.randn((rows, width), generator=generator, dtype=torch.float64)
    q1 = q1 / torch.linalg.vector_norm(q1, dim=-1, keepdim=True)
    q2 = torch.randn((rows, width), generator=generator, dtype=torch.float64)
    q2 = q2 - torch.sum(q2 * q1, dim=-1, keepdim=True) * q1
    q2 = q2 / torch.linalg.vector_norm(q2, dim=-1, keepdim=True)
    norm_a = torch.sqrt(reference["aa"])
    norm_b = torch.sqrt(reference["bb"])
    cosine = reference["cosine"].clamp(-1.0, 1.0)
    sine = torch.sqrt(torch.clamp(1.0 - cosine * cosine, min=0.0))
    random_a = (norm_a[:, None] * q1).float().contiguous()
    random_b = (norm_b[:, None] * (cosine[:, None] * q1 + sine[:, None] * q2)).float().contiguous()
    observed = _positionwise_gram(random_a, random_b)
    aa_relative = (observed["aa"] - reference["aa"]).abs() / reference["aa"]
    bb_relative = (observed["bb"] - reference["bb"]).abs() / reference["bb"]
    cosine_absolute = (observed["cosine"] - reference["cosine"]).abs()
    maximum = float(
        torch.stack([aa_relative.max(), bb_relative.max(), cosine_absolute.max()]).max().item()
    )
    return (
        random_a,
        random_b,
        {
            "seed": seed,
            "positions": rows,
            "width": width,
            "maximum_normalized_gram_error": maximum,
            "aa_relative_max": float(aa_relative.max().item()),
            "bb_relative_max": float(bb_relative.max().item()),
            "cosine_absolute_max": float(cosine_absolute.max().item()),
        },
    )


def _positionwise_rms_match(
    source: torch.Tensor,
    target: torch.Tensor,
) -> tuple[torch.Tensor, dict[str, Any]]:
    value = source.detach().double().cpu()
    reference = target.detach().double().cpu()
    if value.ndim != 2 or value.shape != reference.shape:
        raise CompositionError("Positionwise RMS tensors must be shape matched")
    source_norm = torch.linalg.vector_norm(value, dim=-1)
    target_norm = torch.linalg.vector_norm(reference, dim=-1)
    if bool((source_norm <= 0).any() or (target_norm <= 0).any()):
        raise CompositionError("Positionwise RMS match requires nonzero token vectors")
    matched = (value * (target_norm / source_norm)[:, None]).float().contiguous()
    observed_norm = torch.linalg.vector_norm(matched.double(), dim=-1)
    relative = (observed_norm - target_norm).abs() / target_norm
    return matched, {
        "positions": int(value.shape[0]),
        "maximum_relative_rms_error": float(relative.max().item()),
    }


def _axis_decomposition(
    request: torch.Tensor,
    gradient: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor, dict[str, Any]]:
    value = request.detach().double().cpu()
    basis = gradient.detach().double().cpu()
    if value.shape != basis.shape or value.ndim != 2:
        raise CompositionError("Answer-axis decomposition requires matched rank-2 tensors")
    denominator = torch.sum(basis * basis)
    if not bool(torch.isfinite(denominator)) or float(denominator.item()) <= 0.0:
        raise CompositionError("Answer-axis gradient is zero or nonfinite")
    coefficient = torch.sum(value * basis) / denominator
    axis = (coefficient * basis).float().contiguous()
    residual = (request.detach().float().cpu() - axis).contiguous()
    reconstruction = axis + residual
    error = float((reconstruction - request.detach().float().cpu()).abs().max().item())
    residual_dot = float(torch.sum(residual.double() * basis).item())
    normalization = max(
        float(torch.linalg.vector_norm(residual.double()).item())
        * float(torch.linalg.vector_norm(basis).item()),
        1e-30,
    )
    return (
        axis,
        residual,
        {
            "coefficient": float(coefficient.item()),
            "requested_dot_gradient": float(torch.sum(value * basis).item()),
            "residual_dot_gradient": residual_dot,
            "residual_normalized_orthogonality_error": abs(residual_dot) / normalization,
            "requested_reconstruction_max_abs_error": error,
            "label_aware": True,
            "architecture_selection_eligible": False,
        },
    )


def _lane_mask(
    lane: str,
    *,
    sequence_length: int,
    current_query_start: int,
) -> torch.Tensor:
    if not 0 <= current_query_start < sequence_length:
        raise CompositionError("Current-query boundary lies outside the sequence")
    mask = torch.zeros((sequence_length, 1), dtype=torch.float32)
    if lane == "full_route":
        mask[:] = 1.0
    elif lane == "answer_boundary_only":
        mask[-1] = 1.0
    elif lane == "non_boundary_only":
        mask[:-1] = 1.0
    elif lane == "current_query_only":
        mask[current_query_start:] = 1.0
    elif lane == "prior_history_only":
        mask[:current_query_start] = 1.0
    elif lane not in {"oracle_global_answer_axis", "oracle_answer_orthogonal"}:
        raise CompositionError(f"Unknown position lane: {lane}")
    return mask


@torch.no_grad()
def _precompute_states(
    model: Any,
    cases: list[predecessor.CaseSpec],
    *,
    device: torch.device,
    precision: str,
    boundary_layer: int,
) -> dict[str, list[PositionState]]:
    if model.functional_boundary_adapter is None or model.functional_reader is None:
        raise CompositionError("Functional reader and split decoder are required")
    worlds = sorted({case.world_index for case in cases})
    if worlds != [0, 1]:
        raise CompositionError("The frozen unrelated-family control requires worlds 0 and 1")
    exemplar = {
        world: next(case for case in cases if case.world_index == world) for world in worlds
    }
    memories: dict[tuple[int, int], tuple[torch.Tensor, torch.Tensor]] = {}
    for world in worlds:
        for side in (0, 1):
            memories[(world, side)] = predecessor._context_memory(
                model,
                exemplar[world].contexts[side],
                device=device,
                precision=precision,
                boundary_layer=boundary_layer,
            )

    output: dict[str, list[PositionState]] = {}
    for case_index, case in enumerate(cases):
        print(f"precompute positions {case_index + 1}/{len(cases)} {case.case_id}", flush=True)
        history = case.query_prefix
        states: list[PositionState] = []
        for horizon in HORIZONS:
            ids = torch.tensor([history], device=device, dtype=torch.long)
            attention = torch.ones_like(ids)
            with engine.autocast_context(device, precision):
                boundary = model.functional_boundary_adapter.encode(ids, attention, boundary_layer)
                base_logits_all = model.functional_boundary_adapter.decode(
                    boundary, attention, boundary_layer
                )
            base_logits = base_logits_all[:, -1:].detach()
            base_readout = predecessor._readout(
                base_logits,
                case.candidate_ids,
                original_label=case.original_label,
                donor_label=case.donor_label,
                affected=case.affected,
            )
            learned_requested: dict[str, torch.Tensor] = {}
            learned_native: dict[str, torch.Tensor] = {}
            learned_full_readouts: dict[str, dict[str, Any]] = {}
            unrelated_requested: dict[str, torch.Tensor] = {}
            reader_receipts: dict[str, dict[str, dict[str, float]]] = {
                "learned": {},
                "unrelated": {},
            }
            for family, source_world in (
                ("learned", case.world_index),
                ("unrelated", 1 - case.world_index),
            ):
                for member, source_side in (
                    ("intact", case.side),
                    ("twin", 1 - case.side),
                ):
                    memory, memory_mask = memories[(source_world, source_side)]
                    with engine.autocast_context(device, precision):
                        reader_state = model.functional_reader.read_state(
                            boundary, attention, memory, memory_mask
                        )
                        full_logits_all = (
                            model.functional_boundary_adapter.decode(
                                reader_state.final_state, attention, boundary_layer
                            )
                            if family == "learned"
                            else None
                        )
                    if len(reader_state.per_step_updates) != 1:
                        raise CompositionError("Frozen assay requires exactly one reader step")
                    requested = reader_state.per_step_updates[0][0].detach().float().cpu()
                    native = (
                        reader_state.final_state[0].detach().float().cpu()
                        - reader_state.initial_state[0].detach().float().cpu()
                    )
                    if not bool(torch.isfinite(requested).all() and torch.isfinite(native).all()):
                        raise CompositionError("Reader update became nonfinite")
                    if family == "learned":
                        learned_requested[member] = requested.contiguous()
                        learned_native[member] = native.contiguous()
                        if full_logits_all is None:
                            raise CompositionError("Learned full-route logits were not produced")
                        learned_full_readouts[member] = predecessor._readout(
                            full_logits_all[:, -1:],
                            case.candidate_ids,
                            original_label=case.original_label,
                            donor_label=case.donor_label,
                            affected=case.affected,
                        )
                    else:
                        unrelated_requested[member] = requested.contiguous()
                    reader_receipts[family][member] = {
                        "gate_mean": float(reader_state.gate_mean.detach().float().item()),
                        "read_norm": float(reader_state.read_norm.detach().float().item()),
                    }
            current_query_start = 0 if horizon == 0 else len(history) - (len(case.turn_chunk) - 1)
            if not 0 <= current_query_start < len(history):
                raise CompositionError("Could not locate the current fixed query segment")
            states.append(
                PositionState(
                    horizon=horizon,
                    history=history,
                    current_query_start=current_query_start,
                    attention_mask=attention.detach(),
                    boundary=boundary.detach(),
                    base_logits=base_logits,
                    base_readout=base_readout,
                    learned_requested=learned_requested,
                    learned_native=learned_native,
                    learned_full_readouts=learned_full_readouts,
                    unrelated_requested=unrelated_requested,
                    reader_receipts=reader_receipts,
                )
            )
            del base_logits_all
            history = (*history, *case.turn_chunk)
        output[case.case_id] = states
    return output


def _control_pairs(
    state: PositionState,
    *,
    seed: int,
    unrelated_case_id: str,
    unrelated_pair_id: str,
    target_pair_id: str,
) -> tuple[dict[str, dict[str, torch.Tensor | None]], dict[str, Any]]:
    learned = state.learned_requested
    random_intact, random_twin, random_receipt = _positionwise_gram_random_pair(
        learned["intact"], learned["twin"], seed=seed
    )
    unrelated_intact, unrelated_intact_receipt = _positionwise_rms_match(
        state.unrelated_requested["intact"], learned["intact"]
    )
    unrelated_twin, unrelated_twin_receipt = _positionwise_rms_match(
        state.unrelated_requested["twin"], learned["twin"]
    )
    controls: dict[str, dict[str, torch.Tensor | None]] = {
        "learned_pair": {"intact": learned["intact"], "twin": learned["twin"]},
        "gram_matched_random": {"intact": random_intact, "twin": random_twin},
        "unrelated_family": {
            "intact": unrelated_intact,
            "twin": unrelated_twin,
        },
        "sham": {"intact": None, "twin": None},
    }
    metadata = {
        "learned_pair": {
            "intact": predecessor._direction_stats(learned["intact"]),
            "twin": predecessor._direction_stats(learned["twin"]),
        },
        "gram_matched_random": {
            "intact": predecessor._direction_stats(random_intact),
            "twin": predecessor._direction_stats(random_twin),
            "positionwise_gram_receipt": random_receipt,
        },
        "unrelated_family": {
            "source_case_id": unrelated_case_id,
            "source_pair_id": unrelated_pair_id,
            "target_pair_id": target_pair_id,
            "distinct_world_family": unrelated_pair_id != target_pair_id,
            "same_query_boundary": True,
            "intact": predecessor._direction_stats(unrelated_intact),
            "twin": predecessor._direction_stats(unrelated_twin),
            "positionwise_rms_receipts": {
                "intact": unrelated_intact_receipt,
                "twin": unrelated_twin_receipt,
            },
        },
        "sham": {"pulse": False},
    }
    return controls, metadata


def _local_answer_gradient(
    model: Any,
    state: PositionState,
    case: predecessor.CaseSpec,
    *,
    precision: str,
    boundary_layer: int,
) -> tuple[torch.Tensor, dict[str, Any]]:
    if model.functional_boundary_adapter is None:
        raise CompositionError("Split decoder is absent")
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
        gradient = torch.autograd.grad(margin, probe, retain_graph=False)[0][0]
    gradient = gradient.detach().float().cpu().contiguous()
    if not bool(torch.isfinite(gradient).all()) or predecessor._rms(gradient) <= 0.0:
        raise CompositionError("Full-sequence local answer gradient is zero or nonfinite")
    start = state.current_query_start
    return gradient, {
        "target_token_id": target_id,
        "reference_token_id": reference_id,
        "base_margin": float(margin.detach().item()),
        "gradient": predecessor._direction_stats(gradient),
        "answer_boundary": predecessor._direction_stats(gradient[-1:]),
        "non_boundary": predecessor._direction_stats(gradient[:-1]),
        "current_query": predecessor._direction_stats(gradient[start:]),
        "prior_history": (predecessor._direction_stats(gradient[:start]) if start else None),
    }


def _request_for_lane(
    request: torch.Tensor | None,
    gradient: torch.Tensor,
    lane: str,
    *,
    current_query_start: int,
) -> tuple[torch.Tensor, dict[str, Any] | None]:
    full = torch.zeros_like(gradient) if request is None else request.detach().float().cpu()
    if full.shape != gradient.shape:
        raise CompositionError("Control direction and local gradient shapes differ")
    if lane == "oracle_global_answer_axis":
        axis, _residual, receipt = _axis_decomposition(full, gradient)
        return axis, receipt
    if lane == "oracle_answer_orthogonal":
        _axis, residual, receipt = _axis_decomposition(full, gradient)
        return residual, receipt
    mask = _lane_mask(
        lane,
        sequence_length=int(full.shape[0]),
        current_query_start=current_query_start,
    )
    return (full * mask).contiguous(), None


@torch.no_grad()
def _decode_request(
    model: Any,
    state: PositionState,
    case: predecessor.CaseSpec,
    request: torch.Tensor,
    gradient: torch.Tensor,
    *,
    precision: str,
    boundary_layer: int,
) -> tuple[dict[str, Any], torch.Tensor]:
    if model.functional_boundary_adapter is None:
        raise CompositionError("Split decoder is absent")
    base = state.boundary.detach()
    addition = request.to(device=base.device, dtype=torch.float32).unsqueeze(0)
    modified = (base.float() + addition).to(dtype=base.dtype)
    with engine.autocast_context(modified.device, precision):
        logits_all = model.functional_boundary_adapter.decode(
            modified, state.attention_mask, boundary_layer
        )
    logits = logits_all[:, -1:]
    readout = predecessor._readout(
        logits,
        case.candidate_ids,
        original_label=case.original_label,
        donor_label=case.donor_label,
        affected=case.affected,
    )
    actual = (modified.float() - base.float())[0].cpu().contiguous()
    requested_projection = predecessor._projection(request, gradient)
    native_projection = predecessor._projection(actual, gradient)
    observed_shift = float(readout["analysis_margin"]) - float(
        state.base_readout["analysis_margin"]
    )
    return {
        "readout": readout,
        "full_logit_l2_from_base": predecessor._full_logit_l2(logits, state.base_logits),
        "requested": predecessor._direction_stats(request),
        "actual_native_delta": predecessor._direction_stats(actual),
        "requested_local_gradient": requested_projection,
        "actual_native_local_gradient": native_projection,
        "local_linear_prediction": native_projection["dot"],
        "observed_analysis_margin_shift": observed_shift,
        "observed_minus_local_linear": observed_shift - float(native_projection["dot"]),
    }, actual


def _lane_pair(
    members: dict[str, dict[str, Any]],
    *,
    affected: bool,
) -> dict[str, Any]:
    pair_effect = predecessor._pair_effect(
        members["intact"]["readout"],
        members["twin"]["readout"],
        affected=affected,
    )
    linear = float(members["twin"]["local_linear_prediction"]) - float(
        members["intact"]["local_linear_prediction"]
    )
    return {
        "intact": members["intact"],
        "twin": members["twin"],
        "signed_pair_effect": pair_effect,
        "local_linear_pair_prediction": linear,
        "observed_minus_local_linear_pair": pair_effect - linear,
        "effect_definition": (
            "twin_donor_margin_minus_intact_donor_margin"
            if affected
            else "twin_original_margin_minus_intact_original_margin"
        ),
    }


def _prior_row_map(report: dict[str, Any]) -> dict[tuple[str, str, int], dict[str, Any]]:
    selected = [row for row in report["rows"] if row["control"] == "learned_pair"]
    mapping = {
        (str(row["model"]), str(row["case_id"]), int(row["horizon"])): row for row in selected
    }
    if len(mapping) != 80:
        raise CompositionError("Predecessor learned-pair row closure changed")
    return mapping


def _build_row(
    model: Any,
    model_id: str,
    case: predecessor.CaseSpec,
    state: PositionState,
    control: str,
    pair: dict[str, torch.Tensor | None],
    metadata: dict[str, Any],
    gradient: torch.Tensor,
    gradient_receipt: dict[str, Any],
    prior_row: dict[str, Any] | None,
    *,
    precision: str,
    boundary_layer: int,
) -> dict[str, Any]:
    lanes: dict[str, Any] = {}
    actuals: dict[str, dict[str, torch.Tensor]] = {member: {} for member in ("intact", "twin")}
    oracle_receipts: dict[str, dict[str, Any]] = {member: {} for member in ("intact", "twin")}
    requests: dict[str, dict[str, torch.Tensor]] = {member: {} for member in ("intact", "twin")}
    for lane in LANES:
        member_receipts: dict[str, dict[str, Any]] = {}
        for member in ("intact", "twin"):
            request, oracle = _request_for_lane(
                pair[member],
                gradient,
                lane,
                current_query_start=state.current_query_start,
            )
            receipt, actual = _decode_request(
                model,
                state,
                case,
                request,
                gradient,
                precision=precision,
                boundary_layer=boundary_layer,
            )
            receipt["selected_token_count"] = int(
                torch.count_nonzero(torch.any(request != 0, dim=-1)).item()
            )
            if oracle is not None:
                receipt["oracle_decomposition"] = oracle
                oracle_receipts[member][lane] = oracle
            if control == "learned_pair":
                receipt["reader"] = state.reader_receipts["learned"][member]
            member_receipts[member] = receipt
            actuals[member][lane] = actual
            requests[member][lane] = request
        lanes[lane] = _lane_pair(member_receipts, affected=case.affected)

    member_mechanics: dict[str, Any] = {}
    for member in ("intact", "twin"):
        full = actuals[member]["full_route"]
        boundary_plus_non = (
            actuals[member]["answer_boundary_only"] + actuals[member]["non_boundary_only"]
        )
        current_plus_history = (
            actuals[member]["current_query_only"] + actuals[member]["prior_history_only"]
        )
        axis_plus_residual_requested = (
            requests[member]["oracle_global_answer_axis"]
            + requests[member]["oracle_answer_orthogonal"]
        )
        raw_full = torch.zeros_like(gradient) if pair[member] is None else pair[member]
        native_axis_plus_residual = (
            actuals[member]["oracle_global_answer_axis"]
            + actuals[member]["oracle_answer_orthogonal"]
        )
        mechanics: dict[str, Any] = {
            "full_equals_boundary_plus_non_boundary_native_exact": bool(
                torch.equal(full, boundary_plus_non)
            ),
            "full_equals_current_plus_history_native_exact": bool(
                torch.equal(full, current_plus_history)
            ),
            "oracle_requested_reconstruction_max_abs_error": float(
                (axis_plus_residual_requested - raw_full).abs().max().item()
            ),
            "oracle_native_reconstruction_max_abs_error": float(
                (native_axis_plus_residual - full).abs().max().item()
            ),
            "oracle_residual_normalized_orthogonality_error": oracle_receipts[member][
                "oracle_answer_orthogonal"
            ]["residual_normalized_orthogonality_error"],
        }
        if control == "learned_pair":
            mechanics.update(
                {
                    "full_replays_reader_native_state_exact": bool(
                        torch.equal(full, state.learned_native[member])
                    ),
                    "full_replays_reader_readout_exact": (
                        lanes["full_route"][member]["readout"]
                        == state.learned_full_readouts[member]
                    ),
                }
            )
        member_mechanics[member] = mechanics

    effects = {lane: float(lanes[lane]["signed_pair_effect"]) for lane in LANES}
    linear = {lane: float(lanes[lane]["local_linear_pair_prediction"]) for lane in LANES}
    compositions = {
        "boundary_non_boundary_observed_interaction": (
            effects["full_route"] - effects["answer_boundary_only"] - effects["non_boundary_only"]
        ),
        "boundary_non_boundary_local_linear_reconstruction_error": (
            linear["full_route"] - linear["answer_boundary_only"] - linear["non_boundary_only"]
        ),
        "current_history_observed_interaction": (
            effects["full_route"] - effects["current_query_only"] - effects["prior_history_only"]
        ),
        "current_history_local_linear_reconstruction_error": (
            linear["full_route"] - linear["current_query_only"] - linear["prior_history_only"]
        ),
        "oracle_axis_residual_observed_interaction": (
            effects["full_route"]
            - effects["oracle_global_answer_axis"]
            - effects["oracle_answer_orthogonal"]
        ),
        "boundary_minus_full_effect": (effects["answer_boundary_only"] - effects["full_route"]),
        "positive_boundary_to_negative_full_reversal": bool(
            case.affected and effects["answer_boundary_only"] > 0.0 and effects["full_route"] < 0.0
        ),
    }
    predecessor_replication = None
    if control == "learned_pair":
        if prior_row is None:
            raise CompositionError("Learned row is missing its frozen predecessor")
        expected_boundary = float(
            prior_row["no_cache"]["repeated_last_token"]["signed_pair_effect"]
        )
        expected_full = float(
            prior_row["no_cache"]["repeated_full_route_reference"]["signed_pair_effect"]
        )
        predecessor_replication = {
            "expected_answer_boundary_effect": expected_boundary,
            "observed_answer_boundary_effect": effects["answer_boundary_only"],
            "answer_boundary_effect_exact": effects["answer_boundary_only"] == expected_boundary,
            "expected_full_route_effect": expected_full,
            "observed_full_route_effect": effects["full_route"],
            "full_route_effect_exact": effects["full_route"] == expected_full,
            "base_readout_exact": state.base_readout == prior_row["no_cache"]["base"],
        }
    return {
        "model": model_id,
        "case_id": case.case_id,
        "world_index": case.world_index,
        "pair_id": case.pair_id,
        "side": case.side,
        "query_index": case.query_index,
        "affected": case.affected,
        "heldout": case.heldout,
        "hop_distance": case.hop_distance,
        "horizon": state.horizon,
        "history_token_count": len(state.history),
        "history_sha256": predecessor._stable_hash(state.history),
        "current_query_start": state.current_query_start,
        "current_query_token_count": len(state.history) - state.current_query_start,
        "fixed_tokens_identical_across_cells": True,
        "control": control,
        "control_metadata": metadata,
        "base": state.base_readout,
        "local_answer_gradient": gradient_receipt,
        "lanes": lanes,
        "composition": compositions,
        "member_mechanics": member_mechanics,
        "predecessor_replication": predecessor_replication,
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
        raise CompositionError("Summary received a nonfinite value")
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


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_horizon: dict[str, Any] = {}
    for model_id in MODEL_ORDER:
        by_horizon[model_id] = {}
        for control in CONTROLS:
            by_horizon[model_id][control] = {}
            for population, affected in (("affected", True), ("unaffected", False)):
                by_horizon[model_id][control][population] = {}
                for horizon in HORIZONS:
                    selected = [
                        row
                        for row in rows
                        if row["model"] == model_id
                        and row["control"] == control
                        and row["affected"] is affected
                        and row["horizon"] == horizon
                    ]
                    by_horizon[model_id][control][population][str(horizon)] = {
                        lane: {
                            "observed_signed_pair_effect": _describe(
                                [
                                    float(row["lanes"][lane]["signed_pair_effect"])
                                    for row in selected
                                ]
                            ),
                            "local_linear_pair_prediction": _describe(
                                [
                                    float(row["lanes"][lane]["local_linear_pair_prediction"])
                                    for row in selected
                                ]
                            ),
                        }
                        for lane in LANES
                    }

    affected_auc: dict[str, Any] = {}
    for model_id in MODEL_ORDER:
        affected_auc[model_id] = {}
        for control in CONTROLS:
            affected_auc[model_id][control] = {}
            case_ids = sorted(
                {
                    row["case_id"]
                    for row in rows
                    if row["model"] == model_id and row["control"] == control and row["affected"]
                }
            )
            for lane in LANES:
                auc_values: list[float] = []
                endpoint_values: list[float] = []
                for case_id in case_ids:
                    trajectory = sorted(
                        [
                            row
                            for row in rows
                            if row["model"] == model_id
                            and row["control"] == control
                            and row["case_id"] == case_id
                        ],
                        key=lambda row: row["horizon"],
                    )
                    if [row["horizon"] for row in trajectory] != list(HORIZONS):
                        raise CompositionError("Affected trajectory lost a horizon")
                    values = [float(row["lanes"][lane]["signed_pair_effect"]) for row in trajectory]
                    auc_values.append(
                        sum((values[index] + values[index + 1]) / 2 for index in range(4))
                    )
                    endpoint_values.append(values[-1])
                affected_auc[model_id][control][lane] = {
                    "endpoint_h4": _describe(endpoint_values),
                    "trapezoid_auc_h0_h4": _describe(auc_values),
                }

    composition: dict[str, Any] = {}
    for model_id in MODEL_ORDER:
        composition[model_id] = {}
        for population, affected in (("affected", True), ("unaffected", False)):
            composition[model_id][population] = {}
            for horizon in HORIZONS:
                selected = [
                    row
                    for row in rows
                    if row["model"] == model_id
                    and row["control"] == "learned_pair"
                    and row["affected"] is affected
                    and row["horizon"] == horizon
                ]
                composition[model_id][population][str(horizon)] = {
                    key: _describe([float(row["composition"][key]) for row in selected])
                    for key in (
                        "boundary_non_boundary_observed_interaction",
                        "boundary_non_boundary_local_linear_reconstruction_error",
                        "current_history_observed_interaction",
                        "current_history_local_linear_reconstruction_error",
                        "oracle_axis_residual_observed_interaction",
                        "boundary_minus_full_effect",
                    )
                }
                composition[model_id][population][str(horizon)][
                    "positive_boundary_to_negative_full_reversal_count"
                ] = sum(
                    bool(row["composition"]["positive_boundary_to_negative_full_reversal"])
                    for row in selected
                )

    focus = [
        row
        for row in rows
        if row["model"] == "semantic"
        and row["control"] == "learned_pair"
        and row["affected"]
        and row["horizon"] == 4
    ]
    return {
        "signed_effects_and_local_linear_predictions_by_horizon": by_horizon,
        "affected_endpoint_and_auc": affected_auc,
        "learned_position_composition": composition,
        "predeclared_predecessor_focus_semantic_affected_h4": {
            lane: _describe([float(row["lanes"][lane]["signed_pair_effect"]) for row in focus])
            for lane in LANES
        },
        "focus_is_predecessor_informed_diagnostic_not_independent_confirmation": True,
        "oracle_lanes": {
            "label_aware": True,
            "architecture_selection_eligible": False,
            "purpose": (
                "diagnose whether the local answer-axis component survives native "
                "upper-layer readout"
            ),
        },
        "semantic_assessment": "DESCRIPTIVE_POSITION_COMPOSITION_NO_PROMOTION_THRESHOLD",
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
        "sham_is_exact_noop_in_every_lane": all(
            row["lanes"][lane][member]["full_logit_l2_from_base"] == 0.0
            and row["lanes"][lane]["signed_pair_effect"] == 0.0
            for row in sham
            for lane in LANES
            for member in ("intact", "twin")
        ),
        "learned_full_route_replays_reader_exactly": all(
            row["member_mechanics"][member]["full_replays_reader_native_state_exact"]
            and row["member_mechanics"][member]["full_replays_reader_readout_exact"]
            for row in learned
            for member in ("intact", "twin")
        ),
        "learned_boundary_and_full_effects_replicate_predecessor_exactly": all(
            row["predecessor_replication"]["answer_boundary_effect_exact"]
            and row["predecessor_replication"]["full_route_effect_exact"]
            and row["predecessor_replication"]["base_readout_exact"]
            for row in learned
        ),
        "disjoint_position_native_reconstruction_exact": all(
            row["member_mechanics"][member]["full_equals_boundary_plus_non_boundary_native_exact"]
            and row["member_mechanics"][member]["full_equals_current_plus_history_native_exact"]
            for row in rows
            for member in ("intact", "twin")
        ),
        "oracle_requested_reconstruction_within_tolerance": all(
            row["member_mechanics"][member]["oracle_requested_reconstruction_max_abs_error"]
            <= tolerance
            and row["member_mechanics"][member]["oracle_residual_normalized_orthogonality_error"]
            <= tolerance
            for row in rows
            for member in ("intact", "twin")
        ),
        "positionwise_random_gram_within_tolerance": all(
            row["control_metadata"]["positionwise_gram_receipt"]["maximum_normalized_gram_error"]
            <= tolerance
            for row in random
        ),
        "unrelated_family_distinct_and_positionwise_rms_matched": all(
            row["control_metadata"]["distinct_world_family"]
            and row["control_metadata"]["same_query_boundary"]
            and all(
                row["control_metadata"]["positionwise_rms_receipts"][member][
                    "maximum_relative_rms_error"
                ]
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
    prior_rows: dict[tuple[str, str, int], dict[str, Any]],
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
        raise CompositionError(f"Loaded base parameter dtype changed: {parameter_dtypes}")
    identities = {
        name: (id(parameter), parameter._version, parameter.dtype, parameter.requires_grad)
        for name, parameter in model.named_parameters()
    }
    dataset = engine.JsonlFineTuningDataset([str(eval_path)], tokenizer, config.data)
    cases = predecessor._build_cases(dataset, tokenizer, plan)
    states = _precompute_states(
        model,
        cases,
        device=device,
        precision=precision,
        boundary_layer=boundary_layer,
    )
    lookup = {(case.world_index, case.side, case.query_index): case for case in cases}

    rows: list[dict[str, Any]] = []
    case_receipts: list[dict[str, Any]] = []
    for case_index, case in enumerate(cases):
        unrelated_case = lookup[(1 - case.world_index, case.side, case.query_index)]
        case_receipts.append(
            {
                "case_id": case.case_id,
                "world_index": case.world_index,
                "pair_id": case.pair_id,
                "side": case.side,
                "query_index": case.query_index,
                "affected": case.affected,
                "heldout": case.heldout,
                "hop_distance": case.hop_distance,
                "candidate_ids": list(case.candidate_ids),
                "original_label": case.original_label,
                "donor_label": case.donor_label,
                "query_prefix_sha256": predecessor._stable_hash(case.query_prefix),
                "turn_chunk_sha256": predecessor._stable_hash(case.turn_chunk),
                "unrelated_case_id": unrelated_case.case_id,
                "unrelated_pair_id": unrelated_case.pair_id,
            }
        )
        for horizon in HORIZONS:
            state = states[case.case_id][horizon]
            print(
                f"measure composition {model_id}/{case.case_id}/h{horizon}",
                flush=True,
            )
            gradient, gradient_receipt = _local_answer_gradient(
                model,
                state,
                case,
                precision=precision,
                boundary_layer=boundary_layer,
            )
            controls, metadata = _control_pairs(
                state,
                seed=int(plan["random_seed"])
                + (0 if model_id == "task" else 1_000_000)
                + case_index * 100
                + horizon,
                unrelated_case_id=unrelated_case.case_id,
                unrelated_pair_id=unrelated_case.pair_id,
                target_pair_id=case.pair_id,
            )
            for control in CONTROLS:
                rows.append(
                    _build_row(
                        model,
                        model_id,
                        case,
                        state,
                        control,
                        controls[control],
                        metadata[control],
                        gradient,
                        gradient_receipt,
                        prior_rows.get((model_id, case.case_id, horizon))
                        if control == "learned_pair"
                        else None,
                        precision=precision,
                        boundary_layer=boundary_layer,
                    )
                )
            del gradient, controls, metadata
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
        "checkpoint_inventory_sha256": predecessor._stable_hash(inventory_before),
        "checkpoint_inventory_entries": len(inventory_before),
        "parameter_dtypes": parameter_dtypes,
        "precision": precision,
        "case_prompt_sha256": predecessor._stable_hash(
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
    del states, cases, dataset, tokenizer, base_model, model
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
        "oracle_lanes_architecture_selection_eligible": False,
    }
    if dry_run:
        return report
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip():
        raise CompositionError("Formal execution requires a clean isolated worktree")
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

    prior_rows = _prior_row_map(paths["recurrence_report"])
    device = engine.resolve_device("cuda")
    for model_id in MODEL_ORDER:
        model_rows, identity, checks = _process_model(
            model_id,
            paths["models"][model_id]["path"],
            paths["eval"],
            plan,
            prior_rows,
            device=device,
        )
        report["rows"].extend(model_rows)
        report["model_identities"][model_id] = identity
        report["model_mechanical_checks"][model_id] = checks
        report["last_completed_model"] = model_id
        atomic_write(paths["output"], report)

    if len(report["rows"]) != int(plan["expected_rows"]):
        raise CompositionError(
            f"Row count mismatch: {len(report['rows'])} != {plan['expected_rows']}"
        )
    prompt_hashes = {
        identity["case_prompt_sha256"] for identity in report["model_identities"].values()
    }
    if len(prompt_hashes) != 1:
        raise CompositionError("Tokenized fixed histories differ across checkpoints")
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
        raise CompositionError("Plan must stay inside the repository") from exc
    plan = load_json(plan_path)
    output = resolve_inside(root, plan["output"], label="output")
    if output.exists():
        raise CompositionError(f"Output already exists: {output}")
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
