#!/usr/bin/env python3
"""Run a controlled five-cell trajectory with checkpoint-derived directions."""

from __future__ import annotations

import argparse
import dataclasses
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

from run_v14_checkpoint_direction_gate import (  # noqa: E402
    _candidate_readout,
    _compact_difference,
    _digest,
    _direction_stats,
    _jsonable,
    _pulse_step,
    _require_idle_gpu,
    _runtime,
    _stable_hash,
)
from v13_visibility_trace import capture_loaded_batch, checkpoint_inventory  # noqa: E402

from latent_workspace_ft_v10 import engine  # noqa: E402
from latent_workspace_ft_v10.cache_binding import (  # noqa: E402
    MistralDynamicCacheAdapter,
)

PLAN_PATH = REPO / "configs/v14/SEMANTIC_TRAJECTORY_PLAN.json"
CELLS = ("A", "B", "C", "D", "E")
CONTROLS = ("semantic", "sham", "gram_matched_random", "unrelated_family")


class TrajectoryError(RuntimeError):
    """Raised when the frozen trajectory contract cannot be executed."""


@dataclasses.dataclass(frozen=True)
class CapturedCase:
    case_id: str
    world_index: int
    pair_id: str
    side: int
    query_index: int
    query_text: str
    affected: bool
    heldout: bool
    hop_distance: int
    source_position: int
    prefix_ids: tuple[int, ...]
    candidate_ids: tuple[int, int]
    original_label: int
    donor_label: int
    intact: torch.Tensor
    twin: torch.Tensor


def _source_identity(plan: dict[str, Any]) -> dict[str, str]:
    expected = plan.get("source_identity")
    if not isinstance(expected, dict) or not expected:
        raise TrajectoryError("Frozen source identity must be a nonempty mapping")
    observed: dict[str, str] = {}
    for relative in expected:
        path = REPO / relative
        if not path.is_file() or path.is_symlink():
            raise TrajectoryError(f"Source identity target is not a regular file: {relative}")
        observed[relative] = _digest(path)
    return observed


def _validate_plan(plan: dict[str, Any]) -> None:
    expected = {
        "format": "latent-workspace-v14-semantic-trajectory-plan-v1",
        "frozen_before_target_model_scoring": True,
        "input_lane": "retained_inline_checkpoint_compatibility",
        "max_worlds": 2,
        "selected_query_indices": [0, 1, 2, 3],
        "expected_cases": 16,
        "turn_count": 5,
        "expected_trajectory_rows": 320,
        "cells": list(CELLS),
        "controls": list(CONTROLS),
    }
    mismatches = {
        key: {"observed": plan.get(key), "expected": value}
        for key, value in expected.items()
        if plan.get(key) != value
    }
    turn = plan.get("fixed_turn", {})
    turn_expected = {
        "force_original_answer_token": True,
        "repeat_same_query": True,
        "separator": "\n",
        "one_cached_call_per_turn_chunk": True,
        "identical_tokens_across_cells": True,
        "free_generation": False,
    }
    if turn != turn_expected:
        mismatches["fixed_turn"] = {"observed": turn, "expected": turn_expected}
    pulse = plan.get("pulse", {})
    pulse_expected = {
        "layer": 16,
        "boundary": "decoder_layer_input_pre_rmsnorm",
        "composition_dtype": "fp32_add_then_cast_to_hidden",
        "semantic_amplitude": "natural_vector_rms_no_gain",
        "random_control": "preserve_intact_twin_gram_matrix",
        "unrelated_control": "other_world_same_side_query_scaled_to_target_rms",
    }
    for key, value in pulse_expected.items():
        if pulse.get(key) != value:
            mismatches[f"pulse.{key}"] = {"observed": pulse.get(key), "expected": value}
    authorized = {
        "checkpoint_load": True,
        "checkpoint_direction_capture": True,
        "fixed_teacher_forced_cache_trajectory": True,
        "optimizer_or_training": False,
        "free_generation": False,
        "model_download": False,
        "weight_write_or_delete": False,
        "gain_layer_query_or_horizon_selection": False,
        "semantic_promotion": False,
    }
    if plan.get("authorized_actions") != authorized:
        mismatches["authorized_actions"] = {
            "observed": plan.get("authorized_actions"),
            "expected": authorized,
        }
    if mismatches:
        raise TrajectoryError(f"Frozen plan contract mismatch: {mismatches}")


