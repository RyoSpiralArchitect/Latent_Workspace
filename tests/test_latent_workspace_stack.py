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


def test_cpu_gradient_transport_is_historical():
    import inspect
    import os

    from latent_workspace import offload
    from latent_workspace_ft_v10 import v15_native_learner

    device = os.environ.get("LTWS_TEST_DEVICE", "cpu")
    for name in ("_CPUGradientAccumulatorSpec", "_CPUGradientAccumulator"):
        assert inspect.getsource(getattr(offload, name)) == inspect.getsource(getattr(engine, name))
    assert inspect.getsource(offload.CompleteCPUWindow) == inspect.getsource(
        v15_native_learner.CompleteCPUWindow
    )
    for dtype in (torch.float32, torch.bfloat16):
        values = []
        for cls in (offload.CompleteCPUWindow, v15_native_learner.CompleteCPUWindow):
            params = [
                ("a", torch.nn.Parameter(torch.ones(3, 5, dtype=dtype, device=device))),
                ("b", torch.nn.Parameter(torch.ones(2, dtype=dtype, device=device))),
            ]
            window = cls(params, merge_device="cpu")
            receipts = []
            for micro in range(3):
                for _, param in params:
                    param.grad = torch.full_like(param, (micro + 1) / 7)
                receipts.append(window.spill())
            gradients, receipt = window.take(3)
            values.append((gradients, receipts, receipt))
        assert values[0][1:] == values[1][1:]
        assert all(torch.equal(values[0][0][key], values[1][0][key]) for key in values[0][0])


def test_native_state_utilities_are_historical():
    import inspect

    from latent_workspace import optimizer_state
    from latent_workspace_ft_v10 import (
        adapter_native_learner_v2,
        training_binding,
        v15_native_learner,
    )

    for source, names in (
        (v15_native_learner, ("require", "tree_hash", "finite_tree", "rng_state", "restore_rng")),
        (
            adapter_native_learner_v2,
            ("snapshot", "tensor_schema", "validate_rng", "validate_optimizer"),
        ),
        (training_binding, ("checkpoint_policy",)),
    ):
        for name in names:
            assert inspect.getsource(getattr(optimizer_state, name)) == inspect.getsource(
                getattr(source, name)
            )
    state = optimizer_state.rng_state()
    optimizer_state.validate_rng(state)
    assert optimizer_state.tree_hash(state) == v15_native_learner.tree_hash(state)
    copied = optimizer_state.snapshot(state)
    copied["torch_cpu"].zero_()
    assert not torch.equal(copied["torch_cpu"], state["torch_cpu"])


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


# ---- deferred memory (V20 A2): an engine option on the promoted route and trainer ----


def left_aligned(lengths, width, hidden=16, seed=0):
    generator = torch.Generator().manual_seed(seed)
    values = torch.randn(len(lengths), width, hidden, generator=generator)
    mask = (torch.arange(width)[None] < torch.tensor(lengths)[:, None]).long()
    return values * mask[..., None], mask


def test_deferred_memory_packs_memory_before_the_query():
    route = d1_route(composition, 4, seed=8).eval()
    open_paths(route, names=["adapter.up.weight", "gate.weight", "lattice.attention.out.weight"])
    memory, memory_mask = left_aligned([3, 0, 5], 5, seed=1)
    hidden, mask = left_aligned([4, 2, 3], 4, seed=2)
    delta, latents, _, gate = route(hidden, mask, memory, memory_mask)
    for row in range(3):
        m, q = int(memory_mask[row].sum()), int(mask[row].sum())
        alone = torch.cat([memory[row, :m], hidden[row, :q]])[None]
        expected, _, _, expected_gate = route(alone, torch.ones(1, m + q, dtype=torch.long))
        assert torch.allclose(delta[row], expected[0], atol=1e-6, rtol=0)
        assert torch.allclose(gate[row], expected_gate[0], atol=1e-6, rtol=0)
    assert latents.shape[1] == 9
    moved = memory + torch.randn(memory.shape, generator=torch.Generator().manual_seed(3))
    assert not torch.allclose(
        route(hidden, mask, moved * memory_mask[..., None], memory_mask)[0][0], delta[0]
    )
    empty = route(hidden, mask, memory, memory_mask)[0][1]  # row 1 has no memory
    assert torch.allclose(empty, route(hidden, mask)[0][1], atol=1e-6, rtol=0)
    with pytest.raises(ValueError, match="left-aligned"):
        route(hidden, mask, memory, memory_mask.flip(1))
    with pytest.raises(ValueError, match="Empty row"):
        route(hidden, mask * 0, memory, memory_mask)


