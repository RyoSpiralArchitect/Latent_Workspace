"""Bounded, no-retry V15.5 diagnostic API runner and replay helpers."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from collections import Counter
from decimal import Decimal
from pathlib import Path

import run_v14_mistral_extension as mistral_envelope
import v15_5_diagnostics as d

io, REPO = d.io, d.REPO
PROVIDERS = {
    "openai": ("https://api.openai.com/v1/responses", "OPENAI_API_KEY", "gpt-5.4-2026-03-05"),
    "mistral": ("https://api.mistral.ai/v1/chat/completions", "MISTRAL_API_KEY", "mistral-large-4"),
}
NEW_SOURCES = (
    "scripts/v15_5_diagnostics.py",
    "scripts/run_v15_5_diagnostic_judge.py",
    "scripts/summarize_v15_5_diagnostic_judge.py",
    "tests/test_v15_5_diagnostics.py",
    d.PLAN,
    d.DATA,
    "docs/v15_5/DIAGNOSTIC_JUDGE_PROTOCOL.md",
    "scripts/judge_v14_answer_bank.py",
    "scripts/run_v14_judge_panel.py",
    "scripts/run_v14_mistral_extension.py",
)
TERMINAL_FAILURES = {"http_error_no_retry", "transport_or_recording_ambiguous_no_retry"}


def confined(path):
    path = Path(path)
    if not path.is_absolute():
        path = REPO / path
    d.require(path.resolve().is_relative_to(REPO.resolve()), "Output outside repository")
    d.require(not any(p.is_symlink() for p in (path, *path.parents)), "Symlink path")
    return path


def load_plan():
    plan = io.load_json(REPO / d.PLAN)
    d.require(plan["format"] == "v15.5-unary-diagnostic-plan-v1", "Plan format")
    d.require(set(plan["providers"]) == set(PROVIDERS), "Frozen provider set")
    for provider, (endpoint, env_key, model) in PROVIDERS.items():
        config = plan["providers"][provider]
        d.require(
            (config["endpoint"], config["env_key"], config["model"]) == (endpoint, env_key, model),
            "Official endpoint/key/model binding",
        )
        host = endpoint.split("/v1/")[0]
        d.require(config["metadata_endpoint"] == f"{host}/v1/models/{model}", "Metadata URL")
        d.require(config["accepted_response_models"] == [model], "Returned model contract")
        d.require(
            config["max_input_tokens"] == 32768
            and config["max_output_tokens"] == (8192 if provider == "openai" else 16384),
            "Output budget",
        )
    d.require(plan["planned_paid_requests"] == 1120, "Total request budget")
    d.require(
        plan["concurrency_per_provider"] == 4 and plan["minimum_dispatch_spacing_seconds"] == 2,
        "Dispatch schedule",
    )
    return plan


def source_hashes():
    parent = io.load_json(REPO / d.BANK / "raw/STARTED.json")["source_hashes"]
    paths = (
        set(parent)
        | set(NEW_SOURCES)
        | {
            f"{d.BANK}/ARTIFACT_INDEX.json",
            f"{d.BANK}/raw/REPORT.json",
            f"{d.BANK}/VALIDATION.json",
        }
    )
    return {name: io.file_sha(REPO / name) for name in sorted(paths)}


def freeze():
    plan = load_plan()
    d.require(not (REPO / d.DATA).exists() and not (REPO / d.SEAL).exists(), "Freeze collision")
    # Preserve and replay the prior sealed experiment rather than copying its headline only.
    from verify_v15_cue_confirmation import verify_bundle

    previous = verify_bundle(REPO / d.BANK)
    d.require(previous["summary"]["primary_expression_gate"] == "FAIL", "Old gate")
    data = d.make_dataset()
    io.write_json(REPO / d.DATA, data, exclusive=True)
    bodies = {
        f"{provider}/{phase}": d.requests_for(data, plan, provider, phase)
        for provider in PROVIDERS
        for phase in ("calibration", "study")
    }
    seal = {
        "format": "v15.5-diagnostic-source-seal-v1",
        "source_hashes": source_hashes(),
        "request_manifests": {k: io.sha256(v) for k, v in bodies.items()},
        "request_counts": {k: len(v) for k, v in bodies.items()},
        "estimated_undiscounted_upper_bound_usd": str(
            sum(
                (Decimal(r["cost_upper_bound_usd"]) for values in bodies.values() for r in values),
                Decimal(0),
            )
        ),
        "instructions_sha256": io.sha256(d.INSTRUCTIONS),
        "schema_sha256": io.sha256(d.SCHEMA),
        "parent_replay": previous["status"],
        "machine_summary": d.machine_summary(data),
        "actual_invoice_usd": None,
        "new_training": False,
    }
    io.write_json(REPO / d.SEAL, seal, exclusive=True)
    return {k: seal[k] for k in ("request_counts", "estimated_undiscounted_upper_bound_usd")}


def load_frozen():
    plan, seal = load_plan(), io.load_json(REPO / d.SEAL)
    d.require(seal["source_hashes"] == source_hashes(), "Sealed source changed")
    data = io.load_json(REPO / d.DATA)
    d.require(data == d.make_dataset(), "Dataset no longer matches the frozen bank")
    for provider in PROVIDERS:
        for phase in ("calibration", "study"):
            requests = d.requests_for(data, plan, provider, phase)
            d.require(
                io.sha256(requests) == seal["request_manifests"][f"{provider}/{phase}"],
                "Frozen request manifest changed",
            )
    return plan, data, seal


def transport(endpoint, api_key, body=None, timeout=1200):
    import certifi

    context = ssl.create_default_context(cafile=certifi.where())
    opener = urllib.request.build_opener(
        io.NoRedirect(), urllib.request.HTTPSHandler(context=context)
    )
    request = urllib.request.Request(
        endpoint,
        data=io.json_bytes(body) if body is not None else None,
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    with opener.open(request, timeout=timeout) as response:
        text = response.read().decode("utf-8")
    try:
        return json.loads(text)
    except ValueError:
        return {"_unparsed_success_body": text}


def metadata(output):
    plan, _data, _seal = load_frozen()
    output = confined(output)
    output.mkdir(parents=True, exist_ok=False)
    summaries = {}
    for provider, config in plan["providers"].items():
        api_key = os.environ.get(config["env_key"])
        d.require(bool(api_key), f"Missing {config['env_key']}")
        receipt = {
            "provider": provider,
            "endpoint": config["metadata_endpoint"],
            "requested_model": config["model"],
            "started_at": io.now(),
            "paid_inference": False,
        }
        try:
            raw = transport(config["metadata_endpoint"], api_key, timeout=30)
            io.write_json(output / f"{provider}.json", raw, exclusive=True)
            receipt.update(
                status="MODEL_PRESENT" if raw.get("id") == config["model"] else "UNEXPECTED_ID",
                returned_id=raw.get("id"),
                response_sha256=io.file_sha(output / f"{provider}.json"),
            )
        except urllib.error.HTTPError as exc:
            receipt.update(status="HTTP_ERROR", http_status=exc.code)
        except Exception as exc:
            receipt.update(status="TRANSPORT_ERROR", exception_type=type(exc).__name__)
        io.write_json(output / f"{provider}.receipt.json", receipt, exclusive=True)
        summaries[provider] = receipt["status"]
    return summaries


def strict_json(text):
    def pairs(values):
        out = {}
        for name, value in values:
            d.require(name not in out, "Duplicate JSON field")
            out[name] = value
        return out

    def invalid_constant(_value):
        raise ValueError("Nonfinite JSON constant")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_constant)


def observe(raw, request, payload, config):
    if not isinstance(raw, dict):
        return {
            "status": "invalid_judgment",
            "response_id": None,
            "response_model": None,
            "judgment": None,
            "verified_evidence": None,
            "reason": "response_not_object",
        }
    result = {
        "status": "invalid_judgment",
        "response_id": raw.get("id"),
        "response_model": raw.get("model"),
        "judgment": None,
        "verified_evidence": None,
    }
    if raw.get("model") not in config["accepted_response_models"]:
        return {**result, "status": "unexpected_model_identity"}
    if request["provider"] == "openai":
        result["api_finish"] = raw.get("status")
        if raw.get("status") != "completed":
            return {**result, "status": "incomplete_response"}
        outputs = raw.get("output")
        if not isinstance(outputs, list) or any(not isinstance(o, dict) for o in outputs):
            return {**result, "reason": "output_envelope"}
        if any(not isinstance(o.get("content", []), list) for o in outputs):
            return {**result, "reason": "content_envelope"}
        content = [c for o in outputs for c in o.get("content", [])]
        if any(not isinstance(c, dict) for c in content):
            return {**result, "reason": "content_envelope"}
        if any(c.get("type") == "refusal" for c in content):
            return {**result, "status": "refused"}
        texts = [c.get("text") for c in content if c.get("type") == "output_text"]
        if len(texts) != 1 or not isinstance(texts[0], str):
            return {**result, "reason": "final_text_envelope"}
        text = texts[0]
    else:
        choices = raw.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            return {**result, "reason": "choice_count"}
        choice = choices[0]
        result["api_finish"] = choice.get("finish_reason")
        if choice.get("finish_reason") != "stop":
            return {**result, "status": "incomplete_response"}
        msg = choice.get("message", {})
        if not isinstance(msg, dict):
            return {**result, "reason": "message_envelope"}
        if msg.get("refusal"):
            return {**result, "status": "refused"}
        if msg.get("role") != "assistant" or msg.get("tool_calls") not in (None, []):
            return {**result, "reason": "unsupported_message"}
        try:
            text = mistral_envelope.final_text(msg.get("content"))
        except (ValueError, TypeError, KeyError):
            return {**result, "reason": "final_text_envelope"}
    try:
        checked = d.validate_diagnosis(strict_json(text), payload)
    except (ValueError, TypeError, KeyError):
        return {**result, "reason": "schema_or_evidence"}
    return {**result, "status": "valid_diagnosis", **checked}


def usage(raw, request, config):
    if not isinstance(raw, dict):
        return {"status": "UNKNOWN", "actual_billed_cost_usd": None}
    normalized = raw
    if request["provider"] == "mistral":
        info = raw.get("usage")
        normalized = {
            "usage": None
            if not isinstance(info, dict)
            else {
                "input_tokens": info.get("prompt_tokens"),
                "output_tokens": info.get("completion_tokens"),
                "total_tokens": info.get("total_tokens"),
            }
        }
    return io.usage_receipt(normalized, request, config)


def run_one(request, payload, config, cell, api_key, dispatch=transport):
    itemdir = cell / "calls" / request["request_id"]
    itemdir.mkdir(parents=True, exist_ok=False)
    io.write_json(itemdir / "REQUEST.json", request, exclusive=True)
    reservation = {
        "status": "reserved_pending",
        "request_id": request["request_id"],
        "body_sha256": request["body_sha256"],
        "reserved_at": io.now(),
    }
    io.write_json(itemdir / "RESERVATION.json", reservation, exclusive=True)
    outcome = {"request_id": request["request_id"], "started_at": reservation["reserved_at"]}
    start = time.monotonic()
    try:
        raw = dispatch(
            config["endpoint"], api_key, request["body"], timeout=config["http_timeout_seconds"]
        )
        io.write_json(itemdir / "RESPONSE.json", raw, exclusive=True)
        observation = observe(raw, request, payload, config)
        outcome.update(
            status="response_recorded",
            observation=observation,
            usage_receipt=usage(raw, request, config),
            response_sha256=io.file_sha(itemdir / "RESPONSE.json"),
        )
    except urllib.error.HTTPError as exc:
        outcome.update(status="http_error_no_retry", http_status=exc.code)
    except Exception as exc:
        outcome.update(
            status="transport_or_recording_ambiguous_no_retry", exception_type=type(exc).__name__
        )
    outcome.update(ended_at=io.now(), elapsed_seconds=time.monotonic() - start)
    io.write_json(itemdir / "OUTCOME.json", outcome, exclusive=True)
    return outcome


def replay_cell(root, provider, phase, plan, data):
    requests = d.requests_for(data, plan, provider, phase)
    items = {
        r["item_id"]: r
        for r in (data["calibration"] if phase == "calibration" else data["records"])
    }
    cell, result = Path(root) / provider / phase, []
    calls = cell / "calls"
    if calls.exists():
        d.require(
            {p.name for p in calls.iterdir()} <= {r["request_id"] for r in requests},
            "Unknown call directory",
        )
    for request in requests:
        itemdir = calls / request["request_id"]
        row = {
            "item_id": request["item_id"],
            "replicate": request["replicate"],
            "request_id": request["request_id"],
            "status": "not_dispatched",
        }
        if not itemdir.exists():
            result.append(row)
            continue
        d.require(io.load_json(itemdir / "REQUEST.json") == request, "Request identity")
        reservation = io.load_json(itemdir / "RESERVATION.json")
        d.require(
            reservation["request_id"] == request["request_id"]
            and reservation["body_sha256"] == request["body_sha256"],
            "Reservation",
        )
        if not (itemdir / "OUTCOME.json").exists():
            result.append({**row, "status": "reserved_pending_unknown"})
            continue
        outcome = io.load_json(itemdir / "OUTCOME.json")
        d.require(outcome["request_id"] == request["request_id"], "Outcome coordinate")
        row["status"] = outcome["status"]
        if outcome["status"] == "response_recorded":
            d.require(
                io.file_sha(itemdir / "RESPONSE.json") == outcome["response_sha256"],
                "Response hash",
            )
            raw = io.load_json(itemdir / "RESPONSE.json")
            observed = observe(
                raw, request, items[row["item_id"]]["payload"], plan["providers"][provider]
            )
            reported_usage = usage(raw, request, plan["providers"][provider])
            d.require(
                observed == outcome["observation"] and reported_usage == outcome["usage_receipt"],
                "Outcome replay",
            )
            row.update(
                status=observed["status"], observation=observed, usage_receipt=reported_usage
            )
        else:
            d.require(outcome["status"] in TERMINAL_FAILURES, "Unknown outcome status")
        result.append(row)
    return result


def calibration_gate(rows, data, plan):
    controls = {c["item_id"]: c for c in data["calibration"]}
    expected_matches, valid = {}, {}
    for row in rows:
        coord = (row["item_id"], row["replicate"])
        judgment = row.get("observation", {}).get("judgment")
        valid[coord] = row["status"] == "valid_diagnosis"
        expected_matches[coord] = bool(
            valid[coord]
            and all(judgment[k] == v for k, v in controls[row["item_id"]]["expected"].items())
        )
    indexed = {(r["item_id"], r["replicate"]): r for r in rows}
    repeated = 0
    for item_id in controls:
        if all(valid.get((item_id, rep), False) for rep in (0, 1)):
            a, b = (indexed[item_id, rep]["observation"]["judgment"] for rep in (0, 1))
            repeated += all(a[k] == b[k] for k in plan["calibration"]["repeat_signature_fields"])
    critical = all(
        expected_matches.get((c["item_id"], rep), False)
        for c in controls.values()
        for rep in (0, 1)
        if c["control_id"] in plan["calibration"]["critical_controls_all_correct"]
    )
    cfg = plan["calibration"]
    passed = (
        sum(valid.values()) == cfg["required_valid"]
        and sum(expected_matches.values()) >= cfg["minimum_all_expected_fields_correct"]
        and critical
        and repeated >= cfg["minimum_repeat_signature_agreements"]
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "planned": 16,
        "valid": sum(valid.values()),
        "all_expected_fields_correct": sum(expected_matches.values()),
        "critical_controls_all_correct": critical,
        "repeat_signatures_equal": repeated,
        "per_control": [
            {
                "control_id": c["control_id"],
                "expected": c["expected"],
                "replicate_matches": [
                    expected_matches.get((c["item_id"], r), False) for r in (0, 1)
                ],
            }
            for c in data["calibration"]
        ],
    }


def run(root, provider, phase, execute_api=False):
    plan, data, seal = load_frozen()
    root = confined(root)
    requests = d.requests_for(data, plan, provider, phase)
    config = plan["providers"][provider]
    if phase == "study":
        gate = calibration_gate(replay_cell(root, provider, "calibration", plan, data), data, plan)
        d.require(gate["status"] == "PASS", "Calibration failed; study remains undispatched")
    cell = root / provider / phase
    cell.mkdir(parents=True, exist_ok=True)
    if (cell / "REQUESTS.json").exists():
        d.require(io.load_json(cell / "REQUESTS.json") == requests, "Existing manifest changed")
    else:
        io.write_json(cell / "REQUESTS.json", requests, exclusive=True)
    if not execute_api:
        return {"status": "PREPARED_NOT_DISPATCHED", "planned": len(requests)}
    d.require(not (cell / "STARTED.json").exists(), "Cell already started; no implicit resume")
    for name in PROVIDERS:
        metadata_receipt = io.load_json(root / "metadata" / f"{name}.receipt.json")
        d.require(metadata_receipt["status"] == "MODEL_PRESENT", "Model metadata preflight")
    api_key = os.environ.get(config["env_key"])
    d.require(bool(api_key), f"Missing {config['env_key']}")
    io.write_json(
        cell / "STARTED.json",
        {
            "started_at": io.now(),
            "source_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
            ).strip(),
            "source_seal_sha256": io.file_sha(REPO / d.SEAL),
            "plan_sha256": io.file_sha(REPO / d.PLAN),
            "manifest_sha256": io.sha256(requests),
            "provider": provider,
            "phase": phase,
            "planned": len(requests),
            "source_files": len(seal["source_hashes"]),
        },
        exclusive=True,
    )
    items = {
        r["item_id"]: r
        for r in (data["calibration"] if phase == "calibration" else data["records"])
    }
    pending, next_index, completed, stopped = {}, 0, 0, False
    last_start = 0.0
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=plan["concurrency_per_provider"]
    ) as pool:
        while next_index < len(requests) or pending:
            now = time.monotonic()
            if (
                not stopped
                and next_index < len(requests)
                and len(pending) < 4
                and now - last_start >= plan["minimum_dispatch_spacing_seconds"]
            ):
                request = requests[next_index]
                future = pool.submit(
                    run_one, request, items[request["item_id"]]["payload"], config, cell, api_key
                )
                pending[future] = request["request_id"]
                next_index += 1
                last_start = now
            if pending:
                done, _ = concurrent.futures.wait(
                    pending, timeout=0.2, return_when=concurrent.futures.FIRST_COMPLETED
                )
                for future in done:
                    request_id = pending.pop(future)
                    try:
                        outcome = future.result()
                        stopped |= outcome["status"] in TERMINAL_FAILURES
                        status = outcome.get("observation", {}).get("status", outcome["status"])
                    except Exception:
                        stopped, status = True, "recording_failure_unknown"
                    completed += 1
                    print(
                        json.dumps(
                            {
                                "provider": provider,
                                "phase": phase,
                                "completed": completed,
                                "planned": len(requests),
                                "last": request_id,
                                "status": status,
                            }
                        ),
                        flush=True,
                    )
            elif stopped:
                break
            else:
                time.sleep(0.2)
    replay = replay_cell(root, provider, phase, plan, data)
    summary = {
        "status": "HALTED_NO_RETRY" if stopped else "ALL_PLANNED_ATTEMPTED",
        "provider": provider,
        "phase": phase,
        "planned": len(requests),
        "counts": dict(Counter(r["status"] for r in replay)),
        "finished_at": io.now(),
    }
    if phase == "calibration":
        summary["gate"] = calibration_gate(replay, data, plan)
    io.write_json(cell / "FINISHED.json", summary, exclusive=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "metadata", "run"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--provider", choices=PROVIDERS)
    parser.add_argument("--phase", choices=("calibration", "study"))
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.action == "freeze":
        result = freeze()
    elif args.action == "metadata":
        d.require(args.output is not None, "Output required")
        result = metadata(args.output)
    else:
        d.require(args.output is not None and args.provider and args.phase, "Run coordinates")
        result = run(args.output, args.provider, args.phase, args.execute)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
