"""Offline complete-bank analysis and literal human answer bank, no model calls."""

import argparse
import itertools
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import v23_recovered_bank as bank  # noqa: E402

HERE = Path(__file__).resolve().parent
ORIGINAL = ROOT / "provenance/pilots/v23_comparison01_20261022/furnace"
RECOVERED = HERE / "furnace"


def transitions(left, right, key, correct):
    a, b = ({key(r): r for r in rows} for rows in (left, right))
    assert a.keys() == b.keys()
    ids = {k: [] for k in ("both_correct", "base_only", "candidate_only", "both_wrong")}
    for item in a:
        ca, cb = bool(correct(a[item])), bool(correct(b[item]))
        name = (
            "both_correct"
            if ca and cb
            else "base_only"
            if ca
            else "candidate_only"
            if cb
            else "both_wrong"
        )
        ids[name].append(item)
    return dict(n=len(a), counts={k: len(v) for k, v in ids.items()}, ids=ids)


def analyze():
    arms, origins = bank.verify(ORIGINAL, RECOVERED, published_copy=True)
    summaries = {}
    for arm, rows in arms.items():
        summaries[arm] = dict(
            mmlu=dict(
                n=570,
                correct=sum(r["correct"] for r in rows["mmlu"]),
                strict_correct=sum(r["strict_correct"] for r in rows["mmlu"]),
                top_option_ties=sum(r["ties"] > 1 for r in rows["mmlu"]),
            ),
            worlds={
                route: dict(
                    n=96,
                    correct=sum(r["exact_match"] for r in rows["worlds"] if r["route"] == route),
                    stops=dict(
                        Counter(r["stop_reason"] for r in rows["worlds"] if r["route"] == route)
                    ),
                )
                for route in ("latent", "inline")
            },
            free=dict(n=24, stops=dict(Counter(r["stop_reason"] for r in rows["free"]))),
            sequences=216,
            generated_tokens=sum(
                r["generated_tokens"] for name in ("worlds", "free") for r in rows[name]
            ),
        )
    pairs = {}
    for a, b in itertools.combinations(arms, 2):
        pairs[f"{a}:{b}"] = dict(
            mmlu=transitions(
                arms[a]["mmlu"], arms[b]["mmlu"], lambda r: r["id"], lambda r: r["correct"]
            ),
            worlds={
                route: transitions(
                    [r for r in arms[a]["worlds"] if r["route"] == route],
                    [r for r in arms[b]["worlds"] if r["route"] == route],
                    lambda r: r["id"],
                    lambda r: r["exact_match"],
                )
                for route in ("latent", "inline")
            },
            free=dict(
                paired_answers=24,
                changed_token_sequences=sum(
                    x["token_ids"] != y["token_ids"]
                    for x, y in zip(arms[a]["free"], arms[b]["free"], strict=True)
                ),
                changed_texts=sum(
                    x["text"] != y["text"]
                    for x, y in zip(arms[a]["free"], arms[b]["free"], strict=True)
                ),
            ),
        )
    folders = [ORIGINAL / "raw/base", ORIGINAL / "raw/off", RECOVERED / "raw/on"]
    assert len({bank.ex.digest(f / "INPUT_MANIFEST.json") for f in folders}) == 1
    result = dict(
        schema="v23-combined-comparison-offline-analysis-01",
        origins=origins,
        selected_sequences=648,
        original_partial_on_scores_excluded=79,
        arm_summaries=summaries,
        paired=pairs,
        input_manifests_identical=True,
        native_weight_updates=0,
        checkpoint_saves=0,
        weight_deletions=0,
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
        claim_scope=(
            "Previously exposed paired diagnostic. Free answers and MMLU use empty memory; "
            "not proof of workspace use. No quality preference without separately qualified "
            "judge/human review. Twelve free prompts, two seeds; 16 world groups, "
            "not 96 independent worlds."
        ),
    )
    return arms, result


def answer_bank(arms):
    lines = [
        "# V23 complete literal answer bank",
        "",
        "24 matched prompt/seed units; original base/off and whole recovered on. All 72 answers, "
        "including capped/unchanged outputs. No preference labels. Empty-memory/direct generation "
        "is a retention/behavior diagnostic, not evidence of workspace use.",
        "",
    ]
    for index, row in enumerate(arms["base"]["free"]):
        values = [arms[a]["free"][index]["text"] for a in arms]
        fence = "`" * max(
            3, 1 + max((len(m) for v in values for m in re.findall(r"`+", v)), default=0)
        )
        lines.extend([f"## {row['id']} · seed {row['seed']}", "", row["prompt"], ""])
        for arm in arms:
            r = arms[arm]["free"][index]
            lines.extend(
                [
                    f"### {arm} · {r['stop_reason']} · "
                    f"{r['generated_tokens']}/{r['max_new_tokens']} tokens",
                    "",
                    fence + "text",
                    r["text"],
                    fence,
                    "",
                ]
            )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "write"))
    args = parser.parse_args()
    arms, result = analyze()
    target = HERE / "analysis"
    text = answer_bank(arms)
    if args.command == "write":
        target.mkdir(exist_ok=False)
        bank.ex.write_new(target / "ANALYSIS.json", result)
        with (target / "ANSWER_BANK.md").open("x") as stream:
            stream.write(text)
        bank.ex.write_new(target / "MANIFEST.json", bank.ex.manifest(target))
    if target.exists():
        assert bank.ex.read(target / "ANALYSIS.json") == result
        assert (target / "ANSWER_BANK.md").read_text() == text
        actual = bank.ex.manifest(target)
        actual.pop("MANIFEST.json")
        assert actual == bank.ex.read(target / "MANIFEST.json")
    print(json.dumps({k: v for k, v in result.items() if k not in ("origins", "paired")}, indent=2))


if __name__ == "__main__":
    main()
