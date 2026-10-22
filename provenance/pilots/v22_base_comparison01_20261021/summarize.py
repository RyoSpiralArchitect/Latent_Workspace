#!/usr/bin/env python3
"""Offline byte/denominator replay and complete paired publication. No model calls."""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path
from xml.etree import ElementTree

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def read(p):
    return json.loads(p.read_text())


def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def manifest(p):
    return {
        f.relative_to(p).as_posix(): dict(bytes=f.stat().st_size, sha256=sha(f))
        for f in sorted(p.rglob("*"))
        if f.is_file()
    }


def terminal(p, status):
    end = read(p / "FINISHED.json")
    files = manifest(p)
    files.pop("FINISHED.json")
    require(end["files"] == files and end["status"] == status, f"Terminal bytes/status: {p}")
    return end


def journal(p):
    return [json.loads(line) for line in p.read_text().splitlines()]


def norm(text):
    return re.sub(r"\s+", " ", text.strip()).rstrip(".").strip().casefold()


def pair(a, b):
    require(set(a) == set(b), "Paired coverage")
    c = dict(both_correct=0, base_only=0, v22_only=0, both_wrong=0)
    for k in a:
        c[
            "both_correct"
            if a[k] and b[k]
            else "base_only"
            if a[k]
            else "v22_only"
            if b[k]
            else "both_wrong"
        ] += 1
    return dict(
        n=len(a),
        **c,
        base_correct=c["both_correct"] + c["base_only"],
        v22_correct=c["both_correct"] + c["v22_only"],
        delta=(sum(b.values()) - sum(a.values())) / len(a),
    )


def generation_check(row, policy, eos=2):
    ids = row["token_ids"]
    require(
        ids and len(ids) == row["generated_tokens"] <= policy["max_new_tokens"],
        "Generation denominator",
    )
    require(all(type(i) is int and 0 <= i < 32768 for i in ids), "Token range")
    require(
        row["max_new_tokens"] == policy["max_new_tokens"]
        and row["temperature"] == policy["temperature"]
        and row["top_p"] == policy["top_p"],
        "Generation policy",
    )
    require(eos not in ids[:-1], "Past EOS continuation")
    require(
        (row["stop_reason"] == "eos" and ids[-1] == eos)
        or (
            row["stop_reason"] == "length"
            and len(ids) == policy["max_new_tokens"]
            and ids[-1] != eos
        ),
        "Stop/censoring receipt",
    )


def world_summary(a, b):
    result = pair(
        {(r["id"], r["route"]): r["exact_match"] for r in a},
        {(r["id"], r["route"]): r["exact_match"] for r in b},
    )
    for arm, rows in (("base", a), ("v22", b)):
        nll = sum(r["teacher"]["nll_sum"] for r in rows)
        tokens = sum(r["teacher"]["supervised_tokens"] for r in rows)
        result[arm] = dict(
            teacher_nll_sum=nll,
            teacher_tokens=tokens,
            token_nll=nll / tokens,
            generated_tokens=sum(r["generated_tokens"] for r in rows),
            eos=sum(r["stop_reason"] == "eos" for r in rows),
            length=sum(r["stop_reason"] == "length" for r in rows),
        )
    return result


