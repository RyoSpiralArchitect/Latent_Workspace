#!/usr/bin/env python3
"""Freeze tokenizer-only comparison inputs; never load model weights or score."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from latent_workspace import execution as ex  # noqa: E402
from latent_workspace import native_evaluation as ev  # noqa: E402


def build(plan):
    ex.offline_environment()
    from transformers import AutoTokenizer

    train = ex.read(ROOT / plan["training_plan"])
    backbone = train["backbone"]
    tokenizer = AutoTokenizer.from_pretrained(
        backbone["repository"],
        revision=backbone["revision"],
        local_files_only=True,
        trust_remote_code=False,
    )
    ex.require(tokenizer.eos_token_id == 2, "Pinned EOS")
    world_path = Path(plan["world_bundle"]) / "world_rows.json.gz"
    ex.require(ex.digest(world_path) == plan["world_rows_sha256"], "Frozen world bank")
    all_worlds = ex.read_gz(world_path)
    training = ex.read_gz(Path(train["data_bundle"]) / "rows.json.gz")
    ex.require(
        ex.digest(Path(train["data_bundle"]) / "MANIFEST.json") == train["data_manifest_sha256"],
        "Training data identity",
    )
    training_groups = {r["group_id"] for r in training}
    selected = ev.select_worlds(all_worlds, plan["world_selection"], training_groups)
    worlds = []
    for row in selected:
        query = row["query"] + plan["world_suffix"]
        inline = ("Memory facts:\n" + row["memory"] + "\n\n" if row["memory"] else "") + query
        memory = tokenizer.encode(row["memory"], add_special_tokens=False) if row["memory"] else []
        answer = tokenizer.encode(" " + row["answer"], add_special_tokens=False) + [2]
        prefixes = dict(
            latent=ev.encode_chat(tokenizer, query), inline=ev.encode_chat(tokenizer, inline)
        )
        ex.require(
            len(memory) <= 128
            and len(answer) <= 24
            and all(len(p) + len(answer) <= 512 for p in prefixes.values()),
            "World complete-sequence bounds; no truncation",
        )
        worlds.append(dict(row, prefixes=prefixes, memory_ids=memory, answer_ids=answer))
    mmlu_path = ROOT / plan["mmlu"]["path"]
    ex.require(ex.digest(mmlu_path) == plan["mmlu"]["sha256"], "MMLU input identity")
    mmlu = [
        ev.choice_tokens(tokenizer, r, plan["mmlu"]["max_prompt_tokens"])
        for r in ex.read(mmlu_path)
    ]
    ex.require(len(mmlu) == plan["mmlu"]["n"], "MMLU denominator")
    free = [dict(r, input_ids=ev.encode_chat(tokenizer, r["prompt"])) for r in plan["free_prompts"]]
    ex.require(all(len(r["input_ids"]) <= 512 for r in free), "Free prompt length")
    return dict(
        schema="ltws-v22-comparison-inputs-v1",
        plan_sha256=ex.plan_hash(plan),
        tokenizer=dict(
            repository=backbone["repository"],
            revision=backbone["revision"],
            eos=2,
            chat_template=tokenizer.chat_template,
        ),
        audit=dict(
            world_groups=len({r["group_id"] for r in worlds}),
            unique_world_rows=len(worlds),
            raw_world_rows=sum(1 + len(r["aliases"]) for r in worlds),
            training_group_overlap=0,
            mmlu_rows=len(mmlu),
            free_prompts=len(free),
            max_mmlu_tokens=max(len(r["input_ids"]) for r in mmlu),
            max_world_memory_tokens=max(len(r["memory_ids"]) for r in worlds),
        ),
        worlds=worlds,
        mmlu=mmlu,
        free=free,
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    plan = ex.read(ROOT / "configs/v22/BASE_COMPARISON_01.json")
    data = build(plan)
    args.output.mkdir(parents=True, exist_ok=False)
    ex.write_gz(args.output / "INPUTS.json.gz", data)
    ex.write_new(
        args.output / "MANIFEST.json",
        dict(
            plan_sha256=ex.plan_hash(plan),
            files=ex.manifest(args.output),
            audit=data["audit"],
            source={
                n: ex.digest(ROOT / n)
                for n in [
                    "scripts/prepare_v22_comparison.py",
                    "src/latent_workspace/native_evaluation.py",
                    "configs/v22/BASE_COMPARISON_01.json",
                ]
            },
        ),
    )
    print(ex.canonical(data["audit"]))


if __name__ == "__main__":
    main()
