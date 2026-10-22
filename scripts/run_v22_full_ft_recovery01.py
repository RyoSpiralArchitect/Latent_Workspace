#!/usr/bin/env python3
"""New sealed cache-boundary trial, split around separately authorized storage work.

No old execution directory is reused. Each phase is exclusive and stops on its
first failure. This program never deletes weights or retries any role.
"""

from __future__ import annotations

import argparse
import functools
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_v22_full_ft as prior  # noqa: E402

ex, common = prior.ex, prior.common
ENTRY = "scripts/run_v22_full_ft_recovery01.py"
PLAN = "configs/v22/FULL_FT_RECOVERY_01.json"
PLAN_SHA256 = "08eed8cc63138916302830f549d4cb4320c9c9493ca2e91a6c80b271cd1244ec"
CHECKS_PASS = "V22_RECOVERY_CHECKS_COMPLETE_NOT_TRAINING"


def validate(plan):
    ex.require(ex.plan_hash(plan) == PLAN_SHA256, "Frozen recovery plan changed")
    old = ex.read(ROOT / plan["execution_reference_plan"])
    prior.validate(old)
    ex.require(ex.plan_hash(old) == plan["execution_reference_plan_sha256"], "Original V22 plan")
    changed = {
        "schema",
        "storage_forecast_bytes",
        "qualification_cases",
        "qualification_test_files",
        "scope",
        "execution_reference_plan",
        "execution_reference_plan_sha256",
        "storage_policy",
        "cache_policy",
        "recovery_of",
    }
    ex.require(
        {k: v for k, v in plan.items() if k not in changed}
        == {k: v for k, v in old.items() if k not in changed},
        "Unchanged numerical, data, resource and quality conditions",
    )
    ex.require(plan["storage_forecast_bytes"] == plan["checkpoint_max_bytes"], "One canary save")
    ex.require(
        plan["qualification_test_files"][: len(old["qualification_test_files"])]
        == old["qualification_test_files"],
        "No qualification exclusions",
    )
    recovery = plan["recovery_of"]
    ex.require(ex.digest(ROOT / recovery["terminal"]) == recovery["terminal_sha256"], "Old failure")


def boundary(owner, kind, output):
    from latent_workspace.cuda_cache import release_unused_cache

    ex.write_new(output, release_unused_cache(owner, kind))


BODIES = {
    "canary": functools.partial(prior.canary, after_boundary=boundary),
    "replay": functools.partial(prior.replay, after_boundary=boundary),
    "train_a": functools.partial(prior.train, after_boundary=boundary),
    "train_b": functools.partial(prior.train, after_boundary=boundary),
}
RUN = ex.SealedRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass=prior.TINY_PASS,
    roles=prior.ROLES,
    role_status=prior.STATUSES,
    validate=validate,
    load=common.load,
    updates_native=True,
)


def check_phase_gate(folder, seal, plan):
    start, end = ex.read(folder / "STARTED.json"), ex.read(folder / "FINISHED.json")
    files = ex.manifest(folder)
    files.pop("FINISHED.json")
    ex.require(start["seal"] == seal and start["plan"] == plan, "Same-source checks phase")
    ex.require(
        end["files"] == files
        and end["status"] == CHECKS_PASS
        and end["completed_roles"] == ["canary", "replay"],
        "Successful complete checks phase",
    )
    raw = folder.parent / "raw"
    for role in ("canary", "replay"):
        args = argparse.Namespace(output=raw / "train_a")
        prior.predecessor(args, role, seal)
        ex.require(end["role_manifests"][role] == ex.manifest(raw / role), "Checks role unchanged")
    ex.require(ex.read(raw / "replay/REPLAY.json")["exact"] is True, "Exact replay gate")


