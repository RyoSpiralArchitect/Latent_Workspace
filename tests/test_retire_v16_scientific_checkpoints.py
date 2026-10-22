"""Offline scope and transaction guards; no real weight/network/model calls."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import retire_v16_scientific_checkpoints as retire  # noqa: E402


def test_exact_six_scientific_targets_and_retained_evidence():
    plan = retire.plan()
    assert len(retire.TARGETS) == 6
    assert sum(size for _, size, _ in retire.TARGETS) == retire.TOTAL == 174442288712
    assert {Path(p).parent.name for p, _, _ in retire.TARGETS} == {
        "common",
        "raw_matched_control",
        "slot_contrast",
    }
    assert all(Path(p).name in {"step1.pt", "step2.pt"} for p, _, _ in retire.TARGETS)
    assert not {p for p, _, _ in retire.TARGETS} & {p for p, _ in retire.PROTECTED}
    assert len(plan["historical_evidence_sha256"]) > 500
    assert plan["old_gate"] == "FAIL"
    assert plan["winner"] == "none"
    assert plan["non_regression"] == "NOT_ESTABLISHED"
    assert plan["weights_reconstructible_from_git"] is False


def test_output_is_exclusive_and_cannot_overlap_targets(tmp_path):
    out = tmp_path.resolve() / "fresh"
    retire.output_directory(out)
    with pytest.raises(FileExistsError):
        retire.output_directory(out)
    for forbidden in (
        retire.ROOT / "new",
        retire.RUN / "new",
        retire.safe.BASE_SNAPSHOT / "new",
        Path(retire.PROTECTED[0][0]).parent / "new",
    ):
        with pytest.raises(ValueError, match="overlaps|ancestor"):
            retire.output_directory(forbidden)


@pytest.fixture
def transaction(tmp_path, monkeypatch):
    frozen = retire.plan()
    targets = []
    for index in range(6):
        p = tmp_path.resolve() / f"tiny{index}.pt"
        content = f"fixture {index}".encode()
        p.write_bytes(content)
        targets.append((str(p), len(content), hashlib.sha256(content).hexdigest()))
    observed = {
        "weights": [retire.safe.inspect_weight(*target) for target in targets],
        "protected": {"fixture": True},
        "allocated_bytes": 0,
    }
    monkeypatch.setattr(retire, "TARGETS", tuple(targets))
    monkeypatch.setattr(retire, "TOTAL", sum(t[1] for t in targets))
    monkeypatch.setattr(retire, "plan", lambda: frozen)
    monkeypatch.setattr(retire, "published_ledger", lambda *_: (observed, {"fixture": True}))
    monkeypatch.setattr(retire, "protected_state", lambda: observed["protected"])
    monkeypatch.setattr(retire.safe, "visible_handles", lambda _: {"fixture": True})
    return targets, tmp_path / "output"


def test_six_file_transaction_and_terminal_receipt(transaction):
    targets, output = transaction
    retire.delete(None, output, "a" * 40)
    receipt = retire.safe.read_json(output / "DELETE_FINISHED.json")
    assert receipt["status"] == "COMPLETE" and receipt["deleted"] == 6
    assert receipt["logical_bytes"] == sum(t[1] for t in targets)
    assert all(not Path(t[0]).exists() for t in targets)
    journal = [json.loads(line) for line in (output / "DELETIONS.jsonl").read_text().splitlines()]
    assert len(journal) == 12


@pytest.mark.parametrize("fault", ["last_hash", "publication", "protected", "handles"])
def test_preflight_failure_deletes_nothing(transaction, monkeypatch, fault):
    targets, output = transaction

    def failure(*args):
        raise ValueError(f"fixture {fault}")

    if fault == "last_hash":
        Path(targets[-1][0]).write_bytes(b"different")
    elif fault == "publication":
        monkeypatch.setattr(retire, "published_ledger", failure)
    elif fault == "protected":
        monkeypatch.setattr(retire, "protected_state", failure)
    else:
        monkeypatch.setattr(retire.safe, "visible_handles", failure)
    with pytest.raises(ValueError):
        retire.delete(None, output, "a" * 40)
    receipt = retire.safe.read_json(output / "DELETE_FINISHED.json")
    assert receipt["status"] == "FAILED_OR_PARTIAL_NO_RETRY"
    assert all(Path(t[0]).exists() for t in targets)
    assert not (output / "DELETIONS.jsonl").exists()


def test_partial_unlink_is_recorded_and_not_retried(transaction, monkeypatch):
    targets, output = transaction
    real_unlink = Path.unlink

    def fail_second(self, *args, **kwargs):
        if str(self) == targets[1][0]:
            raise PermissionError("fixture failure")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_second)
    with pytest.raises(PermissionError):
        retire.delete(None, output, "a" * 40)
    assert not Path(targets[0][0]).exists()
    assert all(Path(t[0]).exists() for t in targets[1:])
    receipt = retire.safe.read_json(output / "DELETE_FINISHED.json")
    assert receipt["status"] == "FAILED_OR_PARTIAL_NO_RETRY"
    with pytest.raises(FileExistsError):
        retire.delete(None, output, "a" * 40)


@pytest.mark.parametrize("fault", ["head", "remote", "unpublished", "dirty", "source", "ledger"])
def test_publication_mismatch_rejected(tmp_path, monkeypatch, fault):
    commit = "a" * 40
    ref = f"refs/heads/{retire.BRANCH}"

    def fake_git(*args):
        if args == ("rev-parse", "HEAD"):
            return ((("b" * 40) if fault == "head" else commit) + "\n").encode()
        if args == ("status", "--porcelain"):
            return b" M changed" if fault == "dirty" else b""
        if args == ("remote", "get-url", "origin"):
            return b"wrong" if fault == "remote" else retire.safe.REMOTE.encode()
        if args == ("ls-remote", "--exit-code", "origin", ref):
            return b"wrong" if fault == "unpublished" else f"{commit}\t{ref}".encode()
        if args[0] == "show":
            name = args[1].split(":", 1)[1]
            return b"wrong" if fault == "source" else (retire.ROOT / name).read_bytes()
        raise AssertionError(args)

    frozen = retire.plan()
    monkeypatch.setattr(retire, "plan", lambda: frozen)
    monkeypatch.setattr(retire.safe, "git", fake_git)
    # Missing published ledger is a rejection, never permission to dispatch.
    with pytest.raises((ValueError, FileNotFoundError)):
        retire.published_ledger(tmp_path, commit)
