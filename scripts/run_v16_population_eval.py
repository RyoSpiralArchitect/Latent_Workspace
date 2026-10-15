#!/usr/bin/env python3
"""Source-isolated evaluation of existing V16 weights. No training or automatic retry."""

from __future__ import annotations

import argparse
import gc
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
ENTRY = "scripts/run_v16_population_eval.py"
PLAN = "configs/v16/POPULATION_EVAL_PLAN.json"
INPUTS = "configs/v16/population_20261015"
TESTS = ["tests/test_v16_population_eval.py"]
PASS = "POPULATION_EVALUATION_COMPLETE_NOT_QUALIFICATION"
TINY_PASS = "TINY_POPULATION_HARNESS_PASS"
CEILING = dict(
    new_training_updates=0,
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


def inputs(core, plan):
    directory = ROOT / INPUTS
    manifest = read(directory / "INPUTS.json")
    require(manifest["plan_sha256"] == core.digest(ROOT / PLAN), "Input/plan identity")
    require(set(manifest["files"]) == {"functional.json", "mmlu.json"}, "Input file coverage")
    for name, sha in manifest["files"].items():
        require(core.digest(directory / name) == sha, "Frozen input bytes")
    worlds, mmlu = [read(directory / f"{name}.json") for name in ("functional", "mmlu")]
    require(len(worlds) == plan["functional_worlds"], "World denominator")
    require(sum(len(w["queries"]) for w in worlds) == plan["functional_queries"], "Query count")
    require(sum(sum(w["affected"]) for w in worlds) == plan["affected_queries"], "Affected count")
    require(len(mmlu) == plan["mmlu"]["n"], "MMLU denominator")
    return worlds, mmlu, manifest


def preflight(args):
    require(sys.flags.isolated and sys.pycache_prefix, "Use sealed isolated launcher")
    source, core = load("run_source_sealed"), load("run_v16_adapter_migration")
    seal = read(args.seal)
    check = source.verify(ROOT, seal, ENTRY)
    require(core.identity() == seal, "Complete source identity")
    plan = read(ROOT / PLAN)
    require(plan["schema"] == "v16-population-diagnostics-v1", "Plan schema")
    require(all(plan[k] == value for k, value in CEILING.items()), "Claim ceiling")
    historical = read(ROOT / "provenance/pilots/v16_full_comparison_20261014/SOURCE_SEAL.json")
    require(historical["source_commit"] == plan["checkpoint_source_commit"], "Parent source")
    require(
        all(core.digest(ROOT / p) == h for p, h in historical["source_hashes"].items()),
        "Historical source changed",
    )
    inputs(core, plan)
    return source, core, seal, check, plan


def manifest(core, directory):
    return {
        p.relative_to(directory).as_posix(): {"bytes": p.stat().st_size, "sha256": core.digest(p)}
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


def qualification(core, directory, seal):
    result = {}
    expected_cases = read(ROOT / PLAN)["qualification_cases"]
    for device in ("cpu", "cuda"):
        path = directory / device
        start, end = [read(path / f"{s}.json") for s in ("STARTED", "FINISHED")]
        observed = manifest(core, path)
        observed.pop("FINISHED.json")
        require(observed == end["files"], "Tiny receipt manifest")
        require(start["seal"] == seal and start["device"] == device, "Tiny identity")
        require(
            end["status"] == TINY_PASS and end["counts"]["tests"] == expected_cases,
            "Tiny suite did not pass",
        )
        require(end.get("pytest_exit_code") == 0, "Tiny pytest exit status")
        require(
            all(end["counts"][k] == 0 for k in ("failures", "errors", "skipped")),
            "Incomplete tiny suite",
        )
        suites = list(ElementTree.parse(path / "TESTS.xml").getroot().iter("testsuite"))
        require(
            end["counts"]
            == {
                k: sum(int(s.attrib.get(k, 0)) for s in suites)
                for k in ("tests", "failures", "errors", "skipped")
            },
            "Tiny XML counts",
        )
        result[device] = core.digest(path / "FINISHED.json")
    return result


def qualify(args):
    source, core, seal, check, plan = preflight(args)
    args.output.mkdir(parents=True, exist_ok=False)
    core.write_new(
        args.output / "STARTED.json",
        dict(seal=seal, device=args.device, check=check, pid=os.getpid()),
    )
    result = dict(status="INCOMPLETE_NO_RETRY", **CEILING)
    started = time.monotonic()

    def deadline(_s, _f):
        raise KeyboardInterrupt("Tiny qualification deadline")

    signal.signal(signal.SIGALRM, deadline)
    signal.setitimer(signal.ITIMER_REAL, plan["qualification_wall_seconds"])
    try:
        os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        os.environ["LATENT_POPULATION_TEST_DEVICE"] = args.device
        sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "src"), str(ROOT / "scripts")]
        core.load_runtime()
        import pytest

        core.torch.set_num_threads(2)
        core.torch.set_num_interop_threads(1)
        if args.device == "cuda":
            clients = subprocess.check_output(
                ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
                text=True,
            ).strip()
            require(not clients, "Tiny admission: occupied GPU")
            free, total = core.torch.cuda.mem_get_info()
            require(free >= 4 * 2**30, "Tiny GPU capacity")
            core.torch.cuda.set_per_process_memory_fraction(4 * 2**30 / total)
        code = pytest.main(["-q", "--tb=short", f"--junitxml={args.output / 'TESTS.xml'}", *TESTS])
        suites = list(ElementTree.parse(args.output / "TESTS.xml").getroot().iter("testsuite"))
        counts = {
            k: sum(int(s.attrib.get(k, 0)) for s in suites)
            for k in ("tests", "failures", "errors", "skipped")
        }
        result.update(counts=counts, pytest_exit_code=int(code))
        require(
            code == 0
            and counts["tests"] == plan["qualification_cases"]
            and all(counts[k] == 0 for k in ("failures", "errors", "skipped")),
            "Tiny tests",
        )
        source.verify(ROOT, seal, ENTRY)
        result["imports"] = core.verify_imports(seal)
        result["status"] = TINY_PASS
    except BaseException as exc:
        result.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    result["elapsed_seconds"] = time.monotonic() - started
    result["files"] = manifest(core, args.output)
    core.write_new(args.output / "FINISHED.json", result)
    return int(result["status"] != TINY_PASS)


