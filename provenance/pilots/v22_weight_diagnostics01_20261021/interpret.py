#!/usr/bin/env python3
"""Additive post-result contrasts of the complete frozen diagnostic panels."""

import argparse
import collections
import json
import math
from pathlib import Path

from summarize import first_fork, journal, paired, read, require

HERE = Path(__file__).resolve().parent


def compute():
    summary = read(HERE / "SUMMARY.json")
    rows = {a: journal(HERE / f"furnace/raw/{a}/worlds.jsonl") for a in ("base", "v22")}
    mmlu = journal(HERE / "furnace/raw/v22/mmlu.jsonl")
    factorial = {}
    for name, left, right in (
        ("head_only_at_base_hidden", "hidden_base_head_base", "hidden_base_head_v22"),
        ("hidden_only_at_base_head", "hidden_base_head_base", "hidden_v22_head_base"),
        ("head_only_at_v22_hidden", "hidden_v22_head_base", "hidden_v22_head_v22"),
        ("both", "hidden_base_head_base", "hidden_v22_head_v22"),
    ):
        factorial[name] = paired(
            {r["id"]: r["head_factorial"][left]["correct"] for r in mmlu},
            {r["id"]: r["head_factorial"][right]["correct"] for r in mmlu},
        )
        factorial[name]["changed_predictions"] = sum(
            r["head_factorial"][left]["prediction"] != r["head_factorial"][right]["prediction"]
            for r in mmlu
        )
    shared_prefix = {}
    for arm, panel in rows.items():
        counts = collections.Counter()
        flips = []
        max_logit_difference = 0.0
        for row in panel:
            fork = row["first_token_difference"]
            for j, step in enumerate(row["fixed_prefix_tokens"]):
                if j >= len(row["gold_ids"]) or (fork is not None and j > fork):
                    break
                gold = row["gold_ids"][j]
                teacher = row["teacher_tokens"][j]["native"]
                actual = (
                    step["native"]
                    if step["recorded_token"] == gold
                    else step["gold_at_first_fork"]["native"]
                )
                require(teacher["target"] == actual["target"] == gold, "Same-prefix target")
                require(row["gold_ids"][:j] == row["recorded_ids"][:j], "Same-prefix token history")
                counts["tokens"] += 1
                counts["same_gold_argmax_correctness"] += teacher["correct"] == actual["correct"]
                max_logit_difference = max(
                    max_logit_difference, abs(teacher["gold_logit"] - actual["gold_logit"])
                )
                if teacher["correct"] != actual["correct"]:
                    flips.append(
                        dict(
                            id=row["id"],
                            route=row["route"],
                            index=j,
                            teacher=teacher,
                            fixed_prefix=actual,
                            target=row["target"],
                            recorded_text=row["recorded_text"],
                        )
                    )
        shared_prefix[arm] = dict(
            **counts,
            max_gold_logit_abs_difference=max_logit_difference,
            correctness_disagreements=flips,
        )
    failed = [r for r in rows["v22"] if r["route"] == "latent" and not r["exact_match"]]
    forks = [first_fork(r) for r in failed]
    require(len(failed) == 13 and all(f is not None for f in forks), "All exposed failures")
    latent = [r for r in rows["v22"] if r["route"] == "latent"]
    return dict(
        scope="Post-result offline interpretation; no new model calls or confirmatory claim",
        head_factorial_contrasts=factorial,
        teacher_vs_prefix_at_identical_token_history=shared_prefix,
        v22_latent=dict(
            rows=len(latent),
            exact_correct=sum(r["exact_match"] for r in latent),
            gold_tokens=sum(len(r["gold_ids"]) for r in latent),
            teacher_gold_argmax=sum(
                s["native"]["correct"] for r in latent for s in r["teacher_tokens"]
            ),
            failures=len(failed),
            first_two_token_forks=sum(f["index"] < 2 for f in forks),
            fp32_gold_top1_at_failed_fork=sum(f["fp32_head"]["correct"] for f in forks),
            first_fork_positions=dict(
                sorted(collections.Counter(str(f["index"]) for f in forks).items())
            ),
            teacher_fork_nll_fraction_min=min(f["teacher_fork_nll_fraction"] for f in forks),
            teacher_fork_nll_fraction_max=max(f["teacher_fork_nll_fraction"] for f in forks),
            teacher_vs_prefix_gold_argmax_disagreements=[
                dict(
                    id=r["id"],
                    index=r["first_token_difference"],
                    teacher=r["teacher_tokens"][r["first_token_difference"]]["native"],
                    prefix=first_fork(r)["native"],
                )
                for r in failed
                if r["teacher_tokens"][r["first_token_difference"]]["native"]["correct"]
                != first_fork(r)["native"]["correct"]
            ],
        ),
        regression_margin_decomposition=[
            dict(
                id=r["id"],
                hidden_effect=r["hidden_effect"],
                head_effect=r["head_effect"],
                interaction=r["interaction"],
                hidden_share_of_total=r["hidden_effect"] / r["total_change"],
            )
            for r in summary["mmlu_regression_cases"]
        ],
        resources_gib={
            arm: {k: round(v / 2**30, 6) for k, v in resource.items() if k.endswith("_bytes")}
            for arm, resource in summary["resources"].items()
        },
        euclidean_change_norms={
            k: math.sqrt(summary["weights"]["total"][k])
            for k in ("native_delta_sq", "master_delta_sq", "cast_error_sq")
        },
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    text = json.dumps(compute(), indent=2, sort_keys=True, allow_nan=False) + "\n"
    target = HERE / "INTERPRETATION_AUDIT.json"
    if args.verify:
        require(target.read_text() == text, "Exact interpretation replay")
    else:
        with target.open("x") as stream:
            stream.write(text)
    print("Offline interpretation audit verified.")


if __name__ == "__main__":
    main()
