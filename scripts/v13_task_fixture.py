#!/usr/bin/env python3
"""Small text-only S0 falsification fixtures, not a qualified training/test corpus.

Every family has one original world/query and two alternate edits, one affecting
the answer and one preserving it. Both query directions are retained. Counts and
width here are engineering bounds, not frozen scientific sample sizes.
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

FORMAT = "latent-workspace-v13-s0-fixture-record-v1"
SCOPE = "S0_FALSIFICATION_FIXTURE_ONLY"
WIDTH = 8
MAX_FAMILIES = 64
HEADER = "World facts. The ranking is transitive."
NAMES = (
    "Aster",
    "Beryl",
    "Cyra",
    "Doran",
    "Eris",
    "Fenn",
    "Galen",
    "Hira",
    "Ione",
    "Joren",
    "Kestrel",
    "Luma",
    "Mira",
    "Neris",
    "Orin",
    "Pavo",
)
TEMPLATES = {
    "ranked_above": "Is {left} ranked above {right}? Answer:",
    "outrank": "Does {left} outrank {right}? Answer:",
}
FACT = re.compile(r"- ([A-Za-z][A-Za-z0-9_]*) is ranked above ([A-Za-z][A-Za-z0-9_]*)\.")
QUERY = re.compile(
    r"(?:Is ([A-Za-z][A-Za-z0-9_]*) ranked above ([A-Za-z][A-Za-z0-9_]*)"
    r"|Does ([A-Za-z][A-Za-z0-9_]*) outrank ([A-Za-z][A-Za-z0-9_]*))\? Answer:"
)


class FixtureError(ValueError):
    """A fixture or parsed relation violates its explicit contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FixtureError(message)


def _parse_context(context: str) -> tuple[list[str], list[tuple[str, str]]]:
    _require(isinstance(context, str), "context must be a string")
    lines = context.splitlines()
    _require(bool(lines) and lines[0] == HEADER, "unexpected context header")
    edges: list[tuple[str, str]] = []
    for line in lines[1:]:
        match = FACT.fullmatch(line)
        _require(match is not None, "unparsed fact line")
        assert match is not None
        edges.append((match[1], match[2]))
    _require(bool(edges) and len(set(edges)) == len(edges), "missing or duplicate facts")
    nodes = set(itertools.chain.from_iterable(edges))
    successors: dict[str, str] = {}
    predecessors: dict[str, str] = {}
    for left, right in edges:
        _require(left != right, "self edge")
        _require(left not in successors and right not in predecessors, "branched ranking")
        successors[left], predecessors[right] = right, left
    starts = nodes - predecessors.keys()
    _require(len(starts) == 1, "ranking needs one root")
    order: list[str] = []
    current = next(iter(starts))
    while True:
        _require(current not in order, "cyclic ranking")
        order.append(current)
        if current not in successors:
            break
        current = successors[current]
    _require(set(order) == nodes and len(edges) == len(nodes) - 1, "disconnected ranking")
    return order, edges


def _parse_query(query: str) -> tuple[str, str]:
    _require(isinstance(query, str), "query must be a string")
    match = QUERY.fullmatch(query)
    _require(match is not None, "unparsed query")
    assert match is not None
    left, right = (match[1], match[2]) if match[1] else (match[3], match[4])
    _require(left != right, "query entities must differ")
    return left, right


def symbolic_oracle(context: str, query: str) -> int:
    """Answer using only parsed text and directed path traversal, never metadata."""
    order, edges = _parse_context(context)
    left, right = _parse_query(query)
    _require(left in order and right in order, "query entity missing from world")
    successors = dict(edges)
    current = left
    while current in successors:
        current = successors[current]
        if current == right:
            return 1
    return 0


def _render(order: Sequence[str], positions: Sequence[int]) -> str:
    return (
        HEADER
        + "\n"
        + "\n".join(f"- {order[i]} is ranked above {order[i + 1]}." for i in positions)
    )


def _swapped(order: Sequence[str], positions: tuple[int, int]) -> list[str]:
    result = list(order)
    left, right = positions
    result[left], result[right] = result[right], result[left]
    return result


def _eligible_edits(
    order: Sequence[str], query_pair: tuple[str, str]
) -> dict[int, dict[bool, list[tuple[int, int]]]]:
    left, right = query_pair
    original_hop = abs(order.index(left) - order.index(right))
    original_answer = order.index(left) < order.index(right)
    candidates: dict[int, dict[bool, list[tuple[int, int]]]] = {}
    for first, second in itertools.combinations(range(1, len(order) - 1), 2):
        if second - first < 2:
            continue
        donor = _swapped(order, (first, second))
        left_pos, right_pos = donor.index(left), donor.index(right)
        if abs(left_pos - right_pos) != original_hop:
            continue
        affected = (left_pos < right_pos) != original_answer
        group = candidates.setdefault(second - first, {False: [], True: []})
        group[affected].append((first, second))
    return {distance: group for distance, group in candidates.items() if all(group.values())}


