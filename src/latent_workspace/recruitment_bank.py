"""Executable, train-independent tasks for a controlled native input-route FT.

Supplied records are external information M, never newly computed latent S.
Both training arms receive identical records/targets, differing only in route.
No benchmark output, teacher generation, exposed mistake or model score enters
the generator. Whole source groups (twins, questions and controls) stay together.
"""

from __future__ import annotations

import copy
import json
import random
import re
from collections import Counter

from . import execution as ex
from .v22_data import rank

FAMILIES = ("arithmetic", "register_trace", "stable_filter")
MODES = ("affected", "unaffected", "absent", "unrelated")
ROUTES = ("inline", "workspace")
UNKNOWN = {"answer": None}


def oracle(family, record, question):
    """Bounded typed operations, no eval/exec and no external code execution."""
    if record is None:
        return copy.deepcopy(UNKNOWN)
    if family == "arithmetic":
        a, b, c, d, e = (record[k] for k in "abcde")
        return (
            dict(steps=[a + b, (a + b) * c], answer=(a + b) * c)
            if question == "target"
            else dict(steps=[d - e], answer=d - e)
        )
    if family == "register_trace":
        register = "x" if question == "target" else "y"
        value = record[register]
        trace = []
        for name, op, operand in record["operations"]:
            if name == register:
                ex.require(op in ("add", "mul"), "Finite operation vocabulary")
                value = value + operand if op == "add" else value * operand
                trace.append(value)
        return dict(steps=trace, answer=value)
    ex.require(family == "stable_filter", "Known family")
    if question == "control":
        return dict(steps=[record["items"][0][0]], answer=record["items"][0][0])
    result = [name for name, score in record["items"] if score >= record["cutoff"]]
    return dict(steps=result, answer=result)


def independently_check(family, record, question, answer):
    """A second computation checks each generated non-missing reference."""
    if family == "arithmetic":
        # Interpreter route is separate from the direct arithmetic formula.
        steps = [("add", record["b"]), ("mul", record["c"])]
        value = record["a"]
        if question == "control":
            value, steps = record["d"], [("add", -record["e"])]
        trace = []
        for op, other in steps:
            value = sum((value, other)) if op == "add" else value * other
            trace.append(value)
        expected = dict(steps=trace, answer=value)
    elif family == "register_trace":
        # Formula checks the fixed program; do not use the interpreter above.
        xadd, xmul, yadd = (op[2] for op in record["operations"])
        expected = (
            dict(
                steps=[record["x"] + xadd, (record["x"] + xadd) * xmul],
                answer=(record["x"] + xadd) * xmul,
            )
            if question == "target"
            else dict(steps=[record["y"] + yadd], answer=record["y"] + yadd)
        )
    else:
        retained = []
        for index in range(len(record["items"])):
            name, score = record["items"][index]
            if not score < record["cutoff"]:
                retained.append(name)
        expected = (
            dict(steps=retained, answer=retained)
            if question == "target"
            else dict(steps=[record["items"][0][0]], answer=record["items"][0][0])
        )
    ex.require(expected == answer, "Independent reference computation")


