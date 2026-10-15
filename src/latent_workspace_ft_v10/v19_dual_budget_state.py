"""V19 state/pipeline guard for the dual-budget reader; not a learner by itself.

Independent copies of the historical tables are extended with the exact V19
reader and pipeline. Historical guard tables, readers, owners and checkpoint
whitelists stay unchanged. Native execution and base storage are validated by
the V19 native owner; this binding owns reader topology, storage and policy.
"""

from __future__ import annotations

import copy
import hashlib
import inspect

import torch

from . import precision_bridge as precision_module
from . import query_modulated_bridge as modulated_module
from . import slot_contrast_state as historical
from . import v15_pipeline as native_pipeline_module
from . import v18_operand_query as operand_module
from . import v19_dual_budget_pipeline as pipeline_module
from . import v19_dual_budget_reader as reader_module
from .query_modulated_bridge import QueryModulatedWorkspaceBridge
from .slot_contrast_state import storage_keys
from .v15_native_learner import reader_descriptor, require, tree_hash
from .v19_dual_budget_pipeline import DualBudgetWorkspacePipeline
from .v19_dual_budget_reader import DualBudgetWorkspaceBridge

FORMAT = "v19-dual-budget-state-guard-v1"
QUALIFICATION = "STATE_GUARD_ONLY_NOT_LEARNER_QUALIFIED"

_ATTRIBUTES = dict(historical._ATTRIBUTES)
_ATTRIBUTES[DualBudgetWorkspaceBridge] = (
    "mode",
    "workspace_cap",
    "common_cap",
    "hidden_dim",
    "workspace_dim",
    "slots",
    "common_descriptor",
)
_METHODS = {cls: dict(methods) for cls, methods in historical._METHODS.items()}
_METHODS[DualBudgetWorkspaceBridge] = {
    name: getattr(DualBudgetWorkspaceBridge, name)
    for name in (*historical._METHOD_NAMES, "_validate_queries")
    if hasattr(DualBudgetWorkspaceBridge, name)
}
_PIPELINE_METHODS = {
    name: getattr(DualBudgetWorkspacePipeline, name)
    for name in ("__init__", "__call__", "describe")
}
_NATIVE_METHODS = {
    name: getattr(native_pipeline_module.NativeWorkspacePipeline, name)
    for name in ("__init__", "query")
}
_SPAN_METHODS = {
    "__post_init__": operand_module.OperandSpan.__post_init__,
    "prefix_ids": operand_module.OperandSpan.prefix_ids.fget,
}
_PIPELINE_MODES = tuple(DualBudgetWorkspacePipeline.MODES)
_READER_MODES = tuple(DualBudgetWorkspaceBridge.MODES)
_QUERY_GLOBALS = tuple(
    (module, name, getattr(module, name))
    for module, names in (
        (reader_module, ("_finite", "reader_descriptor")),
        (precision_module, ("_finite", "_mask")),
        (modulated_module, ("_finite", "_mask")),
        (pipeline_module, (
            "operand_reader_query", "validate_operand_span", "validate_token_tuple",
            "NativeWorkspacePipeline", "DualBudgetWorkspaceBridge", "SelectionWorkspaceOutput",
        )),
        (operand_module, ("validate_operand_span", "OperandSpan", "_ids", "_operands", "_indices")),
        (native_pipeline_module, ("base_readout_hidden", "reader_query_hidden")),
    )
    for name in names
)
_GRAMMARS = tuple(operand_module._GRAMMARS)
_IMPLEMENTATIONS = {
    **dict(historical._SOURCES),
    **{
        f"{value.__module__}.{value.__qualname__}": hashlib.sha256(
            inspect.getsource(value).encode()
        ).hexdigest()
        for value in (
            DualBudgetWorkspaceBridge, DualBudgetWorkspacePipeline,
            *[value for _, _, value in _QUERY_GLOBALS if inspect.isfunction(value)],
            *_NATIVE_METHODS.values(), *_SPAN_METHODS.values(),
        )
    },
}


