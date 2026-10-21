"""Tiny tests of the actual read-only runner, full-vocab generation and scoring."""

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch
from test_latent_workspace_stack import host_model

from latent_workspace import native_evaluation as ev
from latent_workspace.native_memory import NativeMemoryCausalLM
from latent_workspace.optimizer_state import tree_hash

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_v22_comparison as runner  # noqa: E402


@pytest.fixture(autouse=True)
def threads():
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("  Not specified.\n", "not specified"),
        ("X. because Y", "x. because y"),
        ("X\n Y.", "x y"),
    ],
)
def test_normalization_is_not_prefix_matching(text, expected):
    assert ev.normalized_answer(text) == expected


@pytest.mark.parametrize("temperature", [0.0, 0.7])
@pytest.mark.parametrize("memory", [[], [4, 5]])
def test_generation_same_seed_no_mutation_or_gradients(temperature, memory):
    graph = NativeMemoryCausalLM(host_model("mistral"), cut=1).eval()
    before = tree_hash(graph.model.state_dict())
    args = dict(seed=7, cap=3, eos=42, temperature=temperature, top_p=0.9, guard=lambda _: None)
    a = ev.generate(graph, [1, 8, 9], memory, **args)
    b = ev.generate(graph, [1, 8, 9], memory, **args)
    assert a == b
    assert 0 < a["generated_tokens"] <= 3
    assert tree_hash(graph.model.state_dict()) == before
    assert all(p.grad is None for p in graph.parameters())


def test_eos_stops_and_non_eos_cap_is_explicit():
    class Fixed(torch.nn.Module):
        def __init__(self, token):
            super().__init__()
            self.p = torch.nn.Parameter(torch.zeros(1), requires_grad=False)
            self.token = token

        def forward(self, input_ids, **kwargs):
            logits = torch.zeros(1, input_ids.shape[1], 7)
            logits[:, :, self.token] = 10
            return SimpleNamespace(logits=logits)

    kw = dict(seed=0, cap=3, eos=2, temperature=0, top_p=1, guard=lambda _: None)
    assert ev.generate(Fixed(2), [1], [], **kw)["token_ids"] == [2]
    result = ev.generate(Fixed(4), [1], [], **kw)
    assert result["token_ids"] == [4, 4, 4] and result["stop_reason"] == "length"


def test_full_vocabulary_sampling_and_bad_logits():
    gen = torch.Generator().manual_seed(3)
    logits = torch.tensor([0.0, 1.0, 9.0, 2.0, 3.0])
    assert ev.choose(logits, generator=gen, temperature=0, top_p=1) == 2
    assert ev.choose(logits, generator=gen, temperature=0.7, top_p=0.01) == 2
    with pytest.raises(ValueError, match="Finite"):
        ev.choose(torch.tensor([float("nan"), 1.0]), generator=gen, temperature=0, top_p=1)


def test_choice_ties_and_gold_log_probability():
    result = ev.score_choices(torch.tensor([9.0, 2.0, 2.0, 0.0, -1.0]), [1, 2, 3, 4], 0)
    assert result["correct"] and not result["strict_correct"] and result["ties"] == 2
    assert result["full_vocabulary_argmax"] == 0
    assert result["gold_logprob"] < -6


def test_tokenizer_rejects_unstable_choice_boundary():
    class Tokenizer:
        def encode(self, text, add_special_tokens):
            return [1] if len(text) == 1 else [2, ord(text[-1])]

    with pytest.raises(ValueError, match="stable"):
        ev.choice_tokens(Tokenizer(), {"prompt": "P"}, 20)


def test_tensor_batch_has_query_only_labels():
    batch = ev.tensor_batch([1, 2], [7, 8], "cpu", [3, 4])
    assert batch["input_ids"].tolist() == [[1, 2, 3, 4]]
    assert batch["labels"].tolist() == [[-100, -100, 3, 4]]
    assert batch["memory_ids"].tolist() == [[7, 8]]


