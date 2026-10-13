"""CPU synthetic-layout qualification only; no downloads or retained checkpoints."""

import copy
from dataclasses import replace

import pytest
import torch
from test_v14_model_binding import tiny_model
from torch import nn
from transformers import Gemma2Config, Gemma2ForCausalLM

from latent_workspace_ft_v10.adapted_workspace import (
    AdaptedWorkspacePipeline,
    adapted_answer_terms,
)
from latent_workspace_ft_v10.hf_readout_adapter import HFNativeReadoutAdapter
from latent_workspace_ft_v10.precision_bridge import PrecisionAwareWorkspaceBridge
from latent_workspace_ft_v10.reader_query import QuestionSpan
from latent_workspace_ft_v10.readout_transport import compare_transport, inject_last
from latent_workspace_ft_v10.v15_full_update import (
    MistralLiveFeatures,
    TrainableNativeWorkspaceReadout,
    full_native_answer_terms,
)
from latent_workspace_ft_v10.v15_pipeline import NativeWorkspacePipeline

FAMILIES = ("mistral", "gpt2", "olmo2", "gemma2")
DTYPES = (torch.float32, torch.bfloat16)
IDS = (1, 4, 5)
SPAN = QuestionSpan("A?", 0, 2, (1, 2), IDS, "tiny")


@pytest.fixture(autouse=True)
def threads():
    old = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(old)


def model(family, dtype=torch.float32):
    if family != "gemma2":
        return tiny_model(family).to(dtype).eval()
    torch.manual_seed(147)
    config = Gemma2Config(
        vocab_size=41,
        hidden_size=16,
        intermediate_size=32,
        num_hidden_layers=2,
        num_attention_heads=4,
        num_key_value_heads=2,
        head_dim=4,
        max_position_embeddings=32,
        attention_dropout=0.0,
        final_logit_softcapping=0.1,
        attn_logit_softcapping=50.0,
        query_pre_attn_scalar=4,
        sliding_window=8,
        pad_token_id=0,
        use_cache=False,
    )
    config._attn_implementation = "eager"
    return Gemma2ForCausalLM(config).to(dtype).eval()


def bridge():
    result = PrecisionAwareWorkspaceBridge(16, workspace_dim=8, heads=2, slots=3)
    nn.init.normal_(result.up.weight, std=0.1)
    return result


