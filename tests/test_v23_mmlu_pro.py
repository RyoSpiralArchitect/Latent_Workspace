"""Offline MMLU-Pro sampling, parsing and native-evaluation controls."""

import copy
from types import SimpleNamespace

import pytest
import run_v23_mmlu_pro as run
import v23_mmlu_pro as data


def row(category="c0", index=0):
    return dict(
        question_id=index,
        category=category,
        question=f"Question {category} {index}?",
        options=["option0", "option1", "option2"],
        answer="B",
        answer_index=1,
        cot_content="Example rationale. The answer is (B).",
        src="offline-fixture",
    )


def panel():
    p = data.ex.read(data.ROOT / data.PLAN)
    test = [row(f"c{c}", i) for c in range(14) for i in range(30)]
    validation = [row(f"c{c}", 100 + i) for c in range(14) for i in range(5)]
    return data.select(test, validation, p), p, test, validation


def test_fixed_balanced_and_nested_counts():
    selected, p, _, _ = panel()
    assert selected["audit"]["selected"] == 280
    assert selected["audit"]["reasoning"] == 28
    assert set(selected["generation_ids"]) <= {r["id"] for r in selected["rows"]}
    assert set(selected["audit"]["selected_categories"].values()) == {20}
    assert len(selected["examples"]) == 70
    assert run.runtime_plan(p)["training_source"] == run.previous.SOURCE


def test_selection_is_permutation_and_label_invariant():
    selected, p, test, validation = panel()
    ids = [r["id"] for r in selected["rows"]]
    for r in test:
        r.update(answer="A", answer_index=0)
    other = data.select(test[::-1], validation, p)
    assert [r["id"] for r in other["rows"]] == ids


def test_test_rationale_and_gold_not_inserted_into_prompt():
    r = data.normalized(row())
    r["cot_content"] = "SECRET_TEST_RATIONALE"
    direct, reasoning = data.prompts(r, [data.normalized(row(index=100 + i)) for i in range(5)])
    assert "SECRET_TEST_RATIONALE" not in direct + reasoning
    assert reasoning.count("Example rationale.") == 5


def test_na_options_are_remapped_without_wrong_gold():
    r = row()
    r.update(options=["N/A", "yes", "no"])
    fixed = data.normalized(r)
    assert fixed["target"] == 0 and fixed["letter"] == "A"
    assert fixed["option_index_map"] == [1, 2]


@pytest.mark.parametrize("damage", ["duplicate", "shots", "overlap"])
def test_bad_panel_is_rejected(damage):
    _, p, test, validation = panel()
    if damage == "duplicate":
        test.append(test[0])
    elif damage == "shots":
        validation.pop()
    else:
        chosen = data.select(test, validation, p)["rows"][0]
        next(r for r in validation if r["category"] == chosen["category"])["question"] = chosen[
            "question"
        ]
    with pytest.raises(ValueError):
        data.select(test, validation, p)


@pytest.mark.parametrize(
    "text,count,expected",
    [
        ("The answer is (B).", 10, 1),
        ("Answer: J", 10, 9),
        ("The answer is (A). The answer is (A).", 3, 0),
        ("The answer is (A). The answer is (B).", 3, None),
        ("B", 3, None),
        ("I am considering A or B.", 3, None),
        ("The answer is (J).", 3, None),
        ("The answer is", 3, None),
        ("The answer is Aardvark", 10, None),
    ],
)
def test_strict_parser_never_randomly_imputes(text, count, expected):
    out = data.extract(text, count)
    assert out["prediction"] == expected
    assert out["parsed"] == (expected is not None)


def test_transitions_include_regressions_not_only_wins():
    a = {"a": True, "b": True, "c": False, "d": False}
    b = {"a": True, "b": False, "c": True, "d": False}
    result = data.transitions(a, b)
    assert result["counts"] == dict(both_correct=1, base_only=1, candidate_only=1, both_wrong=1)
    assert result["ids"]["candidate_only"] == ["c"] and result["ids"]["base_only"] == ["b"]
    assert result["net_correct"] == 0


