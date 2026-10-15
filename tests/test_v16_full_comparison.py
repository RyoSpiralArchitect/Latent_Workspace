"""Tiny harness integration, not a real-model scientific receipt."""

import copy
import os
import random

import numpy as np
import pytest
import torch
from test_v15_full_update import tiny
from test_v15_native_learner import OPT
from test_v15_native_runner import make_store

from latent_workspace_ft_v10.adapter_native_learner_v2 import AdapterNativeLearnerV2
from latent_workspace_ft_v10.native_training_preparation import (
    prepare_native_gradient_checkpointing,
)
from latent_workspace_ft_v10.slot_contrast_learner import SlotContrastNativeLearner
from latent_workspace_ft_v10.training_binding import MistralTrainingBinding
from latent_workspace_ft_v10.v15_native_learner import create_reader, tree_hash
from latent_workspace_ft_v10.v16_comparison_eval import CONDITIONS, FACTORS, summarize
from latent_workspace_ft_v10.v16_slot_contrast import SlotContrastWorkspaceBridge
from scripts import run_v16_adapter_migration as core
from scripts import run_v16_full_comparison as run

DEVICE = os.environ.get("LATENT_COMPARISON_TEST_DEVICE", "cpu")


@pytest.fixture(autouse=True)
def setup():
    core.load_runtime()
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


def build(arm, dtype):
    base, _, _ = tiny(dtype)
    base.to(DEVICE)
    prepare_native_gradient_checkpointing(base)
    torch.manual_seed(47)
    common = create_reader(
        16, dict(workspace_dim=8, heads=2, slots=3, max_delta_norm=1), "query_modulated"
    ).to(DEVICE)
    bridge = common if arm == "common" else SlotContrastWorkspaceBridge(common, mode=arm)
    contract = dict(original_base_sha256=tree_hash(base.state_dict()), objective="tiny", arm=arm)
    random.seed(47)
    np.random.seed(47)
    torch.manual_seed(47)
    cls = AdapterNativeLearnerV2 if arm == "common" else SlotContrastNativeLearner
    return cls(
        MistralTrainingBinding(base, 1),
        bridge,
        full_update=True,
        optimizer_config=OPT,
        run_contract=contract,
    )


def without_observations(window):
    result = copy.deepcopy(window)
    for row in result["pairs"]:
        row.pop("bridge_gradients")
    return result


@pytest.mark.parametrize("arm", run.ARMS)
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_evaluation_update_unchanged_and_serialized_replay(monkeypatch, tmp_path, arm, dtype):
    plan = run.read(run.ROOT / run.PLAN)
    learner = build(arm, dtype)
    store = make_store(monkeypatch, learner)
    objective = core.legacy.old.validate()[0]
    def guard(*a):
        pass
    initial = run.evaluate(core, learner, store, None, guard, plan)
    assert len(initial["rows"]) == 160 and len(initial["contrasts"]) == 80
    assert all(r["full_logits_equal_current_base"] for r in initial["rows"])
    first = run.update_window(core, learner, store, objective, guard)
    after1 = run.evaluate(core, learner, store, initial["direct_base"], guard, plan)
    assert after1["owned_state_fingerprint_unchanged"]
    receipt = learner.save(tmp_path / "step1.pt", {"tiny": arm})
    payload = torch.load(tmp_path / "step1.pt", weights_only=True, map_location="cpu")
    second = run.update_window(core, learner, store, objective, guard)
    after2 = run.evaluate(core, learner, store, initial["direct_base"], guard, plan)
    state = tree_hash(learner.payload({"tiny": arm}))
    assert after2["original_base"] == initial["direct_base"]
    for report in (after1, after2):
        assert report["rng_unchanged"]
        assert all(
            r["transport"]["native_published_gap_change"] == [0.0]
            for r in report["contrasts"]
            if r["factor"] == "same_memory"
        )
        if arm == "slot_contrast":
            assert all(
                r["interaction_exact_zero"]
                for r in report["rows"]
                if r["condition"].startswith("common_")
            )
    # Independent call of the unchanged qualified window excludes observation effects.
    reference = build(arm, dtype)
    ref_store = make_store(monkeypatch, reference)
    assert without_observations(first) == core.update_window(
        reference, ref_store, objective, "adapter_v2", guard
    )
    assert without_observations(second) == core.update_window(
        reference, ref_store, objective, "adapter_v2", guard
    )
    target = build(arm, dtype)
    restored = type(target).restore(
        target.binding,
        target.bridge,
        payload,
        expected_metadata={"tiny": arm},
        expected_run_contract=target.run_contract,
        expected_state_sha256=receipt["state_sha256"],
    )
    replay = run.update_window(core, restored, make_store(monkeypatch, restored), objective, guard)
    assert replay == second
    assert tree_hash(restored.payload({"tiny": arm})) == state


@pytest.mark.parametrize(
    "key,value",
    [
        ("seed", 48),
        ("full_update", False),
        ("steps", [1, 2, 3]),
        ("per_arm_storage_forecast_bytes", 1),
    ],
)
def test_plan_rejects_drift(key, value):
    plan = run.read(run.ROOT / run.PLAN)
    run.validate_plan(plan)
    plan[key] = value
    with pytest.raises(ValueError, match="Frozen"):
        run.validate_plan(plan)


def test_capacity_controls_have_identical_common_interaction_initialization():
    common = build("common", torch.float32)
    raw = build("raw_matched_control", torch.float32)
    contrast = build("slot_contrast", torch.float32)
    assert tree_hash(raw.bridge.state_dict()) == tree_hash(contrast.bridge.state_dict())
    assert tree_hash(common.bridge.state_dict()) == tree_hash(raw.bridge.common.state_dict())


def test_summary_does_not_promote_controls_or_erase_regressions():
    rows = [
        dict(
            world=0,
            query=0,
            condition=c,
            target=1 if c == "intact" else None,
            prediction=0,
            correct=False if c == "intact" else None,
        )
        for c in CONDITIONS
    ]
    contrasts = [
        dict(
            factor=f,
            affected=True,
            labels=[0, 1],
            donor_directed_gap_change=-0.1,
            left_prediction=0,
            right_prediction=0,
        )
        for f in FACTORS
    ]
    result = summarize(
        dict(
            rows=rows,
            contrasts=contrasts,
            direct_base=[{}],
            original_base=[dict(world=0, query=0, prediction=1)],
        )
    )
    assert result["conditions"]["intact"]["regressions_from_original"] == 1
    assert result["conditions"]["random_intact"]["labelled_n"] == 0
    assert result["factors"]["actual"]["negative"] == 1
    assert result["factors"]["actual"]["donor_directed_flips"] == 0
    assert result["old_expression_gate"] == "FAIL" and result["winner"] == "none"
