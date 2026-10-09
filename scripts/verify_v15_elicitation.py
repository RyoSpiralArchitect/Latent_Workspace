#!/usr/bin/env python3
"""Portable V15 base-elicitation accounting; no model, decoding or tensor replay.

The native-chat renderer is prospective, not selected from this panel's scores.
Initial two-choice scores are diagnostics, never repairs to generated answers.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts"), str(REPO / "src")]
from v15_assay_summary import _scores, parse_functional_answer  # noqa: E402
from verify_ft_beta_query_pool import (  # noqa: E402
    BASE_HASH,
    digest,
    finite_tree,
    load,
    require,
    sha,
    verify_resources,
    write_new,
)
from verify_v15_readout_transport import (  # noqa: E402
    number,
)
from verify_v15_readout_transport import (  # noqa: E402
    verify_bundle as verify_predecessor,
)

from latent_workspace_ft_v10.answer_bank_generation import matched_uniform  # noqa: E402

PLAN_PATH = "configs/v15/ELICITATION_PLAN.json"
RAW_NAMES = {
    "STARTED.json",
    "CASES.json",
    "RENDERINGS.json",
    "CHOICES.json",
    "GENERATION.json",
    "REPORT.json",
    "RESOURCES.jsonl",
}
RENDERERS = ("raw", "native_chat")
INFORMATION = ("query_only", "inline")
REGIMES = [
    {"id": "greedy", "seed": 0, "temperature": 0.0},
    {"id": "sample211", "seed": 211, "temperature": 0.7},
]
CONDITIONS = {"query_only": "base", "inline": "base_inline"}
DIMENSIONS = ("renderer", "information", "split", "view", "wording")
SOURCE_ADDITIONS = {
    PLAN_PATH,
    "docs/v15/ELICITATION_PLAN.md",
    "scripts/run_v15_elicitation.py",
    "scripts/v15_elicitation_inputs.py",
    "scripts/verify_v15_elicitation.py",
    "scripts/verify_v15_readout_transport.py",
    "scripts/v13_task_fixture.py",
    "configs/v14/MISTRAL_PROMPT_GATE_PLAN.json",
}
CLAIM_CEILING = (
    "finite-panel expression qualification, not causal fact-use or model-quality qualification"
)


def validate_cases(cases):
    require(isinstance(cases, list) and len(cases) == 36, "Case denominator")
    indexed = {}
    for case in cases:
        identity = case["case_id"]
        require(isinstance(identity, str) and identity and identity not in indexed, "Case identity")
        require(type(case["target_label"]) is int and case["target_label"] in (0, 1), "Case label")
        require(case["split"] in ("exposed", "confirmation"), "Case split")
        require(case["view"] in ("historical", "atomic", "full_chain"), "Case view")
        require(isinstance(case["wording"], str) and case["wording"], "Case wording")
        indexed[identity] = case
    require(sum(c["split"] == "exposed" for c in cases) == 4, "Exposed denominator")
    confirmation = [c for c in cases if c["split"] == "confirmation"]
    require(len(confirmation) == 32, "Confirmation denominator")
    expected = set(itertools.product(("atomic", "full_chain"), ("ranked_above", "outrank")))
    actual = {(c["view"], c["wording"]) for c in confirmation}
    require(actual == expected, "Confirmation view/wording grid")
    for view, wording in expected:
        labels = [
            c["target_label"] for c in confirmation if (c["view"], c["wording"]) == (view, wording)
        ]
        require(len(labels) == 8 and sum(labels) == 4, "Confirmation balance")
    return indexed


def _group(rows, dimensions, kind):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[k] for k in dimensions)].append(row)
    result = []
    for key, selected in sorted(groups.items()):
        cell = dict(zip(dimensions, key))
        cell["total"] = len(selected)

        def correct(row):
            return (
                row["strict_correct"]
                if kind != "choice"
                else row["native"]["prediction"] == row["target_label"]
            )

        cell["label_correct"] = {}
        for label, name in ((0, "no"), (1, "yes")):
            labeled = [r for r in selected if r["target_label"] == label]
            count = sum(correct(r) for r in labeled)
            cell["label_correct"][name] = {
                "correct": count,
                "total": len(labeled),
                "recall": count / len(labeled) if labeled else None,
            }
        pairs = defaultdict(list)
        for row in selected:
            if row["split"] == "confirmation":
                pairs[row["family_id"], row["view"], row["wording"]].append(row)
        require(
            all(
                len(pair) == 2 and {r["target_label"] for r in pair} == {0, 1}
                for pair in pairs.values()
            ),
            "Reciprocal pair accounting",
        )
        cell["reciprocal_pairs"] = {
            "total": len(pairs),
            "both_correct": sum(all(correct(r) for r in pair) for pair in pairs.values()),
        }
        if kind == "choice":
            cell.update(
                correct=sum(r["native"]["prediction"] == r["target_label"] for r in selected),
                ties=sum(r["native"]["prediction"] is None for r in selected),
            )
        else:
            cell.update(
                strict_correct=sum(r["strict_correct"] for r in selected),
                valid_eos=sum(r["valid_eos"] for r in selected),
                unparseable=sum(r["parsed_answer"] is None for r in selected),
                length_truncated=sum(r["finish_reason"] == "length" for r in selected),
                lowercase_compliant=sum(r["lowercase_compliant"] for r in selected),
            )
        result.append(cell)
    return result


def _paired(rows, generation):
    groups = defaultdict(dict)
    dimensions = ("renderer", "split", "view", "wording") + (("regime",) if generation else ())
    for row in rows:
        key = tuple(row[k] for k in dimensions) + (row["case_id"],)
        correct = (
            row["strict_correct"]
            if generation
            else row["native"]["prediction"] == row["target_label"]
        )
        groups[key][row["information"]] = correct
    cells = defaultdict(list)
    for key, pair in groups.items():
        require(set(pair) == set(INFORMATION), "Missing paired information condition")
        cells[key[:-1]].append(pair)
    return [
        {
            **dict(zip(dimensions, key)),
            "total": len(pairs),
            "query_only_correct": sum(p["query_only"] for p in pairs),
            "inline_correct": sum(p["inline"] for p in pairs),
            "rescued_by_inline": sum(p["inline"] and not p["query_only"] for p in pairs),
            "regressed_with_inline": sum(p["query_only"] and not p["inline"] for p in pairs),
            "net_correct_change": sum(int(p["inline"]) - int(p["query_only"]) for p in pairs),
        }
        for key, pairs in sorted(cells.items())
    ]


def summarize(cases, choice_rows, generation_rows, plan):
    """Recompute strict scalar results and the fixed finite-panel expression gate."""
    finite_tree([cases, choice_rows, generation_rows, plan])
    case_index = validate_cases(cases)
    require(
        plan["renderers"] == list(RENDERERS) and plan["information"] == list(INFORMATION),
        "Renderer/information contract",
    )
    require(plan["regimes"] == REGIMES and plan["max_new_tokens"] == 64, "Decoding contract")
    require(plan["primary_renderer"] == "native_chat", "Prospective renderer changed")
    require(
        plan["gate"]
        == {
            "scope": CLAIM_CEILING,
            "split": "confirmation",
            "information": "inline",
            "regime": "greedy",
            "valid_eos_required": 32,
            "correct_per_view_required": 12,
            "per_view_denominator": 16,
            "correct_per_view_wording_required": 6,
            "per_view_wording_denominator": 8,
        },
        "Expression gate changed",
    )
    expected = set(itertools.product(case_index, RENDERERS, INFORMATION))
    require(len(choice_rows) == len(expected), "Choice denominator")
    choices, seen = [], set()
    for row in choice_rows:
        key = tuple(row[k] for k in ("case_id", "renderer", "information"))
        require(key in expected and key not in seen, "Choice cell duplicate/unknown")
        seen.add(key)
        case = case_index[row["case_id"]]
        if "target_label" in row:
            require(row["target_label"] == case["target_label"], "Choice target drift")
        choices.append(
            {
                **row,
                **{k: case[k] for k in ("split", "view", "wording", "target_label", "family_id")},
                "native": _scores(row["native"], "initial native choice"),
            }
        )
    expected_generation = {
        *itertools.product(case_index, RENDERERS, INFORMATION, (r["id"] for r in REGIMES))
    }
    require(len(generation_rows) == len(expected_generation), "Generation denominator")
    generated, seen = [], set()
    for row in generation_rows:
        key = tuple(row[k] for k in ("case_id", "renderer", "information", "regime"))
        require(key in expected_generation and key not in seen, "Generation cell duplicate/unknown")
        seen.add(key)
        case = case_index[row["case_id"]]
        require(row["finish_reason"] in ("eos", "length"), "Termination contract")
        parsed = parse_functional_answer(row["answer"])
        valid = parsed is not None and row["finish_reason"] == "eos"
        require(row["target_label"] == case["target_label"], "Generation target drift")
        require(
            row["parsed_answer"] == parsed
            and (row["parsed_answer"] is None or type(row["parsed_answer"]) is int),
            "Whole-answer parser mismatch",
        )
        require(row["valid_eos"] is valid, "Valid EOS mismatch")
        require(
            row["strict_correct"] is (valid and parsed == case["target_label"]),
            "Strict correctness mismatch",
        )
        require(
            row["lowercase_compliant"] is (row["answer"].strip() in ("no", "yes")),
            "Lowercase compliance mismatch",
        )
        generated.append({**row, **{k: case[k] for k in ("split", "view", "wording", "family_id")}})
    gates = {}
    for renderer in RENDERERS:
        selected = [
            r
            for r in generated
            if r["renderer"] == renderer
            and r["split"] == "confirmation"
            and r["information"] == "inline"
            and r["regime"] == "greedy"
        ]
        by_view = _group(selected, ("view",), "generation")
        by_wording = _group(selected, ("view", "wording"), "generation")
        valid = sum(r["valid_eos"] for r in selected)
        passed = (
            valid == 32
            and all(r["total"] == 16 and r["strict_correct"] >= 12 for r in by_view)
            and all(r["total"] == 8 and r["strict_correct"] >= 6 for r in by_wording)
        )
        gates[renderer] = {
            "status": "PASS" if passed else "FAIL",
            "total": len(selected),
            "valid_eos": valid,
            "by_view": by_view,
            "by_view_wording": by_wording,
            "prospective_primary": renderer == "native_chat",
        }
    return {
        "format": "v15-base-elicitation-summary-v1",
        "denominators": {"cases": 36, "choices": 144, "generation_sequences": 288},
        "choices": {
            "cells": _group(choices, DIMENSIONS, "choice"),
            "by_renderer_information_split": _group(choices, DIMENSIONS[:3], "choice"),
            "paired_inline_minus_query": _paired(choices, False),
        },
        "generation": {
            "cells": _group(generated, (*DIMENSIONS, "regime"), "generation"),
            "by_renderer_information_split_regime": _group(
                generated, (*DIMENSIONS[:3], "regime"), "generation"
            ),
            "paired_inline_minus_query": _paired(generated, True),
        },
        "expression_gates": gates,
        "primary_renderer": "native_chat",
        "primary_expression_gate": gates["native_chat"]["status"],
        "method_selected": False,
        "claim_ceiling": CLAIM_CEILING,
    }


def verify_renderings(rows, cases, plan):
    from v15_elicitation_inputs import SYMMETRIC_INSTRUCTION

    indexed = {}
    case_index = {c["case_id"]: c for c in cases}
    expected = set(itertools.product(case_index, RENDERERS, INFORMATION))
    require(len(rows) == 144, "Rendering denominator")
    template_hashes = set()
    for row in rows:
        key = tuple(row[k] for k in ("case_id", "renderer", "information"))
        require(key in expected and key not in indexed, "Rendering duplicate/unknown")
        indexed[key] = row
        case = case_index[row["case_id"]]
        user = SYMMETRIC_INSTRUCTION + "\n\n" + case["query"].strip()
        if row["information"] == "inline":
            user = case["context"] + "\n\n" + user
        require(row["user_content"] == user, "Label-independent inference content")
        require(isinstance(row["text"], str) and row["text"].count(user) == 1, "Rendering content")
        ids = row["prompt_ids"]
        require(
            isinstance(ids, list)
            and 1 <= len(ids) <= plan["maximum_prompt_tokens"]
            and all(type(t) is int and t >= 0 for t in ids),
            "Prompt IDs/bound",
        )
        require(
            row["candidate_ids"] == [1476, 5849] and row["candidate_suffixes"] == [" no", " yes"],
            "Candidate token binding",
        )
        span = row["span"]
        question = case["query"].strip().removesuffix("Answer:").strip()
        require(
            span["question"] == question and span["prefix_ids"] == ids, "Question prefix binding"
        )
        start, end = span["character_start"], span["character_end"]
        require(
            type(start) is int
            and type(end) is int
            and 0 <= start < end <= len(row["text"])
            and row["text"][start:end] == question,
            "Question text span",
        )
        require(
            span["rendered_prefix_sha256"] == hashlib.sha256(row["text"].encode()).hexdigest(),
            "Rendered prefix hash",
        )
        indices = span["token_indices"]
        require(
            isinstance(indices, list)
            and indices
            and all(type(t) is int and 0 <= t < len(ids) for t in indices)
            and indices == sorted(set(indices)),
            "Question token span receipt",
        )
        template = row["chat_template"]
        require(sha(template["sha256"]), "Chat template identity")
        template_hashes.add(template["sha256"])
        applied = row["renderer"] == "native_chat"
        require(
            template
            == {
                "sha256": template["sha256"],
                "applied": applied,
                "add_generation_prompt": applied,
                "messages": "single_user_no_system" if applied else None,
                "native_tokenization_exact": True if applied else None,
            },
            "Chat template receipt",
        )
        require(row["text"] != user if applied else row["text"] == user, "Raw/chat distinction")
    require(set(indexed) == expected and len(template_hashes) == 1, "Rendering/template coverage")
    return indexed


def verify_generation(value, cases, renderings, plan, old_rows):
    rows = value["rows"]
    require(value["eos_token_ids"] == [2], "Pinned EOS policy")
    indexed = {}
    case_index = {c["case_id"]: c for c in cases}
    for row in rows:
        key = tuple(row[k] for k in ("case_id", "renderer", "information", "regime"))
        require(key not in indexed, "Duplicate generation token record")
        indexed[key] = row
        case, condition = case_index[row["case_id"]], CONDITIONS[row["information"]]
        regime = next(r for r in REGIMES if r["id"] == row["regime"])
        require(
            row["condition"] == condition
            and row["id"] == f"{row['case_id']}__{regime['id']}__{condition}__{row['renderer']}"
            and row["regime_parameters"] == regime,
            "Generation identity/decoding policy",
        )
        require(
            all(row[k] == case[k] for k in ("split", "family_id", "view", "wording")),
            "Generation case metadata",
        )
        require(
            row["prompt_ids"] == renderings[key[:3]]["prompt_ids"], "Generation rendered prefix"
        )
        ids, trace = row["generated_ids"], row["token_trace"]
        require(
            isinstance(ids, list)
            and 1 <= len(ids) <= 64
            and all(type(t) is int and t >= 0 for t in ids)
            and row["token_count"] == len(ids) == len(trace),
            "Generated token denominator",
        )
        require(2 not in ids[:-1], "Continued after EOS")
        require(
            (ids[-1] == 2 and row["finish_reason"] == "eos")
            or (ids[-1] != 2 and len(ids) == 64 and row["finish_reason"] == "length"),
            "EOS/length termination",
        )
        for step, token in enumerate(trace):
            require(
                token["step"] == step
                and token["token_id"] == ids[step]
                and token["uniform"] == matched_uniform(row["case_id"], regime["seed"], step),
                "Matched uniform/token trace",
            )
            for name in (
                "sampling_probability",
                "chosen_token_native_probability",
                "same_prefix_base_chosen_token_native_probability",
            ):
                number(token[name], name, 0, 1)
            number(token["chosen_native_logit"], "chosen native logit")
            for name in ("native_top1_token_id", "same_prefix_base_native_top1_token_id"):
                require(type(token[name]) is int and token[name] >= 0, "Native top1 token ID")
            require(
                all(
                    token[name] == 0
                    for name in (
                        "delta_l2",
                        "native_applied_delta_l2",
                        "native_applied_fraction",
                        "native_logit_change_max_abs",
                        "native_logit_change_l2",
                    )
                )
                and token["native_top1_changed"] is False
                and token["chosen_native_logit"] == token["same_prefix_base_native_logit"]
                and token["native_top1_token_id"] == token["same_prefix_base_native_top1_token_id"]
                and token["chosen_token_native_probability"]
                == token["same_prefix_base_chosen_token_native_probability"],
                "Base-only zero readout trace",
            )
            if regime["temperature"] == 0:
                require(
                    token["sampling_probability"] == 1
                    and token["token_id"] == token["native_top1_token_id"],
                    "Greedy token selection",
                )
    receipts = value["receipts"]
    expected = set(itertools.product(case_index, RENDERERS, (r["id"] for r in REGIMES)))
    require(len(receipts) == len(expected) == 144, "Generation receipt denominator")
    seen, total_decoder = set(), 0
    for receipt in receipts:
        group = tuple(receipt[k] for k in ("case_id", "renderer", "regime"))
        require(group in expected and group not in seen, "Generation receipt duplicate/unknown")
        seen.add(group)
        current = [indexed[group[0], group[1], info, group[2]] for info in INFORMATION]
        counts = [
            len(
                {
                    tuple(r["prompt_ids"] + r["generated_ids"][:step])
                    for r in current
                    if r["token_count"] > step
                }
            )
            for step in range(max(r["token_count"] for r in current))
        ]
        calls = sum(counts)
        require(
            receipt["decoder_calls"] == calls
            and receipt["maximum_concurrent_prefixes"] == max(counts)
            and receipt["shared_historical_native_checks"] == calls,
            "Generation decoder/native-check accounting",
        )
        require(
            receipt["zero_full_logit_exact_checks"] == 0
            and receipt["zero_full_logit_exact_checks_by_condition"] == {}
            and receipt["zero_pairs"] == []
            and receipt["base_zero_token_ids_exact"] is True
            and receipt["persistent_prefix_cache_entries"] == 0
            and receipt["kv_cache_used"] is False
            and receipt["readout_contract"] == "shared_native_full_sequence_full_vocabulary"
            and receipt["logit_reference"] == "base_at_same_current_prefix"
            and receipt["reader_span_owner"] == "backend_bound_original_prompt",
            "Generation no-workspace/no-cache contract",
        )
        total_decoder += calls
    old_index = {(r["case_id"], r["regime"], r["condition"]): r for r in old_rows}
    replay = 0
    for row in rows:
        if row["split"] == "exposed" and row["renderer"] == "raw":
            old = old_index[row["case_id"], row["regime"], row["condition"]]
            require(
                all(
                    row[k] == old[k]
                    for k in (
                        "prompt_ids",
                        "generated_ids",
                        "answer",
                        "finish_reason",
                        "token_trace",
                    )
                ),
                "Historical raw generation replay",
            )
            replay += 1
    require(replay == 16, "Historical raw replay denominator")
    return {
        "decoder_calls": total_decoder,
        "shared_historical_native_checks": total_decoder,
        "raw_replay_exact_sequences": replay,
    }


def verify_contracts(bundle, repo=REPO):
    from v15_elicitation_inputs import make_cases

    raw = bundle / "raw"
    require(
        raw.is_dir() and not raw.is_symlink() and {p.name for p in raw.iterdir()} == RAW_NAMES,
        "Raw artifact inventory",
    )
    data = {name: load(raw / name) for name in RAW_NAMES}
    started, report = data["STARTED.json"], data["REPORT.json"]
    plan = load(repo / PLAN_PATH)
    require(started["plan"] == plan, "Frozen plan identity")
    require(
        plan["format"] == "v15-base-elicitation-v1"
        and plan["predecessor_bundle"] == "provenance/pilots/v15_readout_transport_20261010"
        and plan["model_parent"] == "configs/v14/PRECISION_BRIDGE_PLAN.json"
        and plan["corpus_seed"] == 15001
        and plan["exposed_cases"] == 4
        and plan["confirmation_families"] == 8
        and plan["confirmation_cases"] == 32
        and plan["maximum_prompt_tokens"] == 512
        and plan["expected_unique_prefixes"] == 144
        and plan["expected_generation_sequences"] == 288
        and plan["optimizer_steps"] == 0
        and plan["workspace_loaded"] is False,
        "Frozen base-only/corpus contract",
    )
    require(
        plan["stop_rule"] == "model EOS only; otherwise length at 64 new tokens"
        and plan["parser"]
        == (
            "whole stripped answer yes/no, casefolded; lowercase compliance separate; "
            "length-truncated is incorrect"
        )
        and plan["choice_suffixes"] == [" no", " yes"]
        and plan["history"] == "full-prefix recomputation; no KV cache",
        "Frozen parser/history contract",
    )
    predecessor = repo / plan["predecessor_bundle"]
    require(
        verify_predecessor(predecessor, repo)["status"] == "VERIFIED_RECEIPTS",
        "Predecessor verification",
    )
    old_started = load(predecessor / "raw/STARTED.json")
    require(plan["resources"] == old_started["plan"]["resources"], "Resource contract")
    require(
        started["runtime"] == load(repo / plan["model_parent"])["expected_runtime"]
        and re.fullmatch(r"[0-9a-f]{40}", started["source_commit"]) is not None,
        "Runtime/source identity",
    )
    hashes = started["source_hashes"]
    require(set(hashes) == set(old_started["source_hashes"]) | SOURCE_ADDITIONS, "Source coverage")
    for name, expected in hashes.items():
        require(sha(expected) and digest(repo / name) == expected, f"Source hash mismatch: {name}")
    require(
        all(hashes[k] == v for k, v in old_started["source_hashes"].items()),
        "Historical source changed",
    )
    cases = data["CASES.json"]
    require(cases == make_cases(repo), "Frozen corpus graph/label regeneration")
    renderings = verify_renderings(data["RENDERINGS.json"], cases, plan)
    tokenizer = started["tokenizer_identity"]
    anchor = load(repo / "configs/v14/MISTRAL_PROMPT_GATE_PLAN.json")["model"]
    names = {
        "config.json",
        "generation_config.json",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer.model",
        "tokenizer.model.v3",
        "tokenizer_config.json",
    }
    require(
        tokenizer["snapshot"] == anchor["snapshot"]
        and tokenizer["files"]
        == [r for r in anchor["snapshot_content_anchor"] if r["path"] in names]
        and {r["path"] for r in tokenizer["files"]} == names
        and sha(tokenizer["chat_template_sha256"])
        and all(
            r["chat_template"]["sha256"] == tokenizer["chat_template_sha256"]
            for r in renderings.values()
        )
        and report["tokenizer_identity_unchanged"] is True,
        "Pinned tokenizer/template identity receipt",
    )
    summary = summarize(cases, data["CHOICES.json"], data["GENERATION.json"]["rows"], plan)
    for row in data["CHOICES.json"]:
        key = tuple(row[k] for k in ("case_id", "renderer", "information"))
        require(
            row["candidate_ids"] == renderings[key]["candidate_ids"]
            and all(
                row[k] is True
                for k in (
                    "ordinary_shared_full_logits_exact",
                    "shared_historical_full_logits_exact",
                    "zero_delta_exact",
                )
            ),
            "Initial choice native parity",
        )
        require(
            type(row["top1_token_id"]) is int and row["top1_token_id"] >= 0, "Initial top1 token"
        )
        number(row["top1_probability"], "Initial top1 probability", 0, 1)
        probabilities = row["candidate_probabilities"]
        require(
            isinstance(probabilities, list) and len(probabilities) == 2,
            "Candidate probability coverage",
        )
        for probability in probabilities:
            number(probability, "Candidate full-vocabulary probability", 0, row["top1_probability"])
        require(sum(probabilities) <= 1, "Candidate probability mass")
    generated = verify_generation(
        data["GENERATION.json"],
        cases,
        renderings,
        plan,
        load(predecessor / "raw/GENERATION.json")["rows"],
    )
    require(data["GENERATION.json"]["summary"] == report["summary"] == summary, "Summary mismatch")
    require(
        report["status"] == "COMPLETED_BASE_ELICITATION_ASSAY"
        and report["optimizer_steps"] == 0
        and report["workspace_loaded"] is False
        and report["base_unchanged"] is True
        and report["source_unchanged"] is True
        and report["base_state_sha256_before"] == report["base_state_sha256_after"] == BASE_HASH,
        "Frozen base/no-update receipt",
    )
    require(
        report["unique_prefixes"] == 144
        and report["generation_sequences"] == 288
        and report["raw_replay_exact_sequences"] == 16
        and report["eos_token_ids"] == [2],
        "Report accounting",
    )
    claims = {
        "training_performed": False,
        "semantic_promotion": False,
        "non_regression": "NOT_ESTABLISHED",
        "quality_judging": "NOT_RUN",
    }
    require(
        plan["claims"] == claims and all(report[k] == v for k, v in claims.items()), "Claim ceiling"
    )
    number(report["elapsed_seconds"], "Elapsed seconds", 0)
    resources = verify_resources(data["RESOURCES.jsonl"], started, report, plan["resources"])
    return {
        "status": "VERIFIED_RECEIPTS",
        "raw_files": len(RAW_NAMES),
        "summary": summary,
        "generation_accounting": generated,
        "resources": resources,
        "native_prefix_parity_checks": 144,
        "full_logits_recomputed": False,
        "tokenizer_decode_recomputed": False,
        "chat_template_tokenization_recomputed": False,
        "native_choice_is_answer_salvage": False,
        "notes": [
            "No new model training or workspace was loaded.",
            (
                "Exact generated text, token IDs and token-level receipts are preserved; "
                "portable verification does not decode them again."
            ),
            (
                "Expression gates describe this finite correlated family panel; they are "
                "not causal fact-use, non-regression or quality evidence."
            ),
        ],
        **claims,
    }


def index_for(bundle):
    return {
        "format": "v15-base-elicitation-artifact-index-v1",
        "files": {
            name: {
                "sha256": digest(bundle / "raw" / name),
                "bytes": (bundle / "raw" / name).stat().st_size,
            }
            for name in sorted(RAW_NAMES)
        },
    }


def verify_bundle(bundle, repo=REPO, *, write_index=False):
    if write_index:
        require(not (bundle / "ARTIFACT_INDEX.json").exists(), "Artifact index collision")
        result = verify_contracts(bundle, repo)
        write_new(bundle / "ARTIFACT_INDEX.json", index_for(bundle))
    else:
        require(
            load(bundle / "ARTIFACT_INDEX.json") == index_for(bundle),
            "Artifact hash/index mismatch",
        )
        result = verify_contracts(bundle, repo)
    return result


def answer_bank(cases, rows):
    """Render every answer; fence payloads so model Markdown is never active."""
    lines = [
        "# V15 base elicitation: complete answer bank",
        "",
        "All 288 sequences are included. Initial two-choice scores do not repair these answers.",
        "",
    ]
    for case in cases:
        lines.extend(
            [
                f"## {case['case_id']}",
                "",
                f"Split: {case['split']}; view: {case['view']}; wording: {case['wording']}; "
                f"target: {'yes' if case['target_label'] else 'no'}.",
                "",
                "Context:",
                "",
            ]
        )
        lines.extend("> " + line for line in case["context"].splitlines())
        lines.extend(["", "Query:", "", "> " + case["query"], ""])
        for row in sorted(
            (r for r in rows if r["case_id"] == case["case_id"]),
            key=lambda r: (r["renderer"], r["information"], r["regime"]),
        ):
            lines.extend(
                [
                    f"### {row['renderer']} / {row['information']} / {row['regime']}",
                    "",
                    f"Termination: {row['finish_reason']}; tokens: {row['token_count']}; "
                    f"valid EOS: {row['valid_eos']}; strict correct: {row['strict_correct']}.",
                    "",
                ]
            )
            fence = "`" * max(3, 1 + max(map(len, re.findall(r"`+", row["answer"])), default=0))
            lines.extend([fence, row["answer"], fence, ""])
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle", type=Path, default=REPO / "provenance/pilots/v15_base_elicitation_20261010"
    )
    parser.add_argument("--write-index", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--answers", type=Path)
    args = parser.parse_args()
    result = verify_bundle(args.bundle.resolve(), write_index=args.write_index)
    if args.output:
        write_new(args.output, result)
    else:
        print(json.dumps(result, indent=2, allow_nan=False))
    if args.answers:
        content = answer_bank(
            load(args.bundle / "raw/CASES.json"), load(args.bundle / "raw/GENERATION.json")["rows"]
        )
        with args.answers.open("x") as target:
            target.write(content)
