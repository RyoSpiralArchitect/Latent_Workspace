from __future__ import annotations

import copy
import sys
from dataclasses import asdict
from pathlib import Path

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_v15_5_native_answer as runner
import verify_v15_5_native_answer as verifier

from latent_workspace_ft_v10.precision_bridge import PrecisionAwareWorkspaceBridge
from latent_workspace_ft_v10.reader_query import QuestionSpan
from latent_workspace_ft_v10.v15_pipeline import NativeWorkspacePipeline
from latent_workspace_ft_v10.v15_readout import NativeWorkspaceReadout


class TinyStore:
    def __init__(self):
        self.records = [{"answers": [[0, 1] * 4, [1, 0] + [0, 1] * 3]} for _ in range(2)]
        span = QuestionSpan("A?", 0, 2, (0, 1), (1, 4, 5), "fixture")
        row = {"prompt_ids": [1, 4, 5], "candidate_ids": [6, 7], "span": asdict(span)}
        self.renderings = {(w, q): copy.deepcopy(row) for w in range(2) for q in range(8)}
        self.hidden = torch.randn(1, 3, 8)
        self.extended = {6: torch.randn(1, 4, 8), 7: torch.randn(1, 4, 8)}
        self.context = torch.randn(1, 3, 8)
        self.requests = []

    def get(self, prefix):
        self.requests.append(prefix)
        return self.hidden if len(prefix) == 3 else self.extended[prefix[-1]]

    def write(self, bridge, world, key):
        shift = 0 if key == 0 else 0.2 if key == 1 else 0.4
        return bridge.write_memory(self.context + shift, torch.ones(1, 3))


def fixture():
    torch.manual_seed(47)
    bridge = PrecisionAwareWorkspaceBridge(8, workspace_dim=4, heads=2, slots=2)
    head = torch.nn.Linear(8, 11, bias=False).requires_grad_(False)
    return NativeWorkspacePipeline(bridge, NativeWorkspaceReadout(head), "final"), TinyStore()


def test_current_plan_graph_truth_and_balanced_denominators():
    plan, parent, records = runner.validate()
    assert plan["training"]["steps"] == 8
    assert parent["bridge"]["max_delta_norm"] == 1.0
    assert len(records) == 2
    assert sum(a != b for r in records for a, b in zip(*r["answers"], strict=True)) == 4


@pytest.mark.parametrize("query", [0, 1, 2, 3])
def test_one_factor_loss_keeps_answer_and_nuisance_terms_identical(query):
    plan, _, _ = runner.validate()
    pipe, store = fixture()
    plain, first = runner.pair_objective(pipe, store, 0, query, plan["training"], 0.0)
    joint, second = runner.pair_objective(pipe, store, 0, query, plan["training"], 1.0)
    for key in first:
        assert torch.equal(first[key], second[key])
    torch.testing.assert_close(joint - plain, first["eos_ce"])
    labels = {store.records[0]["answers"][side][query] for side in (0, 1)}
    assert set(store.requests) == {(1, 4, 5)} | {(1, 4, 5, 6 + label) for label in labels}


def test_complete_batch_reduction_matches_mean_over_32_answer_rows():
    plan, _, _ = runner.validate()
    pipe, store = fixture()
    terms = [
        runner.pair_objective(pipe, store, w, q, plan["training"], 0.0)[1]
        for w in range(2)
        for q in range(8)
    ]
    scores = pipe.readout.head(store.hidden)[:, -1].float()
    expected = (
        torch.nn.functional.cross_entropy(scores, torch.tensor([6]))
        + torch.nn.functional.cross_entropy(scores, torch.tensor([7]))
    ) / 2
    torch.testing.assert_close(sum(t["answer_ce"] for t in terms), expected)
    # Zero-initialized bridge gives zero donor change and exactly one globally
    # averaged 0.25 hinge, not four duplicated or sixteen diluted hinges.
    torch.testing.assert_close(sum(t["donor_hinge"] for t in terms), torch.tensor(0.25))
    assert sum(t["unaffected_gap_square"] for t in terms) == 0


