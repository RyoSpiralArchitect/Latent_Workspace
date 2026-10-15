#!/usr/bin/env python3
"""Sealed V18 frozen-backbone selection diagnostic: two matched arms and a replay.

The pinned Mistral-7B stays frozen; only the 32 workspace tensors train for 512
complete windows. Each arm and the replay own a fresh child process through the
pre-import source launcher, sequentially, stopping at the first failure. No
retry, download, generation, judge call, native update or weight deletion.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import inspect
import io
import json
import math
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
ENTRY = "scripts/run_v18_frozen_diagnostic.py"
PLAN = "configs/v18/FROZEN_DIAGNOSTIC_PLAN.json"
PLAN_CANONICAL_SHA256 = "f00c7738fcefbb4cc4cf65b95fc45868444b2409e9214f70ecd029c77bb7f55b"
ARMS = ("centered_ordered", "centered_final")
ROLES = (*ARMS, "replay")
SPLITS = ("train", "dev", "final")
PASS = "V18_FROZEN_DIAGNOSTIC_COMPLETE_NOT_FULL_UPDATE_OR_RELEASE"
TINY_PASS = "TINY_V18_FROZEN_DIAGNOSTIC_HARNESS_PASS_NOT_7B"
ARM_PASS = "V18_FROZEN_ARM_COMPLETE"
ROLE_PASS = {
    "centered_ordered": ARM_PASS,
    "centered_final": ARM_PASS,
    "replay": "V18_FROZEN_FRESH_PROCESS_EXACT_REPLAY",
}
VERDICTS = ("CONTENT_REACHES_ANSWERS", "DIRECTIONAL_ONLY", "NOT_ESTABLISHED")
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
QUALIFICATION_CASES = 16
_MODULES = {}


def load(name):
    if name not in _MODULES:
        spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        _MODULES[name] = module
    return _MODULES[name]


def pilot():
    """Sealed pure helpers (span binding, policy, occurrence IDs, exact JSON compare)."""
    return load("run_v18_native_pilot")


def read(path):
    return json.loads(Path(path).read_text())


def require(ok, message):
    if not ok:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


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


def validate_plan(plan):
    require(
        hashlib.sha256(canonical(plan).encode()).hexdigest() == PLAN_CANONICAL_SHA256,
        "Frozen V18 diagnostic plan changed",
    )
    # Defense in depth for the fields the code relies on.
    require(
        [a["name"] for a in plan["arms"]] == list(ARMS)
        and plan["full_update"] is False
        and plan["schedule"]["updates"]
        == plan["schedule"]["epochs"]
        * plan["data"]["train"]["world_pairs"]
        // plan["schedule"]["worlds_per_window"]
        and plan["endpoints"]["step"] == plan["schedule"]["updates"]
        and plan["final_evaluation_steps"][-1] == plan["schedule"]["updates"]
        and plan["qualification_cases"] == QUALIFICATION_CASES
        and all(plan[k] == v for k, v in CEILING.items()),
        "Frozen V18 diagnostic plan semantics changed",
    )


def preflight(args):
    require(sys.flags.isolated and sys.pycache_prefix, "Use isolated pre-import source launcher")
    source = load("run_source_sealed")
    seal = read(args.seal)
    check = source.verify(ROOT, seal, ENTRY)
    core = load("run_v16_adapter_migration")
    require(core.identity() == seal, "Complete source seal differs")
    plan = read(ROOT / PLAN)
    validate_plan(plan)
    require(digest(ROOT / plan["pilot_plan"]) == plan["pilot_plan_sha256"], "Pilot plan changed")
    owner_seal = ROOT / plan["qualified_owner_seal"]
    require(digest(owner_seal) == plan["qualified_owner_seal_sha256"], "Owner seal receipt")
    require(
        all(digest(ROOT / n) == h for n, h in read(owner_seal)["source_hashes"].items()),
        "Furnace-qualified V18 owner source changed",
    )
    for split in SPLITS:
        spec = plan["data"][split]
        require(digest(ROOT / spec["path"]) == spec["sha256"], f"Data changed: {split}")
    return source, core, seal, check, plan


def manifest(path):
    return {
        p.relative_to(path).as_posix(): {"bytes": p.stat().st_size, "sha256": digest(p)}
        for p in sorted(path.rglob("*"))
        if p.is_file()
    }


def offline_environment():
    for key, value in OFFLINE.items():
        os.environ[key] = value


# ---- data, schedule and endpoint arithmetic (no Torch) ------------------------


def load_records(plan):
    result = {}
    for split in SPLITS:
        path = ROOT / plan["data"][split]["path"]
        text = path.read_text()
        if path.suffix == ".jsonl":
            result[split] = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            result[split] = json.loads(text)
        require(len(result[split]) == plan["data"][split]["world_pairs"], f"{split} denominator")
    return result


def validate_data(old, records):
    """Independent symbolic-oracle labels, fixed strata and zero split overlap."""
    for split, rows in records.items():
        for record in rows:
            require(len(record["queries"]) == 8 and len(record["contexts"]) == 2, "Shape")
            for side, context in enumerate(record["contexts"]):
                for q, query in enumerate(record["queries"]):
                    expected = old.symbolic_oracle(context, query)
                    require(expected == record["answers"][side][q], f"{split} label oracle")
                    for reverse in (False, True):
                        require(
                            old.symbolic_oracle(old.canonical_facts(context, reverse), query)
                            == expected,
                            f"{split} fact serialization changed truth",
                        )
            affected = [a != b for a, b in zip(*record["answers"], strict=True)]
            require(affected == [True, True] + [False] * 6, f"{split} affected pattern")
            require(
                all(labels.count(0) == labels.count(1) == 4 for labels in record["answers"]),
                f"{split} label balance",
            )
            old.prior.unrelated_context(record)
    audit = {}
    for left, right in (("train", "dev"), ("train", "final"), ("dev", "final")):
        audit[f"{left}_{right}"] = old.prior.split_audit(records[left], records[right])
    return audit


def schedule_rows(plan, records):
    import numpy as np

    occurrence = pilot().occurrence
    width = plan["schedule"]["worlds_per_window"]
    rows = []
    for epoch, seed in enumerate(plan["schedule"]["permutation_seeds"], start=1):
        order = np.random.default_rng(seed).permutation(len(records)).tolist()
        for index, start in enumerate(range(0, len(order), width), start=1):
            worlds = order[start : start + width]
            occurrences = tuple(
                (occurrence(w, q), records[w]["answers"][0][q], records[w]["answers"][1][q])
                for w in worlds
                for q in range(len(records[w]["queries"]))
            )
            rows.append((f"v18-frozen-e{epoch}-w{index:03d}", occurrences))
    require(len(rows) == plan["schedule"]["updates"], "Schedule length")
    return rows


def binomial_upper(successes, trials):
    """Exact one-sided P(X >= successes) for X ~ Binomial(trials, 1/2)."""
    if trials == 0:
        return 1.0
    return sum(math.comb(trials, k) for k in range(successes, trials + 1)) / 2**trials


def diagnose(report, records, endpoints):
    """Pre-registered memory-content endpoints from one saved evaluation report."""
    contrasts = {(c["world"], c["query"], c["factor"]): c for c in report["contrasts"]}
    affected = sorted({(c["world"], c["query"]) for c in report["contrasts"] if c["affected"]})

    def flipped(factor):
        result = []
        for world, query in affected:
            row = contrasts[world, query, factor]
            labels = row["labels"]
            if row["left_prediction"] == labels[0] and row["right_prediction"] == labels[1]:
                result.append([world, query])
        return result

    factors = sorted({c["factor"] for c in report["contrasts"]})
    flips = {factor: flipped(factor) for factor in factors}
    sums = {}
    for world, query in affected:
        change = contrasts[world, query, "actual"]["donor_directed_gap_change"]
        sums[world] = sums.get(world, 0.0) + change
    positive = sum(v > 0 for v in sums.values())
    negative = sum(v < 0 for v in sums.values())
    p_value = binomial_upper(positive, positive + negative)
    actual, chance = len(flips["actual"]), len(flips[endpoints["chance_control"]])
    sign = p_value <= endpoints["sign_test_alpha"]
    if (
        sign
        and actual >= endpoints["minimum_actual_flips"]
        and actual - chance >= endpoints["minimum_flip_margin_over_random"]
    ):
        verdict = "CONTENT_REACHES_ANSWERS"
    elif sign:
        verdict = "DIRECTIONAL_ONLY"
    else:
        verdict = "NOT_ESTABLISHED"
    unaffected = [c for c in report["contrasts"] if c["factor"] == "actual" and not c["affected"]]
    wording = {}

    def add(key, correct, tie):
        cell = wording.setdefault(key, {"n": 0, "correct": 0, "ties": 0})
        cell["n"] += 1
        cell["correct"] += bool(correct)
        cell["ties"] += bool(tie)

    def form(world, query):
        text = records[world]["queries"][query]
        return "outrank" if text.startswith("Does ") else "ranked_above"

    for row in report["rows"]:
        if row["condition"] in ("intact", "twin"):
            add(
                f"{row['condition']}:{form(row['world'], row['query'])}",
                row["correct"],
                row["prediction"] is None,
            )
    for row in report["direct_base"]:
        for side, name in ((0, "direct_vs_intact"), (1, "direct_vs_twin")):
            add(
                f"{name}:{form(row['world'], row['query'])}",
                row["prediction"] == row["labels"][side],
                row["prediction"] is None,
            )
    return {
        "affected_queries": len(affected),
        "worlds": len(sums),
        "flips": {factor: len(rows) for factor, rows in flips.items()},
        "actual_flip_queries": flips["actual"],
        "world_sign": {
            "positive": positive,
            "negative": negative,
            "zero": len(sums) - positive - negative,
        },
        "sign_test_p": p_value,
        "sign_test_passes": sign,
        "flip_margin_over_chance": actual - chance,
        "unaffected_prediction_changes": sum(
            c["left_prediction"] != c["right_prediction"] for c in unaffected
        ),
        "accuracy_by_wording": wording,
        "verdict": verdict,
        "endpoint_definition": endpoints,
    }


def compare_arms(ordered, final, rule):
    left = {tuple(q) for q in ordered["actual_flip_queries"]}
    right = {tuple(q) for q in final["actual_flip_queries"]}
    only_ordered, only_final = len(left - right), len(right - left)
    p_value = binomial_upper(only_ordered, only_ordered + only_final)
    difference = len(left) - len(right)
    advantage = difference >= rule["minimum_flip_difference"] and p_value <= rule["mcnemar_alpha"]
    return {
        "ordered_flips": len(left),
        "final_flips": len(right),
        "both": len(left & right),
        "only_ordered": only_ordered,
        "only_final": only_final,
        "difference": difference,
        "mcnemar_one_sided_p": p_value,
        "label": rule["positive_label"] if advantage else rule["otherwise"],
        "rule": rule,
    }


# ---- tiny qualification --------------------------------------------------------


def qualify(args):
    source, core, seal, check, plan = preflight(args)
    require(not args.output.resolve().is_relative_to(ROOT), "Output must be outside source")
    args.output.mkdir(parents=True, exist_ok=False)
    write_new(
        args.output / "STARTED.json",
        dict(seal=seal, source_check=check, plan=plan, pid=os.getpid(), device=args.device),
    )
    started = time.monotonic()
    result = dict(status="INCOMPLETE_NO_RETRY", device=args.device, real_model_updates=0, **CEILING)
    try:
        offline_environment()
        os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        os.environ["LATENT_V18_FROZEN_TEST_DEVICE"] = args.device
        sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "scripts"), str(ROOT / "tests")]
        core.load_runtime()
        import pytest

        result["runtime"] = load("run_v16_adapter_full_recovery_02").runtime(core, plan)
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
    write_new(args.output / "FINISHED.json", result)
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


def reseed(seed, core):
    random.seed(seed)
    core.np.random.seed(seed)
    core.torch.manual_seed(seed)


def arm_spec(plan, name):
    return next(arm for arm in plan["arms"] if arm["name"] == name)


def schedule(plan, records):
    from latent_workspace_ft_v10.v18_window_objective import WindowReductionSpec

    data_sha256 = plan["data"]["train"]["sha256"]
    return tuple(
        WindowReductionSpec(window_id, rows, data_sha256)
        for window_id, rows in schedule_rows(plan, records)
    )


def make_contract(core, base, objective, seal, plan, arm, windows):
    return {
        "original_base_sha256": core.tree_hash(base.state_dict()),
        "original_legacy_identity_sha256": core.legacy.old.BASE_HASH,
        "objective": {"terms": objective["training"], "eos_weight": 0.0, "query_mode": "final"},
        "data": {split: dict(plan["data"][split]) for split in SPLITS},
        "schedule_sha256": core.tree_hash([w.descriptor() for w in windows]),
        "source_commit": seal["source_commit"],
        "plan_sha256": digest(ROOT / PLAN),
        "full_update": False,
        "preparation": None,
        "condition": arm["name"],
        "v18_selection_policy": pilot().policy(arm["interaction_query"]),
    }


def metadata(seal_path, seal, arm):
    return dict(
        source_commit=seal["source_commit"],
        seal_sha256=digest(seal_path),
        plan_sha256=digest(ROOT / PLAN),
        condition=arm["name"],
    )


def light_fingerprint(core, inner):
    """Owned trainable state without rehashing the frozen 7B on every window."""
    from latent_workspace_ft_v10.v15_native_learner import rng_state

    require(inner.base_optimizer is None and not inner.masters, "Frozen owner only")
    return {
        "completed_steps": inner.completed_steps,
        "bridge_state": {n: core.tree_hash(p) for n, p in inner.bridge.state_dict().items()},
        "bridge_optimizer": core.tree_hash(inner.bridge_optimizer.state_dict()),
        "rng": core.tree_hash(rng_state()),
    }


def native_versions(base):
    return [int(p._version) for p in base.parameters()]


def throttled(guard, every):
    count = [0]

    def call(phase):
        if count[0] % every == 0:
            guard(phase)
        count[0] += 1

    return call


def fresh(core, parent, architecture, guard, plan, arm):
    from latent_workspace_ft_v10.v18_selection_reader import SelectionWorkspaceBridge

    base, common, tokenizer = core.fresh_parts(False, parent, architecture, guard)
    require(
        not any(p.requires_grad for p in base.parameters()) and not base.training,
        "Frozen eval-mode backbone",
    )
    bridge = SelectionWorkspaceBridge(
        common, mode=arm["factor"], interaction_fraction=plan["interaction_fraction"]
    )
    reseed(plan["seed"], core)
    return base, bridge, tokenizer


def build_learner(core, plan, parent, objective, base, bridge, contract, windows, arm):
    from latent_workspace_ft_v10.v18_selection_window_learner import V18SelectionWindowLearner

    return V18SelectionWindowLearner(
        core.MistralTrainingBinding(base, plan["context_boundary"]),
        bridge,
        selection_policy=pilot().policy(arm["interaction_query"]),
        full_update=False,
        optimizer_config=parent["optimizer"],
        run_contract=contract,
        schedule=windows,
        reference_bank=None,
        eos_weight=plan["eos_weight"],
        eos_token_id=plan["eos_token_id"],
    )


def stores_for(core, learner, tokenizer, records, guard, splits):
    stores, spans, receipts = {}, {}, {}
    for split in splits:
        store = core.legacy.LiveStore(learner, tokenizer, records[split], guard)
        bound, receipt = pilot().bind_spans(core, store, tokenizer)
        stores[split], spans[split] = store, bound
        receipts[split] = {
            "features_sha256": core.tree_hash(store.feature_receipt()),
            "spans_sha256": core.tree_hash(receipt),
            "renderings": len(store.renderings),
            "contexts": len(store.contexts),
        }
    return stores, spans, receipts


def update_window(core, learner, store, spans, guard):
    """Owned complete-window arithmetic with light, frozen-safe receipts."""
    spec = learner.current_spec
    guard(f"window:{learner.completed_steps + 1}:before")
    learner.begin_window()
    inner = learner.inner
    parse = pilot().parse_occurrence
    rows = []
    for identifier in spec.ids:
        world, query = parse(identifier)
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
        rows.append(
            dict(
                occurrence_id=identifier,
                components=values,
                spill=spill,
                accumulated_gradients_sha256=core.tree_hash(gradients),
            )
        )
        del gradients
    update = learner.step()
    guard(f"window:{learner.completed_steps}:updated")
    return dict(
        window_id=spec.window_id,
        window_sha256=spec.descriptor()["sha256"],
        pairs=rows,
        update=update,
        state=light_fingerprint(core, inner),
    )


def evaluate(core, learner, store, spans, records, original, guard, plan):
    from latent_workspace_ft_v10.v18_native_eval import evaluate as evaluate_native

    learner._validate()
    before, versions = light_fingerprint(core, learner.inner), native_versions(learner.base)
    report = evaluate_native(
        learner,
        store,
        spans,
        original=original,
        random_seed=plan["random_memory_seed"],
        guard=throttled(guard, 64),
    )
    require(
        light_fingerprint(core, learner.inner) == before
        and native_versions(learner.base) == versions,
        "Evaluation mutated owned state, RNG or the frozen backbone",
    )
    learner._validate()
    require(
        all(
            r["full_logits_equal_current_base"] for r in report["rows"] if r["condition"] == "zero"
        ),
        "Zero memory must equal the frozen direct base exactly",
    )
    report["owned_state_fingerprint_unchanged"] = True
    report["diagnosis"] = diagnose(report, records, plan["endpoints"])
    return report


def record_evaluation(out, split, step, report):
    write_gz(out / f"eval_{split}_step{step}.json.gz", report)
    write_new(
        out / f"summary_{split}_step{step}.json",
        dict(split=split, step=step, summary=report["summary"], diagnosis=report["diagnosis"]),
    )


def arm_run(core, args, plan, parent, objective, architecture, records, guard, seal, audit):
    arm = arm_spec(plan, args.role)
    out = args.output
    base, bridge, tokenizer = fresh(core, parent, architecture, guard, plan, arm)
    windows = schedule(plan, records["train"])
    contract = make_contract(core, base, objective, seal, plan, arm, windows)
    learner = build_learner(core, plan, parent, objective, base, bridge, contract, windows, arm)
    stores, spans, receipts = stores_for(core, learner, tokenizer, records, guard, SPLITS)
    meta = metadata(args.seal, seal, arm)
    write_new(
        out / "CONTEXT.json",
        dict(
            contract=contract,
            metadata=meta,
            binding=learner.binding.describe(),
            stores=receipts,
            data_audit=audit,
            windows=len(windows),
        ),
    )
    write_new(
        out / "INITIAL.json",
        dict(
            light=light_fingerprint(core, learner.inner),
            native_sha256=contract["original_base_sha256"],
        ),
    )
    originals = {}
    for split in ("dev", "final"):
        report = evaluate(
            core, learner, stores[split], spans[split], records[split], None, guard, plan
        )
        record_evaluation(out, split, 0, report)
        originals[split] = report["direct_base"]
    dev_steps, final_steps = set(plan["dev_evaluation_steps"]), set(plan["final_evaluation_steps"])
    checkpoints, final_diagnosis = [], None
    with (out / "windows.jsonl").open("x") as journal:
        for step in range(1, plan["schedule"]["updates"] + 1):
            window = update_window(core, learner, stores["train"], spans["train"], guard)
            require(window["update"]["completed_step"] == step, "Window step")
            journal.write(canonical(window) + "\n")
            journal.flush()
            os.fsync(journal.fileno())
            for split, steps in (("dev", dev_steps), ("final", final_steps)):
                if step in steps:
                    report = evaluate(
                        core,
                        learner,
                        stores[split],
                        spans[split],
                        records[split],
                        originals[split],
                        guard,
                        plan,
                    )
                    record_evaluation(out, split, step, report)
                    if split == "final" and step == plan["endpoints"]["step"]:
                        final_diagnosis = report["diagnosis"]
                    print(
                        json.dumps(
                            dict(
                                split=split,
                                step=step,
                                verdict=report["diagnosis"]["verdict"],
                                flips=report["diagnosis"]["flips"],
                            )
                        ),
                        flush=True,
                    )
            if step in plan["checkpoint_steps"]:
                guard("before_checkpoint", forecast_bytes=GIB)
                path = args.checkpoints / arm["name"] / f"step{step}.pt"
                receipt = learner.save(path, meta)
                receipt["sha256"] = digest(path)
                checkpoints.append(receipt)
                write_new(out / f"CHECKPOINT_step{step}.json", receipt)
    native = core.tree_hash(learner.base.state_dict())
    require(native == contract["original_base_sha256"], "Frozen backbone changed")
    write_new(
        out / "FINAL_STATE.json",
        dict(
            light=light_fingerprint(core, learner.inner),
            native_sha256=native,
            native_unchanged=True,
        ),
    )
    write_new(out / "DIAGNOSIS.json", final_diagnosis)
    return dict(
        verdict=final_diagnosis["verdict"],
        flips=final_diagnosis["flips"],
        sign_test_p=final_diagnosis["sign_test_p"],
        checkpoints=checkpoints,
    )


def replay_run(core, args, plan, parent, objective, architecture, records, guard, seal, audit):
    from latent_workspace_ft_v10.v18_selection_window_learner import V18SelectionWindowLearner

    rule = plan["replay"]
    arm = arm_spec(plan, rule["arm"])
    source = args.output.parent / arm["name"]
    require(read(source / "FINISHED.json")["status"] == ARM_PASS, "Replayed arm must pass")
    context = read(source / "CONTEXT.json")
    first = read(source / f"CHECKPOINT_step{rule['from_step']}.json")
    lines = (source / "windows.jsonl").read_text().splitlines()
    expected = json.loads(lines[rule["execute_step"] - 1])
    base, bridge, tokenizer = fresh(core, parent, architecture, guard, plan, arm)
    windows = schedule(plan, records["train"])
    contract = make_contract(core, base, objective, seal, plan, arm, windows)
    meta = metadata(args.seal, seal, arm)
    same = pilot().same
    require(same(contract, context["contract"]), "Independently rebuilt run contract differs")
    require(same(meta, context["metadata"]), "Independently rebuilt metadata differs")
    path = args.checkpoints / arm["name"] / first["path"]
    require(path.stat().st_size == first["bytes"] and digest(path) == first["sha256"], "Bytes")
    payload = core.torch.load(path, map_location="cpu", weights_only=True)
    learner = V18SelectionWindowLearner.restore(
        core.MistralTrainingBinding(base, plan["context_boundary"]),
        bridge,
        payload,
        expected_selection_policy=pilot().policy(arm["interaction_query"]),
        expected_metadata=meta,
        expected_run_contract=contract,
        expected_schedule=windows,
        expected_state_sha256=first["state_sha256"],
        expected_reference_bank=None,
        eos_weight=plan["eos_weight"],
        eos_token_id=plan["eos_token_id"],
    )
    del payload
    require(learner.completed_steps == rule["from_step"], "Restored step")
    stores, spans, receipts = stores_for(core, learner, tokenizer, records, guard, ("train",))
    require(same(receipts["train"], context["stores"]["train"]), "Replay immutable train inputs")
    window = update_window(core, learner, stores["train"], spans["train"], guard)
    write_new(args.output / "replay_window.json", window)
    require(same(window, expected), "Exact complete next-window replay")
    require(
        core.tree_hash(learner.base.state_dict()) == contract["original_base_sha256"],
        "Frozen backbone changed during replay",
    )
    report = dict(
        exact=True,
        arm=arm["name"],
        from_step=rule["from_step"],
        execute_step=rule["execute_step"],
        compared_pairs=len(window["pairs"]),
        arm_pid=read(source / "STARTED.json")["pid"],
        replay_pid=os.getpid(),
    )
    require(report["arm_pid"] != report["replay_pid"], "Replay must be a fresh process")
    write_new(args.output / "REPLAY.json", report)
    return report


def run_role(args):
    source, core, seal, check, plan = preflight(args)
    qualified = qualification(args.qualification, seal, plan)
    out, ckpt = args.output.resolve(), args.checkpoints.resolve()
    require(not out.is_relative_to(ROOT) and not ckpt.is_relative_to(ROOT), "Outside source")
    require(
        out != ckpt and not out.is_relative_to(ckpt) and not ckpt.is_relative_to(out),
        "Separate outputs/checkpoints",
    )
    require(not out.exists(), "Fresh role output only")
    out.mkdir(parents=True, exist_ok=False)
    if args.role in ARMS:
        require(not (ckpt / args.role).exists(), "Fresh checkpoint destination only")
        (ckpt / args.role).mkdir(parents=True, exist_ok=False)
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
    result = dict(status="INCOMPLETE_NO_RETRY", role=args.role, **CEILING)

    def deadline(_signal, _frame):
        raise KeyboardInterrupt("V18 frozen diagnostic process wall limit")

    signal.signal(signal.SIGALRM, deadline)
    signal.setitimer(signal.ITIMER_REAL, plan["resources"]["max_elapsed_seconds"])
    try:
        offline_environment()
        core.load_runtime()
        result["runtime"] = load("run_v16_adapter_full_recovery_02").runtime(core, plan)
        parent, objective, architecture, _ = core.legacy.validate()
        require(
            hashlib.sha256(inspect.getsource(core.legacy.Adafactor.step).encode()).hexdigest()
            == parent["optimizer"]["base_adafactor_step_sha256"],
            "Optimizer math changed",
        )
        records = load_records(plan)
        audit = validate_data(core.legacy.old, records)
        guard = core.legacy.Guard(plan["resources"], out)
        guard("admission", admission=True, forecast_bytes=plan["storage_forecast_bytes"])
        torch = core.torch
        require(torch.cuda.device_count() == 1, "One CUDA device")
        torch.cuda.set_per_process_memory_fraction(
            plan["resources"]["allocator_cap_gib"]
            * GIB
            / torch.cuda.get_device_properties(0).total_memory
        )
        torch.cuda.reset_peak_memory_stats()
        args.output = out
        call = replay_run if args.role == "replay" else arm_run
        result["outcome"] = call(
            core, args, plan, parent, objective, architecture, records, guard, seal, audit
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
    write_new(out / "FINISHED.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "files"}), flush=True)
    return int(result["status"] != ROLE_PASS[args.role])


def dispatch(args):
    source, core, seal, check, plan = preflight(args)
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
            ]
            # The live log stays outside each role's sealed manifest.
            with (out / f"{role}.log").open("x") as log:
                child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
                write_new(out / f"DISPATCH_{role}.json", dict(pid=child.pid, command=command))
                code = child.wait()
            require(code == 0, f"{role} exited {code}; no later role or retry dispatched")
            require(read(out / role / "FINISHED.json")["status"] == ROLE_PASS[role], "Role receipt")
            result["completed_roles"].append(role)
        selection = compare_arms(
            read(out / "centered_ordered" / "DIAGNOSIS.json"),
            read(out / "centered_final" / "DIAGNOSIS.json"),
            plan["endpoints"]["selection_comparison"],
        )
        write_new(out / "SELECTION.json", selection)
        source.verify(ROOT, seal, ENTRY)
        result.update(
            status=PASS,
            verdicts={a: read(out / a / "DIAGNOSIS.json")["verdict"] for a in ARMS},
            selection=selection["label"],
        )
    except BaseException as exc:
        result.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    result["elapsed_seconds"] = time.monotonic() - started
    result["files"] = manifest(out)
    write_new(out / "FINISHED.json", result)
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
    args = parser.parse_args()
    if args.command == "prepare-seal":
        core = load("run_v16_adapter_migration")
        validate_plan(read(ROOT / PLAN))
        write_new(args.output, core.identity())
        return 0
    return {"qualify": qualify, "run-role": run_role, "dispatch": dispatch}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
