#!/usr/bin/env python3
"""Replay saved toy-case metrics without constructing a reader or forwarding.

This verifies recorded control summaries and their gate use, not a new control
forward. Final tiny weights are retained separately for later mechanistic work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import assay_v18_operand_selection as assay  # noqa: E402


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"Nonfinite JSON constant: {value}")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replay(directory):
    import torch

    torch.set_num_threads(2)
    directory = Path(directory)
    plan = strict_json((directory / "PLAN.json").read_text())
    if plan != assay.load_plan():
        raise ValueError("Frozen plan differs from replay implementation")
    source = strict_json((directory / "SOURCE.json").read_text())
    if not re.fullmatch(r"[0-9a-f]{40}", source["commit"]):
        raise ValueError("Malformed source commit")
    tracked = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", source["commit"], "--",
         "src", "scripts", "configs", "tests", "pyproject.toml"], cwd=ROOT, text=True,
    ).splitlines()
    if not tracked or set(source["files"]) != set(tracked):
        raise ValueError("Source map differs from the committed file population")
    if source["aggregate_sha256"] != assay.digest(source["files"]):
        raise ValueError("Source hash-map digest mismatch")
    for name, digest in source["files"].items():
        raw_path = ROOT / name
        path = raw_path.resolve()
        if not path.is_relative_to(ROOT) or raw_path.is_symlink() or sha(path) != digest:
            raise ValueError(f"Current source differs: {name}")
        committed = subprocess.check_output(["git", "show", f"{source['commit']}:{name}"], cwd=ROOT)
        if hashlib.sha256(committed).hexdigest() != digest:
            raise ValueError(f"Source differs from declared commit: {name}")
    result = strict_json((directory / "RESULTS.json").read_text())
    terminal = strict_json((directory / "FINISHED.json").read_text())
    started = strict_json((directory / "STARTED.json").read_text())
    if terminal["status"] != "COMPLETED" or (directory / "FAILED.json").exists():
        raise ValueError("Study has not completed successfully")
    for filename, key in (("RESULTS.json", "results_sha256"), ("CASES.jsonl", "cases_sha256")):
        if sha(directory / filename) != terminal[key]:
            raise ValueError(f"Terminal artifact hash mismatch: {filename}")
    for value in (started, result):
        if (value["plan_sha256"] != assay.digest(plan)
                or value["source_sha256"] != source["aggregate_sha256"]):
            raise ValueError("Source/plan identity mismatch")
    if result["device"] != started["device"]:
        raise ValueError("Runtime identity mismatch")
    manifest = strict_json((directory / "POPULATIONS.json").read_text())
    if manifest != result["populations"] or manifest["file"] != "POPULATIONS.pt":
        raise ValueError("Realized-population manifest mismatch")
    if sha(directory / "POPULATIONS.pt") != manifest["file_sha256"]:
        raise ValueError("Realized-population artifact hash mismatch")
    realized = torch.load(directory / "POPULATIONS.pt", map_location="cpu", weights_only=True)
    if set(realized) != set(plan["splits"]):
        raise ValueError("Population split set mismatch")
    for split, payload in realized.items():
        item = manifest[split]
        if (item["frames"] != payload["frames"]
                or item["frames"] != plan["splits"][split]["frames"]
                or item["unique_queries"] != item["frames"] * 36
                or item["rows_sha256"] != assay.digest(payload["rows"])):
            raise ValueError("Population identity/count mismatch")
        for field, expected in item["tensors"].items():
            if assay.tensor_fingerprint(payload[field]) != expected:
                raise ValueError("Realized population tensor fingerprint mismatch")
    expected_fits = {f"{seed}:{factor}" for seed in plan["model_seeds"] for factor in assay.FACTORS}
    if set(result["results"]) != expected_fits:
        raise ValueError("Incomplete or additional fitting cells")
    groups = defaultdict(list)
    with (directory / "CASES.jsonl").open() as stream:
        for line in stream:
            row = strict_json(line)
            groups[(row["seed"], row["factor"], row["split"], row["native_dtype"])].append(row)
    expected_groups = {
        (seed, factor, split, dtype)
        for seed in plan["model_seeds"] for factor in assay.FACTORS
        for split in ("dev", "held_out") for dtype in ("torch.float32", "torch.bfloat16")
    } | {(None, "common_only", "held_out", dtype) for dtype in ("torch.float32", "torch.bfloat16")}
    if set(groups) != expected_groups:
        raise ValueError("Unexpected or missing raw-case groups")
    populations = {name: assay.population(**plan["splits"][name]) for name in ("dev", "held_out")}
    for (seed, factor, split, dtype), rows in groups.items():
        pop = populations[split]
        if [row["case"] for row in rows] != list(range(len(pop.rows))):
            raise ValueError("Raw cases missing, duplicated or reordered")
        for row, expected, label, twin_label in zip(rows, pop.rows, pop.labels, pop.twin_labels):
            if any(row[key] != value for key, value in expected.items()):
                raise ValueError("Raw case metadata differs from frozen population")
            if row["label"] != int(label) or row["twin_label"] != int(twin_label):
                raise ValueError("Raw labels differ from generated facts")
        logits = torch.tensor([row["logits"] for row in rows], dtype=torch.float32)
        twin = torch.tensor([row["twin_logits"] for row in rows], dtype=torch.float32)
        if logits.shape != (len(rows), 7) or twin.shape != logits.shape:
            raise ValueError("Raw full-vocabulary geometry changed")
        if not bool(torch.isfinite(logits).all() & torch.isfinite(twin).all()):
            raise ValueError("Nonfinite raw logits")
        metrics = assay.summarize(logits, twin, pop)
        saved = (
            result["common_only_reference"][dtype] if factor == "common_only"
            else result["results"][f"{seed}:{factor}"][f"{split}_{dtype.split('.')[-1]}"]
        )
        if any(saved[key] != value for key, value in metrics.items()):
            raise ValueError(f"Raw metric replay mismatch: {seed}/{factor}/{split}/{dtype}")
        if abs(saved["max_delta_norm"] - max(row["delta_norm"] for row in rows)) > 1e-7:
            raise ValueError("Residual norm summary mismatch")
    if assay.gates(result["results"], plan) != result["gates"]:
        raise ValueError("Gate replay mismatch")
    for key, fit in result["results"].items():
        if fit["updates"] != plan["training"]["updates"] or len(fit["losses"]) != fit["updates"]:
            raise ValueError(f"Incomplete fitting budget: {key}")
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in fit["losses"]):
            raise ValueError("Nonfinite fitting history")
        seed, factor = key.split(":")
        if strict_json((directory / f"{seed}_{factor}.json").read_text()) != fit:
            raise ValueError("Per-fit receipt differs from aggregate")
        if fit["state_file"] != f"{seed}_{factor}_final_state.pt":
            raise ValueError("Unexpected tiny-state artifact path")
        if sha(directory / fit["state_file"]) != fit["state_file_sha256"]:
            raise ValueError("Tiny-state artifact hash mismatch")
        state = torch.load(directory / fit["state_file"], map_location="cpu", weights_only=True)
        checksum = hashlib.sha256()
        for name, tensor in state.items():
            checksum.update(name.encode())
            checksum.update(assay.tensor_fingerprint(tensor).encode())
        if checksum.hexdigest() != fit["final_state_sha256"]:
            raise ValueError("Tiny-state tensor fingerprint mismatch")
        trainable = fit["trainable_parameter_names_and_counts"]
        if sum(trainable.values()) != fit["trainable_parameter_count"]:
            raise ValueError("Trainable parameter denominator mismatch")
    for seed in plan["model_seeds"]:
        fits = [result["results"][f"{seed}:{factor}"] for factor in assay.FACTORS]
        if len({fit["initial_state_sha256"] for fit in fits}) != 1:
            raise ValueError("Factor initialization differs")
        if any(fit["trainable_parameter_names_and_counts"] != fits[0][
            "trainable_parameter_names_and_counts"] for fit in fits[1:]):
            raise ValueError("Factor parameter budget differs")
    for name in ("IMPORTS_BEFORE.json", "IMPORTS_AFTER.json"):
        imports = strict_json((directory / name).read_text())
        if not {"src/latent_workspace_ft_v10/v18_selection_reader.py",
                "src/latent_workspace_ft_v10/precision_bridge.py"} <= set(imports.values()):
            raise ValueError("Critical import proof missing")
        if any(path not in source["files"] for path in imports.values()):
            raise ValueError("Imported source is not sealed")
    for resources in (result["resources"], terminal["resources"]):
        if (not 0 < resources["elapsed_seconds"] <= plan["resources"]["wall_seconds"]
                or not 0 < resources["peak_rss_bytes"] <= plan["resources"]["peak_bytes"]
                or not 0 <= resources["peak_cuda_allocated_bytes"]
                <= plan["resources"]["peak_bytes"]):
            raise ValueError("Recorded resource limit exceeded")
    return {
        "status": "OFFLINE_RAW_METRICS_AND_GATES_PASS",
        "source_commit": source["commit"], "device": result["device"],
        "fitted_cells": len(expected_fits), "raw_groups": len(groups),
        "raw_rows": sum(map(len, groups.values())), "gates": result["gates"],
        "forward_calls": 0, "training_updates": 0,
        "control_forward_replay": "NOT_PERFORMED_saved_observations_only",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    receipt = replay(args.bundle)
    if args.output:
        assay.write_json(args.output, receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
