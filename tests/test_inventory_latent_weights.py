from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/inventory_latent_weights.py"
SPEC = importlib.util.spec_from_file_location("inventory_latent_weights", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    source = tmp_path / "experiments"
    source.mkdir()
    return source


def test_inventory_hashes_weights_but_copies_only_metadata(root: Path, tmp_path: Path) -> None:
    final = root / "condition" / "final"
    final.mkdir(parents=True)
    (root / "MANIFEST.json").write_text('{"kind":"test"}')
    (final / "config.json").write_text('{"steps":1}')
    (final / "COMPLETED").write_text("")
    (final / "notes.md").write_text("fixture")
    (final / "model.safetensors").write_bytes(b"not actual model weights")
    (final / "optimizer.pt").write_bytes(b"training state is not necessarily inference weights")
    (final / "ignored.py").write_text("untouched")
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }
    destination = tmp_path / "evidence"
    report = inventory.inventory_weights(root, destination)
    assert report["status"] == "COMPLETE_WITH_DECLARED_EXCLUSIONS"
    assert report["summary"]["weight_paths"] == 2
    assert report["summary"]["metadata_copied"] == 4
    assert report["deletion_performed"] is False
    assert report["retention_policy_selected"] is False
    assert report["weight_backups_created"] is False
    assert report["summary"]["reclaimable_bytes"] is None
    for entry in report["weights"]:
        assert (
            entry["sha256"]
            == hashlib.sha256((root / entry["relative_path"]).read_bytes()).hexdigest()
        )
        assert entry["source_static_during_hash"] is True
        assert entry["reconstructible_weight_backup"] is False
        assert entry["nlink"] >= 1 and entry["inode"] > 0
        assert entry["allocated_bytes"] >= 0
        assert (
            entry["closest_references"]["config"][0]["relative_path"]
            == "condition/final/config.json"
        )
        assert entry["closest_references"]["manifest"][0]["relative_path"] == "MANIFEST.json"
        assert not (destination / "metadata" / entry["relative_path"]).exists()
    for entry in report["metadata"]:
        copied = destination / entry["backup_relative_path"]
        assert copied.read_bytes() == (root / entry["relative_path"]).read_bytes()
        assert entry["sha256"] == entry["backup_sha256"]
    assert before == {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in before}
    payload = Path(report["inventory_path"]).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == report["inventory_sha256"]
    assert "NOT reconstructible backups" in report["claim_boundary"]


def test_excludes_cache_directories_without_inventorying_their_contents(
    root: Path, tmp_path: Path
) -> None:
    for name in ("cache", "model_cache", "hf", "huggingface", ".venv"):
        directory = root / name
        directory.mkdir()
        (directory / "model.bin").write_bytes(b"excluded")
    (root / "model.bin").write_bytes(b"in scope")
    report = inventory.inventory_weights(root, tmp_path / "evidence")
    assert report["summary"]["weight_paths"] == 1
    assert set(report["excluded_directories"]) == {
        "cache",
        "model_cache",
        "hf",
        "huggingface",
        ".venv",
    }


def test_symlink_files_and_directories_are_rejected_not_followed(
    root: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "model.bin").write_bytes(b"outside scope")
    (outside / "config.json").write_text("{}")
    (root / "linked-directory").symlink_to(outside, target_is_directory=True)
    (root / "linked-model.bin").symlink_to(outside / "model.bin")
    (root / "linked-config.json").symlink_to(outside / "config.json")
    report = inventory.inventory_weights(root, tmp_path / "evidence")
    assert report["status"] == "PARTIAL"
    assert len(report["rejected_paths"]) == 3
    assert not report["weights"] and not report["metadata"]
    assert (outside / "model.bin").read_bytes() == b"outside scope"


def test_large_metadata_is_explicitly_not_copied(root: Path, tmp_path: Path) -> None:
    huge = root / "metrics.jsonl"
    with huge.open("wb") as handle:
        handle.truncate(inventory.MAX_METADATA_BYTES + 1)
    report = inventory.inventory_weights(root, tmp_path / "evidence")
    assert report["summary"]["metadata_not_copied_size_limit"] == 1
    assert report["metadata"][0]["sha256"] is None
    assert report["metadata"][0]["backup_status"] == "NOT_COPIED_EXCEEDS_50_MIB"
    assert not (tmp_path / "evidence" / "metadata" / "metrics.jsonl").exists()