def test_feature_bank_shares_segments_and_carries_memory():
    states, offsets, base, targets, worlds = d1_features(rows=4)
    shared = training.FeatureBank(
        states,
        offsets,
        base[[0, 1, 1, 3]],
        targets[[0, 1, 1, 3]],
        worlds[[0, 1, 1, 3]],
        segments=torch.tensor([0, 1, 1, 3]),
    )
    copies = training.FeatureBank(states, offsets, base, targets, worlds)
    for got, want in zip(shared.batch([1, 2]), copies.batch([1, 1]), strict=True):
        assert torch.equal(got, want)
    memory = (states, offsets, torch.tensor([3, 0, 2, 2]))
    bank = shared.with_memory(memory)
    values, mask = bank.memory_batch([0, 3])
    assert torch.equal(values, copies.batch([3, 2])[0]) and torch.equal(
        mask, copies.batch([3, 2])[1]
    )
    assert shared.memory_batch([0]) is None and bank.with_memory(None).memory is None
    route = d1_route(composition, 2, seed=4)
    open_paths(route, names=["adapter.up.weight", "gate.weight"])
    adapted, final = training.evaluate(route, bank, batch_size=3, final=True)
    hidden, query_mask, rows_base, _, _ = bank.batch([0, 1, 2, 3])
    delta, latents, _, _ = route(hidden, query_mask, *bank.memory_batch([0, 1, 2, 3]))
    assert torch.allclose(adapted, rows_base + delta, atol=1e-6, rtol=0) and final.shape == (4, 8)
    with pytest.raises(ValueError, match="segments"):
        shared.with_memory((states, offsets, torch.tensor([0, 1, 9, 2])))


def test_deferred_memory_route_learns_what_only_the_memory_holds():
    """Both sides of a pair share one query and differ only in memory and answer (as in A2):
    the memory route learns to read the planted answer, a query-only route stays at chance."""
    generator = torch.Generator().manual_seed(17)
    pairs, hidden = 48, 16
    rows = 2 * pairs
    first = torch.randint(0, 2, (pairs,), generator=generator)
    labels = torch.stack([first, 1 - first], 1).flatten()
    direction = torch.randn(hidden, generator=generator)
    queries = torch.randn(pairs * 3, hidden, generator=generator).to(torch.bfloat16)
    query_offsets, query_segments = torch.arange(0, pairs * 3 + 1, 3), torch.arange(rows) // 2
    memories = 0.5 * torch.randn(rows * 2, hidden, generator=generator)
    memories[1::2] += 2.0 * (2 * labels[:, None] - 1) * direction
    memory_offsets = torch.arange(0, rows * 2 + 1, 2)
    base, worlds = torch.zeros(rows, 2), torch.arange(rows) // 2
    config = training.TrainConfig(
        seed=2,
        updates=240,
        batch_size=16,
        learning_rate=3e-3,
        weight_decay=0.0,
        max_grad_norm=1.0,
        workspace_loss_weight=0.0,
        loss_tokens_per_row=0,
        loss_tokens_per_batch=0,
        spectral_every=1,
    )
    held_out = {}
    for name, carried in (("memory", True), ("query_only", False)):
        route = composition.DeliberationRoute(
            hidden, 43, (6, 7), steps=1, seed=2, workspace_dim=8, heads=2, rank=4, dropout=0.0
        )

        def bank(n, carried=carried):
            rows_bank = training.FeatureBank(
                queries,
                query_offsets,
                base[:n],
                labels[:n],
                worlds[:n],
                segments=query_segments[:n],
            )
            return rows_bank.with_memory(
                (memories.to(torch.bfloat16), memory_offsets, torch.arange(n)) if carried else None
            )

        optimizer = training.optimizer_for(training.trainable(route), 3e-3, 0.0)
        train = bank(64)  # pairs 0-31; pairs 32-47 are never trained on
        for step in range(1, config.updates + 1):
            training.update(route, None, optimizer, train, config, step)
        adapted = training.evaluate(route, bank(rows))[64:]
        held_out[name] = float((adapted.argmax(1) == labels[64:]).float().mean())
    assert held_out["memory"] >= 0.9 and held_out["query_only"] == 0.5, held_out


