"""Offline Gemini 3.8 contract tests; never read real credentials or dispatch APIs."""

import copy
import json
import shutil
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_v14_gemini38_panel as run  # noqa: E402


@pytest.fixture
def frozen_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "REPO", tmp_path)
    monkeypatch.setattr(run.panel, "REPO", tmp_path)
    monkeypatch.setattr(run.os, "environ", {})
    names = ["run_v14_gemini38_panel.py", "run_v14_judge_panel.py", "judge_v14_answer_bank.py"]
    for name in names:
        target = tmp_path / "scripts" / name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(ROOT / "scripts" / name, target)
    cases = [
        {
            "id": f"case-{i:02d}",
            "lane": "general" if i < 8 else "relation",
            "user_prompt": "Synthetic question",
            "reference": {"original": "reference"},
            "rubric": ["Use the supplied facts."],
        }
        for i in range(16)
    ]
    pairs = []
    for i in range(14):
        case = cases[i]
        comparison = run.prior.COMPARISONS[i % 2]
        pairs.append(
            {
                "pair_id": run.prior.sha256([case["id"], "greedy", comparison])[:20],
                "case_id": case["id"],
                "lane": case["lane"],
                "regime": "greedy",
                "comparison": comparison,
                "base_answer": "Base answer",
                "workspace_answer": "Work answer" if i < 10 else "Base answer",
                "base_finish_reason": "eos",
                "workspace_finish_reason": "length",
                "exact_identical": i >= 10,
                "calibration_only": i >= 10,
            }
        )
    selection = tmp_path / "selection.json"
    run.prior.write_json(selection, {"cases": cases, "pairs": pairs})
    source = {"scripts/" + name: run.prior.file_sha(tmp_path / "scripts" / name) for name in names}
    parent = {
        "format": "latent-workspace-v14-judge-panel-plan-v1",
        "replicates": list(range(5)),
        "max_calls_per_cell": 28,
        "dataset": {"path": "selection.json", "sha256": run.prior.file_sha(selection)},
        "source_identity": {key: value for key, value in source.items() if "gemini" not in key},
        "providers": {},
    }
    for provider, fixed in run.panel.PROVIDERS.items():
        parent["providers"][provider] = {
            **fixed,
            "max_output_tokens": 4000,
            "max_input_tokens": 32768,
            "input_usd_per_million_tokens": 2,
            "output_usd_per_million_tokens": 12,
            "max_cost_usd": None,
            "accepted_response_models": [fixed["model"]],
        }
    parent["providers"]["openai"]["reasoning_effort"] = "low"
    parent["providers"]["mistral"].update(temperature=0.2, random_seed_base=1001)
    parent_path = tmp_path / "parent.json"
    run.prior.write_json(parent_path, parent)
    plan = {
        "format": "latent-workspace-v14-gemini38-panel-plan-v1",
        "replicates": list(range(5)),
        "max_calls_per_cell": 28,
        "dataset": parent["dataset"],
        "source_identity": source,
        "parent_panel_plan": {"path": "parent.json", "sha256": run.prior.file_sha(parent_path)},
        "providers": {
            "gemini": {
                **run.PROVIDERS["gemini"],
                "max_output_tokens": 4000,
                "max_input_tokens": 32768,
                "execution_gate": "READY",
                "thinking_level": "LOW",
                "random_seed_base": 1001,
                "input_usd_per_million_tokens": 0.75,
                "output_usd_per_million_tokens": 3.75,
                "max_cost_usd": None,
                "accepted_response_models": [run.MODEL],
            }
        },
    }
    path = tmp_path / "plan.json"
    run.prior.write_json(path, plan)
    return path, plan, tmp_path


def prepared(fixture, replicate=0):
    _, plan, _ = fixture
    config, _, pairs, cases = run.validate_plan(plan, "gemini", replicate)
    return run.prepare_requests(plan, "gemini", replicate, config, pairs, cases), config


