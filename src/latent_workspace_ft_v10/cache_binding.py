"""Strict Mistral KV-cache instrumentation for bounded trajectory canaries.

This module owns model- and Transformers-specific cache mechanics.  It does not
define a semantic intervention, choose a task direction, or claim that a cache
displacement is useful.  The first supported surface is deliberately narrow:
an eval-mode, full-attention Mistral using a native ``DynamicCache``.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Literal

import torch
import torch.nn as nn

_SUPPORTED_TRANSFORMERS = frozenset({"4.57.6", "5.15.0"})
_SNAPSHOT_SCHEMA = "latent_workspace.mistral_dynamic_cache.v1"
_PULSE_BOUNDARY = "decoder_layer_input_pre_rmsnorm"
_PULSE_COMPOSITION = "fp32_add_then_cast_to_hidden"


@dataclass(frozen=True, slots=True)
class ActivationPulse:
    """One unit-RMS activation displacement at one decoder-layer input.

    ``scale`` is signed.  ``direction`` is normalized to unit RMS in FP32
    immediately before use; it is not orthogonalized or otherwise changed.
    Composition occurs in FP32 and the result is cast once to the native hidden
    dtype.  A pulse is only admitted for a one-token cached step.
    """

    layer_index: int
    direction: torch.Tensor
    scale: float
    boundary: Literal["decoder_layer_input_pre_rmsnorm"] = _PULSE_BOUNDARY
    composition_dtype: Literal["fp32_add_then_cast_to_hidden"] = _PULSE_COMPOSITION

    def __post_init__(self) -> None:
        if type(self.layer_index) is not int or self.layer_index < 0:
            raise ValueError("layer_index must be a non-negative integer")
        if not isinstance(self.direction, torch.Tensor) or not self.direction.is_floating_point():
            raise ValueError("direction must be a floating-point tensor")
        if self.direction.ndim != 1 or self.direction.numel() == 0:
            raise ValueError("direction must be a nonempty rank-one tensor")
        if not bool(torch.isfinite(self.direction.detach()).all()):
            raise ValueError("direction must be finite")
        if type(self.scale) not in (float, int) or isinstance(self.scale, bool):
            raise ValueError("scale must be a finite nonzero number")
        if not math.isfinite(float(self.scale)) or float(self.scale) == 0.0:
            raise ValueError("scale must be a finite nonzero number")
        if self.boundary != _PULSE_BOUNDARY:
            raise ValueError(f"boundary must be {_PULSE_BOUNDARY!r}")
        if self.composition_dtype != _PULSE_COMPOSITION:
            raise ValueError(f"composition_dtype must be {_PULSE_COMPOSITION!r}")


@dataclass(frozen=True, slots=True)
class CacheSnapshot:
    """Detached in-memory cache snapshot with optional exact history identity."""

    schema_version: str
    adapter_fingerprint: str
    transformers_version: str
    representation: str
    layers: tuple[tuple[torch.Tensor, torch.Tensor], ...]
    seq_length: int
    batch_size: int
    token_ids: torch.Tensor | None
    position_ids: torch.Tensor | None
    attention_mask: torch.Tensor | None
    integrity_sha256: str

    @property
    def has_history(self) -> bool:
        return self.token_ids is not None

    def to_dict(self) -> dict[str, Any]:
        """Return identity and layout metadata, never tensor payloads."""
        return {
            "schema_version": self.schema_version,
            "adapter_fingerprint": self.adapter_fingerprint,
            "transformers_version": self.transformers_version,
            "representation": self.representation,
            "layer_count": len(self.layers),
            "seq_length": self.seq_length,
            "batch_size": self.batch_size,
            "has_history": self.has_history,
            "layer_shapes": [
                {"key": list(key.shape), "value": list(value.shape)} for key, value in self.layers
            ],
            "layer_dtypes": [
                {"key": str(key.dtype), "value": str(value.dtype)} for key, value in self.layers
            ],
            "layer_devices": [
                {"key": str(key.device), "value": str(value.device)} for key, value in self.layers
            ],
            "history_shapes": None
            if not self.has_history
            else {
                "token_ids": list(self.token_ids.shape),
                "position_ids": list(self.position_ids.shape),
                "attention_mask": list(self.attention_mask.shape),
            },
            "integrity_sha256": self.integrity_sha256,
        }


@dataclass(frozen=True, slots=True)
class CacheStepResult:
    """Output of one cache-writing model call."""

    logits: torch.Tensor
    cache: Any
    receipt: dict[str, Any]

    @property
    def pulse(self) -> dict[str, Any]:
        """Compatibility view for the pulse-specific subreceipt."""
        return self.receipt["pulse"]


@dataclass(frozen=True, slots=True)
class FiveCellCaches:
    """Independent caches for the predeclared A--E trajectory comparison."""

    a_base: Any
    b_intact_carried: Any
    c_twin_carried: Any
    d_intact_reset: Any
    e_twin_reset: Any

    @property
    def A(self) -> Any:
        return self.a_base

    @property
    def B(self) -> Any:
        return self.b_intact_carried

    @property
    def C(self) -> Any:
        return self.c_twin_carried

    @property
    def D(self) -> Any:
        return self.d_intact_reset

    @property
    def E(self) -> Any:
        return self.e_twin_reset

    def as_dict(self) -> dict[str, Any]:
        return {
            "A": self.a_base,
            "B": self.b_intact_carried,
            "C": self.c_twin_carried,
            "D": self.d_intact_reset,
            "E": self.e_twin_reset,
        }


class MistralDynamicCacheAdapter:
    """Fail-closed cache and layer-input pulse adapter for pinned Mistral APIs."""

    def __init__(self, model: nn.Module) -> None:
        try:
            import transformers
            from transformers import DynamicCache
        except ImportError as exc:
            raise RuntimeError("Mistral cache instrumentation requires Transformers") from exc

        runtime_version = str(transformers.__version__)
        if runtime_version not in _SUPPORTED_TRANSFORMERS:
            supported = ", ".join(sorted(_SUPPORTED_TRANSFORMERS))
            raise RuntimeError(
                "Unsupported Transformers version for strict Mistral cache instrumentation: "
                f"{runtime_version!r}; expected exactly one of {supported}."
            )
        config = getattr(model, "config", None)
        if str(getattr(config, "model_type", "")) != "mistral":
            raise TypeError("Cache trajectory adapter requires model_type='mistral'")
        decoder = getattr(model, "model", None)
        layers = getattr(decoder, "layers", None)
        if decoder is None or layers is None or getattr(decoder, "embed_tokens", None) is None:
            raise TypeError("Mistral cache adapter could not locate the native decoder layout")
        configured_layers = getattr(config, "num_hidden_layers", None)
        if configured_layers is None or int(configured_layers) != len(layers):
            raise ValueError("Mistral decoder layer count does not match config.num_hidden_layers")
        if getattr(config, "sliding_window", None) is not None:
            raise ValueError(
                "The first cache trajectory canary requires full attention, not sliding"
            )
        if getattr(config, "attention_chunk_size", None) is not None:
            raise ValueError("The first cache trajectory canary rejects chunked attention")
        layer_types = getattr(config, "layer_types", None)
        if layer_types is not None and any(kind != "full_attention" for kind in layer_types):
            raise ValueError("The first cache trajectory canary requires all full-attention layers")
        attention_implementation = getattr(config, "_attn_implementation", None)
        if attention_implementation not in ("eager", "sdpa"):
            raise ValueError("Cache trajectory adapter supports only eager or SDPA attention")
        if not bool(getattr(config, "use_return_dict", True)):
            raise ValueError("Mistral cache adapter requires dictionary model outputs")
        for index, layer in enumerate(layers):
            if (
                getattr(layer, "input_layernorm", None) is None
                or getattr(layer, "self_attn", None) is None
            ):
                raise TypeError(f"Mistral decoder layer {index} lacks the required native boundary")
            native_index = getattr(layer.self_attn, "layer_idx", None)
            if native_index is not None and int(native_index) != index:
                raise ValueError(f"Mistral attention layer index mismatch at {index}")

        model_parameters = inspect.signature(model.forward).parameters
        required_forward = {"input_ids", "attention_mask", "position_ids", "past_key_values"}
        if not required_forward.issubset(model_parameters):
            raise TypeError("Mistral model forward signature lacks required cache inputs")
        has_cache_position = "cache_position" in model_parameters
        if has_cache_position != (runtime_version == "4.57.6"):
            raise TypeError("Mistral cache-position signature does not match the pinned version")

        self.model = model
        self._dynamic_cache_type = DynamicCache
        self.transformers_version = runtime_version
        self.representation = (
            "dynamic_cache_iterator_pairs"
            if runtime_version == "4.57.6"
            else "dynamic_cache_iterator_triples_no_sliding"
        )
        self.layer_count = len(layers)
        self.hidden_size = int(config.hidden_size)
        descriptor = {
            "schema_version": _SNAPSHOT_SCHEMA,
            "model_type": "mistral",
            "model_class": f"{type(model).__module__}.{type(model).__qualname__}",
            "layer_count": self.layer_count,
            "hidden_size": self.hidden_size,
            "transformers_version": runtime_version,
            "torch_version": str(torch.__version__),
            "attention_implementation": attention_implementation,
            "cache_representation": self.representation,
            "sliding_window": None,
            "pulse_boundary": _PULSE_BOUNDARY,
            "pulse_composition": _PULSE_COMPOSITION,
        }
        self.descriptor = descriptor
        self.adapter_fingerprint = hashlib.sha256(
            json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def describe(self) -> dict[str, Any]:
        """Return immutable-contract metadata, not a run or parity result."""
        return {
            **self.descriptor,
            "adapter_fingerprint": self.adapter_fingerprint,
            "support_status": "strict_bounded_mechanical_canary_only",
            "limitations": [
                "No sliding, chunked, offloaded, static, quantized, or recurrent cache.",
                "No semantic direction, training, generation, or capability claim.",
                "Cache snapshots are in-memory and bound to one exact adapter fingerprint.",
            ],
        }

    def new_cache(self) -> Any:
        """Create an empty native cache and validate its representation."""
        cache = self._dynamic_cache_type(config=self.model.config)
        self._extract_layers(cache, require_initialized=False)
        return cache

    def clone(self, cache: Any) -> Any:
        """Return an independent full cache without mutating the input."""
        layers = self._extract_layers(cache, require_initialized=True)
        return self._build_cache(
            tuple((key.detach().clone(), value.detach().clone()) for key, value in layers)
        )

    def snapshot(
        self,
        cache: Any,
        *,
        token_ids: torch.Tensor | list[int] | None = None,
        position_ids: torch.Tensor | list[int] | None = None,
        attention_mask: torch.Tensor | list[int] | None = None,
    ) -> CacheSnapshot:
        """Clone a cache and bind it to an optional exact token-history identity."""
        layers = tuple(
            (key.detach().clone(), value.detach().clone())
            for key, value in self._extract_layers(cache, require_initialized=True)
        )
        seq_length = int(layers[0][0].shape[-2])
        batch_size = int(layers[0][0].shape[0])
        history_device = layers[0][0].device
        token_ids = self._coerce_history_tensor(token_ids, history_device)
        position_ids = self._coerce_history_tensor(position_ids, history_device)
        attention_mask = self._coerce_history_tensor(attention_mask, history_device)
        history = self._validate_history(
            token_ids,
            position_ids,
            attention_mask,
            batch_size=batch_size,
            seq_length=seq_length,
        )
        if history is not None and any(value.device != history_device for value in history):
            raise ValueError("Snapshot history tensors must be on the cache device")
        snapshot = CacheSnapshot(
            schema_version=_SNAPSHOT_SCHEMA,
            adapter_fingerprint=self.adapter_fingerprint,
            transformers_version=self.transformers_version,
            representation=self.representation,
            layers=layers,
            seq_length=seq_length,
            batch_size=batch_size,
            token_ids=None if history is None else history[0].clone(),
            position_ids=None if history is None else history[1].clone(),
            attention_mask=None if history is None else history[2].clone(),
            integrity_sha256="",
        )
        digest = self._snapshot_digest(snapshot)
        return CacheSnapshot(
            schema_version=snapshot.schema_version,
            adapter_fingerprint=snapshot.adapter_fingerprint,
            transformers_version=snapshot.transformers_version,
            representation=snapshot.representation,
            layers=snapshot.layers,
            seq_length=snapshot.seq_length,
            batch_size=snapshot.batch_size,
            token_ids=snapshot.token_ids,
            position_ids=snapshot.position_ids,
            attention_mask=snapshot.attention_mask,
            integrity_sha256=digest,
        )

    def restore(self, snapshot: CacheSnapshot) -> Any:
        """Validate and materialize an independent cache from a snapshot."""
        self._validate_snapshot(snapshot)
        return self._build_cache(
            tuple((key.detach().clone(), value.detach().clone()) for key, value in snapshot.layers)
        )

    def replace(self, target: CacheSnapshot, source: CacheSnapshot) -> Any:
        """Replace all target K/V with source K/V for the exact same history.

        This is a functional replacement: the input snapshots and any caches
        they were made from are not mutated.
        """
        self._validate_snapshot(target, require_history=True)
        self._validate_snapshot(source, require_history=True)
        self._require_same_history(target, source)
        self._require_same_layout(target.layers, source.layers)
        return self.restore(source)

    def five_cells(
        self,
        base: CacheSnapshot,
        intact: CacheSnapshot,
        twin: CacheSnapshot,
    ) -> FiveCellCaches:
        """Build A/B/C carried cells and D/E reset-to-base cells."""
        for candidate in (base, intact, twin):
            self._validate_snapshot(candidate, require_history=True)
        self._require_same_history(base, intact)
        self._require_same_history(base, twin)
        self._require_same_layout(base.layers, intact.layers)
        self._require_same_layout(base.layers, twin.layers)
        return FiveCellCaches(
            a_base=self.restore(base),
            b_intact_carried=self.restore(intact),
            c_twin_carried=self.restore(twin),
            d_intact_reset=self.replace(intact, base),
            e_twin_reset=self.replace(twin, base),
        )

    def prefill(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor,
        position_ids: torch.Tensor,
    ) -> CacheStepResult:
        """Write a fixed nonempty prefix once, without an activation pulse."""
        self._validate_forward_inputs(
            input_ids,
            attention_mask,
            position_ids,
            past_length=0,
            one_token=False,
        )
        return self._forward(
            input_ids=input_ids,
            attention_mask=attention_mask,
            position_ids=position_ids,
            cache=self.new_cache(),
            pulse=None,
            clone_cache=False,
        )

    def step(
        self,
        input_token: torch.Tensor,
        cache: Any,
        total_attention_mask: torch.Tensor,
        position_id: torch.Tensor,
        *,
        pulse: ActivationPulse | None = None,
    ) -> CacheStepResult:
        """Advance an independent cache by exactly one fixed teacher-forced token."""
        past_length = self._cache_length(cache)
        self._validate_forward_inputs(
            input_token,
            total_attention_mask,
            position_id,
            past_length=past_length,
            one_token=True,
        )
        if pulse is not None:
            if not isinstance(pulse, ActivationPulse):
                raise ValueError("pulse must be an ActivationPulse or None")
            if pulse.layer_index >= self.layer_count:
                raise ValueError(f"pulse layer {pulse.layer_index} outside model layer range")
            if pulse.direction.numel() != self.hidden_size:
                raise ValueError("pulse direction width does not match model hidden_size")
        return self._forward(
            input_ids=input_token,
            attention_mask=total_attention_mask,
            position_ids=position_id,
            cache=cache,
            pulse=pulse,
            clone_cache=True,
        )

    def stats(self, cache: Any) -> dict[str, Any]:
        """Return JSON-compatible cache norms and last-position norms."""
        layers = self._extract_layers(cache, require_initialized=True)
        per_layer = []
        for index, (key, value) in enumerate(layers):
            key32 = key.detach().float()
            value32 = value.detach().float()
            per_layer.append(
                {
                    "layer": index,
                    "key_shape": list(key.shape),
                    "value_shape": list(value.shape),
                    "key_dtype": str(key.dtype),
                    "value_dtype": str(value.dtype),
                    "device": str(key.device),
                    "key_l2": float(torch.linalg.vector_norm(key32).item()),
                    "value_l2": float(torch.linalg.vector_norm(value32).item()),
                    "key_last_position_l2": float(
                        torch.linalg.vector_norm(key32[..., -1, :]).item()
                    ),
                    "value_last_position_l2": float(
                        torch.linalg.vector_norm(value32[..., -1, :]).item()
                    ),
                }
            )
        return {
            "schema_version": "latent_workspace.cache_stats.v1",
            "adapter_fingerprint": self.adapter_fingerprint,
            "representation": self.representation,
            "layer_count": len(layers),
            "seq_length": int(layers[0][0].shape[-2]),
            "batch_size": int(layers[0][0].shape[0]),
            "per_layer": per_layer,
        }

    def difference(self, left: Any, right: Any) -> dict[str, Any]:
        """Return FP32 K/V displacement, including the newest cached position."""
        left_layers = self._extract_layers(left, require_initialized=True)
        right_layers = self._extract_layers(right, require_initialized=True)
        self._require_same_layout(left_layers, right_layers)
        total_squared = 0.0
        maximum = 0.0
        nonzero = 0
        per_layer = []
        exact_equal = True
        for index, ((left_key, left_value), (right_key, right_value)) in enumerate(
            zip(left_layers, right_layers, strict=True)
        ):
            row: dict[str, Any] = {"layer": index}
            for name, first, second in (
                ("key", left_key, right_key),
                ("value", left_value, right_value),
            ):
                delta = first.detach().float() - second.detach().float()
                squared = float(torch.sum(delta * delta).item())
                max_abs = float(delta.abs().max().item())
                count = int(torch.count_nonzero(delta).item())
                last = delta[..., -1, :]
                row[f"{name}_l2"] = math.sqrt(squared)
                row[f"{name}_max_abs"] = max_abs
                row[f"{name}_nonzero"] = count
                row[f"{name}_last_position_l2"] = float(torch.linalg.vector_norm(last).item())
                row[f"{name}_last_position_max_abs"] = float(last.abs().max().item())
                total_squared += squared
                maximum = max(maximum, max_abs)
                nonzero += count
                exact_equal = exact_equal and bool(torch.equal(first, second))
            per_layer.append(row)
        return {
            "schema_version": "latent_workspace.cache_difference.v1",
            "adapter_fingerprint": self.adapter_fingerprint,
            "representation": self.representation,
            "layer_count": len(left_layers),
            "seq_length": int(left_layers[0][0].shape[-2]),
            "aggregate_l2": math.sqrt(total_squared),
            "aggregate_max_abs": maximum,
            "nonzero_count": nonzero,
            "exact_equal": exact_equal,
            "per_layer": per_layer,
        }

    def position_fingerprints(self, cache: Any, position: int) -> dict[str, Any]:
        """Hash one stored K/V position in every layer without exposing mutable views."""
        layers = self._extract_layers(cache, require_initialized=True)
        seq_length = int(layers[0][0].shape[-2])
        if type(position) is not int or not 0 <= position < seq_length:
            raise ValueError(f"cache position must be in [0, {seq_length})")
        return {
            "schema_version": "latent_workspace.cache_position_fingerprints.v1",
            "adapter_fingerprint": self.adapter_fingerprint,
            "position": position,
            "seq_length": seq_length,
            "layers": [
                {
                    "layer": index,
                    "key_sha256": _tensor_digest(key[..., position : position + 1, :]),
                    "value_sha256": _tensor_digest(value[..., position : position + 1, :]),
                }
                for index, (key, value) in enumerate(layers)
            ],
        }

    def _forward(
        self,
        *,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor,
        position_ids: torch.Tensor,
        cache: Any,
        pulse: ActivationPulse | None,
        clone_cache: bool,
    ) -> CacheStepResult:
        if self.model.training:
            raise RuntimeError("Cache trajectory calls require model.eval()")
        self._assert_model_device(input_ids.device)
        before_length = self._cache_length(cache)
        before_layers = (
            () if before_length == 0 else self._extract_layers(cache, require_initialized=True)
        )
        working_cache = self.clone(cache) if clone_cache else cache
        input_copies = tuple(
            tensor.detach().clone() for tensor in (input_ids, attention_mask, position_ids)
        )
        pulse_state: dict[str, Any] = {"applied": False, "call_count": 0}
        handle = None
        if pulse is not None:
            handle = self.model.model.layers[pulse.layer_index].register_forward_pre_hook(
                self._pulse_hook(pulse, pulse_state), with_kwargs=True, prepend=True
            )
        kwargs: dict[str, Any] = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "position_ids": position_ids,
            "past_key_values": working_cache,
            "use_cache": True,
        }
        if self.transformers_version == "4.57.6":
            if not bool(torch.equal(position_ids, position_ids[:1].expand_as(position_ids))):
                raise ValueError("4.57.6 cache_position requires identical positions across batch")
            kwargs["cache_position"] = position_ids[0]
        try:
            with torch.inference_mode():
                outputs = self.model(**kwargs)
        finally:
            if handle is not None:
                handle.remove()
        for original, copied, name in zip(
            (input_ids, attention_mask, position_ids),
            input_copies,
            ("input_ids", "attention_mask", "position_ids"),
            strict=True,
        ):
            if not torch.equal(original, copied):
                raise RuntimeError(f"Native model mutated {name}")
        if pulse is not None and pulse_state["call_count"] != 1:
            raise RuntimeError("Activation pulse hook did not run exactly once")
        output_cache = getattr(outputs, "past_key_values", None)
        if output_cache is None:
            raise RuntimeError("Mistral did not return a cache under use_cache=True")
        after_length = self._cache_length(output_cache)
        expected_length = before_length + input_ids.shape[1]
        if after_length != expected_length:
            raise RuntimeError(
                f"Cache length advanced to {after_length}, expected {expected_length}"
            )
        after_layers = self._extract_layers(output_cache, require_initialized=True)
        if before_length:
            for index, ((before_key, before_value), (after_key, after_value)) in enumerate(
                zip(before_layers, after_layers, strict=True)
            ):
                if not torch.equal(
                    before_key, after_key[..., :before_length, :]
                ) or not torch.equal(before_value, after_value[..., :before_length, :]):
                    raise RuntimeError(f"Native cache rewrote the stored prefix at layer {index}")
        logits = getattr(outputs, "logits", None)
        if not isinstance(logits, torch.Tensor) or logits.shape[:2] != input_ids.shape:
            raise RuntimeError("Mistral returned malformed logits")
        if not bool(torch.isfinite(logits).all()):
            raise RuntimeError("Mistral returned non-finite logits")
        receipt = {
            "schema_version": "latent_workspace.cache_step.v1",
            "adapter_fingerprint": self.adapter_fingerprint,
            "transformers_version": self.transformers_version,
            "representation": self.representation,
            "input_ids_sha256": _tensor_digest(input_ids),
            "position_ids_sha256": _tensor_digest(position_ids),
            "attention_mask_sha256": _tensor_digest(attention_mask),
            "input_shape": list(input_ids.shape),
            "cache_length_before": before_length,
            "cache_length_after": after_length,
            "cache_input_mutated": False,
            "cache_prefix_exact": True,
            "token_position_mask_mutated": False,
            "pulse": dict(pulse_state),
        }
        return CacheStepResult(logits=logits.detach().clone(), cache=output_cache, receipt=receipt)

    def _pulse_hook(self, pulse: ActivationPulse, state: dict[str, Any]):
        def hook(
            module: nn.Module,
            args: tuple[Any, ...],
            kwargs: dict[str, Any],
        ) -> tuple[tuple[Any, ...], dict[str, Any]]:
            del module
            state["call_count"] += 1
            if state["call_count"] != 1:
                raise RuntimeError("Activation pulse boundary was invoked more than once")
            if args and isinstance(args[0], torch.Tensor):
                hidden = args[0]
                location = "args"
            else:
                hidden = kwargs.get("hidden_states")
                location = "kwargs"
            if not isinstance(hidden, torch.Tensor) or not hidden.is_floating_point():
                raise TypeError("Mistral decoder layer input was not a floating tensor")
            if hidden.ndim != 3 or hidden.shape[1] != 1 or hidden.shape[-1] != self.hidden_size:
                raise ValueError("Activation pulse requires [batch, 1, hidden_size] layer input")
            direction = pulse.direction.detach().to(device=hidden.device, dtype=torch.float32)
            direction_l2 = torch.linalg.vector_norm(direction)
            direction_rms = torch.sqrt(torch.mean(direction * direction))
            if (
                not bool(torch.isfinite(direction_l2))
                or not bool(torch.isfinite(direction_rms))
                or float(direction_rms.item()) == 0.0
            ):
                raise ValueError("Pulse direction became non-finite or zero on the model device")
            unit_rms = direction / direction_rms
            unit_l2 = direction / direction_l2
            requested = unit_rms.view(1, 1, -1) * float(pulse.scale)
            modified = (hidden.float() + requested).to(dtype=hidden.dtype)
            actual = modified.float() - hidden.float()
            requested_l2 = abs(float(pulse.scale)) * math.sqrt(hidden.numel())
            state.update(
                {
                    "applied": True,
                    "layer_index": pulse.layer_index,
                    "boundary": pulse.boundary,
                    "composition_dtype": pulse.composition_dtype,
                    "scale": float(pulse.scale),
                    "direction_l2": float(direction_l2.item()),
                    "direction_rms": float(direction_rms.item()),
                    "normalized_direction_rms": 1.0,
                    "requested_delta_rms": abs(float(pulse.scale)),
                    "requested_delta_l2": requested_l2,
                    "actual_delta_l2": float(torch.linalg.vector_norm(actual).item()),
                    "actual_delta_rms": float(torch.sqrt(torch.mean(actual * actual)).item()),
                    "actual_signed_projection": float(
                        torch.sum(actual * unit_l2.view(1, 1, -1)).item()
                    ),
                    "signed_projection_basis": "provided_direction_normalized_to_unit_l2",
                    "hidden_dtype": str(hidden.dtype),
                    "hidden_shape": list(hidden.shape),
                }
            )
            if location == "args":
                return (modified, *args[1:]), kwargs
            updated_kwargs = dict(kwargs)
            updated_kwargs["hidden_states"] = modified
            return args, updated_kwargs

        return hook

    def _extract_layers(
        self,
        cache: Any,
        *,
        require_initialized: bool,
    ) -> tuple[tuple[torch.Tensor, torch.Tensor], ...]:
        if type(cache) is not self._dynamic_cache_type:
            raise TypeError("Only an exact Transformers DynamicCache is admitted")
        if bool(getattr(cache, "offloading", False)):
            raise ValueError("Offloaded caches are not admitted by the first trajectory canary")
        if len(cache) != self.layer_count:
            raise ValueError("DynamicCache layer count does not match the Mistral decoder")
        sliding = getattr(cache, "is_sliding", None)
        if (
            sliding is None
            or len(sliding) != self.layer_count
            or any(bool(value) for value in sliding)
        ):
            raise ValueError("Only non-sliding DynamicCache layers are admitted")
        native_layers = getattr(cache, "layers", None)
        if native_layers is None or any(
            type(layer).__name__ != "DynamicLayer" for layer in native_layers
        ):
            raise TypeError("DynamicCache contains a nonstandard layer representation")
        expected_arity = 2 if self.transformers_version == "4.57.6" else 3
        extracted: list[tuple[torch.Tensor, torch.Tensor]] = []
        seen_uninitialized = False
        for index, entry in enumerate(cache):
            if not isinstance(entry, tuple) or len(entry) != expected_arity:
                raise TypeError("DynamicCache iterator layout does not match the pinned version")
            if expected_arity == 3 and entry[2] is not None:
                raise ValueError("Sliding-window cache metadata is not admitted")
            key, value = entry[:2]
            if key is None and value is None:
                seen_uninitialized = True
                continue
            if not isinstance(key, torch.Tensor) or not isinstance(value, torch.Tensor):
                raise TypeError(f"Cache layer {index} does not contain a K/V tensor pair")
            if seen_uninitialized:
                raise ValueError("Cache initialization is inconsistent across layers")
            if key.ndim != 4 or value.ndim != 4:
                raise ValueError(f"Cache layer {index} K/V tensors must be rank four")
            if key.shape != value.shape:
                raise ValueError(f"Cache layer {index} K/V shapes differ")
            if key.dtype != value.dtype or key.device != value.device:
                raise ValueError(f"Cache layer {index} K/V dtype or device differs")
            if not key.is_floating_point() or not value.is_floating_point():
                raise ValueError(f"Cache layer {index} K/V must be floating tensors")
            if key.shape[-2] <= 0:
                raise ValueError(f"Cache layer {index} has an empty initialized sequence")
            if not bool(torch.isfinite(key).all()) or not bool(torch.isfinite(value).all()):
                raise ValueError(f"Cache layer {index} contains non-finite values")
            extracted.append((key, value))
        if require_initialized and len(extracted) != self.layer_count:
            raise ValueError("DynamicCache must be initialized at every decoder layer")
        if not require_initialized and extracted and len(extracted) != self.layer_count:
            raise ValueError("DynamicCache is only partially initialized")
        if extracted:
            first_shape = extracted[0][0].shape
            first_dtype = extracted[0][0].dtype
            first_device = extracted[0][0].device
            for index, (key, value) in enumerate(extracted[1:], 1):
                if key.shape[0] != first_shape[0] or key.shape[-2] != first_shape[-2]:
                    raise ValueError(f"Cache layer {index} batch or sequence length differs")
                if value.shape[0] != first_shape[0] or value.shape[-2] != first_shape[-2]:
                    raise ValueError(f"Cache value layer {index} batch or sequence length differs")
                if key.dtype != first_dtype or key.device != first_device:
                    raise ValueError(f"Cache layer {index} dtype or device differs")
            for index in range(self.layer_count):
                if int(cache.get_seq_length(index)) != int(first_shape[-2]):
                    raise ValueError(f"Cache public sequence length differs at layer {index}")
        return tuple(extracted)

    def _build_cache(self, layers: tuple[tuple[torch.Tensor, torch.Tensor], ...]) -> Any:
        cache = self._dynamic_cache_type(ddp_cache_data=layers)
        extracted = self._extract_layers(cache, require_initialized=True)
        self._require_same_layout(layers, extracted)
        for (expected_key, expected_value), (actual_key, actual_value) in zip(
            layers, extracted, strict=True
        ):
            if not torch.equal(expected_key, actual_key) or not torch.equal(
                expected_value, actual_value
            ):
                raise RuntimeError("DynamicCache public reconstruction changed K/V values")
            aliases_key = expected_key.data_ptr() == actual_key.data_ptr()
            aliases_value = expected_value.data_ptr() == actual_value.data_ptr()
            if aliases_key or aliases_value:
                raise RuntimeError("DynamicCache reconstruction aliased source tensor storage")
        return cache

    def _cache_length(self, cache: Any) -> int:
        layers = self._extract_layers(cache, require_initialized=False)
        return 0 if not layers else int(layers[0][0].shape[-2])

    def _validate_forward_inputs(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor,
        position_ids: torch.Tensor,
        *,
        past_length: int,
        one_token: bool,
    ) -> None:
        if not isinstance(input_ids, torch.Tensor) or input_ids.dtype != torch.long:
            raise ValueError("input_ids must be a torch.long tensor")
        if input_ids.ndim != 2 or input_ids.shape[0] <= 0 or input_ids.shape[1] <= 0:
            raise ValueError("input_ids must have nonempty [batch, sequence] shape")
        if one_token and input_ids.shape[1] != 1:
            raise ValueError("Cached trajectory steps admit exactly one input token")
        if not isinstance(position_ids, torch.Tensor) or position_ids.dtype != torch.long:
            raise ValueError("position_ids must be a torch.long tensor")
        if position_ids.shape != input_ids.shape:
            raise ValueError("position_ids must match the input token shape")
        if not isinstance(attention_mask, torch.Tensor) or attention_mask.ndim != 2:
            raise ValueError("attention_mask must be a rank-two tensor")
        expected_mask_shape = (input_ids.shape[0], past_length + input_ids.shape[1])
        if tuple(attention_mask.shape) != expected_mask_shape:
            raise ValueError(
                f"attention_mask shape {tuple(attention_mask.shape)} != {expected_mask_shape}"
            )
        if input_ids.device != position_ids.device or input_ids.device != attention_mask.device:
            raise ValueError("tokens, positions, and attention mask must share a device")
        if attention_mask.dtype not in (torch.bool, torch.long, torch.int32, torch.int64):
            raise ValueError("attention_mask must have boolean or integer dtype")
        if not bool(torch.all(attention_mask == 1)):
            raise ValueError("The first cache trajectory canary admits only unpadded histories")
        expected_positions = (
            torch.arange(
                past_length,
                past_length + input_ids.shape[1],
                device=position_ids.device,
                dtype=torch.long,
            )
            .unsqueeze(0)
            .expand_as(position_ids)
        )
        if not torch.equal(position_ids, expected_positions):
            raise ValueError("position_ids must be explicit contiguous zero-based cache positions")
        vocab_size = int(getattr(self.model.config, "vocab_size", 0))
        if bool(torch.any(input_ids < 0)) or bool(torch.any(input_ids >= vocab_size)):
            raise ValueError("input_ids contain values outside the model vocabulary")

    def _validate_history(
        self,
        token_ids: torch.Tensor | None,
        position_ids: torch.Tensor | None,
        attention_mask: torch.Tensor | None,
        *,
        batch_size: int,
        seq_length: int,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor] | None:
        supplied = tuple(value is not None for value in (token_ids, position_ids, attention_mask))
        if not any(supplied):
            return None
        if not all(supplied):
            raise ValueError("Snapshot history requires tokens, positions, and mask together")
        assert token_ids is not None and position_ids is not None and attention_mask is not None
        self._validate_forward_inputs(
            token_ids,
            attention_mask,
            position_ids,
            past_length=0,
            one_token=False,
        )
        if tuple(token_ids.shape) != (batch_size, seq_length):
            raise ValueError("Snapshot history shape does not match cache batch/sequence")
        return token_ids, position_ids, attention_mask

    @staticmethod
    def _coerce_history_tensor(
        value: torch.Tensor | list[int] | None,
        device: torch.device,
    ) -> torch.Tensor | None:
        if value is None or isinstance(value, torch.Tensor):
            return value
        if not isinstance(value, list) or not value or any(type(item) is not int for item in value):
            raise ValueError("Snapshot list histories must be nonempty integer lists")
        return torch.tensor([value], device=device, dtype=torch.long)

    def _validate_snapshot(
        self,
        snapshot: CacheSnapshot,
        *,
        require_history: bool = False,
    ) -> None:
        if not isinstance(snapshot, CacheSnapshot):
            raise TypeError("Expected a CacheSnapshot")
        if snapshot.schema_version != _SNAPSHOT_SCHEMA:
            raise ValueError("Unknown cache snapshot schema")
        if snapshot.adapter_fingerprint != self.adapter_fingerprint:
            raise ValueError("Cache snapshot was produced by a different adapter contract")
        if snapshot.transformers_version != self.transformers_version:
            raise ValueError("Cache snapshot Transformers version differs")
        if snapshot.representation != self.representation:
            raise ValueError("Cache snapshot representation differs")
        if len(snapshot.layers) != self.layer_count:
            raise ValueError("Cache snapshot layer count differs")
        self._require_same_layout(snapshot.layers, snapshot.layers)
        if snapshot.seq_length <= 0 or snapshot.batch_size <= 0:
            raise ValueError("Cache snapshot has invalid dimensions")
        expected_heads = int(self.model.config.num_key_value_heads)
        expected_head_dim = int(
            getattr(self.model.config, "head_dim", None)
            or self.hidden_size // int(self.model.config.num_attention_heads)
        )
        first_dtype = snapshot.layers[0][0].dtype
        first_device = snapshot.layers[0][0].device
        for index, (key, value) in enumerate(snapshot.layers):
            if not isinstance(key, torch.Tensor) or not isinstance(value, torch.Tensor):
                raise TypeError(f"Cache snapshot layer {index} is not a tensor pair")
            expected_shape = (
                snapshot.batch_size,
                expected_heads,
                snapshot.seq_length,
                expected_head_dim,
            )
            if tuple(key.shape) != expected_shape or tuple(value.shape) != expected_shape:
                raise ValueError(f"Cache snapshot K/V shape differs at layer {index}")
            if key.dtype != value.dtype or key.device != value.device:
                raise ValueError(f"Cache snapshot K/V dtype or device differs at layer {index}")
            if key.dtype != first_dtype or key.device != first_device:
                raise ValueError(f"Cache snapshot layer dtype or device differs at {index}")
            if not key.is_floating_point() or not value.is_floating_point():
                raise ValueError(f"Cache snapshot K/V is not floating at layer {index}")
            if key.shape[0] != snapshot.batch_size or key.shape[-2] != snapshot.seq_length:
                raise ValueError(f"Cache snapshot dimensions differ at layer {index}")
            if not bool(torch.isfinite(key).all()) or not bool(torch.isfinite(value).all()):
                raise ValueError(f"Cache snapshot contains non-finite values at layer {index}")
        history = self._validate_history(
            snapshot.token_ids,
            snapshot.position_ids,
            snapshot.attention_mask,
            batch_size=snapshot.batch_size,
            seq_length=snapshot.seq_length,
        )
        if history is not None and any(value.device != first_device for value in history):
            raise ValueError("Cache snapshot history and K/V devices differ")
        if require_history and not snapshot.has_history:
            raise ValueError("This cache operation requires exact history identity")
        if self._snapshot_digest(snapshot) != snapshot.integrity_sha256:
            raise ValueError("Cache snapshot integrity digest mismatch")

    @staticmethod
    def _require_same_history(left: CacheSnapshot, right: CacheSnapshot) -> None:
        if not left.has_history or not right.has_history:
            raise ValueError("Cache replacement requires exact history identity")
        for name in ("token_ids", "position_ids", "attention_mask"):
            if not torch.equal(getattr(left, name), getattr(right, name)):
                raise ValueError(f"Cache histories differ in {name}")

    @staticmethod
    def _require_same_layout(
        left: tuple[tuple[torch.Tensor, torch.Tensor], ...],
        right: tuple[tuple[torch.Tensor, torch.Tensor], ...],
    ) -> None:
        if len(left) != len(right):
            raise ValueError("Cache layer counts differ")
        for index, ((left_key, left_value), (right_key, right_value)) in enumerate(
            zip(left, right, strict=True)
        ):
            for kind, first, second in (
                ("key", left_key, right_key),
                ("value", left_value, right_value),
            ):
                if not isinstance(first, torch.Tensor) or not isinstance(second, torch.Tensor):
                    raise TypeError(f"Cache {kind} layer {index} is not a tensor")
                if first.shape != second.shape:
                    raise ValueError(f"Cache {kind} shape differs at layer {index}")
                if first.dtype != second.dtype:
                    raise ValueError(f"Cache {kind} dtype differs at layer {index}")
                if first.device != second.device:
                    raise ValueError(f"Cache {kind} device differs at layer {index}")

    def _snapshot_digest(self, snapshot: CacheSnapshot) -> str:
        digest = hashlib.sha256()
        metadata = {
            "schema_version": snapshot.schema_version,
            "adapter_fingerprint": snapshot.adapter_fingerprint,
            "transformers_version": snapshot.transformers_version,
            "representation": snapshot.representation,
            "seq_length": snapshot.seq_length,
            "batch_size": snapshot.batch_size,
            "has_history": snapshot.has_history,
        }
        digest.update(json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode())
        for key, value in snapshot.layers:
            _update_tensor_digest(digest, key)
            _update_tensor_digest(digest, value)
        if snapshot.has_history:
            assert snapshot.token_ids is not None
            assert snapshot.position_ids is not None
            assert snapshot.attention_mask is not None
            _update_tensor_digest(digest, snapshot.token_ids)
            _update_tensor_digest(digest, snapshot.position_ids)
            _update_tensor_digest(digest, snapshot.attention_mask)
        return digest.hexdigest()

    def _assert_model_device(self, device: torch.device) -> None:
        devices = {parameter.device for parameter in self.model.parameters()}
        if len(devices) != 1 or next(iter(devices)) != device:
            raise ValueError("Cache trajectory canary requires one model/input device")


def _update_tensor_digest(digest: Any, tensor: torch.Tensor) -> None:
    detached = tensor.detach().contiguous()
    header = {
        "dtype": str(detached.dtype),
        "shape": list(detached.shape),
        "device": str(detached.device),
    }
    digest.update(json.dumps(header, sort_keys=True, separators=(",", ":")).encode())
    digest.update(detached.view(torch.uint8).cpu().numpy().tobytes())


def _tensor_digest(tensor: torch.Tensor) -> str:
    digest = hashlib.sha256()
    _update_tensor_digest(digest, tensor)
    return digest.hexdigest()


def runtime_transformers_version() -> str | None:
    """Small metadata helper used without importing Transformers eagerly."""
    try:
        return version("transformers")
    except PackageNotFoundError:
        return None
