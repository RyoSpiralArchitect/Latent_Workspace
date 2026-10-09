"""Offline cell reconstruction plus mocked cross-provider accounting tests."""

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import run_v14_gemini38_panel as gemini  # noqa: E402
import run_v14_mistral_extension as mistral  # noqa: E402
import summarize_v14_judge_extension as summary  # noqa: E402
from test_v14_gemini38_panel import frozen_plan as gemini_fixture  # noqa: E402
from test_v14_gemini38_panel import response as gemini_response  # noqa: E402
from test_v14_mistral_extension import frozen_plan as mistral_fixture  # noqa: E402
from test_v14_mistral_extension import parent_plan as mistral_parent_fixture  # noqa: E402
from test_v14_mistral_extension import response as mistral_response  # noqa: E402
from test_v14_panel_summary import cell, save  # noqa: E402
from test_v14_panel_summary import panel as panel_fixture  # noqa: E402


@pytest.fixture
def panel(tmp_path, monkeypatch):
    return panel_fixture.__wrapped__(tmp_path, monkeypatch)


def test_generic_original_cell_is_exactly_equal_to_frozen_verifier(panel):
    directory = cell(panel, "mistral", 0)
    actual = summary.verify_cell(summary.original_runner, panel[0], "mistral", 0, directory)
    expected = summary.original.verify_cell(panel[0], "mistral", 0, directory)
    assert actual == expected


@pytest.mark.parametrize("mutation", ["raw", "request", "summary", "unreserved", "snapshot"])
def test_generic_cell_reconstruction_rejects_tampering(panel, mutation):
    directory = cell(panel)
    if mutation == "raw":
        path = next((directory / "responses").iterdir())
        path.write_text(path.read_text() + " ")
    elif mutation == "unreserved":
        save(directory / "responses/unknown.json", {})
    else:
        path = (
            next((directory / "requests").iterdir())
            if mutation == "request"
            else (directory / ("SUMMARY.json" if mutation == "summary" else "SNAPSHOT.json"))
        )
        value = json.loads(path.read_text())
        if mutation == "request":
            value["order"] = "BA" if value["order"] == "AB" else "AB"
        else:
            value["changed"] = True
        save(path, value)
    with pytest.raises(ValueError):
        summary.verify_cell(summary.original_runner, panel[0], "openai", 0, directory)


def test_pending_cell_is_not_reconciled_or_counted_as_valid(panel):
    directory = cell(panel, pending=True)
    before = {p: p.read_bytes() for p in directory.rglob("*") if p.is_file()}
    result = summary.verify_cell(summary.original_runner, panel[0], "openai", 0, directory)
    assert result["status"] == "INCOMPLETE_RECEIPTS"
    assert result["reserved_requests"] == 1 and result["not_dispatched_requests"] == 27
    assert len(result["unresolved_request_ids"]) == 1
    assert before == {p: p.read_bytes() for p in directory.rglob("*") if p.is_file()}


@pytest.mark.parametrize("outcome", ["valid", "invalid_quote", "wrong_model", "pending"])
def test_gemini_cell_reconstruction_uses_raw_provider_contract(tmp_path, monkeypatch, outcome):
    plan_path, _, root = gemini_fixture.__wrapped__(tmp_path, monkeypatch)
    monkeypatch.setitem(gemini.os.environ, "GEMINI_API_KEY", "unit-test-dummy")

    def transport(provider, body, key):
        assert provider == "gemini" and key == "unit-test-dummy"
        if outcome == "pending":
            raise TimeoutError("Mock transport ambiguity")
        raw = gemini_response(body, wrapped=outcome == "invalid_quote")
        if outcome == "wrong_model":
            raw["modelVersion"] = "another-model"
        return raw

    directory = root / "cells/gemini/r0"
    gemini.execute(plan_path, "gemini", 0, directory, execute_api=True, transport=transport)
    rebuilt = summary.verify_cell(gemini, plan_path, "gemini", 0, directory)
    if outcome == "valid":
        assert rebuilt["status"] == "VERIFIED_RECEIPT_CLOSURE"
        assert all(row["status"] == "completed" for row in rebuilt["observations"].values())
        assert rebuilt["summary"]["usage"]["reported_output_tokens"] == 28 * 250
    elif outcome == "invalid_quote":
        assert rebuilt["status"] == "VERIFIED_RECEIPT_CLOSURE"
        assert all(row["status"] == "invalid_judgment" for row in rebuilt["observations"].values())
    else:
        assert rebuilt["status"] == "INCOMPLETE_RECEIPTS"
        assert rebuilt["reserved_requests"] == 1
        assert rebuilt["not_dispatched_requests"] == 27


