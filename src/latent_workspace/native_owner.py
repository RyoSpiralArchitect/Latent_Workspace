"""One native full-update owner: ordered token-weighted windows and CPU masters.

Transport and checkpoint primitives are promoted, not imported from history.
The FP32 Adafactor settings, native-dtype ordered gradient merges, clipping and
native casts match the historical native family. Query-token weighting and the
bridge-free parameter partition are explicit new policies, tested separately.

Exclusive model/RNG ownership is required. Preflighted restore rejects an
invalid payload before writing target tensors or global RNG; device/process
failure during publication is not an atomic transaction. A failed update
poisons the owner: recovery requires a fresh model and a recorded checkpoint.
"""

from __future__ import annotations

import copy
import hashlib
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import torch
from torch import nn
from transformers.optimization import Adafactor

from .native_memory import NativeMemoryCausalLM
from .offload import CompleteCPUWindow
from .optimizer_state import (
    checkpoint_policy,
    finite_tree,
    require,
    restore_rng,
    rng_state,
    snapshot,
    tensor_schema,
    tree_hash,
    validate_optimizer,
    validate_rng,
)
from .preservation_objective import PreservationTargets, validate_objective

FORMAT = "ltws-native-owner-v1"
PRESERVATION_FORMAT = "ltws-native-owner-preservation-v2"


@dataclass(frozen=True)
class NativeOptimizerConfig:
    learning_rate: float = 2e-7
    weight_decay: float = 0.0
    max_grad_norm: float = 1.0

    def validate(self):
        for name, value in asdict(self).items():
            require(type(value) in (float, int) and math.isfinite(value), f"Finite {name}")
            require(value >= 0 if name == "weight_decay" else value > 0, f"Invalid {name}")


def native_optimizer(masters, config):
    """The exact historical native-family optimizer; no GPU optimizer state."""
    return Adafactor(
        list(masters),
        lr=config.learning_rate,
        eps=(1e-30, 1e-3),
        clip_threshold=1.0,
        decay_rate=-0.8,
        beta1=None,
        weight_decay=config.weight_decay,
        scale_parameter=False,
        relative_step=False,
        warmup_init=False,
    )


def _parameters(model):
    named = list(model.named_parameters())
    require(named and all(p.requires_grad for _, p in named), "Every native parameter trainable")
    require(all(p.dtype in (torch.float32, torch.bfloat16) for _, p in named), "FP32/BF16 host")
    require(len({p.device for _, p in named}) == 1, "One native device per owner")
    require(next(iter(p.device.type for _, p in named)) in ("cpu", "cuda"), "CPU/CUDA owner")
    # A tied parameter is one physical object, never two optimizations. Distinct
    # Parameter objects sharing storage are not a supported alias representation.
    storage = [(p.device, p.untyped_storage().data_ptr()) for _, p in named]
    require(len(set(storage)) == len(storage), "Distinct parameters share storage")
    canonical = {id(p): n for n, p in named}
    aliases = {n: canonical[id(p)] for n, p in model.named_parameters(remove_duplicate=False)}
    return named, aliases


def _schema(named):
    return {
        n: dict(shape=list(p.shape), dtype=str(p.dtype), stride=list(p.stride())) for n, p in named
    }


def _execution(graph):
    model = graph.model
    config = getattr(model, "config", None)
    return dict(
        graph=graph.contract(),
        config=config.to_dict() if config is not None else None,
        modules=[
            (n, type(m).__module__, type(m).__qualname__, m.extra_repr(), m.training)
            for n, m in graph.named_modules()
        ],
        checkpointing=checkpoint_policy(model),
        runtime=dict(torch=str(torch.__version__), cuda=torch.version.cuda),
        backends=dict(
            mkldnn=torch.backends.mkldnn.enabled,
            math_sdpa=torch.backends.cuda.math_sdp_enabled(),
            flash_sdpa=torch.backends.cuda.flash_sdp_enabled(),
            efficient_sdpa=torch.backends.cuda.mem_efficient_sdp_enabled(),
            cudnn_sdpa=torch.backends.cuda.cudnn_sdp_enabled(),
            bf16_reduced_precision=torch.backends.cuda.matmul.allow_bf16_reduced_precision_reduction,
            matmul_tf32=torch.backends.cuda.matmul.allow_tf32,
            cudnn_tf32=torch.backends.cudnn.allow_tf32,
        ),
        deterministic=torch.are_deterministic_algorithms_enabled(),
        deterministic_warn_only=torch.is_deterministic_algorithms_warn_only_enabled(),
        matmul_precision=torch.get_float32_matmul_precision(),
        threads=torch.get_num_threads(),
        device=str(next(model.parameters()).device),
    )


