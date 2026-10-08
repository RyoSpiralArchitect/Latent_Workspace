import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import judge_v14_answer_bank as judge  # noqa: E402
import verify_v14_answer_bank_judge as verifier  # noqa: E402


@pytest.fixture
def artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(judge, "dispatch", lambda *_: pytest.fail("Verifier attempted API"))
    cases = {"cases": [{"id": f"case-{i:02d}", "lane": "general" if i < 8 else "relation",
                        "user_prompt": "Synthetic question", "reference": {"original": "answer"},
                        "rubric": ["Use supplied facts."]} for i in range(16)]}
    cases_path = tmp_path / "cases.json"
    judge.write_json(cases_path, cases)
    plan = {
        "cases": {"path": "cases.json", "sha256": judge.file_sha(cases_path)},
        "source_identity": {"scripts/judge_v14_answer_bank.py":
                            judge.file_sha(Path(judge.__file__))},
        "judge": {"model": "gpt-5.4-2026-03-05", "reasoning_effort": "low",
                  "max_output_tokens": 4000, "max_calls": 192,
                  "max_total_output_tokens": 768000, "max_cost_usd": None,
                  "input_usd_per_million_tokens": 2.5, "output_usd_per_million_tokens": 15},
    }
    plan_path = tmp_path / "plan.json"
    judge.write_json(plan_path, plan)
    bank = {"format": "latent-workspace-v14-answer-bank-v1",
            "plan_sha256": judge.file_sha(plan_path), "rows": [{
                "case_id": case["id"], "regime": regime, "condition": condition,
                "answer": "same answer", "finish_reason": "eos",
            } for case in cases["cases"] for regime in ("greedy", "sample211", "sample212")
            for condition in judge.CONDITIONS]}
    bank_path = tmp_path / "bank.json"
    judge.write_json(bank_path, bank)
    output = tmp_path / "judge"
    pairs, case_map = judge.prepare_pairs(cases, bank)
    requests = judge.prepare_requests(pairs, case_map, plan["judge"])
    snapshot = verifier.expected_snapshot(plan_path, cases_path, bank_path, plan["judge"],
                                          pairs, requests)
    judge.write_json(output / "SNAPSHOT.json", snapshot)
    judge.write_json(output / "PAIRS.json", {"pairs": pairs})
    judge.write_json(output / "PREPARED_REQUESTS.json", {"requests": requests})
    receipts = []
    for item in requests:
        verdict = {
            "scores": {side: {dim: 3 for dim in judge.DIMENSIONS} for side in ("A", "B")},
            "dimension_analysis_ja": {dim: "同じ回答です。" for dim in judge.DIMENSIONS},
            "winner": "tie", "quoted_evidence": {"A": ["same answer"], "B": ["same answer"]},
            "changes_ja": [], "risks_ja": [], "rationale_ja": "同文です。", "uncertainty_ja": "",
        }
        raw = {"id": "mock-" + item["request_id"], "model": plan["judge"]["model"],
               "status": "completed", "usage": {
                   "input_tokens": 100, "output_tokens": 200, "total_tokens": 300,
               }, "output": [{"type": "message", "content": [
                   {"type": "output_text", "text": json.dumps(verdict)},
               ]}]}
        response_path = output / "responses" / (item["request_id"] + ".json")
        judge.write_json(response_path, raw)
        receipt = {**item, "status": "response_recorded", "reserved_at": "mock-timestamp",
                   "response_sha256": judge.file_sha(response_path),
                   "observation": judge.response_observation(raw, item["body"]),
                   "usage_receipt": judge.usage_receipt(raw, item, plan["judge"])}
        judge.write_json(output / "requests" / (item["request_id"] + ".json"), receipt)
        receipts.append(receipt)
    write_summary(output, pairs, receipts, snapshot, len(requests))
    return bank_path, plan_path, cases_path, output


def write_summary(output, pairs, receipts, snapshot, request_count):
    result = judge.summarize(pairs, receipts)
    result.update(snapshot=snapshot, stopped_on_failure=False,
                  undispatched_requests=request_count - len(receipts),
                  usage=judge.usage_summary(receipts))
    judge.write_json(output / "SUMMARY.json", result)


def test_complete_receipt_grid_recomputed_without_api(artifacts):
    result = verifier.verify(*artifacts)
    assert result["status"] == "VERIFIED_RECEIPT_CLOSURE"
    assert result["planned_pairs"] == 96 and result["planned_requests"] == 8
    assert result["valid_judgments"] == 8
    assert result["usage"]["reported_total_tokens"] == 2400
    assert result["usage"]["actual_billed_cost_usd"] is None


@pytest.mark.parametrize("artifact", ["SNAPSHOT.json", "PAIRS.json", "PREPARED_REQUESTS.json"])
def test_frozen_preparation_tampering_rejected(artifacts, artifact):
    path = artifacts[-1] / artifact
    value = judge.load_json(path)
    value["extra_unbound"] = True
    judge.write_json(path, value)
    with pytest.raises(ValueError, match="mismatch"):
        verifier.verify(*artifacts)


