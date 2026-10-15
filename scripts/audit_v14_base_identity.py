#!/usr/bin/env python3
"""CPU-only exact tensor audit of historical V14 bases against pinned Mistral.

This does not load a Transformers model, execute a forward pass, or access CUDA.
Only a new JSON receipt is written; existing evidence and weights stay unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import time
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
MODEL_ID = "mistralai/Mistral-7B-Instruct-v0.3"
REVISION = "c170c708c41dac9275d15a8fff4eca08d52bab71"
FROZEN_SOURCES = {
    "scripts/run_v14_multiturn_choice.py": (
        "86dc1f258a8627a337fc815409b8729c573b52675a38b558627c276d620df7b1"
    ),
    "configs/v14/MULTITURN_CHOICE_PLAN.json": (
        "a8e70b61ab01458d872632ecea23251df84c363750d9bbbab02f5fb1caabce17"
    ),
    "src/latent_workspace_ft_v10/engine.py": (
        "3e7659b7c927cab23b4d994ce2e320d99431e4ba657d560c1094bc36de596178"
    ),
}
CHECKPOINTS = {
    "task": {
        "path": "runs/v14/boundary_training/task_seed47_step8/final",
        "manifest_sha256": "00561bf8fd6f1b4eec52061fe88684198dbaa8ea2feee1d948bd202eb43523ad",
        "workspace_sha256": "2861d3421fde4d9532142517f86ae1a4984806b3f872ead6d426f1fee6ec0e00",
    },
    "semantic": {
        "path": "runs/v14/boundary_training/semantic_seed47_step8/final",
        "manifest_sha256": "067c48cb1d312e1e0fa504f889343d5bd825140a49e0a3e2deec2004bf3113f2",
        "workspace_sha256": "3e2c9ace61b7aa08c1efb93e0b8e6d9466ba52073395cf20c0c599ea06a518b2",
    },
}
PINNED_SHARD_HASHES = {
    "model-00001-of-00003.safetensors": (
        "ce6fb6f6f4d0183f4813cbf4ece24109da629a08d4210da46f77e1d8b0bd5c19"
    ),
    "model-00002-of-00003.safetensors": (
        "8c0e72f148366b6a3709e002a98706a33d31aec8515090c856c95b2044f92ae0"
    ),
    "model-00003-of-00003.safetensors": (
        "905dd405363e43d95779c1c1155a2dbfd36155914ae95dbd934e12e490cfb4ca"
    ),
}


class IdentityAuditError(RuntimeError):
    """An identity contract failed before an audit could be qualified."""


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise IdentityAuditError(f"Expected JSON object: {path}")
    return value


def stable_hash(value: dict[str, Any]) -> str:
    """Match the historical engine's config payload hash, not its file hash."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _stat(path: Path) -> tuple[int, int, int, int]:
    value = path.stat()
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _weight_map(directory: Path) -> dict[str, str]:
    mapping = load_json(directory / "model.safetensors.index.json").get("weight_map")
    if not isinstance(mapping, dict) or not mapping:
        raise IdentityAuditError("Missing or empty weight_map")
    for key, shard in mapping.items():
        if (
            not isinstance(key, str)
            or not isinstance(shard, str)
            or Path(shard).name != shard
            or not shard.endswith(".safetensors")
            or not (directory / shard).is_file()
        ):
            raise IdentityAuditError("Invalid or absent safetensors shard")
    return mapping


