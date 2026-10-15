from __future__ import annotations

import hashlib
import importlib
import math
import sys
from pathlib import Path

import pytest
import torch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
analysis = importlib.import_module("analyze_v13_boundaries")


def test_boundary_relative_norm_and_zero_denominator() -> None:
    before = torch.tensor([[1.0, 2.0]])
    after = torch.tensor([[1.0, 0.0]])
    report = analysis.boundary_stats(before, after)
    assert report["relative_l2"] == pytest.approx(2 / math.sqrt(5))
    assert report["changed_elements"] == 1
    assert report["changed_rows"] == 1
    zero = analysis.boundary_stats(torch.zeros(1, 2), torch.ones(1, 2))
    assert zero["relative_l2"] is None
    assert zero["relative_l2_defined"] is False


def test_roundtrip_distinguishes_erasure_from_small_error() -> None:
    query = torch.tensor([[20.0, 19.0]], dtype=torch.bfloat16)
    update = torch.tensor([[0.01, -0.01]], dtype=torch.bfloat16)
    returned = query + update
    recovered = returned - query
    report = analysis.roundtrip_summary(update, recovered, query, returned)
    assert report["relative_l2"] == pytest.approx(1.0)
    assert report["erased_fraction_among_nonzero"] == 1.0
    assert report["fully_erased_query_rows"] == 1
    assert report["actual_return_minus_query_numeric_exact"]
    assert report["mean_cosine"] is None


def test_payload_hash_checked_before_deserialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = tmp_path / "invalid.pt"
    payload.write_bytes(b"not a valid tensor payload")
    called = False

    def forbidden_load(*_args: object, **_kwargs: object) -> None:
        nonlocal called
        called = True
        raise AssertionError("must not deserialize a hash mismatch")

    monkeypatch.setattr(torch, "load", forbidden_load)
    with pytest.raises(analysis.BoundaryError, match="SHA-256 mismatch"):
        analysis.checked_payload(payload, "0" * 64)
    assert not called


def test_checked_payload_uses_cpu_weights_only(tmp_path: Path) -> None:
    payload = tmp_path / "valid.pt"
    torch.save(
        {
            "tensors": {"adapter.candidates_precast": torch.ones(1, 2)},
            "direct_base": torch.zeros(1, 2),
        },
        payload,
    )
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    result = analysis.checked_payload(payload, digest)
    assert result["direct_base"].device.type == "cpu"
    assert torch.equal(result["tensors"]["adapter.candidates_precast"], torch.ones(1, 2))
