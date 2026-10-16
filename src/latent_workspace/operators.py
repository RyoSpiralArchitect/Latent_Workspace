"""Explicit workspace operators.

Promoted verbatim from ``normalization.py`` in ``latent_workspace_ft_v10`` at
``d4cd1ee0340a``. The historical files are frozen; this module is the living home
(docs/ARCHITECTURE.md). Parity: ``test_logit_adapter_and_operators_are_historical``.
"""

from __future__ import annotations

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
