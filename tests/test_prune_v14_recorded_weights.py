"""V14 cleanup safety tests use temporary toy files, never real checkpoints."""

import json
import os
from pathlib import Path

import pytest

from scripts import prune_v14_recorded_weights as prune


@pytest.fixture
def scope(tmp_path, monkeypatch):
    root, evidence = tmp_path / "source", tmp_path / "record"
    root.mkdir()
    for name in prune.expected_paths():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"toy weight")
    for i in range(502):
        (root / f"record-{i}.json").write_text('{"toy": true}\n')
    monkeypatch.setattr(prune, "ROOT", root)
    monkeypatch.setattr(prune, "EVIDENCE", evidence)
    monkeypatch.setattr(prune, "TOTAL_BYTES", 44 * len(b"toy weight"))
    monkeypatch.setattr(prune, "git", lambda *a: (prune.ORIGIN if a[0] == "remote"
                                                else "a" * 40).encode())
    monkeypatch.setattr(prune, "protected_other", lambda: {})
    monkeypatch.setattr(prune, "no_open_targets", lambda: {"same_user_open_target_handles": []})
    return root, evidence


def record(scope):
    prune.inventory()
    return prune.sha(scope[1] / "INVENTORY.json")


def permit_test_publication(monkeypatch):
    # The independent publication-rejection test below exercises the real guard.
    monkeypatch.setattr(prune, "verify_published", lambda *_: None)


def test_exact_authorized_scope():
    paths = prune.expected_paths()
    assert len(paths) == 44
    assert sum(p.endswith(".safetensors") for p in paths) == 24
    assert sum(p.endswith("workspace_state.pt") for p in paths) == 6
    assert sum(p.endswith("trainer_state.pt") for p in paths) == 6
    assert sum("bridge_20261009" in p for p in paths) == 8
    assert all("model_cache" not in p and "v15" not in p and "v16" not in p for p in paths)


@pytest.mark.parametrize("name", ["systemd", "(sd-pam)", "sshd-session", "smbd[192.168.11"])
def test_service_visibility_gap_is_explicit(name):
    assert prune.service_visibility_gap(name)


@pytest.mark.parametrize("name", ["python3", "torchrun", "train", "unknown"])
def test_unreadable_learner_process_is_not_exempt(name):
    assert not prune.service_visibility_gap(name)


def test_record_copy_and_delete_only_targets(scope, monkeypatch):
    root, evidence = scope
    digest = record(scope)
    inv = prune.load_inventory(evidence, digest)
    prune.verify_backup(evidence, inv)
    assert all((root / p).exists() for p in prune.expected_paths())
    assert not (evidence / "DELETE_STARTED.json").exists()
    permit_test_publication(monkeypatch)
    prune.execute(digest, "a" * 40)
    done = json.loads((evidence / "DELETE_FINISHED.json").read_text())
    assert done["deleted_count"] == 44 and done["metadata_hashes_preserved"] == 502
    assert not any((root / p).exists() for p in prune.expected_paths())
    assert len(list(root.rglob("*.json"))) == 502
    assert len((evidence / "DELETIONS.jsonl").read_text().splitlines()) == 44
    assert prune.sha(evidence / "INVENTORY.json") == digest
    with pytest.raises(ValueError, match="already started"):
        prune.execute(digest, "a" * 40)


@pytest.mark.parametrize("kind", ["weight", "metadata", "backup", "added_source", "added_backup"])
def test_changes_fail_before_any_deletion(scope, monkeypatch, kind):
    root, evidence = scope
    digest = record(scope)
    inv = prune.load_inventory(evidence, digest)
    paths = {
        "weight": root / inv["weights"][0]["relative_path"],
        "metadata": root / inv["metadata"][0]["relative_path"],
        "backup": evidence / inv["metadata"][0]["backup_relative_path"],
        "added_source": root / "surprise.json",
        "added_backup": evidence / "metadata/surprise.json",
    }
    paths[kind].write_bytes(b"changed")
    permit_test_publication(monkeypatch)
    with pytest.raises(ValueError):
        prune.execute(digest, "a" * 40)
    assert all((root / p).exists() for p in prune.expected_paths())
    assert not (evidence / "DELETE_STARTED.json").exists()


def test_wrong_inventory_seal_cannot_delete(scope, monkeypatch):
    record(scope)
    permit_test_publication(monkeypatch)
    with pytest.raises(ValueError, match="inventory seal"):
        prune.execute("0" * 64, "a" * 40)
    assert all((scope[0] / p).exists() for p in prune.expected_paths())


def test_missing_git_record_cannot_delete(scope):
    digest = record(scope)
    with pytest.raises(ValueError, match="published bytes mismatch"):
        prune.execute(digest, "a" * 40)
    assert all((scope[0] / p).exists() for p in prune.expected_paths())
    assert not (scope[1] / "DELETE_STARTED.json").exists()


def test_all_weight_hashes_checked_before_first_unlink(scope, monkeypatch):
    root, evidence = scope
    record(scope)
    path = evidence / "INVENTORY.json"
    inv = json.loads(path.read_text())
    inv["weights"][-1]["sha256"] = "0" * 64
    path.write_text(json.dumps(inv))
    permit_test_publication(monkeypatch)
    with pytest.raises(ValueError, match="hash mismatch"):
        prune.execute(prune.sha(path), "a" * 40)
    assert all((root / p).exists() for p in prune.expected_paths())
    assert not (evidence / "DELETE_STARTED.json").exists()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "unexpected_weight"])
def test_unsafe_inventory_rejected(scope, kind):
    root, evidence = scope
    target = root / sorted(prune.expected_paths())[0]
    if kind == "symlink":
        (root / "link.json").symlink_to(target)
    elif kind == "hardlink":
        os.link(target, root / "link.json")
    else:
        (root / "unknown.pt").write_bytes(b"not authorized")
    with pytest.raises(ValueError):
        prune.inventory()
    assert not evidence.exists()
    assert all((root / p).exists() for p in prune.expected_paths())


def test_inventory_is_exclusive(scope):
    record(scope)
    with pytest.raises(FileExistsError):
        prune.inventory()


def test_interrupted_delete_has_receipt_and_no_retry(scope, monkeypatch):
    _, evidence = scope
    digest = record(scope)
    permit_test_publication(monkeypatch)
    original = os.unlink
    calls = 0

    def interrupted(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated I/O failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(os, "unlink", interrupted)
    with pytest.raises(OSError, match="simulated"):
        prune.execute(digest, "a" * 40)
    fail = json.loads((evidence / "DELETE_FAILED.json").read_text())
    assert fail["confirmed_deletions"] == 1 and fail["automatic_retry_allowed"] is False
    assert not (evidence / "DELETE_FINISHED.json").exists()
    with pytest.raises(ValueError, match="already started"):
        prune.execute(digest, "a" * 40)


@pytest.mark.parametrize("commit", ["HEAD", "a" * 39, "x" * 40])
def test_publication_requires_exact_commit(commit):
    with pytest.raises(ValueError, match="bad commit"):
        prune.verify_published(commit, {}, "0" * 64)


def test_script_change_rejected(scope, monkeypatch):
    digest = record(scope)
    original = prune.sha
    monkeypatch.setattr(prune, "sha", lambda p: "f" * 64 if p == Path(prune.__file__)
                        else original(p))
    with pytest.raises(ValueError, match="pruner source changed"):
        prune.load_inventory(scope[1], digest)
