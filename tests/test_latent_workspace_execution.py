"""The engine's sealed-execution skeleton, exercised in-process with stubbed sources."""

import json
import sys
from argparse import Namespace
from types import SimpleNamespace

import pytest

from latent_workspace import execution as ex

SEAL = {"source_commit": "0" * 40, "source_hashes": {}}
PLAN = {
    "qualification_cases": 2,
    "resources": {"max_elapsed_seconds": 60},
    "pass_status": "DONE",
    **ex.CEILING,
}


def stub_core():
    return SimpleNamespace(identity=lambda: SEAL, verify_imports=lambda seal: {"stub": True})


class StubRun(ex.SealedRun):
    """Skips the isolated-launcher check; everything after it is the real skeleton."""

    def preflight(self, args):
        source = SimpleNamespace(verify=lambda root, seal, entry: {"checked": True})
        return source, stub_core(), SEAL, {"checked": True}, PLAN


def qualification_bundles(root, tiny_pass="TINY", tests=2):
    for device in ("cpu", "cuda"):
        bundle = root / device
        bundle.mkdir(parents=True)
        ex.write_new(bundle / "STARTED.json", dict(seal=SEAL, plan=PLAN, device=device))
        ex.write_new(
            bundle / "FINISHED.json",
            dict(
                status=tiny_pass,
                pytest_exit_code=0,
                counts=dict(tests=tests, failures=0, errors=0, skipped=0),
                files=ex.manifest(bundle),
                **ex.CEILING,
            ),
        )
    return root


def runner(tmp_path, roles=("a", "b")):
    return StubRun(
        root=tmp_path / "source",
        entry="scripts/stub.py",
        plan_path="plan.json",
        tiny_pass="TINY",
        roles=roles,
        role_status={role: f"{role.upper()}_PASS" for role in roles},
        validate=lambda plan: None,
        load=lambda name: None,
    )


def test_receipts_are_deterministic_and_never_overwrite(tmp_path):
    ex.write_gz(tmp_path / "a.json.gz", {"b": [1, 2], "a": 0.5})
    ex.write_gz(tmp_path / "b.json.gz", {"a": 0.5, "b": [1, 2]})
    assert (tmp_path / "a.json.gz").read_bytes() == (tmp_path / "b.json.gz").read_bytes()
    assert ex.read_gz(tmp_path / "a.json.gz") == {"a": 0.5, "b": [1, 2]}
    ex.write_new(tmp_path / "r.json", {"x": 1})
    with pytest.raises(FileExistsError):
        ex.write_new(tmp_path / "r.json", {"x": 2})
    listing = ex.manifest(tmp_path)
    assert set(listing) == {"a.json.gz", "b.json.gz", "r.json"}
    assert listing["r.json"]["sha256"] == ex.digest(tmp_path / "r.json")
    assert ex.plan_hash({"b": 1, "a": 2}) == ex.plan_hash({"a": 2, "b": 1})


def test_qualification_binds_both_devices_and_rejects_tampering(tmp_path):
    run = runner(tmp_path)
    bundles = qualification_bundles(tmp_path / "qualification")
    result = run.qualification(bundles, SEAL, PLAN)
    assert set(result) == {"cpu", "cuda"}
    (bundles / "cpu" / "extra.txt").write_text("tamper")
    with pytest.raises(ValueError, match="Qualification artifact bytes"):
        run.qualification(bundles, SEAL, PLAN)


def role_args(tmp_path, role):
    return Namespace(
        seal=tmp_path / "SEAL.json",
        output=tmp_path / "raw" / role,
        checkpoints=tmp_path / "checkpoints",
        qualification=qualification_bundles(tmp_path / f"q_{role}"),
        role=role,
    )