def group_rows(group, family, split, seed):
    rng = random.Random(f"{seed}:{group}")
    if family == "arithmetic":
        record = dict(zip("abcde", [rng.randint(2, 60) for _ in range(5)], strict=True))
        record["c"] = rng.randint(2, 9)
        twin = {**record, "a": record["a"] + 1}
        questions = {
            "target": "Compute (a + b) * c. Steps are the sum, then the product.",
            "control": "Compute d - e. Steps contain that difference.",
        }
    elif family == "register_trace":
        record = dict(
            x=rng.randint(2, 60),
            y=rng.randint(2, 60),
            operations=[
                ["x", "add", rng.randint(2, 20)],
                ["x", "mul", rng.randint(2, 9)],
                ["y", "add", rng.randint(2, 20)],
            ],
        )
        twin = {**record, "x": record["x"] + 1}
        questions = {
            q: f"Execute the operations in order. Steps contain each new value of {r}; "
            f"answer is final {r}."
            for q, r in (("target", "x"), ("control", "y"))
        }
    else:
        ex.require(family == "stable_filter", "Known family")
        codes = ["".join(rng.choices("ABCDEFGHJKLMNPQRSTUVWXYZ", k=5)) for _ in range(4)]
        ex.require(len(set(codes)) == 4, "Unique copy codes")
        record = dict(
            items=list(zip(codes, [rng.randint(0, 12) for _ in codes], strict=True)), cutoff=6
        )
        record["items"] = [list(x) for x in record["items"]]
        twin = copy.deepcopy(record)
        twin["items"][1][1] = 5 if record["items"][1][1] >= 6 else 6
        questions = {
            "target": "Keep codes with score >= cutoff in input order. Steps and answer "
            "are both the list of kept codes.",
            "control": "Copy the first code exactly. Steps contain that code; answer is the code.",
        }
    rows = []
    # A short group identifier keeps missing-record prompts distinct across splits.
    identifier = ex.plan_hash(group)[:10]
    for side, facts in enumerate((record, twin)):
        for mode in MODES:
            question = "control" if mode == "unaffected" else "target"
            present = mode in ("affected", "unaffected")
            answer = oracle(family, facts if present else None, question)
            if present:
                independently_check(family, facts, question, answer)
            text = (
                ""
                if mode == "absent"
                else ex.canonical(
                    {"record": identifier, "data": facts}
                    if present
                    else {"record": "unrelated-" + identifier, "data": {"z": 0}}
                )
            )
            query = (
                f"Use record {identifier}. {questions[question]} Return only a JSON object "
                'with keys "steps" and "answer". If the record is missing, return '
                '{"answer":null}.'
            )
            rows.append(
                dict(
                    row_id=f"{group}/s{side}/{mode}",
                    group_id=group,
                    split=split,
                    family=family,
                    role="reasoning",
                    side=side,
                    mode=mode,
                    memory=text,
                    query=query,
                    answer=ex.canonical(answer),
                    oracle=answer,
                    semantic_record=facts,
                    question=question,
                    verification="TWO_EXECUTABLE_CHECKS",
                )
            )
    return rows


def build(plan):
    ex.require(plan["schema"] == "ltws-recruitment-bank-v1", "Bank schema")
    ex.require(plan["families"] == list(FAMILIES), "Fixed families")
    ex.require(re.fullmatch(r"recruit-[0-9]{8}", plan["namespace"]), "Fresh namespace")
    ex.require(set(plan["groups_per_family"]) == {"train", "dev", "confirmation"}, "Splits")
    rows = []
    for family in FAMILIES:
        for split, count in plan["groups_per_family"].items():
            ex.require(type(count) is int and count > 0, "Finite group count")
            for i in range(count):
                group = f"{plan['namespace']}-{family}-{split}-{i:04d}"
                rows.extend(group_rows(group, family, split, plan["seed"]))
    audit(rows)
    return rows


def audit(rows):
    groups, content, semantics, cells = {}, {}, {}, {}
    for row in rows:
        g, split = row["group_id"], row["split"]
        present = row["mode"] in ("affected", "unaffected")
        expected = oracle(
            row["family"], row["semantic_record"] if present else None, row["question"]
        )
        ex.require(
            row["oracle"] == expected and row["answer"] == ex.canonical(expected), "Reference drift"
        )
        if present:
            independently_check(row["family"], row["semantic_record"], row["question"], expected)
        ex.require(groups.setdefault(g, split) == split, "Group leakage")
        sig = ex.plan_hash([row["memory"], row["query"]])
        ex.require(content.setdefault(sig, g) == g, "Cross-group prompt duplication")
        if row["side"] == 0 and row["mode"] == "affected":
            sig = ex.plan_hash([row["family"], row["semantic_record"]])
            ex.require(semantics.setdefault(sig, g) == g, "Cross-group semantic duplicate")
        key = (row["side"], row["mode"])
        ex.require(key not in cells.setdefault(g, {}), "Duplicate cell")
        cells[g][key] = row
    for group in cells.values():
        ex.require(len(group) == 8, "Complete twin/control group")
        for mode in MODES:
            a, b = group[0, mode], group[1, mode]
            ex.require(a["query"] == b["query"], "Twin question parity")
            ex.require((a["answer"] != b["answer"]) == (mode == "affected"), "Twin direction")
    return dict(
        groups=len(groups), rows=len(rows), rows_by_split=dict(Counter(r["split"] for r in rows))
    )


