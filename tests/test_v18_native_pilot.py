"""Tiny harness integration for the V18 native pilot, not a real-model receipt."""

import copy
import json
import os
import random
from dataclasses import asdict

import numpy as np
import pytest
import torch
from test_v15_full_update import tiny
from test_v15_native_learner import OPT
from test_v18_selection_pipeline import TinyTokenizer

from latent_workspace_ft_v10.native_training_preparation import (
    prepare_native_gradient_checkpointing,
)
from latent_workspace_ft_v10.slot_contrast_learner import SlotContrastNativeLearner
from latent_workspace_ft_v10.training_binding import MistralTrainingBinding
from latent_workspace_ft_v10.v15_native_learner import create_reader, tree_hash
from latent_workspace_ft_v10.v16_slot_contrast import SlotContrastWorkspaceBridge
from latent_workspace_ft_v10.v18_operand_query import bind_operand_span
from latent_workspace_ft_v10.v18_selection_reader import SelectionWorkspaceBridge
from latent_workspace_ft_v10.v18_selection_window_learner import V18SelectionWindowLearner
from scripts import run_v16_adapter_migration as core
from scripts import run_v16_full_comparison as v16
from scripts import run_v18_native_pilot as run

DEVICE = os.environ.get("LATENT_V18_PILOT_TEST_DEVICE", "cpu")
PLAN = run.read(run.ROOT / run.PLAN)
SEAL = {"source_commit": "0" * 40, "source_hashes": {}}
META = {"tiny": "v18-native-pilot"}


def guard(*_args, **_kwargs):
    pass


@pytest.fixture(autouse=True)
def setup():
    core.load_runtime()
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


class Tokenizer(TinyTokenizer):
    """Regex offsets for prompts; fixed tiny IDs for fact contexts."""

    def encode(self, text, *, add_special_tokens=False):
        if "Answer:" in text:
            return super().encode(text, add_special_tokens=add_special_tokens)
        return [1, 8, 9] if "Galen" in text else [1, 9, 8]

    def get_vocab(self):
        return {"fake": 1}


def render(_tokenizer, *, query, context, renderer, cue, information):
    assert (renderer, cue, information) == ("native_chat", "present", "query_only")
    text = "Use facts.\n" + query
    ids = Tokenizer().encode(text)
    span = bind_operand_span(
        Tokenizer(), raw_query=query, rendered_prefix=text, expected_prefix_ids=ids
    ).question_span
    return dict(
        text=text, prompt_ids=ids, candidate_ids=[6, 7], span=json.loads(json.dumps(asdict(span)))
    )


def legacy_data():
    objective, _architecture, records = core.legacy.old.validate()
    return objective, records


def make_store(monkeypatch, learner):
    monkeypatch.setattr(core.legacy.old, "render_case", render)
    return core.legacy.LiveStore(learner, Tokenizer(), legacy_data()[1], guard)


def parts(dtype):
    base, _, _ = tiny(dtype)
    base.to(DEVICE)
    preparation = prepare_native_gradient_checkpointing(base)
    torch.manual_seed(47)
    common = create_reader(
        16, dict(workspace_dim=8, heads=2, slots=3, max_delta_norm=1), "query_modulated"
    ).to(DEVICE)
    return base, common, preparation


def reseed():
    random.seed(47)
    np.random.seed(47)
    torch.manual_seed(47)


def spec(mode):
    return dict(PLAN["condition"] if mode != "final" else PLAN["probe"], interaction_query=mode)


def v18(dtype, mode, window_ids=None):
    base, common, preparation = parts(dtype)
    bridge = SelectionWorkspaceBridge(common, mode="slot_contrast", interaction_fraction=0.25)
    reseed()
    objective, records = legacy_data()
    chosen = spec(mode)
    contract = run.make_contract(core, base, objective, SEAL, PLAN, preparation, chosen)
    windows = run.schedule(
        records, PLAN, window_ids or chosen["window_ids"], PLAN["training_data_sha256"]
    )
    learner = V18SelectionWindowLearner(
        MistralTrainingBinding(base, 1),
        bridge,
        selection_policy=run.policy(mode),
        full_update=True,
        optimizer_config=OPT,
        run_contract=contract,
        schedule=windows,
    )
    return learner, contract, windows


def legacy(dtype):
    base, common, _preparation = parts(dtype)
    bridge = SlotContrastWorkspaceBridge(common, mode="slot_contrast")
    reseed()
    contract = dict(original_base_sha256=tree_hash(base.state_dict()), objective="tiny")
    return SlotContrastNativeLearner(
        MistralTrainingBinding(base, 1),
        bridge,
        full_update=True,
        optimizer_config=OPT,
        run_contract=contract,
    )


