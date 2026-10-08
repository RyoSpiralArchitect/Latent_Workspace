import json
import shutil
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_v14_judge_panel as run  # noqa: E402


@pytest.fixture
def frozen_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "REPO", tmp_path)
    monkeypatch.setattr(run.os, "environ", {})  # Tests never inspect real provider credentials.
    for name in ("run_v14_judge_panel.py", "judge_v14_answer_bank.py"):
        target = tmp_path / "scripts" / name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(ROOT / "scripts" / name, target)
    cases = [{"id": f"case-{i:02d}", "lane": "general" if i < 8 else "relation",
              "user_prompt": "Synthetic question", "reference": {"original": "reference"},
              "rubric": ["Use the supplied facts."]} for i in range(16)]
    pairs = []
    for i in range(14):
        case = cases[i // 2]
        comparison = run.prior.COMPARISONS[i % 2]
        pair_id = run.prior.sha256([case["id"], "greedy", comparison])[:20]
        pairs.append({"pair_id": pair_id, "case_id": case["id"], "lane": case["lane"],
                      "regime": "greedy", "comparison": comparison,
                      "base_answer": "Base answer", "workspace_answer":
                      "Work answer" if i < 10 else "Base answer",
                      "base_finish_reason": "eos", "workspace_finish_reason": "length",
                      "exact_identical": i >= 10, "calibration_only": i >= 10})
    selection = tmp_path / "selection.json"
    run.prior.write_json(selection, {"format": "latent-workspace-v14-judge-panel-selection-v1",
                                     "cases": cases, "pairs": pairs})
    plan = {
        "format": "latent-workspace-v14-judge-panel-plan-v1", "replicates": list(range(5)),
        "max_calls_per_cell": 28, "dataset": {"path": "selection.json",
                                                "sha256": run.prior.file_sha(selection)},
        "source_identity": {"scripts/" + name: run.prior.file_sha(tmp_path / "scripts" / name)
                            for name in ("run_v14_judge_panel.py", "judge_v14_answer_bank.py")},
        "providers": {},
    }
    for provider, fixed in run.PROVIDERS.items():
        plan["providers"][provider] = {
            **fixed, "max_output_tokens": 4000, "max_input_tokens": 32768,
            "input_usd_per_million_tokens": 2.5 if provider == "openai" else 1.36,
            "output_usd_per_million_tokens": 15 if provider == "openai" else 4.18,
            "max_cost_usd": None, "accepted_response_models": [fixed["model"]],
        }
    plan["providers"]["openai"]["reasoning_effort"] = "low"
    plan["providers"]["mistral"].update(temperature=0.2, random_seed_base=1001)
    path = tmp_path / "plan.json"
    run.prior.write_json(path, plan)
    return path, plan, tmp_path


def prepared(fixture, provider="openai", replicate=0):
    _, plan, _ = fixture
    config, _, pairs, cases = run.validate_plan(plan, provider, replicate)
    return run.prepare_requests(plan, provider, replicate, config, pairs, cases), config


def response(provider, body, *, wrapped=False, winner="tie"):
    content = (body["input"][0]["content"][0]["text"] if provider == "openai"
               else body["messages"][1]["content"])
    data = json.loads(content)
    quotes = {side: [data["answer_" + side]] for side in ("A", "B")}
    if wrapped:
        quotes["A"] = ['"' + data["answer_A"] + '"']
    verdict = {
        "scores": {side: {dim: 3 for dim in run.prior.DIMENSIONS} for side in ("A", "B")},
        "dimension_analysis_ja": {dim: "確認した差分です。" for dim in run.prior.DIMENSIONS},
        "winner": winner, "quoted_evidence": quotes, "changes_ja": [], "risks_ja": [],
        "rationale_ja": "観察であり確定ではない。", "uncertainty_ja": "人間確認が必要。",
    }
    common = {"id": "mock-response", "model": body["model"]}
    if provider == "openai":
        return {**common, "status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps(verdict)},
        ]}], "usage": {"input_tokens": 100, "output_tokens": 200, "total_tokens": 300}}
    return {**common, "choices": [{"index": 0, "finish_reason": "stop", "message": {
        "role": "assistant", "content": json.dumps(verdict),
    }}], "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300}}


@pytest.mark.parametrize("provider", ["openai", "mistral"])
def test_complete_blinded_grid_and_exact_provider_contract(frozen_plan, provider):
    requests, _ = prepared(frozen_plan, provider, 3)
    assert len(requests) == 28 and len({row["request_id"] for row in requests}) == 28
    assert sum(row["calibration_only"] for row in requests) == 8
    for request in requests:
        body = request["body"]
        assert "legacy_semantic" not in json.dumps(body)
        assert "centered_semantic" not in json.dumps(body)
        content = (body["input"][0]["content"][0]["text"] if provider == "openai"
                   else body["messages"][1]["content"])
        assert "comparison" not in json.loads(content)
        assert "no automatic repair" in json.dumps(body)
        if provider == "openai":
            assert body["store"] is False and body["service_tier"] == "default"
            assert body["text"]["format"]["strict"] is True
            assert "temperature" not in body and "random_seed" not in body
        else:
            assert body["stream"] is False and body["service_tier"] == "standard_only"
            assert body["random_seed"] == 1004 and body["temperature"] == 0.2
            assert body["response_format"]["json_schema"]["strict"] is True
            assert "reasoning_effort" not in body


def test_provider_seed_and_order_are_recorded_without_leaking_labels(frozen_plan):
    a, _ = prepared(frozen_plan, "mistral", 0)
    b, _ = prepared(frozen_plan, "mistral", 1)
    assert a[0]["body"]["random_seed"] + 1 == b[0]["body"]["random_seed"]
    first = json.loads(a[0]["body"]["messages"][1]["content"])
    second = json.loads(a[1]["body"]["messages"][1]["content"])
    assert first["answer_A"] == second["answer_B"]
    assert first["answer_B"] == second["answer_A"]
    assert first["reference_selection"] == second["reference_selection"] == "original"


@pytest.mark.parametrize("field,value", [
    ("model", "mistral-large-latest"), ("endpoint", "https://example.invalid"),
    ("env_key", "OPENAI_API_KEY"), ("accepted_response_models", ["mistral-large-latest"]),
    ("temperature", 0.9), ("random_seed_base", 999), ("max_output_tokens", 8000),
])
def test_changed_provider_contract_fails_closed(frozen_plan, field, value):
    _, plan, _ = frozen_plan
    plan["providers"]["mistral"][field] = value
    with pytest.raises(ValueError):
        run.validate_plan(plan, "mistral", 0)


def test_incomplete_selected_grid_and_source_drift_rejected(frozen_plan):
    _, plan, root = frozen_plan
    selection = run.prior.load_json(root / "selection.json")
    selection["pairs"].pop()
    run.prior.write_json(root / "selection.json", selection)
    plan["dataset"]["sha256"] = run.prior.file_sha(root / "selection.json")
    with pytest.raises(ValueError, match="14 unique"):
        run.validate_plan(plan, "openai", 0)
    plan["source_identity"]["scripts/run_v14_judge_panel.py"] = "bad"
    with pytest.raises(ValueError, match="source identity"):
        run.validate_plan(plan, "openai", 0)


@pytest.mark.parametrize("provider", ["openai", "mistral"])
def test_dry_run_does_not_access_key_or_api(frozen_plan, provider):
    path, _, root = frozen_plan
    result = run.execute(path, provider, 0, root / "output",
                         transport=lambda *_: pytest.fail("Unexpected API"))
    assert result["status"] == "PREPARED_NOT_DISPATCHED" and result["request_count"] == 28
    assert not (root / "output" / "requests").exists()


@pytest.mark.parametrize("provider", ["openai", "mistral"])
def test_execute_complete_and_resume_without_redispatch(frozen_plan, provider):
    path, _, root = frozen_plan
    secret = "SYNTHETIC_SECRET_MUST_NOT_APPEAR"
    run.os.environ[run.PROVIDERS[provider]["env_key"]] = secret
    calls = []

    def transport(selected, body, key):
        assert selected == provider and key == secret
        calls.append(body)
        return response(provider, body)

    output = root / "output"
    result = run.execute(path, provider, 0, output, execute_api=True, transport=transport)
    assert result["durable_responses"] == 28
    assert result["observation_status_counts"] == {"completed": 28}
    assert result["usage"]["reported_total_tokens"] == 8400
    assert result["usage"]["actual_billed_cost_usd"] is None
    again = run.execute(path, provider, 0, output, execute_api=True, resume=True,
                        transport=transport)
    assert len(calls) == 28 and result == again
    for artifact in output.rglob("*.json"):
        assert secret not in artifact.read_text()


def test_provider_cannot_use_other_provider_key(frozen_plan):
    path, _, root = frozen_plan
    run.os.environ["OPENAI_API_KEY"] = "fake-openai"
    with pytest.raises(ValueError, match="environment key"):
        run.execute(path, "mistral", 0, root / "output", execute_api=True,
                    transport=lambda *_: pytest.fail("Wrong provider credential used"))


@pytest.mark.parametrize("provider", ["openai", "mistral"])
def test_invalid_quotes_are_retained_and_do_not_trigger_quality_early_stop(frozen_plan, provider):
    path, _, root = frozen_plan
    run.os.environ[run.PROVIDERS[provider]["env_key"]] = "fake"
    report = run.execute(path, provider, 0, root / "output", execute_api=True,
                         transport=lambda p, body, _k: response(p, body, wrapped=True))
    assert report["observation_status_counts"] == {"invalid_judgment": 28}
    assert report["durable_responses"] == 28
    assert not report["stopped_on_contract_or_transport_failure"]


def test_ambiguous_dispatch_stops_cell_and_remains_stopped_on_resume(frozen_plan):
    path, _, root = frozen_plan
    run.os.environ["OPENAI_API_KEY"] = "fake"

    def broken(*_):
        raise TimeoutError("DO_NOT_RECORD_SECRET_OR_URL")

    output = root / "output"
    first = run.execute(path, "openai", 0, output, execute_api=True, transport=broken)
    assert first["reserved_requests"] == 1 and first["undispatched_requests"] == 27
    again = run.execute(path, "openai", 0, output, execute_api=True, resume=True,
                        transport=lambda *_: pytest.fail("Prior ambiguous cell resumed dispatch"))
    assert first == again and again["stopped_on_contract_or_transport_failure"]
    for artifact in output.rglob("*.json"):
        assert "DO_NOT_RECORD_SECRET_OR_URL" not in artifact.read_text()


def test_http_error_status_only_and_no_retry(frozen_plan):
    path, _, root = frozen_plan
    run.os.environ["MISTRAL_API_KEY"] = "fake"

    def rejected(*_):
        raise urllib.error.HTTPError("private-url", 401, "private-key", {}, None)

    report = run.execute(path, "mistral", 0, root / "output", execute_api=True, transport=rejected)
    assert report["receipt_status_counts"] == {"http_error_no_automatic_retry": 1}
    raw = next((root / "output" / "requests").glob("*.json")).read_text()
    assert '"http_status": 401' in raw and "private-" not in raw


@pytest.mark.parametrize("provider", ["openai", "mistral"])
def test_changed_returned_model_stops_before_remaining_requests(frozen_plan, provider):
    path, _, root = frozen_plan
    run.os.environ[run.PROVIDERS[provider]["env_key"]] = "fake"

    def wrong_model(p, body, _key):
        raw = response(p, body)
        raw["model"] = "unapproved-latest-alias"
        return raw

    report = run.execute(path, provider, 0, root / "output", execute_api=True,
                         transport=wrong_model)
    assert report["observation_status_counts"] == {"unexpected_model_identity": 1}
    assert report["stopped_on_contract_or_transport_failure"]
    assert report["undispatched_requests"] == 27


def test_mistral_length_and_malformed_usage_preserve_unknown(frozen_plan):
    requests, config = prepared(frozen_plan, "mistral")
    request = requests[0]
    raw = response("mistral", request["body"])
    raw["choices"][0]["finish_reason"] = "length"
    raw["usage"]["total_tokens"] = 999
    assert run.response_observation(raw, request, config)["status"] == "incomplete_response"
    assert run.usage_receipt(raw, request, config)["status"] == "UNKNOWN"


def test_native_response_hash_is_verified_on_resume(frozen_plan):
    path, _, root = frozen_plan
    run.os.environ["OPENAI_API_KEY"] = "fake"
    output = root / "output"
    run.execute(path, "openai", 0, output, execute_api=True,
                transport=lambda p, body, _k: response(p, body))
    artifact = next((output / "responses").glob("*.json"))
    raw = run.prior.load_json(artifact)
    raw["id"] = "changed"
    run.prior.write_json(artifact, raw)
    with pytest.raises(ValueError, match="Durable response identity"):
        run.execute(path, "openai", 0, output, execute_api=True, resume=True,
                    transport=lambda *_: pytest.fail("Redispatch"))


def test_order_disagreement_is_not_collapsed_into_a_winner(frozen_plan):
    requests, config = prepared(frozen_plan)
    _, plan, _ = frozen_plan
    _, _, pairs, _ = run.validate_plan(plan, "openai", 0)
    receipts = []
    for request in requests:
        raw = response("openai", request["body"], winner="A")
        receipts.append({**request, "status": "response_recorded",
                         "observation": run.response_observation(raw, request, config),
                         "usage_receipt": run.usage_receipt(raw, request, config)})
    summary = run.summarize(pairs, receipts, {"provider": "openai", "replicate": 0,
                                            "request_count": 28})
    assert all(row["judge_status"] == "order_conflict" for row in summary["pairs"])
    assert all(row["order_consistent_preference"] is None for row in summary["pairs"])


def test_full_grid_cost_ceiling_fails_before_dispatch(frozen_plan):
    path, plan, root = frozen_plan
    plan["providers"]["openai"]["max_cost_usd"] = 0.000001
    run.prior.write_json(path, plan)
    with pytest.raises(ValueError, match="Complete cell"):
        run.execute(path, "openai", 0, root / "output", execute_api=True,
                    transport=lambda *_: pytest.fail("Selective budget dispatch"))
    assert not (root / "output").exists()


def test_changed_snapshot_cannot_resume_as_another_replicate(frozen_plan):
    path, _, root = frozen_plan
    run.execute(path, "openai", 0, root / "output")
    with pytest.raises(ValueError, match="snapshot"):
        run.execute(path, "openai", 1, root / "output", resume=True)


def test_pending_durable_response_recovered_without_redispatch(frozen_plan):
    path, _, root = frozen_plan
    output = root / "output"
    run.execute(path, "mistral", 0, output)
    run.os.environ["MISTRAL_API_KEY"] = "fake"
    requests, _ = prepared(frozen_plan, "mistral")
    for item in requests:
        run.prior.write_json(output / "requests" / (item["request_id"] + ".json"), {
            **item, "status": "reserved_pending", "reserved_at": "mock-earlier",
        })
        run.prior.write_json(output / "responses" / (item["request_id"] + ".json"),
                             response("mistral", item["body"]))
    result = run.execute(path, "mistral", 0, output, execute_api=True, resume=True,
                         transport=lambda *_: pytest.fail("Recovered response redispatched"))
    assert result["observation_status_counts"] == {"completed": 28}


@pytest.mark.parametrize("status", sorted(run.RECEIPT_FAILURES))
def test_all_existing_failure_statuses_block_remaining_cell_dispatch(frozen_plan, status):
    path, _, root = frozen_plan
    output = root / "output"
    run.execute(path, "openai", 0, output)
    run.os.environ["OPENAI_API_KEY"] = "fake"
    requests, _ = prepared(frozen_plan)
    first = requests[0]
    run.prior.write_json(output / "requests" / (first["request_id"] + ".json"), {
        **first, "status": status, "reserved_at": "mock-earlier",
    })
    result = run.execute(path, "openai", 0, output, execute_api=True, resume=True,
                         transport=lambda *_: pytest.fail("Failed cell dispatched remaining calls"))
    assert result["reserved_requests"] == 1 and result["undispatched_requests"] == 27
    assert result["stopped_on_contract_or_transport_failure"]
