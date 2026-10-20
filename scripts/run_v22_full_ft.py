#!/usr/bin/env python3
"""Sealed English V22: length canary, exact replay, then a finite native FT pilot.

Canary updates are not inherited by the training condition. No generation,
provider call, automatic retry, threshold adjustment, export or deletion.
"""

from __future__ import annotations

import gc
import inspect
import os
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from latent_workspace import execution as ex  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
import run_native_7b_canary as common  # noqa: E402

ENTRY = "scripts/run_v22_full_ft.py"
PLAN = "configs/v22/FULL_FT_01.json"
PLAN_SHA256 = "72de41bb91cd0c0c2c0f0c4956ea079e82fcec552091f555912b5172b2c5b897"
TINY_PASS = "TINY_V22_MIXED_TRAINING_HARNESS_PASS_NOT_7B"
ROLES = ("canary", "replay", "train_a", "train_b")
STATUSES = dict(
    canary="V22_TWO_LENGTH_UPDATES_ONE_SAVE",
    replay="V22_EXACT_LENGTH_STEP2_REPLAY",
    train_a="V22_TRAINING_STEP16_SAVED",
    train_b="V22_TRAINING_STEP32_SAVED",
)


def validate(plan):
    ex.require(ex.plan_hash(plan) == PLAN_SHA256, "Frozen V22 plan changed")
    reference = ex.read(ROOT / plan["reference_plan"])
    ex.require(
        ex.plan_hash(reference) == plan["reference_plan_sha256"], "Historical numerical recipe"
    )
    ex.require(
        ex.digest(ROOT / plan["data_recipe"]) == plan["data_recipe_sha256"], "Frozen data recipe"
    )
    for key in ("backbone", "optimizer", "adafactor_step_sha256", "objective", "expected_runtime"):
        ex.require(plan[key] == reference[key], f"Unchanged native policy: {key}")
    ex.require(plan["no_retry"] and plan["planned_training_updates"] == 32, "Finite no-retry run")
    ex.require(
        plan["checkpoint_names"] == ["canary_step1.pt", "training_step16.pt", "training_step32.pt"],
        "Checkpoint scope",
    )


def load_data(plan, root=ROOT):
    from latent_workspace import v22_data

    folder = Path(plan["data_bundle"])
    ex.require(not folder.is_symlink(), "No data-bundle symlink")
    ex.require(
        ex.digest(folder / "MANIFEST.json") == plan["data_manifest_sha256"], "Pinned data seal"
    )
    manifest = ex.read(folder / "MANIFEST.json")
    files = ex.manifest(folder)
    files.pop("MANIFEST.json")
    ex.require(files == manifest["files"], "Frozen data bytes/file set")
    for name, digest in manifest["source"].items():
        ex.require(ex.digest(root / name) == digest, "Data builder source changed")
    recipe = ex.read(root / plan["data_recipe"])
    ex.require(recipe == ex.read(folder / "PLAN.json"), "Same data recipe")
    rows, schedule = ex.read_gz(folder / "rows.json.gz"), ex.read(folder / "SCHEDULE.json")
    for row in rows:
        v22_data.validate_row(row, recipe)
    ex.require(len({r["key"] for r in rows}) == len(rows), "Unique row keys")
    ex.require(schedule["training"] == v22_data.schedule(rows, recipe), "Exact training schedule")
    ex.require(
        schedule["canary"] == v22_data.select_canary(rows, recipe), "Exact length-canary selection"
    )
    ex.require(schedule["development"] == v22_data.select_dev(rows, recipe), "Exact dev selection")
    summary = ex.read(folder / "SUMMARY.json")
    rebuilt = v22_data.summarize(
        rows,
        schedule["training"],
        schedule["canary"],
        schedule["development"],
        summary["excluded"],
        recipe,
    )
    ex.require(rebuilt == summary, "Exact data denominators")
    ex.require(
        summary["training_rows"] == plan["planned_training_rows"]
        and summary["training_tokens"] == plan["planned_training_tokens"],
        "Planned training exposure",
    )
    return rows, schedule, manifest, summary


def predecessor(args, role, seal):
    folder = args.output.parent / role
    start, end = ex.read(folder / "STARTED.json"), ex.read(folder / "FINISHED.json")
    files = ex.manifest(folder)
    files.pop("FINISHED.json")
    ex.require(start["seal"] == seal and end["files"] == files, "Predecessor source/artifacts")
    ex.require(end["status"] == STATUSES[role], f"Predecessor did not pass: {role}")
    return folder


