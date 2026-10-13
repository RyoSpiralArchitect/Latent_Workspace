"""Opt-in native readout with explicitly scoped, shared prefix autograd graphs.

The historical adapter is unchanged. This backend still runs the native outer
forward and its post-head transforms. A prepared prefix shares only its exact
normalized head input within one objective; it is never a cross-update hidden
cache, KV cache, selected-row head or detached surrogate backward.
"""

from __future__ import annotations

import threading
import types
from contextlib import contextmanager

import torch
from torch import nn
from torch.nn.modules import module as module_runtime
from transformers import PreTrainedModel

from .hf_readout_adapter import HFNativeReadoutAdapter, _config_hash
from .readout_transport import TransportReadout, inject_last
from .v15_full_update import validate_token_tuple
from .v15_readout import NativeReadoutResult, _finite


def execution_structure(base):
    """Process-local guards, not content hashes or persistent resume metadata."""
    modules = []
    for name, module in base.named_modules():
        scalars = tuple(
            sorted(
                (k, v)
                for k, v in vars(module).items()
                if not k.startswith("_") and type(v) in (bool, int, float, str, type(None))
            )
        )
        hooks = tuple((key, id(fn)) for key, fn in module._forward_hooks.items())
        modules.append((name, id(module), type(module), id(type(module).forward), scalars, hooks))
    return (
        tuple(modules),
        tuple(
            (n, id(p), p.shape, p.dtype, p.device, p.requires_grad)
            for n, p in base.named_parameters(remove_duplicate=False)
        ),
        tuple(
            (n, id(b), b.shape, b.dtype, b.device, b._version)
            for n, b in base.named_buffers(remove_duplicate=False)
        ),
        getattr(base.config, "_attn_implementation", None),
    )


def native_input_grad_hook(base, module, key, hook):
    """Only the installed HF embedding hook; no arbitrary native-hook bypass."""
    method = PreTrainedModel.enable_input_require_grads
    codes = [
        c
        for c in method.__code__.co_consts
        if isinstance(c, types.CodeType) and c.co_name == "make_inputs_require_grads"
    ]
    return (
        module is base.get_input_embeddings()
        and key in {h.id for h in getattr(base, "_require_grads_hooks", [])}
        and isinstance(hook, types.FunctionType)
        and hook.__code__ in codes
        and hook.__globals__ is method.__globals__
        and hook.__closure__ is None
        and hook.__defaults__ is None
    )