def _scale_to_rms(vector: torch.Tensor, target_rms: float) -> torch.Tensor:
    value = vector.detach().double().cpu().contiguous()
    observed = torch.sqrt(torch.mean(value * value))
    if (
        not bool(torch.isfinite(value).all())
        or not bool(torch.isfinite(observed))
        or float(observed.item()) == 0.0
        or not math.isfinite(target_rms)
        or target_rms <= 0.0
    ):
        raise TrajectoryError("Cannot RMS-match a zero or nonfinite direction")
    return (value * (target_rms / float(observed.item()))).float()


def _gram(value_a: torch.Tensor, value_b: torch.Tensor) -> dict[str, float]:
    a = value_a.detach().double().cpu().flatten()
    b = value_b.detach().double().cpu().flatten()
    aa = float(torch.dot(a, a).item())
    bb = float(torch.dot(b, b).item())
    ab = float(torch.dot(a, b).item())
    if aa <= 0.0 or bb <= 0.0 or not all(math.isfinite(x) for x in (aa, bb, ab)):
        raise TrajectoryError("Gram matrix requires finite nonzero vectors")
    return {
        "aa": aa,
        "bb": bb,
        "ab": ab,
        "cosine": ab / math.sqrt(aa * bb),
    }


def _gram_error(reference: dict[str, float], observed: dict[str, float]) -> dict[str, float]:
    values = {
        key: abs(observed[key] - reference[key]) / max(abs(reference[key]), 1e-12)
        for key in ("aa", "bb", "ab")
    }
    values["cosine_absolute"] = abs(observed["cosine"] - reference["cosine"])
    values["maximum"] = max(values.values())
    return values


def _gram_matched_random_pair(
    intact: torch.Tensor,
    twin: torch.Tensor,
    *,
    seed: int,
) -> tuple[torch.Tensor, torch.Tensor, dict[str, Any]]:
    reference = _gram(intact, twin)
    width = intact.numel()
    if twin.numel() != width or width < 2:
        raise TrajectoryError("Gram-matched control requires equal vector widths >= 2")
    generator = torch.Generator(device="cpu").manual_seed(seed)
    q1 = torch.randn(width, generator=generator, dtype=torch.float64)
    q1 = q1 / torch.linalg.vector_norm(q1)
    q2 = torch.randn(width, generator=generator, dtype=torch.float64)
    q2 = q2 - torch.dot(q2, q1) * q1
    q2_norm = torch.linalg.vector_norm(q2)
    if not bool(torch.isfinite(q2_norm)) or float(q2_norm.item()) == 0.0:
        raise TrajectoryError("Deterministic random basis became degenerate")
    q2 = q2 / q2_norm
    norm_a = math.sqrt(reference["aa"])
    norm_b = math.sqrt(reference["bb"])
    cosine = max(-1.0, min(1.0, reference["cosine"]))
    sine = math.sqrt(max(0.0, 1.0 - cosine * cosine))
    random_a = (norm_a * q1).float()
    random_b = (norm_b * (cosine * q1 + sine * q2)).float()
    observed = _gram(random_a, random_b)
    return (
        random_a,
        random_b,
        {
            "seed": seed,
            "reference": reference,
            "observed": observed,
            "relative_error": _gram_error(reference, observed),
        },
    )


def _extend_fixed_chunk(
    adapter: MistralDynamicCacheAdapter,
    cache: Any,
    token_ids: tuple[int, ...],
) -> Any:
    if not token_ids:
        raise TrajectoryError("Fixed turn chunk must contain at least one token")
    past_length = adapter._cache_length(cache)
    device = next(adapter.model.parameters()).device
    tokens = torch.tensor([token_ids], device=device, dtype=torch.long)
    positions = torch.arange(
        past_length, past_length + len(token_ids), device=device, dtype=torch.long
    )[None, :]
    mask = torch.ones((1, past_length + len(token_ids)), device=device, dtype=torch.long)
    adapter._validate_forward_inputs(
        tokens, mask, positions, past_length=past_length, one_token=False
    )
    return adapter._forward(
        input_ids=tokens,
        attention_mask=mask,
        position_ids=positions,
        cache=cache,
        pulse=None,
        clone_cache=True,
    )


def _full_logit_l2(left: torch.Tensor, right: torch.Tensor) -> float:
    delta = left.detach().float() - right.detach().float()
    if left.shape != right.shape or not bool(torch.isfinite(delta).all()):
        raise TrajectoryError("Full-logit displacement must be finite and shape matched")
    return float(torch.linalg.vector_norm(delta).item())


def _cell_receipt(
    result: Any,
    base: Any,
    adapter: MistralDynamicCacheAdapter,
    candidate_ids: tuple[int, int],
    *,
    original_label: int,
    donor_label: int,
    inherited_logits: torch.Tensor | None = None,
) -> dict[str, Any]:
    logits = result.logits if inherited_logits is None else inherited_logits
    return {
        "readout": _candidate_readout(
            logits,
            list(candidate_ids),
            original_label=original_label,
            donor_label=donor_label,
        ),
        "full_logit_l2_from_A": _full_logit_l2(logits, base.logits),
        "cache_from_A": _compact_difference(adapter.difference(base.cache, result.cache)),
    }


