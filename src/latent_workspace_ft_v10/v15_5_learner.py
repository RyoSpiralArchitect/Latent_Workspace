"""Native answer learning with separately weighted answer-conditioned completion.

The frozen decoder features and head keep their ordinary full-prefix geometry.
Only the workspace receives gradients. Targets are consumed by cross-entropy,
not by the writer or reader. The sole target-bearing forward is the explicitly
teacher-forced prefix used to supervise EOS; inference must never use it.

An EOS weight of one ADDS its CE. It does not halve the answer CE, replace it
with a two-candidate softmax, or reward stopping after an unverified answer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch

from .reader_query import QuestionSpan
from .v15_pipeline import NativeWorkspacePipeline, WorkspaceOutput


@dataclass
class NativeAnswerTerms:
    answer_output: WorkspaceOutput
    completion_output: WorkspaceOutput
    answer_ce: torch.Tensor
    eos_ce: torch.Tensor

    def objective(self, eos_weight: float) -> torch.Tensor:
        if (
            isinstance(eos_weight, bool)
            or not isinstance(eos_weight, (int, float))
            or not math.isfinite(eos_weight)
            or eos_weight < 0
        ):
            raise ValueError("EOS weight must be finite and nonnegative")
        return self.answer_ce + eos_weight * self.eos_ce


def native_answer_terms(
    pipeline: NativeWorkspacePipeline,
    memory: torch.Tensor,
    memory_mask: torch.Tensor,
    *,
    normalized_prefix: torch.Tensor,
    normalized_completion: torch.Tensor,
    prefix_ids: tuple[int, ...],
    completion_prefix_ids: tuple[int, ...],
    span: QuestionSpan,
    answer_token_id: int,
    eos_token_id: int,
) -> NativeAnswerTerms:
    """Supervise one exact answer token and EOS after that verified answer.

    Both forward paths run even when a caller later sets EOS weight to zero,
    keeping feature exposure and diagnostics matched across the two arms.
    The caller must establish symbolic truth and exact tokenizer extension;
    this model-neutral primitive checks the declared token/feature contract.
    """
    vocabulary = pipeline.readout.head.out_features
    for value in (answer_token_id, eos_token_id):
        if type(value) is not int or not 0 <= value < vocabulary:
            raise ValueError("Answer/EOS token must be an in-vocabulary integer")
    if answer_token_id == eos_token_id:
        raise ValueError("Answer token and EOS must differ")
    for ids in (prefix_ids, completion_prefix_ids):
        if (
            not isinstance(ids, tuple)
            or not ids
            or any(type(value) is not int or not 0 <= value < vocabulary for value in ids)
        ):
            raise ValueError("Prefix IDs must be nonempty tuples of vocabulary integers")
    if prefix_ids != span.prefix_ids:
        raise ValueError("Answer supervision must start at the exact bound original prefix")
    if completion_prefix_ids != prefix_ids + (answer_token_id,):
        raise ValueError("Completion must extend the original prefix by its verified answer")
    for hidden, ids in (
        (normalized_prefix, prefix_ids),
        (normalized_completion, completion_prefix_ids),
    ):
        if (
            not isinstance(hidden, torch.Tensor)
            or hidden.ndim != 3
            or hidden.shape[:2] != (1, len(ids))
        ):
            raise ValueError("Each feature must preserve one complete unpadded prefix")
        if hidden.requires_grad or hidden.grad is not None:
            raise ValueError("Decoder features must be detached and frozen")

    answer = pipeline(normalized_prefix, memory, memory_mask, prefix_ids=prefix_ids, span=span)
    completion = pipeline(
        normalized_completion,
        memory,
        memory_mask,
        prefix_ids=completion_prefix_ids,
        span=span,
    )
    device = answer.readout.logits.device
    answer_ce = answer.readout.cross_entropy(torch.tensor([answer_token_id], device=device))
    eos_ce = completion.readout.cross_entropy(torch.tensor([eos_token_id], device=device))
    return NativeAnswerTerms(answer, completion, answer_ce, eos_ce)


def validate_optimizer_ownership(bridge, optimizer) -> dict:
    """Reject duplicate, omitted, extra, or frozen parameters before an update."""
    expected = [p for p in bridge.parameters() if p.requires_grad]
    actual = [p for group in optimizer.param_groups for p in group["params"]]
    if (
        not expected
        or len(actual) != len(expected)
        or len({id(p) for p in actual}) != len(actual)
        or {id(p) for p in actual} != {id(p) for p in expected}
        or any(not p.requires_grad for p in actual)
    ):
        raise ValueError("Optimizer must own exactly the trainable workspace parameters")
    return {"parameter_tensors": len(actual), "parameter_elements": sum(p.numel() for p in actual)}