def test_missing_pair_does_not_reduce_denominator_silently():
    with pytest.raises(ValueError, match="paired IDs"):
        data.transitions({"x": True}, {})


class Tokenizer:
    chat_template = "offline-test-template"
    eos_token_id = 2

    def encode(self, value, add_special_tokens=False):
        return [ord(c) for c in value if c != " "]

    def apply_chat_template(self, messages, tokenize=True, **kwargs):
        text = messages[0]["content"] + "|"
        return self.encode(text) if tokenize else text


def test_tokenization_keeps_all_options_and_five_examples():
    selected, p, _, _ = panel()
    result = data.tokenize(selected, Tokenizer(), p)
    assert len(result["rows"]) == 280
    assert sum("reasoning_ids" in r for r in result["rows"]) == 28
    assert all(len(r["choice_ids"]) == 3 for r in result["rows"])
    assert all(len(r["example_ids"]) == 5 for r in result["rows"] if "example_ids" in r)


def test_long_context_is_not_truncated_or_shot_reduced():
    selected, p, _, _ = panel()
    altered = copy.deepcopy(p)
    altered["max_prompt_tokens"] = 1
    with pytest.raises(ValueError, match="prompt bound"):
        data.tokenize(selected, Tokenizer(), altered)


def test_predecessor_missing_blocks_new_forward(tmp_path):
    p = data.ex.read(data.ROOT / data.PLAN)
    p["predecessor_bundle"] = str(tmp_path)
    with pytest.raises(FileNotFoundError):
        run.predecessor(p)


def test_entire_runner_counts_readonly_and_separate_endpoints(tmp_path, monkeypatch):
    import torch

    from latent_workspace.optimizer_state import tree_hash

    class Host(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.marker = torch.nn.Parameter(torch.ones(1))

        def forward(self, input_ids, **kwargs):
            return SimpleNamespace(logits=torch.zeros(1, input_ids.shape[1], 12))

    class Graph(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.model = Host()

        def forward(self, **kwargs):
            return self.model(**kwargs)

    graph = Graph()
    rows = [
        dict(
            id=str(i),
            category="mock-only",
            input_ids=[1, 2],
            choice_ids=[3, 4, 5],
            target=2,
            options=["a", "b", "c"],
            reasoning_ids=[1, 2],
        )
        for i in range(280)
    ]
    inputs = dict(rows=rows, generation_ids=[str(i) for i in range(28)])
    monkeypatch.setattr(run, "inputs", lambda p: (inputs, {}))
    monkeypatch.setattr(run, "predecessor", lambda p: {"mock_only": True})
    monkeypatch.setattr(
        run.previous,
        "prepare",
        lambda *a: (
            graph,
            SimpleNamespace(decode=lambda *a, **k: "The answer is (C)."),
            lambda *a, **k: None,
            tree_hash(graph.model.state_dict()),
        ),
    )
    monkeypatch.setattr(
        run.ev,
        "generate",
        lambda *a, **k: dict(
            token_ids=[2],
            generated_tokens=1,
            stop_reason="eos",
            seed=k["seed"],
            max_new_tokens=k["cap"],
            temperature=k["temperature"],
            top_p=k["top_p"],
        ),
    )
    monkeypatch.setattr(run.previous.common, "engine_imports", lambda s: {})
    monkeypatch.setattr(run.previous.common, "peak", lambda: {})
    result = run.run(
        None, SimpleNamespace(output=tmp_path, role="base"), data.ex.read(data.ROOT / data.PLAN), {}
    )
    assert result["new_sequences"] == 28 and result["direct_rows"] == 280
    assert result["native_weight_updates"] == 0
    direct = (tmp_path / "direct.jsonl").read_text().splitlines()
    reasoning = (tmp_path / "reasoning.jsonl").read_text().splitlines()
    assert len(direct) == 280 and len(reasoning) == 28
    assert data.ex.read(tmp_path / "WEIGHT_IDENTITY.json")["equal"]
