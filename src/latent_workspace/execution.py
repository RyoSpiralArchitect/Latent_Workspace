"""Sealed execution: receipts, qualification and the role/dispatch skeleton.

Every sealed run follows one skeleton: a pre-import source check against a
committed seal, tiny CPU and CUDA qualification (CPU alone when the plan names only
``cpu`` in ``qualification_devices``, for a run whose roles never use a GPU), roles
run as fresh processes in
a fixed order that stop at the first failure, STARTED/FINISHED receipts with
file manifests, and no retry. A runner supplies only its plan, its roles and the
status each role must reach. Endpoints are computed inside a role, so the
dispatcher itself never imports model code (V20 D1's dispatch failed there).

The source launcher (``scripts/run_source_sealed.py``) and the source identity
(``core``: ``identity``, ``verify_imports``, ``load_runtime``) are passed in.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path
from xml.etree import ElementTree

CEILING = dict(
    new_sequences=0,
    judge_calls=0,
    weight_deletions=0,
    native_weight_updates=0,
    old_expression_gate="FAIL",
    winner="none",
    non_regression="NOT_ESTABLISHED",
)
OFFLINE = {
    "HF_HUB_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "TOKENIZERS_PARALLELISM": "false",
}
GIB = 2**30
INCOMPLETE = "INCOMPLETE_NO_RETRY"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text())


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def plan_hash(plan):
    return hashlib.sha256(canonical(plan).encode()).hexdigest()


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_new(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def write_gz(path, value):
    """Deterministic bytes: canonical JSON, fixed gzip header (no name, mtime 0)."""
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0, compresslevel=6) as gz:
        gz.write((canonical(value) + "\n").encode())
    with Path(path).open("xb") as stream:
        stream.write(buffer.getvalue())
        stream.flush()
        os.fsync(stream.fileno())


def read_gz(path):
    return json.loads(gzip.decompress(Path(path).read_bytes()))


def manifest(path):
    return {
        p.relative_to(path).as_posix(): {"bytes": p.stat().st_size, "sha256": digest(p)}
        for p in sorted(Path(path).rglob("*"))
        if p.is_file()
    }


def offline_environment():
    os.environ.update(OFFLINE)


def qualification_devices(plan):
    """The devices a plan qualifies on: CPU and CUDA, or CPU alone for a CPU-only run."""
    devices = tuple(plan.get("qualification_devices", ("cpu", "cuda")))
    require(devices in (("cpu",), ("cpu", "cuda")), "Qualification devices")
    return devices


def qualification_backend_policy(torch_module, plan):
    """Optional explicit CPU backend policy, also inherited by tiny child tests.

    No implicit fallback: old plans leave the runtime untouched. A policy is
    a declared numerical condition, not a dtype conversion or a skipped test.
    """
    key = "qualification_cpu_mkldnn_enabled"
    if key not in plan:
        return {}
    require(type(plan[key]) is bool, "CPU oneDNN policy must be boolean")
    torch_module.backends.mkldnn.enabled = plan[key]
    os.environ["LTWS_CPU_MKLDNN_ENABLED"] = "1" if plan[key] else "0"
    return {"cpu_mkldnn_enabled": torch_module.backends.mkldnn.enabled}


class SealedRun:
    """One sealed run: ``qualify``, ``run-role`` and ``dispatch`` over fixed roles.

    ``roles``: ordered role names. ``role_status``: status each role must reach.
    ``validate``: raises if the plan changed. ``load``: imports a module from
    ``root/scripts`` by name (the source launcher and ``core``).
    """

    def __init__(self, *, root, entry, plan_path, tiny_pass, roles, role_status, validate, load):
        self.root, self.entry, self.plan_path = Path(root), entry, plan_path
        self.tiny_pass, self.roles, self.role_status = tiny_pass, tuple(roles), dict(role_status)
        self.validate, self.load = validate, load

    # -- preflight and qualification ------------------------------------------------

    def preflight(self, args):
        require(
            sys.flags.isolated and sys.pycache_prefix, "Use isolated pre-import source launcher"
        )
        source = self.load("run_source_sealed")
        seal = read(args.seal)
        check = source.verify(self.root, seal, self.entry)
        core = self.load("run_v16_adapter_migration")
        require(core.identity() == seal, "Complete source seal differs")
        plan = read(self.root / self.plan_path)
        self.validate(plan)
        return source, core, seal, check, plan

    def qualify(self, args):
        source, core, seal, check, plan = self.preflight(args)
        require(args.device in qualification_devices(plan), f"{args.device} is not qualified")
        require(not args.output.resolve().is_relative_to(self.root), "Output outside source")
        args.output.mkdir(parents=True, exist_ok=False)
        write_new(
            args.output / "STARTED.json",
            dict(seal=seal, source_check=check, plan=plan, pid=os.getpid(), device=args.device),
        )
        started = time.monotonic()
        result = dict(status=INCOMPLETE, device=args.device, real_model_updates=0, **CEILING)
        try:
            offline_environment()
            os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
            names = plan["qualification_device_env"]
            for name in [names] if isinstance(names, str) else names:
                os.environ[name] = args.device
            sys.path[:0] = [str(self.root / p) for p in ("", "src", "scripts", "tests")]
            core.load_runtime()
            result.update(qualification_backend_policy(core.torch, plan))
            import pytest

            if args.device == "cuda":
                clients = subprocess.check_output(
                    ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
                    text=True,
                ).split()
                require(not any(int(p) != os.getpid() for p in clients), "Other GPU workload")
                free, total = core.torch.cuda.mem_get_info(0)
                limit = plan["qualification_gpu_limit_gib"] * GIB
                require(free >= limit, "Tiny CUDA admission")
                core.torch.cuda.set_per_process_memory_fraction(limit / total)
                core.torch.cuda.reset_peak_memory_stats()

            def deadline(_s, _f):
                raise KeyboardInterrupt("Tiny qualification wall limit")

            signal.signal(signal.SIGALRM, deadline)
            signal.setitimer(signal.ITIMER_REAL, plan["qualification_wall_seconds"])
            try:
                code = int(
                    pytest.main(
                        [
                            "-q",
                            "--tb=short",
                            "-p",
                            "no:cacheprovider",
                            "-o",
                            "junit_family=xunit1",
                            f"--junitxml={args.output / 'TESTS.xml'}",
                            *plan["qualification_test_files"],
                        ]
                    )
                )
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
            suites = ElementTree.parse(args.output / "TESTS.xml").getroot().iter("testsuite")
            totals = {k: 0 for k in ("tests", "failures", "errors", "skipped")}
            for suite in suites:
                for key in totals:
                    totals[key] += int(suite.attrib.get(key, 0))
            result.update(pytest_exit_code=code, counts=totals)
            expected = dict(tests=plan["qualification_cases"], failures=0, errors=0, skipped=0)
            require(code == 0 and totals == expected, "Tiny qualification failed")
            if "cpu_mkldnn_enabled" in result:
                require(
                    core.torch.backends.mkldnn.enabled == result["cpu_mkldnn_enabled"],
                    "CPU backend changed during qualification",
                )
            result["imports"] = core.verify_imports(seal)
            source.verify(self.root, seal, self.entry)
            require(core.identity() == seal, "Source changed during qualification")
            if args.device == "cuda":
                peak = core.torch.cuda.max_memory_allocated()
                limit = plan["qualification_gpu_limit_gib"] * GIB
                require(0 < peak <= limit, "Tiny CUDA envelope")
                result["peak_cuda_allocated_bytes"] = peak
            result["status"] = self.tiny_pass
        except BaseException as exc:
            result.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
        result["elapsed_seconds"] = time.monotonic() - started
        result["files"] = manifest(args.output)
        write_new(args.output / "FINISHED.json", result)
        print(json.dumps({k: v for k, v in result.items() if k != "files"}), flush=True)
        return int(result["status"] != self.tiny_pass)

    def qualification(self, path, seal, plan):
        result = {}
        for device in qualification_devices(plan):
            bundle = path / device
            require((bundle / "FINISHED.json").is_file(), f"{device} qualification missing")
            start, end = read(bundle / "STARTED.json"), read(bundle / "FINISHED.json")
            files = manifest(bundle)
            files.pop("FINISHED.json")
            require(files == end["files"], "Qualification artifact bytes")
            require(
                start["seal"] == seal and start["plan"] == plan and start["device"] == device,
                "Qualification selection/source/device mismatch",
            )
            counts = dict(tests=plan["qualification_cases"], failures=0, errors=0, skipped=0)
            require(
                end["status"] == self.tiny_pass
                and end["pytest_exit_code"] == 0
                and end["counts"] == counts,
                "Every qualification device must pass",
            )
            require(all(end[k] == v for k, v in CEILING.items()), "Qualification ceiling")
            result[device] = manifest(bundle)
        return result

    # -- roles and dispatch ----------------------------------------------------------

    def run_role(self, args, body):
        """Run ``body(core, args, plan, seal)`` as role ``args.role``; it returns the outcome."""
        source, core, seal, check, plan = self.preflight(args)
        require(args.role in self.roles, f"Unknown role {args.role}")
        qualified = self.qualification(args.qualification, seal, plan)
        out, ckpt = args.output.resolve(), args.checkpoints.resolve()
        require(not out.is_relative_to(self.root) and not ckpt.is_relative_to(self.root), "Outside")
        require(not out.exists(), "Fresh role output only")
        out.mkdir(parents=True, exist_ok=False)
        write_new(
            out / "STARTED.json",
            dict(
                pid=os.getpid(),
                role=args.role,
                seal=seal,
                plan=plan,
                source_check=check,
                qualification=qualified,
                output=str(out),
                checkpoints=str(ckpt),
            ),
        )
        started = time.monotonic()
        result = dict(status=INCOMPLETE, role=args.role, **CEILING)

        def deadline(_signal, _frame):
            raise KeyboardInterrupt("Role wall limit")

        signal.signal(signal.SIGALRM, deadline)
        signal.setitimer(signal.ITIMER_REAL, plan["resources"]["max_elapsed_seconds"])
        try:
            offline_environment()
            args.output, args.checkpoints = out, ckpt
            result["outcome"] = body(core, args, plan, seal)
            source.verify(self.root, seal, self.entry)
            require(core.identity() == seal, "Source changed")
            require(self.qualification(args.qualification, seal, plan) == qualified, "Qualified")
            result["imports"] = core.verify_imports(seal)
            result["status"] = self.role_status[args.role]
        except BaseException as exc:
            result.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        result["elapsed_seconds"] = time.monotonic() - started
        result["files"] = manifest(out)
        write_new(out / "FINISHED.json", result)
        print(json.dumps({k: v for k, v in result.items() if k != "files"}), flush=True)
        return int(result["status"] != self.role_status[args.role])

    def role_command(self, args, role):
        return [
            sys.executable,
            "-I",
            str(self.root / "scripts/run_source_sealed.py"),
            "--seal",
            str(args.seal),
            "--entry",
            self.entry,
            "--",
            "run-role",
            "--role",
            role,
            "--seal",
            str(args.seal),
            "--output",
            str(args.output / role),
            "--checkpoints",
            str(args.checkpoints),
            "--qualification",
            str(args.qualification),
        ]

    def dispatch(self, args, summary):
        """Run every role in order; ``summary(out, plan)`` reads the last role's outcome."""
        source, core, seal, check, plan = self.preflight(args)
        qualified = self.qualification(args.qualification, seal, plan)
        out, ckpt = args.output.resolve(), args.checkpoints.resolve()
        require(not out.is_relative_to(self.root) and not ckpt.is_relative_to(self.root), "Outside")
        require(not out.exists() and not ckpt.exists(), "Fresh destinations only")
        out.mkdir(parents=True, exist_ok=False)
        ckpt.mkdir(parents=True, exist_ok=False)
        write_new(
            out / "STARTED.json",
            dict(
                pid=os.getpid(),
                seal=seal,
                plan=plan,
                source_check=check,
                qualification=qualified,
                checkpoints=str(ckpt),
            ),
        )
        started = time.monotonic()
        result = dict(status=INCOMPLETE, completed_roles=[], **CEILING)
        try:
            args.output, args.checkpoints = out, ckpt
            for role in self.roles:
                command = self.role_command(args, role)
                with (out / f"{role}.log").open("x") as log:
                    child = subprocess.Popen(
                        command, cwd=self.root, stdout=log, stderr=subprocess.STDOUT
                    )
                    write_new(out / f"DISPATCH_{role}.json", dict(pid=child.pid, command=command))
                    code = child.wait()
                require(code == 0, f"{role} exited {code}; no later role or retry dispatched")
                status = read(out / role / "FINISHED.json")["status"]
                require(status == self.role_status[role], f"{role} receipt status {status}")
                result["completed_roles"].append(role)
            result["summary"] = summary(out, plan)
            source.verify(self.root, seal, self.entry)
            result["status"] = plan["pass_status"]
        except BaseException as exc:
            result.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
        result["elapsed_seconds"] = time.monotonic() - started
        result["files"] = manifest(out)
        write_new(out / "FINISHED.json", result)
        print(json.dumps({k: v for k, v in result.items() if k != "files"}), flush=True)
        return int(result["status"] != plan["pass_status"])

    # -- command line ----------------------------------------------------------------

    def main(self, bodies, summary, argv=None):
        """``bodies``: role → ``body(core, args, plan, seal)``."""
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command", required=True)
        seal = sub.add_parser("prepare-seal")
        seal.add_argument("--output", type=Path, required=True)
        for name in ("qualify", "run-role", "dispatch"):
            p = sub.add_parser(name)
            p.add_argument("--seal", type=Path, required=True)
            p.add_argument("--output", type=Path, required=True)
            if name == "qualify":
                p.add_argument("--device", choices=("cpu", "cuda"), required=True)
            else:
                p.add_argument("--qualification", type=Path, required=True)
                p.add_argument("--checkpoints", type=Path, required=True)
            if name == "run-role":
                p.add_argument("--role", required=True)
        args = parser.parse_args(argv)
        if args.command == "prepare-seal":
            self.validate(read(self.root / self.plan_path))
            write_new(args.output, self.load("run_v16_adapter_migration").identity())
            return 0
        if args.command == "qualify":
            return self.qualify(args)
        if args.command == "dispatch":
            return self.dispatch(args, summary)
        return self.run_role(args, bodies[args.role])
