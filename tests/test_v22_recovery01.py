"""Recovery phase/source gates; no real-model, deletion or network work."""

import argparse
import copy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_v22_full_ft_recovery01 as run  # noqa: E402

ex = run.ex


def test_frozen_recovery_keeps_resource_numerics_and_does_not_delete():
    plan = ex.read(run.ROOT / run.PLAN)
    run.validate(plan)
    old = ex.read(run.ROOT / run.prior.PLAN)
    assert plan["resources"] == old["resources"]
    assert plan["storage_forecast_bytes"] == 28 * 2**30
    assert plan["checkpoint_names"] == old["checkpoint_names"]
    assert plan["weight_deletions"] == 0
    assert plan["data_manifest_sha256"] == old["data_manifest_sha256"]


@pytest.mark.parametrize("fault", ["seed", "resources", "optimizer", "data_manifest_sha256"])
def test_recovery_plan_drift_is_rejected(fault):
    plan = ex.read(run.ROOT / run.PLAN)
    plan[fault] = None
    with pytest.raises(ValueError, match="Frozen"):
        run.validate(plan)


@pytest.mark.parametrize("fault", [None, "phase_status", "source", "role_bytes", "exact"])
def test_training_requires_sealed_successful_checks_and_exact_replay(tmp_path, fault):
    seal, plan = {"source_commit": "1" * 40}, {"x": 1}
    phase, raw = tmp_path / "checks", tmp_path / "raw"
    phase.mkdir()
    for role in ("canary", "replay"):
        path = raw / role
        path.mkdir(parents=True)
        ex.write_new(path / "STARTED.json", dict(seal=seal))
        if role == "replay":
            ex.write_new(path / "REPLAY.json", dict(exact=fault != "exact"))
        ex.write_new(
            path / "FINISHED.json", dict(files=ex.manifest(path), status=run.prior.STATUSES[role])
        )
    ex.write_new(phase / "STARTED.json", dict(seal={} if fault == "source" else seal, plan=plan))
    ex.write_new(
        phase / "FINISHED.json",
        dict(
            files=ex.manifest(phase),
            status=ex.INCOMPLETE if fault == "phase_status" else run.CHECKS_PASS,
            completed_roles=["canary", "replay"],
            role_manifests={r: ex.manifest(raw / r) for r in ("canary", "replay")},
        ),
    )
    if fault == "role_bytes":
        (raw / "canary" / "extra.json").write_text("{}")
    if fault is None:
        run.check_phase_gate(phase, seal, plan)
    else:
        with pytest.raises(ValueError):
            run.check_phase_gate(phase, seal, plan)


@pytest.mark.parametrize("failed_role", [None, "canary", "replay"])
def test_two_phase_controller_is_exclusive_and_stops_without_retry(
    tmp_path, monkeypatch, failed_role
):
    seal, plan = {"source_commit": "1" * 40}, {"pass_status": "ALL_PASS"}
    source = SimpleNamespace(verify=lambda *a: None)
    core = SimpleNamespace(identity=lambda: seal)
    monkeypatch.setattr(run.RUN, "preflight", lambda args: (source, core, seal, {}, plan))
    monkeypatch.setattr(run.RUN, "qualification", lambda *a: {})
    seen = []
    raw = tmp_path / "raw"

    class Child:
        pid = 123

        def __init__(self, command, **kwargs):
            role = command[command.index("--role") + 1]
            self.role = role
            seen.append(role)
            folder = raw / role
            folder.mkdir()
            ex.write_new(folder / "STARTED.json", dict(seal=seal))
            if role == "replay":
                ex.write_new(folder / "REPLAY.json", dict(exact=True))
            ex.write_new(
                folder / "FINISHED.json",
                dict(
                    status=ex.INCOMPLETE if role == failed_role else run.prior.STATUSES[role],
                    files=ex.manifest(folder),
                ),
            )

        def wait(self):
            return int(self.role == failed_role)

    monkeypatch.setattr(run.subprocess, "Popen", Child)
    args = argparse.Namespace(
        output=raw,
        checkpoints=tmp_path / "checkpoints",
        seal=tmp_path / "seal",
        qualification=tmp_path / "qualification",
    )
    assert run.dispatch_phase(copy.copy(args), training=False) == int(failed_role is not None)
    assert seen == (["canary"] if failed_role == "canary" else ["canary", "replay"])
    end = ex.read(tmp_path / "checks/FINISHED.json")
    assert end["weight_deletions"] == 0
    assert end["native_weight_updates"] == (3 if failed_role is None else None)
    assert (raw / "FINISHED.json").exists() == (failed_role is not None)
    with pytest.raises(ValueError, match="Exclusive"):
        run.dispatch_phase(copy.copy(args), training=False)
    if failed_role is not None:
        with pytest.raises(ValueError):
            run.dispatch_phase(copy.copy(args), training=True)
    else:
        monkeypatch.setattr(run.prior, "summary", lambda *a: dict(native_weight_updates=35))
        assert run.dispatch_phase(copy.copy(args), training=True) == 0
        assert seen == ["canary", "replay", "train_a", "train_b"]
        assert ex.read(raw / "FINISHED.json")["native_weight_updates"] == 35
        assert ex.read(tmp_path / "training/FINISHED.json")["native_weight_updates"] == 32
        with pytest.raises(ValueError, match="Exclusive"):
            run.dispatch_phase(copy.copy(args), training=True)
