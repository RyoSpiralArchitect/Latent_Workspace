"""Retained snapshots, non-mutating rejection and unchanged next-update math."""

import copy

import pytest
import test_adapter_native_learner as previous
import torch

from latent_workspace_ft_v10.adapter_native_learner import AdapterNativeLearner
from latent_workspace_ft_v10.adapter_native_learner_v2 import AdapterNativeLearnerV2, snapshot
from latent_workspace_ft_v10.training_binding import MistralTrainingBinding
from latent_workspace_ft_v10.v15_native_learner import rng_state, tree_hash


@pytest.fixture(autouse=True)
def v2_owner(monkeypatch):
    monkeypatch.setattr(previous, "AdapterNativeLearner", AdapterNativeLearnerV2)
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("checkpointing", [False, True])
def test_v2_matched_two_window_updates(dtype, full, checkpointing):
    previous.test_matched_windows_equal_legacy_base_bridge_master_and_optimizer(
        dtype, full, checkpointing
    )


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("checkpointing", [False, True])
def test_v2_serialized_next_update_and_rng(tmp_path, dtype, full, checkpointing):
    previous.test_saved_next_update_exact_including_all_owned_state_and_rng(
        tmp_path, dtype, full, checkpointing
    )


@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_retained_snapshot_survives_owner_update_and_metadata_edit(full, dtype):
    learner = previous.new_owner(dtype, full)
    previous.update(learner)
    metadata = {**previous.META, "nested": [{"values": [1, 2]}]}
    saved = learner.payload(metadata)
    before = tree_hash(saved)
    previous.update(learner)
    metadata["nested"][0]["values"].append(3)
    assert tree_hash(saved) == before
    fresh = previous.new_owner(dtype, full)
    resumed = AdapterNativeLearnerV2.restore(
        fresh.binding,
        fresh.bridge,
        saved,
        expected_metadata=saved["metadata"],
        expected_run_contract=learner.run_contract,
        expected_state_sha256=before,
    )
    previous.update(resumed)
    assert tree_hash(resumed.base.state_dict()) == tree_hash(learner.base.state_dict())
    assert tree_hash(resumed.bridge.state_dict()) == tree_hash(learner.bridge.state_dict())
    assert tree_hash(saved) == before


def mutate_tensors(value):
    if isinstance(value, torch.Tensor):
        value.zero_()
    elif isinstance(value, dict):
        for part in value.values():
            mutate_tensors(part)
    elif isinstance(value, (tuple, list)):
        for part in value:
            mutate_tensors(part)


@pytest.mark.parametrize("full", [False, True])
def test_snapshot_mutation_cannot_change_any_owner_state_or_caller_metadata(full):
    learner = previous.new_owner(full=full)
    previous.update(learner)
    metadata = {"nested": [{"tensor": torch.ones(2), "names": ["original"]}]}
    caller_before = tree_hash(metadata)
    saved = learner.payload(metadata)
    owner_before = tree_hash(learner.payload(metadata))
    mutate_tensors(saved)
    saved["metadata"]["nested"][0]["names"].append("snapshot-only")
    saved["reader"]["cap"] = 999
    saved["optimizer_config"]["bridge_lr"] = 0
    saved["base_aliases"].clear()
    saved["execution"].clear()
    saved["run_contract"].clear()
    assert tree_hash(metadata) == caller_before
    assert tree_hash(learner.payload(metadata)) == owner_before


FAILURES = [
    "receipt",
    "old_format",
    "metadata",
    "execution",
    "reader",
    "run_contract",
    "base_aliases",
    "native_schema",
    "boundary",
    "completed_steps",
    "reference_role",
    "current_base_sha",
    "buffer",
    "bridge_keys",
    "bridge_shape",
    "bridge_dtype",
    "nonfinite",
    "bridge_policy",
    "bridge_ids",
    "bridge_coverage",
    "bridge_moment",
    "bridge_step",
    "bridge_negative_variance",
    "base_policy",
    "base_masters",
    "rng_keys",
    "rng_python",
    "rng_numpy",
    "rng_cpu",
    "rng_cuda",
]


