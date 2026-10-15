from __future__ import annotations

import copy
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "render_v15_answer_bank_test", ROOT / "scripts/render_v15_answer_bank.py"
)
renderer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(renderer)
BUNDLE = ROOT / "provenance/pilots/v15_readout_transport_20261010"


@pytest.mark.parametrize(
    "text",
    [
        "yes",
        "no\n",
        "",
        "```\n# Injected\n```",
        "``````text\n<script>ignore</script>\n~~~~",
        "α\n\nβ",
    ],
)
def test_fences_preserve_literal_answer_and_cannot_be_closed_by_content(text):
    result = renderer.fenced(text)
    opening, payload = result.split("\n", 1)
    fence = opening[:-4]  # Strip the 'text' language identifier.
    assert set(fence) == {"`"} and len(fence) >= 3
    assert all(len(run) < len(fence) for run in re.findall(r"`+", text))
    assert payload == text + ("" if text.endswith("\n") else "\n") + fence


def test_complete_actual_bank_is_readable_and_preserves_every_answer():
    rendered = renderer.render_bundle(BUNDLE)
    raw = renderer.load(BUNDLE / "raw/GENERATION.json")
    assert len(re.findall(r"^## World ", rendered, flags=re.MULTILINE)) == 8
    assert (
        sum(
            len(re.findall(rf"^### {condition}$", rendered, flags=re.MULTILINE))
            for condition in renderer.CONDITIONS
        )
        == 64
    )
    assert "Strictly correct: **0/64**" in rendered
    assert "Whole-answer unparseable: **64/64**" in rendered
    assert "Length-capped at 64 new tokens: **63/64**" in rendered
    assert "not rescued as a correct whole answer" in rendered
    assert "confounds content and serialization" in rendered
    assert "does not carry continuous hidden state or a KV cache" in rendered
    for row in raw["rows"]:
        assert renderer.fenced(row["answer"]) in rendered
    for header in (
        "Target",
        "Finish",
        "Tokens",
        "Strict correct",
        "First divergence from base",
        "Initial max absolute Δlogit",
        "Initial Δp(chosen)",
    ):
        assert header in rendered


def test_renderer_is_independent_of_raw_row_order():
    raw = renderer.load(BUNDLE / "raw/GENERATION.json")
    features = renderer.load(BUNDLE / "raw/FEATURES.json")
    summary = renderer.load(BUNDLE / "SUMMARY.json")
    first = renderer.render_verified(raw, features, summary)
    raw["rows"].reverse()
    assert renderer.render_verified(raw, features, summary) == first


@pytest.mark.parametrize("mutation", ["missing", "duplicate"])
def test_renderer_never_silently_selects_subset(mutation):
    raw = renderer.load(BUNDLE / "raw/GENERATION.json")
    if mutation == "missing":
        raw["rows"].pop()
    else:
        raw["rows"][-1] = copy.deepcopy(raw["rows"][0])
    with pytest.raises(ValueError):
        renderer.render_verified(
            raw, renderer.load(BUNDLE / "raw/FEATURES.json"), renderer.load(BUNDLE / "SUMMARY.json")
        )


def test_saved_summary_must_match_verified_bundle(monkeypatch):
    expected = renderer.load(BUNDLE / "SUMMARY.json")
    expected["generation"]["summary"]["base"]["strict_correct"] = 99
    monkeypatch.setattr(renderer, "verify_bundle", lambda _: expected)
    with pytest.raises(ValueError, match="SUMMARY differs"):
        renderer.render_bundle(BUNDLE)


def test_exclusive_creation_and_check_mode_never_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(renderer, "render_bundle", lambda _: "exact\n")
    assert renderer.write_or_check(tmp_path)["status"] == "CREATED"
    assert renderer.write_or_check(tmp_path, check=True)["status"] == "MATCHED"
    with pytest.raises(FileExistsError):
        renderer.write_or_check(tmp_path)
    destination = tmp_path / "ANSWER_BANK.md"
    destination.write_text("changed\n")
    with pytest.raises(ValueError, match="differs from verified render"):
        renderer.write_or_check(tmp_path, check=True)
    assert destination.read_text() == "changed\n"


def test_first_divergence_labels_are_explicitly_one_and_zero_based():
    assert renderer.divergence_text(0) == "token 1 (step 0)"
    assert renderer.divergence_text(4) == "token 5 (step 4)"
    assert renderer.divergence_text(None) == "none"
    assert renderer.divergence_text(None, base=True) == "reference"
