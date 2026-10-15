#!/usr/bin/env python3
"""Qualify a balanced Mistral-native label projection after the first gate blocked."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import torch

REPO = Path(__file__).resolve().parents[1]
import run_v14_mistral_prompt_gate as v1  # noqa: E402
from v14_prompt_binding import exact_suffix_token_ids  # noqa: E402
from v14_prompt_binding_v2 import render_demonstrated_mistral_prefix  # noqa: E402

PLAN_PATH = REPO / "configs/v14/MISTRAL_PROMPT_GATE_V2_PLAN.json"
PARENT_PLAN_PATH = REPO / "configs/v14/MISTRAL_PROMPT_GATE_PLAN.json"
PARENT_REPORT_PATH = REPO / "provenance/raw/v14_mistral_prompt_gate_20260907/report.json"
DIAGNOSTIC_PATH = REPO / "provenance/raw/v14_mistral_prompt_gate_20260907/diagnostic.json"


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


def _target_content(context: str | None, query: str) -> str:
    query = str(query).strip()
    if query.endswith("Answer:"):
        query = query[: -len("Answer:")].rstrip()
    question = (
        f"Question: {query}\n"
        "Reply with exactly Yes if the statement is true, or No if it is false."
    )
    return question if context is None else f"{context}\n\n{question}"


def _case_rows(
    records: list[dict[str, Any]],
    tokenizer: Any,
    *,
    candidate: dict[str, Any],
    route: str,
    model_type: str,
    suffixes: list[str],
    maximum_tokens: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = []
    descriptors = []
    candidate_rows: set[tuple[int, ...]] = set()
    for record_index, record in enumerate(records):
        for side in range(2):
            for query_index, query in enumerate(record["queries"]):
                content = _target_content(
                    None if route == "query_only" else str(record["contexts"][side]),
                    str(query),
                )
                rendered, descriptor = render_demonstrated_mistral_prefix(
                    tokenizer,
                    content,
                    renderer=candidate["renderer"],
                    model_type=model_type,
                )
                prefix_ids = None
                choice_ids = []
                for suffix in suffixes:
                    actual_prefix, answer = exact_suffix_token_ids(
                        tokenizer, rendered, suffix, require_one=True
                    )
                    if prefix_ids is None:
                        prefix_ids = actual_prefix
                    elif prefix_ids != actual_prefix:
                        raise ValueError("Candidate suffixes changed prompt identity")
                    choice_ids.append(answer[0])
                assert prefix_ids is not None
                if len(prefix_ids) > maximum_tokens:
                    raise ValueError("Rendered prompt exceeds the frozen token limit")
                if len(set(choice_ids)) != 2:
                    raise ValueError("Answer candidates are not distinct")
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
                        "target": int(record["answers"][side][query_index]),
                        "affected": bool(record["affected"][query_index]),
                        "prefix_ids": prefix_ids,
                        "candidate_ids": choice_ids,
                        "rendered_prompt_sha256": hashlib.sha256(
                            rendered.encode("utf-8")
                        ).hexdigest(),
                    }
                )
    if len(candidate_rows) != 1:
        raise ValueError("Candidate token IDs changed across cases")
    if len({_stable_hash(value) for value in descriptors}) != 1:
        raise ValueError("Prompt descriptor changed across cases")
    return rows, {
        "descriptor": descriptors[0],
        "candidate_ids": list(next(iter(candidate_rows))),
        "case_count": len(rows),
        "maximum_prompt_tokens": max(len(row["prefix_ids"]) for row in rows),
        "all_prefixes_exact_under_both_suffixes": True,
    }


def _score_split(
    model: Any,
    tokenizer: Any,
    records: list[dict[str, Any]],
    candidate: dict[str, Any],
    plan: dict[str, Any],
    *,
    split: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    summaries = {}
    tokenization = {}
    all_rows = []
    for route in ("query_only", "inline"):
        rows, binding = _case_rows(
            records,
            tokenizer,
            candidate=candidate,
            route=route,
            model_type=model.config.model_type,
            suffixes=plan["answer_suffixes"],
            maximum_tokens=plan["maximum_prompt_tokens"],
        )
        v1._score_rows(
            model,
            rows,
            pad_token_id=int(tokenizer.pad_token_id),
            batch_size=plan["batch_size"],
        )
        for row in rows:
            row.update(split=split, candidate_id=candidate["id"], route=route)
        all_rows.extend(rows)
        summaries[route] = v1._summarize(rows)
        tokenization[route] = binding
    return {
        "candidate": candidate,
        "tokenization": tokenization,
        "summaries": summaries,
        "gate": v1._gate(summaries, plan["gates"]),
    }, all_rows


def run(plan: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    started = time.monotonic()
    if output_dir.exists():
        raise ValueError("Output directory already exists")
    output_dir.mkdir(parents=True)
    if _source_identity(plan) != plan["source_identity"]:
        raise ValueError("Frozen source identity mismatch")
    for path, expected in (
        (PARENT_PLAN_PATH, plan["parent_prompt_plan_sha256"]),
        (PARENT_REPORT_PATH, plan["blocked_report_sha256"]),
        (DIAGNOSTIC_PATH, plan["diagnostic_sha256"]),
    ):
        if _digest(path) != expected:
            raise ValueError(f"Bound predecessor changed: {path.name}")
    parent_report = json.loads(PARENT_REPORT_PATH.read_text())
    if parent_report["status"] != "BLOCKED" or parent_report["holdout"] is not None:
        raise ValueError("V2 requires the calibration-blocked, holdout-unopened V1 report")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True).strip():
        raise ValueError("Run requires a clean isolated worktree")
    parent_plan = json.loads(PARENT_PLAN_PATH.read_text())
    observed_env = {key: os.environ.get(key) for key in parent_plan["required_environment"]}
    if observed_env != parent_plan["required_environment"]:
        raise ValueError("Runtime environment differs from the frozen parent plan")
    runtime = {
        "torch": str(torch.__version__),
        "transformers": version("transformers"),
        "python": sys.version.split()[0],
        "cuda": torch.version.cuda,
    }
    if runtime != parent_plan["expected_runtime"] or not torch.cuda.is_available():
        raise ValueError(f"Runtime differs from the frozen CUDA plan: {runtime}")
    torch.set_num_threads(parent_plan["cpu_threads"])
    torch.set_num_interop_threads(parent_plan["cpu_threads"])
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.set_float32_matmul_precision("highest")
    torch.cuda.set_per_process_memory_fraction(parent_plan["cuda_allocator_fraction"])
    torch.cuda.reset_peak_memory_stats()
    model_plan = parent_plan["model"]
    snapshot = Path(model_plan["snapshot"])
    before = v1._snapshot_inventory(snapshot, model_plan["max_snapshot_bytes"])
    if v1._content_anchor(before) != model_plan["snapshot_content_anchor"]:
        raise ValueError("Snapshot differs from the frozen content anchor")
    calibration_path = REPO / parent_plan["data"]["calibration"]["path"]
    holdout_path = REPO / parent_plan["data"]["holdout"]["path"]
    if _digest(calibration_path) != parent_plan["data"]["calibration"]["sha256"]:
        raise ValueError("Calibration corpus changed")
    if _digest(holdout_path) != parent_plan["data"]["holdout"]["sha256"]:
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
    calibration_records = v1._read_jsonl(calibration_path)
    candidates = {item["id"]: item for item in plan["candidates"]}
    calibration = {}
    calibration_rows = []
    for candidate_id in plan["candidate_order"]:
        item, rows = _score_split(
            model,
            tokenizer,
            calibration_records,
            candidates[candidate_id],
            plan,
            split="calibration",
        )
        item["calibration_gate"] = item.pop("gate")
        calibration[candidate_id] = item
        calibration_rows.extend(rows)
    selection = v1._selection(calibration, plan["candidate_order"])
    selected_id = selection["selected_candidate"]
    holdout = None
    holdout_rows = []
    if selected_id is not None:
        holdout_item, holdout_rows = _score_split(
            model,
            tokenizer,
            v1._read_jsonl(holdout_path),
            candidates[selected_id],
            plan,
            split="holdout",
        )
        holdout_item["qualification_gate"] = holdout_item.pop("gate")
        holdout = holdout_item
    parameter_identity_ok = all(
        identities[name] == (id(parameter), parameter._version, parameter.requires_grad)
        for name, parameter in model.named_parameters()
    )
    snapshot_ok = before == v1._snapshot_inventory(snapshot, model_plan["max_snapshot_bytes"])
    v1._write_jsonl(output_dir / "calibration_cases.jsonl", calibration_rows)
    if holdout_rows:
        v1._write_jsonl(output_dir / "holdout_cases.jsonl", holdout_rows)
    qualified = bool(
        holdout is not None
        and holdout["qualification_gate"]["qualified"]
        and parameter_identity_ok
        and snapshot_ok
    )
    return {
        "format": "latent-workspace-v14-mistral-prompt-gate-v2",
        "status": "QUALIFIED" if qualified else "BLOCKED",
        "created_utc": datetime.now(UTC).isoformat(),
        "elapsed_seconds": time.monotonic() - started,
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip(),
        "plan_sha256": _digest(PLAN_PATH),
        "source_identity": _source_identity(plan),
        "predecessors": {
            "v1_report_sha256": _digest(PARENT_REPORT_PATH),
            "diagnostic_sha256": _digest(DIAGNOSTIC_PATH),
        },
        "runtime": runtime,
        "calibration": calibration,
        "selection": selection,
        "holdout": holdout,
        "mistral_task_entry_qualified": qualified,
        "model_integrity": {
            "parameter_identity_versions_unchanged": parameter_identity_ok,
            "snapshot_inventory_unchanged": snapshot_ok,
        },
        "training_performed": False,
        "semantic_direction_tested": False,
        "cuda_peak_allocated_bytes": torch.cuda.max_memory_allocated(),
        "claim_boundary": plan["claim_boundary"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run(json.loads(PLAN_PATH.read_text()), args.output_dir.expanduser().resolve())
    (args.output_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "selected": report["selection"]["selected_candidate"],
                "holdout_gate": (
                    None
                    if report["holdout"] is None
                    else report["holdout"]["qualification_gate"]
                ),
                "elapsed_seconds": report["elapsed_seconds"],
            },
            indent=2,
        )
    )
    return 0 if report["status"] == "QUALIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
