#!/usr/bin/env python3
"""Descriptive tables of the A2 depth ladder declared before launch, from receipts only.

Reversed-memory agreement (the same prediction under intact and reversed facts, twin
and reversed twin) and training-split accuracy at update 512, for the host and both
trained arms at every cut. Reads ROWS, HOST_SCORES and eval files; no features.
"""

import gzip
import json
import sys
from pathlib import Path

raw = Path(sys.argv[1])
CUTS, SEEDS, ARMS = (0, 4, 8, 16), 3, ("route", "readout")


def read_gz(path):
    return json.loads(gzip.open(path).read())


def by_condition(meta, scores):
    out = {}
    for m, s in zip(meta, scores, strict=True):
        out.setdefault(m["condition"], {})[m["question"]] = s[1] > s[0]
    return {c: [v[i] for i in sorted(v)] for c, v in out.items()}


def agreement(pred, a, b):
    return sum(x == y for x, y in zip(pred[a], pred[b], strict=True)) / len(pred[a])


def train_accuracy(meta, scores):
    return sum((s[1] > s[0]) == bool(m["label"]) for m, s in zip(meta, scores, strict=True)) / len(
        meta
    )


result = {}
for cut in CUTS:
    folder = raw / f"extract_cut{cut}"
    meta_final = read_gz(folder / "ROWS_final.json.gz")
    meta_train = read_gz(folder / "ROWS_train.json.gz")
    host = by_condition(meta_final, read_gz(folder / "HOST_SCORES_final.json.gz"))
    cell = {
        "host": dict(
            reversed_agreement=[
                agreement(host, "intact", "reverse_intact"),
                agreement(host, "twin", "reverse_twin"),
            ],
            train_accuracy=train_accuracy(
                meta_train, read_gz(folder / "HOST_SCORES_train.json.gz")
            ),
        )
    }
    for arm in ARMS:
        rows = []
        for index in range(1, SEEDS + 1):
            role = raw / f"route_cut{cut}_s{index}"
            final = read_gz(role / f"eval_{arm}_final_step512.json.gz")["adapted_logits"]
            train = read_gz(role / f"eval_{arm}_train_step512.json.gz")["adapted_logits"]
            pred = by_condition(meta_final, final)
            rows.append(
                dict(
                    reversed_agreement=[
                        agreement(pred, "intact", "reverse_intact"),
                        agreement(pred, "twin", "reverse_twin"),
                    ],
                    train_accuracy=train_accuracy(meta_train, train),
                )
            )
        cell[arm] = rows
    result[str(cut)] = cell
print(json.dumps(result, indent=1))
