"""Explicit host-snapshot admission, independent from actual checkpoint writes.

The historical 32-GiB write reserve and independent host reserve are preserved.
Reading an existing checkpoint or hashing a payload creates no tensor file.
This module does not change owner arithmetic, payloads, serialization or floors.
"""

import gc

import run_native_7b_canary as common

from latent_workspace import execution as ex

WRITE_RESERVE = 32 * ex.GIB
OPERATIONS = {"checkpoint_write": WRITE_RESERVE, "checkpoint_read": 0, "payload_hash": 0}


def future_write_bytes(checkpoint_max_bytes, remaining_files):
    """Peak future requirement: prior bounded files plus the last write reserve."""
    ex.require(
        type(checkpoint_max_bytes) is int and 0 < checkpoint_max_bytes <= WRITE_RESERVE,
        "Bounded checkpoint upper size",
    )
    ex.require(type(remaining_files) is int and remaining_files >= 0, "Remaining file count")
    return WRITE_RESERVE + (remaining_files - 1) * checkpoint_max_bytes if remaining_files else 0


def admit(core, plan, guard, *, operation):
    ex.require(operation in OPERATIONS, "Explicit snapshot operation")
    ex.require(
        core.legacy.backward.host_available()
        >= plan["snapshot_host_extra_bytes"]
        + plan["resources"]["host_abort_available_gib"] * ex.GIB,
        "forecast independent snapshot host envelope",
    )
    guard(f"before_snapshot:{operation}", forecast_bytes=OPERATIONS[operation])


def checkpoint(owner, core, args, plan, guard, name):
    ex.require(name in plan["checkpoint_names"], "Allowlisted checkpoint")
    admit(core, plan, guard, operation="checkpoint_write")
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
    admit(core, plan, guard, operation="checkpoint_read")
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


def payload_sha(owner, core, plan, guard):
    from latent_workspace.optimizer_state import tree_hash

    admit(core, plan, guard, operation="payload_hash")
    return tree_hash(owner.payload())
