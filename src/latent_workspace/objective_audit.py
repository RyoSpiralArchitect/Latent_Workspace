"""Train-only objective instrumentation; not an alternative trainer or adapter.

The owner's ordinary CE, denominator and checkpoint contract remain unchanged.
Oracle spans are chosen before scoring. Boundary-straddling tokens remain an
explicit mixed bucket, never silently reassigned to manufacture a semantic gain.
"""

from __future__ import annotations

import math
import re

import torch
from torch.nn import functional as F

from . import execution as ex
from .composition import pack_memory

PARTS = ("identity", "copy", "format", "mixed")


def oracle_partition(tokenizer, value, candidates):
    """Partition ``' ' + value + '.' + EOS`` without observing any model output.

    Identity ends at the shortest lexical token prefix distinguishing the gold
    from other oracle symbols. A prefix-ambiguous value, number, or abstention
    uses its whole lexical span. This is a local discriminator, not a reasoning
    label. A token touching both value and suffix is mixed, including fused
    punctuation; EOS is always format. Offsets must come from a fast tokenizer.
    """
    ex.require(isinstance(value, str) and value and value == value.strip(), "Oracle value")
    text = " " + value + "."
    encoded = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
    ids, offsets = list(encoded["input_ids"]), list(encoded["offset_mapping"])
    ex.require(len(ids) == len(offsets) > 0, "Tokenizer offsets")
    end = 1 + len(value)
    lexical = []
    categories = []
    for i, (start, stop) in enumerate(offsets):
        ex.require(0 <= start < stop <= len(text), "Nonempty character offsets")
        if stop <= 1 or start >= end:
            categories.append("format")
        elif stop > end:
            categories.append("mixed")
        else:
            categories.append("identity")
            lexical.append(i)
    distinct = sorted(set(candidates) - {value})
    ex.require(all(isinstance(c, str) and c for c in distinct), "Oracle candidates")
    target = [ids[i] for i in lexical]
    alternatives = []
    for candidate in distinct:
        other = tokenizer(
            " " + candidate + ".", add_special_tokens=False, return_offsets_mapping=True
        )
        alternatives.append(
            [
                t
                for t, (a, b) in zip(other["input_ids"], other["offset_mapping"])
                if b > 1 and a < 1 + len(candidate) and b <= 1 + len(candidate)
            ]
        )
    # No candidate set or no separating prefix => do not invent later-copy labels.
    identity_length = len(target)
    if re.fullmatch(r"N[a-z]+", value) and alternatives:
        for k in range(1, len(target) + 1):
            if all(target[:k] != other[:k] for other in alternatives):
                identity_length = k
                break
        for i in lexical[identity_length:]:
            categories[i] = "copy"
    eos = tokenizer.eos_token_id
    ex.require(type(eos) is int and eos >= 0, "Explicit EOS")
    return dict(
        input_ids=ids + [eos],
        parts=categories + ["format"],
        lexical_tokens=len(lexical),
        identity_prefix_tokens=identity_length,
        candidate_count=len(distinct),
        rule="oracle_lexical_prefix_v1",
        offsets=[list(v) for v in offsets] + [None],
    )


def partitioned_ce(logits, labels, parts, *, denominator=None):
    """Four contributions with ONE total-token denominator, plus untouched CE.

    ``parts`` has label layout: -1 on unsupervised positions, 0..3 otherwise.
    Floating summation order may differ for the diagnostic sum of parts. The
    returned total uses the existing fused reduction and is the parity anchor.
    """
    ex.require(logits.ndim == 3 and labels.shape == logits.shape[:2], "Logit/label shape")
    ex.require(labels.dtype == torch.long and labels.device == logits.device, "Labels")
    ex.require(
        parts.shape == labels.shape and parts.dtype == torch.long and parts.device == labels.device,
        "Part layout",
    )
    active = labels != -100
    ex.require(not active[:, 0].any() and active.any(), "Causal labels")
    ex.require(torch.equal(parts == -1, ~active), "No missing or unsupervised part")
    ex.require(((parts[active] >= 0) & (parts[active] < len(PARTS))).all(), "Part range")
    count = int(active.sum())
    denominator = count if denominator is None else denominator
    ex.require(type(denominator) is int and denominator >= count, "Whole-window denominator")
    pred, target = logits[:, :-1].float().reshape(-1, logits.shape[-1]), labels[:, 1:].reshape(-1)
    token_loss = F.cross_entropy(pred, target, ignore_index=-100, reduction="none")
    contribution = {
        name: (token_loss * (parts[:, 1:].reshape(-1) == i)).sum() / denominator
        for i, name in enumerate(PARTS)
    }
    total = F.cross_entropy(pred, target, ignore_index=-100, reduction="sum") / denominator
    ex.require(bool(torch.isfinite(total)), "Finite CE")
    return dict(
        total=total,
        components=contribution,
        supervised_tokens=count,
        denominator=denominator,
        counts={n: int((parts == i).sum()) for i, n in enumerate(PARTS)},
    )


