"""A small decoder trained from scratch, joined through the custom split interface.

It implements ``functional_forward_to_boundary``, ``functional_forward_from_boundary``,
``functional_states_from_boundary`` and ``functional_num_layers``, so the historical
cut protocol and every route treat it exactly like an HF host. Pre-norm blocks with
causal SDPA and a learned position table; deliberately plain, not a claim about any
architecture choice.
"""

from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F


class _Block(nn.Module):
    def __init__(self, width, heads):
        super().__init__()
        self.heads = heads
        self.attention_norm = nn.LayerNorm(width)
        self.qkv = nn.Linear(width, 3 * width)
        self.out = nn.Linear(width, width)
        self.mlp_norm = nn.LayerNorm(width)
        self.mlp = nn.Sequential(
            nn.Linear(width, 4 * width), nn.GELU(), nn.Linear(4 * width, width)
        )

    def forward(self, hidden, attention_mask):
        batch, length, width = hidden.shape
        q, k, v = self.qkv(self.attention_norm(hidden)).split(width, dim=-1)
        shape = (batch, length, self.heads, width // self.heads)
        q, k, v = (t.view(shape).transpose(1, 2) for t in (q, k, v))
        causal = torch.ones(length, length, dtype=torch.bool, device=hidden.device).tril()
        allowed = causal[None, None] & attention_mask.bool()[:, None, None, :]
        attended = F.scaled_dot_product_attention(q, k, v, attn_mask=allowed)
        hidden = hidden + self.out(attended.transpose(1, 2).reshape(batch, length, width))
        return hidden + self.mlp(self.mlp_norm(hidden))


class ScratchDecoder(nn.Module):
    def __init__(self, vocab_size, width=64, layers=4, heads=4, max_length=256):
        super().__init__()
        self.embed = nn.Embedding(vocab_size, width)
        self.positions = nn.Embedding(max_length, width)
        self.blocks = nn.ModuleList(_Block(width, heads) for _ in range(layers))
        self.norm = nn.LayerNorm(width)
        self.lm_head = nn.Linear(width, vocab_size, bias=False)

    @property
    def functional_num_layers(self):
        return len(self.blocks)

    def functional_forward_to_boundary(self, input_ids, attention_mask, boundary):
        positions = torch.arange(input_ids.shape[1], device=input_ids.device)
        hidden = self.embed(input_ids) + self.positions(positions)[None]
        for block in self.blocks[:boundary]:
            hidden = block(hidden, attention_mask)
        return hidden

    def functional_states_from_boundary(self, hidden, attention_mask, boundary):
        for block in self.blocks[boundary:]:
            hidden = block(hidden, attention_mask)
        return self.norm(hidden)

    def functional_forward_from_boundary(self, hidden, attention_mask, boundary):
        return self.lm_head(self.functional_states_from_boundary(hidden, attention_mask, boundary))

    def final_states(self, input_ids, attention_mask):
        hidden = self.functional_forward_to_boundary(input_ids, attention_mask, len(self.blocks))
        return self.norm(hidden)

    def forward(self, input_ids, attention_mask=None, use_cache=False):
        del use_cache
        if attention_mask is None:
            attention_mask = torch.ones_like(input_ids)
        logits = self.lm_head(self.final_states(input_ids, attention_mask))
        return type("Output", (), {"logits": logits})()
