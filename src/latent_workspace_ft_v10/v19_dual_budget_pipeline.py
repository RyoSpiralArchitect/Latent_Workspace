"""V19 text-bound pipeline over the dual-budget reader.

Query routing is the V18 selection pipeline's: the common route reads the
original final normalized state, the workspace route reads the declared
operand query, and the native head stays adapter-owned. Only the reader type
differs. No KV carry or free generation is implemented here.
"""

from __future__ import annotations

from .readout_transport import ReadoutAdapter
from .v15_full_update import validate_token_tuple
from .v15_pipeline import NativeWorkspacePipeline
from .v18_operand_query import OperandSpan, operand_reader_query, validate_operand_span
from .v18_selection_pipeline import SelectionWorkspaceOutput
from .v19_dual_budget_reader import DualBudgetWorkspaceBridge


class DualBudgetWorkspacePipeline:
    """Inference-only inputs; labels/facts never select operand positions."""

    MODES = ("final", "ordered_difference", "symmetric_mean")

    def __init__(self, bridge: DualBudgetWorkspaceBridge, adapter: ReadoutAdapter, mode: str):
        if type(bridge) is not DualBudgetWorkspaceBridge:
            raise ValueError("V19 pipeline requires the exact dual-budget reader")
        if mode not in self.MODES:
            raise ValueError("Unknown workspace query mode")
        self.bridge, self.adapter, self.mode = bridge, adapter, mode

    def describe(self):
        return {
            "schema": "v19-text-bound-dual-budget-pipeline-v1",
            "workspace_query": self.mode,
            "common_query": "original_current_final_normalized_state_fp32",
            "operand_anchor": "exact_original_inference_prefix",
            "operand_pooling": "ascending_tokens_cpu_fp32_mean_then_combine_then_return",
            "native_head": "unchanged_adapter_owned_full_sequence_full_vocabulary",
            "reader": self.bridge.describe(),
        }

    def __call__(self, prefix_ids, memory, memory_mask, *, span: OperandSpan):
        validate_operand_span(span)
        validate_token_tuple(prefix_ids, self.adapter.vocabulary)
        if prefix_ids[: len(span.prefix_ids)] != span.prefix_ids:
            raise ValueError("Runtime prefix must extend the exact bound inference prefix")
        captured = {}

        def residual(normalized):
            common_query = NativeWorkspacePipeline(None, None, "final").query(
                normalized, prefix_ids=prefix_ids, span=span.question_span
            )
            workspace_query = (
                common_query
                if self.mode == "final"
                else operand_reader_query(normalized, span, prefix_ids=prefix_ids, mode=self.mode)
            )
            delta = self.bridge.read_delta(common_query, workspace_query, memory, memory_mask)
            captured.update(delta=delta, common=common_query, interaction=workspace_query)
            return delta

        transport = self.adapter.read(prefix_ids, residual)
        return SelectionWorkspaceOutput(
            transport.readout, captured["delta"], captured["common"],
            captured["interaction"], transport,
        )