def memory():
    return torch.randn(1, 3, 8), torch.ones(1, 3, dtype=torch.long)


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("dtype", DTYPES)
@pytest.mark.parametrize("length", (1, 7))
def test_native_zero_exact_full_geometry_and_no_parameter_ownership(family, dtype, length):
    base = model(family, dtype)
    ids = tuple(range(1, length + 1))
    parameters = [(n, id(p), p.requires_grad) for n, p in base.named_parameters()]
    adapter = HFNativeReadoutAdapter(base)
    ordinary = base(
        input_ids=torch.tensor([ids]),
        attention_mask=torch.ones(1, length),
        use_cache=False,
        logits_to_keep=0,
    ).logits
    out = adapter.read(ids, lambda h: torch.zeros_like(h[:, -1:]).float())
    assert torch.equal(out.readout.logits, ordinary)
    assert out.head_logits.shape == out.readout.logits.shape == (1, length, 41)
    assert not out.injection.applied_delta.count_nonzero()
    assert parameters == [(n, id(p), p.requires_grad) for n, p in base.named_parameters()]
    assert not isinstance(adapter, nn.Module)
    assert not adapter.head._forward_hooks and not adapter.head._forward_pre_hooks
    assert adapter.describe()["normalizer_owner"] == "native_model_forward"


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("dtype", DTYPES)
@pytest.mark.parametrize("checkpointing", (False, True))
def test_nonzero_native_reference_and_backprop(family, dtype, checkpointing):
    base = model(family, dtype).train()
    reference = copy.deepcopy(base)
    if checkpointing:
        for value in (base, reference):
            value.gradient_checkpointing_enable(
                gradient_checkpointing_kwargs={"use_reentrant": False}
            )
    delta = torch.randn(1, 1, 16, requires_grad=True)
    reference_delta = delta.detach().clone().requires_grad_(True)

    # Independent explicit native-head intervention, not the implementation helper.
    def inject(_m, inputs):
        h = inputs[0]
        return (torch.cat((h[:, :-1], (h[:, -1:].float() + reference_delta).to(dtype)), 1),)

    handle = reference.get_output_embeddings().register_forward_pre_hook(inject)
    try:
        expected = reference(
            input_ids=torch.tensor([IDS]),
            attention_mask=torch.ones(1, 3),
            use_cache=False,
            logits_to_keep=0,
        ).logits
    finally:
        handle.remove()
    actual = HFNativeReadoutAdapter(base).read(IDS, lambda _: delta)
    assert torch.equal(actual.readout.logits, expected)
    targets = torch.tensor([7])
    actual.readout.cross_entropy(targets).backward()
    torch.nn.functional.cross_entropy(expected[:, -1].float(), targets).backward()
    assert torch.equal(delta.grad, reference_delta.grad)
    for (name, p), (other_name, other) in zip(
        base.named_parameters(), reference.named_parameters()
    ):
        assert name == other_name
        assert p.grad is not None and other.grad is not None, name
        assert torch.equal(p.grad, other.grad), name


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("full", (False, True))
def test_answer_eos_loss_and_generation_share_actual_logits(family, full):
    base = model(family).requires_grad_(full)
    reader = bridge()
    mem, mask = memory()
    mem.requires_grad_(True)
    pipe = AdaptedWorkspacePipeline(reader, HFNativeReadoutAdapter(base))
    answer = pipe(IDS, mem, mask, span=SPAN)
    terms = adapted_answer_terms(
        pipe,
        mem,
        mask,
        prefix_ids=IDS,
        completion_prefix_ids=IDS + (6,),
        span=SPAN,
        answer_token_id=6,
        eos_token_id=2,
    )
    assert torch.equal(answer.readout.logits, terms.answer_output.readout.logits)
    with torch.no_grad():
        decoded = pipe(IDS, mem, mask, span=SPAN)
        # One deterministic next-token decision, not a qualitative answer bank.
        assert torch.equal(
            decoded.readout.last_logits.argmax(-1),
            terms.answer_output.readout.last_logits.argmax(-1),
        )
    terms.objective(0.3).backward()
    assert mem.grad is not None and mem.grad.abs().sum() > 0
    assert reader.up.weight.grad.abs().sum() > 0
    assert reader.query_projection.weight.grad.abs().sum() > 0
    assert all((p.grad is not None) == full for p in base.parameters())


@pytest.mark.parametrize("dtype", DTYPES)
def test_mistral_legacy_objective_and_all_gradients_exact(dtype):
    original = model("mistral", dtype).train()
    changed = copy.deepcopy(original)
    old_bridge = bridge()
    new_bridge = copy.deepcopy(old_bridge)
    mem, mask = memory()
    old_mem = mem.clone().requires_grad_(True)
    new_mem = mem.clone().requires_grad_(True)
    old_pipe = NativeWorkspacePipeline(
        old_bridge, TrainableNativeWorkspaceReadout(original.lm_head), "final"
    )
    features = MistralLiveFeatures(original, 1)
    kwargs = dict(
        prefix_ids=IDS,
        completion_prefix_ids=IDS + (6,),
        span=SPAN,
        answer_token_id=6,
        eos_token_id=2,
    )
    old_terms = full_native_answer_terms(
        old_pipe,
        old_mem,
        mask,
        normalized_prefix=features.prefix(IDS),
        normalized_completion=features.prefix(IDS + (6,)),
        **kwargs,
    )
    new_terms = adapted_answer_terms(
        AdaptedWorkspacePipeline(new_bridge, HFNativeReadoutAdapter(changed)),
        new_mem,
        mask,
        **kwargs,
    )
    assert torch.equal(old_terms.objective(0.3), new_terms.objective(0.3))
    old_terms.objective(0.3).backward()
    new_terms.objective(0.3).backward()
    assert torch.equal(old_mem.grad, new_mem.grad)
    for old_module, new_module in ((original, changed), (old_bridge, new_bridge)):
        for (name, p), (_, q) in zip(old_module.named_parameters(), new_module.named_parameters()):
            assert (p.grad is None) == (q.grad is None), name
            if p.grad is not None:
                assert torch.equal(p.grad, q.grad), name


