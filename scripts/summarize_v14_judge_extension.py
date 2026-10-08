#!/usr/bin/env python3
"""Reconstruct the additive three-provider panel without rewriting sealed evidence."""

from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from decimal import Decimal
from itertools import combinations
from pathlib import Path

import prepare_v14_judge_panel as selection
import run_v14_judge_panel as original_runner
import seal_v14_judge_panel as original_seal
import summarize_v14_judge_panel as original

REPO = Path(__file__).resolve().parents[1]
ORIGINAL_BUNDLE = "provenance/pilots/v14_judge_panel_20261009"
BUNDLE = "provenance/pilots/v14_judge_extension_20261009"
ORIGINAL_PLAN = "configs/v14/JUDGE_PANEL_PLAN.json"
MISTRAL_PLAN = "configs/v14/MISTRAL_JUDGE_EXTENSION_PLAN.json"
GEMINI_PLAN = "configs/v14/GEMINI_JUDGE_PANEL_PLAN.json"
PROVIDERS = ("openai", "mistral", "gemini")
require, load, source_path = original.require, original.load, original.source_path


def cell_snapshot(module, plan_path, provider, replicate, config, dataset_path, pairs, requests):
    """Exact common snapshot contract; each runner/source identity stays separate."""
    return {
        "format": "latent-workspace-v14-judge-panel-cell-snapshot-v1",
        "provider": provider,
        "replicate": replicate,
        "plan_sha256": module.prior.file_sha(plan_path),
        "dataset_sha256": module.prior.file_sha(dataset_path),
        "runner_sha256": module.prior.file_sha(Path(module.__file__)),
        "validator_sha256": module.prior.file_sha(Path(module.prior.__file__)),
        "pairs_sha256": module.prior.sha256(pairs),
        "requests_sha256": module.prior.sha256(requests),
        "provider_config": config,
        "pair_count": len(pairs),
        "request_count": len(requests),
        "endpoint": module.PROVIDERS[provider]["endpoint"],
        "cost_upper_bound_usd": str(
            sum((Decimal(row["cost_upper_bound_usd"]) for row in requests), Decimal(0))
        ),
        "output_token_upper_bound": len(requests) * config["max_output_tokens"],
        "key_source": module.PROVIDERS[provider]["env_key"] + "_environment_only_not_recorded",
        "quote_instruction_sha256": module.prior.sha256(module.INSTRUCTIONS),
    }


