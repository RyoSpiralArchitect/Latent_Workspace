#!/usr/bin/env python3
"""Additive high-budget Mistral / Sonnet 5 panel. Never edits an older run.

Unchanged blinded data, rubric, strict schema and literal-quote validator.
Credentials remain process-environment only. Every dispatch is reserved once;
transport ambiguity, model drift and accounting violations stop that cell.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

import run_v14_judge_panel as panel
import run_v14_mistral_extension as mistral
import summarize_v14_judge_extension as audit

prior = panel.prior
REPO = Path(__file__).resolve().parents[1]
INSTRUCTIONS = panel.INSTRUCTIONS
RECEIPT_FAILURES = panel.RECEIPT_FAILURES
CAPS = (16384, 32768, 65536)
PROVIDERS = {
    "mistral": panel.PROVIDERS["mistral"],
    "anthropic": {
        "model": "claude-sonnet-5",
        "endpoint": "https://api.anthropic.com/v1/messages",
        "env_key": "ANTHROPIC_API_KEY",
    },
}
SOURCE_FILES = (
    "scripts/run_v14_budget_panel.py",
    "scripts/probe_v14_budget_panel.py",
    "scripts/run_v14_judge_panel.py",
    "scripts/run_v14_mistral_extension.py",
    "scripts/judge_v14_answer_bank.py",
    "scripts/summarize_v14_judge_extension.py",
    "data/v14_budget_panel/canaries.json",
)


def config_for(provider, cap):
    if provider not in PROVIDERS or type(cap) is not int or cap not in CAPS:
        raise ValueError("Unknown provider or unplanned output cap")
    config = {
        **PROVIDERS[provider],
        "accepted_response_models": [PROVIDERS[provider]["model"]],
        "max_output_tokens": cap,
        "max_input_tokens": 32768,
        "max_cost_usd": None,
        "http_timeout_seconds": 1200,
    }
    if provider == "mistral":
        config.update(
            temperature=0.2,
            random_seed_base=1001,
            service_tier="standard_only",
            input_usd_per_million_tokens=1.36,
            output_usd_per_million_tokens=4.18,
        )
    else:
        config.update(
            thinking="adaptive",
            effort="medium",
            anthropic_version="2023-06-01",
            input_usd_per_million_tokens=2.0,
            output_usd_per_million_tokens=10.0,
        )
    return config


def resolve(path):
    candidate = REPO / path
    if candidate.is_symlink() or not candidate.resolve().is_relative_to(REPO.resolve()):
        raise ValueError("Bound file outside repository")
    return candidate


def validate_plan(plan, provider, replicate):
    if plan.get("format") != "latent-workspace-v14-budget-panel-plan-v1":
        raise ValueError("Unexpected plan format")
    if provider not in PROVIDERS or type(replicate) is not int or replicate not in range(5):
        raise ValueError("Invalid provider/replicate")
    if (
        plan["replicates"] != list(range(5))
        or plan["max_calls_per_cell"] != 28
        or set(plan["providers"]) != {provider}
        or plan["planned_requests"] != 140
    ):
        raise ValueError("Frozen grid changed")
    if not set(SOURCE_FILES) <= set(plan["source_identity"]):
        raise ValueError("Incomplete source binding")
    for name, sha in plan["source_identity"].items():
        if prior.file_sha(resolve(name)) != sha:
            raise ValueError("Frozen source identity changed")
    parent_path = resolve(plan["parent_panel_plan"]["path"])
    if prior.file_sha(parent_path) != plan["parent_panel_plan"]["sha256"]:
        raise ValueError("Parent plan changed")
    parent = prior.load_json(parent_path)
    if plan["dataset"] != parent["dataset"]:
        raise ValueError("Selected dataset changed")
    _, dataset, pairs, cases = panel.validate_plan(parent, "openai", replicate)
    config = plan["providers"][provider]
    if config != config_for(provider, config["max_output_tokens"]):
        raise ValueError("Provider settings changed")
    gate_path = resolve(plan["qualification"]["path"])
    if prior.file_sha(gate_path) != plan["qualification"]["sha256"]:
        raise ValueError("Qualification changed")
    import probe_v14_budget_panel as probe

    gate = probe.verify(gate_path.parent)
    if not gate["qualified"] or gate["provider"] != provider or gate["config"] != config:
        raise ValueError("No qualified pre-study capacity panel")
    return config, dataset, pairs, cases


def request_body(provider, replicate, config, data):
    if provider not in PROVIDERS or type(replicate) is not int or replicate not in range(5):
        raise ValueError("Invalid provider or replicate")
    if config != config_for(provider, config["max_output_tokens"]):
        raise ValueError("Nonfrozen request settings")
    if provider == "mistral":
        # Only max_tokens differs from the old 4,000-token request body.
        return panel.request_body(provider, replicate, config, data)
    return {
        "model": config["model"],
        "max_tokens": config["max_output_tokens"],
        "stream": False,
        "system": INSTRUCTIONS,
        "thinking": {"type": "adaptive"},
        "messages": [
            {"role": "user", "content": json.dumps(data, ensure_ascii=False, sort_keys=True)}
        ],
        "output_config": {
            "effort": config["effort"],
            "format": {"type": "json_schema", "schema": prior.JUDGMENT_SCHEMA},
        },
    }


def prepare_requests(plan, provider, replicate, config, pairs, cases):
    rows = []
    for pair in pairs:
        for order in ("AB", "BA"):
            data = panel.input_data(cases[pair["case_id"]], pair, order)
            body = request_body(provider, replicate, config, data)
            rows.append(
                {
                    "request_id": f"{provider}-r{replicate}-{pair['pair_id']}-{order}",
                    "provider": provider,
                    "replicate": replicate,
                    "pair_id": pair["pair_id"],
                    "order": order,
                    "calibration_only": pair["calibration_only"],
                    "body": body,
                    "body_sha256": prior.sha256(body),
                    "evaluator_input_sha256": prior.sha256(data),
                    **prior.cost_bound(body, config),
                }
            )
    if len(rows) != plan["max_calls_per_cell"]:
        raise ValueError("Request grid changed")
    return rows


def response_observation(raw, request, config):
    if request["provider"] == "mistral":
        return mistral.response_observation(raw, request, config)
    result = {
        "response_id": raw.get("id"),
        "response_model": raw.get("model"),
        "judgment": None,
        "actual_billed_cost_usd": None,
        "model_identity_ceiling": "requested_and_returned_id_only; immutable_weights_unknown",
    }
    if raw.get("model") not in config["accepted_response_models"]:
        return {**result, "status": "unexpected_model_identity"}
    reason = raw.get("stop_reason")
    result.update(api_finish_reason=reason, usage=raw.get("usage"))
    if reason == "refusal":
        return {**result, "status": "refused"}
    if reason != "end_turn":
        return {**result, "status": "incomplete_response"}
    blocks = raw.get("content")
    if (
        raw.get("type") != "message"
        or raw.get("role") != "assistant"
        or not isinstance(blocks, list)
        or not blocks
    ):
        return {**result, "status": "invalid_judgment", "error": "message_envelope"}
    text = []
    for block in blocks:
        if not isinstance(block, dict):
            return {**result, "status": "invalid_judgment", "error": "block_envelope"}
        if block.get("type") in {"thinking", "redacted_thinking"}:
            if text:
                return {**result, "status": "invalid_judgment", "error": "thinking_after_text"}
            continue
        if (
            block.get("type") != "text"
            or not isinstance(block.get("text"), str)
            or block.get("citations") not in (None, [])
        ):
            return {**result, "status": "invalid_judgment", "error": "nontext_or_cited_content"}
        text.append(block["text"])
    try:
        data = json.loads(request["body"]["messages"][0]["content"])
        judgment = prior.validate_judgment(
            json.loads("".join(text)), data["answer_A"], data["answer_B"]
        )
    except (ValueError, KeyError, TypeError):
        return {**result, "status": "invalid_judgment", "error": "schema_or_quote_check"}
    return {**result, "status": "completed", "judgment": judgment}


def usage_receipt(raw, request, config):
    if request["provider"] == "mistral":
        return panel.usage_receipt(raw, request, config)
    usage = raw.get("usage")
    if not isinstance(usage, dict):
        return {"status": "UNKNOWN", "actual_billed_cost_usd": None}
    # No prompt-cache request is made; still account explicitly if API reports it.
    fields = (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    )
    values = {name: usage.get(name, 0 if name.startswith("cache_") else None) for name in fields}
    if any(type(v) is not int or v < 0 for v in values.values()):
        return {"status": "UNKNOWN", "actual_billed_cost_usd": None}
    inputs = (
        values["input_tokens"]
        + values["cache_creation_input_tokens"]
        + values["cache_read_input_tokens"]
    )
    output = values["output_tokens"]
    report = prior.usage_receipt(
        {
            "usage": {
                "input_tokens": inputs,
                "output_tokens": output,
                "total_tokens": inputs + output,
            }
        },
        request,
        config,
    )
    report.update(
        reported_uncached_input_tokens=values["input_tokens"],
        reported_cache_creation_input_tokens=values["cache_creation_input_tokens"],
        reported_cache_read_input_tokens=values["cache_read_input_tokens"],
        reported_thinking_tokens=None,
        output_accounting="API_output_tokens_including_thinking; separate_thought_count_unknown",
    )
    # Unexpected cache writes could exceed the simple rate estimate; don't promote that bound.
    if values["cache_creation_input_tokens"]:
        report["bound_exceeded"] = True
        report["accounting_warning"] = "unexpected_cache_write_requires_separate_pricing"
    return report


def dispatch(provider, body, key):
    import certifi

    headers = {"Content-Type": "application/json"}
    if provider == "mistral":
        headers["Authorization"] = "Bearer " + key
    elif provider == "anthropic":
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    else:
        raise ValueError("Unknown provider")
    request = urllib.request.Request(
        PROVIDERS[provider]["endpoint"], data=prior.json_bytes(body), method="POST", headers=headers
    )
    opener = urllib.request.build_opener(
        prior.NoRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())),
    )
    with opener.open(request, timeout=1200) as response:
        return json.loads(response.read())


def summarize(pairs, receipts, snapshot):
    return panel.summarize(pairs, receipts, snapshot)


def stop_required(receipt):
    return (
        receipt["status"] in RECEIPT_FAILURES
        or receipt.get("observation", {}).get("status") == "unexpected_model_identity"
        or receipt.get("usage_receipt", {}).get("bound_exceeded", False)
    )


def record_one(request, config, output, key, *, transport=None):
    output = Path(output)
    receipt_path = output / "requests" / (request["request_id"] + ".json")
    response_path = output / "responses" / (request["request_id"] + ".json")
    if receipt_path.exists():
        receipt = prior.load_json(receipt_path)
        if any(receipt.get(k) != v for k, v in request.items()):
            raise ValueError("Reserved request changed")
        if receipt["status"] == "reserved_pending" and response_path.exists():
            raw = prior.load_json(response_path)
            receipt.update(
                status="response_recorded",
                recovered_from_response_receipt=True,
                response_sha256=prior.file_sha(response_path),
                observation=response_observation(raw, request, config),
                usage_receipt=usage_receipt(raw, request, config),
            )
            prior.write_json(receipt_path, receipt)
        if receipt["status"] == "response_recorded":
            raw = prior.load_json(response_path)
            if (
                receipt["response_sha256"] != prior.file_sha(response_path)
                or receipt["observation"] != response_observation(raw, request, config)
                or receipt["usage_receipt"] != usage_receipt(raw, request, config)
            ):
                raise ValueError("Durable observation changed")
        elif receipt["status"] not in RECEIPT_FAILURES:
            raise ValueError("Unknown receipt status")
        return receipt
    receipt = {**request, "status": "reserved_pending", "reserved_at": prior.now()}
    prior.write_json(receipt_path, receipt, exclusive=True)
    try:
        raw = (transport or dispatch)(request["provider"], request["body"], key)
        prior.write_json(response_path, raw, exclusive=True)
        receipt.update(
            status="response_recorded",
            completed_at=prior.now(),
            response_sha256=prior.file_sha(response_path),
            observation=response_observation(raw, request, config),
            usage_receipt=usage_receipt(raw, request, config),
        )
    except urllib.error.HTTPError as error:
        receipt.update(
            status="http_error_no_automatic_retry", http_status=error.code, failure_at=prior.now()
        )
    except Exception as error:
        receipt.update(
            status="transport_or_recording_ambiguous_no_automatic_retry",
            error_type=type(error).__name__,
            failure_at=prior.now(),
        )
    prior.write_json(receipt_path, receipt)
    return receipt


def execute(
    plan_path, provider, replicate, output, *, execute_api=False, resume=False, transport=None
):
    plan_path, output = Path(plan_path), Path(output)
    plan = prior.load_json(plan_path)
    config, dataset, pairs, cases = validate_plan(plan, provider, replicate)
    requests = prepare_requests(plan, provider, replicate, config, pairs, cases)
    snapshot = audit.cell_snapshot(
        sys.modules[__name__], plan_path, provider, replicate, config, dataset, pairs, requests
    )
    files = {
        "SNAPSHOT.json": snapshot,
        "PAIRS.json": {"pairs": pairs},
        "PREPARED_REQUESTS.json": {"requests": requests},
    }
    if output.exists():
        if output.is_symlink() or not resume:
            raise FileExistsError("Cell exists; explicit --resume required")
        if any(prior.load_json(output / name) != value for name, value in files.items()):
            raise ValueError("Cell preparation changed")
    else:
        output.mkdir(parents=True, exist_ok=False)
        for name, value in files.items():
            prior.write_json(output / name, value, exclusive=True)
    if not execute_api:
        return {**snapshot, "status": "PREPARED_NOT_DISPATCHED"}
    key = os.environ.get(PROVIDERS[provider]["env_key"])
    if not key:
        raise ValueError("Required key unavailable")
    receipts, stopped = [], False
    for request in requests:
        exists = (output / "requests" / (request["request_id"] + ".json")).exists()
        if stopped and not exists:
            continue
        receipt = record_one(request, config, output, key, transport=transport)
        receipts.append(receipt)
        stopped |= stop_required(receipt)
        print(
            f"panel {provider} r{replicate} {len(receipts)}/28 "
            f"{receipt.get('observation', {}).get('status', receipt['status'])}",
            flush=True,
        )
    report = summarize(pairs, receipts, snapshot)
    report["stopped_on_contract_or_transport_failure"] = stopped
    prior.write_json(output / "SUMMARY.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--provider", choices=sorted(PROVIDERS), required=True)
    parser.add_argument("--replicate", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    report = execute(
        args.plan,
        args.provider,
        args.replicate,
        args.output,
        execute_api=args.execute,
        resume=args.resume,
    )
    print(json.dumps({k: report[k] for k in ("status", "provider", "replicate")}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Budget panel halted safely: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
