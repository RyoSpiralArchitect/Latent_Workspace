"""CPU-only corpus and tokenizer-bound rendering contracts; no model download."""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
from collections import Counter, defaultdict

import pytest
import v15_elicitation_inputs as inputs
from v13_task_fixture import HEADER, _parse_context, _parse_query, symbolic_oracle

from latent_workspace_ft_v10 import engine

QUERY = "Is Aster ranked above Beryl? Answer:"
CONTEXT = HEADER + "\n- Aster is ranked above Beryl."


class ToyTokenizer:
    is_fast = True
    bos_token_id = 1
    chat_template = "toy-pinned-native-template-v1"
    markers = {"<s>": 1, "[INST]": 2, "[/INST]": 3, " no": 10001, " yes": 10002}

    def tokenize_offsets(self, text):
        ids, offsets = [], []
        index = 0
        while index < len(text):
            for marker, token in self.markers.items():
                if text.startswith(marker, index):
                    ids.append(token)
                    offsets.append((index, index + len(marker)))
                    index += len(marker)
                    break
            else:
                ids.append(ord(text[index]) + 100)
                offsets.append((index, index + 1))
                index += 1
        return ids, offsets

    def encode(self, text, *, add_special_tokens):
        assert add_special_tokens is False
        return self.tokenize_offsets(text)[0]

    def get_chat_template(self):
        return self.chat_template

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        assert add_generation_prompt is True
        assert len(messages) == 1 and messages[0]["role"] == "user"
        text = "<s>[INST] " + messages[0]["content"] + " [/INST]"
        if not tokenize:
            return text
        return {"input_ids": self.encode(text, add_special_tokens=False)}

    def __call__(self, text, **kwargs):
        assert kwargs == {
            "add_special_tokens": False,
            "truncation": False,
            "padding": False,
            "return_offsets_mapping": True,
            "return_attention_mask": False,
        }
        ids, offsets = self.tokenize_offsets(text)
        return {"input_ids": ids, "offset_mapping": offsets}


def render(**kwargs):
    return inputs.render_case(
        kwargs.pop("tokenizer", ToyTokenizer()),
        query=kwargs.pop("query", QUERY),
        context=kwargs.pop("context", CONTEXT),
        renderer=kwargs.pop("renderer", "raw"),
        information=kwargs.pop("information", "inline"),
        **kwargs,
    )


def test_corpus_is_deterministic_balanced_and_exactly_36_cases():
    cases = inputs.make_cases()
    assert cases == inputs.make_cases()
    assert len({row["case_id"] for row in cases}) == len(cases) == 36
    assert Counter(row["split"] for row in cases) == {"exposed": 4, "confirmation": 32}
    assert Counter(row["view"] for row in cases) == {
        "historical": 4,
        "atomic": 16,
        "full_chain": 16,
    }
    assert Counter(row["target_label"] for row in cases) == {0: 18, 1: 18}
    assert all(
        set(row)
        == {
            "case_id",
            "split",
            "family_id",
            "view",
            "query",
            "context",
            "target_label",
            "hop",
            "wording",
        }
        for row in cases
    )


def test_exposed_cases_replay_exact_original_side_zero_bytes_and_ids():
    records = [
        json.loads(line)
        for line in (inputs.REPO / "data/v10/functional_train.jsonl").read_text().splitlines()[:2]
    ]
    exposed = inputs.make_cases()[:4]
    assert [row["case_id"] for row in exposed] == ["w0_q0", "w0_q1", "w1_q0", "w1_q1"]
    for row, (world, query) in zip(exposed, ((0, 0), (0, 1), (1, 0), (1, 1)), strict=True):
        assert row["context"] == records[world]["contexts"][0]
        assert row["query"] == records[world]["queries"][query]
        assert row["target_label"] == records[world]["answers"][0][query]


def test_confirmation_orders_are_new_distinct_six_entity_families():
    known = inputs.known_orders()
    grouped = defaultdict(list)
    for row in inputs.make_cases()[4:]:
        grouped[row["family_id"]].append(row)
    assert len(grouped) == 8
    orders = []
    for family_index, rows in enumerate(grouped.values()):
        full_rows = [row for row in rows if row["view"] == "full_chain"]
        order, edges = _parse_context(full_rows[0]["context"])
        assert len(order) == 6 and len(edges) == 5
        assert tuple(order) not in known
        assert set(order) <= set(inputs.NAMES)
        orders.append(tuple(order))
        expected = "ranked_above" if family_index % 2 == 0 else "outrank"
        assert {row["wording"] for row in rows} == {expected}
    assert len(set(orders)) == 8


