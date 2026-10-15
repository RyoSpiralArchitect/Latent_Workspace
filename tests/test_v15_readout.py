from __future__ import annotations

from types import SimpleNamespace

import pytest
import torch
from torch import nn
from torch.nn import functional as F

from latent_workspace_ft_v10.answer_bank_generation import choose_token, native_full_readout
from latent_workspace_ft_v10.precision_bridge import (
    MistralPrecisionBridgeAdapter,
    PrecisionAwareWorkspaceBridge,
)
from latent_workspace_ft_v10.v15_readout import NativeWorkspaceReadout


def _head(dtype=torch.float32, bias=True):
    torch.manual_seed(23)
    return nn.Linear(8, 17, bias=bias).to(dtype).requires_grad_(False)


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("length", [1, 7])
def test_zero_is_exact_native_base_and_v14_generation(dtype, length):
    head = _head(dtype)
    hidden = torch.randn(1, length, 8).to(dtype)
    zero = torch.zeros(1, 1, 8)
    state = NativeWorkspaceReadout(head)(hidden, zero)
    legacy, trace = native_full_readout(hidden, zero, head)
    assert torch.equal(state.logits, head(hidden))
    assert torch.equal(state.logits, legacy)
    assert state.logits.shape == (1, length, 17)
    assert state.last_logits.shape == (1, 17)
    assert state.last_logits.dtype == torch.float32
    assert not torch.count_nonzero(state.applied_delta)
    assert trace["native_applied_delta_l2"] == 0


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_nonzero_adapter_and_generation_parity(dtype):
    head = _head(dtype)
    boundary = SimpleNamespace(
        _kind="mistral",
        base_model=SimpleNamespace(
            model=SimpleNamespace(layers=nn.ModuleList([nn.Identity()]), norm=nn.Identity()),
            lm_head=head,
        ),
        encode=lambda *args: None,
        _run_mistral_layers=lambda *args: None,
    )
    hidden = torch.randn(1, 5, 8).to(dtype)
    delta = torch.randn(1, 1, 8) * 0.1
    readout = NativeWorkspaceReadout(head)
    state = readout(hidden, delta)
    prior = MistralPrecisionBridgeAdapter(boundary).decode(hidden, delta, (1, 9))
    assert torch.equal(state.logits, prior.native_logits)
    assert torch.equal(state.logits, native_full_readout(hidden, delta, head)[0])
    assert torch.equal(state.choice_scores((1, 9)), prior.native_choice_scores[:, 0])
    assert torch.equal(state.applied_delta, prior.native_applied_delta)
    assert torch.equal(
        readout.legacy_fp32_choices(hidden, delta, (1, 9)), prior.fp32_choice_scores[:, 0]
    )


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_train_eval_generation_use_identical_actual_logits(dtype):
    readout = NativeWorkspaceReadout(_head(dtype))
    hidden = torch.randn(2, 6, 8).to(dtype)
    delta = torch.randn(2, 1, 8) * 0.03
    train = readout.train()(hidden, delta)
    evaluation = readout.eval()(hidden, delta)
    with torch.no_grad():
        generation = readout(hidden, delta)
    assert torch.equal(train.logits, evaluation.logits)
    assert torch.equal(train.logits, generation.logits)
    assert torch.equal(train.choice_scores([3, 11]), generation.last_logits[:, [3, 11]])
    targets = torch.tensor([3, 11])
    assert torch.equal(
        train.cross_entropy(targets), F.cross_entropy(generation.last_logits, targets)
    )
    assert choose_token(train.last_logits[0], 0, 0.2) == choose_token(
        generation.last_logits[0], 0, 0.7
    )


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_external_autocast_cannot_change_native_head(dtype):
    head = _head(dtype)
    readout = NativeWorkspaceReadout(head)
    hidden = torch.randn(2, 5, 8).to(dtype)
    delta = torch.randn(2, 1, 8)
    expected = readout(hidden, delta)
    with torch.autocast("cpu", dtype=torch.bfloat16):
        actual = readout(hidden, delta)
    assert actual.logits.dtype == dtype
    assert torch.equal(actual.logits, expected.logits)
    assert torch.equal(actual.applied_delta, expected.applied_delta)


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_full_vocab_native_loss_reaches_delta_and_bridge_not_base(dtype):
    base = nn.Linear(8, 8, bias=False).to(dtype).requires_grad_(False)
    head = _head(dtype)
    readout = NativeWorkspaceReadout(head)
    bridge = PrecisionAwareWorkspaceBridge(8, workspace_dim=4, heads=2, slots=3)
    nn.init.normal_(bridge.up.weight, std=0.1)
    hidden = base(torch.randn(2, 5, 8).to(dtype))
    memory, mask = bridge.write_memory(hidden, torch.ones(2, 5))
    delta = bridge.read_delta(hidden[:, -1:], memory, mask)
    delta.retain_grad()
    state = readout(hidden, delta)
    state.cross_entropy(torch.tensor([2, 11])).backward()
    assert delta.grad is not None and torch.isfinite(delta.grad).all()
    assert delta.grad.abs().sum() > 0
    for parameter in (bridge.up.weight, bridge.query_projection.weight):
        assert parameter.grad is not None and parameter.grad.abs().sum() > 0
    assert bridge.writer.context_projection.weight.grad.abs().sum() > 0
    assert all(parameter.grad is None for parameter in base.parameters())
    assert all(parameter.grad is None for parameter in head.parameters())


