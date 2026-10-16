"""Parity of the ``latent_workspace`` engine with the frozen historical modules.

Every promoted object (configs/architecture/PROMOTIONS.json) has a test here that
compares it with its historical original: identical initial state from the same
seed, and bitwise-identical outputs and gradients on fixed tiny cases.
"""

import pytest
import torch
from test_v15_full_update import tiny
from transformers import GPT2Config, GPT2LMHeadModel, Olmo2Config, Olmo2ForCausalLM

import latent_workspace as lw
from latent_workspace import composition, stats, training
from latent_workspace_ft_v10 import (
    engine,
    model_binding,
    normalization,
    readout_transport,
    v15_readout,
    v20_deliberation,
    workspace_core,
)


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


def same_init(new, old, seed, *args, **kwargs):
    torch.manual_seed(seed)
    a = new(*args, **kwargs)
    torch.manual_seed(seed)
    b = old(*args, **kwargs)
    sa, sb = a.state_dict(), b.state_dict()
    assert sa.keys() == sb.keys() and all(torch.equal(sa[k], sb[k]) for k in sa)
    return a, b


def open_paths(*modules, seed=11, names=()):
    """Fill zero-initialized output paths with identical seeded values."""
    for module in modules:
        generator = torch.Generator().manual_seed(seed)
        with torch.no_grad():
            for name in names:
                parameter = module.get_parameter(name)
                parameter.copy_(0.3 * torch.randn(parameter.shape, generator=generator))


def grads(module):
    return {n: p.grad.clone() for n, p in module.named_parameters() if p.grad is not None}


# ---- promoted objects: parity with the frozen originals -------------------------


@pytest.mark.parametrize("kind", ["mistral", "olmo2", "gpt2", "scratch"])
def test_cut_protocol_is_the_historical_protocol(kind):
    model = host_model(kind)
    new, old = lw.FunctionalBoundaryAdapter(model), model_binding.FunctionalBoundaryAdapter(model)
    ids, mask = inputs()
    assert new.layer_count() == old.layer_count() == 2
    with torch.no_grad():
        for cut in range(3):
            hidden = old.encode(ids, mask, cut)
            assert torch.equal(new.encode(ids, mask, cut), hidden)
            assert torch.equal(new.decode(hidden, mask, cut), old.decode(hidden, mask, cut))
            assert new.describe_boundary(cut).to_dict() == old.describe_boundary(cut).to_dict()


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_native_readout_is_the_historical_readout(dtype):
    model, _, _ = tiny(dtype)
    model.eval().requires_grad_(False)
    ids, mask = inputs(1)
    normalized = model.model(ids[:1], attention_mask=mask[:1]).last_hidden_state
    delta = 0.1 * torch.randn(1, 1, 16, generator=torch.Generator().manual_seed(2))
    new = lw.NativeWorkspaceReadout(model.lm_head)(normalized, delta)
    old = v15_readout.NativeWorkspaceReadout(model.lm_head)(normalized, delta)
    for field in old.__slots__:
        a, b = getattr(new, field), getattr(old, field)
        assert torch.equal(a, b) if isinstance(b, torch.Tensor) else a == b, field
    a, b = lw.inject_last(normalized, delta), readout_transport.inject_last(normalized, delta)
    for field in (
        "sequence",
        "original_last",
        "intended_delta",
        "corrected_last_fp32",
        "applied_delta",
    ):
        assert torch.equal(getattr(a, field), getattr(b, field)), field


def test_logit_adapter_and_operators_are_historical():
    new, old = same_init(
        lw.LowRankWorkspaceLogitAdapter, workspace_core.LowRankWorkspaceLogitAdapter, 5, 8, 43, 4
    )
    open_paths(new, old, names=("up.weight",))
    state = torch.randn(3, 8, generator=torch.Generator().manual_seed(1))
    assert torch.equal(new(state), old(state))
    for kind, eps in (("layer_norm", 1e-5), ("rms_norm", 1e-6)):
        a, b = lw.NormalizationSpec(kind, eps), normalization.NormalizationSpec(kind, eps)
        assert type(a.build(8)) is type(b.build(8)) and a.fingerprint() == b.fingerprint()


LATTICE_PATHS = ("attention.out.weight", "candidate_out.weight", "anchor_projection.weight")


