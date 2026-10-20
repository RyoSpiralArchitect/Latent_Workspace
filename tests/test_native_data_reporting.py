"""Offline reporting must preserve bytes, missingness and rejected candidates."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import count_native_bank_tokens as count  # noqa: E402
import report_native_data_preparation as report  # noqa: E402


def test_terminal_manifest_detects_changes(tmp_path):
    report.ex.write_new(tmp_path / "data.json", {"value": 1})
    report.ex.write_new(tmp_path / "FINISHED.json", {"files": report.ex.manifest(tmp_path)})
    report.verify_terminal(tmp_path)
    (tmp_path / "data.json").write_text('{"value":2}')
    with pytest.raises(ValueError, match="Terminal bytes changed"):
        report.verify_terminal(tmp_path)


def test_literal_panel_preserves_trailing_spaces_and_code_fences():
    text = "answer  \n```\ncode\n```\n"
    rendered = report.fence(text)
    assert text in rendered and rendered.startswith("````")


def test_token_counts_do_not_select_only_structural_successes(tmp_path):
    (tmp_path / "run").mkdir()
    rows = [
        {"row": {"row_id": str(i), "query": "old", "answer": "old", "memory": ""}}
        for i in range(3)
    ]
    report.ex.write_new(tmp_path / "INPUTS.json", rows)
    report.ex.write_new(
        tmp_path / "run" / "outcome_000.json",
        {"status": "STRUCTURE_FAIL", "candidate": {"question": "new", "answer": "response"}},
    )
    report.ex.write_new(tmp_path / "run" / "outcome_001.json", {"status": "TRUNCATED"})
    report.ex.write_new(tmp_path / "run" / "FINISHED.json", {})
    selected, metadata = count.select_rows(None, tmp_path)
    assert len(selected) == 1 and selected[0]["query"] == "new"
    assert metadata["teacher_indices_without_countable_text"] == [1, 2]
    assert metadata["teacher_request_statuses"] == {
        "STRUCTURE_FAIL": 1,
        "TRUNCATED": 1,
        "NOT_ATTEMPTED": 1,
    }
