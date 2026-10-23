#!/usr/bin/env python3
"""FT03 offline replay; original FT01 verifier stays unchanged. No tensor forwards."""

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

SOURCE = "09addc856ba6f10da31054f1674c7547b1ab91ad"
PLAN = "configs/v24/RECRUITMENT_FT_03.json"
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


def stopped(folder, seal, plan, qualified, result):
    """Explain a sealed interruption without upgrading its null terminal count."""
    raw = folder / "raw"
    for path in (folder / "checks", raw, raw / "canary"):
        start, end = terminal(path, "INCOMPLETE_NO_RETRY", None)
        ex.require(start["seal"] == seal and start["plan"] == plan, "Stopped source/protocol")
        if path != folder / "checks":
            ex.require(start["qualification"] == qualified, "Stopped qualification")
        if path == raw / "canary":
            ex.require(
                end["error"] == "ValueError: Another GPU client; stop own job only",
                "Recorded contention stop",
            )
        else:
            ex.require(
                end["completed_roles"] == []
                and end["error"] == "ValueError: canary exited 1; stop without retry",
                "No completed role",
            )
    ex.require(
        not any((raw / r).exists() for r in ("replay", "inline", "workspace"))
        and not (folder / "training").exists()
        and not (folder / "CANARY_RETIREMENT.json").exists(),
        "No successor, training or retirement",
    )
    canary = raw / "canary"
    ex.require(
        not (canary / "step2.json").exists() and not (canary / "STEP2_PAYLOAD.json").exists(),
        "Second update missing",
    )
    initial = ex.read(canary / "INITIAL.json")
    step = ex.read(canary / "step1.json")
    saved = ex.read(canary / "CHECKPOINT_canary_step1.pt.json")
    schedule = ex.read(PREP / "SCHEDULE.json")
    ex.require(
        [r["key"] for r in step["rows"]] == schedule["canary"][0]
        and len(step["rows"]) == 4
        and sum(r["tokens"] for r in step["rows"]) == 1171,
        "Completed frozen first window",
    )
    for i, row in enumerate(step["rows"]):
        ex.require(ex.read(canary / f"step1_row{i}.json") == row, "Individual backward receipt")
    state = step["state"]
    ex.require(
        initial["completed_steps"] == 0
        and state["completed_steps"] == step["update"]["completed_steps"] == 1
        and state["tokens_seen"] == step["update"]["tokens_seen"] == 1171
        and state == ex.read(canary / "STATE_canary_step1.pt.json")
        and saved["completed_steps"] == 1
        and all(initial[k] != state[k] for k in ("native", "masters", "optimizer")),
        "Saved changed native/master/optimizer state, not verified replay",
    )
    resources = [json.loads(s) for s in (canary / "RESOURCES.jsonl").read_text().splitlines()]
    final = resources[-1]
    own = ex.read(canary / "STARTED.json")["pid"]
    foreign = [p for p in final["processes"] if p["pid"] != own]
    ex.require(
        final["phase"] == "saved:canary_step1.pt"
        and final["own_pid"] == own
        and any(p["pid"] == own for p in final["processes"])
        and len(foreign) == 1
        and foreign[0]["bytes"] > 0,
        "Observed separate GPU process at post-save boundary",
    )
    result.update(
        status="VERIFIED_INTERRUPTED_CHECKS_NOT_REPLAY_OR_TRAINING",
        terminal_native_weight_updates=None,
        observed_completed_canary_updates=1,
        planned_canary_updates=2,
        observed_backward_rows=4,
        planned_canary_backward_rows=8,
        observed_training_tokens=1171,
        scientific_updates=0,
        exact_next_update_replay="NOT_RUN",
        canary_checkpoint=saved,
        failed_phase=final["phase"],
        foreign_gpu_clients=foreign,
        peak_cuda_allocated_bytes=max(r.get("peak_allocated", 0) for r in resources),
        peak_cuda_reserved_bytes=max(r.get("peak_reserved", 0) for r in resources),
        terminal_sha256=ex.digest(raw / "FINISHED.json"),
    )
    return result


