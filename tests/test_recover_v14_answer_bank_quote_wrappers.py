import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import judge_v14_answer_bank as judge  # noqa: E402
import recover_v14_answer_bank_quote_wrappers as recovery  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "receipt_test_fixture", ROOT / "tests/test_verify_v14_answer_bank_judge.py"
)
fixture_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture_module)
artifacts = fixture_module.artifacts


def raw_and_body(quote='"a literal answer"', answer="This is a literal answer."):
    verdict = {
        "scores": {side: {dim: 3 for dim in judge.DIMENSIONS} for side in ("A", "B")},
        "dimension_analysis_ja": {dim: "比較観察です。" for dim in judge.DIMENSIONS},
        "winner": "A", "quoted_evidence": {"A": [quote], "B": ["Other answer"]},
        "changes_ja": ["仮説候補"], "risks_ja": [], "rationale_ja": "比較です。",
        "uncertainty_ja": "確定ではない。",
    }
    body = {"model": "pinned-test-model", "input": [{"content": [{"text": json.dumps({
        "answer_A": answer, "answer_B": "Other answer",
    })}]}]}
    raw = {"status": "completed", "model": body["model"], "output": [{"content": [
        {"type": "output_text", "text": json.dumps(verdict)},
    ]}]}
    return raw, body


def test_only_one_ascii_wrapper_pair_removed_and_inputs_unchanged():
    raw, body = raw_and_body()
    before = copy.deepcopy((raw, body))
    result = recovery.recover_judgment(raw, body)
    assert result["recovered"]
    assert result["quote_changes"] == [{
        "side": "A", "index": 0, "before": '"a literal answer"', "after": "a literal answer",
        "removed_characters": ["U+0022", "U+0022"],
        "original_is_answer_substring": False, "recovered_is_exact_answer_substring": True,
    }]
    assert result["all_other_judgment_fields_unchanged"]
    assert result["before_nonquote_fields_sha256"] == result["after_nonquote_fields_sha256"]
    assert (raw, body) == before
    assert result["after_judgment"]["winner"] == "A"
    assert result["after_judgment"]["quoted_evidence"]["B"] == ["Other answer"]


@pytest.mark.parametrize("quote", [
    "a literal answer", '""a literal answer""', '" a literal answer "',
    "“a literal answer”", "'a literal answer'", '"a literal...answer"',
    '"a literal answer!"', '""', '"absent answer"',
])
def test_no_broader_normalization_or_recursive_removal(quote):
    raw, body = raw_and_body(quote)
    result = recovery.recover_judgment(raw, body)
    assert not result["recovered"]
    assert result["quote_changes"] == []


def test_already_valid_quotes_with_literal_wrappers_are_not_modified():
    raw, body = raw_and_body('"a literal answer"', 'He wrote "a literal answer".')
    result = recovery.recover_judgment(raw, body)
    assert not result["recovered"] and result["quote_changes"] == []


def test_other_validator_failure_prevents_partial_quote_recovery():
    raw, body = raw_and_body()
    verdict = json.loads(raw["output"][0]["content"][0]["text"])
    verdict["scores"]["B"]["correctness"] = 8
    raw["output"][0]["content"][0]["text"] = json.dumps(verdict)
    result = recovery.recover_judgment(raw, body)
    assert not result["recovered"]
    assert result["outcome"] == "still_invalid_after_wrapper_only_change"
    assert len(result["quote_changes"]) == 1
    assert result["after_judgment"]["scores"]["B"]["correctness"] == 8


def test_one_remaining_unrecoverable_quote_keeps_entire_judgment_invalid():
    raw, body = raw_and_body()
    verdict = json.loads(raw["output"][0]["content"][0]["text"])
    verdict["quoted_evidence"]["B"] = ["“Other answer”"]
    raw["output"][0]["content"][0]["text"] = json.dumps(verdict)
    result = recovery.recover_judgment(raw, body)
    assert not result["recovered"] and len(result["quote_changes"]) == 1


@pytest.mark.parametrize("failure", ["malformed_json", "wrong_model", "incomplete", "extra_text"])
def test_non_quote_response_failures_not_recovered(failure):
    raw, body = raw_and_body()
    if failure == "malformed_json":
        raw["output"][0]["content"][0]["text"] = "{broken json"
    elif failure == "wrong_model":
        raw["model"] = "not-pinned"
    elif failure == "incomplete":
        raw["status"] = "incomplete"
    else:
        raw["output"][0]["content"].append({"type": "output_text", "text": "extra"})
    assert not recovery.recover_judgment(raw, body)["recovered"]


def wrap_one_primary_quote(artifacts):
    output = artifacts[-1]
    request_path = next((output / "requests").glob("*.json"))
    receipt = judge.load_json(request_path)
    response_path = output / "responses" / request_path.name
    raw = judge.load_json(response_path)
    verdict = json.loads(raw["output"][0]["content"][0]["text"])
    verdict["quoted_evidence"]["A"] = ['"same answer"']
    raw["output"][0]["content"][0]["text"] = json.dumps(verdict)
    judge.write_json(response_path, raw)
    receipt.update(response_sha256=judge.file_sha(response_path),
                   observation=judge.response_observation(raw, receipt["body"]))
    assert receipt["observation"]["status"] == "invalid_judgment"
    judge.write_json(request_path, receipt)
    fixture_module.reprepare_summary(output)
    return request_path


def test_supplement_is_deterministic_separate_and_preserves_primary_bytes(artifacts, tmp_path):
    wrap_one_primary_quote(artifacts)
    primary_dir = artifacts[-1]
    before = {path: path.read_bytes() for path in primary_dir.rglob("*") if path.is_file()}
    first = recovery.build_supplement(*artifacts)
    assert first == recovery.build_supplement(*artifacts)
    assert first["status"] == recovery.STATUS
    assert first["primary_valid_judgments"] == 7 and first["supplemental_valid_judgments"] == 8
    assert len(first["recovered_request_ids"]) == len(first["recovery_attempts"]) == 1
    assert first["new_api_requests"] == 0 and first["primary_artifacts_modified"] is False
    assert first["primary_summary_sha256"] == judge.file_sha(primary_dir / "SUMMARY.json")
    output = tmp_path / "supplement"
    assert recovery.recover(*artifacts, output) == first
    assert {path.name for path in output.iterdir()} == {"SUMMARY.json", "REVIEW.md"}
    text = (output / "REVIEW.md").read_text()
    assert recovery.STATUS in text and "一次評価で有効: 7/8" in text
    assert "この補足で有効: 8/8" in text
    assert before == {path: path.read_bytes() for path in primary_dir.rglob("*") if path.is_file()}
    with pytest.raises(FileExistsError):
        recovery.recover(*artifacts, output)


def test_primary_valid_judgments_are_never_selected_for_recovery(artifacts):
    result = recovery.build_supplement(*artifacts)
    assert result["primary_valid_judgments"] == result["supplemental_valid_judgments"] == 8
    assert result["recovery_attempts"] == result["recovered_request_ids"] == []


def test_incomplete_primary_cannot_generate_supplement(artifacts):
    path = next((artifacts[-1] / "requests").glob("*.json"))
    (artifacts[-1] / "responses" / path.name).unlink()
    path.unlink()
    fixture_module.reprepare_summary(artifacts[-1])
    with pytest.raises(ValueError, match="closure must be complete"):
        recovery.build_supplement(*artifacts)
