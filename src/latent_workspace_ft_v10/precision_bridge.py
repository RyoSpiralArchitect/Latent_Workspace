"""Compact workspace residuals with architecture-owned post-norm readout.

This is a new post-final-normalization route, not a numerical replacement for
the legacy layer-16 injection route.  The core sees neither candidate IDs nor
labels.  The caller owns base-model freezing and training/evaluation splits.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import torch
from torch import nn
from torch.nn import functional as F

from .workspace_core import FunctionalMemoryWriter


def _finite(value: torch.Tensor, name: str) -> None:
    if not torch.isfinite(value).all():
        raise ValueError(f"{name} contains nonfinite values")


def _mask(mask: torch.Tensor, shape: tuple[int, int], device: torch.device) -> None:
    if tuple(mask.shape) != shape or mask.device != device:
        raise ValueError("Attention mask shape/device does not match its tensor")
    if not ((mask == 0) | (mask == 1)).all():
        raise ValueError("Attention mask must be binary")
    if not mask.bool().any(dim=1).all():
        raise ValueError("Every example requires at least one unmasked token")


class PrecisionAwareWorkspaceBridge(nn.Module):
    """Query-independent slot writer plus a compact, memory-dependent reader.

    The reader is bias-free along the memory-to-output path, including an
    affine-free memory normalizer.  Consequently zeroing *written memory* gives
    exactly zero correction, even after training.  Zeroing source context is not
    the same intervention because the writer has learned slot seeds and biases.
    All bridge parameters and computation remain FP32 under outer autocast.
    """

    def __init__(
        self,
        hidden_dim: int,
        workspace_dim: int = 256,
        heads: int = 8,
        slots: int = 4,
        max_delta_norm: float = 0.25,
    ) -> None:
        super().__init__()
        if any(
            int(value) != value or value < 1 for value in (hidden_dim, workspace_dim, heads, slots)
        ):
            raise ValueError("Bridge dimensions, heads and slots must be positive integers")
        if workspace_dim % heads:
            raise ValueError("workspace_dim must be divisible by heads")
        if not math.isfinite(max_delta_norm) or max_delta_norm <= 0:
            raise ValueError("max_delta_norm must be finite and positive")
        self.hidden_dim = int(hidden_dim)
        self.workspace_dim = int(workspace_dim)
        self.slots = int(slots)
        self.max_delta_norm = float(max_delta_norm)
        self.writer = FunctionalMemoryWriter(
            self.hidden_dim,
            self.workspace_dim,
            mode="slots",
            slot_count=self.slots,
            steps=1,
            heads=int(heads),
            dropout=0.0,
        )
        self.query_projection = nn.Linear(self.hidden_dim, self.workspace_dim, bias=False)
        self.query_norm = nn.LayerNorm(self.workspace_dim)
        self.memory_norm = nn.LayerNorm(self.workspace_dim, elementwise_affine=False)
        self.attention = nn.MultiheadAttention(
            self.workspace_dim, int(heads), dropout=0.0, bias=False, batch_first=True
        )
        self.up = nn.Linear(self.workspace_dim, self.hidden_dim, bias=False)
        nn.init.zeros_(self.up.weight)
        self.float()

    def _validate_parameters(self, device: torch.device) -> None:
        if any(parameter.dtype != torch.float32 for parameter in self.parameters()):
            raise TypeError("PrecisionAwareWorkspaceBridge parameters must remain float32")
        if any(parameter.device != device for parameter in self.parameters()):
            raise ValueError("Bridge parameters and input must share a device")

    def write_memory(
        self, context: torch.Tensor, mask: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Write [B,C,H] frozen context features into [B,slots,D] FP32 memory."""
        if context.ndim != 3 or context.shape[-1] != self.hidden_dim:
            raise ValueError("Writer expects context [B,C,hidden_dim]")
        if context.shape[0] < 1 or context.shape[1] < 1 or not context.is_floating_point():
            raise ValueError("Writer context must be nonempty and floating point")
        _mask(mask, tuple(context.shape[:2]), context.device)
        _finite(context, "Context")
        self._validate_parameters(context.device)
        with torch.autocast(device_type=context.device.type, enabled=False):
            memory, memory_mask, _, _ = self.writer(context.float(), mask)
        _finite(memory, "Written memory")
        return memory, memory_mask

    def read_delta(
        self,
        normalized_last_hidden: torch.Tensor,
        memory: torch.Tensor,
        mask: torch.Tensor,
    ) -> torch.Tensor:
        """Return an FP32 [B,1,H] residual with L2 norm at most the fixed cap."""
        query = normalized_last_hidden
        if query.ndim == 2:
            query = query.unsqueeze(1)
        if query.ndim != 3 or query.shape[1:] != (1, self.hidden_dim):
            raise ValueError("Reader query must have shape [B,1,hidden_dim] or [B,hidden_dim]")
        if (
            memory.ndim != 3
            or memory.shape[0] != query.shape[0]
            or memory.shape[-1] != self.workspace_dim
        ):
            raise ValueError("Reader memory must have shape [B,S,workspace_dim]")
        if query.shape[0] < 1 or memory.shape[1] < 1:
            raise ValueError("Reader inputs must be nonempty")
        if (
            query.device != memory.device
            or not query.is_floating_point()
            or not memory.is_floating_point()
        ):
            raise ValueError("Reader inputs must be floating point on the same device")
        _mask(mask, tuple(memory.shape[:2]), memory.device)
        _finite(query, "Query")
        _finite(memory, "Memory")
        self._validate_parameters(query.device)
        with torch.autocast(device_type=query.device.type, enabled=False):
            projected_query = self.query_norm(self.query_projection(query.float()))
            normalized_memory = self.memory_norm(memory.float())
            read, _ = self.attention(
                projected_query,
                normalized_memory,
                normalized_memory,
                key_padding_mask=~mask.bool(),
                need_weights=False,
            )
            raw_delta = self.up(read)
            # Unlike clipping, this has a finite derivative of one at zero.
            scale = self.max_delta_norm / torch.sqrt(
                self.max_delta_norm**2 + raw_delta.square().sum(dim=-1, keepdim=True)
            )
            delta = raw_delta * scale
        _finite(delta, "Bridge residual")
        return delta


