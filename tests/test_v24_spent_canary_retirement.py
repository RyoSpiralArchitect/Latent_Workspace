import importlib.util
import json
from pathlib import Path

import pytest


def test_actual_failed_canary_is_not_spent_or_retirable(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    path = root / "provenance/inventory/v24_spent_canary_20261023/retire.py"
    spec = importlib.util.spec_from_file_location("blocked_spent_canary", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(
        mod, "ROOT", root / "provenance/engineering/v24_recruitment_ft01_20261023/furnace"
    )
    with pytest.raises(ValueError, match="Complete checks phase"):
        mod.gates()


def setup(tmp_path, monkeypatch):
    path = (
        Path(__file__).resolve().parents[1]
        / "provenance/inventory/v24_spent_canary_20261023/retire.py"
    )
    spec = importlib.util.spec_from_file_location("spent_canary", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ROOT = tmp_path
    mod.TARGET, mod.RECEIPT = tmp_path / "canary.pt", tmp_path / "saved.json"
    mod.TARGET.write_bytes(b"obsolete-canary")
    mod.RECEIPT.write_text(json.dumps(dict(bytes=15, sha256=mod.digest(mod.TARGET))))
    (tmp_path / "raw/replay").mkdir(parents=True)
    mod.write(tmp_path / "raw/replay/REPLAY.json", dict(exact=True))
    mod.EVIDENCE = [mod.RECEIPT, tmp_path / "raw/replay/REPLAY.json"]
    monkeypatch.setattr(mod, "gates", lambda: [])
    monkeypatch.setattr(mod, "unused", lambda: None)
    output = tmp_path / "retirement"
    mod.inventory(output)
    return mod, output, mod.digest(output / "INVENTORY.json")


def test_one_exact_body_and_bound_training_handoff(tmp_path, monkeypatch):
    mod, output, sha = setup(tmp_path, monkeypatch)
    latest = tmp_path / "final.pt"
    latest.write_bytes(b"keep")
    mod.execute(output, sha, "a" * 40)
    assert not mod.TARGET.exists() and latest.read_bytes() == b"keep"
    assert mod.read(output / "DELETE_FINISHED.json") == mod.read(
        tmp_path / "CANARY_RETIREMENT.json"
    )
    assert mod.read(tmp_path / "CANARY_RETIREMENT.json")["files_deleted"] == 1
    with pytest.raises(ValueError, match="Exclusive"):
        mod.execute(output, sha, "a" * 40)


@pytest.mark.parametrize("damage", ["body", "receipt", "ledger", "symlink", "busy", "kept"])
def test_any_failed_precondition_leaves_canary(tmp_path, monkeypatch, damage):
    mod, output, sha = setup(tmp_path, monkeypatch)
    if damage == "body":
        mod.TARGET.write_bytes(b"CHANGED")
    elif damage == "receipt":
        mod.RECEIPT.write_text("{}")
    elif damage == "ledger":
        (output / "INVENTORY.json").write_text("{}")
    elif damage == "symlink":
        target = tmp_path / "other.pt"
        target.write_bytes(b"obsolete-canary")
        mod.TARGET.unlink()
        mod.TARGET.symlink_to(target)
    elif damage == "busy":

        def fail():
            raise ValueError("busy")

        monkeypatch.setattr(mod, "unused", fail)
    else:
        monkeypatch.setattr(mod, "gates", lambda: ["changed"])
    with pytest.raises(ValueError):
        mod.execute(output, sha, "a" * 40)
    assert mod.TARGET.exists()
    assert not (output / "DELETE_STARTED.json").exists()
    assert not (tmp_path / "CANARY_RETIREMENT.json").exists()
