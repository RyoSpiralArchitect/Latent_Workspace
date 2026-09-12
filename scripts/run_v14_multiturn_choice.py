#!/usr/bin/env python3
"""Run frozen constrained multi-turn trajectories after the V14 precision gate."""

from __future__ import annotations

import argparse
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

import run_v14_answer_boundary_recurrence as recurrence  # noqa: E402
import run_v14_experimental_chat as prior_chat  # noqa: E402
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

PLAN_PATH = REPO / "configs/v14/MULTITURN_CHOICE_PLAN.json"
FORMAT = "latent-workspace-v14-multiturn-choice-v1"
MODEL_ORDER = ("base", "task", "semantic")
HISTORY_MODES = ("teacher_forced_fixed_history", "free_history")
READOUTS = ("native_bf16_head", "fp32_choice_head")
TURN_QUERY_INDICES = (0, 2, 0, 2)
REGIMES = (
    {"id": "greedy", "seed": 0, "temperature": 0.0},
    {"id": "sample_211", "seed": 211, "temperature": 0.7},
    {"id": "sample_212", "seed": 212, "temperature": 0.7},
    {"id": "sample_213", "seed": 213, "temperature": 0.7},
)
CONDITIONS = (
    {
        "id": "base_query_only",
        "model": "base",
        "route": "query_only",
        "memory": "none",
    },
    {
        "id": "base_inline",
        "model": "base",
        "route": "inline",
        "memory": "original",
    },
    {
        "id": "task_full_intact",
        "model": "task",
        "route": "full_route",
        "memory": "intact",
    },
    {
        "id": "task_full_twin",
        "model": "task",
        "route": "full_route",
        "memory": "twin",
    },
    {
        "id": "task_boundary_intact",
        "model": "task",
        "route": "answer_boundary_only",
        "memory": "intact",
    },
    {
        "id": "task_boundary_twin",
        "model": "task",
        "route": "answer_boundary_only",
        "memory": "twin",
    },
    {
        "id": "task_non_boundary_intact",
        "model": "task",
        "route": "non_boundary_only",
        "memory": "intact",
    },
    {
        "id": "task_non_boundary_twin",
        "model": "task",
        "route": "non_boundary_only",
        "memory": "twin",
    },
    {
        "id": "semantic_full_intact",
        "model": "semantic",
        "route": "full_route",
        "memory": "intact",
    },
    {
        "id": "semantic_full_twin",
        "model": "semantic",
        "route": "full_route",
        "memory": "twin",
    },
    {
        "id": "semantic_boundary_intact",
        "model": "semantic",
        "route": "answer_boundary_only",
        "memory": "intact",
    },
    {
        "id": "semantic_boundary_twin",
        "model": "semantic",
        "route": "answer_boundary_only",
        "memory": "twin",
    },
    {
        "id": "semantic_non_boundary_intact",
        "model": "semantic",
        "route": "non_boundary_only",
        "memory": "intact",
    },
    {
        "id": "semantic_non_boundary_twin",
        "model": "semantic",
        "route": "non_boundary_only",
        "memory": "twin",
    },
)


