"""Tiny V19 dual-budget mechanics: reader, binding, native and window owners.

CPU or CUDA via LATENT_V19_TEST_DEVICE. Engineering only; no semantic claim.
"""

import copy
import math
import os

import pytest
import torch
from test_v15_native_learner import CONTRACT, META, OPT, owner
from test_v18_selection_pipeline import bound
from test_v18_window_learner import schedule, synthetic_bank

from latent_workspace_ft_v10.adapted_pair_objective import adapted_pair_objective
from latent_workspace_ft_v10.native_training_preparation import (
    prepare_native_gradient_checkpointing,
)
from latent_workspace_ft_v10.training_binding import MistralTrainingBinding
from latent_workspace_ft_v10.v15_native_learner import rng_state, tree_hash
from latent_workspace_ft_v10.v18_selection_learner import FORMAT as V18_FORMAT
from latent_workspace_ft_v10.v18_selection_pipeline import SelectionWorkspacePipeline
from latent_workspace_ft_v10.v18_selection_reader import SelectionWorkspaceBridge
from latent_workspace_ft_v10.v18_selection_window_learner import (
    FORMAT as V18_WINDOW_FORMAT,
)
from latent_workspace_ft_v10.v19_dual_budget_learner import (
    CONTRACT_KEY,
    FORMAT,
    POLICY_FORMAT,
    DualBudgetNativeLearner,
)
from latent_workspace_ft_v10.v19_dual_budget_pipeline import DualBudgetWorkspacePipeline
from latent_workspace_ft_v10.v19_dual_budget_reader import DualBudgetWorkspaceBridge
from latent_workspace_ft_v10.v19_dual_budget_state import DualBudgetStateBinding
from latent_workspace_ft_v10.v19_dual_budget_window_learner import (
    CONTRACT_KEY as WINDOW_KEY,
)
from latent_workspace_ft_v10.v19_dual_budget_window_learner import (
    FORMAT as WINDOW_FORMAT,
)
from latent_workspace_ft_v10.v19_dual_budget_window_learner import V19DualBudgetWindowLearner

DEVICE = os.environ.get("LATENT_V19_TEST_DEVICE", "cpu")


@pytest.fixture(autouse=True)
def threads():
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


def policy(mode="ordered_difference"):
    return {"schema": POLICY_FORMAT, "workspace_query": mode}


def parts(dtype=torch.float32, full=True):
    original = owner(dtype, full)
    original.base.to(DEVICE)
    return original


def dual(common, factor="slot_contrast", cap=0.25):
    return DualBudgetWorkspaceBridge(common, mode=factor, workspace_cap=cap).to(DEVICE)


def contract(base, mode, preparation):
    return {
        "original_base_sha256": tree_hash(base.state_dict()),
        "objective": copy.deepcopy(CONTRACT),
        "preparation": preparation,
        "data": "tiny V19 engineering fixture, no model-quality claim",
        CONTRACT_KEY: policy(mode),
    }


def native(dtype=torch.float32, full=True, mode="ordered_difference", factor="slot_contrast",
           cap=0.25, checkpointing=True):
    original = parts(dtype, full)
    bridge = dual(original.bridge, factor, cap)
    preparation = prepare_native_gradient_checkpointing(original.base) if checkpointing else None
    before = tree_hash(rng_state())
    learner = DualBudgetNativeLearner(
        MistralTrainingBinding(original.base, 1), bridge, workspace_policy=policy(mode),
        full_update=full, optimizer_config=OPT,
        run_contract=contract(original.base, mode, preparation),
    )
    assert tree_hash(rng_state()) == before
    return learner


def write_for(learner):
    def write(side):
        assert side in (0, 1, "unrelated")
        ids = (1, 8, 9) if side == 0 else (1, 9, 8) if side == 1 else (1, 10, 11)
        hidden = learner.context(ids)
        assert hidden.requires_grad == learner.full_update
        mask = torch.ones(hidden.shape[:2], dtype=torch.long, device=hidden.device)
        return learner.bridge.write_memory(hidden, mask)

    return write


def update(learner):
    span = bound()
    learner.begin_window(("affected", "unaffected"))
    rows = []
    for key, labels in (("affected", (0, 1)), ("unaffected", (1, 1))):
        loss, components = adapted_pair_objective(
            learner.pipeline, write_for(learner), prefix_ids=span.prefix_ids, span=span,
            candidate_ids=(6, 7), labels=labels, contract=CONTRACT,
        )
        values = {name: float(value.detach()) for name, value in components.items()}
        spill = learner.backward_pair(key, loss)
        assert spill["current_gradient_count"] == len(learner.named)
        rows.append((values, spill))
    return rows, learner.step()