def verify_cell(module, plan_path, provider, replicate, directory):
    """Read only, never dispatch, reconcile a pending receipt, or repair a judgment."""
    plan = load(plan_path)
    config, dataset_path, pairs, cases = module.validate_plan(plan, provider, replicate)
    requests = module.prepare_requests(plan, provider, replicate, config, pairs, cases)
    expected = cell_snapshot(
        module, plan_path, provider, replicate, config, dataset_path, pairs, requests
    )
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
        request_files = original.names(directory / "requests")
        response_files = original.names(directory / "responses")
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
                    receipt.get("response_sha256") == module.prior.file_sha(path),
                    "Durable response hash changed",
                )
                observation = module.response_observation(raw, request, config)
                require(
                    receipt.get("observation") == observation,
                    "Strict response observation does not reconstruct",
                )
                require(
                    receipt.get("usage_receipt") == module.usage_receipt(raw, request, config),
                    "Usage receipt does not reconstruct",
                )
                normalized = module.prior.normalize_observation(receipt)
                observations[request["request_id"]] = {
                    "status": observation["status"],
                    "normalized_preference": normalized["winner"] if normalized else None,
                    "judgment": observation.get("judgment"),
                    "response_model": observation.get("response_model"),
                    "raw_response_path": source_path(path),
                    "raw_response_sha256": module.prior.file_sha(path),
                }
            elif receipt["status"] in module.RECEIPT_FAILURES:
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
                    load(path)
                    observations[request["request_id"]].update(
                        raw_response_path=source_path(path),
                        raw_response_sha256=module.prior.file_sha(path),
                        raw_body_binding="UNRECONCILED_NOT_A_VALIDATED_API_OBSERVATION",
                    )
            else:
                raise ValueError("Unknown reservation status")
            receipts.append(receipt)
        summary_present = (directory / "SUMMARY.json").exists()
    rebuilt = module.summarize(pairs, receipts, expected)
    if summary_present:
        flag = any(
            receipt["status"] in module.RECEIPT_FAILURES
            or receipt.get("observation", {}).get("status") == "unexpected_model_identity"
            or receipt.get("usage_receipt", {}).get("bound_exceeded", False)
            for receipt in receipts
        )
        require(
            load(directory / "SUMMARY.json")
            == {
                **rebuilt,
                "stopped_on_contract_or_transport_failure": flag,
            },
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


def check_layout(cells_root):
    if not cells_root.exists():
        return
    require(cells_root.is_dir() and not cells_root.is_symlink(), "Nonregular cells root")
    for provider in cells_root.iterdir():
        require(
            provider.name in ("mistral", "gemini")
            and provider.is_dir()
            and not provider.is_symlink(),
            "Unexpected provider; OpenAI must remain referenced, never copied",
        )
        for cell in provider.iterdir():
            require(
                cell.name in {f"r{r}" for r in range(5)}
                and cell.is_dir()
                and not cell.is_symlink(),
                "Unexpected or duplicate replicate",
            )


def provider_report(provider, cells, note):
    counts = Counter(value["status"] for cell in cells for value in cell["observations"].values())
    usages = [cell["summary"]["usage"] for cell in cells]
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
            for key in (
                "reported_usage_undiscounted_cost_usd",
                "reserved_cost_upper_bound_usd",
            )
        }
    )
    usage["actual_billed_cost_usd"] = None
    reserved = sum(cell["reserved_requests"] for cell in cells)
    if "planned_requests" in note:
        require(note["planned_requests"] == 140, "Execution-note planned denominator changed")
    if "dispatched_requests" in note:
        require(
            note["dispatched_requests"] == reserved,
            "Execution-note dispatched count contradicts durable reservations",
        )
    if note.get("status") == "credential_unavailable":
        require(reserved == 0, "Credential-unavailable note contradicts reservations")
    recorded = any(
        cell["summary"]["receipt_status_counts"].get("response_recorded", 0) for cell in cells
    )
    return {
        "planned_cells": 5,
        "planned_requests": 140,
        "reserved_requests": reserved,
        "durable_responses": sum(cell["durable_responses"] for cell in cells),
        "not_dispatched_requests": 140 - reserved,
        "valid_judgments": counts["completed"],
        "observation_status_counts": dict(sorted(counts.items())),
        "observed_model_contract_satisfied": counts["unexpected_model_identity"] == 0
        if recorded
        else None,
        "reported_usage_within_bounds_for_known_calls": usage["usage_bound_exceeded_calls"] == 0
        if usage["calls_with_reported_usage"]
        else None,
        "usage": usage,
        "execution_note_status": note.get("status", "not_supplied"),
        "execution_note_is_operator_report_not_credential_inspection": bool(note),
        "evidence_origin": "original_sealed_bundle_referenced_not_copied"
        if provider == "openai"
        else "additive_extension",
        "all_five_cells_receipt_closed": all(
            cell["status"] == "VERIFIED_RECEIPT_CLOSURE" for cell in cells
        ),
        "cells": [
            {key: value for key, value in cell.items() if key not in ("summary", "observations")}
            for cell in cells
        ],
    }


