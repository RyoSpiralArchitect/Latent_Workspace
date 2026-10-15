#!/usr/bin/env python3
"""Bounded, read-only retained-inline S1 instrumentation (never a training runner).

Actual tensors are captured with passthrough hooks. Internal SDPA Q/K/V are
captured at the original operation, not reconstructed from attention weights.
The gated update is explicitly labelled a replay of the engine's arithmetic
and checked against the actual reader return. Recomposition/gain sweeps are
descriptive interventions on the SAME captured candidate tensors.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import sys
import threading
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from run_v11_gate0 import flatten_functional_batch  # noqa: E402

from latent_workspace_ft_v10 import engine  # noqa: E402

FORMAT = "latent-workspace-v13-retained-inline-visibility-v1"
MODES = ("intact", "zero", "fixed_carrier", "norm_matched_random", "counterfactual_twin")
_CAPTURE_LOCK = threading.Lock()


class VisibilityError(RuntimeError):
    """An execution or evidence boundary was not satisfied."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def tensor_hash(value: torch.Tensor) -> str:
    value = value.detach().cpu().contiguous()
    header = {"dtype": str(value.dtype), "shape": list(value.shape)}
    digest = hashlib.sha256(json.dumps(header, sort_keys=True).encode())
    digest.update(value.reshape(-1).view(torch.uint8).numpy().tobytes())
    return digest.hexdigest()


def bitwise_equal(left: torch.Tensor, right: torch.Tensor) -> bool:
    return (
        left.shape == right.shape
        and left.dtype == right.dtype
        and torch.equal(
            left.detach().cpu().contiguous().reshape(-1).view(torch.uint8),
            right.detach().cpu().contiguous().reshape(-1).view(torch.uint8),
        )
    )


def answer_positions(labels: torch.Tensor) -> torch.Tensor:
    valid = labels[:, 1:].ne(-100)
    if labels.ndim != 2 or labels.shape[0] == 0 or not bool(valid.sum(1).eq(1).all()):
        raise VisibilityError("Exactly one supervised next-token label per nonempty row required.")
    return valid.long().argmax(1)


def candidates(
    logits: torch.Tensor, positions: torch.Tensor, candidate_ids: torch.Tensor
) -> torch.Tensor:
    if logits.ndim != 3 or candidate_ids.ndim != 2 or len(logits) != len(candidate_ids):
        raise VisibilityError("Candidate tensor shape mismatch.")
    rows = torch.arange(len(logits), device=logits.device)
    return logits[rows, positions.to(logits.device)].gather(1, candidate_ids.to(logits.device))


def recompose_candidates(
    base: torch.Tensor,
    residual: torch.Tensor,
    *,
    gains: Sequence[float] = (1.0,),
) -> dict[str, Any]:
    """No forward rerun: all variants use these exact captured CPU tensors."""
    base, residual = base.detach().cpu(), residual.detach().cpu()
    if base.shape != residual.shape or base.ndim != 2:
        raise VisibilityError("Base/residual candidate shapes differ.")
    if not bool(torch.isfinite(base).all() and torch.isfinite(residual).all()):
        raise VisibilityError("Non-finite candidate tensor.")
    if not gains or any(not math.isfinite(g) or g <= 0 for g in gains):
        raise VisibilityError("Diagnostic gains must be finite and positive.")
    cast = residual.to(base.dtype)
    base_bf16 = base.to(torch.bfloat16)
    positive = torch.full_like(base_bf16, float("inf"))
    negative = torch.full_like(base_bf16, -float("inf"))
    upper = (torch.nextafter(base_bf16, positive).float() - base_bf16.float()).abs()
    lower = (base_bf16.float() - torch.nextafter(base_bf16, negative).float()).abs()
    spacing = torch.where(residual.float().ge(0), upper, lower)
    return {
        "native": base + cast,
        "residual_postcast": cast,
        "bf16": base_bf16 + residual.to(torch.bfloat16),
        "fp32": base.float() + residual.float(),
        "bf16_ulp_up": upper,
        "bf16_ulp_down": lower,
        "residual_to_directional_bf16_ulp": residual.float().abs() / spacing,
        "fp32_diagnostic_gains": {
            format(gain, ".12g"): base.float() + float(gain) * residual.float() for gain in gains
        },
    }


