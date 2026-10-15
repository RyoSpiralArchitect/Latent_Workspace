from __future__ import annotations

import copy
import importlib.util
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "completion_verify_test", ROOT / "scripts/verify_v15_completion_mass.py"
)
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)
OLD = ROOT / verify.PREDECESSOR / "raw"


@pytest.fixture
def panel():
    cases = verify.load(OLD / "CASES.json")
    renderings = verify.load(OLD / "RENDERINGS.json")
    choices = verify.load(OLD / "CHOICES.json")
    cases_by_id = {c["case_id"]: c for c in cases}
    choice_by_id = {(r["case_id"], r["renderer"], r["information"]): r for r in choices}
    rows = []
    for rendered in renderings:
        old = choice_by_id[rendered["case_id"], rendered["renderer"], rendered["information"]]
        meta = {**cases_by_id[rendered["case_id"]], **rendered}
        lower = old["candidate_probabilities"]
        upper = max(1e-30, (1 - sum(lower)) / 4)
        aliases = []
        for label, suffix, token, probability in (
            (0, " no", 1476, lower[0]),
            (0, " No", 4999, upper),
            (1, " yes", 5849, lower[1]),
            (1, " Yes", 5999, upper),
        ):
            first, eos = math.log(probability), math.log(0.5)
            aliases.append(
                {
                    "target_label": label,
                    "token_id": token,
                    "suffixes": [suffix],
                    "first_log_probability": first,
                    "eos_log_probability": eos,
                    "complete_log_probability": first + eos,
                    "first_probability": math.exp(first),
                    "eos_probability": math.exp(eos),
                    "complete_probability": math.exp(first + eos),
                }
            )
        ids = rendered["prompt_ids"]
        rows.append(
            {
                **{k: meta[k] for k in verify.METADATA},
                "prefix_ids": ids,
                "prefix_sha256": verify.prefix_hash(ids),
                "old_lowercase_native": old["native"],
                "initial_choice_replay_exact": True,
                "ordinary_shared_full_logits_exact": True,
                "aliases": aliases,
            }
        )
    return rows, renderings, cases, choices


def test_scalar_panel_complete_counts_and_claims(panel):
    summary, counters = verify.verify_scores(*panel)
    assert counters == {
        "rows": 144,
        "alias_forwards": 576,
        "initial_choice_replay_matches": 144,
        "readout_parity_checks": 720,
    }
    assert summary["panel_status"] == "all_cases_exposed_before_this_posthoc_diagnostic"
    assert summary["denominators"]["unique_answer_token_paths"] == 576


def test_within_class_alias_dedup_reduces_actual_forward_count(panel):
    rows = panel[0]
    for row in rows:
        row["aliases"][0]["suffixes"].append(" No")
        row["aliases"].pop(1)
        row["aliases"][1]["suffixes"].append(" Yes")
        row["aliases"].pop(2)
    _, counters = verify.verify_scores(*panel)
    assert counters["alias_forwards"] == 288
    assert counters["readout_parity_checks"] == 432


@pytest.mark.parametrize(
    "mutation",
    [
        lambda rows: rows.pop(),
        lambda rows: rows.__setitem__(-1, copy.deepcopy(rows[0])),
        lambda rows: rows[0].update(target_label=1 - rows[0]["target_label"]),
        lambda rows: rows[0].update(prefix_sha256="a" * 64),
        lambda rows: rows[0].update(prefix_ids=[1, 2]),
        lambda rows: rows[0].update(initial_choice_replay_exact=False),
        lambda rows: rows[0].update(ordinary_shared_full_logits_exact=False),
        lambda rows: rows[0]["old_lowercase_native"].update(gap=999),
        lambda rows: rows[0]["aliases"][0].update(token_id=555),
        lambda rows: rows[0]["aliases"][0].update(first_probability=0.2),
        lambda rows: rows[0]["aliases"][0].update(complete_log_probability=-1),
        lambda rows: rows[0]["aliases"][0].update(eos_probability=1.1),
        lambda rows: rows[0]["aliases"][0].update(suffixes=[" maybe"]),
        lambda rows: rows[0]["aliases"][0].update(first_log_probability=float("nan")),
    ],
)
def test_scalar_panel_mutations_rejected(panel, mutation):
    mutation(panel[0])
    with pytest.raises(ValueError):
        verify.verify_scores(*panel)