def test_sub_ulp_native_surrogate_gradient_is_not_finite_forward_effect():
    readout = NativeWorkspaceReadout(_head(torch.bfloat16))
    hidden = torch.ones(1, 3, 8, dtype=torch.bfloat16)
    delta = torch.full((1, 1, 8), 0.0001, requires_grad=True)
    state = readout(hidden, delta)
    assert torch.equal(state.logits, readout(hidden, torch.zeros_like(delta)).logits)
    assert not torch.count_nonzero(state.applied_delta)
    state.cross_entropy(torch.tensor([2])).backward()
    assert delta.grad.abs().sum() > 0  # PyTorch's cast gradient is a surrogate.
    legacy = readout.legacy_fp32_choices(hidden, delta, (1, 9))
    assert not legacy.requires_grad
    assert not torch.equal(
        legacy, readout.legacy_fp32_choices(hidden, torch.zeros_like(delta), (1, 9))
    )


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_written_zero_uses_actual_bridge_and_exact_native_noop(dtype):
    readout = NativeWorkspaceReadout(_head(dtype))
    bridge = PrecisionAwareWorkspaceBridge(8, workspace_dim=4, heads=2, slots=3)
    nn.init.normal_(bridge.up.weight, std=0.1)
    hidden = torch.randn(2, 5, 8).to(dtype)
    memory, mask = bridge.write_memory(hidden, torch.ones(2, 5))
    intact_delta = bridge.read_delta(hidden[:, -1:], memory, mask)
    assert torch.count_nonzero(intact_delta)
    actual_zero = bridge.read_delta(hidden[:, -1:], torch.zeros_like(memory), mask)
    assert torch.equal(actual_zero, torch.zeros_like(actual_zero))
    assert torch.equal(readout(hidden, actual_zero).logits, readout.head(hidden))


def test_head_geometry_remains_complete_sequence_and_vocabulary():
    head = _head()
    seen = []
    handle = head.register_forward_pre_hook(lambda _module, args: seen.append(args[0].shape))
    state = NativeWorkspaceReadout(head)(torch.ones(3, 7, 8), torch.zeros(3, 1, 8))
    state.choice_scores((1, 9))
    handle.remove()
    assert seen == [torch.Size((3, 7, 8))]
    assert state.logits.shape == (3, 7, 17)


def test_head_freezing_is_required_and_revalidated_without_mutation():
    head = nn.Linear(8, 17)
    with pytest.raises(ValueError, match="frozen"):
        NativeWorkspaceReadout(head)
    assert head.weight.requires_grad
    head.requires_grad_(False)
    readout = NativeWorkspaceReadout(head)
    head.bias.requires_grad_(True)
    with pytest.raises(ValueError, match="frozen"):
        readout(torch.ones(1, 2, 8), torch.zeros(1, 1, 8))


@pytest.mark.parametrize("ids", [[], [1, 1], [-1], [17], [1.0, 2], [True, 2], "12", 1])
def test_candidate_id_guards(ids):
    state = NativeWorkspaceReadout(_head())(torch.ones(1, 2, 8), torch.zeros(1, 1, 8))
    with pytest.raises(ValueError):
        state.choice_scores(ids)


