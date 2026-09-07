"""Model-free checks for the checkpoint-derived native direction gate."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
import torch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

gate = importlib.import_module("run_v14_checkpoint_direction_gate")


def test_direction_stats_preserve_natural_rms_and_identity() -> None:
    vector = torch.tensor([1.0, -1.0, 0.0, 2.0], dtype=torch.bfloat16)
    observed = gate._direction_stats(vector)
    assert observed["shape"] == [4]
    assert observed["source_dtype"] == "torch.bfloat16"
    assert observed["analysis_dtype"] == "torch.float32"
    assert observed["finite"] is True
    assert observed["nonzero"] is True
    assert observed["nonzero_elements"] == 3
    assert observed["rms"] == pytest.approx((6.0 / 4.0) ** 0.5)
    assert len(observed["sha256"]) == 64


def test_candidate_readout_keeps_ties_unknown_and_orients_donor_margin() -> None:
    logits = torch.zeros((1, 1, 8), dtype=torch.float32)
    logits[0, 0, 2] = -1.0
    logits[0, 0, 5] = 3.0
    receipt = gate._candidate_readout(logits, [2, 5], original_label=0, donor_label=1)
    assert receipt["candidate_logits"] == [-1.0, 3.0]
    assert receipt["prediction"] == 1
    assert receipt["tie"] is False
    assert receipt["original_margin"] == -4.0
    assert receipt["donor_margin"] == 4.0

    tie = gate._candidate_readout(torch.zeros((1, 1, 8)), [2, 5], original_label=1, donor_label=1)
    assert tie["prediction"] is None
    assert tie["tie"] is True
    assert tie["donor_margin"] == 0.0


def test_compact_difference_tracks_changed_layer_span() -> None:
    receipt = {
        "aggregate_l2": 2.0,
        "aggregate_max_abs": 1.0,
        "nonzero_count": 3,
        "exact_equal": False,
        "per_layer": [
            {"layer": 0, "key_nonzero": 0, "value_nonzero": 0},
            {"layer": 1, "key_nonzero": 2, "value_nonzero": 0},
            {"layer": 2, "key_nonzero": 0, "value_nonzero": 1},
        ],
    }
    assert gate._compact_difference(receipt) == {
        "aggregate_l2": 2.0,
        "aggregate_max_abs": 1.0,
        "nonzero_count": 3,
        "exact_equal": False,
        "changed_layers": [1, 2],
        "first_changed_layer": 1,
        "last_changed_layer": 2,
    }


def test_row_gate_requires_native_distinction_not_only_nonzero_vectors() -> None:
    direction = {"finite": True, "nonzero": True}
    pulse = {
        "applied": True,
        "call_count": 1,
        "actual_delta_rms": 0.1,
        "actual_signed_projection": 1.0,
    }
    difference = {"exact_equal": False}
    row = {
        "directions": {name: dict(direction) for name in ("i", "t", "d")},
        "pulse_receipts": {name: dict(pulse) for name in ("i", "t", "d")},
        "cache_differences": {
            "base_vs_intact": dict(difference),
            "base_vs_twin": dict(difference),
            "base_vs_semantic_delta": dict(difference),
            "intact_vs_twin": {"exact_equal": True},
        },
    }
    checks = gate._row_gate(row)
    assert checks["all_direction_vectors_finite_nonzero"] is True
    assert checks["all_native_cast_deltas_nonzero"] is True
    assert checks["all_intact_twin_caches_are_distinct"] is False


def test_plan_validator_rejects_amplitude_selection() -> None:
    plan = {
        "format": "latent-workspace-v14-checkpoint-direction-gate-plan-v1",
        "frozen_before_target_model_scoring": True,
        "input_lane": "retained_inline_checkpoint_compatibility",
        "max_worlds": 2,
        "expected_rows": 32,
        "world_selection": "first_n_complete_records_in_file_order",
        "modes": ["intact", "counterfactual_twin"],
        "pulse": {
            "layer": 16,
            "boundary": "decoder_layer_input_pre_rmsnorm",
            "composition_dtype": "fp32_add_then_cast_to_hidden",
            "amplitude": "natural_vector_rms_no_gain",
            "directions": ["intact_update", "twin_update", "twin_minus_intact"],
        },
        "mechanical_gates": {
            "all_direction_vectors_finite_nonzero": True,
            "all_pulses_applied_once": True,
            "all_native_cast_deltas_nonzero": True,
            "all_actual_projections_follow_requested_sign": True,
            "all_direction_caches_differ_from_base": True,
            "all_intact_twin_caches_are_distinct": True,
            "frozen_row_count_complete": True,
            "all_inputs_and_parameters_unchanged": True,
        },
        "authorized_actions": {
            "checkpoint_load": True,
            "checkpoint_direction_capture": True,
            "native_cache_pulse": True,
            "optimizer_or_training": False,
            "free_generation": False,
            "model_download": False,
            "weight_write_or_delete": False,
            "amplitude_layer_or_row_selection": False,
            "semantic_success_claim": False,
        },
    }
    gate._validate_plan(plan)
    plan["pulse"]["amplitude"] = "choose_best_gain"
    with pytest.raises(gate.DirectionGateError, match="Frozen plan contract mismatch"):
        gate._validate_plan(plan)


def test_frozen_plan_contract_and_source_hashes_are_self_consistent() -> None:
    plan = gate.json.loads(gate.PLAN_PATH.read_text(encoding="utf-8"))
    gate._validate_plan(plan)
    assert gate._source_identity(plan) == plan["source_identity"]
