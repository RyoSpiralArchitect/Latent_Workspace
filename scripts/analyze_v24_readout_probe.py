#!/usr/bin/env python3
"""Offline replay of the bounded V24 readout diagnostic; no model/provider load."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import subprocess
import sys
import tarfile
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from qualification_isolation import validate_audit  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402
from latent_workspace import readout_audit as audit  # noqa: E402

SOURCE = "bb1ecc8b3b3b98f9b63a67da1dbdd76033c76c79"
PLAN = "configs/v24/READOUT_PROBE_01.json"
CASES = "configs/v24/readout_probe01/CASES.json.gz"
ROLES = ("base", "off", "on")
SCOPES = ("src", "scripts", "tests", "configs", "data/v10", "pyproject.toml")


def source(folder):
    seal = ex.read(folder / "SOURCE_SEAL.json")
    ex.require(seal["source_commit"] == SOURCE, "Pinned execution source")
    archive = subprocess.check_output(["git", "archive", SOURCE, "--", *SCOPES], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        bodies = {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}
    hashes = {p: hashlib.sha256(b).hexdigest() for p, b in bodies.items()}
    ex.require(hashes == seal["source_hashes"], "Entire committed source seal")
    for name in (
        "src/latent_workspace/execution.py",
        "src/latent_workspace/readout_audit.py",
        "scripts/qualification_isolation.py",
    ):
        ex.require(ex.digest(ROOT / name) == hashes[name], "Exact offline replay implementation")
    plan = json.loads(bodies[PLAN])
    ex.require(ex.read(ROOT / PLAN) == plan, "Frozen plan unchanged")
    ex.require(ex.digest(ROOT / CASES) == hashes[CASES], "Frozen case bytes")
    return seal, plan


def terminal(folder, status):
    ex.require(not any(p.is_symlink() for p in folder.rglob("*")), "No artifact symlinks")
    end = ex.read(folder / "FINISHED.json")
    files = ex.manifest(folder)
    files.pop("FINISHED.json")
    ex.require(end["status"] == status and end["files"] == files, "Terminal status and manifest")
    ex.require(all(end[k] == v for k, v in ex.CEILING.items()), "Unchanged claim ceiling")
    return ex.read(folder / "STARTED.json"), end


def verify(folder):
    folder = Path(folder)
    seal, plan = source(folder)
    data = ex.read_gz(ROOT / CASES)
    ex.require(ex.plan_hash(data) == plan["cases_sha256"], "Case content hash")
    ex.require(len(data["cases"]) == 44 and data["forwards_per_arm"] == 197, "Frozen denominator")
    qualified = {}
    for device in ("cpu", "cuda"):
        path = folder / "qualification" / device
        start, end = terminal(path, "TINY_V24_READOUT_PASS_NOT_7B")
        ex.require(
            start["seal"] == seal and start["plan"] == plan and start["device"] == device,
            "Qualification provenance",
        )
        counts = dict(tests=350, failures=0, errors=0, skipped=0)
        xml = ElementTree.parse(path / "TESTS.xml")
        observed = {k: sum(int(s.get(k, 0)) for s in xml.iter("testsuite")) for k in counts}
        ex.require(
            end["counts"] == observed == counts and end["pytest_exit_code"] == 0,
            "All 350 tests/device; no skips",
        )
        qualified[device] = ex.manifest(path)
    isolation = folder / "qualification/CPU_ISOLATION.json"
    validate_audit(
        ex.read(isolation),
        ex.digest(folder / "qualification/cpu/FINISHED.json"),
        ex.read(folder / "qualification/cpu/STARTED.json")["pid"],
    )
    qualified["cpu_isolation"] = dict(sha256=ex.digest(isolation))
    start, end = terminal(folder / "raw", plan["pass_status"])
    ex.require(
        start["seal"] == seal and start["plan"] == plan and start["qualification"] == qualified,
        "Dispatch provenance",
    )
    ex.require(
        end["completed_roles"] == list(ROLES) and end["native_forward_calls"] == 591,
        "All three completed roles",
    )
    checkpoints = folder / "checkpoints"
    # Empty directories disappear from Git; no nonempty checkpoint tree is allowed.
    ex.require(not checkpoints.exists() or not list(checkpoints.iterdir()), "No saved weights")
    arms, resources = {}, {}
    for role in ROLES:
        path = folder / "raw" / role
        start, end = terminal(path, "V24_READOUT_ARM_COMPLETE_NOT_QUALITY")
        ex.require(
            start["role"] == role
            and start["seal"] == seal
            and start["plan"] == plan
            and start["qualification"] == qualified,
            "Role provenance",
        )
        ex.require(ex.read(path / "INPUTS.json") == data, "Identical frozen inputs")
        outcome = end["outcome"]
        ex.require(
            outcome["cases"] == 44
            and outcome["native_forward_calls"] == 197
            and outcome["checkpoint_saves"] == 0,
            "Role denominator",
        )
        identity = ex.read(path / "WEIGHT_IDENTITY.json")
        ex.require(identity["before"] == identity["after"], "Read-only model weights")
        lines = [json.loads(line) for line in (path / "READOUT.jsonl").read_text().splitlines()]
        ex.require(len(lines) == 44, "Exact journal denominator")
        records = {}
        for line, case in zip(lines, data["cases"], strict=True):
            trace = line["trace"]
            ex.require(
                line["id"] == case["id"]
                and line["family"] == case["family"]
                and trace["spec"] == case["spec"]
                and trace["memory_ids"] == case["memory_ids"],
                "Exact ordered case / history / memory",
            )
            ex.require(line["id"] not in records, "Unique case ID")
            audit.compare_fixed(trace, trace)
            records[line["id"]] = trace
        ex.require(
            sum(t["native_forward_calls"] for t in records.values()) == 197,
            "Actual forward denominator",
        )
        arms[role] = records
        resources[role] = {k: v for k, v in outcome.items() if k.startswith("peak_")}
        resources[role]["elapsed_seconds"] = end["elapsed_seconds"]
    return (
        arms,
        data,
        dict(
            source_commit=SOURCE,
            source_files=len(seal["source_hashes"]),
            source_seal_sha256=ex.digest(folder / "SOURCE_SEAL.json"),
            terminal_sha256=ex.digest(folder / "raw/FINISHED.json"),
            cases=132,
            native_forward_calls=591,
            resources=resources,
        ),
    )


def binding(row):
    probes = row["probes"]
    ex.require(bool(probes), "Declared candidate probes")
    target = row["target"]
    other = [p["logit"] for p in probes if p["token_id"] != target["token_id"]]
    best = max(p["logit"] for p in probes)
    winners = [p["token_id"] for p in probes if p["logit"] == best]
    return dict(
        target_probability=math.exp(target["logprob"]),
        target_rank=target["rank"],
        target_full_vocab_margin=target["margin_vs_best_other"],
        target_choice_margin=target["logit"] - max(other),
        target_strict_choice_win=target["logit"] > max(other),
        choice_winners=winners,
        candidate_tie=len(winners) > 1,
        eos_probability=math.exp(row["eos"]["logprob"]),
    )


def stage_delta(left, right):
    result = audit.compare_fixed(left, right)
    return dict(
        tokens=result["tokens"],
        stages=result["stages"],
        target_logprob_sum=sum(r["target_logprob"] for r in result["deltas"]),
    )


def analyze(arms, data, verification):
    mmlu, worlds = {}, {}
    for role, traces in arms.items():
        mmlu[role] = {}
        for uid in ex.read(ROOT / PLAN)["mmlu_ids"]:
            item = {}
            for anchor in ("direct", "unassisted_label", "oracle_content_label"):
                item[anchor] = binding(traces[f"{uid}/{anchor}"]["rows"][0])
            for anchor in ("start_eos", "complete_eos"):
                row = traces[f"{uid}/{anchor}"]["rows"][0]
                item[anchor] = dict(
                    probability=math.exp(row["eos"]["logprob"]),
                    rank=row["eos"]["rank"],
                    margin=row["eos"]["margin_vs_best_other"],
                )
            mmlu[role][uid] = item
        worlds[role] = {}
        for group in data["selected_world_groups"]:
            refs = []
            for side in (0, 1):
                intact = traces[f"{group}/ref{side}/s{side}"]
                twin = traces[f"{group}/ref{side}/s{1 - side}"]
                empty = traces[f"{group}/ref{side}/empty"]
                refs.append(
                    dict(
                        side=side,
                        intact_minus_twin=stage_delta(twin, intact),
                        intact_minus_empty=stage_delta(empty, intact),
                    )
                )
            worlds[role][group] = refs
    contrasts = {}
    for a, b in (("base", "off"), ("base", "on"), ("off", "on")):
        contrasts[f"{b}_minus_{a}"] = {
            key: audit.compare_fixed(arms[a][key], arms[b][key]) for key in arms[a]
        }
    return dict(
        schema="ltws-v24-readout-offline-analysis-v1",
        verification=verification,
        mmlu=mmlu,
        worlds=worlds,
        model_contrasts=contrasts,
        **ex.CEILING,
        claim=(
            "Exposed conditional readout diagnosis; not benchmark accuracy, "
            "broad ability or a causal reasoning proof"
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--write", type=Path)
    parser.add_argument("--check", type=Path)
    args = parser.parse_args()
    ex.require(not (args.write and args.check), "One offline output operation")
    value = analyze(*verify(args.bundle))
    if args.write:
        ex.write_new(args.write, value)
    if args.check:
        ex.require(ex.read(args.check) == value, "Exact analysis replay")
    print(ex.canonical(value["verification"]))