def aggregate(root=REPO, *, cells_root=None, note_path=None):
    import run_v14_gemini_panel as gemini_runner
    import run_v14_mistral_extension as mistral_runner

    root = Path(root).resolve()
    cells_root = Path(cells_root) if cells_root else root / BUNDLE / "cells"
    note_path = Path(note_path) if note_path else root / BUNDLE / "EXECUTION_NOTE.json"
    original_receipt = original_seal.verify(root)
    note = load(note_path)
    require(
        note.get("format") == "latent-workspace-v14-judge-extension-execution-note-v1",
        "Unknown extension execution note format",
    )
    require(set(note.get("providers", {})) <= set(PROVIDERS), "Unknown execution-note provider")
    check_layout(cells_root)
    plan_path = root / ORIGINAL_PLAN
    plan = load(plan_path)
    _, dataset_path, pairs, cases = original_runner.validate_plan(plan, "openai", 0)
    dataset = load(dataset_path)
    require(dataset == selection.build(root), "Selection does not reconstruct from original bank")
    sources = {
        "openai": (original_runner, plan_path),
        "mistral": (mistral_runner, root / MISTRAL_PLAN),
        "gemini": (gemini_runner, root / GEMINI_PLAN),
    }
    for provider in ("mistral", "gemini"):
        module, provider_plan_path = sources[provider]
        _, provider_dataset, provider_pairs, provider_cases = module.validate_plan(
            load(provider_plan_path), provider, 0
        )
        require(
            provider_dataset.resolve() == dataset_path.resolve()
            and provider_pairs == pairs
            and provider_cases == cases,
            f"{provider} and original panel do not bind identical cases and answer pairs",
        )
    cells = {}
    for provider in PROVIDERS:
        module, selected_plan = sources[provider]
        origin = root / ORIGINAL_BUNDLE / "cells" if provider == "openai" else cells_root
        cells[provider] = [
            verify_cell(module, selected_plan, provider, r, origin / provider / f"r{r}")
            for r in range(5)
        ]
    providers = {
        provider: provider_report(provider, rows, note["providers"].get(provider, {}))
        for provider, rows in cells.items()
    }
    pair_results = []
    for pair in pairs:
        by_provider = {
            provider: original.describe_repeats(
                [original.normalized_repeat(cell, pair) for cell in rows]
            )
            for provider, rows in cells.items()
        }
        cross = []
        for replicate in range(5):
            values = {
                provider: result["replicates"][replicate]["order_consistent_preference"]
                for provider, result in by_provider.items()
            }
            comparable = all(value is not None for value in values.values())
            cross.append(
                {
                    "replicate": replicate,
                    "preferences": values,
                    "all_three_models_valid_order_consistent": comparable,
                    "all_three_agree": len(set(values.values())) == 1 if comparable else None,
                    "pairwise_agreement": {
                        f"{left}__{right}": (
                            values[left] == values[right]
                            if values[left] is not None and values[right] is not None
                            else None
                        )
                        for left, right in combinations(PROVIDERS, 2)
                    },
                }
            )
        pair_results.append(
            {
                **pair,
                "constraint_checks": original.constraint_checks(pair),
                "world_task_cluster": list(selection.cluster(cases[pair["case_id"]])),
                "providers": by_provider,
                "cross_provider_within_replicate": cross,
            }
        )
    for provider, report in providers.items():
        report["lanes"] = {}
        for lane in ("general", "relation"):
            changed = [p for p in pair_results if p["lane"] == lane and not p["calibration_only"]]
            controls = [p for p in pair_results if p["lane"] == lane and p["calibration_only"]]
            report["lanes"][lane] = {
                "changed_pairs": len(changed),
                "changed_case_prompts": len({p["case_id"] for p in changed}),
                "changed_world_task_clusters": len(
                    {tuple(p["world_task_cluster"]) for p in changed}
                ),
                "changed_stable_all_five_counts": {
                    value: sum(
                        p["providers"][provider]["stable_all_five_preference"] == value
                        for p in changed
                    )
                    for value in original.PREFERENCES
                },
                "calibration_pairs": len(controls),
                "calibration_stable_all_five_ties": sum(
                    p["providers"][provider]["stable_all_five_preference"] == "tie"
                    for p in controls
                ),
            }
    complete = all(value["all_five_cells_receipt_closed"] for value in providers.values())

    def bound(path):
        return {"path": source_path(path), "sha256": original_runner.prior.file_sha(path)}

    return {
        "format": "latent-workspace-v14-judge-extension-summary-v1",
        "status": "VERIFIED_COMPLETE_RECEIPTS_NOT_GOLD"
        if complete
        else "VERIFIED_PARTIAL_RECEIPTS_NOT_GOLD",
        "inputs": {
            "original_index": bound(root / ORIGINAL_BUNDLE / "INDEX.json"),
            "original_validation": bound(root / ORIGINAL_BUNDLE / "VALIDATION.json"),
            "original_validation_recomputed": original_receipt["status"],
            "original_plan": bound(plan_path),
            "mistral_plan": bound(root / MISTRAL_PLAN),
            "gemini_plan": bound(root / GEMINI_PLAN),
            "selection": bound(dataset_path),
            "execution_note": bound(note_path),
            "aggregator_sha256": original_runner.prior.file_sha(Path(__file__)),
        },
        "selection_counts": dataset["counts"],
        "planned_requests": 420,
        "newly_planned_requests": 280,
        "reused_openai_requests": 140,
        "providers": providers,
        "cases": dataset["cases"],
        "pairs": pair_results,
        "semantic_promotion": False,
        "winner": "none",
        "human_evaluation": "PENDING",
        "non_regression": "NOT_ESTABLISHED",
        "pooled_provider_winner": None,
        "claim_boundary": [
            "All ten changed pairs and four actual-identical controls are reused "
            "without outcome selection.",
            "Seven changed prompts form six world/task clusters; "
            "repeats are not independent task samples.",
            "OpenAI's 140 earlier calls are referenced, "
            "not re-run or silently counted as new observations.",
            "Three provider/model/settings packages are compared; "
            "family identity alone is not isolated.",
            "Repeat-index alignment is bookkeeping, "
            "not shared provider randomness or matched seeds.",
            "No majority vote is gold. Missing, refused, invalid "
            "and order-conflicting judgments stay visible.",
            "Stable all-five preference requires five valid, order-consistent repeats "
            "with one common preference.",
            "API model IDs do not prove immutable preview weights or independent family judgments.",
            "Quoted evidence is checked literally with no repair; "
            "valid syntax does not imply correct reasoning.",
            "Receipt closure is not model improvement, non-regression, "
            "human agreement or memory-content causality.",
        ],
    }