@pytest.mark.parametrize("outcome", ["valid", "invalid_quote", "unknown_chunk"])
def test_mistral_chunked_cell_reconstruction_preserves_raw_envelope(tmp_path, monkeypatch, outcome):
    parent = mistral_parent_fixture.__wrapped__(tmp_path, monkeypatch)
    plan_path, _, root = mistral_fixture.__wrapped__(parent, monkeypatch)
    monkeypatch.setitem(mistral.os.environ, "MISTRAL_API_KEY", "unit-test-dummy")

    def transport(provider, body, key):
        assert provider == "mistral" and key == "unit-test-dummy"
        raw = mistral_response(provider, body, wrapped=outcome == "invalid_quote")
        if outcome == "unknown_chunk":
            raw["choices"][0]["message"]["content"].append({"type": "unknown"})
        return raw

    directory = root / "cells/mistral/r0"
    mistral.execute(plan_path, "mistral", 0, directory, execute_api=True, transport=transport)
    before = {path: path.read_bytes() for path in directory.rglob("*") if path.is_file()}
    rebuilt = summary.verify_cell(mistral, plan_path, "mistral", 0, directory)
    assert rebuilt["status"] == "VERIFIED_RECEIPT_CLOSURE"
    expected = "completed" if outcome == "valid" else "invalid_judgment"
    assert all(row["status"] == expected for row in rebuilt["observations"].values())
    assert "SYNTHETIC_THINKING_NOT_A_VERDICT" not in json.dumps(rebuilt["observations"])
    assert before == {path: path.read_bytes() for path in directory.rglob("*") if path.is_file()}


@pytest.fixture
def extension(tmp_path, monkeypatch):
    dataset = json.loads((ROOT / "data/v14_judge_panel/selection.json").read_text())
    dataset_path = tmp_path / "selection.json"
    save(dataset_path, dataset)
    pairs = dataset["pairs"]
    cases = {case["id"]: case for case in dataset["cases"]}

    def validate(*args):
        return {}, dataset_path, copy.deepcopy(pairs), copy.deepcopy(cases)

    monkeypatch.setattr(summary.original_runner, "validate_plan", validate)
    monkeypatch.setattr(gemini, "validate_plan", validate)
    monkeypatch.setattr(mistral, "validate_plan", validate)
    monkeypatch.setattr(summary.selection, "build", lambda _: copy.deepcopy(dataset))
    monkeypatch.setattr(
        summary.original_seal, "verify", lambda _: {"status": "PASS_ARTIFACT_INTEGRITY_ONLY"}
    )
    for name in (
        summary.ORIGINAL_PLAN,
        summary.BLOCKED_GEMINI_PLAN,
        summary.MISTRAL_PLAN,
        summary.GEMINI_PLAN,
        f"{summary.ORIGINAL_BUNDLE}/INDEX.json",
        f"{summary.ORIGINAL_BUNDLE}/VALIDATION.json",
    ):
        save(tmp_path / name, {})
    save(
        tmp_path / summary.BUNDLE / "EXECUTION_NOTE.json",
        {
            "format": "latent-workspace-v14-judge-extension-execution-note-v1",
            "providers": {},
        },
    )
    settings = {
        provider: {"present": True, "preference": "workspace"} for provider in summary.PROVIDERS
    }

    def fake_cell(module, plan_path, provider, replicate, directory):
        """Accounting fixture; not presented as an API/receipt verification test."""
        config = settings[provider]
        present = config["present"]
        observations, pair_rows = {}, []
        for index, pair in enumerate(pairs):
            preference = "tie" if pair["calibration_only"] else config["preference"]
            status = "order_consistent" if present else "missing_or_invalid_order"
            if config.get("conflict") and index == 0 and replicate == 0:
                preference, status = None, "order_conflict"
            pair_rows.append(
                {
                    **pair,
                    "judge_status": status,
                    "order_consistent_preference": preference if present else None,
                }
            )
            for order in ("AB", "BA"):
                observations[f"{provider}-r{replicate}-{pair['pair_id']}-{order}"] = {
                    "status": "completed" if present else "not_dispatched",
                    "normalized_preference": preference if present else None,
                    "judgment": {"rationale_ja": "Mocked only"} if present else None,
                }
        count = 28 if present else 0
        usage = {
            "reserved_calls": count,
            "calls_with_reported_usage": count,
            "calls_without_reported_usage": 0,
            "reported_input_tokens": count * 10,
            "reported_output_tokens": count * 20,
            "reported_total_tokens": count * 30,
            "usage_bound_exceeded_calls": 0,
            "reported_usage_undiscounted_cost_usd": "0.01",
            "reserved_cost_upper_bound_usd": "1",
        }
        return {
            "provider": provider,
            "replicate": replicate,
            "directory": str(directory),
            "status": "VERIFIED_RECEIPT_CLOSURE" if present else "NOT_DISPATCHED",
            "planned_requests": 28,
            "reserved_requests": count,
            "durable_responses": count,
            "not_dispatched_requests": 28 - count,
            "unresolved_request_ids": [],
            "summary": {
                "pairs": pair_rows,
                "usage": usage,
                "receipt_status_counts": {"response_recorded": count},
            },
            "observations": observations,
        }

    monkeypatch.setattr(summary, "verify_cell", fake_cell)
    return tmp_path, settings


