"""Pure fixed-path completion accounting for an already-exposed V15 panel.

This posthoc diagnostic sums four declared one-token answer aliases followed
immediately by EOS. It is neither new generation nor an exhaustive valid-answer
probability, and it cannot change the preceding expression gate or its answers.
"""

from __future__ import annotations

import itertools
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from numbers import Integral, Real
from typing import Any

ALIASES = ((0, " no"), (0, " No"), (1, " yes"), (1, " Yes"))
RENDERERS = ("raw", "native_chat")
INFORMATION = ("query_only", "inline")
METADATA = (
    "case_id",
    "renderer",
    "information",
    "target_label",
    "view",
    "wording",
    "split",
    "family_id",
)
STAGES = ("lowercase", "alias_start", "completion")
CLAIM_CEILING = (
    "posthoc fixed-alias-plus-immediate-EOS mass on an exposed panel; "
    "not new generation, exhaustive valid-answer mass, or a replacement expression gate"
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _number(value: Any, name: str) -> float:
    _require(isinstance(value, Real) and not isinstance(value, bool), f"{name} must be numeric")
    result = float(value)
    _require(math.isfinite(result), f"{name} must be finite")
    return result


def _ids(values: Any) -> list[int]:
    _require(
        isinstance(values, Sequence)
        and not isinstance(values, (str, bytes))
        and bool(values)
        and all(isinstance(v, Integral) and not isinstance(v, bool) and v >= 0 for v in values),
        "Expected a nonempty unbatched integer token sequence",
    )
    return [int(value) for value in values]


def bind_aliases(tokenizer: Any, text: str, prefix_ids: Sequence[int]) -> list[dict[str, Any]]:
    """Bind fixed aliases without truncation or prefix retokenization fallback.

    Token-equivalent capitalization aliases within one answer class count once.
    A token shared between no and yes is an error, not an ambiguous class mass.
    """
    _require(isinstance(text, str) and bool(text), "Expected nonempty prefix text")
    prefix = _ids(prefix_ids)
    _require(
        _ids(tokenizer.encode(text, add_special_tokens=False)) == prefix,
        "Prefix text/token identity changed",
    )
    by_token: dict[int, dict[str, Any]] = {}
    for label, suffix in ALIASES:
        full = _ids(tokenizer.encode(text + suffix, add_special_tokens=False))
        _require(
            len(full) == len(prefix) + 1 and full[:-1] == prefix,
            f"Alias {suffix!r} is not an exact one-token prefix extension",
        )
        token = full[-1]
        if token in by_token:
            _require(by_token[token]["target_label"] == label, "Cross-class token collision")
            by_token[token]["suffixes"].append(suffix)
        else:
            by_token[token] = {"target_label": label, "token_id": token, "suffixes": [suffix]}
    return list(by_token.values())


def _binding_rows(aliases: Any) -> None:
    _require(isinstance(aliases, list) and 2 <= len(aliases) <= 4, "Alias-path denominator")
    suffixes, tokens, positions = [], set(), []
    for alias in aliases:
        _require(isinstance(alias, Mapping), "Alias row must be a mapping")
        label = alias.get("target_label")
        token = alias.get("token_id")
        _require(type(label) is int and label in (0, 1), "Alias label")
        _require(
            type(token) is int and token >= 0 and token not in tokens, "Duplicate/invalid token"
        )
        tokens.add(token)
        strings = alias.get("suffixes")
        _require(isinstance(strings, list) and 1 <= len(strings) <= 2, "Alias suffix denominator")
        _require(
            all(isinstance(s, str) and (label, s) in ALIASES for s in strings), "Alias spelling"
        )
        indices = [ALIASES.index((label, suffix)) for suffix in strings]
        _require(indices == sorted(set(indices)), "Duplicate/reordered alias spelling")
        suffixes.extend(strings)
        positions.append(indices[0])
    _require(sorted(suffixes) == sorted(s for _, s in ALIASES), "Missing/duplicate fixed aliases")
    _require(positions == sorted(positions), "Alias class/path order changed")


def _logsumexp(values: Sequence[float]) -> float:
    maximum = max(values)
    return maximum + math.log(math.fsum(math.exp(value - maximum) for value in values))


def _prediction(gap: float) -> int | None:
    return None if gap == 0 else int(gap > 0)


def _class_result(logs: list[float], target: int) -> dict[str, Any]:
    total_log = _logsumexp(logs)
    gap = logs[1] - logs[0]
    predicted = _prediction(gap)
    return {
        "scores": logs,
        "gap": gap,
        "prediction": predicted,
        "correct": predicted == target,
        "probabilities": [math.exp(value) for value in logs],
        "total_probability": math.exp(total_log),
        "conditional_probabilities": [math.exp(value - total_log) for value in logs],
    }


def analyze_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Validate saved scalar receipts and recompute all three answer contrasts."""
    _require(isinstance(row, Mapping), "Expected a scored prompt row")
    for name in METADATA:
        _require(name in row, f"Missing metadata {name}")
    target = row["target_label"]
    _require(type(target) is int and target in (0, 1), "Target label")
    _require(row["renderer"] in RENDERERS and row["information"] in INFORMATION, "Factor level")
    _require(row["split"] in ("exposed", "confirmation"), "Original panel split")
    _require(row["view"] in ("historical", "atomic", "full_chain"), "View")
    _require(row["wording"] in ("ranked_above", "outrank"), "Wording")
    for name in ("case_id", "family_id"):
        _require(isinstance(row[name], str) and bool(row[name]), f"Invalid {name}")

    aliases = row.get("aliases")
    _binding_rows(aliases)
    starts, completes = {0: [], 1: []}, {0: [], 1: []}
    for alias in aliases:
        first = _number(alias["first_log_probability"], "First log probability")
        eos = _number(alias["eos_log_probability"], "EOS log probability")
        complete = _number(alias["complete_log_probability"], "Complete log probability")
        _require(first <= 0 and eos <= 0 and complete <= 0, "Log probability must be nonpositive")
        _require(
            math.isclose(complete, first + eos, rel_tol=1e-12, abs_tol=1e-14),
            "Complete log probability is not first plus EOS",
        )
        for name, logp in (
            ("first_probability", first),
            ("eos_probability", eos),
            ("complete_probability", complete),
        ):
            probability = _number(alias[name], name)
            _require(0 <= probability <= 1, f"Invalid {name}")
            _require(
                math.isclose(probability, math.exp(logp), rel_tol=1e-12, abs_tol=1e-15),
                f"{name} disagrees with its log probability",
            )
        starts[alias["target_label"]].append(first)
        completes[alias["target_label"]].append(first + eos)
    start = _class_result([_logsumexp(starts[label]) for label in (0, 1)], target)
    completion = _class_result([_logsumexp(completes[label]) for label in (0, 1)], target)
    _require(start["total_probability"] <= 1 + 1e-12, "Alias first-token masses exceed one")
    _require(
        completion["total_probability"] <= start["total_probability"] + 1e-12,
        "Complete path mass exceeds first-token mass",
    )

    old = row.get("old_lowercase_native")
    _require(isinstance(old, Mapping), "Missing original lowercase native scores")
    scores = old.get("scores")
    _require(isinstance(scores, list) and len(scores) == 2, "Original score denominator")
    scores = [_number(value, "Original score") for value in scores]
    gap = scores[1] - scores[0]
    _require(_number(old.get("gap"), "Original gap") == gap, "Original lowercase gap drift")
    prediction = _prediction(gap)
    _require(
        old.get("prediction") == prediction
        and (old.get("prediction") is None or type(old["prediction"]) is int),
        "Original lowercase prediction drift",
    )
    return {
        **{name: row[name] for name in METADATA},
        "alias_token_paths": len(aliases),
        "lowercase": {
            "scores": scores,
            "gap": gap,
            "prediction": prediction,
            "correct": prediction == target,
        },
        "alias_start": start,
        "completion": completion,
    }


def _group(rows: Sequence[dict[str, Any]], dimensions: Sequence[str]) -> list[dict[str, Any]]:
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[name] for name in dimensions)].append(row)
    output = []
    for key, selected in sorted(groups.items()):
        cell = {**dict(zip(dimensions, key, strict=True)), "total": len(selected), "stages": {}}
        pairs = defaultdict(list)
        for row in selected:
            pairs[
                (
                    row["renderer"],
                    row["information"],
                    row["split"],
                    row["family_id"],
                    row["view"],
                    row["wording"],
                )
            ].append(row)
        _require(
            all(
                len(pair) == 2 and {r["target_label"] for r in pair} == {0, 1}
                for pair in pairs.values()
            ),
            "Reciprocal pair accounting failed",
        )
        for stage in STAGES:
            detail = {
                "correct": sum(row[stage]["correct"] for row in selected),
                "ties": sum(row[stage]["prediction"] is None for row in selected),
                "label_correct": {},
                "reciprocal_pairs": {
                    "total": len(pairs),
                    "both_correct": sum(
                        all(r[stage]["correct"] for r in pair) for pair in pairs.values()
                    ),
                },
            }
            for label, name in ((0, "no"), (1, "yes")):
                labeled = [r for r in selected if r["target_label"] == label]
                correct = sum(row[stage]["correct"] for row in labeled)
                detail["label_correct"][name] = {
                    "correct": correct,
                    "total": len(labeled),
                    "recall": correct / len(labeled) if labeled else None,
                }
            if stage != "lowercase":
                for name, accessor in (
                    ("mean_total_probability", lambda r: r[stage]["total_probability"]),
                    (
                        "mean_correct_class_probability",
                        lambda r: r[stage]["probabilities"][r["target_label"]],
                    ),
                    (
                        "mean_correct_class_conditional_probability",
                        lambda r: r[stage]["conditional_probabilities"][r["target_label"]],
                    ),
                ):
                    detail[name] = math.fsum(accessor(row) for row in selected) / len(selected)
            cell["stages"][stage] = detail
        cell["transitions"] = {}
        for after, before in (
            ("alias_start", "lowercase"),
            ("completion", "lowercase"),
            ("completion", "alias_start"),
        ):
            rescued = sum(r[after]["correct"] and not r[before]["correct"] for r in selected)
            regressed = sum(r[before]["correct"] and not r[after]["correct"] for r in selected)
            cell["transitions"][f"{after}_vs_{before}"] = {
                "rescued": rescued,
                "regressed": regressed,
                "net_correct_change": rescued - regressed,
                "prediction_changed": sum(
                    r[after]["prediction"] != r[before]["prediction"] for r in selected
                ),
            }
        output.append(cell)
    return output


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Require the complete 36-case by 2-renderer by 2-information fixed panel."""
    _require(isinstance(rows, list) and len(rows) == 144, "Prompt-row denominator must be 144")
    derived = [analyze_row(row) for row in rows]
    cases, keys = {}, set()
    invariant = tuple(name for name in METADATA if name not in ("renderer", "information"))
    for row in derived:
        key = (row["case_id"], row["renderer"], row["information"])
        _require(key not in keys, "Duplicate prompt cell")
        keys.add(key)
        metadata = {name: row[name] for name in invariant}
        _require(
            row["case_id"] not in cases or cases[row["case_id"]] == metadata,
            "Case metadata changed across prompt conditions",
        )
        cases[row["case_id"]] = metadata
    _require(len(cases) == 36, "Case denominator must be 36")
    _require(
        keys == set(itertools.product(cases, RENDERERS, INFORMATION)), "Incomplete prompt grid"
    )
    _require(sum(c["split"] == "exposed" for c in cases.values()) == 4, "Exposed denominator")
    _require(
        sum(c["split"] == "confirmation" for c in cases.values()) == 32,
        "Original confirmation denominator",
    )
    _require(
        all((c["split"] == "exposed") == (c["view"] == "historical") for c in cases.values()),
        "Historical/exposed case membership drift",
    )
    confirmation = [c for c in cases.values() if c["split"] == "confirmation"]
    _require(len({c["family_id"] for c in confirmation}) == 8, "Confirmation family denominator")
    for view, wording in itertools.product(("atomic", "full_chain"), ("ranked_above", "outrank")):
        labels = [
            c["target_label"] for c in confirmation if c["view"] == view and c["wording"] == wording
        ]
        _require(len(labels) == 8 and sum(labels) == 4, "Confirmation balance/grid drift")
    return {
        "format": "v15-completion-mass-summary-v1",
        "claim_ceiling": CLAIM_CEILING,
        "panel_status": "all_cases_exposed_before_this_posthoc_diagnostic",
        "denominators": {
            "cases": 36,
            "prompt_rows": 144,
            "unique_answer_token_paths": sum(r["alias_token_paths"] for r in derived),
        },
        "rows": derived,
        "cells": _group(derived, ("renderer", "information", "split", "view", "wording")),
        "by_renderer_information_split_view": _group(
            derived, ("renderer", "information", "split", "view")
        ),
        "by_renderer_information_split": _group(derived, ("renderer", "information", "split")),
        "overall": _group(derived, ())[0],
    }