def prepare(core, args, plan, seal, *, stream, forecast):
    rows, schedule, manifest, summary = load_data(plan)
    core.load_runtime()
    import torch
    from transformers import AutoModelForCausalLM
    from transformers.optimization import Adafactor

    from latent_workspace.native_memory import NativeMemoryCausalLM
    from latent_workspace.native_owner import NativeOptimizerConfig

    runtime = common.load("run_v16_adapter_full_recovery_02").runtime(core, plan)
    ex.qualification_backend_policy(torch, plan)
    ex.require(
        ex.hashlib.sha256(inspect.getsource(Adafactor.step).encode()).hexdigest()
        == plan["adafactor_step_sha256"],
        "Adafactor implementation",
    )
    ex.require(torch.cuda.device_count() == 1, "One visible CUDA device")
    guard = core.legacy.Guard(plan["resources"], args.output)
    guard("admission", admission=True, forecast_bytes=forecast)
    torch.cuda.set_per_process_memory_fraction(
        plan["resources"]["allocator_cap_gib"]
        * ex.GIB
        / torch.cuda.get_device_properties(0).total_memory
    )
    torch.cuda.reset_peak_memory_stats()
    backbone = plan["backbone"]
    print(f"{args.role}: loading pinned original Mistral", flush=True)
    model = AutoModelForCausalLM.from_pretrained(
        backbone["repository"],
        revision=backbone["revision"],
        local_files_only=True,
        trust_remote_code=False,
        dtype=torch.bfloat16,
        attn_implementation=backbone["attention"],
    ).to("cuda")
    model.config.use_cache = False
    identity = common.original_identity(
        model, backbone["identity"], args.output, legacy_hash=core.legacy.old.prior.state_hash
    )
    model.requires_grad_(True).train()
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    graph = NativeMemoryCausalLM(model, cut=backbone["cut"])
    ex.require(graph.require_full_update() == backbone["parameters"], "All native parameters")
    random.seed(plan["seed"])
    core.np.random.seed(plan["seed"])
    torch.manual_seed(plan["seed"])
    contract = dict(
        source_commit=seal["source_commit"],
        original_base_sha256=identity["state_tree_v1_sha256"],
        data_sha256=ex.plan_hash(dict(manifest_sha256=plan["data_manifest_sha256"], stream=stream)),
        objective=plan["objective"],
    )
    config = NativeOptimizerConfig(**plan["optimizer"])
    ex.write_new(
        args.output / "CONTEXT.json",
        dict(
            contract=contract,
            graph=graph.contract(),
            runtime=runtime,
            optimizer=plan["optimizer"],
            parameter_elements=graph.require_full_update(),
            physical_parameters=len(list(model.parameters())),
            data_manifest=manifest,
            data_summary=summary,
            stream=stream,
            imports=common.engine_imports(seal),
        ),
    )
    guard("original_loaded")
    return graph, rows, schedule, config, contract, guard


def checkpoint(owner, core, args, plan, guard, name):
    ex.require(name in plan["checkpoint_names"], "Allowlisted checkpoint")
    core.snapshot_admission(plan, guard, True)
    receipt = owner.save(args.checkpoints / name)
    ex.require(receipt["bytes"] <= plan["checkpoint_max_bytes"], "Checkpoint forecast exceeded")
    ex.write_new(args.output / f"CHECKPOINT_{name}.json", receipt)
    ex.write_new(args.output / f"STATE_{name}.json", common.fingerprint(owner))
    guard(f"saved:{name}")
    return receipt


def restore(
    graph, config, contract, core, args, plan, guard, reference, name, *, after_restore=None
):
    import torch

    from latent_workspace.native_owner import NativeFullUpdateOwner

    receipt = ex.read(reference / f"CHECKPOINT_{name}.json")
    path = args.checkpoints / name
    ex.require(
        path.stat().st_size == receipt["bytes"] and ex.digest(path) == receipt["sha256"],
        "Checkpoint file receipt",
    )
    core.snapshot_admission(plan, guard, True)
    payload = torch.load(path, map_location="cpu", weights_only=False)
    owner = NativeFullUpdateOwner.restore(
        graph,
        payload,
        config=config,
        expected_run_contract=contract,
        expected_state_sha256=receipt["state_sha256"],
    )
    del payload
    gc.collect()
    common.exact(
        common.fingerprint(owner),
        ex.read(reference / f"STATE_{name}.json"),
        "fresh-process checkpoint state",
    )
    ex.write_new(
        args.output / "RESTORE.json", dict(exact=True, checkpoint=receipt, reference=str(reference))
    )
    if after_restore is not None:
        after_restore(owner, "restore", args.output / "CACHE_restore.json")
        guard("restore:cache_released")
    return owner


