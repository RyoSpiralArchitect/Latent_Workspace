"""Synthetic receipt validation only; fake checkpoints are never loaded."""

import copy
import importlib.util
import json
from pathlib import Path
from xml.etree import ElementTree as E

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "v18_selection_window_verifier", ROOT / "scripts/verify_v18_selection_window.py",
)
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)
Q = V.CONTRACT


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, allow_nan=False))


def fixture(tmp_path, device="cuda"):
    repo, bundle = tmp_path / "repo", tmp_path / "output"
    source = Q.CRITICAL | {Q.ENTRY, "scripts/run_source_sealed.py",
                           "scripts/verify_v18_selection_window.py"}
    for name in source:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic source fixture\n")
    seal = {"source_commit": "a" * 40,
            "source_hashes": {name: Q.digest(repo / name) for name in source}}
    seal_path = tmp_path / "seal.json"
    write(seal_path, seal)
    check = {"schema": "pre-import-source-check-v1", "source_commit": "a" * 40,
             "entry": Q.ENTRY, "source_files": len(source), "untracked_check": "all",
             "isolated_python": True, "fresh_bytecode_cache": True}
    write(bundle / "STARTED.json", {"source_seal": seal, "plan": Q.PLAN,
                                    "device": device, "pid": 99, "source_check": check})
    jobs = [("tests", -1, "tests")]
    jobs += [(role, i, f"case-{i:02d}/{role}") for i in range(10)
             for role in ("producer", "resumer")]
    dispatched = []
    for j, (role, i, path) in enumerate(jobs):
        folder, pid = bundle / path, 100 + j
        common = {"role": role, "case_index": i, "device": device, "pid": pid}
        write(folder / "STARTED.json", {**common, "plan": Q.PLAN, "source_check": check})
        end = {**common, "status": "PASS", "elapsed_seconds": 0.5,
               "runtime": {"device": device, "threads": 2, "interop_threads": 1, "tf32": False},
               "peak_cuda_allocated_bytes": 100 if device == "cuda" else None,
               "imported_sources": {f"module{n}": name for n, name in enumerate(Q.CRITICAL)}}
        if role == "tests":
            tree = E.Element("testsuites")
            suite = E.SubElement(tree, "testsuite", tests="102", failures="0",
                                 errors="0", skipped="0")
            for n in range(102):
                E.SubElement(suite, "testcase", file=Q.TEST,
                             classname="tests.fixture", name=f"t{n}")
            E.ElementTree(tree).write(folder / "TESTS.xml")
            end.update(pytest_exit_code=0, counts=Q.test_report(folder / "TESTS.xml"))
        else:
            checkpoint = bundle / f"case-{i:02d}/producer/window1.pt"
            if role == "producer":
                checkpoint.write_bytes(b"not a checkpoint; offline receipt fixture")
                end["checkpoint_receipt"] = {
                    "bytes": checkpoint.stat().st_size, "completed_steps": 1,
                    "format": "v18-selection-window-reference-resume-v1",
                }
            else:
                end.update(producer_pid=pid - 1, checkpoint_payload_unchanged=True)
            end.update(case=Q.CASES[i], checkpoint_file_sha256=Q.digest(checkpoint),
                       window2={"completed_steps": 2, "payload_sha256": "b" * 64})
        end["files"] = Q.files(folder)
        write(folder / "FINISHED.json", end)
        dispatched.append({"role": role, "case_index": i, "relative_path": path,
                           "launcher_pid": 200 + j, "returncode": 0})
    write(bundle / "FINISHED.json", {"status": Q.PASS, "plan": Q.PLAN, "device": device,
                                     "elapsed_seconds": 11.0, "children": dispatched,
                                     "files": Q.files(bundle)})
    return repo, bundle, seal_path


def rebind_parent(bundle):
    value = V.read(bundle / "FINISHED.json")
    value["files"] = {k: v for k, v in Q.files(bundle).items() if k != "FINISHED.json"}
    write(bundle / "FINISHED.json", value)


