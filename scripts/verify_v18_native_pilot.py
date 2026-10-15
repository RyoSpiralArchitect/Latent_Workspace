#!/usr/bin/env python3
"""Offline source/receipt verification of the V18 native pilot; no model execution.

Rehashes the sealed sources, both tiny qualification bundles, the dispatch and
every role manifest; recomputes the V16 probe comparison, the fresh-process
replay equality and the evaluation summaries from saved records. Checkpoint
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
    "v18_native_pilot_contract", Path(__file__).with_name("run_v18_native_pilot.py")
)
RUN = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RUN)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"Duplicate JSON field in {path}")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"Nonfinite JSON in {path}: {value}")

    return json.loads(Path(path).read_text(), object_pairs_hook=unique, parse_constant=invalid)


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
        "scripts/run_source_sealed.py",
        "scripts/verify_v18_native_pilot.py",
        RUN.PLAN,
        "tests/test_v18_native_pilot.py",
        "src/latent_workspace_ft_v10/v18_native_eval.py",
    }
    require(needed <= set(seal["source_hashes"]), "Critical source missing from seal")
    core = RUN.load("run_v16_adapter_migration")
    for name, digest in seal["source_hashes"].items():
        path = repo / name
        require(path.resolve().is_relative_to(repo.resolve()) and not path.is_symlink(), name)
        require(core.digest(path) == digest, f"Source content changed: {name}")


def verify_role(bundle, role, seal, plan, qualified):
    start, end = read(bundle / "STARTED.json"), read(bundle / "FINISHED.json")
    require(start["role"] == end["role"] == role, f"{role} identity")
    require(start["seal"] == seal and start["plan"] == plan, f"{role} seal/plan")
    require(start["qualification"] == qualified, f"{role} qualification binding")
    require(end["status"] == RUN.ROLE_PASS[role], f"{role} did not pass: {end.get('error')}")
    require(all(end[k] == v for k, v in RUN.CEILING.items()), f"{role} ceiling")
    verify_manifest(bundle, end["files"])
    return start, end


def condition_table(summary):
    return {
        name: {
            k: summary["conditions"][name][k]
            for k in (
                "labelled_n",
                "correct",
                "ties",
                "regressions_from_original",
                "repairs_from_original",
            )
        }
        for name in ("intact", "twin", "reverse_intact", "reverse_twin")
    }


def verify(bundle, qualification, seal_path, repo=ROOT, checkpoints=None):
    sys.path.insert(0, str(repo / "src"))
    from latent_workspace_ft_v10.v16_comparison_eval import summarize

    seal = read(seal_path)
    verify_sources(seal, repo)
    plan = read(repo / RUN.PLAN)
    RUN.validate_plan(plan)
    qualified = RUN.qualification(qualification, seal, plan)
    start, end = read(bundle / "STARTED.json"), read(bundle / "FINISHED.json")
    require(start["seal"] == seal and start["plan"] == plan, "Dispatch seal/plan")
    require(start["qualification"] == qualified, "Dispatch qualification binding")
    require(end["status"] == RUN.PASS and end["completed_roles"] == list(RUN.ROLES), "Dispatch")
    require(all(end[k] == v for k, v in RUN.CEILING.items()), "Dispatch ceiling")
    verify_manifest(bundle, end["files"])
    roles = {role: verify_role(bundle / role, role, seal, plan, qualified) for role in RUN.ROLES}
    pids = {roles[r][1]["outcome"].get("replay_pid") for r in ("replay",)}
    starts = [roles[r][0]["pid"] for r in RUN.ROLES]
    require(len(set(starts)) == 3, "Each role must be a distinct process")

    # Probe: recompute every V16 comparison from the saved records.
    probe = bundle / "probe"
    comparator = repo / plan["probe"]["comparator"]
    old_context = read(comparator / "CONTEXT.json")
    context = read(probe / "CONTEXT.json")
    checks = {
        "original_base_sha256": context["contract"]["original_base_sha256"]
        == old_context["contract"]["original_base_sha256"],
        "preparation": RUN.same(
            context["contract"]["preparation"], old_context["contract"]["preparation"]
        ),
        "binding": RUN.same(context["binding"], old_context["binding"]),
        "features": RUN.same(context["features"], old_context["features"]),
        "initial_state": RUN.same(read(probe / "INITIAL.json"), read(comparator / "INITIAL.json")),
        "window": RUN.compare_v16_window(
            read(probe / "probe_step1.json"), read(comparator / "step1.json")
        ),
    }
    require(RUN.all_true(checks), "Offline probe recomputation differs from V16")
    require(RUN.same(read(probe / "PROBE.json")["checks"], checks), "Saved probe checks differ")

    # Primary: windows, evaluations, checkpoint receipts.
    primary = bundle / "primary"
    p_context = read(primary / "CONTEXT.json")
    require(
        p_context["contract"]["v18_selection_policy"]["interaction_query"]
        == plan["condition"]["interaction_query"],
        "Primary interaction query",
    )
    require(
        p_context["contract"]["original_base_sha256"]
        == context["contract"]["original_base_sha256"],
        "Primary original base",
    )
    windows, evaluations, receipts = [], [], []
    for step in plan["evaluation_steps"]:
        report = read(primary / f"evaluation_step{step}.json")
        require(report["step"] == step and report["rng_unchanged"], f"Evaluation {step}")
        require(report["owned_state_fingerprint_unchanged"] is True, f"Evaluation {step} state")
        require(
            len(report["rows"]) == plan["evaluation_rows_per_step"]
            and len(report["direct_base"]) == plan["direct_base_rows_per_step"]
            and len(report["contrasts"]) == plan["factor_rows_per_step"],
            "Eval counts",
        )
        require(RUN.same(summarize(report), report["summary"]), f"Summary {step} recomputation")
        evaluations.append(report)
    for step in plan["steps"]:
        window = read(primary / f"step{step}.json")
        require(window["update"]["completed_step"] == step, f"Window {step}")
        require(window["window"]["window_id"] == plan["condition"]["window_ids"][step - 1], "ID")
        require(len(window["pairs"]) == 16, f"Window {step} pairs")
        pairs = [json.loads(line) for line in (primary / f"step{step}_pairs.jsonl").open()]
        require(RUN.same(pairs, window["pairs"]), f"Pair journal {step}")
        receipt = read(primary / f"CHECKPOINT_step{step}.json")
        require(
            receipt["completed_steps"] == step
            and receipt["format"] == "v18-selection-window-reference-resume-v1",
            f"Checkpoint {step}",
        )
        if checkpoints is not None:
            path = checkpoints / "primary" / receipt["path"]
            core = RUN.load("run_v16_adapter_migration")
            require(
                path.stat().st_size == receipt["bytes"] and core.digest(path) == receipt["sha256"],
                f"Checkpoint {step} bytes",
            )
        windows.append(window)
        receipts.append(receipt)

    # Replay: fresh process, exact window and serialized state.
    replay = bundle / "replay"
    report = read(replay / "REPLAY.json")
    require(RUN.same(read(replay / "replay_step2.json"), windows[1]), "Replay window differs")
    require(
        report["exact"] is True and report["state_sha256"] == receipts[1]["state_sha256"],
        "Replay state",
    )
    require(
        report["primary_pid"] == roles["primary"][0]["pid"]
        and report["replay_pid"] == roles["replay"][0]["pid"]
        and report["primary_pid"] != report["replay_pid"],
        "Replay process identity",
    )
    require(pids == {roles["replay"][0]["pid"]}, "Replay outcome identity")
    parity = read(primary / "STEP0_V16_EVALUATION_PARITY.json")
    return {
        "status": "OFFLINE_V18_NATIVE_PILOT_RECEIPT_PASS",
        "source_commit": seal["source_commit"],
        "source_files": len(seal["source_hashes"]),
        "probe_exact_v16_parity": True,
        "probe_compared_pairs": len(read(probe / "probe_step1.json")["pairs"]),
        "replay_exact": True,
        "checkpoint_bodies_rehashed": checkpoints is not None,
        "step0_v16_evaluation_parity": parity["checks"],
        "conditions_by_step": {str(r["step"]): condition_table(r["summary"]) for r in evaluations},
        "factors_by_step": {str(r["step"]): r["summary"]["factors"] for r in evaluations},
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
        "checkpoints": receipts,
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
