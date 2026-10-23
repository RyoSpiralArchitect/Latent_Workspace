"""Temporary-file retirement only; never real checkpoint bodies or GPU calls."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "provenance/inventory/v24_ft03_canaries_20261023/retire.py"


def fixture(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("ft03_retirement_test", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT, module.OLD = tmp_path / "new", tmp_path / "old"
    module.HELPERS = [HELPER, module.PRIMITIVES]
    selected = []
    for i, folder in enumerate((module.ROOT, module.OLD)):
        (folder / "checkpoints").mkdir(parents=True)
        (folder / "raw/canary").mkdir(parents=True)
        target = folder / "checkpoints/canary_step1.pt"
        target.write_bytes(f"obsolete-{i}".encode())
        receipt = folder / "raw/canary/CHECKPOINT_canary_step1.pt.json"
        saved = dict(bytes=target.stat().st_size, sha256=module.digest(target))
        module.write(receipt, saved)
        selected.append((target, saved, receipt))
    (module.ROOT / "raw/replay").mkdir()
    module.write(module.ROOT / "raw/replay/REPLAY.json", dict(exact=True))
    # Gates are tested by the immutable offline verifier. This fixture tests
    # the destructive primitive and receipt-binding boundary on tiny files.
    monkeypatch.setattr(module, "gates", lambda: ["protected"])
    monkeypatch.setattr(module, "targets", lambda: selected)
    monkeypatch.setattr(module, "unused", lambda: None)
    output = tmp_path / "journal"
    module.inventory(output)
    return module, output, module.digest(output / "INVENTORY.json")


def test_two_exact_bodies_and_only_new_canary_training_receipt(tmp_path, monkeypatch):
    module, output, sha = fixture(tmp_path, monkeypatch)
    kept = tmp_path / "final.pt"
    kept.write_bytes(b"keep")
    before = module.evidence()
    module.execute(output, sha, "a" * 40)
    assert all(not p.exists() for p, _, _ in module.targets())
    assert kept.read_bytes() == b"keep" and module.evidence() == before
    combined = module.read(output / "DELETE_FINISHED.json")
    assert combined["files_deleted"] == 2 and combined["bytes_deleted"] == 20
    new = module.read(module.ROOT / "CANARY_RETIREMENT.json")
    assert new["files_deleted"] == 1
    assert new["checkpoint"] == module.targets()[0][1]
    assert new["combined_retirement_terminal_sha256"] == module.digest(
        output / "DELETE_FINISHED.json"
    )
    assert not (module.OLD / "CANARY_RETIREMENT.json").exists()
    with pytest.raises(ValueError, match="Exclusive"):
        module.execute(output, sha, "a" * 40)


@pytest.mark.parametrize(
    "damage", ["body", "ledger", "receipt", "symlink", "busy", "kept", "extra", "helper"]
)
def test_failed_preconditions_remove_neither_body(tmp_path, monkeypatch, damage):
    module, output, sha = fixture(tmp_path, monkeypatch)
    target, _, receipt = module.targets()[1]
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
    elif damage == "busy":

        def busy():
            raise ValueError("in use")

        monkeypatch.setattr(module, "unused", busy)
    elif damage == "kept":
        monkeypatch.setattr(module, "gates", lambda: ["changed"])
    elif damage == "extra":
        (module.OLD / "added.json").write_text("{}")
    else:
        module.HELPERS = []
    with pytest.raises(ValueError):
        module.execute(output, sha, "a" * 40)
    assert all(p.exists() for p, _, _ in module.targets())
    assert not (output / "DELETE_STARTED.json").exists()
    assert not (module.ROOT / "CANARY_RETIREMENT.json").exists()
