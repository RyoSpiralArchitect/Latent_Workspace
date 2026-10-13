#!/usr/bin/env python3
"""One authorized fresh-process full-only migration; offline verification is separate.

The sealed original source and 26-file terminal bundle are not edited. No
third-party/project imports precede the isolated pre-import source guard.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import json
import os
import platform
import resource
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "scripts/continue_v16_adapter_full.py"
PLAN = "configs/v16/ADAPTER_FULL_CONTINUATION_01.json"
ORIGINAL = "provenance/pilots/v16_adapter_migration_20261014"
ORIGINAL_COMMIT = "7c3af3c70df31a69bbe624532dbcd516dbb195a0"
ORIGINAL_HASH = "643300b3ec9468933d7ab68e9d03aedf3d3a9450fe6077bc0ff3c6540b5f034c"
PASS = "EXACT_7B_FULL_CONTINUATION_PASS_NOT_SEMANTIC_QUALIFICATION"
CEILING = {
    "new_sequences": 0,
    "judge_calls": 0,
    "weight_deletions": 0,
    "old_expression_gate": "FAIL",
    "winner": "none",
    "non_regression": "NOT_ESTABLISHED",
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text())


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def exact(a, b, label):
    require(canonical(a) == canonical(b), f"mismatch: {label}")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_source(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def manifest(bundle):
    require(bundle.is_dir() and not bundle.is_symlink(), "missing/symlink bundle")
    result = {}
    for path in sorted(bundle.rglob("*")):
        require(not path.is_symlink(), "symlink in evidence")
        if path.is_file():
            result[path.relative_to(bundle).as_posix()] = {
                "bytes": path.stat().st_size,
                "sha256": digest(path),
            }
        else:
            require(path.is_dir(), "non-regular evidence")
    return result


def validate_selection(plan):
    exact(
        plan,
        {
            "schema": "v16-adapter-full-continuation-01-v1",
            "parent_plan": "configs/v16/ADAPTER_MIGRATION_PLAN.json",
            "original_bundle": ORIGINAL,
            "original_source_commit": ORIGINAL_COMMIT,
            "original_file_count": 26,
            "original_bundle_sha256": ORIGINAL_HASH,
            "authorization": (
                "Human approved only the never-dispatched full mode in a separate process; "
                "do not rerun frozen"
            ),
            "selected_modes": ["full"],
            "planned_unique_windows": 4,
            "planned_replay_windows": 1,
            "planned_backward_pairs": 80,
            "algorithm": (
                "Reuse original arm, replay, losses, complete windows "
                "and all resource floors unchanged"
            ),
            "no_retry": True,
            **CEILING,
        },
        "full-only authorization/selection",
    )


def verify_original(bundle=None):
    bundle = ROOT / ORIGINAL if bundle is None else bundle
    files = manifest(bundle)
    require(len(files) == 26, "original file count changed")
    require(
        hashlib.sha256(canonical(files).encode()).hexdigest() == ORIGINAL_HASH,
        "original bundle changed",
    )
    verifier = load_source("verify_v16_adapter_migration")
    result = verifier.verify(bundle / "raw")
    exact(result, read(bundle / "OFFLINE_VERIFY.json"), "original offline receipt")
    require(result["run_status"] == "INCOMPLETE_NO_RETRY", "original terminal status")
    require(
        result["matched_modes"] == result["replayed_modes"] == ["frozen"],
        "original frozen-only qualification",
    )
    require(result["journaled_backward_pairs"] == 80, "original denominator")
    started, finished = [read(bundle / "raw" / f"{s}.json") for s in ("STARTED", "FINISHED")]
    require(started["seal"]["source_commit"] == ORIGINAL_COMMIT, "original source identity")
    exact(started["seal"], read(bundle / "SOURCE_SEAL.json"), "original source seal")
    require(
        not any(Path(name).name.startswith("full_") for name in files),
        "full work was already started",
    )
    require(
        finished["error"]
        == ("ResourceAbort: Insufficient free memory at full:admission; stop own run only"),
        "original stop was not pre-full admission",
    )
    return {"original_bundle_sha256": ORIGINAL_HASH, "file_count": 26, **result}


def full_work(core, args, plan, parent, objective, architecture, records, guard, seal):
    """The original arithmetic functions are reused, with one literal selected mode."""
    mode = "full"
    guard("full:admission", admission=True, forecast_bytes=plan["storage_forecast_bytes"])
    reference = core.arm(
        args, mode, "legacy", plan, parent, objective, architecture, records, guard, seal
    )
    core.clean_between_arms()
    candidate = core.arm(
        args, mode, "adapter_v2", plan, parent, objective, architecture, records, guard, seal
    )
    core.clean_between_arms()
    for key in ("initial", "windows", "features", "contract"):
        exact(reference[key], candidate[key], f"full:{key}")
    core.write_new(
        args.output / "full_EQUIVALENCE.json",
        {
            "exact": True,
            "steps": [1, 2],
            "ordered_backward_pairs_per_arm": 32,
            "reference": "legacy",
            "candidate": "adapter_v2",
        },
    )
    resumed = core.replay(
        args, mode, candidate, plan, parent, objective, architecture, records, guard
    )
    core.clean_between_arms()
    core.write_new(args.output / "full_REPLAY.json", resumed)


def execute(args):
    require(sys.flags.isolated and sys.pycache_prefix, "use isolated pre-import launcher")
    source_guard = load_source("run_source_sealed")
    seal = read(args.seal)
    check = source_guard.verify(ROOT, seal, ENTRY)
    core = load_source("run_v16_adapter_migration")
    exact(core.identity(), seal, "complete source selection")
    selection, plan = read(ROOT / PLAN), read(ROOT / core.PLAN)
    validate_selection(selection)
    core.validate_plan(plan)
    original = verify_original()
    out, ckpt = args.output.resolve(), args.checkpoints.resolve()
    require(not args.output.exists() and not args.checkpoints.exists(), "fresh destinations only")
    require(
        out != ckpt and not out.is_relative_to(ckpt) and not ckpt.is_relative_to(out),
        "separate output/checkpoint paths",
    )
    require(not out.is_relative_to(ROOT) and not ckpt.is_relative_to(ROOT), "outside source only")
    args.output.mkdir(parents=True, exist_ok=False)
    args.checkpoints.mkdir(parents=True, exist_ok=False)
    require(out.stat().st_dev == ckpt.stat().st_dev, "one persistent filesystem required")
    core.write_new(
        out / "STARTED.json",
        {
            "pid": os.getpid(),
            "source_check": check,
            "seal": seal,
            "selection": selection,
            "plan": plan,
            "original": original,
            "output": str(out),
            "checkpoints": str(ckpt),
        },
    )
    started = time.monotonic()
    result = {"status": "INCOMPLETE_NO_RETRY", "completed_modes": [], **CEILING}
    try:
        core.load_runtime()
        result["imported_project_sources"] = core.verify_imports(seal)
        parent, objective, architecture, records = core.legacy.validate()
        torch = core.torch
        runtime = {
            "python": platform.python_version(),
            "torch": str(torch.__version__),
            "transformers": core.transformers.__version__,
            "cuda": torch.version.cuda,
        }
        exact(runtime, plan["expected_runtime"], "same runtime")
        require(
            hashlib.sha256(inspect.getsource(core.legacy.Adafactor.step).encode()).hexdigest()
            == parent["optimizer"]["base_adafactor_step_sha256"],
            "optimizer math changed",
        )
        torch.set_num_threads(plan["resources"]["cpu_threads"])
        torch.set_num_interop_threads(1)
        torch.set_float32_matmul_precision("highest")
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        require(torch.cuda.device_count() == 1, "one visible CUDA device required")
        guard = core.legacy.Guard(plan["resources"], out)
        guard("admission", admission=True, forecast_bytes=plan["storage_forecast_bytes"])
        torch.cuda.set_per_process_memory_fraction(
            plan["resources"]["allocator_cap_gib"]
            * core.GIB
            / torch.cuda.get_device_properties(0).total_memory
        )
        torch.cuda.reset_peak_memory_stats()
        result["runtime"] = runtime
        full_work(core, args, plan, parent, objective, architecture, records, guard, seal)
        result["completed_modes"].append("full")
        source_guard.verify(ROOT, seal, ENTRY)
        exact(core.identity(), seal, "source unchanged")
        exact(verify_original(), original, "original unchanged")
        core.legacy.validate()
        exact(core.verify_imports(seal), result["imported_project_sources"], "import set unchanged")
        guard("finished")
        result.update(
            status=PASS,
            complete_unique_windows=4,
            complete_replay_windows=1,
            complete_backward_pairs=80,
            peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(),
            peak_cuda_reserved_bytes=torch.cuda.max_memory_reserved(),
            minimum_sampled_device_free_bytes=min(r["free_bytes"] for r in guard.gpu.rows),
            minimum_sampled_host_available_bytes=min(r["available_bytes"] for r in guard.host_rows),
        )
    except BaseException as exc:
        result.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    result["elapsed_seconds"] = time.monotonic() - started
    result["peak_process_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    result["files"] = manifest(out)
    core.write_new(out / "FINISHED.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "files"}), flush=True)
    return 0 if result["status"] == PASS else 1


def verify(bundle):
    """Replay literal receipts offline. Never load Torch or a model/checkpoint."""
    original = verify_original()
    core = load_source("run_v16_adapter_migration")
    previous = load_source("verify_v16_adapter_migration")
    started, finished = [read(bundle / f"{s}.json") for s in ("STARTED", "FINISHED")]
    actual = manifest(bundle)
    actual.pop("FINISHED.json")
    exact(actual, finished["files"], "terminal file set and bytes")
    exact(started["seal"], read(bundle.parent / "SOURCE_SEAL.json"), "execution source seal")
    require(
        {ENTRY, PLAN, core.ENTRY, core.PLAN, "scripts/run_source_sealed.py"}.issubset(
            started["seal"]["source_hashes"]
        ),
        "missing critical execution source",
    )
    exact(
        started["source_check"],
        {
            "schema": "pre-import-source-check-v1",
            "source_commit": started["seal"]["source_commit"],
            "entry": ENTRY,
            "source_files": len(started["seal"]["source_hashes"]),
            "untracked_check": "all",
            "isolated_python": True,
            "fresh_bytecode_cache": True,
        },
        "pre-import receipt",
    )
    validate_selection(started["selection"])
    exact(started["selection"], read(ROOT / PLAN), "selection source")
    core.validate_plan(started["plan"])
    exact(started["plan"], read(ROOT / core.PLAN), "parent plan")
    exact(started["original"], original, "original proof")
    for name, sha in started["seal"]["source_hashes"].items():
        p = ROOT / name
        require(p.resolve().is_relative_to(ROOT) and digest(p) == sha, f"source changed: {name}")
    for key, value in CEILING.items():
        exact(finished[key], value, key)
    pairs, windows, replays = 0, 0, 0
    allowed = {f"full_{impl}_step{s}" for impl in ("legacy", "adapter_v2") for s in (1, 2)}
    allowed.add("full_replay_step2")
    allowed_files = {
        "STARTED.json",
        "RESOURCES.jsonl",
        "HOST_RESOURCES.jsonl",
        "full_EQUIVALENCE.json",
        "full_REPLAY.json",
    }
    allowed_files |= {f"{stem}{suffix}" for stem in allowed for suffix in (".json", "_pairs.jsonl")}
    allowed_files |= {
        f"full_{impl}_{part}.json"
        for impl in ("legacy", "adapter_v2")
        for part in ("INITIAL", "CONTEXT")
    }
    allowed_files |= {f"full_adapter_v2_step{s}_CHECKPOINT.json" for s in (1, 2)}
    require(set(actual).issubset(allowed_files), "unexpected continuation file")
    require(not any(name.startswith("frozen_") for name in actual), "frozen redispatched")
    for path in bundle.glob("*_pairs.jsonl"):
        stem = path.name.removesuffix("_pairs.jsonl")
        require(stem in allowed, "unselected journal")
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        require(len(rows) <= 16, "over-budget window")
        exact(
            [[r["world"], r["query"]] for r in rows],
            [list(p) for p in core.PAIRS][: len(rows)],
            "ordered journal",
        )
        pairs += len(rows)
    require(pairs <= 80, "over-budget continuation")
    for stem in allowed:
        path = bundle / f"{stem}.json"
        if path.exists():
            row = read(path)
            previous.verify_window(row)
            exact(
                row["pairs"],
                [
                    json.loads(line)
                    for line in (bundle / f"{stem}_pairs.jsonl").read_text().splitlines()
                ],
                "window journal",
            )
            require(row["state"]["completed_steps"] == int(stem[-1]), "window step")
            if "replay" in stem:
                replays += 1
            else:
                windows += 1
    matched, replayed = [], []
    if (bundle / "full_EQUIVALENCE.json").exists():
        exact(
            read(bundle / "full_EQUIVALENCE.json"),
            {
                "exact": True,
                "steps": [1, 2],
                "ordered_backward_pairs_per_arm": 32,
                "reference": "legacy",
                "candidate": "adapter_v2",
            },
            "equivalence receipt",
        )
        for part in ("INITIAL", "step1", "step2"):
            exact(
                read(bundle / f"full_legacy_{part}.json"),
                read(bundle / f"full_adapter_v2_{part}.json"),
                f"full:{part}",
            )
        a, b = [read(bundle / f"full_{impl}_CONTEXT.json") for impl in ("legacy", "adapter_v2")]
        for key in ("features", "contract"):
            exact(a[key], b[key], f"full:{key}")
        require(a["contract"]["full_update"] is True, "not full update")
        matched = ["full"]
    if (bundle / "full_REPLAY.json").exists():
        exact(
            read(bundle / "full_replay_step2.json"),
            read(bundle / "full_adapter_v2_step2.json"),
            "complete replay window",
        )
        exact(
            read(bundle / "full_REPLAY.json"),
            {
                "exact": True,
                "from_step": 1,
                "execute_step": 2,
                "compared_pairs": 16,
                "state_sha256": read(bundle / "full_adapter_v2_step2_CHECKPOINT.json")[
                    "state_sha256"
                ],
            },
            "replay payload",
        )
        replayed = ["full"]
    if finished["status"] == PASS:
        require(set(actual) == allowed_files, "PASS file set incomplete")
        require(matched == replayed == finished["completed_modes"] == ["full"], "incomplete PASS")
        require((windows, replays, pairs) == (4, 1, 80), "PASS denominators")
        for key, value in {
            "complete_unique_windows": 4,
            "complete_replay_windows": 1,
            "complete_backward_pairs": 80,
        }.items():
            exact(finished[key], value, key)
    else:
        require(
            finished["status"] == "INCOMPLETE_NO_RETRY" and finished.get("error"),
            "unknown terminal status",
        )
    return {
        "receipt_verification": "PASS",
        "run_status": finished["status"],
        "original_status": original["run_status"],
        "original_bundle_sha256": ORIGINAL_HASH,
        "matched_modes": matched,
        "replayed_modes": replayed,
        "complete_unique_windows": windows,
        "complete_replay_windows": replays,
        "journaled_backward_pairs": pairs,
        "planned_backward_pairs": 80,
        "combined_backward_pairs": 80 + pairs,
        "combined_planned_backward_pairs": 160,
        "combined_engineering_status": (
            "EXACT_7B_MIGRATION_PASS_ACROSS_TWO_PROCESSES"
            if finished["status"] == PASS
            else "INCOMPLETE"
        ),
        "checkpoint_bytes_reloaded_offline": False,
        **CEILING,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare-seal")
    prepare.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--seal", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--checkpoints", type=Path, required=True)
    offline = sub.add_parser("verify")
    offline.add_argument("--bundle", type=Path, required=True)
    sub.add_parser("verify-original")
    args = parser.parse_args()
    if args.command == "prepare-seal":
        require(
            not subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=all"], cwd=ROOT
            ).strip(),
            "clean committed source required",
        )
        core = load_source("run_v16_adapter_migration")
        core.write_new(args.output, core.identity())
        return 0
    if args.command in ("verify", "verify-original"):
        print(
            json.dumps(
                verify(args.bundle) if args.command == "verify" else verify_original(),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    return execute(args)


if __name__ == "__main__":
    raise SystemExit(main())
