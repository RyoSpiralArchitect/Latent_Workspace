"""Tiny local native-owner mechanics, not fresh-process/CUDA/semantic admission."""

import copy
import random

import numpy as np
import pytest
import torch
from test_adapter_native_learner_v2 import FAILURES, corrupt, mutate_tensors, versions
from test_v15_native_learner import CONTRACT, META, OPT, owner
from test_v18_selection_pipeline import bound
from test_v18_selection_state import mutate

from latent_workspace_ft_v10.adapted_pair_objective import adapted_pair_objective
from latent_workspace_ft_v10.adapter_native_learner_v2 import AdapterNativeLearnerV2
from latent_workspace_ft_v10.native_training_preparation import (
    prepare_native_gradient_checkpointing,
)
from latent_workspace_ft_v10.slot_contrast_learner import SlotContrastNativeLearner
from latent_workspace_ft_v10.training_binding import MistralTrainingBinding
from latent_workspace_ft_v10.v15_native_learner import V15NativeLearner, rng_state, tree_hash
from latent_workspace_ft_v10.v16_slot_contrast import SlotContrastWorkspaceBridge
from latent_workspace_ft_v10.v18_selection_learner import (
    CONTRACT_KEY,
    FORMAT,
    POLICY_FORMAT,
    SelectionNativeLearner,
)
from latent_workspace_ft_v10.v18_selection_pipeline import SelectionWorkspacePipeline
from latent_workspace_ft_v10.v18_selection_reader import SelectionWorkspaceBridge
from latent_workspace_ft_v10.v18_selection_state import SelectionStateBinding
from latent_workspace_ft_v10.v18_window_learner import _ReaderGuard


@pytest.fixture(autouse=True)
def threads():
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


def policy(mode="ordered_difference"):
    return {"schema": POLICY_FORMAT, "interaction_query": mode}


def build(dtype=torch.float32, full=True, mode="ordered_difference",
          factor="slot_contrast", checkpointing=True, *, legacy=False, zero=False,
          initial_buffer_alias=False):
    original = owner(dtype, full)
    reader_class = SlotContrastWorkspaceBridge if legacy else SelectionWorkspaceBridge
    bridge = reader_class(original.bridge, mode=factor)
    if zero:
        with torch.no_grad():
            bridge.common.up.weight.zero_()
    if initial_buffer_alias:
        original.base.register_buffer("selection_alias", next(original.base.parameters()).detach())
    preparation = prepare_native_gradient_checkpointing(original.base) if checkpointing else None
    binding = MistralTrainingBinding(original.base, 1)
    contract = {
        "original_base_sha256": tree_hash(original.base.state_dict()),
        "objective": copy.deepcopy(CONTRACT),
        "preparation": preparation,
        "data": "tiny engineering fixture, no model-quality claim",
        CONTRACT_KEY: policy(mode),
    }
    before = tree_hash(rng_state())
    cls = SlotContrastNativeLearner if legacy else SelectionNativeLearner
    result = cls(
        binding, bridge, full_update=full, optimizer_config=OPT, run_contract=contract,
        **({} if legacy else {"selection_policy": policy(mode)}),
    )
    assert tree_hash(rng_state()) == before
    return result


def objective(learner, affected):
    def write(side):
        assert side in (0, 1, "unrelated")
        ids = (1, 8, 9) if side == 0 else (1, 9, 8) if side == 1 else (1, 10, 11)
        hidden = learner.context(ids)
        assert hidden.requires_grad == learner.full_update
        return learner.bridge.write_memory(hidden, torch.ones(hidden.shape[:2], dtype=torch.long))

    span = bound()
    return adapted_pair_objective(
        learner.pipeline, write, prefix_ids=span.prefix_ids,
        span=span.question_span if type(learner) is SlotContrastNativeLearner else span,
        candidate_ids=(6, 7), labels=(0, 1) if affected else (1, 1), contract=CONTRACT,
    )


