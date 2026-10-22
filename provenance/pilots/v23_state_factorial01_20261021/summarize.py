#!/usr/bin/env python3
"""Offline replay of the complete factorial and bounded descriptive contrasts."""

import argparse
import collections
import gzip
import hashlib
import itertools
import json
import math
import re
import subprocess
from pathlib import Path
from xml.etree import ElementTree

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = "6064c69ab722330f3d51574768a1c52e887d6866"
ROLES = ("base", "v22", "base_cross")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text())


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def token_key(tokens):
    return hashlib.sha256(canonical(tokens).encode()).hexdigest()


def manifest(folder):
    return {
        p.relative_to(folder).as_posix(): dict(bytes=p.stat().st_size, sha256=sha(p))
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def journal(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def terminal(folder, status, remote_only):
    end = read(folder / "FINISHED.json")
    actual = manifest(folder)
    actual.pop("FINISHED.json")
    for name, meta in remote_only.items():
        relative = (
            (HERE / "furnace" / name).relative_to(folder)
            if (HERE / "furnace" / name).is_relative_to(folder)
            else None
        )
        if relative is not None:
            actual[str(relative)] = meta
    require(end["status"] == status and end["files"] == actual, f"Terminal {folder}")
    require(
        end["new_sequences"]
        == end["native_weight_updates"]
        == end["judge_calls"]
        == end["weight_deletions"]
        == 0,
        "Activity ceiling",
    )
    require(
        end["old_expression_gate"] == "FAIL"
        and end["winner"] == "none"
        and end["non_regression"] == "NOT_ESTABLISHED",
        "Claim ceiling",
    )
    return end


def stats(values):
    require(bool(values) and all(math.isfinite(x) for x in values), "Finite nonempty distribution")
    return dict(
        n=len(values), mean=sum(values) / len(values), minimum=min(values), maximum=max(values)
    )


def paired(a, b):
    require(set(a) == set(b), "Paired coverage")
    return dict(
        n=len(a),
        left_correct=sum(a.values()),
        right_correct=sum(b.values()),
        repairs=sum(not a[k] and b[k] for k in a),
        losses=sum(a[k] and not b[k] for k in a),
    )


def label(w, q, r):
    return f"W={w}/Q={q}/R={r}"


def aggregate(cells, world_rows):
    world, mmlu = {}, {}
    for (kind, rid, j, w, q, r), record in cells.items():
        target = world if kind == "world" else mmlu
        target.setdefault(label(w, q, r), {})[(rid, j)] = record
    metrics, all_paths = {}, {}
    for cell, rows in world.items():
        groups = collections.defaultdict(list)
        for (rid, _), record in rows.items():
            groups[rid].append(record)
        paths = {rid: all(r["score"]["correct"] for r in values) for rid, values in groups.items()}
        all_paths[cell] = paths
        subsets = {
            "all": list(rows.values()),
            "first_two_positions": [r for r in rows.values() if r["index"] < 2],
            "later_symbol_positions": [
                r
                for r in rows.values()
                if re.fullmatch(r"N[a-z]+\.", world_rows[r["id"]]["answer"])
                and 2 <= r["index"] < len(world_rows[r["id"]]["answer_ids"]) - 2
            ],
        }
        metrics[cell] = dict(
            rows=len(groups),
            oracle_prefix_all_top1=sum(paths.values()),
            modes={
                mode: dict(
                    rows=sum(world_rows[k]["mode"] == mode for k in paths),
                    all_top1=sum(v for k, v in paths.items() if world_rows[k]["mode"] == mode),
                )
                for mode in sorted({world_rows[k]["mode"] for k in paths})
            },
            positions={
                name: dict(
                    n=len(sub),
                    correct=sum(r["score"]["correct"] for r in sub),
                    mean_gold_logprob=sum(r["score"]["gold_logprob"] for r in sub) / len(sub)
                    if sub
                    else None,
                )
                for name, sub in subsets.items()
            },
        )
    contrasts = {}
    for factor in range(3):
        for fixed in itertools.product(("base", "v22"), repeat=2):
            low, high = list(fixed), list(fixed)
            low.insert(factor, "base")
            high.insert(factor, "v22")
            a, b = label(*low), label(*high)
            contrasts[f"{'WQR'[factor]}: {a} -> {b}"] = dict(
                paths=paired(all_paths[a], all_paths[b]),
                positions=paired(
                    {k: r["score"]["correct"] for k, r in world[a].items()},
                    {k: r["score"]["correct"] for k, r in world[b].items()},
                ),
                changed_top1=sum(
                    world[a][k]["score"]["top1"] != world[b][k]["score"]["top1"] for k in world[a]
                ),
                gold_logprob_shift=stats(
                    [
                        world[b][k]["score"]["gold_logprob"] - world[a][k]["score"]["gold_logprob"]
                        for k in sorted(world[a])
                    ]
                ),
            )
    # Full inclusion-exclusion expansion; no additive attribution assumption.
    baseline = world[label("base", "base", "base")]
    effects = {}
    for degree in (1, 2, 3):
        for factors in itertools.combinations(range(3), degree):
            values = []
            for key in sorted(baseline):
                value = 0
                for bits in itertools.product((0, 1), repeat=degree):
                    settings = ["base"] * 3
                    for i, bit in zip(factors, bits, strict=True):
                        settings[i] = "v22" if bit else "base"
                    value += (-1) ** (degree - sum(bits)) * world[label(*settings)][key]["score"][
                        "gold_logprob"
                    ]
                values.append(value)
            effects["".join("WQR"[i] for i in factors)] = stats(values)
    mm_metrics = {
        cell: dict(
            n=len(rows),
            correct=sum(r["score"]["correct"] for r in rows.values()),
            strict_correct=sum(r["score"]["strict_correct"] for r in rows.values()),
            ties=sum(r["score"]["ties"] > 1 for r in rows.values()),
        )
        for cell, rows in mmlu.items()
    }
    mm_contrasts = {}
    for factor in (1, 2):
        for fixed in ("base", "v22"):
            a = label("none", "base" if factor == 1 else fixed, "base" if factor == 2 else fixed)
            b = label("none", "v22" if factor == 1 else fixed, "v22" if factor == 2 else fixed)
            mm_contrasts[f"{a} -> {b}"] = paired(
                {k: v["score"]["correct"] for k, v in mmlu[a].items()},
                {k: v["score"]["correct"] for k, v in mmlu[b].items()},
            )
    native_base = mmlu[label("none", "base", "base")]
    changed_ids = {
        k
        for k in native_base
        if len({rows[k]["score"]["prediction"] for rows in mmlu.values()}) > 1
    }
    mm_changed = {
        str(k[0]): {cell: rows[k]["score"] for cell, rows in mmlu.items()}
        for k in sorted(changed_ids)
    }
    # Same common oracle prefix, reciprocal donor signs, unchanged Q and R.
    direction = {}
    for cell, rows in world.items():
        selected = [r for r in rows.values() if r.get("donor_token") is not None]
        if not selected:
            continue
        by_key = {(r["id"], r["index"]): r for r in selected}
        direction[cell] = {}
        for stratum in ("all", "equal_length", "unequal_length"):
            deltas = []
            for record in selected:
                donor = by_key[record["donor_id"], record["index"]]
                require(
                    record["query_key"] == donor["query_key"]
                    and record["target"] == donor["donor_token"],
                    "Common-prefix natural twin",
                )
                equal = record["memory_tokens"] == donor["memory_tokens"]
                if stratum != "all" and equal != (stratum == "equal_length"):
                    continue
                deltas.append(
                    -donor["score"]["donor_minus_original"]
                    - record["score"]["donor_minus_original"]
                )
            direction[cell][stratum] = dict(positive=sum(d > 0 for d in deltas), **stats(deltas))
    return dict(
        world_cells=metrics,
        factorial_contrasts=contrasts,
        token_weighted_logprob_interactions=effects,
        mmlu_cells=mm_metrics,
        mmlu_contrasts=mm_contrasts,
        mmlu_changed=mm_changed,
        natural_twin=direction,
    )


def compute():
    bundle = HERE / "furnace"
    publication = read(bundle / "PUBLICATION_MANIFEST.json")
    actual = manifest(bundle)
    actual.pop("PUBLICATION_MANIFEST.json")
    require(actual == publication["included"], "Every published byte")
    remote_only = publication["remote_only"]
    require(
        set(remote_only) == {f"raw/{r}/cut_states.safetensors" for r in ("base", "v22")},
        "Explicit remote-only artifacts",
    )
    witness = read(bundle / "REMOTE_TERMINAL_CHECK.json")
    require(
        witness["status"] == "V23_STATE_FACTORIAL_OFFLINE_TERMINAL_PASS"
        and witness["source"] == SOURCE
        and witness["model_calls"] == 0
        and witness["no_checkpoint_writes"],
        "Remote offline witness",
    )
    require(
        witness["verifier_sha256"]
        == sha(HERE / "verify_remote.py")
        == sha(bundle / "verify_remote.py"),
        "Witness verifier identity",
    )
    require(not any(r["process_exists"] for r in witness["workers"].values()), "Workers ended")
    seal = read(bundle / "SOURCE_SEAL.json")
    require(seal["source_commit"] == SOURCE and len(seal["source_hashes"]) == 744, "Frozen source")
    for name, digest in seal["source_hashes"].items():
        raw = subprocess.check_output(["git", "show", f"{SOURCE}:{name}"], cwd=ROOT)
        require(hashlib.sha256(raw).hexdigest() == digest, f"Sealed source {name}")
    plan = read(ROOT / "configs/v23/STATE_FACTORIAL_01.json")
    qualifications = {}
    for device in ("cpu", "cuda"):
        folder = bundle / "qualification" / device
        end = terminal(folder, "TINY_V23_STATE_FACTORIAL_PASS_NOT_7B", remote_only)
        expected = dict(tests=216, failures=0, errors=0, skipped=0)
        counts = collections.Counter()
        for suite in ElementTree.parse(folder / "TESTS.xml").getroot().iter("testsuite"):
            counts.update({k: int(suite.attrib.get(k, 0)) for k in expected})
        require(dict(counts) == end["counts"] == expected, "Qualification denominator")
        start = read(folder / "STARTED.json")
        require(
            start["seal"] == seal and start["plan"] == plan and start["device"] == device,
            "Qualification seal/plan/device",
        )
        qualifications[device] = dict(counts=expected, elapsed_seconds=end["elapsed_seconds"])
    dispatch = terminal(bundle / "raw", plan["pass_status"], remote_only)
    require(dispatch["completed_roles"] == list(ROLES), "Complete roles")
    training = HERE.parent / "v22_full_ft_recovery01_20261021/furnace/raw/train_b"
    restore = read(bundle / "raw/v22/RESTORE.json")
    require(
        restore["exact"]
        and restore["fingerprint"] == read(training / "STATE_training_step32.pt.json")
        and restore["checkpoint"] == read(training / "CHECKPOINT_training_step32.pt.json")
        and restore["training_contract"] == read(training / "CONTEXT.json")["contract"],
        "Complete native-owner restore",
    )
    require(
        witness["checkpoint_sha256"] == restore["checkpoint"]["sha256"], "Post-terminal checkpoint"
    )
    original = HERE.parent / "v22_base_comparison01_20261021/furnace"
    data = json.loads(gzip.decompress((original / "inputs/INPUTS.json.gz").read_bytes()))
    rows = {r["row_id"]: r for r in data["worlds"]}
    mm = {r["id"]: r for r in data["mmlu"]}
    cells, outcomes, repeats = {}, {}, 0
    for role in ROLES:
        folder = bundle / "raw" / role
        end = terminal(folder, "V23_STATE_FACTORIAL_ARM_COMPLETE", remote_only)
        start = read(folder / "STARTED.json")
        require(start["seal"] == seal and start["plan"] == plan, "Role source and plan")
        identity = read(folder / "WEIGHT_IDENTITY.json")
        require(identity["equal"] and identity["before"] == identity["after"], "Frozen weights")
        if role != "base_cross":
            bank = read(folder / "CUT_BANK.json")
            require(
                bank["sha256"]
                == remote_only[f"raw/{role}/cut_states.safetensors"]["sha256"]
                == witness["banks"][role]["sha256"],
                "Activation bank witness",
            )
        records = journal(folder / "cells.jsonl")
        observed = set()
        reader = "v22" if role == "v22" else "base"
        for record in records:
            kind, rid, j = record["kind"], record["id"], record["index"]
            source = rows[rid] if kind == "world" else mm[rid]
            tokens = (
                source["prefixes"]["latent"] + source["answer_ids"][:j]
                if kind == "world"
                else source["input_ids"]
            )
            memory = source["memory_ids"] if kind == "world" else []
            target = source["answer_ids"][j] if kind == "world" else source["target"]
            require(
                record["query_key"] == token_key(tokens)
                and record["memory_key"] == (token_key(memory) if memory else None)
                and record["target"] == target,
                "Exact input and target binding",
            )
            require(
                record["query_tokens"] == len(tokens) and record["memory_tokens"] == len(memory),
                "Sequence extent",
            )
            key = (kind, rid, j, record["writer"], record["query_encoder"], record["reader"])
            require(key not in observed and record["reader"] == reader, "Unique per-role cell")
            observed.add(key)
            score = record["score"]
            require(math.isfinite(score["gold_logprob"]), "Finite score")
            if kind == "world":
                require(
                    score["target"] == target and score["correct"] == (score["top1"] == target),
                    "Token correctness",
                )
            else:
                logits = score["logits"]
                predicted = max(range(4), key=lambda i: logits[i])
                ties = sum(x == max(logits) for x in logits)
                require(
                    score["prediction"] == predicted
                    and score["ties"] == ties
                    and score["correct"] == (predicted == target)
                    and score["strict_correct"] == (predicted == target and ties == 1),
                    "MMLU arithmetic",
                )
            if key in cells:
                require(cells[key] == record, "Exact repeated base journal row")
                repeats += 1
            else:
                cells[key] = record
        require(
            sum(r["kind"] == "world" for r in records) == end["outcome"]["world_cells"]
            and sum(r["kind"] == "mmlu" for r in records) == end["outcome"]["mmlu_cells"],
            "Role counts",
        )
        outcomes[role] = dict(**end["outcome"], elapsed_seconds=end["elapsed_seconds"])
    expected = {
        ("world", rid, j, w, q, r)
        for rid, source in rows.items()
        for j in range(len(source["answer_ids"]))
        for w in (("base", "v22") if source["memory_ids"] else ("none",))
        for q in ("base", "v22")
        for r in ("base", "v22")
    }
    expected |= {
        ("mmlu", rid, 0, "none", q, r)
        for rid in mm
        for q in ("base", "v22")
        for r in ("base", "v22")
    }
    require(set(cells) == expected and repeats == 1193, "Every selected factorial cell, no extras")
    require(
        sum(k[0] == "world" for k in cells) == 4728 and sum(k[0] == "mmlu" for k in cells) == 2280,
        "Unique denominators",
    )
    require(
        dispatch["summary"]
        == dict(
            world_cells=5351,
            mmlu_cells=2850,
            full_self_parity=2386,
            repeated_self_parity=1193,
            new_sequences=0,
            native_weight_updates=0,
            checkpoint_saves=0,
        ),
        "Complete dispatch accounting",
    )
    require(
        [outcomes[r]["full_self_parity"] for r in ROLES] == [1193, 1193, 0]
        and [outcomes[r]["repeated_self_parity"] for r in ROLES] == [0, 0, 1193],
        "All measured parity denominators",
    )
    # Reproduce previous self-cell receipts independently of runner assertions.
    for host in ("base", "v22"):
        prior = HERE.parent / "v22_memory_causality01_20261021/furnace/raw" / host / "prefix.jsonl"
        require(
            sha(prior) == plan["historical_prefix_sha256"][host], "Original cropped journal bytes"
        )
        for record in journal(prior):
            if record["route"] == "latent":
                rid, j = record["id"], record["index"]
                w = host if rows[rid]["memory_ids"] else "none"
                cell = cells["world", rid, j, w, host, host]
                observed_score = {
                    k: v for k, v in cell["score"].items() if k != "donor_minus_original"
                }
                require(
                    cell["logits_sha256"] == record["variants"]["cropped"]["sha256"]
                    and observed_score == record["variants"]["cropped"]["score"],
                    "Exact historical cropped endpoint",
                )
        for record in journal(original / "raw" / host / "mmlu.jsonl"):
            score = cells["mmlu", record["id"], 0, "none", host, host]["score"]
            require(score == {k: record[k] for k in score}, "Historical MMLU score")
    summary = dict(
        schema="ltws-v23-state-factorial-summary-v1",
        source=SOURCE,
        qualifications=qualifications,
        outcomes=outcomes,
        planned=plan["planned"],
        unique_cells=len(cells),
        repeated_cells=repeats,
        remote_only=remote_only,
        invalid_cells=0,
        retries=0,
        new_sequences=0,
        model_calls_during_analysis=0,
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
        **aggregate(cells, rows),
    )
    return summary, cells, rows, mm


def panel(cells, rows, mm):
    text = read(HERE / "furnace/TOKEN_TEXT.json")["tokens"]
    old = HERE.parent / "v22_base_comparison01_20261021/furnace/raw"
    generations = {
        host: {r["id"]: r for r in journal(old / host / "worlds.jsonl") if r["route"] == "latent"}
        for host in ("base", "v22")
    }
    lines = [
        "# W/Q/R fixed-prefix panel: all 96 world rows",
        "",
        "This assay generates no answers. Tables show the first disagreement with",
        "the **oracle-provided prefix**, not a hybrid free-generation continuation.",
        "Only the two explicitly labeled historical strings are actual generated answers.",
        "W = memory writer; Q = question AND continuation encoder; R = upper reader/head.",
        "Token strings use JSON quoting to preserve spaces and special symbols.",
        "",
    ]
    for rid, row in sorted(rows.items()):
        lines += [
            f"## {rid}",
            "",
            f"Mode: {row['mode']}; target: `{row['answer']}`.",
            "",
            "Memory:",
            "",
            "```text",
            row["memory"],
            "```",
            "",
            "Question (with the original short-answer suffix and chat template):",
            "",
            "```text",
            row["query"],
            "```",
            "",
        ]
        for host in ("base", "v22"):
            prior = generations[host][rid]
            lines += [
                f"Historical {host} generation ({prior['stop_reason']}):",
                "",
                "```text",
                prior["text"],
                "```",
                "",
            ]
        lines += [
            "| W | Q | R | Gold-prefix top-1 positions | First mismatch index "
            "| Target token | Predicted token | Gold margin |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for w, q, r in itertools.product(
            ("base", "v22") if row["memory_ids"] else ("none",), ("base", "v22"), ("base", "v22")
        ):
            values = [cells["world", rid, j, w, q, r] for j in range(len(row["answer_ids"]))]
            failures = [v for v in values if not v["score"]["correct"]]
            tail = "— | — | — | —"
            if failures:
                first = failures[0]
                target, predicted = (
                    json.dumps(text[str(i)], ensure_ascii=True)
                    for i in (first["target"], first["score"]["top1"])
                )
                require(
                    "|" not in target + predicted and "`" not in target + predicted,
                    "Literal table delimiters",
                )
                tail = (
                    f"{first['index']} | `{target}` | `{predicted}` "
                    f"| {first['score']['gold_margin']:.8g}"
                )
            lines.append(
                f"| {w} | {q} | {r} | {len(values) - len(failures)}/{len(values)} | {tail} |"
            )
        lines += [""]
    lines += [
        "# MMLU: every question with any Q/R prediction change",
        "",
        "All 570 questions are retained in the raw journals; this panel selects every",
        "prediction-changing case across the four fixed-prefix cells, not only losses.",
        "",
    ]
    for rid, row in sorted(mm.items()):
        four = {
            (q, r): cells["mmlu", rid, 0, "none", q, r]["score"]
            for q, r in itertools.product(("base", "v22"), repeat=2)
        }
        if len({s["prediction"] for s in four.values()}) == 1:
            continue
        lines += [
            f"## {rid} — {row['subject']}",
            "",
            "```text",
            row["question"],
            "```",
            "",
            f"Gold: {'ABCD'[row['target']]}",
            "",
            "| Q | R | Prediction | Correct | Ties | A/B/C/D logits |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for (q, r), score in four.items():
            lines.append(
                f"| {q} | {r} | {'ABCD'[score['prediction']]} | {score['correct']} "
                f"| {score['ties']} | {score['logits']} |"
            )
        lines += [""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    summary, cells, rows, mm = compute()
    literal = panel(cells, rows, mm)
    if args.verify:
        require(read(HERE / "SUMMARY.json") == summary, "Summary exact replay")
        require((HERE / "FACTORIAL_PANEL.md").read_text() == literal, "Literal panel exact replay")
    else:
        with (HERE / "SUMMARY.json").open("x") as stream:
            json.dump(summary, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
        with (HERE / "FACTORIAL_PANEL.md").open("x") as stream:
            stream.write(literal)
    print(
        json.dumps(
            dict(
                status="V23_STATE_FACTORIAL_OFFLINE_REPLAY_PASS",
                unique_cells=summary["unique_cells"],
                repeated_cells=summary["repeated_cells"],
                new_sequences=0,
            )
        )
    )


if __name__ == "__main__":
    main()
