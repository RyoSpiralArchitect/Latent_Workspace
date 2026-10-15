#!/usr/bin/env python3
"""Run one source-bound artificial-pulse Mistral K/V trajectory canary."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import torch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from run_v14_portability_canary import (  # noqa: E402
    _cuda_peak_memory,
    _digest,
    _observed_runtime,
    _snapshot_files,
    _stat,
    check_inventory,
)
from v14_cache_trajectory_metrics import (  # noqa: E402
    BOOTSTRAP_DRAWS,
    BOOTSTRAP_SEED,
    mechanical_return_gate,
    semantic_qualification,
    summarize,
)

from latent_workspace_ft_v10.cache_binding import (  # noqa: E402
    ActivationPulse,
    MistralDynamicCacheAdapter,
)
from latent_workspace_ft_v10.implementation_identity import implementation_fingerprint  # noqa: E402

PLAN_PATH = REPO / "configs/v14/CACHE_TRAJECTORY_PLAN.json"
SOURCE_SCRIPTS = (
    "scripts/run_v14_cache_trajectory_canary.py",
    "scripts/v14_cache_trajectory_metrics.py",
    "scripts/run_v14_portability_canary.py",
)
CELL_PROTOCOL = {
    "A": ("base", 0, "none", "carry"),
    "B": ("intact", 1, "one_pulse", "carry"),
    "C": ("twin", 1, "one_pulse", "carry"),
    "D": ("intact", 1, "one_pulse", "matched_no_pulse_history_replacement"),
    "E": ("twin", 1, "one_pulse", "matched_no_pulse_history_replacement"),
}


def _validate_plan_contract(plan: dict[str, Any]) -> None:
    expected_pairs = {
        "format": (plan.get("format"), "latent-workspace-v14-cache-trajectory-plan-v1"),
        "frozen_before_target_model_scoring": (
            plan.get("frozen_before_target_model_scoring"),
            True,
        ),
        "model_id": (
            plan.get("model", {}).get("model_id"),
            "mistralai/Mistral-7B-Instruct-v0.3",
        ),
        "model_type": (plan.get("model", {}).get("model_type"), "mistral"),
        "cache_representation": (
            plan.get("model", {}).get("expected_cache", {}).get("representation"),
            "dynamic_cache_iterator_triples_no_sliding",
        ),
        "pulse_kind": (
            plan.get("pulse", {}).get("kind"),
            "equal_norm_random_sign_pair",
        ),
        "pulse_semantic": (plan.get("pulse", {}).get("semantic"), False),
        "pulse_normalization": (
            plan.get("pulse", {}).get("direction_normalization"),
            "unit_rms",
        ),
        "pulse_layer": (plan.get("pulse", {}).get("layer"), 16),
        "pulse_horizon": (plan.get("pulse", {}).get("horizon"), 0),
        "pulse_boundary": (
            plan.get("pulse", {}).get("boundary"),
            "decoder_layer_input_pre_rmsnorm",
        ),
        "pulse_composition": (
            plan.get("pulse", {}).get("composition_dtype"),
            "fp32_add_then_cast_to_hidden",
        ),
        "pulse_orthogonality_enforced": (
            plan.get("pulse", {}).get("orthogonality_enforced"),
            False,
        ),
        "teacher_forced": (plan.get("tokens", {}).get("teacher_forced"), True),
        "free_generation": (plan.get("tokens", {}).get("free_generation"), False),
        "trajectory_cells": (
            plan.get("trajectory", {}).get("cells"),
            list(CELL_PROTOCOL),
        ),
        "trajectory_replacement": (
            plan.get("trajectory", {}).get("replacement"),
            "complete matched-history native K/V cache",
        ),
        "trajectory_transplant": (
            plan.get("trajectory", {}).get("transplant"),
            "complete B cache into matched-history A target",
        ),
        "probe_read_only": (
            plan.get("trajectory", {}).get("probe_advances_main_trajectory"),
            False,
        ),
        "partial_cache_patches_deferred": (
            plan.get("trajectory", {}).get("k_only_v_only_layer_patch_deferred"),
            True,
        ),
        "metrics_primary": (
            plan.get("metrics", {}).get("primary"),
            ["signed_label1_endpoint", "signed_label1_trapezoid_auc"],
        ),
        "metrics_secondary": (
            plan.get("metrics", {}).get("secondary"),
            ["floor_guarded_absolute_amplification_ratio"],
        ),
        "metrics_state_kv_separate": (
            plan.get("metrics", {}).get("state_and_kv_displacement_separate"),
            True,
        ),
        "metrics_bootstrap_draws": (
            plan.get("metrics", {}).get("bootstrap_draws"),
            BOOTSTRAP_DRAWS,
        ),
        "metrics_bootstrap_seed": (
            plan.get("metrics", {}).get("bootstrap_seed"),
            BOOTSTRAP_SEED,
        ),
        "metrics_bootstrap_unit": (
            plan.get("metrics", {}).get("bootstrap_unit"),
            "family_cluster",
        ),
        "semantic_thresholds_not_frozen": (
            plan.get("semantic_threshold_placeholder", {}).get(
                "frozen_before_measurement"
            ),
            False,
        ),
    }
    mismatches = {
        name: {"observed": observed, "expected": expected}
        for name, (observed, expected) in expected_pairs.items()
        if observed != expected
    }
    tokens = plan.get("tokens", {})
    horizons = plan.get("trajectory", {}).get("horizons")
    expected_horizons = list(range(len(tokens.get("continuation_ids", [])) + 1))
    if horizons != expected_horizons:
        mismatches["trajectory_horizons"] = {
            "observed": horizons,
            "expected": expected_horizons,
        }
    endpoint = plan.get("metrics", {}).get("endpoint_horizon")
    if not expected_horizons or endpoint != expected_horizons[-1]:
        mismatches["metrics_endpoint_horizon"] = {
            "observed": endpoint,
            "expected": expected_horizons[-1] if expected_horizons else None,
        }
    pulse = plan.get("pulse", {})
    if type(pulse.get("scale")) not in (int, float) or pulse.get("scale", 0) <= 0:
        mismatches["pulse_scale"] = {"observed": pulse.get("scale"), "expected": "> 0"}
    tolerance = pulse.get("actual_rms_absolute_tolerance")
    if type(tolerance) not in (int, float) or tolerance <= 0:
        mismatches["pulse_actual_rms_absolute_tolerance"] = {
            "observed": tolerance,
            "expected": "> 0",
        }
    floor = plan.get("metrics", {}).get("frozen_floor")
    if type(floor) not in (int, float) or floor <= 0:
        mismatches["metrics_frozen_floor"] = {
            "observed": floor,
            "expected": "> 0",
        }
    expected_authorized = {
        "target_model_load": True,
        "fixed_teacher_forced_forward": True,
        "native_cache_clone_replace_transplant": True,
        "optimizer_or_training": False,
        "heldout_open": False,
        "free_generation": False,
        "model_download": False,
        "weight_write_or_delete": False,
        "automatic_retry_or_sweep": False,
        "semantic_launch": False,
    }
    if plan.get("authorized_actions") != expected_authorized:
        mismatches["authorized_actions"] = {
            "observed": plan.get("authorized_actions"),
            "expected": expected_authorized,
        }
    if mismatches:
        raise ValueError(f"Frozen plan contract mismatch: {mismatches}")


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, torch.Tensor):
        return value.detach().cpu().tolist()
    return value


def _source_identity() -> dict[str, Any]:
    scripts = [REPO / relative for relative in SOURCE_SCRIPTS]
    if any(not path.is_file() or path.is_symlink() for path in scripts):
        raise ValueError("Frozen cache-trajectory source set must be regular local files")
    return {
        "package": implementation_fingerprint(),
        "source_manifest_sha256": _digest(
            REPO / "src/latent_workspace_ft_v10/source_manifest.json"
        ),
        "scripts": {str(path.relative_to(REPO)): _digest(path) for path in scripts},
    }


def _snapshot_inventory(path: Path, byte_limit: int) -> list[dict[str, Any]]:
    files = _snapshot_files(path)
    if not files or len(files) > 128 or not any(item.suffix == ".safetensors" for item in files):
        raise ValueError("Expected bounded safetensors snapshot")
    if sum(item.stat().st_size for item in files) > byte_limit:
        raise ValueError("Snapshot exceeds frozen byte limit")
    rows = []
    for item in files:
        before = _stat(item)
        digest = _digest(item)
        if _stat(item) != before:
            raise ValueError("Snapshot changed during pre-run hashing")
        rows.append({"path": str(item.relative_to(path)), **before, "sha256": digest})
    return rows


def _content_anchor(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: row[key] for key in ("path", "bytes", "sha256")} for row in rows]


def _tensor_sha256(value: torch.Tensor) -> str:
    raw = value.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes()
    return hashlib.sha256(raw).hexdigest()


def _candidate_logits(logits: torch.Tensor, candidate_ids: list[int]) -> list[float]:
    if logits.ndim == 3:
        logits = logits[:, -1, :]
    if logits.ndim != 2 or logits.shape[0] != 1:
        raise ValueError("Expected one batch row of last-token logits")
    selected = logits[0, torch.tensor(candidate_ids, device=logits.device)]
    if not bool(torch.isfinite(selected).all()):
        raise ValueError("Nonfinite candidate logits")
    return selected.float().cpu().tolist()


def _full_logit_l2(left: torch.Tensor, right: torch.Tensor) -> float:
    if left.shape != right.shape:
        raise ValueError("Logit displacement shape mismatch")
    delta = left.detach().float() - right.detach().float()
    if not bool(torch.isfinite(delta).all()):
        raise ValueError("Nonfinite logit displacement")
    return float(delta.norm())


def _difference_l2(receipt: Any) -> float:
    value = _jsonable(receipt)
    for key in ("l2", "l2_fp32", "total_l2", "aggregate_l2"):
        if isinstance(value, dict) and type(value.get(key)) in (int, float):
            return float(value[key])
    raise ValueError("Cache difference receipt exposes no aggregate L2")


def _model_config_projection(config: Any) -> dict[str, Any]:
    rope_parameters = dict(config.rope_parameters)
    return {
        "model_type": str(config.model_type),
        "hidden_size": int(config.hidden_size),
        "intermediate_size": int(config.intermediate_size),
        "num_hidden_layers": int(config.num_hidden_layers),
        "num_attention_heads": int(config.num_attention_heads),
        "num_key_value_heads": int(config.num_key_value_heads),
        "head_dim": int(config.head_dim),
        "rms_norm_eps": float(config.rms_norm_eps),
        "rope_parameters": {
            "rope_theta": float(rope_parameters["rope_theta"]),
            "rope_type": str(rope_parameters["rope_type"]),
        },
        "max_position_embeddings": int(config.max_position_embeddings),
        "sliding_window": config.sliding_window,
        "attention_implementation_requested": str(config._attn_implementation),
    }


def _snapshot_regions(
    base: Any,
    changed: Any,
    *,
    pulse_layer: int,
) -> dict[str, bool]:
    if base.seq_length != changed.seq_length or len(base.layers) != len(changed.layers):
        raise ValueError("Snapshot layouts differ in structural pulse check")
    prior_exact = True
    lower_current_exact = True
    selected_current_changed = False
    for layer, ((base_key, base_value), (other_key, other_value)) in enumerate(
        zip(base.layers, changed.layers, strict=True)
    ):
        for base_tensor, other_tensor in (
            (base_key, other_key),
            (base_value, other_value),
        ):
            prior_exact = prior_exact and bool(
                torch.equal(base_tensor[..., :-1, :], other_tensor[..., :-1, :])
            )
            if layer < pulse_layer:
                lower_current_exact = lower_current_exact and bool(
                    torch.equal(base_tensor[..., -1, :], other_tensor[..., -1, :])
                )
            if layer == pulse_layer:
                selected_current_changed = selected_current_changed or not bool(
                    torch.equal(base_tensor[..., -1, :], other_tensor[..., -1, :])
                )
    return {
        "all_prior_positions_exact": prior_exact,
        "layers_below_pulse_current_position_exact": lower_current_exact,
        "selected_layer_current_position_changed": selected_current_changed,
    }


def _future_position_structure(difference: dict[str, Any], pulse_layer: int) -> dict[str, bool]:
    layers = difference["per_layer"]
    lower_through_selected_exact = all(
        layer[f"{kind}_last_position_l2"] == 0.0
        for layer in layers[: pulse_layer + 1]
        for kind in ("key", "value")
    )
    above_selected_changed = any(
        layer[f"{kind}_last_position_l2"] > 0.0
        for layer in layers[pulse_layer + 1 :]
        for kind in ("key", "value")
    )
    return {
        "layers_through_pulse_new_position_exact": lower_through_selected_exact,
        "layer_above_pulse_new_position_changed": above_selected_changed,
    }


def _stored_position_stable(initial: Any, final: Any, position: int) -> bool:
    if len(initial.layers) != len(final.layers):
        return False
    return all(
        torch.equal(first[..., position, :], second[..., position, :])
        for initial_pair, final_pair in zip(initial.layers, final.layers, strict=True)
        for first, second in zip(initial_pair, final_pair, strict=True)
    )


def _full_recompute_receipt(
    model: Any,
    history: list[int],
    cached_logits: torch.Tensor,
    candidate_ids: list[int],
) -> dict[str, Any]:
    device = cached_logits.device
    input_ids = torch.tensor([history], device=device, dtype=torch.long)
    positions = torch.arange(len(history), device=device, dtype=torch.long).unsqueeze(0)
    mask = torch.ones_like(input_ids)
    output = model(
        input_ids=input_ids,
        attention_mask=mask,
        position_ids=positions,
        past_key_values=None,
        use_cache=False,
    )
    recomputed = output.logits[:, -1:, :]
    delta = cached_logits.detach().float() - recomputed.detach().float()
    return {
        "history_length": len(history),
        "cache_returned": getattr(output, "past_key_values", None) is not None,
        "exact_equal": bool(torch.equal(cached_logits, recomputed)),
        "l2": float(torch.linalg.vector_norm(delta).item()),
        "max_abs": float(delta.abs().max().item()),
        "cached_candidate_logits": _candidate_logits(cached_logits, candidate_ids),
        "recomputed_candidate_logits": _candidate_logits(recomputed, candidate_ids),
        "comparison_role": "CROSS_SHAPE_DIAGNOSTIC_NOT_AN_EXACT_CLONE_GATE",
    }


def _row(
    *,
    horizon: int,
    histories: dict[str, list[int]],
    logits: dict[str, torch.Tensor],
    differences: dict[str, Any],
    pulse_norm: float,
    reference_norm: float,
    equal_norm_tolerance: float,
    equal_norm_verified: bool,
    candidate_ids: list[int],
    fixed_query_ids: list[int],
) -> dict[str, Any]:
    cells = {}
    for name, (kind, count, forcing, history_mode) in CELL_PROTOCOL.items():
        token_ids = list(histories[name])
        cells[name] = {
            "intervention_kind": kind,
            "pulse_count": count,
            "forcing_mode": forcing,
            "history_mode": history_mode,
            "candidate_logits": _candidate_logits(logits[name], candidate_ids),
            "token_ids": token_ids,
            "position_ids": list(range(len(token_ids))),
            "attention_mask": [1] * len(token_ids),
            "state_displacement": _full_logit_l2(logits[name], logits["A"]),
            "kv_displacement": 0.0 if name == "A" else _difference_l2(differences[name]),
        }
    return {
        "family_id": "v14t-mechanical-family-00",
        "probe_id": "fixed-no-yes-readout",
        "query_id": "fixed-engineering-prefix",
        "horizon": horizon,
        "original_label": 0,
        "donor_label": 0,
        "affected": False,
        "query_token_ids": list(fixed_query_ids),
        "probe_token_ids": list(candidate_ids),
        "pulse_horizon": 0,
        "fixed_continuation": True,
        "probe_is_read_only": True,
        "direction": {
            "kind": "equal_norm_random",
            "direction_id": "seed1413-rms1-sign-pair",
            "pulse_norm": pulse_norm,
            "reference_norm": reference_norm,
            "equal_norm_tolerance": equal_norm_tolerance,
            "equal_norm_verified": equal_norm_verified,
        },
        "cells": cells,
        "measurement_definitions": {
            "state_displacement": "full-vocabulary output-logit L2 versus cell A",
            "kv_displacement": "all-layer native K/V L2 versus cell A",
            "candidate_order": ["no", "yes"],
            "semantic_direction": False,
        },
    }


def run(args: argparse.Namespace) -> int:
    args.output_dir.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report: dict[str, Any] = {
        "format": "latent-workspace-v14-cache-trajectory-canary-v1",
        "status": "RUNNING",
        "started_utc": datetime.now(UTC).isoformat(),
        "training_performed": False,
        "optimizer_constructed": False,
        "free_generation_performed": False,
        "heldout_opened": False,
        "semantic_direction_used": False,
        "semantic_success": False,
        "automatic_retry_permitted": False,
        "amplitude_or_layer_sweep_permitted": False,
        "claim_boundary": (
            "Artificial one-pulse native K/V write/carry/replacement/transplant canary only. "
            "No learned workspace, semantic amplification, capability or generalization claim."
        ),
    }
    plan: dict[str, Any] | None = None
    model = None
    metrics: dict[str, Any] | None = None
    before = None
    snapshot_path = None
    rows: list[dict[str, Any]] = []
    cuda_started = False
    execution_finished = False
    structural_checks: dict[str, bool] = {}
    parameter_identity_ok = False
    try:
        plan = json.loads(PLAN_PATH.read_text())
        _validate_plan_contract(plan)
        report["frozen_plan_contract_valid"] = True
        report["plan_sha256"] = _digest(PLAN_PATH)
        report["source_identity"] = _source_identity()
        if report["source_identity"] != plan["source_identity"]:
            raise ValueError("Frozen source identity mismatch")
        if subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True).strip():
            raise ValueError("Run requires a clean isolated worktree")
        report["commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip()
        required_environment = plan["required_environment"]
        observed_environment = {
            key: os.environ.get(key) for key in required_environment
        }
        if observed_environment != required_environment:
            raise ValueError(
                f"Environment differs from frozen plan: {observed_environment}"
            )
        report["environment"] = observed_environment
        actual_runtime = {
            "torch": str(torch.__version__),
            "transformers": version("transformers"),
            "python": sys.version.split()[0],
            "cuda": torch.version.cuda,
        }
        if actual_runtime != plan["expected_runtime"]:
            raise ValueError(f"Runtime differs from frozen plan: {actual_runtime}")
        if not torch.cuda.is_available():
            raise ValueError("CUDA required")
        torch.set_num_threads(plan["cpu_threads"])
        torch.set_num_interop_threads(plan["cpu_threads"])
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.set_float32_matmul_precision("highest")
        torch.cuda.set_per_process_memory_fraction(plan["cuda_allocator_fraction"])
        torch.cuda.reset_peak_memory_stats()
        cuda_started = True
        report["runtime"] = _observed_runtime("cuda", "sdpa")

        model_plan = plan["model"]
        snapshot_path = Path(model_plan["snapshot"])
        if snapshot_path.name != model_plan["revision"]:
            raise ValueError("Snapshot revision path mismatch")
        before = _snapshot_inventory(snapshot_path, model_plan["max_snapshot_bytes"])
        if _content_anchor(before) != model_plan["snapshot_content_anchor"]:
            raise ValueError("Snapshot differs from frozen prelaunch content anchor")
        from transformers import AutoModelForCausalLM, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            str(snapshot_path), local_files_only=True, trust_remote_code=False
        )
        prefix_ids = tokenizer.encode(plan["tokens"]["prefix_text"], add_special_tokens=True)
        continuation_ids = tokenizer.encode(
            plan["tokens"]["continuation_text"], add_special_tokens=False
        )
        candidate_tokenizations = [
            tokenizer.encode(choice, add_special_tokens=False)
            for choice in plan["tokens"]["candidate_suffixes"]
        ]
        candidate_ids = [tokens[0] for tokens in candidate_tokenizations if len(tokens) == 1]
        if (
            prefix_ids != plan["tokens"]["prefix_ids"]
            or continuation_ids != plan["tokens"]["continuation_ids"]
            or candidate_ids != plan["tokens"]["candidate_ids"]
            or any(len(tokens) != 1 for tokens in candidate_tokenizations)
        ):
            raise ValueError("Frozen tokenizer projection mismatch")
        report["tokenization"] = {
            "prefix_ids": prefix_ids,
            "continuation_ids": continuation_ids,
            "candidate_ids": candidate_ids,
            "all_cells_fixed_teacher_forcing": True,
        }
        model = AutoModelForCausalLM.from_pretrained(
            str(snapshot_path),
            local_files_only=True,
            trust_remote_code=False,
            dtype=torch.bfloat16,
            attn_implementation="sdpa",
        ).to("cuda").eval()
        model_config = _model_config_projection(model.config)
        if model_config != plan["model"]["expected_config"]:
            raise ValueError(f"Model config differs from frozen projection: {model_config}")
        report["model_config"] = model_config
        report["model_parameter_dtypes"] = sorted(
            {str(parameter.dtype) for parameter in model.parameters()}
        )
        identities = {
            name: (id(parameter), parameter._version, parameter.dtype, parameter.requires_grad)
            for name, parameter in model.named_parameters()
        }
        adapter = MistralDynamicCacheAdapter(model)
        report["adapter"] = _jsonable(adapter.describe())
        direction = torch.randn(
            model.config.hidden_size,
            generator=torch.Generator(device="cpu").manual_seed(plan["pulse"]["seed"]),
            dtype=torch.float32,
        )
        direction = direction / direction.square().mean().sqrt()
        if _tensor_sha256(direction) != plan["pulse"]["direction_sha256"]:
            raise ValueError("Frozen direction identity mismatch")
        report["direction"] = {
            "seed": plan["pulse"]["seed"],
            "sha256": _tensor_sha256(direction),
            "rms": float(torch.sqrt(torch.mean(direction * direction)).item()),
            "l2": float(torch.linalg.vector_norm(direction).item()),
            "semantic": False,
            "orthogonality_enforced": False,
            "orthogonality_measured": False,
        }
        direction = direction.to("cuda")

        prefix = torch.tensor([prefix_ids], device="cuda", dtype=torch.long)
        prefix_head, pulse_token = prefix[:, :-1], prefix[:, -1:]
        head_mask = torch.ones_like(prefix_head)
        head_positions = torch.arange(prefix_head.shape[1], device="cuda")[None, :]
        with torch.inference_mode():
            prefill = adapter.prefill(prefix_head, head_mask, head_positions)
            base_cache = adapter.clone(prefill.cache)

            def pulse_step(sign: float | None):
                pulse = None
                if sign is not None:
                    pulse = ActivationPulse(
                        layer_index=plan["pulse"]["layer"],
                        direction=direction,
                        scale=plan["pulse"]["scale"] * sign,
                        boundary=plan["pulse"]["boundary"],
                        composition_dtype=plan["pulse"]["composition_dtype"],
                    )
                return adapter.step(
                    pulse_token,
                    adapter.clone(base_cache),
                    torch.ones((1, len(prefix_ids)), device="cuda", dtype=torch.long),
                    torch.tensor([[len(prefix_ids) - 1]], device="cuda", dtype=torch.long),
                    pulse=pulse,
                )

            initial = {"A": pulse_step(None), "B": pulse_step(1.0), "C": pulse_step(-1.0)}
            snapshots = {
                name: adapter.snapshot(
                    result.cache,
                    token_ids=prefix_ids,
                    position_ids=list(range(len(prefix_ids))),
                    attention_mask=[1] * len(prefix_ids),
                )
                for name, result in initial.items()
            }
            caches = adapter.five_cells(snapshots["A"], snapshots["B"], snapshots["C"])
            current = caches.as_dict()
            logits = {
                "A": initial["A"].logits,
                "B": initial["B"].logits,
                "C": initial["C"].logits,
                "D": initial["B"].logits,
                "E": initial["C"].logits,
            }
            histories = {name: list(prefix_ids) for name in CELL_PROTOCOL}
            differences = {
                name: adapter.difference(current["A"], current[name])
                for name in CELL_PROTOCOL
            }
            initial_differences = differences
            positive_receipt = initial["B"].pulse
            negative_receipt = initial["C"].pulse
            actual_tolerance = float(plan["pulse"]["actual_rms_absolute_tolerance"])
            actual_positive_rms = float(positive_receipt["actual_delta_rms"])
            actual_negative_rms = float(negative_receipt["actual_delta_rms"])
            equal_norm_verified = (
                abs(actual_positive_rms - actual_negative_rms) <= actual_tolerance
                and abs(actual_positive_rms - plan["pulse"]["scale"]) <= actual_tolerance
                and abs(actual_negative_rms - plan["pulse"]["scale"]) <= actual_tolerance
            )
            rows.append(
                _row(
                    horizon=0,
                    histories=histories,
                    logits=logits,
                    differences=differences,
                    pulse_norm=actual_positive_rms,
                    reference_norm=actual_negative_rms,
                    equal_norm_tolerance=actual_tolerance,
                    equal_norm_verified=equal_norm_verified,
                    candidate_ids=candidate_ids,
                    fixed_query_ids=prefix_ids,
                )
            )
            report["pulse_receipts"] = {
                "base": _jsonable(initial["A"].receipt),
                "positive": _jsonable(positive_receipt),
                "negative": _jsonable(negative_receipt),
                "realized_equal_norm_absolute_tolerance": actual_tolerance,
                "realized_equal_norm_verified": equal_norm_verified,
            }
            report["horizon_differences"] = {"0": _jsonable(differences)}
            report["full_recompute_diagnostic"] = {
                "0": _full_recompute_receipt(
                    model, histories["A"], logits["A"], candidate_ids
                )
            }

            pulse_regions = {
                name: _snapshot_regions(
                    snapshots["A"], snapshots[name], pulse_layer=plan["pulse"]["layer"]
                )
                for name in ("B", "C")
            }
            report["pulse_cache_regions"] = pulse_regions
            pulse_position = len(prefix_ids) - 1
            initial_position_fingerprints = {
                name: adapter.position_fingerprints(current[name], pulse_position)
                for name in ("A", "B", "C", "D", "E")
            }
            report["cache_snapshots_horizon_0"] = {
                name: _jsonable(snapshot.to_dict())
                for name, snapshot in snapshots.items()
            }
            report["pulse_position_fingerprints_horizon_0"] = (
                initial_position_fingerprints
            )
            cache_stats = adapter.stats(current["A"])
            report["base_cache_stats_horizon_0"] = cache_stats
            expected_cache = plan["model"]["expected_cache"]
            cache_layout_ok = (
                cache_stats["layer_count"] == model.config.num_hidden_layers
                and cache_stats["seq_length"] == len(prefix_ids)
                and cache_stats["representation"] == expected_cache["representation"]
                and all(
                    row["key_shape"]
                    == [
                        1,
                        expected_cache["num_key_value_heads"],
                        len(prefix_ids),
                        expected_cache["head_dim"],
                    ]
                    and row["value_shape"] == row["key_shape"]
                    and row["key_dtype"] == expected_cache["dtype"]
                    and row["value_dtype"] == expected_cache["dtype"]
                    for row in cache_stats["per_layer"]
                )
            )

            first_token = torch.tensor([[continuation_ids[0]]], device="cuda", dtype=torch.long)
            first_mask = torch.ones((1, len(prefix_ids) + 1), device="cuda", dtype=torch.long)
            first_position = torch.tensor([[len(prefix_ids)]], device="cuda", dtype=torch.long)
            a_next_reference = adapter.step(
                first_token, adapter.restore(snapshots["A"]), first_mask, first_position
            )
            a_next_duplicate = adapter.step(
                first_token, adapter.restore(snapshots["A"]), first_mask, first_position
            )
            b_next_reference = adapter.step(
                first_token, adapter.restore(snapshots["B"]), first_mask, first_position
            )
            transplant = adapter.step(
                first_token,
                adapter.replace(snapshots["A"], snapshots["B"]),
                first_mask,
                first_position,
            )
            duplicate_difference = adapter.difference(
                a_next_reference.cache, a_next_duplicate.cache
            )
            transplant_difference = adapter.difference(
                transplant.cache, b_next_reference.cache
            )
            report["duplicate_a_next_step"] = {
                "logits_exact": bool(
                    torch.equal(a_next_reference.logits, a_next_duplicate.logits)
                ),
                "cache_difference": _jsonable(duplicate_difference),
            }
            report["transplant_next_step"] = {
                "logits_exact_to_B": bool(
                    torch.equal(transplant.logits, b_next_reference.logits)
                ),
                "cache_difference_from_B": _jsonable(transplant_difference),
            }

            continuation_receipts: list[dict[str, Any]] = []
            replacement_future_exact = True
            carried_future_logit_changed = {"B": False, "C": False}
            future_structure: dict[str, dict[str, bool]] | None = None
            for horizon, token in enumerate(continuation_ids, start=1):
                for name in CELL_PROTOCOL:
                    histories[name].append(token)
                    token_tensor = torch.tensor([[token]], device="cuda", dtype=torch.long)
                    mask = torch.ones((1, len(histories[name])), device="cuda", dtype=torch.long)
                    position = torch.tensor([[len(histories[name]) - 1]], device="cuda")
                    result = adapter.step(token_tensor, current[name], mask, position)
                    current[name], logits[name] = result.cache, result.logits
                    continuation_receipts.append(
                        {
                            "horizon": horizon,
                            "cell": name,
                            **_jsonable(result.receipt),
                        }
                    )
                differences = {
                    name: adapter.difference(current["A"], current[name])
                    for name in CELL_PROTOCOL
                }
                report["horizon_differences"][str(horizon)] = _jsonable(differences)
                if horizon == 1:
                    future_structure = {
                        name: _future_position_structure(
                            differences[name], plan["pulse"]["layer"]
                        )
                        for name in ("B", "C")
                    }
                for name in ("B", "C"):
                    carried_future_logit_changed[name] = (
                        carried_future_logit_changed[name]
                        or _full_logit_l2(logits[name], logits["A"]) > 0.0
                    )
                replacement_future_exact = replacement_future_exact and all(
                    differences[name]["exact_equal"]
                    and torch.equal(logits[name], logits["A"])
                    for name in ("D", "E")
                )
                rows.append(
                    _row(
                        horizon=horizon,
                        histories=histories,
                        logits=logits,
                        differences=differences,
                        pulse_norm=actual_positive_rms,
                        reference_norm=actual_negative_rms,
                        equal_norm_tolerance=actual_tolerance,
                        equal_norm_verified=equal_norm_verified,
                        candidate_ids=candidate_ids,
                        fixed_query_ids=prefix_ids,
                    )
                )
                report["full_recompute_diagnostic"][str(horizon)] = (
                    _full_recompute_receipt(
                        model, histories["A"], logits["A"], candidate_ids
                    )
                )

            if future_structure is None:
                raise RuntimeError("Frozen continuation did not produce a future horizon")
            report["future_position_structure_horizon_1"] = future_structure
            final_snapshots = {
                name: adapter.snapshot(current[name]) for name in ("B", "C")
            }
            final_position_fingerprints = {
                name: adapter.position_fingerprints(current[name], pulse_position)
                for name in ("B", "C")
            }
            pulse_position_stable = {
                name: _stored_position_stable(
                    snapshots[name], final_snapshots[name], pulse_position
                )
                for name in ("B", "C")
            }
            report["stored_pulse_position_stable"] = pulse_position_stable
            report["pulse_position_fingerprints_final"] = final_position_fingerprints
            report["carried_future_logits_changed_descriptive_only"] = (
                carried_future_logit_changed
            )
            report["continuation_step_receipts"] = continuation_receipts

            structural_checks = {
                "model_eval_and_bfloat16_parameters": (
                    not model.training
                    and report["model_parameter_dtypes"] == ["torch.bfloat16"]
                ),
                "native_cache_layout_matches_frozen_contract": cache_layout_ok,
                "pulse_hooks_applied_once": all(
                    receipt["applied"] and receipt["call_count"] == 1
                    for receipt in (positive_receipt, negative_receipt)
                ),
                "pulse_native_cast_nonzero": (
                    actual_positive_rms > 0.0 and actual_negative_rms > 0.0
                ),
                "pulse_signed_projection_matches_requested_sign": (
                    positive_receipt["actual_signed_projection"] > 0.0
                    and negative_receipt["actual_signed_projection"] < 0.0
                ),
                "pulse_realized_norms_match_frozen_contract": equal_norm_verified,
                "all_prior_cache_positions_exact_after_pulse": all(
                    item["all_prior_positions_exact"] for item in pulse_regions.values()
                ),
                "lower_layers_current_position_exact_after_pulse": all(
                    item["layers_below_pulse_current_position_exact"]
                    for item in pulse_regions.values()
                ),
                "selected_layer_current_position_changed_after_pulse": all(
                    item["selected_layer_current_position_changed"]
                    for item in pulse_regions.values()
                ),
                "replacement_caches_exact_to_A_at_horizon_0": all(
                    initial_differences[name]["exact_equal"] for name in ("D", "E")
                ),
                "future_new_kv_exact_through_pulse_layer": all(
                    item["layers_through_pulse_new_position_exact"]
                    for item in future_structure.values()
                ),
                "future_new_kv_changed_above_pulse_layer": all(
                    item["layer_above_pulse_new_position_changed"]
                    for item in future_structure.values()
                ),
                "replacement_future_exact_to_A": replacement_future_exact,
                "duplicate_A_next_step_exact": (
                    report["duplicate_a_next_step"]["logits_exact"]
                    and duplicate_difference["exact_equal"]
                ),
                "full_B_cache_transplant_next_step_exact": (
                    report["transplant_next_step"]["logits_exact_to_B"]
                    and transplant_difference["exact_equal"]
                ),
                "stored_pulse_position_exact_after_continuation": all(
                    pulse_position_stable.values()
                )
                and all(
                    initial_position_fingerprints[name]["layers"]
                    == final_position_fingerprints[name]["layers"]
                    for name in ("B", "C")
                ),
                "all_step_inputs_and_cache_prefixes_preserved": all(
                    receipt["token_position_mask_mutated"] is False
                    and receipt["cache_input_mutated"] is False
                    and receipt["cache_prefix_exact"] is True
                    for receipt in continuation_receipts
                )
                and all(
                    result.receipt["token_position_mask_mutated"] is False
                    and result.receipt["cache_input_mutated"] is False
                    and result.receipt["cache_prefix_exact"] is True
                    for result in initial.values()
                )
                and all(
                    receipt["pulse"] == {"applied": False, "call_count": 0}
                    for receipt in continuation_receipts
                ),
                "full_recompute_returned_no_cache": all(
                    item["cache_returned"] is False
                    for item in report["full_recompute_diagnostic"].values()
                ),
            }
            report["structural_checks"] = structural_checks

        (args.output_dir / "trajectory.jsonl").write_text(
            "".join(json.dumps(row, allow_nan=False) + "\n" for row in rows)
        )
        metrics = summarize(
            rows,
            expected_horizons=tuple(plan["trajectory"]["horizons"]),
            endpoint_horizon=plan["metrics"]["endpoint_horizon"],
            frozen_floor=plan["metrics"]["frozen_floor"],
            expected_families=1,
            expected_probes_per_family=1,
            expected_direction_kinds=("equal_norm_random",),
        )
        report["metrics"] = metrics
        report["semantic_qualification"] = semantic_qualification(
            metrics, threshold_plan=plan["semantic_threshold_placeholder"]
        )
        report["cell_name_mapping"] = {
            "metrics_protocol_labels": {
                "B": "intact",
                "C": "twin",
                "D": "intact_then_replaced",
                "E": "twin_then_replaced",
            },
            "this_mechanical_run_meaning": {
                "B": "synthetic_positive_carried",
                "C": "synthetic_negative_carried",
                "D": "synthetic_positive_then_base_cache_replacement",
                "E": "synthetic_negative_then_base_cache_replacement",
            },
            "semantic_intact_or_twin_claimed": False,
        }
        parameter_identity_ok = identities == {
            name: (id(parameter), parameter._version, parameter.dtype, parameter.requires_grad)
            for name, parameter in model.named_parameters()
        }
        report["base_parameter_identity_versions_unchanged"] = parameter_identity_ok
        if not parameter_identity_ok:
            raise ValueError("Base parameter identity/version changed")
        execution_finished = True
        report["status"] = "POSTRUN_VALIDATION_PENDING"
    except Exception as exc:
        report.update(
            status="FAILED",
            error_type=type(exc).__name__,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
    finally:
        snapshot_integrity_ok = False
        if before is not None:
            try:
                report["snapshot_after"] = check_inventory(snapshot_path, before)
                snapshot_integrity_ok = True
            except Exception as exc:
                report.update(status="FAILED", integrity_ok=False, integrity_error=str(exc))
        if cuda_started:
            try:
                torch.cuda.synchronize()
                report["cuda_memory"] = _cuda_peak_memory()
            except Exception as exc:
                report["cuda_memory"] = {
                    "status": "UNKNOWN_CUDA_POSTRUN_ERROR",
                    "error": str(exc),
                }
                report.update(status="FAILED", integrity_ok=False)
        report["elapsed_seconds"] = time.monotonic() - started
        report["trajectory_rows"] = len(rows)
        if execution_finished and plan is not None and metrics is not None:
            try:
                postrun_failed = report["status"] == "FAILED"
                source_integrity_ok = report.get("source_identity") == _source_identity()
                plan_integrity_ok = report.get("plan_sha256") == _digest(PLAN_PATH)
                report["integrity_checks"] = {
                    "snapshot_payloads_unchanged": snapshot_integrity_ok,
                    "source_identity_unchanged": source_integrity_ok,
                    "plan_bytes_unchanged": plan_integrity_ok,
                    "model_parameter_identity_versions_unchanged": parameter_identity_ok,
                }
                integrity_ok = all(report["integrity_checks"].values())
                report["integrity_ok"] = integrity_ok
                peak_allocated = report.get("cuda_memory", {}).get(
                    "peak_allocated_bytes"
                )
                resource_checks = {
                    "elapsed_within_frozen_limit": (
                        report["elapsed_seconds"] <= plan["max_elapsed_seconds"]
                    ),
                    "peak_allocated_within_frozen_limit": (
                        type(peak_allocated) is int
                        and peak_allocated <= plan["peak_allocated_stop_bytes"]
                    ),
                }
                report["resource_checks"] = resource_checks
                instrument_ok = all(structural_checks.values()) and all(
                    resource_checks.values()
                )
                report["mechanical_return_gate"] = mechanical_return_gate(
                    metrics, instrument_ok=instrument_ok, integrity_ok=integrity_ok
                )
                if not postrun_failed:
                    report["status"] = (
                        "COMPLETE"
                        if report["mechanical_return_gate"]["return_allowed"]
                        else "MECHANICAL_GATE_BLOCKED"
                    )
            except Exception as exc:
                report.update(
                    status="FAILED",
                    integrity_ok=False,
                    postrun_error_type=type(exc).__name__,
                    postrun_error=str(exc),
                    postrun_traceback=traceback.format_exc(),
                )
        trajectory = args.output_dir / "trajectory.jsonl"
        if trajectory.is_file():
            report["trajectory_sha256"] = _digest(trajectory)
        (args.output_dir / "report.json").write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n"
        )
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "error": report.get("error"),
                    "rows": len(rows),
                    "output": str(args.output_dir),
                }
            ),
            flush=True,
        )
    return 0 if report["status"] == "COMPLETE" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
