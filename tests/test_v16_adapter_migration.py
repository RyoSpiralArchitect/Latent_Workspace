"""Tiny complete-window migration and offline contract checks; not a 7B run."""

import copy
import json
from pathlib import Path

import pytest
import torch
from test_v15_native_learner import OPT, owner
from test_v15_native_runner import make_store

from latent_workspace_ft_v10.adapter_native_learner_v2 import AdapterNativeLearnerV2
from latent_workspace_ft_v10.training_binding import MistralTrainingBinding
from latent_workspace_ft_v10.v15_native_learner import tree_hash
from scripts import run_v16_adapter_migration as run
from scripts import verify_v16_adapter_migration as verify


@pytest.fixture(autouse=True)
def runtime():
    run.load_runtime()
    old = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(old)


def new_adapter(dtype, full):
    parts = owner(dtype, full)
    contract = {
        "original_base_sha256": tree_hash(parts.base.state_dict()),
        "objective": {"same": "tiny six terms"},
    }
    return AdapterNativeLearnerV2(
        MistralTrainingBinding(parts.base, 1),
        parts.bridge,
        full_update=full,
        optimizer_config=OPT,
        run_contract=contract,
    )


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("full", [False, True])
def test_two_complete_16_pair_windows_match(monkeypatch, tmp_path, dtype, full):
    reference, candidate = owner(dtype, full), new_adapter(dtype, full)
    reference_store, candidate_store = [make_store(monkeypatch, x) for x in (reference, candidate)]
    objective = run.legacy.old.validate()[0]
    run.assert_exact(run.state_fingerprint(reference), run.state_fingerprint(candidate), "initial")
    for step in (1, 2):
        a, b = [
            run.update_window(
                learner,
                store,
                objective,
                implementation,
                lambda *_a: None,
                tmp_path / f"{implementation}_{step}.jsonl",
            )
            for learner, store, implementation in (
                (reference, reference_store, "legacy"),
                (candidate, candidate_store, "adapter_v2"),
            )
        ]
        run.assert_exact(a, b, "complete window")
        verify.verify_window(a)
        verify.verify_window(b)
        assert len(a["pairs"]) == 16
        assert len({r["accumulated_gradients_sha256"] for r in a["pairs"]}) == 16
        assert [(r["world"], r["query"]) for r in a["pairs"]] == list(run.PAIRS)


@pytest.mark.parametrize("full", [False, True])
def test_complete_window_next_update_replay(monkeypatch, tmp_path, full):
    learner = new_adapter(torch.bfloat16, full)
    store = make_store(monkeypatch, learner)
    objective = run.legacy.old.validate()[0]
    run.update_window(learner, store, objective, "adapter_v2", lambda *_a: None)
    receipt = learner.save(tmp_path / "step1.pt", {"test": "migration"})
    expected = run.update_window(learner, store, objective, "adapter_v2", lambda *_a: None)
    fresh = new_adapter(torch.bfloat16, full)
    payload = torch.load(tmp_path / "step1.pt", map_location="cpu", weights_only=True)
    restored = AdapterNativeLearnerV2.restore(
        fresh.binding,
        fresh.bridge,
        payload,
        expected_metadata={"test": "migration"},
        expected_run_contract=learner.run_contract,
        expected_state_sha256=receipt["state_sha256"],
    )
    actual = run.update_window(
        restored, make_store(monkeypatch, restored), objective, "adapter_v2", lambda *_a: None
    )
    run.assert_exact(expected, actual, "replay")


@pytest.mark.parametrize(
    "field,value",
    [
        ("steps", [1]),
        ("adapter_checkpoints", [1]),
        ("planned_backward_pairs", 128),
        ("new_sequences", 1),
        ("weight_deletions", 1),
        ("judge_calls", 1),
        ("no_retry", False),
        ("winner", "candidate"),
        ("storage_forecast_bytes", 1),
    ],
)
def test_contract_rejects_budget_scope_claim_drift(field, value):
    plan = json.loads((run.ROOT / run.PLAN).read_text())
    run.validate_plan(plan)
    plan[field] = value
    with pytest.raises(ValueError):
        run.validate_plan(plan)


@pytest.mark.parametrize("failure", ["reorder", "loss", "gradient", "update", "rng", "missing"])
def test_comparator_rejects_every_observation_family(failure):
    original = {
        "pairs": [{"q": 0, "loss": 1.0, "gradient": "abc"}, {"q": 1}],
        "update": {"step": 1},
        "state": {"rng": "def"},
    }
    bad = copy.deepcopy(original)
    if failure == "reorder":
        bad["pairs"].reverse()
    elif failure == "loss":
        bad["pairs"][0]["loss"] += 1e-15
    elif failure == "gradient":
        bad["pairs"][0]["gradient"] = "other"
    elif failure == "update":
        bad["update"]["step"] = 2
    elif failure == "rng":
        bad["state"]["rng"] = "changed"
    else:
        bad["pairs"].pop()
    with pytest.raises(ValueError, match="Exact comparison"):
        run.assert_exact(original, bad, "mutation")


def test_output_is_exclusive_and_forbids_nonfinite(tmp_path):
    path = tmp_path / "evidence.json"
    run.write_new(path, {"status": "tiny"})
    with pytest.raises(FileExistsError):
        run.write_new(path, {})
    with pytest.raises(ValueError):
        run.canonical({"loss": float("nan")})


def test_entry_import_is_standard_library_only():
    # load_runtime is explicit; no model or third-party import is at module level.
    import ast

    tree = ast.parse(Path(run.__file__).read_text())
    imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert not any(
        "torch" in ast.unparse(n) or "latent_workspace" in ast.unparse(n) for n in imports
    )


@pytest.mark.parametrize("failure", ["missing_pair", "reorder", "hash", "spills", "step"])
def test_offline_window_validator_rejects_changed_denominators(failure):
    row = {
        "pairs": [
            {"world": w, "query": q, "accumulated_gradients_sha256": "a" * 64} for w, q in run.PAIRS
        ],
        "update": {"completed_step": 1, "transfer": {"spill_count": 16}},
        "state": {"completed_steps": 1, "native_state": {"w": "a"}, "bridge_state": {"w": "b"}},
    }
    verify.verify_window(row)
    if failure == "missing_pair":
        row["pairs"].pop()
    elif failure == "reorder":
        row["pairs"].reverse()
    elif failure == "hash":
        row["pairs"][0]["accumulated_gradients_sha256"] = None
    elif failure == "spills":
        row["update"]["transfer"]["spill_count"] = 15
    else:
        row["state"]["completed_steps"] = 2
    with pytest.raises((ValueError, TypeError)):
        verify.verify_window(row)
