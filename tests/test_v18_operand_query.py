"""Offline text/offset, prefix anchoring and CPU-FP32 operand-query contracts."""

from __future__ import annotations

import inspect
import os
from dataclasses import FrozenInstanceError, replace

import pytest
import torch

from latent_workspace_ft_v10.v18_operand_query import (
    OperandSpan,
    bind_operand_span,
    operand_reader_query,
    validate_operand_span,
)


class CharacterTokenizer:
    is_fast = True

    def encode(self, text, *, add_special_tokens):
        assert add_special_tokens is False
        return [ord(character) for character in text]

    def __call__(self, text, **kwargs):
        assert kwargs == {
            "add_special_tokens": False,
            "truncation": False,
            "padding": False,
            "return_offsets_mapping": True,
            "return_attention_mask": False,
        }
        return {
            "input_ids": self.encode(text, add_special_tokens=False),
            "offset_mapping": [(index, index + 1) for index in range(len(text))],
        }


RAW = "Is Aster ranked above Beryl? Answer:"
PREFIX = "[INST] Use facts.\n" + RAW + " [/INST]"
DEVICE = os.environ.get("LATENT_SLOT_STATE_TEST_DEVICE", "cpu")
if DEVICE not in ("cpu", "cuda"):
    raise ValueError("LATENT_SLOT_STATE_TEST_DEVICE must be cpu or cuda")


def bind(raw=RAW, rendered=None, tokenizer=None, ids=None):
    rendered = PREFIX if rendered is None and raw == RAW else rendered or raw
    tokenizer = tokenizer or CharacterTokenizer()
    ids = tokenizer.encode(rendered, add_special_tokens=False) if ids is None else ids
    return bind_operand_span(
        tokenizer, raw_query=raw, rendered_prefix=rendered, expected_prefix_ids=ids
    )


@pytest.mark.parametrize(
    "raw,subject,object_",
    [
        (RAW, "Aster", "Beryl"),
        ("Does Aster outrank Beryl? Answer:", "Aster", "Beryl"),
        ("Is Entity_7 ranked above NEW12? Answer:", "Entity_7", "NEW12"),
        ("Is A ranked above a? Answer:", "A", "a"),
    ],
)
def test_exact_supported_templates_and_lexical_contract(raw, subject, object_):
    rendered = "System.\n" + raw + "\n[/INST]"
    span = bind(raw=raw, rendered=rendered)
    assert span.subject == subject and span.object == object_
    assert span.prefix_ids == span.question_span.prefix_ids
    assert span.question_span.question == raw.removesuffix(" Answer:")
    for name, expected in (("subject", subject), ("object", object_)):
        start, end = (getattr(span, f"{name}_character_{side}") for side in ("start", "end"))
        assert rendered[start:end] == expected
        selected = "".join(rendered[index] for index in getattr(span, f"{name}_token_indices"))
        assert selected == expected
    validate_operand_span(span)


@pytest.mark.parametrize(
    "raw",
    [
        "Is Aster ranked above Aster? Answer:",
        "Does Aster outrank Aster? Answer:",
        "Is Aster above Beryl? Answer:",
        "Which is ranked higher, Aster or Beryl? Answer:",
        "Is Aster ranked above Beryl?",
        "Is Aster ranked above Beryl? Answer: extra",
        "Is Aster ranked above Beryl? Answer: Answer:",
        "Is Aster ranked above Beryl? Why? Answer:",
        "Is 7A ranked above Beryl? Answer:",
        "Is A-ster ranked above Beryl? Answer:",
        "Is A's ranked above Beryl? Answer:",
        "Is A B ranked above C? Answer:",
        "Is Åster ranked above Beryl? Answer:",
        "Is Aster  ranked above Beryl? Answer:",
        "Is Aster ranked above  Beryl? Answer:",
        "is Aster ranked above Beryl? Answer:",
    ],
)
def test_unsupported_ambiguous_or_same_operand_rejects(raw):
    with pytest.raises(ValueError):
        bind(raw=raw)


