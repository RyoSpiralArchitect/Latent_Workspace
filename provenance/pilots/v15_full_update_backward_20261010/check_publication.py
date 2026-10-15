#!/usr/bin/env python3
"""Offline selected-number and local-link checks for this engineering result."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("backward_receipts", HERE / "inspect_results.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def main():
    summary, index = audit.build()
    for name, value in (("SUMMARY.json", summary), ("ARTIFACT_INDEX.json", index)):
        audit.require(audit.read(HERE / name) == value, f"Derived mismatch: {name}")
    text = (HERE / "README.md").read_text()
    resources = [
        json.loads(line) for line in (HERE / "raw/RESOURCES.jsonl").read_text().splitlines()
    ]
    host = [
        json.loads(line) for line in (HERE / "raw/HOST_RESOURCES.jsonl").read_text().splitlines()
    ]
    audit.require(len(resources) == len(host) == 23, "Resource sample count")
    numbers = [
        summary[k] for k in ("elapsed_seconds", "peak_cuda_allocated_gib", "peak_cuda_reserved_gib")
    ]
    numbers += [
        min(r["free_bytes"] for r in resources) / 2**30,
        max(p["bytes"] for r in resources for p in r["processes"] if p["pid"] == r["own_pid"])
        / 2**30,
        min(r["available_bytes"] for r in host) / 2**30,
    ]
    for state in audit.STATES:
        value = audit.read(HERE / "raw" / f"{state}.json")
        numbers += [
            value["restore"]["peak_cpu_total_bytes"] / 2**30,
            value["restore"]["peak_cpu_accumulator_bytes"] / 2**30,
        ]
        audit.require(
            sum(r["elements"] for r in value["cpu_reference_exact"]) == 7252223744,
            "CPU reference element count",
        )
    for value in numbers:
        audit.require(f"{value:.6f}" in text, f"Rounded number absent: {value:.6f}")
    expected_nonzero = {
        "initial_seed47": (0, 0, 3),
        "retained_answer_step8": (9, 9, 3),
    }
    for state, counts in expected_nonzero.items():
        pairs = summary["states"][state]["backward_pairs"]
        for route, expected in zip(
            ("context_to_writer", "query_to_reader", "query_or_completion"), counts, strict=True
        ):
            audit.require(
                sum(r["routes"][route]["nonzero"] for r in pairs) == expected, "Route count"
            )
        for world, query in audit.PAIRS:
            pair = audit.read(HERE / "raw" / f"{state}_w{world}q{query}.json")
            reader = [r for r in pair["route_gradients"] if r["route"] == "query_to_reader"]
            audit.require(
                reader[1]["nonzero_elements"] == reader[3]["nonzero_elements"] == 0,
                "Completion gradients",
            )
    documents = {
        p: p.read_text()
        for p in (
            HERE / "README.md",
            HERE / "EXECUTION_HANDOFF.md",
            audit.REPO / "docs/v15/FULL_UPDATE_BACKWARD.md",
        )
    }
    root = audit.REPO / "README.md"
    next_steps = audit.REPO / "docs/v15/NEXT_STEPS.md"
    documents[root] = root.read_text().split("## V15.5 learner restart:")[0]
    documents[next_steps] = next_steps.read_text().split("## Prior decision:")[0]
    links = {}
    for path, content in documents.items():
        count = 0
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", content):
            if target.startswith(("https://", "http://", "#")):
                continue
            audit.require(
                (path.parent / target.split("#", 1)[0]).resolve().is_file(),
                f"Broken local link: {path}: {target}",
            )
            count += 1
        links[str(path.relative_to(audit.REPO))] = count
    print(
        json.dumps(
            {
                "status": "VERIFIED_PUBLICATION_NUMBERS_AND_LINKS",
                "numeric_checks": len(numbers),
                "raw_files": len(index),
                "local_links": links,
                "scope": "selected numerical claims and local links; not causal validation",
            }
        )
    )


if __name__ == "__main__":
    main()
