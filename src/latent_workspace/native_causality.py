"""Inference-only cut-state interventions, independent of decoder architecture.

These probes are NOT a learner change. Zero/reversed states are off-manifold
stress controls, not semantic counterfactuals. A foreign writer holds the reader
(including query encoder and head) fixed; it does not isolate a decoder layer.
"""

from __future__ import annotations

import hashlib

import torch
from torch import nn

from . import execution as ex
from .composition import pack_memory
from .native_memory import NativeMemoryOutput, _tokens


def tensor_digest(value):
    raw = value.detach().contiguous().view(torch.uint8).cpu().numpy().tobytes()
    return hashlib.sha256(raw).hexdigest()


def difference(reference, changed):
    ex.require(reference.shape == changed.shape, "Comparable diagnostic shapes")
    a, b = reference.detach().float(), changed.detach().float()
    ex.require(bool(torch.isfinite(a).all() & torch.isfinite(b).all()), "Finite comparison")
    delta = b - a
    return dict(
        exact=torch.equal(reference, changed),
        changed_elements=int((reference != changed).sum()),
        max_abs=float(delta.abs().max()),
        rms=float(delta.square().mean().sqrt()),
        top1_same=int(a.argmax()) == int(b.argmax()),
    )


def prefix_variants(prefix, gold, index, memory, device, vocab):
    """Same prediction position, separately vary extent, mask and future content."""
    from .native_evaluation import tensor_batch

    ex.require(prefix and 0 <= index < len(gold), "Prefix assay index")
    full = list(prefix) + list(gold)
    length = len(prefix) + index
    cropped = tensor_batch(full[:length], memory, device)
    changed = tensor_batch(full[:length] + [(v + 1) % vocab for v in full[length:]], memory, device)
    padded = tensor_batch(full[:length] + [0] * (len(full) - length), memory, device)
    padded["attention_mask"][:, length:] = 0
    return dict(cropped=cropped, padded=padded, changed_future=changed)


class MemoryProbe(nn.Module):
    """Batch-one, eval-only use of the SAME host/cut/packing/native head.

    With replacement, memory_ids are a layout witness of exactly that length;
    the externally encoded memory states replace only the writer output.
    Queries/continuations are always re-encoded by the current reader. Nothing
    is persisted in the graph and no cache, head hook or method is replaced.
    Identity must be checked against NativeMemoryCausalLM before intervention.
    """

    def __init__(self, graph, *, mode="identity", replacement=None):
        super().__init__()
        ex.require(mode in ("identity", "zero", "reverse", "replacement"), "Probe mode")
        ex.require((mode == "replacement") == (replacement is not None), "Replacement policy")
        self.graph, self.mode, self.replacement = graph, mode, replacement

    def forward(self, input_ids, attention_mask=None, *, memory_ids=None, memory_mask=None):
        graph = self.graph
        ex.require(not graph.training and not torch.is_grad_enabled(), "Read-only eval probe")
        ex.require(input_ids.shape[0] == 1, "Batch-one causal probe")
        mask, _ = _tokens(
            input_ids, attention_mask, name="query", vocab=graph.host.head.out_features
        )
        ex.require(memory_ids is not None and memory_ids.shape[0] == 1, "Nonempty memory probe")
        ex.require(memory_ids.device == input_ids.device, "Probe device")
        mm, lengths = _tokens(
            memory_ids, memory_mask, name="memory", vocab=graph.host.head.out_features
        )
        ex.require(bool((mm == 1).all()), "Unpadded memory witness")
        query = graph.host.to_cut(input_ids, mask, graph.cut)
        if self.mode == "replacement":
            memory = self.replacement
            ex.require(
                memory.shape == (1, memory_ids.shape[1], graph.host.hidden_size)
                and memory.dtype == query.dtype
                and memory.device == query.device
                and not memory.requires_grad
                and bool(torch.isfinite(memory).all()),
                "Exact replacement shape/dtype/device/finite policy",
            )
        else:
            memory = graph.host.to_cut(memory_ids, mm, graph.cut)
            if self.mode == "zero":
                memory = torch.zeros_like(memory)
            elif self.mode == "reverse":
                memory = memory.flip(1)
        packed, packed_mask = pack_memory(memory, mm, query, mask)
        final = graph.host.from_cut_states(packed, packed_mask, graph.cut)
        columns = lengths[:, None] + torch.arange(input_ids.shape[1], device=input_ids.device)[None]
        rows = torch.arange(1, device=input_ids.device)[:, None]
        return NativeMemoryOutput(logits=graph.host.head(final[rows, columns]))
