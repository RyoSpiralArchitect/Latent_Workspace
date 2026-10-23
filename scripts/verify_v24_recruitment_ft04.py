#!/usr/bin/env python3
"""FT04 offline replay; original FT01 verifier stays unchanged. No tensor forwards."""

import argparse
import hashlib
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from qualification_isolation_v2 import validate_audit  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402

SOURCE = "4b69c6b0d604f4947b7075e40430b9b8f113f4ad"
PLAN = "configs/v24/RECRUITMENT_FT_04.json"
PREP = ROOT / "provenance/engineering/v24_recruitment_preparation01_20261023/furnace/raw/data/bank"


def terminal(folder, status, updates):
    ex.require(not any(p.is_symlink() for p in folder.rglob("*")), "No artifact symlinks")
    end = ex.read(folder / "FINISHED.json")
    files = ex.manifest(folder)
    files.pop("FINISHED.json")
    ex.require(end["status"] == status and end["files"] == files, "Complete terminal manifest")
    ex.require(end["native_weight_updates"] == updates, "Actual update denominator")
    for k, v in ex.CEILING.items():
        if k != "native_weight_updates":
            ex.require(end[k] == v, "Unchanged activity and quality ceiling")
    return ex.read(folder / "STARTED.json"), end


def verify_accounting(path, role, plan):
    """Recheck the real receipts, not just the presence of new operation names."""
    rows = [json.loads(s) for s in (path / "HOST_RESOURCES.jsonl").read_text().splitlines()]
    writes = {"canary": 1, "replay": 0, "inline": 2, "workspace": 1}[role]
    forecast = 32 * ex.GIB + (writes - 1) * plan["checkpoint_max_bytes"] if writes else 0
    ex.require(
        rows[0]["phase"] == "admission" and rows[0]["forecast_bytes"] == forecast,
        "Role-wide future file reserve",
    )
    expected = {
        "canary": [("checkpoint_write", 32 * ex.GIB), ("payload_hash", 0)],
        "replay": [("checkpoint_read", 0), ("payload_hash", 0)],
        "inline": [("checkpoint_write", 32 * ex.GIB)],
        "workspace": [("checkpoint_write", 32 * ex.GIB)],
    }[role]
    observed = [
        (r["phase"].removeprefix("before_snapshot:"), r["forecast_bytes"])
        for r in rows
        if r["phase"].startswith("before_snapshot:")
    ]
    ex.require(observed == expected, "Exact operation-aware reserves")
    for row in rows:
        ex.require(row["phase"] != "before_checkpoint", "No inherited ambiguous admission")
        ex.require(
            row["disk_free_bytes"] - row["forecast_bytes"] >= 50 * ex.GIB,
            "Unchanged disk floor including all write forecasts",
        )
        host = 100 if row["phase"] == "admission" else 24
        if row["phase"].startswith("before_snapshot:"):
            host += 32
        ex.require(row["available_bytes"] >= host * ex.GIB, "Host floor and snapshot reserve")
    return dict(
        admission_forecast_bytes=forecast,
        operations=observed,
        min_disk_free_bytes=min(r["disk_free_bytes"] for r in rows),
    )


