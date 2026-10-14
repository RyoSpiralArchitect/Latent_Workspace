#!/usr/bin/env python3
"""Sealed V18 native selection pilot: V16 parity probe, one full-update arm, replay.

The dispatcher never imports Torch. Probe, primary and replay each own a fresh
child process through the pre-import source launcher, run sequentially and stop
at the first failure. No retry, download, generation, judge call or deletion.
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
ENTRY = "scripts/run_v18_native_pilot.py"
PLAN = "configs/v18/NATIVE_PILOT_PLAN.json"
ROLES = ("probe", "primary", "replay")
PASS = "BOUNDED_V18_NATIVE_PILOT_COMPLETE_NOT_SEMANTIC_QUALIFICATION"
TINY_PASS = "TINY_V18_NATIVE_PILOT_HARNESS_PASS_NOT_7B"
ROLE_PASS = {
    "probe": "V18_FINAL_QUERY_EXACT_V16_PARITY",
    "primary": "V18_CENTERED_ORDERED_FULL_UPDATE_TWO_WINDOWS_COMPLETE",
    "replay": "V18_FRESH_PROCESS_EXACT_NEXT_WINDOW_REPLAY",
}
CEILING = dict(
    new_sequences=0,
    judge_calls=0,
    weight_deletions=0,
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
QUALIFICATION_CASES = 18
_MODULES = {}


def load(name):
    if name not in _MODULES:
        spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        _MODULES[name] = module
    return _MODULES[name]


def read(path):
    return json.loads(Path(path).read_text())


def require(ok, message):
    if not ok:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def same(left, right):
    """Exact equality after the JSON round trip every saved receipt takes."""
    return canonical(json.loads(canonical(left))) == canonical(json.loads(canonical(right)))


def expected_plan():
    windows = ["v18-native-pilot-01-step1", "v18-native-pilot-01-step2"]
    return {
        "schema": "v18-native-selection-pilot-v1",
        "budget_plan": "configs/v16/ADAPTER_MIGRATION_PLAN.json",
        "parent": "configs/v15/NATIVE_LEARNER_PLAN.json",
        "qualified_owner_seal": (
            "provenance/pilots/v18_selection_window_20261015/raw/SOURCE_SEAL.json"
        ),
        "qualified_owner_seal_sha256": (
            "c1fbcdebd6322c108ac5eacbcdac9d494e3fa37a2d8e24cbcbc02f96e09444cc"
        ),
        "training_data": "data/v10/functional_train.jsonl",
        "training_data_sha256": (
            "8ca42ca2908a3d554849b6fb0054f838c424fdfed48ca478bbac7174740feea3"
        ),
        "seed": 47,
        "worlds": [0, 1],
        "queries": list(range(8)),
        "occurrence_order": "world_major",
        "context_boundary": 16,
        "eos_weight": 0.0,
        "eos_token_id": 2,
        "reference_bank": None,
        "condition": {
            "name": "centered_ordered",
            "factor": "slot_contrast",
            "interaction_query": "ordered_difference",
            "interaction_fraction": 0.25,
            "full_update": True,
            "window_ids": windows,
        },
        "probe": {
            "name": "centered_final_v16_parity",
            "factor": "slot_contrast",
            "interaction_query": "final",
            "interaction_fraction": 0.25,
            "full_update": True,
            "window_ids": ["v18-native-pilot-01-final-parity-step1"],
            "executed_windows": 1,
            "checkpoints": 0,
            "comparator": "provenance/pilots/v16_full_comparison_20261014/raw/slot_contrast",
            "comparator_sha256": {
                "CONTEXT.json": "3be8e20dc81959571aae94d44cf39fb58a1e03a1f5daf7f7c8e4d123f24a5dc0",
                "INITIAL.json": "d01c43e0efaacdf0226af65d463cdfd4b9ba19b75c75d4d4958ecf759987f9dd",
                "evaluation_step0.json": (
                    "1cd1aff3a3d5009bcade2292f6e86c3da2c6eb3915a21ed591c4d550b75adb38"
                ),
                "step1.json": "fc8c03a8340313d1b77afe9bb14b8b1b4ef93c842de313a65095686038a5e84a",
            },
            "comparison": (
                "exact_original_hash_preparation_binding_features_initial_state_then_every_"
                "pair_components_without_total_spill_gradient_hash_bridge_gradients_update_"
                "and_state"
            ),
            "gate": "any_mismatch_stops_before_primary",
        },
        "steps": [1, 2],
        "evaluation_steps": [0, 1, 2],
        "checkpoint_steps": [1, 2],
        "replay": {"from_step": 1, "execute_step": 2, "process": "fresh_interpreter"},
        "random_memory_seed": 470016,
        "evaluation_rows_per_step": 160,
        "direct_base_rows_per_step": 16,
        "factor_rows_per_step": 80,
        "planned_unique_windows": 3,
        "planned_replay_windows": 1,
        "planned_backward_pairs": 64,
        "storage_forecast_bytes": 64 * GIB,
        "process_policy": "sequential_fresh_processes_probe_primary_replay_stop_on_first_failure",
        "arithmetic": "unchanged_native_bf16_base_fp32_bridge_cpu_native_gradient_accumulation",
        "training_rng": "reseed_47_after_reader_construction",
        "diagnostics": "no_grad_no_mode_switch_no_global_rng_draw_state_fingerprint_unchanged",
        "qualification_test_files": ["tests/test_v18_native_pilot.py"],
        "qualification_cases": QUALIFICATION_CASES,
        "qualification_wall_seconds": 900,
        "qualification_gpu_limit_gib": 4,
        "no_retry": True,
        **CEILING,
        "scope": (
            "First real Mistral-7B full-parameter update with the qualified V18 selection "
            "window owner: one centered-ordered condition on the two exposed V16 training "
            "worlds, matched to the V16 slot-contrast arm; bounded engineering and mechanism "
            "pilot, not held-out generalization, base-floor qualification or a release candidate"
        ),
    }


def validate_plan(plan):
    require(plan == expected_plan(), "Frozen V18 native pilot plan changed")


def preflight(args):
    require(sys.flags.isolated and sys.pycache_prefix, "Use isolated pre-import source launcher")
    source = load("run_source_sealed")
    seal = read(args.seal)
    check = source.verify(ROOT, seal, ENTRY)
    core = load("run_v16_adapter_migration")
    require(core.identity() == seal, "Complete source seal differs")
    plan = read(ROOT / PLAN)
    validate_plan(plan)
    budget = read(ROOT / plan["budget_plan"])
    core.validate_plan(budget)
    owner_seal = ROOT / plan["qualified_owner_seal"]
    require(core.digest(owner_seal) == plan["qualified_owner_seal_sha256"], "Owner seal receipt")
    require(
        all(
            core.digest(ROOT / name) == digest
            for name, digest in read(owner_seal)["source_hashes"].items()
        ),
        "Furnace-qualified V18 owner source changed",
    )
    comparator = ROOT / plan["probe"]["comparator"]
    for name, digest in plan["probe"]["comparator_sha256"].items():
        require(core.digest(comparator / name) == digest, f"V16 comparator changed: {name}")
    require(core.digest(ROOT / plan["training_data"]) == plan["training_data_sha256"], "Data")
    return source, core, seal, check, plan, budget


def manifest(path):
    core = load("run_v16_adapter_migration")
    return {
        p.relative_to(path).as_posix(): {"bytes": p.stat().st_size, "sha256": core.digest(p)}
        for p in sorted(path.rglob("*"))
        if p.is_file()
    }


def offline_environment():
    for key, value in OFFLINE.items():
        os.environ[key] = value


def qualify(args):
    source, core, seal, check, plan, budget = preflight(args)
    require(not args.output.resolve().is_relative_to(ROOT), "Output must be outside source")
    args.output.mkdir(parents=True, exist_ok=False)
    core.write_new(
        args.output / "STARTED.json",
        dict(seal=seal, source_check=check, plan=plan, pid=os.getpid(), device=args.device),
    )
    started = time.monotonic()
    result = dict(status="INCOMPLETE_NO_RETRY", device=args.device, real_model_updates=0, **CEILING)
    try:
        offline_environment()
        os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        os.environ["LATENT_V18_PILOT_TEST_DEVICE"] = args.device
        sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "scripts"), str(ROOT / "tests")]
        core.load_runtime()
        import pytest

        result["runtime"] = load("run_v16_adapter_full_recovery_02").runtime(core, budget)
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
        if args.device == "cuda":
            peak = core.torch.cuda.max_memory_allocated()
            require(0 < peak <= plan["qualification_gpu_limit_gib"] * GIB, "Tiny CUDA envelope")
            result["peak_cuda_allocated_bytes"] = peak
        result["status"] = TINY_PASS
    except BaseException as exc:
        result.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    result["elapsed_seconds"] = time.monotonic() - started
    result["files"] = manifest(args.output)
    core.write_new(args.output / "FINISHED.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "files"}), flush=True)
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


# ---- model-side helpers (called only after core.load_runtime) -----------------


def policy(mode):
    from latent_workspace_ft_v10.v18_selection_learner import POLICY_FORMAT

    return {"schema": POLICY_FORMAT, "interaction_query": mode}


def occurrence(world, query):
    return f"world{world}-query{query}"


def parse_occurrence(identifier):
    world, query = identifier.removeprefix("world").split("-query")
    return int(world), int(query)


def schedule(records, plan, window_ids, data_sha256):
    from latent_workspace_ft_v10.v18_window_objective import WindowReductionSpec

    rows = tuple(
        (occurrence(w, q), records[w]["answers"][0][q], records[w]["answers"][1][q])
        for w in plan["worlds"]
        for q in plan["queries"]
    )
    return tuple(WindowReductionSpec(window_id, rows, data_sha256) for window_id in window_ids)


def fresh(core, parent, architecture, guard, plan, spec):
    from latent_workspace_ft_v10.v18_selection_reader import SelectionWorkspaceBridge

    base, common, tokenizer, preparation = load("run_v16_adapter_full_recovery_02").fresh(
        core, parent, architecture, guard
    )
    bridge = SelectionWorkspaceBridge(
        common, mode=spec["factor"], interaction_fraction=spec["interaction_fraction"]
    )
    # Reader construction consumes RNG; every training draw starts from the seed.
    random.seed(plan["seed"])
    core.np.random.seed(plan["seed"])
    core.torch.manual_seed(plan["seed"])
    return base, bridge, tokenizer, preparation


def make_contract(core, base, objective, seal, plan, preparation, spec):
    return {
        "original_base_sha256": core.tree_hash(base.state_dict()),
        "original_legacy_identity_sha256": core.legacy.old.BASE_HASH,
        "objective": {"terms": objective["training"], "eos_weight": 0.0, "query_mode": "final"},
        "data": {
            "pairs": [[w, q] for w in plan["worlds"] for q in plan["queries"]],
            "training_sha256": plan["training_data_sha256"],
            "records": "first two validated functional_train rows",
        },
        "source_commit": seal["source_commit"],
        "plan_sha256": core.digest(ROOT / PLAN),
        "full_update": spec["full_update"],
        "preparation": preparation,
        "condition": spec["name"],
        "v18_selection_policy": policy(spec["interaction_query"]),
    }


def metadata(core, seal_path, seal, spec):
    return dict(
        source_commit=seal["source_commit"],
        seal_sha256=core.digest(seal_path),
        plan_sha256=core.digest(ROOT / PLAN),
        condition=spec["name"],
    )


def bind_spans(core, store, tokenizer):
    from latent_workspace_ft_v10.v18_operand_query import bind_operand_span

    spans, receipt = {}, []
    for (world, query), row in sorted(store.renderings.items()):
        span = bind_operand_span(
            tokenizer,
            raw_query=store.records[world]["queries"][query],
            rendered_prefix=row["text"],
            expected_prefix_ids=row["prompt_ids"],
        )
        require(span.question_span == core.legacy.old.bound_span(row), "Question span drift")
        require(span.prefix_ids == tuple(row["prompt_ids"]), "Operand prefix drift")
        spans[world, query] = span
        receipt.append(
            dict(
                world=world,
                query=query,
                subject=span.subject,
                object=span.object,
                subject_token_indices=list(span.subject_token_indices),
                object_token_indices=list(span.object_token_indices),
                question_token_indices=list(span.question_span.token_indices),
            )
        )
    return spans, receipt


def build(core, plan, parent, objective, architecture, records, guard, seal, spec, window_ids):
    from latent_workspace_ft_v10.v18_selection_window_learner import V18SelectionWindowLearner

    base, bridge, tokenizer, preparation = fresh(core, parent, architecture, guard, plan, spec)
    windows = schedule(records, plan, window_ids, plan["training_data_sha256"])
    contract = make_contract(core, base, objective, seal, plan, preparation, spec)
    learner = V18SelectionWindowLearner(
        core.MistralTrainingBinding(base, plan["context_boundary"]),
        bridge,
        selection_policy=policy(spec["interaction_query"]),
        full_update=spec["full_update"],
        optimizer_config=parent["optimizer"],
        run_contract=contract,
        schedule=windows,
        reference_bank=None,
        eos_weight=plan["eos_weight"],
        eos_token_id=plan["eos_token_id"],
    )
    store = core.legacy.LiveStore(learner, tokenizer, records, guard)
    spans, span_receipt = bind_spans(core, store, tokenizer)
    return learner, store, spans, span_receipt, windows, contract, preparation


def update_window(core, learner, store, spans, guard, log=None):
    """Owned complete-window arithmetic, plus detached gradient observations."""
    spec = learner.current_spec
    learner.begin_window()
    inner = learner.inner
    rows = []
    for identifier in spec.ids:
        world, query = parse_occurrence(identifier)
        guard(f"pair:{learner.completed_steps + 1}:{world}:{query}:before")
        row = store.renderings[world, query]
        components, spill = learner.backward_pair(
            identifier,
            write_memory=lambda side, world=world: store.write(learner.bridge, world, side),
            prefix_ids=tuple(row["prompt_ids"]),
            span=spans[world, query],
            candidate_ids=tuple(row["candidate_ids"]),
        )
        values = {k: float(v.detach()) for k, v in components.items()}
        del components
        gradients = {n: inner.window._buffers[id(p)] for n, p in inner.named}
        observed = {
            n: {
                "l2": float(gradients[f"bridge.{n}"].double().norm()),
                "nonzero": int(gradients[f"bridge.{n}"].count_nonzero()),
            }
            for n, _p in inner.bridge_named
        }
        result = dict(
            world=world,
            query=query,
            occurrence_id=identifier,
            components=values,
            spill=spill,
            accumulated_gradients_sha256=core.tree_hash(gradients),
            bridge_gradients=observed,
        )
        del gradients
        rows.append(result)
        if log is not None:
            with log.open("a") as stream:
                stream.write(core.canonical(result) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        guard(f"pair:{learner.completed_steps + 1}:{world}:{query}:spilled")
    update = learner.step()
    guard(f"step:{learner.completed_steps}:updated")
    return dict(
        window=spec.descriptor(),
        pairs=rows,
        update=update,
        state=core.state_fingerprint(inner),
    )


def evaluate(core, learner, store, spans, original, guard, plan):
    from latent_workspace_ft_v10.v18_native_eval import evaluate as evaluate_native

    learner._validate()
    before = core.state_fingerprint(learner.inner)
    result = evaluate_native(
        learner,
        store,
        spans,
        original=original,
        random_seed=plan["random_memory_seed"],
        guard=guard,
    )
    require(
        core.state_fingerprint(learner.inner) == before, "Evaluation mutated learner/optimizer/RNG"
    )
    learner._validate()
    result["owned_state_fingerprint_unchanged"] = True
    return result


def compare_v16_window(ours, theirs):
    """Field-level exact agreement with a historical V16 window receipt."""
    checks = {
        "pair_count": len(ours["pairs"]) == len(theirs["pairs"]),
        "update": same(ours["update"], theirs["update"]),
        "state": same(ours["state"], theirs["state"]),
        "pairs": [],
    }
    for mine, old in zip(ours["pairs"], theirs["pairs"]):
        expected = {k: v for k, v in old["components"].items() if k != "loss"}
        checks["pairs"].append(
            {
                "world": mine["world"] == old["world"],
                "query": mine["query"] == old["query"],
                "components": same(mine["components"], expected),
                "spill": same(mine["spill"], old["spill"]),
                "accumulated_gradients_sha256": mine["accumulated_gradients_sha256"]
                == old["accumulated_gradients_sha256"],
                "bridge_gradients": same(mine["bridge_gradients"], old["bridge_gradients"]),
            }
        )
    return checks


def all_true(value):
    if isinstance(value, dict):
        return bool(value) and all(all_true(v) for v in value.values())
    if isinstance(value, list):
        return bool(value) and all(all_true(v) for v in value)
    return value is True


def compare_v16_evaluation(ours, theirs):
    """Non-gating step-0 check: shared V16 fields of every evaluation record."""

    def strip(rows, keys):
        return [{k: r[k] for k in keys} for r in rows]

    keys = list(theirs["rows"][0])
    return {
        "rows": len(ours["rows"]) == len(theirs["rows"])
        and same(strip(ours["rows"], keys), theirs["rows"]),
        "contrasts": same(ours["contrasts"], theirs["contrasts"]),
        "direct_base": same(ours["direct_base"], theirs["direct_base"]),
        "memories": same(ours["memories"], theirs["memories"]),
    }


def probe(core, args, plan, parent, objective, architecture, records, guard, seal):
    spec = plan["probe"]
    comparator = ROOT / spec["comparator"]
    old_context = read(comparator / "CONTEXT.json")
    old_initial = read(comparator / "INITIAL.json")
    old_step = read(comparator / "step1.json")
    learner, store, spans, span_receipt, windows, contract, preparation = build(
        core, plan, parent, objective, architecture, records, guard, seal, spec, spec["window_ids"]
    )
    context = dict(
        contract=contract,
        metadata=metadata(core, args.seal, seal, spec),
        binding=learner.binding.describe(),
        features=store.feature_receipt(),
        spans=span_receipt,
        schedule=[w.descriptor() for w in windows],
    )
    core.write_new(args.output / "CONTEXT.json", context)
    initial = core.state_fingerprint(learner.inner)
    core.write_new(args.output / "INITIAL.json", initial)
    checks = {
        "original_base_sha256": contract["original_base_sha256"]
        == old_context["contract"]["original_base_sha256"],
        "preparation": same(preparation, old_context["contract"]["preparation"]),
        "binding": same(context["binding"], old_context["binding"]),
        "features": same(context["features"], old_context["features"]),
        "initial_state": same(initial, old_initial),
    }
    window = update_window(
        core, learner, store, spans, guard, args.output / "probe_step1_pairs.jsonl"
    )
    core.write_new(args.output / "probe_step1.json", window)
    checks["window"] = compare_v16_window(window, old_step)
    passed = all_true(checks)
    core.write_new(args.output / "PROBE.json", dict(checks=checks, exact_v16_parity=passed))
    require(passed, "V18 final-query probe differs from the V16 slot-contrast receipt")
    return dict(exact_v16_parity=True, compared_pairs=len(window["pairs"]))


def primary(core, args, plan, budget, parent, objective, architecture, records, guard, seal):
    spec = plan["condition"]
    learner, store, spans, span_receipt, windows, contract, _ = build(
        core, plan, parent, objective, architecture, records, guard, seal, spec, spec["window_ids"]
    )
    meta = metadata(core, args.seal, seal, spec)
    context = dict(
        contract=contract,
        metadata=meta,
        binding=learner.binding.describe(),
        features=store.feature_receipt(),
        spans=span_receipt,
        schedule=[w.descriptor() for w in windows],
    )
    core.write_new(args.output / "CONTEXT.json", context)
    core.write_new(args.output / "INITIAL.json", core.state_fingerprint(learner.inner))
    initial = evaluate(core, learner, store, spans, None, guard, plan)
    core.write_new(args.output / "evaluation_step0.json", initial)
    old_step0 = read(ROOT / plan["probe"]["comparator"] / "evaluation_step0.json")
    core.write_new(
        args.output / "STEP0_V16_EVALUATION_PARITY.json",
        dict(checks=compare_v16_evaluation(initial, old_step0), gating=False),
    )
    result = dict(windows=[], checkpoints=[])
    checkpoints = args.checkpoints / "primary"
    for step in plan["steps"]:
        window = update_window(
            core, learner, store, spans, guard, args.output / f"step{step}_pairs.jsonl"
        )
        core.write_new(args.output / f"step{step}.json", window)
        result["windows"].append(window["update"]["completed_step"])
        report = evaluate(core, learner, store, spans, initial["direct_base"], guard, plan)
        core.write_new(args.output / f"evaluation_step{step}.json", report)
        core.snapshot_admission(budget, guard, True)
        path = checkpoints / f"step{step}.pt"
        receipt = learner.save(path, meta)
        receipt["sha256"] = core.digest(path)
        result["checkpoints"].append(receipt)
        core.write_new(args.output / f"CHECKPOINT_step{step}.json", receipt)
        print(json.dumps(dict(step=step, summary=report["summary"])), flush=True)
    return result


def replay(core, args, plan, budget, parent, objective, architecture, records, guard, seal):
    from latent_workspace_ft_v10.v18_selection_window_learner import V18SelectionWindowLearner

    spec = plan["condition"]
    source = args.primary
    context = read(source / "CONTEXT.json")
    first = read(source / "CHECKPOINT_step1.json")
    last = read(source / "CHECKPOINT_step2.json")
    expected = read(source / "step2.json")
    base, bridge, tokenizer, preparation = fresh(core, parent, architecture, guard, plan, spec)
    windows = schedule(records, plan, spec["window_ids"], plan["training_data_sha256"])
    contract = make_contract(core, base, objective, seal, plan, preparation, spec)
    meta = metadata(core, args.seal, seal, spec)
    require(same(contract, context["contract"]), "Independently rebuilt run contract differs")
    require(same(meta, context["metadata"]), "Independently rebuilt metadata differs")
    require(
        same([w.descriptor() for w in windows], context["schedule"]), "Rebuilt schedule differs"
    )
    path = args.checkpoints / "primary" / first["path"]
    require(
        path.stat().st_size == first["bytes"] and core.digest(path) == first["sha256"],
        "Checkpoint bytes",
    )
    core.snapshot_admission(budget, guard, True)
    payload = core.torch.load(path, map_location="cpu", weights_only=True)
    learner = V18SelectionWindowLearner.restore(
        core.MistralTrainingBinding(base, plan["context_boundary"]),
        bridge,
        payload,
        expected_selection_policy=policy(spec["interaction_query"]),
        expected_metadata=meta,
        expected_run_contract=contract,
        expected_schedule=windows,
        expected_state_sha256=first["state_sha256"],
        expected_reference_bank=None,
        eos_weight=plan["eos_weight"],
        eos_token_id=plan["eos_token_id"],
    )
    del payload
    gc.collect()
    require(learner.completed_steps == plan["replay"]["from_step"], "Restored step")
    store = core.legacy.LiveStore(learner, tokenizer, records, guard)
    spans, span_receipt = bind_spans(core, store, tokenizer)
    require(same(store.feature_receipt(), context["features"]), "Replay immutable features")
    require(same(span_receipt, context["spans"]), "Replay operand bindings")
    window = update_window(
        core, learner, store, spans, guard, args.output / "replay_step2_pairs.jsonl"
    )
    core.write_new(args.output / "replay_step2.json", window)
    require(same(window, expected), "Exact complete next-window replay")
    core.snapshot_admission(budget, guard, True)
    state = core.tree_hash(learner.payload(meta))
    require(state == last["state_sha256"], "Exact serialized replay state")
    report = dict(
        exact=True,
        state_sha256=state,
        compared_pairs=len(window["pairs"]),
        from_step=plan["replay"]["from_step"],
        execute_step=plan["replay"]["execute_step"],
        primary_pid=read(source / "STARTED.json")["pid"],
        replay_pid=os.getpid(),
    )
    require(report["primary_pid"] != report["replay_pid"], "Replay must be a fresh process")
    core.write_new(args.output / "REPLAY.json", report)
    return report


def run_role(args):
    source, core, seal, check, plan, budget = preflight(args)
    qualified = qualification(args.qualification, seal, plan)
    out, ckpt = args.output.resolve(), args.checkpoints.resolve()
    require(not out.is_relative_to(ROOT) and not ckpt.is_relative_to(ROOT), "Outside source")
    require(
        out != ckpt and not out.is_relative_to(ckpt) and not ckpt.is_relative_to(out),
        "Separate outputs/checkpoints",
    )
    require(not out.exists(), "Fresh role output only")
    out.mkdir(parents=True, exist_ok=False)
    if args.role == "primary":
        require(not (ckpt / "primary").exists(), "Fresh checkpoint destination only")
        (ckpt / "primary").mkdir(parents=True, exist_ok=False)
        require(out.stat().st_dev == (ckpt / "primary").stat().st_dev, "Same filesystem")
    if args.role == "replay":
        require(args.primary is not None and (args.primary / "FINISHED.json").is_file(), "Primary")
        require(read(args.primary / "FINISHED.json")["status"] == ROLE_PASS["primary"], "Primary")
    core.write_new(
        out / "STARTED.json",
        dict(
            pid=os.getpid(),
            role=args.role,
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
    result = dict(status="INCOMPLETE_NO_RETRY", role=args.role, **CEILING)

    def deadline(_signal, _frame):
        raise KeyboardInterrupt("V18 native pilot process wall limit")

    signal.signal(signal.SIGALRM, deadline)
    signal.setitimer(signal.ITIMER_REAL, budget["resources"]["max_elapsed_seconds"])
    try:
        offline_environment()
        core.load_runtime()
        result["runtime"] = load("run_v16_adapter_full_recovery_02").runtime(core, budget)
        parent, objective, architecture, records = core.legacy.validate()
        require(
            hashlib.sha256(inspect.getsource(core.legacy.Adafactor.step).encode()).hexdigest()
            == parent["optimizer"]["base_adafactor_step_sha256"],
            "Optimizer math changed",
        )
        guard = core.legacy.Guard(budget["resources"], out)
        forecast = plan["storage_forecast_bytes"] if args.role == "primary" else 0
        guard("admission", admission=True, forecast_bytes=forecast)
        torch = core.torch
        require(torch.cuda.device_count() == 1, "One CUDA device")
        torch.cuda.set_per_process_memory_fraction(
            budget["resources"]["allocator_cap_gib"]
            * GIB
            / torch.cuda.get_device_properties(0).total_memory
        )
        torch.cuda.reset_peak_memory_stats()
        args.output = out
        call = {"probe": probe, "primary": primary, "replay": replay}[args.role]
        if args.role == "probe":
            result["outcome"] = call(
                core, args, plan, parent, objective, architecture, records, guard, seal
            )
        else:
            result["outcome"] = call(
                core, args, plan, budget, parent, objective, architecture, records, guard, seal
            )
        core.clean_between_arms()
        source.verify(ROOT, seal, ENTRY)
        require(core.identity() == seal, "Source changed")
        require(qualification(args.qualification, seal, plan) == qualified, "Qualification")
        result["imports"] = core.verify_imports(seal)
        guard("finished")
        result["status"] = ROLE_PASS[args.role]
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
    print(json.dumps({k: v for k, v in result.items() if k != "files"}), flush=True)
    return int(result["status"] != ROLE_PASS[args.role])


def dispatch(args):
    source, core, seal, check, plan, budget = preflight(args)
    qualified = qualification(args.qualification, seal, plan)
    out, ckpt = args.output.resolve(), args.checkpoints.resolve()
    require(not out.is_relative_to(ROOT) and not ckpt.is_relative_to(ROOT), "Outside source")
    require(
        out != ckpt and not out.is_relative_to(ckpt) and not ckpt.is_relative_to(out),
        "Disjoint output/checkpoint roots",
    )
    require(not out.exists() and not ckpt.exists(), "Fresh destinations only")
    out.mkdir(parents=True, exist_ok=False)
    ckpt.mkdir(parents=True, exist_ok=False)
    core.write_new(
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
    result = dict(status="INCOMPLETE_NO_RETRY", completed_roles=[], **CEILING)
    try:
        for role in ROLES:
            command = [
                sys.executable,
                "-I",
                str(ROOT / "scripts/run_source_sealed.py"),
                "--seal",
                str(args.seal),
                "--entry",
                ENTRY,
                "--",
                "run-role",
                "--role",
                role,
                "--seal",
                str(args.seal),
                "--output",
                str(out / role),
                "--checkpoints",
                str(ckpt),
                "--qualification",
                str(args.qualification),
                "--primary",
                str(out / "primary"),
            ]
            # The live log stays outside each role's sealed manifest.
            with (out / f"{role}.log").open("x") as log:
                child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
                core.write_new(out / f"DISPATCH_{role}.json", dict(pid=child.pid, command=command))
                code = child.wait()
            require(code == 0, f"{role} exited {code}; no later role or retry dispatched")
            require(read(out / role / "FINISHED.json")["status"] == ROLE_PASS[role], "Role receipt")
            result["completed_roles"].append(role)
        source.verify(ROOT, seal, ENTRY)
        result.update(
            status=PASS,
            complete_unique_windows=plan["planned_unique_windows"],
            complete_replay_windows=plan["planned_replay_windows"],
            complete_backward_pairs=plan["planned_backward_pairs"],
        )
    except BaseException as exc:
        result.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    result["files"] = manifest(out)
    core.write_new(out / "FINISHED.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "files"}), flush=True)
    return int(result["status"] != PASS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
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
            p.add_argument("--role", choices=ROLES, required=True)
            p.add_argument("--primary", type=Path)
    args = parser.parse_args()
    if args.command == "prepare-seal":
        core = load("run_v16_adapter_migration")
        validate_plan(read(ROOT / PLAN))
        core.write_new(args.output, core.identity())
        return 0
    return {"qualify": qualify, "run-role": run_role, "dispatch": dispatch}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
