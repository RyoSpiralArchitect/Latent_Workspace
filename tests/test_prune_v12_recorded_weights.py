"""Safety tests on temporary toy files only; never touch Furnace paths."""

import hashlib
import os
from pathlib import Path

import pytest

from scripts import prune_v12_recorded_weights as prune


def toy(tmp_path):
    path = tmp_path / "state.pt"
    path.write_bytes(b"not real weights")
    record = prune.signature(path.stat())
    record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, record


def test_exact_scope():
    paths = prune.expected_paths()
    assert len(paths) == 90
    assert all("/final/" in p and "model_cache" not in p and ".." not in p for p in paths)
    assert sum(p.endswith(".safetensors") for p in paths) == 60
    assert sum(p.endswith("trainer_state.pt") for p in paths) == 15
    assert sum(p.endswith("workspace_state.pt") for p in paths) == 15


def test_hash_is_read_only(tmp_path):
    path, record = toy(tmp_path)
    with prune.parent_fd(tmp_path.resolve(), path.name) as (fd, name):
        prune.checked_hash(fd, name, record)
    assert path.read_bytes() == b"not real weights"


def test_changed_target_rejected(tmp_path):
    path, record = toy(tmp_path)
    path.write_bytes(b"changed")
    with prune.parent_fd(tmp_path.resolve(), path.name) as (fd, name):
        with pytest.raises(ValueError, match="changed"):
            prune.checked_hash(fd, name, record)
    assert path.exists()


def test_digest_mismatch_rejected(tmp_path):
    path, record = toy(tmp_path)
    record["sha256"] = "0" * 64
    with prune.parent_fd(tmp_path.resolve(), path.name) as (fd, name):
        with pytest.raises(ValueError, match="hash mismatch"):
            prune.checked_hash(fd, name, record)


def test_symlink_target_rejected(tmp_path):
    path, record = toy(tmp_path)
    link = tmp_path / "link.pt"
    link.symlink_to(path)
    with prune.parent_fd(tmp_path.resolve(), link.name) as (fd, name):
        with pytest.raises(ValueError, match="regular file"):
            prune.checked_stat(fd, name, record)
    assert path.exists()


def test_symlink_parent_rejected(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real")
    with pytest.raises(OSError):
        with prune.parent_fd(tmp_path.resolve(), "link/state.pt"):
            pytest.fail("followed a symbolic parent")


def test_hardlink_rejected(tmp_path):
    path, record = toy(tmp_path)
    os.link(path, tmp_path / "other.pt")
    with prune.parent_fd(tmp_path.resolve(), path.name) as (fd, name):
        with pytest.raises(ValueError, match="single-link"):
            prune.checked_stat(fd, name, record)


@pytest.mark.parametrize("relative", ["../state.pt", "/state.pt", "a/../../state.pt"])
def test_escape_rejected(tmp_path, relative):
    with pytest.raises(ValueError):
        with prune.parent_fd(tmp_path.resolve(), relative):
            pytest.fail("accepted a path escape")


def test_receipt_is_exclusive(tmp_path):
    path = tmp_path / "receipt.json"
    prune.durable_json(path, {"deleted": 0})
    with pytest.raises(FileExistsError):
        prune.durable_json(path, {"deleted": 90})
    assert '"deleted": 0' in path.read_text()


def test_default_dispatch_cannot_delete(monkeypatch):
    # A wrong inventory seal fails even when the execute flag is supplied.
    monkeypatch.setattr(Path, "read_bytes", lambda _: b"{}")
    monkeypatch.setattr(os, "unlink", lambda *_a, **_kw: pytest.fail("deleted"))
    with pytest.raises(ValueError, match="inventory seal changed"):
        prune.run(execute=True)
