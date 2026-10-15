from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "panel_seal_test", REPO / "scripts/seal_v14_judge_panel.py"
)
seal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(seal)


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    for relative in (
        *seal.EXPLICIT_FILES,
        *(f"{seal.BUNDLE}/{name}" for name in seal.REQUIRED_BUNDLE_FILES),
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture artifact\n")
    monkeypatch.setattr(
        seal,
        "verify_payloads",
        lambda root: {
            "panel_status": "VERIFIED_PARTIAL_RECEIPTS_NOT_GOLD",
            "planned_requests": 280,
            "providers": {
                "mistral": {
                    "planned_requests": 140,
                    "reserved_requests": 0,
                    "not_dispatched_requests": 140,
                }
            },
            "semantic_promotion": False,
            "winner": "none",
        },
    )
    return tmp_path


def test_manifest_is_deterministic_sorted_and_scope_bounded(bundle):
    first = seal.make_index(bundle)
    assert first == seal.make_index(bundle)
    paths = [row["path"] for row in first["artifacts"]]
    assert paths == sorted(paths)
    assert len(paths) == len(set(paths))
    assert all(path.startswith(seal.BUNDLE + "/") or path in seal.EXPLICIT_FILES for path in paths)
    assert not any("v14_answer_bank_20261009" in path for path in paths)


def test_seal_is_exclusive_and_verify_preserves_missing_provider(bundle):
    result = seal.seal(bundle)
    assert result["status"] == "SEALED_INTEGRITY_ONLY"
    with pytest.raises(FileExistsError):
        seal.seal(bundle)
    receipt = seal.verify(bundle)
    assert receipt["status"] == "PASS_ARTIFACT_INTEGRITY_ONLY"
    assert receipt["panel_status"] == "VERIFIED_PARTIAL_RECEIPTS_NOT_GOLD"
    assert receipt["providers"]["mistral"]["not_dispatched_requests"] == 140
    assert not (bundle / seal.BUNDLE / "VALIDATION.json").exists()


def test_validation_receipt_optional_exclusive_and_excluded_from_index(bundle):
    seal.seal(bundle)
    first = seal.verify(bundle, write_receipt=True)
    assert seal.verify(bundle) == first
    with pytest.raises(FileExistsError):
        seal.verify(bundle, write_receipt=True)
    index = json.loads((bundle / seal.BUNDLE / "INDEX.json").read_text())
    assert not any(row["path"].endswith("/VALIDATION.json") for row in index["artifacts"])


def test_excluded_validation_receipt_tampering_is_still_rejected(bundle):
    seal.seal(bundle)
    seal.verify(bundle, write_receipt=True)
    path = bundle / seal.BUNDLE / "VALIDATION.json"
    value = json.loads(path.read_text())
    value["providers"]["mistral"]["not_dispatched_requests"] = 0
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="validation receipt does not reconstruct"):
        seal.verify(bundle)


@pytest.mark.parametrize("mutation", ["extra", "changed", "missing", "duplicate_index_row"])
def test_exact_closure_rejects_material_drift(bundle, mutation):
    seal.seal(bundle)
    if mutation == "extra":
        (bundle / seal.BUNDLE / "UNDECLARED.md").write_text("late addition")
    elif mutation == "changed":
        (bundle / seal.BUNDLE / "README.md").write_text("changed")
    elif mutation == "missing":
        (bundle / "tests/test_v14_panel_seal.py").unlink()
    else:
        path = bundle / seal.BUNDLE / "INDEX.json"
        value = json.loads(path.read_text())
        value["artifacts"].append(value["artifacts"][0])
        path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        seal.verify(bundle)


def test_symlink_artifacts_and_outside_paths_are_rejected(bundle):
    (bundle / seal.BUNDLE / "LINK.md").symlink_to(bundle / seal.BUNDLE / "README.md")
    with pytest.raises(ValueError, match="Symlink"):
        seal.make_index(bundle)
    with pytest.raises(ValueError, match="escapes"):
        seal.checked_file(bundle, "../outside.txt")


def test_payload_failure_prevents_sealing(bundle, monkeypatch):
    def fail(root):
        raise ValueError("Aggregator mismatch")

    monkeypatch.setattr(seal, "verify_payloads", fail)
    with pytest.raises(ValueError, match="Aggregator mismatch"):
        seal.seal(bundle)
    assert not (bundle / seal.BUNDLE / "INDEX.json").exists()


def test_old_bundle_changes_are_out_of_new_manifest_scope(bundle):
    seal.seal(bundle)
    old = bundle / "provenance/pilots/v14_answer_bank_20261009/README.md"
    old.parent.mkdir(parents=True)
    old.write_text("Outside the new manifest, independently validated through dependency receipts.")
    assert seal.verify(bundle)["status"] == "PASS_ARTIFACT_INTEGRITY_ONLY"
