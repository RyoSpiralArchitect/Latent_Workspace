import copy
import json
import shutil
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_v14_mistral_extension as run  # noqa: E402
from test_v14_judge_panel import frozen_plan as parent_plan  # noqa: E402, F401
from test_v14_judge_panel import response as parent_response  # noqa: E402


@pytest.fixture
def frozen_plan(parent_plan, monkeypatch):  # noqa: F811
    parent_path, parent, root = parent_plan
    monkeypatch.setattr(run, "REPO", root)
    name = "scripts/run_v14_mistral_extension.py"
    shutil.copyfile(ROOT / name, root / name)
    plan = {
        "format": "latent-workspace-v14-mistral-extension-plan-v1",
        "parent_panel_plan": {
            "path": parent_path.name, "sha256": run.prior.file_sha(parent_path),
        },
        "dataset": parent["dataset"], "replicates": parent["replicates"],
        "max_calls_per_cell": parent["max_calls_per_cell"],
        "source_identity": {
            **parent["source_identity"], name: run.prior.file_sha(root / name),
        },
        "providers": {
            "mistral": {**parent["providers"]["mistral"], "http_timeout_seconds": 600},
        },
    }
    path = root / "extension.json"
    run.prior.write_json(path, plan)
    return path, plan, root


def response(provider, body, *, wrapped=False, winner="tie", chunked=True):
    raw = parent_response(provider, body, wrapped=wrapped, winner=winner)
    if chunked:
        message = raw["choices"][0]["message"]
        message["content"] = [
            {"type": "thinking", "closed": True,
             "thinking": [{"type": "text", "text": "SYNTHETIC_THINKING_NOT_A_VERDICT"}]},
            {"type": "text", "text": message["content"]},
        ]
        message["tool_calls"] = None
    return raw


def prepared(fixture, replicate=0):
    _, plan, _ = fixture
    config, _, pairs, cases = run.validate_plan(plan, "mistral", replicate)
    return run.prepare_requests(plan, "mistral", replicate, config, pairs, cases), config


def test_grid_request_bodies_identical_to_frozen_parent(frozen_plan):
    _, plan, _ = frozen_plan
    parent = run.prior.load_json(run.resolve(plan["parent_panel_plan"]["path"]))
    parent_config, _, pairs, cases = run.panel.validate_plan(parent, "mistral", 3)
    old = run.panel.prepare_requests(parent, "mistral", 3, parent_config, pairs, cases)
    new, config = prepared(frozen_plan, 3)
    assert new == old and len(new) == 28
    assert config["http_timeout_seconds"] == 600
    assert all("reasoning_effort" not in request["body"] for request in new)
    assert all("http_timeout_seconds" not in request["body"] for request in new)


@pytest.mark.parametrize("field,value", [
    ("model", "mistral-large-latest"), ("temperature", 0.3),
    ("http_timeout_seconds", 180), ("reasoning_effort", "none"),
    ("accepted_response_models", ["mistral-large-4-0"]),
    ("input_usd_per_million_tokens", 0.68),
])
def test_changed_provider_config_rejected(frozen_plan, field, value):
    _, plan, _ = frozen_plan
    plan["providers"]["mistral"][field] = value
    with pytest.raises(ValueError, match="exactly inherit"):
        run.validate_plan(plan, "mistral", 0)


def test_parent_dataset_and_source_bindings_fail_closed(frozen_plan):
    _, plan, _ = frozen_plan
    bad = copy.deepcopy(plan)
    bad["parent_panel_plan"]["sha256"] = "bad"
    with pytest.raises(ValueError, match="parent plan identity"):
        run.validate_plan(bad, "mistral", 0)
    bad = copy.deepcopy(plan)
    bad["dataset"]["sha256"] = "bad"
    with pytest.raises(ValueError, match="exact original"):
        run.validate_plan(bad, "mistral", 0)
    bad = copy.deepcopy(plan)
    bad["source_identity"]["scripts/run_v14_mistral_extension.py"] = "bad"
    with pytest.raises(ValueError, match="source identity"):
        run.validate_plan(bad, "mistral", 0)


