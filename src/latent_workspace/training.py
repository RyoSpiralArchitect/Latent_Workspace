"""Training a workspace on frozen host features: seeds, banks, updates, evaluation.

Promoted verbatim from ``v20_deliberation.py`` (and ``_uses_weight_decay`` from
``engine.py``) in ``latent_workspace_ft_v10`` at ``d4cd1ee0340a``, where V19.5
D1 trained the v4 lattice on frozen Mistral-7B features. The historical files
are frozen; this module is the living home (docs/ARCHITECTURE.md). Parity:
``test_frozen_feature_training_is_the_d1_trainer``.

Every component is initialized from its own derived seed, and data order,
dropout and loss sampling derive only from (seed, update), so a run is exact
and a fresh process replays any update bitwise.
"""

from __future__ import annotations

import contextlib
import hashlib
from dataclasses import dataclass

import torch
from torch import nn
from torch.nn import functional as F

from .losses import LatentWorkspaceLoss

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


def _uses_weight_decay(name: str, parameter: nn.Parameter) -> bool:
    lowered = name.lower()
    if parameter.ndim < 2:
        return False
    return not (
        lowered.endswith(".bias")
        or "norm" in lowered
        or "layernorm" in lowered
        or "embedding" in lowered
    )


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
