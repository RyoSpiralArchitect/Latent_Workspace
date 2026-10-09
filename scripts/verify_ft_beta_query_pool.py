#!/usr/bin/env python3
"""Portable verification of bounded query-pooling receipts, not tensor replay.

No model, checkpoint body, CUDA allocation, network call, or new evaluation is
required. Full-logit parity and gradient reconstruction remain execution
receipts; candidate arithmetic, summaries, gates, inventories and resources are
independently checked. The allocator ceiling is NOT a whole-process ceiling.
"""

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
from ft_beta_query_pool_eval import CONTROLS as CONTROLS  # noqa: E402
from ft_beta_query_pool_eval import READOUTS, summarize  # noqa: E402
from verify_ft_beta_learner_audit import verify_reader  # noqa: E402

MODES = ("final", "mean_span")
STEPS = (0, 1, 128, 256)
GROUPS = (
    "writer",
    "query_projection",
    "query_norm",
    "reader_q",
    "reader_k",
    "reader_v",
    "reader_out",
    "up",
)
WEIGHTS = {
    "paired_ce": 1.0,
    "donor_hinge": 0.25,
    "unaffected_gap_square": 0.25,
    "unrelated_gap_square": 0.25,
    "residual_norm_square": 0.001,
}
DIAGNOSTICS = ("donor_even_hinge", "donor_odd_hinge")
RAW_NAMES = (
    {"STARTED.json", "FEATURES.json", "REPORT.json", "RESOURCES.jsonl"}
    | {f"{mode}_{suffix}" for mode in MODES for suffix in ("REPORT.json", "training.jsonl")}
    | {
        f"{mode}_{step}_{kind}.json"
        for mode in MODES
        for step in STEPS
        for kind in ("evaluation", "gradients", "reader")
    }
)
PLAN_PATH = "configs/v14/FT_BETA_QUERY_POOL_PLAN.json"
SOURCE_ADDITIONS = {
    PLAN_PATH,
    "configs/v14/PRECISION_BRIDGE_PLAN.json",
    "scripts/run_ft_beta_query_pool.py",
    "scripts/ft_beta_query_pool_eval.py",
    "scripts/run_ft_beta_learner_audit.py",
    "src/latent_workspace_ft_v10/reader_query.py",
    "src/latent_workspace_ft_v10/learner_gradient_audit.py",
    "src/latent_workspace_ft_v10/bridge_reader_panel.py",
}
GIB = 1024**3
BASE_HASH = "54d161755862ebf00d8acbca083d5f290a5de44d33af82ca885f3bd8f9c94312"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_hash(value):
    return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()


def finite_tree(value):
    if isinstance(value, float):
        require(math.isfinite(value), "Nonfinite JSON value")
    elif isinstance(value, dict):
        for item in value.values():
            finite_tree(item)
    elif isinstance(value, list):
        for item in value:
            finite_tree(item)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load(path):
    require(path.is_file() and not path.is_symlink(), f"Missing or symlinked file: {path}")
    text = path.read_text()
    value = (
        [json.loads(line, object_pairs_hook=unique_object) for line in text.splitlines()]
        if path.suffix == ".jsonl"
        else json.loads(text, object_pairs_hook=unique_object)
    )
    finite_tree(value)
    return value


def sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def verify_scores(value):
    require(set(value) == set(READOUTS), "Dual readout coverage")
    for score in value.values():
        values = score["scores"]
        require(
            len(values) == 2 and all(type(v) in (int, float) and math.isfinite(v) for v in values),
            "Two finite candidate scores required",
        )
        gap = values[1] - values[0]
        require(
            score["yes_minus_no"] == gap
            and score["tie"] is (gap == 0)
            and score["greedy_choice"] == (None if gap == 0 else int(gap > 0)),
            "Candidate arithmetic",
        )


