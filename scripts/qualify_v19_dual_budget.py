#!/usr/bin/env python3
"""Sealed, serial CPU/CUDA V19 dual-budget tests and independent-process resume.

Derived from the V18 window qualifier. The coordinator never imports Torch. Every
test/producer/resumer child ends before the next begins, so no resident CUDA
allocator is reused. No retry, download, real-model update, generation, judge or
weight retirement is offered.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "scripts/qualify_v19_dual_budget.py"
TEST = "tests/test_v19_dual_budget.py"
PASS = "TINY_V19_DUAL_BUDGET_WINDOW_AND_PROCESS_RESTART_PASS_NOT_7B"
CASES = [
    {"dtype": dtype, "full": full, "cap": cap, "factor": "slot_contrast",
     "query": "ordered_difference"}
    for dtype in ("float32", "bfloat16") for full in (False, True) for cap in (0.25, 1.0)
] + [
    {"dtype": "bfloat16", "full": True, "cap": 0.25, "factor": "slot_contrast",
     "query": "final"},
    {"dtype": "float32", "full": True, "cap": 1.0, "factor": "raw_matched_control",
     "query": "ordered_difference"},
]
PLAN = {
    "schema": "v19-dual-budget-qualification-v1",
    "test_file": TEST, "test_cases": 30, "restart_cases": CASES,
    "max_threads": 2, "gpu_memory_limit_gib": 4,
    "wall_seconds_per_device": 900, "test_child_seconds": 600, "restart_child_seconds": 60,
    "real_model_updates": 0, "judge_calls": 0, "new_sequences": 0, "weight_deletions": 0,
    "old_expression_gate": "FAIL", "winner": "none", "non_regression": "NOT_ESTABLISHED",
}
CRITICAL = {
    TEST, "src/latent_workspace_ft_v10/v19_dual_budget_window_learner.py",
    "src/latent_workspace_ft_v10/v19_dual_budget_learner.py",
    "src/latent_workspace_ft_v10/v19_dual_budget_state.py",
    "src/latent_workspace_ft_v10/v19_dual_budget_reader.py",
    "src/latent_workspace_ft_v10/v19_dual_budget_pipeline.py",
    "src/latent_workspace_ft_v10/v18_window_objective.py",
    "src/latent_workspace_ft_v10/v18_reference_bank.py",
}


def write_new(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def files(folder):
    return {p.relative_to(folder).as_posix(): {"bytes": p.stat().st_size, "sha256": digest(p)}
            for p in sorted(folder.rglob("*")) if p.is_file()}


def identity():
    names = subprocess.check_output([
        "git", "ls-files", "-z", "--", "src", "scripts", "tests", "configs",
        "data/v10", "pyproject.toml",
    ], cwd=ROOT).decode().split("\0")
    return {"source_commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
    ).strip(), "source_hashes": {name: digest(ROOT / name) for name in sorted(filter(None, names))}}


def guard(seal):
    spec = importlib.util.spec_from_file_location(
        "source_guard", ROOT / "scripts/run_source_sealed.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.verify(ROOT, seal, ENTRY)
    if identity() != seal:
        raise ValueError("Complete execution source set differs")
    return result


def import_proof(seal):
    top = {Path(name).stem for name in seal["source_hashes"]
           if name.startswith(("scripts/", "tests/")) and name.endswith(".py")}
    result = {}
    for name, module in list(sys.modules.items()):
        belongs = (name == "latent_workspace_ft_v10" or name.startswith("latent_workspace_ft_v10.")
                   or name.startswith("scripts.") or name in top)
        try:
            filename = vars(module).get("__file__")
        except TypeError:
            filename = None
        if not filename:
            if belongs:
                raise ValueError(f"Project module has no direct source: {name}")
            continue
        if not isinstance(filename, str) or not Path(filename).is_absolute():
            raise ValueError(f"Nonabsolute module source: {name}")
        path = Path(filename).resolve()
        local = path.is_relative_to(ROOT)
        if local and path.relative_to(ROOT).parts[0] in (".venv", "venv") and not belongs:
            continue
        if not (local or belongs):
            continue
        if not local or path.suffix != ".py":
            raise ValueError(f"Escaped project source: {name}")
        relative = path.relative_to(ROOT).as_posix()
        if seal["source_hashes"].get(relative) != digest(path):
            raise ValueError(f"Unsealed project source: {name}")
        result[name] = relative
    if not CRITICAL <= set(result.values()):
        raise ValueError("Missing critical imported source proof")
    return result


def test_report(path):
    root = ElementTree.parse(path).getroot()
    counts = {key: sum(int(s.attrib.get(key, 0)) for s in root.iter("testsuite"))
              for key in ("tests", "errors", "failures", "skipped")}
    cases = list(root.iter("testcase"))
    if (counts != {"tests": PLAN["test_cases"], "errors": 0, "failures": 0, "skipped": 0}
            or len(cases) != PLAN["test_cases"]
            or len({(c.get("classname"), c.get("name")) for c in cases}) != len(cases)
            or any(c.get("file") != TEST for c in cases)):
        raise ValueError(f"Frozen unit population failed: {counts}")
    return counts


def child(args, seal):
    source_check = guard(seal)
    if args.output.resolve().is_relative_to(ROOT):
        raise ValueError("Child artifacts must be outside the sealed source")
    args.output.mkdir(parents=True, exist_ok=False)
    write_new(args.output / "STARTED.json", {
        "pid": os.getpid(), "device": args.device, "role": args.role,
        "source_check": source_check, "plan": PLAN, "case_index": args.case_index,
    })
    outcome = {"status": "FAIL", "role": args.role, "device": args.device,
               "pid": os.getpid(), "case_index": args.case_index}
    started = time.monotonic()
    try:
        sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "scripts"), str(ROOT / "tests")]
        import numpy as np
        import pytest
        import torch
        import transformers

        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        torch.set_float32_matmul_precision("highest")
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        if args.device == "cuda":
            clients = subprocess.check_output([
                "nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits",
            ], text=True).strip().splitlines()
            if any(int(pid) != os.getpid() for pid in clients):
                raise ValueError("Other CUDA workload; no computation dispatched")
            if torch.cuda.device_count() != 1:
                raise ValueError("Exactly one CUDA device required")
            free, total = torch.cuda.mem_get_info()
            if free < 4 * 2**30:
                raise ValueError("Insufficient free CUDA memory")
            torch.cuda.set_per_process_memory_fraction(4 * 2**30 / total)
            torch.cuda.reset_peak_memory_stats()
        outcome["runtime"] = {
            "python": sys.version, "torch": str(torch.__version__), "numpy": np.__version__,
            "pytest": pytest.__version__, "transformers": transformers.__version__,
            "cuda": torch.version.cuda, "device": args.device,
            "threads": torch.get_num_threads(), "interop_threads": torch.get_num_interop_threads(),
            "tf32": torch.backends.cuda.matmul.allow_tf32,
        }
        if args.role == "tests":
            code = int(pytest.main(["-q", "--tb=short", "-o", "junit_family=xunit1",
                                   f"--junitxml={args.output / 'TESTS.xml'}", TEST]))
            outcome["pytest_exit_code"] = code
            outcome["counts"] = test_report(args.output / "TESTS.xml")
            if code:
                raise ValueError("Unit test process failed")
        else:
            process_case(args, outcome)
        outcome["imported_sources"] = import_proof(seal)
        guard(seal)
        outcome["peak_cuda_allocated_bytes"] = (
            torch.cuda.max_memory_allocated() if args.device == "cuda" else None
        )
        if args.device == "cuda" and not (0 < outcome["peak_cuda_allocated_bytes"] <= 4 * 2**30):
            raise ValueError("CUDA allocation outside fixed envelope")
        outcome["status"] = "PASS"
    except BaseException as exc:
        outcome.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    outcome["elapsed_seconds"] = time.monotonic() - started
    outcome["files"] = files(args.output)
    write_new(args.output / "FINISHED.json", outcome)
    return 0 if outcome["status"] == "PASS" else 1


def process_case(args, outcome):
    import random

    import numpy as np
    import torch
    from test_v19_dual_budget import META, policy, schedule, state, window_owner, window_update

    from latent_workspace_ft_v10.v15_native_learner import rng_state, tree_hash
    from latent_workspace_ft_v10.v19_dual_budget_window_learner import (
        FORMAT,
        V19DualBudgetWindowLearner,
    )

    case = CASES[args.case_index]
    outcome["case"] = case
    random.seed(19081)
    np.random.seed(19082)
    torch.manual_seed(19083)
    learner, bank = window_owner(getattr(torch, case["dtype"]), case["full"],
                                 factor=case["factor"], cap=case["cap"], mode=case["query"])
    expected_contract = learner.base_run_contract
    producer_path = args.output.parent / "producer"
    checkpoint = producer_path / "window1.pt"
    original_hash = None
    if args.role == "producer":
        outcome["window1_update_sha256"] = tree_hash(window_update(learner))
        outcome["checkpoint_receipt"] = learner.save(checkpoint, META)
        assert outcome["checkpoint_receipt"]["format"] == FORMAT
    else:
        producer = json.loads((producer_path / "FINISHED.json").read_text())
        if producer["status"] != "PASS" or producer["runtime"] != outcome["runtime"]:
            raise ValueError("Producer runtime/result mismatch")
        payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
        original_hash = tree_hash(payload)
        if original_hash != producer["checkpoint_receipt"]["state_sha256"]:
            raise ValueError("Checkpoint content mismatch")
        random.seed(301)
        np.random.seed(302)
        torch.manual_seed(303)
        assert tree_hash(rng_state()) != tree_hash(payload["inner"]["rng"])
        learner = V19DualBudgetWindowLearner.restore(
            learner.binding, learner.bridge, payload,
            expected_workspace_policy=policy(case["query"]), expected_metadata=META,
            expected_run_contract=expected_contract, expected_schedule=schedule(),
            expected_reference_bank=bank, expected_state_sha256=original_hash,
        )
        assert tree_hash(learner.payload(META)) == original_hash
        outcome["producer_pid"] = producer["pid"]
        assert outcome["producer_pid"] != os.getpid()
    outcome["checkpoint_file_sha256"] = digest(checkpoint)
    updated = window_update(learner)
    result = learner.payload(META)
    draws = random.random(), float(np.random.rand()), torch.rand(7, device=args.device)
    outcome["window2"] = {
        "update": updated, "update_sha256": tree_hash(updated),
        "payload_sha256": tree_hash(result),
        "payload_fields": {key: tree_hash(value) for key, value in result.items()},
        "inner_fields": {key: tree_hash(value) for key, value in result["inner"].items()},
        "owned_state": state(learner.inner), "rng_draws_sha256": tree_hash(draws),
        "rng_after_sha256": tree_hash(rng_state()), "completed_steps": learner.completed_steps,
    }
    assert learner.completed_steps == 2
    if args.role == "resumer":
        canonical = lambda x: json.dumps(x, sort_keys=True, allow_nan=False)  # noqa: E731
        assert canonical(outcome["window2"]) == canonical(producer["window2"])
        assert outcome["checkpoint_file_sha256"] == producer["checkpoint_file_sha256"]
        assert tree_hash(payload) == original_hash
        outcome["checkpoint_payload_unchanged"] = True


def environment(device):
    return {"PATH": os.defpath, "LANG": "C.UTF-8", "OMP_NUM_THREADS": "2",
            "MKL_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2",
            "HF_HUB_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
            "TOKENIZERS_PARALLELISM": "false", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "LATENT_V19_TEST_DEVICE": device,
            "CUDA_VISIBLE_DEVICES": "0" if device == "cuda" else ""}


def execute(args, seal):
    source_check = guard(seal)
    if args.output.resolve().is_relative_to(ROOT):
        raise ValueError("Artifacts must be outside sealed execution source")
    args.output.mkdir(parents=True, exist_ok=False)
    write_new(args.output / "STARTED.json", {
        "pid": os.getpid(), "device": args.device, "source_check": source_check,
        "source_seal": seal, "plan": PLAN,
    })
    started = time.monotonic()
    result = {"status": "FAIL", "device": args.device, "children": [], "plan": PLAN}
    try:
        jobs = [("tests", -1, args.output / "tests")]
        jobs += [(role, i, args.output / f"case-{i:02d}" / role)
                 for i in range(len(CASES)) for role in ("producer", "resumer")]
        for role, index, output in jobs:
            remaining = PLAN["wall_seconds_per_device"] - (time.monotonic() - started)
            limit = min(remaining, PLAN["test_child_seconds"] if role == "tests"
                        else PLAN["restart_child_seconds"])
            if limit <= 0:
                raise TimeoutError("Qualification wall limit reached before dispatch")
            command = [sys.executable, "-I", str(ROOT / "scripts/run_source_sealed.py"),
                       "--seal", str(args.source_seal), "--entry", ENTRY, "--", "child",
                       "--source-seal", str(args.source_seal), "--device", args.device,
                       "--output", str(output), "--role", role, "--case-index", str(index)]
            log = args.output / f"{index:02d}-{role}.log"
            with log.open("x") as stream:
                process = subprocess.Popen(command, cwd=ROOT, env=environment(args.device),
                                           stdout=stream, stderr=subprocess.STDOUT,
                                           start_new_session=True)
                try:
                    code = process.wait(timeout=limit)
                except BaseException:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    raise
            result["children"].append({"role": role, "case_index": index,
                                       "relative_path": output.relative_to(args.output).as_posix(),
                                       "launcher_pid": process.pid, "returncode": code})
            if code or not (output / "FINISHED.json").is_file():
                raise ValueError(f"Child failed; no retry: {role}/{index}")
            receipt = json.loads((output / "FINISHED.json").read_text())
            if receipt["status"] != "PASS":
                raise ValueError("Child did not qualify")
        guard(seal)
        result["status"] = PASS
    except BaseException as exc:
        result.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    result["elapsed_seconds"] = time.monotonic() - started
    result["files"] = files(args.output)
    write_new(args.output / "FINISHED.json", result)
    print(json.dumps({k: v for k, v in result.items() if k not in ("files", "plan")}), flush=True)
    return 0 if result["status"] == PASS else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare-seal", "run", "child"))
    parser.add_argument("--source-seal", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"))
    parser.add_argument("--role", choices=("tests", "producer", "resumer"))
    parser.add_argument("--case-index", type=int, default=-1)
    args = parser.parse_args()
    if args.command == "prepare-seal":
        seal = identity()
        guard(seal)
        write_new(args.output, seal)
        return 0
    if not sys.flags.isolated or not sys.pycache_prefix or args.source_seal is None:
        raise ValueError("Use the sealed isolated pre-import launcher")
    if args.device is None:
        raise ValueError("Explicit device required")
    seal = json.loads(args.source_seal.read_text())
    if args.command == "child":
        if (args.role is None or (args.role == "tests" and args.case_index != -1)
                or (args.role != "tests" and not 0 <= args.case_index < len(CASES))):
            raise ValueError("Explicit fixed child/case required")
        return child(args, seal)
    return execute(args, seal)


if __name__ == "__main__":
    raise SystemExit(main())
