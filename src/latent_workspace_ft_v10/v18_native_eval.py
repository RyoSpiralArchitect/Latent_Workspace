"""Read-only native evaluation for the bounded V18 selection pilot.

This ports the V16 comparison evaluation to the split-query selection pipeline:
the conditions, factors, memory bank, choice arithmetic and summary are imported
unchanged. Only two inputs differ. The pipeline receives the exact
inference-bound ``OperandSpan``, and the common/interaction split uses the
selection reader's own two queries. No mode switch, label-conditioned forward,
generated sequence or global RNG draw occurs here.
"""

from __future__ import annotations

import torch

from .reader_query import QuestionSpan
from .readout_transport import compare_transport
from .v15_native_learner import rng_state, tree_hash
from .v16_comparison_eval import CONDITIONS, FACTORS, choice, memory_bank, summarize
from .v18_operand_query import OperandSpan, validate_operand_span

SCHEMA = "v18-native-selection-evaluation-v1"


def legacy_span(row):
    value = dict(row["span"])
    value["token_indices"] = tuple(value["token_indices"])
    value["prefix_ids"] = tuple(value["prefix_ids"])
    return QuestionSpan(**value)


@torch.no_grad()
def evaluate(learner, store, spans, *, original=None, random_seed=470016, guard=lambda *a: None):
    """Exact small exposed-data denominators, as in the V16 bounded evaluation."""
    rng_before = tree_hash(rng_state())
    rows, contrasts, bases, memories = [], [], [], []
    mode = learner.pipeline.mode
    centered = getattr(learner.bridge, "mode", None) == "slot_contrast"
    for world, record in enumerate(store.records):
        bank = memory_bank(learner, store, world, random_seed)
        memories.append({"world": world, "hashes": {k: tree_hash(v) for k, v in bank.items()}})
        for query in range(len(record["queries"])):
            guard(f"evaluation:{learner.completed_steps}:{world}:{query}")
            row = store.renderings[world, query]
            ids = tuple(row["prompt_ids"])
            span = spans[world, query]
            if type(span) is not OperandSpan:
                raise ValueError("Evaluation requires an exact OperandSpan")
            validate_operand_span(span)
            if span.question_span != legacy_span(row) or span.prefix_ids != ids:
                raise ValueError("Operand span is not bound to this exact rendering")
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
                # A diagnostic recomputation from the two captured queries; the
                # published residual remains the pipeline's own output.
                parts = learner.bridge.parts(
                    output.common_query, output.interaction_query, memory, mask
                )
                interaction_zero = not bool(parts["interaction"].count_nonzero())
                if condition.startswith("common_") and centered and not interaction_zero:
                    raise ValueError("Equal-slot centered route lost its exact null")
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
                        "parts_reproduce_delta": bool(torch.equal(parts["delta"], output.delta)),
                        "full_logits_equal_current_base": zero_exact,
                        "interaction_query": mode,
                        "interaction_query_equals_common": bool(
                            torch.equal(output.interaction_query, output.common_query)
                        ),
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
        "schema": SCHEMA,
        "step": learner.completed_steps,
        "interaction_query": mode,
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
