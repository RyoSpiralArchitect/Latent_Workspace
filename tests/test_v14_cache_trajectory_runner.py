"""Model-free contracts for the bounded V14 cache-trajectory runner."""

from __future__ import annotations

import importlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
canary = importlib.import_module("run_v14_cache_trajectory_canary")


@dataclass(frozen=True)
class TinySnapshot:
    layers: tuple[tuple[torch.Tensor, torch.Tensor], ...]
    seq_length: int


@dataclass(frozen=True)
class TinyDifferenceReceipt:
    aggregate_l2: float


def _snapshot(values: tuple[tuple[list[float], list[float]], ...]) -> TinySnapshot:
    layers = tuple(
        (
            torch.tensor(key, dtype=torch.float32).reshape(1, 1, -1, 1),
            torch.tensor(value, dtype=torch.float32).reshape(1, 1, -1, 1),
        )
        for key, value in values
    )
    return TinySnapshot(layers=layers, seq_length=layers[0][0].shape[-2])


def _difference(last_position_values: list[tuple[float, float]]) -> dict:
    return {
        "per_layer": [
            {
                "key_last_position_l2": key,
                "value_last_position_l2": value,
            }
            for key, value in last_position_values
        ]
    }


def _row_inputs() -> tuple[
    dict[str, list[int]], dict[str, torch.Tensor], dict[str, dict[str, float]]
]:
    histories = {name: [1, 2] for name in canary.CELL_PROTOCOL}
    logits = {
        name: torch.tensor([[[0.0, float(index), 2.0]]])
        for index, name in enumerate(canary.CELL_PROTOCOL)
    }
    differences = {
        name: {"aggregate_l2": 0.0 if name == "A" else float(index)}
        for index, name in enumerate(canary.CELL_PROTOCOL)
    }
    return histories, logits, differences


def test_row_freezes_query_and_cell_history_at_each_horizon() -> None:
    fixed_query_ids = [11, 12]
    candidate_ids = [0, 2]
    histories, logits, differences = _row_inputs()
    row_zero = canary._row(
        horizon=0,
        histories=histories,
        logits=logits,
        differences=differences,
        pulse_norm=0.25,
        reference_norm=0.25,
        equal_norm_tolerance=1e-6,
        equal_norm_verified=True,
        candidate_ids=candidate_ids,
        fixed_query_ids=fixed_query_ids,
    )

    for history in histories.values():
        history.append(3)
    row_one = canary._row(
        horizon=1,
        histories=histories,
        logits=logits,
        differences=differences,
        pulse_norm=0.25,
        reference_norm=0.25,
        equal_norm_tolerance=1e-6,
        equal_norm_verified=True,
        candidate_ids=candidate_ids,
        fixed_query_ids=fixed_query_ids,
    )
    fixed_query_ids.append(99)
    candidate_ids.append(1)

    assert row_zero["query_token_ids"] == [11, 12]
    assert row_one["query_token_ids"] == [11, 12]
    assert row_zero["probe_token_ids"] == [0, 2]
    assert row_one["probe_token_ids"] == [0, 2]
    assert row_zero["affected"] is False
    assert row_zero["original_label"] == row_zero["donor_label"] == 0
    for name in canary.CELL_PROTOCOL:
        assert row_zero["cells"][name]["token_ids"] == [1, 2]
        assert row_zero["cells"][name]["position_ids"] == [0, 1]
        assert row_zero["cells"][name]["attention_mask"] == [1, 1]
        assert row_one["cells"][name]["token_ids"] == [1, 2, 3]
        assert row_one["cells"][name]["position_ids"] == [0, 1, 2]
        assert row_one["cells"][name]["attention_mask"] == [1, 1, 1]


def test_snapshot_regions_separates_prior_lower_and_selected_positions() -> None:
    base = _snapshot(
        (
            ([1, 2, 3], [4, 5, 6]),
            ([7, 8, 9], [10, 11, 12]),
            ([13, 14, 15], [16, 17, 18]),
        )
    )
    changed = _snapshot(
        (
            ([1, 2, 3], [4, 5, 6]),
            ([7, 8, 90], [10, 11, 120]),
            ([13, 14, 150], [16, 17, 180]),
        )
    )
    assert canary._snapshot_regions(base, changed, pulse_layer=1) == {
        "all_prior_positions_exact": True,
        "layers_below_pulse_current_position_exact": True,
        "selected_layer_current_position_changed": True,
    }

    prior_corrupt = _snapshot(
        (
            ([99, 2, 3], [4, 5, 6]),
            ([7, 8, 90], [10, 11, 120]),
            ([13, 14, 150], [16, 17, 180]),
        )
    )
    lower_corrupt = _snapshot(
        (
            ([1, 2, 30], [4, 5, 6]),
            ([7, 8, 90], [10, 11, 120]),
            ([13, 14, 150], [16, 17, 180]),
        )
    )
    selected_unchanged = _snapshot(
        (
            ([1, 2, 3], [4, 5, 6]),
            ([7, 8, 9], [10, 11, 12]),
            ([13, 14, 150], [16, 17, 180]),
        )
    )
    assert canary._snapshot_regions(base, prior_corrupt, pulse_layer=1)[
        "all_prior_positions_exact"
    ] is False
    assert canary._snapshot_regions(base, lower_corrupt, pulse_layer=1)[
        "layers_below_pulse_current_position_exact"
    ] is False
    assert canary._snapshot_regions(base, selected_unchanged, pulse_layer=1)[
        "selected_layer_current_position_changed"
    ] is False

    with pytest.raises(ValueError, match="layouts differ"):
        canary._snapshot_regions(
            base,
            SimpleNamespace(seq_length=2, layers=changed.layers),
            pulse_layer=1,
        )


