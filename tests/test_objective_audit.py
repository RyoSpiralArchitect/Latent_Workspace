import copy
import os

import pytest
import torch
from test_native_memory import KINDS, setup

from latent_workspace import objective_audit as audit


@pytest.fixture(autouse=True)
def threads():
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


def fixture(kind="mistral", dtype=torch.float32):
    graph, batch = setup(kind)
    device = os.environ.get("LTWS_TEST_DEVICE", "cpu")
    graph = graph.to(device=device, dtype=dtype).eval()
    batch = {k: v.to(device) for k, v in batch.items()}
    parts = torch.full_like(batch["labels"], -1)
    parts[0, 2:] = torch.tensor([0, 1, 2], device=device)
    parts[1, 2] = 3
    return graph, batch, parts


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("memory", [True, False])
def test_trace_is_bitwise_noop_logits_loss_gradients_and_rng(kind, memory):
    graph, batch, _ = fixture(kind)
    graph.train()  # Include GPT-2 dropout RNG order, not only deterministic eval.
    if not memory:
        batch.pop("memory_ids")
        batch.pop("memory_mask")
    other = copy.deepcopy(graph)
    state = torch.get_rng_state()
    cuda = torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None
    expected = graph(**batch)
    expected.loss.backward()
    final = torch.get_rng_state()
    final_cuda = torch.cuda.get_rng_state_all() if cuda is not None else None
    torch.set_rng_state(state)
    if cuda is not None:
        torch.cuda.set_rng_state_all(cuda)
    actual = other(**batch, capture_cut_trace=True)
    actual.loss.backward()
    assert torch.equal(actual.logits, expected.logits)
    assert torch.equal(actual.loss, expected.loss)
    assert torch.equal(final, torch.get_rng_state())
    if cuda is not None:
        assert all(torch.equal(a, b) for a, b in zip(final_cuda, torch.cuda.get_rng_state_all()))
    assert (actual.cut_trace is not None) == memory
    for p, q in zip(graph.parameters(), other.parameters(), strict=True):
        assert torch.equal(p.grad, q.grad)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_same_denominator_and_state_gradient_decomposition(kind, dtype):
    graph, batch, parts = fixture(kind, dtype)
    output = graph(**batch, capture_cut_trace=True)
    loss = audit.partitioned_ce(output.logits, batch["labels"], parts)
    assert torch.equal(loss["total"], output.loss)
    assert loss["counts"] == dict(identity=1, copy=1, format=1, mixed=1)
    torch.testing.assert_close(sum(loss["components"].values()), loss["total"])
    result = audit.state_gradient_audit(output, batch["labels"], parts)
    assert result["gradients"]["total"]["memory"]["l2"] > 0
    # Native BF16 rounds individual paths independently; do not demand bitwise sums.
    tolerance = 0.02 if dtype == torch.bfloat16 else 2e-5
    for block in ("memory", "question", "continuation"):
        bound = 2e-7 + tolerance * result["gradients"]["total"][block]["max_abs"]
        assert result["component_sum_residual"][block]["max_abs"] <= bound
    assert all(p.grad is None for p in graph.parameters())


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_shared_lower_and_tied_head_are_attributed_not_assumed_independent(kind, dtype):
    graph, batch, _ = fixture(kind, dtype)
    output = graph(**batch, capture_cut_trace=True)
    records = list(audit.parameter_path_audit(graph, output, batch["labels"]))
    assert len(records) == len(list(graph.model.parameters()))
    atol, rtol = (1e-4, 0.03) if dtype == torch.bfloat16 else (2e-6, 2e-4)
    assert audit.validate_path_residuals(records, atol=atol, rtol=rtol)
    assert any(r["W"]["l2"] > 0 and r["Q"]["l2"] > 0 for r in records)
    assert any(r["R"]["l2"] > 0 for r in records)
    if kind == "gpt2":
        assert any(all(r[p]["l2"] > 0 for p in ("W", "Q", "R")) for r in records)
    assert all(p.grad is None for p in graph.parameters())


def test_full_window_denominator_not_sum_of_group_means():
    graph, batch, parts = fixture()
    output = graph(**batch)
    value = audit.partitioned_ce(output.logits, batch["labels"], parts, denominator=10)
    assert torch.equal(value["total"], output.loss_sum / 10)
    with pytest.raises(ValueError, match="denominator"):
        audit.partitioned_ce(output.logits, batch["labels"], parts, denominator=3)


@pytest.mark.parametrize("mutation", ["missing", "prompt", "out_of_range", "label_zero"])
def test_invalid_partition_fails_closed(mutation):
    graph, batch, parts = fixture()
    output = graph(**batch)
    if mutation == "missing":
        parts[0, 2] = -1
    elif mutation == "prompt":
        parts[0, 0] = 0
    elif mutation == "out_of_range":
        parts[0, 2] = 4
    else:
        batch["labels"][0, 0] = 2
        parts[0, 0] = 0
    with pytest.raises(ValueError):
        audit.partitioned_ce(output.logits, batch["labels"], parts)


