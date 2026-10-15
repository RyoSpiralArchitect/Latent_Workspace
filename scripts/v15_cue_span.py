"""Exact assay-local binding at a tokenizer-owned terminal special marker.

Unlike the sealed whitespace-only binder, this also accepts one native special
end token immediately after '?'. It changes no text, IDs or historical code.
"""

import hashlib
from collections.abc import Mapping, Sequence
from numbers import Integral

from latent_workspace_ft_v10.reader_query import QuestionSpan, _ids, bind_question_span


def bind_cue_question_span(
    tokenizer, *, raw_query, rendered_prefix, expected_prefix_ids, allow_native_end
):
    raw = raw_query.strip()
    if not raw.endswith("Answer:") or raw.count("Answer:") != 1:
        raise ValueError("Canonical raw query must end in one Answer: marker")
    question = raw[: -len("Answer:")].strip()
    if not question.endswith("?") or question.count("?") != 1 or len(question) <= 1:
        raise ValueError("Expected one exact question")
    if rendered_prefix.count(question) != 1:
        raise ValueError("Exact question must occur once")
    start = rendered_prefix.index(question)
    end = start + len(question)
    if end == len(rendered_prefix) or rendered_prefix[end].isspace():
        return bind_question_span(
            tokenizer,
            raw_query=raw_query,
            rendered_prefix=rendered_prefix,
            expected_prefix_ids=expected_prefix_ids,
        )
    if allow_native_end is not True:
        raise ValueError("Non-whitespace boundary is not an authorized native end")
    if start and not rendered_prefix[start - 1].isspace():
        raise ValueError("Question start must be an unambiguous boundary")
    suffix = rendered_prefix[end:]
    terminal = _ids(tokenizer.encode(suffix, add_special_tokens=False), "Template end")
    expected = _ids(expected_prefix_ids, "Expected prefix")
    added = tokenizer.added_tokens_decoder.get(terminal[0])
    if (
        len(terminal) != 1
        or added is None
        or getattr(added, "special", False) is not True
        or tokenizer.get_added_vocab().get(suffix) != terminal[0]
        or expected[-1] != terminal[0]
    ):
        raise ValueError("Native terminal suffix must be one known special token")
    if tokenizer.convert_ids_to_tokens(terminal[0]) != suffix:
        raise ValueError("Native terminal token must own the entire literal suffix")
    if getattr(tokenizer, "is_fast", False) is not True:
        raise ValueError("Fast tokenizer offsets required")
    encoded = tokenizer(
        rendered_prefix,
        add_special_tokens=False,
        truncation=False,
        padding=False,
        return_offsets_mapping=True,
        return_attention_mask=False,
    )
    if not isinstance(encoded, Mapping) or "offset_mapping" not in encoded:
        raise ValueError("Missing offsets")
    ids = _ids(encoded.get("input_ids", ()), "Offset prefix")
    if ids != expected or ids != _ids(
        tokenizer.encode(rendered_prefix, add_special_tokens=False), "Full prefix"
    ):
        raise ValueError("Full prefix identity mismatch")
    offsets = encoded["offset_mapping"]
    if not isinstance(offsets, Sequence) or len(offsets) != len(ids):
        raise ValueError("Offset denominator")
    selected, covered = [], [False] * len(question)
    previous_left, previous_right = -1, -1
    for index, offset in enumerate(offsets):
        if (
            not isinstance(offset, Sequence)
            or len(offset) != 2
            or any(isinstance(v, bool) or not isinstance(v, Integral) for v in offset)
        ):
            raise ValueError("Invalid offset pair")
        left, right = map(int, offset)
        if (
            not 0 <= left < right <= len(rendered_prefix)
            or left < previous_left
            or right < previous_right
        ):
            raise ValueError("Nonmonotone/out-of-range offsets")
        previous_left, previous_right = left, right
        a, b = max(left, start), min(right, end)
        if a >= b:
            continue
        if rendered_prefix[left:a].strip() or rendered_prefix[b:right].strip():
            raise ValueError("Question token crosses the native terminal boundary")
        selected.append(index)
        for char in range(a - start, b - start):
            covered[char] = True
    if tuple(offsets[-1]) != (end, len(rendered_prefix)):
        raise ValueError("Terminal special-token offset must exactly cover the suffix")
    if not selected or selected != list(range(selected[0], selected[-1] + 1)):
        raise ValueError("Question tokens must form one contiguous span")
    if any(not hit and not char.isspace() for char, hit in zip(question, covered)):
        raise ValueError("Question character coverage incomplete")
    if selected[-1] >= len(ids) - 1:
        raise ValueError("Native terminal cannot enter question span")
    return QuestionSpan(
        question,
        start,
        end,
        tuple(selected),
        ids,
        hashlib.sha256(rendered_prefix.encode()).hexdigest(),
    )