def response(body, *, wrapped=False, winner="tie"):
    data = json.loads(body["contents"][0]["parts"][0]["text"])
    quotes = {side: [data["answer_" + side]] for side in ("A", "B")}
    if wrapped:
        quotes["A"] = ['"' + data["answer_A"] + '"']
    verdict = {
        "scores": {side: {dim: 3 for dim in run.prior.DIMENSIONS} for side in ("A", "B")},
        "dimension_analysis_ja": {dim: "確認した差分です。" for dim in run.prior.DIMENSIONS},
        "winner": winner,
        "quoted_evidence": quotes,
        "changes_ja": [],
        "risks_ja": [],
        "rationale_ja": "観察であり確定ではない。",
        "uncertainty_ja": "人間確認が必要。",
    }
    return {
        "responseId": "mock-response",
        "modelVersion": run.MODEL,
        "candidates": [
            {
                "index": 0,
                "finishReason": "STOP",
                "content": {
                    "role": "model",
                    "parts": [{"text": json.dumps(verdict)}],
                },
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 100,
            "candidatesTokenCount": 200,
            "thoughtsTokenCount": 50,
            "totalTokenCount": 350,
        },
    }


def test_blinded_grid_exact_schema_rubric_and_seed(frozen_plan):
    assert run.MODEL == "gemini-3.8-flash"
    assert run.ENDPOINT.endswith("/models/gemini-3.8-flash:generateContent")
    requests, _ = prepared(frozen_plan, 3)
    assert len(requests) == 28 and len({r["request_id"] for r in requests}) == 28
    assert sum(r["calibration_only"] for r in requests) == 8
    for request in requests:
        body = request["body"]
        assert body["systemInstruction"]["parts"][0]["text"] == run.panel.INSTRUCTIONS
        assert "legacy_semantic" not in json.dumps(body)
        assert "centered_semantic" not in json.dumps(body)
        assert "comparison" not in json.loads(body["contents"][0]["parts"][0]["text"])
        config = body["generationConfig"]
        assert config["responseJsonSchema"] == run.prior.JUDGMENT_SCHEMA
        assert config["responseMimeType"] == "application/json"
        assert config["seed"] == 1004
        assert not run.DEPRECATED_GENERATION_FIELDS.intersection(config)
        assert config["thinkingConfig"] == {"thinkingLevel": "LOW", "includeThoughts": False}
        assert config["maxOutputTokens"] == 4000
        assert "tools" not in body and "cachedContent" not in body
    a, b = [json.loads(r["body"]["contents"][0]["parts"][0]["text"]) for r in requests[:2]]
    assert a["answer_A"] == b["answer_B"] and a["answer_B"] == b["answer_A"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "gemini-latest"),
        ("model", "gemini-3.1-pro-preview"),
        ("model", "gemini-3.7-flash"),
        ("endpoint", "https://example.invalid"),
        ("env_key", "OPENAI_API_KEY"),
        ("accepted_response_models", ["gemini-*"]),
        ("accepted_response_models", ["gemini-3.1-pro-preview"]),
        ("accepted_response_models", ["gemini-3.7-flash"]),
        ("accepted_response_models", [run.MODEL, run.MODEL]),
        ("temperature", 0.2),
        ("thinking_level", "HIGH"),
        ("random_seed_base", 999),
        ("max_output_tokens", 8000),
        ("max_output_tokens", 4000.0),
        ("random_seed_base", 1001.0),
        ("temperature", True),
        ("input_usd_per_million_tokens", "NaN"),
    ],
)
def test_changed_provider_contract_rejected(frozen_plan, field, value):
    _, plan, _ = frozen_plan
    plan["providers"]["gemini"][field] = value
    with pytest.raises(ValueError):
        run.validate_plan(plan, "gemini", 0)


@pytest.mark.parametrize("drift", ["parent", "source", "dataset", "grid"])
def test_frozen_parent_and_source_closure(frozen_plan, drift):
    _, plan, _ = frozen_plan
    if drift == "parent":
        plan["parent_panel_plan"]["sha256"] = "wrong"
    elif drift == "source":
        plan["source_identity"]["scripts/run_v14_gemini38_panel.py"] = "wrong"
    elif drift == "dataset":
        plan["dataset"] = {"path": "another.json", "sha256": "wrong"}
    else:
        plan["replicates"] = [0]
    with pytest.raises(ValueError):
        run.validate_plan(plan, "gemini", 0)


def test_dry_run_no_key_or_api_and_exact_resume(frozen_plan):
    path, _, root = frozen_plan
    result = run.execute(
        path, "gemini", 0, root / "output", transport=lambda *_: pytest.fail("Unexpected API")
    )
    assert result["status"] == "PREPARED_NOT_DISPATCHED"
    assert not (root / "output" / "requests").exists()
    with pytest.raises(FileExistsError):
        run.execute(path, "gemini", 0, root / "output")
    with pytest.raises(ValueError, match="snapshot"):
        run.execute(path, "gemini", 1, root / "output", resume=True)


