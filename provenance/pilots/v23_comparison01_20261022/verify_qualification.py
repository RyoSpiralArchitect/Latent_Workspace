"""Read-only exact-source and full CPU/CUDA qualification replay. No models."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from xml.etree import ElementTree

SOURCE = "84073310cd7b2c56b5e3de046fb3bdc99e461bfb"


def read(path):
    return json.loads(path.read_text())


def manifest(folder):
    result = {}
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            with path.open("rb") as stream:
                result[path.relative_to(folder).as_posix()] = dict(
                    bytes=path.stat().st_size,
                    sha256=hashlib.file_digest(stream, "sha256").hexdigest(),
                )
    return result


def verify(root, repo):
    seal = read(root / "SOURCE_SEAL.json")
    assert seal["source_commit"] == SOURCE and len(seal["source_hashes"]) == 774
    for name, expected in seal["source_hashes"].items():
        body = subprocess.check_output(["git", "show", f"{SOURCE}:{name}"], cwd=repo)
        assert hashlib.sha256(body).hexdigest() == expected, name
    plan = json.loads(
        subprocess.check_output(
            ["git", "show", f"{SOURCE}:configs/v23/COMPARISON_01.json"], cwd=repo
        )
    )
    devices = {}
    for device in ("cpu", "cuda"):
        folder = root / "qualification" / device
        start, end = read(folder / "STARTED.json"), read(folder / "FINISHED.json")
        actual = manifest(folder)
        actual.pop("FINISHED.json")
        assert actual == end["files"]
        assert start["seal"] == seal and start["plan"] == plan and start["device"] == device
        assert end["status"] == "TINY_V23_EVALUATION_PASS_NOT_7B" and end["pytest_exit_code"] == 0
        expected = dict(tests=223, failures=0, errors=0, skipped=0)
        assert end["counts"] == expected
        totals = dict.fromkeys(expected, 0)
        for suite in ElementTree.parse(folder / "TESTS.xml").getroot().iter("testsuite"):
            for key in totals:
                totals[key] += int(suite.attrib.get(key, 0))
        assert totals == expected and 0 < end["elapsed_seconds"] < 900
        assert all(
            end[k] == 0
            for k in (
                "real_model_updates",
                "native_weight_updates",
                "new_sequences",
                "judge_calls",
                "weight_deletions",
            )
        )
        assert end["old_expression_gate"] == "FAIL" and end["winner"] == "none"
        assert end["non_regression"] == "NOT_ESTABLISHED"
        if device == "cuda":
            assert 0 < end["peak_cuda_allocated_bytes"] <= 4 * 2**30
        devices[device] = {k: end[k] for k in ("status", "counts", "elapsed_seconds")}
    return dict(
        status="OFFLINE_QUALIFICATION_REPLAY_PASS_NOT_7B",
        source=SOURCE,
        source_files=774,
        devices=devices,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.root, args.repo), indent=2))
