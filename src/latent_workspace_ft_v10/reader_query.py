"""Parameter-free reader-query selection, separate from the base readout state.

This narrow functional-query contract consumes only inference-available text
and its exact token prefix. It does not accept answers, labels, or world facts.
The pooled state is ONLY a workspace-reader input: residuals must still be
applied to the original final-position state returned by ``base_readout_hidden``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Integral
from typing import Any, Literal

import torch

ReaderQueryMode = Literal["final", "mean_span"]


@dataclass(frozen=True, slots=True)
class QuestionSpan:
    """Exact text/token binding for one unpadded, inference-only query prefix."""

    question: str
    character_start: int
    character_end: int
    token_indices: tuple[int, ...]
    prefix_ids: tuple[int, ...]
    rendered_prefix_sha256: str


def _ids(values: Sequence[int], name: str) -> tuple[int, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"{name} must be a nonempty, unbatched token-ID sequence")
    if not values or any(
        isinstance(value, bool) or not isinstance(value, Integral) or value < 0
        for value in values
    ):
        raise ValueError(f"{name} must contain nonnegative integer token IDs")
    return tuple(int(value) for value in values)


def bind_question_span(
    tokenizer: Any,
    *,
    raw_query: str,
    rendered_prefix: str,
    expected_prefix_ids: Sequence[int],
) -> QuestionSpan:
    """Locate the single raw question, excluding template and answer cue tokens.

    Supported raw queries are one question ending in ``? Answer:`` (whitespace
    may vary). Rendered prompts may surround that question with an instruction
    or chat template, but must contain its exact text exactly once. Tokenizer
    offsets must cover all non-whitespace question characters without crossing
    into non-whitespace template/answer-cue text. A token may include surrounding
    whitespace. No approximate string matching or slow-tokenizer fallback exists.

    The complete untruncated rendered-prefix IDs must exactly equal the IDs
    encoded by the caller. This rejects silent truncation, suffix-boundary
    retokenization, and an offset mapping from another template/tokenization.
    """
    if not isinstance(raw_query, str) or not isinstance(rendered_prefix, str):
        raise ValueError("Raw query and rendered prefix must be strings")
    raw = raw_query.strip()
    marker = "Answer:"
    if not raw.endswith(marker) or raw.count(marker) != 1:
        raise ValueError("Raw query must end in exactly one 'Answer:' marker")
    question = raw[: -len(marker)].strip()
    if not question.endswith("?") or question.count("?") != 1:
        raise ValueError("Raw query must contain exactly one nonempty question")
    if len(question) <= 1 or rendered_prefix.count(question) != 1:
        raise ValueError("Rendered prefix must contain the exact question exactly once")
    start = rendered_prefix.index(question)
    end = start + len(question)
    # A matching substring inside a longer word is not a question boundary.
    if start and not rendered_prefix[start - 1].isspace():
        raise ValueError("Question must begin at an unambiguous text boundary")
    if end < len(rendered_prefix) and not rendered_prefix[end].isspace():
        raise ValueError("Question must end at an unambiguous text boundary")
    if getattr(tokenizer, "is_fast", False) is not True:
        raise ValueError("Question-span binding requires a fast tokenizer with offsets")
    encoded = tokenizer(
        rendered_prefix,
        add_special_tokens=False,
        truncation=False,
        padding=False,
        return_offsets_mapping=True,
        return_attention_mask=False,
    )
    if not isinstance(encoded, Mapping) or "offset_mapping" not in encoded:
        raise ValueError("Tokenizer did not provide an offset mapping")
    token_ids = _ids(encoded.get("input_ids", ()), "Tokenizer input_ids")
    expected = _ids(expected_prefix_ids, "Expected prefix IDs")
    full_ids = _ids(
        tokenizer.encode(rendered_prefix, add_special_tokens=False), "Full prefix IDs"
    )
    if token_ids != expected or token_ids != full_ids:
        raise ValueError("Rendered token IDs differ from the complete expected prefix")
    offsets = encoded["offset_mapping"]
    if not isinstance(offsets, Sequence) or len(offsets) != len(token_ids):
        raise ValueError("Token offsets do not align with prefix token IDs")
    selected: list[int] = []
    covered = [False] * len(question)
    previous_start, previous_end = -1, -1
    for index, offset in enumerate(offsets):
        if (
            not isinstance(offset, Sequence)
            or len(offset) != 2
            or any(isinstance(value, bool) or not isinstance(value, Integral) for value in offset)
        ):
            raise ValueError("Every token offset must be one integer start/end pair")
        left, right = (int(value) for value in offset)
        if not (0 <= left < right <= len(rendered_prefix)):
            raise ValueError("Token offsets must be nonempty and inside the rendered text")
        if left < previous_start or right < previous_end:
            raise ValueError("Token offsets must be monotone")
        previous_start, previous_end = left, right
        overlap_start, overlap_end = max(left, start), min(right, end)
        if overlap_start >= overlap_end:
            continue
        if (
            rendered_prefix[left:overlap_start].strip()
            or rendered_prefix[overlap_end:right].strip()
        ):
            raise ValueError("Question token crosses into template or answer marker text")
        selected.append(index)
        for character in range(overlap_start - start, overlap_end - start):
            covered[character] = True
    if not selected or any(not hit and not char.isspace() for char, hit in zip(question, covered)):
        raise ValueError("Token offsets do not completely cover the question")
    if selected != list(range(selected[0], selected[-1] + 1)):
        raise ValueError("Question token span must be contiguous")
    return QuestionSpan(
        question=question,
        character_start=start,
        character_end=end,
        token_indices=tuple(selected),
        prefix_ids=token_ids,
        rendered_prefix_sha256=hashlib.sha256(rendered_prefix.encode("utf-8")).hexdigest(),
    )


def _validate_hidden(hidden: torch.Tensor) -> None:
    if hidden.ndim != 3 or any(dimension < 1 for dimension in hidden.shape):
        raise ValueError("Normalized prefix hidden states must be nonempty [B,L,H]")
    if not hidden.is_floating_point() or not bool(torch.isfinite(hidden).all()):
        raise ValueError("Normalized prefix hidden states must be finite floating point")


def base_readout_hidden(hidden: torch.Tensor) -> torch.Tensor:
    """Return the original final prefix state unchanged, including native dtype.

    This view is separate from reader-query selection. Do not modify it in place.
    The architecture-owned native/full-vocabulary decoder should continue to
    receive the complete original ``hidden`` sequence, not this selected view.
    """
    _validate_hidden(hidden)
    return hidden[:, -1:]


def reader_query_hidden(
    hidden: torch.Tensor,
    span: QuestionSpan,
    *,
    prefix_ids: Sequence[int],
    mode: ReaderQueryMode,
) -> torch.Tensor:
    """Return FP32 [1,1,H] reader input without modifying final readout/features.

    ``final`` and ``mean_span`` add no parameters. Both consume the same frozen
    normalized sequence; only the reader's input selection/reduction changes.
    Span pooling reduces token hidden states in FP32, after native normalization.
    Equal-length but different prefixes are rejected before either mode runs.
    """
    _validate_hidden(hidden)
    if hidden.shape[0] != 1 or hidden.shape[1] != len(span.prefix_ids):
        raise ValueError("Question span requires one complete, unpadded hidden prefix")
    if _ids(prefix_ids, "Runtime prefix IDs") != span.prefix_ids:
        raise ValueError("Runtime prefix IDs do not match the bound question span")
    if not span.token_indices or any(
        index < 0 or index >= hidden.shape[1] for index in span.token_indices
    ):
        raise ValueError("Question span token indices are empty or outside the prefix")
    if tuple(range(span.token_indices[0], span.token_indices[-1] + 1)) != span.token_indices:
        raise ValueError("Question span token indices must be contiguous and increasing")
    if mode == "final":
        return base_readout_hidden(hidden).float()
    if mode == "mean_span":
        indices = torch.tensor(span.token_indices, dtype=torch.long, device=hidden.device)
        return hidden.index_select(1, indices).float().mean(dim=1, keepdim=True)
    raise ValueError(f"Unknown reader query mode: {mode!r}")
