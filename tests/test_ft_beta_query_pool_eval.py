from __future__ import annotations

import copy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ft_beta_query_pool_eval as assay  # noqa: E402


class Store:
    candidate_ids = (0, 1)

    def __init__(self):
        self.records = [
            {
                "queries": [f"q{q}" for q in range(8)],
                "answers": [[1, 0, 1, 0, 1, 0, 1, 0], [0, 1, 1, 0, 1, 0, 1, 0]],
                "affected": [True, True] + [False] * 6,
                "metadata": {"pair_id": f"world-{w}"},
            }
            for w in range(2)
        ]
        self.reader_modes = []

    def context(self, world, side):
        del world
        value = (
            1.0
            if side in (0, "reserialized_0")
            else -1.0
            if side in (1, "reserialized_1")
            else 0.25
        )
        return torch.tensor([[[value, 0.0, 0.0, 0.0]]])

    def query(self, world, query):
        del world
        gap = 0.1 if query < 2 else 1.0 if query % 2 == 0 else -1.0
        direction = 1.0 if query == 0 else -1.0 if query == 1 else 0.0
        return torch.tensor([[[0.0] * 4, [gap, direction, 0.0, 0.0]]])

    def reader_query(self, world, query, mode):
        self.reader_modes.append(mode)
        result = self.query(world, query)[:, -1:].clone()
        # Deliberately not a valid base-readout anchor: evaluator must ignore this coordinate.
        result[..., 0] = 999.0
        return result


class Bridge(torch.nn.Module):
    def write_memory(self, context, mask):
        return context, mask

    def read_delta(self, query, memory, mask):
        assert not torch.is_grad_enabled()
        del mask
        result = torch.zeros_like(query)
        result[..., 0] = query[..., 1] * memory[..., 0].mean(dim=-1, keepdim=True)
        return result


class ZeroBridge(Bridge):
    def read_delta(self, query, memory, mask):
        return torch.zeros_like(query)


class Adapter:
    def __init__(self):
        self.calls = []

    def decode(self, normalized, delta, candidate_ids):
        assert tuple(candidate_ids) == (0, 1)
        self.calls.append(tuple(normalized.shape))
        assert normalized.shape == (1, 2, 4)
        corrected = normalized.clone()
        corrected[:, -1:] += delta
        gap = corrected[..., 0]
        logits = torch.stack((-gap / 2, gap / 2), dim=-1)
        return SimpleNamespace(
            native_logits=logits,
            native_choice_scores=logits[:, -1:],
            fp32_choice_scores=logits[:, -1:],
            native_applied_delta=delta,
        )


def run(bridge=None, store=None, adapter=None, **kwargs):
    return assay.evaluate(
        (bridge or Bridge()).eval(),
        store or Store(),
        adapter or Adapter(),
        "question_span_mean",
        "cpu",
        **kwargs,
    )


def test_complete_panel_and_strict_success_gates_preserve_final_base_position():
    store, adapter, phases = Store(), Adapter(), []
    result = run(store=store, adapter=adapter, guard=phases.append)
    assert result["row_count"] == 256
    assert result["zero_full_logit_checks"] == 16
    assert result["initial_zero_checks"] == 0
    assert result["gates"] == {
        "tiny_feasibility": True,
        "fp32_objective_attainment": True,
        "separation_screen": True,
        "written_zero_full_logit_parity": True,
        "initial_all_controls_zero": None,
    }
    assert len(store.reader_modes) == 16 and set(store.reader_modes) == {"question_span_mean"}
    assert phases[0].endswith("memory:before") and phases[-1].endswith("q7:after")
    for readout in assay.READOUTS:
        summary = result["summary"][readout]
        assert summary["controls"]["intact"]["correct"] == 32
        assert summary["affected_count"] == summary["affected_correct_flips"] == 4
        assert summary["unaffected_count"] == 12
        assert summary["unaffected_prediction_flips"] == 0
        assert summary["donor_signed_changes"] == pytest.approx([2.0] * 4)
        assert summary["paired_correctness_ledger"] == {
            "both_correct": 28,
            "both_wrong": 0,
            "base_correct_candidate_wrong": 0,
            "base_wrong_candidate_correct": 4,
        }
    assert result["winner"] == "none" and result["semantic_promotion"] is False
    assert result["non_regression"] == "NOT_ESTABLISHED"


def test_step_zero_checks_every_unique_memory_and_does_not_establish_fit():
    result = run(bridge=ZeroBridge(), expect_initial_zero=True)
    assert result["initial_zero_checks"] == 16 * 10
    assert result["gates"]["initial_all_controls_zero"] is True
    assert result["gates"]["tiny_feasibility"] is False
    assert result["gates"]["fp32_objective_attainment"] is False
    assert result["gates"]["separation_screen"] is False