def verify(folder, phase="checks"):
    folder = Path(folder)
    ex.require(
        phase in ("qualification", "checks", "training"),
        "Explicit verification stage",
    )
    seal = ex.read(folder / "SOURCE_SEAL.json")
    ex.require(seal["source_commit"] == SOURCE, "Exact execution source")
    archive = subprocess.check_output(
        [
            "git",
            "archive",
            SOURCE,
            "--",
            "src",
            "scripts",
            "tests",
            "configs",
            "data/v10",
            "pyproject.toml",
        ],
        cwd=ROOT,
    )
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        bodies = {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}
    hashes = {p: hashlib.sha256(b).hexdigest() for p, b in bodies.items()}
    ex.require(hashes == seal["source_hashes"], "Full source seal")
    plan = json.loads(bodies[PLAN])
    ex.require(plan == ex.read(ROOT / PLAN), "Frozen numerical/data protocol")
    ex.require(ex.digest(PREP / "MANIFEST.json") == plan["data_manifest_sha256"], "Prepared bank")
    qualified = {}
    durations = {}
    for device in ("cpu", "cuda"):
        path = folder / "qualification" / device
        start, end = terminal(path, "V24_ROUTE_FT_TINY_PASS_NOT_7B", 0)
        counts = dict(tests=643, failures=0, errors=0, skipped=0)
        xml = ElementTree.parse(path / "TESTS.xml")
        actual = {k: sum(int(s.get(k, 0)) for s in xml.iter("testsuite")) for k in counts}
        ex.require(
            start["seal"] == seal
            and start["plan"] == plan
            and start["device"] == device
            and end["counts"] == actual == counts
            and end["pytest_exit_code"] == 0,
            "643/device qualified",
        )
        qualified[device] = ex.manifest(path)
        durations[device] = end["elapsed_seconds"]
    isolation = folder / "qualification/CPU_ISOLATION.json"
    validate_audit(
        ex.read(isolation),
        ex.digest(folder / "qualification/cpu/FINISHED.json"),
        ex.read(folder / "qualification/cpu/STARTED.json")["pid"],
        folder / "qualification/CPU_OBSERVER.jsonl",
    )
    qualified["cpu_isolation"] = dict(sha256=ex.digest(isolation))
    qualified["cpu_observer"] = dict(sha256=ex.digest(folder / "qualification/CPU_OBSERVER.jsonl"))
    result = dict(
        status="QUALIFICATION_ONLY_NO_7B_RESULT",
        source_commit=SOURCE,
        source_files=len(hashes),
        tests_per_device=643,
        qualification_seconds=durations,
        local_model_forwards=0,
        local_weight_body_rehash=False,
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
    )
    if phase == "qualification":
        return result
    raw = folder / "raw"
    start, end = terminal(folder / "checks", "V24_ROUTE_CHECKS_COMPLETE_NOT_TRAINING", 3)
    ex.require(
        start["seal"] == seal
        and start["plan"] == plan
        and end["completed_roles"] == ["canary", "replay"],
        "Exact checks source/roles",
    )
    resources = {}
    for role, updates in (("canary", 2), ("replay", 1)):
        path = raw / role
        begin, finish = terminal(path, f"V24_RECRUITMENT_{role.upper()}_COMPLETE", updates)
        ex.require(
            begin["seal"] == seal
            and begin["plan"] == plan
            and begin["qualification"] == qualified
            and end["role_manifests"][role] == ex.manifest(path),
            "Role provenance",
        )
        resources[role] = dict(elapsed_seconds=finish["elapsed_seconds"], **finish["outcome"])
        resources[role]["storage_accounting"] = verify_accounting(path, role, plan)
    expected, actual = ex.read(raw / "canary/step2.json"), ex.read(raw / "replay/step2.json")
    ex.require(expected == actual, "Exact next-update losses/gradients/native/master/moments/RNG")
    replay = ex.read(raw / "replay/REPLAY.json")
    ex.require(
        replay["exact"] is True
        and replay["state_sha256"] == ex.read(raw / "canary/STEP2_PAYLOAD.json")["state_sha256"],
        "Exact payload replay",
    )
    saved = ex.read(raw / "canary/CHECKPOINT_canary_step1.pt.json")
    restore = ex.read(raw / "replay/RESTORE.json")
    ex.require(
        restore["exact"] is True and restore["checkpoint"] == saved, "Fresh checkpoint restore"
    )
    schedule = ex.read(PREP / "SCHEDULE.json")
    for step, keys in enumerate(schedule["canary"], 1):
        value = ex.read(raw / "canary" / f"step{step}.json")
        ex.require([r["key"] for r in value["rows"]] == keys, "Frozen mixed-route canary rows")
        for i, row in enumerate(value["rows"]):
            ex.require(
                ex.read(raw / "canary" / f"step{step}_row{i}.json") == row,
                "Individual backward receipts",
            )
        previous = ROOT / "provenance/engineering/v24_recruitment_ft03_20261023/furnace/raw/canary"
        ex.require(
            value == ex.read(previous / f"step{step}.json"),
            "Both completed numerical updates exactly reproduce FT03",
        )
    result.update(
        status="CHECKS_COMPLETE_NOT_SCIENTIFIC_FT_OR_QUALITY",
        exact_next_update_replay=True,
        resources=resources,
        canary_checkpoint=saved,
        native_executed_updates=3,
        checks_terminal_sha256=ex.digest(folder / "checks/FINISHED.json"),
        both_canary_updates_exactly_match_ft03=True,
    )
    if phase == "checks":
        return result
    retired = ex.read(folder / "CANARY_RETIREMENT.json")
    ex.require(
        retired["status"] == "SPENT_CANARY_RETIRED_AFTER_EXACT_REPLAY"
        and retired["source_commit"] == SOURCE
        and retired["checkpoint"] == saved
        and retired["files_deleted"] == 1
        and retired["replay_receipt_sha256"] == ex.digest(raw / "replay/REPLAY.json"),
        "Separate spent-canary journal",
    )
    begin, finish = terminal(folder / "training", "V24_ROUTE_FT_32_EACH_COMPLETE_NOT_QUALITY", 64)
    ex.require(
        begin["seal"] == seal
        and begin["plan"] == plan
        and finish["completed_roles"] == ["inline", "workspace"],
        "Scientific phase",
    )
    for role in ("inline", "workspace"):
        path = raw / role
        begin, end = terminal(path, f"V24_RECRUITMENT_{role.upper()}_COMPLETE", 32)
        ex.require(
            begin["seal"] == seal
            and begin["plan"] == plan
            and begin["qualification"] == qualified
            and finish["role_manifests"][role] == ex.manifest(path),
            "Training provenance",
        )
        ex.require(
            end["outcome"]["training_tokens_seen"] == 21112
            and end["outcome"]["backward_rows"] == 538,
            "Complete matched budget",
        )
        cumulative = 0
        for step, keys in enumerate(schedule["training"], 1):
            value = ex.read(path / f"step{step}.json")
            ex.require([r["key"] for r in value["rows"]] == keys, "Exact frozen row order")
            cumulative += sum(r["tokens"] for r in value["rows"])
            ex.require(
                value["state"]["tokens_seen"] == cumulative
                and value["state"]["completed_steps"] == step,
                "Complete cursor",
            )
        ex.require(cumulative == 21112, "Exact training token sum")
        result[role] = dict(
            outcome=end["outcome"],
            storage_accounting=verify_accounting(path, role, plan),
            elapsed_seconds=end["elapsed_seconds"],
            checkpoint=ex.read(path / f"CHECKPOINT_{role}_step32.pt.json"),
        )
    begin, finish = terminal(raw, "V24_ROUTE_FT_32_EACH_COMPLETE_NOT_QUALITY", 67)
    ex.require(
        begin["seal"] == seal
        and finish["completed_roles"] == ["canary", "replay", "inline", "workspace"],
        "Whole execution terminal",
    )
    result.update(
        status="PAIRED_NATIVE_FT_COMPLETE_NOT_QUALITY",
        native_executed_updates=67,
        scientific_updates=64,
        training_tokens_per_arm=21112,
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument(
        "--phase",
        choices=("qualification", "checks", "training"),
        default="checks",
    )
    args = parser.parse_args()
    print(ex.canonical(verify(args.bundle, args.phase)))
