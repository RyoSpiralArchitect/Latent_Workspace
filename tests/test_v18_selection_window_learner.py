"""Tiny complete-window selection ownership; CPU/CUDA via explicit test device."""

import copy
import os
import random

import numpy as np
import pytest
import torch
from test_adapter_native_learner_v2 import mutate_tensors, versions
from test_v15_native_learner import CONTRACT, META, OPT, owner
from test_v18_selection_learner import policy, state
from test_v18_selection_pipeline import bound
from test_v18_window_learner import (
    CORRUPTIONS,
    corrupt_outer,
    scalar_components,
    schedule,
    synthetic_bank,
)

from latent_workspace_ft_v10.native_training_preparation import (
    prepare_native_gradient_checkpointing,
)
from latent_workspace_ft_v10.training_binding import MistralTrainingBinding
from latent_workspace_ft_v10.v15_native_learner import rng_state, tree_hash
from latent_workspace_ft_v10.v16_slot_contrast import SlotContrastWorkspaceBridge
from latent_workspace_ft_v10.v18_selection_learner import CONTRACT_KEY as SELECTION_KEY
from latent_workspace_ft_v10.v18_selection_reader import SelectionWorkspaceBridge
from latent_workspace_ft_v10.v18_selection_window_learner import (
    CONTRACT_KEY,
    FORMAT,
    V18SelectionWindowLearner,
)
from latent_workspace_ft_v10.v18_window_learner import V18WindowLearner

DEVICE = os.environ.get("LATENT_SLOT_STATE_TEST_DEVICE", "cpu")


@pytest.fixture(autouse=True)
def threads():
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


def build(dtype=torch.float32, full=True, mode="ordered_difference",
          factor="slot_contrast", checkpointing=True, *, with_bank=True,
          legacy=False, windows=None):
    parts = owner(dtype, full)
    parts.base.to(DEVICE)
    cls = SlotContrastWorkspaceBridge if legacy else SelectionWorkspaceBridge
    bridge = cls(parts.bridge, mode=factor).to(DEVICE)
    preparation = prepare_native_gradient_checkpointing(parts.base) if checkpointing else None
    binding = MistralTrainingBinding(parts.base, 1)
    original_sha = tree_hash(parts.base.state_dict())
    contract = {
        "original_base_sha256": original_sha,
        "objective": {"terms": copy.deepcopy(CONTRACT), "eos_weight": 0.0,
                      "query_mode": "final"},
        "preparation": preparation,
        "data": "synthetic selection window ownership fixture; no semantic claim",
        SELECTION_KEY: policy(mode),
    }
    bank = synthetic_bank(original_sha, tree_hash(binding.describe()), dtype) if with_bank else None
    if bank is not None:
        contract["reference_source"] = dict(bank.source._asdict())
    before = tree_hash(rng_state())
    result = (V18WindowLearner if legacy else V18SelectionWindowLearner)(
        binding, bridge, full_update=full, optimizer_config=OPT, run_contract=contract,
        schedule=schedule() if windows is None else windows, reference_bank=bank,
        **({} if legacy else {"selection_policy": policy(mode)}),
    )
    assert tree_hash(rng_state()) == before
    assert result.base_run_contract == contract and CONTRACT_KEY not in contract
    assert all(p.device.type == DEVICE for p in result.base.parameters())
    return result, bank


def pair_kwargs(learner):
    def write(side):
        assert side in (0, 1, "unrelated")
        ids = (1, 8, 9) if side == 0 else (1, 9, 8) if side == 1 else (1, 10, 11)
        hidden = learner.context(ids)
        assert hidden.requires_grad == learner.full_update
        return learner.bridge.write_memory(
            hidden, torch.ones(hidden.shape[:2], dtype=torch.long, device=hidden.device),
        )
    span = bound()
    return {"write_memory": write, "prefix_ids": span.prefix_ids, "candidate_ids": (6, 7),
            "span": span.question_span if type(learner) is V18WindowLearner else span}


