#!/usr/bin/env python3
"""Offline comparison of new Mistral capacity method against sealed older judges."""

from __future__ import annotations

import argparse
import copy
import html
import json
import statistics
from collections import Counter
from pathlib import Path

import run_v14_budget_panel as run
import seal_v14_judge_extension as previous_seal
import summarize_v14_judge_extension as previous
import summarize_v14_judge_panel as original

REPO = run.REPO
BUNDLE = "provenance/pilots/v14_judge_capacity_20261009"
METHODS = ("openai", "gemini", "mistral_4k", "mistral_enlarged")


def aggregate(plan_path, *, root=REPO):
    root, plan_path = Path(root).resolve(), Path(plan_path).resolve()
    old_receipt = previous_seal.verify(root)
    old = previous.load(root / previous.BUNDLE / "analysis/SUMMARY.json")
    plan = run.prior.load_json(plan_path)
    config, _, pairs, cases = run.validate_plan(plan, "mistral", 0)
    cells_root = root / BUNDLE / "cells" / plan["method_id"]
    if cells_root.exists():
        if cells_root.is_symlink() or not cells_root.is_dir():
            raise ValueError("Nonregular cells root")
        if {p.name for p in cells_root.iterdir()} - {f"r{r}" for r in range(5)}:
            raise ValueError("Unexpected duplicate cell")
    cells = [
        previous.verify_cell(run, plan_path, "mistral", r, cells_root / f"r{r}") for r in range(5)
    ]
    fresh = previous.provider_report("mistral", cells, {})
    fresh.update(
        evidence_origin="new_enlarged_budget_method", method_id=plan["method_id"], config=config
    )
    providers = {}
    for label, key in (("openai", "openai"), ("gemini", "gemini"), ("mistral_4k", "mistral")):
        providers[label] = {
            **copy.deepcopy(old["providers"][key]),
            "evidence_origin": "previous_sealed_evidence_referenced_not_rerun",
        }
    providers["mistral_enlarged"] = fresh
    results = []
    for pair in pairs:
        earlier = next(p for p in old["pairs"] if p["pair_id"] == pair["pair_id"])
        reports = {
            label: copy.deepcopy(earlier["providers"][key])
            for label, key in (
                ("openai", "openai"),
                ("gemini", "gemini"),
                ("mistral_4k", "mistral"),
            )
        }
        reports["mistral_enlarged"] = original.describe_repeats(
            [original.normalized_repeat(cell, pair) for cell in cells]
        )
        results.append(
            {
                **pair,
                "constraint_checks": original.constraint_checks(pair),
                "world_task_cluster": earlier["world_task_cluster"],
                "methods": reports,
            }
        )
    for method, report in providers.items():
        changed = [p for p in results if not p["calibration_only"]]
        controls = [p for p in results if p["calibration_only"]]
        report["changed_stable_counts"] = {
            value: sum(p["methods"][method]["stable_all_five_preference"] == value for p in changed)
            for value in (*original.PREFERENCES, None)
        }
        # JSON object keys must remain deterministic and readable after reconstruction.
        report["changed_stable_counts"]["nonstable"] = report["changed_stable_counts"].pop(None)
        report["control_stable_ties"] = sum(
            p["methods"][method]["stable_all_five_preference"] == "tie" for p in controls
        )
    return {
        "format": "latent-workspace-v14-budget-panel-summary-v1",
        "status": "NEW_METHOD_COMPLETE_STRICT_RECEIPTS_NOT_GOLD"
        if fresh["all_five_cells_receipt_closed"] and fresh["valid_judgments"] == 140
        else "NEW_METHOD_PARTIAL_OR_INVALID_RECEIPTS_NOT_GOLD",
        "newly_planned_requests": 140,
        "historical_planned_requests": 420,
        "historical_reserved_requests": sum(
            old["providers"][p]["reserved_requests"] for p in old["providers"]
        ),
        "previous_validation_recomputed": old_receipt["status"],
        "inputs": {
            "plan": {
                "path": str(plan_path.relative_to(root)),
                "sha256": run.prior.file_sha(plan_path),
            },
            "previous_index_sha256": run.prior.file_sha(root / previous.BUNDLE / "INDEX.json"),
            "previous_summary_sha256": run.prior.file_sha(
                root / previous.BUNDLE / "analysis/SUMMARY.json"
            ),
            "aggregator_sha256": run.prior.file_sha(Path(__file__)),
        },
        "providers": providers,
        "pairs": results,
        "cases": list(cases.values()),
        "selection_counts": old["selection_counts"],
        "claude": {"status": "SKIPPED_BY_USER_AFTER_METADATA_401", "study_requests": 0},
        "winner": "none",
        "human_evaluation": "PENDING",
        "non_regression": "NOT_ESTABLISHED",
        "semantic_promotion": False,
        "pooled_provider_winner": None,
        "claim_boundary": [
            "Old Mistral4k and the enlarged-cap method remain separate; votes are never pooled.",
            "OpenAI/Gemini and old Mistral receipts are referenced without new API calls.",
            "All ten changed pairs and four identical controls, no outcome-conditioned selection.",
            "Seven changed prompts form six task/world clusters; repeated calls are not new tasks.",
            "Five-repeat stability requires all valid AB/BA pairs to agree on one preference.",
            "Missing, refused, invalid and order-conflicting results are not losses or ties.",
            "No JSON/quote repair, majority gold, or latent-capability inference from prose.",
            "Different providers/settings/token budgets do not isolate a family-only effect.",
            "Exact returned API model ID does not establish immutable remote weights.",
            "Valid syntax/quotes, control ties and receipt closure do not prove judge correctness.",
            "Quality, non-regression, human agreement and memory causality remain unestablished.",
        ],
    }


