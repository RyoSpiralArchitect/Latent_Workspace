from __future__ import annotations

import json
import math

import pytest
import torch

from latent_workspace_ft_v10.bridge_mechanistic import (
    intervention_delta,
    parameter_norms,
    summarize_trace,
    trace_reader,
)
from latent_workspace_ft_v10.precision_bridge import PrecisionAwareWorkspaceBridge


def _fixture():
    torch.manual_seed(173)
    bridge = PrecisionAwareWorkspaceBridge(12, workspace_dim=8, heads=2, slots=4)
    torch.nn.init.normal_(bridge.up.weight, std=0.2)
    return bridge, torch.randn(2, 1, 12), torch.randn(2, 4, 8), torch.ones(2, 4)


def test_trace_preserves_production_and_reconstructs_fp32_reader():
    bridge, query, memory, mask = _fixture()
    expected = bridge.read_delta(query, memory, mask)
    trace = trace_reader(bridge, query, memory, mask)
    torch.testing.assert_close(trace["delta"], expected, rtol=0, atol=0)
    for left, right in (("manual_attention_output", "attention_output"), ("manual_delta", "delta")):
        torch.testing.assert_close(trace[left], trace[right], atol=1e-6, rtol=1e-5)
    torch.testing.assert_close(
        intervention_delta(bridge, trace, "manual_original"), expected, atol=1e-6, rtol=1e-5
    )
    torch.testing.assert_close(
        trace["mean_value_raw_delta"] + trace["centered_value_raw_delta"],
        trace["raw_delta"],
        atol=1e-6,
        rtol=1e-5,
    )
    assert trace["attention_weights"].shape == (2, 2, 1, 4)
    assert not any(value.requires_grad for value in trace.values())
    assert not bridge.attention._forward_hooks
    summary = summarize_trace(trace, candidate_head_weight=torch.randn(2, 12))
    assert summary["manual_attention_allclose"] and summary["manual_delta_allclose"]
    assert summary["attention_maximum_entropy_mean"] == pytest.approx(math.log(4))
    assert parameter_norms(bridge)["attention.out_proj.weight"] > 0
    json.dumps(summary, allow_nan=False)


def test_collapsed_memory_removes_query_dependence_and_centered_value_path():
    bridge, query, memory, mask = _fixture()
    memory = memory[:, :1].expand(-1, 4, -1).clone()
    trace = trace_reader(bridge, query, memory, mask)
    donor = trace_reader(bridge, -query, memory, mask)
    for mode in ("query_zero", "query_swap", "uniform_attention", "alternate_query_attention"):
        torch.testing.assert_close(
            intervention_delta(bridge, trace, mode, donor), trace["delta"], atol=1e-7, rtol=1e-5
        )
    centered = intervention_delta(bridge, trace, "centered_values")
    assert torch.count_nonzero(centered) == 0
    summary = summarize_trace(trace)
    assert summary["values"]["within_mean_rms"] == 0
    assert summary["normalized_memory"]["pairwise_cosine_mean"] == pytest.approx(1)
    assert summary["attention_entropy_mean"] == pytest.approx(math.log(4))


def test_query_swap_is_local_and_matches_actual_alternate_query():
    bridge, query, memory, mask = _fixture()
    trace = trace_reader(bridge, query, memory, mask)
    donor = trace_reader(bridge, -query, memory, mask)
    swapped = intervention_delta(bridge, trace, "query_swap", donor)
    assert not torch.allclose(swapped, trace["delta"], atol=1e-5, rtol=1e-5)
    torch.testing.assert_close(swapped, donor["delta"], rtol=0, atol=0)
    torch.testing.assert_close(
        intervention_delta(bridge, trace, "alternate_query_attention", donor),
        swapped,
        atol=1e-6,
        rtol=1e-5,
    )
    torch.testing.assert_close(
        intervention_delta(bridge, trace, "query_zero"),
        intervention_delta(bridge, trace, "uniform_attention"),
        atol=1e-6,
        rtol=1e-5,
    )
    torch.testing.assert_close(
        intervention_delta(bridge, trace, "mean_values"),
        intervention_delta(bridge, trace, "uniform_attention"),
        atol=1e-6,
        rtol=1e-5,
    )
    torch.testing.assert_close(
        intervention_delta(bridge, trace, "slot_permutation"), trace["delta"], atol=1e-6, rtol=1e-5
    )


