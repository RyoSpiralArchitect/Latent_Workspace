#!/usr/bin/env python3
"""Descriptive tables of A4 declared before launch, from receipts only.

Per seed, for the gated route and the ladder's ungated route: the endpoint figures and
the gap moved from the host's under every final condition (from ENDPOINTS.json),
reversed-memory agreement, and on the training rows at update 512 the accuracy and the gap
moved with each row's own memory and, for the gated route, with its mismatch memory.
Reads ROWS, HOST_SCORES and eval files; no features.
"""

import gzip
import json
import sys
from pathlib import Path

raw, ladder = Path(sys.argv[1]), Path(sys.argv[2])
SEEDS, STEP = 3, 512


def read_gz(path):
    return json.loads(gzip.open(path).read())


def by_condition(meta, scores):
    out = {}
    for m, s in zip(meta, scores, strict=True):
        out.setdefault(m["condition"], {})[m["question"]] = s[1] > s[0]
    return {c: [v[i] for i in sorted(v)] for c, v in out.items()}


def agreement(pred, a, b):
    return sum(x == y for x, y in zip(pred[a], pred[b], strict=True)) / len(pred[a])


def accuracy(meta, scores):
    right = [(s[1] > s[0]) == bool(m["label"]) for m, s in zip(meta, scores, strict=True)]
    return sum(right) / len(right)


def moved(scores, host):
    gaps = [abs((s[1] - s[0]) - (h[1] - h[0])) for s, h in zip(scores, host, strict=True)]
    return sum(gaps) / len(gaps)


source = ladder / "extract_cut4"
meta_final = read_gz(source / "ROWS_final.json.gz")
meta_train = read_gz(source / "ROWS_train.json.gz")
host_train = read_gz(source / "HOST_SCORES_train.json.gz")
host_mismatch = read_gz(raw / "extract_mismatch" / "HOST_SCORES_mismatch.json.gz")
endpoints = json.loads((raw / "endpoints" / "ENDPOINTS.json").read_text())
host = endpoints["host"]
result = {
    "host": dict(
        verdict=host["verdict"],
        flips=host["flips"],
        accuracy=host["accuracy"],
        train_accuracy=accuracy(meta_train, host_train),
    )
}
for arm in ("gated", "ungated"):
    rows = []
    for index in range(1, SEEDS + 1):
        if arm == "gated":
            role, name = raw / f"gated_s{index}", "gated"
        else:
            role, name = ladder / f"route_cut4_s{index}", "route"
        final = read_gz(role / f"eval_{name}_final_step{STEP}.json.gz")["adapted_logits"]
        train = read_gz(role / f"eval_{name}_train_step{STEP}.json.gz")["adapted_logits"]
        pred = by_condition(meta_final, final)
        seed = endpoints[arm]["per_seed"][index - 1]
        row = dict(
            verdict=seed["verdict"],
            flips=seed["flips"],
            margin=seed["flip_margin_over_chance"],
            world_sign=seed["world_sign"],
            sign_test_p=seed["sign_test_p"],
            accuracy=seed["accuracy"],
            gap_moved=seed["gap_moved"],
            unaffected_prediction_changes=seed["unaffected_prediction_changes"],
            reversed_agreement=[
                agreement(pred, "intact", "reverse_intact"),
                agreement(pred, "twin", "reverse_twin"),
            ],
            train_accuracy=accuracy(meta_train, train),
            train_gap_moved=moved(train, host_train),
        )
        if arm == "gated":
            mismatch = read_gz(role / f"eval_gated_mismatch_step{STEP}.json.gz")["adapted_logits"]
            row["mismatch_gap_moved"] = moved(mismatch, host_mismatch)
        rows.append(row)
    result[arm] = rows
print(json.dumps(result, indent=1))