def test_a_role_writes_receipts_and_records_failure_without_retry(tmp_path):
    run = runner(tmp_path)
    (tmp_path / "raw").mkdir()
    assert run.run_role(role_args(tmp_path, "a"), lambda core, args, plan, seal: {"ok": 1}) == 0
    finished = ex.read(tmp_path / "raw" / "a" / "FINISHED.json")
    assert finished["status"] == "A_PASS" and finished["outcome"] == {"ok": 1}
    assert set(finished["files"]) == {"STARTED.json"}

    def broken(core, args, plan, seal):
        raise RuntimeError("boom")

    assert run.run_role(role_args(tmp_path, "b"), broken) == 1
    failed = ex.read(tmp_path / "raw" / "b" / "FINISHED.json")
    assert failed["status"] == ex.INCOMPLETE and "RuntimeError: boom" in failed["error"]


class ScriptedRun(StubRun):
    """Each role is a tiny subprocess that writes its own FINISHED receipt."""

    def __init__(self, *args, outcomes, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = outcomes

    def role_command(self, args, role):
        status, code = self.outcomes[role]
        script = (
            "import json, pathlib, sys; out = pathlib.Path(sys.argv[1]); out.mkdir(); "
            "(out / 'FINISHED.json').write_text(json.dumps({'status': sys.argv[2], "
            "'outcome': {'role': sys.argv[3]}})); sys.exit(int(sys.argv[4]))"
        )
        return [sys.executable, "-c", script, str(args.output / role), status, role, str(code)]


def dispatch_args(tmp_path, name):
    return Namespace(
        seal=tmp_path / "SEAL.json",
        output=tmp_path / name / "raw",
        checkpoints=tmp_path / name / "checkpoints",
        qualification=qualification_bundles(tmp_path / name / "qualification"),
    )


def test_dispatch_runs_roles_in_order_and_stops_at_the_first_failure(tmp_path):
    (tmp_path / "source").mkdir()
    ok = dict(a=("A_PASS", 0), b=("B_PASS", 0))
    run = ScriptedRun(**vars_of(runner(tmp_path)), outcomes=ok)
    summary = lambda out, plan: ex.read(out / "b" / "FINISHED.json")["outcome"]  # noqa: E731
    assert run.dispatch(dispatch_args(tmp_path, "good"), summary) == 0
    finished = ex.read(tmp_path / "good" / "raw" / "FINISHED.json")
    assert finished["status"] == "DONE" and finished["completed_roles"] == ["a", "b"]
    assert finished["summary"] == {"role": "b"}

    failing = ScriptedRun(**vars_of(runner(tmp_path)), outcomes=dict(a=("A_PASS", 3), b=ok["b"]))
    assert failing.dispatch(dispatch_args(tmp_path, "bad"), summary) == 1
    stopped = ex.read(tmp_path / "bad" / "raw" / "FINISHED.json")
    assert stopped["status"] == ex.INCOMPLETE and stopped["completed_roles"] == []
    assert "a exited 3; no later role or retry dispatched" in stopped["error"]
    assert not (tmp_path / "bad" / "raw" / "b").exists()


def vars_of(run):
    return dict(
        root=run.root,
        entry=run.entry,
        plan_path=run.plan_path,
        tiny_pass=run.tiny_pass,
        roles=run.roles,
        role_status=run.role_status,
        validate=run.validate,
        load=run.load,
    )


def test_summary_is_read_only_after_every_role_passed(tmp_path):
    (tmp_path / "source").mkdir()
    wrong = ScriptedRun(**vars_of(runner(tmp_path)), outcomes=dict(a=("A_PASS", 0), b=("NOT_B", 0)))
    calls = []
    wrong.dispatch(dispatch_args(tmp_path, "wrong"), lambda out, plan: calls.append(1))
    assert calls == []
    stopped = ex.read(tmp_path / "wrong" / "raw" / "FINISHED.json")
    assert "b receipt status NOT_B" in stopped["error"]
    assert json.loads(json.dumps(stopped["completed_roles"])) == ["a"]
