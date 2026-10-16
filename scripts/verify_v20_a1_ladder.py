#!/usr/bin/env python3
"""Offline receipt verification of V20 A1, the Availability ladder; no model execution.

Rehashes the sealed sources, both qualification bundles, the dispatch and every
role manifest; checks each extraction receipt against the V19 data shapes; and
re-derives every state's tests and verdict from the recorded per-world counts
with the plan's rule. Where the feature files are present (Furnace), it refits
every probe and requires ``LADDER.json`` to match exactly.
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
    "v20_a1_contract", Path(__file__).with_name("run_v20_a1_ladder.py")
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
        "scripts/verify_v20_a1_ladder.py",
        "scripts/run_v19_frozen_diagnostic.py",
        "src/latent_workspace/ladder.py",
        "src/latent_workspace/execution.py",
        "tests/test_v20_a1_ladder.py",
    }
    ex.require(needed <= set(seal["source_hashes"]), "Critical source missing from seal")
    for name, digest in seal["source_hashes"].items():
        path = repo / name
        ex.require(path.resolve().is_relative_to(repo.resolve()) and not path.is_symlink(), name)
        ex.require(ex.digest(path) == digest, f"Source content changed: {name}")


def rederive(result, alpha, primary):
    """The state's tests and verdict from recorded per-world counts alone."""
    from latent_workspace import ladder

    tests = []
    for probe, zero, shuffled in zip(
        *(result["memory"][k] for k in ("memory", "zero", "shuffled")), strict=True
    ):
        tests.append(
            dict(
                seed=probe["seed"],
                against_zero=ladder.sign_test(probe["world_counts"], zero["world_counts"]),
                against_shuffled=ladder.sign_test(probe["world_counts"], shuffled["world_counts"]),
            )
        )
    ex.require(tests == result["memory_tests"], "Memory sign tests")
    memory_pass = all(
        t["against_zero"]["p_one_sided"] <= alpha and t["against_shuffled"]["p_one_sided"] <= alpha
        for t in tests
    )
    for route, entry in result["reading"].items():
        ex.require(
            ladder.chance_sign_test(entry["world_counts"], 2) == entry["world_test"],
            f"Reading sign test: {route}",
        )
    reading_pass = result["reading"][primary]["world_test"]["p_one_sided"] <= alpha
    ex.require(
        memory_pass == result["memory_pass"] and reading_pass == result["reading_pass"],
        "Pass flags",
    )
    verdict = ladder.ladder_verdict(memory_pass, reading_pass)
    ex.require(verdict == result["verdict"], "Verdict")
    return verdict


def verify_results(bundle, plan, roles, refit):
    """Content checks; ``roles`` maps role -> (STARTED, FINISHED, complete manifest)."""
    plan19 = ex.read(ROOT / plan["v19"]["plan"])
    worlds = {split: plan19["data"][split]["world_pairs"] for split in RUN.SPLITS}
    conditions = len(plan["conditions"])
    for state in RUN.STATES:
        role = f"extract_{state}"
        outcome = roles[role][1]["outcome"]
        ex.require(outcome["state"] == state, f"{role} state")
        for split in RUN.SPLITS:
            shapes = outcome["splits"][split]
            ex.require(
                shapes["memory"][:2] == [worlds[split], conditions]
                and shapes["common"][:3] == [worlds[split], 8, conditions]
                and shapes["interaction"] == shapes["common"]
                and shapes["query_common"][:2] == [worlds[split], 8],
                f"{role} {split} shapes",
            )
            rows = ex.read_gz(bundle / role / f"ROWS_{split}.json.gz")
            ex.require(
                len(rows) == 8 * worlds[split]
                and sum(r["affected"] for r in rows) == 2 * worlds[split],
                f"{role} {split} rows",
            )
    ladder_json = ex.read(bundle / "probe" / "LADDER.json")
    verdicts = {
        state: rederive(
            ladder_json[state], plan["endpoints"]["alpha"], plan["probes"]["primary_route"]
        )
        for state in RUN.STATES
    }
    ex.require(roles["probe"][1]["outcome"] == verdicts, "Probe outcome")
    refitted = False
    if refit and all(roles[f"extract_{s}"][2] for s in RUN.STATES):
        for state in RUN.STATES:
            features, rows = RUN.load_features(bundle / f"extract_{state}")
            again = RUN.ladder_for_state(features, rows, plan["probes"], plan["endpoints"]["alpha"])
            ex.require(
                json.loads(json.dumps(again)) == ladder_json[state], f"Refit differs: {state}"
            )
        refitted = True
    return dict(verdicts=verdicts, ladder=ladder_json, probes_refitted=refitted)


def verify(bundle, qualification, seal_path, repo=ROOT, refit=False):
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
    roles = {}
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
        complete = verify_manifest(bundle / role, role_end["files"])
        roles[role] = (role_start, role_end, complete)
    ex.require(len({r[0]["pid"] for r in roles.values()}) == len(roles), "Distinct processes")
    result = verify_results(bundle, plan, roles, refit)
    ex.require(end["summary"] == result["verdicts"], "Dispatch summary")
    return {
        "status": "OFFLINE_V20_A1_LADDER_RECEIPT_PASS",
        "source_commit": seal["source_commit"],
        "source_files": len(seal["source_hashes"]),
        **result,
        "elapsed_seconds": {role: roles[role][1]["elapsed_seconds"] for role in roles},
        **ex.CEILING,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--source-seal", type=Path, required=True)
    parser.add_argument("--refit", action="store_true")
    args = parser.parse_args()
    result = verify(args.bundle, args.qualification, args.source_seal, refit=args.refit)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
