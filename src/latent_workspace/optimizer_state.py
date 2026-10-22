"""Promoted checkpoint primitives; no historical owner or model binding is imported.

Exact origins and hashes are recorded in configs/architecture/PROMOTIONS.json.
"""

from __future__ import annotations

import copy
import functools
import hashlib
import json
import math
import random

import numpy as np
import torch


def require(condition, message):
    if not condition:
        raise ValueError(message)


def tree_hash(value):
    """Hash tensor contents plus dtype/shape, containers and scalar metadata."""
    digest = hashlib.sha256()

    def visit(item):
        if isinstance(item, torch.Tensor):
            tensor = item.detach().cpu().contiguous()
            digest.update(json.dumps(["tensor", str(tensor.dtype), list(tensor.shape)]).encode())
            digest.update(tensor.reshape(-1).view(torch.uint8).numpy().tobytes())
        elif isinstance(item, dict):
            digest.update(b"dict{")
            for key in sorted(item, key=lambda k: (type(k).__name__, str(k))):
                visit(key)
                visit(item[key])
            digest.update(b"}")
        elif isinstance(item, (tuple, list)):
            digest.update(type(item).__name__.encode() + b"[")
            for part in item:
                visit(part)
            digest.update(b"]")
        else:
            digest.update(json.dumps([type(item).__name__, item], allow_nan=False).encode())

    visit(value)
    return digest.hexdigest()


def finite_tree(value):
    if isinstance(value, torch.Tensor):
        return bool(torch.isfinite(value).all())
    if isinstance(value, dict):
        return all(finite_tree(v) for v in value.values())
    if isinstance(value, (tuple, list)):
        return all(finite_tree(v) for v in value)
    return not isinstance(value, float) or math.isfinite(value)


def rng_state():
    numpy = np.random.get_state()
    return {
        "python": random.getstate(),
        "numpy": [numpy[0], numpy[1].tolist(), numpy[2], numpy[3], numpy[4]],
        "torch_cpu": torch.get_rng_state(),
        "torch_cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_initialized() else [],
    }


def restore_rng(state):
    random.setstate(state["python"])
    numpy = state["numpy"]
    np.random.set_state((numpy[0], np.array(numpy[1], dtype=np.uint32), *numpy[2:]))
    torch.set_rng_state(state["torch_cpu"])
    if state["torch_cuda"]:
        require(torch.cuda.is_initialized(), "CUDA RNG needs initialized matching devices")
        require(len(state["torch_cuda"]) == torch.cuda.device_count(), "CUDA RNG device count")
        torch.cuda.set_rng_state_all(state["torch_cuda"])


def snapshot(value):
    """Independent, detached CPU tensors AND independent metadata containers."""
    if isinstance(value, torch.Tensor):
        return value.detach().to(device="cpu", copy=True)
    if isinstance(value, dict):
        return {copy.deepcopy(k): snapshot(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return tuple(snapshot(v) for v in value)
    if isinstance(value, list):
        return [snapshot(v) for v in value]
    return copy.deepcopy(value)


def tensor_schema(value, shape, dtype):
    require(
        isinstance(value, torch.Tensor)
        and value.device.type == "cpu"
        and value.layout == torch.strided
        and value.shape == shape
        and value.dtype == dtype,
        "Checkpoint tensor schema mismatch",
    )


def validate_rng(state):
    """Validate on private generators; never set the process generators here."""
    require(set(state) == {"python", "numpy", "torch_cpu", "torch_cuda"}, "RNG keys")
    random.Random(0).setstate(state["python"])
    numpy = state["numpy"]
    require(isinstance(numpy, list) and len(numpy) == 5, "NumPy RNG schema")
    require(
        numpy[0] == "MT19937"
        and isinstance(numpy[1], list)
        and len(numpy[1]) == 624
        and all(type(n) is int and 0 <= n < 2**32 for n in numpy[1])
        and type(numpy[2]) is int
        and 0 <= numpy[2] <= 624
        and type(numpy[3]) is int
        and numpy[3] in (0, 1),
        "NumPy RNG contents",
    )
    np.random.RandomState(0).set_state((numpy[0], np.array(numpy[1], dtype=np.uint32), *numpy[2:]))
    cpu = state["torch_cpu"]
    tensor_schema(cpu, torch.get_rng_state().shape, torch.uint8)
    torch.Generator(device="cpu").set_state(cpu)
    states = state["torch_cuda"]
    count = torch.cuda.device_count() if torch.cuda.is_initialized() else 0
    require(isinstance(states, list) and len(states) == count, "CUDA RNG device count")
    for device, saved in enumerate(states):
        tensor_schema(saved, torch.cuda.get_rng_state(device).shape, torch.uint8)
        torch.Generator(device=f"cuda:{device}").set_state(saved)


def validate_optimizer(saved, optimizer, steps, *, base):
    """Bind policy, ordered parameter IDs and every moment before loading."""
    if optimizer is None:
        require(saved is None, "Frozen checkpoint has base optimizer")
        return
    require(set(saved) == {"state", "param_groups"}, "Optimizer keys")
    expected = optimizer.state_dict()
    require(saved["param_groups"] == expected["param_groups"], "Optimizer policy/IDs mismatch")
    params = [p for group in optimizer.param_groups for p in group["params"]]
    ids = [n for group in expected["param_groups"] for n in group["params"]]
    require(set(saved["state"]) == (set(ids) if steps else set()), "Optimizer state coverage")
    for index, parameter in zip(ids, params, strict=True):
        if not steps:
            continue
        state = saved["state"][index]
        if base:
            require(type(state["step"]) is int and state["step"] == steps, "Base step mismatch")
            shapes = {"RMS": torch.Size([])}
            if parameter.ndim >= 2:
                shapes.update(
                    exp_avg_sq_row=parameter.shape[:-1],
                    exp_avg_sq_col=parameter.shape[:-2] + parameter.shape[-1:],
                )
            else:
                shapes["exp_avg_sq"] = parameter.shape
        else:
            tensor_schema(state["step"], torch.Size([]), torch.float32)
            require(state["step"].item() == steps, "Bridge step mismatch")
            shapes = {"exp_avg": parameter.shape, "exp_avg_sq": parameter.shape}
        require(set(state) == {"step", *shapes}, "Optimizer moment keys")
        for name, shape in shapes.items():
            tensor_schema(state[name], shape, torch.float32)
            if name != "exp_avg":
                require(bool((state[name] >= 0).all()), "Negative second moment/RMS")


def checkpoint_policy(base):
    rows = []
    for name, module in base.named_modules():
        if hasattr(module, "gradient_checkpointing"):
            fn = getattr(module, "_gradient_checkpointing_func", None)
            if fn is not None and (
                not isinstance(fn, functools.partial)
                or fn.args
                or any(
                    type(v) not in (bool, int, float, str, type(None)) for v in fn.keywords.values()
                )
            ):
                raise ValueError("Unknown gradient checkpointing implementation")
            rows.append(
                {
                    "module": name,
                    "enabled": module.gradient_checkpointing,
                    "function": f"{fn.func.__module__}.{fn.func.__qualname__}" if fn else None,
                    "keywords": dict(fn.keywords) if fn else None,
                }
            )
    return rows
