"""V19 dual-budget native owner; historical update and restore publication unchanged.

Derived from the V18 split-query owner with only the reader, pipeline, state
binding, payload format and policy names replaced. The independently expected
workspace-query policy is bound into the run contract, so restore never infers
policy from saved state. Native CPU gradient accumulation, FP32 masters and the
original optimizers are reused unchanged. Not a window/data provenance owner.
"""

from __future__ import annotations

import copy
import math

import torch
from torch import nn
from transformers.optimization import Adafactor

from .adapter_native_learner_v2 import (
    AdapterNativeLearnerV2,
    _ProjectedNativeState,
    snapshot,
    tensor_schema,
    validate_optimizer,
    validate_rng,
)
from .slot_contrast_learner import PAYLOAD_KEYS as HISTORICAL_PAYLOAD_KEYS
from .slot_contrast_state import storage_keys
from .v15_native_learner import V15NativeLearner, finite_tree, require, tree_hash
from .v19_dual_budget_pipeline import DualBudgetWorkspacePipeline
from .v19_dual_budget_state import DualBudgetStateBinding

FORMAT = "v19-dual-budget-native-resume-v1"
POLICY_FORMAT = "v19-dual-budget-query-policy-v1"
CONTRACT_KEY = "v19_dual_budget_policy"
PAYLOAD_KEYS = HISTORICAL_PAYLOAD_KEYS | {"workspace_policy", "tensor_layout"}
_QUERY_MODES = ("final", "ordered_difference", "symmetric_mean")


def validate_workspace_policy(policy):
    """Validate primitive caller policy without executing a model or changing RNG."""
    require(type(policy) is dict and set(policy) == {"schema", "workspace_query"},
            "Exact V19 workspace policy fields required")
    require(type(policy["schema"]) is str and policy["schema"] == POLICY_FORMAT,
            "V19 workspace policy schema mismatch")
    require(type(policy["workspace_query"]) is str
            and policy["workspace_query"] in _QUERY_MODES,
            "Unknown V19 workspace query")


def _contract_policy(run_contract):
    require(type(run_contract) is dict and CONTRACT_KEY in run_contract,
            "Explicit V19 workspace policy in run contract required")
    policy = run_contract[CONTRACT_KEY]
    validate_workspace_policy(policy)
    return policy


def _layout(named):
    result = {}
    for name, value in named:
        require(value.layout == torch.strided and value.is_contiguous()
                and value.storage_offset() == 0 and value.device.type != "meta",
                "V19 owner requires contiguous offset-zero materialized tensors")
        result[name] = {
            "shape": list(value.shape), "stride": list(value.stride()),
            "storage_offset": value.storage_offset(), "layout": str(value.layout),
        }
    return result


def _storage_identity(named):
    return [
        (name, id(value), str(value.device), value.untyped_storage().data_ptr(),
         value.untyped_storage().nbytes(), value.data_ptr())
        for name, value in named
    ]


