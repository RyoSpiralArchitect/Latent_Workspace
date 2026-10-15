#!/usr/bin/env python3
"""Prepare fresh, provenance-bound worlds without loading a model or using a GPU."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from latent_workspace_ft_v10.engine import make_functional_relation_pair_records  # noqa: E402

SEED = 901009
POOL_SIZE = 128
ACCEPT_COUNT = 64
DEFAULT_OUTPUT = REPO / "data/v14_mech_repair"
PRIOR_FILES = (
    (
        "data/v10/functional_train.jsonl",
        "8ca42ca2908a3d554849b6fb0054f838c424fdfed48ca478bbac7174740feea3",
        256,
    ),
    (
        "data/v10/functional_eval.jsonl",
        "fcd7bdd3966cbcd0fd02315ee76c813aaf51b82f913abdd074f1585d5958386e",
        64,
    ),
)
KEYS = ("pair_ids", "orders", "unordered_twins", "contexts")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record_keys(record: dict[str, Any]) -> dict[str, set[Any]]:
    meta = record["metadata"]
    orders = [tuple(order) for order in meta["orders"]]
    contexts = record["contexts"]
    if len(orders) != 2 or len(set(orders)) != 2 or len(set(contexts)) != 2:
        raise ValueError("A world pair requires two distinct orders and contexts")
    if len(contexts) != 2 or any(not isinstance(value, str) for value in contexts):
        raise ValueError("Context contract changed")
    return {
        "pair_ids": {meta["pair_id"], meta["world_pair_id"]},
        "orders": set(orders),
        "unordered_twins": {tuple(sorted(orders))},
        "contexts": set(contexts),
    }


def _all_keys(records: list[dict[str, Any]]) -> dict[str, set[Any]]:
    result: dict[str, set[Any]] = {key: set() for key in KEYS}
    for record in records:
        for key, values in _record_keys(record).items():
            result[key].update(values)
    return result


def select_disjoint(
    candidates: list[dict[str, Any]],
    previous: list[dict[str, Any]],
    count: int = ACCEPT_COUNT,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Accept in generator order; reject overlap with prior or accepted worlds."""
    if count < 1:
        raise ValueError("count must be positive")
    seen = _all_keys(previous)
    accepted, rejected = [], []
    for record in candidates:
        keys = _record_keys(record)
        overlaps = {key: len(keys[key] & seen[key]) for key in KEYS}
        if any(overlaps.values()):
            rejected.append(
                {"generator_index": record["metadata"]["world_index"], "overlaps": overlaps}
            )
            continue
        accepted.append(copy.deepcopy(record))
        for key in KEYS:
            seen[key].update(keys[key])
        if len(accepted) == count:
            return accepted, rejected
    raise ValueError(f"Insufficient disjoint worlds: {len(accepted)}/{count}")


def audit_disjoint(
    previous: list[dict[str, Any]], fresh: list[dict[str, Any]]
) -> dict[str, Any]:
    """Independently fail closed on old/new overlap and within-fresh duplicates."""
    old_keys, new_keys = _all_keys(previous), _all_keys(fresh)
    overlap = {key: len(old_keys[key] & new_keys[key]) for key in KEYS}
    seen: dict[str, set[Any]] = {key: set() for key in KEYS}
    internal = {key: 0 for key in KEYS}
    for record in fresh:
        for key, values in _record_keys(record).items():
            internal[key] += len(values & seen[key])
            seen[key].update(values)
    if any(overlap.values()) or any(internal.values()):
        raise ValueError(f"Corpus overlap: prior={overlap}, internal={internal}")
    return {
        "prior_world_pairs": len(previous),
        "fresh_world_pairs": len(fresh),
        "prior_unique_orders": len(old_keys["orders"]),
        "fresh_unique_orders": len(new_keys["orders"]),
        "prior_overlaps": overlap,
        "internal_overlaps": internal,
        "entity_heldout": False,
        "query_text_heldout": False,
    }


def prepare(output_dir: Path = DEFAULT_OUTPUT, repo: Path = REPO) -> dict[str, Any]:
    previous, prior_receipts = [], []
    for relative, expected_sha, expected_count in PRIOR_FILES:
        path = repo / relative
        if sha256(path) != expected_sha:
            raise ValueError(f"Prior corpus identity changed: {relative}")
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        if len(rows) != expected_count:
            raise ValueError(f"Prior corpus denominator changed: {relative}")
        previous.extend(rows)
        prior_receipts.append({"path": relative, "sha256": expected_sha, "rows": len(rows)})

    candidates = make_functional_relation_pair_records(
        worlds=POOL_SIZE,
        seed=SEED,
        width=6,
        queries_per_world=8,
        heldout_template="Does {left} outrank {right}? Answer:",
        heldout_fraction=0.5,
    )
    accepted, rejected = select_disjoint(candidates, previous)
    for record in accepted:
        if record["choices"] != [" 0", " 1"]:
            raise ValueError("Canonical generator choices changed")
        record["choices"] = [" no", " yes"]
    audit = audit_disjoint(previous, accepted)
    corpus = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in accepted)
    receipt = {
        "format": "latent-workspace-v14-mech-fresh-corpus-v1",
        "status": "PREPARED_NOT_EVALUATED",
        "seed": SEED,
        "candidate_pool_world_pairs": POOL_SIZE,
        "accepted_world_pairs": ACCEPT_COUNT,
        "accepted_generator_indices": [r["metadata"]["world_index"] for r in accepted],
        "rejections_before_completion": rejected,
        "prior_corpora": prior_receipts,
        "generator": {
            "path": "src/latent_workspace_ft_v10/engine.py",
            "function": "make_functional_relation_pair_records",
            "source_sha256": sha256(repo / "src/latent_workspace_ft_v10/engine.py"),
            "width": 6,
            "queries_per_world": 8,
            "query_template": "Is {left} ranked above {right}? Answer:",
            "heldout_template": "Does {left} outrank {right}? Answer:",
            "heldout_fraction": 0.5,
            "only_post_generation_change": {"choices": [" no", " yes"]},
        },
        "preparer_source_sha256": sha256(Path(__file__).resolve()),
        "fresh_corpus": {
            "path": "fresh_eval.jsonl",
            "sha256": hashlib.sha256(corpus.encode()).hexdigest(),
            "rows": len(accepted),
        },
        "split_audit": audit,
        "claim_boundary": [
            "Fresh evaluation worlds, not training or mechanistic repair-selection data.",
            "Entity names and query templates are shared; no entity/OOD generalization claim.",
            "Adjacent-twin contexts also differ in sentence serialization.",
            "No model loaded, GPU operation performed, or evaluation outcome inspected.",
        ],
    }
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    with (output_dir / "fresh_eval.jsonl").open("x", encoding="utf-8") as stream:
        stream.write(corpus)
    with (output_dir / "PREPARATION.json").open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = prepare(args.output)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
