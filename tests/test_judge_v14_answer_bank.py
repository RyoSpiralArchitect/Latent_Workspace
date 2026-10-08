import copy
import json
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import judge_v14_answer_bank as run  # noqa: E402


def fixtures():
    cases = {"cases": [{
        "id": f"c{number:02d}", "lane": "general" if number < 8 else "relation",
        "user_prompt": "質問です。", "reference": {"answer": "合成参照"},
        "rubric": ["正確で簡潔に答える"],
    } for number in range(16)]}
    bank = {"rows": [{
        "case_id": case["id"], "condition": condition, "regime": regime,
        "answer": "同じ回答です。",
    } for case in cases["cases"] for regime in ("greedy", "sample211", "sample212")
        for condition in run.CONDITIONS]}
    plan = {"judge": {
        "model": "gpt-5.4-2026-03-05", "reasoning_effort": "low",
        "max_output_tokens": 4000, "max_calls": 192, "max_total_output_tokens": 768000,
        "input_usd_per_million_tokens": "2.50", "output_usd_per_million_tokens": "15",
        "max_cost_usd": None, "max_input_tokens": 32000, "calibration_identical_pairs": 4,
        "output": "runs/test_judge", "endpoint": run.ENDPOINT,
    }}
    return plan, cases, bank


def judgment(a="同じ回答です。", b="同じ回答です。", winner="tie"):
    return {
        "scores": {side: {name: 3 for name in run.DIMENSIONS} for side in ("A", "B")},
        "dimension_analysis_ja": {name: "確認できる範囲で同等です。" for name in run.DIMENSIONS},
        "winner": winner, "quoted_evidence": {"A": [a] if a else [], "B": [b] if b else []},
        "changes_ja": [], "risks_ja": ["参照には限界がある。"],
        "rationale_ja": "観測範囲で同等です。", "uncertainty_ja": "人間による確認が必要。",
    }


def response(body):
    data = json.loads(body["input"][0]["content"][0]["text"])
    return {
        "id": "resp_test", "model": body["model"], "status": "completed",
        "usage": {"input_tokens": 200, "output_tokens": 300, "total_tokens": 500},
        "output": [{"type": "message", "content": [{"type": "output_text", "text":
                    json.dumps(judgment(data["answer_A"], data["answer_B"]))}]}],
    }


def write_fixture(tmp_path, plan=None, cases=None, bank=None):
    defaults = fixtures()
    paths = []
    for filename, value, default in zip(("plan.json", "cases.json", "bank.json"),
                                        (plan, cases, bank), defaults, strict=True):
        path = tmp_path / filename
        run.write_json(path, default if value is None else value)
        paths.append(path)
    return (*paths, tmp_path / "output")


def test_complete_pairs_retained_identical_deduplicated_and_blinded():
    plan, cases, bank = fixtures()
    pairs, case_map = run.prepare_pairs(cases, bank)
    requests = run.prepare_requests(pairs, case_map, plan["judge"])
    assert len(pairs) == 96
    assert sum(row["exact_identical"] for row in pairs) == 96
    assert sum(row["selected_for_identical_calibration"] for row in pairs) == 4
    assert len(requests) == 8
    assert {row["order"] for row in requests} == {"AB", "BA"}
    for row in requests:
        body = row["body"]
        assert body["store"] is False and body["service_tier"] == "default"
        assert body["text"]["format"]["strict"] is True
        serialized = json.dumps(body)
        assert "legacy_semantic" not in serialized and "centered_semantic" not in serialized
        assert "pair_id" not in serialized and "case_id" not in serialized
        data = json.loads(body["input"][0]["content"][0]["text"])
        assert data["reference_selection"] == "original"
        assert data["finish_reason_A"] == data["finish_reason_B"] == "unknown"


def test_changed_pairs_both_orders_and_no_fabricated_identical_controls():
    plan, cases, bank = fixtures()
    for row in bank["rows"]:
        if row["condition"] in run.COMPARISONS:
            row["answer"] = "変更回答です。"
    pairs, case_map = run.prepare_pairs(cases, bank)
    requests = run.prepare_requests(pairs, case_map, plan["judge"])
    assert len(requests) == 192
    assert not any(row["calibration_only"] for row in requests)
    first, second = [json.loads(row["body"]["input"][0]["content"][0]["text"])
                     for row in requests[:2]]
    assert first["answer_A"] == second["answer_B"]
    assert first["answer_B"] == second["answer_A"]
    assert first["answer_A"] != first["answer_B"]


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown_condition", "unfinished"])
def test_invalid_generation_denominators_fail_closed(mutation):
    _, cases, bank = fixtures()
    if mutation == "missing":
        bank["rows"].pop()
    elif mutation == "duplicate":
        bank["rows"].append(bank["rows"][0])
    elif mutation == "unknown_condition":
        bank["rows"][0]["condition"] = "winner_only"
    else:
        bank["rows"][0]["status"] = "failed"
    with pytest.raises(ValueError):
        run.prepare_pairs(cases, bank)