def _validate_contract(contract):
    require(
        isinstance(contract, dict)
        and set(contract)
        == {
            "source_commit",
            "original_base_sha256",
            "data_sha256",
            "objective",
        },
        "Explicit source/base/data/objective contract",
    )
    for key, length in (("source_commit", 40), ("original_base_sha256", 64), ("data_sha256", 64)):
        require(
            isinstance(contract[key], str) and re.fullmatch(f"[0-9a-f]{{{length}}}", contract[key]),
            f"Invalid {key}",
        )
    validate_objective(contract["objective"])


def _validate_targets(contract, targets, *, full=False):
    enabled = validate_objective(contract["objective"])
    if not enabled:
        require(targets is None, "Legacy CE must not own preservation targets")
        return False
    require(type(targets) is PreservationTargets, "Owned preservation targets required")
    targets.validate(full=full)
    manifest = targets.manifest()
    require(manifest == contract["objective"]["bank"], "Preservation bank identity mismatch")
    require(
        manifest["source_commit"] == contract["source_commit"]
        and manifest["original_base_sha256"] == contract["original_base_sha256"],
        "Teacher source/original host mismatch",
    )
    return True


class _ProjectedState(dict):
    """Hash one native cast at a time instead of materializing a second 7B model."""

    def __init__(self, model, masters, aliases):
        super().__init__(model.state_dict())
        self.masters, self.aliases = masters, aliases

    def __getitem__(self, name):
        value = super().__getitem__(name)
        if name in self.aliases:
            return self.masters[self.aliases[name]].detach().to(value.dtype)
        return value


