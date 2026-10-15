#!/usr/bin/env python3
"""Offline tiny window/reference receipt replay; no Torch, checkpoint or API load."""

import argparse
import hashlib
import importlib.util
import json
import math
import re
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "scripts/qualify_v18_window_reference.py"
PLAN = "configs/v18/WINDOW_REFERENCE_QUALIFICATION_PLAN.json"
TESTS = (
    "tests/test_v18_reference_bank.py",
    "tests/test_v18_window_objective.py",
    "tests/test_v18_window_learner.py",
)
MODULES = (
    "src/latent_workspace_ft_v10/v18_reference_bank.py",
    "src/latent_workspace_ft_v10/v18_window_objective.py",
    "src/latent_workspace_ft_v10/v18_window_learner.py",
)
CRITICAL = {
    ENTRY,
    PLAN,
    *TESTS,
    *MODULES,
    "scripts/run_source_sealed.py",
    "scripts/verify_v18_window_reference.py",
    "src/latent_workspace_ft_v10/v16_slot_contrast.py",
    "src/latent_workspace_ft_v10/native_training_preparation.py",
}
PASS = "TINY_WINDOW_REFERENCE_PASS_NOT_7B_OR_SEMANTIC"

# The runner module is standard-library-only until execute() is called. Load
# its actual sibling source, not an arbitrary same-named module from sys.path.
_spec = importlib.util.spec_from_file_location(
    "v18_qualification_receipt_contract",
    Path(__file__).with_name("qualify_v18_window_reference.py"),
)
QUALIFICATION = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(QUALIFICATION)
STARTED_KEYS = {
    "source_commit",
    "source_hashes",
    "plan",
    "source_check",
    "pid",
    "device",
    "python",
}
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


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate JSON object field")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError(f"Nonfinite JSON constant: {value}")

    return json.loads(path.read_text(), object_pairs_hook=unique, parse_constant=reject_constant)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mapping(value, keys, message):
    require(type(value) is dict and set(value) == set(keys), message)


def _text(value):
    return type(value) is str and bool(value) and not any(ord(char) < 32 for char in value)


def _same(left, right):
    """Canonical JSON equality distinguishes integer values from booleans."""
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(
        right,
        sort_keys=True,
        allow_nan=False,
    )


