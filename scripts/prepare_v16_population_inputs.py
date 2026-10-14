#!/usr/bin/env python3
"""Freeze fresh world inputs and a pinned, answer-blind MMLU selection; no model calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_new(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def world_key(record):
    return tuple(sorted(tuple(order) for order in record["metadata"]["orders"]))


def fresh_worlds(plan):
    from v13_task_fixture import symbolic_oracle

    from latent_workspace_ft_v10.engine import make_functional_relation_pair_records

    historical = [
        json.loads(line)
        for name in ("functional_train.jsonl", "functional_eval.jsonl")
        for line in (ROOT / "data/v10" / name).read_text().splitlines()
    ]
    blocked_orders = {tuple(o) for r in historical for o in r["metadata"]["orders"]}
    seen_orders = set(blocked_orders)
    selected, rejected = [], []
    for seed in plan["functional_data_seeds"]:
        candidates = make_functional_relation_pair_records(
            worlds=plan["worlds_per_seed"] * 2,
            seed=seed,
            heldout_template="Does {left} outrank {right}? Answer:",
            heldout_fraction=0.5,
        )
        chosen = 0
        for row in candidates:
            orders = {tuple(o) for o in row["metadata"]["orders"]}
            if orders & seen_orders:
                rejected.append(row["metadata"]["pair_id"])
                continue
            row["choices"] = [" no", " yes"]
            for side in (0, 1):
                for q, query in enumerate(row["queries"]):
                    if symbolic_oracle(row["contexts"][side], query) != row["answers"][side][q]:
                        raise ValueError("Independent text oracle disagreement")
            selected.append(row)
            seen_orders.update(orders)
            chosen += 1
            if chosen == plan["worlds_per_seed"]:
                break
        if chosen != plan["worlds_per_seed"]:
            raise ValueError("Bounded fresh-world pool exhausted")
    return selected, {
        "historical_worlds_excluded": len(historical),
        "historical_order_overlap": 0,
        "within_selection_order_overlap": 0,
        "rejected_pair_ids": rejected,
        "oracle": "text_only_directed_path_traversal",
        "entity_heldout": False,
        "templates_heldout": False,
        "independent_model_training_seeds": 1,
    }


def example(row, *, answer=False):
    if len(row["choices"]) != 4:
        raise ValueError("MMLU requires four choices")
    text = row["question"] + "\n"
    text += "\n".join(f"{letter}. {choice}" for letter, choice in zip("ABCD", row["choices"]))
    text += "\nAnswer:"
    return text + (f" {'ABCD'[row['answer']]}\n\n" if answer else "")


def select_mmlu(test, dev, spec):
    subjects, shots = defaultdict(list), defaultdict(list)
    for index, row in enumerate(test):
        subjects[row["subject"]].append((index, row))
    for index, row in enumerate(dev):
        shots[row["subject"]].append((index, row))
    if len(subjects) != spec["subjects"] or set(shots) != set(subjects):
        raise ValueError("MMLU subject inventory mismatch")
    selected = []
    for subject in sorted(subjects):
        fewshot = shots[subject]
        if len(fewshot) != spec["fewshot"]:
            raise ValueError("Fixed five-shot dev coverage")
        # Selection depends on subject and source row index, never an answer or model score.
        rows = sorted(
            subjects[subject],
            key=lambda item: hashlib.sha256(
                f"{spec['selection_seed']}:{subject}:{item[0]}".encode()
            ).hexdigest(),
        )[: spec["per_subject"]]
        if len(rows) != spec["per_subject"]:
            raise ValueError("Insufficient test rows")
        prefix = (
            "The following are multiple choice questions (with answers) about "
            + " "
            + subject.replace("_", " ")
            + ".\n\n"
            + "".join(example(row, answer=True) for _, row in fewshot)
        )
        for index, row in rows:
            selected.append(
                {
                    "id": f"mmlu:all:test:{index}",
                    "source_index": index,
                    "subject": subject,
                    "prompt": prefix + example(row),
                    "target": row["answer"],
                    "dev_indices": [i for i, _ in fewshot],
                    "question": row["question"],
                    "choices": row["choices"],
                }
            )
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    import pyarrow.parquet as pq

    plan = json.loads((ROOT / "configs/v16/POPULATION_EVAL_PLAN.json").read_text())
    worlds, audit = fresh_worlds(plan)
    paths = {s: args.parquet_dir / f"{s}.parquet" for s in ("test", "dev")}
    rows = {s: pq.read_table(p).to_pylist() for s, p in paths.items()}
    mmlu = select_mmlu(rows["test"], rows["dev"], plan["mmlu"])
    if len(worlds) != plan["functional_worlds"] or len(mmlu) != plan["mmlu"]["n"]:
        raise ValueError("Planned denominators differ")
    args.output.mkdir(parents=True, exist_ok=False)
    write_new(args.output / "functional.json", worlds)
    write_new(args.output / "mmlu.json", mmlu)
    manifest = {
        "schema": "v16-population-inputs-v1",
        "plan_sha256": digest(ROOT / "configs/v16/POPULATION_EVAL_PLAN.json"),
        "functional_audit": audit,
        "mmlu": {
            **plan["mmlu"],
            "license": "MIT",
            "source": "https://huggingface.co/datasets/cais/mmlu",
            "canonical_prompt_reference": "https://github.com/hendrycks/test/blob/master/evaluate.py",
            "source_rows": {s: len(v) for s, v in rows.items()},
            "parquet_sha256": {s: digest(p) for s, p in paths.items()},
        },
        "files": {p.name: digest(p) for p in sorted(args.output.iterdir())},
    }
    write_new(args.output / "INPUTS.json", manifest)
    print(json.dumps({"worlds": len(worlds), "mmlu": len(mmlu), "audit": audit}))


if __name__ == "__main__":
    main()
