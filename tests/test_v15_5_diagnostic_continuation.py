from __future__ import annotations

import copy
import json
import sys
import threading
import time
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import continue_v15_5_diagnostic_judge as c
import run_v15_5_diagnostic_judge as old
import v15_5_diagnostics as d


@pytest.fixture(scope="module")
def original():
    plan, data, _ = old.load_frozen()
    selected, rows, summary, ledger = c.verify_original(plan, data)
    return plan, data, selected, rows, summary, ledger


def not_dispatched(selected):
    return [
        {**{k: r[k] for k in ("request_id", "item_id", "replicate")}, "status": "not_dispatched"}
        for r in selected
    ]


def test_exact_never_dispatched_inventory(original):
    plan, data, selected, rows, _summary, _ledger = original
    requests = d.requests_for(data, plan, "mistral", "study")
    assert c.select_never_dispatched(requests, rows) == selected
    assert len(selected) == 320
    assert len({r["request_id"] for r in selected}) == 320
    reserved = {r["request_id"] for r in rows if r["status"] != "not_dispatched"}
    assert not ({r["request_id"] for r in selected} & reserved)
    assert all(
        (r["provider"], r["phase"], r["replicate"]) == ("mistral", "study", 0) for r in selected
    )
    assert all(
        r["body"]["random_seed"] == 15501 and r["body"]["max_tokens"] == 16384 for r in selected
    )
    assert Counter(r["status"] for r in rows) == c.BASELINE_COUNTS


@pytest.mark.parametrize("mutation", ["pending", "unknown", "invalid", "reorder", "duplicate"])
def test_changed_baseline_is_not_new_authority(original, mutation):
    plan, data, _selected, rows, _summary, _ledger = original
    changed = copy.deepcopy(rows)
    if mutation in ("pending", "unknown", "invalid"):
        row = next(r for r in changed if r["status"] == "not_dispatched")
        row["status"] = {
            "pending": "reserved_pending_unknown",
            "unknown": "transport_or_recording_ambiguous_no_retry",
            "invalid": "invalid_judgment",
        }[mutation]
    elif mutation == "reorder":
        changed.reverse()
    else:
        changed[-1] = changed[-2]
    with pytest.raises(ValueError):
        c.select_never_dispatched(d.requests_for(data, plan, "mistral", "study"), changed)


@pytest.mark.parametrize("mutation", ["provider", "phase", "replicate"])
def test_selection_cannot_expand_to_other_cells(original, mutation):
    plan, data, selected, rows, _summary, _ledger = original
    requests = copy.deepcopy(d.requests_for(data, plan, "mistral", "study"))
    item = next(r for r in requests if r["request_id"] == selected[0]["request_id"])
    item[mutation] = {"provider": "openai", "phase": "calibration", "replicate": 1}[mutation]
    with pytest.raises(ValueError):
        c.select_never_dispatched(requests, rows)


def test_merge_preserves_unknown_invalid_repeats_and_denominators(original):
    _plan, _data, selected, rows, _summary, _ledger = original
    new = not_dispatched(selected)
    for row in new:
        row["status"] = "valid_diagnosis"
    before = copy.deepcopy(rows)
    merged = c.combine_rows(rows, new, selected)
    assert rows == before
    assert Counter(r["status"] for r in merged) == {
        "valid_diagnosis": 539,
        "invalid_judgment": 1,
        "transport_or_recording_ambiguous_no_retry": 4,
    }
    assert sum(r["replicate"] == 0 and r["status"] == "valid_diagnosis" for r in merged) == 508
    assert len(merged) == 544
    assert [r for r in merged if r["replicate"] == 1] == [r for r in rows if r["replicate"] == 1]


@pytest.mark.parametrize(
    "status",
    [
        "valid_diagnosis",
        "invalid_judgment",
        "transport_or_recording_ambiguous_no_retry",
        "reserved_pending_unknown",
    ],
)
def test_merge_cannot_replace_any_reserved_status(original, status):
    _plan, _data, _selected, rows, _summary, _ledger = original
    old_row = copy.deepcopy(rows[0])
    old_row["status"] = status
    replacement = {**old_row, "status": "valid_diagnosis"}
    with pytest.raises(ValueError, match="reserved or repeat"):
        c.combine_rows([old_row], [replacement], [{"request_id": old_row["request_id"]}])


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "coordinate", "unknown"])
def test_merge_rejects_ambiguous_inventory(original, mutation):
    _plan, _data, selected, rows, _summary, _ledger = original
    new, chosen = not_dispatched(selected), copy.deepcopy(selected)
    if mutation == "duplicate":
        chosen.append(chosen[0])
        new.append(new[0])
    elif mutation == "missing":
        new.pop()
    elif mutation == "coordinate":
        new[0]["item_id"] = "wrong_item"
    else:
        chosen[0]["request_id"] = new[0]["request_id"] = "unknown-request"
    with pytest.raises(ValueError):
        c.combine_rows(rows, new, chosen)