def verify_evaluation(evaluation, records, mode, step, baselines):
    finite_tree(evaluation)
    rows = evaluation["rows"]
    result = summarize(rows)  # Checks the complete 256-row grid and recomputes all summary numbers.
    require(
        evaluation["summary"] == result and evaluation["row_count"] == 256,
        "Evaluation summary mismatch",
    )
    require(
        evaluation["zero_full_logit_checks"] == 16
        and evaluation["initial_zero_checks"] == (160 if step == 0 else 0),
        "Native/initial parity denominator",
    )
    require(
        evaluation["scope"] == "two_exposed_train_worlds_no_generation"
        and evaluation["winner"] == "none"
        and evaluation["semantic_promotion"] is False
        and evaluation["non_regression"] == "NOT_ESTABLISHED",
        "Evaluation claim ceiling",
    )
    require(
        evaluation["random_matching"] == "historical_global_raw_memory_L2"
        and evaluation["different_schema_amplitude_matched"] is False,
        "Control matching claim",
    )
    index = {(r["world_index"], r["query_index"], r["side"], r["control"]): r for r in rows}
    for row in rows:
        w, q, side = row["world_index"], row["query_index"], row["side"]
        require(
            row["reader_mode"] == mode
            and row["original_label"] == records[w]["answers"][side][q]
            and row["donor_label"] == records[w]["answers"][1 - side][q],
            "Train labels or reader mode changed",
        )
        verify_scores(row["dual_readout"])
        verify_scores(row["base_dual_readout"])
        require(
            baselines.setdefault((w, q), row["base_dual_readout"]) == row["base_dual_readout"],
            "Base differs between controls, sides, modes or steps",
        )
        require(
            0 <= row["delta_l2"] <= 1.000001 and row["native_applied_delta_l2"] >= 0,
            "Residual cap/norm changed",
        )
        for key in ("native_applied_nonzero", "native_full_vocab_last_changed"):
            require(type(row[key]) is int and row[key] >= 0, "Invalid nonzero count")
        for key in (
            "native_full_vocab_last_delta_l2",
            "native_full_vocab_last_delta_max",
            "memory_l2",
        ):
            require(row[key] >= 0, "Invalid tensor norm")
        if row["control"] == "zero" or step == 0:
            require(
                row["dual_readout"] == row["base_dual_readout"]
                and all(
                    row[key] == 0
                    for key in (
                        "delta_l2",
                        "native_applied_delta_l2",
                        "native_applied_nonzero",
                        "native_full_vocab_last_changed",
                        "native_full_vocab_last_delta_l2",
                        "native_full_vocab_last_delta_max",
                    )
                ),
                "Exact zero/base parity failed",
            )
        if row["control"] == "twin":
            reverse = index[(w, q, 1 - side, "intact")]
            require(
                row["dual_readout"] == reverse["dual_readout"]
                and row["delta_l2"] == reverse["delta_l2"],
                "Twin/intact reciprocal scores differ",
            )
    gates = {
        "tiny_feasibility": all(v["tiny_feasibility"] for v in result.values()),
        "fp32_objective_attainment": all(
            v >= 0.25 for v in result[READOUTS[1]]["donor_signed_changes"]
        ),
        "separation_screen": all(v["separation_screen"] for v in result.values()),
        "written_zero_full_logit_parity": True,
        "initial_all_controls_zero": True if step == 0 else None,
    }
    require(evaluation["gates"] == gates, "Evaluation gates mismatch")
    return {"summary": result, "gates": gates}


