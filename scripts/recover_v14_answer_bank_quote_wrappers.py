#!/usr/bin/env python3
"""Explicit posthoc, ASCII-quote-wrapper-only recovery; never primary evidence.

This script does not call an API or alter primary artifacts. Its deterministic
supplement is a separately labelled rendering of otherwise unchanged judgments.
"""

from __future__ import annotations

import argparse
import copy
import json
from collections import Counter
from pathlib import Path

import judge_v14_answer_bank as judge
import render_v14_answer_bank as renderer
import verify_v14_answer_bank_judge as verifier

REPO = Path(__file__).resolve().parents[1]
STATUS = "POSTHOC_FORMAT_RECOVERY_NOT_PRIMARY_NOT_GOLD"
RULE = {
    "id": "one_ascii_double_quote_wrapper_pair_v1",
    "eligible_primary_status": "invalid_judgment",
    "character": "U+0022",
    "operation": "Remove exactly one surrounding ASCII double-quote pair only when the original "
                 "quote fails containment and the nonempty remainder is an exact substring of "
                 "the assigned answer. Keep already-valid quotes unchanged.",
    "forbidden": ["whitespace normalization", "punctuation normalization", "ellipsis repair",
                  "recursive wrapper removal", "non-ASCII wrapper removal", "other field edits"],
    "acceptance": "The entire original frozen validate_judgment must pass after transformation.",
    "selection_timing": "Rule declared after initial invalid-quote observations, before the "
                        "primary 28-request run completed; explicitly posthoc.",
}


def recover_judgment(raw, body):
    """Return a full audit of one attempt, without mutating either argument."""
    result = {"recovered": False, "quote_changes": [], "before_judgment": None,
              "after_judgment": None, "all_other_judgment_fields_unchanged": None}
    if raw.get("status") != "completed" or raw.get("model") != body["model"]:
        return {**result, "outcome": "unsupported_response_state"}
    outputs = [item.get("text", "") for output in raw.get("output", [])
               for item in output.get("content", []) if item.get("type") == "output_text"]
    if len(outputs) != 1:
        return {**result, "outcome": "output_text_count_not_one"}
    try:
        before = json.loads(outputs[0])
        data = json.loads(body["input"][0]["content"][0]["text"])
    except (ValueError, TypeError, KeyError):
        return {**result, "outcome": "unparseable_structured_output"}
    result["before_judgment"] = before
    if not isinstance(before, dict) or not isinstance(before.get("quoted_evidence"), dict):
        return {**result, "outcome": "unsupported_evidence_structure"}
    after = copy.deepcopy(before)
    for side in ("A", "B"):
        quotes = after["quoted_evidence"].get(side)
        answer = data["answer_" + side]
        if not isinstance(quotes, list):
            continue  # The unchanged full validator will reject malformed evidence.
        for index, quote in enumerate(quotes):
            if not isinstance(quote, str) or quote in answer:
                continue
            if len(quote) >= 3 and quote.startswith('"') and quote.endswith('"'):
                inner = quote[1:-1]
                if inner and inner in answer:
                    after["quoted_evidence"][side][index] = inner
                    result["quote_changes"].append({
                        "side": side, "index": index, "before": quote, "after": inner,
                        "removed_characters": ["U+0022", "U+0022"],
                        "original_is_answer_substring": False,
                        "recovered_is_exact_answer_substring": True,
                    })
    before_other = {key: value for key, value in before.items() if key != "quoted_evidence"}
    after_other = {key: value for key, value in after.items() if key != "quoted_evidence"}
    if before_other != after_other:
        raise AssertionError("Recovery modified a non-quote judgment field")
    result.update(after_judgment=after, all_other_judgment_fields_unchanged=True,
                  before_nonquote_fields_sha256=judge.sha256(before_other),
                  after_nonquote_fields_sha256=judge.sha256(after_other))
    if not result["quote_changes"]:
        return {**result, "outcome": "no_permitted_wrapper_change"}
    try:
        judge.validate_judgment(after, data["answer_A"], data["answer_B"])
    except (ValueError, TypeError, KeyError):
        return {**result, "outcome": "still_invalid_after_wrapper_only_change"}
    return {**result, "recovered": True, "outcome": "recovered_ascii_wrapper_only"}


