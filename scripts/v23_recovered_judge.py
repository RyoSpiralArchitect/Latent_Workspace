#!/usr/bin/env python3
"""Frozen calibrated judge with explicit whole-arm recovered-input provenance."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import v23_recovered_bank as bank

ex, judge, ROOT = bank.ex, bank.judge, bank.ROOT
SOURCES = [
    bank.PLAN,
    "scripts/v23_recovered_bank.py",
    "scripts/v23_recovered_judge.py",
    "tests/test_v23_recovered_followup.py",
    "docs/v23/RECOVERED_FOLLOWUP_01.md",
    "scripts/qualification_isolation.py",
    "scripts/run_v23_comparison_recovery.py",
    "scripts/run_v23_comparison_recovery02.py",
    "scripts/run_v23_comparison.py",
    "scripts/run_v22_comparison.py",
    "scripts/run_native_7b_canary.py",
    "configs/v23/COMPARISON_RECOVERY_02.json",
]


def source():
    return {n: ex.digest(ROOT / n) for n in SOURCES}


def requests_for(cases):
    return [
        judge.request(c, order, repeat, judge.plan())
        for c in cases
        for order in ("AB", "BA")
        for repeat in range(2 if c.get("repeat") else 1)
    ]


def freeze(output, original, recovered, calibration):
    ex.require(judge.replay(calibration)["calibration_gate"] == "PASS", "Unchanged calibration")
    ex.require((calibration / "run/FINISHED.json").is_file(), "Terminal calibration")
    arms, origins = bank.verify(original, recovered, published_copy=True)
    cases = bank.cases_from_arms(arms, judge.plan())
    requests = requests_for(cases)
    ex.require(len(requests) == 174, "Original study denominator")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    # Bind every new adapter source to this committed version before freezing.
    for name, digest in source().items():
        import hashlib

        body = subprocess.check_output(["git", "show", f"{commit}:{name}"], cwd=ROOT)
        ex.require(hashlib.sha256(body).hexdigest() == digest, "Commit the adapter before freeze")
    output.mkdir(parents=True, exist_ok=False)
    ex.write_new(output / "CASES_OPERATOR.json", cases)
    ex.write_new(output / "REQUESTS_OPERATOR.json", requests)
    ex.write_new(
        output / "BLIND_PACKET.json",
        dict(
            instructions=judge.INSTRUCTIONS,
            schema=judge.SCHEMA,
            rows=[dict(id=r["id"], **r["shown"]) for r in requests],
        ),
    )
    ex.write_new(
        output / "ADAPTER_BINDING.json",
        dict(
            source=source(),
            source_commit=commit,
            origins=origins,
            calibration_terminal_sha256=ex.digest(calibration / "run/FINISHED.json"),
            amendment=(
                "Only the legacy generation-source/status reference is superseded by the explicit "
                "combined bank. The original dispatcher is still incomplete; calibrated judge "
                "policy and all request-construction code are unchanged."
            ),
        ),
    )
    ex.write_new(
        output / "SEAL.json",
        dict(
            phase="study",
            plan=judge.plan(),
            source=judge.source(),
            origins=origins,
            files=ex.manifest(output),
            requests=len(requests),
            created_at=judge.now(),
            source_commit=commit,
        ),
    )
    return dict(status="FROZEN_NOT_DISPATCHED", requests=len(requests), origins=origins)


def verify(output, original, recovered, calibration):
    seal, cases, requests = judge.verify(output)
    binding = ex.read(output / "ADAPTER_BINDING.json")
    ex.require(binding["source"] == source(), "Frozen provenance adapter source")
    ex.require(
        binding["calibration_terminal_sha256"] == ex.digest(calibration / "run/FINISHED.json")
        and judge.replay(calibration)["calibration_gate"] == "PASS",
        "Exact passed calibration",
    )
    arms, origins = bank.verify(original, recovered, published_copy=True)
    ex.require(origins == seal["origins"] == binding["origins"], "Explicit generation origins")
    ex.require(cases == bank.cases_from_arms(arms, judge.plan()), "Every literal answer retained")
    ex.require(requests == requests_for(cases) and len(requests) == 174, "Unchanged request recipe")
    return judge.replay(output)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("freeze", "verify", "run"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--recovered", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--execute-api", action="store_true")
    a = parser.parse_args()
    if a.command == "freeze":
        result = freeze(a.output, a.original, a.recovered, a.calibration)
    else:
        result = verify(a.output, a.original, a.recovered, a.calibration)
        if a.command == "run":
            result = judge.run(a.output, execute_api=a.execute_api, calibration=a.calibration)
            verify(a.output, a.original, a.recovered, a.calibration)
    print(ex.canonical(result), flush=True)


if __name__ == "__main__":
    main()