def test_invalid_cases_and_lane_counts_fail_closed():
    _, cases, bank = fixtures()
    cases["cases"][0]["lane"] = "relation"
    with pytest.raises(ValueError, match="eight"):
        run.prepare_pairs(cases, bank)


@pytest.mark.parametrize("budget", ["max_cost_usd", "max_calls", "max_total_output_tokens"])
def test_budget_preflight_precedes_any_request(budget, tmp_path):
    plan, cases, bank = fixtures()
    plan["judge"][budget] = 1 if budget != "max_cost_usd" else 0.00001
    args = write_fixture(tmp_path, plan=plan, cases=cases, bank=bank)
    with pytest.raises(ValueError):
        run.execute(*args, execute_api=True, transport=lambda *_: pytest.fail("Unexpected API"))
    assert not args[-1].exists()


def test_uncapped_cost_has_finite_call_output_bounds_and_rate_validation():
    plan, cases, bank = fixtures()
    assert run.validate_judge_plan(plan)["max_cost_usd"] is None
    for bad in ("NaN", "Infinity", -1):
        changed = copy.deepcopy(plan)
        changed["judge"]["input_usd_per_million_tokens"] = bad
        with pytest.raises(ValueError):
            run.validate_judge_plan(changed)
    pairs, case_map = run.prepare_pairs(cases, bank)
    plan["judge"]["max_input_tokens"] = 1
    with pytest.raises(ValueError, match="input token bound"):
        run.prepare_requests(pairs, case_map, plan["judge"])


def test_nonofficial_endpoint_is_rejected():
    plan, _, _ = fixtures()
    plan["judge"]["endpoint"] = "https://example.invalid/collect"
    with pytest.raises(ValueError, match="official"):
        run.validate_judge_plan(plan)


@pytest.mark.parametrize(
    "mutation", ["extra", "score_bool", "score_float", "quote", "missing_quote"]
)
def test_judgment_validation_preserves_literal_evidence(mutation):
    result = judgment()
    if mutation == "extra":
        result["secret_score"] = 4
    elif mutation == "score_bool":
        result["scores"]["A"]["correctness"] = True
    elif mutation == "score_float":
        result["scores"]["B"]["usefulness"] = 3.5
    elif mutation == "quote":
        result["quoted_evidence"]["A"] = ["存在しない引用"]
    else:
        result["quoted_evidence"]["B"] = []
    with pytest.raises(ValueError):
        run.validate_judgment(result, "同じ回答です。", "同じ回答です。")
    valid = judgment("", "ある回答")
    valid["scores"]["A"]["correctness"] = None
    assert run.validate_judgment(valid, "", "ある回答") == valid


@pytest.mark.parametrize("mutation,expected", [
    ("refusal", "refused"), ("incomplete", "incomplete_response"),
    ("parse", "invalid_judgment"), ("snapshot", "unexpected_model_snapshot"),
])
def test_api_missingness_is_not_a_tie(mutation, expected):
    plan, cases, bank = fixtures()
    pairs, case_map = run.prepare_pairs(cases, bank)
    body = run.prepare_requests(pairs, case_map, plan["judge"])[0]["body"]
    raw = response(body)
    if mutation == "refusal":
        raw["output"][0]["content"] = [{"type": "refusal", "refusal": "Cannot evaluate"}]
    elif mutation == "incomplete":
        raw["status"] = "incomplete"
    elif mutation == "parse":
        raw["output"][0]["content"][0]["text"] = "not json"
    else:
        raw["model"] = "other-snapshot"
    observation = run.response_observation(raw, body)
    assert observation["status"] == expected
    assert observation["judgment"] is None