def compute(bundle):
    seal = read(bundle / "SOURCE_SEAL.json")
    for name, digest in seal["source_hashes"].items():
        body = subprocess.check_output(["git", "show", f"{seal['source_commit']}:{name}"], cwd=ROOT)
        require(hashlib.sha256(body).hexdigest() == digest, f"Committed source: {name}")
    plan = read(ROOT / "configs/v22/BASE_COMPARISON_01.json")
    oracle = read(HERE / "WORLD_ORACLE_REPLAY.json")
    require(
        oracle["status"] == "WORLD_ORACLE_AND_RENDER_REPLAY_PASS"
        and oracle["rows"] == 96
        and oracle["model_calls"] == 0
        and oracle["generator_sha256"]
        == seal["source_hashes"]["src/latent_workspace/world_bank.py"],
        "Visible-fact oracle replay",
    )
    decoding = read(bundle / "OFFLINE_REPLAY.json")
    require(
        decoding["status"] == "OFFLINE_INPUT_AND_DECODING_REPLAY_PASS"
        and decoding["source_commit"] == seal["source_commit"] == decoding["source_head"]
        and decoding["input_regeneration_exact"]
        and decoding["no_checkpoint_writes"]
        and decoding["model_calls"] == decoding["new_sequences"] == 0
        and decoding["training_bank_files_verified"] == 5
        and decoding["literal_rows"]
        == {"base/free": 24, "base/worlds": 192, "v22/free": 24, "v22/worlds": 192},
        "Offline input and literal decoding receipt",
    )
    engine_changes = subprocess.check_output(
        [
            "git",
            "diff",
            "--name-status",
            plan["training_source"],
            seal["source_commit"],
            "--",
            "src",
        ],
        cwd=ROOT,
        text=True,
    ).splitlines()
    require(
        engine_changes == ["A\tsrc/latent_workspace/native_evaluation.py"],
        "Training engine must remain unchanged; evaluation helper is additive",
    )
    inputs_manifest = read(bundle / "inputs/MANIFEST.json")
    require(
        sha(bundle / "inputs/MANIFEST.json")
        == sha(ROOT / "configs/v22/comparison_20261021/MANIFEST.json"),
        "Input seal",
    )
    files = manifest(bundle / "inputs")
    files.pop("MANIFEST.json")
    require(files == inputs_manifest["files"], "Input bytes")
    inputs = json.loads(gzip.decompress((bundle / "inputs/INPUTS.json.gz").read_bytes()))
    quals = {}
    for device in ("cpu", "cuda"):
        folder = bundle / "qualification" / device
        end = terminal(folder, "TINY_V22_EVALUATION_PASS_NOT_7B")
        expected = dict(tests=138, failures=0, errors=0, skipped=0)
        suites = list(ElementTree.parse(folder / "TESTS.xml").getroot().iter("testsuite"))
        require(
            {k: sum(int(s.attrib.get(k, 0)) for s in suites) for k in expected}
            == expected
            == end["counts"],
            "All tiny tests",
        )
        require(read(folder / "STARTED.json")["seal"] == seal, "Qualification source")
        quals[device] = dict(counts=end["counts"], elapsed_seconds=end["elapsed_seconds"])
    all_end = terminal(bundle / "raw", "V22_BASE_COMPARISON_COMPLETE_NOT_RELEASE")
    require(all_end["completed_roles"] == ["base", "v22"], "Both roles")
    require(read(bundle / "raw/STARTED.json")["seal"] == seal, "Dispatcher source")
    measured = {}
    mmlu_inputs = {r["id"]: r for r in inputs["mmlu"]}
    world_inputs = {r["row_id"]: r for r in inputs["worlds"]}
    free_inputs = {r["id"]: r for r in inputs["free"]}
    for arm in ("base", "v22"):
        folder = bundle / "raw" / arm
        end = terminal(folder, "V22_EVALUATION_ARM_COMPLETE")
        start = read(folder / "STARTED.json")
        require(start["seal"] == seal and start["plan"] == plan, "Role source/plan")
        require(end["new_sequences"] == 216 and end["native_weight_updates"] == 0, "Activity")
        identity = read(folder / "WEIGHT_IDENTITY.json")
        require(identity["before"] == identity["after"] and identity["equal"], "Frozen weights")
        original = read(folder / "ORIGINAL_IDENTITY.json")
        require(all(original["matches"].values()), "Original identity")
        require(all(r["bitwise_equal"] for r in read(folder / "PARITY.json")), "Native parity")
        mmlu, worlds, free = [journal(folder / (n + ".jsonl")) for n in ("mmlu", "worlds", "free")]
        require(
            len(mmlu) == len({r["id"] for r in mmlu}) == 570
            and {r["id"] for r in mmlu} == set(mmlu_inputs),
            "MMLU rows",
        )
        for row in mmlu:
            source = mmlu_inputs[row["id"]]
            require(
                row["target"] == source["target"] and row["subject"] == source["subject"],
                "MMLU target",
            )
            scores = row["logits"]
            require(len(scores) == 4 and all(math.isfinite(v) for v in scores), "Finite scores")
            pred = max(range(4), key=lambda i: scores[i])
            ties = scores.count(max(scores))
            require(
                row["prediction"] == pred
                and row["ties"] == ties
                and row["correct"] == (pred == row["target"])
                and row["strict_correct"] == (pred == row["target"] and ties == 1),
                "Choice score replay",
            )
        require(
            len(worlds) == len({(r["id"], r["route"]) for r in worlds}) == 192
            and {(r["id"], r["route"]) for r in worlds}
            == {(k, route) for k in world_inputs for route in plan["world_routes"]},
            "World coverage",
        )
        for row in worlds:
            source = world_inputs[row["id"]]
            require(
                all(
                    row[k] == source[k]
                    for k in ("group_id", "family", "split", "mode", "side", "aliases")
                ),
                "World key",
            )
            require(
                row["target"] == source["answer"]
                and row["exact_match"] == (norm(row["text"]) == norm(row["target"])),
                "Literal exact match",
            )
            require(
                row["teacher"]["supervised_tokens"] == len(source["answer_ids"])
                and math.isfinite(row["teacher"]["nll_sum"]),
                "World teacher denominator",
            )
            generation_check(row, plan["world_generation"])
            require(row["seed"] == plan["world_generation"]["seed"], "World seed")
        require(
            len(free) == len({(r["id"], r["seed"]) for r in free}) == 24
            and {(r["id"], r["seed"]) for r in free}
            == {(k, seed) for k in free_inputs for seed in plan["generation"]["seeds"]},
            "Free coverage",
        )
        for row in free:
            source = free_inputs[row["id"]]
            require(
                row["prompt"] == source["prompt"] and row["category"] == source["category"],
                "Free prompt identity",
            )
            generation_check(row, plan["generation"])
        require(
            end["outcome"]["generated_tokens"] == sum(r["generated_tokens"] for r in worlds + free),
            "Total token receipt",
        )
        measured[arm] = dict(
            mmlu=mmlu,
            worlds=worlds,
            free=free,
            outcome=end["outcome"],
            elapsed_seconds=end["elapsed_seconds"],
        )
    restore = read(bundle / "raw/v22/RESTORE.json")
    require(
        restore["exact"]
        and restore["checkpoint"]["sha256"] == plan["checkpoint"]["sha256"]
        and restore["checkpoint"]["state_sha256"] == plan["checkpoint"]["state_sha256"]
        and restore["fingerprint"]["completed_steps"] == 32,
        "Exact V22 restoration",
    )
    a, b = measured["base"], measured["v22"]
    absent_parity = {}
    for arm, values in measured.items():
        rows = {(r["id"], r["route"]): r for r in values["worlds"] if r["mode"] == "absent"}
        ids = {key for key, _ in rows}
        for key in ids:
            left, right = rows[key, "latent"], rows[key, "inline"]
            require(
                left["token_ids"] == right["token_ids"] and left["teacher"] == right["teacher"],
                "Empty-memory latent/inline identity",
            )
        absent_parity[arm] = dict(rows=len(ids), identical_tokens_and_teacher_nll=True)
    mmlu = pair(
        {r["id"]: r["correct"] for r in a["mmlu"]}, {r["id"]: r["correct"] for r in b["mmlu"]}
    )
    mmlu["strict"] = pair(
        {r["id"]: r["strict_correct"] for r in a["mmlu"]},
        {r["id"]: r["strict_correct"] for r in b["mmlu"]},
    )
    mmlu["ties"] = {arm: sum(r["ties"] > 1 for r in measured[arm]["mmlu"]) for arm in measured}
    mmlu["per_subject"] = {
        subject: pair(
            {r["id"]: r["correct"] for r in a["mmlu"] if r["subject"] == subject},
            {r["id"]: r["correct"] for r in b["mmlu"] if r["subject"] == subject},
        )
        for subject in sorted({r["subject"] for r in a["mmlu"]})
    }
    worlds = {}
    for split in ("test", "ood"):
        for route in plan["world_routes"]:
            for mode in ("all", "affected", "unaffected", "absent", "unrelated"):

                def select(rows):
                    return [
                        r
                        for r in rows
                        if r["split"] == split
                        and r["route"] == route
                        and (mode == "all" or r["mode"] == mode)
                    ]

                worlds[f"{split}/{route}/{mode}"] = world_summary(
                    select(a["worlds"]), select(b["worlds"])
                )
    twins = {}
    for arm in measured:
        for route in plan["world_routes"]:
            groups = collections.defaultdict(list)
            for row in measured[arm]["worlds"]:
                if row["route"] == route and row["mode"] == "affected":
                    groups[row["group_id"]].append(row)
            require(all(len(rows) == 2 for rows in groups.values()), "Whole twin groups")
            twins[f"{arm}/{route}"] = dict(
                groups=len(groups),
                both_correct=sum(all(r["exact_match"] for r in rows) for rows in groups.values()),
                changed_text=sum(rows[0]["text"] != rows[1]["text"] for rows in groups.values()),
            )
    free_pairs = {arm: {(r["id"], r["seed"]): r for r in measured[arm]["free"]} for arm in measured}
    free = dict(
        pairs=24,
        changed_text=sum(
            free_pairs["base"][k]["text"] != free_pairs["v22"][k]["text"]
            for k in free_pairs["base"]
        ),
        arms={
            arm: dict(
                generated_tokens=sum(r["generated_tokens"] for r in measured[arm]["free"]),
                eos=sum(r["stop_reason"] == "eos" for r in measured[arm]["free"]),
                length=sum(r["stop_reason"] == "length" for r in measured[arm]["free"]),
            )
            for arm in measured
        },
        quality="UNJUDGED; all pairs in ANSWER_BANK.md",
    )
    free["per_category"] = {}
    for category in ("reasoning", "writing", "code"):
        keys = [k for k, r in free_pairs["base"].items() if r["category"] == category]
        free["per_category"][category] = dict(
            pairs=len(keys),
            changed_text=sum(
                free_pairs["base"][k]["text"] != free_pairs["v22"][k]["text"] for k in keys
            ),
            arms={
                arm: dict(
                    generated_tokens=sum(free_pairs[arm][k]["generated_tokens"] for k in keys),
                    eos=sum(free_pairs[arm][k]["stop_reason"] == "eos" for k in keys),
                    length=sum(free_pairs[arm][k]["stop_reason"] == "length" for k in keys),
                )
                for arm in free_pairs
            },
        )
    summary = dict(
        status="COMPLETE_DESCRIPTIVE_COMPARISON_NOT_RELEASE",
        execution_source=seal["source_commit"],
        training_engine_unchanged=True,
        source_files=len(seal["source_hashes"]),
        inputs=inputs_manifest,
        qualifications=quals,
        planned=plan["planned"],
        measured=dict(
            new_sequences=432,
            native_weight_updates=0,
            checkpoint_saves=0,
            judge_calls=0,
            weight_deletions=0,
        ),
        mmlu=mmlu,
        empty_memory_route_parity=absent_parity,
        worlds=worlds,
        twins=twins,
        free_generation=free,
        resources={
            arm: dict(elapsed_seconds=measured[arm]["elapsed_seconds"], **measured[arm]["outcome"])
            for arm in measured
        },
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
        limitations=plan["claim_scope"],
    )
    return summary, measured


