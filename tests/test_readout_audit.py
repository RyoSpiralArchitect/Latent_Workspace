"""Actual native sampler/forced-prefix parity on portable tiny hosts, not quality."""

import copy
import json
import os

import pytest
import torch
from test_latent_workspace_stack import host_model

from latent_workspace import native_evaluation as ev
from latent_workspace import readout_audit as audit
from latent_workspace.native_memory import NativeMemoryCausalLM
from latent_workspace.optimizer_state import tree_hash


@pytest.fixture(autouse=True)
def threads():
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


def graph(kind="mistral", dtype=torch.float32):
    return (
        NativeMemoryCausalLM(host_model(kind), cut=1)
        .to(device=os.environ.get("LTWS_TEST_DEVICE", "cpu"), dtype=dtype)
        .eval()
    )


def policy(temperature=0.7):
    return dict(seed=17, cap=3, eos=42, temperature=temperature, top_p=0.9, guard=lambda _: None)


def spec():
    return audit.ReadoutSpec((1, 8), (7, 9, 2), ("content", "binding", "stop"), 2, (4, 7))


@pytest.mark.parametrize("kind", ["mistral", "olmo2", "gpt2", "scratch"])
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("memory", [(), (3, 5)])
@pytest.mark.parametrize("temperature", [0.0, 0.7])
def test_observation_preserves_actual_tokens_weights_gradients_and_rng(
    kind, dtype, memory, temperature
):
    model = graph(kind, dtype)
    model.requires_grad_(True)
    before = tree_hash(model.state_dict())
    rng = torch.get_rng_state().clone()
    cuda_rng = torch.cuda.get_rng_state().clone() if next(model.parameters()).is_cuda else None
    plain = ev.generate(model, [1, 8], list(memory), **policy(temperature))
    result = audit.trace_generation(model, (1, 8), memory, probes=(4, 7), **policy(temperature))
    assert result["generation"] == plain
    assert result["native_forward_calls"] == len(plain["token_ids"])
    assert [r["target"]["token_id"] for r in result["rows"]] == plain["token_ids"]
    assert all(r["stage"] == "unclassified" for r in result["rows"])
    assert tree_hash(model.state_dict()) == before
    assert all(p.grad is None for p in model.parameters())
    assert torch.equal(rng, torch.get_rng_state())
    if cuda_rng is not None:
        assert torch.equal(cuda_rng, torch.cuda.get_rng_state())


@pytest.mark.parametrize("kind", ["mistral", "olmo2", "gpt2", "scratch"])
@pytest.mark.parametrize("memory", [(), (3, 5)])
def test_forced_trace_matches_generation_on_its_own_tokens(kind, memory):
    model = graph(kind)
    gen = audit.trace_generation(model, (1, 8), memory, probes=(4,), **policy())
    tokens = tuple(gen["generation"]["token_ids"])
    reference = audit.ReadoutSpec((1, 8), tokens, ("unclassified",) * len(tokens), 42, (4,))
    forced = audit.trace_continuation(model, reference, memory, guard=lambda _: None)
    assert forced["rows"] == gen["rows"]
    assert forced["new_sequences"] == 0 and gen["new_sequences"] == 1
    assert audit.compare_fixed(forced, json.loads(json.dumps(forced)))["tokens"] == len(tokens)


def test_observation_uses_only_copied_cpu_scores(monkeypatch):
    model = graph()
    plain = ev.generate(model, [1, 8], [], **policy())
    seen = []
    original = audit.token_readout

    def observe(logits, **kw):
        assert logits.device.type == "cpu"
        assert logits.dtype == torch.float32 and not logits.requires_grad
        result = original(logits, **kw)
        logits.fill_(float("nan"))
        seen.append(kw["target"])
        return result

    monkeypatch.setattr(audit, "token_readout", observe)
    assert audit.trace_generation(model, (1, 8), (), **policy())["generation"] == plain
    assert len(seen) == plain["generated_tokens"]


def test_ties_native_full_vocab_eos_and_margin_are_distinct():
    scores = torch.tensor([9.0, 2.0, 2.0, 1.0, -3.0], requires_grad=True)
    before = scores.clone()
    row = audit.token_readout(scores, target=1, eos=4, probes=(0, 2))
    assert torch.equal(scores, before)
    assert row["argmax"] == 0 and row["target"]["rank"] == 2
    assert row["target"]["ties"] == 2 and row["target"]["margin_vs_best_other"] == -7
    assert row["eos"]["rank"] == 5 and row["probes"][0]["margin_vs_best_other"] == 7
    assert row["target"]["logprob"] == float(scores.detach().log_softmax(-1)[1])
    ties = audit.token_readout(torch.tensor([9.0, 9.0, 1.0]), target=0, eos=2)
    assert ties["argmax_ties"] == 2 and ties["target"]["margin_vs_best_other"] == 0


