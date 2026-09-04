#!/usr/bin/env python3
"""Fixed calibration-only V14 screen metrics; task gates never gate the Mistral return.

Rows are answer cases, not independent replicates. Bootstrap draws resample entire
original-world families, preserving both routes and all views together. This module
does not validate source/weight provenance, inspect holdout data, or authorize jobs.
"""

from __future__ import annotations

import importlib.util
import math
import random
import struct
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

_SPEC = importlib.util.spec_from_file_location(
    "_v14_screen_paired_metrics", Path(__file__).with_name("v13_paired_metrics.py")
)
assert _SPEC is not None and _SPEC.loader is not None
_PAIRED = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_PAIRED)

BOOTSTRAP_DRAWS = 4096
BOOTSTRAP_SEED = 1404
THRESHOLDS = {
    "easy": {"accuracy": 0.75, "label_recall": 0.60},
    "primary": {"accuracy": 0.60, "label_recall": 0.55},
}
_RECORD_FIELDS = ("family_id", "role", "hop", "template", "orientation", "edit_type")


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value


def _fp32(value: float) -> float:
    result = struct.unpack("!f", struct.pack("!f", value))[0]
    if not math.isfinite(result):
        raise ValueError("NONFINITE_FP32_ARITHMETIC")
    return result


def _subtract(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    try:
        return _fp32(left - right)
    except (OverflowError, ValueError, struct.error):
        return None


def _logits(value: Any, target: int) -> dict[str, Any]:
    reason = None
    values = None
    if value is None:
        reason = "MISSING"
    elif not isinstance(value, (list, tuple)) or len(value) != 2:
        reason = "INVALID_SHAPE"
    elif any(type(item) not in (int, float) for item in value):
        reason = "INVALID_VALUE"
    else:
        try:
            values = [_fp32(float(item)) for item in value]
        except (OverflowError, ValueError, struct.error):
            reason = "NONFINITE_FP32_LOGITS"
    prediction = None
    margin = None
    if values is not None:
        if values[0] == values[1]:
            reason = "TIE_FP32"
        else:
            prediction = int(values[1] > values[0])
        margin = _subtract(values[target], values[1 - target])
    return {
        "logits": values,
        "prediction": prediction,
        "correct": None if prediction is None else int(prediction == target),
        "categorical_unknown_reason": reason,
        "target_margin": margin,
        "continuous_unknown": margin is None,
    }


def _prepare(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(rows, (str, bytes, Mapping)):
        raise ValueError("rows must be an iterable of answer-case objects")
    try:
        iterator = iter(rows)
    except TypeError as exc:
        raise ValueError("rows must be an iterable of answer-case objects") from exc
    result = []
    identities = set()
    records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(iterator):
        if not isinstance(row, Mapping):
            raise ValueError(f"row {index} must be an object")
        item = {
            field: _identifier(row.get(field), field)
            for field in ("record_id", "family_id", "role", "template", "orientation", "edit_type")
        }
        if item["role"] not in THRESHOLDS:
            raise ValueError("role must be primary or easy")
        for field in ("side", "query_index", "target_index"):
            if type(row.get(field)) is not int or row[field] not in (0, 1):
                raise ValueError(f"{field} must be integer 0 or 1, not boolean")
            item[field] = row[field]
        if type(row.get("affected")) is not bool:
            raise ValueError("affected must be boolean")
        item["affected"] = row["affected"]
        hop = row.get("hop")
        if type(hop) is not int or hop not in ((1,) if item["role"] == "easy" else (2, 3, 4)):
            raise ValueError("hop must be 1 for easy or 2/3/4 for primary")
        item["hop"] = hop
        identity = (item["record_id"], item["side"], item["query_index"])
        if identity in identities:
            raise ValueError(f"duplicate answer case: {identity}")
        identities.add(identity)
        for route in ("f0", "f1"):
            item[route] = _logits(row.get(f"{route}_logits"), item["target_index"])
        item["context_margin_gain"] = _subtract(
            item["f1"]["target_margin"], item["f0"]["target_margin"]
        )
        records[item["record_id"]].append(item)
        result.append(item)
    for record_id, cases in records.items():
        reference = cases[0]
        if any(any(row[k] != reference[k] for k in _RECORD_FIELDS) for row in cases):
            raise ValueError(f"inconsistent record metadata: {record_id}")
        if any(row["affected"] != reference["affected"] for row in cases):
            raise ValueError(f"reverse-query affected flags must agree: {record_id}")
        by_key = {(row["side"], row["query_index"]): row for row in cases}
        for query in (0, 1):
            pair = [by_key.get((side, query)) for side in (0, 1)]
            if all(pair):
                before, after = pair
                if before["affected"] != after["affected"] or before["affected"] != (
                    before["target_index"] != after["target_index"]
                ):
                    raise ValueError(f"twin labels disagree with affected: {record_id}/{query}")
        for side in (0, 1):
            pair = [by_key.get((side, query)) for query in (0, 1)]
            if all(pair):
                left, right = pair
                if left["target_index"] == right["target_index"]:
                    raise ValueError(f"reverse-query labels must be complementary: {record_id}")
                if left["affected"] != right["affected"]:
                    raise ValueError(f"reverse-query affected flags must agree: {record_id}")
    return sorted(result, key=lambda r: (r["record_id"], r["side"], r["query_index"]))


def _rate(correct: int, denominator: int, unknown: int) -> dict[str, Any]:
    return {
        "correct": correct,
        "denominator": denominator,
        "unknown_count": unknown,
        "value": correct / denominator if denominator and not unknown else None,
        "bounds": (
            [correct / denominator, (correct + unknown) / denominator]
            if denominator
            else [0.0, 1.0]
        ),
    }


def _distribution(values: list[float | None], missing: int = 0) -> dict[str, Any]:
    finite = sorted(value for value in values if value is not None)
    size = len(finite)
    return {
        "observed_count": size,
        "unknown_count": len(values) - size + missing,
        "mean": math.fsum(value / size for value in finite) if size else None,
        "min": finite[0] if size else None,
        "max": finite[-1] if size else None,
        "values": finite,
    }


def _quantile(values: list[float], fraction: float) -> float:
    position = (len(values) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (position - low)


def _interval(families: list[dict[str, Any]], metric: str, *, coverage_ok: bool) -> dict[str, Any]:
    bounds = [family[metric] for family in families]
    complete = coverage_ok and bool(bounds)
    domain = [-1.0, 1.0] if metric == "context_accuracy_delta" else [0.0, 1.0]
    if not complete:
        return {
            "value": None,
            "bounds": domain,
            "ci95": domain,
            "status": "UNKNOWN_INCOMPLETE_COVERAGE",
            "independent_families": len(bounds),
        }
    count = len(bounds)
    lower = math.fsum(value[0] / count for value in bounds)
    upper = math.fsum(value[1] / count for value in bounds)
    rng = random.Random(BOOTSTRAP_SEED)
    draws_low, draws_high = [], []
    for _ in range(BOOTSTRAP_DRAWS):
        sample = [bounds[rng.randrange(count)] for _ in range(count)]
        draws_low.append(math.fsum(value[0] / count for value in sample))
        draws_high.append(math.fsum(value[1] / count for value in sample))
    observed = all(value[0] == value[1] for value in bounds)
    return {
        "value": lower if observed else None,
        "bounds": [lower, upper],
        "ci95": [_quantile(sorted(draws_low), 0.025), _quantile(sorted(draws_high), 0.975)],
        "status": "OBSERVED" if observed else "UNKNOWN_BOUNDED",
        "independent_families": count,
    }


def _subset(
    rows: list[dict[str, Any]], *, coverage_ok: bool, bootstrap: bool = False
) -> dict[str, Any]:
    # Every known record has exactly four expected answer-case positions.
    expected = 4 * len({row["record_id"] for row in rows})
    missing = expected - len(rows)
    result: dict[str, Any] = {
        "observed_case_count": len(rows),
        "expected_cases_in_identified_records": expected,
        "missing_cases_in_identified_records": missing,
        "family_count": len({row["family_id"] for row in rows}),
        "unidentified_record_allocation_known": coverage_ok,
        "context_target_margin_gain": _distribution(
            [row["context_margin_gain"] for row in rows], missing
        ),
    }
    for route in ("f0", "f1"):
        correct = sum(row[route]["correct"] == 1 for row in rows)
        unknown = sum(row[route]["correct"] is None for row in rows)
        labels = {}
        for label in (0, 1):
            selected = [row for row in rows if row["target_index"] == label]
            recall = _rate(
                sum(row[route]["correct"] == 1 for row in selected),
                len(selected),
                sum(row[route]["correct"] is None for row in selected),
            )
            if missing or not coverage_ok:
                recall.update(value=None, bounds=[0.0, 1.0], missing_label_allocation_unknown=True)
            labels[str(label)] = recall
        result[route] = {
            "accuracy": _rate(correct, expected, unknown + missing),
            "label_recall": labels,
            "prediction_counts": {
                str(label): sum(row[route]["prediction"] == label for row in rows)
                for label in (0, 1)
            },
            "categorical_unknown_count": unknown + missing,
            "unknown_reason_counts": dict(
                sorted(
                    Counter(
                        row[route]["categorical_unknown_reason"]
                        for row in rows
                        if row[route]["categorical_unknown_reason"] is not None
                    ).items()
                )
            ),
            "target_margin": _distribution([row[route]["target_margin"] for row in rows], missing),
        }
    transition = {
        f"{before}_to_{after}": 0
        for before in ("wrong", "correct")
        for after in ("wrong", "correct")
    }
    context_unknown = missing
    for row in rows:
        f0, f1 = (row[route]["correct"] for route in ("f0", "f1"))
        if f0 is None or f1 is None:
            context_unknown += 1
        else:
            transition[f"{'correct' if f0 else 'wrong'}_to_{'correct' if f1 else 'wrong'}"] += 1
    result["same_target_f0_to_f1_transitions"] = {
        "counts": transition,
        "unknown_count": context_unknown,
        "denominator": expected,
    }
    families = []
    for family_id in sorted({row["family_id"] for row in rows}):
        selected = [row for row in rows if row["family_id"] == family_id]
        denominator = 4 * len({row["record_id"] for row in selected})
        family = {"family_id": family_id, "denominator": denominator}
        for route in ("f0", "f1"):
            correct = sum(row[route]["correct"] == 1 for row in selected)
            unknown = denominator - sum(row[route]["correct"] is not None for row in selected)
            family[f"{route}_accuracy"] = [correct / denominator, (correct + unknown) / denominator]
        a, b = family["f0_accuracy"], family["f1_accuracy"]
        family["context_accuracy_delta"] = [b[0] - a[1], b[1] - a[0]]
        families.append(family)
    result["families"] = families
    if bootstrap:
        result["family_cluster"] = {
            metric: _interval(families, metric, coverage_ok=coverage_ok)
            for metric in ("f0_accuracy", "f1_accuracy", "context_accuracy_delta")
        }
    return result


def _gate(role: str, result: dict[str, Any], coverage_ok: bool) -> dict[str, Any]:
    threshold = THRESHOLDS[role]
    f1 = result["f1"]
    accuracy = f1["accuracy"]["value"]
    recalls = [f1["label_recall"][str(label)]["value"] for label in (0, 1)]
    intervals = result["family_cluster"]
    known = (
        coverage_ok
        and result["observed_case_count"] > 0
        and all(
            result[route]["categorical_unknown_count"] == 0
            and result[route]["target_margin"]["unknown_count"] == 0
            for route in ("f0", "f1")
        )
        and result["context_target_margin_gain"]["unknown_count"] == 0
    )
    checks = {
        "complete_known_measurements": known,
        "f1_accuracy": accuracy is not None and accuracy >= threshold["accuracy"],
        "both_label_recall": all(
            value is not None and value >= threshold["label_recall"] for value in recalls
        ),
        "f1_family_ci_lower_above_chance": intervals["f1_accuracy"]["ci95"][0] > 0.5,
        "context_benefit_family_ci_lower_positive": (
            intervals["context_accuracy_delta"]["ci95"][0] > 0.0
        ),
    }
    qualified = all(checks.values())
    return {
        "status": "QUALIFIED_CALIBRATION_ONLY"
        if qualified
        else "NOT_QUALIFIED"
        if known
        else "UNKNOWN",
        "qualified": qualified,
        "checks": checks,
        "thresholds": {
            **threshold,
            "f1_family_ci_lower_strictly_above": 0.5,
            "context_benefit_ci_lower_strictly_above": 0.0,
        },
        "is_mistral_return_prerequisite": False,
    }


def _donor_pairs(rows: list[dict[str, Any]], expected_records: int) -> dict[str, Any]:
    cases = {(row["record_id"], row["query_index"], row["side"]): row for row in rows}
    pairs = []
    missing_side_labels_derived = 0
    for record_id, query in sorted({(row["record_id"], row["query_index"]) for row in rows}):
        before, after = [cases.get((record_id, query, side)) for side in (0, 1)]
        known = before if before is not None else after
        assert known is not None
        original_label = (
            before["target_index"]
            if before is not None
            else (known["target_index"] ^ int(known["affected"]))
        )
        donor_label = original_label ^ int(known["affected"])
        missing_side_labels_derived += int(before is None or after is None)
        for route in ("f0", "f1"):
            pairs.append(
                {
                    "original_world_family_id": known["family_id"],
                    "pair_id": record_id,
                    "query_id": str(query),
                    "variant_id": known["role"],
                    "control_id": route,
                    "original_label": original_label,
                    "donor_label": donor_label,
                    "intact_logits": before[route]["logits"] if before is not None else None,
                    "swapped_logits": after[route]["logits"] if after is not None else None,
                }
            )
    groups = _PAIRED.summarize_pairs(pairs)["groups"] if pairs else []
    return {
        "comparison": "ORIGINAL_TO_TWIN_CONTEXT_WITHIN_ROUTE_NOT_F0_TO_F1",
        "expected_pairs_per_route": expected_records * 2,
        "identified_pairs_per_route": len(pairs) // 2,
        "unidentified_pairs_per_route": expected_records * 2 - len(pairs) // 2,
        "missing_side_labels_derived_from_other_side_and_affected": missing_side_labels_derived,
        "groups": [
            {key: value for key, value in group.items() if key not in ("families", "per_case")}
            for group in groups
        ],
        "claim_boundary": (
            "Context-twin sensitivity, not learned-memory transfer or causal qualification."
        ),
    }


def summarize(
    rows: Iterable[Mapping[str, Any]], *, expected_records: int = 120, expected_families: int = 12
) -> dict[str, Any]:
    """Summarize fixed calibration cases; missing observations are never zero-filled.

    Each record has two sides x two reverse queries. Entirely absent records cannot
    be allocated to a role/family from rows alone: their expected global denominator
    remains explicit, role CIs widen to the full domain, and both task gates block.
    The caller must separately bind records and identities to the frozen corpus.
    """
    for name, value in (
        ("expected_records", expected_records),
        ("expected_families", expected_families),
    ):
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    prepared = _prepare(rows)
    record_ids = {row["record_id"] for row in prepared}
    family_ids = {row["family_id"] for row in prepared}
    expected_cases = 4 * expected_records
    if len(record_ids) > expected_records or len(family_ids) > expected_families:
        raise ValueError("observed records/families exceed the frozen expected denominators")
    role_families = {
        role: len({row["family_id"] for row in prepared if row["role"] == role})
        for role in THRESHOLDS
    }
    coverage_ok = (
        len(prepared) == expected_cases
        and len(family_ids) == expected_families
        and all(count == expected_families for count in role_families.values())
    )
    missing_cases = expected_cases - len(prepared)
    result: dict[str, Any] = {
        "format": "latent-workspace-v14-screen-metrics-v1",
        "scope": "CALIBRATION_ONLY_NO_HOLDOUT_OR_GENERALIZATION_CLAIM",
        "coverage": {
            "ok": coverage_ok,
            "expected_records": expected_records,
            "observed_records": len(record_ids),
            "expected_cases": expected_cases,
            "observed_cases": len(prepared),
            "missing_cases": missing_cases,
            "expected_independent_families": expected_families,
            "observed_independent_families": len(family_ids),
            "observed_independent_families_by_role": role_families,
            "missing_cases_in_unidentified_records": 4 * (expected_records - len(record_ids)),
            "corpus_identity_binding_checked_here": False,
        },
        "bootstrap": {
            "draws": BOOTSTRAP_DRAWS,
            "seed": BOOTSTRAP_SEED,
            "confidence": 0.95,
            "unit": "ORIGINAL_WORLD_FAMILY_CLUSTER",
            "method": "PERCENTILE_LINEAR_INTERPOLATION",
            "estimand": "EQUAL_WEIGHT_MEAN_OF_FAMILY_CASE_ACCURACIES_AND_PAIRED_ROUTE_DIFFERENCES",
            "unknown_policy": "RESAMPLE_FAMILY_LOWER_UPPER_BOUNDS; NO_QUALIFICATION_WITH_UNKNOWNS",
            "all_sides_queries_templates_orientations_alternate_edits_resampled_together": True,
            "strata_intervals_computed": False,
        },
        "arithmetic": "FP32_OPERANDS_AND_SUBTRACTIONS; FLOAT64_DESCRIPTIVE_SUMS",
        "overall_accuracy_expected_denominator": {},
    }
    for route in ("f0", "f1"):
        result["overall_accuracy_expected_denominator"][route] = _rate(
            sum(row[route]["correct"] == 1 for row in prepared),
            expected_cases,
            missing_cases + sum(row[route]["correct"] is None for row in prepared),
        )
    roles = {}
    for role in THRESHOLDS:
        selected = [row for row in prepared if row["role"] == role]
        role_result = _subset(selected, coverage_ok=coverage_ok, bootstrap=True)
        role_result["gate"] = _gate(role, role_result, coverage_ok)
        role_result["strata"] = {
            field: {
                str(value): _subset(
                    [row for row in selected if row[field] == value], coverage_ok=coverage_ok
                )
                for value in sorted({row[field] for row in selected})
            }
            for field in ("hop", "template", "affected", "orientation")
        }
        roles[role] = role_result
    result["roles"] = roles
    result["donor_pairs"] = _donor_pairs(prepared, expected_records)
    result["screen_complete"] = (
        coverage_ok
        and all(
            row[route]["logits"] is not None and not row[route]["continuous_unknown"]
            for row in prepared
            for route in ("f0", "f1")
        )
        and all(row["context_margin_gain"] is not None for row in prepared)
    )
    result["status"] = "COMPLETE_CALIBRATION_SCREEN" if result["screen_complete"] else "INCOMPLETE"
    result["claim_boundary"] = (
        "No training, holdout scoring, generalization, learned-memory causality, "
        "or scientific promotion. Constrained BASE-model elicitation only; finite ties "
        "keep margins but not categorical credit. Easy and hard gates are calibration-only "
        "and are never prerequisites for returning to Mistral. Coverage counts do not replace "
        "external frozen-corpus/source/input/weight integrity checks."
    )
    return result


def return_decision(
    instrument_ok: bool, coverage_ok: bool, integrity_ok: bool, screen_complete: bool
) -> dict[str, Any]:
    """Pure mechanical return decision; task accuracy is intentionally not an input."""
    checks = dict(
        instrument_ok=instrument_ok,
        coverage_ok=coverage_ok,
        integrity_ok=integrity_ok,
        screen_complete=screen_complete,
    )
    if any(type(value) is not bool for value in checks.values()):
        raise ValueError("return-decision checks must be explicit booleans")
    allowed = all(checks.values())
    return {
        "return_to_mistral": allowed,
        "decision": "RETURN_TO_MISTRAL" if allowed else "BLOCKED_MECHANICAL_CHECK",
        "checks": checks,
        "blocking_checks": [key for key, value in checks.items() if not value],
        "task_accuracy_is_prerequisite": False,
        "scientific_promotion": False,
        "execution_authorization_granted_here": False,
    }