def canary(core, args, plan, seal, *, after_boundary=None):
    from latent_workspace.native_owner import NativeFullUpdateOwner
    from latent_workspace.optimizer_state import tree_hash

    graph, rows, schedule, config, contract, guard = prepare(
        core, args, plan, seal, stream="canary", forecast=plan["storage_forecast_bytes"]
    )
    owner = NativeFullUpdateOwner(graph, config=config, run_contract=contract)
    ex.write_new(args.output / "INITIAL.json", common.fingerprint(owner))
    for step, keys in enumerate(schedule["canary"], 1):
        print(f"canary: length-qualified update {step}/2", flush=True)
        common.update(owner, rows, keys, guard, args.output, step, after_spill=after_boundary)
        if step == 1:
            checkpoint(owner, core, args, plan, guard, "canary_step1.pt")
    core.snapshot_admission(plan, guard, True)
    ex.write_new(
        args.output / "STEP2_PAYLOAD.json",
        dict(state_sha256=tree_hash(owner.payload()), weight_file_written=False),
    )
    return dict(
        native_weight_updates=2,
        backward_rows=sum(map(len, schedule["canary"])),
        checkpoints=1,
        **common.peak(),
    )


def replay(core, args, plan, seal, *, after_boundary=None):
    from latent_workspace.optimizer_state import tree_hash

    reference = predecessor(args, "canary", seal)
    graph, rows, schedule, config, contract, guard = prepare(
        core, args, plan, seal, stream="canary", forecast=0
    )
    owner = restore(
        graph,
        config,
        contract,
        core,
        args,
        plan,
        guard,
        reference,
        "canary_step1.pt",
        after_restore=after_boundary,
    )
    actual = common.update(
        owner, rows, schedule["canary"][1], guard, args.output, 2, after_spill=after_boundary
    )
    common.exact(
        actual,
        ex.read(reference / "step2.json"),
        "length-step2 losses/gradients/weights/optimizer/RNG",
    )
    core.snapshot_admission(plan, guard, True)
    state = tree_hash(owner.payload())
    ex.require(
        state == ex.read(reference / "STEP2_PAYLOAD.json")["state_sha256"], "Exact step2 payload"
    )
    ex.write_new(
        args.output / "REPLAY.json", dict(exact=True, state_sha256=state, weight_file_written=False)
    )
    return dict(
        native_weight_updates=1,
        backward_rows=len(schedule["canary"][1]),
        exact_replay=True,
        **common.peak(),
    )


def train_update(owner, rows, keys, guard, output, step, *, after_spill=None):
    """Same owner arithmetic; omit full gradient hashes outside the parity canary."""
    lookup = {r["key"]: r for r in rows}
    owner.begin_window([(key, lookup[key]["supervised_tokens"]) for key in keys])
    receipts = []
    for i, key in enumerate(keys):
        guard(f"step{step}:row{i}:before")
        result = owner.accumulate(
            key, common.batch(lookup[key], next(owner.model.parameters()).device)
        )
        if after_spill is not None:
            after_spill(owner, "spill", output / f"CACHE_step{step}_row{i}.json")
        receipts.append(result)
        ex.write_new(output / f"step{step}_row{i}.json", result)
        guard(f"step{step}:row{i}:spilled")
    guard(f"step{step}:before_update")
    updated = owner.step()
    ex.require(owner.completed_steps == step, "Training step cursor")
    ex.require(any(r["master_changed"] for r in updated["changes"]), "No master changed")
    ex.require(
        sum(r["native_changed_elements"] for r in updated["changes"]) > 0,
        "No visible native change",
    )
    result = dict(rows=receipts, update=updated, state=common.fingerprint(owner))
    ex.write_new(output / f"step{step}.json", result)
    guard(f"step{step}:complete")
    return result


def assert_cursor(owner, rows, windows, step):
    lookup = {r["key"]: r for r in rows}
    expected = [[(k, lookup[k]["supervised_tokens"]) for k in window] for window in windows[:step]]
    common.exact(owner.history, expected, "frozen schedule cursor")
    ex.require(
        owner.completed_steps == step
        and owner.tokens_seen == sum(n for w in expected for _, n in w),
        "Resume token cursor",
    )


