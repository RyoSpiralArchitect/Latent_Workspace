from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import huggingface_hub
import pytest
import torch
from safetensors.torch import save_file

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

prefetch = importlib.import_module("prefetch_v10_model")


def write_index(path: Path, shard_name: str) -> None:
    path.write_text(
        json.dumps({"weight_map": {"model.weight": shard_name}}),
        encoding="utf-8",
    )


def test_safetensors_layout_accepts_snapshot_symlink_to_blob(tmp_path: Path) -> None:
    blob = tmp_path / "blobs" / "weight-blob"
    blob.parent.mkdir()
    save_file({"model.weight": torch.arange(6).reshape(2, 3)}, str(blob))

    snapshot = tmp_path / "snapshots" / "revision"
    snapshot.mkdir(parents=True)
    shard = snapshot / "model-00001-of-00001.safetensors"
    shard.symlink_to(blob)
    write_index(snapshot / "model.safetensors.index.json", shard.name)

    layout = prefetch.inspect_safetensors_layout(snapshot)

    assert layout["weight_file_count"] == 1
    assert layout["indexed_weight_files"] == [shard.name]
    assert layout["standalone_weight_files"] == []
    assert layout["weight_bytes"] == blob.stat().st_size


def test_safetensors_layout_rejects_parent_traversal(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    save_file(
        {"model.weight": torch.ones(1)},
        str(snapshot / "model-00001-of-00001.safetensors"),
    )
    write_index(snapshot / "model.safetensors.index.json", "../outside.safetensors")

    with pytest.raises(prefetch.PrefetchError, match="Unsafe snapshot-relative path"):
        prefetch.inspect_safetensors_layout(snapshot)


def test_cached_snapshot_resolution_reuses_prefetch_allow_patterns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, object] = {}

    def fake_snapshot_download(**kwargs: object) -> str:
        observed.update(kwargs)
        return str(tmp_path)

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot_download)

    resolved = prefetch._resolve_cached_snapshot(
        prefetch.DEFAULT_MODEL,
        prefetch.DEFAULT_REVISION,
        cache_dir=tmp_path / "cache",
    )

    assert resolved == tmp_path.resolve()
    assert observed["local_files_only"] is True
    assert observed["allow_patterns"] == list(prefetch.SNAPSHOT_ALLOW_PATTERNS)
