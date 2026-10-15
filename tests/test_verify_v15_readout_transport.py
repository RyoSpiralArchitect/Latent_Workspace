from __future__ import annotations

import copy
import importlib.util
import itertools
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "v15_transport_verify_test", ROOT / "scripts/verify_v15_readout_transport.py"
)
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)
PLAN = verify.load(ROOT / verify.PLAN_PATH)
OLD = ROOT / PLAN["predecessor_bundle"] / "raw"
RECORDS = verify.load(ROOT / "data/v10/functional_train.jsonl")[:2]


def gradient_fixture():
    return {
        mode: {
            "unchanged": True,
            "optimizer_steps": 0,
            "scope": "PyTorch BF16 cast surrogate-gradient connectivity; not finite-step learning",
            "rows": [
                {
                    "world": 0,
                    "query": q,
                    "native_train_eval_logits_exact": True,
                    "losses": {
                        name: {
                            "loss": 1.0,
                            "parameter_gradient_l2": {p: 0.1 for p in verify.GRADIENT_PARAMETERS},
                        }
                        for name in ("native_two_choice_ce", "native_full_vocab_ce")
                    },
                }
                for q in (0, 1)
            ],
        }
        for mode in verify.MODES
    }


def feature_fixture():
    old = verify.load(OLD / "FEATURES.json")
    return {
        "candidate_ids": old["candidate_ids"],
        "spans": old["spans"],
        "native_gates": old["native_gates"],
        "mean_reduction": PLAN["mean_reduction"],
        "facts": [
            {
                "world": w,
                "side": side,
                "order": order,
                "text": RECORDS[w]["contexts"][side]
                if order == "original"
                else verify.canonical_facts(
                    RECORDS[w]["contexts"][side], reverse=order == "canonical_reverse"
                ),
                "token_ids": [0],
            }
            for w, side, order in itertools.product(range(2), range(2), PLAN["orders"])
        ],
    }


def crossover_fixture():
    from v15_assay_summary import MEMORY_KEYS

    rows = []
    score = {"scores": [0.0, 1.0], "gap": 1.0, "prediction": 1}
    for mode, w, q, memory in itertools.product(verify.MODES, range(2), range(8), MEMORY_KEYS):
        rows.append(
            {
                "mode": mode,
                "world": w,
                "query": q,
                "memory_key": memory,
                "labels": [RECORDS[w]["answers"][s][q] for s in (0, 1)],
                "affected": RECORDS[w]["affected"][q],
                "native": copy.deepcopy(score),
                "fp32": copy.deepcopy(score),
                "base_native": copy.deepcopy(score),
                "base_fp32": copy.deepcopy(score),
                "delta_l2": 0.0,
                "native_applied_delta_l2": 0.0,
                "transport": {
                    "kl_base_to_candidate": 0.0,
                    "total_variation": 0.0,
                    "max_abs_logit_change": 0.0,
                    "logit_change_l2": 0.0,
                    "base_top1": 0,
                    "candidate_top1": 0,
                    "base_top1_probability": 0.5,
                    "candidate_top1_probability": 0.5,
                    "base_top1_candidate_probability": 0.5,
                },
            }
        )
    return {
        "rows": rows,
        "summary": verify.summarize_crossover(rows),
        "shared_historical_native_full_logit_exact_checks": 384,
        "zero_checks": 32,
    }