def test_each_reciprocal_pair_shares_context_but_flips_label_and_preserves_hop():
    grouped = defaultdict(list)
    for row in inputs.make_cases()[4:]:
        grouped[row["family_id"], row["view"]].append(row)
    for (_, view), (first, second) in grouped.items():
        assert first["context"] == second["context"]
        assert _parse_query(first["query"]) == _parse_query(second["query"])[::-1]
        assert first["target_label"] + second["target_label"] == 1
        order, edges = _parse_context(first["context"])
        expected_hop = 1 if view == "atomic" else 3
        assert len(edges) == (1 if view == "atomic" else 5)
        for row in (first, second):
            left, right = _parse_query(row["query"])
            assert row["hop"] == abs(order.index(left) - order.index(right)) == expected_hop
            assert row["target_label"] == symbolic_oracle(row["context"], row["query"])


def test_atomic_relation_belongs_to_corresponding_full_chain():
    grouped = defaultdict(dict)
    for row in inputs.make_cases()[4:]:
        grouped[row["family_id"]][row["view"]] = row["context"]
    for contexts in grouped.values():
        _, atomic_edges = _parse_context(contexts["atomic"])
        _, chain_edges = _parse_context(contexts["full_chain"])
        assert set(atomic_edges) <= set(chain_edges)


def test_fact_serialization_is_not_always_total_order_and_is_label_independent():
    serialized = []
    for row in inputs.make_cases()[4:]:
        if row["view"] == "full_chain":
            order, edges = _parse_context(row["context"])
            serialized.append(edges == list(zip(order, order[1:], strict=False)))
    assert not any(serialized)


def write_tiny_repo(tmp_path, mutate=None):
    record = json.loads(
        (inputs.REPO / "data/v10/functional_train.jsonl").read_text().splitlines()[0]
    )
    if mutate:
        mutate(record)
    folder = tmp_path / "data/v10"
    folder.mkdir(parents=True)
    for split in ("train", "eval"):
        (folder / f"functional_{split}.jsonl").write_text(json.dumps(record) + "\n")
    return record


def test_known_orders_come_from_graphs_not_metadata(tmp_path):
    record = write_tiny_repo(
        tmp_path, lambda record: record.update(metadata={"orders": [["fake"]]})
    )
    expected = {tuple(_parse_context(context)[0]) for context in record["contexts"]}
    assert inputs.known_orders(tmp_path) == expected


@pytest.mark.parametrize("mutation", ["bad_header", "disconnected", "branched", "duplicate"])
def test_known_order_parser_fails_closed_on_malformed_graphs(tmp_path, mutation):
    def mutate(record):
        if mutation == "bad_header":
            record["contexts"][0] = record["contexts"][0].replace(HEADER, "Guess the order")
        elif mutation == "disconnected":
            record["contexts"][0] += "\n- Aster is ranked above Beryl."
        elif mutation == "branched":
            record["contexts"][0] += "\n- Hira is ranked above Doran."
        else:
            record["contexts"][0] += "\n" + record["contexts"][0].splitlines()[1]

    write_tiny_repo(tmp_path, mutate)
    with pytest.raises(ValueError):
        inputs.known_orders(tmp_path)


def test_renderer_api_does_not_accept_scoring_metadata():
    assert set(inspect.signature(inputs.render_case).parameters) == {
        "tokenizer",
        "query",
        "context",
        "renderer",
        "information",
    }
    with pytest.raises(TypeError):
        render(target_label=1)


@pytest.mark.parametrize("information", inputs.INFORMATION)
def test_raw_and_native_chat_contain_identical_user_content(information):
    raw = render(information=information)
    chat = render(renderer="native_chat", information=information)
    assert raw["user_content"] == chat["user_content"] == raw["text"]
    assert chat["text"] == "<s>[INST] " + raw["text"] + " [/INST]"
    assert chat["prompt_ids"][0] == ToyTokenizer.bos_token_id
    assert chat["prompt_ids"].count(ToyTokenizer.bos_token_id) == 1
    assert raw["candidate_ids"] == chat["candidate_ids"] == [10001, 10002]
    assert raw["candidate_suffixes"] == chat["candidate_suffixes"] == [" no", " yes"]
    assert chat["chat_template"]["native_tokenization_exact"] is True
    assert raw["chat_template"]["native_tokenization_exact"] is None
    assert (
        chat["chat_template"]["sha256"]
        == hashlib.sha256(ToyTokenizer.chat_template.encode()).hexdigest()
    )


