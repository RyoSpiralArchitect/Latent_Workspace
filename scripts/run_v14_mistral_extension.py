#!/usr/bin/env python3
"""Additive Mistral content-chunk adapter for the sealed V14 judge panel.

Request bodies, selected answers, strict schema and literal-quote validation are
unchanged. Only the documented response envelope is decoded. Raw responses are
retained verbatim as JSON objects; thinking content is never judged or repaired.
No credential or API is accessed without --execute; ambiguous calls never retry.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from decimal import Decimal
from pathlib import Path

import run_v14_judge_panel as panel

prior = panel.prior
REPO = Path(__file__).resolve().parents[1]
PROVIDERS = {"mistral": panel.PROVIDERS["mistral"]}
INSTRUCTIONS = panel.INSTRUCTIONS
RECEIPT_FAILURES = panel.RECEIPT_FAILURES
HTTP_TIMEOUT_SECONDS = 600
input_data = panel.input_data
prepare_requests = panel.prepare_requests
request_body = panel.request_body
usage_receipt = panel.usage_receipt
summarize = panel.summarize


def resolve(path):
    candidate = REPO / path
    if candidate.is_symlink() or not candidate.resolve().is_relative_to(REPO.resolve()):
        raise ValueError("Bound file must be a regular repository file")
    return candidate


def validate_plan(plan, provider, replicate):
    if plan.get("format") != "latent-workspace-v14-mistral-extension-plan-v1":
        raise ValueError("Unexpected Mistral extension plan format")
    if provider != "mistral" or type(replicate) is not int:
        raise ValueError("Invalid provider or replicate")
    if plan["replicates"] != list(range(5)) or replicate not in plan["replicates"]:
        raise ValueError("Expected frozen five-replicate grid")
    if plan["max_calls_per_cell"] != 28 or set(plan["providers"]) != {"mistral"}:
        raise ValueError("Expected Mistral and 28 calls per cell")
    required = {
        "scripts/run_v14_mistral_extension.py",
        "scripts/run_v14_judge_panel.py",
        "scripts/judge_v14_answer_bank.py",
    }
    if not required <= set(plan["source_identity"]):
        raise ValueError("Required runner/validator source identity missing")
    for name, sha in plan["source_identity"].items():
        if prior.file_sha(resolve(name)) != sha:
            raise ValueError("Frozen Mistral extension source identity changed")
    parent_path = resolve(plan["parent_panel_plan"]["path"])
    if prior.file_sha(parent_path) != plan["parent_panel_plan"]["sha256"]:
        raise ValueError("Frozen parent plan identity changed")
    parent = prior.load_json(parent_path)
    if plan["dataset"] != parent["dataset"]:
        raise ValueError("Mistral must use the exact original selected dataset")
    parent_config, dataset_path, pairs, cases = panel.validate_plan(parent, provider, replicate)
    config = plan["providers"][provider]
    if config != {**parent_config, "http_timeout_seconds": HTTP_TIMEOUT_SECONDS}:
        raise ValueError("Mistral provider contract must exactly inherit parent plus timeout")
    return config, dataset_path, pairs, cases


def final_text(content):
    """Unwrap documented final text only; reject unknown or malformed chunks.

Plain strings preserve compatibility. In chunk mode, closed thinking chunks may
precede final text chunks. Multiple final text chunks concatenate without added
characters. We never extract candidate JSON from thinking, fences or prose.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list) or not content:
        raise ValueError("nonstring_or_empty_content")
    text = []
    for chunk in content:
        if not isinstance(chunk, dict):
            raise ValueError("invalid_content_chunk")
        if chunk.get("type") == "thinking":
            if text or set(chunk) != {"type", "thinking", "closed"}:
                raise ValueError("invalid_thinking_envelope")
            thoughts = chunk["thinking"]
            if chunk["closed"] is not True or not isinstance(thoughts, list) or not thoughts:
                raise ValueError("unclosed_or_invalid_thinking")
            if any(
                not isinstance(part, dict)
                or set(part) != {"type", "text"}
                or part["type"] != "text"
                or not isinstance(part["text"], str)
                for part in thoughts
            ):
                raise ValueError("invalid_thinking_part")
        elif chunk.get("type") == "text":
            if set(chunk) != {"type", "text"} or not isinstance(chunk["text"], str):
                raise ValueError("invalid_text_chunk")
            text.append(chunk["text"])
        else:
            raise ValueError("unsupported_content_chunk")
    if not text:
        raise ValueError("missing_final_text")
    return "".join(text)


