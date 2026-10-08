from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import torch
from safetensors.torch import save_file

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import audit_v14_base_identity as identity  # noqa: E402


def _model(path: Path, values: dict[str, torch.Tensor]) -> Path:
    path.mkdir()
    save_file(values, path / "model.safetensors")
    (path / "model.safetensors.index.json").write_text(
        json.dumps(
            {
                "weight_map": {key: "model.safetensors" for key in values},
            }
        )
    )
    return path


def test_cpu_exact_comparison_counts_equal_and_changed(tmp_path: Path) -> None:
    left = _model(tmp_path / "left", {"a": torch.ones(3), "b": torch.zeros(2)})
    right = _model(tmp_path / "right", {"a": torch.ones(3), "b": torch.ones(2)})
    result = identity.compare_tensors(left, right)
    assert result["equal_tensor_keys"] == ["a"]
    assert result["changed_tensor_keys"] == ["b"]
    assert result["scalar_count"] == 5
    assert not result["all_tensors_equal"]


def test_dtype_mismatch_cannot_be_silently_cast(tmp_path: Path) -> None:
    left = _model(tmp_path / "left", {"a": torch.ones(3)})
    right = _model(tmp_path / "right", {"a": torch.ones(3, dtype=torch.bfloat16)})
    with pytest.raises(identity.IdentityAuditError, match="geometry/dtype"):
        identity.compare_tensors(left, right)


def test_key_mismatch_fails_closed(tmp_path: Path) -> None:
    left = _model(tmp_path / "left", {"a": torch.ones(3)})
    right = _model(tmp_path / "right", {"b": torch.ones(3)})
    with pytest.raises(identity.IdentityAuditError, match="key sets"):
        identity.compare_tensors(left, right)


def test_output_never_overwrites_existing_receipt(tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    identity.write_fresh(path, {"original": True})
    with pytest.raises(FileExistsError):
        identity.write_fresh(path, {"original": False})
    assert json.loads(path.read_text()) == {"original": True}


def test_historical_sources_remain_pinned() -> None:
    for relative, expected in identity.FROZEN_SOURCES.items():
        assert identity.digest(identity.REPO / relative) == expected
