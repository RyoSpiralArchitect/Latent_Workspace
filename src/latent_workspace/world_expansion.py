"""Additive oracle worlds, not a rewrite of the original held-out protocol.

The former two-hop OOD *family* is explicitly promoted, using new identities.
Its old groups stay excluded. Three-hop owner-location composition is reserved
wholesale. No model, benchmark gold or diagnostic mistake is a generator input.
"""

from __future__ import annotations

import copy
import random
import re
from collections import Counter

from . import execution as ex
from . import world_bank as wb


def names_in(value):
    return set(re.findall(r"\bN[a-z]{9}\b", ex.canonical(value)))


def solve(facts, query):
    if query["op"] != "owner_chain_location":
        return wb.solve(facts, query)
    current, evidence = query["subject"], []
    for relation in ("owned_by", "owned_by", "at"):
        matches = [f for f in facts if f["relation"] == relation and f["subject"] == current]
        if len(matches) != 1:
            return wb.UNKNOWN, []
        current = matches[0]["value"]
        evidence.append(matches[0]["id"])
    return current, evidence


def render_query(query):
    if query["op"] == "owner_chain_location":
        return wb.POLICY + f"Where is the owner of the owner of {query['subject']}?"
    return wb.render_query(query)


def group_rows(group, family, split, seed, style, distractors=2):
    # First create facts and questions; renaming is independent of twin side.
    if family == "owner_chain_location":
        n = [wb._entity(group, i) for i in range(8)]
        original = [
            dict(id=f"f{i}", relation=r, subject=s, value=v)
            for i, (r, s, v) in enumerate(
                [
                    ("owned_by", n[0], n[1]),
                    ("owned_by", n[1], n[2]),
                    ("at", n[2], n[3]),
                    ("owned_by", n[4], n[5]),
                    ("owned_by", n[5], n[6]),
                    ("at", n[6], n[7]),
                ]
            )
        ]
        twin = copy.deepcopy(original)
        twin[2]["value"] = wb._entity(group, 8)
        target = dict(op=family, subject=n[0])
        control = dict(op=family, subject=n[4])
    else:
        original, twin, target, control = wb.make_world(group, family, seed)
    for i in range(distractors):
        fact = dict(
            id=f"d{i}",
            relation="at",
            subject=wb._entity(group, 20 + i * 2),
            value=wb._entity(group, 21 + i * 2),
        )
        original.append(fact)
        twin.append(copy.deepcopy(fact))
    unrelated = [
        dict(id="u0", relation="at", subject=wb._entity(group, 50), value=wb._entity(group, 51))
    ]
    values = [original, twin, target, control, unrelated]
    if style == "shared_prefix":
        symbols = sorted(names_in(values))
        rng = random.Random(f"{seed}:{group}:names")
        prefix = wb._entity(group, 90)[:9]  # N + eight letters; last letter distinguishes.
        suffixes = rng.sample("abcdefghijklmnopqrstuvwxyz", len(symbols))
        mapping = {n: prefix + s for n, s in zip(symbols, suffixes, strict=True)}

        def rename(value):
            if isinstance(value, str):
                return mapping.get(value, value)
            if isinstance(value, list):
                return [rename(v) for v in value]
            if isinstance(value, dict):
                return {k: rename(v) for k, v in value.items()}
            return value

        original, twin, target, control, unrelated = rename(values)
    else:
        ex.require(style == "independent", "Identifier style")
    rng = random.Random(f"{seed}:{group}:order")
    rng.shuffle(original)
    order = {f["id"]: i for i, f in enumerate(original)}
    twin.sort(key=lambda f: order[f["id"]])
    rows = []
    for side, world in enumerate((original, twin)):
        for mode in wb.MODES:
            query = control if mode == "unaffected" else target
            facts = [] if mode == "absent" else unrelated if mode == "unrelated" else world
            answer, evidence = solve(facts, query)
            memory = wb.render_memory(facts)
            rows.append(
                dict(
                    row_id=f"{group}/s{side}/{mode}",
                    group_id=group,
                    world_id=f"{group}/s{side}",
                    family=family,
                    split=split,
                    side=side,
                    mode=mode,
                    identifier_style=style,
                    facts=copy.deepcopy(facts),
                    query_spec=copy.deepcopy(query),
                    memory=memory,
                    query=render_query(query),
                    answer=answer + ".",
                    answer_value=answer,
                    evidence_ids=evidence,
                    memory_sha256=ex.hashlib.sha256(memory.encode()).hexdigest(),
                    verification="EXECUTABLE_ORACLE",
                    training_selection="UNSET",
                )
            )
    return rows