def verify_gradients(value):
    finite_tree(value)
    require(
        value["format"] == "latent-workspace-loss-gradient-audit-v1"
        and value["optimizer_steps"] == 0,
        "Gradient audit format/steps",
    )
    require(
        all(
            value[k] is True
            for k in (
                "bridge_state_unchanged",
                "parameter_grads_unchanged",
                "module_modes_unchanged",
            )
        ),
        "Gradient mutation receipt",
    )
    require(
        value["frozen_input_names"] == ["base", "context", "head", "query"]
        and len(value["donor_margins"]) == 16,
        "Gradient frozen inputs/denominator",
    )
    reconstruction = value["reconstruction"]
    require(
        reconstruction["atol"] == 1e-6
        and reconstruction["rtol"] == 1e-5
        and reconstruction["passed"] is True
        and set(reconstruction["groups"]) == set(GROUPS)
        and all(v["passed"] is True for v in reconstruction["groups"].values()),
        "Gradient reconstruction receipt",
    )
    terms = value["terms"]
    require(set(terms) == set(WEIGHTS) | set(DIAGNOSTICS), "Gradient term set")
    for name, term in terms.items():
        expected = WEIGHTS.get(name)
        require(
            term["weight"] == expected and term["included_in_objective"] is (name in WEIGHTS),
            "Objective weighting",
        )
        require(set(term["raw"]) == set(GROUPS), "Gradient group coverage")
        require(
            term["weighted"] is None if expected is None else set(term["weighted"]) == set(GROUPS),
            "Diagnostic entered objective or missing weighted groups",
        )
        for group, raw in term["raw"].items():
            require(raw["status"] in {"missing", "zero", "nonzero"}, "Gradient status")
            if raw["status"] == "missing":
                require(
                    raw["l2"] is None and raw["present_elements"] == 0, "Missing gradient disguised"
                )
            else:
                require(
                    raw["l2"] is not None
                    and raw["l2"] >= 0
                    and raw["present_elements"] > 0
                    and (raw["status"] == "zero")
                    == (raw["l2"] == 0)
                    == (raw["nonzero_elements"] == 0),
                    "Gradient norm/status",
                )
            if expected is not None:
                actual = term["weighted"][group]["l2"]
                require(
                    actual is None
                    if raw["l2"] is None
                    else actual is not None
                    and math.isclose(actual, raw["l2"] * expected, rel_tol=1e-12, abs_tol=0),
                    "Weighted gradient norm",
                )
    pairs = value["pairwise"]
    require(
        len(pairs) == 21
        and {frozenset((p["first"], p["second"])) for p in pairs}
        == {frozenset(p) for p in itertools.combinations(terms, 2)},
        "Gradient pair grid",
    )
    pair = next(p for p in pairs if {p["first"], p["second"]} == set(DIAGNOSTICS))
    cancellation = {}
    for group in GROUPS:
        combined = terms["donor_hinge"]["raw"][group]["l2"]
        norms = [terms[name]["raw"][group]["l2"] for name in DIAGNOSTICS]
        mean = None if any(n is None for n in norms) else sum(norms) / 2
        cancellation[group] = {
            "combined_over_mean_direction_norm": combined / mean
            if combined is not None and mean
            else None,
            "even_odd_cosine": pair["raw"][group]["cosine"],
        }
    return cancellation


def verify_training(rows):
    finite_tree(rows)
    require([row["step"] for row in rows] == list(range(1, 257)), "Training sequence/denominator")
    for row in rows:
        components = row["components"]
        require(
            set(components) == set(WEIGHTS) | {"loss"}
            and len(row["donor_margins_before_update"]) == 16
            and row["preclip_gradient_l2"] >= 0,
            "Training component/gradient contract",
        )
        expected = sum(components[name] * weight for name, weight in WEIGHTS.items())
        require(
            math.isclose(components["loss"], expected, rel_tol=1e-5, abs_tol=1e-6),
            "Training objective arithmetic",
        )


