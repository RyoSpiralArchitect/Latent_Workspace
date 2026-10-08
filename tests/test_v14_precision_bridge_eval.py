from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import v14_precision_bridge_eval as assay  # noqa: E402


class _Bridge(torch.nn.Module):
    def write_memory(self, hidden, mask):
        return hidden, mask

    def read_delta(self, query, memory, mask):
        assert not torch.is_grad_enabled()
        result = torch.zeros_like(query, dtype=torch.float32)
        result[..., 0] = query[..., 1] * memory[..., 0].mean(dim=-1, keepdim=True)
        return result


class _Adapter:
    def decode(self, normalized, delta, candidate_ids):
        assert tuple(candidate_ids) == (10, 11)
        gap = normalized[:, -1:, 0] + delta[..., 0]
        scores = torch.stack((-gap / 2, gap / 2), dim=-1)
        return SimpleNamespace(native_choice_scores=scores, fp32_choice_scores=scores)


class _Store:
    def __init__(self):
        self.records = [
            {
                "queries": [f"q{q}" for q in range(8)],
                "answers": [[1, 0, 1, 0, 1, 0, 1, 0], [0, 1, 1, 0, 1, 0, 1, 0]],
                "affected": [True, True] + [False] * 6,
                "heldout_queries": [False] * 4 + [True] * 4,
                "metadata": {"pair_id": f"w{w}"},
            }
            for w in range(2)
        ]
        self.features = []
        self.prefix_calls = []

    def context(self, world, side):
        del world
        value = 0.25 if side == "unrelated" else 1.0 if side == 0 else -1.0
        return torch.tensor([[[value, 0.0, 0.0, 0.0]]])

    def query(self, world, query):
        del world
        value = 1.0 if query == 0 else -1.0 if query == 1 else 0.0
        return torch.tensor([[[0.0, value, 0.0, 0.0]]])

    def get_prefix(self, prefix):
        self.prefix_calls.append(prefix)
        history_effect = (0.1 if prefix[-2] == 11 else -0.1) if len(prefix) > 2 else 0.0
        value = 1.0 if prefix[-1] == 100 else 0.0
        return torch.tensor([[[history_effect, value, 0.0, 0.0]]])


def _scenarios():
    result = []
    for world in range(2):
        for side in range(2):
            turns = [
                {
                    "turn_index": t,
                    "query_index": q,
                    "query_text": f"q{q}",
                    "query_suffix": (100 + q,),
                    "affected": q == 0,
                    "heldout": False,
                    "hop_distance": 1 if q == 0 else 5,
                    "original_label": (1 - side) if q == 0 else 1,
                    "donor_label": side if q == 0 else 1,
                }
                for t, q in enumerate(assay.TURN_QUERY_INDICES)
            ]
            result.append(
                {
                    "id": f"w{world}_s{side}",
                    "world_index": world,
                    "side": side,
                    "pair_id": f"w{world}",
                    "query_prefix": (100,),
                    "inline_prefix": (99, 100),
                    "candidate_ids": (10, 11),
                    "choice_text": ("no", "yes"),
                    "turns": turns,
                }
            )
    return result


def test_single_closes_controls_and_unique_pair_denominators():
    result = assay.evaluate_single(_Bridge().eval(), _Store(), _Adapter(), (10, 11), "cpu")
    assert result["row_count"] == 2 * 8 * 2 * 6
    assert result["winner"] == "none"
    for summary in result["summary"].values():
        assert summary["affected_correct_flip"]["count"] == 4
        assert summary["affected_correct_flip"]["mean"] == 1.0
        assert summary["affected_donor_signed_gap_change"]["mean"] == 2.0
        assert summary["unaffected_gap_change"]["mean_absolute"] == 0.0
        assert summary["control_accuracy"]["intact"]["heldout_template"]["count"] == 16
        assert summary["unrelated_delta_l2"]["count"] == 16
        assert summary["unrelated_gap_change_from_base"]["mean_absolute"] > 0.0


def test_random_memory_is_reproducible_norm_matched_and_rng_isolated():
    bridge, store = _Bridge().eval(), _Store()
    before = torch.random.get_rng_state().clone()
    with torch.no_grad():
        first = assay._memories(bridge, store, 0, "cpu")
        second = assay._memories(bridge, store, 0, "cpu")
        other = assay._memories(bridge, store, 1, "cpu")
    assert torch.equal(before, torch.random.get_rng_state())
    assert torch.equal(first[("norm_matched_random", 0)][0], second[("norm_matched_random", 0)][0])
    assert not torch.equal(
        first[("norm_matched_random", 0)][0], other[("norm_matched_random", 0)][0]
    )
    assert first[("norm_matched_random", 0)][0].norm().item() == pytest.approx(
        first[0][0].norm().item()
    )
    assert torch.equal(first["fixed_carrier"][0], other["fixed_carrier"][0])


def test_multiturn_closes_896_trajectories_and_respects_history_and_sampling():
    store = _Store()
    result = assay.evaluate_multiturn(
        {"task": _Bridge().eval(), "semantic": _Bridge().eval()},
        store,
        _Adapter(),
        None,
        _scenarios(),
        (10, 11),
        "cpu",
    )
    assert result["trajectory_count"] == 896
    assert result["turn_count"] == 3584
    assert result["independent_world_count"] == 2
    assert result["kv_cache"] is False
    assert result["semantic_promotion"] is False
    assert any(len(prefix) > 2 for prefix in store.prefix_calls)
    uniforms = {}
    for row in result["rows"]:
        expected = (
            [turn["original_label"] for turn in row["turns"]]
            if row["history_mode"] == assay.HISTORY_MODES[0]
            else row["generated_labels"]
        )
        assert row["appended_history_labels"] == expected
        for turn in row["turns"]:
            key = (row["scenario"], row["regime"], turn["turn_index"])
            uniforms.setdefault(key, turn["matched_uniform"])
            assert uniforms[key] == turn["matched_uniform"]
            assert turn["history_appended_labels_before_turn"] == expected[: turn["turn_index"]]
    for key, summary in result["summary"]["intact_twin_pairs"].items():
        assert summary["pair_count"] == 16
        assert summary["world_count"] == 2
        assert summary["affected_turn_count"] == 32
        for pair in summary["pairs"]:
            if pair["first_difference_turn"] is not None:
                assert pair["first_difference_prefix_equal"] is True
            if "teacher_forced_fixed_history" in key:
                assert all(turn["prefix_equal"] for turn in pair["turns"])


def test_eval_rejects_training_mode_and_changed_query_schedule():
    with pytest.raises(ValueError, match="eval"):
        assay.evaluate_single(_Bridge(), _Store(), _Adapter(), (10, 11), "cpu")
    scenarios = _scenarios()
    scenarios[0]["turns"][0]["query_index"] = 3
    with pytest.raises(ValueError, match="query order"):
        assay.evaluate_multiturn(
            {"task": _Bridge().eval(), "semantic": _Bridge().eval()},
            _Store(),
            _Adapter(),
            None,
            scenarios,
            (10, 11),
            "cpu",
        )


def test_summary_rejects_duplicate_observations():
    result = assay.evaluate_single(_Bridge().eval(), _Store(), _Adapter(), (10, 11), "cpu")
    with pytest.raises(ValueError, match="Duplicate"):
        assay.summarize_single(result["rows"] + [result["rows"][0]])
