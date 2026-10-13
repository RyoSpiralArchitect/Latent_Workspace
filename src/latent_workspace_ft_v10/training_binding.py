"""Explicit model bindings for an adapter-owned training graph, not core policy."""

import functools
import hashlib
import inspect
import platform

import torch

from .hf_training_readout import HFTrainingReadoutAdapter
from .v15_full_update import MistralLiveFeatures


def checkpoint_policy(base):
    rows = []
    for name, module in base.named_modules():
        if hasattr(module, "gradient_checkpointing"):
            fn = getattr(module, "_gradient_checkpointing_func", None)
            if fn is not None and (
                not isinstance(fn, functools.partial)
                or fn.args
                or any(
                    type(v) not in (bool, int, float, str, type(None)) for v in fn.keywords.values()
                )
            ):
                raise ValueError("Unknown gradient checkpointing implementation")
            rows.append(
                {
                    "module": name,
                    "enabled": module.gradient_checkpointing,
                    "function": f"{fn.func.__module__}.{fn.func.__qualname__}" if fn else None,
                    "keywords": dict(fn.keywords) if fn else None,
                }
            )
    return rows


class MistralTrainingBinding:
    """First qualified context binding; readout itself supports more layouts.

    The owner below only uses this public binding contract. Other architectures
    need separately qualified context extraction, not a hidden family switch in
    the optimizer or reader. No observer may replace native features.
    """

    def __init__(self, base, boundary, observer=None):
        if observer is not None:
            raise ValueError("Observer callbacks need a separately qualified training binding")
        self.base, self.boundary = base, boundary
        self.features = MistralLiveFeatures(base, boundary, observer)
        self.readout = HFTrainingReadoutAdapter(base)
        classes = {type(module) for module in base.modules()}
        self._forward_sources = {
            f"{cls.__module__}.{cls.__qualname__}": hashlib.sha256(
                inspect.getsource(cls.forward).encode()
            ).hexdigest()
            for cls in classes
        }

    def validate(self):
        self.readout._validate()
        if (
            self.readout.base is not self.base
            or self.features.base_model is not self.base
            or self.features.context_boundary != self.boundary
        ):
            raise ValueError("Context/readout base ownership changed")

    def context(self, ids):
        self.validate()
        return self.features.context(tuple(ids))

    def describe(self):
        return {
            "schema": "mistral-training-binding-v1",
            "readout": self.readout.describe(),
            "context": self.features.boundary.describe_boundary(self.boundary).to_dict(),
            "native_forward_sources": self._forward_sources,
            "modes": {n: m.training for n, m in self.base.named_modules()},
            "checkpointing": checkpoint_policy(self.base),
            "parameter_schema": {
                n: [list(p.shape), str(p.dtype), str(p.device), p.requires_grad]
                for n, p in self.base.named_parameters()
            },
            "buffer_schema": {
                n: [list(b.shape), str(b.dtype), str(b.device)]
                for n, b in self.base.named_buffers(remove_duplicate=False)
            },
            "arithmetic": {
                "python": platform.python_version(),
                "machine": platform.machine(),
                "float32_matmul_precision": torch.get_float32_matmul_precision(),
                "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
                "cuda_tf32": torch.backends.cuda.matmul.allow_tf32,
                "cudnn_tf32": torch.backends.cudnn.allow_tf32,
                "cpu_threads": torch.get_num_threads(),
                "cpu_interop_threads": torch.get_num_interop_threads(),
                "cuda_runtime": torch.version.cuda,
                "device_name": torch.cuda.get_device_name(self.readout.head.weight.device)
                if self.readout.head.weight.device.type == "cuda"
                else "cpu",
                "cuda_capability": list(
                    torch.cuda.get_device_capability(self.readout.head.weight.device)
                )
                if self.readout.head.weight.device.type == "cuda"
                else None,
            },
        }