def update(learner):
    learner.begin_window(("affected", "unaffected"))
    rows = []
    for key, affected in (("affected", True), ("unaffected", False)):
        loss, components = objective(learner, affected)
        row = {name: float(value.detach()) for name, value in components.items()}
        spill = learner.backward_pair(key, loss)
        assert spill["current_gradient_count"] == len(learner.named)
        rows.append((row, spill))
    return rows, learner.step()


def restore(target, payload, *, contract=None, expected_policy=None, receipt=None):
    return SelectionNativeLearner.restore(
        target.binding, target.bridge, payload,
        expected_selection_policy=(
            target.selection_policy if expected_policy is None else expected_policy
        ),
        expected_metadata=META,
        expected_run_contract=target.run_contract if contract is None else contract,
        expected_state_sha256=tree_hash(payload) if receipt is None else receipt,
    )


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


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("mode", SelectionWorkspacePipeline.MODES)
@pytest.mark.parametrize("factor", ["slot_contrast", "raw_matched_control"])
def test_two_windows_serialized_same_process_replay_snapshot_and_rng(
    tmp_path, dtype, full, mode, factor,
):
    learner = build(dtype, full, mode, factor)
    update(learner)
    receipt = learner.save(tmp_path / "step1.pt", META)
    assert receipt["format"] == FORMAT
    payload = torch.load(tmp_path / "step1.pt", map_location="cpu", weights_only=True)
    before = tree_hash(payload)
    expected_update = update(learner)
    expected = tree_hash(learner.payload(META))
    after = random.random(), np.random.rand(), torch.rand(3)
    fresh = build(dtype, full, mode, factor)
    resumed = restore(
        fresh, payload, contract=learner.run_contract, receipt=receipt["state_sha256"]
    )
    assert tree_hash(update(resumed)) == tree_hash(expected_update)
    assert tree_hash(resumed.payload(META)) == expected
    assert (random.random(), np.random.rand()) == after[:2]
    assert torch.equal(torch.rand(3), after[2])
    assert tree_hash(payload) == before
    with pytest.raises(FileExistsError):
        resumed.save(tmp_path / "step1.pt", META)


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("factor", ["slot_contrast", "raw_matched_control"])
@pytest.mark.parametrize("checkpointing", [False, True])
def test_final_route_matches_v16_all_losses_spills_updates_and_state(
    dtype, full, factor, checkpointing,
):
    actual = build(dtype, full, "final", factor, checkpointing)
    legacy = build(dtype, full, "final", factor, checkpointing, legacy=True)
    assert state(actual) == state(legacy)
    for _ in range(2):
        assert tree_hash(update(actual)) == tree_hash(update(legacy))
        assert state(actual) == state(legacy)


@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("failure", FAILURES + [
    "selection", "partitions", "extra", "layout", "typed_metadata", "v16_format",
    "master_offset", "bridge_offset",
])
def test_rejected_rehashed_restore_leaves_all_target_state_and_rng_unchanged(full, failure):
    source = build(torch.bfloat16, full)
    update(source)
    payload = source.payload(META)
    corrupt(payload, failure, full)
    if failure == "selection":
        payload["selection_policy"]["interaction_query"] = "final"
    elif failure == "partitions":
        payload["reader"]["parameter_partitions"]["writer"].pop()
    elif failure == "extra":
        payload["unknown"] = {}
    elif failure == "layout":
        next(iter(payload["tensor_layout"].values()))["stride"] = [999]
    elif failure == "typed_metadata":
        payload["metadata"] = {"flag": True}
    elif failure == "v16_format":
        payload["format"] = "v16-slot-contrast-native-resume-v1"
    elif failure in ("master_offset", "bridge_offset"):
        if failure == "master_offset" and not full:
            payload["base_masters"]["unexpected"] = torch.ones(1)
        else:
            family = payload["base_masters"] if failure == "master_offset" else payload["bridge"]
            name = next(iter(family))
            original = family[name]
            padding = torch.zeros(original.numel() + 1, dtype=original.dtype)
            padding[1:].copy_(original.reshape(-1))
            family[name] = padding[1:].view(original.shape)
    target = build(torch.bfloat16, full)
    before = (tree_hash(target.payload(META)), versions(target),
              target.binding.readout._execution_key())
    saved_before, rng_before = tree_hash(payload), tree_hash(rng_state())
    with pytest.raises(ValueError):
        restore(target, payload, contract=source.run_contract,
                receipt="0" * 64 if failure == "receipt" else tree_hash(payload))
    assert (tree_hash(target.payload(META)), versions(target),
            target.binding.readout._execution_key()) == before
    assert tree_hash(payload) == saved_before
    assert tree_hash(rng_state()) == rng_before


