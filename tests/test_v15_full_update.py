from __future__ import annotations

import copy
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch
from transformers import MistralConfig, MistralForCausalLM

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import probe_v15_full_update_backward as probe  # noqa: E402
import run_v15_5_native_answer as frozen_runner  # noqa: E402

from latent_workspace_ft_v10.engine import (  # noqa: E402
    _CPUGradientAccumulator,
    enable_gradient_checkpointing,
)
from latent_workspace_ft_v10.precision_bridge import PrecisionAwareWorkspaceBridge  # noqa: E402
from latent_workspace_ft_v10.reader_query import QuestionSpan  # noqa: E402
from latent_workspace_ft_v10.v15_5_learner import native_answer_terms  # noqa: E402
from latent_workspace_ft_v10.v15_full_update import (  # noqa: E402
    MistralLiveFeatures,
    TrainableNativeWorkspaceReadout,
    full_native_answer_terms,
    full_parameter_ownership,
    validate_full_optimizer_ownership,
)
from latent_workspace_ft_v10.v15_pipeline import NativeWorkspacePipeline  # noqa: E402
from latent_workspace_ft_v10.v15_readout import NativeWorkspaceReadout  # noqa: E402


@pytest.fixture(autouse=True)
def threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(previous)


def tiny(dtype=torch.float32, *, up_nonzero=False):
    torch.manual_seed(47)
    config = MistralConfig(
        vocab_size=43,
        hidden_size=16,
        intermediate_size=32,
        num_hidden_layers=2,
        num_attention_heads=4,
        num_key_value_heads=2,
        max_position_embeddings=64,
        attention_dropout=0.0,
        pad_token_id=0,
        sliding_window=None,
        use_cache=False,
    )
    config._attn_implementation = "eager"
    base = MistralForCausalLM(config).to(dtype).train()
    bridge = PrecisionAwareWorkspaceBridge(16, workspace_dim=8, heads=2, slots=3, max_delta_norm=1)
    if up_nonzero:
        torch.nn.init.normal_(bridge.up.weight, std=0.1)
    pipe = NativeWorkspacePipeline(bridge, TrainableNativeWorkspaceReadout(base.lm_head), "final")
    return base, bridge, pipe


SPAN = QuestionSpan("A?", 0, 2, (1, 2), (1, 4, 5), "tiny")


class Store:
    def __init__(self, base, observer=None):
        self.features = MistralLiveFeatures(base, 1, observer)
        self.records = [{"answers": [[0, 1] * 4, [1, 0] + [0, 1] * 3]} for _ in range(2)]
        row = {"prompt_ids": list(SPAN.prefix_ids), "candidate_ids": [6, 7], "span": asdict(SPAN)}
        self.renderings = {(w, q): copy.deepcopy(row) for w in range(2) for q in range(8)}

    def get(self, ids):
        return self.features.prefix(ids)

    def write(self, bridge, world, side):
        ids = (1, 8, 9) if side == 0 else (1, 9, 8) if side == 1 else (1, 10, 11)
        value = self.features.context(ids)
        return bridge.write_memory(value, torch.ones(value.shape[:2], dtype=torch.long))


CONTRACT = {
    "donor_margin": 0.25,
    "direction_weight": 0.25,
    "stability_weight": 0.25,
    "unrelated_weight": 0.25,
    "residual_penalty": 0.001,
}


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_trainable_readout_reuses_exact_frozen_forward(dtype):
    base, _, pipe = tiny(dtype)
    hidden = MistralLiveFeatures(base, 1).prefix(SPAN.prefix_ids)
    delta = torch.randn(1, 1, 16, requires_grad=True)
    frozen_head = copy.deepcopy(base.lm_head).requires_grad_(False)
    actual = pipe.readout(hidden, delta)
    reference = NativeWorkspaceReadout(frozen_head)(hidden.detach(), delta.detach())
    assert torch.equal(actual.logits, reference.logits)
    actual.cross_entropy(torch.tensor([6])).backward()
    assert base.lm_head.weight.grad.count_nonzero() > 0
    assert delta.grad.count_nonzero() > 0
    with pytest.raises(ValueError, match="frozen"):
        NativeWorkspaceReadout(base.lm_head)
    with pytest.raises(ValueError, match="trainable"):
        TrainableNativeWorkspaceReadout(frozen_head)


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_zero_matches_current_base_before_and_after_tiny_parameter_change(dtype):
    base, bridge, pipe = tiny(dtype, up_nonzero=True)
    features = MistralLiveFeatures(base, 1)
    ids = torch.tensor([SPAN.prefix_ids])
    original = None
    for changed in (False, True):
        if changed:
            with torch.no_grad():
                base.model.norm.weight[0].add_(0.5)
                base.model.embed_tokens.weight[1, 0].add_(0.5)
        hidden = features.prefix(SPAN.prefix_ids)
        memory, mask = bridge.write_memory(features.context((1, 8, 9)), torch.ones(1, 3))
        value = pipe(hidden, torch.zeros_like(memory), mask, prefix_ids=SPAN.prefix_ids, span=SPAN)
        ordinary = base(ids, attention_mask=torch.ones_like(ids), use_cache=False).logits
        assert torch.equal(value.readout.logits, ordinary)
        if original is None:
            original = ordinary.detach().clone()
        else:
            assert not torch.equal(ordinary, original)
    assert not hasattr(features, "cache")


