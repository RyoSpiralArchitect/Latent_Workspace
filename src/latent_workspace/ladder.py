"""Availability ladder: at which rung does memory content get lost?

Route- and writer-agnostic: every function takes tensors. Rungs are read with
probes fitted on training worlds and tested on held-out worlds:

- **written memory**: ``AttentionProbe`` (query → memory slots → yes/no), compared
  with the same probe given zeroed memory (query only) or another world's memory;
- **read output**: a logistic contrast probe on ``v(intact) - v(twin)`` for the
  affected questions, predicting the intact answer;
- world-level sign tests, so the two affected questions of a world count once,
  and distinguishability ratios (content difference against form difference).

The probes are deliberately small; a pass shows the content is extractable from
that rung, a fail that this probe could not extract it.
"""

from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F

from .stats import binomial_upper

VERDICTS = ("CONTENT_ABSENT_IN_MEMORY", "LOST_IN_READING", "LOST_IN_TRANSPORT")


class AttentionProbe(nn.Module):
    """One-head attention over memory slots, then a yes/no logit from query and read."""

    def __init__(self, query_dim, memory_dim, width=64):
        super().__init__()
        self.width = width
        self.query_norm = nn.LayerNorm(query_dim)
        self.memory_norm = nn.LayerNorm(memory_dim)
        self.query = nn.Linear(query_dim, width)
        self.key = nn.Linear(memory_dim, width)
        self.value = nn.Linear(memory_dim, width)
        self.out = nn.Linear(2 * width, 1)

    def forward(self, query, memory, mask):
        """``query`` [N, Dq], ``memory`` [N, S, Dm], ``mask`` [N, S] → logits [N]."""
        q = self.query(self.query_norm(query))
        normalized = self.memory_norm(memory)
        keys, values = self.key(normalized), self.value(normalized)
        scores = (keys @ q.unsqueeze(-1)).squeeze(-1) / self.width**0.5
        scores = scores.masked_fill(~mask.bool(), float("-inf"))
        read = (scores.softmax(-1).unsqueeze(-1) * values).sum(1)
        return self.out(torch.cat([q, read], dim=-1)).squeeze(-1)


def fit_attention_probe(train, test, *, seed, width=64, steps=300, lr=1e-3, weight_decay=1e-4):
    """Full-batch AdamW; returns held-out yes predictions and the final training loss.

    ``train``/``test``: dicts with ``query`` [N, Dq], ``memory`` [N, S, Dm],
    ``mask`` [N, S] and (train only) ``label`` [N] in {0, 1}.
    """
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        probe = AttentionProbe(train["query"].shape[-1], train["memory"].shape[-1], width)
    optimizer = torch.optim.AdamW(probe.parameters(), lr=lr, weight_decay=weight_decay)
    labels = train["label"].float()
    for _ in range(steps):
        loss = F.binary_cross_entropy_with_logits(
            probe(train["query"], train["memory"], train["mask"]), labels
        )
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
    with torch.no_grad():
        logits = probe(test["query"], test["memory"], test["mask"])
    return (logits > 0).tolist(), float(loss.detach())


def fit_contrast_probe(train_x, train_y, test_x, *, l2=1e-3, iterations=200):
    """L2 logistic regression on standardized contrasts, both orientations; deterministic.

    Each training contrast ``x`` with intact answer ``y`` also enters as ``-x`` with
    ``1 - y`` (the twin's orientation), so the fit carries no orientation bias.
    Returns held-out yes predictions for ``test_x`` (intact orientation).
    """
    x = torch.cat([train_x, -train_x]).double()
    y = torch.cat([train_y, 1 - train_y]).double()
    scale = x.std(0).clamp_min(1e-12)
    x = x / scale
    weight = torch.zeros(x.shape[1], dtype=torch.float64, requires_grad=True)
    optimizer = torch.optim.LBFGS(
        [weight], lr=1.0, max_iter=iterations, line_search_fn="strong_wolfe"
    )

    def closure():
        optimizer.zero_grad()
        loss = F.binary_cross_entropy_with_logits(x @ weight, y) + l2 * weight.square().sum()
        loss.backward()
        return loss

    optimizer.step(closure)
    with torch.no_grad():
        return ((test_x.double() / scale) @ weight > 0).tolist()


def pair_following(correct, pairs):
    """Per pair: both rows right. ``pairs`` maps a key to its two row indices."""
    return {key: bool(correct[a] and correct[b]) for key, (a, b) in pairs.items()}


def world_counts(values, worlds):
    """Sum boolean ``values`` per world (``worlds`` gives each value's world)."""
    counts = {}
    for value, world in zip(values, worlds, strict=True):
        counts[world] = counts.get(world, 0) + int(value)
    return counts


def sign_test(left, right):
    """One-sided: worlds where ``left`` counts more than ``right``."""
    positive = sum(left[w] > right[w] for w in left)
    negative = sum(left[w] < right[w] for w in left)
    return {
        "positive": positive,
        "negative": negative,
        "zero": len(left) - positive - negative,
        "p_one_sided": binomial_upper(positive, positive + negative),
    }


def chance_sign_test(counts, per_world):
    """Against chance for ``per_world`` binary predictions per world (symmetric)."""
    half = per_world / 2
    return sign_test(counts, dict.fromkeys(counts, half))


def distinguishability(content, form):
    """Median over worlds of ``|content difference| / |form difference|``."""
    ratios = sorted(
        float(c.norm() / f.norm().clamp_min(1e-12)) for c, f in zip(content, form, strict=True)
    )
    middle = len(ratios) // 2
    return ratios[middle] if len(ratios) % 2 else (ratios[middle - 1] + ratios[middle]) / 2


def ladder_verdict(memory_pass, reading_pass):
    if not memory_pass:
        return VERDICTS[0]
    return VERDICTS[2] if reading_pass else VERDICTS[1]
