#!/usr/bin/env python3
"""Isolated tiny V18 selection qualification, not a learner or semantic run.

Invoke CPU and CUDA as separate fresh processes through run_source_sealed.py.
The selected tests use synthetic data/tiny random models only: no downloads,
training updates, generation, judge dispatch, or old receipt/source mutation.
"""

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
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "scripts/qualify_v18_selection.py"
PLAN = "configs/v18/SELECTION_QUALIFICATION_PLAN.json"
PASS = "TINY_SELECTION_PASS_NOT_LEARNER_OR_SEMANTIC"
EXPECTED_BY_FILE = {
    "tests/test_v18_operand_query.py": 87,
    "tests/test_v18_selection_reader.py": 85,
    "tests/test_v18_selection_pipeline.py": 28,
}
CRITICAL_IMPORTS = {
    "src/latent_workspace_ft_v10/v18_operand_query.py",
    "src/latent_workspace_ft_v10/v18_selection_reader.py",
    "src/latent_workspace_ft_v10/v18_selection_pipeline.py",
    *EXPECTED_BY_FILE,
}
OFFLINE_ENV = {
    "HF_HUB_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
    "TOKENIZERS_PARALLELISM": "false",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
}
CEILING = {
    "real_model_updates": 0,
    "new_sequences": 0,
    "judge_calls": 0,
    "weight_deletions": 0,
    "old_expression_gate": "FAIL",
    "winner": "none",
    "non_regression": "NOT_ESTABLISHED",
}


def write_new(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def identity():
    names = subprocess.check_output(
        [
            "git", "ls-files", "-z", "--", "src", "scripts", "tests", "configs",
            "data/v10", "pyproject.toml",
        ],
        cwd=ROOT,
    ).decode().split("\0")
    return {
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        ).strip(),
        "source_hashes": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in sorted(filter(None, names))
        },
    }


def validate_plan(plan):
    """Exactly bind the selected test population, resources and claim ceiling."""
    expected = {
        "schema": "v18-selection-qualification-v1",
        "test_files": list(EXPECTED_BY_FILE),
        "expected_cases_by_file": EXPECTED_BY_FILE,
        "expected_test_cases": sum(EXPECTED_BY_FILE.values()),
        "max_threads": 2,
        "gpu_memory_limit_gib": 4,
        "wall_limit_seconds": 900,
        "arms": ["final", "ordered_difference", "symmetric_mean"],
        "device_env": "LATENT_SLOT_STATE_TEST_DEVICE",
        "fresh_process_per_device": True,
        "offline_environment": OFFLINE_ENV,
        "claim_ceiling": (
            "tiny inference-text binding/split-query/native-readout arithmetic only; "
            "no learner admission, learning, semantic or 7B qualification"
        ),
        **CEILING,
    }
    # Canonical bytes distinguish bool from integer, beyond Python dict equality.
    canonical = lambda value: json.dumps(  # noqa: E731
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
    )
    if type(plan) is not dict or canonical(plan) != canonical(expected):
        raise ValueError("Fixed selection qualification plan changed")