def test_generation_bypasses_training_feature_memoization():
    backend = object.__new__(runner.GenerationBackend)

    class Store:
        def get(self, prefix):
            raise AssertionError("Generation must recompute full prefixes")

        def encode(self, prefix):
            return prefix

    backend.store = Store()
    assert backend.encode((1, 2, 3)) == (1, 2, 3)


def test_evaluation_replay_separates_control_missing_truth_and_four_donor_pairs():
    records = TinyStore().records
    rows = []
    for w in range(2):
        for q in range(8):
            for control in verifier.CONTROLS:
                side = (
                    0
                    if control in ("intact", "reverse_intact")
                    else (1 if control in ("twin", "reverse_twin") else None)
                )
                target = records[w]["answers"][side][q] if side is not None else None
                prediction = target if target is not None else 0
                rows.append(
                    {
                        "world": w,
                        "query": q,
                        "control": control,
                        "target_label": target,
                        "native_prediction": prediction,
                        "native_scores": [1 - prediction, prediction],
                        "base_native_scores": [1, 0],
                        "correct": True if target is not None else None,
                        "base_correct": target == 0 if target is not None else None,
                        "delta_l2": 0 if target is None else 0.5,
                        "full_logits_equal_base": prediction == 0,
                        "max_abs_logit_change": prediction,
                        "total_variation": prediction * 0.1,
                    }
                )
    result = verifier.eval_summary(rows, records, 8)
    assert result["controls"]["zero"]["correct"] is None
    assert result["controls"]["intact"]["correct"] == 16
    assert [r["donor_signed_change"] for r in result["unique_affected_pairs"]] == [2] * 4
    rows[0]["correct"] = False
    with pytest.raises(ValueError, match="arithmetic"):
        verifier.eval_summary(rows, records, 8)


def generation_fixture():
    records = [{"answers": [[0, 1] * 4, [1, 0] + [0, 1] * 3]} for _ in range(2)]
    rows = []
    for world in range(2):
        for query in range(2):
            for condition in verifier.CONDITIONS:
                label = records[world]["answers"][int(condition == "twin")][query]
                tokens = [6 + label, 2]
                rows.append(
                    {
                        "world": world,
                        "query": query,
                        "condition": condition,
                        "generated_ids": tokens,
                        "token_count": 2,
                        "token_trace": [{"token_id": token} for token in tokens],
                        "finish_reason": "eos",
                        "answer": ("no", "yes")[label],
                        "parsed_answer": label,
                        "target_label": label,
                        "valid_eos": True,
                        "strict_correct": True,
                    }
                )
    return rows, records


def test_generation_replay_retains_whole_answer_scoring():
    rows, records = generation_fixture()
    assert verifier.generation_summary(rows, records)["workspace"]["strict_correct"] == 4
    row = next(r for r in rows if r["condition"] == "workspace")
    row.update(
        answer="no, because I think so", parsed_answer=None, valid_eos=False, strict_correct=False
    )
    assert verifier.generation_summary(rows, records)["workspace"]["strict_correct"] == 3
    row.update(parsed_answer=0, valid_eos=True, strict_correct=True)
    with pytest.raises(ValueError, match="Whole-answer"):
        verifier.generation_summary(rows, records)


@pytest.mark.parametrize("kind", ["missing", "duplicate", "wrong_eos", "over_budget", "trace"])
def test_generation_replay_rejects_incomplete_or_inconsistent_receipts(kind):
    rows, records = generation_fixture()
    if kind == "missing":
        rows.pop()
    elif kind == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    elif kind == "wrong_eos":
        rows[0]["generated_ids"][-1] = 8
        rows[0]["token_trace"][-1]["token_id"] = 8
    elif kind == "over_budget":
        rows[0]["generated_ids"] *= 9
    else:
        rows[0]["token_trace"].pop()
    with pytest.raises(ValueError):
        verifier.generation_summary(rows, records)
