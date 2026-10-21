#!/usr/bin/env python3
"""Matched P=0/P=1 full FT, using the one native owner and unchanged V22 rows.

Fresh processes: targets -> positive-P canary -> exact replay -> off -> on.
No retry, new sequences, judge, data expansion, automatic deletion or release.
"""

from __future__ import annotations

import copy
import gc
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import run_native_7b_canary as common  # noqa: E402
import run_v22_full_ft as previous  # noqa: E402
from run_v22_full_ft_recovery01 import boundary  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402

ENTRY = "scripts/run_v23_preservation_ft.py"
PLAN = "configs/v23/PRESERVATION_FT_01.json"
ROLES = ("teacher", "canary", "replay", "off", "on")
STATUSES = {r: f"V23_PRESERVATION_{r.upper()}_COMPLETE" for r in ROLES}
PASS = "V23_MATCHED_P_OFF_ON_32_STEPS_COMPLETE_NOT_QUALITY"


def validate(plan):
    ex.require(plan["schema"] == "ltws-v23-preservation-ft-01" and plan["no_retry"], "Plan")
    ex.require(plan["pass_status"] == PASS, "Terminal policy")
    reference = ex.read(ROOT / plan["reference_plan"])
    ex.require(ex.plan_hash(reference) == plan["reference_plan_sha256"], "Frozen V22 reference")
    ex.require(plan["coefficients"] == {"off": 0.0, "on": 1.0}, "Predeclared P contrast")
    ex.require(
        plan["checkpoint_names"] == ["canary_step1.pt", "off_step32.pt", "on_step32.pt"],
        "Exactly three planned saves",
    )
    ex.require(
        plan["vocabulary"] == 32768
        and plan["target_dtype"] == "float32"
        and plan["temperature"] == 1.0,
        "Uncompressed full-vocabulary target policy",
    )
    ex.require(plan["resources"] == reference["resources"], "Unchanged resource limits")
    ex.require(
        plan["training_updates_per_arm"] == 32
        and plan["training_tokens_per_arm"] == 20860
        and plan["training_rows_per_arm"] == 723,
        "Unchanged training budget",
    )
    ex.require(
        all(plan[k] == 0 for k in ("new_sequences", "judge_calls", "weight_deletions")),
        "No generation/judge/deletion",
    )


def numerical_plan(plan, value):
    result = copy.deepcopy(ex.read(ROOT / plan["reference_plan"]))
    result["objective"] = value
    result["checkpoint_names"] = plan["checkpoint_names"]
    return result


def registry(rows, schedule, plan):
    lookup = {r["key"]: r for r in rows}
    keys = sorted({k for stream in ("canary", "training") for w in schedule[stream] for k in w})
    registered = [lookup[k] for k in keys]
    eligible = [r["key"] for r in registered if r["role"] in ("instruction", "prose", "code")]
    ex.require(
        all(r["split"] == "train" and r["language"] == "en" for r in registered),
        "Train-only registry; never dev/confirmation targets",
    )
    ex.require(all(lookup[k]["memory_ids"] == [] for k in eligible), "Ordinary no-memory host")
    ex.require(
        len(registered) == plan["registered_rows"]
        and len(eligible) == plan["teacher_rows"]
        and sum(lookup[k]["supervised_tokens"] for k in eligible) == plan["teacher_positions"],
        "Frozen target census",
    )
    for name in ("canary", "training"):
        totals = [
            sum(lookup[k]["supervised_tokens"] for k in w if k in eligible) for w in schedule[name]
        ]
        ex.require(
            min(totals) > 0 and sum(totals) == plan[f"{name}_preservation_tokens"],
            "Positive eligible denominator for every frozen window",
        )
    return registered, eligible


def predecessor(args, role, seal):
    path = args.output.parent / role
    start, end = ex.read(path / "STARTED.json"), ex.read(path / "FINISHED.json")
    files = ex.manifest(path)
    files.pop("FINISHED.json")
    ex.require(
        start["seal"] == seal
        and start["role"] == role
        and end["files"] == files
        and end["status"] == STATUSES[role],
        "Exact completed predecessor",
    )
    return path


