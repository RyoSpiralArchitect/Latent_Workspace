#!/usr/bin/env python3
"""Additive length/gradient resource assay. No optimizer update, save or generation."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import run_native_7b_canary as prior  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402

ENTRY = "scripts/run_native_resource_probe.py"
PLAN = "configs/v1_0/NATIVE_RESOURCE_PROBE_RECOVERY_01.json"
PLAN_SHA256 = "b8e1c00ff520328c1ad5552dc18f2baa85a3d34d30c817b9d7b984edededcf84"
TINY_PASS = "TINY_NATIVE_RESOURCE_PROBE_PASS_NOT_7B"
ROLE_PASS = "THREE_BACKWARDS_NO_NATIVE_UPDATE"


def validate(plan):
    ex.require(ex.plan_hash(plan) == PLAN_SHA256, "Frozen resource plan changed")
    reference = ex.read(ROOT / plan["reference_plan"])
    ex.require(ex.plan_hash(reference) == plan["reference_plan_sha256"], "Reference recipe changed")
    ex.require(
        plan["no_retry"] and plan["native_weight_updates"] == plan["checkpoint_writes"] == 0,
        "No-update no-retry scope",
    )
    recovery = plan["recovery_of"]
    ex.require(
        ex.digest(ROOT / recovery["terminal"]) == recovery["terminal_sha256"],
        "Previous terminal changed",
    )


def effective_plan(plan):
    result = ex.read(ROOT / plan["reference_plan"])
    result.update(plan)
    result["storage_forecast_bytes"] = 0
    return result


def resource_contract(contract, rows):
    # Diagnostic purpose is not a different loss. Keep the owner's genuine
    # token-weighted causal-NLL identifier; only input provenance changes.
    return {**contract, "data_sha256": ex.plan_hash(rows)}


def resource_rows(tokenizer, profiles):
    """Exact synthetic tensor lengths, not natural examples or hidden truncation."""
    pattern = tokenizer.encode(
        "A neutral resource probe contains a sequence of ordinary words.",
        add_special_tokens=False,
    )
    ex.require(pattern and all(type(t) is int and t >= 0 for t in pattern), "Pattern IDs")
    ex.require(tokenizer.eos_token_id == 2, "Pinned EOS")
    rows = []
    for profile in profiles:
        m, q, a = (profile[k] for k in ("memory_tokens", "query_tokens", "answer_tokens"))
        ex.require(
            all(type(n) is int for n in (m, q, a))
            and 0 <= m <= 128
            and 2 <= q <= 128
            and 0 < a < q,
            "Resource profile bounds",
        )
        ids = (pattern * (q // len(pattern) + 1))[:q]
        ids[-1] = 2
        memory = (pattern * (m // len(pattern) + 1))[:m]
        rows.append(
            dict(
                key=profile["key"],
                input_ids=ids,
                labels=[-100] * (q - a) + ids[q - a :],
                memory_ids=memory,
                supervised_tokens=a,
            )
        )
    ex.require(len({r["key"] for r in rows}) == len(rows), "Unique profile keys")
    return rows


def backward_window(owner, rows, guard, output):
    """Keep the real owner's masters/spill buffers present, but NEVER call step/save."""
    import torch

    from latent_workspace.optimizer_state import tree_hash

    before = tree_hash(owner.model.state_dict())
    master_before = tree_hash(owner.masters)
    owner.begin_window([(r["key"], r["supervised_tokens"]) for r in rows])
    records = []
    for row in rows:
        guard(f"{row['key']}:before_backward")
        receipt = owner.accumulate(
            row["key"], prior.batch(row, next(owner.model.parameters()).device)
        )
        guard(f"{row['key']}:after_spill")
        receipt.update(
            memory_tokens=len(row["memory_ids"]),
            query_tokens=len(row["input_ids"]),
            native_gradient_tensors=len(owner.named),
            native_gradient_elements=sum(p.numel() for _, p in owner.named),
            accumulated_gradient_sha256=tree_hash(
                {s.name: owner.window._buffers[id(s.parameter)] for s in owner.window._specs}
            ),
        )
        if torch.cuda.is_available() and next(owner.model.parameters()).is_cuda:
            receipt.update(prior.peak())
        records.append(receipt)
        ex.write_new(output / f"{row['key']}.json", receipt)
    ex.require(owner.cursor == len(rows), "All declared rows accumulated")
    ex.require(before == tree_hash(owner.model.state_dict()), "Native parameters changed")
    ex.require(master_before == tree_hash(owner.masters), "Master parameters changed")
    ex.require(owner.completed_steps == owner.tokens_seen == 0, "Unexpected optimizer step")
    # Explicitly discard diagnostic gradients; this owner is not saved or reused.
    owner.window.discard()
    return dict(
        backward_rows=len(records),
        supervised_tokens=sum(r["supervised_tokens"] for r in rows),
        native_unchanged=True,
        masters_unchanged=True,
        native_weight_updates=0,
        checkpoint_writes=0,
        records=records,
    )


def probe(core, args, plan, seal):
    from transformers import AutoTokenizer

    from latent_workspace.native_owner import NativeFullUpdateOwner

    effective = effective_plan(plan)
    graph, _, config, contract, guard = prior.prepare(core, args, effective, seal)
    backbone = effective["backbone"]
    tokenizer = AutoTokenizer.from_pretrained(
        backbone["repository"],
        revision=backbone["revision"],
        local_files_only=True,
        trust_remote_code=False,
    )
    rows = resource_rows(tokenizer, plan["profiles"])
    ex.write_new(args.output / "RESOURCE_INPUTS.json", rows)
    contract = resource_contract(contract, rows)
    owner = NativeFullUpdateOwner(graph, config=config, run_contract=contract)
    result = backward_window(owner, rows, guard, args.output)
    result.update(prior.peak())
    ex.write_new(args.output / "RESOURCE_RESULT.json", result)
    return result


def summary(output, _plan):
    result = ex.read(output / "probe" / "RESOURCE_RESULT.json")
    ex.require(result["backward_rows"] == 3 and result["native_weight_updates"] == 0, "Scope")
    return result


RUN = ex.SealedRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass=TINY_PASS,
    roles=("probe",),
    role_status={"probe": ROLE_PASS},
    validate=validate,
    load=prior.load,
)

if __name__ == "__main__":
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    os.environ["LTWS_CPU_SDPA_BACKEND"] = "math"
    raise SystemExit(RUN.main({"probe": probe}, summary))
