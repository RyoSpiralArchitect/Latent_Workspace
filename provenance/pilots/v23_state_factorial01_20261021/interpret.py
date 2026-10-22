#!/usr/bin/env python3
"""Additive source-backed interpretation; never rewrite the primary summary."""

import argparse
import collections
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("state_report", HERE / "summarize.py")
REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)


def compute():
    summary, cells, rows, _ = REPORT.compute()
    REPORT.require(REPORT.read(HERE / "SUMMARY.json") == summary, "Primary summary unchanged")
    text = REPORT.read(HERE / "furnace/TOKEN_TEXT.json")["tokens"]
    repairs, losses = collections.Counter(), collections.Counter()
    query_changes, copy = [], {}
    for key, a in cells.items():
        if key[0] != "world":
            continue
        _, rid, j, w, q, r = key
        if (w, q, r) == ("base", "base", "base"):
            b = cells[key[:3] + ("base", "base", "v22")]
            category = "eos" if a["target"] == 2 else "period" if a["target"] == 29491 else "other"
            repairs[category] += int(not a["score"]["correct"] and b["score"]["correct"])
            losses[category] += int(a["score"]["correct"] and not b["score"]["correct"])
        if w in ("v22", "none") and (q, r) == ("base", "v22"):
            b = cells[key[:3] + (w, "v22", "v22")]
            if a["score"]["top1"] != b["score"]["top1"]:
                query_changes.append(
                    dict(
                        id=rid,
                        index=j,
                        target=text[str(a["target"])],
                        base_q=text[str(a["score"]["top1"])],
                        v22_q=text[str(b["score"]["top1"])],
                        base_q_margin=a["score"]["gold_margin"],
                        v22_q_margin=b["score"]["gold_margin"],
                        full_target=rows[rid]["answer"],
                        mode=rows[rid]["mode"],
                    )
                )
        if rid == "wb01-linked_location-ood-0058/s1/affected" and j == 5:
            copy[REPORT.label(w, q, r)] = dict(
                target=text[str(a["target"])],
                top1=text[str(a["score"]["top1"])],
                margin=a["score"]["gold_margin"],
                correct=a["score"]["correct"],
            )
    mmlu_losses = []
    for key, a in cells.items():
        if key[0] == "mmlu" and key[3:] == ("none", "base", "base"):
            b = cells[key[:3] + ("none", "v22", "v22")]
            if a["score"]["correct"] and not b["score"]["correct"]:
                mmlu_losses.append(
                    dict(
                        id=key[1],
                        cells={
                            REPORT.label("none", q, r): cells[key[:3] + ("none", q, r)]["score"]
                            for q in ("base", "v22")
                            for r in ("base", "v22")
                        },
                    )
                )
    return dict(
        schema="ltws-v23-state-factorial-interpretation-v1",
        source=REPORT.SOURCE,
        reader_only_repairs=dict(repairs),
        reader_only_losses=dict(losses),
        query_changes_fixed_v22_writer_reader=query_changes,
        copy_position_0058_s1_j5=copy,
        original_mmlu_losses=mmlu_losses,
        new_sequences=0,
        model_calls=0,
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    result = compute()
    path = HERE / "INTERPRETATION.json"
    if args.verify:
        REPORT.require(REPORT.read(path) == result, "Additive interpretation replay")
    else:
        with path.open("x") as stream:
            json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    print("V23 additive interpretation verified; no model calls.")


if __name__ == "__main__":
    main()