def render(summary):
    pre, fold = original.pre, original.fold
    cases = {c["id"]: c for c in summary["cases"]}
    blocks = [
        "# V14: enlarged-cap Mistral / OpenAI / Gemini\n",
        "新Mistralを別methodとして追加。旧4kの失敗は別欄に保持し、多数決を正解にしません。",
        pre({k: summary[k] for k in ("status", "newly_planned_requests", "claude")}),
    ]
    for method, report in summary["providers"].items():
        blocks += [f"## {method}\n", fold("分母・欠測・費用・反復", pre(report))]
    headers = ["case / regime", "区分", *METHODS]
    table = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for pair in summary["pairs"]:
        values = [
            pair["case_id"] + " / " + pair["regime"],
            "同文control" if pair["calibration_only"] else "変更組",
        ]
        for method in METHODS:
            report = pair["methods"][method]
            values.append(
                " · ".join(original.repeat_label(row) for row in report["replicates"])
                + " / stable="
                + str(report["stable_all_five_preference"])
            )
        table.append("| " + " | ".join(html.escape(v) for v in values) + " |")
    blocks += ["## 14組の一覧\n", "各欄はr0→r4。conflictはAB/BA不一致。", "\n".join(table)]
    for pair in summary["pairs"]:
        body = [
            "質問",
            pre(cases[pair["case_id"]]["user_prompt"]),
            "Base",
            pre(pair["base_answer"]),
            "Workspace",
            pre(pair["workspace_answer"]),
            "機械的制約チェック（票は変更しない）",
            pre(pair["constraint_checks"]),
        ]
        for method, report in pair["methods"].items():
            body += [f"### {method}\n", pre({k: v for k, v in report.items() if k != "replicates"})]
            for row in report["replicates"]:
                body.append(
                    fold(
                        f"r{row['replicate']} / {row['judge_status']} / "
                        f"{row['order_consistent_preference']}",
                        pre(row),
                    )
                )
        blocks.append(fold(pair["case_id"] + " / " + pair["regime"], "\n\n".join(body)))
    blocks += ["## 解釈の境界\n", "\n".join("- " + line for line in summary["claim_boundary"])]
    return "\n\n".join(blocks) + "\n"


