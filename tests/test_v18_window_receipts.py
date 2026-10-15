"""Synthetic offline receipts, never real qualification or model execution."""

import copy
import json
from xml.etree import ElementTree as ET

import pytest

from scripts import verify_v18_window_reference as verify


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True))


def fixture(tmp_path, monkeypatch, device="cuda"):
    repo, bundle = tmp_path / "source", tmp_path / "bundle" / device
    bundle.mkdir(parents=True)
    for name in verify.CRITICAL:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Synthetic fixture only; not execution evidence.\n")
    population = dict(zip(verify.TESTS, (85, 59, 166), strict=True))
    monkeypatch.setattr(verify.QUALIFICATION, "EXPECTED_BY_FILE", population)
    plan = {
        "schema": "v18-window-reference-qualification-v1",
        "test_files": list(verify.TESTS),
        "expected_cases_by_file": population,
        "expected_test_cases": sum(population.values()),
        "max_threads": 2,
        "gpu_memory_limit_gib": 4,
        "wall_limit_seconds": 900,
        "arms": ["common", "slot_contrast", "raw_matched_control"],
        "device_env": "LATENT_SLOT_STATE_TEST_DEVICE",
        "fresh_process_per_device": True,
        "offline_environment": copy.deepcopy(verify.QUALIFICATION.OFFLINE_ENV),
        "claim_ceiling": (
            "tiny immutable reference ownership/window reduction/update/replay only; "
            "no preservation loss, real reference capture, semantic or 7B qualification"
        ),
        **verify.QUALIFICATION.CEILING,
    }
    write(repo / verify.PLAN, plan)
    seal = {
        "source_commit": "a" * 40,
        "source_hashes": {name: verify.digest(repo / name) for name in verify.CRITICAL},
    }
    write(bundle.parent / "SOURCE_SEAL.json", seal)
    started = {
        **seal,
        "plan": plan,
        "device": device,
        "pid": 1234,
        "python": "3.12.14",
        "source_check": {
            "schema": "pre-import-source-check-v1",
            "source_commit": seal["source_commit"],
            "entry": verify.ENTRY,
            "source_files": len(seal["source_hashes"]),
            "untracked_check": "all",
            "isolated_python": True,
            "fresh_bytecode_cache": True,
        },
    }
    write(bundle / "STARTED.json", started)
    root = ET.Element("testsuites")
    for index, (filename, count) in enumerate(population.items()):
        suite = ET.SubElement(
            root, "testsuite", tests=str(count), failures="0", errors="0", skipped="0"
        )
        for case in range(count):
            ET.SubElement(
                suite, "testcase", classname=f"fixture{index}", name=f"test_{case}", file=filename
            )
    ET.ElementTree(root).write(bundle / "TESTS.xml")
    finished = {
        "status": verify.PASS,
        "device": device,
        "pytest_exit_code": 0,
        "counts": {"tests": sum(population.values()), "failures": 0, "errors": 0, "skipped": 0},
        "cases_by_file": population,
        "peak_cuda_allocated_bytes": 123456 if device == "cuda" else None,
        "elapsed_seconds": 30.0,
        "runtime": {
            "python": "3.12.14",
            "torch": "2.13.0",
            "pytest": "9.1.1",
            "transformers": "5.15.0",
            "platform": "synthetic-fixture",
            "cuda": "13.2" if device == "cuda" else None,
        },
        "offline_environment": copy.deepcopy(plan["offline_environment"]),
        "imported_project_sources": {
            f"fixture_{i}": name for i, name in enumerate((*verify.MODULES, *verify.TESTS))
        },
        **verify.QUALIFICATION.CEILING,
    }
    reseal(bundle, finished)
    return repo, bundle, finished


def reseal(bundle, finished):
    finished["files"] = {
        name: {"bytes": (bundle / name).stat().st_size, "sha256": verify.digest(bundle / name)}
        for name in ("STARTED.json", "TESTS.xml")
    }
    write(bundle / "FINISHED.json", finished)