def update(learner):
    spec = learner.current_spec
    learner.begin_window()
    rows = []
    for occurrence_id in spec.ids:
        components, spill = learner.backward_pair(occurrence_id, **pair_kwargs(learner))
        assert spill["current_gradient_count"] == len(learner.inner.named)
        rows.append((occurrence_id, scalar_components(components), spill))
    return rows, learner.step()


def restore(target, payload, *, contract=None, bank=None, windows=None,
            selection=None, receipt=None, **kwargs):
    return V18SelectionWindowLearner.restore(
        target.binding, target.bridge, payload,
        expected_selection_policy=target.inner.selection_policy if selection is None else selection,
        expected_metadata=META,
        expected_run_contract=target.base_run_contract if contract is None else contract,
        expected_schedule=schedule() if windows is None else windows,
        expected_reference_bank=bank,
        expected_state_sha256=tree_hash(payload) if receipt is None else receipt,
        **kwargs,
    )


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("mode", ["final", "ordered_difference", "symmetric_mean"])
@pytest.mark.parametrize("factor", ["slot_contrast", "raw_matched_control"])
def test_complete_unequal_windows_exact_serialized_resume(tmp_path, dtype, full, mode, factor):
    source, bank = build(dtype, full, mode, factor)
    assert len(update(source)[0]) == 2
    receipt = source.save(tmp_path / "step1.pt", META)
    assert receipt["format"] == FORMAT
    payload = torch.load(tmp_path / "step1.pt", map_location="cpu", weights_only=True)
    before = tree_hash(payload)
    expected = update(source)
    assert len(expected[0]) == 3
    expected_state = tree_hash(source.payload(META))
    expected_random = random.random(), np.random.rand(), torch.rand(3, device=DEVICE)
    target, fresh_bank = build(dtype, full, mode, factor)
    actual = restore(target, payload, bank=fresh_bank, receipt=receipt["state_sha256"])
    assert tree_hash(update(actual)) == tree_hash(expected)
    assert tree_hash(actual.payload(META)) == expected_state
    assert (random.random(), np.random.rand()) == expected_random[:2]
    assert torch.equal(torch.rand(3, device=DEVICE), expected_random[2])
    assert tree_hash(payload) == before and fresh_bank == bank
    with pytest.raises(FileExistsError):
        actual.save(tmp_path / "step1.pt", META)
    with pytest.raises(ValueError):
        actual.begin_window()


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("factor", ["slot_contrast", "raw_matched_control"])
@pytest.mark.parametrize("checkpointing", [False, True])
def test_final_selection_matches_historical_window_arithmetic(dtype, full, factor, checkpointing):
    actual, _ = build(dtype, full, "final", factor, checkpointing)
    old, _ = build(dtype, full, "final", factor, checkpointing, legacy=True)
    for _ in schedule():
        assert tree_hash(update(actual)) == tree_hash(update(old))
        assert state(actual.inner) == state(old.inner)


@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("failure", (*CORRUPTIONS, "selection", "guard", "typed_policy"))
def test_rehashed_bad_restore_never_publishes(full, failure):
    source, _ = build(torch.bfloat16, full)
    update(source)
    payload = source.payload(META)
    if failure == "selection":
        payload["policy"]["selection_policy"]["interaction_query"] = "final"
    elif failure == "guard":
        payload["policy"]["reader_guard"]["parameter_partitions"]["writer"].pop()
    elif failure == "typed_policy":
        payload["policy"]["eos_weight"] = False
    else:
        corrupt_outer(payload, failure, full)
    target, bank = build(torch.bfloat16, full)
    before = tree_hash(target.payload(META)), versions(target.inner), tree_hash(rng_state())
    key, saved_hash = target.binding.readout._execution_key(), tree_hash(payload)
    with pytest.raises(ValueError):
        restore(target, payload, bank=bank, receipt="0" * 64 if failure == "receipt" else None)
    assert (tree_hash(target.payload(META)), versions(target.inner),
            tree_hash(rng_state())) == before
    assert target.binding.readout._execution_key() == key and tree_hash(payload) == saved_hash
    update(target)


