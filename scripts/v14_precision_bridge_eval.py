"""Read-only heldout and matched four-turn assays for the compact V14 bridge.

Only text-derived tensors enter the bridge. Labels and world/side metadata are
used outside model calls for intervention selection and scoring. Native versus
FP32 compares composition plus head precision, not a whole-decoder FP32 run.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from typing import Any

import torch
from run_v14_multiturn_choice import (
    HISTORY_MODES,
    READOUTS,
    REGIMES,
    TURN_QUERY_INDICES,
    _matched_uniform,
    _sample_choice,
)

CONTROLS = ("intact", "twin", "zero", "fixed_carrier", "norm_matched_random", "unrelated")


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()


def _describe(values: list[float]) -> dict[str, Any]:
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Nonfinite evaluation statistic")
    return {
        "count": len(values),
        "mean": sum(values) / len(values) if values else None,
        "mean_absolute": sum(abs(value) for value in values) / len(values) if values else None,
        "positive": sum(value > 0 for value in values),
        "negative": sum(value < 0 for value in values),
        "zero": sum(value == 0 for value in values),
        "positive_rate": sum(value > 0 for value in values) / len(values) if values else None,
    }


def _accuracy(rows: list[dict[str, Any]], field: str = "target_correct") -> dict[str, Any]:
    return {
        "count": len(rows),
        "correct": sum(bool(row[field]) for row in rows),
        "accuracy": sum(bool(row[field]) for row in rows) / len(rows) if rows else None,
    }


def _memories(bridge: Any, store: Any, world: int, device: Any) -> dict[Any, Any]:
    memories: dict[Any, Any] = {}
    for side in (0, 1, "unrelated"):
        hidden = store.context(world, side).to(device)
        mask = torch.ones(hidden.shape[:2], dtype=torch.long, device=device)
        memories[side] = bridge.write_memory(hidden.float(), mask)
    memory, mask = memories[0]
    positions = torch.arange(memory.numel(), device=device, dtype=torch.float32)
    fixed = (torch.sin(positions * 0.017) + torch.cos(positions * 0.031)).reshape_as(memory)
    fixed = fixed / fixed.square().mean().sqrt().clamp_min(1e-12)
    memories["fixed_carrier"] = (fixed, torch.ones_like(mask))
    memories["zero"] = (torch.zeros_like(memory), torch.ones_like(mask))
    for side in (0, 1):
        source, source_mask = memories[side]
        seed = int(_hash([271828, world, side])[:15], 16)
        generator = torch.Generator(device="cpu").manual_seed(seed)
        random = torch.randn(source.shape, generator=generator, dtype=torch.float32).to(device)
        random = random * (source.float().norm() / random.norm().clamp_min(1e-12))
        memories[("norm_matched_random", side)] = (random, source_mask)
    return memories


def _memory_key(control: str, side: int) -> Any:
    if control == "intact":
        return side
    if control == "twin":
        return 1 - side
    if control == "norm_matched_random":
        return (control, side)
    if control not in CONTROLS:
        raise ValueError(f"Unknown memory control: {control}")
    return control


def _scores(
    adapter: Any, normalized: torch.Tensor, delta: torch.Tensor, candidates: Any
) -> dict[str, Any]:
    decoded = adapter.decode(normalized, delta, candidates)
    result: dict[str, Any] = {}
    for name, tensor in zip(
        READOUTS, (decoded.native_choice_scores, decoded.fp32_choice_scores), strict=True
    ):
        values = [float(value) for value in tensor.detach().float().reshape(-1).tolist()]
        if len(values) != 2 or not all(math.isfinite(value) for value in values):
            raise ValueError("Adapter must return two finite choice scores")
        result[name] = {
            "scores": values,
            "yes_minus_no": values[1] - values[0],
            "greedy_choice": int(values[1] > values[0]),
        }
    result["delta_l2"] = float(delta.float().norm().item())
    result["delta_rms"] = float(delta.float().square().mean().sqrt().item())
    return result


@torch.no_grad()
def evaluate_single(
    bridge: Any, store: Any, adapter: Any, candidate_ids: Any, device: Any
) -> dict[str, Any]:
    """Evaluate every supplied heldout world, side, query, and control once.

    Side-swapped duplicates are preserved in raw rows; unique world/query
    pairs (side 0) are used for paired directional summary denominators.
    """
    if bridge.training:
        raise ValueError("Evaluation requires bridge.eval()")
    rows: list[dict[str, Any]] = []
    for world, record in enumerate(store.records):
        memories = _memories(bridge, store, world, device)
        for query, _query_text in enumerate(record["queries"]):
            normalized = store.query(world, query).to(device)
            zero = torch.zeros_like(normalized[:, -1:], dtype=torch.float32)
            base = _scores(adapter, normalized, zero, candidate_ids)
            cache: dict[Any, Any] = {}
            for side in (0, 1):
                original = int(record["answers"][side][query])
                donor = int(record["answers"][1 - side][query])
                affected = bool(record["affected"][query])
                if affected != (original != donor):
                    raise ValueError("Affected mask disagrees with paired labels")
                for control in CONTROLS:
                    key = _memory_key(control, side)
                    if key not in cache:
                        memory, mask = memories[key]
                        delta = bridge.read_delta(normalized[:, -1:].float(), memory, mask)
                        cache[key] = _scores(adapter, normalized, delta, candidate_ids)
                    receipt = cache[key]
                    target = donor if control == "twin" else original
                    rows.append(
                        {
                            "world_index": world,
                            "pair_id": record.get("metadata", {}).get("pair_id", f"world-{world}"),
                            "query_index": query,
                            "side": side,
                            "control": control,
                            "affected": affected,
                            "heldout_template": bool(
                                record.get("heldout_queries", [False] * len(record["queries"]))[
                                    query
                                ]
                            ),
                            "original_label": original,
                            "donor_label": donor,
                            "target_label": target,
                            "dual_readout": receipt,
                            "base_dual_readout": base,
                        }
                    )
    expected = sum(len(record["queries"]) * 2 * len(CONTROLS) for record in store.records)
    if len(rows) != expected:
        raise ValueError("Single-turn evaluation denominator did not close")
    return {
        "rows": rows,
        "summary": summarize_single(rows),
        "world_count": len(store.records),
        "row_count": len(rows),
        "semantic_promotion": False,
        "winner": "none",
        "control_accuracy_semantics": (
            "intact uses original labels; twin uses donor labels; other interventions "
            "use original-label reference accuracy, not a claim that control memory "
            "answers the query"
        ),
    }


def summarize_single(rows: list[dict[str, Any]]) -> dict[str, Any]:
    index = {(r["world_index"], r["side"], r["query_index"], r["control"]): r for r in rows}
    if len(index) != len(rows):
        raise ValueError("Duplicate single-turn evaluation keys")
    summary: dict[str, Any] = {}
    for readout in READOUTS:
        controls: dict[str, Any] = {}
        for control in CONTROLS:
            selected = [r for r in rows if r["control"] == control]
            scored = [
                {
                    **r,
                    "target_correct": r["dual_readout"][readout]["greedy_choice"]
                    == r["target_label"],
                }
                for r in selected
            ]
            controls[control] = {
                "all": _accuracy(scored),
                "affected": _accuracy([r for r in scored if r["affected"]]),
                "unaffected": _accuracy([r for r in scored if not r["affected"]]),
                "heldout_template": _accuracy([r for r in scored if r["heldout_template"]]),
                "seen_template": _accuracy([r for r in scored if not r["heldout_template"]]),
            }
        affected_delta: list[float] = []
        unaffected_delta: list[float] = []
        correct_flip: list[float] = []
        world_delta: dict[int, list[float]] = defaultdict(list)
        for row in rows:
            if row["control"] != "intact" or row["side"] != 0:
                continue
            twin = index[(row["world_index"], 0, row["query_index"], "twin")]
            intact_score, twin_score = row["dual_readout"][readout], twin["dual_readout"][readout]
            difference = twin_score["yes_minus_no"] - intact_score["yes_minus_no"]
            if row["affected"]:
                signed = (2 * row["donor_label"] - 1) * difference
                affected_delta.append(signed)
                world_delta[row["world_index"]].append(signed)
                correct_flip.append(
                    float(
                        intact_score["greedy_choice"] == row["original_label"]
                        and twin_score["greedy_choice"] == row["donor_label"]
                    )
                )
            else:
                unaffected_delta.append(difference)
        unrelated = [r for r in rows if r["control"] == "unrelated" and r["side"] == 0]
        base_scored = [
            {
                **r,
                "target_correct": r["base_dual_readout"][readout]["greedy_choice"]
                == r["original_label"],
            }
            for r in rows
            if r["control"] == "intact"
        ]
        summary[readout] = {
            "control_accuracy": controls,
            "base_query_only_accuracy": {
                "all": _accuracy(base_scored),
                "affected": _accuracy([r for r in base_scored if r["affected"]]),
                "unaffected": _accuracy([r for r in base_scored if not r["affected"]]),
                "heldout_template": _accuracy([r for r in base_scored if r["heldout_template"]]),
            },
            "intact_accuracy": controls["intact"]["all"],
            "affected_correct_flip": _describe(correct_flip),
            "affected_donor_signed_gap_change": _describe(affected_delta),
            "affected_world_mean_donor_gap_change": _describe(
                [sum(v) / len(v) for v in world_delta.values()]
            ),
            "unaffected_gap_change": _describe(unaffected_delta),
            "unrelated_gap_change_from_base": _describe(
                [
                    r["dual_readout"][readout]["yes_minus_no"]
                    - r["base_dual_readout"][readout]["yes_minus_no"]
                    for r in unrelated
                ]
            ),
            "unrelated_delta_l2": _describe([r["dual_readout"]["delta_l2"] for r in unrelated]),
            "pair_denominator": (
                "unique world/query pairs, side 0; no duplicated twin-side observations"
            ),
        }
    return summary


@torch.no_grad()
def evaluate_multiturn(
    bridge_map: dict[str, Any],
    store: Any,
    adapter: Any,
    tokenizer: Any,
    scenarios: list[dict[str, Any]],
    candidate_ids: Any,
    device: Any,
) -> dict[str, Any]:
    """Repeat the sealed four-turn query/sampling protocol with new controls."""
    del tokenizer  # Frozen projected scenarios already contain all token IDs.
    if set(bridge_map) != {"task", "semantic"} or any(b.training for b in bridge_map.values()):
        raise ValueError("Exactly task/semantic eval-mode bridges are required")
    if len(scenarios) != 4 or len({(s["world_index"], s["side"]) for s in scenarios}) != 4:
        raise ValueError("Four distinct world/side scenarios are required")
    conditions = [
        {"id": "base_query_only", "model": "base", "control": "query_only"},
        {"id": "base_inline", "model": "base", "control": "inline"},
    ]
    conditions += [
        {"id": f"{model}_{control}", "model": model, "control": control}
        for model in ("task", "semantic")
        for control in CONTROLS
    ]
    memories: dict[tuple[str, int], Any] = {}
    decode_cache: dict[Any, Any] = {}
    rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        if tuple(t["query_index"] for t in scenario["turns"]) != TURN_QUERY_INDICES:
            raise ValueError("Frozen four-turn query order changed")
        if tuple(scenario["candidate_ids"]) != tuple(candidate_ids):
            raise ValueError("Scenario candidate IDs disagree with model candidates")
        world, side = int(scenario["world_index"]), int(scenario["side"])
        for model, bridge in bridge_map.items():
            if (model, world) not in memories:
                memories[(model, world)] = _memories(bridge, store, world, device)
        for condition in conditions:
            for history in HISTORY_MODES:
                for readout in READOUTS:
                    for regime in REGIMES:
                        prefix = tuple(
                            scenario["inline_prefix"]
                            if condition["control"] == "inline"
                            else scenario["query_prefix"]
                        )
                        turns, generated, appended = [], [], []
                        for turn_index, turn in enumerate(scenario["turns"]):
                            key = (condition["id"], world, side, prefix)
                            if key not in decode_cache:
                                normalized = store.get_prefix(prefix).to(device)
                                if condition["model"] == "base":
                                    delta = torch.zeros_like(
                                        normalized[:, -1:], dtype=torch.float32
                                    )
                                else:
                                    memory_key = _memory_key(condition["control"], side)
                                    memory, mask = memories[(condition["model"], world)][memory_key]
                                    delta = bridge_map[condition["model"]].read_delta(
                                        normalized[:, -1:].float(), memory, mask
                                    )
                                decode_cache[key] = _scores(
                                    adapter, normalized, delta, candidate_ids
                                )
                            receipt = decode_cache[key]
                            uniform = (
                                None
                                if regime["temperature"] <= 0
                                else _matched_uniform(regime["seed"], scenario["id"], turn_index)
                            )
                            scores = receipt[readout]["scores"]
                            choice, probabilities = _sample_choice(
                                scores, temperature=regime["temperature"], uniform=uniform
                            )
                            original, donor = int(turn["original_label"]), int(turn["donor_label"])
                            target = donor if condition["control"] == "twin" else original
                            history_label = original if history == HISTORY_MODES[0] else choice
                            turns.append(
                                {
                                    "turn_index": turn_index,
                                    "query_index": int(turn["query_index"]),
                                    "query_text": turn["query_text"],
                                    "affected": bool(turn["affected"]),
                                    "heldout": bool(turn["heldout"]),
                                    "original_label": original,
                                    "donor_label": donor,
                                    "target_label": target,
                                    "choice_label": choice,
                                    "choice_text": scenario["choice_text"][choice],
                                    "target_correct": choice == target,
                                    "original_correct": choice == original,
                                    "prefix_token_count": len(prefix),
                                    "prefix_token_sha256": _hash(prefix),
                                    "history_generated_labels_before_turn": list(generated),
                                    "history_appended_labels_before_turn": list(appended),
                                    "appended_history_label": history_label,
                                    "matched_uniform": uniform,
                                    "selected_scores": scores,
                                    "selected_probabilities": probabilities,
                                    "dual_readout": receipt,
                                }
                            )
                            generated.append(choice)
                            appended.append(history_label)
                            if turn_index < 3:
                                prefix = (
                                    *prefix,
                                    int(candidate_ids[history_label]),
                                    *scenario["turns"][turn_index + 1]["query_suffix"],
                                )
                        rows.append(
                            {
                                "condition": condition["id"],
                                "model": condition["model"],
                                "control": condition["control"],
                                "scenario": scenario["id"],
                                "world_index": world,
                                "side": side,
                                "pair_id": scenario["pair_id"],
                                "history_mode": history,
                                "selected_readout": readout,
                                "regime": regime["id"],
                                "seed": regime["seed"],
                                "temperature": regime["temperature"],
                                "generated_labels": generated,
                                "appended_history_labels": appended,
                                "generated_text": [scenario["choice_text"][v] for v in generated],
                                "turns": turns,
                            }
                        )
    expected = 4 * 14 * len(HISTORY_MODES) * len(READOUTS) * len(REGIMES)
    if len(rows) != expected or any(len(row["turns"]) != 4 for row in rows):
        raise ValueError("Four-turn evaluation denominator did not close")
    return {
        "rows": rows,
        "summary": summarize_multiturn(rows),
        "trajectory_count": len(rows),
        "turn_count": len(rows) * 4,
        "semantic_promotion": False,
        "winner": "none",
        "kv_cache": False,
        "actual_prefix_recomputation_with_identical_prefix_memoization": True,
        "independent_world_count": len({s["world_index"] for s in scenarios}),
        "claim_boundary": (
            "Constrained no/yes generation only. Sixteen scenario/regime pairs are two worlds, "
            "not sixteen independent worlds. No automatic semantic promotion. Control accuracies "
            "except twin use original-label references even when memory cannot answer the query."
        ),
    }


def summarize_multiturn(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    index: dict[Any, Any] = {}
    for row in rows:
        key = (
            row["condition"],
            row["scenario"],
            row["history_mode"],
            row["selected_readout"],
            row["regime"],
        )
        if key in index:
            raise ValueError("Duplicate trajectory key")
        index[key] = row
        grouped["|".join((row["condition"], row["history_mode"], row["selected_readout"]))].extend(
            row["turns"]
        )
    accuracies = {
        key: {
            "all": _accuracy(turns),
            "affected": _accuracy([t for t in turns if t["affected"]]),
            "unaffected": _accuracy([t for t in turns if not t["affected"]]),
        }
        for key, turns in grouped.items()
    }
    paired: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        if row["control"] != "intact":
            continue
        twin = index[
            (
                f"{row['model']}_twin",
                row["scenario"],
                row["history_mode"],
                row["selected_readout"],
                row["regime"],
            )
        ]
        first = next(
            (
                i
                for i, (a, b) in enumerate(
                    zip(row["generated_labels"], twin["generated_labels"], strict=True)
                )
                if a != b
            ),
            None,
        )
        turn_pairs: list[dict[str, Any]] = []
        for intact_turn, twin_turn in zip(row["turns"], twin["turns"], strict=True):
            readout = row["selected_readout"]
            gap_delta = (
                twin_turn["dual_readout"][readout]["yes_minus_no"]
                - intact_turn["dual_readout"][readout]["yes_minus_no"]
            )
            affected = intact_turn["affected"]
            turn_pairs.append(
                {
                    "turn_index": intact_turn["turn_index"],
                    "affected": affected,
                    "prefix_equal": intact_turn["prefix_token_sha256"]
                    == twin_turn["prefix_token_sha256"],
                    "gap_change": gap_delta,
                    "donor_signed_gap_change": (2 * intact_turn["donor_label"] - 1) * gap_delta
                    if affected
                    else None,
                    "answer_changed": intact_turn["choice_label"] != twin_turn["choice_label"],
                    "correct_donor_flip": bool(
                        affected
                        and intact_turn["choice_label"] == intact_turn["original_label"]
                        and twin_turn["choice_label"] == intact_turn["donor_label"]
                    ),
                }
            )
        paired["|".join((row["model"], row["history_mode"], row["selected_readout"]))].append(
            {
                "scenario": row["scenario"],
                "world_index": row["world_index"],
                "regime": row["regime"],
                "first_difference_turn": first,
                "first_difference_prefix_equal": None
                if first is None
                else turn_pairs[first]["prefix_equal"],
                "first_difference_affected": None
                if first is None
                else turn_pairs[first]["affected"],
                "intact_labels": row["generated_labels"],
                "twin_labels": twin["generated_labels"],
                "turns": turn_pairs,
            }
        )
    pair_summary = {}
    for key, pairs in paired.items():
        turns = [turn for pair in pairs for turn in pair["turns"]]
        affected = [t for t in turns if t["affected"]]
        pair_summary[key] = {
            "pair_count": len(pairs),
            "world_count": len({p["world_index"] for p in pairs}),
            "trajectory_changed": sum(p["first_difference_turn"] is not None for p in pairs),
            "affected_answer_changes": sum(t["answer_changed"] for t in affected),
            "correct_donor_flips": sum(t["correct_donor_flip"] for t in affected),
            "affected_turn_count": len(affected),
            "affected_donor_signed_gap_change": _describe(
                [t["donor_signed_gap_change"] for t in affected]
            ),
            "affected_same_prefix_donor_signed_gap_change": _describe(
                [t["donor_signed_gap_change"] for t in affected if t["prefix_equal"]]
            ),
            "unaffected_gap_change": _describe(
                [t["gap_change"] for t in turns if not t["affected"]]
            ),
            "pairs": pairs,
        }
    return {
        "accuracy": accuracies,
        "intact_twin_pairs": pair_summary,
        "semantic_promotion": False,
        "winner": "none",
    }
