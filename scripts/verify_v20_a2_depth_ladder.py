#!/usr/bin/env python3
"""Offline receipt verification of V20 A2, the depth ladder; no model execution.

Rehashes the sealed sources, both qualification bundles, the dispatch and every role
manifest (feature files may be absent away from Furnace). Checks every cut's
extraction against the data's world counts and conditions, that every route started
exactly at the host's own logits, and the fresh-process replay. Then recomputes
every cut's verdicts from the saved scores with the runner's own function and
requires ``ENDPOINTS.json`` and the dispatch summary to match exactly.
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
    "v20_a2_depth_contract", Path(__file__).with_name("run_v20_a2_depth_ladder.py")
)
RUN = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RUN)
ex = RUN.ex
LARGE = re.compile(r"(^|/)FEATURES_[a-z]+\.safetensors$")


def verify_manifest(folder, expected):
    """Every listed file must match; only large feature files may be absent."""
    actual = ex.manifest(folder)
    actual.pop("FINISHED.json", None)
    for name in expected:
        pure = PurePosixPath(name)
        ex.require(str(pure) == name and not pure.is_absolute() and ".." not in pure.parts, name)
    missing = sorted(set(expected) - set(actual))
    ex.require(all(LARGE.search(name) for name in missing), f"Missing receipts: {missing}")
    ex.require(set(actual) <= set(expected), f"Unlisted files in {folder}")
    ex.require(all(actual[n] == expected[n] for n in actual), f"Manifest mismatch: {folder}")
    return not missing


def verify_sources(seal, repo):
    ex.require(set(seal) == {"source_commit", "source_hashes"}, "Seal schema")
    ex.require(re.fullmatch(r"[0-9a-f]{40}", seal["source_commit"]) is not None, "Seal commit")
    needed = {
        RUN.ENTRY,
        RUN.PLAN,
        "scripts/run_source_sealed.py",
        "scripts/verify_v20_a2_depth_ladder.py",
        "src/latent_workspace/availability.py",
        "src/latent_workspace/composition.py",
        "src/latent_workspace/cuts.py",
        "src/latent_workspace/execution.py",
        "src/latent_workspace/host.py",
        "src/latent_workspace/training.py",
        "tests/test_v20_a2_depth_ladder.py",
    }
    ex.require(needed <= set(seal["source_hashes"]), "Critical source missing from seal")
    for name, digest in seal["source_hashes"].items():
        path = repo / name
        ex.require(path.resolve().is_relative_to(repo.resolve()) and not path.is_symlink(), name)
        ex.require(ex.digest(path) == digest, f"Source content changed: {name}")


def verify_results(bundle, plan, roles):
    """Content checks; ``roles`` maps role -> (STARTED, FINISHED, complete manifest)."""
    worlds = {split: plan["data"][split]["world_pairs"] for split in RUN.SPLITS}
    expected = {"train": worlds["train"] * 16, "final": worlds["final"] * 8 * len(RUN.CONDITIONS)}
    host_final = {}
    for cut in RUN.CUTS:
        folder = bundle / f"extract_cut{cut}"
        for split in RUN.SPLITS:
            meta = ex.read_gz(folder / f"ROWS_{split}.json.gz")
            scores = ex.read_gz(folder / f"HOST_SCORES_{split}.json.gz")
            ex.require(len(meta) == len(scores) == expected[split], f"cut {cut} {split} rows")
            if split == "final":
                counts = {c: sum(m["condition"] == c for m in meta) for c in RUN.CONDITIONS}
                ex.require(set(counts.values()) == {worlds["final"] * 8}, f"cut {cut} conditions")
                host_final[cut] = scores
        questions = ex.read_gz(folder / "QUESTIONS_final.json.gz")
        ex.require(len(questions) == worlds["final"] * 8, f"cut {cut} questions")
    step = plan["training"]["updates"]
    for role in RUN.ARM_ROLES:
        cut, _ = RUN.parse_role(plan, role)
        for arm in RUN.ARMS:
            start = ex.read_gz(bundle / role / f"eval_{arm}_final_step0.json.gz")["adapted_logits"]
            ex.require(start == host_final[cut], f"{role} {arm}: step 0 is not the host")
            ex.read_gz(bundle / role / f"eval_{arm}_final_step{step}.json.gz")
    rule = plan["replay"]
    source = f"route_cut{rule['cut']}_s{plan['seeds'].index(rule['seed']) + 1}"
    replay = ex.read(bundle / "replay" / "REPLAY.json")
    fingerprints = ex.read(bundle / source / "FINGERPRINTS.json")[rule["arm"]]
    checkpoint = ex.read(bundle / source / f"CHECKPOINT_{rule['arm']}_step{rule['from_step']}.json")
    ex.require(
        replay["exact"]
        and replay["role"] == source
        and replay["replayed_fingerprint"] == fingerprints[str(rule["execute_step"])]
        and replay["restored_fingerprint"] == checkpoint["fingerprint"]
        and replay["update"] == replay["original_update"],
        "Replay",
    )
    recomputed = json.loads(json.dumps(RUN.endpoints_for(bundle, plan)))
    ex.require(recomputed == ex.read(bundle / "endpoints" / "ENDPOINTS.json"), "Endpoints differ")
    outcome = RUN.outcome_of(recomputed)
    ex.require(roles["endpoints"][1]["outcome"] == outcome, "Endpoint outcome")
    return dict(verdicts=outcome, endpoints=recomputed)


def verify(bundle, qualification, seal_path, repo=ROOT):
    sys.path.insert(0, str(repo / "src"))
    seal = ex.read(seal_path)
    verify_sources(seal, repo)
    plan = ex.read(repo / RUN.PLAN)
    RUN.validate_plan(plan)
    qualified = RUN.RUN.qualification(qualification, seal, plan)
    start, end = ex.read(bundle / "STARTED.json"), ex.read(bundle / "FINISHED.json")
    ex.require(start["seal"] == seal and start["plan"] == plan, "Dispatch seal/plan")
    ex.require(start["qualification"] == qualified, "Dispatch qualification binding")
    ex.require(
        end["status"] == plan["pass_status"] and end["completed_roles"] == list(RUN.ROLES),
        "Dispatch",
    )
    ex.require(all(end[k] == v for k, v in ex.CEILING.items()), "Dispatch ceiling")
    verify_manifest(bundle, end["files"])
    roles, complete = {}, True
    for role in RUN.ROLES:
        role_start = ex.read(bundle / role / "STARTED.json")
        role_end = ex.read(bundle / role / "FINISHED.json")
        ex.require(role_start["role"] == role_end["role"] == role, f"{role} identity")
        ex.require(role_start["seal"] == seal and role_start["plan"] == plan, f"{role} seal/plan")
        ex.require(role_start["qualification"] == qualified, f"{role} qualification")
        ex.require(
            role_end["status"] == RUN.RUN.role_status[role], f"{role}: {role_end.get('error')}"
        )
        ex.require(all(role_end[k] == v for k, v in ex.CEILING.items()), f"{role} ceiling")
        complete &= verify_manifest(bundle / role, role_end["files"])
        roles[role] = (role_start, role_end, complete)
    ex.require(len({r[0]["pid"] for r in roles.values()}) == len(roles), "Distinct processes")
    result = verify_results(bundle, plan, roles)
    ex.require(end["summary"] == result["verdicts"], "Dispatch summary")
    return {
        "status": "OFFLINE_V20_A2_DEPTH_LADDER_RECEIPT_PASS",
        "source_commit": seal["source_commit"],
        "source_files": len(seal["source_hashes"]),
        "features_rehashed": complete,
        "verdicts": result["verdicts"],
        "endpoints": result["endpoints"],
        "elapsed_seconds": {role: roles[role][1]["elapsed_seconds"] for role in roles},
        **ex.CEILING,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--source-seal", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.bundle, args.qualification, args.source_seal)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