def tokenize_mmlu(tokenizer, rows, cap):
    encoded = []
    for row in rows:
        prefix = tuple(tokenizer.encode(row["prompt"], add_special_tokens=True))
        require(
            0 < len(prefix) <= cap, f"No truncation permitted: {row['id']} length {len(prefix)}"
        )
        candidates = []
        for letter in "ABCD":
            full = tuple(tokenizer.encode(row["prompt"] + " " + letter, add_special_tokens=True))
            require(
                full[:-1] == prefix and len(full) == len(prefix) + 1,
                "MMLU candidate must be exactly one prefix-compatible token",
            )
            candidates.append(full[-1])
        require(len(set(candidates)) == 4, "Distinct MMLU candidates")
        encoded.append(dict(id=row["id"], prefix_ids=prefix, candidate_ids=candidates))
    return encoded


def make_learner(core, plan, parent_root, arm, guard):
    comparison = load("run_v16_full_comparison")
    parent, objective, architecture, records = core.legacy.validate()
    old_plan = read(ROOT / comparison.PLAN)
    source_arm = "common" if arm == "original" else arm
    base, bridge, tokenizer, preparation = comparison.fresh(
        core, parent, architecture, guard, source_arm, old_plan
    )
    context = read(parent_root / "raw" / source_arm / "CONTEXT.json")
    require(preparation == context["contract"]["preparation"], "Same owned native preparation")
    binding = core.MistralTrainingBinding(base, 16)
    cls = comparison.owner_class(core, source_arm)
    if arm == "original":
        learner = cls(
            binding,
            bridge,
            full_update=True,
            optimizer_config=parent["optimizer"],
            run_contract=context["contract"],
        )
        receipt = None
        step = 0
    else:
        receipt = read(parent_root / "raw" / arm / "CHECKPOINT_step2.json")
        checkpoint = parent_root / "checkpoints" / arm / receipt["path"]
        require(
            checkpoint.stat().st_size == receipt["bytes"]
            and core.digest(checkpoint) == receipt["sha256"],
            "Exact checkpoint bytes",
        )
        guard("before_checkpoint_load")
        payload = core.torch.load(checkpoint, map_location="cpu", weights_only=True)
        learner = cls.restore(
            binding,
            bridge,
            payload,
            expected_metadata=context["metadata"],
            expected_run_contract=context["contract"],
            expected_state_sha256=receipt["state_sha256"],
        )
        del payload
        gc.collect()
        step = 2
    # A real-model restore/parity smoke against the original frozen observation.
    store = core.legacy.LiveStore(learner, tokenizer, records, guard)
    old_initial = read(parent_root / "raw" / source_arm / "evaluation_step0.json")
    observed = comparison.evaluate(
        core, learner, store, None if step == 0 else old_initial["direct_base"], guard, old_plan
    )
    require(
        observed == read(parent_root / "raw" / source_arm / f"evaluation_step{step}.json"),
        "Old full evaluation does not replay exactly",
    )
    return (
        learner,
        tokenizer,
        {
            "checkpoint": receipt,
            "old_evaluation_replay_exact": True,
            "replayed_step": step,
            "source_arm": source_arm,
        },
    )


