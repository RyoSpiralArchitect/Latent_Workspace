#!/usr/bin/env python3
"""Verify V15 scalar artifacts and execution receipts, not model/checkpoint replay.

The verifier recomputes summaries, grid/counter contracts, recorded token
divergence and common random numbers. It cannot reconstruct omitted full logits,
gradient tensors, tokenizer decoding, checkpoint bodies or continuous VRAM peaks.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts"), str(REPO / "src")]
from v15_assay_summary import (  # noqa: E402
    canonical_facts,
    parse_functional_answer,
    summarize_crossover,
)
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
from verify_ft_beta_query_pool import (  # noqa: E402
    verify_bundle as verify_predecessor,
)

from latent_workspace_ft_v10.answer_bank_generation import matched_uniform  # noqa: E402

PLAN_PATH = "configs/v15/READOUT_TRANSPORT_PLAN.json"
RAW_NAMES = {
    "STARTED.json",
    "FEATURES.json",
    "GRADIENTS.json",
    "CROSSOVER.json",
    "GENERATION.json",
    "REPORT.json",
    "RESOURCES.jsonl",
}
SOURCE_ADDITIONS = {
    PLAN_PATH,
    "scripts/run_v15_readout_transport.py",
    "scripts/v15_assay_summary.py",
    "scripts/verify_ft_beta_query_pool.py",
    "scripts/verify_ft_beta_learner_audit.py",
    "docs/v15/PLAN.md",
    *{
        f"src/latent_workspace_ft_v10/{name}.py"
        for name in ("v15_readout", "v15_pipeline", "v15_generation", "answer_bank_generation")
    },
}
MODES = ("final", "mean_span")
GRADIENT_PARAMETERS = {
    "writer.slot_seed",
    "writer.context_projection.weight",
    *{
        f"writer.{name}.{part}"
        for name in ("slot_norm", "context_norm", "ff_norm")
        for part in ("weight", "bias")
    },
    *{
        f"writer.{name}.{part}"
        for name in ("cross_attention", "self_attention")
        for part in ("in_proj_weight", "in_proj_bias", "out_proj.weight", "out_proj.bias")
    },
    *{f"writer.ff.{layer}.{part}" for layer in (0, 3) for part in ("weight", "bias")},
    "query_projection.weight",
    "query_norm.weight",
    "query_norm.bias",
    "attention.in_proj_weight",
    "attention.out_proj.weight",
    "up.weight",
}
CONDITIONS = (
    "base",
    "base_inline",
    "final_intact",
    "final_twin",
    "final_zero",
    "mean_intact",
    "mean_twin",
    "mean_zero",
)
REGIMES = [
    {"id": "greedy", "seed": 0, "temperature": 0.0},
    {"id": "sample211", "seed": 211, "temperature": 0.7},
]


def number(value, name, minimum=None, maximum=None):
    require(type(value) in (int, float) and math.isfinite(value), f"Nonfinite number: {name}")
    require(minimum is None or value >= minimum, f"Below range: {name}")
    require(maximum is None or value <= maximum, f"Above range: {name}")


def first_divergence(left, right):
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return index
    return min(len(left), len(right)) if len(left) != len(right) else None


def verify_gradients(value):
    finite_tree(value)
    require(set(value) == set(MODES), "Gradient modes")
    for mode in MODES:
        cell = value[mode]
        require(cell["unchanged"] is True and cell["optimizer_steps"] == 0, "Gradient mutation")
        require(
            cell["scope"]
            == ("PyTorch BF16 cast surrogate-gradient connectivity; not finite-step learning"),
            "Gradient scope",
        )
        require(
            len(cell["rows"]) == 2
            and {(r["world"], r["query"]) for r in cell["rows"]} == {(0, 0), (0, 1)},
            "Gradient query grid",
        )
        for row in cell["rows"]:
            require(row["native_train_eval_logits_exact"] is True, "Train/eval parity receipt")
            require(
                set(row["losses"]) == {"native_two_choice_ce", "native_full_vocab_ce"},
                "Native loss coverage",
            )
            for loss in row["losses"].values():
                number(loss["loss"], "native loss", minimum=0)
                norms = loss["parameter_gradient_l2"]
                require(set(norms) == GRADIENT_PARAMETERS, "Gradient parameter coverage")
                for norm in norms.values():
                    number(norm, "gradient norm", minimum=0)
                require(any(v > 0 for v in norms.values()), "Native gradient path disconnected")
    return {"query_receipts": 4, "loss_receipts": 8, "optimizer_steps": 0}


def generation_summary(rows):
    return {
        c: {
            "sequences": len(selected := [r for r in rows if r["condition"] == c]),
            "strict_correct": sum(r["strict_correct"] for r in selected),
            "unparseable": sum(r["parsed_answer"] is None for r in selected),
            "length_truncated": sum(r["finish_reason"] == "length" for r in selected),
            "lowercase_compliant": sum(r["lowercase_compliant"] for r in selected),
        }
        for c in CONDITIONS
    }


def verify_generation(value, records, features, spec):
    finite_tree(value)
    rows = value["rows"]
    require(
        len(rows) == 64
        and value["quality_claim"] is False
        and value["kv_cache_used"] is False
        and value["scope"] == "exposed functional transport probe",
        "Generation scope/grid",
    )
    expected = set(itertools.product(range(2), range(2), (r["id"] for r in REGIMES), CONDITIONS))
    indexed, prefixes = {}, {}
    spans = {(s["world"], s["query"]): s["span"]["prefix_ids"] for s in features["spans"]}
    for row in rows:
        w, q, regime_id, condition = (row[k] for k in ("world", "query", "regime", "condition"))
        key = w, q, regime_id, condition
        require(key in expected and key not in indexed, "Duplicate/unknown generation cell")
        indexed[key] = row
        regime = next(r for r in REGIMES if r["id"] == regime_id)
        case_id = f"w{w}_q{q}"
        require(
            row["case_id"] == case_id
            and row["id"] == f"{case_id}__{regime_id}__{condition}"
            and row["regime_parameters"] == regime,
            "Generation identity/regime",
        )
        ids, prompt = row["generated_ids"], row["prompt_ids"]
        require(
            isinstance(ids, list)
            and isinstance(prompt, list)
            and prompt
            and all(type(t) is int and t >= 0 for t in ids + prompt),
            "Token IDs",
        )
        require(
            1 <= len(ids) <= spec["max_new_tokens"]
            and row["token_count"] == len(ids)
            and len(row["token_trace"]) == len(ids),
            "Generation token denominator",
        )
        require(prefixes.setdefault((w, q, condition), prompt) == prompt, "Regime prompt drift")
        if condition != "base_inline":
            require(prompt == spans[w, q], "Generation prompt/span mismatch")
        else:
            require(prompt != spans[w, q], "Inline control must have distinct input facts")
        require(row["finish_reason"] in {"eos", "length"}, "Generation termination")
        if row["finish_reason"] == "length":
            require(len(ids) == spec["max_new_tokens"], "Length receipt before token cap")
        parsed = parse_functional_answer(row["answer"])
        target = records[w]["answers"][int(condition.endswith("_twin"))][q]
        require(
            row["target_label"] == target
            and row["parsed_answer"] == parsed
            and row["lowercase_compliant"] is (row["answer"].strip() in ("yes", "no"))
            and row["strict_correct"] is (parsed == target and row["finish_reason"] == "eos"),
            "Functional answer parsing/strict correctness",
        )
        for step, trace in enumerate(row["token_trace"]):
            require(
                trace["step"] == step
                and trace["token_id"] == ids[step]
                and trace["uniform"] == matched_uniform(case_id, regime["seed"], step),
                "Token trace/common random number",
            )
            for name in (
                "sampling_probability",
                "chosen_token_native_probability",
                "same_prefix_base_chosen_token_native_probability",
                "native_applied_fraction",
            ):
                number(trace[name], name, 0, 1)
            for name in ("chosen_native_logit", "same_prefix_base_native_logit"):
                number(trace[name], name)
            for name in (
                "native_logit_change_max_abs",
                "native_logit_change_l2",
                "delta_l2",
                "native_applied_delta_l2",
            ):
                number(trace[name], name, 0)
            require(trace["delta_l2"] <= 1.000001, "Generation residual cap")
            for name in ("native_top1_token_id", "same_prefix_base_native_top1_token_id"):
                require(type(trace[name]) is int and trace[name] >= 0, "Top1 token ID")
            require(
                trace["native_top1_changed"]
                is (
                    trace["native_top1_token_id"] != trace["same_prefix_base_native_top1_token_id"]
                ),
                "Native top1 flag",
            )
            require(
                trace["native_logit_change_l2"] + 1e-12
                >= trace["native_logit_change_max_abs"]
                >= abs(trace["chosen_native_logit"] - trace["same_prefix_base_native_logit"])
                - 1e-12,
                "Recorded logit norm bounds",
            )
            if regime["temperature"] == 0:
                require(
                    trace["sampling_probability"] == 1
                    and trace["token_id"] == trace["native_top1_token_id"],
                    "Greedy policy",
                )
            if condition in ("base", "base_inline", "final_zero", "mean_zero"):
                require(
                    all(
                        trace[name] == 0
                        for name in (
                            "delta_l2",
                            "native_applied_delta_l2",
                            "native_applied_fraction",
                            "native_logit_change_max_abs",
                            "native_logit_change_l2",
                        )
                    )
                    and trace["native_top1_changed"] is False
                    and trace["chosen_native_logit"] == trace["same_prefix_base_native_logit"]
                    and trace["chosen_token_native_probability"]
                    == trace["same_prefix_base_chosen_token_native_probability"],
                    "Generation zero trace",
                )
    require(set(indexed) == expected, "Missing generation cells")
    receipts = value["receipts"]
    require(
        len(receipts) == 8 and len({(r["world"], r["query"], r["regime"]) for r in receipts}) == 8,
        "Generation receipt grid",
    )
    divergences = []
    total_checks = total_decoder = 0
    for receipt in receipts:
        group = receipt["world"], receipt["query"], receipt["regime"]
        require((*group, "base") in indexed, "Unknown generation receipt")
        current = {c: indexed[*group, c] for c in CONDITIONS}
        base = current["base"]
        for zero in ("final_zero", "mean_zero"):
            require(
                current[zero]["generated_ids"] == base["generated_ids"]
                and current[zero]["finish_reason"] == base["finish_reason"]
                and current[zero]["token_trace"] == base["token_trace"],
                "Zero/base token parity",
            )
        counts = []
        for step in range(max(r["token_count"] for r in current.values())):
            active = [r for r in current.values() if r["token_count"] > step]
            counts.append(len({tuple(r["prompt_ids"] + r["generated_ids"][:step]) for r in active}))
        decoder = sum(counts)
        zero_counts = {c: current[c]["token_count"] for c in ("final_zero", "mean_zero")}
        native_checks = decoder + sum(
            r["token_count"] for c, r in current.items() if c not in ("base", "base_inline")
        )
        require(
            receipt["decoder_calls"] == decoder
            and receipt["maximum_concurrent_prefixes"] == max(counts)
            and receipt["shared_historical_native_checks"] == native_checks
            and receipt["zero_full_logit_exact_checks_by_condition"] == zero_counts
            and receipt["zero_full_logit_exact_checks"] == sum(zero_counts.values()),
            "Generation execution counter mismatch",
        )
        require(
            receipt["base_zero_token_ids_exact"] is True
            and receipt["zero_pairs"] == [["base", "final_zero"], ["base", "mean_zero"]]
            and receipt["persistent_prefix_cache_entries"] == 0
            and receipt["kv_cache_used"] is False
            and receipt["readout_contract"] == "shared_native_full_sequence_full_vocabulary"
            and receipt["logit_reference"] == "base_at_same_current_prefix"
            and receipt["reader_span_owner"] == "backend_bound_original_prompt",
            "Generation contract",
        )
        total_checks += native_checks
        total_decoder += decoder
        for condition, row in current.items():
            if condition != "base":
                divergences.append(
                    {
                        "world": group[0],
                        "query": group[1],
                        "regime": group[2],
                        "condition": condition,
                        "first_divergence_step": first_divergence(
                            base["generated_ids"], row["generated_ids"]
                        ),
                        "comparison": "different_prompt_inline_control"
                        if condition == "base_inline"
                        else "matched_initial_prefix_not_semantic_causality",
                    }
                )
    summary = generation_summary(rows)
    require(value["summary"] == summary, "Generation summary mismatch")
    return {
        "summary": summary,
        "first_divergences": divergences,
        "decoder_calls": total_decoder,
        "shared_historical_native_checks": total_checks,
    }


def verify_features(value, old, records, plan):
    require(
        value["candidate_ids"] == old["candidate_ids"] == [1476, 5849]
        and value["spans"] == old["spans"]
        and value["native_gates"] == old["native_gates"]
        and len(value["native_gates"]) == 16
        and all(g["full_logits_exact"] is True for g in value["native_gates"])
        and value["mean_reduction"] == plan["mean_reduction"],
        "Feature/prefix native gates",
    )
    facts = value["facts"]
    expected = set(itertools.product(range(2), (0, 1), plan["orders"]))
    require(
        len(facts) == 12 and {(r["world"], r["side"], r["order"]) for r in facts} == expected,
        "Fact serialization grid",
    )
    for row in facts:
        original = records[row["world"]]["contexts"][row["side"]]
        text = (
            original
            if row["order"] == "original"
            else canonical_facts(original, reverse=row["order"] == "canonical_reverse")
        )
        require(
            row["text"] == text
            and row["token_ids"]
            and all(type(t) is int and t >= 0 for t in row["token_ids"]),
            "Fact preservation",
        )


def verify_contracts(bundle, repo=REPO):
    raw = bundle / "raw"
    require(
        raw.is_dir() and not raw.is_symlink() and {p.name for p in raw.iterdir()} == RAW_NAMES,
        "Raw artifact inventory",
    )
    data = {name: load(raw / name) for name in RAW_NAMES}
    started, report = data["STARTED.json"], data["REPORT.json"]
    plan = load(repo / PLAN_PATH)
    require(
        started["plan"] == plan
        and plan["format"] == "v15-native-readout-transport-v1"
        and plan["worlds"] == [0, 1]
        and plan["queries"] == list(range(8))
        and plan["modes"] == list(MODES)
        and plan["optimizer_steps"] == 0
        and plan["checkpoint_step"] == 256
        and plan["max_delta_norm"] == 1.0
        and plan["orders"] == ["original", "canonical", "canonical_reverse"]
        and plan["mean_reduction"] == "CPU FP32, matching retained checkpoint training"
        and plan["predecessor_bundle"] == "provenance/pilots/ft_beta_query_pool_20261010"
        and plan["model_parent"] == "configs/v14/PRECISION_BRIDGE_PLAN.json",
        "Frozen V15 contract",
    )
    spec = plan["generation"]
    require(
        spec["worlds"] == [0, 1]
        and spec["queries"] == [0, 1]
        and spec["side"] == 0
        and spec["regimes"] == REGIMES
        and spec["conditions"] == list(CONDITIONS)
        and spec["max_new_tokens"] == 64
        and spec["expected_sequences"] == 64
        and spec["parser"]
        == (
            "whole stripped answer yes/no, casefolded; lowercase compliance separate; "
            "length-truncated is incorrect"
        )
        and spec["history"] == ("full-prefix recomputation; no KV cache or continuous state carry"),
        "Frozen generation contract",
    )
    predecessor = repo / plan["predecessor_bundle"]
    require(
        verify_predecessor(predecessor, repo)["status"] == "VERIFIED_RECEIPTS",
        "Predecessor verification",
    )
    old_started = load(predecessor / "raw/STARTED.json")
    old_report = load(predecessor / "raw/REPORT.json")
    parent = load(repo / plan["model_parent"])
    require(plan["resources"] == old_started["plan"]["resources"], "Resource contract")
    require(
        started["runtime"] == parent["expected_runtime"]
        and re.fullmatch(r"[0-9a-f]{40}", started["source_commit"]) is not None
        and started["split"] == old_started["split_audit"],
        "Runtime/source/split identity",
    )
    hashes = started["source_hashes"]
    require(set(hashes) == set(old_started["source_hashes"]) | SOURCE_ADDITIONS, "Source coverage")
    for name, expected in hashes.items():
        require(sha(expected) and digest(repo / name) == expected, f"Source hash mismatch: {name}")
    for name, expected in old_started["source_hashes"].items():
        require(hashes[name] == expected, f"Historical source changed: {name}")
    records = load(repo / parent["data"]["train"]["path"])[:2]
    verify_features(data["FEATURES.json"], load(predecessor / "raw/FEATURES.json"), records, plan)
    gradient_summary = verify_gradients(data["GRADIENTS.json"])
    cross = data["CROSSOVER.json"]
    crossover = summarize_crossover(cross["rows"])
    require(
        cross["summary"] == crossover
        and cross["shared_historical_native_full_logit_exact_checks"] == 384
        and cross["zero_checks"] == 32,
        "Crossover summary/parity counters",
    )
    for row in cross["rows"]:
        w, q = row["world"], row["query"]
        require(
            row["labels"] == [records[w]["answers"][s][q] for s in (0, 1)]
            and row["affected"] is records[w]["affected"][q]
            and row["delta_l2"] <= 1.000001,
            "Crossover labels/cap",
        )
        transport = row["transport"]
        number(transport["logit_change_l2"], "logit L2", 0)
        number(
            transport["base_top1_candidate_probability"], "base top1 candidate probability", 0, 1
        )
        require(
            transport["logit_change_l2"] >= transport["max_abs_logit_change"] - 1e-12,
            "Crossover logit norm bound",
        )
        if row["memory_key"] == "zero":
            require(
                transport["logit_change_l2"] == 0
                and transport["base_top1_candidate_probability"]
                == transport["base_top1_probability"],
                "Zero full-vocab transport",
            )
    generated = verify_generation(data["GENERATION.json"], records, data["FEATURES.json"], spec)
    require(
        report["status"] == "COMPLETED_V15_ENGINEERING_ASSAY"
        and report["optimizer_steps"] == 0
        and report["base_unchanged"] is True
        and report["bridges_unchanged"] is True
        and report["source_unchanged"] is True
        and report["base_state_sha256_before"]
        == report["base_state_sha256_after"]
        == BASE_HASH
        == old_report["base_state_sha256_after"],
        "No-update/frozen base receipt",
    )
    require(set(report["checkpoints"]) == set(MODES), "Checkpoint modes")
    for mode in MODES:
        expected = next(
            c
            for c in old_report["results"][mode]["checkpoints"]
            if c["path"] == f"{mode}_step256.pt"
        )
        require(report["checkpoints"][mode] == expected, "Retained checkpoint identity")
    claims = {
        "winner": "none",
        "semantic_promotion": False,
        "non_regression": "NOT_ESTABLISHED",
        "quality_judging": "NOT_RUN",
    }
    require(
        plan["claims"] == claims and all(report[k] == v for k, v in claims.items()), "Claim ceiling"
    )
    require(
        report["crossover_rows"] == 384
        and report["generation_sequences"] == 64
        and report["generation_summary"] == generated["summary"],
        "Report denominators",
    )
    number(report["elapsed_seconds"], "elapsed seconds", 0)
    resources = verify_resources(data["RESOURCES.jsonl"], started, report, plan["resources"])
    return {
        "status": "VERIFIED_RECEIPTS",
        "raw_files": len(RAW_NAMES),
        "crossover": crossover,
        "generation": generated,
        "gradients": gradient_summary,
        "resources": resources,
        "native_prefix_parity_checks": 16,
        "crossover_native_parity_checks": 384,
        "written_zero_checks": 32,
        "checkpoint_bodies_verified": False,
        "full_logits_recomputed": False,
        "gradients_recomputed": False,
        "tokenizer_decode_recomputed": False,
        "interpretation": {
            "original_order_contrast": (
                "Historical twin/intact fact orders were independently permuted; "
                "original-order contrasts confound content with serialization. "
                "The raw affected_content field does not establish isolated semantic causality."
            ),
            "canonical_order_contrast": (
                "Canonical/canonical_reverse are deterministic literal fact order controls "
                "for these two exposed worlds, not evidence of general serialization invariance."
            ),
            "generation": (
                "Token divergence is a native transport observation, not a quality gain or "
                "KV-mediated continuous-state recurrence; inline uses a different prompt."
            ),
        },
        **claims,
    }


def index_for(bundle):
    return {
        "format": "v15-readout-transport-artifact-index-v1",
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle", type=Path, default=REPO / "provenance/pilots/v15_readout_transport_20261010"
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--write-index", action="store_true")
    args = parser.parse_args()
    result = verify_bundle(args.bundle.resolve(), write_index=args.write_index)
    if args.output:
        write_new(args.output, result)
    else:
        print(json.dumps(result, indent=2, allow_nan=False))
