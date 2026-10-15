"""Train-only paired query-pooling assay; never a heldout-quality qualification."""

from __future__ import annotations

import math

import torch
from v14_precision_bridge_eval import READOUTS, _memories, _memory_key

CONTROLS = (
    "intact",
    "twin",
    "zero",
    "fixed_carrier",
    "norm_matched_random",
    "unrelated",
    "different_schema",
    "same_world_reserialization",
)


def _describe(values):
    if not values or not all(math.isfinite(value) for value in values):
        raise ValueError("Missing or nonfinite observations")
    return {
        "count": len(values),
        "mean": sum(values) / len(values),
        "minimum": min(values),
        "maximum": max(values),
        "maximum_absolute": max(abs(value) for value in values),
    }


def _scores(decoded):
    result = {}
    for key, scores in zip(
        READOUTS, (decoded.native_choice_scores, decoded.fp32_choice_scores), strict=True
    ):
        values = scores.detach().float().reshape(-1).tolist()
        if len(values) != 2 or not all(math.isfinite(value) for value in values):
            raise ValueError("Two finite candidate scores required")
        gap = values[1] - values[0]
        result[key] = {
            "scores": values,
            "yes_minus_no": gap,
            "greedy_choice": None if gap == 0 else int(gap > 0),
            "tie": gap == 0,
        }
    for tensor in (decoded.native_logits, decoded.native_applied_delta):
        if not bool(torch.isfinite(tensor).all()):
            raise ValueError("Nonfinite native readout")
    return result


def _validate_records(records):
    if len(records) != 2:
        raise ValueError("Expected exactly two train worlds")
    affected_count = 0
    for record in records:
        if len(record["queries"]) != 8 or len(record["answers"]) != 2:
            raise ValueError("Expected eight queries and two sides")
        if any(
            len(side) != 8 or any(label not in (0, 1) for label in side)
            for side in record["answers"]
        ):
            raise ValueError("Expected binary answers for eight queries")
        actual = [a != b for a, b in zip(*record["answers"], strict=True)]
        if actual != record["affected"]:
            raise ValueError("Affected flags disagree with labels")
        affected_count += sum(actual)
    if affected_count != 4:
        raise ValueError("Expected four affected and twelve unaffected unique queries")


def summarize(rows):
    """Reconstruct strict diagnostic gates; ties are never counted as correct."""
    expected = {(w, q, s, c) for w in range(2) for q in range(8) for s in (0, 1) for c in CONTROLS}
    index = {(r["world_index"], r["query_index"], r["side"], r["control"]): r for r in rows}
    if len(index) != len(rows) or set(index) != expected:
        raise ValueError("Duplicate, missing or unexpected evaluation denominator")
    for row in rows:
        reference = index[(row["world_index"], row["query_index"], row["side"], "intact")]
        target = row["donor_label"] if row["control"] == "twin" else row["original_label"]
        if (
            any(
                row[key] != reference[key]
                for key in ("original_label", "donor_label", "affected", "base_dual_readout")
            )
            or row["target_label"] != target
            or row["affected"] != (row["original_label"] != row["donor_label"])
        ):
            raise ValueError("Inconsistent paired control metadata")
    unique = [index[(w, q, 0, "intact")] for w in range(2) for q in range(8)]
    if sum(bool(row["affected"]) for row in unique) != 4:
        raise ValueError("Expected four affected and twelve unaffected unique queries")
    summary = {}
    for readout in READOUTS:
        controls = {}
        for control in CONTROLS:
            selected = [row for row in rows if row["control"] == control]
            correct = [
                row["dual_readout"][readout]["greedy_choice"] == row["target_label"]
                for row in selected
            ]
            drift = [
                row["dual_readout"][readout]["yes_minus_no"]
                - row["base_dual_readout"][readout]["yes_minus_no"]
                for row in selected
            ]
            controls[control] = {
                "count": len(selected),
                "correct": sum(correct),
                "ties": sum(row["dual_readout"][readout]["tie"] for row in selected),
                "gap_change_from_base": _describe(drift),
                "delta_l2": _describe([row["delta_l2"] for row in selected]),
                "native_applied_delta_l2": _describe(
                    [row["native_applied_delta_l2"] for row in selected]
                ),
            }
        donor, unchanged, flips, unaffected_flips = [], [], [], []
        for row in unique:
            twin = index[(row["world_index"], row["query_index"], 0, "twin")]
            a, b = row["dual_readout"][readout], twin["dual_readout"][readout]
            difference = b["yes_minus_no"] - a["yes_minus_no"]
            if row["affected"]:
                donor.append((2 * row["donor_label"] - 1) * difference)
                flips.append(
                    a["greedy_choice"] == row["original_label"]
                    and b["greedy_choice"] == row["donor_label"]
                )
            else:
                unchanged.append(difference)
                unaffected_flips.append(a["greedy_choice"] != b["greedy_choice"])
        intact = [row for row in rows if row["control"] == "intact"]
        ledger = {
            "both_correct": 0,
            "both_wrong": 0,
            "base_correct_candidate_wrong": 0,
            "base_wrong_candidate_correct": 0,
        }
        for row in intact:
            before = row["base_dual_readout"][readout]["greedy_choice"] == row["original_label"]
            after = row["dual_readout"][readout]["greedy_choice"] == row["original_label"]
            key = (
                "both_correct"
                if before and after
                else "both_wrong"
                if not before and not after
                else "base_correct_candidate_wrong"
                if before
                else "base_wrong_candidate_correct"
            )
            ledger[key] += 1
        feasibility = (
            controls["intact"]["correct"] == 32 and sum(flips) == 4 and sum(unaffected_flips) == 0
        )
        summary[readout] = {
            "controls": controls,
            "affected_count": 4,
            "unaffected_count": 12,
            "affected_correct_flips": sum(flips),
            "affected_correct_flip_values": flips,
            "donor_signed_changes": donor,
            "donor_signed_change": _describe(donor),
            "unaffected_gap_changes": unchanged,
            "unaffected_gap_change": _describe(unchanged),
            "unaffected_prediction_flips": sum(unaffected_flips),
            "paired_correctness_ledger": ledger,
            "tiny_feasibility": feasibility,
            "separation_screen": min(donor) > max(abs(value) for value in unchanged),
        }
    return summary