def inventory(directory: Path, mapping: dict[str, str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name in sorted(set(mapping.values()) | {"model.safetensors.index.json"}):
        path = directory / name
        before = _stat(path)
        sha256 = digest(path)
        if before != _stat(path):
            raise IdentityAuditError(f"File changed while hashing: {name}")
        result[name] = {"bytes": before[2], "sha256": sha256}
    return result


def compare_tensors(reference: Path, saved: Path) -> dict[str, Any]:
    """Compare one CPU tensor pair at a time without dtype conversion/tolerance."""
    import torch
    from safetensors import safe_open

    left_map, right_map = _weight_map(reference), _weight_map(saved)
    if set(left_map) != set(right_map):
        raise IdentityAuditError("Tensor key sets differ")
    equal_names: list[str] = []
    changed_names: list[str] = []
    dtype_pairs: set[tuple[str, str]] = set()
    scalar_count = 0
    with ExitStack() as stack:
        left = {
            name: stack.enter_context(safe_open(reference / name, framework="pt", device="cpu"))
            for name in sorted(set(left_map.values()))
        }
        right = {
            name: stack.enter_context(safe_open(saved / name, framework="pt", device="cpu"))
            for name in sorted(set(right_map.values()))
        }
        for key in sorted(left_map):
            original = left[left_map[key]].get_tensor(key)
            observed = right[right_map[key]].get_tensor(key)
            if original.device.type != "cpu" or observed.device.type != "cpu":
                raise IdentityAuditError("Non-CPU tensor in identity audit")
            if original.shape != observed.shape or original.dtype != observed.dtype:
                raise IdentityAuditError(f"Tensor geometry/dtype differs: {key}")
            dtype_pairs.add((str(original.dtype), str(observed.dtype)))
            scalar_count += original.numel()
            (equal_names if torch.equal(original, observed) else changed_names).append(key)
            del original, observed
    return {
        "tensor_keys_exact_match": True,
        "tensor_count": len(left_map),
        "scalar_count": scalar_count,
        "equal_tensor_count": len(equal_names),
        "changed_tensor_count": len(changed_names),
        "changed_tensor_keys": changed_names,
        "equal_tensor_keys": equal_names,
        "dtype_pairs": [list(pair) for pair in sorted(dtype_pairs)],
        "all_tensors_equal": not changed_names,
        "comparison": (
            "torch.equal on matching-shape matching-dtype CPU tensors; no casting or tolerance"
        ),
    }


def validate_inputs(root: Path, snapshot: Path) -> dict[str, Path]:
    if snapshot.name != REVISION or not snapshot.is_dir():
        raise IdentityAuditError("Snapshot must name the pinned model revision")
    for relative, expected in FROZEN_SOURCES.items():
        if digest(root / relative) != expected:
            raise IdentityAuditError(f"Historical source identity mismatch: {relative}")
    checkpoints: dict[str, Path] = {}
    for cell, contract in CHECKPOINTS.items():
        checkpoint = root / contract["path"]
        if not (checkpoint / "COMPLETED").is_file():
            raise IdentityAuditError(f"Checkpoint incomplete: {cell}")
        if digest(checkpoint / "manifest.json") != contract["manifest_sha256"]:
            raise IdentityAuditError(f"Checkpoint manifest mismatch: {cell}")
        if digest(checkpoint / "workspace_state.pt") != contract["workspace_sha256"]:
            raise IdentityAuditError(f"Checkpoint workspace mismatch: {cell}")
        manifest = load_json(checkpoint / "manifest.json")
        config = load_json(checkpoint / "experiment_config.json")
        if (
            manifest.get("complete") is not True
            or manifest.get("global_step") != 8
            or manifest.get("base_storage") != "pretrained"
            or stable_hash(config) != manifest.get("config_sha256")
            or config["model"]["name_or_path"] != MODEL_ID
            or config["model"]["revision"] != REVISION
        ):
            raise IdentityAuditError(f"Checkpoint model/config contract mismatch: {cell}")
        checkpoints[cell] = checkpoint
    return checkpoints


def audit(root: Path, snapshot: Path) -> dict[str, Any]:
    import torch

    started = time.monotonic()
    torch.set_num_threads(2)
    checkpoints = validate_inputs(root, snapshot)
    directories = {"pinned_original": snapshot}
    directories.update({cell: path / "base_model" for cell, path in checkpoints.items()})
    before = {name: inventory(path, _weight_map(path)) for name, path in directories.items()}
    if {
        name: value["sha256"]
        for name, value in before["pinned_original"].items()
        if name.endswith(".safetensors")
    } != PINNED_SHARD_HASHES:
        raise IdentityAuditError("Pinned original shard content hash mismatch")
    cells = {
        cell: {
            "saved_base": contract["path"] + "/base_model",
            "checkpoint_manifest_sha256": contract["manifest_sha256"],
            "checkpoint_workspace_sha256": contract["workspace_sha256"],
            **compare_tensors(snapshot, directories[cell]),
        }
        for cell, contract in CHECKPOINTS.items()
    }
    after = {name: inventory(path, _weight_map(path)) for name, path in directories.items()}
    if before != after:
        raise IdentityAuditError("Model contents changed during comparison")
    validate_inputs(root, snapshot)
    return {
        "format": "latent-workspace-v14-historical-base-identity-v1",
        "status": "QUALIFIED_EXECUTION",
        "created_utc": datetime.now(UTC).isoformat(),
        "model": {"id": MODEL_ID, "revision": REVISION},
        "path_roots": {
            "saved_bases": "repository-relative",
            "pinned_original": (
                "huggingface-hub/models--mistralai--Mistral-7B-Instruct-v0.3/snapshots/" + REVISION
            ),
        },
        "historical_source_identity": FROZEN_SOURCES,
        "audit_source_sha256": digest(Path(__file__)),
        "environment": {"python": platform.python_version(), "torch": torch.__version__},
        "cells": cells,
        "file_inventory": before,
        "contents_unchanged_after_rehash": True,
        "gpu_used": False,
        "weight_write_or_delete": False,
        "runtime_seconds": time.monotonic() - started,
        "interpretation": {
            "historical_base_conditions_use_task_checkpoint_backbone": True,
            "historical_base_is_pinned_original": cells["task"]["all_tensors_equal"],
            "historical_labels": ["base_query_only", "base_inline"],
            "corrected_interpretation": "task-trained backbone with workspace hard-bypassed",
            "historical_evidence_modified": False,
            "claim_boundary": (
                "Exact backbone identity only; neither difference counts nor this correction "
                "quantify output effects, semantic benefit, or a winning experimental cell."
            ),
        },
    }


def write_fresh(path: Path, receipt: dict[str, Any]) -> None:
    encoded = json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(encoded)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--base-snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise IdentityAuditError(f"Refusing to overwrite receipt: {args.output}")
    receipt = audit(args.repo.resolve(), args.base_snapshot.expanduser().resolve())
    write_fresh(args.output, receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "output": str(args.output),
                "changed_tensor_counts": {
                    cell: row["changed_tensor_count"] for cell, row in receipt["cells"].items()
                },
                "historical_base_is_pinned_original": receipt["interpretation"][
                    "historical_base_is_pinned_original"
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