@dataclass(frozen=True, slots=True)
class BridgeReadoutState:
    """Native and FP32 heads applied to a common, explicitly bounded residual."""

    native_logits: torch.Tensor
    native_choice_scores: torch.Tensor
    fp32_choice_scores: torch.Tensor
    corrected_last_hidden_fp32: torch.Tensor
    native_applied_delta: torch.Tensor


class MistralPrecisionBridgeAdapter:
    """Keep native Mistral normalization and head arithmetic out of the core.

    Native readout casts the corrected last state back to native dtype, preserving
    the complete sequence/full-vocabulary GEMM.  FP32 readout selects head rows
    and adds the residual in FP32, without a second native-dtype quantization.
    This selected-row FP32 operation is a distinct readout, not full-model FP32.
    """

    def __init__(self, boundary_adapter: Any) -> None:
        if getattr(boundary_adapter, "_kind", None) != "mistral":
            raise TypeError("MistralPrecisionBridgeAdapter requires a Mistral boundary adapter")
        self.boundary_adapter = boundary_adapter
        self.base_model = getattr(boundary_adapter, "base_model", None)
        self.decoder = getattr(self.base_model, "model", None)
        if self.decoder is None or any(
            getattr(self.decoder, name, None) is None for name in ("layers", "norm")
        ):
            raise TypeError("Mistral decoder layout is incomplete")
        self.head = getattr(self.base_model, "lm_head", None)
        if self.head is None or not isinstance(getattr(self.head, "weight", None), torch.Tensor):
            raise TypeError("Mistral language-model head is unavailable")
        if self.head.weight.ndim != 2:
            raise ValueError("Language-model head must have a rank-2 weight")
        if not callable(getattr(boundary_adapter, "encode", None)) or not callable(
            getattr(boundary_adapter, "_run_mistral_layers", None)
        ):
            raise TypeError("Mistral split encoder/layer runner is unavailable")

    def encode_prefix(
        self, ids: torch.Tensor, mask: torch.Tensor, boundary_layer: int = 16
    ) -> torch.Tensor:
        """Return native normalized [B,L,H] features; no KV cache is involved."""
        if ids.ndim != 2 or ids.shape[0] < 1 or ids.shape[1] < 1:
            raise ValueError("Prefix IDs must be nonempty [B,L]")
        if ids.dtype not in (torch.int32, torch.int64):
            raise ValueError("Prefix IDs must be integer tensors")
        _mask(mask, tuple(ids.shape), ids.device)
        if not mask[:, -1].bool().all():
            raise ValueError("Final prefix position must be unmasked; use left padding")
        if int(boundary_layer) != boundary_layer or not 0 <= boundary_layer <= len(
            self.decoder.layers
        ):
            raise ValueError("Boundary layer lies outside the Mistral decoder")
        boundary = int(boundary_layer)
        hidden = self.boundary_adapter.encode(ids, mask, boundary)
        upper = self.boundary_adapter._run_mistral_layers(
            hidden, mask, self.decoder.layers[boundary:]
        )
        normalized = self.decoder.norm(upper)
        _finite(normalized, "Normalized prefix")
        return normalized

    def decode(
        self,
        normalized: torch.Tensor,
        delta: torch.Tensor,
        candidate_ids: Sequence[int],
    ) -> BridgeReadoutState:
        if (
            normalized.ndim != 3
            or normalized.shape[0] < 1
            or normalized.shape[1] < 1
            or normalized.shape[-1] != self.head.weight.shape[1]
        ):
            raise ValueError("Normalized prefix must have shape [B,L,head_hidden_dim]")
        if tuple(delta.shape) != (normalized.shape[0], 1, normalized.shape[-1]):
            raise ValueError("Bridge residual must have shape [B,1,head_hidden_dim]")
        if not normalized.is_floating_point() or delta.dtype != torch.float32:
            raise TypeError("Normalized prefix must be floating point and residual must be float32")
        if normalized.device != delta.device or normalized.device != self.head.weight.device:
            raise ValueError("Prefix, residual and language-model head must share a device")
        _finite(normalized, "Normalized prefix")
        _finite(delta, "Bridge residual")
        candidates = tuple(int(value) for value in candidate_ids)
        if (
            len(candidates) != 2
            or candidates[0] == candidates[1]
            or any(value != original for value, original in zip(candidates, candidate_ids))
        ):
            raise ValueError("Readout requires two distinct integer candidate token IDs")
        if min(candidates) < 0 or max(candidates) >= self.head.weight.shape[0]:
            raise ValueError("Candidate token ID lies outside the language-model head")
        indices = torch.tensor(candidates, dtype=torch.long, device=normalized.device)
        with torch.autocast(device_type=normalized.device.type, enabled=False):
            corrected_fp32 = normalized[:, -1:].float() + delta
        corrected_native = corrected_fp32.to(normalized.dtype)
        native_sequence = torch.cat((normalized[:, :-1], corrected_native), dim=1)
        native_logits = self.head(native_sequence)
        native_scores = native_logits[:, -1:].index_select(-1, indices).float()
        with torch.autocast(device_type=normalized.device.type, enabled=False):
            selected_weight = self.head.weight.index_select(0, indices).float()
            bias = getattr(self.head, "bias", None)
            selected_bias = (
                bias.index_select(0, indices).float() if isinstance(bias, torch.Tensor) else None
            )
            fp32_scores = F.linear(corrected_fp32, selected_weight, selected_bias)
            applied = corrected_native.float() - normalized[:, -1:].float()
        _finite(native_scores, "Native choice scores")
        _finite(fp32_scores, "FP32 choice scores")
        return BridgeReadoutState(
            native_logits, native_scores, fp32_scores, corrected_fp32, applied
        )
