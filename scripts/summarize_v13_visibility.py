#!/usr/bin/env python3
"""Summarize a completed V13 visibility trace without scientific qualification."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from v13_paired_metrics import summarize_pairs

FORMAT = "latent-workspace-v13-retained-inline-visibility-v1"
REQUIRED_MODES = (
    "intact",
    "zero",
    "fixed_carrier",
    "norm_matched_random",
    "counterfactual_twin",
    "hard_bypass",
)
VECTOR_FIELDS = (
    "logits",
    "bf16",
    "fp32",
    "direct_base_logits",
    "true_bypass_logits",
    "residual_precast",
    "residual_postcast",
    "bf16_ulp_up",
    "bf16_ulp_down",
    "residual_to_directional_bf16_ulp",
)
IDENTITY_FIELDS = (
    "sample_index",
    "family_id",
    "pair_id",
    "side",
    "query_index",
    "case_id",
    "input_sha256",
    "original_label",
    "donor_label",
    "affected",
    "heldout",
    "hop_distance",
    "candidate_ids",
    "answer_source_position",
)


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _finite_tree(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Nonfinite scalar in receipt")
    if isinstance(value, Mapping):
        for child in value.values():
            _finite_tree(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _finite_tree(child)


def _sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"Invalid SHA256: {label}")
    return value


def _vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"Expected two finite candidate scalars: {label}")
    if any(type(item) not in (int, float) for item in value):
        raise ValueError(f"Invalid candidate scalar: {label}")
    try:
        result = [float(item) for item in value]
    except OverflowError as exc:
        raise ValueError(f"Nonfinite candidate scalar: {label}") from exc
    if not all(math.isfinite(item) for item in result):
        raise ValueError(f"Nonfinite candidate scalar: {label}")
    return result


def _validated(receipt: Any) -> tuple[dict[str, dict[str, Any]], list[str], dict[str, str]]:
    if not isinstance(receipt, dict) or receipt.get("format") != FORMAT:
        raise ValueError("Unsupported visibility receipt")
    _finite_tree(receipt)
    if receipt.get("status") != "COMPLETE":
        raise ValueError("Receipt must be COMPLETE")
    for flag in ("checkpoint_bytes_unchanged", "parameters_unmodified"):
        if receipt.get(flag) is not True:
            raise ValueError(f"Required unchanged flag is not true: {flag}")
    for flag in ("training_performed", "gain_selection_performed"):
        if receipt.get(flag) is not False:
            raise ValueError(f"Diagnostic flag must be false: {flag}")
    if receipt.get("lane") != "retained_inline_diagnostic":
        raise ValueError("Only retained-inline diagnostic receipts are supported")
    hashes = {"receipt": "NOT_PROVIDED", "checkpoint_inventory": "NOT_PROVIDED"}
    if "receipt_sha256" in receipt:
        expected = _sha256(receipt["receipt_sha256"], "receipt_sha256")
        if (
            _hash({key: value for key, value in receipt.items() if key != "receipt_sha256"})
            != expected
        ):
            raise ValueError("Receipt self-hash mismatch")
        hashes["receipt"] = "VERIFIED_CONTENT_HASH"
    inventory_keys = ("checkpoint_inventory", "checkpoint_inventory_sha256")
    if any(key in receipt for key in inventory_keys):
        inventory = receipt.get("checkpoint_inventory")
        if not isinstance(inventory, list) or not inventory:
            raise ValueError("Checkpoint inventory must be nonempty")
        expected = _sha256(receipt.get("checkpoint_inventory_sha256"), inventory_keys[1])
        if _hash(inventory) != expected:
            raise ValueError("Checkpoint inventory hash mismatch")
        hashes["checkpoint_inventory"] = "VERIFIED_CONTENT_HASH"
    modes = receipt.get("modes")
    if (
        not isinstance(modes, list)
        or len(modes) != len(REQUIRED_MODES)
        or set(modes) != set(REQUIRED_MODES)
    ):
        raise ValueError("Exactly all required memory modes must be present")
    gains = receipt.get("gains")
    if (
        not isinstance(gains, list)
        or not gains
        or any(
            type(gain) not in (int, float) or not math.isfinite(gain) or gain <= 0 for gain in gains
        )
    ):
        raise ValueError("Finite positive diagnostic gains required")
    gain_keys = [format(gain, ".12g") for gain in gains]
    if len(set(gain_keys)) != len(gain_keys):
        raise ValueError("Duplicate diagnostic gain identity")
    rows = receipt.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Nonempty visibility rows required")
    indexed: dict[str, dict[str, Any]] = {mode: {} for mode in REQUIRED_MODES}
    for row in rows:
        if not isinstance(row, dict) or row.get("mode") not in indexed:
            raise ValueError("Invalid row or memory mode")
        for field in IDENTITY_FIELDS:
            if field not in row:
                raise ValueError(f"Missing row identity: {field}")
        for field in ("case_id", "family_id", "pair_id"):
            if not isinstance(row[field], str) or not row[field].strip():
                raise ValueError(f"Nonempty identity required: {field}")
        for field in ("sample_index", "query_index", "answer_source_position"):
            if type(row[field]) is not int or row[field] < 0:
                raise ValueError(f"Nonnegative integer required: {field}")
        if type(row["hop_distance"]) is not int:
            raise ValueError("Integer hop distance required")
        for field in ("side", "original_label", "donor_label"):
            if type(row[field]) is not int or row[field] not in (0, 1):
                raise ValueError(f"Binary integer required: {field}")
        if type(row["heldout"]) is not bool or type(row["affected"]) is not bool:
            raise ValueError("Boolean heldout/affected flags required")
        if row["affected"] != (row["original_label"] != row["donor_label"]):
            raise ValueError("Affected flag disagrees with labels")
        candidates = row["candidate_ids"]
        if (
            not isinstance(candidates, list)
            or len(candidates) != 2
            or any(type(value) is not int or value < 0 for value in candidates)
            or candidates[0] == candidates[1]
        ):
            raise ValueError("Two distinct candidate token IDs required")
        _sha256(row["input_sha256"], "input_sha256")
        for field in VECTOR_FIELDS:
            _vector(row.get(field), field)
        gain_logits = row.get("diagnostic_fp32_gain_logits")
        if not isinstance(gain_logits, dict) or set(gain_logits) != set(gain_keys):
            raise ValueError("Diagnostic gain coverage differs from receipt")
        for key, value in gain_logits.items():
            _vector(value, f"gain:{key}")
        mode, case = row["mode"], row["case_id"]
        if case in indexed[mode]:
            raise ValueError(f"Duplicate mode/case identity: {mode}/{case}")
        indexed[mode][case] = row
    intact = indexed["intact"]
    if not intact:
        raise ValueError("Intact cases must be nonempty")
    for mode, cases in indexed.items():
        if set(cases) != set(intact):
            raise ValueError(f"Case coverage mismatch: {mode}")
        for case, row in cases.items():
            for field in IDENTITY_FIELDS:
                if row[field] != intact[case][field]:
                    raise ValueError(f"Matched input/label identity differs: {mode}/{case}/{field}")
            if row["direct_base_logits"] != intact[case]["direct_base_logits"]:
                raise ValueError(f"Matched direct base differs: {mode}/{case}")
            if row["true_bypass_logits"] != intact[case]["true_bypass_logits"]:
                raise ValueError(f"Matched true bypass differs: {mode}/{case}")
    return indexed, gain_keys, hashes


def _variants(row: dict[str, Any], gains: list[str]) -> dict[str, list[float]]:
    return {
        "native": row["logits"],
        "explicit_bf16": row["bf16"],
        "fp32": row["fp32"],
        **{
            f"diagnostic_fp32_gain:{gain}": row["diagnostic_fp32_gain_logits"][gain]
            for gain in gains
        },
    }


def _pairs(indexed: dict[str, dict[str, Any]], gains: list[str]) -> list[dict[str, Any]]:
    pairs = []
    for mode, cases in indexed.items():
        for case, row in sorted(cases.items()):
            baseline = _variants(indexed["intact"][case], gains)
            for variant, logits in _variants(row, gains).items():
                pairs.append(
                    {
                        "original_world_family_id": row["family_id"],
                        "pair_id": row["pair_id"],
                        "query_id": f"side{row['side']}:query{row['query_index']}",
                        "original_label": row["original_label"],
                        "donor_label": row["donor_label"],
                        "intact_logits": baseline[variant],
                        "swapped_logits": logits,
                        "variant_id": variant,
                        "control_id": mode,
                    }
                )
    return pairs


def build_pair_rows(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    """Match each memory control to intact on the same input, labels and numeric variant."""
    indexed, gains, _ = _validated(receipt)
    return _pairs(indexed, gains)


def _effects(pairs: list[tuple[list[float], list[float]]]) -> dict[str, Any]:
    differences = [
        [float(right) - float(left) for left, right in zip(a, b, strict=True)] for a, b in pairs
    ]
    _finite_tree(differences)
    return {
        "row_count": len(pairs),
        "candidate_count": 2 * len(pairs),
        "changed_row_count": sum(any(value != 0 for value in row) for row in differences),
        "changed_candidate_count": sum(value != 0 for row in differences for value in row),
        "max_abs_candidate_delta": max(
            (abs(value) for row in differences for value in row), default=None
        ),
    }


def summarize_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    indexed, gains, hashes = _validated(receipt)
    summaries = []
    for mode, cases in indexed.items():
        rows = list(cases.values())
        summaries.append(
            {
                "mode": mode,
                "row_count": len(rows),
                "native_vs_direct_base": _effects(
                    [(row["direct_base_logits"], row["logits"]) for row in rows]
                ),
                "fp32_vs_direct_base": _effects(
                    [(row["direct_base_logits"], row["fp32"]) for row in rows]
                ),
                "precast_residual_nonzero_but_native_equals_base_rows": sum(
                    any(value != 0 for value in row["residual_precast"])
                    and row["logits"] == row["direct_base_logits"]
                    for row in rows
                ),
                "postcast_residual_nonzero_but_native_equals_base_rows": sum(
                    any(value != 0 for value in row["residual_postcast"])
                    and row["logits"] == row["direct_base_logits"]
                    for row in rows
                ),
                "max_abs_residual_precast": max(
                    abs(value) for row in rows for value in row["residual_precast"]
                ),
                "max_residual_to_directional_bf16_ulp": max(
                    value for row in rows for value in row["residual_to_directional_bf16_ulp"]
                ),
                "versus_matched_intact": {
                    variant: _effects(
                        [
                            (
                                _variants(indexed["intact"][case], gains)[variant],
                                _variants(row, gains)[variant],
                            )
                            for case, row in cases.items()
                        ]
                    )
                    for variant in _variants(rows[0], gains)
                },
            }
        )
    true_bypass = _effects(
        [
            (row["direct_base_logits"], row["true_bypass_logits"])
            for row in indexed["intact"].values()
        ]
    )
    result = {
        "format": "latent-workspace-v13-visibility-summary-v1",
        "status": "DESCRIPTIVE_ONLY",
        "source_status": receipt["status"],
        "source_hash_checks": hashes,
        "external_payloads_rehashed": False,
        "checkpoint": receipt.get("checkpoint"),
        "lane": receipt["lane"],
        "mode_summaries": summaries,
        "true_bypass_vs_direct_base": true_bypass,
        "control_meanings": {
            "zero": "Zero memory through the normal reader and adapter; not a true bypass.",
            "hard_bypass": (
                "Legacy reader hard bypass; adapter can retain a residual; not true amputation."
            ),
            "true_bypass": (
                "Captured bypass_workspace=True, compared with direct base separately "
                "from memory modes."
            ),
        },
        "paired_metrics": summarize_pairs(_pairs(indexed, gains)),
        "scientific_success": False,
        "execution_ready": False,
        "claim_boundary": (
            "Candidate-logit numerical visibility only. Numeric equality is not byte equality. "
            "No gain selection, content-specific causal success, task qualification, training, "
            "promotion or V14 bridge is established."
        ),
    }
    _finite_tree(result)
    return result


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON object key: {key}")
        result[key] = value
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace_json", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        source = args.trace_json.resolve()
        payload = source.read_bytes()
        receipt = json.loads(payload, object_pairs_hook=_unique_object)
        result = summarize_receipt(receipt)
        result["source_file"] = {"path": str(source), "sha256": hashlib.sha256(payload).hexdigest()}
        encoded = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
        print(
            json.dumps(
                {
                    "status": "DESCRIPTIVE_ONLY",
                    "output": str(args.output.resolve()),
                    "scientific_success": False,
                }
            )
        )
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(
            json.dumps({"status": "INPUT_ERROR", "error": str(exc), "scientific_success": False}),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
