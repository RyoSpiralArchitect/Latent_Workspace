"""Offline consistency checks for the additive English synthesis, not quality gates."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs/v14"
SUMMARY = ROOT / "provenance/pilots/v14_judge_capacity_20261009/analysis/SUMMARY.json"
METHODS = ("openai", "gemini", "mistral_enlarged")


def load_summary():
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def outcome_counts(report):
    labels = {"workspace": "W", "base": "B", "tie": "T"}
    counts = Counter()
    for repeat in report["replicates"]:
        if repeat["judge_status"] == "order_consistent":
            counts[labels[repeat["order_consistent_preference"]]] += 1
        elif repeat["judge_status"] == "order_conflict":
            counts["C"] += 1
        else:
            counts["I"] += 1
    assert sum(counts.values()) == 5
    return " ".join(
        f"{label}{counts[label]}" for label in ("W", "B", "T", "C", "I") if counts[label]
    )


def test_all_changed_pair_rows_match_sealed_repeat_outcomes():
    result = load_summary()
    text = (DOCS / "FT_BETA_JUDGE_SYNTHESIS.md").read_text(encoding="utf-8")
    changed = [p for p in result["pairs"] if not p["calibration_only"]]
    assert len(changed) == result["selection_counts"]["changed_pairs"] == 10
    for pair in changed:
        case = re.sub(r"^general-[0-9]+-", "", pair["case_id"])
        values = [outcome_counts(pair["methods"][method]) for method in METHODS]
        line = f"| {case} / {pair['regime']} | " + " | ".join(values) + " |"
        assert line in text


@pytest.mark.parametrize(
    "method,label",
    [
        ("openai", "OpenAI `gpt-5.4-2026-03-05`, low, 4,000-token cap"),
        ("gemini", "Gemini `gemini-3.8-flash`, LOW, 4,000-token cap"),
        ("mistral_enlarged", "Mistral Large 4, temperature 0.2, 16,384-token cap"),
    ],
)
def test_provider_summary_matches_sealed_counts(method, label):
    report = load_summary()["providers"][method]
    text = (DOCS / "FT_BETA_JUDGE_SYNTHESIS.md").read_text(encoding="utf-8")
    stable = report["changed_stable_counts"]
    line = (
        f"| {label} | {report['durable_responses']} / {report['planned_requests']} | "
        f"{report['valid_judgments']} | {stable['workspace']} / {stable['tie']} / "
        f"{stable['nonstable']} | {stable['base']} | {report['control_stable_ties']} / 4 |"
    )
    assert line in text


@pytest.mark.parametrize(
    "name", ["README.md", "FT_BETA_JUDGE_SYNTHESIS.md", "FT_BETA_IMPROVEMENT_PLAN.md"]
)
def test_new_document_local_evidence_links_resolve(name):
    text = (DOCS / name).read_text(encoding="utf-8")
    links = re.findall(r"\]\(([^)]+)\)", text)
    assert links
    for link in links:
        if "://" in link or link.startswith("#"):
            continue
        path = (DOCS / link.split("#", 1)[0]).resolve()
        assert path.is_relative_to(ROOT)
        assert path.is_file(), link


def test_shared_preference_and_partial_validity_are_not_promoted():
    result = load_summary()
    shared = [
        (p["case_id"], p["regime"])
        for p in result["pairs"]
        if not p["calibration_only"]
        and all(p["methods"][m]["stable_all_five_preference"] == "workspace" for m in METHODS)
    ]
    assert shared == [("general-05-causal", "sample211")]
    assert result["providers"]["mistral_enlarged"]["observation_status_counts"] == {
        "completed": 136,
        "invalid_judgment": 4,
    }
    assert result["winner"] == "none"
    assert result["non_regression"] == "NOT_ESTABLISHED"
    assert result["human_evaluation"] == "PENDING"


def test_proposed_exit_contract_keeps_zero_tolerance_and_missingness_explicit():
    text = (DOCS / "FT_BETA_IMPROVEMENT_PLAN.md").read_text(encoding="utf-8")
    assert "PROPOSED / NOT_TRAINED / NOT_RELEASE_QUALIFIED" in text
    assert "candidate_score - pinned_base_score >= 0" in text
    assert "delta = 0" in text
    assert "INCONCLUSIVE" in text
    assert "infrastructure missingness blocks the claim" in text
    assert "not yet fixed or\nimplemented" in text
