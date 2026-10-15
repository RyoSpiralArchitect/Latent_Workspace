"""Additive actual-writer wiring for controlled engineering fixtures only.

This module chooses no populations, fitting budget, numerical repair, optimizer,
or launch policy. It reuses the sealed reader/head math. Frozen containers do
not make their caller-owned tensors immutable; validate inputs again at every
write. This is not a learner/checkpoint owner or real-model qualification.
Shape checks do not authenticate factual identity or label independence inside
caller-owned tensors; those require a separately sealed population recipe.
"""

from __future__ import annotations

from dataclasses import dataclass

import assay_v18_operand_selection as assay
import torch


@dataclass(frozen=True, slots=True)
class WriterInputs:
    """Question features and fact-only context; labels/side metadata are absent."""

    states: torch.Tensor
    context: torch.Tensor
    context_mask: torch.Tensor

    def __post_init__(self):
        self.validate()

    def validate(self):
        if type(self) is not WriterInputs:
            raise ValueError("Exact controlled writer-input container required")
        if any(
            not isinstance(value, torch.Tensor)
            for value in (self.states, self.context, self.context_mask)
        ):
            raise ValueError("Writer inputs must be tensors")
        if (
            self.states.ndim != 3
            or tuple(self.states.shape[1:]) != (3, 32)
            or self.states.shape[0] < 1
            or self.context.ndim != 3
            or self.context.shape[0] != self.states.shape[0]
            or self.context.shape[1] < 1
            or self.context.shape[2] != 32
        ):
            raise ValueError("Expected controlled [B,3,32] states and [B,C,32] context")
        if self.states.dtype != torch.float32 or self.context.dtype != torch.float32:
            raise ValueError("Controlled question and factual features must be FP32")
        if (
            self.context_mask.shape != self.context.shape[:2]
            or self.context_mask.dtype not in (torch.bool, torch.int32, torch.int64)
            or len({v.device for v in (self.states, self.context, self.context_mask)}) != 1
        ):
            raise ValueError("Context mask shape, integer dtype and shared device required")
        if (
            not ((self.context_mask == 0) | (self.context_mask == 1)).all()
            or not self.context_mask.bool().any(-1).all()
        ):
            raise ValueError("Binary context mask with a valid fact in every row required")
        if not torch.isfinite(self.states).all() or not torch.isfinite(self.context).all():
            raise ValueError("Controlled writer inputs must be finite")

    def take(self, indices):
        self.validate()
        return WriterInputs(*(v[indices] for v in (self.states, self.context, self.context_mask)))

    def to(self, device):
        self.validate()
        return WriterInputs(*(v.to(device) for v in (self.states, self.context, self.context_mask)))


def partition_manifest(bridge):
    """Export the narrow fixture partition; do not confer checkpoint admission."""
    if type(bridge) is not assay.SelectionWorkspaceBridge or (
        bridge.hidden_dim, bridge.workspace_dim, bridge.slots
    ) != (32, 32, 3):
        raise ValueError("Exact controlled selection reader geometry required")
    partitions = {name: {} for name in ("writer", "common_reader", "interaction")}
    for name, parameter in bridge.named_parameters():
        partition = (
            "writer" if name.startswith("common.writer.")
            else "common_reader" if name.startswith("common.")
            else "interaction"
        )
        expected_trainable = partition != "common_reader"
        if parameter.requires_grad != expected_trainable or parameter.dtype != torch.float32:
            raise ValueError("Controlled writer/interaction-only parameter policy changed")
        partitions[partition][name] = parameter.numel()
    expected = {"writer": (20, 13952), "common_reader": (6, 6208), "interaction": (6, 6208)}
    for name, (count, elements) in expected.items():
        if len(partitions[name]) != count or sum(partitions[name].values()) != elements:
            raise ValueError("Controlled parameter denominator changed")
    if not bridge.common.up.weight.eq(0).all():
        raise ValueError("Controlled common readout must remain exactly zero")
    return {
        "schema": "v18-controlled-writer-partitions-v1",
        "partitions": partitions,
        "trainable_partitions": ["writer", "interaction"],
        "trainable_parameter_tensors": 26,
        "trainable_parameter_elements": 20160,
        "frozen_parameter_tensors": 6,
        "frozen_parameter_elements": 6208,
        "checkpoint_qualification": "NOT_ADMITTED_BY_V18_OWNER",
    }


def make_writer_reader(seed, factor, device="cpu"):
    """Preserve initial values/RNG; unfreeze only the existing writer partition."""
    bridge = assay.make_reader(seed, factor, device)
    bridge.common.writer.requires_grad_(True)
    partition_manifest(bridge)
    return bridge


def write_inputs(bridge, inputs):
    """Only facts and their mask enter the writer; use its actual output mask."""
    if type(inputs) is not WriterInputs:
        raise ValueError("Exact controlled writer-input container required")
    inputs.validate()
    partition_manifest(bridge)
    memory, memory_mask = bridge.write_memory(inputs.context, inputs.context_mask)
    return assay.Inputs(inputs.states, memory, memory_mask)


def writer_forward(bridge, inputs, factor, *, native_dtype=torch.float32, common_only=False):
    """Write actual slots, then use the sealed reader and complete native head."""
    if factor not in assay.FACTORS:
        raise ValueError("Unknown controlled writer factor")
    expected_mode = "raw_matched_control" if factor == "raw_ordered" else "slot_contrast"
    if type(bridge) is not assay.SelectionWorkspaceBridge or bridge.mode != expected_mode:
        raise ValueError("Controlled writer factor and reader mode must match")
    written = write_inputs(bridge, inputs)
    return assay.forward(
        bridge, written, factor, native_dtype=native_dtype, common_only=common_only
    )
