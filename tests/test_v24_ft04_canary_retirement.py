"""Offline evidence and tiny-file-only deletion contract. No GPU/model calls."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "provenance/inventory/v24_ft04_canaries_20261023/retire.py"


def module():
    spec = importlib.util.spec_from_file_location("ft04_retirement_test", HELPER)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_real_ft04_replay_and_ft03_failure_remain_distinct(monkeypatch):
    mod = module()
    monkeypatch.setattr(mod, "SOURCE_TREE", ROOT)
    monkeypatch.setattr(mod, "VERIFIER", ROOT / "scripts/verify_v24_recruitment_ft04.py")
    monkeypatch.setattr(mod, "OLD_VERIFIER", ROOT / "scripts/verify_v24_recruitment_ft03.py")
    monkeypatch.setattr(
        mod, "ROOT", ROOT / "provenance/engineering/v24_recruitment_ft04_20261023/furnace"
    )
    monkeypatch.setattr(
        mod, "OLD", ROOT / "provenance/engineering/v24_recruitment_ft03_20261023/furnace"
    )
    monkeypatch.setattr(mod.common, "KEPT", [])  # No remote bodies in this offline test.
    assert mod.gates() == []
    assert not (mod.OLD / "CANARY_RETIREMENT.json").exists()
    selected = mod.targets()
    assert [saved["sha256"] for _, saved, _ in selected] == [mod.SHA, mod.OLD_SHA]
    assert sum(saved["bytes"] for _, saved, _ in selected) == 58008756888


def fixture(tmp_path, monkeypatch):
    mod = module()
    mod.ROOT, mod.OLD = tmp_path / "new", tmp_path / "old"
    mod.HELPERS = [HELPER, mod.PRIMITIVES]
    selected = []
    for i, folder in enumerate((mod.ROOT, mod.OLD)):
        (folder / "checkpoints").mkdir(parents=True)
        (folder / "raw/canary").mkdir(parents=True)
        target = folder / "checkpoints/canary_step1.pt"
        target.write_bytes(f"obsolete-{i}".encode())
        receipt = folder / "raw/canary/CHECKPOINT_canary_step1.pt.json"
        saved = dict(bytes=target.stat().st_size, sha256=mod.digest(target))
        mod.write(receipt, saved)
        selected.append((target, saved, receipt))
    (mod.ROOT / "raw/replay").mkdir()
    mod.write(mod.ROOT / "raw/replay/REPLAY.json", dict(exact=True))
    protected = tmp_path / "scientific_final.pt"
    protected.write_bytes(b"keep")
    monkeypatch.setattr(mod, "gates", lambda: [mod.identity(protected, 4)])
    monkeypatch.setattr(mod, "targets", lambda: selected)
    monkeypatch.setattr(mod, "unused", lambda: None)
    output = tmp_path / "journal"
    mod.inventory(output)
    return mod, output, mod.digest(output / "INVENTORY.json"), protected


def test_only_two_bodies_and_only_ft04_training_handoff(tmp_path, monkeypatch):
    mod, output, sha, protected = fixture(tmp_path, monkeypatch)
    before = mod.evidence()
    mod.execute(output, sha, "a" * 40)
    assert all(not p.exists() for p, _, _ in mod.targets())
    assert protected.read_bytes() == b"keep" and mod.evidence() == before
    combined = mod.read(output / "DELETE_FINISHED.json")
    assert combined["files_deleted"] == 2 and combined["bytes_deleted"] == 20
    new = mod.read(mod.ROOT / "CANARY_RETIREMENT.json")
    assert new["files_deleted"] == 1
    assert new["checkpoint"] == mod.targets()[0][1]
    assert new["combined_retirement_terminal_sha256"] == mod.digest(output / "DELETE_FINISHED.json")
    assert not (mod.OLD / "CANARY_RETIREMENT.json").exists()
    with pytest.raises(ValueError, match="Exclusive"):
        mod.execute(output, sha, "a" * 40)


@pytest.mark.parametrize(
    "damage",
    [
        "body",
        "ledger",
        "receipt",
        "symlink",
        "hardlink",
        "busy",
        "kept",
        "extra",
        "helper",
        "publication",
        "old_false_retirement",
        "denominator",
        "receipt_path",
    ],
)
def test_failed_preconditions_remove_neither_body(tmp_path, monkeypatch, damage):
    mod, output, sha, protected = fixture(tmp_path, monkeypatch)
    target, _, receipt = mod.targets()[1]
    if damage == "body":
        target.write_bytes(b"changed")
    elif damage == "ledger":
        (output / "INVENTORY.json").write_text("{}")
    elif damage == "receipt":
        receipt.write_text("{}")
    elif damage == "symlink":
        another = tmp_path / "other.pt"
        another.write_bytes(b"obsolete-1")
        target.unlink()
        target.symlink_to(another)
    elif damage == "hardlink":
        (tmp_path / "linked.pt").hardlink_to(target)
    elif damage == "busy":
        monkeypatch.setattr(mod, "unused", lambda: mod.require(False, "in use"))
    elif damage == "kept":
        protected.write_bytes(b"nope")
    elif damage == "extra":
        (mod.OLD / "added.json").write_text("{}")
    elif damage == "helper":
        mod.HELPERS = []
    elif damage == "old_false_retirement":
        (mod.OLD / "CANARY_RETIREMENT.json").write_text("{}")
    elif damage in ("denominator", "receipt_path"):
        value = mod.read(output / "INVENTORY.json")
        if damage == "denominator":
            value["total_bytes"] += 1
        else:
            value["targets"][0]["receipt_path"] = str(tmp_path / "wrong.json")
        (output / "INVENTORY.json").write_text(json.dumps(value))
        sha = mod.digest(output / "INVENTORY.json")
    with pytest.raises(ValueError):
        mod.execute(output, sha, "" if damage == "publication" else "a" * 40)
    assert all(p.exists() for p, _, _ in mod.targets())
    assert not (output / "DELETE_STARTED.json").exists()
    assert not (mod.ROOT / "CANARY_RETIREMENT.json").exists()


def test_exact_allowlist_cannot_take_a_different_receipt(tmp_path, monkeypatch):
    mod = module()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    (tmp_path / "raw/canary").mkdir(parents=True)
    mod.write(
        tmp_path / "raw/canary/CHECKPOINT_canary_step1.pt.json",
        dict(bytes=mod.SIZE, sha256=mod.OLD_SHA),
    )
    with pytest.raises(ValueError, match="Exact approved save receipt"):
        mod.targets()
