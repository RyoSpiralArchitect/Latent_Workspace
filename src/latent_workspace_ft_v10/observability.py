"""Bounded, named normalization observations; no attention/K/V instrumentation."""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

import torch
from torch import nn


class NamedNormRecorder:
    """Observe explicit modules without replacing outputs or retaining graphs.

    Each record is one invocation's pre/post summary. Hashes and statistics
    cover only the explicitly labelled flattened prefix, not omitted elements.
    Re-entering after completion starts a fresh capture; nesting is rejected.
    """

    def __init__(
        self,
        modules: Mapping[str, nn.Module],
        *,
        max_records: int = 16,
        max_tensor_elements: int = 4096,
    ) -> None:
        if max_records < 0 or max_tensor_elements <= 0:
            raise ValueError("Require max_records >= 0 and max_tensor_elements > 0.")
        if any(
            not isinstance(name, str) or not name or not isinstance(module, nn.Module)
            for name, module in modules.items()
        ):
            raise TypeError("Expected explicit nonempty names mapped to torch modules.")
        if len({id(module) for module in modules.values()}) != len(modules):
            raise ValueError("Each module must have exactly one observation name.")
        self.modules = dict(modules)
        self.max_records = max_records
        self.max_tensor_elements = max_tensor_elements
        self.records: list[dict[str, Any]] = []
        self.counts: dict[str, dict[str, int]] = {}
        self._pending: dict[str, list[dict[str, Any] | None]] = {}
        self._handles: list[Any] = []
        self._active = False

    def _snapshot(self, value: Any) -> dict[str, Any]:
        if (
            not isinstance(value, torch.Tensor)
            or value.layout != torch.strided
            or value.is_quantized
            or value.is_complex()
            or value.device.type == "meta"
        ):
            return {"status": "UNSUPPORTED", "reason": "expected_dense_real_tensor"}
        sample = value.detach().reshape(-1)[: self.max_tensor_elements].cpu().contiguous()
        numeric = sample.double()
        finite = bool(torch.isfinite(numeric).all())
        return {
            "status": "CAPTURED",
            "shape": list(value.shape),
            "dtype": str(value.dtype),
            "tensor_elements": value.numel(),
            "sampled_elements": sample.numel(),
            "omitted_elements": value.numel() - sample.numel(),
            "hash_scope": "full_tensor" if sample.numel() == value.numel() else "flat_prefix",
            "sha256": hashlib.sha256(sample.view(torch.uint8).numpy().tobytes()).hexdigest(),
            "statistics_dtype": "torch.float64",
            "sample_finite": finite,
            "sample_mean": numeric.mean().item() if finite and sample.numel() else None,
            "sample_l2": numeric.norm().item() if finite else None,
        }

    def _before(self, name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        counts = self.counts[name]
        counts["invoked"] += 1
        if len(self.records) >= self.max_records:
            counts["dropped"] += 1
            self._pending[name].append(None)
            return
        value = args[0] if args else next(iter(kwargs.values())) if len(kwargs) == 1 else None
        record = {
            "name": name,
            "invocation": counts["invoked"],
            "status": "PENDING",
            "pre": self._snapshot(value),
            "post": None,
        }
        self.records.append(record)
        self._pending[name].append(record)
        counts["recorded"] += 1

    def _after(self, name: str, output: Any) -> None:
        record = self._pending[name].pop()
        if record is None:
            return
        record["post"] = self._snapshot(output)
        if record["pre"]["status"] != "CAPTURED" or record["post"]["status"] != "CAPTURED":
            record["status"] = "UNSUPPORTED"
        elif record["pre"]["shape"] != record["post"]["shape"]:
            record["status"] = "UNSUPPORTED"
            record["reason"] = "normalization_input_output_shape_mismatch"
        else:
            record["status"] = "COMPLETE"

    def __enter__(self) -> NamedNormRecorder:
        if self._active:
            raise RuntimeError("Nested capture on the same recorder is not allowed.")
        self._active = True
        self.records = []
        self.counts = {name: {"invoked": 0, "recorded": 0, "dropped": 0} for name in self.modules}
        self._pending = {name: [] for name in self.modules}
        try:
            for name, module in self.modules.items():

                def before(_module, args, kwargs, name=name):
                    self._before(name, args, kwargs)

                def after(_module, _args, _kwargs, output, name=name):
                    self._after(name, output)

                self._handles.append(module.register_forward_pre_hook(before, with_kwargs=True))
                self._handles.append(module.register_forward_hook(after, with_kwargs=True))
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_exc: Any) -> None:
        for handle in self._handles:
            handle.remove()
        self._handles.clear()
        for record in self.records:
            if record["status"] == "PENDING":
                record["status"] = "INTERRUPTED"
        self._pending.clear()
        self._active = False

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(
            {
                "schema_version": "latent_workspace.named_norm_observations.v1",
                "scope": "explicit_norm_modules_only_no_attention_or_kv_claim",
                "max_records": self.max_records,
                "max_tensor_elements": self.max_tensor_elements,
                "active": self._active,
                "counts": self.counts,
                "records": self.records,
            }
        )