def generation_fixture(features=None):
    features = features or feature_fixture()
    spans = {(s["world"], s["query"]): s["span"]["prefix_ids"] for s in features["spans"]}
    rows, receipts = [], []
    for w, q, regime in itertools.product(range(2), range(2), verify.REGIMES):
        case = f"w{w}_q{q}"
        for condition in verify.CONDITIONS:
            target = RECORDS[w]["answers"][int(condition.endswith("_twin"))][q]
            rows.append(
                {
                    "id": f"{case}__{regime['id']}__{condition}",
                    "case_id": case,
                    "world": w,
                    "query": q,
                    "condition": condition,
                    "regime": regime["id"],
                    "regime_parameters": regime,
                    "prompt_ids": ([999] if condition == "base_inline" else []) + spans[w, q],
                    "generated_ids": [0],
                    "token_count": 1,
                    "answer": "yes",
                    "target_label": target,
                    "parsed_answer": 1,
                    "lowercase_compliant": True,
                    "strict_correct": target == 1,
                    "finish_reason": "eos",
                    "token_trace": [
                        {
                            "step": 0,
                            "token_id": 0,
                            "uniform": verify.matched_uniform(case, regime["seed"], 0),
                            "sampling_probability": 1.0 if regime["temperature"] == 0 else 0.5,
                            "chosen_token_native_probability": 0.5,
                            "same_prefix_base_chosen_token_native_probability": 0.5,
                            "chosen_native_logit": 1.0,
                            "same_prefix_base_native_logit": 1.0,
                            "native_logit_change_max_abs": 0.0,
                            "native_logit_change_l2": 0.0,
                            "native_top1_token_id": 0,
                            "same_prefix_base_native_top1_token_id": 0,
                            "native_top1_changed": False,
                            "delta_l2": 0.0,
                            "native_applied_delta_l2": 0.0,
                            "native_applied_fraction": 0.0,
                        }
                    ],
                }
            )
        receipts.append(
            {
                "world": w,
                "query": q,
                "regime": regime["id"],
                "decoder_calls": 2,
                "maximum_concurrent_prefixes": 2,
                "shared_historical_native_checks": 8,
                "zero_full_logit_exact_checks_by_condition": {"final_zero": 1, "mean_zero": 1},
                "zero_full_logit_exact_checks": 2,
                "base_zero_token_ids_exact": True,
                "zero_pairs": [["base", "final_zero"], ["base", "mean_zero"]],
                "persistent_prefix_cache_entries": 0,
                "kv_cache_used": False,
                "readout_contract": "shared_native_full_sequence_full_vocabulary",
                "logit_reference": "base_at_same_current_prefix",
                "reader_span_owner": "backend_bound_original_prompt",
            }
        )
    return {
        "rows": rows,
        "receipts": receipts,
        "summary": verify.generation_summary(rows),
        "quality_claim": False,
        "kv_cache_used": False,
        "scope": "exposed functional transport probe",
    }


@pytest.fixture
def bundle(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    old_started, old_report = (verify.load(OLD / name) for name in ("STARTED.json", "REPORT.json"))
    features = feature_fixture()
    generation = generation_fixture(features)
    started = {
        "source_commit": "a" * 40,
        "plan": PLAN,
        "runtime": old_started["runtime"],
        "split": old_started["split_audit"],
        "admission": old_started["admission"],
        "source_hashes": {
            name: verify.digest(ROOT / name)
            for name in set(old_started["source_hashes"]) | verify.SOURCE_ADDITIONS
        },
    }
    report = {
        "status": "COMPLETED_V15_ENGINEERING_ASSAY",
        "optimizer_steps": 0,
        "base_state_sha256_before": verify.BASE_HASH,
        "base_state_sha256_after": verify.BASE_HASH,
        "base_unchanged": True,
        "bridges_unchanged": True,
        "source_unchanged": True,
        "checkpoints": {
            mode: next(
                c
                for c in old_report["results"][mode]["checkpoints"]
                if c["path"] == f"{mode}_step256.pt"
            )
            for mode in verify.MODES
        },
        "crossover_rows": 384,
        "generation_sequences": 64,
        "generation_summary": generation["summary"],
        "elapsed_seconds": 1.0,
        **{
            key: old_report[key]
            for key in (
                "peak_cuda_allocated_bytes",
                "peak_cuda_reserved_bytes",
                "sampled_own_process_peak_bytes",
                "minimum_sampled_device_free_bytes",
            )
        },
        **PLAN["claims"],
    }
    for name, value in {
        "STARTED.json": started,
        "FEATURES.json": features,
        "REPORT.json": report,
        "GRADIENTS.json": gradient_fixture(),
        "GENERATION.json": generation,
        "CROSSOVER.json": crossover_fixture(),
    }.items():
        verify.write_new(raw / name, value)
    (raw / "RESOURCES.jsonl").write_bytes((OLD / "RESOURCES.jsonl").read_bytes())
    return tmp_path


def test_complete_scalar_bundle_verifies_and_index_is_exclusive(bundle):
    result = verify.verify_bundle(bundle, write_index=True)
    assert result["status"] == "VERIFIED_RECEIPTS"
    assert result["raw_files"] == 7
    assert result["native_prefix_parity_checks"] == 16
    assert result["gradients"]["optimizer_steps"] == 0
    assert result["generation"]["decoder_calls"] == 16
    assert result["generation"]["shared_historical_native_checks"] == 64
    assert len(result["generation"]["first_divergences"]) == 56
    assert result["checkpoint_bodies_verified"] is False
    assert result["tokenizer_decode_recomputed"] is False
    assert verify.verify_bundle(bundle) == result
    with pytest.raises(ValueError, match="index collision"):
        verify.verify_bundle(bundle, write_index=True)


@pytest.mark.parametrize(
    "left,right,expected", [([1], [1], None), ([1, 2], [1, 3], 1), ([1], [1, 2], 1), ([2], [1], 0)]
)
def test_first_divergence(left, right, expected):
    assert verify.first_divergence(left, right) == expected


@pytest.mark.parametrize("kind", ["update", "zero", "missing", "nonfinite", "parity"])
def test_gradient_failures(kind):
    data = gradient_fixture()
    cell = data["final"]
    norm = cell["rows"][0]["losses"]["native_two_choice_ce"]["parameter_gradient_l2"]
    if kind == "update":
        cell["optimizer_steps"] = 1
    elif kind == "zero":
        norm.update(dict.fromkeys(norm, 0))
    elif kind == "missing":
        norm.pop("up.weight")
    elif kind == "nonfinite":
        norm["up.weight"] = float("nan")
    else:
        cell["rows"][0]["native_train_eval_logits_exact"] = False
    with pytest.raises(ValueError):
        verify.verify_gradients(data)


@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "uniform",
        "probability",
        "length",
        "zero",
        "counter",
        "prompt",
        "greedy",
        "summary",
        "step",
        "claim",
    ],
)
def test_generation_failure_mutations(kind):
    data = generation_fixture()
    row = data["rows"][0]
    if kind == "missing":
        data["rows"].pop()
    elif kind == "uniform":
        row["token_trace"][0]["uniform"]["value"] = 0.2
    elif kind == "probability":
        row["token_trace"][0]["sampling_probability"] = 2
    elif kind == "length":
        row["finish_reason"] = "length"
    elif kind == "zero":
        data["rows"][4]["token_trace"][0]["delta_l2"] = 0.1
    elif kind == "counter":
        data["receipts"][0]["shared_historical_native_checks"] += 1
    elif kind == "prompt":
        row["prompt_ids"] = [0]
    elif kind == "greedy":
        row["token_trace"][0]["native_top1_token_id"] = 1
    elif kind == "summary":
        data["summary"]["base"]["strict_correct"] += 1
    elif kind == "step":
        row["token_trace"][0]["step"] = 1
    else:
        data["quality_claim"] = True
    with pytest.raises(ValueError):
        verify.verify_generation(data, RECORDS, feature_fixture(), PLAN["generation"])