def _validate_implementations():
    require(
        all(getattr(module, name) is value for module, name, value in _QUERY_GLOBALS),
        "V19 query/validation helper replaced",
    )
    require(
        tuple(DualBudgetWorkspacePipeline.MODES) == _PIPELINE_MODES
        and type(DualBudgetWorkspacePipeline.MODES) is tuple
        and tuple(DualBudgetWorkspaceBridge.MODES) == _READER_MODES
        and type(DualBudgetWorkspaceBridge.MODES) is tuple,
        "V19 pipeline/reader mode contract changed",
    )
    require(
        all(getattr(DualBudgetWorkspacePipeline, name) is value
            for name, value in _PIPELINE_METHODS.items())
        and all(getattr(native_pipeline_module.NativeWorkspacePipeline, name) is value
                for name, value in _NATIVE_METHODS.items())
        and operand_module.OperandSpan.__post_init__ is _SPAN_METHODS["__post_init__"]
        and operand_module.OperandSpan.prefix_ids.fget is _SPAN_METHODS["prefix_ids"],
        "V19 pipeline/span method replaced",
    )
    require(
        type(operand_module._GRAMMARS) is tuple
        and len(operand_module._GRAMMARS) == len(_GRAMMARS)
        and all(type(actual) is type(expected) and actual is expected
                for actual, expected in zip(operand_module._GRAMMARS, _GRAMMARS, strict=True)),
        "V19 operand grammar changed",
    )


def _structure(bridge):
    modules = {}
    for name, module in bridge.named_modules(remove_duplicate=False):
        cls = type(module)
        require(cls in _ATTRIBUTES, "Unqualified V19 reader module")
        require(
            all(getattr(getattr(module, method), "__func__", None) is function
                for method, function in _METHODS[cls].items()),
            "V19 reader method override",
        )
        require(not any(value for key, value in vars(module).items() if "hook" in key),
                "V19 reader hooks are not owned")
        require(not any(isinstance(value, torch.Tensor) for value in vars(module).values()),
                "Unregistered V19 reader tensor")
        require(not any(callable(value) for value in vars(module).values()),
                "V19 reader instance callback is not owned")
        modules[name] = {
            "class": f"{cls.__module__}.{cls.__qualname__}",
            "training": module.training,
            "attribute_names": sorted(vars(module)),
            "policy": {key: copy.deepcopy(getattr(module, key)) for key in _ATTRIBUTES[cls]},
        }
    parameters = list(bridge.named_parameters(remove_duplicate=False))
    require(len({id(p) for _, p in parameters}) == len(parameters), "Aliased reader parameter")
    require(
        not any(getattr(parameter, name, None)
                for _, parameter in parameters
                for name in ("_backward_hooks", "_post_accumulate_grad_hooks")),
        "V19 reader parameter hooks are not owned",
    )
    require(not list(bridge.named_buffers()), "V19 reader buffers are not owned")
    require(set(bridge.state_dict()) == {name for name, _ in parameters}, "Unowned reader state")
    require(all(p.requires_grad and p.dtype == torch.float32 for _, p in parameters),
            "All production V19 reader parameters must be trainable FP32")
    return {
        "modules": modules,
        "parameters": {name: [list(p.shape), str(p.dtype), p.requires_grad]
                       for name, p in parameters},
    }


def _validate_pipeline_shape(bridge, pipeline):
    require(type(pipeline) is DualBudgetWorkspacePipeline, "Expected exact V19 pipeline")
    require(set(vars(pipeline)) == {"bridge", "adapter", "mode"} and pipeline.bridge is bridge,
            "V19 pipeline ownership or instance state changed")
    require(type(pipeline.mode) is str and pipeline.mode in _PIPELINE_MODES,
            "Invalid V19 pipeline mode")


