import copy
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import prepare_v14_judge_panel as panel  # noqa: E402


@pytest.fixture
def sources():
    return tuple(
        json.loads((REPO / panel.SOURCES[name]["path"]).read_text())
        for name in ("source_bank", "source_cases", "source_pairs")
    )


def test_selection_includes_all_changed_pairs_and_fixed_real_controls(sources):
    selected = panel.select(*sources)
    old_pairs = sources[2]["pairs"]
    changed = {pair["pair_id"] for pair in old_pairs if not pair["exact_identical"]}
    actual = {pair["pair_id"] for pair in selected["pairs"] if not pair["calibration_only"]}
    assert actual == changed and len(actual) == 10
    controls = [pair for pair in selected["pairs"] if pair["calibration_only"]]
    assert {pair["case_id"] for pair in controls} == set(panel.CONTROL_CASES)
    assert all(
        pair["regime"] == "greedy"
        and pair["comparison"] == "centered_semantic"
        and pair["base_answer"] == pair["workspace_answer"]
        for pair in controls
    )
    assert selected["counts"]["changed_pairs_by_lane"] == {"general": 5, "relation": 5}
    assert selected["counts"]["changed_pairs_by_comparison"] == {
        "legacy_semantic": 10,
        "centered_semantic": 0,
    }
    assert selected["counts"]["changed_unique_cases"] == 7
    assert selected["counts"]["changed_world_task_clusters"] == 6
    assert selected["counts"]["selected_unique_cases"] == 11
    assert selected["counts"]["selected_world_task_clusters"] == 9
    assert len(selected["cases"]) == 16
    assert all(set(case) == set(panel.CASE_FIELDS) for case in selected["cases"])
    for pair in selected["pairs"]:
        assert pair["pair_id"] == panel.identifier(
            pair["case_id"], pair["regime"], pair["comparison"]
        )
        assert pair["calibration_only"] is pair["exact_identical"]
        assert "judge_status" not in pair and "winner" not in pair and "scores" not in pair


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_answer",
        "duplicate_answer",
        "missing_pair",
        "duplicate_pair",
        "wrong_pair_id",
        "unequal_prompt",
        "unknown_finish",
        "fabricated_answer",
        "judge_verdict_in_pair",
        "calibration_tokens_changed",
        "duplicate_case",
    ],
)
def test_incomplete_or_altered_sources_fail_closed(sources, mutation):
    bank, cases, pairs = copy.deepcopy(sources)
    if mutation == "missing_answer":
        bank["rows"].pop()
    elif mutation == "duplicate_answer":
        bank["rows"][-1] = copy.deepcopy(bank["rows"][0])
    elif mutation == "missing_pair":
        pairs["pairs"].pop()
    elif mutation == "duplicate_pair":
        pairs["pairs"][-1] = copy.deepcopy(pairs["pairs"][0])
    elif mutation == "wrong_pair_id":
        pairs["pairs"][0]["pair_id"] = "unbound"
    elif mutation == "unequal_prompt":
        next(row for row in bank["rows"] if row["condition"] == "legacy_semantic")["prompt_ids"] = [
            99
        ]
    elif mutation == "unknown_finish":
        bank["rows"][0]["finish_reason"] = "success"
    elif mutation == "fabricated_answer":
        pairs["pairs"][0]["base_answer"] = "not the generated answer"
    elif mutation == "judge_verdict_in_pair":
        pairs["pairs"][0]["winner"] = "workspace"
    elif mutation == "calibration_tokens_changed":
        row = next(
            row
            for row in bank["rows"]
            if row["case_id"] == panel.CONTROL_CASES[0]
            and row["regime"] == "greedy"
            and row["condition"] == "centered_semantic"
        )
        row["generated_ids"][0] += 1
    else:
        cases["cases"][-1] = copy.deepcopy(cases["cases"][0])
    with pytest.raises(ValueError):
        panel.select(bank, cases, pairs)


def test_reproduce_without_loading_any_prior_judgments(tmp_path, monkeypatch):
    allowed = {REPO / spec["path"] for spec in panel.SOURCES.values()}
    original_read = Path.read_text

    def restricted_read(path, *args, **kwargs):
        assert path in allowed or path.is_relative_to(tmp_path)
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", restricted_read)
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    receipt = panel.prepare(first)
    assert panel.prepare(second) == receipt
    assert first.read_bytes() == second.read_bytes()
    assert panel.prepare(first, check=True) == receipt
    first.write_text(first.read_text() + "human note\n")
    before = first.read_bytes()
    with pytest.raises(FileExistsError):
        panel.prepare(first)
    assert first.read_bytes() == before


def test_changed_bound_source_fails_before_creating_output(tmp_path):
    bad_root = tmp_path / "repo"
    bank = bad_root / panel.SOURCES["source_bank"]["path"]
    bank.parent.mkdir(parents=True)
    bank.write_text("{}")
    output = tmp_path / "selection.json"
    with pytest.raises(ValueError, match="Frozen source changed"):
        panel.prepare(output, root=bad_root)
    assert not output.exists()
