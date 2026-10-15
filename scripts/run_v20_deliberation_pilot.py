#!/usr/bin/env python3
"""Sealed V20 Deliberation pilot (D1): the v4/v5 lattice over frozen Mistral-7B states.

Pinned Mistral-7B stays frozen and sees the world facts inline (V15's qualified
native-chat renderer). One GPU role extracts, for every train/dev/final row, the
final hidden states entering the LM head and the base logits of the two
candidates, with bitwise native parity. CPU roles then train the v4 route
(lattice, gate, low-rank vocabulary residual) for four arms x three seeds and
evaluate dev and the held-out final split; a fresh process replays update 257
exactly. Each role is a fresh process through the pre-import source launcher,
run in order and stopping at the first failure. No retry, download, generation,
judge call, native update or weight deletion.
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
ENTRY = "scripts/run_v20_deliberation_pilot.py"
PLAN = "configs/v20/DELIBERATION_PILOT_PLAN.json"
PLAN_CANONICAL_SHA256 = "23f2e28671f9ccaa0bc2b325bf9609f5de9ced10db29c3e6c18c53f5509c8a77"
SPLITS = ("train", "dev", "final")
ARMS = ("k4", "k1", "k4_lw", "readout")
PASS = "V20_DELIBERATION_PILOT_COMPLETE_NOT_FULL_UPDATE_OR_RELEASE"
TINY_PASS = "TINY_V20_DELIBERATION_HARNESS_PASS_NOT_7B"
EXTRACT_PASS = "V20_FROZEN_INLINE_FEATURES_EXTRACTED"
ARM_PASS = "V20_DELIBERATION_ARM_COMPLETE"
REPLAY_PASS = "V20_DELIBERATION_FRESH_PROCESS_EXACT_REPLAY"
VERDICTS = ("DELIBERATION_STEP_GAIN", "LATTICE_GAIN_WITHOUT_STEP_DEPENDENCE", "NO_LATTICE_GAIN")
CEILING = dict(
    new_sequences=0,
    judge_calls=0,
    weight_deletions=0,
    native_weight_updates=0,
    old_expression_gate="FAIL",
    winner="none",
    non_regression="NOT_ESTABLISHED",
)
GIB = 2**30
QUALIFICATION_CASES = 25
_MODULES = {}


def load(name):
    if name not in _MODULES:
        spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        _MODULES[name] = module
    return _MODULES[name]


def v19():
    """Sealed V19 helpers: data loading/oracle audit, manifests, deterministic gzip."""
    return load("run_v19_frozen_diagnostic")


def read(path):
    return json.loads(Path(path).read_text())


def require(ok, message):
    if not ok:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def seed_roles(plan):
    return [f"{arm}_s{i + 1}" for i in range(len(plan["seeds"])) for arm in ARMS]


def roles(plan):
    return ["extract", *seed_roles(plan), "replay"]


def parse_role(plan, role):
    arm, index = role.rsplit("_s", 1)
    require(arm in ARMS and index.isdigit(), f"Unknown role {role}")
    spec = next(a for a in plan["arms"] if a["name"] == arm)
    return spec, plan["seeds"][int(index) - 1]


def validate_plan(plan):
    require(
        hashlib.sha256(canonical(plan).encode()).hexdigest() == PLAN_CANONICAL_SHA256,
        "Frozen V20 Deliberation plan changed",
    )
    training = plan["training"]
    rows = 16 * plan["data"]["train"]["world_pairs"]
    require(
        [a["name"] for a in plan["arms"]] == list(ARMS)
        and len(plan["seeds"]) == len(set(plan["seeds"])) == 3
        and plan["backbone"]["frozen"] is True
        and training["updates"] == training["epochs"] * (rows // training["batch_size"])
        and plan["endpoints"]["step"] == training["updates"]
        and plan["final_evaluation_steps"] == [0, training["updates"]]
        and plan["replay"]["execute_step"] == plan["replay"]["from_step"] + 1
        and plan["replay"]["from_step"] in plan["checkpoint_steps"]
        and tuple(plan["endpoints"]["verdicts"]) == VERDICTS
        and plan["qualification_cases"] == QUALIFICATION_CASES
        and all(plan[k] == v for k, v in CEILING.items()),
        "Frozen V20 Deliberation plan semantics changed",
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
    for split in SPLITS:
        spec = plan["data"][split]
        require(v19().digest(ROOT / spec["path"]) == spec["sha256"], f"Data changed: {split}")
    return source, core, seal, check, plan


def offline_environment():
    for key, value in v19().OFFLINE.items():
        os.environ[key] = value


# ---- tiny qualification --------------------------------------------------------


def qualify(args):
    source, core, seal, check, plan = preflight(args)
    require(not args.output.resolve().is_relative_to(ROOT), "Output must be outside source")
    args.output.mkdir(parents=True, exist_ok=False)
    v19().write_new(
        args.output / "STARTED.json",
        dict(seal=seal, source_check=check, plan=plan, pid=os.getpid(), device=args.device),
    )
    started = time.monotonic()
    result = dict(status="INCOMPLETE_NO_RETRY", device=args.device, real_model_updates=0, **CEILING)
    try:
        offline_environment()
        os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        os.environ["LATENT_V20_TEST_DEVICE"] = args.device
        sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "scripts"), str(ROOT / "tests")]
        core.load_runtime()
        import pytest

        if args.device == "cuda":
            clients = subprocess.check_output(
                ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
                text=True,
            ).split()
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
    result["files"] = v19().manifest(args.output)
    v19().write_new(args.output / "FINISHED.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "files"}), flush=True)
    return int(result["status"] != TINY_PASS)


def qualification(path, seal, plan):
    result = {}
    for device in ("cpu", "cuda"):
        bundle = path / device
        start, end = read(bundle / "STARTED.json"), read(bundle / "FINISHED.json")
        files = v19().manifest(bundle)
        files.pop("FINISHED.json")
        require(files == end["files"], "Qualification artifact bytes")
        require(
            start["seal"] == seal and start["plan"] == plan and start["device"] == device,
            "Qualification selection/source/device mismatch",
        )
        counts = dict(tests=plan["qualification_cases"], failures=0, errors=0, skipped=0)
        require(
            end["status"] == TINY_PASS and end["pytest_exit_code"] == 0 and end["counts"] == counts,
            "Both CPU and CUDA qualification must pass",
        )
        require(all(end[k] == v for k, v in CEILING.items()), "Qualification ceiling")
        result[device] = v19().manifest(bundle)
    return result


# ---- rows and features ---------------------------------------------------------


def wording(query):
    return "outrank" if "outrank" in query.lower() else "ranked_above"


def render_rows(old, tokenizer, records, plan):
    """Inline renderings in fixed order: world, side (intact, twin), query."""
    spec = plan["rendering"]
    rows = []
    for w, record in enumerate(records):
        for side in (0, 1):
            context = old.canonical_facts(record["contexts"][side])
            for q, query in enumerate(record["queries"]):
                rendered = old.render_case(
                    tokenizer,
                    query=query,
                    context=context,
                    renderer=spec["renderer"],
                    cue=spec["cue"],
                    information=spec["information"],
                )
                require(rendered["candidate_ids"] == plan["candidate_ids"], "Candidate ids")
                rows.append(
                    dict(
                        world=w,
                        side=side,
                        query=q,
                        label=int(record["answers"][side][q]),
                        affected=record["answers"][0][q] != record["answers"][1][q],
                        hop=int(record["hop_distances"][q]),
                        wording=wording(query),
                        prompt_ids=list(rendered["prompt_ids"]),
                        candidate_ids=list(rendered["candidate_ids"]),
                    )
                )
    return rows


def extract_split(torch, base, readout, rows, guard, label):
    hidden_rows, base_rows = [], []
    for index, row in enumerate(rows):
        if index % 64 == 0:
            guard(f"extract:{label}:{index}")
        ids = torch.tensor([row["prompt_ids"]], device=base.device)
        mask = torch.ones_like(ids)
        logits = base(ids, attention_mask=mask, use_cache=False).logits
        hidden = base.model(ids, attention_mask=mask, use_cache=False).last_hidden_state
        shared = readout(hidden, torch.zeros_like(hidden[:, -1:]).float())
        require(torch.equal(logits, shared.logits), "Ordinary/shared native parity failed")
        hidden_rows.append(hidden[0].detach().cpu())
        base_rows.append(logits[0, -1, list(row["candidate_ids"])].float().cpu())
    offsets = [0]
    for tensor in hidden_rows:
        offsets.append(offsets[-1] + tensor.shape[0])
    return {
        "hidden": torch.cat(hidden_rows),
        "offsets": torch.tensor(offsets, dtype=torch.long),
        "base_logits": torch.stack(base_rows),
        "targets": torch.tensor([r["label"] for r in rows], dtype=torch.long),
        "worlds": torch.tensor([r["world"] for r in rows], dtype=torch.long),
    }


def load_bank(directory, split):
    from safetensors.torch import load_file

    from latent_workspace_ft_v10.v20_deliberation import FeatureBank

    tensors = load_file(str(directory / f"FEATURES_{split}.safetensors"))
    return FeatureBank(
        tensors["hidden"],
        tensors["offsets"],
        tensors["base_logits"],
        tensors["targets"],
        tensors["worlds"],
    )


def extract_run(core, args, plan, guard):
    torch = core.torch
    old = core.legacy.old
    _, _, architecture, _ = core.legacy.validate()
    config = old.engine.ModelConfig(**architecture["model"])
    tokenizer = old.engine.load_tokenizer(config)
    require(tokenizer.eos_token_id == plan["eos_token_id"], "Pinned EOS")
    base = old.engine._load_hf_model(config).eval().requires_grad_(False).to("cuda")
    require(
        core.tree_hash(base.state_dict()) == plan["backbone"]["original_base_sha256"],
        "Pinned base identity",
    )
    require(base.lm_head.weight.shape[0] == plan["route"]["vocab_size"], "Vocabulary size")
    readout = old.NativeWorkspaceReadout(base.lm_head)
    records = v19().load_records(plan)
    audit = v19().validate_data(old, records)
    from safetensors.torch import save_file

    receipts = {}
    for split in SPLITS:
        rows = render_rows(old, tokenizer, records[split], plan)
        with torch.no_grad():
            tensors = extract_split(torch, base, readout, rows, guard, split)
        for row, logits in zip(rows, tensors["base_logits"].tolist(), strict=True):
            row["base_logits"] = logits
        path = args.output / f"FEATURES_{split}.safetensors"
        save_file({k: v.contiguous() for k, v in tensors.items()}, str(path))
        v19().write_gz(args.output / f"ROWS_{split}.json.gz", rows)
        receipts[split] = split_receipt(rows, str(tensors["hidden"].dtype))
    return dict(splits=receipts, data_audit=audit, model_config=architecture["model"])


def split_receipt(rows, hidden_dtype):
    correct = [r["base_logits"][r["label"]] > r["base_logits"][1 - r["label"]] for r in rows]
    return dict(
        rows=len(rows),
        tokens=sum(len(r["prompt_ids"]) for r in rows),
        max_length=max(len(r["prompt_ids"]) for r in rows),
        base_inline_correct=sum(correct),
        hidden_dtype=hidden_dtype,
    )


# ---- CPU training ----------------------------------------------------------------


def cpu_runtime(plan):
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    import torch

    torch.set_num_threads(plan["training"]["threads"])
    torch.use_deterministic_algorithms(True)
    return torch


def build(plan, spec, seed):
    from latent_workspace_ft_v10 import v20_deliberation as deliberation

    route_spec = plan["route"]
    route = deliberation.DeliberationRoute(
        route_spec["hidden_dim"],
        route_spec["vocab_size"],
        tuple(plan["candidate_ids"]),
        steps=spec["steps"],
        seed=seed,
        workspace_dim=route_spec["workspace_dim"],
        heads=route_spec["attention_heads"],
        ff_multiplier=route_spec["ff_multiplier"],
        dropout=route_spec["dropout"],
        rank=route_spec["rank"],
        gate_init_bias=route_spec["gate_init_bias"],
    )
    weight = spec["workspace_loss_weight"]
    loss = deliberation.workspace_loss(seed, route_spec["workspace_dim"]) if weight else None
    training = plan["training"]
    config = deliberation.TrainConfig(
        seed=seed,
        updates=training["updates"],
        batch_size=training["batch_size"],
        learning_rate=training["learning_rate"],
        weight_decay=training["weight_decay"],
        max_grad_norm=training["max_grad_norm"],
        workspace_loss_weight=weight,
        loss_tokens_per_row=training["loss_tokens_per_row"],
        loss_tokens_per_batch=training["loss_tokens_per_batch"],
        spectral_every=training["spectral_every"],
    )
    named = deliberation.trainable(route, loss)
    optimizer = deliberation.optimizer_for(named, config.learning_rate, config.weight_decay)
    return deliberation, route, loss, optimizer, config, named


def adapted_record(adapted, bank):
    rows = adapted.tolist()
    targets = bank.targets.tolist()
    return {
        "adapted_logits": rows,
        "correct": [r[t] > r[1 - t] for r, t in zip(rows, targets, strict=True)],
    }


def train_run(torch, args, plan, role, banks):
    spec, seed = parse_role(plan, role)
    deliberation, route, loss, optimizer, config, named = build(plan, spec, seed)
    checkpoints = args.checkpoints / role
    checkpoints.mkdir(parents=True, exist_ok=False)
    fingerprints = {0: deliberation.fingerprint(named)}

    def evaluation(split, step, steps=None):
        adapted = deliberation.evaluate(route, banks[split], steps=steps)
        record = adapted_record(adapted, banks[split])
        suffix = "" if steps is None else f"_k{steps}"
        v19().write_gz(args.output / f"eval_{split}_step{step}{suffix}.json.gz", record)
        return record

    for split in ("dev", "final"):
        record = evaluation(split, 0)
        require(
            record["adapted_logits"] == banks[split].base_logits.tolist(),
            "Step-0 route must leave base inline logits exact",
        )
    with (args.output / "updates.jsonl").open("x") as log:
        for step in range(1, config.updates + 1):
            receipt = deliberation.update(route, loss, optimizer, banks["train"], config, step)
            log.write(json.dumps(receipt) + "\n")
            if step in plan["checkpoint_steps"] or step == plan["replay"]["execute_step"]:
                fingerprints[step] = deliberation.fingerprint(named)
            if step in plan["checkpoint_steps"]:
                path = checkpoints / f"step{step}.pt"
                state = dict(
                    route=route.state_dict(),
                    loss=None if loss is None else loss.state_dict(),
                    optimizer=optimizer.state_dict(),
                    completed_steps=step,
                )
                torch.save(state, path)
                v19().write_new(
                    args.output / f"CHECKPOINT_step{step}.json",
                    dict(
                        path=path.name,
                        bytes=path.stat().st_size,
                        sha256=v19().digest(path),
                        fingerprint=fingerprints[step],
                        completed_steps=step,
                    ),
                )
            if step in plan["dev_evaluation_steps"]:
                evaluation("dev", step)
    fingerprints[config.updates] = deliberation.fingerprint(named)
    evaluation("final", config.updates)
    if spec["steps"] > 1:
        for steps in plan["truncation_steps"]:
            if steps < spec["steps"]:
                evaluation("final", config.updates, steps=steps)
    v19().write_new(args.output / "FINGERPRINTS.json", {str(k): v for k, v in fingerprints.items()})
    return dict(arm=spec["name"], seed=seed, fingerprints=fingerprints)


def replay_run(torch, args, plan, banks):
    rule = plan["replay"]
    role = f"{rule['arm']}_s{plan['seeds'].index(rule['seed']) + 1}"
    source = args.output.parent / role
    spec, seed = parse_role(plan, role)
    deliberation, route, loss, optimizer, config, named = build(plan, spec, seed)
    receipt = read(source / f"CHECKPOINT_step{rule['from_step']}.json")
    path = args.checkpoints / role / receipt["path"]
    require(v19().digest(path) == receipt["sha256"], "Replay checkpoint bytes")
    state = torch.load(path, map_location="cpu", weights_only=True)
    route.load_state_dict(state["route"])
    if loss is not None:
        loss.load_state_dict(state["loss"])
    optimizer.load_state_dict(state["optimizer"])
    require(state["completed_steps"] == rule["from_step"], "Checkpoint step")
    restored = deliberation.fingerprint(named)
    require(restored == receipt["fingerprint"], "Restored state differs")
    update = deliberation.update(
        route, loss, optimizer, banks["train"], config, rule["execute_step"]
    )
    replayed = deliberation.fingerprint(named)
    expected = read(source / "FINGERPRINTS.json")[str(rule["execute_step"])]
    original = [json.loads(line) for line in (source / "updates.jsonl").read_text().splitlines()][
        rule["execute_step"] - 1
    ]
    report = dict(
        role=role,
        from_step=rule["from_step"],
        execute_step=rule["execute_step"],
        restored_fingerprint=restored,
        replayed_fingerprint=replayed,
        original_fingerprint=expected,
        update=update,
        original_update=original,
        exact=replayed == expected and update == original,
        replay_pid=os.getpid(),
        arm_pid=read(source / "STARTED.json")["pid"],
    )
    require(report["exact"], "Fresh-process replay differs")
    require(report["arm_pid"] != report["replay_pid"], "Replay must be a fresh process")
    v19().write_new(args.output / "REPLAY.json", report)
    return report


# ---- endpoints -------------------------------------------------------------------


def endpoints_for(raw, plan):
    from latent_workspace_ft_v10 import v20_deliberation as deliberation

    rows = v19().read_gz(raw / "extract" / "ROWS_final.json.gz")
    worlds = [r["world"] for r in rows]
    base = [r["base_logits"][r["label"]] > r["base_logits"][1 - r["label"]] for r in rows]
    step = plan["endpoints"]["step"]
    rule = plan["endpoints"]
    correct = {
        role: v19().read_gz(raw / role / f"eval_final_step{step}.json.gz")["correct"]
        for role in seed_roles(plan)
    }
    route_gains, step_gains, per_seed = [], [], []
    for index in range(1, len(plan["seeds"]) + 1):
        k4, k1 = correct[f"k4_s{index}"], correct[f"k1_s{index}"]
        route = deliberation.gain(k4, base, worlds, rule)
        steps = deliberation.gain(k4, k1, worlds, rule)
        route_gains.append(route)
        step_gains.append(steps)
        per_seed.append(
            dict(
                seed=plan["seeds"][index - 1],
                base_inline_accuracy=sum(base) / len(base),
                accuracy={a: sum(correct[f"{a}_s{index}"]) / len(base) for a in ARMS},
                route_gain=route,
                step_gain=steps,
            )
        )
    return dict(
        verdict=deliberation.verdict(route_gains, step_gains, VERDICTS),
        per_seed=per_seed,
        rule=rule,
    )


# ---- roles -----------------------------------------------------------------------


def run_role(args):
    source, core, seal, check, plan = preflight(args)
    qualified = qualification(args.qualification, seal, plan)
    out, ckpt = args.output.resolve(), args.checkpoints.resolve()
    require(not out.is_relative_to(ROOT) and not ckpt.is_relative_to(ROOT), "Outside source")
    require(not out.exists(), "Fresh role output only")
    out.mkdir(parents=True, exist_ok=False)
    v19().write_new(
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
        raise KeyboardInterrupt("V20 Deliberation role wall limit")

    signal.signal(signal.SIGALRM, deadline)
    signal.setitimer(signal.ITIMER_REAL, plan["resources"]["max_elapsed_seconds"])
    try:
        offline_environment()
        args.output = out
        if args.role == "extract":
            core.load_runtime()
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
            result["outcome"] = extract_run(core, args, plan, guard)
            guard("finished")
            result.update(
                peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(),
                peak_cuda_reserved_bytes=torch.cuda.max_memory_reserved(),
            )
            status = EXTRACT_PASS
        else:
            torch = cpu_runtime(plan)
            core.load_runtime()
            require(not torch.cuda.is_available(), "CPU roles must not see a GPU")
            features = out.parent / "extract"
            require(
                read(features / "FINISHED.json")["status"] == EXTRACT_PASS, "Features not extracted"
            )
            banks = {split: load_bank(features, split) for split in SPLITS}
            if args.role == "replay":
                result["outcome"] = replay_run(torch, args, plan, banks)
                status = REPLAY_PASS
            else:
                result["outcome"] = train_run(torch, args, plan, args.role, banks)
                status = ARM_PASS
        source.verify(ROOT, seal, ENTRY)
        require(core.identity() == seal, "Source changed")
        require(qualification(args.qualification, seal, plan) == qualified, "Qualification")
        result["imports"] = core.verify_imports(seal)
        result["status"] = status
    except BaseException as exc:
        result.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    result["elapsed_seconds"] = time.monotonic() - started
    result["files"] = v19().manifest(out)
    v19().write_new(out / "FINISHED.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "files"}), flush=True)
    passed = {"extract": EXTRACT_PASS, "replay": REPLAY_PASS}.get(args.role, ARM_PASS)
    return int(result["status"] != passed)


def dispatch(args):
    source, core, seal, check, plan = preflight(args)
    qualified = qualification(args.qualification, seal, plan)
    out, ckpt = args.output.resolve(), args.checkpoints.resolve()
    require(not out.is_relative_to(ROOT) and not ckpt.is_relative_to(ROOT), "Outside source")
    require(not out.exists() and not ckpt.exists(), "Fresh destinations only")
    out.mkdir(parents=True, exist_ok=False)
    ckpt.mkdir(parents=True, exist_ok=False)
    v19().write_new(
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
        for role in roles(plan):
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
            with (out / f"{role}.log").open("x") as log:
                child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
                v19().write_new(out / f"DISPATCH_{role}.json", dict(pid=child.pid, command=command))
                code = child.wait()
            require(code == 0, f"{role} exited {code}; no later role or retry dispatched")
            result["completed_roles"].append(role)
        endpoints = endpoints_for(out, plan)
        v19().write_new(out / "ENDPOINTS.json", endpoints)
        source.verify(ROOT, seal, ENTRY)
        result.update(status=PASS, verdict=endpoints["verdict"])
    except BaseException as exc:
        result.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    result["elapsed_seconds"] = time.monotonic() - started
    result["files"] = v19().manifest(out)
    v19().write_new(out / "FINISHED.json", result)
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
            p.add_argument("--role", required=True)
    args = parser.parse_args()
    if args.command == "prepare-seal":
        core = load("run_v16_adapter_migration")
        validate_plan(read(ROOT / PLAN))
        v19().write_new(args.output, core.identity())
        return 0
    return {"qualify": qualify, "run-role": run_role, "dispatch": dispatch}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