def test_raw_instruction_and_prefix_match_historical_config():
    config = engine.DataConfig(
        **json.loads(
            (
                inputs.REPO
                / "configs/v14/boundary_training/config_semantic_boundary16_seed47_step8.json"
            ).read_text()
        )["data"]
    )
    expected = engine._functional_elicitation_query(QUERY, config)
    assert render(information="query_only")["text"] == expected
    assert render()["text"] == CONTEXT + config.prompt_separator + expected


def test_query_only_prefix_is_invariant_to_valid_world_context():
    first = render(information="query_only")
    second = render(information="query_only", context=HEADER + "\n- Beryl is ranked above Aster.")
    assert first == second


@pytest.mark.parametrize("renderer", inputs.RENDERERS)
@pytest.mark.parametrize("information", inputs.INFORMATION)
def test_question_span_covers_only_exact_raw_question(renderer, information):
    rendered = render(renderer=renderer, information=information)
    span = rendered["span"]
    assert span["question"] == QUERY.removesuffix(" Answer:")
    assert rendered["text"][span["character_start"] : span["character_end"]] == span["question"]
    assert list(span["prefix_ids"]) == rendered["prompt_ids"]
    assert span["character_end"] < rendered["text"].index("Answer:")


def test_list_returning_native_chat_tokenizer_is_supported():
    class ListTokenizer(ToyTokenizer):
        def apply_chat_template(self, messages, **kwargs):
            result = super().apply_chat_template(messages, **kwargs)
            return result["input_ids"] if kwargs["tokenize"] else result

    assert (
        render(renderer="native_chat", tokenizer=ListTokenizer())["chat_template"][
            "native_tokenization_exact"
        ]
        is True
    )


@pytest.mark.parametrize("renderer,information", [("other", "inline"), ("raw", "other")])
def test_unknown_factor_levels_fail(renderer, information):
    with pytest.raises(ValueError):
        render(renderer=renderer, information=information)


@pytest.mark.parametrize("mutation", ["mismatch", "double_bos", "batched", "missing_ids"])
def test_invalid_chat_native_tokenization_is_rejected(mutation):
    class BrokenTokenizer(ToyTokenizer):
        def apply_chat_template(self, messages, **kwargs):
            result = super().apply_chat_template(messages, **kwargs)
            if mutation == "double_bos":
                return (
                    {"input_ids": [1] + result["input_ids"]}
                    if kwargs["tokenize"]
                    else "<s>" + result
                )
            if kwargs["tokenize"]:
                if mutation == "mismatch":
                    result["input_ids"][-1] += 1
                elif mutation == "batched":
                    result["input_ids"] = [result["input_ids"]]
                else:
                    result = {"attention_mask": [1]}
            return result

    with pytest.raises(ValueError):
        render(renderer="native_chat", tokenizer=BrokenTokenizer())


@pytest.mark.parametrize("mutation", ["multiple_tokens", "changed_prefix", "same_id"])
def test_invalid_candidate_boundaries_are_rejected(mutation):
    class BrokenTokenizer(ToyTokenizer):
        def encode(self, text, **kwargs):
            result = super().encode(text, **kwargs)
            if text.endswith(inputs.SUFFIXES):
                if mutation == "multiple_tokens":
                    result.append(77)
                elif mutation == "changed_prefix":
                    result[-2] += 1
                else:
                    result[-1] = 10001
            return result

    with pytest.raises(ValueError):
        render(tokenizer=BrokenTokenizer())


def test_missing_native_template_fails_even_in_raw_receipt():
    tokenizer = ToyTokenizer()
    tokenizer.chat_template = None
    with pytest.raises(ValueError, match="template"):
        render(tokenizer=tokenizer)


@pytest.mark.parametrize("mutation", ["drop_instruction", "duplicate"])
def test_native_template_cannot_change_matched_user_content(mutation):
    class ChangedContentTokenizer(ToyTokenizer):
        def apply_chat_template(self, messages, **kwargs):
            changed = copy.deepcopy(messages)
            if mutation == "drop_instruction":
                changed[0]["content"] = changed[0]["content"].replace(
                    inputs.SYMMETRIC_INSTRUCTION, "Answer the query."
                )
            else:
                changed[0]["content"] *= 2
            return super().apply_chat_template(changed, **kwargs)

    with pytest.raises(ValueError, match="user content"):
        render(renderer="native_chat", tokenizer=ChangedContentTokenizer())


def test_corpus_function_does_not_mutate_external_random_state():
    import random

    before = copy.deepcopy(random.getstate())
    inputs.make_cases()
    assert random.getstate() == before