def replace_plan(repo, bundle, plan):
    write(repo / verify.PLAN, plan)
    seal = verify.read(bundle.parent / "SOURCE_SEAL.json")
    seal["source_hashes"][verify.PLAN] = verify.digest(repo / verify.PLAN)
    write(bundle.parent / "SOURCE_SEAL.json", seal)
    started = verify.read(bundle / "STARTED.json")
    started.update(**seal, plan=plan)
    write(bundle / "STARTED.json", started)


@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_valid_synthetic_receipt_replays_exact_population(tmp_path, monkeypatch, device):
    repo, bundle, finished = fixture(tmp_path, monkeypatch, device)
    result = verify.verify(bundle, repo)
    assert result["counts"]["tests"] == 310
    assert result["cases_by_file"] == finished["cases_by_file"]
    assert result["status"] == verify.PASS
    assert result["old_expression_gate"] == "FAIL"
    assert result["non_regression"] == "NOT_ESTABLISHED"


@pytest.mark.parametrize(
    "mutation",
    [
        "bytes",
        "source",
        "artifact_extra",
        "artifact_missing",
        "artifact_symlink",
        "source_seal_extra",
        "source_hash_bad",
        "missing_critical",
        "source_identity",
        "source_path_escape",
        "source_symlink_escape",
        "source_receipt",
        "source_receipt_bool",
        "started_extra",
        "started_missing",
        "finished_extra",
        "finished_missing",
        "import_missing",
        "import_unsealed",
        "import_schema",
        "duplicate_json",
        "status",
        "device",
        "exit_code",
        "exit_bool",
        "count_bool",
        "counts",
        "file_counts",
        "offline",
        "runtime",
        "runtime_python",
        "cuda_runtime",
        "peak",
        "peak_zero",
        "peak_bool",
        "elapsed",
        "elapsed_zero",
        "elapsed_bool",
        "elapsed_nan",
        "byte_bool",
        "pid_bool",
    ],
)
def test_corrupt_receipts_fail_even_with_reissued_file_hashes(tmp_path, monkeypatch, mutation):
    repo, bundle, finished = fixture(tmp_path, monkeypatch)
    if mutation == "bytes":
        (bundle / "TESTS.xml").write_text("changed")
    elif mutation == "source":
        (repo / verify.MODULES[0]).write_text("changed")
    elif mutation == "artifact_extra":
        (bundle / "UNOWNED.json").write_text("{}")
    elif mutation == "artifact_missing":
        (bundle / "TESTS.xml").unlink()
    elif mutation == "artifact_symlink":
        external = tmp_path / "external.xml"
        external.write_bytes((bundle / "TESTS.xml").read_bytes())
        (bundle / "TESTS.xml").unlink()
        (bundle / "TESTS.xml").symlink_to(external)
    elif (
        mutation.startswith("source_")
        and mutation
        not in (
            "source_receipt",
            "source_receipt_bool",
            "source_identity",
        )
        or mutation == "missing_critical"
    ):
        seal = verify.read(bundle.parent / "SOURCE_SEAL.json")
        if mutation == "source_seal_extra":
            seal["extra"] = True
        elif mutation == "source_hash_bad":
            seal["source_hashes"][verify.MODULES[0]] = "z" * 64
        elif mutation == "missing_critical":
            seal["source_hashes"].pop(verify.MODULES[0])
        elif mutation == "source_path_escape":
            seal["source_hashes"]["../outside.py"] = "b" * 64
        else:
            external = tmp_path / "outside.py"
            external.write_bytes((repo / verify.MODULES[0]).read_bytes())
            (repo / verify.MODULES[0]).unlink()
            (repo / verify.MODULES[0]).symlink_to(external)
        write(bundle.parent / "SOURCE_SEAL.json", seal)
    elif mutation in (
        "source_identity",
        "source_receipt",
        "source_receipt_bool",
        "started_extra",
        "started_missing",
        "pid_bool",
    ):
        started = verify.read(bundle / "STARTED.json")
        if mutation == "source_identity":
            started["source_commit"] = "b" * 40
        elif mutation == "source_receipt":
            started["source_check"]["fresh_bytecode_cache"] = False
        elif mutation == "source_receipt_bool":
            started["source_check"]["isolated_python"] = 1
        elif mutation == "started_extra":
            started["extra"] = True
        elif mutation == "started_missing":
            started.pop("plan")
        else:
            started["pid"] = True
        write(bundle / "STARTED.json", started)
    elif mutation == "finished_extra":
        finished["ignored_error"] = "Failure must not be ignored"
    elif mutation == "finished_missing":
        finished.pop("counts")
    elif mutation == "import_missing":
        finished["imported_project_sources"].pop("fixture_0")
    elif mutation == "import_unsealed":
        finished["imported_project_sources"]["other"] = "src/unsealed.py"
    elif mutation == "import_schema":
        finished["imported_project_sources"] = list(finished["imported_project_sources"].values())
    elif mutation == "duplicate_json":
        serialized = (bundle / "STARTED.json").read_text()
        (bundle / "STARTED.json").write_text('{"pid": 1234,' + serialized[1:])
    elif mutation == "count_bool":
        finished["counts"]["failures"] = False
    elif mutation == "counts":
        finished["counts"]["tests"] -= 1
    elif mutation == "file_counts":
        finished["cases_by_file"] = dict(finished["cases_by_file"])
        finished["cases_by_file"][verify.TESTS[0]] -= 1
    elif mutation == "offline":
        finished["offline_environment"]["HF_HUB_OFFLINE"] = "0"
    elif mutation == "runtime":
        finished["runtime"]["ignored"] = "unowned"
    elif mutation == "runtime_python":
        finished["runtime"]["python"] = "other-version"
    elif mutation == "cuda_runtime":
        finished["runtime"]["cuda"] = None
    elif mutation == "byte_bool":
        pass
    else:
        key, value = {
            "status": ("status", "INCOMPLETE"),
            "device": ("device", "cpu"),
            "exit_code": ("pytest_exit_code", 1),
            "exit_bool": ("pytest_exit_code", False),
            "peak": ("peak_cuda_allocated_bytes", 5 * 2**30),
            "peak_zero": ("peak_cuda_allocated_bytes", 0),
            "peak_bool": ("peak_cuda_allocated_bytes", True),
            "elapsed": ("elapsed_seconds", 961),
            "elapsed_zero": ("elapsed_seconds", 0),
            "elapsed_bool": ("elapsed_seconds", True),
            "elapsed_nan": ("elapsed_seconds", float("nan")),
        }[mutation]
        finished[key] = value
    if mutation not in ("bytes", "artifact_missing"):
        reseal(bundle, finished)
    if mutation == "byte_bool":
        finished["files"]["STARTED.json"]["bytes"] = True
        write(bundle / "FINISHED.json", finished)
    with pytest.raises(ValueError):
        verify.verify(bundle, repo)


