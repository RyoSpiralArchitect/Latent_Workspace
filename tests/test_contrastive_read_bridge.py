from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
import torch
from torch import nn

from latent_workspace_ft_v10.bridge_mechanistic import intervention_delta, trace_reader
from latent_workspace_ft_v10.contrastive_read_bridge import CenteredValueWorkspaceBridge
from latent_workspace_ft_v10.precision_bridge import (
    MistralPrecisionBridgeAdapter,
    PrecisionAwareWorkspaceBridge,
)


def _bridge(cls=CenteredValueWorkspaceBridge):
    torch.manual_seed(631)
    return cls(12, workspace_dim=8, heads=2, slots=4)


def _state_digest(bridge):
    digest = hashlib.sha256()
    for name, value in bridge.state_dict().items():
        digest.update(name.encode())
        digest.update(str((tuple(value.shape), value.dtype)).encode())
        digest.update(value.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def test_parameter_schema_initialization_and_checkpoint_compatibility_are_identical():
    original = _bridge(PrecisionAwareWorkspaceBridge)
    centered = _bridge()
    assert CenteredValueWorkspaceBridge.__init__ is PrecisionAwareWorkspaceBridge.__init__
    assert list(original.state_dict()) == list(centered.state_dict())
    assert _state_digest(original) == _state_digest(centered)
    nn.init.normal_(original.up.weight)
    centered.load_state_dict(original.state_dict(), strict=True)
    assert _state_digest(original) == _state_digest(centered)
    assert sum(p.numel() for p in original.parameters()) == sum(
        p.numel() for p in centered.parameters()
    )


@pytest.mark.parametrize("masked", [False, True])
def test_matches_centered_value_mechanistic_intervention(masked):
    original = _bridge(PrecisionAwareWorkspaceBridge)
    nn.init.normal_(original.up.weight, std=0.5)
    centered = _bridge()
    centered.load_state_dict(original.state_dict(), strict=True)
    query, memory = torch.randn(2, 1, 12), torch.randn(2, 4, 8)
    mask = torch.ones(2, 4)
    if masked:
        mask[0, -1] = 0
        mask[1, 1:3] = 0
    trace = trace_reader(original, query, memory, mask)
    expected = intervention_delta(original, trace, "centered_values")
    actual = centered.read_delta(query, memory, mask)
    torch.testing.assert_close(actual, expected, atol=1e-5, rtol=1e-5)
    assert not torch.allclose(actual, trace["delta"], atol=1e-5, rtol=1e-5)


def test_constant_slots_and_zero_memory_cannot_use_slot_mean_even_after_training():
    bridge = _bridge()
    with torch.no_grad():
        for parameter in bridge.parameters():
            nn.init.normal_(parameter, std=0.4)
    query = torch.randn(2, 1, 12)
    repeated = torch.randn(2, 1, 8).expand(-1, 4, -1).clone()
    mask = torch.ones(2, 4)
    for memory in (repeated, torch.zeros_like(repeated)):
        assert torch.count_nonzero(bridge.read_delta(query, memory, mask)) == 0
    # A non-power-of-two reduction can round an identical repeated value.
    # Retain a numerical tolerance rather than claiming bitwise cancellation.
    mask[:, -1] = 0
    torch.testing.assert_close(
        bridge.read_delta(query, repeated, mask), torch.zeros_like(query), atol=1e-6, rtol=0
    )


def test_diverse_slots_retain_query_dependence_and_masked_slots_do_not_leak():
    bridge = _bridge()
    nn.init.normal_(bridge.up.weight, std=0.4)
    query, memory = torch.randn(2, 1, 12), torch.randn(2, 4, 8)
    mask = torch.tensor([[1, 1, 1, 0], [1, 1, 1, 0]])
    first = bridge.read_delta(query, memory, mask)
    assert not torch.allclose(first, bridge.read_delta(-query, memory, mask), atol=1e-5, rtol=1e-5)
    memory[:, -1] = torch.randn(2, 8) * 1000
    torch.testing.assert_close(first, bridge.read_delta(query, memory, mask), atol=0, rtol=0)
    assert (torch.linalg.vector_norm(first, dim=-1) <= bridge.max_delta_norm).all()


def test_two_updates_open_finite_writer_and_query_gradients():
    bridge = _bridge()
    query, context, target = torch.randn(2, 1, 12), torch.randn(2, 7, 12), torch.randn(2, 1, 12)
    optimizer = torch.optim.SGD(bridge.parameters(), lr=0.5)
    for step in range(2):
        optimizer.zero_grad()
        memory, mask = bridge.write_memory(context, torch.ones(2, 7))
        delta = bridge.read_delta(query, memory, mask)
        if step == 0:
            assert torch.count_nonzero(delta) == 0
        (delta - target).square().mean().backward()
        for parameter in bridge.parameters():
            if parameter.grad is not None:
                assert torch.isfinite(parameter.grad).all()
        assert bridge.up.weight.grad.abs().sum() > 0
        if step == 0:
            assert bridge.query_projection.weight.grad.abs().sum() == 0
        else:
            assert bridge.query_projection.weight.grad.abs().sum() > 0
            assert bridge.writer.context_projection.weight.grad.abs().sum() > 0
        optimizer.step()


def test_fp32_isolation_cap_and_validation_match_parent():
    bridge = _bridge()
    nn.init.normal_(bridge.up.weight, std=100)
    query, memory, mask = torch.randn(2, 12), torch.randn(2, 4, 8), torch.ones(2, 4)
    with torch.autocast("cpu", dtype=torch.bfloat16):
        delta = bridge.read_delta(query.bfloat16(), memory.bfloat16(), mask)
    assert delta.dtype == torch.float32
    assert (torch.linalg.vector_norm(delta, dim=-1) <= bridge.max_delta_norm + 1e-7).all()
    with pytest.raises(ValueError, match="unmasked"):
        bridge.read_delta(query, memory, torch.zeros_like(mask))
    with pytest.raises(ValueError, match="binary"):
        bridge.read_delta(query, memory, mask * 0.5)
    with pytest.raises(ValueError, match="nonfinite"):
        bridge.read_delta(query, memory * float("nan"), mask)
    with pytest.raises(ValueError, match="Reader query"):
        bridge.read_delta(query[:, :-1], memory, mask)
    bridge.bfloat16()
    with pytest.raises(TypeError, match="remain float32"):
        bridge.read_delta(query, memory, mask)


def test_unchanged_native_adapter_accepts_centered_residual_without_modifying_base():
    bridge = _bridge()
    decoder = SimpleNamespace(layers=nn.ModuleList([nn.Identity()]), norm=nn.Identity())
    model = SimpleNamespace(model=decoder, lm_head=nn.Linear(12, 17, bias=False).bfloat16())
    boundary = SimpleNamespace(
        _kind="mistral",
        base_model=model,
        encode=lambda *args: None,
        _run_mistral_layers=lambda *args: None,
    )
    adapter = MistralPrecisionBridgeAdapter(boundary)
    normalized = torch.randn(2, 3, 12).bfloat16()
    memory, mask = torch.randn(2, 4, 8), torch.ones(2, 4)
    head_before = model.lm_head.weight.detach().clone()
    delta = bridge.read_delta(normalized[:, -1:], memory, mask)
    state = adapter.decode(normalized, delta, (3, 11))
    torch.testing.assert_close(state.native_logits, model.lm_head(normalized), atol=0, rtol=0)
    torch.testing.assert_close(model.lm_head.weight, head_before, atol=0, rtol=0)
    assert state.fp32_choice_scores.dtype == torch.float32
    nn.init.normal_(bridge.up.weight, std=0.4)
    changed = bridge.read_delta(normalized[:, -1:], memory, mask)
    corrected = adapter.decode(normalized, changed, (3, 11))
    torch.testing.assert_close(
        corrected.corrected_last_hidden_fp32,
        normalized[:, -1:].float() + changed,
        atol=0,
        rtol=0,
    )
    torch.testing.assert_close(model.lm_head.weight, head_before, atol=0, rtol=0)