@torch.no_grad()
def evaluate(bridge, store, adapter, mode, device, guard=None, expect_initial_zero=False):
    """Eight memory controls with a fixed last-position base readout and no generation."""
    if bridge.training:
        raise ValueError("Evaluation requires bridge.eval()")
    _validate_records(store.records)
    guard = guard or (lambda label: None)
    rows, zero_checks, initial_checks = [], 0, 0
    for world, record in enumerate(store.records):
        guard(f"eval:{mode}:world{world}:memory:before")
        memories = _memories(bridge, store, world, device)
        for key in ("different_schema", "reserialized_0", "reserialized_1"):
            context = store.context(world, key).to(device=device, dtype=torch.float32)
            memories[key] = bridge.write_memory(
                context, torch.ones(context.shape[:2], device=device, dtype=torch.long)
            )
        if any(not bool(torch.isfinite(memory).all()) for memory, mask in memories.values()):
            raise ValueError("Nonfinite written memory")
        guard(f"eval:{mode}:world{world}:memory:after")
        for query in range(8):
            guard(f"eval:{mode}:world{world}:q{query}:before")
            normalized = store.query(world, query).to(device)
            reader_query = store.reader_query(world, query, mode).to(
                device=device, dtype=torch.float32
            )
            zero = torch.zeros_like(normalized[:, -1:], dtype=torch.float32)
            base_decoded = adapter.decode(normalized, zero, store.candidate_ids)
            base_scores = _scores(base_decoded)
            cache = {}
            for side in (0, 1):
                original, donor = (record["answers"][s][query] for s in (side, 1 - side))
                for control in CONTROLS:
                    key = (
                        f"reserialized_{side}"
                        if control == "same_world_reserialization"
                        else "different_schema"
                        if control == "different_schema"
                        else _memory_key(control, side)
                    )
                    if key not in cache:
                        memory, mask = memories[key]
                        delta = bridge.read_delta(reader_query, memory, mask)
                        if not bool(torch.isfinite(delta).all()):
                            raise ValueError("Nonfinite residual")
                        decoded = adapter.decode(normalized, delta, store.candidate_ids)
                        scores = _scores(decoded)
                        if key == "zero" or expect_initial_zero:
                            if torch.count_nonzero(delta) or not torch.equal(
                                decoded.native_logits, base_decoded.native_logits
                            ):
                                raise RuntimeError(
                                    "Written-zero or initial full-logit parity failed"
                                )
                            if scores != base_scores:
                                raise RuntimeError("Zero or initial candidate-score parity failed")
                            zero_checks += int(key == "zero")
                            initial_checks += int(expect_initial_zero)
                        changed = (
                            decoded.native_logits[:, -1].float()
                            - base_decoded.native_logits[:, -1].float()
                        )
                        if not bool(torch.isfinite(changed).all()):
                            raise ValueError("Nonfinite full-vocabulary difference")
                        cache[key] = {
                            "dual_readout": scores,
                            "delta_l2": float(delta.norm()),
                            "native_applied_delta_l2": float(decoded.native_applied_delta.norm()),
                            "native_applied_nonzero": int(
                                torch.count_nonzero(decoded.native_applied_delta)
                            ),
                            "native_full_vocab_last_delta_l2": float(changed.norm()),
                            "native_full_vocab_last_delta_max": float(changed.abs().max()),
                            "native_full_vocab_last_changed": int(torch.count_nonzero(changed)),
                            "memory_l2": float(memory.norm()),
                            "slot_l2": memory.norm(dim=-1).tolist(),
                        }
                    rows.append(
                        {
                            "world_index": world,
                            "query_index": query,
                            "side": side,
                            "control": control,
                            "reader_mode": mode,
                            "pair_id": record.get("metadata", {}).get("pair_id", f"world-{world}"),
                            "affected": original != donor,
                            "original_label": original,
                            "donor_label": donor,
                            "target_label": donor if control == "twin" else original,
                            "base_dual_readout": base_scores,
                            **cache[key],
                        }
                    )
            guard(f"eval:{mode}:world{world}:q{query}:after")
    summary = summarize(rows)
    gates = {
        "tiny_feasibility": all(value["tiny_feasibility"] for value in summary.values()),
        "fp32_objective_attainment": all(
            value >= 0.25 for value in summary[READOUTS[1]]["donor_signed_changes"]
        ),
        "separation_screen": all(value["separation_screen"] for value in summary.values()),
        "written_zero_full_logit_parity": zero_checks == 16,
        "initial_all_controls_zero": True if expect_initial_zero else None,
    }
    return {
        "rows": rows,
        "summary": summary,
        "gates": gates,
        "row_count": len(rows),
        "zero_full_logit_checks": zero_checks,
        "initial_zero_checks": initial_checks,
        "scope": "two_exposed_train_worlds_no_generation",
        "winner": "none",
        "semantic_promotion": False,
        "non_regression": "NOT_ESTABLISHED",
        "random_matching": "historical_global_raw_memory_L2",
        "different_schema_amplitude_matched": False,
        "control_accuracy_semantics": "Twin uses donor labels; other non-intact controls use "
        "original labels as references, not authoritative answers. Query-only base is "
        "unequal-information; this ledger is not a non-regression benchmark.",
    }
