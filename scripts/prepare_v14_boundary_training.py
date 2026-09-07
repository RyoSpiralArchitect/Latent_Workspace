#!/usr/bin/env python3
"""Prepare the matched V14 layer-16 boundary-return training pair."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "configs/v14/boundary_training"
TRAJECTORY_REPORT = REPO / "provenance/raw/v14_semantic_trajectory_20260907/report.json"
TRAJECTORY_SHA256 = "2fb9a403ec7d495b3f860c82db314fa89fdeccacff3ab280695409a017888883"
PARENTS = {
    "task": REPO / "configs/v12/conditions/config_task_lr_1e_5_seed43_step16.json",
    "semantic": REPO
    / "configs/v12/conditions/config_semantic_lr_1e_5_seed43_step16.json",
}
SEED = 47
MAX_STEPS = 8
BASE_RELEASE_STEP = 4


class PrepareError(RuntimeError):
    """Raised when the boundary-training preparation contract is violated."""


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_new(path: Path, value: Any) -> None:
    if path.exists():
        raise PrepareError(f"Refusing to overwrite generated config: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def make_config(parent: dict[str, Any], branch: str) -> dict[str, Any]:
    if branch not in ("task", "semantic"):
        raise PrepareError(f"Unknown branch: {branch}")
    config = copy.deepcopy(parent)
    config["functional"].update(
        {
            "route_mode": "deferred",
            "boundary_layer": 16,
            "memory_mode": "slots",
            "slot_count": 4,
            "writer_steps": 1,
            "reader_steps": 1,
            "readout_step": -1,
            "injection_scale": 1.0,
            "counterfactual_weight": 1.0 if branch == "semantic" else 0.0,
            "stability_weight": 0.25 if branch == "semantic" else 0.0,
            "task_objective": "choice_normalized",
        }
    )
    config["workspace"]["loss_weight"] = 0.0
    config["workspace"]["aux_backprop_to_base"] = False
    config["model"].update(
        {
            "train_mode": "full",
            "hidden_capture": "hidden_states",
            "gradient_checkpointing": True,
            "attn_implementation": "sdpa",
            "dtype": "bfloat16",
            "local_files_only": True,
        }
    )
    config["train"].update(
        {
            "seed": SEED,
            "max_steps": MAX_STEPS,
            "base_release_step": BASE_RELEASE_STEP,
            "batch_size": 1,
            "eval_batch_size": 1,
            "gradient_accumulation_steps": 8,
            "gradient_accumulation_offload": "cpu_accumulate",
            "base_activation_offload": "legacy_functional",
            "learning_rate": 1e-7,
            "workspace_learning_rate": 1e-5,
            "mixed_precision": "bf16",
            "eval_at_start": True,
            "eval_every": 4,
            "save_every": 4,
            "save_every_minutes": 0.0,
            "save_best": False,
            "keep_last_checkpoints": 2,
            "save_frozen_base": False,
            "save_optimizer": True,
            "resume_from": "none",
            "strict_resume": True,
            "strict_source_resume": True,
            "strict_torch_resume": True,
            "minimum_free_disk_gb": 50.0,
            "output_dir": (
                f"../../../runs/v14/boundary_training/{branch}_seed{SEED}_step{MAX_STEPS}"
            ),
        }
    )
    config["assays"].update(
        {
            "amputation_eval": True,
            "amputation_eval_every": 4,
            "gradient_alignment_every": 0,
        }
    )
    necessity = config["assays"]["necessity"]
    necessity.update(
        {
            "enabled": True,
            "require_deferred_bridge": False,
            "require_counterfactual_pairs": False,
            "run_choice_eval": False,
            "batch_size": 4,
            "eval_batches": 0,
            "modes": [
                "intact",
                "hard_bypass",
                "zero",
                "fixed_carrier",
                "norm_matched_random",
                "counterfactual_twin",
                "cross_world_shuffle",
            ],
        }
    )
    return config


def validate_pair(configs: dict[str, dict[str, Any]]) -> None:
    if set(configs) != {"task", "semantic"}:
        raise PrepareError("Exactly task and semantic configs are required")
    task = copy.deepcopy(configs["task"])
    semantic = copy.deepcopy(configs["semantic"])
    for value in (task, semantic):
        value["functional"].pop("counterfactual_weight")
        value["functional"].pop("stability_weight")
        value["train"].pop("output_dir")
    if task != semantic:
        raise PrepareError("Training cells differ outside objective weights/output paths")
    if configs["task"]["functional"]["counterfactual_weight"] != 0.0:
        raise PrepareError("Task cell must disable the counterfactual objective")
    if configs["semantic"]["functional"]["counterfactual_weight"] != 1.0:
        raise PrepareError("Semantic cell must enable the counterfactual objective")
    for branch, config in configs.items():
        train = config["train"]
        functional = config["functional"]
        if (
            train["keep_last_checkpoints"] != 2
            or train["save_every"] != 4
            or train["max_steps"] != 8
            or train["base_release_step"] != 4
            or functional["route_mode"] != "deferred"
            or functional["boundary_layer"] != 16
        ):
            raise PrepareError(f"Frozen training or retention contract changed: {branch}")


def prepare() -> dict[str, Any]:
    if digest(TRAJECTORY_REPORT) != TRAJECTORY_SHA256:
        raise PrepareError("Trajectory predecessor hash mismatch")
    trajectory = json.loads(TRAJECTORY_REPORT.read_text(encoding="utf-8"))
    if (
        trajectory.get("status") != "QUALIFIED_EXECUTION"
        or trajectory.get("trajectory_execution_qualified") is not True
        or trajectory.get("semantic_effect_qualified") is not False
    ):
        raise PrepareError("Training requires a valid but semantically unpromoted trajectory")
    parent_hashes = {name: digest(path) for name, path in PARENTS.items()}
    configs = {
        branch: make_config(json.loads(path.read_text(encoding="utf-8")), branch)
        for branch, path in PARENTS.items()
    }
    validate_pair(configs)
    outputs: dict[str, Any] = {}
    for branch, config in configs.items():
        path = OUTPUT / f"config_{branch}_boundary16_seed{SEED}_step{MAX_STEPS}.json"
        write_new(path, config)
        outputs[branch] = {
            "path": str(path.relative_to(REPO)),
            "sha256": digest(path),
            "output_dir": config["train"]["output_dir"],
        }
    receipt = {
        "format": "latent-workspace-v14-boundary-training-preparation-v1",
        "status": "PREPARED_NOT_RUN",
        "trajectory_report_sha256": TRAJECTORY_SHA256,
        "parent_config_sha256": parent_hashes,
        "cells": outputs,
        "matched_fields": (
            "All fields equal except counterfactual/stability objective weights and output_dir"
        ),
        "full_update_schedule": {
            "max_steps": MAX_STEPS,
            "base_frozen_steps": [1, 2, 3, 4],
            "base_released_steps": [5, 6, 7, 8],
            "seed": SEED,
        },
        "retention": {
            "per_condition": "keep latest and immediately prior distinct saved steps",
            "save_steps": [4, 8],
            "keep_last_checkpoints": 2,
            "final_bundle_separate_role": True,
            "deletion_performed": False,
        },
        "claim_boundary": (
            "Preparation only. It does not establish that either cell trains, that full-base "
            "updates persist, or that layer-16 return is semantic or beneficial."
        ),
    }
    write_new(OUTPUT / "PREPARATION.json", receipt)
    return receipt


def main() -> int:
    receipt = prepare()
    print(json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
