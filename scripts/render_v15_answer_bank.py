#!/usr/bin/env python3
"""Render all 64 verified V15 continuations without rewriting or salvaging answers."""

from __future__ import annotations

import argparse
import itertools
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from verify_v15_readout_transport import (  # noqa: E402
    CONDITIONS,
    REGIMES,
    load,
    require,
    verify_bundle,
)


def fenced(text):
    """Keep text verbatim, choosing a delimiter longer than every backtick run."""
    require(isinstance(text, str), "Expected verbatim answer text")
    width = max(3, max((len(run) + 1 for run in re.findall(r"`+", text)), default=3))
    fence = "`" * width
    return fence + "text\n" + text + ("" if text.endswith("\n") else "\n") + fence


def fmt(number):
    return f"{number:.9g}"


def divergence_text(step, *, base=False):
    if base:
        return "reference"
    return "none" if step is None else f"token {step + 1} (step {step})"


def render_verified(generation, features, summary):
    """Formatting-only stage; the caller must supply the verified scalar bundle."""
    rows = generation["rows"]
    require(len(rows) == 64, "Expected all 64 continuations")
    indexed = {(r["world"], r["query"], r["regime"], r["condition"]): r for r in rows}
    expected = set(itertools.product(range(2), range(2), (r["id"] for r in REGIMES), CONDITIONS))
    require(set(indexed) == expected and len(indexed) == len(rows), "Complete answer grid required")
    divergences = {
        (r["world"], r["query"], r["regime"], r["condition"]): r["first_divergence_step"]
        for r in summary["generation"]["first_divergences"]
    }
    spans = {(s["world"], s["query"]): s for s in features["spans"]}
    facts = {
        (f["world"], f["side"]): f["text"] for f in features["facts"] if f["order"] == "original"
    }
    strict = sum(r["strict_correct"] for r in rows)
    unparseable = sum(r["parsed_answer"] is None for r in rows)
    truncated = sum(r["finish_reason"] == "length" for r in rows)
    lines = [
        "# V15 native-readout transport: complete answer bank",
        "",
        "All 64 continuations are shown below in eight matched case/regime groups. "
        "No answer has been selected, shortened, corrected, or relabeled.",
        "",
        f"Strictly correct: **{strict}/64**. Whole-answer unparseable: **{unparseable}/64**. "
        f"Length-capped at 64 new tokens: **{truncated}/64**; "
        f"EOS-terminated: **{64 - truncated}/64**.",
        "",
        "These are two exposed training worlds, not a held-out quality evaluation. "
        "The strict parser accepts only the entire stripped answer `yes` or `no` "
        "(case-insensitive); lowercase compliance is a separate measure. "
        "An initial yes/no token is not rescued as a correct whole answer. "
        "Length-capped outputs remain incorrect. No LLM judge was run.",
        "",
        "`final_*` and `mean_*` use the retained step-256 final-state and question-mean "
        "readers, respectively. `*_twin` targets the counterfactual memory; "
        "other conditions target original memory. Zero controls execute their readers "
        "and match base exactly. `base_inline` puts facts in a different prompt, "
        "so its divergence is not attributed to workspace memory.",
        "",
        "First divergence compares generated token IDs with the matched base continuation "
        "(both one-based token number and zero-based step are shown). Initial logit and "
        "probability shifts compare the selected token against a zero-delta base at the "
        "**same prefix**, not against a different inline prompt. Probabilities are native "
        "temperature-1 softmax values, distinct from sampling-policy probabilities. "
        "All selections use native full-vocabulary logits. Full-prefix recomputation "
        "does not carry continuous hidden state or a KV cache.",
        "",
        "Historical original twin/intact fact lists were independently permuted; their "
        "contrast confounds content and serialization. Neither visible divergence nor "
        "a changed probability establishes isolated semantic causality or improved quality.",
        "",
        "Sources: [raw generation and token traces](raw/GENERATION.json), "
        "[verified scalar summary](SUMMARY.json), [raw feature bindings](raw/FEATURES.json), "
        "[SHA/byte inventory](ARTIFACT_INDEX.json). Numeric displays below are rounded; "
        "the source JSON retains recorded precision. Rendering does not replay tokenizer decoding.",
        "",
    ]
    for w, q, regime in itertools.product(range(2), range(2), REGIMES):
        group = w, q, regime["id"]
        lines.extend(
            [
                f"## World {w}, query {q} — {regime['id']}",
                "",
                f"Seed: {regime['seed']}; temperature: {regime['temperature']}; "
                "maximum new tokens: 64.",
                "",
                "### Common non-inline prompt",
                "",
                fenced(spans[w, q]["rendered_prefix"]),
                "",
                "### Original memory facts (also provided in the inline prompt)",
                "",
                fenced(facts[w, 0]),
                "",
                "### Counterfactual memory facts",
                "",
                fenced(facts[w, 1]),
                "",
                "| Condition | Target | Finish | Tokens | Strict correct "
                "| First divergence from base "
                "| Initial max absolute Δlogit | Initial Δp(chosen) |",
                "| --- | --- | --- | ---: | --- | --- | ---: | ---: |",
            ]
        )
        for condition in CONDITIONS:
            row = indexed[*group, condition]
            first = row["token_trace"][0]
            shift = (
                first["chosen_token_native_probability"]
                - first["same_prefix_base_chosen_token_native_probability"]
            )
            divergence = divergence_text(
                divergences.get((*group, condition)), base=condition == "base"
            )
            lines.append(
                f"| {condition} | {('no', 'yes')[row['target_label']]} | {row['finish_reason']} "
                f"| {row['token_count']} | {str(row['strict_correct']).lower()} | {divergence} "
                f"| {fmt(first['native_logit_change_max_abs'])} | {fmt(shift)} |"
            )
        lines.append("")
        for condition in CONDITIONS:
            row = indexed[*group, condition]
            first = row["token_trace"][0]
            parsed = (
                "unparseable"
                if row["parsed_answer"] is None
                else ("no", "yes")[row["parsed_answer"]]
            )
            lines.extend(
                [
                    f"### {condition}",
                    "",
                    f"Whole-answer parse: **{parsed}**; lowercase compliant: "
                    f"**{str(row['lowercase_compliant']).lower()}**. "
                    f"Initial selected token ID: `{first['token_id']}`; native top-1 changed: "
                    f"**{str(first['native_top1_changed']).lower()}**.",
                    "",
                    "Initial selected-token logit, same-prefix base → condition: "
                    f"`{fmt(first['same_prefix_base_native_logit'])}` → "
                    f"`{fmt(first['chosen_native_logit'])}`. Native probability: "
                    f"`{fmt(first['same_prefix_base_chosen_token_native_probability'])}` → "
                    f"`{fmt(first['chosen_token_native_probability'])}`. "
                    f"Sampling-policy probability: `{fmt(first['sampling_probability'])}`.",
                    "",
                    fenced(row["answer"]),
                    "",
                ]
            )
    return "\n".join(lines)


def render_bundle(bundle):
    result = verify_bundle(bundle)
    require(load(bundle / "SUMMARY.json") == result, "Saved SUMMARY differs from verified scalars")
    return render_verified(
        load(bundle / "raw/GENERATION.json"), load(bundle / "raw/FEATURES.json"), result
    )


def write_or_check(bundle, *, check=False):
    rendered = render_bundle(bundle)
    destination = bundle / "ANSWER_BANK.md"
    if check:
        require(
            destination.is_file()
            and not destination.is_symlink()
            and destination.read_text() == rendered,
            "ANSWER_BANK.md differs from verified render",
        )
    else:
        with destination.open("x", encoding="utf-8") as handle:
            handle.write(rendered)
    return {
        "status": "MATCHED" if check else "CREATED",
        "answers": 64,
        "groups": 8,
        "path": str(destination),
    }


if __name__ == "__main__":
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle", type=Path, default=REPO / "provenance/pilots/v15_readout_transport_20261010"
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    print(json.dumps(write_or_check(args.bundle.resolve(), check=args.check)))
