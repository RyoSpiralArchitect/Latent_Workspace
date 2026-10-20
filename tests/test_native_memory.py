"""Full-vocabulary graph qualification, not a scientific or 7B training result."""

import copy
import os
import subprocess
import sys
from pathlib import Path

import pytest
import torch
from test_latent_workspace_stack import host_model
from torch.nn import functional as F

from latent_workspace import composition
from latent_workspace.native_memory import NativeMemoryCausalLM

KINDS = ("mistral", "olmo2", "gpt2", "scratch")


@pytest.fixture(autouse=True)
def threads():
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


def setup(kind="mistral"):
    model = host_model(kind).requires_grad_(True)
    graph = NativeMemoryCausalLM(model, cut=1)
    query = torch.tensor([[11, 12, 13, 14, 15], [16, 17, 18, 0, 0]])
    mask = (query != 0).long()
    memory = torch.tensor([[2, 3, 4], [5, 6, 0]])
    memory_mask = (memory != 0).long()
    labels = query.clone()
    labels[:, :2] = -100
    labels[mask == 0] = -100
    return graph, dict(
        input_ids=query,
        attention_mask=mask,
        memory_ids=memory,
        memory_mask=memory_mask,
        labels=labels,
    )


@pytest.mark.parametrize("kind", KINDS)
def test_full_parameter_identity_and_no_silent_policy_changes(kind):
    model = host_model(kind)
    flags = [(m, m.training) for m in model.modules()]
    graph = NativeMemoryCausalLM(model, cut=1)
    assert all(m.training == flag for m, flag in flags)
    with pytest.raises(ValueError, match="frozen"):
        graph.require_full_update()
    model.requires_grad_(True)
    assert graph.require_full_update() == sum(p.numel() for p in model.parameters())
    assert list(graph.parameters()) == list(model.parameters())
    assert len({id(p) for p in graph.parameters()}) == len(list(model.parameters()))
    assert graph.contract()["route"] == "native_full_vocabulary"


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("mode", ["none", "empty", "padding"])
def test_no_memory_is_bitwise_native_logits_loss_and_gradient(kind, mode):
    graph, batch = setup(kind)
    reference = copy.deepcopy(graph.model)
    if mode == "none":
        batch.pop("memory_ids")
        batch.pop("memory_mask")
    elif mode == "empty":
        batch["memory_ids"] = torch.empty(2, 0, dtype=torch.long)
        batch["memory_mask"] = torch.empty(2, 0, dtype=torch.long)
    else:
        batch["memory_mask"].zero_()
    actual = graph(**batch)
    expected = reference(
        batch["input_ids"], attention_mask=batch["attention_mask"], use_cache=False
    ).logits
    loss = F.cross_entropy(expected[:, :-1].reshape(-1, 43), batch["labels"][:, 1:].reshape(-1))
    assert torch.equal(actual.logits, expected)
    assert torch.equal(actual.loss, loss)
    actual.loss.backward()
    loss.backward()
    for left, right in zip(graph.model.parameters(), reference.parameters(), strict=True):
        assert torch.equal(left.grad, right.grad)


@pytest.mark.parametrize("kind", KINDS)
def test_matches_beta_host_path_and_reaches_both_encodings_and_all_layers(kind):
    graph, batch = setup(kind)
    encodings = []
    original = graph.host.to_cut

    def capture(*args):
        value = original(*args)
        value.retain_grad()
        encodings.append(value)
        return value

    graph.host.to_cut = capture
    output = graph(**batch)
    assert output.logits.shape == (2, 5, 43)  # Full vocabulary, not two candidates.
    assert output.supervised_tokens == 4
    with torch.no_grad():
        query = original(batch["input_ids"], batch["attention_mask"], 1)
        memory = original(batch["memory_ids"], batch["memory_mask"], 1)
        _, beta_logits, _ = composition.CutPrefixRoute(graph.host, 1)(
            query, batch["attention_mask"], memory, batch["memory_mask"]
        )
        for row, length in enumerate(batch["attention_mask"].sum(1)):
            start = int(batch["memory_mask"][row].sum())
            torch.testing.assert_close(
                output.logits[row, :length], beta_logits[row, start : start + length]
            )
    output.loss.backward()
    for encoded in encodings:
        assert encoded.grad is not None
        assert torch.isfinite(encoded.grad).all() and encoded.grad.abs().sum() > 0
    for name, param in graph.model.named_parameters():
        assert param.grad is not None, name
        assert torch.isfinite(param.grad).all(), name
    # Both prefixes influence shared lower layers, and the native head trains.
    assert graph.model.get_parameter("lm_head.weight").grad.abs().sum() > 0