@pytest.mark.parametrize("chunked", [False, True])
def test_final_text_strictly_validates_without_modifying_raw(frozen_plan, chunked):
    requests, config = prepared(frozen_plan)
    raw = response("mistral", requests[0]["body"], chunked=chunked)
    original = copy.deepcopy(raw)
    observation = run.response_observation(raw, requests[0], config)
    assert observation["status"] == "completed" and observation["judgment"]["winner"] == "tie"
    assert "SYNTHETIC_THINKING" not in json.dumps(observation)
    assert raw == original
    assert run.usage_receipt(raw, requests[0], config)["output_tokens"] == 200


def test_split_final_text_and_thinking_not_fallback(frozen_plan):
    requests, config = prepared(frozen_plan)
    raw = response("mistral", requests[0]["body"])
    chunks = raw["choices"][0]["message"]["content"]
    final = chunks.pop()["text"]
    chunks.extend([{"type": "text", "text": final[:30]},
                   {"type": "text", "text": final[30:]}])
    assert run.response_observation(raw, requests[0], config)["status"] == "completed"
    chunks[0]["thinking"][0]["text"] = final
    del chunks[1:]
    observation = run.response_observation(raw, requests[0], config)
    assert observation["status"] == "invalid_judgment"
    assert observation["error"] == "missing_final_text"


@pytest.mark.parametrize("content", [
    None, [], 1, [{}], ["not a chunk"],
    [{"type": "tool_call", "text": "{}"}],
    [{"type": "text", "text": "{}", "unexpected": True}],
    [{"type": "text", "text": None}],
    [{"type": "thinking", "closed": False, "thinking": [{"type": "text", "text": "x"}]}],
    [{"type": "thinking", "closed": True, "thinking": []}],
    [{"type": "thinking", "closed": True, "thinking": [{"type": "image", "text": "x"}]}],
    [{"type": "text", "text": "{}"},
     {"type": "thinking", "closed": True, "thinking": [{"type": "text", "text": "x"}]}],
])
def test_malformed_chunk_envelopes_are_not_repaired(frozen_plan, content):
    requests, config = prepared(frozen_plan)
    raw = response("mistral", requests[0]["body"])
    raw["choices"][0]["message"]["content"] = content
    assert run.response_observation(raw, requests[0], config)["status"] == "invalid_judgment"


def test_model_refusal_incomplete_tool_call_and_schema_are_distinct(frozen_plan):
    requests, config = prepared(frozen_plan)
    request = requests[0]
    raw = response("mistral", request["body"])
    raw["model"] = "mistral-large-latest"
    assert run.response_observation(raw, request, config)["status"] == "unexpected_model_identity"
    raw = response("mistral", request["body"])
    raw["choices"][0]["message"]["refusal"] = "Cannot judge"
    assert run.response_observation(raw, request, config)["status"] == "refused"
    raw = response("mistral", request["body"])
    raw["choices"][0]["finish_reason"] = "length"
    assert run.response_observation(raw, request, config)["status"] == "incomplete_response"
    raw = response("mistral", request["body"])
    raw["choices"][0]["message"]["tool_calls"] = [{"function": "unexpected"}]
    assert run.response_observation(raw, request, config)["error"] == "unsupported_message"
    raw = response("mistral", request["body"], wrapped=True)
    assert run.response_observation(raw, request, config)["error"] == "schema_or_quote_check"


def test_dry_run_never_accesses_credentials_or_api(frozen_plan):
    path, _, root = frozen_plan
    report = run.execute(path, "mistral", 0, root / "output",
                         transport=lambda *_: pytest.fail("Unexpected API"))
    assert report["status"] == "PREPARED_NOT_DISPATCHED"
    assert not (root / "output" / "requests").exists()


