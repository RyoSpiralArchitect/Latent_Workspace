import json

import pytest
import torch

from latent_workspace_ft_v10.contrastive_read_bridge import CenteredValueWorkspaceBridge
from latent_workspace_ft_v10.learner_gradient_audit import audit_loss_gradients
from latent_workspace_ft_v10.precision_bridge import PrecisionAwareWorkspaceBridge


def fixture(kind=PrecisionAwareWorkspaceBridge, opened=True):
    torch.manual_seed(91)
    bridge = kind(8, workspace_dim=4, heads=2, slots=3).eval()
    if opened:
        torch.nn.init.normal_(bridge.up.weight, std=0.1)
    context, query = torch.randn(2, 5, 8), torch.randn(2, 1, 8)
    memory, mask = bridge.write_memory(context, torch.ones(2, 5))
    delta = bridge.read_delta(query, memory, mask)
    return bridge, delta, {"query": query, "context": context}


@pytest.mark.parametrize("kind", [PrecisionAwareWorkspaceBridge, CenteredValueWorkspaceBridge])
def test_production_graph_reconstructs_and_preserves_populated_grads(kind):
    bridge, delta, frozen = fixture(kind)
    for parameter in bridge.parameters():
        parameter.grad = torch.randn_like(parameter)
    parts = {"fit": (delta - 0.1).square().mean(), "residual": delta.square().sum()}
    result = audit_loss_gradients(
        bridge, parts, {"fit": 1.0, "residual": 0.03},
        total_loss=parts["fit"] + 0.03 * parts["residual"], frozen_tensors=frozen,
    )
    assert result["optimizer_steps"] == 0
    assert result["reconstruction"]["passed"]
    assert result["bridge_state_unchanged"] and result["parameter_grads_unchanged"]
    assert result["module_modes_unchanged"]
    assert result["terms"]["fit"]["raw"]["up"]["status"] == "nonzero"
    assert result["terms"]["fit"]["raw"]["reader_q"]["status"] == "nonzero"
    json.dumps(result, allow_nan=False)


def test_zero_init_is_zero_upstream_not_missing_and_keeps_grads_unpopulated():
    bridge, delta, _ = fixture(opened=False)
    loss = (delta - 0.1).square().mean()
    result = audit_loss_gradients(bridge, {"fit": loss}, {"fit": 1.0}, total_loss=loss)
    for group in ("writer", "query_projection", "query_norm", "reader_q", "reader_k"):
        assert result["terms"]["fit"]["raw"][group]["status"] == "zero"
        assert result["terms"]["fit"]["raw"][group]["missing_elements"] == 0
    assert result["terms"]["fit"]["raw"]["up"]["status"] == "nonzero"
    assert all(parameter.grad is None for parameter in bridge.parameters())


def test_constants_unused_paths_and_zero_weight_are_explicit():
    bridge, _, _ = fixture()
    parts = {"up_only": bridge.up.weight.square().sum(), "constant": torch.tensor(2.0)}
    result = audit_loss_gradients(
        bridge, parts, {"up_only": 0.0, "constant": 1.0},
        total_loss=parts["up_only"] * 0 + parts["constant"],
    )
    assert result["terms"]["constant"]["raw"]["up"]["status"] == "missing"
    assert result["terms"]["up_only"]["raw"]["writer"]["status"] == "missing"
    assert result["terms"]["up_only"]["weighted"]["up"]["status"] == "zero"
    assert result["pairwise"][0]["raw"]["up"]["cosine"] is None
    assert result["reconstruction"]["passed"]


def test_qkv_slices_are_disjoint_and_reciprocal_diagnostics_excluded():
    bridge, _, _ = fixture()
    q, k, v = bridge.attention.in_proj_weight.chunk(3)
    parts = {"q": q.sum(), "k": 2 * k.sum(), "v": 3 * v.sum()}
    result = audit_loss_gradients(
        bridge, parts, dict.fromkeys(parts, 1.0), total_loss=sum(parts.values()),
        diagnostic_components={"forward": q.sum(), "reverse": -q.sum()},
    )
    for name, group, norm in (("q", "reader_q", 4), ("k", "reader_k", 8),
                              ("v", "reader_v", 12)):
        assert result["terms"][name]["raw"][group]["l2"] == norm
    pair = next(row for row in result["pairwise"] if row["first"] == "forward")
    assert pair["raw"]["reader_q"]["cosine"] == pytest.approx(-1)
    assert pair["weighted"] is None
    assert result["terms"]["forward"]["weight"] is None
    assert result["reconstruction"]["passed"]


def test_mismatched_objective_is_not_qualified():
    bridge, delta, _ = fixture()
    loss = delta.square().sum()
    result = audit_loss_gradients(bridge, {"fit": loss}, {"fit": 2.0}, total_loss=loss)
    assert not result["reconstruction"]["passed"]


def test_invalid_contracts_fail_before_measurement():
    bridge, delta, _ = fixture()
    loss = delta.sum()
    with pytest.raises(ValueError, match="cover exactly"):
        audit_loss_gradients(bridge, {"fit": loss}, {}, total_loss=loss)
    with pytest.raises(ValueError, match="finite"):
        audit_loss_gradients(bridge, {"fit": loss}, {"fit": float("nan")}, total_loss=loss)
    with pytest.raises(ValueError, match="frozen input"):
        audit_loss_gradients(bridge, {"fit": loss}, {"fit": 1}, total_loss=loss,
                             frozen_tensors={"head": torch.ones(2, 8, requires_grad=True)})
    with pytest.raises(ValueError, match="disjoint"):
        audit_loss_gradients(bridge, {"fit": loss}, {"fit": 1}, total_loss=loss,
                             diagnostic_components={"fit": loss})
    with pytest.raises(ValueError, match="scalar"):
        audit_loss_gradients(bridge, {"fit": delta}, {"fit": 1}, total_loss=loss)
