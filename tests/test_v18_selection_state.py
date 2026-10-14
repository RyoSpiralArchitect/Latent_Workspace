"""Tiny state/pipeline guard tests; no learner admission or study fitting."""

import copy
import types

import pytest
import torch

from latent_workspace_ft_v10 import slot_contrast_state as historical
from latent_workspace_ft_v10 import v15_pipeline as native_module
from latent_workspace_ft_v10 import v18_operand_query as operand_module
from latent_workspace_ft_v10 import v18_selection_pipeline as pipeline_module
from latent_workspace_ft_v10 import v18_selection_reader as reader_module
from latent_workspace_ft_v10.precision_bridge import PrecisionAwareWorkspaceBridge
from latent_workspace_ft_v10.query_modulated_bridge import QueryModulatedWorkspaceBridge
from latent_workspace_ft_v10.v15_native_learner import rng_state, tree_hash
from latent_workspace_ft_v10.v18_selection_pipeline import SelectionWorkspacePipeline
from latent_workspace_ft_v10.v18_selection_reader import SelectionWorkspaceBridge
from latent_workspace_ft_v10.v18_selection_state import (
    FORMAT,
    QUALIFICATION,
    SelectionStateBinding,
)
from latent_workspace_ft_v10.v18_window_learner import _ReaderGuard


class NoExecutionAdapter:
    vocabulary = 41

    def read(self, *_args):
        raise AssertionError("State binding must not execute native model")


def build(mode="ordered_difference", common=PrecisionAwareWorkspaceBridge,
          factor="slot_contrast"):
    torch.manual_seed(271)
    reader = SelectionWorkspaceBridge(
        common(16, workspace_dim=8, heads=2, slots=3, max_delta_norm=1), mode=factor
    )
    pipeline = SelectionWorkspacePipeline(reader, NoExecutionAdapter(), mode)
    return reader, pipeline


@pytest.mark.parametrize("mode", SelectionWorkspacePipeline.MODES)
@pytest.mark.parametrize("common", [PrecisionAwareWorkspaceBridge, QueryModulatedWorkspaceBridge])
@pytest.mark.parametrize("factor", ["slot_contrast", "raw_matched_control"])
def test_production_partition_query_policy_and_rng_neutral_construction(mode, common, factor):
    bridge, pipeline = build(mode, common, factor)
    before = tree_hash(rng_state()), tree_hash(bridge.state_dict())
    binding = SelectionStateBinding(bridge, pipeline)
    descriptor = binding.describe()
    assert (tree_hash(rng_state()), tree_hash(bridge.state_dict())) == before
    assert descriptor["schema"] == FORMAT
    assert descriptor["qualification"] == QUALIFICATION
    assert descriptor["pipeline"]["interaction_query"] == mode
    assert {name: len(values) for name, values in descriptor["parameter_partitions"].items()} == {
        "writer": 20, "common_reader": 6, "interaction": 6,
    }
    names = [name for values in descriptor["parameter_partitions"].values() for name in values]
    assert len(names) == len(set(names)) == 32
    assert set(names) == set(dict(bridge.named_parameters()))
    assert descriptor["prototype"]["checkpoint_qualification"] == "NOT_ADMITTED_BY_V18_OWNER"
    descriptor["parameter_partitions"]["writer"].clear()
    descriptor["pipeline"]["interaction_query"] = "forged"
    assert binding.describe()["pipeline"]["interaction_query"] == mode
    assert len(binding.describe()["parameter_partitions"]["writer"]) == 20


@pytest.mark.parametrize("profile", ["all_frozen", "toy26", "one_frozen", "bf16", "eval"])
def test_nonproduction_trainability_dtype_or_training_profile_rejected(profile):
    bridge, pipeline = build()
    if profile == "all_frozen":
        bridge.requires_grad_(False)
    elif profile == "toy26":
        bridge.common.requires_grad_(False)
        bridge.common.writer.requires_grad_(True)
    elif profile == "one_frozen":
        bridge.up.weight.requires_grad_(False)
    elif profile == "bf16":
        bridge.bfloat16()
    else:
        bridge.eval()
    with pytest.raises(ValueError):
        SelectionStateBinding(bridge, pipeline)


