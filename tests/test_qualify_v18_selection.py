"""Cheap synthetic guard/replay checks; no model import or qualification run."""

import copy
import hashlib
import json
import subprocess
from pathlib import Path
from types import ModuleType, SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from scripts import qualify_v18_selection as run
from scripts import verify_v18_selection as replay


def plan():
    return json.loads((run.ROOT / run.PLAN).read_text())


@pytest.mark.parametrize(
    "key,value",
    [
        ("schema", "other"),
        ("test_files", []),
        ("expected_cases_by_file", {}),
        ("expected_test_cases", 199),
        ("max_threads", True),
        ("gpu_memory_limit_gib", 5),
        ("wall_limit_seconds", 901),
        ("arms", ["final"]),
        ("fresh_process_per_device", 1),
        ("offline_environment", {}),
        ("old_expression_gate", "PASS"),
        ("extra", "unknown"),
    ],
)
def test_plan_changes_fail_closed(key, value):
    frozen = plan()
    run.validate_plan(frozen)
    frozen[key] = value
    with pytest.raises(ValueError, match="plan changed"):
        run.validate_plan(frozen)


def import_fixture(tmp_path, monkeypatch):
    repo = tmp_path / "source"
    repo.mkdir()
    monkeypatch.setattr(run, "ROOT", repo)
    hashes, modules = {}, {}
    for name in sorted(run.CRITICAL_IMPORTS):
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# synthetic source only\n")
        hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
        module = (
            "latent_workspace_ft_v10." + target.stem if name.startswith("src/") else target.stem
        )
        modules[module] = SimpleNamespace(__file__=str(target))
    return {"source_hashes": hashes}, modules


def test_virtual_module_metadata_never_runs_dynamic_or_inherited_lookup(tmp_path, monkeypatch):
    seal, modules = import_fixture(tmp_path, monkeypatch)

    class Virtual(ModuleType):
        __file__ = "_ops.py"

    class Dynamic(ModuleType):
        def __getattr__(self, name):
            raise AssertionError(f"Dynamic metadata lookup: {name}")

    modules["torch.ops"] = Virtual("torch.ops")
    modules["torch.classes"] = Dynamic("torch.classes")
    (run.ROOT / "_ops.py").write_text("# not an imported module\n")
    assert set(run.imported_sources(seal, modules).values()) == run.CRITICAL_IMPORTS


@pytest.mark.parametrize(
    "kind", ["missing", "escaped", "changed", "unsealed", "relative", "virtual"]
)
def test_import_closure_rejects_missing_or_unowned_source(tmp_path, monkeypatch, kind):
    seal, modules = import_fixture(tmp_path, monkeypatch)
    name = next(iter(modules))
    if kind == "missing":
        del modules[name]
    elif kind == "escaped":
        modules[name].__file__ = str(tmp_path / "outside.py")
    elif kind == "changed":
        Path(modules[name].__file__).write_text("# changed\n")
    elif kind == "unsealed":
        target = run.ROOT / "extra.py"
        target.write_text("# unsealed\n")
        modules["extra_alias"] = SimpleNamespace(__file__=str(target))
    elif kind == "relative":
        modules[name].__file__ = "_ops.py"
    else:

        class VirtualProject(ModuleType):
            __file__ = "_ops.py"

        modules[name] = VirtualProject(name)
    with pytest.raises(ValueError):
        run.imported_sources(seal, modules)


def xml_report(path, frozen):
    root = ET.Element("testsuites")
    for source, count in frozen["expected_cases_by_file"].items():
        suite = ET.SubElement(
            root, "testsuite", tests=str(count), failures="0", errors="0", skipped="0"
        )
        for index in range(count):
            ET.SubElement(
                suite, "testcase", file=source, classname=Path(source).stem, name=f"case{index}"
            )
    ET.ElementTree(root).write(path)


@pytest.mark.parametrize("kind", ["valid", "duplicate", "count", "unselected", "per_file"])
def test_junit_population_and_unique_cases(tmp_path, kind):
    frozen = plan()
    path = tmp_path / "TESTS.xml"
    xml_report(path, frozen)
    tree = ET.parse(path)
    cases = list(tree.getroot().iter("testcase"))
    if kind == "duplicate":
        cases[1].set("name", cases[0].get("name"))
    elif kind == "count":
        next(tree.getroot().iter("testsuite")).set("tests", "1")
    elif kind == "unselected":
        cases[0].set("file", "tests/unselected.py")
    elif kind == "per_file":
        cases[0].set("file", frozen["test_files"][1])
    tree.write(path)
    if kind == "valid":
        counts, by_file = run.test_report(path, frozen)
        assert counts == {"tests": 200, "failures": 0, "errors": 0, "skipped": 0}
        assert by_file == frozen["expected_cases_by_file"]
    else:
        with pytest.raises(ValueError):
            run.test_report(path, frozen)


