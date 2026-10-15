"""Matched V15 generation through the same native readout used by the learner.

The backend owns question-span binding and the condition's reader/memory. This
module never re-parses generated text for a question, never receives labels, and
never substitutes a base shortcut for a zero-memory bridge invocation. Each
step recomputes complete prefixes; sharing is only within that step, not KV
carry or evidence of a continuous-state recurrence.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Mapping

import torch

from .answer_bank_generation import choose_token, matched_uniform


def _validate_inputs(case_id, prompts, regime, max_new_tokens, eos_token_ids, zero_pairs):
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("case_id must be a nonempty string")
    if not isinstance(prompts, Mapping) or "base" not in prompts:
        raise ValueError("prompts must contain the base condition")
    for condition, ids in prompts.items():
        if not isinstance(condition, str) or not condition:
            raise ValueError("Condition names must be nonempty strings")
        if not isinstance(ids, list) or not ids:
            raise ValueError("Each prompt must be a nonempty list of token IDs")
        if any(type(token) is not int or token < 0 for token in ids):
            raise ValueError("Prompt token IDs must be nonnegative integers")
        if condition != "base_inline" and ids != prompts["base"]:
            raise ValueError("Non-inline conditions require identical initial prompt IDs")
    if type(max_new_tokens) is not int or max_new_tokens < 1:
        raise ValueError("max_new_tokens must be a positive integer")
    if not isinstance(eos_token_ids, (set, frozenset)) or any(
        type(token) is not int or token < 0 for token in eos_token_ids
    ):
        raise ValueError("EOS IDs must be a set of nonnegative integers")
    if not isinstance(regime, Mapping):
        raise ValueError("regime must be a mapping")
    if not isinstance(regime.get("id"), str) or not regime["id"]:
        raise ValueError("regime.id must be a nonempty string")
    if type(regime.get("seed")) is not int:
        raise ValueError("regime.seed must be an integer")
    temperature = regime.get("temperature")
    if type(temperature) not in (int, float) or not math.isfinite(temperature) or temperature < 0:
        raise ValueError("regime.temperature must be finite and nonnegative")
    if not isinstance(zero_pairs, (tuple, list)):
        raise ValueError("zero_pairs must be a sequence of base/zero pairs")
    seen = set()
    for pair in zero_pairs:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise ValueError("Each zero pair must have exactly two conditions")
        reference, zero_condition = pair
        if not isinstance(reference, str) or not isinstance(zero_condition, str):
            raise ValueError("Zero pair condition names must be strings")
        if reference != "base" or zero_condition not in prompts or zero_condition == "base":
            raise ValueError("Each zero pair must name base and an existing non-base condition")
        if zero_condition == "base_inline" or zero_condition in seen:
            raise ValueError("Zero conditions must be unique, non-inline bridge conditions")
        seen.add(zero_condition)
    return seen


def _validated_readout(backend, hidden, delta):
    if (
        not isinstance(hidden, torch.Tensor)
        or hidden.ndim != 3
        or hidden.shape[0] != 1
        or hidden.shape[1] < 1
        or hidden.shape[2] < 1
        or not hidden.is_floating_point()
    ):
        raise ValueError("encode must return one nonempty normalized [1,L,H] prefix")
    if (
        not isinstance(delta, torch.Tensor)
        or delta.shape != hidden[:, -1:].shape
        or delta.dtype != torch.float32
        or delta.device != hidden.device
    ):
        raise ValueError("Reader delta must be FP32 [1,1,H] on the hidden state's device")
    if not bool(torch.isfinite(hidden).all()) or not bool(torch.isfinite(delta).all()):
        raise ValueError("Nonfinite hidden state or reader delta")
    result = backend.readout(hidden, delta)
    logits, last = result.logits, result.last_logits
    if (
        not isinstance(logits, torch.Tensor)
        or not isinstance(last, torch.Tensor)
        or logits.ndim != 3
        or logits.shape[:2] != hidden.shape[:2]
        or logits.shape[-1] < 1
        or logits.device != hidden.device
        or last.shape != (1, logits.shape[-1])
        or last.dtype != torch.float32
        or last.device != hidden.device
        or not torch.equal(logits[:, -1].float(), last)
        or not bool(torch.isfinite(logits).all())
    ):
        raise ValueError("Readout must preserve finite full-sequence/full-vocabulary native logits")
    return result


@torch.no_grad()
def generate_matched(
    *,
    case_id: str,
    prompts: Mapping[str, list[int]],
    regime: Mapping,
    max_new_tokens: int,
    eos_token_ids: set[int],
    backend,
    decode: Callable[[list[int]], str],
    zero_pairs=(("base", "final_zero"), ("base", "mean_zero")),
    guard: Callable[[], None] | None = None,
) -> tuple[list[dict], dict]:
    """Generate condition-matched continuations and explicit execution receipts.

    ``backend.encode(tuple_ids)`` returns normalized full-prefix states;
    ``backend.delta(condition, hidden, tuple_ids)`` reads the selected memory;
    ``backend.readout(hidden, delta)`` is the shared NativeWorkspaceReadout.
    The backend must bind any pooled question span to the original prompt.
    Base and base_inline use zero deltas through that same readout. ``guard``
    runs before each prefix encode and may raise to stop the caller's own run.

    Native probabilities are temperature-1 softmax probabilities. Sampling
    probabilities instead describe the specified decoding policy (1 for a
    greedy chosen token), so the two are deliberately recorded separately.
    Every logit difference uses base *at the condition's current prefix*;
    after token divergence it is not a comparison to base's different history.
    """
    zero_conditions = _validate_inputs(
        case_id, prompts, regime, max_new_tokens, eos_token_ids, zero_pairs
    )
    if not callable(decode) or (guard is not None and not callable(guard)):
        raise ValueError("decode and optional guard must be callable")
    records = {
        condition: {
            "id": f"{case_id}__{regime['id']}__{condition}",
            "case_id": case_id,
            "condition": condition,
            "regime": regime["id"],
            "regime_parameters": dict(regime),
            "prompt_ids": list(ids),
            "generated_ids": [],
            "token_trace": [],
            "finish_reason": None,
        }
        for condition, ids in prompts.items()
    }
    decoder_calls = maximum_concurrent_prefixes = 0
    zero_checks = {condition: 0 for condition in sorted(zero_conditions)}
    for step in range(max_new_tokens):
        groups = defaultdict(list)
        for condition, row in records.items():
            if row["finish_reason"] is None:
                groups[tuple(row["prompt_ids"] + row["generated_ids"])].append(condition)
        if not groups:
            break
        maximum_concurrent_prefixes = max(maximum_concurrent_prefixes, len(groups))
        uniform = matched_uniform(case_id, regime["seed"], step)
        for prefix, conditions in groups.items():
            if guard is not None:
                guard()
            hidden = backend.encode(prefix)
            # Validate hidden before indexing so malformed backends fail closed.
            if not isinstance(hidden, torch.Tensor) or hidden.ndim != 3:
                raise ValueError("encode must return normalized [1,L,H] states")
            if hidden.shape[1] != len(prefix):
                raise ValueError("encode changed the full prefix length")
            decoder_calls += 1
            zero = torch.zeros_like(hidden[:, -1:], dtype=torch.float32)
            baseline = _validated_readout(backend, hidden, zero)
            base_last = baseline.last_logits[0].detach().to(device="cpu", dtype=torch.float64)
            if any(token >= base_last.numel() for token in eos_token_ids):
                raise ValueError("EOS token ID lies outside the native vocabulary")
            base_probability = torch.softmax(base_last, 0)
            base_top1 = int(base_last.argmax())
            for condition in conditions:
                if condition in ("base", "base_inline"):
                    delta, result = zero, baseline
                else:
                    delta = backend.delta(condition, hidden, prefix)
                    result = _validated_readout(backend, hidden, delta)
                    if result.logits.shape != baseline.logits.shape:
                        raise ValueError("Condition changed the native vocabulary geometry")
                    if condition in zero_conditions:
                        if bool(torch.count_nonzero(delta)) or not torch.equal(
                            result.logits, baseline.logits
                        ):
                            raise RuntimeError(
                                "Zero-memory bridge is not an exact full-logit base noop"
                            )
                        zero_checks[condition] += 1
                last = result.last_logits[0].detach().to(device="cpu", dtype=torch.float64)
                token, sampling_probability = choose_token(
                    last, regime["temperature"], uniform["value"]
                )
                probabilities = torch.softmax(last, 0)
                change = last - base_last
                trace = {
                    "step": step,
                    "token_id": token,
                    "uniform": dict(uniform),
                    "sampling_probability": sampling_probability,
                    "chosen_token_native_probability": float(probabilities[token]),
                    "same_prefix_base_chosen_token_native_probability": float(
                        base_probability[token]
                    ),
                    "chosen_native_logit": float(last[token]),
                    "same_prefix_base_native_logit": float(base_last[token]),
                    "native_logit_change_max_abs": float(change.abs().max()),
                    "native_logit_change_l2": float(change.norm()),
                    "native_top1_token_id": int(last.argmax()),
                    "same_prefix_base_native_top1_token_id": base_top1,
                    "native_top1_changed": int(last.argmax()) != base_top1,
                    "delta_l2": float(delta.double().norm()),
                }
                if hasattr(result, "applied_delta"):
                    applied = result.applied_delta
                    trace.update(
                        native_applied_delta_l2=float(applied.double().norm()),
                        native_applied_fraction=float(applied.ne(0).float().mean()),
                    )
                row = records[condition]
                row["generated_ids"].append(token)
                row["token_trace"].append(trace)
                if token in eos_token_ids:
                    row["finish_reason"] = "eos"
                elif step + 1 == max_new_tokens:
                    row["finish_reason"] = "length"
                del result, delta, last, probabilities, change
            del hidden, zero, baseline, base_last, base_probability
        for reference, zero_condition in zero_pairs:
            if (
                records[reference]["generated_ids"] != records[zero_condition]["generated_ids"]
                or records[reference]["finish_reason"] != records[zero_condition]["finish_reason"]
            ):
                raise RuntimeError(
                    "Base and zero-memory generation diverged under matched uniforms"
                )
    rows = list(records.values())
    for row in rows:
        row["answer"] = decode(list(row["generated_ids"]))
        row["token_count"] = len(row["generated_ids"])
        if row["finish_reason"] is None:
            raise RuntimeError("Missing generation termination receipt")
    return rows, {
        "decoder_calls": decoder_calls,
        "zero_full_logit_exact_checks": sum(zero_checks.values()),
        "zero_full_logit_exact_checks_by_condition": zero_checks,
        "zero_pairs": [list(pair) for pair in zero_pairs],
        "base_zero_token_ids_exact": True,
        "maximum_concurrent_prefixes": maximum_concurrent_prefixes,
        "persistent_prefix_cache_entries": 0,
        "kv_cache_used": False,
        "readout_contract": "shared_native_full_sequence_full_vocabulary",
        "logit_reference": "base_at_same_current_prefix",
        "reader_span_owner": "backend_bound_original_prompt",
    }
