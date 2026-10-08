"""Offline exact-closure tests for the additive evidence tree."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import seal_v14_judge_extension as seal  # noqa: E402


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
        lambda _: {
            "panel_status": "VERIFIED_PARTIAL_RECEIPTS_NOT_GOLD",
            "planned_requests": 420,
            "newly_planned_requests": 280,
            "reused_openai_requests": 140,
            "providers": {"gemini": {"not_dispatched_requests": 140}},
            "semantic_promotion": False,
            "winner": "none",
        },
    )
    return tmp_path


def test_scope_is_exact_sorted_and_original_index_referenced(bundle):
    index = seal.make_index(bundle)
    assert index == seal.make_index(bundle)
    paths = [row["path"] for row in index["artifacts"]]
    assert paths == sorted(set(paths))
    assert f"{seal.aggregator.ORIGINAL_BUNDLE}/INDEX.json" in paths
    assert not any("/cells/openai/" in path for path in paths)


def test_seal_and_validation_are_exclusive_and_missingness_survives(bundle):
    assert seal.seal(bundle)["status"] == "SEALED_INTEGRITY_ONLY"
    with pytest.raises(FileExistsError):
        seal.seal(bundle)
    result = seal.verify(bundle, write_receipt=True)
    assert result["planned_requests"] == 420
    assert result["providers"]["gemini"]["not_dispatched_requests"] == 140
    assert seal.verify(bundle) == result
    with pytest.raises(FileExistsError):
        seal.verify(bundle, write_receipt=True)


@pytest.mark.parametrize("mutation", ["extra", "missing", "changed", "duplicate", "original"])
def test_integrity_drift_rejected(bundle, mutation):
    seal.seal(bundle)
    if mutation == "extra":
        (bundle / seal.BUNDLE / "late.json").write_text("{}")
    elif mutation == "missing":
        (bundle / seal.BUNDLE / "README.md").unlink()
    elif mutation == "changed":
        (bundle / seal.BUNDLE / "README.md").write_text("changed")
    elif mutation == "original":
        (bundle / seal.aggregator.ORIGINAL_BUNDLE / "INDEX.json").write_text("changed")
    else:
        path = bundle / seal.BUNDLE / "INDEX.json"
        index = json.loads(path.read_text())
        index["artifacts"].append(index["artifacts"][0])
        path.write_text(json.dumps(index))
    with pytest.raises(ValueError):
        seal.verify(bundle)


def test_symlink_escape_and_validation_tampering_rejected(bundle):
    seal.seal(bundle)
    seal.verify(bundle, write_receipt=True)
    path = bundle / seal.BUNDLE / "VALIDATION.json"
    value = json.loads(path.read_text())
    value["planned_requests"] = 280
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="validation receipt"):
        seal.verify(bundle)
    with pytest.raises(ValueError, match="escapes"):
        seal.checked_file(bundle, "../outside")
    (bundle / seal.BUNDLE / "LINK").symlink_to(bundle / seal.BUNDLE / "README.md")
    with pytest.raises(ValueError, match="Symlink"):
        seal.make_index(bundle)


def test_payload_failure_prevents_sealing(bundle, monkeypatch):
    def fail(_):
        raise ValueError("Original bundle changed")

    monkeypatch.setattr(seal, "verify_payloads", fail)
    with pytest.raises(ValueError, match="Original bundle"):
        seal.seal(bundle)
    assert not (bundle / seal.BUNDLE / "INDEX.json").exists()
