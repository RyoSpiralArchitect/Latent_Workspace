"""Tiny state-mechanics qualification, not a semantic training comparison."""

import copy
import os
import random
import types

import numpy as np
import pytest
import torch
from test_adapter_native_learner_v2 import FAILURES, corrupt, versions
from test_v15_native_learner import META, OPT, owner
from test_v15_native_runner import make_store
from transformers.optimization import Adafactor

from latent_workspace_ft_v10.adapter_native_learner_v2 import AdapterNativeLearnerV2
from latent_workspace_ft_v10.native_training_preparation import (
    prepare_native_gradient_checkpointing,
)
from latent_workspace_ft_v10.slot_contrast_learner import FORMAT, SlotContrastNativeLearner
from latent_workspace_ft_v10.slot_contrast_state import SlotContrastStateBinding
from latent_workspace_ft_v10.training_binding import MistralTrainingBinding
from latent_workspace_ft_v10.v15_native_learner import rng_state, tree_hash
from latent_workspace_ft_v10.v16_slot_contrast import SlotContrastWorkspaceBridge
from scripts import run_v16_adapter_migration as run

DEVICE = os.environ.get("LATENT_SLOT_STATE_TEST_DEVICE", "cpu")
MODES = ("slot_contrast", "raw_matched_control")


@pytest.fixture(autouse=True)
def setup():
    run.load_runtime()
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


def build(mode="slot_contrast", dtype=torch.float32, full=True, checkpointing=True):
    parts = owner(dtype, full)
    parts.base.to(DEVICE)
    bridge = SlotContrastWorkspaceBridge(parts.bridge, mode=mode).to(DEVICE)
    preparation = prepare_native_gradient_checkpointing(parts.base) if checkpointing else None
    contract = {
        "original_base_sha256": tree_hash(parts.base.state_dict()),
        "objective": run.legacy.old.validate()[0]["training"],
        "preparation": preparation,
        "data": "tiny 16-pair fixture; not a 7B or semantic qualification",
    }
    before = tree_hash(rng_state())
    learner = SlotContrastNativeLearner(
        MistralTrainingBinding(parts.base, 1),
        bridge,
        full_update=full,
        optimizer_config=OPT,
        run_contract=contract,
    )
    assert tree_hash(rng_state()) == before
    return learner


def update(learner, monkeypatch):
    return run.update_window(
        learner,
        make_store(monkeypatch, learner),
        run.legacy.old.validate()[0],
        "adapter_v2",
        lambda *a: None,
    )


def restore(target, payload, contract, receipt=None):
    return SlotContrastNativeLearner.restore(
        target.binding,
        target.bridge,
        payload,
        expected_metadata=META,
        expected_run_contract=contract,
        expected_state_sha256=receipt or tree_hash(payload),
    )


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("checkpointing", [False, True])
def test_two_windows_serialized_replay_all_owned_state_rng_and_snapshot(
    monkeypatch,
    tmp_path,
    mode,
    dtype,
    full,
    checkpointing,
):
    learner = build(mode, dtype, full, checkpointing)
    first = update(learner, monkeypatch)
    assert len(first["pairs"]) == 16
    receipt = learner.save(tmp_path / "step1.pt", META)
    payload = torch.load(tmp_path / "step1.pt", map_location="cpu", weights_only=True)
    assert receipt["format"] == FORMAT
    assert tree_hash(payload) == receipt["state_sha256"]
    retained = learner.payload(META)
    before = tree_hash(retained)
    expected = update(learner, monkeypatch)
    assert tree_hash(retained) == before
    expected_state = tree_hash(learner.payload(META))
    after = random.random(), np.random.rand(), torch.rand(3, device=DEVICE)
    fresh = build(mode, dtype, full, checkpointing)
    resumed = restore(fresh, payload, learner.run_contract, receipt["state_sha256"])
    assert tree_hash(update(resumed, monkeypatch)) == tree_hash(expected)
    assert tree_hash(resumed.payload(META)) == expected_state
    assert (random.random(), np.random.rand()) == after[:2]
    assert torch.equal(torch.rand(3, device=DEVICE), after[2])
    assert tree_hash(payload) == receipt["state_sha256"]
    with pytest.raises(FileExistsError):
        resumed.save(tmp_path / "step1.pt", META)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("full", [False, True])
