import copy
import csv
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import render_v14_answer_bank as renderer  # noqa: E402


@pytest.fixture
def fixture():
    cases = json.loads((ROOT / "data/v14_answer_bank/cases.json").read_text())
    rows = []
    for case in cases["cases"]:
        for regime, parameters in renderer.REGIMES.items():
            for condition in renderer.CONDITIONS:
                rows.append(
                    {
                        "id": "__".join((case["id"], regime, condition)),
                        "case_id": case["id"],
                        "lane": case["lane"],
                        "regime": regime,
                        "regime_parameters": copy.deepcopy(parameters),
                        "condition": condition,
                        "answer": f"ANSWER {case['id']} {regime} "
                        f"variant-{renderer.CONDITIONS.index(condition)}",
                        "rendered_prompt": case["user_prompt"],
                        "finish_reason": "eos",
                        "token_count": 2,
                        "generated_ids": [11, 2],
                    }
                )
    return cases, {"format": "latent-workspace-v14-answer-bank-v1", "rows": rows}


def _inputs(tmp_path, fixture):
    cases, bank = fixture
    cases_path, bank_path = tmp_path / "cases.json", tmp_path / "bank.json"
    cases_path.write_text(json.dumps(cases, ensure_ascii=False))
    bank_path.write_text(json.dumps(bank, ensure_ascii=False))
    return cases_path, bank_path


def _judge(fixture, cases_path, bank_path):
    cases, bank = fixture
    case_map, indexed = renderer.validate(cases, bank)
    pairs = renderer.make_pairs(case_map, indexed)
    result = {
        "format": "latent-workspace-v14-answer-bank-judge-summary-v1",
        "snapshot": {
            "bank_sha256": renderer.digest(bank_path),
            "cases_sha256": renderer.digest(cases_path),
        },
        "pair_count": 96,
        "pairs": [],
    }
    for pair in pairs:
        result["pairs"].append(
            {
                **{
                    field: pair[field]
                    for field in (
                        "pair_id",
                        "case_id",
                        "lane",
                        "regime",
                        "comparison",
                    )
                },
                "base_answer": pair["base"]["answer"],
                "workspace_answer": pair["workspace"]["answer"],
                "exact_identical": False,
                "judge_status": "missing_or_invalid_order",
                "order_consistent_preference": None,
                "observations": [
                    {
                        "request_id": pair["pair_id"] + "-" + order,
                        "order": order,
                        "status": "not_dispatched",
                        "response_model": None,
                        "response_id": None,
                        "judgment": None,
                    }
                    for order in ("AB", "BA")
                ],
            }
        )
    return result


def _verdict(answer_a, answer_b):
    return {
        "winner": "tie",
        "scores": {
            side: {dimension: 2 for dimension in renderer.DIMENSIONS} for side in ("A", "B")
        },
        "quoted_evidence": {"A": [answer_a], "B": [answer_b]},
        "dimension_analysis_ja": {dimension: "差は未確認。" for dimension in renderer.DIMENSIONS},
        "changes_ja": ["質的な向上は未確立。"],
        "risks_ja": [],
        "rationale_ja": "同点です。",
        "uncertainty_ja": "小規模な探索です。",
    }


def test_all_rows_pairs_and_blank_human_labels_retained_deterministically(tmp_path, fixture):
    cases_path, bank_path = _inputs(tmp_path, fixture)
    summary = renderer.render(bank_path, cases_path, tmp_path / "first")
    assert summary["denominators"]["answers"] == 336
    assert summary["denominators"]["human_pairs"] == 96
    assert summary["human_completed_labels"] == 0
    assert summary["human_evaluation"] == "PENDING"
    assert summary["non_regression"] == "NOT_ESTABLISHED"
    renderer.render(bank_path, cases_path, tmp_path / "second")
    first, second = tmp_path / "first", tmp_path / "second"
    assert {path.name: path.read_bytes() for path in first.iterdir()} == {
        path.name: path.read_bytes() for path in second.iterdir()
    }
    full = (first / "ANSWER_BANK.md").read_text()
    for row in fixture[1]["rows"]:
        assert row["answer"] in full
    human = (first / "HUMAN_REVIEW.md").read_text()
    assert "legacy_semantic" not in human and "centered_semantic" not in human
    for case in fixture[0]["cases"]:
        assert case["id"] in full and case["id"] in human
    records = list(csv.DictReader((first / "human_scores.csv").open()))
    assert len(records) == len({row["pair_id"] for row in records}) == 96
    assert Counter(row["lane"] for row in records) == {"general": 48, "relation": 48}
    for row in records:
        assert row["status"] == "pending"
        for field in renderer.HUMAN_FIELDS[5:]:
            assert row[field] == ""
    key = json.loads((first / "HUMAN_KEY.json").read_text())
    assert sum(row["A"]["condition"] == "base" for row in key["mapping"]) == 48
    assert sum(row["B"]["condition"] == "base" for row in key["mapping"]) == 48
    assert "NOT_PROVIDED" in (first / "JUDGE_REVIEW.md").read_text()