def verify_resources(rows, started, report, contract):
    finite_tree(rows)
    require(
        rows
        and rows[0] == started["admission"]
        and rows[0]["phase"] == "admission"
        and rows[-1]["phase"] == "completed",
        "Resource start/end receipt",
    )
    identity = {(row["uuid"], row["own_pid"], row["total_bytes"]) for row in rows}
    require(len(identity) == 1, "Resource GPU/process identity changed")
    require(
        [r["monotonic_seconds"] for r in rows] == sorted(r["monotonic_seconds"] for r in rows),
        "Resource time order",
    )
    cap = contract["allocator_cap_gib"] * GIB
    for index, row in enumerate(rows):
        threshold = contract["admission_free_gib" if index == 0 else "abort_free_gib"] * GIB
        require(row["free_bytes"] >= threshold, "Resource free-memory threshold violated")
        require(
            row["total_bytes"] > 0
            and 0 <= row["used_bytes"] <= row["total_bytes"]
            and 0 <= row["free_bytes"] <= row["total_bytes"],
            "Invalid device memory receipt",
        )
        require(
            len({p["pid"] for p in row["processes"]}) == len(row["processes"])
            and all(p["bytes"] >= 0 for p in row["processes"]),
            "Invalid process memory receipt",
        )
        if "allocated" in row:
            require(
                0 <= row["allocated"] <= row["reserved"] <= cap
                and row["allocated"] <= row["peak_allocated"] <= row["peak_reserved"] <= cap
                and row["reserved"] <= row["peak_reserved"],
                "Allocator cap/order violated",
            )
        else:
            require(index == 0, "Missing allocator observation")
    allocated = max(r.get("peak_allocated", 0) for r in rows)
    reserved = max(r.get("peak_reserved", 0) for r in rows)
    own = max(
        (p["bytes"] for r in rows for p in r["processes"] if p["pid"] == r["own_pid"]), default=0
    )
    free = min(r["free_bytes"] for r in rows)
    require(
        allocated > 0
        and reserved > 0
        and own > 0
        and (allocated, reserved, own, free)
        == tuple(
            report[k]
            for k in (
                "peak_cuda_allocated_bytes",
                "peak_cuda_reserved_bytes",
                "sampled_own_process_peak_bytes",
                "minimum_sampled_device_free_bytes",
            )
        ),
        "Resource reported peaks differ from observations",
    )
    return {
        "peak_allocated_bytes": allocated,
        "peak_reserved_bytes": reserved,
        "sampled_process_peak_bytes": own,
        "minimum_sampled_free_bytes": free,
        "allocator_cap_bytes": cap,
        "process_memory_capped": False,
        "continuous_process_peak_measured": False,
    }


def verify_features(features, records):
    require(
        features["candidate_ids"] == [1476, 5849]
        and features["use_chat_template"] is False
        and features["cache_tensor_bytes"] > 0,
        "Feature contract",
    )
    spans, gates = features["spans"], features["native_gates"]
    require(
        len(spans) == 16
        and {(s["world"], s["query"]) for s in spans} == set(itertools.product(range(2), range(8))),
        "Span denominator/duplicates",
    )
    hashes = set()
    for row in spans:
        span, text = row["span"], row["rendered_prefix"]
        raw = records[row["world"]]["queries"][row["query"]]
        question = raw.strip()[: -len("Answer:")].strip()
        require(
            row["raw_query"] == raw
            and span["question"] == question
            and text.count(question) == 1
            and text[span["character_start"] : span["character_end"]] == question
            and span["rendered_prefix_sha256"] == hashlib.sha256(text.encode()).hexdigest(),
            "Span text binding",
        )
        ids, tokens = span["prefix_ids"], span["token_indices"]
        require(
            ids
            and tokens
            and all(type(v) is int and v >= 0 for v in ids)
            and tokens == list(range(tokens[0], tokens[-1] + 1))
            and 0 <= tokens[0] <= tokens[-1] < len(ids)
            and len(row["selected_tokens"]) == len(tokens),
            "Span token binding",
        )
        require(
            row["metadata_permutations_prefix_equal"]
            == ["answers", "side", "query_order", "metadata"],
            "Inference-only permutation receipt",
        )
        hashes.add(stable_hash(ids))
    require(
        len(hashes) == 16
        and len(gates) == 16
        and {g["prefix_sha256"] for g in gates} == hashes
        and all(g["full_logits_exact"] is True for g in gates),
        "Native parity denominator/identity",
    )
    require(
        set(features["prefix_tensor_hashes"]) == hashes
        and all(sha(v) for v in features["prefix_tensor_hashes"].values()),
        "Prefix tensor hashes",
    )
    context_keys = {
        str((w, side))
        for w in range(2)
        for side in (0, 1, "unrelated", "different_schema", "reserialized_0", "reserialized_1")
    }
    require(
        set(features["context_tensor_hashes"]) == context_keys
        and all(sha(v) for v in features["context_tensor_hashes"].values()),
        "Context tensor hashes",
    )


