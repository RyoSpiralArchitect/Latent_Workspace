import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "query_pool_verifier", ROOT / "scripts/verify_ft_beta_query_pool.py"
)
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)
OLD = ROOT / "provenance/pilots/ft_beta_learner_audit_20261009/raw"
RECORDS = verify.load(ROOT / "data/v10/functional_train.jsonl")[:2]


def evaluation(mode="final", step=0):
    score = {
        name: {"scores": [0.0, 1.0], "yes_minus_no": 1.0, "greedy_choice": 1, "tie": False}
        for name in verify.READOUTS
    }
    rows = []
    for w, record in enumerate(RECORDS):
        for q in range(8):
            for side in (0, 1):
                original, donor = [record["answers"][s][q] for s in (side, 1 - side)]
                for control in verify.CONTROLS:
                    rows.append(
                        {
                            "world_index": w,
                            "query_index": q,
                            "side": side,
                            "control": control,
                            "reader_mode": mode,
                            "original_label": original,
                            "donor_label": donor,
                            "target_label": donor if control == "twin" else original,
                            "affected": original != donor,
                            "base_dual_readout": copy.deepcopy(score),
                            "dual_readout": copy.deepcopy(score),
                            "delta_l2": 0.0,
                            "native_applied_delta_l2": 0.0,
                            "native_applied_nonzero": 0,
                            "native_full_vocab_last_changed": 0,
                            "native_full_vocab_last_delta_l2": 0.0,
                            "native_full_vocab_last_delta_max": 0.0,
                            "memory_l2": 0.0,
                        }
                    )
    return {
        "rows": rows,
        "summary": verify.summarize(rows),
        "row_count": 256,
        "zero_full_logit_checks": 16,
        "initial_zero_checks": 160 if step == 0 else 0,
        "scope": "two_exposed_train_worlds_no_generation",
        "winner": "none",
        "semantic_promotion": False,
        "non_regression": "NOT_ESTABLISHED",
        "random_matching": "historical_global_raw_memory_L2",
        "different_schema_amplitude_matched": False,
        "gates": {
            "tiny_feasibility": False,
            "fp32_objective_attainment": False,
            "separation_screen": False,
            "written_zero_full_logit_parity": True,
            "initial_all_controls_zero": True if step == 0 else None,
        },
    }


def gradients():
    value = verify.load(OLD / "legacy_semantic256_gradients.json")
    value["frozen_input_names"] = ["base", "context", "head", "query"]
    value["donor_margins"] = value.pop("batch")["donor_margins"]
    return value


def training():
    return [
        {
            "step": step,
            "preclip_gradient_l2": 0.1,
            "components": {
                "loss": 1.0,
                **{term: 1.0 if term == "paired_ce" else 0.0 for term in verify.WEIGHTS},
            },
            "donor_margins_before_update": [0.0] * 16,
        }
        for step in range(1, 257)
    ]


def resource_fixture():
    rows = [
        {
            "uuid": "GPU-test",
            "own_pid": 123,
            "total_bytes": 32 * verify.GIB,
            "used_bytes": 3 * verify.GIB,
            "free_bytes": 29 * verify.GIB,
            "phase": "admission",
            "monotonic_seconds": 1.0,
            "processes": [{"pid": 321, "bytes": 3 * verify.GIB}],
        }
    ]
    rows.append(
        {
            **rows[0],
            "used_bytes": 22 * verify.GIB,
            "free_bytes": 10 * verify.GIB,
            "phase": "completed",
            "monotonic_seconds": 2.0,
            "allocated": 14 * verify.GIB,
            "reserved": 16 * verify.GIB,
            "peak_allocated": 14 * verify.GIB,
            "peak_reserved": 16 * verify.GIB,
            "processes": [*rows[0]["processes"], {"pid": 123, "bytes": 19 * verify.GIB}],
        }
    )
    report = {
        "peak_cuda_allocated_bytes": 14 * verify.GIB,
        "peak_cuda_reserved_bytes": 16 * verify.GIB,
        "sampled_own_process_peak_bytes": 19 * verify.GIB,
        "minimum_sampled_device_free_bytes": 10 * verify.GIB,
    }
    return rows, {"admission": copy.deepcopy(rows[0])}, report


