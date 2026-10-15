#!/usr/bin/env python3
"""Offline panel reconstruction and descriptive reporting, never majority gold."""

from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

import prepare_v14_judge_panel as selection
import run_v14_judge_panel as runner

REPO = Path(__file__).resolve().parents[1]
PREFERENCES = ("base", "workspace", "tie", "uncertain")


def require(value, message):
    if not value:
        raise ValueError(message)


def load(path):
    require(path.is_file() and not path.is_symlink(), f"Missing/nonregular input: {path.name}")
    return json.loads(path.read_text())


def names(path):
    if not path.exists():
        return set()
    require(path.is_dir() and not path.is_symlink(), "Nonregular receipt directory")
    files = list(path.iterdir())
    require(
        all(item.is_file() and not item.is_symlink() and item.suffix == ".json" for item in files),
        "Unexpected receipt file",
    )
    return {item.name for item in files}


def source_path(path):
    return str(path.relative_to(REPO)) if path.is_relative_to(REPO) else str(path)


def snapshot(plan_path, provider, replicate, config, dataset_path, pairs, requests):
    return {
        "format": "latent-workspace-v14-judge-panel-cell-snapshot-v1",
        "provider": provider,
        "replicate": replicate,
        "plan_sha256": runner.prior.file_sha(plan_path),
        "dataset_sha256": runner.prior.file_sha(dataset_path),
        "runner_sha256": runner.prior.file_sha(Path(runner.__file__)),
        "validator_sha256": runner.prior.file_sha(Path(runner.prior.__file__)),
        "pairs_sha256": runner.prior.sha256(pairs),
        "requests_sha256": runner.prior.sha256(requests),
        "provider_config": config,
        "pair_count": len(pairs),
        "request_count": len(requests),
        "endpoint": runner.PROVIDERS[provider]["endpoint"],
        "cost_upper_bound_usd": str(
            sum((Decimal(row["cost_upper_bound_usd"]) for row in requests), Decimal(0))
        ),
        "output_token_upper_bound": len(requests) * config["max_output_tokens"],
        "key_source": runner.PROVIDERS[provider]["env_key"] + "_environment_only_not_recorded",
        "quote_instruction_sha256": runner.prior.sha256(runner.INSTRUCTIONS),
    }