@pytest.mark.parametrize("checkpointed", [False, True])
@pytest.mark.parametrize("up_nonzero", [False, True])
def test_full_base_and_memory_routes_backward(checkpointed, up_nonzero):
    base, bridge, pipe = tiny(up_nonzero=up_nonzero)
    if checkpointed:
        enable_gradient_checkpointing(base)
    routes = probe.RouteGradients()
    store = Store(base, routes.observe)
    handle = bridge.query_projection.register_forward_pre_hook(
        lambda _module, args: routes.observe("query_to_reader", args[0])
    )
    before = {k: v.detach().clone() for k, v in base.state_dict().items()}
    loss, terms = probe.pair_objective(pipe, store, 0, 0, CONTRACT, 0.0)
    assert set(terms) == {
        "answer_ce",
        "eos_ce",
        "donor_hinge",
        "unaffected_gap_square",
        "unrelated_gap_square",
        "residual_norm_square",
    }
    loss.backward()
    handle.remove()
    for name, parameter in base.named_parameters():
        assert parameter.grad is not None, name
        assert torch.isfinite(parameter.grad).all(), name
        assert parameter.grad.count_nonzero() > 0, name
    for route in ("context_to_writer", "query_to_reader"):
        rows = [r for r in routes.rows if r["route"] == route]
        assert rows and all(r["backward_calls"] == 1 for r in rows)
        assert any(r["nonzero_elements"] > 0 for r in rows) == up_nonzero
    assert all(torch.equal(v, base.state_dict()[k]) for k, v in before.items())


def terms_inputs(base, bridge):
    features = MistralLiveFeatures(base, 1)
    memory, mask = bridge.write_memory(features.context((1, 8, 9)), torch.ones(1, 3))
    return (
        memory,
        mask,
        {
            "normalized_prefix": features.prefix(SPAN.prefix_ids),
            "normalized_completion": features.prefix(SPAN.prefix_ids + (6,)),
            "prefix_ids": SPAN.prefix_ids,
            "completion_prefix_ids": SPAN.prefix_ids + (6,),
            "span": SPAN,
            "answer_token_id": 6,
            "eos_token_id": 2,
        },
    )


@pytest.mark.parametrize("kind", ["prefix", "completion", "detached", "memory", "answer", "eos"])
def test_full_supervision_fails_closed(kind):
    base, bridge, pipe = tiny()
    memory, mask, kwargs = terms_inputs(base, bridge)
    if kind == "prefix":
        kwargs["prefix_ids"] = (1, 4, 4)
    elif kind == "completion":
        kwargs["completion_prefix_ids"] = SPAN.prefix_ids + (7,)
    elif kind == "detached":
        kwargs["normalized_prefix"] = kwargs["normalized_prefix"].detach()
    elif kind == "memory":
        memory = memory.detach()
    elif kind == "answer":
        kwargs["answer_token_id"] = True
    else:
        kwargs["eos_token_id"] = 6
    with pytest.raises(ValueError):
        full_native_answer_terms(pipe, memory, mask, **kwargs)


def test_answer_label_changes_only_completion_not_answer_forward():
    base, bridge, pipe = tiny(up_nonzero=True)
    memory, mask, kwargs = terms_inputs(base, bridge)
    first = full_native_answer_terms(pipe, memory, mask, **kwargs)
    kwargs.update(
        answer_token_id=7,
        completion_prefix_ids=SPAN.prefix_ids + (7,),
        normalized_completion=MistralLiveFeatures(base, 1).prefix(SPAN.prefix_ids + (7,)),
    )
    second = full_native_answer_terms(pipe, memory, mask, **kwargs)
    assert torch.equal(first.answer_output.readout.logits, second.answer_output.readout.logits)
    assert not torch.equal(
        first.completion_output.readout.logits, second.completion_output.readout.logits
    )


