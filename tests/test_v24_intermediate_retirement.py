import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def fixture(tmp_path, monkeypatch):
    path = (
        Path(__file__).resolve().parents[1]
        / "provenance/inventory/v24_intermediates_20261022/retire.py"
    )
    spec = importlib.util.spec_from_file_location("v24_retire", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ROOT = tmp_path
    targets = []
    for i in range(2):
        body = tmp_path / f"intermediate{i}.pt"
        body.write_bytes(f"weight{i}".encode())
        receipt = tmp_path / f"receipt{i}.json"
        receipt.write_text(json.dumps(dict(bytes=body.stat().st_size, sha256=mod.digest(body))))
        targets.append((body, body.stat().st_size, mod.digest(body), receipt))
    mod.TARGETS = targets
    mod.EVIDENCE = [t[3] for t in targets]
    monkeypatch.setattr(mod, "gates", lambda: [])
    monkeypatch.setattr(mod, "unused", lambda: None)
    output = tmp_path / "ledger"
    mod.inventory(output)
    return mod, output, mod.digest(output / "INVENTORY.json")


def test_only_two_exact_intermediates_and_no_repeat(tmp_path, monkeypatch):
    mod, output, sha = fixture(tmp_path, monkeypatch)
    retained = tmp_path / "final.pt"
    retained.write_bytes(b"keep")
    mod.execute(output, sha, "a" * 40)
    assert all(not t[0].exists() for t in mod.TARGETS)
    assert retained.read_bytes() == b"keep"
    result = mod.read(output / "DELETE_FINISHED.json")
    assert result["files_deleted"] == 2 and result["bytes_deleted"] == 14
    with pytest.raises(ValueError, match="repeated"):
        mod.execute(output, sha, "a" * 40)


@pytest.mark.parametrize("damage", ["body", "symlink", "receipt", "ledger", "in_use", "retained"])
def test_failed_precondition_deletes_nothing(tmp_path, monkeypatch, damage):
    mod, output, sha = fixture(tmp_path, monkeypatch)
    last = mod.TARGETS[-1][0]
    if damage == "body":
        last.write_bytes(b"CHANGED")
    elif damage == "symlink":
        last.unlink()
        last.symlink_to(mod.TARGETS[0][0])
    elif damage == "receipt":
        mod.TARGETS[-1][3].write_text("{}")
    elif damage == "ledger":
        (output / "INVENTORY.json").write_text("{}")
    elif damage == "in_use":

        def reject():
            raise ValueError("in use")

        monkeypatch.setattr(mod, "unused", reject)
    else:
        monkeypatch.setattr(mod, "gates", lambda: ["changed"])
    with pytest.raises(ValueError):
        mod.execute(output, sha, "a" * 40)
    assert all(t[0].exists() for t in mod.TARGETS)
    assert not (output / "DELETE_STARTED.json").exists()


@pytest.mark.parametrize("code,out,err", [(0, "1234", ""), (2, "", "failed"), (1, "", "denied")])
def test_open_file_check_fails_closed(tmp_path, monkeypatch, code, out, err):
    path = (
        Path(__file__).resolve().parents[1]
        / "provenance/inventory/v24_intermediates_20261022/retire.py"
    )
    spec = importlib.util.spec_from_file_location("v24_retire_unused", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=code, stdout=out, stderr=err),
    )
    with pytest.raises(ValueError):
        mod.unused()


def test_fuser_absolute_operands_and_clean_unused_result(tmp_path, monkeypatch):
    path = (
        Path(__file__).resolve().parents[1]
        / "provenance/inventory/v24_intermediates_20261022/retire.py"
    )
    spec = importlib.util.spec_from_file_location("v24_retire_fuser", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def check(command, **kwargs):
        assert command == ["fuser", *(str(t[0]) for t in mod.TARGETS)]
        assert len(command) == 3 and all(p.startswith("/") for p in command[1:])
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", check)
    mod.unused()
    mod.TARGETS = [(Path("-k"), 0, "", None)]
    with pytest.raises(ValueError, match="Absolute"):
        mod.unused()
