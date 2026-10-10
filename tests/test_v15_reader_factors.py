from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import probe_v15_reader_factors as probe  # noqa: E402

from latent_workspace_ft_v10 import reader_factor_audit as audit  # noqa: E402
from latent_workspace_ft_v10.precision_bridge import PrecisionAwareWorkspaceBridge  # noqa: E402
from latent_workspace_ft_v10.query_modulated_bridge import (
    QueryModulatedWorkspaceBridge,  # noqa: E402
)


def test_factor_reconstruction_and_known_signs():
    corners = torch.tensor([[1, 2], [3, 4], [5, 6], [9, 10]], dtype=torch.float64)
    original = corners.clone()
    parts = audit.factors(corners)
    assert torch.equal(audit.reconstruct(parts), corners)
    assert parts["interaction"].tolist() == [0.5, 0.5]
    assert torch.equal(corners, original)
    null = audit.factors(corners[[0, 0, 2, 2]])
    assert null["memory"].count_nonzero() == null["interaction"].count_nonzero() == 0


@pytest.mark.parametrize(
    "value",
    [
        torch.ones(3, 2),
        torch.ones(4, 2, 1),
        torch.full((4, 2), float("nan")),
        torch.full((4, 2), float("inf")),
    ],
)
def test_invalid_corners(value):
    with pytest.raises(ValueError, match="Four finite"):
        audit.factors(value)


@pytest.mark.parametrize("cap", [0.5, 1.0, 2.0])
def test_cap_jvp_matches_autograd(cap):
    x = torch.tensor([1.2, -0.9, 0.4], dtype=torch.float64)
    v = torch.tensor([-0.2, 0.3, 0.7], dtype=torch.float64)
    _, expected = torch.autograd.functional.jvp(lambda p: audit.cap64(p, cap), x, v)
    assert torch.allclose(audit.cap_jvp64(x, v, cap), expected, atol=1e-15, rtol=1e-14)
    scale = cap / (cap**2 + x.square().sum()).sqrt()
    assert torch.allclose(audit.cap_jvp64(x, x, cap), x * scale**3, atol=1e-15, rtol=1e-14)


@pytest.mark.parametrize(
    "memory,interaction,sign", list(itertools.product((-2.0, 0.0, 2.0), (-3.0, 0.0, 3.0), (-1, 1)))
)
def test_reciprocal_binding_inequality(memory, interaction, sign):
    b = audit.binding_condition(memory, interaction, sign)
    even, odd = -sign * 2 * (memory - interaction), sign * 2 * (memory + interaction)
    assert b["even_donor_margin"] == even and b["odd_donor_margin"] == odd
    assert b["both_donor_margins_positive"] == (even > 0 and odd > 0)


def test_modulation_interaction_real_identity_and_shape():
    torch.manual_seed(47)
    r, g = torch.randn(4, 8, dtype=torch.float64), torch.randn(2, 8, dtype=torch.float64) * 0.1
    z = r * (1 + g[[0, 0, 1, 1]])
    terms = audit.modulation_interaction(r, g)
    assert torch.allclose(sum(terms.values()), audit.factors(z)["interaction"], atol=1e-15)
    with pytest.raises(ValueError, match="One gate"):
        audit.modulation_interaction(r, g[:1])


def test_spectrum_rank_one_zero_and_shape():
    op = torch.zeros(12, 8, dtype=torch.float64)
    op[0, 0] = 3
    axis = torch.arange(12, dtype=torch.float64)
    left, right, s = audit.spectral(op, axis)
    assert s["participation_rank"] == s["entropy_effective_rank"] == 1
    assert s["top_k_frobenius_energy_fraction"]["1"] == 1
    assert s["svd_max_abs_reconstruction_error"] == 0
    assert left.shape == (12, 8) and right.shape == (8, 8)
    _, _, z = audit.spectral(torch.zeros_like(op), axis)
    assert z["participation_rank"] is z["entropy_effective_rank"] is None
    with pytest.raises(ValueError, match="shape"):
        audit.spectral(op, axis[:8])


@pytest.mark.parametrize("cls", [PrecisionAwareWorkspaceBridge, QueryModulatedWorkspaceBridge])
@pytest.mark.parametrize("same_memory", [False, True])
def test_real_toy_trace_audit_no_mutation_no_graph(cls, same_memory):
    torch.manual_seed(47)
    bridge = cls(16, workspace_dim=8, heads=2, slots=3, max_delta_norm=1).eval()
    torch.nn.init.normal_(bridge.up.weight, std=0.2)
    before = {k: v.clone() for k, v in bridge.state_dict().items()}
    questions = [torch.randn(1, 1, 16) for _ in range(2)]
    memory = [torch.randn(1, 3, 8) for _ in range(2)]
    if same_memory:
        memory[1] = memory[0]
    mask = torch.ones(1, 3)
    traces = [probe.capture(bridge, q, m, mask)[1] for q in questions for m in memory]
    operator, axis = bridge.up.weight.detach().double(), torch.randn(16).double()
    left, right, _ = audit.spectral(operator, axis)
    result = audit.audit_block(
        traces, operator, axis, left, right, 1, cls is QueryModulatedWorkspaceBridge, 1
    )
    assert max(result["reconstruction_max_abs"].values()) < 1e-12
    assert all(p.grad is None for p in bridge.parameters())
    assert all(torch.equal(before[k], v) for k, v in bridge.state_dict().items())
    assert not bridge.up._forward_hooks and not bridge.up._forward_pre_hooks
    if same_memory:
        assert all(
            result["factors"][stage][name]["l2"] == 0
            for stage in ("r", "z", "x", "d")
            for name in ("memory", "interaction")
        )


def test_prospective_plan_and_prior_seals():
    plan, *_ = probe.validate()
    assert plan["optimizer_steps"] == 0 and plan["no_retry"]
