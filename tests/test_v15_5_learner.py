from __future__ import annotations

import copy

import pytest
import torch
from torch.nn import functional as F

from latent_workspace_ft_v10.precision_bridge import PrecisionAwareWorkspaceBridge
from latent_workspace_ft_v10.reader_query import QuestionSpan
from latent_workspace_ft_v10.v15_5_learner import (
    native_answer_terms,
    validate_optimizer_ownership,
)
from latent_workspace_ft_v10.v15_pipeline import NativeWorkspacePipeline
from latent_workspace_ft_v10.v15_readout import NativeWorkspaceReadout


def fixture(dtype=torch.float32, mode="final"):
    torch.manual_seed(15503)
    bridge = PrecisionAwareWorkspaceBridge(8, workspace_dim=4, heads=2, slots=2)
    head = torch.nn.Linear(8, 11, bias=False).to(dtype).requires_grad_(False)
    pipeline = NativeWorkspacePipeline(bridge, NativeWorkspaceReadout(head), mode)
    kwargs = dict(
        normalized_prefix=torch.randn(1, 3, 8, dtype=dtype),
        normalized_completion=torch.randn(1, 4, 8, dtype=dtype),
        prefix_ids=(1, 4, 5),
        completion_prefix_ids=(1, 4, 5, 6),
        span=QuestionSpan("A?", 0, 2, (0, 1), (1, 4, 5), "fixture"),
        answer_token_id=6,
        eos_token_id=2,
    )
    return pipeline, torch.randn(1, 3, 8), torch.ones(1, 3), kwargs


def terms(pipeline, context, mask, kwargs):
    memory, memory_mask = pipeline.bridge.write_memory(context, mask)
    return native_answer_terms(pipeline, memory, memory_mask, **kwargs)


@pytest.mark.parametrize("mode", ["final", "mean_span"])
def test_full_vocabulary_ce_and_separate_completion_coefficient(mode):
    pipe, context, mask, kwargs = fixture(mode=mode)
    result = terms(pipe, context, mask, kwargs)
    expected = F.cross_entropy(result.answer_output.readout.last_logits, torch.tensor([6]))
    assert torch.equal(result.answer_ce, expected)
    assert torch.equal(result.objective(0), result.answer_ce)
    assert torch.equal(result.objective(1), result.answer_ce + result.eos_ce)
    two_choice = F.cross_entropy(
        result.answer_output.readout.choice_scores((6, 7)), torch.tensor([0])
    )
    assert not torch.equal(result.answer_ce, two_choice)
    assert result.answer_output.readout.logits.shape == (1, 3, 11)
    assert result.completion_output.readout.logits.shape == (1, 4, 11)


@pytest.mark.parametrize("weight", [-1, float("nan"), float("inf"), True, "1"])
def test_invalid_completion_weight_fails_closed(weight):
    pipe, context, mask, kwargs = fixture()
    with pytest.raises(ValueError, match="EOS weight"):
        terms(pipe, context, mask, kwargs).objective(weight)


@pytest.mark.parametrize(
    "change",
    [
        {"answer_token_id": True},
        {"answer_token_id": -1},
        {"eos_token_id": 11},
        {"eos_token_id": 6},
        {"prefix_ids": (1, 4)},
        {"prefix_ids": [1, 4, 5]},
        {"completion_prefix_ids": (1, 4, 5, 7)},
        {"completion_prefix_ids": (1, 4, 5, 6, 2)},
    ],
)
def test_token_or_anchor_drift_is_not_repaired(change):
    pipe, context, mask, kwargs = fixture()
    with pytest.raises(ValueError):
        terms(pipe, context, mask, kwargs | change)


@pytest.mark.parametrize("key", ["normalized_prefix", "normalized_completion"])
def test_backbone_feature_gradient_is_rejected(key):
    pipe, context, mask, kwargs = fixture()
    kwargs[key].requires_grad_(True)
    with pytest.raises(ValueError, match="detached"):
        terms(pipe, context, mask, kwargs)


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("eos_weight", [0, 1])
def test_finite_update_changes_native_logits_and_preserves_frozen_state(dtype, eos_weight):
    pipe, context, mask, kwargs = fixture(dtype)
    head_before = copy.deepcopy(pipe.readout.head.state_dict())
    features_before = kwargs["normalized_prefix"].clone()
    optimizer = torch.optim.AdamW(pipe.bridge.parameters(), lr=0.03)
    validate_optimizer_ownership(pipe.bridge, optimizer)
    initial = terms(pipe, context, mask, kwargs).answer_output.readout.logits.detach().clone()
    for _ in range(3):
        optimizer.zero_grad(set_to_none=True)
        result = terms(pipe, context, mask, kwargs)
        result.objective(eos_weight).backward()
        assert pipe.bridge.up.weight.grad.norm() > 0
        assert all(p.grad is None for p in pipe.readout.head.parameters())
        torch.nn.utils.clip_grad_norm_(pipe.bridge.parameters(), 1.0, error_if_nonfinite=True)
        optimizer.step()
    final = terms(pipe, context, mask, kwargs)
    assert not torch.equal(initial, final.answer_output.readout.logits)
    assert pipe.bridge.writer.context_projection.weight.grad.norm() > 0
    assert torch.equal(features_before, kwargs["normalized_prefix"])
    assert all(torch.equal(v, pipe.readout.head.state_dict()[k]) for k, v in head_before.items())
    memory, memory_mask = pipe.bridge.write_memory(context, mask)
    zero = native_answer_terms(pipe, torch.zeros_like(memory), memory_mask, **kwargs)
    assert torch.count_nonzero(zero.answer_output.delta) == 0
    assert torch.count_nonzero(zero.completion_output.delta) == 0
    assert torch.equal(zero.answer_output.readout.logits, initial)


def test_answer_gradients_identical_when_only_zero_weight_completion_changes():
    pipe, context, mask, kwargs = fixture()
    result = terms(pipe, context, mask, kwargs)
    expected = torch.autograd.grad(result.answer_ce, pipe.bridge.up.weight, retain_graph=True)[0]
    actual = torch.autograd.grad(result.objective(0), pipe.bridge.up.weight)[0]
    assert torch.equal(expected, actual)


def test_optimizer_rejects_missing_and_extra_parameters():
    pipe, _, _, _ = fixture()
    with pytest.raises(ValueError, match="exactly"):
        validate_optimizer_ownership(pipe.bridge, torch.optim.SGD([pipe.bridge.up.weight], lr=0.1))
    other = torch.nn.Parameter(torch.ones(1))
    optimizer = torch.optim.SGD([*pipe.bridge.parameters(), other], lr=0.1)
    with pytest.raises(ValueError, match="exactly"):
        validate_optimizer_ownership(pipe.bridge, optimizer)
