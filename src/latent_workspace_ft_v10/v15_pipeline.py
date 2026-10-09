"""Shared workspace/readout entry point for native learning, assays and decoding.

The question span is anchored in the original inference prefix. Generated text
cannot redefine that span. This does not add persistent hidden state or KV carry.
Labels are accepted only by loss functions on the returned native readout.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch

from .reader_query import QuestionSpan, base_readout_hidden, reader_query_hidden
from .v15_readout import NativeReadoutResult, NativeWorkspaceReadout


@dataclass
class WorkspaceOutput:
    readout: NativeReadoutResult
    delta: torch.Tensor
    reader_query: torch.Tensor


class NativeWorkspacePipeline:
    def __init__(self, bridge, readout: NativeWorkspaceReadout, mode: str):
        if mode not in ("final", "mean_span"):
            raise ValueError("Unknown reader mode")
        self.bridge, self.readout, self.mode = bridge, readout, mode

    def query(self, normalized, *, prefix_ids, span: QuestionSpan):
        prefix = tuple(prefix_ids)
        anchor = span.prefix_ids
        if prefix[: len(anchor)] != anchor or len(prefix) != normalized.shape[1]:
            raise ValueError("Runtime prefix must extend the exact bound inference prefix")
        if normalized.shape[0] != 1:
            raise ValueError("One unpadded prefix required for native parity")
        if self.mode == "final":
            return base_readout_hidden(normalized).float()
        # Retain the checkpoint's training-time CPU FP32 reduction geometry.
        # Only a frozen prefix is moved; changing reduction device is a separate
        # numerical intervention, not part of this readout-integration assay.
        return reader_query_hidden(
            normalized[:, : len(anchor)].to("cpu"), span, prefix_ids=anchor, mode="mean_span"
        ).to(normalized.device)

    def delta(self, normalized, memory, memory_mask, *, prefix_ids, span):
        query = self.query(normalized, prefix_ids=prefix_ids, span=span)
        return self.bridge.read_delta(query, memory, memory_mask), query

    def __call__(self, normalized, memory, memory_mask, *, prefix_ids, span):
        delta, query = self.delta(normalized, memory, memory_mask, prefix_ids=prefix_ids, span=span)
        return WorkspaceOutput(self.readout(normalized, delta), delta, query)
