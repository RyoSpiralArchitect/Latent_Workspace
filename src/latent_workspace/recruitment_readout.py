"""Model-neutral measurement of JSON values, reference assistance and generation.

No new learner, sampler, forced answer, postprocessing or changed historical
target. Field order is an explicitly labelled diagnostic factor. A field token
is not proof of reasoning; gold-prefix assistance is recorded at every position.
"""

from __future__ import annotations

import copy
import json
from collections import Counter

from . import execution as ex
from . import native_evaluation as ev
from . import readout_audit as audit
from . import recruitment_bank as bank

PARTS = ("answer", "steps", "format", "mixed", "stop")
ORDERS = ("answer_first", "steps_first")


def select_development(raw, *, seed, groups_per_family, exposed_keys):
    """Hash-selected whole dev groups, excluding EVERY previously exposed group."""
    ex.require(type(groups_per_family) is int and groups_per_family > 0, "Finite quota")
    reasoning = [r for r in raw if r["role"] == "reasoning"]
    bank.audit(reasoning)
    exposed = {r["group_id"] for r in reasoning if r["row_id"] in set(exposed_keys)}
    training = {r["group_id"] for r in reasoning if r["split"] == "train"}
    chosen = []
    for family in bank.FAMILIES:
        pool = {
            r["group_id"] for r in reasoning if r["split"] == "dev" and r["family"] == family
        } - exposed
        ex.require(len(pool) >= groups_per_family, "Unexposed development coverage")
        chosen.extend(sorted(pool, key=lambda g: ev.rank(seed, g))[:groups_per_family])
    ex.require(not set(chosen) & (training | exposed), "Whole-group leakage")
    seen = {}
    for row in sorted(reasoning, key=lambda r: r["row_id"]):
        if row["group_id"] not in chosen:
            continue
        signature = ex.plan_hash([row["group_id"], row["memory"], row["query"], row["answer"]])
        if signature in seen:
            seen[signature]["aliases"].append(row["row_id"])
        else:
            seen[signature] = dict(copy.deepcopy(row), aliases=[])
    rows = list(seen.values())
    ex.require(len(rows) == len(chosen) * 6, "Six unique rows per complete twin/control group")
    return dict(
        rows=rows,
        selected_groups=chosen,
        excluded_exposed_groups=sorted(exposed),
        groups=len(chosen),
        raw_rows=len(chosen) * 8,
        unique_rows=len(rows),
        confirmation_rows=0,
        training_group_overlap=0,
        exposed_group_overlap=0,
    )


def reference(tokenizer, expected, order):
    """Use tokenizer offsets, not a guessed split, for the predeclared reference.

    Value punctuation (quotes, list brackets and separators) is format; a token
    straddling any categories is mixed. All buckets remain in the denominator.
    The first answer-bearing token sees no earlier gold answer token, even if it
    is mixed. Subsequent answer tokens see their own teacher-forced partial answer.
    """
    ex.require(order in ORDERS, "Declared reference order")
    ex.require(set(expected) in ({"answer"}, {"answer", "steps"}), "Expected JSON fields")
    chars, fields, regions = [], [], []

    def emit(text, field="format"):
        chars.extend(text)
        fields.extend([field] * len(text))
        regions.extend([None] * len(text))

    def value(obj, field):
        start = len(chars)
        if isinstance(obj, list):
            emit("[")
            for i, item in enumerate(obj):
                if i:
                    emit(",")
                value(item, field)
            emit("]")
        elif type(obj) is str:
            text = ex.canonical(obj)
            emit('"')
            emit(text[1:-1], field)
            emit('"')
        else:
            ex.require(obj is None or type(obj) is int, "Typed finite oracle value")
            emit(ex.canonical(obj), field)
        regions[start:] = [field] * (len(chars) - start)

    keys = ["answer", "steps"] if order == "answer_first" else ["steps", "answer"]
    emit(" {")
    for i, key in enumerate(k for k in keys if k in expected):
        if i:
            emit(",")
        emit(ex.canonical(key) + ":")
        value(expected[key], key)
    emit("}")
    text = "".join(chars)
    if order == "answer_first":
        ex.require(text == " " + ex.canonical(expected), "Historical target order unchanged")
    encoded = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
    ids, offsets = list(encoded["input_ids"]), list(encoded["offset_mapping"])
    ex.require(ids == tokenizer.encode(text, add_special_tokens=False), "Tokenizer ID parity")
    ex.require(len(ids) == len(offsets) > 0, "Explicit offsets for every token")
    covered, tokens, seen_answer = set(), [], False
    for start, stop in offsets:
        ex.require(
            type(start) is int and type(stop) is int and 0 <= start < stop <= len(text),
            "Valid character offsets",
        )
        covered.update(range(start, stop))
        touched = sorted(set(fields[start:stop]))
        value_fields = sorted({r for r in regions[start:stop] if r is not None})
        tokens.append(
            dict(
                part=touched[0] if len(touched) == 1 else "mixed",
                touches=touched,
                value_fields=value_fields,
                gold_answer_in_prefix=seen_answer,
                offsets=[start, stop],
            )
        )
        seen_answer |= "answer" in value_fields
    ex.require(
        all(i in covered for i, f in enumerate(fields) if f != "format"),
        "No omitted value character",
    )
    # A field's brackets/quotes count as supplied value context, including [].
    # Keep a separate lexical index: syntax prediction is not a solved answer.
    answer_positions = [i for i, t in enumerate(tokens) if "answer" in t["value_fields"]]
    lexical = [i for i, t in enumerate(tokens) if "answer" in t["touches"]]
    eos = tokenizer.eos_token_id
    ex.require(type(eos) is int and eos >= 0 and eos not in ids, "One explicit terminal EOS")
    tokens.append(
        dict(
            part="stop",
            touches=[],
            value_fields=[],
            gold_answer_in_prefix=seen_answer,
            offsets=None,
        )
    )
    return dict(
        text=text,
        order=order,
        expected=copy.deepcopy(expected),
        token_ids=ids + [eos],
        tokens=tokens,
        first_answer_index=answer_positions[0] if answer_positions else None,
        first_answer_lexical_index=lexical[0] if lexical else None,
        last_answer_index=answer_positions[-1] if answer_positions else None,
        parts=dict(Counter(t["part"] for t in tokens)),
    )


