"""Deterministic, query-deferred worlds and a deliberately limited preservation starter.

No models, network, old evaluation artifacts or hidden-feature caches are used.
Semantic solvers consume visible facts; generated free text is NEVER certified
by merely repeating the supplied answer/evidence fields.
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
from collections import Counter, deque

from . import execution as ex

FAMILIES = ("location", "ownership", "order", "event_order", "inventory", "revision")
MODES = ("affected", "unaffected", "absent", "unrelated")
UNKNOWN = "Not specified"
POLICY = (
    "Use only the supplied memory facts. If they do not determine the answer, "
    "reply 'Not specified'. "
)


def _fact(i, relation, subject, value, **extra):
    return dict(id=f"f{i}", relation=relation, subject=subject, value=value, **extra)


def _entity(group, index):
    # Disjoint nonce vocabularies across groups, without putting split/answer
    # labels in the text. Names are not ordinary-world facts a host can recall.
    digest = hashlib.sha256(f"{group}:{index}".encode()).digest()
    return "N" + "".join(chr(97 + byte % 26) for byte in digest[:9])


def make_world(group, family, seed):
    rng = random.Random(f"{seed}:{group}")
    names = [_entity(group, i) for i in range(12)]
    a, b, c, d, e, x, y, z, *_ = names
    if family == "location":
        facts = [_fact(0, "at", a, x), _fact(1, "at", b, y)]
        target, control = (
            dict(op="lookup", relation="at", subject=a),
            dict(op="lookup", relation="at", subject=b),
        )
        twin = copy.deepcopy(facts)
        twin[0]["value"] = z
    elif family == "ownership":
        facts = [_fact(0, "owned_by", x, a), _fact(1, "owned_by", y, b)]
        target, control = (
            dict(op="lookup", relation="owned_by", subject=x),
            dict(op="lookup", relation="owned_by", subject=y),
        )
        twin = copy.deepcopy(facts)
        twin[0]["value"] = c
    elif family == "order":
        order = [a, b, c, d, e]
        facts = [_fact(i, "above", u, v) for i, (u, v) in enumerate(zip(order, order[1:]))]
        swapped = [c, b, a, d, e]
        twin = [_fact(i, "above", u, v) for i, (u, v) in enumerate(zip(swapped, swapped[1:]))]
        target, control = dict(op="higher", left=a, right=c), dict(op="higher", left=d, right=e)
    elif family == "event_order":
        times = sorted(rng.sample(range(1, 29), 4))
        facts = [_fact(i, "day", n, t) for i, (n, t) in enumerate(zip([a, b, c, d], times))]
        twin = copy.deepcopy(facts)
        twin[0]["value"], twin[1]["value"] = twin[1]["value"], twin[0]["value"]
        target, control = dict(op="earlier", left=a, right=b), dict(op="earlier", left=c, right=d)
    elif family == "inventory":
        n, added = rng.randrange(3, 40), rng.randrange(1, 12)
        facts = [
            _fact(0, "initial", a, n),
            _fact(1, "received", a, added),
            _fact(2, "initial", b, 17),
            _fact(3, "received", b, 2),
        ]
        twin = copy.deepcopy(facts)
        twin[0]["value"] += 3
        target, control = dict(op="total", subject=a), dict(op="total", subject=b)
    elif family == "revision":
        facts = [
            _fact(0, "at_version", a, x, version=1),
            _fact(1, "at_version", a, y, version=2),
            _fact(2, "at_version", b, z, version=1),
        ]
        twin = copy.deepcopy(facts)
        twin[1]["value"] = e
        target, control = dict(op="latest", subject=a), dict(op="latest", subject=b)
    elif family == "linked_location":
        # This composition family is held out wholesale, not merely renamed.
        facts = [
            _fact(0, "owned_by", x, a),
            _fact(1, "at", a, y),
            _fact(2, "owned_by", z, b),
            _fact(3, "at", b, d),
        ]
        twin = copy.deepcopy(facts)
        twin[1]["value"] = e
        target, control = dict(op="owner_location", subject=x), dict(op="owner_location", subject=z)
    else:
        raise ValueError(f"Unknown world family: {family}")
    # Rendering order is independent of target position and twin side.
    rng.shuffle(facts)
    positions = {f["id"]: i for i, f in enumerate(facts)}
    twin.sort(key=lambda f: positions[f["id"]])
    return facts, twin, target, control


def solve(facts, query):
    """Independent executable oracle over *visible* atoms. No cached answer field."""

    def select(relation, subject):
        return [f for f in facts if f["relation"] == relation and f["subject"] == subject]

    def single(relation, subject):
        matches = select(relation, subject)
        return matches[0] if len(matches) == 1 else None

    op = query["op"]
    if op == "lookup":
        fact = single(query["relation"], query["subject"])
        return (str(fact["value"]), [fact["id"]]) if fact else (UNKNOWN, [])
    if op == "latest":
        matches = select("at_version", query["subject"])
        if matches:
            latest = max(f["version"] for f in matches)
            matches = [f for f in matches if f["version"] == latest]
            if len(matches) == 1:
                return str(matches[0]["value"]), [matches[0]["id"]]
        return UNKNOWN, []
    if op == "total":
        initial, received = (
            single("initial", query["subject"]),
            single("received", query["subject"]),
        )
        if initial and received:
            return str(initial["value"] + received["value"]), [initial["id"], received["id"]]
        return UNKNOWN, []
    if op == "earlier":
        left, right = single("day", query["left"]), single("day", query["right"])
        if left and right and left["value"] != right["value"]:
            winner = left if left["value"] < right["value"] else right
            return winner["subject"], [left["id"], right["id"]]
        return UNKNOWN, []
    if op == "owner_location":
        owner = single("owned_by", query["subject"])
        location = single("at", owner["value"]) if owner else None
        if owner and location:
            return str(location["value"]), [owner["id"], location["id"]]
        return UNKNOWN, []
    if op == "higher":

        def path(start, end):
            queue, seen = deque([(start, [])]), {start}
            while queue:
                node, evidence = queue.popleft()
                if node == end:
                    return evidence
                for f in select("above", node):
                    if f["value"] not in seen:
                        seen.add(f["value"])
                        queue.append((f["value"], [*evidence, f["id"]]))
            return None

        forward, reverse = path(query["left"], query["right"]), path(query["right"], query["left"])
        if forward is not None and reverse is None:
            return query["left"], forward
        if reverse is not None and forward is None:
            return query["right"], reverse
        return UNKNOWN, []
    raise ValueError(f"Unknown query operation: {op}")


def render_fact(fact):
    subject, value = fact["subject"], fact["value"]
    relation = fact["relation"]
    if relation == "at_version":
        return f"Version {fact['version']}: {subject} is at {value}."
    templates = {
        "at": "{s} is at {v}.",
        "owned_by": "{s} is owned by {v}.",
        "above": "{s} is ranked above {v}.",
        "day": "Event {s} occurs on day {v}.",
        "initial": "{s} initially has {v} tokens.",
        "received": "{s} receives {v} more tokens; no tokens are removed.",
    }
    return templates[relation].format(s=subject, v=value)


def render_memory(facts):
    return "\n".join(render_fact(f) for f in facts)


def render_query(query):
    op = query["op"]
    if op == "lookup":
        body = (
            f"Where is {query['subject']}?"
            if query["relation"] == "at"
            else f"Who owns {query['subject']}?"
        )
    elif op == "higher":
        body = f"Which is ranked higher, {query['left']} or {query['right']}?"
    elif op == "earlier":
        body = f"Which event occurs earlier, {query['left']} or {query['right']}?"
    elif op == "total":
        body = f"How many tokens does {query['subject']} have after receiving the tokens?"
    elif op == "latest":
        body = f"At the greatest recorded version number, where is {query['subject']}?"
    elif op == "owner_location":
        body = f"Where is the owner of {query['subject']}?"
    else:
        raise ValueError("Unknown query")
    return POLICY + body


def group_rows(group, family, split, seed):
    original, twin, target, control = make_world(group, family, seed)
    rows = []
    for side, world in enumerate((original, twin)):
        for mode in MODES:
            query = control if mode == "unaffected" else target
            facts = [] if mode == "absent" else world
            if mode == "unrelated":
                facts = [_fact(0, "at", _entity(group, 50), _entity(group, 51))]
            value, evidence = solve(facts, query)
            memory = render_memory(facts)
            rows.append(
                dict(
                    row_id=f"{group}/s{side}/{mode}",
                    group_id=group,
                    world_id=f"{group}/s{side}",
                    family=family,
                    split=split,
                    side=side,
                    mode=mode,
                    facts=copy.deepcopy(facts),
                    query_spec=copy.deepcopy(query),
                    memory=memory,
                    query=render_query(query),
                    answer=value + ".",
                    answer_value=value,
                    evidence_ids=evidence,
                    memory_sha256=hashlib.sha256(memory.encode()).hexdigest(),
                    verification="EXECUTABLE_ORACLE",
                    training_selection="UNSET",
                )
            )
    return rows


def instruction_seeds(seed, count=128):
    """Original, limited instruction seeds; no external benchmark/dataset import."""
    ex.require(count == 128, "Fixed starter size")
    rng, rows = random.Random(seed), []
    translations = [
        ("ありがとう。", "Thank you."),
        ("おはようございます。", "Good morning."),
        ("また明日。", "See you tomorrow."),
        ("少し待ってください。", "Please wait a moment."),
        ("おやすみなさい。", "Good night."),
        ("すみません。", "Excuse me."),
        ("どうぞ座ってください。", "Please sit down."),
        ("お元気ですか。", "How are you?"),
    ]
    for index in range(count):
        family, i = divmod(index, 16)
        a, b = rng.randrange(10, 90), rng.randrange(2, 10)
        verification = "EXECUTABLE_TEMPLATE"
        if family == 0:
            task, query, answer = (
                "arithmetic",
                f"Calculate {a} + {b}. Return only the integer.",
                str(a + b),
            )
        elif family == 1:
            values = rng.sample(range(1, 100), 5)
            task, query, answer = (
                "sorting",
                f"Sort {values} ascending. Return a JSON array.",
                json.dumps(sorted(values)),
            )
        elif family == 2:
            obj = {"label": f"parcel-{i}", "count": a, "colour": "blue"}
            task, query, answer = (
                "extraction",
                f"From this JSON, return only count: {json.dumps(obj)}",
                str(a),
            )
        elif family == 3:
            task, query, answer = (
                "formatting",
                f"Return a JSON object with x={a} and y={b}; no other keys.",
                json.dumps({"x": a, "y": b}),
            )
        elif family == 4:
            source, translated = translations[i % 8]
            if i >= 8:
                source, translated = translated, source
            task, query, answer = (
                "translation",
                f"Translate into {'Japanese' if i >= 8 else 'English'}: {source}",
                translated,
            )
            verification = "ASSISTANT_AUTHORED_REFERENCE_NOT_UNIQUE_GOLD"
        elif family == 5:
            task, query, answer = (
                "code",
                f"Write only Python code defining add_{b}_{i}(x) that returns x plus {b}.",
                f"def add_{b}_{i}(x):\n    return x + {b}",
            )
        elif family == 6:
            text = f"Delivery {i} arrived on day {b}. It contained {a} notebooks."
            task, query, answer = (
                "reading",
                f"{text}\nHow many notebooks? Return only the integer.",
                str(a),
            )
        else:
            task = "polite_rewrite"
            # Use valid hours; names/numbers are controlled, quality is not a theorem.
            query = (
                f"Politely ask a colleague to move meeting {i} "
                "from 10:00 to 11:00. Use one sentence."
            )
            answer = f"Could we please move meeting {i} from 10:00 to 11:00?"
            verification = "ASSISTANT_AUTHORED_REFERENCE_NOT_UNIQUE_GOLD"
        rows.append(
            dict(
                row_id=f"instruction/{index:03d}",
                split="train",
                family=task,
                memory="",
                query=query,
                answer=answer,
                verification=verification,
                training_selection="UNSET",
            )
        )
    return rows


def build(plan):
    ex.require(plan["families"] == list(FAMILIES), "Fixed family selection")
    ex.require(plan["heldout_family"] == "linked_location", "Fixed held-out composition")
    rows = []
    for family in FAMILIES:
        for split, count in plan["groups_per_family"].items():
            for i in range(count):
                group = f"wb01-{family}-{split}-{i:04d}"
                rows.extend(group_rows(group, family, split, plan["seed"]))
    for i in range(plan["heldout_groups"]):
        group = f"wb01-linked_location-ood-{i:04d}"
        rows.extend(group_rows(group, "linked_location", "ood", plan["seed"]))
    instructions = instruction_seeds(plan["seed"], plan["instruction_seed_rows"])
    return rows, instructions


def audit(rows, instructions):
    ids, groups, content_splits = set(), {}, {}
    for row in rows:
        ex.require(row["row_id"] not in ids, "Duplicate row ID")
        ids.add(row["row_id"])
        ex.require(
            groups.setdefault(row["group_id"], row["split"]) == row["split"], "Group leakage"
        )
        answer, evidence = solve(row["facts"], row["query_spec"])
        ex.require(
            (answer, evidence) == (row["answer_value"], row["evidence_ids"]), "Oracle mismatch"
        )
        ex.require(row["answer"] == answer + ".", "Rendered answer mismatch")
        ex.require(row["memory"] == render_memory(row["facts"]), "Memory mismatch")
        ex.require(row["query"] == render_query(row["query_spec"]), "Query mismatch")
        ex.require(
            row["memory_sha256"] == hashlib.sha256(row["memory"].encode()).hexdigest(),
            "Memory hash mismatch",
        )
        signature = ex.plan_hash([row["memory"], row["query"], row["answer"]])
        ex.require(
            content_splits.setdefault(signature, row["split"]) == row["split"], "Text leakage"
        )
        ex.require(
            (row["family"] == "linked_location") == (row["split"] == "ood"), "Held-out family leak"
        )
    by_group = {}
    for row in rows:
        by_group.setdefault(row["group_id"], {})[(row["side"], row["mode"])] = row
    for siblings in by_group.values():
        ex.require(set(siblings) == {(s, m) for s in (0, 1) for m in MODES}, "Incomplete group")
        for mode in MODES:
            left, right = siblings[0, mode], siblings[1, mode]
            ex.require(left["query"] == right["query"], "Twin queries differ")
            ex.require(
                (left["answer"] != right["answer"]) == (mode == "affected"),
                "Twin direction/control",
            )
            if mode in ("absent", "unrelated"):
                ex.require(
                    left["answer_value"] == right["answer_value"] == UNKNOWN, "Boundary oracle"
                )
    ex.require(
        len({r["row_id"] for r in instructions}) == len(instructions), "Instruction duplicates"
    )
    ex.require(
        all(r["split"] == "train" and r["memory"] == "" for r in instructions), "Instruction scope"
    )
    return dict(
        status="STRUCTURED_WORLD_BANK_VERIFIED_NOT_TRAINED",
        world_groups=len(groups),
        world_variants=2 * len(groups),
        world_rows=len(rows),
        world_rows_by_split=dict(Counter(r["split"] for r in rows)),
        world_rows_by_family=dict(Counter(r["family"] for r in rows)),
        instruction_rows=len(instructions),
        instruction_families=dict(Counter(r["family"] for r in instructions)),
        cross_split_group_overlap=0,
        cross_split_exact_text_overlap=0,
        within_split_duplicate_world_rows=len(rows) - len(content_splits),
        duplicate_policy="Paired control duplicates retained for audit; training sampling UNSET",
        old_evaluation_imports=0,
        non_regression="NOT_ESTABLISHED",
        mixture_weights="UNSET",
    )


def teacher_inputs(rows, instructions, plan):
    chosen = []
    for family in FAMILIES:
        pool = [
            r
            for r in rows
            if r["split"] == "train" and r["family"] == family and r["mode"] == "affected"
        ]
        # Four group pairs per family: both counterfactual sides remain inspectable.
        chosen.extend(
            dict(kind="world", row=r) for r in pool[: plan["teacher_world_rows_per_family"]]
        )
    # Two examples of each of the eight instruction families; no eval inputs.
    selected_instructions = []
    for family in dict.fromkeys(r["family"] for r in instructions):
        selected_instructions.extend([r for r in instructions if r["family"] == family][:2])
    chosen.extend(dict(kind="instruction", row=r) for r in selected_instructions)
    ex.require(len(chosen) == plan["teacher_requests"] == 64, "Exactly 64 teacher requests")
    ex.require(all(v["row"]["split"] == "train" for v in chosen), "No teacher evaluation exposure")
    return chosen


def inspect_candidate(candidate, item):
    """Structural triage ONLY. Human semantic review is required even if all checks pass."""
    errors = []
    expected = {"question", "answer", "answer_value", "evidence_ids"}
    if not isinstance(candidate, dict) or set(candidate) != expected:
        return dict(structural_pass=False, errors=["schema_keys"], training_approved=False)
    for key in ("question", "answer", "answer_value"):
        if not isinstance(candidate[key], str) or len(candidate[key]) > 4000:
            errors.append(f"invalid_{key}")
    evidence = candidate["evidence_ids"]
    if not isinstance(evidence, list) or not all(isinstance(e, str) for e in evidence):
        errors.append("evidence_schema")
    if not candidate["question"] or not candidate["answer"]:
        errors.append("empty_text")
    row = item["row"]
    if item["kind"] == "world":
        if candidate["answer_value"] != row["answer_value"]:
            errors.append("canonical_value_mismatch")
        if evidence != row["evidence_ids"]:
            errors.append("evidence_mismatch")
        if isinstance(candidate["answer"], str) and row["answer_value"] not in candidate["answer"]:
            errors.append("answer_anchor_absent")
    elif candidate["answer_value"] != "" or evidence != []:
        errors.append("instruction_evidence_must_be_empty")
    return dict(
        structural_pass=not errors,
        errors=errors,
        semantic_equivalence="UNREVIEWED",
        training_approved=False,
    )


def compose_teacher_candidate(candidate, item):
    """A new quarantined derivative: the teacher may supply answer prose only.

    Never rewrite the original generation. Canonical memory/query are compiler
    owned, so policy text and paired query equality cannot drift with the donor
    answer. Semantic admission of prose remains a separate, unmet gate.
    """
    checks = inspect_candidate(candidate, item)
    ex.require(checks["structural_pass"], "Cannot compose a structurally invalid candidate")
    original = item["row"]
    ex.require(original["split"] == "train", "No evaluation derivatives")
    return {
        **copy.deepcopy(original),
        "answer": candidate["answer"],
        "verification": "TEACHER_PROSE_SEMANTICS_UNREVIEWED",
        "training_selection": "UNSET",
        "training_approved": False,
        "composition": "canonical_memory_and_query_teacher_answer_only_v1",
        "teacher_question_used": False,
        "source_teacher_candidate_sha256": ex.plan_hash(candidate),
        "canonical_reference_answer": original["answer"],
    }