@pytest.mark.parametrize(
    "mutation",
    [
        "schema",
        "extra",
        "denominator",
        "per_file",
        "bool_count",
        "test_order",
        "threads",
        "wall",
        "memory",
        "offline",
        "fresh",
        "gate",
    ],
)
def test_changed_plan_rejected_even_if_source_and_start_are_resealed(
    tmp_path, monkeypatch, mutation
):
    repo, bundle, finished = fixture(tmp_path, monkeypatch)
    plan = verify.read(repo / verify.PLAN)
    if mutation == "schema":
        plan["schema"] = "unknown"
    elif mutation == "extra":
        plan["ignored"] = 1
    elif mutation == "denominator":
        plan["expected_test_cases"] -= 1
    elif mutation == "per_file":
        plan["expected_cases_by_file"][verify.TESTS[0]] -= 1
        plan["expected_cases_by_file"][verify.TESTS[1]] += 1
    elif mutation == "bool_count":
        plan["expected_cases_by_file"][verify.TESTS[0]] = True
    elif mutation == "test_order":
        plan["test_files"].reverse()
    elif mutation == "offline":
        plan["offline_environment"]["HF_HUB_OFFLINE"] = "0"
    else:
        key, value = {
            "threads": ("max_threads", 4),
            "wall": ("wall_limit_seconds", 901),
            "memory": ("gpu_memory_limit_gib", 5),
            "fresh": ("fresh_process_per_device", 1),
            "gate": ("old_expression_gate", "PASS"),
        }[mutation]
        plan[key] = value
    replace_plan(repo, bundle, plan)
    reseal(bundle, finished)
    with pytest.raises(ValueError):
        verify.verify(bundle, repo)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "missing",
        "wrong_file",
        "missing_name",
        "missing_class",
        "file_counts",
        "skipped",
        "failure",
        "error",
        "suite_count",
        "suite_skips",
        "negative_count",
        "missing_denominator",
        "nested_suite",
        "unknown_child",
        "root",
        "malformed",
    ],
)
def test_junit_identity_and_population_rejected_even_when_rehashed(tmp_path, monkeypatch, mutation):
    repo, bundle, finished = fixture(tmp_path, monkeypatch)
    tree = ET.parse(bundle / "TESTS.xml")
    root = tree.getroot()
    suites, cases = list(root), list(root.iter("testcase"))
    if mutation == "duplicate":
        cases[1].set("name", cases[0].get("name"))
    elif mutation == "missing":
        suites[0].remove(cases[0])
    elif mutation == "wrong_file":
        cases[0].set("file", "tests/unselected.py")
    elif mutation == "missing_name":
        cases[0].attrib.pop("name")
    elif mutation == "missing_class":
        cases[0].attrib.pop("classname")
    elif mutation == "file_counts":
        cases[0].set("file", verify.TESTS[1])
    elif mutation in ("skipped", "failure", "error"):
        ET.SubElement(cases[0], mutation)
    elif mutation == "suite_count":
        suites[0].set("tests", "84")
    elif mutation == "suite_skips":
        suites[0].set("skipped", "1")
    elif mutation == "negative_count":
        suites[0].set("errors", "-1")
    elif mutation == "missing_denominator":
        suites[0].attrib.pop("errors")
    elif mutation == "nested_suite":
        ET.SubElement(suites[0], "testsuite", tests="0", errors="0", skipped="0", failures="0")
    elif mutation == "unknown_child":
        ET.SubElement(suites[0], "unowned")
    elif mutation == "root":
        root.tag = "unowned"
    tree.write(bundle / "TESTS.xml")
    if mutation == "malformed":
        (bundle / "TESTS.xml").write_text("<bad")
    reseal(bundle, finished)
    with pytest.raises(ValueError):
        verify.verify(bundle, repo)


@pytest.mark.parametrize("field", list(verify.QUALIFICATION.CEILING))
@pytest.mark.parametrize("kind", ["value", "type"])
def test_unchanged_claim_ceilings_are_strict(tmp_path, monkeypatch, field, kind):
    repo, bundle, finished = fixture(tmp_path, monkeypatch)
    expected = finished[field]
    finished[field] = (
        (1 if kind == "value" else False)
        if type(expected) is int
        else ("PROMOTED" if kind == "value" else None)
    )
    reseal(bundle, finished)
    with pytest.raises(ValueError):
        verify.verify(bundle, repo)


def test_cpu_receipt_cannot_claim_cuda_allocation(tmp_path, monkeypatch):
    repo, bundle, finished = fixture(tmp_path, monkeypatch, "cpu")
    finished["peak_cuda_allocated_bytes"] = 1
    reseal(bundle, finished)
    with pytest.raises(ValueError):
        verify.verify(bundle, repo)