def generate_fixture(seed: int, families: int) -> list[dict[str, Any]]:
    """Return two serializable paired-world records per original-world family.

    Original order/query are sampled before candidate donor edits are examined.
    Rejection only enforces paired eligibility. Query distance and transposition
    distance are exactly matched across affected/unaffected edits in this fixture.
    """
    _require(type(seed) is int, "seed must be an integer, not bool")
    _require(type(families) is int and 1 <= families <= MAX_FAMILIES, "invalid family count")
    rng = random.Random(seed)
    records: list[dict[str, Any]] = []
    query_positions = [
        pair for pair in itertools.combinations(range(1, WIDTH - 1), 2) if pair[1] - pair[0] >= 2
    ]
    for family_index in range(families):
        original = rng.sample(NAMES, WIDTH)
        rejected = 0
        for _attempt in range(128):
            first, second = rng.choice(query_positions)
            query_pair = (original[first], original[second])
            candidates = _eligible_edits(original, query_pair)
            if candidates:
                break
            rejected += 1
        else:
            raise FixtureError("bounded paired-query eligibility search exhausted")
        edit_distance = rng.choice(sorted(candidates))
        positions = list(range(WIDTH - 1))
        rng.shuffle(positions)
        template_name = rng.choice(sorted(TEMPLATES))
        pairs = [query_pair, query_pair[::-1]]
        rng.shuffle(pairs)
        queries = [TEMPLATES[template_name].format(left=a, right=b) for a, b in pairs]
        family_id = f"v13-s0-seed{seed}-family{family_index:04d}"
        variants = [True, False]
        rng.shuffle(variants)
        for affected in variants:
            edit = rng.choice(candidates[edit_distance][affected])
            donor = _swapped(original, edit)
            contexts = [_render(original, positions), _render(donor, positions)]
            variant = "affected" if affected else "unaffected"
            records.append(
                {
                    "format": FORMAT,
                    "scope": SCOPE,
                    "seed": seed,
                    "family_id": family_id,
                    "pair_id": f"{family_id}:{variant}",
                    "variant": variant,
                    "contexts": contexts,
                    "queries": list(queries),
                    "choices": [" no", " yes"],
                    "answers": [[symbolic_oracle(c, q) for q in queries] for c in contexts],
                    "affected": [affected, affected],
                    "hop_distances": [
                        [abs(order.index(a) - order.index(b)) for a, b in pairs]
                        for order in (original, donor)
                    ],
                    "metadata": {
                        "family_index": family_index,
                        "original_order": list(original),
                        "donor_order": donor,
                        "edit_type": "internal_nonadjacent_transposition",
                        "swapped_positions": list(edit),
                        "edit_distance": edit_distance,
                        "fact_position_order": list(positions),
                        "template": template_name,
                        "eligibility_rejected_queries": rejected,
                    },
                }
            )
    audit = validate_fixture(records)
    _require(audit["passed"], f"generated fixture failed validation: {audit['errors']}")
    return records