def score_mmlu(core, learner, rows, encoded, output, guard, original_rows=None):
    from latent_workspace_ft_v10.v16_population_probe import choice4

    torch = core.torch
    reports = []
    for index, (row, tokens) in enumerate(zip(rows, encoded, strict=True)):
        guard(f"mmlu:{index}")
        ids = torch.tensor([tokens["prefix_ids"]], device=learner.base.device)
        with torch.no_grad():
            logits = learner.base(
                input_ids=ids,
                attention_mask=torch.ones_like(ids),
                use_cache=False,
                logits_to_keep=0,
                return_dict=True,
            ).logits
            scores = logits[0, -1, tokens["candidate_ids"]].detach().cpu().double().tolist()
        del logits, ids
        measured = choice4(scores)
        measured.update(
            id=row["id"],
            subject=row["subject"],
            target=row["target"],
            token_count=len(tokens["prefix_ids"]),
            candidate_ids=tokens["candidate_ids"],
            correct=measured["prediction"] == row["target"],
            strict_correct=measured["strict_prediction"] == row["target"],
            prompt_ids_sha256=core.tree_hash(tokens["prefix_ids"]),
        )
        if original_rows is not None:
            reference = original_rows[index]
            require(
                all(
                    measured[k] == reference[k]
                    for k in ("id", "target", "candidate_ids", "prompt_ids_sha256")
                ),
                "MMLU pairing",
            )
            measured.update(
                regression=reference["correct"] and not measured["correct"],
                repair=not reference["correct"] and measured["correct"],
            )
        reports.append(measured)
        with (output / "mmlu.jsonl").open("a") as stream:
            stream.write(core.canonical(measured) + "\n")
            stream.flush()
        if (index + 1) % 50 == 0:
            print(json.dumps(dict(mmlu_rows=index + 1)), flush=True)
        if index == 9:
            core.write_new(
                output / "MMLU_SMOKE.json",
                dict(
                    status="FINITE_PREFIX_COMPATIBLE_NATIVE_SCORES_NOT_ACCURACY_GATE",
                    n=10,
                    correct=sum(r["correct"] for r in reports),
                    ties=sum(r["tie"] for r in reports),
                ),
            )
    return reports


def evaluate_world(core, learner, tokenizer, record, guard, world_index, plan, original=None):
    from latent_workspace_ft_v10.reader_query import QuestionSpan
    from latent_workspace_ft_v10.v16_comparison_eval import choice, evaluate, memory_bank
    from latent_workspace_ft_v10.v16_population_probe import slot_trace

    store = core.legacy.LiveStore(learner, tokenizer, [record], guard)
    if original is None:
        bases = []
        with core.torch.no_grad():
            for q in range(8):
                row = store.renderings[0, q]
                tokens = core.torch.tensor([row["prompt_ids"]], device=learner.base.device)
                logits = learner.base(
                    input_ids=tokens,
                    attention_mask=core.torch.ones_like(tokens),
                    use_cache=False,
                    logits_to_keep=0,
                    return_dict=True,
                ).logits
                bases.append(
                    dict(
                        world=0,
                        query=q,
                        labels=[a[q] for a in record["answers"]],
                        **choice(logits, row["candidate_ids"]),
                    )
                )
        return {
            "direct_base": bases,
            "world_index": world_index,
            "pair_id": record["metadata"]["pair_id"],
        }
    before = core.tree_hash(core.rng_state())
    versions = [
        (id(p), p._version) for p in (*learner.base.parameters(), *learner.bridge.parameters())
    ]
    with core.torch.no_grad():
        report = evaluate(
            learner,
            store,
            original=original["direct_base"],
            random_seed=plan["random_memory_seed"] + world_index,
            guard=guard,
        )
        bank = memory_bank(learner, store, 0, plan["random_memory_seed"] + world_index)
        traces = []
        for q in range(8):
            row = store.renderings[0, q]
            value = row["span"]
            span = QuestionSpan(
                **{
                    **value,
                    "token_indices": tuple(value["token_indices"]),
                    "prefix_ids": tuple(value["prefix_ids"]),
                }
            )
            for condition in ("intact", "twin"):
                memory, mask = bank[condition]
                captured = learner.pipeline(tuple(row["prompt_ids"]), memory, mask, span=span)
                traces.append(
                    dict(
                        query=q,
                        condition=condition,
                        **slot_trace(learner.bridge, captured.reader_query, memory, mask),
                    )
                )
    require(core.tree_hash(core.rng_state()) == before, "Probe changed RNG")
    require(
        versions
        == [
            (id(p), p._version) for p in (*learner.base.parameters(), *learner.bridge.parameters())
        ],
        "Probe mutated parameter versions",
    )
    report.update(
        traces=traces,
        world_index=world_index,
        pair_id=record["metadata"]["pair_id"],
        parameter_versions_unchanged=True,
    )
    return report