class DualBudgetNativeLearner(AdapterNativeLearnerV2):
    """Own exact dual-budget execution and all 20/6/6 reader partitions.

    ``run_contract[CONTRACT_KEY]`` must independently agree with the explicit
    ``workspace_policy`` argument. Public restore requires both again; policy
    is never inferred from untrusted saved state. All borrowed updates retain
    native CPU gradient accumulation, FP32 masters and original optimizer math.
    """

    def __init__(
        self, binding, bridge, *, workspace_policy, full_update, optimizer_config,
        run_contract, master_state=None,
    ):
        require(type(self) is DualBudgetNativeLearner,
                "Exact V19 dual-budget native owner required")
        validate_workspace_policy(workspace_policy)
        require(tree_hash(_contract_policy(run_contract)) == tree_hash(workspace_policy),
                "V19 workspace policy differs from independently declared run contract")
        require(type(full_update) is bool, "Explicit update scope")
        self.binding, self.base, self.bridge = binding, binding.base, bridge
        self._binding_id, self._base_id = id(binding), id(self.base)
        self.full_update, self.boundary = full_update, binding.boundary
        self.workspace_policy = copy.deepcopy(workspace_policy)
        self._workspace_hash = tree_hash(self.workspace_policy)
        self.config = copy.deepcopy(optimizer_config)
        self._config_hash = tree_hash(self.config)
        require(
            set(self.config) >= {
                "bridge_lr", "base_lr", "max_grad_norm_per_family",
                "bridge_weight_decay", "base_weight_decay",
            }, "Complete optimizer settings",
        )
        for key in ("bridge_lr", "base_lr", "max_grad_norm_per_family"):
            require(type(self.config[key]) in (int, float)
                    and math.isfinite(self.config[key]) and self.config[key] > 0,
                    "Positive finite optimizer settings")
        for key in ("bridge_weight_decay", "base_weight_decay"):
            require(type(self.config[key]) in (int, float)
                    and math.isfinite(self.config[key]) and self.config[key] >= 0,
                    "Finite weight decay")
        require(run_contract.get("objective")
                and run_contract.get("original_base_sha256") == tree_hash(self.base.state_dict()),
                "Initialize from the exact pinned original base and explicit objective")
        self.run_contract = copy.deepcopy(run_contract)
        self._run_hash = tree_hash(self.run_contract)
        binding.validate()
        self.execution = copy.deepcopy(binding.describe())
        self._execution_hash = tree_hash(self.execution)
        self.pipeline = DualBudgetWorkspacePipeline(
            bridge, binding.readout, self.workspace_policy["workspace_query"]
        )
        self.reader_binding = DualBudgetStateBinding(bridge, self.pipeline)
        self._reader_binding_id = id(self.reader_binding)
        self.reader = self.reader_binding.describe()
        self._reader_hash = tree_hash(self.reader)
        self.base_named, self.bridge_named = (
            list(self.base.named_parameters()), list(bridge.named_parameters()),
        )
        self.schemas = {id(p): (tuple(p.shape), p.dtype, p.device)
                        for _, p in self.base_named + self.bridge_named}
        require(self.base_named and self.bridge_named, "Both parameter families required")
        require(all(p.requires_grad == full_update for _, p in self.base_named),
                "Base update ownership")
        require(all(p.requires_grad and p.dtype == torch.float32 for _, p in self.bridge_named),
                "FP32 trainable bridge required")
        require({p.device for _, p in self.bridge_named} == {p.device for _, p in self.base_named}
                and len({p.device for _, p in self.base_named}) == 1,
                "Single shared native/reader device required")
        require(not ({id(p) for _, p in self.base_named} & {id(p) for _, p in self.bridge_named}),
                "Cross-owned parameter")
        canonical = {id(p): n for n, p in self.base_named}
        self.aliases = {
            n: canonical[id(p)] for n, p in self.base.named_parameters(remove_duplicate=False)
        }
        self.buffer_names = sorted(set(self.base.state_dict()) - set(self.aliases))
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
                    if master_state is None else master_state[name].detach().clone()
                )
                require(value.device.type == "cpu" and value.dtype == torch.float32
                        and value.shape == parameter.shape and bool(torch.isfinite(value).all()),
                        "FP32 master schema")
                self.masters[name] = nn.Parameter(value, requires_grad=True)
        else:
            require(master_state is None, "Frozen owner cannot import base masters")
        self.bridge_optimizer = torch.optim.AdamW(
            [p for _, p in self.bridge_named], lr=self.config["bridge_lr"],
            weight_decay=self.config["bridge_weight_decay"],
        )
        self.base_optimizer = (
            Adafactor(
                list(self.masters.values()), lr=self.config["base_lr"], eps=(1e-30, 1e-3),
                clip_threshold=1.0, decay_rate=-0.8, beta1=None,
                weight_decay=self.config["base_weight_decay"], scale_parameter=False,
                relative_step=False, warmup_init=False,
            ) if full_update else None
        )
        self.tensor_layout = self._current_layout()
        self._layout_hash = tree_hash(self.tensor_layout)
        self._storage = _storage_identity(self._owned_tensors())
        owned_storage = storage_keys(p for _, p in self._owned_tensors())
        require(len(set(owned_storage)) == len(owned_storage),
                "Shared native/reader/master/buffer storage")
        self.completed_steps, self.window, self.keys, self.cursor = 0, None, (), 0
        self._bridge_policy = self._optimizer_policy(self.bridge_optimizer)
        self._base_policy = self._optimizer_policy(self.base_optimizer)
        self._validate_ownership()

    def _owned_tensors(self):
        return (
            [(f"base.{name}", value) for name, value in self.base_named]
            + [(f"bridge.{name}", value) for name, value in self.bridge_named]
            + [(f"masters.{name}", value) for name, value in self.masters.items()]
            + [(f"buffers.{name}", value)
               for name, value in self.base.named_buffers(remove_duplicate=False)]
        )

    def _current_layout(self):
        return _layout(self._owned_tensors())

    def _validate_ownership(self):
        V15NativeLearner._validate_ownership(self)
        require(tree_hash(self.tensor_layout) == self._layout_hash
                and tree_hash(self._current_layout()) == self._layout_hash
                and _storage_identity(self._owned_tensors()) == self._storage,
                "Owned tensor layout/storage identity changed")
        require(id(self.binding) == self._binding_id and id(self.base) == self._base_id,
                "Native binding/base object replaced")
        require(type(self.reader_binding) is DualBudgetStateBinding
                and id(self.reader_binding) == self._reader_binding_id
                and self.reader_binding.bridge is self.bridge
                and self.reader_binding.pipeline is self.pipeline,
                "V19 binding ownership changed")
        require(not (set(storage_keys(self.base.parameters()))
                     & set(storage_keys(self.bridge.parameters()))),
                "Cross-owned parameter storage")
        require(not self.binding.readout.objective_active,
                "Active objective cannot change owner state")
        require(tree_hash(self.config) == self._config_hash, "Optimizer configuration changed")
        require(tree_hash(self.reader) == self._reader_hash, "Reader descriptor changed")
        require(tree_hash(self.execution) == self._execution_hash, "Execution descriptor changed")
        validate_workspace_policy(self.workspace_policy)
        require(tree_hash(self.workspace_policy) == self._workspace_hash
                and tree_hash(_contract_policy(self.run_contract)) == self._workspace_hash,
                "V19 workspace policy changed")
        self.binding.validate()
        require(self.binding.base is self.base and self.pipeline.adapter is self.binding.readout
                and self.pipeline.mode == self.workspace_policy["workspace_query"],
                "V19 pipeline/native ownership changed")
        require(tree_hash(self.binding.describe()) == self._execution_hash,
                "Native execution contract changed")
        require(tree_hash(self.run_contract) == self._run_hash, "Run contract changed")
        require(tree_hash(self.reader_binding.describe()) == self._reader_hash,
                "Reader semantics changed")
        require(self._optimizer_policy(self.bridge_optimizer) == self._bridge_policy
                and self._optimizer_policy(self.base_optimizer) == self._base_policy,
                "Optimizer policy changed")

    def payload(self, metadata):
        value = super().payload(metadata)
        value.update(
            format=FORMAT, workspace_policy=copy.deepcopy(self.workspace_policy),
            tensor_layout=copy.deepcopy(self.tensor_layout),
        )
        return value

    @classmethod
    def restore(
        cls, binding, bridge, payload, *, expected_workspace_policy, expected_metadata,
        expected_run_contract, expected_state_sha256,
    ):
        require(cls is DualBudgetNativeLearner, "Exact V19 dual-budget native owner required")
        validate_workspace_policy(expected_workspace_policy)
        require(tree_hash(_contract_policy(expected_run_contract))
                == tree_hash(expected_workspace_policy),
                "Independent expected V19 workspace policy mismatch")
        # The inherited V2 entry calls our preflight, then publishes using its
        # unchanged direct-copy order. No temporary global/class policy exists.
        return super().restore(
            binding, bridge, payload, expected_metadata=expected_metadata,
            expected_run_contract=expected_run_contract,
            expected_state_sha256=expected_state_sha256,
        )

    @classmethod
    def _prepare_restore(
        cls, binding, bridge, payload, *, expected_metadata, expected_run_contract,
        expected_state_sha256,
    ):
        require(cls is DualBudgetNativeLearner, "Exact V19 dual-budget native owner required")
        policy = _contract_policy(expected_run_contract)
        require(type(payload) is dict and set(payload) == PAYLOAD_KEYS,
                "Checkpoint field ownership mismatch")
        require(tree_hash(payload) == expected_state_sha256, "Checkpoint content receipt mismatch")
        require(payload["format"] == FORMAT
                and tree_hash(payload["metadata"]) == tree_hash(expected_metadata)
                and tree_hash(payload["run_contract"]) == tree_hash(expected_run_contract),
                "Resume provenance mismatch")
        validate_workspace_policy(payload["workspace_policy"])
        require(tree_hash(payload["workspace_policy"]) == tree_hash(policy),
                "Saved V19 workspace policy mismatch")
        require(tree_hash(payload["execution"]) == tree_hash(binding.describe()),
                "Resume execution policy mismatch")
        pipeline = DualBudgetWorkspacePipeline(bridge, binding.readout, policy["workspace_query"])
        require(tree_hash(payload["reader"])
                == tree_hash(DualBudgetStateBinding(bridge, pipeline).describe()),
                "Reader semantics mismatch")
        require(finite_tree(payload), "Nonfinite checkpoint")
        require(payload["native_schema"]
                == {n: [list(p.shape), str(p.dtype)] for n, p in binding.base.named_parameters()},
                "Native schema mismatch")
        require(all(p.grad is None for p in (*binding.base.parameters(), *bridge.parameters())),
                "Restore targets have live gradients")
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
        require(type(payload["full_update"]) is bool, "Explicit checkpoint update scope")
        if not payload["full_update"]:
            require(not payload["base_masters"], "Frozen checkpoint has base masters")
        else:
            require(set(payload["base_masters"]) == dict(binding.base.named_parameters()).keys(),
                    "Master keys")
            for name, target in binding.base.named_parameters():
                tensor_schema(payload["base_masters"][name], target.shape, torch.float32)
        # Inspect saved layouts before clone/copy can normalize an offset/view.
        saved_layout = _layout(
            [(f"bridge.{n}", p) for n, p in payload["bridge"].items()]
            + [(f"masters.{n}", p) for n, p in payload["base_masters"].items()]
            + [(f"buffers.{n}", p) for n, p in payload["all_buffers"].items()]
        )
        require(type(payload["tensor_layout"]) is dict
                and all(payload["tensor_layout"].get(n) == value
                        for n, value in saved_layout.items()),
                "Saved tensor layout differs from checkpoint layout policy")
        learner = cls(
            binding, bridge, workspace_policy=policy, full_update=payload["full_update"],
            optimizer_config=payload["optimizer_config"], run_contract=expected_run_contract,
            master_state=payload["base_masters"] if payload["full_update"] else None,
        )
        require(tree_hash(payload["tensor_layout"]) == tree_hash(learner.tensor_layout),
                "Checkpoint tensor layout policy mismatch")
        require(payload["base_aliases"] == learner.aliases
                and set(payload["native_buffers"]) == set(learner.buffer_names)
                and payload["boundary"] == learner.boundary,
                "Alias/boundary/buffer mismatch")
        for name in learner.buffer_names:
            tensor_schema(payload["native_buffers"][name], buffers[name].shape, buffers[name].dtype)
            require(torch.equal(payload["native_buffers"][name], buffers[name].cpu()),
                    "Persistent buffer representations disagree")
        require(tree_hash(_ProjectedNativeState(learner)) == payload["current_base_sha256"],
                "Restored current-base content mismatch")
        validate_optimizer(payload["bridge_optimizer"], learner.bridge_optimizer, steps, base=False)
        validate_optimizer(payload["base_optimizer"], learner.base_optimizer, steps, base=True)
        validate_rng(payload["rng"])
        learner.bridge_optimizer.load_state_dict(snapshot(payload["bridge_optimizer"]))
        if learner.base_optimizer is not None:
            learner.base_optimizer.load_state_dict(snapshot(payload["base_optimizer"]))
        learner.completed_steps = steps
        learner._validate_ownership()
        return learner
