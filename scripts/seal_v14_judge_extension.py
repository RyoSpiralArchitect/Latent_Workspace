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
    "scripts/run_v14_gemini38_panel.py",
    "scripts/run_v14_mistral_extension.py",
    "scripts/probe_v14_judge_extension.py",
    "scripts/probe_v14_gemini38.py",
    "scripts/diagnose_v14_mistral_budget.py",
    "scripts/summarize_v14_judge_extension.py",
    "scripts/seal_v14_judge_extension.py",
    "tests/test_v14_gemini_panel.py",
    "tests/test_v14_gemini38_panel.py",
    "tests/test_v14_mistral_extension.py",
    "tests/test_v14_mistral_budget.py",
    "tests/test_v14_extension_summary.py",
    "tests/test_v14_extension_seal.py",
    "configs/v14/GEMINI_JUDGE_PANEL_PLAN.json",
    "configs/v14/GEMINI38_JUDGE_PANEL_PLAN.json",
    "configs/v14/MISTRAL_JUDGE_EXTENSION_PLAN.json",
    "docs/v14/JUDGE_EXTENSION_LEARNER_UPDATE.md",
    f"{aggregator.ORIGINAL_BUNDLE}/INDEX.json",
    f"{aggregator.ORIGINAL_BUNDLE}/VALIDATION.json",
)
REQUIRED_BUNDLE_FILES = (
    "PROTOCOL.md",
    "GEMINI38_AMENDMENT.md",
    "README.md",
    "EXECUTION_NOTE.json",
    "analysis/SUMMARY.json",
    "analysis/PANEL_REVIEW.md",
    "diagnostics/MISTRAL_OUTPUT_BUDGET.json",
)
EXCLUDED = ("INDEX.json", "VALIDATION.json")
require, digest, checked_file = parent.require, parent.digest, parent.checked_file


def verify_original_canaries(root=REPO):
    """Recompute compatibility observations, never resending or repairing responses."""
    import run_v14_gemini_panel as blocked_gemini
    import run_v14_mistral_extension as mistral

    root = Path(root).resolve()
    prefix = f"{BUNDLE}/preflight"
    qualification = json.loads(checked_file(root, f"{prefix}/QUALIFICATION.json").read_text())
    require(
        qualification["format"] == "latent-workspace-v14-nonstudy-api-qualification-v1"
        and qualification["study_judgments"] is False,
        "Original canary qualification format or scope changed",
    )
    expected = {
        "mistral": (mistral, "mistral-large-4", f"{prefix}/PROBE_EXECUTED.py"),
        "gemini": (blocked_gemini, "gemini-3.1-pro-preview", f"{prefix}/PROBE_EXECUTED.py"),
        "gemini_3_7": (blocked_gemini, "gemini-3.7-flash", "scripts/probe_v14_judge_extension.py"),
    }
    rows = qualification["canaries"]
    require(
        len(rows) == 3 and {row["directory"] for row in rows} == set(expected),
        "Original canary inventory changed",
    )
    reports = []
    for row in rows:
        module, requested_model, source = expected[row["directory"]]
        request_path = checked_file(root, f"{prefix}/{row['directory']}/REQUEST.json")
        response_path = checked_file(root, f"{prefix}/{row['directory']}/RESPONSE.json")
        receipt, raw = json.loads(request_path.read_text()), json.loads(response_path.read_text())
        require(
            row["request_sha256"] == digest(request_path)
            and row["response_sha256"] == digest(response_path),
            "Original canary raw/request hash changed",
        )
        require(
            receipt["body_sha256"] == module.prior.sha256(receipt["body"])
            and receipt["response_sha256"] == digest(response_path),
            "Original canary durable body binding changed",
        )
        require(
            row["executed_probe_sha256"]
            == digest(checked_file(root, source))
            == receipt["source_sha256"]
            and row["validator_sha256"] == digest(Path(module.prior.__file__)),
            "Original canary source/validator identity changed",
        )
        require(
            receipt["requested_model"] == row["requested_model"] == requested_model,
            "Original canary requested model changed",
        )
        observation = module.response_observation(
            raw,
            {"provider": receipt["provider"], "body": receipt["body"]},
            {"accepted_response_models": [requested_model]},
        )
        require(
            row["original_receipt_status"] == receipt["status"]
            and row["offline_strict_observation_status"] == observation["status"]
            and row["returned_model"] == observation["response_model"]
            and row["winner"] == (observation.get("judgment") or {}).get("winner")
            and row["judgment_repaired"] is False,
            "Original canary qualification does not reconstruct",
        )
        reports.append(
            {
                "directory": row["directory"],
                "status": observation["status"],
                "requested_model": requested_model,
                "returned_model": observation["response_model"],
            }
        )
    return reports


