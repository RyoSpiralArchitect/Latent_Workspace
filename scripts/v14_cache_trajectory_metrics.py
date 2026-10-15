#!/usr/bin/env python3
"""Family-aware metrics for the frozen V14 cache-trajectory five-cell screen.

This module is deliberately model-free.  It validates already captured JSON rows and
summarizes a one-pulse trajectory.  It does not create interventions, run a model, or
turn a mechanical cache screen into evidence for a semantic direction.

One row represents one ``(family, probe, direction, horizon)`` observation.  The five
required cells are:

``A`` base with normal history carry;
``B`` intact one-pulse with history carry;
``C`` twin one-pulse with history carry;
``D`` intact one-pulse followed by matched no-pulse-history replacement; and
``E`` twin one-pulse followed by the same replacement.

Candidate logits are ordered by label (0, 1).  For affected probes, the signed donor
margin is ``logit[donor] - logit[original]`` and the cache-history contrast is
``(C - B) - (E - D)``.  Absolute magnitude alone is never a semantic pass criterion.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import struct
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

FORMAT = "latent-workspace-v14-cache-trajectory-metrics-v1"
BOOTSTRAP_DRAWS = 4096
BOOTSTRAP_SEED = 1414
CELL_NAMES = ("A", "B", "C", "D", "E")
DIRECTION_KINDS = ("semantic", "equal_norm_random", "sham", "unrelated")
CELL_PROTOCOL = {
    "A": {
        "intervention_kind": "base",
        "pulse_count": 0,
        "forcing_mode": "none",
        "history_mode": "carry",
    },
    "B": {
        "intervention_kind": "intact",
        "pulse_count": 1,
        "forcing_mode": "one_pulse",
        "history_mode": "carry",
    },
    "C": {
        "intervention_kind": "twin",
        "pulse_count": 1,
        "forcing_mode": "one_pulse",
        "history_mode": "carry",
    },
    "D": {
        "intervention_kind": "intact",
        "pulse_count": 1,
        "forcing_mode": "one_pulse",
        "history_mode": "matched_no_pulse_history_replacement",
    },
    "E": {
        "intervention_kind": "twin",
        "pulse_count": 1,
        "forcing_mode": "one_pulse",
        "history_mode": "matched_no_pulse_history_replacement",
    },
}


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value.strip()


def _integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{field} must be an integer >= {minimum}, not a boolean")
    return value


def _fp32(value: Any) -> float | None:
    if type(value) not in (int, float):
        return None
    try:
        result = struct.unpack("!f", struct.pack("!f", float(value)))[0]
    except (OverflowError, struct.error, ValueError):
        return None
    return result if math.isfinite(result) else None


def _fp32_subtract(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return _fp32(left - right)


def _fp32_add(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return _fp32(left + right)


def _sequence(value: Any, field: str, *, binary: bool = False) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError(f"{field} must be a nonempty integer sequence")
    result = []
    for item in value:
        if type(item) is not int or item < 0 or (binary and item not in (0, 1)):
            suffix = " of 0/1 values" if binary else " of nonnegative values"
            raise ValueError(f"{field} must be an integer sequence{suffix}")
        result.append(item)
    return tuple(result)


def _logits(value: Any) -> dict[str, Any]:
    reason = None
    logits = None
    if value is None:
        reason = "MISSING"
    elif not isinstance(value, (list, tuple)) or len(value) != 2:
        reason = "INVALID_SHAPE"
    else:
        logits = [_fp32(item) for item in value]
        if any(item is None for item in logits):
            logits = None
            reason = "NONFINITE_OR_INVALID_FP32"
    prediction = None
    if logits is not None:
        if logits[0] == logits[1]:
            reason = "TIE_FP32"
        else:
            prediction = int(logits[1] > logits[0])
    return {
        "values": logits,
        "prediction": prediction,
        "categorical_status": "OBSERVED" if prediction is not None else "UNKNOWN",
        "categorical_unknown_reason": reason,
        # A finite tie retains a continuous margin of zero.
        "continuous_status": "OBSERVED" if logits is not None else "UNKNOWN",
    }


def _finite_measurement(value: Any) -> dict[str, Any]:
    result = _fp32(value)
    reason = None if result is not None else "MISSING_OR_NONFINITE"
    if result is not None and result < 0.0:
        result = None
        reason = "NEGATIVE_DISPLACEMENT"
    return {
        "value": result,
        "status": "OBSERVED" if result is not None else "UNKNOWN",
        "reason": reason,
    }


def _parse_direction(value: Any, row_index: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"row {row_index}.direction must be an object")
    kind = _identifier(value.get("kind"), f"row {row_index}.direction.kind")
    if kind not in DIRECTION_KINDS:
        raise ValueError(f"row {row_index}.direction.kind is not supported: {kind}")
    direction_id = _identifier(value.get("direction_id"), f"row {row_index}.direction.direction_id")
    pulse_norm = _fp32(value.get("pulse_norm"))
    reference_norm = _fp32(value.get("reference_norm"))
    tolerance = _fp32(value.get("equal_norm_tolerance"))
    if pulse_norm is None or pulse_norm < 0.0:
        raise ValueError(f"row {row_index}.direction.pulse_norm must be finite and nonnegative")
    if reference_norm is None or reference_norm <= 0.0:
        raise ValueError(f"row {row_index}.direction.reference_norm must be finite and positive")
    if tolerance is None or tolerance < 0.0:
        raise ValueError(
            f"row {row_index}.direction.equal_norm_tolerance must be finite and nonnegative"
        )
    verified = value.get("equal_norm_verified")
    if type(verified) is not bool:
        raise ValueError(f"row {row_index}.direction.equal_norm_verified must be boolean")
    allowed_error = tolerance * max(1.0, abs(reference_norm))
    if kind == "sham":
        norm_valid = pulse_norm == 0.0 and not verified
        norm_status = "SHAM_ZERO" if norm_valid else "INVALID_SHAM_NORM_METADATA"
    else:
        norm_valid = verified and abs(pulse_norm - reference_norm) <= allowed_error
        norm_status = "MATCHED" if norm_valid else "INVALID_EQUAL_NORM_METADATA"
    return {
        "kind": kind,
        "direction_id": direction_id,
        "pulse_norm": pulse_norm,
        "reference_norm": reference_norm,
        "equal_norm_tolerance": tolerance,
        "equal_norm_verified": verified,
        "norm_metadata_valid": norm_valid,
        "norm_status": norm_status,
    }


def _parse_cell(name: str, value: Any, row_index: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"row {row_index}.cells.{name} must be an object")
    expected = CELL_PROTOCOL[name]
    protocol = {
        "intervention_kind": value.get("intervention_kind"),
        "pulse_count": value.get("pulse_count"),
        "forcing_mode": value.get("forcing_mode"),
        "history_mode": value.get("history_mode"),
    }
    protocol_errors = [
        f"{field}:expected={expected_value!r}:observed={protocol[field]!r}"
        for field, expected_value in expected.items()
        if protocol[field] != expected_value
    ]
    if type(protocol["pulse_count"]) is not int:
        protocol_errors.append("pulse_count:must_be_integer_not_boolean")
    cell = {
        **protocol,
        "protocol_errors": sorted(set(protocol_errors)),
        "candidate_logits": _logits(value.get("candidate_logits")),
        "token_ids": _sequence(value.get("token_ids"), f"row {row_index}.cells.{name}.token_ids"),
        "position_ids": _sequence(
            value.get("position_ids"), f"row {row_index}.cells.{name}.position_ids"
        ),
        "attention_mask": _sequence(
            value.get("attention_mask"),
            f"row {row_index}.cells.{name}.attention_mask",
            binary=True,
        ),
        "state_displacement": _finite_measurement(value.get("state_displacement")),
        "kv_displacement": _finite_measurement(value.get("kv_displacement")),
    }
    lengths = {len(cell[name]) for name in ("token_ids", "position_ids", "attention_mask")}
    if len(lengths) != 1:
        cell["protocol_errors"].append("token_position_mask_length_mismatch")
    return cell


def _margin(logits: list[float] | None, positive: int, negative: int) -> float | None:
    if logits is None:
        return None
    return _fp32_subtract(logits[positive], logits[negative])


def _prepare(row: Any, index: int) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise ValueError(f"row {index} must be an object")
    result = {
        name: _identifier(row.get(name), f"row {index}.{name}")
        for name in ("family_id", "probe_id", "query_id")
    }
    result["horizon"] = _integer(row.get("horizon"), f"row {index}.horizon")
    for name in ("original_label", "donor_label"):
        value = row.get(name)
        if type(value) is not int or value not in (0, 1):
            raise ValueError(f"row {index}.{name} must be integer 0 or 1, not boolean")
        result[name] = value
    affected = row.get("affected")
    if type(affected) is not bool:
        raise ValueError(f"row {index}.affected must be boolean")
    if affected != (result["original_label"] != result["donor_label"]):
        raise ValueError(f"row {index}.affected disagrees with original/donor labels")
    result["affected"] = affected
    result["query_token_ids"] = _sequence(
        row.get("query_token_ids"), f"row {index}.query_token_ids"
    )
    result["probe_token_ids"] = _sequence(
        row.get("probe_token_ids"), f"row {index}.probe_token_ids"
    )
    result["pulse_horizon"] = _integer(
        row.get("pulse_horizon"), f"row {index}.pulse_horizon"
    )
    if type(row.get("fixed_continuation")) is not bool:
        raise ValueError(f"row {index}.fixed_continuation must be boolean")
    result["fixed_continuation"] = row["fixed_continuation"]
    if type(row.get("probe_is_read_only")) is not bool:
        raise ValueError(f"row {index}.probe_is_read_only must be boolean")
    result["probe_is_read_only"] = row["probe_is_read_only"]
    result["direction"] = _parse_direction(row.get("direction"), index)
    cells = row.get("cells")
    if not isinstance(cells, Mapping) or set(cells) != set(CELL_NAMES):
        raise ValueError(f"row {index}.cells must contain exactly A, B, C, D, E")
    result["cells"] = {name: _parse_cell(name, cells[name], index) for name in CELL_NAMES}

    reference = result["cells"]["A"]
    identity_errors = []
    for name in CELL_NAMES[1:]:
        cell = result["cells"][name]
        for field in ("token_ids", "position_ids", "attention_mask"):
            if cell[field] != reference[field]:
                identity_errors.append(f"{name}:{field}:differs_from_A")
    result["protocol_errors"] = sorted(
        error
        for name, cell in result["cells"].items()
        for error in (f"{name}:{item}" for item in cell["protocol_errors"])
    )
    result["protocol_errors"].extend(identity_errors)
    if not result["fixed_continuation"]:
        result["protocol_errors"].append("fixed_continuation:false")
    if not result["probe_is_read_only"]:
        result["protocol_errors"].append("probe_is_read_only:false")
    if result["pulse_horizon"] > result["horizon"]:
        result["protocol_errors"].append("pulse_horizon:after_measurement_horizon")
    if not result["direction"]["norm_metadata_valid"]:
        result["protocol_errors"].append(result["direction"]["norm_status"])
    result["protocol_errors"] = sorted(set(result["protocol_errors"]))

    for name, cell in result["cells"].items():
        logits = cell["candidate_logits"]["values"]
        cell["label1_margin"] = _margin(logits, 1, 0)
        cell["donor_margin"] = (
            _margin(logits, result["donor_label"], result["original_label"])
            if affected
            else None
        )
        prediction = cell["candidate_logits"]["prediction"]
        cell["original_correct"] = (
            None if prediction is None else prediction == result["original_label"]
        )

    margin_name = "donor_margin" if affected else "label1_margin"
    b, c, d, e = (result["cells"][name][margin_name] for name in ("B", "C", "D", "E"))
    carry_delta = _fp32_subtract(c, b)
    replacement_delta = _fp32_subtract(e, d)
    result["carry_delta"] = carry_delta
    result["replacement_delta"] = replacement_delta
    result["central_contrast"] = _fp32_subtract(carry_delta, replacement_delta)
    result["central_contrast_kind"] = (
        "SIGNED_DONOR" if affected else "NONDIRECTIONAL_LABEL1_DIAGNOSTIC"
    )

    if not affected:
        predictions = {
            name: result["cells"][name]["candidate_logits"]["prediction"] for name in CELL_NAMES
        }
        result["unaffected_retention"] = {
            "carry_intact_twin_agree": (
                None
                if predictions["B"] is None or predictions["C"] is None
                else predictions["B"] == predictions["C"]
            ),
            "replacement_intact_twin_agree": (
                None
                if predictions["D"] is None or predictions["E"] is None
                else predictions["D"] == predictions["E"]
            ),
            "all_interventions_match_base": (
                None
                if any(value is None for value in predictions.values())
                else all(predictions[name] == predictions["A"] for name in CELL_NAMES[1:])
            ),
        }
    else:
        result["unaffected_retention"] = None
    return result


def _quantile(sorted_values: list[float], fraction: float) -> float:
    position = (len(sorted_values) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (position - low)


def _distribution(values: Iterable[float | None]) -> dict[str, Any]:
    materialized = list(values)
    observed = sorted(value for value in materialized if value is not None)
    return {
        "observed_count": len(observed),
        "unknown_count": len(materialized) - len(observed),
        "mean": math.fsum(observed) / len(observed) if observed else None,
        "min": observed[0] if observed else None,
        "max": observed[-1] if observed else None,
        "positive_count": sum(value > 0.0 for value in observed),
        "zero_count": sum(value == 0.0 for value in observed),
        "negative_count": sum(value < 0.0 for value in observed),
    }


def _family_interval(
    values: Mapping[str, Sequence[float | None]],
    *,
    coverage_complete: bool,
    expected_families: int,
) -> dict[str, Any]:
    family_values: dict[str, float] = {}
    unknown_families = []
    for family, observations in sorted(values.items()):
        if not observations or any(value is None for value in observations):
            unknown_families.append(family)
        else:
            finite = [value for value in observations if value is not None]
            family_values[family] = math.fsum(finite) / len(finite)
    if (
        not coverage_complete
        or unknown_families
        or len(values) != expected_families
        or len(family_values) != expected_families
    ):
        return {
            "status": "UNKNOWN_INCOMPLETE_FAMILY_COVERAGE",
            "value": None,
            "ci95": None,
            "observed_family_count": len(family_values),
            "unknown_family_count": len(unknown_families),
            "family_values": family_values,
        }
    ordered = [family_values[name] for name in sorted(family_values)]
    count = len(ordered)
    value = math.fsum(ordered) / count
    rng = random.Random(BOOTSTRAP_SEED)
    draws = []
    for _ in range(BOOTSTRAP_DRAWS):
        sample = [ordered[rng.randrange(count)] for _ in range(count)]
        draws.append(math.fsum(sample) / count)
    draws.sort()
    return {
        "status": "OBSERVED",
        "value": value,
        "ci95": [_quantile(draws, 0.025), _quantile(draws, 0.975)],
        "observed_family_count": count,
        "unknown_family_count": 0,
        "family_values": family_values,
    }


def _trajectory(
    rows: list[dict[str, Any]], floor: float, expected_horizons: tuple[int, ...]
) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: row["horizon"])
    points = [
        {
            "horizon": row["horizon"],
            "carry_delta": row["carry_delta"],
            "replacement_delta": row["replacement_delta"],
            "central_contrast": row["central_contrast"],
            "central_contrast_kind": row["central_contrast_kind"],
            "cells": {
                name: {
                    "candidate_logits": row["cells"][name]["candidate_logits"]["values"],
                    "prediction": row["cells"][name]["candidate_logits"]["prediction"],
                    "categorical_status": row["cells"][name]["candidate_logits"][
                        "categorical_status"
                    ],
                    "categorical_unknown_reason": row["cells"][name]["candidate_logits"][
                        "categorical_unknown_reason"
                    ],
                    "donor_margin": row["cells"][name]["donor_margin"],
                    "label1_margin": row["cells"][name]["label1_margin"],
                    "state_displacement": row["cells"][name]["state_displacement"]["value"],
                    "kv_displacement": row["cells"][name]["kv_displacement"]["value"],
                }
                for name in CELL_NAMES
            },
        }
        for row in ordered
    ]
    auc = 0.0
    auc_status = "OBSERVED"
    if (
        len(points) < 2
        or tuple(point["horizon"] for point in points) != expected_horizons
        or any(point["central_contrast"] is None for point in points)
    ):
        auc_value = None
        auc_status = "UNKNOWN_INCOMPLETE_TRAJECTORY"
    else:
        for left, right in zip(points[:-1], points[1:], strict=True):
            width = right["horizon"] - left["horizon"]
            if width <= 0:
                raise ValueError("trajectory horizons must be strictly increasing")
            term = width * (left["central_contrast"] + right["central_contrast"]) / 2.0
            auc += term
        auc_value = _fp32(auc)
        if auc_value is None:
            auc_status = "UNKNOWN_NONFINITE_FP32_AUC"
    ratios = []
    for left, right in zip(points[:-1], points[1:], strict=True):
        denominator = left["central_contrast"]
        numerator = right["central_contrast"]
        if denominator is None or numerator is None:
            ratios.append(
                {
                    "from_horizon": left["horizon"],
                    "to_horizon": right["horizon"],
                    "value": None,
                    "status": "UNKNOWN_MISSING_OR_NONFINITE",
                }
            )
        elif abs(denominator) < floor:
            ratios.append(
                {
                    "from_horizon": left["horizon"],
                    "to_horizon": right["horizon"],
                    "value": None,
                    "status": "UNKNOWN_BELOW_FROZEN_FLOOR",
                }
            )
        else:
            ratios.append(
                {
                    "from_horizon": left["horizon"],
                    "to_horizon": right["horizon"],
                    "value": abs(numerator) / abs(denominator),
                    "status": "SECONDARY_DESCRIPTIVE",
                    "signed_direction_preserved": numerator == 0.0
                    or (numerator > 0.0) == (denominator > 0.0),
                }
            )
    return {
        "points": points,
        "signed_trapezoid_auc": auc_value,
        "signed_trapezoid_auc_status": auc_status,
        "amplification_ratios": ratios,
        "amplification_ratios_are_secondary": True,
        "absolute_magnitude_is_semantic_qualification": False,
    }


def _retention(
    rows: list[dict[str, Any]], *, coverage_complete: bool, expected_families: int
) -> dict[str, Any]:
    unaffected = [row for row in rows if not row["affected"]]
    result: dict[str, Any] = {"row_count": len(unaffected), "checks": {}}
    for name in (
        "carry_intact_twin_agree",
        "replacement_intact_twin_agree",
        "all_interventions_match_base",
    ):
        values = [row["unaffected_retention"][name] for row in unaffected]
        known = [value for value in values if value is not None]
        by_family: dict[str, list[float | None]] = defaultdict(list)
        for row in unaffected:
            value = row["unaffected_retention"][name]
            by_family[row["family_id"]].append(None if value is None else float(value))
        result["checks"][name] = {
            "agree_count": sum(value is True for value in values),
            "denominator": len(values),
            "unknown_count": len(values) - len(known),
            "value": (
                sum(value is True for value in values) / len(values)
                if values and len(known) == len(values)
                else None
            ),
            "family_cluster": _family_interval(
                by_family,
                coverage_complete=coverage_complete and bool(values),
                expected_families=expected_families,
            ),
        }
    return result


def _cross_direction_differences(
    trajectories: list[dict[str, Any]], *, coverage_complete: bool, expected_families: int
) -> dict[str, Any]:
    indexed = {
        (item["family_id"], item["probe_id"], item["direction_kind"]): item
        for item in trajectories
    }
    semantic_keys = sorted(
        (family, probe)
        for family, probe, kind in indexed
        if kind == "semantic" and indexed[(family, probe, kind)]["affected"]
    )
    result = {}
    for control in ("equal_norm_random", "sham", "unrelated"):
        endpoint_by_family: dict[str, list[float | None]] = defaultdict(list)
        auc_by_family: dict[str, list[float | None]] = defaultdict(list)
        pair_count = 0
        for family, probe in semantic_keys:
            semantic = indexed[(family, probe, "semantic")]
            other = indexed.get((family, probe, control))
            if other is None:
                endpoint_by_family[family].append(None)
                auc_by_family[family].append(None)
                continue
            pair_count += 1
            endpoint_by_family[family].append(
                _fp32_subtract(semantic["endpoint"], other["endpoint"])
            )
            auc_by_family[family].append(
                _fp32_subtract(semantic["signed_auc"], other["signed_auc"])
            )
        result[control] = {
            "paired_affected_trajectory_count": pair_count,
            "semantic_minus_control_endpoint": _family_interval(
                endpoint_by_family,
                coverage_complete=coverage_complete and bool(semantic_keys),
                expected_families=expected_families,
            ),
            "semantic_minus_control_signed_auc": _family_interval(
                auc_by_family,
                coverage_complete=coverage_complete and bool(semantic_keys),
                expected_families=expected_families,
            ),
        }
    return result


def summarize(
    rows: Iterable[Mapping[str, Any]],
    *,
    expected_horizons: Sequence[int],
    endpoint_horizon: int,
    frozen_floor: float,
    expected_families: int = 1,
    expected_probes_per_family: int = 1,
    expected_direction_kinds: Sequence[str] = ("equal_norm_random", "sham"),
) -> dict[str, Any]:
    """Validate and summarize frozen five-cell trajectory rows.

    Missing/nonfinite measurements stay UNKNOWN.  Malformed structural identities raise
    ``ValueError`` because they cannot identify a matched comparison.  Entirely absent
    rows remain in the explicit expected denominator supplied by the caller.
    """
    if isinstance(rows, (str, bytes, Mapping)):
        raise ValueError("rows must be an iterable of objects")
    horizons = tuple(expected_horizons)
    if not horizons or any(type(value) is not int or value < 0 for value in horizons):
        raise ValueError("expected_horizons must be a nonempty sequence of nonnegative integers")
    if tuple(sorted(set(horizons))) != horizons:
        raise ValueError("expected_horizons must be strictly increasing and unique")
    if type(endpoint_horizon) is not int or endpoint_horizon not in horizons:
        raise ValueError("endpoint_horizon must be a member of expected_horizons")
    floor = _fp32(frozen_floor)
    if floor is None or floor <= 0.0:
        raise ValueError("frozen_floor must be finite and positive")
    for name, value in (
        ("expected_families", expected_families),
        ("expected_probes_per_family", expected_probes_per_family),
    ):
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    directions = tuple(expected_direction_kinds)
    if not directions or len(directions) != len(set(directions)):
        raise ValueError("expected_direction_kinds must be nonempty and unique")
    if any(value not in DIRECTION_KINDS for value in directions):
        raise ValueError("expected_direction_kinds contains an unsupported direction")

    prepared = [_prepare(row, index) for index, row in enumerate(rows)]
    identities = set()
    for row in prepared:
        identity = (
            row["family_id"],
            row["probe_id"],
            row["direction"]["kind"],
            row["horizon"],
        )
        if identity in identities:
            raise ValueError(f"duplicate trajectory row: {identity}")
        identities.add(identity)
        if row["horizon"] not in horizons:
            raise ValueError(f"observed horizon outside frozen plan: {row['horizon']}")
        if row["direction"]["kind"] not in directions:
            raise ValueError(
                f"observed direction outside frozen plan: {row['direction']['kind']}"
            )

    # Query/probe and direction identities are invariant over horizons.  Tokenized full
    # histories may grow over horizons, but matched cells and directions at one horizon
    # must see exactly the same tokens, positions, and masks.
    trajectory_metadata: dict[tuple[str, str, str], tuple[Any, ...]] = {}
    probe_metadata: dict[tuple[str, str], tuple[Any, ...]] = {}
    matched_history: dict[tuple[str, str, int], tuple[Any, ...]] = {}
    for row in prepared:
        trajectory_key = (row["family_id"], row["probe_id"], row["direction"]["kind"])
        metadata = (
            row["query_id"],
            row["query_token_ids"],
            row["probe_token_ids"],
            row["pulse_horizon"],
            row["direction"]["direction_id"],
            row["direction"]["pulse_norm"],
            row["direction"]["reference_norm"],
            row["direction"]["equal_norm_tolerance"],
            row["direction"]["equal_norm_verified"],
            row["original_label"],
            row["donor_label"],
            row["affected"],
        )
        prior = trajectory_metadata.setdefault(trajectory_key, metadata)
        if metadata != prior:
            row["protocol_errors"].append("query_probe_direction_metadata_changed_across_horizons")
        shared_probe_metadata = (
            row["query_id"],
            row["query_token_ids"],
            row["probe_token_ids"],
            row["pulse_horizon"],
            row["original_label"],
            row["donor_label"],
            row["affected"],
        )
        prior_probe_metadata = probe_metadata.setdefault(
            (row["family_id"], row["probe_id"]), shared_probe_metadata
        )
        if shared_probe_metadata != prior_probe_metadata:
            row["protocol_errors"].append("query_probe_metadata_changed_across_directions")
        matched_key = (row["family_id"], row["probe_id"], row["horizon"])
        history = tuple(
            row["cells"]["A"][field] for field in ("token_ids", "position_ids", "attention_mask")
        )
        prior_history = matched_history.setdefault(matched_key, history)
        if history != prior_history:
            row["protocol_errors"].append("matched_history_changed_across_directions")
        row["protocol_errors"] = sorted(set(row["protocol_errors"]))

    direction_groups: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in prepared:
        direction_groups[(row["family_id"], row["probe_id"], row["horizon"])].append(row)
    for selected in direction_groups.values():
        non_sham = [row for row in selected if row["direction"]["kind"] != "sham"]
        reference_row = (
            min(
                non_sham,
                key=lambda row: (
                    row["direction"]["kind"] != "semantic",
                    row["direction"]["kind"],
                ),
            )
            if non_sham
            else None
        )
        reference = reference_row["direction"]["pulse_norm"] if reference_row else None
        if reference is None:
            continue
        for row in selected:
            direction = row["direction"]
            tolerance = direction["equal_norm_tolerance"] * max(1.0, abs(reference))
            if abs(direction["reference_norm"] - reference) > tolerance:
                row["protocol_errors"].append("reference_norm_not_matched_across_directions")
            if direction["kind"] != "sham" and abs(direction["pulse_norm"] - reference) > tolerance:
                row["protocol_errors"].append("pulse_norm_not_matched_across_directions")
            row["protocol_errors"] = sorted(set(row["protocol_errors"]))

    observed_families = sorted({row["family_id"] for row in prepared})
    observed_probes = {(row["family_id"], row["probe_id"]) for row in prepared}
    expected_rows = (
        expected_families * expected_probes_per_family * len(horizons) * len(directions)
    )
    observed_rows = len(prepared)
    if (
        observed_rows > expected_rows
        or len(observed_families) > expected_families
        or len(observed_probes) > expected_families * expected_probes_per_family
    ):
        raise ValueError("observed rows/families/probes exceed frozen expected denominators")
    coverage_complete = (
        observed_rows == expected_rows
        and len(observed_families) == expected_families
        and len(observed_probes) == expected_families * expected_probes_per_family
        and all(
            sum(family == name for family, _ in observed_probes) == expected_probes_per_family
            for name in observed_families
        )
        and all(
            sum(row["direction"]["kind"] == kind for row in prepared)
            == expected_families * expected_probes_per_family * len(horizons)
            for kind in directions
        )
    )
    protocol_errors = [
        {
            "family_id": row["family_id"],
            "probe_id": row["probe_id"],
            "direction_kind": row["direction"]["kind"],
            "horizon": row["horizon"],
            "errors": row["protocol_errors"],
        }
        for row in prepared
        if row["protocol_errors"]
    ]

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in prepared:
        grouped[(row["family_id"], row["probe_id"], row["direction"]["kind"])].append(row)
    trajectories = []
    for (family, probe, kind), selected in sorted(grouped.items()):
        by_horizon = {row["horizon"]: row for row in selected}
        ordered = [by_horizon[horizon] for horizon in horizons if horizon in by_horizon]
        trajectory = _trajectory(ordered, floor, horizons)
        endpoint_row = by_horizon.get(endpoint_horizon)
        trajectories.append(
            {
                "family_id": family,
                "probe_id": probe,
                "direction_kind": kind,
                "direction_id": selected[0]["direction"]["direction_id"],
                "direction": dict(selected[0]["direction"]),
                "affected": selected[0]["affected"],
                "observed_horizons": sorted(by_horizon),
                "expected_horizons": list(horizons),
                "complete": set(by_horizon) == set(horizons),
                "endpoint_horizon": endpoint_horizon,
                "endpoint": endpoint_row["central_contrast"] if endpoint_row else None,
                "endpoint_kind": selected[0]["central_contrast_kind"],
                "signed_auc": trajectory["signed_trapezoid_auc"],
                "trajectory": trajectory,
            }
        )

    by_direction: dict[str, Any] = {}
    for kind in directions:
        selected = [item for item in trajectories if item["direction_kind"] == kind]
        direction_result: dict[str, Any] = {
            "trajectory_count": len(selected),
            "affected_trajectory_count": sum(item["affected"] for item in selected),
            "unaffected_trajectory_count": sum(not item["affected"] for item in selected),
            "endpoint": _distribution(item["endpoint"] for item in selected),
            "signed_auc": _distribution(item["signed_auc"] for item in selected),
            "affected": {},
        }
        for metric, field in (("endpoint", "endpoint"), ("signed_auc", "signed_auc")):
            by_family: dict[str, list[float | None]] = defaultdict(list)
            for item in selected:
                if item["affected"]:
                    by_family[item["family_id"]].append(item[field])
            direction_result["affected"][metric] = _family_interval(
                by_family,
                coverage_complete=coverage_complete
                and bool(by_family)
                and all(item["complete"] for item in selected),
                expected_families=expected_families,
            )
        per_horizon = {}
        for horizon in horizons:
            by_family = defaultdict(list)
            for row in prepared:
                if (
                    row["direction"]["kind"] == kind
                    and row["affected"]
                    and row["horizon"] == horizon
                ):
                    by_family[row["family_id"]].append(row["central_contrast"])
            per_horizon[str(horizon)] = _family_interval(
                by_family,
                coverage_complete=coverage_complete and bool(by_family),
                expected_families=expected_families,
            )
        direction_result["affected"]["per_horizon"] = per_horizon
        by_direction[kind] = direction_result

    measurements_complete = all(
        cell["candidate_logits"]["continuous_status"] == "OBSERVED"
        and cell["state_displacement"]["status"] == "OBSERVED"
        and cell["kv_displacement"]["status"] == "OBSERVED"
        for row in prepared
        for cell in row["cells"].values()
    )
    categorical_unknowns = Counter(
        cell["candidate_logits"]["categorical_unknown_reason"]
        for row in prepared
        for cell in row["cells"].values()
        if cell["candidate_logits"]["categorical_status"] == "UNKNOWN"
    )
    displacement = {
        measurement: {
            name: _distribution(
                row["cells"][name][measurement]["value"] for row in prepared
            )
            for name in CELL_NAMES
        }
        for measurement in ("state_displacement", "kv_displacement")
    }
    result: dict[str, Any] = {
        "format": FORMAT,
        "scope": "FIXED_TOKEN_ONE_PULSE_CACHE_TRAJECTORY_SCREEN",
        "plan": {
            "expected_horizons": list(horizons),
            "endpoint_horizon": endpoint_horizon,
            "frozen_floor": floor,
            "expected_families": expected_families,
            "expected_probes_per_family": expected_probes_per_family,
            "expected_direction_kinds": list(directions),
        },
        "coverage": {
            "complete": coverage_complete,
            "expected_rows": expected_rows,
            "observed_rows": observed_rows,
            "missing_rows": expected_rows - observed_rows,
            "expected_families": expected_families,
            "observed_families": len(observed_families),
            "expected_probes": expected_families * expected_probes_per_family,
            "observed_probes": len(observed_probes),
        },
        "protocol": {
            "valid": not protocol_errors,
            "errors": protocol_errors,
            "cell_contract": CELL_PROTOCOL,
            "same_token_ids_positions_masks_checked_within_five_cells": True,
            "same_history_checked_across_directions_at_each_horizon": True,
            "query_probe_identity_checked_across_horizons": True,
            "continuous_forcing_permitted": False,
        },
        "measurements": {
            "complete": measurements_complete,
            "categorical_unknown_count": sum(categorical_unknowns.values()),
            "categorical_unknown_reason_counts": dict(sorted(categorical_unknowns.items())),
            "finite_ties_retain_continuous_zero_margin": True,
            "displacement": displacement,
            "state_and_kv_displacement_are_separate": True,
        },
        "bootstrap": {
            "draws": BOOTSTRAP_DRAWS,
            "seed": BOOTSTRAP_SEED,
            "unit": "FAMILY_CLUSTER",
            "within_family_estimand": "EQUAL_WEIGHT_MEAN_OF_PROBES",
            "unknown_policy": "NO_ZERO_FILL; INCOMPLETE_FAMILY_INTERVAL_IS_UNKNOWN",
        },
        "trajectories": trajectories,
        "directions": by_direction,
        "semantic_minus_controls": _cross_direction_differences(
            trajectories,
            coverage_complete=coverage_complete,
            expected_families=expected_families,
        ),
        "unaffected_retention": _retention(
            prepared,
            coverage_complete=coverage_complete,
            expected_families=expected_families,
        ),
        "mechanical_screen_complete": (
            coverage_complete and not protocol_errors and measurements_complete
        ),
        "semantic_qualification": {
            "status": "NOT_RUN",
            "qualified": False,
            "reason": "Call semantic_qualification with a predeclared signed threshold plan.",
        },
        "claim_boundary": (
            "The central contrast is descriptive cache-history sensitivity. A non-semantic "
            "direction is never interpreted as semantic, G ratios are secondary, and neither "
            "completion nor displacement alone proves donor-directed semantic mediation."
        ),
    }
    return result


def mechanical_return_gate(
    summary: Mapping[str, Any], *, instrument_ok: bool, integrity_ok: bool
) -> dict[str, Any]:
    """Return a mechanical continuation decision without consulting semantic outcomes."""
    if type(instrument_ok) is not bool or type(integrity_ok) is not bool:
        raise ValueError("instrument_ok and integrity_ok must be explicit booleans")
    if summary.get("format") != FORMAT:
        raise ValueError("summary format is not a V14 cache-trajectory summary")
    checks = {
        "instrument_ok": instrument_ok,
        "integrity_ok": integrity_ok,
        "coverage_complete": summary["coverage"]["complete"] is True,
        "protocol_valid": summary["protocol"]["valid"] is True,
        "measurements_complete": summary["measurements"]["complete"] is True,
    }
    passed = all(checks.values())
    return {
        "status": "MECHANICAL_RETURN_GATE_PASSED" if passed else "BLOCKED_MECHANICAL_CHECK",
        "return_allowed": passed,
        "checks": checks,
        "blocking_checks": [name for name, value in checks.items() if not value],
        "semantic_accuracy_or_directionality_is_prerequisite": False,
        "semantic_qualification": False,
        "execution_authorization_granted_here": False,
    }


def semantic_qualification(
    summary: Mapping[str, Any], *, threshold_plan: Mapping[str, Any]
) -> dict[str, Any]:
    """Evaluate a separately frozen, signed semantic plan.

    Required thresholds are deliberately explicit so a mechanical run cannot silently
    inherit or tune a semantic pass rule after observing outcomes.
    """
    if summary.get("format") != FORMAT:
        raise ValueError("summary format is not a V14 cache-trajectory summary")
    required = (
        "endpoint_ci_lower_strictly_above",
        "signed_auc_ci_lower_strictly_above",
        "semantic_minus_control_endpoint_ci_lower_strictly_above",
        "semantic_minus_control_auc_ci_lower_strictly_above",
        "unaffected_retention_ci_lower_at_least",
    )
    if not isinstance(threshold_plan, Mapping) or any(
        name not in threshold_plan for name in required
    ):
        raise ValueError("threshold_plan is missing a required signed threshold")
    thresholds = {name: _fp32(threshold_plan[name]) for name in required}
    if any(value is None for value in thresholds.values()):
        raise ValueError("semantic thresholds must be finite numbers")
    plan_id = _identifier(threshold_plan.get("plan_id"), "threshold_plan.plan_id")
    if type(threshold_plan.get("frozen_before_measurement")) is not bool:
        raise ValueError("threshold_plan.frozen_before_measurement must be boolean")

    expected = set(summary["plan"]["expected_direction_kinds"])
    if "semantic" not in expected:
        return {
            "status": "NOT_APPLICABLE_NON_SEMANTIC_SCREEN",
            "qualified": False,
            "plan_id": plan_id,
            "reason": "The frozen screen contains no semantic direction.",
            "absolute_only_semantic_pass": False,
        }
    required_controls = {"equal_norm_random", "sham", "unrelated"}
    frozen = threshold_plan["frozen_before_measurement"]
    checks: dict[str, bool] = {
        "plan_frozen_before_measurement": frozen,
        "mechanical_screen_complete": summary["mechanical_screen_complete"] is True,
        "all_required_controls_present": required_controls <= expected,
    }
    semantic = summary["directions"].get("semantic", {}).get("affected", {})
    endpoint = semantic.get("endpoint", {})
    auc = semantic.get("signed_auc", {})
    checks["signed_endpoint_family_ci"] = (
        endpoint.get("status") == "OBSERVED"
        and endpoint["ci95"][0] > thresholds["endpoint_ci_lower_strictly_above"]
    )
    checks["signed_auc_family_ci"] = (
        auc.get("status") == "OBSERVED"
        and auc["ci95"][0] > thresholds["signed_auc_ci_lower_strictly_above"]
    )
    for control in sorted(required_controls):
        comparison = summary["semantic_minus_controls"][control]
        endpoint_delta = comparison["semantic_minus_control_endpoint"]
        auc_delta = comparison["semantic_minus_control_signed_auc"]
        checks[f"semantic_minus_{control}_endpoint_ci"] = (
            endpoint_delta["status"] == "OBSERVED"
            and endpoint_delta["ci95"][0]
            > thresholds["semantic_minus_control_endpoint_ci_lower_strictly_above"]
        )
        checks[f"semantic_minus_{control}_signed_auc_ci"] = (
            auc_delta["status"] == "OBSERVED"
            and auc_delta["ci95"][0]
            > thresholds["semantic_minus_control_auc_ci_lower_strictly_above"]
        )
    retention = summary["unaffected_retention"]
    retention_checks = []
    for item in retention["checks"].values():
        interval = item["family_cluster"]
        retention_checks.append(
            interval["status"] == "OBSERVED"
            and interval["ci95"][0] >= thresholds["unaffected_retention_ci_lower_at_least"]
        )
    checks["unaffected_retention"] = bool(retention_checks) and all(retention_checks)
    qualified = all(checks.values())
    return {
        "status": (
            "QUALIFIED_SIGNED_SEMANTIC_TRAJECTORY"
            if qualified
            else "NOT_QUALIFIED"
            if frozen
            else "UNKNOWN_NOT_PREDECLARED"
        ),
        "qualified": qualified,
        "plan_id": plan_id,
        "thresholds": thresholds,
        "checks": checks,
        "blocking_checks": [name for name, value in checks.items() if not value],
        "absolute_only_semantic_pass": False,
        "mechanical_return_gate_is_separate": True,
        "claim_boundary": (
            "Qualification is limited to the supplied frozen screen and does not prove "
            "generalization, free-generation behavior, or a learned workspace mechanism."
        ),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSONL rows")
    parser.add_argument("output", type=Path, help="summary JSON")
    parser.add_argument("--horizons", required=True, help="comma-separated frozen horizons")
    parser.add_argument("--endpoint-horizon", type=int, required=True)
    parser.add_argument("--frozen-floor", type=float, required=True)
    parser.add_argument("--expected-families", type=int, default=1)
    parser.add_argument("--expected-probes-per-family", type=int, default=1)
    parser.add_argument(
        "--direction-kinds", default="equal_norm_random,sham", help="comma-separated kinds"
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    rows = [json.loads(line) for line in args.input.read_text().splitlines() if line.strip()]
    result = summarize(
        rows,
        expected_horizons=tuple(int(value) for value in args.horizons.split(",")),
        endpoint_horizon=args.endpoint_horizon,
        frozen_floor=args.frozen_floor,
        expected_families=args.expected_families,
        expected_probes_per_family=args.expected_probes_per_family,
        expected_direction_kinds=tuple(args.direction_kinds.split(",")),
    )
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
