"""Tiny local matched updates and adapter-owned exact resume; no FT benchmark."""

import copy
import random

import numpy as np
import pytest
import torch
from test_v15_native_learner import (
    CONTRACT,
    META,
    OPT,
    SPAN,
    OwnedStore,
    objective,
    owner,
)

from latent_workspace_ft_v10.adapted_pair_objective import adapted_pair_objective
from latent_workspace_ft_v10.adapter_native_learner import AdapterNativeLearner
from latent_workspace_ft_v10.training_binding import MistralTrainingBinding
from latent_workspace_ft_v10.v15_native_learner import tree_hash


@pytest.fixture(autouse=True)
def threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(previous)


def new_owner(dtype=torch.float32, full=True, checkpointing=False):
    original = owner(dtype, full)
    if checkpointing:
        original.base.gradient_checkpointing_enable(
            gradient_checkpointing_kwargs={"use_reentrant": False}
        )
    binding = MistralTrainingBinding(original.base, 1)
    contract = {
        "original_base_sha256": tree_hash(original.base.state_dict()),
        "objective": {"terms": CONTRACT, "eos_weight": 0.0, "query_mode": "final"},
        "data": "tiny_only_not_a_real_training_window",
    }
    return AdapterNativeLearner(
        binding, original.bridge, full_update=full, optimizer_config=OPT, run_contract=contract
    )


def new_objective(learner, query):
    store = OwnedStore(learner)
    return adapted_pair_objective(
        learner.pipeline,
        lambda side: store.write(learner.bridge, 0, side),
        prefix_ids=SPAN.prefix_ids,
        span=SPAN,
        candidate_ids=(6, 7),
        labels=[store.records[0]["answers"][s][query] for s in (0, 1)],
        contract=CONTRACT,
    )[0]


def update(learner, *, legacy=False):
    learner.begin_window(("affected", "unaffected"))
    for key, query in (("affected", 0), ("unaffected", 2)):
        loss = objective(learner, query) if legacy else new_objective(learner, query)
        learner.backward_pair(key, loss)
    return learner.step()


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("checkpointing", [False, True])
def test_matched_windows_equal_legacy_base_bridge_master_and_optimizer(dtype, full, checkpointing):
    legacy, migrated = owner(dtype, full), new_owner(dtype, full, checkpointing)
    if checkpointing:
        legacy.base.gradient_checkpointing_enable(
            gradient_checkpointing_kwargs={"use_reentrant": False}
        )
    for _ in range(2):
        a, b = update(legacy, legacy=True), update(migrated)
        assert tree_hash(a) == tree_hash(b)
        for left, right in (
            (legacy.base.state_dict(), migrated.base.state_dict()),
            (legacy.bridge.state_dict(), migrated.bridge.state_dict()),
            (legacy.masters, migrated.masters),
            (legacy.bridge_optimizer.state_dict(), migrated.bridge_optimizer.state_dict()),
        ):
            assert tree_hash(left) == tree_hash(right)
        if full:
            assert tree_hash(legacy.base_optimizer.state_dict()) == tree_hash(
                migrated.base_optimizer.state_dict()
            )


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("checkpointing", [False, True])
def test_saved_next_update_exact_including_all_owned_state_and_rng(
    tmp_path,
    dtype,
    full,
    checkpointing,
):
    learner = new_owner(dtype, full, checkpointing)
    update(learner)
    receipt = learner.save(tmp_path / "step1.pt", META)
    payload = torch.load(tmp_path / "step1.pt", map_location="cpu", weights_only=True)
    initial_hash = tree_hash(payload)
    assert initial_hash == receipt["state_sha256"]
    update(learner)
    expected = tree_hash(learner.payload(META))
    random_after = (random.random(), np.random.rand(), torch.rand(3))
    fresh = new_owner(dtype, full, checkpointing)
    resumed = AdapterNativeLearner.restore(
        fresh.binding,
        fresh.bridge,
        payload,
        expected_metadata=META,
        expected_run_contract=learner.run_contract,
        expected_state_sha256=initial_hash,
    )
    update(resumed)
    assert tree_hash(resumed.payload(META)) == expected
    assert (random.random(), np.random.rand()) == random_after[:2]
    assert torch.equal(torch.rand(3), random_after[2])
    # Payload masters/optimizers must not secretly become the resumed mutable state.
    assert tree_hash(payload) == initial_hash
    with pytest.raises(FileExistsError):
        resumed.save(tmp_path / "step1.pt", META)


@pytest.mark.parametrize(
    "failure", ["mode", "checkpointing", "reader", "optimizer", "run", "buffer", "pipeline"]
)
def test_live_policy_mutations_fail_before_begin_window(failure):
    learner = new_owner()
    if failure == "mode":
        learner.base.eval()
    elif failure == "checkpointing":
        learner.base.gradient_checkpointing_enable(
            gradient_checkpointing_kwargs={"use_reentrant": False}
        )
    elif failure == "reader":
        learner.bridge._modulation_strength = 0.5
    elif failure == "optimizer":
        learner.bridge_optimizer.param_groups[0]["betas"] = (0.8, 0.9)
    elif failure == "run":
        learner.run_contract["objective"]["eos_weight"] = 1.0
    elif failure == "buffer":
        with torch.no_grad():
            next(learner.base.buffers()).add_(0.1)
    else:
        learner.pipeline._reader.mode = "mean_span"
    with pytest.raises(ValueError):
        learner.begin_window((0,))


@pytest.mark.parametrize(
    "failure",
    ["receipt", "metadata", "execution", "optimizer", "reference", "buffer", "original_weights"],
)
def test_resume_fails_closed_for_wrong_contract_or_state(failure):
    source = new_owner()
    update(source)
    payload = copy.deepcopy(source.payload(META))
    target = new_owner()
    if failure == "metadata":
        payload["metadata"] = {}
    elif failure == "execution":
        payload["execution"]["readout"]["graph_policy"] = "independent_forwards"
    elif failure == "optimizer":
        payload["bridge_optimizer"]["param_groups"][0]["betas"] = (0.8, 0.9)
    elif failure == "reference":
        payload["run_contract"]["original_base_sha256"] = "0" * 64
    elif failure == "buffer":
        next(iter(payload["all_buffers"].values())).add_(1)
    elif failure == "original_weights":
        with torch.no_grad():
            target.base_named[0][1].add_(0.1)
    with pytest.raises(ValueError):
        AdapterNativeLearner.restore(
            target.binding,
            target.bridge,
            payload,
            expected_metadata=META,
            expected_run_contract=source.run_contract,
            expected_state_sha256="0" * 64 if failure == "receipt" else tree_hash(payload),
        )


def test_window_boundaries_and_frozen_original_identity():
    learner = new_owner(full=False)
    learner.begin_window((0, 1))
    with pytest.raises(ValueError, match="Complete"):
        learner.step()
    learner.backward_pair(0, new_objective(learner, 0))
    with pytest.raises(ValueError, match="Checkpoint"):
        learner.payload(META)
    learner.backward_pair(1, new_objective(learner, 2))
    learner.step()
    with torch.no_grad():
        learner.base_named[0][1].add_(1)
    with pytest.raises(ValueError, match="Frozen base"):
        learner.payload(META)
