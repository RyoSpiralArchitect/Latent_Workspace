"""Parity of the version-free ``latent_workspace`` stack with the historical modules."""

import pytest
import torch
from test_v15_full_update import tiny
from transformers import GPT2Config, GPT2LMHeadModel, Olmo2Config, Olmo2ForCausalLM

import latent_workspace as lw
from latent_workspace_ft_v10 import engine, v20_deliberation, workspace_core
from latent_workspace_ft_v10.v15_readout import NativeWorkspaceReadout
from latent_workspace_ft_v10.v19_dual_budget_reader import DualBudgetWorkspaceBridge


@pytest.fixture(autouse=True)
def threads():
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


def host_model(kind):
    torch.manual_seed(3)
    if kind == "mistral":
        model, _, _ = tiny(torch.float32)
    elif kind == "olmo2":
        config = Olmo2Config(
            vocab_size=43,
            hidden_size=16,
            intermediate_size=32,
            num_hidden_layers=2,
            num_attention_heads=4,
            num_key_value_heads=2,
            max_position_embeddings=64,
            pad_token_id=0,
            use_cache=False,
        )
        config._attn_implementation = "eager"
        model = Olmo2ForCausalLM(config)
    elif kind == "gpt2":
        config = GPT2Config(vocab_size=43, n_embd=16, n_layer=2, n_head=4, n_positions=64)
        config._attn_implementation = "eager"
        model = GPT2LMHeadModel(config)
    else:
        model = lw.ScratchDecoder(43, width=16, layers=2, heads=4, max_length=64)
    return model.eval().requires_grad_(False)


def inputs(seed=0):
    generator = torch.Generator().manual_seed(seed)
    ids = torch.randint(1, 43, (2, 7), generator=generator)
    return ids, torch.ones_like(ids)


def test_components_are_the_historical_classes():
    assert lw.CausalBroadcastLattice is engine.CausalBroadcastLatentWorkspace
    assert lw.TokenLocalLattice is engine.CausalLatentWorkspace
    assert lw.LatentWorkspaceLoss is engine.LatentWorkspaceLoss
    assert lw.LowRankLogitAdapter is workspace_core.LowRankWorkspaceLogitAdapter
    assert lw.FunctionalMemoryWriter is workspace_core.FunctionalMemoryWriter
    assert lw.FunctionalMemoryReader is workspace_core.FunctionalMemoryReader
    assert lw.DualBudgetBridge is DualBudgetWorkspaceBridge


@pytest.mark.parametrize("kind", ["mistral", "olmo2", "gpt2", "scratch"])
def test_decoder_hosts_reproduce_their_native_logits(kind):
    model = host_model(kind)
    host = lw.DecoderHost(model)
    ids, mask = inputs()
    with torch.no_grad():
        native = model(ids, attention_mask=mask, use_cache=False).logits
        assert torch.equal(host.logits(ids, mask), native)
        assert torch.equal(host.head(host.final_states(ids, mask)), native)
        for cut in (0, 1, host.layer_count):
            split = host.from_cut(host.to_cut(ids, mask, cut), mask, cut)
            assert torch.equal(split, native), (kind, cut)
    assert host.layer_count == 2 and host.hidden_size == 16


