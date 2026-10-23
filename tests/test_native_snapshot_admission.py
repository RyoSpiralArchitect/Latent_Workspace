"""Operation-aware accounting and unchanged tiny owner update/save/replay."""

import copy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import native_snapshot_admission as io  # noqa: E402
import run_v22_full_ft as old  # noqa: E402


def fixture(available=200 * io.ex.GIB):
    plan = dict(
        snapshot_host_extra_bytes=32 * io.ex.GIB,
        resources=dict(host_abort_available_gib=24, disk_free_gib=50),
        checkpoint_names=["canary.pt"],
        checkpoint_max_bytes=28 * io.ex.GIB,
    )
    core = SimpleNamespace(
        legacy=SimpleNamespace(backward=SimpleNamespace(host_available=lambda: available))
    )
    return core, plan


@pytest.mark.parametrize("operation,forecast", list(io.OPERATIONS.items()))
def test_independent_host_and_operation_disk_accounting(operation, forecast):
    core, plan = fixture()
    events = []
    io.admit(core, plan, lambda *a, **kw: events.append((a, kw)), operation=operation)
    assert events == [((f"before_snapshot:{operation}",), dict(forecast_bytes=forecast))]


@pytest.mark.parametrize("operation", list(io.OPERATIONS))
def test_host_snapshot_reserve_is_not_relaxed(operation):
    core, plan = fixture(56 * io.ex.GIB - 1)
    events = []
    with pytest.raises(ValueError, match="independent snapshot host"):
        io.admit(core, plan, lambda *a, **kw: events.append(a), operation=operation)
    assert events == []


@pytest.mark.parametrize("operation", ["checkpoint_read", "payload_hash"])
def test_ft03_free_space_is_sufficient_for_no_new_tensor_file(operation):
    core, plan = fixture()

    def guard(phase, forecast_bytes):
        io.ex.require(76828856320 - forecast_bytes >= 50 * io.ex.GIB, "Forecast disk envelope")

    io.admit(core, plan, guard, operation=operation)
    with pytest.raises(ValueError, match="Forecast disk envelope"):
        io.admit(core, plan, guard, operation="checkpoint_write")


@pytest.mark.parametrize("operation", list(io.OPERATIONS))
def test_disk_floor_still_rejects_every_operation(operation):
    core, plan = fixture()

    def guard(phase, forecast_bytes):
        io.ex.require(50 * io.ex.GIB - 1 - forecast_bytes >= 50 * io.ex.GIB, "disk floor")

    with pytest.raises(ValueError, match="disk floor"):
        io.admit(core, plan, guard, operation=operation)


def test_unknown_operation_never_queries_resources():
    with pytest.raises(ValueError, match="Explicit snapshot"):
        io.admit(None, {}, None, operation="automatic")


@pytest.mark.parametrize("count,gib", [(0, 0), (1, 32), (2, 60)])
def test_future_write_forecast_includes_last_real_write_reserve(count, gib):
    assert io.future_write_bytes(28 * io.ex.GIB, count) == gib * io.ex.GIB


@pytest.mark.parametrize(
    "size,count",
    [
        (0, 1),
        (33 * io.ex.GIB, 1),
        (28 * io.ex.GIB, -1),
        (28 * io.ex.GIB, True),
        (28 * io.ex.GIB, 1.0),
    ],
)
def test_bad_forecast_rejected(size, count):
    with pytest.raises(ValueError):
        io.future_write_bytes(size, count)


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_save_read_payload_and_next_update_exact_against_legacy(tmp_path, dtype):
    from test_native_owner import setup

    owner, _ = setup(dtype=dtype)
    original = copy.deepcopy(owner.graph)
    core, plan = fixture()
    # Legacy body uses this same reserve for every operation. The new helper
    # must keep the complete numerical/serialization result, not that mistake.
    core.snapshot_admission = lambda p, g, full: io.admit(core, p, g, operation="checkpoint_write")
    paths = {name: tmp_path / name for name in ("old", "new", "next", "replay")}
    for path in paths.values():
        path.mkdir()
    rows = [
        dict(
            key="row",
            split="train",
            role="world",
            mode="affected",
            input_ids=[3, 4, 5, 6, 7, 8],
            labels=[-100, -100, 5, 6, 7, 8],
            memory_ids=[9, 10],
            supervised_tokens=4,
        )
    ]
    events = []

    def guard(phase, **kw):
        events.append((phase, kw))

    old.common.update(owner, rows, ["row"], guard, paths["old"], 1)
    args_old = SimpleNamespace(output=paths["old"], checkpoints=paths["old"])
    args_new = SimpleNamespace(output=paths["new"], checkpoints=paths["new"])
    legacy = old.checkpoint(owner, core, args_old, plan, guard, "canary.pt")
    saved = io.checkpoint(owner, core, args_new, plan, guard, "canary.pt")
    assert legacy["state_sha256"] == saved["state_sha256"]
    expected = old.common.update(owner, rows, ["row"], guard, paths["next"], 2)
    expected_payload = io.payload_sha(owner, core, plan, guard)
    args = SimpleNamespace(output=paths["replay"], checkpoints=paths["new"])
    restored = io.restore(
        original,
        owner.config,
        owner.run_contract,
        core,
        args,
        plan,
        guard,
        paths["new"],
        "canary.pt",
    )
    actual = old.common.update(restored, rows, ["row"], guard, paths["replay"], 2)
    old.common.exact(actual, expected, "exact rows, gradients and full owner state")
    assert io.payload_sha(restored, core, plan, guard) == expected_payload
    assert [p.name for p in paths["replay"].glob("*.pt")] == []
    assert ("before_snapshot:checkpoint_read", dict(forecast_bytes=0)) in events


def test_payload_not_materialized_when_host_admission_fails():
    core, plan = fixture(0)
    with pytest.raises(ValueError, match="independent snapshot"):
        io.payload_sha(None, core, plan, None)