class HFTrainingReadoutAdapter(HFNativeReadoutAdapter):
    """Same admitted native layouts, with an exclusive objective graph lifetime."""

    def __init__(self, base):
        self._structure = None
        self._scope_thread, self._reading = None, False
        self._prepared, self._preparing = {}, False
        super().__init__(base)
        self._structure = execution_structure(base)

    @property
    def objective_active(self):
        return self._scope_thread is not None or self._reading

    def _validate(self):
        super()._validate()
        if any(
            getattr(module_runtime, name)
            for name in (
                "_global_forward_hooks",
                "_global_forward_pre_hooks",
                "_global_backward_hooks",
                "_global_backward_pre_hooks",
            )
        ):
            raise ValueError("Global native hooks need a separately qualified adapter")
        for module in self.base.modules():
            if (
                any(
                    not native_input_grad_hook(self.base, module, key, hook)
                    for key, hook in module._forward_hooks.items()
                )
                or module._forward_pre_hooks
                or module._backward_hooks
                or module._backward_pre_hooks
            ):
                raise ValueError("Training adapter rejects unqualified native hooks")
            if module.training and (
                (isinstance(module, nn.Dropout) and module.p > 0)
                or float(getattr(module, "attention_dropout", 0)) > 0
            ):
                raise ValueError("Every training submodule must have deterministic zero dropout")
        if self._structure is not None and execution_structure(self.base) != self._structure:
            raise ValueError("Native execution structure/mode/buffer changed; bind explicitly")

    def describe(self):
        return {
            **super().describe(),
            "schema": "latent_workspace.training_readout_adapter.v1",
            "graph_policy": "explicit_objective_scoped_prepared_prefixes",
            "prepared_input": "exact_native_normalized_full_prefix_with_live_autograd",
            "prepared_lifetime": "one_pair_no_cross_objective_or_update_cache",
            "outer_forward": "recomputed_and_checked_before_reusing_prepared_head_input",
        }

    def _execution_key(self):
        return (*super()._execution_key(), execution_structure(self.base))

    @contextmanager
    def objective(self):
        """Own the model until all forwards of one objective are constructed."""
        if self._scope_thread is not None or not self._lock.acquire(blocking=False):
            raise RuntimeError("Concurrent or nested objective on the same model")
        self._scope_thread = threading.get_ident()
        try:
            self._validate()
            yield self
        finally:
            self._prepared.clear()
            self._scope_thread = None
            self._lock.release()

    def prepare(self, prefix_ids):
        """Prepare in the historical graph-construction order, replacing any prior key.

        Repeated teacher-forced completions are intentionally prepared afresh;
        equal token IDs do not authorize merging their distinct backward graphs.
        """
        if self._scope_thread != threading.get_ident() or self._reading:
            raise RuntimeError("Prepare requires its exclusive objective outside a read")
        validate_token_tuple(prefix_ids, self.vocabulary)
        self._prepared.pop(prefix_ids, None)
        capture = {}

        def zero(hidden):
            capture["hidden"] = hidden
            return torch.zeros_like(hidden[:, -1:]).float()

        self._preparing = True
        try:
            output = self.read(prefix_ids, zero)
            self._prepared[prefix_ids] = (
                capture["hidden"],
                output.execution_key,
                torch.is_grad_enabled(),
            )
        finally:
            self._preparing = False

    def read(self, prefix_ids, residual):
        validate_token_tuple(prefix_ids, self.vocabulary)
        if not callable(residual):
            raise TypeError("Residual provider must be callable")
        scoped = self._scope_thread is not None
        if self._reading or (scoped and self._scope_thread != threading.get_ident()):
            raise RuntimeError("Concurrent or recursive training readout")
        acquired = not scoped
        if acquired and not self._lock.acquire(blocking=False):
            raise RuntimeError("Concurrent native readout on the same model")
        self._reading = True
        handles, captured = [], {}
        try:
            self._validate()
            key, device = self._execution_key(), self.head.weight.device
            if scoped and not self._preparing and prefix_ids not in self._prepared:
                raise ValueError("Objective read must explicitly prepare its prefix graph")
            ids = torch.tensor([prefix_ids], dtype=torch.long, device=device)

            def before(_module, inputs):
                if "injection" in captured or len(inputs) != 1:
                    raise ValueError("Expected exactly one native head invocation")
                hidden = inputs[0]
                if (
                    hidden.shape != (1, len(prefix_ids), self.head.in_features)
                    or hidden.dtype != self.head.weight.dtype
                    or hidden.device != device
                ):
                    raise ValueError("Native head input lost full geometry/dtype/device")
                if scoped and not self._preparing:
                    shared, old_key, was_grad_enabled = self._prepared[prefix_ids]
                    if old_key != key or (torch.is_grad_enabled() and not was_grad_enabled):
                        raise ValueError("Prepared graph model version or gradient mode changed")
                    if not torch.equal(hidden, shared):
                        raise ValueError("Recomputed native prefix differs from prepared input")
                    hidden = shared
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
            for label, logits in (("head", captured["head_logits"]), ("published", result.logits)):
                if (
                    not isinstance(logits, torch.Tensor)
                    or logits.shape != (1, len(prefix_ids), self.vocabulary)
                    or logits.device != device
                    or not logits.is_floating_point()
                ):
                    raise ValueError(f"{label} logits lost native full geometry/device")
                _finite(logits, label)
            if getattr(result, "past_key_values", None) is not None:
                raise ValueError("Native readout unexpectedly produced a cache")
            # Our temporary head hooks are not a caller-side execution change.
            # Remove them before comparing the original hook/structure identity.
            for handle in handles:
                handle.remove()
            handles.clear()
            if self._execution_key() != key or _config_hash(self.base) != self._config:
                raise ValueError("Model execution state mutated during readout")
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
            self._reading = False
            if acquired:
                self._lock.release()
