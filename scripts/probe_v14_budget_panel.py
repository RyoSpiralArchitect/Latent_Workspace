#!/usr/bin/env python3
"""Six non-study, length-aware canaries; capacity selection never uses study votes."""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

import run_v14_budget_panel as run

prior = run.prior
FIXTURES = "data/v14_budget_panel/canaries.json"


def preparation(provider, cap):
    config = run.config_for(provider, cap)
    cases = prior.load_json(run.REPO / FIXTURES)["cases"]
    requests = []
    for case in cases:
        for order in ("AB", "BA"):
            data = {key: value for key, value in case.items() if key != "id"}
            if order == "BA":
                data["answer_A"], data["answer_B"] = data["answer_B"], data["answer_A"]
            body = run.request_body(provider, 0, config, data)
            requests.append(
                {
                    "request_id": case["id"] + "-" + order,
                    "provider": provider,
                    "order": order,
                    "case_id": case["id"],
                    "study_judgment": False,
                    "identical_control": data["answer_A"] == data["answer_B"],
                    "body": body,
                    "body_sha256": prior.sha256(body),
                    **prior.cost_bound(body, config),
                }
            )
    return {
        "format": "latent-workspace-v14-capacity-preparation-v1",
        "provider": provider,
        "config": config,
        "study_judgments": False,
        "source_identity": {p: prior.file_sha(run.REPO / p) for p in run.SOURCE_FILES},
        "requests": requests,
        "qualification_rule": "all_six_strict_valid; identical_tie; max_output_le_75pct",
    }


def reconstruct(directory):
    directory = Path(directory)
    saved = prior.load_json(directory / "PREPARED.json")
    expected = preparation(saved["provider"], saved["config"]["max_output_tokens"])
    if saved != expected:
        raise ValueError("Capacity preparation changed")
    receipts, rows = [], []
    allowed = {request["request_id"] + ".json" for request in saved["requests"]}
    for name in ("requests", "responses"):
        folder = directory / name
        if folder.exists() and {p.name for p in folder.iterdir()} - allowed:
            raise ValueError("Unknown capacity receipt")
    for request in saved["requests"]:
        path = directory / "requests" / (request["request_id"] + ".json")
        response_path = directory / "responses" / path.name
        if not path.exists():
            if response_path.exists():
                raise ValueError("Unreserved canary response")
            rows.append({"request_id": request["request_id"], "status": "not_dispatched"})
            continue
        receipt = prior.load_json(path)
        if any(receipt.get(k) != v for k, v in request.items()):
            raise ValueError("Capacity request binding changed")
        receipts.append(receipt)
        observation = receipt.get("observation", {})
        usage = receipt.get("usage_receipt", {})
        if receipt["status"] == "response_recorded":
            raw = prior.load_json(response_path)
            if (
                receipt["response_sha256"] != prior.file_sha(response_path)
                or observation != run.response_observation(raw, request, saved["config"])
                or usage != run.usage_receipt(raw, request, saved["config"])
            ):
                raise ValueError("Capacity raw observation changed")
        elif receipt["status"] not in run.RECEIPT_FAILURES:
            raise ValueError("Unknown capacity status")
        valid = (
            observation.get("status") == "completed"
            and usage.get("status") == "REPORTED_BY_API"
            and not usage.get("bound_exceeded", False)
            and (not request["identical_control"] or observation["judgment"]["winner"] == "tie")
        )
        rows.append(
            {
                "request_id": request["request_id"],
                "status": observation.get("status", receipt["status"]),
                "returned_model": observation.get("response_model"),
                "strict_and_control_pass": valid,
                "output_tokens": usage.get("output_tokens"),
            }
        )
    maximum = max((r.get("output_tokens") or 0 for r in rows), default=0)
    return {
        "format": "latent-workspace-v14-capacity-qualification-v1",
        "provider": saved["provider"],
        "config": saved["config"],
        "prepared_sha256": prior.file_sha(directory / "PREPARED.json"),
        "study_judgments": False,
        "planned_calls": 6,
        "reserved_calls": len(receipts),
        "rows": rows,
        "max_reported_output_tokens": maximum,
        "qualified": (
            len(rows) == 6
            and all(r.get("strict_and_control_pass") for r in rows)
            and maximum <= saved["config"]["max_output_tokens"] * 3 // 4
        ),
        "usage": prior.usage_summary(receipts),
        "claim_boundary": (
            "API/schema/quote/capacity calibration only; "
            "not study quality or guaranteed future completion."
        ),
    }