@pytest.mark.parametrize("kind", KINDS)
def test_mixed_empty_memory_and_padding_match_individual_rows(kind):
    graph, batch = setup(kind)
    batch["memory_mask"][1].zero_()
    together = graph(**batch)
    for row in range(2):
        q = int(batch["attention_mask"][row].sum())
        m = int(batch["memory_mask"][row].sum())
        single = graph(
            batch["input_ids"][row : row + 1, :q],
            memory_ids=batch["memory_ids"][row : row + 1, :m],
        )
        torch.testing.assert_close(together.logits[row, :q], single.logits[0], rtol=1e-5, atol=1e-6)
    together.loss.backward()
    assert all(torch.isfinite(p.grad).all() for p in graph.parameters())


@pytest.mark.parametrize("kind", KINDS)
def test_future_answer_tokens_do_not_change_earlier_logits(kind):
    graph, batch = setup(kind)
    original = graph(**batch).logits
    batch["input_ids"][0, -1] = 39
    changed = graph(**batch).logits
    assert torch.equal(original[0, :-1], changed[0, :-1])


@pytest.mark.parametrize("kind", ["mistral", "olmo2"])
def test_rotary_cut_zero_matches_inline_control(kind):
    graph, batch = setup(kind)
    graph = NativeMemoryCausalLM(graph.model, cut=0)
    actual = graph(**batch)
    for row in range(2):
        q = int(batch["attention_mask"][row].sum())
        m = int(batch["memory_mask"][row].sum())
        ids = torch.cat([batch["memory_ids"][row, :m], batch["input_ids"][row, :q]])[None]
        expected = graph.model(ids, use_cache=False).logits[0, m:]
        torch.testing.assert_close(actual.logits[row, :q], expected, rtol=1e-5, atol=1e-6)


@pytest.mark.parametrize("kind", KINDS)
def test_bfloat16_full_graph_has_finite_loss_and_gradients(kind):
    graph, batch = setup(kind)
    graph.to(torch.bfloat16)
    output = graph(**batch)
    assert output.logits.dtype == torch.bfloat16 and output.loss.dtype == torch.float32
    output.loss.backward()
    assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in graph.parameters())


def test_mistral_fourth_layer_cut_has_live_writer_and_reader_gradients():
    from transformers import MistralConfig, MistralForCausalLM

    config = MistralConfig(
        vocab_size=43,
        hidden_size=16,
        intermediate_size=32,
        num_hidden_layers=6,
        num_attention_heads=4,
        num_key_value_heads=2,
        max_position_embeddings=64,
        sliding_window=None,
        use_cache=False,
    )
    config._attn_implementation = "eager"
    model = MistralForCausalLM(config).eval()
    graph = NativeMemoryCausalLM(model, cut=4)
    _, batch = setup()
    graph(**batch).loss.backward()
    for layer in model.model.layers:
        assert sum(p.grad.float().abs().sum() for p in layer.parameters()) > 0
    assert model.model.embed_tokens.weight.grad.abs().sum() > 0
    assert model.lm_head.weight.grad.abs().sum() > 0


@pytest.mark.parametrize("kind", KINDS)
def test_memory_reencoded_after_update_and_standard_checkpoint_roundtrip(kind, tmp_path):
    graph, batch = setup(kind)
    optimizer = torch.optim.AdamW(graph.parameters(), lr=0.01, foreach=False)

    def step(net, opt):
        opt.zero_grad(set_to_none=True)
        loss = net(**batch).loss
        loss.backward()
        opt.step()
        opt.zero_grad(set_to_none=True)
        return loss.detach()

    before = graph.host.to_cut(batch["memory_ids"], batch["memory_mask"], 1).detach().clone()
    step(graph, optimizer)
    after = graph.host.to_cut(batch["memory_ids"], batch["memory_mask"], 1).detach().clone()
    assert not torch.equal(before, after)
    path = tmp_path / "tiny.pt"
    torch.save(dict(model=graph.state_dict(), optimizer=optimizer.state_dict()), path)
    expected = step(graph, optimizer)
    restored, _ = setup(kind)
    restored_opt = torch.optim.AdamW(restored.parameters(), lr=0.01, foreach=False)
    payload = torch.load(path, weights_only=True)
    restored.load_state_dict(payload["model"])
    restored_opt.load_state_dict(payload["optimizer"])
    assert torch.equal(expected, step(restored, restored_opt))
    assert all(
        torch.equal(a, b) for a, b in zip(graph.parameters(), restored.parameters(), strict=True)
    )


def test_token_weighted_loss_not_mean_of_unequal_microbatch_means():
    graph, batch = setup()
    out = graph(**batch)
    parts = [
        graph(**{key: value[row : row + 1] for key, value in batch.items()}) for row in range(2)
    ]
    expected = sum(p.loss_sum for p in parts) / sum(p.supervised_tokens for p in parts)
    torch.testing.assert_close(out.loss, expected)
    assert not torch.isclose(expected, sum(p.loss for p in parts) / 2)


