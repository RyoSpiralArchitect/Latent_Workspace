#!/usr/bin/env python3
"""Build the LTWS β package (rehearsal) from V20 A5's sealed records; no upload.

A5's runs saved scores and parameter fingerprints, not final route weights. This script
retrains each stable route on CPU exactly as A5's role did: A5's plan, the ladder's and
A4's pinned records, deterministic arithmetic. It then requires the parameter fingerprint
to equal A5's sealed record before exporting the route (engine ``package.export``). The
exported weights are therefore the sealed routes, bit for bit.

The package holds the routes and a descriptor, never the host's weights. Which member, or
their mean, a release would use, and whether there is a release at all, is Ryō's
decision.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
import run_v20_a5_stable_route as A5  # noqa: E402

LADDER = A5.LADDER
ex = A5.ex
NAME = "mistral-7b-instruct-v0.3-LTWS β"


def records(torch, ladder, a4, plan):
    """The ladder's train rows and A4's mismatch rows, rehashed and aligned."""
    A5.verify_records(ladder, a4, plan)
    source, folder = ladder / f"extract_cut{A5.CUT}", a4 / "extract_mismatch"
    train = LADDER.load_bank(torch, source, "train")
    mismatch = LADDER.load_bank(torch, folder, "mismatch")
    own = ex.read_gz(source / "ROWS_train.json.gz")
    other = ex.read_gz(folder / "ROWS_mismatch.json.gz")
    ex.require(
        [(m["question"], m["side"]) for m in own] == [(m["question"], m["side"]) for m in other]
        and torch.equal(train.offsets, mismatch.offsets),
        "Mismatch rows are not aligned with the train rows",
    )
    return train, mismatch


def retrain(torch, plan, seed, train, mismatch):
    from latent_workspace import training

    route, optimizer, config, named = A5.build(plan, seed)
    for step in range(1, config.updates + 1):
        training.update(route, None, optimizer, train, config, step, mismatch)
    return route.eval(), training.fingerprint(named)


def descriptor(plan, outcome):
    from latent_workspace import package

    backbone = plan["backbone"]
    return dict(
        name=NAME,
        status=(
            "PACKAGING REHEARSAL. Not a release candidate and not uploaded; whether and what to "
            "release is Ryō's decision under docs/v18/HF_RELEASE.md."
        ),
        host=dict(
            repository=backbone["repository"],
            revision=backbone["revision"],
            original_base_sha256=backbone["original_base_sha256"],
            layers=backbone["layers"],
            dtype=backbone["dtype"],
            frozen=True,
            weights="not included: load the pinned upstream revision, unchanged",
        ),
        memory=dict(
            cut=plan["cut"],
            text="canonical fact lines (engine package.canonical_facts), tokenized without "
            "special tokens",
            encoding="the memory alone through the host's layers below the cut; its states "
            "enter before the question's at the cut and the host's remaining layers continue",
        ),
        candidates=plan["candidates"],
        candidate_ids=plan["candidate_ids"],
        prompt=dict(
            instruction=package.INSTRUCTION,
            query_suffix=package.QUERY_SUFFIX,
            template="the tokenizer's native chat template, one user turn, generation prompt",
            source="V15 query-only rendering with the answer cue (scripts/v15_cue_contract.py)",
        ),
        route={k: plan["route"][k] for k in package.ROUTE_KEYS},
        training=dict(
            run="V20 A5 attempt 02 (source 14ddacf, plan 1b5ce8e9e6c9a818fc39222e9a9b80f3e7c0ab11"
            "e9add95dcf67c0f247a38d77)",
            data="train split, 256 world pairs (data/v10/functional_train.jsonl)",
            gating=plan["gating"]["weight"],
            schedule=plan["training"]["schedule"],
        ),
        evidence=dict(
            lane_a=outcome,
            records="provenance/pilots/v20_a5_stable_route_20261018/README.md",
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a5-raw", type=Path, required=True)
    parser.add_argument("--ladder-raw", type=Path, required=True)
    parser.add_argument("--a4-raw", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    from latent_workspace import package

    plan = ex.read(ROOT / A5.PLAN)
    A5.validate_plan(plan)
    torch = LADDER.cpu_runtime(plan)
    LADDER.load("run_v16_adapter_migration").load_runtime()
    train, mismatch = records(torch, args.ladder_raw, args.a4_raw, plan)
    outcome = ex.read(args.a5_raw / "endpoints" / "FINISHED.json")["outcome"]
    routes, report = {}, {}
    for index, seed in enumerate(plan["seeds"], 1):
        started = time.monotonic()
        recorded = ex.read(args.a5_raw / f"stable_s{index}" / "FINGERPRINTS.json")
        route, fingerprint = retrain(torch, plan, seed, train, mismatch)
        expected = recorded[A5.ARM][str(plan["training"]["updates"])]
        ex.require(fingerprint == expected, f"Seed {seed}: the retrained route differs from A5's")
        source = f"V20 A5 stable_s{index}, seed {seed}, update {plan['training']['updates']}"
        routes[f"s{index}"] = (route, source)
        report[f"s{index}"] = dict(
            seed=seed, fingerprint=fingerprint, seconds=round(time.monotonic() - started, 1)
        )
    written = package.export(args.out, routes, descriptor(plan, outcome))
    print(json.dumps(dict(members=report, package=str(args.out), name=written["name"])))


if __name__ == "__main__":
    main()
