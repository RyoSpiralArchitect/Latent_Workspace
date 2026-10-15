"""Synthetic objective-graph qualification; no real checkpoints or downloads."""

import copy
import json
from contextlib import contextmanager

import pytest
import test_readout_adapters as native_reference_tests
import torch
from test_readout_adapters import FAMILIES, IDS, model
from test_v15_native_learner import CONTRACT, SPAN, OwnedStore, objective, owner

from latent_workspace_ft_v10.adapted_pair_objective import adapted_pair_objective
from latent_workspace_ft_v10.adapted_workspace import AdaptedWorkspacePipeline
from latent_workspace_ft_v10.hf_readout_adapter import HFNativeReadoutAdapter
from latent_workspace_ft_v10.hf_training_readout import HFTrainingReadoutAdapter


@pytest.fixture(autouse=True)
def threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(previous)


def adapted_objective(learner, query):
    store = OwnedStore(learner)
    return adapted_pair_objective(
        AdaptedWorkspacePipeline(learner.bridge, HFTrainingReadoutAdapter(learner.base)),
        lambda side: store.write(learner.bridge, 0, side),
        prefix_ids=SPAN.prefix_ids,
        span=SPAN,
        candidate_ids=(6, 7),
        labels=[store.records[0]["answers"][s][query] for s in (0, 1)],
        contract=CONTRACT,
    )[0]


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("query", [0, 2])
def test_complete_pair_loss_and_every_gradient_matches_historical(dtype, full, query):
    legacy, migrated = owner(dtype, full), owner(dtype, full)
    left, right = objective(legacy, query), adapted_objective(migrated, query)
    assert torch.equal(left, right)
    left.backward()
    right.backward()
    for (name, a), (_, b) in zip(legacy.named, migrated.named, strict=True):
        assert torch.equal(a.grad, b.grad), name


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_prepared_zero_and_nonzero_keep_native_outer_transform(family, dtype):
    base = model(family, dtype)
    reference = copy.deepcopy(base)
    adapter = HFTrainingReadoutAdapter(base)
    ref = HFNativeReadoutAdapter(reference)
    with adapter.objective() as graphs:
        graphs.prepare(IDS)
        for value in (0.0, 0.1):

            def residual(h):
                return torch.full_like(h[:, -1:], value).float()

            actual, expected = adapter.read(IDS, residual), ref.read(IDS, residual)
            assert torch.equal(actual.readout.logits, expected.readout.logits)
            assert torch.equal(actual.head_logits, expected.head_logits)
    assert not adapter._prepared and adapter._scope_thread is None
    assert not adapter.head._forward_hooks and not adapter.head._forward_pre_hooks


def test_scopes_reject_missing_preparation_recursion_concurrency_and_updates():
    base = model("mistral")
    adapter, other = HFTrainingReadoutAdapter(base), HFNativeReadoutAdapter(base)

    def zero(h):
        return torch.zeros_like(h[:, -1:]).float()

    with pytest.raises(RuntimeError, match="exclusive objective"):
        adapter.prepare(IDS)
    with adapter.objective() as graphs:
        with pytest.raises(ValueError, match="explicitly prepare"):
            adapter.read(IDS, zero)
        graphs.prepare(IDS)
        with pytest.raises(RuntimeError, match="Concurrent"):
            other.read(IDS, zero)
        with pytest.raises(RuntimeError, match="nested"):
            with adapter.objective():
                pass
        with pytest.raises(RuntimeError, match="recursive"):
            adapter.read(IDS, lambda h: adapter.read(IDS, zero))
        with torch.no_grad():
            adapter.head.weight.add_(0.01)
        with pytest.raises(ValueError, match="version"):
            adapter.read(IDS, zero)
    assert not adapter._prepared and not adapter.head._forward_hooks