def targets(args, plan, seal):
    from latent_workspace.preservation_objective import PreservationTargets

    teacher = predecessor(args, "teacher", seal)
    setup = numerical_plan(plan, "query_only_token_weighted_causal_nll")
    rows, schedule, _, _ = previous.load_data(setup)
    registered, eligible = registry(rows, schedule, plan)
    receipt = ex.read(teacher / "TEACHER_TARGETS.json")
    ex.require(
        receipt["source_commit"] == seal["source_commit"]
        and receipt["native_sha256"] == setup["backbone"]["identity"]["state_tree_v1_sha256"]
        and receipt["teacher_policy"] == plan["teacher_policy"],
        "Frozen teacher execution",
    )
    # The expected digest comes from a source-verified completed predecessor, not
    # solely from the target file's self-description. No old audit bank fallback.
    return PreservationTargets.load(
        teacher / "PRIVATE_TEACHER_TARGETS.safetensors",
        receipt,
        registered,
        eligible,
        expected_receipt_plan_sha256=ex.plan_hash(receipt),
    )


def teacher(core, args, plan, seal):
    import torch
    from safetensors.torch import save_file

    from latent_workspace.optimizer_state import restore_rng, rng_state, tree_hash

    setup = numerical_plan(plan, "query_only_token_weighted_causal_nll")
    forecast = 3 * setup["checkpoint_max_bytes"] + plan["target_file_max_bytes"]
    graph, rows, schedule, _, contract, guard = previous.prepare(
        core, args, setup, seal, stream="training", forecast=forecast
    )
    registered, eligible = registry(rows, schedule, plan)
    lookup = {r["key"]: r for r in registered}
    tensors, index = {}, []
    before_rng = rng_state()
    graph.eval()
    with torch.no_grad():
        for i, key in enumerate(eligible):
            guard(f"teacher:{i}")
            row = lookup[key]
            data = common.batch(row, "cuda")
            result = graph(**data)
            active = data["labels"][:, 1:] != -100
            value = result.logits[:, :-1][active].float().log_softmax(-1).cpu().contiguous()
            ex.require(
                value.shape == (row["supervised_tokens"], plan["vocabulary"])
                and bool(torch.isfinite(value).all()),
                "Finite full target tensor",
            )
            tensors[str(i)] = value
            index.append(
                dict(
                    index=str(i),
                    key=key,
                    row_sha256=ex.plan_hash(row),
                    supervised_tokens=row["supervised_tokens"],
                    shape=list(value.shape),
                )
            )
            del result, data, value
    graph.train()
    sentinels = []
    # Every selected complete context, same unchanged weights, eval teacher vs
    # training-mode forward. This is a numerical sentinel, not a quality gate.
    with torch.no_grad():
        for i, key in enumerate(eligible):
            guard(f"same_weight:{i}")
            data = common.batch(lookup[key], "cuda")
            result = graph(**data)
            active = data["labels"][:, 1:] != -100
            actual = result.logits[:, :-1][active].float().log_softmax(-1).cpu()
            target = tensors[str(i)]
            kl = (target.exp() * (target - actual)).sum(-1)
            ex.require(bool(torch.isfinite(kl).all()), "Finite same-weight sentinel")
            sentinels.append(
                dict(
                    key=key,
                    targets=len(kl),
                    mean_kl=float(kl.mean()),
                    max_abs_log_probability_difference=float((target - actual).abs().max()),
                    bitwise_log_probabilities=torch.equal(actual, target),
                )
            )
            del data, result, actual, target, kl
    restore_rng(before_rng)
    path = args.output / "PRIVATE_TEACHER_TARGETS.safetensors"
    ex.require(not path.exists(), "Exclusive teacher targets")
    save_file(tensors, str(path))
    tensor_bytes = sum(t.numel() * 4 for t in tensors.values())
    ex.require(
        tensor_bytes == plan["teacher_tensor_bytes"]
        and path.stat().st_size <= plan["target_file_max_bytes"],
        "Target storage forecast",
    )
    receipt = dict(
        native_sha256=contract["original_base_sha256"],
        source_commit=seal["source_commit"],
        input_sha256=ex.plan_hash(registered),
        rows=index,
        bytes=path.stat().st_size,
        sha256=ex.digest(path),
        tensor_bytes=tensor_bytes,
        teacher_policy=plan["teacher_policy"],
        vocabulary=plan["vocabulary"],
        target_dtype=plan["target_dtype"],
        temperature=1.0,
    )
    ex.write_new(args.output / "TEACHER_TARGETS.json", receipt)
    ex.write_new(args.output / "SAME_WEIGHT_SENTINELS.json", sentinels)
    ex.require(
        tree_hash(graph.model.state_dict()) == contract["original_base_sha256"],
        "Teacher never updates native weights",
    )
    guard("teacher_complete")
    return dict(
        native_weight_updates=0,
        teacher_rows=len(index),
        target_positions=18727,
        target_tensor_bytes=tensor_bytes,
        **common.peak(),
    )