@pytest.mark.parametrize("mismatch", ["selection", "schedule", "bank", "no_bank", "eos", "run"])
def test_independent_external_contract_required(mismatch):
    source, _ = build()
    payload = source.payload(META)
    target, bank = build()
    args = {"bank": bank}
    if mismatch == "selection":
        args["selection"] = policy("final")
    elif mismatch == "schedule":
        args["windows"] = tuple(reversed(schedule()))
    elif mismatch == "bank":
        args["bank"] = bank._replace(split_manifest_sha256="7" * 64)
    elif mismatch == "no_bank":
        args["bank"] = None
    elif mismatch == "eos":
        args["eos_weight"] = 0.25
    else:
        args["contract"] = target.base_run_contract
        args["contract"]["objective"]["terms"]["donor_margin"] += 1
    before = tree_hash(target.payload(META)), versions(target.inner), tree_hash(rng_state())
    with pytest.raises(ValueError):
        restore(target, payload, **args)
    assert (tree_hash(target.payload(META)), versions(target.inner),
            tree_hash(rng_state())) == before


def test_partial_order_bypass_and_exclusive_checkpoint(tmp_path):
    learner, _ = build()
    learner.begin_window()
    with pytest.raises(ValueError):
        learner.step()
    with pytest.raises(ValueError):
        learner.backward_pair("w1-q1", **pair_kwargs(learner))
    learner.backward_pair("w1-q0", **pair_kwargs(learner))
    for operation in (lambda: learner.step(), lambda: learner.save(tmp_path / "bad.pt", META),
                      lambda: learner.backward_pair("w1-q0", **pair_kwargs(learner))):
        with pytest.raises(ValueError):
            operation()
    assert not (tmp_path / "bad.pt").exists()
    learner.inner.cursor += 1
    with pytest.raises(ValueError):
        learner.backward_pair("w1-q1", **pair_kwargs(learner))


@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("with_bank", [False, True])
def test_step_zero_snapshot_and_accepted_payload_independence(full, with_bank):
    source, bank = build(full=full, with_bank=with_bank)
    payload = source.payload(META)
    target, fresh_bank = build(full=full, with_bank=with_bank)
    result = restore(target, payload, bank=fresh_bank)
    assert tree_hash(result.payload(META)) == tree_hash(payload)
    before = tree_hash(result.payload(META)), tree_hash(source.payload(META))
    mutate_tensors(payload)
    payload["policy"]["selection_policy"]["interaction_query"] = "final"
    payload["schedule"][0]["occurrences"][0][0] = "unowned"
    if with_bank:
        payload["reference_bank"]["rows"][0]["logits"][0] = 99.0
    assert (tree_hash(result.payload(META)), tree_hash(source.payload(META))) == before
    assert fresh_bank == bank


@pytest.mark.parametrize("failure", ["schedule", "policy", "bank", "guard", "query", "run"])
def test_live_mutation_rejected_before_window_allocation(failure):
    learner, _ = build()
    if failure == "schedule":
        learner._schedule = tuple(reversed(schedule()))
    elif failure == "policy":
        learner._policy["eos_weight"] = 1.0
    elif failure == "bank":
        learner._bank = None
    elif failure == "guard":
        learner._guard = None
    elif failure == "query":
        learner.pipeline.mode = "final"
    else:
        learner._base_contract["data"] = "changed"
    before = versions(learner.inner), tree_hash(rng_state())
    with pytest.raises(ValueError):
        learner.begin_window()
    assert learner.inner.window is None
    assert (versions(learner.inner), tree_hash(rng_state())) == before


def test_historical_owner_keeps_selection_rejected():
    source, _ = build()
    with pytest.raises(ValueError):
        V18WindowLearner(source.binding, source.bridge, full_update=True,
                         optimizer_config=OPT, run_contract=source.base_run_contract,
                         schedule=schedule())