@pytest.mark.parametrize("failure", [*sorted(old.TERMINAL_FAILURES), "raise"])
def test_failure_stops_dispatch_without_retry(tmp_path, failure):
    selected = [{"request_id": str(i), "item_id": str(i)} for i in range(8)]
    calls = []

    def fake(request, *_args):
        calls.append(request["request_id"])
        if failure == "raise":
            raise OSError("not a credential; must not be exposed")
        return {"status": failure}

    result = c.dispatch_selected(
        selected,
        {str(i): {"payload": {}} for i in range(8)},
        {},
        tmp_path,
        "not-a-real-key",
        workers=1,
        spacing=0,
        run_one=fake,
    )
    assert result == {"halted": True, "submitted": 1, "completed": 1}
    assert calls == ["0"]


def test_inflight_drains_and_concurrency_is_bounded(tmp_path):
    selected = [{"request_id": str(i), "item_id": str(i)} for i in range(12)]
    condition = threading.Condition()
    calls, active = [], [0, 0]

    def fake(request, *_args):
        with condition:
            calls.append(request["request_id"])
            active[0] += 1
            active[1] = max(active)
            condition.notify_all()
            assert condition.wait_for(lambda: len(calls) == 4, timeout=5)
        if request["request_id"] != "0":
            time.sleep(0.2)
        with condition:
            active[0] -= 1
        return {
            "status": "http_error_no_retry" if request["request_id"] == "0" else "response_recorded"
        }

    result = c.dispatch_selected(
        selected,
        {str(i): {"payload": {}} for i in range(12)},
        {},
        tmp_path,
        "not-a-real-key",
        workers=4,
        spacing=0,
        run_one=fake,
    )
    assert result == {"halted": True, "submitted": 4, "completed": 4}
    assert active == [0, 4]


def test_invalid_diagnosis_stays_invalid_and_does_not_trigger_retry(tmp_path):
    selected = [{"request_id": str(i), "item_id": str(i)} for i in range(3)]
    calls = []

    def fake(request, *_args):
        calls.append(request["request_id"])
        return {"status": "response_recorded", "observation": {"status": "invalid_judgment"}}

    result = c.dispatch_selected(
        selected,
        {str(i): {"payload": {}} for i in range(3)},
        {},
        tmp_path,
        "not-a-real-key",
        workers=1,
        spacing=0.1,
        run_one=fake,
    )
    assert result == {"halted": False, "submitted": 3, "completed": 3}
    assert calls == ["0", "1", "2"]


@pytest.fixture
def new_root(tmp_path, monkeypatch):
    monkeypatch.setattr(old, "REPO", tmp_path)
    monkeypatch.setattr(c, "REPO", tmp_path)
    root = tmp_path / c.ROOT
    root.mkdir(parents=True)
    return root


@pytest.mark.parametrize(
    "unauthorized", ["openai/study", "mistral/calibration", "mistral/study/calls/unknown"]
)
def test_unselected_cells_never_replay(new_root, original, unauthorized):
    plan, data, selected, *_ = original
    (new_root / unauthorized).mkdir(parents=True)
    with pytest.raises(ValueError):
        c.replay_continuation(plan, data, selected)


def test_symlink_raw_evidence_rejected(new_root, original):
    plan, data, selected, *_ = original
    calls = new_root / "mistral/study/calls"
    calls.mkdir(parents=True)
    (calls / selected[0]["request_id"]).symlink_to(new_root, target_is_directory=True)
    with pytest.raises(ValueError, match="Symlink"):
        c.replay_continuation(plan, data, selected)


def test_original_tree_hashes_detect_additions_mutations(new_root):
    p = new_root / "RECEIPT.json"
    d.io.write_json(p, {"a": 1}, exclusive=True)
    before = c.tree_hashes(new_root)
    d.io.write_json(p, {"a": 2})
    assert c.tree_hashes(new_root) != before
    d.io.write_json(p, {"a": 1})
    d.io.write_json(new_root / "extra.json", {}, exclusive=True)
    assert c.tree_hashes(new_root) != before


@pytest.mark.parametrize("reservation", ["STARTED.json", "FINISHED.json", "calls"])
def test_no_implicit_resume_before_key_or_dispatch(new_root, original, monkeypatch, reservation):
    plan, data, selected, rows, summary, ledger = original
    monkeypatch.setattr(
        c,
        "load_frozen",
        lambda: (plan, data, {"original_bundle_files": {}}, selected, rows, summary, ledger),
    )
    monkeypatch.setattr(c, "verify_checkout", lambda: pytest.fail("Must not admit a started cell"))
    cell = new_root / "mistral/study"
    cell.mkdir(parents=True)
    if reservation == "calls":
        (cell / reservation).mkdir()
    else:
        d.io.write_json(cell / reservation, {}, exclusive=True)
    with pytest.raises(ValueError, match="no resume"):
        c.run(execute=True)