MUTATIONS = (
    "mode", "fraction", "cap", "writer_steps", "writer_mode", "epsilon", "typed_dropout",
    "training", "module", "parameter", "storage_only", "shared_storage", "alias", "buffer",
    "nonpersistent_buffer", "unregistered_tensor", "callback", "method", "validator",
    "hook", "parameter_hook", "parameter_post_accumulate_hook", "requires_grad", "extra_policy",
)


def mutate(bridge, mutation):
    if mutation == "mode":
        bridge.mode = "raw_matched_control"
    elif mutation == "fraction":
        bridge.interaction_fraction = 0.5
    elif mutation == "cap":
        bridge.max_delta_norm = 2
    elif mutation == "writer_steps":
        bridge.common.writer.steps = 2
    elif mutation == "writer_mode":
        bridge.common.writer.mode = "projected_sequence"
    elif mutation == "epsilon":
        bridge.query_norm.eps = 0.01
    elif mutation == "typed_dropout":
        bridge.attention.dropout = False
    elif mutation == "training":
        bridge.common.writer.eval()
    elif mutation == "module":
        bridge.query_projection = copy.deepcopy(bridge.query_projection)
    elif mutation == "parameter":
        bridge.query_projection.weight = torch.nn.Parameter(bridge.query_projection.weight.clone())
    elif mutation == "storage_only":
        bridge.query_projection.weight.data = bridge.query_projection.weight.detach().clone()
    elif mutation == "shared_storage":
        bridge.query_projection.weight = torch.nn.Parameter(bridge.common.query_projection.weight)
    elif mutation == "alias":
        bridge.query_projection.weight = bridge.common.query_projection.weight
    elif mutation in ("buffer", "nonpersistent_buffer"):
        bridge.register_buffer("extra", torch.zeros(1), persistent=mutation == "buffer")
    elif mutation == "unregistered_tensor":
        bridge.extra = torch.zeros(1)
    elif mutation == "callback":
        bridge.extra = lambda: None
    elif mutation == "method":
        bridge.parts = types.MethodType(lambda self, *args: None, bridge)
    elif mutation == "validator":
        bridge._validate_queries = types.MethodType(lambda self, *args: None, bridge)
    elif mutation == "hook":
        bridge.up.register_forward_hook(lambda *args: None)
    elif mutation == "parameter_hook":
        bridge.up.weight.register_hook(lambda gradient: gradient * 0)
    elif mutation == "parameter_post_accumulate_hook":
        bridge.up.weight.register_post_accumulate_grad_hook(lambda parameter: None)
    elif mutation == "requires_grad":
        bridge.query_norm.bias.requires_grad_(False)
    else:
        bridge.extra_policy = {"secret": torch.zeros(1)}


@pytest.mark.parametrize("mutation", MUTATIONS)
def test_live_reader_mutations_rejected_without_forward(mutation):
    bridge, pipeline = build()
    binding = SelectionStateBinding(bridge, pipeline)
    mutate(bridge, mutation)
    with pytest.raises(ValueError):
        binding.validate()


@pytest.mark.parametrize("mutation", [
    "shared_storage", "alias", "buffer", "nonpersistent_buffer", "unregistered_tensor",
    "callback", "method", "validator", "hook", "parameter_hook",
    "parameter_post_accumulate_hook", "extra_policy", "typed_dropout",
])
def test_noncanonical_initial_reader_is_rejected(mutation):
    bridge, pipeline = build()
    mutate(bridge, mutation)
    with pytest.raises(ValueError):
        SelectionStateBinding(bridge, pipeline)


@pytest.mark.parametrize("mutation", [
    "mode", "bridge", "adapter", "callback", "tensor", "call_method", "describe_method",
])
def test_pipeline_policy_identity_and_instance_state_rejected(mutation):
    bridge, pipeline = build()
    binding = SelectionStateBinding(bridge, pipeline)
    if mutation == "mode":
        pipeline.mode = "final"
    elif mutation == "bridge":
        pipeline.bridge = copy.deepcopy(bridge)
    elif mutation == "adapter":
        pipeline.adapter = NoExecutionAdapter()
    elif mutation == "callback":
        pipeline.callback = lambda: None
    elif mutation == "tensor":
        pipeline.query = torch.zeros(1)
    elif mutation == "call_method":
        pipeline.__call__ = lambda *args: None
    else:
        pipeline.describe = lambda: {}
    with pytest.raises(ValueError):
        binding.validate()