@pytest.mark.parametrize(
    "new_cls,old_cls,paths",
    [
        (lw.CausalBroadcastLatentWorkspace, engine.CausalBroadcastLatentWorkspace, LATTICE_PATHS),
        (lw.CausalLatentWorkspace, engine.CausalLatentWorkspace, LATTICE_PATHS[1:]),
    ],
)
@pytest.mark.parametrize("steps", [1, 3])
def test_lattices_are_the_historical_lattices(new_cls, old_cls, paths, steps):
    kwargs = dict(dropout=0.1)
    if new_cls is lw.CausalBroadcastLatentWorkspace:
        kwargs["attention_heads"] = 2
    new, old = same_init(new_cls, old_cls, 7, 16, 8, steps, **kwargs)
    open_paths(new, old, names=paths)
    hidden = torch.randn(2, 6, 16, generator=torch.Generator().manual_seed(4))
    mask = torch.ones(2, 6, dtype=torch.long)
    mask[1, 4:] = 0
    outputs = []
    for module in (new, old):
        module.train()
        torch.manual_seed(9)
        latents, anchor = module(hidden, mask)
        (latents.square().sum() + anchor.sum()).backward()
        outputs.append((latents, anchor))
    assert all(torch.equal(a, b) for a, b in zip(*outputs, strict=True))
    ga, gb = grads(new), grads(old)
    assert ga.keys() == gb.keys() and all(torch.equal(ga[k], gb[k]) for k in ga)


def test_workspace_loss_is_the_historical_loss():
    config = dict(projection_dim=8, probe_dropout=0.05)
    new, old = same_init(lw.LatentWorkspaceLoss, engine.LatentWorkspaceLoss, 3, 8, **config)
    generator = torch.Generator().manual_seed(6)
    latents = torch.randn(12, 3, 8, generator=generator, requires_grad=True)
    h0 = torch.randn(12, 8, generator=generator)
    groups = torch.arange(12) // 3
    results, input_grads = [], []
    for module in (new, old):
        module.train()
        torch.manual_seed(8)
        result = module(latents, h0, compute_spectral=True, contrastive_group_ids=groups)
        result["loss"].backward()
        results.append(result)
        input_grads.append(latents.grad.clone())
        latents.grad = None
    a, b = results
    assert a.keys() == b.keys()
    assert all(torch.equal(a[k], b[k]) if torch.is_tensor(b[k]) else a[k] == b[k] for k in a)
    assert torch.equal(*input_grads)
    ga, gb = grads(new), grads(old)
    assert ga.keys() == gb.keys() and all(torch.equal(ga[k], gb[k]) for k in ga)


