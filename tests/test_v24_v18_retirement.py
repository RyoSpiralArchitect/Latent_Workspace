import importlib.util
import json
from pathlib import Path

import pytest


def setup(tmp_path, monkeypatch):
    path = (
        Path(__file__).resolve().parents[1]
        / "provenance/inventory/v24_v18_engineering_20261023/retire.py"
    )
    spec = importlib.util.spec_from_file_location("v18_retire", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ROOT = tmp_path
    mod.TARGETS = []
    for i in range(2):
        body, receipt = tmp_path / f"step{i}.pt", tmp_path / f"saved{i}.json"
        body.write_bytes(f"weight{i}".encode())
        receipt.write_text(json.dumps(dict(bytes=7, sha256=mod.digest(body))))
        mod.TARGETS.append((body, 7, mod.digest(body), receipt))
    mod.EVIDENCE = [t[3] for t in mod.TARGETS]
    monkeypatch.setattr(mod, "gates", lambda: [])
    monkeypatch.setattr(mod, "unused", lambda: None)
    output = tmp_path / "ledger"
    mod.inventory(output)
    return mod, output, mod.digest(output / "INVENTORY.json")


def test_exact_two_and_no_repeat(tmp_path, monkeypatch):
    mod, output, sha = setup(tmp_path, monkeypatch)
    kept = tmp_path / "latest.pt"
    kept.write_bytes(b"keep")
    mod.execute(output, sha, "a" * 40)
    assert all(not t[0].exists() for t in mod.TARGETS)
    assert kept.read_bytes() == b"keep"
    assert mod.read(output / "DELETE_FINISHED.json")["bytes_deleted"] == 14
    with pytest.raises(ValueError, match="repeated"):
        mod.execute(output, sha, "a" * 40)


@pytest.mark.parametrize("damage", ["body", "symlink", "receipt", "ledger", "in_use", "kept"])
def test_rejection_deletes_nothing(tmp_path, monkeypatch, damage):
    mod, output, sha = setup(tmp_path, monkeypatch)
    path = mod.TARGETS[-1][0]
    if damage == "body":
        path.write_bytes(b"CHANGED")
    elif damage == "symlink":
        path.unlink()
        path.symlink_to(mod.TARGETS[0][0])
    elif damage == "receipt":
        mod.TARGETS[-1][3].write_text("{}")
    elif damage == "ledger":
        (output / "INVENTORY.json").write_text("{}")
    elif damage == "in_use":

        def fail():
            raise ValueError("in use")

        monkeypatch.setattr(mod, "unused", fail)
    else:
        monkeypatch.setattr(mod, "gates", lambda: ["changed"])
    with pytest.raises(ValueError):
        mod.execute(output, sha, "a" * 40)
    assert all(t[0].exists() for t in mod.TARGETS)
    assert not (output / "DELETE_STARTED.json").exists()