@pytest.mark.parametrize("field", ["body", "observation", "usage_receipt", "response_sha256"])
def test_receipt_tampering_rejected(artifacts, field):
    path = next((artifacts[-1] / "requests").glob("*.json"))
    receipt = judge.load_json(path)
    receipt[field] = None
    judge.write_json(path, receipt)
    with pytest.raises(ValueError, match="mismatch"):
        verifier.verify(*artifacts)


def test_raw_response_tampering_rejected(artifacts):
    path = next((artifacts[-1] / "responses").glob("*.json"))
    raw = judge.load_json(path)
    raw["id"] = "changed"
    judge.write_json(path, raw)
    with pytest.raises(ValueError, match="Response hash"):
        verifier.verify(*artifacts)


def test_summary_preference_and_usage_tampering_rejected(artifacts):
    path = artifacts[-1] / "SUMMARY.json"
    summary = judge.load_json(path)
    summary["pairs"][0]["order_consistent_preference"] = "workspace"
    judge.write_json(path, summary)
    with pytest.raises(ValueError, match="Full SUMMARY"):
        verifier.verify(*artifacts)


def test_invalid_quote_is_explicit_not_a_mechanical_failure(artifacts):
    output = artifacts[-1]
    request_path = next((output / "requests").glob("*.json"))
    receipt = judge.load_json(request_path)
    response_path = output / "responses" / request_path.name
    raw = judge.load_json(response_path)
    verdict = json.loads(raw["output"][0]["content"][0]["text"])
    verdict["quoted_evidence"]["A"] = ["invented evidence"]
    raw["output"][0]["content"][0]["text"] = json.dumps(verdict)
    judge.write_json(response_path, raw)
    receipt.update(response_sha256=judge.file_sha(response_path),
                   observation=judge.response_observation(raw, receipt["body"]))
    judge.write_json(request_path, receipt)
    reprepare_summary(output)
    result = verifier.verify(*artifacts)
    assert result["status"] == "VERIFIED_RECEIPT_CLOSURE"
    assert result["valid_judgments"] == 7
    assert result["observation_status_counts"]["invalid_judgment"] == 1


def reprepare_summary(output):
    requests = judge.load_json(output / "PREPARED_REQUESTS.json")["requests"]
    paths = [output / "requests" / (row["request_id"] + ".json") for row in requests]
    receipts = [judge.load_json(path) for path in paths if path.is_file()]
    write_summary(output, judge.load_json(output / "PAIRS.json")["pairs"], receipts,
                  judge.load_json(output / "SNAPSHOT.json"), len(requests))


def test_reserved_pending_remains_incomplete_even_with_durable_response(artifacts):
    path = next((artifacts[-1] / "requests").glob("*.json"))
    receipt = judge.load_json(path)
    for field in ("observation", "usage_receipt", "response_sha256"):
        receipt.pop(field)
    receipt["status"] = "reserved_pending"
    judge.write_json(path, receipt)
    reprepare_summary(artifacts[-1])
    result = verifier.verify(*artifacts)
    assert result["status"] == "INCOMPLETE_RECEIPTS"
    assert len(result["unresolved_requests_with_durable_body"]) == 1
    assert judge.load_json(path)["status"] == "reserved_pending"  # No recovery mutation.


def test_missing_request_and_response_remain_incomplete(artifacts):
    path = next((artifacts[-1] / "requests").glob("*.json"))
    (artifacts[-1] / "responses" / path.name).unlink()
    path.unlink()
    reprepare_summary(artifacts[-1])
    result = verifier.verify(*artifacts)
    assert result["status"] == "INCOMPLETE_RECEIPTS"
    assert len(result["missing_request_ids"]) == 1


def test_unreserved_extra_response_is_rejected(artifacts):
    judge.write_json(artifacts[-1] / "responses" / "outside-grid.json", {"id": "extra"})
    with pytest.raises(ValueError, match="outside prepared"):
        verifier.verify(*artifacts)


def test_per_invocation_runtime_flag_is_only_unrecomputed_summary_field(artifacts):
    path = artifacts[-1] / "SUMMARY.json"
    summary = judge.load_json(path)
    summary["stopped_on_failure"] = True
    judge.write_json(path, summary)
    assert verifier.verify(*artifacts)["mechanical_receipt_closure"]
    summary["undispatched_requests"] = 99
    judge.write_json(path, summary)
    with pytest.raises(ValueError, match="Full SUMMARY"):
        verifier.verify(*artifacts)


def test_symlink_receipt_is_rejected(artifacts):
    path = next((artifacts[-1] / "requests").glob("*.json"))
    stored = artifacts[-1] / "saved.json"
    path.rename(stored)
    path.symlink_to(stored)
    with pytest.raises(ValueError, match="nonregular"):
        verifier.verify(*artifacts)
