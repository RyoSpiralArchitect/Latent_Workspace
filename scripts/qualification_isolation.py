"""Additive, fail-closed CPU qualification boundary for newly authorized runs.

This is a device-visibility guard, not an OS sandbox. Historical execution code
and receipts stay unchanged. The external audit is required in addition to the
ordinary test receipt; a passing test receipt alone cannot admit a model role.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

_MASKED_PID = None


def require(condition, message):
    if not condition:
        raise ValueError(message)


def isolate_cli_before_imports(argv=None):
    """Entry points call this before importing their legacy evaluation graph."""
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "qualify" and "--device" in argv:
        index = argv.index("--device")
        require(index + 1 < len(argv), "Missing qualification device")
        if argv[index + 1] == "cpu":
            global _MASKED_PID
            if _MASKED_PID == os.getpid():
                # Pytest can import the active __main__ script by its module
                # name. Only the registration made before the first imports
                # permits that reentry; an environment variable alone cannot.
                require(os.environ.get("CUDA_VISIBLE_DEVICES") == "", "CPU mask changed")
                return
            mask_before_import()
            _MASKED_PID = os.getpid()


def mask_before_import(environ=None, modules=None):
    environ = os.environ if environ is None else environ
    modules = sys.modules if modules is None else modules
    require("torch" not in modules, "CPU visibility must be set before importing torch")
    environ["CUDA_VISIBLE_DEVICES"] = ""


def snapshot(root_pid):
    processes = subprocess.check_output(["ps", "-eo", "pid=,ppid="], text=True, timeout=10)
    parents = {int(p): int(parent) for p, parent in (s.split() for s in processes.splitlines())}
    descendants = {root_pid}
    while True:
        expanded = descendants | {p for p, parent in parents.items() if parent in descendants}
        if expanded == descendants:
            break
        descendants = expanded
    clients = subprocess.check_output(
        ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
        text=True,
        timeout=10,
    ).split()
    return dict(
        pid=root_pid,
        descendants=sorted(descendants),
        gpu_clients=sorted(int(p) for p in clients),
        own_gpu_clients=sorted(descendants.intersection(map(int, clients))),
    )


PROBE = """
import json, os, torch
assert os.environ.get('CUDA_VISIBLE_DEVICES') == ''
assert torch.cuda.device_count() == 0 and not torch.cuda.is_initialized()
try:
    torch.cuda.init()
except (RuntimeError, AssertionError) as error:
    rejected = type(error).__name__
else:
    raise AssertionError('Masked child initialized CUDA')
assert not torch.cuda.is_initialized()
print(json.dumps(dict(pid=os.getpid(), visible_devices=0, initialized=False,
                     cuda_init_rejected=rejected)))
"""


def child_probe():
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", PROBE],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return json.loads(result.stdout)


def validate_audit(audit, terminal_sha256, pid):
    require(
        audit["status"] == "CPU_GPU_ISOLATION_PASS"
        and audit["terminal_sha256"] == terminal_sha256
        and audit["pid"] == pid
        and audit["mask_before_runtime_import"]
        and audit["final_visible_devices"] == 0
        and audit["final_initialized"] is False
        and audit["child_probe"]["visible_devices"] == 0
        and audit["child_probe"]["initialized"] is False
        and audit["child_probe"]["cuda_init_rejected"] in ("RuntimeError", "AssertionError")
        and audit["samples"]
        and all(not s["own_gpu_clients"] for s in audit["samples"])
        and not audit["monitor_errors"]
        and "error_type" not in audit,
        "CPU qualification requires a matching no-CUDA audit",
    )


class IsolatedQualificationMixin:
    """Use before EvaluationRun in the MRO; CPU and CUDA remain separate processes."""

    def qualify(self, args):
        from latent_workspace import execution as ex

        if args.device != "cpu":
            return super().qualify(args)
        # Legacy entry imports may import torch transitively. The CLI boundary
        # must already have masked it; never accept late environment-only masking.
        ex.require(
            _MASKED_PID == os.getpid() and os.environ.get("CUDA_VISIBLE_DEVICES") == "",
            "CPU entry must register masking before repository imports",
        )
        path = args.output.parent / "CPU_ISOLATION.json"
        ex.require(not path.exists() and not args.output.exists(), "Fresh CPU qualification")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        samples, errors, stop = [], [], threading.Event()
        audit = dict(
            status="CPU_GPU_ISOLATION_FAILED",
            pid=os.getpid(),
            mask_before_runtime_import=True,
            samples=samples,
            monitor_errors=errors,
            scope="CUDA visibility plus sampled parent/descendant nvidia-smi audit; not OS sandbox",
        )

        def sample():
            try:
                samples.append(
                    dict(elapsed_seconds=time.monotonic() - start, **snapshot(os.getpid()))
                )
            except Exception as exc:
                errors.append(type(exc).__name__)

        def monitor():
            while not stop.wait(0.5):
                sample()

        start = time.monotonic()
        sample()
        worker = threading.Thread(target=monitor, daemon=True)
        worker.start()
        code = 1
        try:
            audit["child_probe"] = child_probe()
            code = super().qualify(args)
            torch = sys.modules["torch"]
            ex.require(os.environ.get("CUDA_VISIBLE_DEVICES") == "", "CPU mask changed")
            audit.update(
                final_visible_devices=torch.cuda.device_count(),
                final_initialized=torch.cuda.is_initialized(),
                terminal_sha256=ex.digest(args.output / "FINISHED.json"),
            )
        except BaseException as exc:
            audit["error_type"] = type(exc).__name__
            code = 1
        finally:
            stop.set()
            worker.join(timeout=25)
            if worker.is_alive():
                errors.append("MonitorDidNotStop")
            sample()
        audit["elapsed_seconds"] = time.monotonic() - start
        try:
            audit["status"] = "CPU_GPU_ISOLATION_PASS"
            validate_audit(audit, ex.digest(args.output / "FINISHED.json"), os.getpid())
        except (KeyError, ValueError, OSError):
            audit["status"] = "CPU_GPU_ISOLATION_FAILED"
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
        )
        result["cpu_isolation"] = dict(sha256=ex.digest(path / "CPU_ISOLATION.json"))
        return result
