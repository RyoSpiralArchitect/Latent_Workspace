"""CPU/offline evaluation publication guards; no model or provider calls."""

import copy
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

import pytest

os.environ["CUDA_VISIBLE_DEVICES"] = ""
ROOT = Path(__file__).resolve().parents[1]


def load(name, folder):
    path = ROOT / "provenance/pilots" / folder / "analyze.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bench = load("pro02_publication", "v23_recovered_mmlu_pro02_20261022")
judge = load("judge_publication", "v23_recovered_behavior_judge01_20261022")


def test_qualification_helper_does_not_claim_generic_module_name():
    assert sys.modules.get("verify_qualification") is not bench.verify_qualification
    assert bench.verify_qualification.__name__ == "v23_mmlu_pro02_qualification"


@pytest.fixture
def direct():
    source = dict(id="x", category="test", target=0, input_ids=[1, 3], choice_ids=[5, 6])
    row = dict(
        id="x",
        category="test",
        target=0,
        prompt_tokens=2,
        option_count=2,
        logits=[2.0, 2.0],
        prediction=0,
        ties=2,
        correct=True,
        strict_correct=False,
        gold_margin=0.0,
    )
    return row, source


def test_direct_tie_preserves_both_endpoints(direct):
    bench.direct_check(*direct)
    assert bench.summarize([direct[0]], [])["direct_correct"] == 1
    assert bench.summarize([direct[0]], [])["direct_tie_free_correct"] == 0


@pytest.mark.parametrize(
    "key,value",
    [
        ("id", "other"),
        ("target", 1),
        ("ties", 1),
        ("prediction", 1),
        ("correct", False),
        ("strict_correct", True),
        ("gold_margin", 1),
        ("prompt_tokens", 3),
        ("option_count", 3),
        ("logits", [float("nan"), 2]),
    ],
)
def test_direct_mutation_fails(direct, key, value):
    row, source = copy.deepcopy(direct)
    row[key] = value
    with pytest.raises(AssertionError):
        bench.direct_check(row, source)


@pytest.fixture
def reasoning():
    policy = dict(seed=7, temperature=0.0, top_p=1.0, max_new_tokens=3)
    source = dict(id="x", category="test", target=0, reasoning_ids=[1, 4], options=["yes", "no"])
    row = dict(
        id="x",
        category="test",
        target=0,
        prompt_tokens=2,
        token_ids=[8, 9, 2],
        generated_tokens=3,
        text="The answer is (A)",
        markers=["A"],
        parsed=True,
        prediction=0,
        correct=True,
        completed_correct=True,
        stop_reason="eos",
        **policy,
    )
    return row, source, policy


def test_reasoning_stop_and_parse_are_independent(reasoning):
    row, source, policy = copy.deepcopy(reasoning)
    bench.reasoning_check(row, source, policy)
    row.update(token_ids=[8, 9, 10], stop_reason="length", completed_correct=False)
    bench.reasoning_check(row, source, policy)
    row.update(text="A", markers=[], parsed=False, prediction=None, correct=False)
    bench.reasoning_check(row, source, policy)


@pytest.mark.parametrize(
    "change",
    [
        dict(token_ids=[2, 8, 2]),
        dict(token_ids=[8, 9, 32768]),
        dict(generated_tokens=2),
        dict(stop_reason="length"),
        dict(completed_correct=False),
        dict(parsed=False),
        dict(prediction=1),
        dict(seed=8),
        dict(markers=["B"]),
        dict(text="The answer is (B)"),
    ],
)
def test_reasoning_mutation_fails(reasoning, change):
    row, source, policy = copy.deepcopy(reasoning)
    row.update(change)
    with pytest.raises(AssertionError):
        bench.reasoning_check(row, source, policy)


def test_repeat_sensitivity_not_requalification():
    rows = [
        dict(id=str(i), outcome=o, repeat_agrees=r)
        for i, (o, r) in enumerate(
            [
                ("A", True),
                ("B", False),
                ("tie", None),
                ("order_conflict", False),
                ("unjudged", None),
            ]
        )
    ]
    result = judge.pair_summary(rows)
    assert result["planned_cases"] == 5
    assert result["r0_order_stable_cases"] == 3
    assert result["repeat_agree"] == 1 and result["repeat_disagree"] == 2
    sensitivity = result["sensitivity_excluding_observed_repeat_disagreements"]
    assert sensitivity["n"] == 2 and sensitivity["outcomes"] == dict(A=1, tie=1)
    assert result["r0_outcomes"]["B"] == 1


