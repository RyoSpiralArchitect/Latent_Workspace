#!/usr/bin/env python3
"""Frozen 64-request local teacher inspection. No retries or training admission."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import traceback
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import run_source_sealed as source  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402
from latent_workspace import world_bank as wb  # noqa: E402

ENTRY = "scripts/run_native_teacher_inspection.py"
PLAN = "configs/v1_0/TEACHER_INSPECTION_01.json"
SCHEMA = {
    "type": "object",
    "properties": {
        "question": {"type": "string"},
        "answer": {"type": "string"},
        "answer_value": {"type": "string"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["question", "answer", "answer_value", "evidence_ids"],
    "additionalProperties": False,
}


def validate_plan(plan):
    ex.require(plan["planned_requests"] == 64 and plan["retries"] == 0, "Fixed no-retry scope")
    ex.require(plan["host"] == "127.0.0.1", "Loopback only")
    ex.require(
        plan["native_weight_updates"] == plan["judge_calls"] == plan["training_admissions"] == 0,
        "Inspection, not training or judging",
    )
    ex.require(len(plan["weights"]) == 6, "Exactly six official shards")
    for name, size, digest in plan["weights"]:
        ex.require(Path(name).name == name and size > 0, "Safe shard identity")
        ex.require(re.fullmatch("[0-9a-f]{64}", digest), "SHA-256 syntax")


def request_body(item, index, plan):
    row = item["row"]
    ex.require(row["split"] == "train", "Teacher cannot see evaluation rows")
    if item["kind"] == "world":
        system = (
            "Create a candidate training example from the supplied fictional facts. "
            "Rephrase the question naturally without changing what it asks. Answer it in "
            "one or two complete sentences, retaining the necessary supporting details. "
            "Do not invent facts or change names, quantities, dates or versions. "
            "Return exactly a JSON object with question, answer, answer_value and evidence_ids. "
            "Copy the canonical answer value and ordered evidence IDs into their fields. "
            "The answer sentence must contain the canonical value. This is a language "
            "rendering task, not independent verification of the supplied answer."
        )
        payload = {k: row[k] for k in ("facts", "query", "answer_value", "evidence_ids")}
    else:
        system = (
            "Create a high-quality candidate instruction response. Keep the instruction's "
            "meaning, language and constraints. Be concise. Return exactly a JSON object "
            "with question, answer, answer_value and evidence_ids. Put the original "
            "instruction in question, your response in answer, an empty string in "
            "answer_value, and an empty list in evidence_ids."
        )
        payload = {"instruction": row["query"]}
    return {
        **plan["request"],
        "seed": plan["seed_start"] + index,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)},
        ],
        "response_format": {"type": "json_object", "schema": SCHEMA},
    }


def classify(response, item):
    result = dict(
        status="INVALID_RESPONSE",
        training_approved=False,
        semantic_equivalence="UNREVIEWED",
        usage=response.get("usage"),
    )
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        return result
    choice = choices[0]
    result["finish_reason"] = choice.get("finish_reason")
    if result["finish_reason"] != "stop":
        result["status"] = "TRUNCATED" if result["finish_reason"] == "length" else "NON_STOP"
        return result
    content = choice.get("message", {}).get("content")
    if not isinstance(content, str):
        return result
    try:
        candidate = json.loads(content)
    except (ValueError, TypeError):
        result["status"] = "INVALID_JSON"
        return result
    checks = wb.inspect_candidate(candidate, item)
    result.update(candidate=candidate, checks=checks)
    result["status"] = (
        "STRUCTURE_PASS_SEMANTICS_UNREVIEWED" if checks["structural_pass"] else "STRUCTURE_FAIL"
    )
    return result


def summarize(outcomes, planned=64):
    tokens = Counter()
    for value in outcomes:
        usage = value.get("usage")
        if isinstance(usage, dict):
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                if type(usage.get(key)) is int:
                    tokens[key] += usage[key]
    return dict(
        planned_requests=planned,
        attempted_requests=len(outcomes),
        unattempted_requests=planned - len(outcomes),
        statuses=dict(Counter(o["status"] for o in outcomes)),
        usage=dict(tokens),
        semantic_approvals=0,
        training_admissions=0,
        native_weight_updates=0,
        judge_calls=0,
        non_regression="NOT_ESTABLISHED",
    )


def freeze(args, plan, seal):
    bank = args.bank
    metadata = ex.read(bank / "MANIFEST.json")
    for name, identity in metadata["files"].items():
        ex.require(ex.digest(bank / name) == identity["sha256"], f"Bank bytes: {name}")
    items = ex.read(bank / "teacher_inputs.json")
    ex.require(len(items) == 64, "Exactly 64 selected items")
    args.output.mkdir(parents=True, exist_ok=False)
    ex.write_new(args.output / "PLAN.json", plan)
    ex.write_new(args.output / "SOURCE.json", seal)
    ex.write_new(args.output / "INPUTS.json", items)
    requests = [
        dict(index=i, row_id=item["row"]["row_id"], body=request_body(item, i, plan))
        for i, item in enumerate(items)
    ]
    ex.write_new(args.output / "REQUESTS.json", requests)
    ex.write_new(
        args.output / "FROZEN.json",
        dict(
            files=ex.manifest(args.output),
            bank_manifest_sha256=ex.digest(bank / "MANIFEST.json"),
            request_count=64,
        ),
    )


def verify_frozen(output, plan):
    frozen = ex.read(output / "FROZEN.json")
    for name, identity in frozen["files"].items():
        ex.require(ex.digest(output / name) == identity["sha256"], f"Frozen bytes: {name}")
    ex.require(ex.read(output / "PLAN.json") == plan, "Teacher plan drift")
    requests, items = ex.read(output / "REQUESTS.json"), ex.read(output / "INPUTS.json")
    ex.require(len(requests) == len(items) == frozen["request_count"] == 64, "Count drift")
    for i, (request, item) in enumerate(zip(requests, items, strict=True)):
        ex.require(
            request
            == dict(index=i, row_id=item["row"]["row_id"], body=request_body(item, i, plan)),
            "Request reconstruction differs",
        )
    return requests, items


def resources(plan, *, admission=False, allowed_pids=()):
    raw = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"], text=True
    ).split()
    ex.require(len(raw) == 1, "One visible device")
    gpu_free = int(raw[0]) * 2**20
    processes = subprocess.check_output(
        ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"], text=True
    ).split()
    ex.require(not (set(map(int, processes)) - set(allowed_pids)), "Other GPU workload")
    host = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    host_free = int(host["MemAvailable"].split()[0]) * 1024
    disk = shutil.disk_usage(ROOT).free
    limits = plan["resources"]
    ex.require(
        gpu_free >= limits["gpu_admission_free_gib" if admission else "gpu_floor_gib"] * ex.GIB,
        "GPU free floor",
    )
    ex.require(
        host_free
        >= limits["host_admission_available_gib" if admission else "host_floor_gib"] * ex.GIB,
        "Host free floor",
    )
    ex.require(disk >= limits["disk_free_gib"] * ex.GIB, "Disk free floor")
    return dict(gpu_free_bytes=gpu_free, host_available_bytes=host_free, disk_free_bytes=disk)


def server_command(args, plan):
    runtime = plan["runtime"]
    return [
        str(args.runtime / "llama-b11756" / "llama-server"),
        "-m",
        str(args.weights / plan["weights"][0][0]),
        "--host",
        plan["host"],
        "--port",
        str(plan["port"]),
        "-ngl",
        str(runtime["gpu_layers"]),
        "-c",
        str(runtime["context"]),
        "-t",
        str(runtime["threads"]),
        "-np",
        str(runtime["parallel"]),
        "-fa",
        "on",
        "--alias",
        plan["request"]["model"],
        "--jinja",
    ]


def verify_runtime_files(runtime_dir, runtime):
    """Bind extracted code/libraries to the pinned official archive bytes too."""
    identities = {}
    for key in ("binary_archive", "cuda_archive"):
        archive = runtime_dir / runtime[key]
        ex.require(ex.digest(archive) == runtime[key + "_sha256"], "Runtime archive identity")
        with tarfile.open(archive, "r:gz") as bundle:
            for member in bundle:
                relative = Path(member.name)
                ex.require(
                    not relative.is_absolute() and ".." not in relative.parts, "Archive path"
                )
                path = runtime_dir / relative
                ex.require(
                    path.resolve().is_relative_to(runtime_dir.resolve()), "Archive link escape"
                )
                if member.isfile():
                    with bundle.extractfile(member) as content:
                        expected = hashlib.file_digest(content, "sha256").hexdigest()
                    ex.require(
                        ex.digest(path) == expected, f"Extracted runtime changed: {member.name}"
                    )
                    identities[member.name] = expected
                elif member.issym():
                    ex.require(
                        path.is_symlink() and os.readlink(path) == member.linkname, "Runtime link"
                    )
    return identities


def run(args, plan, seal):
    requests, items = verify_frozen(args.output, plan)
    ex.require(ex.read(args.output / "SOURCE.json") == seal, "Frozen source differs")
    out = args.output / "run"
    out.mkdir(exist_ok=False)
    ex.write_new(
        out / "STARTED.json",
        dict(
            pid=os.getpid(),
            source_commit=seal["source_commit"],
            utc=datetime.datetime.now(datetime.UTC).isoformat(),
            planned_requests=64,
            plan_sha256=ex.plan_hash(plan),
            retries=0,
        ),
    )
    server, outcomes, started = None, [], time.monotonic()
    result = dict(status="INCOMPLETE_NO_RETRY")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = f"http://127.0.0.1:{plan['port']}"
    try:
        ex.write_new(out / "ADMISSION.json", resources(plan, admission=True))
        with socket.socket() as sock:
            sock.bind((plan["host"], plan["port"]))  # Refuse an occupied local endpoint.
        identities = []
        for name, size, expected in plan["weights"]:
            path = args.weights / name
            measured = dict(name=name, bytes=path.stat().st_size, sha256=ex.digest(path))
            identities.append(measured)
            ex.require(
                measured["bytes"] == size and measured["sha256"] == expected, "Weight identity"
            )
        runtime = plan["runtime"]
        runtime_files = verify_runtime_files(args.runtime, runtime)
        command = server_command(args, plan)
        ex.write_new(
            out / "MODEL_IDENTITY.json",
            dict(
                shards=identities,
                runtime=runtime,
                server_sha256=ex.digest(command[0]),
                runtime_files=runtime_files,
            ),
        )
        env = dict(os.environ)
        env["LD_LIBRARY_PATH"] = str(args.runtime / "cudart-llama-b11756-bin-ubuntu-cuda-12.8-x64")
        with (out / "server.log").open("x") as log:
            server = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
            ex.write_new(out / "SERVER.json", dict(pid=server.pid, command=command))
            ready_limit = time.monotonic() + plan["startup_timeout_seconds"]
            while time.monotonic() < ready_limit:
                ex.require(server.poll() is None, "Teacher server exited during startup")
                try:
                    with opener.open(base + "/health", timeout=2) as response:
                        if response.status == 200:
                            break
                except (OSError, urllib.error.URLError):
                    time.sleep(1)
            else:
                raise TimeoutError("Teacher server startup deadline")
            with opener.open(base + "/props", timeout=10) as response:
                ex.write_new(out / "SERVER_PROPS.json", json.load(response))
            for i, (request, item) in enumerate(zip(requests, items, strict=True)):
                ex.require(time.monotonic() - started < plan["wall_seconds"], "Teacher wall bound")
                before = resources(plan, allowed_pids=(server.pid,))
                ex.write_new(
                    out / f"dispatch_{i:03d}.json",
                    dict(
                        index=i,
                        row_id=request["row_id"],
                        body_sha256=ex.plan_hash(request["body"]),
                        before=before,
                    ),
                )
                tick = time.monotonic()
                try:
                    req = urllib.request.Request(
                        base + "/v1/chat/completions",
                        data=ex.canonical(request["body"]).encode(),
                        headers={"Content-Type": "application/json"},
                    )
                    with opener.open(req, timeout=plan["request_timeout_seconds"]) as response:
                        raw = response.read()
                    with (out / f"response_{i:03d}.json").open("xb") as stream:
                        stream.write(raw)
                    outcome = classify(json.loads(raw), item)
                except Exception as exc:
                    outcome = dict(
                        status="TRANSPORT_OR_RESPONSE_ERROR",
                        error=f"{type(exc).__name__}: {exc}",
                        remote_execution="UNKNOWN",
                        training_approved=False,
                    )
                    outcome.update(index=i, elapsed_seconds=time.monotonic() - tick)
                    outcomes.append(outcome)
                    ex.write_new(out / f"outcome_{i:03d}.json", outcome)
                    raise
                outcome.update(index=i, elapsed_seconds=time.monotonic() - tick)
                outcomes.append(outcome)
                ex.write_new(out / f"outcome_{i:03d}.json", outcome)
                print(f"teacher {i + 1}/64 {outcome['status']}", flush=True)
            result["post_run_source_check"] = source.verify(ROOT, seal, ENTRY)
            result["status"] = "64_REQUEST_INSPECTION_COMPLETE_NOT_TRAINING_APPROVED"
    except BaseException as exc:
        result.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    finally:
        if server is not None and server.poll() is None:
            server.terminate()  # Only the child this runner owns.
            try:
                server.wait(timeout=20)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=20)
        result.update(summarize(outcomes), elapsed_seconds=time.monotonic() - started)
        result["files"] = ex.manifest(out)
        ex.write_new(out / "FINISHED.json", result)
    print(ex.canonical({k: v for k, v in result.items() if k != "files"}), flush=True)
    return int(result["attempted_requests"] != 64 or result["status"].startswith("INCOMPLETE"))


def verify(output, plan):
    requests, items = verify_frozen(output, plan)
    out, outcomes = output / "run", []
    terminal = ex.read(out / "FINISHED.json")
    actual = ex.manifest(out)
    actual.pop("FINISHED.json")
    ex.require(actual == terminal["files"], "Teacher outcome bytes changed")
    indices = sorted(int(p.stem.split("_")[1]) for p in out.glob("outcome_*.json"))
    ex.require(indices == list(range(len(indices))), "Noncontiguous outcomes")
    ex.require(len(indices) <= 64, "Extra outcomes")
    for i, (request, item) in enumerate(zip(requests, items, strict=True)):
        path = out / f"outcome_{i:03d}.json"
        if not path.exists():
            ex.require(not (out / f"dispatch_{i:03d}.json").exists(), "Dispatched outcome missing")
            continue
        observed = ex.read(path)
        receipt = ex.read(out / f"dispatch_{i:03d}.json")
        ex.require(observed["index"] == receipt["index"] == i, "Outcome index drift")
        ex.require(receipt["row_id"] == request["row_id"], "Outcome row drift")
        ex.require(receipt["body_sha256"] == ex.plan_hash(request["body"]), "Request body drift")
        if observed["status"] != "TRANSPORT_OR_RESPONSE_ERROR":
            expected = classify(ex.read(out / f"response_{i:03d}.json"), item)
            ex.require(
                expected
                == {k: v for k, v in observed.items() if k not in ("index", "elapsed_seconds")},
                "Outcome replay differs",
            )
        outcomes.append(observed)
    summary = summarize(outcomes)
    ex.require(all(terminal[k] == v for k, v in summary.items()), "Terminal denominator drift")
    if terminal["status"] == "64_REQUEST_INSPECTION_COMPLETE_NOT_TRAINING_APPROVED":
        ex.require(
            len(outcomes) == 64
            and not any(o["status"] == "TRANSPORT_OR_RESPONSE_ERROR" for o in outcomes),
            "Completion is not equivalent to valid diagnoses",
        )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "run", "verify"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seal", type=Path)
    parser.add_argument("--bank", type=Path)
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--runtime", type=Path)
    args = parser.parse_args()
    plan = ex.read(ROOT / PLAN)
    validate_plan(plan)
    if args.command == "verify":
        print(ex.canonical(verify(args.output, plan)))
        return 0
    ex.require(sys.flags.isolated and sys.pycache_prefix, "Use the sealed isolated launcher")
    seal = ex.read(args.seal)
    source.verify(ROOT, seal, ENTRY)
    if args.command == "freeze":
        freeze(args, plan, seal)
        return 0
    return run(args, plan, seal)


if __name__ == "__main__":
    raise SystemExit(main())
