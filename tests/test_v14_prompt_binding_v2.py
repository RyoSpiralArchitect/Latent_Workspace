from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from v14_prompt_binding_v2 import (  # noqa: E402
    PromptBindingV2Error,
    render_demonstrated_mistral_prefix,
)


class FakeTokenizer:
    chat_template = "fixed-template"

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        assert tokenize is False
        assert add_generation_prompt is True
        return "|".join(f"{row['role']}:{row['content']}" for row in messages) + "|assistant:"


def test_balanced_turn_demo_has_exact_role_and_label_order() -> None:
    rendered, descriptor = render_demonstrated_mistral_prefix(
        FakeTokenizer(),
        "target",
        renderer="native_chat_balanced_turn_demo",
        model_type="mistral",
    )
    assert descriptor.role_sequence == ("user", "assistant", "user", "assistant", "user")
    assert descriptor.demonstration_labels == ("Yes", "No")
    assert "assistant:Yes" in rendered
    assert "assistant:No" in rendered
    assert rendered.endswith("user:target|assistant:")


def test_text_demo_and_direct_renderer_remain_distinguishable() -> None:
    direct, direct_descriptor = render_demonstrated_mistral_prefix(
        FakeTokenizer(),
        "target",
        renderer="native_chat_direct_caps",
        model_type="mistral",
    )
    text, text_descriptor = render_demonstrated_mistral_prefix(
        FakeTokenizer(),
        "target",
        renderer="native_chat_balanced_text_demo",
        model_type="mistral",
    )
    assert direct_descriptor.demonstration_labels == ()
    assert text_descriptor.demonstration_labels == ("Yes", "No")
    assert direct != text


def test_v2_binding_rejects_other_model_families_and_unknown_modes() -> None:
    with pytest.raises(PromptBindingV2Error, match="only for Mistral"):
        render_demonstrated_mistral_prefix(
            FakeTokenizer(), "target", renderer="native_chat_direct_caps", model_type="olmo2"
        )
    with pytest.raises(PromptBindingV2Error, match="Unsupported"):
        render_demonstrated_mistral_prefix(
            FakeTokenizer(), "target", renderer="mystery", model_type="mistral"
        )