def test_initial_nonzero_and_broken_written_zero_fail_closed():
    with pytest.raises(RuntimeError, match="parity"):
        run(expect_initial_zero=True)

    class BadZero(Bridge):
        def read_delta(self, query, memory, mask):
            return torch.ones_like(query)

    with pytest.raises(RuntimeError, match="parity"):
        run(bridge=BadZero())


@pytest.mark.parametrize("native_only", [False, True])
def test_ties_never_become_correct_no_and_native_fp32_gates_are_separate(native_only):
    class TiedAdapter(Adapter):
        def decode(self, normalized, delta, candidate_ids):
            result = super().decode(normalized, delta, candidate_ids)
            result.native_logits = torch.zeros_like(result.native_logits)
            result.native_choice_scores = torch.zeros_like(result.native_choice_scores)
            if not native_only:
                result.fp32_choice_scores = torch.zeros_like(result.fp32_choice_scores)
            return result

    result = run(adapter=TiedAdapter())
    assert result["gates"]["tiny_feasibility"] is False
    native = result["summary"][assay.READOUTS[0]]
    assert native["controls"]["intact"]["correct"] == 0
    assert native["controls"]["intact"]["ties"] == 32
    assert all(
        row["dual_readout"][assay.READOUTS[0]]["greedy_choice"] is None for row in result["rows"]
    )
    assert result["summary"][assay.READOUTS[1]]["tiny_feasibility"] is native_only


def test_nonfinite_readout_is_rejected():
    class NonfiniteAdapter(Adapter):
        def decode(self, normalized, delta, candidate_ids):
            result = super().decode(normalized, delta, candidate_ids)
            result.fp32_choice_scores = result.fp32_choice_scores.clone()
            result.fp32_choice_scores[..., 0] = float("nan")
            return result

    with pytest.raises(ValueError, match="finite"):
        run(adapter=NonfiniteAdapter())


def test_wrong_direction_is_preserved_in_regression_ledger():
    class ReversedBridge(Bridge):
        def read_delta(self, query, memory, mask):
            return -super().read_delta(query, memory, mask)

    result = run(bridge=ReversedBridge())
    for summary in result["summary"].values():
        assert summary["affected_correct_flips"] == 0
        assert summary["donor_signed_changes"] == pytest.approx([-2.0] * 4)
        assert summary["paired_correctness_ledger"] == {
            "both_correct": 24,
            "both_wrong": 4,
            "base_correct_candidate_wrong": 4,
            "base_wrong_candidate_correct": 0,
        }
    assert result["gates"]["tiny_feasibility"] is False


def test_control_target_tampering_is_rejected_by_summary():
    rows = run()["rows"]
    rows[0]["target_label"] = 1 - rows[0]["target_label"]
    with pytest.raises(ValueError, match="metadata"):
        assay.summarize(rows)


def test_nonfinite_written_memory_fails_even_if_reader_would_ignore_it():
    class NonfiniteMemory(ZeroBridge):
        def write_memory(self, context, mask):
            return torch.full_like(context, float("nan")), mask

    with pytest.raises(ValueError, match="memory"):
        run(bridge=NonfiniteMemory())


@pytest.mark.parametrize("mutation", ["world", "query", "label", "affected", "count"])
def test_malformed_training_denominators_fail_before_model_calls(mutation):
    store, adapter = Store(), Adapter()
    if mutation == "world":
        store.records.pop()
    elif mutation == "query":
        store.records[0]["queries"].pop()
    elif mutation == "label":
        store.records[0]["answers"][0][0] = 3
    elif mutation == "affected":
        store.records[0]["affected"][0] = False
    else:
        store.records[0]["answers"][1][:2] = [1, 0]
        store.records[0]["affected"][:2] = [False, False]
    with pytest.raises(ValueError):
        run(store=store, adapter=adapter)
    assert adapter.calls == []


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "extra", "affected"])
def test_summary_rejects_malformed_raw_denominators(mutation):
    rows = copy.deepcopy(run()["rows"])
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows.append(rows[0])
    elif mutation == "extra":
        rows[0]["world_index"] = 9
    else:
        rows[0]["affected"] = False
    with pytest.raises(ValueError):
        assay.summarize(rows)


def test_training_mode_and_guard_abort_are_not_silently_recovered():
    with pytest.raises(ValueError, match="eval"):
        assay.evaluate(Bridge(), Store(), Adapter(), "last", "cpu")
    adapter = Adapter()

    def guard(label):
        raise RuntimeError("resource stop")

    with pytest.raises(RuntimeError, match="resource stop"):
        run(adapter=adapter, guard=guard)
    assert adapter.calls == []