def response_observation(raw, request, config):
    body = request["body"]
    result = {
        "response_id": raw.get("id"), "response_model": raw.get("model"),
        "judgment": None, "actual_billed_cost_usd": None,
        "model_identity_ceiling": "requested_and_returned_id_only; preview_weights_unknown",
    }
    if raw.get("model") not in config.get("accepted_response_models", [body["model"]]):
        return {**result, "status": "unexpected_model_identity"}
    choices = raw.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        return {**result, "status": "invalid_judgment", "error": "choice_count"}
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        return {**result, "status": "invalid_judgment", "error": "invalid_message"}
    finish = choice.get("finish_reason")
    result.update(api_finish_reason=finish, usage=raw.get("usage"))
    if message.get("refusal"):
        return {**result, "status": "refused", "refusal": message["refusal"]}
    if finish != "stop":
        return {**result, "status": "incomplete_response"}
    if message.get("role") != "assistant" or message.get("tool_calls") not in (None, []):
        return {**result, "status": "invalid_judgment", "error": "unsupported_message"}
    try:
        text = final_text(message.get("content"))
    except ValueError as error:
        return {**result, "status": "invalid_judgment", "error": str(error)}
    try:
        data = json.loads(body["messages"][1]["content"])
        verdict = prior.validate_judgment(json.loads(text), data["answer_A"], data["answer_B"])
    except (ValueError, TypeError, KeyError):
        return {**result, "status": "invalid_judgment", "error": "schema_or_quote_check"}
    return {**result, "status": "completed", "judgment": verdict}


