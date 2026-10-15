#!/usr/bin/env python3
"""Offline check of the stopped V19 frozen diagnostic attempt 01; no model execution.

The sealed verifier accepts only a complete dispatch. This additive check loads
that verifier from a clean checkout of the execution commit (``--repo``) and
reuses its functions to verify what the stopped attempt did record: sealed
sources, both qualification bundles, the dispatch and role manifests, the
complete ``ordered_cap025`` arm (every summary and diagnosis recomputed from the
gzip records) and the stopped ``final_cap025`` arm (its 512-window journal and
every saved evaluation recomputed). The stopped arm's step-512 held-out
evaluation is missing, not zero. Checkpoint bodies are rehashed only when their
directory is supplied.

The sealed verifier's checkpoint-receipt check compares against the V18 owner's
format string, which no V19 checkpoint can carry. Its ``verify_arm`` is
therefore called with the receipt loop disabled, and receipts are checked
against the sealed V19 window owner's own ``FORMAT``; nothing else is replaced.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

STOPPED, COMPLETE = "final_cap025", "ordered_cap025"
DISPATCH_ERROR = f"ValueError: {STOPPED} exited 1; no later role or retry dispatched"
STOP_ERROR = "ValueError: Another GPU client; stop own job only"


def load_verifier(repo):
    path = repo / "scripts/verify_v19_frozen_diagnostic.py"
    spec = importlib.util.spec_from_file_location("v19_frozen_verifier", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_stopped_arm(VERIFY, bundle, plan, records, summarize, schedule_ids, checkpoints):
    RUN, require, same = VERIFY.RUN, VERIFY.require, VERIFY.RUN.pilot().same
    context = RUN.read(bundle / "CONTEXT.json")
    initial = RUN.read(bundle / "INITIAL.json")
    require(context["contract"]["full_update"] is False, "Frozen contract")
    require(
        initial["native_sha256"] == context["contract"]["original_base_sha256"],
        "Frozen backbone identity at start",
    )
    lines = (bundle / "windows.jsonl").read_text().splitlines()
    require(len(lines) == plan["schedule"]["updates"], "All scheduled windows completed")
    for step, line in enumerate(lines, start=1):
        window = json.loads(line)
        require(
            window["update"]["completed_step"] == step
            and window["window_id"] == schedule_ids[step - 1]
            and window["update"]["base_changes"] == []
            and len(window["pairs"]) == plan["schedule"]["occurrences_per_window"],
            f"Window {step} receipt",
        )
    curve, missing = {}, []
    for split, steps in (
        ("dev", plan["dev_evaluation_steps"]),
        ("final", plan["final_evaluation_steps"]),
    ):
        for step in steps:
            path = bundle / f"eval_{split}_step{step}.json.gz"
            if not path.exists():
                require(
                    not (bundle / f"summary_{split}_step{step}.json").exists(),
                    f"{split} {step} summary without records",
                )
                missing.append(f"{split}:{step}")
                continue
            report = RUN.read_gz(path)
            require(
                report["step"] == step
                and report["rng_unchanged"] is True
                and report["owned_state_fingerprint_unchanged"] is True,
                f"{split} {step}",
            )
            require(
                all(
                    r["full_logits_equal_current_base"]
                    for r in report["rows"]
                    if r["condition"] == "zero"
                ),
                f"{split} {step} zero-memory validity",
            )
            require(same(summarize(report), report["summary"]), f"{split} {step} summary")
            diagnosis = RUN.diagnose(report, records[split], plan["endpoints"])
            require(same(diagnosis, report["diagnosis"]), f"{split} {step} diagnosis")
            saved = RUN.read(bundle / f"summary_{split}_step{step}.json")
            require(
                same(saved["diagnosis"], diagnosis) and same(saved["summary"], report["summary"]),
                f"{split} {step} summary file",
            )
            curve[f"{split}:{step}"] = {
                "flips": diagnosis["flips"],
                "world_sign": diagnosis["world_sign"],
                "sign_test_p": diagnosis["sign_test_p"],
                "verdict": diagnosis["verdict"],
                "unaffected_prediction_changes": diagnosis["unaffected_prediction_changes"],
                "accuracy_by_wording": diagnosis["accuracy_by_wording"],
            }
    endpoint = f"final:{plan['endpoints']['step']}"
    require(missing == [endpoint], f"Only the endpoint evaluation may be missing: {missing}")
    require(
        not any(
            (bundle / name).exists()
            for name in (
                "DIAGNOSIS.json",
                "FINAL_STATE.json",
                f"CHECKPOINT_step{plan['endpoints']['step']}.json",
            )
        ),
        "No endpoint, final state or step-512 checkpoint may be claimed",
    )
    steps = [s for s in plan["checkpoint_steps"] if (bundle / f"CHECKPOINT_step{s}.json").exists()]
    require(steps == [256], "Stopped arm checkpoint set")
    return curve, missing, verify_receipts(VERIFY, bundle, steps, checkpoints)


def verify_receipts(VERIFY, bundle, steps, checkpoints):
    """Checkpoint receipts against the sealed V19 window owner's format."""
    from latent_workspace_ft_v10.v19_dual_budget_window_learner import FORMAT

    RUN, require = VERIFY.RUN, VERIFY.require
    condition = RUN.read(bundle / "CONTEXT.json")["contract"]["condition"]
    receipts = []
    for step in steps:
        receipt = RUN.read(bundle / f"CHECKPOINT_step{step}.json")
        require(
            receipt["completed_steps"] == step and receipt["format"] == FORMAT,
            f"Checkpoint {step}",
        )
        if checkpoints is not None:
            body = checkpoints / condition / receipt["path"]
            require(
                body.stat().st_size == receipt["bytes"] and RUN.digest(body) == receipt["sha256"],
                f"Checkpoint {step} bytes",
            )
        receipts.append(receipt)
    return receipts


