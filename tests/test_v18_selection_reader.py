"""Split-query arithmetic contracts, not a semantic or 7B qualification.

Set LATENT_SLOT_STATE_TEST_DEVICE=cuda only within a separately authorized,
bounded runtime. CPU is the default; unavailable CUDA is not silently skipped.
"""

import inspect
import os

import pytest
import torch

from latent_workspace_ft_v10.precision_bridge import PrecisionAwareWorkspaceBridge
from latent_workspace_ft_v10.query_modulated_bridge import QueryModulatedWorkspaceBridge
from latent_workspace_ft_v10.v15_native_learner import tree_hash
from latent_workspace_ft_v10.v16_slot_contrast import SlotContrastWorkspaceBridge
from latent_workspace_ft_v10.v18_selection_reader import SelectionWorkspaceBridge
from latent_workspace_ft_v10.v18_window_learner import _ReaderGuard

DEVICE = os.environ.get("LATENT_SLOT_STATE_TEST_DEVICE", "cpu")
MODES = ("slot_contrast", "raw_matched_control")


@pytest.fixture(autouse=True)
def threads():
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


def make_bridge(cls=SelectionWorkspaceBridge, *, mode="slot_contrast", nonzero=True, common=None):
    torch.manual_seed(49)
    common_cls = QueryModulatedWorkspaceBridge if common is None else common
    common = common_cls(16, workspace_dim=8, heads=2, slots=3, max_delta_norm=1).to(DEVICE)
    with torch.no_grad():
        common.up.weight.normal_(std=0.05)
    bridge = cls(common, mode=mode)
    if nonzero:
        with torch.no_grad():
            bridge.up.weight.normal_(std=0.08)
    return bridge


def inputs(dtype=torch.float32, rank=3, memory_kind="diverse"):
    torch.manual_seed(63)
    query = torch.randn(2, 1, 16, device=DEVICE).to(dtype)
    if rank == 2:
        query = query.squeeze(1)
    memory = torch.randn(2, 3, 8, device=DEVICE)
    mask = torch.tensor([[1, 1, 1], [0, 1, 1]], device=DEVICE)
    if memory_kind == "equal_masked":
        memory = memory[:, :1].expand_as(memory).clone()
        memory[1, 0].fill_(42)
    elif memory_kind == "zero":
        memory.zero_()
    return query.requires_grad_(), memory.requires_grad_(), mask


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("common", [PrecisionAwareWorkspaceBridge, QueryModulatedWorkspaceBridge])
def test_initialization_parameters_state_names_and_rng_match_v16(mode, common):
    previous = make_bridge(SlotContrastWorkspaceBridge, mode=mode, nonzero=False, common=common)
    previous_rng = torch.get_rng_state()
    candidate = make_bridge(mode=mode, nonzero=False, common=common)
    assert torch.equal(torch.get_rng_state(), previous_rng)
    assert tree_hash(previous.state_dict()) == tree_hash(candidate.state_dict())
    assert list(previous.named_parameters()) != []
    assert [(n, tuple(p.shape)) for n, p in previous.named_parameters()] == [
        (n, tuple(p.shape)) for n, p in candidate.named_parameters()
    ]
    assert sum(p.numel() for p in previous.parameters()) == sum(
        p.numel() for p in candidate.parameters()
    )
    assert type(candidate) is not type(previous)
    assert not isinstance(candidate, SlotContrastWorkspaceBridge)
    descriptor = candidate.describe()
    assert descriptor["schema"] == "v18-selection-prototype-v1"
    assert descriptor["checkpoint_qualification"] == "NOT_ADMITTED_BY_V18_OWNER"
    descriptor["common"]["cap"] = 99
    assert candidate.describe()["common"]["cap"] == 1


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("rank", [2, 3])
@pytest.mark.parametrize("nonzero", [False, True])
@pytest.mark.parametrize("memory_kind", ["diverse", "equal_masked", "zero"])
def test_same_query_forward_and_all_gradients_are_bitexact_v16(
    mode, dtype, rank, nonzero, memory_kind
):
    previous = make_bridge(SlotContrastWorkspaceBridge, mode=mode, nonzero=nonzero)
    candidate = make_bridge(mode=mode, nonzero=nonzero)
    old_query, old_memory, mask = inputs(dtype, rank, memory_kind)
    new_query = old_query.detach().clone().requires_grad_()
    new_memory = old_memory.detach().clone().requires_grad_()
    # A native BF16 query under outer autocast must retain FP32 bridge arithmetic.
    with torch.autocast(device_type=torch.device(DEVICE).type, dtype=torch.bfloat16):
        old_parts = previous.parts(old_query, old_memory, mask)
        new_parts = candidate.parts(new_query, new_query, new_memory, mask)
    for name in ("common", "interaction", "delta"):
        assert old_parts[name].dtype == new_parts[name].dtype == torch.float32
        assert torch.equal(old_parts[name], new_parts[name]), name
    assert torch.equal(
        candidate.read_delta(new_query, new_query, new_memory, mask), new_parts["delta"]
    )
    old_grads = torch.autograd.grad(
        old_parts["delta"].square().sum() + old_parts["interaction"].sum(),
        (old_query, old_memory, *previous.parameters()),
        allow_unused=True,
    )
    new_grads = torch.autograd.grad(
        new_parts["delta"].square().sum() + new_parts["interaction"].sum(),
        (new_query, new_memory, *candidate.parameters()),
        allow_unused=True,
    )
    for index, (old, new) in enumerate(zip(old_grads, new_grads, strict=True)):
        if old is None:
            assert new is None, index
        else:
            assert new is not None and torch.equal(old, new), index


