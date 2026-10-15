from __future__ import annotations

import json

import pytest
import torch

from latent_workspace_ft_v10.bridge_reader_panel import capture_reverse_panel
from latent_workspace_ft_v10.contrastive_read_bridge import CenteredValueWorkspaceBridge
from latent_workspace_ft_v10.precision_bridge import PrecisionAwareWorkspaceBridge


class _Store:
    def __init__(self):
        self.records = self.features = [{}, {}]
        generator = torch.Generator().manual_seed(79)
        self.contexts = torch.randn(2, 2, 1, 6, 12, generator=generator)
        self.queries = torch.randn(2, 8, 1, 3, 12, generator=generator)

    def query(self, world, query):
        return self.queries[world, query]

    def context(self, world, side):
        return self.contexts[world, side]


def _bridge(cls=PrecisionAwareWorkspaceBridge):
    torch.manual_seed(82)
    bridge = cls(12, workspace_dim=8, heads=2, slots=4).eval()
    torch.nn.init.normal_(bridge.up.weight, std=0.5)
    return bridge


@pytest.mark.parametrize("cls", [PrecisionAwareWorkspaceBridge, CenteredValueWorkspaceBridge])
def test_counts_real_path_pairing_unchanged_state_and_no_hook_leaks(cls):
    bridge, store = _bridge(cls), _Store()
    before = {name: value.clone() for name, value in bridge.state_dict().items()}
    queries_before, contexts_before = store.queries.clone(), store.contexts.clone()
    result = capture_reverse_panel(bridge, store, torch.randn(2, 12), "cpu", world_count=2)
    assert len(result["rows"]) == result["summary"]["row_count"] == 32
    assert len(result["pairs"]) == result["summary"]["pair_count"] == 16
    assert result["protocol"]["manual_reconstruction"] is False
    assert not result["protocol"]["held_out_evidence"]
    assert result["pairs"][0]["even_query"] == 0
    assert result["pairs"][0]["odd_query"] == 1
    assert all(row["keys_relative_l2"] == 0 for row in result["pairs"])
    assert all(row["values_relative_l2"] == 0 for row in result["pairs"])
    assert all(row["query_relative_l2"] > 0 for row in result["pairs"])
    assert max(row["permutation_delta_max_abs_error"] for row in result["rows"]) < 1e-5
    for name, value in bridge.state_dict().items():
        torch.testing.assert_close(value, before[name], atol=0, rtol=0)
    torch.testing.assert_close(store.queries, queries_before, atol=0, rtol=0)
    torch.testing.assert_close(store.contexts, contexts_before, atol=0, rtol=0)
    assert not any(parameter.grad is not None for parameter in bridge.parameters())
    for module in bridge.modules():
        assert not module._forward_hooks and not module._forward_pre_hooks
        assert not module.training
    json.dumps(result, allow_nan=False)


def test_uniform_bias_removed_in_centered_actual_value_path():
    original, centered, store = _bridge(), _bridge(CenteredValueWorkspaceBridge), _Store()
    head = torch.randn(2, 12)
    baseline = capture_reverse_panel(original, store, head, "cpu", world_count=2)
    changed = capture_reverse_panel(centered, store, head, "cpu", world_count=2)
    assert min(row["uniform_delta_l2"] for row in baseline["rows"]) > 1e-3
    assert max(row["uniform_delta_l2"] for row in changed["rows"]) < 1e-6
    assert min(row["value_mean_fraction"] for row in baseline["rows"]) > 0.1
    assert max(row["value_mean_fraction"] for row in changed["rows"]) < 1e-4


def test_collapsed_slots_and_zero_initialized_up():
    store, head = _Store(), torch.randn(2, 12)
    for cls in (PrecisionAwareWorkspaceBridge, CenteredValueWorkspaceBridge):
        bridge = _bridge(cls)
        torch.nn.init.zeros_(bridge.up.weight)
        result = capture_reverse_panel(bridge, store, head, "cpu", world_count=2)
        assert all(row["delta_l2"] == row["uniform_delta_l2"] == 0 for row in result["rows"])
        assert all(row["delta_relative_l2"] == 0 for row in result["pairs"])
        torch.nn.init.normal_(bridge.up.weight, std=0.5)
        constant = torch.randn(1, 1, 8).expand(1, 4, 8).clone()
        bridge.write_memory = lambda context, mask: (constant, torch.ones(1, 4))
        result = capture_reverse_panel(bridge, store, head, "cpu", world_count=2)
        assert max(row["delta_relative_l2"] for row in result["pairs"]) < 1e-5
        if cls is CenteredValueWorkspaceBridge:
            assert all(row["delta_l2"] == 0 for row in result["rows"])


def test_eval_shape_and_availability_guards_and_error_cleanup():
    bridge, store, head = _bridge(), _Store(), torch.randn(2, 12)
    bridge.train()
    with pytest.raises(ValueError, match="eval"):
        capture_reverse_panel(bridge, store, head, "cpu", world_count=2)
    bridge.eval()
    with pytest.raises(ValueError, match="world_count"):
        capture_reverse_panel(bridge, store, head, "cpu", world_count=3)
    with pytest.raises(ValueError, match="finite"):
        capture_reverse_panel(bridge, store, head * float("nan"), "cpu", world_count=2)
    store.queries[0, 0] *= float("nan")
    with pytest.raises(ValueError, match="nonfinite"):
        capture_reverse_panel(bridge, store, head, "cpu", world_count=2)
    for module in bridge.modules():
        assert not module._forward_hooks and not module._forward_pre_hooks
