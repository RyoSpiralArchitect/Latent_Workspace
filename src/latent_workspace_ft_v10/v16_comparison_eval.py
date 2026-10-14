"""Read-only native evaluation for the bounded V16 full-update comparison.

No training/eval mode switches, label-conditioned forwards, generated sequences,
alternate head arithmetic, or global RNG draws. The original base is a recorded
step-zero reference, not an extra resident model or a preservation loss.
"""

from __future__ import annotations

import torch

from .reader_query import QuestionSpan
from .readout_transport import compare_transport
from .v15_native_learner import rng_state, tree_hash
from .v16_slot_contrast import SlotContrastWorkspaceBridge

CONDITIONS = (
    "intact",
    "twin",
    "reverse_intact",
    "reverse_twin",
    "zero",
    "unrelated",
    "common_intact",
    "common_twin",
    "random_intact",
    "random_twin",
)
FACTORS = {
    "actual": ("intact", "twin"),
    "reversed": ("reverse_intact", "reverse_twin"),
    "common_slots": ("common_intact", "common_twin"),
    "random_pair": ("random_intact", "random_twin"),
    "same_memory": ("intact", "intact"),
}


def choice(logits, candidates):
    values = logits[0, -1, list(candidates)].detach().cpu().double().tolist()
    gap = values[1] - values[0]
    return {"scores": values, "gap": gap, "prediction": None if gap == 0 else int(gap > 0)}


def memory_bank(learner, store, world, seed):
    source = {
        name: store.write(learner.bridge, world, key)
        for name, key in (
            ("intact", 0),
            ("twin", 1),
            ("reverse_intact", "reverse_0"),
            ("reverse_twin", "reverse_1"),
            ("unrelated", "unrelated"),
        )
    }
    memory, mask = source["intact"]
    source["zero"] = (torch.zeros_like(memory), mask)
    generator = torch.Generator(device="cpu").manual_seed(seed + world)
    for name in ("intact", "twin"):
        memory, mask = source[name]
        valid = mask.bool().unsqueeze(-1)
        mean = memory.masked_fill(~valid, 0).sum(1, keepdim=True) / mask.sum(1)[:, None, None]
        source[f"common_{name}"] = (mean.expand_as(memory).clone(), mask)
        random = torch.randn(memory.shape, generator=generator, device="cpu").to(memory.device)
        random = random.masked_fill(~valid, 0)
        # Norm-matched but not semantic or distribution-matched memory.
        random = random * (memory.masked_fill(~valid, 0).norm() / random.norm().clamp_min(1e-12))
        source[f"random_{name}"] = (random, mask)
    return source


