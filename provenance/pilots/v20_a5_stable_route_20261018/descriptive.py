#!/usr/bin/env python3
"""Descriptive tables of A5 declared before launch, from receipts only.

Per seed, for the stable route, A4's gated route and the ladder's ungated route: the
endpoint figures and the gap moved from the host's under every final condition (from
ENDPOINTS.json), reversed-memory agreement, and on the training rows at update 512 the
accuracy and the gap moved with each row's own memory and, for the gated routes, with its
mismatch memory. Also the training loss over the last updates. Reads ROWS, HOST_SCORES,
eval and update files; no features.
"""

import gzip
import json
import sys
from pathlib import Path

raw, ladder, a4 = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
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


def losses(path):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    tail = [r["task_loss"] for r in rows]
    return dict(loss_last32=sum(tail[-32:]) / 32, loss_max_last64=max(tail[-64:]))


source = ladder / "extract_cut4"
meta_final = read_gz(source / "ROWS_final.json.gz")
meta_train = read_gz(source / "ROWS_train.json.gz")
host_train = read_gz(source / "HOST_SCORES_train.json.gz")
host_mismatch = read_gz(a4 / "extract_mismatch" / "HOST_SCORES_mismatch.json.gz")
endpoints = json.loads((raw / "endpoints" / "ENDPOINTS.json").read_text())
result = {
    "host": dict(
        verdict=endpoints["host"]["verdict"],
        flips=endpoints["host"]["flips"],
        accuracy=endpoints["host"]["accuracy"],
        train_accuracy=accuracy(meta_train, host_train),
    ),
    "ensemble": {
        k: endpoints["ensemble"][k]
        for k in ("verdict", "flips", "world_sign", "sign_test_p", "accuracy", "gap_moved")
    },
}
folders = {
    "stable": lambda i: (raw / f"stable_s{i}", "stable"),
    "gated": lambda i: (a4 / f"gated_s{i}", "gated"),
    "ungated": lambda i: (ladder / f"route_cut4_s{i}", "route"),
}
for arm, where in folders.items():
    rows = []
    for index in range(1, SEEDS + 1):
        role, name = where(index)
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
            **losses(role / f"updates_{name}.jsonl"),
        )
        if arm != "ungated":
            path = role / f"eval_{name}_mismatch_step{STEP}.json.gz"
            row["mismatch_gap_moved"] = moved(read_gz(path)["adapted_logits"], host_mismatch)
        rows.append(row)
    result[arm] = rows
print(json.dumps(result, indent=1))
