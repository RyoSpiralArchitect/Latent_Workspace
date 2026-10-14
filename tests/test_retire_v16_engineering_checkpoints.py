"""Temporary, tiny files only. No Furnace, model, actual weight or network calls."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import retire_v16_engineering_checkpoints as retire  # noqa: E402


@pytest.fixture
def targets(tmp_path):
    root = tmp_path.resolve() / "fixture_run" / "checkpoints"
    root.mkdir(parents=True)
    result = []
    for index in range(4):
        path = root / f"step{index}.pt"
        content = f"tiny fixture {index}".encode()
        path.write_bytes(content)
        result.append((str(path), len(content), hashlib.sha256(content).hexdigest()))
    return tuple(result)


def records(targets):
    return [retire.inspect_weight(*target) for target in targets]


def test_exact_allowlist_and_historical_hash_bindings():
    plan = retire.plan()
    assert len(plan["targets"]) == 4
    assert sum(t["bytes"] for t in plan["targets"]) == 58210741126
    assert len(plan["protected_current_v16"]) == 6
    assert not set(t["path"] for t in plan["targets"]) & set(plan["protected_current_v16"])
    assert plan["old_gate"] == "FAIL" and plan["winner"] == "none"
    assert plan["weights_reconstructible_from_hashes"] is False
    checkpoint_receipts = [name for name in retire.EVIDENCE if name.endswith("CHECKPOINT.json")]
    assert len(checkpoint_receipts) == 4
    for target, name in zip(retire.TARGETS, checkpoint_receipts):
        receipt = retire.read_json(retire.ROOT / name)
        assert receipt["path"] == Path(target[0]).name
        assert (receipt["bytes"], receipt["sha256"]) == target[1:]
    assert len(plan["historical_evidence_sha256"]) == len(retire.EVIDENCE)


@pytest.mark.parametrize("fault", ["missing", "size", "hash", "symlink", "hardlink"])
def test_weight_validation_rejects_mismatch(targets, fault):
    path, size, digest = targets[0]
    weight = Path(path)
    if fault == "missing":
        weight.unlink()
    elif fault == "size":
        size += 1
    elif fault == "hash":
        digest = "0" * 64
    elif fault == "symlink":
        weight.unlink()
        weight.symlink_to(targets[1][0])
    else:
        os.link(weight, weight.parent / "extra-link")
    with pytest.raises((ValueError, FileNotFoundError)):
        retire.inspect_weight(path, size, digest)


def test_symlink_ancestor_and_relative_path_rejected(targets, tmp_path):
    link = tmp_path.resolve() / "alias"
    link.symlink_to(Path(targets[0][0]).parent, target_is_directory=True)
    with pytest.raises(ValueError, match="ancestor"):
        retire.regular(link / Path(targets[0][0]).name)
    with pytest.raises(ValueError, match="Absolute"):
        retire.regular(Path("relative.pt"))


def test_mutation_during_hash_rejected(targets, monkeypatch):
    original = hashlib.file_digest

    def mutate(stream, algorithm):
        result = original(stream, algorithm)
        Path(targets[0][0]).write_bytes(b"changed")
        return result

    monkeypatch.setattr(hashlib, "file_digest", mutate)
    with pytest.raises(ValueError, match="changed while hashing"):
        retire.inspect_weight(*targets[0])


@pytest.mark.parametrize("fault", ["count", "path", "hash", "size", "stat", "missing", "handles"])
def test_all_file_preflight_fails_without_mutation(targets, fault):
    observed = records(targets)
    pristine = [Path(item[0]).read_bytes() for item in targets]
    if fault == "count":
        observed.pop()
    elif fault == "path":
        observed[-1]["path"] += "-unapproved"
    elif fault == "hash":
        observed[-1]["sha256"] = "0" * 64
    elif fault == "size":
        observed[-1]["stat"]["size_bytes"] += 1
    elif fault == "stat":
        observed[-1]["stat"]["inode"] += 1
    elif fault == "missing":
        Path(targets[-1][0]).unlink()

    def screen(_paths):
        if fault == "handles":
            raise ValueError("active handle")
        return {"visible_open_targets": []}

    with pytest.raises((ValueError, FileNotFoundError)):
        retire.preflight(observed, targets, screen)
    for index, target in enumerate(targets):
        if not (fault == "missing" and index == 3):
            assert Path(target[0]).read_bytes() == pristine[index]


def test_exact_unlink_journal_and_unrelated_sibling(targets, tmp_path):
    observed = records(targets)
    marker = Path(targets[0][0]).parent / "preserve.txt"
    marker.write_text("protected fixture")
    retire.preflight(observed, targets, lambda paths: {"paths": paths})
    journal_path = tmp_path / "journal.jsonl"
    with journal_path.open("x") as journal:
        retire.unlink_recorded(observed, journal)
    events = [json.loads(line) for line in journal_path.read_text().splitlines()]
    assert [e["event"] for e in events] == ["UNLINK_INTENT", "UNLINK_CONFIRMED"] * 4
    assert [e["path"] for e in events[::2]] == [t[0] for t in targets]
    assert not any(Path(t[0]).exists() for t in targets)
    assert marker.read_text() == "protected fixture"


def test_changed_after_preflight_not_deleted(targets, tmp_path):
    observed = records(targets)
    Path(targets[0][0]).write_bytes(b"changed before unlink")
    with (tmp_path / "journal").open("x") as journal:
        with pytest.raises(ValueError, match="changed immediately"):
            retire.unlink_recorded(observed, journal)
    assert all(Path(t[0]).exists() for t in targets)


def test_unlink_failure_preserves_intent_and_later_files(targets, tmp_path, monkeypatch):
    observed = records(targets)
    actual = Path.unlink

    def fail_second(self, *args, **kwargs):
        if str(self) == targets[1][0]:
            raise PermissionError("fixture permission failure")
        return actual(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_second)
    journal_path = tmp_path / "journal"
    with journal_path.open("x") as journal:
        with pytest.raises(PermissionError):
            retire.unlink_recorded(observed, journal)
    events = [json.loads(line) for line in journal_path.read_text().splitlines()]
    assert [e["event"] for e in events] == ["UNLINK_INTENT", "UNLINK_CONFIRMED", "UNLINK_INTENT"]
    assert not Path(targets[0][0]).exists()
    assert all(Path(t[0]).exists() for t in targets[1:])


def test_exclusive_receipts_and_output_directory(tmp_path):
    out = tmp_path.resolve() / "exclusive"
    retire.output_directory(out)
    with pytest.raises(FileExistsError):
        retire.output_directory(out)
    retire.write_new(out / "receipt", {"original": True})
    with pytest.raises(FileExistsError):
        retire.write_new(out / "receipt", {"original": False})
    assert retire.read_json(out / "receipt") == {"original": True}
    link = tmp_path.resolve() / "alias"
    link.symlink_to(out, target_is_directory=True)
    with pytest.raises(ValueError, match="ancestor"):
        retire.output_directory(link / "new")
    with pytest.raises(ValueError, match="external"):
        retire.output_directory(retire.ROOT / "disallowed-output")


@pytest.mark.parametrize("content", ['{"a":1,"a":2}', '{"a":NaN}', '{"a":1e309}'])
def test_ambiguous_json_rejected(tmp_path, content):
    path = tmp_path / "invalid.json"
    path.write_text(content)
    with pytest.raises(ValueError):
        retire.read_json(path)


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path.resolve() / "ledger"
    path.mkdir()
    retire.write_new(path / "PLAN.json", retire.plan())
    retire.write_new(
        path / "INVENTORY.json",
        {
            "schema": "v16-retirement-inventory-v1",
            "deletion_performed": False,
            "plan_sha256": hashlib.sha256((path / "PLAN.json").read_bytes()).hexdigest(),
        },
    )
    commit = "a" * 40

    def fake_git(*args):
        if args == ("rev-parse", "HEAD"):
            return (commit + "\n").encode()
        if args == ("remote", "get-url", "origin"):
            return (retire.REMOTE + "\n").encode()
        if args == ("ls-remote", "--exit-code", "origin", f"refs/heads/{retire.BRANCH}"):
            return f"{commit}\trefs/heads/{retire.BRANCH}\n".encode()
        assert args[0] == "show"
        name = args[1].split(":", 1)[1]
        if name.startswith(retire.PUBLICATION + "/"):
            return (path / Path(name).name).read_bytes()
        return (retire.ROOT / name).read_bytes()

    monkeypatch.setattr(retire, "git", fake_git)
    return path, commit, fake_git


def test_publication_exact_commit_source_evidence_and_ledger(ledger):
    path, commit, _ = ledger
    _, receipt = retire.published_ledger(path, commit)
    assert receipt["commit"] == commit and receipt["remote"] == retire.REMOTE


@pytest.mark.parametrize(
    "changed", ["commit", "origin", "branch", "source", "evidence", "plan", "inventory"]
)
def test_publication_mismatch_blocks(ledger, monkeypatch, changed):
    path, commit, original = ledger

    def fake_git(*args):
        if (
            changed == "commit"
            and args[0] == "rev-parse"
            or changed == "origin"
            and args[0] == "remote"
            or changed == "branch"
            and args[0] == "ls-remote"
            or changed == "source"
            and args == ("show", f"{commit}:{retire.ENTRY}")
            or changed == "evidence"
            and args == ("show", f"{commit}:{retire.EVIDENCE[0]}")
            or changed == "plan"
            and args == ("show", f"{commit}:{retire.PUBLICATION}/PLAN.json")
            or changed == "inventory"
            and args == ("show", f"{commit}:{retire.PUBLICATION}/INVENTORY.json")
        ):
            return b"unexpected bytes"
        return original(*args)

    monkeypatch.setattr(retire, "git", fake_git)
    with pytest.raises(ValueError):
        retire.published_ledger(path, commit)


def test_delete_preflight_failure_records_terminal_no_unlink(tmp_path, monkeypatch):
    observed = {"protected": {}, "weights": []}
    monkeypatch.setattr(retire, "published_ledger", lambda *_: (observed, {}))
    monkeypatch.setattr(retire, "protected_state", lambda: {})

    def fail(*_args):
        raise ValueError("preflight failed")

    monkeypatch.setattr(retire, "preflight", fail)
    monkeypatch.setattr(retire, "unlink_recorded", lambda *_: pytest.fail("must not unlink"))
    out = tmp_path.resolve() / "attempt"
    with pytest.raises(ValueError, match="preflight failed"):
        retire.delete(tmp_path, out, "a" * 40)
    terminal = retire.read_json(out / "DELETE_FINISHED.json")
    assert terminal["status"] == "FAILED_OR_PARTIAL_NO_RETRY"
    assert not (out / "DELETIONS.jsonl").exists()
    with pytest.raises(FileExistsError):
        retire.delete(tmp_path, out, "a" * 40)


def test_available_space_and_allocations_are_observations(targets):
    observed = records(targets)
    assert all(r["stat"]["allocated_blocks_512"] >= 0 for r in observed)
    spaces = retire.available_space([t[0] for t in targets])
    assert len(spaces) == 1
    assert all(item["available_bytes"] >= 0 for item in spaces.values())


def proc_fixture(tmp_path, command=b"unrelated\0"):
    proc = tmp_path.resolve() / "proc"
    process = proc / "99999999"
    (process / "fd").mkdir(parents=True)
    (process / "cmdline").write_bytes(command)
    (process / "comm").write_text("unrelated")
    return proc, process


@pytest.mark.parametrize("active", ["handle", "target_command", "run_command"])
def test_visible_process_target_use_blocks(targets, tmp_path, active):
    proc, process = proc_fixture(tmp_path)
    if active == "handle":
        (process / "fd" / "3").symlink_to(targets[0][0])
    else:
        marker = (
            targets[0][0] if active == "target_command" else str(Path(targets[0][0]).parent.parent)
        )
        (process / "cmdline").write_bytes(f"python\0--input\0{marker}".encode())
    with pytest.raises(ValueError, match="Visible"):
        retire.screen_processes([t[0] for t in targets], proc)


def test_unrelated_process_is_not_changed(targets, tmp_path):
    proc, process = proc_fixture(tmp_path)
    assert retire.screen_processes([t[0] for t in targets], proc) == []
    assert (process / "cmdline").read_bytes() == b"unrelated\0"


@pytest.mark.parametrize("comm", ["systemd", "worker"])
def test_unreadable_service_is_unknown_nonservice_blocks(targets, tmp_path, monkeypatch, comm):
    proc, process = proc_fixture(tmp_path)
    (process / "comm").write_text(comm)
    actual = Path.iterdir

    def denied(self):
        if self == process / "fd":
            raise PermissionError("fixture denied")
        return actual(self)

    monkeypatch.setattr(Path, "iterdir", denied)
    if comm == "worker":
        with pytest.raises(ValueError, match="Unreadable non-service"):
            retire.screen_processes([t[0] for t in targets], proc)
    else:
        result = retire.screen_processes([t[0] for t in targets], proc)
        assert result == [{"pid": 99999999, "comm": "systemd", "target_handles": "UNKNOWN"}]


@pytest.mark.parametrize(
    ("code", "stdout", "stderr", "allowed"),
    [
        (1, "", "", True),
        (0, "p123\nnweight", "", False),
        (1, "", "warning", False),
        (2, "", "", False),
    ],
)
def test_lsof_unknown_and_open_handles_block(monkeypatch, code, stdout, stderr, allowed):
    actual = Path.is_dir
    monkeypatch.setattr(Path, "is_dir", lambda path: True if str(path) == "/proc" else actual(path))
    monkeypatch.setattr(retire.shutil, "which", lambda _: "/usr/bin/lsof")
    monkeypatch.setattr(
        retire.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr),
    )
    monkeypatch.setattr(retire, "screen_processes", lambda *_: [])
    if allowed:
        assert retire.visible_handles(["/unexecuted/fixture"])["visible_open_targets"] == []
    else:
        with pytest.raises(ValueError, match="lsof"):
            retire.visible_handles(["/unexecuted/fixture"])


def test_plan_tampering_rejected_even_with_matching_git(ledger):
    path, commit, _ = ledger
    changed = copy.deepcopy(retire.plan())
    changed["targets"][0]["path"] += "-other"
    (path / "PLAN.json").write_bytes(retire.encode(changed))
    with pytest.raises(ValueError, match="fixed retirement scope"):
        retire.published_ledger(path, commit)
