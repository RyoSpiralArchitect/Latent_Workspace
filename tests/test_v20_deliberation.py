"""Tiny harness for the V20 Deliberation pilot (D1), not a real-model receipt."""

import copy
import os
from argparse import Namespace
from math import comb

import pytest
import torch
from test_v15_full_update import tiny

from latent_workspace_ft_v10 import v20_deliberation as deliberation
from latent_workspace_ft_v10.engine import CausalBroadcastLatentWorkspace
from latent_workspace_ft_v10.workspace_core import LowRankWorkspaceLogitAdapter
from scripts import run_v16_adapter_migration as core
from scripts import run_v20_deliberation_pilot as run
from scripts import verify_v20_deliberation_pilot as verifier

DEVICE = os.environ.get("LATENT_V20_TEST_DEVICE", "cpu")
PLAN = run.read(run.ROOT / run.PLAN)
SMALL = dict(workspace_dim=8, heads=2, rank=4)


@pytest.fixture(autouse=True)
def setup():
    core.load_runtime()
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


def route(steps, seed=5):
    return deliberation.DeliberationRoute(16, 43, (6, 7), steps=steps, seed=seed, **SMALL)


def bank(rows=48, seed=0):
    generator = torch.Generator().manual_seed(seed)
    lengths = [4 + (i % 3) for i in range(rows)]
    offsets = torch.tensor([0, *torch.tensor(lengths).cumsum(0).tolist()])
    hidden = torch.randn(int(offsets[-1]), 16, generator=generator).to(torch.bfloat16)
    base = torch.randn(rows, 2, generator=generator)
    targets = torch.randint(0, 2, (rows,), generator=generator)
    return deliberation.FeatureBank(hidden, offsets, base, targets, torch.arange(rows) // 16)


def config(**changes):
    values = dict(
        seed=3,
        updates=6,
        batch_size=8,
        learning_rate=3e-3,
        weight_decay=0.01,
        max_grad_norm=1.0,
        workspace_loss_weight=0.0,
        loss_tokens_per_row=4,
        loss_tokens_per_batch=16,
        spectral_every=2,
    )
    values.update(changes)
    return deliberation.TrainConfig(**values)


def nonzero_up(module, seed=11):
    """Open the zero-initialized v4 residual and v5 update paths with seeded values.

    At initialization the lattice is an identity (its output projections are
    zero), so latent steps can only matter once these weights are nonzero.
    """
    generator = torch.Generator().manual_seed(seed)
    lattice = module.lattice
    with torch.no_grad():
        for parameter in (
            module.adapter.up.weight,
            lattice.attention.out.weight,
            lattice.candidate_out.weight,
            lattice.candidate_out.bias,
            lattice.anchor_projection.weight,
        ):
            parameter.copy_(0.3 * torch.randn(parameter.shape, generator=generator))


def test_arms_share_every_common_parameter():
    four, one, readout = route(4), route(1), route(0)
    for other in (one, readout):
        for name, parameter in four.named_parameters():
            mine = dict(other.named_parameters())[name]
            if name == "lattice.step_embeddings":
                assert torch.equal(mine, parameter[: mine.shape[0]])
            elif "step_scales" in name:
                assert torch.equal(mine, parameter[: mine.shape[0]])
            else:
                assert torch.equal(mine, parameter), name
    assert not torch.equal(
        route(4, seed=6).lattice.input_projection.weight, four.lattice.input_projection.weight
    )


def test_route_reuses_the_historical_modules_and_starts_at_base():
    four = route(4)
    assert type(four.lattice) is CausalBroadcastLatentWorkspace
    assert type(four.adapter) is LowRankWorkspaceLogitAdapter
    hidden, mask = torch.randn(3, 5, 16), torch.ones(3, 5, dtype=torch.long)
    for steps in (0, 1, 4):
        delta, _, _, gate = route(steps)(hidden, mask)
        assert torch.equal(delta, torch.zeros_like(delta))
        assert torch.allclose(gate, torch.sigmoid(torch.tensor(-2.0)).expand_as(gate))


def test_candidate_columns_equal_the_full_v4_adapter():
    four = route(4).eval()
    nonzero_up(four)
    hidden, mask = torch.randn(2, 6, 16), torch.ones(2, 6, dtype=torch.long)
    delta, latents, _, gate = four(hidden, mask)
    full = four.adapter(latents[:, -1, -1])
    assert torch.allclose(delta, gate * full[:, [6, 7]], atol=1e-6, rtol=0)


def test_readout_control_never_runs_the_lattice(monkeypatch):
    readout = route(0)

    def refuse(*_args, **_kwargs):
        raise AssertionError("readout must not run latent steps")

    monkeypatch.setattr(readout.lattice, "forward", refuse)
    delta, latents, anchor, _ = readout(torch.randn(2, 4, 16), torch.ones(2, 4, dtype=torch.long))
    assert latents is None and anchor.shape == (2, 4, 8) and delta.shape == (2, 2)
    with pytest.raises(ValueError, match="Truncation"):
        with readout.truncated(1):
            pass


def test_right_padding_does_not_change_a_row():
    four = route(4).eval()
    nonzero_up(four)
    hidden = torch.randn(2, 7, 16)
    mask = torch.ones(2, 7, dtype=torch.long)
    mask[0, 4:] = 0
    batched, _, _, _ = four(hidden, mask)
    alone, _, _, _ = four(hidden[:1, :4], mask[:1, :4])
    assert torch.allclose(batched[:1], alone, atol=1e-6, rtol=0)


def test_truncation_equals_a_shorter_lattice_of_the_same_seed():
    four, two = route(4).eval(), route(2).eval()
    nonzero_up(four)
    nonzero_up(two)
    hidden, mask = torch.randn(2, 5, 16), torch.ones(2, 5, dtype=torch.long)
    full, _, _, _ = four(hidden, mask)
    with four.truncated(4):
        same, _, _, _ = four(hidden, mask)
    with four.truncated(2):
        short, _, _, _ = four(hidden, mask)
    assert torch.equal(full, same)
    assert torch.equal(short, two(hidden, mask)[0])
    assert four.lattice.steps == 4
    with pytest.raises(ValueError, match="Truncation"):
        with four.truncated(5):
            pass


def test_batches_cover_every_row_once_per_epoch():
    settings = config(batch_size=10)
    first = [i for step in range(1, 5) for i in deliberation.batch_indices(settings, 45, step)]
    second = [i for step in range(5, 9) for i in deliberation.batch_indices(settings, 45, step)]
    assert len(first) == len(set(first)) == 40 and set(first) <= set(range(45))
    assert first != second
    assert first == [i for s in range(1, 5) for i in deliberation.batch_indices(settings, 45, s)]


def train(steps, seed=5, lw=0.0, until=6, stop=None):
    module = route(steps, seed)
    loss = deliberation.workspace_loss(seed, 8) if lw else None
    named = deliberation.trainable(module, loss)
    settings = config(workspace_loss_weight=lw)
    optimizer = deliberation.optimizer_for(named, settings.learning_rate, settings.weight_decay)
    features, receipts, prints = bank(), [], {}
    for step in range(1, until + 1):
        receipts.append(deliberation.update(module, loss, optimizer, features, settings, step))
        prints[step] = deliberation.fingerprint(named)
        if step == stop:
            state = dict(
                route=copy.deepcopy(module.state_dict()),
                loss=None if loss is None else copy.deepcopy(loss.state_dict()),
                optimizer=copy.deepcopy(optimizer.state_dict()),
            )
            return state, receipts, prints
    return None, receipts, prints


@pytest.mark.parametrize("steps,lw", [(4, 0.0), (1, 0.0), (0, 0.0), (4, 0.02)])
def test_updates_are_deterministic_and_replay_exactly_from_a_checkpoint(steps, lw):
    _, receipts, prints = train(steps, lw=lw)
    _, again, prints_again = train(steps, lw=lw)
    assert receipts == again and prints == prints_again
    assert len(set(prints.values())) == len(prints)
    state, _, _ = train(steps, lw=lw, stop=3)
    module = route(steps)
    loss = deliberation.workspace_loss(5, 8) if lw else None
    module.load_state_dict(state["route"])
    if loss is not None:
        loss.load_state_dict(state["loss"])
    named = deliberation.trainable(module, loss)
    settings = config(workspace_loss_weight=lw)
    optimizer = deliberation.optimizer_for(named, settings.learning_rate, settings.weight_decay)
    optimizer.load_state_dict(state["optimizer"])
    assert deliberation.fingerprint(named) == prints[3]
    receipt = deliberation.update(module, loss, optimizer, bank(), settings, 4)
    assert receipt == receipts[3] and deliberation.fingerprint(named) == prints[4]


def test_workspace_loss_arm_trains_its_own_parameters():
    module, loss = route(4), deliberation.workspace_loss(5, 8)
    named = deliberation.trainable(module, loss)
    assert any(n.startswith("workspace_loss.") for n, _ in named)
    before = {n: p.detach().clone() for n, p in named}
    settings = config(workspace_loss_weight=0.02)
    optimizer = deliberation.optimizer_for(named, settings.learning_rate, settings.weight_decay)
    for step in (1, 2):
        receipt = deliberation.update(module, loss, optimizer, bank(), settings, step)
        assert receipt["workspace_loss"] > 0
    assert any(not torch.equal(before[n], p) for n, p in named if n.startswith("workspace_loss."))


def test_evaluate_matches_base_at_initialization_and_truncates():
    features = bank()
    four = route(4)
    assert torch.equal(deliberation.evaluate(four, features), features.base_logits)
    nonzero_up(four)
    full = deliberation.evaluate(four, features)
    short = deliberation.evaluate(four, features, steps=1)
    assert full.shape == short.shape == (48, 2) and not torch.equal(full, short)


def test_statistics_are_exact():
    adapted = torch.tensor([[0.0, 1.0], [1.0, 1.0], [2.0, 0.0]])
    assert deliberation.correct_flags(adapted, [1, 0, 0]) == [True, False, True]
    assert deliberation.binomial_upper(5, 5) == 1 / 32
    assert deliberation.binomial_upper(0, 0) == 1.0
    assert deliberation.binomial_upper(7, 10) == sum(comb(10, i) for i in range(7, 11)) / 1024
    sign = deliberation.world_sign([1, 1, 0, 1, 0], [0, 1, 0, 0, 1], [0, 0, 1, 1, 2])
    assert sign == {"positive": 2, "negative": 1, "zero": 0, "p_one_sided": 0.5}
    rule = {"minimum_accuracy_gain": 0.02, "alpha": 0.01}
    worlds = [w for w in range(12) for _ in range(4)]
    better = [1] * 48
    worse = [1, 1, 1, 0] * 12
    passed = deliberation.gain(better, worse, worlds, rule)
    assert passed["passed"] and passed["accuracy_gain"] == 0.25
    assert passed["world_sign"]["p_one_sided"] == 1 / 4096
    assert not deliberation.gain(worse, better, worlds, rule)["passed"]
    labels = run.VERDICTS
    yes, no = {"passed": True}, {"passed": False}
    assert deliberation.verdict([yes] * 3, [yes] * 3, labels) == labels[0]
    assert deliberation.verdict([yes] * 3, [yes, no, yes], labels) == labels[1]
    assert deliberation.verdict([yes, no, yes], [yes] * 3, labels) == labels[2]


@pytest.mark.parametrize(
    "path,value",
    [
        (("training", "updates"), 511),
        (("endpoints", "alpha"), 0.05),
        (("arms", 0, "steps"), 3),
        (("winner",), "k4"),
    ],
)
def test_plan_hash_and_semantics_reject_drift(path, value):
    run.validate_plan(PLAN)
    changed = copy.deepcopy(PLAN)
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError, match="plan"):
        run.validate_plan(changed)


