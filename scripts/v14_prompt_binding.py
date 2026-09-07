"""Model-owned prompt rendering boundaries for functional workspace tasks.

The engine owns task structure and answer scoring. This module owns the text-to-
token dialogue envelope, because chat-template behavior is tokenizer/model
specific and must not be inferred from a generic ``use_chat_template`` flag.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any


class PromptBindingError(ValueError):
    """A requested prompt projection is unsupported or changes its prefix."""


@dataclass(frozen=True)
class PromptBindingDescriptor:
    schema_version: str
    renderer: str
    model_type: str
    template_sha256: str | None
    roles: tuple[str, ...]
    add_generation_prompt: bool
    system_policy: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["roles"] = list(self.roles)
        return value


def _template_sha256(tokenizer: Any) -> str | None:
    template = getattr(tokenizer, "chat_template", None)
    if not isinstance(template, str) or not template:
        return None
    return hashlib.sha256(template.encode("utf-8")).hexdigest()


def describe_prompt_binding(
    tokenizer: Any,
    *,
    renderer: str,
    model_type: str,
) -> PromptBindingDescriptor:
    """Describe one renderer without claiming numerical or task parity."""
    if renderer == "plain":
        return PromptBindingDescriptor(
            schema_version="latent_workspace.prompt_binding.v1",
            renderer=renderer,
            model_type=model_type,
            template_sha256=None,
            roles=(),
            add_generation_prompt=False,
            system_policy="not_applicable",
        )
    if renderer != "native_chat_user":
        raise PromptBindingError(f"Unsupported functional prompt renderer: {renderer!r}.")
    template_hash = _template_sha256(tokenizer)
    if template_hash is None:
        raise PromptBindingError("native_chat_user requires a non-empty tokenizer chat template.")
    if model_type != "mistral":
        raise PromptBindingError(
            "The first native_chat_user qualification is pinned to model_type='mistral'."
        )
    return PromptBindingDescriptor(
        schema_version="latent_workspace.prompt_binding.v1",
        renderer=renderer,
        model_type=model_type,
        template_sha256=template_hash,
        roles=("user",),
        add_generation_prompt=True,
        system_policy="no_system_role_single_user_message",
    )


def render_functional_prefix(
    tokenizer: Any,
    content: str,
    *,
    renderer: str,
    model_type: str,
) -> tuple[str, PromptBindingDescriptor]:
    """Project one complete functional prompt into a model-owned envelope."""
    if not isinstance(content, str) or not content.strip():
        raise PromptBindingError("Functional prompt content must be non-empty text.")
    descriptor = describe_prompt_binding(
        tokenizer,
        renderer=renderer,
        model_type=model_type,
    )
    if renderer == "plain":
        return content, descriptor
    rendered = tokenizer.apply_chat_template(
        [{"role": "user", "content": content}],
        tokenize=False,
        add_generation_prompt=True,
    )
    if not isinstance(rendered, str) or not rendered:
        raise PromptBindingError("The native chat template returned no text.")
    return rendered, descriptor


def exact_suffix_token_ids(
    tokenizer: Any,
    prefix: str,
    suffix: str,
    *,
    require_one: bool = True,
) -> tuple[list[int], list[int]]:
    """Return exact prefix and suffix token IDs, rejecting boundary retokenization."""
    prefix_ids = list(tokenizer.encode(prefix, add_special_tokens=False))
    full_ids = list(tokenizer.encode(prefix + suffix, add_special_tokens=False))
    if full_ids[: len(prefix_ids)] != prefix_ids:
        raise PromptBindingError("Answer suffix changed the rendered prompt token prefix.")
    answer_ids = full_ids[len(prefix_ids) :]
    if not answer_ids:
        raise PromptBindingError("Answer suffix produced no new token.")
    if require_one and len(answer_ids) != 1:
        raise PromptBindingError(
            f"Answer suffix {suffix!r} must be exactly one token, got {answer_ids}."
        )
    return prefix_ids, answer_ids
