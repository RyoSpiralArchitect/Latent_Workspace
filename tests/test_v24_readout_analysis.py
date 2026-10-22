import copy
import importlib.util
import math
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "v24_analysis", ROOT / "scripts/analyze_v24_readout_probe.py"
)
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)
BUNDLE = ROOT / "provenance/engineering/v24_readout_probe01_20261022/furnace"


@pytest.mark.parametrize(
    "gold,other,strict,tied",
    [(1.0, 0.0, True, False), (0.0, 1.0, False, False), (1.0, 1.0, False, True)],
)
def test_binding_has_strict_tie_and_full_vocab_denominators(gold, other, strict, tied):
    row = dict(
        target=dict(token_id=8, logit=gold, logprob=-4.0, rank=9, margin_vs_best_other=-2.0),
        probes=[dict(token_id=3, logit=other), dict(token_id=8, logit=gold)],
        eos=dict(logprob=-6.0),
    )
    before = copy.deepcopy(row)
    result = analysis.binding(row)
    assert result["target_strict_choice_win"] is strict and result["candidate_tie"] is tied
    assert result["target_choice_margin"] == gold - other
    assert result["target_probability"] == math.exp(-4.0)
    assert result["target_full_vocab_margin"] == -2.0 and result["target_rank"] == 9
    assert row == before


def test_complete_real_receipts_replay_without_a_model_load():
    had_torch = "torch" in sys.modules
    arms, data, verification = analysis.verify(BUNDLE)
    assert [len(arms[r]) for r in analysis.ROLES] == [44, 44, 44]
    assert verification["native_forward_calls"] == 591
    value = analysis.analyze(arms, data, verification)
    assert value["old_expression_gate"] == "FAIL" and value["winner"] == "none"
    assert value["non_regression"] == "NOT_ESTABLISHED"
    assert all(len(rows) == 44 for rows in value["model_contrasts"].values())
    assert ("torch" in sys.modules) == had_torch


@pytest.mark.parametrize("damage", ["source", "journal", "input", "missing_terminal"])
def test_changed_or_incomplete_publication_is_not_accepted(tmp_path, damage):
    bundle = tmp_path / "bundle"
    shutil.copytree(BUNDLE, bundle)
    if damage == "source":
        path = bundle / "SOURCE_SEAL.json"
        value = analysis.ex.read(path)
        value["source_commit"] = "0" * 40
        path.write_text(analysis.ex.canonical(value))
    elif damage == "journal":
        path = bundle / "raw/on/READOUT.jsonl"
        path.write_text(path.read_text().splitlines()[0] + "\n")
    elif damage == "input":
        (bundle / "raw/off/INPUTS.json").write_text("{}")
    else:
        (bundle / "raw/FINISHED.json").unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        analysis.verify(bundle)
