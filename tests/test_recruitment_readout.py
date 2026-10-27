"""Pure oracle/annotation checks and unchanged tiny-host measurement semantics."""

import copy
import json
import os

import pytest
import torch
from test_latent_workspace_stack import host_model

from latent_workspace import native_evaluation as ev
from latent_workspace import readout_audit as audit
from latent_workspace import recruitment_bank as bank
from latent_workspace import recruitment_readout as rr
from latent_workspace.native_memory import NativeMemoryCausalLM
from latent_workspace.optimizer_state import tree_hash


class Tokenizer:
    eos_token_id = 2

    def encode(self, text, **kwargs):
        return [ord(c) % 36 + 4 for c in text]

    def __call__(self, text, **kwargs):
        return dict(
            input_ids=self.encode(text), offset_mapping=[(i, i + 1) for i in range(len(text))]
        )

    def apply_chat_template(self, messages, **kwargs):
        return [1] + self.encode(messages[0]["content"])


def rows():
    return [
        r
        for family in bank.FAMILIES
        for split in ("train", "dev", "confirmation")
        for i in range(4)
        for r in bank.group_rows(f"fixture-{family}-{split}-{i}", family, split, 71)
    ]


def selection():
    return rr.select_development(rows(), seed="test", groups_per_family=2, exposed_keys=[])


def test_whole_group_exposure_and_confirmation_exclusion():
    raw = rows()
    exposed = [
        next(r["row_id"] for r in raw if r["split"] == "dev" and r["family"] == f)
        for f in bank.FAMILIES
    ]
    result = rr.select_development(raw, seed="fixed", groups_per_family=2, exposed_keys=exposed)
    assert result["groups"] == 6 and result["unique_rows"] == 36 and result["raw_rows"] == 48
    assert len(result["excluded_exposed_groups"]) == 3
    assert result == rr.select_development(
        list(reversed(raw)), seed="fixed", groups_per_family=2, exposed_keys=exposed
    )
    assert all(r["split"] == "dev" for r in result["rows"])
    assert sum(len(r["aliases"]) for r in result["rows"]) == 12
    assert not set(result["selected_groups"]) & set(result["excluded_exposed_groups"])


def test_insufficient_unexposed_groups_rejected():
    raw = rows()
    with pytest.raises(ValueError, match="coverage"):
        rr.select_development(
            raw,
            seed=1,
            groups_per_family=1,
            exposed_keys=[r["row_id"] for r in raw if r["split"] == "dev"],
        )


@pytest.mark.parametrize(
    "expected",
    [
        dict(answer=42, steps=[6, 42]),
        dict(answer=[], steps=[]),
        dict(answer=["ABCDE"], steps=["ABCDE"]),
        dict(answer="ABCDE", steps=["ABCDE"]),
        dict(answer=None),
    ],
)
@pytest.mark.parametrize("order", rr.ORDERS)
def test_annotation_denominator_and_gold_answer_context(expected, order):
    ref = rr.reference(Tokenizer(), expected, order)
    assert json.loads(ref["text"]) == expected
    assert sum(ref["parts"].values()) == len(ref["token_ids"]) == len(ref["tokens"])
    assert ref["tokens"][-1]["part"] == "stop"
    first = ref["first_answer_index"]
    assert first is not None and not ref["tokens"][first]["gold_answer_in_prefix"]
    if expected["answer"] == []:
        assert ref["first_answer_lexical_index"] is None
    step_tokens = [t for t in ref["tokens"] if "steps" in t["value_fields"]]
    assert all(t["gold_answer_in_prefix"] == (order == "answer_first") for t in step_tokens)
    if order == "answer_first":
        assert ref["text"] == " " + rr.ex.canonical(expected)


def test_mixed_boundary_tokens_are_not_counted_as_pure_semantics():
    class Fused(Tokenizer):
        def encode(self, text, **kwargs):
            return [7]

        def __call__(self, text, **kwargs):
            return dict(input_ids=[7], offset_mapping=[(0, len(text))])

    ref = rr.reference(Fused(), dict(answer=4, steps=[4]), "answer_first")
    assert ref["parts"] == dict(mixed=1, stop=1)
    assert ref["tokens"][0]["value_fields"] == ["answer", "steps"]