def prepare_owner(core, args, plan, seal, *, stream, forecast, enabled):
    from latent_workspace.preservation_objective import objective

    bank = targets(args, plan, seal) if enabled else None
    setup = numerical_plan(plan, objective(plan["coefficients"]["on" if enabled else "off"], bank))
    values = previous.prepare(core, args, setup, seal, stream=stream, forecast=forecast)
    return (*values, bank, setup)


def checkpoint(owner, core, args, setup, guard, name):
    receipt = previous.checkpoint(owner, core, args, setup, guard, name)
    if owner.preservation is not None:
        ex.write_new(
            args.output / f"PRESERVATION_{name}.json",
            dict(tokens_seen=owner.preservation_tokens_seen, history=owner.preservation_history),
        )
    return receipt


def canary(core, args, plan, seal):
    from latent_workspace.native_owner import NativeFullUpdateOwner
    from latent_workspace.optimizer_state import tree_hash

    graph, rows, schedule, config, contract, guard, bank, setup = prepare_owner(
        core,
        args,
        plan,
        seal,
        stream="canary",
        forecast=3 * plan["checkpoint_max_bytes"],
        enabled=True,
    )
    owner = NativeFullUpdateOwner(graph, config=config, run_contract=contract, preservation=bank)
    ex.write_new(args.output / "INITIAL.json", common.fingerprint(owner))
    for step, keys in enumerate(schedule["canary"], 1):
        common.update(owner, rows, keys, guard, args.output, step, after_spill=boundary)
        if step == 1:
            checkpoint(owner, core, args, setup, guard, "canary_step1.pt")
    core.snapshot_admission(setup, guard, True)
    ex.write_new(args.output / "STEP2_PAYLOAD.json", dict(state_sha256=tree_hash(owner.payload())))
    return dict(
        native_weight_updates=2,
        preservation_tokens_seen=owner.preservation_tokens_seen,
        **common.peak(),
    )


def replay(core, args, plan, seal):
    import torch

    from latent_workspace.native_owner import NativeFullUpdateOwner
    from latent_workspace.optimizer_state import tree_hash

    reference = predecessor(args, "canary", seal)
    graph, rows, schedule, config, contract, guard, bank, setup = prepare_owner(
        core,
        args,
        plan,
        seal,
        stream="canary",
        forecast=2 * plan["checkpoint_max_bytes"],
        enabled=True,
    )
    receipt = ex.read(reference / "CHECKPOINT_canary_step1.pt.json")
    path = args.checkpoints / "canary_step1.pt"
    ex.require(
        path.stat().st_size == receipt["bytes"] and ex.digest(path) == receipt["sha256"],
        "Exact checkpoint file",
    )
    core.snapshot_admission(setup, guard, True)
    payload = torch.load(path, map_location="cpu", weights_only=False)
    owner = NativeFullUpdateOwner.restore(
        graph,
        payload,
        config=config,
        expected_run_contract=contract,
        expected_state_sha256=receipt["state_sha256"],
        preservation=bank,
    )
    del payload
    gc.collect()
    common.exact(
        common.fingerprint(owner),
        ex.read(reference / "STATE_canary_step1.pt.json"),
        "Checkpoint native/master/moments/RNG",
    )
    common.exact(
        dict(tokens_seen=owner.preservation_tokens_seen, history=owner.preservation_history),
        ex.read(reference / "PRESERVATION_canary_step1.pt.json"),
        "Checkpoint KL cursor",
    )
    boundary(owner, "restore", args.output / "CACHE_restore.json")
    guard("restore:cache_released")
    actual = common.update(
        owner, rows, schedule["canary"][1], guard, args.output, 2, after_spill=boundary
    )
    common.exact(actual, ex.read(reference / "step2.json"), "Exact update/row/gradient replay")
    core.snapshot_admission(setup, guard, True)
    state = tree_hash(owner.payload())
    ex.require(
        state == ex.read(reference / "STEP2_PAYLOAD.json")["state_sha256"], "Exact full v2 payload"
    )
    ex.write_new(args.output / "REPLAY.json", dict(exact=True, state_sha256=state))
    return dict(native_weight_updates=1, exact_replay=True, **common.peak())


