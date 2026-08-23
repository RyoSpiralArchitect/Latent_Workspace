#!/usr/bin/env python3
"""Freeze the V11 F1 one-update learning-rate response surface."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

PARENT_CONFIG_SHA256 = (
    "863560fec80f5aaf5fb3a8d9e202394ac5473f0efd92bebb98a0ae56e90f25ff"
)
GATE0_RECEIPT_SHA256 = (
    "0b852e53bd65b51499571ce5d9b5c05699c06d44fdf32fd686a2c8666406e7c7"
)
BLOCKED_F1_RECEIPT_SHA256 = (
    "f06f12560539fe9c51ddae2dbb28a19b6dddaba316a56258f52e6ef713d8a79b"
)
BLOCKED_F1_BEHAVIOR_SHA256 = (
    "e700959342c4c14f42b880b32d2a830b9e94c839a543101b89f9522e1c2c4d14"
)
PROMPT_SUITE_SHA256 = (
    "f3710a323b876fd42da19b2c4a97e6fd303b67c0db338da53c57209177979373"
)
TRAIN_SHA256 = "8ca42ca2908a3d554849b6fb0054f838c424fdfed48ca478bbac7174740feea3"
EVAL_SHA256 = "fcd7bdd3966cbcd0fd02315ee76c813aaf51b82f913abdd074f1585d5958386e"
PARENT_COMMIT = "c1b18818364fc42daa07cf2583b0593d484c6019"
MODEL_ID = "mistralai/Mistral-7B-Instruct-v0.3"
MODEL_REVISION = "c170c708c41dac9275d15a8fff4eca08d52bab71"

LEARNING_RATES: tuple[tuple[str, float], ...] = (
    ("lr_2e_5", 2e-5),
    ("lr_6p324555e_6", 6.324555320336759e-6),
    ("lr_2e_6", 2e-6),
    ("lr_6p324555e_7", 6.324555320336759e-7),
    ("lr_2e_7", 2e-7),
)


class PrepareError(RuntimeError):
    """A pinned parent or frozen response-surface assumption changed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


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
    condition_id: str,
    learning_rate: float,
    max_steps: int,
) -> dict[str, Any]:
    if max_steps not in {1, 4}:
        raise PrepareError("Only the frozen one-step surface and four-step confirm exist.")
    config = copy.deepcopy(parent)
    config["train"]["learning_rate"] = learning_rate
    config["train"]["max_steps"] = max_steps
    config["train"]["eval_every"] = 1
    config["train"]["save_every"] = 0
    config["train"]["save_every_minutes"] = 0.0
    config["train"]["output_dir"] = (
        "../../../runs/v11/update_response/"
        f"F1_{condition_id}_seed42_step{max_steps}"
    )
    return config


