"""Read-only receipt validation and corruption rejection using the sealed raw runs.

These tests intentionally do not require SUMMARY.json or ARTIFACT_INDEX.json.
All mutations affect deep-copied Python objects, never the evidence files.
"""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "provenance/pilots/v14_mech_repair_20261009"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture(scope="module")
def receipts():
    spec = importlib.util.spec_from_file_location("mech_repair_test_verifier", BUNDLE / "verify.py")
    assert spec is not None and spec.loader is not None
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    previous = verifier.load_module(
        "mech_repair_test_previous_verifier", ROOT / verifier.OLD_VERIFY
    )

    def read(path):
        return verifier.read_json(path, previous)

    plan = read(ROOT / verifier.REPAIR_PLAN)
    evidence_paths = [
        BUNDLE / "mechanistic/report.json",
        *sorted((BUNDLE / "repair").glob("*.json")),
    ]
    evidence_paths += [ROOT / plan["data"][split]["path"] for split in ("train", "eval")]
    before = {path: previous.digest(path) for path in evidence_paths}
    data = verifier.verify_fresh_data(plan, ROOT, previous)
    yield SimpleNamespace(
        verifier=verifier,
        previous=previous,
        plan=plan,
        old_plan=read(ROOT / verifier.OLD_PLAN),
        old_report=read(ROOT / plan["predecessor"]["path"]),
        mi_plan=read(ROOT / verifier.MI_PLAN),
        mi=read(BUNDLE / "mechanistic/report.json"),
        repair=read(BUNDLE / "repair/report.json"),
        multi=read(BUNDLE / "repair/multiturn_centered.json"),
        data=data,
    )
    assert {path: previous.digest(path) for path in evidence_paths} == before


def _verify_mi(receipts, report):
    return receipts.verifier.verify_mechanistic(
        report,
        receipts.mi_plan,
        receipts.old_report,
        receipts.data["datasets"]["train"],
        ROOT,
        receipts.previous,
        False,
    )


def test_frozen_raw_subverification_passes_without_model_or_weights(receipts, monkeypatch):
    from latent_workspace_ft_v10 import engine

    def forbidden(*args, **kwargs):
        pytest.fail("Receipt-only verification must not load a model or checkpoint")

    monkeypatch.setattr(engine, "_load_hf_model", forbidden)
    monkeypatch.setattr(torch, "load", forbidden)
    mi = _verify_mi(receipts, receipts.mi)
    assert (mi["trace_rows"], mi["reverse_pairs"]) == (1280, 640)
    assert mi["training_worlds_only"] == 16
    assert mi["manual_delta_max_error"] <= 1e-5
    assert mi["slot_permutation_exact"]
    result = receipts.verifier.verify_repair(
        receipts.repair,
        receipts.plan,
        receipts.old_plan,
        receipts.old_report,
        receipts.mi,
        receipts.data,
        BUNDLE,
        ROOT,
        receipts.previous,
        False,
    )
    assert (result["single_rows"], result["trajectories"], result["turns"]) == (24576, 1792, 7168)
    assert (result["reader_panel_rows"], result["reader_panel_reverse_pairs"]) == (1024, 512)
    assert result["new_checkpoint_count"] == 4
    assert result["initial_zero_exact"] and result["zero_controls_exact_base"]
    assert result["matched_uniforms_recomputed"]
    assert result["fixed_history_intact_twin_prefixes_equal"]
    commit = receipts.verifier.verify_started(
        BUNDLE / "repair/STARTED.json", receipts.repair["plan_sha256"], receipts.previous
    )
    assert commit == receipts.repair["source_commit"]


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("missing_row", "MI trace grid closure"),
        ("manual_error", "Manual reader reconstruction failed"),
        ("slot_placebo", "Slot-permutation placebo not exact"),
        ("summary", "MI summary does not rebuild"),
    ],
)
def test_mechanistic_corruption_fails_closed(receipts, mutation, expected_error):
    changed = copy.deepcopy(receipts.mi)
    if mutation == "missing_row":
        changed["rows"].pop()
    elif mutation == "manual_error":
        changed["rows"][0]["manual_delta_max_error"] = 1e-4
    elif mutation == "slot_placebo":
        changed["rows"][0]["interventions"]["slot_permutation"]["gap_change"] = 1e-7
    elif mutation == "summary":
        changed["summary"]["initial"]["trace_count"] = 0
    else:
        raise AssertionError(f"Unknown mutation: {mutation}")
    with pytest.raises(ValueError, match=expected_error):
        _verify_mi(receipts, changed)


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("uniform", "Matched uniform drift"),
        ("fixed_prefix", "Fixed-history intact/twin prefixes differ"),
        ("generated_history", "Generated history"),
    ],
)
def test_multiturn_corruption_fails_closed(receipts, mutation, expected_error):
    changed = copy.deepcopy(receipts.multi)
    if mutation == "uniform":
        row = next(r for r in changed["rows"] if r["regime"] == "sample_211")
        row["turns"][0]["matched_uniform"] = 0.0
    elif mutation == "fixed_prefix":
        row = next(
            r
            for r in changed["rows"]
            if r["condition"] == "semantic_twin"
            and r["history_mode"] == "teacher_forced_fixed_history"
        )
        row["turns"][1]["prefix_token_sha256"] = "f" * 64
    elif mutation == "generated_history":
        changed["rows"][0]["turns"][2]["history_generated_labels_before_turn"] = []
    else:
        raise AssertionError(f"Unknown mutation: {mutation}")
    with pytest.raises(ValueError, match=expected_error):
        receipts.previous.verify_multi(changed, receipts.data["datasets"]["eval"])