def test_blocked_gate_prevents_reservation_key_access_and_dispatch(frozen_plan, monkeypatch):
    path, plan, root = frozen_plan
    plan["providers"]["gemini"]["execution_gate"] = "BLOCKED_requested_model_mismatch"
    run.prior.write_json(path, plan)

    class NoCredentialAccess(dict):
        def get(self, *_args, **_kwargs):
            pytest.fail("Blocked execution accessed credentials")

    monkeypatch.setattr(run.os, "environ", NoCredentialAccess())
    with pytest.raises(ValueError, match="execution gate is not READY"):
        run.execute(
            path,
            "gemini",
            0,
            root / "blocked",
            execute_api=True,
            transport=lambda *_: pytest.fail("Blocked execution dispatched"),
        )
    assert not (root / "blocked").exists()
    report = run.execute(
        path,
        "gemini",
        0,
        root / "dry",
        execute_api=False,
        transport=lambda *_: pytest.fail("Dry run dispatched"),
    )
    assert report["status"] == "PREPARED_NOT_DISPATCHED"
    assert report["provider_config"]["execution_gate"] == "BLOCKED_requested_model_mismatch"
    assert not (root / "dry" / "requests").exists()


@pytest.mark.parametrize("gate", ["UNKNOWN", "ready", "", None, False, ["READY"]])
@pytest.mark.parametrize("execute_api", [False, True])
def test_unknown_execution_gate_fails_closed_without_output(frozen_plan, gate, execute_api):
    path, plan, root = frozen_plan
    plan["providers"]["gemini"]["execution_gate"] = gate
    run.prior.write_json(path, plan)
    with pytest.raises(ValueError, match="Unknown Gemini execution gate"):
        run.execute(
            path,
            "gemini",
            0,
            root / "output",
            execute_api=execute_api,
            transport=lambda *_: pytest.fail("Unknown gate dispatched"),
        )
    assert not (root / "output").exists()


def test_execute_complete_and_resume_never_redispatch_or_record_key(frozen_plan):
    path, _, root = frozen_plan
    secret = "SYNTHETIC_SECRET_MUST_NOT_APPEAR"
    run.os.environ["GEMINI_API_KEY"] = secret
    calls = []

    def transport(provider, body, key):
        assert provider == "gemini" and key == secret
        calls.append(body)
        return response(body)

    output = root / "output"
    report = run.execute(path, "gemini", 0, output, execute_api=True, transport=transport)
    assert report["durable_responses"] == 28
    assert report["observation_status_counts"] == {"completed": 28}
    assert report["usage"]["reported_output_tokens"] == 7000
    assert report["usage"]["reported_total_tokens"] == 9800
    assert report["usage"]["actual_billed_cost_usd"] is None
    again = run.execute(
        path, "gemini", 0, output, execute_api=True, resume=True, transport=transport
    )
    assert again == report and len(calls) == 28
    for artifact in output.rglob("*.json"):
        assert secret not in artifact.read_text()


def test_no_cross_provider_credential_fallback(frozen_plan):
    path, _, root = frozen_plan
    run.os.environ.update(OPENAI_API_KEY="fake-openai", MISTRAL_API_KEY="fake-mistral")
    with pytest.raises(ValueError, match="Gemini environment key"):
        run.execute(
            path,
            "gemini",
            0,
            root / "output",
            execute_api=True,
            transport=lambda *_: pytest.fail("Wrong key dispatched"),
        )


def test_response_strict_quotes_thought_filter_and_no_fence_repair(frozen_plan):
    requests, config = prepared(frozen_plan)
    request = requests[0]
    raw = response(request["body"])
    raw["candidates"][0]["content"]["parts"].insert(0, {"thought": True, "text": "not judgment"})
    assert run.response_observation(raw, request, config)["status"] == "completed"
    bad = response(request["body"], wrapped=True)
    assert run.response_observation(bad, request, config)["status"] == "invalid_judgment"
    bad = response(request["body"])
    part = bad["candidates"][0]["content"]["parts"][0]
    part["text"] = "```json\n" + part["text"] + "\n```"
    assert run.response_observation(bad, request, config)["status"] == "invalid_judgment"