@pytest.mark.parametrize("target", [
    "operand_reader_query", "validate_operand_span", "validate_token_tuple", "native_query",
    "operand_ids", "operand_validator", "reader_validator", "class_call", "class_modes",
    "grammar",
])
def test_class_and_query_helper_replacement_is_rejected(monkeypatch, target):
    bridge, pipeline = build()
    binding = SelectionStateBinding(bridge, pipeline)
    def replacement(*args, **kwargs):
        return None

    if target in ("operand_reader_query", "validate_operand_span", "validate_token_tuple"):
        monkeypatch.setattr(pipeline_module, target, replacement)
    elif target == "native_query":
        monkeypatch.setattr(native_module.NativeWorkspacePipeline, "query", replacement)
    elif target == "operand_ids":
        monkeypatch.setattr(operand_module, "_ids", replacement)
    elif target == "operand_validator":
        monkeypatch.setattr(operand_module.OperandSpan, "__post_init__", replacement)
    elif target == "reader_validator":
        monkeypatch.setattr(
            reader_module.SelectionWorkspaceBridge, "_validate_queries", replacement
        )
    elif target == "class_call":
        monkeypatch.setattr(SelectionWorkspacePipeline, "__call__", replacement)
    elif target == "class_modes":
        monkeypatch.setattr(SelectionWorkspacePipeline, "MODES", ["final"])
    else:
        monkeypatch.setattr(operand_module, "_GRAMMARS", ())
    with pytest.raises(ValueError):
        binding.validate()


def test_parameter_values_can_change_but_descriptor_and_storage_cannot():
    bridge, pipeline = build()
    binding = SelectionStateBinding(bridge, pipeline)
    with torch.no_grad():
        bridge.up.weight.fill_(0.01)
    binding.validate()
    binding._descriptor["qualification"] = "claimed-pass"
    with pytest.raises(ValueError, match="contract mutated"):
        binding.validate()


def test_initial_pipeline_callback_rejected_before_callback_can_execute():
    bridge, pipeline = build()
    pipeline.describe = lambda: pytest.fail("Unowned descriptor callback executed")
    with pytest.raises(ValueError, match="instance state"):
        SelectionStateBinding(bridge, pipeline)


@pytest.mark.parametrize("already_bound", [False, True])
def test_same_pattern_and_flags_do_not_admit_fake_grammar_implementation(
    monkeypatch, already_bound
):
    bridge, pipeline = build()
    binding = SelectionStateBinding(bridge, pipeline) if already_bound else None
    original = operand_module._GRAMMARS[0]

    class FakeGrammar:
        pattern = original.pattern
        flags = original.flags

        def fullmatch(self, _text):
            raise AssertionError("Unowned regex implementation must not execute")

    monkeypatch.setattr(
        operand_module, "_GRAMMARS", (FakeGrammar(), *operand_module._GRAMMARS[1:])
    )
    with pytest.raises(ValueError, match="grammar changed"):
        if binding is None:
            SelectionStateBinding(bridge, pipeline)
        else:
            binding.validate()


def test_exact_classes_only_and_historical_whitelists_remain_unchanged():
    class NewReader(SelectionWorkspaceBridge):
        pass

    class NewPipeline(SelectionWorkspacePipeline):
        pass

    bridge, pipeline = build()
    attributes = dict(historical._ATTRIBUTES)
    SelectionStateBinding(bridge, pipeline)
    assert historical._ATTRIBUTES == attributes and SelectionWorkspaceBridge not in attributes
    with pytest.raises(ValueError):
        historical.SlotContrastStateBinding(bridge)
    with pytest.raises(ValueError):
        _ReaderGuard(bridge)
    with pytest.raises(ValueError):
        SelectionStateBinding(NewReader(bridge.common), pipeline)
    with pytest.raises(ValueError):
        SelectionStateBinding(bridge, NewPipeline(bridge, pipeline.adapter, "final"))