def build_supplement(bank_path, plan_path, cases_path, judge_dir):
    bank_path, plan_path, cases_path, judge_dir = map(
        Path, (bank_path, plan_path, cases_path, judge_dir)
    )
    verification = verifier.verify(bank_path, plan_path, cases_path, judge_dir)
    if not verification["mechanical_receipt_closure"]:
        raise ValueError("Primary receipt closure must be complete before posthoc recovery")
    primary_path = judge_dir / "SUMMARY.json"
    primary = judge.load_json(primary_path)
    pairs = judge.load_json(judge_dir / "PAIRS.json")["pairs"]
    prepared = judge.load_json(judge_dir / "PREPARED_REQUESTS.json")["requests"]
    receipts, attempts, recovered_ids = [], [], []
    for request in prepared:
        filename = request["request_id"] + ".json"
        receipt = judge.load_json(judge_dir / "requests" / filename)
        copied = copy.deepcopy(receipt)
        if receipt["observation"]["status"] == "invalid_judgment":
            response_path = judge_dir / "responses" / filename
            audit = recover_judgment(judge.load_json(response_path), request["body"])
            attempt = {
                "request_id": request["request_id"], "pair_id": request["pair_id"],
                "order": request["order"], "raw_response_sha256": judge.file_sha(response_path),
                "primary_observation_status": "invalid_judgment", **audit,
            }
            attempts.append(attempt)
            if audit["recovered"]:
                observation = copied["observation"]
                observation["primary_error"] = observation.pop("error", None)
                observation.update(status="completed", judgment=audit["after_judgment"],
                                   primary_status="invalid_judgment", posthoc_recovered=True)
                recovered_ids.append(request["request_id"])
        receipts.append(copied)
    supplemental = judge.summarize(pairs, receipts)
    recovered_set = set(recovered_ids)
    for pair in supplemental["pairs"]:
        for observation in pair["observations"]:
            if observation["request_id"] in recovered_set:
                observation.update(primary_status="invalid_judgment", posthoc_recovered=True)
    after_counts = Counter(receipt["observation"]["status"] for receipt in receipts)
    supplemental.update(
        format="latent-workspace-v14-answer-bank-quote-wrapper-recovery-v1", status=STATUS,
        primary_summary_sha256=judge.file_sha(primary_path),
        recovery_script_sha256=judge.file_sha(Path(__file__)), rule=RULE,
        snapshot=primary["snapshot"], recovery_attempts=attempts,
        recovered_request_ids=recovered_ids,
        primary_valid_judgments=verification["valid_judgments"],
        supplemental_valid_judgments=after_counts["completed"],
        primary_observation_status_counts=verification["observation_status_counts"],
        supplemental_observation_status_counts=dict(sorted(after_counts.items())),
        primary_artifacts_modified=False, new_api_requests=0,
        actual_billed_cost_usd=None,
    )
    supplemental["claim_boundary"] = [
        "POSTHOC supplement only; primary invalid judgments and denominators remain unchanged.",
        "No new LLM verdict was requested and no score, winner or rationale was edited.",
        "Recovered quote formatting does not validate the judge's reasoning or establish quality.",
        *supplemental["claim_boundary"],
    ]
    return supplemental


def render_review(summary):
    preface = [
        "# 補足：引用符ラッパーだけの事後回復\n",
        f"状態: **{STATUS}**。これは一次評価ではなく、正式集計への上書きもありません。",
        f"一次評価で有効: {summary['primary_valid_judgments']}/{summary['request_receipt_count']}。"
        f"この補足で有効: {summary['supplemental_valid_judgments']}/"
        f"{summary['request_receipt_count']}。"
        f"回復した要求: {len(summary['recovered_request_ids'])}件。",
        "原回答に存在しない引用文字列についてのみ、外側のASCII二重引用符を正確に1対除き、"
        "残りが原回答の完全一致部分文字列になる場合に限って修正しました。"
        "空白・句読点・省略記号・曲がった引用符などは修正していません。"
        "全体の元validatorを再通過したものだけを補足として集計しています。",
        "点数、選好、説明、そのほかの判定内容は変更していません。"
        "一次評価の不正引用・欠測はそのままです。新しいAPI要求や人間評価はありません。",
        "元SUMMARY SHA-256: " + summary["primary_summary_sha256"],
        renderer.details("回復規則と一次／補足の分母", renderer.pre({
            "rule": summary["rule"],
            "primary_observation_status_counts": summary["primary_observation_status_counts"],
            "supplemental_observation_status_counts": summary[
                "supplemental_observation_status_counts"
            ],
        })),
    ]
    for attempt in summary["recovery_attempts"]:
        preface.append(renderer.details(attempt["request_id"] + " / " + attempt["outcome"],
                                        renderer.pre(attempt)))
    return "\n\n".join(preface) + "\n\n---\n\n" + renderer.judge_review(summary)


def recover(bank_path, plan_path, cases_path, judge_dir, output):
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("Supplement output exists; refusing overwrite")
    summary = build_supplement(bank_path, plan_path, cases_path, judge_dir)
    review = render_review(summary)
    output.mkdir(parents=True, exist_ok=False)
    judge.write_json(output / "SUMMARY.json", summary, exclusive=True)
    with (output / "REVIEW.md").open("x", encoding="utf-8") as stream:
        stream.write(review)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=REPO / "data/v14_answer_bank/cases.json")
    parser.add_argument("--judge-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = recover(args.bank, args.plan, args.cases, args.judge_dir, args.output)
    print(json.dumps({key: result[key] for key in (
        "status", "primary_valid_judgments", "supplemental_valid_judgments",
        "recovered_request_ids", "primary_summary_sha256",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
