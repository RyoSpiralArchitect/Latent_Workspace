import importlib.util
import json
import sys
from pathlib import Path

import pytest


def fixture(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / (
        "provenance/inventory/v23_obsolete_canaries_20261022/retire.py"
    )
    spec = importlib.util.spec_from_file_location("v23_retire", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ROOT, mod.OLD, mod.V22 = tmp_path, tmp_path / "old", tmp_path / "v22"
    targets = []
    for i in range(3):
        body = tmp_path / f"weight{i}.pt"
        body.write_bytes(f"weight-{i}".encode())
        receipt = tmp_path / f"receipt{i}.json"
        receipt.write_text(json.dumps(dict(bytes=body.stat().st_size, sha256=mod.digest(body))))
        targets.append((body, body.stat().st_size, mod.digest(body), receipt))
    mod.TARGETS = targets
    mod.KEPT = []
    monkeypatch.setattr(mod, "gates", lambda: [])
    for root in (mod.OLD, mod.V22):
        (root / "raw/replay").mkdir(parents=True)
        for rel in ("SOURCE_SEAL.json", "raw/replay/REPLAY.json", "raw/replay/FINISHED.json"):
            (root / rel).write_text("{}")
    output = tmp_path / "record"
    monkeypatch.setattr(sys, "argv", [str(path), "inventory", "--output", str(output)])
    mod.main()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(path),
            "execute",
            "--output",
            str(output),
            "--ledger-sha256",
            mod.digest(output / "INVENTORY.json"),
            "--published-commit",
            "a" * 40,
        ],
    )
    return mod, output


def test_exact_three_files_and_no_repeat(tmp_path, monkeypatch):
    mod, output = fixture(tmp_path, monkeypatch)
    unrelated = tmp_path / "keep.pt"
    unrelated.write_bytes(b"keep")
    mod.main()
    assert all(not p.exists() for p, *_ in mod.TARGETS)
    assert unrelated.read_bytes() == b"keep"
    assert json.loads((output / "DELETE_FINISHED.json").read_text())["files_deleted"] == 3
    with pytest.raises(ValueError, match="repeat"):
        mod.main()


@pytest.mark.parametrize("change", ["body", "symlink", "evidence", "ledger"])
def test_failure_removes_nothing(tmp_path, monkeypatch, change):
    mod, output = fixture(tmp_path, monkeypatch)
    last = mod.TARGETS[-1][0]
    if change == "body":
        last.write_bytes(b"different")
    elif change == "symlink":
        last.unlink()
        last.symlink_to(mod.TARGETS[0][0])
    elif change == "evidence":
        (mod.OLD / "SOURCE_SEAL.json").write_text("changed")
    else:
        (output / "INVENTORY.json").write_text("{}")
    with pytest.raises(ValueError):
        mod.main()
    assert all(p.exists() for p, *_ in mod.TARGETS)
    assert not (output / "DELETE_STARTED.json").exists()