@pytest.mark.parametrize("kind", ["absent", "duplicate", "embedded", "changed", "truncated"])
def test_exact_question_and_complete_token_identity_required(kind):
    rendered = PREFIX
    ids = None
    if kind == "absent":
        rendered = "No query here"
    elif kind == "duplicate":
        rendered = PREFIX + "\n" + RAW
    elif kind == "embedded":
        rendered = "word" + RAW
    elif kind == "changed":
        ids = [9999, *map(ord, PREFIX[1:])]
    elif kind == "truncated":
        ids = list(map(ord, PREFIX[:-1]))
    with pytest.raises(ValueError):
        bind(rendered=rendered, ids=ids)


@pytest.mark.parametrize("kind", ["punctuation", "relation", "gap", "reversed", "empty", "bool"])
def test_bad_operand_offsets_reject(kind):
    class Changed(CharacterTokenizer):
        def __call__(self, text, **kwargs):
            encoded = super().__call__(text, **kwargs)
            subject = text.index("Aster")
            object_end = text.index("Beryl") + len("Beryl")
            offsets = encoded["offset_mapping"]
            if kind == "punctuation":
                offsets[object_end - 1] = (object_end - 1, object_end + 1)
            elif kind == "relation":
                offsets[subject - 1] = (subject - 2, subject + 1)
            elif kind == "gap":
                offsets[subject + 1] = (subject + 2, subject + 3)
            elif kind == "reversed":
                offsets.reverse()
            elif kind == "empty":
                offsets[subject] = (subject, subject)
            else:
                offsets[subject] = (True, subject + 1)
            return encoded

    with pytest.raises(ValueError):
        bind(tokenizer=Changed())


def test_operand_whitespace_boundary_token_is_accepted_and_tokenizer_called_once():
    class Whitespace(CharacterTokenizer):
        calls = 0

        def __call__(self, text, **kwargs):
            self.calls += 1
            encoded = super().__call__(text, **kwargs)
            for word in ("Aster", "Beryl"):
                start = text.index(word)
                encoded["offset_mapping"][start] = (start - 1, start + 1)
            return encoded

    tokenizer = Whitespace()
    span = bind(tokenizer=tokenizer)
    assert tokenizer.calls == 1
    assert len(span.subject_token_indices) == len("Aster")
    assert len(span.object_token_indices) == len("Beryl")


def test_slow_tokenizer_has_no_fallback():
    tokenizer = CharacterTokenizer()
    tokenizer.is_fast = False
    with pytest.raises(ValueError, match="fast tokenizer"):
        bind(tokenizer=tokenizer)


@pytest.mark.parametrize("mode", ["ordered_difference", "symmetric_mean"])
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_pooling_matches_cpu_fp32_order_without_mutating_hidden(mode, dtype, monkeypatch):
    span = bind()
    generator = torch.Generator().manual_seed(832)
    hidden = torch.randn(1, len(PREFIX), 7, generator=generator).to(device=DEVICE, dtype=dtype)
    before = hidden.clone()
    cpu_hidden = hidden.to(device="cpu", dtype=torch.float32)
    subject = cpu_hidden[:, span.subject_token_indices].mean(1, keepdim=True)
    object_ = cpu_hidden[:, span.object_token_indices].mean(1, keepdim=True)
    expected = subject - object_ if mode == "ordered_difference" else 0.5 * (subject + object_)
    reductions = []
    ordinary_mean = torch.Tensor.mean

    def observed_mean(tensor, *args, **kwargs):
        reductions.append((tensor.device.type, tensor.dtype, tuple(tensor.shape)))
        return ordinary_mean(tensor, *args, **kwargs)

    monkeypatch.setattr(torch.Tensor, "mean", observed_mean)
    query = operand_reader_query(hidden, span, prefix_ids=span.prefix_ids, mode=mode)
    assert reductions == [
        ("cpu", torch.float32, (1, len(span.subject_token_indices), 7)),
        ("cpu", torch.float32, (1, len(span.object_token_indices), 7)),
    ]
    assert query.dtype == torch.float32 and query.shape == (1, 1, 7)
    assert query.device == hidden.device and query.device.type == DEVICE
    torch.testing.assert_close(query, expected.to(hidden.device), rtol=0, atol=0)
    assert torch.equal(hidden, before)
    assert query.data_ptr() != hidden.data_ptr()


