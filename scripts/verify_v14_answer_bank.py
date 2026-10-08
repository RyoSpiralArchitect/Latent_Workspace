#!/usr/bin/env python3
"""Read-only reconstruction of the V14 matched answer-bank receipts.

This verifier does not call an API, generate answers, alter evidence, or infer
answer quality from token divergence. Tokenizer-free checks cannot reconstruct
tokenization, decoded text, or sampling probabilities from absent full logits.
Those limits remain explicit in the emitted summary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import subprocess
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONDITIONS = (
    "base",
    "base_inline",
    "legacy_semantic",
    "centered_semantic",
    "centered_zero",
    "centered_unrelated",
    "centered_twin",
)
REGIMES = (
    {"id": "greedy", "seed": 0, "temperature": 0.0},
    {"id": "sample211", "seed": 211, "temperature": 0.7},
    {"id": "sample212", "seed": 212, "temperature": 0.7},
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def inside(root, name):
    path = (root / name).resolve()
    require(
        not Path(name).is_absolute() and path.is_relative_to(root.resolve()),
        "Path escapes repository",
    )
    return path


def bound(root, spec):
    path = inside(root, spec["path"])
    require(
        path.is_file() and not path.is_symlink() and digest(path) == spec["sha256"],
        f"Bound file identity changed: {spec['path']}",
    )
    return json.loads(path.read_text())


def uniform(case_id, seed, step):
    payload = json.dumps(
        ["v14-answer-bank-uniform-v1", case_id, seed, step], separators=(",", ":")
    ).encode()
    sha = hashlib.sha256(payload).hexdigest()
    return {"sha256": sha, "value": (int(sha[:16], 16) >> 11) / 2**53}


def first_divergence(left, right):
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return index
    return min(len(left), len(right)) if len(left) != len(right) else None


def describe(values):
    return {
        "count": len(values),
        "mean": statistics.mean(values) if values else None,
        "median": statistics.median(values) if values else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def sharing_receipt(rows):
    counts = []
    for step in range(max(row["token_count"] for row in rows)):
        prefixes = {
            tuple(row["prompt_ids"] + row["generated_ids"][:step])
            for row in rows
            if step < row["token_count"]
        }
        counts.append(len(prefixes))
    return sum(counts), max(counts)


def verify_bank(bank, report, cases, plan, memory_receipts):
    """Validate in-memory evidence and return descriptives, never a quality claim."""
    if isinstance(cases, dict):
        cases = cases["cases"]
    require(bank["format"] == "latent-workspace-v14-answer-bank-v1", "Wrong bank format")
    require(report["format"] == "latent-workspace-v14-answer-bank-result-v1", "Wrong result format")
    require(
        report["status"] == "QUALIFIED_EXECUTION"
        and report["semantic_promotion"] is False
        and report["winner"] == "none",
        "Execution/claim ceiling changed",
    )
    require(
        plan["conditions"] == list(CONDITIONS) and plan["regimes"] == list(REGIMES),
        "Frozen answer grid changed",
    )
    require(
        len(cases) == 16 and Counter(c["lane"] for c in cases) == {"relation": 8, "general": 8},
        "Case denominator changed",
    )
    case_map = {case["id"]: case for case in cases}
    require(len(case_map) == 16, "Duplicate case ID")
    require(report["runtime"] == plan["expected_runtime"], "Runtime receipt drift")
    require(report["source_identity"] == plan["source_identity"], "Source identity receipt drift")
    require(report["claim_boundary"] == plan["claim_boundary"], "Claim boundary drift")
    require(bank["plan_sha256"] == report["plan_sha256"], "Bank/report plan disagreement")
    for key in ("base_unchanged", "bridges_unchanged", "checkpoint_bodies_unchanged"):
        require(report[key] is True, f"Missing immutability receipt: {key}")
    require(
        report["base_state_sha256_before"] == report["base_state_sha256_after"],
        "Base state hash drift",
    )
    require(
        report["bridge_state_sha256_before"] == report["bridge_state_sha256_after"],
        "Bridge state hash drift",
    )
    for sha in [
        report["base_state_sha256_before"],
        *report["bridge_state_sha256_before"].values(),
        report["chat_template_sha256"],
    ]:
        require(re.fullmatch(r"[0-9a-f]{64}", sha) is not None, "Malformed identity digest")
    rows = bank["rows"]
    expected = {
        (case_id, regime["id"], condition)
        for case_id in case_map
        for regime in REGIMES
        for condition in CONDITIONS
    }
    coordinates = [(row["case_id"], row["regime"], row["condition"]) for row in rows]
    require(
        len(rows) == 336 and len(set(coordinates)) == 336 and set(coordinates) == expected,
        "Missing/duplicate answer grid record",
    )
    indexed = dict(zip(coordinates, rows))
    require(
        set(report["ordinary_base_gates"]) == set(case_map), "Ordinary base case gates incomplete"
    )
    eos = set(report["eos_token_ids"])
    require(
        eos and all(type(value) is int and value >= 0 for value in eos), "Invalid EOS inventory"
    )
    max_tokens = plan["generation"]["max_new_tokens"]
    vocabularies = set()
    template_wrappers = set()
    for case_id, case in case_map.items():
        gates = report["ordinary_base_gates"][case_id]
        require(set(gates) == {"base", "base_inline"}, "Ordinary base prompt geometries incomplete")
        for condition, gate in gates.items():
            row = indexed[(case_id, "greedy", condition)]
            require(
                gate["full_logits_exact"] is True and gate["kv_cache_used"] is False,
                "Native ordinary-base exactness gate failed",
            )
            require(
                gate["positions"] == len(row["prompt_ids"]),
                "Native base gate prefix geometry differs",
            )
            require(
                gate["manual_logits_dtype"] == "torch.bfloat16"
                and gate["ordinary_logits_dtype"] in ("torch.bfloat16", "torch.float32"),
                "Native BF16 head receipt changed",
            )
            vocabularies.add(gate["vocabulary_size"])
    require(len(vocabularies) == 1, "Vocabulary geometry differs across base gates")
    vocabulary = next(iter(vocabularies))
    require(type(vocabulary) is int and vocabulary > max(eos), "Invalid vocabulary geometry")
    regimes = {regime["id"]: regime for regime in REGIMES}
    for row in rows:
        case, regime = case_map[row["case_id"]], regimes[row["regime"]]
        require(
            row["id"] == f"{row['case_id']}__{row['regime']}__{row['condition']}",
            "Answer artifact ID differs",
        )
        require(
            row["lane"] == case["lane"] and row["regime_parameters"] == regime,
            "Lane/regime metadata drift",
        )
        expected_text = case["user_prompt"]
        if row["condition"] == "base_inline":
            expected_text = case["memory_text"] + "\n\n" + expected_text
        require(
            row["messages"] == [{"role": "user", "content": expected_text}],
            "Reference/prompt isolation failed",
        )
        require(
            isinstance(row["rendered_prompt"], str) and expected_text in row["rendered_prompt"],
            "Rendered prompt omits declared user text",
        )
        template_wrappers.add(tuple(row["rendered_prompt"].split(expected_text, 1)))
        tokens, prompt = row["generated_ids"], row["prompt_ids"]
        require(
            isinstance(prompt, list) and 0 < len(prompt) <= plan["generation"]["max_prompt_tokens"],
            "Prompt length is invalid",
        )
        require(
            isinstance(tokens, list)
            and 0 < len(tokens) <= max_tokens
            and row["token_count"] == len(tokens),
            "Generated token denominator differs",
        )
        require(
            all(type(value) is int and 0 <= value < vocabulary for value in tokens + prompt),
            "Token outside vocabulary",
        )
        require(isinstance(row["answer"], str), "Missing decoded answer")
        require(not set(tokens[:-1]) & eos, "Generation continued after EOS")
        if row["finish_reason"] == "eos":
            require(tokens[-1] in eos, "EOS finish has no terminal EOS")
        elif row["finish_reason"] == "length":
            require(
                len(tokens) == max_tokens and tokens[-1] not in eos,
                "Length finish does not meet token budget",
            )
        else:
            raise ValueError("Unknown finish reason")
        require(len(row["token_trace"]) == len(tokens), "Token trace denominator differs")
        for step, trace in enumerate(row["token_trace"]):
            require(
                trace["step"] == step and trace["token_id"] == tokens[step],
                "Token trace coordinate differs",
            )
            require(
                trace["uniform"] == uniform(row["case_id"], regime["seed"], step),
                "Matched uniform hash/value drift",
            )
            for key in (
                "delta_l2",
                "native_applied_delta_l2",
                "native_applied_fraction",
                "native_logit_change_max_abs",
                "sampling_probability",
                "chosen_native_logit",
                "same_prefix_base_native_logit",
            ):
                require(
                    isinstance(trace[key], (int, float)) and math.isfinite(trace[key]),
                    f"Nonfinite token measurement: {key}",
                )
            require(
                0 <= trace["delta_l2"] <= plan["bridge"]["max_delta_norm"] + 1e-6,
                "Delta violates frozen norm cap",
            )
            require(
                trace["native_applied_delta_l2"] >= 0 and trace["native_logit_change_max_abs"] >= 0,
                "Negative absolute measurement",
            )
            require(
                0 <= trace["native_applied_fraction"] <= 1
                and 0 <= trace["sampling_probability"] <= 1,
                "Invalid fraction/probability",
            )
            if regime["temperature"] == 0:
                require(trace["sampling_probability"] == 1, "Greedy receipt probability differs")
            if row["condition"] in ("base", "base_inline", "centered_zero"):
                require(
                    all(
                        trace[key] == 0
                        for key in (
                            "delta_l2",
                            "native_applied_delta_l2",
                            "native_applied_fraction",
                            "native_logit_change_max_abs",
                        )
                    ),
                    "Base/zero residual measurement is nonzero",
                )
                require(
                    trace["chosen_native_logit"] == trace["same_prefix_base_native_logit"],
                    "Base/zero native logit differs",
                )
    require(len(template_wrappers) == 1, "Chat template wrapper varies across prompts")
    groups = {
        (receipt["case_id"], receipt["regime"]): receipt for receipt in report["group_receipts"]
    }
    require(len(report["group_receipts"]) == len(groups) == 48, "Group receipt denominator differs")
    for case_id in case_map:
        common = indexed[(case_id, "greedy", "base")]
        inline = indexed[(case_id, "greedy", "base_inline")]
        for regime in REGIMES:
            group = [indexed[(case_id, regime["id"], c)] for c in CONDITIONS]
            for row in group:
                expected_prompt = inline if row["condition"] == "base_inline" else common
                require(
                    row["prompt_ids"] == expected_prompt["prompt_ids"]
                    and row["rendered_prompt"] == expected_prompt["rendered_prompt"],
                    "Matched prompt geometry drift",
                )
            baseline, zero = group[0], group[4]
            require(
                baseline["generated_ids"] == zero["generated_ids"]
                and baseline["answer"] == zero["answer"]
                and baseline["finish_reason"] == zero["finish_reason"],
                "Zero/base answer mismatch",
            )
            require(
                baseline["token_trace"] == zero["token_trace"],
                "Zero/base token measurements mismatch",
            )
            receipt = groups[(case_id, regime["id"])]
            calls, concurrent = sharing_receipt(group)
            require(
                receipt["decoder_calls"] == calls
                and receipt["maximum_concurrent_prefixes"] == concurrent,
                "Prefix sharing receipt differs from answer trajectories",
            )
            require(
                receipt["zero_full_logit_exact_checks"] == zero["token_count"]
                and receipt["base_zero_token_ids_exact"] is True,
                "Zero/base execution receipt differs",
            )
            require(
                receipt["persistent_prefix_cache_entries"] == 0
                and receipt["kv_cache_used"] is False,
                "Unregistered persistent cache route",
            )
    require(set(memory_receipts) == set(case_map), "Memory case receipts incomplete")
    for case_id, memories in memory_receipts.items():
        require(
            set(memories) == {"intact", "twin", "unrelated"}, "Memory control receipts incomplete"
        )
        for name, field in (
            ("intact", "memory_text"),
            ("twin", "twin_memory_text"),
            ("unrelated", "unrelated_memory_text"),
        ):
            receipt = memories[name]
            require(
                receipt["text_sha256"]
                == hashlib.sha256(case_map[case_id][field].encode()).hexdigest(),
                "Memory text identity drift",
            )
            require(
                receipt["query_independent_encoding"] is True and receipt["boundary_layer"] == 16,
                "Memory encoding boundary drift",
            )
            require(
                0 < len(receipt["token_ids"]) <= plan["generation"]["max_memory_tokens"]
                and all(
                    type(token) is int and 0 <= token < vocabulary for token in receipt["token_ids"]
                ),
                "Memory token geometry invalid",
            )
    denominators = {
        "cases": 16,
        "regimes": 3,
        "conditions": 7,
        "answers": 336,
        "generated_tokens": sum(row["token_count"] for row in rows),
    }
    finish = dict(Counter(row["finish_reason"] for row in rows))
    finish_by_condition = {
        condition: dict(
            Counter(row["finish_reason"] for row in rows if row["condition"] == condition)
        )
        for condition in CONDITIONS
    }
    require(
        report["denominators"] == denominators
        and report["finish_counts"] == finish
        and report["finish_counts_by_condition"] == finish_by_condition,
        "Aggregate denominators/finish receipts differ",
    )
    pairs = [("base", c) for c in CONDITIONS if c != "base"] + [
        ("legacy_semantic", "centered_semantic"),
        ("centered_semantic", "centered_twin"),
        ("centered_semantic", "centered_unrelated"),
    ]
    comparisons, metrics = [], []
    for lane in ("relation", "general"):
        lane_ids = [case_id for case_id, case in case_map.items() if case["lane"] == lane]
        for regime in REGIMES:
            for left, right in pairs:
                paired = [
                    (
                        indexed[(case_id, regime["id"], left)],
                        indexed[(case_id, regime["id"], right)],
                    )
                    for case_id in lane_ids
                ]
                divergences = [
                    first_divergence(a["generated_ids"], b["generated_ids"]) for a, b in paired
                ]
                comparisons.append(
                    {
                        "lane": lane,
                        "regime": regime["id"],
                        "left": left,
                        "right": right,
                        "pairs": len(paired),
                        "token_identical": sum(d is None for d in divergences),
                        "text_identical": sum(a["answer"] == b["answer"] for a, b in paired),
                        "first_divergence_token_index": describe(
                            [d for d in divergences if d is not None]
                        ),
                        "diverged_case_ids": [
                            case_id for case_id, d in zip(lane_ids, divergences) if d is not None
                        ],
                    }
                )
            for condition in CONDITIONS:
                selected = [indexed[(case_id, regime["id"], condition)] for case_id in lane_ids]
                traces = [trace for row in selected for trace in row["token_trace"]]
                metrics.append(
                    {
                        "lane": lane,
                        "regime": regime["id"],
                        "condition": condition,
                        "answers": len(selected),
                        "tokens": sum(row["token_count"] for row in selected),
                        "token_counts": describe([row["token_count"] for row in selected]),
                        "finish_counts": dict(Counter(row["finish_reason"] for row in selected)),
                        "token_weighted_measurements": {
                            key: describe([trace[key] for trace in traces])
                            for key in (
                                "delta_l2",
                                "native_applied_delta_l2",
                                "native_applied_fraction",
                                "native_logit_change_max_abs",
                            )
                        },
                    }
                )
    return {
        "status": "PASS",
        "semantic_promotion": False,
        "winner": "none",
        "denominators": denominators,
        "finish_counts": finish,
        "finish_counts_by_condition": finish_by_condition,
        "comparisons": comparisons,
        "trajectory_measurements": metrics,
        "verification_limits": {
            "tokenizer_decoding_recomputed": False,
            "prompt_and_memory_tokenization_recomputed": False,
            "sampling_probability_recomputed_from_full_logits": False,
            "native_logit_equalities": "recorded execution gates, not GPU forward rerun",
            "quality_claim": (
                "Token divergence and residual size are descriptive, not evidence of "
                "improved intelligence or base noninferiority."
            ),
        },
    }


def verify_run(run_path, plan_path, root=REPO, verify_weights=False):
    plan = json.loads(plan_path.read_text())
    bank_path, report_path, memory_path = [
        run_path / name for name in ("bank.json", "report.json", "memory_receipts.json")
    ]
    require(not (run_path / "FAILED.json").exists(), "Run contains a failure receipt")
    bank, report, memory = [
        json.loads(path.read_text()) for path in (bank_path, report_path, memory_path)
    ]
    require(
        bank["plan_sha256"] == report["plan_sha256"] == digest(plan_path),
        "Plan file binding differs",
    )
    require(
        report["bank_sha256"] == digest(bank_path)
        and report["memory_receipts_sha256"] == digest(memory_path),
        "Evidence file digest differs",
    )
    require(
        plan["format"] == "latent-workspace-v14-answer-bank-plan-v1"
        and plan["semantic_promotion"] is False
        and plan["frozen_before_generation"] is True,
        "Plan qualification contract differs",
    )
    cases = bound(root, plan["cases"])
    require(plan["source_identity"], "No frozen source identity")
    commit = report["source_commit"]
    require(re.fullmatch(r"[0-9a-f]{40}", commit) is not None, "Malformed source commit")
    for path, expected in plan["source_identity"].items():
        require(digest(inside(root, path)) == expected, f"Current frozen source differs: {path}")
        executed = subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=root)
        require(
            hashlib.sha256(executed).hexdigest() == expected,
            f"Execution commit source differs: {path}",
        )
    relative_plan = str(plan_path.resolve().relative_to(root.resolve()))
    executed_plan = subprocess.check_output(["git", "show", f"{commit}:{relative_plan}"], cwd=root)
    require(
        hashlib.sha256(executed_plan).hexdigest() == digest(plan_path),
        "Execution commit plan differs",
    )
    for family in ("legacy", "centered"):
        previous = bound(root, plan["predecessors"][family])
        previous_plan = bound(root, plan["checkpoint_plans"][family])
        require(
            previous["status"] == "QUALIFIED_EXECUTION"
            and previous["plan_sha256"] == plan["checkpoint_plans"][family]["sha256"],
            "Predecessor checkpoint plan binding differs",
        )
        require(
            all(previous_plan[key] == plan[key] for key in ("model", "bridge", "expected_runtime")),
            "Predecessor model/bridge/runtime differs",
        )
        require(
            previous["base_state_sha256_before"] == report["base_state_sha256_before"],
            "Original base predecessor identity differs",
        )
        expected_state = previous["training"]["semantic"]["final_state_sha256"]
        require(
            report["bridge_state_sha256_before"][family] == expected_state,
            "Retained bridge predecessor state differs",
        )
        entries = [
            entry
            for entry in previous["training"]["semantic"]["checkpoints"]
            if entry["path"].endswith("/semantic_step256.pt")
        ]
        require(
            len(entries) == 1 and report["checkpoint_inventory"][family] == entries[0],
            "Retained checkpoint inventory differs",
        )
        if verify_weights:
            entry = entries[0]
            weight_path = inside(root, entry["path"])
            require(
                weight_path.stat().st_size == entry["bytes"]
                and digest(weight_path) == entry["sha256"],
                "Checkpoint file body differs",
            )
            import torch

            payload = torch.load(weight_path, map_location="cpu", weights_only=True)
            require(
                payload["step"] == 256
                and payload["cell"] == "semantic"
                and payload["plan_sha256"] == plan["checkpoint_plans"][family]["sha256"]
                and payload["base_revision"] == plan["model"]["revision"],
                "Checkpoint payload metadata differs",
            )
            state = hashlib.sha256()
            for name, value in payload["state_dict"].items():
                value = value.detach().cpu().contiguous()
                state.update(name.encode())
                state.update(str(value.dtype).encode())
                state.update(str(tuple(value.shape)).encode())
                state.update(value.view(torch.uint8).numpy().tobytes())
            require(state.hexdigest() == expected_state, "Checkpoint tensor-state hash differs")
    summary = verify_bank(bank, report, cases, plan, memory)
    summary.update(
        {
            "plan_sha256": digest(plan_path),
            "bank_sha256": digest(bank_path),
            "report_sha256": digest(report_path),
            "source_commit": commit,
            "source_identity_verified_against_execution_commit": True,
            "checkpoint_files_and_tensor_states_rechecked": verify_weights,
        }
    )
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=REPO / "configs/v14/ANSWER_BANK_PLAN.json")
    parser.add_argument("--run", type=Path)
    parser.add_argument("--verify-weights", action="store_true")
    args = parser.parse_args()
    run = args.run or REPO / json.loads(args.plan.read_text())["output"]
    print(
        json.dumps(
            verify_run(run, args.plan, verify_weights=args.verify_weights),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
