#!/usr/bin/env python3
"""Additive post-result contrasts; no model calls or reinterpretation of gates."""

import argparse
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("causal_replay", HERE / "summarize.py")
REPLAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPLAY)


def compute():
    summary, inputs, observed = REPLAY.compute()
    REPLAY.require(summary == REPLAY.read(HERE / "SUMMARY.json"), "Base analysis unchanged")
    writer_changes, unaffected_changes, empty_unique, prefix_changes = [], [], {}, []
    for role, left, right in (
        ("base", "identity", "foreign_writer"),
        ("v22", "foreign_writer", "identity"),
    ):
        for (rid, condition), a in observed[role].items():
            if condition != left:
                continue
            b = observed["base_cross" if role == "base" else "v22"][rid, right]
            if a["token_ids"] != b["token_ids"]:
                writer_changes.append(
                    dict(
                        reader=role,
                        id=rid,
                        target=a["target"],
                        base_writer_text=a["text"],
                        v22_writer_text=b["text"],
                        base_writer_correct=a["exact_match"],
                        v22_writer_correct=b["exact_match"],
                        memory=inputs[rid]["memory"],
                        query=inputs[rid]["query"],
                    )
                )
    for (rid, condition), b in observed["v22"].items():
        if condition != "twin" or b["mode"] != "unaffected":
            continue
        a = observed["v22"][rid, "identity"]
        if a["token_ids"] != b["token_ids"]:
            unaffected_changes.append(
                dict(
                    id=rid,
                    target=a["target"],
                    intact=a["text"],
                    swapped=b["text"],
                    donor_id=b["donor_id"],
                )
            )
    for role in ("base", "v22"):
        unique = {}
        for (rid, condition), row in observed[role].items():
            if condition != "empty":
                continue
            key = tuple(inputs[rid]["prefixes"]["latent"])
            if key in unique:
                REPLAY.require(
                    unique[key]["token_ids"] == row["token_ids"], "Identical empty query"
                )
            unique[key] = row
        empty_unique[role] = dict(
            queries=len(unique),
            abstained=sum(r["abstained"] for r in unique.values()),
            source_condition_rows=80,
        )
        for row in REPLAY.journal(HERE / "furnace/raw" / role / "prefix.jsonl"):
            cropped = row["variants"]["cropped"]["score"]
            if row["full"]["correct"] != cropped["correct"]:
                prefix_changes.append(
                    dict(
                        role=role,
                        id=row["id"],
                        route=row["route"],
                        index=row["index"],
                        full=row["full"],
                        cropped=cropped,
                    )
                )
    return dict(
        source=summary["source"],
        model_calls=0,
        new_sequences=0,
        writer_output_changes=writer_changes,
        v22_unaffected_changes=unaffected_changes,
        empty_unique_queries=empty_unique,
        prefix_correctness_changes=prefix_changes,
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
        REPLAY.require(REPLAY.read(path) == result, "Additive interpretation replay")
    else:
        with path.open("x") as stream:
            json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    print("Offline additive interpretation verified; no model calls.")


if __name__ == "__main__":
    main()