def project(raw, tokenizer, route):
    """Route-neutral targets. Confirmation is never projected for training."""
    ex.require(route in ROUTES, "Training route")
    rows, seen = [], {}
    for item in sorted(raw, key=lambda r: r["row_id"]):
        if item["split"] not in ("train", "dev"):
            continue
        text = item["query"]
        if route == "inline" and item["memory"]:
            text = item["memory"] + "\n\n" + text
        prefix = list(
            tokenizer.apply_chat_template(
                [{"role": "user", "content": text}],
                tokenize=True,
                add_generation_prompt=True,
                return_dict=False,
            )
        )
        target = tokenizer.encode(" " + item["answer"], add_special_tokens=False) + [
            tokenizer.eos_token_id
        ]
        memory = (
            tokenizer.encode(item["memory"], add_special_tokens=False)
            if item["memory"] and route == "workspace"
            else []
        )
        # Deduplicate using the semantic source, so alias selection is identical across routes.
        signature = ex.plan_hash([item["group_id"], item["memory"], item["query"], item["answer"]])
        if signature in seen:
            seen[signature]["duplicate_aliases"].append(item["row_id"])
            continue
        row = dict(
            key=item["row_id"],
            group_id=item["group_id"],
            split=item["split"],
            role=item["role"],
            language="en",
            family=item["family"],
            side=item["side"],
            mode=item["mode"],
            memory_ids=memory,
            input_ids=prefix + target,
            labels=[-100] * len(prefix) + target,
            supervised_tokens=len(target),
            target_ids=target,
            route=route,
            source_information_sha256=ex.plan_hash([item["memory"], item["query"], item["answer"]]),
            parent_record_sha256=ex.plan_hash(item),
            duplicate_aliases=[],
        )
        ex.require(
            len(memory) <= 128 and len(row["input_ids"]) <= 1024, "Qualified lengths; no truncation"
        )
        seen[signature] = row
        rows.append(row)
    return rows


def match_routes(left, right):
    ex.require(len(left) == len(right), "Route count")
    for a, b in zip(left, right, strict=True):
        for field in (
            "key",
            "group_id",
            "split",
            "role",
            "target_ids",
            "supervised_tokens",
            "source_information_sha256",
            "parent_record_sha256",
            "duplicate_aliases",
        ):
            ex.require(a[field] == b[field], f"Route-independent {field}")
        ex.require(
            not a["memory_ids"] and a["route"] == "inline" and b["route"] == "workspace",
            "Route identity",
        )


def schedule(rows, plan):
    """Whole-row token-fair schedule reused identically by both route arms."""
    shares = plan["target_supervised_token_shares"]
    ex.require(set(shares) == {"world", "reasoning", "instruction", "prose", "code"}, "Five roles")
    ex.require(
        all(type(v) in (int, float) and v > 0 for v in shares.values())
        and abs(sum(shares.values()) - 1) < 1e-12,
        "Token shares",
    )
    pools = {
        role: sorted(
            (r for r in rows if r["split"] == "train" and r["role"] == role),
            key=lambda r: rank(plan["seed"], r["key"]),
        )
        for role in shares
    }
    ex.require(all(pools.values()), "Every training pool nonempty")
    used, cursors, windows = Counter(), Counter(), []
    for _ in range(plan["training_updates"]):
        keys, tokens = [], 0
        while tokens < plan["minimum_window_supervised_tokens"]:
            role = min(shares, key=lambda r: (used[r] / shares[r], rank(plan["seed"], r)))
            row = pools[role][cursors[role] % len(pools[role])]
            ex.require(row["key"] not in keys, "No repeated row in one window")
            keys.append(row["key"])
            cursors[role] += 1
            used[role] += row["supervised_tokens"]
            tokens += row["supervised_tokens"]
            ex.require(len(keys) <= plan["maximum_window_rows"], "Window bound")
        windows.append(keys)
    return windows


def score(text, expected):
    """Wrong/unparsed stays wrong, never an excluded invalidity or length reward."""

    def object_pairs(pairs):
        ex.require(len({k for k, _ in pairs}) == len(pairs), "Duplicate JSON field")
        return dict(pairs)

    def invalid_constant(value):
        raise ValueError(f"Non-finite JSON constant: {value}")

    try:
        actual = json.loads(text, object_pairs_hook=object_pairs, parse_constant=invalid_constant)
        ex.canonical(actual)
    except (ValueError, TypeError):
        return dict(parsed=False, content_correct=False, steps_correct=False, exact=False)
    is_object = isinstance(actual, dict)
    # JSON booleans must not pass as integer answers (True == 1 in Python).
    same = lambda a, b: ex.canonical(a) == ex.canonical(b)  # noqa: E731
    return dict(
        parsed=is_object,
        content_correct=is_object
        and "answer" in actual
        and same(actual["answer"], expected["answer"]),
        steps_correct=is_object
        and expected != UNKNOWN
        and "steps" in actual
        and same(actual["steps"], expected["steps"]),
        exact=same(actual, expected),
    )
