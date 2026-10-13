#!/usr/bin/env python3
"""Owned preparation repair; only missing full adapter updates and replay.

All historical source/evidence remains immutable. No automatic retry. Project
and third-party imports follow the isolated pre-import guard for live work.
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
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "scripts/run_v16_adapter_full_recovery_02.py"
PLAN = "configs/v16/ADAPTER_FULL_RECOVERY_02.json"
PREVIOUS = "provenance/pilots/v16_adapter_full_continuation_01_20261014"
PREVIOUS_COMMIT = "6bf83985f02575a83aefe9817f1afcea7baa832e"
PREVIOUS_HASH = "49c2b861805a1208e433011fa1dac9ed4c9e109161891bfb295a37acb1efbd2a"
PASS = "EXACT_7B_FULL_PREPARATION_REPAIR_PASS_NOT_SEMANTIC_QUALIFICATION"
TINY_PASS = "SYNTHETIC_PREPARATION_PASS_NOT_7B_QUALIFICATION"
TESTS = ["tests/test_native_training_preparation.py"]
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


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def validate_selection(plan):
    exact(
        plan,
        {
            "schema": "v16-adapter-full-recovery-02-v1",
            "parent_plan": "configs/v16/ADAPTER_MIGRATION_PLAN.json",
            "previous_bundle": PREVIOUS,
            "previous_source_commit": PREVIOUS_COMMIT,
            "previous_file_count": 20,
            "previous_bundle_sha256": PREVIOUS_HASH,
            "authorization": (
                "Human approved the proposed preparation repair, tiny qualification, "
                "then a separate missing-adapter/replay attempt; no completed arm rerun"
            ),
            "selected_mode": "full",
            "selected_implementation": "adapter_v2",
            "planned_unique_windows": 2,
            "planned_replay_windows": 1,
            "planned_backward_pairs": 48,
            "retained_reference_pairs": 32,
            "retained_frozen_pairs": 80,
            "preparation": "owned_single_native_input_grad_hook_nonreentrant_idempotent",
            "comparison": "exact_except_explicit_source_commit_and_preparation_provenance",
            "tiny_tests": TESTS,
            "tiny_cases": 22,
            "tiny_gpu_limit_gib": 4,
            "tiny_wall_seconds": 300,
            "no_retry": True,
            **CEILING,
        },
        "recovery authorization/selection",
    )


def verify_history(bundle=None):
    old = load("continue_v16_adapter_full")
    bundle = ROOT / PREVIOUS if bundle is None else bundle
    manifest = old.manifest(bundle)
    require(len(manifest) == 20, "previous file count changed")
    require(
        hashlib.sha256(canonical(manifest).encode()).hexdigest() == PREVIOUS_HASH,
        "previous complete bundle changed",
    )
    result = old.verify(bundle / "raw")
    exact(result, read(bundle / "OFFLINE_VERIFY.json"), "previous offline receipt")
    finished = read(bundle / "raw/FINISHED.json")
    require(
        finished["status"] == "INCOMPLETE_NO_RETRY"
        and finished["error"] == "ValueError: Training adapter rejects unqualified native hooks",
        "previous failure is not pre-adapter hook admission",
    )
    require(
        result["journaled_backward_pairs"] == 32
        and result["complete_unique_windows"] == 2
        and result["complete_replay_windows"] == 0,
        "previous denominators differ",
    )
    require(
        not any("adapter_v2" in p or "replay" in p for p in manifest if p.startswith("raw/")),
        "selected work already started",
    )
    require(
        read(bundle / "SOURCE_SEAL.json")["source_commit"] == PREVIOUS_COMMIT,
        "reference source identity",
    )
    return {"previous_bundle_sha256": PREVIOUS_HASH, "file_count": 20, **result}


def reference():
    raw = ROOT / PREVIOUS / "raw"
    return {
        "initial": read(raw / "full_legacy_INITIAL.json"),
        "context": read(raw / "full_legacy_CONTEXT.json"),
        "windows": [read(raw / f"full_legacy_step{s}.json") for s in (1, 2)],
    }


def compare_context(reference_context, context, source_commit):
    """Only TWO declared provenance differences; no state/math normalization."""
    exact(reference_context["features"], context["features"], "feature receipt")
    left, right = reference_context["contract"], context["contract"]
    keys = {
        "original_base_sha256",
        "original_legacy_identity_sha256",
        "objective",
        "data",
        "plan_sha256",
        "full_update",
        "source_commit",
    }
    require(set(left) == keys and set(right) == keys | {"preparation"}, "contract keys changed")
    require(left["source_commit"] == PREVIOUS_COMMIT, "reference commit changed")
    require(right["source_commit"] == source_commit, "candidate commit changed")
    for key in keys - {"source_commit"}:
        exact(left[key], right[key], f"owned contract:{key}")
    prep = right["preparation"]
    exact(
        prep,
        {
            "schema": "native-hf-owned-checkpoint-preparation-v1",
            "transformers": "5.15.0",
            "native_method_source_sha256": {
                "gradient_checkpointing_enable": (
                    "b9bcfa11735c8f26016b80f1ddf2227b9cc478056330358e57e7eaf2f603cb33"
                ),
                "enable_input_require_grads": (
                    "40cef9819fccca325944cf432038e0afd302b63e87ea02369cbc19816cfa303f"
                ),
            },
            "checkpoint_policy": [
                {
                    "module": name,
                    "enabled": True,
                    "function": "torch.utils.checkpoint.checkpoint",
                    "keywords": {"use_reentrant": False},
                }
                for name in ["model", *(f"model.layers.{i}" for i in range(32))]
            ],
            "input_gradient_hook": {
                "module": "model.embed_tokens",
                "registered": 1,
                "tracked": 1,
                "owner": "installed_PreTrainedModel.enable_input_require_grads",
            },
            "legacy_difference": (
                "one_tracked_input_grad_hook_instead_of_duplicate_with_stale_handle"
            ),
            "weights_losses_optimizers": "unchanged",
        },
        "owned preparation",
    )
    exact(context["binding"]["checkpointing"], prep["checkpoint_policy"], "bound preparation")


def source_preflight(args):
    require(sys.flags.isolated and sys.pycache_prefix, "use isolated pre-import launcher")
    source_guard = load("run_source_sealed")
    seal = read(args.seal)
    check = source_guard.verify(ROOT, seal, ENTRY)
    core = load("run_v16_adapter_migration")
    exact(core.identity(), seal, "complete source seal")
    selection = read(ROOT / PLAN)
    validate_selection(selection)
    plan = read(ROOT / core.PLAN)
    core.validate_plan(plan)
    return source_guard, core, seal, check, selection, plan


def runtime(core, plan):
    observed = {
        "python": platform.python_version(),
        "torch": str(core.torch.__version__),
        "transformers": core.transformers.__version__,
        "cuda": core.torch.version.cuda,
    }
    exact(observed, plan["expected_runtime"], "same runtime")
    core.torch.set_num_threads(plan["resources"]["cpu_threads"])
    core.torch.set_num_interop_threads(1)
    core.torch.set_float32_matmul_precision("highest")
    core.torch.backends.cuda.matmul.allow_tf32 = False
    core.torch.backends.cudnn.allow_tf32 = False
    return observed


def verify_qualification(bundle, seal):
    old = load("continue_v16_adapter_full")
    started, finished = [read(bundle / f"{s}.json") for s in ("STARTED", "FINISHED")]
    files = old.manifest(bundle)
    files.pop("FINISHED.json")
    exact(files, finished["files"], "tiny artifact bytes")
    require(set(files) == {"STARTED.json", "TESTS.xml"}, "tiny file set")
    exact(started["seal"], seal, "tiny same source")
    validate_selection(started["selection"])
    require(started["device"] == "cuda" and started["test_files"] == TESTS, "tiny scope")
    require(finished["status"] == TINY_PASS and finished["pytest_exit_code"] == 0, "tiny failed")
    counts = {"tests": 22, "failures": 0, "errors": 0, "skipped": 0}
    exact(finished["counts"], counts, "tiny counts")
    suites = list(ElementTree.parse(bundle / "TESTS.xml").getroot().iter("testsuite"))
    exact({k: sum(int(s.attrib.get(k, 0)) for s in suites) for k in counts}, counts, "tiny XML")
    core = load("run_v16_adapter_migration")
    exact(finished["runtime"], read(ROOT / core.PLAN)["expected_runtime"], "tiny runtime")
    for k, v in {**CEILING, "real_model_updates": 0}.items():
        exact(finished[k], v, k)
    return {"status": TINY_PASS, "files": old.manifest(bundle), "tests": 22}


def qualify(args):
    source_guard, core, seal, check, selection, plan = source_preflight(args)
    verify_history()
    require(not args.output.resolve().is_relative_to(ROOT), "output outside source")
    args.output.mkdir(parents=True, exist_ok=False)
    core.write_new(
        args.output / "STARTED.json",
        {
            "seal": seal,
            "source_check": check,
            "selection": selection,
            "device": "cuda",
            "test_files": TESTS,
            "pid": os.getpid(),
        },
    )
    start = time.monotonic()
    result = {"status": "INCOMPLETE_NO_RETRY", "real_model_updates": 0, **CEILING}
    try:
        os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        os.environ["LATENT_PREPARATION_TEST_DEVICE"] = "cuda"
        sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "scripts"), str(ROOT / "tests")]
        core.load_runtime()
        import pytest

        torch = core.torch
        result["runtime"] = runtime(core, plan)
        clients = (
            subprocess.check_output(
                ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
                text=True,
            )
            .strip()
            .splitlines()
        )
        require(not any(int(pid) != os.getpid() for pid in clients), "Other GPU workload")
        require(torch.cuda.device_count() == 1, "one CUDA device")
        free, total = torch.cuda.mem_get_info(0)
        require(free >= 4 * core.GIB, "tiny admission memory")
        torch.cuda.set_per_process_memory_fraction(4 * core.GIB / total)
        torch.cuda.reset_peak_memory_stats()
        torch.set_default_device("cuda")

        def deadline(_signal, _frame):
            raise KeyboardInterrupt("Tiny qualification wall limit")

        previous = signal.signal(signal.SIGALRM, deadline)
        signal.setitimer(signal.ITIMER_REAL, selection["tiny_wall_seconds"])
        try:
            code = int(
                pytest.main(
                    [
                        "-q",
                        "--tb=short",
                        "-o",
                        "junit_family=xunit1",
                        f"--junitxml={args.output / 'TESTS.xml'}",
                        *TESTS,
                    ]
                )
            )
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
        suites = list(ElementTree.parse(args.output / "TESTS.xml").getroot().iter("testsuite"))
        counts = {
            k: sum(int(s.attrib.get(k, 0)) for s in suites)
            for k in ("tests", "failures", "errors", "skipped")
        }
        result.update(
            pytest_exit_code=code,
            counts=counts,
            peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(),
        )
        result["imported_project_sources"] = core.verify_imports(seal)
        source_guard.verify(ROOT, seal, ENTRY)
        exact(core.identity(), seal, "tiny source unchanged")
        verify_history()
        require(code == 0, "tiny tests failed")
        exact(counts, {"tests": 22, "failures": 0, "errors": 0, "skipped": 0}, "tiny counts")
        result["status"] = TINY_PASS
    except BaseException as exc:
        result.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    result["elapsed_seconds"] = time.monotonic() - start
    result["files"] = load("continue_v16_adapter_full").manifest(args.output)
    core.write_new(args.output / "FINISHED.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "files"}), flush=True)
    return 0 if result["status"] == TINY_PASS else 1


def fresh(core, parent, architecture, guard):
    from latent_workspace_ft_v10.native_training_preparation import (
        prepare_native_gradient_checkpointing,
    )

    config = core.legacy.old.engine.ModelConfig(**architecture["model"])
    tokenizer = core.legacy.old.engine.load_tokenizer(config)
    require(tokenizer.eos_token_id == 2, "pinned EOS")
    base = core.legacy.old.engine._load_hf_model(config).to("cuda")
    require(core.legacy.old.prior.state_hash(base) == core.legacy.old.BASE_HASH, "pinned base")
    base.requires_grad_(True).train(True)
    preparation = prepare_native_gradient_checkpointing(base)
    exact(prepare_native_gradient_checkpointing(base), preparation, "idempotent production setup")
    random.seed(parent["seed"])
    core.np.random.seed(parent["seed"])
    core.torch.manual_seed(parent["seed"])
    bridge = (
        core.legacy.create_reader(
            base.config.hidden_size, architecture["bridge"], "query_modulated"
        )
        .to("cuda")
        .float()
    )
    require(
        core.legacy.old.prior.state_hash(bridge)
        == ("97cb24a0bec75d9b00fa0c8b8e6056d27a21ee739fd0564752b6734e9b148fe4"),
        "matched bridge initialization",
    )
    guard("fresh_original_parts_loaded")
    return base, bridge, tokenizer, preparation


def adapter_arm(core, args, plan, parent, objective, architecture, records, guard, seal):
    base, bridge, tokenizer, preparation = fresh(core, parent, architecture, guard)
    contract = {**core.owned_contract(base, objective, True, seal), "preparation": preparation}
    metadata = {
        "source_commit": seal["source_commit"],
        "seal_sha256": digest(args.seal),
        "plan_sha256": digest(ROOT / core.PLAN),
        "selection_sha256": digest(ROOT / PLAN),
        "reference_bundle_sha256": PREVIOUS_HASH,
        "mode": "full",
        "implementation": "adapter_v2",
    }
    learner = core.AdapterNativeLearnerV2(
        core.MistralTrainingBinding(base, 16),
        bridge,
        full_update=True,
        optimizer_config=parent["optimizer"],
        run_contract=contract,
    )
    store = core.legacy.LiveStore(learner, tokenizer, records, guard)
    result = {
        "initial": core.state_fingerprint(learner),
        "windows": [],
        "checkpoints": [],
        "context": {
            "features": store.feature_receipt(),
            "contract": contract,
            "metadata": metadata,
            "binding": learner.binding.describe(),
        },
    }
    core.write_new(args.output / "full_adapter_v2_INITIAL.json", result["initial"])
    core.write_new(args.output / "full_adapter_v2_CONTEXT.json", result["context"])
    retained = reference()
    exact(retained["initial"], result["initial"], "retained legacy initial state")
    compare_context(retained["context"], result["context"], seal["source_commit"])
    for step in plan["steps"]:
        stem = f"full_adapter_v2_step{step}"
        window = core.update_window(
            learner, store, objective, "adapter_v2", guard, args.output / f"{stem}_pairs.jsonl"
        )
        core.write_new(args.output / f"{stem}.json", window)
        require(learner.completed_steps == step, "progression")
        exact(retained["windows"][step - 1], window, f"retained full legacy window {step}")
        result["windows"].append(window)
        core.snapshot_admission(plan, guard, True)
        path = args.checkpoints / f"full_step{step}.pt"
        receipt = learner.save(path, metadata)
        receipt["sha256"] = digest(path)
        core.write_new(args.output / f"{stem}_CHECKPOINT.json", receipt)
        result["checkpoints"].append(receipt)
        guard("checkpoint_saved")
        print(
            json.dumps(
                {
                    "implementation": "adapter_v2",
                    "step": step,
                    "exact_retained_reference": True,
                    "complete_pairs": 16,
                }
            ),
            flush=True,
        )
    return result


def replay(core, args, primary, plan, parent, objective, architecture, records, guard):
    base, bridge, tokenizer, prep = fresh(core, parent, architecture, guard)
    context = primary["context"]
    exact(prep, context["contract"]["preparation"], "restore owned preparation")
    receipt = primary["checkpoints"][0]
    path = args.checkpoints / receipt["path"]
    require(
        path.stat().st_size == receipt["bytes"] and digest(path) == receipt["sha256"],
        "checkpoint bytes differ",
    )
    core.snapshot_admission(plan, guard, True)
    payload = core.torch.load(path, map_location="cpu", weights_only=True)
    learner = core.AdapterNativeLearnerV2.restore(
        core.MistralTrainingBinding(base, 16),
        bridge,
        payload,
        expected_metadata=context["metadata"],
        expected_run_contract=context["contract"],
        expected_state_sha256=receipt["state_sha256"],
    )
    del payload
    gc.collect()
    store = core.legacy.LiveStore(learner, tokenizer, records, guard)
    exact(store.feature_receipt(), context["features"], "replay features")
    window = core.update_window(
        learner,
        store,
        objective,
        "adapter_v2",
        guard,
        args.output / "full_replay_step2_pairs.jsonl",
    )
    core.write_new(args.output / "full_replay_step2.json", window)
    exact(primary["windows"][1], window, "complete replay update")
    core.snapshot_admission(plan, guard, True)
    state = core.tree_hash(learner.payload(context["metadata"]))
    require(state == primary["checkpoints"][1]["state_sha256"], "v2 payload replay mismatch")
    return {
        "exact": True,
        "from_step": 1,
        "execute_step": 2,
        "state_sha256": state,
        "compared_pairs": 16,
    }


def work(core, args, plan, parent, objective, architecture, records, guard, seal):
    guard("full:admission", admission=True, forecast_bytes=plan["storage_forecast_bytes"])
    candidate = adapter_arm(core, args, plan, parent, objective, architecture, records, guard, seal)
    core.clean_between_arms()
    core.write_new(
        args.output / "full_EQUIVALENCE.json",
        {
            "exact": True,
            "steps": [1, 2],
            "ordered_backward_pairs_per_arm": 32,
            "reference_bundle_sha256": PREVIOUS_HASH,
            "reference_recomputed": False,
            "candidate": "adapter_v2",
            "provenance_differences": ["source_commit", "preparation"],
        },
    )
    resumed = replay(core, args, candidate, plan, parent, objective, architecture, records, guard)
    core.clean_between_arms()
    core.write_new(args.output / "full_REPLAY.json", resumed)


def execute(args):
    source_guard, core, seal, check, selection, plan = source_preflight(args)
    history = verify_history()
    qualification = verify_qualification(args.qualification, seal)
    out, ckpt = args.output.resolve(), args.checkpoints.resolve()
    require(not args.output.exists() and not args.checkpoints.exists(), "fresh destinations only")
    require(
        out != ckpt and not out.is_relative_to(ckpt) and not ckpt.is_relative_to(out),
        "separate outputs/checkpoints",
    )
    require(not out.is_relative_to(ROOT) and not ckpt.is_relative_to(ROOT), "outside source")
    args.output.mkdir(parents=True, exist_ok=False)
    args.checkpoints.mkdir(parents=True, exist_ok=False)
    require(out.stat().st_dev == ckpt.stat().st_dev, "one persistent filesystem")
    core.write_new(
        out / "STARTED.json",
        {
            "pid": os.getpid(),
            "seal": seal,
            "source_check": check,
            "selection": selection,
            "plan": plan,
            "history": history,
            "qualification": qualification,
            "output": str(out),
            "checkpoints": str(ckpt),
        },
    )
    start = time.monotonic()
    result = {"status": "INCOMPLETE_NO_RETRY", "completed_modes": [], **CEILING}
    try:
        core.load_runtime()
        # Import preparation before the import-set snapshot; no model constructed.
        from latent_workspace_ft_v10 import native_training_preparation  # noqa: F401

        result["imported_project_sources"] = core.verify_imports(seal)
        parent, objective, architecture, records = core.legacy.validate()
        torch = core.torch
        result["runtime"] = runtime(core, plan)
        require(
            hashlib.sha256(inspect.getsource(core.legacy.Adafactor.step).encode()).hexdigest()
            == parent["optimizer"]["base_adafactor_step_sha256"],
            "optimizer math changed",
        )
        require(torch.cuda.device_count() == 1, "one visible CUDA device")
        guard = core.legacy.Guard(plan["resources"], out)
        guard("admission", admission=True, forecast_bytes=plan["storage_forecast_bytes"])
        torch.cuda.set_per_process_memory_fraction(
            plan["resources"]["allocator_cap_gib"]
            * core.GIB
            / torch.cuda.get_device_properties(0).total_memory
        )
        torch.cuda.reset_peak_memory_stats()
        work(core, args, plan, parent, objective, architecture, records, guard, seal)
        source_guard.verify(ROOT, seal, ENTRY)
        exact(core.identity(), seal, "source unchanged")
        exact(verify_history(), history, "historical evidence unchanged")
        exact(verify_qualification(args.qualification, seal), qualification, "tiny unchanged")
        core.legacy.validate()
        exact(core.verify_imports(seal), result["imported_project_sources"], "import set unchanged")
        guard("finished")
        result.update(
            status=PASS,
            completed_modes=["full"],
            complete_unique_windows=2,
            complete_replay_windows=1,
            complete_backward_pairs=48,
        )
    except BaseException as exc:
        result.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    if "guard" in locals():
        result.update(
            peak_cuda_allocated_bytes=core.torch.cuda.max_memory_allocated(),
            peak_cuda_reserved_bytes=core.torch.cuda.max_memory_reserved(),
            minimum_sampled_device_free_bytes=min(
                (r["free_bytes"] for r in guard.gpu.rows), default=None
            ),
            minimum_sampled_host_available_bytes=min(
                (r["available_bytes"] for r in guard.host_rows), default=None
            ),
        )
    result["elapsed_seconds"] = time.monotonic() - start
    result["peak_process_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    result["files"] = load("continue_v16_adapter_full").manifest(out)
    core.write_new(out / "FINISHED.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "files"}), flush=True)
    return 0 if result["status"] == PASS else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    seal = sub.add_parser("prepare-seal")
    seal.add_argument("--output", type=Path, required=True)
    tiny = sub.add_parser("qualify")
    tiny.add_argument("--seal", type=Path, required=True)
    tiny.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--seal", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--checkpoints", type=Path, required=True)
    run.add_argument("--qualification", type=Path, required=True)
    sub.add_parser("verify-history")
    args = parser.parse_args()
    if args.command == "prepare-seal":
        require(
            not subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=all"], cwd=ROOT
            ).strip(),
            "clean committed source",
        )
        core = load("run_v16_adapter_migration")
        core.write_new(args.output, core.identity())
        return 0
    if args.command == "verify-history":
        print(json.dumps(verify_history(), indent=2, sort_keys=True))
        return 0
    return qualify(args) if args.command == "qualify" else execute(args)


if __name__ == "__main__":
    raise SystemExit(main())
