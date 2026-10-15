#!/usr/bin/env python3
"""Test a retained checkpoint direction at the native Mistral cache boundary."""

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

from run_v11_gate0 import flatten_functional_batch  # noqa: E402
from v13_visibility_trace import (  # noqa: E402
    answer_positions,
    capture_loaded_batch,
    checkpoint_inventory,
)

from latent_workspace_ft_v10 import engine  # noqa: E402
from latent_workspace_ft_v10.cache_binding import (  # noqa: E402
    ActivationPulse,
    MistralDynamicCacheAdapter,
)

PLAN_PATH = REPO / "configs/v14/CHECKPOINT_DIRECTION_GATE_PLAN.json"


class DirectionGateError(RuntimeError):
    """Raised when the frozen native-direction contract cannot be executed."""


def _digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _tensor_hash(value: torch.Tensor) -> str:
    raw = value.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes()
    return hashlib.sha256(raw).hexdigest()


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


def _source_identity(plan: dict[str, Any]) -> dict[str, str]:
    paths = plan.get("source_identity")
    if not isinstance(paths, dict) or not paths:
        raise DirectionGateError("Frozen source identity must be a nonempty mapping")
    observed: dict[str, str] = {}
    for relative in paths:
        path = REPO / relative
        if not path.is_file() or path.is_symlink():
            raise DirectionGateError(f"Source identity target is not a regular file: {relative}")
        observed[relative] = _digest(path)
    return observed


def _require_idle_gpu() -> str:
    result = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        raise DirectionGateError("GPU already has compute clients; refusing to interfere")
    return "NO_COMPUTE_CLIENTS_AT_CHECK"


def _runtime() -> dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "torch": str(torch.__version__),
        "transformers": version("transformers"),
        "cuda": torch.version.cuda,
    }


def _validate_plan(plan: dict[str, Any]) -> None:
    expected = {
        "format": "latent-workspace-v14-checkpoint-direction-gate-plan-v1",
        "frozen_before_target_model_scoring": True,
        "input_lane": "retained_inline_checkpoint_compatibility",
        "max_worlds": 2,
        "expected_rows": 32,
        "world_selection": "first_n_complete_records_in_file_order",
        "modes": ["intact", "counterfactual_twin"],
    }
    mismatches = {
        key: {"observed": plan.get(key), "expected": value}
        for key, value in expected.items()
        if plan.get(key) != value
    }
    pulse = plan.get("pulse", {})
    pulse_expected = {
        "layer": 16,
        "boundary": "decoder_layer_input_pre_rmsnorm",
        "composition_dtype": "fp32_add_then_cast_to_hidden",
        "amplitude": "natural_vector_rms_no_gain",
        "directions": ["intact_update", "twin_update", "twin_minus_intact"],
    }
    for key, value in pulse_expected.items():
        if pulse.get(key) != value:
            mismatches[f"pulse.{key}"] = {"observed": pulse.get(key), "expected": value}
    gates = plan.get("mechanical_gates", {})
    gate_expected = {
        "all_direction_vectors_finite_nonzero": True,
        "all_pulses_applied_once": True,
        "all_native_cast_deltas_nonzero": True,
        "all_actual_projections_follow_requested_sign": True,
        "all_direction_caches_differ_from_base": True,
        "all_intact_twin_caches_are_distinct": True,
        "frozen_row_count_complete": True,
        "all_inputs_and_parameters_unchanged": True,
    }
    if gates != gate_expected:
        mismatches["mechanical_gates"] = {"observed": gates, "expected": gate_expected}
    authorized = {
        "checkpoint_load": True,
        "checkpoint_direction_capture": True,
        "native_cache_pulse": True,
        "optimizer_or_training": False,
        "free_generation": False,
        "model_download": False,
        "weight_write_or_delete": False,
        "amplitude_layer_or_row_selection": False,
        "semantic_success_claim": False,
    }
    if plan.get("authorized_actions") != authorized:
        mismatches["authorized_actions"] = {
            "observed": plan.get("authorized_actions"),
            "expected": authorized,
        }
    if mismatches:
        raise DirectionGateError(f"Frozen plan contract mismatch: {mismatches}")


