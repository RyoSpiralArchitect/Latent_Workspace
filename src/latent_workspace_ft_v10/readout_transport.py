"""Model-neutral residual transport and paired, diagnostic-only localization.

No normalization, model layout, logit transformation or label policy lives here.
The native adapter owns those operations. FP64 linear projections are explicitly
diagnostics, never replacement logits or a differentiable objective.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

import torch

from .v15_readout import NativeReadoutResult, _candidate_indices, _finite


@dataclass(frozen=True)
class ResidualInjection:
    sequence: torch.Tensor
    original_last: torch.Tensor
    intended_delta: torch.Tensor
    corrected_last_fp32: torch.Tensor
    applied_delta: torch.Tensor


def inject_last(normalized: torch.Tensor, delta: torch.Tensor) -> ResidualInjection:
    """Historical FP32 add -> native cast, preserving the entire head geometry."""
    if not isinstance(normalized, torch.Tensor) or not isinstance(delta, torch.Tensor):
        raise TypeError("Readout input and residual must be tensors")
    if normalized.ndim != 3 or min(normalized.shape) < 1:
        raise ValueError("Readout input must be nonempty [B,L,H]")
    if normalized.dtype not in (torch.float32, torch.bfloat16):
        raise TypeError("Only float32/bfloat16 native input is currently qualified")
    if delta.shape != (normalized.shape[0], 1, normalized.shape[-1]):
        raise ValueError("Residual must be [B,1,H]")
    if delta.dtype != torch.float32 or delta.device != normalized.device:
        raise ValueError("Residual must be FP32 on the native input device")
    _finite(normalized, "Native head input")
    _finite(delta, "Intended residual")
    with torch.autocast(normalized.device.type, enabled=False):
        original = normalized[:, -1:]
        corrected = original.float() + delta
        native = corrected.to(normalized.dtype)
        sequence = torch.cat((normalized[:, :-1], native), dim=1)
        applied = native.float() - original.float()
    _finite(sequence, "Injected head input")
    return ResidualInjection(sequence, original, delta, corrected, applied)


@dataclass(frozen=True)
class TransportReadout:
    readout: NativeReadoutResult
    injection: ResidualInjection
    head_logits: torch.Tensor
    prefix_ids: tuple[int, ...]
    # Process-local identity/version guard, NOT a checkpoint content hash.
    execution_key: tuple
    linear_probe_key: tuple | None = None


class ReadoutAdapter(Protocol):
    """Opt-in backend contract: all native operations remain adapter-owned."""

    @property
    def vocabulary(self) -> int: ...

    def describe(self) -> dict: ...

    def read(
        self, prefix_ids: tuple[int, ...], residual: Callable[[torch.Tensor], torch.Tensor]
    ) -> TransportReadout: ...


@torch.no_grad()
def compare_transport(
    left: TransportReadout,
    right: TransportReadout,
    candidate_ids: Sequence[int],
    *,
    linear_weight: torch.Tensor,
) -> dict:
    """Same-prefix/current-weight intervention; exactly two diagnostic head rows.

    The gap is candidate[1] - candidate[0], not a donor-labelled margin. A caller
    may interpret its direction afterward. Requires a *linear* raw head; a new
    nonlinear-head backend must supply a different probe, not fake a weight.
    The caller must provide the matching adapter's current linear weight.
    """
    if left.prefix_ids != right.prefix_ids or left.execution_key != right.execution_key:
        raise ValueError("Transport comparison requires the same prefix and model version")
    if not torch.equal(left.injection.original_last, right.injection.original_last):
        raise ValueError("Transport comparison changed the native input state")
    if left.readout.logits.shape != right.readout.logits.shape:
        raise ValueError("Transport comparison changed output geometry")
    weight_key = (id(linear_weight), linear_weight._version)
    if left.linear_probe_key != weight_key or right.linear_probe_key != weight_key:
        raise ValueError("Diagnostic weight is not the captured native head version")
    indices = _candidate_indices(candidate_ids, left.readout.logits.shape[-1], linear_weight.device)
    if indices.numel() != 2:
        raise ValueError("Transport probe requires exactly two candidate IDs")
    if linear_weight.shape != (
        left.readout.logits.shape[-1],
        left.injection.original_last.shape[-1],
    ):
        raise ValueError("Diagnostic linear head geometry mismatch")
    _finite(linear_weight, "Diagnostic linear weight")
    weights = linear_weight.index_select(0, indices).detach().cpu().double()
    axis = weights[1] - weights[0]
    intended = (
        right.injection.intended_delta.detach().cpu().double()
        - left.injection.intended_delta.detach().cpu().double()
    )
    applied = (
        right.injection.applied_delta.detach().cpu().double()
        - left.injection.applied_delta.detach().cpu().double()
    )
    ids = indices.cpu()

    def gap(logits):
        values = logits[:, -1].detach().cpu().double().index_select(-1, ids)
        return values[:, 1] - values[:, 0]

    ideal = (intended[:, 0] * axis).sum(-1)
    after_cast = (applied[:, 0] * axis).sum(-1)
    raw_change = gap(right.head_logits) - gap(left.head_logits)
    final_change = gap(right.readout.logits) - gap(left.readout.logits)
    return {
        "scope": "paired_same_prefix_current_weights_not_semantic_qualification",
        "gap_definition": "candidate_1_minus_candidate_0",
        "candidate_ids": ids.tolist(),
        "intended_delta_difference_l2": intended.flatten(1).norm(dim=-1).tolist(),
        "applied_delta_difference_l2": applied.flatten(1).norm(dim=-1).tolist(),
        "intended_linear_gap_change_fp64": ideal.tolist(),
        "after_input_cast_linear_gap_change_fp64": after_cast.tolist(),
        "native_head_gap_change": raw_change.tolist(),
        "native_published_gap_change": final_change.tolist(),
        "input_cast_gap_residual": (after_cast - ideal).tolist(),
        "head_arithmetic_gap_residual": (raw_change - after_cast).tolist(),
        "model_postprocessing_gap_residual": (final_change - raw_change).tolist(),
        "changed_last_vocab_elements": (right.readout.last_logits != left.readout.last_logits)
        .sum(-1)
        .tolist(),
        "greedy_token_changed": (
            right.readout.last_logits.argmax(-1) != left.readout.last_logits.argmax(-1)
        ).tolist(),
        "fp64_probe_is_native_logits": False,
    }
