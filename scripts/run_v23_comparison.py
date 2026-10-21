#!/usr/bin/env python3
"""Fresh base/off/on diagnostic on the unchanged exposed V22 evaluation inputs.

No training, saved weights, retries, paid judges, or new confirmation groups.
Strict full v1/v2 owner restore precedes the shared explicit inference policy.
"""

from __future__ import annotations

import gc
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import run_native_7b_canary as common  # noqa: E402
import run_v22_comparison as previous  # noqa: E402
import run_v23_preservation_ft as training  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402

ENTRY = "scripts/run_v23_comparison.py"
PLAN = "configs/v23/COMPARISON_01.json"
ROLES = ("base", "off", "on")
SOURCE = "b46f04caefcfd596ccde3b0af8fd886d859f11b7"
HISTORICAL = ROOT / "provenance/engineering/v23_preservation_ft01_20261022/furnace"


def reference(plan):
    result = ex.read(ROOT / plan["reference_evaluation_plan"])
    ex.require(
        ex.plan_hash(result) == plan["reference_evaluation_plan_sha256"],
        "Unchanged exposed input/generation policy",
    )
    return result


def validate(plan):
    old = reference(plan)
    ex.require(plan["schema"] == "ltws-v23-base-off-on-comparison-01" and plan["no_retry"], "Plan")
    ex.require(plan["roles"] == list(ROLES) and plan["training_source"] == SOURCE, "Fixed arms")
    ex.require(
        plan["planned"]
        == dict(
            arms=3,
            mmlu_scores=1710,
            world_teacher_forced_rows=576,
            world_generations=576,
            free_generations=72,
            total_new_sequences=648,
            native_weight_updates=0,
            checkpoint_saves=0,
            judge_calls=0,
            weight_deletions=0,
        ),
        "Finite diagnostic scope",
    )
    ex.require(plan["resources"] == old["resources"], "Unchanged resource limits")
    ex.require(plan["training_plan"] == old["training_plan"], "Same host/optimizer contract")
    ex.require(plan["pass_status"] == "V23_BASE_OFF_ON_COMPARISON_COMPLETE_NOT_RELEASE", "Gate")
    for arm in ("off", "on"):
        saved = ex.read(HISTORICAL / f"raw/{arm}/CHECKPOINT_{arm}_step32.pt.json")
        ex.require(plan["checkpoints"][arm] == saved, "Pinned final checkpoint receipt")


def inputs(plan):
    # Existing tokenized inputs keep their original plan hash and exposure.
    # No editing/resealing an old bundle to make it look like a new holdout.
    return previous.inputs(reference(plan))


def verified_training(plan, arm):
    bundle = Path(plan["training_bundle"])
    ex.require(
        ex.digest(bundle / "SOURCE_SEAL.json") == ex.digest(HISTORICAL / "SOURCE_SEAL.json"),
        "Historical source seal",
    )
    for role in ("teacher", arm):
        remote, local = bundle / "raw" / role, HISTORICAL / "raw" / role
        end = ex.read(remote / "FINISHED.json")
        ex.require(
            ex.digest(remote / "FINISHED.json") == ex.digest(local / "FINISHED.json"),
            "Historical terminal receipt",
        )
        actual = ex.manifest(remote)
        actual.pop("FINISHED.json")
        ex.require(actual == end["files"], "All original role bytes, including private targets")
        ex.require(end["status"] == f"V23_PRESERVATION_{role.upper()}_COMPLETE", "Training status")
        for name in ("STARTED.json", "CONTEXT.json"):
            ex.require(ex.digest(remote / name) == ex.digest(local / name), "Training context")
    return bundle


def owned_targets(bundle):
    from latent_workspace.preservation_objective import PreservationTargets

    plan = ex.read(ROOT / training.PLAN)
    ex.require(
        ex.plan_hash(plan) == "0e175eeaffe2bfc1dd7de4fe32616b51768aa83caadd54023d1a4a9d600c28ed",
        "Frozen training plan",
    )
    rows, schedule, _, _ = training.previous.load_data(ex.read(ROOT / plan["reference_plan"]))
    registered, eligible = training.registry(rows, schedule, plan)
    folder = bundle / "raw/teacher"
    receipt = ex.read(folder / "TEACHER_TARGETS.json")
    ex.require(receipt["source_commit"] == SOURCE, "Original owned teacher source")
    return PreservationTargets.load(
        folder / "PRIVATE_TEACHER_TARGETS.safetensors",
        receipt,
        registered,
        eligible,
        expected_receipt_plan_sha256=ex.plan_hash(receipt),
    )


