#!/usr/bin/env python3
"""Tiny CPU/CUDA qualification then offline bank/token-span preparation. No 7B run."""

from __future__ import annotations

import os
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import run_native_7b_canary as common  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402

ENTRY = "scripts/run_v23_preparation.py"
PLAN = "configs/v23/PREPARATION_01.json"
PASS = "V23_PREPARATION_COMPLETE_NOT_7B_OR_TRAINING"


def validate(plan):
    ex.require(plan.get("pass_status") == PASS, "Explicit dispatch pass_status before any work")
    ex.require(plan["schema"] == "ltws-v23-preparation-01" and plan["no_retry"], "Plan")
    ex.require(
        not plan["full_7b_dispatch"] and plan["checkpoint_saves"] == plan["teacher_calls"] == 0,
        "No 7B model/weight/teacher work",
    )
    ex.require(
        plan["audit_world_rows"] == 84 and plan["audit_preservation_rows"] == 12,
        "Finite train-only selection",
    )


def data_role(core, args, plan, seal):
    from transformers import AutoTokenizer

    from latent_workspace import objective_audit as obj
    from latent_workspace import world_expansion as worlds
    from latent_workspace.v22_data import rank

    builder = common.load("build_world_expansion")
    ex.require(
        shutil.disk_usage(args.output).free >= plan["resources"]["disk_free_gib"] * ex.GIB,
        "Storage floor",
    )
    summary = builder.run("build", args.output / "bank")
    ex.require(builder.run("verify", args.output / "bank") == summary, "Bank replay")
    bp = plan["backbone"]
    tokenizer = AutoTokenizer.from_pretrained(
        bp["repository"], revision=bp["revision"], local_files_only=True, trust_remote_code=False
    )
    ex.require(
        tokenizer.is_fast and tokenizer.eos_token_id == 2 and len(tokenizer) == 32768,
        "Pinned fast tokenizer vocabulary/EOS",
    )
    world_plan = ex.read(ROOT / plan["world_plan"])
    raw_rows = worlds.build(world_plan)
    counts, train, parts_count = [], {}, Counter()
    for row in raw_rows:
        prefix = list(
            tokenizer.apply_chat_template(
                [{"role": "user", "content": row["query"]}],
                tokenize=True,
                add_generation_prompt=True,
                return_dict=False,
            )
        )
        partition = obj.oracle_partition(
            tokenizer, row["answer_value"], worlds.names_in([row["facts"], row["query_spec"]])
        )
        answer = tokenizer.encode(" " + row["answer"], add_special_tokens=False) + [2]
        ex.require(partition["input_ids"] == answer, "Span compiler must preserve target tokens")
        memory = tokenizer.encode(row["memory"], add_special_tokens=False) if row["memory"] else []
        count = dict(
            row_id=row["row_id"],
            split=row["split"],
            family=row["family"],
            identifier_style=row["identifier_style"],
            memory_tokens=len(memory),
            query_tokens=len(prefix) + len(answer),
            target_tokens=len(answer),
            parts=dict(Counter(partition["parts"])),
        )
        counts.append(count)
        if row["split"] != "train":
            continue
        signature = ex.plan_hash([memory, prefix, answer])
        if signature in train:
            ex.require(train[signature]["group_id"] == row["group_id"], "Cross-group alias")
            train[signature]["duplicate_aliases"].append(row["row_id"])
            continue
        train[signature] = dict(
            key=row["row_id"],
            group_id=row["group_id"],
            split="train",
            role="world",
            language="en",
            family=row["family"],
            mode=row["mode"],
            side=row["side"],
            identifier_style=row["identifier_style"],
            memory_ids=memory,
            input_ids=prefix + answer,
            labels=[-100] * len(prefix) + answer,
            parts=[-1] * len(prefix) + [obj.PARTS.index(p) for p in partition["parts"]],
            supervised_tokens=len(answer),
            parent_record_sha256=ex.plan_hash(row),
            oracle_partition=partition,
            duplicate_aliases=[],
        )
        parts_count.update(partition["parts"])
    train = sorted(train.values(), key=lambda r: r["key"])
    selected = []
    for family in world_plan["families"]:
        for style in world_plan["identifier_styles"]:
            pool = [r for r in train if r["family"] == family and r["identifier_style"] == style]
            group = min({r["group_id"] for r in pool}, key=lambda g: rank(plan["seed"], g))
            selected.extend(r for r in pool if r["group_id"] == group)
    ex.require(len(selected) == plan["audit_world_rows"], "Complete selected groups")
    old = Path(plan["preservation_bank"])
    ex.require(
        ex.digest(old / "MANIFEST.json") == plan["preservation_manifest_sha256"],
        "Preservation manifest identity",
    )
    manifest = ex.read(old / "MANIFEST.json")
    ex.require(
        ex.digest(old / "rows.json.gz") == manifest["files"]["rows.json.gz"]["sha256"],
        "Preservation rows identity",
    )
    candidates = ex.read_gz(old / "rows.json.gz")
    preservation = []
    for role in ("instruction", "prose", "code"):
        pool = [
            r
            for r in candidates
            if r["split"] == "train"
            and r["role"] == role
            and r["language"] == "en"
            and len(r["input_ids"]) <= plan["audit_preservation_maximum_query_tokens"]
        ]
        pool.sort(key=lambda r: rank(plan["seed"], r["key"]))
        ex.require(len(pool) >= plan["audit_preservation_rows_per_role"], "Preservation quota")
        preservation.extend(pool[: plan["audit_preservation_rows_per_role"]])
    ex.require(len(preservation) == plan["audit_preservation_rows"], "Preservation panel size")
    ex.require(all(not r["memory_ids"] for r in preservation), "No-memory preservation")
    # Keep these source-owned instruction/prose/code token arrays remote only.
    ex.write_gz(
        args.output / "PRIVATE_AUDIT_INPUTS.json.gz",
        dict(worlds=selected, preservation=preservation),
    )
    ex.write_gz(args.output / "TRAIN_TOKENS.json.gz", train)
    ex.write_gz(args.output / "TOKEN_COUNTS.json.gz", counts)
    selection = dict(
        world_keys=[r["key"] for r in selected],
        world_groups=sorted({r["group_id"] for r in selected}),
        preservation=[
            dict(
                key=r["key"],
                group_id=r["group_id"],
                role=r["role"],
                query_tokens=len(r["input_ids"]),
                supervised_tokens=r["supervised_tokens"],
                row_sha256=ex.plan_hash(r),
            )
            for r in preservation
        ],
        private_inputs_sha256=ex.digest(args.output / "PRIVATE_AUDIT_INPUTS.json.gz"),
        seed=plan["seed"],
        selection="hash_rank_complete_train_groups_and_short_complete_preservation",
        heldout_model_evaluations=0,
        targets_status="NOT_RUN",
    )
    ex.write_new(args.output / "AUDIT_SELECTION.json", selection)
    anchor_tokens = sum(r["supervised_tokens"] for r in preservation)
    result = dict(
        bank=summary,
        backbone=bp,
        unique_train_rows=len(train),
        unique_train_supervised_tokens=sum(r["supervised_tokens"] for r in train),
        unique_train_part_tokens=dict(parts_count),
        max_memory_tokens=max(r["memory_tokens"] for r in counts),
        max_query_tokens=max(r["query_tokens"] for r in counts),
        outside_previously_tested_128_by_128=dict(
            Counter(
                f"{r['split']}/{r['family']}"
                for r in counts
                if r["memory_tokens"] > 128 or r["query_tokens"] > 128
            )
        ),
        planned_audit_world_rows=len(selected),
        planned_audit_preservation_rows=len(preservation),
        planned_audit_max_memory_tokens=max(len(r["memory_ids"]) for r in selected),
        planned_audit_max_query_tokens=max(len(r["input_ids"]) for r in selected + preservation),
        planned_anchor_supervised_tokens=anchor_tokens,
        planned_full_vocab_fp32_target_bytes=anchor_tokens * 32768 * 4,
        future_anchor=plan["future_anchor"],
        native_model_forward_calls=0,
        teacher_target_files_written=0,
        truncations=0,
        training_admissions=0,
        private_source_tokens_publication="OMIT_PRIVATE_AUDIT_INPUTS_KEEP_HASH_AND_REMOTE_BODY",
        source=seal["source_commit"],
        **ex.CEILING,
    )
    ex.write_new(args.output / "PREPARATION.json", result)
    ex.require(
        shutil.disk_usage(args.output).free >= plan["resources"]["disk_free_gib"] * ex.GIB,
        "Storage floor after data preparation",
    )
    return result


RUN = ex.SealedRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass="TINY_V23_OBJECTIVE_AUDIT_PASS_NOT_7B",
    roles=("data",),
    role_status={"data": PASS},
    validate=validate,
    load=common.load,
)


if __name__ == "__main__":
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    os.environ["LTWS_CPU_SDPA_BACKEND"] = "math"
    raise SystemExit(
        RUN.main({"data": data_role}, lambda out, plan: ex.read(out / "data" / "PREPARATION.json"))
    )