def _verify(bundle, repo):
    started, finished = (read(bundle / f"{name}.json") for name in ("STARTED", "FINISHED"))
    _mapping(started, STARTED_KEYS, "Started receipt schema")
    _mapping(finished, FINISHED_KEYS, "Finished receipt schema")
    require(type(started["pid"]) is int and started["pid"] > 0, "Started process identity")
    require(_text(started["python"]), "Started Python runtime")
    require(
        {p.name for p in bundle.iterdir()} == {"STARTED.json", "TESTS.xml", "FINISHED.json"},
        "Unexpected qualification artifact",
    )
    require(
        all(path.is_file() and not path.is_symlink() for path in bundle.iterdir()),
        "Qualification artifacts must be owned regular files",
    )
    actual = {
        name: {"bytes": (bundle / name).stat().st_size, "sha256": digest(bundle / name)}
        for name in ("STARTED.json", "TESTS.xml")
    }
    require(_same(actual, finished["files"]), "Terminal artifact bytes mismatch")
    seal = read(bundle.parent / "SOURCE_SEAL.json")
    require(
        type(seal) is dict
        and set(seal) == {"source_commit", "source_hashes"}
        and type(seal["source_commit"]) is str
        and re.fullmatch(r"[0-9a-f]{40}", seal["source_commit"]),
        "Source seal schema",
    )
    require(
        type(seal["source_hashes"]) is dict
        and all(
            type(name) is str and type(sha) is str and re.fullmatch(r"[0-9a-f]{64}", sha)
            for name, sha in seal["source_hashes"].items()
        ),
        "Source hash schema",
    )
    require(CRITICAL <= set(seal["source_hashes"]), "Missing critical sealed source")
    require(all(started[key] == value for key, value in seal.items()), "Source identity mismatch")
    for name, sha in seal["source_hashes"].items():
        path = PurePosixPath(name)
        require(
            not path.is_absolute()
            and ".." not in path.parts
            and str(path) == name
            and "\\" not in name,
            "Source path escape or noncanonical source name",
        )
        target = repo / name
        require(target.resolve().is_relative_to(repo.resolve()), "Source symlink escape")
        require(digest(target) == sha, f"Source changed: {name}")
    require(
        _same(
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
        "Pre-import source receipt mismatch",
    )
    plan = read(repo / PLAN)
    QUALIFICATION.validate_plan(plan)
    require(_same(started["plan"], plan), "Qualification plan mismatch")
    require(plan["test_files"] == list(TESTS), "Test selection")
    per_file = plan["expected_cases_by_file"]
    require(
        set(per_file) == set(TESTS)
        and all(type(n) is int and n > 0 for n in per_file.values())
        and type(plan["expected_test_cases"]) is int
        and sum(per_file.values()) == plan["expected_test_cases"],
        "Complete planned test denominators",
    )
    require(
        plan["wall_limit_seconds"] == 900 and plan["gpu_memory_limit_gib"] == 4,
        "Resource ceilings changed",
    )
    counts = {"tests": plan["expected_test_cases"], "failures": 0, "errors": 0, "skipped": 0}
    require(_same(finished["counts"], counts), "Terminal test denominators mismatch")
    require(_same(finished["cases_by_file"], per_file), "Terminal per-file denominators mismatch")
    root = ElementTree.parse(bundle / "TESTS.xml").getroot()
    require(root.tag == "testsuites", "JUnit report root")
    suites = list(root)
    require(bool(suites) and all(s.tag == "testsuite" for s in suites), "JUnit suite schema")
    require(
        all(all(child.tag == "testcase" for child in suite) for suite in suites),
        "Unexpected JUnit suite child",
    )
    require(
        all(
            re.fullmatch(r"0|[1-9][0-9]*", suite.get(key, "")) for suite in suites for key in counts
        ),
        "JUnit denominator schema",
    )
    require(
        {key: sum(int(s.attrib[key]) for s in suites) for key in counts}
        == finished["counts"]
        == counts,
        "Test denominators mismatch",
    )
    cases = list(root.iter("testcase"))
    require(
        len(cases)
        == len({(case.get("classname"), case.get("name")) for case in cases})
        == counts["tests"]
        and all(_text(case.get("classname")) and _text(case.get("name")) for case in cases)
        and all(case.get("file") in TESTS for case in cases)
        and {name: sum(case.get("file") == name for case in cases) for name in TESTS} == per_file
        and all(not list(case) for case in cases),
        "Test identity mismatch",
    )
    require(
        finished["status"] == PASS
        and type(finished["pytest_exit_code"]) is int
        and finished["pytest_exit_code"] == 0,
        "Not a passed run",
    )
    require(finished["device"] == started["device"] in ("cpu", "cuda"), "Device mismatch")
    for key, expected in QUALIFICATION.CEILING.items():
        require(
            type(finished[key]) is type(expected) and finished[key] == expected,
            f"Claim ceiling changed: {key}",
        )
    _mapping(finished["runtime"], RUNTIME_KEYS, "Runtime schema")
    require(
        all(_text(value) for key, value in finished["runtime"].items() if key != "cuda")
        and (finished["runtime"]["cuda"] is None or _text(finished["runtime"]["cuda"]))
        and finished["runtime"]["python"] == started["python"],
        "Runtime identity mismatch",
    )
    require(
        finished["device"] != "cuda" or finished["runtime"]["cuda"] is not None,
        "CUDA runtime missing",
    )
    require(
        _same(finished["offline_environment"], plan["offline_environment"]),
        "Offline environment mismatch",
    )
    peak = finished["peak_cuda_allocated_bytes"]
    if finished["device"] == "cuda":
        require(type(peak) is int and 0 < peak <= plan["gpu_memory_limit_gib"] * 2**30, "CUDA peak")
    else:
        require(peak is None, "CPU run has CUDA peak")
    elapsed = finished["elapsed_seconds"]
    require(
        type(elapsed) in (int, float)
        and math.isfinite(elapsed)
        and 0 < elapsed <= plan["wall_limit_seconds"] + 60,
        "Wall limit",
    )
    imports = finished["imported_project_sources"]
    require(
        type(imports) is dict
        and all(_text(key) and _text(value) for key, value in imports.items()),
        "Import proof schema",
    )
    require(
        set(MODULES + TESTS) <= set(imports.values()), "Missing window/bank/owner/test import proof"
    )
    require(set(imports.values()) <= set(seal["source_hashes"]), "Unsealed imported module")
    return {
        "status": PASS,
        "device": finished["device"],
        "counts": counts,
        "cases_by_file": per_file,
        "source_commit": seal["source_commit"],
        "source_files": len(seal["source_hashes"]),
        "elapsed_seconds": elapsed,
        "peak_cuda_allocated_bytes": peak,
        "old_expression_gate": "FAIL",
        "winner": "none",
        "non_regression": "NOT_ESTABLISHED",
    }


def verify(bundle, repo=ROOT):
    """Invalid or incomplete artifacts fail closed with one public exception type."""
    try:
        return _verify(Path(bundle), Path(repo))
    except (
        OSError,
        KeyError,
        TypeError,
        IndexError,
        AttributeError,
        ElementTree.ParseError,
    ) as error:
        raise ValueError(f"Invalid qualification receipt: {error}") from error


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    print(json.dumps(verify(parser.parse_args().bundle), indent=2, sort_keys=True))
