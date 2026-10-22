"""Group-aware, missingness-preserving workspace capability comparisons.

This is a reducer, NOT a correctness judge or a proof of general intelligence.
Callers freeze route-specific inputs/oracles and supply independently replayed
strict binary scores. Unparsed/wrong/capped answers are not erased as missing;
use the predeclared task scorer. Invalid means unusable execution evidence.
"""

from __future__ import annotations

from collections import defaultdict

from . import execution as ex

MODELS = ("original", "candidate")
ROUTES = ("no_memory", "inline", "workspace")


def _sha(value):
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _mean_groups(values, units):
    groups = defaultdict(list)
    for uid, delta in values.items():
        groups[units[uid]["group_id"]].append(delta)
    means = {g: sum(ds) / len(ds) for g, ds in sorted(groups.items())}
    return dict(
        paired_units=len(values),
        paired_groups=len(groups),
        group_means=means,
        group_macro_mean=sum(means.values()) / len(means) if means else None,
        unit_mean=sum(values.values()) / len(values) if values else None,
    )


def summarize(units, observations):
    """Six cells per unit, fixed IDs/hashes; no silent intersection denominators.

    Each unit declares group/domain/condition and three route-input hashes. A
    route hash MUST include exact input tokens, tokenizer identity and scorer
    contract (including that route's oracle). Both model arms use that hash.
    An oracle for a no-memory abstention task can differ from an informed task.
    The caller, not this reducer, is responsible for verifying those semantics.

    The descriptive interaction is (candidate workspace - candidate inline)
    minus (original workspace - original inline). It is not a significance test
    or a pure compute-matched causal effect: route arithmetic/positions differ.
    """
    declared = {}
    for unit in units:
        ex.require(
            set(unit) == {"id", "group_id", "domain", "condition", "route_sha256"},
            "Exact workspace-improvement unit contract",
        )
        ex.require(
            all(
                type(unit[k]) is str and bool(unit[k])
                for k in ("id", "group_id", "domain", "condition")
            ),
            "Nonempty unit/group/domain/condition",
        )
        ex.require(unit["id"] not in declared, "Duplicate declared unit")
        ex.require(
            set(unit["route_sha256"]) == set(ROUTES)
            and all(_sha(h) for h in unit["route_sha256"].values()),
            "All route input/scorer hashes required",
        )
        declared[unit["id"]] = unit
    ex.require(declared, "Nonempty frozen workspace-improvement panel")
    rows = {}
    for row in observations:
        ex.require(
            set(row) == {"id", "model", "route", "route_sha256", "status", "correct", "reason"},
            "Exact observation contract",
        )
        uid, model, route = row["id"], row["model"], row["route"]
        key = (uid, model, route)
        ex.require(uid in declared and model in MODELS and route in ROUTES, "Unplanned observation")
        ex.require(key not in rows, "Duplicate observation")
        ex.require(
            row["route_sha256"] == declared[uid]["route_sha256"][route], "Route input/scorer hash"
        )
        ex.require(
            (row["status"] == "valid" and type(row["correct"]) is bool and row["reason"] is None)
            or (
                row["status"] == "invalid"
                and row["correct"] is None
                and type(row["reason"]) is str
                and bool(row["reason"])
            ),
            "Explicit valid score or invalid reason; invalid is not false",
        )
        rows[key] = row

    def score(uid, model, route):
        row = rows.get((uid, model, route))
        return None if row is None or row["status"] != "valid" else int(row["correct"])

    def subset(selected):
        cells, paired = {}, {}
        for route in ROUTES:
            for model in MODELS:
                present = [rows[(u, model, route)] for u in selected if (u, model, route) in rows]
                valid = [r for r in present if r["status"] == "valid"]
                cells[f"{model}/{route}"] = dict(
                    planned=len(selected),
                    observed=len(present),
                    valid=len(valid),
                    invalid=len(present) - len(valid),
                    missing=len(selected) - len(present),
                    correct=sum(r["correct"] for r in valid),
                    accuracy_valid=sum(r["correct"] for r in valid) / len(valid) if valid else None,
                )
            both, repairs, losses = {}, 0, 0
            for uid in selected:
                a, b = score(uid, "original", route), score(uid, "candidate", route)
                if a is not None and b is not None:
                    both[uid] = b - a
                    repairs += a == 0 and b == 1
                    losses += a == 1 and b == 0
            paired[route] = dict(
                planned_units=len(selected),
                unpaired_units=len(selected) - len(both),
                repairs=repairs,
                losses=losses,
                **_mean_groups(both, declared),
            )
        contrasts = {}
        for uid in selected:
            a, b, c, d = (
                score(uid, m, r)
                for m, r in (
                    ("original", "inline"),
                    ("original", "workspace"),
                    ("candidate", "inline"),
                    ("candidate", "workspace"),
                )
            )
            if all(v is not None for v in (a, b, c, d)):
                contrasts[uid] = (d - c) - (b - a)
        return dict(
            planned_units=len(selected),
            planned_groups=len({declared[u]["group_id"] for u in selected}),
            cells=cells,
            candidate_minus_original=paired,
            workspace_interaction=dict(
                planned_units=len(selected),
                unpaired_units=len(selected) - len(contrasts),
                **_mean_groups(contrasts, declared),
            ),
        )

    incomplete = len(rows) != len(declared) * 6 or any(
        r["status"] != "valid" for r in rows.values()
    )
    return dict(
        schema="ltws-workspace-improvement-summary-v1",
        panel_sha256=ex.plan_hash(sorted(units, key=lambda u: u["id"])),
        status="INCOMPLETE_NOT_NON_REGRESSION" if incomplete else "COMPLETE_NOT_NON_REGRESSION",
        overall=subset(sorted(declared)),
        strata={
            axis: {
                value: subset(sorted(u for u in declared if declared[u][axis] == value))
                for value in sorted({u[axis] for u in declared.values()})
            }
            for axis in ("domain", "condition")
        },
        invalidities=[
            dict(id=u, model=m, route=r, reason=rows[u, m, r]["reason"])
            for u, m, r in sorted(rows)
            if rows[u, m, r]["status"] == "invalid"
        ],
        missing=[
            dict(id=u, model=m, route=r)
            for u in sorted(declared)
            for m in MODELS
            for r in ROUTES
            if (u, m, r) not in rows
        ],
        claim="Descriptive strict-score contrasts; no non-regression, generality or release gate",
    )
