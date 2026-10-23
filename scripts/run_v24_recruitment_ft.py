#!/usr/bin/env python3
"""Same native owner, paired input routes, separate qualification/storage phases.

No generation, judge, automatic deletion, retry or quality promotion. A spent
canary must be separately retired and journaled before either scientific arm.
"""

from __future__ import annotations

import argparse
import inspect
import os
import random
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from qualification_isolation import (  # noqa: E402
    IsolatedQualificationMixin,
    isolate_cli_before_imports,
)

isolate_cli_before_imports()
import run_native_7b_canary as common  # noqa: E402
import run_v22_full_ft as prior  # noqa: E402
from run_v22_full_ft_recovery01 import boundary  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402
from latent_workspace import recruitment_bank as bank  # noqa: E402

ENTRY = "scripts/run_v24_recruitment_ft.py"
PLAN = "configs/v24/RECRUITMENT_FT_01.json"
ROLES = ("canary", "replay", "inline", "workspace")
STATUSES = {r: f"V24_RECRUITMENT_{r.upper()}_COMPLETE" for r in ROLES}
PASS = "V24_ROUTE_FT_32_EACH_COMPLETE_NOT_QUALITY"
CHECKS_PASS = "V24_ROUTE_CHECKS_COMPLETE_NOT_TRAINING"


def validate(plan):
    ex.require(
        plan["schema"] == "ltws-v24-recruitment-ft-01" and plan["no_retry"], "Frozen protocol"
    )
    ex.require(
        plan["pass_status"] == PASS and plan["routes"] == list(bank.ROUTES), "Route contrast"
    )
    reference = ex.read(ROOT / plan["reference_plan"])
    ex.require(
        ex.plan_hash(reference) == plan["reference_plan_sha256"], "Original numerical recipe"
    )
    for field in ("resources", "checkpoint_max_bytes"):
        ex.require(plan[field] == reference[field], f"Unchanged {field}")
    ex.require(
        plan["preservation_coefficient"] == 0.0 and plan["training_updates_per_arm"] == 32,
        "Fixed P and updates",
    )
    ex.require(
        plan["checkpoint_names"] == ["canary_step1.pt", "inline_step32.pt", "workspace_step32.pt"],
        "Three explicit saves",
    )
    ex.require(
        plan["new_sequences"] == plan["judge_calls"] == plan["weight_deletions"] == 0,
        "No generation/judge/deletion",
    )
    ex.require(
        ex.plan_hash(ex.read(ROOT / plan["recipe"])) == plan["recipe_sha256"], "Frozen recipe"
    )


def numerical_plan(plan):
    value = ex.read(ROOT / plan["reference_plan"])
    value["checkpoint_names"] = plan["checkpoint_names"]
    return value


def load_data(plan, stream):
    folder = Path(plan["data_bundle"])
    ex.require(folder.is_absolute() and folder.resolve() == folder, "Exact data path")
    ex.require(
        ex.digest(folder / "MANIFEST.json") == plan["data_manifest_sha256"], "Frozen route bank"
    )
    manifest = ex.read(folder / "MANIFEST.json")
    files = ex.manifest(folder)
    files.pop("MANIFEST.json")
    ex.require(files == manifest["files"], "Full input bytes/file set")
    for path, sha in manifest["source"].items():
        ex.require(ex.digest(ROOT / path) == sha, "Prepared data implementation unchanged")
    end_path = folder.parent / "FINISHED.json"
    ex.require(
        ex.digest(end_path) == plan["preparation_terminal_sha256"], "Completed preparation receipt"
    )
    end = ex.read(end_path)
    ex.require(end["status"] == "V24_ROUTE_BANK_PREPARED_NO_7B_OR_TRAINING", "Preparation passed")
    ex.require(
        manifest["source_commit"] == plan["preparation_source_commit"], "Preparation provenance"
    )
    summary = ex.read(folder / "SUMMARY.json")
    for field in ("training_updates_per_arm", "training_rows_per_arm", "training_tokens_per_arm"):
        ex.require(summary[field] == plan[field], f"Frozen {field}")
    recipe = ex.read(ROOT / plan["recipe"])
    ex.require(ex.read(folder / "PLAN.json") == recipe, "Same recipe")
    routes = {r: ex.read_gz(folder / f"PRIVATE_{r}.json.gz") for r in bank.ROUTES}
    bank.match_routes(routes["inline"], routes["workspace"])
    schedule = ex.read(folder / "SCHEDULE.json")
    for rows in routes.values():
        ex.require(
            bank.schedule(rows, recipe) == schedule["training"], "Exact matched schedule replay"
        )
    rows = ex.read_gz(folder / "PRIVATE_CANARY.json.gz") if stream == "canary" else routes[stream]
    lookup = {r["key"]: r for r in rows}
    ex.require(len(lookup) == len(rows), "Unique registry")
    for row in rows:
        ids, labels = row["input_ids"], row["labels"]
        ex.require(
            len(ids) == len(labels) <= 1024 and len(row["memory_ids"]) <= 128,
            "Untruncated qualified lengths",
        )
        ex.require(
            labels[0] == -100 and [t for t in labels if t != -100] == row["target_ids"],
            "Causal target identity",
        )
        ex.require(
            all(t == -100 or t == i for t, i in zip(labels, ids, strict=True)), "Label alignment"
        )
        ex.require(len(row["target_ids"]) == row["supervised_tokens"] > 0, "Target denominator")
        ex.require(
            row["split"] in ("train", "dev") and row["language"] == "en", "No heldout registry"
        )
    windows = schedule["canary" if stream == "canary" else "training"]
    ex.require(all(lookup[k]["split"] == "train" for w in windows for k in w), "No heldout update")
    return rows, schedule, manifest, summary


