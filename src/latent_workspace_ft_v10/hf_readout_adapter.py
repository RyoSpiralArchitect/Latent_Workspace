"""Explicit, eager/no-cache HF adapter preserving the model's entire forward.

Native normalization and post-head transformations (e.g. Gemma2 softcapping)
are executed by the original model, never reconstructed by the workspace.
Temporary hooks bind the single native full-sequence head invocation. This is
an exclusive, uncompiled model-instance API, not a generic concurrent serving
or KV-cache integration. It does not own, freeze, copy or register parameters.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import threading
import weakref
from collections.abc import Callable

import torch
import transformers
from torch import nn

from .readout_transport import TransportReadout, inject_last
from .v15_full_update import validate_token_tuple
from .v15_readout import NativeReadoutResult, _finite

_LOCKS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_REGISTRY_LOCK = threading.Lock()


def _config_hash(base):
    return hashlib.sha256(json.dumps(base.config.to_dict(), sort_keys=True).encode()).hexdigest()


class HFNativeReadoutAdapter:
    """Tested layouts only, not structural duck-typing of unknown architectures.

    Exact model classes, package version, a single device, full head geometry,
    no active head hooks and deterministic mode are validated before execution.
    Multi-device/offload/quantized/custom/compiled variants require another
    explicit adapter. All output transforms stay in base.forward, including any
    native output upcast. Frozen and full-update ownership is external.
    """

    def __init__(self, base: nn.Module):
        from transformers import (
            Gemma2ForCausalLM,
            GPT2LMHeadModel,
            MistralForCausalLM,
            Olmo2ForCausalLM,
        )

        known = {
            GPT2LMHeadModel: ("gpt2", "transformer.ln_f"),
            MistralForCausalLM: ("mistral", "model.norm"),
            Olmo2ForCausalLM: ("olmo2", "model.norm"),
            Gemma2ForCausalLM: ("gemma2", "model.norm"),
        }
        if transformers.__version__ != "5.15.0" or type(base) not in known:
            raise TypeError("Unqualified model class or Transformers version for native adapter")
        family, norm_path = known[type(base)]
        if base.config.model_type != family:
            raise ValueError("Model class/config family mismatch")
        self.base = base
        self.family, self.norm_path = family, norm_path
        self.head = base.get_output_embeddings()
        if type(self.head) is not nn.Linear:
            raise TypeError("This adapter qualifies only native nn.Linear output embeddings")
        self.norm = base.get_submodule(norm_path)
        self._config = _config_hash(base)
        self._parameters = tuple((n, id(p)) for n, p in base.named_parameters())
        with _REGISTRY_LOCK:
            self._lock = _LOCKS.setdefault(base, threading.Lock())
        self._validate()

    @property
    def vocabulary(self) -> int:
        return self.head.out_features

    def _validate(self):
        if _config_hash(self.base) != self._config:
            raise ValueError("Model configuration changed; bind a new adapter explicitly")
        if self.base.get_output_embeddings() is not self.head:
            raise ValueError("Native head was replaced")
        if tuple((n, id(p)) for n, p in self.base.named_parameters()) != self._parameters:
            raise ValueError("Native parameter identity changed")
        if any("forward" in module.__dict__ for module in self.base.modules()):
            raise ValueError("Instance-patched/compiled forwards need a separate adapter")
        if getattr(self.base, "hf_device_map", None) or any(
            hasattr(module, "_hf_hook") for module in self.base.modules()
        ):
            raise ValueError("Dispatched/offloaded model needs a separate adapter")
        devices = {p.device for p in self.base.parameters()}
        if devices != {self.head.weight.device} or self.head.weight.device.type == "meta":
            raise ValueError("Single materialized model device required")
        if self.head.weight.dtype not in (torch.float32, torch.bfloat16):
            raise TypeError("Only FP32/BF16 native heads are currently qualified")
        if self.head._forward_pre_hooks or self.head._forward_hooks:
            raise ValueError("Native head already has hooks; exclusive ownership required")
        if self.base.training:
            dropout = (
                any(isinstance(m, nn.Dropout) and m.p > 0 for m in self.base.modules())
                or float(getattr(self.base.config, "attention_dropout", 0)) > 0
            )
            if dropout:
                raise ValueError("Training-mode parity requires zero dropout")

    def describe(self) -> dict:
        return {
            "schema": "latent_workspace.native_model_readout_adapter.v1",
            "family": self.family,
            "model_class": f"{type(self.base).__module__}.{type(self.base).__name__}",
            "model_forward_source_sha256": hashlib.sha256(
                inspect.getsource(type(self.base).forward).encode()
            ).hexdigest(),
            "config_sha256": self._config,
            "torch": str(torch.__version__),
            "transformers": transformers.__version__,
            "normalizer_class": f"{type(self.norm).__module__}.{type(self.norm).__name__}",
            "normalizer_owner": "native_model_forward",
            "post_head_owner": "native_model_forward",
            "injection_phase": "native_head_input_after_final_normalization",
            "composition": "FP32_add_then_native_cast_full_sequence_full_vocab",
            "cache": "disabled_recompute_complete_prefix",
            "concurrency": "exclusive_uncompiled_model_instance",
            "support": "explicit_layout_not_real_model_quality_qualification",
        }

    def _execution_key(self):
        return (
            id(self.base),
            self._config,
            tuple((id(p), p._version) for p in self.base.parameters()),
        )

    def read(
        self, prefix_ids: tuple[int, ...], residual: Callable[[torch.Tensor], torch.Tensor]
    ) -> TransportReadout:
        validate_token_tuple(prefix_ids, self.vocabulary)
        if not callable(residual):
            raise TypeError("Residual provider must be callable")
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("Concurrent or recursive native readout on the same model")
        handles, captured = [], {}
        try:
            self._validate()
            key = self._execution_key()
            device = self.head.weight.device
            ids = torch.tensor([prefix_ids], dtype=torch.long, device=device)

            def before(_module, inputs):
                if "injection" in captured or len(inputs) != 1:
                    raise ValueError("Expected exactly one native head invocation")
                hidden = inputs[0]
                if hidden.shape != (1, len(prefix_ids), self.head.in_features):
                    raise ValueError("Native head did not receive complete unpadded prefix")
                if hidden.dtype != self.head.weight.dtype or hidden.device != device:
                    raise ValueError("Native head input dtype/device changed")
                injection = inject_last(hidden, residual(hidden))
                captured["injection"] = injection
                return (injection.sequence,)

            def after(_module, _inputs, output):
                if "head_logits" in captured:
                    raise ValueError("Multiple native head outputs")
                captured["head_logits"] = output

            handles.append(self.head.register_forward_pre_hook(before))
            handles.append(self.head.register_forward_hook(after))
            with torch.autocast(device.type, enabled=False):
                result = self.base(
                    input_ids=ids,
                    attention_mask=torch.ones_like(ids),
                    use_cache=False,
                    logits_to_keep=0,
                    return_dict=True,
                )
            if set(captured) != {"injection", "head_logits"}:
                raise ValueError("Native model skipped the declared head boundary")
            for name, logits in (("head", captured["head_logits"]), ("published", result.logits)):
                if (
                    not isinstance(logits, torch.Tensor)
                    or logits.shape != (1, len(prefix_ids), self.vocabulary)
                    or logits.device != device
                    or not logits.is_floating_point()
                ):
                    raise ValueError(f"{name} logits lost native full geometry/device")
                _finite(logits, name)
            if getattr(result, "past_key_values", None) is not None:
                raise ValueError("Native readout unexpectedly produced a cache")
            if self._execution_key() != key or _config_hash(self.base) != self._config:
                raise ValueError("Model parameters/config mutated during readout")
            injection = captured["injection"]
            return TransportReadout(
                NativeReadoutResult(
                    result.logits, injection.applied_delta, injection.corrected_last_fp32
                ),
                injection,
                captured["head_logits"],
                prefix_ids,
                key,
                (id(self.head.weight), self.head.weight._version),
            )
        finally:
            for handle in handles:
                handle.remove()
            self._lock.release()