def diagnostics(result, *, root=REPO):
    """Explain strict rejections without repairing JSON, quotes, or excluded votes."""
    root = Path(root).resolve()
    method = result["providers"]["mistral_enlarged"]
    cells = root / BUNDLE / "cells" / method["method_id"]
    rows, output_tokens, finishes = [], [], Counter()
    for path in sorted(cells.glob("r*/requests/*.json")):
        receipt = run.prior.load_json(path)
        observation = receipt.get("observation", {})
        usage = receipt.get("usage_receipt", {})
        if usage.get("status") == "REPORTED_BY_API":
            output_tokens.append(usage["output_tokens"])
        if receipt["status"] != "response_recorded":
            continue
        raw_path = path.parent.parent / "responses" / path.name
        raw = run.prior.load_json(raw_path)
        finishes[str(observation.get("api_finish_reason") or "unknown")] += 1
        if observation.get("status") != "invalid_judgment":
            continue
        row = {
            "request_id": receipt["request_id"],
            "pair_id": receipt["pair_id"],
            "replicate": receipt["replicate"],
            "order": receipt["order"],
            "observation_error": observation.get("error"),
            "raw_response_path": str(raw_path.relative_to(root)),
            "raw_response_sha256": run.prior.file_sha(raw_path),
            "exact_quote_mismatches": [],
            "vote_excluded": True,
            "repaired": False,
        }
        try:
            text = run.mistral.final_text(raw["choices"][0]["message"]["content"])
            verdict = json.loads(text)
            if not isinstance(verdict, dict):
                raise ValueError("Nonobject judge JSON")
            data = json.loads(receipt["body"]["messages"][1]["content"])
            evidence = verdict.get("quoted_evidence", {})
            if isinstance(evidence, dict):
                for side in ("A", "B"):
                    if isinstance(evidence.get(side), list):
                        for quote in evidence[side]:
                            if isinstance(quote, str) and quote not in data["answer_" + side]:
                                row["exact_quote_mismatches"].append(
                                    {
                                        "assigned_side": side,
                                        "quote": quote,
                                        "answer_sha256": run.prior.sha256(data["answer_" + side]),
                                    }
                                )
            run.prior.validate_judgment(verdict, data["answer_A"], data["answer_B"])
        except (ValueError, TypeError, KeyError, IndexError) as error:
            row["validator_error_type"] = type(error).__name__
            # No exception text fallback or corrected judgment is promoted to a vote.
        rows.append(row)
    cap = method["config"]["max_output_tokens"]
    return {
        "format": "latent-workspace-v14-budget-strict-diagnostics-v1",
        "method_id": method["method_id"],
        "plan": result["inputs"]["plan"],
        "finish_reason_counts": dict(sorted(finishes.items())),
        "reported_output_tokens": {
            "calls": len(output_tokens),
            "min": min(output_tokens) if output_tokens else None,
            "median": statistics.median(output_tokens) if output_tokens else None,
            "max": max(output_tokens) if output_tokens else None,
            "above_old_4000_cap": sum(v > 4000 for v in output_tokens),
            "at_new_cap": sum(v == cap for v in output_tokens),
        },
        "invalid_judgments": len(rows),
        "rejections": rows,
        "claim_boundary": "Mechanical diagnostics only. Invalid votes stay excluded; no repair.",
    }


def publish(plan_path, *, root=REPO):
    result = aggregate(plan_path, root=root)
    output = Path(root) / BUNDLE / "analysis"
    output.mkdir(parents=True, exist_ok=False)
    run.prior.write_json(output / "SUMMARY.json", result, exclusive=True)
    run.prior.write_json(
        output / "STRICT_DIAGNOSTICS.json", diagnostics(result, root=root), exclusive=True
    )
    with (output / "PANEL_REVIEW.md").open("x", encoding="utf-8") as stream:
        stream.write(render(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    result = publish(args.plan) if args.publish else aggregate(args.plan)
    print(
        json.dumps(
            {
                "status": result["status"],
                "new": {
                    k: result["providers"]["mistral_enlarged"][k]
                    for k in (
                        "planned_requests",
                        "reserved_requests",
                        "valid_judgments",
                        "observation_status_counts",
                        "changed_stable_counts",
                    )
                },
            }
        )
    )


if __name__ == "__main__":
    main()
