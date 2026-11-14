"""Additive output-order control for the V24 recruitment bank.

This changes only the supervised JSON serialization of train/dev reasoning
rows. The semantic oracle, source record, prompt, memory and native learner are
unchanged. It is an order/leakage control, not a new latent workspace state.
"""

from __future__ import annotations

import copy
import json

from . import execution as ex
from . import recruitment_bank as bank

ORDERS = ("answer_first", "steps_first")


def serialized_answer(row, order):
    """Return one strictly checked target without altering the source row."""
    ex.require(order in ORDERS, "Known target order")
    oracle = row["oracle"]
    ex.require(row["answer"] == ex.canonical(oracle), "Original source reference intact")
    if order == "answer_first" or row["role"] != "reasoning" or "steps" not in oracle:
        return row["answer"]
    ex.require(set(oracle) == {"steps", "answer"}, "Complete reasoning oracle")
    return json.dumps(
        {"steps": oracle["steps"], "answer": oracle["answer"]},
        separators=(",", ":"),
        allow_nan=False,
    )


def project_pair(raw, tokenizer, order):
    """Project both input routes with identical semantic cases and target IDs."""
    ex.require(order in ORDERS, "Known target order")
    reasoning = [row for row in raw if row["role"] == "reasoning"]
    bank.audit(reasoning)
    projected_source = copy.deepcopy(raw)
    for row in projected_source:
        if row["role"] == "reasoning" and row["split"] in ("train", "dev"):
            row["answer"] = serialized_answer(row, order)
    routes = {route: bank.project(projected_source, tokenizer, route) for route in bank.ROUTES}
    bank.match_routes(routes["inline"], routes["workspace"])
    return routes
