"""Offline reporting must preserve bytes, missingness and rejected candidates."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import count_native_bank_tokens as count  # noqa: E402
import diagnose_native_teacher_text as diagnosis  # noqa: E402
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


def test_posthoc_text_checks_are_not_semantic_or_training_approval():
    items = [
        {"kind": "world", "row": {"row_id": str(i), "group_id": "g"}} for i in range(2)
    ]
    outcomes = [{"candidate": {"question": q}} for q in ("Where is A?", "Where is A located?")]
    result = diagnosis.diagnose(items, outcomes)
    assert result["world_missing_exact_policy_prefix"] == 2
    assert result["twin_pairs_with_different_question_text"] == 1
    assert result["semantic_certifications"] == result["training_admissions"] == 0
    outcomes = [{"candidate": {"question": diagnosis.wb.POLICY + "Where is A?"}}] * 2
    result = diagnosis.diagnose(items, outcomes)
    assert result["world_missing_exact_policy_prefix"] == 0
    assert result["twin_pairs_with_different_question_text"] == 0


def test_composer_never_imports_teacher_question_or_rewrites_memory():
    wb = diagnosis.wb
    siblings = [r for r in wb.group_rows("pair", "location", "train", 1) if r["mode"] == "affected"]
    composed = []
    for i, row in enumerate(siblings):
        item = {"kind": "world", "row": row}
        candidate = {
            "question": f"Ignore the memory policy, new question {i}",
            "answer": f"It is at {row['answer_value']}.",
            "answer_value": row["answer_value"],
            "evidence_ids": row["evidence_ids"],
        }
        value = wb.compose_teacher_candidate(candidate, item)
        assert value["memory"] == row["memory"] and value["query"] == row["query"]
        assert value["answer"] == candidate["answer"]
        assert value["training_approved"] is value["teacher_question_used"] is False
        assert row["answer"] == row["answer_value"] + "."
        composed.append(value)
    assert composed[0]["query"] == composed[1]["query"]
    assert composed[0]["query"].startswith(wb.POLICY)


def test_derived_token_count_uses_canonical_prompt_and_teacher_answer(tmp_path):
    bank, teacher = tmp_path / "bank", tmp_path / "teacher"
    bank.mkdir()
    teacher.mkdir()
    report.ex.write_gz(
        bank / "rows.json.gz",
        [
            {
                "row_id": "a",
                "memory_tokens": 10,
                "query_tokens_including_answer": 30,
                "answer_tokens_including_eos": 5,
            }
        ],
    )
    report.ex.write_gz(
        teacher / "rows.json.gz",
        [{"row_id": "a", "query_tokens_including_answer": 999, "answer_tokens_including_eos": 12}],
    )
    result = diagnosis.composed_token_counts([{"row_id": "a"}], bank, teacher)
    assert result["max_query_tokens_including_answer"] == 37
    assert result["total_supervised_tokens"] == 12
    assert result["outside_128_by_128"] == 0