def _trajectory_row(
    case: CapturedCase,
    control: str,
    horizon: int,
    results: dict[str, Any],
    adapter: MistralDynamicCacheAdapter,
    *,
    inherited: dict[str, torch.Tensor] | None = None,
    history_ids: tuple[int, ...],
    chunk_ids: tuple[int, ...],
) -> dict[str, Any]:
    base = results["A"]
    cells = {
        name: _cell_receipt(
            results[name],
            base,
            adapter,
            case.candidate_ids,
            original_label=case.original_label,
            donor_label=case.donor_label,
            inherited_logits=None if inherited is None else inherited.get(name),
        )
        for name in CELLS
    }
    affected = case.donor_label != case.original_label
    if affected:
        margins = {name: cells[name]["readout"]["donor_margin"] for name in CELLS}
        central = (margins["C"] - margins["B"]) - (margins["E"] - margins["D"])
    else:
        margins = None
        central = None
    return {
        "case_id": case.case_id,
        "world_index": case.world_index,
        "pair_id": case.pair_id,
        "side": case.side,
        "query_index": case.query_index,
        "affected": case.affected,
        "heldout": case.heldout,
        "hop_distance": case.hop_distance,
        "control": control,
        "horizon": horizon,
        "history_length": len(history_ids),
        "history_sha256": _stable_hash(history_ids),
        "fixed_turn_chunk_sha256": _stable_hash(chunk_ids),
        "fixed_tokens_identical_across_cells": True,
        "cells": cells,
        "donor_margins": margins,
        "central_cache_mediated_donor_contrast": central,
        "measurement_definition": (
            "(C_donor_margin-B_donor_margin)-(E_donor_margin-D_donor_margin); "
            "undefined for unaffected rows"
        ),
    }


def _capture_cases(
    model: Any,
    tokenizer: Any,
    config: Any,
    eval_path: Path,
    plan: dict[str, Any],
    device: torch.device,
    precision: str,
) -> list[CapturedCase]:
    dataset = engine.JsonlFineTuningDataset([str(eval_path)], tokenizer, config.data)
    if len(dataset) < plan["max_worlds"]:
        raise TrajectoryError("Evaluation dataset contains too few complete worlds")
    collator = engine.CausalFineTuningCollator(
        int(tokenizer.pad_token_id), config.data.pad_to_multiple_of
    )
    selected = set(plan["selected_query_indices"])
    cases: list[CapturedCase] = []
    for world_index in range(plan["max_worlds"]):
        print(f"capture trajectory directions {world_index + 1}/{plan['max_worlds']}", flush=True)
        cpu_batch = collator([dataset[world_index]])
        batch = engine.move_batch_to_device(cpu_batch, device)
        captured = capture_loaded_batch(
            model,
            batch,
            modes=("intact", "counterfactual_twin"),
            gains=(1.0,),
            precision=precision,
            raw_query_limit=0,
            seed=plan["seed"],
        )
        source_record = dataset._read_record(dataset.locations[world_index])
        metadata = source_record.get("metadata", {})
        pair_id = str(metadata.get("pair_id", metadata.get("world_pair_id", world_index)))
        flat = captured["flat"]
        intact = captured["captures"]["intact"]["tensors"]["adapter.actual_recovered_delta.answer"]
        twin = captured["captures"]["counterfactual_twin"]["tensors"][
            "adapter.actual_recovered_delta.answer"
        ]
        for row_index in range(len(intact)):
            query_index = int(flat["query_indices"][row_index])
            if query_index not in selected:
                continue
            side = int(flat["side_indices"][row_index])
            source_position = int(captured["positions"][row_index])
            original_label = int(flat["answer_classes"][row_index])
            candidate_ids = tuple(int(value) for value in flat["candidate_ids"][row_index])
            if len(candidate_ids) != 2 or candidate_ids[0] == candidate_ids[1]:
                raise TrajectoryError("Expected two distinct candidate IDs")
            next_position = source_position + 1
            if (
                source_position < 1
                or next_position >= flat["input_ids"].shape[1]
                or int(flat["attention_mask"][row_index, source_position]) != 1
                or int(flat["input_ids"][row_index, next_position]) != candidate_ids[original_label]
            ):
                raise TrajectoryError("Supervised answer token does not follow source position")
            prefix_ids = tuple(
                int(value) for value in flat["input_ids"][row_index, : source_position + 1].tolist()
            )
            donor_label = int(cpu_batch["functional_answer_classes"][0, 1 - side, query_index])
            affected = bool(flat["affected"][row_index])
            if affected != (donor_label != original_label):
                raise TrajectoryError("Affected flag disagrees with paired donor label")
            cases.append(
                CapturedCase(
                    case_id=f"{pair_id}:side{side}:query{query_index}",
                    world_index=world_index,
                    pair_id=pair_id,
                    side=side,
                    query_index=query_index,
                    query_text=str(source_record["queries"][query_index]),
                    affected=affected,
                    heldout=bool(flat["heldout"][row_index]),
                    hop_distance=int(flat["hop_distances"][row_index]),
                    source_position=source_position,
                    prefix_ids=prefix_ids,
                    candidate_ids=(candidate_ids[0], candidate_ids[1]),
                    original_label=original_label,
                    donor_label=donor_label,
                    intact=intact[row_index].float().cpu().contiguous(),
                    twin=twin[row_index].float().cpu().contiguous(),
                )
            )
        del captured, batch, cpu_batch
    if len(cases) != plan["expected_cases"] or len({case.case_id for case in cases}) != len(cases):
        raise TrajectoryError("Frozen case selection is incomplete or duplicated")
    affected_count = sum(case.affected for case in cases)
    if affected_count != plan["expected_affected_cases"]:
        raise TrajectoryError("Frozen affected/unaffected balance changed")
    return cases