class MultiTurnError(RuntimeError):
    """Raised when the frozen multi-turn assay cannot execute exactly."""


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _source_identity(root: Path, plan: dict[str, Any]) -> dict[str, str]:
    expected = plan.get("source_identity")
    if not isinstance(expected, dict) or not expected:
        raise MultiTurnError("Frozen source_identity must be a nonempty mapping")
    observed: dict[str, str] = {}
    for relative in expected:
        path = resolve_inside(root, relative, label="source identity")
        if not path.is_file() or path.is_symlink():
            raise MultiTurnError(f"Source identity is not a plain file: {relative}")
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
        "format": "latent-workspace-v14-multiturn-choice-plan-v1",
        "frozen_before_generation": True,
        "model_order": list(MODEL_ORDER),
        "history_modes": list(HISTORY_MODES),
        "readouts": list(READOUTS),
        "turn_query_indices": list(TURN_QUERY_INDICES),
        "regimes": list(REGIMES),
        "conditions": list(CONDITIONS),
        "expected_scenarios": 4,
        "expected_conditions": 14,
        "expected_trajectories": 896,
        "expected_turn_rows": 3584,
        "choice_vocabulary": ["no", "yes"],
        "kv_cache": False,
        "full_prefix_recompute_each_turn": True,
        "semantic_promotion": False,
    }
    mismatches = {
        key: {"observed": plan.get(key), "expected": value}
        for key, value in expected.items()
        if plan.get(key) != value
    }
    expected_actions = {
        "checkpoint_load": True,
        "constrained_choice_generation": True,
        "native_full_vocab_head": True,
        "fp32_two_choice_head": True,
        "teacher_forced_history": True,
        "free_choice_history": True,
        "full_prefix_recompute": True,
        "kv_cache": False,
        "unconstrained_free_form_generation": False,
        "optimizer_or_training": False,
        "model_download": False,
        "weight_write_or_delete": False,
        "condition_prompt_metric_or_checkpoint_selection": False,
        "semantic_promotion": False,
    }
    if plan.get("authorized_actions") != expected_actions:
        mismatches["authorized_actions"] = {
            "observed": plan.get("authorized_actions"),
            "expected": expected_actions,
        }
    if mismatches:
        raise MultiTurnError(f"Frozen plan mismatch: {mismatches}")

    predecessors: dict[str, Path] = {}
    for name, artifact in plan["predecessors"].items():
        path = resolve_inside(root, artifact["path"], label=f"predecessor {name}")
        if not path.is_file() or digest(path) != artifact["sha256"]:
            raise MultiTurnError(f"Predecessor changed: {name}")
        predecessors[name] = path
    precision_report = load_json(predecessors["readout_precision_report"])
    precision_summary = load_json(predecessors["readout_precision_summary"])
    if (
        precision_report.get("status") != "QUALIFIED_EXECUTION"
        or precision_report.get("winner") != "none"
        or precision_report.get("semantic_effect_qualified") is not False
        or precision_summary.get("winner") != "none"
        or precision_summary.get("semantic_effect_qualified") is not False
    ):
        raise MultiTurnError("Readout-precision predecessor contract changed")

    eval_path = resolve_inside(root, plan["eval"]["path"], label="eval")
    if not eval_path.is_file() or digest(eval_path) != plan["eval"]["sha256"]:
        raise MultiTurnError("Frozen evaluation file changed")
    scenarios = plan.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != 4:
        raise MultiTurnError("Exactly four frozen world/side scenarios are required")
    observed_scenarios = [
        (row.get("id"), row.get("world_index"), row.get("side")) for row in scenarios
    ]
    expected_scenarios = [
        ("w0_s0", 0, 0),
        ("w0_s1", 0, 1),
        ("w1_s0", 1, 0),
        ("w1_s1", 1, 1),
    ]
    if observed_scenarios != expected_scenarios:
        raise MultiTurnError("Frozen scenario order changed")

    model_specs = plan.get("models")
    if not isinstance(model_specs, list) or [row.get("id") for row in model_specs] != [
        "task",
        "semantic",
    ]:
        raise MultiTurnError("Ordered task and semantic checkpoints are required")
    resolved_models: dict[str, dict[str, Any]] = {}
    for model in model_specs:
        checkpoint = resolve_inside(root, model["checkpoint"], label="checkpoint")
        if verify_checkpoints:
            if not (checkpoint / "COMPLETED").is_file():
                raise MultiTurnError(f"Incomplete checkpoint: {model['id']}")
            if digest(checkpoint / "manifest.json") != model["manifest_sha256"]:
                raise MultiTurnError(f"Checkpoint manifest changed: {model['id']}")
            if digest(checkpoint / "workspace_state.pt") != model["workspace_sha256"]:
                raise MultiTurnError(f"Workspace state changed: {model['id']}")
        resolved_models[str(model["id"])] = {**model, "path": checkpoint}

    if _source_identity(root, plan) != plan["source_identity"]:
        raise MultiTurnError("Frozen source identity changed")
    output = resolve_inside(root, plan["output"], label="output")
    if require_fresh and output.exists():
        raise MultiTurnError(f"Output already exists: {output}")
    return {
        "predecessors": predecessors,
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
        raise MultiTurnError(
            f"Runtime mismatch: observed={observed}, expected={plan['expected_runtime']}"
        )
    environment = {key: os.environ.get(key) for key in plan["required_environment"]}
    if environment != plan["required_environment"]:
        raise MultiTurnError(f"Environment mismatch: {environment}")
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise MultiTurnError("Exactly one visible CUDA device is required")
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
        raise MultiTurnError("GPU already has compute clients; refusing to interfere")
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
        raise MultiTurnError(f"Model protocol changed for {model_id}: {observed}")


def _project_scenarios(
    dataset: Any,
    tokenizer: Any,
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    for frozen in plan["scenarios"]:
        world = int(frozen["world_index"])
        side = int(frozen["side"])
        feature = dataset[world]
        source = dataset._read_record(dataset.locations[world])
        first_query = TURN_QUERY_INDICES[0]
        query_prefix = prior_chat._prompt_prefix(
            feature["functional_query_ids"][side][first_query],
            feature["functional_query_labels"][side][first_query],
        )
        inline_prefix = prior_chat._prompt_prefix(
            feature["functional_inline_ids"][side][first_query],
            feature["functional_inline_labels"][side][first_query],
        )
        turns: list[dict[str, Any]] = []
        candidate_ids: tuple[int, int] | None = None
        for turn_index, query_index in enumerate(TURN_QUERY_INDICES):
            choices = feature["functional_query_choice_ids"][side][query_index]
            if any(len(value) != 1 for value in choices):
                raise MultiTurnError("Multi-turn choice generation requires one-token choices")
            observed_candidates = (int(choices[0][0]), int(choices[1][0]))
            if candidate_ids is None:
                candidate_ids = observed_candidates
            elif candidate_ids != observed_candidates:
                raise MultiTurnError("Choice token IDs changed within a scenario")
            query_text = str(source["queries"][query_index])
            suffix = tuple(
                int(value)
                for value in tokenizer.encode(
                    "\n" + query_text,
                    add_special_tokens=False,
                )
            )
            original_label = int(feature["functional_answers"][side][query_index])
            donor_label = int(feature["functional_answers"][1 - side][query_index])
            affected = bool(feature["functional_affected"][query_index])
            if affected != (original_label != donor_label):
                raise MultiTurnError("Affected flag and donor label disagree")
            turns.append(
                {
                    "turn_index": turn_index,
                    "query_index": query_index,
                    "query_text": query_text,
                    "query_suffix": suffix,
                    "affected": affected,
                    "heldout": bool(feature["functional_heldout_queries"][query_index]),
                    "hop_distance": int(feature["functional_hop_distances"][query_index]),
                    "original_label": original_label,
                    "donor_label": donor_label,
                }
            )
        if candidate_ids is None:
            raise MultiTurnError("Scenario contains no answer choices")
        contexts = tuple(
            tuple(int(token) for token in context) for context in feature["functional_context_ids"]
        )
        scenarios.append(
            {
                "id": str(frozen["id"]),
                "world_index": world,
                "side": side,
                "pair_id": str(source.get("metadata", {}).get("pair_id", f"world-{world}")),
                "query_prefix": tuple(int(value) for value in query_prefix),
                "inline_prefix": tuple(int(value) for value in inline_prefix),
                "contexts": contexts,
                "candidate_ids": candidate_ids,
                "choice_text": ("no", "yes"),
                "turns": turns,
            }
        )
    if len(scenarios) != 4:
        raise MultiTurnError("Scenario projection did not close at four")
    return scenarios


def _matched_uniform(seed: int, scenario_id: str, turn_index: int) -> float:
    payload = f"{int(seed)}|{scenario_id}|{int(turn_index)}".encode()
    integer = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
    return (integer + 0.5) / 2**64


def _sample_choice(
    scores: list[float],
    *,
    temperature: float,
    uniform: float | None,
) -> tuple[int, list[float]]:
    if len(scores) != 2 or not all(math.isfinite(value) for value in scores):
        raise MultiTurnError("Choice sampler requires two finite scores")
    values = torch.tensor(scores, dtype=torch.float64)
    if temperature <= 0.0:
        return int(torch.argmax(values).item()), [
            float(value) for value in torch.softmax(values, dim=-1).tolist()
        ]
    if uniform is None or not 0.0 < uniform < 1.0:
        raise MultiTurnError("Sampled generation requires one matched open-unit uniform")
    probabilities = torch.softmax(values / float(temperature), dim=-1)
    choice = int(uniform >= float(probabilities[0].item()))
    return choice, [float(value) for value in probabilities.tolist()]


def _direction_stats(value: torch.Tensor) -> dict[str, Any]:
    return recurrence._direction_stats(value)


@torch.no_grad()
def _decode_turn(
    model: Any,
    adapter: MistralChoiceReadoutAdapter,
    prefix: tuple[int, ...],
    candidate_ids: tuple[int, int],
    *,
    route: str,
    memory: torch.Tensor | None,
    memory_mask: torch.Tensor | None,
    device: torch.device,
    precision: str,
    boundary_layer: int,
) -> dict[str, Any]:
    if model.functional_boundary_adapter is None:
        raise MultiTurnError("Functional boundary adapter is absent")
    ids = torch.tensor([prefix], device=device, dtype=torch.long)
    attention = torch.ones_like(ids)
    with engine.autocast_context(device, precision):
        boundary = model.functional_boundary_adapter.encode(
            ids,
            attention,
            boundary_layer,
        )

    gate_mean: float | None = None
    read_norm: float | None = None
    partition_exact: bool | None = None
    if route in {"query_only", "inline"}:
        requested = torch.zeros_like(boundary, dtype=torch.float32)
    else:
        if model.functional_reader is None or memory is None or memory_mask is None:
            raise MultiTurnError("Workspace route requires reader memory")
        with engine.autocast_context(device, precision):
            reader_state = model.functional_reader.read_state(
                boundary,
                attention,
                memory,
                memory_mask,
            )
        if len(reader_state.per_step_updates) != 1:
            raise MultiTurnError("Frozen multi-turn harness requires one reader step")
        full = reader_state.per_step_updates[0].detach().float()
        boundary_request = torch.zeros_like(full)
        boundary_request[:, -1:] = full[:, -1:]
        non_boundary_request = torch.zeros_like(full)
        non_boundary_request[:, :-1] = full[:, :-1]
        if route == "full_route":
            requested = full
        elif route == "answer_boundary_only":
            requested = boundary_request
        elif route == "non_boundary_only":
            requested = non_boundary_request
        else:
            raise MultiTurnError(f"Unknown workspace route: {route}")
        base_float = boundary.float()

        def actual(request: torch.Tensor) -> torch.Tensor:
            return (base_float + request).to(dtype=boundary.dtype).float() - base_float

        partition_exact = bool(
            torch.equal(
                actual(full),
                actual(boundary_request) + actual(non_boundary_request),
            )
        )
        gate_mean = float(reader_state.gate_mean.detach().float().item())
        read_norm = float(reader_state.read_norm.detach().float().item())

    modified = (boundary.float() + requested).to(dtype=boundary.dtype)
    with engine.autocast_context(device, precision):
        decoded = adapter.decode_choices(
            modified,
            attention,
            boundary_layer,
            candidate_ids,
        )
    native_scores = [
        float(value) for value in decoded.native_choice_scores.detach().float().reshape(-1).tolist()
    ]
    fp32_scores = [
        float(value) for value in decoded.fp32_choice_scores.detach().float().reshape(-1).tolist()
    ]
    return {
        "native_bf16_head": {
            "scores": native_scores,
            "yes_minus_no": native_scores[1] - native_scores[0],
            "greedy_choice": int(native_scores[1] > native_scores[0]),
        },
        "fp32_choice_head": {
            "scores": fp32_scores,
            "yes_minus_no": fp32_scores[1] - fp32_scores[0],
            "greedy_choice": int(fp32_scores[1] > fp32_scores[0]),
        },
        "native_logits_dtype": str(decoded.native_logits.dtype),
        "fp32_choice_dtype": str(decoded.fp32_choice_scores.dtype),
        "same_normalized_hidden_for_both_heads": True,
        "normalized_last_hidden": _direction_stats(decoded.normalized_last_hidden),
        "reader": {
            "gate_mean": gate_mean,
            "read_norm": read_norm,
            "full_equals_boundary_plus_non_boundary_native_exact": partition_exact,
        },
    }


def _analysis_margin(
    scores: list[float],
    *,
    affected: bool,
    original_label: int,
    donor_label: int,
) -> float:
    if affected:
        return scores[donor_label] - scores[original_label]
    return scores[original_label] - scores[1 - original_label]


def _target_label(condition: dict[str, Any], turn: dict[str, Any]) -> int:
    return (
        int(turn["donor_label"]) if condition["memory"] == "twin" else int(turn["original_label"])
    )


def _run_trajectory(
    model: Any,
    adapter: MistralChoiceReadoutAdapter,
    scenario: dict[str, Any],
    condition: dict[str, Any],
    history_mode: str,
    regime: dict[str, Any],
    selected_readout: str,
    memory: torch.Tensor | None,
    memory_mask: torch.Tensor | None,
    *,
    device: torch.device,
    precision: str,
    boundary_layer: int,
) -> dict[str, Any]:
    prefix = (
        scenario["inline_prefix"] if condition["route"] == "inline" else scenario["query_prefix"]
    )
    generated_labels: list[int] = []
    appended_labels: list[int] = []
    turns: list[dict[str, Any]] = []
    for turn_index, turn in enumerate(scenario["turns"]):
        receipt = _decode_turn(
            model,
            adapter,
            prefix,
            scenario["candidate_ids"],
            route=str(condition["route"]),
            memory=memory,
            memory_mask=memory_mask,
            device=device,
            precision=precision,
            boundary_layer=boundary_layer,
        )
        uniform = (
            None
            if float(regime["temperature"]) <= 0.0
            else _matched_uniform(int(regime["seed"]), scenario["id"], turn_index)
        )
        selected_scores = receipt[selected_readout]["scores"]
        choice, probabilities = _sample_choice(
            selected_scores,
            temperature=float(regime["temperature"]),
            uniform=uniform,
        )
        target_label = _target_label(condition, turn)
        original_label = int(turn["original_label"])
        donor_label = int(turn["donor_label"])
        appended = original_label if history_mode == HISTORY_MODES[0] else choice
        turns.append(
            {
                "turn_index": turn_index,
                "query_index": int(turn["query_index"]),
                "query_text": str(turn["query_text"]),
                "affected": bool(turn["affected"]),
                "heldout": bool(turn["heldout"]),
                "hop_distance": int(turn["hop_distance"]),
                "prefix_token_count": len(prefix),
                "prefix_token_sha256": _stable_hash(prefix),
                "history_generated_labels_before_turn": list(generated_labels),
                "history_appended_labels_before_turn": list(appended_labels),
                "matched_uniform": uniform,
                "selected_readout": selected_readout,
                "selected_scores": selected_scores,
                "selected_probabilities": probabilities,
                "choice_label": choice,
                "choice_text": scenario["choice_text"][choice],
                "choice_token_id": scenario["candidate_ids"][choice],
                "appended_history_label": appended,
                "appended_history_text": scenario["choice_text"][appended],
                "target_label": target_label,
                "target_correct": choice == target_label,
                "original_label": original_label,
                "original_correct": choice == original_label,
                "donor_label": donor_label,
                "donor_correct": choice == donor_label,
                "analysis_margin": _analysis_margin(
                    selected_scores,
                    affected=bool(turn["affected"]),
                    original_label=original_label,
                    donor_label=donor_label,
                ),
                "dual_readout": receipt,
            }
        )
        generated_labels.append(choice)
        appended_labels.append(appended)
        if turn_index + 1 < len(scenario["turns"]):
            next_turn = scenario["turns"][turn_index + 1]
            prefix = (
                *prefix,
                int(scenario["candidate_ids"][appended]),
                *next_turn["query_suffix"],
            )
    return {
        "condition": condition["id"],
        "model": condition["model"],
        "route": condition["route"],
        "memory": condition["memory"],
        "scenario": scenario["id"],
        "world_index": scenario["world_index"],
        "side": scenario["side"],
        "pair_id": scenario["pair_id"],
        "history_mode": history_mode,
        "regime": regime["id"],
        "seed": regime["seed"],
        "temperature": regime["temperature"],
        "selected_readout": selected_readout,
        "candidate_token_ids": list(scenario["candidate_ids"]),
        "generated_labels": generated_labels,
        "generated_text": [scenario["choice_text"][value] for value in generated_labels],
        "appended_history_labels": appended_labels,
        "appended_history_text": [scenario["choice_text"][value] for value in appended_labels],
        "trajectory_sha256": _stable_hash(generated_labels),
        "turns": turns,
    }


def _describe(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "mean": None, "mean_absolute": None}
    if not all(math.isfinite(value) for value in values):
        raise MultiTurnError("Summary received nonfinite values")
    return {
        "count": len(values),
        "mean": sum(values) / len(values),
        "mean_absolute": sum(abs(value) for value in values) / len(values),
        "positive": sum(value > 0 for value in values),
        "zero": sum(value == 0 for value in values),
        "negative": sum(value < 0 for value in values),
        "minimum": min(values),
        "maximum": max(values),
    }


def _first_difference(left: list[int], right: list[int]) -> int | None:
    for index, (first, second) in enumerate(zip(left, right, strict=True)):
        if first != second:
            return index
    return None


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    condition_turn: dict[str, Any] = {}
    grouped: dict[tuple[str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for turn in row["turns"]:
            grouped[
                (
                    row["condition"],
                    row["history_mode"],
                    row["selected_readout"],
                    int(turn["turn_index"]),
                )
            ].append(turn)
    for key, values in sorted(grouped.items()):
        condition, history_mode, readout, turn_index = key
        name = f"{condition}|{history_mode}|{readout}|turn{turn_index}"
        condition_turn[name] = {
            "count": len(values),
            "target_accuracy": sum(bool(value["target_correct"]) for value in values) / len(values),
            "original_accuracy": sum(bool(value["original_correct"]) for value in values)
            / len(values),
            "donor_accuracy": sum(bool(value["donor_correct"]) for value in values) / len(values),
            "analysis_margin": _describe([float(value["analysis_margin"]) for value in values]),
        }

    indexed = {
        (
            row["condition"],
            row["scenario"],
            row["history_mode"],
            row["regime"],
            row["selected_readout"],
        ): row
        for row in rows
    }
    intact_twin: dict[str, Any] = {}
    for model in ("task", "semantic"):
        for route, stem in (
            ("full_route", "full"),
            ("answer_boundary_only", "boundary"),
            ("non_boundary_only", "non_boundary"),
        ):
            for history_mode in HISTORY_MODES:
                for readout in READOUTS:
                    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
                    for scenario_id in ("w0_s0", "w0_s1", "w1_s0", "w1_s1"):
                        for regime in (row["id"] for row in REGIMES):
                            intact = indexed[
                                (
                                    f"{model}_{stem}_intact",
                                    scenario_id,
                                    history_mode,
                                    regime,
                                    readout,
                                )
                            ]
                            twin = indexed[
                                (
                                    f"{model}_{stem}_twin",
                                    scenario_id,
                                    history_mode,
                                    regime,
                                    readout,
                                )
                            ]
                            pairs.append((intact, twin))
                    changed = [
                        sum(
                            a != b
                            for a, b in zip(
                                left["generated_labels"], right["generated_labels"], strict=True
                            )
                        )
                        for left, right in pairs
                    ]
                    affected_slots = [
                        (left["turns"][turn], right["turns"][turn])
                        for left, right in pairs
                        for turn in (0, 2)
                    ]
                    unaffected_slots = [
                        (left["turns"][turn], right["turns"][turn])
                        for left, right in pairs
                        for turn in (1, 3)
                    ]
                    pair_effect_by_turn = {
                        str(turn): _describe(
                            [
                                float(right["turns"][turn]["analysis_margin"])
                                - float(left["turns"][turn]["analysis_margin"])
                                for left, right in pairs
                            ]
                        )
                        for turn in range(4)
                    }
                    name = f"{model}|{route}|{history_mode}|{readout}"
                    intact_twin[name] = {
                        "pair_count": len(pairs),
                        "trajectory_changed_pairs": sum(value > 0 for value in changed),
                        "mean_hamming_turns": sum(changed) / len(changed),
                        "first_turn_same_then_later_changed_pairs": sum(
                            left["generated_labels"][0] == right["generated_labels"][0]
                            and _first_difference(
                                left["generated_labels"], right["generated_labels"]
                            )
                            is not None
                            for left, right in pairs
                        ),
                        "affected_changed_slots": sum(
                            left["choice_label"] != right["choice_label"]
                            for left, right in affected_slots
                        ),
                        "affected_changed_to_twin_donor_slots": sum(
                            left["choice_label"] != right["choice_label"]
                            and right["choice_label"] == right["donor_label"]
                            for left, right in affected_slots
                        ),
                        "unaffected_same_slots": sum(
                            left["choice_label"] == right["choice_label"]
                            for left, right in unaffected_slots
                        ),
                        "affected_slot_count": len(affected_slots),
                        "unaffected_slot_count": len(unaffected_slots),
                        "signed_pair_effect_by_turn": pair_effect_by_turn,
                    }

    readout_pairs: dict[str, Any] = {}
    for condition in (row["id"] for row in CONDITIONS):
        for history_mode in HISTORY_MODES:
            pairs = []
            for scenario_id in ("w0_s0", "w0_s1", "w1_s0", "w1_s1"):
                for regime in (row["id"] for row in REGIMES):
                    native = indexed[(condition, scenario_id, history_mode, regime, READOUTS[0])]
                    fp32 = indexed[(condition, scenario_id, history_mode, regime, READOUTS[1])]
                    pairs.append((native, fp32))
            differences = [
                sum(
                    a != b
                    for a, b in zip(
                        left["generated_labels"], right["generated_labels"], strict=True
                    )
                )
                for left, right in pairs
            ]
            readout_pairs[f"{condition}|{history_mode}"] = {
                "pair_count": len(pairs),
                "trajectory_changed_pairs": sum(value > 0 for value in differences),
                "mean_hamming_turns": sum(differences) / len(differences),
                "first_difference_histogram": {
                    str(turn): sum(
                        _first_difference(left["generated_labels"], right["generated_labels"])
                        == turn
                        for left, right in pairs
                    )
                    for turn in range(4)
                },
            }

    history_pairs: dict[str, Any] = {}
    for condition in (row["id"] for row in CONDITIONS):
        for readout in READOUTS:
            pairs = []
            for scenario_id in ("w0_s0", "w0_s1", "w1_s0", "w1_s1"):
                for regime in (row["id"] for row in REGIMES):
                    fixed = indexed[(condition, scenario_id, HISTORY_MODES[0], regime, readout)]
                    free = indexed[(condition, scenario_id, HISTORY_MODES[1], regime, readout)]
                    pairs.append((fixed, free))
            differences = [
                sum(
                    a != b
                    for a, b in zip(
                        left["generated_labels"], right["generated_labels"], strict=True
                    )
                )
                for left, right in pairs
            ]
            history_pairs[f"{condition}|{readout}"] = {
                "pair_count": len(pairs),
                "trajectory_changed_pairs": sum(value > 0 for value in differences),
                "mean_hamming_turns": sum(differences) / len(differences),
                "first_difference_histogram": {
                    str(turn): sum(
                        _first_difference(left["generated_labels"], right["generated_labels"])
                        == turn
                        for left, right in pairs
                    )
                    for turn in range(4)
                },
            }

    predeclared_greedy: dict[str, Any] = {}
    for row in rows:
        if (
            row["model"] == "semantic"
            and row["regime"] == "greedy"
            and row["history_mode"] in HISTORY_MODES
        ):
            predeclared_greedy[
                f"{row['condition']}|{row['scenario']}|{row['history_mode']}|{row['selected_readout']}"
            ] = row["generated_text"]
    return {
        "condition_turn_metrics": condition_turn,
        "intact_twin_trajectory_pairs": intact_twin,
        "native_fp32_trajectory_pairs": readout_pairs,
        "fixed_free_history_pairs": history_pairs,
        "predeclared_semantic_greedy_transcripts": predeclared_greedy,
        "interpretation_boundary": (
            "Constrained no/yes trajectories diagnose history-mediated divergence. "
            "They are not unconstrained chat quality, KV-cache-specific evidence, or promotion."
        ),
        "winner": "none",
    }


def _model_checks(
    rows: list[dict[str, Any]],
    *,
    expected_trajectories: int,
    parameter_identity_ok: bool,
    checkpoint_unchanged: bool,
    source_unchanged: bool,
    eval_unchanged: bool,
) -> dict[str, bool]:
    readout_recompute_consistent = True
    paired: dict[tuple[str, str, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        paired[
            (
                row["condition"],
                row["scenario"],
                row["history_mode"],
                row["regime"],
            )
        ][row["selected_readout"]] = row
    for pair in paired.values():
        if set(pair) != set(READOUTS):
            readout_recompute_consistent = False
            continue
        native = pair[READOUTS[0]]
        fp32 = pair[READOUTS[1]]
        for left, right in zip(native["turns"], fp32["turns"], strict=True):
            if left["prefix_token_sha256"] != right["prefix_token_sha256"]:
                continue
            if (
                left["dual_readout"]["native_bf16_head"]
                != right["dual_readout"]["native_bf16_head"]
                or left["dual_readout"]["fp32_choice_head"]
                != right["dual_readout"]["fp32_choice_head"]
                or left["dual_readout"]["normalized_last_hidden"]["sha256"]
                != right["dual_readout"]["normalized_last_hidden"]["sha256"]
            ):
                readout_recompute_consistent = False

    fixed_query_histories_match = all(
        len(
            {
                row["turns"][turn]["prefix_token_sha256"]
                for row in rows
                if row["history_mode"] == HISTORY_MODES[0]
                and row["scenario"] == scenario
                and row["route"] != "inline"
            }
        )
        == 1
        for scenario in ("w0_s0", "w0_s1", "w1_s0", "w1_s1")
        for turn in range(4)
    )
    return {
        "trajectory_count_complete": len(rows) == expected_trajectories,
        "four_turns_each": all(len(row["turns"]) == 4 for row in rows),
        "same_hidden_dual_readout": all(
            turn["dual_readout"]["same_normalized_hidden_for_both_heads"]
            for row in rows
            for turn in row["turns"]
        ),
        "native_and_fp32_dtypes_distinct": all(
            turn["dual_readout"]["native_logits_dtype"] == "torch.bfloat16"
            and turn["dual_readout"]["fp32_choice_dtype"] == "torch.float32"
            for row in rows
            for turn in row["turns"]
        ),
        "fixed_history_always_appends_original": all(
            turn["appended_history_label"] == turn["original_label"]
            for row in rows
            if row["history_mode"] == HISTORY_MODES[0]
            for turn in row["turns"]
        ),
        "free_history_always_appends_generated": all(
            turn["appended_history_label"] == turn["choice_label"]
            for row in rows
            if row["history_mode"] == HISTORY_MODES[1]
            for turn in row["turns"]
        ),
        "fixed_query_histories_match_across_base_and_workspace_routes": (
            fixed_query_histories_match
        ),
        "duplicate_readout_recompute_exact_when_prefix_matches": (readout_recompute_consistent),
        "matched_uniform_independent_of_condition_history_and_readout": all(
            len(
                {
                    row["turns"][turn]["matched_uniform"]
                    for row in rows
                    if row["scenario"] == selected["scenario"]
                    and row["regime"] == selected["regime"]
                }
            )
            == 1
            for selected in rows
            for turn in range(4)
        ),
        "workspace_position_partition_exact": all(
            turn["dual_readout"]["reader"]["full_equals_boundary_plus_non_boundary_native_exact"]
            is True
            for row in rows
            if row["model"] != "base"
            for turn in row["turns"]
        ),
        "inputs_sources_parameters_unchanged": bool(
            parameter_identity_ok and checkpoint_unchanged and source_unchanged and eval_unchanged
        ),
    }


def _process_checkpoint(
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
    parameter_dtypes = sorted({str(parameter.dtype) for parameter in model.base_model.parameters()})
    if parameter_dtypes != ["torch.bfloat16"]:
        raise MultiTurnError(f"Loaded base parameter dtype changed: {parameter_dtypes}")
    identities = {
        name: (id(parameter), parameter._version, parameter.dtype, parameter.requires_grad)
        for name, parameter in model.named_parameters()
    }
    dataset = engine.JsonlFineTuningDataset([str(eval_path)], tokenizer, config.data)
    scenarios = _project_scenarios(dataset, tokenizer, plan)
    if model.functional_boundary_adapter is None:
        raise MultiTurnError("Functional boundary adapter is absent")
    adapter = MistralChoiceReadoutAdapter(model.functional_boundary_adapter)
    memory_cache: dict[tuple[int, int], tuple[torch.Tensor, torch.Tensor]] = {}
    for scenario in scenarios:
        for source_side in (0, 1):
            key = (int(scenario["world_index"]), source_side)
            if key not in memory_cache:
                memory_cache[key] = recurrence._context_memory(
                    model,
                    scenario["contexts"][source_side],
                    device=device,
                    precision=precision,
                    boundary_layer=boundary_layer,
                )

    allowed_models = {model_id}
    if model_id == "task":
        allowed_models.add("base")
    conditions = [row for row in CONDITIONS if row["model"] in allowed_models]
    rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        for condition in conditions:
            print(
                f"multiturn {model_id}/{scenario['id']}/{condition['id']}",
                flush=True,
            )
            memory: torch.Tensor | None = None
            memory_mask: torch.Tensor | None = None
            if condition["memory"] in {"intact", "twin"}:
                source_side = (
                    int(scenario["side"])
                    if condition["memory"] == "intact"
                    else 1 - int(scenario["side"])
                )
                memory, memory_mask = memory_cache[(int(scenario["world_index"]), source_side)]
            for history_mode in HISTORY_MODES:
                for regime in REGIMES:
                    for readout in READOUTS:
                        rows.append(
                            _run_trajectory(
                                model,
                                adapter,
                                scenario,
                                condition,
                                history_mode,
                                regime,
                                readout,
                                memory,
                                memory_mask,
                                device=device,
                                precision=precision,
                                boundary_layer=boundary_layer,
                            )
                        )

    parameter_identity_ok = identities == {
        name: (id(parameter), parameter._version, parameter.dtype, parameter.requires_grad)
        for name, parameter in model.named_parameters()
    }
    checkpoint_unchanged = checkpoint_inventory(checkpoint) == inventory_before
    source_unchanged = _source_identity(REPO, plan) == plan["source_identity"]
    eval_unchanged = digest(eval_path) == plan["eval"]["sha256"]
    expected = 512 if model_id == "task" else 384
    checks = _model_checks(
        rows,
        expected_trajectories=expected,
        parameter_identity_ok=parameter_identity_ok,
        checkpoint_unchanged=checkpoint_unchanged,
        source_unchanged=source_unchanged,
        eval_unchanged=eval_unchanged,
    )
    identity = {
        "checkpoint": checkpoint.relative_to(REPO).as_posix(),
        "manifest_sha256": digest(checkpoint / "manifest.json"),
        "workspace_sha256": digest(checkpoint / "workspace_state.pt"),
        "checkpoint_inventory_sha256": _stable_hash(inventory_before),
        "checkpoint_inventory_entries": len(inventory_before),
        "parameter_dtypes": parameter_dtypes,
        "precision": precision,
        "readout_adapter": adapter.describe(),
        "scenario_projection_sha256": _stable_hash(
            [
                {
                    "id": scenario["id"],
                    "query_prefix": scenario["query_prefix"],
                    "inline_prefix": scenario["inline_prefix"],
                    "turns": scenario["turns"],
                }
                for scenario in scenarios
            ]
        ),
        "integrity": {
            "parameter_identity_versions_unchanged": parameter_identity_ok,
            "checkpoint_inventory_unchanged": checkpoint_unchanged,
            "source_identity_unchanged": source_unchanged,
            "eval_unchanged": eval_unchanged,
        },
    }
    del memory_cache, adapter, scenarios, dataset, tokenizer, model
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
        "generation_protocol": {
            "constrained_choice_vocabulary": ["no", "yes"],
            "history_modes": list(HISTORY_MODES),
            "full_prefix_recompute_each_turn": True,
            "kv_cache": False,
            "matched_sampling_uniforms": True,
            "unconstrained_free_form_generation": False,
        },
        "training_performed": False,
        "optimizer_constructed": False,
        "weights_written_or_deleted": False,
        "semantic_promotion_performed": False,
        "predecessor_winner": "none",
    }
    if dry_run:
        return report
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip():
        raise MultiTurnError("Formal execution requires a clean isolated worktree")
    report["runtime"] = _validate_runtime(plan)
    report["gpu_admission"] = _require_idle_gpu()
    first_config = engine.ExperimentConfig.from_json(
        paths["models"]["task"]["path"] / "experiment_config.json"
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
    for model_id in ("task", "semantic"):
        rows, identity, checks = _process_checkpoint(
            model_id,
            paths["models"][model_id]["path"],
            paths["eval"],
            plan,
            device=device,
        )
        report["rows"].extend(rows)
        report["model_identities"][model_id] = identity
        report["model_mechanical_checks"][model_id] = checks
        report["last_completed_model"] = model_id
        atomic_write(paths["output"], report)

    if len(report["rows"]) != int(plan["expected_trajectories"]):
        raise MultiTurnError("Trajectory count did not close")
    turn_count = sum(len(row["turns"]) for row in report["rows"])
    if turn_count != int(plan["expected_turn_rows"]):
        raise MultiTurnError("Turn-row count did not close")
    projection_hashes = {
        identity["scenario_projection_sha256"] for identity in report["model_identities"].values()
    }
    if len(projection_hashes) != 1:
        raise MultiTurnError("Tokenized scenario projections differ across checkpoints")
    all_mechanical = all(
        all(checks.values()) for checks in report["model_mechanical_checks"].values()
    )
    report.update(
        {
            "status": "QUALIFIED_EXECUTION" if all_mechanical else "BLOCKED_EXECUTION",
            "completed_utc": datetime.now(UTC).isoformat(),
            "elapsed_seconds": time.monotonic() - started,
            "trajectory_count": len(report["rows"]),
            "turn_row_count": turn_count,
            "mechanical_execution_qualified": all_mechanical,
            "summary": _summarize(report["rows"]),
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
        raise MultiTurnError("Plan must stay inside the repository") from exc
    plan = load_json(plan_path)
    output = resolve_inside(root, plan["output"], label="output")
    if output.exists():
        raise MultiTurnError(f"Output already exists: {output}")
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
                    "weights_written_or_deleted": False,
                    "semantic_promotion_performed": False,
                }
            )
            atomic_write(output, prior)
        raise
    printable = {key: value for key, value in report.items() if key != "rows"}
    print(json.dumps(printable, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