@pytest.mark.parametrize("eos_weight", [0.0, 1.0])
def test_complete_batch_reductions_match_frozen_source(eos_weight):
    base, bridge, pipe = tiny(up_nonzero=True)
    live = Store(base)

    class FrozenStore:
        records, renderings = live.records, live.renderings

        def get(self, ids):
            return live.get(ids).detach()

        def write(self, current_bridge, world, side):
            # The loss equality check compares identical features and weights.
            return live.write(current_bridge, world, side)

    frozen = NativeWorkspacePipeline(
        bridge, NativeWorkspaceReadout(copy.deepcopy(base.lm_head).requires_grad_(False)), "final"
    )
    totals = dict.fromkeys(
        (
            "answer_ce",
            "eos_ce",
            "donor_hinge",
            "unaffected_gap_square",
            "unrelated_gap_square",
            "residual_norm_square",
        ),
        0.0,
    )
    for w in range(2):
        for q in range(8):
            old_loss, old_terms = frozen_runner.pair_objective(
                frozen, FrozenStore(), w, q, CONTRACT, eos_weight
            )
            new_loss, new_terms = probe.pair_objective(pipe, live, w, q, CONTRACT, eos_weight)
            assert torch.equal(old_loss, new_loss)
            for key in totals:
                assert torch.equal(old_terms[key], new_terms[key])
                totals[key] += float(new_terms[key].detach())
    assert totals["answer_ce"] > 0


def test_old_feature_detachment_contract_remains():
    base, bridge, pipe = tiny()
    memory, mask, kwargs = terms_inputs(base, bridge)
    frozen = NativeWorkspacePipeline(
        bridge, NativeWorkspaceReadout(copy.deepcopy(base.lm_head).requires_grad_(False)), "final"
    )
    with pytest.raises(ValueError, match="detached and frozen"):
        native_answer_terms(frozen, memory, mask, **kwargs)


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("checkpointed", [False, True])
def test_zero_path_base_gradients_match_ordinary_model(dtype, checkpointed):
    base, _, pipe = tiny(dtype)
    ordinary = copy.deepcopy(base)
    if checkpointed:
        enable_gradient_checkpointing(base)
        enable_gradient_checkpointing(ordinary)
    ids = torch.tensor([SPAN.prefix_ids])
    hidden = MistralLiveFeatures(base, 1).prefix(SPAN.prefix_ids)
    value = pipe.readout(hidden, torch.zeros(1, 1, 16))
    value.cross_entropy(torch.tensor([6])).backward()
    native = ordinary(ids, attention_mask=torch.ones_like(ids), use_cache=False).logits
    torch.nn.functional.cross_entropy(native[:, -1].float(), torch.tensor([6])).backward()
    assert torch.equal(value.logits, native)
    for (name, parameter), (reference_name, reference) in zip(
        base.named_parameters(), ordinary.named_parameters(), strict=True
    ):
        assert name == reference_name
        assert torch.equal(parameter.grad, reference.grad), name


def test_parameter_aliases_and_invalid_optimizer_ownership():
    base, bridge, _ = tiny()
    base.lm_head.weight = base.model.embed_tokens.weight
    named = full_parameter_ownership(base, bridge)
    assert len(named) == len({id(p) for _, p in named})
    fake = SimpleNamespace(param_groups=[{"params": [p for _, p in named]}])
    assert validate_full_optimizer_ownership(base, bridge, fake)["parameter_tensors"] == len(named)
    for parameters in ([p for _, p in named][:-1], [p for _, p in named] + [named[0][1]]):
        with pytest.raises(ValueError, match="exactly once"):
            validate_full_optimizer_ownership(
                base, bridge, SimpleNamespace(param_groups=[{"params": parameters}])
            )
    bridge.up.weight.requires_grad_(False)
    with pytest.raises(ValueError, match="frozen"):
        full_parameter_ownership(base, bridge)


def test_cpu_accumulation_matches_independent_same_order_clone_add():
    base, bridge, pipe = tiny(up_nonzero=True)
    store = Store(base)
    named = full_parameter_ownership(base, bridge)
    accumulator = _CPUGradientAccumulator(named, merge_device="cpu")
    expected = {}
    for query in (0, 1, 2):
        loss, _ = probe.pair_objective(pipe, store, 0, query, CONTRACT, 0.0)
        loss.backward()
        probe.add_cpu_reference(expected, named)
        accumulator.spill()
        assert all(p.grad is None for _, p in named)
    receipt = accumulator.restore()
    assert receipt["spill_count"] == 3
    assert len(probe.verify_cpu_reference(expected, named)) == len(named)
    named[0][1].grad.add_(1)
    with pytest.raises(ValueError, match="accumulation differs"):
        probe.verify_cpu_reference(expected, named)


def test_frozen_backbone_cannot_masquerade_as_live_features():
    base, _, _ = tiny()
    base.requires_grad_(False)
    features = MistralLiveFeatures(base, 1)
    with pytest.raises(ValueError, match="lost their backbone"):
        features.prefix(SPAN.prefix_ids)


@pytest.mark.parametrize("ids", [(), (True,), (-1,), (43,), [1, 2]])
def test_invalid_live_token_inputs(ids):
    base, _, _ = tiny()
    with pytest.raises(ValueError, match="Token IDs"):
        MistralLiveFeatures(base, 1).prefix(ids)
