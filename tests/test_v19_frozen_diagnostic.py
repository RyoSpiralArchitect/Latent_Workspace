"""Tiny harness integration for the V19 frozen diagnostic, not a real-model receipt."""

import copy
import gzip
import os
from math import comb

import pytest
import torch
from test_v15_full_update import tiny
from test_v15_native_learner import OPT
from test_v18_native_pilot import Tokenizer, render

from latent_workspace_ft_v10.training_binding import MistralTrainingBinding
from latent_workspace_ft_v10.v15_native_learner import create_reader, tree_hash
from latent_workspace_ft_v10.v19_dual_budget_reader import DualBudgetWorkspaceBridge
from latent_workspace_ft_v10.v19_dual_budget_window_learner import V19DualBudgetWindowLearner
from scripts import run_v16_adapter_migration as core
from scripts import run_v19_frozen_diagnostic as run

DEVICE = os.environ.get("LATENT_V19_TEST_DEVICE", "cpu")
PLAN = run.read(run.ROOT / run.PLAN)
SEAL = {"source_commit": "0" * 40, "source_hashes": {}}
META = {"tiny": "v19-frozen-diagnostic"}


def guard(*_args, **_kwargs):
    pass


@pytest.fixture(autouse=True)
def setup():
    core.load_runtime()
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


def records():
    return run.load_records(PLAN)


def tiny_plan(train_worlds=4):
    plan = copy.deepcopy(PLAN)
    plan["schedule"].update(epochs=2, permutation_seeds=[11, 12], updates=train_worlds)
    return plan


def build(dtype, name, plan, train):
    base, _, _ = tiny(dtype)
    base.requires_grad_(False).train(False)
    base.to(DEVICE)
    torch.manual_seed(47)
    common = create_reader(
        16, dict(workspace_dim=8, heads=2, slots=3, max_delta_norm=1), "query_modulated"
    ).to(DEVICE)
    arm = run.arm_spec(plan, name)
    bridge = DualBudgetWorkspaceBridge(
        common, mode=arm["factor"], workspace_cap=arm["workspace_cap"]
    )
    run.reseed(plan["seed"], core)
    windows = run.schedule(plan, train)
    objective = core.legacy.old.validate()[0]
    contract = run.make_contract(core, base, objective, SEAL, plan, arm, windows)
    learner = V19DualBudgetWindowLearner(
        MistralTrainingBinding(base, 1),
        bridge,
        workspace_policy=run.workspace_policy(arm["workspace_query"]),
        full_update=False,
        optimizer_config=OPT,
        run_contract=contract,
        schedule=windows,
    )
    return learner, contract, windows


def store(monkeypatch, learner, rows):
    monkeypatch.setattr(core.legacy.old, "render_case", render)
    result = core.legacy.LiveStore(learner, Tokenizer(), rows, guard)
    spans, receipt = run.pilot().bind_spans(core, result, Tokenizer())
    return result, spans, receipt


def contrast(world, query, factor, labels, left, right, change):
    return dict(
        world=world,
        query=query,
        factor=factor,
        affected=labels[0] != labels[1],
        labels=labels,
        left_prediction=left,
        right_prediction=right,
        donor_directed_gap_change=change if labels[0] != labels[1] else None,
    )


def synthetic_report():
    contrasts, rows, direct = [], [], []
    for world in range(4):
        for query, labels in ((0, [1, 0]), (1, [0, 1]), (2, [1, 1])):
            flip = world < 3  # three worlds flip in the donor direction
            for factor in ("actual", "random_pair", "reversed", "common_slots", "same_memory"):
                hit = flip and factor == "actual"
                left, right = labels if hit else [labels[0], labels[0]]
                change = (0.5 if world < 3 else -0.25) if factor == "actual" else 0.0
                contrasts.append(contrast(world, query, factor, labels, left, right, change))
            for condition, side in (("intact", 0), ("twin", 1)):
                prediction = labels[side] if flip else labels[0]
                rows.append(
                    dict(
                        world=world,
                        query=query,
                        condition=condition,
                        prediction=prediction,
                        correct=prediction == labels[side],
                    )
                )
            direct.append(dict(world=world, query=query, labels=labels, prediction=labels[0]))
    return dict(contrasts=contrasts, rows=rows, direct_base=direct)


def synthetic_records():
    queries = [
        "Is A ranked above B? Answer:",
        "Is B ranked above A? Answer:",
        "Does A outrank C? Answer:",
    ]
    return [dict(queries=queries) for _ in range(4)]


@pytest.mark.parametrize(
    "path,value",
    [
        (("seed",), 48),
        (("schedule", "updates"), 256),
        (("endpoints", "sign_test_alpha"), 0.01),
        (("arms",), list(reversed(PLAN["arms"]))),
    ],
)
def test_plan_hash_and_semantics_reject_drift(path, value):
    plan = copy.deepcopy(PLAN)
    run.validate_plan(plan)
    target = plan
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError, match="Frozen V19 diagnostic plan"):
        run.validate_plan(plan)