def fence(text):
    ticks = max([3] + [len(s) for s in re.findall(r"`+", text)]) + 1
    mark = "`" * ticks
    return mark + "text\n" + text + "\n" + mark


def bank(measured):
    left = {(r["id"], r["seed"]): r for r in measured["base"]["free"]}
    right = {(r["id"], r["seed"]): r for r in measured["v22"]["free"]}
    parts = [
        "# V22 versus base — all 24 free-generation pairs\n",
        "Unblinded human-inspection artifact; no LLM judge or quality score. "
        "Same prompt/seed and full-vocabulary sampling policy in both arms. "
        "Length-capped replies are censored, not complete answers.\n",
    ]
    for key in sorted(left):
        a, b = left[key], right[key]
        parts += [f"## {key[0]} — seed {key[1]}\n", "Prompt:\n", fence(a["prompt"])]
        for name, row in (("Original Mistral", a), ("V22 step 32", b)):
            parts += [
                f"### {name}\n",
                f"{row['generated_tokens']} tokens; stop: {row['stop_reason']}.\n",
                fence(row["text"]),
            ]
    return "\n\n".join(parts) + "\n"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bundle", type=Path, default=HERE / "furnace")
    p.add_argument("--verify", action="store_true")
    args = p.parse_args()
    summary, measured = compute(args.bundle)
    text = json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n"
    panel = bank(measured)
    if args.verify:
        require((HERE / "SUMMARY.json").read_text() == text, "Summary exact replay")
        require((HERE / "ANSWER_BANK.md").read_text() == panel, "Literal panel exact replay")
        print(
            "Verified frozen source, inputs, qualifications, terminals, scores and literal panel."
        )
    else:
        with (HERE / "SUMMARY.json").open("x") as f:
            f.write(text)
        with (HERE / "ANSWER_BANK.md").open("x") as f:
            f.write(panel)
        print(text)


if __name__ == "__main__":
    main()
