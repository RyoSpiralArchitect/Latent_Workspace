from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import torch
from transformers import MistralConfig, MistralForCausalLM

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import probe_v15_reader_modulation as probe  # noqa: E402
import summarize_v15_reader_modulation as summary  # noqa: E402

from latent_workspace_ft_v10.precision_bridge import PrecisionAwareWorkspaceBridge  # noqa: E402
from latent_workspace_ft_v10.query_modulated_bridge import (  # noqa: E402
    QueryModulatedWorkspaceBridge,
)
from latent_workspace_ft_v10.reader_query import QuestionSpan  # noqa: E402
from latent_workspace_ft_v10.v15_full_update import (  # noqa: E402
    MistralLiveFeatures,
    TrainableNativeWorkspaceReadout,
)
from latent_workspace_ft_v10.v15_pipeline import NativeWorkspacePipeline  # noqa: E402
from latent_workspace_ft_v10.v15_readout import NativeWorkspaceReadout  # noqa: E402


@pytest.fixture(autouse=True)
def threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(previous)


def bridges(strength=0.25, initial=False):
    torch.manual_seed(47)
    old = PrecisionAwareWorkspaceBridge(16, workspace_dim=8, heads=2, slots=3, max_delta_norm=1)
    if not initial:
        torch.nn.init.normal_(old.up.weight, std=0.2)
    new = QueryModulatedWorkspaceBridge(
        16, workspace_dim=8, heads=2, slots=3, max_delta_norm=1, modulation_strength=strength
    )
    new.load_state_dict(old.state_dict(), strict=True)
    return old.eval(), new.eval()


def inputs(dtype=torch.float32):
    q = torch.randn(2, 1, 16).to(dtype).requires_grad_()
    memory = torch.randn(2, 3, 8).to(dtype).requires_grad_()
    mask = torch.tensor([[1, 0, 1], [1, 1, 0]])
    return q, memory, mask


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("initial", [False, True])
def test_strength_zero_exact_forward_and_gradients(dtype, initial):
    old, new = bridges(0, initial)
    a = inputs(dtype)
    b = tuple(v.detach().clone().requires_grad_(v.requires_grad) for v in a)
    x, y = old.read_delta(*a), new.read_delta(*b)
    assert torch.equal(x, y)
    x.sum().backward()
    y.sum().backward()
    assert torch.equal(a[0].grad, b[0].grad)
    assert torch.equal(a[1].grad, b[1].grad)
    for (name, p), (name2, p2) in zip(old.named_parameters(), new.named_parameters(), strict=True):
        assert name == name2 and torch.equal(p, p2)
        assert (p.grad is None) == (p2.grad is None)
        if p.grad is not None:
            assert torch.equal(p.grad, p2.grad)


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_exact_zero_memory_cap_masks_and_outer_autocast(dtype):
    _, new = bridges()
    q, memory, mask = inputs(dtype)
    with torch.autocast("cpu", dtype=torch.bfloat16):
        delta = new.read_delta(q, memory, mask)
        zero = new.read_delta(q, torch.zeros_like(memory), mask)
    assert delta.dtype == torch.float32 and float(delta.detach().norm(dim=-1).max()) < 1
    assert zero.count_nonzero() == 0
    assert torch.autograd.grad(zero.sum(), q)[0].count_nonzero() == 0
    changed = memory.detach().clone()
    changed[~mask.bool()] = 1e5
    assert torch.equal(delta, new.read_delta(q, changed, mask))
    assert torch.allclose(delta, new.read_delta(q, memory.flip(1), mask.flip(1)), atol=1e-6)
    assert torch.equal(delta, new.read_delta(q[:, 0], memory, mask))


def test_formula_has_only_one_parameter_free_change():
    old, new = bridges()
    q, memory, mask = inputs()
    pq, mem = new.query_norm(new.query_projection(q)), new.memory_norm(memory)
    read, _ = new.attention(pq, mem, mem, key_padding_mask=~mask.bool(), need_weights=False)
    raw = new.up(read * (1 + 0.25 * pq.tanh()))
    expected = raw * (1 / torch.sqrt(1 + raw.square().sum(-1, keepdim=True)))
    assert torch.equal(new.read_delta(q, memory, mask), expected)
    assert list(new.state_dict()) == list(old.state_dict())
    assert sum(p.numel() for p in old.parameters()) == sum(p.numel() for p in new.parameters())
    assert len(list(new.parameters())) == 26
    context = torch.randn(2, 5, 16)
    cmask = torch.ones(2, 5)
    assert torch.equal(old.write_memory(context, cmask)[0], new.write_memory(context, cmask)[0])


