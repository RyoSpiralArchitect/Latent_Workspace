"""Text-only cue-by-envelope inputs and integer accounting, frozen before scoring."""

from __future__ import annotations

import hashlib
import itertools
import json
import random
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path

import v15_elicitation_inputs as old
from v13_task_fixture import NAMES, TEMPLATES, _parse_context, _parse_query, symbolic_oracle
from v15_assay_summary import parse_functional_answer
from v15_completion_mass import analyze_row, bind_aliases
from v15_cue_span import bind_cue_question_span
from verify_ft_beta_query_pool import require

REPO = Path(__file__).resolve().parents[1]
SEED, FAMILIES = 15002, 16
RENDERERS, CUES, INFORMATION = (
    ("raw", "native_chat"),
    ("present", "absent"),
    ("query_only", "inline"),
)
KEYS = ("case_id", "renderer", "cue", "information")
META = ("case_id", "family_id", "view", "wording", "split", "target_label")
REGIME = {"id": "greedy", "seed": 0, "temperature": 0.0}


def make_cases(repo=REPO):
    historical = old.known_orders(repo)
    exposed = old.make_cases(repo)
    prior_orders = {
        tuple(_parse_context(c["context"])[0]) for c in exposed if c["view"] == "full_chain"
    }
    require(len(historical) == 640 and len(prior_orders) == 8, "Prior-order denominator")
    excluded = historical | prior_orders
    atomic_pairs = {
        frozenset(_parse_query(c["query"]))
        for c in exposed
        if c["view"] in ("atomic", "historical")
    }
    initial_pairs = len(atomic_pairs)
    rng, fact_rng = random.Random(SEED), random.Random(SEED ^ 0x15FAC7)
    cases, worlds = [], []
    for i in range(FAMILIES):
        for _ in range(4096):
            order = tuple(rng.sample(NAMES, 6))
            adjacent, chain = rng.randrange(5), rng.randrange(3)
            pair = frozenset(order[adjacent : adjacent + 2])
            if order not in excluded and pair not in atomic_pairs:
                break
        else:
            raise ValueError("Structural rejection budget exhausted")
        excluded.add(order)
        atomic_pairs.add(pair)
        positions = list(range(5))
        fact_rng.shuffle(positions)
        family = f"v15-cue-seed{SEED}-family{i:04d}"
        wording = "ranked_above" if i % 2 == 0 else "outrank"
        worlds.append(
            {
                "family_id": family,
                "order": list(order),
                "atomic_edge": adjacent,
                "chain_start": chain,
                "fact_positions": positions,
            }
        )
        for view, first, hop, facts in (
            ("atomic", adjacent, 1, [adjacent]),
            ("full_chain", chain, 3, positions),
        ):
            context = old._context(order, facts)
            pair = (order[first], order[first + hop])
            for direction, (left, right) in enumerate((pair, pair[::-1])):
                query = TEMPLATES[wording].format(left=left, right=right)
                cases.append(
                    {
                        "case_id": f"{family}_{view}_d{direction}",
                        "family_id": family,
                        "split": "confirmation",
                        "view": view,
                        "wording": wording,
                        "target_label": symbolic_oracle(context, query),
                        "query": query,
                        "context": context,
                        "hop": hop,
                    }
                )
    require(len(cases) == 64 and len({c["case_id"] for c in cases}) == 64, "Case denominator")
    return {
        "cases": cases,
        "worlds": worlds,
        "exclusion": {
            "historical_orders": len(historical),
            "elicitation_orders": len(prior_orders),
            "union_orders": len(historical | prior_orders),
            "prior_atomic_unordered_pairs": initial_pairs,
            "new_unique_atomic_unordered_pairs": FAMILIES,
        },
    }


def user_content(query, context, cue, information):
    require(cue in CUES and information in INFORMATION, "Unknown cue/information")
    _parse_query(query)
    _parse_context(context)
    require(query.endswith(" Answer:"), "Canonical query suffix changed")
    inference_query = query if cue == "present" else query[:-8]
    # len(' Answer:') == 8; no other character is changed.
    content = old.SYMMETRIC_INSTRUCTION + "\n\n" + inference_query
    return context + "\n\n" + content if information == "inline" else content