def state(learner):
    return {
        "base": tree_hash(learner.base.state_dict()),
        "bridge": tree_hash(learner.bridge.state_dict()),
        "masters": tree_hash(learner.masters),
        "base_optimizer": tree_hash(
            learner.base_optimizer.state_dict() if learner.base_optimizer else None
        ),
        "bridge_optimizer": tree_hash(learner.bridge_optimizer.state_dict()),
    }


def restore_native(target, payload, *, expected_policy=None, receipt=None):
    return DualBudgetNativeLearner.restore(
        target.binding, target.bridge, payload,
        expected_workspace_policy=target.workspace_policy if expected_policy is None
        else expected_policy,
        expected_metadata=META,
        expected_run_contract=target.run_contract,
        expected_state_sha256=tree_hash(payload) if receipt is None else receipt,
    )


def memory(slots=3, equal=False, seed=3):
    generator = torch.Generator().manual_seed(seed)
    values = torch.randn(1, slots, 8, generator=generator)
    if equal:
        values = values[:, :1].expand(1, slots, 8).clone()
    return values.to(DEVICE), torch.ones(1, slots, dtype=torch.long, device=DEVICE)


def query(seed=4):
    return torch.randn(1, 1, 16, generator=torch.Generator().manual_seed(seed)).to(DEVICE)


# ---- reader -------------------------------------------------------------------


@pytest.mark.parametrize("factor", DualBudgetWorkspaceBridge.MODES)
def test_layout_and_initialization_match_the_v18_selection_reader(factor):
    left, right = parts(), parts()
    torch.manual_seed(11)
    v18 = SelectionWorkspaceBridge(left.bridge, mode=factor).to(DEVICE)
    torch.manual_seed(11)
    v19 = DualBudgetWorkspaceBridge(right.bridge, mode=factor, workspace_cap=0.25).to(DEVICE)
    assert list(v18.state_dict()) == list(v19.state_dict())
    assert tree_hash(v18.state_dict()) == tree_hash(v19.state_dict())
    assert sum(p.numel() for p in v18.parameters()) == sum(p.numel() for p in v19.parameters())


def test_workspace_budget_is_independent_of_a_saturated_common_route():
    left, right = parts(), parts()
    v18 = SelectionWorkspaceBridge(left.bridge).to(DEVICE)
    v19 = dual(right.bridge, cap=0.25)
    with torch.no_grad():
        v18.common.up.weight.normal_(std=50.0, generator=torch.Generator().manual_seed(1))
        v18.up.weight.normal_(std=50.0, generator=torch.Generator().manual_seed(2))
    v19.load_state_dict(v18.state_dict())
    values, mask = memory()
    q = query()
    with torch.no_grad():
        old, new = v18.parts(q, q, values, mask), v19.parts(q, q, values, mask)
    cap = v18.max_delta_norm
    assert torch.equal(old["common"], new["common"])
    assert float(new["common"].norm()) > 0.99 * cap
    assert float(old["interaction"].norm()) < 0.01 * 0.25 * cap
    assert 0.9 * 0.25 < float(new["interaction"].norm()) < 0.25
    assert torch.equal(new["delta"], new["common"] + new["interaction"])


def test_saturated_common_starves_v18_gradient_but_not_v19():
    left, right = parts(), parts()
    v18 = SelectionWorkspaceBridge(left.bridge).to(DEVICE)
    v19 = dual(right.bridge, cap=0.25)
    with torch.no_grad():
        v18.common.up.weight.normal_(std=1e4, generator=torch.Generator().manual_seed(1))
        v18.up.weight.normal_(std=0.1, generator=torch.Generator().manual_seed(2))
    v19.load_state_dict(v18.state_dict())
    values, mask = memory()
    q = query()
    for bridge in (v18, v19):
        bridge.zero_grad(set_to_none=True)
        bridge.parts(q, q, values, mask)["interaction"].sum().backward()
    assert not bool(v18.up.weight.grad.count_nonzero())
    assert bool(v19.up.weight.grad.count_nonzero())


