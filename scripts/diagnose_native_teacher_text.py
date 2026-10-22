#!/usr/bin/env python3
"""Post-hoc text-contract diagnostics, not a changed teacher rubric or semantic judge."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import run_native_teacher_inspection as teacher  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402
from latent_workspace import world_bank as wb  # noqa: E402


def diagnose(items, outcomes):
    world, pairs, instructions = [], {}, []
    for i, (item, outcome) in enumerate(zip(items, outcomes, strict=True)):
        candidate = outcome.get("candidate")
        if not isinstance(candidate, dict) or not isinstance(candidate.get("question"), str):
            continue
        value = dict(
            panel_index=i + 1,
            row_id=item["row"]["row_id"],
            question=candidate["question"],
        )
        if item["kind"] == "world":
            value["exact_policy_prefix_retained"] = candidate["question"].startswith(wb.POLICY)
            value["abstention_literal_retained"] = "Not specified" in candidate["question"]
            world.append(value)
            pairs.setdefault(item["row"]["group_id"], []).append(value)
        else:
            value["original_query_retained"] = candidate["question"] == item["row"]["query"]
            instructions.append(value)
    paired = [p for p in pairs.values() if len(p) == 2]
    differing = [p for p in paired if p[0]["question"] != p[1]["question"]]
    return dict(
        scope="POST_HOC_TEXT_DIAGNOSTIC_NOT_A_CHANGED_RUBRIC_OR_APPROVAL",
        planned_items=len(items),
        world_text_candidates=len(world),
        world_missing_exact_policy_prefix=sum(not x["exact_policy_prefix_retained"] for x in world),
        world_missing_abstention_literal=sum(not x["abstention_literal_retained"] for x in world),
        complete_twin_pairs=len(paired),
        twin_pairs_with_different_question_text=len(differing),
        differing_pairs=differing,
        world_rows=world,
        instruction_text_candidates=len(instructions),
        instruction_query_changes=sum(not x["original_query_retained"] for x in instructions),
        instruction_rows=instructions,
        semantic_certifications=0,
        training_admissions=0,
        caveat="Literal absence does not by itself test paraphrased policy equivalence.",
    )


def composed_token_counts(rows, bank_tokens, teacher_tokens):
    original = {r["row_id"]: r for r in ex.read_gz(bank_tokens / "rows.json.gz")}
    generated = {r["row_id"]: r for r in ex.read_gz(teacher_tokens / "rows.json.gz")}
    counts = []
    for row in rows:
        base, text = original[row["row_id"]], generated[row["row_id"]]
        answer = text["answer_tokens_including_eos"]
        query = base["query_tokens_including_answer"] - base["answer_tokens_including_eos"] + answer
        counts.append(
            dict(
                row_id=row["row_id"],
                memory_tokens=base["memory_tokens"],
                query_tokens_including_answer=query,
                answer_tokens_including_eos=answer,
            )
        )
    return dict(
        method="Exact addition; the sealed counter separately encodes prompt and answer",
        bank_counts_sha256=ex.digest(bank_tokens / "rows.json.gz"),
        teacher_counts_sha256=ex.digest(teacher_tokens / "rows.json.gz"),
        rows=counts,
        total_supervised_tokens=sum(r["answer_tokens_including_eos"] for r in counts),
        max_memory_tokens=max(r["memory_tokens"] for r in counts),
        max_query_tokens_including_answer=max(r["query_tokens_including_answer"] for r in counts),
        outside_128_by_128=sum(
            r["memory_tokens"] > 128 or r["query_tokens_including_answer"] > 128 for r in counts
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--compose-output", type=Path)
    parser.add_argument("--bank-tokens", type=Path)
    parser.add_argument("--teacher-tokens", type=Path)
    args = parser.parse_args()
    teacher.verify(args.teacher, ex.read(ROOT / teacher.PLAN))
    items = ex.read(args.teacher / "INPUTS.json")
    outcomes = []
    for i in range(len(items)):
        path = args.teacher / "run" / f"outcome_{i:03d}.json"
        outcomes.append(ex.read(path) if path.exists() else {"status": "NOT_ATTEMPTED"})
    result = diagnose(items, outcomes)
    result["teacher_terminal_sha256"] = ex.digest(args.teacher / "run" / "FINISHED.json")
    if args.verify or args.output.exists():
        ex.require(ex.read(args.output) == result, "Post-hoc diagnostics differ")
    else:
        ex.write_new(args.output, result)
    if args.compose_output is not None:
        candidates = [
            wb.compose_teacher_candidate(outcome["candidate"], item)
            for item, outcome in zip(items, outcomes, strict=True)
            if outcome.get("checks", {}).get("structural_pass")
        ]
        derivative = dict(
            status="POST_HOC_DERIVATIVE_QUARANTINED_NOT_TRAINING_APPROVED",
            source_teacher_terminal_sha256=result["teacher_terminal_sha256"],
            source_function_sha256=ex.digest(ROOT / "src/latent_workspace/world_bank.py"),
            planned_items=len(items),
            composed_candidates=len(candidates),
            excluded_items=len(items) - len(candidates),
            teacher_generations_added=0,
            training_admissions=0,
            rows=candidates,
        )
        if args.bank_tokens is not None and args.teacher_tokens is not None:
            derivative["student_tokens"] = composed_token_counts(
                candidates, args.bank_tokens, args.teacher_tokens
            )
        if args.verify:
            ex.require(ex.read(args.compose_output) == derivative, "Derivative differs")
        else:
            ex.write_new(args.compose_output, derivative)
    print(ex.canonical({k: v for k, v in result.items() if not isinstance(v, list)}))


if __name__ == "__main__":
    main()