class CharacterTokenizer:
    eos_token_id = 2

    def __call__(self, text, **_):
        return dict(
            input_ids=[ord(c) for c in text], offset_mapping=[(i, i + 1) for i in range(len(text))]
        )


def test_oracle_identity_is_not_fixed_first_two_positions():
    tok = CharacterTokenizer()
    a = audit.oracle_partition(tok, "Nabcd", ["Nabcd", "Nzxyz"])
    b = audit.oracle_partition(tok, "Nabcd", ["Nabcd", "Nabce"])
    assert a["parts"] == [
        "format",
        "identity",
        "identity",
        "copy",
        "copy",
        "copy",
        "format",
        "format",
    ]
    assert b["parts"].count("copy") == 0
    assert audit.oracle_partition(tok, "Not specified", ["Nx"])["parts"].count("copy") == 0
    assert audit.oracle_partition(tok, "123", ["124"])["parts"].count("copy") == 0


def test_boundary_fused_tokens_are_mixed_not_semantic_or_format():
    class FusedTokenizer:
        eos_token_id = 2

        def __call__(self, text, **_):
            return dict(input_ids=[3], offset_mapping=[(0, len(text))])

    result = audit.oracle_partition(FusedTokenizer(), "Nabc", ["Nxyz"])
    assert result["parts"] == ["mixed", "format"]


def test_full_vocab_kl_zero_anchor_and_masked_tokens():
    student = torch.randn(1, 4, 43, requires_grad=True)
    teacher = student.detach().log_softmax(-1)
    mask = torch.tensor([[False, True, True, False]])
    loss = audit.full_vocab_kl_sum(student, teacher, mask)
    assert loss == 0
    loss.backward()
    assert student.grad.abs().max() < 1e-7
    changed = student.detach().clone().requires_grad_(True)
    changed.data[:, 1, 7] += 1
    assert audit.full_vocab_kl_sum(changed, teacher, mask) > 0


@pytest.mark.parametrize("invalid", ["topk", "unnormalized", "live", "bf16", "nan"])
def test_kl_rejects_approximate_or_invalid_teacher(invalid):
    student = torch.randn(1, 2, 43, requires_grad=True)
    target = student.detach().log_softmax(-1)
    if invalid == "topk":
        target = target[..., :2]
    elif invalid == "unnormalized":
        target = target + 1
    elif invalid == "live":
        target.requires_grad_()
    elif invalid == "bf16":
        target = target.bfloat16()
    else:
        target[0, 0, 0] = float("nan")
    with pytest.raises(ValueError):
        audit.full_vocab_kl_sum(student, target, torch.ones(1, 2, dtype=torch.bool))


def test_preservation_conflict_streaming_matches_joint_autograd():
    graph, batch, parts = fixture()
    memory = graph(**batch)
    plain = graph(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"])
    target = (plain.logits.detach().float() + 0.2 * torch.randn_like(plain.logits)).log_softmax(-1)
    anchor = (
        audit.full_vocab_kl_sum(
            plain.logits[:, :-1], target[:, :-1], batch["labels"][:, 1:] != -100
        )
        / memory.supervised_tokens
    )
    ce = audit.partitioned_ce(memory.logits, batch["labels"], parts)["total"]
    named = list(graph.model.named_parameters())
    left = torch.autograd.grad(ce, [p for _, p in named], retain_graph=True)
    right = torch.autograd.grad(anchor, [p for _, p in named], retain_graph=True)
    expected = sum(
        float(a.double().flatten().dot(b.double().flatten()))
        for a, b in zip(left, right, strict=True)
    )
    records = list(audit.gradient_conflicts(ce, anchor, named))
    assert sum(r["dot"] for r in records) == pytest.approx(expected, rel=1e-10, abs=1e-12)
    assert all(r["finite"] for r in records)
    assert all(p.grad is None for p in graph.parameters())


def test_empty_memory_trace_not_fabricated_and_nondeterministic_audit_rejected():
    graph, batch, parts = fixture()
    empty = graph(input_ids=batch["input_ids"], labels=batch["labels"], capture_cut_trace=True)
    assert empty.cut_trace is None
    with pytest.raises(ValueError, match="Live nonempty"):
        audit.state_gradient_audit(empty, batch["labels"], parts)
    graph.train()
    output = graph(**batch, capture_cut_trace=True)
    with pytest.raises(ValueError, match="eval-mode"):
        list(audit.parameter_path_audit(graph, output, batch["labels"]))
    with pytest.raises(ValueError, match="boolean"):
        graph(**batch, capture_cut_trace="yes")