def test_model_and_prompt_markup_is_data_not_executable_markdown(tmp_path, fixture):
    malicious = '</pre><script>alert("x")</script>\n```html\n<img src=x onerror="boom">\n```\n|x|'
    fixture[1]["rows"][0]["answer"] = malicious
    fixture[1]["rows"][0]["rendered_prompt"] = malicious
    fixture[0]["cases"][0]["user_prompt"] = malicious
    cases_path, bank_path = _inputs(tmp_path, fixture)
    renderer.render(bank_path, cases_path, tmp_path / "review")
    text = (tmp_path / "review" / "ANSWER_BANK.md").read_text()
    assert "<script>" not in text and "<img src=x" not in text
    assert "&lt;/pre&gt;&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in text
    assert "```html" in text  # Remains literal text inside escaped HTML pre.
    assert (
        renderer.pre("<a title='v'>&</a>")
        == "<pre>&lt;a title=&#x27;v&#x27;&gt;&amp;&lt;/a&gt;</pre>"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "unknown_condition",
        "unknown_regime",
        "unknown_lane",
        "unknown_finish",
        "changed_seed",
        "token_count",
        "wrong_id",
        "duplicate_case",
    ],
)
def test_unknown_labels_or_nonclosed_grid_fail_before_output(tmp_path, fixture, mutation):
    cases, bank = fixture
    row = bank["rows"][0]
    if mutation == "missing":
        bank["rows"].pop()
    elif mutation == "duplicate":
        bank["rows"][-1] = copy.deepcopy(row)
    elif mutation == "unknown_condition":
        row["condition"] = "winner_model"
    elif mutation == "unknown_regime":
        row["regime"] = "sample999"
    elif mutation == "unknown_lane":
        row["lane"] = "quality_proven"
    elif mutation == "unknown_finish":
        row["finish_reason"] = "success"
    elif mutation == "changed_seed":
        row["regime_parameters"]["seed"] = 99
    elif mutation == "token_count":
        row["token_count"] = 3
    elif mutation == "wrong_id":
        row["id"] += "changed"
    else:
        cases["cases"][-1] = copy.deepcopy(cases["cases"][0])
    cases_path, bank_path = _inputs(tmp_path, fixture)
    output = tmp_path / "review"
    with pytest.raises(ValueError):
        renderer.render(bank_path, cases_path, output)
    assert not output.exists()


def test_existing_human_annotations_cannot_be_overwritten(tmp_path, fixture):
    cases_path, bank_path = _inputs(tmp_path, fixture)
    output = tmp_path / "review"
    renderer.render(bank_path, cases_path, output)
    edited = output / "human_scores.csv"
    edited.write_text(edited.read_text() + "MANUALLY REVIEWED\n")
    snapshot = {path.name: path.read_bytes() for path in output.iterdir()}
    with pytest.raises(FileExistsError, match="human annotations"):
        renderer.render(bank_path, cases_path, output)
    assert snapshot == {path.name: path.read_bytes() for path in output.iterdir()}


def test_optional_judge_quotes_ratings_are_separate_and_never_human_labels(tmp_path, fixture):
    cases_path, bank_path = _inputs(tmp_path, fixture)
    judge = _judge(fixture, cases_path, bank_path)
    row = judge["pairs"][0]
    row["judge_status"], row["order_consistent_preference"] = "order_consistent", "tie"
    for item in row["observations"]:
        a, b = row["base_answer"], row["workspace_answer"]
        if item["order"] == "BA":
            a, b = b, a
        item["status"] = "completed"
        item["judgment"] = _verdict(a, b)
        item["judgment"]["rationale_ja"] += '</pre><script>bad</script>"'
    judge_path = tmp_path / "judge.json"
    judge_path.write_text(json.dumps(judge))
    renderer.render(bank_path, cases_path, tmp_path / "review", judge_path)
    text = (tmp_path / "review" / "JUDGE_REVIEW.md").read_text()
    assert "同点です。" in text and "&lt;script&gt;bad&lt;/script&gt;" in text
    assert "A=base / B=workspace" in text and "A=workspace / B=base" in text
    assert "<script>bad" not in text
    human = (tmp_path / "review" / "HUMAN_REVIEW.md").read_text()
    assert "同点です。" not in human
    scores = list(csv.DictReader((tmp_path / "review" / "human_scores.csv").open()))
    assert all(row["winner"] == "" and row["status"] == "pending" for row in scores)


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_bank",
        "wrong_cases",
        "missing_pair",
        "duplicate_pair",
        "unknown_preference",
        "wrong_answer",
        "bad_quote",
        "unknown_winner",
        "duplicate_order",
    ],
)
def test_mismatched_or_invalid_judge_is_not_rendered(tmp_path, fixture, mutation):
    cases_path, bank_path = _inputs(tmp_path, fixture)
    judge = _judge(fixture, cases_path, bank_path)
    row = judge["pairs"][0]
    if mutation == "wrong_bank":
        judge["snapshot"]["bank_sha256"] = "wrong"
    elif mutation == "wrong_cases":
        judge["snapshot"]["cases_sha256"] = "wrong"
    elif mutation == "missing_pair":
        judge["pairs"].pop()
    elif mutation == "duplicate_pair":
        judge["pairs"][-1] = copy.deepcopy(row)
    elif mutation == "unknown_preference":
        row["order_consistent_preference"] = "great"
    elif mutation == "wrong_answer":
        row["base_answer"] += "not in source"
    elif mutation == "duplicate_order":
        row["observations"][1] = copy.deepcopy(row["observations"][0])
    else:
        item = row["observations"][0]
        item["status"] = "completed"
        item["judgment"] = _verdict(row["base_answer"], row["workspace_answer"])
        if mutation == "bad_quote":
            item["judgment"]["quoted_evidence"]["A"] = ["invented quote"]
        else:
            item["judgment"]["winner"] = "best"
    judge_path = tmp_path / "judge.json"
    judge_path.write_text(json.dumps(judge))
    with pytest.raises(ValueError):
        renderer.render(bank_path, cases_path, tmp_path / "review", judge_path)
    assert not (tmp_path / "review").exists()