def verify_cell(plan_path, provider, replicate, directory):
    """Reconstruct one cell from durable data; missing cells remain missing."""
    plan = load(plan_path)
    config, dataset_path, pairs, cases = runner.validate_plan(plan, provider, replicate)
    requests = runner.prepare_requests(plan, provider, replicate, config, pairs, cases)
    expected = snapshot(plan_path, provider, replicate, config, dataset_path, pairs, requests)
    summary_present, present = False, directory.exists()
    receipts, unresolved, observations = [], [], {}
    response_files = set()
    if present:
        require(directory.is_dir() and not directory.is_symlink(), "Nonregular cell directory")
        require(
            {path.name for path in directory.iterdir()}
            <= {
                "SNAPSHOT.json",
                "PAIRS.json",
                "PREPARED_REQUESTS.json",
                "SUMMARY.json",
                "requests",
                "responses",
            },
            "Unexpected file or duplicate cell material",
        )
        for name, value in (
            ("SNAPSHOT.json", expected),
            ("PAIRS.json", {"pairs": pairs}),
            ("PREPARED_REQUESTS.json", {"requests": requests}),
        ):
            require(load(directory / name) == value, f"Cell {name} does not reconstruct")
        request_files, response_files = (
            names(directory / "requests"),
            names(directory / "responses"),
        )
        allowed = {request["request_id"] + ".json" for request in requests}
        require(
            request_files <= allowed and response_files <= request_files,
            "Unknown, duplicate or unreserved request/response identity",
        )
        for request in requests:
            filename = request["request_id"] + ".json"
            if filename not in request_files:
                continue
            receipt = load(directory / "requests" / filename)
            require(
                {key: receipt.get(key) for key in request} == request,
                "Reserved request body or coordinate changed",
            )
            require(
                isinstance(receipt.get("reserved_at"), str) and receipt["reserved_at"],
                "Missing request reservation timestamp",
            )
            if receipt["status"] == "response_recorded":
                path = directory / "responses" / filename
                raw = load(path)
                require(
                    receipt.get("response_sha256") == runner.prior.file_sha(path),
                    "Durable response hash changed",
                )
                observation = runner.response_observation(raw, request, config)
                require(
                    receipt.get("observation") == observation,
                    "Strict response observation does not reconstruct",
                )
                require(
                    receipt.get("usage_receipt") == runner.usage_receipt(raw, request, config),
                    "Usage receipt does not reconstruct",
                )
                normalized = runner.prior.normalize_observation(receipt)
                observations[request["request_id"]] = {
                    "status": observation["status"],
                    "normalized_preference": normalized["winner"] if normalized else None,
                    "judgment": observation.get("judgment"),
                    "response_model": observation.get("response_model"),
                    "raw_response_path": source_path(path),
                    "raw_response_sha256": runner.prior.file_sha(path),
                }
            elif receipt["status"] in runner.RECEIPT_FAILURES:
                require(
                    receipt.get("observation") is None and receipt.get("usage_receipt") is None,
                    "Unresolved receipt contains an unsupported observation",
                )
                unresolved.append(request["request_id"])
                observations[request["request_id"]] = {
                    "status": receipt["status"],
                    "normalized_preference": None,
                    "judgment": None,
                    "durable_body_without_reconciled_receipt": filename in response_files,
                }
                if filename in response_files:
                    path = directory / "responses" / filename
                    load(path)  # Retain readable evidence without reconciling or re-dispatching.
                    observations[request["request_id"]].update(
                        raw_response_path=source_path(path),
                        raw_response_sha256=runner.prior.file_sha(path),
                        raw_body_binding="UNRECONCILED_NOT_A_VALIDATED_API_OBSERVATION",
                    )
            else:
                raise ValueError("Unknown reservation status")
            receipts.append(receipt)
        summary_present = (directory / "SUMMARY.json").exists()
    rebuilt = runner.summarize(pairs, receipts, expected)
    if summary_present:
        reported = load(directory / "SUMMARY.json")
        flag = any(
            receipt["status"] in runner.RECEIPT_FAILURES
            or receipt.get("observation", {}).get("status") == "unexpected_model_identity"
            or receipt.get("usage_receipt", {}).get("bound_exceeded", False)
            for receipt in receipts
        )
        require(
            reported.get("stopped_on_contract_or_transport_failure") is flag,
            "Cell execution-stop flag disagrees with receipt failures",
        )
        require(
            reported == {**rebuilt, "stopped_on_contract_or_transport_failure": flag},
            "Cell SUMMARY does not reconstruct exactly",
        )
    for request in requests:
        observations.setdefault(
            request["request_id"],
            {
                "status": "not_dispatched",
                "normalized_preference": None,
                "judgment": None,
            },
        )
    complete = len(receipts) == len(requests) and not unresolved and summary_present
    return {
        "provider": provider,
        "replicate": replicate,
        "directory": source_path(directory),
        "status": "VERIFIED_RECEIPT_CLOSURE"
        if complete
        else ("NOT_DISPATCHED" if not receipts else "INCOMPLETE_RECEIPTS"),
        "prepared_artifacts_present": present,
        "summary_recomputed_exactly": summary_present,
        "planned_requests": len(requests),
        "reserved_requests": len(receipts),
        "durable_responses": len(response_files),
        "not_dispatched_requests": len(requests) - len(receipts),
        "unresolved_request_ids": unresolved,
        "summary": rebuilt,
        "observations": observations,
    }


def normalized_repeat(cell, pair):
    row = next(row for row in cell["summary"]["pairs"] if row["pair_id"] == pair["pair_id"])
    orders = {
        order: cell["observations"][
            f"{cell['provider']}-r{cell['replicate']}-{pair['pair_id']}-{order}"
        ]
        for order in ("AB", "BA")
    }
    return {
        "replicate": cell["replicate"],
        "cell_status": cell["status"],
        "judge_status": row["judge_status"],
        "order_consistent_preference": row["order_consistent_preference"],
        "orders": orders,
    }