def test_all_labels_pass_the_oracle_and_splits_are_disjoint():
    data = records()
    audit = run.validate_data(core.legacy.old, data)
    assert all(not any(v["overlaps"].values()) for v in audit.values())
    assert [len(data[s]) for s in run.SPLITS] == [256, 64, 128]
    broken = copy.deepcopy(data)
    broken["final"][7]["answers"][1][0] ^= 1
    with pytest.raises(ValueError, match="final"):
        run.validate_data(core.legacy.old, broken)


def test_schedule_covers_every_train_world_once_per_epoch():
    train = records()["train"]
    rows = run.schedule_rows(PLAN, train)
    assert rows == run.schedule_rows(PLAN, train)
    assert len(rows) == 512 and len({window_id for window_id, _ in rows}) == 512
    for epoch in range(4):
        worlds = []
        for _window_id, occurrences in rows[epoch * 128 : (epoch + 1) * 128]:
            assert len(occurrences) == 16
            assert sum(a != b for _, a, b in occurrences) == 4
            worlds += sorted({run.pilot().parse_occurrence(o)[0] for o, _, _ in occurrences})
        assert sorted(worlds) == list(range(256))
    windows = run.schedule(PLAN, train)
    assert all(w.counts["affected_pairs"] == 4 and w.counts["answer_terms"] == 32 for w in windows)


def test_binomial_tail_is_exact():
    assert run.binomial_upper(0, 9) == 1.0
    assert run.binomial_upper(10, 10) == 2**-10
    assert run.binomial_upper(5, 10) == sum(comb(10, k) for k in range(5, 11)) / 1024
    assert run.binomial_upper(0, 0) == 1.0


def test_diagnosis_counts_flips_world_signs_and_verdicts():
    endpoints = dict(
        PLAN["endpoints"],
        minimum_actual_flips=6,
        minimum_flip_margin_over_random=5,
        sign_test_alpha=0.07,
    )
    result = run.diagnose(synthetic_report(), synthetic_records(), endpoints)
    assert result["affected_queries"] == 8 and result["worlds"] == 4
    assert result["flips"]["actual"] == 6 and result["flips"]["random_pair"] == 0
    assert result["world_sign"] == {"positive": 3, "negative": 1, "zero": 0}
    assert result["sign_test_p"] == 5 / 16
    assert result["verdict"] == "NOT_ESTABLISHED"
    loose = dict(endpoints, sign_test_alpha=0.5)
    assert run.diagnose(synthetic_report(), synthetic_records(), loose)["verdict"] == (
        "CONTENT_REACHES_ANSWERS"
    )
    strict = dict(loose, minimum_actual_flips=7)
    assert run.diagnose(synthetic_report(), synthetic_records(), strict)["verdict"] == (
        "DIRECTIONAL_ONLY"
    )
    assert result["accuracy_by_wording"]["intact:ranked_above"]["correct"] == 8
    assert result["accuracy_by_wording"]["direct_vs_twin:outrank"]["n"] == 4


def test_selection_comparison_uses_paired_discordant_flips():
    rule = PLAN["endpoints"]["comparisons"]["selection"]
    ordered = {"actual_flip_queries": [[w, 0] for w in range(20)]}
    final = {"actual_flip_queries": [[w, 0] for w in range(2)]}
    result = run.compare_arms(ordered, final, rule)
    assert (result["only_ordered"], result["only_final"], result["difference"]) == (18, 0, 18)
    assert result["mcnemar_one_sided_p"] == 2**-18
    assert result["label"] == rule["positive_label"]
    assert run.compare_arms(final, ordered, rule)["label"] == rule["otherwise"]


def test_gzip_records_are_deterministic(tmp_path):
    value = {"b": [1, 2.5, None], "a": "x"}
    run.write_gz(tmp_path / "one.json.gz", value)
    run.write_gz(tmp_path / "two.json.gz", value)
    assert (tmp_path / "one.json.gz").read_bytes() == (tmp_path / "two.json.gz").read_bytes()
    assert run.read_gz(tmp_path / "one.json.gz") == value
    assert gzip.decompress((tmp_path / "one.json.gz").read_bytes()).endswith(b"\n")
    with pytest.raises(FileExistsError):
        run.write_gz(tmp_path / "one.json.gz", value)


def test_throttled_guard_calls_every_nth_phase():
    seen = []
    call = run.throttled(seen.append, 3)
    for index in range(7):
        call(f"p{index}")
    assert seen == ["p0", "p3", "p6"]


