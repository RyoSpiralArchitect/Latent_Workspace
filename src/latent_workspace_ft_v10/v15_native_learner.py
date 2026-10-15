"""V15 native learner ownership, complete-window updates and exact resume.

The model still executes in its native dtype. Full updates use CPU FP32 masters
and factored Adafactor state; the FP32 workspace keeps its own matched AdamW.
No labels, donor IDs or diagnostic factors are inputs to this mechanism.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from contextlib import nullcontext
from pathlib import Path

import numpy as np
import torch
from torch import nn
from transformers.optimization import Adafactor

from .engine import _CPUGradientAccumulator
from .precision_bridge import PrecisionAwareWorkspaceBridge
from .query_modulated_bridge import QueryModulatedWorkspaceBridge
from .v15_full_update import MistralLiveFeatures, TrainableNativeWorkspaceReadout
from .v15_pipeline import NativeWorkspacePipeline
from .v15_readout import NativeWorkspaceReadout


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


def cpu_tree(value):
    if isinstance(value, torch.Tensor):
        return value.detach().cpu()
    if isinstance(value, dict):
        return {k: cpu_tree(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return tuple(cpu_tree(v) for v in value)
    if isinstance(value, list):
        return [cpu_tree(v) for v in value]
    return value


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


def reader_descriptor(bridge):
    require(
        type(bridge) in (PrecisionAwareWorkspaceBridge, QueryModulatedWorkspaceBridge),
        "Unknown reader class",
    )
    return {
        "class": type(bridge).__name__,
        "strength": getattr(bridge, "modulation_strength", 0.0),
        "hidden_dim": bridge.hidden_dim,
        "workspace_dim": bridge.workspace_dim,
        "slots": bridge.slots,
        "heads": bridge.attention.num_heads,
        "writer_steps": bridge.writer.steps,
        "cap": bridge.max_delta_norm,
    }


def create_reader(hidden_dim, architecture, name):
    require(name in ("legacy", "query_modulated"), "Unknown reader name")
    cls = PrecisionAwareWorkspaceBridge if name == "legacy" else QueryModulatedWorkspaceBridge
    return cls(hidden_dim, **architecture)


class FrozenQueryProbePipeline(NativeWorkspacePipeline):
    """Same forward; an input leaf measures reader gradients, not base gradients."""

    def query(self, normalized, *, prefix_ids, span):
        value = super().query(normalized, prefix_ids=prefix_ids, span=span)
        return value.detach().requires_grad_(torch.is_grad_enabled())


class CompleteCPUWindow(_CPUGradientAccumulator):
    """Consume completed host gradients without an unnecessary full GPU restore.

    Inherits the sealed engine's synchronized, native-dtype CPU addition. A new
    adapter owns its buffers only after complete-window validation. No old
    transport implementation or receipt is modified or re-labelled.
    """

    @torch.no_grad()
    def take(self, expected_spills):
        self._require_active()
        require(type(expected_spills) is int and expected_spills > 0, "Positive window length")
        require(self._spill_count == expected_spills, "Incomplete accumulation window")
        require(
            set(self._buffers) == set(self._specs_by_id) == self._seen_parameter_ids,
            "Missing gradient ownership",
        )
        for spec in self._specs:
            self._validate_parameter(spec)
            require(spec.parameter.grad is None, "Unspilled gradient")
            self._validate_buffer(spec, self._buffers[id(spec.parameter)])
            require(
                bool(torch.isfinite(self._buffers[id(spec.parameter)]).all()),
                "Nonfinite accumulation",
            )
        values = {spec.name: self._buffers[id(spec.parameter)] for spec in self._specs}
        receipt = self.statistics()
        receipt.update(consumed_parameter_count=len(values), consumer="CPU master plus FP32 bridge")
        self._buffers.clear()
        self._staging_buffers.clear()
        self._seen_parameter_ids.clear()
        self._buffer_strides.clear()
        self._active = False
        return values, receipt


class V15NativeLearner:
    """One explicit state owner for native features, reader, optimizers and RNG.

    Begin a declared ordered window, accumulate each scalar objective once, and
    update only after all keys. This class does not choose data, losses or success
    thresholds. The first architecture binding is Mistral, final-query only.
    """

    def __init__(
        self,
        base,
        bridge,
        *,
        full_update,
        optimizer_config,
        boundary=16,
        observer=None,
        master_state=None,
    ):
        require(type(full_update) is bool, "Explicit update scope")
        self.base, self.bridge, self.full_update = base, bridge, full_update
        self.config, self.boundary = dict(optimizer_config), boundary
        for key in ("bridge_lr", "base_lr", "max_grad_norm_per_family"):
            require(
                type(self.config[key]) in (int, float)
                and math.isfinite(self.config[key])
                and self.config[key] > 0,
                "Positive finite optimizer settings",
            )
        for key in ("bridge_weight_decay", "base_weight_decay"):
            require(
                type(self.config[key]) in (int, float)
                and math.isfinite(self.config[key])
                and self.config[key] >= 0,
                "Finite weight decay",
            )
        self.reader = reader_descriptor(bridge)
        self.base_named = list(base.named_parameters())
        self.bridge_named = list(bridge.named_parameters())
        self.schemas = {
            id(p): (tuple(p.shape), p.dtype, p.device)
            for _, p in self.base_named + self.bridge_named
        }
        require(self.base_named and self.bridge_named, "Both parameter families required")
        require(
            all(p.requires_grad == full_update for _, p in self.base_named), "Base update ownership"
        )
        require(
            all(p.requires_grad and p.dtype == torch.float32 for _, p in self.bridge_named),
            "FP32 trainable bridge required",
        )
        require(
            not ({id(p) for _, p in self.base_named} & {id(p) for _, p in self.bridge_named}),
            "Cross-owned parameter",
        )
        canonical = {id(p): name for name, p in self.base_named}
        self.aliases = {
            name: canonical[id(p)] for name, p in base.named_parameters(remove_duplicate=False)
        }
        self.buffer_names = sorted(set(base.state_dict()) - set(self.aliases))
        self.features = MistralLiveFeatures(base, boundary, observer)
        readout = (
            TrainableNativeWorkspaceReadout(base.lm_head)
            if full_update
            else NativeWorkspaceReadout(base.lm_head)
        )
        pipe = NativeWorkspacePipeline if full_update else FrozenQueryProbePipeline
        self.pipeline = pipe(bridge, readout, "final")
        self.named = [(f"base.{name}", p) for name, p in self.base_named] if full_update else []
        self.named += [(f"bridge.{name}", p) for name, p in self.bridge_named]
        require(
            len({id(p) for _, p in self.named}) == len(self.named), "Duplicate physical parameter"
        )
        self.masters = {}
        if full_update:
            if master_state is not None:
                require(
                    set(master_state) == {n for n, _ in self.base_named}, "Master parameter keys"
                )
            for name, p in self.base_named:
                value = (
                    p.detach().to(device="cpu", dtype=torch.float32, copy=True)
                    if master_state is None
                    else master_state[name]
                )
                require(
                    value.device.type == "cpu"
                    and value.dtype == torch.float32
                    and value.shape == p.shape
                    and bool(torch.isfinite(value).all()),
                    "FP32 master schema",
                )
                self.masters[name] = nn.Parameter(value.detach(), requires_grad=True)
        else:
            require(master_state is None, "Frozen owner cannot import base masters")
        self.bridge_optimizer = torch.optim.AdamW(
            [p for _, p in self.bridge_named],
            lr=self.config["bridge_lr"],
            weight_decay=self.config["bridge_weight_decay"],
        )
        self.base_optimizer = (
            Adafactor(
                list(self.masters.values()),
                lr=self.config["base_lr"],
                eps=(1e-30, 1e-3),
                clip_threshold=1.0,
                decay_rate=-0.8,
                beta1=None,
                weight_decay=self.config["base_weight_decay"],
                scale_parameter=False,
                relative_step=False,
                warmup_init=False,
            )
            if full_update
            else None
        )
        self.completed_steps = 0
        self.window, self.keys, self.cursor = None, (), 0
        self._validate_ownership()

    def _validate_ownership(self):
        require(
            [(n, id(p)) for n, p in self.base.named_parameters()]
            == [(n, id(p)) for n, p in self.base_named],
            "Base parameter replacement",
        )
        require(
            [(n, id(p)) for n, p in self.bridge.named_parameters()]
            == [(n, id(p)) for n, p in self.bridge_named],
            "Bridge parameter replacement",
        )
        require(
            all(p.requires_grad == self.full_update for _, p in self.base_named),
            "Base trainability changed",
        )
        require(all(p.requires_grad for _, p in self.bridge_named), "Bridge trainability changed")
        require(
            all(
                self.schemas[id(p)] == (tuple(p.shape), p.dtype, p.device)
                for _, p in self.base_named + self.bridge_named
            ),
            "Native or bridge schema changed",
        )
        require(
            list(self.masters) == ([n for n, _ in self.base_named] if self.full_update else []),
            "Master names/order changed",
        )
        require(
            all(
                p.device.type == "cpu"
                and p.dtype == torch.float32
                and p.requires_grad
                and p.shape == dict(self.base_named)[n].shape
                for n, p in self.masters.items()
            ),
            "Master schema changed",
        )
        for optimizer, expected in (
            (self.bridge_optimizer, [p for _, p in self.bridge_named]),
            (self.base_optimizer, list(self.masters.values())),
        ):
            if optimizer is None:
                require(not expected, "Missing optimizer")
                continue
            actual = [p for group in optimizer.param_groups for p in group["params"]]
            require(
                [id(p) for p in actual] == [id(p) for p in expected],
                "Optimizer must own exact family once in order",
            )

    def prefix(self, ids):
        with nullcontext() if self.full_update else torch.no_grad():
            return self.features.prefix(tuple(ids))

    def context(self, ids):
        with nullcontext() if self.full_update else torch.no_grad():
            return self.features.context(tuple(ids))

    def begin_window(self, keys):
        require(self.window is None, "Window already active")
        self._validate_ownership()
        keys = tuple(keys)
        require(keys and len(set(keys)) == len(keys), "Unique nonempty window keys")
        require(
            all(p.grad is None for _, p in self.named)
            and all(p.grad is None for p in self.masters.values()),
            "Stale gradients",
        )
        self.keys, self.cursor = keys, 0
        self.window = CompleteCPUWindow(self.named, merge_device="cpu")

    def backward_pair(self, key, loss):
        require(self.window is not None and self.cursor < len(self.keys), "No pending window slot")
        require(key == self.keys[self.cursor], "Pair ordering/duplication mismatch")
        require(
            loss.ndim == 0 and loss.requires_grad and bool(torch.isfinite(loss)),
            "Finite scalar live objective",
        )
        loss.backward()
        require(
            all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for _, p in self.named),
            "Missing/nonfinite physical gradient",
        )
        receipt = self.window.spill()
        self.cursor += 1
        return receipt

    @torch.no_grad()
    def step(self):
        require(
            self.window is not None and self.cursor == len(self.keys),
            "Complete window required before any step",
        )
        self._validate_ownership()
        gradients, transfer = self.window.take(len(self.keys))
        for name, p in self.bridge_named:
            p.grad = gradients.pop(f"bridge.{name}").to(p.device)
        for name, master in self.masters.items():
            master.grad = gradients.pop(f"base.{name}").float()
        require(not gradients, "Unexpected optimizer gradient")
        max_norm = self.config["max_grad_norm_per_family"]
        bridge_norm = torch.nn.utils.clip_grad_norm_(
            [p for _, p in self.bridge_named], max_norm, error_if_nonfinite=True
        )
        base_norm = (
            torch.nn.utils.clip_grad_norm_(
                list(self.masters.values()), max_norm, error_if_nonfinite=True
            )
            if self.full_update
            else None
        )
        master_before = {name: tree_hash(value) for name, value in self.masters.items()}
        bridge_before = {name: tree_hash(value) for name, value in self.bridge_named}
        if self.base_optimizer is not None:
            self.base_optimizer.step()
            self.base_optimizer.zero_grad(set_to_none=True)
        self.bridge_optimizer.step()
        self.bridge_optimizer.zero_grad(set_to_none=True)
        require(
            all(bool(torch.isfinite(p).all()) for _, p in self.bridge_named),
            "Nonfinite bridge update",
        )
        changes = []
        for name, native in self.base_named if self.full_update else []:
            master = self.masters[name]
            require(bool(torch.isfinite(master).all()), "Nonfinite master update")
            cast = master.detach().to(dtype=native.dtype)
            before = native.detach().cpu()
            changed = int((before != cast).count_nonzero())
            after_hash = tree_hash(master)
            native.copy_(cast, non_blocking=False)
            require(torch.equal(native.detach().cpu(), cast), "Native cast/copy mismatch")
            changes.append(
                {
                    "name": name,
                    "elements": native.numel(),
                    "native_changed_elements": changed,
                    "master_changed": master_before[name] != after_hash,
                    "master_sha256_before": master_before[name],
                    "master_sha256_after": after_hash,
                }
            )
        bridge_changes = [
            {"name": name, "changed": bridge_before[name] != tree_hash(p)}
            for name, p in self.bridge_named
        ]
        self.completed_steps += 1
        self.window, self.keys, self.cursor = None, (), 0
        return {
            "completed_step": self.completed_steps,
            "transfer": transfer,
            "preclip_bridge_l2": float(bridge_norm),
            "preclip_base_l2": float(base_norm) if base_norm is not None else None,
            "base_changes": changes,
            "bridge_changes": bridge_changes,
            "master_elements": sum(p.numel() for p in self.masters.values()),
            "native_base_tensors_eligible": len(changes),
        }

    def payload(self, metadata):
        require(self.window is None, "Checkpoint only at a complete-window boundary")
        self._validate_ownership()
        require(
            all(p.grad is None for _, p in self.named)
            and all(p.grad is None for p in self.masters.values()),
            "Checkpoint with live gradients",
        )
        if self.full_update:
            require(
                all(
                    torch.equal(p.detach().cpu(), self.masters[n].detach().to(p.dtype))
                    for n, p in self.base_named
                ),
                "Native/master cast identity at checkpoint",
            )
        state = self.base.state_dict()
        return {
            "format": "v15-native-resume-v1",
            "metadata": metadata,
            "full_update": self.full_update,
            "reader": self.reader,
            "optimizer_config": self.config,
            "boundary": self.boundary,
            "completed_steps": self.completed_steps,
            "base_aliases": self.aliases,
            "native_schema": {n: [list(p.shape), str(p.dtype)] for n, p in self.base_named},
            "native_buffers": {n: state[n].detach().cpu() for n in self.buffer_names},
            "base_masters": {n: p.detach() for n, p in self.masters.items()},
            "bridge": cpu_tree(self.bridge.state_dict()),
            "base_optimizer": cpu_tree(self.base_optimizer.state_dict())
            if self.base_optimizer is not None
            else None,
            "bridge_optimizer": cpu_tree(self.bridge_optimizer.state_dict()),
            "rng": rng_state(),
        }

    def save(self, path: Path, metadata):
        payload = self.payload(metadata)
        with path.open("xb") as stream:
            torch.save(payload, stream)
        return {
            "path": path.name,
            "bytes": path.stat().st_size,
            "state_sha256": tree_hash(payload),
            "completed_steps": self.completed_steps,
            "format": payload["format"],
        }

    @classmethod
    def restore(cls, base, bridge, payload, *, expected_metadata, observer=None):
        require(
            payload["format"] == "v15-native-resume-v1"
            and payload["metadata"] == expected_metadata,
            "Resume provenance mismatch",
        )
        require(
            payload["reader"] == reader_descriptor(bridge),
            "Reader semantics differ despite tensor compatibility",
        )
        require(
            payload["native_schema"]
            == {n: [list(p.shape), str(p.dtype)] for n, p in base.named_parameters()},
            "Native parameter schema changed",
        )
        require(finite_tree(payload), "Nonfinite checkpoint")
        bridge.load_state_dict(payload["bridge"], strict=True)
        learner = cls(
            base,
            bridge,
            full_update=payload["full_update"],
            optimizer_config=payload["optimizer_config"],
            boundary=payload["boundary"],
            observer=observer,
            master_state=payload["base_masters"] if payload["full_update"] else None,
        )
        require(
            payload["base_aliases"] == learner.aliases
            and set(payload["native_buffers"]) == set(learner.buffer_names),
            "Native alias/buffer ownership changed",
        )
        with torch.no_grad():
            for name, p in learner.base_named if learner.full_update else []:
                p.copy_(learner.masters[name].detach().to(dtype=p.dtype), non_blocking=False)
            for name in learner.buffer_names:
                base.state_dict()[name].copy_(payload["native_buffers"][name])
        learner.bridge_optimizer.load_state_dict(payload["bridge_optimizer"])
        if learner.base_optimizer is not None:
            learner.base_optimizer.load_state_dict(payload["base_optimizer"])
        else:
            require(
                payload["base_optimizer"] is None and not payload["base_masters"],
                "Frozen checkpoint has base optimizer",
            )
        learner.completed_steps = payload["completed_steps"]
        require(
            type(learner.completed_steps) is int and learner.completed_steps >= 0,
            "Invalid completed step",
        )
        learner._validate_ownership()
        require(
            learner.bridge_optimizer.param_groups[0]["lr"] == learner.config["bridge_lr"]
            and learner.bridge_optimizer.param_groups[0]["weight_decay"]
            == learner.config["bridge_weight_decay"],
            "Bridge optimizer policy mismatch",
        )
        if learner.base_optimizer is not None:
            group = learner.base_optimizer.param_groups[0]
            require(
                group["lr"] == learner.config["base_lr"]
                and group["weight_decay"] == learner.config["base_weight_decay"]
                and group["beta1"] is None
                and not group["relative_step"]
                and not group["scale_parameter"]
                and not group["warmup_init"],
                "Base optimizer policy mismatch",
            )
        restore_rng(payload["rng"])
        return learner
