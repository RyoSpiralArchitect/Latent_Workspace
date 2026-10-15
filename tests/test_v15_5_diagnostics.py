from __future__ import annotations

import copy
import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_v15_5_diagnostic_judge as run
import summarize_v15_5_diagnostic_judge as summary
import v15_5_diagnostics as d


@pytest.fixture(scope="module")
def data():
    return d.make_dataset()


@pytest.fixture(scope="module")
def plan():
    return run.load_plan()


def diagnosis(item):
    result = {
        "commitment": "yes",
        "contradiction": "absent",
        "reasoning": "none",
        "added_facts": "none",
        "evidence": {k: [] for k in d.ENUMS},
        "assessment_en": "The explicit answer is classified without rescuing format.",
    }
    result.update(item.get("expected", {}))
    result["evidence"]["commitment"] = [item["payload"]["response_text"]]
    if result["commitment"] == "conflicting":
        result["evidence"]["commitment"] = ["Bram is above Alder", "Bram is not above Alder"]
        result["evidence"]["contradiction"] = result["evidence"]["commitment"]
    if result["added_facts"] in ("entailed", "unsupported"):
        result["evidence"]["added_facts"] = [item["payload"]["response_text"]]
    return result


def raw_response(provider, config, value):
    text = json.dumps(value)
    if provider == "openai":
        return {
            "model": config["model"],
            "id": "test_response",
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
            "usage": {"input_tokens": 100, "output_tokens": 120, "total_tokens": 220},
        }
    return {
        "model": config["model"],
        "id": "test_response",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 120, "total_tokens": 220},
    }


def test_complete_frozen_bank_and_oracle(data):
    assert len(data["records"]) == len({r["item_id"] for r in data["records"]}) == 512
    assert len({r["family_id"] for r in data["records"]}) == 16
    assert len(data["repeat_item_ids"]) == 32
    assert data["counts"]["primary_inline"] == 256
    assert d.machine_summary(data)["old_expression_gate"] == "FAIL"
    for row in data["records"]:
        assert len(row["oracle"]["proof_path"]) == (2 if row["view"] == "atomic" else 4)
        assert bool(row["payload"]["visible_facts"]) == (
            row["coordinate"]["information"] == "inline"
        )
        assert set(row["payload"]) == {
            "visible_facts",
            "question",
            "task_instruction",
            "response_text",
            "finish_reason",
        }


def test_repeats_are_balanced_not_change_selected(data):
    rows = [r for r in data["records"] if r["item_id"] in data["repeat_item_ids"]]
    groups = {
        (
            r["coordinate"]["renderer"],
            r["coordinate"]["cue"],
            r["coordinate"]["information"],
            r["view"],
            r["oracle"]["label"],
        )
        for r in rows
    }
    assert len(groups) == 32


def test_dataset_is_json_round_trip_stable(data):
    assert json.loads(json.dumps(data, ensure_ascii=False)) == data


@pytest.mark.parametrize("provider", run.PROVIDERS)
@pytest.mark.parametrize("phase,count", [("calibration", 16), ("study", 544)])
def test_requests_and_blinding(data, plan, provider, phase, count):
    values = d.requests_for(data, plan, provider, phase)
    assert len(values) == len({r["request_id"] for r in values}) == count
    for request in values:
        assert request["body_sha256"] == d.io.sha256(request["body"])
        text = json.dumps(request["body"])
        for forbidden in ("target_label", "strict_correct", "control_id", "family000", "item_id"):
            assert forbidden not in text
        assert "OPENAI_API_KEY" not in text and "MISTRAL_API_KEY" not in text


@pytest.mark.parametrize("control", d.calibration(), ids=lambda c: c["control_id"])
def test_valid_literal_evidence(control):
    result = d.validate_diagnosis(diagnosis(control), control["payload"])
    for evidence in result["verified_evidence"].values():
        for item in evidence:
            assert all(
                control["payload"]["response_text"][a:b] == item["quote"]
                for a, b in item["codepoint_spans"]
            )