def render_case(tokenizer, *, query, context, renderer, cue, information):
    require(renderer in RENDERERS, "Unknown renderer")
    content = user_content(query, context, cue, information)
    template = tokenizer.get_chat_template()
    messages = [{"role": "user", "content": content}]
    text, native_ids = content, None
    if renderer == "native_chat":
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        encoded = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True)
        native_ids = old._token_ids(
            encoded.get("input_ids") if isinstance(encoded, Mapping) else encoded, "Native IDs"
        )
    ids = old._token_ids(tokenizer.encode(text, add_special_tokens=False), "Prefix IDs")
    require(text.count(content) == 1 and 1 <= len(ids) <= 512, "Content/truncation contract")
    require(native_ids is None or ids == native_ids, "Native tokenization mismatch")
    require(len(ids) < 2 or ids[:2] != [tokenizer.bos_token_id] * 2, "Double BOS")
    aliases = bind_aliases(tokenizer, text, ids)
    candidates = [
        next(a["token_id"] for a in aliases if suffix in a["suffixes"])
        for suffix in (" no", " yes")
    ]
    span = asdict(
        bind_cue_question_span(
            tokenizer,
            raw_query=query,
            rendered_prefix=text,
            expected_prefix_ids=ids,
            allow_native_end=renderer == "native_chat" and cue == "absent",
        )
    )
    # Convert tuples now so saved JSON and regenerated in-memory receipts agree.
    span = json.loads(json.dumps(span))
    result = {
        "renderer": renderer,
        "cue": cue,
        "information": information,
        "text": text,
        "user_content": content,
        "prompt_ids": ids,
        "span": span,
        "candidate_ids": candidates,
        "candidate_suffixes": [" no", " yes"],
        "aliases": aliases,
        "chat_template": {
            "sha256": hashlib.sha256(template.encode()).hexdigest(),
            "applied": renderer == "native_chat",
            "add_generation_prompt": renderer == "native_chat",
            "messages": "single_user_no_system" if renderer == "native_chat" else None,
            "native_tokenization_exact": True if native_ids is not None else None,
        },
    }
    if cue == "present":
        legacy = old.render_case(
            tokenizer, query=query, context=context, renderer=renderer, information=information
        )
        require(
            {k: v for k, v in result.items() if k not in ("cue", "aliases")}
            == json.loads(json.dumps(legacy)),
            "Present cue failed legacy rendering parity",
        )
    return result


def expected_grid(cases):
    return set(itertools.product((c["case_id"] for c in cases), RENDERERS, CUES, INFORMATION))


def _groups(rows, dimensions, stage):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[k] for k in dimensions)].append(row)
    out = []
    for key, selected in sorted(groups.items()):

        def correct(r):
            return r["strict_correct"] if stage == "generation" else r[stage]["correct"]

        pairs = defaultdict(list)
        for row in selected:
            pairs[
                tuple(row[k] for k in ("renderer", "cue", "information", "family_id", "view"))
            ].append(row)
        require(
            all(len(v) == 2 and {r["target_label"] for r in v} == {0, 1} for v in pairs.values()),
            "Reciprocal accounting",
        )
        record = {
            **dict(zip(dimensions, key)),
            "total": len(selected),
            "correct": sum(correct(r) for r in selected),
            "labels": {
                str(label): {
                    "total": sum(r["target_label"] == label for r in selected),
                    "correct": sum(correct(r) for r in selected if r["target_label"] == label),
                }
                for label in (0, 1)
            },
            "reciprocal_pairs": {
                "total": len(pairs),
                "both_correct": sum(all(correct(r) for r in pair) for pair in pairs.values()),
            },
        }
        if stage == "generation":
            record.update(
                valid_eos=sum(r["valid_eos"] for r in selected),
                eos=sum(r["finish_reason"] == "eos" for r in selected),
                length=sum(r["finish_reason"] == "length" for r in selected),
                lowercase_compliant=sum(r["lowercase_compliant"] for r in selected),
            )
        else:
            record["ties"] = sum(r[stage]["prediction"] is None for r in selected)
        out.append(record)
    return out


