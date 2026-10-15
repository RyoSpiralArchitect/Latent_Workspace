from __future__ import annotations

import pytest
import torch

from latent_workspace_ft_v10.precision_bridge import PrecisionAwareWorkspaceBridge
from latent_workspace_ft_v10.reader_query import QuestionSpan
from latent_workspace_ft_v10.v15_pipeline import NativeWorkspacePipeline
from latent_workspace_ft_v10.v15_readout import NativeWorkspaceReadout


def fixture(mode):
    torch.manual_seed(47)
    bridge = PrecisionAwareWorkspaceBridge(8, workspace_dim=4, heads=2, slots=2)
    torch.nn.init.normal_(bridge.up.weight, std=0.1)
    head = torch.nn.Linear(8, 7, bias=False).requires_grad_(False)
    pipe = NativeWorkspacePipeline(bridge, NativeWorkspaceReadout(head), mode)
    span = QuestionSpan("A?", 0, 2, (0, 1), (1, 2, 3), "unused")
    hidden = torch.randn(1, 5, 8)
    memory, mask = bridge.write_memory(torch.randn(1, 3, 8), torch.ones(1, 3))
    return pipe, span, hidden, memory, mask


@pytest.mark.parametrize("mode", ["final", "mean_span"])
def test_generated_suffix_never_rebinds_question_or_changes_base_anchor(mode):
    pipe, span, hidden, memory, mask = fixture(mode)
    output = pipe(hidden, memory, mask, prefix_ids=(1, 2, 3, 6, 5), span=span)
    expected_query = hidden[:, -1:] if mode == "final" else hidden[:, :2].mean(1, keepdim=True)
    torch.testing.assert_close(output.reader_query, expected_query, atol=0, rtol=0)
    expected = pipe.readout(hidden, output.delta)
    torch.testing.assert_close(output.readout.logits, expected.logits, atol=0, rtol=0)
    assert not torch.equal(hidden[:, -1:], expected_query) if mode == "mean_span" else True


def test_native_learning_flows_into_bridge_not_frozen_head():
    pipe, span, hidden, memory, mask = fixture("mean_span")
    output = pipe(hidden, memory, mask, prefix_ids=(1, 2, 3, 6, 5), span=span)
    output.readout.cross_entropy(torch.tensor([2])).backward()
    assert pipe.bridge.up.weight.grad.norm() > 0
    assert pipe.bridge.writer.context_projection.weight.grad.norm() > 0
    assert hidden.grad is None


@pytest.mark.parametrize("prefix", [(1, 4, 3, 6, 5), (1, 2), (1, 2, 3, 6)])
def test_fail_closed_on_anchor_or_sequence_length_drift(prefix):
    pipe, span, hidden, memory, mask = fixture("mean_span")
    with pytest.raises(ValueError, match="prefix"):
        pipe(hidden, memory, mask, prefix_ids=prefix, span=span)


def test_reader_mode_cannot_select_a_new_parameterization():
    pipe, _, _, _, _ = fixture("final")
    with pytest.raises(ValueError, match="mode"):
        NativeWorkspacePipeline(pipe.bridge, pipe.readout, "unknown")
