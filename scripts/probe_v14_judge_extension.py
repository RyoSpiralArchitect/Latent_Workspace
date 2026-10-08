#!/usr/bin/env python3
"""One non-study, identical-answer API contract canary per new provider.

No study answers are used. Exclusive reservations prevent repeat dispatch.
Credentials are read only from the named provider environment variable.
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path

import run_v14_judge_panel as panel

CONFIG = {
    "mistral": {
        "model": "mistral-large-4", "env": "MISTRAL_API_KEY",
        "endpoint": "https://api.mistral.ai/v1/chat/completions",
    },
    "gemini": {
        "model": "gemini-3.7-flash", "env": "GEMINI_API_KEY",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-3.7-flash:generateContent",
    },
}
DATA = {
    "lane": "general", "visible_user_prompt": "Reply with the single word Ready.",
    "evaluator_reference": {"original": "Ready."},
    "rubric": ["The response must be the single word Ready."],
    "reference_selection": "original", "answer_A": "Ready.", "answer_B": "Ready.",
    "finish_reason_A": "eos", "finish_reason_B": "eos",
}


def body(provider):
    if provider == "mistral":
        return panel.request_body("mistral", 0, {"temperature": 0.2,
                                                   "max_output_tokens": 4000}, DATA)
    return {
        "systemInstruction": {"parts": [{"text": panel.INSTRUCTIONS}]},
        "contents": [{"role": "user", "parts": [{
            "text": json.dumps(DATA, ensure_ascii=False, sort_keys=True),
        }]}],
        "generationConfig": {
            "candidateCount": 1, "temperature": 1.0, "seed": 1001,
            "maxOutputTokens": 4000,
            "thinkingConfig": {"thinkingLevel": "LOW", "includeThoughts": False},
            "responseMimeType": "application/json",
            "responseJsonSchema": panel.prior.JUDGMENT_SCHEMA,
        },
    }


def run(provider, output, execute=False):
    spec, request = CONFIG[provider], body(provider)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "format": "latent-workspace-v14-nonstudy-api-canary-v1",
        "provider": provider, "requested_model": spec["model"],
        "endpoint": spec["endpoint"], "body": request,
        "body_sha256": panel.prior.sha256(request),
        "source_sha256": panel.prior.file_sha(Path(__file__)),
        "status": "not_dispatched", "study_judgment": False,
        "claim_boundary": "API contract only; not a study observation or quality evidence.",
    }
    path = output / "REQUEST.json"
    panel.prior.write_json(path, receipt, exclusive=True)
    if not execute:
        return receipt
    key = os.environ.get(spec["env"])
    if not key:
        raise ValueError("Provider key unavailable")
    receipt.update(status="reserved_pending", reserved_at=panel.prior.now())
    panel.prior.write_json(path, receipt)
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
        headers = {"Content-Type": "application/json"}
        headers["Authorization" if provider == "mistral" else "x-goog-api-key"] = (
            "Bearer " + key if provider == "mistral" else key
        )
        opener = urllib.request.build_opener(panel.prior.NoRedirect(),
                                           urllib.request.HTTPSHandler(context=context))
        req = urllib.request.Request(spec["endpoint"], data=panel.prior.json_bytes(request),
                                     headers=headers, method="POST")
        with opener.open(req, timeout=180) as response:
            raw = json.load(response)
        panel.prior.write_json(output / "RESPONSE.json", raw, exclusive=True)
        receipt.update(status="response_recorded", completed_at=panel.prior.now(),
                       response_sha256=panel.prior.file_sha(output / "RESPONSE.json"))
        if provider == "mistral":
            choice = raw["choices"][0]
            content = choice["message"]["content"]
            model, finish, usage = raw.get("model"), choice.get("finish_reason"), raw.get("usage")
            finished = finish == "stop"
        else:
            choice = raw["candidates"][0]
            content = "".join(part.get("text", "") for part in choice["content"]["parts"]
                              if not part.get("thought", False))
            model, finish, usage = (
                raw.get("modelVersion"), choice.get("finishReason"), raw.get("usageMetadata")
            )
            finished = finish == "STOP"
        judgment = panel.prior.validate_judgment(
            json.loads(content), DATA["answer_A"], DATA["answer_B"]
        )
        receipt.update(returned_model=model, finish_reason=finish, usage=usage,
                       schema_and_quotes_valid=True, completed=finished,
                       canary_preference=judgment["winner"])
    except urllib.error.HTTPError as error:
        # The URL contains no secret. Do not retain provider error bodies or headers.
        receipt.update(status="http_error_no_retry", http_status=error.code)
    except Exception as error:
        receipt.update(status="canary_failure_no_retry", error_type=type(error).__name__)
    panel.prior.write_json(path, receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=CONFIG, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    receipt = run(args.provider, args.output, args.execute)
    print(json.dumps({key: receipt.get(key) for key in (
        "provider", "status", "returned_model", "finish_reason", "schema_and_quotes_valid",
        "http_status", "error_type", "usage",
    )}, ensure_ascii=False))


if __name__ == "__main__":
    main()