def run_arm(args):
    source, core, seal, check, plan = preflight(args)
    qualified = qualification(core, args.qualification, seal)
    require(args.arm in plan["arms"], "Unknown arm")
    require(not args.output.resolve().is_relative_to(ROOT), "Output outside source")
    args.output.mkdir(parents=True, exist_ok=False)
    core.write_new(
        args.output / "STARTED.json",
        dict(
            pid=os.getpid(),
            arm=args.arm,
            source=seal,
            plan=plan,
            check=check,
            qualification=qualified,
            parent_root=str(args.parent_root),
        ),
    )
    result = dict(
        status="INCOMPLETE_NO_RETRY", arm=args.arm, completed_worlds=0, completed_mmlu=0, **CEILING
    )
    started = time.monotonic()

    def deadline(_s, _f):
        raise KeyboardInterrupt("Population arm wall limit")

    signal.signal(signal.SIGALRM, deadline)
    signal.setitimer(signal.ITIMER_REAL, plan["resources"]["max_elapsed_seconds"])
    try:
        core.load_runtime()
        budget = read(ROOT / core.PLAN)
        result["runtime"] = load("run_v16_adapter_full_recovery_02").runtime(core, budget)
        guard = core.legacy.Guard(plan["resources"], args.output)
        guard("admission", admission=True, forecast_bytes=2 * 2**30)
        core.torch.cuda.set_per_process_memory_fraction(
            plan["resources"]["allocator_cap_gib"]
            * 2**30
            / core.torch.cuda.get_device_properties(0).total_memory
        )
        worlds, mmlu, input_manifest = inputs(core, plan)
        learner, tokenizer, restored = make_learner(core, plan, args.parent_root, args.arm, guard)
        core.write_new(args.output / "RESTORE.json", restored)
        encoded = tokenize_mmlu(tokenizer, mmlu, plan["mmlu"]["max_prompt_tokens"])
        core.write_new(
            args.output / "TOKENS.json",
            {
                "input_manifest": input_manifest,
                "mmlu_token_sha256": core.tree_hash(encoded),
                "max_mmlu_prompt_tokens": max(len(x["prefix_ids"]) for x in encoded),
                "tokenizer_vocab_sha256": core.tree_hash(tokenizer.get_vocab()),
            },
        )
        before = core.state_fingerprint(learner)
        core.write_new(args.output / "BEFORE.json", before)
        original_dir = args.output.parent / "original"
        original_mmlu = (
            None
            if args.arm == "original"
            else [
                json.loads(line) for line in (original_dir / "mmlu.jsonl").read_text().splitlines()
            ]
        )
        mmlu_results = score_mmlu(core, learner, mmlu, encoded, args.output, guard, original_mmlu)
        result["completed_mmlu"] = len(mmlu_results)
        for index, record in enumerate(worlds):
            guard(f"world:{index}")
            baseline = (
                None if args.arm == "original" else read(original_dir / f"world_{index:03d}.json")
            )
            report = evaluate_world(core, learner, tokenizer, record, guard, index, plan, baseline)
            core.write_new(args.output / f"world_{index:03d}.json", report)
            result["completed_worlds"] += 1
            print(
                json.dumps(
                    dict(
                        arm=args.arm,
                        worlds=result["completed_worlds"],
                        mmlu=result["completed_mmlu"],
                    )
                ),
                flush=True,
            )
        after = core.state_fingerprint(learner)
        require(before == after, "Evaluation changed model/reader/optimizer/RNG")
        learner._validate_ownership()
        core.write_new(args.output / "AFTER.json", after)
        result.update(
            state_unchanged=True,
            mmlu_correct=sum(r["correct"] for r in mmlu_results),
            mmlu_strict_correct=sum(r["strict_correct"] for r in mmlu_results),
            mmlu_ties=sum(r["tie"] for r in mmlu_results),
            peak_cuda_allocated_bytes=core.torch.cuda.max_memory_allocated(),
            peak_cuda_reserved_bytes=core.torch.cuda.max_memory_reserved(),
        )
        source.verify(ROOT, seal, ENTRY)
        result["imports"] = core.verify_imports(seal)
        result["status"] = PASS
    except BaseException as exc:
        result.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    journal = args.output / "mmlu.jsonl"
    if journal.exists():
        result["completed_mmlu"] = len(journal.read_text().splitlines())
    result["elapsed_seconds"] = time.monotonic() - started
    result["files"] = manifest(core, args.output)
    core.write_new(args.output / "FINISHED.json", result)
    return int(result["status"] != PASS)


