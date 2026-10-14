#!/usr/bin/env python3
"""Offline replay of both tiny selection runtimes; no Torch or API imports."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import subprocess
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "v18_selection_receipt_contract", Path(__file__).with_name("qualify_v18_selection.py")
)
QUALIFICATION = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(QUALIFICATION)
ENTRY, PLAN, PASS = QUALIFICATION.ENTRY, QUALIFICATION.PLAN, QUALIFICATION.PASS
SCOPE = ("src", "scripts", "tests", "configs", "data/v10", "pyproject.toml")
CRITICAL = {
    ENTRY,
    PLAN,
    "scripts/run_source_sealed.py",
    "scripts/verify_v18_selection.py",
    *QUALIFICATION.CRITICAL_IMPORTS,
}
STARTED_KEYS = {"source_commit", "source_hashes", "plan", "source_check", "pid", "device", "python"}
FINISHED_KEYS = {
    "status",
    "device",
    "runtime",
    "offline_environment",
    "pytest_exit_code",
    "counts",
    "cases_by_file",
    "imported_project_sources",
    "peak_cuda_allocated_bytes",
    "elapsed_seconds",
    "files",
    *QUALIFICATION.CEILING,
}
RUNTIME_KEYS = {"torch", "transformers", "pytest", "cuda", "python", "platform"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate JSON field")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError(f"Nonfinite JSON constant: {value}")

    return json.loads(path.read_text(), object_pairs_hook=unique, parse_constant=nonfinite)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def same(left, right):
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(
        right, sort_keys=True, allow_nan=False
    )


def mapping(value, keys, message):
    require(type(value) is dict and set(value) == set(keys), message)


def text(value):
    return type(value) is str and bool(value) and all(ord(character) >= 32 for character in value)


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, stderr=subprocess.PIPE)


def source_path(repo, name):
    require(text(name), "Source path must be text")
    relative = PurePosixPath(name)
    require(
        not relative.is_absolute()
        and str(relative) == name
        and "\\" not in name
        and ".." not in relative.parts
        and ".git" not in relative.parts,
        "Noncanonical or escaping source path",
    )
    target = repo / name
    require(
        target.is_file()
        and target.resolve().is_relative_to(repo.resolve())
        and not any(part.is_symlink() for part in (target, *target.parents) if part != repo),
        "Source must be an owned regular nonsymlink file",
    )
    return target


def verify_sources(repo, seal):
    mapping(seal, {"source_commit", "source_hashes"}, "Source seal schema")
    commit, hashes = seal["source_commit"], seal["source_hashes"]
    require(type(commit) is str and re.fullmatch(r"[0-9a-f]{40}", commit), "Source commit")
    require(type(hashes) is dict and CRITICAL <= set(hashes), "Critical source seal missing")
    require(
        all(type(sha) is str and re.fullmatch(r"[0-9a-f]{64}", sha) for sha in hashes.values()),
        "Source hash schema",
    )
    require(
        Path(git(repo, "rev-parse", "--show-toplevel").decode().strip()).resolve()
        == repo.resolve(),
        "Expected exact repository root",
    )
    records = git(repo, "ls-tree", "-rz", "--full-tree", commit, "--", *SCOPE).split(b"\0")
    committed = {}
    for record in filter(None, records):
        metadata, raw_name = record.split(b"\t", 1)
        mode, kind, sha = metadata.decode().split()
        require(mode in ("100644", "100755") and kind == "blob", "Nonregular committed source")
        committed[raw_name.decode()] = sha
    require(set(committed) == set(hashes), "Seal does not cover the exact committed source scope")
    # Batched immutable blob reads are byte-equivalent to git show COMMIT:path,
    # avoiding one subprocess for every source file in the frozen tree.
    names = sorted(committed)
    response = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=repo,
        input="".join(committed[name] + "\n" for name in names).encode(),
        capture_output=True,
        check=True,
    ).stdout
    cursor = 0
    for name in names:
        end = response.index(b"\n", cursor)
        sha, kind, size = response[cursor:end].decode().split()
        require(sha == committed[name] and kind == "blob", "Committed blob identity mismatch")
        size = int(size)
        require(size >= 0, "Committed blob size")
        content = response[end + 1 : end + 1 + size]
        cursor = end + 1 + size
        require(response[cursor : cursor + 1] == b"\n", "Truncated committed blob")
        cursor += 1
        require(hashlib.sha256(content).hexdigest() == hashes[name], f"Commit hash differs: {name}")
        require(digest(source_path(repo, name)) == hashes[name], f"Current source differs: {name}")
    require(cursor == len(response), "Unexpected committed blob output")


def verify_device(directory, device, seal, plan):
    require(directory.is_dir() and not directory.is_symlink(), "Runtime receipt directory")
    expected_files = {"STARTED.json", "TESTS.xml", "FINISHED.json"}
    require({path.name for path in directory.iterdir()} == expected_files, "Runtime artifact set")
    require(
        all(path.is_file() and not path.is_symlink() for path in directory.iterdir()),
        "Runtime artifacts must be owned regular files",
    )
    started, finished = (read(directory / f"{name}.json") for name in ("STARTED", "FINISHED"))
    mapping(started, STARTED_KEYS, "Started schema")
    mapping(finished, FINISHED_KEYS, "Finished schema: incomplete/error runs cannot qualify")
    require(
        type(started["pid"]) is int and started["pid"] > 0 and text(started["python"]),
        "Started process/runtime identity",
    )
    require(
        all(same(started[key], value) for key, value in seal.items()), "Started source identity"
    )
    require(same(started["plan"], plan), "Started frozen plan changed")
    require(
        same(
            started["source_check"],
            {
                "schema": "pre-import-source-check-v1",
                "source_commit": seal["source_commit"],
                "entry": ENTRY,
                "source_files": len(seal["source_hashes"]),
                "untracked_check": "all",
                "isolated_python": True,
                "fresh_bytecode_cache": True,
            },
        ),
        "Pre-import proof mismatch",
    )
    require(started["device"] == finished["device"] == device, "Runtime device identity")
    expected_digests = {
        name: {"bytes": (directory / name).stat().st_size, "sha256": digest(directory / name)}
        for name in ("STARTED.json", "TESTS.xml")
    }
    require(same(finished["files"], expected_digests), "Terminal artifact digests mismatch")
    counts, by_file = QUALIFICATION.test_report(directory / "TESTS.xml", plan)
    expected_counts = {
        "tests": plan["expected_test_cases"],
        "failures": 0,
        "errors": 0,
        "skipped": 0,
    }
    require(same(counts, expected_counts), "JUnit counts not a complete pass")
    require(same(finished["counts"], counts), "Terminal counts mismatch")
    require(same(finished["cases_by_file"], by_file), "Terminal per-file counts mismatch")
    xml = ElementTree.parse(directory / "TESTS.xml").getroot()
    require(xml.tag == "testsuites" and len(xml) > 0, "JUnit root")
    require(all(suite.tag == "testsuite" for suite in xml), "JUnit suite schema")
    require(
        all(
            all(re.fullmatch(r"0|[1-9][0-9]*", suite.get(key, "")) for key in expected_counts)
            and all(child.tag == "testcase" for child in suite)
            for suite in xml
        ),
        "JUnit suite counters/children",
    )
    require(
        all(
            text(case.get("classname")) and text(case.get("name")) and not list(case)
            for case in xml.iter("testcase")
        ),
        "JUnit test identity or failure child",
    )
    require(
        finished["status"] == PASS
        and type(finished["pytest_exit_code"]) is int
        and finished["pytest_exit_code"] == 0,
        "Not a complete passed run",
    )
    for key, expected in QUALIFICATION.CEILING.items():
        require(
            type(finished[key]) is type(expected) and finished[key] == expected, "Claim ceiling"
        )
    require(same(finished["offline_environment"], plan["offline_environment"]), "Offline contract")
    runtime = finished["runtime"]
    mapping(runtime, RUNTIME_KEYS, "Runtime schema")
    require(all(text(value) for key, value in runtime.items() if key != "cuda"), "Runtime text")
    require(runtime["python"] == started["python"], "Python identity mismatch")
    require(runtime["cuda"] is None or text(runtime["cuda"]), "CUDA runtime field")
    peak = finished["peak_cuda_allocated_bytes"]
    if device == "cuda":
        require(text(runtime["cuda"]), "CUDA runtime missing")
        require(type(peak) is int and 0 < peak <= plan["gpu_memory_limit_gib"] * 2**30, "CUDA peak")
    else:
        require(peak is None, "CPU receipt has CUDA allocation")
    elapsed = finished["elapsed_seconds"]
    require(
        type(elapsed) in (int, float)
        and math.isfinite(elapsed)
        and 0 < elapsed <= plan["wall_limit_seconds"],
        "Wall budget exceeded",
    )
    imports = finished["imported_project_sources"]
    require(
        type(imports) is dict and all(text(key) and text(value) for key, value in imports.items()),
        "Import proof schema",
    )
    require(QUALIFICATION.CRITICAL_IMPORTS <= set(imports.values()), "Critical imports missing")
    require(set(imports.values()) <= set(seal["source_hashes"]), "Unsealed import")
    return {
        "status": PASS,
        "device": device,
        "counts": counts,
        "cases_by_file": by_file,
        "elapsed_seconds": elapsed,
        "peak_cuda_allocated_bytes": peak,
        "imported_source_count": len(set(imports.values())),
    }


def verify(bundle, repo=ROOT):
    """Both runtimes must qualify; missing/partial/error evidence is not a pass."""
    try:
        bundle, repo = Path(bundle), Path(repo)
        require(bundle.is_dir() and not bundle.is_symlink(), "Bundle directory")
        seal_path = bundle / "SOURCE_SEAL.json"
        require(seal_path.is_file() and not seal_path.is_symlink(), "Source seal regular file")
        seal = read(seal_path)
        verify_sources(repo, seal)
        plan = read(repo / PLAN)
        QUALIFICATION.validate_plan(plan)
        runs = {
            device: verify_device(bundle / device, device, seal, plan) for device in ("cpu", "cuda")
        }
        return {
            "schema": "v18-selection-offline-replay-v1",
            "status": PASS,
            "source_commit": seal["source_commit"],
            "source_files": len(seal["source_hashes"]),
            "committed_and_current_source": "MATCH",
            "runtimes": runs,
            **QUALIFICATION.CEILING,
        }
    except (
        OSError,
        KeyError,
        TypeError,
        IndexError,
        AttributeError,
        subprocess.CalledProcessError,
        ElementTree.ParseError,
    ) as error:
        raise ValueError(f"Invalid selection qualification evidence: {error}") from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.bundle)
    if args.output is not None:
        QUALIFICATION.write_new(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