def test_dry_run_no_credential_or_network_and_snapshot_resume(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    args = write_fixture(tmp_path)
    report = run.execute(*args, transport=lambda *_: pytest.fail("Unexpected API"))
    assert report["status"] == "PREPARED_NOT_DISPATCHED"
    assert report["pair_count"] == 96 and report["request_count"] == 8
    assert not (args[-1] / "requests").exists()
    assert run.execute(*args, resume=True) == report
    with pytest.raises(FileExistsError):
        run.execute(*args)
    run.write_json(args[0], {"judge": {**fixtures()[0]["judge"], "reasoning_effort": "high"}})
    with pytest.raises(ValueError, match="snapshot changed"):
        run.execute(*args, resume=True)


def test_execute_uses_environment_only_keeps_receipts_never_repeats(tmp_path, monkeypatch):
    secret = "TEST_SECRET_SHOULD_NEVER_APPEAR_IN_ARTIFACTS"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    calls = []

    def transport(body, key):
        assert key == secret
        calls.append(body)
        return response(body)

    args = write_fixture(tmp_path)
    report = run.execute(*args, execute_api=True, transport=transport)
    assert len(calls) == 8
    assert report["identical_calibration"]["order_consistent_ties"] == 4
    assert report["non_regression"] == "NOT_ESTABLISHED"
    assert report["usage"]["reported_total_tokens"] == 4000
    assert report["usage"]["actual_billed_cost_usd"] is None
    again = run.execute(*args, execute_api=True, resume=True, transport=transport)
    assert len(calls) == 8 and again == report
    for path in args[-1].rglob("*.json"):
        assert secret not in path.read_text()


def test_ambiguous_failure_reserved_never_retried_and_messages_redacted(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "DO_NOT_LOG_SECRET")
    args = write_fixture(tmp_path)

    def broken(*_):
        raise TimeoutError("DO_NOT_LOG_SECRET https://unsafe.example")

    result = run.execute(*args, execute_api=True, transport=broken)
    assert result["stopped_on_failure"] and result["undispatched_requests"] == 7
    reserved = list((args[-1] / "requests").glob("*.json"))
    assert len(reserved) == 1
    first = reserved[0].read_text()
    calls = []

    def successful(body, _key):
        calls.append(body)
        return response(body)

    resumed = run.execute(*args, execute_api=True, resume=True, transport=successful)
    assert len(calls) == 7
    assert reserved[0].read_text() == first
    assert resumed["identical_calibration"]["missing_or_invalid"] == 1
    assert resumed["usage"]["calls_without_reported_usage"] == 1
    for path in args[-1].rglob("*.json"):
        assert "DO_NOT_LOG_SECRET" not in path.read_text()
        assert "unsafe.example" not in path.read_text()


def test_http_failure_records_code_not_body_or_headers(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    args = write_fixture(tmp_path)

    def broken(*_):
        raise urllib.error.HTTPError("sensitive_url", 429, "sensitive_message", {}, None)

    run.execute(*args, execute_api=True, transport=broken)
    receipt = run.load_json(next((args[-1] / "requests").glob("*.json")))
    assert receipt["http_status"] == 429
    assert "sensitive" not in json.dumps(receipt)


def test_pending_reservation_recovers_durable_response_without_dispatch(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    args = write_fixture(tmp_path)
    run.execute(*args)
    prepared = run.load_json(args[-1] / "PREPARED_REQUESTS.json")["requests"]
    for row in prepared:
        run.write_json(args[-1] / "requests" / (row["request_id"] + ".json"), {
            **row, "status": "reserved_pending", "reserved_at": "earlier",
        })
        run.write_json(args[-1] / "responses" / (row["request_id"] + ".json"),
                       response(row["body"]))
    result = run.execute(*args, execute_api=True, resume=True,
                         transport=lambda *_: pytest.fail("Unexpected retry"))
    assert result["identical_calibration"]["order_consistent_ties"] == 4


def test_pending_without_response_is_unknown_never_dispatched(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    args = write_fixture(tmp_path)
    run.execute(*args)
    prepared = run.load_json(args[-1] / "PREPARED_REQUESTS.json")["requests"]
    for row in prepared:
        run.write_json(args[-1] / "requests" / (row["request_id"] + ".json"), {
            **row, "status": "reserved_pending", "reserved_at": "earlier",
        })
    result = run.execute(*args, execute_api=True, resume=True,
                         transport=lambda *_: pytest.fail("Unexpected retry"))
    assert result["identical_calibration"]["missing_or_invalid"] == 4


def test_order_conflict_and_correct_winner_mapping_are_kept_separate():
    plan, cases, bank = fixtures()
    pairs, _ = run.prepare_pairs(cases, bank)
    pair = {**pairs[0], "exact_identical": False, "selected_for_identical_calibration": False}
    receipts = [{
        "request_id": pair["pair_id"] + "-" + order, "order": order,
        "observation": {"status": "completed", "judgment": judgment(winner=winner)},
    } for order, winner in (("AB", "B"), ("BA", "A"))]
    result = run.summarize([pair], receipts)
    assert result["pairs"][0]["order_consistent_preference"] == "workspace"
    receipts[1]["observation"]["judgment"]["winner"] = "B"
    result = run.summarize([pair], receipts)
    assert result["pairs"][0]["judge_status"] == "order_conflict"
    assert result["pairs"][0]["order_consistent_preference"] is None


def test_no_redirect_can_forward_authorization():
    redirect = run.NoRedirect().redirect_request(None, None, 307, "", {}, "https://other.invalid")
    assert redirect is None


def test_usage_bound_violation_stops_further_dispatch(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    args = write_fixture(tmp_path)

    def oversized(body, _key):
        raw = response(body)
        raw["usage"] = {"input_tokens": 200, "output_tokens": 4001, "total_tokens": 4201}
        return raw

    result = run.execute(*args, execute_api=True, transport=oversized)
    assert result["stopped_on_failure"] and result["request_receipt_count"] == 1
    assert result["usage"]["usage_bound_exceeded_calls"] == 1
