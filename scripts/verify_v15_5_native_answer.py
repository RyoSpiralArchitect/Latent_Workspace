#!/usr/bin/env python3
"""Offline scalar/identity replay for the eight-update native learner pilot.

This verifies stored evidence, not an independent model reload or tensor replay.
No network, Torch, tokenizer download, learner execution or API judge is used.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ARMS = ("native_answer", "native_answer_eos")
CONTROLS = ("intact", "twin", "reverse_intact", "reverse_twin", "zero", "unrelated")
CONDITIONS = ("base", "base_inline", "workspace", "twin", "zero")


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finite(value):
    if isinstance(value, float):
        require(math.isfinite(value), "Nonfinite receipt scalar")
    elif isinstance(value, dict):
        for item in value.values():
            finite(item)
    elif isinstance(value, list):
        for item in value:
            finite(item)


def read(path):
    result = json.loads(path.read_text())
    finite(result)
    return result


def eval_summary(rows, records, step):
    expected = set(itertools.product(range(2), range(8), CONTROLS))
    keyed = {(r["world"], r["query"], r["control"]): r for r in rows}
    require(len(keyed) == len(rows) == 96 and set(keyed) == expected, "Evaluation denominator")
    for (w, q, control), row in keyed.items():
        scores, base = row["native_scores"], row["base_native_scores"]
        require(len(scores) == len(base) == 2, "Native choice shape")
        prediction = None if scores[0] == scores[1] else int(scores[1] > scores[0])
        side = (
            0
            if control in ("intact", "reverse_intact")
            else (1 if control in ("twin", "reverse_twin") else None)
        )
        target = records[w]["answers"][side][q] if side is not None else None
        correct = prediction is not None and prediction == target if target is not None else None
        base_correct = (
            base[0] != base[1] and int(base[1] > base[0]) == target if target is not None else None
        )
        require(
            (row["native_prediction"], row["target_label"], row["correct"], row["base_correct"])
            == (prediction, target, correct, base_correct),
            "Choice arithmetic differs",
        )
        require(row["delta_l2"] <= 1.000001, "Residual cap violated")
        if step == 0 or control == "zero":
            require(
                row["full_logits_equal_base"] and scores == base and row["delta_l2"] == 0,
                "Initial/written-zero parity differs",
            )
    result = {}
    for control in CONTROLS:
        selected = [r for r in rows if r["control"] == control]
        has_truth = control not in ("zero", "unrelated")
        result[control] = {
            "rows": 16,
            "correct": sum(r["correct"] for r in selected) if has_truth else None,
            "ties": sum(r["native_prediction"] is None for r in selected),
            "changed_full_logits": sum(not r["full_logits_equal_base"] for r in selected),
            "max_abs_logit_change": max(r["max_abs_logit_change"] for r in selected),
            "max_total_variation": max(r["total_variation"] for r in selected),
            "new_errors_relative_to_same_prefix_base": sum(
                r["base_correct"] and not r["correct"] for r in selected
            )
            if has_truth
            else None,
        }
    affected = []
    for w, q in itertools.product(range(2), range(2)):
        original, twin = keyed[w, q, "intact"], keyed[w, q, "twin"]
        a, b = original["native_scores"], twin["native_scores"]
        affected.append(
            {
                "world": w,
                "query": q,
                "donor_signed_change": (2 * twin["target_label"] - 1)
                * ((b[1] - b[0]) - (a[1] - a[0])),
                "both_sides_correct": original["correct"] and twin["correct"],
            }
        )
    return {"controls": result, "unique_affected_pairs": affected}


def generation_summary(rows, records):
    keyed = {(r["world"], r["query"], r["condition"]): r for r in rows}
    expected = set(itertools.product(range(2), range(2), CONDITIONS))
    require(len(rows) == len(keyed) == 20 and set(keyed) == expected, "Generation denominator")
    for (w, q, condition), row in keyed.items():
        tokens = row["generated_ids"]
        require(1 <= len(tokens) <= 16 and len(tokens) == row["token_count"], "Token budget")
        require(len(row["token_trace"]) == len(tokens), "Token trace denominator")
        require([t["token_id"] for t in row["token_trace"]] == tokens, "Trace/token mismatch")
        if row["finish_reason"] == "eos":
            require(tokens[-1] == 2 and 2 not in tokens[:-1], "EOS identity")
        else:
            require(
                row["finish_reason"] == "length" and len(tokens) == 16 and 2 not in tokens,
                "Length/termination contract",
            )
        parsed = {"no": 0, "yes": 1}.get(row["answer"].strip().lower())
        target = records[w]["answers"][int(condition == "twin")][q]
        valid = parsed is not None and row["finish_reason"] == "eos"
        require(
            (row["parsed_answer"], row["valid_eos"], row["strict_correct"], row["target_label"])
            == (parsed, valid, valid and parsed == target, target),
            "Whole-answer score differs",
        )
        if condition == "zero":
            baseline = keyed[w, q, "base"]
            require(
                tokens == baseline["generated_ids"] and row["answer"] == baseline["answer"],
                "Base/zero generated text differs",
            )
    return {
        condition: {
            "planned": 4,
            "strict_correct": sum(r["strict_correct"] for r in rows if r["condition"] == condition),
            "valid_eos": sum(r["valid_eos"] for r in rows if r["condition"] == condition),
            "length_limited": sum(
                r["finish_reason"] == "length" for r in rows if r["condition"] == condition
            ),
        }
        for condition in CONDITIONS
    }


def build(bundle):
    raw = bundle / "raw"
    start, report = read(raw / "STARTED.json"), read(raw / "REPORT.json")
    require(report["status"] == "COMPLETED_ENGINEERING_PILOT", "No completed pilot")
    require(start["source_commit"] == report["source_commit"], "Source commit drift")
    for name, sha in start["source_hashes"].items():
        require(digest(REPO / name) == sha, f"Source bytes changed: {name}")
    require(
        report["base_state_sha256_before"]
        == report["base_state_sha256_after"]
        == "54d161755862ebf00d8acbca083d5f290a5de44d33af82ca885f3bd8f9c94312",
        "Base identity",
    )
    require(report["base_unchanged"] and report["source_unchanged"], "Mutated frozen state")
    require(
        report["old_expression_gate"] == "FAIL"
        and report["winner"] == "none"
        and report["semantic_promotion"] is False
        and report["non_regression"] == "NOT_ESTABLISHED"
        and report["judge_calls"] == 0,
        "Claim ceiling changed",
    )
    plan = read(REPO / "configs/v15_5/NATIVE_ANSWER_PLAN.json")
    require(start["plan"] == plan, "Recorded plan differs")
    records = [
        json.loads(line)
        for line in (REPO / "data/v10/functional_train.jsonl").read_text().splitlines()
    ][:2]
    features = read(raw / "FEATURES.json")
    require(
        len(features["renderings"]) == 16
        and all(r["full_logits_exact"] for r in features["native_parity"]),
        "Native feature parity incomplete",
    )
    require(
        len(features["native_parity"]) == report["native_parity_forward_checks"], "Parity count"
    )
    summary = {
        "status": "VERIFIED_ENGINEERING_RECEIPTS",
        "arms": {},
        "source_commit": report["source_commit"],
        "planned_updates": 16,
        "evaluation_rows": 576,
        "generated_sequences": 80,
        "old_expression_gate": "FAIL",
        "winner": "none",
        "semantic_promotion": False,
        "non_regression": "NOT_ESTABLISHED",
        "human_gold": False,
        "validation_scope": "scalar/identity replay; no independent full-tensor reload",
    }
    initial = []
    bank = [
        "# V15.5 native learner: all 80 bounded greedy outputs",
        "",
        "Exposed engineering cases only. Both steps and all conditions are retained.",
        "Strict whole-answer scoring, 16-token budget; old gate remains FAIL.",
        "",
    ]
    for arm in ARMS:
        receipt = read(raw / f"{arm}_REPORT.json")
        require(
            receipt["steps"] == 8
            and receipt["optimizer_membership"]["parameter_elements"] == 4200192,
            "Optimizer scope/budget",
        )
        require(
            receipt["initial_state_sha256"] != receipt["final_state_sha256"], "No finite update"
        )
        initial.append(receipt["initial_state_sha256"])
        training = [
            json.loads(line) for line in (raw / f"{arm}_training.jsonl").read_text().splitlines()
        ]
        require([r["step"] for r in training] == list(range(1, 9)), "Missing/extra training update")
        finite(training)
        weight = 0.0 if arm == "native_answer" else 1.0
        for row in training:
            require(
                (row["pairs"], row["answer_rows"], row["eos_feature_rows"], row["eos_weight"])
                == (16, 32, 32, weight),
                "Training exposure drift",
            )
            c, t = row["components"], plan["training"]
            expected = (
                c["answer_ce"]
                + weight * c["eos_ce"]
                + t["direction_weight"] * c["donor_hinge"]
                + t["stability_weight"] * c["unaffected_gap_square"]
                + t["unrelated_weight"] * c["unrelated_gap_square"]
                + t["residual_penalty"] * c["residual_norm_square"]
            )
            require(
                math.isclose(c["loss"], expected, abs_tol=1e-5, rel_tol=1e-6), "Loss reconstruction"
            )
        require(
            len(receipt["checkpoints"]) == 2
            and all(c["roundtrip_exact"] for c in receipt["checkpoints"]),
            "Checkpoint receipt incomplete",
        )
        value = {
            "training": {"first": training[0]["components"], "last": training[-1]["components"]},
            "evaluation": {},
            "generation": {},
        }
        for step in (0, 1, 8):
            value["evaluation"][str(step)] = eval_summary(
                read(raw / f"{arm}_{step}_evaluation.json")["rows"], records, step
            )
        for step in (0, 8):
            generated = read(raw / f"{arm}_{step}_generation.json")
            value["generation"][str(step)] = generation_summary(generated["rows"], records)
            require(
                len(generated["receipts"]) == 4
                and all(
                    r["base_zero_token_ids_exact"]
                    and r["zero_full_logit_exact_checks"] > 0
                    and r["kv_cache_used"] is False
                    for r in generated["receipts"]
                ),
                "Generation parity",
            )
            for row in generated["rows"]:
                bank.extend(
                    [
                        f"## {arm} / step {step} / w{row['world']} q{row['query']}"
                        f" / {row['condition']}",
                        "",
                        f"Strict correct: {row['strict_correct']}; finish: {row['finish_reason']}; "
                        f"target: {row['target_label']}; tokens: {row['token_count']}.",
                        "",
                        "```text",
                        row["answer"],
                        "```",
                        "",
                    ]
                )
        summary["arms"][arm] = value
    require(len(set(initial)) == 1, "Unmatched initial workspace")
    index = {
        str(path.relative_to(bundle)): digest(path)
        for path in sorted(raw.iterdir())
        if path.is_file() and path.suffix in (".json", ".jsonl")
    }
    return summary, index, "\n".join(bank)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    summary, index, bank = build(args.bundle)
    outputs = {
        "SUMMARY.json": json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
        "ARTIFACT_INDEX.json": json.dumps(index, indent=2, sort_keys=True) + "\n",
        "GENERATION_BANK.md": bank,
    }
    if args.write:
        require(
            not any((args.bundle / name).exists() for name in outputs), "Exclusive artifacts exist"
        )
        for name, text in outputs.items():
            with (args.bundle / name).open("x", encoding="utf-8") as stream:
                stream.write(text)
    else:
        for name, text in outputs.items():
            require((args.bundle / name).read_text() == text, f"Replay differs: {name}")
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "status",
                    "evaluation_rows",
                    "generated_sequences",
                    "old_expression_gate",
                    "non_regression",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