def restore_checkpoint(graph, path, receipt, config, contract, fingerprint, *, preservation=None):
    """Shared strict owner, unmodified run contract; no objective downgrade."""
    import torch

    from latent_workspace.native_owner import NativeFullUpdateOwner

    ex.require(
        not path.is_symlink()
        and path.is_file()
        and path.stat().st_size == receipt["bytes"]
        and ex.digest(path) == receipt["sha256"],
        "Exact saved checkpoint body",
    )
    payload = torch.load(path, map_location="cpu", weights_only=False)
    owner = NativeFullUpdateOwner.restore(
        graph,
        payload,
        config=config,
        expected_run_contract=contract,
        expected_state_sha256=receipt["state_sha256"],
        preservation=preservation,
    )
    del payload
    gc.collect()
    actual = common.fingerprint(owner)
    common.exact(actual, fingerprint, "Complete original owner fingerprint")
    return owner, actual


def restore(graph, args, plan):
    from latent_workspace.native_owner import NativeOptimizerConfig

    bundle = verified_training(plan, args.role)
    folder = bundle / "raw" / args.role
    receipt = plan["checkpoints"][args.role]
    context = ex.read(folder / "CONTEXT.json")
    contract = context["contract"]
    ex.require(contract["source_commit"] == SOURCE, "Unmodified training source identity")
    bank = owned_targets(bundle) if args.role == "on" else None
    owner, actual = restore_checkpoint(
        graph,
        bundle / "checkpoints" / receipt["path"],
        receipt,
        NativeOptimizerConfig(**context["optimizer"]),
        contract,
        ex.read(folder / f"STATE_{receipt['path']}.json"),
        preservation=bank,
    )
    kl = None
    if bank is not None:
        kl = dict(tokens_seen=owner.preservation_tokens_seen, history=owner.preservation_history)
        common.exact(
            kl,
            ex.read(folder / f"PRESERVATION_{receipt['path']}.json"),
            "Owned KL history before inference",
        )
    ex.write_new(
        args.output / "RESTORE.json",
        dict(
            exact=True,
            checkpoint=receipt,
            fingerprint=actual,
            training_contract=contract,
            preservation=kl,
        ),
    )
    del owner, bank
    gc.collect()


def prepare(core, args, plan):
    return previous.prepare(core, args, plan, restore=None if args.role == "base" else restore)


def run(core, args, plan, seal):
    runtime = dict(reference(plan), **plan)
    return previous.run(
        core, args, runtime, seal, inputs_fn=inputs, prepare_fn=prepare, sequences_per_arm=216
    )


def summary(folder, plan):
    ends = [ex.read(folder / r / "FINISHED.json")["outcome"] for r in ROLES]
    ex.require(
        all(
            e["new_sequences"] == 216
            and e["mmlu_rows"] == 570
            and e["world_rows"] == 192
            and e["free_rows"] == 24
            for e in ends
        ),
        "Every arm has the entire frozen panel",
    )
    ex.require(not list((folder.parent / "checkpoints").iterdir()), "No new checkpoint bodies")
    return dict(
        new_sequences=sum(e["new_sequences"] for e in ends),
        generated_tokens=sum(e["generated_tokens"] for e in ends),
        native_weight_updates=0,
        checkpoint_saves=0,
        completed_arms=list(ROLES),
    )


RUN = previous.EvaluationRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass="TINY_V23_EVALUATION_PASS_NOT_7B",
    roles=ROLES,
    role_status={r: "V23_EVALUATION_ARM_COMPLETE" for r in ROLES},
    validate=validate,
    load=common.load,
)

if __name__ == "__main__":
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    os.environ["LTWS_CPU_SDPA_BACKEND"] = "math"
    raise SystemExit(RUN.main({r: run for r in ROLES}, summary))
