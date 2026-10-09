#!/usr/bin/env python3
"""Seal new capacity-study receipts while independently reverifying older bundles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import probe_v14_budget_panel as probe
import run_v14_budget_panel as run
import seal_v14_judge_panel as base
import summarize_v14_budget_panel as summary

REPO = run.REPO
BUNDLE = summary.BUNDLE
EXPLICIT = (
    *run.SOURCE_FILES,
    "scripts/prepare_v14_budget_panel.py",
    "scripts/summarize_v14_budget_panel.py",
    "scripts/seal_v14_budget_panel.py",
    "tests/test_v14_budget_panel.py",
    "tests/test_v14_budget_reporting.py",
)


def make_index(root, plan_path):
    root, plan_path = Path(root).resolve(), Path(plan_path).resolve()
    directory = root / BUNDLE
    names = set(EXPLICIT) | {str(plan_path.relative_to(root))}
    for name in (
        "PROTOCOL.md",
        "SCOPE_UPDATE.md",
        "README.md",
        "EXECUTION_NOTE.json",
        "analysis/SUMMARY.json",
        "analysis/PANEL_REVIEW.md",
    ):
        base.checked_file(root, f"{BUNDLE}/{name}")
    for path in directory.rglob("*"):
        base.require(not path.is_symlink(), "Symlink in capacity evidence")
        if path.is_file() and path not in (directory / "INDEX.json", directory / "VALIDATION.json"):
            names.add(str(path.relative_to(root)))
    artifacts = []
    for name in sorted(names):
        path = base.checked_file(root, name)
        artifacts.append({"path": name, "bytes": path.stat().st_size, "sha256": base.digest(path)})
    return {
        "format": "latent-workspace-v14-budget-panel-index-v1",
        "scope": BUNDLE,
        "plan": str(plan_path.relative_to(root)),
        "artifacts": artifacts,
        "excluded_self_receipts": [f"{BUNDLE}/INDEX.json", f"{BUNDLE}/VALIDATION.json"],
        "claim_boundary": "Integrity and reconstruction only; not judge correctness or quality.",
    }


def verify_payloads(root, plan_path):
    root, plan_path = Path(root).resolve(), Path(plan_path).resolve()
    result = summary.aggregate(plan_path, root=root)
    directory = root / BUNDLE
    base.require(
        run.prior.load_json(directory / "analysis/SUMMARY.json") == result,
        "Published summary does not reconstruct",
    )
    base.require(
        (directory / "analysis/PANEL_REVIEW.md").read_text() == summary.render(result),
        "Published reader does not reconstruct",
    )
    plan = run.prior.load_json(plan_path)
    gate = probe.verify((root / plan["qualification"]["path"]).parent)
    note = run.prior.load_json(directory / "EXECUTION_NOTE.json")
    fresh = result["providers"]["mistral_enlarged"]
    for field in ("planned_requests", "reserved_requests", "durable_responses", "valid_judgments"):
        base.require(note["mistral"][field] == fresh[field], "Execution note count differs")
    base.require(
        note["claude_study_requests"] == 0 and note["new_training_or_generation"] is False,
        "Execution scope differs",
    )
    meta_reports = {}
    for provider in ("mistral", "anthropic"):
        folder = directory / "metadata" / provider
        receipt = run.prior.load_json(folder / "REQUEST.json")
        base.require(
            receipt["provider"] == provider and receipt["study_judgment"] is False,
            "Metadata scope changed",
        )
        if receipt["status"] == "response_recorded":
            response = folder / "RESPONSE.json"
            raw = run.prior.load_json(response)
            base.require(
                receipt["response_sha256"] == base.digest(response)
                and receipt["returned_model"] == raw["id"],
                "Metadata response changed",
            )
        else:
            base.require(
                receipt["status"] == "http_error_no_retry"
                and provider == "anthropic"
                and receipt["http_status"] == 401,
                "Unexpected metadata failure",
            )
            base.require(not (folder / "RESPONSE.json").exists(), "Unexpected failed metadata body")
        meta_reports[provider] = {k: receipt[k] for k in ("status", "requested_model")}
    return {
        "panel_status": result["status"],
        "capacity_qualified": gate["qualified"],
        "new_method": {
            k: fresh[k]
            for k in (
                "planned_requests",
                "reserved_requests",
                "durable_responses",
                "valid_judgments",
            )
        },
        "previous_sealed_bundle_reverified": True,
        "metadata": meta_reports,
        "raw_summary_reader_reconstructed": True,
        "winner": "none",
        "semantic_promotion": False,
    }


def seal(root, plan_path):
    directory = Path(root) / BUNDLE
    verify_payloads(root, plan_path)
    index = make_index(root, plan_path)
    base.write_exclusive(directory / "INDEX.json", index)
    return {"status": "SEALED_INTEGRITY_ONLY", "artifact_count": len(index["artifacts"])}


def verify(root, plan_path, *, write_receipt=False):
    directory = Path(root) / BUNDLE
    index = run.prior.load_json(directory / "INDEX.json")
    base.require(index == make_index(root, plan_path), "Index closure or hashes differ")
    result = {
        "format": "latent-workspace-v14-budget-panel-validation-v1",
        "status": "PASS_ARTIFACT_INTEGRITY_ONLY",
        "artifact_count": len(index["artifacts"]),
        "index_sha256": base.digest(directory / "INDEX.json"),
        **verify_payloads(root, plan_path),
    }
    receipt = directory / "VALIDATION.json"
    if receipt.exists():
        base.require(run.prior.load_json(receipt) == result, "Validation receipt changed")
    if write_receipt:
        base.write_exclusive(receipt, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--seal", action="store_true")
    parser.add_argument("--write-receipt", action="store_true")
    args = parser.parse_args()
    result = (
        seal(REPO, args.plan)
        if args.seal
        else verify(REPO, args.plan, write_receipt=args.write_receipt)
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
