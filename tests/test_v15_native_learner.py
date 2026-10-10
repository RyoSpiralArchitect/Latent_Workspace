from __future__ import annotations

import copy
import random
import sys
from pathlib import Path

import numpy as np
import pytest
import torch
from transformers.optimization import Adafactor

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import probe_v15_full_update_backward as probe  # noqa: E402
import run_v15_5_native_answer as old  # noqa: E402
from test_v15_full_update import CONTRACT, SPAN, Store, tiny  # noqa: E402

from latent_workspace_ft_v10.v15_native_learner import (  # noqa: E402
    CompleteCPUWindow,
    V15NativeLearner,
    create_reader,
    reader_descriptor,
    restore_rng,
    rng_state,
    tree_hash,
)

OPT = dict(
    bridge_lr=1e-4,
    bridge_weight_decay=0.01,
    base_lr=2e-7,
    base_weight_decay=0.0,
    max_grad_norm_per_family=1.0,
)
META = {"source": "tiny-only", "plan": "fixed", "original_base": "tiny"}


@pytest.fixture(autouse=True)
def threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(previous)


def owner(dtype=torch.float32, full=True, reader="query_modulated"):
    base, old_bridge, _ = tiny(dtype, up_nonzero=True)
    bridge = create_reader(16, dict(workspace_dim=8, heads=2, slots=3, max_delta_norm=1), reader)
    bridge.load_state_dict(old_bridge.state_dict())
    base.requires_grad_(full)
    return V15NativeLearner(base, bridge, full_update=full, optimizer_config=OPT, boundary=1)


class OwnedStore(Store):
    def __init__(self, learner):
        super().__init__(learner.base)
        self.learner = learner

    def get(self, ids):
        return self.learner.prefix(ids)

    def write(self, bridge, world, side):
        ids = (1, 8, 9) if side == 0 else (1, 9, 8) if side == 1 else (1, 10, 11)
        hidden = self.learner.context(ids)
        return bridge.write_memory(hidden, torch.ones(hidden.shape[:2], dtype=torch.long))


def objective(learner, query):
    fn = probe.full_native_answer_terms if learner.full_update else old.native_answer_terms
    return probe.pair_objective(learner.pipeline, OwnedStore(learner), 0, query, CONTRACT, 0.0, fn)[
        0
    ]


def update(learner):
    learner.begin_window(("q0", "q1"))
    for q in range(2):
        learner.backward_pair(f"q{q}", objective(learner, q))
    return learner.step()


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("full", [False, True])
def test_complete_window_matches_independent_optimizer_reference(dtype, full):
    actual, reference = owner(dtype, full), owner(dtype, full)
    accumulated = {}
    for q in range(2):
        objective(reference, q).backward()
        for name, p in reference.named:
            value = p.grad.detach().cpu()
            if name in accumulated:
                accumulated[name].add_(value)
            else:
                accumulated[name] = value.clone()
            p.grad = None
    for name, p in reference.bridge_named:
        p.grad = accumulated[f"bridge.{name}"]
    torch.nn.utils.clip_grad_norm_(
        [p for _, p in reference.bridge_named], 1, error_if_nonfinite=True
    )
    bridge_optimizer = torch.optim.AdamW(reference.bridge.parameters(), lr=1e-4, weight_decay=0.01)
    if full:
        master = {
            name: torch.nn.Parameter(p.detach().float().clone()) for name, p in reference.base_named
        }
        optimizer = Adafactor(
            list(master.values()),
            lr=2e-7,
            eps=(1e-30, 1e-3),
            clip_threshold=1.0,
            decay_rate=-0.8,
            beta1=None,
            weight_decay=0.0,
            scale_parameter=False,
            relative_step=False,
            warmup_init=False,
        )
        for name, p in master.items():
            p.grad = accumulated[f"base.{name}"].float()
        torch.nn.utils.clip_grad_norm_(list(master.values()), 1, error_if_nonfinite=True)
        optimizer.step()
        with torch.no_grad():
            for name, p in reference.base_named:
                p.copy_(master[name].to(dtype))
    bridge_optimizer.step()
    receipt = update(actual)
    assert receipt["transfer"]["spill_count"] == 2
    assert receipt["transfer"]["consumed_parameter_count"] == len(actual.named)
    assert tree_hash(actual.base.state_dict()) == tree_hash(reference.base.state_dict())
    assert tree_hash(actual.bridge.state_dict()) == tree_hash(reference.bridge.state_dict())
    if full:
        assert tree_hash(actual.masters) == tree_hash(master)
        assert tree_hash(actual.base_optimizer.state_dict()) == tree_hash(optimizer.state_dict())
    assert tree_hash(actual.bridge_optimizer.state_dict()) == tree_hash(
        bridge_optimizer.state_dict()
    )


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("full", [False, True])
def test_save_restore_next_update_exact_including_rng(tmp_path, dtype, full):
    learner = owner(dtype, full)
    update(learner)
    path = tmp_path / "step1.pt"
    receipt = learner.save(path, META)
    payload = torch.load(path, map_location="cpu", weights_only=True)
    assert tree_hash(payload) == receipt["state_sha256"]
    update(learner)
    expected = tree_hash(learner.payload(META))
    expected_base = tree_hash(learner.base.state_dict())
    rng_after = (random.random(), np.random.rand(), torch.rand(3))
    loaded_base = owner(dtype, full)
    loaded = V15NativeLearner.restore(
        loaded_base.base, loaded_base.bridge, payload, expected_metadata=META
    )
    update(loaded)
    assert tree_hash(loaded.payload(META)) == expected
    assert tree_hash(loaded.base.state_dict()) == expected_base
    assert (random.random(), np.random.rand()) == rng_after[:2]
    assert torch.equal(torch.rand(3), rng_after[2])
    with pytest.raises(FileExistsError):
        learner.save(path, META)