def test_arms_match_except_the_declared_query_policy_or_budget():
    plan, train = tiny_plan(), records()["train"][:4]
    ordered, ordered_contract, _ = build(torch.float32, "ordered_cap025", plan, train)
    final, final_contract, _ = build(torch.float32, "final_cap025", plan, train)
    larger, larger_contract, _ = build(torch.float32, "ordered_cap100", plan, train)
    assert tree_hash(ordered.bridge.state_dict()) == tree_hash(final.bridge.state_dict())
    assert tree_hash(ordered.bridge.state_dict()) == tree_hash(larger.bridge.state_dict())
    key = run.workspace_key()
    differing = {k for k in ordered_contract if ordered_contract[k] != final_contract[k]}
    assert differing == {"condition", key}
    differing = {k for k in ordered_contract if ordered_contract[k] != larger_contract[k]}
    assert differing == {"condition", "workspace_cap"}
    assert (ordered.bridge.workspace_cap, larger.bridge.workspace_cap) == (0.25, 1.0)
    assert ordered_contract["full_update"] is False and ordered_contract["preparation"] is None


def test_comparisons_read_both_frozen_rules(tmp_path):
    flips = {"ordered_cap025": 20, "final_cap025": 2, "ordered_cap100": 20}
    for arm, count in flips.items():
        (tmp_path / arm).mkdir()
        run.write_new(
            tmp_path / arm / "DIAGNOSIS.json",
            {"actual_flip_queries": [[w, 0] for w in range(count)]},
        )
    result = run.comparisons_for(tmp_path, PLAN)
    assert set(result) == {"selection", "budget_dose"}
    assert result["selection"]["label"] == "ORDERED_SELECTION_ADVANTAGE_DIAGNOSTIC"
    assert result["budget_dose"]["label"] == "NO_BUDGET_DOSE_ADVANTAGE_ESTABLISHED"


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_frozen_windows_evaluation_checkpoint_and_independent_replay(monkeypatch, tmp_path, dtype):
    plan, data = tiny_plan(), records()
    train, dev = data["train"][:4], data["dev"][:2]
    learner, contract, windows = build(dtype, "ordered_cap025", plan, train)
    train_store, train_spans, train_receipt = store(monkeypatch, learner, train)
    dev_store, dev_spans, _ = store(monkeypatch, learner, dev)
    native = tree_hash(learner.base.state_dict())
    start = run.evaluate(core, learner, dev_store, dev_spans, dev, None, guard, plan)
    assert start["diagnosis"]["flips"]["actual"] == 0
    assert start["diagnosis"]["verdict"] == "NOT_ESTABLISHED"
    assert start["diagnosis"]["affected_queries"] == 4
    first = run.update_window(core, learner, train_store, train_spans, guard)
    saved = learner.save(tmp_path / "step1.pt", META)
    second = run.update_window(core, learner, train_store, train_spans, guard)
    after = run.evaluate(
        core, learner, dev_store, dev_spans, dev, start["direct_base"], guard, plan
    )
    assert after["owned_state_fingerprint_unchanged"] and after["rng_unchanged"]
    assert tree_hash(learner.base.state_dict()) == native
    assert first["state"] != second["state"]
    assert [first["update"]["completed_step"], second["update"]["completed_step"]] == [1, 2]
    assert first["update"]["base_changes"] == [] and len(first["pairs"]) == 16
    assert after["original_base"] == start["direct_base"]
    target, rebuilt, rebuilt_windows = build(dtype, "ordered_cap025", plan, train)
    assert run.pilot().same(rebuilt, contract)
    assert [w.descriptor() for w in rebuilt_windows] == [w.descriptor() for w in windows]
    payload = torch.load(tmp_path / "step1.pt", map_location="cpu", weights_only=True)
    restored = V19DualBudgetWindowLearner.restore(
        target.binding,
        target.bridge,
        payload,
        expected_workspace_policy=run.workspace_policy("ordered_difference"),
        expected_metadata=META,
        expected_run_contract=rebuilt,
        expected_schedule=rebuilt_windows,
        expected_state_sha256=saved["state_sha256"],
    )
    replay_store, replay_spans, replay_receipt = store(monkeypatch, restored, train)
    assert run.pilot().same(replay_receipt, train_receipt)
    replay = run.update_window(core, restored, replay_store, replay_spans, guard)
    assert run.pilot().same(replay, second)


def test_light_fingerprint_refuses_full_update_owner():
    class Owner:
        base_optimizer = object()
        masters = {"x": 1}

    with pytest.raises(ValueError, match="Frozen owner only"):
        run.light_fingerprint(core, Owner())


def test_role_constants_ceiling_and_plan_binding():
    assert run.ROLES == ("ordered_cap025", "final_cap025", "ordered_cap100", "replay")
    assert set(run.ROLE_PASS) == set(run.ROLES)
    assert run.CEILING["native_weight_updates"] == 0 and run.CEILING["winner"] == "none"
    assert PLAN["qualification_cases"] == run.QUALIFICATION_CASES
    assert PLAN["endpoints"]["chance_control"] == "random_pair"
    assert set(PLAN["endpoints"]["verdicts"]) == set(run.VERDICTS)
