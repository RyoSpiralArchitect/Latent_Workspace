from __future__ import annotations

import sys
from pathlib import Path

import pytest
import torch
from transformers import MistralConfig, MistralForCausalLM

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_v14_instrument_screen as screen
from v14_instrument_corpus import generate_corpus


class Words:
    pad_token_id, eos_token_id, bos_token_id = 0, 1, None

    def __init__(self):
        self.vocab = {}

    def encode(self, text, add_special_tokens=False):
        assert not add_special_tokens
        return [self.vocab.setdefault(word, len(self.vocab) + 2) for word in text.split()]


def test_strict_prefix_candidates_and_full_calibration():
    records = generate_corpus()["calibration"]
    features, receipt = screen.strict_tokenization(records, Words())
    assert len(features) == 120
    assert receipt["unchanged_entire_prefix"]
    assert receipt["prefix_count"] == 720
    assert len(set(receipt["candidate_ids"])) == 2
    assert max(receipt["max_unpadded_tokens"].values()) <= 256


def test_boundary_replacement_is_rejected_even_with_one_suffix_token():
    class BadBoundary(Words):
        def encode(self, text, add_special_tokens=False):
            ids = super().encode(text, add_special_tokens)
            if text.endswith((" no", " yes")):
                ids[-2] += 10000
            return ids

    with pytest.raises(ValueError, match="changes prefix"):
        screen.strict_tokenization(generate_corpus()["calibration"][:1], BadBoundary())


def test_collapsed_candidates_are_rejected():
    class SameChoice(Words):
        def encode(self, text, add_special_tokens=False):
            ids = super().encode(text, add_special_tokens)
            if text.endswith((" no", " yes")):
                ids[-1] = 123
            return ids

    with pytest.raises(ValueError, match="not distinct"):
        screen.strict_tokenization(generate_corpus()["calibration"][:1], SameChoice())


@pytest.mark.parametrize("route", ["query_only", "inline"])
def test_grouped_native_route_exact_and_causally_blind(route):
    torch.set_num_threads(2)
    torch.manual_seed(1401)
    tokenizer = Words()
    features, _ = screen.strict_tokenization(generate_corpus()["calibration"][:1], tokenizer)
    batch = screen.api.CausalFineTuningCollator(0)(features)
    config = MistralConfig(
        vocab_size=128,
        hidden_size=16,
        intermediate_size=32,
        num_hidden_layers=2,
        num_attention_heads=4,
        num_key_value_heads=2,
        max_position_embeddings=256,
        pad_token_id=0,
        attention_dropout=0.0,
    )
    config._attn_implementation = "eager"
    base = MistralForCausalLM(config).eval()
    wrapper = screen.make_wrapper(base, route)
    scores, receipt = screen.score_route(wrapper, batch, route, device="cpu", check_suffix=True)
    assert len(scores) == 4
    assert receipt["full_logits_numeric_exact"]
    assert receipt["future_answer_blindness"]
    assert receipt["finite"]
    assert all(p.grad is None for p in wrapper.parameters())


def test_changed_source_plan_is_rejected():
    with pytest.raises(ValueError, match="source identity"):
        screen.check_plan({"source_identity": {}}, "olmo")