@pytest.mark.parametrize("ids", [torch.tensor([[1, 2]]), torch.tensor([1.0, 2.0])])
def test_candidate_tensor_guards(ids):
    state = NativeWorkspaceReadout(_head())(torch.ones(1, 2, 8), torch.zeros(1, 1, 8))
    with pytest.raises(ValueError, match="one-dimensional integer"):
        state.choice_scores(ids)


def test_candidate_and_target_int32_are_supported():
    state = NativeWorkspaceReadout(_head())(torch.ones(1, 2, 8), torch.zeros(1, 1, 8))
    assert torch.equal(
        state.choice_scores(torch.tensor([1, 9], dtype=torch.int32)), state.choice_scores((1, 9))
    )
    assert torch.equal(
        state.cross_entropy(torch.tensor([1], dtype=torch.int32)),
        state.cross_entropy(torch.tensor([1])),
    )


@pytest.mark.parametrize(
    "targets,error",
    [
        ([1], TypeError),
        (torch.tensor([1.0]), TypeError),
        (torch.tensor([[1]]), ValueError),
        (torch.tensor([-100]), ValueError),
        (torch.tensor([17]), ValueError),
    ],
)
def test_target_guards(targets, error):
    state = NativeWorkspaceReadout(_head())(torch.ones(1, 2, 8), torch.zeros(1, 1, 8))
    with pytest.raises(error):
        state.cross_entropy(targets)


@pytest.mark.parametrize(
    "hidden,delta,error,match",
    [
        (torch.ones(1, 0, 8), torch.zeros(1, 1, 8), ValueError, "nonempty"),
        (torch.ones(1, 2, 7), torch.zeros(1, 1, 7), ValueError, "head_hidden_dim"),
        (torch.ones(1, 2, 8), torch.zeros(1, 2, 8), ValueError, "Residual must have shape"),
        (torch.ones(1, 2, 8).bfloat16(), torch.zeros(1, 1, 8), TypeError, "dtype must match"),
        (torch.ones(1, 2, 8), torch.zeros(1, 1, 8).bfloat16(), TypeError, "float32"),
        (torch.full((1, 2, 8), float("nan")), torch.zeros(1, 1, 8), ValueError, "nonfinite"),
        (torch.ones(1, 2, 8), torch.full((1, 1, 8), float("inf")), ValueError, "nonfinite"),
    ],
)
def test_input_guards(hidden, delta, error, match):
    with pytest.raises(error, match=match):
        NativeWorkspaceReadout(_head())(hidden, delta)


def test_device_mismatch_guards_without_allocating_gpu():
    readout = NativeWorkspaceReadout(_head())
    with pytest.raises(ValueError, match="share a device"):
        readout(torch.ones(1, 2, 8), torch.empty(1, 1, 8, device="meta"))
    state = readout(torch.ones(1, 2, 8), torch.zeros(1, 1, 8))
    with pytest.raises(ValueError, match="share a device"):
        state.choice_scores(torch.empty(2, dtype=torch.long, device="meta"))
    with pytest.raises(ValueError, match="share a device"):
        state.cross_entropy(torch.empty(1, dtype=torch.long, device="meta"))


def test_unsupported_and_nonfinite_head_guards():
    with pytest.raises(TypeError, match="nn.Linear"):
        NativeWorkspaceReadout(nn.Identity())
    with pytest.raises(TypeError, match="native float32 or bfloat16"):
        NativeWorkspaceReadout(_head(torch.float64))
    head = _head()
    head.weight[0, 0] = float("nan")
    with pytest.raises(ValueError, match="head weight.*nonfinite"):
        NativeWorkspaceReadout(head)
    head = _head()
    readout = NativeWorkspaceReadout(head)
    head.weight[0, 0] = float("nan")
    with pytest.raises(ValueError, match="Native logits.*nonfinite"):
        readout(torch.ones(1, 2, 8), torch.zeros(1, 1, 8))


@pytest.mark.parametrize("wrong_dtype", [False, True])
def test_malformed_linear_subclass_output_fails_closed(wrong_dtype):
    class MalformedHead(nn.Linear):
        def forward(self, value):
            logits = super().forward(value)
            return logits.double() if wrong_dtype else logits[:, -1:]

    readout = NativeWorkspaceReadout(MalformedHead(8, 17).requires_grad_(False))
    with pytest.raises(ValueError, match="preserve"):
        readout(torch.ones(1, 2, 8), torch.zeros(1, 1, 8))