def test_length_truncated_yes_is_still_incorrect():
    data = generation_fixture()
    for row in data["rows"]:
        row["generated_ids"] = [0] * 64
        row["token_count"] = 64
        row["finish_reason"] = "length"
        row["strict_correct"] = False
        trace = row["token_trace"][0]
        row["token_trace"] = [
            {
                **trace,
                "step": step,
                "uniform": verify.matched_uniform(
                    row["case_id"], row["regime_parameters"]["seed"], step
                ),
            }
            for step in range(64)
        ]
    for receipt in data["receipts"]:
        receipt.update(
            decoder_calls=128,
            shared_historical_native_checks=512,
            zero_full_logit_exact_checks=128,
            zero_full_logit_exact_checks_by_condition={"final_zero": 64, "mean_zero": 64},
        )
    data["summary"] = verify.generation_summary(data["rows"])
    result = verify.verify_generation(data, RECORDS, feature_fixture(), PLAN["generation"])
    assert result["summary"]["base"]["strict_correct"] == 0
    assert result["summary"]["base"]["length_truncated"] == 8
    data["rows"][0]["strict_correct"] = True
    with pytest.raises(ValueError, match="strict correctness"):
        verify.verify_generation(data, RECORDS, feature_fixture(), PLAN["generation"])


@pytest.mark.parametrize("kind", ["source", "checkpoint", "denominator", "feature", "fact", "cap"])
def test_bundle_failure_mutations(bundle, kind):
    filename = {
        "source": "STARTED.json",
        "checkpoint": "REPORT.json",
        "denominator": "REPORT.json",
        "feature": "FEATURES.json",
        "fact": "FEATURES.json",
        "cap": "CROSSOVER.json",
    }[kind]
    path = bundle / "raw" / filename
    data = verify.load(path)
    if kind == "source":
        data["source_hashes"][verify.PLAN_PATH] = "a" * 64
    elif kind == "checkpoint":
        data["checkpoints"]["final"]["bytes"] += 1
    elif kind == "denominator":
        data["generation_sequences"] = 63
    elif kind == "feature":
        data["native_gates"][0]["full_logits_exact"] = False
    elif kind == "fact":
        data["facts"][0]["text"] += "tampered"
    else:
        data["rows"][0]["delta_l2"] = 2
        data["summary"] = verify.summarize_crossover(data["rows"])
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        verify.verify_bundle(bundle, write_index=True)
    assert not (bundle / "ARTIFACT_INDEX.json").exists()


def test_index_tampering_and_duplicate_json_keys_fail(bundle):
    verify.verify_bundle(bundle, write_index=True)
    path = bundle / "raw/REPORT.json"
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="hash/index"):
        verify.verify_bundle(bundle)
    path.write_text('{"status": "one", "status": "two"}')
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        verify.load(path)
