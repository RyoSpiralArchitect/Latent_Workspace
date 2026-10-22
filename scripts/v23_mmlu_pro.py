#!/usr/bin/env python3
"""Prospective fixed MMLU-Pro panel: download, select, tokenize; no model forward.

Scoring/analysis helpers are pure and shared with the separate sealed runner.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import ssl
import sys
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from latent_workspace import execution as ex  # noqa: E402
from latent_workspace import native_evaluation as ev  # noqa: E402

PLAN = "configs/v23/MMLU_PRO_01.json"
LETTERS = "ABCDEFGHIJ"


def normalized(row):
    old = row["options"]
    target = row["answer_index"]
    ex.require(
        type(target) is int and 0 <= target < len(old) and row["answer"] == LETTERS[target],
        "Source answer consistency",
    )
    keep = [i for i, value in enumerate(old) if value != "N/A"]
    ex.require(target in keep and 2 <= len(keep) <= 10, "Nonempty gold / option count")
    # Official preprocessing drops N/A; remap rather than assuming they are trailing.
    target = keep.index(target)
    return dict(
        id=f"{row['category']}:{row['question_id']}",
        question_id=row["question_id"],
        category=row["category"],
        question=row["question"],
        options=[old[i] for i in keep],
        target=target,
        letter=LETTERS[target],
        source_answer=row["answer"],
        source_options=old,
        option_index_map=keep,
        cot_content=row["cot_content"],
        src=row["src"],
    )


def select(test, validation, p):
    test, validation = [normalized(r) for r in test], [normalized(r) for r in validation]
    ex.require(len({r["id"] for r in test}) == len(test), "Unique test IDs")
    categories = sorted({r["category"] for r in test})
    ex.require(len(categories) == 14, "Fourteen categories")
    selected, examples, generation = [], [], []
    for category in categories:
        pool = [r for r in test if r["category"] == category]
        rows = sorted(pool, key=lambda r: ev.rank(p["selection_seed"], r["id"]))[
            : p["per_category"]
        ]
        ex.require(len(rows) == p["per_category"], "Category test denominator")
        shots = [r for r in validation if r["category"] == category]
        ex.require(len(shots) == p["shots"], "Exactly five validation examples")
        ex.require(
            all(r["letter"] == r["source_answer"] for r in shots),
            "Do not silently relabel a validation rationale",
        )
        ex.require(
            not {r["question"].strip() for r in rows}.intersection(
                r["question"].strip() for r in shots
            ),
            "Selected test / example exact overlap",
        )
        selected.extend(rows)
        examples.extend(shots)
        generation.extend(r["id"] for r in rows[: p["generation_per_category"]])
    return dict(
        plan_sha256=ex.plan_hash(p),
        rows=selected,
        examples=examples,
        generation_ids=generation,
        categories=categories,
        audit=dict(
            available_categories=dict(Counter(r["category"] for r in test)),
            selected_categories=dict(Counter(r["category"] for r in selected)),
            options=dict(Counter(len(r["options"]) for r in selected)),
            test_rows=len(test),
            validation_rows=len(validation),
            selected=len(selected),
            reasoning=len(generation),
            pretraining_contamination="UNKNOWN",
        ),
    )


def question(row):
    return (
        "Question:\n"
        + row["question"]
        + "\nOptions:\n"
        + "\n".join(f"{LETTERS[i]}. {option}" for i, option in enumerate(row["options"]))
    )


def prompts(row, examples):
    direct = question(row) + "\nReturn only the letter of the correct option."
    cot = (
        f"Solve the following {row['category']} multiple-choice problem. Explain your "
        "reasoning briefly, then finish with exactly 'The answer is (X)' where X is the "
        "chosen option letter. The following solved examples illustrate the format.\n\n"
    )
    for example in examples:
        cot += question(example) + "\n" + example["cot_content"] + "\n\n"
    cot += question(row)
    return direct, cot


def tokenize(panel, tokenizer, p):
    rows = []
    for row in panel["rows"]:
        examples = [e for e in panel["examples"] if e["category"] == row["category"]]
        ex.require(len(examples) == 5, "Five-shot context")
        direct, cot = prompts(row, examples)
        rendered = tokenizer.apply_chat_template(
            [dict(role="user", content=direct)], tokenize=False, add_generation_prompt=True
        )
        ids = tokenizer.encode(rendered, add_special_tokens=False)
        choices = []
        for letter in LETTERS[: len(row["options"])]:
            extended = tokenizer.encode(rendered + " " + letter, add_special_tokens=False)
            ex.require(
                extended[:-1] == ids and len(extended) == len(ids) + 1,
                "Stable one-token chat candidate",
            )
            choices.append(extended[-1])
        ex.require(len(set(choices)) == len(choices), "Distinct option tokens")
        item = dict(row, direct_prompt=direct, input_ids=ids, choice_ids=choices)
        if row["id"] in panel["generation_ids"]:
            item.update(
                reasoning_prompt=cot,
                reasoning_ids=ev.encode_chat(tokenizer, cot),
                example_ids=[e["id"] for e in examples],
            )
        ex.require(0 < len(ids) <= p["max_prompt_tokens"], "Direct prompt bound; no truncation")
        ex.require(
            len(item.get("reasoning_ids", [])) <= p["max_prompt_tokens"],
            "Five-shot prompt bound; no shot reduction/truncation",
        )
        rows.append(item)
    return dict(
        plan_sha256=ex.plan_hash(p),
        rows=rows,
        generation_ids=panel["generation_ids"],
        audit=dict(
            panel["audit"],
            max_direct_tokens=max(len(r["input_ids"]) for r in rows),
            max_reasoning_tokens=max(len(r.get("reasoning_ids", [])) for r in rows),
        ),
        tokenizer=dict(chat_template=tokenizer.chat_template, eos=tokenizer.eos_token_id),
    )


def extract(text, count):
    """Only explicit final-answer markers; conflicting or out-of-range => unparsed.

    No bare-letter guessing and no random replacement, including on capped answers.
    """
    values = re.findall(
        r"\b(?:the\s+)?answer(?:\s+is\s*|\s*:\s*)\(?([A-J])\)?\b", text, flags=re.IGNORECASE
    )
    values = [v.upper() for v in values]
    if not values or len(set(values)) != 1 or values[0] not in LETTERS[:count]:
        return dict(prediction=None, parsed=False, markers=values)
    return dict(prediction=LETTERS.index(values[0]), parsed=True, markers=values)


def transitions(base, candidate):
    ex.require(set(base) == set(candidate), "Complete paired IDs")
    groups = {k: [] for k in ("both_correct", "base_only", "candidate_only", "both_wrong")}
    for key in sorted(base):
        a, b = base[key], candidate[key]
        ex.require(type(a) is bool and type(b) is bool, "Explicit correctness booleans")
        name = (
            "both_correct"
            if a and b
            else "base_only"
            if a
            else "candidate_only"
            if b
            else "both_wrong"
        )
        groups[name].append(key)
    return dict(
        n=len(base),
        counts={k: len(v) for k, v in groups.items()},
        ids=groups,
        net_correct=sum(candidate.values()) - sum(base.values()),
    )


def download_panel(output, cache, p):
    import certifi
    import pyarrow.parquet as pq

    ex.require(not output.exists() and not cache.exists(), "Fresh download destinations")
    cache.mkdir(parents=True)
    source, data = {}, {}
    ctx = ssl.create_default_context(cafile=certifi.where())
    for split in ("test", "validation"):
        pin = p["dataset"][split]
        url = (
            f"https://huggingface.co/datasets/{p['dataset']['id']}/resolve/"
            f"{p['dataset']['revision']}/{pin['file']}"
        )
        with urllib.request.urlopen(url, context=ctx, timeout=120) as stream:
            body = stream.read()
        ex.require(
            len(body) == pin["bytes"] and hashlib.sha256(body).hexdigest() == pin["sha256"],
            "Pinned parquet bytes",
        )
        with (cache / f"{split}.parquet").open("xb") as stream:
            stream.write(body)
        data[split] = pq.read_table(io.BytesIO(body)).to_pylist()
        ex.require(len(data[split]) == pin["rows"], "Source split count")
        source[split] = dict(url=url, **pin)
    panel = select(data["test"], data["validation"], p)
    output.mkdir(parents=True)
    ex.write_gz(output / "PANEL.json.gz", panel)
    ex.write_new(
        output / "MANIFEST.json",
        dict(
            plan_sha256=ex.plan_hash(p),
            source=source,
            files=ex.manifest(output),
            audit=panel["audit"],
            selection_source=ex.digest(Path(__file__)),
        ),
    )
    return panel["audit"]


def load_panel(p):
    manifest = ex.read(ROOT / p["panel_manifest"])
    ex.require(
        manifest["plan_sha256"] == ex.plan_hash(p)
        and manifest["selection_source"] == ex.digest(Path(__file__)),
        "Frozen panel source",
    )
    path = ROOT / p["panel"]
    ex.require(ex.digest(path) == manifest["files"][path.name]["sha256"], "Panel bytes")
    panel = ex.read_gz(path)
    ex.require(panel["plan_sha256"] == ex.plan_hash(p), "Panel plan")
    return panel, manifest


def tokenize_panel(output, p):
    ex.offline_environment()
    from transformers import AutoTokenizer

    backbone = ex.read(ROOT / "configs/v22/FULL_FT_RECOVERY_01.json")["backbone"]
    tokenizer = AutoTokenizer.from_pretrained(
        backbone["repository"],
        revision=backbone["revision"],
        local_files_only=True,
        trust_remote_code=False,
    )
    ex.require(tokenizer.eos_token_id == 2, "Pinned EOS")
    panel, manifest = load_panel(p)
    data = tokenize(panel, tokenizer, p)
    output.mkdir(parents=True, exist_ok=False)
    ex.write_gz(output / "INPUTS.json.gz", data)
    ex.write_new(
        output / "MANIFEST.json",
        dict(
            plan_sha256=ex.plan_hash(p),
            panel_manifest=manifest,
            audit=data["audit"],
            files=ex.manifest(output),
            tokenizer_revision=backbone["revision"],
            source={
                n: ex.digest(ROOT / n)
                for n in (
                    PLAN,
                    "scripts/v23_mmlu_pro.py",
                    "src/latent_workspace/native_evaluation.py",
                )
            },
        ),
    )
    return data["audit"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("download-panel", "tokenize"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path)
    a = parser.parse_args()
    p = ex.read(ROOT / PLAN)
    if a.command == "download-panel":
        ex.require(a.cache is not None, "Explicit new cache path")
        result = download_panel(a.output, a.cache, p)
    else:
        result = tokenize_panel(a.output, p)
    print(ex.canonical(result))


if __name__ == "__main__":
    main()
