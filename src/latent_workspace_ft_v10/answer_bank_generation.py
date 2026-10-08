"""Matched, full-vocabulary generation for the frozen V14 qualitative assay.

This module has no training, network, filesystem, reference-answer or judge path.
Each decoding step recomputes the full prefix. Identical prefixes share one
decoder call only within that step; there is no KV cache or persistent hidden
state cache. Native head geometry is the complete sequence and vocabulary.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Callable

import torch

CONDITIONS = (
    "base",
    "base_inline",
    "legacy_semantic",
    "centered_semantic",
    "centered_zero",
    "centered_unrelated",
    "centered_twin",
)


def matched_uniform(case_id: str, seed: int, step: int) -> dict:
    """A counter-based common random number, independent of condition/history.

    The top 53 hash bits map to [0, 1), including zero but never one. Token-ID
    CDF sampling therefore couples distributions without sorting their logits.
    """
    if not isinstance(case_id, str) or not case_id or type(seed) is not int or step < 0:
        raise ValueError("Invalid common-random-number coordinates")
    payload = json.dumps(
        ["v14-answer-bank-uniform-v1", case_id, seed, step], separators=(",", ":")
    ).encode()
    digest = hashlib.sha256(payload).hexdigest()
    return {"sha256": digest, "value": (int(digest[:16], 16) >> 11) / 2**53}


def choose_token(logits: torch.Tensor, temperature: float, uniform: float) -> tuple[int, float]:
    """Greedy lowest-ID tie break or CPU FP64 inverse CDF in token-ID order."""
    if logits.ndim != 1 or not logits.numel() or not bool(torch.isfinite(logits).all()):
        raise ValueError("Expected finite nonempty full-vocabulary logits")
    if not math.isfinite(temperature) or temperature < 0 or not 0 <= uniform < 1:
        raise ValueError("Invalid sampling temperature or uniform")
    if temperature == 0:
        return int(logits.argmax()), 1.0
    probabilities = torch.softmax(
        logits.detach().to(device="cpu", dtype=torch.float64) / temperature, 0
    )
    cdf = probabilities.cumsum(0)
    # Make the representable probability interval exhaustive, without a top-p cut.
    cdf[-1] = 1.0
    token = int(torch.searchsorted(cdf, torch.tensor(uniform, dtype=torch.float64), right=True))
    return token, float(probabilities[token])


def native_full_readout(
    hidden: torch.Tensor, delta: torch.Tensor, head
) -> tuple[torch.Tensor, dict]:
    """Apply FP32 delta, cast back, then run the native full-sequence/full head."""
    if hidden.ndim != 3 or hidden.shape[0] != 1 or hidden.shape[1] < 1:
        raise ValueError("Expected one nonempty normalized [1,L,H] prefix")
    if delta.shape != hidden[:, -1:].shape or delta.dtype != torch.float32:
        raise ValueError("Delta must be FP32 [1,1,H]")
    if hidden.device != delta.device or not hidden.is_floating_point():
        raise ValueError("Hidden state and residual must share a device")
    if not bool(torch.isfinite(hidden).all()) or not bool(torch.isfinite(delta).all()):
        raise ValueError("Nonfinite readout input")
    with torch.autocast(device_type=hidden.device.type, enabled=False):
        corrected = (hidden[:, -1:].float() + delta).to(hidden.dtype)
        applied = corrected.float() - hidden[:, -1:].float()
    sequence = torch.cat((hidden[:, :-1], corrected), dim=1)
    logits = head(sequence)
    if logits.ndim != 3 or logits.shape[:2] != hidden.shape[:2]:
        raise ValueError("Head did not preserve full sequence geometry")
    if not bool(torch.isfinite(logits).all()):
        raise ValueError("Nonfinite native logits")
    return logits, {
        "delta_l2": float(delta.norm()),
        "native_applied_delta_l2": float(applied.norm()),
        "native_applied_fraction": float(applied.ne(0).float().mean()),
    }


@torch.no_grad()
def generate_group(
    *,
    case_id: str,
    lane: str,
    regime: dict,
    prompts: dict,
    backend,
    max_new_tokens: int,
    eos_token_ids: set[int],
    decode: Callable[[list[int]], str],
    on_answer: Callable[[dict], None] | None = None,
) -> tuple[list[dict], dict]:
    """Decode seven matched conditions with a small, duck-typed frozen backend.

    backend.encode(prefix) returns normalized states; backend.delta(condition,
    hidden) returns FP32 [1,1,H]. backend.head is the original native LM head.
    The zero-memory condition is evaluated, not replaced with a base shortcut.
    """
    if tuple(prompts) != CONDITIONS or max_new_tokens < 1:
        raise ValueError("Condition order or token budget changed")
    common = prompts["base"]["ids"]
    if not common or any(prompts[c]["ids"] != common for c in CONDITIONS if c != "base_inline"):
        raise ValueError("Non-inline conditions must have an identical nonempty initial prompt")
    if any(not prompts[c]["ids"] for c in CONDITIONS):
        raise ValueError("All prompts must be nonempty")
    records = {}
    for condition in CONDITIONS:
        records[condition] = {
            "id": f"{case_id}__{regime['id']}__{condition}",
            "case_id": case_id,
            "lane": lane,
            "condition": condition,
            "regime": regime["id"],
            "regime_parameters": dict(regime),
            "prompt_ids": list(prompts[condition]["ids"]),
            "messages": prompts[condition]["messages"],
            "rendered_prompt": prompts[condition]["rendered_prompt"],
            "generated_ids": [],
            "token_trace": [],
            "finish_reason": None,
        }
    decoder_calls = zero_checks = 0
    maximum_concurrent_prefixes = 0
    for step in range(max_new_tokens):
        groups = defaultdict(list)
        for condition, record in records.items():
            if record["finish_reason"] is None:
                groups[tuple(record["prompt_ids"] + record["generated_ids"])].append(condition)
        if not groups:
            break
        maximum_concurrent_prefixes = max(maximum_concurrent_prefixes, len(groups))
        random_number = matched_uniform(case_id, regime["seed"], step)
        for prefix, conditions in groups.items():
            hidden = backend.encode(prefix)
            decoder_calls += 1
            zero = torch.zeros_like(hidden[:, -1:], dtype=torch.float32)
            baseline, baseline_trace = native_full_readout(hidden, zero, backend.head)
            base_last = baseline[0, -1].float()
            for condition in conditions:
                if condition in ("base", "base_inline"):
                    logits, trace = baseline, dict(baseline_trace)
                else:
                    delta = backend.delta(condition, hidden)
                    logits, trace = native_full_readout(hidden, delta, backend.head)
                    if condition == "centered_zero":
                        if bool(torch.count_nonzero(delta)) or not torch.equal(logits, baseline):
                            raise RuntimeError(
                                "Zero-memory bridge is not an exact full-logit base noop"
                            )
                        zero_checks += 1
                last = logits[0, -1].float()
                token, probability = choose_token(
                    last, regime["temperature"], random_number["value"]
                )
                trace.update(
                    {
                        "step": step,
                        "token_id": token,
                        "uniform": random_number,
                        "sampling_probability": probability,
                        "native_logit_change_max_abs": float((last - base_last).abs().max()),
                        "chosen_native_logit": float(last[token]),
                        "same_prefix_base_native_logit": float(base_last[token]),
                    }
                )
                record = records[condition]
                record["generated_ids"].append(token)
                record["token_trace"].append(trace)
                if token in eos_token_ids:
                    record["finish_reason"] = "eos"
                elif step + 1 == max_new_tokens:
                    record["finish_reason"] = "length"
                # No cross-step tensor cache: a complete sequence head can be large.
                if condition not in ("base", "base_inline"):
                    del logits, delta
            del hidden, baseline, base_last
        if records["base"]["generated_ids"] != records["centered_zero"]["generated_ids"]:
            raise RuntimeError("Base and zero-memory generation diverged under matched uniforms")
    result = []
    for record in records.values():
        record["answer"] = decode(record["generated_ids"])
        record["token_count"] = len(record["generated_ids"])
        if record["finish_reason"] is None:
            raise RuntimeError("Missing generation termination receipt")
        result.append(record)
        if on_answer is not None:
            on_answer(record)
    return result, {
        "decoder_calls": decoder_calls,
        "zero_full_logit_exact_checks": zero_checks,
        "base_zero_token_ids_exact": True,
        "maximum_concurrent_prefixes": maximum_concurrent_prefixes,
        "persistent_prefix_cache_entries": 0,
        "kv_cache_used": False,
    }