@pytest.mark.parametrize("family", FAMILIES)
def test_written_zero_identity_and_bound_query_extension(family):
    base = model(family)
    pipe = AdaptedWorkspacePipeline(bridge(), HFNativeReadoutAdapter(base), "mean_span")
    mem, mask = memory()
    for ids in (IDS, IDS + (6,)):
        actual = pipe(ids, torch.zeros_like(mem), mask, span=SPAN)
        expected = base(
            input_ids=torch.tensor([ids]), attention_mask=torch.ones(1, len(ids)), use_cache=False
        ).logits
        assert not actual.delta.count_nonzero()
        assert torch.equal(actual.readout.logits, expected)
    with pytest.raises(ValueError, match="exact bound"):
        pipe((1, 5, 4), mem, mask, span=SPAN)


def test_gemma_postprocess_is_preserved_and_not_mistaken_for_raw_head():
    adapter = HFNativeReadoutAdapter(model("gemma2"))
    left = adapter.read(IDS, lambda h: torch.zeros_like(h[:, -1:]).float())
    right = adapter.read(IDS, lambda h: torch.full_like(h[:, -1:], 0.2).float())
    assert not torch.equal(right.head_logits, right.readout.logits)
    expected = (right.head_logits / 0.1).tanh() * 0.1
    assert torch.equal(expected, right.readout.logits)
    probe = compare_transport(left, right, (6, 7), linear_weight=adapter.head.weight)
    assert probe["model_postprocessing_gap_residual"][0] != 0
    fields = (
        "intended_linear_gap_change_fp64",
        "input_cast_gap_residual",
        "head_arithmetic_gap_residual",
        "model_postprocessing_gap_residual",
    )
    total = sum(probe[key][0] for key in fields)
    assert total == pytest.approx(probe["native_published_gap_change"][0], abs=1e-15)
    assert not probe["fp64_probe_is_native_logits"]


def test_subgrid_residual_has_surrogate_gradient_not_forward_effect():
    normalized = torch.ones(1, 3, 4, dtype=torch.bfloat16)
    delta = torch.full((1, 1, 4), 1e-4, requires_grad=True)
    injection = inject_last(normalized, delta)
    assert torch.equal(injection.sequence, normalized)
    assert not injection.applied_delta.count_nonzero()
    injection.sequence.float().sum().backward()
    assert torch.equal(delta.grad, torch.ones_like(delta))


def test_pair_guard_rejects_wrong_weights_prefix_and_updated_model():
    adapter = HFNativeReadoutAdapter(model("mistral"))

    def residual(h):
        return torch.ones_like(h[:, -1:]).float() * 0.01

    before = adapter.read(IDS, residual)
    with pytest.raises(ValueError, match="captured native head"):
        compare_transport(before, before, (6, 7), linear_weight=adapter.head.weight.clone())
    with pytest.raises(ValueError, match="same prefix"):
        compare_transport(
            before, replace(before, prefix_ids=(1,)), (6, 7), linear_weight=adapter.head.weight
        )
    with torch.no_grad():
        adapter.head.weight.add_(0.001)
    after = adapter.read(IDS, residual)
    with pytest.raises(ValueError, match="model version"):
        compare_transport(before, after, (6, 7), linear_weight=adapter.head.weight)


