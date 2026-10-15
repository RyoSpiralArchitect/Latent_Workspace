#!/usr/bin/env python3
"""Verify the V14 free-form evidence without rerunning any model."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Expected an object: {path}")
    return value


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _close(observed: float, expected: float) -> bool:
    return math.isclose(observed, expected, rel_tol=0.0, abs_tol=1e-15)


def _pair_rows(
    rows: list[dict[str, Any]],
    model: str,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    indexed = {
        (row["model"], row["case_id"], row["regime"], row["lane"]): row
        for row in rows
    }
    pairs = []
    for row in rows:
        if row["model"] != model or row["lane"] != "deferred_intact":
            continue
        twin = indexed[(model, row["case_id"], row["regime"], "deferred_twin")]
        pairs.append((row, twin))
    return pairs


def _first_divergence(
    left: list[int],
    right: list[int],
) -> int | None:
    for index, (left_token, right_token) in enumerate(zip(left, right), start=1):
        if left_token != right_token:
            return index
    if len(left) != len(right):
        return min(len(left), len(right)) + 1
    return None


def _pair_metrics(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    changed = [
        pair
        for pair in pairs
        if pair[0]["generated_token_ids"] != pair[1]["generated_token_ids"]
    ]
    affected = [pair for pair in pairs if pair[0]["affected"]]
    unaffected = [pair for pair in pairs if not pair[0]["affected"]]
    divergence = Counter(
        _first_divergence(
            pair[0]["generated_token_ids"],
            pair[1]["generated_token_ids"],
        )
        for pair in changed
    )
    return {
        "pairs": len(pairs),
        "first_choice_changes": sum(
            left["first_token_choice"] != right["first_token_choice"]
            for left, right in pairs
        ),
        "full_sequence_changes": len(changed),
        "affected_changes": sum(
            left["generated_token_ids"] != right["generated_token_ids"]
            for left, right in affected
        ),
        "affected_pairs": len(affected),
        "unaffected_changes": sum(
            left["generated_token_ids"] != right["generated_token_ids"]
            for left, right in unaffected
        ),
        "unaffected_pairs": len(unaffected),
        "first_divergence": {str(key): value for key, value in sorted(divergence.items())},
    }


def _choice_accuracy(
    rows: list[dict[str, Any]],
    model: str,
    lane: str,
    affected: bool | None,
) -> tuple[int, int, float]:
    selected = [
        row
        for row in rows
        if row["model"] == model
        and row["lane"] == lane
        and (affected is None or row["affected"] is affected)
    ]
    correct = sum(bool(row["target_correct"]) for row in selected)
    return correct, len(selected), correct / len(selected)


def _first_step_delta(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    affected: bool,
) -> tuple[float, float]:
    values = [
        abs(
            left["step_receipts"][0]["chosen_log_probability"]
            - right["step_receipts"][0]["chosen_log_probability"]
        )
        for left, right in pairs
        if left["affected"] is affected
    ]
    return math.fsum(values) / len(values), max(values)


def main() -> int:
    manifest = _load(HERE / "ARTIFACT_INDEX.json")
    summary = _load(HERE / "SUMMARY.json")
    report = _load(HERE / "raw/report.json")
    training = _load(HERE / "raw/training_execution.json")
    grouped_execution = _load(HERE / "raw/grouped_execution.json")
    comparison = _load(HERE / "raw/grouped_comparison.json")
    plan_path = REPO / "configs/v14/EXPERIMENTAL_CHAT_PLAN.json"
    plan = _load(plan_path)
    rows = report["rows"]

    file_checks = {}
    for relative, expected in manifest["files"].items():
        path = HERE / relative
        file_checks[relative] = {
            "bytes": path.stat().st_size == expected["bytes"],
            "sha256": _digest(path) == expected["sha256"],
        }

    task_pairs = _pair_rows(rows, "task")
    semantic_pairs = _pair_rows(rows, "semantic")
    task_metrics = _pair_metrics(task_pairs)
    semantic_metrics = _pair_metrics(semantic_pairs)
    expected_task = summary["autoregressive_continuation"]["task_intact_twin"]
    expected_semantic = summary["autoregressive_continuation"][
        "semantic_intact_twin"
    ]

    source_checks = {
        relative: _digest(REPO / relative) == expected
        for relative, expected in plan["source_identity"].items()
    }
    model_specs = {model["id"]: model for model in plan["models"]}
    training_runs = {run["id"]: run for run in training["runs"]}
    first_displacement = summary["first_step_probability_displacement"]
    task_affected_delta = _first_step_delta(task_pairs, True)
    task_unaffected_delta = _first_step_delta(task_pairs, False)
    semantic_affected_delta = _first_step_delta(semantic_pairs, True)
    semantic_unaffected_delta = _first_step_delta(semantic_pairs, False)

    checks = {
        "manifest_files": all(
            all(values.values()) for values in file_checks.values()
        ),
        "plan_hash": (
            _digest(plan_path) == report["plan"]["sha256"]
            == manifest["plan_sha256"]
        ),
        "source_identity": all(source_checks.values()),
        "completed_192": report["status"] == "COMPLETED" and len(rows) == 192,
        "no_cache_full_recompute": (
            report["generation_protocol"]["kv_cache"] is False
            and report["generation_protocol"]["full_prefix_recompute_per_token"]
            is True
        ),
        "all_first_tokens_valid": all(
            row["first_token_choice"] is not None for row in rows
        ),
        "grouped_no_winner": (
            grouped_execution["status"] == "COMPLETED"
            and grouped_execution["comparison_sha256"] == _digest(
                HERE / "raw/grouped_comparison.json"
            )
            and comparison["winner"] == "none"
        ),
        "training_bundles_match": all(
            training_runs[model]["bundles"]["final"]["manifest_sha256"]
            == model_specs[model]["manifest_sha256"]
            == report["model_identities"][model]["manifest_sha256"]
            for model in ("task", "semantic")
        ),
        "base_inline_accuracy": (
            _choice_accuracy(rows, "base", "inline", True) == (11, 16, 0.6875)
            and _choice_accuracy(rows, "base", "inline", False)
            == (12, 16, 0.75)
        ),
        "base_query_only_accuracy": (
            _choice_accuracy(rows, "base", "query_only", True)
            == (8, 16, 0.5)
            and _choice_accuracy(rows, "base", "query_only", False)
            == (12, 16, 0.75)
        ),
        "task_pair_metrics": (
            task_metrics["first_choice_changes"] == 0
            and task_metrics["full_sequence_changes"]
            == expected_task["full_sequence_changes"]
            and task_metrics["affected_changes"] == expected_task["affected_changes"]
            and task_metrics["unaffected_changes"]
            == expected_task["unaffected_changes"]
            and task_metrics["first_divergence"]
            == expected_task["first_divergence_token_positions_one_based"]
        ),
        "semantic_pair_metrics": (
            semantic_metrics["first_choice_changes"] == 0
            and semantic_metrics["full_sequence_changes"]
            == expected_semantic["full_sequence_changes"]
            and semantic_metrics["affected_changes"]
            == expected_semantic["affected_changes"]
            and semantic_metrics["unaffected_changes"]
            == expected_semantic["unaffected_changes"]
            and semantic_metrics["first_divergence"]
            == expected_semantic["first_divergence_token_positions_one_based"]
        ),
        "first_step_probability_displacement": all(
            _close(observed, expected)
            for observed, expected in (
                (task_affected_delta[0], first_displacement["task_affected_mean"]),
                (task_affected_delta[1], first_displacement["task_affected_max"]),
                (
                    task_unaffected_delta[0],
                    first_displacement["task_unaffected_mean"],
                ),
                (
                    task_unaffected_delta[1],
                    first_displacement["task_unaffected_max"],
                ),
                (
                    semantic_affected_delta[0],
                    first_displacement["semantic_affected_mean"],
                ),
                (
                    semantic_affected_delta[1],
                    first_displacement["semantic_affected_max"],
                ),
                (
                    semantic_unaffected_delta[0],
                    first_displacement["semantic_unaffected_mean"],
                ),
                (
                    semantic_unaffected_delta[1],
                    first_displacement["semantic_unaffected_max"],
                ),
            )
        ),
        "continuation_lengths": (
            sum(row["finish_reason"] == "eos" for row in rows) == 15
            and sum(len(row["generated_token_ids"]) == 16 for row in rows) == 177
        ),
    }
    result = {
        "status": "VERIFIED" if all(checks.values()) else "FAILED",
        "checks": checks,
        "file_checks": file_checks,
        "source_checks": source_checks,
        "target_model_rerun": False,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