@pytest.mark.parametrize("full", [False, True])
def test_independent_expected_policy_and_complete_contract_required(full):
    learner = build(full=full)
    payload = learner.payload(META)
    before = tree_hash(payload), versions(learner), tree_hash(rng_state())
    for expected, contract in (
        (policy("final"), learner.run_contract),
        (policy(), {k: v for k, v in learner.run_contract.items() if k != CONTRACT_KEY}),
        ({**policy(), "extra": True}, learner.run_contract),
        ({**policy(), "interaction_query": True}, learner.run_contract),
    ):
        with pytest.raises(ValueError):
            restore(learner, payload, expected_policy=expected, contract=contract)
    assert (tree_hash(learner.payload(META)), versions(learner), tree_hash(rng_state())) == before


@pytest.mark.parametrize("mutation", [
    "requires_grad", "training", "parameter_hook", "parameter_post_accumulate_hook",
    "storage_only", "callback", "validator", "shared_storage",
])
def test_live_reader_policy_mutation_rejected_before_window(mutation):
    learner = build()
    mutate(learner.bridge, mutation)
    rng_before = tree_hash(rng_state())
    with pytest.raises(ValueError):
        learner.begin_window(("q",))
    assert learner.window is None and learner.completed_steps == 0
    assert tree_hash(rng_state()) == rng_before


@pytest.mark.parametrize("mutation", [
    "policy", "contract_policy", "pipeline_mode", "pipeline_object", "guard_object",
    "native_flag", "layout_descriptor",
])
def test_live_selection_execution_identity_is_not_silently_rebound(mutation):
    learner = build()
    if mutation == "policy":
        learner.selection_policy["interaction_query"] = "final"
    elif mutation == "contract_policy":
        learner.run_contract[CONTRACT_KEY]["interaction_query"] = "final"
    elif mutation == "pipeline_mode":
        learner.pipeline.mode = "final"
    elif mutation == "pipeline_object":
        learner.pipeline = SelectionWorkspacePipeline(
            learner.bridge, learner.binding.readout, "ordered_difference"
        )
    elif mutation == "guard_object":
        learner.reader_binding = SelectionStateBinding(learner.bridge, learner.pipeline)
    elif mutation == "native_flag":
        next(learner.base.parameters()).requires_grad_(False)
    else:
        learner.tensor_layout.clear()
    before = tree_hash(rng_state()), versions(learner), state(learner)
    with pytest.raises(ValueError):
        learner.begin_window(("q",))
    assert learner.window is None
    assert (tree_hash(rng_state()), versions(learner), state(learner)) == before


