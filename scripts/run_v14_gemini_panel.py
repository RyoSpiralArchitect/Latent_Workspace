#!/usr/bin/env python3
"""Additive Gemini cell runner; old selected data, rubric and artifacts stay sealed.

The parent plan supplies the exact paired data. No credentials or API are used
without --execute. Each provider/replicate cell reserves all dispatches durably;
an ambiguous request is never resent, including when resuming a stopped cell.
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
MODEL = "gemini-3.7-flash"
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/" + MODEL + ":generateContent"
PROVIDERS = {"gemini": {"model": MODEL, "endpoint": ENDPOINT, "env_key": "GEMINI_API_KEY"}}
INSTRUCTIONS = panel.INSTRUCTIONS
RECEIPT_FAILURES = panel.RECEIPT_FAILURES
EXECUTION_GATES = {"READY", "BLOCKED_requested_model_mismatch"}


def resolve(path):
    candidate = REPO / path
    if candidate.is_symlink() or not candidate.resolve().is_relative_to(REPO.resolve()):
        raise ValueError("Bound file must be a regular repository file")
    return candidate


def validate_plan(plan, provider, replicate):
    if plan.get("format") != "latent-workspace-v14-gemini-panel-plan-v1":
        raise ValueError("Unexpected Gemini panel plan format")
    if provider != "gemini" or type(replicate) is not int:
        raise ValueError("Invalid provider or replicate")
    if plan["replicates"] != list(range(5)) or replicate not in plan["replicates"]:
        raise ValueError("Expected frozen five-replicate grid")
    if plan["max_calls_per_cell"] != 28 or set(plan["providers"]) != {"gemini"}:
        raise ValueError("Expected Gemini and 28 calls per cell")
    required = {
        "scripts/run_v14_gemini_panel.py",
        "scripts/run_v14_judge_panel.py",
        "scripts/judge_v14_answer_bank.py",
    }
    if not required <= set(plan["source_identity"]):
        raise ValueError("Required runner/validator source identity missing")
    for name, sha in plan["source_identity"].items():
        if prior.file_sha(resolve(name)) != sha:
            raise ValueError("Frozen Gemini source identity changed")
    parent_path = resolve(plan["parent_panel_plan"]["path"])
    if prior.file_sha(parent_path) != plan["parent_panel_plan"]["sha256"]:
        raise ValueError("Frozen parent plan identity changed")
    parent = prior.load_json(parent_path)
    if plan["dataset"] != parent["dataset"]:
        raise ValueError("Gemini must use the exact original selected dataset")
    _, dataset_path, pairs, cases = panel.validate_plan(parent, "openai", replicate)
    config = plan["providers"][provider]
    gate = config.get("execution_gate", "READY")
    if not isinstance(gate, str) or gate not in EXECUTION_GATES:
        raise ValueError("Unknown Gemini execution gate")
    for key, value in PROVIDERS[provider].items():
        if config.get(key) != value:
            raise ValueError("Fixed Gemini model, endpoint or key source changed")
    accepted = config.get("accepted_response_models")
    if accepted != [MODEL]:
        raise ValueError("Expected one exact predeclared Gemini response model ID")
    fixed_settings = {
        "max_output_tokens": 4000,
        "max_input_tokens": 32768,
        "temperature": 1.0,
        "random_seed_base": 1001,
        "thinking_level": "LOW",
    }
    if any(
        config.get(key) != value or isinstance(config.get(key), bool)
        for key, value in fixed_settings.items()
    ):
        raise ValueError("Frozen Gemini generation settings changed")
    for field in ("input_usd_per_million_tokens", "output_usd_per_million_tokens"):
        amount = Decimal(str(config[field]))
        if not amount.is_finite() or amount <= 0:
            raise ValueError("Provider rates must be positive finite frozen values")
    return config, dataset_path, pairs, cases


def request_body(provider, replicate, config, data):
    if provider != "gemini":
        raise ValueError("Gemini runner cannot dispatch another provider")
    return {
        "systemInstruction": {"parts": [{"text": INSTRUCTIONS}]},
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": json.dumps(data, ensure_ascii=False, sort_keys=True),
                    }
                ],
            }
        ],
        "generationConfig": {
            "candidateCount": 1,
            "maxOutputTokens": config["max_output_tokens"],
            "temperature": config["temperature"],
            "seed": config["random_seed_base"] + replicate,
            "thinkingConfig": {"thinkingLevel": config["thinking_level"], "includeThoughts": False},
            "responseMimeType": "application/json",
            "responseJsonSchema": prior.JUDGMENT_SCHEMA,
        },
    }


def prepare_requests(plan, provider, replicate, config, pairs, cases):
    requests = []
    for pair in pairs:
        for order in ("AB", "BA"):
            data = panel.input_data(cases[pair["case_id"]], pair, order)
            body = request_body(provider, replicate, config, data)
            requests.append(
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
    if len(requests) != plan["max_calls_per_cell"]:
        raise ValueError("Prepared request grid changed")
    cost = sum((Decimal(row["cost_upper_bound_usd"]) for row in requests), Decimal(0))
    cap = config.get("max_cost_usd")
    if cap is not None and (not Decimal(str(cap)).is_finite() or cost > Decimal(str(cap))):
        raise ValueError("Complete cell exceeds frozen cost ceiling; no selective judging")
    return requests


def response_observation(raw, request, config):
    result = {
        "response_id": raw.get("responseId"),
        "response_model": raw.get("modelVersion"),
        "judgment": None,
        "actual_billed_cost_usd": None,
        "model_identity_ceiling": "requested_and_returned_id_only; immutable_weights_unknown",
    }
    if raw.get("modelVersion") not in config["accepted_response_models"]:
        return {**result, "status": "unexpected_model_identity"}
    feedback = raw.get("promptFeedback", {})
    if isinstance(feedback, dict) and feedback.get("blockReason") not in (
        None,
        "BLOCK_REASON_UNSPECIFIED",
    ):
        return {**result, "status": "refused", "block_reason": feedback["blockReason"]}
    candidates = raw.get("candidates")
    if (
        not isinstance(candidates, list)
        or len(candidates) != 1
        or not isinstance(candidates[0], dict)
    ):
        return {**result, "status": "invalid_judgment", "error": "candidate_count"}
    candidate = candidates[0]
    finish = candidate.get("finishReason")
    result.update(api_finish_reason=finish, usage=raw.get("usageMetadata"))
    if finish in {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "RECITATION"}:
        return {**result, "status": "refused", "block_reason": finish}
    if finish != "STOP":
        return {**result, "status": "incomplete_response"}
    content = candidate.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list) or not parts:
        return {**result, "status": "invalid_judgment", "error": "missing_parts"}
    text = []
    for part in parts:
        if not isinstance(part, dict):
            return {**result, "status": "invalid_judgment", "error": "invalid_part"}
        if part.get("thought") is True:
            continue
        if not isinstance(part.get("text"), str) or set(part) - {
            "text",
            "thought",
            "thoughtSignature",
        }:
            return {**result, "status": "invalid_judgment", "error": "nontext_content"}
        text.append(part["text"])
    try:
        data = json.loads(request["body"]["contents"][0]["parts"][0]["text"])
        verdict = prior.validate_judgment(
            json.loads("".join(text)), data["answer_A"], data["answer_B"]
        )
    except (ValueError, TypeError, KeyError):
        return {**result, "status": "invalid_judgment", "error": "schema_or_quote_check"}
    return {**result, "status": "completed", "judgment": verdict}


def usage_receipt(raw, request, config):
    usage = raw.get("usageMetadata")
    if not isinstance(usage, dict) or any(
        type(usage.get(field)) is not int or usage[field] < 0
        for field in ("promptTokenCount", "totalTokenCount")
    ):
        return {"status": "UNKNOWN", "actual_billed_cost_usd": None}
    output = usage["totalTokenCount"] - usage["promptTokenCount"]
    candidates, thoughts = usage.get("candidatesTokenCount"), usage.get("thoughtsTokenCount")
    for value in (candidates, thoughts):
        if value is not None and (type(value) is not int or value < 0 or value > output):
            return {"status": "UNKNOWN", "actual_billed_cost_usd": None}
    if candidates is not None and thoughts is not None and candidates + thoughts != output:
        return {"status": "UNKNOWN", "actual_billed_cost_usd": None}
    normalized = {
        "usage": {
            "input_tokens": usage["promptTokenCount"],
            "output_tokens": output,
            "total_tokens": usage["totalTokenCount"],
        }
    }
    receipt = prior.usage_receipt(normalized, request, config)
    if receipt["status"] == "REPORTED_BY_API":
        receipt.update(
            reported_candidate_tokens=candidates,
            reported_thought_tokens=thoughts,
            output_accounting="totalTokenCount_minus_promptTokenCount_including_thoughts",
        )
    return receipt


def dispatch(provider, body, key):
    if provider != "gemini":
        raise ValueError("Gemini runner cannot dispatch another provider")
    try:
        import certifi
    except ImportError:
        context = ssl.create_default_context()
    else:
        context = ssl.create_default_context(cafile=certifi.where())
    request = urllib.request.Request(
        ENDPOINT,
        data=prior.json_bytes(body),
        method="POST",
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(
        prior.NoRedirect(), urllib.request.HTTPSHandler(context=context)
    )
    with opener.open(request, timeout=180) as response:
        return json.loads(response.read())


def summarize(pairs, receipts, snapshot):
    result = panel.summarize(pairs, receipts, snapshot)
    result["claim_boundary"] = [
        item.replace("Mistral public-preview", "Gemini stable-model")
        for item in result["claim_boundary"]
    ] + [
        "Gemini settings are provider-specific, not a compute-matched intervention.",
        "Gemini billed output estimates include thinking; missing components remain null.",
    ]
    return result


def execute(
    plan_path, provider, replicate, output, *, execute_api=False, resume=False, transport=None
):
    plan_path, output = Path(plan_path), Path(output)
    plan = prior.load_json(plan_path)
    config, dataset_path, pairs, cases = validate_plan(plan, provider, replicate)
    if execute_api and config.get("execution_gate", "READY") != "READY":
        raise ValueError("Gemini execution gate is not READY; no output or request reserved")
    requests = prepare_requests(plan, provider, replicate, config, pairs, cases)
    snapshot = {
        "format": "latent-workspace-v14-judge-panel-cell-snapshot-v1",
        "provider": provider,
        "replicate": replicate,
        "plan_sha256": prior.file_sha(plan_path),
        "dataset_sha256": prior.file_sha(dataset_path),
        "runner_sha256": prior.file_sha(Path(__file__)),
        "validator_sha256": prior.file_sha(Path(prior.__file__)),
        "pairs_sha256": prior.sha256(pairs),
        "requests_sha256": prior.sha256(requests),
        "provider_config": config,
        "pair_count": len(pairs),
        "request_count": len(requests),
        "endpoint": ENDPOINT,
        "cost_upper_bound_usd": str(
            sum((Decimal(row["cost_upper_bound_usd"]) for row in requests), Decimal(0))
        ),
        "output_token_upper_bound": len(requests) * config["max_output_tokens"],
        "key_source": PROVIDERS[provider]["env_key"] + "_environment_only_not_recorded",
        "quote_instruction_sha256": prior.sha256(INSTRUCTIONS),
    }
    if output.exists():
        if output.is_symlink() or not resume:
            raise FileExistsError("Cell output exists; explicit --resume is required")
        for name, expected in (
            ("SNAPSHOT.json", snapshot),
            ("PAIRS.json", {"pairs": pairs}),
            ("PREPARED_REQUESTS.json", {"requests": requests}),
        ):
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
        raise ValueError("Required Gemini environment key unavailable; no key recorded")
    transport = transport or dispatch
    receipts, stopped = [], False
    for request in requests:
        filename = request["request_id"] + ".json"
        receipt_path, response_path = (
            output / "requests" / filename,
            output / "responses" / filename,
        )
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
                receipt.update(
                    status="response_recorded",
                    recovered_from_response_receipt=True,
                    response_sha256=prior.file_sha(response_path),
                    observation=response_observation(raw, request, config),
                    usage_receipt=usage_receipt(raw, request, config),
                )
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
            receipt.update(
                status="response_recorded",
                completed_at=prior.now(),
                response_sha256=prior.file_sha(response_path),
                observation=response_observation(raw, request, config),
                usage_receipt=usage_receipt(raw, request, config),
            )
            stopped = receipt["observation"]["status"] == "unexpected_model_identity" or (
                receipt["usage_receipt"].get("bound_exceeded", False)
            )
        except urllib.error.HTTPError as error:
            receipt.update(
                status="http_error_no_automatic_retry",
                http_status=error.code,
                failure_at=prior.now(),
            )
            stopped = True
        except Exception as error:
            receipt.update(
                status="transport_or_recording_ambiguous_no_automatic_retry",
                error_type=type(error).__name__,
                failure_at=prior.now(),
            )
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
    parser.add_argument("--provider", choices=["gemini"], default="gemini")
    parser.add_argument("--replicate", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
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
    print(
        json.dumps(
            {key: report[key] for key in ("status", "provider", "replicate")}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Gemini panel halted safely: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
