"""V16 reader-state owner; unchanged v15 complete-window/optimizer arithmetic.

The v1 constructor and v2 restore preflight are deliberately specialized here,
additively, because their historical source seals and strict legacy whitelist
must not be rewritten. Inherited update, payload snapshot and restore publication
methods remain byte-for-byte the qualified implementations. The only new state
is the explicit reader contract; no new losses or head arithmetic are introduced.
"""

from __future__ import annotations

import copy
import math

import torch
from torch import nn
from transformers.optimization import Adafactor

from .adapted_workspace import AdaptedWorkspacePipeline
from .adapter_native_learner_v2 import (
    AdapterNativeLearnerV2,
    _ProjectedNativeState,
    snapshot,
    tensor_schema,
    validate_optimizer,
    validate_rng,
)
from .slot_contrast_state import SlotContrastStateBinding, storage_keys
from .v15_native_learner import V15NativeLearner, finite_tree, require, tree_hash

FORMAT = "v16-slot-contrast-native-resume-v1"
PAYLOAD_KEYS = {
    "format",
    "metadata",
    "full_update",
    "reader",
    "optimizer_config",
    "boundary",
    "completed_steps",
    "base_aliases",
    "native_schema",
    "native_buffers",
    "base_masters",
    "bridge",
    "base_optimizer",
    "bridge_optimizer",
    "rng",
    "run_contract",
    "execution",
    "all_buffers",
    "current_base_sha256",
    "preservation_reference",
}


