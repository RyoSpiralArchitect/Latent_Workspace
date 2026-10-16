"""Exact paired statistics for pre-registered endpoints.

Promoted verbatim from ``v20_deliberation.py`` in ``latent_workspace_ft_v10`` at
``d4cd1ee0340a``. The historical files are frozen; this module is the living home
(docs/ARCHITECTURE.md). Parity: ``test_statistics_are_the_historical_statistics``.
"""

from __future__ import annotations

import math


def correct_flags(adapted, targets):
    """Strict: the target candidate's logit must exceed the other one."""
    return [bool(row[t] > row[1 - t]) for row, t in zip(adapted, targets, strict=True)]


def binomial_upper(k, n):
    return sum(math.comb(n, i) for i in range(k, n + 1)) / 2**n if n else 1.0


def world_sign(left, right, worlds):
    """One-sided sign test that ``left`` beats ``right`` across worlds."""
    totals = {}
    for a, b, w in zip(left, right, worlds, strict=True):
        totals[w] = totals.get(w, 0) + int(a) - int(b)
    positive = sum(v > 0 for v in totals.values())
    negative = sum(v < 0 for v in totals.values())
    return {
        "positive": positive,
        "negative": negative,
        "zero": len(totals) - positive - negative,
        "p_one_sided": binomial_upper(positive, positive + negative),
    }


def gain(left, right, worlds, rule):
    rows = len(left)
    difference = (sum(left) - sum(right)) / rows
    sign = world_sign(left, right, worlds)
    passed = difference >= rule["minimum_accuracy_gain"] and sign["p_one_sided"] <= rule["alpha"]
    return {"accuracy_gain": difference, "world_sign": sign, "passed": passed}


def verdict(route_gains, step_gains, labels):
    """``route_gains``/``step_gains``: per-seed ``gain`` results for k4 vs base and k4 vs k1."""
    if all(g["passed"] for g in route_gains) and all(g["passed"] for g in step_gains):
        return labels[0]
    if all(g["passed"] for g in route_gains):
        return labels[1]
    return labels[2]