def _validate_record(record: Mapping[str, Any]) -> None:
    _require(record.get("format") == FORMAT and record.get("scope") == SCOPE, "wrong scope")
    _require(type(record.get("seed")) is int, "invalid seed")
    variant = record.get("variant")
    _require(variant in {"affected", "unaffected"}, "invalid variant")
    metadata = record.get("metadata")
    _require(isinstance(metadata, dict), "missing metadata")
    assert isinstance(metadata, dict)
    family_index = metadata.get("family_index")
    _require(type(family_index) is int and family_index >= 0, "invalid family index")
    family_id = f"v13-s0-seed{record['seed']}-family{family_index:04d}"
    _require(record.get("family_id") == family_id, "family identity mismatch")
    _require(record.get("pair_id") == f"{family_id}:{variant}", "pair identity mismatch")
    _require(record.get("choices") == [" no", " yes"], "unexpected choices")
    contexts, queries = record.get("contexts"), record.get("queries")
    _require(isinstance(contexts, list) and len(contexts) == 2, "need two contexts")
    _require(isinstance(queries, list) and len(queries) == 2, "need bidirectional queries")
    assert isinstance(contexts, list) and isinstance(queries, list)
    pairs = [_parse_query(query) for query in queries]
    _require(pairs[0] == pairs[1][::-1], "queries are not reverse directions")
    orders = [_parse_context(context)[0] for context in contexts]
    _require(all(len(order) == WIDTH for order in orders), "incorrect fixture width")
    _require(set(orders[0]) == set(orders[1]), "twins use different entities")
    _require(metadata.get("original_order") == orders[0], "declared original order false")
    _require(metadata.get("donor_order") == orders[1], "declared donor order false")
    edit = metadata.get("swapped_positions")
    _require(
        isinstance(edit, list) and len(edit) == 2 and all(type(i) is int for i in edit),
        "invalid edit positions",
    )
    assert isinstance(edit, list)
    _require(1 <= edit[0] < edit[1] <= WIDTH - 2 and edit[1] - edit[0] >= 2, "invalid edit")
    _require(metadata.get("edit_type") == "internal_nonadjacent_transposition", "wrong edit type")
    _require(orders[1] == _swapped(orders[0], tuple(edit)), "not the declared transposition")
    _require(
        type(metadata.get("edit_distance")) is int
        and metadata["edit_distance"] == edit[1] - edit[0],
        "edit distance mismatch",
    )
    presentation = metadata.get("fact_position_order")
    _require(
        isinstance(presentation, list)
        and all(type(i) is int for i in presentation)
        and sorted(presentation) == list(range(WIDTH - 1)),
        "invalid fact presentation",
    )
    assert isinstance(presentation, list)
    _require(
        contexts == [_render(order, presentation) for order in orders],
        "twins do not share the declared fact-position order",
    )
    template = metadata.get("template")
    _require(template in TEMPLATES, "unrecognized template")
    _require(
        queries == [TEMPLATES[template].format(left=a, right=b) for a, b in pairs],
        "query template metadata mismatch",
    )
    hops = []
    for order in orders:
        side_hops = []
        for left, right in pairs:
            _require(left in order and right in order, "query entity missing")
            first, second = order.index(left), order.index(right)
            _require(0 < first < WIDTH - 1 and 0 < second < WIDTH - 1, "endpoint query")
            _require(abs(first - second) >= 2, "adjacent query")
            side_hops.append(abs(first - second))
        hops.append(side_hops)
    declared_hops = record.get("hop_distances")
    _require(
        isinstance(declared_hops, list)
        and len(declared_hops) == 2
        and all(isinstance(row, list) and all(type(x) is int for x in row) for row in declared_hops)
        and declared_hops == hops,
        "hop metadata mismatch",
    )
    _require(hops[0] == hops[1], "fixture must match hop across world sides")
    answers = record.get("answers")
    recomputed = [[symbolic_oracle(c, q) for q in queries] for c in contexts]
    _require(
        isinstance(answers, list)
        and len(answers) == 2
        and all(
            isinstance(row, list) and all(type(x) is int and x in (0, 1) for x in row)
            for row in answers
        )
        and answers == recomputed,
        "answer/path mismatch",
    )
    affected = record.get("affected")
    derived = [a != b for a, b in zip(recomputed[0], recomputed[1], strict=True)]
    _require(
        isinstance(affected, list)
        and all(type(x) is bool for x in affected)
        and affected == derived == [variant == "affected"] * 2,
        "affected metadata mismatch",
    )
    _require(
        type(metadata.get("eligibility_rejected_queries")) is int
        and metadata["eligibility_rejected_queries"] >= 0,
        "invalid rejection count",
    )


def _direct_edge_endpoint(context: str, query: str) -> int | None:
    order, edges = _parse_context(context)
    left, right = _parse_query(query)
    if (left, right) in edges:
        return 1
    if (right, left) in edges:
        return 0
    if left == order[0] or right == order[-1]:
        return 1
    if right == order[0] or left == order[-1]:
        return 0
    return None


def _probe_summary(predictions: list[int | None], labels: list[int]) -> dict[str, Any]:
    answered = sum(prediction is not None for prediction in predictions)
    correct = sum(p == y for p, y in zip(predictions, labels, strict=True))
    return {
        "cases": len(labels),
        "answered": answered,
        "abstentions": len(labels) - answered,
        "correct": correct,
        "coverage": answered / len(labels),
        "correct_fraction_all_cases": correct / len(labels),
        "accuracy_answered": correct / answered if answered else None,
    }


