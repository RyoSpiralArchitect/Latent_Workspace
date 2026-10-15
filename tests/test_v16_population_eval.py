"""Small CPU/CUDA qualification of the additive population observer and data selection."""

import copy
import os

import pytest
import torch
from test_v15_native_runner import make_store
from test_v16_full_comparison import build

from latent_workspace_ft_v10.v15_native_learner import tree_hash
from latent_workspace_ft_v10.v16_comparison_eval import memory_bank
from latent_workspace_ft_v10.v16_population_probe import choice4, slot_trace
from scripts import prepare_v16_population_inputs as prepare
from scripts import run_v16_adapter_migration as core
from scripts import run_v16_population_eval as run

DEVICE = os.environ.get("LATENT_POPULATION_TEST_DEVICE", "cpu")


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    import test_v16_full_comparison as comparison

    monkeypatch.setattr(comparison, "DEVICE", DEVICE)
    core.load_runtime()
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


@pytest.mark.parametrize("arm", ["raw_matched_control", "slot_contrast"])
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_trace_reconstructs_without_state_rng_or_forward_mutation(monkeypatch, arm, dtype):
    learner = build(arm, dtype)
    with torch.no_grad():
        learner.bridge.up.weight.normal_(std=0.01)
    store = make_store(monkeypatch, learner)
    before = core.state_fingerprint(learner)
    with torch.no_grad():
        bank = memory_bank(learner, store, 0, 124)
        memory, mask = bank["intact"]
        query = torch.arange(16, dtype=torch.float32, device=DEVICE).reshape(1, 1, 16)
        first = learner.bridge.parts(query, memory, mask)
        trace = slot_trace(learner.bridge, query, memory, mask)
        second = learner.bridge.parts(query, memory, mask)
    assert tree_hash(first) == tree_hash(second)
    assert trace["interaction_reconstruction_exact"]
    assert trace["shadow_weights_are_production_output"] is False
    assert core.state_fingerprint(learner) == before


@pytest.mark.parametrize("arm", ["raw_matched_control", "slot_contrast"])
def test_equal_slots_and_masked_padding_have_declared_null(arm):
    learner = build(arm, torch.float32)
    with torch.no_grad():
        learner.bridge.up.weight.normal_(std=0.1)
        memory = torch.arange(8, device=DEVICE).float().reshape(1, 1, 8).expand(1, 3, 8).clone()
        memory[:, 2] = -123
        mask = torch.tensor([[1, 1, 0]], device=DEVICE)
        trace = slot_trace(learner.bridge, torch.ones(1, 1, 16, device=DEVICE), memory, mask)
    assert trace["centered_slots_l2"] == 0
    if arm == "slot_contrast":
        assert trace["interaction_l2"] == 0 and trace["production_read_l2"] == 0
    else:
        assert trace["interaction_l2"] > 0


@pytest.mark.parametrize(
    "scores,pred,strict",
    [
        ([1, 2, 3, 4], 3, 3),
        ([4, 4, 1, 2], 0, None),
        ([0, 0, 0, 0], 0, None),
        ([-5, -1, -2, -3], 1, 1),
    ],
)
def test_mmlu_argmax_and_strict_ties(scores, pred, strict):
    result = choice4(scores)
    assert result["prediction"] == pred and result["strict_prediction"] == strict


@pytest.mark.parametrize("scores", [[1, 2], [0, 0, 0, float("nan")]])
def test_mmlu_rejects_missing_or_nonfinite_scores(scores):
    with pytest.raises(ValueError):
        choice4(scores)


class Tokenizer:
    def encode(self, text, add_special_tokens=True):
        return [1, 2, 3] + ([ord(text[-1])] if text[-1] in "ABCD" else [])


def test_mmlu_candidates_are_bound_to_exact_prefix():
    rows = [{"id": "one", "prompt": "Question? Answer:"}]
    observed = run.tokenize_mmlu(Tokenizer(), rows, 64)
    assert observed[0]["candidate_ids"] == list(map(ord, "ABCD"))
    with pytest.raises(ValueError, match="No truncation"):
        run.tokenize_mmlu(Tokenizer(), rows, 2)