def full_vocab_kl_sum(student, teacher_log_probs, active):
    """Diagnostic primitive only: forward KL(teacher || student), all vocab rows.

    Caller owns causal alignment, train-only provenance and frozen target hashes.
    Targets must be detached FP32 full-vocabulary normalized log probabilities;
    top-k and BF16-compressed targets are not this objective. No trainer wiring.
    """
    ex.require(student.shape == teacher_log_probs.shape and student.ndim == 3, "Full vocabulary")
    ex.require(
        teacher_log_probs.dtype == torch.float32 and not teacher_log_probs.requires_grad,
        "Detached FP32 targets",
    )
    ex.require(
        teacher_log_probs.device == student.device and active.device == student.device, "KL device"
    )
    ex.require(
        active.shape == student.shape[:2] and active.dtype == torch.bool and active.any(),
        "KL token mask",
    )
    ex.require(bool(torch.isfinite(teacher_log_probs).all()), "Finite targets")
    ex.require(
        torch.allclose(
            teacher_log_probs.logsumexp(-1),
            torch.zeros_like(teacher_log_probs[..., 0]),
            atol=2e-6,
            rtol=0,
        ),
        "Normalized full distribution",
    )
    loss = F.kl_div(
        F.log_softmax(student.float(), -1), teacher_log_probs, reduction="none", log_target=True
    ).sum(-1)
    result = loss[active].sum()
    ex.require(bool(torch.isfinite(result)), "Finite KL")
    return result


def _grad(loss, value):
    (grad,) = torch.autograd.grad(loss, value, retain_graph=True, allow_unused=True)
    return torch.zeros_like(value) if grad is None else grad


def gradient_stats(value):
    v = value.detach().to(device="cpu", dtype=torch.float64)
    return dict(
        elements=v.numel(),
        nonzero=int(v.count_nonzero()),
        positive=int((v > 0).sum()),
        negative=int((v < 0).sum()),
        l2=float(v.norm()),
        rms=float(v.square().mean().sqrt()) if v.numel() else 0.0,
        max_abs=float(v.abs().max()) if v.numel() else 0.0,
        dtype=str(value.dtype),
    )


def cosine(left, right):
    a, b = (v.detach().to(device="cpu", dtype=torch.float64).reshape(-1) for v in (left, right))
    denominator = float(a.norm() * b.norm())
    return float(a.dot(b) / denominator) if denominator else None


def state_gradient_audit(output, labels, parts):
    """Cut-state gradients, with prompt and fixed continuation kept distinct.

    Retains only small cut-state arrays, not a collection of parameter gradients.
    Zero entries are observations; they are not evidence of absent semantics.
    """
    trace = output.cut_trace
    ex.require(
        trace is not None and trace.query.requires_grad and trace.memory.requires_grad,
        "Live nonempty-memory cut trace required",
    )
    objective = partitioned_ce(output.logits, labels, parts)
    state = {}
    terms = {"total": objective["total"], **objective["components"]}
    q_masks = {
        "question": (labels == -100) & trace.query_mask.bool(),
        "continuation": (labels != -100) & trace.query_mask.bool(),
    }
    for name, loss in terms.items():
        dm, dq = torch.autograd.grad(loss, (trace.memory, trace.query), retain_graph=True)
        state[name] = {
            "memory": dm[trace.memory_mask.bool()],
            **{k: dq[mask] for k, mask in q_masks.items()},
        }
    blocks = ("memory", "question", "continuation")
    return dict(
        counts=objective["counts"],
        denominator=objective["denominator"],
        loss={n: float(v.detach()) for n, v in terms.items()},
        gradients={n: {b: gradient_stats(v) for b, v in s.items()} for n, s in state.items()},
        component_sum_residual={
            b: gradient_stats(sum(state[n][b].float() for n in PARTS) - state["total"][b].float())
            for b in blocks
        },
        component_cosines={
            b: {
                f"{a}/{c}": cosine(state[a][b], state[c][b])
                for i, a in enumerate(PARTS)
                for c in PARTS[i + 1 :]
            }
            for b in blocks
        },
        native_update_visibility="NOT_MEASURED_NO_OPTIMIZER_UPDATE",
    )


