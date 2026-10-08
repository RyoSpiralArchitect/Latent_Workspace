#!/usr/bin/env python3
"""Offline closure audit of the frozen V14 judge requests and durable responses.

No credentials, API calls, retry, or artifact writes. Receipt closure does not
imply valid judgments, human agreement, quality improvement, or non-regression.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

import judge_v14_answer_bank as judge

REPO = Path(__file__).resolve().parents[1]
NONRESPONSE_STATUSES = {
    "reserved_pending", "http_error_no_automatic_retry",
    "transport_or_recording_ambiguous_no_automatic_retry",
}


def load(path):
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Missing, nonregular or symlink artifact: {path.name}")
    return judge.load_json(path)


def equal(actual, expected, label):
    if actual != expected:
        raise ValueError(f"{label} mismatch")


def expected_snapshot(plan_path, cases_path, bank_path, plan, pairs, requests):
    return {
        "format": "latent-workspace-v14-judge-snapshot-v1",
        "plan_sha256": judge.file_sha(plan_path), "cases_sha256": judge.file_sha(cases_path),
        "bank_sha256": judge.file_sha(bank_path),
        "judge_script_sha256": judge.file_sha(Path(judge.__file__)),
        "judge_plan": plan, "pairs_sha256": judge.sha256(pairs),
        "requests_sha256": judge.sha256(requests), "pair_count": len(pairs),
        "request_count": len(requests), "endpoint": judge.ENDPOINT,
        "cost_upper_bound_usd": str(sum((Decimal(row["cost_upper_bound_usd"])
                                        for row in requests), Decimal(0))),
        "output_token_upper_bound": len(requests) * plan["max_output_tokens"],
        "credentials_source": "OPENAI_API_KEY_environment_only_not_recorded",
    }


def directory_files(path):
    if not path.exists():
        return set()
    if not path.is_dir() or path.is_symlink():
        raise ValueError(f"Invalid receipt directory: {path.name}")
    files = list(path.iterdir())
    if any(not item.is_file() or item.is_symlink() or item.suffix != ".json" for item in files):
        raise ValueError(f"Unexpected non-JSON, nonregular or temporary artifact in {path.name}")
    return {item.name for item in files}


def verify(bank_path, plan_path, cases_path, judge_dir):
    bank_path, plan_path, cases_path, judge_dir = map(
        Path, (bank_path, plan_path, cases_path, judge_dir)
    )
    plan, cases, bank = map(load, (plan_path, cases_path, bank_path))
    config = judge.validate_judge_plan(plan)
    equal(plan["source_identity"]["scripts/judge_v14_answer_bank.py"],
          judge.file_sha(Path(judge.__file__)), "Frozen judge source identity")
    equal(plan["cases"]["sha256"], judge.file_sha(cases_path), "Frozen cases identity")
    equal(bank["plan_sha256"], judge.file_sha(plan_path), "Generation plan identity")
    if bank.get("format") != "latent-workspace-v14-answer-bank-v1":
        raise ValueError("Unexpected generation bank format")
    pairs, case_map = judge.prepare_pairs(cases, bank)
    requests = judge.prepare_requests(pairs, case_map, config)
    snapshot = expected_snapshot(plan_path, cases_path, bank_path, config, pairs, requests)
    equal(load(judge_dir / "SNAPSHOT.json"), snapshot, "SNAPSHOT")
    equal(load(judge_dir / "PAIRS.json"), {"pairs": pairs}, "PAIRS")
    equal(load(judge_dir / "PREPARED_REQUESTS.json"), {"requests": requests}, "PREPARED_REQUESTS")
    names = {row["request_id"] + ".json" for row in requests}
    if len(names) != len(requests):
        raise ValueError("Nonunique request identity")
    request_files = directory_files(judge_dir / "requests")
    response_files = directory_files(judge_dir / "responses")
    if request_files - names or response_files - names:
        raise ValueError("Unexpected request/response file outside prepared grid")
    if response_files - request_files:
        raise ValueError("Unreserved response file")
    receipts, missing, unresolved, pending_durable = [], [], [], []
    observation_counts, receipt_counts = Counter(), Counter()
    for request in requests:
        filename = request["request_id"] + ".json"
        if filename not in request_files:
            missing.append(request["request_id"])
            continue
        receipt = load(judge_dir / "requests" / filename)
        equal({key: receipt.get(key) for key in request}, request, "Reserved request body/budget")
        if not isinstance(receipt.get("reserved_at"), str) or not receipt["reserved_at"]:
            raise ValueError("Missing reservation timestamp")
        status = receipt.get("status")
        receipt_counts[status] += 1
        if status == "response_recorded":
            if filename not in response_files:
                raise ValueError("Recorded response is missing its durable body")
            response_path = judge_dir / "responses" / filename
            raw = load(response_path)
            equal(receipt.get("response_sha256"), judge.file_sha(response_path), "Response hash")
            observation = judge.response_observation(raw, request["body"])
            usage = judge.usage_receipt(raw, request, config)
            equal(receipt.get("observation"), observation, "Response observation")
            equal(receipt.get("usage_receipt"), usage, "Response usage receipt")
            observation_counts[observation["status"]] += 1
        elif status in NONRESPONSE_STATUSES:
            if receipt.get("observation") is not None or receipt.get("usage_receipt") is not None:
                raise ValueError("Unresolved receipt carries an unsupported observation")
            unresolved.append(request["request_id"])
            if filename in response_files:
                # Keep this incomplete: verification never mutates/reconciles reservations.
                load(judge_dir / "responses" / filename)
                pending_durable.append(request["request_id"])
        else:
            raise ValueError("Unknown request receipt status")
        receipts.append(receipt)
    summary_path = judge_dir / "SUMMARY.json"
    summary_present = summary_path.is_file()
    if summary_present:
        summary = load(summary_path)
        if type(summary.get("stopped_on_failure")) is not bool:
            raise ValueError("Missing per-invocation runtime stop flag")
        rebuilt = judge.summarize(pairs, receipts)
        rebuilt.update(
            snapshot=snapshot, usage=judge.usage_summary(receipts),
            undispatched_requests=len(requests) - len(receipts),
            # This describes only the last invocation; resume history is not reconstructed.
            stopped_on_failure=summary["stopped_on_failure"],
        )
        equal(summary, rebuilt, "Full SUMMARY recomputation")
    complete = not missing and not unresolved and summary_present
    usage = judge.usage_summary(receipts)
    return {
        "format": "latent-workspace-v14-judge-verification-v1",
        "status": "VERIFIED_RECEIPT_CLOSURE" if complete else "INCOMPLETE_RECEIPTS",
        "mechanical_receipt_closure": complete,
        "source_snapshot_and_request_bodies_verified": True,
        "summary_recomputed_exactly": summary_present,
        "planned_pairs": len(pairs), "planned_requests": len(requests),
        "reserved_requests": len(receipts), "durable_responses": len(response_files),
        "receipt_status_counts": dict(sorted(receipt_counts.items())),
        "observation_status_counts": dict(sorted(observation_counts.items())),
        "valid_judgments": observation_counts["completed"],
        "missing_request_ids": missing, "unresolved_request_ids": unresolved,
        "unresolved_requests_with_durable_body": pending_durable,
        "judge_model_contract_satisfied": not observation_counts["unexpected_model_snapshot"],
        "reported_usage_within_reserved_bounds": usage["usage_bound_exceeded_calls"] == 0,
        "usage": usage, "snapshot": snapshot,
        "semantic_promotion": False, "non_regression": "NOT_ESTABLISHED",
        "human_evaluation": "PENDING",
        "claim_boundary": [
            "Receipt closure can include refused, incomplete or invalid model judgments.",
            "Exact quote checks verify attribution, not the correctness of judge reasoning.",
            "Only stopped_on_failure is accepted as per-invocation runtime metadata.",
            "No API call, credentials access, retry, recovery or artifact write is performed.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=REPO / "data/v14_answer_bank/cases.json")
    parser.add_argument("--judge-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify(args.bank, args.plan, args.cases, args.judge_dir)
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps({"status": "INTEGRITY_FAILURE", "error_type": type(error).__name__,
                          "message": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["mechanical_receipt_closure"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