@pytest.mark.parametrize(
    "bad", [torch.tensor([float("nan"), 1.0]), torch.ones(1), torch.ones(1, 3)]
)
def test_bad_native_logits_fail(bad):
    with pytest.raises(ValueError, match="vocabulary"):
        audit.token_readout(bad, target=0, eos=0)


@pytest.mark.parametrize("change", ["prefix", "continuation", "stage", "probes", "eos"])
def test_changed_reference_is_not_a_matched_prefix_contrast(change):
    model = graph()
    first = audit.trace_continuation(model, spec(), guard=lambda _: None)
    kwargs = dict(
        prefix=(1, 8),
        continuation=(7, 9, 2),
        stages=("content", "binding", "stop"),
        eos=2,
        probes=(4, 7),
    )
    replacements = dict(
        prefix=(1, 6),
        continuation=(7, 6, 2),
        stage=("format", "binding", "stop"),
        probes=(4,),
        eos=3,
    )
    kwargs["stages" if change == "stage" else change] = replacements[change]
    second = audit.trace_continuation(model, audit.ReadoutSpec(**kwargs), guard=lambda _: None)
    with pytest.raises(ValueError, match="Identical"):
        audit.compare_fixed(first, second)


@pytest.mark.parametrize(
    "damage", ["missing", "reorder", "hash", "target", "stage", "nan", "dtype", "vocab"]
)
def test_partial_or_misaligned_receipts_are_rejected(damage):
    left = audit.trace_continuation(graph(), spec(), guard=lambda _: None)
    right = copy.deepcopy(left)
    if damage == "missing":
        right["rows"].pop()
    elif damage == "reorder":
        right["rows"].reverse()
    elif damage == "hash":
        right["spec_sha256"] = "0" * 64
    elif damage == "target":
        right["rows"][0]["target"]["token_id"] = 8
    elif damage == "stage":
        right["rows"][0]["stage"] = "format"
    elif damage == "nan":
        right["rows"][0]["eos"]["logprob"] = float("nan")
    elif damage == "dtype":
        right["rows"][0]["native_dtype"] = "torch.bfloat16"
    else:
        right["rows"][0]["vocabulary"] = 42
    with pytest.raises(ValueError):
        audit.compare_fixed(left, right)


def test_free_trajectory_is_not_fixed_token_evidence():
    model = graph()
    forced = audit.trace_continuation(model, spec(), guard=lambda _: None)
    free = audit.trace_generation(model, (1, 8), (), **policy())
    with pytest.raises(ValueError, match="fixed-continuation"):
        audit.compare_fixed(forced, free)


def test_memory_intervention_keeps_query_history_and_stage_denominators():
    model = graph()
    left = audit.trace_continuation(model, spec(), (3, 5), guard=lambda _: None)
    right = audit.trace_continuation(model, spec(), (3, 6), guard=lambda _: None)
    contrast = audit.compare_fixed(left, right)
    assert contrast["tokens"] == 3
    assert sum(r["tokens"] for r in contrast["stages"].values()) == 3
    assert contrast["left_memory_sha256"] != contrast["right_memory_sha256"]
    identical = audit.compare_fixed(left, left)
    assert all(r["target_logprob"] == r["eos_logprob"] == 0 for r in identical["deltas"])


def test_future_reference_tokens_never_enter_an_earlier_forward():
    model = graph()
    a = audit.trace_continuation(model, spec(), guard=lambda _: None)
    changed_future = audit.ReadoutSpec((1, 8), (7, 5, 6), ("content", "binding", "stop"), 2, (4, 7))
    b = audit.trace_continuation(model, changed_future, guard=lambda _: None)
    assert a["rows"][0] == b["rows"][0]
    assert a["rows"][1]["query_sha256"] == b["rows"][1]["query_sha256"]
    assert a["rows"][2]["query_sha256"] != b["rows"][2]["query_sha256"]


@pytest.mark.parametrize("mode", ["forced", "free"])
def test_train_mode_rejected_without_silent_mode_change(mode):
    model = graph().train()
    with pytest.raises(ValueError, match="eval mode"):
        if mode == "forced":
            audit.trace_continuation(model, spec(), guard=lambda _: None)
        else:
            audit.trace_generation(model, (1, 8), (), **policy())
    assert model.training


@pytest.mark.parametrize(
    "field,value",
    [
        ("prefix", []),
        ("prefix", (True,)),
        ("continuation", ()),
        ("stages", ("content",)),
        ("stages", ("truth",)),
        ("probes", (2, 2)),
        ("eos", -1),
    ],
)
def test_spec_rejects_ambiguous_or_mutable_annotations(field, value):
    kwargs = dict(prefix=(1,), continuation=(2, 3), stages=("content", "stop"), eos=3, probes=())
    kwargs[field] = value
    with pytest.raises(ValueError):
        audit.ReadoutSpec(**kwargs)