def evaluate_dev(graph, rows, keys, guard, output):
    """Fixed teacher-forced dev NLL, not a benchmark/non-regression gate."""
    import torch

    from latent_workspace.optimizer_state import restore_rng, rng_state

    lookup = {r["key"]: r for r in rows}
    before = rng_state()
    results, losses, counts = [], Counter(), Counter()
    try:
        with torch.no_grad():
            for key in keys:
                row = lookup[key]
                ex.require(row["split"] == "dev", "Only frozen development rows")
                guard(f"dev:{key}")
                value = graph(**common.batch(row, next(graph.parameters()).device))
                ex.require(bool(torch.isfinite(value.loss_sum)), "Finite development NLL")
                bucket = row["role"] + ("/" + row["mode"] if row["role"] == "world" else "")
                item = dict(
                    key=key,
                    bucket=bucket,
                    supervised_tokens=value.supervised_tokens,
                    loss_sum=float(value.loss_sum),
                )
                ex.require(
                    value.supervised_tokens == row["supervised_tokens"], "Development denominator"
                )
                results.append(item)
                losses[bucket] += item["loss_sum"]
                counts[bucket] += item["supervised_tokens"]
                del value
    finally:
        restore_rng(before)
    result = dict(
        rows=results,
        tokens_by_bucket=dict(counts),
        mean_nll_by_bucket={k: losses[k] / counts[k] for k in counts},
        interpretation="FIXED_DEV_NLL_ONLY_NOT_NON_REGRESSION",
        new_sequences=0,
    )
    ex.write_new(output, result)
    return result


def train(core, args, plan, seal, *, after_boundary=None):
    from latent_workspace.native_owner import NativeFullUpdateOwner

    reference = predecessor(args, "replay", seal)
    ex.require(ex.read(reference / "REPLAY.json")["exact"] is True, "Exact replay gate")
    first = args.role == "train_a"
    if not first:
        reference = predecessor(args, "train_a", seal)
    graph, rows, schedule, config, contract, guard = prepare(
        core,
        args,
        plan,
        seal,
        stream="training",
        forecast=(2 if first else 1) * plan["checkpoint_max_bytes"],
    )
    if first:
        owner = NativeFullUpdateOwner(graph, config=config, run_contract=contract)
        ex.write_new(args.output / "INITIAL.json", common.fingerprint(owner))
        evaluate_dev(graph, rows, schedule["development"], guard, args.output / "DEV_BASE.json")
    else:
        owner = restore(
            graph,
            config,
            contract,
            core,
            args,
            plan,
            guard,
            reference,
            "training_step16.pt",
            after_restore=after_boundary,
        )
    start, end = (0, 16) if first else (16, 32)
    assert_cursor(owner, rows, schedule["training"], start)
    for step in range(start + 1, end + 1):
        print(f"{args.role}: training update {step}/32", flush=True)
        train_update(
            owner,
            rows,
            schedule["training"][step - 1],
            guard,
            args.output,
            step,
            after_spill=after_boundary,
        )
    assert_cursor(owner, rows, schedule["training"], end)
    checkpoint(owner, core, args, plan, guard, f"training_step{end}.pt")
    if not first:
        evaluate_dev(graph, rows, schedule["development"], guard, args.output / "DEV_STEP32.json")
    return dict(
        native_weight_updates=end - start,
        completed_training_steps=end,
        training_tokens_seen=owner.tokens_seen,
        backward_rows=sum(map(len, schedule["training"][start:end])),
        checkpoints=1,
        exact_resume=not first,
        **common.peak(),
    )


def summary(out, plan):
    ends = {role: ex.read(out / role / "FINISHED.json") for role in ROLES}
    for role, updates in (("canary", 2), ("replay", 1), ("train_a", 16), ("train_b", 16)):
        ex.require(
            ends[role]["status"] == STATUSES[role]
            and ends[role]["native_weight_updates"] == updates,
            "Completed role/update count",
        )
    final = ends["train_b"]["outcome"]
    ex.require(
        final["completed_training_steps"] == 32
        and final["training_tokens_seen"] == plan["planned_training_tokens"],
        "Training completion denominator",
    )
    return dict(
        native_weight_updates=35,
        training_updates=32,
        engineering_updates=2,
        replay_updates=1,
        training_tokens=final["training_tokens_seen"],
        retained_checkpoints=3,
        non_regression="NOT_ESTABLISHED",
        old_expression_gate="FAIL",
        winner="none",
    )


RUN = ex.SealedRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass=TINY_PASS,
    roles=ROLES,
    role_status=STATUSES,
    validate=validate,
    load=common.load,
    updates_native=True,
)

if __name__ == "__main__":
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    os.environ["LTWS_CPU_SDPA_BACKEND"] = "math"
    raise SystemExit(
        RUN.main(dict(canary=canary, replay=replay, train_a=train, train_b=train), summary)
    )