@pytest.mark.parametrize("mode", MODES)
def test_common_and_writer_routes_are_exactly_retained_with_independent_interaction(mode):
    bridge = make_bridge(mode=mode)
    common_query, memory, mask = inputs()
    interaction_query = torch.flip(common_query.detach(), (-1,)).requires_grad_()
    baseline = bridge.common.read_delta(common_query, memory, mask)
    a = bridge.parts(common_query, common_query, memory, mask)
    b = bridge.parts(common_query, interaction_query, memory, mask)
    assert torch.equal(a["common"], baseline)
    assert torch.equal(b["common"], baseline)
    assert not torch.equal(a["interaction"], b["interaction"])
    common_grads = torch.autograd.grad(
        b["common"].sum(), (common_query, interaction_query), allow_unused=True, retain_graph=True
    )
    assert common_grads[0] is not None and torch.count_nonzero(common_grads[0])
    assert common_grads[1] is None
    interaction_grad = torch.autograd.grad(b["interaction"].square().sum(), interaction_query)[0]
    assert torch.isfinite(interaction_grad).all() and torch.count_nonzero(interaction_grad)
    context = torch.randn(2, 5, 16, device=DEVICE, requires_grad=True)
    context_mask = torch.ones(2, 5, dtype=torch.long, device=DEVICE)
    expected_memory = bridge.common.write_memory(context, context_mask)
    actual_memory = bridge.write_memory(context, context_mask)
    assert all(
        torch.equal(a, b) for a, b in zip(expected_memory, actual_memory, strict=True)
    )
    expected_grads = torch.autograd.grad(expected_memory[0].sum(), context)
    actual_grads = torch.autograd.grad(actual_memory[0].sum(), context)
    assert torch.equal(expected_grads[0], actual_grads[0])


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("gain", [1.0, 100.0])
def test_budget_uses_common_query_output_only_and_retains_total_cap(mode, gain):
    bridge = make_bridge(mode=mode)
    common_query, memory, mask = inputs()
    interaction_query = torch.flip(common_query.detach(), (-1,)).requires_grad_()
    with torch.no_grad():
        bridge.up.weight.mul_(gain)
    raw_outputs = []
    handle = bridge.up.register_forward_hook(
        lambda module, args, output: raw_outputs.append(output)
    )
    try:
        part = bridge.parts(common_query, interaction_query, memory, mask)
    finally:
        handle.remove()
    assert len(raw_outputs) == 1
    raw = raw_outputs[0]
    cap = bridge.max_delta_norm
    expected_common = bridge.common.read_delta(common_query, memory, mask)
    assert not torch.equal(
        expected_common, bridge.common.read_delta(interaction_query, memory, mask)
    )
    bounded = raw * (cap / torch.sqrt(cap**2 + raw.square().sum(-1, keepdim=True)))
    remaining = (1 - expected_common.norm(dim=-1, keepdim=True) / cap).clamp(0, 1)
    assert torch.equal(part["interaction"], bridge.interaction_fraction * remaining * bounded)
    assert bool((part["delta"].norm(dim=-1) <= cap + 1e-6).all())
    room = bridge.interaction_fraction * (cap - part["common"].norm(dim=-1))
    assert bool((part["interaction"].norm(dim=-1) <= room + 1e-6).all())


