"""CPU-only native/split contracts; no downloads or retained model checkpoints."""

import copy
import dataclasses
import hashlib
import json
from types import SimpleNamespace

import pytest
import torch
from torch import nn

transformers = pytest.importorskip("transformers")
from transformers import (  # noqa: E402
    GPT2Config,
    GPT2LMHeadModel,
    MistralConfig,
    MistralForCausalLM,
    Olmo2Config,
    Olmo2ForCausalLM,
)

from latent_workspace_ft_v10.model_binding import FunctionalBoundaryAdapter  # noqa: E402


@pytest.fixture(autouse=True)
def bounded_cpu_threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(previous)


def tiny_model(family: str) -> nn.Module:
    torch.manual_seed(147)
    if family == "gpt2":
        config = GPT2Config(
            vocab_size=41,
            n_embd=16,
            n_layer=2,
            n_head=4,
            n_positions=16,
            resid_pdrop=0.0,
            embd_pdrop=0.0,
            attn_pdrop=0.0,
            pad_token_id=0,
            use_cache=False,
        )
        model_type = GPT2LMHeadModel
    else:
        config_type, model_type = (
            (MistralConfig, MistralForCausalLM)
            if family == "mistral"
            else (Olmo2Config, Olmo2ForCausalLM)
        )
        kwargs = {"sliding_window": None} if family == "mistral" else {}
        config = config_type(
            vocab_size=41,
            hidden_size=16,
            intermediate_size=32,
            num_hidden_layers=2,
            num_attention_heads=4,
            num_key_value_heads=2,
            max_position_embeddings=32,
            attention_dropout=0.0,
            pad_token_id=0,
            use_cache=False,
            **kwargs,
        )
    config._attn_implementation = "eager"
    return model_type(config)


def tokens(padded: bool = True) -> tuple[torch.Tensor, torch.Tensor]:
    ids = torch.tensor([[1, 4, 5, 6, 7], [1, 8, 9, 0 if padded else 10, 0 if padded else 11]])
    return ids, ids.ne(0).long()


@pytest.mark.parametrize("family", ["gpt2", "mistral", "olmo2"])
@pytest.mark.parametrize("boundary", [0, 1, 2])
@pytest.mark.parametrize("padded", [False, True])
def test_native_split_logits(family: str, boundary: int, padded: bool) -> None:
    model = tiny_model(family).eval()
    binding = FunctionalBoundaryAdapter(model)
    ids, mask = tokens(padded)
    with torch.no_grad():
        expected = model(input_ids=ids, attention_mask=mask, use_cache=False).logits
        hidden = binding.encode(ids, mask, boundary)
        actual = binding.decode(hidden, mask, boundary)
    torch.testing.assert_close(actual, expected, rtol=1e-6, atol=1e-6)
    descriptor = binding.describe_boundary(boundary)
    assert descriptor.binding_kind == descriptor.model_type == family
    assert descriptor.boundary_layer == boundary
    assert descriptor.phase == ("pre_final_norm" if boundary == 2 else "pre_decoder_block")


@pytest.mark.parametrize("family", ["gpt2", "mistral", "olmo2"])
@pytest.mark.parametrize("boundary", [0, 1, 2])
@pytest.mark.parametrize("checkpointing", [False, True])
def test_native_split_gradients(family: str, boundary: int, checkpointing: bool) -> None:
    native = tiny_model(family).train()
    split = copy.deepcopy(native)
    if checkpointing:
        for model in (native, split):
            model.gradient_checkpointing_enable(
                gradient_checkpointing_kwargs={"use_reentrant": False}
            )
    ids, mask = tokens()
    expected = native(input_ids=ids, attention_mask=mask, use_cache=False).logits
    cotangent = torch.randn_like(expected)
    (expected * cotangent).sum().backward()
    binding = FunctionalBoundaryAdapter(split)
    actual = binding.decode(binding.encode(ids, mask, boundary), mask, boundary)
    (actual * cotangent).sum().backward()
    torch.testing.assert_close(actual, expected, rtol=1e-6, atol=1e-6)
    native_parameters = dict(native.named_parameters())
    split_parameters = dict(split.named_parameters())
    assert native_parameters.keys() == split_parameters.keys()
    for name, parameter in native_parameters.items():
        counterpart = split_parameters[name]
        assert (parameter.grad is None) == (counterpart.grad is None), name
        if parameter.grad is not None:
            torch.testing.assert_close(
                counterpart.grad,
                parameter.grad,
                rtol=2e-5,
                atol=2e-5,
                msg=lambda message, name=name: f"{name}: {message}",
            )