@pytest.mark.parametrize("family", ["base", "bridge", "masters"])
@pytest.mark.parametrize("change", ["transpose", "storage"])
def test_live_owned_layout_and_storage_mutation_rejected(family, change):
    learner = build()
    values = (learner.masters if family == "masters"
              else dict(getattr(learner, family).named_parameters()))
    p = next(p for p in values.values() if p.ndim == 2 and p.shape[0] == p.shape[1])
    p.data = p.detach().t() if change == "transpose" else p.detach().clone()
    with pytest.raises(ValueError):
        learner.begin_window(("q",))
    assert learner.window is None


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("full", [False, True])
def test_partition_zero_warmup_and_no_grad_keeps_execution_identity(dtype, full):
    learner = build(dtype, full, zero=True)
    assert len(learner.bridge_named) == 32
    assert {k: len(v) for k, v in learner.reader["parameter_partitions"].items()} == {
        "writer": 20, "common_reader": 6, "interaction": 6,
    }
    before = tree_hash(learner.payload(META))
    with torch.no_grad():
        hidden = learner.context((1, 8, 9))
        memory, mask = learner.bridge.write_memory(hidden, torch.ones(hidden.shape[:2]))
        span = bound()
        out = learner.pipeline(span.prefix_ids, memory, mask, span=span)
        assert torch.count_nonzero(out.delta) == 0
    assert tree_hash(learner.payload(META)) == before
    loss, _ = objective(learner, True)
    loss.backward()
    assert all(p.grad is not None and torch.isfinite(p.grad).all() for _, p in learner.named)
    assert learner.bridge.query_projection.weight.grad.count_nonzero() == 0
    assert learner.bridge.common.writer.context_projection.weight.grad.count_nonzero() == 0
    for _, p in learner.named:
        p.grad = None
    update(learner)
    loss, _ = objective(learner, True)
    loss.backward()
    assert learner.bridge.common.writer.context_projection.weight.grad.abs().sum() > 0


@pytest.mark.parametrize("full", [False, True])
def test_snapshot_and_policy_ownership_step_zero_and_no_partial_save(full, tmp_path):
    learner = build(full=full)
    payload = learner.payload(META)
    fresh = build(full=full)
    restored = restore(fresh, payload, contract=learner.run_contract)
    assert tree_hash(restored.payload(META)) == tree_hash(payload)
    assert not payload["bridge_optimizer"]["state"]
    before = tree_hash(learner.payload(META))
    mutate_tensors(payload)
    payload["selection_policy"]["interaction_query"] = "final"
    payload["tensor_layout"].clear()
    assert tree_hash(learner.payload(META)) == before
    learner.begin_window(("q0", "q1"))
    with pytest.raises(ValueError):
        learner.save(tmp_path / "partial.pt", META)
    assert not (tmp_path / "partial.pt").exists()


@pytest.mark.parametrize("full", [False, True])
def test_successful_restore_does_not_alias_accepted_payload(full):
    source = build(full=full)
    update(source)
    accepted = source.payload(META)
    resumed = restore(build(full=full), accepted, contract=source.run_contract)
    before = tree_hash(resumed.payload(META)), versions(resumed), tree_hash(rng_state())
    mutate_tensors(accepted)
    accepted["selection_policy"]["interaction_query"] = "final"
    accepted["tensor_layout"].clear()
    assert (tree_hash(resumed.payload(META)), versions(resumed), tree_hash(rng_state())) == before


@pytest.mark.parametrize("full", [False, True])
def test_initial_native_parameter_buffer_storage_alias_is_rejected(full):
    with pytest.raises(ValueError, match="Shared native/reader/master/buffer storage"):
        build(full=full, initial_buffer_alias=True)


def test_arithmetic_publication_and_historical_whitelists_are_unchanged(monkeypatch):
    assert SelectionNativeLearner.step is V15NativeLearner.step
    assert SelectionNativeLearner.begin_window is V15NativeLearner.begin_window
    assert SelectionNativeLearner.save is V15NativeLearner.save
    learner = build()
    assert type(learner.reader_binding) is SelectionStateBinding
    calls = []
    original_restore = AdapterNativeLearnerV2.restore.__func__

    def tracked_restore(cls, *args, **kwargs):
        calls.append(cls)
        return original_restore(cls, *args, **kwargs)

    monkeypatch.setattr(AdapterNativeLearnerV2, "restore", classmethod(tracked_restore))
    saved = learner.payload(META)
    restored = restore(build(), saved, contract=learner.run_contract)
    assert calls == [SelectionNativeLearner]
    assert tree_hash(restored.payload(META)) == tree_hash(saved)
    with pytest.raises(ValueError):
        _ReaderGuard(learner.bridge)
    with pytest.raises(ValueError):
        AdapterNativeLearnerV2(
            learner.binding, learner.bridge, full_update=True, optimizer_config=OPT,
            run_contract=learner.run_contract,
        )