def predecessor(args, role, seal):
    folder = args.output.parent / role
    start, end = ex.read(folder / "STARTED.json"), ex.read(folder / "FINISHED.json")
    files = ex.manifest(folder)
    files.pop("FINISHED.json")
    ex.require(
        start["seal"] == seal
        and start["role"] == role
        and end["files"] == files
        and end["status"] == STATUSES[role],
        "Exact successful predecessor",
    )
    return folder


def prepare(core, args, plan, seal, stream, forecast):
    rows, schedule, manifest, summary = load_data(plan, stream)
    setup = numerical_plan(plan)
    core.load_runtime()
    import torch
    from transformers import AutoModelForCausalLM
    from transformers.optimization import Adafactor

    from latent_workspace.native_memory import NativeMemoryCausalLM
    from latent_workspace.native_owner import NativeOptimizerConfig

    runtime = common.load("run_v16_adapter_full_recovery_02").runtime(core, setup)
    ex.qualification_backend_policy(torch, setup)
    ex.require(
        ex.hashlib.sha256(inspect.getsource(Adafactor.step).encode()).hexdigest()
        == setup["adafactor_step_sha256"],
        "Adafactor source",
    )
    ex.require(torch.cuda.device_count() == 1, "One visible device")
    guard = core.legacy.Guard(plan["resources"], args.output)
    guard("admission", admission=True, forecast_bytes=forecast)
    torch.cuda.set_per_process_memory_fraction(
        plan["resources"]["allocator_cap_gib"]
        * ex.GIB
        / torch.cuda.get_device_properties(0).total_memory
    )
    torch.cuda.reset_peak_memory_stats()
    bp = setup["backbone"]
    print(f"{args.role}: loading original host, stream={stream}", flush=True)
    model = AutoModelForCausalLM.from_pretrained(
        bp["repository"],
        revision=bp["revision"],
        local_files_only=True,
        trust_remote_code=False,
        dtype=torch.bfloat16,
        attn_implementation=bp["attention"],
    ).to("cuda")
    model.config.use_cache = False
    identity = common.original_identity(
        model, bp["identity"], args.output, legacy_hash=core.legacy.old.prior.state_hash
    )
    model.requires_grad_(True).train()
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    graph = NativeMemoryCausalLM(model, cut=bp["cut"])
    ex.require(graph.require_full_update() == bp["parameters"], "Full native parameter set")
    random.seed(setup["seed"])
    core.np.random.seed(setup["seed"])
    torch.manual_seed(setup["seed"])
    contract = dict(
        source_commit=seal["source_commit"],
        original_base_sha256=identity["state_tree_v1_sha256"],
        data_sha256=ex.plan_hash(dict(manifest_sha256=plan["data_manifest_sha256"], stream=stream)),
        objective=setup["objective"],
    )
    config = NativeOptimizerConfig(**setup["optimizer"])
    ex.write_new(
        args.output / "CONTEXT.json",
        dict(
            contract=contract,
            graph=graph.contract(),
            runtime=runtime,
            optimizer=setup["optimizer"],
            data_manifest=manifest,
            data_summary=summary,
            stream=stream,
            imports=common.engine_imports(seal),
            parameter_elements=graph.require_full_update(),
        ),
    )
    guard("original_loaded")
    return graph, rows, schedule, config, contract, guard, setup