@pytest.mark.parametrize("failure", ("exception", "recursive", "wrong_shape", "nonfinite"))
def test_temporary_hooks_cleaned_on_failure(failure):
    base = model("mistral")
    adapter, second = HFNativeReadoutAdapter(base), HFNativeReadoutAdapter(base)

    def residual(h):
        if failure == "exception":
            raise RuntimeError("deliberate")
        if failure == "recursive":
            return second.read(IDS, lambda x: x).readout.logits
        if failure == "wrong_shape":
            return torch.zeros(1)
        return torch.full_like(h[:, -1:], float("nan")).float()

    with pytest.raises((ValueError, RuntimeError)):
        adapter.read(IDS, residual)
    assert not adapter.head._forward_hooks and not adapter.head._forward_pre_hooks
    adapter.read(IDS, lambda h: torch.zeros_like(h[:, -1:]).float())


def test_reject_unknown_layout_mutation_dropout_hooks_and_invalid_tokens():
    class Impostor(type(model("mistral"))):
        pass

    with pytest.raises(TypeError, match="Unqualified"):
        HFNativeReadoutAdapter(Impostor(model("mistral").config))
    base = model("gpt2").train()
    base.transformer.drop.p = 0.2
    with pytest.raises(ValueError, match="dropout"):
        HFNativeReadoutAdapter(base)
    adapter = HFNativeReadoutAdapter(model("mistral"))
    for ids in ([1, 2], (), (True,), (-1,), (41,)):
        with pytest.raises(ValueError, match="Token IDs"):
            adapter.read(ids, lambda h: h)
    handle = adapter.head.register_forward_hook(lambda *args: None)
    with pytest.raises(ValueError, match="already has hooks"):
        adapter.read(IDS, lambda h: h)
    handle.remove()
    adapter.base.config.vocab_size += 1
    with pytest.raises(ValueError, match="configuration changed"):
        adapter.read(IDS, lambda h: h)


@pytest.mark.parametrize("family", FAMILIES)
def test_external_autocast_does_not_change_declared_native_route(family):
    adapter = HFNativeReadoutAdapter(model(family))

    def residual(h):
        return torch.ones_like(h[:, -1:]).float() * 0.01

    expected = adapter.read(IDS, residual)
    with torch.autocast("cpu", dtype=torch.bfloat16):
        actual = adapter.read(IDS, residual)
    assert torch.equal(actual.readout.logits, expected.readout.logits)


def test_core_accepts_protocol_not_concrete_model_adapter():
    # A backend decorator is enough; the core must not reach through to .base/head.
    class ProtocolOnly:
        def __init__(self, concrete):
            self._delegate = concrete

        @property
        def vocabulary(self):
            return self._delegate.vocabulary

        def describe(self):
            return self._delegate.describe()

        def read(self, prefix_ids, residual):
            return self._delegate.read(prefix_ids, residual)

    pipe = AdaptedWorkspacePipeline(bridge(), ProtocolOnly(HFNativeReadoutAdapter(model("gpt2"))))
    mem, mask = memory()
    terms = adapted_answer_terms(
        pipe,
        mem,
        mask,
        prefix_ids=IDS,
        completion_prefix_ids=IDS + (6,),
        span=SPAN,
        answer_token_id=6,
        eos_token_id=2,
    )
    terms.objective(0.3).backward()


@pytest.mark.parametrize(
    "bad",
    (
        {"completion_prefix_ids": IDS + (7,)},
        {"answer_token_id": True},
        {"eos_token_id": 6},
        {"prefix_ids": IDS + (8,)},
    ),
)
def test_supervision_rejected_before_any_native_forward(bad):
    class NoForward:
        vocabulary = 41

        def read(self, *args):
            pytest.fail("Invalid supervision reached the native forward")

    pipe = AdaptedWorkspacePipeline(bridge(), NoForward())
    mem, mask = memory()
    args = dict(
        prefix_ids=IDS,
        completion_prefix_ids=IDS + (6,),
        span=SPAN,
        answer_token_id=6,
        eos_token_id=2,
    )
    args.update(bad)
    with pytest.raises(ValueError):
        adapted_answer_terms(pipe, mem, mask, **args)