def _direction_stats(value: torch.Tensor) -> dict[str, Any]:
    vector = value.detach().float().cpu().contiguous()
    finite = bool(torch.isfinite(vector).all())
    l2 = float(torch.linalg.vector_norm(vector).item()) if finite else float("nan")
    rms = float(torch.sqrt(torch.mean(vector * vector)).item()) if finite else float("nan")
    return {
        "shape": list(vector.shape),
        "source_dtype": str(value.dtype),
        "analysis_dtype": str(vector.dtype),
        "finite": finite,
        "nonzero": bool(finite and torch.count_nonzero(vector).item() > 0),
        "nonzero_elements": int(torch.count_nonzero(vector).item()) if finite else 0,
        "l2": l2,
        "rms": rms,
        "max_abs": float(vector.abs().max().item()) if finite else float("nan"),
        "sha256": _tensor_hash(vector),
    }


def _compact_difference(value: dict[str, Any]) -> dict[str, Any]:
    changed_layers = [
        int(row["layer"])
        for row in value["per_layer"]
        if row["key_nonzero"] or row["value_nonzero"]
    ]
    return {
        "aggregate_l2": float(value["aggregate_l2"]),
        "aggregate_max_abs": float(value["aggregate_max_abs"]),
        "nonzero_count": int(value["nonzero_count"]),
        "exact_equal": bool(value["exact_equal"]),
        "changed_layers": changed_layers,
        "first_changed_layer": None if not changed_layers else changed_layers[0],
        "last_changed_layer": None if not changed_layers else changed_layers[-1],
    }


def _candidate_readout(
    logits: torch.Tensor,
    candidate_ids: list[int],
    *,
    original_label: int,
    donor_label: int,
) -> dict[str, Any]:
    selected = logits[0, -1, torch.tensor(candidate_ids, device=logits.device)].float().cpu()
    if len(selected) != 2 or not bool(torch.isfinite(selected).all()):
        raise DirectionGateError("Candidate readout must contain two finite logits")
    tie = bool(selected[0] == selected[1])
    prediction = None if tie else int(torch.argmax(selected).item())
    donor_margin = (
        0.0
        if donor_label == original_label
        else float((selected[donor_label] - selected[original_label]).item())
    )
    return {
        "candidate_logits": selected.tolist(),
        "prediction": prediction,
        "tie": tie,
        "original_label": original_label,
        "donor_label": donor_label,
        "original_margin": float((selected[original_label] - selected[1 - original_label]).item()),
        "donor_margin": donor_margin,
    }


def _pulse_step(
    adapter: MistralDynamicCacheAdapter,
    base_cache: Any,
    token: torch.Tensor,
    total_length: int,
    direction: torch.Tensor | None,
    *,
    layer: int,
    boundary: str,
    composition_dtype: str,
) -> Any:
    pulse = None
    if direction is not None:
        stats = _direction_stats(direction)
        if not stats["finite"] or not stats["nonzero"] or stats["rms"] <= 0.0:
            raise DirectionGateError("Refusing a zero or nonfinite checkpoint direction")
        pulse = ActivationPulse(
            layer_index=layer,
            direction=direction,
            scale=stats["rms"],
            boundary=boundary,
            composition_dtype=composition_dtype,
        )
    device = token.device
    return adapter.step(
        token,
        adapter.clone(base_cache),
        torch.ones((1, total_length), device=device, dtype=torch.long),
        torch.tensor([[total_length - 1]], device=device, dtype=torch.long),
        pulse=pulse,
    )


def _row_gate(row: dict[str, Any]) -> dict[str, bool]:
    pulse_receipts = row["pulse_receipts"]
    differences = row["cache_differences"]
    return {
        "all_direction_vectors_finite_nonzero": all(
            stats["finite"] and stats["nonzero"] for stats in row["directions"].values()
        ),
        "all_pulses_applied_once": all(
            receipt["applied"] and receipt["call_count"] == 1 for receipt in pulse_receipts.values()
        ),
        "all_native_cast_deltas_nonzero": all(
            receipt["actual_delta_rms"] > 0.0 for receipt in pulse_receipts.values()
        ),
        "all_actual_projections_follow_requested_sign": all(
            receipt["actual_signed_projection"] > 0.0 for receipt in pulse_receipts.values()
        ),
        "all_direction_caches_differ_from_base": all(
            not differences[name]["exact_equal"]
            for name in ("base_vs_intact", "base_vs_twin", "base_vs_semantic_delta")
        ),
        "all_intact_twin_caches_are_distinct": not differences["intact_vs_twin"]["exact_equal"],
    }