@pytest.mark.parametrize(
    "mutation",
    (
        "fabricate",
        "empty",
        "long",
        "unknown",
        "extra",
        "missing",
        "no_evidence",
        "too_many",
        "long_assessment",
    ),
)
def test_reject_bad_diagnoses(mutation):
    control = d.calibration()[0]
    value = diagnosis(control)
    if mutation == "fabricate":
        value["evidence"]["commitment"] = ["Yes"]
    if mutation == "empty":
        value["evidence"]["commitment"] = [""]
    if mutation == "long":
        value["evidence"]["commitment"] = ["x" * 241]
    if mutation == "unknown":
        value["commitment"] = "probably_yes"
    if mutation == "extra":
        value["winner"] = "A"
    if mutation == "missing":
        del value["reasoning"]
    if mutation == "no_evidence":
        value["evidence"]["commitment"] = []
    if mutation == "too_many":
        value["evidence"]["commitment"] = ["yes"] * 5
    if mutation == "long_assessment":
        value["assessment_en"] = "word " * 121
    with pytest.raises(ValueError):
        d.validate_diagnosis(value, control["payload"])


def test_conflict_requires_two_distinct_spans():
    control = d.calibration()[4]
    value = diagnosis(control)
    value["evidence"]["contradiction"] = ["Bram", "Bram"]
    with pytest.raises(ValueError):
        d.validate_diagnosis(value, control["payload"])


@pytest.mark.parametrize("bad", ['{"a":1,"a":2}', '{"a":NaN}', "```json\n{}\n```"])
def test_json_no_repair(bad):
    with pytest.raises(ValueError):
        run.strict_json(bad)


@pytest.mark.parametrize("provider", run.PROVIDERS)
def test_model_finish_and_evidence_fail_closed(plan, provider):
    control = d.calibration()[0]
    request = {"provider": provider}
    config = plan["providers"][provider]
    raw = raw_response(provider, config, diagnosis(control))
    assert run.observe(raw, request, control["payload"], config)["status"] == "valid_diagnosis"
    raw["model"] = "different_model"
    assert (
        run.observe(raw, request, control["payload"], config)["status"]
        == "unexpected_model_identity"
    )
    raw = raw_response(provider, config, diagnosis(control))
    if provider == "openai":
        raw["status"] = "incomplete"
    else:
        raw["choices"][0]["finish_reason"] = "length"
    assert run.observe(raw, request, control["payload"], config)["status"] == "incomplete_response"
    assert run.usage({}, {"provider": provider}, config)["status"] == "UNKNOWN"


def test_calibration_rule_and_critical_failures(data, plan):
    rows = []
    for control in data["calibration"]:
        for rep in (0, 1):
            rows.append(
                {
                    "item_id": control["item_id"],
                    "replicate": rep,
                    "status": "valid_diagnosis",
                    "observation": {"judgment": diagnosis(control)},
                }
            )
    assert run.calibration_gate(rows, data, plan)["status"] == "PASS"
    bad = copy.deepcopy(rows)
    bad[0]["status"] = "invalid_judgment"
    assert run.calibration_gate(bad, data, plan)["status"] == "FAIL"
    critical = {c["item_id"] for c in data["calibration"] if c["control_id"] == "conflict"}
    bad = copy.deepcopy(rows)
    next(r for r in bad if r["item_id"] in critical)["observation"]["judgment"]["commitment"] = "no"
    assert run.calibration_gate(bad, data, plan)["status"] == "FAIL"


@pytest.mark.parametrize("provider", run.PROVIDERS)
def test_exclusive_reservation_and_replay(tmp_path, data, plan, provider):
    request = d.requests_for(data, plan, provider, "calibration")[0]
    control = next(c for c in data["calibration"] if c["item_id"] == request["item_id"])
    config = plan["providers"][provider]
    calls = []

    def fake(endpoint, api_key, body, timeout):
        calls.append(1)
        assert endpoint == config["endpoint"] and api_key == "not-a-real-key"
        return raw_response(provider, config, diagnosis(control))

    cell = tmp_path / provider / "calibration"
    result = run.run_one(request, control["payload"], config, cell, "not-a-real-key", fake)
    assert result["observation"]["status"] == "valid_diagnosis"
    with pytest.raises(FileExistsError):
        run.run_one(request, control["payload"], config, cell, "not-a-real-key", fake)
    assert len(calls) == 1
    replay = run.replay_cell(tmp_path, provider, "calibration", plan, data)
    assert sum(r["status"] == "valid_diagnosis" for r in replay) == 1
    assert sum(r["status"] == "not_dispatched" for r in replay) == 15
    outcome_path = cell / "calls" / request["request_id"] / "OUTCOME.json"
    outcome = d.io.load_json(outcome_path)
    outcome["observation"]["judgment"]["commitment"] = "forged"
    d.io.write_json(outcome_path, outcome)
    with pytest.raises(ValueError):
        run.replay_cell(tmp_path, provider, "calibration", plan, data)


