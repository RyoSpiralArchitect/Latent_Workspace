#!/usr/bin/env python3
"""Qualify Mistral rendering/scoring on isolated one-edge evidence controls."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
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
import run_v14_mistral_prompt_gate_v2 as v2  # noqa: E402

PLAN_PATH = REPO / "configs/v14/MISTRAL_ATOMIC_INSTRUMENT_GATE_PLAN.json"
PARENT_PLAN_PATH = REPO / "configs/v14/MISTRAL_PROMPT_GATE_PLAN.json"
V2_REPORT_PATH = REPO / "provenance/raw/v14_mistral_prompt_gate_v2_20260907/report.json"
FACT = re.compile(r"- ([A-Za-z][A-Za-z0-9_]*) is ranked above ([A-Za-z][A-Za-z0-9_]*)\.")


def _digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _source_identity(plan: dict[str, Any]) -> dict[str, str]:
    return {name: _digest(REPO / name) for name in plan["source_identity"]}


def atomic_easy_view(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Retain one explicit evidence edge only for designated easy records."""
    output = copy.deepcopy(records)
    for record in output:
        if record["metadata"]["role"] != "easy":
            continue
        entities = set(record["metadata"]["query_entities"])
        contexts = []
        for side, context in enumerate(record["contexts"]):
            matches = []
            for line in str(context).splitlines()[1:]:
                match = FACT.fullmatch(line)
                if match is None:
                    raise ValueError("Atomic view encountered an unparsed fact")
                if {match[1], match[2]} == entities:
                    matches.append((line, match[1], match[2]))
            if len(matches) != 1:
                raise ValueError("Atomic easy view requires exactly one direct evidence edge")
            line, above, below = matches[0]
            original_entities = record["metadata"]["query_entities"]
            query_pairs = (original_entities, list(reversed(original_entities)))
            for query_index, query_entities in enumerate(query_pairs):
                expected = int(query_entities == [above, below])
                if int(record["answers"][side][query_index]) != expected:
                    raise ValueError("Atomic evidence direction disagrees with the symbolic answer")
            contexts.append(f"World facts. The ranking is transitive.\n{line}")
        record["contexts"] = contexts
        record["metadata"]["instrument_view"] = "isolated_direct_evidence_edge"
    return output


def run(plan: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    started = time.monotonic()
    if output_dir.exists():
        raise ValueError("Output directory already exists")
    output_dir.mkdir(parents=True)
    if _source_identity(plan) != plan["source_identity"]:
        raise ValueError("Frozen source identity mismatch")
    if _digest(PARENT_PLAN_PATH) != plan["parent_prompt_plan_sha256"]:
        raise ValueError("Parent prompt plan changed")
    if _digest(V2_REPORT_PATH) != plan["blocked_v2_report_sha256"]:
        raise ValueError("Blocked V2 report changed")
    v2_report = json.loads(V2_REPORT_PATH.read_text())
    if v2_report["status"] != "BLOCKED" or v2_report["holdout"] is not None:
        raise ValueError("Atomic gate requires blocked V2 with unopened holdout")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True).strip():
        raise ValueError("Run requires a clean isolated worktree")
    parent = json.loads(PARENT_PLAN_PATH.read_text())
    observed_env = {key: os.environ.get(key) for key in parent["required_environment"]}
    if observed_env != parent["required_environment"]:
        raise ValueError("Runtime environment differs from the frozen parent plan")
    runtime = {
        "torch": str(torch.__version__),
        "transformers": version("transformers"),
        "python": sys.version.split()[0],
        "cuda": torch.version.cuda,
    }
    if runtime != parent["expected_runtime"] or not torch.cuda.is_available():
        raise ValueError(f"Runtime differs from the frozen CUDA plan: {runtime}")
    torch.set_num_threads(parent["cpu_threads"])
    torch.set_num_interop_threads(parent["cpu_threads"])
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.set_float32_matmul_precision("highest")
    torch.cuda.set_per_process_memory_fraction(parent["cuda_allocator_fraction"])
    torch.cuda.reset_peak_memory_stats()
    model_plan = parent["model"]
    snapshot = Path(model_plan["snapshot"])
    before = v1._snapshot_inventory(snapshot, model_plan["max_snapshot_bytes"])
    if v1._content_anchor(before) != model_plan["snapshot_content_anchor"]:
        raise ValueError("Snapshot differs from the frozen content anchor")
    calibration_path = REPO / parent["data"]["calibration"]["path"]
    holdout_path = REPO / parent["data"]["holdout"]["path"]
    for path, split in ((calibration_path, "calibration"), (holdout_path, "holdout")):
        if _digest(path) != parent["data"][split]["sha256"]:
            raise ValueError(f"{split} corpus changed")
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
    candidate = plan["candidate"]
    calibration_records = atomic_easy_view(v1._read_jsonl(calibration_path))
    calibration, calibration_rows = v2._score_split(
        model,
        tokenizer,
        calibration_records,
        candidate,
        plan,
        split="calibration",
    )
    calibration["calibration_gate"] = calibration.pop("gate")
    holdout = None
    holdout_rows = []
    if calibration["calibration_gate"]["qualified"]:
        holdout, holdout_rows = v2._score_split(
            model,
            tokenizer,
            atomic_easy_view(v1._read_jsonl(holdout_path)),
            candidate,
            plan,
            split="holdout",
        )
        holdout["qualification_gate"] = holdout.pop("gate")
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
        "format": "latent-workspace-v14-mistral-atomic-instrument-gate-v1",
        "status": "QUALIFIED" if qualified else "BLOCKED",
        "created_utc": datetime.now(UTC).isoformat(),
        "elapsed_seconds": time.monotonic() - started,
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip(),
        "plan_sha256": _digest(PLAN_PATH),
        "source_identity": _source_identity(plan),
        "runtime": runtime,
        "instrument_view": "isolated_direct_evidence_edge",
        "calibration": calibration,
        "holdout": holdout,
        "renderer_and_choice_instrument_qualified": qualified,
        "full_context_task_qualified": False,
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
                "calibration_gate": report["calibration"]["calibration_gate"],
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
