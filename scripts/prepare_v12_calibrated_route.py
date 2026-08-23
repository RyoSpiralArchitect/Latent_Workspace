#!/usr/bin/env python3
"""Freeze the V12 no-op sidecar, ownership, and semantic comparison matrix."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

PARENT_COMMIT = "a76459c2853fe9fd03bd0e7d0c774c50633d4edd"
PARENT_CONFIG_SHA256 = "cf2e9a7d8418613cef6f9a52f974217ef1f98fbe25586cedcb9eab77cf5c991f"
V11_CONTRACT_SHA256 = "5491e6c46d7982b6f9cda80e831b921179573d03fd060800aa01005d38b8eec3"
V11_RECEIPT_SHA256 = "2c7a08f00a0800e18c51e8b9e44be2c43c16ddef13e82d8d6a7a4d92a9467f55"
V11_BEHAVIOR_SHA256 = "6cfb8c5feade382f67d0ea0ba93f76280bc80fbc8c816d120b41504eeb2a4a3e"
PROMPT_SUITE_SHA256 = "f3710a323b876fd42da19b2c4a97e6fd303b67c0db338da53c57209177979373"
TRAIN_SHA256 = "8ca42ca2908a3d554849b6fb0054f838c424fdfed48ca478bbac7174740feea3"
EVAL_SHA256 = "fcd7bdd3966cbcd0fd02315ee76c813aaf51b82f913abdd074f1585d5958386e"

MODEL_ID = "mistralai/Mistral-7B-Instruct-v0.3"
MODEL_REVISION = "c170c708c41dac9275d15a8fff4eca08d52bab71"
BASE_LEARNING_RATE = 1e-7
WORKSPACE_LEARNING_RATES = (1e-5, 3e-5, 1e-4)
SEEDS = (43, 44, 45)
BRANCHES = ("task", "semantic")
SEMANTIC_WEIGHTS = {"counterfactual": 1.0, "stability": 0.25}


class PrepareError(RuntimeError):
    """A pinned input or frozen V12 assumption changed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_pinned(path: Path, digest: str) -> dict[str, Any]:
    if sha256_file(path) != digest:
        raise PrepareError(f"Pinned input changed: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PrepareError(f"Pinned input is not a JSON object: {path}")
    return value


def learning_rate_slug(value: float) -> str:
    labels = {1e-5: "1e_5", 3e-5: "3e_5", 1e-4: "1e_4"}
    try:
        return labels[float(value)]
    except KeyError as exc:
        raise PrepareError(f"Unregistered workspace learning rate: {value}") from exc


def _assert_parent(parent: dict[str, Any]) -> None:
    if parent["model"]["name_or_path"] != MODEL_ID:
        raise PrepareError("Pinned model id changed.")
    if parent["model"]["revision"] != MODEL_REVISION:
        raise PrepareError("Pinned model revision changed.")
    if parent["functional"]["route_mode"] != "deferred":
        raise PrepareError("Pinned parent is not the failed deferred O0 route.")
    if parent["functional"]["memory_mode"] != "slots":
        raise PrepareError("Pinned parent is not the four-slot memory route.")
    if int(parent["functional"]["slot_count"]) != 4:
        raise PrepareError("Pinned parent slot count changed.")
    if parent["functional"]["task_objective"] != "choice_normalized":
        raise PrepareError("Pinned parent objective changed.")
    if parent["train"]["gradient_accumulation_offload"] != "cpu_accumulate":
        raise PrepareError("Pinned CPU accumulation transport changed.")


def make_config(
    parent: dict[str, Any],
    *,
    workspace_learning_rate: float,
    seed: int,
    max_steps: int,
    branch: str,
) -> dict[str, Any]:
    if branch not in BRANCHES:
        raise PrepareError(f"Unsupported branch: {branch}")
    if max_steps not in {1, 4, 16}:
        raise PrepareError(f"Unsupported V12 horizon: {max_steps}")
    config = copy.deepcopy(parent)

    config["functional"].update(
        {
            "route_mode": "inline_sidecar",
            "memory_mode": "slots",
            "slot_count": 4,
            "writer_steps": 1,
            "reader_steps": 1,
            "injection_scale": 1.0,
            "gate_init_bias": -2.0,
            "counterfactual_weight": (
                SEMANTIC_WEIGHTS["counterfactual"] if branch == "semantic" else 0.0
            ),
            "stability_weight": (SEMANTIC_WEIGHTS["stability"] if branch == "semantic" else 0.0),
        }
    )
    config["workspace"]["loss_weight"] = 0.0
    config["workspace"]["aux_backprop_to_base"] = False
    config["attribution"].update(
        {
            "clip_mode": "per_family",
            "base_max_grad_norm": 1.0,
            "workspace_max_grad_norm": 0.25,
        }
    )
    config["model"]["train_mode"] = "full"

    train = config["train"]
    train.update(
        {
            "learning_rate": BASE_LEARNING_RATE,
            "workspace_learning_rate": float(workspace_learning_rate),
            "seed": int(seed),
            "max_steps": int(max_steps),
            "base_release_step": 4 if max_steps == 16 else max_steps,
            "eval_at_start": True,
            "eval_every": 4 if max_steps == 16 else 1,
            "eval_batches": 0,
            "save_every": 0,
            "save_every_minutes": 0.0,
            "resume_from": "none",
            "allow_schedule_extension": False,
            "save_optimizer": True,
        }
    )
    lr_slug = learning_rate_slug(workspace_learning_rate)
    if max_steps == 1:
        stage = "step1"
        condition = f"task_lr_{lr_slug}_seed{seed}_step1"
    elif max_steps == 4:
        stage = "stage4"
        condition = f"{branch}_lr_{lr_slug}_seed{seed}_step4"
    else:
        stage = "refinement16"
        condition = f"{branch}_lr_{lr_slug}_seed{seed}_step16"
    train["output_dir"] = f"../../../runs/v12/calibrated_route/{stage}/{condition}"

    config["assays"]["amputation_eval"] = True
    config["assays"]["amputation_eval_every"] = 0
    config["assays"]["necessity"]["enabled"] = max_steps == 16
    return config


def _artifact(
    path: Path,
    config: dict[str, Any],
    *,
    branch: str,
    seed: int,
    learning_rate: float,
) -> dict[str, Any]:
    return {
        "condition_id": path.stem.removeprefix("config_"),
        "branch": branch,
        "seed": seed,
        "workspace_learning_rate": float(learning_rate),
        "base_learning_rate": float(config["train"]["learning_rate"]),
        "base_release_step": int(config["train"]["base_release_step"]),
        "max_steps": int(config["train"]["max_steps"]),
        "path": f"conditions/{path.name}",
        "sha256": sha256_file(path),
        "output_dir": config["train"]["output_dir"],
    }


def prepare(repo_root: Path) -> dict[str, Any]:
    root = repo_root.expanduser().resolve()
    config_root = root / "configs" / "v12"
    condition_root = config_root / "conditions"
    parent_path = root / "configs/v11/conditions/config_O0_slots4_k1_symmetric_choice_repair.json"
    parent = read_pinned(parent_path, PARENT_CONFIG_SHA256)
    _assert_parent(parent)

    pinned = (
        (root / "configs/v11/F1_O0_REFINEMENT_CONTRACT.json", V11_CONTRACT_SHA256),
        (
            root / "provenance/pilots/v11_f1_o0_refinement/REFINEMENT_RECEIPT.json",
            V11_RECEIPT_SHA256,
        ),
        (
            root / "provenance/pilots/v11_f1_o0_refinement/refinement16/GENERATION_BEHAVIOR.json",
            V11_BEHAVIOR_SHA256,
        ),
        (root / "configs/v10/behavior_prompt_suite_v1.json", PROMPT_SUITE_SHA256),
        (root / "data/v10/functional_train.jsonl", TRAIN_SHA256),
        (root / "data/v10/functional_eval.jsonl", EVAL_SHA256),
    )
    for path, digest in pinned:
        if sha256_file(path) != digest:
            raise PrepareError(f"Pinned V12 input changed: {path}")

    step1: dict[str, Any] = {}
    stage4: dict[str, Any] = {}
    refinement16: dict[str, Any] = {}
    for learning_rate in WORKSPACE_LEARNING_RATES:
        lr_slug = learning_rate_slug(learning_rate)
        step_config = make_config(
            parent,
            workspace_learning_rate=learning_rate,
            seed=43,
            max_steps=1,
            branch="task",
        )
        step_path = condition_root / f"config_task_lr_{lr_slug}_seed43_step1.json"
        atomic_write(step_path, step_config)
        step1[lr_slug] = _artifact(
            step_path,
            step_config,
            branch="task",
            seed=43,
            learning_rate=learning_rate,
        )

        for branch in BRANCHES:
            for seed in SEEDS:
                stage4_config = make_config(
                    parent,
                    workspace_learning_rate=learning_rate,
                    seed=seed,
                    max_steps=4,
                    branch=branch,
                )
                stage4_path = condition_root / (
                    f"config_{branch}_lr_{lr_slug}_seed{seed}_step4.json"
                )
                atomic_write(stage4_path, stage4_config)
                stage4[f"{branch}_{lr_slug}_seed{seed}"] = _artifact(
                    stage4_path,
                    stage4_config,
                    branch=branch,
                    seed=seed,
                    learning_rate=learning_rate,
                )

                refinement_config = make_config(
                    parent,
                    workspace_learning_rate=learning_rate,
                    seed=seed,
                    max_steps=16,
                    branch=branch,
                )
                refinement_path = condition_root / (
                    f"config_{branch}_lr_{lr_slug}_seed{seed}_step16.json"
                )
                atomic_write(refinement_path, refinement_config)
                refinement16[f"{branch}_{lr_slug}_seed{seed}"] = _artifact(
                    refinement_path,
                    refinement_config,
                    branch=branch,
                    seed=seed,
                    learning_rate=learning_rate,
                )

    contract: dict[str, Any] = {
        "format": "latent-workspace-ft-v12-calibrated-route-contract-v1",
        "schema_version": 1,
        "frozen_before_execution": True,
        "parent_commit": PARENT_COMMIT,
        "question": (
            "Can a zero-initialized inline sidecar preserve the qualified base "
            "boundary, separate workspace/base update ownership, and acquire "
            "replicated content-specific counterfactual behavior without the V11 "
            "active-route collapse?"
        ),
        "model": {"name_or_path": MODEL_ID, "revision": MODEL_REVISION},
        "data": {
            "train": {"path": "../../data/v10/functional_train.jsonl", "sha256": TRAIN_SHA256},
            "eval": {"path": "../../data/v10/functional_eval.jsonl", "sha256": EVAL_SHA256},
        },
        "v11_control": {
            "contract": {
                "path": "../v11/F1_O0_REFINEMENT_CONTRACT.json",
                "sha256": V11_CONTRACT_SHA256,
            },
            "receipt": {
                "path": "../../provenance/pilots/v11_f1_o0_refinement/REFINEMENT_RECEIPT.json",
                "sha256": V11_RECEIPT_SHA256,
            },
            "behavior": {
                "path": (
                    "../../provenance/pilots/v11_f1_o0_refinement/"
                    "refinement16/GENERATION_BEHAVIOR.json"
                ),
                "sha256": V11_BEHAVIOR_SHA256,
            },
            "f1_mean_accuracy": 0.7692057291666666,
            "original_behavior_accuracy": 0.875,
        },
        "route_design": {
            "route_mode": "inline_sidecar",
            "inline_base_is_authoritative": True,
            "sidecar_input_detached_from_base": True,
            "sidecar_logit_up_projection_zero_initialized": True,
            "amputation_restores": "inline",
            "memory_mode": "slots",
            "slot_count": 4,
            "reader_steps": 1,
            "writer_steps": 1,
            "gate_init_bias": -2.0,
            "injection_scale": 1.0,
        },
        "ownership": {
            "clip_mode": "per_family",
            "base_max_grad_norm": 1.0,
            "workspace_max_grad_norm": 0.25,
            "base_learning_rate_after_release": BASE_LEARNING_RATE,
            "step1_base_release_step": 1,
            "stage4_base_release_step": 4,
            "refinement16_base_release_step": 4,
            "frozen_semantics": (
                "Base gradients are measured and clipped, then cleared before "
                "Adafactor; applied base LR is zero and no base optimizer state "
                "may be created before release."
            ),
        },
        "v12_0_noop_gate": {
            "config": step1["1e_5"],
            "optimizer_steps": 0,
            "complete_eval_cases": 1024,
            "requirements": {
                "bitwise_choice_logits": True,
                "exact_predictions": True,
                "exact_complete_metrics": True,
                "zero_sidecar_delta_logit_norm": True,
                "routed_amputated_exact": True,
            },
        },
        "v12_1_step1_response": {
            "condition_order": [learning_rate_slug(lr) for lr in WORKSPACE_LEARNING_RATES],
            "artifacts": step1,
            "gates": {
                "require_integrity_pass": True,
                "require_base_sentinel_unchanged": True,
                "require_zero_applied_base_lr": True,
                "require_no_base_optimizer_state": True,
                "require_workspace_sentinel_updated": True,
                "minimum_accuracy": 0.75,
                "minimum_label_recall": 0.65,
                "minimum_distinct_predicted_classes": 2,
                "maximum_full_vocab_loss": 1.0,
            },
            "selection_rule": (
                "Among passing cells, maximize final complete-eval accuracy, then "
                "minimize choice loss, then choose the lower workspace LR."
            ),
        },
        "v12_2_stage4": {
            "artifacts": stage4,
            "branches": {
                "task": {"counterfactual_weight": 0.0, "stability_weight": 0.0},
                "semantic": {
                    "counterfactual_weight": SEMANTIC_WEIGHTS["counterfactual"],
                    "stability_weight": SEMANTIC_WEIGHTS["stability"],
                },
            },
            "required_seeds": list(SEEDS),
            "gates": {
                "require_every_seed_integrity_pass": True,
                "require_base_exactly_unchanged": True,
                "require_four_frozen_ownership_records": True,
                "minimum_accuracy": 0.75,
                "minimum_label_recall": 0.65,
                "minimum_distinct_predicted_classes": 2,
                "maximum_full_vocab_loss": 1.0,
                "minimum_behavior_task_accuracy": 0.75,
            },
            "promotion_rule": "Promote each branch independently only if every seed passes.",
        },
        "v12_3_refinement16": {
            "artifacts": refinement16,
            "required_seeds": list(SEEDS),
            "fresh_from_pinned_model": True,
            "base_frozen_updates": 4,
            "joint_updates": 12,
            "gates": {
                "require_every_promoted_seed_integrity_pass": True,
                "require_base_release_at_step5": True,
                "require_nonzero_persisted_base_update": True,
                "minimum_accuracy": 0.70,
                "minimum_label_recall": 0.60,
                "minimum_distinct_predicted_classes": 2,
                "maximum_full_vocab_loss": 1.5,
                "minimum_behavior_task_accuracy": 0.75,
            },
            "necessity": {
                "required_levels": ["F0", "F1", "F2", "F3", "F4", "F5"],
                "content_specific_replication_requires": ["F3", "F4"],
                "minimum_replicating_seeds": 2,
            },
        },
        "decision_rules": [
            {
                "id": "promote_semantic_sidecar",
                "when": "semantic is robust and F3/F4 replicate in at least two seeds",
            },
            {
                "id": "stable_redundant_sidecar",
                "when": "semantic is robust but content-specific necessity does not replicate",
            },
            {
                "id": "task_only_survives",
                "when": "task-only is robust while semantic is not",
            },
            {
                "id": "revisit_route",
                "when": "no sidecar branch is robust",
            },
        ],
        "behavior_veto": {
            "prompt_suite": {
                "path": "../v10/behavior_prompt_suite_v1.json",
                "sha256": PROMPT_SUITE_SHA256,
            },
            "minimum_task_subset_accuracy": 0.75,
            "minimum_distinct_task_choices": 2,
            "maximum_single_token_run": 24,
            "maximum_top_token_fraction": 0.75,
        },
        "execution_boundaries": {
            "run_only_selected_lr_after_step1": True,
            "run_refinement_only_for_stage4_promoted_branches": True,
            "retain_weights_until_generation_and_necessity_complete": True,
            "no_14b_scale_up_authorized": True,
        },
        "claim_boundary": (
            "This contract can establish no-op initialization, update ownership, "
            "bounded task robustness, and controlled memory-intervention effects on "
            "the pinned Mistral-7B task. It cannot establish broad capability gains, "
            "intrinsic workspace necessity, transfer to 14B, or a general global workspace."
        ),
    }
    atomic_write(config_root / "CONTRACT.json", contract)
    return contract


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    contract = prepare(args.repo_root)
    print(json.dumps(contract, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