def train(core, args, plan, seal):
    from latent_workspace.native_owner import NativeFullUpdateOwner

    reference = predecessor(args, "replay", seal)
    ex.require(ex.read(reference / "REPLAY.json")["exact"] is True, "New objective replay gate")
    enabled = args.role == "on"
    if enabled:
        predecessor(args, "off", seal)
    graph, rows, schedule, config, contract, guard, bank, setup = prepare_owner(
        core,
        args,
        plan,
        seal,
        stream="training",
        forecast=(1 if enabled else 2) * plan["checkpoint_max_bytes"],
        enabled=enabled,
    )
    # Both arms start from the original host, not from the canary or V22 checkpoint.
    owner = NativeFullUpdateOwner(graph, config=config, run_contract=contract, preservation=bank)
    ex.write_new(args.output / "INITIAL.json", common.fingerprint(owner))
    previous.evaluate_dev(
        graph, rows, schedule["development"], guard, args.output / "DEV_BASE.json"
    )
    for step, keys in enumerate(schedule["training"], 1):
        print(f"{args.role}: update {step}/32", flush=True)
        previous.train_update(owner, rows, keys, guard, args.output, step, after_spill=boundary)
    previous.assert_cursor(owner, rows, schedule["training"], 32)
    if enabled:
        ex.require(
            owner.preservation_tokens_seen == plan["training_preservation_tokens"],
            "Complete KL exposure cursor",
        )
    checkpoint(owner, core, args, setup, guard, f"{args.role}_step32.pt")
    previous.evaluate_dev(
        graph, rows, schedule["development"], guard, args.output / "DEV_STEP32.json"
    )
    return dict(
        native_weight_updates=32,
        training_tokens_seen=owner.tokens_seen,
        preservation_tokens_seen=owner.preservation_tokens_seen,
        backward_rows=723,
        checkpoints=1,
        **common.peak(),
    )


def summary(out, plan):
    counts = {"teacher": 0, "canary": 2, "replay": 1, "off": 32, "on": 32}
    for role, count in counts.items():
        result = ex.read(out / role / "FINISHED.json")
        ex.require(
            result["status"] == STATUSES[role] and result["native_weight_updates"] == count,
            "Finite completed roles",
        )
    for role in ("off", "on"):
        end = ex.read(out / role / "FINISHED.json")["outcome"]
        ex.require(
            end["training_tokens_seen"] == 20860 and end["backward_rows"] == 723,
            "Matched training exposure",
        )
    common.exact(
        ex.read(out / "off/DEV_BASE.json"),
        ex.read(out / "on/DEV_BASE.json"),
        "Identical base development forward",
    )
    left, right = (ex.read(out / role / "INITIAL.json") for role in ("off", "on"))
    common.exact(left, right, "Identical initial native/master/optimizer/RNG/execution")
    return dict(
        native_weight_updates=67,
        engineering_updates=2,
        replay_updates=1,
        training_updates=64,
        training_updates_per_arm=32,
        retained_checkpoints=3,
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
    )


RUN = ex.SealedRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass="TINY_V23_PRESERVATION_OWNER_PASS_NOT_7B",
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
        RUN.main(dict(teacher=teacher, canary=canary, replay=replay, off=train, on=train), summary)
    )