@pytest.mark.parametrize("family", ["gpt2", "mistral", "olmo2"])
def test_descriptor_fingerprint_is_metadata_only_and_immutable(family: str) -> None:
    model = tiny_model(family)
    binding = FunctionalBoundaryAdapter(model)
    descriptor = binding.describe_boundary(1)
    before = {name: parameter.detach().clone() for name, parameter in model.named_parameters()}
    payload = descriptor.to_dict()
    assert payload["backend"] == "torch"
    assert payload["torch_version"] == str(torch.__version__)
    assert payload["transformers_version"] == transformers.__version__
    assert payload["cache_policy"] == "disabled_no_cache"
    assert payload["position_policy"] == "sequential_zero_based"
    assert payload["attention_implementation"] == "eager"
    expected_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert descriptor.fingerprint() == expected_hash == binding.describe_boundary(1).fingerprint()
    assert descriptor.fingerprint() != binding.describe_boundary(0).fingerprint()
    with pytest.raises(dataclasses.FrozenInstanceError):
        descriptor.phase = "changed"
    for name, parameter in model.named_parameters():
        assert torch.equal(parameter, before[name])


@pytest.mark.parametrize("family", ["gpt2", "mistral", "olmo2"])
@pytest.mark.parametrize("boundary", [-1, 3])
def test_invalid_boundary_fails_all_interfaces(family: str, boundary: int) -> None:
    binding = FunctionalBoundaryAdapter(tiny_model(family))
    ids, mask = tokens()
    hidden = torch.zeros(2, 5, 16)
    for call in (
        lambda: binding.describe_boundary(boundary),
        lambda: binding.encode(ids, mask, boundary),
        lambda: binding.decode(hidden, mask, boundary),
    ):
        with pytest.raises(ValueError, match=r"outside \[0, 2\]"):
            call()


class CustomSplit(nn.Module):
    functional_num_layers = 1

    def __init__(self) -> None:
        super().__init__()
        self.config = SimpleNamespace(model_type="test_custom")
        self.embedding = nn.Embedding(12, 4)
        self.layer = nn.Linear(4, 4)
        self.head = nn.Linear(4, 12)

    def functional_forward_to_boundary(self, ids, mask, boundary):
        hidden = self.embedding(ids) * mask.unsqueeze(-1)
        return self.layer(hidden) if boundary else hidden

    def functional_forward_from_boundary(self, hidden, mask, boundary):
        return self.head(hidden if boundary else self.layer(hidden))


@pytest.mark.parametrize("boundary", [0, 1])
def test_custom_protocol_preserved_without_native_semantic_claims(boundary: int) -> None:
    model = CustomSplit()
    binding = FunctionalBoundaryAdapter(model)
    ids, mask = tokens()
    hidden = binding.encode(ids, mask, boundary)
    logits = binding.decode(hidden, mask, boundary)
    expected = model.head(model.layer(model.embedding(ids) * mask.unsqueeze(-1)))
    torch.testing.assert_close(logits, expected)
    descriptor = binding.describe_boundary(boundary)
    assert descriptor.binding_kind == "custom"
    assert descriptor.phase == descriptor.position_policy == "custom_protocol_defined"
    assert descriptor.cache_policy == "not_exposed_by_custom_protocol"
    assert descriptor.support_status == "delegated_custom_protocol"


def test_unsupported_and_partial_custom_models_fail_closed() -> None:
    unknown = nn.Module()
    unknown.config = SimpleNamespace(model_type="not_supported")
    with pytest.raises(TypeError, match="complete custom"):
        FunctionalBoundaryAdapter(unknown)
    unknown.functional_forward_to_boundary = lambda *args: None
    with pytest.raises(TypeError, match="complete custom"):
        FunctionalBoundaryAdapter(unknown)


def test_legacy_structural_gpt2_is_explicitly_labelled() -> None:
    model = tiny_model("gpt2")
    model.config.model_type = "legacy_structural_probe"
    descriptor = FunctionalBoundaryAdapter(model).describe_boundary(0)
    assert descriptor.binding_kind == "gpt2"
    assert descriptor.model_type == "legacy_structural_probe"
    assert descriptor.support_status == "legacy_gpt2_structural_layout"


@pytest.mark.parametrize("family", ["mistral", "olmo2"])
def test_strict_transformers_guards_preserved(monkeypatch, family: str) -> None:
    # Resolve the live module after optional imports initialize lazy packages.
    import transformers as runtime_transformers

    model = tiny_model(family)
    monkeypatch.setattr(runtime_transformers, "__version__", "999.0.0")
    with pytest.raises(RuntimeError, match="Unsupported Transformers version"):
        FunctionalBoundaryAdapter(model)


def test_olmo2_missing_native_norm_is_not_treated_as_mistral() -> None:
    model = tiny_model("olmo2")
    model.model.layers[0].post_feedforward_layernorm = None
    with pytest.raises(TypeError, match="native layer components"):
        FunctionalBoundaryAdapter(model)
