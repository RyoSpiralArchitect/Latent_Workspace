#!/usr/bin/env python3
"""Offline exact receipt replay and descriptive readout analysis; no model calls."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import tarfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import run_v24_recruitment_readout as run  # noqa: E402
from qualification_isolation_v2 import validate_audit  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402
from latent_workspace import recruitment_readout as meter  # noqa: E402

SCOPES = ("src", "scripts", "tests", "configs", "data/v10", "pyproject.toml")


def lines(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def source(folder, expected_source):
    seal = ex.read(folder / "SOURCE_SEAL.json")
    ex.require(
        len(expected_source) == 40 and seal["source_commit"] == expected_source, "Pinned source"
    )
    archive = subprocess.check_output(["git", "archive", expected_source, "--", *SCOPES], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        bodies = {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}
    hashes = {p: hashlib.sha256(b).hexdigest() for p, b in bodies.items()}
    ex.require(hashes == seal["source_hashes"], "Complete committed source seal")
    for name in (
        "scripts/analyze_v24_recruitment_readout.py",
        run.ENTRY,
        "src/latent_workspace/execution.py",
        "src/latent_workspace/recruitment_readout.py",
        "src/latent_workspace/readout_audit.py",
        "src/latent_workspace/recruitment_bank.py",
        "scripts/qualification_isolation.py",
        "scripts/qualification_isolation_v2.py",
        "scripts/qualification_observer.py",
    ):
        ex.require(ex.digest(ROOT / name) == hashes[name], "Exact offline replay implementation")
    plan = json.loads(bodies[run.PLAN])
    ex.require(ex.read(ROOT / run.PLAN) == plan, "Frozen plan")
    run.validate(plan)
    return seal, plan


def terminal(folder, status, sequences):
    ex.require(not any(p.is_symlink() for p in folder.rglob("*")), "No artifact symlinks")
    start, end = ex.read(folder / "STARTED.json"), ex.read(folder / "FINISHED.json")
    files = ex.manifest(folder)
    files.pop("FINISHED.json")
    ex.require(end["status"] == status and end["files"] == files, "Closed complete manifest")
    for key, value in ex.CEILING.items():
        ex.require(
            end[key] == (sequences if key == "new_sequences" else value), "Actual activity/ceiling"
        )
    return start, end


def resources(path, plan, pid, forward_calls):
    host, gpu, cache = (
        lines(path / name) for name in ("HOST_RESOURCES.jsonl", "RESOURCES.jsonl", "CACHE.jsonl")
    )
    limits = plan["resources"]
    ex.require(len(host) == len(gpu) > 1 and host[0]["phase"] == "admission", "Resource coverage")
    ex.require(len({row["uuid"] for row in gpu}) == 1, "Stable GPU identity")
    for h, g in zip(host, gpu, strict=True):
        admission = h["phase"] == "admission"
        ex.require(h["phase"] == g["phase"], "Paired resource observation")
        ex.require(
            h["disk_free_bytes"] - h["forecast_bytes"] >= limits["disk_free_gib"] * ex.GIB,
            "Disk floor",
        )
        ex.require(
            h["available_bytes"]
            >= limits["host_admission_available_gib" if admission else "host_abort_available_gib"]
            * ex.GIB,
            "Host floor",
        )
        ex.require(h["elapsed_seconds"] <= limits["max_elapsed_seconds"], "Time bound")
        ex.require(
            g["free_bytes"]
            >= limits["admission_free_gib" if admission else "abort_free_gib"] * ex.GIB,
            "GPU floor",
        )
        ex.require(
            g["own_pid"] == pid and all(p["pid"] == pid for p in g["processes"]),
            "No competing GPU client",
        )
        ex.require(
            g.get("peak_allocated", 0) <= limits["allocator_cap_gib"] * ex.GIB, "Allocator limit"
        )
    ex.require(len(cache) == forward_calls, "Every token boundary observed")
    ex.require(
        all(r["allocated_before"] == r["allocated_after"] for r in cache),
        "Live allocations preserved",
    )
    ex.require(
        [r["phase"] for r in cache]
        == [r["phase"] for r in host if r["phase"].startswith("generation:")],
        "Boundary/guard parity",
    )
    return dict(
        min_disk_free_bytes=min(r["disk_free_bytes"] for r in host),
        min_host_available_bytes=min(r["available_bytes"] for r in host),
        min_gpu_free_bytes=min(r["free_bytes"] for r in gpu),
    )


def replay_rows(path, data, plan, tokenizer):
    fixed, free = lines(path / "FIXED.jsonl"), lines(path / "GENERATIONS.jsonl")
    expected = [(c, r) for c in data["cases"] for r in c["references"]]
    ex.require(
        len(fixed) == len(expected) and len(free) == len(data["cases"]), "No missing/repeated rows"
    )
    fixed_by_case = {c["id"]: {} for c in data["cases"]}
    for record, (case, ref) in zip(fixed, expected, strict=True):
        trace = record["trace"]
        ex.require(
            record["id"] == case["id"] and record["reference"] == ref["id"],
            "Ordered reference identity",
        )
        ex.require(
            trace["spec"]
            == meter.specification(case["prefix_ids"], ref, tokenizer.eos_token_id).record(),
            "Exact reference prefix",
        )
        ex.require(trace["memory_ids"] == case["memory_ids"], "Exact memory")
        ex.require(
            record["measurements"] == meter.summarize_fixed(trace, ref), "Exact metric replay"
        )
        fixed_by_case[case["id"]][ref["id"]] = record
    free_by_case = {}
    for record, case in zip(free, data["cases"], strict=True):
        ex.require(record["id"] == case["id"], "Ordered generation identity")
        replay = dict(
            id=case["id"],
            **run.score_result(
                tokenizer, record["generation"], case["expected"], plan["generation"]
            ),
        )
        ex.require(record == replay, "Exact token decode and strict score replay")
        free_by_case[case["id"]] = record
    return dict(fixed=fixed_by_case, free=free_by_case)


def verify(folder, expected_source, tokenizer):
    folder = Path(folder)
    seal, plan = source(folder, expected_source)
    data = run.load_inputs(plan)
    ex.require(run.make_inputs(tokenizer, plan) == data, "Offline tokenizer/input replay")
    qualified = {}
    for device in ("cpu", "cuda"):
        path = folder / "qualification" / device
        start, end = terminal(path, run.RUN.tiny_pass, 0)
        counts = dict(tests=plan["qualification_cases"], failures=0, errors=0, skipped=0)
        xml = ElementTree.parse(path / "TESTS.xml")
        actual = {k: sum(int(s.get(k, 0)) for s in xml.iter("testsuite")) for k in counts}
        ex.require(
            start["seal"] == seal and start["plan"] == plan and start["device"] == device,
            "Qualified provenance",
        )
        ex.require(
            end["counts"] == actual == counts and end["pytest_exit_code"] == 0, "All selected tests"
        )
        qualified[device] = ex.manifest(path)
    q = folder / "qualification"
    validate_audit(
        ex.read(q / "CPU_ISOLATION.json"),
        ex.digest(q / "cpu/FINISHED.json"),
        ex.read(q / "cpu/STARTED.json")["pid"],
        q / "CPU_OBSERVER.jsonl",
    )
    for key, name in (
        ("cpu_isolation", "CPU_ISOLATION.json"),
        ("cpu_observer", "CPU_OBSERVER.jsonl"),
    ):
        qualified[key] = dict(sha256=ex.digest(q / name))
    start, end = terminal(folder / "raw", plan["pass_status"], 216)
    ex.require(
        start["seal"] == seal and start["plan"] == plan and start["qualification"] == qualified,
        "Dispatch provenance",
    )
    ex.require(end["completed_roles"] == list(run.ROLES), "All three roles complete")
    checkpoints = folder / "checkpoints"
    ex.require(not checkpoints.exists() or not list(checkpoints.iterdir()), "No checkpoint writes")
    arms, totals, safety = {}, Counter(), {}
    original = run.frozen_training(plan)
    for role in run.ROLES:
        path = folder / "raw" / role
        begin, finish = terminal(path, run.RUN.role_status[role], 72)
        ex.require(
            begin["role"] == role
            and begin["seal"] == seal
            and begin["plan"] == plan
            and begin["qualification"] == qualified,
            "Role provenance",
        )
        ex.require(ex.read(path / "INPUTS.json") == data, "Same frozen inputs")
        identity = ex.read(path / "WEIGHT_IDENTITY.json")
        ex.require(identity["before"] == identity["after"], "Read-only model")
        origin = ex.read(path / "ORIGINAL_IDENTITY.json")
        backbone = ex.read(ROOT / plan["training_plan"])["backbone"]["identity"]
        ex.require(
            origin["expected"] == origin["observed"] == backbone
            and all(origin["matches"].values()),
            "Original base identity",
        )
        if role != "base":
            saved = original["roles"][role]
            restore = ex.read(path / "RESTORE.json")
            ex.require(
                restore["exact"] is True
                and restore["checkpoint"] == saved[f"CHECKPOINT_{role}_step32.pt.json"]
                and restore["fingerprint"] == saved[f"STATE_{role}_step32.pt.json"]
                and restore["training_contract"] == saved["CONTEXT.json"]["contract"],
                "Original final checkpoint restore",
            )
        arms[role] = replay_rows(path, data, plan, tokenizer)
        generated = sum(r["generation"]["generated_tokens"] for r in arms[role]["free"].values())
        counts = dict(
            new_sequences=72,
            reference_traces=144,
            fixed_forwards=2320,
            generated_tokens=generated,
            native_forward_calls=2320 + generated,
            native_weight_updates=0,
            checkpoint_saves=0,
        )
        ex.require(
            all(finish["outcome"][k] == v for k, v in counts.items())
            and finish["native_forward_calls"] == counts["native_forward_calls"],
            "Actual denominator",
        )
        safety[role] = resources(path, plan, begin["pid"], counts["native_forward_calls"])
        safety[role]["elapsed_seconds"] = finish["elapsed_seconds"]
        totals.update(counts)
    ex.require(
        dict(totals) == end["summary"]
        and end["native_forward_calls"] == totals["native_forward_calls"],
        "Complete dispatcher totals",
    )
    return (
        arms,
        data,
        dict(
            source_commit=expected_source,
            source_files=len(seal["source_hashes"]),
            source_seal_sha256=ex.digest(folder / "SOURCE_SEAL.json"),
            terminal_sha256=ex.digest(folder / "raw/FINISHED.json"),
            counts=dict(totals),
            safety=safety,
            tests_per_device=plan["qualification_cases"],
        ),
    )


def count_generation(records):
    return dict(
        rows=len(records),
        parsed=sum(r["score"]["parsed"] for r in records),
        correct_answer=sum(r["score"]["content_correct"] for r in records),
        steps_applicable=sum(r["score"]["steps_applicable"] for r in records),
        correct_steps=sum(
            r["score"]["steps_correct"] and r["score"]["steps_applicable"] for r in records
        ),
        exact=sum(r["score"]["exact"] for r in records),
        eos=sum(r["generation"]["stop_reason"] == "eos" for r in records),
        length_capped=sum(r["generation"]["stop_reason"] == "length" for r in records),
        generated_tokens=sum(r["generation"]["generated_tokens"] for r in records),
    )


def contrast(left, right, ids):
    metrics = {}
    for metric in ("parsed", "content_correct", "exact", "steps_correct"):
        eligible = [
            i for i in ids if metric != "steps_correct" or left[i]["score"]["steps_applicable"]
        ]
        metrics[metric] = dict(
            rows=len(eligible),
            repaired=[
                i for i in eligible if not left[i]["score"][metric] and right[i]["score"][metric]
            ],
            lost=[
                i for i in eligible if left[i]["score"][metric] and not right[i]["score"][metric]
            ],
        )
    return dict(
        metrics=metrics,
        changed_tokens=[
            i
            for i in ids
            if left[i]["generation"]["token_ids"] != right[i]["generation"]["token_ids"]
        ],
    )


def analyze(arms, data, verification):
    cells, comparisons, directions = {}, {}, {}
    for role in run.ROLES:
        directions[role] = []
        for route in ("inline", "workspace"):
            cases = [c for c in data["cases"] if c["route"] == route]
            strata = {"all": cases}
            for key in ("family", "group_id", "mode"):
                for label in sorted({c[key] for c in cases}):
                    strata[f"{key}:{label}"] = [c for c in cases if c[key] == label]
            cell = {}
            for name, selected in strata.items():
                fixed = {}
                for reference in ("own_answer_first", "own_steps_first", "donor_answer_first"):
                    measurements = [
                        arms[role]["fixed"][c["id"]][reference]["measurements"]
                        for c in selected
                        if reference in arms[role]["fixed"][c["id"]]
                    ]
                    fixed[reference] = dict(
                        rows=len(measurements),
                        parts={
                            p: dict(
                                tokens=sum(m["parts"][p]["tokens"] for m in measurements),
                                nll_sum=sum(m["parts"][p]["nll_sum"] for m in measurements),
                            )
                            for p in meter.PARTS
                        },
                        step_bearing_tokens_by_assistance={
                            p: dict(
                                tokens=sum(
                                    m["step_bearing_tokens_by_assistance"][p]["tokens"]
                                    for m in measurements
                                ),
                                nll_sum=sum(
                                    m["step_bearing_tokens_by_assistance"][p]["nll_sum"]
                                    for m in measurements
                                ),
                            )
                            for p in ("before_gold_answer", "after_gold_answer")
                        },
                    )
                cell[name] = dict(
                    generation=count_generation([arms[role]["free"][c["id"]] for c in selected]),
                    fixed=fixed,
                )
            cells[f"{role}/{route}"] = cell
            for c in cases:
                if c["mode"] == "affected":
                    measured = arms[role]["fixed"][c["id"]]
                    own = measured["own_answer_first"]["measurements"]["answer_prefix_logprob"]
                    donor = measured["donor_answer_first"]["measurements"]["answer_prefix_logprob"]
                    directions[role].append(
                        dict(
                            id=c["id"],
                            group_id=c["group_id"],
                            route=route,
                            side=c["side"],
                            own_minus_donor_answer_prefix_logprob=own - donor,
                        )
                    )
        ids = [c["id"] for c in data["cases"]]
        if role != "base":
            comparisons[f"{role}_versus_base"] = contrast(
                arms["base"]["free"], arms[role]["free"], ids
            )
    return dict(
        schema="ltws-v24-recruitment-readout-analysis-v1",
        verification=verification,
        selection=data["selection"],
        cells=cells,
        paired_generation=comparisons,
        directionality=directions,
        literal_generations={r: list(arms[r]["free"].values()) for r in run.ROLES},
        **{k: v for k, v in ex.CEILING.items() if k != "new_sequences"},
        new_sequences=verification["counts"]["new_sequences"],
        claim=(
            "Six development source groups; correlated twins/routes, not 216 independent problems. "
            "Prefix likelihood includes syntax/length, not choice accuracy. "
            "No general ability or release claim."
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--tokenizer", required=True)
    parser.add_argument("--write", type=Path)
    parser.add_argument("--check", type=Path)
    args = parser.parse_args()
    ex.require(not (args.write and args.check), "One output operation")
    ex.offline_environment()
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        args.tokenizer, local_files_only=True, trust_remote_code=False
    )
    value = analyze(*verify(args.bundle, args.source, tokenizer))
    if args.write:
        ex.write_new(args.write, value)
    if args.check:
        ex.require(ex.read(args.check) == value, "Exact analysis replay")
    print(ex.canonical(value["verification"]))