def test_mmlu_rejects_boundary_retokenization():
    class BadTokenizer(Tokenizer):
        def encode(self, text, add_special_tokens=True):
            return [9, 9, ord(text[-1])] if text[-1] in "ABCD" else [1, 2]

    with pytest.raises(ValueError, match="prefix-compatible"):
        run.tokenize_mmlu(BadTokenizer(), [{"id": "one", "prompt": "Answer:"}], 64)


def test_fresh_worlds_are_deterministic_disjoint_and_oracle_checked():
    plan = run.read(run.ROOT / run.PLAN)
    left, audit = prepare.fresh_worlds(plan)
    assert (left, audit) == prepare.fresh_worlds(plan)
    assert len(left) == 128 and sum(sum(r["affected"]) for r in left) == 256
    orders = [tuple(o) for r in left for o in r["metadata"]["orders"]]
    assert len(set(orders)) == 256
    assert audit["historical_order_overlap"] == 0 and not audit["entity_heldout"]


def test_mmlu_selection_does_not_depend_on_test_labels():
    row = {"question": "Q?", "choices": ["a", "b", "c", "d"], "answer": 0, "subject": "tiny"}
    tests = [{**row, "question": f"Q{i}?"} for i in range(15)]
    dev = [dict(row) for _ in range(5)]
    spec = dict(subjects=1, per_subject=10, fewshot=5, selection_seed=16101557)
    first = prepare.select_mmlu(tests, dev, spec)
    second = prepare.select_mmlu([{**r, "answer": 3} for r in tests], dev, spec)
    assert [r["id"] for r in first] == [r["id"] for r in second]
    assert [r["prompt"] for r in first] == [r["prompt"] for r in second]
    assert all(r["target"] == 3 for r in second)


def test_inputs_reject_changed_plan_or_missing_files(tmp_path, monkeypatch):
    directory = tmp_path / "inputs"
    directory.mkdir()
    core.write_new(directory / "INPUTS.json", {"plan_sha256": "bad", "files": {}})
    monkeypatch.setattr(run, "INPUTS", str(directory))
    with pytest.raises(ValueError, match="Input/plan"):
        run.inputs(core, run.read(run.ROOT / run.PLAN))


@pytest.mark.parametrize("arm", ["common", "raw_matched_control", "slot_contrast"])
def test_population_world_preserves_native_evaluation(monkeypatch, arm):
    from latent_workspace_ft_v10.v16_comparison_eval import evaluate

    learner = build(arm, torch.float32)
    store = make_store(monkeypatch, learner)
    records = store.records
    # Initialization is a useful hard null; the observer must not invent a direction.
    original = run.evaluate_world(
        core, learner, store.tokenizer, records[0], lambda *a: None, 9, {"random_memory_seed": 123}
    )
    before = core.state_fingerprint(learner)
    value = run.evaluate_world(
        core,
        learner,
        store.tokenizer,
        records[0],
        lambda *a: None,
        9,
        {"random_memory_seed": 123},
        original,
    )
    selected = core.legacy.LiveStore(learner, store.tokenizer, [records[0]], lambda *a: None)
    expected = evaluate(learner, selected, original=original["direct_base"], random_seed=132)
    for key in expected:
        assert value[key] == expected[key]
    assert len(value["traces"]) == 16
    assert core.state_fingerprint(learner) == before


def test_qualification_rejects_partial_receipts(tmp_path):
    path = tmp_path / "cpu"
    path.mkdir()
    core.write_new(path / "STARTED.json", {"seal": {}, "device": "cpu"})
    core.write_new(
        path / "FINISHED.json",
        {
            "status": "INCOMPLETE_NO_RETRY",
            "files": run.manifest(core, path),
            "counts": {"tests": 0},
        },
    )
    with pytest.raises(ValueError, match="Tiny suite"):
        run.qualification(core, tmp_path, {})


def test_changed_test_labels_do_not_affect_prompt_bytes():
    row = {"question": "Q", "choices": ["a", "b", "c", "d"], "answer": 1}
    altered = copy.deepcopy(row)
    altered["answer"] = 3
    assert prepare.example(row) == prepare.example(altered)
    assert prepare.example(row, answer=True) != prepare.example(altered, answer=True)