def describe_repeats(repeats):
    consistent = [row for row in repeats if row["judge_status"] == "order_consistent"]
    preferences = [row["order_consistent_preference"] for row in consistent]
    all_five = len(consistent) == len(repeats) == 5
    stable = all_five and len(set(preferences)) == 1
    return {
        "planned_replicates": 5,
        "order_consistent_replicates": len(consistent),
        "order_conflicting_replicates": sum(
            row["judge_status"] == "order_conflict" for row in repeats
        ),
        "missing_or_invalid_replicates": sum(
            row["judge_status"] == "missing_or_invalid_order" for row in repeats
        ),
        "consistent_preference_counts": {value: preferences.count(value) for value in PREFERENCES},
        "all_five_valid_and_order_consistent": all_five,
        "stable_all_five_preference": preferences[0] if stable else None,
        "stability_status": "STABLE_ALL_FIVE"
        if stable
        else ("VARIES_ACROSS_REPLICATES" if all_five else "INCOMPLETE_OR_ORDER_CONFLICT"),
        "replicates": repeats,
    }


def constraint_checks(pair):
    """Posthoc whitespace counts only, never a replacement for judge outcomes."""
    limit = (
        30
        if pair["lane"] == "relation"
        else {
            "general-01-summary": 55,
            "general-05-causal": 60,
        }.get(pair["case_id"])
    )
    return {
        "status": "POSTHOC_MECHANICAL_DESCRIPTIVE",
        "preregistered_judge_outcome": False,
        "applicability": "applicable_english_word_limit" if limit is not None else "not_applicable",
        "method": "len(answer.split())",
        "word_limit": limit,
        **{
            side: {
                "whitespace_word_count": len(pair[side + "_answer"].split())
                if limit is not None
                else None,
                "exceeds_limit": len(pair[side + "_answer"].split()) > limit
                if limit is not None
                else None,
            }
            for side in ("base", "workspace")
        },
        "claim_boundary": "Whitespace-separated units, not tokenizer tokens or linguistic "
        "segmentation. No Japanese word/character count or overall quality claim. "
        "Computed for every selected applicable pair; existing judge preferences stay unchanged.",
    }


def check_layout(cells_root, note_path):
    if not cells_root.exists():
        return
    require(cells_root.is_dir() and not cells_root.is_symlink(), "Nonregular cells root")
    for path in cells_root.iterdir():
        if note_path and path.resolve() == note_path.resolve():
            continue
        require(
            path.name in runner.PROVIDERS and path.is_dir() and not path.is_symlink(),
            "Unexpected provider or duplicate cell directory",
        )
        for cell in path.iterdir():
            require(
                cell.name in {f"r{replicate}" for replicate in range(5)}
                and cell.is_dir()
                and not cell.is_symlink(),
                "Unexpected or duplicate replicate",
            )


