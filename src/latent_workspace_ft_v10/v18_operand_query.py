"""Inference-text-bound operands for an additive V18 interaction query.

Only the repository's two functional-query templates are supported: ``Is X
ranked above Y?`` and ``Does X outrank Y?``. The latter is an inference-visible
held-out wording, not a metadata flag. Operands are distinct, case-sensitive
ASCII identifiers matching ``[A-Za-z][A-Za-z0-9_]*``; this is a narrow lexical
contract, not general-language entity recognition. Facts, answers and donor
identities are not accepted by this module.

The query is an interaction-reader input only. It must not replace the common
reader's final-state input or the architecture adapter's native output state.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from numbers import Integral
from typing import Any, Literal

import torch

from .reader_query import QuestionSpan, _ids, bind_question_span

OperandQueryMode = Literal["ordered_difference", "symmetric_mean"]
_IDENTIFIER = r"[A-Za-z][A-Za-z0-9_]*"
_GRAMMARS = tuple(
    re.compile(pattern)
    for pattern in (
        rf"Is (?P<subject>{_IDENTIFIER}) ranked above (?P<object>{_IDENTIFIER})\?",
        rf"Does (?P<subject>{_IDENTIFIER}) outrank (?P<object>{_IDENTIFIER})\?",
    )
)


def _operands(question: str) -> re.Match[str]:
    if isinstance(question, str):
        for grammar in _GRAMMARS:
            match = grammar.fullmatch(question)
            if match is not None:
                if match["subject"] == match["object"]:
                    raise ValueError("Operand binding requires two distinct identifiers")
                return match
    raise ValueError("Question does not match a supported exact operand grammar")


def _indices(value: tuple[int, ...], *, name: str, length: int) -> None:
    if (
        not isinstance(value, tuple)
        or not value
        or any(
            isinstance(index, bool)
            or not isinstance(index, Integral)
            or not 0 <= index < length
            for index in value
        )
        or value != tuple(range(value[0], value[-1] + 1))
    ):
        raise ValueError(f"{name} indices must be nonempty, contiguous and increasing")


@dataclass(frozen=True, slots=True)
class OperandSpan:
    """Exact operand binding to one original, unpadded inference prefix.

    Character ranges are absolute half-open positions in the rendered prefix.
    Token positions remain anchored when answer tokens are appended. This
    structural value does not authenticate a caller who manually forges every
    field; obtain it with :func:`bind_operand_span` for checked text offsets.
    """

    question_span: QuestionSpan
    subject: str
    object: str
    subject_character_start: int
    subject_character_end: int
    object_character_start: int
    object_character_end: int
    subject_token_indices: tuple[int, ...]
    object_token_indices: tuple[int, ...]

    @property
    def prefix_ids(self) -> tuple[int, ...]:
        return self.question_span.prefix_ids

    def __post_init__(self) -> None:
        # Repeated at query time: a frozen dataclass is not proof that its
        # contents were produced by our binder or were never forcibly mutated.
        question = self.question_span
        if type(question) is not QuestionSpan:
            raise ValueError("Operand span requires a QuestionSpan")
        if not isinstance(question.prefix_ids, tuple):
            raise ValueError("Bound prefix IDs must be an immutable tuple")
        _ids(question.prefix_ids, "Bound prefix IDs")
        for value in (question.character_start, question.character_end):
            if isinstance(value, bool) or not isinstance(value, Integral):
                raise ValueError("Question character ranges must be integers")
        match = _operands(question.question)
        if (
            question.character_start < 0
            or question.character_end != question.character_start + len(question.question)
            or not isinstance(question.rendered_prefix_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", question.rendered_prefix_sha256) is None
        ):
            raise ValueError("Question text range or rendered-prefix digest is malformed")
        _indices(question.token_indices, name="Question", length=len(self.prefix_ids))
        for name in ("subject", "object"):
            if getattr(self, name) != match[name]:
                raise ValueError("Operand identifiers must match the bound question text")
            for side, relative in zip(("start", "end"), match.span(name)):
                actual = getattr(self, f"{name}_character_{side}")
                if (
                    isinstance(actual, bool)
                    or not isinstance(actual, Integral)
                    or actual != question.character_start + relative
                ):
                    raise ValueError("Operand character range differs from the bound question")
            indices = getattr(self, f"{name}_token_indices")
            _indices(indices, name=name, length=len(self.prefix_ids))
            if not set(indices).issubset(question.token_indices):
                raise ValueError("Operand indices must be inside the bound question")
        if self.subject_token_indices[-1] >= self.object_token_indices[0]:
            raise ValueError("Operand token spans must be ordered and disjoint")


def validate_operand_span(span: OperandSpan) -> None:
    """Revalidate structural metadata without any tensor pooling or transfer."""
    if type(span) is not OperandSpan:
        raise ValueError("Reader query requires an OperandSpan")
    span.__post_init__()


class _CaptureTokenizer:
    """Let the existing question binder validate the very same offset map."""

    def __init__(self, tokenizer: Any):
        self.tokenizer = tokenizer
        self.encoded = None

    @property
    def is_fast(self):
        return getattr(self.tokenizer, "is_fast", False)

    def __call__(self, *args, **kwargs):
        self.encoded = self.tokenizer(*args, **kwargs)
        return self.encoded

    def encode(self, *args, **kwargs):
        return self.tokenizer.encode(*args, **kwargs)


def _operand_indices(rendered: str, offsets, *, start: int, end: int) -> tuple[int, ...]:
    selected: list[int] = []
    covered = [False] * (end - start)
    # The question binder has already checked shape, bounds and monotonicity
    # of every offset. Require stricter coverage at each operand boundary.
    for index, (left, right) in enumerate(offsets):
        overlap_start, overlap_end = max(left, start), min(right, end)
        if overlap_start >= overlap_end:
            continue
        if rendered[left:overlap_start].strip() or rendered[overlap_end:right].strip():
            raise ValueError("Operand token crosses punctuation or other nonoperand text")
        selected.append(index)
        for character in range(overlap_start - start, overlap_end - start):
            covered[character] = True
    if not selected or not all(covered):
        raise ValueError("Token offsets do not completely cover an operand")
    return tuple(selected)


def bind_operand_span(
    tokenizer: Any,
    *,
    raw_query: str,
    rendered_prefix: str,
    expected_prefix_ids: Sequence[int],
) -> OperandSpan:
    """Bind both operands using inference text and exact fast-tokenizer offsets.

    The existing question contract validates the untruncated prefix and answer
    cue. A token may include surrounding whitespace but may not include the
    question mark, a relation word, or any other nonoperand character. No
    approximate matching, metadata lookup, or tokenizer fallback exists.
    """
    captured = _CaptureTokenizer(tokenizer)
    question = bind_question_span(
        captured,
        raw_query=raw_query,
        rendered_prefix=rendered_prefix,
        expected_prefix_ids=expected_prefix_ids,
    )
    match = _operands(question.question)
    fields: dict[str, Any] = {"question_span": question}
    for name in ("subject", "object"):
        start, end = (question.character_start + relative for relative in match.span(name))
        fields.update(
            {
                name: match[name],
                f"{name}_character_start": start,
                f"{name}_character_end": end,
                f"{name}_token_indices": _operand_indices(
                    rendered_prefix, captured.encoded["offset_mapping"], start=start, end=end
                ),
            }
        )
    return OperandSpan(**fields)


def operand_reader_query(
    hidden: torch.Tensor,
    span: OperandSpan,
    *,
    prefix_ids: Sequence[int],
    mode: OperandQueryMode = "ordered_difference",
) -> torch.Tensor:
    """Return FP32 ``[1,1,H]`` with fixed CPU reduction and retained autograd.

    Each operand is gathered in ascending original-prefix token order and
    averaged in CPU FP32. Difference or half-sum is then computed on CPU FP32
    before transport back to the hidden-state device. Appended completion
    states cannot enter either operand. Contextual states still depend on the
    actual prefix: reversing the text need not exactly negate this query.
    """
    validate_operand_span(span)
    if mode not in ("ordered_difference", "symmetric_mean"):
        raise ValueError(f"Unknown operand reader query mode: {mode!r}")
    if (
        not isinstance(hidden, torch.Tensor)
        or hidden.ndim != 3
        or hidden.shape[0] != 1
        or any(dimension < 1 for dimension in hidden.shape)
        or hidden.dtype not in (torch.float32, torch.bfloat16)
        or not bool(torch.isfinite(hidden).all())
    ):
        raise ValueError("Normalized states must be one finite, nonempty FP32/BF16 [1,L,H] prefix")
    runtime = _ids(prefix_ids, "Runtime prefix IDs")
    anchor = span.prefix_ids
    if len(runtime) != hidden.shape[1] or runtime[: len(anchor)] != anchor:
        raise ValueError("Runtime prefix must extend the exact bound inference prefix")
    with torch.autocast("cpu", enabled=False):
        frozen = hidden[:, : len(anchor)].to(device="cpu", dtype=torch.float32)
        means = [
            frozen.index_select(1, torch.tensor(indices, dtype=torch.long, device="cpu")).mean(
                dim=1, keepdim=True
            )
            for indices in (span.subject_token_indices, span.object_token_indices)
        ]
        query = means[0] - means[1] if mode == "ordered_difference" else 0.5 * (means[0] + means[1])
    if not bool(torch.isfinite(query).all()):
        raise ValueError("Operand reduction produced a nonfinite query")
    return query.to(hidden.device)
