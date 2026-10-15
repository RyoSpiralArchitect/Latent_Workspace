#!/usr/bin/env python3
"""Offline receipt verification of the V18 frozen diagnostic; no model execution.

Rehashes the sealed sources, both qualification bundles, the dispatch and every
role manifest. Recomputes every evaluation summary and pre-registered diagnosis
from the saved gzip records, the cross-arm selection comparison, the schedule,
the frozen-backbone identity and the fresh-process replay equality. Checkpoint
bodies are rehashed only when their directory is supplied.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "v18_frozen_diagnostic_contract", Path(__file__).with_name("run_v18_frozen_diagnostic.py")
)
RUN = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RUN)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def verify_manifest(folder, expected):
    actual = RUN.manifest(folder)
    actual.pop("FINISHED.json", None)
    for name in expected:
        pure = PurePosixPath(name)
        require(str(pure) == name and not pure.is_absolute() and ".." not in pure.parts, name)
    require(actual == expected, f"Artifact bytes/manifest mismatch: {folder}")


def verify_sources(seal, repo):
    require(set(seal) == {"source_commit", "source_hashes"}, "Seal schema")
    require(re.fullmatch(r"[0-9a-f]{40}", seal["source_commit"]) is not None, "Seal commit")
    needed = {
        RUN.ENTRY,
        RUN.PLAN,
        "scripts/run_source_sealed.py",
        "scripts/verify_v18_frozen_diagnostic.py",
        "scripts/run_v18_native_pilot.py",
        "tests/test_v18_frozen_diagnostic.py",
        "src/latent_workspace_ft_v10/v18_native_eval.py",
    }
    require(needed <= set(seal["source_hashes"]), "Critical source missing from seal")
    for name, digest in seal["source_hashes"].items():
        path = repo / name
        require(path.resolve().is_relative_to(repo.resolve()) and not path.is_symlink(), name)
        require(RUN.digest(path) == digest, f"Source content changed: {name}")


def verify_role(bundle, role, seal, plan, qualified):
    start, end = RUN.read(bundle / "STARTED.json"), RUN.read(bundle / "FINISHED.json")
    require(start["role"] == end["role"] == role, f"{role} identity")
    require(start["seal"] == seal and start["plan"] == plan, f"{role} seal/plan")
    require(start["qualification"] == qualified, f"{role} qualification binding")
    require(end["status"] == RUN.ROLE_PASS[role], f"{role} did not pass: {end.get('error')}")
    require(all(end[k] == v for k, v in RUN.CEILING.items()), f"{role} ceiling")
    verify_manifest(bundle, end["files"])
    return start, end


def verify_arm(bundle, plan, records, summarize, schedule_ids, checkpoints):
    same = RUN.pilot().same
    context = RUN.read(bundle / "CONTEXT.json")
    initial, final_state = RUN.read(bundle / "INITIAL.json"), RUN.read(bundle / "FINAL_STATE.json")
    require(context["contract"]["full_update"] is False, "Frozen contract")
    require(
        initial["native_sha256"]
        == final_state["native_sha256"]
        == context["contract"]["original_base_sha256"]
        and final_state["native_unchanged"] is True,
        "Frozen backbone identity",
    )
    lines = (bundle / "windows.jsonl").read_text().splitlines()
    require(len(lines) == plan["schedule"]["updates"], "Window journal length")
    for step, line in enumerate(lines, start=1):
        window = json.loads(line)
        require(
            window["update"]["completed_step"] == step
            and window["window_id"] == schedule_ids[step - 1]
            and window["update"]["base_changes"] == []
            and len(window["pairs"]) == plan["schedule"]["occurrences_per_window"],
            f"Window {step} receipt",
        )
    curve = {}
    for split, steps in (
        ("dev", plan["dev_evaluation_steps"]),
        ("final", plan["final_evaluation_steps"]),
    ):
        for step in steps:
            report = RUN.read_gz(bundle / f"eval_{split}_step{step}.json.gz")
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
            if split == "final" and step == plan["endpoints"]["step"]:
                endpoint = diagnosis
    require(same(RUN.read(bundle / "DIAGNOSIS.json"), endpoint), "Endpoint diagnosis file")
    receipts = []
    for step in plan["checkpoint_steps"]:
        receipt = RUN.read(bundle / f"CHECKPOINT_step{step}.json")
        require(
            receipt["completed_steps"] == step
            and receipt["format"] == "v18-selection-window-reference-resume-v1",
            f"Checkpoint {step}",
        )
        if checkpoints is not None:
            path = checkpoints / context["contract"]["condition"] / receipt["path"]
            require(
                path.stat().st_size == receipt["bytes"] and RUN.digest(path) == receipt["sha256"],
                f"Checkpoint {step} bytes",
            )
        receipts.append(receipt)
    return endpoint, curve, receipts, lines


def verify(bundle, qualification, seal_path, repo=ROOT, checkpoints=None):
    sys.path.insert(0, str(repo / "src"))
    from latent_workspace_ft_v10.v16_comparison_eval import summarize

    seal = RUN.read(seal_path)
    verify_sources(seal, repo)
    plan = RUN.read(repo / RUN.PLAN)
    RUN.validate_plan(plan)
    records = RUN.load_records(plan)
    qualified = RUN.qualification(qualification, seal, plan)
    start, end = RUN.read(bundle / "STARTED.json"), RUN.read(bundle / "FINISHED.json")
    require(start["seal"] == seal and start["plan"] == plan, "Dispatch seal/plan")
    require(start["qualification"] == qualified, "Dispatch qualification binding")
    require(end["status"] == RUN.PASS and end["completed_roles"] == list(RUN.ROLES), "Dispatch")
    require(all(end[k] == v for k, v in RUN.CEILING.items()), "Dispatch ceiling")
    verify_manifest(bundle, end["files"])
    roles = {role: verify_role(bundle / role, role, seal, plan, qualified) for role in RUN.ROLES}
    require(len({roles[r][0]["pid"] for r in RUN.ROLES}) == len(RUN.ROLES), "Distinct processes")
    schedule_ids = [window_id for window_id, _ in RUN.schedule_rows(plan, records["train"])]
    arms = {}
    for arm in RUN.ARMS:
        arms[arm] = verify_arm(bundle / arm, plan, records, summarize, schedule_ids, checkpoints)
    # Matched arms: identical initial trainable state, contracts differing only by policy.
    ordered_context = RUN.read(bundle / "centered_ordered" / "CONTEXT.json")["contract"]
    final_context = RUN.read(bundle / "centered_final" / "CONTEXT.json")["contract"]
    require(
        {k for k in ordered_context if ordered_context[k] != final_context[k]}
        == {"condition", "v18_selection_policy"},
        "Arm contracts not matched",
    )
    require(
        RUN.read(bundle / "centered_ordered" / "INITIAL.json")["light"]["bridge_state"]
        == RUN.read(bundle / "centered_final" / "INITIAL.json")["light"]["bridge_state"],
        "Arm initial workspace states differ",
    )
    selection = RUN.compare_arms(
        arms["centered_ordered"][0],
        arms["centered_final"][0],
        plan["endpoints"]["selection_comparison"],
    )
    require(RUN.pilot().same(RUN.read(bundle / "SELECTION.json"), selection), "Selection file")
    require(
        end["selection"] == selection["label"]
        and end["verdicts"] == {a: arms[a][0]["verdict"] for a in RUN.ARMS},
        "Dispatch result",
    )
    replay = RUN.read(bundle / "replay" / "REPLAY.json")
    rule = plan["replay"]
    expected = json.loads(arms[rule["arm"]][3][rule["execute_step"] - 1])
    require(
        RUN.pilot().same(RUN.read(bundle / "replay" / "replay_window.json"), expected),
        "Replay window differs",
    )
    require(
        replay["exact"] is True
        and replay["arm"] == rule["arm"]
        and replay["arm_pid"] == roles[rule["arm"]][0]["pid"]
        and replay["replay_pid"] == roles["replay"][0]["pid"]
        and replay["arm_pid"] != replay["replay_pid"],
        "Replay identity",
    )
    return {
        "status": "OFFLINE_V18_FROZEN_DIAGNOSTIC_RECEIPT_PASS",
        "source_commit": seal["source_commit"],
        "source_files": len(seal["source_hashes"]),
        "verdicts": {arm: arms[arm][0]["verdict"] for arm in RUN.ARMS},
        "endpoints": {
            arm: {
                k: arms[arm][0][k]
                for k in (
                    "flips",
                    "world_sign",
                    "sign_test_p",
                    "flip_margin_over_chance",
                    "unaffected_prediction_changes",
                    "accuracy_by_wording",
                )
            }
            for arm in RUN.ARMS
        },
        "selection": selection,
        "curves": {arm: arms[arm][1] for arm in RUN.ARMS},
        "replay_exact": True,
        "checkpoints": {arm: arms[arm][2] for arm in RUN.ARMS},
        "checkpoint_bodies_rehashed": checkpoints is not None,
        "resources": {
            role: {
                k: roles[role][1].get(k)
                for k in (
                    "elapsed_seconds",
                    "peak_cuda_allocated_bytes",
                    "peak_cuda_reserved_bytes",
                    "peak_process_rss_bytes",
                    "minimum_sampled_device_free_bytes",
                    "minimum_sampled_host_available_bytes",
                )
            }
            for role in RUN.ROLES
        },
        "forward_calls": 0,
        **RUN.CEILING,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--source-seal", type=Path, required=True)
    parser.add_argument("--checkpoints", type=Path)
    args = parser.parse_args()
    result = verify(args.bundle, args.qualification, args.source_seal, checkpoints=args.checkpoints)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