def dispatch_phase(args, *, training):
    source, core, seal, check, plan = RUN.preflight(args)
    qualified = RUN.qualification(args.qualification, seal, plan)
    out, ckpt = args.output.resolve(), args.checkpoints.resolve()
    ex.require(out.name == "raw" and ckpt.parent == out.parent, "Fixed recovery layout")
    ex.require(not out.is_relative_to(ROOT) and not ckpt.is_relative_to(ROOT), "Outside source")
    phase = out.parent / ("training" if training else "checks")
    ex.require(not phase.exists(), "Exclusive phase: no rerun or resume")
    if training:
        check_phase_gate(out.parent / "checks", seal, plan)
        ex.require(not (out / "FINISHED.json").exists(), "No terminal trial reuse")
        start = ex.read(out / "STARTED.json")
        ex.require(start["seal"] == seal and start["plan"] == plan, "Same recovery trial")
        ex.require(start["checkpoints"] == str(ckpt) and ckpt.is_dir(), "Same checkpoint root")
    else:
        ex.require(not out.exists() and not ckpt.exists(), "Fresh destinations only")
        out.mkdir(parents=True, exist_ok=False)
        ckpt.mkdir(parents=True, exist_ok=False)
        ex.write_new(
            out / "STARTED.json",
            dict(
                seal=seal,
                plan=plan,
                source_check=check,
                qualification=qualified,
                pid=os.getpid(),
                checkpoints=str(ckpt),
                controller="exclusive-two-phase-v1",
            ),
        )
    roles = ("train_a", "train_b") if training else ("canary", "replay")
    ex.require(all(not (out / r).exists() for r in roles), "No role reuse")
    phase.mkdir(exist_ok=False)
    ex.write_new(phase / "STARTED.json", dict(seal=seal, plan=plan, roles=roles, pid=os.getpid()))
    args.output, args.checkpoints = out, ckpt
    began = time.monotonic()
    result = dict(status=ex.INCOMPLETE, completed_roles=[], **ex.CEILING)
    result["native_weight_updates"] = None
    try:
        for role in roles:
            command = RUN.role_command(args, role)
            with (out / f"{role}.log").open("x") as log:
                child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
                ex.write_new(out / f"DISPATCH_{role}.json", dict(pid=child.pid, command=command))
                code = child.wait()
            ex.require(code == 0, f"{role} exited {code}; no later role or retry dispatched")
            prior.predecessor(argparse.Namespace(output=out / role), role, seal)
            result["completed_roles"].append(role)
        result["role_manifests"] = {r: ex.manifest(out / r) for r in roles}
        if training:
            result["summary"] = prior.summary(out, plan)
        source.verify(ROOT, seal, ENTRY)
        ex.require(core.identity() == seal, "Source changed during phase")
        ex.require(RUN.qualification(args.qualification, seal, plan) == qualified, "Qualification")
        result["native_weight_updates"] = 32 if training else 3
        result["status"] = plan["pass_status"] if training else CHECKS_PASS
    except BaseException as exc:
        result.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    result["elapsed_seconds"] = time.monotonic() - began
    result["files"] = ex.manifest(phase)
    ex.write_new(phase / "FINISHED.json", result)
    if training or result["status"] != CHECKS_PASS:
        terminal = {k: v for k, v in result.items() if k not in ("files", "role_manifests")}
        if training:
            terminal["completed_roles"] = ["canary", "replay", *result["completed_roles"]]
            if result["status"] == plan["pass_status"]:
                terminal["native_weight_updates"] = 35
        terminal["files"] = ex.manifest(out)
        ex.write_new(out / "FINISHED.json", terminal)
    print(
        ex.canonical({k: v for k, v in result.items() if k not in ("files", "role_manifests")}),
        flush=True,
    )
    return int(result["status"] == ex.INCOMPLETE)


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("dispatch-checks", "dispatch-training"):
        parser = argparse.ArgumentParser()
        parser.add_argument("command", choices=("dispatch-checks", "dispatch-training"))
        for name in ("seal", "output", "qualification", "checkpoints"):
            parser.add_argument(f"--{name}", type=Path, required=True)
        args = parser.parse_args()
        return dispatch_phase(args, training=args.command == "dispatch-training")
    ex.require("dispatch" not in sys.argv[1:], "Use exclusive checks/training phases")
    return RUN.main(BODIES, prior.summary)


if __name__ == "__main__":
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    os.environ["LTWS_CPU_SDPA_BACKEND"] = "math"
    raise SystemExit(main())
