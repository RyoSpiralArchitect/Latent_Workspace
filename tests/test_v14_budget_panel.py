import copy
import json
import shutil
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import probe_v14_budget_panel as probe  # noqa: E402
import run_v14_budget_panel as run  # noqa: E402
from test_judge_v14_answer_bank import judgment  # noqa: E402
from test_v14_judge_panel import frozen_plan as parent_plan  # noqa: E402, F401


def response(provider, body, *, winner="tie"):
    index = 1 if provider == "mistral" else 0
    data = json.loads(body["messages"][index]["content"])
    text = json.dumps(judgment(data["answer_A"], data["answer_B"], winner))
    common = {"id": "mock-only", "model": body["model"]}
    if provider == "mistral":
        return {
            **common,
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
        }
    return {
        **common,
        "type": "message",
        "role": "assistant",
        "stop_reason": "end_turn",
        "content": [
            {"type": "thinking", "thinking": "NOT_A_VERDICT", "signature": "mock"},
            {"type": "text", "text": text},
        ],
        "usage": {"input_tokens": 100, "output_tokens": 200},
    }


@pytest.fixture(params=["mistral", "anthropic"])
def frozen(parent_plan, monkeypatch, request):  # noqa: F811
    path, parent, root = parent_plan
    monkeypatch.setattr(run, "REPO", root)
    for name in run.SOURCE_FILES:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    provider = request.param
    run.os.environ[run.PROVIDERS[provider]["env_key"]] = "SYNTHETIC_NOT_A_REAL_KEY"
    gate_dir = root / "preflight"
    probe.execute(
        provider, 16384, gate_dir, execute_api=True, transport=lambda p, b, k: response(p, b)
    )
    gate = gate_dir / "QUALIFICATION.json"
    plan = {
        "format": "latent-workspace-v14-budget-panel-plan-v1",
        "parent_panel_plan": {"path": path.name, "sha256": run.prior.file_sha(path)},
        "dataset": parent["dataset"],
        "replicates": list(range(5)),
        "max_calls_per_cell": 28,
        "planned_requests": 140,
        "source_identity": {p: run.prior.file_sha(root / p) for p in run.SOURCE_FILES},
        "qualification": {"path": str(gate.relative_to(root)), "sha256": run.prior.file_sha(gate)},
        "providers": {provider: run.config_for(provider, 16384)},
    }
    plan_path = root / "budget.json"
    run.prior.write_json(plan_path, plan)
    return plan_path, plan, provider, root


def prepared(frozen, replicate=0):
    _, plan, provider, _ = frozen
    config, _, pairs, cases = run.validate_plan(plan, provider, replicate)
    return run.prepare_requests(plan, provider, replicate, config, pairs, cases), config


def test_only_mistral_token_cap_changes(frozen):
    _, plan, provider, _ = frozen
    requests, config = prepared(frozen, 2)
    assert len(requests) == 28
    assert len({r["request_id"] for r in requests}) == 28
    assert sum(r["calibration_only"] for r in requests) == 8
    if provider == "mistral":
        parent = run.prior.load_json(run.resolve(plan["parent_panel_plan"]["path"]))
        old_config, _, pairs, cases = run.panel.validate_plan(parent, provider, 2)
        old = run.panel.prepare_requests(parent, provider, 2, old_config, pairs, cases)
        for current, before in zip(requests, old, strict=True):
            assert current["body"] == {**before["body"], "max_tokens": 16384}
            assert "reasoning_effort" not in current["body"]
    else:
        body = requests[0]["body"]
        assert body["thinking"] == {"type": "adaptive"}
        assert body["output_config"]["effort"] == "medium"
        assert body["output_config"]["format"]["schema"] == run.prior.JUDGMENT_SCHEMA
        assert not {"temperature", "top_p", "top_k", "seed", "tools"}.intersection(body)
        assert requests[0]["body"] == prepared(frozen, 4)[0][0]["body"]
    assert all(r["output_token_upper_bound"] == config["max_output_tokens"] for r in requests)


def test_dry_run_no_api_no_key_lookup(frozen, monkeypatch):
    path, _, provider, root = frozen
    monkeypatch.setattr(run.os, "environ", {})
    result = run.execute(path, provider, 0, root / "dry", transport=lambda *_: pytest.fail("API"))
    assert result["status"] == "PREPARED_NOT_DISPATCHED"


def test_complete_resume_raw_reconstruction_and_secret_exclusion(frozen):
    path, _, provider, root = frozen
    calls = []

    def transport(p, b, key):
        calls.append(1)
        return response(p, b)

    result = run.execute(path, provider, 0, root / "cell", execute_api=True, transport=transport)
    assert result["observation_status_counts"] == {"completed": 28}
    assert len(calls) == 28
    resumed = run.execute(
        path,
        provider,
        0,
        root / "cell",
        execute_api=True,
        resume=True,
        transport=lambda *_: pytest.fail("redispatch"),
    )
    assert resumed == result
    assert all(
        "SYNTHETIC_NOT_A_REAL_KEY" not in p.read_text() for p in (root / "cell").rglob("*.json")
    )
    verified = run.audit.verify_cell(run, path, provider, 0, root / "cell")
    assert verified["status"] == "VERIFIED_RECEIPT_CLOSURE"


