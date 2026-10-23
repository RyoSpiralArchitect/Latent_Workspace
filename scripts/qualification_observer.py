#!/usr/bin/env python3
"""Standalone, stdlib-only CPU/GPU observer; never imports the test process.

Only PID/PPID and compute-client PID commands are captured. A bad sample is a
terminal failure, not an empty sample or a retry. The JSONL journal is flushed
after every event so an interrupted observer remains visibly incomplete.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

SCHEMA = "ltws-cpu-gpu-observer-v2"
INTERVAL = 0.5
TIMEOUT = 10
COMMANDS = {
    "processes": ["ps", "-eo", "pid=,ppid="],
    "gpu_clients": ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
}


def captured(value):
    value = value or ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return dict(
        text=value[:4096], characters=len(value), sha256=hashlib.sha256(value.encode()).hexdigest()
    )


class ObservationError(ValueError):
    def __init__(self, stage, error, **details):
        self.details = dict(
            stage=stage, error_type=type(error).__name__, message=str(error)[:2048], **details
        )
        super().__init__(f"{stage}: {type(error).__name__}: {error}")


def command_output(name, runner=None):
    runner = subprocess.run if runner is None else runner
    command = COMMANDS[name]
    try:
        result = runner(command, capture_output=True, text=True, timeout=TIMEOUT, check=False)
    except Exception as error:
        raise ObservationError(
            f"{name}.execute",
            error,
            command=command,
            stdout=captured(getattr(error, "stdout", None)),
            stderr=captured(getattr(error, "stderr", None)),
            timeout_seconds=TIMEOUT,
        ) from error
    if result.returncode != 0:
        raise ObservationError(
            f"{name}.exit",
            ValueError(f"Command exited {result.returncode}"),
            command=command,
            returncode=result.returncode,
            stdout=captured(result.stdout),
            stderr=captured(result.stderr),
        )
    return result.stdout, result.stderr


def snapshot(root_pid, runner=None):
    process_text, process_stderr = command_output("processes", runner)
    try:
        parents = {}
        for line in process_text.splitlines():
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) != 2 or not all(p.isascii() and p.isdecimal() for p in parts):
                raise ValueError(f"Expected PID PPID, got {line!r}")
            pid, parent = map(int, parts)
            if pid <= 0 or pid in parents:
                raise ValueError(f"Invalid or duplicate PID: {pid}")
            parents[pid] = parent
        if root_pid not in parents:
            raise ValueError(f"Root PID {root_pid} absent from process snapshot")
        descendants = {root_pid}
        while True:
            expanded = descendants | {p for p, parent in parents.items() if parent in descendants}
            if expanded == descendants:
                break
            descendants = expanded
    except Exception as error:
        raise ObservationError(
            "processes.parse",
            error,
            command=COMMANDS["processes"],
            stdout=captured(process_text),
            stderr=captured(process_stderr),
        ) from error
    client_text, client_stderr = command_output("gpu_clients", runner)
    try:
        values = client_text.split()
        if any(not (p.isascii() and p.isdecimal() and int(p) > 0) for p in values):
            raise ValueError("Expected positive compute-client PIDs or empty output")
        clients = sorted(set(map(int, values)))
    except Exception as error:
        raise ObservationError(
            "gpu_clients.parse",
            error,
            command=COMMANDS["gpu_clients"],
            stdout=captured(client_text),
            stderr=captured(client_stderr),
        ) from error
    return dict(
        pid=root_pid,
        descendants=sorted(descendants),
        gpu_clients=clients,
        own_gpu_clients=sorted(descendants.intersection(clients)),
    )


def observe(root_pid, output):
    start = time.monotonic()
    samples = 0
    with output.open("x") as journal:

        def emit(kind, **fields):
            journal.write(
                json.dumps(
                    dict(kind=kind, elapsed_seconds=time.monotonic() - start, **fields),
                    sort_keys=True,
                )
                + "\n"
            )
            journal.flush()

        def sample():
            nonlocal samples
            emit("sample", **snapshot(root_pid))
            samples += 1

        emit(
            "started",
            schema=SCHEMA,
            root_pid=root_pid,
            observer_pid=os.getpid(),
            source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            interval_seconds=INTERVAL,
            command_timeout_seconds=TIMEOUT,
        )
        code, reason = 1, "error"
        try:
            sample()
            print(
                json.dumps(dict(event="ready", observer_pid=os.getpid(), root_pid=root_pid)),
                flush=True,
            )
            while True:
                readable, _, _ = select.select([sys.stdin], [], [], INTERVAL)
                if readable:
                    message = sys.stdin.readline()
                    if message != "STOP\n":
                        raise ObservationError("control", ValueError(f"Unexpected {message!r}"))
                    sample()
                    code, reason = 0, "requested_stop"
                    break
                sample()
        except BaseException as error:
            details = (
                error.details
                if isinstance(error, ObservationError)
                else dict(
                    stage="observer", error_type=type(error).__name__, message=str(error)[:2048]
                )
            )
            emit("error", **details)
        emit("finished", returncode=code, reason=reason, samples=samples)
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root-pid", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.root_pid <= 0:
        parser.error("Positive root PID required")
    raise SystemExit(observe(args.root_pid, args.output))
