"""Host binding: the model-specific half of the stack behind one small protocol.

A host runs its decoder to cut N, continues from cut N to logits, exposes the
normalized final states that enter its head, and its head. ``DecoderHost`` uses
the engine's cut protocol (GPT-2, Mistral, OLMo2, and any model with the custom
split interface, which is how a from-scratch model joins) and native readout.
"""

from __future__ import annotations

from typing import Protocol

import torch
from torch import nn

from .cuts import FunctionalBoundaryAdapter
from .readout import NativeWorkspaceReadout


class Host(Protocol):
    @property
    def layer_count(self) -> int: ...

    @property
    def hidden_size(self) -> int: ...

    @property
    def head(self) -> nn.Linear: ...

    def to_cut(self, input_ids, attention_mask, cut) -> torch.Tensor: ...

    def from_cut(self, hidden, attention_mask, cut) -> torch.Tensor: ...

    def from_cut_states(self, hidden, attention_mask, cut) -> torch.Tensor: ...

    def final_states(self, input_ids, attention_mask) -> torch.Tensor: ...

    def logits(self, input_ids, attention_mask) -> torch.Tensor: ...


class DecoderHost:
    """Any decoder the cut protocol supports; the backbone is never modified."""

    def __init__(self, model: nn.Module):
        self.model = model
        self.cuts = FunctionalBoundaryAdapter(model)

    @property
    def layer_count(self):
        return self.cuts.layer_count()

    @property
    def hidden_size(self):
        return int(self.head.weight.shape[1])

    @property
    def head(self):
        head = getattr(self.model, "lm_head", None)
        if not isinstance(head, nn.Linear):
            raise TypeError("Host model needs an nn.Linear lm_head")
        return head

    def to_cut(self, input_ids, attention_mask, cut):
        return self.cuts.encode(input_ids, attention_mask, cut)

    def from_cut(self, hidden, attention_mask, cut):
        return self.cuts.decode(hidden, attention_mask, cut)

    def from_cut_states(self, hidden, attention_mask, cut):
        """The normalized states entering the head when the host continues from ``cut``."""
        return self.cuts.decode_states(hidden, attention_mask, cut)

    def final_states(self, input_ids, attention_mask):
        custom = getattr(self.model, "final_states", None)
        if callable(custom):
            return custom(input_ids, attention_mask)
        decoder = getattr(self.model, "model", None) or getattr(self.model, "transformer", None)
        if decoder is None:
            raise TypeError("Host model exposes neither final_states nor a base decoder")
        return decoder(input_ids, attention_mask=attention_mask, use_cache=False).last_hidden_state

    def logits(self, input_ids, attention_mask):
        return self.model(input_ids, attention_mask=attention_mask, use_cache=False).logits

    def readout(self):
        """The native head as a residual readout (requires a frozen head)."""
        return NativeWorkspaceReadout(self.head)
