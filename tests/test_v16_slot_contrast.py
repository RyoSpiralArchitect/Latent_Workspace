"""Mechanism contracts only: no semantic win, benchmark or new 7B training."""

import copy
import inspect

import pytest
import torch
from test_adapter_native_learner import new_owner
from test_v15_native_learner import META, OPT, SPAN

from latent_workspace_ft_v10.adapted_workspace import AdaptedWorkspacePipeline
from latent_workspace_ft_v10.adapter_native_learner_v2 import AdapterNativeLearnerV2
from latent_workspace_ft_v10.query_modulated_bridge import QueryModulatedWorkspaceBridge
from latent_workspace_ft_v10.v15_native_learner import tree_hash
from latent_workspace_ft_v10.v16_slot_contrast import SlotContrastWorkspaceBridge


@pytest.fixture(autouse=True)
def threads():
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


def fixture(mode="slot_contrast", *, nonzero=True):
    torch.manual_seed(49)
    common = QueryModulatedWorkspaceBridge(16, workspace_dim=8, heads=2, slots=3, max_delta_norm=1)
    with torch.no_grad():
        common.up.weight.normal_(std=0.05)
    bridge = SlotContrastWorkspaceBridge(common, mode=mode)
    if nonzero:
        with torch.no_grad():
            bridge.up.weight.normal_(std=0.08)
    query = torch.randn(2, 1, 16, requires_grad=True)
    memory = torch.randn(2, 3, 8, requires_grad=True)
    mask = torch.tensor([[1, 1, 1], [0, 1, 1]], dtype=torch.long)
    return bridge, query, memory, mask


@pytest.mark.parametrize("mode", ["slot_contrast", "raw_matched_control"])
def test_initialization_is_exact_common_path(mode):
    bridge, query, memory, mask = fixture(mode, nonzero=False)
    assert torch.equal(
        bridge.read_delta(query, memory, mask), bridge.common.read_delta(query, memory, mask)
    )


def test_matched_control_has_exact_same_tensors_and_parameter_count():
    candidate, *_ = fixture()
    control, *_ = fixture("raw_matched_control")
    assert tree_hash(candidate.state_dict()) == tree_hash(control.state_dict())
    assert sum(p.numel() for p in candidate.parameters()) == sum(
        p.numel() for p in control.parameters()
    )
    assert candidate.describe() != control.describe()


@pytest.mark.parametrize("slots", [1, 3, 7])
def test_identical_slot_carrier_has_exact_zero_interaction_even_after_nonzero_up(slots):
    bridge, query, memory, _ = fixture()
    same = memory[:, :1].expand(-1, slots, -1).clone().detach().requires_grad_()
    mask = torch.ones(2, slots, dtype=torch.long)
    if slots > 1:
        mask[1, 0] = 0
        with torch.no_grad():
            same[1, 0].fill_(42)  # Masked values do not invalidate the null.
    part = bridge.parts(query, same, mask)
    assert torch.count_nonzero(part["interaction"]) == 0
    assert torch.equal(part["delta"], part["common"])
    grad = torch.autograd.grad(part["interaction"].sum(), query)[0]
    assert torch.count_nonzero(grad) == 0


def test_raw_control_exposes_identical_carrier_loophole():
    bridge, query, memory, mask = fixture("raw_matched_control")
    same = memory[:, :1].expand_as(memory)
    part = bridge.parts(query, same, mask)
    assert torch.count_nonzero(part["interaction"]) > 0


@pytest.mark.parametrize("mode", ["slot_contrast", "raw_matched_control"])
def test_zero_written_memory_is_exact_identity(mode):
    bridge, query, memory, mask = fixture(mode)
    assert torch.count_nonzero(bridge.read_delta(query, torch.zeros_like(memory), mask)) == 0


@pytest.mark.parametrize("gain", [1.0, 100.0])
def test_separate_norm_budget_preserves_total_cap_and_common_output(gain):
    bridge, query, memory, mask = fixture()
    with torch.no_grad():
        bridge.up.weight.mul_(gain)
    part = bridge.parts(query, memory, mask)
    assert torch.equal(part["common"], bridge.common.read_delta(query, memory, mask))
    assert bool((part["delta"].norm(dim=-1) <= bridge.max_delta_norm + 1e-6).all())
    room = bridge.interaction_fraction * (bridge.max_delta_norm - part["common"].norm(dim=-1))
    assert bool((part["interaction"].norm(dim=-1) <= room + 1e-6).all())


def test_question_and_memory_gradients_are_live_for_diverse_slots():
    bridge, query, memory, mask = fixture()
    value = bridge.parts(query, memory, mask)["interaction"]
    gradients = torch.autograd.grad(value.square().sum(), (query, memory, bridge.up.weight))
    assert all(torch.isfinite(g).all() and torch.count_nonzero(g) for g in gradients)


def test_writer_unchanged_query_independent_and_no_label_or_donor_input():
    bridge, _, _, _ = fixture()
    context, mask = torch.randn(2, 5, 16), torch.ones(2, 5, dtype=torch.long)
    a, b = bridge.write_memory(context, mask), bridge.common.write_memory(context, mask)
    assert all(torch.equal(left, right) for left, right in zip(a, b, strict=True))
    assert list(inspect.signature(bridge.read_delta).parameters) == ["query", "memory", "mask"]
    assert list(inspect.signature(bridge.write_memory).parameters) == ["context", "mask"]


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_native_pipeline_zero_identity_and_live_backward(dtype):
    owner = new_owner(dtype)
    bridge = SlotContrastWorkspaceBridge(copy.deepcopy(owner.bridge))
    with torch.no_grad():
        bridge.up.weight.normal_(std=0.08)
    pipeline = AdaptedWorkspacePipeline(bridge, owner.binding.readout)
    context = owner.context((1, 8, 9))
    memory, mask = bridge.write_memory(context, torch.ones(context.shape[:2], dtype=torch.long))
    with owner.binding.readout.objective():
        owner.binding.readout.prepare(SPAN.prefix_ids)
        zero = pipeline(SPAN.prefix_ids, torch.zeros_like(memory), mask, span=SPAN)
        actual = pipeline(SPAN.prefix_ids, memory, mask, span=SPAN)
    native = owner.base(torch.tensor([SPAN.prefix_ids]), use_cache=False).logits
    assert torch.equal(zero.readout.logits, native)
    actual.readout.cross_entropy(torch.tensor([6])).backward()
    assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in bridge.parameters())
    assert all(p.grad is not None for p in owner.base.parameters())


def test_unqualified_reader_cannot_silently_enter_v15_checkpoint_owner():
    owner = new_owner()
    bridge = SlotContrastWorkspaceBridge(owner.bridge)
    with pytest.raises(ValueError, match="Unknown reader class"):
        AdapterNativeLearnerV2(
            owner.binding,
            bridge,
            full_update=True,
            optimizer_config=OPT,
            run_contract=owner.run_contract,
        )
    assert owner.payload(META)["completed_steps"] == 0