def test_roles_follow_the_plan():
    names = run.roles(PLAN)
    assert names[0] == "extract" and names[-1] == "replay" and len(names) == 14
    spec, seed = run.parse_role(PLAN, "k4_lw_s2")
    assert spec["name"] == "k4_lw" and spec["workspace_loss_weight"] == 0.02
    assert seed == PLAN["seeds"][1]
    rule = PLAN["replay"]
    assert f"{rule['arm']}_s{PLAN['seeds'].index(rule['seed']) + 1}" in names


def fake_render(calls):
    def render(_tokenizer, *, query, context, renderer, cue, information):
        calls.append((renderer, cue, information, context))
        ids = [1, 2, 3 + len(context) % 5, 4 + len(query) % 7]
        return dict(prompt_ids=ids, candidate_ids=list(PLAN["candidate_ids"]))

    return render


def test_rows_render_facts_inline_in_fixed_order(monkeypatch):
    old = core.legacy.old
    calls = []
    monkeypatch.setattr(old, "render_case", fake_render(calls))
    records = run.v19().load_records(PLAN)["dev"]
    rows = run.render_rows(old, None, records, PLAN)
    assert len(rows) == 16 * len(records) == len(calls)
    assert {c[:3] for c in calls} == {("native_chat", "present", "inline")}
    assert calls[0][3] == old.canonical_facts(records[0]["contexts"][0])
    assert calls[8][3] == old.canonical_facts(records[0]["contexts"][1])
    first = rows[:16]
    assert [(r["side"], r["query"]) for r in first] == [(s, q) for s in (0, 1) for q in range(8)]
    assert [r["label"] for r in first] == records[0]["answers"][0] + records[0]["answers"][1]
    assert [r["affected"] for r in first[:8]] == [True, True] + [False] * 6
    assert [r["hop"] for r in first[:8]] == records[0]["hop_distances"]
    assert {r["wording"] for r in rows} == {"ranked_above", "outrank"}


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_extraction_keeps_native_parity_and_feeds_training(dtype):
    base, _, _ = tiny(dtype)
    base.to(DEVICE).eval().requires_grad_(False)
    readout = core.legacy.old.NativeWorkspaceReadout(base.lm_head)
    generator = torch.Generator().manual_seed(9)
    rows = [
        dict(
            prompt_ids=torch.randint(1, 43, (5 + i % 3,), generator=generator).tolist(),
            candidate_ids=[6, 7],
            label=i % 2,
            world=i // 4,
        )
        for i in range(12)
    ]
    with torch.no_grad():
        tensors = run.extract_split(torch, base, readout, rows, lambda *_a, **_k: None, "tiny")
    assert tensors["offsets"].tolist()[-1] == tensors["hidden"].shape[0]
    for i, row in enumerate(rows):
        ids = torch.tensor([row["prompt_ids"]], device=DEVICE)
        mask = torch.ones_like(ids)
        with torch.no_grad():
            hidden = base.model(ids, attention_mask=mask, use_cache=False).last_hidden_state
            logits = base(ids, attention_mask=mask, use_cache=False).logits[0, -1, [6, 7]]
        hidden, logits = hidden[0].cpu(), logits.float().cpu()
        start, end = tensors["offsets"][i : i + 2].tolist()
        assert torch.equal(tensors["hidden"][start:end], hidden)
        assert torch.equal(tensors["base_logits"][i], logits)
    features = deliberation.FeatureBank(
        tensors["hidden"].cpu(),
        tensors["offsets"],
        tensors["base_logits"],
        tensors["targets"],
        tensors["worlds"],
    )
    module = route(4)
    named = deliberation.trainable(module)
    settings = config(batch_size=4)
    optimizer = deliberation.optimizer_for(named, settings.learning_rate, settings.weight_decay)
    for step in (1, 2):
        deliberation.update(module, None, optimizer, features, settings, step)
    assert deliberation.evaluate(module, features).shape == (12, 2)