def specification(prefix, ref, eos):
    roles = {
        "answer": "content",
        "steps": "content",
        "format": "format",
        "mixed": "unclassified",
        "stop": "stop",
    }
    return audit.ReadoutSpec(
        tuple(prefix), tuple(ref["token_ids"]), tuple(roles[t["part"]] for t in ref["tokens"]), eos
    )


def summarize_fixed(trace, ref):
    # Reuse the engine's complete causal-layout, arithmetic and hash checks.
    audit.compare_fixed(trace, trace)
    ex.require(trace["spec"]["continuation"] == ref["token_ids"], "Reference token identity")
    ex.require(len(trace["rows"]) == len(ref["tokens"]), "Complete annotated denominator")
    buckets = {part: dict(tokens=0, nll_sum=0.0) for part in PARTS}
    steps = {
        name: dict(tokens=0, nll_sum=0.0) for name in ("before_gold_answer", "after_gold_answer")
    }
    total = 0.0
    for row, tag in zip(trace["rows"], ref["tokens"], strict=True):
        loss = -row["target"]["logprob"]
        total += loss
        buckets[tag["part"]]["tokens"] += 1
        buckets[tag["part"]]["nll_sum"] += loss
        if "steps" in tag["touches"]:
            name = "after_gold_answer" if tag["gold_answer_in_prefix"] else "before_gold_answer"
            steps[name]["tokens"] += 1
            steps[name]["nll_sum"] += loss
    first, last = ref["first_answer_index"], ref["last_answer_index"]
    return dict(
        tokens=len(trace["rows"]),
        nll_sum=total,
        parts=buckets,
        step_bearing_tokens_by_assistance=steps,
        first_answer=None
        if first is None
        else dict(index=first, annotation=ref["tokens"][first], observation=trace["rows"][first]),
        first_answer_lexical_index=ref["first_answer_lexical_index"],
        answer_prefix_logprob=None
        if last is None
        else sum(row["target"]["logprob"] for row in trace["rows"][: last + 1]),
        answer_prefix_scope="Includes formatting and any prior field; not answer accuracy",
    )


def cases(tokenizer, selection, *, memory_cap=128, query_cap=1024, generation_cap=128):
    """No target tokens are appended to the unassisted generation prefix."""
    rows = selection["rows"]
    affected = {(r["group_id"], r["side"]): r for r in rows if r["mode"] == "affected"}
    output = []
    for row in rows:
        refs = [dict(id="own_answer_first", **reference(tokenizer, row["oracle"], "answer_first"))]
        if "steps" in row["oracle"]:
            refs.append(
                dict(id="own_steps_first", **reference(tokenizer, row["oracle"], "steps_first"))
            )
        if row["mode"] == "affected":
            donor = affected[row["group_id"], 1 - row["side"]]
            refs.append(
                dict(
                    id="donor_answer_first", **reference(tokenizer, donor["oracle"], "answer_first")
                )
            )
        for route in bank.ROUTES:
            text = row["query"]
            if route == "inline" and row["memory"]:
                text = row["memory"] + "\n\n" + text
            prefix = ev.encode_chat(tokenizer, text)
            memory = (
                tokenizer.encode(row["memory"], add_special_tokens=False)
                if (route == "workspace" and row["memory"])
                else []
            )
            ex.require(
                len(memory) <= memory_cap
                and len(prefix) + max(generation_cap, *(len(r["token_ids"]) for r in refs))
                <= query_cap,
                "Qualified bounds; no silent truncation",
            )
            output.append(
                dict(
                    id=f"{row['row_id']}/{route}",
                    row_id=row["row_id"],
                    group_id=row["group_id"],
                    family=row["family"],
                    side=row["side"],
                    mode=row["mode"],
                    aliases=row["aliases"],
                    route=route,
                    prefix_ids=prefix,
                    memory_ids=memory,
                    references=refs,
                    expected=row["oracle"],
                    source_row_sha256=ex.plan_hash(row),
                    input_information_sha256=ex.plan_hash([row["memory"], row["query"]]),
                )
            )
    return output


def score_generation(text, expected):
    """Keep the existing strict semantic/step scorer and record natural key order."""
    result = bank.score(text, expected)
    key_order = None
    if result["parsed"]:
        key_order = list(json.loads(text))
    return dict(
        **result,
        steps_applicable="steps" in expected,
        key_order=key_order,
        reference_assistance=False,
        response_postprocessed=False,
    )
