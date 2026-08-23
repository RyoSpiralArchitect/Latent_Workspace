#!/usr/bin/env python3
"""Prepare a bounded transport-v2 pilot config from a frozen v10 condition."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if source.parent != output.parent:
        raise ValueError(
            "Pilot config must remain beside its source so relative data paths "
            "retain identical meaning."
        )
    if source == output:
        raise ValueError("Pilot output must not overwrite the frozen source config.")
    raw = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Source config must contain a JSON object.")
    train = raw.get("train")
    if not isinstance(train, dict):
        raise ValueError("Source config train section is missing.")
    model = raw.get("model")
    if not isinstance(model, dict):
        raise ValueError("Source config model section is missing.")

    original = json.loads(json.dumps(raw))
    model["local_files_only"] = True
    model["trust_remote_code"] = False
    train["base_activation_offload"] = args.base_activation_offload
    train["gradient_accumulation_offload"] = args.gradient_accumulation_offload
    train["gradient_accumulation_steps"] = args.gradient_accumulation_steps
    train["max_steps"] = args.max_steps
    train["output_dir"] = args.run_dir
    train["resume_from"] = "none"
    train["save_every"] = max(args.max_steps, 1)
    train["eval_every"] = max(args.max_steps, 1)

    changed: list[str] = []
    original_model = original["model"]
    for key in sorted(set(original_model) | set(model)):
        if original_model.get(key) != model.get(key):
            changed.append(f"model.{key}")
    original_train = original["train"]
    for key in sorted(set(original_train) | set(train)):
        if original_train.get(key) != train.get(key):
            changed.append(f"train.{key}")
    allowed = {
        "model.local_files_only",
        "train.base_activation_offload",
        "train.eval_every",
        "train.gradient_accumulation_offload",
        "train.gradient_accumulation_steps",
        "train.max_steps",
        "train.output_dir",
        "train.resume_from",
        "train.save_every",
    }
    unexpected = sorted(set(changed) - allowed)
    if unexpected:
        raise ValueError(f"Unexpected pilot config mutations: {unexpected}")

    atomic_write_json(output, raw)
    receipt = {
        "schema_version": 1,
        "source_config": source.name,
        "source_config_sha256": sha256_file(source),
        "pilot_config": output.name,
        "pilot_config_sha256": sha256_file(output),
        "changed_fields": changed,
        "base_activation_offload": args.base_activation_offload,
        "gradient_accumulation_offload": args.gradient_accumulation_offload,
        "gradient_accumulation_steps": args.gradient_accumulation_steps,
        "max_steps": args.max_steps,
        "run_dir": args.run_dir,
    }
    receipt_path = output.with_suffix(".prepare.json")
    atomic_write_json(receipt_path, receipt)
    receipt["prepare_receipt"] = str(receipt_path)
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument(
        "--base-activation-offload",
        choices=("disabled", "legacy_functional", "all_base"),
        default="all_base",
    )
    parser.add_argument(
        "--gradient-accumulation-offload",
        choices=("none", "cpu", "cpu_accumulate"),
        default="none",
    )
    parser.add_argument("--gradient-accumulation-steps", type=int, default=8)
    parser.add_argument("--max-steps", type=int, default=1)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.gradient_accumulation_steps < 1 or args.max_steps < 1:
        raise SystemExit("gradient accumulation and max steps must be positive")
    print(json.dumps(prepare(args), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
