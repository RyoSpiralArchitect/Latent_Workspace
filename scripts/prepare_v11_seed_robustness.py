#!/usr/bin/env python3
"""Freeze the V11 low-learning-rate, new-seed robustness matrix."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

PARENT_CONFIG_SHA256 = "7559978e8a82054ad52b14e97c6177757d8f171c9bd38ffb3af9513a689a6624"
PARENT_CONTRACT_SHA256 = "4dcc8119572e9b0cfd21698a0dd8f0b911a45d0af1573314e49d49ede39bcb1c"
SURFACE_RECEIPT_SHA256 = "360b9ba8c31bdf35a7732d57ce94d5ee646227412a2fbc027c27c6acab60d67d"
PROMOTION_RECEIPT_SHA256 = "8d56f695fe67d0598693629c7849081b978cb693a7eecbddb30772e2a5c19124"
PROMOTION_BEHAVIOR_SHA256 = "e9827320d3ab8b304cdccbb4db35d8c19b4f7199feba1c7e8a4e676dca318482"
PROMPT_SUITE_SHA256 = "f3710a323b876fd42da19b2c4a97e6fd303b67c0db338da53c57209177979373"
TRAIN_SHA256 = "8ca42ca2908a3d554849b6fb0054f838c424fdfed48ca478bbac7174740feea3"
EVAL_SHA256 = "fcd7bdd3966cbcd0fd02315ee76c813aaf51b82f913abdd074f1585d5958386e"
PARENT_COMMIT = "13ecc2a74b394f49d6f1ba1cb5327c3e4e916a0b"
MODEL_ID = "mistralai/Mistral-7B-Instruct-v0.3"
MODEL_REVISION = "c170c708c41dac9275d15a8fff4eca08d52bab71"

LEARNING_RATES: tuple[tuple[str, float], ...] = (
    ("lr_1e_7", 1e-7),
    ("lr_2e_7", 2e-7),
)
SEEDS = (43, 44, 45)
EXECUTION_ORDER = (
    "lr_1e_7_seed43",
    "lr_2e_7_seed43",
    "lr_2e_7_seed44",
    "lr_1e_7_seed44",
    "lr_1e_7_seed45",
    "lr_2e_7_seed45",
)


class PrepareError(RuntimeError):
    """A pinned input or frozen robustness assumption changed."""


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


def make_condition(
    parent: dict[str, Any],
    *,
    learning_rate_id: str,
    learning_rate: float,
    seed: int,
) -> dict[str, Any]:
    config = copy.deepcopy(parent)
    config["train"]["learning_rate"] = learning_rate
    config["train"]["seed"] = seed
    config["train"]["max_steps"] = 4
    config["train"]["eval_every"] = 1
    config["train"]["save_every"] = 0
    config["train"]["save_every_minutes"] = 0.0
    config["train"]["output_dir"] = (
        f"../../../runs/v11/seed_robustness/F1_{learning_rate_id}_seed{seed}_step4"
    )
    return config


def prepare(repo_root: Path) -> dict[str, Any]:
    root = repo_root.expanduser().resolve()
    config_root = root / "configs" / "v11"
    condition_root = config_root / "conditions"
    parent_path = condition_root / "config_F1_update_response_lr_2e_7_step4.json"
    parent = read_pinned(parent_path, PARENT_CONFIG_SHA256)

    pinned = (
        (config_root / "UPDATE_RESPONSE_CONTRACT.json", PARENT_CONTRACT_SHA256),
        (
            root
            / "provenance"
            / "pilots"
            / "v11_update_response_seed42"
            / "UPDATE_RESPONSE_RECEIPT.json",
            SURFACE_RECEIPT_SHA256,
        ),
        (
            root
            / "provenance"
            / "pilots"
            / "v11_update_response_seed42"
            / "STEP4_PROMOTION_RECEIPT.json",
            PROMOTION_RECEIPT_SHA256,
        ),
        (
            root
            / "provenance"
            / "pilots"
            / "v11_update_response_seed42"
            / "GENERATION_BEHAVIOR_STEP4.json",
            PROMOTION_BEHAVIOR_SHA256,
        ),
        (root / "configs" / "v10" / "behavior_prompt_suite_v1.json", PROMPT_SUITE_SHA256),
        (root / "data" / "v10" / "functional_train.jsonl", TRAIN_SHA256),
        (root / "data" / "v10" / "functional_eval.jsonl", EVAL_SHA256),
    )
    for path, digest in pinned:
        if sha256_file(path) != digest:
            raise PrepareError(f"Pinned robustness input changed: {path}")

    if parent["model"]["name_or_path"] != MODEL_ID:
        raise PrepareError("Pinned model id changed.")
    if parent["model"]["revision"] != MODEL_REVISION:
        raise PrepareError("Pinned model revision changed.")
    if parent["model"]["train_mode"] != "full":
        raise PrepareError("Robustness matrix requires full-model update.")
    if parent["train"]["optimizer"] != "adafactor":
        raise PrepareError("Robustness matrix requires Adafactor.")
    if parent["functional"]["task_objective"] != "choice_normalized":
        raise PrepareError("Robustness matrix requires choice-normalized CE.")
    if parent["data"]["functional_elicitation"] != "symmetric_instruction":
        raise PrepareError("Robustness matrix requires qualified elicitation.")

    artifacts: dict[str, Any] = {}
    learning_rate_by_id = dict(LEARNING_RATES)
    for condition_id in EXECUTION_ORDER:
        learning_rate_id, seed_text = condition_id.rsplit("_seed", maxsplit=1)
        seed = int(seed_text)
        learning_rate = learning_rate_by_id[learning_rate_id]
        config = make_condition(
            parent,
            learning_rate_id=learning_rate_id,
            learning_rate=learning_rate,
            seed=seed,
        )
        path = condition_root / f"config_F1_seed_robustness_{condition_id}_step4.json"
        atomic_write(path, config)
        artifacts[condition_id] = {
            "learning_rate_id": learning_rate_id,
            "learning_rate": learning_rate,
            "seed": seed,
            "path": f"conditions/{path.name}",
            "sha256": sha256_file(path),
            "output_dir": config["train"]["output_dir"],
        }

    contract = {
        "format": "latent-workspace-ft-v11-seed-robustness-contract-v1",
        "schema_version": 1,
        "frozen_before_execution": True,
        "question": (
            "Across three new training-order seeds, does 1e-7 or 2e-7 provide "
            "the more robust four-update F1 full-update baseline under the "
            "already qualified metric and generation-behavior gates?"
        ),
        "parent_commit": PARENT_COMMIT,
        "model": {"name_or_path": MODEL_ID, "revision": MODEL_REVISION},
        "data": {
            "train": {
                "path": "../../data/v10/functional_train.jsonl",
                "sha256": TRAIN_SHA256,
            },
            "eval": {
                "path": "../../data/v10/functional_eval.jsonl",
                "sha256": EVAL_SHA256,
            },
        },
        "prior_selected_baseline": {
            "selection_seed": 42,
            "selected_learning_rate": 2e-7,
            "contract": {
                "path": "UPDATE_RESPONSE_CONTRACT.json",
                "sha256": PARENT_CONTRACT_SHA256,
            },
            "surface_receipt": {
                "path": (
                    "../../provenance/pilots/v11_update_response_seed42/"
                    "UPDATE_RESPONSE_RECEIPT.json"
                ),
                "sha256": SURFACE_RECEIPT_SHA256,
            },
            "promotion_receipt": {
                "path": (
                    "../../provenance/pilots/v11_update_response_seed42/"
                    "STEP4_PROMOTION_RECEIPT.json"
                ),
                "sha256": PROMOTION_RECEIPT_SHA256,
            },
            "promotion_behavior": {
                "path": (
                    "../../provenance/pilots/v11_update_response_seed42/"
                    "GENERATION_BEHAVIOR_STEP4.json"
                ),
                "sha256": PROMOTION_BEHAVIOR_SHA256,
            },
            "role": "design input only; seed 42 is excluded from robustness aggregation",
        },
        "matched_design": {
            "learning_rates": [
                {"id": learning_rate_id, "value": value}
                for learning_rate_id, value in LEARNING_RATES
            ],
            "new_seeds": list(SEEDS),
            "cells": len(LEARNING_RATES) * len(SEEDS),
            "pairing": "Both learning rates use the same train seed within each pair.",
            "seed42_excluded": True,
        },
        "held_fixed": [
            "Mistral-7B model id, revision, and BF16 stored parameters",
            "F1 inline route and train-selected symmetric elicitation",
            "choice-normalized objective with zero full-vocabulary loss weight",
            "functional train and eval bytes",
            "Adafactor, weight decay, clipping, and cosine scheduler semantics",
            "four optimizer steps with eight-microbatch cpu_accumulate transport",
            "step-0 and every-step complete 1,024-case eval",
            "behavior prompt suite, greedy decoding, token cap, and capture seed",
        ],
        "execution": {
            "condition_order": list(EXECUTION_ORDER),
            "optimizer_steps": 4,
            "eval_every": 1,
            "eval_batches": 0,
            "save_periodic_checkpoints": False,
            "retain_all_weights_until_behavior_capture": True,
            "alternating_pair_order": True,
        },
        "cell_gates": {
            "require_integrity_pass": True,
            "require_exact_step0_parity": True,
            "require_exact_pre_update_window_within_seed_pair": True,
            "require_applied_learning_rate_schedule_match": True,
            "require_nonzero_persisted_base_update": True,
            "minimum_accuracy": 0.70,
            "minimum_label_recall": 0.60,
            "minimum_distinct_predicted_classes": 2,
            "require_final_choice_loss_below_step0": True,
            "maximum_final_full_vocab_loss": 1.50,
            "require_finite_decision_metrics": True,
            "require_behavior_veto_pass": True,
        },
        "behavior_veto": {
            "prompt_suite": {
                "path": "../v10/behavior_prompt_suite_v1.json",
                "sha256": PROMPT_SUITE_SHA256,
            },
            "capture_seed": 20260823,
            "max_new_tokens": 96,
            "minimum_task_subset_accuracy": 0.75,
            "minimum_distinct_task_choices": 2,
            "maximum_single_token_run": 24,
            "maximum_top_token_fraction": 0.75,
        },
        "learning_rate_robustness_gate": {
            "required_new_seeds": list(SEEDS),
            "require_every_cell_eligible": True,
            "minimum_passed_seed_fraction": 1.0,
            "allow_seed42_in_aggregation": False,
        },
        "selection_rule": [
            "Exclude any learning rate that fails a frozen cell gate on any new seed.",
            "Rank robust learning rates by higher worst-seed behavior task accuracy.",
            "Then rank by higher worst-seed complete-eval accuracy.",
            "Then rank by higher worst-seed minimum label recall.",
            "Then rank by lower worst-seed and lower mean final choice loss.",
            "Break any remaining tie by the lower learning rate.",
        ],
        "post_result_authority": {
            "selected_learning_rate_becomes_candidate_f1_baseline": True,
            "next_contract_design_authorized": True,
            "further_training_or_o0_execution_authorized": False,
        },
        "deferred": [
            "O0 or other active-workspace execution until a separate matched contract is frozen",
            "sixteen-step continuation",
            "optimizer or precision comparison",
            "14B scaling and the broad matrix",
        ],
        "artifacts": artifacts,
        "claim_boundary": (
            "This matched six-cell matrix can establish descriptive four-step "
            "robustness across new seeds 43, 44, and 45 for the two tested "
            "learning rates. The rates were chosen after seed-42 exploration; "
            "n=3 does not establish broad optimizer, model, or long-run robustness."
        ),
    }
    contract_path = config_root / "SEED_ROBUSTNESS_CONTRACT.json"
    atomic_write(contract_path, contract)
    return {
        "contract": str(contract_path),
        "contract_sha256": sha256_file(contract_path),
        "conditions": artifacts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    result = prepare(parser.parse_args().repo_root)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