@pytest.mark.parametrize(
    "failure,expected",
    [
        ("model", "unexpected_model_identity"),
        ("length", "incomplete_response"),
        ("safety", "refused"),
        ("prompt_block", "refused"),
        ("multiple", "invalid_judgment"),
        ("nontext", "invalid_judgment"),
        ("empty", "invalid_judgment"),
        ("malformed", "invalid_judgment"),
    ],
)
def test_response_failures_keep_missingness(frozen_plan, failure, expected):
    requests, config = prepared(frozen_plan)
    request = requests[0]
    raw = response(request["body"])
    candidate = raw["candidates"][0]
    if failure == "model":
        raw["modelVersion"] = "gemini-unapproved"
    elif failure == "length":
        candidate["finishReason"] = "MAX_TOKENS"
    elif failure == "safety":
        candidate["finishReason"] = "SAFETY"
    elif failure == "prompt_block":
        raw["promptFeedback"] = {"blockReason": "SAFETY"}
        raw["candidates"] = []
    elif failure == "multiple":
        raw["candidates"].append(copy.deepcopy(candidate))
    elif failure == "nontext":
        candidate["content"]["parts"].append({"functionCall": {"name": "unexpected"}})
    elif failure == "empty":
        candidate["content"]["parts"] = []
    else:
        candidate["content"]["parts"][0] = False
    observation = run.response_observation(raw, request, config)
    assert observation["status"] == expected and observation["judgment"] is None


def test_usage_counts_thinking_and_preserves_absent_breakdown(frozen_plan):
    requests, config = prepared(frozen_plan)
    request = requests[0]
    raw = response(request["body"])
    usage = run.usage_receipt(raw, request, config)
    assert usage["output_tokens"] == 250 and usage["reported_thought_tokens"] == 50
    del raw["usageMetadata"]["thoughtsTokenCount"]
    usage = run.usage_receipt(raw, request, config)
    assert usage["output_tokens"] == 250 and usage["reported_thought_tokens"] is None
    assert usage["actual_billed_cost_usd"] is None
    raw["usageMetadata"]["thoughtsTokenCount"] = 49
    assert run.usage_receipt(raw, request, config)["status"] == "UNKNOWN"
    raw["usageMetadata"]["promptTokenCount"] = True
    assert run.usage_receipt(raw, request, config)["status"] == "UNKNOWN"


@pytest.mark.parametrize("kind", ["timeout", "http", "model", "bound"])
def test_failure_stops_remaining_calls_and_does_not_retry(frozen_plan, kind):
    path, _, root = frozen_plan
    run.os.environ["GEMINI_API_KEY"] = "fake"
    calls = []

    def transport(_provider, body, _key):
        calls.append(1)
        if kind == "timeout":
            raise TimeoutError("private-url-and-secret")
        if kind == "http":
            raise urllib.error.HTTPError("private-url", 401, "private-secret", {}, None)
        raw = response(body)
        if kind == "model":
            raw["modelVersion"] = "gemini-unapproved"
        else:
            raw["usageMetadata"].update(
                candidatesTokenCount=4001, thoughtsTokenCount=50, totalTokenCount=4151
            )
        return raw

    output = root / "output"
    report = run.execute(path, "gemini", 0, output, execute_api=True, transport=transport)
    assert report["stopped_on_contract_or_transport_failure"] and len(calls) == 1
    assert report["undispatched_requests"] == 27
    run.execute(path, "gemini", 0, output, execute_api=True, resume=True, transport=transport)
    assert len(calls) == 1
    for artifact in output.rglob("*.json"):
        assert "private-" not in artifact.read_text()


def test_order_conflict_and_quality_invalid_never_short_circuit(frozen_plan):
    path, _, root = frozen_plan
    run.os.environ["GEMINI_API_KEY"] = "fake"
    report = run.execute(
        path,
        "gemini",
        0,
        root / "conflict",
        execute_api=True,
        transport=lambda _p, body, _k: response(body, winner="A"),
    )
    assert all(pair["judge_status"] == "order_conflict" for pair in report["pairs"])
    assert all(pair["order_consistent_preference"] is None for pair in report["pairs"])
    report = run.execute(
        path,
        "gemini",
        0,
        root / "invalid",
        execute_api=True,
        transport=lambda _p, body, _k: response(body, wrapped=True),
    )
    assert report["observation_status_counts"] == {"invalid_judgment": 28}
    assert not report["stopped_on_contract_or_transport_failure"]


def test_pending_durable_response_recovery_and_hash_verification(frozen_plan):
    path, _, root = frozen_plan
    output = root / "output"
    run.execute(path, "gemini", 0, output)
    run.os.environ["GEMINI_API_KEY"] = "fake"
    requests, _ = prepared(frozen_plan)
    for item in requests:
        filename = item["request_id"] + ".json"
        run.prior.write_json(output / "requests" / filename, {**item, "status": "reserved_pending"})
        run.prior.write_json(output / "responses" / filename, response(item["body"]))
    report = run.execute(
        path,
        "gemini",
        0,
        output,
        execute_api=True,
        resume=True,
        transport=lambda *_: pytest.fail("Recovered response resent"),
    )
    assert report["durable_responses"] == 28
    artifact = next((output / "responses").glob("*.json"))
    raw = run.prior.load_json(artifact)
    raw["responseId"] = "changed"
    run.prior.write_json(artifact, raw)
    with pytest.raises(ValueError, match="Durable response identity"):
        run.execute(
            path,
            "gemini",
            0,
            output,
            execute_api=True,
            resume=True,
            transport=lambda *_: pytest.fail("Mutated response resent"),
        )


