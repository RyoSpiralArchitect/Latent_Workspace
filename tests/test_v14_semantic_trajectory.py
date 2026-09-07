"""Model-free checks for the V14 checkpoint-direction trajectory."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
import torch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

trajectory = importlib.import_module("run_v14_semantic_trajectory")


def test_gram_matched_random_pair_preserves_full_pair_geometry() -> None:
    intact = torch.tensor([1.0, 2.0, -1.0, 0.5])
    twin = torch.tensor([-0.5, 1.0, 2.0, 1.5])
    random_intact, random_twin, receipt = trajectory._gram_matched_random_pair(
        intact, twin, seed=1415
    )
    assert random_intact.shape == intact.shape
    assert random_twin.shape == twin.shape
    assert receipt["relative_error"]["maximum"] < 1e-6
    assert trajectory._gram(random_intact, random_twin)["cosine"] == pytest.approx(
        trajectory._gram(intact, twin)["cosine"], abs=1e-7
    )


def test_scale_to_rms_matches_target_and_rejects_zero() -> None:
    value = torch.tensor([1.0, -2.0, 3.0, -4.0])
    result = trajectory._scale_to_rms(value, 0.25)
    assert torch.sqrt(torch.mean(result * result)).item() == pytest.approx(0.25)
    with pytest.raises(trajectory.TrajectoryError, match="zero or nonfinite"):
        trajectory._scale_to_rms(torch.zeros(4), 0.25)


class TinyAdapter:
    def __init__(self) -> None:
        self.model = torch.nn.Linear(2, 2)
        self.validated = None
        self.forwarded = None

    def _cache_length(self, cache) -> int:
        assert cache == "cache"
        return 3

    def _validate_forward_inputs(
        self, tokens, mask, positions, *, past_length: int, one_token: bool
    ) -> None:
        self.validated = (tokens.clone(), mask.clone(), positions.clone(), past_length, one_token)

    def _forward(self, **kwargs):
        self.forwarded = kwargs
        return "result"


def test_extend_fixed_chunk_uses_one_matched_cached_call() -> None:
    adapter = TinyAdapter()
    observed = trajectory._extend_fixed_chunk(adapter, "cache", (7, 8))
    assert observed == "result"
    assert adapter.validated is not None
    tokens, mask, positions, past_length, one_token = adapter.validated
    assert tokens.tolist() == [[7, 8]]
    assert mask.tolist() == [[1, 1, 1, 1, 1]]
    assert positions.tolist() == [[3, 4]]
    assert past_length == 3
    assert one_token is False
    assert adapter.forwarded["cache"] == "cache"
    assert adapter.forwarded["pulse"] is None
    assert adapter.forwarded["clone_cache"] is True


def test_plan_contract_rejects_free_generation() -> None:
    plan = {
        "format": "latent-workspace-v14-semantic-trajectory-plan-v1",
        "frozen_before_target_model_scoring": True,
        "input_lane": "retained_inline_checkpoint_compatibility",
        "max_worlds": 2,
        "selected_query_indices": [0, 1, 2, 3],
        "expected_cases": 16,
        "turn_count": 5,
        "expected_trajectory_rows": 320,
        "cells": list(trajectory.CELLS),
        "controls": list(trajectory.CONTROLS),
        "fixed_turn": {
            "force_original_answer_token": True,
            "repeat_same_query": True,
            "separator": "\n",
            "one_cached_call_per_turn_chunk": True,
            "identical_tokens_across_cells": True,
            "free_generation": False,
        },
        "pulse": {
            "layer": 16,
            "boundary": "decoder_layer_input_pre_rmsnorm",
            "composition_dtype": "fp32_add_then_cast_to_hidden",
            "semantic_amplitude": "natural_vector_rms_no_gain",
            "random_control": "preserve_intact_twin_gram_matrix",
            "unrelated_control": "other_world_same_side_query_scaled_to_target_rms",
        },
        "authorized_actions": {
            "checkpoint_load": True,
            "checkpoint_direction_capture": True,
            "fixed_teacher_forced_cache_trajectory": True,
            "optimizer_or_training": False,
            "free_generation": False,
            "model_download": False,
            "weight_write_or_delete": False,
            "gain_layer_query_or_horizon_selection": False,
            "semantic_promotion": False,
        },
    }
    trajectory._validate_plan(plan)
    plan["fixed_turn"]["free_generation"] = True
    with pytest.raises(trajectory.TrajectoryError, match="Frozen plan contract mismatch"):
        trajectory._validate_plan(plan)


def test_frozen_plan_contract_and_source_hashes_are_self_consistent() -> None:
    plan = trajectory.json.loads(trajectory.PLAN_PATH.read_text(encoding="utf-8"))
    trajectory._validate_plan(plan)
    assert trajectory._source_identity(plan) == plan["source_identity"]
