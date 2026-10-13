"""Qualify the composed production setup, not only direct HF checkpointing."""

import copy
import functools
import os
import types

import pytest
import torch
from test_readout_adapters import FAMILIES, model
from test_v15_native_learner import OPT, owner
from test_v15_native_runner import make_store

from latent_workspace_ft_v10.adapter_native_learner_v2 import AdapterNativeLearnerV2
from latent_workspace_ft_v10.engine import enable_gradient_checkpointing
from latent_workspace_ft_v10.hf_training_readout import HFTrainingReadoutAdapter
from latent_workspace_ft_v10.native_training_preparation import (
    prepare_native_gradient_checkpointing,
)
from latent_workspace_ft_v10.training_binding import MistralTrainingBinding
from latent_workspace_ft_v10.v15_native_learner import rng_state, tree_hash
from scripts import run_v16_adapter_migration as run

DEVICE = os.environ.get("LATENT_PREPARATION_TEST_DEVICE", "cpu")


@pytest.fixture(autouse=True)
def setup():
    run.load_runtime()
    old = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(old)


def hooks(base):
    return [
        (n, tuple(m._forward_hooks.items())) for n, m in base.named_modules() if m._forward_hooks
    ]


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_preparation_is_idempotent_and_keeps_values_parameters_rng(family, dtype):
    base = model(family, dtype).to(DEVICE).train().requires_grad_(True)
    native = copy.deepcopy(base)
    before, random = tree_hash(base.state_dict()), tree_hash(rng_state())
    parameters = [(n, id(p), p.requires_grad) for n, p in base.named_parameters()]
    first = prepare_native_gradient_checkpointing(base)
    registered = hooks(base)
    for _ in range(3):
        assert prepare_native_gradient_checkpointing(base) == first
        assert hooks(base) == registered
    assert tree_hash(base.state_dict()) == before
    assert tree_hash(rng_state()) == random
    assert [(n, id(p), p.requires_grad) for n, p in base.named_parameters()] == parameters
    assert first["input_gradient_hook"]["registered"] == 1
    ids = torch.tensor([[1, 4, 5]], device=DEVICE)
    a = base(ids, use_cache=False).logits
    b = native(ids, use_cache=False).logits
    assert torch.equal(a, b)
    a.float().sum().backward()
    b.float().sum().backward()
    for (name, x), (_, y) in zip(base.named_parameters(), native.named_parameters(), strict=True):
        assert (x.grad is None) == (y.grad is None), name
        if x.grad is not None:
            assert torch.equal(x.grad, y.grad), name


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_historical_duplicate_reproduces_failure_and_is_not_silently_repaired(dtype):
    base = model("mistral", dtype).to(DEVICE).train()
    enable_gradient_checkpointing(base)
    before, random = hooks(base), tree_hash(rng_state())
    assert sum(len(rows) for _, rows in before) == 2
    with pytest.raises(ValueError, match="unqualified native hooks"):
        prepare_native_gradient_checkpointing(base)
    assert hooks(base) == before
    assert tree_hash(rng_state()) == random


@pytest.mark.parametrize(
    "mutation",
    [
        "foreign",
        "head",
        "pre",
        "lost_handle",
        "extra_handle",
        "alias",
        "kwargs",
        "mixed",
        "reentrant",
        "patched",
    ],
)
def test_unowned_or_changed_setup_rejected_without_repair(mutation):
    base = model("mistral").to(DEVICE).train()
    prepare_native_gradient_checkpointing(base)
    embedding = base.get_input_embeddings()
    if mutation == "foreign":
        embedding.register_forward_hook(lambda m, a, y: y)
    elif mutation == "head":
        base.lm_head.register_forward_hook(lambda m, a, y: y)
    elif mutation == "pre":
        embedding.register_forward_pre_hook(lambda m, a: a)
    elif mutation == "lost_handle":
        base._require_grads_hooks = []
    elif mutation == "extra_handle":
        base._require_grads_hooks.append(base._require_grads_hooks[0])
    elif mutation == "alias":
        base._require_grads_hook = None
    elif mutation == "kwargs":
        embedding._forward_hooks_with_kwargs[next(iter(embedding._forward_hooks))] = True
    elif mutation == "mixed":
        base.model.layers[0].gradient_checkpointing = False
    elif mutation == "reentrant":
        for layer in base.model.layers:
            layer._gradient_checkpointing_func = functools.partial(
                torch.utils.checkpoint.checkpoint, use_reentrant=True
            )
    else:
        base.gradient_checkpointing_enable = types.MethodType(lambda self, **kw: None, base)
    before, state, random = hooks(base), tree_hash(base.state_dict()), tree_hash(rng_state())
    with pytest.raises(ValueError):
        prepare_native_gradient_checkpointing(base)
    assert hooks(base) == before
    assert tree_hash(base.state_dict()) == state
    assert tree_hash(rng_state()) == random


def build(dtype, legacy):
    parts = owner(dtype, True)
    parts.base.to(DEVICE)
    parts.bridge.to(DEVICE)
    # Owner helper initially creates CPU masters. Native and bridge references
    # stay the same after .to; a fresh production owner below owns the graph.
    if legacy:
        enable_gradient_checkpointing(parts.base)
        return run.legacy.V15NativeLearner(
            parts.base, parts.bridge, full_update=True, optimizer_config=OPT, boundary=1
        )
    preparation = prepare_native_gradient_checkpointing(parts.base)
    assert prepare_native_gradient_checkpointing(parts.base) == preparation
    contract = {
        "original_base_sha256": tree_hash(parts.base.state_dict()),
        "objective": {"same": "six terms"},
        "preparation": preparation,
    }
    return AdapterNativeLearnerV2(
        MistralTrainingBinding(parts.base, 1),
        parts.bridge,
        full_update=True,
        optimizer_config=OPT,
        run_contract=contract,
    )


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_production_setup_two_complete_windows_and_serialized_replay(monkeypatch, tmp_path, dtype):
    objective = run.legacy.old.validate()[0]
    reference = build(dtype, True)
    reference_store = make_store(monkeypatch, reference)
    initial = run.state_fingerprint(reference)
    expected = [
        run.update_window(reference, reference_store, objective, "legacy", lambda *a: None)
        for _ in range(2)
    ]
    candidate = build(dtype, False)
    run.assert_exact(initial, run.state_fingerprint(candidate), "initial after preparation")
    candidate_store = make_store(monkeypatch, candidate)
    receipt = None
    for step in (1, 2):
        row = run.update_window(
            candidate, candidate_store, objective, "adapter_v2", lambda *a: None
        )
        run.assert_exact(expected[step - 1], row, f"complete 16-pair window {step}")
        if step == 1:
            receipt = candidate.save(tmp_path / "step1.pt", {"test": "production preparation"})
    state = tree_hash(candidate.payload({"test": "production preparation"}))
    fresh = build(dtype, False)
    payload = torch.load(tmp_path / "step1.pt", map_location="cpu", weights_only=True)
    restored = AdapterNativeLearnerV2.restore(
        fresh.binding,
        fresh.bridge,
        payload,
        expected_metadata={"test": "production preparation"},
        expected_run_contract=candidate.run_contract,
        expected_state_sha256=receipt["state_sha256"],
    )
    replay = run.update_window(
        restored, make_store(monkeypatch, restored), objective, "adapter_v2", lambda *a: None
    )
    run.assert_exact(expected[1], replay, "complete 16-pair replay")
    assert tree_hash(restored.payload({"test": "production preparation"})) == state
    assert len(hooks(restored.base)[0][1]) == 1
    HFTrainingReadoutAdapter(restored.base)
