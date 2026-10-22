"""Additive English-only projection and frozen complete-row token scheduling.

No model execution and no evaluation-driven selection. Original banks are never
rewritten. The optimizer still uses its existing token-weighted NLL, not a new
role-weighted loss. Requested token shares and realized shares are distinct.
"""

from __future__ import annotations

from collections import Counter

from . import execution as ex


def rank(seed, key):
    return ex.hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()


def validate_row(row, plan):
    ids, labels, memory = row["input_ids"], row["labels"], row["memory_ids"]
    ex.require(row["language"] == "en" and row["split"] in ("train", "dev"), "English train/dev")
    ex.require(row["role"] in plan["target_supervised_token_shares"], "Known role")
    ex.require(
        len(ids) == len(labels) and len(ids) > 1 and labels[0] == -100,
        "Query-only causal mask",
    )
    ex.require(all(type(t) is int and 0 <= t < 32768 for t in [*ids, *memory]), "Token IDs")
    ex.require(all(t == -100 or t == i for t, i in zip(labels, ids)), "Labels equal input")
    ex.require(
        sum(t != -100 for t in labels[1:]) == row["supervised_tokens"] > 0,
        "Supervised denominator",
    )
    ex.require(len(memory) <= plan["maximum_memory_tokens"], "Memory length")
    limit = (
        plan["world_maximum_query_tokens"]
        if row["role"] == "world"
        else plan["maximum_query_tokens"]
    )
    ex.require(len(ids) <= limit, "Query length; no truncation")
    if row["role"] != "world":
        ex.require(not memory, "Preservation must have no memory")


def project(preservation, worlds, tokenizer, plan):
    ex.require(plan["languages"] == ["en"] and not plan["truncation"], "English-only complete rows")
    rows, excluded = [], Counter()
    for item in preservation:
        if item["language"] != "en":
            excluded[f"preservation/{item['language']}/{item['split']}"] += 1
            continue
        ex.require(item["memory"] == [], "Original preservation memory policy")
        rows.append(
            dict(
                key=item["row_id"],
                group_id=item["group_id"],
                split=item["split"],
                role=item["role"],
                language="en",
                memory_ids=[],
                input_ids=item["input_ids"],
                labels=item["labels"],
                supervised_tokens=sum(t != -100 for t in item["labels"][1:]),
                parent_record_sha256=ex.plan_hash(item),
            )
        )
    seen = {}
    for item in sorted(worlds, key=lambda r: r["row_id"]):
        if item["split"] not in ("train", "dev"):
            excluded[f"world/{item['split']}"] += 1
            continue
        ex.require(item["family"] in plan["world_families"], "Held-out world family")
        prompt = list(
            tokenizer.apply_chat_template(
                [{"role": "user", "content": item["query"]}],
                tokenize=True,
                add_generation_prompt=True,
                return_dict=False,
            )
        )
        answer = tokenizer.encode(" " + item["answer"], add_special_tokens=False) + [
            tokenizer.eos_token_id
        ]
        memory = (
            tokenizer.encode(item["memory"], add_special_tokens=False) if item["memory"] else []
        )
        signature = ex.plan_hash([memory, prompt, answer])
        if signature in seen:
            prior = seen[signature]
            ex.require(
                prior["group_id"] == item["group_id"] and prior["split"] == item["split"],
                "Duplicate across groups/splits",
            )
            prior["duplicate_aliases"].append(item["row_id"])
            excluded[f"world/duplicate/{item['split']}"] += 1
            continue
        row = dict(
            key=item["row_id"],
            group_id=item["group_id"],
            split=item["split"],
            role="world",
            family=item["family"],
            mode=item["mode"],
            side=item["side"],
            language="en",
            memory_ids=memory,
            input_ids=prompt + answer,
            labels=[-100] * len(prompt) + answer,
            supervised_tokens=len(answer),
            parent_record_sha256=ex.plan_hash(item),
            duplicate_aliases=[],
        )
        seen[signature] = row
        rows.append(row)
    rows.sort(key=lambda r: r["key"])
    ex.require(len({r["key"] for r in rows}) == len(rows), "Unique keys")
    groups, content = {}, {}
    for row in rows:
        validate_row(row, plan)
        ex.require(
            groups.setdefault(row["group_id"], row["split"]) == row["split"], "Group leakage"
        )
        signature = ex.plan_hash([row["memory_ids"], row["input_ids"], row["labels"]])
        ex.require(signature not in content, "Duplicate projected sequence")
        content[signature] = row["split"]
    return rows, dict(excluded)