def test_logit_route_reproduces_the_v20_d1_route():
    d1 = v20_deliberation.DeliberationRoute(
        16, 43, (6, 7), steps=4, seed=5, workspace_dim=8, heads=2, rank=4
    ).eval()
    generator = torch.Generator().manual_seed(11)
    with torch.no_grad():
        for parameter in (
            d1.adapter.up.weight,
            d1.gate.weight,
            d1.lattice.attention.out.weight,
            d1.lattice.candidate_out.weight,
        ):
            parameter.copy_(0.3 * torch.randn(parameter.shape, generator=generator))
    route = lw.LogitResidualRoute(8, 43, 16, rank=4)
    route.adapter.load_state_dict(d1.adapter.state_dict())
    route.gate_norm.load_state_dict(d1.gate_norm.state_dict())
    route.gate.load_state_dict(d1.gate.state_dict())
    hidden, mask = torch.randn(3, 5, 16), torch.ones(3, 5, dtype=torch.long)
    expected, _, _, expected_gate = d1(hidden, mask)
    latents, _ = d1.lattice(hidden, mask)
    delta, gate = route(hidden[:, -1], latents[:, -1, -1], candidate_ids=[6, 7])
    assert torch.equal(delta, expected) and torch.equal(gate, expected_gate)
    full, _ = route(hidden[:, -1], latents[:, -1, -1])
    assert torch.allclose(full[:, [6, 7]], expected, atol=1e-6, rtol=0)
    assert torch.allclose(full, gate * d1.adapter(latents[:, -1, -1]), atol=1e-6, rtol=0)


def test_logit_route_starts_at_zero():
    route = lw.LogitResidualRoute(8, 43, 16, rank=4)
    delta, gate = route(torch.randn(2, 16), torch.randn(2, 8))
    assert torch.equal(delta, torch.zeros_like(delta))
    assert torch.allclose(gate, torch.sigmoid(torch.tensor(-2.0)).expand_as(gate))


def test_answer_route_is_the_native_readout():
    model = host_model("mistral")
    host = lw.DecoderHost(model)
    ids, mask = inputs(1)
    normalized = host.final_states(ids[:1], mask[:1])
    delta = 0.1 * torch.randn(1, 1, 16, generator=torch.Generator().manual_seed(2))
    native = NativeWorkspaceReadout(model.lm_head)(normalized, delta)
    routed = lw.AnswerResidualRoute(host.readout())(normalized, delta)
    assert torch.equal(routed.logits, native.logits)


@pytest.mark.parametrize("kind", ["mistral", "scratch"])
def test_cut_route_is_native_at_zero_and_causal_when_writing(kind):
    host = lw.DecoderHost(host_model(kind))
    ids, mask = inputs(2)
    route = lw.CutResidualRoute(host, 1)
    zero = torch.zeros(2, 7, 16)
    with torch.no_grad():
        native = host.logits(ids, mask)
        assert torch.equal(route(ids, mask, zero), native)
        write = zero.clone()
        write[:, 4] = torch.randn(2, 16, generator=torch.Generator().manual_seed(3))
        changed = route(ids, mask, write)
    assert torch.equal(changed[:, :4], native[:, :4])
    assert not torch.equal(changed[:, 4:], native[:, 4:])
    with pytest.raises(ValueError, match="Cut"):
        lw.CutResidualRoute(host, 3)


def test_scratch_host_trains_with_a_workspace_through_a_cut():
    torch.manual_seed(4)
    model = lw.ScratchDecoder(43, width=16, layers=2, heads=4, max_length=64)
    host = lw.DecoderHost(model)
    lattice = lw.CausalBroadcastLattice(16, 8, 2, dropout=0.0, attention_heads=2)
    project = torch.nn.Linear(8, 16)
    route = lw.CutResidualRoute(host, 1)
    ids, mask = inputs(5)
    targets = torch.roll(ids, -1, dims=1)
    parameters = [*model.parameters(), *lattice.parameters(), *project.parameters()]
    optimizer = torch.optim.AdamW(parameters, lr=1e-2)
    losses = []
    for _ in range(30):
        hidden = host.to_cut(ids, mask, 1)
        latents, _ = lattice(hidden, mask)
        logits = route(ids, mask, project(latents[:, :, -1]))
        loss = torch.nn.functional.cross_entropy(logits.reshape(-1, 43), targets.reshape(-1))
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        losses.append(float(loss.detach()))
    assert losses[-1] < 0.5 * losses[0]
    assert all(p.grad is not None for p in lattice.parameters() if p.requires_grad)
