#!/usr/bin/env python3
"""Offline, deterministic diagnosis of finished Mistral judge output envelopes.

Never dispatches requests, reads credentials, writes files, repairs JSON or emits
thinking/final-answer text. The existing cell verifier reconstructs all request,
raw-response, observation, usage and summary bindings before counting envelopes.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import run_v14_mistral_extension as runner
import summarize_v14_judge_extension as verifier

REPO = Path(__file__).resolve().parents[1]
BUNDLE = "provenance/pilots/v14_judge_extension_20261009"
PLAN = "configs/v14/MISTRAL_JUDGE_EXTENSION_PLAN.json"
FORMAT = "latent-workspace-v14-mistral-output-budget-diagnostic-v1"


def counts(values):
    return dict(sorted(Counter(values).items()))


def envelope(raw):
    """Inspect envelope types and final JSON syntax only, never thinking text."""
    choices = raw.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        return {"envelope_status": "UNKNOWN_CHOICE_SHAPE"}
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        return {"envelope_status": "UNKNOWN_MESSAGE_SHAPE"}
    content = message.get("content")
    if isinstance(content, str):
        chunks = [{"type": "text", "text": content}]
    elif isinstance(content, list) and all(isinstance(part, dict) for part in content):
        chunks = content
    else:
        return {"envelope_status": "UNKNOWN_CONTENT_SHAPE"}
    allowed_types = {"thinking", "text"}
    types = [part.get("type") for part in chunks]
    if any(not isinstance(kind, str) or kind not in allowed_types for kind in types):
        return {"envelope_status": "UNSUPPORTED_CONTENT_TYPE"}
    text_parts = [part.get("text") for part in chunks if part["type"] == "text"]
    if not all(isinstance(value, str) for value in text_parts):
        return {"envelope_status": "UNKNOWN_FINAL_TEXT_SHAPE"}
    text = "".join(text_parts)
    parse_status = "NO_FINAL_TEXT" if not text_parts else "VALID_JSON"
    if text_parts:
        try:
            json.loads(text)
        except (TypeError, ValueError):
            parse_status = "INVALID_JSON_FRAGMENT"
    return {
        "envelope_status": "OBSERVED",
        "content_types": types,
        "thinking_chunk_count": types.count("thinking"),
        "final_text_chunk_count": len(text_parts),
        "final_text_characters": len(text),
        "final_json_syntax": parse_status,
        "finish_reason": choice.get("finish_reason"),
    }


def reconstruct(root=REPO):
    root = Path(root).resolve()
    verifier.require(
        root == runner.REPO.resolve() == runner.panel.REPO.resolve(),
        "Diagnostic root must match the loaded bound runner repository",
    )
    plan_path = root / PLAN
    plan = verifier.load(plan_path)
    config, dataset_path, pairs, _ = runner.validate_plan(plan, "mistral", 0)
    pair_map = {row["pair_id"]: row for row in pairs}
    directory = root / BUNDLE / "cells/mistral"
    verifier.require(
        directory.is_dir() and not directory.is_symlink()
        and {path.name for path in directory.iterdir()} == {f"r{i}" for i in range(5)},
        "Expected exactly five finished Mistral cell directories",
    )
    cells, receipts, raw_rows, valid, failures, bindings = [], [], [], [], [], []

    def bind(path):
        value = {"path": str(path.relative_to(root)), "sha256": runner.prior.file_sha(path)}
        bindings.append(value)
        return value

    for replicate in plan["replicates"]:
        cell = directory / f"r{replicate}"
        rebuilt = verifier.verify_cell(runner, plan_path, "mistral", replicate, cell)
        verifier.require(rebuilt["summary_recomputed_exactly"], "Cell is not finished")
        cell_receipts = []
        for name in ("SNAPSHOT.json", "PAIRS.json", "PREPARED_REQUESTS.json", "SUMMARY.json"):
            bind(cell / name)
        for request_path in sorted((cell / "requests").glob("*.json")):
            receipt = verifier.load(request_path)
            verifier.require(receipt["status"] != "reserved_pending", "Cell has a pending request")
            bind(request_path)
            cell_receipts.append(receipt)
            if receipt["status"] != "response_recorded":
                failures.append({
                    "request_id": receipt["request_id"], "status": receipt["status"],
                    "http_status": receipt.get("http_status"),
                    "reported_usage": None, "actual_billed_cost_usd": None,
                })
                verifier.require(
                    not (cell / "responses" / request_path.name).exists(),
                    "Unreconciled response cannot be included in finished diagnosis",
                )
                continue
            raw_path = cell / "responses" / request_path.name
            bind(raw_path)
            raw = verifier.load(raw_path)
            usage = receipt["usage_receipt"]
            observation = receipt["observation"]
            known_usage = usage.get("status") == "REPORTED_BY_API"
            raw_rows.append({
                "request_id": receipt["request_id"],
                "observation_status": observation["status"],
                "requested_max_tokens": receipt["body"]["max_tokens"],
                "reported_completion_tokens": usage.get("output_tokens") if known_usage else None,
                **envelope(raw),
            })
            if observation["status"] == "completed":
                pair = pair_map[receipt["pair_id"]]
                valid.append({
                    "request_id": receipt["request_id"], "replicate": replicate,
                    "pair_id": receipt["pair_id"], "order": receipt["order"],
                    "case_id": pair["case_id"], "regime": pair["regime"],
                    "comparison": pair["comparison"],
                    "calibration_only": pair["calibration_only"],
                    "winner": observation["judgment"]["winner"],
                    "normalized_preference": runner.prior.normalize_observation(receipt)["winner"],
                })
        receipts.extend(cell_receipts)
        cells.append({
            "replicate": replicate, "planned_requests": rebuilt["planned_requests"],
            "reserved_requests": rebuilt["reserved_requests"],
            "durable_responses": rebuilt["durable_responses"],
            "not_dispatched_requests": rebuilt["not_dispatched_requests"],
            "receipt_status_counts": rebuilt["summary"]["receipt_status_counts"],
            "observation_status_counts": rebuilt["summary"]["observation_status_counts"],
            "complete_valid_order_pairs": sum(
                row["judge_status"] in ("order_consistent", "order_conflict")
                for row in rebuilt["summary"]["pairs"]
            ),
        })
    selected = {(row["replicate"], row["pair_id"], row["order"]): row for row in valid}
    stable = []
    for pair in pairs:
        rows = [selected.get((replicate, pair["pair_id"], order))
                for replicate in plan["replicates"] for order in ("AB", "BA")]
        if all(rows) and len({row["normalized_preference"] for row in rows}) == 1:
            stable.append(pair["pair_id"])
    observations = counts(row["observation_status"] for row in raw_rows)
    finishes = counts(row.get("finish_reason", "UNKNOWN") for row in raw_rows)
    completion = counts(str(row["reported_completion_tokens"]) for row in raw_rows)
    known = [row for row in raw_rows if row["envelope_status"] == "OBSERVED"]
    at_cap = [row for row in raw_rows if row["reported_completion_tokens"] is not None
              and row["reported_completion_tokens"] == row["requested_max_tokens"]]
    return {
        "format": FORMAT,
        "status": "OFFLINE_RECONSTRUCTED_OBSERVATIONS_NOT_GOLD",
        "provider": "mistral", "requested_model": config["model"],
        "source_identity": {
            "scripts/diagnose_v14_mistral_budget.py": runner.prior.file_sha(Path(__file__)),
            **plan["source_identity"],
        },
        "plan": {"path": PLAN, "sha256": runner.prior.file_sha(plan_path)},
        "parent_plan": plan["parent_panel_plan"],
        "dataset": {"path": str(dataset_path.relative_to(root)),
                    "sha256": runner.prior.file_sha(dataset_path)},
        "artifact_bindings": sorted(bindings, key=lambda row: row["path"]),
        "verification": {
            "cell_verifier": "scripts/summarize_v14_judge_extension.py:verify_cell",
            "requests_raw_observations_usage_summaries_recomputed": True,
            "additional_source_binding_required":
                "Diagnostic and verifier covered by extension seal",
            "thinking_text_emitted": False, "final_answer_text_emitted": False,
            "quote_or_json_repair": False, "api_calls": 0,
        },
        "counts": {
            "planned_requests": sum(row["planned_requests"] for row in cells),
            "reserved_requests": len(receipts), "durable_responses": len(raw_rows),
            "strict_valid_judgments": observations.get("completed", 0),
            "incomplete_responses": observations.get("incomplete_response", 0),
            "http_errors": sum(
                row["status"] == "http_error_no_automatic_retry" for row in failures
            ),
            "not_dispatched_requests": sum(row["not_dispatched_requests"] for row in cells),
            "complete_valid_order_pairs": sum(row["complete_valid_order_pairs"] for row in cells),
            "changed_pair_valid_judgments": sum(not row["calibration_only"] for row in valid),
            "all_five_stable_pair_preferences": len(stable),
        },
        "receipt_status_counts": counts(row["status"] for row in receipts),
        "observation_status_counts": observations, "finish_reason_counts": finishes,
        "completion_token_counts": completion,
        "envelope_counts": {
            "thinking_only_no_final_text": sum(
                row["thinking_chunk_count"] > 0 and row["final_text_chunk_count"] == 0
                for row in known
            ),
            "thinking_and_final_text": sum(
                row["thinking_chunk_count"] > 0 and row["final_text_chunk_count"] > 0
                for row in known
            ),
            "final_invalid_json_fragments": sum(
                row["final_json_syntax"] == "INVALID_JSON_FRAGMENT" for row in known
            ),
            "final_syntactically_valid_json": sum(
                row["final_json_syntax"] == "VALID_JSON" for row in known
            ),
            "unknown_envelopes": len(raw_rows) - len(known),
            "at_requested_output_token_cap": len(at_cap),
            "length_termination_at_cap": sum(
                row.get("finish_reason") == "length" for row in at_cap
            ),
        },
        "cells": cells, "raw_envelope_observations": raw_rows,
        "valid_judgments": valid, "unresolved_transport_failures": failures,
        "usage": runner.prior.usage_summary(receipts),
        "claim_boundary": {
            "output_budget_limitation_observed": bool(finishes.get("length", 0)),
            "reasoning_vs_final_token_breakdown": "UNKNOWN_NOT_REPORTED",
            "http_failure_usage_and_cost": "UNKNOWN",
            "actual_invoice": "UNKNOWN",
            "failed_evaluations_are_not_workspace_quality_votes": True,
            "higher_cap_or_reasoning_change_requires_new_prospective_method": True,
            "semantic_promotion": False, "non_regression": "NOT_ESTABLISHED", "winner": "none",
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO)
    args = parser.parse_args()
    print(json.dumps(reconstruct(args.root), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