def test_zero_up_and_equal_slots_give_an_exact_zero_workspace():
    original = parts()
    v19 = dual(original.bridge, cap=1.0)
    values, mask = memory()
    q = query()
    assert not bool(v19.parts(q, q, values, mask)["interaction"].count_nonzero())
    with torch.no_grad():
        v19.up.weight.normal_(std=0.2, generator=torch.Generator().manual_seed(5))
    equal, equal_mask = memory(equal=True)
    assert not bool(v19.parts(q, q, equal, equal_mask)["interaction"].count_nonzero())
    raw = dual(parts().bridge, "raw_matched_control", cap=1.0)
    raw.load_state_dict(v19.state_dict())
    assert bool(raw.parts(q, q, equal, equal_mask)["interaction"].count_nonzero())


def test_invalid_reader_configuration_is_rejected():
    common = parts().bridge
    with pytest.raises(ValueError, match="value factor"):
        DualBudgetWorkspaceBridge(common, mode="final")
    for cap in (0, -1.0, math.nan, math.inf, "0.25", True):
        with pytest.raises(ValueError, match="Workspace cap"):
            DualBudgetWorkspaceBridge(common, workspace_cap=cap)


@pytest.mark.parametrize("mode", DualBudgetWorkspacePipeline.MODES)
def test_pipeline_equals_v18_while_the_workspace_output_is_zero(mode):
    left, right = parts(), parts()
    v18 = SelectionWorkspaceBridge(left.bridge).to(DEVICE)
    v19 = dual(right.bridge)
    v19.load_state_dict(v18.state_dict())
    binding_left = MistralTrainingBinding(left.base, 1)
    binding_right = MistralTrainingBinding(right.base, 1)
    old = SelectionWorkspacePipeline(v18, binding_left.readout, mode)
    new = DualBudgetWorkspacePipeline(v19, binding_right.readout, mode)
    span = bound()
    hidden = binding_left.context((1, 8, 9))
    mask = torch.ones(hidden.shape[:2], dtype=torch.long, device=hidden.device)
    with torch.no_grad():
        values, slots = v18.write_memory(hidden, mask)
        a = old(span.prefix_ids, values, slots, span=span)
        b = new(span.prefix_ids, values, slots, span=span)
    assert torch.equal(a.readout.logits, b.readout.logits)
    assert torch.equal(a.delta, b.delta)
    assert new.describe()["workspace_query"] == mode


def test_state_binding_owns_partitions_and_rejects_foreign_objects():
    original = parts()
    bridge = dual(original.bridge)
    binding = MistralTrainingBinding(original.base, 1)
    pipeline = DualBudgetWorkspacePipeline(bridge, binding.readout, "ordered_difference")
    guard = DualBudgetStateBinding(bridge, pipeline)
    described = guard.describe()
    assert {k: len(v) for k, v in described["parameter_partitions"].items()} == {
        "writer": 20, "common_reader": 6, "workspace": 6,
    }
    assert described["reader"]["workspace_cap"] == 0.25
    other = SelectionWorkspaceBridge(parts().bridge).to(DEVICE)
    with pytest.raises(ValueError):
        DualBudgetWorkspacePipeline(other, binding.readout, "final")
    with pytest.raises(ValueError, match="Expected exact V19 pipeline"):
        DualBudgetStateBinding(bridge, SelectionWorkspacePipeline(other, binding.readout, "final"))
    handle = bridge.up.register_forward_hook(lambda *args: None)
    with pytest.raises(ValueError):
        guard.validate()
    handle.remove()
    guard.validate()
    bridge.register_buffer("unowned", torch.zeros(1, device=DEVICE))
    with pytest.raises(ValueError):
        DualBudgetStateBinding(bridge, pipeline)


# ---- native owner ---------------------------------------------------------------


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("mode", ["final", "ordered_difference"])
def test_native_owner_serialized_next_update_is_exact(dtype, full, mode):
    learner = native(dtype, full, mode)
    update(learner)
    payload = learner.payload(META)
    assert payload["format"] == FORMAT and payload["workspace_policy"] == policy(mode)
    second = update(learner)
    target = native(dtype, full, mode)
    restored = restore_native(target, payload)
    assert tree_hash(update(restored)) == tree_hash(second)
    assert state(restored) == state(learner)


def test_native_restore_rejects_policy_mismatch_and_foreign_payloads():
    learner = native()
    update(learner)
    payload = learner.payload(META)
    with pytest.raises(ValueError):
        restore_native(native(), payload, expected_policy=policy("final"))
    forged = copy.deepcopy(payload)
    forged["format"] = V18_FORMAT
    with pytest.raises(ValueError):
        restore_native(native(), forged, receipt=tree_hash(forged))
    renamed = copy.deepcopy(payload)
    renamed["selection_policy"] = renamed.pop("workspace_policy")
    with pytest.raises(ValueError):
        restore_native(native(), renamed, receipt=tree_hash(renamed))