class VisibilityTrace:
    """One wrapper forward, eval-only, reader_steps=1; hooks never replace outputs.

    Primary-path hooks ignore subsequent auxiliary-loss reader/adapter calls.
    Captured answer-position tensors cover every query. Full sequence tensors
    are capped at raw_query_limit rows. SDPA patching is process-global only
    for this context, guarded against nested captures and other-thread capture.
    """

    def __init__(
        self,
        model: engine.LatentWorkspaceCausalLM,
        positions: torch.Tensor,
        candidate_ids: torch.Tensor,
        *,
        raw_query_limit: int = 2,
    ) -> None:
        if model.training or model.functional_config.route_mode != "inline_sidecar":
            raise VisibilityError("Trace requires an eval-mode inline_sidecar wrapper.")
        if model.functional_config.reader_steps != 1 or model.functional_reader.steps != 1:
            raise VisibilityError("S1 trace qualifies exactly one reader step.")
        if raw_query_limit < 0 or raw_query_limit > 8:
            raise VisibilityError("raw_query_limit must be between 0 and 8.")
        self.model = model
        self.positions = positions.detach().cpu()
        self.candidate_ids = candidate_ids.detach().cpu()
        self.raw_query_limit = raw_query_limit
        self.tensors: dict[str, torch.Tensor] = {}
        self.checks: dict[str, Any] = {}
        self.counts = {"base": 0, "writer": 0, "reader": 0, "adapter": 0, "reader_sdpa": 0}
        self.handles: list[Any] = []
        self.references: dict[str, torch.Tensor] = {}
        self.active_reader = False
        self.active_attention = False
        self.active_adapter = False
        self.original_sdpa: Any = None

    def put(self, name: str, value: torch.Tensor) -> None:
        if name in self.tensors:
            raise VisibilityError(f"Duplicate primary capture: {name}")
        self.tensors[name] = value.detach().cpu().contiguous().clone()

    def query(self, name: str, value: torch.Tensor, *, heads: bool = False) -> None:
        rows = torch.arange(len(value), device=value.device)
        pos = self.positions.to(value.device)
        selected = value[rows, :, pos, :] if heads else value[rows, pos]
        self.put(name + ".answer", selected)
        if self.raw_query_limit:
            self.put(name + ".raw_prefix", value[: self.raw_query_limit])

    def _base(self, _module: Any, _args: Any, output: Any) -> None:
        self.counts["base"] += 1
        if self.counts["base"] == 1:
            self.put(
                "base.candidates", candidates(output.logits, self.positions, self.candidate_ids)
            )

    def _writer(self, _module: Any, args: Any, output: Any) -> None:
        self.counts["writer"] += 1
        if self.counts["writer"] == 1:
            self.put("writer.context_mask", args[1])
            self.put("writer.raw_memory", output[0])
            self.put("writer.memory_mask", output[1])
            self.put("writer.trajectory", output[2])
            self.put("writer.anchor", output[3])

    def _reader_pre(self, _module: Any, args: Any) -> None:
        self.counts["reader"] += 1
        self.active_reader = self.counts["reader"] == 1
        if self.active_reader:
            query, mask, memory, memory_mask = args
            self.references.update(query=query, mask=mask)
            self.query("reader.query_input", query)
            self.put("reader.memory_input", memory)
            self.put("reader.memory_mask", memory_mask)

    def _reader_post(self, module: Any, _args: Any, output: Any) -> None:
        if self.active_reader:
            gate = torch.sigmoid(self.references["gate_logits"])
            read = self.references["read"]
            update = module.injection_scale * gate.to(read.dtype) * read
            update = update * self.references["mask"].to(self.references["query"].dtype).unsqueeze(
                -1
            )
            replay = self.references["query"] + update
            self.checks["gated_update_replay_matches_actual_reader_return"] = bool(
                torch.equal(replay, output[0])
            )
            self.checks["gate_replay_matches_actual_summary"] = bool(
                torch.equal(gate.mean(), output[1])
            )
            self.query("reader.gate_replayed", gate)
            self.query("reader.gated_update_replayed", update)
            self.query("reader.actual_return", output[0])
            self.references.clear()
        self.active_reader = False

    def _attention_pre(self, _module: Any, _args: Any) -> None:
        self.active_attention = self.active_reader

    def _attention_post(self, _module: Any, _args: Any, output: Any) -> None:
        if self.active_reader:
            self.references["read"] = output[0]
            self.query("reader.actual_read", output[0])
        self.active_attention = False

    def _gate(self, _module: Any, _args: Any, output: Any) -> None:
        if self.active_reader:
            self.references["gate_logits"] = output
            self.query("reader.gate_logits", output)

    def _memory_norm(self, _module: Any, _args: Any, output: Any) -> None:
        if self.active_reader:
            self.put("reader.actual_learned_memory_norm", output)

    def _query_norm(self, _module: Any, _args: Any, output: Any) -> None:
        if self.active_reader and "reader.actual_query_norm.answer" not in self.tensors:
            self.query("reader.actual_query_norm", output)

    def _memory_projection(self, _module: Any, _args: Any, output: Any) -> None:
        if self.active_reader:
            self.put("reader.memory_projection_before_attention_kv", output)

    def _adapter_pre(self, _module: Any, args: Any) -> None:
        self.counts["adapter"] += 1
        self.active_adapter = self.counts["adapter"] == 1
        if self.active_adapter:
            self.query("adapter.actual_recovered_delta", args[0])

    def _adapter_norm(self, _module: Any, _args: Any, output: Any) -> None:
        if self.active_adapter:
            self.query("adapter.actual_learned_norm", output)

    def _adapter_post(self, _module: Any, _args: Any, output: Any) -> None:
        if self.active_adapter:
            self.put(
                "adapter.candidates_precast", candidates(output, self.positions, self.candidate_ids)
            )
        self.active_adapter = False

    def _sdpa(self, query: Any, key: Any, value: Any, *args: Any, **kwargs: Any) -> Any:
        capture = self.active_attention and threading.get_ident() == self.thread_id
        if capture:
            self.counts["reader_sdpa"] += 1
            self.query("reader.actual_sdpa_q", query, heads=True)
            self.put("reader.actual_sdpa_k", key)
            self.put("reader.actual_sdpa_v", value)
            mask = args[0] if args else kwargs.get("attn_mask")
            if isinstance(mask, torch.Tensor):
                self.put("reader.actual_sdpa_mask", mask)
        result = self.original_sdpa(query, key, value, *args, **kwargs)
        if capture:
            self.query("reader.actual_sdpa_return", result, heads=True)
        return result

    def __enter__(self) -> VisibilityTrace:
        if not _CAPTURE_LOCK.acquire(blocking=False):
            raise VisibilityError("Nested/concurrent visibility capture is not allowed.")
        self.thread_id = threading.get_ident()
        self.original_sdpa = F.scaled_dot_product_attention
        try:
            reader = self.model.functional_reader
            adapter = self.model.functional_sidecar_adapter
            if reader is None or adapter is None or self.model.functional_writer is None:
                raise VisibilityError("Missing functional trace modules.")
            for module, method, pre in (
                (self.model.base_model, self._base, False),
                (self.model.functional_writer, self._writer, False),
                (reader, self._reader_pre, True),
                (reader, self._reader_post, False),
                (reader.attention, self._attention_pre, True),
                (reader.attention, self._attention_post, False),
                (reader.gate, self._gate, False),
                (reader.memory_norm, self._memory_norm, False),
                (reader.query_norm, self._query_norm, False),
                (reader.memory_projection, self._memory_projection, False),
                (adapter, self._adapter_pre, True),
                (adapter, self._adapter_post, False),
                (adapter.norm, self._adapter_norm, False),
            ):
                register = module.register_forward_pre_hook if pre else module.register_forward_hook
                self.handles.append(register(method))
            F.scaled_dot_product_attention = self._sdpa
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_exc: Any) -> None:
        if self.original_sdpa is not None:
            F.scaled_dot_product_attention = self.original_sdpa
        for handle in self.handles:
            handle.remove()
        self.handles.clear()
        self.references.clear()
        _CAPTURE_LOCK.release()

    def finish(self, logits: torch.Tensor, *, mode: str) -> dict[str, Any]:
        self.put(
            "wrapper.actual_candidates", candidates(logits, self.positions, self.candidate_ids)
        )
        legacy = mode == "hard_bypass"
        expected_sdpa = 0 if legacy else 1
        if self.counts["base"] != 1 or self.counts["reader_sdpa"] != expected_sdpa:
            raise VisibilityError(f"Unqualified trace call counts: {self.counts}")
        if self.counts["writer"] != 1 or self.counts["adapter"] < 1:
            raise VisibilityError("Missing writer/adapter primary capture.")
        if not legacy and not all(self.checks.values()):
            raise VisibilityError(f"Reader arithmetic replay failed: {self.checks}")
        if not legacy:
            replayed_delta = (
                self.tensors["reader.actual_return.answer"]
                - self.tensors["reader.query_input.answer"]
            )
            self.checks["answer_delta_matches_actual_adapter_input"] = bitwise_equal(
                replayed_delta, self.tensors["adapter.actual_recovered_delta.answer"]
            )
            if not self.checks["answer_delta_matches_actual_adapter_input"]:
                raise VisibilityError("Reader subtraction does not match actual adapter input.")
        if any(
            not bool(torch.isfinite(t).all()) for k, t in self.tensors.items() if "mask" not in k
        ):
            raise VisibilityError("Non-finite captured tensor.")
        return {
            "counts": dict(self.counts),
            "checks": dict(self.checks),
            "legacy_hard_bypass_is_not_true_amputation": legacy,
            "capture_scope": "all answer rows; full sequence raw_prefix capped",
            "raw_query_limit": self.raw_query_limit,
            "tensors": {
                name: {
                    "shape": list(tensor.shape),
                    "dtype": str(tensor.dtype),
                    "sha256": tensor_hash(tensor),
                }
                for name, tensor in sorted(self.tensors.items())
            },
        }


