from __future__ import annotations

import copy
import hashlib
import importlib.util
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "verify_v14_answer_bank_test", REPO / "scripts/verify_v14_answer_bank.py"
)
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


def fixture():
    cases = [
        {
            "id": f"case{index}",
            "lane": "relation" if index < 8 else "general",
            "user_prompt": f"Question{index}",
            "memory_text": f"Memory{index}",
            "twin_memory_text": f"Twin{index}",
            "unrelated_memory_text": f"Unrelated{index}",
            "reference": {"original": "PRIVATE"},
            "rubric": ["not a prompt"],
        }
        for index in range(16)
    ]
    plan = {
        "conditions": list(verifier.CONDITIONS),
        "regimes": list(verifier.REGIMES),
        "expected_runtime": {"test": True},
        "source_identity": {"test.py": "a" * 64},
        "claim_boundary": ["descriptive, not semantic"],
        "bridge": {"max_delta_norm": 1.0},
        "generation": {"max_new_tokens": 128, "max_prompt_tokens": 1024, "max_memory_tokens": 1024},
    }
    rows, groups, gates, memories = [], [], {}, {}
    for case in cases:
        memories[case["id"]] = {
            key: {
                "text_sha256": hashlib.sha256(case[field].encode()).hexdigest(),
                "token_ids": [4, 5],
                "boundary_layer": 16,
                "query_independent_encoding": True,
            }
            for key, field in (
                ("intact", "memory_text"),
                ("twin", "twin_memory_text"),
                ("unrelated", "unrelated_memory_text"),
            )
        }
        gates[case["id"]] = {
            condition: {
                "full_logits_exact": True,
                "kv_cache_used": False,
                "positions": 2 if condition == "base_inline" else 1,
                "vocabulary_size": 10,
                "manual_logits_dtype": "torch.bfloat16",
                "ordinary_logits_dtype": "torch.bfloat16",
            }
            for condition in ("base", "base_inline")
        }
        for regime in verifier.REGIMES:
            group = []
            for condition in verifier.CONDITIONS:
                changed = condition == "centered_semantic"
                tokens = [3 if changed else 1, 2]
                text = case["user_prompt"]
                if condition == "base_inline":
                    text = case["memory_text"] + "\n\n" + text
                record = {
                    "id": f"{case['id']}__{regime['id']}__{condition}",
                    "case_id": case["id"],
                    "lane": case["lane"],
                    "regime": regime["id"],
                    "regime_parameters": dict(regime),
                    "condition": condition,
                    "prompt_ids": [4, 5] if condition == "base_inline" else [4],
                    "messages": [{"role": "user", "content": text}],
                    "rendered_prompt": "[INST]" + text + "[/INST]",
                    "generated_ids": tokens,
                    "token_count": len(tokens),
                    "answer": "different" if changed else "same",
                    "finish_reason": "eos",
                    "token_trace": [
                        {
                            "step": step,
                            "token_id": token,
                            "uniform": verifier.uniform(case["id"], regime["seed"], step),
                            "sampling_probability": 1.0 if regime["temperature"] == 0 else 0.2,
                            "delta_l2": 0.1 if changed else 0.0,
                            "native_applied_delta_l2": 0.1 if changed else 0.0,
                            "native_applied_fraction": 0.5 if changed else 0.0,
                            "native_logit_change_max_abs": 0.1 if changed else 0.0,
                            "chosen_native_logit": 1.1 if changed else 1.0,
                            "same_prefix_base_native_logit": 1.0,
                        }
                        for step, token in enumerate(tokens)
                    ],
                }
                rows.append(record)
                group.append(record)
            calls, concurrent = verifier.sharing_receipt(group)
            groups.append(
                {
                    "case_id": case["id"],
                    "regime": regime["id"],
                    "decoder_calls": calls,
                    "maximum_concurrent_prefixes": concurrent,
                    "zero_full_logit_exact_checks": 2,
                    "base_zero_token_ids_exact": True,
                    "persistent_prefix_cache_entries": 0,
                    "kv_cache_used": False,
                }
            )
    bank = {"format": "latent-workspace-v14-answer-bank-v1", "plan_sha256": "f" * 64, "rows": rows}
    report = {
        "format": "latent-workspace-v14-answer-bank-result-v1",
        "status": "QUALIFIED_EXECUTION",
        "winner": "none",
        "semantic_promotion": False,
        "runtime": plan["expected_runtime"],
        "source_identity": plan["source_identity"],
        "claim_boundary": plan["claim_boundary"],
        "plan_sha256": bank["plan_sha256"],
        "base_unchanged": True,
        "bridges_unchanged": True,
        "checkpoint_bodies_unchanged": True,
        "base_state_sha256_before": "a" * 64,
        "base_state_sha256_after": "a" * 64,
        "bridge_state_sha256_before": {"legacy": "b" * 64, "centered": "c" * 64},
        "bridge_state_sha256_after": {"legacy": "b" * 64, "centered": "c" * 64},
        "chat_template_sha256": "d" * 64,
        "ordinary_base_gates": gates,
        "group_receipts": groups,
        "eos_token_ids": [2],
        "denominators": {
            "cases": 16,
            "regimes": 3,
            "conditions": 7,
            "answers": 336,
            "generated_tokens": 672,
        },
        "finish_counts": {"eos": 336},
        "finish_counts_by_condition": {condition: {"eos": 48} for condition in verifier.CONDITIONS},
    }
    return bank, report, cases, plan, memories


