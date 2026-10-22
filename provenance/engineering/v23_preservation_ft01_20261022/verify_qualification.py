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


def verify_public_teacher(root):
    """Verify published metadata; the private 2.286-GiB body is not local evidence."""
    folder = root / "raw/teacher"
    seal = read(root / "SOURCE_SEAL.json")
    start, end = read(folder / "STARTED.json"), read(folder / "FINISHED.json")
    assert start["seal"] == seal and end["status"] == "V23_PRESERVATION_TEACHER_COMPLETE"
    assert end["native_weight_updates"] == 0
    actual = manifest(folder)
    actual.pop("FINISHED.json")
    missing = "PRIVATE_TEACHER_TARGETS.safetensors"
    assert actual == {k: v for k, v in end["files"].items() if k != missing}
    receipt = read(folder / "TEACHER_TARGETS.json")
    assert end["files"][missing] == dict(bytes=receipt["bytes"], sha256=receipt["sha256"])
    assert receipt["source_commit"] == SOURCE
    assert (
        receipt["native_sha256"]
        == "9db998af86c8105f0a2d774c10f777e190f86e54473b6b756bb51b225064a189"
    )
    assert receipt["vocabulary"] == 32768 and receipt["target_dtype"] == "float32"
    assert receipt["temperature"] == 1 and len(receipt["rows"]) == 89
    assert sum(r["supervised_tokens"] for r in receipt["rows"]) == 18727
    assert receipt["tensor_bytes"] == 2454585344 and receipt["bytes"] == 2454592344
    assert [r["index"] for r in receipt["rows"]] == [str(i) for i in range(89)]
    assert all(r["shape"] == [r["supervised_tokens"], 32768] for r in receipt["rows"])
    sentinels = read(folder / "SAME_WEIGHT_SENTINELS.json")
    assert [r["key"] for r in sentinels] == [r["key"] for r in receipt["rows"]]
    assert all(
        r["bitwise_log_probabilities"]
        and r["mean_kl"] == 0
        and r["max_abs_log_probability_difference"] == 0
        for r in sentinels
    )
    return dict(
        status="PUBLIC_TEACHER_METADATA_PASS_PRIVATE_BODY_OMITTED",
        rows=89,
        positions=18727,
        bitwise_same_weight_rows=89,
        target_body_sha256=receipt["sha256"],
        private_body_verified_locally=False,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.root, args.repo)
    if (args.root / "raw/teacher").exists():
        result["teacher"] = verify_public_teacher(args.root)
    print(json.dumps(result, indent=2))
