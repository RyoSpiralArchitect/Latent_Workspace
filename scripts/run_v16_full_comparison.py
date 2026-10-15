#!/usr/bin/env python3
"""Prospective three-arm V16 pilot. No automatic retry, API or generation.

The dispatcher never imports torch; each arm owns a fresh child process.
Project/runtime imports for live work follow the sealed pre-import launcher.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.util
import inspect
import json
import os
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
ENTRY = "scripts/run_v16_full_comparison.py"
PLAN = "configs/v16/FULL_COMPARISON_PLAN.json"
ARMS = ("common", "raw_matched_control", "slot_contrast")
PASS = "BOUNDED_FULL_COMPARISON_COMPLETE_NOT_SEMANTIC_QUALIFICATION"
TINY_PASS = "TINY_COMPARISON_HARNESS_PASS_NOT_7B_QUALIFICATION"
CEILING = dict(
    new_sequences=0,
    judge_calls=0,
    weight_deletions=0,
    old_expression_gate="FAIL",
    winner="none",
    non_regression="NOT_ESTABLISHED",
)


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def read(path):
    return json.loads(Path(path).read_text())


def require(ok, message):
    if not ok:
        raise ValueError(message)


def validate_plan(plan):
    expected = {
        "schema": "v16-three-arm-full-comparison-v1",
        "arms": list(ARMS),
        "parent": "configs/v16/ADAPTER_MIGRATION_PLAN.json",
        "seed": 47,
        "worlds": [0, 1],
        "queries": list(range(8)),
        "steps": [1, 2],
        "evaluation_steps": [0, 1, 2],
        "checkpoint_steps": [1, 2],
        "replay": {"from_step": 1, "execute_step": 2},
        "full_update": True,
        "interaction_fraction": 0.25,
        "random_memory_seed": 470016,
        "evaluation_conditions": [
            "intact",
            "twin",
            "reverse_intact",
            "reverse_twin",
            "zero",
            "unrelated",
            "common_intact",
            "common_twin",
            "random_intact",
            "random_twin",
        ],
        "evaluation_rows_per_step": 160,
        "direct_base_rows_per_step": 16,
        "factor_rows_per_step": 80,
        "planned_unique_windows": 6,
        "planned_replay_windows": 3,
        "planned_backward_pairs": 144,
        "per_arm_storage_forecast_bytes": 64 * 2**30,
        "process_policy": "fresh_process_per_arm_sequential_stop_on_first_failure",
        "arithmetic": "unchanged_native_bf16_base_fp32_bridge_cpu_native_gradient_accumulation",
        "training_rng": "reseed_47_after_reader_construction_for_all_arms",
        "diagnostics": "no_grad_no_mode_switch_no_global_rng_draw_state_fingerprint_unchanged",
        "qualification_test_files": ["tests/test_v16_full_comparison.py"],
        "qualification_cases": 12,
        "qualification_wall_seconds": 900,
        "qualification_gpu_limit_gib": 4,
        "no_retry": True,
        **CEILING,
        "scope": (
            "Two exposed training worlds; bounded mechanism and state pilot, "
            "not held-out generalization or base-floor qualification"
        ),
    }
    require(plan == expected, "Frozen comparison plan changed")


def preflight(args):
    require(sys.flags.isolated and sys.pycache_prefix, "Use isolated pre-import source launcher")
    source = load("run_source_sealed")
    seal = read(args.seal)
    check = source.verify(ROOT, seal, ENTRY)
    core = load("run_v16_adapter_migration")
    require(core.identity() == seal, "Complete source seal differs")
    plan = read(ROOT / PLAN)
    validate_plan(plan)
    parent = read(ROOT / plan["parent"])
    core.validate_plan(parent)
    old_seal = read(ROOT / "provenance/pilots/v16_slot_state_owner_20261014/SOURCE_SEAL.json")
    require(
        all(core.digest(ROOT / p) == h for p, h in old_seal["source_hashes"].items()),
        "Historical 526-file qualification source changed",
    )
    return source, core, seal, check, plan, parent


def manifest(path):
    core = load("run_v16_adapter_migration")
    return {
        p.relative_to(path).as_posix(): {"bytes": p.stat().st_size, "sha256": core.digest(p)}
        for p in sorted(path.rglob("*"))
        if p.is_file()
    }


def qualify(args):
    source, core, seal, check, plan, parent = preflight(args)
    require(not args.output.resolve().is_relative_to(ROOT), "Output must be outside source")
    args.output.mkdir(parents=True, exist_ok=False)
    core.write_new(
        args.output / "STARTED.json",
        dict(seal=seal, source_check=check, plan=plan, pid=os.getpid(), device=args.device),
    )
    started = time.monotonic()
    result = dict(status="INCOMPLETE_NO_RETRY", device=args.device, real_model_updates=0, **CEILING)
    try:
        os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        os.environ["LATENT_COMPARISON_TEST_DEVICE"] = args.device
        sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "scripts"), str(ROOT / "tests")]
        core.load_runtime()
        import pytest

        result["runtime"] = load("run_v16_adapter_full_recovery_02").runtime(core, parent)
        if args.device == "cuda":
            clients = (
                subprocess.check_output(
                    ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
                    text=True,
                )
                .strip()
                .splitlines()
            )
            require(not any(int(p) != os.getpid() for p in clients), "Other GPU workload")
            free, total = core.torch.cuda.mem_get_info(0)
            require(free >= 4 * core.GIB, "Tiny CUDA admission")
            core.torch.cuda.set_per_process_memory_fraction(4 * core.GIB / total)

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
                        "-o",
                        "junit_family=xunit1",
                        f"--junitxml={args.output / 'TESTS.xml'}",
                        *plan["qualification_test_files"],
                    ]
                )
            )
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        suites = list(ElementTree.parse(args.output / "TESTS.xml").getroot().iter("testsuite"))
        counts = {
            k: sum(int(s.attrib.get(k, 0)) for s in suites)
            for k in ("tests", "failures", "errors", "skipped")
        }
        result.update(pytest_exit_code=code, counts=counts)
        require(
            code == 0
            and counts == dict(tests=plan["qualification_cases"], failures=0, errors=0, skipped=0),
            "Tiny qualification failed",
        )
        result["imports"] = core.verify_imports(seal)
        source.verify(ROOT, seal, ENTRY)
        require(core.identity() == seal, "Source changed during qualification")
        result["status"] = TINY_PASS
    except BaseException as exc:
        result.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    result["elapsed_seconds"] = time.monotonic() - started
    result["files"] = manifest(args.output)
    core.write_new(args.output / "FINISHED.json", result)
    print(json.dumps(result), flush=True)
    return int(result["status"] != TINY_PASS)


def qualification(path, seal, plan):
    result = {}
    for device in ("cpu", "cuda"):
        bundle = path / device
        start, end = read(bundle / "STARTED.json"), read(bundle / "FINISHED.json")
        files = manifest(bundle)
        files.pop("FINISHED.json")
        require(files == end["files"], "Qualification artifact bytes")
        require(
            start["seal"] == seal and start["plan"] == plan and start["device"] == device,
            "Qualification selection/source/device mismatch",
        )
        require(
            end["status"] == TINY_PASS and end["pytest_exit_code"] == 0,
            "Both CPU and CUDA qualification must pass",
        )
        counts = dict(tests=plan["qualification_cases"], failures=0, errors=0, skipped=0)
        require(end["counts"] == counts, "Qualification counts")
        suites = list(ElementTree.parse(bundle / "TESTS.xml").getroot().iter("testsuite"))
        require(
            {k: sum(int(s.attrib.get(k, 0)) for s in suites) for k in counts} == counts,
            "Qualification XML counts",
        )
        require(all(end[k] == v for k, v in CEILING.items()), "Qualification ceiling")
        result[device] = manifest(bundle)
    return result


def fresh(core, parent, architecture, guard, arm, plan):
    base, bridge, tokenizer, prep = load("run_v16_adapter_full_recovery_02").fresh(
        core, parent, architecture, guard
    )
    if arm != "common":
        from latent_workspace_ft_v10.v16_slot_contrast import SlotContrastWorkspaceBridge

        bridge = SlotContrastWorkspaceBridge(
            bridge, mode=arm, interaction_fraction=plan["interaction_fraction"]
        )
    # Architecture construction consumes RNG differently; training draws do not.
    random.seed(plan["seed"])
    core.np.random.seed(plan["seed"])
    core.torch.manual_seed(plan["seed"])
    return base, bridge, tokenizer, prep


def owner_class(core, arm):
    if arm == "common":
        return core.AdapterNativeLearnerV2
    from latent_workspace_ft_v10.slot_contrast_learner import SlotContrastNativeLearner

    return SlotContrastNativeLearner


def update_window(core, learner, store, objective, guard, log=None):
    """Same qualified arithmetic, plus detached bridge-gradient observations."""
    learner.begin_window(core.PAIRS)
    rows = []
    for world, query in core.PAIRS:
        guard(f"pair:{learner.completed_steps + 1}:{world}:{query}:before")
        loss, components = core.pair_loss(learner, store, world, query, objective, "adapter_v2")
        values = {k: float(v.detach()) for k, v in dict(loss=loss, **components).items()}
        spill = learner.backward_pair((world, query), loss)
        del loss, components
        gradients = {n: learner.window._buffers[id(p)] for n, p in learner.named}
        observed = {
            n: {
                "l2": float(gradients[f"bridge.{n}"].double().norm()),
                "nonzero": int(gradients[f"bridge.{n}"].count_nonzero()),
            }
            for n, _p in learner.bridge_named
        }
        row = dict(
            world=world,
            query=query,
            components=values,
            spill=spill,
            accumulated_gradients_sha256=core.tree_hash(gradients),
            bridge_gradients=observed,
        )
        del gradients
        rows.append(row)
        if log is not None:
            with log.open("a") as stream:
                stream.write(core.canonical(row) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        guard(f"pair:{learner.completed_steps + 1}:{world}:{query}:spilled")
    update = learner.step()
    guard(f"step:{learner.completed_steps}:updated")
    return dict(pairs=rows, update=update, state=core.state_fingerprint(learner))


def evaluate(core, learner, store, original, guard, plan):
    from latent_workspace_ft_v10.v16_comparison_eval import evaluate as evaluate_native

    learner._validate_ownership()
    before = core.state_fingerprint(learner)
    result = evaluate_native(
        learner, store, original=original, random_seed=plan["random_memory_seed"], guard=guard
    )
    require(core.state_fingerprint(learner) == before, "Evaluation mutated learner/optimizer/RNG")
    learner._validate_ownership()
    result["owned_state_fingerprint_unchanged"] = True
    return result


def primary(core, args, plan, budget, parent, objective, architecture, records, guard, seal):
    base, bridge, tokenizer, prep = fresh(core, parent, architecture, guard, args.arm, plan)
    contract = {
        **core.owned_contract(base, objective, True, seal),
        "preparation": prep,
        "plan_sha256": core.digest(ROOT / PLAN),
        "arm": args.arm,
    }
    metadata = dict(
        source_commit=seal["source_commit"],
        seal_sha256=core.digest(args.seal),
        plan_sha256=core.digest(ROOT / PLAN),
        arm=args.arm,
    )
    learner = owner_class(core, args.arm)(
        core.MistralTrainingBinding(base, 16),
        bridge,
        full_update=True,
        optimizer_config=parent["optimizer"],
        run_contract=contract,
    )
    store = core.legacy.LiveStore(learner, tokenizer, records, guard)
    context = dict(
        contract=contract,
        metadata=metadata,
        binding=learner.binding.describe(),
        features=store.feature_receipt(),
    )
    core.write_new(args.output / "CONTEXT.json", context)
    core.write_new(args.output / "INITIAL.json", core.state_fingerprint(learner))
    initial = evaluate(core, learner, store, None, guard, plan)
    core.write_new(args.output / "evaluation_step0.json", initial)
    result = dict(context=context, windows=[], checkpoints=[])
    for step in plan["steps"]:
        window = update_window(
            core, learner, store, objective, guard, args.output / f"step{step}_pairs.jsonl"
        )
        core.write_new(args.output / f"step{step}.json", window)
        result["windows"].append(window)
        report = evaluate(core, learner, store, initial["direct_base"], guard, plan)
        core.write_new(args.output / f"evaluation_step{step}.json", report)
        core.snapshot_admission(budget, guard, True)
        path = args.checkpoints / f"step{step}.pt"
        receipt = learner.save(path, metadata)
        receipt["sha256"] = core.digest(path)
        result["checkpoints"].append(receipt)
        core.write_new(args.output / f"CHECKPOINT_step{step}.json", receipt)
        print(json.dumps(dict(arm=args.arm, step=step, summary=report["summary"])), flush=True)
    return result


def replay(
    core, args, plan, budget, parent, objective, architecture, records, guard, primary_result
):
    base, bridge, tokenizer, prep = fresh(core, parent, architecture, guard, args.arm, plan)
    context = primary_result["context"]
    require(prep == context["contract"]["preparation"], "Replay preparation")
    receipt = primary_result["checkpoints"][0]
    path = args.checkpoints / receipt["path"]
    require(
        path.stat().st_size == receipt["bytes"] and core.digest(path) == receipt["sha256"],
        "Checkpoint bytes",
    )
    core.snapshot_admission(budget, guard, True)
    payload = core.torch.load(path, map_location="cpu", weights_only=True)
    learner = owner_class(core, args.arm).restore(
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
    require(store.feature_receipt() == context["features"], "Replay immutable features")
    window = update_window(
        core, learner, store, objective, guard, args.output / "replay_step2_pairs.jsonl"
    )
    core.write_new(args.output / "replay_step2.json", window)
    require(window == primary_result["windows"][1], "Exact complete next-update replay")
    core.snapshot_admission(budget, guard, True)
    state = core.tree_hash(learner.payload(context["metadata"]))
    require(
        state == primary_result["checkpoints"][1]["state_sha256"], "Exact serialized replay state"
    )
    core.write_new(
        args.output / "REPLAY.json",
        dict(exact=True, state_sha256=state, compared_pairs=16, from_step=1, execute_step=2),
    )


def run_arm(args):
    source, core, seal, check, plan, budget = preflight(args)
    qualified = qualification(args.qualification, seal, plan)
    out, ckpt = args.output.resolve(), args.checkpoints.resolve()
    require(
        not out.is_relative_to(ROOT) and not ckpt.is_relative_to(ROOT), "Outputs outside source"
    )
    require(
        out != ckpt and not out.is_relative_to(ckpt) and not ckpt.is_relative_to(out),
        "Separate outputs/checkpoints",
    )
    require(not out.exists() and not ckpt.exists(), "Fresh destinations only")
    out.mkdir(parents=True, exist_ok=False)
    ckpt.mkdir(parents=True, exist_ok=False)
    require(out.stat().st_dev == ckpt.stat().st_dev, "Same persistent filesystem")
    core.write_new(
        out / "STARTED.json",
        dict(
            pid=os.getpid(),
            arm=args.arm,
            seal=seal,
            plan=plan,
            budget=budget,
            source_check=check,
            qualification=qualified,
            output=str(out),
            checkpoints=str(ckpt),
        ),
    )
    started = time.monotonic()
    result = dict(status="INCOMPLETE_NO_RETRY", arm=args.arm, **CEILING)

    def deadline(_signal, _frame):
        raise KeyboardInterrupt("Full comparison arm wall limit")

    signal.signal(signal.SIGALRM, deadline)
    signal.setitimer(signal.ITIMER_REAL, budget["resources"]["max_elapsed_seconds"])
    try:
        core.load_runtime()
        result["runtime"] = load("run_v16_adapter_full_recovery_02").runtime(core, budget)
        parent, objective, architecture, records = core.legacy.validate()
        require(
            hashlib.sha256(inspect.getsource(core.legacy.Adafactor.step).encode()).hexdigest()
            == parent["optimizer"]["base_adafactor_step_sha256"],
            "Optimizer math changed",
        )
        guard = core.legacy.Guard(budget["resources"], out)
        remaining = len(ARMS) - ARMS.index(args.arm)
        guard(
            "admission",
            admission=True,
            forecast_bytes=remaining * plan["per_arm_storage_forecast_bytes"],
        )
        torch = core.torch
        require(torch.cuda.device_count() == 1, "One CUDA device")
        torch.cuda.set_per_process_memory_fraction(
            budget["resources"]["allocator_cap_gib"]
            * core.GIB
            / torch.cuda.get_device_properties(0).total_memory
        )
        torch.cuda.reset_peak_memory_stats()
        primary_result = primary(
            core, args, plan, budget, parent, objective, architecture, records, guard, seal
        )
        core.clean_between_arms()
        replay(
            core,
            args,
            plan,
            budget,
            parent,
            objective,
            architecture,
            records,
            guard,
            primary_result,
        )
        core.clean_between_arms()
        source.verify(ROOT, seal, ENTRY)
        require(core.identity() == seal, "Source changed")
        require(qualification(args.qualification, seal, plan) == qualified, "Qualification changed")
        result["imports"] = core.verify_imports(seal)
        guard("finished")
        result.update(
            status=PASS,
            complete_unique_windows=2,
            complete_replay_windows=1,
            complete_backward_pairs=48,
            evaluation_steps=[0, 1, 2],
        )
    except BaseException as exc:
        result.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
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
    result["elapsed_seconds"] = time.monotonic() - started
    result["peak_process_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    result["files"] = manifest(out)
    core.write_new(out / "FINISHED.json", result)
    print(json.dumps(result), flush=True)
    return int(result["status"] != PASS)


def dispatch(args):
    source, core, seal, check, plan, budget = preflight(args)
    qualified = qualification(args.qualification, seal, plan)
    require(not args.output.resolve().is_relative_to(ROOT), "Output outside source")
    out, ckpt = args.output.resolve(), args.checkpoints.resolve()
    require(not ckpt.is_relative_to(ROOT), "Checkpoints outside source")
    require(
        out != ckpt and not out.is_relative_to(ckpt) and not ckpt.is_relative_to(out),
        "Disjoint output/checkpoint roots",
    )
    require(not args.checkpoints.exists(), "Fresh checkpoint root")
    args.output.mkdir(parents=True, exist_ok=False)
    args.checkpoints.mkdir(parents=True, exist_ok=False)
    core.write_new(
        args.output / "STARTED.json",
        dict(
            pid=os.getpid(),
            seal=seal,
            plan=plan,
            source_check=check,
            qualification=qualified,
            checkpoints=str(args.checkpoints),
        ),
    )
    result = dict(status="INCOMPLETE_NO_RETRY", completed_arms=[], **CEILING)
    try:
        for arm in ARMS:
            command = [
                sys.executable,
                "-I",
                str(ROOT / "scripts/run_source_sealed.py"),
                "--seal",
                str(args.seal),
                "--entry",
                ENTRY,
                "--",
                "run-arm",
                "--seal",
                str(args.seal),
                "--arm",
                arm,
                "--output",
                str(args.output / arm),
                "--checkpoints",
                str(args.checkpoints / arm),
                "--qualification",
                str(args.qualification),
            ]
            # Log is outside the sealed arm manifest; do not include an active log in FINISHED.
            with (args.output / f"{arm}.log").open("x") as log:
                child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
                core.write_new(
                    args.output / f"DISPATCH_{arm}.json", dict(pid=child.pid, command=command)
                )
                code = child.wait()
            require(code == 0, f"{arm} exited {code}; no later arms or retry dispatched")
            require(
                read(args.output / arm / "FINISHED.json")["status"] == PASS, "Arm terminal receipt"
            )
            result["completed_arms"].append(arm)
        source.verify(ROOT, seal, ENTRY)
        result["status"] = PASS
    except BaseException as exc:
        result.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    result["files"] = manifest(args.output)
    core.write_new(args.output / "FINISHED.json", result)
    return int(result["status"] != PASS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    seal = sub.add_parser("prepare-seal")
    seal.add_argument("--output", type=Path, required=True)
    for name in ("qualify", "run-arm", "dispatch"):
        p = sub.add_parser(name)
        p.add_argument("--seal", type=Path, required=True)
        p.add_argument("--output", type=Path, required=True)
        if name == "qualify":
            p.add_argument("--device", choices=("cpu", "cuda"), required=True)
        else:
            p.add_argument("--qualification", type=Path, required=True)
            p.add_argument("--checkpoints", type=Path, required=True)
        if name == "run-arm":
            p.add_argument("--arm", choices=ARMS, required=True)
    args = parser.parse_args()
    if args.command == "prepare-seal":
        core = load("run_v16_adapter_migration")
        core.write_new(args.output, core.identity())
        return 0
    return {"qualify": qualify, "run-arm": run_arm, "dispatch": dispatch}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
