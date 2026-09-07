from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from v14_prompt_binding import (  # noqa: E402
    PromptBindingError,
    describe_prompt_binding,
    exact_suffix_token_ids,
    render_functional_prefix,
)


class FakeTokenizer:
    chat_template = "{{ messages[0]['content'] }}"

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        assert tokenize is False
        assert add_generation_prompt is True
        assert [row["role"] for row in messages] == ["user"]
        return f"<s>[INST] {messages[0]['content']} [/INST]"

    def encode(self, text, *, add_special_tokens):
        assert add_special_tokens is False
        return [ord(char) for char in text]


def test_plain_binding_is_model_agnostic_and_text_exact() -> None:
    tokenizer = FakeTokenizer()
    rendered, descriptor = render_functional_prefix(
        tokenizer,
        "facts\nquestion",
        renderer="plain",
        model_type="olmo2",
    )
    assert rendered == "facts\nquestion"
    assert descriptor.to_dict() == {
        "schema_version": "latent_workspace.prompt_binding.v1",
        "renderer": "plain",
        "model_type": "olmo2",
        "template_sha256": None,
        "roles": [],
        "add_generation_prompt": False,
        "system_policy": "not_applicable",
    }


def test_mistral_chat_binding_uses_only_one_user_role() -> None:
    tokenizer = FakeTokenizer()
    rendered, descriptor = render_functional_prefix(
        tokenizer,
        "facts\nquestion",
        renderer="native_chat_user",
        model_type="mistral",
    )
    assert rendered == "<s>[INST] facts\nquestion [/INST]"
    assert descriptor.template_sha256 == hashlib.sha256(
        tokenizer.chat_template.encode("utf-8")
    ).hexdigest()
    assert descriptor.system_policy == "no_system_role_single_user_message"


def test_native_chat_binding_fails_closed_for_unqualified_model_family() -> None:
    with pytest.raises(PromptBindingError, match="pinned to model_type='mistral'"):
        describe_prompt_binding(
            FakeTokenizer(),
            renderer="native_chat_user",
            model_type="olmo2",
        )


def test_exact_suffix_rejects_prefix_retokenization_and_multiple_tokens() -> None:
    tokenizer = FakeTokenizer()
    prefix_ids, answer_ids = exact_suffix_token_ids(
        tokenizer, "prompt", " y", require_one=False
    )
    assert prefix_ids == [ord(char) for char in "prompt"]
    assert answer_ids == [ord(" "), ord("y")]

    with pytest.raises(PromptBindingError, match="exactly one token"):
        exact_suffix_token_ids(tokenizer, "prompt", " yes")


class BoundaryChangingTokenizer(FakeTokenizer):
    def encode(self, text, *, add_special_tokens):
        if text.endswith(" yes"):
            return [999]
        return super().encode(text, add_special_tokens=add_special_tokens)


def test_exact_suffix_detects_changed_prefix() -> None:
    with pytest.raises(PromptBindingError, match="changed the rendered prompt"):
        exact_suffix_token_ids(BoundaryChangingTokenizer(), "prompt", " yes")