def schedule(rows, plan):
    """Weighted fair queue by actual supervised tokens; whole rows, no padding loss."""
    shares = plan["target_supervised_token_shares"]
    ex.require(set(shares) == {"world", "instruction", "prose", "code"}, "Four roles")
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
    ex.require(all(pools.values()), "Nonempty training pools")
    used, cursors, windows = Counter(), Counter(), []
    for _ in range(plan["unique_training_updates"]):
        keys, tokens = [], 0
        while tokens < plan["minimum_window_supervised_tokens"]:
            role = min(shares, key=lambda r: (used[r] / shares[r], rank(plan["seed"], r)))
            pool = pools[role]
            row = pool[cursors[role] % len(pool)]
            ex.require(row["key"] not in keys, "Pool exhaustion within window")
            keys.append(row["key"])
            cursors[role] += 1
            used[role] += row["supervised_tokens"]
            tokens += row["supervised_tokens"]
            ex.require(len(keys) <= plan["maximum_window_rows"], "Window row cap")
        windows.append(keys)
    return windows


def select_canary(rows, plan):
    train = [r for r in rows if r["split"] == "train"]

    def longest(role, field, predicate=lambda _: True):
        return min(
            (r for r in train if r["role"] == role and predicate(r)),
            key=lambda r: (-len(r[field]), rank(plan["seed"], r["key"])),
        )

    instruction = longest("instruction", "input_ids")
    code = longest("code", "input_ids")
    memory = longest("world", "memory_ids", lambda r: r["mode"] == "affected")
    twin = next(
        r
        for r in train
        if r["role"] == "world"
        and r["group_id"] == memory["group_id"]
        and r["mode"] == "affected"
        and r["side"] != memory["side"]
    )
    query = longest("world", "input_ids", lambda r: r["mode"] == "unaffected")
    prose = longest("prose", "input_ids")
    absent = longest("world", "input_ids", lambda r: r["mode"] == "absent")
    unrelated = longest("world", "input_ids", lambda r: r["mode"] == "unrelated")
    return [
        [r["key"] for r in [instruction, memory, twin, prose]],
        [r["key"] for r in [code, query, absent, unrelated, prose]],
    ]


def select_dev(rows, plan):
    dev = sorted(
        (r for r in rows if r["split"] == "dev"), key=lambda r: rank(plan["seed"], r["key"])
    )
    selected = []
    for family in plan["world_families"]:
        for mode in plan["world_modes"]:
            selected.append(
                next(
                    r["key"]
                    for r in dev
                    if r["role"] == "world" and r["family"] == family and r["mode"] == mode
                )
            )
    for role, count in plan["dev_preservation_rows"].items():
        pool = [r["key"] for r in dev if r["role"] == role]
        ex.require(len(pool) >= count, "Development quota")
        selected.extend(pool[:count])
    return selected


def summarize(rows, windows, canary, dev, excluded, plan):
    lookup = {r["key"]: r for r in rows}
    counts, tokens = Counter(), Counter()
    for row in rows:
        bucket = f"{row['split']}/{row['role']}"
        counts[bucket] += 1
        tokens[bucket] += row["supervised_tokens"]
    exposure, occurrences = Counter(), Counter()
    window_report, objective_share = [], Counter()
    for step, keys in enumerate(windows, 1):
        current = Counter()
        for key in keys:
            row = lookup[key]
            ex.require(row["split"] == "train", "Development in training")
            current[row["role"]] += row["supervised_tokens"]
            occurrences[row["role"]] += 1
        total = sum(current.values())
        exposure.update(current)
        for role, n in current.items():
            objective_share[role] += n / total / len(windows)
        window_report.append(
            dict(step=step, rows=len(keys), supervised_tokens=total, tokens_by_role=dict(current))
        )
    total = sum(exposure.values())
    selected = [lookup[k] for w in canary for k in w]
    return dict(
        schema="ltws-v22-data-summary-v1",
        rows=len(rows),
        counts=dict(counts),
        supervised_tokens=dict(tokens),
        excluded=excluded,
        language="en",
        truncations=0,
        target_supervised_token_shares=plan["target_supervised_token_shares"],
        training_rows=sum(map(len, windows)),
        training_unique_rows=len({k for w in windows for k in w}),
        training_tokens=total,
        training_tokens_by_role=dict(exposure),
        training_rows_by_role=dict(occurrences),
        realized_supervised_token_shares={r: n / total for r, n in exposure.items()},
        mean_window_objective_shares=dict(objective_share),
        windows=window_report,
        canary_rows=sum(map(len, canary)),
        canary_replay_rows=len(canary[1]),
        canary_max_query_tokens=max(len(r["input_ids"]) for r in selected),
        canary_max_memory_tokens=max(len(r["memory_ids"]) for r in selected),
        development_rows=len(dev),
        development_tokens=sum(lookup[k]["supervised_tokens"] for k in dev),
        train_dev_group_overlap=0,
        duplicate_sequences=0,
        test_and_ood_used=0,
        teacher_candidates_used=0,
        no_memory_preservation=True,
        original_banks_mutated=False,
        quality_claim="NOT_ESTABLISHED",
        old_expression_gate="FAIL",
        winner="none",
        rights_scope=plan["rights_scope"],
    )