def verify(directory):
    result = reconstruct(directory)
    if prior.load_json(Path(directory) / "QUALIFICATION.json") != result:
        raise ValueError("Qualification does not reconstruct")
    return result


def execute(provider, cap, output, *, execute_api=False, transport=None):
    output = Path(output)
    prepared = preparation(provider, cap)
    output.mkdir(parents=True, exist_ok=False)
    prior.write_json(output / "PREPARED.json", prepared, exclusive=True)
    if not execute_api:
        return {"status": "PREPARED_NOT_DISPATCHED"}
    key = os.environ.get(run.PROVIDERS[provider]["env_key"])
    if not key:
        raise ValueError("Required key unavailable")
    for request in prepared["requests"]:
        receipt = run.record_one(request, prepared["config"], output, key, transport=transport)
        print(
            json.dumps(
                {
                    "canary": request["request_id"],
                    "status": receipt.get("observation", {}).get("status", receipt["status"]),
                    "output_tokens": receipt.get("usage_receipt", {}).get("output_tokens"),
                }
            ),
            flush=True,
        )
        if run.stop_required(receipt):
            break
    result = reconstruct(output)
    prior.write_json(output / "QUALIFICATION.json", result, exclusive=True)
    return result


def metadata(provider, output):
    import certifi

    config = run.PROVIDERS[provider]
    key = os.environ.get(config["env_key"])
    if not key:
        raise ValueError("Key unavailable")
    endpoint = (
        "https://api.mistral.ai/v1/models/"
        if provider == "mistral"
        else "https://api.anthropic.com/v1/models/"
    ) + config["model"]
    headers = (
        {"Authorization": "Bearer " + key}
        if provider == "mistral"
        else {"x-api-key": key, "anthropic-version": "2023-06-01"}
    )
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "provider": provider,
        "requested_model": config["model"],
        "endpoint": endpoint,
        "reserved_at": prior.now(),
        "status": "reserved_pending",
        "study_judgment": False,
    }
    prior.write_json(output / "REQUEST.json", receipt, exclusive=True)
    try:
        opener = urllib.request.build_opener(
            prior.NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())),
        )
        with opener.open(urllib.request.Request(endpoint, headers=headers), timeout=60) as response:
            raw = json.loads(response.read())
        prior.write_json(output / "RESPONSE.json", raw, exclusive=True)
        receipt.update(
            status="response_recorded",
            response_sha256=prior.file_sha(output / "RESPONSE.json"),
            returned_model=raw.get("id"),
        )
    except urllib.error.HTTPError as error:
        receipt.update(status="http_error_no_retry", http_status=error.code)
    except Exception as error:
        receipt.update(status="metadata_failure_no_retry", error_type=type(error).__name__)
    prior.write_json(output / "REQUEST.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=sorted(run.PROVIDERS), required=True)
    parser.add_argument("--cap", type=int, choices=run.CAPS, default=16384)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--metadata", action="store_true")
    args = parser.parse_args()
    if args.metadata and not args.execute:
        raise ValueError("Metadata also requires explicit execute")
    result = (
        metadata(args.provider, args.output)
        if args.metadata
        else execute(args.provider, args.cap, args.output, execute_api=args.execute)
    )
    print(
        json.dumps(
            {
                k: result.get(k)
                for k in (
                    "status",
                    "qualified",
                    "reserved_calls",
                    "max_reported_output_tokens",
                    "returned_model",
                    "http_status",
                )
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Capacity probe halted safely: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