class NativeFullUpdateOwner:
    """FP32 CPU masters for exactly one NativeMemoryCausalLM's native parameters.

    Before a window, declare ordered (row key, supervised token count) pairs.
    Each row's *summed* NLL is divided by the declared window token count before
    backward. No optimizer or native weight changes until the whole window
    completes. Only clean window boundaries can be checkpointed.
    """

    def __init__(self, graph, *, config, run_contract, preservation=None, _master_state=None):
        require(type(graph) is NativeMemoryCausalLM, "Native memory graph required")
        require(type(config) is NativeOptimizerConfig, "Explicit native optimizer config")
        config.validate()
        _validate_contract(run_contract)
        self._has_preservation = _validate_targets(run_contract, preservation, full=True)
        self.preservation = preservation
        self._preservation_id = id(preservation)
        self.preservation_tokens_seen, self.preservation_history = 0, []
        self._preservation_plan = ()
        require(
            tree_hash(graph.model.state_dict()) == run_contract["original_base_sha256"],
            "Initialize/restore into the pinned original host",
        )
        self.graph, self.model = graph, graph.model
        self.named, self.aliases = _parameters(self.model)
        require(all(p.grad is None for _, p in self.named), "Target has live gradients")
        self.config, self.run_contract = config, copy.deepcopy(run_contract)
        self.execution = copy.deepcopy(_execution(graph))
        self.schema = _schema(self.named)
        self.buffers = snapshot(dict(self.model.named_buffers(remove_duplicate=False)))
        self._buffer_hash = tree_hash(self.buffers)
        self._policy_hash = tree_hash((asdict(config), self.run_contract, self.execution))
        self.masters = {}
        if _master_state is not None:
            require(set(_master_state) == set(dict(self.named)), "Master keys")
        for name, param in self.named:
            value = (
                param.detach().to(device="cpu", dtype=torch.float32, copy=True)
                if _master_state is None
                else _master_state[name].detach().clone()
            )
            tensor_schema(value, param.shape, torch.float32)
            require(bool(torch.isfinite(value).all()), "Nonfinite master")
            self.masters[name] = nn.Parameter(value)
        self.optimizer = native_optimizer(self.masters.values(), config)
        self._optimizer_policy = self._get_optimizer_policy()
        self.completed_steps, self.tokens_seen, self.history = 0, 0, []
        self.window, self.plan, self.cursor = None, (), 0
        self.failed = False
        self._record_versions()

    def _get_optimizer_policy(self):
        return [
            {k: v for k, v in group.items() if k != "params"}
            for group in self.optimizer.param_groups
        ]

    def _record_versions(self):
        self._versions = {n: p._version for n, p in self.named}
        self._master_versions = {n: p._version for n, p in self.masters.items()}
        self._cursor_hash = tree_hash(self._cursor_state())

    def _cursor_state(self):
        value = (self.completed_steps, self.tokens_seen, self.history)
        if self._has_preservation:
            value += (self.preservation_tokens_seen, self.preservation_history)
        return value

    def _validate(self):
        require(not self.failed, "Failed owner requires fresh restore")
        require(
            tree_hash(self._cursor_state()) == self._cursor_hash,
            "Completed cursor/history changed",
        )
        require(self.execution == _execution(self.graph), "Recorded execution changed")
        require(id(self.preservation) == self._preservation_id, "Target ownership changed")
        require(
            _validate_targets(self.run_contract, self.preservation) == self._has_preservation,
            "Objective mode changed",
        )
        if self._has_preservation and self.window is not None:
            require(
                tuple(self.preservation.window(self.plan)) == self._preservation_plan,
                "Preservation window denominator changed",
            )
        require(tree_hash(self.buffers) == self._buffer_hash, "Recorded buffers changed")
        require(
            self.graph.model is self.model
            and self.graph.host.model is self.model
            and self.graph.host.cuts.base_model is self.model,
            "Host identity changed",
        )
        named, aliases = _parameters(self.model)
        require(
            [(n, id(p)) for n, p in named] == [(n, id(p)) for n, p in self.named],
            "Parameter ownership changed",
        )
        require(aliases == self.aliases and _schema(named) == self.schema, "Native schema changed")
        require(
            tree_hash((asdict(self.config), self.run_contract, _execution(self.graph)))
            == self._policy_hash,
            "Execution/config/contract changed",
        )
        require(
            tree_hash(dict(self.model.named_buffers(remove_duplicate=False))) == self._buffer_hash,
            "Host buffer changed",
        )
        require(all(p._version == self._versions[n] for n, p in named), "Out-of-band native update")
        require(list(self.masters) == [n for n, _ in named], "Master ownership changed")
        for name, param in named:
            master = self.masters[name]
            tensor_schema(master, param.shape, torch.float32)
            require(
                master.requires_grad and master._version == self._master_versions[name],
                "Master policy/content changed",
            )
        require(self._get_optimizer_policy() == self._optimizer_policy, "Optimizer policy changed")
        owned = [p for group in self.optimizer.param_groups for p in group["params"]]
        require(
            [id(p) for p in owned] == [id(p) for p in self.masters.values()],
            "Optimizer ownership changed",
        )

    def _clean_boundary(self):
        self._validate()
        require(self.window is None and not self.plan and self.cursor == 0, "Active window")
        require(
            all(p.grad is None for p in [*(p for _, p in self.named), *self.masters.values()]),
            "Stale gradients",
        )

    def begin_window(self, rows):
        self._clean_boundary()
        rows = tuple(rows)
        require(
            rows and all(isinstance(r, (tuple, list)) and len(r) == 2 for r in rows),
            "Declare ordered row keys and token counts",
        )
        require(
            all(isinstance(k, str) and k and type(n) is int and n > 0 for k, n in rows),
            "Nonempty keys and positive integer token counts",
        )
        require(len({k for k, _ in rows}) == len(rows), "Duplicate window key")
        if self._has_preservation:
            self._preservation_plan = tuple(self.preservation.window(rows))
        self.plan, self.cursor = tuple((k, n) for k, n in rows), 0
        self.window = CompleteCPUWindow(self.named, merge_device="cpu")

    def _poison(self):
        if self.window is not None:
            self.window.discard()
        for p in self.masters.values():
            p.grad = None
        self.failed = True

    def accumulate(self, key, batch):
        self._validate()
        require(self.window is not None and self.cursor < len(self.plan), "No pending window row")
        require(key == self.plan[self.cursor][0], "Row ordering/duplication mismatch")
        require(all(p.grad is None for _, p in self.named), "Unspilled native gradient")
        try:
            if self._has_preservation:
                self.preservation.require_batch(key, batch)
            result = self.graph(**batch)
            require(result.supervised_tokens == self.plan[self.cursor][1], "Token count mismatch")
            require(
                result.loss_sum is not None
                and result.loss_sum.requires_grad
                and bool(torch.isfinite(result.loss_sum)),
                "Finite live summed NLL required",
            )
            loss = result.loss_sum / sum(n for _, n in self.plan)
            preservation_receipt = {}
            if self._has_preservation:
                kl = self.preservation.kl_sum(key, result.logits)
                np = sum(n for _, n in self._preservation_plan)
                scaled_kl = None
                if kl is not None:
                    scaled_kl = self.run_contract["objective"]["coefficient"] * kl / np
                    loss = loss + scaled_kl
                preservation_receipt = dict(
                    ce_denominator=sum(n for _, n in self.plan),
                    preservation_denominator=np,
                    preservation_tokens=result.supervised_tokens if kl is not None else 0,
                    kl_sum=float(kl.detach()) if kl is not None else None,
                    scaled_kl=float(scaled_kl.detach()) if scaled_kl is not None else None,
                    scaled_ce=float((result.loss_sum / sum(n for _, n in self.plan)).detach()),
                )
            loss.backward()
            require(
                all(
                    p.grad is not None and bool(torch.isfinite(p.grad).all()) for _, p in self.named
                ),
                "Missing/nonfinite physical gradient",
            )
            transfer = self.window.spill()
            self.cursor += 1
            return dict(
                key=key,
                tokens=result.supervised_tokens,
                loss_sum=float(result.loss_sum.detach()),
                scaled_loss=float(loss.detach()),
                transfer=transfer,
                **preservation_receipt,
            )
        except Exception:
            self._poison()
            raise

    @torch.no_grad()
    def step(self):
        self._validate()
        require(self.window is not None and self.cursor == len(self.plan), "Incomplete window")
        try:
            gradients, transfer = self.window.take(len(self.plan))
            for name, master in self.masters.items():
                master.grad = gradients.pop(name).float()
            require(not gradients, "Unexpected gradients")
            norm = torch.nn.utils.clip_grad_norm_(
                list(self.masters.values()), self.config.max_grad_norm, error_if_nonfinite=True
            )
            before = {n: tree_hash(p) for n, p in self.masters.items()}
            self.optimizer.step()
            self.optimizer.zero_grad(set_to_none=True)
            require(
                finite_tree(self.masters) and finite_tree(self.optimizer.state_dict()),
                "Nonfinite optimizer result",
            )
            changes = []
            for name, native in self.named:
                master = self.masters[name]
                cast = master.detach().to(native.dtype)
                require(bool(torch.isfinite(cast).all()), "Nonfinite native cast")
                changed = int((native.detach().cpu() != cast).count_nonzero())
                native.copy_(cast, non_blocking=False)
                require(torch.equal(native.detach().cpu(), cast), "Native cast/copy mismatch")
                changes.append(
                    dict(
                        name=name,
                        master_changed=tree_hash(master) != before[name],
                        native_changed_elements=changed,
                    )
                )
            self.completed_steps += 1
            self.tokens_seen += sum(n for _, n in self.plan)
            self.history.append(list(self.plan))
            if self._has_preservation:
                self.preservation_tokens_seen += sum(n for _, n in self._preservation_plan)
                self.preservation_history.append(list(self._preservation_plan))
                self._preservation_plan = ()
            self.window, self.plan, self.cursor = None, (), 0
            self._record_versions()
            result = dict(
                completed_steps=self.completed_steps,
                tokens_seen=self.tokens_seen,
                preclip_native_l2=float(norm),
                changes=changes,
                transfer=transfer,
            )
            if self._has_preservation:
                result["preservation_tokens_seen"] = self.preservation_tokens_seen
            return result
        except Exception:
            self._poison()
            raise

    def payload(self):
        self._clean_boundary()
        if self._has_preservation:
            self.preservation.validate(full=True)
        require(
            all(
                torch.equal(p.detach().cpu(), self.masters[n].detach().to(p.dtype))
                for n, p in self.named
            ),
            "Native/master cast identity at checkpoint",
        )
        extra = (
            dict(
                preservation_tokens_seen=self.preservation_tokens_seen,
                preservation_history=self.preservation_history,
            )
            if self._has_preservation
            else {}
        )
        return snapshot(
            dict(
                format=PRESERVATION_FORMAT if self._has_preservation else FORMAT,
                run_contract=self.run_contract,
                config=asdict(self.config),
                execution=self.execution,
                aliases=self.aliases,
                schema=self.schema,
                buffers=self.buffers,
                completed_steps=self.completed_steps,
                tokens_seen=self.tokens_seen,
                history=self.history,
                masters=self.masters,
                optimizer=self.optimizer.state_dict(),
                rng=rng_state(),
                native_sha256=tree_hash(self.model.state_dict()),
                **extra,
            )
        )

    def save(self, path):
        path = Path(path)
        require(not path.exists(), "Checkpoint path already exists")
        payload = self.payload()
        with path.open("xb") as stream:
            torch.save(payload, stream)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        return dict(
            path=path.name,
            bytes=path.stat().st_size,
            sha256=digest,
            state_sha256=tree_hash(payload),
            completed_steps=self.completed_steps,
        )

    @classmethod
    def restore(
        cls,
        graph,
        payload,
        *,
        config,
        expected_run_contract,
        expected_state_sha256,
        preservation=None,
    ):
        """Validate everything on private CPU state, then publish native casts and RNG."""
        require(tree_hash(payload) == expected_state_sha256, "Checkpoint content receipt mismatch")
        keys = {
            "format",
            "run_contract",
            "config",
            "execution",
            "aliases",
            "schema",
            "buffers",
            "completed_steps",
            "tokens_seen",
            "history",
            "masters",
            "optimizer",
            "rng",
            "native_sha256",
        }
        config.validate()
        _validate_contract(expected_run_contract)
        enabled = _validate_targets(expected_run_contract, preservation, full=True)
        if enabled:
            keys |= {"preservation_tokens_seen", "preservation_history"}
        require(
            set(payload) == keys
            and payload["format"] == (PRESERVATION_FORMAT if enabled else FORMAT),
            "Checkpoint schema",
        )
        require(
            payload["run_contract"] == expected_run_contract
            and payload["config"] == asdict(config),
            "Resume provenance/config mismatch",
        )
        require(payload["execution"] == _execution(graph), "Resume execution mismatch")
        require(finite_tree(payload), "Nonfinite checkpoint")
        named, aliases = _parameters(graph.model)
        require(all(p.grad is None for _, p in named), "Restore target has live gradients")
        require(
            payload["schema"] == _schema(named) and payload["aliases"] == aliases,
            "Resume native schema/alias mismatch",
        )
        buffers = dict(graph.model.named_buffers(remove_duplicate=False))
        require(set(payload["buffers"]) == set(buffers), "Buffer keys")
        for name, value in buffers.items():
            saved = payload["buffers"][name]
            tensor_schema(saved, value.shape, value.dtype)
            require(torch.equal(saved, value.detach().cpu()), "Buffer mismatch")
        require(set(payload["masters"]) == set(dict(named)), "Master keys")
        for name, param in named:
            tensor_schema(payload["masters"][name], param.shape, torch.float32)
        steps, tokens, history = (
            payload["completed_steps"],
            payload["tokens_seen"],
            payload["history"],
        )
        require(
            type(steps) is int and steps >= 0 and type(tokens) is int and tokens >= 0,
            "Invalid completed cursor",
        )
        require(type(history) is list and len(history) == steps, "Window history length")
        for rows in history:
            require(
                type(rows) is list
                and rows
                and all(
                    isinstance(r, (tuple, list))
                    and len(r) == 2
                    and isinstance(r[0], str)
                    and r[0]
                    and type(r[1]) is int
                    and r[1] > 0
                    for r in rows
                ),
                "Window history schema",
            )
            require(len({k for k, _ in rows}) == len(rows), "Duplicate history key")
        require(tokens == sum(n for rows in history for _, n in rows), "Token cursor mismatch")
        if enabled:
            ph = payload["preservation_history"]
            pn = payload["preservation_tokens_seen"]
            expected = [preservation.window(rows) for rows in history]
            require(
                type(ph) is list and tree_hash(ph) == tree_hash(expected),
                "Preservation history/denominator mismatch",
            )
            require(
                type(pn) is int and pn == sum(n for rows in expected for _, n in rows),
                "Preservation token cursor mismatch",
            )
        require(
            tree_hash(_ProjectedState(graph.model, payload["masters"], aliases))
            == payload["native_sha256"],
            "Projected native content mismatch",
        )
        validate_rng(payload["rng"])
        # Constructor verifies the original host hash, owns independent masters,
        # and does not write to the native model or process RNG.
        owner = cls(
            graph,
            config=config,
            run_contract=expected_run_contract,
            preservation=preservation,
            _master_state=payload["masters"],
        )
        validate_optimizer(payload["optimizer"], owner.optimizer, steps, base=True)
        owner.optimizer.load_state_dict(snapshot(payload["optimizer"]))
        with torch.no_grad():
            for name, param in owner.named:
                param.copy_(owner.masters[name].detach().to(param.dtype), non_blocking=False)
        restore_rng(payload["rng"])
        owner.completed_steps, owner.tokens_seen, owner.history = (
            steps,
            tokens,
            copy.deepcopy(history),
        )
        if enabled:
            owner.preservation_tokens_seen = pn
            owner.preservation_history = copy.deepcopy(ph)
        owner._record_versions()
        return owner
