"""Differentiable latent memory through the host's native, full-vocabulary head.

This is the training counterpart of the beta's *host-only* latent-memory path,
not its two-candidate residual adapter. Memory and query/continuation tokens are
encoded separately to a cut, packed there, and decoded by the remaining host
layers. Both encodings are recomputed on every forward; detached feature banks
and cross-update memory caches are deliberately not accepted.

The component owns exactly the supplied host parameters. Optimizer offload,
checkpoint ownership, data policy and scientific gates are separate concerns.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn
from torch.nn import functional as F

from .composition import pack_memory
from .host import DecoderHost


@dataclass
class NativeCutTrace:
    """Live, opt-in diagnostic references. No detach, cache, or retained gradients."""

    query: torch.Tensor
    memory: torch.Tensor
    query_mask: torch.Tensor
    memory_mask: torch.Tensor


@dataclass
class NativeMemoryOutput:
    """Query-position logits; labels never supervise the packed memory positions.

    ``loss_sum`` and ``supervised_tokens`` permit token-weighted accumulation;
    summing per-microbatch means instead would overweight short answers.
    """

    logits: torch.Tensor
    loss: torch.Tensor | None = None
    loss_sum: torch.Tensor | None = None
    supervised_tokens: int = 0
    cut_trace: NativeCutTrace | None = None


def _tokens(ids, mask, *, name, vocab, allow_empty=False):
    if ids.ndim != 2 or ids.dtype != torch.long or ids.shape[0] == 0:
        raise ValueError(f"{name}: expected nonempty-batch int64 token ids [B, L]")
    if ids.numel() and ((ids < 0).any() or (ids >= vocab).any()):
        raise ValueError(f"{name}: token outside the host vocabulary")
    if mask is None:
        mask = torch.ones_like(ids)
    if mask.shape != ids.shape or mask.device != ids.device:
        raise ValueError(f"{name}: mask shape/device mismatch")
    if not torch.all((mask == 0) | (mask == 1)):
        raise ValueError(f"{name}: mask must be binary")
    lengths = mask.long().sum(1)
    expected = torch.arange(ids.shape[1], device=ids.device)[None] < lengths[:, None]
    if not torch.equal(mask.bool(), expected):
        raise ValueError(f"{name}: valid tokens must be left-aligned")
    if not allow_empty and (lengths == 0).any():
        raise ValueError(f"{name}: empty row")
    return mask.long(), lengths


class NativeMemoryCausalLM(nn.Module):
    """One trainable host, with a separately written latent prefix at ``cut``.

    The wrapper does not silently unfreeze the host, change its training mode,
    move it, or enable checkpointing. ``require_full_update`` fails if any
    parameter is frozen. The caller chooses those policies explicitly.

    Labels have the query/continuation layout, not the packed layout. As for a
    causal LM, label at position t is predicted at t-1. Prompt and pad labels
    must be -100; position zero cannot be supervised. A completion must include
    its prompt so its first token has a query-position predecessor.
    """

    def __init__(self, model: nn.Module, *, cut: int):
        super().__init__()
        self.model = model
        self.host = DecoderHost(model)
        if type(cut) is not int or not 0 <= cut < self.host.layer_count:
            raise ValueError("cut must leave at least one host layer to read memory")
        self.cut = cut

    def require_full_update(self):
        frozen = [name for name, param in self.model.named_parameters() if not param.requires_grad]
        if frozen:
            raise ValueError(f"Full update requires every host parameter: frozen={frozen}")
        return sum(param.numel() for param in self.model.parameters())

    def contract(self):
        """Execution metadata, not a checkpoint, parameter hash, or qualification."""
        return dict(
            schema="ltws-native-memory-graph-v1",
            boundary=self.host.cuts.describe_boundary(self.cut).to_dict(),
            route="native_full_vocabulary",
            memory_policy="reencode_from_tokens_every_forward",
            labels="query_only_next_token",
            cache="disabled",
        )

    def forward(
        self,
        input_ids,
        attention_mask=None,
        *,
        memory_ids=None,
        memory_mask=None,
        labels=None,
        capture_cut_trace=False,
    ):
        if type(capture_cut_trace) is not bool:
            raise ValueError("capture_cut_trace must be boolean")
        vocab = self.host.head.out_features
        mask, _ = _tokens(input_ids, attention_mask, name="query", vocab=vocab)
        memory_lengths = None
        if memory_ids is None:
            if memory_mask is not None:
                raise ValueError("memory_mask requires memory_ids")
        else:
            if memory_ids.ndim != 2:
                raise ValueError("memory: expected token ids [B, M]")
            if memory_ids.shape[0] != input_ids.shape[0] or memory_ids.device != input_ids.device:
                raise ValueError("Memory and query must share batch and device")
            memory_mask, memory_lengths = _tokens(
                memory_ids, memory_mask, name="memory", vocab=vocab, allow_empty=True
            )

        count = 0
        if labels is not None:
            if labels.shape != input_ids.shape or labels.dtype != torch.long:
                raise ValueError("labels must be int64 with the query shape")
            if labels.device != input_ids.device:
                raise ValueError("labels must share the query device")
            active = labels != -100
            if active[:, 0].any() or (active & ~mask.bool()).any():
                raise ValueError("No labels on padding or query position zero")
            if active.any() and ((labels[active] < 0).any() or (labels[active] >= vocab).any()):
                raise ValueError("Target outside the host vocabulary")
            count = int(active.sum())
            if count == 0:
                raise ValueError("At least one supervised next token is required")

        trace = None
        if memory_lengths is None or not memory_lengths.any():
            # Exact native bypass, including dropout RNG order in training mode.
            logits = self.host.logits(input_ids, mask)
        else:
            query = self.host.to_cut(input_ids, mask, self.cut)
            # Do not send all-padding rows through an attention implementation.
            # index_copy preserves the gradient to the live memory encodings.
            live = (memory_lengths > 0).nonzero(as_tuple=True)[0]
            encoded = self.host.to_cut(memory_ids[live], memory_mask[live], self.cut)
            memory = query.new_zeros(
                input_ids.shape[0], memory_ids.shape[1], self.host.hidden_size
            ).index_copy(0, live, encoded)
            if capture_cut_trace:
                trace = NativeCutTrace(query, memory, mask, memory_mask)
            packed, packed_mask = pack_memory(memory, memory_mask, query, mask)
            final = self.host.from_cut_states(packed, packed_mask, self.cut)
            # Apply the full native head only to query positions, saving memory
            # without selecting vocabulary rows or changing the native head.
            columns = (
                memory_lengths[:, None]
                + torch.arange(input_ids.shape[1], device=input_ids.device)[None]
            )
            rows = torch.arange(input_ids.shape[0], device=input_ids.device)[:, None]
            logits = self.host.head(final[rows, columns])

        result = NativeMemoryOutput(logits=logits, supervised_tokens=count, cut_trace=trace)
        if labels is not None:
            result.loss_sum = F.cross_entropy(
                logits[:, :-1].float().reshape(-1, vocab),
                labels[:, 1:].reshape(-1),
                ignore_index=-100,
                reduction="sum",
            )
            result.loss = result.loss_sum / count
        return result