def test_literal_banks_preserve_spaces_and_fences(reasoning):
    row, source, _ = reasoning
    row = dict(row, text="some ``` text  \nend ")
    source = dict(source, question="Q", category="test", example_ids=["example"])
    rendered = bench.literal_bank(
        dict(rows=[source], generation_ids=["x"]),
        {a: dict(reasoning=[row]) for a in ("base", "off", "on")},
    )
    assert rendered.count("````text\n" + row["text"] + "\n````") == 3
    record = dict(
        request_id="id",
        case_id="case",
        order="AB",
        repeat=0,
        status="INVALID",
        normalized_preference=None,
        final_text=row["text"],
    )
    result = dict(
        frozen_replay=dict(
            pairs=[dict(id="case", arms=["base", "on"], outcome="unjudged", repeat_agrees=None)]
        )
    )
    assert "````text\n" + row["text"] + "\n````" in judge.literal_bank(result, [record])


def test_terminal_judge_replay_cannot_dispatch(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("No provider calls in publication replay")

    monkeypatch.setattr(judge.judge, "transport", forbidden)
    result, records = judge.analyze()
    assert result["denominators"]["valid"] == 170 and len(result["invalid"]) == 4
    assert len(records) == 174 and all(v["repeat"] == 0 for v in result["invalid"])
    assert sum(v["r0_order_stable_cases"] for v in result["pairs"].values()) == 57
    assert result["frozen_replay"]["usage"]["total_tokens"] == 883937
    assert result["winner"] == "none" and result["non_regression"] == "NOT_ESTABLISHED"


def test_published_tables_and_nested_panel_are_source_backed():
    data = json.loads((bench.HERE / "analysis/ANALYSIS.json").read_text())
    text = (bench.HERE / "README.md").read_text()
    arms = ("base", "off", "on")
    for category in data["arms"]["base"]["categories"]:
        values = [data["arms"][a]["categories"][category] for a in arms]
        direct = " / ".join(str(v["direct_correct"]) for v in values)
        reasoning = " / ".join(str(v["reasoning_correct"]) for v in values)
        assert f"| {category} | {direct} | {reasoning} |" in text
    for a, b in (("base", "off"), ("base", "on"), ("off", "on")):
        label = "Base" if a == "base" else "Off"
        for endpoint, key in (
            ("Direct / 280", "direct:correct"),
            ("Tie-free direct / 280", "direct:strict_correct"),
            ("Reasoning / 28", "reasoning:correct"),
        ):
            counts = data["paired"][f"{a}:{b}"][key]["counts"]
            nums = " | ".join(
                str(counts[k])
                for k in ("candidate_only", "base_only", "both_correct", "both_wrong")
            )
            assert f"| {endpoint} | {label} → {b} | {nums} |" in text
    nested, strict = [], []
    for arm in arms:
        folder = bench.HERE / "furnace/raw" / arm
        ids = {r["id"] for r in bench.bank.judge.read_lines(folder / "reasoning.jsonl")}
        rows = [r for r in bench.bank.judge.read_lines(folder / "direct.jsonl") if r["id"] in ids]
        assert len(rows) == 28
        nested.append(sum(r["correct"] for r in rows))
        strict.append(sum(r["strict_correct"] for r in rows))
    assert nested == [12, 10, 11] and strict == [11, 10, 11]


def test_published_judge_domain_tables_include_all_pairs():
    data = json.loads((judge.HERE / "analysis/ANALYSIS.json").read_text())
    text = (judge.HERE / "README.md").read_text()
    for domain in ("code", "reasoning", "writing"):
        columns = []
        for arms in (["base", "off"], ["base", "on"], ["off", "on"]):
            rows = [
                r
                for r in data["frozen_replay"]["pairs"]
                if r["arms"] == arms and r["unit"][0].startswith(domain + "-")
            ]
            assert len(rows) == 8
            counts = judge.Counter(r["outcome"] for r in rows)
            columns.append(
                " / ".join(str(counts[k]) for k in ("A", "B", "tie", "order_conflict", "unjudged"))
            )
        assert f"| {domain.title()} | " + " | ".join(columns) + " |" in text


def test_new_publication_links_resolve_outside_literal_fences():
    files = [
        ROOT / "README.md",
        ROOT / "docs/v23/EVALUATION_SYNTHESIS.md",
        ROOT / "docs/v23/NEXT_FACTORS.md",
        ROOT / "docs/v23/FULL_FT_REVIEW_GUIDE.md",
        ROOT / "docs/v23/LOCAL_VALIDATION.md",
        *[
            here / name
            for here in (bench.HERE, judge.HERE)
            for name in ("README.md", "EXECUTION_HANDOFF.md")
        ],
        bench.HERE / "analysis/REASONING_BANK.md",
        judge.HERE / "analysis/JUDGMENT_BANK.md",
    ]
    for file in files:
        text = re.sub(r"(?ms)^(`{3,})[^\n]*\n.*?^\1\s*$", "", file.read_text())
        for target in re.findall(r"\[[^\]\n]+\]\(([^)\n]+)\)", text):
            if target.startswith(("https://", "http://", "#", "mailto:")):
                continue
            assert (file.parent / target.split("#", 1)[0]).exists(), (file, target)
