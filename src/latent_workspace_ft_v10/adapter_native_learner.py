"""Additive adapter-bound owner; historical optimizer math is reused verbatim.

No family attributes, normalization formula or head operation lives here. The
binding owns context extraction/readout. The parent is used only for its sealed
complete-window accumulator and optimizer/CPU-master methods, never its Mistral
constructor/prefix pipeline or old resume entry. Checkpoints use a new format.
"""

from __future__ import annotations

import copy
import math
from contextlib import nullcontext

import torch
from torch import nn
from transformers.optimization import Adafactor

from .adapted_workspace import AdaptedWorkspacePipeline
from .v15_native_learner import (
    V15NativeLearner,
    finite_tree,
    reader_descriptor,
    require,
    restore_rng,
    tree_hash,
)


class AdapterNativeLearner(V15NativeLearner):
    """Unchanged window/update algorithm, explicit model-independent binding."""

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
        self.reader = reader_descriptor(bridge)
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

    @staticmethod
    def _optimizer_policy(optimizer):
        return (
            None
            if optimizer is None
            else [
                {k: v for k, v in group.items() if k != "params"}
                for group in optimizer.param_groups
            ]
        )

    def _validate_ownership(self):
        super()._validate_ownership()
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
        require(reader_descriptor(self.bridge) == self.reader, "Reader semantics changed")
        require(
            self._optimizer_policy(self.bridge_optimizer) == self._bridge_policy
            and self._optimizer_policy(self.base_optimizer) == self._base_policy,
            "Optimizer policy changed",
        )

    def prefix(self, ids):
        raise TypeError("Adapter owner accepts tokens through pipeline; no legacy hidden prefix")

    def context(self, ids):
        with nullcontext() if self.full_update else torch.no_grad():
            return self.binding.context(tuple(ids))

    def backward_pair(self, key, loss):
        self._validate_ownership()
        require(not self.binding.readout.objective_active, "Close objective before backward")
        return super().backward_pair(key, loss)

    def payload(self, metadata):
        require(not self.binding.readout.objective_active, "Checkpoint with live objective")
        value = super().payload(metadata)
        value.update(
            format="v15-adapter-native-resume-v1",
            run_contract=copy.deepcopy(self.run_contract),
            execution=copy.deepcopy(self.execution),
            all_buffers={
                n: b.detach().cpu().clone()
                for n, b in self.base.named_buffers(remove_duplicate=False)
            },
            current_base_sha256=tree_hash(self.base.state_dict()),
            preservation_reference="pinned_identity_only_no_new_preservation_loss",
        )
        if not self.full_update:
            require(
                value["current_base_sha256"] == self.run_contract["original_base_sha256"],
                "Frozen base changed",
            )
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
        require(tree_hash(payload) == expected_state_sha256, "Checkpoint content receipt mismatch")
        require(
            payload["format"] == "v15-adapter-native-resume-v1"
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
        buffers = dict(binding.base.named_buffers(remove_duplicate=False))
        require(set(buffers) == set(payload["all_buffers"]), "Buffer ownership mismatch")
        for name, buffer in buffers.items():
            saved = payload["all_buffers"][name]
            require(
                saved.dtype == buffer.dtype
                and saved.shape == buffer.shape
                and torch.equal(saved, buffer.detach().cpu()),
                "Native buffer content/schema differs from pinned execution",
            )
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
            require(
                torch.equal(payload["native_buffers"][name], buffers[name].cpu()),
                "Persistent buffer representations disagree",
            )
        require(
            type(payload["completed_steps"]) is int and payload["completed_steps"] >= 0,
            "Invalid completed step",
        )
        require(
            payload["preservation_reference"] == "pinned_identity_only_no_new_preservation_loss",
            "Unknown reference role",
        )
        bridge.load_state_dict(payload["bridge"], strict=True)
        with torch.no_grad():
            for name, native in learner.base_named if learner.full_update else []:
                native.copy_(learner.masters[name].to(native.dtype), non_blocking=False)
        require(
            tree_hash(binding.base.state_dict()) == payload["current_base_sha256"],
            "Restored current-base content mismatch",
        )
        learner.bridge_optimizer.load_state_dict(copy.deepcopy(payload["bridge_optimizer"]))
        if learner.base_optimizer is not None:
            learner.base_optimizer.load_state_dict(copy.deepcopy(payload["base_optimizer"]))
        else:
            require(
                payload["base_optimizer"] is None and not payload["base_masters"],
                "Frozen checkpoint has base optimizer",
            )
        learner.completed_steps = payload["completed_steps"]
        learner._validate_ownership()
        restore_rng(payload["rng"])
        return learner