def test_centering_preserves_weights_and_respects_mask_before_cap():
    bridge, query, memory, mask = _fixture()
    mask[:, -1] = 0
    trace = trace_reader(bridge, query, memory, mask)
    changed = memory.clone()
    changed[:, -1] *= 1000
    changed_trace = trace_reader(bridge, query, changed, mask)
    centered = intervention_delta(bridge, trace, "centered_values")
    torch.testing.assert_close(
        centered, intervention_delta(bridge, changed_trace, "centered_values"), atol=0, rtol=0
    )
    active = mask[:, None, :, None]
    mean = (trace["v_heads"] * active).sum(-2, keepdim=True) / active.sum(-2, keepdim=True)
    read = (
        torch.matmul(trace["attention_weights"], trace["v_heads"] - mean)
        .transpose(1, 2)
        .reshape(2, 1, 8)
    )
    raw = bridge.up(bridge.attention.out_proj(read))
    expected = (
        raw
        * bridge.max_delta_norm
        / torch.sqrt(bridge.max_delta_norm**2 + raw.square().sum(-1, keepdim=True))
    )
    torch.testing.assert_close(centered, expected, atol=1e-7, rtol=1e-5)
    assert (torch.linalg.vector_norm(centered, dim=-1) <= bridge.max_delta_norm).all()
    assert not torch.count_nonzero(trace["attention_weights"][..., -1])


def test_axis_projection_preserves_selected_margin_and_does_not_inflate_norm():
    bridge, query, memory, mask = _fixture()
    trace = trace_reader(bridge, query, memory, mask)
    head = torch.randn(2, 12)
    axis = head[1] - head[0]
    projected = intervention_delta(bridge, trace, "candidate_axis", candidate_axis=axis)
    torch.testing.assert_close((projected * axis).sum(-1), (trace["delta"] * axis).sum(-1))
    assert (
        torch.linalg.vector_norm(projected, dim=-1)
        <= torch.linalg.vector_norm(trace["delta"], dim=-1)
    ).all()


def test_guards_and_cleanup_after_invalid_production_input():
    bridge, query, memory, mask = _fixture()
    with pytest.raises(ValueError, match="unmasked"):
        trace_reader(bridge, query, memory, torch.zeros_like(mask))
    for module in (bridge.query_norm, bridge.memory_norm, bridge.attention, bridge.up):
        assert not module._forward_hooks
    trace = trace_reader(bridge, query, memory, mask)
    with pytest.raises(ValueError, match="requires donor_trace"):
        intervention_delta(bridge, trace, "query_swap")
    donor = trace_reader(bridge, -query, -memory, mask)
    with pytest.raises(ValueError, match="identical memory"):
        intervention_delta(bridge, trace, "alternate_query_attention", donor)
    with pytest.raises(ValueError, match="nonzero"):
        intervention_delta(bridge, trace, "candidate_axis", candidate_axis=torch.zeros(12))
    with pytest.raises(ValueError, match="Unknown"):
        intervention_delta(bridge, trace, "not_a_mode")


def test_outer_autocast_cannot_change_trace_or_intervention_dtype():
    bridge, query, memory, mask = _fixture()
    with torch.autocast("cpu", dtype=torch.bfloat16):
        trace = trace_reader(bridge, query.bfloat16(), memory.bfloat16(), mask)
        delta = intervention_delta(bridge, trace, "centered_values")
        summary = summarize_trace(trace, candidate_head_weight=torch.randn(2, 12))
    assert delta.dtype == torch.float32
    assert trace["q_heads"].dtype == torch.float32
    assert summary["manual_delta_allclose"]