def _control_directions(
    case: CapturedCase,
    unrelated: CapturedCase,
    plan: dict[str, Any],
    case_index: int,
) -> tuple[dict[str, tuple[torch.Tensor | None, torch.Tensor | None]], dict[str, Any]]:
    intact_rms = _direction_stats(case.intact)["rms"]
    twin_rms = _direction_stats(case.twin)["rms"]
    random_intact, random_twin, random_receipt = _gram_matched_random_pair(
        case.intact,
        case.twin,
        seed=plan["pulse"]["random_seed"] + case_index,
    )
    unrelated_intact = _scale_to_rms(unrelated.intact, intact_rms)
    unrelated_twin = _scale_to_rms(unrelated.twin, twin_rms)
    controls = {
        "semantic": (case.intact, case.twin),
        "sham": (None, None),
        "gram_matched_random": (random_intact, random_twin),
        "unrelated_family": (unrelated_intact, unrelated_twin),
    }
    metadata = {
        "semantic": {
            "source_pair_id": case.pair_id,
            "intact": _direction_stats(case.intact),
            "twin": _direction_stats(case.twin),
            "gram": _gram(case.intact, case.twin),
        },
        "sham": {"pulse": False},
        "gram_matched_random": {
            "intact": _direction_stats(random_intact),
            "twin": _direction_stats(random_twin),
            "gram_receipt": random_receipt,
        },
        "unrelated_family": {
            "source_case_id": unrelated.case_id,
            "source_pair_id": unrelated.pair_id,
            "distinct_family": unrelated.pair_id != case.pair_id,
            "intact": _direction_stats(unrelated_intact),
            "twin": _direction_stats(unrelated_twin),
            "target_rms": {"intact": intact_rms, "twin": twin_rms},
        },
    }
    return controls, metadata