def test_common_slot_route_and_initial_zero_caveat():
    old, new = bridges()
    q, memory, mask = inputs()
    memory = memory[:, :1].expand_as(memory).detach()
    a, b = old.read_delta(q, memory, mask), new.read_delta(q, memory, mask)
    old_grad = torch.autograd.grad(a.sum(), q)[0]
    new_grad = torch.autograd.grad(b.sum(), q)[0]
    assert old_grad.norm() < 1e-6
    assert new_grad.norm() > 1e-3
    assert not torch.equal(new.read_delta(q, memory, mask), new.read_delta(-q, memory, mask))
    # This is deliberately a content-free common carrier, not semantic evidence.
    assert not torch.equal(b, new.read_delta(q, -memory, mask))
    _, initial = bridges(initial=True)
    result = initial.read_delta(q, memory, mask)
    result.sum().backward()
    assert result.count_nonzero() == 0
    assert q.grad.count_nonzero() == 0
    assert initial.up.weight.grad.count_nonzero() > 0
    assert initial.query_projection.weight.grad.count_nonzero() == 0


@pytest.mark.parametrize("strength", [True, -0.1, 1.1, float("inf"), float("nan"), "0.25"])
def test_strength_rejects_unsafe_values(strength):
    with pytest.raises(ValueError, match="modulation_strength"):
        bridges(strength)


@pytest.mark.parametrize(
    "corrupt", ["mask", "empty_mask", "query_nan", "memory_inf", "shape", "dtype"]
)
def test_candidate_keeps_input_guards(corrupt):
    _, new = bridges()
    q, memory, mask = inputs()
    if corrupt == "mask":
        mask[0, 0] = 2
    elif corrupt == "empty_mask":
        mask[0] = 0
    elif corrupt == "query_nan":
        q = q.detach().clone()
        q[0, 0, 0] = float("nan")
    elif corrupt == "memory_inf":
        memory = memory.detach().clone()
        memory[0, 0, 0] = float("inf")
    elif corrupt == "shape":
        q = q.expand(-1, 2, -1)
    else:
        new.bfloat16()
    with pytest.raises((ValueError, TypeError)):
        new.read_delta(q, memory, mask)


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_tiny_live_full_model_zero_parity_and_nonzero_gradient_integration(dtype):
    torch.manual_seed(47)
    config = MistralConfig(
        vocab_size=43,
        hidden_size=16,
        intermediate_size=32,
        num_hidden_layers=2,
        num_attention_heads=4,
        num_key_value_heads=2,
        attention_dropout=0,
        sliding_window=None,
        use_cache=False,
    )
    config._attn_implementation = "eager"
    base = MistralForCausalLM(config).to(dtype).eval()
    _, bridge = bridges()
    native = TrainableNativeWorkspaceReadout(base.lm_head)
    ids = torch.tensor([[1, 4, 5]])
    direct = base(ids, use_cache=False).logits
    direct_grad = torch.autograd.grad(direct.float().sum(), list(base.parameters()))
    features = MistralLiveFeatures(base, 1)
    hidden = features.prefix((1, 4, 5))
    context = features.context((1, 8, 9))
    memory, mask = bridge.write_memory(context, torch.ones(1, 3))
    span = QuestionSpan("A?", 0, 2, (1, 2), (1, 4, 5), "tiny")
    pipe = NativeWorkspacePipeline(bridge, native, "final")
    zero = pipe(hidden, torch.zeros_like(memory), mask, prefix_ids=span.prefix_ids, span=span)
    assert torch.equal(zero.readout.logits, direct)
    zero_grad = torch.autograd.grad(
        zero.readout.logits.float().sum(), list(base.parameters()), retain_graph=True
    )
    assert all(torch.equal(a, b) for a, b in zip(zero_grad, direct_grad, strict=True))
    output = pipe(hidden, memory, mask, prefix_ids=span.prefix_ids, span=span)
    output.readout.cross_entropy(torch.tensor([6])).backward()
    assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in base.parameters())
    assert bridge.query_projection.weight.grad.count_nonzero() > 0
    assert bridge.writer.slot_seed.grad.count_nonzero() > 0


def test_query_cut_preserves_values_without_inventing_backbone_gradient():
    _, bridge = bridges()
    head = torch.nn.Linear(16, 43, bias=False).requires_grad_(False)
    readout = NativeWorkspaceReadout(head)
    plain, cut = (
        cls(bridge, readout, "final") for cls in (NativeWorkspacePipeline, probe.QueryCutPipeline)
    )
    hidden = torch.randn(1, 3, 16)
    span = QuestionSpan("A?", 0, 2, (1, 2), (1, 4, 5), "tiny")
    memory, mask = torch.randn(1, 3, 8), torch.ones(1, 3)
    before = plain(hidden, memory, mask, prefix_ids=span.prefix_ids, span=span)
    after = cut(hidden, memory, mask, prefix_ids=span.prefix_ids, span=span)
    assert torch.equal(before.readout.logits, after.readout.logits)
    assert after.reader_query.is_leaf and after.reader_query.requires_grad
    after.readout.cross_entropy(torch.tensor([6])).backward()
    assert after.reader_query.grad.count_nonzero() > 0
    assert hidden.grad is None and head.weight.grad is None


