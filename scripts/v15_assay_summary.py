"""Pure, fail-closed summaries for the fixed V15 content/order crossover.

This module has no model, filesystem, network, or training dependencies. Native
and diagnostic FP32 scores remain distinct; ties are never counted as correct.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence

MODES = ("final", "mean_span")
ORDERS = ("original", "canonical", "canonical_reverse")
MEMORY_KEYS = tuple(f"{order}_{side}" for order in ORDERS for side in (0, 1)) + (
    "zero",
    "fixed_carrier",
    "norm_matched_random_0",
    "norm_matched_random_1",
    "unrelated",
    "different_schema",
)
CONTROL_KEYS = MEMORY_KEYS[6:]
TRANSPORT_FLOATS = (
    "kl_base_to_candidate",
    "total_variation",
    "max_abs_logit_change",
    "base_top1_probability",
    "candidate_top1_probability",
)


def canonical_facts(text: str, reverse: bool = False) -> str:
    """Sort literal fact lines without labels, preserving their text and header.

    Accept one nonempty header followed by one or more unique, nonempty ``- ``
    lines. Blank lines, extra headers, indentation and whitespace repair are
    rejected; the final newline, if present, is retained. This intentionally
    does not require the current dataset's five facts.
    """
    if not isinstance(text, str) or type(reverse) is not bool or "\r" in text:
        raise ValueError("Expected LF-separated fact text and a boolean reverse flag")
    lines = text.splitlines()
    if len(lines) < 2:
        raise ValueError("Expected one header followed by nonempty fact lines")
    header, facts = lines[0], lines[1:]
    if not header or header != header.strip() or header.startswith("-"):
        raise ValueError("Expected one nonempty, unindented header")
    if any(
        not line.startswith("- ") or not line[2:] or line[2:] != line[2:].strip() for line in facts
    ):
        raise ValueError("Each fact must be an unmodified nonempty '- ' line")
    if len(set(facts)) != len(facts):
        raise ValueError("Fact lines must be unique")
    return "\n".join([header, *sorted(facts, reverse=reverse)]) + (
        "\n" if text.endswith("\n") else ""
    )


def parse_functional_answer(text: str) -> int | None:
    """Parse only an entire stripped yes/no answer, never an inferred first token."""
    if not isinstance(text, str):
        raise ValueError("Functional answer must be text")
    return {"no": 0, "yes": 1}.get(text.strip().lower())


def _number(value, name, *, minimum=None, maximum=None):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} lies below its minimum")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} lies above its maximum")
    return float(value)


def _scores(value, name):
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a score record")
    scores = value.get("scores")
    if not isinstance(scores, (list, tuple)) or len(scores) != 2:
        raise ValueError(f"{name}.scores must contain [no, yes]")
    no, yes = [_number(item, f"{name}.scores") for item in scores]
    gap = _number(value.get("gap"), f"{name}.gap")
    # Raw scores and their Python-float subtraction are the source of truth.
    # Do not infer ties from the sign of an approximately equal recorded gap.
    if gap != yes - no:
        raise ValueError(f"{name}.gap does not reproduce its two scores")
    prediction = None if yes == no else int(yes > no)
    supplied = value.get("prediction", "missing")
    if (supplied is not None and type(supplied) is not int) or supplied != prediction:
        raise ValueError(f"{name}.prediction disagrees with scores or tie policy")
    return {"scores": [no, yes], "gap": gap, "prediction": prediction}


def _stats(values):
    values = list(values)
    if not values:
        raise ValueError("Cannot summarize an empty diagnostic slice")
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": math.fsum(values) / len(values),
    }


def _accuracy(items):
    items = list(items)
    correct = sum(score["prediction"] == label for score, label in items)
    ties = sum(score["prediction"] is None for score, _ in items)
    return {
        "correct": correct,
        "total": len(items),
        "ties": ties,
        "incorrect_nonties": len(items) - correct - ties,
    }


def _validate(rows):
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or len(rows) != 384:
        raise ValueError("The complete crossover must contain exactly 384 rows")
    indexed, metadata, bases, base_top = {}, {}, {}, {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("Each crossover row must be a mapping")
        mode, world, query, key = (
            row.get(name) for name in ("mode", "world", "query", "memory_key")
        )
        if mode not in MODES or type(world) is not int or world not in (0, 1):
            raise ValueError("Unknown mode or world")
        if type(query) is not int or query not in range(8) or key not in MEMORY_KEYS:
            raise ValueError("Unknown query or memory key")
        identity = mode, world, query, key
        if identity in indexed:
            raise ValueError(f"Duplicate crossover row: {identity}")
        labels = row.get("labels")
        if (
            not isinstance(labels, (list, tuple))
            or len(labels) != 2
            or any(type(label) is not int or label not in (0, 1) for label in labels)
        ):
            raise ValueError("labels must be two binary integers")
        affected = row.get("affected")
        if type(affected) is not bool or affected != (labels[0] != labels[1]):
            raise ValueError("Affected flag must exactly match the label change")
        meta = tuple(labels), affected
        pair = world, query
        if pair in metadata and metadata[pair] != meta:
            raise ValueError("Labels/affected metadata changed across crossover cells")
        metadata[pair] = meta
        normalized = {"labels": tuple(labels), "affected": affected}
        for arithmetic in ("native", "fp32"):
            normalized[arithmetic] = _scores(row.get(arithmetic), arithmetic)
            baseline = _scores(row.get(f"base_{arithmetic}"), f"base_{arithmetic}")
            base_key = world, query, arithmetic
            if base_key in bases and bases[base_key] != baseline:
                raise ValueError("Base scores changed across matched cells")
            bases[base_key] = baseline
            normalized[f"base_{arithmetic}"] = baseline
        transport = row.get("transport")
        if not isinstance(transport, Mapping):
            raise ValueError("Missing native full-vocabulary transport record")
        t = {}
        for name in TRANSPORT_FLOATS:
            # A tiny negative KL is possible in finite arithmetic; retain it,
            # rather than silently clipping it into a positive effect.
            minimum = -1e-12 if name == "kl_base_to_candidate" else 0
            maximum = (
                1
                if name
                in ("total_variation", "base_top1_probability", "candidate_top1_probability")
                else None
            )
            t[name] = _number(transport.get(name), name, minimum=minimum, maximum=maximum)
        for name in ("base_top1", "candidate_top1"):
            token = transport.get(name)
            if type(token) is not int or token < 0:
                raise ValueError(f"{name} must be a nonnegative token ID")
            t[name] = token
        base_reference = t["base_top1"], t["base_top1_probability"]
        if pair in base_top and base_top[pair] != base_reference:
            raise ValueError("Full-vocabulary base reference changed across matched cells")
        base_top[pair] = base_reference
        normalized["transport"] = t
        for name in ("delta_l2", "native_applied_delta_l2"):
            normalized[name] = _number(row.get(name), name, minimum=0)
        if key == "zero":
            if any(normalized[a] != normalized[f"base_{a}"] for a in ("native", "fp32")):
                raise ValueError("Written-zero scores are not an exact base noop")
            if any(normalized[name] != 0 for name in ("delta_l2", "native_applied_delta_l2")):
                raise ValueError("Written-zero residual is nonzero")
            if any(t[name] != 0 for name in TRANSPORT_FLOATS[:3]) or (
                t["base_top1"] != t["candidate_top1"]
                or t["base_top1_probability"] != t["candidate_top1_probability"]
            ):
                raise ValueError("Written-zero native transport is nonzero")
        indexed[identity] = normalized
    expected = set(itertools.product(MODES, range(2), range(8), MEMORY_KEYS))
    if set(indexed) != expected:
        raise ValueError("Crossover row identities do not match the complete grid")
    if sum(affected for _, affected in metadata.values()) != 4:
        raise ValueError("Expected four affected and twelve unaffected world/query pairs")
    return indexed


def summarize_crossover(rows):
    """Validate the fixed grid, then summarize matched content/order contrasts.

    Raw score differences are checked exactly. No winner or all-32 feasibility
    gate is introduced. Input row order is irrelevant and input data is untouched.
    Scalar summaries validate receipts, not the underlying absent tensor logits.
    """
    indexed = _validate(rows)
    pairs = tuple(itertools.product(range(2), range(8)))
    result = {
        "schema_version": "v15_crossover_summary_v1",
        "row_count": len(indexed),
        "denominators": {
            "worlds": 2,
            "unique_world_query_pairs": 16,
            "affected_pairs": 4,
            "unaffected_pairs": 12,
            "side_query_rows_per_order": 32,
        },
        "claim_scope": "exposed_train_worlds_no_training_no_winner_no_nonregression_claim",
        "modes": {},
    }
    for mode in MODES:
        summary = {"base": {}, "orders": {}, "serialization": {}, "controls": {}}
        for arithmetic in ("native", "fp32"):
            summary["base"][arithmetic] = _accuracy(
                (
                    indexed[mode, w, q, "zero"][f"base_{arithmetic}"],
                    indexed[mode, w, q, "zero"]["labels"][side],
                )
                for w, q in pairs
                for side in (0, 1)
            )
        for order in ORDERS:
            summary["orders"][order] = {}
            for arithmetic in ("native", "fp32"):
                affected, unaffected, accuracy = [], [], []
                for w, q in pairs:
                    left, right = (indexed[mode, w, q, f"{order}_{side}"] for side in (0, 1))
                    a, b = left[arithmetic], right[arithmetic]
                    labels = left["labels"]
                    accuracy.extend([(a, labels[0]), (b, labels[1])])
                    contrast = {
                        "world": w,
                        "query": q,
                        "gap_0": a["gap"],
                        "gap_1": b["gap"],
                        "gap_change": b["gap"] - a["gap"],
                        "prediction_0": a["prediction"],
                        "prediction_1": b["prediction"],
                        "labels": list(labels),
                    }
                    if left["affected"]:
                        contrast["donor_signed_change"] = (2 * labels[1] - 1) * contrast[
                            "gap_change"
                        ]
                        contrast["correct_flip"] = (
                            a["prediction"] == labels[0] and b["prediction"] == labels[1]
                        )
                        affected.append(contrast)
                    else:
                        contrast["prediction_changed_including_ties"] = (
                            a["prediction"] != b["prediction"]
                        )
                        unaffected.append(contrast)
                summary["orders"][order][arithmetic] = {
                    **_accuracy(accuracy),
                    "affected_content": {
                        "rows": affected,
                        "count": len(affected),
                        "correct_flips": sum(row["correct_flip"] for row in affected),
                        "positive_donor_changes": sum(
                            row["donor_signed_change"] > 0 for row in affected
                        ),
                        "donor_signed_change": _stats(
                            row["donor_signed_change"] for row in affected
                        ),
                    },
                    "unaffected_content": {
                        "rows": unaffected,
                        "count": len(unaffected),
                        "prediction_changes_including_ties": sum(
                            row["prediction_changed_including_ties"] for row in unaffected
                        ),
                        "absolute_gap_change": _stats(abs(row["gap_change"]) for row in unaffected),
                    },
                }
        for order in ORDERS[1:]:
            summary["serialization"][order] = {}
            for arithmetic in ("native", "fp32"):
                changes = []
                for w, q in pairs:
                    for side in (0, 1):
                        original = indexed[mode, w, q, f"original_{side}"]
                        variant = indexed[mode, w, q, f"{order}_{side}"]
                        a, b = original[arithmetic], variant[arithmetic]
                        label = original["labels"][side]
                        changes.append(
                            {
                                "world": w,
                                "query": q,
                                "side": side,
                                "label": label,
                                "gap_change": b["gap"] - a["gap"],
                                "prediction_original": a["prediction"],
                                "prediction_variant": b["prediction"],
                                "regression": a["prediction"] == label and b["prediction"] != label,
                                "improvement": a["prediction"] != label
                                and b["prediction"] == label,
                            }
                        )
                summary["serialization"][order][arithmetic] = {
                    "rows": changes,
                    "count": len(changes),
                    "absolute_gap_change": _stats(abs(row["gap_change"]) for row in changes),
                    "prediction_changes_including_ties": sum(
                        row["prediction_original"] != row["prediction_variant"] for row in changes
                    ),
                    "regressions_from_original": sum(row["regression"] for row in changes),
                    "improvements_from_original": sum(row["improvement"] for row in changes),
                }
        for key in CONTROL_KEYS:
            selected = [indexed[mode, w, q, key] for w, q in pairs]
            control = {"count": len(selected)}
            for arithmetic in ("native", "fp32"):
                control[arithmetic] = {
                    "absolute_gap_drift_from_base": _stats(
                        abs(row[arithmetic]["gap"] - row[f"base_{arithmetic}"]["gap"])
                        for row in selected
                    ),
                    "prediction_changes_from_base_including_ties": sum(
                        row[arithmetic]["prediction"] != row[f"base_{arithmetic}"]["prediction"]
                        for row in selected
                    ),
                    "ties": sum(row[arithmetic]["prediction"] is None for row in selected),
                }
            control["transport"] = {
                name: _stats(row["transport"][name] for row in selected)
                for name in TRANSPORT_FLOATS
            }
            control["transport"]["top1_changes"] = sum(
                row["transport"]["base_top1"] != row["transport"]["candidate_top1"]
                for row in selected
            )
            for name in ("delta_l2", "native_applied_delta_l2"):
                control[name] = _stats(row[name] for row in selected)
            summary["controls"][key] = control
        result["modes"][mode] = summary
    return result
