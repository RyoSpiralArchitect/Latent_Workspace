#!/usr/bin/env python3
"""Derive publication tables and an exact escaped-text bank from sealed receipts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent
REPO = BUNDLE.parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import verify_v15_native_learner as verify  # noqa: E402


def derive(summary):
    rows, bank = [], []
    for phase, result in summary["phases"].items():
        if result["report"] is None:
            continue
        for arm, values in result["arms"].items():
            step = 8 if phase == "reader" else 2
            evaluation = values["evaluation"][str(step)]
            generation = values["generation"][str(step)]
            factors = values["factors"][str(step)]
            output = verify.read(BUNDLE / "raw" / phase / f"{arm}_{step}_generation.json")["rows"]
            keyed = {(r["world"], r["query"], r["condition"]): r for r in output}
            coordinates = [(w, q) for w in range(2) for q in range(2)]
            initial_eval = verify.read(BUNDLE / "raw" / phase / f"{arm}_0_evaluation.json")["rows"]
            final_eval = verify.read(BUNDLE / "raw" / phase / f"{arm}_{step}_evaluation.json")[
                "rows"
            ]
            original = {(r["world"], r["query"], r["control"]): r for r in initial_eval}
            truth = [r for r in final_eval if r["control"] in ("intact", "twin")]
            original_comparison = {}
            for target, field in (("current_base", "base_correct"), ("workspace", "correct")):
                original_comparison[target] = dict(
                    rows=32,
                    correct=sum(r[field] for r in truth),
                    new_errors=sum(
                        original[r["world"], r["query"], r["control"]]["base_correct"]
                        and not r[field]
                        for r in truth
                    ),
                    repaired_errors=sum(
                        not original[r["world"], r["query"], r["control"]]["base_correct"]
                        and r[field]
                        for r in truth
                    ),
                    fresh_holdout=False,
                )
            row = dict(
                phase=phase,
                arm=arm,
                step=step,
                native_correct=sum(
                    evaluation["controls"][c]["correct"] for c in ("intact", "twin")
                ),
                native_denominator=32,
                positive_native_donor=sum(
                    r["donor_signed_change"] > 0 for r in evaluation["unique_affected_pairs"]
                ),
                correct_native_donor_flips=sum(
                    r["both_sides_correct"] for r in evaluation["unique_affected_pairs"]
                ),
                donor_denominator=4,
                workspace_strict=generation["workspace"]["strict_correct"],
                workspace_valid_eos=generation["workspace"]["valid_eos"],
                workspace_length_stops=generation["workspace"]["length_limited"],
                generated_query_denominator=4,
                same_twin_tokens=sum(
                    keyed[w, q, "workspace"]["generated_ids"]
                    == keyed[w, q, "twin"]["generated_ids"]
                    for w, q in coordinates
                ),
                changed_from_current_base=sum(
                    keyed[w, q, "workspace"]["generated_ids"]
                    != keyed[w, q, "base"]["generated_ids"]
                    for w, q in coordinates
                ),
                mean_query_gradient_l2=values["updates"][-1]["mean_query_gradient_l2"],
                final_mean_delta_factors=factors["mean_delta_factors"],
                spectrum_top1=factors["spectrum"]["top_k_frobenius_energy_fraction"]["1"],
                resume_exact=values.get("resume", {}).get("exact"),
                executed_windows=(step + int(phase == "full")),
                updates=values["updates"],
                inline_generation=generation["base_inline"],
                affected_projected_binding=factors["affected_binding"],
                original_base_comparison_exposed_only=original_comparison,
            )
            rows.append(row)
            for observed_step in (0, step):
                path = BUNDLE / "raw" / phase / f"{arm}_{observed_step}_generation.json"
                for r in verify.read(path)["rows"]:
                    bank.append(
                        dict(
                            phase=phase,
                            arm=arm,
                            step=observed_step,
                            **{
                                k: r[k]
                                for k in (
                                    "world",
                                    "query",
                                    "condition",
                                    "answer",
                                    "generated_ids",
                                    "finish_reason",
                                    "target_label",
                                    "valid_eos",
                                    "strict_correct",
                                )
                            },
                            source=str(path.relative_to(BUNDLE)),
                        )
                    )
    return dict(
        source_commit=summary["source_commit"],
        comparisons=rows,
        generated_sequences=len(bank),
        planned_generated_sequences=160,
        stored_evaluation_rows=sum(p["stored_evaluation_rows"] for p in summary["phases"].values()),
        planned_evaluation_rows=1152,
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
        judge_calls=0,
    ), bank


def render_bank(bank):
    lines = [
        "# V15 native learner: literal generation bank",
        "",
        "All strings below are JSON-escaped, preserving whitespace, casing and truncation.",
        "Decode the JSON string to recover exact text; no output is repaired or completed.",
        "Each sequence has a 16-token ceiling. `length` is not valid EOS termination.",
        "The two worlds were exposed during training; these are not holdout results.",
        "",
    ]
    for row in bank:
        key = (
            f"{row['phase']} / {row['arm']} / step {row['step']} / "
            f"w{row['world']} q{row['query']} / {row['condition']}"
        )
        lines.extend(
            [
                f"## {key}",
                "",
                (
                    f"[Raw receipt]({row['source']}); finish `{row['finish_reason']}`; "
                    f"strict correct `{str(row['strict_correct']).lower()}`."
                ),
                "",
                "```json",
                json.dumps(row["answer"], ensure_ascii=False),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def render_table(publication):
    lines = [
        (
            "| Phase / arm | Step | Native correct | Positive donor / correct flips | "
            "Workspace strict | Same intact/twin tokens | Changed vs current base |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in publication["comparisons"]:
        lines.append(
            f"| {r['phase']} / {r['arm']} | {r['step']} | {r['native_correct']}/32 | "
            f"{r['positive_native_donor']}/4 / {r['correct_native_donor_flips']}/4 | "
            f"{r['workspace_strict']}/4 | {r['same_twin_tokens']}/4 | "
            f"{r['changed_from_current_base']}/4 |"
        )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    summary = verify.build(BUNDLE, args.allow_incomplete)
    publication, bank = derive(summary)
    outputs = {
        "GENERATION_BANK.md": render_bank(bank),
        "COMPARISON_TABLE.md": render_table(publication),
    }
    if args.write:
        verify.write_new(BUNDLE / "PUBLICATION.json", publication)
        verify.write_new(BUNDLE / "GENERATION_BANK.json", bank)
        for name, text in outputs.items():
            with (BUNDLE / name).open("x", encoding="utf-8") as stream:
                stream.write(text)
    else:
        verify.require(
            verify.read(BUNDLE / "PUBLICATION.json") == publication, "Publication arithmetic"
        )
        verify.require(verify.read(BUNDLE / "GENERATION_BANK.json") == bank, "Literal bank rows")
        for name, text in outputs.items():
            verify.require(
                (BUNDLE / name).read_text() == text, f"Publication literal differs: {name}"
            )
        decoded = [
            json.loads(value)
            for value in re.findall(
                r"```json\n(.*?)\n```", outputs["GENERATION_BANK.md"], flags=re.S
            )
        ]
        verify.require(decoded == [r["answer"] for r in bank], "Escaped answer roundtrip")
    print(
        json.dumps(
            dict(
                status="PUBLICATION_RECEIPTS_VERIFIED",
                comparisons=len(publication["comparisons"]),
                evaluation_rows=publication["stored_evaluation_rows"],
                generated_sequences=len(bank),
            )
        )
    )


if __name__ == "__main__":
    main()
