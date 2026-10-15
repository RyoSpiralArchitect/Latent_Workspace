"""Tiny native-layout engineering tests, not semantic/model-quality evidence."""

import copy
import os
import re

import pytest
import torch
from test_readout_adapters import FAMILIES, bridge, memory, model

from latent_workspace_ft_v10.adapted_workspace import (
    AdaptedWorkspacePipeline,
    adapted_answer_terms,
)
from latent_workspace_ft_v10.hf_readout_adapter import HFNativeReadoutAdapter
from latent_workspace_ft_v10.v16_slot_contrast import SlotContrastWorkspaceBridge
from latent_workspace_ft_v10.v18_operand_query import bind_operand_span
from latent_workspace_ft_v10.v18_selection_pipeline import SelectionWorkspacePipeline
from latent_workspace_ft_v10.v18_selection_reader import SelectionWorkspaceBridge
from latent_workspace_ft_v10.v18_window_learner import _ReaderGuard

DEVICE = os.environ.get("LATENT_SLOT_STATE_TEST_DEVICE", "cpu")


def native_model(family, dtype=torch.float32):
    return model(family, dtype).to(DEVICE)


def native_bridge():
    return bridge().to(DEVICE)


def native_memory():
    return tuple(value.to(DEVICE) for value in memory())


class TinyTokenizer:
    is_fast = True

    def encode(self, text, *, add_special_tokens):
        return list(range(1, len(list(re.finditer(r"\w+|[^\w\s]", text))) + 1))

    def __call__(self, text, **kwargs):
        return {
            "input_ids": self.encode(text, add_special_tokens=False),
            "offset_mapping": [m.span() for m in re.finditer(r"\w+|[^\w\s]", text)],
        }


def bound():
    raw = "Is Aster ranked above Beryl? Answer:"
    text = "Use facts.\n" + raw
    tokenizer = TinyTokenizer()
    return bind_operand_span(
        tokenizer, raw_query=raw, rendered_prefix=text,
        expected_prefix_ids=tokenizer.encode(text, add_special_tokens=False),
    )


@pytest.fixture(autouse=True)
def threads():
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_final_control_exact_native_output_and_all_gradients(family, dtype):
    torch.manual_seed(291)
    base = native_model(family, dtype).train()
    other_base = copy.deepcopy(base)
    old = SlotContrastWorkspaceBridge(native_bridge())
    with torch.no_grad():
        old.up.weight.normal_(std=0.2)
    new = SelectionWorkspaceBridge(copy.deepcopy(old.common))
    new.load_state_dict(old.state_dict(), strict=True)
    old_pipe = AdaptedWorkspacePipeline(old, HFNativeReadoutAdapter(base))
    new_pipe = SelectionWorkspacePipeline(new, HFNativeReadoutAdapter(other_base), "final")
    span = bound()
    mem, mask = native_memory()
    a = mem.clone().requires_grad_()
    b = mem.clone().requires_grad_()
    kwargs = dict(prefix_ids=span.prefix_ids, completion_prefix_ids=span.prefix_ids + (6,),
                  answer_token_id=6, eos_token_id=2)
    old_terms = adapted_answer_terms(old_pipe, a, mask, span=span.question_span, **kwargs)
    new_terms = adapted_answer_terms(new_pipe, b, mask, span=span, **kwargs)
    assert torch.equal(old_terms.objective(0.3), new_terms.objective(0.3))
    for key in ("answer_output", "completion_output"):
        left, right = getattr(old_terms, key), getattr(new_terms, key)
        assert torch.equal(left.readout.logits, right.readout.logits)
        assert torch.equal(right.common_query, right.interaction_query)
        assert torch.equal(left.delta, right.delta)
    old_terms.objective(0.3).backward()
    new_terms.objective(0.3).backward()
    assert torch.equal(a.grad, b.grad)
    for left, right in ((base, other_base), (old, new)):
        for (name, p), (other_name, q) in zip(left.named_parameters(), right.named_parameters()):
            assert name == other_name
            assert (p.grad is None) == (q.grad is None), name
            if p.grad is not None:
                assert torch.equal(p.grad, q.grad), name


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("mode", ["ordered_difference", "symmetric_mean"])
def test_native_identity_head_geometry_and_live_gradient(family, dtype, mode):
    torch.manual_seed(292)
    base = native_model(family, dtype).train()
    reader = SelectionWorkspaceBridge(native_bridge())
    with torch.no_grad():
        reader.up.weight.normal_(std=0.2)
    pipe = SelectionWorkspacePipeline(reader, HFNativeReadoutAdapter(base), mode)
    span = bound()
    mem, mask = native_memory()
    mem.requires_grad_()
    zero = pipe(span.prefix_ids, torch.zeros_like(mem), mask, span=span)
    ordinary = base(
        torch.tensor([span.prefix_ids], device=DEVICE), use_cache=False, logits_to_keep=0
    ).logits
    assert torch.equal(zero.readout.logits, ordinary)
    actual = pipe(span.prefix_ids, mem, mask, span=span)
    assert actual.readout.logits.shape == (1, len(span.prefix_ids), 41)
    assert actual.common_query.dtype == actual.interaction_query.dtype == torch.float32
    assert torch.equal(actual.transport.injection.original_last.float(), actual.common_query)
    actual.readout.cross_entropy(torch.tensor([6], device=DEVICE)).backward()
    assert mem.grad is not None and mem.grad.abs().sum() > 0
    assert reader.query_projection.weight.grad.abs().sum() > 0
    assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in base.parameters())


@pytest.mark.parametrize("mode", SelectionWorkspacePipeline.MODES)
def test_protocol_only_adapter_and_completion_anchor(mode):
    reader = SelectionWorkspaceBridge(native_bridge())
    span = bound()
    base_adapter = HFNativeReadoutAdapter(native_model("mistral"))

    class ProtocolOnly:
        vocabulary = 41

        def describe(self):
            return {"test": "protocol-only"}

        def read(self, ids, residual):
            return base_adapter.read(ids, residual)

    pipe = SelectionWorkspacePipeline(reader, ProtocolOnly(), mode)
    assert not hasattr(pipe, "_common_query")
    mem, mask = native_memory()
    for ids in (span.prefix_ids, span.prefix_ids + (6, 7)):
        out = pipe(ids, mem, mask, span=span)
        assert out.transport.prefix_ids == ids
        assert out.common_query.shape == out.interaction_query.shape == (1, 1, 16)
        assert torch.equal(out.common_query, out.transport.injection.original_last.float())
    assert pipe.describe()["checkpoint_qualification"] == "NOT_ADMITTED_BY_V18_OWNER"


def test_invalid_prefix_rejects_before_adapter_forward_and_owner_rejects_prototype():
    class NoForward:
        vocabulary = 41

        def read(self, *_):
            pytest.fail("invalid binding reached native forward")

    reader = SelectionWorkspaceBridge(native_bridge())
    pipe = SelectionWorkspacePipeline(reader, NoForward(), "final")
    span = bound()
    mem, mask = native_memory()
    for ids in (span.prefix_ids[:-1], (40,) + span.prefix_ids[1:]):
        with pytest.raises(ValueError, match="exact bound"):
            pipe(ids, mem, mask, span=span)
    with pytest.raises(ValueError, match="Unqualified reader class"):
        _ReaderGuard(reader)