def test_statistics_are_the_historical_statistics():
    generator = torch.Generator().manual_seed(12)
    left = torch.randint(0, 2, (96,), generator=generator).bool().tolist()
    right = torch.randint(0, 2, (96,), generator=generator).bool().tolist()
    worlds = [i // 6 for i in range(96)]
    rule = {"minimum_accuracy_gain": 0.02, "alpha": 0.01}
    adapted = torch.randn(96, 2, generator=generator)
    targets = torch.randint(0, 2, (96,), generator=generator).tolist()
    assert stats.correct_flags(adapted, targets) == v20_deliberation.correct_flags(adapted, targets)
    for k, n in ((0, 0), (3, 10), (10, 10)):
        assert stats.binomial_upper(k, n) == v20_deliberation.binomial_upper(k, n)
    assert stats.world_sign(left, right, worlds) == v20_deliberation.world_sign(left, right, worlds)
    assert stats.gain(left, right, worlds, rule) == v20_deliberation.gain(left, right, worlds, rule)
    passed, failed = {"passed": True}, {"passed": False}
    labels = ("A", "B", "C")
    for route, step in (([passed] * 3, [passed] * 3), ([passed] * 3, [failed]), ([failed], [])):
        assert stats.verdict(route, step, labels) == v20_deliberation.verdict(route, step, labels)


def d1_features(rows=12, hidden=16, seed=21):
    """Variable-length frozen features in D1's bank layout."""
    generator = torch.Generator().manual_seed(seed)
    lengths = torch.randint(3, 7, (rows,), generator=generator)
    offsets = torch.cat([torch.zeros(1, dtype=torch.long), lengths.cumsum(0)])
    states = torch.randn(int(offsets[-1]), hidden, generator=generator).to(torch.bfloat16)
    base = torch.randn(rows, 2, generator=generator)
    targets = torch.randint(0, 2, (rows,), generator=generator)
    worlds = torch.arange(rows) // 4
    return states, offsets, base, targets, worlds


def d1_route(module, steps, seed=5):
    return module.DeliberationRoute(
        16, 43, (6, 7), steps=steps, seed=seed, workspace_dim=8, heads=2, rank=4
    )


@pytest.mark.parametrize("steps", [0, 1, 4])
def test_deliberation_route_is_the_d1_route(steps):
    new, old = d1_route(composition, steps), d1_route(v20_deliberation, steps)
    sn, so = new.state_dict(), old.state_dict()
    assert sn.keys() == so.keys() and all(torch.equal(sn[k], so[k]) for k in sn)
    names = ["adapter.up.weight", "gate.weight"]
    if steps:
        names += ["lattice.attention.out.weight", "lattice.candidate_out.weight"]
    open_paths(new, old, names=names)
    bank = training.FeatureBank(*d1_features())
    hidden, mask, _, _, _ = bank.batch(list(range(6)))
    for mode in ("train", "eval"):
        outputs = []
        for route in (new, old):
            getattr(route, mode)()
            route.zero_grad(set_to_none=True)
            torch.manual_seed(9)
            delta, latents, anchor, gate = route(hidden, mask)
            (delta.square().sum() + gate.sum()).backward()
            outputs.append(((delta, latents, anchor, gate), grads(route)))
        (a, ga), (b, gb) = outputs
        assert all(
            (x is None and y is None) or torch.equal(x, y) for x, y in zip(a, b, strict=True)
        )
        assert ga.keys() == gb.keys() and all(torch.equal(ga[k], gb[k]) for k in ga)
    if steps == 4:
        with new.truncated(2), old.truncated(2):
            assert torch.equal(new(hidden, mask)[0], old(hidden, mask)[0])


def test_frozen_feature_training_is_the_d1_trainer():
    features = d1_features(rows=16)
    runs = []
    for module, routes in ((training, composition), (v20_deliberation, v20_deliberation)):
        route = d1_route(routes, 4, seed=3)
        loss = module.workspace_loss(3, 8)
        bank = module.FeatureBank(*features)
        config = module.TrainConfig(
            seed=3,
            updates=3,
            batch_size=4,
            learning_rate=1e-3,
            weight_decay=0.01,
            max_grad_norm=1.0,
            workspace_loss_weight=0.02,
            loss_tokens_per_row=2,
            loss_tokens_per_batch=6,
            spectral_every=2,
        )
        named = module.trainable(route, loss)
        optimizer = module.optimizer_for(named, config.learning_rate, config.weight_decay)
        receipts = [module.update(route, loss, optimizer, bank, config, step) for step in (1, 2, 3)]
        runs.append(
            dict(
                receipts=receipts,
                fingerprint=module.fingerprint(named),
                evaluated=module.evaluate(route, bank, batch_size=5),
                order=[module.batch_indices(config, len(bank), s) for s in (1, 4, 5)],
            )
        )
    new, old = runs
    assert new["receipts"] == old["receipts"] and new["fingerprint"] == old["fingerprint"]
    assert torch.equal(new["evaluated"], old["evaluated"]) and new["order"] == old["order"]
    named = training.trainable(d1_route(composition, 4))
    assert [training._uses_weight_decay(n, p) for n, p in named] == [
        engine._uses_weight_decay(n, p) for n, p in named
    ]
    mask = torch.tensor([[1, 1, 1, 0], [1, 1, 0, 0], [1, 1, 1, 1]])
    for per_row, cap in ((2, 5), (9, 4)):
        assert all(
            torch.equal(x, y)
            for x, y in zip(
                training.sample_positions(mask, per_row, cap, torch.Generator().manual_seed(1)),
                v20_deliberation.sample_positions(
                    mask, per_row, cap, torch.Generator().manual_seed(1)
                ),
                strict=True,
            )
        )


# ---- engine composition --------------------------------------------------------


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
    open_paths(
        d1,
        names=(
            "adapter.up.weight",
            "gate.weight",
            "lattice.attention.out.weight",
            "lattice.candidate_out.weight",
        ),
    )
    route = lw.LogitResidualRoute(8, 43, 16, rank=4)
    route.adapter.load_state_dict(d1.adapter.state_dict())
    route.gate_norm.load_state_dict(d1.gate_norm.state_dict())
    route.gate.load_state_dict(d1.gate.state_dict())
    lattice = lw.CausalBroadcastLatentWorkspace(16, 8, 4, dropout=0.05, attention_heads=2).eval()
    lattice.load_state_dict(d1.lattice.state_dict())
    hidden, mask = torch.randn(3, 5, 16), torch.ones(3, 5, dtype=torch.long)
    expected, _, _, expected_gate = d1(hidden, mask)
    latents, _ = lattice(hidden, mask)
    delta, gate = route(hidden[:, -1], latents[:, -1, -1], candidate_ids=[6, 7])
    assert torch.equal(delta, expected) and torch.equal(gate, expected_gate)
    full, _ = route(hidden[:, -1], latents[:, -1, -1])
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
    native = v15_readout.NativeWorkspaceReadout(model.lm_head)(normalized, delta)
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