def test_geometry_distinguishes_norm_only_changes_and_missing_direction():
    row = probe.geometry(torch.tensor([1.0, 0.0]), torch.tensor([2.0, 0.0]))
    assert row["difference_l2"] == 1
    assert row["equal_norm_difference_l2"] == row["tangential_difference_l2"] == 0
    zero = probe.geometry(torch.zeros(2), torch.zeros(2))
    assert zero["relative_l2"] == 0 and zero["unit_direction_difference_l2"] is None


def test_plan_and_past_seals_validate_without_cuda():
    plan, *_ = probe.validate()
    assert plan["optimizer_constructed"] is False
    assert len(probe.identity()) >= 279


def test_no_hidden_mutation_or_parameter_grad_on_read():
    _, new = bridges()
    snapshot = copy.deepcopy(new.state_dict())
    q, memory, mask = inputs()
    q0, m0, mask0 = q.clone(), memory.clone(), mask.clone()
    result = new.read_delta(q, memory, mask)
    torch.autograd.grad(result.square().sum(), (q, memory, *new.parameters()), allow_unused=True)
    assert all(torch.equal(v, snapshot[k]) for k, v in new.state_dict().items())
    assert torch.equal(q, q0) and torch.equal(memory, m0) and torch.equal(mask, mask0)
    assert all(p.grad is None for p in new.parameters())


def test_complete_tiny_probe_gradient_and_evaluation_denominators():
    from dataclasses import asdict

    old, new = bridges()
    head = torch.nn.Linear(16, 43, bias=False).requires_grad_(False)
    readout = NativeWorkspaceReadout(head)
    span = QuestionSpan("A?", 0, 2, (1, 2), (1, 4, 5), "tiny")
    rendering = {"prompt_ids": list(span.prefix_ids), "candidate_ids": [6, 7], "span": asdict(span)}
    hidden, context = torch.randn(1, 4, 16), torch.randn(1, 5, 16)

    class Store:
        records = [{"answers": [[0, 1] * 4, [1, 0] + [0, 1] * 3]} for _ in range(2)]
        renderings = {(w, q): rendering for w in range(2) for q in range(8)}

        def get(self, prefix):
            return hidden[:, : len(prefix)]

        def write(self, bridge, world, key):
            value = context if key == 0 else context.flip(1) if key == 1 else -context
            return bridge.write_memory(value, torch.ones(1, 5))

    store = Store()
    plan, parent, *_ = probe.validate()
    oldpipe = NativeWorkspacePipeline(old, readout, "final")
    history = probe.old.evaluate(oldpipe, store, 8)["rows"]
    _, off = bridges(strength=0)
    legacy = probe.evaluation(oldpipe, off, store, plan, "retained_answer_step8", history)
    panel = probe.evaluation(
        NativeWorkspacePipeline(new, readout, "final"),
        None,
        store,
        plan,
        "retained_answer_step8",
        history,
    )
    assert len(legacy["rows"]) == len(panel["rows"]) == 128
    assert len(panel["reciprocal"]) == 64 and len(panel["interactions"]) == 8
    result = probe.gradients(new, readout, store, parent["training"], plan, lambda _: None)
    assert len(result["pairs"]) == 16
    routes = [r for pair in result["pairs"] for r in pair["routes"]]
    assert len(routes) == 80
    assert sum(r["role"].endswith("eos") for r in routes) == 32
    assert sum(r["l2"] > 0 for r in routes) == 48
    replay = summary.cell(panel, result, "retained_answer_step8", "query_modulated")
    assert replay["truth_rows"] == 32 and replay["affected_pairs"] == 4
    assert replay["query_routes"] == 80
    corrupted = copy.deepcopy(panel)
    corrupted["rows"].append(corrupted["rows"][0])
    with pytest.raises(ValueError, match="duplicate/missing"):
        summary.cell(corrupted, result, "retained_answer_step8", "query_modulated")
    corrupted = copy.deepcopy(result)
    corrupted["pairs"][0]["routes"][1]["l2"] = 0.01
    with pytest.raises(ValueError, match="EOS zero"):
        summary.cell(panel, corrupted, "retained_answer_step8", "query_modulated")
