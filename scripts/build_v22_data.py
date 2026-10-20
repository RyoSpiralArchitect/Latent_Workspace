#!/usr/bin/env python3
"""Offline, exclusive V22 English projection. No weights or model forwards."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from latent_workspace import execution as ex  # noqa: E402
from latent_workspace import v22_data as data  # noqa: E402


def materialize(preservation, world, plan):
    from transformers import AutoTokenizer

    ex.require(
        ex.digest(preservation / "MANIFEST.json") == plan["preservation_manifest_sha256"],
        "Original preservation seal",
    )
    manifest = ex.read(preservation / "MANIFEST.json")
    for name, item in manifest["files"].items():
        path = preservation / name
        ex.require(
            path.stat().st_size == item["bytes"] and ex.digest(path) == item["sha256"],
            "Original preservation bytes",
        )
    ex.require(
        ex.digest(world / "MANIFEST.json") == plan["world_manifest_sha256"], "World manifest"
    )
    ex.require(
        ex.digest(world / "world_rows.json.gz") == plan["world_rows_sha256"], "Original world rows"
    )
    parent = ex.read(preservation / "SUMMARY.json")
    backbone = plan["backbone"]
    ex.require(parent["backbone"] == backbone, "Same student tokenizer")
    tokenizer = AutoTokenizer.from_pretrained(
        backbone["repository"],
        revision=backbone["revision"],
        local_files_only=True,
        trust_remote_code=False,
    )
    ex.require(
        ex.hashlib.sha256(tokenizer.chat_template.encode()).hexdigest()
        == parent["chat_template_sha256"],
        "Chat template identity",
    )
    from huggingface_hub import snapshot_download

    cache = Path(
        snapshot_download(
            backbone["repository"], revision=backbone["revision"], local_files_only=True
        )
    )
    for name, item in parent["tokenizer_files"].items():
        ex.require(ex.digest(cache / name) == item["sha256"], "Tokenizer bytes")
    rows, excluded = data.project(
        ex.read_gz(preservation / "rows.json.gz"),
        ex.read_gz(world / "world_rows.json.gz"),
        tokenizer,
        plan,
    )
    windows, canary, dev = (
        data.schedule(rows, plan),
        data.select_canary(rows, plan),
        data.select_dev(rows, plan),
    )
    schedule = dict(training=windows, canary=canary, development=dev)
    summary = data.summarize(rows, windows, canary, dev, excluded, plan)
    index = [
        {
            **{k: v for k, v in row.items() if k not in ("input_ids", "labels", "memory_ids")},
            "input_tokens": len(row["input_ids"]),
            "memory_tokens": len(row["memory_ids"]),
            "record_sha256": ex.plan_hash(row),
        }
        for row in rows
    ]
    return rows, schedule, summary, index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--preservation", type=Path, required=True)
    parser.add_argument("--world", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ex.offline_environment()
    plan_path = ROOT / "configs/v22/DATA_01.json"
    plan = ex.read(plan_path)
    rows, schedule, summary, index = materialize(args.preservation, args.world, plan)
    sources = {
        str(p.relative_to(ROOT)): ex.digest(p)
        for p in (Path(__file__), ROOT / "src/latent_workspace/v22_data.py", plan_path)
    }
    if args.command == "build":
        args.output.mkdir(parents=True, exist_ok=False)
        ex.write_new(args.output / "PLAN.json", plan)
        ex.write_new(args.output / "SCHEDULE.json", schedule)
        ex.write_new(args.output / "SUMMARY.json", summary)
        ex.write_gz(args.output / "rows.json.gz", rows)
        ex.write_gz(args.output / "index.json.gz", index)
        ex.write_new(
            args.output / "MANIFEST.json",
            dict(schema="ltws-v22-data-v1", files=ex.manifest(args.output), source=sources),
        )
    else:
        manifest = ex.read(args.output / "MANIFEST.json")
        files = ex.manifest(args.output)
        files.pop("MANIFEST.json")
        ex.require(files == manifest["files"] and sources == manifest["source"], "Data seal")
        for name, value in (("PLAN", plan), ("SCHEDULE", schedule), ("SUMMARY", summary)):
            ex.require(ex.read(args.output / f"{name}.json") == value, "Exact metadata replay")
        ex.require(
            ex.read_gz(args.output / "rows.json.gz") == rows
            and ex.read_gz(args.output / "index.json.gz") == index,
            "Exact row replay",
        )
    print(ex.canonical(summary))


if __name__ == "__main__":
    main()
