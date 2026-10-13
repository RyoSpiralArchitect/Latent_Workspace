"""Post-result offline checks; never execute or select a learner."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("native_publication", HERE / "publish_receipts.py")
publication = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publication)
verify = publication.verify


def test_reader_phase_replay():
    phase = verify.build_phase(HERE / "raw/reader", verify.read(HERE / "SOURCE_SEAL.json"))
    assert phase["stored_evaluation_rows"] == 576
    assert phase["stored_generated_sequences"] == 80


@pytest.mark.parametrize("name", ["legacy", "query_modulated"])
def test_factor_panel_missing_or_inconsistent_corners_rejected(name):
    panel = verify.read(HERE / "raw/reader" / f"{name}_8_factors.json")
    evaluation = verify.read(HERE / "raw/reader" / f"{name}_8_evaluation.json")["rows"]
    valid = verify.factor_summary(panel, evaluation)
    assert valid["blocks"] == 32
    for error in ("missing_block", "duplicate_corner", "native_mismatch", "broken_null"):
        bad = copy.deepcopy(panel)
        if error == "missing_block":
            bad["blocks"].pop()
        elif error == "duplicate_corner":
            bad["rows"][-1] = bad["rows"][0]
        elif error == "native_mismatch":
            bad["rows"][0]["native_scores"][0] += 1
        else:
            target = next(b for b in bad["blocks"] if b["variant"] == "same_memory")
            target["factors"]["d"]["interaction"]["l2"] = 1
        with pytest.raises(ValueError):
            verify.factor_summary(bad, evaluation)


def test_literal_bank_escaped_strings_roundtrip():
    phase = verify.build_phase(HERE / "raw/reader", verify.read(HERE / "SOURCE_SEAL.json"))
    _, bank = publication.derive({"source_commit": "test", "phases": {"reader": phase}})
    assert len(bank) == 80
    for row in bank:
        assert json.loads(json.dumps(row["answer"], ensure_ascii=False)) == row["answer"]
    # Exercise whitespace and Markdown-sensitive symbols independent of the
    # particular model strings in this run.
    row = copy.deepcopy(bank[0])
    row["answer"] = '  a|b\n```\n"quoted" ' + "\t"
    text = publication.render_bank([row])
    encoded = text.split("```json\n", 1)[1].split("\n```", 1)[0]
    assert json.loads(encoded) == row["answer"]


def test_terminal_and_all_seals():
    if not (HERE / "ARTIFACT_INDEX.json").exists():
        pytest.skip("Terminal collection has not been sealed yet")
    summary = verify.build(HERE)
    assert set(summary["phases"]) == {"reader", "full"}
    assert all(p["stored_generated_sequences"] == 80 for p in summary["phases"].values())
    assert summary["old_expression_gate"] == "FAIL"
    assert not summary["semantic_promotion"]


def test_checkpoint_source_and_comparison_receipts():
    audit = verify.read(HERE / "raw/CHECKPOINT_AUDIT.json")
    assert audit["script_sha256"] == verify.digest(HERE / "audit_checkpoints.py")
    assert audit["files"] == 8
    assert audit["step1_frozen_full_bridge_and_adamw_exact"]
    assert audit["model_forwards"] == audit["model_updates"] == 0


def test_prose_numbers_links_and_literal_examples():
    import sys

    sys.path.insert(0, str(HERE))
    from check_publication import verify_publication

    assert verify_publication()["literal_excerpts"] == 3