class DualBudgetStateBinding:
    """Guard writer, common and workspace partitions and the immutable pipeline."""

    def __init__(self, bridge, pipeline):
        require(type(bridge) is DualBudgetWorkspaceBridge, "Expected exact V19 reader class")
        require(type(pipeline) is DualBudgetWorkspacePipeline, "Expected exact V19 pipeline")
        _validate_implementations()
        common = reader_descriptor(bridge.common)
        with torch.device("meta"):
            template_common = type(bridge.common)(
                common["hidden_dim"], common["workspace_dim"], common["heads"],
                common["slots"], common["cap"],
                **({"modulation_strength": common["strength"]}
                   if type(bridge.common) is QueryModulatedWorkspaceBridge else {}),
            )
            template = DualBudgetWorkspaceBridge(
                template_common, mode=bridge.mode, workspace_cap=bridge.workspace_cap
            )
        structure = _structure(bridge)
        require(tree_hash(structure) == tree_hash(_structure(template)),
                "Noncanonical V19 reader graph or policy")
        _validate_pipeline_shape(bridge, pipeline)
        self.bridge, self.pipeline = bridge, pipeline
        self._bridge_id, self._pipeline_id = id(bridge), id(pipeline)
        self._adapter_id = id(pipeline.adapter)
        self._modules = [(name, id(module))
                         for name, module in bridge.named_modules(remove_duplicate=False)]
        self._parameters = [(name, id(parameter)) for name, parameter in bridge.named_parameters()]
        self._storage = storage_keys(bridge.parameters())
        require(len(set(self._storage)) == len(self._storage), "Shared V19 reader storage")
        devices = {parameter.device for parameter in bridge.parameters()}
        require(len(devices) == 1 and next(iter(devices)).type != "meta",
                "V19 reader requires one materialized device")
        partitions = {name: [] for name in ("writer", "common_reader", "workspace")}
        for name, _ in bridge.named_parameters():
            partition = (
                "writer" if name.startswith("common.writer.")
                else "common_reader" if name.startswith("common.") else "workspace"
            )
            partitions[partition].append(name)
        require({name: len(items) for name, items in partitions.items()}
                == {"writer": 20, "common_reader": 6, "workspace": 6},
                "Expected exact 20/6/6 production parameter partitions")
        self._descriptor = copy.deepcopy({
            "schema": FORMAT,
            "qualification": QUALIFICATION,
            "reader": bridge.describe(),
            "pipeline": pipeline.describe(),
            "structure": structure,
            "parameter_partitions": partitions,
            "trainability": "all 32 bridge parameter tensors; no frozen-common profile",
            "buffer_policy": "none; reject persistent and nonpersistent additions",
            "adapter_scope": "object identity only; native execution/storage owned separately",
            "operand_scope": "structural query policy; tokenizer/data provenance owned separately",
            "implementation_sha256": copy.deepcopy(_IMPLEMENTATIONS),
            "torch_version": str(torch.__version__),
        })
        self._hash = tree_hash(self._descriptor)
        self.validate()

    def validate(self):
        _validate_implementations()
        require(tree_hash(self._descriptor) == self._hash, "V19 state contract mutated")
        require(id(self.bridge) == self._bridge_id and id(self.pipeline) == self._pipeline_id,
                "V19 reader/pipeline object replaced")
        require(type(self.bridge) is DualBudgetWorkspaceBridge
                and type(self.pipeline) is DualBudgetWorkspacePipeline,
                "V19 reader/pipeline class changed")
        _validate_pipeline_shape(self.bridge, self.pipeline)
        require(id(self.pipeline.adapter) == self._adapter_id, "V19 pipeline adapter changed")
        require([(name, id(module))
                 for name, module in self.bridge.named_modules(remove_duplicate=False)]
                == self._modules, "V19 reader module replaced")
        require([(name, id(parameter)) for name, parameter in self.bridge.named_parameters()]
                == self._parameters and storage_keys(self.bridge.parameters()) == self._storage,
                "V19 reader parameter/storage replaced")
        require(tree_hash(_structure(self.bridge)) == tree_hash(self._descriptor["structure"])
                and tree_hash(self.bridge.describe()) == tree_hash(self._descriptor["reader"])
                and tree_hash(self.pipeline.describe()) == tree_hash(self._descriptor["pipeline"]),
                "V19 reader/pipeline execution policy changed")

    def describe(self):
        self.validate()
        return copy.deepcopy(self._descriptor)
