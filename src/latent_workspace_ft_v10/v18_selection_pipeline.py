"""Text-bound selection prototype over the model-neutral readout protocol.

The final-position common query and native head remain unchanged. Only the
interaction query is selected. This is NOT admitted by an existing learner or
checkpoint owner, and does not implement KV carry or free generation.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch

from .readout_transport import ReadoutAdapter, TransportReadout
from .v15_full_update import validate_token_tuple
from .v15_pipeline import NativeWorkspacePipeline
from .v15_readout import NativeReadoutResult
from .v18_operand_query import OperandSpan, operand_reader_query, validate_operand_span
from .v18_selection_reader import SelectionWorkspaceBridge


@dataclass
class SelectionWorkspaceOutput:
    readout: NativeReadoutResult
    delta: torch.Tensor
    common_query: torch.Tensor
    interaction_query: torch.Tensor
    transport: TransportReadout


class SelectionWorkspacePipeline:
    """Inference-only inputs; labels/facts never select operand positions."""

    MODES = ("final", "ordered_difference", "symmetric_mean")

    def __init__(
        self, bridge: SelectionWorkspaceBridge, adapter: ReadoutAdapter, mode: str
    ):
        if type(bridge) is not SelectionWorkspaceBridge:
            raise ValueError("Selection pipeline requires the explicit split-query prototype")
        if mode not in self.MODES:
            raise ValueError("Unknown selection query mode")
        self.bridge, self.adapter, self.mode = bridge, adapter, mode

    def describe(self):
        return {
            "schema": "v18-text-bound-selection-pipeline-v1",
            "interaction_query": self.mode,
            "common_query": "original_current_final_normalized_state_fp32",
            "operand_anchor": "exact_original_inference_prefix",
            "operand_pooling": "ascending_tokens_cpu_fp32_mean_then_combine_then_return",
            "native_head": "unchanged_adapter_owned_full_sequence_full_vocabulary",
            "checkpoint_qualification": "NOT_ADMITTED_BY_V18_OWNER",
            "reader": self.bridge.describe(),
        }

    def __call__(self, prefix_ids, memory, memory_mask, *, span: OperandSpan):
        validate_operand_span(span)
        validate_token_tuple(prefix_ids, self.adapter.vocabulary)
        if prefix_ids[: len(span.prefix_ids)] != span.prefix_ids:
            raise ValueError("Runtime prefix must extend the exact bound inference prefix")
        captured = {}

        def residual(normalized):
            # No stored mutable query-policy object may redirect the common
            # route while the descriptor still declares a final-state query.
            common_query = NativeWorkspacePipeline(None, None, "final").query(
                normalized, prefix_ids=prefix_ids, span=span.question_span
            )
            interaction_query = (
                common_query
                if self.mode == "final"
                else operand_reader_query(normalized, span, prefix_ids=prefix_ids, mode=self.mode)
            )
            delta = self.bridge.read_delta(common_query, interaction_query, memory, memory_mask)
            captured.update(delta=delta, common=common_query, interaction=interaction_query)
            return delta

        transport = self.adapter.read(prefix_ids, residual)
        return SelectionWorkspaceOutput(
            transport.readout, captured["delta"], captured["common"],
            captured["interaction"], transport,
        )