def test_future_position_structure_requires_exact_lower_and_changed_upper_layers() -> None:
    expected = _difference([(0.0, 0.0), (0.0, 0.0), (0.5, 0.0)])
    assert canary._future_position_structure(expected, pulse_layer=1) == {
        "layers_through_pulse_new_position_exact": True,
        "layer_above_pulse_new_position_changed": True,
    }

    selected_changed = _difference([(0.0, 0.0), (0.25, 0.0), (0.5, 0.0)])
    no_upper_change = _difference([(0.0, 0.0), (0.0, 0.0), (0.0, 0.0)])
    assert canary._future_position_structure(selected_changed, pulse_layer=1)[
        "layers_through_pulse_new_position_exact"
    ] is False
    assert canary._future_position_structure(no_upper_change, pulse_layer=1)[
        "layer_above_pulse_new_position_changed"
    ] is False


def test_stored_position_stability_ignores_appends_but_detects_rewrites() -> None:
    initial = _snapshot((([1, 2, 3], [4, 5, 6]), ([7, 8, 9], [10, 11, 12])))
    appended = _snapshot(
        (([1, 2, 3, 30, 31], [4, 5, 6, 40, 41]), ([7, 8, 9, 50, 51], [10, 11, 12, 60, 61]))
    )
    rewritten = _snapshot(
        (([1, 2, 300, 30, 31], [4, 5, 6, 40, 41]), ([7, 8, 9, 50, 51], [10, 11, 12, 60, 61]))
    )

    assert canary._stored_position_stable(initial, appended, position=2) is True
    assert canary._stored_position_stable(initial, rewritten, position=2) is False
    assert (
        canary._stored_position_stable(
            initial,
            TinySnapshot(layers=appended.layers[:1], seq_length=5),
            position=2,
        )
        is False
    )


class TinyNoCacheModel(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.call: dict | None = None

    def forward(
        self,
        *,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor,
        position_ids: torch.Tensor,
        past_key_values,
        use_cache: bool,
    ):
        self.call = {
            "input_ids": input_ids.clone(),
            "attention_mask": attention_mask.clone(),
            "position_ids": position_ids.clone(),
            "past_key_values": past_key_values,
            "use_cache": use_cache,
        }
        logits = torch.nn.functional.one_hot(input_ids % 5, num_classes=5).float()
        return SimpleNamespace(logits=logits, past_key_values=None)


def test_full_recompute_is_explicitly_cache_free_and_uses_complete_history() -> None:
    model = TinyNoCacheModel()
    history = [1, 3, 4]
    cached_logits = torch.nn.functional.one_hot(torch.tensor([[[4]]]), num_classes=5).float()
    cached_logits = cached_logits.reshape(1, 1, 5)
    receipt = canary._full_recompute_receipt(model, history, cached_logits, [1, 4])

    assert model.call is not None
    assert model.call["past_key_values"] is None
    assert model.call["use_cache"] is False
    assert torch.equal(model.call["input_ids"], torch.tensor([[1, 3, 4]]))
    assert torch.equal(model.call["attention_mask"], torch.ones((1, 3), dtype=torch.long))
    assert torch.equal(model.call["position_ids"], torch.tensor([[0, 1, 2]]))
    assert receipt == {
        "history_length": 3,
        "cache_returned": False,
        "exact_equal": True,
        "l2": 0.0,
        "max_abs": 0.0,
        "cached_candidate_logits": [0.0, 1.0],
        "recomputed_candidate_logits": [0.0, 1.0],
        "comparison_role": "CROSS_SHAPE_DIAGNOSTIC_NOT_AN_EXACT_CLONE_GATE",
    }


def test_deterministic_tensor_and_difference_helpers_are_fail_closed() -> None:
    tensor = torch.tensor([[1.0, 2.0]], dtype=torch.float32)
    assert canary._tensor_sha256(tensor) == canary._tensor_sha256(tensor.clone())
    assert canary._difference_l2({"aggregate_l2": 1.25}) == 1.25
    assert canary._difference_l2(TinyDifferenceReceipt(aggregate_l2=2.5)) == 2.5
    with pytest.raises(ValueError, match="no aggregate L2"):
        canary._difference_l2({"exact_equal": True})
    with pytest.raises(ValueError, match="shape mismatch"):
        canary._full_logit_l2(torch.zeros(1, 2), torch.zeros(1, 3))
    with pytest.raises(ValueError, match="Nonfinite"):
        canary._candidate_logits(torch.tensor([[[float("nan"), 0.0]]]), [0])


def test_checked_in_plan_matches_the_hard_mechanical_contract() -> None:
    plan_path = Path(__file__).resolve().parents[1] / "configs/v14/CACHE_TRAJECTORY_PLAN.json"
    plan = json.loads(plan_path.read_text())
    canary._validate_plan_contract(plan)
    assert plan["source_identity"] == canary._source_identity()

    changed = json.loads(plan_path.read_text())
    changed["pulse"]["horizon"] = 1
    with pytest.raises(ValueError, match="pulse_horizon"):
        canary._validate_plan_contract(changed)


def test_model_config_projection_uses_nested_transformers_5_rope_contract() -> None:
    config = SimpleNamespace(
        model_type="mistral",
        hidden_size=4096,
        intermediate_size=14336,
        num_hidden_layers=32,
        num_attention_heads=32,
        num_key_value_heads=8,
        head_dim=128,
        rms_norm_eps=1e-5,
        rope_parameters={"rope_theta": 1_000_000.0, "rope_type": "default"},
        max_position_embeddings=32768,
        sliding_window=None,
        _attn_implementation="sdpa",
    )
    assert canary._model_config_projection(config)["rope_parameters"] == {
        "rope_theta": 1_000_000.0,
        "rope_type": "default",
    }
