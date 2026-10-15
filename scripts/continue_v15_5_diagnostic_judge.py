"""One explicitly authorized, additive continuation of 320 never-dispatched calls.

This is not a generic resume command. The original paid run, rubric and runner
stay immutable; ambiguous reservations and invalid diagnoses cannot be selected.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import copy
import json
import os
import subprocess
import threading
import time
from collections import Counter
from decimal import Decimal
from pathlib import Path

import run_v15_5_diagnostic_judge as old
import summarize_v15_5_diagnostic_judge as report
import v15_5_diagnostics as d

io, REPO = d.io, d.REPO
ORIGINAL = "provenance/pilots/v15_5_diagnostic_judge_20261010"
ROOT = "provenance/pilots/v15_5_diagnostic_judge_continuation_01_20261010"
PARENT_COMMIT = "5a27d0d663dfd3e3a6f607256fe0201439929386"
ORIGINAL_PAID_COMMIT = "59ac10623c0f088d61481e1cfbb9898c206002b5"
BRANCH = "SpiralReality/v15-5-judge-diagnostics"
REMOTE = "https://github.com/RyoSpiralArchitect/Latent_Workspace.git"
SOURCES = (
    "scripts/continue_v15_5_diagnostic_judge.py",
    "tests/test_v15_5_diagnostic_continuation.py",
    "docs/v15_5/DIAGNOSTIC_CONTINUATION_01.md",
)
BASELINE_COUNTS = {
    "valid_diagnosis": 219,
    "invalid_judgment": 1,
    "transport_or_recording_ambiguous_no_retry": 4,
    "not_dispatched": 320,
}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def tree_hashes(root):
    root = old.confined(root)
    files = {}
    for path in sorted(root.rglob("*")):
        d.require(not path.is_symlink(), "Symlink inside evidence bundle")
        if path.is_file():
            files[str(path.relative_to(root))] = io.file_sha(path)
    return files


def select_never_dispatched(requests, rows):
    ids = [r["request_id"] for r in requests]
    d.require(len(ids) == len(set(ids)) == 544, "Original request inventory")
    d.require([r["request_id"] for r in rows] == ids, "Replay inventory/order")
    d.require(dict(Counter(r["status"] for r in rows)) == BASELINE_COUNTS, "Baseline counts")
    selected = [q for q, r in zip(requests, rows, strict=True) if r["status"] == "not_dispatched"]
    d.require(len(selected) == 320, "Exactly 320 never-dispatched requests")
    d.require(
        all(
            (r["provider"], r["phase"], r["replicate"]) == ("mistral", "study", 0) for r in selected
        ),
        "Only Mistral study r0 is authorized",
    )
    return selected


def verify_original(plan, data):
    root = old.confined(REPO / ORIGINAL)
    summary, ledger = report.analyze(root)
    d.require(io.load_json(root / "analysis/SUMMARY.json") == summary, "Original summary replay")
    d.require(io.load_json(root / "analysis/LEDGER.json") == ledger, "Original ledger replay")
    d.require(
        io.load_json(root / "analysis/ARTIFACT_INDEX.json") == report.raw_index(root),
        "Original raw index replay",
    )
    d.require(
        (root / "analysis/DIAGNOSTIC_PANEL.md").read_text() == report.panel_text(summary, ledger),
        "Original literal panel replay",
    )
    d.require(summary["status"] == "INCOMPLETE_OR_CALIBRATION_BLOCKED", "Original claim ceiling")
    d.require(summary["old_expression_gate"] == "FAIL", "Original expression gate")
    d.require(
        summary["providers"]["mistral"]["calibration"]["status"] == "PASS", "Mistral admission"
    )
    d.require(
        summary["providers"]["openai"]["calibration"]["status"] == "FAIL", "OpenAI remains blocked"
    )
    d.require(
        summary["providers"]["openai"]["study_and_repeat_statuses"] == {"not_dispatched": 544},
        "OpenAI study must remain undispatched",
    )
    rows = old.replay_cell(root, "mistral", "study", plan, data)
    requests = d.requests_for(data, plan, "mistral", "study")
    selected = select_never_dispatched(requests, rows)
    selected_ids = {r["request_id"] for r in selected}
    reserved = {p.name for p in (root / "mistral/study/calls").iterdir()}
    d.require(len(reserved) == 224 and not (reserved & selected_ids), "Disjoint old reservations")
    started = io.load_json(root / "mistral/study/STARTED.json")
    finished = io.load_json(root / "mistral/study/FINISHED.json")
    d.require(started["source_commit"] == ORIGINAL_PAID_COMMIT, "Original paid source")
    d.require(
        finished["status"] == "HALTED_NO_RETRY"
        and finished["planned"] == 544
        and finished["counts"] == BASELINE_COUNTS,
        "Original terminal receipt",
    )
    metadata = io.load_json(root / "metadata/mistral.receipt.json")
    d.require(
        metadata["status"] == "MODEL_PRESENT"
        and metadata["returned_id"] == plan["providers"]["mistral"]["model"],
        "Original metadata identity",
    )
    return selected, rows, summary, ledger


def freeze():
    d.require(git("rev-parse", "HEAD") == PARENT_COMMIT, "Freeze must follow terminal parent")
    plan, data, _ = old.load_frozen()
    selected, rows, _summary, _ledger = verify_original(plan, data)
    root = old.confined(REPO / ROOT)
    root.mkdir(parents=True, exist_ok=False)
    io.write_json(root / "mistral/study/REQUESTS.json", selected, exclusive=True)
    seal = {
        "format": "v15.5-never-dispatched-continuation-seal-v1",
        "client_date": "2026-10-10",
        "parent_commit": PARENT_COMMIT,
        "original_paid_source_commit": ORIGINAL_PAID_COMMIT,
        "original_bundle": ORIGINAL,
        "continuation_bundle": ROOT,
        "original_source_seal_sha256": io.file_sha(REPO / d.SEAL),
        "original_bundle_files": tree_hashes(REPO / ORIGINAL),
        "source_hashes": {p: io.file_sha(REPO / p) for p in SOURCES},
        "manifest_sha256": io.sha256(selected),
        "selected_request_ids": [r["request_id"] for r in selected],
        "excluded_original_outcomes": [r for r in rows if r["status"] != "not_dispatched"],
        "planned": 320,
        "estimated_undiscounted_upper_bound_usd": str(
            sum((Decimal(r["cost_upper_bound_usd"]) for r in selected), Decimal(0))
        ),
        "authority": "Ryō approved the separately recorded continuation of only the 320 "
        "never-dispatched Mistral requests: うん！きちっと終わらせよ🐈‍⬛🌀",
        "unchanged": [
            "model",
            "body",
            "seed",
            "token_caps",
            "rubric",
            "validator",
            "calibration",
            "timeout",
            "concurrency",
            "spacing",
            "old_FAIL_gate",
        ],
        "retry_policy": "No retry or implicit resume. Any new transport/HTTP failure stops "
        "new dispatch, drains in-flight calls and requires a new decision.",
        "remote_weight_revision": "UNKNOWN",
        "openai_study": "BLOCKED_NOT_AUTHORIZED",
        "actual_billed_cost_usd": None,
        "training_performed": False,
        "new_learner_generations": 0,
    }
    io.write_json(root / "CONTINUATION_SEAL.json", seal, exclusive=True)
    return {
        "status": "FROZEN_NOT_DISPATCHED",
        "planned": 320,
        "manifest_sha256": seal["manifest_sha256"],
        "estimated_undiscounted_upper_bound_usd": seal["estimated_undiscounted_upper_bound_usd"],
    }


def load_frozen():
    plan, data, _ = old.load_frozen()
    root = old.confined(REPO / ROOT)
    seal = io.load_json(root / "CONTINUATION_SEAL.json")
    d.require(seal["format"] == "v15.5-never-dispatched-continuation-seal-v1", "Seal format")
    d.require(
        (seal["parent_commit"], seal["original_bundle"], seal["continuation_bundle"])
        == (PARENT_COMMIT, ORIGINAL, ROOT),
        "Continuation lineage",
    )
    d.require(
        seal["original_source_seal_sha256"] == io.file_sha(REPO / d.SEAL), "Old seal unchanged"
    )
    d.require(
        seal["original_bundle_files"] == tree_hashes(REPO / ORIGINAL), "Original bundle changed"
    )
    d.require(
        seal["source_hashes"] == {p: io.file_sha(REPO / p) for p in SOURCES},
        "Continuation source changed",
    )
    selected, rows, summary, ledger = verify_original(plan, data)
    d.require(
        io.load_json(root / "mistral/study/REQUESTS.json") == selected, "Exact selected bodies"
    )
    d.require(
        seal["manifest_sha256"] == io.sha256(selected)
        and seal["selected_request_ids"] == [r["request_id"] for r in selected]
        and seal["planned"] == len(selected) == 320,
        "Frozen continuation selection",
    )
    d.require(
        seal["excluded_original_outcomes"] == [r for r in rows if r["status"] != "not_dispatched"],
        "Excluded outcomes changed",
    )
    return plan, data, seal, selected, rows, summary, ledger


def replay_continuation(plan, data, selected):
    root = old.confined(REPO / ROOT)
    d.require(
        not (root / "openai").exists() and not (root / "mistral/calibration").exists(),
        "Unauthorized continuation cell",
    )
    # Check all descendants before following any raw-record paths.
    tree_hashes(root / "mistral")
    calls = root / "mistral/study/calls"
    selected_ids = {r["request_id"] for r in selected}
    if calls.exists():
        d.require({p.name for p in calls.iterdir()} <= selected_ids, "Unselected call directory")
    all_rows = old.replay_cell(root, "mistral", "study", plan, data)
    return [r for r in all_rows if r["request_id"] in selected_ids]


def combine_rows(original, continuation, selected):
    selected_ids = [r["request_id"] for r in selected]
    d.require(len(selected_ids) == len(set(selected_ids)), "Duplicate selected request")
    d.require(
        [r["request_id"] for r in continuation] == selected_ids, "Continuation replay inventory"
    )
    original_ids = [r["request_id"] for r in original]
    d.require(len(original_ids) == len(set(original_ids)), "Duplicate original request")
    d.require(set(selected_ids) <= set(original_ids), "Unknown continuation request")
    replacement = {r["request_id"]: r for r in continuation}
    combined = []
    for row in original:
        other = replacement.get(row["request_id"])
        if other is not None:
            d.require(
                row["status"] == "not_dispatched" and row["replicate"] == 0,
                "Cannot replace a reserved or repeat outcome",
            )
            d.require(
                (row["item_id"], row["replicate"]) == (other["item_id"], other["replicate"]),
                "Combined coordinate mismatch",
            )
        combined.append(copy.deepcopy(other if other is not None else row))
    return combined


def dispatch_selected(
    selected, items, config, cell, api_key, *, workers, spacing, run_one=old.run_one
):
    """Drain observed completions before admitting more work; never retry a future."""
    stop = threading.Event()

    def worker(request):
        try:
            result = run_one(request, items[request["item_id"]]["payload"], config, cell, api_key)
            if result["status"] in old.TERMINAL_FAILURES:
                stop.set()
            return result
        except Exception:
            stop.set()
            raise

    pending, index, completed, last_start = {}, 0, 0, float("-inf")
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        while index < len(selected) or pending:
            if pending:
                done, _ = concurrent.futures.wait(
                    pending, timeout=0.1, return_when=concurrent.futures.FIRST_COMPLETED
                )
                for future in done:
                    request_id = pending.pop(future)
                    try:
                        outcome = future.result()
                        status = outcome.get("observation", {}).get("status", outcome["status"])
                    except Exception:
                        stop.set()
                        status = "recording_failure_unknown"
                    completed += 1
                    print(
                        json.dumps(
                            {
                                "continuation": "01",
                                "completed": completed,
                                "planned": len(selected),
                                "last": request_id,
                                "status": status,
                            }
                        ),
                        flush=True,
                    )
            if stop.is_set() and not pending:
                break
            now = time.monotonic()
            if (
                not stop.is_set()
                and index < len(selected)
                and len(pending) < workers
                and now - last_start >= spacing
            ):
                request = selected[index]
                pending[pool.submit(worker, request)] = request["request_id"]
                index += 1
                last_start = now
            elif not pending:
                time.sleep(0.1)
    return {"halted": stop.is_set(), "submitted": index, "completed": completed}


def verify_checkout():
    d.require(
        Path(git("rev-parse", "--show-toplevel")).resolve() == REPO.resolve(), "Exact checkout"
    )
    d.require(git("branch", "--show-current") == BRANCH, "Continuation branch")
    d.require(
        git("remote", "get-url", "origin") == REMOTE
        and git("remote", "get-url", "--push", "origin") == REMOTE,
        "Exact remote",
    )
    git("merge-base", "--is-ancestor", PARENT_COMMIT, "HEAD")
    paths = [*SOURCES, f"{ROOT}/CONTINUATION_SEAL.json", f"{ROOT}/mistral/study/REQUESTS.json"]
    git("ls-files", "--error-unmatch", "--", *paths)
    d.require(
        not git("status", "--porcelain", "--", *paths), "Commit continuation source before dispatch"
    )
    return git("rev-parse", "HEAD")


def run(execute=False):
    plan, data, seal, selected, original, _summary, _ledger = load_frozen()
    root = old.confined(REPO / ROOT)
    cell = root / "mistral/study"
    replay = replay_continuation(plan, data, selected)
    if not execute:
        return {
            "status": "VERIFIED_NO_NETWORK",
            "planned": len(selected),
            "counts": dict(Counter(r["status"] for r in replay)),
            "original_sealed_files": len(seal["original_bundle_files"]),
        }
    d.require(
        not (cell / "STARTED.json").exists()
        and not (cell / "FINISHED.json").exists()
        and not (cell / "calls").exists(),
        "Continuation already reserved; no resume",
    )
    commit = verify_checkout()
    config = plan["providers"]["mistral"]
    api_key = os.environ.get(config["env_key"])
    d.require(bool(api_key), "Missing MISTRAL_API_KEY")
    io.write_json(
        cell / "STARTED.json",
        {
            "format": "v15.5-continuation-start-v1",
            "started_at": io.now(),
            "pid": os.getpid(),
            "source_commit": commit,
            "continuation_seal_sha256": io.file_sha(root / "CONTINUATION_SEAL.json"),
            "original_paid_source_commit": ORIGINAL_PAID_COMMIT,
            "original_source_seal_sha256": seal["original_source_seal_sha256"],
            "manifest_sha256": seal["manifest_sha256"],
            "provider": "mistral",
            "phase": "study",
            "planned": 320,
            "retries": 0,
        },
        exclusive=True,
    )
    result = dispatch_selected(
        selected,
        {r["item_id"]: r for r in data["records"]},
        config,
        cell,
        api_key,
        workers=plan["concurrency_per_provider"],
        spacing=plan["minimum_dispatch_spacing_seconds"],
    )
    replay = replay_continuation(plan, data, selected)
    combined = combine_rows(original, replay, selected)
    terminal = {
        "status": "HALTED_NO_RETRY" if result["halted"] else "ALL_SELECTED_ATTEMPTED",
        "provider": "mistral",
        "phase": "study",
        "planned": 320,
        "counts": dict(Counter(r["status"] for r in replay)),
        "combined_mistral_study_and_repeat_counts": dict(Counter(r["status"] for r in combined)),
        "cross_provider_status": "INCOMPLETE_OR_CALIBRATION_BLOCKED",
        "old_expression_gate": "FAIL",
        "dispatch": result,
        "finished_at": io.now(),
        "retries": 0,
    }
    io.write_json(cell / "FINISHED.json", terminal, exclusive=True)
    return terminal


def analyze():
    plan, data, seal, selected, original, base_summary, base_ledger = load_frozen()
    root = old.confined(REPO / ROOT)
    started = io.load_json(root / "mistral/study/STARTED.json")
    finished = io.load_json(root / "mistral/study/FINISHED.json")
    d.require(
        started["continuation_seal_sha256"] == io.file_sha(root / "CONTINUATION_SEAL.json")
        and started["manifest_sha256"] == seal["manifest_sha256"],
        "Continuation start identity",
    )
    new = replay_continuation(plan, data, selected)
    combined = combine_rows(original, new, selected)
    d.require(
        finished["counts"] == dict(Counter(r["status"] for r in new))
        and finished["combined_mistral_study_and_repeat_counts"]
        == dict(Counter(r["status"] for r in combined)),
        "Terminal count replay",
    )
    d.require(finished["planned"] == 320 and finished["retries"] == 0, "Terminal scope")
    d.require(
        finished["status"] in ("HALTED_NO_RETRY", "ALL_SELECTED_ATTEMPTED"), "Terminal status"
    )
    if finished["status"] == "ALL_SELECTED_ATTEMPTED":
        d.require(
            all(
                r["status"]
                not in old.TERMINAL_FAILURES | {"not_dispatched", "reserved_pending_unknown"}
                for r in new
            ),
            "Incomplete terminal",
        )
    summary, ledger = copy.deepcopy(base_summary), copy.deepcopy(base_ledger)
    p = summary["providers"]["mistral"]
    p["study_and_repeat_statuses"] = dict(Counter(r["status"] for r in combined))
    p["primary_measurement_statuses"] = dict(
        Counter(r["status"] for r in combined if r["replicate"] == 0)
    )
    d.require(
        [r for r in combined if r["replicate"] == 1]
        == [r for r in original if r["replicate"] == 1],
        "Fixed repeat panel must be untouched",
    )
    cal = old.replay_cell(REPO / ORIGINAL, "mistral", "calibration", plan, data)
    receipts = []
    for phase, rows in (("calibration", cal), ("study", combined)):
        requests = {r["request_id"]: r for r in d.requests_for(data, plan, "mistral", phase)}
        receipts.extend(
            {**requests[r["request_id"]], "usage_receipt": r.get("usage_receipt", {})}
            for r in rows
            if r["status"] != "not_dispatched"
        )
    p["usage"] = io.usage_summary(receipts)
    indexed = {r["item_id"]: r for r in combined if r["replicate"] == 0}
    selected_ids = {r["request_id"] for r in selected}
    for row in ledger:
        value = indexed[row["item_id"]]
        observation = value.get("observation") if value["status"] == "valid_diagnosis" else None
        commitment = observation["judgment"]["commitment"] if observation else None
        row["diagnoses"]["mistral"] = {
            "status": value["status"],
            "request_id": value["request_id"],
            "observation": observation,
            "bucket": report.bucket(row, observation),
            "truth_relative_commitment_match": commitment == row["oracle"]["answer"]
            if commitment in ("yes", "no")
            else None,
            "call_source_bundle": ROOT if value["request_id"] in selected_ids else ORIGINAL,
        }
    summary["primary_inline"] = report.summarize_rows(
        [r for r in ledger if r["coordinate"]["information"] == "inline"]
    )
    summary["secondary_query_only"] = report.summarize_rows(
        [r for r in ledger if r["coordinate"]["information"] == "query_only"]
    )
    strata = []
    for entry in summary["strata"]:
        keys = {k: entry[k] for k in ("renderer", "cue", "information", "view", "label")}
        rows = [
            r
            for r in ledger
            if all(r["coordinate"][k] == keys[k] for k in ("renderer", "cue", "information"))
            and r["view"] == keys["view"]
            and r["oracle"]["label"] == keys["label"]
        ]
        strata.append({**keys, **report.summarize_rows(rows)})
    summary["strata"] = strata
    summary["continuation"] = {
        "bundle": ROOT,
        "original_bundle": ORIGINAL,
        "parent_commit": PARENT_COMMIT,
        "source_commit": started["source_commit"],
        "status": finished["status"],
        "planned": 320,
        "counts": finished["counts"],
        "retries": 0,
        "original_reserved_outcomes_replaced": 0,
        "original_bundle_files_verified": len(seal["original_bundle_files"]),
        "continuation_seal_sha256": io.file_sha(root / "CONTINUATION_SEAL.json"),
    }
    d.require(
        summary["status"] == "INCOMPLETE_OR_CALIBRATION_BLOCKED"
        and summary["old_expression_gate"] == "FAIL",
        "Combined claim ceiling",
    )
    return summary, ledger


def analysis_artifacts(write=False, verify=False):
    summary, ledger = analyze()
    root = old.confined(REPO / ROOT)
    path = root / "analysis"
    index = {
        "format": "v15.5-combined-diagnostic-index-v1",
        "original_bundle": ORIGINAL,
        "original_files": tree_hashes(REPO / ORIGINAL),
        "continuation_bundle": ROOT,
        "continuation_raw": report.raw_index(root),
        "continuation_seal_sha256": io.file_sha(root / "CONTINUATION_SEAL.json"),
    }
    artifacts = {"SUMMARY.json": summary, "LEDGER.json": ledger, "ARTIFACT_INDEX.json": index}
    panel = report.panel_text(summary, ledger)
    if write:
        path.mkdir(parents=True, exist_ok=False)
        for name, value in artifacts.items():
            io.write_json(path / name, value, exclusive=True)
        with (path / "DIAGNOSTIC_PANEL.md").open("x", encoding="utf-8") as stream:
            stream.write(panel)
    if verify:
        for name, value in artifacts.items():
            d.require(io.load_json(path / name) == value, f"Combined replay: {name}")
        d.require((path / "DIAGNOSTIC_PANEL.md").read_text() == panel, "Combined literal panel")
    return {
        "status": summary["status"],
        "continuation": summary["continuation"],
        "mistral": summary["providers"]["mistral"]["study_and_repeat_statuses"],
        "old_expression_gate": "FAIL",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("freeze", "verify", "run", "write-analysis", "verify-analysis")
    )
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    d.require(not args.execute or args.action == "run", "Execute only with run")
    if args.action == "freeze":
        result = freeze()
    elif args.action in ("run", "verify"):
        result = run(execute=args.execute)
    else:
        result = analysis_artifacts(
            write=args.action == "write-analysis", verify=args.action == "verify-analysis"
        )
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