def tiny_plan():
    plan = copy.deepcopy(PLAN)
    plan["route"].update(hidden_dim=16, vocab_size=43, workspace_dim=8, attention_heads=2, rank=4)
    plan["candidate_ids"] = [6, 7]
    plan["training"].update(
        updates=6, batch_size=8, loss_tokens_per_row=4, loss_tokens_per_batch=16, spectral_every=2
    )
    plan["checkpoint_steps"] = [3]
    plan["dev_evaluation_steps"] = [0, 3, 6]
    plan["final_evaluation_steps"] = [0, 6]
    plan["endpoints"]["step"] = 6
    plan["replay"].update(from_step=3, execute_step=4)
    return plan


def test_arm_role_writes_receipts_and_replays_exactly(tmp_path):
    plan = tiny_plan()
    banks = {"train": bank(48, 1), "dev": bank(32, 2), "final": bank(32, 3)}
    raw, checkpoints = tmp_path / "raw", tmp_path / "checkpoints"
    role = f"{plan['replay']['arm']}_s1"
    out = raw / role
    out.mkdir(parents=True)
    run.v19().write_new(out / "STARTED.json", {"pid": -1})
    outcome = run.train_run(
        torch, Namespace(output=out, checkpoints=checkpoints), plan, role, banks
    )
    assert set(outcome["fingerprints"]) == {0, 3, 4, 6}
    for name in (
        "eval_dev_step0",
        "eval_final_step0",
        "eval_dev_step6",
        "eval_final_step6",
        "eval_final_step6_k1",
        "eval_final_step6_k3",
    ):
        assert (out / f"{name}.json.gz").exists(), name
    assert (out / "CHECKPOINT_step3.json").exists() and (checkpoints / role / "step3.pt").exists()
    (raw / "replay").mkdir()
    report = run.replay_run(
        torch, Namespace(output=raw / "replay", checkpoints=checkpoints), plan, banks
    )
    assert report["exact"] and report["replayed_fingerprint"] == outcome["fingerprints"][4]


