"""Offline runner guards; not included in the isolated model-test population."""

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest

from scripts import qualify_v18_window_reference as run


@pytest.fixture
def frozen_plan(monkeypatch):
    by_file = dict(run.EXPECTED_BY_FILE)
    by_file["tests/test_v18_window_learner.py"] = 3
    monkeypatch.setattr(run, "EXPECTED_BY_FILE", by_file)
    plan = json.loads((run.ROOT / run.PLAN).read_text())
    plan["expected_cases_by_file"] = by_file
    plan["expected_test_cases"] = sum(by_file.values())
    return plan


def xml_report(path, plan):
    root = ElementTree.Element("testsuites")
    for source, count in plan["expected_cases_by_file"].items():
        suite = ElementTree.SubElement(
            root, "testsuite", tests=str(count), failures="0", errors="0", skipped="0",
        )
        for index in range(count):
            ElementTree.SubElement(
                suite, "testcase", file=source, classname=Path(source).stem,
                name=f"test_case_{index}",
            )
    ElementTree.ElementTree(root).write(path)


def test_frozen_plan_qualifies_and_pending_count_cannot_dispatch(frozen_plan, monkeypatch):
    run.validate_plan(frozen_plan)
    incomplete = dict(run.EXPECTED_BY_FILE)
    incomplete["tests/test_v18_window_learner.py"] = None
    monkeypatch.setattr(run, "EXPECTED_BY_FILE", incomplete)
    with pytest.raises(ValueError, match="not frozen"):
        run.validate_plan(frozen_plan)


@pytest.mark.parametrize("key,value", [
    ("test_files", ["tests/another.py"]),
    ("expected_test_cases", 1),
    ("expected_cases_by_file", {}),
    ("max_threads", 4),
    ("gpu_memory_limit_gib", 5),
    ("wall_limit_seconds", 901),
    ("schema", "v16"),
    ("fresh_process_per_device", 1),
    ("device_env", "OTHER_DEVICE"),
    ("old_expression_gate", "PASS"),
    ("judge_calls", 1),
    ("new_sequences", False),
    ("offline_environment", {}),
    ("extra", "field"),
])
def test_fixed_plan_rejects_mutation(frozen_plan, key, value):
    changed = copy.deepcopy(frozen_plan)
    changed[key] = value
    with pytest.raises(ValueError, match="plan changed"):
        run.validate_plan(changed)


def test_report_counts_exact_selection_and_unique_cases(tmp_path, frozen_plan):
    path = tmp_path / "TESTS.xml"
    xml_report(path, frozen_plan)
    counts, by_file = run.test_report(path, frozen_plan)
    assert counts == {
        "tests": frozen_plan["expected_test_cases"], "failures": 0, "errors": 0, "skipped": 0,
    }
    assert by_file == frozen_plan["expected_cases_by_file"]


@pytest.mark.parametrize("kind", ["scope", "duplicate", "count", "per_file"])
def test_report_fails_closed_on_test_population_change(tmp_path, frozen_plan, kind):
    path = tmp_path / "TESTS.xml"
    xml_report(path, frozen_plan)
    tree = ElementTree.parse(path)
    cases = list(tree.getroot().iter("testcase"))
    if kind == "scope":
        cases[0].set("file", "tests/unselected.py")
    elif kind == "duplicate":
        cases[1].set("name", cases[0].get("name"))
    elif kind == "count":
        next(tree.getroot().iter("testsuite")).set("tests", "1")
    else:
        cases[0].set("file", "tests/test_v18_window_learner.py")
    tree.write(path)
    with pytest.raises(ValueError):
        run.test_report(path, frozen_plan)


def import_fixture(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    monkeypatch.setattr(run, "ROOT", root)
    hashes, modules = {}, {}
    for source in sorted(run.CRITICAL_IMPORTS):
        path = root / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# synthetic source identity fixture\n")
        hashes[source] = hashlib.sha256(path.read_bytes()).hexdigest()
        name = (
            "latent_workspace_ft_v10." + path.stem if source.startswith("src/") else path.stem
        )
        modules[name] = SimpleNamespace(__file__=str(path))
    return {"source_hashes": hashes}, modules


def test_import_closure_binds_all_new_modules_and_tests(tmp_path, monkeypatch):
    seal, modules = import_fixture(tmp_path, monkeypatch)
    result = run.imported_sources(seal, modules)
    assert set(result.values()) == run.CRITICAL_IMPORTS


@pytest.mark.parametrize("kind", ["missing", "escaped", "unsealed", "changed", "no_source"])
def test_import_closure_rejects_shadow_or_missing_source(tmp_path, monkeypatch, kind):
    seal, modules = import_fixture(tmp_path, monkeypatch)
    name = next(iter(modules))
    if kind == "missing":
        del modules[name]
    elif kind == "escaped":
        modules[name].__file__ = str(tmp_path / "outside.py")
    elif kind == "unsealed":
        path = run.ROOT / "unexpected.py"
        path.write_text("# unsealed\n")
        modules["unexpected_import_name"] = SimpleNamespace(__file__=str(path))
    elif kind == "changed":
        Path(modules[name].__file__).write_text("# changed\n")
    else:
        modules[name].__file__ = None
    with pytest.raises(ValueError):
        run.imported_sources(seal, modules)


def test_receipts_are_exclusive_and_preimport_requires_isolation(tmp_path, monkeypatch):
    path = tmp_path / "receipt.json"
    run.write_new(path, {"first": True})
    with pytest.raises(FileExistsError):
        run.write_new(path, {"overwritten": True})
    assert json.loads(path.read_text()) == {"first": True}
    monkeypatch.setattr(run.sys, "flags", SimpleNamespace(isolated=0))
    with pytest.raises(ValueError, match="isolated pre-import"):
        run.execute(SimpleNamespace())
