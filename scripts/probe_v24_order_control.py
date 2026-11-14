#!/usr/bin/env python3
"""Pinned-tokenizer, data-only V24 output-order audit; never loads a model."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from latent_workspace import execution as ex  # noqa: E402
from latent_workspace import recruitment_bank as bank  # noqa: E402
from latent_workspace import recruitment_order as order  # noqa: E402

PLAN = ROOT / "configs/v24/ORDER_CONTROL_01.json"
GIB = 2**30


def inspect(bundle, plan, tokenizer):
    """Pure receipt/target comparison; no model forward or output mutation."""
    ex.require(bundle.is_absolute() and bundle.resolve() == bundle, "Exact source bundle path")
    ex.require(
        ex.digest(bundle / "MANIFEST.json") == plan["source_bank_manifest_sha256"],
        "Pinned bank manifest",
    )
    manifest = ex.read(bundle / "MANIFEST.json")
    files = ex.manifest(bundle)
    files.pop("MANIFEST.json")
    ex.require(files == manifest["files"], "Closed input file set")
    for name, key in (
        ("PUBLIC_SYNTHETIC.json.gz", "source_bank_public_sha256"),
        ("SCHEDULE.json", "source_schedule_sha256"),
    ):
        ex.require(ex.digest(bundle / name) == plan[key], f"Pinned {name}")

    raw, schedule = (
        ex.read_gz(bundle / "PUBLIC_SYNTHETIC.json.gz"),
        ex.read(bundle / "SCHEDULE.json"),
    )
    original = order.project_pair(raw, tokenizer, "answer_first")
    changed = order.project_pair(raw, tokenizer, "steps_first")
    ex.require(set(schedule) == {"training", "canary", "development"}, "Frozen schedule shape")

    changed_rows = {}
    for route in bank.ROUTES:
        saved = {row["key"]: row for row in ex.read_gz(bundle / f"PRIVATE_{route}.json.gz")}
        prior = {row["key"]: row for row in original[route]}
        after = {row["key"]: row for row in changed[route]}
        ex.require(
            prior.keys() == after.keys() and prior.keys() <= saved.keys(), "Same source rows"
        )
        ex.require(
            all(row == saved[key] for key, row in prior.items()), "Historical projection exact"
        )
        changed_rows[route] = 0
        for key, before in prior.items():
            now = after[key]
            for field in (
                "key",
                "group_id",
                "split",
                "role",
                "family",
                "side",
                "mode",
                "memory_ids",
                "duplicate_aliases",
            ):
                ex.require(before[field] == now[field], f"Unchanged {field}")
            ex.require(
                before["input_ids"][: -len(before["target_ids"])]
                == now["input_ids"][: -len(now["target_ids"])],
                "Unchanged query prefix",
            )
            ex.require(
                now["labels"]
                == [-100] * (len(now["input_ids"]) - len(now["target_ids"])) + now["target_ids"],
                "Target-only causal labels",
            )
            if now["role"] != "reasoning" or now["mode"] in ("absent", "unrelated"):
                ex.require(before == now, "Only present reasoning target changes")
            else:
                ex.require(before["target_ids"] != now["target_ids"], "Order visibly changed")
                changed_rows[route] += 1
    ex.require(changed_rows["inline"] == changed_rows["workspace"], "Matched changed rows")

    by_original = {row["key"]: row for row in original["inline"]}
    by_changed = {row["key"]: row for row in changed["inline"]}
    baseline_tokens = changed_tokens = changed_occurrences = scheduled_rows = 0
    delta_by_family = {}
    for window in schedule["training"]:
        for key in window:
            ex.require(
                key in by_original and by_original[key]["split"] == "train", "Train-only schedule"
            )
            left, right = by_original[key], by_changed[key]
            baseline_tokens += left["supervised_tokens"]
            changed_tokens += right["supervised_tokens"]
            scheduled_rows += 1
            if left["target_ids"] != right["target_ids"]:
                changed_occurrences += 1
                family = right["family"]
                delta_by_family[family] = (
                    delta_by_family.get(family, 0)
                    + right["supervised_tokens"]
                    - left["supervised_tokens"]
                )

    ex.require(scheduled_rows == plan["expected_baseline_scheduled_rows"], "Scheduled rows")
    ex.require(
        baseline_tokens == plan["expected_baseline_scheduled_targets"], "Baseline target budget"
    )
    ex.require(
        changed_tokens == plan["expected_steps_first_scheduled_targets"], "Order target budget"
    )
    ex.require(
        changed_tokens - baseline_tokens == plan["expected_token_delta"],
        "Observed tokenization delta",
    )
    return dict(
        status="V24_ORDER_CONTROL_DATA_PILOT_COMPLETE_NOT_TRAINING",
        original_projection_matches_frozen_private=True,
        route_target_parity=True,
        same_queries_and_memory=True,
        changed_unique_present_reasoning_rows_per_route=changed_rows["inline"],
        scheduled_rows=scheduled_rows,
        baseline_supervised_tokens=baseline_tokens,
        steps_first_supervised_tokens=changed_tokens,
        token_delta=changed_tokens - baseline_tokens,
        changed_scheduled_occurrences=changed_occurrences,
        token_delta_by_family=delta_by_family,
        new_model_forwards=0,
        native_weight_updates=0,
        checkpoint_saves=0,
        judge_calls=0,
        weight_deletions=0,
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", required=True)
    args = parser.parse_args()
    plan = ex.read(PLAN)
    ex.require(plan["schema"] == "ltws-v24-order-control-data-pilot-v1", "Frozen pilot plan")
    ex.require(
        plan["new_model_forwards"]
        == plan["native_weight_updates"]
        == plan["checkpoint_saves"]
        == plan["judge_calls"]
        == plan["weight_deletions"]
        == 0,
        "Data-only scope",
    )
    actual_source = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    ex.require(
        actual_source == args.source and len(actual_source) == 40, "Committed source identity"
    )
    ex.require(
        not subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT
        ),
        "Clean committed source",
    )
    ex.require(args.output.is_absolute() and not args.output.exists(), "Exclusive output")
    ex.require(
        shutil.disk_usage(args.output.parent).free >= plan["resource_floor_gib"] * GIB,
        "Data-only disk floor",
    )

    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        os.environ[key] = "1"
    from huggingface_hub import snapshot_download
    from transformers import AutoTokenizer

    manifest = ex.read(args.bundle / "MANIFEST.json")
    identity = manifest["tokenizer"]
    cache = Path(
        snapshot_download(
            identity["repository"], revision=identity["revision"], local_files_only=True
        )
    )
    ex.require(
        all(ex.digest(cache / name) == digest for name, digest in identity["files"].items()),
        "Pinned tokenizer files",
    )
    tokenizer = AutoTokenizer.from_pretrained(
        identity["repository"],
        revision=identity["revision"],
        local_files_only=True,
        trust_remote_code=False,
    )
    ex.require(
        hashlib.sha256(tokenizer.chat_template.encode()).hexdigest()
        == identity["chat_template_sha256"],
        "Pinned chat template",
    )
    ex.require(
        tokenizer.eos_token_id == 2 and len(tokenizer) == 32768 and tokenizer.is_fast,
        "Tokenizer shape",
    )

    result = inspect(args.bundle, plan, tokenizer)
    result.update(
        source_commit=actual_source,
        plan_sha256=ex.digest(PLAN),
        input_manifest_sha256=ex.digest(args.bundle / "MANIFEST.json"),
        input_source_commit=manifest["source_commit"],
        tokenizer=identity,
        execution_utc=dt.datetime.now(dt.UTC).isoformat(),
    )
    args.output.mkdir(exist_ok=False)
    ex.write_new(args.output / "RESULTS.json", result)
    ex.write_new(
        args.output / "FINISHED.json",
        dict(status=result["status"], source_commit=actual_source, files=ex.manifest(args.output)),
    )
    print(
        ex.canonical(
            {
                k: result[k]
                for k in (
                    "status",
                    "scheduled_rows",
                    "baseline_supervised_tokens",
                    "steps_first_supervised_tokens",
                    "token_delta",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
