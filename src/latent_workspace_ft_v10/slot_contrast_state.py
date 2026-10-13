"""Explicit reader-state contract, independent of transformer architecture.

The sealed prototype and v15 whitelist remain unchanged. This binding admits
only that prototype's canonical module graph, not arbitrary nn.Module objects.
It owns disjoint writer/common-reader/interaction parameter partitions. Empty
buffer ownership is intentional: new buffers require a new qualified contract.
"""

from __future__ import annotations

import copy
import hashlib
import inspect

import torch
from torch import nn

from .precision_bridge import PrecisionAwareWorkspaceBridge
from .query_modulated_bridge import QueryModulatedWorkspaceBridge
from .v15_native_learner import reader_descriptor, require, tree_hash
from .v16_slot_contrast import SlotContrastWorkspaceBridge
from .workspace_core import FunctionalMemoryWriter

_ATTRIBUTES = {
    SlotContrastWorkspaceBridge: (
        "mode",
        "interaction_fraction",
        "hidden_dim",
        "workspace_dim",
        "max_delta_norm",
        "slots",
        "common_descriptor",
    ),
    PrecisionAwareWorkspaceBridge: ("hidden_dim", "workspace_dim", "slots", "max_delta_norm"),
    QueryModulatedWorkspaceBridge: (
        "hidden_dim",
        "workspace_dim",
        "slots",
        "max_delta_norm",
        "_modulation_strength",
    ),
    FunctionalMemoryWriter: (
        "hidden_dim",
        "workspace_dim",
        "mode",
        "slot_count",
        "steps",
        "output_dim",
    ),
    nn.Linear: ("in_features", "out_features"),
    nn.modules.linear.NonDynamicallyQuantizableLinear: ("in_features", "out_features"),
    nn.LayerNorm: ("normalized_shape", "eps", "elementwise_affine"),
    nn.MultiheadAttention: (
        "embed_dim",
        "kdim",
        "vdim",
        "_qkv_same_embed_dim",
        "num_heads",
        "dropout",
        "head_dim",
        "add_zero_attn",
        "batch_first",
    ),
    nn.Sequential: (),
    nn.GELU: ("approximate",),
    nn.Dropout: ("p", "inplace"),
}
_METHOD_NAMES = (
    "forward",
    "write_memory",
    "read_delta",
    "parts",
    "describe",
    "_validate_parameters",
)
_METHODS = {
    cls: {name: getattr(cls, name) for name in _METHOD_NAMES if hasattr(cls, name)}
    for cls in _ATTRIBUTES
}
_SOURCES = {
    f"{cls.__module__}.{cls.__qualname__}": hashlib.sha256(
        inspect.getsource(cls).encode()
    ).hexdigest()
    for cls in _ATTRIBUTES
}


def _structure(bridge):
    modules = {}
    for name, module in bridge.named_modules(remove_duplicate=False):
        cls = type(module)
        require(cls in _ATTRIBUTES, "Unqualified reader module")
        require(
            all(
                getattr(getattr(module, method), "__func__", None) is function
                for method, function in _METHODS[cls].items()
            ),
            "Reader method override",
        )
        require(
            not any(value for key, value in vars(module).items() if "hook" in key),
            "Reader hooks are not owned",
        )
        require(
            not any(isinstance(value, torch.Tensor) for value in vars(module).values()),
            "Unregistered reader tensor",
        )
        require(
            not any(callable(value) for value in vars(module).values()),
            "Instance reader callbacks are not owned",
        )
        modules[name] = {
            "class": f"{cls.__module__}.{cls.__qualname__}",
            "training": module.training,
            "attribute_names": sorted(vars(module)),
            "policy": {key: copy.deepcopy(getattr(module, key)) for key in _ATTRIBUTES[cls]},
        }
    parameters = list(bridge.named_parameters(remove_duplicate=False))
    require(len({id(p) for _, p in parameters}) == len(parameters), "Aliased reader parameter")
    require(not list(bridge.named_buffers()), "Reader buffers require a new contract")
    require(set(bridge.state_dict()) == {name for name, _ in parameters}, "Unowned reader state")
    return {
        "modules": modules,
        "parameters": {
            name: [list(p.shape), str(p.dtype), p.requires_grad] for name, p in parameters
        },
    }


def storage_keys(parameters):
    """Reject storage sharing as well as duplicate Parameter identities."""
    return [(str(p.device), p.untyped_storage().data_ptr()) for p in parameters]


class SlotContrastStateBinding:
    """Canonical training-only reader, with zero mutable buffers and no hooks."""

    def __init__(self, bridge):
        require(type(bridge) is SlotContrastWorkspaceBridge, "Expected exact slot-contrast class")
        common = reader_descriptor(bridge.common)
        # Meta construction validates canonical shapes/policies without allocating
        # a second reader or consuming process CPU/CUDA RNG state.
        with torch.device("meta"):
            template_common = type(bridge.common)(
                common["hidden_dim"],
                common["workspace_dim"],
                common["heads"],
                common["slots"],
                common["cap"],
                **(
                    {"modulation_strength": common["strength"]}
                    if type(bridge.common) is QueryModulatedWorkspaceBridge
                    else {}
                ),
            )
            template = SlotContrastWorkspaceBridge(
                template_common, mode=bridge.mode, interaction_fraction=bridge.interaction_fraction
            )
        structure = _structure(bridge)
        require(structure == _structure(template), "Noncanonical reader graph or policy")
        self.bridge = bridge
        self._modules = [(n, id(m)) for n, m in bridge.named_modules(remove_duplicate=False)]
        self._parameters = [(n, id(p)) for n, p in bridge.named_parameters()]
        self._storage = storage_keys(bridge.parameters())
        require(len(set(self._storage)) == len(self._storage), "Shared reader storage")
        partitions = {"writer": [], "common_reader": [], "interaction": []}
        for name, _ in bridge.named_parameters():
            partition = (
                "writer"
                if name.startswith("common.writer.")
                else "common_reader"
                if name.startswith("common.")
                else "interaction"
            )
            partitions[partition].append(name)
        require(all(partitions.values()), "All three reader partitions required")
        self._descriptor = {
            "schema": "v16-slot-contrast-state-v1",
            "prototype": bridge.describe(),
            "structure": structure,
            "parameter_partitions": partitions,
            "buffer_policy": "none; reject persistent and nonpersistent additions",
            "implementation_sha256": _SOURCES,
            "torch_version": str(torch.__version__),
        }
        self._descriptor = copy.deepcopy(self._descriptor)
        self._hash = tree_hash(self._descriptor)
        self.validate()

    def validate(self):
        require(tree_hash(self._descriptor) == self._hash, "Reader contract mutated")
        require(
            [(n, id(m)) for n, m in self.bridge.named_modules(remove_duplicate=False)]
            == self._modules,
            "Reader module replacement",
        )
        require(
            [(n, id(p)) for n, p in self.bridge.named_parameters()] == self._parameters
            and storage_keys(self.bridge.parameters()) == self._storage,
            "Reader parameter/storage replacement",
        )
        require(
            _structure(self.bridge) == self._descriptor["structure"]
            and self.bridge.describe() == self._descriptor["prototype"],
            "Reader execution policy changed",
        )

    def describe(self):
        self.validate()
        return copy.deepcopy(self._descriptor)
