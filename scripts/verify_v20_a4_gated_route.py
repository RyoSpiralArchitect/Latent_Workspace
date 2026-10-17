#!/usr/bin/env python3
"""Offline receipt verification of V20 A4, the content-gated cut-4 route; no model execution.

Rehashes the sealed sources, both qualification bundles, the dispatch, every role manifest
(feature files may be absent away from Furnace) and the ladder files the run pinned. Checks
that every mismatch row follows the plan's rule on the pinned training data and aligns with
the ladder's train rows, that every gated route started exactly at the host's logits, the
bitwise reproduction of the ladder's ungated route and the fresh-process replay. Then
recomputes the verdicts from the saved scores with the runner's own function and requires
``ENDPOINTS.json`` and the dispatch summary to match exactly.
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
    "v20_a4_gated_contract", Path(__file__).with_name("run_v20_a4_gated_route.py")
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
        "scripts/run_v20_a2_depth_ladder.py",
        "scripts/verify_v20_a4_gated_route.py",
        "src/latent_workspace/availability.py",
        "src/latent_workspace/composition.py",
        "src/latent_workspace/cuts.py",
        "src/latent_workspace/execution.py",
        "src/latent_workspace/host.py",
        "src/latent_workspace/training.py",
        "tests/test_v20_a4_gated_route.py",
    }
    ex.require(needed <= set(seal["source_hashes"]), "Critical source missing from seal")
    for name, digest in seal["source_hashes"].items():
        path = repo / name
        ex.require(path.resolve().is_relative_to(repo.resolve()) and not path.is_symlink(), name)
        ex.require(ex.digest(path) == digest, f"Source content changed: {name}")


def train_records(plan, repo):
    entry = plan["data"]["train"]
    path = repo / entry["path"]
    ex.require(ex.digest(path) == entry["sha256"], "Train data changed")
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    ex.require(len(records) == entry["world_pairs"], "Train worlds")
    return records


def verify_results(bundle, ladder, plan, roles, records):
    """Content checks; ``roles`` maps role -> (STARTED, FINISHED, complete manifest)."""
    RUN.verify_ladder(ladder, plan, features=False)
    rehashed = all((ladder / name).exists() for name in plan["source"]["features"])
    if rehashed:
        RUN.verify_pinned(ladder, plan["source"]["features"])
    source = ladder / f"extract_cut{RUN.CUT}"
    own = ex.read_gz(source / "ROWS_train.json.gz")
    folder = bundle / "extract_mismatch"
    meta = ex.read_gz(folder / "ROWS_mismatch.json.gz")
    scores = ex.read_gz(folder / "HOST_SCORES_mismatch.json.gz")
    rows = plan["data"]["train"]["world_pairs"] * 16
    ex.require(len(meta) == len(own) == len(scores) == rows, "Mismatch rows")
    keys = ("question", "world", "query", "side", "label")
    for row, stored in zip(meta, own, strict=True):
        ex.require(all(row[k] == stored[k] for k in keys), "Mismatch rows are not aligned")
        chosen = RUN.mismatch_world(records, row["world"], row["query"], plan["mismatch"]["stride"])
        ex.require((row["mismatch_world"], row["stride_steps"]) == chosen, "Mismatch rule")
    host_final = ex.read_gz(source / "HOST_SCORES_final.json.gz")
    step = plan["training"]["updates"]
    for role in RUN.ARM_ROLES:
        start = ex.read_gz(bundle / role / f"eval_{RUN.ARM}_final_step0.json.gz")["adapted_logits"]
        ex.require(start == host_final, f"{role}: step 0 is not the host")
        ex.read_gz(bundle / role / f"eval_{RUN.ARM}_final_step{step}.json.gz")
    reproduce = ex.read(bundle / "reproduce" / "REPRODUCE.json")
    ex.require(
        reproduce["exact"]
        and reproduce["receipts_equal"]
        and reproduce["scores_equal"]
        and reproduce["fingerprint"] == reproduce["expected_fingerprint"]
        and reproduce["fingerprint"] == plan["reproduce"]["fingerprint"],
        "Reproduction",
    )
    rule = plan["replay"]
    role = f"gated_s{plan['seeds'].index(rule['seed']) + 1}"
    replay = ex.read(bundle / "replay" / "REPLAY.json")
    fingerprints = ex.read(bundle / role / "FINGERPRINTS.json")[RUN.ARM]
    checkpoint = ex.read(bundle / role / f"CHECKPOINT_{RUN.ARM}_step{rule['from_step']}.json")
    ex.require(
        replay["exact"]
        and replay["role"] == role
        and replay["replayed_fingerprint"] == fingerprints[str(rule["execute_step"])]
        and replay["restored_fingerprint"] == checkpoint["fingerprint"]
        and replay["update"] == replay["original_update"],
        "Replay",
    )
    recomputed = json.loads(json.dumps(RUN.endpoints_for(bundle, ladder, plan)))
    ex.require(recomputed == ex.read(bundle / "endpoints" / "ENDPOINTS.json"), "Endpoints differ")
    outcome = RUN.outcome_of(recomputed)
    ex.require(roles["endpoints"][1]["outcome"] == outcome, "Endpoint outcome")
    RUN.check_comparator(outcome, plan)
    return dict(verdicts=outcome, endpoints=recomputed, ladder_features_rehashed=rehashed)


def verify(bundle, ladder, qualification, seal_path, repo=ROOT):
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
    result = verify_results(bundle, ladder, plan, roles, train_records(plan, repo))
    ex.require(end["summary"] == result["verdicts"], "Dispatch summary")
    return {
        "status": "OFFLINE_V20_A4_GATED_ROUTE_RECEIPT_PASS",
        "source_commit": seal["source_commit"],
        "source_files": len(seal["source_hashes"]),
        "features_rehashed": complete,
        "ladder_features_rehashed": result["ladder_features_rehashed"],
        "verdicts": result["verdicts"],
        "endpoints": result["endpoints"],
        "elapsed_seconds": {role: roles[role][1]["elapsed_seconds"] for role in roles},
        **ex.CEILING,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--ladder-bundle", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--source-seal", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.bundle, args.ladder_bundle, args.qualification, args.source_seal)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
