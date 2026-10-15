"""Explicit final-logit arithmetic; this never selects whole-model forward precision."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import torch

NumericsProfile = Literal["legacy_native", "fp32_accumulate"]


@dataclass(frozen=True, slots=True)
class NumericsPolicy:
    """Immutable arithmetic contract for combining captured base and sidecar logits.

    ``fp32_accumulate`` casts the inputs already computed by the model, adds in
    FP32 and retains FP32 output. It does not recover earlier quantization loss
    or change the forward precision of the base model, reader or adapter.
    """

    profile: NumericsProfile = "legacy_native"

    def __post_init__(self) -> None:
        if type(self.profile) is not str or self.profile not in (
            "legacy_native",
            "fp32_accumulate",
        ):
            raise ValueError("Numerics profile must be legacy_native or fp32_accumulate")

    def fingerprint(self) -> dict[str, Any]:
        """Return a stable JSON-serializable contract, not an evidence/pass receipt."""
        native = self.profile == "legacy_native"
        return {
            "type": "latent_workspace_final_logit_numerics",
            "version": 1,
            "profile": self.profile,
            "scope": "final_captured_logit_composition_only",
            "whole_forward_fp32": False,
            "accumulation_dtype": "base.dtype" if native else "torch.float32",
            "base_input_cast": "none" if native else "torch.float32",
            "residual_input_cast": "base.dtype" if native else "torch.float32",
            "output_dtype": "base.dtype" if native else "torch.float32",
            "output_contract": "base + residual.to(base.dtype)"
            if native
            else "base.float() + residual.float(); keep float32",
            "true_bypass_contract": "return original base object and dtype; residual not consumed",
            "autograd": "preserved; no implicit detach",
        }

    def compose_logits(
        self,
        base: torch.Tensor,
        residual: torch.Tensor | None,
        *,
        true_bypass: bool = False,
    ) -> torch.Tensor:
        """Combine matched floating tensors, or return the exact direct base on bypass.

        Bypass permits ``residual=None`` and never evaluates a residual or an
        adapter. Ordinary composition does not broadcast shapes, move devices,
        mutate inputs, detach gradients or introduce an autocast context.
        """
        if type(true_bypass) is not bool:
            raise ValueError("true_bypass must be a boolean")
        _floating_tensor(base, "base")
        if true_bypass:
            return base
        _floating_tensor(residual, "residual")
        if base.shape != residual.shape:
            raise ValueError("Base and residual logits must have identical shapes")
        if base.device != residual.device:
            raise ValueError("Base and residual logits must be on the same device")
        if self.profile == "legacy_native":
            return base + residual.to(base.dtype)
        return base.float() + residual.float()


def _floating_tensor(value: Any, name: str) -> None:
    if not isinstance(value, torch.Tensor) or not value.is_floating_point():
        raise ValueError(f"{name} must be a floating-point tensor")


def compose_logits(
    base: torch.Tensor,
    residual: torch.Tensor | None,
    *,
    policy: NumericsPolicy = NumericsPolicy(),
    true_bypass: bool = False,
) -> torch.Tensor:
    """Shared final-logit operation; default behavior is exactly legacy arithmetic."""
    if not isinstance(policy, NumericsPolicy):
        raise ValueError("policy must be a NumericsPolicy")
    return policy.compose_logits(base, residual, true_bypass=true_bypass)
