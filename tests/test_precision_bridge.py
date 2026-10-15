from __future__ import annotations

from types import SimpleNamespace

import pytest
import torch
from torch import nn

from latent_workspace_ft_v10.precision_bridge import (
    MistralPrecisionBridgeAdapter,
    PrecisionAwareWorkspaceBridge,
)


def _bridge() -> PrecisionAwareWorkspaceBridge:
    torch.manual_seed(13)
    return PrecisionAwareWorkspaceBridge(8, workspace_dim=4, heads=2, slots=3)


def test_zero_initialization_and_zero_memory_are_exact_noops() -> None:
    bridge = _bridge()
    query = torch.randn(2, 1, 8)
    memory, mask = bridge.write_memory(torch.randn(2, 5, 8), torch.ones(2, 5))
    assert memory.shape == (2, 3, 4)
    assert torch.equal(bridge.read_delta(query, memory, mask), torch.zeros_like(query))
    nn.init.normal_(bridge.up.weight)
    assert torch.count_nonzero(bridge.read_delta(query, memory, mask)) > 0
    assert torch.equal(
        bridge.read_delta(query, torch.zeros_like(memory), mask), torch.zeros_like(query)
    )
    assert bridge.attention.in_proj_bias is None
    assert bridge.attention.out_proj.bias is None
    assert bridge.memory_norm.weight is None
    assert bridge.memory_norm.bias is None


def test_cap_fp32_and_autocast_isolation() -> None:
    bridge = _bridge()
    nn.init.normal_(bridge.up.weight, std=100.0)
    with torch.autocast("cpu", dtype=torch.bfloat16):
        memory, mask = bridge.write_memory(torch.randn(2, 5, 8).bfloat16(), torch.ones(2, 5))
        delta = bridge.read_delta(torch.randn(2, 8).bfloat16(), memory, mask)
    assert memory.dtype == delta.dtype == torch.float32
    assert (torch.linalg.vector_norm(delta, dim=-1) <= bridge.max_delta_norm + 1e-7).all()
    bridge.bfloat16()
    with pytest.raises(TypeError, match="remain float32"):
        bridge.read_delta(torch.randn(2, 1, 8), memory, mask)


def test_two_steps_open_the_writer_and_query_gradient_paths() -> None:
    bridge = _bridge()
    context = torch.randn(2, 5, 8)
    query = torch.randn(2, 1, 8)
    target = torch.randn(2, 1, 8)
    optimizer = torch.optim.SGD(bridge.parameters(), lr=0.2)
    for step in range(2):
        optimizer.zero_grad()
        memory, mask = bridge.write_memory(context, torch.ones(2, 5))
        delta = bridge.read_delta(query, memory, mask)
        (delta - target).square().mean().backward()
        assert bridge.up.weight.grad.abs().sum() > 0
        if step == 0:
            assert bridge.query_projection.weight.grad.abs().sum() == 0
        else:
            assert bridge.query_projection.weight.grad.abs().sum() > 0
            assert bridge.writer.context_projection.weight.grad.abs().sum() > 0
        optimizer.step()


def test_masked_memory_is_ignored_and_memory_changes_the_residual() -> None:
    bridge = _bridge()
    nn.init.normal_(bridge.up.weight)
    query = torch.randn(1, 1, 8)
    memory = torch.randn(1, 3, 4)
    mask = torch.tensor([[1, 1, 0]])
    original = bridge.read_delta(query, memory, mask)
    altered = memory.clone()
    altered[:, 2] = torch.tensor([100.0, -300.0, 40.0, 0.0])
    torch.testing.assert_close(bridge.read_delta(query, altered, mask), original, rtol=0, atol=0)
    altered[:, 0] = -memory[:, 0]
    assert not torch.equal(bridge.read_delta(query, altered, mask), original)


class _Boundary:
    def __init__(self, dtype: torch.dtype = torch.float32) -> None:
        self._kind = "mistral"
        self.calls: list[tuple[str, int]] = []
        torch.manual_seed(5)
        self.base_model = SimpleNamespace(
            model=SimpleNamespace(
                embed_tokens=nn.Embedding(10, 8).to(dtype),
                layers=nn.ModuleList([nn.Identity(), nn.Identity()]),
                norm=nn.LayerNorm(8).to(dtype),
            ),
            lm_head=nn.Linear(8, 7, bias=True).to(dtype),
        )

    def encode(self, ids: torch.Tensor, mask: torch.Tensor, boundary: int) -> torch.Tensor:
        self.calls.append(("encode", boundary))
        return self.base_model.model.embed_tokens(ids)

    def _run_mistral_layers(
        self, hidden: torch.Tensor, mask: torch.Tensor, layers: nn.ModuleList
    ) -> torch.Tensor:
        self.calls.append(("upper", len(layers)))
        for layer in layers:
            hidden = layer(hidden)
        return hidden


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_adapter_zero_delta_preserves_native_base_and_head_geometry(dtype: torch.dtype) -> None:
    boundary = _Boundary(dtype)
    adapter = MistralPrecisionBridgeAdapter(boundary)
    ids = torch.tensor([[1, 2, 3], [4, 5, 6]])
    normalized = adapter.encode_prefix(ids, torch.ones_like(ids), boundary_layer=1)
    assert boundary.calls == [("encode", 1), ("upper", 1)]
    state = adapter.decode(normalized, torch.zeros(2, 1, 8), (1, 5))
    expected = boundary.base_model.lm_head(normalized)
    torch.testing.assert_close(state.native_logits, expected, rtol=0, atol=0)
    torch.testing.assert_close(
        state.native_choice_scores, expected[:, -1:, [1, 5]].float(), rtol=0, atol=0
    )
    assert state.native_logits.shape == (2, 3, 7)
    assert state.fp32_choice_scores.dtype == torch.float32
    assert not torch.count_nonzero(state.native_applied_delta)