def canary(core, args, plan, seal):
    from latent_workspace.native_owner import NativeFullUpdateOwner
    from latent_workspace.optimizer_state import tree_hash

    graph, rows, schedule, config, contract, guard, setup = prepare(
        core, args, plan, seal, "canary", plan["checkpoint_max_bytes"]
    )
    owner = NativeFullUpdateOwner(graph, config=config, run_contract=contract)
    ex.write_new(args.output / "INITIAL.json", common.fingerprint(owner))
    for step, keys in enumerate(schedule["canary"], 1):
        common.update(owner, rows, keys, guard, args.output, step, after_spill=boundary)
        if step == 1:
            prior.checkpoint(owner, core, args, setup, guard, "canary_step1.pt")
    core.snapshot_admission(setup, guard, True)
    ex.write_new(args.output / "STEP2_PAYLOAD.json", dict(state_sha256=tree_hash(owner.payload())))
    return dict(
        native_weight_updates=2,
        backward_rows=sum(map(len, schedule["canary"])),
        checkpoints=1,
        **common.peak(),
    )


def replay(core, args, plan, seal):
    from latent_workspace.optimizer_state import tree_hash

    reference = predecessor(args, "canary", seal)
    graph, rows, schedule, config, contract, guard, setup = prepare(
        core, args, plan, seal, "canary", 0
    )
    owner = prior.restore(
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
    core.snapshot_admission(setup, guard, True)
    state = tree_hash(owner.payload())
    ex.require(
        state == ex.read(reference / "STEP2_PAYLOAD.json")["state_sha256"], "Exact next payload"
    )
    ex.write_new(args.output / "REPLAY.json", dict(exact=True, state_sha256=state))
    return dict(native_weight_updates=1, exact_replay=True, **common.peak())


def train(core, args, plan, seal):
    from latent_workspace.native_owner import NativeFullUpdateOwner

    reference = predecessor(args, "replay", seal)
    ex.require(ex.read(reference / "REPLAY.json")["exact"] is True, "Canary replay gate")
    validate_retirement(args.output.parent, args.checkpoints, seal, plan)
    if args.role == "workspace":
        predecessor(args, "inline", seal)
    forecast = (2 if args.role == "inline" else 1) * plan["checkpoint_max_bytes"]
    graph, rows, schedule, config, contract, guard, setup = prepare(
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
    prior.checkpoint(owner, core, args, setup, guard, f"{args.role}_step32.pt")
    prior.evaluate_dev(graph, rows, schedule["development"], guard, args.output / "DEV_STEP32.json")
    return dict(
        native_weight_updates=32,
        training_tokens_seen=owner.tokens_seen,
        backward_rows=sum(map(len, schedule["training"])),
        checkpoints=1,
        **common.peak(),
    )


def validate_retirement(raw, checkpoints, seal, plan):
    """No auto-delete. Require a separate, published, exact one-canary journal."""
    receipt = ex.read(raw / "canary/CHECKPOINT_canary_step1.pt.json")
    ledger_path = raw.parent / "CANARY_RETIREMENT.json"
    retired = ex.read(ledger_path)
    ex.require(
        retired["status"] == "SPENT_CANARY_RETIRED_AFTER_EXACT_REPLAY"
        and retired["source_commit"] == seal["source_commit"]
        and retired["checkpoint"] == receipt
        and retired["path"] == str(checkpoints / "canary_step1.pt")
        and retired["files_deleted"] == 1
        and retired["replay_receipt_sha256"] == ex.digest(raw / "replay/REPLAY.json"),
        "Exact spent-canary retirement",
    )
    ex.require(
        re.fullmatch(r"[0-9a-f]{40}", retired["published_ledger_commit"]),
        "Published ledger identity",
    )
    ex.require(
        ex.read(raw / "replay/REPLAY.json")["exact"] is True, "Exact replay before retirement"
    )
    ex.require(not (checkpoints / "canary_step1.pt").exists(), "No concurrent spent canary")
    return dict(path=str(ledger_path), sha256=ex.digest(ledger_path))


def summary(raw, plan):
    for role, updates in (("canary", 2), ("replay", 1), ("inline", 32), ("workspace", 32)):
        end = ex.read(raw / role / "FINISHED.json")
        ex.require(
            end["status"] == STATUSES[role] and end["native_weight_updates"] == updates,
            "Terminal denominator",
        )
    return dict(
        native_weight_updates=67,
        scientific_updates=64,
        replay_updates=1,
        engineering_updates=2,
        training_tokens_per_arm=plan["training_tokens_per_arm"],
        winner="none",
        non_regression="NOT_ESTABLISHED",
        old_expression_gate="FAIL",
    )


class RouteRun(IsolatedQualificationMixin, ex.SealedRun):
    pass


RUN = RouteRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass="V24_ROUTE_FT_TINY_PASS_NOT_7B",
    roles=ROLES,
    role_status=STATUSES,
    validate=validate,
    load=common.load,
    updates_native=True,
)
BODIES = dict(canary=canary, replay=replay, inline=train, workspace=train)


def phase(args, training):
    source, core, seal, check, plan = RUN.preflight(args)
    qualified = RUN.qualification(args.qualification, seal, plan)
    raw, ckpt = args.output.resolve(), args.checkpoints.resolve()
    ex.require(
        raw.name == "raw" and ckpt.parent == raw.parent and ckpt.name == "checkpoints",
        "Fixed layout",
    )
    ex.require(not raw.is_relative_to(ROOT) and not ckpt.is_relative_to(ROOT), "Outside source")
    phase_dir = raw.parent / ("training" if training else "checks")
    ex.require(not phase_dir.exists(), "Exclusive phase; no retry")
    if training:
        gate = raw.parent / "checks"
        start, end = ex.read(gate / "STARTED.json"), ex.read(gate / "FINISHED.json")
        files = ex.manifest(gate)
        files.pop("FINISHED.json")
        ex.require(
            start["seal"] == seal
            and start["plan"] == plan
            and end["files"] == files
            and end["status"] == CHECKS_PASS
            and end["completed_roles"] == ["canary", "replay"],
            "Complete checks gate",
        )
        for role in ("canary", "replay"):
            folder = predecessor(argparse.Namespace(output=raw / role), role, seal)
            ex.require(end["role_manifests"][role] == ex.manifest(folder), "Checks unchanged")
        validate_retirement(raw, ckpt, seal, plan)
    else:
        ex.require(not raw.exists() and not ckpt.exists(), "Fresh trial only")
        raw.mkdir(parents=True, exist_ok=False)
        ckpt.mkdir(parents=True, exist_ok=False)
        ex.write_new(
            raw / "STARTED.json",
            dict(
                seal=seal,
                plan=plan,
                pid=os.getpid(),
                source_check=check,
                qualification=qualified,
                checkpoints=str(ckpt),
            ),
        )
    roles = ("inline", "workspace") if training else ("canary", "replay")
    ex.require(all(not (raw / r).exists() for r in roles), "No role reuse")
    phase_dir.mkdir(exist_ok=False)
    ex.write_new(
        phase_dir / "STARTED.json", dict(seal=seal, plan=plan, roles=roles, pid=os.getpid())
    )
    args.output, args.checkpoints = raw, ckpt
    began = time.monotonic()
    result = dict(status=ex.INCOMPLETE, completed_roles=[], **ex.CEILING)
    result["native_weight_updates"] = None
    try:
        for role in roles:
            command = RUN.role_command(args, role)
            with (raw / f"{role}.log").open("x") as log:
                child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
                ex.write_new(raw / f"DISPATCH_{role}.json", dict(pid=child.pid, command=command))
                code = child.wait()
            ex.require(code == 0, f"{role} exited {code}; stop without retry")
            predecessor(argparse.Namespace(output=raw / role), role, seal)
            result["completed_roles"].append(role)
        result["role_manifests"] = {r: ex.manifest(raw / r) for r in roles}
        source.verify(ROOT, seal, ENTRY)
        ex.require(
            core.identity() == seal
            and RUN.qualification(args.qualification, seal, plan) == qualified,
            "Source/qualification unchanged",
        )
        result.update(
            native_weight_updates=64 if training else 3, status=PASS if training else CHECKS_PASS
        )
        if training:
            result["summary"] = summary(raw, plan)
    except BaseException as exc:
        result.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    result["elapsed_seconds"] = time.monotonic() - began
    result["files"] = ex.manifest(phase_dir)
    ex.write_new(phase_dir / "FINISHED.json", result)
    if training or result["status"] != CHECKS_PASS:
        terminal = {k: v for k, v in result.items() if k not in ("files", "role_manifests")}
        if training and result["status"] == PASS:
            terminal.update(native_weight_updates=67, completed_roles=list(ROLES))
        terminal["files"] = ex.manifest(raw)
        ex.write_new(raw / "FINISHED.json", terminal)
    print(
        ex.canonical({k: v for k, v in result.items() if k not in ("files", "role_manifests")}),
        flush=True,
    )
    return int(result["status"] == ex.INCOMPLETE)


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("dispatch-checks", "dispatch-training"):
        parser = argparse.ArgumentParser()
        parser.add_argument("command", choices=("dispatch-checks", "dispatch-training"))
        for field in ("seal", "output", "checkpoints", "qualification"):
            parser.add_argument(f"--{field}", type=Path, required=True)
        args = parser.parse_args()
        return phase(args, args.command == "dispatch-training")
    ex.require("dispatch" not in sys.argv[1:], "Use gated checks and training phases")
    return RUN.main(BODIES, summary)


if __name__ == "__main__":
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    os.environ["LTWS_CPU_SDPA_BACKEND"] = "math"
    raise SystemExit(main())