def test_update_matches_independent_native_dtype_cpu_accumulation(monkeypatch, mode, dtype, full):
    actual, reference = build(mode, dtype, full), build(mode, dtype, full)
    store = make_store(monkeypatch, reference)
    gradients = {}
    for world, query in run.PAIRS:
        loss, _ = run.pair_loss(
            reference, store, world, query, run.legacy.old.validate()[0], "adapter_v2"
        )
        loss.backward()
        for name, parameter in reference.named:
            assert parameter.grad is not None
            value = parameter.grad.detach().cpu()
            if name in gradients:
                gradients[name].add_(value)
            else:
                gradients[name] = value.clone()
            parameter.grad = None
    bridge_optimizer = torch.optim.AdamW(
        reference.bridge.parameters(), lr=OPT["bridge_lr"], weight_decay=OPT["bridge_weight_decay"]
    )
    for name, parameter in reference.bridge_named:
        parameter.grad = gradients[f"bridge.{name}"].to(parameter.device)
    torch.nn.utils.clip_grad_norm_(reference.bridge.parameters(), 1, error_if_nonfinite=True)
    if full:
        masters = {
            name: torch.nn.Parameter(parameter.detach().float().cpu().clone())
            for name, parameter in reference.base_named
        }
        base_optimizer = Adafactor(
            list(masters.values()),
            lr=OPT["base_lr"],
            eps=(1e-30, 1e-3),
            clip_threshold=1.0,
            decay_rate=-0.8,
            beta1=None,
            weight_decay=0.0,
            scale_parameter=False,
            relative_step=False,
            warmup_init=False,
        )
        for name, parameter in masters.items():
            parameter.grad = gradients[f"base.{name}"].float()
        torch.nn.utils.clip_grad_norm_(list(masters.values()), 1, error_if_nonfinite=True)
        base_optimizer.step()
        with torch.no_grad():
            for name, native in reference.base_named:
                native.copy_(masters[name].to(native.dtype))
    bridge_optimizer.step()
    update(actual, monkeypatch)
    assert tree_hash(actual.base.state_dict()) == tree_hash(reference.base.state_dict())
    assert tree_hash(actual.bridge.state_dict()) == tree_hash(reference.bridge.state_dict())
    assert tree_hash(actual.bridge_optimizer.state_dict()) == tree_hash(
        bridge_optimizer.state_dict()
    )
    if full:
        assert tree_hash(actual.masters) == tree_hash(masters)
        assert tree_hash(actual.base_optimizer.state_dict()) == tree_hash(
            base_optimizer.state_dict()
        )


@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("failure", FAILURES + ["partitions", "extra_field", "v2_format"])
def test_bad_resume_cannot_mutate_target_even_with_rehashed_payload(monkeypatch, full, failure):
    source = build(full=full, dtype=torch.bfloat16)
    update(source, monkeypatch)
    payload = source.payload(META)
    corrupt(payload, failure, full)
    if failure == "partitions":
        payload["reader"]["parameter_partitions"]["interaction"] = []
    elif failure == "extra_field":
        payload["unowned_state"] = 42
    elif failure == "v2_format":
        payload["format"] = "v15-adapter-native-resume-v2"
    target = build(full=full, dtype=torch.bfloat16)
    before = tree_hash(target.payload(META)), versions(target), tree_hash(rng_state())
    saved = tree_hash(payload)
    with pytest.raises(ValueError):
        restore(target, payload, source.run_contract, "0" * 64 if failure == "receipt" else None)
    assert (tree_hash(target.payload(META)), versions(target), tree_hash(rng_state())) == before
    assert tree_hash(payload) == saved
    update(target, monkeypatch)


MUTATIONS = [
    "mode",
    "fraction",
    "cap",
    "common_strength",
    "common_cap",
    "writer_steps",
    "writer_mode",
    "norm_epsilon",
    "dropout",
    "heads",
    "training",
    "module",
    "parameter",
    "alias",
    "storage",
    "buffer",
    "nonpersistent_buffer",
    "unregistered_tensor",
    "method",
    "hook",
    "requires_grad",
]