def test_fp32_residual_survives_native_quantization_and_has_gradients() -> None:
    boundary = _Boundary(torch.bfloat16)
    adapter = MistralPrecisionBridgeAdapter(boundary)
    normalized = torch.ones(1, 3, 8, dtype=torch.bfloat16)
    delta = torch.full((1, 1, 8), 0.0001, requires_grad=True)
    state = adapter.decode(normalized, delta, (1, 5))
    baseline = adapter.decode(normalized, torch.zeros_like(delta), (1, 5))
    assert torch.equal(state.native_choice_scores, baseline.native_choice_scores)
    assert not torch.equal(state.fp32_choice_scores, baseline.fp32_choice_scores)
    assert not torch.count_nonzero(state.native_applied_delta)
    state.fp32_choice_scores.sum().backward()
    assert delta.grad is not None and delta.grad.abs().sum() > 0
    assert torch.isfinite(delta.grad).all()


def test_bridge_shape_mask_and_nonfinite_guards() -> None:
    bridge = _bridge()
    with pytest.raises(ValueError, match="Writer expects"):
        bridge.write_memory(torch.ones(1, 2, 7), torch.ones(1, 2))
    with pytest.raises(ValueError, match="unmasked"):
        bridge.write_memory(torch.ones(1, 2, 8), torch.zeros(1, 2))
    with pytest.raises(ValueError, match="binary"):
        bridge.write_memory(torch.ones(1, 2, 8), torch.full((1, 2), 0.5))
    with pytest.raises(ValueError, match="nonfinite"):
        bridge.write_memory(torch.full((1, 2, 8), float("nan")), torch.ones(1, 2))
    with pytest.raises(ValueError, match="Reader query"):
        bridge.read_delta(torch.ones(1, 2, 8), torch.ones(1, 3, 4), torch.ones(1, 3))
    with pytest.raises(ValueError, match="nonfinite"):
        bridge.read_delta(torch.ones(1, 8), torch.full((1, 3, 4), float("inf")), torch.ones(1, 3))


def test_adapter_rejects_unknown_architecture_and_invalid_inputs() -> None:
    boundary = _Boundary()
    boundary._kind = "olmo2"
    with pytest.raises(TypeError, match="requires a Mistral"):
        MistralPrecisionBridgeAdapter(boundary)
    boundary._kind = "mistral"
    adapter = MistralPrecisionBridgeAdapter(boundary)
    with pytest.raises(ValueError, match="Boundary layer"):
        adapter.encode_prefix(torch.ones(1, 2, dtype=torch.long), torch.ones(1, 2), 3)
    with pytest.raises(ValueError, match="unmasked"):
        adapter.encode_prefix(torch.ones(1, 2, dtype=torch.long), torch.tensor([[1, 0]]), 1)
    for candidates in ((1, 1), (1, 2, 3), (1, 1.5)):
        with pytest.raises(ValueError, match="two distinct"):
            adapter.decode(torch.ones(1, 2, 8), torch.zeros(1, 1, 8), candidates)
    with pytest.raises(ValueError, match="outside"):
        adapter.decode(torch.ones(1, 2, 8), torch.zeros(1, 1, 8), (1, 10))
    with pytest.raises(ValueError, match="residual must have shape"):
        adapter.decode(torch.ones(1, 2, 8), torch.zeros(1, 2, 8), (1, 2))
    with pytest.raises(ValueError, match="nonfinite"):
        adapter.decode(torch.ones(1, 2, 8), torch.full((1, 1, 8), float("nan")), (1, 2))


@pytest.mark.parametrize(
    "kwargs",
    [{"max_delta_norm": 0.0}, {"max_delta_norm": float("nan")}, {"heads": 3}, {"slots": 0}],
)
def test_constructor_validation(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        PrecisionAwareWorkspaceBridge(hidden_dim=8, workspace_dim=4, **kwargs)
