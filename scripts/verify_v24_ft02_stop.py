#!/usr/bin/env python3
"""Offline replay of the audit-stopped FT02; never promotes CPU tests to admission."""

import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = (
    ROOT
    / "provenance/engineering/v24_recruitment_ft02_20261023/latent-v24-recruitment-ft02-20261023"
)
SOURCE = "d43382833f6dc85787720bda80aec511c66f58be"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(folder=BUNDLE):
    files = {
        p.relative_to(folder).as_posix(): dict(bytes=p.stat().st_size, sha256=sha(p))
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }
    require(not any(p.is_symlink() for p in folder.rglob("*")), "No artifact symlinks")
    require(
        set(files)
        == {
            "CHECKS_DISPATCH_SCRIPT.sh",
            "CHECKS_LAUNCH.log",
            "SOURCE_SEAL.json",
            "qualification/CPU_ISOLATION.json",
            "qualification/cpu/STARTED.json",
            "qualification/cpu/FINISHED.json",
            "qualification/cpu/TESTS.xml",
        },
        "CPU-only artifact set; no CUDA, 7B or whole-run terminal",
    )
    seal = json.loads((folder / "SOURCE_SEAL.json").read_text())
    require(seal["source_commit"] == SOURCE, "Original execution source")
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
        source = {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}
    require(
        {p: hashlib.sha256(b).hexdigest() for p, b in source.items()} == seal["source_hashes"],
        "Every source file matches frozen archive",
    )
    require(
        (folder / "CHECKS_DISPATCH_SCRIPT.sh").read_bytes()
        == (folder.parent / "launch_checks.sh").read_bytes(),
        "Published launcher bytes",
    )
    cpu = folder / "qualification/cpu"
    start, end = (
        json.loads((cpu / name).read_text()) for name in ("STARTED.json", "FINISHED.json")
    )
    require(
        start["seal"] == seal
        and start["device"] == "cpu"
        and start["plan"] == json.loads(source["configs/v24/RECRUITMENT_FT_01.json"]),
        "CPU source/plan/device identity",
    )
    require(
        end["files"]
        == {name: files[f"qualification/cpu/{name}"] for name in ("STARTED.json", "TESTS.xml")},
        "CPU terminal file set",
    )
    counts = dict(tests=570, failures=0, errors=0, skipped=0)
    xml = ElementTree.parse(cpu / "TESTS.xml")
    observed = {k: sum(int(s.get(k, 0)) for s in xml.iter("testsuite")) for k in counts}
    require(
        end["counts"] == observed == counts
        and end["pytest_exit_code"] == 0
        and end["status"] == "V24_ROUTE_FT_TINY_PASS_NOT_7B",
        "570 passing CPU tests only",
    )
    audit_path = folder / "qualification/CPU_ISOLATION.json"
    require(
        sha(audit_path) == "ead025364dde04d9b5ea6b8c876b318523c1f1eaeefa37341a05998bae09a127",
        "Unchanged historical failed audit",
    )
    audit = json.loads(audit_path.read_text())
    require(
        audit["status"] == "CPU_GPU_ISOLATION_FAILED"
        and audit["monitor_errors"] == ["ValueError"]
        and audit["terminal_sha256"] == sha(cpu / "FINISHED.json")
        and audit["pid"] == start["pid"]
        and len(audit["samples"]) == 134
        and all(s["gpu_clients"] == s["own_gpu_clients"] == [] for s in audit["samples"]),
        "Observed samples and failed monitor are separate facts",
    )
    return dict(
        status="VERIFIED_AUDIT_STOP_NOT_CUDA_OR_7B_ADMISSION",
        source_commit=SOURCE,
        source_files=len(source),
        files=files,
        cpu_tests=counts,
        observed_samples=134,
        observer_errors=["ValueError"],
        error_cause="UNKNOWN",
        cuda_tests="NOT_RUN",
        native_weight_updates=0,
        new_sequences=0,
        judge_calls=0,
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
    )


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