def _shortcut_probes(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    cases = [
        (context, query, record["answers"][side][i], i)
        for record in records
        for side, context in enumerate(record["contexts"])
        for i, query in enumerate(record["queries"])
    ]
    labels = [case[2] for case in cases]
    direct = [_direct_edge_endpoint(context, query) for context, query, _, _ in cases]
    internal_inversion: list[int] = []
    for (context, query, _, _), direct_prediction in zip(cases, direct, strict=True):
        order, _edges = _parse_context(context)
        left, right = _parse_query(query)
        internal = left not in (order[0], order[-1]) and right not in (order[0], order[-1])
        prediction = 0 if direct_prediction is None else direct_prediction
        internal_inversion.append(1 - prediction if internal else prediction)
    query_counts: dict[str, Counter[int]] = defaultdict(Counter)
    position_counts: dict[int, Counter[int]] = defaultdict(Counter)
    for _, query, target, position in cases:
        query_counts[query][target] += 1
        position_counts[position][target] += 1

    def majority(counts: Counter[int]) -> int:
        return int(counts[1] > counts[0])

    return {
        "scope": "TEXT_ONLY_FIXTURE_DIAGNOSTICS_NOT_MODEL_CAPABILITY",
        "symbolic_path_oracle": _probe_summary(
            [symbolic_oracle(context, query) for context, query, _, _ in cases],
            labels,
        ),
        "direct_edge_endpoint_abstaining": _probe_summary(direct, labels),
        "direct_edge_endpoint_fallback_no": _probe_summary(
            [0 if p is None else p for p in direct],
            labels,
        ),
        "query_only_constant_no": _probe_summary([0] * len(labels), labels),
        "query_only_constant_yes": _probe_summary([1] * len(labels), labels),
        "memory_blind_internal_inversion_fallback_no": _probe_summary(
            internal_inversion,
            labels,
        ),
        "query_text_in_sample_majority": _probe_summary(
            [majority(query_counts[query]) for _, query, _, _ in cases],
            labels,
        ),
        "query_position_in_sample_majority": _probe_summary(
            [majority(position_counts[position]) for _, _, _, position in cases],
            labels,
        ),
        "interpretation": (
            "Internal inversion uses the direct-edge/endpoint rule with explicit no fallback "
            "before inverting internal-node comparisons; it never receives donor memory. "
            "Majority lookup is fitted and scored on the SAME fixture, not a held-out result. "
            "Alternate edits can produce a 3:1 per-query label split. Chance for a named "
            "probe, or abstention by the direct-edge rule, does not rule out other shortcuts."
        ),
    }


def validate_fixture(records: object) -> dict[str, Any]:
    """Return a fail-closed structural/path receipt, never scientific qualification."""
    errors: list[str] = []
    valid: list[Mapping[str, Any]] = []
    families: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    original_families: dict[tuple[str, ...], str] = {}
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_FAMILIES * 2:
        errors.append("records must be a nonempty bounded list")
    else:
        for index, record in enumerate(records):
            try:
                _require(isinstance(record, dict), "record must be an object")
                _validate_record(record)
                valid.append(record)
                families[record["family_id"]].append(record)
            except (FixtureError, KeyError, TypeError, IndexError) as exc:
                errors.append(f"record {index}: {exc}")
    for family_id, group in families.items():
        try:
            _require(len(group) == 2, "family must contain exactly two alternate edits")
            _require({r["variant"] for r in group} == {"affected", "unaffected"}, "missing variant")
            first, second = group
            original_key = tuple(first["metadata"]["original_order"])
            _require(
                original_key not in original_families
                or original_families[original_key] == family_id,
                "same original world assigned to different uncertainty families",
            )
            original_families[original_key] = family_id
            _require(first["contexts"][0] == second["contexts"][0], "original world differs")
            _require(first["queries"] == second["queries"], "original query set differs")
            _require(first["hop_distances"] == second["hop_distances"], "unmatched query hop")
            for key in ("edit_distance", "fact_position_order", "template"):
                _require(first["metadata"][key] == second["metadata"][key], f"unmatched {key}")
        except FixtureError as exc:
            errors.append(f"family {family_id}: {exc}")
    return {
        "format": "latent-workspace-v13-s0-fixture-validation-v1",
        "scope": SCOPE,
        "passed": not errors,
        "errors": errors,
        "records": len(records) if isinstance(records, list) else 0,
        "valid_records": len(valid),
        "families": len(families),
        "cases": len(valid) * 4,
        "uncertainty_unit": "ORIGINAL_WORLD_ALTERNATE_EDIT_FAMILY",
        "qualified_corpus": False,
        "model_capability_assessed": False,
        "training_or_split_freeze": False,
        "shortcut_probes": _shortcut_probes(valid) if valid and not errors else None,
        "claim_boundary": (
            "PASS verifies only this bounded synthetic fixture's paired text and path semantics. "
            "It does not qualify a corpus, a reader, model capability, or causal workspace use."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--families", type=int, default=4)
    parser.add_argument("--include-records", action="store_true")
    args = parser.parse_args()
    try:
        records = generate_fixture(args.seed, args.families)
        report = validate_fixture(records)
        if args.include_records:
            report["fixture_records"] = records
        print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
        return 0
    except FixtureError as exc:
        print(json.dumps({"scope": SCOPE, "passed": False, "errors": [str(exc)]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
