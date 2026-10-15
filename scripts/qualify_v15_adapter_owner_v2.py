#!/usr/bin/env python3
"""V2 checkpoint repair qualification; additive copy of the sealed V1 launcher."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = "configs/v15/ADAPTER_OWNER_V2_QUALIFICATION_PLAN.json"


def write_new(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def identity():
    names = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--", "src", "scripts", "tests", PLAN],
            cwd=ROOT,
        )
        .decode()
        .split("\0")
    )
    return {
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_hashes": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in sorted(filter(None, names))
        },
    }


def execute(args):
    if not sys.flags.isolated or not sys.pycache_prefix:
        raise ValueError("Use the isolated pre-import source launcher with fresh bytecode cache")
    spec = importlib.util.spec_from_file_location(
        "source_guard", ROOT / "scripts/run_source_sealed.py"
    )
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    seal = json.loads(args.source_seal.read_text())
    source_check = guard.verify(ROOT, seal, "scripts/qualify_v15_adapter_owner_v2.py")
    if identity() != seal:
        raise ValueError("Qualification source seal differs")
    plan = json.loads((ROOT / PLAN).read_text())
    if plan["test_files"] != [
        "tests/test_training_readout.py",
        "tests/test_adapter_native_learner.py",
        "tests/test_adapter_native_learner_v2.py",
    ]:
        raise ValueError("Fixed test selection changed")
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    write_new(
        args.output / "STARTED.json",
        {
            **seal,
            "plan": plan,
            "source_check": source_check,
            "pid": os.getpid(),
            "device": args.device,
            "python": platform.python_version(),
        },
    )
    outcome = {
        "status": "FAILED",
        "device": args.device,
        "real_model_updates": 0,
        "new_sequences": 0,
        "judge_calls": 0,
        "weight_deletions": 0,
        "old_expression_gate": "FAIL",
        "winner": "none",
    }
    try:
        # No repository/third-party imports occur before the source checks above.
        os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts"), str(ROOT / "tests")]
        import pytest
        import torch
        import transformers

        torch.set_num_threads(plan["max_threads"])
        torch.set_num_interop_threads(1)
        torch.set_float32_matmul_precision("highest")
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        if args.device == "cuda":
            clients = (
                subprocess.check_output(
                    ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
                    text=True,
                )
                .strip()
                .splitlines()
            )
            if any(int(pid) != os.getpid() for pid in clients):
                raise ValueError("Other GPU workload; no test/model dispatched")
            if torch.cuda.device_count() != 1:
                raise ValueError("One CUDA device required")
            free, total = torch.cuda.mem_get_info(0)
            if free < plan["gpu_memory_limit_gib"] * 2**30:
                raise ValueError("Insufficient free GPU memory")
            torch.cuda.set_per_process_memory_fraction(plan["gpu_memory_limit_gib"] * 2**30 / total)
            torch.cuda.reset_peak_memory_stats()
        torch.set_default_device(args.device)
        outcome["runtime"] = {
            "torch": str(torch.__version__),
            "transformers": transformers.__version__,
            "pytest": pytest.__version__,
            "cuda": torch.version.cuda,
            "python": platform.python_version(),
            "platform": platform.platform(),
        }

        def deadline(_signal, _frame):
            raise KeyboardInterrupt("Synthetic qualification exceeded its fixed wall limit")

        previous = signal.signal(signal.SIGALRM, deadline)
        signal.setitimer(signal.ITIMER_REAL, plan["wall_limit_seconds"])
        try:
            code = int(
                pytest.main(
                    [
                        "-q",
                        "--tb=short",
                        "-o",
                        "junit_family=xunit1",
                        f"--junitxml={args.output / 'TESTS.xml'}",
                        *plan["test_files"],
                    ]
                )
            )
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
        from xml.etree import ElementTree

        root = ElementTree.parse(args.output / "TESTS.xml").getroot()
        suites = list(root.iter("testsuite"))
        counts = {
            key: sum(int(s.attrib.get(key, 0)) for s in suites)
            for key in ("tests", "failures", "errors", "skipped")
        }
        # An editable installation must not silently redirect this isolated
        # checkout to another workspace's project modules.
        top_level = {
            Path(name).stem
            for name in seal["source_hashes"]
            if name.startswith(("scripts/", "tests/")) and name.endswith(".py")
        }
        imported = {}
        for name, module in list(sys.modules.items()):
            if (
                name == "latent_workspace_ft_v10"
                or name.startswith("latent_workspace_ft_v10.")
                or name in top_level
            ):
                source = Path(module.__file__).resolve()
                relative = source.relative_to(ROOT).as_posix()
                digest = hashlib.sha256(source.read_bytes()).hexdigest()
                if seal["source_hashes"].get(relative) != digest:
                    raise ValueError(f"Imported project source is not sealed: {name}")
                imported[name] = relative
        outcome["imported_project_sources"] = imported
        outcome.update(
            pytest_exit_code=code,
            counts=counts,
            peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated()
            if args.device == "cuda"
            else None,
        )
        if code == 0 and counts == {
            "tests": plan["expected_test_cases"],
            "failures": 0,
            "errors": 0,
            "skipped": 0,
        }:
            outcome["status"] = "SYNTHETIC_CHECKPOINT_V2_PASS_NOT_7B_QUALIFICATION"
        else:
            outcome["status"] = "SYNTHETIC_ENGINEERING_FAIL"
    except BaseException as exc:
        outcome.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    finally:
        outcome["elapsed_seconds"] = time.monotonic() - started
        outcome["files"] = {
            p.name: {
                "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in args.output.iterdir()
            if p.is_file()
        }
        write_new(args.output / "FINISHED.json", outcome)
    print(json.dumps(outcome, sort_keys=True))
    return 0 if outcome["status"] == "SYNTHETIC_CHECKPOINT_V2_PASS_NOT_7B_QUALIFICATION" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare-seal")
    prepare.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--source-seal", required=True, type=Path)
    run.add_argument("--output", required=True, type=Path)
    run.add_argument("--device", required=True, choices=("cpu", "cuda"))
    args = parser.parse_args()
    if args.command == "prepare-seal":
        if subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT
        ).strip():
            raise ValueError(
                "Commit source before preparing seal; launch separately checks untracked"
            )
        write_new(args.output, identity())
        return 0
    return execute(args)


if __name__ == "__main__":
    raise SystemExit(main())