class SlotContrastNativeLearner(AdapterNativeLearnerV2):
    """Owned writer/common/interaction state with fail-before-write restoration."""

    def __init__(
        self, binding, bridge, *, full_update, optimizer_config, run_contract, master_state=None
    ):
        require(type(full_update) is bool, "Explicit update scope")
        self.binding, self.base, self.bridge = binding, binding.base, bridge
        self.full_update, self.boundary = full_update, binding.boundary
        self.config = copy.deepcopy(optimizer_config)
        self._config_hash = tree_hash(self.config)
        require(
            set(self.config)
            >= {
                "bridge_lr",
                "base_lr",
                "max_grad_norm_per_family",
                "bridge_weight_decay",
                "base_weight_decay",
            },
            "Complete optimizer settings",
        )
        for key in ("bridge_lr", "base_lr", "max_grad_norm_per_family"):
            require(
                type(self.config[key]) in (int, float)
                and math.isfinite(self.config[key])
                and self.config[key] > 0,
                "Positive finite optimizer settings",
            )
        for key in ("bridge_weight_decay", "base_weight_decay"):
            require(
                type(self.config[key]) in (int, float)
                and math.isfinite(self.config[key])
                and self.config[key] >= 0,
                "Finite weight decay",
            )
        require(
            isinstance(run_contract, dict)
            and run_contract.get("objective")
            and run_contract.get("original_base_sha256") == tree_hash(self.base.state_dict()),
            "Initialize from the exact pinned original base and explicit objective",
        )
        self.run_contract = copy.deepcopy(run_contract)
        self._run_hash = tree_hash(self.run_contract)
        binding.validate()
        self.execution = copy.deepcopy(binding.describe())
        self._execution_hash = tree_hash(self.execution)
        self.reader_binding = SlotContrastStateBinding(bridge)
        self.reader = self.reader_binding.describe()
        self._reader_hash = tree_hash(self.reader)
        self.base_named, self.bridge_named = (
            list(self.base.named_parameters()),
            list(bridge.named_parameters()),
        )
        self.schemas = {
            id(p): (tuple(p.shape), p.dtype, p.device)
            for _, p in self.base_named + self.bridge_named
        }
        require(self.base_named and self.bridge_named, "Both parameter families required")
        require(
            all(p.requires_grad == full_update for _, p in self.base_named), "Base update ownership"
        )
        require(
            all(p.requires_grad and p.dtype == torch.float32 for _, p in self.bridge_named),
            "FP32 trainable bridge required",
        )
        require(
            {p.device for _, p in self.bridge_named} == {p.device for _, p in self.base_named}
            and len({p.device for _, p in self.base_named}) == 1,
            "Single shared native/reader device required",
        )
        require(
            not ({id(p) for _, p in self.base_named} & {id(p) for _, p in self.bridge_named}),
            "Cross-owned parameter",
        )
        canonical = {id(p): n for n, p in self.base_named}
        self.aliases = {
            n: canonical[id(p)] for n, p in self.base.named_parameters(remove_duplicate=False)
        }
        self.buffer_names = sorted(set(self.base.state_dict()) - set(self.aliases))
        self.pipeline = AdaptedWorkspacePipeline(bridge, binding.readout, "final")
        self.named = [(f"base.{n}", p) for n, p in self.base_named] if full_update else []
        self.named += [(f"bridge.{n}", p) for n, p in self.bridge_named]
        require(len({id(p) for _, p in self.named}) == len(self.named), "Duplicate parameter")
        self.masters = {}
        if full_update:
            if master_state is not None:
                require(set(master_state) == {n for n, _ in self.base_named}, "Master keys")
            for name, parameter in self.base_named:
                value = (
                    parameter.detach().to(device="cpu", dtype=torch.float32, copy=True)
                    if master_state is None
                    else master_state[name].detach().clone()
                )
                require(
                    value.device.type == "cpu"
                    and value.dtype == torch.float32
                    and value.shape == parameter.shape
                    and bool(torch.isfinite(value).all()),
                    "FP32 master schema",
                )
                self.masters[name] = nn.Parameter(value, requires_grad=True)
        else:
            require(master_state is None, "Frozen owner cannot import base masters")
        self.bridge_optimizer = torch.optim.AdamW(
            [p for _, p in self.bridge_named],
            lr=self.config["bridge_lr"],
            weight_decay=self.config["bridge_weight_decay"],
        )
        self.base_optimizer = (
            Adafactor(
                list(self.masters.values()),
                lr=self.config["base_lr"],
                eps=(1e-30, 1e-3),
                clip_threshold=1.0,
                decay_rate=-0.8,
                beta1=None,
                weight_decay=self.config["base_weight_decay"],
                scale_parameter=False,
                relative_step=False,
                warmup_init=False,
            )
            if full_update
            else None
        )
        self.completed_steps, self.window, self.keys, self.cursor = 0, None, (), 0
        self._bridge_policy = self._optimizer_policy(self.bridge_optimizer)
        self._base_policy = self._optimizer_policy(self.base_optimizer)
        self._validate_ownership()

    def _validate_ownership(self):
        V15NativeLearner._validate_ownership(self)
        require(self.reader_binding.bridge is self.bridge, "Reader binding ownership changed")
        require(
            not (
                set(storage_keys(self.base.parameters()))
                & set(storage_keys(self.bridge.parameters()))
            ),
            "Cross-owned parameter storage",
        )
        require(
            not self.binding.readout.objective_active, "Active objective cannot change owner state"
        )
        require(tree_hash(self.config) == self._config_hash, "Optimizer configuration changed")
        require(tree_hash(self.reader) == self._reader_hash, "Reader descriptor changed")
        require(tree_hash(self.execution) == self._execution_hash, "Execution descriptor changed")
        self.binding.validate()
        require(
            self.binding.base is self.base
            and self.pipeline.adapter is self.binding.readout
            and self.pipeline.bridge is self.bridge
            and self.pipeline._reader.bridge is self.bridge
            and self.pipeline._reader.mode == "final",
            "Pipeline ownership changed",
        )
        require(
            tree_hash(self.binding.describe()) == self._execution_hash,
            "Native execution contract changed",
        )
        require(tree_hash(self.run_contract) == self._run_hash, "Run contract changed")
        require(self.reader_binding.describe() == self.reader, "Reader semantics changed")
        require(
            self._optimizer_policy(self.bridge_optimizer) == self._bridge_policy
            and self._optimizer_policy(self.base_optimizer) == self._base_policy,
            "Optimizer policy changed",
        )

    def payload(self, metadata):
        value = super().payload(metadata)
        value["format"] = FORMAT
        return value

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
        require(
            payload["reader"] == SlotContrastStateBinding(bridge).describe(),
            "Reader semantics mismatch",
        )
        require(set(payload) == PAYLOAD_KEYS, "Checkpoint field ownership mismatch")
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