@torch.no_grad()
def evaluate(learner, store, *, original=None, random_seed=470016, guard=lambda *a: None):
    """All counters retain their exact small, exposed-data denominators."""
    rng_before = tree_hash(rng_state())
    rows, contrasts, bases, memories = [], [], [], []
    for world, record in enumerate(store.records):
        bank = memory_bank(learner, store, world, random_seed)
        memories.append({"world": world, "hashes": {k: tree_hash(v) for k, v in bank.items()}})
        for query in range(len(record["queries"])):
            guard(f"evaluation:{learner.completed_steps}:{world}:{query}")
            row = store.renderings[world, query]
            ids = tuple(row["prompt_ids"])
            span_value = {
                **row["span"],
                "token_indices": tuple(row["span"]["token_indices"]),
                "prefix_ids": tuple(row["span"]["prefix_ids"]),
            }
            span = QuestionSpan(**span_value)
            candidates = row["candidate_ids"]
            labels = [record["answers"][side][query] for side in (0, 1)]
            device = next(learner.base.parameters()).device
            tokens = torch.tensor([ids], dtype=torch.long, device=device)
            direct = learner.base(
                input_ids=tokens,
                attention_mask=torch.ones_like(tokens),
                use_cache=False,
                logits_to_keep=0,
                return_dict=True,
            ).logits
            direct_choice = choice(direct, candidates)
            bases.append({"world": world, "query": query, "labels": labels, **direct_choice})
            outputs = {}
            for condition in CONDITIONS:
                memory, mask = bank[condition]
                output = learner.pipeline(ids, memory, mask, span=span)
                outputs[condition] = output
                measured = choice(output.readout.logits, candidates)
                side = 0 if condition in ("intact", "reverse_intact") else 1
                target = labels[side] if condition in CONDITIONS[:4] else None
                parts = (
                    learner.bridge.parts(output.reader_query, memory, mask)
                    if isinstance(learner.bridge, SlotContrastWorkspaceBridge)
                    else {"common": output.delta, "interaction": torch.zeros_like(output.delta)}
                )
                interaction_zero = not bool(parts["interaction"].count_nonzero())
                if (
                    condition.startswith("common_")
                    and getattr(learner.bridge, "mode", None) == "slot_contrast"
                ):
                    if not interaction_zero:
                        raise ValueError("Equal-slot contrast route lost its exact null")
                zero_exact = torch.equal(direct, output.readout.logits)
                if condition == "zero" and (not zero_exact or bool(output.delta.count_nonzero())):
                    raise ValueError("Zero workspace differs from current native base")
                if learner.completed_steps == 0 and original is None:
                    if not zero_exact or bool(output.delta.count_nonzero()):
                        raise ValueError("Fresh zero-up initialization differs from original base")
                rows.append(
                    {
                        "world": world,
                        "query": query,
                        "condition": condition,
                        "target": target,
                        "correct": measured["prediction"] == target if target is not None else None,
                        "candidate_ids": list(candidates),
                        **measured,
                        "delta_l2": float(output.delta.norm()),
                        "applied_delta_l2": float(output.transport.injection.applied_delta.norm()),
                        "common_l2": float(parts["common"].norm()),
                        "interaction_l2": float(parts["interaction"].norm()),
                        "interaction_exact_zero": interaction_zero,
                        "full_logits_equal_current_base": zero_exact,
                    }
                )
            for factor, (left, right) in FACTORS.items():
                transport = compare_transport(
                    outputs[left].transport,
                    outputs[right].transport,
                    candidates,
                    linear_weight=learner.binding.readout.head.weight,
                )
                change = transport["native_published_gap_change"][0]
                affected = labels[0] != labels[1]
                contrasts.append(
                    {
                        "world": world,
                        "query": query,
                        "factor": factor,
                        "affected": affected,
                        "labels": labels,
                        "donor_directed_gap_change": (2 * labels[1] - 1) * change
                        if affected
                        else None,
                        "transport": transport,
                        "left_prediction": choice(outputs[left].readout.logits, candidates)[
                            "prediction"
                        ],
                        "right_prediction": choice(outputs[right].readout.logits, candidates)[
                            "prediction"
                        ],
                    }
                )
            del outputs, direct, output, parts
    if tree_hash(rng_state()) != rng_before:
        raise ValueError("Evaluation changed the global RNG")
    baseline = bases if original is None else original
    if [(r["world"], r["query"], r["labels"]) for r in baseline] != [
        (r["world"], r["query"], r["labels"]) for r in bases
    ]:
        raise ValueError("Original-base reference geometry mismatch")
    result = {
        "schema": "v16-native-comparison-evaluation-v1",
        "step": learner.completed_steps,
        "rows": rows,
        "contrasts": contrasts,
        "direct_base": bases,
        "original_base": baseline,
        "memories": memories,
        "rng_unchanged": True,
        "scope": "two_exposed_training_worlds_not_held_out_non_regression",
    }
    result["summary"] = summarize(result)
    return result


def summarize(result):
    rows, contrasts = result["rows"], result["contrasts"]
    baseline = {(r["world"], r["query"]): r for r in result["original_base"]}
    conditions = {}
    for condition in CONDITIONS:
        selected = [r for r in rows if r["condition"] == condition]
        labelled = [r for r in selected if r["target"] is not None]
        conditions[condition] = {
            "n": len(selected),
            "labelled_n": len(labelled),
            "correct": sum(r["correct"] for r in labelled),
            "ties": sum(r["prediction"] is None for r in selected),
            "regressions_from_original": sum(
                baseline[r["world"], r["query"]]["prediction"] == r["target"] and not r["correct"]
                for r in labelled
            ),
            "repairs_from_original": sum(
                baseline[r["world"], r["query"]]["prediction"] != r["target"] and r["correct"]
                for r in labelled
            ),
        }
    factors = {}
    for factor in FACTORS:
        selected = [r for r in contrasts if r["factor"] == factor]
        affected = [r for r in selected if r["affected"]]
        unaffected = [r for r in selected if not r["affected"]]
        values = [r["donor_directed_gap_change"] for r in affected]
        factors[factor] = {
            "n": len(selected),
            "affected_n": len(affected),
            "unaffected_n": len(unaffected),
            "positive": sum(v > 0 for v in values),
            "zero": sum(v == 0 for v in values),
            "negative": sum(v < 0 for v in values),
            "mean_donor_directed_gap_change": sum(values) / len(values) if values else None,
            "donor_directed_flips": sum(
                r["left_prediction"] == r["labels"][0] and r["right_prediction"] == r["labels"][1]
                for r in affected
            ),
            "unaffected_prediction_changes": sum(
                r["left_prediction"] != r["right_prediction"] for r in unaffected
            ),
            "mean_abs_unaffected_gap_change": sum(
                abs(r["transport"]["native_published_gap_change"][0]) for r in unaffected
            )
            / len(unaffected)
            if unaffected
            else None,
        }
    return {
        "conditions": conditions,
        "factors": factors,
        "workspace_rows": len(rows),
        "direct_base_rows": len(result["direct_base"]),
        "old_expression_gate": "FAIL",
        "winner": "none",
        "non_regression": "NOT_ESTABLISHED",
    }