def test_report(path, plan):
    root = ElementTree.parse(path).getroot()
    suites = list(root.iter("testsuite"))
    counts = {
        key: sum(int(s.attrib.get(key, 0)) for s in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    cases = list(root.iter("testcase"))
    unique = {(case.get("classname"), case.get("name")) for case in cases}
    by_file = {name: 0 for name in plan["test_files"]}
    for case in cases:
        source = case.get("file")
        if source not in by_file:
            raise ValueError("Unselected test in selection qualification report")
        by_file[source] += 1
    if len(cases) != len(unique) or len(cases) != counts["tests"]:
        raise ValueError("Duplicate test or inconsistent JUnit denominator")
    if by_file != plan["expected_cases_by_file"]:
        raise ValueError("Qualified per-file test population differs from frozen plan")
    return counts, by_file


def imported_sources(seal, modules=None):
    """Bind imported local sources without evaluating virtual module attributes."""
    top_level = {
        Path(name).stem
        for name in seal["source_hashes"]
        if name.startswith(("scripts/", "tests/")) and name.endswith(".py")
    }
    imported = {}
    for name, module in list((sys.modules if modules is None else modules).items()):
        belongs = (
            name == "latent_workspace_ft_v10"
            or name.startswith("latent_workspace_ft_v10.")
            or name.startswith("scripts.")
            or name in top_level
        )
        # Torch virtual namespaces inherit fictional class-level __file__ values
        # and may dynamically implement attribute lookup. Only direct metadata
        # identifies a source. Never resolve inherited/dynamic names from cwd.
        try:
            metadata = vars(module)
        except TypeError:
            metadata = {}
        filename = metadata.get("__file__")
        if not filename:
            if belongs:
                raise ValueError(f"Project module has no source: {name}")
            continue
        if type(filename) is not str or not Path(filename).is_absolute():
            raise ValueError(f"Module source must be an explicit absolute path: {name}")
        source = Path(filename).resolve()
        local = source.is_relative_to(ROOT.resolve())
        if (
            local
            and source.relative_to(ROOT.resolve()).parts[0] in (".venv", "venv")
            and not belongs
        ):
            continue
        if not (belongs or local):
            continue
        if not local or source.suffix != ".py":
            raise ValueError(f"Imported project module escaped source tree: {name}")
        if not source.is_file():
            raise ValueError(f"Imported project source does not exist: {name}")
        relative = source.relative_to(ROOT.resolve()).as_posix()
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if seal["source_hashes"].get(relative) != digest:
            raise ValueError(f"Imported project source is not sealed: {name}")
        imported[name] = relative
    if not CRITICAL_IMPORTS <= set(imported.values()):
        raise ValueError("Missing operand/selection reader/pipeline/test import proof")
    return imported


def execute(args):
    if not sys.flags.isolated or not sys.pycache_prefix:
        raise ValueError("Use the isolated pre-import source launcher with fresh bytecode cache")
    module_spec = importlib.util.spec_from_file_location(
        "source_guard", ROOT / "scripts/run_source_sealed.py",
    )
    guard = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(guard)
    seal = json.loads(args.source_seal.read_text())
    source_check = guard.verify(ROOT, seal, ENTRY)
    if identity() != seal:
        raise ValueError("Selection qualification source seal differs")
    plan = json.loads((ROOT / PLAN).read_text())
    validate_plan(plan)
    if args.output.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError("Qualification artifacts must be outside the sealed source tree")
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    write_new(args.output / "STARTED.json", {
        **seal, "plan": plan, "source_check": source_check, "pid": os.getpid(),
        "device": args.device, "python": platform.python_version(),
    })
    outcome = {"status": "FAILED", "device": args.device, **CEILING}

    def deadline(_signal, _frame):
        raise KeyboardInterrupt("Synthetic selection qualification exceeded its fixed wall limit")

    previous = signal.signal(signal.SIGALRM, deadline)
    signal.setitimer(signal.ITIMER_REAL, plan["wall_limit_seconds"])
    try:
        # No third-party/model imports occur before the source and output guards.
        os.environ.update(OFFLINE_ENV)
        os.environ[plan["device_env"]] = args.device
        for key in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
            os.environ.pop(key, None)
        sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "scripts"), str(ROOT / "tests")]
        import pytest
        import torch
        import transformers

        torch.set_num_threads(plan["max_threads"])
        torch.set_num_interop_threads(1)
        torch.set_float32_matmul_precision("highest")
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        if args.device == "cuda":
            clients = subprocess.check_output(
                ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
                text=True,
            ).strip().splitlines()
            if any(int(pid) != os.getpid() for pid in clients):
                raise ValueError("Other GPU workload; no test/model dispatched")
            if torch.cuda.device_count() != 1:
                raise ValueError("One CUDA device required")
            free, total = torch.cuda.mem_get_info(0)
            if free < plan["gpu_memory_limit_gib"] * 2**30:
                raise ValueError("Insufficient free GPU memory")
            torch.cuda.set_per_process_memory_fraction(plan["gpu_memory_limit_gib"] * 2**30 / total)
            torch.cuda.reset_peak_memory_stats()
        outcome["runtime"] = {
            "torch": str(torch.__version__), "transformers": transformers.__version__,
            "pytest": pytest.__version__, "cuda": torch.version.cuda,
            "python": platform.python_version(), "platform": platform.platform(),
        }
        outcome["offline_environment"] = {key: os.environ[key] for key in OFFLINE_ENV}
        code = int(pytest.main([
            "-q", "--tb=short", "-o", "junit_family=xunit1",
            f"--junitxml={args.output / 'TESTS.xml'}", *plan["test_files"],
        ]))
        outcome["pytest_exit_code"] = code
        counts, by_file = test_report(args.output / "TESTS.xml", plan)
        outcome.update(counts=counts, cases_by_file=by_file)
        outcome["imported_project_sources"] = imported_sources(seal)
        guard.verify(ROOT, seal, ENTRY)
        if identity() != seal:
            raise ValueError("Source changed during qualification")
        peak = torch.cuda.max_memory_allocated() if args.device == "cuda" else None
        outcome["peak_cuda_allocated_bytes"] = peak
        if args.device == "cuda" and not (0 < peak <= plan["gpu_memory_limit_gib"] * 2**30):
            raise ValueError("CUDA peak is absent or exceeded the fixed budget")
        passed = code == 0 and counts == {
            "tests": plan["expected_test_cases"], "failures": 0, "errors": 0, "skipped": 0,
        }
        outcome["status"] = PASS if passed else "SYNTHETIC_ENGINEERING_FAIL"
    except BaseException as exc:
        outcome.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        outcome["elapsed_seconds"] = time.monotonic() - started
        outcome["files"] = {
            path.name: {
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in args.output.iterdir() if path.is_file()
        }
        write_new(args.output / "FINISHED.json", outcome)
    print(json.dumps(outcome, sort_keys=True))
    return 0 if outcome["status"] == PASS else 1


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
        validate_plan(json.loads((ROOT / PLAN).read_text()))
        if subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
        ).strip():
            raise ValueError("Commit source before preparing seal; launch also checks untracked")
        seal = identity()
        if not {ENTRY, PLAN, "scripts/run_source_sealed.py", *CRITICAL_IMPORTS} <= set(
            seal["source_hashes"]
        ):
            raise ValueError("Missing committed critical selection qualification source")
        write_new(args.output, seal)
        return 0
    return execute(args)


if __name__ == "__main__":
    raise SystemExit(main())
