#!/usr/bin/env python3
"""One frozen provider/replicate cell of a blinded qualitative judge panel.

No credential is accessed and no API request is sent without --execute. Each
cell has its own durable reservations; ambiguous requests are never resent.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import ssl
import sys
import urllib.error
import urllib.request
from collections import Counter
from decimal import Decimal
from pathlib import Path

import judge_v14_answer_bank as prior

REPO = Path(__file__).resolve().parents[1]
PROVIDERS = {
    "openai": {"endpoint": "https://api.openai.com/v1/responses",
               "env_key": "OPENAI_API_KEY", "model": "gpt-5.4-2026-03-05"},
    "mistral": {"endpoint": "https://api.mistral.ai/v1/chat/completions",
                "env_key": "MISTRAL_API_KEY", "model": "mistral-large-4"},
}
QUOTE_CLARIFICATION = """
Literal quotation rule: the JSON string value in quoted_evidence must itself be
an exact substring of its assigned answer. JSON's syntactic double quotes are
not part of that value. Do not add extra quotation marks, ellipses, or punctuation
inside the value. For answer `The sky is blue.`, use ["sky is blue"], not a
string whose value contains surrounding double-quote characters. Preserve any
quote characters actually present in the answer. There is no automatic repair.
"""
INSTRUCTIONS = prior.INSTRUCTIONS + QUOTE_CLARIFICATION
RECEIPT_FAILURES = {
    "reserved_pending", "http_error_no_automatic_retry",
    "transport_or_recording_ambiguous_no_automatic_retry",
}


def resolve(path):
    candidate = REPO / path
    if candidate.is_symlink() or not candidate.resolve().is_relative_to(REPO.resolve()):
        raise ValueError("Bound source/dataset must be a regular repository file")
    return candidate


def validate_plan(plan, provider, replicate):
    if plan.get("format") != "latent-workspace-v14-judge-panel-plan-v1":
        raise ValueError("Unexpected judge panel plan format")
    if provider not in PROVIDERS or type(replicate) is not int:
        raise ValueError("Unknown provider or invalid replicate")
    if plan["replicates"] != list(range(5)) or replicate not in plan["replicates"]:
        raise ValueError("Expected frozen five-replicate grid")
    if plan["max_calls_per_cell"] != 28 or set(plan["providers"]) != set(PROVIDERS):
        raise ValueError("Expected two providers and 28 calls per cell")
    required = {"scripts/run_v14_judge_panel.py", "scripts/judge_v14_answer_bank.py"}
    if not required <= set(plan["source_identity"]):
        raise ValueError("Required runner/validator source identity missing")
    for name, sha in plan["source_identity"].items():
        if prior.file_sha(resolve(name)) != sha:
            raise ValueError("Frozen panel source identity changed")
    config = plan["providers"][provider]
    fixed = PROVIDERS[provider]
    for name in ("model", "endpoint", "env_key"):
        if config.get(name, fixed[name]) != fixed[name]:
            raise ValueError("Fixed provider model, endpoint or credential source changed")
    accepted = config.get("accepted_response_models", [fixed["model"]])
    if accepted != [fixed["model"]]:
        raise ValueError("Response-model identity must exactly match the frozen requested model")
    if config["max_output_tokens"] != 4000 or config["max_input_tokens"] != 32768:
        raise ValueError("Frozen input/output token bounds changed")
    for field in ("input_usd_per_million_tokens", "output_usd_per_million_tokens"):
        amount = Decimal(str(config[field]))
        if not amount.is_finite() or amount <= 0:
            raise ValueError("Provider rates must be positive finite frozen values")
    if provider == "openai" and config["reasoning_effort"] != "low":
        raise ValueError("OpenAI reasoning effort changed")
    if provider == "mistral" and (
        not math.isfinite(config["temperature"]) or config["temperature"] != 0.2
        or config.get("random_seed_base", 1001) != 1001
    ):
        raise ValueError("Mistral sampling settings changed")
    dataset_path = resolve(plan["dataset"]["path"])
    if prior.file_sha(dataset_path) != plan["dataset"]["sha256"]:
        raise ValueError("Frozen selected dataset identity changed")
    dataset = prior.load_json(dataset_path)
    cases = {case["id"]: case for case in dataset["cases"]}
    if len(cases) != 16 or len(dataset["cases"]) != 16:
        raise ValueError("Expected original 16-case catalog")
    pairs = dataset["pairs"]
    if len(pairs) != 14 or len({pair["pair_id"] for pair in pairs}) != 14:
        raise ValueError("Expected 14 unique preselected pairs")
    if sum(pair["exact_identical"] is True for pair in pairs) != 4:
        raise ValueError("Expected 10 changed pairs plus four actual identical controls")
    for pair in pairs:
        case = cases[pair["case_id"]]
        if pair["lane"] != case["lane"] or pair["lane"] not in ("general", "relation"):
            raise ValueError("Pair/case lane mismatch")
        if pair["comparison"] not in prior.COMPARISONS:
            raise ValueError("Unexpected comparison condition")
        coordinate = [pair["case_id"], pair["regime"], pair["comparison"]]
        if pair["pair_id"] != prior.sha256(coordinate)[:20]:
            raise ValueError("Original pair identity changed")
        for field in ("base_answer", "workspace_answer"):
            if not isinstance(pair[field], str):
                raise ValueError("Answer must be a string")
        identical = pair["base_answer"] == pair["workspace_answer"]
        if pair["exact_identical"] is not identical or pair["calibration_only"] is not identical:
            raise ValueError("Calibration and exact-text identity disagree")
        if not isinstance(case["user_prompt"], str) or not case["user_prompt"]:
            raise ValueError("Visible user prompt missing")
        if "reference" not in case or "rubric" not in case:
            raise ValueError("Case evaluator metadata missing")
        for side in ("base", "workspace"):
            if pair[side + "_finish_reason"] not in ("eos", "length"):
                raise ValueError("Unrecognized generation termination")
    return config, dataset_path, pairs, cases


def input_data(case, pair, order):
    base, workspace = ("base", "workspace") if order == "AB" else ("workspace", "base")
    return {
        "lane": case["lane"], "visible_user_prompt": case["user_prompt"],
        "evaluator_reference": case["reference"], "rubric": case["rubric"],
        "reference_selection": "original", "answer_A": pair[base + "_answer"],
        "answer_B": pair[workspace + "_answer"],
        "finish_reason_A": pair[base + "_finish_reason"],
        "finish_reason_B": pair[workspace + "_finish_reason"],
    }


def request_body(provider, replicate, config, data):
    content = json.dumps(data, ensure_ascii=False, sort_keys=True)
    schema = {"name": "blinded_qualitative_observation", "strict": True,
              "schema": prior.JUDGMENT_SCHEMA}
    if provider == "openai":
        return {
            "model": PROVIDERS[provider]["model"], "store": False, "service_tier": "default",
            "reasoning": {"effort": config["reasoning_effort"]},
            "max_output_tokens": config["max_output_tokens"], "instructions": INSTRUCTIONS,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": content}]}],
            "text": {"format": {"type": "json_schema", **schema}},
        }
    return {
        "model": PROVIDERS[provider]["model"], "stream": False, "service_tier": "standard_only",
        "messages": [{"role": "system", "content": INSTRUCTIONS},
                     {"role": "user", "content": content}],
        "temperature": config["temperature"], "random_seed": 1001 + replicate,
        "max_tokens": config["max_output_tokens"],
        "response_format": {"type": "json_schema", "json_schema": schema},
    }


def prepare_requests(plan, provider, replicate, config, pairs, cases):
    requests = []
    for pair in pairs:
        for order in ("AB", "BA"):
            data = input_data(cases[pair["case_id"]], pair, order)
            body = request_body(provider, replicate, config, data)
            requests.append({
                "request_id": f"{provider}-r{replicate}-{pair['pair_id']}-{order}",
                "provider": provider, "replicate": replicate, "pair_id": pair["pair_id"],
                "order": order, "calibration_only": pair["calibration_only"],
                "body": body, "body_sha256": prior.sha256(body),
                "evaluator_input_sha256": prior.sha256(data), **prior.cost_bound(body, config),
            })
    if len(requests) != plan["max_calls_per_cell"]:
        raise ValueError("Prepared request grid changed")
    cost = sum((Decimal(row["cost_upper_bound_usd"]) for row in requests), Decimal(0))
    cap = config.get("max_cost_usd")
    if cap is not None and (not Decimal(str(cap)).is_finite() or cost > Decimal(str(cap))):
        raise ValueError("Complete cell exceeds frozen cost ceiling; no selective judging")
    return requests


def response_observation(raw, request, config):
    provider, body = request["provider"], request["body"]
    result = {"response_id": raw.get("id"), "response_model": raw.get("model"),
              "judgment": None, "actual_billed_cost_usd": None,
              "model_identity_ceiling": "requested_and_returned_id_only; preview_weights_unknown"
              if provider == "mistral" else "pinned_requested_snapshot_and_returned_id"}
    if raw.get("model") not in config.get("accepted_response_models", [body["model"]]):
        return {**result, "status": "unexpected_model_identity"}
    if provider == "openai":
        # The old helper enforces the requested model; map only a predeclared accepted return ID.
        matched = {**body, "model": raw["model"]}
        observation = prior.response_observation(raw, matched)
        return {**result, **observation}
    choices = raw.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        return {**result, "status": "invalid_judgment", "error": "choice_count"}
    choice = choices[0]
    message = choice.get("message", {})
    finish = choice.get("finish_reason")
    result.update(api_finish_reason=finish, usage=raw.get("usage"))
    if message.get("refusal"):
        return {**result, "status": "refused", "refusal": message["refusal"]}
    if finish != "stop":
        return {**result, "status": "incomplete_response"}
    content = message.get("content")
    if not isinstance(content, str):
        return {**result, "status": "invalid_judgment", "error": "nonstring_content"}
    try:
        data = json.loads(body["messages"][1]["content"])
        verdict = prior.validate_judgment(json.loads(content), data["answer_A"], data["answer_B"])
    except (ValueError, TypeError, KeyError):
        return {**result, "status": "invalid_judgment", "error": "schema_or_quote_check"}
    return {**result, "status": "completed", "judgment": verdict}


def usage_receipt(raw, request, config):
    normalized = raw
    if request["provider"] == "mistral":
        usage = raw.get("usage")
        normalized = {"usage": None if not isinstance(usage, dict) else {
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        }}
    return prior.usage_receipt(normalized, request, config)


def dispatch(provider, body, key):
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
    with opener.open(request, timeout=180) as response:
        return json.loads(response.read())


def summarize(pairs, receipts, snapshot):
    by_coordinate = {(row["pair_id"], row["order"]): row for row in receipts}
    rows = []
    for pair in pairs:
        observations, normalized = [], []
        for order in ("AB", "BA"):
            receipt = by_coordinate.get((pair["pair_id"], order), {})
            observation = receipt.get("observation", {})
            observations.append({
                "request_id": receipt.get("request_id"), "order": order,
                "status": observation.get("status", receipt.get("status", "not_dispatched")),
                "response_model": observation.get("response_model"),
                "judgment": observation.get("judgment"),
            })
            normalized.append(prior.normalize_observation(receipt))
        preference, status = None, "missing_or_invalid_order"
        if all(normalized):
            wins = [row["winner"] for row in normalized]
            status = "order_consistent" if wins[0] == wins[1] else "order_conflict"
            if status == "order_consistent":
                preference = wins[0]
        rows.append({**pair, "judge_status": status, "order_consistent_preference": preference,
                     "observations": observations})
    return {
        "format": "latent-workspace-v14-judge-panel-cell-result-v1",
        "status": "OBSERVATIONS_NOT_GOLD", "provider": snapshot["provider"],
        "replicate": snapshot["replicate"], "snapshot": snapshot, "pairs": rows,
        "planned_requests": snapshot["request_count"], "reserved_requests": len(receipts),
        "durable_responses": sum(row["status"] == "response_recorded" for row in receipts),
        "undispatched_requests": snapshot["request_count"] - len(receipts),
        "receipt_status_counts": dict(sorted(Counter(row["status"] for row in receipts).items())),
        "observation_status_counts": dict(sorted(Counter(
            row["observation"]["status"] for row in receipts if "observation" in row
        ).items())),
        "usage": prior.usage_summary(receipts),
        "semantic_promotion": False, "non_regression": "NOT_ESTABLISHED",
        "human_evaluation": "PENDING", "winner": "none",
        "claim_boundary": [
            "Only selected changed pairs and actual identical calibration controls are judged.",
            "Replicates are repeated judge calls, not independent tasks or independent models.",
            "Model labels are blinded; exact evidence quotes remain strict, with no repair.",
            "Mistral public-preview identifier does not establish an immutable weight version.",
            "Transport, model-identity or usage-contract failures can stop a cell; quality cannot.",
        ],
    }


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
    parser.add_argument("--provider", choices=sorted(PROVIDERS), required=True)
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
        print(f"panel halted safely: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
