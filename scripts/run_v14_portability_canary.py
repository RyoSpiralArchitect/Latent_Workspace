#!/usr/bin/env python3
"""Offline native/split identity canary on one model; no training or capability claims."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from latent_workspace_ft_v10.implementation_identity import implementation_fingerprint  # noqa: E402
from latent_workspace_ft_v10.model_binding import FunctionalBoundaryAdapter  # noqa: E402
from latent_workspace_ft_v10.normalization import inventory_normalizers  # noqa: E402
from latent_workspace_ft_v10.numerics import NumericsPolicy  # noqa: E402
from latent_workspace_ft_v10.observability import NamedNormRecorder  # noqa: E402

PROMPTS = (
    "The cobalt box is in room A. The amber box is in room B. The cobalt box is in",
    "Rain fell overnight. By morning the streets were",
    "Two keys rest on a wooden table. Beside them is",
)
MAX_INPUT_TOKENS = 96
GENERATION_TOKENS = 4
TOLERANCES = {
    "float32": {"logits_atol": 1e-5, "logits_rtol": 1e-4, "grad_atol": 1e-6, "grad_rtol": 1e-4},
    "bfloat16": {
        "logits_atol": 0.015625,
        "logits_rtol": 0.0078125,
        "grad_atol": 1e-5,
        "grad_rtol": 0.02,
    },
}
CLAIM_BOUNDARY = (
    "Fixed-input, no-cache native/split pipeline identity only. Greedy text is a pipeline "
    "check, not capability, semantic transfer, workspace utility, training, or V14 bridge. "
    "Tolerances are predeclared and not fitted to observed outputs. No optimizer is constructed."
)


def _norm_observation_qualified(observation: dict) -> bool:
    chosen = observation["selected_module_names"]
    counts, records = observation.get("counts", {}), observation.get("records", [])
    if not chosen or set(counts) != set(chosen) or len(records) != len(chosen):
        return False
    if any(
        counts[name] != {"invoked": 1, "recorded": 1, "dropped": 0}
        or any(type(value) is not int for value in counts[name].values())
        for name in chosen
    ):
        return False
    if {row.get("name") for row in records} != set(chosen):
        return False
    return all(
        row.get("status") == "COMPLETE"
        and all(
            isinstance(row.get(side), dict)
            and row[side].get("status") == "CAPTURED"
            and row[side].get("sample_finite") is True
            and type(row[side].get("sampled_elements")) is int
            and row[side]["sampled_elements"] > 0
            for side in ("pre", "post")
        )
        for row in records
    )


def _observed_runtime(device: str, attention_implementation: str) -> dict:
    try:
        transformers_version = version("transformers")
    except PackageNotFoundError:
        transformers_version = None
    runtime = {
        "torch": torch.__version__,
        "transformers": transformers_version,
        "python": sys.version,
        "cuda": torch.version.cuda,
        "torch_threads": torch.get_num_threads(),
        "torch_interop_threads": torch.get_num_interop_threads(),
        "float32_matmul_precision": torch.get_float32_matmul_precision(),
        "cuda_matmul_policy": {
            name: getattr(torch.backends.cuda.matmul, name, None)
            for name in (
                "allow_tf32",
                "allow_fp16_reduced_precision_reduction",
                "allow_bf16_reduced_precision_reduction",
                "allow_fp16_accumulation",
            )
        },
        "cudnn_allow_tf32": torch.backends.cudnn.allow_tf32,
        "sdpa_policy": {
            name: getattr(torch.backends.cuda, name)()
            if callable(getattr(torch.backends.cuda, name, None))
            else None
            for name in (
                "flash_sdp_enabled",
                "mem_efficient_sdp_enabled",
                "math_sdp_enabled",
                "cudnn_sdp_enabled",
                "fp16_bf16_reduction_math_sdp_allowed",
            )
        },
        "effective_sdpa_backend": "UNKNOWN"
        if attention_implementation == "sdpa"
        else "NOT_APPLICABLE_EAGER",
        "sdpa_backend_instrumented": False,
        "sdpa_policy_is_executed_backend_evidence": False,
        "gpu": None,
    }
    if device == "cuda":
        index = torch.cuda.current_device()
        runtime["gpu"] = {
            "device_index": index,
            "name": torch.cuda.get_device_name(index),
            "capability": list(torch.cuda.get_device_capability(index)),
            "total_memory_bytes": torch.cuda.get_device_properties(index).total_memory,
        }
    return runtime


def _cuda_peak_memory() -> dict:
    return {
        "status": "OBSERVED",
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
        "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
        "final_allocated_bytes": torch.cuda.memory_allocated(),
        "final_reserved_bytes": torch.cuda.memory_reserved(),
        "scope": "this process Torch CUDA allocator since pre-load reset; not all GPU memory",
    }


def _difference(left: torch.Tensor, right: torch.Tensor, *, atol: float, rtol: float) -> dict:
    if left.shape != right.shape or left.dtype != right.dtype:
        raise ValueError("Compared tensors differ in shape or dtype")
    left, right = left.detach().cpu().double(), right.detach().cpu().double()
    finite = bool(torch.isfinite(left).all() and torch.isfinite(right).all())
    if not finite:
        return {
            "finite": False,
            "elements": left.numel(),
            "max_abs_difference": None,
            "within_tolerance": False,
        }
    delta = (left - right).abs()
    return {
        "finite": True,
        "elements": left.numel(),
        "max_abs_difference": float(delta.max()) if delta.numel() else 0.0,
        "different_elements": int(delta.ne(0).sum()),
        "within_tolerance": bool(torch.allclose(left, right, atol=atol, rtol=rtol)),
    }


def _native(model: Any, ids: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    return model(input_ids=ids, attention_mask=mask, use_cache=False, return_dict=True).logits


def _split(binding: Any, ids: torch.Tensor, mask: torch.Tensor, cut: int) -> torch.Tensor:
    return binding.decode(binding.encode(ids, mask, cut), mask, cut)


def _greedy(forward: Any, ids: torch.Tensor) -> list[int]:
    generated = []
    for _ in range(GENERATION_TOKENS):
        logits = forward(ids, torch.ones_like(ids))
        if not bool(torch.isfinite(logits).all()):
            raise ValueError("Nonfinite greedy logits")
        token = logits[:, -1].argmax(-1, keepdim=True)
        generated.append(int(token.item()))
        ids = torch.cat((ids, token), dim=1)
    return generated


def _gradient_comparison(
    model: Any, binding: Any, ids: torch.Tensor, mask: torch.Tensor, cut: int, tolerances: dict
) -> dict:
    parameters = list(model.named_parameters())
    if not parameters or any(not parameter.requires_grad for _, parameter in parameters):
        raise ValueError(
            "Full-parameter gradient check requires every parameter trainable, without an optimizer"
        )
    labels = ids[:, 1:].clone().masked_fill(mask[:, 1:].eq(0), -100)

    def backward(forward: Any) -> float:
        logits = forward(ids, mask)
        loss = F.cross_entropy(
            logits[:, :-1].float().reshape(-1, logits.shape[-1]), labels.reshape(-1)
        )
        if not bool(torch.isfinite(loss)):
            raise ValueError("Nonfinite fixed-label cross entropy")
        loss.backward()
        return float(loss.detach())

    model.zero_grad(set_to_none=True)
    try:
        with torch.enable_grad():
            native_loss = backward(lambda a, b: _native(model, a, b))
            saved = {
                name: None if p.grad is None else p.grad.detach().cpu().clone()
                for name, p in parameters
            }
            model.zero_grad(set_to_none=True)
            split_loss = backward(lambda a, b: _split(binding, a, b, cut))
        rows = []
        for name, parameter in parameters:
            first, second = saved.pop(name), parameter.grad
            row = {
                "parameter": name,
                "parameter_elements": parameter.numel(),
                "native_gradient_present": first is not None,
                "split_gradient_present": second is not None,
            }
            if first is not None and second is not None:
                row.update(
                    _difference(
                        first, second, atol=tolerances["grad_atol"], rtol=tolerances["grad_rtol"]
                    )
                )
            else:
                row.update(finite=False, within_tolerance=False, max_abs_difference=None)
            rows.append(row)
        observed = [
            row["max_abs_difference"] for row in rows if row["max_abs_difference"] is not None
        ]
        return {
            "status": "COMPLETE",
            "boundary_layer": cut,
            "native_loss": native_loss,
            "split_loss": split_loss,
            "parameter_count": len(rows),
            "parameter_elements": sum(row["parameter_elements"] for row in rows),
            "finite_parameter_gradient_count": sum(row["finite"] for row in rows),
            "max_abs_gradient_difference": max(observed, default=None),
            "all_parameter_gradients_within_tolerance": all(
                row["within_tolerance"] for row in rows
            ),
            "loss_definition": (
                "mean fixed next-input-token CE over non-padding targets, logits cast to FP32"
            ),
            "gradients_copied_to_cpu_sequentially": True,
            "parameters": rows,
        }
    finally:
        model.zero_grad(set_to_none=True)


def run_canary(
    model: Any,
    tokenizer: Any,
    *,
    check_gradients: bool = False,
    binding_factory: Any = FunctionalBoundaryAdapter,
    receipt: dict | None = None,
) -> dict:
    """Run on one caller-supplied model; optional receipt retains progress on exceptions."""
    report = receipt if receipt is not None else {}
    report.update(status="RUNNING", claim_boundary=CLAIM_BOUNDARY, scientific_success=False)
    if type(check_gradients) is not bool:
        raise ValueError("check_gradients must be boolean")
    parameters = list(model.named_parameters())
    if not parameters:
        raise ValueError("Model must have parameters")
    versions = {name: (id(p), p._version, p.requires_grad) for name, p in parameters}
    first = parameters[0][1]
    precision = {torch.float32: "float32", torch.bfloat16: "bfloat16"}.get(first.dtype)
    if precision is None:
        raise ValueError("Canary supports float32 or bfloat16 parameters")
    tolerances = dict(TOLERANCES[precision])
    model.eval()
    tokenizer.padding_side = "right"
    if tokenizer.pad_token_id is None:
        if tokenizer.eos_token_id is None:
            raise ValueError(
                "Tokenizer requires an existing pad or EOS token; vocabulary is not extended"
            )
        tokenizer.pad_token = tokenizer.eos_token
    encoded = tokenizer(
        list(PROMPTS), padding=True, truncation=False, add_special_tokens=True, return_tensors="pt"
    )
    ids, mask = encoded["input_ids"].to(first.device), encoded["attention_mask"].to(first.device)
    if (
        ids.ndim != 2
        or ids.shape != mask.shape
        or ids.shape[0] != len(PROMPTS)
        or not 2 <= ids.shape[1] <= MAX_INPUT_TOKENS
    ):
        raise ValueError("Fixed prompt batch shape or token bound changed")
    if (
        not bool(((mask == 0) | (mask == 1)).all())
        or bool((mask[:, 1:] > mask[:, :-1]).any())
        or bool(mask.sum(1).lt(2).any())
    ):
        raise ValueError("Expected nonempty right-padded attention masks")
    binding = binding_factory(model)
    layers = binding.layer_count()
    if type(layers) is not int or layers < 1:
        raise ValueError("Binding must have at least one decoder layer")
    cuts = sorted({0, layers // 2, layers})
    report.update(
        model_type=str(getattr(model.config, "model_type", "unknown")),
        precision=precision,
        weight_dtypes=dict(Counter(str(p.dtype) for _, p in parameters)),
        device=str(first.device),
        tolerances=tolerances,
        tolerance_selection="fixed_in_source_before_run",
        prompts=list(PROMPTS),
        input_ids=ids.cpu().tolist(),
        attention_mask=mask.cpu().tolist(),
        padding_side="right",
        pad_token_id=tokenizer.pad_token_id,
        use_cache=False,
        boundary_layers=cuts,
        boundaries=[],
        generation=[],
        gradient_check={"status": "NOT_RUN"},
    )
    try:
        with torch.no_grad():
            native = _native(model, ids, mask)
            baseline = native.detach().cpu().clone()
            report["true_bypass"] = {
                "scope": (
                    "numerics helper identity on native logits; not a workspace-wrapper route test"
                ),
                "profiles": {
                    profile: NumericsPolicy(profile).compose_logits(native, None, true_bypass=True)
                    is native
                    for profile in ("legacy_native", "fp32_accumulate")
                },
                "output_dtype": str(native.dtype),
            }
            del native
            inventory_names = list(inventory_normalizers(model))
            chosen = inventory_names[:3]
            if "model.norm" in inventory_names and "model.norm" not in chosen:
                chosen.append("model.norm")
            modules = dict(model.named_modules())
            with NamedNormRecorder(
                {name: modules[name] for name in chosen},
                max_records=8,
                max_tensor_elements=4096,
            ) as recorder:
                observed_native = _native(model, ids, mask)
            report["named_norm_observation"] = {
                "selected_module_names": chosen,
                "selection": (
                    "first three inventoried normalizers plus native model.norm if present"
                ),
                "passthrough_numeric_exact": bool(torch.equal(observed_native.cpu(), baseline)),
                **recorder.to_dict(),
            }
            report["named_norm_observation"]["observation_checks_passed"] = (
                _norm_observation_qualified(report["named_norm_observation"])
            )
            del observed_native
            for cut in cuts:
                output = _split(binding, ids, mask, cut)
                descriptor = binding.describe_boundary(cut)
                report["boundaries"].append(
                    {
                        "boundary_layer": cut,
                        "descriptor": descriptor.to_dict(),
                        "descriptor_sha256": descriptor.fingerprint(),
                        "output_dtype": str(output.dtype),
                        **_difference(
                            baseline,
                            output,
                            atol=tolerances["logits_atol"],
                            rtol=tolerances["logits_rtol"],
                        ),
                    }
                )
                del output
            for index in range(2):
                unpadded = ids[index : index + 1, : int(mask[index].sum())]
                native_ids = _greedy(lambda a, b: _native(model, a, b), unpadded)
                split_ids = _greedy(lambda a, b: _split(binding, a, b, layers // 2), unpadded)
                report["generation"].append(
                    {
                        "prompt_index": index,
                        "new_tokens": GENERATION_TOKENS,
                        "native_token_ids": native_ids,
                        "split_token_ids": split_ids,
                        "native_text": tokenizer.decode(native_ids, skip_special_tokens=False),
                        "split_text": tokenizer.decode(split_ids, skip_special_tokens=False),
                        "token_ids_equal": native_ids == split_ids,
                    }
                )
        if check_gradients:
            report["gradient_check"] = _gradient_comparison(
                model, binding, ids, mask, layers // 2, tolerances
            )
        passed = all(row["within_tolerance"] for row in report["boundaries"]) and all(
            row["token_ids_equal"] for row in report["generation"]
        )
        passed = passed and all(report["true_bypass"]["profiles"].values())
        passed = passed and report["named_norm_observation"]["passthrough_numeric_exact"]
        passed = passed and report["named_norm_observation"]["observation_checks_passed"]
        if check_gradients:
            passed = passed and report["gradient_check"]["all_parameter_gradients_within_tolerance"]
        report.update(status="COMPLETE" if passed else "MISMATCH", pipeline_checks_passed=passed)
    finally:
        model.zero_grad(set_to_none=True)
        unchanged = versions == {
            name: (id(p), p._version, p.requires_grad) for name, p in model.named_parameters()
        }
        report["parameter_identity_versions_unchanged"] = unchanged
        report["gradients_cleared"] = all(p.grad is None for p in model.parameters())
        if not unchanged:
            report.update(status="FAILED", pipeline_checks_passed=False)
            raise ValueError("Model parameters changed during canary")
    return report


def _digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _stat(path: Path) -> dict:
    item = path.stat()
    return {
        "resolved_path": str(path.resolve()),
        "bytes": item.st_size,
        "mtime_ns": item.st_mtime_ns,
        "ctime_ns": item.st_ctime_ns,
    }


def _snapshot_files(model_path: Path) -> list[Path]:
    files = []
    for path in sorted(model_path.rglob("*")):
        if path.is_symlink():
            target = Path(os.readlink(path))
            allowed_blobs = model_path.parent.parent / "blobs"
            if (
                path.parent != model_path
                or target.is_absolute()
                or len(target.parts) != 4
                or target.parts[:3] != ("..", "..", "blobs")
                or path.resolve().parent != allowed_blobs.resolve()
                or not path.is_file()
            ):
                raise ValueError("Only standard snapshot ../../blobs/file HF symlinks are allowed")
        if path.is_file():
            files.append(path)
    return files


def inventory(model_path: Path) -> list[dict]:
    files = _snapshot_files(model_path)
    if (
        not files
        or len(files) > 128
        or not (model_path / "config.json").is_file()
        or not any(path.suffix == ".safetensors" for path in files)
    ):
        raise ValueError("Expected bounded local model config and safetensors snapshot")
    if sum(path.stat().st_size for path in files) > 8 * 1024**3:
        raise ValueError("Canary snapshot exceeds fixed 8 GiB payload bound")
    rows = []
    for path in files:
        before = _stat(path)
        sha256 = _digest(path)
        if _stat(path) != before:
            raise ValueError("Snapshot changed while hashing")
        rows.append({"path": str(path.relative_to(model_path)), **before, "sha256": sha256})
    return rows


def check_inventory(model_path: Path, before: list[dict]) -> dict:
    actual = [str(path.relative_to(model_path)) for path in _snapshot_files(model_path)]
    if actual != [row["path"] for row in before]:
        raise ValueError("Snapshot file inventory changed")
    rehashed = []
    for row in before:
        path = model_path / row["path"]
        if _stat(path) != {
            key: row[key] for key in ("resolved_path", "bytes", "mtime_ns", "ctime_ns")
        }:
            changed_digest = _digest(path)
            raise ValueError(
                f"Snapshot metadata changed: {row['path']}; content_sha256={changed_digest}"
            )
        if _digest(path) != row["sha256"]:
            raise ValueError(f"Snapshot payload hash changed: {row['path']}")
        if _stat(path) != {
            key: row[key] for key in ("resolved_path", "bytes", "mtime_ns", "ctime_ns")
        }:
            raise ValueError(f"Snapshot changed during post-run hashing: {row['path']}")
        rehashed.append(row["path"])
    return {
        "manifest_stats_unchanged": True,
        "all_payload_sha256_unchanged": True,
        "payloads_rehashed": rehashed,
        "reconstructible_weight_backup": False,
    }


def _load_local_model(
    path: Path, *, device: str, dtype: torch.dtype, attention_implementation: str = "sdpa"
) -> tuple[Any, Any]:
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        str(path), local_files_only=True, trust_remote_code=False
    )
    model = AutoModelForCausalLM.from_pretrained(
        str(path),
        local_files_only=True,
        trust_remote_code=False,
        dtype=dtype,
        attn_implementation=attention_implementation,
    )
    return model.to(device), tokenizer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), required=True)
    parser.add_argument("--dtype", choices=("bfloat16", "float32"), required=True)
    parser.add_argument("--attention-implementation", choices=("eager", "sdpa"), default="sdpa")
    parser.add_argument("--check-gradients", action="store_true")
    args = parser.parse_args(argv)
    started_monotonic = time.monotonic()
    report: dict[str, Any] = {
        "format": "latent-workspace-v14-portability-canary-v1",
        "status": "RUNNING",
        "started_utc": datetime.now(UTC).isoformat(),
        "scientific_success": False,
        "training_performed": False,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    created = False
    before = None
    cuda_peaks_reset = False
    try:
        if (
            not args.model_path.is_absolute()
            or not args.model_path.is_dir()
            or not args.output_dir.is_absolute()
        ):
            raise ValueError(
                "Model and output must be explicit absolute paths; model directory must exist"
            )
        model_path, output = args.model_path.resolve(), args.output_dir.resolve()
        if (
            output.exists()
            or args.output_dir.is_symlink()
            or output.is_relative_to(model_path)
            or model_path.is_relative_to(output)
        ):
            raise ValueError("Output must be fresh and disjoint from model snapshot")
        output.mkdir(parents=True, exist_ok=False)
        created = True
        report.update(
            model_path=str(model_path),
            requested_device=args.device,
            requested_dtype=args.dtype,
            requested_gradient_check=args.check_gradients,
        )
        os.environ.update(
            HF_HUB_OFFLINE="1",
            TRANSFORMERS_OFFLINE="1",
            HF_DATASETS_OFFLINE="1",
            TOKENIZERS_PARALLELISM="false",
        )
        report["offline_loading"] = {
            "local_files_only": True,
            "trust_remote_code": False,
            "attention_implementation": args.attention_implementation,
        }
        torch.set_num_threads(2)
        torch.manual_seed(1401)
        if args.device == "cuda":
            if not torch.cuda.is_available():
                raise ValueError("CUDA explicitly requested but unavailable")
            torch.backends.cuda.matmul.allow_tf32 = False
            torch.backends.cudnn.allow_tf32 = False
        report["runtime"] = _observed_runtime(args.device, args.attention_implementation)
        if args.device == "cuda":
            torch.cuda.reset_peak_memory_stats()
            cuda_peaks_reset = True
        before = inventory(model_path)
        report["model_payload_inventory"] = before
        sources = [
            Path(__file__),
            REPO / "src/latent_workspace_ft_v10/model_binding.py",
            REPO / "src/latent_workspace_ft_v10/numerics.py",
        ]
        report["implementation_fingerprint"] = implementation_fingerprint()
        report["source_sha256"] = {str(path.resolve()): _digest(path) for path in sources}
        model, tokenizer = _load_local_model(
            model_path,
            device=args.device,
            dtype=getattr(torch, args.dtype),
            attention_implementation=args.attention_implementation,
        )
        actual_attention = getattr(model.config, "_attn_implementation", None)
        report["actual_attention_implementation"] = actual_attention
        if actual_attention != args.attention_implementation:
            raise ValueError("Loaded attention implementation differs from requested backend")
        for obj in (type(model), type(tokenizer)):
            source = inspect.getsourcefile(obj)
            if source and Path(source).is_file():
                sources.append(Path(source))
        report["source_sha256"] = {str(path.resolve()): _digest(path) for path in sources}
        report["normalizer_inventory"] = inventory_normalizers(model)
        report["runtime"] = _observed_runtime(args.device, args.attention_implementation)
        report["canary"] = {}
        run_canary(model, tokenizer, check_gradients=args.check_gradients, receipt=report["canary"])
        report["snapshot_postcheck"] = check_inventory(model_path, before)
        if any(_digest(Path(path)) != value for path, value in report["source_sha256"].items()):
            raise ValueError("Canary or model implementation source changed")
        if implementation_fingerprint() != report["implementation_fingerprint"]:
            raise ValueError("Package implementation changed during canary")
        report["status"] = report["canary"]["status"]
    except Exception as exc:
        report.update(status="FAILED", error=f"{type(exc).__name__}: {exc}")
        if before is not None:
            try:
                report["snapshot_postcheck"] = check_inventory(args.model_path.resolve(), before)
            except Exception as post_error:
                report["snapshot_postcheck"] = {"status": "FAILED", "error": str(post_error)}
    report["finished_utc"] = datetime.now(UTC).isoformat()
    report["cuda_memory"] = {"status": "NOT_MEASURED"}
    if cuda_peaks_reset:
        try:
            report["cuda_memory"] = _cuda_peak_memory()
        except Exception as exc:
            report["cuda_memory"] = {"status": "UNAVAILABLE", "error": str(exc)}
    report["elapsed_seconds"] = time.monotonic() - started_monotonic
    report["timing_scope"] = (
        "monotonic CLI execution including hashing, loading and checks, "
        "before receipt serialization; "
        "execution bookkeeping only, not a speed comparison"
    )
    if created:
        with (args.output_dir.resolve() / "PORTABILITY_CANARY.json").open(
            "x", encoding="utf-8"
        ) as handle:
            json.dump(report, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "output_dir": str(args.output_dir),
                "error": report.get("error"),
                "scientific_success": False,
            }
        )
    )
    return 0 if report["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
