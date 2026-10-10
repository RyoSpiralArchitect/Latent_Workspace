"""Post-result corruption checks; raw inputs and execution source stay untouched."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "scripts"))
import summarize_v15_reader_factors as replay  # noqa: E402


def inputs(arm):
    panel = replay.read(HERE / "raw" / f"{arm}_FACTORS.json")
    prior = replay.read(
        HERE.parent
        / "v15_reader_modulation_20261010/raw"
        / f"retained_answer_step8_{arm}_EVAL.json"
    )["rows"]
    return panel, prior


def test_frozen_summary_and_index():
    assert replay.build(HERE) == replay.read(HERE / "SUMMARY.json")
    assert replay.read(HERE / "ARTIFACT_INDEX.json") == {
        p.name: {"sha256": replay.digest(p), "bytes": p.stat().st_size}
        for p in (HERE / "raw").iterdir()
        if p.is_file()
    }


@pytest.mark.parametrize("arm", replay.ARMS)
def test_prior_and_no_label_controls(arm):
    panel, prior = inputs(arm)
    result = replay.summarize_cell(panel, arm, prior)
    assert result["truth_rows"] == 32 and result["correct"] == 16
    assert result["correct_donor_flips"] == 0 and result["written_zero"] == 16


@pytest.mark.parametrize(
    "damage",
    [
        "missing_row",
        "duplicate_block",
        "synthetic_label",
        "native_score",
        "zero",
        "binding_scope",
        "binding_sign",
        "cap_gain",
        "null",
        "modulation_bound",
    ],
)
def test_corrupt_scalar_receipt_rejected(damage):
    panel, prior = inputs("query_modulated")
    bad = copy.deepcopy(panel)
    if damage == "missing_row":
        bad["rows"].pop()
    elif damage == "duplicate_block":
        bad["blocks"][1] = copy.deepcopy(bad["blocks"][0])
    elif damage == "synthetic_label":
        next(r for r in bad["rows"] if r["variant"] == "random_pair")["label"] = 1
    elif damage == "native_score":
        bad["rows"][0]["native_scores"][0] += 0.125
    elif damage == "zero":
        bad["written_zero"][0]["full_logits_exact"] = False
    elif damage == "binding_scope":
        bad["blocks"][0]["binding_label_interpretation"] = False
    elif damage == "binding_sign":
        bad["blocks"][0]["binding"]["even_donor_margin"] *= -1
    elif damage == "cap_gain":
        bad["blocks"][0]["cap"][0]["radial_scale"] *= 2
    elif damage == "null":
        next(b for b in bad["blocks"] if b["variant"] == "same_memory")["factors"]["d"][
            "interaction"
        ]["l2"] = 1e-8
    else:
        bad["blocks"][0]["modulation_sources"]["rounding_error_max_abs"] = 1
    with pytest.raises(ValueError):
        replay.summarize_cell(bad, "query_modulated", prior)


def test_reader_intervention_preserves_memory_and_pre_modulation_read():
    a, _ = inputs("legacy")
    b, _ = inputs("query_modulated")
    for x, y in zip(a["rows"], b["rows"], strict=True):
        for key in ("world", "query", "variant", "side", "memory_sha256", "mask_sha256"):
            assert x[key] == y[key]
        for key in ("q", "r"):
            assert x["trace_sha256"][key] == y["trace_sha256"][key]
