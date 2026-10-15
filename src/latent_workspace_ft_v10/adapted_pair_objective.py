"""Historical six-term reductions with explicit prefix graph ownership.

Labels choose losses/teacher-forced completions only. The model-independent
writer callback receives a context key, never a question or answer. This is a
fixed 2-world/8-query diagnostic objective, not a general data-reduction API.
"""

import torch
from torch.nn import functional as F

from .adapted_workspace import adapted_answer_terms


def adapted_pair_objective(
    pipeline,
    write_memory,
    *,
    prefix_ids,
    span,
    candidate_ids,
    labels,
    contract,
    eos_weight=0.0,
    eos_token_id=2,
):
    if (
        len(candidate_ids) != 2
        or len(labels) != 2
        or any(type(v) is not int or v not in (0, 1) for v in labels)
    ):
        raise ValueError("Two binary labels and candidates required by paired objective")
    adapter = pipeline.adapter
    # Preparation order is algorithmic state: the question graph is shared;
    # completion graphs are separately constructed before their answer heads.
    with adapter.objective() as graphs:
        graphs.prepare(prefix_ids)
        terms = []
        for side, label in enumerate(labels):
            memory, mask = write_memory(side)
            token = candidate_ids[label]
            graphs.prepare(prefix_ids + (token,))
            terms.append(
                adapted_answer_terms(
                    pipeline,
                    memory,
                    mask,
                    prefix_ids=prefix_ids,
                    completion_prefix_ids=prefix_ids + (token,),
                    span=span,
                    answer_token_id=token,
                    eos_token_id=eos_token_id,
                )
            )
        memory, mask = write_memory("unrelated")
        unrelated = pipeline(prefix_ids, memory, mask, span=span)
        with torch.no_grad():
            baseline = adapter.read(prefix_ids, lambda h: torch.zeros_like(h[:, -1:]).float())
        scores = [t.answer_output.readout.choice_scores(candidate_ids)[0] for t in terms]
        gap = [v[1] - v[0] for v in scores]
        difference = gap[1] - gap[0]
        donor = (2 * labels[1] - 1) * difference
        other = unrelated.readout.choice_scores(candidate_ids)[0]
        base = baseline.readout.choice_scores(candidate_ids)[0]
        affected, zero = labels[0] != labels[1], difference * 0
        components = {
            "answer_ce": (terms[0].answer_ce + terms[1].answer_ce) / 32,
            "eos_ce": (terms[0].eos_ce + terms[1].eos_ce) / 32,
            "donor_hinge": F.relu(contract["donor_margin"] - donor) / 4 if affected else zero,
            "unaffected_gap_square": difference.square() / 12 if not affected else zero,
            "unrelated_gap_square": ((other[1] - other[0]) - (base[1] - base[0])).square() / 16,
            "residual_norm_square": sum(
                out.delta.square().sum()
                for out in (terms[0].answer_output, terms[1].answer_output, unrelated)
            )
            / 48,
        }
        total = (
            components["answer_ce"]
            + eos_weight * components["eos_ce"]
            + contract["direction_weight"] * components["donor_hinge"]
            + contract["stability_weight"] * components["unaffected_gap_square"]
            + contract["unrelated_weight"] * components["unrelated_gap_square"]
            + contract["residual_penalty"] * components["residual_norm_square"]
        )
    return total, components