@pytest.mark.parametrize("damage", ["offset", "omission", "id", "eos"])
def test_invalid_tokenizer_alignment_rejected(damage):
    class Damaged(Tokenizer):
        def __call__(self, text, **kwargs):
            item = super().__call__(text, **kwargs)
            if damage == "offset":
                item["offset_mapping"][0] = (0, 0)
            elif damage == "omission":
                item["offset_mapping"] = [(0, 1)] * len(item["input_ids"])
            elif damage == "id":
                item["input_ids"][0] = 999
            return item

    tok = Damaged()
    if damage == "eos":
        tok.eos_token_id = tok.encode(" ")[0]
    with pytest.raises(ValueError):
        rr.reference(tok, dict(answer=8), "answer_first")


def test_crossed_routes_have_no_assisted_generation_prefix_and_full_controls():
    tok = Tokenizer()
    data = rr.cases(tok, selection(), memory_cap=4096, query_cap=4096)
    assert len(data) == 72
    assert sum(len(c["references"]) for c in data) == 144
    for a, b in zip(data[::2], data[1::2], strict=True):
        assert a["route"] == "inline" and b["route"] == "workspace"
        assert a["references"] == b["references"] and a["expected"] == b["expected"]
        assert not a["memory_ids"]
        if a["mode"] == "absent":
            assert a["prefix_ids"] == b["prefix_ids"] and not b["memory_ids"]
        row = next(r for r in selection()["rows"] if r["row_id"] == b["row_id"])
        assert b["prefix_ids"] == ev.encode_chat(tok, row["query"])
        assert len(b["references"]) == (
            3 if b["mode"] == "affected" else 2 if b["mode"] == "unaffected" else 1
        )


def test_route_bounds_never_silently_truncate():
    with pytest.raises(ValueError, match="bounds"):
        rr.cases(Tokenizer(), selection(), memory_cap=1)


@pytest.mark.parametrize(
    "text,content,steps,parsed",
    [
        ('{"answer":42,"steps":[6,42]}', True, True, True),
        ('{"steps":[6,42],"answer":42}', True, True, True),
        ('{"answer":42,"steps":[7,42]}', True, False, True),
        ('{"answer":43,"steps":[6,42]}', False, True, True),
        ('{"answer":42,"answer":42,"steps":[6,42]}', False, False, False),
        ('```json\n{"answer":42,"steps":[6,42]}\n```', False, False, False),
        ('{"answer":NaN}', False, False, False),
        ('{"answer":42,', False, False, False),
    ],
)
def test_free_generation_keeps_errors_in_denominator(text, content, steps, parsed):
    result = rr.score_generation(text, dict(answer=42, steps=[6, 42]))
    assert (result["content_correct"], result["steps_correct"], result["parsed"]) == (
        content,
        steps,
        parsed,
    )
    assert result["steps_applicable"] and not result["reference_assistance"]
    if parsed:
        assert result["key_order"] == list(json.loads(text))


def test_abstention_steps_are_not_an_incorrect_reasoning_attempt():
    result = rr.score_generation('{"answer":null}', bank.UNKNOWN)
    assert result["exact"] and not result["steps_applicable"]


@pytest.mark.parametrize("kind", ["mistral", "olmo2", "gpt2", "scratch"])
def test_native_fixed_observation_is_read_only_and_causally_annotated(kind):
    old = torch.get_num_threads()
    torch.set_num_threads(2)
    try:
        graph = (
            NativeMemoryCausalLM(host_model(kind), cut=1)
            .to(os.environ.get("LTWS_TEST_DEVICE", "cpu"))
            .eval()
        )
        before = tree_hash(graph.state_dict())
        ref = rr.reference(Tokenizer(), dict(answer=7, steps=[7]), "answer_first")
        spec = rr.specification([1, 6], ref, 2)
        trace = audit.trace_continuation(graph, spec, (3, 5), guard=lambda _: None)
        summary = rr.summarize_fixed(trace, ref)
        assert summary["tokens"] == len(ref["token_ids"])
        assert summary["step_bearing_tokens_by_assistance"]["before_gold_answer"]["tokens"] == 0
        assert summary["step_bearing_tokens_by_assistance"]["after_gold_answer"]["tokens"] > 0
        assert sum(v["nll_sum"] for v in summary["parts"].values()) == pytest.approx(
            summary["nll_sum"]
        )
        assert tree_hash(graph.state_dict()) == before and all(
            p.grad is None for p in graph.parameters()
        )
        bad = copy.deepcopy(ref)
        bad["token_ids"][0] += 1
        with pytest.raises(ValueError):
            rr.summarize_fixed(trace, bad)
    finally:
        torch.set_num_threads(old)
