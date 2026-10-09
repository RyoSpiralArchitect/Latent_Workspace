"""One native full-head route for V15 training, evaluation, and generation.

The reader's query representation is deliberately not an argument here: the
residual is always applied to the original *last* normalized decoder state.
Composition is FP32, followed by a native-dtype cast and the original complete
sequence/full-vocabulary head. Selected choices are gathered only afterward.

Autograd through the BF16 cast uses PyTorch's surrogate derivative; it is not
the derivative of a discrete quantizer. A nonzero training gradient therefore
does not establish that a finite residual changes native logits. Callers must
also measure ``applied_delta`` and actual native output differences.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from numbers import Integral

import torch
from torch import nn
from torch.nn import functional as F

_NATIVE_DTYPES = (torch.float32, torch.bfloat16)


def _finite(value: torch.Tensor, name: str) -> None:
    if not bool(torch.isfinite(value).all()):
        raise ValueError(f"{name} contains nonfinite values")


def _candidate_indices(
    candidate_ids: Sequence[int] | torch.Tensor, vocabulary: int, device: torch.device
) -> torch.Tensor:
    if isinstance(candidate_ids, torch.Tensor):
        if candidate_ids.ndim != 1 or candidate_ids.dtype not in (torch.int32, torch.int64):
            raise ValueError("Candidate IDs must be a one-dimensional integer tensor")
        if candidate_ids.device != device:
            raise ValueError("Candidate IDs and logits must share a device")
        indices = candidate_ids.to(dtype=torch.long)
    else:
        if not isinstance(candidate_ids, Sequence) or isinstance(candidate_ids, (str, bytes)):
            raise ValueError("Candidate IDs must be an integer sequence or tensor")
        if any(
            not isinstance(value, Integral) or isinstance(value, bool) for value in candidate_ids
        ):
            raise ValueError("Candidate IDs must be integers, not floats or booleans")
        indices = torch.tensor(tuple(candidate_ids), dtype=torch.long, device=device)
    if not indices.numel() or indices.unique().numel() != indices.numel():
        raise ValueError("Candidate IDs must be nonempty and distinct")
    if bool(((indices < 0) | (indices >= vocabulary)).any()):
        raise ValueError("Candidate ID lies outside the language-model vocabulary")
    return indices


@dataclass(frozen=True, slots=True)
class NativeReadoutResult:
    """Native outputs with a differentiable path back to the FP32 residual."""

    logits: torch.Tensor
    applied_delta: torch.Tensor
    corrected_last_hidden_fp32: torch.Tensor

    @property
    def last_logits(self) -> torch.Tensor:
        """FP32 view/cast of actual native last-token logits, not a second head."""
        return self.logits[:, -1].float()

    def choice_scores(self, candidate_ids: Sequence[int] | torch.Tensor) -> torch.Tensor:
        """Return [B,C] gathered native logits, sharing the generation readout."""
        indices = _candidate_indices(candidate_ids, self.logits.shape[-1], self.logits.device)
        return self.last_logits.index_select(-1, indices)

    def cross_entropy(self, target_ids: torch.Tensor) -> torch.Tensor:
        """Mean full-vocabulary next-token CE; targets cannot be ignored or masked."""
        if not isinstance(target_ids, torch.Tensor):
            raise TypeError("Target IDs must be an integer tensor")
        if target_ids.dtype not in (torch.int32, torch.int64):
            raise TypeError("Target IDs must have integer dtype")
        if tuple(target_ids.shape) != (self.logits.shape[0],):
            raise ValueError("Target IDs must have shape [B]")
        if target_ids.device != self.logits.device:
            raise ValueError("Target IDs and logits must share a device")
        if bool(((target_ids < 0) | (target_ids >= self.logits.shape[-1])).any()):
            raise ValueError("Target ID lies outside the language-model vocabulary")
        return F.cross_entropy(self.last_logits, target_ids.long())


class NativeWorkspaceReadout(nn.Module):
    """Architecture-independent native head adapter for a frozen linear LM head.

    No parameters are added and the constructor does not freeze or otherwise mutate
    the supplied head. Its owner must freeze it first. This adapter has no label,
    reader-pooling, normalization, KV-cache, sampling, or context-persistence policy.
    The callable is identical in train/eval modes and keeps residual gradients.
    """

    def __init__(self, head: nn.Linear) -> None:
        super().__init__()
        if not isinstance(head, nn.Linear):
            raise TypeError("NativeWorkspaceReadout requires an nn.Linear language-model head")
        self.head = head
        self._validate_head()
        _finite(head.weight, "Language-model head weight")
        if head.bias is not None:
            _finite(head.bias, "Language-model head bias")

    def _validate_head(self) -> None:
        head = self.head
        if head.weight.ndim != 2 or min(head.weight.shape) < 1:
            raise ValueError("Language-model head weight must be nonempty [V,H]")
        if head.weight.dtype not in _NATIVE_DTYPES:
            raise TypeError("Language-model head must have native float32 or bfloat16 dtype")
        if any(parameter.requires_grad for parameter in head.parameters()):
            raise ValueError("Language-model head must be frozen before using this readout")
        if head.bias is not None and (
            tuple(head.bias.shape) != (head.weight.shape[0],)
            or head.bias.dtype != head.weight.dtype
            or head.bias.device != head.weight.device
        ):
            raise ValueError("Language-model head bias must match weight shape/dtype/device")

    def _validate_inputs(self, normalized: torch.Tensor, delta: torch.Tensor) -> None:
        self._validate_head()
        if not isinstance(normalized, torch.Tensor) or not isinstance(delta, torch.Tensor):
            raise TypeError("Normalized prefix and residual must be tensors")
        if (
            normalized.ndim != 3
            or normalized.shape[0] < 1
            or normalized.shape[1] < 1
            or normalized.shape[-1] != self.head.weight.shape[1]
        ):
            raise ValueError("Normalized prefix must be nonempty [B,L,head_hidden_dim]")
        if tuple(delta.shape) != (normalized.shape[0], 1, normalized.shape[-1]):
            raise ValueError("Residual must have shape [B,1,head_hidden_dim]")
        if normalized.dtype != self.head.weight.dtype:
            raise TypeError("Normalized prefix dtype must match the native language-model head")
        if delta.dtype != torch.float32:
            raise TypeError("Residual must have float32 dtype")
        if normalized.device != delta.device or normalized.device != self.head.weight.device:
            raise ValueError("Prefix, residual and language-model head must share a device")
        _finite(normalized, "Normalized prefix")
        _finite(delta, "Residual")

    def forward(self, normalized: torch.Tensor, delta: torch.Tensor) -> NativeReadoutResult:
        self._validate_inputs(normalized, delta)
        # Keep both the original sequence length and full vocabulary GEMM. A
        # last-row or selected-head-row GEMM need not be numerically identical.
        with torch.autocast(device_type=normalized.device.type, enabled=False):
            corrected_fp32 = normalized[:, -1:].float() + delta
            corrected_native = corrected_fp32.to(normalized.dtype)
            sequence = torch.cat((normalized[:, :-1], corrected_native), dim=1)
            logits = self.head(sequence)
            applied = corrected_native.float() - normalized[:, -1:].float()
        if not isinstance(logits, torch.Tensor) or tuple(logits.shape) != (
            normalized.shape[0],
            normalized.shape[1],
            self.head.weight.shape[0],
        ):
            raise ValueError("Head must preserve full sequence/full vocabulary geometry")
        if logits.dtype != normalized.dtype or logits.device != normalized.device:
            raise ValueError("Head logits must preserve native dtype and device")
        _finite(logits, "Native logits")
        return NativeReadoutResult(logits, applied, corrected_fp32)

    @torch.no_grad()
    def legacy_fp32_choices(
        self,
        normalized: torch.Tensor,
        delta: torch.Tensor,
        candidate_ids: Sequence[int] | torch.Tensor,
    ) -> torch.Tensor:
        """Diagnostic-only [B,C] legacy selected-row FP32 scores, never a loss path.

        This is intentionally detached by ``no_grad`` to prevent an accidental
        fallback from native training to the numerically different legacy head.
        """
        self._validate_inputs(normalized, delta)
        indices = _candidate_indices(candidate_ids, self.head.weight.shape[0], normalized.device)
        with torch.autocast(device_type=normalized.device.type, enabled=False):
            corrected = normalized[:, -1:].float() + delta
            weight = self.head.weight.index_select(0, indices).float()
            bias = self.head.bias
            selected_bias = bias.index_select(0, indices).float() if bias is not None else None
            scores = F.linear(corrected, weight, selected_bias)[:, 0]
        _finite(scores, "Legacy FP32 choice scores")
        return scores