def corrupt(payload, failure, full):
    if failure == "old_format":
        payload["format"] = "v15-adapter-native-resume-v1"
    elif failure in (
        "metadata",
        "execution",
        "reader",
        "run_contract",
        "base_aliases",
        "native_schema",
    ):
        payload[failure] = {}
    elif failure == "boundary":
        payload[failure] = -1
    elif failure == "completed_steps":
        payload[failure] = True
    elif failure == "reference_role":
        payload["preservation_reference"] = "updated_theta"
    elif failure == "current_base_sha":
        payload["current_base_sha256"] = "f" * 64
    elif failure == "buffer":
        next(iter(payload["all_buffers"].values())).add_(1)
    elif failure == "bridge_keys":
        payload["bridge"].pop(next(iter(payload["bridge"])))
    elif failure in ("bridge_shape", "bridge_dtype", "nonfinite"):
        key = next(iter(payload["bridge"]))
        tensor = payload["bridge"][key]
        if failure == "bridge_shape":
            payload["bridge"][key] = tensor.flatten()[:1]
        elif failure == "bridge_dtype":
            payload["bridge"][key] = tensor.double()
        else:
            tensor.fill_(float("nan"))
    elif failure == "bridge_policy":
        payload["bridge_optimizer"]["param_groups"][0]["betas"] = (0.8, 0.9)
    elif failure == "bridge_ids":
        payload["bridge_optimizer"]["param_groups"][0]["params"].reverse()
    elif failure == "bridge_coverage":
        payload["bridge_optimizer"]["state"].pop(0)
    elif failure == "bridge_moment":
        payload["bridge_optimizer"]["state"][0]["exp_avg"] = torch.ones(1, device="cpu")
    elif failure == "bridge_step":
        payload["bridge_optimizer"]["state"][0]["step"].add_(1)
    elif failure == "bridge_negative_variance":
        payload["bridge_optimizer"]["state"][0]["exp_avg_sq"].fill_(-1)
    elif failure == "base_policy":
        if full:
            payload["base_optimizer"]["param_groups"][0]["relative_step"] = True
        else:
            payload["base_optimizer"] = {}
    elif failure == "base_masters":
        if full:
            payload["base_masters"].pop(next(iter(payload["base_masters"])))
        else:
            payload["base_masters"]["unexpected"] = torch.zeros(1, device="cpu")
    elif failure == "rng_keys":
        payload["rng"].pop("torch_cpu")
    elif failure == "rng_python":
        payload["rng"]["python"] = (0, (), None)
    elif failure == "rng_numpy":
        payload["rng"]["numpy"][1] = [-1] * 624
    elif failure == "rng_cpu":
        payload["rng"]["torch_cpu"] = torch.zeros(1, dtype=torch.uint8, device="cpu")
    elif failure == "rng_cuda":
        payload["rng"]["torch_cuda"].append(torch.zeros(1, dtype=torch.uint8, device="cpu"))


def versions(learner):
    tensors = [
        *learner.base.parameters(),
        *learner.base.buffers(),
        *learner.bridge.parameters(),
        *learner.bridge.buffers(),
        *learner.masters.values(),
    ]
    return [(id(p), p.data_ptr(), p._version, p.requires_grad, p.grad) for p in tensors]


@pytest.mark.parametrize("failure", FAILURES)
@pytest.mark.parametrize("full", [False, True])
def test_rejected_restore_leaves_values_versions_pointers_guards_rng_unchanged(failure, full):
    source = previous.new_owner(torch.bfloat16, full)
    previous.update(source)
    payload = source.payload(previous.META)
    corrupt(payload, failure, full)
    # Nonfinite input is rejected even if the external receipt matches the bytes.
    receipt = "0" * 64 if failure == "receipt" else tree_hash(payload)
    target = previous.new_owner(torch.bfloat16, full)
    before = tree_hash(target.payload(previous.META))
    payload_before = tree_hash(payload)
    version_before = versions(target)
    guard_before = target.binding.readout._execution_key()
    rng_before = tree_hash(rng_state())
    with pytest.raises(ValueError):
        AdapterNativeLearnerV2.restore(
            target.binding,
            target.bridge,
            payload,
            expected_metadata=previous.META,
            expected_run_contract=source.run_contract,
            expected_state_sha256=receipt,
        )
    assert tree_hash(target.payload(previous.META)) == before
    assert versions(target) == version_before
    assert target.binding.readout._execution_key() == guard_before
    assert tree_hash(rng_state()) == rng_before
    assert tree_hash(payload) == payload_before
    # Still usable after rejection, without rebuilding the binding/guards.
    previous.update(target)


