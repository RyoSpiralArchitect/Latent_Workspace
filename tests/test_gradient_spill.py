import copy

import pytest
import torch
from test_native_memory import KINDS
from test_objective_audit import fixture
from torch.nn import functional as F
from torch.utils.checkpoint import checkpoint

from latent_workspace.gradient_spill import GradientSpill, tensor_pair_stats, upper_replay


@pytest.fixture(autouse=True)
def threads():
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("recompute", [False, True])
def test_one_backward_matches_whole_gradient_bitwise_and_preserves_parameters(
    kind, dtype, recompute
):
    graph, batch, _ = fixture(kind, dtype)
    expected = copy.deepcopy(graph)
    before = {n: p.detach().clone() for n, p in graph.model.named_parameters()}
    bank = GradientSpill(graph.model.named_parameters())
    sums = {}
    for _ in range(2):
        reference = expected(**batch)
        reference.loss.backward()
        for n, p in expected.model.named_parameters():
            if n in sums:
                sums[n].add_(p.grad.float().cpu())
            else:
                sums[n] = p.grad.float().cpu().clone()
        expected.zero_grad(set_to_none=True)
        out = checkpoint(graph, use_reentrant=False, **batch) if recompute else graph(**batch)
        assert torch.equal(reference.logits, out.logits)
        with bank.capture():
            out.loss.backward()
    assert bank.backward_count == 2
    for n, p in graph.model.named_parameters():
        assert torch.equal(bank.buffers[n], sums[n]), n
        assert torch.equal(p, before[n]) and p.grad is None
        assert bank.events[n] == 2
        assert not p._post_accumulate_grad_hooks


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_streaming_w_q_r_reconstructs_full_including_tied_embeddings(kind, dtype):
    graph, batch, _ = fixture(kind, dtype)
    full = GradientSpill(graph.model.named_parameters())
    output = graph(**batch, capture_cut_trace=True)
    trace = output.cut_trace
    dm, dq = torch.autograd.grad(output.loss, (trace.memory, trace.query), retain_graph=True)
    direct_logits = upper_replay(graph, trace)
    assert torch.equal(direct_logits, output.logits)
    direct = F.cross_entropy(
        direct_logits[:, :-1].float().reshape(-1, 43), batch["labels"][:, 1:].reshape(-1)
    )
    with full.capture():
        output.loss.backward(retain_graph=True)
    summed = GradientSpill(graph.model.named_parameters())
    with summed.capture(require_all=False):
        torch.autograd.backward(trace.memory, dm, retain_graph=True)
    with summed.capture(require_all=False):
        torch.autograd.backward(trace.query, dq)
    with summed.capture(require_all=False):
        direct.backward()
    atol, rtol = (1e-4, 0.03) if dtype == torch.bfloat16 else (2e-6, 2e-4)
    for n, expected in full.buffers.items():
        result = tensor_pair_stats(expected, summed.buffers.get(n), chunk_elements=97)
        assert result["max_abs_residual"] <= atol + rtol * result["left_max_abs"], n


def test_unused_leaves_missing_full_and_failure_cleanup():
    p = torch.nn.Parameter(torch.ones(2))
    q = torch.nn.Parameter(torch.ones(2))
    bank = GradientSpill([("p", p), ("q", q)])
    with pytest.raises(ValueError, match="Incomplete"):
        with bank.capture():
            p.sum().backward()
    assert p.grad is q.grad is None
    assert not p._post_accumulate_grad_hooks and not q._post_accumulate_grad_hooks
    with pytest.raises(ValueError, match="Poisoned"):
        bank.receipt()
    p.sum().backward()  # No leaked hooks consuming gradients after an exception.
    assert torch.equal(p.grad, torch.ones_like(p))


def test_multiple_backwards_and_nonfinite_fail_closed():
    p = torch.nn.Parameter(torch.ones(2))
    bank = GradientSpill([("p", p)])
    with pytest.raises(ValueError, match="Repeated"):
        with bank.capture():
            p.sum().backward()
            p.sum().backward()
    bank = GradientSpill([("p", p)])
    with pytest.raises(ValueError, match="Finite"):
        with bank.capture():
            (p * float("nan")).sum().backward()
    assert p.grad is None and not p._post_accumulate_grad_hooks


def test_duplicate_dirty_changed_and_empty_capture_rejected():
    p = torch.nn.Parameter(torch.ones(2))
    with pytest.raises(ValueError, match="physical"):
        GradientSpill([("p", p), ("q", p)])
    bank = GradientSpill([("p", p)])
    with pytest.raises(ValueError, match="nonempty backward"):
        with bank.capture():
            pass
    bank = GradientSpill([("p", p)])
    with torch.no_grad():
        p.add_(1)
    with pytest.raises(ValueError, match="version"):
        bank.receipt()
    p.grad = torch.zeros_like(p)
    with pytest.raises(ValueError, match="Clean"):
        GradientSpill([("p", p)])


def test_chunked_stats_and_explicit_zero_path():
    a, b = torch.randn(71), torch.randn(71)
    value = tensor_pair_stats(a, b, chunk_elements=7)
    assert value["dot"] == pytest.approx(float(a.double().dot(b.double())))
    assert value["residual_sq"] == pytest.approx(float((a.double() - b.double()).square().sum()))
    zero = tensor_pair_stats(a, None)
    assert zero["cosine"] is None and zero["right_nonzero"] == 0