@pytest.mark.parametrize("mode", ["ordered_difference", "symmetric_mean"])
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_gradient_and_extended_completion_are_original_operand_anchored(mode, dtype):
    span = bind()
    hidden = torch.randn(1, len(PREFIX) + 3, 4, dtype=dtype).to(DEVICE).requires_grad_()
    runtime_ids = (*span.prefix_ids, 0, 1, 2)
    query = operand_reader_query(hidden, span, prefix_ids=runtime_ids, mode=mode)
    original = operand_reader_query(
        hidden[:, : len(PREFIX)], span, prefix_ids=span.prefix_ids, mode=mode
    )
    assert torch.equal(query, original)
    query.sum().backward()
    expected = torch.zeros_like(hidden)
    subject_gain = 1.0 if mode == "ordered_difference" else 0.5
    object_gain = -1.0 if mode == "ordered_difference" else 0.5
    expected[:, span.subject_token_indices] = subject_gain / len(span.subject_token_indices)
    expected[:, span.object_token_indices] = object_gain / len(span.object_token_indices)
    torch.testing.assert_close(hidden.grad, expected, rtol=0, atol=0)
    assert hidden.grad.device == hidden.device and hidden.grad.device.type == DEVICE
    assert not hidden.grad[:, len(PREFIX) :].any()


@pytest.mark.parametrize("mode", ["ordered_difference", "symmetric_mean"])
def test_cpu_autocast_does_not_change_reduction(mode):
    span = bind()
    hidden = torch.randn(1, len(PREFIX), 3).to(DEVICE)
    ordinary = operand_reader_query(hidden, span, prefix_ids=span.prefix_ids, mode=mode)
    with torch.autocast("cpu", dtype=torch.bfloat16):
        autocast = operand_reader_query(hidden, span, prefix_ids=span.prefix_ids, mode=mode)
    assert torch.equal(ordinary, autocast)
    assert autocast.dtype == torch.float32


@pytest.mark.parametrize(
    "kind", ["rank", "batch", "empty", "integer", "fp16", "fp64", "nan", "inf", "not_tensor"]
)
def test_unsupported_hidden_contract_rejects(kind):
    span = bind()
    hidden = torch.ones(1, len(PREFIX), 2)
    if kind == "rank":
        hidden = hidden.squeeze(0)
    elif kind == "batch":
        hidden = hidden.repeat(2, 1, 1)
    elif kind == "empty":
        hidden = hidden[:, :0]
    elif kind in ("integer", "fp16", "fp64"):
        dtype = {"integer": torch.int64, "fp16": torch.float16, "fp64": torch.float64}[kind]
        hidden = hidden.to(dtype)
    elif kind in ("nan", "inf"):
        hidden[0, 0, 0] = float(kind)
    else:
        hidden = None
    with pytest.raises(ValueError, match="Normalized states"):
        operand_reader_query(hidden, span, prefix_ids=span.prefix_ids)


@pytest.mark.parametrize("kind", ["changed", "short", "long", "bool", "float", "string"])
def test_bad_runtime_prefix_rejects(kind):
    span = bind()
    runtime = span.prefix_ids
    if kind == "changed":
        runtime = (9999, *runtime[1:])
    elif kind == "short":
        runtime = runtime[:-1]
    elif kind == "long":
        runtime = (*runtime, 1)
    elif kind == "bool":
        runtime = (True, *runtime[1:])
    elif kind == "float":
        runtime = (1.0, *runtime[1:])
    else:
        runtime = PREFIX
    with pytest.raises(ValueError, match="Runtime prefix"):
        operand_reader_query(torch.ones(1, len(PREFIX), 2), span, prefix_ids=runtime)