def paired(monkeypatch, dtype, mode):
    learner, _, _ = v18(dtype, mode, PLAN["probe"]["window_ids"])
    store = make_store(monkeypatch, learner)
    spans, _ = run.bind_spans(core, store, Tokenizer())
    old = legacy(dtype)
    old_store = make_store(monkeypatch, old)
    return learner, store, spans, old, old_store


def setpath(value, path, new):
    for key in path[:-1]:
        value = value[key]
    value[path[-1]] = new


@pytest.mark.parametrize(
    "path,value",
    [
        (("seed",), 48),
        (("condition", "interaction_query"), "final"),
        (("probe", "gate"), "record_only"),
        (("storage_forecast_bytes",), 1),
        (("probe", "comparator_sha256", "step1.json"), "0" * 64),
    ],
)
def test_plan_rejects_drift(path, value):
    plan = copy.deepcopy(PLAN)
    run.validate_plan(plan)
    setpath(plan, path, value)
    with pytest.raises(ValueError, match="Frozen"):
        run.validate_plan(plan)


def test_pinned_comparators_owner_seal_and_data_match_repository():
    for name, digest in PLAN["probe"]["comparator_sha256"].items():
        assert core.digest(run.ROOT / PLAN["probe"]["comparator"] / name) == digest
    seal = run.ROOT / PLAN["qualified_owner_seal"]
    assert core.digest(seal) == PLAN["qualified_owner_seal_sha256"]
    hashes = run.read(seal)["source_hashes"]
    assert len(hashes) == 594
    assert all(core.digest(run.ROOT / name) == digest for name, digest in hashes.items())
    assert core.digest(run.ROOT / PLAN["training_data"]) == PLAN["training_data_sha256"]


def test_world_major_schedule_keeps_historical_denominators():
    _objective, records = legacy_data()
    windows = run.schedule(
        records, PLAN, PLAN["condition"]["window_ids"], PLAN["training_data_sha256"]
    )
    assert [w.window_id for w in windows] == PLAN["condition"]["window_ids"]
    ids = tuple(run.occurrence(w, q) for w in range(2) for q in range(8))
    for window in windows:
        assert window.ids == ids
        assert window.counts == dict(
            answer_terms=32,
            affected_pairs=4,
            unaffected_pairs=12,
            unrelated_pairs=16,
            residual_terms=48,
        )
    assert [run.parse_occurrence(i) for i in ids] == [(w, q) for w in range(2) for q in range(8)]


def test_operand_spans_bind_exact_rendering_and_reject_span_drift(monkeypatch):
    learner, _, _ = v18(torch.float32, "ordered_difference")
    store = make_store(monkeypatch, learner)
    spans, receipt = run.bind_spans(core, store, Tokenizer())
    assert len(spans) == len(receipt) == 16
    assert all(s.subject_token_indices and s.object_token_indices for s in spans.values())
    store.renderings[1, 3]["span"]["token_indices"] = [0]
    with pytest.raises(ValueError, match="Question span drift"):
        run.bind_spans(core, store, Tokenizer())


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_final_probe_reproduces_v16_window_exactly(monkeypatch, dtype):
    learner, store, spans, old, old_store = paired(monkeypatch, dtype, "final")
    assert run.same(core.state_fingerprint(learner.inner), core.state_fingerprint(old))
    ours = run.update_window(core, learner, store, spans, guard)
    objective = legacy_data()[0]
    theirs = v16.update_window(core, old, old_store, objective, guard)
    checks = run.compare_v16_window(ours, theirs)
    assert run.all_true(checks)
    assert all(
        "loss" in r["components"] and "loss" not in m["components"]
        for r, m in zip(theirs["pairs"], ours["pairs"])
    )


def test_ordered_query_is_caught_by_the_probe_comparison(monkeypatch):
    learner, store, spans, old, old_store = paired(monkeypatch, torch.float32, "ordered_difference")
    ours = run.update_window(core, learner, store, spans, guard)
    theirs = v16.update_window(core, old, old_store, legacy_data()[0], guard)
    checks = run.compare_v16_window(ours, theirs)
    # The zero-initialized interaction output keeps every forward identical, but
    # the interaction up-projection gradient follows the selected query.
    assert all(pair["components"] for pair in checks["pairs"])
    assert not all(pair["accumulated_gradients_sha256"] for pair in checks["pairs"])
    assert not checks["state"] and not run.all_true(checks)


def test_window_comparison_rejects_single_field_tampering(monkeypatch):
    learner, store, spans, old, old_store = paired(monkeypatch, torch.float32, "final")
    ours = run.update_window(core, learner, store, spans, guard)
    theirs = v16.update_window(core, old, old_store, legacy_data()[0], guard)
    assert run.all_true(run.compare_v16_window(ours, theirs))
    changed = copy.deepcopy(theirs)
    changed["pairs"][5]["spill"]["current_gradient_count"] += 1
    assert not run.all_true(run.compare_v16_window(ours, changed))
    assert not run.all_true({}) and not run.all_true([]) and not run.all_true({"x": 1})


