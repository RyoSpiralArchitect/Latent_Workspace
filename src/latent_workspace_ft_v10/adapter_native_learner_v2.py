"""Snapshot-owned checkpoint successor; update/graph arithmetic is unchanged.

The v1 source remains sealed historical evidence. V2 rejects incompatible
checkpoints before writing any target tensor or process RNG. Preparation owns
CPU masters and optimizer state, but does not duplicate the native GPU model.
Publication assumes exclusive access and a functioning device: process death,
device failure and concurrent/out-of-band mutation are not transactions.
"""

from __future__ import annotations

import copy
import random

import numpy as np
import torch

from .adapter_native_learner import AdapterNativeLearner
from .v15_native_learner import finite_tree, reader_descriptor, require, restore_rng, tree_hash

FORMAT = "v15-adapter-native-resume-v2"


def snapshot(value):
    """Independent, detached CPU tensors AND independent metadata containers."""
    if isinstance(value, torch.Tensor):
        return value.detach().to(device="cpu", copy=True)
    if isinstance(value, dict):
        return {copy.deepcopy(k): snapshot(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return tuple(snapshot(v) for v in value)
    if isinstance(value, list):
        return [snapshot(v) for v in value]
    return copy.deepcopy(value)


def tensor_schema(value, shape, dtype):
    require(
        isinstance(value, torch.Tensor)
        and value.device.type == "cpu"
        and value.layout == torch.strided
        and value.shape == shape
        and value.dtype == dtype,
        "Checkpoint tensor schema mismatch",
    )


def validate_rng(state):
    """Validate on private generators; never set the process generators here."""
    require(set(state) == {"python", "numpy", "torch_cpu", "torch_cuda"}, "RNG keys")
    random.Random(0).setstate(state["python"])
    numpy = state["numpy"]
    require(isinstance(numpy, list) and len(numpy) == 5, "NumPy RNG schema")
    require(
        numpy[0] == "MT19937"
        and isinstance(numpy[1], list)
        and len(numpy[1]) == 624
        and all(type(n) is int and 0 <= n < 2**32 for n in numpy[1])
        and type(numpy[2]) is int
        and 0 <= numpy[2] <= 624
        and type(numpy[3]) is int
        and numpy[3] in (0, 1),
        "NumPy RNG contents",
    )
    np.random.RandomState(0).set_state((numpy[0], np.array(numpy[1], dtype=np.uint32), *numpy[2:]))
    cpu = state["torch_cpu"]
    tensor_schema(cpu, torch.get_rng_state().shape, torch.uint8)
    torch.Generator(device="cpu").set_state(cpu)
    states = state["torch_cuda"]
    count = torch.cuda.device_count() if torch.cuda.is_initialized() else 0
    require(isinstance(states, list) and len(states) == count, "CUDA RNG device count")
    for device, saved in enumerate(states):
        tensor_schema(saved, torch.cuda.get_rng_state(device).shape, torch.uint8)
        torch.Generator(device=f"cuda:{device}").set_state(saved)


def validate_optimizer(saved, optimizer, steps, *, base):
    """Bind policy, ordered parameter IDs and every moment before loading."""
    if optimizer is None:
        require(saved is None, "Frozen checkpoint has base optimizer")
        return
    require(set(saved) == {"state", "param_groups"}, "Optimizer keys")
    expected = optimizer.state_dict()
    require(saved["param_groups"] == expected["param_groups"], "Optimizer policy/IDs mismatch")
    params = [p for group in optimizer.param_groups for p in group["params"]]
    ids = [n for group in expected["param_groups"] for n in group["params"]]
    require(set(saved["state"]) == (set(ids) if steps else set()), "Optimizer state coverage")
    for index, parameter in zip(ids, params, strict=True):
        if not steps:
            continue
        state = saved["state"][index]
        if base:
            require(type(state["step"]) is int and state["step"] == steps, "Base step mismatch")
            shapes = {"RMS": torch.Size([])}
            if parameter.ndim >= 2:
                shapes.update(
                    exp_avg_sq_row=parameter.shape[:-1],
                    exp_avg_sq_col=parameter.shape[:-2] + parameter.shape[-1:],
                )
            else:
                shapes["exp_avg_sq"] = parameter.shape
        else:
            tensor_schema(state["step"], torch.Size([]), torch.float32)
            require(state["step"].item() == steps, "Bridge step mismatch")
            shapes = {"exp_avg": parameter.shape, "exp_avg_sq": parameter.shape}
        require(set(state) == {"step", *shapes}, "Optimizer moment keys")
        for name, shape in shapes.items():
            tensor_schema(state[name], shape, torch.float32)
            if name != "exp_avg":
                require(bool((state[name] >= 0).all()), "Negative second moment/RMS")


class _ProjectedNativeState(dict):
    """Hash the proposed native state one CPU cast at a time, not a second model."""

    def __init__(self, learner):
        super().__init__(learner.base.state_dict())
        self.learner = learner

    def __getitem__(self, name):
        value = super().__getitem__(name)
        if self.learner.full_update and name in self.learner.aliases:
            return self.learner.masters[self.learner.aliases[name]].detach().to(value.dtype)
        return value


class AdapterNativeLearnerV2(AdapterNativeLearner):
    """V1 training algorithm with independent snapshots and preflighted restore."""

    def payload(self, metadata):
        value = snapshot(super().payload(metadata))
        value["format"] = FORMAT
        return value

    @classmethod
    def restore(
        cls,
        binding,
        bridge,
        payload,
        *,
        expected_metadata,
        expected_run_contract,
        expected_state_sha256,
    ):
        # Preparation is deliberately the only validation phase. No load into
        # bridge/base and no global set_rng_state occurs on these error paths.
        try:
            learner = cls._prepare_restore(
                binding,
                bridge,
                payload,
                expected_metadata=expected_metadata,
                expected_run_contract=expected_run_contract,
                expected_state_sha256=expected_state_sha256,
            )
        except (KeyError, TypeError, IndexError, RuntimeError, OverflowError) as exc:
            raise ValueError(f"Invalid checkpoint: {exc}") from exc

        # The caller grants exclusive target/RNG ownership for publication.
        # Direct copies avoid arbitrary load_state_dict callbacks after preflight.
        with torch.no_grad():
            for name, target in bridge.state_dict(keep_vars=True).items():
                target.copy_(payload["bridge"][name], non_blocking=False)
            if learner.full_update:
                for name, native in learner.base_named:
                    native.copy_(
                        learner.masters[name].detach().to(native.dtype), non_blocking=False
                    )
        restore_rng(payload["rng"])
        return learner

    @classmethod
    def _prepare_restore(
        cls,
        binding,
        bridge,
        payload,
        *,
        expected_metadata,
        expected_run_contract,
        expected_state_sha256,
    ):
        require(tree_hash(payload) == expected_state_sha256, "Checkpoint content receipt mismatch")
        require(
            payload["format"] == FORMAT
            and payload["metadata"] == expected_metadata
            and payload["run_contract"] == expected_run_contract,
            "Resume provenance mismatch",
        )
        require(payload["execution"] == binding.describe(), "Resume execution policy mismatch")
        require(payload["reader"] == reader_descriptor(bridge), "Reader semantics mismatch")
        require(finite_tree(payload), "Nonfinite checkpoint")
        require(
            payload["native_schema"]
            == {n: [list(p.shape), str(p.dtype)] for n, p in binding.base.named_parameters()},
            "Native schema mismatch",
        )
        require(
            all(p.grad is None for p in (*binding.base.parameters(), *bridge.parameters())),
            "Restore targets have live gradients",
        )
        buffers = dict(binding.base.named_buffers(remove_duplicate=False))
        require(set(buffers) == set(payload["all_buffers"]), "Buffer ownership mismatch")
        for name, buffer in buffers.items():
            saved = payload["all_buffers"][name]
            tensor_schema(saved, buffer.shape, buffer.dtype)
            require(torch.equal(saved, buffer.detach().cpu()), "Native buffer content mismatch")
        current_bridge = bridge.state_dict()
        require(set(current_bridge) == set(payload["bridge"]), "Bridge keys mismatch")
        for name, target in current_bridge.items():
            tensor_schema(payload["bridge"][name], target.shape, target.dtype)
        steps = payload["completed_steps"]
        require(type(steps) is int and steps >= 0, "Invalid completed step")
        require(
            payload["preservation_reference"] == "pinned_identity_only_no_new_preservation_loss",
            "Unknown reference role",
        )
        if not payload["full_update"]:
            require(not payload["base_masters"], "Frozen checkpoint has base masters")
        learner = cls(
            binding,
            bridge,
            full_update=payload["full_update"],
            optimizer_config=payload["optimizer_config"],
            run_contract=expected_run_contract,
            master_state=payload["base_masters"] if payload["full_update"] else None,
        )
        require(
            payload["base_aliases"] == learner.aliases
            and set(payload["native_buffers"]) == set(learner.buffer_names)
            and payload["boundary"] == learner.boundary,
            "Alias/boundary/buffer mismatch",
        )
        for name in learner.buffer_names:
            tensor_schema(payload["native_buffers"][name], buffers[name].shape, buffers[name].dtype)
            require(
                torch.equal(payload["native_buffers"][name], buffers[name].cpu()),
                "Persistent buffer representations disagree",
            )
        require(
            tree_hash(_ProjectedNativeState(learner)) == payload["current_base_sha256"],
            "Restored current-base content mismatch",
        )
        validate_optimizer(payload["bridge_optimizer"], learner.bridge_optimizer, steps, base=False)
        validate_optimizer(payload["base_optimizer"], learner.base_optimizer, steps, base=True)
        validate_rng(payload["rng"])
        # Loading only private optimizer dictionaries does not update parameters.
        learner.bridge_optimizer.load_state_dict(snapshot(payload["bridge_optimizer"]))
        if learner.base_optimizer is not None:
            learner.base_optimizer.load_state_dict(snapshot(payload["base_optimizer"]))
        learner.completed_steps = steps
        learner._validate_ownership()
        return learner
