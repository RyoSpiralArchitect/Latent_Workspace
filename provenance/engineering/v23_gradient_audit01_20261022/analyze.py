"""Descriptive, offline reductions only; no model imports or acceptance changes."""

import argparse
import json
import math
import statistics
from collections import Counter
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def pairs(rows):
    dot = sum(r["dot"] for r in rows)
    aa, bb = (sum(r[k] for r in rows) for k in ("left_sq", "right_sq"))
    return dict(
        tensors=len(rows),
        elements=sum(r["elements"] for r in rows),
        dot=dot,
        world_l2=math.sqrt(aa),
        preservation_l2=math.sqrt(bb),
        cosine=dot / math.sqrt(aa * bb) if aa and bb else None,
        negative_dot_tensors=sum(r["dot"] < 0 for r in rows),
    )


def analyze(root):
    assert read(root / "raw/FINISHED.json")["status"] == (
        "V23_TRAIN_ONLY_GRADIENT_AUDIT_COMPLETE_NOT_TRAINING"
    )
    current = root / "raw/v22"
    audit = read(current / "AUDIT.json")
    canary = read(current / "CANARY.json")
    visits = {k: set(v) for k, v in canary["path_visits"].items()}
    lower, upper = visits["W"] | visits["Q"], visits["R"]
    groups = dict(
        lower_only=lower - upper, reader_only=upper - lower, lower_and_reader=lower & upper
    )
    conflicts = {}
    for term in ("total", "identity", "copy", "format", "mixed"):
        key = f"worlds_{term}"
        conflicts[term] = dict(
            loss=audit["summaries"][key]["loss"], l2=audit["summaries"][key]["l2"]
        )
        for ref in ("ce", "kl"):
            records = read(current / f"{key}_VS_{ref}.json")
            conflicts[term][ref] = dict(
                all=pairs(records),
                **{
                    g: pairs([r for r in records if r["name"] in names])
                    for g, names in groups.items()
                },
            )
    rows = [json.loads(line) for line in (current / "worlds_total.jsonl").read_text().splitlines()]
    states = [r["state"] for r in rows if "state" in r]
    components = {}
    for term in ("total", "identity", "copy", "format", "mixed"):
        record = {}
        for block in ("memory", "question", "continuation"):
            gs = [s["gradients"][term][block] for s in states]
            n = sum(g["elements"] for g in gs)
            ss = sum(g["l2"] ** 2 for g in gs)
            record[block] = dict(
                rows=len(gs),
                elements=n,
                pooled_row_normalized_rms=math.sqrt(ss / n),
                median_row_l2=statistics.median(g["l2"] for g in gs),
                nonzero=sum(g["nonzero"] for g in gs),
                positive=sum(g["positive"] for g in gs),
                negative=sum(g["negative"] for g in gs),
            )
        ratios = [
            s["gradients"][term]["question"]["rms"] / s["gradients"][term]["memory"]["rms"]
            for s in states
            if s["gradients"][term]["memory"]["rms"] > 0
        ]
        record["question_to_memory_rms"] = dict(
            nonzero_memory_rows=len(ratios), median=statistics.median(ratios) if ratios else None
        )
        components[term] = record
    counts = Counter()
    for s in states:
        counts.update(s["counts"])
    return dict(
        schema="ltws-v23-gradient-audit-descriptive-analysis-v1",
        state_row_denominator="per-row total target count; not whole-panel parameter denominator",
        world_rows=len(rows),
        nonempty_state_rows=len(states),
        nonempty_part_counts=dict(counts),
        whole_world_tokens=audit["world_supervised_tokens"],
        preservation_tokens=audit["preservation_supervised_tokens"],
        canary_reachability={k: len(v) for k, v in groups.items()},
        conflicts=conflicts,
        state_gradients=components,
        interpretation=(
            "Local unpreconditioned first-order geometry, "
            "not an optimizer step, quality or causality proof"
        ),
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    result = json.dumps(analyze(args.root), indent=2, sort_keys=True, allow_nan=False)
    if args.output:
        with args.output.open("x") as f:
            f.write(result + "\n")
    else:
        print(result)
