"""Owned, idempotent preparation for qualified native HF training adapters.

No model-family switch, weights/loss/optimizer change or arbitrary-hook bypass.
The historical engine helper remains unchanged. Existing unowned registrations
are rejected, not silently removed. Call on exclusively owned native models.
"""

import functools
import hashlib
import inspect

import transformers
from torch.utils.checkpoint import checkpoint
from transformers import PreTrainedModel

from .hf_training_readout import HFTrainingReadoutAdapter, native_input_grad_hook
from .training_binding import checkpoint_policy

METHOD_HASHES = {
    "gradient_checkpointing_enable": (
        "b9bcfa11735c8f26016b80f1ddf2227b9cc478056330358e57e7eaf2f603cb33"
    ),
    "enable_input_require_grads": (
        "40cef9819fccca325944cf432038e0afd302b63e87ea02369cbc19816cfa303f"
    ),
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def _methods(base):
    require(transformers.__version__ == "5.15.0", "Unqualified preparation runtime")
    hashes = {}
    for name, expected in METHOD_HASHES.items():
        native = getattr(PreTrainedModel, name)
        require(
            getattr(getattr(base, name), "__func__", None) is native,
            "Overridden native preparation method",
        )
        hashes[name] = hashlib.sha256(inspect.getsource(native).encode()).hexdigest()
        require(hashes[name] == expected, "Native preparation source changed")
    require(base.main_input_name == "input_ids", "Only qualified text input preparation")
    return hashes


def _hooks(base):
    tracked = getattr(base, "_require_grads_hooks", [])
    require(isinstance(tracked, list), "Malformed native input-gradient handles")
    rows = []
    for name, module in base.named_modules():
        require(
            not module._forward_hooks_with_kwargs and not module._forward_hooks_always_called,
            "Nonstandard native hook invocation",
        )
        for key, hook in module._forward_hooks.items():
            require(
                native_input_grad_hook(base, module, key, hook),
                "Unowned native input-gradient registration",
            )
            rows.append((name, key))
    require(
        len(rows) <= 1 and len(tracked) == len(rows),
        "Duplicate/stale native input-gradient handles",
    )
    if rows:
        require(
            tracked[0].id == rows[0][1]
            and getattr(base, "_require_grads_hook", None) is tracked[0],
            "Native input-gradient handle aliases differ",
        )
    else:
        require(
            getattr(base, "_require_grads_hook", None) is None,
            "Stale native input-gradient handle alias",
        )
    return rows


def _checkpointed_modules(base):
    modules = [(n, m) for n, m in base.named_modules() if hasattr(m, "gradient_checkpointing")]
    require(bool(modules), "No qualified checkpointable modules")
    require(all(type(m.gradient_checkpointing) is bool for _, m in modules), "Checkpoint flag type")
    enabled = {m.gradient_checkpointing for _, m in modules}
    require(len(enabled) == 1, "Mixed native checkpointing state")
    for _, module in modules:
        fn = getattr(module, "_gradient_checkpointing_func", None)
        if True in enabled:
            require(
                isinstance(fn, functools.partial)
                and fn.func is checkpoint
                and not fn.args
                and fn.keywords == {"use_reentrant": False},
                "Native checkpoint arithmetic differs",
            )
        else:
            require(fn is None, "Stale native checkpoint implementation")
    return True in enabled


def prepare_native_gradient_checkpointing(base):
    """Admit a fresh model or an already identical setup; register at most once.

    Validation rejection does not repair/remove existing state. This is not a
    transaction against device failures or concurrent/out-of-band model mutation.
    The prepared execution and this receipt must be bound into resume ownership.
    """
    hashes = _methods(base)
    # Keep the existing strict adapter's global/module hook, dropout, native
    # class and parameter guards. Construction performs no model forwards.
    HFTrainingReadoutAdapter(base)
    hooks = _hooks(base)
    enabled = _checkpointed_modules(base)
    require(enabled == bool(hooks), "Checkpoint policy/input-gradient ownership disagree")
    if not enabled:
        # In this pinned implementation this call owns the single input hook.
        # DO NOT additionally call enable_input_require_grads as engine.py does.
        base.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    require(_checkpointed_modules(base), "Native checkpoint preparation did not enable")
    hooks = _hooks(base)
    require(len(hooks) == 1, "Native checkpoint preparation did not own one input hook")
    HFTrainingReadoutAdapter(base)
    return {
        "schema": "native-hf-owned-checkpoint-preparation-v1",
        "transformers": transformers.__version__,
        "native_method_source_sha256": hashes,
        "checkpoint_policy": checkpoint_policy(base),
        "input_gradient_hook": {
            "module": hooks[0][0],
            "registered": 1,
            "tracked": 1,
            "owner": "installed_PreTrainedModel.enable_input_require_grads",
        },
        "legacy_difference": "one_tracked_input_grad_hook_instead_of_duplicate_with_stale_handle",
        "weights_losses_optimizers": "unchanged",
    }
