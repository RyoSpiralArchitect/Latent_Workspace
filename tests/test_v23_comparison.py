"""No real-model calls: full v1/v2 restore before matched inference."""

import copy

import pytest
import run_v23_comparison as run
import torch
from test_native_owner import setup as legacy_setup
from test_native_owner import update as legacy_update
from test_preservation_owner import batch, fixture, update

from latent_workspace.optimizer_state import tree_hash


@pytest.fixture(autouse=True)
def threads():
    old = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(old)


def test_complete_frozen_evaluation_contract():
    plan = run.ex.read(run.ROOT / run.PLAN)
    run.validate(plan)
    old = run.reference(plan)
    assert old["generation"]["seeds"] == [2026102101, 2026102102]
    assert old["generation"]["max_new_tokens"] == 256
    assert old["world_generation"]["max_new_tokens"] == 24
    assert plan["planned"]["total_new_sequences"] == 3 * 216
    assert not run.RUN.updates_native


@pytest.mark.parametrize(
    "field,value",
    [
        ("no_retry", False),
        ("roles", ["on"]),
        ("training_source", "1" * 40),
        ("reference_evaluation_plan_sha256", "0" * 64),
        ("resources", {}),
    ],
)
def test_changed_contract_rejected(field, value):
    plan = run.ex.read(run.ROOT / run.PLAN)
    plan[field] = value
    with pytest.raises((ValueError, KeyError)):
        run.validate(plan)


@pytest.mark.parametrize("kind", ["mistral", "olmo2", "gpt2", "scratch"])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_v1_v2_strict_restore_then_inference_parity(kind, enabled, dtype, tmp_path):
    if enabled:
        owner, rows, _ = fixture(tmp_path / "targets.safetensors", kind, dtype)
        graph = copy.deepcopy(owner.graph)
        update(owner, rows)
        data = batch(rows[-1], next(owner.graph.parameters()).device)
    else:
        owner, data = legacy_setup(kind, dtype)
        graph = copy.deepcopy(owner.graph)
        legacy_update(owner, data)
    path = tmp_path / "checkpoint.pt"
    receipt = owner.save(path)
    fingerprint = run.common.fingerprint(owner)
    restored, actual = run.restore_checkpoint(
        graph,
        path,
        receipt,
        owner.config,
        owner.run_contract,
        fingerprint,
        preservation=owner.preservation,
    )
    assert actual == fingerprint and graph.training
    assert tree_hash(restored.payload()) == receipt["state_sha256"]
    for candidate in (graph, owner.graph):
        if kind != "scratch":
            candidate.model.gradient_checkpointing_disable()
        candidate.eval().requires_grad_(False)
    before = tree_hash(graph.model.state_dict())
    with torch.no_grad():
        assert torch.equal(graph(**data).logits, owner.graph(**data).logits)
    assert tree_hash(graph.model.state_dict()) == before == actual["native"]


@pytest.mark.parametrize("damage", ["bytes", "sha256", "state_sha256", "contract", "bank"])
def test_restore_guard_rejects_damage_before_inference(damage, tmp_path):
    owner, rows, _ = fixture(tmp_path / "targets.safetensors")
    graph = copy.deepcopy(owner.graph)
    update(owner, rows)
    path = tmp_path / "checkpoint.pt"
    receipt = owner.save(path)
    contract = copy.deepcopy(owner.run_contract)
    bank = owner.preservation
    if damage == "bytes":
        receipt[damage] += 1
    elif damage in ("sha256", "state_sha256"):
        receipt[damage] = "0" * 64
    elif damage == "contract":
        contract["objective"] = "query_only_token_weighted_causal_nll"
    else:
        bank = None
    before = tree_hash(graph.model.state_dict())
    with pytest.raises(ValueError):
        run.restore_checkpoint(
            graph,
            path,
            receipt,
            owner.config,
            contract,
            run.common.fingerprint(owner),
            preservation=bank,
        )
    assert graph.training and tree_hash(graph.model.state_dict()) == before


def test_reference_evaluator_defaults_remain_legacy():
    import inspect

    assert inspect.signature(run.previous.prepare).parameters["restore"].default is None
    assert inspect.signature(run.previous.run).parameters["sequences_per_arm"].default is None


def test_missing_terminal_keeps_generation_unknown():
    result = {}
    run.RUN.activity(result)
    assert result == dict(new_sequences=None, native_weight_updates=0)
