#!/usr/bin/env python3
"""New source/attempt: separate host snapshots from real-file disk forecasts."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from qualification_isolation import isolate_cli_before_imports  # noqa: E402

isolate_cli_before_imports()
import native_snapshot_admission as snapshots  # noqa: E402
import run_v24_recruitment_ft03 as previous  # noqa: E402
from qualification_isolation_v2 import IsolatedQualificationMixin  # noqa: E402

# Qualification mocks of historical runners cannot mutate this private dispatcher.
spec = importlib.util.spec_from_file_location(
    f"_v24_ft04_body_{__name__}", ROOT / "scripts/run_v24_recruitment_ft.py"
)
body = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = body
spec.loader.exec_module(body)
ex, common, prior, boundary = body.ex, body.common, body.prior, body.boundary
ENTRY = "scripts/run_v24_recruitment_ft04.py"
PLAN = "configs/v24/RECRUITMENT_FT_04.json"
ADDED_TESTS = ["tests/test_native_snapshot_admission.py", "tests/test_v24_recruitment_ft04.py"]
STORAGE_POLICY = (
    "Checks save one bounded 28-GiB canary with the unchanged 32-GiB real-write reserve. "
    "Memory-only payload hashing and checkpoint reading forecast zero new tensor bytes, "
    "while retaining the independent host snapshot reserve and 50-GiB disk floor. "
    "Training remains gated on exact replay and separate spent-canary retirement; "
    "two bounded finals require 28+32+50=110 GiB before the first arm. No auto-delete."
)
RECOVERY = dict(
    original_source="09addc856ba6f10da31054f1674c7547b1ab91ad",
    original_terminal="provenance/engineering/v24_recruitment_ft03_20261023/furnace/raw/FINISHED.json",
    original_terminal_sha256="6aa7c9f5c3296f5588170261b92c3298faf816c5c5d8ec0c5aee6daf61f2eb7f",
    change=(
        "Explicit memory-only versus file-write admission; "
        "original host/GPU/disk floors and numerical recipe unchanged"
    ),
    write_reserve_bytes=32 * ex.GIB,
    checkpoint_read_forecast_bytes=0,
    payload_hash_forecast_bytes=0,
)


def validate(plan):
    old = ex.read(ROOT / previous.PLAN)
    previous.validate(old)
    body.validate(plan)
    fields = {
        "qualification_cases",
        "qualification_test_files",
        "storage_policy",
        "storage_recovery",
    }
    ex.require(
        {k: v for k, v in plan.items() if k not in fields}
        == {k: v for k, v in old.items() if k not in fields},
        "No numerical, data, safety, audit or claim changes",
    )
    ex.require(
        plan["qualification_test_files"] == old["qualification_test_files"] + ADDED_TESTS,
        "All original tests retained",
    )
    ex.require(plan["qualification_cases"] == 643, "Expanded exact qualification count")
    ex.require(
        plan["storage_recovery"] == RECOVERY and plan["storage_policy"] == STORAGE_POLICY,
        "Explicit storage accounting recovery",
    )
    ex.require(
        ex.digest(ROOT / RECOVERY["original_terminal"]) == RECOVERY["original_terminal_sha256"],
        "Original FT03 failure preserved",
    )


def canary(core, args, plan, seal):
    from latent_workspace.native_owner import NativeFullUpdateOwner

    graph, rows, schedule, config, contract, guard, setup = body.prepare(
        core,
        args,
        plan,
        seal,
        "canary",
        snapshots.future_write_bytes(plan["checkpoint_max_bytes"], 1),
    )
    owner = NativeFullUpdateOwner(graph, config=config, run_contract=contract)
    ex.write_new(args.output / "INITIAL.json", common.fingerprint(owner))
    for step, keys in enumerate(schedule["canary"], 1):
        common.update(owner, rows, keys, guard, args.output, step, after_spill=boundary)
        if step == 1:
            snapshots.checkpoint(owner, core, args, setup, guard, "canary_step1.pt")
    ex.write_new(
        args.output / "STEP2_PAYLOAD.json",
        dict(state_sha256=snapshots.payload_sha(owner, core, setup, guard)),
    )
    return dict(
        native_weight_updates=2,
        backward_rows=sum(map(len, schedule["canary"])),
        checkpoints=1,
        **common.peak(),
    )


def replay(core, args, plan, seal):
    reference = body.predecessor(args, "canary", seal)
    graph, rows, schedule, config, contract, guard, setup = body.prepare(
        core, args, plan, seal, "canary", 0
    )
    owner = snapshots.restore(
        graph,
        config,
        contract,
        core,
        args,
        setup,
        guard,
        reference,
        "canary_step1.pt",
        after_restore=boundary,
    )
    actual = common.update(
        owner, rows, schedule["canary"][1], guard, args.output, 2, after_spill=boundary
    )
    common.exact(actual, ex.read(reference / "step2.json"), "Exact next update and row gradients")
    state = snapshots.payload_sha(owner, core, setup, guard)
    ex.require(
        state == ex.read(reference / "STEP2_PAYLOAD.json")["state_sha256"], "Exact next payload"
    )
    ex.write_new(args.output / "REPLAY.json", dict(exact=True, state_sha256=state))
    return dict(native_weight_updates=1, exact_replay=True, **common.peak())


def train(core, args, plan, seal):
    from latent_workspace.native_owner import NativeFullUpdateOwner

    reference = body.predecessor(args, "replay", seal)
    ex.require(ex.read(reference / "REPLAY.json")["exact"] is True, "Canary replay gate")
    body.validate_retirement(args.output.parent, args.checkpoints, seal, plan)
    if args.role == "workspace":
        body.predecessor(args, "inline", seal)
    forecast = snapshots.future_write_bytes(
        plan["checkpoint_max_bytes"], 2 if args.role == "inline" else 1
    )
    graph, rows, schedule, config, contract, guard, setup = body.prepare(
        core, args, plan, seal, args.role, forecast
    )
    owner = NativeFullUpdateOwner(graph, config=config, run_contract=contract)
    ex.write_new(args.output / "INITIAL.json", common.fingerprint(owner))
    prior.evaluate_dev(graph, rows, schedule["development"], guard, args.output / "DEV_BASE.json")
    for step, keys in enumerate(schedule["training"], 1):
        print(f"{args.role}: update {step}/32", flush=True)
        prior.train_update(owner, rows, keys, guard, args.output, step, after_spill=boundary)
    prior.assert_cursor(owner, rows, schedule["training"], 32)
    ex.require(owner.tokens_seen == plan["training_tokens_per_arm"], "Complete matched budget")
    snapshots.checkpoint(owner, core, args, setup, guard, f"{args.role}_step32.pt")
    prior.evaluate_dev(graph, rows, schedule["development"], guard, args.output / "DEV_STEP32.json")
    return dict(
        native_weight_updates=32,
        training_tokens_seen=owner.tokens_seen,
        backward_rows=sum(map(len, schedule["training"])),
        checkpoints=1,
        **common.peak(),
    )


class RouteRun(IsolatedQualificationMixin, ex.SealedRun):
    pass


RUN = RouteRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass="V24_ROUTE_FT_TINY_PASS_NOT_7B",
    roles=body.ROLES,
    role_status=body.STATUSES,
    validate=validate,
    load=common.load,
    updates_native=True,
)
body.RUN, body.ENTRY = RUN, ENTRY
body.BODIES = dict(canary=canary, replay=replay, inline=train, workspace=train)


if __name__ == "__main__":
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    os.environ["LTWS_CPU_SDPA_BACKEND"] = "math"
    raise SystemExit(body.main())