@pytest.mark.parametrize("mode", ["final", "ordered_difference"])
def test_step_zero_evaluation_port_matches_v16(monkeypatch, mode):
    learner, store, spans, old, old_store = paired(monkeypatch, torch.float32, mode)
    ours = run.evaluate(core, learner, store, spans, None, guard, PLAN)
    theirs = v16.evaluate(core, old, old_store, None, guard, PLAN)
    assert run.all_true(run.compare_v16_evaluation(ours, theirs))
    assert all(r["interaction_query"] == mode for r in ours["rows"])
    assert all(r["interaction_query_equals_common"] == (mode == "final") for r in ours["rows"])


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_update_evaluation_checkpoint_and_independent_restore_replay(monkeypatch, tmp_path, dtype):
    learner, contract, windows = v18(dtype, "ordered_difference")
    store = make_store(monkeypatch, learner)
    spans, receipt = run.bind_spans(core, store, Tokenizer())
    initial = run.evaluate(core, learner, store, spans, None, guard, PLAN)
    assert len(initial["rows"]) == 160 and len(initial["contrasts"]) == 80
    assert len(initial["direct_base"]) == 16
    assert all(r["full_logits_equal_current_base"] for r in initial["rows"])
    assert all(r["interaction_exact_zero"] for r in initial["rows"])
    first = run.update_window(core, learner, store, spans, guard)
    after1 = run.evaluate(core, learner, store, spans, initial["direct_base"], guard, PLAN)
    saved1 = learner.save(tmp_path / "step1.pt", META)
    second = run.update_window(core, learner, store, spans, guard)
    after2 = run.evaluate(core, learner, store, spans, initial["direct_base"], guard, PLAN)
    saved2 = learner.save(tmp_path / "step2.pt", META)
    assert [first["update"]["completed_step"], second["update"]["completed_step"]] == [1, 2]
    assert first["window"]["window_id"] != second["window"]["window_id"]
    for report in (after1, after2):
        assert report["rng_unchanged"] and report["owned_state_fingerprint_unchanged"]
        assert all(r["parts_reproduce_delta"] for r in report["rows"])
        assert all(
            r["interaction_exact_zero"]
            for r in report["rows"]
            if r["condition"].startswith("common_")
        )
        assert all(
            r["transport"]["native_published_gap_change"] == [0.0]
            for r in report["contrasts"]
            if r["factor"] == "same_memory"
        )
        assert report["original_base"] == initial["direct_base"]
    assert any(
        not r["interaction_exact_zero"] for r in after1["rows"] if r["condition"] == "intact"
    )
    # An independently rebuilt fresh owner restores step 1 and replays step 2 exactly.
    target, rebuilt, rebuilt_windows = v18(dtype, "ordered_difference")
    assert run.same(rebuilt, contract)
    assert [w.descriptor() for w in rebuilt_windows] == [w.descriptor() for w in windows]
    payload = torch.load(tmp_path / "step1.pt", map_location="cpu", weights_only=True)
    restored = V18SelectionWindowLearner.restore(
        target.binding,
        target.bridge,
        payload,
        expected_selection_policy=run.policy("ordered_difference"),
        expected_metadata=META,
        expected_run_contract=rebuilt,
        expected_schedule=rebuilt_windows,
        expected_state_sha256=saved1["state_sha256"],
    )
    replay_store = make_store(monkeypatch, restored)
    replay_spans, replay_receipt = run.bind_spans(core, replay_store, Tokenizer())
    assert run.same(replay_receipt, receipt)
    assert run.same(replay_store.feature_receipt(), store.feature_receipt())
    replay = run.update_window(core, restored, replay_store, replay_spans, guard)
    assert run.same(replay, second)
    assert tree_hash(restored.payload(META)) == saved2["state_sha256"]


def test_contracts_differ_only_by_declared_condition_and_policy():
    base, _, preparation = parts(torch.float32)
    objective = legacy_data()[0]
    ordered = run.make_contract(
        core, base, objective, SEAL, PLAN, preparation, spec("ordered_difference")
    )
    final = run.make_contract(core, base, objective, SEAL, PLAN, preparation, spec("final"))
    differing = {k for k in ordered if ordered[k] != final[k]}
    assert differing == {"condition", "v18_selection_policy"}
    assert ordered["v18_selection_policy"]["interaction_query"] == "ordered_difference"
    assert "v18_selection_window_reference" not in ordered


def test_role_receipts_and_ceiling_are_fixed():
    assert run.ROLES == ("probe", "primary", "replay")
    assert set(run.ROLE_PASS) == set(run.ROLES)
    assert run.CEILING == dict(
        new_sequences=0,
        judge_calls=0,
        weight_deletions=0,
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
    )
    assert PLAN["qualification_cases"] == run.QUALIFICATION_CASES