def test_full_grid_cost_ceiling_prevents_selective_dispatch(frozen_plan):
    path, plan, root = frozen_plan
    plan["providers"]["gemini"]["max_cost_usd"] = 0.000001
    run.prior.write_json(path, plan)
    with pytest.raises(ValueError, match="Complete cell"):
        run.execute(
            path,
            "gemini",
            0,
            root / "output",
            execute_api=True,
            transport=lambda *_: pytest.fail("Selective dispatch"),
        )
    assert not (root / "output").exists()


def test_dispatch_uses_header_not_url_and_blocks_redirects(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b"{}"

    class Opener:
        def open(self, request, timeout):
            captured.update(
                url=request.full_url, headers=dict(request.header_items()), timeout=timeout
            )
            return Response()

    def opener(*handlers):
        assert any(isinstance(handler, run.prior.NoRedirect) for handler in handlers)
        return Opener()

    monkeypatch.setattr(run.urllib.request, "build_opener", opener)
    run.dispatch("gemini", {"synthetic": True}, "fake-key")
    assert captured["url"] == run.ENDPOINT and "fake-key" not in captured["url"]
    assert captured["headers"]["X-goog-api-key"] == "fake-key"
    assert "Authorization" not in captured["headers"]
    assert captured["timeout"] == 180


@pytest.mark.parametrize("execute_api", [False, True])
def test_missing_execution_gate_fails_closed_before_output_or_credentials(
    frozen_plan, monkeypatch, execute_api
):
    path, plan, root = frozen_plan
    del plan["providers"]["gemini"]["execution_gate"]
    run.prior.write_json(path, plan)

    class NoCredentialAccess(dict):
        def get(self, *_args, **_kwargs):
            pytest.fail("Missing execution gate accessed credentials")

    monkeypatch.setattr(run.os, "environ", NoCredentialAccess())
    with pytest.raises(ValueError, match="Unknown Gemini execution gate"):
        run.execute(
            path,
            "gemini",
            0,
            root / "output",
            execute_api=execute_api,
            transport=lambda *_: pytest.fail("Missing execution gate dispatched"),
        )
    assert not (root / "output").exists()


@pytest.mark.parametrize("field", sorted(run.DEPRECATED_GENERATION_FIELDS))
@pytest.mark.parametrize("value", [None, 1.0])
def test_deprecated_parameter_rejected_in_plan_and_direct_body(frozen_plan, field, value):
    _, plan, _ = frozen_plan
    config = plan["providers"]["gemini"]
    config[field] = value
    with pytest.raises(ValueError, match="Deprecated Gemini"):
        run.validate_plan(plan, "gemini", 0)
    with pytest.raises(ValueError, match="Deprecated Gemini"):
        run.request_body("gemini", 0, config, {"synthetic": True})


@pytest.mark.parametrize("replicate", [-1, 5, True, 0.0, "0"])
def test_direct_body_rejects_unfrozen_replicate(frozen_plan, replicate):
    _, plan, _ = frozen_plan
    with pytest.raises(ValueError, match="frozen five replicates"):
        run.request_body("gemini", replicate, plan["providers"]["gemini"], {})


@pytest.mark.parametrize("empty_output", [False, True])
def test_thinking_cap_preserves_incomplete_even_with_valid_json(frozen_plan, empty_output):
    requests, config = prepared(frozen_plan)
    request = requests[0]
    raw = response(request["body"])
    raw["candidates"][0]["finishReason"] = "MAX_TOKENS"
    if empty_output:
        raw["candidates"][0].pop("content")
    raw["usageMetadata"].update(
        candidatesTokenCount=0 if empty_output else 200,
        thoughtsTokenCount=4000 if empty_output else 3800,
        totalTokenCount=4100,
    )
    observation = run.response_observation(raw, request, config)
    usage = run.usage_receipt(raw, request, config)
    assert observation["status"] == "incomplete_response"
    assert observation["judgment"] is None
    assert usage["status"] == "REPORTED_BY_API"
    assert usage["output_tokens"] == 4000
    assert not usage["bound_exceeded"]
