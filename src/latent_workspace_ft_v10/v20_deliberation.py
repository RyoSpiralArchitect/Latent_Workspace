"""V20 Deliberation (潜在熟考): the v4/v5 latent lattice over frozen hidden states.

The historical modules are reused unchanged: the v5 ``CausalBroadcastLatentWorkspace``,
``LatentWorkspaceLoss`` and the weight-decay policy from ``engine``, and v4's
``LowRankWorkspaceLogitAdapter`` from ``workspace_core``. As in v4, the lattice
reads the hidden state that enters the frozen LM head and adds
``sigmoid(gate) * adapter(final latent state)`` to the base logits. Only the
answer position and the two candidate columns of that vocabulary residual are
evaluated (choice-normalized objective); the adapter itself is the full v4 one.

``steps == 0`` is the readout control: the anchor projection feeds the adapter
without a latent step. Every component is initialized from its own derived seed,
so arms of one seed share every common parameter exactly, and the first step
embedding of a one-step lattice equals that of a four-step one.
"""

from __future__ import annotations

import contextlib
import hashlib
import math
from dataclasses import dataclass

import torch
from torch import nn
from torch.nn import functional as F

from .engine import CausalBroadcastLatentWorkspace, LatentWorkspaceLoss, _uses_weight_decay
from .workspace_core import LowRankWorkspaceLogitAdapter

MAX_STEPS = 4
# v9 / V10 ``workspace.loss`` values (configs/v9_reference/config_O0_slots4_k1.json).
V9_LOSS = dict(
    projection_dim=128,
    variance_target=1.0,
    eps=1e-4,
    contrastive_temperature=0.1,
    worst_step_temperature=0.1,
    temporal_drift_margin=0.2,
    probe_dropout=0.05,
    lambda_var=1.0,
    lambda_cov=1.0,
    lambda_info=0.5,
    lambda_contrast=0.25,
    lambda_relation=0.1,
    lambda_temporal=0.1,
    lambda_worst=0.25,
    lambda_rank=0.05,
)