def dispatch(args):
    source, core, seal, check, plan = preflight(args)
    qualification(core, args.qualification, seal)
    require(not args.output.resolve().is_relative_to(ROOT), "Output outside source")
    args.output.mkdir(parents=True, exist_ok=False)
    core.write_new(
        args.output / "STARTED.json",
        dict(pid=os.getpid(), seal=seal, plan=plan, check=check, parent_root=str(args.parent_root)),
    )
    result = dict(status="INCOMPLETE_NO_RETRY", completed_arms=[], **CEILING)
    try:
        # Replay all old receipts; no old call or cell is re-dispatched.
        sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
        old = load("verify_v16_full_comparison")
        require(
            read(args.parent_root / "SOURCE_SEAL.json")
            == read(ROOT / "provenance/pilots/v16_full_comparison_20261014/SOURCE_SEAL.json"),
            "Exact parent source seal",
        )
        old_receipt = old.verify(
            args.parent_root / "raw",
            read(args.parent_root / "SOURCE_SEAL.json"),
            args.parent_root / "qualification",
        )
        core.write_new(args.output / "PARENT_VERIFY.json", old_receipt)
        for arm in plan["arms"]:
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
                "--parent-root",
                str(args.parent_root),
                "--qualification",
                str(args.qualification),
                "--arm",
                arm,
                "--output",
                str(args.output / arm),
            ]
            with (args.output / f"{arm}.log").open("x") as log:
                child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
                core.write_new(
                    args.output / f"DISPATCH_{arm}.json", dict(pid=child.pid, command=command)
                )
                code = child.wait()
            require(
                code == 0 and read(args.output / arm / "FINISHED.json")["status"] == PASS,
                f"{arm} failed; no later arm, retry or resume",
            )
            result["completed_arms"].append(arm)
        source.verify(ROOT, seal, ENTRY)
        result["status"] = PASS
    except BaseException as exc:
        result.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    result["files"] = manifest(core, args.output)
    core.write_new(args.output / "FINISHED.json", result)
    return int(result["status"] != PASS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    seal = sub.add_parser("prepare-seal")
    seal.add_argument("--output", type=Path, required=True)
    for name in ("qualify", "dispatch", "run-arm"):
        p = sub.add_parser(name)
        p.add_argument("--seal", required=True, type=Path)
        p.add_argument("--output", required=True, type=Path)
        if name == "qualify":
            p.add_argument("--device", required=True, choices=("cpu", "cuda"))
        else:
            p.add_argument("--parent-root", required=True, type=Path)
            p.add_argument("--qualification", required=True, type=Path)
        if name == "run-arm":
            p.add_argument("--arm", required=True)
    args = parser.parse_args()
    if args.command == "prepare-seal":
        core = load("run_v16_adapter_migration")
        core.write_new(args.output, core.identity())
        return 0
    return {"qualify": qualify, "dispatch": dispatch, "run-arm": run_arm}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
