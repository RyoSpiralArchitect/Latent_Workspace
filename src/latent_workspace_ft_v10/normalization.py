"""Explicit workspace operators and read-only descriptions of native norms.

An operator replacement changes the workspace algorithm. Native model norms are
described, never replaced or reconstructed. Unsupported norms stay UNKNOWN.
"""

from __future__ import annotations

import hashlib
import inspect
import math
from dataclasses import asdict, dataclass
from typing import Any

import torch
from torch import nn


@dataclass(frozen=True)
class NormalizationSpec:
    kind: str = "layer_norm"
    eps: float = 1e-5

    def __post_init__(self) -> None:
        if self.kind not in {"layer_norm", "rms_norm"}:
            raise ValueError("Unsupported workspace normalization kind")
        if isinstance(self.eps, bool) or not math.isfinite(self.eps) or self.eps <= 0:
            raise ValueError("Normalization epsilon must be finite and positive")

    def build(self, width: int) -> nn.Module:
        if type(width) is not int or width < 1:
            raise ValueError("Normalization width must be a positive integer")
        if self.kind == "layer_norm":
            return nn.LayerNorm(width, eps=self.eps)
        return nn.RMSNorm(width, eps=self.eps)

    def fingerprint(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "axis": "last",
            "affine": "direct_weight_plus_bias" if self.kind == "layer_norm" else "direct_weight",
            "centers": self.kind == "layer_norm",
            "implementation": "torch.nn.LayerNorm"
            if self.kind == "layer_norm"
            else "torch.nn.RMSNorm",
            "torch_version": str(torch.__version__),
            "replacement_is_algorithm_change": True,
        }


def _tensor_identity(tensor: torch.Tensor) -> dict[str, Any]:
    value = tensor.detach().contiguous().cpu()
    return {
        "shape": list(value.shape),
        "dtype": str(value.dtype),
        "sha256": hashlib.sha256(value.reshape(-1).view(torch.uint8).numpy().tobytes()).hexdigest(),
    }


def describe_normalizer(module: nn.Module) -> dict[str, Any]:
    """No forward calls or mutation; family semantics require an exact known class."""
    cls = type(module)
    identity = f"{cls.__module__}.{cls.__name__}"
    kind, affine, centers = "UNKNOWN", "UNKNOWN", None
    if cls is nn.LayerNorm:
        kind, affine, centers = "layer_norm", "direct_weight_plus_bias", True
    elif cls is nn.RMSNorm:
        kind, affine, centers = "rms_norm", "direct_weight", False
    elif identity in {
        "transformers.models.mistral.modeling_mistral.MistralRMSNorm",
        "transformers.models.olmo2.modeling_olmo2.Olmo2RMSNorm",
        "transformers.models.llama.modeling_llama.LlamaRMSNorm",
        "transformers.models.qwen2.modeling_qwen2.Qwen2RMSNorm",
    }:
        kind, affine, centers = "rms_norm", "direct_weight", False
    elif identity in {
        "transformers.models.gemma2.modeling_gemma2.Gemma2RMSNorm",
        "transformers.models.gemma3.modeling_gemma3.Gemma3RMSNorm",
    }:
        kind, affine, centers = "rms_norm", "one_plus_weight", False
    eps = getattr(module, "eps", getattr(module, "variance_epsilon", None))
    shape = getattr(module, "normalized_shape", None)
    try:
        class_source_hash = hashlib.sha256(inspect.getsource(cls).encode()).hexdigest()
    except (OSError, TypeError):
        class_source_hash = None
    return {
        "class": identity,
        "class_source_sha256": class_source_hash,
        "status": "DESCRIBED" if kind != "UNKNOWN" else "UNSUPPORTED_UNKNOWN",
        "kind": kind,
        "centers": centers,
        "affine_parameterization": affine,
        "eps": eps,
        "eps_rule": "input_dtype_finfo"
        if cls is nn.RMSNorm and eps is None
        else "explicit_or_unknown",
        "axis": (
            f"last_{len(shape)}"
            if shape is not None
            else "last_1"
            if kind != "UNKNOWN"
            else "UNKNOWN"
        ),
        "normalized_shape": list(shape) if shape is not None else None,
        "parameters": {
            name: _tensor_identity(p) for name, p in module.named_parameters(recurse=False)
        },
        "note": "Module inventory, not proof this operator executed or of its reduction precision.",
    }


def inventory_normalizers(model: nn.Module) -> dict[str, dict[str, Any]]:
    result = {}
    for name, module in model.named_modules():
        if (
            isinstance(module, (nn.LayerNorm, nn.RMSNorm))
            or "norm" in type(module).__name__.lower()
        ):
            result[name] = {
                "owner": "base_model" if name.startswith("base_model.") else "workspace_or_model",
                **describe_normalizer(module),
            }
    return result