@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_complete_synthetic_receipts_pass_without_torch(tmp_path, device):
    repo, bundle, seal = fixture(tmp_path, device)
    result = V.verify(bundle, seal, repo)
    assert result["unit_cases"] == 102 and result["restart_cases"] == 10
    assert result["independent_child_processes"] == 21
    assert result["tensor_payload_replayed"] is False


@pytest.mark.parametrize("failure", [
    "source", "source_check", "plan", "count", "duplicate", "missing_child", "order",
    "exit", "pid", "runtime", "cuda_peak", "elapsed", "case", "checkpoint",
    "window", "unchanged", "imports", "file", "extra",
])
def test_rehashed_malformed_receipts_rejected(tmp_path, failure):
    repo, bundle, seal = fixture(tmp_path)
    parent = V.read(bundle / "FINISHED.json")
    folder = bundle / "case-00/resumer"
    child = V.read(folder / "FINISHED.json")
    if failure == "source":
        (repo / Q.ENTRY).write_text("changed source")
    elif failure == "source_check":
        started = V.read(folder / "STARTED.json")
        started["source_check"]["isolated_python"] = False
        write(folder / "STARTED.json", started)
        child["files"] = {k: v for k, v in Q.files(folder).items() if k != "FINISHED.json"}
    elif failure == "plan":
        parent["plan"]["max_threads"] = 4
    elif failure in ("count", "duplicate"):
        path = bundle / "tests/TESTS.xml"
        tree = E.parse(path)
        cases = list(tree.iter("testcase"))
        if failure == "count":
            next(tree.iter("testsuite")).remove(cases[-1])
        else:
            cases[-1].set("name", cases[0].get("name"))
        tree.write(path)
        end = V.read(bundle / "tests/FINISHED.json")
        end["files"] = {k: v for k, v in Q.files(bundle / "tests").items()
                        if k != "FINISHED.json"}
        write(bundle / "tests/FINISHED.json", end)
    elif failure == "missing_child":
        parent["children"].pop()
    elif failure == "order":
        parent["children"].reverse()
    elif failure == "exit":
        parent["children"][0]["returncode"] = 1
    elif failure == "pid":
        child["producer_pid"] += 1
    elif failure == "runtime":
        child["runtime"]["tf32"] = True
    elif failure == "cuda_peak":
        child["peak_cuda_allocated_bytes"] = 0
    elif failure == "elapsed":
        child["elapsed_seconds"] = 61
    elif failure == "case":
        child["case"]["query"] = "final"
    elif failure == "checkpoint":
        child["checkpoint_file_sha256"] = "0" * 64
    elif failure == "window":
        child["window2"]["payload_sha256"] = "0" * 64
    elif failure == "unchanged":
        child["checkpoint_payload_unchanged"] = False
    elif failure == "imports":
        child["imported_sources"] = {}
    elif failure == "file":
        child["files"]["STARTED.json"]["sha256"] = "0" * 64
    else:
        (folder / "unexpected.txt").write_text("not in child manifest")
    write(folder / "FINISHED.json", child)
    write(bundle / "FINISHED.json", parent)
    rebind_parent(bundle)
    with pytest.raises(ValueError):
        V.verify(bundle, seal, repo)


def test_child_environment_does_not_import_secrets_or_change_home(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-pass")
    for device in ("cpu", "cuda"):
        env = Q.environment(device)
        assert not {"HOME", "CODEX_HOME", "PYTHONPATH", "OPENAI_API_KEY"} & set(env)
        assert env["LATENT_SLOT_STATE_TEST_DEVICE"] == device
        assert env["HF_HUB_OFFLINE"] == env["TRANSFORMERS_OFFLINE"] == "1"


def test_frozen_case_matrix_has_no_duplicates():
    assert len(Q.CASES) == len({json.dumps(v, sort_keys=True) for v in Q.CASES}) == 10
    assert sum(c["query"] == "ordered_difference" for c in Q.CASES) == 8
    assert Q.PLAN["test_cases"] == 102
    assert copy.deepcopy(Q.PLAN) == Q.PLAN