def test_http_failure_is_reserved_not_retried(tmp_path, data, plan):
    request = d.requests_for(data, plan, "openai", "calibration")[0]
    control = next(c for c in data["calibration"] if c["item_id"] == request["item_id"])

    def fail(*args, **kwargs):
        raise urllib.error.HTTPError("https://api.openai.com", 429, "not logged", {}, None)

    result = run.run_one(
        request,
        control["payload"],
        plan["providers"]["openai"],
        tmp_path / "openai/calibration",
        "not-a-real-key",
        fail,
    )
    assert result["status"] == "http_error_no_retry" and result["http_status"] == 429
    assert "not logged" not in json.dumps(result)


def test_bucket_does_not_rescue_or_confuse_truncation(data):
    row = next(
        r
        for r in data["records"]
        if r["coordinate"]
        == {
            "case_id": "v15-cue-seed15002-family0011_atomic_d1",
            "renderer": "native_chat",
            "cue": "absent",
            "information": "inline",
        }
    )
    original = copy.deepcopy(row)
    judgment = {
        "commitment": "no",
        "contradiction": "absent",
        "reasoning": "supported",
        "added_facts": "entailed",
    }
    assert summary.bucket(row, {"judgment": judgment}) == "format_only_candidate_not_rescued"
    assert row == original and row["mechanical"]["strict_correct"] is False
    modified = copy.deepcopy(row)
    modified["mechanical"]["finish_reason"] = "length"
    assert summary.bucket(modified, {"judgment": judgment}) == "incomplete_observed_text"
    judgment["contradiction"] = "present"
    assert summary.bucket(row, {"judgment": judgment}) == "internal_contradiction"


def test_plan_endpoint_cannot_be_redirected(monkeypatch, plan):
    malicious = copy.deepcopy(plan)
    malicious["providers"]["openai"]["endpoint"] = "https://attacker.invalid"
    monkeypatch.setattr(d.io, "load_json", lambda _: malicious)
    with pytest.raises(ValueError):
        run.load_plan()


def test_protocol_has_no_online_rewriter_or_preference_vote(data, plan):
    assert plan["claims"]["new_learner_generations"] == 0
    assert plan["claims"]["training_performed"] is False
    assert "winner" not in d.SCHEMA["properties"]
    assert set(data["calibration"][4]["expected"]) <= set(d.ENUMS)


@pytest.mark.parametrize("provider", run.PROVIDERS)
@pytest.mark.parametrize("shape", [[], None, "non-object", {"output": None}])
def test_malformed_envelopes_stay_visible(provider, shape, plan):
    result = run.observe(
        shape, {"provider": provider}, d.calibration()[0]["payload"], plan["providers"][provider]
    )
    assert result["status"] in ("invalid_judgment", "unexpected_model_identity")
    assert result["judgment"] is None


def test_pending_reservation_is_unknown(tmp_path, data, plan):
    request = d.requests_for(data, plan, "openai", "calibration")[0]
    itemdir = tmp_path / "openai/calibration/calls" / request["request_id"]
    d.io.write_json(itemdir / "REQUEST.json", request, exclusive=True)
    d.io.write_json(
        itemdir / "RESERVATION.json",
        {
            "request_id": request["request_id"],
            "body_sha256": request["body_sha256"],
            "status": "reserved_pending",
        },
        exclusive=True,
    )
    rows = run.replay_cell(tmp_path, "openai", "calibration", plan, data)
    assert sum(r["status"] == "reserved_pending_unknown" for r in rows) == 1
    assert run.calibration_gate(rows, data, plan)["status"] == "FAIL"


def test_invalid_and_disagreeing_judgments_not_majority_gold(data):
    row = copy.deepcopy(data["records"][0])
    row["agreement"] = "unavailable"
    row["diagnoses"] = {
        p: {
            "status": "invalid_judgment",
            "bucket": "unavailable_judgment",
            "observation": None,
            "truth_relative_commitment_match": None,
        }
        for p in run.PROVIDERS
    }
    result = summary.summarize_rows([row])
    assert result["total"] == 1
    assert result["agreement"] == {"unavailable": 1}
    for provider in run.PROVIDERS:
        assert result["judges"][provider]["truth_relative_unresolved"] == 1
        assert result["judges"][provider]["truth_relative_mismatches"] == 0