def test_reconstructs_full_grid_pairs_and_token_descriptives():
    summary = verifier.verify_bank(*fixture())
    assert summary["status"] == "PASS"
    assert summary["denominators"]["answers"] == 336
    assert len(summary["comparisons"]) == 54
    assert len(summary["trajectory_measurements"]) == 42
    comparison = next(
        c
        for c in summary["comparisons"]
        if c["left"] == "base" and c["right"] == "centered_semantic"
    )
    assert comparison["pairs"] == 8 and comparison["token_identical"] == 0
    assert comparison["first_divergence_token_index"] == {
        "count": 8,
        "mean": 0,
        "median": 0.0,
        "min": 0,
        "max": 0,
    }
    assert summary["verification_limits"]["tokenizer_decoding_recomputed"] is False


@pytest.mark.parametrize("mutation", ["duplicate", "missing"])
def test_rejects_duplicate_or_missing_records(mutation):
    values = fixture()
    rows = values[0]["rows"]
    if mutation == "duplicate":
        rows[-1] = copy.deepcopy(rows[0])
    else:
        rows.pop()
    with pytest.raises(ValueError, match="answer grid"):
        verifier.verify_bank(*values)


@pytest.mark.parametrize("field,value", [("sha256", "0" * 64), ("value", 0.123)])
def test_rejects_changed_uniform_hash_or_value(field, value):
    values = fixture()
    values[0]["rows"][2]["token_trace"][0]["uniform"][field] = value
    with pytest.raises(ValueError, match="uniform"):
        verifier.verify_bank(*values)


def test_rejects_zero_base_trajectory_mismatch():
    values = fixture()
    zero = values[0]["rows"][4]
    zero["generated_ids"][0] = 6
    zero["token_trace"][0]["token_id"] = 6
    with pytest.raises(ValueError, match="Zero/base answer"):
        verifier.verify_bank(*values)


@pytest.mark.parametrize("kind", ["base", "bridge"])
def test_rejects_state_hash_drift(kind):
    values = fixture()
    if kind == "base":
        values[1]["base_state_sha256_after"] = "9" * 64
    else:
        values[1]["bridge_state_sha256_after"]["legacy"] = "9" * 64
    with pytest.raises(ValueError, match="state hash drift"):
        verifier.verify_bank(*values)


def test_rejects_reference_leak_in_declared_prompt():
    values = fixture()
    values[0]["rows"][0]["messages"][0]["content"] += "PRIVATE"
    with pytest.raises(ValueError, match="isolation"):
        verifier.verify_bank(*values)


def test_rejects_varying_chat_template_wrapper():
    values = fixture()
    values[0]["rows"][0]["rendered_prompt"] += "PRIVATE"
    with pytest.raises(ValueError, match="wrapper varies"):
        verifier.verify_bank(*values)


def test_rejects_invalid_eos_and_trace_denominator():
    values = fixture()
    values[0]["rows"][0]["finish_reason"] = "length"
    with pytest.raises(ValueError, match="Length finish"):
        verifier.verify_bank(*values)
    values = fixture()
    values[0]["rows"][0]["token_trace"].pop()
    with pytest.raises(ValueError, match="trace denominator"):
        verifier.verify_bank(*values)


def test_rejects_false_prefix_sharing_and_memory_identity():
    values = fixture()
    values[1]["group_receipts"][0]["decoder_calls"] += 1
    with pytest.raises(ValueError, match="Prefix sharing"):
        verifier.verify_bank(*values)
    values = fixture()
    values[4]["case0"]["intact"]["text_sha256"] = "9" * 64
    with pytest.raises(ValueError, match="Memory text identity"):
        verifier.verify_bank(*values)


def test_rejects_false_finish_aggregates():
    values = fixture()
    values[1]["finish_counts"] = dict(Counter({"length": 336}))
    with pytest.raises(ValueError, match="Aggregate"):
        verifier.verify_bank(*values)


def test_first_divergence_distinguishes_equal_and_prefix_only():
    assert verifier.first_divergence([1, 2], [1, 2]) is None
    assert verifier.first_divergence([1, 2], [1, 3]) == 1
    assert verifier.first_divergence([1, 2], [1, 2, 3]) == 2