def verify_contracts(bundle, repo=REPO):
    raw = bundle / "raw"
    require(
        raw.is_dir() and not raw.is_symlink() and {p.name for p in raw.iterdir()} == RAW_NAMES,
        "Raw artifact inventory",
    )
    data = {name: load(raw / name) for name in RAW_NAMES}
    started, features, report = (
        data[name] for name in ("STARTED.json", "FEATURES.json", "REPORT.json")
    )
    plan = load(repo / PLAN_PATH)
    parent = load(repo / plan["parent_plan"])
    require(
        started["plan"] == plan
        and plan["modes"] == list(MODES)
        and plan["world_indices"] == [0, 1]
        and plan["query_indices"] == list(range(8))
        and plan["primary_step"] == 256
        and plan["diagnostic_steps"] == list(STEPS)
        and plan["checkpoint_steps"] == [128, 256],
        "Frozen plan contract",
    )
    require(
        plan["resources"]
        == {
            "admission_free_gib": 20,
            "allocator_cap_gib": 18,
            "abort_free_gib": 4,
            "poll_steps": 16,
            "cpu_threads": 2,
        },
        "Frozen resource contract",
    )
    require(
        re.fullmatch(r"[0-9a-f]{40}", started["source_commit"]) is not None
        and started["runtime"] == parent["expected_runtime"],
        "Source commit/runtime receipt",
    )
    hashes = started["source_hashes"]
    require(
        set(hashes) == set(parent["source_identity"]) | SOURCE_ADDITIONS, "Source coverage changed"
    )
    for name, expected in hashes.items():
        require(sha(expected) and digest(repo / name) == expected, f"Source hash mismatch: {name}")
    for name, expected in parent["source_identity"].items():
        require(hashes[name] == expected, f"Historical source identity changed: {name}")
    training = parent["training"]
    require(
        training
        == {
            "seed": 47,
            "steps": 256,
            "batch_size": 16,
            "learning_rate": 0.0001,
            "weight_decay": 0.01,
            "max_grad_norm": 1.0,
            "donor_margin": 0.25,
            "direction_weight": 0.25,
            "stability_weight": 0.25,
            "unrelated_weight": 0.25,
            "residual_penalty": 0.001,
            "save_steps": [128, 256],
        },
        "Optimizer/objective contract",
    )
    train_path = repo / parent["data"]["train"]["path"]
    require(digest(train_path) == parent["data"]["train"]["sha256"], "Training data identity")
    records = load(train_path)[:2]
    verify_features(features, records)
    require(
        report["status"] == "COMPLETED_TINY_TRAIN_ONLY"
        and report["base_unchanged"] is True
        and report["source_unchanged"] is True
        and report["base_state_sha256_before"] == report["base_state_sha256_after"] == BASE_HASH,
        "Execution/frozen base identity receipt",
    )
    require(
        report["winner"] == "none"
        and report["semantic_promotion"] is False
        and report["heldout_nonregression"] == report["free_text_generation"] == "NOT_RUN",
        "Report claim ceiling",
    )
    require(set(report["results"]) == set(MODES), "Mode coverage")
    cells, baselines, checkpoints = {}, {}, []
    for mode in MODES:
        current = report["results"][mode]
        require(
            current == data[f"{mode}_REPORT.json"]
            and current["query_mode"] == mode
            and current["steps"] == 256
            and current["parameters"] == 4200192
            and current["batch_order_sha256"]
            == stable_hash([[w, q] for w in range(2) for q in range(8)])
            and sha(current["initial_state_sha256"])
            and sha(current["final_state_sha256"]),
            "Mode/matched schedule receipt",
        )
        require(
            set(current["summaries"]) == set(current["gates"]) == {str(s) for s in STEPS},
            "Mode diagnostic step coverage",
        )
        verify_training(data[f"{mode}_training.jsonl"])
        require(len(current["checkpoints"]) == 2, "Checkpoint count")
        for step, checkpoint in zip((128, 256), current["checkpoints"], strict=True):
            require(
                checkpoint["path"] == f"{mode}_step{step}.pt"
                and checkpoint["bytes"] > 0
                and sha(checkpoint["sha256"])
                and checkpoint["roundtrip_exact"] is True,
                "Checkpoint metadata receipt",
            )
            checkpoints.append(checkpoint)
        cells[mode] = {}
        for step in STEPS:
            stem = f"{mode}_{step}"
            result = verify_evaluation(
                data[f"{stem}_evaluation.json"], records, mode, step, baselines
            )
            require(
                result["summary"] == current["summaries"][str(step)]
                and result["gates"] == current["gates"][str(step)],
                "Mode report evaluation mismatch",
            )
            reader = data[f"{stem}_reader.json"]
            require(reader["query_representation"] == mode, "Reader representation receipt")
            result["reader_summary"] = verify_reader(reader, reader["summary"])
            result["gradient_geometry"] = verify_gradients(data[f"{stem}_gradients.json"])
            cells[mode][str(step)] = result
    require(
        report["results"]["final"]["initial_state_sha256"]
        == report["results"]["mean_span"]["initial_state_sha256"],
        "Matched initialization failed",
    )
    resource = verify_resources(data["RESOURCES.jsonl"], started, report, plan["resources"])
    primary = {mode: cells[mode]["256"] for mode in MODES}
    return {
        "format": "ft-beta-query-pool-verification-v1",
        "status": "VERIFIED_RECEIPTS",
        "raw_artifacts": len(RAW_NAMES),
        "source_commit": started["source_commit"],
        "primary_step": 256,
        "denominators": {
            "worlds": 2,
            "unique_queries": 16,
            "affected_queries": 4,
            "unaffected_queries": 12,
            "evaluations": 8,
            "evaluation_rows_each": 256,
            "native_prefix_checks": 16,
            "zero_full_logit_checks": 128,
            "initial_all_control_checks": 320,
            "training_steps_each": 256,
        },
        "pooling_specific_native_tiny_benefit": primary["mean_span"]["summary"][READOUTS[0]][
            "tiny_feasibility"
        ]
        and not primary["final"]["summary"][READOUTS[0]]["tiny_feasibility"],
        "cells": cells,
        "resources": resource,
        "checkpoint_metadata": checkpoints,
        "checkpoint_bodies_verified": False,
        "full_logits_recomputed": False,
        "gradients_recomputed": False,
        "feature_tensors_recomputed": False,
        "winner": "none",
        "semantic_promotion": False,
        "heldout_nonregression": "NOT_RUN",
        "free_text_generation": "NOT_RUN",
    }


def write_new(path, value):
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(value, indent=2, allow_nan=False) + "\n")


def index_for(bundle):
    return {
        "format": "ft-beta-query-pool-artifact-index-v1",
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
        index = load(bundle / "ARTIFACT_INDEX.json")
        require(index == index_for(bundle), "Artifact hash/index mismatch")
        result = verify_contracts(bundle, repo)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle", type=Path, default=REPO / "provenance/pilots/ft_beta_query_pool_20261010"
    )
    parser.add_argument(
        "--output", type=Path, help="Exclusive-create derived summary; default prints to stdout"
    )
    parser.add_argument(
        "--write-index",
        action="store_true",
        help="Exclusive-create raw hash index after validation",
    )
    args = parser.parse_args()
    result = verify_bundle(args.bundle.resolve(), write_index=args.write_index)
    if args.output:
        write_new(args.output, result)
    else:
        print(json.dumps(result, indent=2, allow_nan=False))
