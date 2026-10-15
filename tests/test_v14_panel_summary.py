"""Offline mocked receipts only: no provider keys, network, or model execution."""

import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import summarize_v14_judge_panel as summary  # noqa: E402
from test_v14_judge_panel import frozen_plan as runner_fixture  # noqa: E402
from test_v14_judge_panel import response  # noqa: E402


def save(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


@pytest.fixture
def panel(tmp_path, monkeypatch):
    path, plan, root = runner_fixture.__wrapped__(tmp_path, monkeypatch)
    dataset = json.loads((ROOT / "data/v14_judge_panel/selection.json").read_text())
    save(root / "selection.json", dataset)
    plan["dataset"]["sha256"] = summary.runner.prior.file_sha(root / "selection.json")
    save(path, plan)
    monkeypatch.setattr(summary.selection, "build", lambda: copy.deepcopy(dataset))
    monkeypatch.setattr(summary.runner, "dispatch", lambda *_: pytest.fail("Unexpected API"))
    return path, plan, root, dataset


def cell(
    panel,
    provider="openai",
    replicate=0,
    *,
    normalized="workspace",
    invalid=False,
    conflict=False,
    dry=False,
    pending=False,
    wrong_model=False,
):
    plan_path, plan, root, _ = panel
    config, dataset_path, pairs, cases = summary.runner.validate_plan(plan, provider, replicate)
    requests = summary.runner.prepare_requests(plan, provider, replicate, config, pairs, cases)
    snap = summary.snapshot(plan_path, provider, replicate, config, dataset_path, pairs, requests)
    output = root / "cells" / provider / f"r{replicate}"
    output.mkdir(parents=True)
    save(output / "SNAPSHOT.json", snap)
    save(output / "PAIRS.json", {"pairs": pairs})
    save(output / "PREPARED_REQUESTS.json", {"requests": requests})
    if dry:
        return output
    receipts = []
    for index, request in enumerate(requests):
        receipt = {**request, "reserved_at": "2026-10-09T00:00:00Z", "status": "reserved_pending"}
        if not pending:
            if request["calibration_only"]:
                winner = "tie"
            elif conflict:
                winner = "A"
            elif normalized in ("tie", "uncertain"):
                winner = normalized
            else:
                base = "A" if request["order"] == "AB" else "B"
                winner = base if normalized == "base" else ({"A", "B"} - {base}).pop()
            raw = response(provider, request["body"], winner=winner, wrapped=invalid and index == 0)
            if wrong_model:
                raw["model"] = "not-the-frozen-model"
            response_path = output / "responses" / (request["request_id"] + ".json")
            save(response_path, raw)
            receipt.update(
                status="response_recorded",
                response_sha256=summary.runner.prior.file_sha(response_path),
                observation=summary.runner.response_observation(raw, request, config),
                usage_receipt=summary.runner.usage_receipt(raw, request, config),
            )
        save(output / "requests" / (request["request_id"] + ".json"), receipt)
        receipts.append(receipt)
        if pending:
            break
    report = summary.runner.summarize(pairs, receipts, snap)
    report["stopped_on_contract_or_transport_failure"] = pending or wrong_model
    save(output / "SUMMARY.json", report)
    return output


def note(panel, provider="mistral"):
    path = panel[2] / "EXECUTION_NOTE.json"
    save(
        path,
        {
            "format": "latent-workspace-v14-judge-panel-execution-note-v1",
            "providers": {
                provider: {
                    "status": "credential_unavailable",
                    "planned_requests": 140,
                    "dispatched_requests": 0,
                },
            },
        },
    )
    return path


def test_five_openai_repeats_missing_mistral_are_separate_and_not_majority_gold(panel):
    for replicate in range(5):
        cell(panel, replicate=replicate)
    result = summary.aggregate(panel[0], panel[2] / "cells", note(panel))
    assert result["status"] == "VERIFIED_PARTIAL_RECEIPTS_NOT_GOLD"
    assert result["planned_requests"] == 280
    assert result["selection_counts"]["changed_world_task_clusters"] == 6
    openai, mistral = result["providers"]["openai"], result["providers"]["mistral"]
    assert openai["valid_judgments"] == openai["reserved_requests"] == 140
    assert openai["all_five_cells_receipt_closed"] is True
    assert openai["observed_model_contract_satisfied"] is True
    assert openai["usage"]["reported_total_tokens"] == 42000
    assert openai["usage"]["actual_billed_cost_usd"] is None
    assert mistral["not_dispatched_requests"] == 140 and mistral["valid_judgments"] == 0
    assert mistral["execution_note_status"] == "credential_unavailable"
    assert mistral["observed_model_contract_satisfied"] is None
    for pair in result["pairs"]:
        expected = "tie" if pair["calibration_only"] else "workspace"
        assert pair["providers"]["openai"]["stable_all_five_preference"] == expected
        assert pair["providers"]["mistral"]["stable_all_five_preference"] is None
        assert all(row["agree"] is None for row in pair["cross_provider_within_replicate"])
    assert result["pooled_provider_winner"] is None and result["winner"] == "none"
    review = summary.render_review(result)
    assert "一部未実行・欠損あり" in review and "14対の早見表" in review
    assert "| case / regime |" in review and "not_dispatched" in review
    assert "| general-01-summary / greedy |" in review
    assert "観察であり確定ではない。" in review
    assert "全監査フィールド" in review


def test_complete_providers_can_disagree_without_pooled_winner(panel):
    for replicate in range(5):
        cell(panel, "openai", replicate, normalized="workspace")
        cell(panel, "mistral", replicate, normalized="base")
    result = summary.aggregate(panel[0], panel[2] / "cells")
    assert result["status"] == "VERIFIED_COMPLETE_RECEIPTS_NOT_GOLD"
    for pair in result["pairs"]:
        assert all(
            row["both_models_valid_order_consistent"]
            for row in pair["cross_provider_within_replicate"]
        )
        assert all(
            row["agree"] is pair["calibration_only"]
            for row in pair["cross_provider_within_replicate"]
        )
    assert result["pooled_provider_winner"] is None


def test_invalid_quotes_and_order_conflicts_remain_visible(panel):
    cell(panel, replicate=0, invalid=True)
    cell(panel, replicate=1, conflict=True)
    result = summary.aggregate(panel[0], panel[2] / "cells")
    assert result["providers"]["openai"]["observation_status_counts"]["invalid_judgment"] == 1
    assert result["providers"]["openai"]["valid_judgments"] == 55
    first = result["pairs"][0]["providers"]["openai"]
    assert first["replicates"][0]["judge_status"] == "missing_or_invalid_order"
    assert first["replicates"][1]["judge_status"] == "order_conflict"
    assert first["replicates"][1]["order_consistent_preference"] is None
    assert first["stable_all_five_preference"] is None
    assert "invalid/missing" in summary.render_review(result)
    assert "conflict" in summary.render_review(result)


def test_dry_missing_pending_and_identity_failure_do_not_become_success(panel):
    cell(panel, "mistral", 0, dry=True)
    cell(panel, "openai", 0, pending=True)
    cell(panel, "openai", 1, wrong_model=True)
    result = summary.aggregate(panel[0], panel[2] / "cells", note(panel))
    assert result["providers"]["mistral"]["reserved_requests"] == 0
    assert result["providers"]["mistral"]["cells"][0]["prepared_artifacts_present"] is True
    openai = result["providers"]["openai"]
    assert openai["reserved_requests"] == 29 and openai["durable_responses"] == 28
    assert openai["valid_judgments"] == 0 and openai["observed_model_contract_satisfied"] is False
    assert openai["cells"][0]["status"] == "INCOMPLETE_RECEIPTS"
    assert openai["cells"][1]["status"] == "VERIFIED_RECEIPT_CLOSURE"
    assert not openai["all_five_cells_receipt_closed"]


def test_pending_durable_body_is_preserved_but_not_recovered_offline(panel):
    output = cell(panel, pending=True)
    request = json.loads((output / "PREPARED_REQUESTS.json").read_text())["requests"][0]
    path = output / "responses" / (request["request_id"] + ".json")
    save(path, response("openai", request["body"]))
    before = {path: path.read_bytes() for path in output.rglob("*") if path.is_file()}
    verified = summary.verify_cell(panel[0], "openai", 0, output)
    assert verified["status"] == "INCOMPLETE_RECEIPTS"
    assert verified["durable_responses"] == 1
    observation = verified["observations"][request["request_id"]]
    assert observation["judgment"] is None and observation["status"] == "reserved_pending"
    assert observation["raw_response_sha256"] == summary.runner.prior.file_sha(path)
    aggregate = summary.aggregate(panel[0], panel[2] / "cells")
    assert aggregate["providers"]["openai"]["observed_model_contract_satisfied"] is None
    assert before == {path: path.read_bytes() for path in output.rglob("*") if path.is_file()}


@pytest.mark.parametrize(
    "mutation",
    [
        "snapshot",
        "prepared",
        "pairs",
        "raw_hash",
        "observation",
        "usage",
        "summary",
        "stop_flag",
        "unreserved_response",
        "duplicate_request",
        "missing_response",
    ],
)
def test_tampering_is_rejected_offline(panel, mutation):
    output = cell(panel)
    if mutation in ("snapshot", "prepared", "pairs", "summary"):
        filename = {
            "snapshot": "SNAPSHOT.json",
            "prepared": "PREPARED_REQUESTS.json",
            "pairs": "PAIRS.json",
            "summary": "SUMMARY.json",
        }[mutation]
        path = output / filename
        value = json.loads(path.read_text())
        value["tampered"] = True
        save(path, value)
    elif mutation == "raw_hash":
        path = next((output / "responses").iterdir())
        path.write_text(path.read_text() + " ")
    elif mutation == "missing_response":
        next((output / "responses").iterdir()).unlink()
    elif mutation in ("unreserved_response", "duplicate_request"):
        folder = "responses" if mutation == "unreserved_response" else "requests"
        save(output / folder / "unexpected.json", {})
    elif mutation == "stop_flag":
        path = output / "SUMMARY.json"
        value = json.loads(path.read_text())
        value["stopped_on_contract_or_transport_failure"] = True
        save(path, value)
    else:
        path = next((output / "requests").iterdir())
        value = json.loads(path.read_text())
        if mutation == "observation":
            value["observation"]["judgment"]["winner"] = "uncertain"
        else:
            value["usage_receipt"]["total_tokens"] += 1
        save(path, value)
    with pytest.raises(ValueError):
        summary.verify_cell(panel[0], "openai", 0, output)


@pytest.mark.parametrize("destination", ["openai/r00", "openai/r1", "mistral/r0"])
def test_duplicate_cells_and_cross_provider_receipts_are_rejected(panel, destination):
    source = cell(panel)
    shutil.copytree(source, panel[2] / "cells" / destination)
    with pytest.raises(ValueError):
        summary.aggregate(panel[0], panel[2] / "cells")


def test_missing_credentials_are_not_inferred_and_note_cannot_contradict_reservations(panel):
    result = summary.aggregate(panel[0], panel[2] / "absent")
    assert result["providers"]["mistral"]["execution_note_status"] == "not_supplied"
    cell(panel, "mistral")
    with pytest.raises(ValueError, match="contradicts request reservations"):
        summary.aggregate(panel[0], panel[2] / "cells", note(panel))


def test_stability_needs_all_five_without_replacing_uncertainty_by_a_winner():
    def row(preference, status="order_consistent"):
        return {"judge_status": status, "order_consistent_preference": preference}

    assert (
        summary.describe_repeats([row("uncertain") for _ in range(5)])["stable_all_five_preference"]
        == "uncertain"
    )
    varying = summary.describe_repeats([row("workspace") for _ in range(4)] + [row("base")])
    assert varying["stability_status"] == "VARIES_ACROSS_REPLICATES"
    assert varying["stable_all_five_preference"] is None
    partial = summary.describe_repeats(
        [row("workspace") for _ in range(4)] + [row(None, "missing_or_invalid_order")]
    )
    assert partial["stable_all_five_preference"] is None


def test_output_is_exclusive_and_model_prose_is_escaped(panel):
    result = summary.prepare(panel[0], panel[2] / "absent", panel[2] / "report", note(panel))
    text = panel[2] / "report" / "PANEL_REVIEW.md"
    text.write_text(text.read_text() + "human annotation\n")
    before = text.read_bytes()
    with pytest.raises(FileExistsError):
        summary.prepare(panel[0], panel[2] / "absent", panel[2] / "report", note(panel))
    assert text.read_bytes() == before
    result["pairs"][0]["base_answer"] = '</pre><script>bad("x")</script>'
    rendered = summary.render_review(result)
    assert "<script>" not in rendered and "&lt;script&gt;bad(&quot;x&quot;)" in rendered


def test_posthoc_word_counts_cover_all_applicable_selected_pairs_without_japanese_claims(panel):
    result = summary.aggregate(panel[0], panel[2] / "absent")
    applicable = [
        pair
        for pair in result["pairs"]
        if pair["constraint_checks"]["applicability"] == "applicable_english_word_limit"
    ]
    assert len(applicable) == 10
    assert len(result["pairs"]) - len(applicable) == 4
    for pair in result["pairs"]:
        check = pair["constraint_checks"]
        assert check["status"] == "POSTHOC_MECHANICAL_DESCRIPTIVE"
        assert check["preregistered_judge_outcome"] is False
        if pair in applicable:
            assert check["word_limit"] == (
                30
                if pair["lane"] == "relation"
                else {
                    "general-01-summary": 55,
                    "general-05-causal": 60,
                }[pair["case_id"]]
            )
            for side in ("base", "workspace"):
                count = len(pair[side + "_answer"].split())
                assert check[side]["whitespace_word_count"] == count
                assert check[side]["exceeds_limit"] is (count > check["word_limit"])
        else:
            assert check["applicability"] == "not_applicable" and check["word_limit"] is None
            assert (
                check["base"]
                == check["workspace"]
                == {
                    "whitespace_word_count": None,
                    "exceeds_limit": None,
                }
            )
        assert pair["providers"]["openai"]["stable_all_five_preference"] is None
    indexed = {
        (pair["case_id"], pair["regime"]): pair["constraint_checks"] for pair in result["pairs"]
    }
    first = indexed["relation-01-forward", "sample212"]
    assert (
        first["base"]["whitespace_word_count"],
        first["workspace"]["whitespace_word_count"],
    ) == (33, 30)
    assert first["base"]["exceeds_limit"] is True and first["workspace"]["exceeds_limit"] is False
    second = indexed["relation-03-forward", "sample211"]
    assert (
        second["base"]["whitespace_word_count"],
        second["workspace"]["whitespace_word_count"],
    ) == (29, 32)
    assert second["base"]["exceeds_limit"] is False and second["workspace"]["exceeds_limit"] is True
    rendered = summary.render_review(result)
    assert rendered.count("POSTHOC_MECHANICAL_DESCRIPTIVE") == 14
    assert "事後の機械的な語数確認" in rendered
