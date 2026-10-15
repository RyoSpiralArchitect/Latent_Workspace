#!/usr/bin/env python3
"""Separate native BF16 final-head quantization from upper-layer composition."""

from __future__ import annotations

import argparse
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

import run_v14_answer_boundary_recurrence as recurrence  # noqa: E402
import run_v14_position_composition as position  # noqa: E402
from run_v14_boundary_training import (  # noqa: E402
    atomic_write,
    digest,
    load_json,
    resolve_inside,
)
from v13_visibility_trace import checkpoint_inventory  # noqa: E402

from latent_workspace_ft_v10 import engine  # noqa: E402
from latent_workspace_ft_v10.choice_readout import (  # noqa: E402
    MistralChoiceReadoutAdapter,
)

PLAN_PATH = REPO / "configs/v14/READOUT_PRECISION_PLAN.json"
FORMAT = "latent-workspace-v14-readout-precision-v1"
MODEL_ORDER = position.MODEL_ORDER
CONTROLS = position.CONTROLS
HORIZONS = position.HORIZONS
LANES = position.LANES
READOUTS = ("native_bf16_head", "fp32_choice_head")


class PrecisionAssayError(RuntimeError):
    """Raised when the frozen precision assay cannot execute exactly."""


def _source_identity(root: Path, plan: dict[str, Any]) -> dict[str, str]:
    expected = plan.get("source_identity")
    if not isinstance(expected, dict) or not expected:
        raise PrecisionAssayError("Frozen source_identity must be a nonempty mapping")
    observed: dict[str, str] = {}
    for relative in expected:
        path = resolve_inside(root, relative, label="source identity")
        if not path.is_file() or path.is_symlink():
            raise PrecisionAssayError(f"Source identity is not a plain file: {relative}")
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
        "format": "latent-workspace-v14-readout-precision-plan-v1",
        "frozen_before_target_model_scoring": True,
        "model_order": list(MODEL_ORDER),
        "controls": list(CONTROLS),
        "horizons": list(HORIZONS),
        "lanes": list(LANES),
        "readouts": list(READOUTS),
        "expected_cases_per_model": 8,
        "expected_rows": 320,
        "boundary_layer": 16,
        "same_normalized_hidden_for_both_heads": True,
        "free_generation": False,
        "lane_selection_after_scoring": False,
        "semantic_promotion": False,
    }
    mismatches = {
        key: {"observed": plan.get(key), "expected": value}
        for key, value in expected.items()
        if plan.get(key) != value
    }
    expected_actions = {
        "checkpoint_load": True,
        "native_upper_decoder": True,
        "native_full_vocab_head": True,
        "fp32_two_choice_head": True,
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
        raise PrecisionAssayError(f"Frozen plan mismatch: {mismatches}")

    predecessors: dict[str, Path] = {}
    for name, artifact in plan["predecessors"].items():
        path = resolve_inside(root, artifact["path"], label=f"predecessor {name}")
        if not path.is_file() or digest(path) != artifact["sha256"]:
            raise PrecisionAssayError(f"Predecessor changed: {name}")
        predecessors[name] = path
    position_report = load_json(predecessors["position_report"])
    position_summary = load_json(predecessors["position_summary"])
    if (
        position_report.get("status") != "QUALIFIED_EXECUTION"
        or position_report.get("winner") != "none"
        or position_report.get("row_count") != 320
        or position_summary.get("winner") != "none"
        or position_summary.get("semantic_effect_qualified") is not False
    ):
        raise PrecisionAssayError("Position-composition predecessor contract changed")

    eval_path = resolve_inside(root, plan["eval"]["path"], label="eval")
    if not eval_path.is_file() or digest(eval_path) != plan["eval"]["sha256"]:
        raise PrecisionAssayError("Frozen evaluation file changed")
    cases = plan.get("cases")
    if not isinstance(cases, list) or len(cases) != 8:
        raise PrecisionAssayError("Exactly eight frozen cases are required")
    if len({str(case.get("id")) for case in cases}) != 8:
        raise PrecisionAssayError("Frozen case IDs must be unique")
    if sum(bool(case.get("affected")) for case in cases) != 4:
        raise PrecisionAssayError("Exactly four affected cases are required")

    models = plan.get("models")
    if not isinstance(models, list) or [item.get("id") for item in models] != list(MODEL_ORDER):
        raise PrecisionAssayError("Ordered task and semantic checkpoints are required")
    resolved_models: dict[str, dict[str, Any]] = {}
    for model in models:
        checkpoint = resolve_inside(root, model["checkpoint"], label="checkpoint")
        if verify_checkpoints:
            if not (checkpoint / "COMPLETED").is_file():
                raise PrecisionAssayError(f"Incomplete checkpoint: {model['id']}")
            if digest(checkpoint / "manifest.json") != model["manifest_sha256"]:
                raise PrecisionAssayError(f"Checkpoint manifest changed: {model['id']}")
            if digest(checkpoint / "workspace_state.pt") != model["workspace_sha256"]:
                raise PrecisionAssayError(f"Workspace state changed: {model['id']}")
        resolved_models[str(model["id"])] = {**model, "path": checkpoint}

    if _source_identity(root, plan) != plan["source_identity"]:
        raise PrecisionAssayError("Frozen source identity changed")
    output = resolve_inside(root, plan["output"], label="output")
    if require_fresh and output.exists():
        raise PrecisionAssayError(f"Output already exists: {output}")
    return {
        "predecessors": predecessors,
        "position_report": position_report,
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
        raise PrecisionAssayError(
            f"Runtime mismatch: observed={observed}, expected={plan['expected_runtime']}"
        )
    environment = {key: os.environ.get(key) for key in plan["required_environment"]}
    if environment != plan["required_environment"]:
        raise PrecisionAssayError(f"Environment mismatch: {environment}")
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise PrecisionAssayError("Exactly one visible CUDA device is required")
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
        raise PrecisionAssayError("GPU already has compute clients; refusing to interfere")
    return "NO_COMPUTE_CLIENTS_AT_CHECK"


def _choice_readout(
    scores: torch.Tensor,
    candidate_ids: tuple[int, int],
    *,
    original_label: int,
    donor_label: int,
    affected: bool,
) -> dict[str, Any]:
    values = scores.detach().float().reshape(-1)
    if values.numel() != 2 or not bool(torch.isfinite(values).all()):
        raise PrecisionAssayError("FP32 choice readout requires two finite scores")
    choices = [float(values[0].item()), float(values[1].item())]
    prediction = None if choices[0] == choices[1] else int(choices[1] > choices[0])
    alternative_label = 1 - original_label
    original_margin = choices[original_label] - choices[alternative_label]
    if affected:
        if donor_label == original_label:
            raise PrecisionAssayError("Affected choice readout requires a donor label")
        target_label = donor_label
        reference_label = original_label
        target_name = "donor_minus_original"
        donor_margin: float | None = choices[donor_label] - choices[original_label]
    else:
        if donor_label != original_label:
            raise PrecisionAssayError("Unaffected choice readout must preserve the label")
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


@torch.no_grad()
def _decode_both(
    adapter: MistralChoiceReadoutAdapter,
    state: position.PositionState,
    case: recurrence.CaseSpec,
    request: torch.Tensor,
    *,
    precision: str,
    boundary_layer: int,
) -> dict[str, Any]:
    base = state.boundary.detach()
    addition = request.to(device=base.device, dtype=torch.float32).unsqueeze(0)
    modified = (base.float() + addition).to(dtype=base.dtype)
    with engine.autocast_context(modified.device, precision):
        decoded = adapter.decode_choices(
            modified,
            state.attention_mask,
            boundary_layer,
            case.candidate_ids,
        )
    native = recurrence._readout(
        decoded.native_logits,
        case.candidate_ids,
        original_label=case.original_label,
        donor_label=case.donor_label,
        affected=case.affected,
    )
    fp32 = _choice_readout(
        decoded.fp32_choice_scores,
        case.candidate_ids,
        original_label=case.original_label,
        donor_label=case.donor_label,
        affected=case.affected,
    )
    native_choices = [float(value) for value in native["candidate_logits"]]
    fp32_choices = [float(value) for value in fp32["candidate_logits"]]
    return {
        "native_bf16_head": native,
        "fp32_choice_head": fp32,
        "native_logits_dtype": str(decoded.native_logits.dtype),
        "fp32_choice_dtype": str(decoded.fp32_choice_scores.dtype),
        "same_normalized_hidden_for_both_heads": True,
        "normalized_last_hidden": recurrence._direction_stats(decoded.normalized_last_hidden),
        "native_minus_fp32_candidate_scores": [
            native_choices[index] - fp32_choices[index] for index in range(2)
        ],
        "native_minus_fp32_analysis_margin": (
            float(native["analysis_margin"]) - float(fp32["analysis_margin"])
        ),
    }


def _member_pair(
    members: dict[str, dict[str, Any]],
    *,
    affected: bool,
) -> dict[str, Any]:
    output: dict[str, Any] = {
        "intact": members["intact"],
        "twin": members["twin"],
    }
    for readout in READOUTS:
        output[readout] = {
            "signed_pair_effect": recurrence._pair_effect(
                members["intact"][readout],
                members["twin"][readout],
                affected=affected,
            ),
            "prediction_changed": (
                members["intact"][readout]["prediction"] != members["twin"][readout]["prediction"]
            ),
        }
    output["native_minus_fp32_pair_effect"] = (
        output["native_bf16_head"]["signed_pair_effect"]
        - output["fp32_choice_head"]["signed_pair_effect"]
    )
    output["effect_definition"] = (
        "twin_donor_margin_minus_intact_donor_margin"
        if affected
        else "twin_original_margin_minus_intact_original_margin"
    )
    return output


def _position_row_map(report: dict[str, Any]) -> dict[tuple[str, str, str, int], dict[str, Any]]:
    mapping = {
        (
            str(row["model"]),
            str(row["case_id"]),
            str(row["control"]),
            int(row["horizon"]),
        ): row
        for row in report["rows"]
    }
    if len(mapping) != 320:
        raise PrecisionAssayError("Position predecessor row closure changed")
    return mapping


def _build_row(
    adapter: MistralChoiceReadoutAdapter,
    model_id: str,
    case: recurrence.CaseSpec,
    state: position.PositionState,
    control: str,
    pair: dict[str, torch.Tensor | None],
    metadata: dict[str, Any],
    gradient: torch.Tensor,
    predecessor_row: dict[str, Any],
    base_receipt: dict[str, Any],
    *,
    precision: str,
    boundary_layer: int,
) -> dict[str, Any]:
    lanes: dict[str, Any] = {}
    for lane in LANES:
        members: dict[str, dict[str, Any]] = {}
        for member in ("intact", "twin"):
            request, oracle = position._request_for_lane(
                pair[member],
                gradient,
                lane,
                current_query_start=state.current_query_start,
            )
            receipt = _decode_both(
                adapter,
                state,
                case,
                request,
                precision=precision,
                boundary_layer=boundary_layer,
            )
            if oracle is not None:
                receipt["oracle_decomposition"] = oracle
            members[member] = receipt
        lanes[lane] = _member_pair(members, affected=case.affected)

    interactions: dict[str, Any] = {}
    for readout in READOUTS:
        effects = {lane: float(lanes[lane][readout]["signed_pair_effect"]) for lane in LANES}
        interactions[readout] = {
            "boundary_non_boundary": (
                effects["full_route"]
                - effects["answer_boundary_only"]
                - effects["non_boundary_only"]
            ),
            "current_query_prior_history": (
                effects["full_route"]
                - effects["current_query_only"]
                - effects["prior_history_only"]
            ),
            "oracle_axis_orthogonal": (
                effects["full_route"]
                - effects["oracle_global_answer_axis"]
                - effects["oracle_answer_orthogonal"]
            ),
        }
    interactions["native_minus_fp32_boundary_non_boundary"] = (
        interactions["native_bf16_head"]["boundary_non_boundary"]
        - interactions["fp32_choice_head"]["boundary_non_boundary"]
    )

    predecessor_replication = {
        "base_native_readout_exact": (base_receipt["native_bf16_head"] == predecessor_row["base"]),
        "lanes": {
            lane: {
                "effect_exact": (
                    lanes[lane]["native_bf16_head"]["signed_pair_effect"]
                    == predecessor_row["lanes"][lane]["signed_pair_effect"]
                ),
                "intact_readout_exact": (
                    lanes[lane]["intact"]["native_bf16_head"]
                    == predecessor_row["lanes"][lane]["intact"]["readout"]
                ),
                "twin_readout_exact": (
                    lanes[lane]["twin"]["native_bf16_head"]
                    == predecessor_row["lanes"][lane]["twin"]["readout"]
                ),
            }
            for lane in LANES
        },
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
        "history_sha256": recurrence._stable_hash(state.history),
        "current_query_start": state.current_query_start,
        "control": control,
        "control_metadata": metadata,
        "base": base_receipt,
        "lanes": lanes,
        "interactions": interactions,
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
        raise PrecisionAssayError("Summary received a nonfinite value")
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
                            readout: _describe(
                                [
                                    float(row["lanes"][lane][readout]["signed_pair_effect"])
                                    for row in selected
                                ]
                            )
                            for readout in READOUTS
                        }
                        for lane in LANES
                    }

    interactions: dict[str, Any] = {}
    for model_id in MODEL_ORDER:
        interactions[model_id] = {}
        for population, affected in (("affected", True), ("unaffected", False)):
            interactions[model_id][population] = {}
            for horizon in HORIZONS:
                selected = [
                    row
                    for row in rows
                    if row["model"] == model_id
                    and row["control"] == "learned_pair"
                    and row["affected"] is affected
                    and row["horizon"] == horizon
                ]
                interactions[model_id][population][str(horizon)] = {
                    readout: {
                        name: _describe(
                            [float(row["interactions"][readout][name]) for row in selected]
                        )
                        for name in (
                            "boundary_non_boundary",
                            "current_query_prior_history",
                            "oracle_axis_orthogonal",
                        )
                    }
                    for readout in READOUTS
                }
                interactions[model_id][population][str(horizon)][
                    "native_minus_fp32_boundary_non_boundary"
                ] = _describe(
                    [
                        float(row["interactions"]["native_minus_fp32_boundary_non_boundary"])
                        for row in selected
                    ]
                )

    focus = [
        row
        for row in rows
        if row["model"] == "semantic"
        and row["control"] == "learned_pair"
        and row["affected"]
        and row["horizon"] == 4
    ]
    focus_summary = {
        lane: {
            readout: _describe(
                [float(row["lanes"][lane][readout]["signed_pair_effect"]) for row in focus]
            )
            for readout in READOUTS
        }
        for lane in LANES
    }
    focus_summary["boundary_non_boundary_interaction"] = {
        readout: _describe(
            [float(row["interactions"][readout]["boundary_non_boundary"]) for row in focus]
        )
        for readout in READOUTS
    }
    return {
        "signed_pair_effects_by_horizon": by_horizon,
        "learned_composition_interactions": interactions,
        "predeclared_semantic_affected_h4": focus_summary,
        "head_comparison": (
            "Both score paths consume one identical native upper-decoder and final-normalized "
            "hidden state; only the selected lm-head matmul and output dtype differ."
        ),
        "multi_turn_followup_required_regardless_of_result": True,
        "semantic_assessment": "DESCRIPTIVE_PRECISION_LOCALIZATION_NO_PROMOTION_THRESHOLD",
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
        "same_normalized_hidden_feeds_both_heads": all(
            row["base"]["same_normalized_hidden_for_both_heads"]
            and all(
                row["lanes"][lane][member]["same_normalized_hidden_for_both_heads"]
                for lane in LANES
                for member in ("intact", "twin")
            )
            for row in rows
        ),
        "native_dtype_and_fp32_dtype_distinct": all(
            row["base"]["native_logits_dtype"] == "torch.bfloat16"
            and row["base"]["fp32_choice_dtype"] == "torch.float32"
            and all(
                row["lanes"][lane][member]["native_logits_dtype"] == "torch.bfloat16"
                and row["lanes"][lane][member]["fp32_choice_dtype"] == "torch.float32"
                for lane in LANES
                for member in ("intact", "twin")
            )
            for row in rows
        ),
        "native_path_reproduces_position_predecessor_exactly": all(
            row["predecessor_replication"]["base_native_readout_exact"]
            and all(all(row["predecessor_replication"]["lanes"][lane].values()) for lane in LANES)
            for row in rows
        ),
        "sham_exact_noop_in_both_heads": all(
            row["lanes"][lane][readout]["signed_pair_effect"] == 0.0
            for row in sham
            for lane in LANES
            for readout in READOUTS
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
    prior_rows: dict[tuple[str, str, str, int], dict[str, Any]],
    *,
    device: torch.device,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, bool]]:
    inventory_before = checkpoint_inventory(checkpoint)
    model, tokenizer, config = engine.load_bundle(checkpoint, device=device)
    position._validate_model_config(config, plan, model_id)
    precision = engine.resolve_mixed_precision(config.train.mixed_precision, device)
    boundary_layer = int(config.functional.boundary_layer)
    base_model = model.base_model.eval()
    parameter_dtypes = sorted({str(parameter.dtype) for parameter in base_model.parameters()})
    if parameter_dtypes != ["torch.bfloat16"]:
        raise PrecisionAssayError(f"Loaded base parameter dtype changed: {parameter_dtypes}")
    identities = {
        name: (id(parameter), parameter._version, parameter.dtype, parameter.requires_grad)
        for name, parameter in model.named_parameters()
    }
    dataset = engine.JsonlFineTuningDataset([str(eval_path)], tokenizer, config.data)
    cases = recurrence._build_cases(dataset, tokenizer, plan)
    states = position._precompute_states(
        model,
        cases,
        device=device,
        precision=precision,
        boundary_layer=boundary_layer,
    )
    if model.functional_boundary_adapter is None:
        raise PrecisionAssayError("Functional boundary adapter is absent")
    readout_adapter = MistralChoiceReadoutAdapter(model.functional_boundary_adapter)
    lookup = {(case.world_index, case.side, case.query_index): case for case in cases}

    rows: list[dict[str, Any]] = []
    for case_index, case in enumerate(cases):
        unrelated_case = lookup[(1 - case.world_index, case.side, case.query_index)]
        for horizon in HORIZONS:
            state = states[case.case_id][horizon]
            print(f"measure head precision {model_id}/{case.case_id}/h{horizon}", flush=True)
            gradient, _gradient_receipt = position._local_answer_gradient(
                model,
                state,
                case,
                precision=precision,
                boundary_layer=boundary_layer,
            )
            controls, metadata = position._control_pairs(
                state,
                seed=int(plan["random_seed"])
                + (0 if model_id == "task" else 1_000_000)
                + case_index * 100
                + horizon,
                unrelated_case_id=unrelated_case.case_id,
                unrelated_pair_id=unrelated_case.pair_id,
                target_pair_id=case.pair_id,
            )
            base_request = torch.zeros_like(gradient)
            base_receipt = _decode_both(
                readout_adapter,
                state,
                case,
                base_request,
                precision=precision,
                boundary_layer=boundary_layer,
            )
            for control in CONTROLS:
                key = (model_id, case.case_id, control, horizon)
                rows.append(
                    _build_row(
                        readout_adapter,
                        model_id,
                        case,
                        state,
                        control,
                        controls[control],
                        metadata[control],
                        gradient,
                        prior_rows[key],
                        base_receipt,
                        precision=precision,
                        boundary_layer=boundary_layer,
                    )
                )
            del gradient, controls, metadata, base_receipt
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
        "checkpoint_inventory_sha256": recurrence._stable_hash(inventory_before),
        "checkpoint_inventory_entries": len(inventory_before),
        "parameter_dtypes": parameter_dtypes,
        "precision": precision,
        "readout_adapter": readout_adapter.describe(),
        "case_prompt_sha256": recurrence._stable_hash(
            [
                {
                    "id": case.case_id,
                    "query_prefix": case.query_prefix,
                    "turn_chunk": case.turn_chunk,
                }
                for case in cases
            ]
        ),
        "integrity": {
            "parameter_identity_versions_unchanged": parameter_identity_ok,
            "checkpoint_inventory_unchanged": checkpoint_unchanged,
            "source_identity_unchanged": source_unchanged,
            "eval_unchanged": eval_unchanged,
        },
    }
    del states, cases, dataset, tokenizer, readout_adapter, base_model, model
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
        "predecessor_winner": "none",
        "same_normalized_hidden_for_both_heads": True,
    }
    if dry_run:
        return report
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip():
        raise PrecisionAssayError("Formal execution requires a clean isolated worktree")
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

    prior_rows = _position_row_map(paths["position_report"])
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
        raise PrecisionAssayError(
            f"Row count mismatch: {len(report['rows'])} != {plan['expected_rows']}"
        )
    prompt_hashes = {
        identity["case_prompt_sha256"] for identity in report["model_identities"].values()
    }
    if len(prompt_hashes) != 1:
        raise PrecisionAssayError("Tokenized fixed histories differ across checkpoints")
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
        raise PrecisionAssayError("Plan must stay inside the repository") from exc
    plan = load_json(plan_path)
    output = resolve_inside(root, plan["output"], label="output")
    if output.exists():
        raise PrecisionAssayError(f"Output already exists: {output}")
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
