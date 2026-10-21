"""Replay the failed CPU collection and passing isolation audit; no model calls."""

import hashlib
import json
import subprocess
from pathlib import Path
from xml.etree import ElementTree

SOURCE = "106e12314d72a16a0515a5961989ed49a193a4f8"
ROOT = Path(__file__).resolve().parents[3]
BUNDLE = Path(__file__).resolve().parent / "furnace"


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify():
    seal = read(BUNDLE / "SOURCE_SEAL.json")
    assert seal["source_commit"] == SOURCE
    for name, expected in seal["source_hashes"].items():
        body = subprocess.check_output(["git", "show", f"{SOURCE}:{name}"], cwd=ROOT)
        assert hashlib.sha256(body).hexdigest() == expected, name
    folder = BUNDLE / "qualification/cpu"
    start, end = read(folder / "STARTED.json"), read(folder / "FINISHED.json")
    actual = {
        p.relative_to(folder).as_posix(): dict(bytes=p.stat().st_size, sha256=digest(p))
        for p in folder.rglob("*")
        if p.is_file() and p.name != "FINISHED.json"
    }
    assert actual == end["files"] and start["seal"] == seal
    assert end["status"] == "INCOMPLETE_NO_RETRY" and end["pytest_exit_code"] == 2
    counts = dict(tests=1, failures=0, errors=1, skipped=0)
    assert end["counts"] == counts and start["plan"]["qualification_cases"] == 244
    totals = dict.fromkeys(counts, 0)
    for suite in ElementTree.parse(folder / "TESTS.xml").getroot().iter("testsuite"):
        for key in totals:
            totals[key] += int(suite.attrib.get(key, 0))
    assert totals == counts
    audit = read(BUNDLE / "qualification/CPU_ISOLATION.json")
    assert audit["status"] == "CPU_GPU_ISOLATION_PASS"
    assert audit["pid"] == start["pid"] and audit["terminal_sha256"] == digest(
        folder / "FINISHED.json"
    )
    assert audit["final_visible_devices"] == 0 and audit["final_initialized"] is False
    assert audit["child_probe"]["visible_devices"] == 0
    assert audit["child_probe"]["initialized"] is False
    assert audit["child_probe"]["cuda_init_rejected"] == "RuntimeError"
    assert audit["samples"] and not audit["monitor_errors"]
    assert all(not sample["own_gpu_clients"] for sample in audit["samples"])
    for name in ("qualification/cuda", "raw", "checkpoints"):
        assert not (BUNDLE / name).exists(), name
    assert all(
        end[k] == 0
        for k in ("new_sequences", "native_weight_updates", "judge_calls", "weight_deletions")
    )
    return dict(
        status="CPU_COLLECTION_ERROR_NO_CUDA_OR_MODEL_DISPATCH",
        source=SOURCE,
        source_files=len(seal["source_hashes"]),
        test_counts=counts,
        planned_cpu_tests=244,
        isolation=audit["status"],
        isolation_samples=len(audit["samples"]),
        own_gpu_clients=[],
        cuda_qualification="NOT_DISPATCHED",
        pon="NOT_DISPATCHED",
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
    )


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