def test_exclusive_write_and_preimport_isolation(tmp_path, monkeypatch):
    output = tmp_path / "receipt.json"
    run.write_new(output, {"first": 1})
    with pytest.raises(FileExistsError):
        run.write_new(output, {"overwrite": 2})
    assert json.loads(output.read_text()) == {"first": 1}
    monkeypatch.setattr(run.sys, "flags", SimpleNamespace(isolated=0))
    with pytest.raises(ValueError, match="isolated pre-import"):
        run.execute(SimpleNamespace())


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True))


def reseal(directory, finished):
    finished["files"] = {
        name: {
            "bytes": (directory / name).stat().st_size,
            "sha256": replay.digest(directory / name),
        }
        for name in ("STARTED.json", "TESTS.xml")
    }
    write(directory / "FINISHED.json", finished)


def receipt_fixture(tmp_path):
    """A real temporary Git tree of clearly synthetic, nonexecutable source."""
    repo, bundle = tmp_path / "repo", tmp_path / "bundle"
    repo.mkdir()
    bundle.mkdir()
    frozen = plan()
    for name in replay.CRITICAL:
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("Synthetic guard fixture only; not execution evidence.\n")
    write(repo / replay.PLAN, frozen)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "user.name=Synthetic fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "Synthetic receipt fixture",
        ],
        cwd=repo,
        check=True,
    )
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    seal = {
        "source_commit": commit,
        "source_hashes": {name: replay.digest(repo / name) for name in replay.CRITICAL},
    }
    write(bundle / "SOURCE_SEAL.json", seal)
    for index, device in enumerate(("cpu", "cuda")):
        directory = bundle / device
        directory.mkdir()
        started = {
            **seal,
            "plan": frozen,
            "device": device,
            "pid": 1234 + index,
            "python": "3.12.14",
            "source_check": {
                "schema": "pre-import-source-check-v1",
                "source_commit": commit,
                "entry": replay.ENTRY,
                "source_files": len(seal["source_hashes"]),
                "untracked_check": "all",
                "isolated_python": True,
                "fresh_bytecode_cache": True,
            },
        }
        write(directory / "STARTED.json", started)
        xml_report(directory / "TESTS.xml", frozen)
        finished = {
            "status": replay.PASS,
            "device": device,
            "pytest_exit_code": 0,
            "counts": {"tests": 200, "failures": 0, "errors": 0, "skipped": 0},
            "cases_by_file": frozen["expected_cases_by_file"],
            "peak_cuda_allocated_bytes": 1024 if device == "cuda" else None,
            "elapsed_seconds": 2.0,
            "runtime": {
                "python": "3.12.14",
                "torch": "synthetic",
                "transformers": "synthetic",
                "pytest": "synthetic",
                "platform": "synthetic",
                "cuda": "synthetic" if device == "cuda" else None,
            },
            "offline_environment": copy.deepcopy(run.OFFLINE_ENV),
            "imported_project_sources": {
                f"synthetic{i}": name for i, name in enumerate(sorted(run.CRITICAL_IMPORTS))
            },
            **run.CEILING,
        }
        reseal(directory, finished)
    return repo, bundle


def test_complete_synthetic_cpu_cuda_receipts_replay_committed_and_current_source(tmp_path):
    repo, bundle = receipt_fixture(tmp_path)
    result = replay.verify(bundle, repo)
    assert result["status"] == run.PASS
    assert result["committed_and_current_source"] == "MATCH"
    assert set(result["runtimes"]) == {"cpu", "cuda"}
    assert result["old_expression_gate"] == "FAIL"
    assert result["non_regression"] == "NOT_ESTABLISHED"