def build(plan):
    ex.require(plan["schema"] == "ltws-world-expansion-v1", "Expansion schema")
    ex.require(plan["families"] == [*wb.FAMILIES, "linked_location"], "Explicit family promotion")
    ex.require(plan["heldout_family"] == "owner_chain_location", "Three-hop held-out family")
    ex.require(plan["identifier_styles"] == ["independent", "shared_prefix"], "Identifier axes")
    ex.require(set(plan["groups_per_family"]) == {"train", "dev", "confirmation"}, "Splits")
    ex.require(plan["distractor_facts"] == 2, "Two unrelated distractor facts")
    ex.require(re.fullmatch(r"wb02-[0-9]{8}", plan["namespace"]), "New namespace")
    rows = []
    for family in [*plan["families"], plan["heldout_family"]]:
        splits = (
            {"ood": plan["heldout_groups"]}
            if family == plan["heldout_family"]
            else plan["groups_per_family"]
        )
        for split, count in splits.items():
            ex.require(type(count) is int and count > 0 and count % 2 == 0, "Balanced group count")
            for i in range(count):
                group = f"{plan['namespace']}-{family}-{split}-{i:04d}"
                rows.extend(
                    group_rows(
                        group,
                        family,
                        split,
                        plan["seed"],
                        plan["identifier_styles"][i % 2],
                        plan["distractor_facts"],
                    )
                )
    return rows


def audit(rows, prior_rows, plan):
    # Regeneration verifies the entire selection and all metadata, not just answers.
    ex.require(rows == build(plan), "Expansion regeneration mismatch")
    ids, groups, texts, names = set(), {}, {}, {}
    siblings = {}
    prior_groups = {r["group_id"] for r in prior_rows}
    prior_names = names_in(prior_rows)
    prior_texts = {ex.plan_hash([r["memory"], r["query"]]) for r in prior_rows}
    for row in rows:
        ex.require(row["row_id"] not in ids, "Duplicate ID")
        ids.add(row["row_id"])
        group, split = row["group_id"], row["split"]
        ex.require(group not in prior_groups, "Historical group overlap")
        ex.require(groups.setdefault(group, split) == split, "Group split leakage")
        signature = ex.plan_hash([row["memory"], row["query"]])
        ex.require(signature not in prior_texts, "Historical text overlap")
        ex.require(texts.setdefault(signature, (group, split)) == (group, split), "Text leakage")
        for name in names_in([row["facts"], row["query_spec"]]):
            ex.require(name not in prior_names, "Historical identifier overlap")
            ex.require(names.setdefault(name, group) == group, "Cross-group identifier overlap")
        ex.require(
            solve(row["facts"], row["query_spec"]) == (row["answer_value"], row["evidence_ids"]),
            "Oracle",
        )
        ex.require((row["family"] == plan["heldout_family"]) == (split == "ood"), "OOD leak")
        siblings.setdefault(group, {})[row["side"], row["mode"]] = row
    for cells in siblings.values():
        ex.require(len(cells) == 8, "Incomplete group")
        for mode in wb.MODES:
            a, b = cells[0, mode], cells[1, mode]
            ex.require(a["query"] == b["query"], "Twin query mismatch")
            ex.require((a["answer"] != b["answer"]) == (mode == "affected"), "Twin direction")
            if mode in ("absent", "unrelated"):
                ex.require(a["answer_value"] == wb.UNKNOWN, "Boundary answer")
        for side in (0, 1):
            ex.require(
                cells[side, "affected"]["memory"] == cells[side, "unaffected"]["memory"],
                "Same-memory multiple questions",
            )
    return dict(
        status="ORACLE_EXPANSION_VERIFIED_NOT_TRAINED",
        rows=len(rows),
        groups=len(groups),
        rows_by_split=dict(Counter(r["split"] for r in rows)),
        rows_by_family=dict(Counter(r["family"] for r in rows)),
        rows_by_style=dict(Counter(r["identifier_style"] for r in rows)),
        evidence_length_counts=dict(
            sorted(Counter(str(len(r["evidence_ids"])) for r in rows).items())
        ),
        unique_sequences=len(texts),
        duplicate_control_rows=len(rows) - len(texts),
        historical_groups_excluded=len(prior_groups),
        historical_group_text_identifier_overlap=0,
        cross_split_group_text_identifier_overlap=0,
        promoted_former_ood_family="linked_location",
        new_ood_family="owner_chain_location",
        model_evaluations=0,
        teacher_calls=0,
        training_recipe="UNSET",
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
    )