def stop_observation(require, bundle):
    """The guard sample that recorded the foreign GPU client."""
    rows = [json.loads(line) for line in (bundle / "RESOURCES.jsonl").read_text().splitlines()]
    last = rows[-1]
    foreign = [p for p in last["processes"] if p["pid"] != last["own_pid"]]
    require(foreign, "Last guard sample must show a foreign GPU client")
    require(
        all(p["pid"] == r["own_pid"] for r in rows[:-1] for p in r["processes"]),
        "Only the last guard sample may show a foreign client",
    )
    return {
        "phase": last["phase"],
        "samples": len(rows),
        "foreign_clients": [{"pid": p["pid"], "bytes": p["bytes"]} for p in foreign],
        "device_used_bytes": last["used_bytes"],
        "device_free_bytes": last["free_bytes"],
    }


def verify(repo, bundle, qualification, seal_path, checkpoints=None):
    VERIFY = load_verifier(repo)
    RUN, require = VERIFY.RUN, VERIFY.require
    sys.path.insert(0, str(repo / "src"))
    from latent_workspace_ft_v10.v16_comparison_eval import summarize

    seal = RUN.read(seal_path)
    VERIFY.verify_sources(seal, repo)
    plan = RUN.read(repo / RUN.PLAN)
    RUN.validate_plan(plan)
    records = RUN.load_records(plan)
    qualified = RUN.qualification(qualification, seal, plan)
    start, end = RUN.read(bundle / "STARTED.json"), RUN.read(bundle / "FINISHED.json")
    require(start["seal"] == seal and start["plan"] == plan, "Dispatch seal/plan")
    require(start["qualification"] == qualified, "Dispatch qualification binding")
    require(
        end["status"] == "INCOMPLETE_NO_RETRY"
        and end["completed_roles"] == [COMPLETE]
        and end["error"] == DISPATCH_ERROR,
        "Stopped dispatch receipt",
    )
    require(all(end[k] == v for k, v in RUN.CEILING.items()), "Dispatch ceiling")
    VERIFY.verify_manifest(bundle, end["files"])
    require(
        sorted(p.name for p in bundle.glob("DISPATCH_*.json"))
        == [f"DISPATCH_{STOPPED}.json", f"DISPATCH_{COMPLETE}.json"]
        and not any((bundle / name).exists() for name in ("ordered_cap100", "replay"))
        and not (bundle / "COMPARISONS.json").exists(),
        "No later role, retry or comparison",
    )
    roles = {COMPLETE: VERIFY.verify_role(bundle / COMPLETE, COMPLETE, seal, plan, qualified)}
    stopped_start = RUN.read(bundle / STOPPED / "STARTED.json")
    stopped_end = RUN.read(bundle / STOPPED / "FINISHED.json")
    require(stopped_start["role"] == stopped_end["role"] == STOPPED, "Stopped role identity")
    require(
        stopped_start["seal"] == seal
        and stopped_start["plan"] == plan
        and stopped_start["qualification"] == qualified,
        "Stopped role binding",
    )
    require(
        stopped_end["status"] == "INCOMPLETE_NO_RETRY" and stopped_end["error"] == STOP_ERROR,
        "Stopped role reason",
    )
    require(all(stopped_end[k] == v for k, v in RUN.CEILING.items()), "Stopped role ceiling")
    VERIFY.verify_manifest(bundle / STOPPED, stopped_end["files"])
    require(roles[COMPLETE][0]["pid"] != stopped_start["pid"], "Distinct processes")
    schedule_ids = [window_id for window_id, _ in RUN.schedule_rows(plan, records["train"])]
    endpoint, curve, _, lines = VERIFY.verify_arm(
        bundle / COMPLETE,
        {**plan, "checkpoint_steps": []},
        records,
        summarize,
        schedule_ids,
        checkpoints,
    )
    receipts = verify_receipts(VERIFY, bundle / COMPLETE, plan["checkpoint_steps"], checkpoints)
    stopped_curve, missing, stopped_receipts = verify_stopped_arm(
        VERIFY, bundle / STOPPED, plan, records, summarize, schedule_ids, checkpoints
    )
    # The selection pair is matched: contracts differ only by the declared query
    # policy and identical initial trainable state.
    contracts = {a: RUN.read(bundle / a / "CONTEXT.json")["contract"] for a in (COMPLETE, STOPPED)}
    require(
        {k for k in contracts[COMPLETE] if contracts[COMPLETE][k] != contracts[STOPPED][k]}
        == {"condition", RUN.workspace_key()},
        "Selection arms not matched",
    )
    initial = {
        a: RUN.read(bundle / a / "INITIAL.json")["light"]["bridge_state"]
        for a in (COMPLETE, STOPPED)
    }
    require(initial[COMPLETE] == initial[STOPPED], "Selection arms start from different states")
    return {
        "status": "OFFLINE_V19_FROZEN_ATTEMPT01_STOPPED_RECEIPT_PASS",
        "source_commit": seal["source_commit"],
        "source_files": len(seal["source_hashes"]),
        "dispatch": {
            "status": end["status"],
            "completed_roles": end["completed_roles"],
            "error": end["error"],
            "not_dispatched": ["ordered_cap100", "replay"],
            "comparisons": "NOT_COMPUTABLE",
        },
        COMPLETE: {
            "status": roles[COMPLETE][1]["status"],
            "verdict": endpoint["verdict"],
            "endpoint": {
                k: endpoint[k]
                for k in (
                    "flips",
                    "world_sign",
                    "sign_test_p",
                    "flip_margin_over_chance",
                    "unaffected_prediction_changes",
                    "accuracy_by_wording",
                )
            },
            "curve": curve,
            "checkpoints": receipts,
            "windows": len(lines),
        },
        STOPPED: {
            "status": stopped_end["status"],
            "error": stopped_end["error"],
            "stop_observation": stop_observation(require, bundle / STOPPED),
            "windows_completed": plan["schedule"]["updates"],
            "missing_evaluations": missing,
            "endpoint": "MISSING_NOT_ZERO",
            "curve": stopped_curve,
            "checkpoints": stopped_receipts,
        },
        "checkpoint_bodies_rehashed": checkpoints is not None,
        "resources": {
            role: {
                k: receipt.get(k)
                for k in (
                    "elapsed_seconds",
                    "peak_cuda_allocated_bytes",
                    "peak_cuda_reserved_bytes",
                    "peak_process_rss_bytes",
                    "minimum_sampled_device_free_bytes",
                    "minimum_sampled_host_available_bytes",
                )
            }
            for role, receipt in ((COMPLETE, roles[COMPLETE][1]), (STOPPED, stopped_end))
        },
        "forward_calls": 0,
        **RUN.CEILING,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="clean checkout of 097d8dd")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--source-seal", type=Path, required=True)
    parser.add_argument("--checkpoints", type=Path)
    args = parser.parse_args()
    result = verify(
        args.repo.resolve(),
        args.bundle,
        args.qualification,
        args.source_seal,
        checkpoints=args.checkpoints,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
