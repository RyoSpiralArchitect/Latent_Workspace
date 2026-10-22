#!/usr/bin/env python3
"""Tokenizer-only offline regeneration and literal decoding check; no weight load."""

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--source", required=True, type=Path)
parser.add_argument("--bundle", required=True, type=Path)
args = parser.parse_args()
os.environ.update(
    HF_HUB_OFFLINE="1",
    HF_DATASETS_OFFLINE="1",
    TRANSFORMERS_OFFLINE="1",
    HF_HUB_DISABLE_TELEMETRY="1",
)
spec = importlib.util.spec_from_file_location(
    "source_guard", args.source / "scripts/run_source_sealed.py"
)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
seal = json.loads((args.bundle / "SOURCE_SEAL.json").read_text())
guard.verify(args.source, seal, "scripts/run_v22_comparison.py")
sys.path[:0] = [str(args.source / "src"), str(args.source / "scripts")]
import prepare_v22_comparison as prepare  # noqa: E402
from transformers import AutoTokenizer  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402

plan = ex.read(args.source / "configs/v22/BASE_COMPARISON_01.json")
train = ex.read(args.source / plan["training_plan"])
training_folder = Path(train["data_bundle"])
training_manifest = ex.read(training_folder / "MANIFEST.json")
ex.require(
    ex.digest(training_folder / "MANIFEST.json") == train["data_manifest_sha256"],
    "Training bank seal",
)
training_files = ex.manifest(training_folder)
training_files.pop("MANIFEST.json")
ex.require(training_files == training_manifest["files"], "Training bank bytes unchanged")
original = ex.read_gz(args.bundle / "inputs/INPUTS.json.gz")
rebuilt = prepare.build(plan)
ex.require(ex.canonical(original) == ex.canonical(rebuilt), "Exact tokenizer/input rebuild")
tokenizer = AutoTokenizer.from_pretrained(
    original["tokenizer"]["repository"],
    revision=original["tokenizer"]["revision"],
    local_files_only=True,
    trust_remote_code=False,
)
ex.require(
    tokenizer.eos_token_id == original["tokenizer"]["eos"]
    and tokenizer.chat_template == original["tokenizer"]["chat_template"],
    "Tokenizer identity",
)
counts = {}
for arm in ("base", "v22"):
    ex.require(
        ex.read(args.bundle / f"raw/{arm}/FINISHED.json")["status"]
        == "V22_EVALUATION_ARM_COMPLETE",
        "Terminal arm required",
    )
    for name in ("worlds", "free"):
        rows = [
            json.loads(s)
            for s in (args.bundle / f"raw/{arm}/{name}.jsonl").read_text().splitlines()
        ]
        for row in rows:
            ex.require(
                tokenizer.decode(row["token_ids"], skip_special_tokens=True) == row["text"],
                "Literal token-to-text replay",
            )
        counts[f"{arm}/{name}"] = len(rows)
ex.require(sum(counts.values()) == 432, "All literal generations")
ex.require(not list((args.bundle / "no-checkpoint-writes").iterdir()), "No checkpoint writes")
guard.verify(args.source, seal, "scripts/run_v22_comparison.py")
print(
    json.dumps(
        dict(
            status="OFFLINE_INPUT_AND_DECODING_REPLAY_PASS",
            model_calls=0,
            new_sequences=0,
            input_regeneration_exact=True,
            literal_rows=counts,
            no_checkpoint_writes=True,
            training_bank_files_verified=len(training_files),
            source_commit=seal["source_commit"],
            python=sys.version.split()[0],
            source_head=subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=args.source, text=True
            ).strip(),
        ),
        sort_keys=True,
    )
)
