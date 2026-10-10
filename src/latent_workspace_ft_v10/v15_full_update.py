"""Separate live-backbone contracts; the frozen V14.5 contracts stay unchanged.

The native readout operation is inherited verbatim. Only its ownership contract
changes. The first live feature binding is explicitly Mistral, not an untested
generic decoder abstraction. No hidden/context feature cache is maintained.
"""

from __future__ import annotations

from collections.abc import Callable

import torch
from torch import nn

from .model_binding import FunctionalBoundaryAdapter
from .reader_query import QuestionSpan
from .v15_5_learner import NativeAnswerTerms
from .v15_pipeline import NativeWorkspacePipeline
from .v15_readout import NativeWorkspaceReadout


class TrainableNativeWorkspaceReadout(NativeWorkspaceReadout):
    """Same native head arithmetic with explicitly trainable head ownership."""

    def _validate_head(self) -> None:
        head = self.head
        if head.weight.ndim != 2 or min(head.weight.shape) < 1:
            raise ValueError("Language-model head weight must be nonempty [V,H]")
        if head.weight.dtype not in (torch.float32, torch.bfloat16):
            raise TypeError("Language-model head must have native float32 or bfloat16 dtype")
        if not all(parameter.requires_grad for parameter in head.parameters()):
            raise ValueError("Full-update readout requires every head parameter trainable")
        if head.bias is not None and (
            tuple(head.bias.shape) != (head.weight.shape[0],)
            or head.bias.dtype != head.weight.dtype
            or head.bias.device != head.weight.device
        ):
            raise ValueError("Language-model head bias must match weight shape/dtype/device")


def validate_token_tuple(ids: tuple[int, ...], vocabulary: int) -> None:
    if (
        not isinstance(ids, tuple)
        or not ids
        or any(type(token) is not int or not 0 <= token < vocabulary for token in ids)
    ):
        raise ValueError("Token IDs must be a nonempty in-vocabulary integer tuple")


class MistralLiveFeatures:
    """Recompute current-theta features; accept token IDs, never answer labels.

    The observer is diagnostic only: it receives live outputs and may register
    gradient hooks. Its return value cannot replace the features. No graph is
    stored by this object. Parameter changes are seen on the next call.
    """

    def __init__(
        self,
        base_model: nn.Module,
        context_boundary: int,
        observer: Callable[[str, torch.Tensor], None] | None = None,
    ) -> None:
        self.base_model = base_model
        self.boundary = FunctionalBoundaryAdapter(base_model)
        if self.boundary.describe_boundary(context_boundary).binding_kind != "mistral":
            raise TypeError("Live native features currently qualify only the Mistral binding")
        if float(getattr(base_model.config, "attention_dropout", -1)) != 0.0:
            raise ValueError("This live parity contract requires zero attention dropout")
        self.context_boundary, self.observer = context_boundary, observer

    def _inputs(self, ids):
        validate_token_tuple(ids, self.base_model.config.vocab_size)
        tensor = torch.tensor([ids], dtype=torch.long, device=self.base_model.device)
        return tensor, torch.ones_like(tensor)

    def _observe(self, route: str, value: torch.Tensor) -> torch.Tensor:
        if torch.is_grad_enabled() and not value.requires_grad:
            raise ValueError("Live features lost their backbone gradient path")
        if self.observer is not None:
            self.observer(route, value)
        return value

    def prefix(self, ids: tuple[int, ...]) -> torch.Tensor:
        tokens, mask = self._inputs(ids)
        value = self.base_model.model(
            input_ids=tokens, attention_mask=mask, use_cache=False
        ).last_hidden_state
        return self._observe("query_or_completion", value)

    def context(self, ids: tuple[int, ...]) -> torch.Tensor:
        tokens, mask = self._inputs(ids)
        value = self.boundary.encode(tokens, mask, self.context_boundary)
        return self._observe("context_to_writer", value)


def full_native_answer_terms(
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
    """Unchanged answer/EOS semantics with live (never detached) features.

    Labels are consumed only in CE and the verified-answer completion prefix.
    They never enter the answer reader or query-independent writer. Both paths
    are evaluated even when EOS has zero objective weight, as in V14.5.
    """
    if not isinstance(pipeline.readout, TrainableNativeWorkspaceReadout):
        raise TypeError("Full native answer loss requires the trainable readout")
    vocabulary = pipeline.readout.head.out_features
    validate_token_tuple(prefix_ids, vocabulary)
    validate_token_tuple(completion_prefix_ids, vocabulary)
    for token in (answer_token_id, eos_token_id):
        if type(token) is not int or not 0 <= token < vocabulary:
            raise ValueError("Answer/EOS token must be an in-vocabulary integer")
    if answer_token_id == eos_token_id:
        raise ValueError("Answer token and EOS must differ")
    if prefix_ids != span.prefix_ids:
        raise ValueError("Answer supervision must start at the bound inference prefix")
    if completion_prefix_ids != prefix_ids + (answer_token_id,):
        raise ValueError("Completion must extend the prefix by its verified answer")
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
        if not hidden.requires_grad:
            raise ValueError("Full-update decoder features must be live, not detached")
    if not memory.requires_grad:
        raise ValueError("Full-update written memory must retain its gradient path")
    answer = pipeline(normalized_prefix, memory, memory_mask, prefix_ids=prefix_ids, span=span)
    completion = pipeline(
        normalized_completion,
        memory,
        memory_mask,
        prefix_ids=completion_prefix_ids,
        span=span,
    )
    device = answer.readout.logits.device
    return NativeAnswerTerms(
        answer,
        completion,
        answer.readout.cross_entropy(torch.tensor([answer_token_id], device=device)),
        completion.readout.cross_entropy(torch.tensor([eos_token_id], device=device)),
    )


def full_parameter_ownership(base: nn.Module, bridge: nn.Module):
    """Deduplicate aliases inside each family, reject frozen or cross-owned state."""
    named, seen = [], set()
    for family, module in (("base", base), ("bridge", bridge)):
        parameters = list(module.named_parameters())  # Physical aliases are deduplicated here.
        if not parameters:
            raise ValueError(f"Missing {family} parameters")
        for name, parameter in parameters:
            if not parameter.requires_grad:
                raise ValueError(f"Full-update parameter is frozen: {family}.{name}")
            if id(parameter) in seen:
                raise ValueError("Base and bridge cannot own the same physical parameter")
            seen.add(id(parameter))
            named.append((f"{family}.{name}", parameter))
    return named


def validate_full_optimizer_ownership(base, bridge, optimizer) -> dict:
    """Reject omitted, repeated or extra optimizer parameters before any step."""
    expected = full_parameter_ownership(base, bridge)
    actual = [parameter for group in optimizer.param_groups for parameter in group["params"]]
    if len(actual) != len(expected) or {id(p) for p in actual} != {id(p) for _, p in expected}:
        raise ValueError("Optimizer must own each full-update physical parameter exactly once")
    return {
        "parameter_tensors": len(expected),
        "parameter_elements": sum(p.numel() for _, p in expected),
    }