@pytest.mark.parametrize(
    "indices", [(), (-1,), (9999,), (True,), (1.0,), (3, 2), (3, 3), (3, 5), [3]]
)
def test_mutated_operand_indices_reject_at_runtime(indices):
    span = bind()
    object.__setattr__(span, "subject_token_indices", indices)
    with pytest.raises(ValueError, match="indices"):
        operand_reader_query(torch.ones(1, len(PREFIX), 2), span, prefix_ids=span.prefix_ids)


@pytest.mark.parametrize(
    "field,value",
    [
        ("subject", "Beryl"),
        ("object", "Aster"),
        ("subject_character_start", 0),
        ("subject_character_end", True),
        ("object_character_start", 0),
        ("object_character_end", 1.0),
    ],
)
def test_mutated_identifier_or_character_range_rejects(field, value):
    span = bind()
    object.__setattr__(span, field, value)
    with pytest.raises(ValueError):
        validate_operand_span(span)


@pytest.mark.parametrize("kind", ["outside_question", "overlap", "wrong_order"])
def test_structurally_invalid_operand_locations_reject(kind):
    span = bind()
    if kind == "outside_question":
        object.__setattr__(span, "subject_token_indices", (0,))
    elif kind == "overlap":
        object.__setattr__(span, "object_token_indices", span.subject_token_indices)
    else:
        subject, object_ = span.subject_token_indices, span.object_token_indices
        object.__setattr__(span, "subject_token_indices", object_)
        object.__setattr__(span, "object_token_indices", subject)
    with pytest.raises(ValueError):
        validate_operand_span(span)


@pytest.mark.parametrize(
    "field,value",
    [
        ("prefix_ids", [1, 2]),
        ("prefix_ids", (True,)),
        ("token_indices", (1, 3)),
        ("character_start", False),
        ("character_end", 0),
        ("question", "Is A above B?"),
        ("rendered_prefix_sha256", "wrong"),
    ],
)
def test_mutated_nested_question_metadata_rejects(field, value):
    span = bind()
    object.__setattr__(span, "question_span", replace(span.question_span, **{field: value}))
    with pytest.raises(ValueError):
        validate_operand_span(span)


def test_dataclass_is_frozen_but_validation_does_not_trust_freezing():
    span = bind()
    with pytest.raises(FrozenInstanceError):
        span.subject = "Other"
    with pytest.raises(ValueError):
        replace(span, subject="Other")
    with pytest.raises(ValueError):
        validate_operand_span(span.question_span)


def test_unknown_mode_rejects():
    span = bind()
    with pytest.raises(ValueError, match="Unknown operand"):
        operand_reader_query(
            torch.ones(1, len(PREFIX), 2), span, prefix_ids=span.prefix_ids, mode="final"
        )


def test_finite_input_that_overflows_fp32_reduction_rejects():
    span = bind()
    hidden = torch.zeros(1, len(PREFIX), 2, device=DEVICE)
    hidden[:, span.subject_token_indices] = torch.finfo(torch.float32).max
    with pytest.raises(ValueError, match="nonfinite query"):
        operand_reader_query(hidden, span, prefix_ids=span.prefix_ids)


def test_public_boundary_is_parameter_free_and_has_no_labels_or_facts():
    assert set(inspect.signature(bind_operand_span).parameters) == {
        "tokenizer", "raw_query", "rendered_prefix", "expected_prefix_ids"
    }
    assert set(inspect.signature(operand_reader_query).parameters) == {
        "hidden", "span", "prefix_ids", "mode"
    }
    assert not isinstance(operand_reader_query, torch.nn.Module)
    assert OperandSpan.__dataclass_params__.frozen
