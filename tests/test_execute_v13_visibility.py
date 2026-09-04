from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "execute_v13_visibility", ROOT / "scripts/execute_v13_visibility.py"
)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


@pytest.fixture
def bound_plan(tmp_path):
    plan = json.loads((ROOT / "configs/v13/VISIBILITY_RUN_PLAN.json").read_text())
    parent = tmp_path / "retained-v12"
    parent.mkdir()
    plan["checkpoint_root"] = str(parent)
    for row in plan["checkpoints"]:
        checkpoint = parent / row["path"]
        checkpoint.mkdir(parents=True)
        (checkpoint / "COMPLETED").write_text("OK\n")
        for name, key in (
            ("manifest.json", "manifest_sha256"),
            ("workspace_state.pt", "workspace_sha256"),
        ):
            payload = f"fake test {row['id']} {name}".encode()
            (checkpoint / name).write_bytes(payload)
            row[key] = hashlib.sha256(payload).hexdigest()
    return plan


def test_pinned_source_and_mock_bundle_bindings(bound_plan):
    assert len(runner.validate_plan(bound_plan, ROOT)) == 2


@pytest.mark.parametrize(
    "field",
    ["training", "base_frozen", "workspace_frozen", "deferred_sufficiency_claim", "scale_up_14b"],
)
def test_guard_change_rejected(bound_plan, field):
    plan = copy.deepcopy(bound_plan)
    plan["guards"][field] = not plan["guards"][field]
    with pytest.raises(ValueError, match="guards"):
        runner.validate_plan(plan, ROOT)


def test_bool_not_integer_guard(bound_plan):
    bound_plan["guards"]["training"] = 0
    with pytest.raises(ValueError, match="guards"):
        runner.validate_plan(bound_plan, ROOT)


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_worlds", 200),
        ("max_worlds", True),
        ("post_adapter_gain_grid", [1, 1000]),
        ("input_lane", "deferred_primary"),
        ("seed", 43),
    ],
)
def test_scope_expansion_rejected(bound_plan, field, value):
    bound_plan[field] = value
    with pytest.raises(ValueError):
        runner.validate_plan(bound_plan, ROOT)


def test_corrupted_workspace_rejected(bound_plan):
    row = bound_plan["checkpoints"][0]
    target = Path(bound_plan["checkpoint_root"]) / row["path"] / "workspace_state.pt"
    target.write_bytes(b"changed")
    with pytest.raises(ValueError, match="binding"):
        runner.validate_plan(bound_plan, ROOT)


def test_checkpoint_path_change_rejected(bound_plan):
    bound_plan["checkpoints"][0]["path"] = "../../outside"
    with pytest.raises(ValueError, match="target"):
        runner.validate_plan(bound_plan, ROOT)


def test_evidence_write_never_overwrites(tmp_path):
    target = tmp_path / "receipt.json"
    runner.write_new(target, {"first": True})
    with pytest.raises(FileExistsError):
        runner.write_new(target, {"second": True})
    assert json.loads(target.read_text()) == {"first": True}


def test_canonical_allocator_child_environment(monkeypatch):
    monkeypatch.setenv("PYTORCH_CUDA_ALLOC_CONF", "backend:cudaMallocAsync")
    monkeypatch.setenv("PYTORCH_HIP_ALLOC_CONF", "bad")
    monkeypatch.setenv("PYTORCH_NO_CUDA_MEMORY_CACHING", "1")
    environment = runner.child_environment(ROOT)
    assert environment["PYTORCH_ALLOC_CONF"] == "backend:native,expandable_segments:True"
    assert (
        not {"PYTORCH_CUDA_ALLOC_CONF", "PYTORCH_HIP_ALLOC_CONF", "PYTORCH_NO_CUDA_MEMORY_CACHING"}
        & environment.keys()
    )
    assert environment["HF_HUB_OFFLINE"] == "1"