def test_endpoints_apply_the_frozen_rule(tmp_path):
    plan = copy.deepcopy(PLAN)
    rows = [
        dict(world=w, label=1, base_logits=[0.0, -1.0] if q < 4 else [0.0, 1.0])
        for w in range(128)
        for q in range(16)
    ]
    (tmp_path / "extract").mkdir()
    run.v19().write_gz(tmp_path / "extract" / "ROWS_final.json.gz", rows)
    accuracy = {"k4": 16, "k1": 12, "k4_lw": 16, "readout": 12}
    for role in run.seed_roles(plan):
        arm = role.rsplit("_s", 1)[0]
        (tmp_path / role).mkdir()
        correct = [q < accuracy[arm] for _ in range(128) for q in range(16)]
        run.v19().write_gz(
            tmp_path / role / f"eval_final_step{plan['endpoints']['step']}.json.gz",
            {"correct": correct},
        )
    result = run.endpoints_for(tmp_path, plan)
    assert result["verdict"] == "DELIBERATION_STEP_GAIN"
    seed = result["per_seed"][0]
    assert seed["base_inline_accuracy"] == 0.75 and seed["accuracy"]["k4"] == 1.0
    assert seed["step_gain"]["world_sign"]["positive"] == 128


def tiny_rows(features):
    rows = []
    for i in range(len(features)):
        start, end = features.offsets[i : i + 2].tolist()
        query = i % 8
        rows.append(
            dict(
                world=int(features.worlds[i]),
                side=(i % 16) // 8,
                query=query,
                label=int(features.targets[i]),
                affected=query < 2,
                hop=1 + query % 5,
                wording="outrank" if query % 2 else "ranked_above",
                prompt_ids=list(range(end - start)),
                candidate_ids=[6, 7],
                base_logits=features.base_logits[i].tolist(),
            )
        )
    return rows