@pytest.fixture
def bundle(tmp_path, panel):
    old_started = verify.load(OLD / "STARTED.json")
    old_report = verify.load(OLD / "REPORT.json")
    plan = verify.load(ROOT / verify.PLAN_PATH)
    hashes = {
        name: verify.digest(ROOT / name)
        for name in set(old_started["source_hashes"]) | verify.SOURCE_ADDITIONS
    }
    summary, counters = verify.verify_scores(*panel)
    identity = old_started["tokenizer_identity"]
    started = {
        "source_commit": "a" * 40,
        "source_manifest_before": hashes,
        "runtime": old_started["runtime"],
        "plan": plan,
        "plan_sha256": verify.PLAN_HASH,
        "admission": old_started["admission"],
        "tokenizer_identity_before": identity,
        "predecessor_artifact_index_sha256": plan["predecessor_artifact_index_sha256"],
    }
    report = {
        "status": "COMPLETED_COMPLETION_MASS_ASSAY",
        "optimizer_steps": 0,
        "workspace_loaded": False,
        "generation_sequences": 0,
        "eos_token_ids": [2],
        "base_sha256_before": verify.BASE_HASH,
        "base_sha256_after": verify.BASE_HASH,
        "source_manifest_before": hashes,
        "source_manifest_after": hashes,
        "tokenizer_identity_before": identity,
        "tokenizer_identity_after": identity,
        "plan_sha256": verify.PLAN_HASH,
        "predecessor_artifact_index_sha256": plan["predecessor_artifact_index_sha256"],
        **counters,
        "summary": summary,
        "elapsed_seconds": 1.0,
        **{
            k: old_report[k]
            for k in (
                "peak_cuda_allocated_bytes",
                "peak_cuda_reserved_bytes",
                "sampled_own_process_peak_bytes",
                "minimum_sampled_device_free_bytes",
            )
        },
        **verify.CLAIMS,
    }
    raw = tmp_path / "raw"
    raw.mkdir()
    for name, value in {
        "STARTED.json": started,
        "REPORT.json": report,
        "SCORES.json": panel[0],
    }.items():
        verify.write_new(raw / name, value)
    (raw / "RESOURCES.jsonl").write_bytes((OLD / "RESOURCES.jsonl").read_bytes())
    return tmp_path


def test_portable_complete_bundle_index_roundtrip(bundle):
    result = verify.verify_bundle(bundle, check_index=False)
    verify.write_new(bundle / "ARTIFACT_INDEX.json", verify.index_for(bundle))
    assert verify.verify_bundle(bundle) == result
    assert result["status"] == "VERIFIED_RECEIPTS"
    assert result["source_files_verified"] == 56
    assert result["predecessor_primary_expression_gate"] == "FAIL"
    assert result["prior_generation_sequences_unchanged"] == 288
    assert result["full_logits_recomputed"] is False
    assert result["alias_tokenization_recomputed"] is False
    assert result["instrument_qualified"] is False


@pytest.mark.parametrize(
    "name,mutation",
    [
        ("STARTED.json", lambda v: v.update(plan_sha256="a" * 64)),
        ("STARTED.json", lambda v: v.update(predecessor_artifact_index_sha256="a" * 64)),
        ("STARTED.json", lambda v: v["source_manifest_before"].pop(verify.PLAN_PATH)),
        (
            "STARTED.json",
            lambda v: v["tokenizer_identity_before"].update(chat_template_sha256="a" * 64),
        ),
        ("REPORT.json", lambda v: v.update(base_sha256_after="a" * 64)),
        ("REPORT.json", lambda v: v.update(alias_forwards=575)),
        ("REPORT.json", lambda v: v.update(readout_parity_checks=719)),
        ("REPORT.json", lambda v: v.update(generation_sequences=1)),
        ("REPORT.json", lambda v: v.update(optimizer_steps=1)),
        ("REPORT.json", lambda v: v.update(eos_token_ids=[1])),
        ("REPORT.json", lambda v: v.update(instrument_qualified=True)),
        ("REPORT.json", lambda v: v.update(historical_generation_gate_changed=True)),
        ("REPORT.json", lambda v: v.update(peak_cuda_allocated_bytes=1)),
        ("REPORT.json", lambda v: v["summary"]["denominators"].update(prompt_rows=143)),
    ],
)
def test_portable_bundle_mutations_fail_closed(bundle, name, mutation):
    path = bundle / "raw" / name
    value = verify.load(path)
    mutation(value)
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        verify.verify_bundle(bundle, check_index=False)


def test_raw_change_detected_by_index(bundle):
    verify.write_new(bundle / "ARTIFACT_INDEX.json", verify.index_for(bundle))
    path = bundle / "raw/SCORES.json"
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="Artifact hash"):
        verify.verify_bundle(bundle)


def test_unexpected_raw_artifact_rejected(bundle):
    (bundle / "raw/FAILED.json").write_text("{}")
    with pytest.raises(ValueError, match="Raw inventory"):
        verify.verify_bundle(bundle, check_index=False)