# ---- memory written into the host at a cut (V20 A2 depth ladder) -------------------


@pytest.mark.parametrize("kind", ["mistral", "olmo2", "gpt2", "scratch"])
def test_hosts_expose_their_final_states_from_every_cut(kind):
    host = lw.DecoderHost(host_model(kind))
    ids, mask = inputs(6)
    native = host.final_states(ids, mask)
    for cut in range(host.layer_count + 1):
        hidden = host.to_cut(ids, mask, cut)
        states = host.from_cut_states(hidden, mask, cut)
        assert torch.equal(host.head(states), host.from_cut(hidden, mask, cut)), cut
        assert torch.equal(states, native), cut


def prefix_parts(seed=8, memory=5, query=4):
    generator = torch.Generator().manual_seed(seed)
    memory_ids = torch.randint(1, 43, (1, memory), generator=generator)
    query_ids = torch.randint(1, 43, (1, query), generator=generator)
    return memory_ids, query_ids


@pytest.mark.parametrize("kind", ["mistral", "olmo2"])
def test_cut_prefix_route_at_cut_zero_is_the_inline_forward(kind):
    """On a rotary-position host, a memory written at cut 0 is the memory text inline."""
    host = lw.DecoderHost(host_model(kind))
    memory_ids, query_ids = prefix_parts()
    route = composition.CutPrefixRoute(host, 0)
    ones = torch.ones_like
    states, logits, mask = route(
        host.to_cut(query_ids, ones(query_ids), 0),
        ones(query_ids),
        host.to_cut(memory_ids, ones(memory_ids), 0),
        ones(memory_ids),
    )
    inline = torch.cat([memory_ids, query_ids], 1)
    assert torch.equal(logits, host.logits(inline, ones(inline)))
    assert torch.equal(states, host.final_states(inline, ones(inline)))
    assert mask.tolist() == [[1] * 9]


def test_cut_prefix_route_packs_rows_and_reads_memory_at_a_deeper_cut():
    host = lw.DecoderHost(host_model("mistral"))
    route = composition.CutPrefixRoute(host, 1)
    rows = [prefix_parts(seed, m, q) for seed, m, q in ((1, 5, 4), (2, 3, 6))]

    def encode(ids_list):
        width = max(ids.shape[1] for ids in ids_list)
        hidden = torch.zeros(len(ids_list), width, 16)
        mask = torch.zeros(len(ids_list), width, dtype=torch.long)
        for row, ids in enumerate(ids_list):
            hidden[row, : ids.shape[1]] = host.to_cut(ids, torch.ones_like(ids), 1)[0]
            mask[row, : ids.shape[1]] = 1
        return hidden, mask

    memory, memory_mask = encode([m for m, _ in rows])
    query, query_mask = encode([q for _, q in rows])
    _, logits, mask = route(query, query_mask, memory, memory_mask)
    for row, (m, q) in enumerate(rows):
        alone, alone_logits, _ = route(*encode([q]), *encode([m]))
        last = int(mask[row].sum()) - 1
        assert torch.allclose(logits[row, last], alone_logits[0, -1], atol=1e-5, rtol=0)
    other = memory + torch.randn(memory.shape, generator=torch.Generator().manual_seed(3))
    _, moved, _ = route(query, query_mask, other * memory_mask[..., None], memory_mask)
    assert not torch.allclose(moved[0, 8], logits[0, 8])
    with pytest.raises(ValueError, match="Cut"):
        composition.CutPrefixRoute(host, 3)


# ---- content gating (V20 A4): an engine option on the trainer -------------------------


def gating_config(weight, **changes):
    values = dict(
        seed=3,
        updates=3,
        batch_size=4,
        learning_rate=1e-3,
        weight_decay=0.01,
        max_grad_norm=1.0,
        workspace_loss_weight=0.0,
        loss_tokens_per_row=0,
        loss_tokens_per_batch=0,
        spectral_every=1,
        mismatch_weight=weight,
    )
    values.update(changes)
    return training.TrainConfig(**values)