def parameter_path_audit(graph, output, labels):
    """Independently verify full gradient = W + Q + direct R, one tensor at a time.

    Eval-mode only (dropout must not change the replay). Shared/tied parameters
    can participate in several paths, including embeddings also used by a head.
    This deliberately expensive reference qualifies attribution on tiny hosts;
    it is NOT a resource-qualified 7B implementation. No parameters or .grad
    fields are modified. At most four gradients of one parameter are retained.
    """
    trace = output.cut_trace
    ex.require(not any(m.training for m in graph.modules()), "Deterministic eval-mode audit")
    ex.require(trace is not None and output.loss is not None, "Live labeled memory trace")
    ex.require(
        all(p.requires_grad and p.grad is None for p in graph.parameters()), "Clean gradients"
    )
    dm, dq = torch.autograd.grad(output.loss, (trace.memory, trace.query), retain_graph=True)
    query, memory = trace.query.detach(), trace.memory.detach()
    packed, mask = pack_memory(memory, trace.memory_mask, query, trace.query_mask)
    final = graph.host.from_cut_states(packed, mask, graph.cut)
    columns = trace.memory_mask.sum(1)[:, None] + torch.arange(query.shape[1], device=query.device)
    rows = torch.arange(query.shape[0], device=query.device)[:, None]
    logits = graph.host.head(final[rows, columns])
    ex.require(torch.equal(logits, output.logits), "Upper-reader replay must be bitwise exact")
    direct = F.cross_entropy(
        logits[:, :-1].float().reshape(-1, logits.shape[-1]),
        labels[:, 1:].reshape(-1),
        ignore_index=-100,
        reduction="sum",
    )
    direct = direct / output.supervised_tokens
    for name, param in graph.model.named_parameters():
        full = _grad(output.loss, param)
        (w,) = torch.autograd.grad(
            trace.memory, param, grad_outputs=dm, retain_graph=True, allow_unused=True
        )
        (q,) = torch.autograd.grad(
            trace.query, param, grad_outputs=dq, retain_graph=True, allow_unused=True
        )
        w = torch.zeros_like(param) if w is None else w
        q = torch.zeros_like(param) if q is None else q
        r = _grad(direct, param)
        error = w.float() + q.float() + r.float() - full.float()
        yield dict(
            name=name,
            full=gradient_stats(full),
            W=gradient_stats(w),
            Q=gradient_stats(q),
            R=gradient_stats(r),
            W_Q_cosine=cosine(w, q),
            residual=gradient_stats(error),
            finite=all(bool(torch.isfinite(v).all()) for v in (full, w, q, r)),
        )
        del full, w, q, r, error


def validate_path_residuals(records, *, atol, rtol):
    """Explicit reference-test tolerances; not a scientific decision threshold."""
    ex.require(math.isfinite(atol) and atol >= 0 and math.isfinite(rtol) and rtol >= 0, "Tolerance")
    ex.require(records and len({r["name"] for r in records}) == len(records), "Parameter census")
    return all(
        r["finite"] and r["residual"]["max_abs"] <= atol + rtol * r["full"]["max_abs"]
        for r in records
    )


def gradient_conflicts(left_loss, right_loss, named_parameters):
    """Reference pairwise objective dot products, streaming one parameter at a time.

    Like path attribution, this is tiny-qualified algebra, not a fast 7B runner.
    Null cosine denotes a zero-norm path, never agreement. No .grad accumulation.
    """
    for name, parameter in named_parameters:
        left, right = _grad(left_loss, parameter), _grad(right_loss, parameter)
        a, b = (v.detach().to(device="cpu", dtype=torch.float64).reshape(-1) for v in (left, right))
        yield dict(
            name=name,
            left_l2=float(a.norm()),
            right_l2=float(b.norm()),
            dot=float(a.dot(b)),
            cosine=cosine(left, right),
            finite=bool(torch.isfinite(a).all() and torch.isfinite(b).all()),
        )
        del left, right, a, b