def test_hardlinks_have_distinct_paths_but_shared_inode_totals(root: Path, tmp_path: Path) -> None:
    first, second = root / "first.pt", root / "second.pth"
    first.write_bytes(b"12345678")
    os.link(first, second)
    report = inventory.inventory_weights(root, tmp_path / "evidence")
    assert report["summary"]["weight_paths"] == 2
    assert report["summary"]["unique_weight_inodes"] == 1
    assert report["summary"]["weight_path_logical_bytes"] == 16
    assert report["summary"]["unique_inode_logical_bytes"] == 8
    assert all(entry["nlink"] == 2 for entry in report["weights"])
    assert first.exists() and second.exists()


def test_fresh_external_output_is_required_before_source_read(root: Path, tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    for output in (existing, root / "evidence"):
        with pytest.raises(inventory.InventoryError):
            inventory.inventory_weights(root, output)
    assert not (root / "evidence").exists()
    linked = tmp_path / "linked-evidence"
    linked.symlink_to(tmp_path / "missing")
    with pytest.raises(inventory.InventoryError):
        inventory.inventory_weights(root, linked)


def test_broad_relative_and_symlink_roots_rejected(root: Path, tmp_path: Path) -> None:
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    for source in (Path("experiments"), Path("/"), Path.home(), tmp_path, alias):
        with pytest.raises(inventory.InventoryError):
            inventory.inventory_weights(source, tmp_path / "evidence")
    assert not (tmp_path / "evidence").exists()


def test_source_change_during_hash_never_gets_trusted_fingerprint(
    root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    weight = root / "model.bin"
    weight.write_bytes(b"original")
    original_read = inventory.os.read
    modified = False

    def modifying_read(fd: int, count: int) -> bytes:
        nonlocal modified
        value = original_read(fd, count)
        if not modified:
            modified = True
            weight.write_bytes(b"changed source contents")
        return value

    monkeypatch.setattr(inventory.os, "read", modifying_read)
    report = inventory.inventory_weights(root, tmp_path / "evidence")
    assert report["status"] == "PARTIAL"
    assert report["weights"][0]["sha256"] is None
    assert report["weights"][0]["source_static_during_hash"] is False
    assert report["weights"][0]["status"] == "SOURCE_CHANGED_DURING_HASH"


def test_cli_stdlib_only_and_no_deletion_option(root: Path, tmp_path: Path) -> None:
    (root / "model.bin").write_bytes(b"fixture")
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(SCRIPT),
            "--root",
            str(root),
            "--output-dir",
            str(tmp_path / "evidence"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["deletion_performed"] is False
    assert (root / "model.bin").read_bytes() == b"fixture"
    denied = subprocess.run(
        [sys.executable, "-I", "-S", str(SCRIPT), "--delete"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert denied.returncode != 0


def test_unstable_metadata_copy_is_retained_but_never_trusted(
    root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = root / "config.json"
    metadata.write_bytes(b'{"v":1}')
    original_read = inventory.os.read
    modified = False

    def modifying_read(fd: int, count: int) -> bytes:
        nonlocal modified
        value = original_read(fd, count)
        if not modified:
            modified = True
            metadata.write_bytes(b'{"v":2,"changed":true}')
        return value

    monkeypatch.setattr(inventory.os, "read", modifying_read)
    report = inventory.inventory_weights(root, tmp_path / "evidence")
    entry = report["metadata"][0]
    assert report["status"] == "PARTIAL"
    assert entry["sha256"] is None
    assert entry["backup_status"] == "UNSTABLE_COPY_RETAINED_DO_NOT_TRUST"
    assert (tmp_path / "evidence" / entry["backup_relative_path"]).exists()
    assert report["summary"]["metadata_copied"] == 0


def test_symlinked_output_parent_cannot_bypass_outside_root_requirement(
    root: Path,
    tmp_path: Path,
) -> None:
    alias = tmp_path / "root-alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(inventory.InventoryError):
        inventory.inventory_weights(root, alias / "evidence")
    assert not (root / "evidence").exists()
