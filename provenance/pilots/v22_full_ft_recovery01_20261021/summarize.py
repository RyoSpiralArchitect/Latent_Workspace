#!/usr/bin/env python3
"""Read-only publication replay for the completed V22 recovery (no model imports).

The training source remains frozen at 13c1192. This later publication helper
reads its receipts; it is not an execution or checkpoint-resume entry point.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import runpy
from collections import Counter
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(root):
    repo = root.parents[2]
    bundle = root / "furnace"
    data = repo / "provenance/data/v22_english_mixture01_20261021/furnace"
    verifier = runpy.run_path(str(repo / "scripts/verify_v22_full_ft.py"))
    verified = verifier["verify"](bundle, repo, data)
    if verified["status"] != "OFFLINE_V22_COMPLETE_NOT_QUALITY":
        raise ValueError("Publication requires the complete terminal, not partial progress")
    raw = bundle / "raw"
    plan = read(raw / "STARTED.json")["plan"]
    old_terminal = repo / plan["recovery_of"]["terminal"]
    if digest(old_terminal) != plan["recovery_of"]["terminal_sha256"]:
        raise ValueError("Original failure terminal differs from the sealed plan")
    _, old_end = verifier["terminal"](old_terminal.parent)
    if old_end["status"] != "INCOMPLETE_NO_RETRY":
        raise ValueError("The original failed trial must remain failed")
    retirement_path = (
        repo / "provenance/inventory/v22_failed_canary_retirement_20261021/DELETE_FINISHED.json"
    )
    retirement = read(retirement_path)
    if (
        retirement["status"] != "RETIRED_ONE_APPROVED_OLD_CANARY"
        or retirement["files_deleted"] != 1
    ):
        raise ValueError("Exactly one separate authorized old-body retirement")
    roles = ("canary", "replay", "train_a", "train_b")
    ends = {role: read(raw / role / "FINISHED.json") for role in roles}
    before = read(raw / "train_a/DEV_BASE.json")
    after = read(raw / "train_b/DEV_STEP32.json")
    row_comparisons = []
    for old, new in zip(before["rows"], after["rows"], strict=True):
        if any(old[k] != new[k] for k in ("key", "bucket", "supervised_tokens")):
            raise ValueError("Development pair binding")
        n = old["supervised_tokens"]
        row_comparisons.append(
            dict(
                key=old["key"],
                bucket=old["bucket"],
                tokens=n,
                before_loss_sum=old["loss_sum"],
                after_loss_sum=new["loss_sum"],
                before_nll=old["loss_sum"] / n,
                after_nll=new["loss_sum"] / n,
                delta_nll=(new["loss_sum"] - old["loss_sum"]) / n,
            )
        )
    development = {}
    for bucket in ("ALL", *sorted(before["tokens_by_bucket"])):
        rows = [r for r in row_comparisons if bucket == "ALL" or r["bucket"] == bucket]
        n = sum(r["tokens"] for r in rows)
        old = sum(r["before_loss_sum"] for r in rows) / n
        new = sum(r["after_loss_sum"] for r in rows) / n
        development[bucket] = dict(
            rows=len(rows),
            tokens=n,
            before_nll=old,
            after_nll=new,
            delta_nll=new - old,
            relative_change=(new - old) / old,
            rows_lower_nll=sum(r["delta_nll"] < 0 for r in rows),
            rows_higher_nll=sum(r["delta_nll"] > 0 for r in rows),
            rows_equal_nll=sum(r["delta_nll"] == 0 for r in rows),
        )
    index = {
        r["key"]: r for r in json.loads(gzip.decompress((data / "index.json.gz").read_bytes()))
    }
    step_summaries, changed, all_names, exposure, token_exposure = (
        [],
        set(),
        set(),
        Counter(),
        Counter(),
    )
    for step in range(1, 33):
        role = "train_a" if step <= 16 else "train_b"
        record = read(raw / role / f"step{step}.json")
        changes = record["update"]["changes"]
        all_names.update(c["name"] for c in changes)
        changed.update(c["name"] for c in changes if c["native_changed_elements"] > 0)
        for row in record["rows"]:
            kind = index[row["key"]]["role"]
            exposure[kind] += 1
            token_exposure[kind] += row["tokens"]
        step_summaries.append(
            dict(
                step=step,
                rows=len(record["rows"]),
                tokens=sum(r["tokens"] for r in record["rows"]),
                preclip_native_l2=record["update"]["preclip_native_l2"],
                master_tensors_changed=sum(c["master_changed"] for c in changes),
                native_tensors_changed=sum(c["native_changed_elements"] > 0 for c in changes),
                native_element_changes=sum(c["native_changed_elements"] for c in changes),
            )
        )
    resources, checkpoints = {}, []
    for role in roles:
        folder = raw / role
        cache = [read(path) for path in sorted(folder.glob("CACHE_*.json"))]
        gpu, host = lines(folder / "RESOURCES.jsonl"), lines(folder / "HOST_RESOURCES.jsonl")
        resources[role] = dict(
            elapsed_seconds=ends[role]["elapsed_seconds"],
            peak_cuda_allocated_bytes=ends[role]["outcome"]["peak_cuda_allocated_bytes"],
            peak_cuda_reserved_bytes=ends[role]["outcome"]["peak_cuda_reserved_bytes"],
            peak_host_rss_bytes=ends[role]["outcome"]["peak_host_rss_bytes"],
            gpu_guard_samples=len(gpu),
            min_gpu_guard_free_bytes=min(r["free_bytes"] for r in gpu),
            host_guard_samples=len(host),
            min_host_available_bytes=min(r["available_bytes"] for r in host),
            min_disk_free_bytes=min(r["disk_free_bytes"] for r in host),
            cache_boundaries=len(cache),
            cache_elapsed_seconds=sum(r["elapsed_seconds"] for r in cache),
            cache_min_after_free_bytes=min(r["after"]["free_bytes"] for r in cache),
            cache_live_allocation_equal=all(
                r["before"]["allocated_bytes"] == r["after"]["allocated_bytes"] for r in cache
            ),
        )
        checkpoints.extend(read(p) for p in sorted(folder.glob("CHECKPOINT_*.json")))
    inputs = [
        bundle / "SOURCE_SEAL.json",
        raw / "FINISHED.json",
        bundle / "checks/FINISHED.json",
        bundle / "training/FINISHED.json",
        data / "MANIFEST.json",
        data / "SCHEDULE.json",
        old_terminal,
        retirement_path,
    ]
    inputs += [raw / role / "FINISHED.json" for role in roles]
    inputs += [bundle / "qualification" / device / "FINISHED.json" for device in ("cpu", "cuda")]
    return dict(
        schema="v22-recovery01-publication-summary-v1",
        verification=verified,
        input_sha256={p.relative_to(repo).as_posix(): digest(p) for p in inputs},
        qualification={
            d: read(bundle / "qualification" / d / "FINISHED.json")["counts"]
            for d in ("cpu", "cuda")
        },
        phase_elapsed_seconds={
            p: read(bundle / p / "FINISHED.json")["elapsed_seconds"] for p in ("checks", "training")
        },
        updates=dict(
            training=32,
            canary=ends["canary"]["native_weight_updates"],
            replay=ends["replay"]["native_weight_updates"],
            physical_total=sum(end["native_weight_updates"] for end in ends.values()),
        ),
        training=dict(
            rows=sum(exposure.values()),
            unique_rows=len(
                {
                    r["key"]
                    for role in ("train_a", "train_b")
                    for p in (raw / role).glob("step[0-9]*.json")
                    if "_row" not in p.name
                    for r in read(p)["rows"]
                }
            ),
            supervised_tokens=sum(token_exposure.values()),
            rows_by_role=dict(exposure),
            tokens_by_role=dict(token_exposure),
            physical_parameter_tensors=len(all_names),
            ever_native_changed_tensors=len(changed),
            never_native_changed_names=sorted(all_names - changed),
            steps=step_summaries,
        ),
        resources=resources,
        checkpoints=checkpoints,
        preserved_old_failure=dict(
            status=old_end["status"],
            raw_files_including_terminal=len(old_end["files"]) + 1,
            same_canary_step_records={
                str(step): read(old_terminal.parent / "canary" / f"step{step}.json")
                == read(raw / "canary" / f"step{step}.json")
                for step in (1, 2)
            },
        ),
        separate_retirement=retirement,
        development=dict(
            interpretation="FIXED_DEV_NLL_ONLY_NOT_NON_REGRESSION",
            lower_nll_is_better=True,
            bucket_results=development,
            paired_rows=row_comparisons,
            prompt_selection_changed=False,
            new_sequences=0,
        ),
        claim_ceiling=dict(
            old_expression_gate="FAIL",
            winner="none",
            non_regression="NOT_ESTABLISHED",
            training_role_weight_deletions=0,
            separately_authorized_workflow_weight_deletions=1,
            new_sequences=0,
            judge_calls=0,
            independent_unseen_benchmark=False,
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", type=Path, help="Compare a saved summary; never writes it")
    args = parser.parse_args()
    result = summarize(Path(__file__).resolve().parent)
    if args.verify is not None:
        if read(args.verify) != result:
            raise ValueError("Saved publication summary differs from replay")
        print("PUBLICATION_SUMMARY_REPLAY_MATCH")
    else:
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
