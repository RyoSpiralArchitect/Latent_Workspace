"""Tiny-file-only retirement contract, not model execution or checkpoint deletion."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "provenance/inventory/v24_ft01_superseded_20261023/retire.py"


def fixture(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("ft01_explicit_retirement_test", HELPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.PROJECT, mod.OLD, mod.RETAINED = tmp_path, tmp_path / "old", tmp_path / "retained"
    for folder in (mod.OLD, mod.RETAINED):
        (folder / "checkpoints").mkdir(parents=True)
    mod.TARGET = mod.OLD / "checkpoints/canary_step1.pt"
    mod.KEPT_CANARY = mod.RETAINED / "checkpoints/canary_step1.pt"
    mod.TARGET.write_bytes(b"old body")
    mod.KEPT_CANARY.write_bytes(b"new body")
    mod.SIZE, mod.SHA, mod.KEPT_SHA = 8, mod.digest(mod.TARGET), mod.digest(mod.KEPT_CANARY)
    mod.RECEIPT = mod.OLD / "saved.json"
    mod.write(mod.RECEIPT, dict(bytes=8, sha256=mod.SHA))
    mod.HELPERS = [HELPER, mod.PRIMITIVES]
    monkeypatch.setattr(mod, "gates", lambda: [mod.identity(mod.KEPT_CANARY, 8)])
    monkeypatch.setattr(mod, "unused", lambda: None)
    output = tmp_path / "ledger"
    mod.inventory(output)
    return mod, output, mod.digest(output / "INVENTORY.json")


def test_one_body_only_and_no_false_training_handoff(tmp_path, monkeypatch):
    mod, output, sha = fixture(tmp_path, monkeypatch)
    evidence = mod.evidence()
    mod.execute(output, sha, "a" * 40)
    assert not mod.TARGET.exists() and mod.KEPT_CANARY.read_bytes() == b"new body"
    assert mod.evidence() == evidence
    end = mod.read(output / "DELETE_FINISHED.json")
    assert end["files_deleted"] == 1 and end["training_gate_satisfied"] is False
    assert end["exact_next_update_replay"] == "NOT_RUN"
    assert not (mod.OLD / "CANARY_RETIREMENT.json").exists()
    assert not (mod.RETAINED / "CANARY_RETIREMENT.json").exists()
    with pytest.raises(ValueError, match="Exclusive"):
        mod.execute(output, sha, "a" * 40)


@pytest.mark.parametrize(
    "fault",
    [
        "body",
        "receipt",
        "ledger",
        "symlink",
        "hardlink",
        "busy",
        "retained",
        "extra_evidence",
        "helpers",
        "publication",
    ],
)
def test_failed_preconditions_preserve_both_bodies(tmp_path, monkeypatch, fault):
    mod, output, sha = fixture(tmp_path, monkeypatch)
    if fault == "body":
        mod.TARGET.write_bytes(b"different")
    elif fault == "receipt":
        mod.RECEIPT.write_text("{}")
    elif fault == "ledger":
        (output / "INVENTORY.json").write_text("{}")
    elif fault == "symlink":
        mod.TARGET.unlink()
        mod.TARGET.symlink_to(mod.KEPT_CANARY)
    elif fault == "hardlink":
        (tmp_path / "linked.pt").hardlink_to(mod.TARGET)
    elif fault == "busy":
        monkeypatch.setattr(mod, "unused", lambda: mod.require(False, "busy"))
    elif fault == "retained":
        mod.KEPT_CANARY.write_bytes(b"changed!")
    elif fault == "extra_evidence":
        (mod.OLD / "added.json").write_text("{}")
    elif fault == "helpers":
        mod.HELPERS = []
    with pytest.raises((ValueError, KeyError)):
        mod.execute(output, sha, "" if fault == "publication" else "a" * 40)
    assert mod.TARGET.exists() and mod.KEPT_CANARY.exists()
    assert not (output / "DELETE_STARTED.json").exists()