def test_mode_and_buffer_changes_are_not_a_paired_intervention():
    adapter = HFTrainingReadoutAdapter(model("mistral"))
    adapter.base.train()
    with pytest.raises(ValueError, match="structure"):
        adapter.read(IDS, lambda h: h)
    adapter = HFTrainingReadoutAdapter(model("mistral"))
    with torch.no_grad():
        next(adapter.base.buffers()).add_(0.1)
    with pytest.raises(ValueError, match="structure"):
        adapter.read(IDS, lambda h: h)


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("checkpointing", [False, True])
def test_new_backend_all_gradients_against_independent_native_hook_reference(
    monkeypatch,
    family,
    dtype,
    checkpointing,
):
    monkeypatch.setattr(native_reference_tests, "HFNativeReadoutAdapter", HFTrainingReadoutAdapter)
    native_reference_tests.test_nonzero_native_reference_and_backprop(family, dtype, checkpointing)


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("full", [False, True])
def test_independent_forward_negative_control_localizes_graph_rounding(
    dtype, full, record_property
):
    class IndependentForwardControl:
        """Intentional negative control: no prepared graph, not a production backend."""

        def __init__(self, base):
            self.backend = HFNativeReadoutAdapter(base)
            self.vocabulary = self.backend.vocabulary

        @contextmanager
        def objective(self):
            yield self

        def prepare(self, prefix):
            pass

        def read(self, prefix, residual):
            return self.backend.read(prefix, residual)

    legacy, independent = owner(dtype, full), owner(dtype, full)
    store = OwnedStore(independent)
    left = objective(legacy, 0)
    right = adapted_pair_objective(
        AdaptedWorkspacePipeline(independent.bridge, IndependentForwardControl(independent.base)),
        lambda side: store.write(independent.bridge, 0, side),
        prefix_ids=SPAN.prefix_ids,
        span=SPAN,
        candidate_ids=(6, 7),
        labels=(0, 1),
        contract=CONTRACT,
    )[0]
    assert torch.equal(left, right)
    left.backward()
    right.backward()
    rows = []
    for (name, a), (_, b) in zip(legacy.named, independent.named, strict=True):
        if not torch.equal(a.grad, b.grad):
            rows.append(
                {
                    "name": name,
                    "different_elements": int((a.grad != b.grad).sum()),
                    "max_abs": float((a.grad.float() - b.grad.float()).abs().max()),
                }
            )
    assert bool(rows) == full
    if next(legacy.base.parameters()).device.type == "cpu":
        assert len(rows) == (20 if full else 0)
    assert all(r["name"].startswith("base.") for r in rows)
    record_property(
        "negative_control",
        json.dumps(
            {
                "dtype": str(dtype),
                "device": str(next(legacy.base.parameters()).device),
                "full_update": full,
                "loss_exact": True,
                "eligible_tensors": len(legacy.named),
                "gradient_differences": rows,
                "scope": "one_synthetic_affected_pair_no_optimizer_steps",
            },
            sort_keys=True,
        ),
    )


def test_mixed_submodule_dropout_and_global_hooks_are_rejected():
    base = model("gpt2").eval()
    base.transformer.drop.p = 0.5
    base.transformer.drop.train()
    with pytest.raises(ValueError, match="dropout"):
        HFTrainingReadoutAdapter(base)
    from torch.nn.modules.module import register_module_forward_hook

    handle = register_module_forward_hook(lambda *args: None)
    try:
        with pytest.raises(ValueError, match="Global"):
            HFTrainingReadoutAdapter(model("mistral"))
    finally:
        handle.remove()


def test_no_grad_preparation_cannot_be_relabelled_live_and_scope_cleans_on_error():
    adapter = HFTrainingReadoutAdapter(model("mistral"))
    with pytest.raises(ValueError, match="gradient mode"):
        with adapter.objective() as graphs:
            with torch.no_grad():
                graphs.prepare(IDS)
            adapter.read(IDS, lambda h: torch.zeros_like(h[:, -1:]).float())
    assert not adapter.objective_active and not adapter._prepared
    assert not adapter.head._forward_hooks
    adapter.read(IDS, lambda h: torch.zeros_like(h[:, -1:]).float())