def dispatch(provider, body, key):
    if provider != "mistral":
        raise ValueError("Mistral runner cannot dispatch another provider")
    try:
        import certifi
    except ImportError:
        context = ssl.create_default_context()
    else:
        context = ssl.create_default_context(cafile=certifi.where())
    request = urllib.request.Request(
        PROVIDERS[provider]["endpoint"], data=prior.json_bytes(body), method="POST",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(prior.NoRedirect(),
                                       urllib.request.HTTPSHandler(context=context))
    with opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return json.loads(response.read())


def execute(plan_path, provider, replicate, output, *, execute_api=False, resume=False,
            transport=None):
    plan_path, output = Path(plan_path), Path(output)
    plan = prior.load_json(plan_path)
    config, dataset_path, pairs, cases = validate_plan(plan, provider, replicate)
    requests = prepare_requests(plan, provider, replicate, config, pairs, cases)
    snapshot = {
        "format": "latent-workspace-v14-judge-panel-cell-snapshot-v1",
        "provider": provider, "replicate": replicate,
        "plan_sha256": prior.file_sha(plan_path), "dataset_sha256": prior.file_sha(dataset_path),
        "runner_sha256": prior.file_sha(Path(__file__)),
        "validator_sha256": prior.file_sha(Path(prior.__file__)),
        "pairs_sha256": prior.sha256(pairs), "requests_sha256": prior.sha256(requests),
        "provider_config": config, "pair_count": len(pairs), "request_count": len(requests),
        "endpoint": PROVIDERS[provider]["endpoint"],
        "cost_upper_bound_usd": str(sum((Decimal(row["cost_upper_bound_usd"])
                                        for row in requests), Decimal(0))),
        "output_token_upper_bound": len(requests) * config["max_output_tokens"],
        "key_source": PROVIDERS[provider]["env_key"] + "_environment_only_not_recorded",
        "quote_instruction_sha256": prior.sha256(INSTRUCTIONS),
    }
    if output.exists():
        if output.is_symlink() or not resume:
            raise FileExistsError("Cell output exists; explicit --resume is required")
        for name, expected in (("SNAPSHOT.json", snapshot), ("PAIRS.json", {"pairs": pairs}),
                               ("PREPARED_REQUESTS.json", {"requests": requests})):
            if prior.load_json(output / name) != expected:
                raise ValueError("Cell snapshot or prepared data changed; no request dispatched")
    else:
        output.mkdir(parents=True, exist_ok=False)
        prior.write_json(output / "SNAPSHOT.json", snapshot, exclusive=True)
        prior.write_json(output / "PAIRS.json", {"pairs": pairs}, exclusive=True)
        prior.write_json(output / "PREPARED_REQUESTS.json", {"requests": requests}, exclusive=True)
    if not execute_api:
        return {**snapshot, "status": "PREPARED_NOT_DISPATCHED"}
    key = os.environ.get(PROVIDERS[provider]["env_key"])
    if not key:
        raise ValueError("Required provider environment key unavailable; no key recorded")
    transport = transport or dispatch
    receipts, stopped = [], False
    for request in requests:
        filename = request["request_id"] + ".json"
        receipt_path = output / "requests" / filename
        response_path = output / "responses" / filename
        if receipt_path.exists():
            receipt = prior.load_json(receipt_path)
            if any(receipt.get(key) != value for key, value in request.items()):
                raise ValueError("Reserved request changed")
            if receipt["status"] == "response_recorded":
                if not response_path.is_file() or receipt.get("response_sha256") != prior.file_sha(
                    response_path
                ):
                    raise ValueError("Durable response identity changed")
                raw = prior.load_json(response_path)
                if receipt["observation"] != response_observation(raw, request, config) or (
                    receipt["usage_receipt"] != usage_receipt(raw, request, config)
                ):
                    raise ValueError("Response observation or usage changed")
            elif receipt["status"] == "reserved_pending" and response_path.exists():
                raw = prior.load_json(response_path)
                receipt.update(status="response_recorded", recovered_from_response_receipt=True,
                               response_sha256=prior.file_sha(response_path),
                               observation=response_observation(raw, request, config),
                               usage_receipt=usage_receipt(raw, request, config))
                prior.write_json(receipt_path, receipt)
            elif receipt["status"] not in RECEIPT_FAILURES:
                raise ValueError("Unknown reservation status")
            stopped |= receipt["status"] in RECEIPT_FAILURES
            stopped |= receipt.get("observation", {}).get("status") == "unexpected_model_identity"
            stopped |= receipt.get("usage_receipt", {}).get("bound_exceeded", False)
            receipts.append(receipt)
            continue
        if stopped:
            continue
        receipt = {**request, "status": "reserved_pending", "reserved_at": prior.now()}
        prior.write_json(receipt_path, receipt, exclusive=True)
        try:
            raw = transport(provider, request["body"], key)
            prior.write_json(response_path, raw, exclusive=True)
            receipt.update(status="response_recorded", completed_at=prior.now(),
                           response_sha256=prior.file_sha(response_path),
                           observation=response_observation(raw, request, config),
                           usage_receipt=usage_receipt(raw, request, config))
            stopped = receipt["observation"]["status"] == "unexpected_model_identity" or (
                receipt["usage_receipt"].get("bound_exceeded", False)
            )
        except urllib.error.HTTPError as error:
            receipt.update(status="http_error_no_automatic_retry", http_status=error.code,
                           failure_at=prior.now())
            stopped = True
        except Exception as error:
            receipt.update(status="transport_or_recording_ambiguous_no_automatic_retry",
                           error_type=type(error).__name__, failure_at=prior.now())
            stopped = True
        prior.write_json(receipt_path, receipt)
        receipts.append(receipt)
        print(f"panel {provider} r{replicate} {len(receipts)}/28 {receipt['status']}", flush=True)
    report = summarize(pairs, receipts, snapshot)
    report["stopped_on_contract_or_transport_failure"] = stopped
    prior.write_json(output / "SUMMARY.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--provider", choices=sorted(PROVIDERS), default="mistral")
    parser.add_argument("--replicate", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    report = execute(args.plan, args.provider, args.replicate, args.output,
                     execute_api=args.execute, resume=args.resume)
    print(json.dumps({key: report[key] for key in ("status", "provider", "replicate")},
                     ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Mistral extension halted safely: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
