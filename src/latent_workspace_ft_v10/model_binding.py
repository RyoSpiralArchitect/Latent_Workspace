"""Model-owned, no-cache decoder boundaries for Latent Workspace.

The split operations preserve the V12 execution path. The descriptor identifies
an execution interface, not model weights, empirical parity, or task capability.
Workspace normalizers and route recurrence deliberately do not live here.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import torch
import torch.nn as nn


@dataclass(frozen=True)
class BoundaryDescriptor:
    """Immutable metadata for one residual-stream cut; contains no tensors."""

    schema_version: str
    binding_kind: str
    model_type: str
    model_class: str
    boundary_layer: int
    layer_count: int
    phase: str
    backend: str
    torch_version: str
    transformers_version: str | None
    attention_implementation: str | None
    support_status: str
    cache_policy: str
    position_policy: str
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-compatible metadata, without accessing model weights."""
        result = asdict(self)
        result["limitations"] = list(self.limitations)
        return result

    def fingerprint(self) -> str:
        """Hash the metadata only, not a checkpoint or a numerical result."""
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class FunctionalBoundaryAdapter:
    """No-cache split decoder for the supported causal-LM layouts.

    GPT-2 remains the compatibility path used by the v9 harness. Mistral is a
    strict adapter because its mask and decoder-layer APIs changed between the
    two Transformers releases supported by this source. Unknown Mistral API
    versions fail closed instead of silently changing the split computation.

    Decoder layers are invoked through ``module(...)`` rather than ``forward``.
    Transformers' ``GradientCheckpointingLayer.__call__`` can therefore retain
    activation checkpointing while the model is split at an internal boundary.
    """

    _MISTRAL_TRANSFORMERS_VERSIONS = frozenset({"4.57.6", "5.15.0"})
    _OLMO2_TRANSFORMERS_VERSIONS = frozenset({"4.57.6", "5.15.0"})

    def __init__(self, base_model: nn.Module) -> None:
        self.base_model = base_model
        custom_to = getattr(base_model, "functional_forward_to_boundary", None)
        custom_from = getattr(base_model, "functional_forward_from_boundary", None)
        custom_layers = getattr(base_model, "functional_num_layers", None)
        if callable(custom_to) and callable(custom_from) and custom_layers is not None:
            self._kind = "custom"
            return

        model_type = str(getattr(getattr(base_model, "config", None), "model_type", ""))
        if model_type == "mistral":
            self._kind = "mistral"
            self._validate_mistral_layout()
            return

        if model_type == "olmo2":
            self._kind = "olmo2"
            self._validate_olmo2_layout()
            return

        transformer = getattr(base_model, "transformer", None)
        if model_type == "gpt2" or (
            transformer is not None and getattr(transformer, "h", None) is not None
        ):
            self._kind = "gpt2"
            return

        raise TypeError(
            "functional_workspace requires model_type='gpt2', "
            "model_type='mistral', model_type='olmo2', "
            "or a complete custom functional split interface."
        )

    def describe_boundary(self, boundary_layer: int) -> BoundaryDescriptor:
        """Describe a validated cut without running or mutating the base model.

        Native cuts are after exactly N decoder blocks and before the next
        block (or the native final norm). Custom cuts delegate phase semantics.
        Legacy GPT-2 structural recognition is reported, not silently promoted
        to support for another named model family.
        """
        count = self.layer_count()
        boundary = self._validate_boundary(boundary_layer, count)
        config = getattr(self.base_model, "config", None)
        model_type = str(getattr(config, "model_type", ""))
        try:
            transformers_version = version("transformers")
        except PackageNotFoundError:
            transformers_version = None
        if self._kind == "mistral":
            transformers_version = self._mistral_transformers_version
        if self._kind == "olmo2":
            transformers_version = self._olmo2_transformers_version
        custom = self._kind == "custom"
        structural_gpt2 = self._kind == "gpt2" and model_type != "gpt2"
        return BoundaryDescriptor(
            schema_version="latent_workspace.boundary.v1",
            binding_kind=self._kind,
            model_type=model_type,
            model_class=(
                f"{type(self.base_model).__module__}.{type(self.base_model).__qualname__}"
            ),
            boundary_layer=boundary,
            layer_count=count,
            phase=(
                "custom_protocol_defined"
                if custom
                else "pre_final_norm"
                if boundary == count
                else "pre_decoder_block"
            ),
            backend="torch",
            torch_version=str(torch.__version__),
            transformers_version=transformers_version,
            attention_implementation=getattr(config, "_attn_implementation", None),
            support_status=(
                "delegated_custom_protocol"
                if custom
                else "legacy_gpt2_structural_layout"
                if structural_gpt2
                else "supported_layout"
            ),
            cache_policy="not_exposed_by_custom_protocol" if custom else "disabled_no_cache",
            position_policy="custom_protocol_defined" if custom else "sequential_zero_based",
            limitations=(
                (
                    "Custom encode/decode semantics are supplied by the model.",
                    "The custom interface exposes no cache or position-ID arguments.",
                )
                if custom
                else (
                    "No past-key-value cache or incremental cached decoding.",
                    "No caller-supplied position IDs or attention-output interface.",
                    "Layer calls preserve native checkpointing hooks; parity is run-specific.",
                )
            ),
        )

    @staticmethod
    def _validate_boundary(boundary_layer: int, layer_count: int) -> int:
        boundary = int(boundary_layer)
        if not 0 <= boundary <= layer_count:
            raise ValueError(f"boundary_layer={boundary} outside [0, {layer_count}].")
        return boundary

    def _validate_mistral_layout(self) -> None:
        try:
            import transformers
        except ImportError as exc:
            raise RuntimeError(
                "The Mistral functional boundary adapter requires Transformers."
            ) from exc

        version = str(transformers.__version__)
        if version not in self._MISTRAL_TRANSFORMERS_VERSIONS:
            supported = ", ".join(sorted(self._MISTRAL_TRANSFORMERS_VERSIONS))
            raise RuntimeError(
                "Unsupported Transformers version for the strict Mistral split "
                f"adapter: {version!r}; expected exactly one of {supported}."
            )

        decoder = getattr(self.base_model, "model", None)
        required = ("embed_tokens", "layers", "rotary_emb", "norm")
        missing = [name for name in required if getattr(decoder, name, None) is None]
        if missing:
            raise TypeError(
                "Mistral split adapter could not locate decoder components: " + ", ".join(missing)
            )
        configured_layers = getattr(getattr(decoder, "config", None), "num_hidden_layers", None)
        if configured_layers is None or int(configured_layers) != len(decoder.layers):
            raise ValueError("Mistral decoder layer count does not match config.num_hidden_layers.")
        if self._lm_head() is None:
            raise ValueError("Mistral split adapter could not locate lm_head.")
        self._mistral_transformers_version = version

    def _lm_head(self) -> nn.Module | None:
        head = getattr(self.base_model, "lm_head", None)
        if head is not None:
            return head
        getter = getattr(self.base_model, "get_output_embeddings", None)
        return getter() if callable(getter) else None

    def _validate_olmo2_layout(self) -> None:
        """Keep OLMo2's post-residual-branch and Q/K norms inside native layers."""
        try:
            import transformers
        except ImportError as exc:
            raise RuntimeError("The OLMo2 boundary adapter requires Transformers.") from exc
        runtime_version = str(transformers.__version__)
        if runtime_version not in self._OLMO2_TRANSFORMERS_VERSIONS:
            supported = ", ".join(sorted(self._OLMO2_TRANSFORMERS_VERSIONS))
            raise RuntimeError(
                "Unsupported Transformers version for the strict OLMo2 split "
                f"adapter: {runtime_version!r}; expected exactly one of {supported}."
            )
        decoder = getattr(self.base_model, "model", None)
        required = ("embed_tokens", "layers", "rotary_emb", "norm")
        missing = [name for name in required if getattr(decoder, name, None) is None]
        if missing:
            raise TypeError("OLMo2 split adapter missing decoder components: " + ", ".join(missing))
        configured_layers = getattr(getattr(decoder, "config", None), "num_hidden_layers", None)
        if configured_layers is None or int(configured_layers) != len(decoder.layers):
            raise ValueError("OLMo2 decoder layer count does not match config.num_hidden_layers.")
        for index, layer in enumerate(decoder.layers):
            if any(
                getattr(layer, name, None) is None
                for name in (
                    "self_attn",
                    "mlp",
                    "post_attention_layernorm",
                    "post_feedforward_layernorm",
                )
            ) or any(getattr(layer.self_attn, name, None) is None for name in ("q_norm", "k_norm")):
                raise TypeError(f"OLMo2 split adapter missing native layer components at {index}.")
        if self._lm_head() is None:
            raise ValueError("OLMo2 split adapter could not locate lm_head.")
        self._olmo2_transformers_version = runtime_version

    def layer_count(self) -> int:
        if self._kind == "custom":
            return int(self.base_model.functional_num_layers)
        if self._kind == "mistral":
            return len(self.base_model.model.layers)
        if self._kind == "olmo2":
            return len(self.base_model.model.layers)
        transformer = getattr(self.base_model, "transformer", None)
        blocks = getattr(transformer, "h", None)
        if blocks is None:
            raise TypeError("GPT-2 split adapter could not locate transformer.h.")
        return len(blocks)

    @staticmethod
    def _legacy_gpt2_attention_mask(
        attention_mask: torch.Tensor,
        dtype: torch.dtype,
    ) -> torch.Tensor:
        expanded = attention_mask[:, None, None, :].to(dtype=dtype)
        return (1.0 - expanded) * torch.finfo(dtype).min

    @staticmethod
    def _position_tensors(hidden: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        cache_position = torch.arange(hidden.shape[1], device=hidden.device)
        return cache_position, cache_position.unsqueeze(0)

    @classmethod
    def _gpt2_causal_mask(
        cls,
        transformer: nn.Module,
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
        cache_position: torch.Tensor,
        position_ids: torch.Tensor,
    ) -> torch.Tensor:
        try:
            from transformers.masking_utils import create_causal_mask

            parameters = inspect.signature(create_causal_mask).parameters
            kwargs: dict[str, Any] = {
                "config": transformer.config,
                "attention_mask": attention_mask,
                "past_key_values": None,
                "position_ids": position_ids,
            }
            if "inputs_embeds" in parameters:
                kwargs["inputs_embeds"] = hidden
            elif "input_embeds" in parameters:
                kwargs["input_embeds"] = hidden
            else:
                raise TypeError("Unknown Transformers causal-mask embedding API.")
            if "cache_position" in parameters:
                kwargs["cache_position"] = cache_position
            return create_causal_mask(**kwargs)
        except (ImportError, TypeError):
            # Compatibility with the pre-mask-utils GPT-2 releases used by v9.
            return cls._legacy_gpt2_attention_mask(attention_mask, hidden.dtype)

    @staticmethod
    def _call_gpt2_block(
        block: nn.Module,
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
        cache_position: torch.Tensor,
        position_ids: torch.Tensor,
    ) -> torch.Tensor:
        parameters = inspect.signature(block.forward).parameters
        attempts: tuple[dict[str, Any], ...]
        if "cache_position" in parameters:
            attempts = (
                {
                    "past_key_values": None,
                    "cache_position": cache_position,
                    "attention_mask": attention_mask,
                    "head_mask": None,
                    "encoder_hidden_states": None,
                    "encoder_attention_mask": None,
                    "use_cache": False,
                    "output_attentions": False,
                },
                {
                    "layer_past": None,
                    "attention_mask": attention_mask,
                    "head_mask": None,
                    "encoder_hidden_states": None,
                    "encoder_attention_mask": None,
                    "use_cache": False,
                    "output_attentions": False,
                },
                {
                    "attention_mask": attention_mask,
                    "use_cache": False,
                    "output_attentions": False,
                },
                {"attention_mask": attention_mask},
            )
        else:
            # Transformers 5.x GPT-2 passes the already combined causal mask
            # and sequential position IDs to each block. Avoid sending legacy
            # head/cache keywords through ``**kwargs`` into the attention API.
            attempts = (
                {
                    "past_key_values": None,
                    "attention_mask": attention_mask,
                    "encoder_hidden_states": None,
                    "encoder_attention_mask": None,
                    "use_cache": False,
                    "position_ids": position_ids,
                },
            )
        last_error: Exception | None = None
        for kwargs in attempts:
            try:
                output = block(hidden, **kwargs)
                return output[0] if isinstance(output, (tuple, list)) else output
            except TypeError as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    def _gpt2_encode(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor,
        boundary_layer: int,
    ) -> torch.Tensor:
        transformer = self.base_model.transformer
        blocks = transformer.h
        boundary = self._validate_boundary(boundary_layer, len(blocks))
        token_embeddings = transformer.wte(input_ids)
        cache_position, position_ids = self._position_tensors(token_embeddings)
        hidden = token_embeddings + transformer.wpe(position_ids).to(token_embeddings.device)
        hidden = transformer.drop(hidden)
        causal_mask = self._gpt2_causal_mask(
            transformer, token_embeddings, attention_mask, cache_position, position_ids
        )
        for block in blocks[:boundary]:
            hidden = self._call_gpt2_block(block, hidden, causal_mask, cache_position, position_ids)
        return hidden

    def _gpt2_decode(
        self,
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
        boundary_layer: int,
    ) -> torch.Tensor:
        transformer = self.base_model.transformer
        blocks = transformer.h
        boundary = self._validate_boundary(boundary_layer, len(blocks))
        cache_position, position_ids = self._position_tensors(hidden)
        causal_mask = self._gpt2_causal_mask(
            transformer, hidden, attention_mask, cache_position, position_ids
        )
        for block in blocks[boundary:]:
            hidden = self._call_gpt2_block(block, hidden, causal_mask, cache_position, position_ids)
        head = self._lm_head()
        if head is None:
            raise ValueError("GPT-2 split adapter could not locate lm_head.")
        return head(transformer.ln_f(hidden))

    def _mistral_runtime(
        self,
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, tuple[torch.Tensor, torch.Tensor]]:
        from transformers.masking_utils import (
            create_causal_mask,
            create_sliding_window_causal_mask,
        )

        decoder = self.base_model.model
        cache_position, position_ids = self._position_tensors(hidden)
        mask_function = (
            create_causal_mask
            if decoder.config.sliding_window is None
            else create_sliding_window_causal_mask
        )
        common = {
            "config": decoder.config,
            "attention_mask": attention_mask,
            "past_key_values": None,
            "position_ids": position_ids,
        }
        if self._mistral_transformers_version == "4.57.6":
            causal_mask = mask_function(
                input_embeds=hidden,
                cache_position=cache_position,
                **common,
            )
        else:
            causal_mask = mask_function(inputs_embeds=hidden, **common)
        position_embeddings = decoder.rotary_emb(hidden, position_ids=position_ids)
        return causal_mask, position_ids, position_embeddings

    def _run_mistral_layers(
        self,
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
        layers: Sequence[nn.Module],
    ) -> torch.Tensor:
        causal_mask, position_ids, position_embeddings = self._mistral_runtime(
            hidden, attention_mask
        )
        cache_position = torch.arange(hidden.shape[1], device=hidden.device)
        for layer in layers:
            kwargs: dict[str, Any] = {
                "attention_mask": causal_mask,
                "position_ids": position_ids,
                "past_key_values": None,
                "use_cache": False,
                "position_embeddings": position_embeddings,
            }
            if self._mistral_transformers_version == "4.57.6":
                kwargs["cache_position"] = cache_position
            output = layer(hidden, **kwargs)
            hidden = output[0] if isinstance(output, (tuple, list)) else output
        return hidden

    def _mistral_encode(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor,
        boundary_layer: int,
    ) -> torch.Tensor:
        decoder = self.base_model.model
        boundary = self._validate_boundary(boundary_layer, len(decoder.layers))
        hidden = decoder.embed_tokens(input_ids)
        return self._run_mistral_layers(hidden, attention_mask, decoder.layers[:boundary])

    def _mistral_decode(
        self,
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
        boundary_layer: int,
    ) -> torch.Tensor:
        decoder = self.base_model.model
        boundary = self._validate_boundary(boundary_layer, len(decoder.layers))
        hidden = self._run_mistral_layers(hidden, attention_mask, decoder.layers[boundary:])
        head = self._lm_head()
        assert head is not None
        return head(decoder.norm(hidden))

    def _run_olmo2_layers(
        self,
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
        layers: Sequence[nn.Module],
    ) -> torch.Tensor:
        # Verified against Olmo2Model.forward in both pinned versions. Unlike
        # Mistral, this family always uses create_causal_mask, not sliding-window
        # selection. All post-attention/post-MLP and Q/K norms stay native.
        from transformers.masking_utils import create_causal_mask

        decoder = self.base_model.model
        cache_position, position_ids = self._position_tensors(hidden)
        common = {
            "config": decoder.config,
            "attention_mask": attention_mask,
            "past_key_values": None,
            "position_ids": position_ids,
        }
        if self._olmo2_transformers_version == "4.57.6":
            causal_mask = create_causal_mask(
                input_embeds=hidden, cache_position=cache_position, **common
            )
        else:
            causal_mask = create_causal_mask(inputs_embeds=hidden, **common)
        position_embeddings = decoder.rotary_emb(hidden, position_ids=position_ids)
        for layer in layers:
            kwargs: dict[str, Any] = {
                "attention_mask": causal_mask,
                "position_ids": position_ids,
                "past_key_values": None,
                "use_cache": False,
                "position_embeddings": position_embeddings,
            }
            if self._olmo2_transformers_version == "4.57.6":
                kwargs["cache_position"] = cache_position
            output = layer(hidden, **kwargs)
            hidden = output[0] if isinstance(output, (tuple, list)) else output
        return hidden

    def _olmo2_encode(
        self, input_ids: torch.Tensor, attention_mask: torch.Tensor, boundary_layer: int
    ) -> torch.Tensor:
        decoder = self.base_model.model
        boundary = self._validate_boundary(boundary_layer, len(decoder.layers))
        hidden = decoder.embed_tokens(input_ids)
        return self._run_olmo2_layers(hidden, attention_mask, decoder.layers[:boundary])

    def _olmo2_decode(
        self, hidden: torch.Tensor, attention_mask: torch.Tensor, boundary_layer: int
    ) -> torch.Tensor:
        decoder = self.base_model.model
        boundary = self._validate_boundary(boundary_layer, len(decoder.layers))
        hidden = self._run_olmo2_layers(hidden, attention_mask, decoder.layers[boundary:])
        head = self._lm_head()
        assert head is not None
        return head(decoder.norm(hidden))

    def encode(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor,
        boundary_layer: int,
    ) -> torch.Tensor:
        if self._kind == "custom":
            boundary = self._validate_boundary(boundary_layer, self.layer_count())
            return self.base_model.functional_forward_to_boundary(
                input_ids, attention_mask, boundary
            )
        if self._kind == "mistral":
            return self._mistral_encode(input_ids, attention_mask, boundary_layer)
        if self._kind == "olmo2":
            return self._olmo2_encode(input_ids, attention_mask, boundary_layer)
        return self._gpt2_encode(input_ids, attention_mask, boundary_layer)

    def decode(
        self,
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
        boundary_layer: int,
    ) -> torch.Tensor:
        if self._kind == "custom":
            boundary = self._validate_boundary(boundary_layer, self.layer_count())
            return self.base_model.functional_forward_from_boundary(
                hidden, attention_mask, boundary
            )
        if self._kind == "mistral":
            return self._mistral_decode(hidden, attention_mask, boundary_layer)
        if self._kind == "olmo2":
            return self._olmo2_decode(hidden, attention_mask, boundary_layer)
        return self._gpt2_decode(hidden, attention_mask, boundary_layer)
