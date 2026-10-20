"""Offline evidence rejection tests; no model/provider/GPU execution."""

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "verify_native_owner_qualification", ROOT / "scripts/verify_native_owner_qualification.py"
)
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


def write(path, value):
    path.write_text(json.dumps(value))


def reseal(folder):
    receipt = json.loads((folder / "FINISHED.json").read_text())
    receipt["files"] = {
        p.relative_to(folder).as_posix(): dict(bytes=p.stat().st_size, sha256=VERIFY.digest(p))
        for p in folder.rglob("*")
        if p.is_file() and p.name != "FINISHED.json"
    }
    write(folder / "FINISHED.json", receipt)


@pytest.fixture
def bundle(tmp_path):
    repo, bundle = tmp_path / "repo", tmp_path / "bundle"
    repo.mkdir()
    bundle.mkdir()
    plan = json.loads((ROOT / VERIFY.PLAN).read_text())
    plan["qualification_cases"] = 1
    for name, data in {
        VERIFY.ENTRY: b"# synthetic source\n",
        VERIFY.PLAN: json.dumps(plan).encode(),
        "src/extra.py": b"# proves omissions are detected\n",
    }.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    for command in (
        ["init", "-q"],
        ["add", "."],
        [
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
    ):
        subprocess.run(["git", *command], cwd=repo, check=True, capture_output=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    seal = dict(
        source_commit=sha,
        source_hashes={
            name: VERIFY.digest(repo / name) for name in (VERIFY.ENTRY, VERIFY.PLAN, "src/extra.py")
        },
    )
    write(bundle / "SOURCE_SEAL.json", seal)
    for device in ("cpu", "cuda"):
        folder = bundle / device
        folder.mkdir()
        write(folder / "STARTED.json", dict(device=device, seal=seal, plan=plan))
        (folder / "TESTS.xml").write_text(
            '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0"/></testsuites>'
        )
        write(
            folder / "FINISHED.json",
            dict(
                status=VERIFY.PASS,
                pytest_exit_code=0,
                counts=dict(tests=1, failures=0, errors=0, skipped=0),
                device=device,
                elapsed_seconds=0.5,
                imports={"entry": VERIFY.ENTRY},
                peak_cuda_allocated_bytes=1024 if device == "cuda" else None,
                **VERIFY.CEILING,
            ),
        )
        reseal(folder)
    return bundle, repo


def test_valid_offline_qualification(bundle):
    result = VERIFY.verify(*bundle)
    assert result["source_files"] == 3
    assert result["devices"]["cuda"]["counts"]["tests"] == 1
    assert result["non_regression"] == "NOT_ESTABLISHED"


@pytest.mark.parametrize(
    "change",
    [
        "source_omission",
        "source_hash",
        "counts",
        "skip",
        "device",
        "wall",
        "gate",
        "update",
        "import",
        "peak",
        "bytes",
        "xml",
        "symlink",
    ],
)
def test_modified_qualification_is_rejected(bundle, change):
    path, repo = bundle
    folder = path / "cuda"
    end = json.loads((folder / "FINISHED.json").read_text())
    if change.startswith("source_"):
        seal = json.loads((path / "SOURCE_SEAL.json").read_text())
        if change == "source_omission":
            del seal["source_hashes"]["src/extra.py"]
        else:
            seal["source_hashes"]["src/extra.py"] = "0" * 64
        write(path / "SOURCE_SEAL.json", seal)
    elif change in ("xml", "bytes", "symlink"):
        if change == "symlink":
            (folder / "link").symlink_to(folder / "TESTS.xml")
        else:
            (folder / "TESTS.xml").write_text('<testsuite tests="0"/>')
        if change != "bytes":
            reseal(folder)
    else:
        if change == "counts":
            end["counts"]["tests"] = 0
        elif change == "skip":
            end["counts"]["skipped"] = 1
        elif change == "device":
            end["device"] = "cpu"
        elif change == "wall":
            end["elapsed_seconds"] = 901
        elif change == "gate":
            end["old_expression_gate"] = "PASS"
        elif change == "update":
            end["real_model_updates"] = 1
        elif change == "import":
            end["imports"]["extra"] = "unsealed.py"
        elif change == "peak":
            end["peak_cuda_allocated_bytes"] = 4 * 2**30 + 1
        write(folder / "FINISHED.json", end)
    with pytest.raises(ValueError):
        VERIFY.verify(path, repo)


def test_plan_hash_matches_sealed_entry():
    plan = json.loads((ROOT / VERIFY.PLAN).read_text())
    encoded = json.dumps(plan, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    assert f'PLAN_SHA256 = "{digest}"' in (ROOT / VERIFY.ENTRY).read_text()
    assert plan["qualification_cases"] == 199
    assert plan["scratch_cpu_sdpa_backend"] == "math"
    assert plan["full_7b_dispatch"] is False and plan["retry"] is False
