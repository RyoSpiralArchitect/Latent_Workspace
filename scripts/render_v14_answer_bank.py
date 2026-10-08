#!/usr/bin/env python3
"""Render a closed qualitative bank without judging, generating, or overwriting.

All model, prompt, and judge prose is escaped HTML data. The human review sheet
has a separate deterministic identity key and never imports judge labels.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import re
from collections import Counter
from pathlib import Path

CONDITIONS = (
    "base",
    "base_inline",
    "legacy_semantic",
    "centered_semantic",
    "centered_zero",
    "centered_unrelated",
    "centered_twin",
)
COMPARISONS = ("legacy_semantic", "centered_semantic")
REGIMES = {
    "greedy": {"id": "greedy", "seed": 0, "temperature": 0.0},
    "sample211": {"id": "sample211", "seed": 211, "temperature": 0.7},
    "sample212": {"id": "sample212", "seed": 212, "temperature": 0.7},
}
DIMENSIONS = (
    "correctness",
    "instruction_following",
    "grounding",
    "coherence",
    "usefulness",
    "calibration",
)
HUMAN_FIELDS = [
    "pair_id",
    "case_id",
    "lane",
    "regime",
    "status",
    "winner",
    *[f"{dimension}_{side}" for side in ("A", "B") for dimension in DIMENSIONS],
    "evidence_A",
    "evidence_B",
    "notes",
    "reviewer",
    "reviewed_at",
]
CLAIMS = [
    "定性的な探索用バンクです。潜在的知能の向上、一般的優越、非劣性は未確立です。",
    "16問は独立16世界ではありません。関係8問は4世界の順逆対で、一般課題は8問です。",
    "同じ問題の3生成条件は独立した問題標本ではありません。",
    "一般課題だけが同じ必要情報を見せる比較です。関係課題の情報アクセス差とは分けて読みます。",
    "同一seed・共通乱数は生成を対応づけますが、文章差を意味的改善に変換する保証ではありません。",
    "length終了は未完了の可能性を残します。eos終了も課題達成や正しさを保証しません。",
    "LLM評価は誤り得る観察で、人間の評価ラベルではありません。人間評価は未記入です。",
]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pair_id(case_id, regime, condition):
    return hashlib.sha256(canonical([case_id, regime, condition])).hexdigest()[:20]


def pre(value):
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
    return "<pre>" + html.escape(value, quote=True) + "</pre>"


def details(label, body):
    return (
        "<details>\n<summary>"
        + html.escape(label, quote=True)
        + "</summary>\n\n"
        + body
        + "\n\n</details>"
    )


def validate(cases, bank):
    if cases.get("format") != "latent-workspace-v14-answer-bank-cases-v1":
        raise ValueError("Unknown cases format")
    if bank.get("format") != "latent-workspace-v14-answer-bank-v1":
        raise ValueError("Unknown bank format")
    rows = cases["cases"]
    indexed_cases = {case["id"]: case for case in rows}
    if len(rows) != 16 or len(indexed_cases) != 16:
        raise ValueError("Expected 16 unique cases")
    if Counter(case["lane"] for case in rows) != {"general": 8, "relation": 8}:
        raise ValueError("Unknown lane or incomplete 8/8 case split")
    for case in rows:
        if not re.fullmatch(r"[a-z0-9-]+", case["id"]):
            raise ValueError("Unsafe case identifier")
        for field in ("user_prompt", "memory_text", "twin_memory_text", "unrelated_memory_text"):
            if not isinstance(case[field], str) or not case[field]:
                raise ValueError("Missing case text")
        if not isinstance(case["reference"], dict) or not isinstance(case["rubric"], list):
            raise ValueError("Missing reference or rubric")
    indexed = {}
    for row in bank["rows"]:
        key = (row["case_id"], row["regime"], row["condition"])
        if key in indexed or key[0] not in indexed_cases:
            raise ValueError("Duplicate or unknown answer coordinate")
        if key[1] not in REGIMES or key[2] not in CONDITIONS:
            raise ValueError("Unknown regime or condition")
        if row["id"] != "__".join(key) or row["lane"] != indexed_cases[key[0]]["lane"]:
            raise ValueError("Answer identity or lane mismatch")
        if row["regime_parameters"] != REGIMES[key[1]]:
            raise ValueError("Sampling regime parameters changed")
        if row["finish_reason"] not in ("eos", "length"):
            raise ValueError("Unknown finish reason")
        if not isinstance(row["answer"], str) or not isinstance(row["rendered_prompt"], str):
            raise ValueError("Answer and rendered prompt must be text")
        if type(row["token_count"]) is not int or not 1 <= row["token_count"] <= 128:
            raise ValueError("Invalid token count")
        if len(row["generated_ids"]) != row["token_count"] or any(
            type(token) is not int or token < 0 for token in row["generated_ids"]
        ):
            raise ValueError("Generated token IDs do not match token count")
        indexed[key] = row
    expected = {
        (case_id, regime, condition)
        for case_id in indexed_cases
        for regime in REGIMES
        for condition in CONDITIONS
    }
    if set(indexed) != expected or len(bank["rows"]) != 336:
        raise ValueError("Incomplete 16 x 3 x 7 answer grid")
    return indexed_cases, indexed


def make_pairs(case_map, indexed):
    pairs = []
    for case_id in sorted(case_map):
        for regime in REGIMES:
            for comparison in COMPARISONS:
                pairs.append(
                    {
                        "pair_id": pair_id(case_id, regime, comparison),
                        "case_id": case_id,
                        "lane": case_map[case_id]["lane"],
                        "regime": regime,
                        "comparison": comparison,
                        "base": indexed[case_id, regime, "base"],
                        "workspace": indexed[case_id, regime, comparison],
                    }
                )
    # Sorting opaque IDs and alternating gives exactly 48 placements per side.
    for index, pair in enumerate(sorted(pairs, key=lambda pair: pair["pair_id"])):
        pair["A"] = pair["base"] if index % 2 == 0 else pair["workspace"]
        pair["B"] = pair["workspace"] if index % 2 == 0 else pair["base"]
    return sorted(pairs, key=lambda pair: (pair["case_id"], pair["pair_id"]))


def validate_judge(judge, pairs, bank_sha, cases_sha):
    if judge.get("format") != "latent-workspace-v14-answer-bank-judge-summary-v1":
        raise ValueError("Unknown judge format")
    if (judge["snapshot"]["bank_sha256"], judge["snapshot"]["cases_sha256"]) != (
        bank_sha,
        cases_sha,
    ):
        raise ValueError("Judge snapshot refers to different bank or cases")
    expected = {pair["pair_id"]: pair for pair in pairs}
    seen = set()
    for row in judge["pairs"]:
        if row["pair_id"] not in expected or row["pair_id"] in seen:
            raise ValueError("Unknown or duplicate judge pair")
        pair = expected[row["pair_id"]]
        seen.add(row["pair_id"])
        for field in ("case_id", "lane", "regime", "comparison"):
            if row[field] != pair[field]:
                raise ValueError("Judge pair coordinate mismatch")
        if (
            row["base_answer"] != pair["base"]["answer"]
            or row["workspace_answer"] != pair["workspace"]["answer"]
        ):
            raise ValueError("Judge answers differ from generation bank")
        identical = pair["base"]["answer"] == pair["workspace"]["answer"]
        if row["exact_identical"] is not identical:
            raise ValueError("Judge text-identity receipt disagrees")
        if row["judge_status"] not in (
            "not_judged_exact_identical",
            "missing_or_invalid_order",
            "order_consistent",
            "order_conflict",
        ) or row["order_consistent_preference"] not in (
            None,
            "base",
            "workspace",
            "tie",
            "uncertain",
        ):
            raise ValueError("Unknown judge status or preference label")
        observations = row["observations"]
        if len(observations) != 2 or {item["order"] for item in observations} != {"AB", "BA"}:
            raise ValueError("Judge orders are incomplete or duplicated")
        for item in observations:
            if item["request_id"] != row["pair_id"] + "-" + item["order"]:
                raise ValueError("Judge request identity mismatch")
            verdict = item["judgment"]
            if verdict is None:
                if item["status"] == "completed":
                    raise ValueError("Completed judgment has no verdict")
                continue
            if item["status"] != "completed" or verdict["winner"] not in (
                "A",
                "B",
                "tie",
                "uncertain",
            ):
                raise ValueError("Unknown judgment status or winner label")
            answer_sides = (
                (pair["base"], pair["workspace"])
                if item["order"] == "AB"
                else (
                    pair["workspace"],
                    pair["base"],
                )
            )
            for side, answer in zip(("A", "B"), answer_sides):
                if set(verdict["scores"][side]) != set(DIMENSIONS):
                    raise ValueError("Unknown judge score dimension")
                for score in verdict["scores"][side].values():
                    if score is not None and (type(score) is not int or score not in range(5)):
                        raise ValueError("Invalid ordinal score")
                quotes = verdict["quoted_evidence"][side]
                if not isinstance(quotes, list) or any(
                    not isinstance(quote, str) or not quote or quote not in answer["answer"]
                    for quote in quotes
                ):
                    raise ValueError("Judge quotation is not answer evidence")
    if seen != set(expected) or judge["pair_count"] != 96:
        raise ValueError("Incomplete judge pair grid")


def answer_bank(case_map, indexed):
    blocks = [
        "# V14 回答バンク\n",
        "全336回答を省略せず掲載します。条件名が見える資料です。"
        "先にブラインド評価する場合は HUMAN_REVIEW.md から読んでください。\n",
    ]
    for case_id, case in sorted(case_map.items()):
        body = [
            "質問",
            pre(case["user_prompt"]),
            "元memory",
            pre(case["memory_text"]),
            "反実仮想memory",
            pre(case["twin_memory_text"]),
            "無関係memory",
            pre(case["unrelated_memory_text"]),
        ]
        for regime in REGIMES:
            entries = []
            for condition in CONDITIONS:
                row = indexed[case_id, regime, condition]
                content = "\n\n".join(
                    [
                        "回答",
                        pre(row["answer"]),
                        f"終了: {row['finish_reason']} / 生成token数: {row['token_count']}",
                        "実際に渡したchat prompt",
                        pre(row["rendered_prompt"]),
                    ]
                )
                entries.append(details(condition, content))
            body.append(details(regime, "\n\n".join(entries)))
        blocks.append(details(case_id + " / " + case["lane"], "\n\n".join(body)))
    return "\n\n".join(blocks) + "\n"


def human_review(case_map, pairs):
    blocks = [
        "# V14 人間評価用シート\n",
        "人間評価は pending（未実施）です。下記A/Bのモデル名・学習条件は伏せています。"
        "HUMAN_KEY.json と ANSWER_BANK.md、JUDGE_REVIEW.md は、"
        "最初の評価を終えるまで開かないでください。",
        "human_scores.csv の各行を pair_id で対応づけます。winner は A / B / tie / uncertain、"
        "各観点は 0（重大な不適合）〜4（よい）、評価不能は空欄のままにしてください。"
        "根拠となる回答中の引用と気づきを残し、"
        "評価した行だけ status を completed に変えてください。"
        "モデル評価を人間ラベルへ自動転記することはありません。",
        "観点: correctness（正しさ）、instruction_following（指示への適合）、grounding（根拠）、"
        "coherence（一貫性）、usefulness（有用性）、calibration（確信の適切さ）。",
        "関係課題は情報アクセスが等しくありません。参照世界への正しさと、見えていない情報を"
        "勝手に断定しない姿勢を区別してください。一般課題はどちらにも必要情報が見えています。",
        "各caseに6対、全96対です。同じ問題の生成違いは独立した問題ではありません。"
        "length終了は打ち切りの可能性を含みます。条件の盲検化は表示上のもので、暗号学的な秘匿ではありません。",
    ]
    for case_id, case in sorted(case_map.items()):
        content = [
            "質問",
            pre(case["user_prompt"]),
            "評価用参照（唯一の言い回しを強制するものではありません）",
            pre(case["reference"]["original"]),
        ]
        if case["lane"] == "relation":
            content += [
                "評価用世界情報（回答時に両方が参照できたとは限りません）",
                pre(case["memory_text"]),
            ]
        content += ["課題別rubric", pre(case["rubric"])]
        for pair in (pair for pair in pairs if pair["case_id"] == case_id):
            columns = []
            for side in ("A", "B"):
                row = pair[side]
                columns.append(
                    "<td>"
                    + pre(row["answer"])
                    + "<p>終了: "
                    + row["finish_reason"]
                    + " / tokens: "
                    + str(row["token_count"])
                    + "</p></td>"
                )
            table = (
                "<table>\n<tr><th>A</th><th>B</th></tr>\n<tr>"
                + "".join(columns)
                + "</tr>\n</table>"
            )
            content.append(details(pair["pair_id"] + " / " + pair["regime"], table))
        blocks.append(details(case_id + " / " + case["lane"], "\n\n".join(content)))
    return "\n\n".join(blocks) + "\n"


def judge_review(judge):
    blocks = [
        "# V14 LLM評価の観察\n",
        "人間評価とは独立した、誤り得る観察です。人間の初回評価が終わるまでは読まないことを推奨します。",
    ]
    if judge is None:
        blocks += ["状態: NOT_PROVIDED。判定も点数も作成していません。"]
    else:
        blocks += [
            "AB/BAの両順序を省略せず記録します。ここでのA/BはLLMへの提示順で、HUMAN_REVIEW.mdのA/Bとは別です。",
            pre(
                {
                    "pair_count": judge["pair_count"],
                    "status_counts": dict(Counter(row["judge_status"] for row in judge["pairs"])),
                }
            ),
        ]
        for pair in sorted(judge["pairs"], key=lambda row: (row["case_id"], row["pair_id"])):
            content = [
                pre(
                    {
                        field: pair[field]
                        for field in (
                            "case_id",
                            "lane",
                            "regime",
                            "comparison",
                            "exact_identical",
                            "judge_status",
                            "order_consistent_preference",
                        )
                    }
                )
            ]
            for item in sorted(pair["observations"], key=lambda item: item["order"]):
                mapping = (
                    "A=base / B=workspace" if item["order"] == "AB" else "A=workspace / B=base"
                )
                content.append(details(item["order"] + " / " + mapping, pre(item)))
            blocks.append(details(pair["pair_id"], "\n\n".join(content)))
    return "\n\n".join(blocks) + "\n"


def draft_summary(pairs, indexed, judge):
    comparison_counts = {}
    for lane in ("general", "relation"):
        for comparison in COMPARISONS:
            group = [
                pair for pair in pairs if pair["lane"] == lane and pair["comparison"] == comparison
            ]
            comparison_counts[lane + "/" + comparison] = {
                "pairs": len(group),
                "identical_text_pairs": sum(
                    pair["base"]["answer"] == pair["workspace"]["answer"] for pair in group
                ),
                "identical_token_pairs": sum(
                    pair["base"]["generated_ids"] == pair["workspace"]["generated_ids"]
                    for pair in group
                ),
            }
    return {
        "format": "latent-workspace-v14-answer-bank-render-summary-v1",
        "status": "DESCRIPTIVE_ARTIFACT_NOT_QUALITY_VERDICT",
        "semantic_promotion": False,
        "human_evaluation": "PENDING",
        "human_completed_labels": 0,
        "judge_provided": judge is not None,
        "non_regression": "NOT_ESTABLISHED",
        "denominators": {
            "cases": 16,
            "relation_worlds": 4,
            "general_tasks": 8,
            "regimes": 3,
            "conditions": 7,
            "answers": 336,
            "human_pairs": 96,
        },
        "finish_counts": dict(
            sorted(Counter(row["finish_reason"] for row in indexed.values()).items())
        ),
        "comparison_counts": comparison_counts,
        "claim_boundary": CLAIMS,
    }


def render(bank_path, cases_path, output, judge_path=None):
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("Output already exists; human annotations must not be overwritten")
    bank_path, cases_path = Path(bank_path), Path(cases_path)
    bank, cases = json.loads(bank_path.read_text()), json.loads(cases_path.read_text())
    case_map, indexed = validate(cases, bank)
    pairs = make_pairs(case_map, indexed)
    judge = json.loads(Path(judge_path).read_text()) if judge_path else None
    if judge is not None:
        validate_judge(judge, pairs, digest(bank_path), digest(cases_path))
    key = {
        "format": "latent-workspace-v14-human-review-key-v1",
        "human_evaluation": "PENDING",
        "mapping": [
            {field: pair[field] for field in ("pair_id", "case_id", "lane", "regime")}
            | {
                side: {"condition": pair[side]["condition"], "answer_id": pair[side]["id"]}
                for side in ("A", "B")
            }
            for pair in pairs
        ],
    }
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=HUMAN_FIELDS, lineterminator="\n")
    writer.writeheader()
    for pair in pairs:
        writer.writerow(
            {field: pair[field] for field in ("pair_id", "case_id", "lane", "regime")}
            | {"status": "pending"}
        )
    summary = draft_summary(pairs, indexed, judge)
    summary["inputs"] = {
        "bank_sha256": digest(bank_path),
        "cases_sha256": digest(cases_path),
        "judge_sha256": digest(Path(judge_path)) if judge_path else None,
    }
    intro = (
        "# V14 回答バンク：探索用資料\n\n"
        + "\n\n".join(
            [
                "336回答・96比較対を、選別せず残した資料です。人間評価は未実施です。",
                "先に [HUMAN_REVIEW.md](HUMAN_REVIEW.md) を読み、"
                "[human_scores.csv](human_scores.csv) に記入できます。"
                " 条件対応は [HUMAN_KEY.json](HUMAN_KEY.json) に分離しています。",
                "全条件の回答は [ANSWER_BANK.md](ANSWER_BANK.md)、"
                "LLMの観察は [JUDGE_REVIEW.md](JUDGE_REVIEW.md) にあります。",
                "## 計数（品質評価ではありません）\n\n"
                + pre(
                    {
                        "denominators": summary["denominators"],
                        "finish_counts": summary["finish_counts"],
                        "comparison_counts": summary["comparison_counts"],
                    }
                ),
                "## 解釈の境界\n\n" + "\n".join("- " + claim for claim in CLAIMS),
            ]
        )
        + "\n"
    )
    documents = {
        "README.md": intro,
        "ANSWER_BANK.md": answer_bank(case_map, indexed),
        "HUMAN_REVIEW.md": human_review(case_map, pairs),
        "JUDGE_REVIEW.md": judge_review(judge),
        "human_scores.csv": stream.getvalue(),
        "HUMAN_KEY.json": json.dumps(key, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        "SUMMARY.json": json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    }
    output.mkdir(parents=True, exist_ok=False)
    for filename, content in documents.items():
        with (output / filename).open("x", encoding="utf-8", newline="") as handle:
            handle.write(content)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--judge", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(render(args.bank, args.cases, args.output, args.judge), ensure_ascii=False))


if __name__ == "__main__":
    main()
