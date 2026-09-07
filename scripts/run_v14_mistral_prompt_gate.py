#!/usr/bin/env python3
"""Select and qualify one Mistral functional-task prompt projection; never train."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import torch

REPO = Path(__file__).resolve().parents[1]

from v14_prompt_binding import (  # noqa: E402
    exact_suffix_token_ids,
    render_functional_prefix,
)

PLAN_PATH = REPO / "configs/v14/MISTRAL_PROMPT_GATE_PLAN.json"
SYMMETRIC_INSTRUCTION = (
    "Use the world facts to decide whether the ranking statement is true. "
    "If it is false, answer no; if it is true, answer yes. "
    "Output exactly one lowercase word: no or yes."
)
COMPACT_INSTRUCTION = (
    "Read the ranking facts and decide whether the final statement is true. "
    "Reply with exactly one word: no or yes."
)


def _digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _source_identity(plan: dict[str, Any]) -> dict[str, str]:
    return {name: _digest(REPO / name) for name in plan["source_identity"]}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"Non-object JSONL row at {path}:{line_number}")
            rows.append(value)
    return rows


def _snapshot_inventory(path: Path, byte_limit: int) -> list[dict[str, Any]]:
    files = sorted(item for item in path.rglob("*") if item.is_file())
    if not files or len(files) > 128 or not any(item.suffix == ".safetensors" for item in files):
        raise ValueError("Expected a bounded local safetensors snapshot")
    if sum(item.stat().st_size for item in files) > byte_limit:
        raise ValueError("Model snapshot exceeds the frozen byte limit")
    result = []
    for item in files:
        stat = item.stat()
        result.append(
            {
                "path": str(item.relative_to(path)),
                "resolved_path": str(item.resolve()),
                "bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "ctime_ns": stat.st_ctime_ns,
                "sha256": _digest(item),
            }
        )
    return result


def _content_anchor(inventory: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"path": row["path"], "bytes": row["bytes"], "sha256": row["sha256"]}
        for row in inventory
    ]


def _elicited_query(query: str, instruction: str) -> str:
    query = str(query).strip()
    if instruction == "symmetric":
        prefix = SYMMETRIC_INSTRUCTION
    elif instruction == "compact":
        prefix = COMPACT_INSTRUCTION
    else:
        raise ValueError(f"Unsupported instruction style: {instruction!r}")
    return f"{prefix}\n\n{query}"


def _case_rows(
    records: list[dict[str, Any]],
    tokenizer: Any,
    *,
    candidate: dict[str, Any],
    route: str,
    model_type: str,
    separator: str,
    maximum_tokens: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    descriptors: list[dict[str, Any]] = []
    candidate_rows: set[tuple[int, ...]] = set()
    for record_index, record in enumerate(records):
        contexts = record["contexts"]
        queries = record["queries"]
        answers = record["answers"]
        choices = record["choices"]
        for side in range(2):
            for query_index, query in enumerate(queries):
                elicited = _elicited_query(query, candidate["instruction"])
                content = elicited if route == "query_only" else separator.join(
                    (str(contexts[side]), elicited)
                )
                rendered, descriptor = render_functional_prefix(
                    tokenizer,
                    content,
                    renderer=candidate["renderer"],
                    model_type=model_type,
                )
                choice_ids = []
                prefix_ids: list[int] | None = None
                for suffix in choices:
                    actual_prefix, suffix_ids = exact_suffix_token_ids(
                        tokenizer, rendered, str(suffix), require_one=True
                    )
                    if prefix_ids is None:
                        prefix_ids = actual_prefix
                    elif actual_prefix != prefix_ids:
                        raise ValueError("Candidate choices produced different prompt prefixes")
                    choice_ids.append(suffix_ids[0])
                assert prefix_ids is not None
                if len(prefix_ids) > maximum_tokens:
                    raise ValueError("Rendered prompt exceeds the frozen token limit")
                if len(set(choice_ids)) != len(choice_ids):
                    raise ValueError("Candidate choices do not map to distinct tokens")
                candidate_rows.add(tuple(choice_ids))
                descriptor_dict = descriptor.to_dict()
                descriptors.append(descriptor_dict)
                metadata = record["metadata"]
                rows.append(
                    {
                        "record_index": record_index,
                        "record_id": record["id"],
                        "family_id": metadata["family_id"],
                        "role": metadata["role"],
                        "variant": metadata["variant"],
                        "template": metadata["template"],
                        "orientation": metadata["orientation"],
                        "primary_hop": int(metadata["primary_hop"]),
                        "side": side,
                        "query_index": query_index,
                        "target": int(answers[side][query_index]),
                        "affected": bool(record["affected"][query_index]),
                        "prefix_ids": prefix_ids,
                        "candidate_ids": choice_ids,
                        "rendered_prompt_sha256": hashlib.sha256(
                            rendered.encode("utf-8")
                        ).hexdigest(),
                    }
                )
    if len(candidate_rows) != 1:
        raise ValueError("Candidate token IDs differ across rendered prefixes")
    if len({_stable_hash(value) for value in descriptors}) != 1:
        raise ValueError("Prompt binding descriptor changed across cases")
    return rows, {
        "descriptor": descriptors[0],
        "candidate_ids": list(next(iter(candidate_rows))),
        "case_count": len(rows),
        "maximum_prompt_tokens": max(len(row["prefix_ids"]) for row in rows),
        "all_prefixes_exact_under_both_suffixes": True,
    }


@torch.inference_mode()
def _score_rows(
    model: Any,
    rows: list[dict[str, Any]],
    *,
    pad_token_id: int,
    batch_size: int,
) -> None:
    device = next(model.parameters()).device
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        maximum = max(len(row["prefix_ids"]) for row in batch)
        ids = torch.full(
            (len(batch), maximum), pad_token_id, dtype=torch.long, device=device
        )
        mask = torch.zeros_like(ids)
        lengths = []
        for index, row in enumerate(batch):
            values = torch.tensor(row["prefix_ids"], dtype=torch.long, device=device)
            ids[index, : values.numel()] = values
            mask[index, : values.numel()] = 1
            lengths.append(values.numel())
        output = model(input_ids=ids, attention_mask=mask, use_cache=False, return_dict=True)
        for index, row in enumerate(batch):
            logits = output.logits[index, lengths[index] - 1, row["candidate_ids"]].float()
            values = [float(value) for value in logits.cpu().tolist()]
            row["choice_logits"] = values
            row["yes_minus_no"] = values[1] - values[0]
            row["prediction"] = None if values[0] == values[1] else int(values[1] > values[0])
            row["correct"] = (
                None if row["prediction"] is None else row["prediction"] == row["target"]
            )
        del output, ids, mask


def _metric(rows: list[dict[str, Any]]) -> dict[str, Any]:
    denominator = len(rows)
    unknown = sum(row["prediction"] is None for row in rows)
    correct = sum(row["correct"] is True for row in rows)
    predictions = Counter(str(row["prediction"]) for row in rows if row["prediction"] is not None)
    targets = Counter(str(row["target"]) for row in rows)
    label_recall = {}
    for label in (0, 1):
        subset = [row for row in rows if row["target"] == label]
        label_unknown = sum(row["prediction"] is None for row in subset)
        label_correct = sum(row["correct"] is True for row in subset)
        label_recall[str(label)] = {
            "correct": label_correct,
            "denominator": len(subset),
            "unknown_count": label_unknown,
            "value": label_correct / len(subset) if label_unknown == 0 else None,
            "bounds": [label_correct / len(subset), (label_correct + label_unknown) / len(subset)],
        }
    return {
        "correct": correct,
        "denominator": denominator,
        "unknown_count": unknown,
        "accuracy": correct / denominator if unknown == 0 else None,
        "accuracy_bounds": [correct / denominator, (correct + unknown) / denominator],
        "prediction_counts": dict(sorted(predictions.items())),
        "target_counts": dict(sorted(targets.items())),
        "distinct_predicted_classes": len(predictions),
        "label_recall": label_recall,
        "mean_target_margin": sum(
            (1.0 if row["target"] == 1 else -1.0) * row["yes_minus_no"] for row in rows
        )
        / denominator,
    }


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "overall": _metric(rows),
        "roles": {
            role: _metric([row for row in rows if row["role"] == role])
            for role in ("easy", "primary")
        },
        "hops": {
            str(hop): _metric(
                [row for row in rows if row["role"] == "primary" and row["primary_hop"] == hop]
            )
            for hop in (2, 3, 4)
        },
        "templates": {
            template: _metric([row for row in rows if row["template"] == template])
            for template in ("outrank", "ranked_above")
        },
    }


def _known_accuracy(metric: dict[str, Any]) -> float:
    return float(metric["accuracy"]) if metric["accuracy"] is not None else -math.inf


def _minimum_recall(metric: dict[str, Any]) -> float:
    values = [item["value"] for item in metric["label_recall"].values()]
    if not all(value is not None for value in values):
        return -math.inf
    return min(float(value) for value in values)


def _gate(
    summaries: dict[str, dict[str, Any]], thresholds: dict[str, Any]
) -> dict[str, Any]:
    query_easy = summaries["query_only"]["roles"]["easy"]
    inline_easy = summaries["inline"]["roles"]["easy"]
    gain = _known_accuracy(inline_easy) - _known_accuracy(query_easy)
    checks = {
        "complete_known_easy_measurements": (
            query_easy["unknown_count"] == 0 and inline_easy["unknown_count"] == 0
        ),
        "inline_easy_accuracy": _known_accuracy(inline_easy)
        >= float(thresholds["minimum_inline_easy_accuracy"]),
        "inline_easy_both_label_recall": _minimum_recall(inline_easy)
        >= float(thresholds["minimum_inline_easy_label_recall"]),
        "inline_easy_distinct_predictions": inline_easy["distinct_predicted_classes"] == 2,
        "inline_minus_query_easy_accuracy": gain
        >= float(thresholds["minimum_inline_minus_query_easy_accuracy"]),
        "balanced_easy_targets": len(set(inline_easy["target_counts"].values())) == 1,
    }
    return {
        "qualified": all(checks.values()),
        "checks": checks,
        "inline_minus_query_easy_accuracy": gain if math.isfinite(gain) else None,
        "thresholds": thresholds,
    }


def _selection(
    candidates: dict[str, dict[str, Any]], order: list[str]
) -> dict[str, Any]:
    eligible = []
    for index, candidate_id in enumerate(order):
        item = candidates[candidate_id]
        if not item["calibration_gate"]["qualified"]:
            continue
        inline = item["summaries"]["inline"]
        score = [
            _known_accuracy(inline["roles"]["easy"]),
            _minimum_recall(inline["roles"]["easy"]),
            _known_accuracy(inline["roles"]["primary"]),
            -index,
        ]
        eligible.append((score, candidate_id))
    eligible.sort(reverse=True)
    return {
        "selected_candidate": eligible[0][1] if eligible else None,
        "eligible_candidates": [candidate_id for _score, candidate_id in eligible],
        "selection_scores": {candidate_id: score for score, candidate_id in eligible},
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            compact = {key: value for key, value in row.items() if key != "prefix_ids"}
            handle.write(json.dumps(compact, sort_keys=True, ensure_ascii=False) + "\n")


def run(plan: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    started = time.monotonic()
    if output_dir.exists():
        raise ValueError("Output directory already exists")
    output_dir.mkdir(parents=True)
    if _source_identity(plan) != plan["source_identity"]:
        raise ValueError("Frozen source identity mismatch")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True).strip():
        raise ValueError("Run requires a clean isolated worktree")
    environment = {key: os.environ.get(key) for key in plan["required_environment"]}
    if environment != plan["required_environment"]:
        raise ValueError(f"Environment differs from frozen plan: {environment}")
    runtime = {
        "torch": str(torch.__version__),
        "transformers": version("transformers"),
        "python": sys.version.split()[0],
        "cuda": torch.version.cuda,
    }
    if runtime != plan["expected_runtime"] or not torch.cuda.is_available():
        raise ValueError(f"Runtime differs from frozen CUDA plan: {runtime}")
    torch.set_num_threads(plan["cpu_threads"])
    torch.set_num_interop_threads(plan["cpu_threads"])
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.set_float32_matmul_precision("highest")
    torch.cuda.set_per_process_memory_fraction(plan["cuda_allocator_fraction"])
    torch.cuda.reset_peak_memory_stats()

    model_plan = plan["model"]
    snapshot = Path(model_plan["snapshot"])
    before = _snapshot_inventory(snapshot, model_plan["max_snapshot_bytes"])
    if _content_anchor(before) != model_plan["snapshot_content_anchor"]:
        raise ValueError("Snapshot differs from the frozen content anchor")
    calibration_path = REPO / plan["data"]["calibration"]["path"]
    holdout_path = REPO / plan["data"]["holdout"]["path"]
    if _digest(calibration_path) != plan["data"]["calibration"]["sha256"]:
        raise ValueError("Calibration corpus changed")
    if _digest(holdout_path) != plan["data"]["holdout"]["sha256"]:
        raise ValueError("Holdout corpus changed")

    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        snapshot, local_files_only=True, trust_remote_code=False
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        snapshot,
        local_files_only=True,
        trust_remote_code=False,
        dtype=torch.bfloat16,
        attn_implementation="sdpa",
    ).to("cuda").eval()
    identities = {
        name: (id(parameter), parameter._version, parameter.requires_grad)
        for name, parameter in model.named_parameters()
    }
    calibration_records = _read_jsonl(calibration_path)
    candidate_results: dict[str, dict[str, Any]] = {}
    all_calibration_rows = []
    candidates = {item["id"]: item for item in plan["candidates"]}
    for candidate_id in plan["candidate_order"]:
        candidate = candidates[candidate_id]
        summaries = {}
        tokenization = {}
        for route in ("query_only", "inline"):
            rows, binding = _case_rows(
                calibration_records,
                tokenizer,
                candidate=candidate,
                route=route,
                model_type=model.config.model_type,
                separator=plan["prompt_separator"],
                maximum_tokens=plan["maximum_prompt_tokens"],
            )
            _score_rows(
                model,
                rows,
                pad_token_id=int(tokenizer.pad_token_id),
                batch_size=plan["batch_size"],
            )
            for row in rows:
                row.update(split="calibration", candidate_id=candidate_id, route=route)
            all_calibration_rows.extend(rows)
            summaries[route] = _summarize(rows)
            tokenization[route] = binding
        candidate_results[candidate_id] = {
            "candidate": candidate,
            "tokenization": tokenization,
            "summaries": summaries,
            "calibration_gate": _gate(summaries, plan["gates"]),
        }
    selection = _selection(candidate_results, plan["candidate_order"])
    selected_id = selection["selected_candidate"]
    holdout_result = None
    all_holdout_rows: list[dict[str, Any]] = []
    if selected_id is not None:
        selected = candidates[selected_id]
        summaries = {}
        tokenization = {}
        holdout_records = _read_jsonl(holdout_path)
        for route in ("query_only", "inline"):
            rows, binding = _case_rows(
                holdout_records,
                tokenizer,
                candidate=selected,
                route=route,
                model_type=model.config.model_type,
                separator=plan["prompt_separator"],
                maximum_tokens=plan["maximum_prompt_tokens"],
            )
            _score_rows(
                model,
                rows,
                pad_token_id=int(tokenizer.pad_token_id),
                batch_size=plan["batch_size"],
            )
            for row in rows:
                row.update(split="holdout", candidate_id=selected_id, route=route)
            all_holdout_rows.extend(rows)
            summaries[route] = _summarize(rows)
            tokenization[route] = binding
        holdout_result = {
            "tokenization": tokenization,
            "summaries": summaries,
            "qualification_gate": _gate(summaries, plan["gates"]),
        }
    parameter_identity_ok = all(
        identities[name] == (id(parameter), parameter._version, parameter.requires_grad)
        for name, parameter in model.named_parameters()
    )
    after = _snapshot_inventory(snapshot, model_plan["max_snapshot_bytes"])
    snapshot_ok = before == after
    _write_jsonl(output_dir / "calibration_cases.jsonl", all_calibration_rows)
    if all_holdout_rows:
        _write_jsonl(output_dir / "holdout_cases.jsonl", all_holdout_rows)
    qualified = bool(
        holdout_result is not None
        and holdout_result["qualification_gate"]["qualified"]
        and parameter_identity_ok
        and snapshot_ok
    )
    return {
        "format": "latent-workspace-v14-mistral-prompt-gate-v1",
        "status": "QUALIFIED" if qualified else "BLOCKED",
        "started_utc": datetime.now(UTC).isoformat(),
        "elapsed_seconds": time.monotonic() - started,
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip(),
        "plan_sha256": _digest(PLAN_PATH),
        "source_identity": _source_identity(plan),
        "runtime": runtime,
        "environment": environment,
        "model": {
            "model_type": model.config.model_type,
            "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
            "parameter_identity_versions_unchanged": parameter_identity_ok,
            "snapshot_inventory_unchanged": snapshot_ok,
        },
        "calibration": candidate_results,
        "selection": selection,
        "holdout": holdout_result,
        "mistral_task_entry_qualified": qualified,
        "training_performed": False,
        "free_generation_performed": False,
        "cuda_peak_allocated_bytes": torch.cuda.max_memory_allocated(),
        "claim_boundary": (
            "Qualification applies only to the frozen Mistral snapshot, renderer, and "
            "synthetic one-hop easy controls. Primary multi-hop rows are descriptive. "
            "It does not establish workspace semantics, training benefit, generalization, "
            "cache-mediated amplification, or free-chat behavior."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    plan = json.loads(PLAN_PATH.read_text())
    report = run(plan, args.output_dir.expanduser().resolve())
    (args.output_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": report["status"],
        "selected": report["selection"]["selected_candidate"],
        "holdout_gate": (
            None if report["holdout"] is None else report["holdout"]["qualification_gate"]
        ),
        "elapsed_seconds": report["elapsed_seconds"],
    }, indent=2))
    return 0 if report["status"] == "QUALIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