def test_complete_and_resume_retain_raw_and_never_redispatch(frozen_plan):
    path, _, root = frozen_plan
    secret = "SYNTHETIC_SECRET_MUST_NOT_APPEAR"
    run.os.environ["MISTRAL_API_KEY"] = secret
    calls = []

    def transport(provider, body, key):
        assert provider == "mistral" and key == secret
        raw = response(provider, body)
        calls.append(raw)
        return raw

    output = root / "output"
    report = run.execute(path, "mistral", 0, output, execute_api=True, transport=transport)
    assert report["durable_responses"] == 28
    assert report["observation_status_counts"] == {"completed": 28}
    again = run.execute(path, "mistral", 0, output, execute_api=True, resume=True,
                        transport=lambda *_: pytest.fail("Unexpected redispatch"))
    assert again == report and len(calls) == 28
    prepared_data = run.prior.load_json(output / "PREPARED_REQUESTS.json")["requests"]
    for request, raw in zip(prepared_data, calls, strict=True):
        assert run.prior.load_json(output / "responses" / (request["request_id"] + ".json")) == raw
    for artifact in output.rglob("*.json"):
        assert secret not in artifact.read_text()


def test_invalid_quotes_do_not_quality_stop(frozen_plan):
    path, _, root = frozen_plan
    run.os.environ["MISTRAL_API_KEY"] = "fake"
    report = run.execute(path, "mistral", 0, root / "output", execute_api=True,
                         transport=lambda p, b, _: response(p, b, wrapped=True))
    assert report["observation_status_counts"] == {"invalid_judgment": 28}
    assert report["durable_responses"] == 28
    assert not report["stopped_on_contract_or_transport_failure"]


@pytest.mark.parametrize("failure", ["timeout", "http"])
def test_ambiguous_and_http_failure_never_retry(frozen_plan, failure):
    path, _, root = frozen_plan
    run.os.environ["MISTRAL_API_KEY"] = "fake"

    def transport(*_):
        if failure == "http":
            raise urllib.error.HTTPError("private-url", 429, "private-key", {}, None)
        raise TimeoutError("DO_NOT_RECORD_SECRET_OR_URL")

    output = root / "output"
    first = run.execute(path, "mistral", 0, output, execute_api=True, transport=transport)
    assert first["reserved_requests"] == 1 and first["undispatched_requests"] == 27
    again = run.execute(path, "mistral", 0, output, execute_api=True, resume=True,
                        transport=lambda *_: pytest.fail("Unexpected retry"))
    assert first == again and first["stopped_on_contract_or_transport_failure"]
    for artifact in output.rglob("*.json"):
        assert "DO_NOT_RECORD_SECRET_OR_URL" not in artifact.read_text()
        assert "private-" not in artifact.read_text()


def test_model_drift_and_usage_bounds_stop_before_next_request(frozen_plan):
    path, _, root = frozen_plan
    run.os.environ["MISTRAL_API_KEY"] = "fake"

    def model_drift(p, b, _):
        raw = response(p, b)
        raw["model"] = "mistral-large-4-0"
        return raw

    report = run.execute(path, "mistral", 0, root / "drift", execute_api=True,
                         transport=model_drift)
    assert report["observation_status_counts"] == {"unexpected_model_identity": 1}
    assert report["undispatched_requests"] == 27

    def excess_usage(p, b, _):
        raw = response(p, b)
        raw["usage"].update(completion_tokens=5000, total_tokens=5100)
        return raw

    report = run.execute(path, "mistral", 0, root / "usage", execute_api=True,
                         transport=excess_usage)
    assert report["stopped_on_contract_or_transport_failure"]
    assert report["undispatched_requests"] == 27


def test_malformed_usage_stays_unknown(frozen_plan):
    requests, config = prepared(frozen_plan)
    raw = response("mistral", requests[0]["body"])
    raw["usage"]["total_tokens"] = 1000
    assert run.usage_receipt(raw, requests[0], config)["status"] == "UNKNOWN"


def test_output_collision_prevents_dispatch(frozen_plan):
    path, _, root = frozen_plan
    output = root / "output"
    run.execute(path, "mistral", 0, output)
    with pytest.raises(FileExistsError):
        run.execute(path, "mistral", 0, output, execute_api=True,
                    transport=lambda *_: pytest.fail("Unexpected API"))