@pytest.mark.parametrize("kind", KINDS[:3])
def test_no_memory_training_preserves_dropout_rng(kind):
    graph, batch = setup(kind)
    graph.train()
    reference = copy.deepcopy(graph.model)
    batch.pop("memory_ids")
    batch.pop("memory_mask")
    torch.manual_seed(31)
    actual = graph(**batch)
    actual_rng = torch.get_rng_state()
    torch.manual_seed(31)
    expected = reference(
        batch["input_ids"], attention_mask=batch["attention_mask"], use_cache=False
    ).logits
    assert torch.equal(actual.logits, expected)
    assert torch.equal(actual_rng, torch.get_rng_state())


@pytest.mark.parametrize("kind", KINDS[:3])
def test_checkpointed_training_preserves_live_memory_graph(kind):
    plain, batch = setup(kind)
    checkpointed, _ = setup(kind)
    plain.train()
    checkpointed.train()
    checkpointed.model.gradient_checkpointing_enable(
        gradient_checkpointing_kwargs={"use_reentrant": False}
    )
    assert checkpointed.model.is_gradient_checkpointing
    losses = []
    for graph in (plain, checkpointed):
        torch.manual_seed(53)
        loss = graph(**batch).loss
        loss.backward()
        losses.append(loss.detach())
    assert torch.equal(*losses)
    for (name, a), (_, b) in zip(
        plain.named_parameters(), checkpointed.named_parameters(), strict=True
    ):
        assert a.grad is not None and b.grad is not None, name
        assert torch.equal(a.grad, b.grad), name


@pytest.mark.parametrize("kind", KINDS)
def test_fresh_process_replays_standard_cpu_optimizer_update(kind, tmp_path):
    # This is a graph + ordinary CPU AdamW test, not the production offload owner.
    root = Path(__file__).resolve().parents[1]
    command = """
import sys
from pathlib import Path
import torch
from test_native_memory import setup
torch.set_num_threads(2)
torch.use_deterministic_algorithms(True)
graph, batch = setup(sys.argv[1])
graph.train()
optimizer = torch.optim.AdamW(graph.parameters(), lr=0.01, foreach=False)
path = Path(sys.argv[2])
if sys.argv[3] == 'replay':
    saved = torch.load(path / 'step1.pt', weights_only=True)
    assert saved['contract'] == graph.contract()
    graph.load_state_dict(saved['model'])
    optimizer.load_state_dict(saved['optimizer'])
    torch.set_rng_state(saved['rng'])
for step in ([1, 2] if sys.argv[3] == 'primary' else [2]):
    optimizer.zero_grad(set_to_none=True)
    loss = graph(**batch).loss
    loss.backward()
    optimizer.step()
    optimizer.zero_grad(set_to_none=True)
    filename = f'step{step}.pt' if sys.argv[3] == 'primary' else 'replay.pt'
    torch.save(dict(model=graph.state_dict(), optimizer=optimizer.state_dict(),
                    loss=loss.detach(), rng=torch.get_rng_state(), contract=graph.contract()),
               path / filename)
"""
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(root / "src"), str(root / "tests")]))
    for mode in ("primary", "replay"):
        subprocess.run(
            [sys.executable, "-c", command, kind, str(tmp_path), mode],
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    expected = torch.load(tmp_path / "step2.pt", weights_only=True)
    actual = torch.load(tmp_path / "replay.pt", weights_only=True)

    def equal(a, b):
        if torch.is_tensor(a):
            return torch.equal(a, b)
        if isinstance(a, dict):
            return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
        if isinstance(a, (list, tuple)):
            return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b, strict=True))
        return a == b

    assert equal(expected, actual)


@pytest.mark.parametrize("bad_cut", [-1, 2, 1.5, True])
def test_invalid_cut_fails(bad_cut):
    with pytest.raises(ValueError, match="cut"):
        NativeMemoryCausalLM(host_model("mistral"), cut=bad_cut)


@pytest.mark.parametrize(
    "case",
    [
        "left_pad",
        "fractional",
        "label_pad",
        "label_zero",
        "no_target",
        "target_oov",
        "orphan_mask",
        "memory_batch",
        "empty_query",
        "token_oov",
    ],
)
def test_invalid_batch_fails_before_execution(case):
    graph, batch = setup()
    if case == "left_pad":
        batch["memory_mask"][1] = torch.tensor([0, 1, 1])
    elif case == "fractional":
        batch["memory_mask"] = batch["memory_mask"].float() * 0.5
    elif case == "label_pad":
        batch["labels"][1, -1] = 2
    elif case == "label_zero":
        batch["labels"][0, 0] = 2
    elif case == "no_target":
        batch["labels"].fill_(-100)
    elif case == "target_oov":
        batch["labels"][0, -1] = 43
    elif case == "orphan_mask":
        batch.pop("memory_ids")
    elif case == "memory_batch":
        batch["memory_ids"] = batch["memory_ids"][:1]
    elif case == "empty_query":
        batch["attention_mask"][0].zero_()
    elif case == "token_oov":
        batch["input_ids"][0, -1] = 43
    with pytest.raises(ValueError):
        graph(**batch)