def gating_banks(deferred):
    states, offsets, base, targets, worlds = d1_features(rows=16)
    other = d1_features(rows=16, seed=22)
    if not deferred:
        return training.FeatureBank(states, offsets, base, targets, worlds), training.FeatureBank(
            *other
        )
    bank = training.FeatureBank(
        states, offsets, base, targets, worlds, memory=(other[0], other[1], torch.arange(16))
    )
    return bank, bank.with_memory((other[0], other[1], torch.arange(16).roll(5)))


@pytest.mark.parametrize("deferred", [False, True])
def test_content_gating_adds_the_mismatch_residual_penalty(deferred):
    """The option is exactly cross-entropy plus the weight times the mean square of the
    route's residual on the same batch rows read with the mismatch memory."""
    bank, mismatch = gating_banks(deferred)
    config = gating_config(0.3)
    names = ["adapter.up.weight", "gate.weight", "lattice.attention.out.weight"]
    engine_route, hand_route, plain_route = (d1_route(composition, 2, seed=3) for _ in range(3))
    open_paths(engine_route, hand_route, plain_route, names=names)
    optimizers = [
        training.optimizer_for(training.trainable(r), config.learning_rate, config.weight_decay)
        for r in (engine_route, hand_route, plain_route)
    ]
    receipts = [
        training.update(engine_route, None, optimizers[0], bank, config, step, mismatch)
        for step in (1, 2, 3)
    ]
    for step in (1, 2, 3):
        hand_route.train()
        torch.manual_seed(training.component_seed(config.seed, f"step{step}"))
        indices = training.batch_indices(config, len(bank), step)

        def residual(source):
            hidden, mask, _, _, _ = source.batch(indices)
            memory = source.memory_batch(indices)
            return hand_route(hidden, mask, *(memory or ()))[0]

        _, _, base, targets, _ = bank.batch(indices)
        task = torch.nn.functional.cross_entropy(base + residual(bank), targets)
        penalty = residual(mismatch).square().mean()
        total = task + 0.3 * penalty
        optimizers[1].zero_grad(set_to_none=True)
        total.backward()
        torch.nn.utils.clip_grad_norm_(list(hand_route.parameters()), config.max_grad_norm)
        optimizers[1].step()
        assert receipts[step - 1]["mismatch_penalty"] == float(penalty.detach())
        assert receipts[step - 1]["total_loss"] == float(total.detach())
        assert receipts[step - 1]["task_loss"] == float(task.detach())
    named = [training.trainable(r) for r in (engine_route, hand_route, plain_route)]
    assert training.fingerprint(named[0]) == training.fingerprint(named[1])
    plain = gating_config(0.0)
    plain_receipts = [
        training.update(plain_route, None, optimizers[2], bank, plain, step) for step in (1, 2, 3)
    ]
    assert "mismatch_penalty" not in plain_receipts[0]
    assert training.fingerprint(named[2]) != training.fingerprint(named[0])


def test_content_gating_checks_its_options():
    bank, mismatch = gating_banks(False)
    route = d1_route(composition, 1)
    optimizer = training.optimizer_for(training.trainable(route), 1e-3, 0.0)
    for config, other in (
        (gating_config(0.0), mismatch),
        (gating_config(0.3), None),
        (gating_config(-0.3), mismatch),
    ):
        with pytest.raises(ValueError, match="mismatch_weight"):
            training.update(route, None, optimizer, bank, config, 1, other)
    short = training.FeatureBank(*d1_features(rows=12, seed=22))
    with pytest.raises(ValueError, match="row for row"):
        training.update(route, None, optimizer, bank, gating_config(0.3), 1, short)


