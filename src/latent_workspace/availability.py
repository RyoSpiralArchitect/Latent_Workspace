"""Availability endpoint: does a memory edit flip only the answers it should?

Lane A's endpoint as frozen for V16-V19, route-agnostic: any route that gives
two candidate scores (" no", " yes") per question and memory is read the same
way. ``choice`` and ``contrast`` follow V16's comparison evaluation
(``v16_comparison_eval.py``), ``diagnose`` V19's pre-registered endpoint
(``run_v19_frozen_diagnostic.py``) without its wording tables, and
``norm_matched_random`` V16's random-memory control. Their tests recompute
V19's recorded contrasts and diagnosis from its saved scores exactly
(``test_availability_reproduces_v19``).
"""

from __future__ import annotations

import torch

from .stats import binomial_upper

FACTORS = {
    "actual": ("intact", "twin"),
    "reversed": ("reverse_intact", "reverse_twin"),
    "random_pair": ("random_intact", "random_twin"),
    "same_memory": ("intact", "intact"),
}
VERDICTS = ("CONTENT_REACHES_ANSWERS", "DIRECTIONAL_ONLY", "NOT_ESTABLISHED")


def choice(scores):
    """The published choice from (no, yes) scores: gap = yes - no in FP64; a tie is None."""
    values = [float(value) for value in scores]
    if len(values) != 2:
        raise ValueError("Two candidate scores required")
    gap = values[1] - values[0]
    return {"scores": values, "gap": gap, "prediction": None if gap == 0 else int(gap > 0)}


def contrast(world, query, factor, labels, left, right):
    """One (question, factor) record from two ``choice`` results (left, then right memory)."""
    labels = [int(label) for label in labels]
    affected = labels[0] != labels[1]
    change = right["gap"] - left["gap"]
    return {
        "world": world,
        "query": query,
        "factor": factor,
        "affected": affected,
        "labels": labels,
        "gap_change": change,
        "donor_directed_gap_change": (2 * labels[1] - 1) * change if affected else None,
        "left_prediction": left["prediction"],
        "right_prediction": right["prediction"],
    }


def contrasts(questions, read, factors):
    """Contrast records for ``questions`` (dicts with world, query and labels).

    ``read(condition)`` returns that condition's (no, yes) scores in question order;
    ``factors`` names entries of ``FACTORS``.
    """
    choices, records = {}, []
    for factor in factors:
        left, right = FACTORS[factor]
        for name in (left, right):
            if name not in choices:
                choices[name] = [choice(scores) for scores in read(name)]
        for index, row in enumerate(questions):
            records.append(
                contrast(
                    row["world"],
                    row["query"],
                    factor,
                    row["labels"],
                    choices[left][index],
                    choices[right][index],
                )
            )
    return records


def diagnose(contrasts, rule):
    """V19's memory-content endpoint over ``contrasts``.

    A flip is an affected question answered with the left label under the left
    memory and the right label under the right one. The sign test is one-sided and
    exact over worlds, on the summed donor-directed gap change of ``actual``.
    ``rule`` names ``chance_control``, ``sign_test_alpha``, ``minimum_actual_flips``
    and ``minimum_flip_margin_over_random``.
    """
    by_key = {(c["world"], c["query"], c["factor"]): c for c in contrasts}
    affected = sorted({(c["world"], c["query"]) for c in contrasts if c["affected"]})

    def flipped(factor):
        result = []
        for world, query in affected:
            row = by_key[world, query, factor]
            labels = row["labels"]
            if row["left_prediction"] == labels[0] and row["right_prediction"] == labels[1]:
                result.append([world, query])
        return result

    flips = {factor: flipped(factor) for factor in sorted({c["factor"] for c in contrasts})}
    sums = {}
    for world, query in affected:
        change = by_key[world, query, "actual"]["donor_directed_gap_change"]
        sums[world] = sums.get(world, 0.0) + change
    positive = sum(v > 0 for v in sums.values())
    negative = sum(v < 0 for v in sums.values())
    p_value = binomial_upper(positive, positive + negative)
    actual, chance = len(flips["actual"]), len(flips[rule["chance_control"]])
    sign = p_value <= rule["sign_test_alpha"]
    if (
        sign
        and actual >= rule["minimum_actual_flips"]
        and actual - chance >= rule["minimum_flip_margin_over_random"]
    ):
        verdict = VERDICTS[0]
    elif sign:
        verdict = VERDICTS[1]
    else:
        verdict = VERDICTS[2]
    unaffected = [c for c in contrasts if c["factor"] == "actual" and not c["affected"]]
    return {
        "affected_queries": len(affected),
        "worlds": len(sums),
        "flips": {factor: len(rows) for factor, rows in flips.items()},
        "actual_flip_queries": flips["actual"],
        "world_sign": {
            "positive": positive,
            "negative": negative,
            "zero": len(sums) - positive - negative,
        },
        "sign_test_p": p_value,
        "sign_test_passes": sign,
        "flip_margin_over_chance": actual - chance,
        "unaffected_prediction_changes": sum(
            c["left_prediction"] != c["right_prediction"] for c in unaffected
        ),
        "verdict": verdict,
    }


def norm_matched_random(memory, mask, generator):
    """V16's control: Gaussian states on the valid positions, scaled to the memory's
    total norm there. Norm-matched, but neither semantic nor distribution-matched."""
    valid = mask.bool().unsqueeze(-1)
    random = torch.randn(memory.shape, generator=generator, device="cpu").to(memory.device)
    random = random.masked_fill(~valid, 0)
    return random * (memory.masked_fill(~valid, 0).norm() / random.norm().clamp_min(1e-12))