def test_native_owner_rejects_the_v18_reader():
    original = parts()
    v18 = SelectionWorkspaceBridge(original.bridge).to(DEVICE)
    with pytest.raises(ValueError):
        DualBudgetNativeLearner(
            MistralTrainingBinding(original.base, 1), v18, workspace_policy=policy(),
            full_update=True, optimizer_config=OPT,
            run_contract=contract(original.base, "ordered_difference", None),
        )


# ---- window owner ---------------------------------------------------------------


def window_owner(dtype, full, factor="slot_contrast", cap=0.25, mode="ordered_difference"):
    original = parts(dtype, full)
    bridge = dual(original.bridge, factor, cap)
    preparation = prepare_native_gradient_checkpointing(original.base)
    binding = MistralTrainingBinding(original.base, 1)
    run = {
        "original_base_sha256": tree_hash(original.base.state_dict()),
        "objective": {"terms": copy.deepcopy(CONTRACT), "eos_weight": 0.0,
                      "query_mode": "final"},
        "preparation": preparation,
        "data": "tiny V19 window fixture; no semantic claim",
        CONTRACT_KEY: policy(mode),
    }
    bank = synthetic_bank(run["original_base_sha256"], tree_hash(binding.describe()), dtype)
    run["reference_source"] = dict(bank.source._asdict())
    before = tree_hash(rng_state())
    learner = V19DualBudgetWindowLearner(
        binding, bridge, workspace_policy=policy(mode), full_update=full,
        optimizer_config=OPT, run_contract=run, schedule=schedule(), reference_bank=bank,
    )
    assert tree_hash(rng_state()) == before and WINDOW_KEY not in run
    return learner, bank


def window_update(learner):
    spec = learner.current_spec
    span = bound()
    learner.begin_window()
    rows = []
    for identifier in spec.ids:
        components, spill = learner.backward_pair(
            identifier, write_memory=write_for(learner), prefix_ids=span.prefix_ids,
            span=span, candidate_ids=(6, 7),
        )
        rows.append((identifier, {k: float(v.detach()) for k, v in components.items()}, spill))
    return rows, learner.step()


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("cap", [0.25, 1.0])
def test_window_owner_complete_windows_and_independent_restore(tmp_path, dtype, full, cap):
    learner, bank = window_owner(dtype, full, cap=cap)
    window_update(learner)
    receipt = learner.save(tmp_path / "window1.pt", META)
    assert receipt["format"] == WINDOW_FORMAT and receipt["completed_steps"] == 1
    second = window_update(learner)
    final = tree_hash(learner.payload(META))
    target, target_bank = window_owner(dtype, full, cap=cap)
    payload = torch.load(tmp_path / "window1.pt", map_location="cpu", weights_only=True)
    restored = V19DualBudgetWindowLearner.restore(
        target.binding, target.bridge, payload,
        expected_workspace_policy=policy(), expected_metadata=META,
        expected_run_contract=target.base_run_contract, expected_schedule=schedule(),
        expected_reference_bank=target_bank, expected_state_sha256=receipt["state_sha256"],
    )
    assert restored.completed_steps == 1
    assert tree_hash(window_update(restored)) == tree_hash(second)
    assert tree_hash(restored.payload(META)) == final


def test_window_owner_raw_factor_and_partial_window_rejection(tmp_path):
    learner, _ = window_owner(torch.float32, True, factor="raw_matched_control", cap=1.0)
    span = bound()
    learner.begin_window()
    first = learner.current_spec.ids[0]
    learner.backward_pair(first, write_memory=write_for(learner), prefix_ids=span.prefix_ids,
                          span=span, candidate_ids=(6, 7))
    with pytest.raises(ValueError, match="complete-window"):
        learner.payload(META)
    with pytest.raises(ValueError):
        learner.step()


def test_window_restore_rejects_a_v18_envelope_format():
    learner, bank = window_owner(torch.float32, True)
    window_update(learner)
    payload = learner.payload(META)
    forged = copy.deepcopy(payload)
    forged["format"] = V18_WINDOW_FORMAT
    target, target_bank = window_owner(torch.float32, True)
    with pytest.raises(ValueError, match="V19 window checkpoint format"):
        V19DualBudgetWindowLearner.restore(
            target.binding, target.bridge, forged,
            expected_workspace_policy=policy(), expected_metadata=META,
            expected_run_contract=target.base_run_contract, expected_schedule=schedule(),
            expected_reference_bank=target_bank, expected_state_sha256=tree_hash(forged),
        )