def test_content_gating_quiets_the_route_on_memory_without_the_answer():
    """Planted as the deferred-memory test: the memory states the answer. A memory that
    does not (a larger isotropic one) still moves an ungated route's answers; with gating
    on such memories the route moves them far less and still reads the real memory."""
    generator = torch.Generator().manual_seed(17)
    pairs, hidden = 48, 16
    rows = 2 * pairs
    first = torch.randint(0, 2, (pairs,), generator=generator)
    labels = torch.stack([first, 1 - first], 1).flatten()
    direction = torch.randn(hidden, generator=generator)
    queries = torch.randn(pairs * 3, hidden, generator=generator).to(torch.bfloat16)
    query_offsets, query_segments = torch.arange(0, pairs * 3 + 1, 3), torch.arange(rows) // 2
    memories = 0.5 * torch.randn(rows * 2, hidden, generator=generator)
    memories[1::2] += 2.0 * (2 * labels[:, None] - 1) * direction
    blank = 2.0 * torch.randn(rows * 2, hidden, generator=generator)
    states = torch.cat([memories, blank]).to(torch.bfloat16)
    offsets = torch.arange(0, rows * 4 + 1, 2)
    base, worlds = torch.zeros(rows, 2), torch.arange(rows) // 2

    def bank(n, memory_offset=0):
        rows_bank = training.FeatureBank(
            queries, query_offsets, base[:n], labels[:n], worlds[:n], segments=query_segments[:n]
        )
        return rows_bank.with_memory((states, offsets, torch.arange(n) + memory_offset))

    measured = {}
    for weight in (0.0, 1.0):
        route = composition.DeliberationRoute(
            hidden, 43, (6, 7), steps=1, seed=2, workspace_dim=8, heads=2, rank=4, dropout=0.0
        )
        config = training.TrainConfig(
            seed=2,
            updates=240,
            batch_size=16,
            learning_rate=3e-3,
            weight_decay=0.0,
            max_grad_norm=1.0,
            workspace_loss_weight=0.0,
            loss_tokens_per_row=0,
            loss_tokens_per_batch=0,
            spectral_every=1,
            mismatch_weight=weight,
        )
        optimizer = training.optimizer_for(training.trainable(route), 3e-3, 0.0)
        train = bank(64)  # pairs 0-31; pairs 32-47 are never trained on
        mismatch = bank(64, memory_offset=rows) if weight else None
        for step in range(1, config.updates + 1):
            training.update(route, None, optimizer, train, config, step, mismatch)
        read = training.evaluate(route, bank(rows))[64:]
        unread = training.evaluate(route, bank(rows, memory_offset=rows))[64:]
        measured[weight] = (
            float((read.argmax(1) == labels[64:]).float().mean()),
            float((unread[:, 1] - unread[:, 0]).abs().mean()),
        )
    (plain_accuracy, plain_moved), (gated_accuracy, gated_moved) = measured[0.0], measured[1.0]
    assert plain_accuracy >= 0.9 and gated_accuracy >= 0.9, measured
    assert gated_moved < 0.5 * plain_moved, measured


# ---- a stable end of training (V20 A5): an engine option on the trainer --------------


def test_learning_rate_decays_linearly_after_decay_from():
    config = gating_config(0.0, updates=512, learning_rate=3e-4, decay_from=256)
    assert training.learning_rate_at(config, 1) == training.learning_rate_at(config, 256) == 3e-4
    assert training.learning_rate_at(config, 257) == 3e-4 * 256 / 257
    assert training.learning_rate_at(config, 512) == 3e-4 / 257
    constant = gating_config(0.0, updates=512, learning_rate=3e-4)
    assert {training.learning_rate_at(constant, s) for s in (1, 300, 512)} == {3e-4}


@pytest.mark.parametrize("weight", [0.0, 0.3])
def test_decay_sets_each_update_learning_rate(weight):
    """With ``decay_from`` the update is the same update run at ``learning_rate_at``."""
    bank, mismatch = gating_banks(False)
    config = gating_config(weight, updates=6, decay_from=2)
    routes = [d1_route(composition, 2, seed=3) for _ in range(2)]
    open_paths(*routes, names=["adapter.up.weight", "gate.weight"])
    optimizers = [
        training.optimizer_for(training.trainable(r), config.learning_rate, config.weight_decay)
        for r in routes
    ]
    plain = gating_config(weight, updates=6)
    other = mismatch if weight else None
    for step in range(1, 7):
        engine = training.update(routes[0], None, optimizers[0], bank, config, step, other)
        for group in optimizers[1].param_groups:
            group["lr"] = training.learning_rate_at(config, step)
        hand = training.update(routes[1], None, optimizers[1], bank, plain, step, other)
        assert engine == hand
    fingerprints = [training.fingerprint(training.trainable(r)) for r in routes]
    assert fingerprints[0] == fingerprints[1]
    assert [g["lr"] for g in optimizers[0].param_groups] == [config.learning_rate / 5] * 2
    with pytest.raises(ValueError, match="decay_from"):
        training.update(
            routes[0],
            None,
            optimizers[0],
            bank,
            gating_config(weight, updates=6, decay_from=6),
            1,
            other,
        )