def aggregate(plan_path, cells_root, note_path=None):
    plan_path, cells_root = Path(plan_path), Path(cells_root)
    note_path = Path(note_path) if note_path else None
    plan, note = load(plan_path), load(note_path) if note_path else None
    if note is not None:
        require(
            note.get("format") == "latent-workspace-v14-judge-panel-execution-note-v1",
            "Unknown execution note format",
        )
        require(set(note["providers"]) <= set(runner.PROVIDERS), "Unknown execution-note provider")
    check_layout(cells_root, note_path)
    _, dataset_path, pairs, cases = runner.validate_plan(plan, "openai", 0)
    dataset = load(dataset_path)
    require(
        dataset == selection.build(), "Selected dataset does not reproduce from original sources"
    )
    cells = {
        provider: [
            verify_cell(plan_path, provider, r, cells_root / provider / f"r{r}")
            for r in plan["replicates"]
        ]
        for provider in runner.PROVIDERS
    }
    providers = {}
    for provider, provider_cells in cells.items():
        provider_note = note["providers"].get(provider, {}) if note else {}
        reserved = sum(cell["reserved_requests"] for cell in provider_cells)
        if provider_note.get("status") == "credential_unavailable":
            require(
                provider_note.get("planned_requests") == 140
                and provider_note.get("dispatched_requests") == 0
                and reserved == 0,
                "Credential-unavailable note contradicts request reservations",
            )
        observation_counts = Counter(
            value["status"] for cell in provider_cells for value in cell["observations"].values()
        )
        usages = [cell["summary"]["usage"] for cell in provider_cells]
        usage = {
            key: sum(row[key] for row in usages)
            for key in (
                "reserved_calls",
                "calls_with_reported_usage",
                "calls_without_reported_usage",
                "reported_input_tokens",
                "reported_output_tokens",
                "reported_total_tokens",
                "usage_bound_exceeded_calls",
            )
        }
        usage.update(
            {
                key: str(sum((Decimal(row[key]) for row in usages), Decimal(0)))
                for key in ("reported_usage_undiscounted_cost_usd", "reserved_cost_upper_bound_usd")
            }
        )
        usage["actual_billed_cost_usd"] = None
        providers[provider] = {
            "planned_cells": 5,
            "planned_requests": 140,
            "reserved_requests": reserved,
            "durable_responses": sum(cell["durable_responses"] for cell in provider_cells),
            "not_dispatched_requests": 140 - reserved,
            "valid_judgments": observation_counts["completed"],
            "observation_status_counts": dict(sorted(observation_counts.items())),
            "observed_model_contract_satisfied": (
                observation_counts["unexpected_model_identity"] == 0
                if any(
                    cell["summary"]["receipt_status_counts"].get("response_recorded", 0)
                    for cell in provider_cells
                )
                else None
            ),
            "reported_usage_within_bounds_for_known_calls": (
                usage["usage_bound_exceeded_calls"] == 0
                if usage["calls_with_reported_usage"]
                else None
            ),
            "usage": usage,
            "execution_note_status": provider_note.get("status", "not_supplied"),
            "execution_note_is_operator_report_not_credential_inspection": bool(provider_note),
            "all_five_cells_receipt_closed": all(
                cell["status"] == "VERIFIED_RECEIPT_CLOSURE" for cell in provider_cells
            ),
            "cells": [
                {
                    key: value
                    for key, value in cell.items()
                    if key not in ("summary", "observations")
                }
                for cell in provider_cells
            ],
        }
    pair_results = []
    for pair in pairs:
        by_provider = {
            provider: describe_repeats([normalized_repeat(cell, pair) for cell in rows])
            for provider, rows in cells.items()
        }
        cross = []
        for replicate in range(5):
            values = {
                provider: results["replicates"][replicate]["order_consistent_preference"]
                for provider, results in by_provider.items()
            }
            comparable = all(value is not None for value in values.values())
            cross.append(
                {
                    "replicate": replicate,
                    "preferences": values,
                    "both_models_valid_order_consistent": comparable,
                    "agree": len(set(values.values())) == 1 if comparable else None,
                }
            )
        pair_results.append(
            {
                **pair,
                "constraint_checks": constraint_checks(pair),
                "world_task_cluster": list(selection.cluster(cases[pair["case_id"]])),
                "providers": by_provider,
                "cross_provider_within_replicate": cross,
            }
        )
    for provider, summary in providers.items():
        summary["lanes"] = {}
        for lane in ("general", "relation"):
            changed = [
                pair
                for pair in pair_results
                if pair["lane"] == lane and not pair["calibration_only"]
            ]
            controls = [
                pair for pair in pair_results if pair["lane"] == lane and pair["calibration_only"]
            ]
            summary["lanes"][lane] = {
                "changed_pairs": len(changed),
                "changed_case_prompts": len({p["case_id"] for p in changed}),
                "changed_world_task_clusters": len(
                    {tuple(p["world_task_cluster"]) for p in changed}
                ),
                "changed_stable_all_five_counts": {
                    value: sum(
                        pair["providers"][provider]["stable_all_five_preference"] == value
                        for pair in changed
                    )
                    for value in PREFERENCES
                },
                "calibration_pairs": len(controls),
                "calibration_stable_all_five_ties": sum(
                    pair["providers"][provider]["stable_all_five_preference"] == "tie"
                    for pair in controls
                ),
            }
    complete = all(value["all_five_cells_receipt_closed"] for value in providers.values())
    return {
        "format": "latent-workspace-v14-multi-judge-panel-summary-v1",
        "status": "VERIFIED_COMPLETE_RECEIPTS_NOT_GOLD"
        if complete
        else "VERIFIED_PARTIAL_RECEIPTS_NOT_GOLD",
        "inputs": {
            "plan": {"path": source_path(plan_path), "sha256": runner.prior.file_sha(plan_path)},
            "selection": {
                "path": source_path(dataset_path),
                "sha256": runner.prior.file_sha(dataset_path),
            },
            "execution_note": {
                "path": source_path(note_path),
                "sha256": runner.prior.file_sha(note_path),
            }
            if note_path
            else None,
            "aggregator_sha256": runner.prior.file_sha(Path(__file__)),
        },
        "selection_counts": dataset["counts"],
        "planned_requests": 280,
        "providers": providers,
        "cases": dataset["cases"],
        "pairs": pair_results,
        "semantic_promotion": False,
        "winner": "none",
        "human_evaluation": "PENDING",
        "non_regression": "NOT_ESTABLISHED",
        "pooled_provider_winner": None,
        "claim_boundary": [
            "Repeated judgments estimate judgment variability, "
            "not independent task samples or majority gold.",
            "All ten previously changed pairs are selected; "
            "this is conditional development evidence, not a fresh holdout.",
            "Seven changed prompts form six world/task clusters; "
            "identical controls are calibration, not quality gains.",
            "Providers remain separate. Repeat-index alignment is bookkeeping, "
            "not shared provider randomness.",
            "Missing providers/cells and strict invalid quotations remain missing; "
            "no format repair is applied.",
            "A stable all-five preference requires five valid, order-consistent repeats "
            "with exactly one common preference.",
            "An operator's credential-unavailable note is not verified credential access "
            "or a successful API call.",
            "Receipt closure does not prove correct judge reasoning, human agreement, "
            "model improvement or non-regression.",
        ],
    }


