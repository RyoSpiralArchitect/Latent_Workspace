"""Validate the pre-generation, hand-authored qualitative answer-bank fixture."""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data/v14_answer_bank/cases.json"
DOCUMENT = json.loads(FIXTURE.read_text())
CASES = DOCUMENT["cases"]
RELATIONS = [case for case in CASES if case["lane"] == "relation"]
GENERAL = [case for case in CASES if case["lane"] == "general"]
REQUIRED = {
    "id",
    "lane",
    "user_prompt",
    "memory_text",
    "twin_memory_text",
    "unrelated_memory_text",
    "reference",
    "rubric",
    "language",
    "task_type",
}
EDGE = re.compile(r"^- (\w+) is ranked above (\w+)\.$", re.MULTILINE)


def _edges(context):
    assert context.startswith("World facts. The ranking is transitive.\n")
    edges = EDGE.findall(context)
    assert len(edges) == 4
    assert len(set(edges)) == 4
    assert len(context.splitlines()) == 5
    return edges


def _relation_worlds():
    worlds = defaultdict(list)
    for case in RELATIONS:
        worlds[case["reference"]["world_id"]].append(case)
    return worlds


def test_complete_precommitted_fixture_and_denominators():
    assert DOCUMENT["format"] == "latent-workspace-v14-answer-bank-cases-v1"
    assert len(CASES) == 16
    assert Counter(case["lane"] for case in CASES) == {"relation": 8, "general": 8}
    assert len({case["id"] for case in CASES}) == len(CASES)
    assert len({case["user_prompt"] for case in CASES}) == len(CASES)
    for case in CASES:
        assert REQUIRED <= case.keys()
        assert all(
            case[key].strip()
            for key in (
                "id",
                "user_prompt",
                "memory_text",
                "twin_memory_text",
                "unrelated_memory_text",
            )
        )
        assert (
            len({case[key] for key in ("memory_text", "twin_memory_text", "unrelated_memory_text")})
            == 3
        )
        assert case["rubric"] and all(isinstance(rule, str) for rule in case["rubric"])
        assert case["language"] in {"en", "ja"}
    provenance = DOCUMENT["provenance"]
    assert provenance["external_facts_required"] is False
    assert provenance["selection_by_prior_outcome"] is False
    assert provenance["independent_case_count"] == 12
    assert provenance["relation_world_count"] == 4
    assert provenance["relation_prompt_count"] == len(RELATIONS)
    assert provenance["general_prompt_count"] == len(GENERAL)


@pytest.mark.parametrize("case", RELATIONS, ids=lambda case: case["id"])
def test_relation_graph_answers_and_single_adjacent_swap(case):
    ref = case["reference"]
    assert ref["authority"] == "selected_memory_world"
    original, twin = ref["original"]["order"], ref["twin"]["order"]
    assert len(original) == len(set(original)) == 5
    assert set(original) == set(twin)
    changed = [index for index in range(5) if original[index] != twin[index]]
    assert len(changed) == 2 and changed[1] == changed[0] + 1
    assert original[changed[0]] == twin[changed[1]]
    assert original[changed[1]] == twin[changed[0]]
    for side, context_key in (("original", "memory_text"), ("twin", "twin_memory_text")):
        order = ref[side]["order"]
        assert _edges(case[context_key]) == list(zip(order, order[1:]))
        left, right = ref["query"]
        expected = "yes" if order.index(left) < order.index(right) else "no"
        assert ref[side]["answer"] == expected
        assert f"Is {left} ranked above {right}?" in case["user_prompt"]
    assert ref["original"]["answer"] != ref["twin"]["answer"]
    unrelated_entities = {
        entity for edge in _edges(case["unrelated_memory_text"]) for entity in edge
    }
    assert set(original).isdisjoint(unrelated_entities)
    assert "ranked above" not in case["user_prompt"].split("?")[1]