def mutate(bridge, failure):
    if failure == "mode":
        bridge.mode = "raw_matched_control"
    elif failure == "fraction":
        bridge.interaction_fraction = 0.5
    elif failure == "cap":
        bridge.max_delta_norm = 2.0
    elif failure == "common_strength":
        bridge.common._modulation_strength = 0.5
    elif failure == "common_cap":
        bridge.common.max_delta_norm = 2.0
    elif failure == "writer_steps":
        bridge.common.writer.steps = 2
    elif failure == "writer_mode":
        bridge.common.writer.mode = "fixed_carrier"
    elif failure == "norm_epsilon":
        bridge.common.memory_norm.eps *= 10
    elif failure == "dropout":
        bridge.attention.dropout = 0.1
    elif failure == "heads":
        bridge.attention.num_heads = 1
    elif failure == "training":
        bridge.common.writer.eval()
    elif failure == "module":
        bridge.query_norm = copy.deepcopy(bridge.query_norm)
    elif failure == "parameter":
        bridge.up.weight = torch.nn.Parameter(bridge.up.weight.detach().clone())
    elif failure == "alias":
        bridge.up.weight = bridge.common.up.weight
    elif failure == "storage":
        bridge.up.weight.data = bridge.common.up.weight.data
    elif failure in ("buffer", "nonpersistent_buffer"):
        bridge.register_buffer(
            "foreign", torch.zeros(1, device=DEVICE), persistent=failure == "buffer"
        )
    elif failure == "unregistered_tensor":
        bridge.foreign_tensor = torch.zeros(1, device=DEVICE)
    elif failure == "method":
        bridge.read_delta = types.MethodType(lambda self, q, m, k: q, bridge)
    elif failure == "hook":
        bridge.attention.register_forward_hook(lambda m, a, out: out)
    elif failure == "requires_grad":
        bridge.up.weight.requires_grad_(False)


@pytest.mark.parametrize("failure", MUTATIONS)
def test_live_reader_mutation_is_rejected_at_window_boundary(failure):
    learner = build()
    mutate(learner.bridge, failure)
    before = tree_hash(rng_state())
    with pytest.raises(ValueError):
        learner.begin_window((0,))
    assert learner.window is None
    assert tree_hash(rng_state()) == before


@pytest.mark.parametrize("failure", MUTATIONS)
def test_changed_restore_target_rejected_without_mutation(failure):
    source, target = build(), build()
    payload = source.payload(META)
    mutate(target.bridge, failure)
    # A same-shaped fresh module/parameter is a valid *new* restore target.
    if failure in ("module", "parameter"):
        assert restore(target, payload, source.run_contract).completed_steps == 0
        return
    before = tree_hash(target.base.state_dict()), tree_hash(target.bridge.state_dict())
    pointers, random_state = versions(target), tree_hash(rng_state())
    with pytest.raises(ValueError):
        restore(target, payload, source.run_contract)
    assert (tree_hash(target.base.state_dict()), tree_hash(target.bridge.state_dict())) == before
    assert versions(target) == pointers
    assert tree_hash(rng_state()) == random_state


@pytest.mark.parametrize("mode", MODES)
def test_partition_ownership_initial_null_and_gradient_warmup(monkeypatch, mode):
    learner = build(mode)
    partitions = learner.reader["parameter_partitions"]
    names = [name for values in partitions.values() for name in values]
    assert len(names) == len(set(names)) == len(learner.bridge_named) == 32
    assert set(names) == set(dict(learner.bridge_named))
    assert {key: len(value) for key, value in partitions.items()} == {
        "writer": 20,
        "common_reader": 6,
        "interaction": 6,
    }
    store = make_store(monkeypatch, learner)
    loss, _ = run.pair_loss(learner, store, 0, 0, run.legacy.old.validate()[0], "adapter_v2")
    loss.backward()
    parameters = dict(learner.bridge.named_parameters())
    assert all(p.grad is not None for p in parameters.values())
    assert parameters["up.weight"].grad.count_nonzero() > 0
    assert parameters["query_projection.weight"].grad.count_nonzero() == 0
    for parameter in (*learner.base.parameters(), *learner.bridge.parameters()):
        parameter.grad = None
    update(learner, monkeypatch)
    loss, _ = run.pair_loss(learner, store, 0, 0, run.legacy.old.validate()[0], "adapter_v2")
    loss.backward()
    for names in partitions.values():
        assert all(torch.isfinite(parameters[name].grad).all() for name in names)
        assert sum(int(parameters[name].grad.count_nonzero()) for name in names) > 0
    assert parameters["query_projection.weight"].grad.count_nonzero() > 0


