"""No real GPU queries: strict parser fixtures and independent-process sentinels."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import qualification_isolation as v1  # noqa: E402
import qualification_isolation_v2 as isolation  # noqa: E402
import qualification_observer as observer  # noqa: E402


def runner(ps="42 1\n43 42\n44 43\n99 1\n", gpu="44\n99\n", code=0, stderr=""):
    def output(command, **kwargs):
        assert kwargs == dict(capture_output=True, text=True, timeout=10, check=False)
        return SimpleNamespace(
            returncode=code, stdout=ps if command[0] == "ps" else gpu, stderr=stderr
        )

    return output


def test_transitive_process_tree_and_foreign_gpu_separation():
    assert observer.snapshot(42, runner()) == dict(
        pid=42, descendants=[42, 43, 44], gpu_clients=[44, 99], own_gpu_clients=[44]
    )


def test_empty_gpu_output_is_valid_not_a_parse_error():
    assert observer.snapshot(42, runner(gpu="\n"))["gpu_clients"] == []


@pytest.mark.parametrize(
    "bad", ["PID PPID\n", "42 1 extra\n", "42 nope\n", "42 1\n42 2\n", "99 1\n"]
)
def test_ps_invalidity_retains_stage_command_message_and_raw_output(bad):
    with pytest.raises(observer.ObservationError) as caught:
        observer.snapshot(42, runner(ps=bad))
    details = caught.value.details
    assert details["stage"] == "processes.parse"
    assert details["command"] == ["ps", "-eo", "pid=,ppid="]
    assert details["stdout"]["text"] == bad and details["error_type"] == "ValueError"
    assert details["message"]


@pytest.mark.parametrize("bad", ["N/A", "No running processes found", "-3", "0", "3.5", "４２"])
def test_unknown_nvidia_output_is_not_converted_to_no_clients(bad):
    with pytest.raises(observer.ObservationError) as caught:
        observer.snapshot(42, runner(gpu=bad))
    assert caught.value.details["stage"] == "gpu_clients.parse"
    assert caught.value.details["stdout"]["text"] == bad


def test_command_failure_captures_stderr_exit_and_stdout():
    with pytest.raises(observer.ObservationError) as caught:
        observer.snapshot(42, runner(code=3, stderr="diagnostic"))
    assert caught.value.details["returncode"] == 3
    assert caught.value.details["stage"] == "processes.exit"
    assert caught.value.details["stderr"]["text"] == "diagnostic"


def test_timeout_is_recorded_not_retried():
    calls = []

    def timeout(command, **kwargs):
        calls.append(command)
        raise subprocess.TimeoutExpired(command, 10, output=b"partial", stderr=b"late")

    with pytest.raises(observer.ObservationError) as caught:
        observer.snapshot(42, timeout)
    assert len(calls) == 1
    assert caught.value.details["error_type"] == "TimeoutExpired"
    assert caught.value.details["stdout"]["text"] == "partial"


def test_large_diagnostic_is_bounded_and_fully_hashed():
    raw = "x" * 9000
    value = observer.captured(raw)
    assert value["text"] == "x" * 4096 and value["characters"] == 9000
    assert value["sha256"] == hashlib.sha256(raw.encode()).hexdigest()


def fake_commands(tmp_path, monkeypatch, gpu=""):
    commands = tmp_path / "bin"
    commands.mkdir()
    for name, output in (("ps", f"{os.getpid()} 1\n"), ("nvidia-smi", gpu)):
        path = commands / name
        path.write_text(f"#!{sys.executable}\nimport sys\nsys.stdout.write({output!r})\n")
        path.chmod(0o700)
    monkeypatch.setenv("PATH", str(commands))


def completed_worker(tmp_path, monkeypatch):
    fake_commands(tmp_path, monkeypatch)
    journal = tmp_path / "observer.jsonl"
    worker = isolation.Observer(os.getpid(), journal)
    try:
        worker.ready()
        # A deliberately invalid mock in the pytest process must not reach the
        # already-running observer or its final sample.
        with monkeypatch.context() as patch:
            patch.setattr(
                subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(ValueError("mock"))
            )
            metadata, errors = worker.finish()
    finally:
        if worker.process.poll() is None:
            worker.process.kill()
            worker.process.wait()
    assert errors == []
    events = isolation.journal_events(journal)
    metadata["journal_sha256"] = hashlib.sha256(journal.read_bytes()).hexdigest()
    audit = dict(
        schema=observer.SCHEMA,
        status="CPU_GPU_ISOLATION_PASS",
        pid=os.getpid(),
        terminal_sha256="a" * 64,
        mask_before_runtime_import=True,
        final_visible_devices=0,
        final_initialized=False,
        child_probe=dict(visible_devices=0, initialized=False, cuda_init_rejected="RuntimeError"),
        samples=[e for e in events if e["kind"] == "sample"],
        monitor_errors=[],
        observer=metadata,
    )
    return audit, journal


def test_external_worker_survives_parent_test_mock_and_binds_journal(tmp_path, monkeypatch):
    audit, journal = completed_worker(tmp_path, monkeypatch)
    assert len(audit["samples"]) == 2
    assert audit["observer"]["pid"] != os.getpid()
    isolation.validate_audit(audit, "a" * 64, os.getpid(), journal)


@pytest.mark.parametrize(
    "damage",
    [
        "missing_terminal",
        "parse_error",
        "journal_hash",
        "sample",
        "returncode",
        "same_process",
        "source",
        "own_gpu",
        "time",
    ],
)
def test_incomplete_changed_or_failed_external_audit_rejected(tmp_path, monkeypatch, damage):
    audit, journal = completed_worker(tmp_path, monkeypatch)
    events = isolation.journal_events(journal)
    if damage == "missing_terminal":
        events.pop()
    elif damage == "parse_error":
        events.insert(1, dict(kind="error", stage="gpu_clients.parse"))
    elif damage == "journal_hash":
        audit["observer"]["journal_sha256"] = "b" * 64
    elif damage == "sample":
        audit["samples"] = []
    elif damage == "returncode":
        audit["observer"]["returncode"] = 1
    elif damage == "same_process":
        events[0]["observer_pid"] = audit["observer"]["pid"] = os.getpid()
    elif damage == "source":
        events[0]["source_sha256"] = "c" * 64
    elif damage == "own_gpu":
        audit["samples"][0]["own_gpu_clients"] = [os.getpid()]
    else:
        events[-1]["elapsed_seconds"] = -1
    journal.write_text("".join(json.dumps(e) + "\n" for e in events))
    if damage != "journal_hash":
        audit["observer"]["journal_sha256"] = hashlib.sha256(journal.read_bytes()).hexdigest()
    with pytest.raises((ValueError, KeyError)):
        isolation.validate_audit(audit, "a" * 64, os.getpid(), journal)


def test_external_failure_keeps_diagnostic_and_no_ready(tmp_path, monkeypatch):
    fake_commands(tmp_path, monkeypatch, gpu="unexpected")
    journal = tmp_path / "failed.jsonl"
    worker = isolation.Observer(os.getpid(), journal)
    with pytest.raises(ValueError):
        worker.ready()
    metadata, errors = worker.finish()
    assert metadata["returncode"] == 1 and errors
    events = isolation.journal_events(journal)
    assert [e["kind"] for e in events] == ["started", "error", "finished"]
    assert events[1]["stage"] == "gpu_clients.parse"
    assert events[1]["stdout"]["text"] == "unexpected"


def test_control_eof_is_failure_not_success(tmp_path, monkeypatch):
    fake_commands(tmp_path, monkeypatch)
    journal = tmp_path / "eof.jsonl"
    worker = isolation.Observer(os.getpid(), journal)
    worker.ready()
    worker.process.communicate(timeout=10)
    assert worker.process.returncode == 1
    assert isolation.journal_events(journal)[-2]["stage"] == "control"


def test_mixin_cpu_pass_and_cuda_bypass(tmp_path, monkeypatch):
    fake_commands(tmp_path, monkeypatch)
    from latent_workspace import execution as ex

    class Parent:
        def qualify(self, args):
            if args.device == "cuda":
                return 7
            args.output.mkdir()
            ex.write_new(args.output / "FINISHED.json", dict(status="fixture"))
            return 0

    class Runner(isolation.IsolatedQualificationMixin, Parent):
        pass

    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    monkeypatch.setattr(v1, "_MASKED_PID", os.getpid())
    monkeypatch.setattr(
        v1,
        "child_probe",
        lambda: dict(visible_devices=0, initialized=False, cuda_init_rejected="RuntimeError"),
    )
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(cuda=SimpleNamespace(device_count=lambda: 0, is_initialized=lambda: False)),
    )
    output = tmp_path / "qualification/cpu"
    assert Runner().qualify(SimpleNamespace(device="cpu", output=output)) == 0
    audit = ex.read(output.parent / "CPU_ISOLATION.json")
    isolation.validate_audit(
        audit,
        ex.digest(output / "FINISHED.json"),
        os.getpid(),
        output.parent / "CPU_OBSERVER.jsonl",
    )
    with pytest.raises(ValueError):
        Runner().qualify(SimpleNamespace(device="cpu", output=output))
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    assert Runner().qualify(SimpleNamespace(device="cuda")) == 7
    assert os.environ["CUDA_VISIBLE_DEVICES"] == "0"