@pytest.mark.parametrize(
    "kind",
    [
        "current_source",
        "rewritten_source_seal",
        "source_missing",
        "source_escape",
        "source_symlink",
        "wrong_commit",
        "missing_finish",
        "missing_runtime",
        "receipt_extra",
        "status",
        "error_field",
        "exit_bool",
        "count_bool",
        "count_drift",
        "file_count_drift",
        "offline",
        "cuda_peak",
        "cuda_peak_bool",
        "elapsed",
        "import_missing",
        "import_unsealed",
        "started_identity",
        "started_plan",
        "source_check",
        "artifact_digest",
        "junit_failure",
        "junit_duplicate",
        "duplicate_json",
    ],
)
def test_partial_corrupt_or_reissued_receipts_never_become_pass(tmp_path, kind):
    repo, bundle = receipt_fixture(tmp_path)
    directory = bundle / "cuda"
    finished = replay.read(directory / "FINISHED.json")
    if kind == "current_source":
        (repo / run.ENTRY).write_text("changed\n")
    elif kind == "rewritten_source_seal":
        (repo / run.ENTRY).write_text("changed\n")
        seal = replay.read(bundle / "SOURCE_SEAL.json")
        seal["source_hashes"][run.ENTRY] = replay.digest(repo / run.ENTRY)
        write(bundle / "SOURCE_SEAL.json", seal)
    elif kind in ("source_missing", "source_escape", "wrong_commit"):
        seal = replay.read(bundle / "SOURCE_SEAL.json")
        if kind == "source_missing":
            seal["source_hashes"].pop(run.ENTRY)
        elif kind == "source_escape":
            seal["source_hashes"]["../outside.py"] = "a" * 64
        else:
            seal["source_commit"] = "f" * 40
        write(bundle / "SOURCE_SEAL.json", seal)
    elif kind == "source_symlink":
        target = repo / run.ENTRY
        outside = tmp_path / "outside.py"
        outside.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(outside)
    elif kind == "missing_finish":
        (directory / "FINISHED.json").unlink()
    elif kind == "missing_runtime":
        directory.rename(bundle / "unpublished-cuda")
    elif kind == "receipt_extra":
        (directory / "UNOWNED.json").write_text("{}")
    elif kind.startswith("started_") or kind == "source_check":
        started = replay.read(directory / "STARTED.json")
        if kind == "started_identity":
            started["source_commit"] = "f" * 40
        elif kind == "started_plan":
            started["plan"]["wall_limit_seconds"] = 901
        else:
            started["source_check"]["isolated_python"] = 1
        write(directory / "STARTED.json", started)
        reseal(directory, finished)
    elif kind in ("junit_failure", "junit_duplicate"):
        tree = ET.parse(directory / "TESTS.xml")
        cases = list(tree.getroot().iter("testcase"))
        if kind == "junit_failure":
            ET.SubElement(cases[0], "failure")
        else:
            cases[1].set("name", cases[0].get("name"))
        tree.write(directory / "TESTS.xml")
        reseal(directory, finished)
    elif kind == "duplicate_json":
        original = (directory / "STARTED.json").read_text()
        (directory / "STARTED.json").write_text('{"pid": 1235,' + original[1:])
        reseal(directory, finished)
    else:
        if kind == "status":
            finished["status"] = "FAILED"
        elif kind == "error_field":
            finished["error"] = "must not be ignored"
        elif kind == "exit_bool":
            finished["pytest_exit_code"] = False
        elif kind == "count_bool":
            finished["counts"]["failures"] = False
        elif kind == "count_drift":
            finished["counts"]["tests"] = 199
        elif kind == "file_count_drift":
            finished["cases_by_file"][next(iter(run.EXPECTED_BY_FILE))] = 86
        elif kind == "offline":
            finished["offline_environment"]["HF_HUB_OFFLINE"] = "0"
        elif kind in ("cuda_peak", "cuda_peak_bool", "elapsed"):
            key, value = {
                "cuda_peak": ("peak_cuda_allocated_bytes", 5 * 2**30),
                "cuda_peak_bool": ("peak_cuda_allocated_bytes", True),
                "elapsed": ("elapsed_seconds", 901),
            }[kind]
            finished[key] = value
        elif kind == "import_missing":
            finished["imported_project_sources"].pop(
                next(iter(finished["imported_project_sources"]))
            )
        elif kind == "import_unsealed":
            finished["imported_project_sources"]["unowned"] = "src/unowned.py"
        elif kind == "artifact_digest":
            finished["files"]["TESTS.xml"]["sha256"] = "0" * 64
        write(directory / "FINISHED.json", finished)
    with pytest.raises(ValueError):
        replay.verify(bundle, repo)
