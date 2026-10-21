"""Read-only diagnostics at the native head; never alter model computation.

FP32 projections are explicitly different arithmetic on the *same rounded*
head inputs and weights, not an FP32 decoder and not replacement evaluation.
"""

from __future__ import annotations

import math

import torch
from torch.nn import functional as F

from . import execution as ex


def observe(graph, batch, positions, head_fp32):
    """Capture only named query positions entering the head, removing the hook."""
    ex.require(bool(positions), "Nonempty head positions")
    length = batch["input_ids"].shape[1]
    ex.require(all(type(i) is int and 0 <= i < length for i in positions), "Head positions")
    captured = []

    def capture(_module, args):
        states = args[0]
        ex.require(states.shape[:2] == batch["input_ids"].shape, "Query-only head layout")
        captured.append(states[:, positions].detach().clone())

    handle = graph.host.head.register_forward_pre_hook(capture)
    try:
        with torch.no_grad():
            output = graph(**batch)
    finally:
        handle.remove()
    ex.require(len(captured) == 1, "Exactly one native head application")
    states = captured[0]
    native = output.logits[:, positions].detach().clone()
    bias = graph.host.head.bias
    with torch.no_grad():
        fp32 = F.linear(states.float(), head_fp32, None if bias is None else bias.float())
    ex.require(bool(torch.isfinite(fp32).all()), "Finite FP32 diagnostic readout")
    return output, states, native, fp32


def token_score(logits, target):
    scores = logits.detach().float()
    ex.require(scores.ndim == 1 and 0 <= target < len(scores), "Token score shape/target")
    ex.require(bool(torch.isfinite(scores).all()), "Finite token scores")
    gold = scores[target]
    best, index = scores.max(0)
    others = scores.clone()
    others[target] = -torch.inf
    return dict(
        target=target,
        top1=int(index),
        correct=int(index) == target,
        top_ties=int((scores == best).sum()),
        gold_rank=1 + int((scores > gold).sum()),
        gold_logprob=float(scores.log_softmax(0)[target]),
        gold_margin=float(gold - others.max()),
        gold_logit=float(gold),
        top_logit=float(best),
    )


def first_difference(gold, observed):
    for i, (a, b) in enumerate(zip(gold, observed)):
        if a != b:
            return i
    return None if len(gold) == len(observed) else min(len(gold), len(observed))


def weight_delta(original, native, master, *, chunk=1_048_576):
    """Streaming CPU FP64 reductions, with exact native/master cast checking."""
    ex.require(original.shape == native.shape == master.shape, "Weight shapes")
    ex.require(original.dtype == native.dtype and master.dtype == torch.float32, "Weight dtype")
    ex.require(all(t.device.type == "cpu" for t in (original, native, master)), "CPU census")
    ex.require(chunk > 0, "Positive census chunk")
    a, b, c = (t.detach().reshape(-1) for t in (original, native, master))
    count = dict(native_changed=0, master_changed=0, master_changed_native_unchanged=0)
    sums = dict(original_sq=0.0, native_delta_sq=0.0, master_delta_sq=0.0, cast_error_sq=0.0)
    maxima = dict(native_delta_max=0.0, master_delta_max=0.0)
    for start in range(0, a.numel(), chunk):
        aa, bb, cc = (t[start : start + chunk] for t in (a, b, c))
        ex.require(bool(torch.isfinite(cc).all()), "Finite master census")
        ex.require(torch.equal(cc.to(bb.dtype), bb), "Master/native cast census")
        nc, mc = bb != aa, cc != aa.float()
        count["native_changed"] += int(nc.sum())
        count["master_changed"] += int(mc.sum())
        count["master_changed_native_unchanged"] += int((mc & ~nc).sum())
        af, bf, cf = (t.double() for t in (aa, bb, cc))
        nd, md, qe = bf - af, cf - af, cf - bf
        for name, value in zip(sums, (af, nd, md, qe), strict=True):
            sums[name] += float(value.square().sum())
        maxima["native_delta_max"] = max(maxima["native_delta_max"], float(nd.abs().max()))
        maxima["master_delta_max"] = max(maxima["master_delta_max"], float(md.abs().max()))
    denom = math.sqrt(sums["original_sq"])
    return dict(
        numel=a.numel(),
        shape=list(original.shape),
        dtype=str(original.dtype),
        **count,
        **sums,
        **maxima,
        native_relative_l2=None if denom == 0 else math.sqrt(sums["native_delta_sq"]) / denom,
        master_relative_l2=None if denom == 0 else math.sqrt(sums["master_delta_sq"]) / denom,
    )