@pytest.mark.parametrize("full", [False, True])
def test_step_zero_payload_restores_without_inventing_optimizer_state(full):
    source, target = previous.new_owner(full=full), previous.new_owner(full=full)
    payload = source.payload(previous.META)
    restored = AdapterNativeLearnerV2.restore(
        target.binding,
        target.bridge,
        payload,
        expected_metadata=previous.META,
        expected_run_contract=source.run_contract,
        expected_state_sha256=tree_hash(payload),
    )
    assert tree_hash(restored.payload(previous.META)) == tree_hash(payload)


def test_snapshot_detaches_nonleaf_metadata_and_deep_copies_containers():
    leaf = torch.ones(2, requires_grad=True)
    source = {"list": [leaf * 2], "tuple": ({"nested": [1]},)}
    saved = snapshot(source)
    assert not saved["list"][0].requires_grad
    saved["list"][0].zero_()
    saved["tuple"][0]["nested"].append(2)
    assert torch.equal(source["list"][0], leaf * 2)
    assert source["tuple"][0]["nested"] == [1]
    assert copy.deepcopy(saved)["tuple"] == saved["tuple"]


def test_historical_snapshot_negative_control_detects_original_alias(monkeypatch):
    monkeypatch.setattr(previous, "AdapterNativeLearner", AdapterNativeLearner)
    source = previous.new_owner()
    previous.update(source)
    saved = source.payload(previous.META)
    before = tree_hash(saved)
    previous.update(source)
    assert tree_hash(saved) != before


def test_historical_restore_negative_control_detects_original_target_mutation(monkeypatch):
    monkeypatch.setattr(previous, "AdapterNativeLearner", AdapterNativeLearner)
    source, target = previous.new_owner(), previous.new_owner()
    previous.update(source)
    saved = snapshot(source.payload(previous.META))
    corrupt(saved, "bridge_policy", True)
    before = tree_hash(target.base.state_dict()), tree_hash(target.bridge.state_dict())
    with pytest.raises(ValueError):
        AdapterNativeLearner.restore(
            target.binding,
            target.bridge,
            saved,
            expected_metadata=previous.META,
            expected_run_contract=source.run_contract,
            expected_state_sha256=tree_hash(saved),
        )
    after = tree_hash(target.base.state_dict()), tree_hash(target.bridge.state_dict())
    assert after != before


def test_persistent_and_nonpersistent_buffers_are_snapshot_owned():
    original = previous.owner()
    original.base.register_buffer("persistent_test_buffer", torch.tensor([1.0, 2.0]))
    original.base.register_buffer("volatile_test_buffer", torch.tensor([3.0]), persistent=False)
    binding = MistralTrainingBinding(original.base, 1)
    contract = {"original_base_sha256": tree_hash(original.base.state_dict()), "objective": "tiny"}
    learner = AdapterNativeLearnerV2(
        binding,
        original.bridge,
        full_update=True,
        optimizer_config=previous.OPT,
        run_contract=contract,
    )
    saved = learner.payload(previous.META)
    before = tree_hash(saved)
    original.base.persistent_test_buffer.add_(1)
    original.base.volatile_test_buffer.add_(1)
    assert tree_hash(saved) == before


@pytest.mark.parametrize("failure", ["shape", "dtype", "step", "negative", "keys"])
def test_base_optimizer_malformed_state_rejected_before_target_write(failure):
    source, target = previous.new_owner(), previous.new_owner()
    previous.update(source)
    saved = source.payload(previous.META)
    state = saved["base_optimizer"]["state"][0]
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
    before, version_before = tree_hash(target.payload(previous.META)), versions(target)
    with pytest.raises(ValueError):
        AdapterNativeLearnerV2.restore(
            target.binding,
            target.bridge,
            saved,
            expected_metadata=previous.META,
            expected_run_contract=source.run_contract,
            expected_state_sha256=tree_hash(saved),
        )
    assert tree_hash(target.payload(previous.META)) == before
    assert versions(target) == version_before
