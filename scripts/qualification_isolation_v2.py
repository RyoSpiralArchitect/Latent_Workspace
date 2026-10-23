"""Additive audit recovery: separate observer process, unchanged CPU visibility.

Historical v1 code and receipts stay frozen. Every observer error, missing
terminal, timeout or changed journal still rejects qualification.
"""

from __future__ import annotations

import hashlib
import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

import qualification_isolation as v1
from qualification_observer import INTERVAL, SCHEMA, TIMEOUT

OBSERVER = Path(__file__).with_name("qualification_observer.py")


class Observer:
    def __init__(self, root_pid, journal):
        self.root_pid, self.journal = root_pid, journal
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-B",
                str(OBSERVER),
                "--root-pid",
                str(root_pid),
                "--output",
                str(journal),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def ready(self):
        readable, _, _ = select.select([self.process.stdout], [], [], 25)
        v1.require(bool(readable), "Observer readiness timeout")
        value = json.loads(self.process.stdout.readline())
        v1.require(
            value == dict(event="ready", observer_pid=self.process.pid, root_pid=self.root_pid),
            "Observer readiness identity",
        )

    def finish(self):
        errors = []
        try:
            _, stderr = self.process.communicate(input="STOP\n", timeout=25)
        except subprocess.TimeoutExpired:
            errors.append(dict(stage="supervisor.stop", error_type="TimeoutExpired"))
            self.process.terminate()  # Only the exact child created by this object.
            try:
                _, stderr = self.process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                _, stderr = self.process.communicate(timeout=5)
        if self.process.returncode != 0 or stderr:
            errors.append(
                dict(
                    stage="supervisor.exit",
                    returncode=self.process.returncode,
                    stderr=stderr[:4096],
                )
            )
        return dict(pid=self.process.pid, returncode=self.process.returncode), errors


def journal_events(journal):
    return [json.loads(line) for line in journal.read_text().splitlines()]


def validate_observer(audit, journal):
    events = journal_events(journal)
    v1.require(len(events) >= 4, "Observer needs start, samples and terminal")
    first, last = events[0], events[-1]
    v1.require(
        first["kind"] == "started"
        and first["schema"] == SCHEMA
        and first["root_pid"] == audit["pid"]
        and first["observer_pid"] == audit["observer"]["pid"] != audit["pid"]
        and first["source_sha256"] == hashlib.sha256(OBSERVER.read_bytes()).hexdigest()
        and first["interval_seconds"] == INTERVAL
        and first["command_timeout_seconds"] == TIMEOUT,
        "Separate pinned observer identity",
    )
    samples = events[1:-1]
    v1.require(
        all(e["kind"] == "sample" and e["pid"] == audit["pid"] for e in samples)
        and samples == audit["samples"]
        and all(
            e["own_gpu_clients"] == sorted(set(e["descendants"]) & set(e["gpu_clients"]))
            and audit["pid"] in e["descendants"]
            for e in samples
        )
        and last["kind"] == "finished"
        and last["returncode"] == 0
        and last["reason"] == "requested_stop"
        and last["samples"] == len(samples)
        and audit["observer"]["returncode"] == 0
        and audit["observer"]["journal_sha256"] == hashlib.sha256(journal.read_bytes()).hexdigest()
        and all(
            0 <= a["elapsed_seconds"] <= b["elapsed_seconds"]
            for a, b in zip(events, events[1:], strict=False)
        ),
        "Complete unchanged external observation without missing or failed samples",
    )


def validate_audit(audit, terminal_sha256, pid, journal):
    v1.validate_audit(audit, terminal_sha256, pid)
    v1.require(audit["schema"] == SCHEMA, "External observer schema")
    validate_observer(audit, journal)


class IsolatedQualificationMixin:
    def qualify(self, args):
        from latent_workspace import execution as ex

        if args.device != "cpu":
            return super().qualify(args)
        ex.require(
            v1._MASKED_PID == os.getpid() and os.environ.get("CUDA_VISIBLE_DEVICES") == "",
            "CPU entry must register masking before repository imports",
        )
        path, journal = (
            args.output.parent / name for name in ("CPU_ISOLATION.json", "CPU_OBSERVER.jsonl")
        )
        ex.require(
            not path.exists() and not journal.exists() and not args.output.exists(),
            "Fresh CPU qualification and observer",
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        audit = dict(
            status="CPU_GPU_ISOLATION_FAILED",
            schema=SCHEMA,
            pid=os.getpid(),
            mask_before_runtime_import=True,
            samples=[],
            monitor_errors=[],
            scope="CUDA visibility plus separate-process sampled PID audit; not OS sandbox",
        )
        start, worker, code = time.monotonic(), None, 1
        try:
            worker = Observer(os.getpid(), journal)
            worker.ready()
            audit["child_probe"] = v1.child_probe()
            code = super().qualify(args)
            torch = sys.modules["torch"]
            ex.require(os.environ.get("CUDA_VISIBLE_DEVICES") == "", "CPU mask changed")
            audit.update(
                final_visible_devices=torch.cuda.device_count(),
                final_initialized=torch.cuda.is_initialized(),
                terminal_sha256=ex.digest(args.output / "FINISHED.json"),
            )
        except BaseException as error:
            audit.update(error_type=type(error).__name__, error_message=str(error)[:2048])
            code = 1
        finally:
            if worker is not None:
                try:
                    audit["observer"], errors = worker.finish()
                    audit["monitor_errors"].extend(errors)
                except BaseException as error:
                    audit["monitor_errors"].append(
                        dict(
                            stage="supervisor.finish",
                            error_type=type(error).__name__,
                            message=str(error)[:2048],
                        )
                    )
            try:
                events = journal_events(journal)
                audit["samples"] = [e for e in events if e["kind"] == "sample"]
                audit["monitor_errors"].extend(e for e in events if e["kind"] == "error")
                audit.setdefault("observer", {})["journal_sha256"] = ex.digest(journal)
            except Exception as error:
                audit["monitor_errors"].append(
                    dict(
                        stage="supervisor.journal",
                        error_type=type(error).__name__,
                        message=str(error)[:2048],
                    )
                )
        audit["elapsed_seconds"] = time.monotonic() - start
        try:
            audit["status"] = "CPU_GPU_ISOLATION_PASS"
            validate_audit(audit, ex.digest(args.output / "FINISHED.json"), os.getpid(), journal)
        except (KeyError, ValueError, OSError, TypeError) as error:
            audit["status"] = "CPU_GPU_ISOLATION_FAILED"
            audit["validation_error"] = f"{type(error).__name__}: {error}"[:2048]
            code = 1
        ex.write_new(path, audit)
        print(ex.canonical({k: v for k, v in audit.items() if k != "samples"}), flush=True)
        return code

    def qualification(self, path, seal, plan):
        from latent_workspace import execution as ex

        result = super().qualification(path, seal, plan)
        audit = ex.read(path / "CPU_ISOLATION.json")
        validate_audit(
            audit,
            ex.digest(path / "cpu/FINISHED.json"),
            ex.read(path / "cpu/STARTED.json")["pid"],
            path / "CPU_OBSERVER.jsonl",
        )
        result["cpu_isolation"] = dict(sha256=ex.digest(path / "CPU_ISOLATION.json"))
        result["cpu_observer"] = dict(sha256=ex.digest(path / "CPU_OBSERVER.jsonl"))
        return result