def test_offline_verifier_accepts_what_the_runner_writes(tmp_path):
    plan = tiny_plan()
    banks = {"train": bank(48, 1), "dev": bank(32, 2), "final": bank(32, 3)}
    for split, features in banks.items():
        plan["data"][split]["world_pairs"] = len(features) // 16
    raw, checkpoints = tmp_path / "raw", tmp_path / "checkpoints"
    (raw / "extract").mkdir(parents=True)
    rows = {split: tiny_rows(features) for split, features in banks.items()}
    for split in run.SPLITS:
        run.v19().write_gz(raw / "extract" / f"ROWS_{split}.json.gz", rows[split])
    receipts = {split: run.split_receipt(rows[split], "torch.bfloat16") for split in run.SPLITS}
    roles = {"extract": ({"pid": 100}, {"outcome": {"splits": receipts}}, [])}
    for pid, role in enumerate(run.seed_roles(plan), start=101):
        out = raw / role
        out.mkdir()
        run.v19().write_new(out / "STARTED.json", {"pid": pid})
        run.train_run(torch, Namespace(output=out, checkpoints=checkpoints), plan, role, banks)
        roles[role] = ({"pid": pid}, {}, [])
    (raw / "replay").mkdir()
    report = run.replay_run(
        torch, Namespace(output=raw / "replay", checkpoints=checkpoints), plan, banks
    )
    roles["replay"] = ({"pid": report["replay_pid"]}, {}, [])
    run.v19().write_new(raw / "ENDPOINTS.json", run.endpoints_for(raw, plan))
    result = verifier.verify_results(raw, plan, roles, checkpoints, deliberation)
    assert result["verdict"] in run.VERDICTS and result["replay_exact"]
    assert set(result["descriptive"]) == {"base_inline", *run.seed_roles(plan)}
    assert set(result["descriptive"]["k4_s1"]["truncated_final_accuracy"]) == {"k1", "k2", "k3"}
    path = raw / "k1_s2" / "eval_final_step6.json.gz"
    saved = run.v19().read_gz(path)
    saved["correct"][0] = not saved["correct"][0]
    path.unlink()
    run.v19().write_gz(path, saved)
    with pytest.raises(ValueError, match="correctness"):
        verifier.verify_results(raw, plan, roles, checkpoints, deliberation)
