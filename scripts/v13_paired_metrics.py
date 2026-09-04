#!/usr/bin/env python3
"""Descriptive, family-aware V13 paired metrics; no scientific pass or promotion."""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


def _identifier(value: Any, field: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if type(value) is int:
        return str(value)
    raise ValueError(f"{field} must be a nonempty string or integer, not a boolean")


def _optional_identifier(row: Mapping[str, Any], name: str) -> str:
    key = f"{name}_id"
    if key not in row and name not in row:
        return "default"
    value = _identifier(row.get(key, row.get(name)), key)
    if key in row and name in row and _identifier(row[name], name) != value:
        raise ValueError(f"conflicting {name} and {key} identities")
    return value


def _fp32(value: float) -> float:
    try:
        result = struct.unpack("!f", struct.pack("!f", value))[0]
    except (OverflowError, struct.error) as exc:
        raise ValueError("NONFINITE_FP32_ARITHMETIC") from exc
    if not math.isfinite(result):
        raise ValueError("NONFINITE_FP32_ARITHMETIC")
    return result


def _logits(value: Any) -> tuple[list[float] | None, int | None, str | None]:
    if value is None:
        return None, None, "MISSING"
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None, None, "INVALID_LOGIT_SHAPE"
    if any(type(item) not in (int, float) for item in value):
        return None, None, "INVALID_LOGIT_VALUE"
    try:
        raw = [float(item) for item in value]
        if not all(math.isfinite(item) for item in raw):
            return None, None, "NONFINITE_LOGITS"
        rounded = [_fp32(item) for item in raw]
    except (OverflowError, ValueError):
        return None, None, "NONFINITE_FP32_LOGITS"
    if rounded[0] == rounded[1]:
        return rounded, None, "TIE_FP32"
    return rounded, int(rounded[1] > rounded[0]), None


def _difference(right: float, left: float) -> float:
    return _fp32(right - left)


def _prepare(row: Any, index: int) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise ValueError(f"row {index}: expected an object")
    result = {
        field: _identifier(row.get(field), f"row {index}.{field}")
        for field in ("original_world_family_id", "pair_id", "query_id")
    }
    result["variant_id"] = _optional_identifier(row, "variant")
    result["control_id"] = _optional_identifier(row, "control")
    for label in ("original_label", "donor_label"):
        if type(row.get(label)) is not int or row[label] not in (0, 1):
            raise ValueError(f"row {index}.{label}: expected the integer label 0 or 1")
        result[label] = row[label]
    result["affected"] = result["original_label"] != result["donor_label"]
    reasons: list[str] = []
    for side in ("intact", "swapped"):
        values, prediction, reason = _logits(row.get(f"{side}_logits"))
        result[f"{side}_logits"] = values
        result[f"{side}_prediction"] = prediction
        result[f"{side}_status"] = "OBSERVED" if reason is None else "UNKNOWN"
        if reason is not None:
            reasons.append(f"{side}:{reason}")
    result["donor_gain"] = None
    result["label1_minus_label0_shift"] = None
    # Ties obscure the categorical decision, not the finite continuous margin.
    continuous_reasons = [reason for reason in reasons if not reason.endswith(":TIE_FP32")]
    if not continuous_reasons:
        intact = result["intact_logits"]
        swapped = result["swapped_logits"]
        try:
            before = _difference(intact[1], intact[0])
            after = _difference(swapped[1], swapped[0])
            result["label1_minus_label0_shift"] = _difference(after, before)
            if result["affected"]:
                original = result["original_label"]
                donor = result["donor_label"]
                result["donor_gain"] = _difference(
                    _difference(swapped[donor], swapped[original]),
                    _difference(intact[donor], intact[original]),
                )
        except ValueError:
            result["label1_minus_label0_shift"] = None
            result["donor_gain"] = None
            continuous_reasons.append("pair:NONFINITE_FP32_ARITHMETIC")
    result["pair_status"] = "UNKNOWN" if reasons else "OBSERVED"
    result["unknown_reasons"] = reasons
    result["continuous_status"] = "UNKNOWN" if continuous_reasons else "OBSERVED"
    result["continuous_unknown_reasons"] = continuous_reasons
    return result


def _rate(count: int, denominator: int, unknown: int = 0) -> dict[str, Any]:
    """Unknown outcomes widen bounds, never enter the numerator as zero effects."""
    return {
        "count": count,
        "denominator": denominator,
        "unknown_outcomes": unknown,
        "rate": count / denominator if denominator and not unknown else None,
        "bounds": ([count / denominator, (count + unknown) / denominator] if denominator else None),
    }


def _distribution(values: list[float], unknown: int) -> dict[str, Any]:
    ordered = sorted(values)
    count = len(ordered)
    if count:
        middle = count // 2
        median = ordered[middle] if count % 2 else (ordered[middle - 1] + ordered[middle]) / 2
        # Input effects have already been rounded to FP32; descriptives use stable float64 sums.
        mean = math.fsum(value / count for value in ordered)
    else:
        mean = median = None
    return {
        "observed_count": count,
        "unknown_count": unknown,
        "values": values,
        "min": ordered[0] if count else None,
        "max": ordered[-1] if count else None,
        "mean": mean,
        "median": median,
        "positive_count": sum(value > 0.0 for value in values),
        "zero_count": sum(value == 0.0 for value in values),
        "negative_count": sum(value < 0.0 for value in values),
    }


def _subset(rows: list[dict[str, Any]], *, affected: bool) -> dict[str, Any]:
    selected = [row for row in rows if row["affected"] is affected]
    observed = [row for row in selected if row["pair_status"] == "OBSERVED"]
    unknown = len(selected) - len(observed)
    continuous_observed = [row for row in selected if row["continuous_status"] == "OBSERVED"]
    continuous_unknown = len(selected) - len(continuous_observed)
    unknown_intact = sum(row["intact_prediction"] is None for row in selected)
    unknown_swapped = sum(row["swapped_prediction"] is None for row in selected)
    intact_correct = sum(row["intact_prediction"] == row["original_label"] for row in selected)
    swapped_correct = sum(row["swapped_prediction"] == row["donor_label"] for row in selected)
    prediction_matrix = [[0, 0], [0, 0]]
    for row in observed:
        prediction_matrix[row["intact_prediction"]][row["swapped_prediction"]] += 1
    reason_counts = Counter(reason for row in selected for reason in row["unknown_reasons"])
    result: dict[str, Any] = {
        "row_count": len(selected),
        "observed_pair_count": len(observed),
        "unknown_pair_count": unknown,
        "continuous_observed_pair_count": len(continuous_observed),
        "continuous_unknown_pair_count": continuous_unknown,
        "continuous_unknown_reason_counts": dict(
            sorted(
                Counter(
                    reason for row in selected for reason in row["continuous_unknown_reasons"]
                ).items()
            )
        ),
        "measurement_status": (
            "EMPTY"
            if not selected
            else "UNKNOWN"
            if not observed
            else "PARTIAL_UNKNOWN"
            if unknown
            else "OBSERVED"
        ),
        "family_count": len({row["original_world_family_id"] for row in selected}),
        "observed_pair_family_count": len({row["original_world_family_id"] for row in observed}),
        "unknown_pair_family_count": len(
            {row["original_world_family_id"] for row in selected if row["pair_status"] == "UNKNOWN"}
        ),
        "unknown_reason_counts": dict(sorted(reason_counts.items())),
        "prediction_transition_matrix": prediction_matrix,
        "prediction_transition_axes": {"rows": "intact_label_0_1", "columns": "swapped_label_0_1"},
        "intact_original_accuracy": _rate(intact_correct, len(selected), unknown_intact),
        "swapped_donor_accuracy": _rate(swapped_correct, len(selected), unknown_swapped),
        "label1_minus_label0_shift": _distribution(
            [row["label1_minus_label0_shift"] for row in continuous_observed], continuous_unknown
        ),
    }
    if affected:
        transitions = {
            "original_to_original": 0,
            "original_to_donor": 0,
            "donor_to_original": 0,
            "donor_to_donor": 0,
        }
        for row in observed:
            before = "original" if row["intact_prediction"] == row["original_label"] else "donor"
            after = "donor" if row["swapped_prediction"] == row["donor_label"] else "original"
            transitions[f"{before}_to_{after}"] += 1
        desired = transitions["original_to_donor"]
        unresolved_eligible = sum(
            row["intact_prediction"] == row["original_label"] and row["pair_status"] == "UNKNOWN"
            for row in selected
        )
        conditional = _rate(desired, intact_correct, unresolved_eligible)
        conditional["denominator_status"] = "UNKNOWN" if unknown_intact else "OBSERVED"
        conditional["unknown_intact_count"] = unknown_intact
        if unknown_intact:
            # An unknown intact label makes the conditional denominator itself unknown.
            conditional["rate"] = None
            conditional["bounds"] = None
        result.update(
            {
                "transition_table": transitions,
                "transition_reference": (
                    "intact and swapped predictions relative to original/donor labels"
                ),
                "desired_flip_per_all_affected": _rate(desired, len(selected), unknown),
                "desired_flip_per_intact_correct": conditional,
                "desired_flip_per_observed_pairs": _rate(desired, len(observed)),
                "donor_gain": _distribution(
                    [row["donor_gain"] for row in continuous_observed], continuous_unknown
                ),
            }
        )
    else:
        transitions = {
            "correct_to_correct": 0,
            "correct_to_wrong": 0,
            "wrong_to_correct": 0,
            "wrong_to_wrong": 0,
        }
        for row in observed:
            before = "correct" if row["intact_prediction"] == row["original_label"] else "wrong"
            after = "correct" if row["swapped_prediction"] == row["original_label"] else "wrong"
            transitions[f"{before}_to_{after}"] += 1
        agreement = transitions["correct_to_correct"] + transitions["wrong_to_wrong"]
        result.update(
            {
                "transition_table": transitions,
                "prediction_agreement": _rate(agreement, len(selected), unknown),
                "correct_retention_per_all_unaffected": _rate(
                    transitions["correct_to_correct"], len(selected), unknown
                ),
                "correct_to_wrong_per_all_unaffected": _rate(
                    transitions["correct_to_wrong"], len(selected), unknown
                ),
                "wrong_to_correct_per_all_unaffected": _rate(
                    transitions["wrong_to_correct"], len(selected), unknown
                ),
                "agreement_is_correctness_or_causal_credit": False,
            }
        )
    return result


def summarize_pairs(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize paired binary logits, preserving UNKNOWN and variant/control separation.

    Required row fields: original_world_family_id, pair_id, query_id,
    original_label, donor_label, intact_logits and swapped_logits. Logits may
    be omitted/null to preserve missing measurements. Optional variant_id and
    control_id (or variant/control aliases) default to "default". Their IDs
    distinguish observations, not randomization units. Duplicate five-part
    identities and malformed structural fields raise ValueError.

    FP32 is applied to each candidate and subtraction before computing effects.
    Finite ties retain continuous effects but categorical predictions remain UNKNOWN;
    continuous arithmetic overflow does not erase otherwise observed predictions.
    No confidence interval, threshold, sufficiency, or causal pass is inferred.
    """
    if isinstance(rows, (Mapping, str, bytes)):
        raise ValueError("rows must be a nonempty iterable of paired observation objects")
    try:
        iterator = iter(rows)
    except TypeError as exc:
        raise ValueError("rows must be a nonempty iterable") from exc
    prepared = [_prepare(row, index) for index, row in enumerate(iterator)]
    if not prepared:
        raise ValueError("rows must be nonempty; empty measurements cannot support a summary")
    identities: set[tuple[str, ...]] = set()
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in prepared:
        identity = tuple(
            row[field]
            for field in (
                "original_world_family_id",
                "pair_id",
                "query_id",
                "variant_id",
                "control_id",
            )
        )
        if identity in identities:
            raise ValueError(f"duplicate observation identity: {identity!r}")
        identities.add(identity)
        groups[(row["variant_id"], row["control_id"])].append(row)
    group_results: list[dict[str, Any]] = []
    for (variant, control), group_rows in sorted(groups.items()):
        families: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in group_rows:
            families[row["original_world_family_id"]].append(row)
        group_results.append(
            {
                "variant_id": variant,
                "control_id": control,
                "row_count": len(group_rows),
                "family_count": len(families),
                "affected": _subset(group_rows, affected=True),
                "unaffected": _subset(group_rows, affected=False),
                "families": [
                    {
                        "original_world_family_id": family_id,
                        "row_count": len(family_rows),
                        "affected": _subset(family_rows, affected=True),
                        "unaffected": _subset(family_rows, affected=False),
                    }
                    for family_id, family_rows in sorted(families.items())
                ],
                "per_case": group_rows,
            }
        )
    return {
        "format": "latent-workspace-ft-v13-paired-metrics-v1",
        "status": "DESCRIPTIVE_ONLY",
        "row_count": len(prepared),
        "family_count": len({row["original_world_family_id"] for row in prepared}),
        "group_count": len(group_results),
        "groups": group_results,
        "uncertainty_unit": "ORIGINAL_WORLD_FAMILY_CLUSTER",
        "cross_group_effects_pooled": False,
        "arithmetic": "FP32_CANDIDATES_AND_SUBTRACTIONS_FLOAT64_DESCRIPTIVE_SUMMARIES",
        "execution_ready": False,
        "claim_boundary": (
            "Descriptive paired measurements only. Groups remain separate; family counts are "
            "not independent query counts. Missing, invalid or nonfinite measurements "
            "remain UNKNOWN. Tied predictions are UNKNOWN but finite continuous effects "
            "retain separate coverage. Donor accuracy, preserved wrong answers and a summary alone "
            "supply no causal credit, scientific pass, promotion or execution authorization. "
            "Matched content controls, sufficiency, heldout coverage and cluster uncertainty "
            "require separate checks."
        ),
    }


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        help="JSON array of rows; stdin if omitted. Reads only, writes JSON to stdout.",
    )
    args = parser.parse_args(argv)
    try:
        source = args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read()
        rows = json.loads(source, object_pairs_hook=_unique_object)
        result = summarize_pairs(rows)
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        print(
            json.dumps(
                {
                    "status": "INPUT_ERROR",
                    "execution_ready": False,
                    "error": f"{type(exc).__name__}: {exc}",
                },
                allow_nan=False,
            )
        )
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