def test_sub_bf16_update_is_kept_in_fp32_master():
    learner = owner(torch.bfloat16)
    name = "model.norm.weight"
    original = dict(learner.base_named)[name].detach().clone()
    first = None
    for step in range(2):
        learner.begin_window((0,))
        learner.backward_pair(0, sum(p.float().sum() for _, p in learner.named))
        receipt = learner.step()
        row = next(r for r in receipt["base_changes"] if r["name"] == name)
        assert row["master_changed"] and row["native_changed_elements"] == 0
        assert torch.equal(dict(learner.base_named)[name], original)
        assert torch.all(learner.masters[name] < original.float())
        if step:
            assert torch.all(learner.masters[name] < first)
        first = learner.masters[name].detach().clone()


@pytest.mark.parametrize("full", [False, True])
def test_live_features_and_current_zero_identity_across_update(full):
    learner = owner(full=full)
    before = learner.prefix(SPAN.prefix_ids).detach().clone()
    base_hash = tree_hash(learner.base.state_dict())
    update(learner)
    after = learner.prefix(SPAN.prefix_ids)
    assert (not torch.equal(before, after)) == full
    assert (tree_hash(learner.base.state_dict()) != base_hash) == full
    with torch.no_grad():
        memory, mask = OwnedStore(learner).write(learner.bridge, 0, 0)
        output = learner.pipeline(
            after, torch.zeros_like(memory), mask, prefix_ids=SPAN.prefix_ids, span=SPAN
        )
        ids = torch.tensor([SPAN.prefix_ids])
        ordinary = learner.base(ids, attention_mask=torch.ones_like(ids), use_cache=False).logits
        assert torch.equal(ordinary, output.readout.logits)


def test_incomplete_out_of_order_duplicate_and_stale_fail_before_update():
    learner = owner()
    before = tree_hash(learner.base.state_dict())
    with pytest.raises(ValueError, match="Unique"):
        learner.begin_window((0, 0))
    learner.begin_window((0, 1))
    with pytest.raises(ValueError, match="Complete"):
        learner.step()
    with pytest.raises(ValueError, match="ordering"):
        learner.backward_pair(1, objective(learner, 0))
    learner.backward_pair(0, objective(learner, 0))
    with pytest.raises(ValueError, match="ordering"):
        learner.backward_pair(0, objective(learner, 0))
    with pytest.raises(ValueError, match="Checkpoint"):
        learner.payload(META)
    assert tree_hash(learner.base.state_dict()) == before


@pytest.mark.parametrize(
    "failure", ["missing", "duplicate", "reordered", "trainability", "master_dtype"]
)
def test_ownership_fails_closed(failure):
    learner = owner()
    params = learner.bridge_optimizer.param_groups[0]["params"]
    if failure == "missing":
        params.pop()
    elif failure == "duplicate":
        params[-1] = params[0]
    elif failure == "reordered":
        params.reverse()
    elif failure == "trainability":
        learner.base_named[0][1].requires_grad_(False)
    else:
        name = next(iter(learner.masters))
        learner.masters[name].data = learner.masters[name].data.bfloat16()
    with pytest.raises(ValueError):
        learner.begin_window((0,))


@pytest.mark.parametrize(
    "failure",
    ["metadata", "reader", "heads", "nonfinite", "optimizer_policy", "alias", "native_schema"],
)
def test_restore_rejects_incompatible_state(failure):
    learner = owner()
    update(learner)
    payload = copy.deepcopy(learner.payload(META))
    if failure == "metadata":
        payload["metadata"] = {}
    elif failure == "reader":
        payload["reader"]["class"] = "PrecisionAwareWorkspaceBridge"
    elif failure == "heads":
        payload["reader"]["heads"] = 1
    elif failure == "nonfinite":
        next(iter(payload["base_masters"].values())).view(-1)[0] = float("nan")
    elif failure == "optimizer_policy":
        payload["base_optimizer"]["param_groups"][0]["scale_parameter"] = True
    elif failure == "alias":
        payload["base_aliases"] = {}
    else:
        payload["native_schema"] = {}
    fresh = owner()
    with pytest.raises(ValueError):
        V15NativeLearner.restore(fresh.base, fresh.bridge, payload, expected_metadata=META)


def test_native_master_drift_cannot_be_saved():
    learner = owner()
    with torch.no_grad():
        learner.base_named[0][1].add_(1)
    with pytest.raises(ValueError, match="cast identity"):
        learner.payload(META)


def test_cpu_window_requires_all_parameter_gradients_and_exact_spill_count():
    a, b = torch.nn.Parameter(torch.ones(2)), torch.nn.Parameter(torch.ones(3))
    window = CompleteCPUWindow([("a", a), ("b", b)], merge_device="cpu")
    a.grad = torch.ones_like(a)
    window.spill()
    with pytest.raises(ValueError, match="Incomplete"):
        window.take(2)
    with pytest.raises(ValueError, match="Missing"):
        window.take(1)


def test_reader_semantics_are_not_inferred_from_compatible_weight_keys():
    legacy, candidate = owner(reader="legacy"), owner(reader="query_modulated")
    assert set(legacy.bridge.state_dict()) == set(candidate.bridge.state_dict())
    assert reader_descriptor(legacy.bridge) != reader_descriptor(candidate.bridge)


def test_rng_hash_and_restore_roundtrip():
    before = rng_state()
    samples = (random.random(), np.random.rand(), torch.rand(4))
    restore_rng(before)
    assert (random.random(), np.random.rand()) == samples[:2]
    assert torch.equal(torch.rand(4), samples[2])