def features():
    spans, hashes = [], []
    for w, record in enumerate(RECORDS):
        for q, raw in enumerate(record["queries"]):
            question = raw.strip()[: -len("Answer:")].strip()
            token_ids = [w * 8 + q, 100, 101]
            span = {
                "question": question,
                "character_start": 0,
                "character_end": len(question),
                "prefix_ids": token_ids,
                "token_indices": [0, 1],
                "rendered_prefix_sha256": verify.hashlib.sha256(raw.encode()).hexdigest(),
            }
            spans.append(
                {
                    "world": w,
                    "query": q,
                    "raw_query": raw,
                    "rendered_prefix": raw,
                    "span": span,
                    "selected_tokens": ["toy", "tokens"],
                    "metadata_permutations_prefix_equal": [
                        "answers",
                        "side",
                        "query_order",
                        "metadata",
                    ],
                }
            )
            hashes.append(verify.stable_hash(token_ids))
    return {
        "spans": spans,
        "native_gates": [{"prefix_sha256": h, "full_logits_exact": True} for h in hashes],
        "candidate_ids": [1476, 5849],
        "cache_tensor_bytes": 100,
        "use_chat_template": False,
        "prefix_tensor_hashes": dict.fromkeys(hashes, "a" * 64),
        "context_tensor_hashes": {
            str((w, side)): "b" * 64
            for w in range(2)
            for side in (0, 1, "unrelated", "different_schema", "reserialized_0", "reserialized_1")
        },
    }


@pytest.fixture
def bundle(tmp_path):
    """Synthetic execution receipts; no CUDA, tokenizer, checkpoint or model use."""
    raw = tmp_path / "raw"
    raw.mkdir()
    plan = verify.load(ROOT / verify.PLAN_PATH)
    parent = verify.load(ROOT / plan["parent_plan"])
    resources, started, report = resource_fixture()
    started.update(
        plan=plan,
        source_commit="a" * 40,
        runtime=parent["expected_runtime"],
        source_hashes={
            name: verify.digest(ROOT / name)
            for name in set(parent["source_identity"]) | verify.SOURCE_ADDITIONS
        },
    )
    report.update(
        status="COMPLETED_TINY_TRAIN_ONLY",
        base_unchanged=True,
        source_unchanged=True,
        base_state_sha256_before=verify.BASE_HASH,
        base_state_sha256_after=verify.BASE_HASH,
        winner="none",
        semantic_promotion=False,
        heldout_nonregression="NOT_RUN",
        free_text_generation="NOT_RUN",
        results={},
    )
    data = {"STARTED.json": started, "FEATURES.json": features(), "RESOURCES.jsonl": resources}
    for mode in verify.MODES:
        current = {
            "query_mode": mode,
            "steps": 256,
            "parameters": 4200192,
            "initial_state_sha256": "a" * 64,
            "final_state_sha256": "b" * 64,
            "batch_order_sha256": verify.stable_hash([[w, q] for w in range(2) for q in range(8)]),
            "summaries": {},
            "gates": {},
            "checkpoints": [
                {
                    "path": f"{mode}_step{step}.pt",
                    "bytes": 100,
                    "sha256": "c" * 64,
                    "roundtrip_exact": True,
                }
                for step in (128, 256)
            ],
        }
        for step in verify.STEPS:
            value = evaluation(mode, step)
            current["summaries"][str(step)] = value["summary"]
            current["gates"][str(step)] = value["gates"]
            reader = verify.load(OLD / "legacy_semantic256_reader.json")
            reader["query_representation"] = mode
            data.update(
                {
                    f"{mode}_{step}_evaluation.json": value,
                    f"{mode}_{step}_reader.json": reader,
                    f"{mode}_{step}_gradients.json": gradients(),
                }
            )
        data[f"{mode}_REPORT.json"] = current
        data[f"{mode}_training.jsonl"] = training()
        report["results"][mode] = current
    data["REPORT.json"] = report
    for name, value in data.items():
        path = raw / name
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in value)
            if name.endswith(".jsonl")
            else json.dumps(value)
        )
    return tmp_path


def test_complete_synthetic_bundle_seals_and_checks_receipts_only(bundle):
    result = verify.verify_bundle(bundle, write_index=True)
    assert result["raw_artifacts"] == 32
    assert result["primary_step"] == 256
    assert result["checkpoint_bodies_verified"] is False
    assert result["resources"]["process_memory_capped"] is False
    assert result["denominators"]["initial_all_control_checks"] == 320
    assert verify.verify_bundle(bundle) == result
    with pytest.raises(ValueError, match="collision"):
        verify.verify_bundle(bundle, write_index=True)
    path = bundle / "raw/FEATURES.json"
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError, match="hash/index mismatch"):
        verify.verify_bundle(bundle)


@pytest.mark.parametrize(
    "mutation", ["duplicate", "initial_count", "scores", "zero", "summary", "gates", "labels"]
)
def test_evaluation_tampering_fails_closed(mutation):
    value = evaluation()
    if mutation == "duplicate":
        value["rows"][-1] = copy.deepcopy(value["rows"][0])
    elif mutation == "initial_count":
        value["initial_zero_checks"] = 159
    elif mutation == "scores":
        value["rows"][0]["dual_readout"][verify.READOUTS[0]]["greedy_choice"] = 0
    elif mutation == "zero":
        value["rows"][0]["native_full_vocab_last_changed"] = 1
    elif mutation == "summary":
        value["summary"][verify.READOUTS[0]]["affected_correct_flips"] = 4
    elif mutation == "gates":
        value["gates"]["tiny_feasibility"] = True
    else:
        value["rows"][0]["original_label"] ^= 1
    with pytest.raises(ValueError):
        verify.verify_evaluation(value, RECORDS, "final", 0, {})


