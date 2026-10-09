#!/usr/bin/env python3
"""Portable cue-panel scalar and identity checks, not model-logit replay."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts"), str(REPO / "src")]
from v15_cue_contract import (  # noqa: E402
    CUES,
    INFORMATION,
    KEYS,
    META,
    REGIME,
    RENDERERS,
    expected_grid,
    summarize,
    user_content,
)
from verify_ft_beta_query_pool import (  # noqa: E402
    BASE_HASH,
    digest,
    finite_tree,
    load,
    require,
    verify_resources,
    write_new,
)
from verify_v15_readout_transport import number  # noqa: E402

from latent_workspace_ft_v10.answer_bank_generation import matched_uniform  # noqa: E402

RAW_NAMES = {
    "STARTED.json",
    "CORPUS.json",
    "RENDERINGS.json",
    "SCORES.json",
    "GENERATION.json",
    "REPORT.json",
    "RESOURCES.jsonl",
}


def verify_renderings(rows, cases, template_hash):
    indexed, case_index = {}, {c["case_id"]: c for c in cases}
    expected = expected_grid(cases)
    require(len(rows) == 512, "Rendering denominator")
    for row in rows:
        key = tuple(row[k] for k in KEYS)
        require(key in expected and key not in indexed, "Rendering duplicate/unknown")
        indexed[key] = row
        case = case_index[row["case_id"]]
        content = user_content(case["query"], case["context"], row["cue"], row["information"])
        text, ids = row["text"], row["prompt_ids"]
        require(
            row["user_content"] == content and text.count(content) == 1, "Exact inference content"
        )
        require(
            isinstance(ids, list)
            and 1 <= len(ids) <= 512
            and all(type(t) is int and t >= 0 for t in ids),
            "Prompt IDs/bound",
        )
        applied = row["renderer"] == "native_chat"
        require((text != content) if applied else (text == content), "Envelope distinction")
        require(
            row["chat_template"]
            == {
                "sha256": template_hash,
                "applied": applied,
                "add_generation_prompt": applied,
                "messages": "single_user_no_system" if applied else None,
                "native_tokenization_exact": True if applied else None,
            },
            "Template identity receipt",
        )
        question = case["query"][:-8]
        span = row["span"]
        require(
            span["question"] == question
            and span["prefix_ids"] == ids
            and span["rendered_prefix_sha256"] == hashlib.sha256(text.encode()).hexdigest(),
            "Question prefix binding",
        )
        start, end, indices = span["character_start"], span["character_end"], span["token_indices"]
        require(
            type(start) is int
            and type(end) is int
            and 0 <= start < end <= len(text)
            and text[start:end] == question,
            "Question text binding",
        )
        require(
            isinstance(indices, list)
            and indices
            and all(type(t) is int and 0 <= t < len(ids) for t in indices)
            and indices == list(range(indices[0], indices[-1] + 1)),
            "Question token span",
        )
        require(
            row["candidate_suffixes"] == [" no", " yes"]
            and len(row["candidate_ids"]) == len(set(row["candidate_ids"])) == 2,
            "Lowercase binding",
        )
    require(set(indexed) == expected, "Complete rendering grid")
    return indexed


def verify_scores(rows, renderings, numerics):
    alias_count = 0
    for row in rows:
        rendered = renderings[tuple(row[k] for k in KEYS)]
        ids = row["prefix_ids"]
        require(
            ids == rendered["prompt_ids"]
            and row["prefix_sha256"]
            == hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest(),
            "Score prefix identity",
        )
        require(
            row["candidate_ids"] == rendered["candidate_ids"]
            and row["ordinary_shared_full_logits_exact"] is True,
            "Native parity receipt",
        )
        require(
            [{k: a[k] for k in ("target_label", "token_id", "suffixes")} for a in row["aliases"]]
            == rendered["aliases"],
            "Alias binding identity",
        )
        require(type(row["top1_token_id"]) is int and row["top1_token_id"] >= 0, "Top1 identity")
        number(row["top1_probability"], "Top1 probability", 0, 1)
        require(len(row["candidate_probabilities"]) == 2, "Candidate probability denominator")
        lower = []
        for label, suffix in ((0, " no"), (1, " yes")):
            a = next(a for a in row["aliases"] if suffix in a["suffixes"])
            require(a["token_id"] == row["candidate_ids"][label], "Lowercase token identity")
            number(
                row["candidate_probabilities"][label],
                "Candidate probability",
                0,
                row["top1_probability"],
            )
            require(
                math.isclose(
                    a["first_probability"],
                    row["candidate_probabilities"][label],
                    rel_tol=numerics["scalar_relative_tolerance"],
                    abs_tol=numerics["scalar_absolute_tolerance"],
                ),
                "Lowercase probability identity",
            )
            lower.append(a)
        require(
            math.isclose(
                lower[1]["first_log_probability"] - lower[0]["first_log_probability"],
                row["old_lowercase_native"]["gap"],
                rel_tol=numerics["scalar_relative_tolerance"],
                abs_tol=numerics["log_gap_absolute_tolerance"],
            ),
            "Logit/log-prob gap identity",
        )
        alias_count += len(row["aliases"])
    return {
        "initial_native_parity_checks": len(rows),
        "scoring_readout_parity_checks": len(rows) + alias_count,
        "alias_forwards": alias_count,
    }


def verify_generation(value, cases, renderings):
    require(value["eos_token_ids"] == [2], "EOS policy")
    indexed, case_index = {}, {c["case_id"]: c for c in cases}
    require(len(value["rows"]) == 512, "Generation denominator")
    for row in value["rows"]:
        key = tuple(row[k] for k in KEYS)
        require(key in renderings and key not in indexed, "Generation duplicate/unknown")
        indexed[key] = row
        condition = "base_inline" if row["information"] == "inline" else "base"
        require(
            row["condition"] == condition
            and row["regime"] == "greedy"
            and row["regime_parameters"] == REGIME
            and row["id"]
            == f"{row['case_id']}__greedy__{condition}__{row['renderer']}__{row['cue']}",
            "Generation identity",
        )
        require(
            all(row[k] == case_index[row["case_id"]][k] for k in META)
            and row["prompt_ids"] == renderings[key]["prompt_ids"],
            "Generation prefix/metadata",
        )
        ids, trace = row["generated_ids"], row["token_trace"]
        require(
            isinstance(ids, list)
            and 1 <= len(ids) <= 64
            and all(type(t) is int and t >= 0 for t in ids)
            and len(ids) == row["token_count"] == len(trace),
            "Token denominator",
        )
        require(
            2 not in ids[:-1]
            and (
                (ids[-1] == 2 and row["finish_reason"] == "eos")
                or (ids[-1] != 2 and len(ids) == 64 and row["finish_reason"] == "length")
            ),
            "EOS termination",
        )
        for step, token in enumerate(trace):
            require(
                token["step"] == step
                and token["token_id"] == ids[step]
                and token["uniform"] == matched_uniform(row["case_id"], 0, step),
                "Token/uniform trace",
            )
            require(
                token["sampling_probability"] == 1
                and token["token_id"]
                == token["native_top1_token_id"]
                == token["same_prefix_base_native_top1_token_id"],
                "Greedy native top1",
            )
            number(token["chosen_token_native_probability"], "Native probability", 0, 1)
            number(token["chosen_native_logit"], "Native logit")
            require(
                token["chosen_token_native_probability"]
                == token["same_prefix_base_chosen_token_native_probability"]
                and token["chosen_native_logit"] == token["same_prefix_base_native_logit"]
                and token["native_top1_changed"] is False
                and all(
                    token[k] == 0
                    for k in (
                        "delta_l2",
                        "native_applied_delta_l2",
                        "native_applied_fraction",
                        "native_logit_change_max_abs",
                        "native_logit_change_l2",
                    )
                ),
                "Base-only native trace",
            )
    expected = set(itertools.product(case_index, RENDERERS, CUES))
    require(len(value["receipts"]) == len(expected) == 256, "Receipt denominator")
    seen, total = set(), 0
    for receipt in value["receipts"]:
        group = tuple(receipt[k] for k in ("case_id", "renderer", "cue"))
        require(group in expected and group not in seen, "Receipt duplicate/unknown")
        seen.add(group)
        current = [indexed[*group, info] for info in INFORMATION]
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
        require(
            receipt["decoder_calls"] == receipt["shared_historical_native_checks"] == sum(counts)
            and receipt["maximum_concurrent_prefixes"] == max(counts),
            "Decoder accounting",
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
            "No workspace/cache contract",
        )
        total += sum(counts)
    return total


def index_for(bundle):
    return {
        "format": "v15-cue-confirmation-index-v1",
        "files": {
            name: {
                "bytes": (bundle / "raw" / name).stat().st_size,
                "sha256": digest(bundle / "raw" / name),
            }
            for name in sorted(RAW_NAMES)
        },
    }


def verify_bundle(bundle, check_index=True):
    import run_v15_cue_confirmation as runner

    bundle = Path(bundle)
    require({p.name for p in (bundle / "raw").iterdir()} == RAW_NAMES, "Raw inventory")
    if check_index:
        require(load(bundle / "ARTIFACT_INDEX.json") == index_for(bundle), "Raw index identity")
    values = {name: load(bundle / "raw" / name) for name in RAW_NAMES}
    finite_tree(values)
    plan, parent, corpus = runner.validate()
    started, report = values["STARTED.json"], values["REPORT.json"]
    require(
        started["plan"] == plan and started["plan_sha256"] == digest(runner.PLAN), "Frozen plan"
    )
    require(
        started["runtime"] == parent["expected_runtime"]
        and re.fullmatch(r"[0-9a-f]{40}", started["source_commit"]) is not None,
        "Runtime/source identity",
    )
    require(started["source_hashes"] == runner.sources(parent), "Source manifest mismatch")
    require(values["CORPUS.json"] == corpus, "Frozen corpus")
    identity = started["tokenizer_identity"]
    old = load(REPO / plan["predecessor_bundle"] / "raw/STARTED.json")
    require(identity == old["tokenizer_identity"], "Pinned tokenizer identity")
    rendered = verify_renderings(
        values["RENDERINGS.json"], corpus["cases"], identity["chat_template_sha256"]
    )
    summary = summarize(
        corpus["cases"], values["SCORES.json"], values["GENERATION.json"]["rows"], plan
    )
    require(report["summary"] == summary, "Exact categorical summary mismatch")
    accounting = verify_scores(values["SCORES.json"], rendered, plan["numerics"])
    generated_calls = verify_generation(values["GENERATION.json"], corpus["cases"], rendered)
    require(
        report["status"] == "COMPLETED_CUE_CONFIRMATION"
        and report["optimizer_steps"] == 0
        and report["workspace_loaded"] is False
        and report["base_sha256_before"] == report["base_sha256_after"] == BASE_HASH
        and report["source_unchanged"] is True
        and report["tokenizer_identity_unchanged"] is True,
        "No-update scope/identity",
    )
    require(
        report["prefixes"] == report["generation_sequences"] == 512
        and report["initial_native_parity_checks"] == accounting["initial_native_parity_checks"]
        and report["scoring_readout_parity_checks"] == accounting["scoring_readout_parity_checks"]
        and report["generation_readout_parity_checks"] == generated_calls,
        "Report forward accounting",
    )
    require(all(report[k] == v for k, v in plan["claims"].items()), "Claim ceiling")
    number(report["elapsed_seconds"], "Elapsed seconds", 0)
    resources = verify_resources(values["RESOURCES.jsonl"], started, report, plan["resources"])
    return {
        "status": "VERIFIED_RECEIPTS",
        "summary": summary,
        "accounting": {**accounting, "generation_readout_parity_checks": generated_calls},
        "source_files_verified": len(started["source_hashes"]),
        "resources": resources,
        "full_logits_recomputed": False,
        "tokenizer_binding_recomputed": False,
        "model_state_recomputed": False,
        "new_scalar_tolerances_predeclared": plan["numerics"],
        "historical_exact_replay_failure_waived": False,
        **plan["claims"],
    }


def answer_bank(corpus, rows, summary):
    def fence(text):
        ticks = "`" * max(3, 1 + max((len(s) for s in re.findall(r"`+", text)), default=0))
        return f"{ticks}text\n{text}\n{ticks}"

    lines = [
        "# Fresh cue-by-envelope answer bank",
        "",
        f"All {len(rows)} greedy outputs; primary gate: **{summary['primary_expression_gate']}**.",
        "",
        "No first-word salvage or post-result method selection. Scores below are "
        "whole-answer plus EOS. Forced-path diagnostics are separate.",
        "",
    ]
    for case in corpus["cases"]:
        lines.extend(
            [
                f"## {case['case_id']}",
                "",
                f"View: {case['view']}; correct answer: {('no', 'yes')[case['target_label']]}",
                "",
                fence(case["context"] + "\n\n" + case["query"]),
                "",
            ]
        )
        for row in (r for r in rows if r["case_id"] == case["case_id"]):
            lines.extend(
                [
                    f"### {row['renderer']} / cue {row['cue']} / {row['information']}",
                    "",
                    f"Finish: {row['finish_reason']}; valid: {row['valid_eos']}; "
                    f"correct: {row['strict_correct']}; tokens: {row['token_count']}.",
                    "",
                    fence(row["answer"]),
                    "",
                ]
            )
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--write-index", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--answers", type=Path)
    args = parser.parse_args()
    if args.write_index:
        require(not (args.bundle / "ARTIFACT_INDEX.json").exists(), "Index collision")
    result = verify_bundle(args.bundle, check_index=not args.write_index)
    if args.write_index:
        write_new(args.bundle / "ARTIFACT_INDEX.json", index_for(args.bundle))
    if args.output:
        write_new(args.output, result)
    else:
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "primary_expression_gate": result["summary"]["primary_expression_gate"],
                    "accounting": result["accounting"],
                }
            )
        )
    if args.answers:
        text = answer_bank(
            load(args.bundle / "raw/CORPUS.json"),
            load(args.bundle / "raw/GENERATION.json")["rows"],
            result["summary"],
        )
        with args.answers.open("x") as handle:
            handle.write(text)