def test_verify_has_no_network_and_missing_key_prevents_reservation(
    new_root, original, monkeypatch
):
    plan, data, selected, rows, summary, ledger = original
    monkeypatch.setattr(
        c,
        "load_frozen",
        lambda: (plan, data, {"original_bundle_files": {}}, selected, rows, summary, ledger),
    )
    monkeypatch.setattr(old, "transport", lambda *_a, **_k: pytest.fail("Network forbidden"))
    monkeypatch.setattr(c, "verify_checkout", lambda: "test_commit")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    assert c.run()["counts"] == {"not_dispatched": 320}
    with pytest.raises(ValueError, match="Missing MISTRAL_API_KEY"):
        c.run(execute=True)
    assert not (new_root / "mistral/study/STARTED.json").exists()


def test_replay_exact_bodies_and_combined_usage_without_duplicates(new_root, original, monkeypatch):
    plan, data, selected, rows, summary, ledger = original
    request = selected[0]
    payload = next(r["payload"] for r in data["records"] if r["item_id"] == request["item_id"])
    value = {k: "unclear" for k in d.ENUMS}
    value.update(evidence={k: [] for k in d.ENUMS}, assessment_en="Synthetic replay fixture.")
    raw = {
        "id": "synthetic_fixture",
        "model": "mistral-large-4",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(value)},
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
    }
    cell = new_root / "mistral/study"
    dispatches = []

    def fake(endpoint, key, body, timeout):
        dispatches.append(1)
        assert endpoint == plan["providers"]["mistral"]["endpoint"]
        assert body == request["body"] and timeout == 1200
        return raw

    old.run_one(request, payload, plan["providers"]["mistral"], cell, "not-a-real-key", fake)
    with pytest.raises(FileExistsError):
        old.run_one(request, payload, plan["providers"]["mistral"], cell, "not-a-real-key", fake)
    assert len(dispatches) == 1
    replay = c.replay_continuation(plan, data, selected)
    assert Counter(r["status"] for r in replay) == {"valid_diagnosis": 1, "not_dispatched": 319}
    combined = c.combine_rows(rows, replay, selected)
    assert Counter(r["status"] for r in combined) == {
        **c.BASELINE_COUNTS,
        "valid_diagnosis": 220,
        "not_dispatched": 319,
    }
    # Exercise the real additive analyzer, with the immutable original calibration read in place.
    actual_repo = d.REPO
    monkeypatch.setattr(c, "ORIGINAL", str(actual_repo / c.ORIGINAL))
    seal = {"original_bundle_files": {"test": "hash"}, "manifest_sha256": io_sha(selected)}
    d.io.write_json(new_root / "CONTINUATION_SEAL.json", seal, exclusive=True)
    d.io.write_json(
        cell / "STARTED.json",
        {
            "source_commit": "fixture",
            "continuation_seal_sha256": d.io.file_sha(new_root / "CONTINUATION_SEAL.json"),
            "manifest_sha256": io_sha(selected),
        },
        exclusive=True,
    )
    d.io.write_json(
        cell / "FINISHED.json",
        {
            "status": "HALTED_NO_RETRY",
            "planned": 320,
            "retries": 0,
            "counts": dict(Counter(r["status"] for r in replay)),
            "combined_mistral_study_and_repeat_counts": dict(
                Counter(r["status"] for r in combined)
            ),
        },
        exclusive=True,
    )
    monkeypatch.setattr(
        c, "load_frozen", lambda: (plan, data, seal, selected, rows, summary, ledger)
    )
    merged_summary, merged_ledger = c.analyze()
    assert merged_summary["status"] == "INCOMPLETE_OR_CALIBRATION_BLOCKED"
    assert merged_summary["old_expression_gate"] == "FAIL"
    assert merged_summary["providers"]["openai"] == summary["providers"]["openai"]
    a, b = (s["providers"]["mistral"] for s in (summary, merged_summary))
    assert a["repeat_stability"] == b["repeat_stability"]
    assert b["usage"]["reserved_calls"] == a["usage"]["reserved_calls"] + 1
    assert b["usage"]["reported_input_tokens"] == a["usage"]["reported_input_tokens"] + 100
    assert b["usage"]["reported_output_tokens"] == a["usage"]["reported_output_tokens"] + 200
    assert len(merged_ledger) == 512
    assert [(r["mechanical"], r["oracle"], r["payload"]) for r in merged_ledger] == [
        (r["mechanical"], r["oracle"], r["payload"]) for r in ledger
    ]
    assert sum(s["total"] for s in merged_summary["strata"]) == 512


def io_sha(value):
    return d.io.sha256(value)
