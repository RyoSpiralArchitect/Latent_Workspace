#!/usr/bin/env python3
"""Seal/recheck only the new V14 judge-panel bundle, entirely offline.

The index binds exact file closure. Verification reconstructs the selection and
all available provider receipts; an absent provider remains planned and missing.
No credential, API, model, or old sealed artifact is created or modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BUNDLE = "provenance/pilots/v14_judge_panel_20261009"
EXPLICIT_FILES = (
    "scripts/prepare_v14_judge_panel.py",
    "scripts/run_v14_judge_panel.py",
    "scripts/summarize_v14_judge_panel.py",
    "scripts/seal_v14_judge_panel.py",
    "tests/test_v14_panel_selection.py",
    "tests/test_v14_judge_panel.py",
    "tests/test_v14_panel_summary.py",
    "tests/test_v14_panel_seal.py",
    "configs/v14/JUDGE_PANEL_PLAN.json",
    "data/v14_judge_panel/selection.json",
    "docs/v14/JUDGE_PANEL_LEARNER_PROPOSAL.md",
)
REQUIRED_BUNDLE_FILES = (
    "PROTOCOL.md",
    "README.md",
    "EXECUTION_NOTE.json",
    "analysis/SUMMARY.json",
    "analysis/PANEL_REVIEW.md",
)
EXCLUDED = ("INDEX.json", "VALIDATION.json")


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def checked_file(root, relative):
    path = root / relative
    require(
        not Path(relative).is_absolute() and path.resolve().is_relative_to(root.resolve()),
        "Artifact escapes repository",
    )
    require(path.is_file() and not path.is_symlink(), f"Missing/nonregular artifact: {relative}")
    require(
        not any(
            parent.is_symlink()
            for parent in path.parents
            if parent != root and parent.is_relative_to(root)
        ),
        "Symlink artifact parent",
    )
    return path


def make_index(root=REPO):
    root = Path(root).resolve()
    bundle = root / BUNDLE
    require(bundle.is_dir() and not bundle.is_symlink(), "Missing/nonregular panel bundle")
    for relative in REQUIRED_BUNDLE_FILES:
        checked_file(root, f"{BUNDLE}/{relative}")
    excluded = {bundle / name for name in EXCLUDED}
    paths = set(EXPLICIT_FILES)
    for path in bundle.rglob("*"):
        require(not path.is_symlink(), "Symlink within panel bundle")
        if path.is_dir() or path in excluded:
            continue
        paths.add(str(path.relative_to(root)))
    artifacts = []
    for relative in sorted(paths):
        path = checked_file(root, relative)
        artifacts.append({"path": relative, "bytes": path.stat().st_size, "sha256": digest(path)})
    return {
        "format": "latent-workspace-v14-judge-panel-index-v1",
        "scope": BUNDLE,
        "excluded_self_receipts": [f"{BUNDLE}/{name}" for name in EXCLUDED],
        "explicit_files": list(EXPLICIT_FILES),
        "artifacts": artifacts,
        "claim_boundary": (
            "Exact artifact integrity only; missingness is retained, not scientific success."
        ),
    }


def write_exclusive(path, value):
    # Parent directory must already be a validated bundle. Never replace evidence.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def verify_payloads(root=REPO):
    root = Path(root).resolve()
    sys.path.insert(0, str(root / "scripts"))
    import prepare_v14_judge_panel as selection
    import summarize_v14_judge_panel as aggregator

    bundle = root / BUNDLE
    selected_path = checked_file(root, "data/v14_judge_panel/selection.json")
    selected = selection.build(root)
    require(
        selected == json.loads(selected_path.read_text()), "Selected panel does not reconstruct"
    )
    serialized = json.dumps(selected, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    require(selected_path.read_text() == serialized, "Selection does not reconstruct byte-for-byte")
    summary = aggregator.aggregate(
        root / "configs/v14/JUDGE_PANEL_PLAN.json", bundle / "cells", bundle / "EXECUTION_NOTE.json"
    )
    recorded = json.loads((bundle / "analysis/SUMMARY.json").read_text())
    require(recorded == summary, "Published panel summary does not reconstruct")
    require(
        (bundle / "analysis/PANEL_REVIEW.md").read_text() == aggregator.render_review(summary),
        "Published panel review does not reconstruct",
    )
    require(
        summary["planned_requests"] == 280 and set(summary["providers"]) == {"openai", "mistral"},
        "Missing provider planned denominator",
    )
    require(
        summary["semantic_promotion"] is False
        and summary["winner"] == "none"
        and summary["pooled_provider_winner"] is None,
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
        if value["not_dispatched_requests"]:
            require(
                summary["status"] == "VERIFIED_PARTIAL_RECEIPTS_NOT_GOLD",
                "Missing provider silently promoted to complete",
            )
        providers[provider] = {
            key: value[key]
            for key in (
                "planned_requests",
                "reserved_requests",
                "durable_responses",
                "not_dispatched_requests",
                "valid_judgments",
                "execution_note_status",
                "all_five_cells_receipt_closed",
            )
        }
    return {
        "selection_rebuilt": True,
        "summary_and_review_rebuilt": True,
        "panel_status": summary["status"],
        "planned_requests": 280,
        "providers": providers,
        "semantic_promotion": False,
        "winner": "none",
        "claim_boundary": (
            "Offline reconstruction is not judge correctness, cross-provider completion, "
            "or model-quality proof."
        ),
    }


def seal(root=REPO):
    root = Path(root).resolve()
    path = root / BUNDLE / "INDEX.json"
    if path.exists():
        raise FileExistsError("Panel index exists; resealing/overwriting is not supported")
    payload = verify_payloads(root)
    index = make_index(root)
    write_exclusive(path, index)
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
    rebuilt = make_index(root)
    require(
        index == rebuilt,
        "Panel index closure/hash differs; missing, extra, duplicate, or changed artifact",
    )
    payload = verify_payloads(root)
    receipt = {
        "format": "latent-workspace-v14-judge-panel-validation-v1",
        "status": "PASS_ARTIFACT_INTEGRITY_ONLY",
        "index_sha256": digest(index_path),
        "artifact_count": len(index["artifacts"]),
        **payload,
    }
    receipt_path = root / BUNDLE / "VALIDATION.json"
    if receipt_path.exists():
        require(
            json.loads(receipt_path.read_text()) == receipt,
            "Existing validation receipt does not reconstruct",
        )
    if write_receipt:
        write_exclusive(receipt_path, receipt)
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