def storage_stopped(folder, seal, plan, qualified, result):
    """Observed two updates are not a complete canary or exact next-update replay."""
    raw, canary = folder / "raw", folder / "raw/canary"
    for path in (folder / "checks", raw, canary):
        start, end = terminal(path, "INCOMPLETE_NO_RETRY", None)
        ex.require(start["seal"] == seal and start["plan"] == plan, "Stopped source/protocol")
        if path != folder / "checks":
            ex.require(start["qualification"] == qualified, "Stopped qualification")
        if path == canary:
            ex.require(end["error"] == "ValueError: Forecast disk envelope", "Exact storage stop")
        else:
            ex.require(
                end["completed_roles"] == []
                and end["error"] == "ValueError: canary exited 1; stop without retry",
                "No completed role",
            )
    ex.require(
        not any((raw / r).exists() for r in ("replay", "inline", "workspace"))
        and not (canary / "STEP2_PAYLOAD.json").exists()
        and not (folder / "CANARY_RETIREMENT.json").exists()
        and not (folder / "training").exists(),
        "Retain missing payload/replay/training",
    )
    schedule = ex.read(PREP / "SCHEDULE.json")["canary"]
    cumulative = 0
    first = None
    for step, keys in enumerate(schedule, 1):
        value = ex.read(canary / f"step{step}.json")
        ex.require(
            [r["key"] for r in value["rows"]] == keys and len(keys) == 4, "Frozen canary windows"
        )
        for i, row in enumerate(value["rows"]):
            ex.require(row == ex.read(canary / f"step{step}_row{i}.json"), "Individual rows")
        cumulative += sum(r["tokens"] for r in value["rows"])
        ex.require(
            value["state"]["completed_steps"] == value["update"]["completed_steps"] == step
            and value["state"]["tokens_seen"] == value["update"]["tokens_seen"] == cumulative,
            "Recorded native update/cursor",
        )
        if step == 1:
            first = value
    ex.require(len(schedule) == 2 and cumulative == 2220, "Two recorded windows, 2220 targets")
    saved = ex.read(canary / "CHECKPOINT_canary_step1.pt.json")
    ex.require(
        first["state"] == ex.read(canary / "STATE_canary_step1.pt.json")
        and saved["completed_steps"] == 1
        and saved["bytes"] == 29004378444,
        "Only step 1 saved",
    )
    old = ex.read(
        ROOT / "provenance/engineering/v24_recruitment_ft01_20261023/furnace/raw/canary/step1.json"
    )
    ex.require(old == first, "Whole first update reproduces FT01 despite new source identity")
    host = [json.loads(s) for s in (canary / "HOST_RESOURCES.jsonl").read_text().splitlines()]
    last = host[-1]
    ex.require(
        host[-2]["phase"] == "step2:complete"
        and last["phase"] == "before_checkpoint"
        and last["forecast_bytes"] == 32 * ex.GIB
        and last["disk_free_bytes"] >= plan["resources"]["disk_free_gib"] * ex.GIB
        and last["disk_free_bytes"] - last["forecast_bytes"]
        < plan["resources"]["disk_free_gib"] * ex.GIB,
        "Read-only payload gate nevertheless forecast another 32 GiB file",
    )
    resources = [json.loads(s) for s in (canary / "RESOURCES.jsonl").read_text().splitlines()]
    own = ex.read(canary / "STARTED.json")["pid"]
    ex.require(
        all(p["pid"] == own for r in resources for p in r["processes"]),
        "No observed foreign GPU client",
    )
    result.update(
        status="VERIFIED_STORAGE_STOP_NOT_REPLAY_OR_TRAINING",
        terminal_native_weight_updates=None,
        observed_completed_canary_updates=2,
        planned_canary_updates=2,
        observed_backward_rows=8,
        observed_training_tokens=2220,
        scientific_updates=0,
        exact_next_update_replay="NOT_RUN",
        step2_payload="NOT_WRITTEN",
        canary_checkpoint=saved,
        first_update_exactly_matches_ft01=True,
        failed_phase=last["phase"],
        disk_free_bytes_at_failure=last["disk_free_bytes"],
        disk_forecast_bytes_at_failure=last["forecast_bytes"],
        peak_cuda_allocated_bytes=max(r.get("peak_allocated", 0) for r in resources),
        peak_cuda_reserved_bytes=max(r.get("peak_reserved", 0) for r in resources),
        terminal_sha256=ex.digest(raw / "FINISHED.json"),
    )
    return result


def verify(folder, phase="checks"):
    folder = Path(folder)
    ex.require(
        phase in ("qualification", "stopped", "storage-stopped", "checks", "training"),
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
        counts = dict(tests=608, failures=0, errors=0, skipped=0)
        xml = ElementTree.parse(path / "TESTS.xml")
        actual = {k: sum(int(s.get(k, 0)) for s in xml.iter("testsuite")) for k in counts}
        ex.require(
            start["seal"] == seal
            and start["plan"] == plan
            and start["device"] == device
            and end["counts"] == actual == counts
            and end["pytest_exit_code"] == 0,
            "608/device qualified",
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
        tests_per_device=608,
        qualification_seconds=durations,
        local_model_forwards=0,
        local_weight_body_rehash=False,
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
    )
    if phase == "qualification":
        return result
    if phase == "stopped":
        return stopped(folder, seal, plan, qualified, result)
    if phase == "storage-stopped":
        return storage_stopped(folder, seal, plan, qualified, result)
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
    result.update(
        status="CHECKS_COMPLETE_NOT_SCIENTIFIC_FT_OR_QUALITY",
        exact_next_update_replay=True,
        resources=resources,
        canary_checkpoint=saved,
        native_executed_updates=3,
        checks_terminal_sha256=ex.digest(folder / "checks/FINISHED.json"),
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
        choices=("qualification", "stopped", "storage-stopped", "checks", "training"),
        default="checks",
    )
    args = parser.parse_args()
    print(ex.canonical(verify(args.bundle, args.phase)))
