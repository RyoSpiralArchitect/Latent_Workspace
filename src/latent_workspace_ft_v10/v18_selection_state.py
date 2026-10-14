"""Additive state/pipeline guard, not selection learner or checkpoint admission.

Only the existing exact split-query reader and pipeline are recognized. A future
numerical implementation requires a separately versioned binding. Historical
guard tables, readers, owners and their checkpoint whitelists stay unchanged.
The native owner must separately validate adapter execution and base storage;
this component binds the adapter object's identity, not its model internals.
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
from . import v18_selection_pipeline as pipeline_module
from . import v18_selection_reader as reader_module
from .query_modulated_bridge import QueryModulatedWorkspaceBridge
from .slot_contrast_state import storage_keys
from .v15_native_learner import reader_descriptor, require, tree_hash
from .v18_selection_pipeline import SelectionWorkspacePipeline
from .v18_selection_reader import SelectionWorkspaceBridge

FORMAT = "v18-selection-state-guard-v1"
QUALIFICATION = "STATE_GUARD_ONLY_NOT_LEARNER_QUALIFIED"

# Independent tables: never broaden the historical class whitelist in place.
_ATTRIBUTES = dict(historical._ATTRIBUTES)
_ATTRIBUTES[SelectionWorkspaceBridge] = historical._ATTRIBUTES[
    historical.SlotContrastWorkspaceBridge
]
_METHODS = {cls: dict(methods) for cls, methods in historical._METHODS.items()}
_METHODS[SelectionWorkspaceBridge] = {
    name: getattr(SelectionWorkspaceBridge, name)
    for name in (*historical._METHOD_NAMES, "_validate_queries")
    if hasattr(SelectionWorkspaceBridge, name)
}
_PIPELINE_METHODS = {
    name: getattr(SelectionWorkspacePipeline, name)
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
_PIPELINE_MODES = tuple(SelectionWorkspacePipeline.MODES)
_QUERY_GLOBALS = tuple(
    (module, name, getattr(module, name))
    for module, names in (
        (reader_module, ("_finite", "reader_descriptor")),
        (precision_module, ("_finite", "_mask")),
        (modulated_module, ("_finite", "_mask")),
        (pipeline_module, (
            "operand_reader_query", "validate_operand_span", "validate_token_tuple",
            "NativeWorkspacePipeline", "SelectionWorkspaceBridge", "SelectionWorkspaceOutput",
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
            SelectionWorkspaceBridge, SelectionWorkspacePipeline,
            *[value for _, _, value in _QUERY_GLOBALS if inspect.isfunction(value)],
            *_NATIVE_METHODS.values(), *_SPAN_METHODS.values(),
        )
    },
}


def _validate_implementations():
    require(
        all(getattr(module, name) is value for module, name, value in _QUERY_GLOBALS),
        "Selection query/validation helper replaced",
    )
    require(
        tuple(SelectionWorkspacePipeline.MODES) == _PIPELINE_MODES
        and type(SelectionWorkspacePipeline.MODES) is tuple,
        "Selection pipeline mode contract changed",
    )
    require(
        all(getattr(SelectionWorkspacePipeline, name) is value
            for name, value in _PIPELINE_METHODS.items())
        and all(getattr(native_pipeline_module.NativeWorkspacePipeline, name) is value
                for name, value in _NATIVE_METHODS.items())
        and operand_module.OperandSpan.__post_init__ is _SPAN_METHODS["__post_init__"]
        and operand_module.OperandSpan.prefix_ids.fget is _SPAN_METHODS["prefix_ids"],
        "Selection pipeline/span method replaced",
    )
    require(
        type(operand_module._GRAMMARS) is tuple
        and len(operand_module._GRAMMARS) == len(_GRAMMARS)
        and all(type(actual) is type(expected) and actual is expected
                for actual, expected in zip(operand_module._GRAMMARS, _GRAMMARS, strict=True)),
        "Selection operand grammar changed",
    )


def _structure(bridge):
    """Historical structural checks extended privately to the exact new root."""
    modules = {}
    for name, module in bridge.named_modules(remove_duplicate=False):
        cls = type(module)
        require(cls in _ATTRIBUTES, "Unqualified selection reader module")
        require(
            all(getattr(getattr(module, method), "__func__", None) is function
                for method, function in _METHODS[cls].items()),
            "Selection reader method override",
        )
        require(not any(value for key, value in vars(module).items() if "hook" in key),
                "Selection reader hooks are not owned")
        require(not any(isinstance(value, torch.Tensor) for value in vars(module).values()),
                "Unregistered selection reader tensor")
        require(not any(callable(value) for value in vars(module).values()),
                "Selection reader instance callback is not owned")
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
        "Selection reader parameter hooks are not owned",
    )
    require(not list(bridge.named_buffers()), "Selection reader buffers are not owned")
    require(set(bridge.state_dict()) == {name for name, _ in parameters}, "Unowned reader state")
    require(all(p.requires_grad and p.dtype == torch.float32 for _, p in parameters),
            "All production selection reader parameters must be trainable FP32")
    return {
        "modules": modules,
        "parameters": {name: [list(p.shape), str(p.dtype), p.requires_grad]
                       for name, p in parameters},
    }


def _validate_pipeline_shape(bridge, pipeline):
    require(type(pipeline) is SelectionWorkspacePipeline, "Expected exact selection pipeline")
    require(set(vars(pipeline)) == {"bridge", "adapter", "mode"}
            and pipeline.bridge is bridge,
            "Selection pipeline ownership or instance state changed")
    require(type(pipeline.mode) is str and pipeline.mode in _PIPELINE_MODES,
            "Invalid selection pipeline mode")


class SelectionStateBinding:
    """Guard all three trainable partitions and immutable pipeline selection.

    There is deliberately no save, optimizer or update API. Tensor values may
    change under a future qualified learner; topology, storage and policy may
    not. OperandSpan provenance still belongs to a sealed text/data binder.
    """

    def __init__(self, bridge, pipeline):
        require(type(bridge) is SelectionWorkspaceBridge, "Expected exact selection reader class")
        require(type(pipeline) is SelectionWorkspacePipeline, "Expected exact selection pipeline")
        _validate_implementations()
        common = reader_descriptor(bridge.common)
        with torch.device("meta"):
            template_common = type(bridge.common)(
                common["hidden_dim"], common["workspace_dim"], common["heads"],
                common["slots"], common["cap"],
                **({"modulation_strength": common["strength"]}
                   if type(bridge.common) is QueryModulatedWorkspaceBridge else {}),
            )
            template = SelectionWorkspaceBridge(
                template_common, mode=bridge.mode, interaction_fraction=bridge.interaction_fraction
            )
        structure = _structure(bridge)
        require(tree_hash(structure) == tree_hash(_structure(template)),
                "Noncanonical selection reader graph or policy")
        _validate_pipeline_shape(bridge, pipeline)
        self.bridge, self.pipeline = bridge, pipeline
        self._bridge_id, self._pipeline_id, self._adapter_id = id(bridge), id(pipeline), id(
            pipeline.adapter
        )
        self._modules = [(name, id(module))
                         for name, module in bridge.named_modules(remove_duplicate=False)]
        self._parameters = [(name, id(parameter)) for name, parameter in bridge.named_parameters()]
        self._storage = storage_keys(bridge.parameters())
        require(len(set(self._storage)) == len(self._storage), "Shared selection reader storage")
        devices = {parameter.device for parameter in bridge.parameters()}
        require(len(devices) == 1 and next(iter(devices)).type != "meta",
                "Selection reader requires one materialized device")
        partitions = {name: [] for name in ("writer", "common_reader", "interaction")}
        for name, _ in bridge.named_parameters():
            partition = (
                "writer" if name.startswith("common.writer.")
                else "common_reader" if name.startswith("common.") else "interaction"
            )
            partitions[partition].append(name)
        require({name: len(items) for name, items in partitions.items()}
                == {"writer": 20, "common_reader": 6, "interaction": 6},
                "Expected exact 20/6/6 production parameter partitions")
        self._descriptor = {
            "schema": FORMAT,
            "qualification": QUALIFICATION,
            "prototype": bridge.describe(),
            "pipeline": pipeline.describe(),
            "structure": structure,
            "parameter_partitions": partitions,
            "trainability": "all 32 bridge parameter tensors; no frozen-common fixture profile",
            "buffer_policy": "none; reject persistent and nonpersistent additions",
            "adapter_scope": "object identity only; native execution/storage owned separately",
            "operand_scope": "structural query policy; tokenizer/data provenance owned separately",
            "implementation_sha256": copy.deepcopy(_IMPLEMENTATIONS),
            "torch_version": str(torch.__version__),
        }
        self._descriptor = copy.deepcopy(self._descriptor)
        self._hash = tree_hash(self._descriptor)
        self.validate()

    def validate(self):
        _validate_implementations()
        require(tree_hash(self._descriptor) == self._hash, "Selection state contract mutated")
        require(id(self.bridge) == self._bridge_id and id(self.pipeline) == self._pipeline_id,
                "Selection reader/pipeline object replaced")
        require(type(self.bridge) is SelectionWorkspaceBridge
                and type(self.pipeline) is SelectionWorkspacePipeline,
                "Selection reader/pipeline class changed")
        _validate_pipeline_shape(self.bridge, self.pipeline)
        require(id(self.pipeline.adapter) == self._adapter_id, "Selection pipeline adapter changed")
        require([(name, id(module))
                 for name, module in self.bridge.named_modules(remove_duplicate=False)]
                == self._modules, "Selection reader module replaced")
        require([(name, id(parameter)) for name, parameter in self.bridge.named_parameters()]
                == self._parameters and storage_keys(self.bridge.parameters()) == self._storage,
                "Selection reader parameter/storage replaced")
        require(tree_hash(_structure(self.bridge)) == tree_hash(self._descriptor["structure"])
                and tree_hash(self.bridge.describe()) == tree_hash(self._descriptor["prototype"])
                and tree_hash(self.pipeline.describe()) == tree_hash(self._descriptor["pipeline"]),
                "Selection reader/pipeline execution policy changed")

    def describe(self):
        self.validate()
        return copy.deepcopy(self._descriptor)