def component_seed(seed, name):
    digest = hashlib.sha256(f"v20-deliberation:{int(seed)}:{name}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % (2**63 - 1)


@contextlib.contextmanager
def seeded(seed):
    """Initialize under a private seed without disturbing the caller's RNG."""
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        yield


class DeliberationRoute(nn.Module):
    """v4 route: lattice over final hidden states, gated low-rank vocabulary residual."""

    def __init__(
        self,
        hidden_dim,
        vocab_size,
        candidate_ids,
        *,
        steps,
        seed,
        workspace_dim=256,
        heads=8,
        ff_multiplier=2.0,
        dropout=0.05,
        rank=32,
        gate_init_bias=-2.0,
    ):
        super().__init__()
        if steps not in range(MAX_STEPS + 1):
            raise ValueError("steps must be 0..4")
        if len(candidate_ids) != 2 or len(set(candidate_ids)) != 2:
            raise ValueError("Two distinct candidate ids required")
        self.steps = int(steps)
        self.register_buffer(
            "candidate_ids", torch.tensor(list(candidate_ids), dtype=torch.long), persistent=False
        )
        with seeded(component_seed(seed, "lattice")):
            self.lattice = CausalBroadcastLatentWorkspace(
                hidden_dim,
                workspace_dim,
                max(self.steps, 1),
                ff_multiplier=ff_multiplier,
                dropout=dropout,
                anchor_refresh="initial_only",
                attention_heads=heads,
                attention_dropout=0.0,
                causal_window=0,
            )
        generator = torch.Generator().manual_seed(component_seed(seed, "step_embeddings"))
        shared = torch.randn(MAX_STEPS, workspace_dim, generator=generator) * 0.02
        with torch.no_grad():
            self.lattice.step_embeddings.copy_(shared[: max(self.steps, 1)])
        with seeded(component_seed(seed, "adapter")):
            self.adapter = LowRankWorkspaceLogitAdapter(workspace_dim, vocab_size, rank)
        with seeded(component_seed(seed, "gate")):
            self.gate_norm = nn.LayerNorm(hidden_dim)
            self.gate = nn.Linear(hidden_dim, 1)
        nn.init.zeros_(self.gate.weight)
        nn.init.constant_(self.gate.bias, gate_init_bias)

    @contextlib.contextmanager
    def truncated(self, steps):
        """Run the first ``steps`` latent steps of the same weights (inference only)."""
        if steps is None:
            yield
            return
        if self.steps == 0 or not 1 <= steps <= self.steps:
            raise ValueError("Truncation needs a lattice and 1 <= steps <= configured steps")
        old = self.lattice.steps
        self.lattice.steps = int(steps)
        try:
            yield
        finally:
            self.lattice.steps = old

    def forward(self, hidden, mask):
        """Return (candidate logit deltas at the last valid position, latents, anchor, gate)."""
        if hidden.ndim != 3 or mask.shape != hidden.shape[:2]:
            raise ValueError("Expected hidden [B, L, H] and mask [B, L]")
        last = mask.long().sum(1) - 1
        if (last < 0).any():
            raise ValueError("Empty row")
        rows = torch.arange(hidden.shape[0], device=hidden.device)
        if self.steps == 0:
            latents = None
            anchor = self.lattice.input_projection(self.lattice.input_norm(hidden))
            final = anchor[rows, last]
        else:
            latents, anchor = self.lattice(hidden, mask)
            final = latents[rows, last, -1]
        gate = torch.sigmoid(self.gate(self.gate_norm(hidden[rows, last])))
        projected = F.gelu(self.adapter.down(self.adapter.norm(final)))
        delta = projected @ self.adapter.up.weight[self.candidate_ids].T
        return gate * delta, latents, anchor, gate


def workspace_loss(seed, workspace_dim=256):
    config = dict(V9_LOSS, projection_dim=min(V9_LOSS["projection_dim"], workspace_dim))
    with seeded(component_seed(seed, "workspace_loss")):
        return LatentWorkspaceLoss(workspace_dim, **config)


def trainable(route, loss=None):
    named = list(route.named_parameters())
    if loss is not None:
        named += [(f"workspace_loss.{n}", p) for n, p in loss.named_parameters()]
    return named


def optimizer_for(named, lr, weight_decay, betas=(0.9, 0.999), eps=1e-8):
    decay = [p for n, p in named if _uses_weight_decay(n, p)]
    other = [p for n, p in named if not _uses_weight_decay(n, p)]
    return torch.optim.AdamW(
        [{"params": decay, "weight_decay": weight_decay}, {"params": other, "weight_decay": 0.0}],
        lr=lr,
        betas=betas,
        eps=eps,
    )


def fingerprint(named):
    digest = hashlib.sha256()
    for name, parameter in named:
        digest.update(name.encode())
        digest.update(parameter.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes())
    return digest.hexdigest()


class FeatureBank:
    """Frozen final hidden states (concatenated rows) with base candidate logits."""

    def __init__(self, hidden, offsets, base_logits, targets, worlds):
        if offsets.ndim != 1 or offsets[0] != 0 or offsets[-1] != hidden.shape[0]:
            raise ValueError("Offsets must span the hidden rows")
        n = offsets.numel() - 1
        if base_logits.shape != (n, 2) or targets.shape != (n,) or worlds.shape != (n,):
            raise ValueError("Row metadata shapes")
        self.hidden, self.offsets = hidden, offsets
        self.base_logits = base_logits.float()
        self.targets, self.worlds = targets.long(), worlds.long()

    def __len__(self):
        return self.offsets.numel() - 1

    def batch(self, indices):
        lengths = [int(self.offsets[i + 1] - self.offsets[i]) for i in indices]
        width = max(lengths)
        hidden = torch.zeros(len(indices), width, self.hidden.shape[1], dtype=torch.float32)
        mask = torch.zeros(len(indices), width, dtype=torch.long)
        for row, (i, length) in enumerate(zip(indices, lengths, strict=True)):
            start = int(self.offsets[i])
            hidden[row, :length] = self.hidden[start : start + length].float()
            mask[row, :length] = 1
        index = torch.tensor(list(indices), dtype=torch.long)
        return hidden, mask, self.base_logits[index], self.targets[index], self.worlds[index]


@dataclass(frozen=True)
class TrainConfig:
    seed: int
    updates: int
    batch_size: int
    learning_rate: float
    weight_decay: float
    max_grad_norm: float
    workspace_loss_weight: float
    loss_tokens_per_row: int
    loss_tokens_per_batch: int
    spectral_every: int


def epoch_order(seed, epoch, rows):
    generator = torch.Generator().manual_seed(component_seed(seed, f"epoch{epoch}"))
    return torch.randperm(rows, generator=generator).tolist()


def batch_indices(config, rows, step):
    """Rows for 1-based ``step``: fixed epoch permutations, last partial batch dropped."""
    per_epoch = rows // config.batch_size
    epoch, offset = divmod(step - 1, per_epoch)
    order = epoch_order(config.seed, epoch, rows)
    return order[offset * config.batch_size : (offset + 1) * config.batch_size]


def sample_positions(mask, per_row, cap, generator):
    rows, cols = [], []
    for row in range(mask.shape[0]):
        valid = torch.nonzero(mask[row], as_tuple=False).flatten()
        if valid.numel() > per_row:
            valid = valid[torch.randperm(valid.numel(), generator=generator)[:per_row]]
        rows.append(torch.full_like(valid, row))
        cols.append(valid)
    rows, cols = torch.cat(rows), torch.cat(cols)
    if rows.numel() > cap:
        keep = torch.randperm(rows.numel(), generator=generator)[:cap]
        rows, cols = rows[keep], cols[keep]
    return rows, cols


def update(route, loss, optimizer, bank, config, step):
    """One owned update; dropout and loss sampling depend only on (seed, step)."""
    route.train()
    if loss is not None:
        loss.train()
    torch.manual_seed(component_seed(config.seed, f"step{step}"))
    hidden, mask, base, targets, worlds = bank.batch(batch_indices(config, len(bank), step))
    delta, latents, anchor, gate = route(hidden, mask)
    task = F.cross_entropy(base + delta, targets)
    total, stats = task, None
    if config.workspace_loss_weight:
        generator = torch.Generator().manual_seed(component_seed(config.seed, f"sample{step}"))
        rows, cols = sample_positions(
            mask, config.loss_tokens_per_row, config.loss_tokens_per_batch, generator
        )
        stats = loss(
            latents[rows, cols],
            anchor[rows, cols],
            compute_spectral=(step - 1) % config.spectral_every == 0,
            contrastive_group_ids=worlds[rows],
        )
        total = task + config.workspace_loss_weight * stats["loss"]
    named = trainable(route, loss if config.workspace_loss_weight else None)
    optimizer.zero_grad(set_to_none=True)
    total.backward()
    norm = torch.nn.utils.clip_grad_norm_([p for _, p in named], config.max_grad_norm)
    optimizer.step()
    receipt = {
        "step": step,
        "task_loss": float(task.detach()),
        "total_loss": float(total.detach()),
        "grad_norm": float(norm),
        "gate_mean": float(gate.detach().mean()),
        "delta_abs_mean": float(delta.detach().abs().mean()),
    }
    if stats is not None:
        receipt["workspace_loss"] = float(stats["loss"].detach())
    return receipt


@torch.no_grad()
def evaluate(route, bank, batch_size=64, steps=None):
    """Adapted candidate logits [n, 2] in row order (fixed batching)."""
    route.eval()
    outputs = []
    with route.truncated(steps):
        for start in range(0, len(bank), batch_size):
            indices = list(range(start, min(start + batch_size, len(bank))))
            hidden, mask, base, _, _ = bank.batch(indices)
            delta, _, _, _ = route(hidden, mask)
            outputs.append(base + delta)
    return torch.cat(outputs)


# ---- pure statistics (shared by runner and offline verifier) -------------------


def correct_flags(adapted, targets):
    """Strict: the target candidate's logit must exceed the other one."""
    return [bool(row[t] > row[1 - t]) for row, t in zip(adapted, targets, strict=True)]


def binomial_upper(k, n):
    return sum(math.comb(n, i) for i in range(k, n + 1)) / 2**n if n else 1.0


def world_sign(left, right, worlds):
    """One-sided sign test that ``left`` beats ``right`` across worlds."""
    totals = {}
    for a, b, w in zip(left, right, worlds, strict=True):
        totals[w] = totals.get(w, 0) + int(a) - int(b)
    positive = sum(v > 0 for v in totals.values())
    negative = sum(v < 0 for v in totals.values())
    return {
        "positive": positive,
        "negative": negative,
        "zero": len(totals) - positive - negative,
        "p_one_sided": binomial_upper(positive, positive + negative),
    }


def gain(left, right, worlds, rule):
    rows = len(left)
    difference = (sum(left) - sum(right)) / rows
    sign = world_sign(left, right, worlds)
    passed = difference >= rule["minimum_accuracy_gain"] and sign["p_one_sided"] <= rule["alpha"]
    return {"accuracy_gain": difference, "world_sign": sign, "passed": passed}


def verdict(route_gains, step_gains, labels):
    """``route_gains``/``step_gains``: per-seed ``gain`` results for k4 vs base and k4 vs k1."""
    if all(g["passed"] for g in route_gains) and all(g["passed"] for g in step_gains):
        return labels[0]
    if all(g["passed"] for g in route_gains):
        return labels[1]
    return labels[2]
