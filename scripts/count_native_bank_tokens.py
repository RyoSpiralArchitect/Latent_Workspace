#!/usr/bin/env python3
"""Offline student-token denominators; counts, not truncation or training admission."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from latent_workspace import execution as ex  # noqa: E402


def select_rows(bank, teacher=None):
    if teacher is None:
        return (
            ex.read_gz(bank / "world_rows.json.gz") + ex.read(bank / "instruction_seeds.json"),
            {},
        )
    rows, statuses, excluded = [], Counter(), []
    for i, item in enumerate(ex.read(teacher / "INPUTS.json")):
        path = teacher / "run" / f"outcome_{i:03d}.json"
        outcome = ex.read(path) if path.exists() else {"status": "NOT_ATTEMPTED"}
        statuses[outcome["status"]] += 1
        candidate = outcome.get("candidate")
        if not isinstance(candidate, dict) or not all(
            isinstance(candidate.get(k), str) and candidate[k] for k in ("question", "answer")
        ):
            excluded.append(i)
            continue
        rows.append(
            {
                **item["row"],
                "query": candidate["question"],
                "answer": candidate["answer"],
            }
        )
    ex.require(rows, "No text candidates available for token counting")
    return rows, dict(
        teacher_request_statuses=dict(statuses),
        teacher_indices_without_countable_text=excluded,
        teacher_terminal_sha256=ex.digest(teacher / "run" / "FINISHED.json"),
        includes_structure_fail_if_text_present=True,
        semantic_equivalence="UNREVIEWED",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--teacher", type=Path)
    args = parser.parse_args()
    ex.offline_environment()
    from transformers import AutoTokenizer

    backbone = ex.read(ROOT / "configs/v1_0/NATIVE_7B_CANARY_RECOVERY_01.json")["backbone"]
    tokenizer = AutoTokenizer.from_pretrained(
        backbone["repository"],
        revision=backbone["revision"],
        local_files_only=True,
        trust_remote_code=False,
    )
    rows, selection = select_rows(args.bank, args.teacher)
    counts, totals, overs = [], Counter(), Counter()
    for row in rows:
        prompt = tokenizer.apply_chat_template(
            [{"role": "user", "content": row["query"]}],
            tokenize=True,
            add_generation_prompt=True,
            return_dict=False,
        )
        answer = tokenizer.encode(" " + row["answer"], add_special_tokens=False) + [
            tokenizer.eos_token_id
        ]
        memory = tokenizer.encode(row["memory"], add_special_tokens=False) if row["memory"] else []
        value = dict(
            row_id=row["row_id"],
            split=row["split"],
            family=row["family"],
            memory_tokens=len(memory),
            query_tokens_including_answer=len(prompt) + len(answer),
            answer_tokens_including_eos=len(answer),
        )
        value["within_tested_axes"] = len(memory) <= 128 and len(prompt) + len(answer) <= 128
        counts.append(value)
        totals[f"{row['split']}/{row['family']}"] += len(answer)
        if not value["within_tested_axes"]:
            overs[f"{row['split']}/{row['family']}"] += 1
    result = dict(
        **selection,
        backbone=backbone,
        bank_manifest_sha256=ex.digest(args.bank / "MANIFEST.json"),
        rows=len(rows),
        total_supervised_tokens=sum(totals.values()),
        supervised_tokens_by_split_family=dict(totals),
        outside_128_by_128=dict(overs),
        max_memory_tokens=max(r["memory_tokens"] for r in counts),
        max_query_tokens_including_answer=max(r["query_tokens_including_answer"] for r in counts),
        max_answer_tokens_including_eos=max(r["answer_tokens_including_eos"] for r in counts),
        truncations=0,
        training_admissions=0,
        resource_pass_not_implied=True,
    )
    args.output.mkdir(parents=True, exist_ok=False)
    ex.write_gz(args.output / "rows.json.gz", counts)
    ex.write_new(args.output / "SUMMARY.json", result)
    print(ex.canonical(result))


if __name__ == "__main__":
    main()
