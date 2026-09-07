"""Second Mistral prompt adapter: balanced demonstrations without a system role."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any


class PromptBindingV2Error(ValueError):
    """A demonstrated native prompt projection is invalid."""


@dataclass(frozen=True)
class PromptBindingV2Descriptor:
    schema_version: str
    renderer: str
    model_type: str
    template_sha256: str
    role_sequence: tuple[str, ...]
    demonstration_labels: tuple[str, ...]
    system_policy: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["role_sequence"] = list(self.role_sequence)
        value["demonstration_labels"] = list(self.demonstration_labels)
        return value


POSITIVE_EXAMPLE = (
    "Example facts:\n"
    "- Tova is ranked above Wren.\n"
    "Question: Is Tova ranked above Wren?\n"
    "Reply with exactly Yes if the statement is true, or No if it is false."
)
NEGATIVE_EXAMPLE = (
    "Example facts:\n"
    "- Tova is ranked above Wren.\n"
    "Question: Is Wren ranked above Tova?\n"
    "Reply with exactly Yes if the statement is true, or No if it is false."
)
TEXT_DEMONSTRATION = (
    "Worked examples:\n\n"
    "Facts: Tova is ranked above Wren.\n"
    "Question: Is Tova ranked above Wren?\n"
    "Answer: Yes\n\n"
    "Facts: Tova is ranked above Wren.\n"
    "Question: Is Wren ranked above Tova?\n"
    "Answer: No\n\n"
    "Now solve the new case."
)


def _template_hash(tokenizer: Any) -> str:
    template = getattr(tokenizer, "chat_template", None)
    if not isinstance(template, str) or not template:
        raise PromptBindingV2Error("A non-empty tokenizer chat template is required.")
    return hashlib.sha256(template.encode("utf-8")).hexdigest()


def render_demonstrated_mistral_prefix(
    tokenizer: Any,
    target_content: str,
    *,
    renderer: str,
    model_type: str,
) -> tuple[str, PromptBindingV2Descriptor]:
    """Render a balanced mapping demonstration and one untouched target case."""
    if model_type != "mistral":
        raise PromptBindingV2Error("This renderer is qualified only for Mistral.")
    if not isinstance(target_content, str) or not target_content.strip():
        raise PromptBindingV2Error("Target content must be non-empty text.")
    if renderer == "native_chat_direct_caps":
        messages = [{"role": "user", "content": target_content}]
        labels: tuple[str, ...] = ()
    elif renderer == "native_chat_balanced_text_demo":
        messages = [
            {"role": "user", "content": f"{TEXT_DEMONSTRATION}\n\n{target_content}"}
        ]
        labels = ("Yes", "No")
    elif renderer == "native_chat_balanced_turn_demo":
        messages = [
            {"role": "user", "content": POSITIVE_EXAMPLE},
            {"role": "assistant", "content": "Yes"},
            {"role": "user", "content": NEGATIVE_EXAMPLE},
            {"role": "assistant", "content": "No"},
            {"role": "user", "content": target_content},
        ]
        labels = ("Yes", "No")
    else:
        raise PromptBindingV2Error(f"Unsupported demonstrated renderer: {renderer!r}.")
    rendered = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    if not isinstance(rendered, str) or not rendered:
        raise PromptBindingV2Error("The native chat template returned no text.")
    descriptor = PromptBindingV2Descriptor(
        schema_version="latent_workspace.prompt_binding.v2",
        renderer=renderer,
        model_type=model_type,
        template_sha256=_template_hash(tokenizer),
        role_sequence=tuple(str(message["role"]) for message in messages),
        demonstration_labels=labels,
        system_policy="no_system_role",
    )
    return rendered, descriptor