def test_complete_three_provider_accounting_is_not_majority_gold(extension):
    root, settings = extension
    settings["mistral"]["preference"] = "base"
    result = summary.aggregate(root)
    assert result["status"] == "VERIFIED_COMPLETE_RECEIPTS_NOT_GOLD"
    assert result["planned_requests"] == 420 and result["newly_planned_requests"] == 280
    assert result["reused_openai_requests"] == 140
    assert result["providers"]["openai"]["evidence_origin"].startswith("original_sealed")
    assert all(provider["valid_judgments"] == 140 for provider in result["providers"].values())
    assert result["winner"] == "none" and result["pooled_provider_winner"] is None
    for pair in result["pairs"]:
        assert all(
            row["all_three_models_valid_order_consistent"]
            for row in pair["cross_provider_within_replicate"]
        )
        assert all(
            row["all_three_agree"] is pair["calibration_only"]
            for row in pair["cross_provider_within_replicate"]
        )
    review = summary.render_review(result)
    assert "gemini r0→r4" in review and "mistral r0→r4" in review
    assert "Mocked only" in review and "general-01-summary / greedy" in review


def test_missing_provider_and_order_conflicts_remain_separate(extension):
    root, settings = extension
    settings["gemini"]["present"] = False
    settings["mistral"]["conflict"] = True
    result = summary.aggregate(root)
    assert result["status"] == "VERIFIED_PARTIAL_RECEIPTS_NOT_GOLD"
    assert result["providers"]["gemini"]["not_dispatched_requests"] == 140
    assert result["providers"]["gemini"]["observed_model_contract_satisfied"] is None
    first = result["pairs"][0]
    assert first["providers"]["mistral"]["order_conflicting_replicates"] == 1
    assert first["providers"]["mistral"]["stable_all_five_preference"] is None
    assert first["cross_provider_within_replicate"][0]["all_three_agree"] is None
    assert "conflict" in summary.render_review(result)


def test_requested_model_mismatch_canary_cannot_count_as_gemini_judgment(extension):
    root, settings = extension
    settings["gemini"]["present"] = False
    save(
        root / summary.BUNDLE / "EXECUTION_NOTE.json",
        {
            "format": "latent-workspace-v14-judge-extension-execution-note-v1",
            "providers": {
                "gemini": {
                    "status": "blocked_requested_model_mismatch",
                    "planned_requests": 140,
                    "dispatched_requests": 0,
                }
            },
        },
    )
    save(
        root / summary.BUNDLE / "preflight/gemini/RESPONSE.json",
        {
            "modelVersion": "a-different-model",
            "canary": "Not a study response",
        },
    )
    result = summary.aggregate(root)
    report = result["providers"]["gemini"]
    assert result["planned_requests"] == 420
    assert result["status"] == "VERIFIED_PARTIAL_RECEIPTS_NOT_GOLD"
    assert report["execution_note_status"] == "blocked_requested_model_mismatch"
    assert report["valid_judgments"] == 0 and report["not_dispatched_requests"] == 140


@pytest.mark.parametrize("path", ["openai/r0", "unknown/r0", "gemini/r5", "mistral/r00"])
def test_extension_never_accepts_copied_openai_or_extra_cells(extension, path):
    root, _ = extension
    (root / summary.BUNDLE / "cells" / path).mkdir(parents=True)
    with pytest.raises(ValueError):
        summary.aggregate(root)


def test_note_cannot_hide_calls_and_original_integrity_failure_propagates(extension, monkeypatch):
    root, _ = extension
    note = root / summary.BUNDLE / "EXECUTION_NOTE.json"
    save(
        note,
        {
            "format": "latent-workspace-v14-judge-extension-execution-note-v1",
            "providers": {"mistral": {"status": "credential_unavailable"}},
        },
    )
    with pytest.raises(ValueError, match="contradicts"):
        summary.aggregate(root)

    def fail(_):
        raise ValueError("Original seal changed")

    monkeypatch.setattr(summary.original_seal, "verify", fail)
    with pytest.raises(ValueError, match="Original seal"):
        summary.aggregate(root)


@pytest.mark.parametrize("provider", ["gemini", "mistral"])
def test_provider_mismatched_pairs_are_rejected(extension, monkeypatch, provider):
    root, _ = extension
    module = gemini if provider == "gemini" else mistral
    original = module.validate_plan

    def different(*args):
        config, path, pairs, cases = original(*args)
        pairs[0]["base_answer"] += "changed"
        return config, path, pairs, cases

    monkeypatch.setattr(module, "validate_plan", different)
    with pytest.raises(ValueError, match="identical cases"):
        summary.aggregate(root)


def test_output_is_exclusive(extension):
    root, _ = extension
    summary.prepare(root)
    with pytest.raises(FileExistsError):
        summary.prepare(root)