def render_review(summary):
    pre, fold = original.pre, original.fold
    cases = {case["id"]: case for case in summary["cases"]}
    blocks = [
        "# V14 3-provider judge追加比較\n",
        "元OpenAI 140件を参照し、Mistral・Geminiを追加。"
        "多数決を正解にせず、欠損と順序不一致を残します。",
        pre({key: summary[key] for key in ("status", "planned_requests", "selection_counts")}),
    ]
    for provider, report in summary["providers"].items():
        blocks += [
            f"## {provider}\n",
            f"予約 {report['reserved_requests']}/140、有効 {report['valid_judgments']}、"
            f"未送信 {report['not_dispatched_requests']}。",
            fold("実行・欠損・usage", pre(report)),
        ]
    blocks += [
        "## 14対の早見表\n",
        "各欄は r0→r4。conflict はAB/BA不一致、invalid/missing は無効・欠損。"
        "同一反復番号は乱数共有を意味しません。5回すべて有効かつ順序一致の場合だけ安定を表示します。",
    ]
    headers = ["case / regime", "区分"]
    for provider in PROVIDERS:
        headers += [f"{provider} r0→r4", "5回安定"]
    table = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for pair in summary["pairs"]:
        values = [
            pair["case_id"] + " / " + pair["regime"],
            "同一文校正" if pair["calibration_only"] else "差分",
        ]
        for provider in PROVIDERS:
            report = pair["providers"][provider]
            values += [
                " · ".join(original.repeat_label(row) for row in report["replicates"]),
                report["stable_all_five_preference"] or "—",
            ]
        table.append("| " + " | ".join(html.escape(value) for value in values) + " |")
    blocks.append("\n".join(table))
    for pair in summary["pairs"]:
        body = [
            "質問",
            pre(cases[pair["case_id"]]["user_prompt"]),
            "Base回答",
            pre(pair["base_answer"]),
            "Workspace回答",
            pre(pair["workspace_answer"]),
            "事後の機械的語数確認（judge判定を上書きしません）",
            pre(pair["constraint_checks"]),
        ]
        for provider, report in pair["providers"].items():
            body += [
                f"### {provider}\n",
                pre({k: v for k, v in report.items() if k != "replicates"}),
            ]
            for row in report["replicates"]:
                label = (
                    f"r{row['replicate']} / {row['judge_status']} / "
                    f"{row['order_consistent_preference']}"
                )
                body.append(fold(label + "・全判断とraw参照", pre(row)))
        body += [
            "provider間比較（同じ反復番号の記述的比較）",
            pre(pair["cross_provider_within_replicate"]),
        ]
        blocks.append(
            fold(
                pair["case_id"] + " / " + pair["regime"] + " / " + pair["pair_id"],
                "\n\n".join(body),
            )
        )
    blocks += ["## 解釈の境界\n", "\n".join("- " + value for value in summary["claim_boundary"])]
    return "\n\n".join(blocks) + "\n"


def prepare(root=REPO, *, output=None, cells_root=None, note_path=None):
    root = Path(root).resolve()
    output = Path(output) if output else root / BUNDLE / "analysis"
    if output.exists() or output.is_symlink():
        raise FileExistsError("Extension reports already exist; never overwrite evidence")
    result = aggregate(root, cells_root=cells_root, note_path=note_path)
    output.mkdir(parents=True, exist_ok=False)
    for name, body in {
        "SUMMARY.json": json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        "PANEL_REVIEW.md": render_review(result),
    }.items():
        with (output / name).open("x", encoding="utf-8") as stream:
            stream.write(body)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO)
    parser.add_argument("--cells-root", type=Path)
    parser.add_argument("--execution-note", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = prepare(
        args.root, output=args.output, cells_root=args.cells_root, note_path=args.execution_note
    )
    print(json.dumps({"status": result["status"], "planned_requests": result["planned_requests"]}))


if __name__ == "__main__":
    main()