def test_relation_reverse_pairs_share_query_independent_memory_and_flip_gold():
    worlds = _relation_worlds()
    assert len(worlds) == 4
    all_entities = []
    for pair in worlds.values():
        assert len(pair) == 2
        forward, reverse = sorted(pair, key=lambda case: case["id"])
        assert forward["id"].endswith("forward") and reverse["id"].endswith("reverse")
        for key in ("memory_text", "twin_memory_text", "unrelated_memory_text"):
            assert forward[key] == reverse[key]
            assert "Answer" not in forward[key] and "?" not in forward[key]
        assert forward["reference"]["query"] == reverse["reference"]["query"][::-1]
        for side in ("original", "twin"):
            assert forward["reference"][side]["order"] == reverse["reference"][side]["order"]
            assert forward["reference"][side]["answer"] != reverse["reference"][side]["answer"]
        all_entities.extend(forward["reference"]["original"]["order"])
    assert len(all_entities) == len(set(all_entities)) == 20


def test_handcrafted_relation_worlds_are_disjoint_from_all_prior_384_worlds():
    previous = []
    for relative in (
        "data/v10/functional_train.jsonl",
        "data/v10/functional_eval.jsonl",
        "data/v14_mech_repair/fresh_eval.jsonl",
    ):
        previous.extend(json.loads(line) for line in (ROOT / relative).read_text().splitlines())
    assert len(previous) == 384
    old_entities = {
        entity for record in previous for order in record["metadata"]["orders"] for entity in order
    }
    old_contexts = {context for record in previous for context in record["contexts"]}
    old_orders = {tuple(order) for record in previous for order in record["metadata"]["orders"]}
    for case in RELATIONS:
        for side, context in (("original", "memory_text"), ("twin", "twin_memory_text")):
            assert set(case["reference"][side]["order"]).isdisjoint(old_entities)
            assert tuple(case["reference"][side]["order"]) not in old_orders
            assert case[context] not in old_contexts


@pytest.mark.parametrize("case", GENERAL, ids=lambda case: case["id"])
def test_general_facts_visible_and_twin_never_rewrites_gold(case):
    ref = case["reference"]
    assert ref["authority"] == "visible_user_prompt"
    assert ref["visible_facts"]
    for fact in ref["visible_facts"]:
        assert fact in case["user_prompt"]
    assert ref["twin"]["gold_unchanged"] is True
    assert ref["twin"]["memory_only_change"]
    assert ref["original"]
    assert ref["example_answer"]
    original_lines, twin_lines = (
        case["memory_text"].splitlines(),
        case["twin_memory_text"].splitlines(),
    )
    assert len(original_lines) == len(twin_lines)
    assert sum(left != right for left, right in zip(original_lines, twin_lines)) == 1


def test_general_task_diversity_and_reference_sanity():
    assert len({case["task_type"] for case in GENERAL}) == 8
    assert Counter(case["language"] for case in GENERAL) == {"en": 5, "ja": 3}
    keyed = {case["id"]: case for case in GENERAL}
    numbers = keyed["general-03-arithmetic"]["reference"]["original"]
    assert numbers["total_cost"] == 7 * 5 + 3 * 2
    assert numbers["credits_left"] == 48 - numbers["total_cost"]
    plan = keyed["general-06-planning"]["reference"]["original"]
    assert plan["intervals_minutes"] == [
        ["バックアップ", 0, 15],
        ["更新", 15, 35],
        ["動作確認", 35, 45],
    ]
    assert plan["spare_minutes"] == 60 - 45
    extraction = keyed["general-02-json"]["reference"]
    assert json.loads(extraction["example_answer"]) == extraction["original"]["object"]
    code_ref = keyed["general-04-code"]["reference"]
    code = code_ref["example_answer"].removeprefix("```python\n").removesuffix("\n```")
    namespace = {}
    exec(compile(code, "<frozen-reference>", "exec"), namespace)
    first_positive = namespace["first_positive"]
    assert first_positive([]) is None
    assert first_positive([0]) is None
    assert first_positive([2, 5]) == 2
    assert keyed["general-05-causal"]["reference"]["original"]["causal_proof"] is False
    for case in GENERAL:
        sample = case["reference"]["example_answer"]
        if case["language"] == "ja":
            assert len(sample) <= 100
        else:
            assert len(sample.split()) <= 60
