#!/usr/bin/env python3
"""Calibration-only token-surface diagnosis after a blocked Mistral prompt gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import torch

REPO = Path(__file__).resolve().parents[1]
from v14_prompt_binding import exact_suffix_token_ids, render_functional_prefix  # noqa: E402

PLAN_PATH = REPO / "configs/v14/MISTRAL_PROMPT_DIAGNOSTIC_PLAN.json"
PARENT_PLAN_PATH = REPO / "configs/v14/MISTRAL_PROMPT_GATE_PLAN.json"
PARENT_REPORT_PATH = REPO / "provenance/raw/v14_mistral_prompt_gate_20260907/report.json"

INSTRUCTIONS = {
    "symmetric": (
        "Use the world facts to decide whether the ranking statement is true. "
        "If it is false, answer no; if it is true, answer yes. "
        "Output exactly one lowercase word: no or yes."
    ),
    "compact": (
        "Read the ranking facts and decide whether the final statement is true. "
        "Reply with exactly one word: no or yes."
    ),
}


def _digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _source_identity(plan: dict[str, Any]) -> dict[str, str]:
    return {name: _digest(REPO / name) for name in plan["source_identity"]}


def _records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _prompt_rows(
    records: list[dict[str, Any]],
    tokenizer: Any,
    candidate: dict[str, str],
    *,
    model_type: str,
) -> list[dict[str, Any]]:
    rows = []
    for record_index, record in enumerate(records):
        if record["metadata"]["role"] != "easy":
            continue
        for side in range(2):
            for query_index, query in enumerate(record["queries"]):
                elicited = f"{INSTRUCTIONS[candidate['instruction']]}\n\n{str(query).strip()}"
                content = f"{record['contexts'][side]}\n\n{elicited}"
                rendered, descriptor = render_functional_prefix(
                    tokenizer,
                    content,
                    renderer=candidate["renderer"],
                    model_type=model_type,
                )
                prefix_ids = list(tokenizer.encode(rendered, add_special_tokens=False))
                rows.append(
                    {
                        "record_index": record_index,
                        "record_id": record["id"],
                        "family_id": record["metadata"]["family_id"],
                        "side": side,
                        "query_index": query_index,
                        "target": int(record["answers"][side][query_index]),
                        "rendered": rendered,
                        "prefix_ids": prefix_ids,
                        "descriptor": descriptor.to_dict(),
                    }
                )
    return rows


@torch.inference_mode()
def _score(
    model: Any,
    tokenizer: Any,
    rows: list[dict[str, Any]],
    surfaces: list[dict[str, Any]],
    *,
    batch_size: int,
) -> None:
    device = next(model.parameters()).device
    for row in rows:
        row["surface_candidate_ids"] = {}
        for surface in surfaces:
            ids = []
            for suffix in surface["suffixes"]:
                prefix, answer = exact_suffix_token_ids(
                    tokenizer, row["rendered"], suffix, require_one=True
                )
                if prefix != row["prefix_ids"]:
                    raise ValueError("Surface candidate changed the prompt prefix")
                ids.append(answer[0])
            row["surface_candidate_ids"][surface["id"]] = ids
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        maximum = max(len(row["prefix_ids"]) for row in batch)
        ids = torch.full(
            (len(batch), maximum), int(tokenizer.pad_token_id), device=device, dtype=torch.long
        )
        mask = torch.zeros_like(ids)
        lengths = []
        for index, row in enumerate(batch):
            values = torch.tensor(row["prefix_ids"], device=device, dtype=torch.long)
            ids[index, : values.numel()] = values
            mask[index, : values.numel()] = 1
            lengths.append(values.numel())
        logits = model(input_ids=ids, attention_mask=mask, use_cache=False).logits
        for index, row in enumerate(batch):
            next_logits = logits[index, lengths[index] - 1].float()
            top_values, top_ids = torch.topk(next_logits, 12)
            row["top_tokens"] = [
                {
                    "id": int(token_id),
                    "text": tokenizer.decode([int(token_id)]),
                    "logit": float(value),
                }
                for value, token_id in zip(top_values.cpu(), top_ids.cpu(), strict=True)
            ]
            row["surfaces"] = {}
            for surface in surfaces:
                candidate_ids = row["surface_candidate_ids"][surface["id"]]
                values = [float(value) for value in next_logits[candidate_ids].cpu().tolist()]
                prediction = None if values[0] == values[1] else int(values[1] > values[0])
                row["surfaces"][surface["id"]] = {
                    "candidate_ids": candidate_ids,
                    "choice_logits": values,
                    "prediction": prediction,
                    "correct": None if prediction is None else prediction == row["target"],
                }
        del logits, ids, mask


@torch.inference_mode()
def _generate(model: Any, tokenizer: Any, rows: list[dict[str, Any]], indices: list[int]) -> None:
    device = next(model.parameters()).device
    for index in indices:
        row = rows[index]
        ids = torch.tensor([row["prefix_ids"]], device=device, dtype=torch.long)
        generated = model.generate(
            input_ids=ids,
            attention_mask=torch.ones_like(ids),
            do_sample=False,
            max_new_tokens=16,
            use_cache=True,
            eos_token_id=tokenizer.eos_token_id,
            pad_token_id=tokenizer.pad_token_id,
        )
        completion = generated[0, ids.shape[1] :].cpu().tolist()
        row["greedy"] = {
            "token_ids": completion,
            "text": tokenizer.decode(completion, skip_special_tokens=True),
        }


def _summary(rows: list[dict[str, Any]], surfaces: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for surface in surfaces:
        values = [row["surfaces"][surface["id"]] for row in rows]
        unknown = sum(row["prediction"] is None for row in values)
        result[surface["id"]] = {
            "correct": sum(row["correct"] is True for row in values),
            "denominator": len(values),
            "unknown_count": unknown,
            "accuracy": (
                sum(row["correct"] is True for row in values) / len(values)
                if unknown == 0
                else None
            ),
            "prediction_counts": dict(
                Counter(str(row["prediction"]) for row in values if row["prediction"] is not None)
            ),
            "candidate_ids": values[0]["candidate_ids"],
        }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output.expanduser().resolve()
    if output.exists():
        raise ValueError("Output already exists")
    plan = json.loads(PLAN_PATH.read_text())
    parent_plan = json.loads(PARENT_PLAN_PATH.read_text())
    parent_report = json.loads(PARENT_REPORT_PATH.read_text())
    if _source_identity(plan) != plan["source_identity"]:
        raise ValueError("Frozen source identity mismatch")
    if _digest(PARENT_PLAN_PATH) != plan["parent_prompt_plan_sha256"]:
        raise ValueError("Parent prompt plan changed")
    if _digest(PARENT_REPORT_PATH) != plan["blocked_report_sha256"]:
        raise ValueError("Blocked report changed")
    if parent_report["status"] != "BLOCKED" or parent_report["holdout"] is not None:
        raise ValueError("Diagnostic requires a blocked calibration-only parent")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True).strip():
        raise ValueError("Run requires a clean isolated worktree")
    observed_env = {key: os.environ.get(key) for key in parent_plan["required_environment"]}
    if observed_env != parent_plan["required_environment"]:
        raise ValueError("Runtime environment differs from the parent plan")
    model_plan = parent_plan["model"]
    data_path = REPO / parent_plan["data"]["calibration"]["path"]
    if _digest(data_path) != parent_plan["data"]["calibration"]["sha256"]:
        raise ValueError("Calibration corpus changed")
    from transformers import AutoModelForCausalLM, AutoTokenizer

    started = time.monotonic()
    tokenizer = AutoTokenizer.from_pretrained(
        model_plan["snapshot"], local_files_only=True, trust_remote_code=False
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        model_plan["snapshot"],
        local_files_only=True,
        trust_remote_code=False,
        dtype=torch.bfloat16,
        attn_implementation="sdpa",
    ).to("cuda").eval()
    records = _records(data_path)
    results = {}
    for candidate in plan["prompt_candidates"]:
        rows = _prompt_rows(records, tokenizer, candidate, model_type=model.config.model_type)
        _score(model, tokenizer, rows, plan["answer_surfaces"], batch_size=plan["batch_size"])
        _generate(model, tokenizer, rows, plan["greedy_row_indices"])
        results[candidate["id"]] = {
            "summary": _summary(rows, plan["answer_surfaces"]),
            "rows": [
                {key: value for key, value in row.items() if key not in {"rendered", "prefix_ids"}}
                for row in rows
            ],
        }
    report = {
        "format": "latent-workspace-v14-mistral-prompt-failure-diagnostic-v1",
        "status": "COMPLETE",
        "created_utc": datetime.now(UTC).isoformat(),
        "elapsed_seconds": time.monotonic() - started,
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip(),
        "plan_sha256": _digest(PLAN_PATH),
        "parent_report_sha256": _digest(PARENT_REPORT_PATH),
        "calibration_only": True,
        "holdout_scored": False,
        "training_performed": False,
        "results": results,
        "claim_boundary": (
            "This is a calibration-only diagnosis of first-token answer surfaces and a "
            "small fixed greedy sample after a blocked renderer gate. It selects nothing, "
            "does not score holdout, and is not task capability or semantic evidence."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({key: value["summary"] for key, value in results.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
