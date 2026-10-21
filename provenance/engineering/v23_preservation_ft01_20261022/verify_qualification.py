"""Offline publication check only. No model imports, jobs, writes or network."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from xml.etree import ElementTree

SOURCE = "b46f04caefcfd596ccde3b0af8fd886d859f11b7"
STATUS = "TINY_V23_PRESERVATION_OWNER_PASS_NOT_7B"


def read(path):
    return json.loads(path.read_text())


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def manifest(path):
    return {
        p.relative_to(path).as_posix(): dict(bytes=p.stat().st_size, sha256=digest(p))
        for p in sorted(path.rglob("*"))
        if p.is_file()
    }


def verify(root, repo):
    seal = read(root / "SOURCE_SEAL.json")
    assert seal["source_commit"] == SOURCE and len(seal["source_hashes"]) == 769
    for name, expected in seal["source_hashes"].items():
        body = subprocess.check_output(["git", "show", f"{SOURCE}:{name}"], cwd=repo)
        assert hashlib.sha256(body).hexdigest() == expected, name
    expected_plan = json.loads(
        subprocess.check_output(
            ["git", "show", f"{SOURCE}:configs/v23/PRESERVATION_FT_01.json"], cwd=repo
        )
    )
    outcomes = {}
    for device in ("cpu", "cuda"):
        folder = root / "qualification" / device
        start, end = read(folder / "STARTED.json"), read(folder / "FINISHED.json")
        files = manifest(folder)
        files.pop("FINISHED.json")
        assert files == end["files"]
        assert start["seal"] == seal and start["plan"] == expected_plan
        assert start["device"] == device and end["status"] == STATUS
        assert end["pytest_exit_code"] == 0
        counts = dict(tests=472, failures=0, errors=0, skipped=0)
        assert end["counts"] == counts
        suites = ElementTree.parse(folder / "TESTS.xml").getroot().iter("testsuite")
        totals = {key: 0 for key in counts}
        for suite in suites:
            for key in totals:
                totals[key] += int(suite.attrib.get(key, 0))
        assert totals == counts
        assert 0 < end["elapsed_seconds"] < 900
        if device == "cuda":
            assert 0 < end["peak_cuda_allocated_bytes"] <= 4 * 2**30
        for key in (
            "real_model_updates",
            "native_weight_updates",
            "new_sequences",
            "judge_calls",
            "weight_deletions",
        ):
            assert end[key] == 0
        assert end["old_expression_gate"] == "FAIL" and end["winner"] == "none"
        assert end["non_regression"] == "NOT_ESTABLISHED"
        outcomes[device] = {k: end[k] for k in ("status", "counts", "elapsed_seconds")}
    return dict(
        status="OFFLINE_QUALIFICATION_REPLAY_PASS_NOT_7B",
        source=SOURCE,
        source_files=769,
        qualifications=outcomes,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.root, args.repo), indent=2))
