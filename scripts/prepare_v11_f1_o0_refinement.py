#!/usr/bin/env python3
"""Freeze the matched V11 F1-versus-O0 comparison and refinement matrix."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

PARENT_COMMIT = "dbe5faa4ac6a78acf9b2fb552c7a1bbdb257a276"
O0_PARENT_SHA256 = "cf2e9a7d8418613cef6f9a52f974217ef1f98fbe25586cedcb9eab77cf5c991f"
F1_CONTRACT_SHA256 = "b5e513c390a392946ccf43715e8a1ae62e381d4a0c43a43c10d5a9394456b820"
F1_RECEIPT_SHA256 = "58d9543e24ba2cc0031a44ed6a85cd27e5e62747b1b8460f9b45d352501ba577"
F1_BEHAVIOR_SHA256 = "4dc6a984067d84b3728a5a81b95c774bb03edaa8eceb77256f7842e446dcee52"
PROMPT_SUITE_SHA256 = "f3710a323b876fd42da19b2c4a97e6fd303b67c0db338da53c57209177979373"
TRAIN_SHA256 = "8ca42ca2908a3d554849b6fb0054f838c424fdfed48ca478bbac7174740feea3"
EVAL_SHA256 = "fcd7bdd3966cbcd0fd02315ee76c813aaf51b82f913abdd074f1585d5958386e"
MODEL_ID = "mistralai/Mistral-7B-Instruct-v0.3"
MODEL_REVISION = "c170c708c41dac9275d15a8fff4eca08d52bab71"
BASE_LEARNING_RATE = 1e-7
WORKSPACE_LEARNING_RATE = 3e-4
SEEDS = (43, 44, 45)
STAGE4_ORDER = tuple(f"O0_seed{seed}" for seed in SEEDS)
REFINEMENT_ORDER = (
    "F1_seed43",
    "O0_seed43",
    "O0_seed44",
    "F1_seed44",
    "F1_seed45",
    "O0_seed45",
)
F1_CONFIG_HASHES = {
    43: "91513daa1535ef9ead93dec13ba1a13762a7a7238015b24bc1a3fc0e6c06ed86",
    44: "b7cb3e3ca0cd08c14d0d74cddc18ff4a5e9d40f657978c43a24d8e75931ffa89",
    45: "46c023b291fbb66a069c6704714361dbc19a00486d71dfec48b5ad83b0a89c0a",
}


class PrepareError(RuntimeError):
    """A pinned input or frozen comparison assumption changed."""


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


def _assert_shared_surface(config: dict[str, Any]) -> None:
    if config["model"]["name_or_path"] != MODEL_ID:
        raise PrepareError("Pinned model id changed.")
    if config["model"]["revision"] != MODEL_REVISION:
        raise PrepareError("Pinned model revision changed.")
    if config["model"]["train_mode"] != "full":
        raise PrepareError("Comparison requires full-model update.")
    if config["train"]["optimizer"] != "adafactor":
        raise PrepareError("Comparison requires Adafactor.")
    if config["train"]["gradient_accumulation_offload"] != "cpu_accumulate":
        raise PrepareError("Comparison requires CPU gradient accumulation.")
    if int(config["train"]["gradient_accumulation_steps"]) != 8:
        raise PrepareError("Comparison requires eight microbatches per update.")
    if config["functional"]["task_objective"] != "choice_normalized":
        raise PrepareError("Comparison requires choice-normalized task CE.")
    if float(config["functional"]["full_vocab_loss_weight"]) != 0.0:
        raise PrepareError("Full-vocabulary loss must remain diagnostic-only.")
    if config["data"]["functional_elicitation"] != "symmetric_instruction":
        raise PrepareError("Comparison requires the qualified symmetric elicitation.")


def _common_train(config: dict[str, Any], *, seed: int, max_steps: int) -> None:
    train = config["train"]
    train["learning_rate"] = BASE_LEARNING_RATE
    train["workspace_learning_rate"] = WORKSPACE_LEARNING_RATE
    train["seed"] = seed
    train["max_steps"] = max_steps
    train["eval_at_start"] = True
    train["eval_every"] = 1 if max_steps == 4 else 4
    train["eval_batches"] = 0
    train["save_every"] = 0
    train["save_every_minutes"] = 0.0
    train["resume_from"] = "none"
    train["allow_schedule_extension"] = False
    train["save_optimizer"] = True


def make_o0(parent: dict[str, Any], *, seed: int, max_steps: int) -> dict[str, Any]:
    config = copy.deepcopy(parent)
    _common_train(config, seed=seed, max_steps=max_steps)
    stage = "stage4" if max_steps == 4 else "refinement16"
    config["train"]["output_dir"] = (
        f"../../../runs/v11/f1_o0_refinement/{stage}/O0_seed{seed}_step{max_steps}"
    )
    config["assays"]["amputation_eval"] = True
    config["assays"]["amputation_eval_every"] = 0
    config["assays"]["necessity"]["enabled"] = True
    return config


def make_f1(parent: dict[str, Any], *, seed: int) -> dict[str, Any]:
    config = copy.deepcopy(parent)
    _common_train(config, seed=seed, max_steps=16)
    config["train"]["output_dir"] = (
        f"../../../runs/v11/f1_o0_refinement/refinement16/F1_seed{seed}_step16"
    )
    config["assays"]["amputation_eval"] = False
    config["assays"]["amputation_eval_every"] = 0
    config["assays"]["necessity"]["enabled"] = False
    return config


def _artifact(path: Path, config: dict[str, Any], *, route: str, seed: int) -> dict[str, Any]:
    return {
        "route_id": route,
        "seed": seed,
        "path": f"conditions/{path.name}",
        "sha256": sha256_file(path),
        "output_dir": config["train"]["output_dir"],
        "base_learning_rate": float(config["train"]["learning_rate"]),
        "workspace_learning_rate": float(config["train"]["workspace_learning_rate"]),
        "max_steps": int(config["train"]["max_steps"]),
        "eval_every": int(config["train"]["eval_every"]),
    }


def prepare(repo_root: Path) -> dict[str, Any]:
    root = repo_root.expanduser().resolve()
    config_root = root / "configs" / "v11"
    condition_root = config_root / "conditions"
    o0_parent_path = condition_root / "config_O0_slots4_k1_symmetric_choice_repair.json"
    o0_parent = read_pinned(o0_parent_path, O0_PARENT_SHA256)
    _assert_shared_surface(o0_parent)
    if o0_parent["functional"]["route_mode"] != "deferred":
        raise PrepareError("O0 parent is not the deferred route.")
    if o0_parent["functional"]["memory_mode"] != "slots":
        raise PrepareError("O0 parent is not the four-slot route.")
    if int(o0_parent["functional"]["slot_count"]) != 4:
        raise PrepareError("O0 parent slot count changed.")
    if float(o0_parent["functional"]["injection_scale"]) != 1.0:
        raise PrepareError("O0 parent injection scale changed.")

    pinned = (
        (config_root / "SEED_ROBUSTNESS_CONTRACT.json", F1_CONTRACT_SHA256),
        (
            root
            / "provenance"
            / "pilots"
            / "v11_seed_robustness_new_seeds"
            / "SEED_ROBUSTNESS_RECEIPT.json",
            F1_RECEIPT_SHA256,
        ),
        (
            root
            / "provenance"
            / "pilots"
            / "v11_seed_robustness_new_seeds"
            / "GENERATION_BEHAVIOR.json",
            F1_BEHAVIOR_SHA256,
        ),
        (root / "configs" / "v10" / "behavior_prompt_suite_v1.json", PROMPT_SUITE_SHA256),
        (root / "data" / "v10" / "functional_train.jsonl", TRAIN_SHA256),
        (root / "data" / "v10" / "functional_eval.jsonl", EVAL_SHA256),
    )
    for path, digest in pinned:
        if sha256_file(path) != digest:
            raise PrepareError(f"Pinned comparison input changed: {path}")

    f1_parents: dict[int, dict[str, Any]] = {}
    for seed in SEEDS:
        path = condition_root / f"config_F1_seed_robustness_lr_1e_7_seed{seed}_step4.json"
        config = read_pinned(path, F1_CONFIG_HASHES[seed])
        _assert_shared_surface(config)
        if config["functional"]["route_mode"] != "inline":
            raise PrepareError(f"F1 seed {seed} is not inline.")
        if float(config["functional"]["injection_scale"]) != 0.0:
            raise PrepareError(f"F1 seed {seed} unexpectedly activates injection.")
        f1_parents[seed] = config

    stage4: dict[str, Any] = {}
    refinement: dict[str, Any] = {}
    for seed in SEEDS:
        o0_stage4 = make_o0(o0_parent, seed=seed, max_steps=4)
        o0_stage4_path = condition_root / f"config_O0_f1_contrast_seed{seed}_step4.json"
        atomic_write(o0_stage4_path, o0_stage4)
        stage4[f"O0_seed{seed}"] = _artifact(o0_stage4_path, o0_stage4, route="O0", seed=seed)

        f1_refinement = make_f1(f1_parents[seed], seed=seed)
        f1_refinement_path = condition_root / f"config_F1_refinement_seed{seed}_step16.json"
        atomic_write(f1_refinement_path, f1_refinement)
        refinement[f"F1_seed{seed}"] = _artifact(
            f1_refinement_path, f1_refinement, route="F1", seed=seed
        )

        o0_refinement = make_o0(o0_parent, seed=seed, max_steps=16)
        o0_refinement_path = condition_root / f"config_O0_refinement_seed{seed}_step16.json"
        atomic_write(o0_refinement_path, o0_refinement)
        refinement[f"O0_seed{seed}"] = _artifact(
            o0_refinement_path, o0_refinement, route="O0", seed=seed
        )

    contract = {
        "format": "latent-workspace-ft-v11-f1-o0-refinement-contract-v1",
        "schema_version": 1,
        "frozen_before_execution": True,
        "question": (
            "Does the active O0 four-slot deferred route provide a competitive or "
            "mechanistically distinct alternative to the robust 1e-7 F1 inline "
            "control at four updates and after an independent sixteen-update "
            "refinement horizon?"
        ),
        "parent_commit": PARENT_COMMIT,
        "model": {"name_or_path": MODEL_ID, "revision": MODEL_REVISION},
        "data": {
            "train": {"path": "../../data/v10/functional_train.jsonl", "sha256": TRAIN_SHA256},
            "eval": {"path": "../../data/v10/functional_eval.jsonl", "sha256": EVAL_SHA256},
        },
        "verified_f1_stage4_control": {
            "contract": {"path": "SEED_ROBUSTNESS_CONTRACT.json", "sha256": F1_CONTRACT_SHA256},
            "receipt": {
                "path": (
                    "../../provenance/pilots/v11_seed_robustness_new_seeds/"
                    "SEED_ROBUSTNESS_RECEIPT.json"
                ),
                "sha256": F1_RECEIPT_SHA256,
            },
            "behavior": {
                "path": (
                    "../../provenance/pilots/v11_seed_robustness_new_seeds/GENERATION_BEHAVIOR.json"
                ),
                "sha256": F1_BEHAVIOR_SHA256,
            },
            "selected_learning_rate": BASE_LEARNING_RATE,
            "seeds": list(SEEDS),
            "reuse_reason": (
                "The exact F1 cells are already receipt-verified; rerunning them under "
                "the same four-step horizon would add no independent evidence."
            ),
        },
        "treatment_difference": {
            "F1": {
                "functional_route_mode": "inline",
                "functional_memory_mode": "raw_sequence",
                "injection_scale": 0.0,
                "workspace_learning_rate": WORKSPACE_LEARNING_RATE,
            },
            "O0": {
                "functional_route_mode": "deferred",
                "functional_memory_mode": "slots",
                "slot_count": 4,
                "reader_steps": 1,
                "writer_steps": 1,
                "injection_scale": 1.0,
                "workspace_learning_rate": WORKSPACE_LEARNING_RATE,
            },
            "claim_boundary": (
                "Route topology, memory representation, and activation of the workspace "
                "injection path change together while both configured learning rates stay "
                "fixed; this is a system-level contrast, not a one-factor causal estimate "
                "of architecture alone."
            ),
        },
        "held_fixed": [
            "Mistral-7B model id, revision, BF16 storage, and full base update mode",
            "base learning rate 1e-7, Adafactor, weight decay, clipping, and scheduler family",
            "train/eval bytes and train-selected symmetric elicitation",
            "choice-normalized objective with zero full-vocabulary loss weight",
            "eight-microbatch cpu_accumulate transport and batch construction",
            "seed pairing at 43, 44, and 45",
            "complete 1,024-case eval and deterministic generation-veto suite",
        ],
        "stage4": {
            "purpose": "Compare O0 directly to the verified V11.0 four-update F1 control.",
            "condition_order": list(STAGE4_ORDER),
            "optimizer_steps": 4,
            "eval_every": 1,
            "artifacts": stage4,
            "behavior_capture": {
                "models": ["original", *STAGE4_ORDER],
                "capture_seed": 20260824,
                "max_new_tokens": 96,
            },
            "post_result_authority": {
                "refinement_execution_authorized_on_integrity_pass": True,
                "competitive_gate_pass_not_required_for_diagnostic_refinement": True,
                "reason": (
                    "The user explicitly authorized comparison through refinement; "
                    "the sixteen-step stage is diagnostic if O0 is not yet competitive."
                ),
            },
        },
        "refinement16": {
            "purpose": (
                "Run both routes from the pinned initial model under a fresh shared "
                "sixteen-step schedule; this is not a schedule extension from step 4."
            ),
            "condition_order": list(REFINEMENT_ORDER),
            "optimizer_steps": 16,
            "eval_every": 4,
            "artifacts": refinement,
            "schedule_note": (
                "cpu_accumulate forbids schedule-horizon extension on resume, so both "
                "routes restart from the pinned model with max_steps=16."
            ),
            "behavior_capture": {
                "models": ["original", *REFINEMENT_ORDER],
                "capture_seed": 20260825,
                "max_new_tokens": 96,
            },
            "necessity": {
                "routes": ["O0"],
                "required_seeds": list(SEEDS),
                "require_engineering_intervention_coverage": True,
                "record_ladder_levels": ["F0", "F1", "F2", "F3", "F4", "F5"],
                "content_specificity_requires": [
                    "F3_counterfactual_direction",
                    "F4_local_causal_specificity",
                ],
            },
        },
        "cell_gates": {
            "require_integrity_pass": True,
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
            "minimum_task_subset_accuracy": 0.75,
            "minimum_distinct_task_choices": 2,
            "maximum_single_token_run": 24,
            "maximum_top_token_fraction": 0.75,
        },
        "branch_robustness_gate": {
            "required_seeds": list(SEEDS),
            "require_every_cell_eligible": True,
            "minimum_passed_seed_fraction": 1.0,
        },
        "noninferiority_margins": {
            "behavior_task_accuracy": 0.03125,
            "complete_eval_accuracy": 0.02,
            "minimum_label_recall": 0.03,
        },
        "v12_decision_rules": [
            {
                "id": "scale_content_specific_o0",
                "when": "O0 is performance-competitive and content-specific necessity replicates.",
                "v12_focus": "scale and efficiency while preserving intervention receipts",
            },
            {
                "id": "sharpen_semantics",
                "when": "O0 is competitive but only carrier dependence replicates.",
                "v12_focus": "separate semantic content from nonzero carrier availability",
            },
            {
                "id": "stabilize_active_route",
                "when": "O0 shows content-specific effects but is not performance-competitive.",
                "v12_focus": "optimize ownership, warm start, gating, and LR curriculum",
            },
            {
                "id": "redesign_route",
                "when": (
                    "F1 is robust while O0 is neither competitive nor mechanistically specific."
                ),
                "v12_focus": "redesign injection and workspace training before scale-up",
            },
            {
                "id": "repair_shared_optimizer",
                "when": "neither F1 nor O0 is robust at sixteen steps.",
                "v12_focus": (
                    "repair shared long-horizon optimizer dynamics before architecture claims"
                ),
            },
        ],
        "execution_boundaries": {
            "retain_all_weights_until_behavior_and_necessity_capture": True,
            "no_14b_or_optimizer_sweep_authorized": True,
            "no_v12_training_execution_authorized": True,
            "v12_design_derivation_authorized": True,
        },
        "claim_boundary": (
            "This contract can compare two complete configured systems across three "
            "seeds at four and sixteen updates and can classify bounded mechanism "
            "evidence. It cannot isolate route topology from workspace optimization, "
            "establish broad capability improvement, or justify 14B/V12 execution."
        ),
    }
    contract_path = config_root / "F1_O0_REFINEMENT_CONTRACT.json"
    atomic_write(contract_path, contract)
    return {
        "contract": str(contract_path),
        "contract_sha256": sha256_file(contract_path),
        "stage4": stage4,
        "refinement16": refinement,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    print(json.dumps(prepare(parser.parse_args().repo_root), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