def summarize(cases, scores, generations, plan):
    expected, indexed = expected_grid(cases), {c["case_id"]: c for c in cases}
    scored, generated = [], []
    for values, kind in ((scores, "scores"), (generations, "generation")):
        require(len(values) == len(expected) == 512, f"{kind} denominator")
        seen = set()
        for row in values:
            key = tuple(row[k] for k in KEYS)
            require(key in expected and key not in seen, f"{kind} duplicate/unknown")
            seen.add(key)
            case = indexed[row["case_id"]]
            require(all(row[k] == case[k] for k in META), "Metadata identity")
            if kind == "scores":
                scored.append({**analyze_row(row), "cue": row["cue"]})
            else:
                parsed = parse_functional_answer(row["answer"])
                valid = parsed is not None and row["finish_reason"] == "eos"
                correct = valid and parsed == case["target_label"]
                require(
                    row["parsed_answer"] == parsed
                    and row["valid_eos"] is valid
                    and row["strict_correct"] is correct
                    and row["lowercase_compliant"] is (row["answer"].strip() in ("no", "yes")),
                    "Whole-answer accounting",
                )
                generated.append(row)
    dimensions = ("renderer", "cue", "information", "view", "wording")
    sections = {
        stage: {
            "cells": _groups(generated if stage == "generation" else scored, dimensions, stage),
            "by_view": _groups(
                generated if stage == "generation" else scored, dimensions[:4], stage
            ),
            "by_method": _groups(
                generated if stage == "generation" else scored, dimensions[:3], stage
            ),
        }
        for stage in ("generation", "lowercase", "alias_start", "completion")
    }
    gates = []
    for renderer, cue in itertools.product(RENDERERS, CUES):
        chosen = [
            r
            for r in generated
            if r["renderer"] == renderer and r["cue"] == cue and r["information"] == "inline"
        ]
        views = _groups(chosen, ("view",), "generation")
        cells = _groups(chosen, ("view", "wording"), "generation")
        valid = sum(r["valid_eos"] for r in chosen)
        passed = (
            valid == 64
            and all(
                r["total"] == 32
                and r["correct"] >= 24
                and all(v["total"] == 16 and v["correct"] >= 12 for v in r["labels"].values())
                for r in views
            )
            and all(r["total"] == 16 and r["correct"] >= 12 for r in cells)
        )
        gates.append(
            {
                "renderer": renderer,
                "cue": cue,
                "status": "PASS" if passed else "FAIL",
                "valid_eos": valid,
                "correct": sum(r["strict_correct"] for r in chosen),
                "total": 64,
                "prospective_primary": {"renderer": renderer, "cue": cue, "information": "inline"}
                == plan["primary"],
            }
        )
    contrasts = []
    for renderer, information, view in itertools.product(
        RENDERERS, INFORMATION, ("atomic", "full_chain")
    ):
        pairs = defaultdict(dict)
        for r in generated:
            if (r["renderer"], r["information"], r["view"]) == (renderer, information, view):
                pairs[r["case_id"]][r["cue"]] = r
        require(
            len(pairs) == 32 and all(set(p) == set(CUES) for p in pairs.values()), "Paired cue grid"
        )
        contrasts.append(
            {
                "renderer": renderer,
                "information": information,
                "view": view,
                "total": len(pairs),
                "corrected_by_removal": sum(
                    p["absent"]["strict_correct"] and not p["present"]["strict_correct"]
                    for p in pairs.values()
                ),
                "regressed_by_removal": sum(
                    p["present"]["strict_correct"] and not p["absent"]["strict_correct"]
                    for p in pairs.values()
                ),
                "generated_ids_changed": sum(
                    p["present"]["generated_ids"] != p["absent"]["generated_ids"]
                    for p in pairs.values()
                ),
            }
        )
    return {
        "format": "v15-cue-confirmation-summary-v1",
        "denominators": {
            "families": 16,
            "cases": 64,
            "prefixes": len(scores),
            "generation_sequences": len(generations),
        },
        **sections,
        "gates": gates,
        "primary_expression_gate": next(g["status"] for g in gates if g["prospective_primary"]),
        "paired_cue_removal": contrasts,
        "method_selected_after_results": False,
        "automatic_training": False,
        "claim_ceiling": (
            "finite fresh-instance base expression panel only; not semantic, quality, "
            "non-regression or causal fact-use qualification"
        ),
    }