def prepare(repo_root: Path) -> dict[str, Any]:
    root = repo_root.expanduser().resolve()
    config_root = root / "configs" / "v11"
    condition_root = config_root / "conditions"
    parent_path = condition_root / "config_F1_inline_symmetric_choice_repair.json"
    parent = read_pinned(parent_path, PARENT_CONFIG_SHA256)

    pinned = (
        (
            root
            / "provenance"
            / "pilots"
            / "v11_gate0_symmetric"
            / "GATE0_RECEIPT.json",
            GATE0_RECEIPT_SHA256,
        ),
        (
            root
            / "provenance"
            / "pilots"
            / "v11_f1_symmetric_choice_repair_seed42_step16"
            / "V11_F1_PILOT_RECEIPT.json",
            BLOCKED_F1_RECEIPT_SHA256,
        ),
        (
            root
            / "provenance"
            / "pilots"
            / "v11_f1_symmetric_choice_repair_seed42_step16"
            / "GENERATION_BEHAVIOR_V11.json",
            BLOCKED_F1_BEHAVIOR_SHA256,
        ),
        (root / "configs" / "v10" / "behavior_prompt_suite_v1.json", PROMPT_SUITE_SHA256),
        (root / "data" / "v10" / "functional_train.jsonl", TRAIN_SHA256),
        (root / "data" / "v10" / "functional_eval.jsonl", EVAL_SHA256),
    )
    for path, digest in pinned:
        if sha256_file(path) != digest:
            raise PrepareError(f"Pinned response-surface input changed: {path}")

    if parent["model"]["name_or_path"] != MODEL_ID:
        raise PrepareError("Pinned model id changed.")
    if parent["model"]["revision"] != MODEL_REVISION:
        raise PrepareError("Pinned model revision changed.")
    if parent["model"]["train_mode"] != "full":
        raise PrepareError("Response surface requires the frozen full-update route.")
    if parent["train"]["optimizer"] != "adafactor":
        raise PrepareError("Response surface requires the frozen Adafactor optimizer.")
    if parent["functional"]["task_objective"] != "choice_normalized":
        raise PrepareError("Response surface requires choice-normalized CE.")
    if parent["data"]["functional_elicitation"] != "symmetric_instruction":
        raise PrepareError("Response surface requires the qualified elicitation.")

    artifacts: dict[str, Any] = {}
    for condition_id, learning_rate in LEARNING_RATES:
        condition_artifacts: dict[str, Any] = {"learning_rate": learning_rate}
        for max_steps in (1, 4):
            config = make_condition(
                parent,
                condition_id=condition_id,
                learning_rate=learning_rate,
                max_steps=max_steps,
            )
            path = condition_root / (
                f"config_F1_update_response_{condition_id}_step{max_steps}.json"
            )
            atomic_write(path, config)
            condition_artifacts[f"step{max_steps}"] = {
                "path": f"conditions/{path.name}",
                "sha256": sha256_file(path),
                "output_dir": config["train"]["output_dir"],
            }
        artifacts[condition_id] = condition_artifacts

    contract = {
        "format": "latent-workspace-ft-v11-update-response-contract-v1",
        "schema_version": 1,
        "frozen_before_execution": True,
        "question": (
            "At what Adafactor base learning-rate scale does one full-model "
            "BF16 update preserve the qualified F1 decision boundary while "
            "producing a non-zero persisted base-weight change?"
        ),
        "parent_commit": PARENT_COMMIT,
        "model": {"name_or_path": MODEL_ID, "revision": MODEL_REVISION},
        "trigger": {
            "failed_hypothesis": (
                "Choice-normalized CE alone is sufficient under the original "
                "2e-5 full-update schedule."
            ),
            "blocked_f1_receipt": {
                "path": (
                    "../../provenance/pilots/"
                    "v11_f1_symmetric_choice_repair_seed42_step16/"
                    "V11_F1_PILOT_RECEIPT.json"
                ),
                "sha256": BLOCKED_F1_RECEIPT_SHA256,
            },
            "blocked_f1_behavior": {
                "path": (
                    "../../provenance/pilots/"
                    "v11_f1_symmetric_choice_repair_seed42_step16/"
                    "GENERATION_BEHAVIOR_V11.json"
                ),
                "sha256": BLOCKED_F1_BEHAVIOR_SHA256,
            },
        },
        "no_update_control": {
            "path": "../../provenance/pilots/v11_gate0_symmetric/GATE0_RECEIPT.json",
            "sha256": GATE0_RECEIPT_SHA256,
            "condition": "F1_inline",
            "optimizer_steps": 0,
        },
        "single_factor": {
            "name": "train.learning_rate",
            "scale": "half-decade logarithmic grid",
            "values": [value for _condition_id, value in LEARNING_RATES],
        },
        "held_fixed": [
            "Mistral-7B model id, revision, and BF16 stored parameters",
            "F1 inline route and train-selected symmetric elicitation",
            "choice-normalized objective with zero full-vocabulary loss weight",
            "functional train and eval bytes",
            "seed 42 and deterministic first eight-record accumulation window",
            "Adafactor settings, weight decay, and per-family gradient clipping",
            "eight-microbatch cpu_accumulate transport",
            "step-0 and post-update complete 1,024-case eval",
        ],
        "execution": {
            "condition_order": [condition_id for condition_id, _value in LEARNING_RATES],
            "primary_optimizer_steps": 1,
            "eval_every": 1,
            "eval_batches": 0,
            "save_periodic_checkpoints": False,
            "retain_all_weights_until_behavior_capture": True,
            "launch_optimizer_or_precision_surface": False,
        },
        "post_update_eligibility_gates": {
            "require_integrity_pass": True,
            "require_exact_step0_parity": True,
            "require_exact_pre_update_window_metrics": True,
            "require_applied_learning_rate_match": True,
            "require_nonzero_persisted_base_update": True,
            "minimum_distinct_predicted_classes": 2,
            "minimum_accuracy": 0.75,
            "minimum_label_recall": 0.60,
            "maximum_choice_loss_increase": 0.02,
            "maximum_full_vocab_loss_increase": 0.25,
            "require_finite_decision_metrics": True,
        },
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
        "selection_rule": [
            "Exclude any condition failing integrity, post-update gates, or behavior veto.",
            "Rank eligible conditions by lower post-update choice loss.",
            "Then rank by higher accuracy and higher minimum label recall.",
            "Then rank by lower full-vocabulary loss and larger changed-element fraction.",
            "Break any remaining tie by the higher learning rate.",
        ],
        "preauthorized_followup": {
            "action": "Run only the selected condition for four optimizer steps.",
            "blocked_if_no_eligible_condition": True,
            "step4_gates": {
                "minimum_accuracy": 0.70,
                "minimum_label_recall": 0.60,
                "minimum_distinct_predicted_classes": 2,
                "require_final_choice_loss_below_step0": True,
                "maximum_final_full_vocab_loss": 1.50,
                "require_behavior_veto_pass": True,
            },
        },
        "deferred": [
            "AdamW comparison until optimizer-state offload is implemented and validated",
            "FP32 parameter update until a memory-safe master-weight path exists",
            "O0 workspace route, 16-step promotion, 57-run matrix, and 14B scaling",
        ],
        "artifacts": artifacts,
        "claim_boundary": (
            "This one-seed response surface can identify a bounded update-scale "
            "region for the exact frozen harness. It cannot identify Adafactor, "
            "BF16 quantization, clipping, or learning rate as a unique general "
            "cause, and preservation after one update is not a training win."
        ),
    }
    contract_path = config_root / "UPDATE_RESPONSE_CONTRACT.json"
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