def _summarize(rows: list[dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any]:
    affected_rows = [row for row in rows if row["affected"]]
    grouped: dict[tuple[str, int], list[float]] = defaultdict(list)
    for row in affected_rows:
        value = row["central_cache_mediated_donor_contrast"]
        if value is None or not math.isfinite(float(value)):
            raise TrajectoryError("Affected central contrast is missing or nonfinite")
        grouped[(row["control"], row["horizon"])].append(float(value))
    by_control_horizon: dict[str, dict[str, Any]] = {}
    for control in CONTROLS:
        by_control_horizon[control] = {}
        for horizon in range(plan["turn_count"]):
            values = grouped[(control, horizon)]
            by_control_horizon[control][str(horizon)] = {
                "count": len(values),
                "mean": sum(values) / len(values),
                "positive": sum(value > 0.0 for value in values),
                "zero": sum(value == 0.0 for value in values),
                "negative": sum(value < 0.0 for value in values),
                "minimum": min(values),
                "maximum": max(values),
            }
    per_case: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in affected_rows:
        per_case[row["case_id"]][row["control"]].append(
            float(row["central_cache_mediated_donor_contrast"])
        )
    auc_by_control: dict[str, dict[str, Any]] = {}
    for control in CONTROLS:
        values = []
        endpoints = []
        for case_id in sorted(per_case):
            trajectory = per_case[case_id][control]
            if len(trajectory) != plan["turn_count"]:
                raise TrajectoryError("Affected trajectory has a missing horizon")
            auc = sum(
                0.5 * (trajectory[index] + trajectory[index + 1])
                for index in range(len(trajectory) - 1)
            )
            values.append(auc)
            endpoints.append(trajectory[-1])
        auc_by_control[control] = {
            "count": len(values),
            "mean_trapezoid_auc": sum(values) / len(values),
            "positive_auc": sum(value > 0.0 for value in values),
            "zero_auc": sum(value == 0.0 for value in values),
            "negative_auc": sum(value < 0.0 for value in values),
            "mean_endpoint": sum(endpoints) / len(endpoints),
            "positive_endpoint": sum(value > 0.0 for value in endpoints),
            "zero_endpoint": sum(value == 0.0 for value in endpoints),
            "negative_endpoint": sum(value < 0.0 for value in endpoints),
        }
    unaffected_rows = [row for row in rows if not row["affected"]]
    unaffected_agreement: dict[str, Any] = {}
    for control in CONTROLS:
        selected = [row for row in unaffected_rows if row["control"] == control]
        comparisons = [
            row["cells"][name]["readout"]["prediction"]
            == row["cells"]["A"]["readout"]["prediction"]
            for row in selected
            for name in ("B", "C")
        ]
        unaffected_agreement[control] = {
            "comparisons": len(comparisons),
            "agreement": sum(comparisons),
            "rate": sum(comparisons) / len(comparisons),
        }
    return {
        "affected_by_control_horizon": by_control_horizon,
        "affected_endpoint_and_auc": auc_by_control,
        "unaffected_prediction_agreement_with_A": unaffected_agreement,
        "semantic_assessment": "DESCRIPTIVE_PILOT_NO_PROMOTION_THRESHOLD",
    }


def _mechanical_checks(
    cases: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    plan: dict[str, Any],
    *,
    parameter_identity_ok: bool,
    checkpoint_unchanged: bool,
    eval_unchanged: bool,
    source_unchanged: bool,
) -> dict[str, bool]:
    non_sham = [
        control
        for case in cases
        for control in case["controls"].values()
        if control.get("pulse_receipts") is not None
    ]
    future = [row for row in rows if row["horizon"] > 0]
    sham = [row for row in rows if row["control"] == "sham"]
    semantic_zero = [row for row in rows if row["control"] == "semantic" and row["horizon"] == 0]
    random_tolerance = plan["pulse"]["gram_relative_tolerance"]
    return {
        "frozen_case_count_complete": len(cases) == plan["expected_cases"],
        "frozen_row_count_complete": len(rows) == plan["expected_trajectory_rows"],
        "all_nonsham_pulses_applied_once": all(
            receipt["applied"] and receipt["call_count"] == 1
            for control in non_sham
            for receipt in control["pulse_receipts"].values()
        ),
        "all_nonsham_native_cast_deltas_nonzero": all(
            receipt["actual_delta_rms"] > 0.0
            for control in non_sham
            for receipt in control["pulse_receipts"].values()
        ),
        "all_nonsham_actual_projections_follow_requested_sign": all(
            receipt["actual_signed_projection"] > 0.0
            for control in non_sham
            for receipt in control["pulse_receipts"].values()
        ),
        "semantic_intact_twin_cache_distinct_at_horizon_zero": all(
            not case["controls"]["semantic"]["horizon_zero_B_vs_C_cache"]["exact_equal"]
            for case in cases
        )
        and all(
            not row["cells"]["C"]["cache_from_A"]["exact_equal"]
            and not row["cells"]["B"]["cache_from_A"]["exact_equal"]
            for row in semantic_zero
        ),
        "sham_is_exactly_noop": all(
            row["cells"][name]["cache_from_A"]["exact_equal"]
            and row["cells"][name]["full_logit_l2_from_A"] == 0.0
            for row in sham
            for name in ("B", "C", "D", "E")
        ),
        "reset_cells_exact_to_A_after_horizon_zero": all(
            row["cells"][name]["cache_from_A"]["exact_equal"]
            and row["cells"][name]["full_logit_l2_from_A"] == 0.0
            for row in future
            for name in ("D", "E")
        ),
        "fixed_tokens_identical_across_cells": all(
            row["fixed_tokens_identical_across_cells"] for row in rows
        ),
        "random_control_preserves_gram": all(
            case["controls"]["gram_matched_random"]["direction_metadata"]["gram_receipt"][
                "relative_error"
            ]["maximum"]
            <= random_tolerance
            for case in cases
        ),
        "unrelated_control_uses_distinct_family": all(
            case["controls"]["unrelated_family"]["direction_metadata"]["distinct_family"]
            for case in cases
        ),
        "unrelated_control_matches_target_rms": all(
            abs(
                case["controls"]["unrelated_family"]["direction_metadata"][name]["rms"]
                - case["controls"]["unrelated_family"]["direction_metadata"]["target_rms"][name]
            )
            <= random_tolerance
            for case in cases
            for name in ("intact", "twin")
        ),
        "inputs_sources_parameters_unchanged": bool(
            parameter_identity_ok and checkpoint_unchanged and eval_unchanged and source_unchanged
        ),
    }


def run(plan: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    started = time.monotonic()
    _validate_plan(plan)
    if output_dir.exists():
        raise TrajectoryError("Output directory already exists")
    output_dir.mkdir(parents=True)
    if _source_identity(plan) != plan["source_identity"]:
        raise TrajectoryError("Frozen source identity mismatch")
    predecessor_path = REPO / plan["predecessor_direction_report"]["path"]
    if _digest(predecessor_path) != plan["predecessor_direction_report"]["sha256"]:
        raise TrajectoryError("Checkpoint direction predecessor hash mismatch")
    predecessor = json.loads(predecessor_path.read_text(encoding="utf-8"))
    if (
        predecessor.get("status") != "QUALIFIED"
        or predecessor.get("checkpoint_direction_native_boundary_qualified") is not True
        or predecessor.get("semantic_effect_qualified") is not False
    ):
        raise TrajectoryError("Required mechanical direction gate is absent")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True).strip():
        raise TrajectoryError("Run requires a clean isolated worktree")
    gpu_admission = _require_idle_gpu()
    observed_env = {key: os.environ.get(key) for key in plan["required_environment"]}
    if observed_env != plan["required_environment"]:
        raise TrajectoryError(f"Runtime environment mismatch: {observed_env}")
    runtime = _runtime()
    if runtime != plan["expected_runtime"] or not torch.cuda.is_available():
        raise TrajectoryError(f"Runtime differs from frozen CUDA contract: {runtime}")
    torch.set_num_threads(plan["cpu_threads"])
    torch.set_num_interop_threads(plan["cpu_threads"])
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.set_float32_matmul_precision("highest")
    torch.cuda.set_per_process_memory_fraction(plan["cuda_allocator_fraction"])
    torch.cuda.reset_peak_memory_stats()

    checkpoint = Path(plan["checkpoint"]["path"])
    eval_path = REPO / plan["eval"]["path"]
    if not checkpoint.is_absolute() or checkpoint.is_symlink() or not checkpoint.is_dir():
        raise TrajectoryError("Checkpoint must be an existing non-symlink absolute directory")
    if _digest(checkpoint / "manifest.json") != plan["checkpoint"]["manifest_sha256"]:
        raise TrajectoryError("Checkpoint manifest hash mismatch")
    if _digest(checkpoint / "workspace_state.pt") != plan["checkpoint"]["workspace_sha256"]:
        raise TrajectoryError("Checkpoint workspace hash mismatch")
    if _digest(eval_path) != plan["eval"]["sha256"]:
        raise TrajectoryError("Evaluation file hash mismatch")
    inventory_before = checkpoint_inventory(checkpoint)
    config = engine.ExperimentConfig.from_json(checkpoint / "experiment_config.json")
    if (
        config.model.train_mode != "full"
        or config.functional.route_mode != "inline_sidecar"
        or config.functional.reader_steps != 1
    ):
        raise TrajectoryError("Checkpoint is not the admitted full inline-sidecar reader-1 lane")
    engine.require_cuda_allocator_policy(config.train)
    engine.configure_runtime_math(config.train)
    engine.set_global_seed(plan["seed"])
    device = engine.resolve_device("cuda")
    model, tokenizer, loaded_config = engine.load_bundle(checkpoint, device=device)
    precision = engine.resolve_mixed_precision(config.train.mixed_precision, device)
    base_model = model.base_model.eval()
    parameter_dtypes = sorted({str(parameter.dtype) for parameter in base_model.parameters()})
    if parameter_dtypes != [plan["model_contract"]["dtype"]]:
        raise TrajectoryError(f"Loaded base dtype differs: {parameter_dtypes}")
    adapter = MistralDynamicCacheAdapter(base_model)
    if adapter.hidden_size != plan["model_contract"]["hidden_size"]:
        raise TrajectoryError("Loaded model hidden size differs from frozen contract")
    identities = {
        name: (id(parameter), parameter._version, parameter.dtype, parameter.requires_grad)
        for name, parameter in model.named_parameters()
    }
    captured_cases = _capture_cases(
        model, tokenizer, loaded_config, eval_path, plan, device, precision
    )
    lookup = {(case.world_index, case.side, case.query_index): case for case in captured_cases}
    pair_ids = {case.world_index: case.pair_id for case in captured_cases}
    if len(set(pair_ids.values())) != plan["max_worlds"]:
        raise TrajectoryError("Unrelated control requires distinct paired-world families")

    case_receipts: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    pulse = plan["pulse"]
    for case_index, case in enumerate(captured_cases):
        print(f"trajectory case {case_index + 1}/{len(captured_cases)} {case.case_id}", flush=True)
        unrelated_world = (case.world_index + 1) % plan["max_worlds"]
        unrelated = lookup[(unrelated_world, case.side, case.query_index)]
        controls, direction_metadata = _control_directions(case, unrelated, plan, case_index)
        suffix_ids = tuple(
            int(value)
            for value in tokenizer.encode(
                plan["fixed_turn"]["separator"] + case.query_text,
                add_special_tokens=False,
            )
        )
        chunk_ids = (case.candidate_ids[case.original_label], *suffix_ids)
        if not suffix_ids:
            raise TrajectoryError("Repeated query tokenization is empty")
        prefix = torch.tensor([case.prefix_ids], device=device, dtype=torch.long)
        prefill = adapter.prefill(
            prefix[:, :-1],
            torch.ones_like(prefix[:, :-1]),
            torch.arange(len(case.prefix_ids) - 1, device=device, dtype=torch.long)[None, :],
        )
        shared_base_cache = adapter.clone(prefill.cache)
        pulse_token = prefix[:, -1:]
        base_initial = _pulse_step(
            adapter,
            shared_base_cache,
            pulse_token,
            len(case.prefix_ids),
            None,
            layer=pulse["layer"],
            boundary=pulse["boundary"],
            composition_dtype=pulse["composition_dtype"],
        )
        control_states: dict[str, dict[str, Any]] = {}
        control_receipts: dict[str, Any] = {}
        for control_name in CONTROLS:
            intact_direction, twin_direction = controls[control_name]
            if intact_direction is None:
                intact_initial = base_initial
                twin_initial = base_initial
                pulse_receipts = None
            else:
                intact_initial = _pulse_step(
                    adapter,
                    shared_base_cache,
                    pulse_token,
                    len(case.prefix_ids),
                    intact_direction,
                    layer=pulse["layer"],
                    boundary=pulse["boundary"],
                    composition_dtype=pulse["composition_dtype"],
                )
                twin_initial = _pulse_step(
                    adapter,
                    shared_base_cache,
                    pulse_token,
                    len(case.prefix_ids),
                    twin_direction,
                    layer=pulse["layer"],
                    boundary=pulse["boundary"],
                    composition_dtype=pulse["composition_dtype"],
                )
                pulse_receipts = {
                    "intact": _jsonable(intact_initial.pulse),
                    "twin": _jsonable(twin_initial.pulse),
                }
            initial_results = {
                "A": base_initial,
                "B": intact_initial,
                "C": twin_initial,
                "D": dataclasses.replace(base_initial, cache=adapter.clone(base_initial.cache)),
                "E": dataclasses.replace(base_initial, cache=adapter.clone(base_initial.cache)),
            }
            inherited = {
                "D": intact_initial.logits,
                "E": twin_initial.logits,
            }
            control_states[control_name] = initial_results
            rows.append(
                _trajectory_row(
                    case,
                    control_name,
                    0,
                    initial_results,
                    adapter,
                    inherited=inherited,
                    history_ids=case.prefix_ids,
                    chunk_ids=chunk_ids,
                )
            )
            control_receipts[control_name] = {
                "direction_metadata": direction_metadata[control_name],
                "pulse_receipts": pulse_receipts,
                "horizon_zero_B_vs_C_cache": _compact_difference(
                    adapter.difference(intact_initial.cache, twin_initial.cache)
                ),
            }
        histories = {control: {name: case.prefix_ids for name in CELLS} for control in CONTROLS}
        for horizon in range(1, plan["turn_count"]):
            for control_name in CONTROLS:
                current = control_states[control_name]
                a_source = current["A"].cache
                next_results = {
                    "A": _extend_fixed_chunk(adapter, current["A"].cache, chunk_ids),
                    "B": _extend_fixed_chunk(adapter, current["B"].cache, chunk_ids),
                    "C": _extend_fixed_chunk(adapter, current["C"].cache, chunk_ids),
                    "D": _extend_fixed_chunk(adapter, adapter.clone(a_source), chunk_ids),
                    "E": _extend_fixed_chunk(adapter, adapter.clone(a_source), chunk_ids),
                }
                control_states[control_name] = next_results
                for name in CELLS:
                    histories[control_name][name] = histories[control_name][name] + chunk_ids
                if len({histories[control_name][name] for name in CELLS}) != 1:
                    raise TrajectoryError("Teacher-forced cell histories diverged")
                rows.append(
                    _trajectory_row(
                        case,
                        control_name,
                        horizon,
                        next_results,
                        adapter,
                        history_ids=histories[control_name]["A"],
                        chunk_ids=chunk_ids,
                    )
                )
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
                "source_position": case.source_position,
                "prefix_sha256": _stable_hash(case.prefix_ids),
                "query_text_sha256": hashlib.sha256(case.query_text.encode()).hexdigest(),
                "candidate_ids": list(case.candidate_ids),
                "original_label": case.original_label,
                "donor_label": case.donor_label,
                "fixed_turn_chunk_ids": list(chunk_ids),
                "fixed_turn_chunk_sha256": _stable_hash(chunk_ids),
                "controls": control_receipts,
            }
        )
        del control_states, prefill, shared_base_cache, base_initial
        torch.cuda.empty_cache()

    parameter_identity_ok = all(
        identities[name]
        == (id(parameter), parameter._version, parameter.dtype, parameter.requires_grad)
        for name, parameter in model.named_parameters()
    )
    checkpoint_unchanged = checkpoint_inventory(checkpoint) == inventory_before
    eval_unchanged = _digest(eval_path) == plan["eval"]["sha256"]
    source_unchanged = _source_identity(plan) == plan["source_identity"]
    mechanical = _mechanical_checks(
        case_receipts,
        rows,
        plan,
        parameter_identity_ok=parameter_identity_ok,
        checkpoint_unchanged=checkpoint_unchanged,
        eval_unchanged=eval_unchanged,
        source_unchanged=source_unchanged,
    )
    execution_qualified = bool(all(mechanical.values()))
    summary = _summarize(rows, plan)
    return {
        "format": "latent-workspace-v14-semantic-trajectory-v1",
        "status": "QUALIFIED_EXECUTION" if execution_qualified else "BLOCKED_EXECUTION",
        "created_utc": datetime.now(UTC).isoformat(),
        "elapsed_seconds": time.monotonic() - started,
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip(),
        "plan_sha256": _digest(PLAN_PATH),
        "source_identity": _source_identity(plan),
        "gpu_admission": gpu_admission,
        "runtime": runtime,
        "precision": precision,
        "model_parameter_dtypes": parameter_dtypes,
        "checkpoint": {
            **plan["checkpoint"],
            "inventory_sha256": _stable_hash(inventory_before),
            "inventory_entries": len(inventory_before),
        },
        "eval": plan["eval"],
        "adapter": _jsonable(adapter.describe()),
        "cases": case_receipts,
        "trajectory_rows": rows,
        "summary": summary,
        "mechanical_checks": mechanical,
        "trajectory_execution_qualified": execution_qualified,
        "semantic_effect_qualified": False,
        "semantic_assessment": "DESCRIPTIVE_PILOT_NO_PROMOTION_THRESHOLD",
        "renderer_and_choice_instrument_qualified": True,
        "full_context_task_qualified": False,
        "training_performed": False,
        "optimizer_constructed": False,
        "free_generation_performed": False,
        "model_integrity": {
            "parameter_identity_versions_unchanged": parameter_identity_ok,
            "checkpoint_inventory_unchanged": checkpoint_unchanged,
            "eval_unchanged": eval_unchanged,
            "source_identity_unchanged": source_unchanged,
        },
        "cuda_peak_allocated_bytes": int(torch.cuda.max_memory_allocated()),
        "claim_boundary": plan["claim_boundary"],
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    output_dir = args.output_dir.expanduser().resolve()
    try:
        plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        report = run(plan, output_dir)
    except BaseException as exc:
        output_dir.mkdir(parents=True, exist_ok=True)
        report = {
            "format": "latent-workspace-v14-semantic-trajectory-v1",
            "status": "FAILED",
            "created_utc": datetime.now(UTC).isoformat(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "training_performed": False,
            "free_generation_performed": False,
        }
        _write_report(output_dir / "report.json", report)
        print(json.dumps({"status": "FAILED", "error": str(exc)}, indent=2), flush=True)
        return 1
    _write_report(output_dir / "report.json", report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "mechanical_checks": report["mechanical_checks"],
                "affected_endpoint_and_auc": report["summary"]["affected_endpoint_and_auc"],
                "elapsed_seconds": report["elapsed_seconds"],
            },
            indent=2,
        ),
        flush=True,
    )
    return 0 if report["status"] == "QUALIFIED_EXECUTION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
