"""Read-only native-memory evaluation; no learned route, cache or candidate head.

Choice restriction is a benchmark *scorer*, never a generation constraint.
Free generation samples the complete vocabulary with a fresh CPU RNG per pair.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from . import execution as ex


def rank(seed, key):
    return hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()


def select_worlds(rows, spec, training_groups):
    """Select whole held-out twin groups before scoring; retain control aliases."""
    pools = defaultdict(set)
    for row in rows:
        if row["split"] in ("test", "ood"):
            pools[row["split"], row["family"]].add(row["group_id"])
    selected = set()
    for split, family, count in spec["strata"]:
        pool = pools[split, family]
        ex.require(len(pool) >= count, "Held-out group coverage")
        selected.update(sorted(pool, key=lambda g: rank(spec["seed"], g))[:count])
    ex.require(not selected.intersection(training_groups), "Training group leakage")
    unique = {}
    for row in sorted(rows, key=lambda r: r["row_id"]):
        if row["group_id"] not in selected:
            continue
        signature = ex.plan_hash([row["memory"], row["query"], row["answer"]])
        if signature in unique:
            old = unique[signature]
            ex.require(old["group_id"] == row["group_id"], "Cross-group duplicate")
            old["aliases"].append(row["row_id"])
        else:
            unique[signature] = dict(row, aliases=[])
    result = sorted(unique.values(), key=lambda r: r["row_id"])
    ex.require(len(result) == spec["unique_rows"], "Frozen unique row denominator")
    return result


def normalized_answer(text):
    # Ignore only case, whitespace and a final period; explanations are not
    # accepted by prefix matching. Raw outputs are always retained.
    return re.sub(r"\s+", " ", text.strip()).rstrip(".").strip().casefold()


def encode_chat(tokenizer, text):
    ids = list(
        tokenizer.apply_chat_template(
            [{"role": "user", "content": text}],
            tokenize=True,
            add_generation_prompt=True,
            return_dict=False,
        )
    )
    ex.require(ids and all(type(i) is int and i >= 0 for i in ids), "Chat token IDs")
    return ids


def choice_tokens(tokenizer, row, cap):
    prefix = tokenizer.encode(row["prompt"], add_special_tokens=True)
    choices = []
    for letter in "ABCD":
        full = tokenizer.encode(row["prompt"] + " " + letter, add_special_tokens=True)
        ex.require(
            len(full) == len(prefix) + 1 and full[:-1] == prefix,
            "MMLU candidate is not one stable continuation token",
        )
        choices.append(full[-1])
    ex.require(len(set(choices)) == 4 and 0 < len(prefix) <= cap, "MMLU bounds")
    return dict(row, input_ids=prefix, choice_ids=choices)


def tensor_batch(prefix, memory, device, answer=None):
    import torch

    values = list(prefix) + ([] if answer is None else list(answer))
    ids = torch.tensor([values], dtype=torch.long, device=device)
    batch = dict(input_ids=ids, attention_mask=torch.ones_like(ids))
    if memory:
        mem = torch.tensor([memory], dtype=torch.long, device=device)
        batch.update(memory_ids=mem, memory_mask=torch.ones_like(mem))
    if answer is not None:
        ex.require(bool(answer), "Nonempty supervised suffix")
        batch["labels"] = torch.tensor(
            [[-100] * len(prefix) + list(answer)], dtype=torch.long, device=device
        )
    return batch


def choose(logits, *, generator, temperature, top_p):
    import torch

    scores = logits.detach().float().cpu()
    ex.require(scores.ndim == 1 and bool(torch.isfinite(scores).all()), "Finite vocabulary")
    ex.require(temperature >= 0 and 0 < top_p <= 1, "Sampling policy")
    if temperature == 0:
        return int(scores.argmax())
    probs = (scores / temperature).softmax(-1)
    ordered, indices = torch.sort(probs, descending=True, stable=True)
    remove = ordered.cumsum(-1) - ordered >= top_p
    ordered[remove] = 0
    ordered /= ordered.sum()
    return int(indices[torch.multinomial(ordered, 1, generator=generator)])


def generate(graph, prefix, memory, *, seed, cap, eos, temperature, top_p, guard):
    import torch

    ex.require(prefix and cap > 0, "Generation bounds")
    device = next(graph.parameters()).device
    generator = torch.Generator(device="cpu").manual_seed(seed)
    tokens = []
    stop = "length"
    with torch.no_grad():
        for step in range(cap):
            guard(f"generation:{step}")
            result = graph(**tensor_batch(prefix + tokens, memory, device))
            token = choose(
                result.logits[0, -1], generator=generator, temperature=temperature, top_p=top_p
            )
            del result
            tokens.append(token)
            if token == eos:
                stop = "eos"
                break
    return dict(
        token_ids=tokens,
        generated_tokens=len(tokens),
        stop_reason=stop,
        seed=seed,
        max_new_tokens=cap,
        temperature=temperature,
        top_p=top_p,
    )


def score_choices(logits, choices, target):
    import torch

    values = logits.detach().float().cpu()
    ex.require(bool(torch.isfinite(values).all()), "Finite choice logits")
    selected = values[choices]
    prediction = int(selected.argmax())
    ties = int((selected == selected.max()).sum())
    return dict(
        logits=selected.tolist(),
        prediction=prediction,
        target=target,
        correct=prediction == target,
        strict_correct=prediction == target and ties == 1,
        ties=ties,
        gold_logprob=float(values.log_softmax(-1)[choices[target]]),
        full_vocabulary_argmax=int(values.argmax()),
    )


def paired_counts(left, right):
    ex.require(set(left) == set(right), "Paired item coverage")
    counts = dict(both_correct=0, base_only=0, v22_only=0, both_wrong=0)
    for key in left:
        a, b = bool(left[key]), bool(right[key])
        counts[
            ("both_correct" if a and b else "base_only" if a else "v22_only" if b else "both_wrong")
        ] += 1
    return dict(
        n=len(left),
        **counts,
        base_correct=counts["both_correct"] + counts["base_only"],
        v22_correct=counts["both_correct"] + counts["v22_only"],
    )
