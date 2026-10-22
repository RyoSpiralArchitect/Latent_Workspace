#!/usr/bin/env python3
"""Build or fully replay a bounded, offline, CPU-only preservation candidate bank."""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src/latent_workspace/preservation_bank.py"
spec = importlib.util.spec_from_file_location("preservation_bank", MODULE)
pb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pb)


def write_new(path, value):
    with Path(path).open("x") as f:
        f.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def compressed(value):
    out = io.BytesIO()
    with gzip.GzipFile(filename="", fileobj=out, mode="wb", mtime=0) as f:
        f.write((pb.canonical(value) + "\n").encode())
    return out.getvalue()


def source_files(plan_path):
    return {
        str(p.relative_to(ROOT)): pb.digest(p)
        for p in [Path(__file__).resolve(), MODULE, plan_path]
    }


def materialize(args, plan):
    if args.deps:
        sys.path.insert(0, str(args.deps))
    import pyarrow
    import pyarrow.parquet as pq
    import transformers
    from huggingface_hub import snapshot_download

    sources = {}
    for name, descriptor in plan["oasst"]["files"].items():
        p = pb.safe_path(args.oasst, name)
        pb.require(p.stat().st_size == descriptor["bytes"], "OASST source size")
        pb.require(pb.digest(p) == descriptor["sha256"], "OASST source hash")
        sources[name] = descriptor
    for name, expected in plan["oasst"]["git_blobs"].items():
        p = pb.safe_path(args.oasst, name)
        data = p.read_bytes()
        import hashlib

        blob = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        pb.require(blob == expected, "OASST pinned documentation blob")
        sources[name] = dict(bytes=len(data), sha256=pb.sha(data), git_blob=blob)
    train_name = next(n for n in sources if n.startswith("data/train-"))
    val_name = next(n for n in sources if n.startswith("data/validation-"))
    train = pq.read_table(args.oasst / train_name).to_pylist()
    validation = pq.read_table(args.oasst / val_name).to_pylist()
    pb.require(pb.digest(args.qspace) == plan["qspace"]["artifact_sha256"], "QSpace source hash")
    qspace = pb.read(args.qspace)
    pb.require(len(qspace["rows"]) == plan["qspace"]["rows"], "QSpace denominator")
    prefix = plan["qspace"]["historical_prefix"]
    qtexts = []
    for item in qspace["rows"]:
        pb.require(item["text"].startswith(prefix), "Unexpected historical code framing")
        qtexts.append(item["text"][len(prefix) :])
    # Evaluation text stays solely in the exclusion set, never in output rows.
    exclusions = pb.Exclusions(qtexts + [r["text"] for r in validation], plan["overlap_span_words"])
    docs, aether_report = pb.verify_aether(args.aether, args.aether_eval, plan)
    backbone = plan["backbone"]
    cache = Path(
        snapshot_download(
            backbone["repository"],
            revision=backbone["revision"],
            local_files_only=True,
        )
    )
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        cache,
        local_files_only=True,
        trust_remote_code=False,
    )
    token_files = {
        p.name: dict(sha256=pb.digest(p), bytes=p.stat().st_size)
        for p in sorted(cache.iterdir())
        if p.name.startswith(("tokenizer", "special_tokens", "chat_template")) and p.is_file()
    }
    pb.require("tokenizer.json" in token_files, "Tokenizer fingerprint absent")
    prose, prose_report = pb.lm_candidates(args.aether, docs, tokenizer, plan, exclusions)
    chat, chat_report = pb.oasst_candidates(train, validation, tokenizer, plan, exclusions)
    rows = sorted(prose + chat, key=lambda r: r["row_id"])
    summary = pb.audit(rows, plan)
    summary.update(
        aether=aether_report,
        prose=prose_report,
        oasst=chat_report,
        qspace=dict(
            rows=len(qtexts),
            artifact_sha256=pb.digest(args.qspace),
            training_rows=0,
            upstream_revision=None,
            original_code_char_cap=3000,
            role="EXCLUSION_ONLY_HISTORICALLY_EXPOSED_NOT_UNSEEN_TEST",
        ),
        contamination=dict(
            checked="QSpace capped code and official OASST validation exact/50-word spans; "
            "Aether validation root/content IDs",
            semantic_or_other_public_benchmarks="NOT_CHECKED",
        ),
        runtime=dict(
            python=sys.version.split()[0],
            transformers=transformers.__version__,
            pyarrow=pyarrow.__version__,
        ),
        backbone=backbone,
        tokenizer_files=token_files,
        chat_template_sha256=pb.sha(tokenizer.chat_template.encode()),
        hf_source_files=sources,
        reproduction="OFFLINE_FULL_REGENERATION",
    )
    index = []
    for row in rows:
        entry = {
            k: v for k, v in row.items() if k not in ("input_ids", "labels", "text", "messages")
        }
        entry.update(
            input_tokens=len(row["input_ids"]),
            supervised_tokens=sum(t != -100 for t in row["labels"][1:]),
            input_ids_sha256=pb.sha(pb.canonical(row["input_ids"]).encode()),
            labels_sha256=pb.sha(pb.canonical(row["labels"]).encode()),
            record_sha256=pb.sha(pb.canonical(row).encode()),
        )
        index.append(entry)
    return rows, summary, index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument(
        "--plan", type=Path, default=ROOT / "configs/v1_0/PRESERVATION_BANK_01.json"
    )
    parser.add_argument("--aether", required=True, type=Path)
    parser.add_argument("--aether-eval", required=True, type=Path)
    parser.add_argument("--oasst", required=True, type=Path)
    parser.add_argument("--qspace", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--deps", type=Path)
    args = parser.parse_args()
    os.environ.update(
        HF_HUB_OFFLINE="1",
        HF_DATASETS_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        TOKENIZERS_PARALLELISM="false",
        CUDA_VISIBLE_DEVICES="",
        OMP_NUM_THREADS="2",
        OPENBLAS_NUM_THREADS="2",
    )
    plan = pb.read(args.plan)
    pb.require(plan["training_approved"] is False, "Preparation only")
    source = source_files(args.plan.resolve())
    if args.command == "build":
        args.output.mkdir(parents=True, exist_ok=False)
        write_new(
            args.output / "STARTED.json", dict(plan_sha256=pb.digest(args.plan), source=source)
        )
    else:
        manifest = pb.read(args.output / "MANIFEST.json")
        pb.require(manifest["source"] == source, "Builder source changed")
        for name, item in manifest["files"].items():
            pb.require(pb.digest(args.output / name) == item["sha256"], "Output changed")
    rows, summary, index = materialize(args, plan)
    payloads = {
        "rows.json.gz": compressed(rows),
        "index.json.gz": compressed(index),
        "SUMMARY.json": (
            json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode(),
        "PLAN.json": (
            json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode(),
    }
    if args.command == "build":
        for name, data in payloads.items():
            with (args.output / name).open("xb") as f:
                f.write(data)
        files = {
            p.name: dict(sha256=pb.digest(p), bytes=p.stat().st_size)
            for p in sorted(args.output.iterdir())
            if p.is_file()
        }
        write_new(
            args.output / "MANIFEST.json",
            dict(
                format="native_preservation_bank_v1",
                files=files,
                source=source,
                training_approved=False,
                raw_text_and_tokens_stay_in_artifact_storage=True,
            ),
        )
    else:
        for name, data in payloads.items():
            pb.require((args.output / name).read_bytes() == data, f"Replay differs: {name}")
    print(
        pb.canonical(
            dict(
                status="BUILT" if args.command == "build" else "OFFLINE_REPLAY_PASS",
                rows=summary["rows"],
                groups=summary["groups"],
                rows_by_bucket=summary["rows_by_bucket"],
                supervised_tokens_by_bucket=summary["supervised_tokens_by_bucket"],
                outside_tested_128_query_axis=summary["outside_tested_128_query_axis"],
                quota_shortfalls=summary["oasst"]["quota_shortfalls"],
                training_admissions=0,
            )
        )
    )


if __name__ == "__main__":
    main()
