"""Offline inference-only span/readout contracts; no model download or GPU."""

from __future__ import annotations

from dataclasses import replace

import pytest
import torch

from latent_workspace_ft_v10.reader_query import (
    base_readout_hidden,
    bind_question_span,
    reader_query_hidden,
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


RAW = "Is A ranked above B? Answer:"
PREFIX = "Use facts. Output no or yes.\n\n" + RAW


def bind(raw=RAW, rendered=PREFIX, tokenizer=None, ids=None):
    tokenizer = tokenizer or CharacterTokenizer()
    ids = tokenizer.encode(rendered, add_special_tokens=False) if ids is None else ids
    return bind_question_span(
        tokenizer, raw_query=raw, rendered_prefix=rendered, expected_prefix_ids=ids
    )


def test_question_binding_excludes_template_and_answer_cue():
    span = bind()
    assert span.question == "Is A ranked above B?"
    assert PREFIX[span.character_start : span.character_end] == span.question
    assert "".join(PREFIX[index] for index in span.token_indices) == span.question
    assert span.token_indices == tuple(range(span.token_indices[0], span.token_indices[-1] + 1))
    assert all(index < PREFIX.index("Answer:") for index in span.token_indices)
    assert len(span.rendered_prefix_sha256) == 64


def test_query_and_readout_are_separate_and_do_not_mutate_features():
    span = bind()
    hidden = torch.arange(len(PREFIX) * 4).reshape(1, len(PREFIX), 4).to(torch.bfloat16)
    before = hidden.clone()
    final = reader_query_hidden(hidden, span, prefix_ids=span.prefix_ids, mode="final")
    pooled = reader_query_hidden(hidden, span, prefix_ids=span.prefix_ids, mode="mean_span")
    readout = base_readout_hidden(hidden)
    assert readout.dtype == torch.bfloat16
    assert final.dtype == pooled.dtype == torch.float32
    assert final.shape == pooled.shape == readout.shape == (1, 1, 4)
    torch.testing.assert_close(final, hidden[:, -1:].float(), rtol=0, atol=0)
    torch.testing.assert_close(
        pooled, hidden[:, span.token_indices].float().mean(1, keepdim=True), rtol=0, atol=0
    )
    assert not torch.equal(pooled, final)
    assert torch.equal(hidden, before)
    assert readout.data_ptr() == hidden[:, -1:].data_ptr()


def test_pooling_gradient_reaches_only_selected_positions():
    span = bind()
    hidden = torch.randn(1, len(PREFIX), 3, requires_grad=True)
    pooled = reader_query_hidden(hidden, span, prefix_ids=span.prefix_ids, mode="mean_span")
    pooled.sum().backward()
    nonzero = tuple(torch.where(hidden.grad[0].abs().sum(-1) > 0)[0].tolist())
    assert nonzero == span.token_indices
    assert not hidden.grad[:, -1].any()


@pytest.mark.parametrize(
    "raw",
    ["", "Is A above B?", "Is A? Is B? Answer:", "Statement Answer:", "? Answer:",
     "Is A Answer: above B? Answer:"],
)
def test_missing_or_ambiguous_question_fails(raw):
    with pytest.raises(ValueError):
        bind(raw=raw)


@pytest.mark.parametrize(
    "rendered", ["No question here", RAW + "\n" + RAW, "prefix" + RAW, RAW.replace("? ", "?x ")]
)
def test_missing_ambiguous_or_embedded_rendered_question_fails(rendered):
    with pytest.raises(ValueError):
        bind(rendered=rendered)


@pytest.mark.parametrize("ids", [[1], [ord(c) for c in PREFIX[:-1]], [True], [1.0]])
def test_token_identity_or_truncation_fails(ids):
    with pytest.raises(ValueError):
        bind(ids=ids)


def test_slow_tokenizer_is_not_silently_approximated():
    tokenizer = CharacterTokenizer()
    tokenizer.is_fast = False
    with pytest.raises(ValueError, match="fast tokenizer"):
        bind(tokenizer=tokenizer)


@pytest.mark.parametrize("mutation", ["crossing", "missing", "reversed", "empty", "outside"])
def test_bad_offset_mapping_fails(mutation):
    class BrokenOffsets(CharacterTokenizer):
        def __call__(self, text, **kwargs):
            encoded = super().__call__(text, **kwargs)
            question_start = text.index("Is A")
            question_end = text.index("?") + 1
            if mutation == "crossing":
                encoded["offset_mapping"][question_end - 1] = (question_end - 1, question_end + 3)
            elif mutation == "missing":
                encoded["offset_mapping"][question_start] = (question_start + 1, question_start + 2)
            elif mutation == "reversed":
                encoded["offset_mapping"] = encoded["offset_mapping"][::-1]
            elif mutation == "empty":
                encoded["offset_mapping"][question_start] = (0, 0)
            elif mutation == "outside":
                encoded["offset_mapping"][-1] = (len(text) - 1, len(text) + 1)
            return encoded

    with pytest.raises(ValueError):
        bind(tokenizer=BrokenOffsets())


def test_whitespace_boundary_token_is_allowed_but_template_token_is_not():
    class WhitespaceOffsets(CharacterTokenizer):
        def __call__(self, text, **kwargs):
            encoded = super().__call__(text, **kwargs)
            question_start = text.index("Is A")
            encoded["offset_mapping"][question_start] = (question_start - 1, question_start + 1)
            return encoded

    span = bind(tokenizer=WhitespaceOffsets())
    assert PREFIX.index("Is A") in span.token_indices


@pytest.mark.parametrize("mode", ["final", "mean_span"])
def test_runtime_prefix_mismatch_same_length_fails(mode):
    span = bind()
    hidden = torch.ones(1, len(PREFIX), 2)
    other = (999, *span.prefix_ids[1:])
    with pytest.raises(ValueError, match="Runtime prefix IDs"):
        reader_query_hidden(hidden, span, prefix_ids=other, mode=mode)


@pytest.mark.parametrize("kind", ["rank", "batch", "length", "nan", "integer", "empty"])
def test_bad_hidden_shape_or_dtype_fails(kind):
    span = bind()
    hidden = torch.ones(1, len(PREFIX), 2)
    if kind == "rank":
        hidden = hidden.squeeze(0)
    elif kind == "batch":
        hidden = hidden.repeat(2, 1, 1)
    elif kind == "length":
        hidden = hidden[:, :-1]
    elif kind == "nan":
        hidden[0, 0, 0] = float("nan")
    elif kind == "integer":
        hidden = hidden.long()
    else:
        hidden = hidden[:, :0]
    with pytest.raises(ValueError):
        reader_query_hidden(hidden, span, prefix_ids=span.prefix_ids, mode="mean_span")


@pytest.mark.parametrize("indices", [(), (-1,), (9999,), (3, 2), (3, 3), (3, 5)])
def test_malformed_span_indices_fail(indices):
    span = replace(bind(), token_indices=indices)
    with pytest.raises(ValueError, match="indices"):
        reader_query_hidden(
            torch.ones(1, len(PREFIX), 2), span, prefix_ids=span.prefix_ids, mode="mean_span"
        )


def test_unknown_mode_fails():
    span = bind()
    with pytest.raises(ValueError, match="Unknown reader query mode"):
        reader_query_hidden(
            torch.ones(1, len(PREFIX), 2), span, prefix_ids=span.prefix_ids, mode="surprise"
        )


def test_readout_and_reader_selection_have_no_parameters_or_label_argument():
    import inspect

    assert set(inspect.signature(bind_question_span).parameters) == {
        "tokenizer", "raw_query", "rendered_prefix", "expected_prefix_ids"
    }
    assert not isinstance(reader_query_hidden, torch.nn.Module)


def test_answer_and_metadata_permutation_cannot_change_span_or_hidden_selection():
    first = {
        "query": RAW,
        "answers": [[1], [0]],
        "affected": [True],
        "metadata": {"query_pairs": [["A", "B"]], "orders": [["A", "B"]]},
    }
    second = {
        "query": RAW,
        "answers": [[0], [1]],
        "affected": [False],
        "metadata": {"query_pairs": [["B", "A"]], "orders": [["B", "A"]]},
    }
    # The public boundary receives only query text and independently rendered
    # prefix IDs; annotation/world metadata cannot enter the selector.
    spans = [bind(raw=record["query"]) for record in (first, second)]
    assert spans[0] == spans[1]
    hidden = torch.randn(1, len(PREFIX), 4)
    selected = [
        reader_query_hidden(hidden, span, prefix_ids=span.prefix_ids, mode="mean_span")
        for span in spans
    ]
    assert torch.equal(selected[0], selected[1])
