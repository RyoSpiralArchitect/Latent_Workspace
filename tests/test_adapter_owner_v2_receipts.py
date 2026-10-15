"""Offline mutation tests for published v2 evidence; no model imports/calls."""

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import verify_v15_adapter_owner_v2 as report  # noqa: E402


def test_replay_and_complete_coordinate_denominator():
    assert len(report.expected_cases()) == 164
    value = report.replay(report.DEFAULT)
    assert value == report.read(report.DEFAULT / "SUMMARY.json")
    assert report.artifacts(report.DEFAULT) == report.read(report.DEFAULT / "ARTIFACT_INDEX.json")
    assert value["old_expression_gate"] == "FAIL"
    assert value["real_model_updates"] == 0


@pytest.mark.parametrize("field", ["counts", "status", "device", "scope", "guard", "seal"])
def test_tampered_qualification_cannot_pass(tmp_path, field):
    bundle = tmp_path / "bundle"
    shutil.copytree(report.DEFAULT, bundle)
    raw = bundle / "raw" / "cuda"
    path = raw / "FINISHED.json"
    value = report.read(path)
    if field == "counts":
        value["counts"]["tests"] = 163
    elif field == "status":
        value["status"] = "FAILED"
    elif field == "device":
        value["device"] = "cpu"
    elif field == "scope":
        value["real_model_updates"] = 1
    elif field == "guard":
        start_path = raw / "STARTED.json"
        start = report.read(start_path)
        start["source_check"]["untracked_check"] = "none"
        start_path.write_text(json.dumps(start))
        value["files"]["STARTED.json"] = report.receipt(start_path)
    else:
        path = bundle / "SOURCE_SEAL.json"
        value = report.read(path)
        value["source_commit"] = "0" * 40
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        report.replay(bundle)


def test_rehashed_missing_or_substituted_coordinate_still_fails(tmp_path):
    bundle = tmp_path / "bundle"
    shutil.copytree(report.DEFAULT, bundle)
    raw = bundle / "raw" / "cuda"
    xml = raw / "TESTS.xml"
    xml.write_text(
        xml.read_text().replace(
            "test_v2_serialized_next_update_and_rng", "test_unqualified_substitute", 1
        )
    )
    terminal = report.read(raw / "FINISHED.json")
    terminal["files"]["TESTS.xml"] = report.receipt(xml)
    (raw / "FINISHED.json").write_text(json.dumps(terminal))
    with pytest.raises(ValueError, match="Incomplete test coverage"):
        report.replay(bundle)
