#!/usr/bin/env python3
"""Offline publication replay; no model loads, retries, or receipt replacement."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

SOURCE = "beda279e3d07e6565831aaceca58f080e1044e4a"
PRIVATE = "raw/data/PRIVATE_AUDIT_INPUTS.json.gz"


def check(root, repo, *, published):
    sys.path.insert(0, str(repo / "src"))
    from latent_workspace import execution as ex
    from latent_workspace import world_expansion as wb

    omitted = {}
    if published:
        m = ex.read(root / "PUBLICATION_MANIFEST.json")
        actual = ex.manifest(root)
        actual.pop("PUBLICATION_MANIFEST.json")
        assert actual == m["included"], "Publication bytes/file set"
        omitted = m["omitted"]
        assert set(omitted) == {PRIVATE}
        assert m["source_commit"] == SOURCE and m["source_worktree_clean"]
    source = ex.read(root / "SOURCE_SEAL.json")
    assert source["source_commit"] == SOURCE and len(source["source_hashes"]) == 753
    for name, expected in source["source_hashes"].items():
        blob = subprocess.check_output(["git", "show", f"{SOURCE}:{name}"], cwd=repo)
        assert hashlib.sha256(blob).hexdigest() == expected, name
        if not published:
            assert ex.digest(repo / name) == expected
        elif name.startswith("src/"):
            assert ex.digest(repo / name) == expected, "Engine changed after tiny qualification"

    def files(directory, receipt):
        for name, metadata in receipt["files"].items():
            path = directory / name
            key = path.relative_to(root).as_posix()
            if key in omitted:
                assert omitted[key] == metadata
            else:
                assert (
                    path.stat().st_size == metadata["bytes"]
                    and ex.digest(path) == metadata["sha256"]
                )

    qualifications = {}
    for device in ("cpu", "cuda"):
        directory = root / "qualification" / device
        end, start = (ex.read(directory / f"{s}.json") for s in ("FINISHED", "STARTED"))
        assert start["seal"] == source and end["status"] == "TINY_V23_OBJECTIVE_AUDIT_PASS_NOT_7B"
        assert end["counts"] == dict(tests=296, failures=0, errors=0, skipped=0)
        suites = ElementTree.parse(directory / "TESTS.xml").getroot().iter("testsuite")
        assert sum(int(s.attrib["tests"]) for s in suites) == 296
        assert end["elapsed_seconds"] < 900
        if device == "cuda":
            assert 0 < end["peak_cuda_allocated_bytes"] <= 4 * ex.GIB
        files(directory, end)
        qualifications[device] = dict(
            counts=end["counts"],
            elapsed_seconds=end["elapsed_seconds"],
            peak_cuda_allocated_bytes=end.get("peak_cuda_allocated_bytes"),
        )
    child = ex.read(root / "raw/data/FINISHED.json")
    outer = ex.read(root / "raw/FINISHED.json")
    assert child["status"] == "V23_PREPARATION_COMPLETE_NOT_7B_OR_TRAINING"
    assert outer["status"] == "INCOMPLETE_NO_RETRY" and outer["error"] == "KeyError: 'pass_status'"
    assert outer["completed_roles"] == ["data"]
    files(root / "raw/data", child)
    files(root / "raw", outer)
    result = ex.read(root / "raw/data/PREPARATION.json")
    assert result == child["outcome"] == outer["summary"]
    assert result["native_model_forward_calls"] == result["teacher_target_files_written"] == 0
    assert all(result[k] == v for k, v in ex.CEILING.items())
    bank = root / "raw/data/bank"
    plan = ex.read(bank / "PLAN.json")
    assert ex.digest(repo / plan["prior_rows"]) == plan["prior_rows_sha256"]
    rows = wb.build(plan)
    assert wb.audit(rows, ex.read_gz(repo / plan["prior_rows"]), plan) == result["bank"]
    for split in ("train", "dev", "confirmation", "ood"):
        assert ex.read_gz(bank / f"{split}.json.gz") == [r for r in rows if r["split"] == split]
    tokens = ex.read_gz(root / "raw/data/TRAIN_TOKENS.json.gz")
    assert len(tokens) == result["unique_train_rows"] == 2016
    counts = Counter()
    for row in tokens:
        assert row["split"] == "train" and row["language"] == "en"
        assert len(row["labels"]) == len(row["parts"]) == len(row["input_ids"])
        assert row["supervised_tokens"] == sum(t != -100 for t in row["labels"])
        assert all((p == -1) == (label == -100) for p, label in zip(row["parts"], row["labels"]))
        counts.update(row["oracle_partition"]["parts"])
    assert dict(counts) == result["unique_train_part_tokens"]
    assert sum(counts.values()) == result["unique_train_supervised_tokens"]
    selection = ex.read(root / "raw/data/AUDIT_SELECTION.json")
    assert len(selection["world_keys"]) == 84 and len(set(selection["world_groups"])) == 14
    assert len(selection["preservation"]) == 12
    assert {r["role"] for r in selection["preservation"]} == {"instruction", "prose", "code"}
    assert selection["targets_status"] == "NOT_RUN" and selection["heldout_model_evaluations"] == 0
    meta = (
        omitted.get(PRIVATE)
        if published
        else dict(bytes=(root / PRIVATE).stat().st_size, sha256=ex.digest(root / PRIVATE))
    )
    assert meta["sha256"] == selection["private_inputs_sha256"]
    target_count = sum(r["supervised_tokens"] for r in selection["preservation"])
    assert target_count == result["planned_anchor_supervised_tokens"]
    assert target_count * 32768 * 4 == result["planned_full_vocab_fp32_target_bytes"]
    assert not list((root / "no-real-checkpoint-writes").glob("*"))
    return dict(
        status="OFFLINE_CHILD_RESULTS_VERIFIED_OUTER_DISPATCH_FAILED",
        source_commit=SOURCE,
        source_files=753,
        qualifications=qualifications,
        preparation=result,
        omitted_private_bytes=meta,
        outer_status=outer["status"],
        outer_error=outer["error"],
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("remote-snapshot", "verify"))
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--repo", required=True, type=Path)
    args = p.parse_args()
    result = check(args.root, args.repo, published=args.command == "verify")
    if args.command == "remote-snapshot":
        sys.path.insert(0, str(args.repo / "src"))
        from latent_workspace import execution as ex

        assert (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=args.repo, text=True).strip()
            == SOURCE
        )
        assert not subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"], cwd=args.repo
        )
        starts = [
            args.root / p
            for p in (
                "qualification/cpu/STARTED.json",
                "qualification/cuda/STARTED.json",
                "raw/STARTED.json",
                "raw/data/STARTED.json",
            )
        ]
        for path in starts:
            pid = ex.read(path)["pid"]
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            raise RuntimeError(f"Recorded PID is present: {pid}; inspect instead of snapshotting")
        all_files = ex.manifest(args.root)
        omitted = {PRIVATE: all_files.pop(PRIVATE)}
        receipt = dict(
            source_commit=SOURCE,
            source_worktree_clean=True,
            recorded_workers_absent=True,
            checked_at_utc=datetime.now(UTC).isoformat(),
            disk_free_bytes=shutil.disk_usage(args.root).free,
            gpu_processes=subprocess.check_output(
                ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader"],
                text=True,
            ),
            included=all_files,
            omitted=omitted,
            verifier_sha256=ex.digest(Path(__file__)),
            result=result,
        )
        ex.write_new(args.root / "PUBLICATION_MANIFEST.json", receipt)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
