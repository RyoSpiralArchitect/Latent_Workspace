#!/usr/bin/env python3
"""Fixed structural candidates for a V14 instrument/elicitation screen, not training."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HELPER_PATH = Path(__file__).with_name("v13_task_fixture.py")
_SPEC = importlib.util.spec_from_file_location("_v14_historical_fixture", HELPER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_HELPER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_HELPER)
symbolic_oracle = _HELPER.symbolic_oracle

SEED = 1402
SPLITS = ("calibration", "holdout")
HOPS = (2, 3, 4)
FAMILIES_PER_HOP = 4
SCOPE = "STRUCTURAL_CANDIDATES_AND_CALIBRATION_SCREEN_ONLY"
WIDTH = _HELPER.WIDTH
TEMPLATES = _HELPER.TEMPLATES
CorpusError = _HELPER.FixtureError
_require = _HELPER._require


def _record(
    *,
    split: str,
    family_index: int,
    hop: int,
    original: list[str],
    hard_query: tuple[str, str],
    query_pair: tuple[str, str],
    presentation: list[int],
    template: str,
    role: str,
    orientation: str,
    variant: str,
    edit: tuple[int, int] | None,
) -> dict[str, Any]:
    family_id = f"v14-instrument-seed{SEED}-{split}-family{family_index:02d}"
    if role == "primary":
        assert edit is not None
        donor = _HELPER._swapped(original, edit)
        orders = [original, donor]
        actual_edit = list(edit)
        if orientation == "reversed":
            orders = [list(reversed(order)) for order in orders]
            actual_edit = [WIDTH - 1 - edit[1], WIDTH - 1 - edit[0]]
    else:
        orders = [original, list(reversed(original))]
        actual_edit = None
    contexts = [_HELPER._render(order, presentation) for order in orders]
    pairs = [query_pair, query_pair[::-1]]
    queries = [TEMPLATES[template].format(left=a, right=b) for a, b in pairs]
    answers = [[symbolic_oracle(c, q) for q in queries] for c in contexts]
    side_hops = [[abs(o.index(a) - o.index(b)) for a, b in pairs] for o in orders]
    return {
        "format": "functional_world_pair",
        "id": f"{family_id}:{role}:{variant}:{orientation}:{template}",
        "pair_id": f"{family_id}:{role}:{variant}:{orientation}:{template}",
        "contexts": contexts,
        "queries": queries,
        "choices": [" no", " yes"],
        "answers": answers,
        "affected": [a != b for a, b in zip(*answers, strict=True)],
        "hop_distances": side_hops[0],
        "heldout_queries": [False, False],
        "metadata": {
            "scope": SCOPE,
            "seed": SEED,
            "split": split,
            "family_id": family_id,
            "family_index": family_index,
            "primary_hop": hop,
            "role": role,
            "template": template,
            "alternate_wording": template == "outrank",
            "wording_held_out_from_training": False,
            "orientation": orientation,
            "variant": variant,
            "causal_edit_claim": role == "primary",
            "edit_type": (
                "internal_nonadjacent_transposition"
                if role == "primary"
                else "global_order_reversal_easy_control"
            ),
            "base_swapped_positions": list(edit) if edit is not None else None,
            "swapped_positions": actual_edit,
            "edit_distance": edit[1] - edit[0] if edit is not None else None,
            "base_original_order": list(original),
            "base_primary_query_entities": list(hard_query),
            "query_entities": list(query_pair),
            "world_orders": orders,
            "side_hop_distances": side_hops,
            "fact_position_order": list(presentation),
        },
    }


def _build_corpus() -> dict[str, list[dict[str, Any]]]:
    rng = random.Random(SEED)
    corpus: dict[str, list[dict[str, Any]]] = {}
    used_worlds: set[tuple[str, ...]] = set()
    for split in SPLITS:
        records = []
        for hop in HOPS:
            for within_hop in range(FAMILIES_PER_HOP):
                family_index = HOPS.index(hop) * FAMILIES_PER_HOP + within_hop
                for _attempt in range(128):
                    original = rng.sample(_HELPER.NAMES, WIDTH)
                    first = rng.choice(list(range(1, WIDTH - 1 - hop)))
                    query_pair = (original[first], original[first + hop])
                    if rng.randrange(2):
                        query_pair = query_pair[::-1]
                    candidates = _HELPER._eligible_edits(original, query_pair)
                    if not candidates:
                        continue
                    distance = rng.choice(sorted(candidates))
                    edits = {
                        affected: rng.choice(candidates[distance][affected])
                        for affected in (False, True)
                    }
                    orders = [original, *[_HELPER._swapped(original, e) for e in edits.values()]]
                    worlds = {tuple(o) for o in orders} | {tuple(reversed(o)) for o in orders}
                    if len(worlds) == 6 and not worlds & used_worlds:
                        used_worlds.update(worlds)
                        break
                else:
                    raise CorpusError("bounded independent-family sampling exhausted")
                presentation = list(range(WIDTH - 1))
                rng.shuffle(presentation)
                easy_start = rng.randrange(1, WIDTH - 2)
                easy_pair = (original[easy_start], original[easy_start + 1])
                if rng.randrange(2):
                    easy_pair = easy_pair[::-1]
                common = {
                    "split": split,
                    "family_index": family_index,
                    "hop": hop,
                    "original": original,
                    "hard_query": query_pair,
                    "presentation": presentation,
                }
                for template in sorted(TEMPLATES):
                    for orientation in ("original", "reversed"):
                        for affected in (False, True):
                            records.append(
                                _record(
                                    **common,
                                    template=template,
                                    query_pair=query_pair,
                                    role="primary",
                                    orientation=orientation,
                                    variant="affected" if affected else "unaffected",
                                    edit=edits[affected],
                                )
                            )
                    records.append(
                        _record(
                            **common,
                            template=template,
                            query_pair=easy_pair,
                            role="easy",
                            orientation="original_to_reversed",
                            variant="not_applicable",
                            edit=None,
                        )
                    )
        rng.shuffle(records)
        corpus[split] = records
    return corpus


def generate_corpus() -> dict[str, list[dict[str, Any]]]:
    """Return fixed seed1402 calibration/holdout records; no model or training call."""
    corpus = _build_corpus()
    audit = validate_corpus(corpus)
    _require(audit["passed"], f"generated corpus failed validation: {audit['errors']}")
    return corpus


def _validate_record(record: dict[str, Any], split: str) -> None:
    _require(record.get("format") == "functional_world_pair", "wrong engine format")
    _require(record.get("choices") == [" no", " yes"], "wrong choices")
    _require(record.get("heldout_queries") == [False, False], "false held-out wording claim")
    meta = record["metadata"]
    _require(meta["split"] == split and meta["scope"] == SCOPE, "split/scope mismatch")
    _require(type(meta["seed"]) is int and meta["seed"] == SEED, "seed mismatch")
    role, template = meta["role"], meta["template"]
    _require(role in ("primary", "easy") and template in TEMPLATES, "role/template mismatch")
    contexts, queries = record["contexts"], record["queries"]
    _require(len(contexts) == len(queries) == 2, "pair/query axes must both have size two")
    orders = [_HELPER._parse_context(c)[0] for c in contexts]
    pairs = [_HELPER._parse_query(q) for q in queries]
    _require(pairs[0] == pairs[1][::-1], "missing bidirectional query")
    _require(list(pairs[0]) == meta["query_entities"], "query entities mismatch")
    _require(all(len(o) == WIDTH and set(o) == set(orders[0]) for o in orders), "world nodes")
    _require(orders == meta["world_orders"], "parsed world metadata mismatch")
    presentation = meta["fact_position_order"]
    _require(
        all(type(p) is int for p in presentation)
        and sorted(presentation) == list(range(WIDTH - 1)),
        "fact permutation mismatch",
    )
    _require(
        contexts == [_HELPER._render(o, presentation) for o in orders],
        "twins must share the same fact-order shuffle",
    )
    _require(
        queries == [TEMPLATES[template].format(left=a, right=b) for a, b in pairs],
        "template text mismatch",
    )
    hops = [[abs(o.index(a) - o.index(b)) for a, b in pairs] for o in orders]
    _require(hops[0] == hops[1] == record["hop_distances"], "flat matched hop mismatch")
    _require(hops == meta["side_hop_distances"], "side hop metadata mismatch")
    _require(all(type(h) is int for h in record["hop_distances"]), "hop must be integer")
    for order in orders:
        _require(
            all(
                a not in (order[0], order[-1]) and b not in (order[0], order[-1]) for a, b in pairs
            ),
            "endpoint query is not eligible",
        )
    answers = [[symbolic_oracle(c, q) for q in queries] for c in contexts]
    _require(
        record["answers"] == answers
        and all(type(a) is int for row in record["answers"] for a in row),
        "answer/path mismatch",
    )
    affected = [a != b for a, b in zip(*answers, strict=True)]
    _require(
        record["affected"] == affected and all(type(a) is bool for a in record["affected"]),
        "affected mismatch",
    )
    if role == "primary":
        _require(
            hops[0] == [meta["primary_hop"]] * 2 and meta["primary_hop"] in HOPS,
            "primary hop coverage mismatch",
        )
        edit = meta["swapped_positions"]
        _require(
            len(edit) == 2
            and all(type(i) is int for i in edit)
            and 1 <= edit[0] < edit[1] < WIDTH - 1
            and edit[1] - edit[0] >= 2,
            "invalid internal nonadjacent edit",
        )
        _require(orders[1] == _HELPER._swapped(orders[0], tuple(edit)), "edit/path mismatch")
        _require(meta["edit_distance"] == edit[1] - edit[0], "edit distance mismatch")
        _require(affected == [meta["variant"] == "affected"] * 2, "variant mismatch")
        _require(meta["causal_edit_claim"] is True, "primary edit declaration missing")
        _require(
            all(_HELPER._direct_edge_endpoint(c, q) is None for c in contexts for q in queries),
            "primary direct-edge/endpoint shortcut answered",
        )
    else:
        _require(hops[0] == [1, 1], "easy control must be hop1")
        _require(orders[1] == orders[0][::-1], "easy reversal mismatch")
        _require(meta["causal_edit_claim"] is False, "easy control is not a causal edit assay")


def validate_corpus(corpus: object) -> dict[str, Any]:
    """Fail closed on text, family, split or frozen-plan tampering; not task qualification."""
    errors: list[str] = []
    summaries: dict[str, Any] = {}
    worlds: dict[tuple[str, ...], str] = {}
    family_splits: dict[str, str] = {}
    try:
        _require(isinstance(corpus, dict) and set(corpus) == set(SPLITS), "need both exact splits")
        assert isinstance(corpus, dict)
        expected = _build_corpus()
        for split in SPLITS:
            records = corpus[split]
            _require(
                isinstance(records, list) and len(records) == 120, "split must have 120 records"
            )
            groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for index, record in enumerate(records):
                try:
                    _require(isinstance(record, dict), "record must be an object")
                    _validate_record(record, split)
                    meta = record["metadata"]
                    family_id = meta["family_id"]
                    _require(
                        family_splits.setdefault(family_id, split) == split, "family crosses splits"
                    )
                    groups[family_id].append(record)
                    for order in meta["world_orders"]:
                        _require(
                            worlds.setdefault(tuple(order), family_id) == family_id,
                            "same parsed world assigned to different families",
                        )
                except (CorpusError, KeyError, TypeError, IndexError, ValueError) as exc:
                    errors.append(f"{split} record {index}: {exc}")
            _require(
                len(groups) == 12 and all(len(g) == 10 for g in groups.values()),
                "family must retain eight primary and two easy variants",
            )
            coverage = Counter()
            reverse_cases = 0
            for group in groups.values():
                first = group[0]["metadata"]
                coverage[first["primary_hop"]] += 1
                for key in (
                    "base_original_order",
                    "base_primary_query_entities",
                    "fact_position_order",
                ):
                    _require(
                        all(r["metadata"][key] == first[key] for r in group),
                        f"family has inconsistent {key}",
                    )
                for template in TEMPLATES:
                    by_variant = {
                        (r["metadata"]["variant"], r["metadata"]["orientation"]): r
                        for r in group
                        if r["metadata"]["role"] == "primary"
                        and r["metadata"]["template"] == template
                    }
                    _require(
                        set(by_variant)
                        == {
                            (v, o)
                            for v in ("affected", "unaffected")
                            for o in ("original", "reversed")
                        },
                        "missing alternate edit/orientation/template",
                    )
                    for orientation in ("original", "reversed"):
                        a, u = [by_variant[v, orientation] for v in ("affected", "unaffected")]
                        _require(
                            a["contexts"][0] == u["contexts"][0]
                            and a["queries"] == u["queries"]
                            and a["metadata"]["edit_distance"] == u["metadata"]["edit_distance"],
                            "alternate edits must share original/query and edit distance",
                        )
                    for variant in ("affected", "unaffected"):
                        a, b = [by_variant[variant, o] for o in ("original", "reversed")]
                        _require(
                            a["queries"] == b["queries"]
                            and a["affected"] == b["affected"]
                            and b["metadata"]["world_orders"]
                            == [o[::-1] for o in a["metadata"]["world_orders"]]
                            and b["answers"] == [[1 - x for x in row] for row in a["answers"]],
                            "global reversal must invert labels, preserving affected status",
                        )
                        reverse_cases += 4
                for role in ("primary", "easy"):
                    counts: dict[str, Counter[int]] = defaultdict(Counter)
                    for r in group:
                        if r["metadata"]["role"] == role:
                            for row in r["answers"]:
                                for q, y in zip(r["queries"], row, strict=True):
                                    counts[q][y] += 1
                    _require(
                        counts and all(c[0] == c[1] for c in counts.values()),
                        "query text is not exactly label-balanced within family/role",
                    )
            _require(
                coverage == Counter({h: 4 for h in HOPS}), "need four families per primary hop"
            )
            summaries[split] = {
                "families": 12,
                "primary_families_by_hop": dict(sorted(coverage.items())),
                "primary_records": 96,
                "primary_cases": 384,
                "easy_records": 24,
                "easy_cases": 96,
                "primary_case_counts_by_hop_and_affected": {
                    str(h): {
                        str(a).lower(): sum(
                            2 * r["affected"].count(a)
                            for r in records
                            if r["metadata"]["role"] == "primary"
                            and r["metadata"]["primary_hop"] == h
                        )
                        for a in (False, True)
                    }
                    for h in HOPS
                },
                "reversal_added_primary_cases_with_verified_label_inversion": reverse_cases,
                "shortcut_probes": {
                    role: _HELPER._shortcut_probes(
                        [r for r in records if r["metadata"]["role"] == role]
                    )
                    for role in ("primary", "easy")
                },
            }
            for probe in summaries[split]["shortcut_probes"].values():
                probe["scope"] = "TEXT_ONLY_STRUCTURAL_DIAGNOSTICS_NOT_MODEL_CAPABILITY"
                probe["interpretation"] = (
                    "Majority lookups fit and score the same split; they are not learned held-out "
                    "baselines. Exact balancing and named shortcut failure do not rule out other "
                    "shortcuts. Easy controls are separate and admit direct-edge solutions."
                )
        # Exact regeneration also binds non-semantic metadata and the fixed sampling plan.
        _require(corpus == expected, "records differ from frozen seed1402 generation plan")
    except (CorpusError, KeyError, TypeError, IndexError, ValueError) as exc:
        errors.append(str(exc))
    return {
        "format": "v14-instrument-corpus-audit-v1",
        "seed": SEED,
        "scope": SCOPE,
        "passed": not errors,
        "errors": errors,
        "status": "STRUCTURAL_CANDIDATES_VALIDATED" if not errors else "FAILED",
        "task_qualified": False,
        "model_capability_assessed": False,
        "holdout_model_scored": False,
        "training_authorized": False,
        "wording_generalization_qualified": False,
        "uncertainty_unit": "ORIGINAL_WORLD_FAMILY_INCLUDING_EDITS_REVERSALS_WORDING_EASY_CONTROLS",
        "checks": {
            name: not errors
            for name in (
                "parsed_text_oracle",
                "internal_nonadjacent_primary",
                "matched_hops_and_edit_distance",
                "query_text_balance_within_family_role",
                "global_reversal_label_inversion",
                "family_atomicity",
                "world_and_family_split_disjointness",
                "frozen_metadata_integrity",
            )
        },
        "splits": summaries if not errors else {},
        "claim_boundary": (
            "Structural candidates only. No model was scored, no training or full task "
            "qualification occurred. Holdout is family-disjoint, not unseen wording. "
            "Causal metrics must exclude easy controls."
        ),
    }


def write_corpus(output_dir: Path) -> dict[str, Any]:
    """Write exactly three fresh files to a newly created directory; refuse overwrite."""
    corpus = generate_corpus()
    audit = validate_corpus(corpus)
    output_dir.mkdir(parents=True, exist_ok=False)
    artifacts = {}
    for split, records in corpus.items():
        name = f"instrument_{split}.jsonl"
        payload = "".join(
            json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in records
        ).encode()
        with (output_dir / name).open("xb") as handle:
            handle.write(payload)
        artifacts[name] = {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
    audit["artifacts"] = artifacts
    audit["generator_sources"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (Path(__file__), HELPER_PATH)
    }
    with (output_dir / "INSTRUMENT_CORPUS_AUDIT.json").open("x", encoding="utf-8") as handle:
        json.dump(audit, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        audit = write_corpus(args.output_dir)
    except (OSError, CorpusError) as exc:
        parser.exit(1, f"corpus generation failed: {exc}\n")
    print(json.dumps({"status": audit["status"], "artifacts": audit["artifacts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
