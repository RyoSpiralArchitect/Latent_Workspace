#!/usr/bin/env python3
"""Seal additive judge evidence, retaining the independently sealed original panel."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import seal_v14_judge_panel as parent
import summarize_v14_judge_extension as aggregator

REPO = Path(__file__).resolve().parents[1]
BUNDLE = aggregator.BUNDLE
EXPLICIT_FILES = (
    "scripts/run_v14_gemini_panel.py",
    "scripts/run_v14_mistral_extension.py",
    "scripts/probe_v14_judge_extension.py",
    "scripts/summarize_v14_judge_extension.py",
    "scripts/seal_v14_judge_extension.py",
    "tests/test_v14_gemini_panel.py",
    "tests/test_v14_mistral_extension.py",
    "tests/test_v14_extension_summary.py",
    "tests/test_v14_extension_seal.py",
    "configs/v14/GEMINI_JUDGE_PANEL_PLAN.json",
    "configs/v14/MISTRAL_JUDGE_EXTENSION_PLAN.json",
    "docs/v14/JUDGE_EXTENSION_LEARNER_UPDATE.md",
    f"{aggregator.ORIGINAL_BUNDLE}/INDEX.json",
    f"{aggregator.ORIGINAL_BUNDLE}/VALIDATION.json",
)
REQUIRED_BUNDLE_FILES = (
    "PROTOCOL.md",
    "README.md",
    "EXECUTION_NOTE.json",
    "analysis/SUMMARY.json",
    "analysis/PANEL_REVIEW.md",
)
EXCLUDED = ("INDEX.json", "VALIDATION.json")
require, digest, checked_file = parent.require, parent.digest, parent.checked_file


def make_index(root=REPO):
    root = Path(root).resolve()
    bundle = root / BUNDLE
    require(bundle.is_dir() and not bundle.is_symlink(), "Missing/nonregular extension bundle")
    for relative in REQUIRED_BUNDLE_FILES:
        checked_file(root, f"{BUNDLE}/{relative}")
    excluded = {bundle / name for name in EXCLUDED}
    paths = set(EXPLICIT_FILES)
    for path in bundle.rglob("*"):
        require(not path.is_symlink(), "Symlink within extension bundle")
        if path.is_dir() or path in excluded:
            continue
        paths.add(str(path.relative_to(root)))
    artifacts = []
    for relative in sorted(paths):
        path = checked_file(root, relative)
        artifacts.append({"path": relative, "bytes": path.stat().st_size, "sha256": digest(path)})
    return {
        "format": "latent-workspace-v14-judge-extension-index-v1",
        "scope": BUNDLE,
        "excluded_self_receipts": [f"{BUNDLE}/{name}" for name in EXCLUDED],
        "explicit_files": list(EXPLICIT_FILES),
        "artifacts": artifacts,
        "original_evidence_policy": "Original sealed index referenced; no duplicate OpenAI cells.",
        "claim_boundary": "Artifact integrity/receipt reconstruction only; no semantic promotion.",
    }


def verify_payloads(root=REPO):
    root = Path(root).resolve()
    bundle = root / BUNDLE
    summary = aggregator.aggregate(root)
    require(
        json.loads((bundle / "analysis/SUMMARY.json").read_text()) == summary,
        "Published extension summary does not reconstruct",
    )
    require(
        (bundle / "analysis/PANEL_REVIEW.md").read_text() == aggregator.render_review(summary),
        "Published extension review does not reconstruct",
    )
    require(
        summary["planned_requests"] == 420
        and summary["newly_planned_requests"] == 280
        and summary["reused_openai_requests"] == 140
        and set(summary["providers"]) == set(aggregator.PROVIDERS),
        "Three-provider or reused-evidence planned denominator changed",
    )
    require(
        summary["semantic_promotion"] is False
        and summary["winner"] == "none"
        and summary["pooled_provider_winner"] is None
        and summary["non_regression"] == "NOT_ESTABLISHED",
        "Scientific claim ceiling changed",
    )
    providers = {}
    for provider, value in summary["providers"].items():
        require(
            value["planned_requests"] == 140 and value["planned_cells"] == 5,
            "Provider planned denominator changed",
        )
        require(
            value["reserved_requests"] + value["not_dispatched_requests"] == 140,
            "Provider missingness denominator differs",
        )
        if not value["all_five_cells_receipt_closed"]:
            require(
                summary["status"] == "VERIFIED_PARTIAL_RECEIPTS_NOT_GOLD",
                "Incomplete receipts silently promoted to complete",
            )
        providers[provider] = {
            key: value[key]
            for key in (
                "planned_requests",
                "reserved_requests",
                "durable_responses",
                "not_dispatched_requests",
                "valid_judgments",
                "evidence_origin",
                "all_five_cells_receipt_closed",
            )
        }
    return {
        "original_sealed_panel_reverified": True,
        "summary_and_review_rebuilt": True,
        "panel_status": summary["status"],
        "planned_requests": 420,
        "newly_planned_requests": 280,
        "reused_openai_requests": 140,
        "providers": providers,
        "semantic_promotion": False,
        "winner": "none",
        "claim_boundary": "Integrity is not judge correctness, scientific success or quality.",
    }


def seal(root=REPO):
    root = Path(root).resolve()
    path = root / BUNDLE / "INDEX.json"
    if path.exists():
        raise FileExistsError("Extension index exists; resealing/overwriting is not supported")
    payload = verify_payloads(root)
    index = make_index(root)
    parent.write_exclusive(path, index)
    return {
        "status": "SEALED_INTEGRITY_ONLY",
        "artifact_count": len(index["artifacts"]),
        "index_sha256": digest(path),
        **payload,
    }


def verify(root=REPO, *, write_receipt=False):
    root = Path(root).resolve()
    index_path = checked_file(root, f"{BUNDLE}/INDEX.json")
    index = json.loads(index_path.read_text())
    require(
        index == make_index(root),
        "Extension index closure/hash differs; missing, extra, duplicate, or changed artifact",
    )
    receipt = {
        "format": "latent-workspace-v14-judge-extension-validation-v1",
        "status": "PASS_ARTIFACT_INTEGRITY_ONLY",
        "index_sha256": digest(index_path),
        "artifact_count": len(index["artifacts"]),
        **verify_payloads(root),
    }
    receipt_path = root / BUNDLE / "VALIDATION.json"
    if receipt_path.exists():
        require(
            json.loads(receipt_path.read_text()) == receipt,
            "Existing validation receipt does not reconstruct",
        )
    if write_receipt:
        parent.write_exclusive(receipt_path, receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--seal", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--write-receipt", action="store_true")
    args = parser.parse_args()
    if args.seal and args.write_receipt:
        parser.error("--write-receipt is available only with --verify")
    result = seal() if args.seal else verify(write_receipt=args.write_receipt)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
