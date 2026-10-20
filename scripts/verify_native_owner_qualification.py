#!/usr/bin/env python3
"""Offline verification: Git blobs, both device manifests and exact test counts.

Standard library only. This checks retained evidence; it never runs model code.
Use the repository whose object database contains the sealed execution commit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

PASS = "TINY_NATIVE_OWNER_AND_REPLAY_PASS_NOT_7B"
ENTRY = "scripts/qualify_native_owner.py"
PLAN = "configs/v1_0/NATIVE_OWNER_QUALIFICATION.json"
SCOPES = ("src", "scripts", "tests", "configs", "data/v10", "pyproject.toml")
CEILING = dict(
    new_sequences=0,
    judge_calls=0,
    weight_deletions=0,
    native_weight_updates=0,
    real_model_updates=0,
    old_expression_gate="FAIL",
    winner="none",
    non_regression="NOT_ESTABLISHED",
)


def read(path):
    return json.loads(path.read_text())


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def verify(bundle, repo):
    seal = read(bundle / "SOURCE_SEAL.json")
    require(set(seal) == {"source_commit", "source_hashes"}, "Seal schema")
    sha = seal["source_commit"]
    require(len(sha) == 40 and all(c in "0123456789abcdef" for c in sha), "Commit")
    tracked = (
        subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", "-z", sha, "--", *SCOPES], cwd=repo
        )
        .decode()
        .split("\0")
    )
    require(set(filter(None, tracked)) == set(seal["source_hashes"]), "Complete source seal")
    source = {}
    for name, expected in seal["source_hashes"].items():
        path = PurePosixPath(name)
        require(not path.is_absolute() and ".." not in path.parts, "Source path")
        data = subprocess.check_output(["git", "show", f"{sha}:{name}"], cwd=repo)
        require(hashlib.sha256(data).hexdigest() == expected, f"Source: {name}")
        if name == PLAN:
            source[name] = data
    require(ENTRY in seal["source_hashes"] and PLAN in source, "Qualification source")
    plan = json.loads(source[PLAN])
    require(
        plan["qualification_devices"] == ["cpu", "cuda"]
        and plan["full_7b_dispatch"] is False
        and plan["retry"] is False
        and plan["pass_status"] == PASS,
        "Tiny qualification scope",
    )
    expected_counts = dict(tests=plan["qualification_cases"], failures=0, errors=0, skipped=0)
    devices = {}
    for device in ("cpu", "cuda"):
        folder = bundle / device
        start, end = read(folder / "STARTED.json"), read(folder / "FINISHED.json")
        require(
            start["device"] == device and start["seal"] == seal and start["plan"] == plan,
            "Start/source/plan/device mismatch",
        )
        require(
            end["status"] == PASS
            and end["pytest_exit_code"] == 0
            and end["counts"] == expected_counts,
            "Qualification outcome",
        )
        require(
            all(end[key] == expected for key, expected in CEILING.items()),
            "Scope ceiling",
        )
        require(end["device"] == device, "Terminal device")
        require(
            0 < end["elapsed_seconds"] <= plan["qualification_wall_seconds"],
            "Wall envelope",
        )
        require(
            all(name in seal["source_hashes"] for name in end["imports"].values()),
            "Unsealed imported module",
        )
        require(not any(p.is_symlink() for p in folder.rglob("*")), "Artifact symlink")
        actual = {
            p.relative_to(folder).as_posix(): dict(bytes=p.stat().st_size, sha256=digest(p))
            for p in folder.rglob("*")
            if p.is_file() and p.name != "FINISHED.json"
        }
        require(actual == end["files"], "Artifact manifest mismatch")
        totals = {k: 0 for k in expected_counts}
        for suite in ElementTree.parse(folder / "TESTS.xml").getroot().iter("testsuite"):
            for key in totals:
                totals[key] += int(suite.attrib.get(key, 0))
        require(totals == expected_counts, "Literal XML counts")
        if device == "cuda":
            require(
                0 < end["peak_cuda_allocated_bytes"] <= plan["qualification_gpu_limit_gib"] * 2**30,
                "CUDA peak",
            )
        devices[device] = dict(
            counts=totals,
            elapsed_seconds=end["elapsed_seconds"],
            peak_cuda_allocated_bytes=end.get("peak_cuda_allocated_bytes"),
        )
    return dict(
        status="OFFLINE_NATIVE_OWNER_QUALIFICATION_VERIFIED_NOT_7B",
        source_commit=sha,
        source_files=len(seal["source_hashes"]),
        devices=devices,
        forwards=0,
        old_expression_gate="FAIL",
        non_regression="NOT_ESTABLISHED",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(verify(args.bundle, args.repo), indent=2))