def test_base_is_fixed_across_modes_and_steps():
    baseline = {}
    verify.verify_evaluation(evaluation(), RECORDS, "final", 0, baseline)
    baseline[(0, 0)] = {}
    with pytest.raises(ValueError, match="Base differs"):
        verify.verify_evaluation(evaluation("mean_span"), RECORDS, "mean_span", 0, baseline)


@pytest.mark.parametrize("mutation", ["reconstruction", "weight", "frozen", "nan"])
def test_gradient_receipts_fail_closed(mutation):
    value = gradients()
    if mutation == "reconstruction":
        value["reconstruction"]["groups"]["writer"]["passed"] = False
    elif mutation == "weight":
        value["terms"]["donor_even_hinge"]["weight"] = 0.25
    elif mutation == "frozen":
        value["frozen_input_names"].remove("base")
    else:
        value["terms"]["paired_ce"]["value"] = float("nan")
    with pytest.raises(ValueError):
        verify.verify_gradients(value)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "loss", "nan"])
def test_training_must_complete_finite_frozen_objective(mutation):
    rows = training()
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows[1]["step"] = 1
    elif mutation == "loss":
        rows[0]["components"]["loss"] = 2
    else:
        rows[0]["components"]["loss"] = float("nan")
    with pytest.raises(ValueError):
        verify.verify_training(rows)


@pytest.mark.parametrize("mutation", ["admission", "free", "cap", "peak", "uuid"])
def test_resource_accounting_fails_closed(mutation):
    rows, started, report = resource_fixture()
    if mutation == "admission":
        rows[0]["free_bytes"] = 19 * verify.GIB
        started["admission"] = copy.deepcopy(rows[0])
    elif mutation == "free":
        rows[1]["free_bytes"] = 3 * verify.GIB
    elif mutation == "cap":
        rows[1]["peak_reserved"] = 19 * verify.GIB
    elif mutation == "peak":
        report["peak_cuda_allocated_bytes"] += 1
    else:
        rows[1]["uuid"] = "another"
    with pytest.raises(ValueError):
        verify.verify_resources(
            rows,
            started,
            report,
            {"admission_free_gib": 20, "abort_free_gib": 4, "allocator_cap_gib": 18},
        )


def test_process_peak_is_not_mistaken_for_allocator_cap():
    rows, started, report = resource_fixture()
    result = verify.verify_resources(
        rows,
        started,
        report,
        {"admission_free_gib": 20, "abort_free_gib": 4, "allocator_cap_gib": 18},
    )
    assert result["sampled_process_peak_bytes"] > result["allocator_cap_bytes"]
    assert result["continuous_process_peak_measured"] is False


@pytest.mark.parametrize("mutation", ["span", "duplicate", "parity", "prefixhash"])
def test_feature_bindings_fail_closed(mutation):
    value = features()
    if mutation == "span":
        value["spans"][0]["span"]["character_end"] -= 1
    elif mutation == "duplicate":
        value["spans"][-1] = copy.deepcopy(value["spans"][0])
    elif mutation == "parity":
        value["native_gates"][0]["full_logits_exact"] = False
    else:
        value["prefix_tensor_hashes"].pop(next(iter(value["prefix_tensor_hashes"])))
    with pytest.raises(ValueError):
        verify.verify_features(value, RECORDS)


@pytest.mark.parametrize(
    "target,change",
    [
        ("STARTED.json", lambda v: v["source_hashes"].pop(next(iter(v["source_hashes"])))),
        ("REPORT.json", lambda v: v.update(base_state_sha256_after="0" * 64)),
        ("REPORT.json", lambda v: v.update(winner="mean_span")),
        ("mean_span_REPORT.json", lambda v: v.update(initial_state_sha256="c" * 64)),
    ],
)
def test_bundle_source_base_claim_and_match_guards(bundle, target, change):
    path = bundle / "raw" / target
    value = verify.load(path)
    change(value)
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        verify.verify_contracts(bundle)


def test_duplicate_json_keys_and_exclusive_output(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"same": 1, "same": 2}')
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        verify.load(path)
    with pytest.raises(FileExistsError):
        verify.write_new(path, {})


def test_unexpected_raw_inventory_and_symlink_fail(bundle):
    (bundle / "raw/FAILED.json").write_text("{}")
    with pytest.raises(ValueError, match="inventory"):
        verify.verify_contracts(bundle)


def test_real_sealed_bundle_reproduces_derived_summary_without_models():
    path = ROOT / "provenance/pilots/ft_beta_query_pool_20261010"
    if not (path / "ARTIFACT_INDEX.json").exists():
        pytest.skip("Execution artifact has not been collected yet")
    result = verify.verify_bundle(path)
    assert result == verify.load(path / "SUMMARY.json")
    assert result["denominators"]["evaluations"] == 8
    assert result["checkpoint_bodies_verified"] is False
