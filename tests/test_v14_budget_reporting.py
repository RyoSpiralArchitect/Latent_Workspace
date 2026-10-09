import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import seal_v14_budget_panel as seal  # noqa: E402
import summarize_v14_budget_panel as report  # noqa: E402
from test_v14_budget_panel import frozen, response  # noqa: E402, F401
from test_v14_judge_panel import frozen_plan as parent_plan  # noqa: E402, F401


@pytest.fixture
def published(frozen, monkeypatch):  # noqa: F811
    path, plan, provider, root = frozen
    if provider != "mistral":
        pytest.skip("Claude was skipped by the user; no Claude study report")
    plan["method_id"] = "mistral_cap16384"
    report.run.prior.write_json(path, plan)
    for r in range(5):
        output = root / report.BUNDLE / "cells" / plan["method_id"] / f"r{r}"
        report.run.execute(
            path, provider, r, output, execute_api=True, transport=lambda p, b, k: response(p, b)
        )
    dataset = report.run.prior.load_json(root / plan["dataset"]["path"])
    pairs = []
    for pair in dataset["pairs"]:
        stable = report.original.describe_repeats(
            [
                {
                    "replicate": r,
                    "judge_status": "order_consistent",
                    "order_consistent_preference": "tie",
                    "orders": {},
                }
                for r in range(5)
            ]
        )
        pairs.append(
            {
                **pair,
                "world_task_cluster": [pair["case_id"]],
                "providers": {p: copy.deepcopy(stable) for p in ("openai", "gemini", "mistral")},
            }
        )
    old_dir = root / report.previous.BUNDLE
    report.run.prior.write_json(old_dir / "INDEX.json", {"test_only": True})
    old = {
        "providers": {
            p: {"reserved_requests": n}
            for p, n in (("openai", 140), ("gemini", 140), ("mistral", 93))
        },
        "pairs": pairs,
        "selection_counts": {"pairs": 14},
    }
    report.run.prior.write_json(old_dir / "analysis/SUMMARY.json", old)
    monkeypatch.setattr(report.previous_seal, "verify", lambda _: {"status": "MOCK_OLD_SEAL"})
    result = report.publish(path, root=root)
    bundle = root / report.BUNDLE
    for name in ("README.md", "PROTOCOL.md", "SCOPE_UPDATE.md"):
        (bundle / name).write_text("Test-only fixture; never real evidence.\n")
    for name in seal.EXPLICIT:
        target = root / name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
    report.run.prior.write_json(
        bundle / "EXECUTION_NOTE.json",
        {
            "mistral": {
                k: result["providers"]["mistral_enlarged"][k]
                for k in (
                    "planned_requests",
                    "reserved_requests",
                    "durable_responses",
                    "valid_judgments",
                )
            },
            "claude_study_requests": 0,
            "new_training_or_generation": False,
        },
    )
    folder = bundle / "metadata/mistral"
    report.run.prior.write_json(folder / "RESPONSE.json", {"id": "mistral-large-4"})
    report.run.prior.write_json(
        folder / "REQUEST.json",
        {
            "provider": "mistral",
            "study_judgment": False,
            "status": "response_recorded",
            "requested_model": "mistral-large-4",
            "returned_model": "mistral-large-4",
            "response_sha256": report.run.prior.file_sha(folder / "RESPONSE.json"),
        },
    )
    report.run.prior.write_json(
        bundle / "metadata/anthropic/REQUEST.json",
        {
            "provider": "anthropic",
            "study_judgment": False,
            "status": "http_error_no_retry",
            "requested_model": "claude-sonnet-5",
            "http_status": 401,
        },
    )
    return root, path, result


def test_separate_methods_stable_counts_and_idempotent_verification(published):
    root, path, result = published
    assert result["newly_planned_requests"] == 140
    assert result["historical_reserved_requests"] == 373
    assert set(result["providers"]) == set(report.METHODS)
    fresh = result["providers"]["mistral_enlarged"]
    assert fresh["valid_judgments"] == 140
    assert fresh["changed_stable_counts"]["tie"] == 10
    assert fresh["control_stable_ties"] == 4
    assert result["winner"] == "none" and result["pooled_provider_winner"] is None
    assert seal.seal(root, path)["status"] == "SEALED_INTEGRITY_ONLY"
    receipt = seal.verify(root, path, write_receipt=True)
    assert receipt["raw_summary_reader_reconstructed"]
    assert seal.verify(root, path) == receipt
    with pytest.raises(FileExistsError):
        report.publish(path, root=root)


@pytest.mark.parametrize("target", ["summary", "reader", "raw", "extra"])
def test_seal_detects_tampering_and_extra_files(published, target):
    root, path, _ = published
    seal.seal(root, path)
    bundle = root / report.BUNDLE
    if target == "summary":
        p = bundle / "analysis/SUMMARY.json"
        data = json.loads(p.read_text())
        data["winner"] = "workspace"
        p.write_text(json.dumps(data))
    elif target == "reader":
        p = bundle / "analysis/PANEL_REVIEW.md"
        p.write_text(p.read_text() + "tampered")
    elif target == "raw":
        p = next((bundle / "cells/mistral_cap16384/r0/responses").glob("*.json"))
        p.write_text("{}")
    else:
        (bundle / "extra.json").write_text("{}")
    with pytest.raises(ValueError):
        seal.verify(root, path)


def test_payload_reconstruction_catches_wrong_prose_counts(published):
    root, path, _ = published
    p = root / report.BUNDLE / "EXECUTION_NOTE.json"
    note = json.loads(p.read_text())
    note["mistral"]["valid_judgments"] = 139
    p.write_text(json.dumps(note))
    with pytest.raises(ValueError, match="count differs"):
        seal.verify_payloads(root, path)
