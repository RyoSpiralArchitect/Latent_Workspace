#!/usr/bin/env python3
"""One exclusively reserved, non-study Gemini 3.8 API-contract canary."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
from pathlib import Path

import probe_v14_judge_extension as old_probe
import run_v14_gemini38_panel as runner

prior = runner.prior
REPO = Path(__file__).resolve().parents[1]
CONFIG = {
    "max_output_tokens": 4000,
    "max_input_tokens": 32768,
    "random_seed_base": 1001,
    "thinking_level": "LOW",
    "accepted_response_models": ["gemini-3.8-flash"],
    "input_usd_per_million_tokens": 0.75,
    "output_usd_per_million_tokens": 3.75,
}


def run(output, *, execute=False):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    body = runner.request_body("gemini", 0, CONFIG, old_probe.DATA)
    request = {"provider": "gemini", "body": body, **prior.cost_bound(body, CONFIG)}
    sources = [
        "scripts/probe_v14_gemini38.py",
        "scripts/run_v14_gemini38_panel.py",
        "scripts/probe_v14_judge_extension.py",
        "scripts/run_v14_judge_panel.py",
        "scripts/judge_v14_answer_bank.py",
    ]
    receipt = {
        "format": "latent-workspace-v14-gemini38-canary-v1",
        **request,
        "requested_model": runner.MODEL,
        "endpoint": runner.ENDPOINT,
        "body_sha256": prior.sha256(body),
        "source_identity": {path: prior.file_sha(REPO / path) for path in sources},
        "status": "not_dispatched",
        "study_judgment": False,
        "qualification_passed": False,
        "claim_boundary": "Identical-answer API contract only; no study or quality inference.",
    }
    path = output / "REQUEST.json"
    prior.write_json(path, receipt, exclusive=True)
    if not execute:
        return receipt
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise ValueError("Gemini key unavailable; no key value recorded")
    receipt.update(status="reserved_pending", reserved_at=prior.now())
    prior.write_json(path, receipt)
    try:
        raw = runner.dispatch("gemini", body, key)
        prior.write_json(output / "RESPONSE.json", raw, exclusive=True)
        observation = runner.response_observation(raw, request, CONFIG)
        usage = runner.usage_receipt(raw, request, CONFIG)
        receipt.update(
            status="response_recorded",
            completed_at=prior.now(),
            response_sha256=prior.file_sha(output / "RESPONSE.json"),
            observation=observation,
            usage_receipt=usage,
            qualification_passed=(
                observation["status"] == "completed"
                and observation["judgment"]["winner"] == "tie"
                and usage["status"] == "REPORTED_BY_API"
                and not usage.get("bound_exceeded", False)
            ),
        )
    except urllib.error.HTTPError as error:
        receipt.update(status="http_error_no_retry", http_status=error.code)
    except Exception as error:
        receipt.update(status="canary_failure_no_retry", error_type=type(error).__name__)
    prior.write_json(path, receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    receipt = run(args.output, execute=args.execute)
    print(json.dumps({
        "status": receipt["status"],
        "qualification_passed": receipt["qualification_passed"],
        "returned_model": receipt.get("observation", {}).get("response_model"),
        "observation_status": receipt.get("observation", {}).get("status"),
        "usage_receipt": receipt.get("usage_receipt"),
        "http_status": receipt.get("http_status"),
        "error_type": receipt.get("error_type"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