@pytest.mark.parametrize("slots", [1, 3, 7])
def test_equal_written_slots_null_interaction_with_separate_query_and_masked_padding(slots):
    bridge = make_bridge()
    common_query, memory, _ = inputs()
    query = torch.flip(common_query.detach(), (-1,)).requires_grad_()
    memory = memory[:, :1].expand(-1, slots, -1).clone().detach().requires_grad_()
    mask = torch.ones(2, slots, dtype=torch.long, device=DEVICE)
    if slots > 1:
        mask[1, 0] = 0
        with torch.no_grad():
            memory[1, 0].fill_(42)
    part = bridge.parts(common_query, query, memory, mask)
    assert torch.count_nonzero(part["interaction"]) == 0
    assert torch.equal(part["delta"], part["common"])
    assert torch.count_nonzero(torch.autograd.grad(part["interaction"].sum(), query)[0]) == 0


def test_mixed_2d_and_3d_queries_have_the_same_geometry():
    bridge = make_bridge()
    query, memory, mask = inputs()
    expected = bridge.read_delta(query, query, memory, mask)
    assert torch.equal(expected, bridge.read_delta(query.squeeze(1), query, memory, mask))
    assert torch.equal(expected, bridge.read_delta(query, query.squeeze(1), memory, mask))


@pytest.mark.parametrize(
    "failure",
    [
        "not_tensor",
        "rank1",
        "rank4",
        "empty",
        "wrong_hidden",
        "two_positions",
        "different_batch",
        "integer",
        "complex",
        "nan",
        "infinity",
        "fp32_overflow",
        "other_device",
    ],
)
def test_bad_interaction_rejects_before_common_computation(monkeypatch, failure):
    bridge = make_bridge()
    common_query, memory, mask = inputs()
    query = common_query.detach().clone()
    if failure == "not_tensor":
        query = [1.0]
    elif failure == "rank1":
        query = query[0, 0]
    elif failure == "rank4":
        query = query.unsqueeze(0)
    elif failure == "empty":
        query = query[:0]
    elif failure == "wrong_hidden":
        query = query[..., :-1]
    elif failure == "two_positions":
        query = query.expand(-1, 2, -1)
    elif failure == "different_batch":
        query = query[:1]
    elif failure == "integer":
        query = query.long()
    elif failure == "complex":
        query = query.to(torch.complex64)
    elif failure == "nan":
        query[0, 0, 0] = float("nan")
    elif failure == "infinity":
        query[0, 0, 0] = float("inf")
    elif failure == "fp32_overflow":
        query = query.double()
        query[0, 0, 0] = 1e300
    elif failure == "other_device":
        query = torch.empty_like(query, device="meta")

    def forbidden(*args):
        pytest.fail("Common computation occurred before interaction validation")

    monkeypatch.setattr(bridge.common, "read_delta", forbidden)
    with pytest.raises(ValueError):
        bridge.parts(common_query, query, memory, mask)


def test_bad_common_query_also_rejects_before_any_route_computation(monkeypatch):
    bridge = make_bridge()
    query, memory, mask = inputs()

    def forbidden(*args):
        pytest.fail("A malformed common query reached common computation")

    monkeypatch.setattr(bridge.common, "read_delta", forbidden)
    with pytest.raises(ValueError, match="Common query"):
        bridge.parts(query.long(), query, memory, mask)


def test_non_fp32_parameters_and_changed_common_policy_fail():
    bridge = make_bridge()
    query, memory, mask = inputs()
    bridge.up.to(torch.bfloat16)
    with pytest.raises(ValueError, match="parameters must be FP32"):
        bridge.parts(query, query, memory, mask)
    bridge.up.float()
    bridge.common._modulation_strength = 0.5
    with pytest.raises(ValueError, match="Common reader policy changed"):
        bridge.parts(query, query, memory, mask)


@pytest.mark.parametrize("value", [0, -1, 1.1, float("nan"), float("inf"), True, "0.25"])
def test_bad_interaction_fraction_rejects(value):
    common = make_bridge().common
    with pytest.raises(ValueError, match="Interaction fraction"):
        SelectionWorkspaceBridge(common, interaction_fraction=value)


def test_explicit_api_and_unqualified_owner_rejection():
    bridge = make_bridge()
    expected = ["common_query", "interaction_query", "memory", "mask"]
    assert list(inspect.signature(bridge.parts).parameters) == expected
    assert list(inspect.signature(bridge.read_delta).parameters) == expected
    assert list(inspect.signature(bridge.write_memory).parameters) == ["context", "mask"]
    with pytest.raises(ValueError, match="Unqualified reader class"):
        _ReaderGuard(bridge)
    with pytest.raises(ValueError, match="Unknown V18 interaction factor"):
        SelectionWorkspaceBridge(bridge.common, mode="ordered_difference")