def pre(value):
    return (
        "<pre>"
        + html.escape(
            value
            if isinstance(value, str)
            else json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2),
            quote=True,
        )
        + "</pre>"
    )


def fold(label, body):
    return "<details>\n<summary>" + html.escape(label) + "</summary>\n\n" + body + "\n\n</details>"


def repeat_label(row):
    if row["judge_status"] == "order_consistent":
        return row["order_consistent_preference"]
    if row["judge_status"] == "order_conflict":
        return "conflict"
    if all(item["status"] == "not_dispatched" for item in row["orders"].values()):
        return "not_dispatched"
    return "invalid/missing"


def render_review(summary):
    cases = {case["id"]: case for case in summary["cases"]}
    blocks = [
        "# V14 複数judge・反復観察パネル"
        + ("（一部未実行・欠損あり）\n" if "PARTIAL" in summary["status"] else "\n"),
        "多数決を正解にしません。providerを混ぜず、各反復のAB/BAと欠損を残します。人間評価は未実施です。",
        pre({"status": summary["status"], "selection_counts": summary["selection_counts"]}),
    ]
    for provider, report in summary["providers"].items():
        blocks += [
            "## " + provider + "\n",
            f"予約 {report['reserved_requests']}/{report['planned_requests']}、"
            f"厳密に有効な判定 {report['valid_judgments']}、"
            f"未送信 {report['not_dispatched_requests']}。"
            + "実行注記: "
            + html.escape(report["execution_note_status"]),
            fold(provider + " の実行・欠損・usage計数", pre(report)),
        ]
    blocks += [
        "## 14対の早見表\n",
        "各欄は r0 → r4。base/workspace は両提示順で一致した選好、tie は同点、"
        "uncertain は判定困難、conflict はAB/BA不一致です。invalid/missing と not_dispatched は"
        "選好ではありません。安定判定は5回すべて有効・両順序一致の場合だけ示します。",
    ]
    table = [
        "| case / regime | 区分 | OpenAI r0→r4 | 5回安定 | Mistral r0→r4 | 5回安定 |",
        "|---|---|---|---|---|---|",
    ]
    for pair in summary["pairs"]:
        values = [
            pair["case_id"] + " / " + pair["regime"],
            "同一文校正" if pair["calibration_only"] else "差分",
        ]
        for provider in ("openai", "mistral"):
            report = pair["providers"][provider]
            values += [
                " · ".join(repeat_label(row) for row in report["replicates"]),
                report["stable_all_five_preference"] or "—",
            ]
        table.append("| " + " | ".join(html.escape(value) for value in values) + " |")
    blocks.append("\n".join(table))
    for pair in summary["pairs"]:
        blocks += [
            "<details>\n<summary>"
            + html.escape(pair["case_id"] + " / " + pair["regime"] + " / " + pair["pair_id"])
            + "</summary>\n",
            pre(
                {
                    key: pair[key]
                    for key in (
                        "lane",
                        "regime",
                        "comparison",
                        "calibration_only",
                        "base_finish_reason",
                        "workspace_finish_reason",
                    )
                }
            ),
            "質問",
            pre(cases[pair["case_id"]]["user_prompt"]),
            "Base回答",
            pre(pair["base_answer"]),
            "Workspace回答",
            pre(pair["workspace_answer"]),
            "事後の機械的な語数確認（事前登録judge判定ではありません）",
            pre(pair["constraint_checks"]),
        ]
        for provider, report in pair["providers"].items():
            blocks += [
                "### " + provider + "\n",
                pre({key: value for key, value in report.items() if key != "replicates"}),
            ]
            for row in report["replicates"]:
                label = f"r{row['replicate']} / {row['judge_status']} / "
                label += str(row["order_consistent_preference"])
                prose = []
                for order, observation in row["orders"].items():
                    prose.append(order + " / " + html.escape(observation["status"]))
                    judgment = observation.get("judgment")
                    if judgment:
                        prose += [
                            pre(judgment["rationale_ja"]),
                            "変化",
                            pre(judgment["changes_ja"]),
                            "注意点",
                            pre(judgment["risks_ja"]),
                            "不確実性",
                            pre(judgment["uncertainty_ja"]),
                            "回答からの引用",
                            pre(judgment["quoted_evidence"]),
                        ]
                prose.append(fold("全監査フィールド・raw応答への参照", pre(row)))
                blocks.append(fold(label, "\n\n".join(prose)))
        blocks += [
            "同一反復番号でのprovider間比較（乱数共有ではありません）",
            pre(pair["cross_provider_within_replicate"]),
            "</details>",
        ]
    blocks += ["## 解釈の境界\n", "\n".join("- " + text for text in summary["claim_boundary"])]
    return "\n\n".join(blocks) + "\n"


def prepare(plan_path, cells_root, output, note_path=None):
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("Panel output already exists; existing reports are never overwritten")
    summary = aggregate(plan_path, cells_root, note_path)
    documents = {
        "SUMMARY.json": json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        "PANEL_REVIEW.md": render_review(summary),
    }
    output.mkdir(parents=True, exist_ok=False)
    for name, body in documents.items():
        with (output / name).open("x", encoding="utf-8") as handle:
            handle.write(body)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--cells-root", type=Path, required=True)
    parser.add_argument("--execution-note", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.plan, args.cells_root, args.output, args.execution_note)
    print(json.dumps({"status": result["status"], "planned_requests": result["planned_requests"]}))


if __name__ == "__main__":
    main()