def verify_gemini38_canary(root=REPO):
    import probe_v14_gemini38 as probe

    root = Path(root).resolve()
    prefix = f"{BUNDLE}/preflight/gemini_3_8"
    path = checked_file(root, f"{prefix}/REQUEST.json")
    receipt = json.loads(path.read_text())
    module = probe.runner
    body = module.request_body("gemini", 0, probe.CONFIG, probe.old_probe.DATA)
    request = {"provider": "gemini", "body": body, **module.prior.cost_bound(body, probe.CONFIG)}
    require(
        receipt["format"] == "latent-workspace-v14-gemini38-canary-v1"
        and receipt["study_judgment"] is False
        and receipt["requested_model"] == module.MODEL
        and receipt["endpoint"] == module.ENDPOINT,
        "Gemini 3.8 canary identity or scope changed",
    )
    require(
        all(receipt.get(key) == value for key, value in request.items())
        and receipt["body_sha256"] == module.prior.sha256(body),
        "Gemini 3.8 canary request/budget does not reconstruct",
    )
    sources = {
        "scripts/probe_v14_gemini38.py",
        "scripts/run_v14_gemini38_panel.py",
        "scripts/probe_v14_judge_extension.py",
        "scripts/run_v14_judge_panel.py",
        "scripts/judge_v14_answer_bank.py",
    }
    require(
        set(receipt["source_identity"]) == sources
        and all(
            receipt["source_identity"][name] == digest(checked_file(root, name)) for name in sources
        ),
        "Gemini 3.8 canary source identity changed",
    )
    response_path = root / prefix / "RESPONSE.json"
    observation = None
    if receipt["status"] == "response_recorded":
        raw = json.loads(checked_file(root, f"{prefix}/RESPONSE.json").read_text())
        require(
            receipt["response_sha256"] == digest(response_path),
            "Gemini 3.8 canary raw response hash changed",
        )
        observation = module.response_observation(raw, request, probe.CONFIG)
        usage = module.usage_receipt(raw, request, probe.CONFIG)
        qualified = (
            observation["status"] == "completed"
            and observation["judgment"]["winner"] == "tie"
            and usage["status"] == "REPORTED_BY_API"
            and not usage.get("bound_exceeded", False)
        )
        require(
            receipt["observation"] == observation
            and receipt["usage_receipt"] == usage
            and receipt["qualification_passed"] is qualified,
            "Gemini 3.8 canary qualification does not reconstruct",
        )
    else:
        require(
            receipt["status"]
            in {
                "not_dispatched",
                "reserved_pending",
                "http_error_no_retry",
                "canary_failure_no_retry",
            }
            and receipt["qualification_passed"] is False
            and receipt.get("observation") is None
            and receipt.get("usage_receipt") is None,
            "Unresolved Gemini 3.8 canary was promoted to qualified",
        )
        qualified = False
    return {
        "status": receipt["status"],
        "qualification_passed": qualified,
        "study_judgment": False,
        "requested_model": module.MODEL,
        "returned_model": observation["response_model"] if observation else None,
        "observation_status": observation["status"] if observation else None,
        "response_file_present": response_path.exists(),
        "request_sha256": digest(path),
    }


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
    import diagnose_v14_mistral_budget as budget_diagnostic

    root = Path(root).resolve()
    bundle = root / BUNDLE
    original_canaries = verify_original_canaries(root)
    gemini38_canary = verify_gemini38_canary(root)
    summary = aggregator.aggregate(root)
    if summary["providers"]["gemini"]["reserved_requests"]:
        require(
            gemini38_canary["qualification_passed"],
            "Gemini study requests exist without a qualified prospective canary",
        )
    require(
        json.loads((bundle / "diagnostics/MISTRAL_OUTPUT_BUDGET.json").read_text())
        == budget_diagnostic.reconstruct(root),
        "Mistral output-budget diagnostic does not reconstruct",
    )
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
        "original_canary_qualifications_recomputed": original_canaries,
        "gemini38_canary_qualification_recomputed": gemini38_canary,
        "mistral_budget_diagnostic_recomputed": True,
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