@pytest.mark.parametrize("failure", ["http", "timeout"])
def test_transport_failure_not_retried(frozen, failure):
    path, _, provider, root = frozen
    calls = []

    def transport(*_):
        calls.append(1)
        if failure == "http":
            raise urllib.error.HTTPError("https://example.invalid", 500, "synthetic", {}, None)
        raise TimeoutError("synthetic")

    result = run.execute(path, provider, 0, root / "cell", execute_api=True, transport=transport)
    assert len(calls) == 1 and result["reserved_requests"] == 1
    assert result["undispatched_requests"] == 27
    assert (
        run.execute(
            path,
            provider,
            0,
            root / "cell",
            execute_api=True,
            resume=True,
            transport=lambda *_: pytest.fail("retry"),
        )
        == result
    )


@pytest.mark.parametrize(
    "field,value",
    [("temperature", 0.7), ("max_output_tokens", 4000), ("model", "an-alias"), ("effort", "high")],
)
def test_setting_change_rejected(frozen, field, value):
    _, plan, provider, _ = frozen
    bad = copy.deepcopy(plan)
    bad["providers"][provider][field] = value
    with pytest.raises(ValueError):
        run.validate_plan(bad, provider, 0)


def test_binding_change_rejected(frozen):
    _, plan, provider, _ = frozen
    for name in ("parent_panel_plan", "dataset", "qualification"):
        bad = copy.deepcopy(plan)
        bad[name]["sha256"] = "tampered"
        with pytest.raises(ValueError):
            run.validate_plan(bad, provider, 0)


def test_strict_quote_incomplete_and_model_checks(frozen):
    requests, config = prepared(frozen)
    req = requests[0]
    provider = req["provider"]
    raw = response(provider, req["body"])
    assert run.response_observation(raw, req, config)["status"] == "completed"
    raw["model"] = "wrong-id"
    assert run.response_observation(raw, req, config)["status"] == "unexpected_model_identity"
    raw = response(provider, req["body"])
    if provider == "mistral":
        raw["choices"][0]["finish_reason"] = "length"
    else:
        raw["stop_reason"] = "max_tokens"
    assert run.response_observation(raw, req, config)["status"] == "incomplete_response"
    raw = response(provider, req["body"])
    block = (
        raw["choices"][0]["message"]["content"][0] if provider == "mistral" else raw["content"][-1]
    )
    verdict = json.loads(block["text"])
    verdict["quoted_evidence"]["A"] = ["not a literal quote"]
    block["text"] = json.dumps(verdict)
    assert run.response_observation(raw, req, config)["status"] == "invalid_judgment"


def test_capacity_headroom_required_and_no_outcome_selection(frozen):
    _, _, provider, root = frozen

    def lengthy(p, body, key):
        raw = response(p, body)
        if p == "mistral":
            raw["usage"].update(completion_tokens=15000, total_tokens=15100)
        else:
            raw["usage"]["output_tokens"] = 15000
        return raw

    result = probe.execute(provider, 16384, root / "long", execute_api=True, transport=lengthy)
    assert result["reserved_calls"] == 6 and not result["qualified"]
    assert probe.verify(root / "long") == result


def test_pending_durable_raw_recovers_without_dispatch(frozen):
    requests, config = prepared(frozen)
    req = requests[0]
    _, _, provider, root = frozen
    output = root / "recovery"
    run.prior.write_json(
        output / "requests" / (req["request_id"] + ".json"),
        {**req, "status": "reserved_pending", "reserved_at": "synthetic"},
    )
    run.prior.write_json(
        output / "responses" / (req["request_id"] + ".json"), response(provider, req["body"])
    )
    receipt = run.record_one(
        req, config, output, "not-used", transport=lambda *_: pytest.fail("redispatch")
    )
    assert receipt["recovered_from_response_receipt"]


def test_anthropic_unknown_usage_and_cache_write_fail_closed():
    config = run.config_for("anthropic", 16384)
    req = {
        "provider": "anthropic",
        "input_token_upper_bound": 4000,
        "output_token_upper_bound": 16384,
    }
    assert run.usage_receipt({}, req, config)["status"] == "UNKNOWN"
    raw = {"usage": {"input_tokens": 100, "output_tokens": 200, "cache_creation_input_tokens": 20}}
    result = run.usage_receipt(raw, req, config)
    assert result["input_tokens"] == 120 and result["bound_exceeded"]
