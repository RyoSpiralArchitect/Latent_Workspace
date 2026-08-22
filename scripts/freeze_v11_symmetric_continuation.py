#!/usr/bin/env python3
"""Freeze configs after the train-only symmetric-elicitation selection."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

F1_SHA256 = "0006a47d43985cdfd31febc0c4a3f1424f72454cc1cc6da13cd4fe36ada0f60c"
O0_SHA256 = "8d8d73351f418c5e9d9f0cad78e2f4c4359c3dc0d8dd323cf69ba98a9eeab8ab"
ORIGINAL_GATE_SHA256 = (
    "985c9f4703220429626134240a7521b6947d80af0039949b945c4703d9a5627e"
)
CALIBRATION_SHA256 = (
    "f47878065a3c5f3c55ba9df3247069d55fef75bd3717c7cada3091acf5776da1"
)
SELECTED_STYLE = "symmetric_instruction"
INSTRUCTION = (
    "Use the world facts to decide whether the ranking statement is true. "
    "If it is false, answer no; if it is true, answer yes. "
    "Output exactly one lowercase word: no or yes."
)


class FreezeError(RuntimeError):
    """A selected input or parent contract changed before freezing."""


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
        raise FreezeError(f"Pinned continuation input changed: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FreezeError(f"Pinned continuation input is not an object: {path}")
    return value


def freeze(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.expanduser().resolve()
    config_root = repo_root / "configs" / "v11"
    condition_root = config_root / "conditions"
    calibration_path = (
        repo_root
        / "provenance"
        / "pilots"
        / "v11_elicitation_calibration"
        / "CALIBRATION_RECEIPT.json"
    )
    calibration = read_pinned(calibration_path, CALIBRATION_SHA256)
    if calibration.get("selection", {}).get("selected_style") != SELECTED_STYLE:
        raise FreezeError("Calibration did not select symmetric_instruction.")
    f1_parent = read_pinned(
        condition_root / "config_F1_inline_choice_repair.json", F1_SHA256
    )
    o0_parent = read_pinned(
        condition_root / "config_O0_slots4_k1_choice_repair.json", O0_SHA256
    )
    original_gate = read_pinned(
        config_root / "GATE0_CONTRACT.json", ORIGINAL_GATE_SHA256
    )

    f1 = copy.deepcopy(f1_parent)
    o0 = copy.deepcopy(o0_parent)
    f1["data"]["functional_elicitation"] = SELECTED_STYLE
    o0["data"]["functional_elicitation"] = SELECTED_STYLE
    f1["train"]["output_dir"] = (
        "../../../runs/v11/F1_inline_symmetric_choice_repair_seed42_step16"
    )
    o0["train"]["output_dir"] = (
        "../../../runs/v11/O0_slots4_k1_symmetric_choice_repair_seed42_step16"
    )
    f1_path = condition_root / "config_F1_inline_symmetric_choice_repair.json"
    o0_path = condition_root / "config_O0_slots4_k1_symmetric_choice_repair.json"
    atomic_write(f1_path, f1)
    atomic_write(o0_path, o0)

    gate = copy.deepcopy(original_gate)
    gate["question"] = (
        "Does the train-selected symmetric instruction qualify on the untouched "
        "eval corpus through exact F0/F1 wrapper paths?"
    )
    gate["config"] = {
        "path": "conditions/config_F1_inline_symmetric_choice_repair.json",
        "sha256": sha256_file(f1_path),
    }
    gate["elicitation"]["functional_elicitation"] = SELECTED_STYLE
    gate["elicitation"]["instruction"] = INSTRUCTION
    gate["parent_calibration"] = {
        "path": (
            "../../provenance/pilots/v11_elicitation_calibration/"
            "CALIBRATION_RECEIPT.json"
        ),
        "sha256": CALIBRATION_SHA256,
        "selected_style": SELECTED_STYLE,
    }
    gate["failure_action"] = (
        "Do not launch V11 training. Preserve this second blocked gate and "
        "revisit task or scoring design without another eval prompt search."
    )
    gate_path = config_root / "GATE0_SYMMETRIC_CONTRACT.json"
    atomic_write(gate_path, gate)

    continuation = {
        "format": "latent-workspace-ft-v11-gate0-continuation-contract-v1",
        "schema_version": 1,
        "frozen_before_eval_rerun": True,
        "trigger": {
            "blocked_gate_receipt": (
                "../../provenance/pilots/v11_gate0_attempt1/GATE0_RECEIPT.json"
            ),
            "failed_check": "f1_minimum_label_recall",
        },
        "calibration": {
            "path": (
                "../../provenance/pilots/v11_elicitation_calibration/"
                "CALIBRATION_RECEIPT.json"
            ),
            "sha256": CALIBRATION_SHA256,
            "selected_style": SELECTED_STYLE,
        },
        "single_prompt_change": {
            "from": "legacy",
            "to": SELECTED_STYLE,
            "instruction": INSTRUCTION,
            "dataset_bytes_changed": False,
            "choice_tokens_changed": False,
        },
        "next_sequence": [
            "Run GATE0_SYMMETRIC_CONTRACT.json once on eval.",
            "Launch F1 16-step objective repair only on Gate PASS.",
            "Launch O0 16-step active route only on F1 pilot PASS.",
            "Capture generation behavior before any pruning.",
        ],
        "artifacts": {
            "gate": {
                "path": "GATE0_SYMMETRIC_CONTRACT.json",
                "sha256": sha256_file(gate_path),
            },
            "F1_inline": {
                "path": "conditions/config_F1_inline_symmetric_choice_repair.json",
                "sha256": sha256_file(f1_path),
            },
            "O0_slots4_k1": {
                "path": "conditions/config_O0_slots4_k1_symmetric_choice_repair.json",
                "sha256": sha256_file(o0_path),
            },
        },
        "claim_boundary": (
            "The prompt was selected only on a frozen train subset. The next "
            "eval run is qualification, not training evidence; no further prompt "
            "selection on eval is permitted in this continuation."
        ),
    }
    continuation_path = config_root / "CONTINUATION_AFTER_GATE0_BLOCK.json"
    atomic_write(continuation_path, continuation)
    return {
        "gate": str(gate_path),
        "continuation": str(continuation_path),
        "f1": str(f1_path),
        "o0": str(o0_path),
        "hashes": {
            "gate": sha256_file(gate_path),
            "continuation": sha256_file(continuation_path),
            "f1": sha256_file(f1_path),
            "o0": sha256_file(o0_path),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    result = freeze(parser.parse_args().repo_root)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