def checkpoint_inventory(checkpoint: Path) -> list[dict[str, Any]]:
    """Hash all inference payload bytes; never load external base references."""
    for name in ("experiment_config.json", "workspace_state.pt", "base_model", "tokenizer"):
        if not (checkpoint / name).exists():
            raise VisibilityError(f"Missing local checkpoint payload: {name}")
    if not any((checkpoint / "base_model").glob("*.safetensors")):
        raise VisibilityError("Retained checkpoint must have local base safetensors.")
    roots = [checkpoint / name for name in ("base_model", "tokenizer")]
    paths = [checkpoint / "experiment_config.json", checkpoint / "workspace_state.pt"]
    if (checkpoint / "manifest.json").exists():
        paths.append(checkpoint / "manifest.json")
    for root in roots:
        paths.extend(path for path in root.rglob("*") if path.is_file())
    inventory = []
    for path in sorted(paths):
        if path.is_symlink() or not path.resolve().is_relative_to(checkpoint.resolve()):
            raise VisibilityError("Checkpoint payload must be local regular files, not symlinks.")
        inventory.append(
            {
                "path": str(path.relative_to(checkpoint)),
                "bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )
    return inventory


def norm_inventory(model: torch.nn.Module) -> dict[str, Any]:
    return {
        name: {
            "eps": module.eps,
            "normalized_shape": list(module.normalized_shape),
            "weight_sha256": tensor_hash(module.weight) if module.weight is not None else None,
            "bias_sha256": tensor_hash(module.bias) if module.bias is not None else None,
        }
        for name, module in model.named_modules()
        if isinstance(module, torch.nn.LayerNorm) and name.startswith("functional_")
    }


def write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        handle.write("\n")


def capture_loaded_batch(
    model: engine.LatentWorkspaceCausalLM,
    batch: Mapping[str, torch.Tensor],
    *,
    modes: Sequence[str] = MODES,
    gains: Sequence[float] = (1.0,),
    precision: str = "no",
    raw_query_limit: int = 2,
    seed: int = 271828,
) -> dict[str, Any]:
    """Public in-memory API; return bounded CPU captures, never write a checkpoint."""
    flat = flatten_functional_batch(batch, "inline")
    positions = answer_positions(flat["labels"])
    device = flat["input_ids"].device
    kwargs = engine.functional_batch_kwargs(batch)
    kwargs.update(
        compute_workspace_loss=False,
        compute_spectral=False,
        rng_streams=None,
        memory_intervention_seed=seed,
    )
    with torch.no_grad(), engine.autocast_context(device, precision):
        direct = model.base_model(
            input_ids=flat["input_ids"],
            attention_mask=flat["attention_mask"],
            use_cache=False,
            return_dict=True,
        )
        base_candidates = candidates(direct.logits, positions, flat["candidate_ids"]).cpu().clone()
        del direct
        bypass = model._forward_functional_workspace(
            **kwargs, bypass_workspace=True, memory_intervention="intact"
        )
        bypass_candidates = (
            candidates(bypass["logits"], positions, flat["candidate_ids"]).cpu().clone()
        )
        del bypass
        if not bitwise_equal(base_candidates, bypass_candidates):
            raise VisibilityError(
                "Direct base and true bypass differ on identical candidate inputs."
            )
        captures = {}
        for mode in modes:
            if mode not in (*MODES, "hard_bypass"):
                raise VisibilityError(f"Unqualified memory control: {mode}")
            trace = VisibilityTrace(
                model, positions, flat["candidate_ids"], raw_query_limit=raw_query_limit
            )
            with trace:
                output = model._forward_functional_workspace(
                    **kwargs, bypass_workspace=False, memory_intervention=mode
                )
            metadata = trace.finish(output["logits"], mode=mode)
            del output
            if not bitwise_equal(trace.tensors["base.candidates"], base_candidates):
                raise VisibilityError("Captured inline base differs across modes/direct base.")
            recomposed = recompose_candidates(
                trace.tensors["base.candidates"],
                trace.tensors["adapter.candidates_precast"],
                gains=gains,
            )
            if not bitwise_equal(recomposed["native"], trace.tensors["wrapper.actual_candidates"]):
                raise VisibilityError(
                    "Same-tensor native recomposition differs from actual wrapper."
                )
            captures[mode] = {
                "metadata": metadata,
                "tensors": trace.tensors,
                "recomposed": recomposed,
            }
    return {
        "flat": {k: v.detach().cpu() for k, v in flat.items()},
        "positions": positions.cpu(),
        "direct_base": base_candidates,
        "true_bypass": bypass_candidates,
        "captures": captures,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    checkpoint = Path(args.checkpoint).expanduser().resolve()
    eval_path = Path(args.eval_file).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    if output_dir.is_relative_to(checkpoint) or checkpoint.is_relative_to(output_dir):
        raise VisibilityError(
            "Output directory must not contain or be inside the immutable checkpoint."
        )
    if not eval_path.is_file() or not 1 <= args.max_worlds <= 8:
        raise VisibilityError("Explicit eval file and max_worlds between 1 and 8 required.")
    modes = args.modes.split(",")
    gains = [float(value) for value in args.gains.split(",")]
    if len(set(modes)) != len(modes) or "intact" not in modes:
        raise VisibilityError("Unique modes including intact required.")
    if any(mode not in (*MODES, "hard_bypass") for mode in modes):
        raise VisibilityError("Unsupported memory mode.")
    recompose_candidates(torch.zeros(1, 2), torch.zeros(1, 2), gains=gains)
    output_dir.mkdir(parents=True, exist_ok=False)
    args._created_output_dir = str(output_dir)
    print("Hashing immutable checkpoint inference payloads.", flush=True)
    inventory = checkpoint_inventory(checkpoint)
    engine_path = Path(engine.__file__).resolve()
    source_hash = file_sha256(engine_path)
    if args.expected_engine_sha256 and source_hash != args.expected_engine_sha256:
        raise VisibilityError("Engine source hash mismatch.")
    workspace_hash = next(row["sha256"] for row in inventory if row["path"] == "workspace_state.pt")
    if args.expected_workspace_sha256 and workspace_hash != args.expected_workspace_sha256:
        raise VisibilityError("Workspace payload hash mismatch.")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    config = engine.ExperimentConfig.from_json(checkpoint / "experiment_config.json")
    if config.model.train_mode != "full" or config.functional.route_mode != "inline_sidecar":
        raise VisibilityError("Only retained full-base inline_sidecar checkpoints are admitted.")
    engine.require_cuda_allocator_policy(config.train)
    engine.configure_runtime_math(config.train)
    engine.set_global_seed(args.seed)
    device = engine.resolve_device(args.device)
    model, tokenizer, loaded_config = engine.load_bundle(checkpoint, device=device)
    precision = engine.resolve_mixed_precision(config.train.mixed_precision, device)
    dataset = engine.JsonlFineTuningDataset([str(eval_path)], tokenizer, loaded_config.data)
    if len(dataset) < args.max_worlds:
        raise VisibilityError(
            "Insufficient complete world-pair records; refusing a partial sample."
        )
    collator = engine.CausalFineTuningCollator(
        int(tokenizer.pad_token_id), config.data.pad_to_multiple_of
    )
    versions = {name: parameter._version for name, parameter in model.named_parameters()}
    receipt: dict[str, Any] = {
        "format": FORMAT,
        "status": "RUNNING",
        "lane": "retained_inline_diagnostic",
        "scientific_claim": (
            "numerical visibility only; not sufficiency, necessity, or generalization"
        ),
        "training_performed": False,
        "checkpoint": str(checkpoint),
        "checkpoint_inventory": inventory,
        "checkpoint_inventory_sha256": stable_hash(inventory),
        "workspace_sha256": workspace_hash,
        "engine_source_sha256": source_hash,
        "trace_source_sha256": file_sha256(Path(__file__)),
        "flatten_helper_source_sha256": file_sha256(REPO / "scripts" / "run_v11_gate0.py"),
        "loaded_checkpoint_config": dataclasses.asdict(loaded_config),
        "eval_file": str(eval_path),
        "eval_sha256": file_sha256(eval_path),
        "runtime": engine.runtime_environment(),
        "precision": precision,
        "device": str(device),
        "seed": args.seed,
        "modes": modes,
        "gains": gains,
        "gain_selection_performed": False,
        "world_batch_size": 1,
        "world_selection": "first_n_complete_records_in_file_order",
        "max_worlds": args.max_worlds,
        "norm_inventory": norm_inventory(model),
        "requested_arguments": {
            key: value for key, value in vars(args).items() if not key.startswith("_")
        },
        "started_at": datetime.now(UTC).isoformat(),
        "worlds": [],
        "rows": [],
    }
    for index in range(args.max_worlds):
        print(
            f"Capturing world {index + 1}/{args.max_worlds} across {len(modes)} modes.", flush=True
        )
        cpu_batch = collator([dataset[index]])
        batch = engine.move_batch_to_device(cpu_batch, device)
        location = dataset.locations[index]
        source_record = dataset._read_record(location)
        metadata = source_record.get("metadata", {})
        family_id = str(metadata.get("world_family_id", metadata.get("world_pair_id", index)))
        pair_id = str(metadata.get("pair_id", family_id))
        result = capture_loaded_batch(
            model,
            batch,
            modes=modes,
            gains=gains,
            precision=precision,
            raw_query_limit=args.raw_query_limit,
            seed=args.seed,
        )
        world_dir = output_dir / f"world_{index:04d}"
        world_dir.mkdir()
        input_path = world_dir / "inputs.pt"
        torch.save(
            {
                "grouped": cpu_batch,
                "flat": result["flat"],
                "positions": result["positions"],
                "source_record": source_record,
            },
            input_path,
        )
        world_entry = {
            "sample_index": index,
            "family_id": family_id,
            "pair_id": pair_id,
            "source_record_sha256": stable_hash(source_record),
            "source_line": location.line_number,
            "inputs_path": str(input_path.relative_to(output_dir)),
            "inputs_sha256": file_sha256(input_path),
            "modes": {},
        }
        flat = result["flat"]
        for mode, captured in result["captures"].items():
            tensor_path = world_dir / f"{mode}.pt"
            torch.save(
                {
                    "tensors": captured["tensors"],
                    "recomposed": captured["recomposed"],
                    "direct_base": result["direct_base"],
                    "true_bypass": result["true_bypass"],
                },
                tensor_path,
            )
            world_entry["modes"][mode] = {
                **captured["metadata"],
                "tensor_path": str(tensor_path.relative_to(output_dir)),
                "tensor_file_sha256": file_sha256(tensor_path),
            }
            rec = captured["recomposed"]
            for row in range(len(flat["input_ids"])):
                side, query = int(flat["side_indices"][row]), int(flat["query_indices"][row])
                token_binding = {
                    key: flat[key][row].tolist()
                    for key in ("input_ids", "attention_mask", "labels", "candidate_ids")
                }
                receipt["rows"].append(
                    {
                        "sample_index": index,
                        "family_id": family_id,
                        "pair_id": pair_id,
                        "side": side,
                        "query_index": query,
                        "mode": mode,
                        "case_id": f"{pair_id}:side{side}:query{query}",
                        "input_sha256": stable_hash(token_binding),
                        "original_label": int(flat["answer_classes"][row]),
                        "donor_label": int(
                            cpu_batch["functional_answer_classes"][0, 1 - side, query]
                        ),
                        "affected": bool(flat["affected"][row]),
                        "heldout": bool(flat["heldout"][row]),
                        "hop_distance": int(flat["hop_distances"][row]),
                        "candidate_ids": flat["candidate_ids"][row].tolist(),
                        "answer_source_position": int(result["positions"][row]),
                        "logits": rec["native"][row].float().tolist(),
                        "direct_base_logits": result["direct_base"][row].float().tolist(),
                        "true_bypass_logits": result["true_bypass"][row].float().tolist(),
                        "residual_precast": captured["tensors"]["adapter.candidates_precast"][row]
                        .float()
                        .tolist(),
                        **{
                            key: rec[key][row].float().tolist()
                            for key in (
                                "residual_postcast",
                                "bf16",
                                "fp32",
                                "bf16_ulp_up",
                                "bf16_ulp_down",
                                "residual_to_directional_bf16_ulp",
                            )
                        },
                        "diagnostic_fp32_gain_logits": {
                            key: tensor[row].float().tolist()
                            for key, tensor in rec["fp32_diagnostic_gains"].items()
                        },
                    }
                )
        receipt["worlds"].append(world_entry)
        del result, batch, cpu_batch
    if any(parameter._version != versions[name] for name, parameter in model.named_parameters()):
        raise VisibilityError("In-memory model parameters changed during read-only capture.")
    print("Rechecking immutable payload hashes.", flush=True)
    if checkpoint_inventory(checkpoint) != inventory:
        raise VisibilityError("Checkpoint payload bytes changed during capture.")
    if file_sha256(eval_path) != receipt["eval_sha256"] or file_sha256(engine_path) != source_hash:
        raise VisibilityError("Input/source changed during capture.")
    if file_sha256(Path(__file__)) != receipt["trace_source_sha256"]:
        raise VisibilityError("Trace source changed during capture.")
    if (
        file_sha256(REPO / "scripts" / "run_v11_gate0.py")
        != receipt["flatten_helper_source_sha256"]
    ):
        raise VisibilityError("Flattening helper source changed during capture.")
    receipt.update(
        status="COMPLETE",
        checkpoint_bytes_unchanged=True,
        parameters_unmodified=True,
        finished_at=datetime.now(UTC).isoformat(),
    )
    receipt["receipt_sha256"] = stable_hash(receipt)
    write_json(output_dir / "VISIBILITY_TRACE.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--eval-file", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--max-worlds", type=int, default=2)
    parser.add_argument("--raw-query-limit", type=int, default=2)
    parser.add_argument("--modes", default=",".join((*MODES, "hard_bypass")))
    parser.add_argument("--gains", default="1,4,16")
    parser.add_argument("--seed", type=int, default=271828)
    parser.add_argument("--expected-engine-sha256")
    parser.add_argument("--expected-workspace-sha256")
    args = parser.parse_args()
    try:
        receipt = run(args)
    except Exception as exc:
        directory = Path(args.output_dir).expanduser().resolve()
        if (
            getattr(args, "_created_output_dir", None) == str(directory)
            and directory.is_dir()
            and not (directory / "VISIBILITY_TRACE.json").exists()
        ):
            failure = directory / "FAILED.json"
            if not failure.exists():
                write_json(
                    failure,
                    {
                        "status": "FAILED",
                        "format": FORMAT,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )
        raise
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "cases": len(receipt["rows"]),
                "receipt": str(Path(args.output_dir) / "VISIBILITY_TRACE.json"),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
