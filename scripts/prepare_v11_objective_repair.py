#!/usr/bin/env python3
"""Compile the frozen v11.0 Gate-0 and objective-repair pilot configs."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

F1_SOURCE_SHA256 = "1d695f4301c00eb37f146f342f4b17b7ff22b8e1888ffa96f47ed3bb990d762c"
O0_SOURCE_SHA256 = "f177774e2184736ae5dd2293875a54765f278be643fc2900e9e3935630d77202"
TRAIN_SHA256 = "8ca42ca2908a3d554849b6fb0054f838c424fdfed48ca478bbac7174740feea3"
EVAL_SHA256 = "fcd7bdd3966cbcd0fd02315ee76c813aaf51b82f913abdd074f1585d5958386e"
MODEL_ID = "mistralai/Mistral-7B-Instruct-v0.3"
MODEL_REVISION = "c170c708c41dac9275d15a8fff4eca08d52bab71"


class PrepareError(RuntimeError):
    """The v10 parent or requested v11 output surface changed."""


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


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
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


def read_pinned_json(path: Path, expected_sha256: str) -> dict[str, Any]:
    if sha256_file(path) != expected_sha256:
        raise PrepareError(f"Pinned v10 parent changed: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PrepareError(f"Pinned v10 parent is not a JSON object: {path}")
    return value


def configure_pilot(
    source: dict[str, Any],
    *,
    output_dir: str,
    amputation_eval: bool,
) -> dict[str, Any]:
    config = copy.deepcopy(source)
    model = config["model"]
    functional = config["functional"]
    train = config["train"]
    assays = config["assays"]
    if model["name_or_path"] != MODEL_ID or model["revision"] != MODEL_REVISION:
        raise PrepareError("Pinned v10 model identity changed.")
    model["local_files_only"] = True
    model["trust_remote_code"] = False
    functional["task_objective"] = "choice_normalized"
    functional["full_vocab_loss_weight"] = 0.0
    train.update(
        {
            "base_activation_offload": "legacy_functional",
            "gradient_accumulation_offload": "cpu_accumulate",
            "gradient_accumulation_steps": 8,
            "max_steps": 16,
            "eval_at_start": True,
            "eval_every": 4,
            "eval_batches": 0,
            "save_every": 16,
            "save_every_minutes": 0.0,
            "save_best": False,
            "keep_last_checkpoints": 1,
            "output_dir": output_dir,
            "resume_from": "none",
        }
    )
    assays["amputation_eval"] = amputation_eval
    assays["amputation_eval_every"] = 0
    return config


def prepare(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.expanduser().resolve()
    v10 = repo_root / "configs" / "v10" / "conditions"
    train_path = repo_root / "data" / "v10" / "functional_train.jsonl"
    eval_path = repo_root / "data" / "v10" / "functional_eval.jsonl"
    if sha256_file(train_path) != TRAIN_SHA256 or sha256_file(eval_path) != EVAL_SHA256:
        raise PrepareError("Pinned v10 functional corpus changed.")
    f1_source = read_pinned_json(
        v10 / "config_F1_inline_upper.json", F1_SOURCE_SHA256
    )
    o0_source = read_pinned_json(v10 / "config_O0_slots4_k1.json", O0_SOURCE_SHA256)
    output_root = repo_root / "configs" / "v11"
    condition_root = output_root / "conditions"
    f1_path = condition_root / "config_F1_inline_choice_repair.json"
    o0_path = condition_root / "config_O0_slots4_k1_choice_repair.json"
    f1 = configure_pilot(
        f1_source,
        output_dir="../../../runs/v11/F1_inline_choice_repair_seed42_step16",
        amputation_eval=False,
    )
    o0 = configure_pilot(
        o0_source,
        output_dir="../../../runs/v11/O0_slots4_k1_choice_repair_seed42_step16",
        amputation_eval=True,
    )
    atomic_write_json(f1_path, f1)
    atomic_write_json(o0_path, o0)

    gate_contract = {
        "format": "latent-workspace-ft-v11-gate0-contract-v1",
        "schema_version": 1,
        "frozen_before_execution": True,
        "question": (
            "Does the pinned base model exceed chance on exact F1 inline and "
            "one-hop constrained evaluation before any update?"
        ),
        "model": {"name_or_path": MODEL_ID, "revision": MODEL_REVISION},
        "config": {
            "path": "conditions/config_F1_inline_choice_repair.json",
            "sha256": sha256_file(f1_path),
        },
        "dataset": {
            "path": "../../data/v10/functional_eval.jsonl",
            "sha256": EVAL_SHA256,
            "record_count": 64,
        },
        "elicitation": {
            "use_chat_template": False,
            "prompt_separator": "\n\n",
            "choices": [" no", " yes"],
        },
        "conditions": [
            {"id": "F0_query_only", "route_mode": "query_only"},
            {"id": "F1_inline", "route_mode": "inline"},
        ],
        "execution": {"max_batches": 0, "optimizer_steps": 0},
        "gates": {
            "wilson_z": 1.959963984540054,
            "minimum_f1_overall_wilson_lower_bound": 0.5,
            "minimum_f1_hop1_wilson_lower_bound": 0.5,
            "minimum_f1_minus_f0_accuracy": 0.05,
            "minimum_f1_label_recall": 0.55,
            "minimum_f1_distinct_predicted_classes": 2,
            "require_balanced_targets": True,
            "require_exact_direct_wrapper_logits": True,
            "require_exact_direct_wrapper_predictions": True,
        },
        "failure_action": (
            "Do not launch v11 training. Repair elicitation or wrapper parity, "
            "freeze a new contract, and rerun Gate-0."
        ),
    }
    gate_path = output_root / "GATE0_CONTRACT.json"
    atomic_write_json(gate_path, gate_contract)

    v11_contract = {
        "format": "latent-workspace-ft-v11-objective-repair-contract-v1",
        "schema_version": 1,
        "frozen_before_execution": True,
        "question": (
            "Did v10 collapse because full-vocabulary answer-token CE optimized "
            "token mass before the balanced no/yes decision?"
        ),
        "single_changed_mechanism": {
            "from": "functional.task_objective=full_vocab",
            "to": "functional.task_objective=choice_normalized",
            "full_vocab_loss_weight": 0.0,
        },
        "held_fixed": [
            "model identity and revision",
            "functional train/eval bytes",
            "raw prompt format and double-newline separator",
            "optimizer and learning rates",
            "gradient accumulation and cpu_accumulate transport",
            "gradient clipping policy",
            "F1 and O0 route definitions",
        ],
        "sequence": [
            "Gate-0 exact F0/F1 step-0 qualification",
            "F1 inline positive-control 16-step full update",
            "O0 active-route 16-step full update only if F1 passes",
            "behavior capture before any weight pruning",
        ],
        "f1_positive_control_gates": {
            "final_choice_loss_below_step0": True,
            "minimum_final_accuracy": 0.7,
            "minimum_final_label_recall": 0.6,
            "minimum_distinct_predicted_classes": 2,
            "forbid_nonfinite_or_constant_choice": True,
        },
        "o0_active_route_gates": {
            "launch_requires_f1_positive_control_pass": True,
            "final_choice_loss_below_step0": True,
            "minimum_final_accuracy": 0.6,
            "minimum_intact_minus_amputated_accuracy": 0.05,
            "minimum_final_label_recall": 0.55,
        },
        "configs": {
            "gate0": {
                "path": "GATE0_CONTRACT.json",
                "sha256": sha256_file(gate_path),
            },
            "F1_inline": {
                "path": "conditions/config_F1_inline_choice_repair.json",
                "sha256": sha256_file(f1_path),
            },
            "O0_slots4_k1": {
                "path": "conditions/config_O0_slots4_k1_choice_repair.json",
                "sha256": sha256_file(o0_path),
            },
        },
        "claim_boundary": (
            "Integrity PASS is not a scientific win. V11.0 tests only the "
            "objective-mismatch hypothesis on one seed and two bounded routes; "
            "it does not qualify the 57-run matrix or 14B scaling."
        ),
    }
    v11_path = output_root / "CONTRACT.json"
    atomic_write_json(v11_path, v11_contract)
    return {
        "gate0_contract": str(gate_path),
        "v11_contract": str(v11_path),
        "f1_config": str(f1_path),
        "o0_config": str(o0_path),
        "hashes": {
            "gate0_contract": sha256_file(gate_path),
            "v11_contract": sha256_file(v11_path),
            "f1_config": sha256_file(f1_path),
            "o0_config": sha256_file(o0_path),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    return parser


def main() -> None:
    result = prepare(build_parser().parse_args().repo_root)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
