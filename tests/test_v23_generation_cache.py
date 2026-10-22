"""No-7B controls for cache-only repair, including exact tiny generation parity."""

import io
import json
import os
from types import SimpleNamespace

import pytest
import run_v23_recovered_mmlu_pro02 as runner
import torch
import v23_generation_cache as cache
from test_latent_workspace_stack import host_model

from latent_workspace import native_evaluation as ev
from latent_workspace.native_memory import NativeMemoryCausalLM
from latent_workspace.optimizer_state import tree_hash


class CudaMock:
    def __init__(self, events, broken=False):
        self.events, self.broken, self.emptied = events, broken, False

    def synchronize(self, device):
        self.events.append("synchronize")

    def memory_allocated(self, device):
        return 9 if self.broken and self.emptied else 10

    def memory_reserved(self, device):
        return 10 if self.emptied else 20

    def empty_cache(self):
        self.events.append("empty_cache")
        self.emptied = True


def test_reclaim_then_original_guard_and_audited_live_identity():
    events, journal = [], io.StringIO()
    guard = cache.GenerationBoundaryGuard(
        lambda phase: events.append(phase), torch.device("cuda"), journal, cuda=CudaMock(events)
    )
    guard("generation:0")
    assert events == ["synchronize", "empty_cache", "generation:0"]
    assert json.loads(journal.getvalue()) == dict(
        phase="generation:0",
        allocated_before=10,
        allocated_after=10,
        reserved_before=20,
        reserved_after=10,
    )


@pytest.mark.parametrize("device,phase", [("cpu", "generation:0"), ("cuda", "direct:0")])
def test_no_cuda_touch_for_cpu_or_non_generation(device, phase):
    events, journal = [], io.StringIO()
    guard = cache.GenerationBoundaryGuard(
        lambda p: events.append(p), torch.device(device), journal, cuda=CudaMock(events)
    )
    guard(phase)
    assert events == [phase] and journal.getvalue() == ""


def test_changed_live_allocation_fails_closed_before_original_guard():
    events = []
    guard = cache.GenerationBoundaryGuard(
        lambda p: events.append(p),
        torch.device("cuda"),
        io.StringIO(),
        cuda=CudaMock(events, broken=True),
    )
    with pytest.raises(ValueError, match="live allocation"):
        guard("generation:4")
    assert events == ["synchronize", "empty_cache"]


def test_resource_abort_is_not_caught_or_retried():
    events = []

    def reject(phase):
        events.append(phase)
        raise RuntimeError("mock resource abort")

    guard = cache.GenerationBoundaryGuard(
        reject, torch.device("cuda"), io.StringIO(), cuda=CudaMock(events)
    )
    with pytest.raises(RuntimeError, match="resource abort"):
        guard("generation:1")
    assert events == ["synchronize", "empty_cache", "generation:1"]


@pytest.mark.parametrize("temperature", [0.0, 0.7])
@pytest.mark.parametrize("memory", [[], [4, 5]])
def test_tiny_generation_exact_and_no_weight_rng_or_gradient_mutation(temperature, memory):
    device = os.environ.get("LTWS_TEST_DEVICE", "cpu")
    graph = NativeMemoryCausalLM(host_model("mistral"), cut=1).to(device, torch.bfloat16).eval()
    state = tree_hash(graph.state_dict())
    rng = torch.get_rng_state().clone()
    cuda_rng = torch.cuda.get_rng_state().clone() if device == "cuda" else None
    events, journal = [], io.StringIO()
    policy = dict(seed=11, cap=4, eos=42, temperature=temperature, top_p=0.9)
    expected = ev.generate(graph, [1, 8, 9], memory, guard=lambda _: None, **policy)
    actual = cache.generate(
        graph, [1, 8, 9], memory, journal=journal, guard=events.append, **policy
    )
    assert actual == expected and len(events) == actual["generated_tokens"]
    assert tree_hash(graph.state_dict()) == state and torch.equal(torch.get_rng_state(), rng)
    assert all(p.grad is None for p in graph.parameters())
    if device == "cuda":
        assert torch.equal(torch.cuda.get_rng_state(), cuda_rng)
        assert len(journal.getvalue().splitlines()) == len(events)
    else:
        assert journal.getvalue() == ""


def test_new_runner_passes_same_policy_and_only_adds_boundary_callback(tmp_path, monkeypatch):
    plan = runner.ex.read(runner.ROOT / runner.PLAN)
    runner.validate(plan)
    monkeypatch.setattr(runner.bank, "verify", lambda: ({}, {"mock": True}))

    def original(core, args, policy, seal, *, predecessor_fn, generation_fn):
        assert policy == runner.previous.reference(plan)
        assert predecessor_fn(policy) == {"mock": True}
        assert callable(generation_fn)
        return {"no_model_calls": True}

    monkeypatch.setattr(runner.original, "run", original)
    assert runner.run(None, SimpleNamespace(output=tmp_path), plan, {}) == {"no_model_calls": True}


def test_changed_resource_floor_rejected():
    plan = runner.ex.read(runner.ROOT / runner.PLAN)
    plan["resources"]["abort_free_gib"] = 0.1
    with pytest.raises(ValueError, match="Same finite"):
        runner.validate(plan)