def test_heldout_group_selection_dedup_and_leakage():
    rows = [
        dict(
            row_id=f"g{i}/s{side}",
            group_id=f"g{i}",
            split="test",
            family="f",
            memory=f"memory{i}",
            query="q",
            answer=f"a{i}",
        )
        for i in range(4)
        for side in (0, 1)
    ]
    spec = dict(strata=[["test", "f", 2]], seed=7, unique_rows=2)
    result = ev.select_worlds(rows, spec, {"train"})
    assert len(result) == 2 and all(len(r["aliases"]) == 1 for r in result)
    assert result == ev.select_worlds(list(reversed(rows)), spec, {"train"})
    with pytest.raises(ValueError, match="leakage"):
        ev.select_worlds(rows, spec, {result[0]["group_id"]})


def test_paired_counts_and_missingness():
    assert ev.paired_counts(
        dict(a=True, b=True, c=False, d=False), dict(a=True, b=False, c=True, d=False)
    ) == dict(
        n=4,
        both_correct=1,
        base_only=1,
        v22_only=1,
        both_wrong=1,
        base_correct=2,
        v22_correct=2,
    )
    with pytest.raises(ValueError, match="coverage"):
        ev.paired_counts({"a": True}, {})


def test_activity_does_not_claim_zero_sequences_on_failure():
    result = {}
    runner.RUN.activity(result)
    assert result == dict(new_sequences=None, native_weight_updates=0)
    runner.RUN.activity(result, {"new_sequences": 12})
    assert result["new_sequences"] == 12


def test_entire_runner_body_uses_native_loss_field_and_no_updates(tmp_path, monkeypatch):
    graph = NativeMemoryCausalLM(host_model("mistral"), cut=1).eval()
    before = tree_hash(graph.model.state_dict())

    class Tokenizer:
        def decode(self, ids, skip_special_tokens):
            return "answer" if ids else ""

    mmlu = [
        dict(id=f"m{i}", subject="s", input_ids=[1, 8, 9], choice_ids=[3, 4, 5, 6], target=0)
        for i in range(2)
    ]
    world = dict(
        row_id="w0",
        group_id="g",
        family="f",
        split="test",
        side=0,
        mode="affected",
        aliases=[],
        answer="answer",
        memory_ids=[4, 5],
        prefixes=dict(latent=[1, 7], inline=[1, 6, 7]),
        answer_ids=[8, 2],
    )
    free = [dict(id="f0", category="writing", prompt="prompt", input_ids=[1, 7])]
    data = dict(mmlu=mmlu, worlds=[world], free=free)
    monkeypatch.setattr(runner, "inputs", lambda plan: (data, {}))
    monkeypatch.setattr(
        runner, "prepare", lambda *a: (graph, Tokenizer(), lambda *a, **kw: None, before)
    )
    monkeypatch.setattr(runner.common, "engine_imports", lambda seal: {})
    monkeypatch.setattr(runner.common, "peak", lambda: {})
    policy = dict(seed=3, seeds=[3, 4], max_new_tokens=2, temperature=0, top_p=1)
    plan = dict(
        world_routes=["latent", "inline"],
        world_generation=policy,
        generation=policy,
        planned=dict(total_new_sequences=8),
    )
    output = runner.run(None, SimpleNamespace(output=tmp_path, role="base"), plan, {})
    assert output["new_sequences"] == 4 and output["native_weight_updates"] == 0
    rows = [json.loads(s) for s in (tmp_path / "worlds.jsonl").read_text().splitlines()]
    assert len(rows) == 2 and all(r["teacher"]["supervised_tokens"] == 2 for r in rows)
    assert tree_hash(graph.model.state_dict()) == before
    assert all(p.grad is None for p in graph.parameters())


def test_journal_rejects_nan():
    with pytest.raises(ValueError):
        runner.append(io.StringIO(), {"score": float("nan")})