def _aggregate_descriptive(rows: list[dict[str, Any]]) -> dict[str, Any]:
    affected = [row for row in rows if row["affected"]]
    donor_changes = [
        row["readouts"]["twin"]["donor_margin"] - row["readouts"]["intact"]["donor_margin"]
        for row in affected
    ]
    return {
        "rows": len(rows),
        "affected_rows": len(affected),
        "unaffected_rows": len(rows) - len(affected),
        "twin_minus_intact_donor_margin": {
            "count": len(donor_changes),
            "positive": sum(value > 0.0 for value in donor_changes),
            "zero": sum(value == 0.0 for value in donor_changes),
            "negative": sum(value < 0.0 for value in donor_changes),
            "mean": (None if not donor_changes else sum(donor_changes) / len(donor_changes)),
            "qualification_role": "DESCRIPTIVE_ONLY_NOT_A_GATE",
        },
        "semantic_delta_rms": {
            "minimum": min(row["directions"]["twin_minus_intact"]["rms"] for row in rows),
            "maximum": max(row["directions"]["twin_minus_intact"]["rms"] for row in rows),
            "mean": sum(row["directions"]["twin_minus_intact"]["rms"] for row in rows) / len(rows),
        },
    }


def run(plan: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    started = time.monotonic()
    _validate_plan(plan)
    if output_dir.exists():
        raise DirectionGateError("Output directory already exists")
    output_dir.mkdir(parents=True)
    if _source_identity(plan) != plan["source_identity"]:
        raise DirectionGateError("Frozen source identity mismatch")
    atomic_path = REPO / plan["predecessor_atomic_report"]["path"]
    if _digest(atomic_path) != plan["predecessor_atomic_report"]["sha256"]:
        raise DirectionGateError("Atomic instrument report hash mismatch")
    atomic = json.loads(atomic_path.read_text(encoding="utf-8"))
    if (
        atomic.get("status") != "QUALIFIED"
        or atomic.get("renderer_and_choice_instrument_qualified") is not True
        or atomic.get("full_context_task_qualified") is not False
    ):
        raise DirectionGateError("Required qualified atomic instrument boundary is absent")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True).strip():
        raise DirectionGateError("Run requires a clean isolated worktree")
    gpu_admission = _require_idle_gpu()
    observed_env = {key: os.environ.get(key) for key in plan["required_environment"]}
    if observed_env != plan["required_environment"]:
        raise DirectionGateError(f"Runtime environment mismatch: {observed_env}")
    runtime = _runtime()
    if runtime != plan["expected_runtime"]:
        raise DirectionGateError(f"Runtime mismatch: {runtime}")
    if not torch.cuda.is_available():
        raise DirectionGateError("CUDA is required")
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
        raise DirectionGateError("Checkpoint must be an existing non-symlink absolute directory")
    if _digest(checkpoint / "manifest.json") != plan["checkpoint"]["manifest_sha256"]:
        raise DirectionGateError("Checkpoint manifest hash mismatch")
    if _digest(checkpoint / "workspace_state.pt") != plan["checkpoint"]["workspace_sha256"]:
        raise DirectionGateError("Checkpoint workspace hash mismatch")
    if _digest(eval_path) != plan["eval"]["sha256"]:
        raise DirectionGateError("Evaluation file hash mismatch")
    inventory_before = checkpoint_inventory(checkpoint)

    config = engine.ExperimentConfig.from_json(checkpoint / "experiment_config.json")
    if (
        config.model.train_mode != "full"
        or config.functional.route_mode != "inline_sidecar"
        or config.functional.reader_steps != 1
    ):
        raise DirectionGateError("Checkpoint is not the admitted full inline-sidecar reader-1 lane")
    engine.require_cuda_allocator_policy(config.train)
    engine.configure_runtime_math(config.train)
    engine.set_global_seed(plan["seed"])
    device = engine.resolve_device("cuda")
    model, tokenizer, loaded_config = engine.load_bundle(checkpoint, device=device)
    precision = engine.resolve_mixed_precision(config.train.mixed_precision, device)
    dataset = engine.JsonlFineTuningDataset([str(eval_path)], tokenizer, loaded_config.data)
    if len(dataset) < plan["max_worlds"]:
        raise DirectionGateError("Evaluation dataset contains too few complete worlds")
    collator = engine.CausalFineTuningCollator(
        int(tokenizer.pad_token_id), config.data.pad_to_multiple_of
    )
    base_model = model.base_model.eval()
    adapter = MistralDynamicCacheAdapter(base_model)
    if adapter.hidden_size != plan["model_contract"]["hidden_size"]:
        raise DirectionGateError("Loaded model hidden size differs from frozen contract")
    parameter_dtypes = sorted({str(parameter.dtype) for parameter in base_model.parameters()})
    if parameter_dtypes != [plan["model_contract"]["dtype"]]:
        raise DirectionGateError(
            f"Loaded base dtype differs from frozen contract: {parameter_dtypes}"
        )
    identities = {
        name: (id(parameter), parameter._version, parameter.dtype, parameter.requires_grad)
        for name, parameter in model.named_parameters()
    }
    rows: list[dict[str, Any]] = []
    pulse = plan["pulse"]
    for world_index in range(plan["max_worlds"]):
        print(f"checkpoint direction world {world_index + 1}/{plan['max_worlds']}", flush=True)
        cpu_batch = collator([dataset[world_index]])
        batch = engine.move_batch_to_device(cpu_batch, device)
        captured = capture_loaded_batch(
            model,
            batch,
            modes=plan["modes"],
            gains=(1.0,),
            precision=precision,
            raw_query_limit=0,
            seed=plan["seed"],
        )
        independently_flat = flatten_functional_batch(batch, "inline")
        independent_positions = answer_positions(independently_flat["labels"])
        if not torch.equal(captured["positions"], independent_positions.cpu()):
            raise DirectionGateError("Independent answer-position projection disagrees")
        flat = captured["flat"]
        intact = captured["captures"]["intact"]["tensors"]["adapter.actual_recovered_delta.answer"]
        twin = captured["captures"]["counterfactual_twin"]["tensors"][
            "adapter.actual_recovered_delta.answer"
        ]
        if intact.shape != twin.shape or intact.shape[1:] != (adapter.hidden_size,):
            raise DirectionGateError("Captured checkpoint direction has an unexpected shape")
        source_record = dataset._read_record(dataset.locations[world_index])
        metadata = source_record.get("metadata", {})
        pair_id = str(metadata.get("pair_id", metadata.get("world_pair_id", world_index)))
        for row_index in range(len(intact)):
            source_position = int(captured["positions"][row_index])
            if source_position < 1 or int(flat["attention_mask"][row_index, source_position]) != 1:
                raise DirectionGateError("Answer source position is not a valid noninitial token")
            prefix_ids = flat["input_ids"][row_index, : source_position + 1].tolist()
            prefix = torch.tensor([prefix_ids], device=device, dtype=torch.long)
            prefill = adapter.prefill(
                prefix[:, :-1],
                torch.ones_like(prefix[:, :-1]),
                torch.arange(source_position, device=device, dtype=torch.long)[None, :],
            )
            base_cache = adapter.clone(prefill.cache)
            token = prefix[:, -1:]
            directions = {
                "intact_update": intact[row_index].float(),
                "twin_update": twin[row_index].float(),
                "twin_minus_intact": twin[row_index].float() - intact[row_index].float(),
            }
            results = {
                "base": _pulse_step(
                    adapter,
                    base_cache,
                    token,
                    len(prefix_ids),
                    None,
                    layer=pulse["layer"],
                    boundary=pulse["boundary"],
                    composition_dtype=pulse["composition_dtype"],
                ),
                "intact": _pulse_step(
                    adapter,
                    base_cache,
                    token,
                    len(prefix_ids),
                    directions["intact_update"],
                    layer=pulse["layer"],
                    boundary=pulse["boundary"],
                    composition_dtype=pulse["composition_dtype"],
                ),
                "twin": _pulse_step(
                    adapter,
                    base_cache,
                    token,
                    len(prefix_ids),
                    directions["twin_update"],
                    layer=pulse["layer"],
                    boundary=pulse["boundary"],
                    composition_dtype=pulse["composition_dtype"],
                ),
                "semantic_delta": _pulse_step(
                    adapter,
                    base_cache,
                    token,
                    len(prefix_ids),
                    directions["twin_minus_intact"],
                    layer=pulse["layer"],
                    boundary=pulse["boundary"],
                    composition_dtype=pulse["composition_dtype"],
                ),
            }
            candidate_ids = [int(value) for value in flat["candidate_ids"][row_index].tolist()]
            original_label = int(flat["answer_classes"][row_index])
            side = int(flat["side_indices"][row_index])
            query = int(flat["query_indices"][row_index])
            donor_label = int(cpu_batch["functional_answer_classes"][0, 1 - side, query])
            cache_differences = {
                "base_vs_intact": _compact_difference(
                    adapter.difference(results["base"].cache, results["intact"].cache)
                ),
                "base_vs_twin": _compact_difference(
                    adapter.difference(results["base"].cache, results["twin"].cache)
                ),
                "base_vs_semantic_delta": _compact_difference(
                    adapter.difference(results["base"].cache, results["semantic_delta"].cache)
                ),
                "intact_vs_twin": _compact_difference(
                    adapter.difference(results["intact"].cache, results["twin"].cache)
                ),
            }
            row = {
                "case_id": f"{pair_id}:side{side}:query{query}",
                "world_index": world_index,
                "pair_id": pair_id,
                "side": side,
                "query_index": query,
                "affected": bool(flat["affected"][row_index]),
                "heldout": bool(flat["heldout"][row_index]),
                "hop_distance": int(flat["hop_distances"][row_index]),
                "source_position": source_position,
                "input_prefix_sha256": _stable_hash(prefix_ids),
                "candidate_ids": candidate_ids,
                "directions": {name: _direction_stats(value) for name, value in directions.items()},
                "pulse_receipts": {
                    "intact_update": _jsonable(results["intact"].pulse),
                    "twin_update": _jsonable(results["twin"].pulse),
                    "twin_minus_intact": _jsonable(results["semantic_delta"].pulse),
                },
                "cache_differences": cache_differences,
                "readouts": {
                    name: _candidate_readout(
                        result.logits,
                        candidate_ids,
                        original_label=original_label,
                        donor_label=donor_label,
                    )
                    for name, result in results.items()
                },
            }
            row["mechanical_gates"] = _row_gate(row)
            rows.append(row)
            del results, base_cache, prefill
        del captured, batch, cpu_batch

    parameter_identity_ok = all(
        identities[name]
        == (id(parameter), parameter._version, parameter.dtype, parameter.requires_grad)
        for name, parameter in model.named_parameters()
    )
    checkpoint_unchanged = checkpoint_inventory(checkpoint) == inventory_before
    eval_unchanged = _digest(eval_path) == plan["eval"]["sha256"]
    source_unchanged = _source_identity(plan) == plan["source_identity"]
    row_gate_names = tuple(plan["mechanical_gates"])
    aggregate_gates: dict[str, bool] = {
        name: all(row["mechanical_gates"][name] for row in rows)
        for name in row_gate_names
        if name not in ("frozen_row_count_complete", "all_inputs_and_parameters_unchanged")
    }
    aggregate_gates["frozen_row_count_complete"] = len(rows) == plan["expected_rows"]
    aggregate_gates["all_inputs_and_parameters_unchanged"] = bool(
        parameter_identity_ok and checkpoint_unchanged and eval_unchanged and source_unchanged
    )
    qualified = bool(rows and all(aggregate_gates.values()))
    return {
        "format": "latent-workspace-v14-checkpoint-direction-gate-v1",
        "status": "QUALIFIED" if qualified else "BLOCKED",
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
        "rows": rows,
        "descriptive_metrics": _aggregate_descriptive(rows),
        "mechanical_gates": aggregate_gates,
        "renderer_and_choice_instrument_qualified": True,
        "checkpoint_direction_native_boundary_qualified": qualified,
        "semantic_effect_qualified": False,
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
            "format": "latent-workspace-v14-checkpoint-direction-gate-v1",
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
                "mechanical_gates": report["mechanical_gates"],
                "descriptive_metrics": report["descriptive_metrics"],
                "elapsed_seconds": report["elapsed_seconds"],
            },
            indent=2,
        ),
        flush=True,
    )
    return 0 if report["status"] == "QUALIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