def test_matched_initial_state_distinct_contract_and_old_whitelist_unchanged():
    candidate, raw = build(), build("raw_matched_control")
    assert tree_hash(candidate.bridge.state_dict()) == tree_hash(raw.bridge.state_dict())
    assert candidate.reader != raw.reader
    before = tree_hash(rng_state())
    assert SlotContrastStateBinding(candidate.bridge).describe() == candidate.reader
    assert tree_hash(rng_state()) == before
    with pytest.raises(ValueError, match="Unknown reader class"):
        AdapterNativeLearnerV2(
            candidate.binding,
            candidate.bridge,
            full_update=True,
            optimizer_config=OPT,
            run_contract=candidate.run_contract,
        )
    with pytest.raises(ValueError):
        restore(raw, candidate.payload(META), candidate.run_contract)


@pytest.mark.parametrize("full", [False, True])
def test_step_zero_and_no_partial_window_checkpoint(full, monkeypatch):
    learner = build(full=full)
    payload = learner.payload(META)
    target = restore(build(full=full), payload, learner.run_contract)
    assert tree_hash(target.payload(META)) == tree_hash(payload)
    target.begin_window((0, 1))
    with pytest.raises(ValueError, match="Complete window"):
        target.step()
    with pytest.raises(ValueError, match="Checkpoint"):
        target.payload(META)


@pytest.mark.parametrize("full", [False, True])
def test_snapshot_and_caller_metadata_are_independently_owned(monkeypatch, full):
    from test_adapter_native_learner_v2 import mutate_tensors

    learner = build(full=full)
    update(learner, monkeypatch)
    metadata = {"nested": [{"tensor": torch.ones(2, device=DEVICE), "names": ["original"]}]}
    before, meta_before = tree_hash(learner.payload(metadata)), tree_hash(metadata)
    saved = learner.payload(metadata)
    mutate_tensors(saved)
    saved["reader"]["parameter_partitions"]["writer"].clear()
    saved["metadata"]["nested"][0]["names"].append("snapshot-only")
    assert tree_hash(learner.payload(metadata)) == before
    assert tree_hash(metadata) == meta_before
    saved = learner.payload(metadata)
    before = tree_hash(saved)
    metadata["nested"][0]["names"].append("caller-only")
    update(learner, monkeypatch)
    assert tree_hash(saved) == before


@pytest.mark.parametrize("failure", ["shape", "dtype", "step", "negative", "keys"])
def test_late_base_optimizer_failure_has_no_target_or_rng_effect(monkeypatch, failure):
    learner = build()
    update(learner, monkeypatch)
    payload = learner.payload(META)
    state = payload["base_optimizer"]["state"][0]
    if failure == "shape":
        state["exp_avg_sq_row"] = torch.ones(1, device="cpu")
    elif failure == "dtype":
        state["RMS"] = state["RMS"].double()
    elif failure == "step":
        state["step"] += 1
    elif failure == "negative":
        state["exp_avg_sq_row"].fill_(-1)
    else:
        state["unused_moment"] = torch.zeros(1, device="cpu")
    target = build()
    before = tree_hash(target.payload(META)), versions(target), tree_hash(rng_state())
    with pytest.raises(ValueError):
        restore(target, payload, learner.run_contract)
    assert (tree_hash(target.payload(META)), versions(target), tree_hash(rng_state())) == before


def test_update_arithmetic_and_publication_are_inherited_not_reimplemented():
    from latent_workspace_ft_v10.v15_native_learner import V15NativeLearner

    assert SlotContrastNativeLearner.step is V15NativeLearner.step
    assert SlotContrastNativeLearner.begin_window is V15NativeLearner.begin_window
    assert SlotContrastNativeLearner.save is V15NativeLearner.save
    assert SlotContrastNativeLearner.restore.__func__ is AdapterNativeLearnerV2.restore.__func__
