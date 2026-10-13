#!/usr/bin/env python3
"""Source-gated sequential 7B old/adapter update/replay comparison; no API calls.

Third-party and project imports occur only after the isolated source check.
New V16 reader factors are deliberately absent from this migration experiment.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.util
import inspect
import json
import os
import platform
import random
import resource
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = "configs/v16/ADAPTER_MIGRATION_PLAN.json"
ENTRY = "scripts/run_v16_adapter_migration.py"
GIB = 2**30
PAIRS = tuple((w, q) for w in range(2) for q in range(8))


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_new(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def assert_exact(left, right, label):
    require(canonical(left) == canonical(right), f"Exact comparison failed: {label}")


def identity():
    names = (
        subprocess.check_output(
            [
                "git",
                "ls-files",
                "-z",
                "--",
                "src",
                "scripts",
                "tests",
                "configs",
                "data/v10",
                "pyproject.toml",
            ],
            cwd=ROOT,
        )
        .decode()
        .split("\0")
    )
    return {
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_hashes": {name: digest(ROOT / name) for name in sorted(filter(None, names))},
    }


def load_runtime():
    # Called by the sealed entry or tiny local tests, never at module import.
    global torch, np, transformers, legacy, AdapterNativeLearnerV2, MistralTrainingBinding
    global adapted_pair_objective, tree_hash, rng_state
    sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
    import numpy as np
    import run_v15_native_learner as legacy
    import torch
    import transformers

    from latent_workspace_ft_v10.adapted_pair_objective import adapted_pair_objective
    from latent_workspace_ft_v10.adapter_native_learner_v2 import AdapterNativeLearnerV2
    from latent_workspace_ft_v10.training_binding import MistralTrainingBinding
    from latent_workspace_ft_v10.v15_native_learner import rng_state, tree_hash


def verify_imports(seal):
    """Reject an editable-install redirection before constructing a model."""
    script_names = {
        Path(p).stem
        for p in seal["source_hashes"]
        if p.startswith("scripts/") and p.endswith(".py")
    }
    imported = {}
    for name, module in list(sys.modules.items()):
        if (
            name == "latent_workspace_ft_v10"
            or name.startswith("latent_workspace_ft_v10.")
            or name in script_names
        ):
            path = Path(module.__file__).resolve()
            relative = path.relative_to(ROOT).as_posix()
            require(
                seal["source_hashes"].get(relative) == digest(path),
                f"imported source outside seal: {name}",
            )
            imported[name] = relative
    return imported


def validate_plan(plan):
    require(plan["schema"] == "v16-prerequisite-adapter-7b-migration-v1", "plan schema")
    for key, value in {
        "parent": "configs/v15/NATIVE_LEARNER_PLAN.json",
        "seed": 47,
        "modes": ["frozen", "full"],
        "implementations": ["legacy", "adapter_v2"],
        "worlds": [0, 1],
        "queries": list(range(8)),
        "steps": [1, 2],
        "adapter_checkpoints": [1, 2],
        "adapter_replay": {"from_step": 1, "execute_step": 2},
        "planned_unique_windows": 8,
        "planned_replay_windows": 2,
        "planned_backward_pairs": 160,
        "comparison": (
            "exact_loss_spill_order_accumulated_gradient_hash_after_every_pair_update_all_state_rng"
        ),
        "storage_forecast_bytes": 64 * GIB,
        "snapshot_host_extra_bytes": 32 * GIB,
        "new_sequences": 0,
        "judge_calls": 0,
        "weight_deletions": 0,
        "no_retry": True,
        "old_expression_gate": "FAIL",
        "winner": "none",
        "non_regression": "NOT_ESTABLISHED",
    }.items():
        assert_exact(plan[key], value, key)
    require(
        plan["expected_runtime"]
        == {
            "python": "3.12.14",
            "torch": "2.13.0+cu132",
            "transformers": "5.15.0",
            "cuda": "13.2",
        },
        "frozen new runtime",
    )
    require(
        plan["resources"]
        == {
            "admission_free_gib": 31,
            "allocator_cap_gib": 30.5,
            "abort_free_gib": 0.75,
            "host_admission_available_gib": 100,
            "host_abort_available_gib": 24,
            "disk_free_gib": 50,
            "max_elapsed_seconds": 7200,
            "cpu_threads": 2,
        },
        "resource envelope changed",
    )


def pair_loss(learner, store, world, query, objective, implementation):
    if implementation == "legacy":
        terms = (
            legacy.backward.full_native_answer_terms
            if learner.full_update
            else legacy.old.native_answer_terms
        )
        return legacy.backward.pair_objective(
            learner.pipeline, store, world, query, objective["training"], 0.0, terms
        )
    require(implementation == "adapter_v2", "unknown implementation")
    row = store.renderings[world, query]
    return adapted_pair_objective(
        learner.pipeline,
        lambda side: store.write(learner.bridge, world, side),
        prefix_ids=tuple(row["prompt_ids"]),
        span=legacy.old.bound_span(row),
        candidate_ids=row["candidate_ids"],
        labels=[store.records[world]["answers"][side][query] for side in (0, 1)],
        contract=objective["training"],
        eos_weight=0.0,
        eos_token_id=2,
    )


def state_fingerprint(learner):
    # Hash one tensor at a time; do not duplicate a full native model on host/GPU.
    return {
        "completed_steps": learner.completed_steps,
        "native_state": {n: tree_hash(p) for n, p in learner.base.state_dict().items()},
        "bridge_state": {n: tree_hash(p) for n, p in learner.bridge.state_dict().items()},
        "masters": {n: tree_hash(p) for n, p in learner.masters.items()},
        "base_optimizer": tree_hash(learner.base_optimizer.state_dict())
        if learner.base_optimizer
        else None,
        "bridge_optimizer": tree_hash(learner.bridge_optimizer.state_dict()),
        "rng": tree_hash(rng_state()),
    }


def update_window(learner, store, objective, implementation, guard, pair_log=None):
    learner.begin_window(PAIRS)
    rows = []
    for world, query in PAIRS:
        guard(f"{implementation}:{learner.completed_steps + 1}:{world}:{query}:before")
        loss, components = pair_loss(learner, store, world, query, objective, implementation)
        values = {k: float(v.detach()) for k, v in dict(loss=loss, **components).items()}
        spill = learner.backward_pair((world, query), loss)
        del loss, components
        # Observe the actual native-dtype accumulated CPU gradients after EVERY
        # ordered pair. No restore, recast or alternate accumulator is used.
        gradients = {n: learner.window._buffers[id(p)] for n, p in learner.named}
        row = {
            "world": world,
            "query": query,
            "components": values,
            "spill": spill,
            "accumulated_gradients_sha256": tree_hash(gradients),
        }
        del gradients
        rows.append(row)
        if pair_log is not None:
            with pair_log.open("a") as stream:
                stream.write(canonical(row) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        guard(f"{implementation}:{learner.completed_steps + 1}:{world}:{query}:spilled")
    update = learner.step()
    guard(f"{implementation}:{learner.completed_steps}:updated")
    return {"pairs": rows, "update": update, "state": state_fingerprint(learner)}


def fresh_parts(full, parent, architecture, guard):
    config = legacy.old.engine.ModelConfig(**architecture["model"])
    tokenizer = legacy.old.engine.load_tokenizer(config)
    require(tokenizer.eos_token_id == 2, "pinned EOS")
    base = legacy.old.engine._load_hf_model(config).to("cuda")
    require(legacy.old.prior.state_hash(base) == legacy.old.BASE_HASH, "pinned original model")
    base.requires_grad_(full).train(full)
    if full:
        legacy.old.engine.enable_gradient_checkpointing(base)
    random.seed(parent["seed"])
    np.random.seed(parent["seed"])
    torch.manual_seed(parent["seed"])
    bridge = (
        legacy.create_reader(base.config.hidden_size, architecture["bridge"], "query_modulated")
        .to("cuda")
        .float()
    )
    require(
        legacy.old.prior.state_hash(bridge)
        == "97cb24a0bec75d9b00fa0c8b8e6056d27a21ee739fd0564752b6734e9b148fe4",
        "matched bridge initialization",
    )
    guard("fresh_original_parts_loaded")
    return base, bridge, tokenizer


def owned_contract(base, objective, full, seal):
    return {
        "original_base_sha256": tree_hash(base.state_dict()),
        "original_legacy_identity_sha256": legacy.old.BASE_HASH,
        "objective": {"terms": objective["training"], "eos_weight": 0.0, "query_mode": "final"},
        "data": {
            "pairs": [list(p) for p in PAIRS],
            "training_sha256": digest(ROOT / "data/v10/functional_train.jsonl"),
        },
        "source_commit": seal["source_commit"],
        "plan_sha256": digest(ROOT / PLAN),
        "full_update": full,
    }


def snapshot_admission(plan, guard, full):
    extra = plan["snapshot_host_extra_bytes"] if full else GIB
    require(
        legacy.backward.host_available()
        >= extra + plan["resources"]["host_abort_available_gib"] * GIB,
        "forecast independent snapshot host envelope",
    )
    guard("before_checkpoint", forecast_bytes=32 * GIB if full else GIB)


def arm(args, mode, implementation, plan, parent, objective, architecture, records, guard, seal):
    full = mode == "full"
    base, bridge, tokenizer = fresh_parts(full, parent, architecture, guard)
    contract = owned_contract(base, objective, full, seal)
    metadata = {
        "source_commit": seal["source_commit"],
        "seal_sha256": digest(args.seal),
        "plan_sha256": digest(ROOT / PLAN),
        "mode": mode,
        "implementation": implementation,
    }
    if implementation == "legacy":
        learner = legacy.V15NativeLearner(
            base, bridge, full_update=full, optimizer_config=parent["optimizer"], boundary=16
        )
    else:
        learner = AdapterNativeLearnerV2(
            MistralTrainingBinding(base, 16),
            bridge,
            full_update=full,
            optimizer_config=parent["optimizer"],
            run_contract=contract,
        )
    store = legacy.LiveStore(learner, tokenizer, records, guard)
    result = {
        "initial": state_fingerprint(learner),
        "windows": [],
        "checkpoints": [],
        "features": store.feature_receipt(),
        "contract": contract,
        "metadata": metadata,
    }
    write_new(args.output / f"{mode}_{implementation}_INITIAL.json", result["initial"])
    write_new(
        args.output / f"{mode}_{implementation}_CONTEXT.json",
        {
            "features": result["features"],
            "contract": contract,
            "metadata": metadata,
            "binding": learner.binding.describe() if implementation == "adapter_v2" else None,
        },
    )
    for step in plan["steps"]:
        name = f"{mode}_{implementation}_step{step}"
        window = update_window(
            learner, store, objective, implementation, guard, args.output / f"{name}_pairs.jsonl"
        )
        require(learner.completed_steps == step, "progression mismatch")
        write_new(args.output / f"{name}.json", window)
        result["windows"].append(window)
        print(
            json.dumps(
                {"mode": mode, "implementation": implementation, "step": step, "complete_pairs": 16}
            ),
            flush=True,
        )
        if implementation == "adapter_v2":
            snapshot_admission(plan, guard, full)
            path = args.checkpoints / f"{mode}_step{step}.pt"
            receipt = learner.save(path, metadata)
            receipt["sha256"] = digest(path)
            result["checkpoints"].append(receipt)
            write_new(args.output / f"{name}_CHECKPOINT.json", receipt)
            guard("checkpoint_saved")
    if not full:
        require(legacy.old.prior.state_hash(base) == legacy.old.BASE_HASH, "frozen model changed")
    return result


def replay(args, mode, primary, plan, parent, objective, architecture, records, guard):
    full = mode == "full"
    base, bridge, tokenizer = fresh_parts(full, parent, architecture, guard)
    receipt = primary["checkpoints"][0]
    path = args.checkpoints / receipt["path"]
    require(
        path.stat().st_size == receipt["bytes"] and digest(path) == receipt["sha256"],
        "checkpoint bytes differ",
    )
    snapshot_admission(plan, guard, full)
    payload = torch.load(path, map_location="cpu", weights_only=True)
    learner = AdapterNativeLearnerV2.restore(
        MistralTrainingBinding(base, 16),
        bridge,
        payload,
        expected_metadata=primary["metadata"],
        expected_run_contract=primary["contract"],
        expected_state_sha256=receipt["state_sha256"],
    )
    del payload
    gc.collect()
    store = legacy.LiveStore(learner, tokenizer, records, guard)
    window = update_window(
        learner,
        store,
        objective,
        "adapter_v2",
        guard,
        args.output / f"{mode}_replay_step2_pairs.jsonl",
    )
    write_new(args.output / f"{mode}_replay_step2.json", window)
    assert_exact(primary["windows"][1], window, f"{mode} complete next-update replay")
    snapshot_admission(plan, guard, full)
    state_hash = tree_hash(learner.payload(primary["metadata"]))
    require(state_hash == primary["checkpoints"][1]["state_sha256"], "v2 payload replay mismatch")
    return {
        "exact": True,
        "from_step": 1,
        "execute_step": 2,
        "state_sha256": state_hash,
        "compared_pairs": 16,
    }


def clean_between_arms():
    gc.collect()
    torch.cuda.empty_cache()


def execute(args):
    require(sys.flags.isolated and sys.pycache_prefix, "use the isolated pre-import launcher")
    spec = importlib.util.spec_from_file_location(
        "source_guard", ROOT / "scripts/run_source_sealed.py"
    )
    source_guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(source_guard)
    seal = json.loads(args.seal.read_text())
    source_check = source_guard.verify(ROOT, seal, ENTRY)
    assert_exact(identity(), seal, "complete source selection")
    plan = json.loads((ROOT / PLAN).read_text())
    validate_plan(plan)
    require(
        not args.output.exists() and not args.checkpoints.exists(),
        "fresh exclusive destinations required",
    )
    out, ckpt = args.output.resolve(), args.checkpoints.resolve()
    require(
        out != ckpt and not out.is_relative_to(ckpt) and not ckpt.is_relative_to(out),
        "separate output/checkpoint directories required",
    )
    require(
        not out.is_relative_to(ROOT) and not ckpt.is_relative_to(ROOT),
        "outputs must be outside sealed source",
    )
    args.output.mkdir(parents=True, exist_ok=False)
    args.checkpoints.mkdir(parents=True, exist_ok=False)
    require(out.stat().st_dev == ckpt.stat().st_dev, "forecast requires one persistent filesystem")
    write_new(
        args.output / "STARTED.json",
        {
            "pid": os.getpid(),
            "source_check": source_check,
            "seal": seal,
            "plan": plan,
            "output": str(out),
            "checkpoints": str(ckpt),
        },
    )
    started = time.monotonic()
    result = {
        "status": "INCOMPLETE_NO_RETRY",
        "completed_modes": [],
        "new_sequences": 0,
        "judge_calls": 0,
        "weight_deletions": 0,
        "old_expression_gate": "FAIL",
        "winner": "none",
        "non_regression": "NOT_ESTABLISHED",
    }
    try:
        load_runtime()
        result["imported_project_sources"] = verify_imports(seal)
        parent, objective, architecture, records = legacy.validate()
        runtime = {
            "python": platform.python_version(),
            "torch": str(torch.__version__),
            "transformers": transformers.__version__,
            "cuda": torch.version.cuda,
        }
        assert_exact(runtime, plan["expected_runtime"], "pinned new runtime")
        require(
            hashlib.sha256(inspect.getsource(legacy.Adafactor.step).encode()).hexdigest()
            == parent["optimizer"]["base_adafactor_step_sha256"],
            "optimizer math changed",
        )
        torch.set_num_threads(plan["resources"]["cpu_threads"])
        torch.set_num_interop_threads(1)
        torch.set_float32_matmul_precision("highest")
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        require(torch.cuda.device_count() == 1, "one visible CUDA device required")
        guard = legacy.Guard(plan["resources"], args.output)
        guard("admission", admission=True, forecast_bytes=plan["storage_forecast_bytes"])
        torch.cuda.set_per_process_memory_fraction(
            plan["resources"]["allocator_cap_gib"]
            * GIB
            / torch.cuda.get_device_properties(0).total_memory
        )
        torch.cuda.reset_peak_memory_stats()
        result["runtime"] = runtime
        for mode in plan["modes"]:
            guard(
                f"{mode}:admission", admission=True, forecast_bytes=plan["storage_forecast_bytes"]
            )
            reference = arm(
                args, mode, "legacy", plan, parent, objective, architecture, records, guard, seal
            )
            clean_between_arms()
            migrated = arm(
                args,
                mode,
                "adapter_v2",
                plan,
                parent,
                objective,
                architecture,
                records,
                guard,
                seal,
            )
            clean_between_arms()
            for key in ("initial", "windows", "features", "contract"):
                assert_exact(reference[key], migrated[key], f"{mode}:{key}")
            write_new(
                args.output / f"{mode}_EQUIVALENCE.json",
                {
                    "exact": True,
                    "steps": [1, 2],
                    "ordered_backward_pairs_per_arm": 32,
                    "reference": "legacy",
                    "candidate": "adapter_v2",
                },
            )
            resumed = replay(
                args, mode, migrated, plan, parent, objective, architecture, records, guard
            )
            clean_between_arms()
            write_new(args.output / f"{mode}_REPLAY.json", resumed)
            result["completed_modes"].append(mode)
        source_guard.verify(ROOT, seal, ENTRY)
        assert_exact(identity(), seal, "source unchanged")
        legacy.validate()
        require(verify_imports(seal) == result["imported_project_sources"], "import set changed")
        guard("finished")
        result.update(
            status="EXACT_7B_MIGRATION_PASS_NOT_SEMANTIC_QUALIFICATION",
            complete_unique_windows=8,
            complete_replay_windows=2,
            complete_backward_pairs=160,
            peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(),
            peak_cuda_reserved_bytes=torch.cuda.max_memory_reserved(),
            minimum_sampled_device_free_bytes=min(r["free_bytes"] for r in guard.gpu.rows),
            minimum_sampled_host_available_bytes=min(r["available_bytes"] for r in guard.host_rows),
        )
    except BaseException as exc:
        result.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    result["elapsed_seconds"] = time.monotonic() - started
    result["peak_process_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    result["files"] = {
        p.name: {"bytes": p.stat().st_size, "sha256": digest(p)}
        for p in args.output.iterdir()
        if p.is_file()
    }
    write_new(args.output / "FINISHED.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "files"}), flush=True)
    return 0 if result["status"] == "EXACT_7B_MIGRATION_PASS_NOT_SEMANTIC_QUALIFICATION" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare-seal")
    prepare.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--seal", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--checkpoints", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare-seal":
        require(
            not subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=all"], cwd=ROOT
            ).strip(),
            "clean committed source required",
        )
        write_new(args.output, identity())
        return 0
    return execute(args)


if __name__ == "__main__":
    raise SystemExit(main())
