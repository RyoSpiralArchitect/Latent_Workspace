"""Small actual owner parity on the qualified device; no skip on CUDA."""

import copy
import sys
from pathlib import Path

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_v22_full_ft as run  # noqa: E402
from test_native_owner import setup  # noqa: E402
from test_v22_full_ft import no_guard, tiny_rows  # noqa: E402

from latent_workspace.cuda_cache import release_unused_cache  # noqa: E402
from latent_workspace.native_owner import NativeFullUpdateOwner  # noqa: E402
from latent_workspace.optimizer_state import tree_hash  # noqa: E402


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("training", [False, True])
def test_cache_boundary_preserves_exact_long_update_and_cpu_gradient_hashes(
    tmp_path, dtype, training
):
    owner, _ = setup(dtype=dtype)
    original, payload = copy.deepcopy(owner.graph), owner.payload()
    rows = tiny_rows()
    keys = [r["key"] for r in rows]
    reference, treated = tmp_path / "reference", tmp_path / "treated"
    reference.mkdir()
    treated.mkdir()
    expected = run.common.update(owner, rows, keys, no_guard, reference, 1)
    restored = NativeFullUpdateOwner.restore(
        original,
        payload,
        config=owner.config,
        expected_run_contract=owner.run_contract,
        expected_state_sha256=tree_hash(payload),
    )
    before = run.common.fingerprint(restored)
    release_unused_cache(restored, "restore")
    run.common.exact(before, run.common.fingerprint(restored), "cache restore state")
    events = []

    def release(current, kind, output):
        grads = tree_hash(current.window._buffers)
        fingerprint = run.common.fingerprint(current)
        native_ids = [(id(p), p.data_ptr(), p._version) for _, p in current.named]
        receipt = release_unused_cache(current, kind)
        assert native_ids == [(id(p), p.data_ptr(), p._version) for _, p in current.named]
        assert grads == tree_hash(current.window._buffers)
        run.common.exact(fingerprint, run.common.fingerprint(current), "cache spill state")
        events.append(receipt)

    update = run.train_update if training else run.common.update
    actual = update(restored, rows, keys, no_guard, treated, 1, after_spill=release)
    if training:
        for row in expected["rows"]:
            row.pop("accumulated_gradient_sha256")
    run.common.exact(expected, actual, "cache/plain exact update")
    assert tree_hash(owner.payload()) == tree_hash(restored.payload())
    assert len(events) == 4
    if next(restored.model.parameters()).is_cuda:
        assert all(r["action"] == "SYNCHRONIZE_EMPTY_CACHE" for r in events)
        assert all(r["before"]["allocated_bytes"] == r["after"]["allocated_bytes"] for r in events)
        assert any(r["before"]["reserved_bytes"] > r["after"]["reserved_bytes"] for r in events)
    else:
        assert all(r["action"] == "CPU_NOOP" for r in events)


@pytest.mark.parametrize(
    "fault",
    [
        "unknown",
        "no_spill",
        "active_restore",
        "native_grad",
        "master_grad",
        "failed",
        "missing_buffer",
        "spill_count",
    ],
)
def test_invalid_cache_boundary_fails_before_cuda_call(monkeypatch, fault):
    owner, batch = setup()
    kind = "spill"
    if fault == "unknown":
        kind = "step"
    elif fault != "no_spill":
        owner.begin_window([("a", 3)])
        owner.accumulate("a", {k: v[:1] for k, v in batch.items()})
    if fault == "active_restore":
        kind = "restore"
    elif fault == "native_grad":
        next(owner.model.parameters()).grad = torch.zeros_like(next(owner.model.parameters()))
    elif fault == "master_grad":
        p = next(iter(owner.masters.values()))
        p.grad = torch.zeros_like(p)
    elif fault == "failed":
        owner.failed = True
    elif fault == "missing_buffer":
        owner.window._buffers.pop(next(iter(owner.window._buffers)))
    elif fault == "spill_count":
        owner.window._spill_count += 1

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid boundary touched CUDA")

    monkeypatch.setattr(torch.cuda, "synchronize", forbidden)
    monkeypatch.setattr(torch.cuda, "empty_cache", forbidden)
    with pytest.raises(ValueError):
        release_unused_cache(owner, kind)


def test_cpu_boundary_never_initializes_cuda(monkeypatch):
    monkeypatch.setenv("LTWS_TEST_DEVICE", "cpu")
    owner, _ = setup()

    def forbidden(*args, **kwargs):
        raise AssertionError("CPU invoked CUDA")

    for name in ("synchronize", "empty_cache", "device", "mem_get_info"):
        monkeypatch.setattr(torch.cuda, name, forbidden)
    assert release_unused_cache(owner, "restore")["action"] == "CPU_NOOP"


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_actual_restore_hook_preserves_saved_payload_then_replays_exactly(tmp_path, dtype):
    from types import SimpleNamespace

    from run_v22_full_ft_recovery01 import boundary

    owner, _ = setup(dtype=dtype)
    original = copy.deepcopy(owner.graph)
    rows = tiny_rows()
    first, repeated, weights = (tmp_path / name for name in ("first", "repeat", "weights"))
    for path in (first, repeated, weights):
        path.mkdir()
    core = SimpleNamespace(snapshot_admission=lambda *args: None)
    plan = dict(checkpoint_names=["canary_step1.pt"], checkpoint_max_bytes=2**20)
    args = SimpleNamespace(output=first, checkpoints=weights)
    run.common.update(
        owner, rows, ["instruction", "memory"], no_guard, first, 1, after_spill=boundary
    )
    run.checkpoint(owner, core, args, plan, no_guard, "canary_step1.pt")
    expected = run.common.update(
        owner, rows, ["code", "prose"], no_guard, first, 2, after_spill=boundary
    )
    args.output = repeated
    restored = run.restore(
        original,
        owner.config,
        owner.run_contract,
        core,
        args,
        plan,
        no_guard,
        first,
        "canary_step1.pt",
        after_restore=boundary,
    )
    assert (repeated / "CACHE_restore.json").is_file()
    actual = run.common.update(
        restored, rows, ["code", "prose"], no_guard, repeated, 2, after_spill=boundary
    )
    run.common.exact(expected, actual, "cache-policy fresh restore replay")
    assert tree_hash(owner.payload()) == tree_hash(restored.payload())
