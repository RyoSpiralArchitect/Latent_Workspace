from __future__ import annotations

import copy
import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/v13_paired_metrics.py"
SPEC = importlib.util.spec_from_file_location("v13_paired_metrics", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
metrics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metrics)


def _row(query: str = "q", **changes: object) -> dict:
    row = {
        "original_world_family_id": "family-a",
        "pair_id": "pair-a",
        "query_id": query,
        "original_label": 0,
        "donor_label": 1,
        "intact_logits": [2.0, 0.0],
        "swapped_logits": [0.0, 2.0],
    }
    return {**row, **changes}


def _summary(rows: list[dict]) -> dict:
    return metrics.summarize_pairs(rows)["groups"][0]


def test_good_directed_effect_and_fp32_donor_gain() -> None:
    row = _row()
    before = copy.deepcopy(row)
    result = metrics.summarize_pairs([row])
    affected = result["groups"][0]["affected"]
    assert affected["transition_table"]["original_to_donor"] == 1
    assert affected["desired_flip_per_all_affected"]["rate"] == 1.0
    assert affected["desired_flip_per_intact_correct"]["denominator"] == 1
    assert affected["donor_gain"]["values"] == [4.0]
    assert affected["prediction_transition_matrix"] == [[0, 1], [0, 0]]
    assert result["status"] == "DESCRIPTIVE_ONLY"
    assert result["execution_ready"] is False
    assert "passed" not in result and "promoted" not in result
    assert row == before


def test_memory_blind_already_predicts_donor_is_not_a_desired_flip() -> None:
    affected = _summary([_row(intact_logits=[0.0, 2.0])])["affected"]
    assert affected["swapped_donor_accuracy"]["rate"] == 1.0
    assert affected["transition_table"]["donor_to_donor"] == 1
    assert affected["desired_flip_per_all_affected"]["rate"] == 0.0
    assert affected["desired_flip_per_intact_correct"]["denominator"] == 0
    assert affected["desired_flip_per_intact_correct"]["rate"] is None
    assert affected["donor_gain"]["values"] == [0.0]


def test_identity_has_zero_gain_and_zero_flip_not_missing() -> None:
    affected = _summary([_row(swapped_logits=[2.0, 0.0], control="identity")])["affected"]
    assert affected["measurement_status"] == "OBSERVED"
    assert affected["transition_table"]["original_to_original"] == 1
    assert affected["donor_gain"]["observed_count"] == 1
    assert affected["donor_gain"]["zero_count"] == 1
    assert affected["desired_flip_per_all_affected"]["rate"] == 0.0


def test_all_four_affected_transitions_and_two_denominators() -> None:
    rows = [
        _row("directed"),
        _row("stayed-original", swapped_logits=[2.0, 0.0]),
        _row("already-donor", intact_logits=[0.0, 2.0]),
        _row("wrong-to-original", intact_logits=[0.0, 2.0], swapped_logits=[2.0, 0.0]),
    ]
    affected = _summary(rows)["affected"]
    assert set(affected["transition_table"].values()) == {1}
    assert affected["prediction_transition_matrix"] == [[1, 1], [1, 1]]
    assert affected["desired_flip_per_all_affected"]["denominator"] == 4
    assert affected["desired_flip_per_all_affected"]["rate"] == 0.25
    assert affected["desired_flip_per_intact_correct"]["denominator"] == 2
    assert affected["desired_flip_per_intact_correct"]["rate"] == 0.5
    assert affected["donor_gain"]["values"] == [4.0, 0.0, 0.0, -4.0]


def test_reverse_labels_preserve_donor_direction() -> None:
    affected = _summary(
        [_row(original_label=1, donor_label=0, intact_logits=[0.0, 2.0], swapped_logits=[2.0, 0.0])]
    )["affected"]
    assert affected["transition_table"]["original_to_donor"] == 1
    assert affected["donor_gain"]["mean"] == 4.0
    assert affected["label1_minus_label0_shift"]["mean"] == -4.0


def test_preserved_unaffected_wrong_answer_is_agreement_not_correct_retention() -> None:
    unaffected = _summary([_row(donor_label=0, intact_logits=[0.0, 2.0])])["unaffected"]
    assert unaffected["transition_table"]["wrong_to_wrong"] == 1
    assert unaffected["prediction_agreement"]["rate"] == 1.0
    assert unaffected["intact_original_accuracy"]["rate"] == 0.0
    assert unaffected["swapped_donor_accuracy"]["rate"] == 0.0
    assert unaffected["correct_retention_per_all_unaffected"]["rate"] == 0.0
    assert unaffected["agreement_is_correctness_or_causal_credit"] is False


def test_all_four_unaffected_transitions_keep_repair_and_damage_separate() -> None:
    rows = [
        _row("kept-correct", donor_label=0, swapped_logits=[2.0, 0.0]),
        _row("damaged", donor_label=0),
        _row("repaired", donor_label=0, intact_logits=[0.0, 2.0], swapped_logits=[2.0, 0.0]),
        _row("kept-wrong", donor_label=0, intact_logits=[0.0, 2.0]),
    ]
    unaffected = _summary(rows)["unaffected"]
    assert set(unaffected["transition_table"].values()) == {1}
    assert unaffected["prediction_transition_matrix"] == [[1, 1], [1, 1]]
    assert unaffected["prediction_agreement"]["rate"] == 0.5
    assert unaffected["intact_original_accuracy"]["rate"] == 0.5
    assert unaffected["swapped_donor_accuracy"]["rate"] == 0.5
    assert unaffected["correct_to_wrong_per_all_unaffected"]["rate"] == 0.25
    assert unaffected["wrong_to_correct_per_all_unaffected"]["rate"] == 0.25


@pytest.mark.parametrize(
    "logits",
    [
        None,
        [float("nan"), 1.0],
        [1.0, float("inf")],
        [1e100, 0.0],
        [True, 1.0],
        ["2", "0"],
        [1.0],
        [],
        {},
    ],
)
def test_missing_invalid_or_nonfinite_logits_remain_unknown(logits: object) -> None:
    result = metrics.summarize_pairs([_row(intact_logits=logits)])
    affected = result["groups"][0]["affected"]
    assert affected["row_count"] == affected["unknown_pair_count"] == 1
    assert affected["observed_pair_count"] == 0
    assert affected["continuous_observed_pair_count"] == 0
    assert affected["continuous_unknown_pair_count"] == 1
    assert affected["donor_gain"]["values"] == []
    assert affected["donor_gain"]["mean"] is None
    assert affected["desired_flip_per_all_affected"]["rate"] is None
    assert affected["desired_flip_per_all_affected"]["bounds"] == [0.0, 1.0]
    assert affected["desired_flip_per_intact_correct"]["denominator_status"] == "UNKNOWN"
    assert affected["desired_flip_per_intact_correct"]["unknown_intact_count"] == 1
    assert affected["unknown_reason_counts"]
    # No nonfinite scalar leaks into the receipt or gets silently replaced by a zero effect.
    json.dumps(result, allow_nan=False)


def test_finite_tie_keeps_continuous_gain_but_flip_remains_unknown() -> None:
    group = _summary([_row(intact_logits=[0.0, 0.0], swapped_logits=[0.0, 2.0])])
    affected = group["affected"]
    assert affected["observed_pair_count"] == 0
    assert affected["unknown_pair_count"] == 1
    assert affected["continuous_observed_pair_count"] == 1
    assert affected["continuous_unknown_pair_count"] == 0
    assert affected["donor_gain"]["values"] == [2.0]
    assert affected["donor_gain"]["unknown_count"] == 0
    assert affected["label1_minus_label0_shift"]["values"] == [2.0]
    assert affected["prediction_transition_matrix"] == [[0, 0], [0, 0]]
    assert affected["desired_flip_per_all_affected"]["rate"] is None
    assert affected["desired_flip_per_intact_correct"]["rate"] is None
    assert group["per_case"][0]["pair_status"] == "UNKNOWN"
    assert group["per_case"][0]["continuous_status"] == "OBSERVED"


def test_absent_swapped_logits_stay_in_intact_correct_denominator() -> None:
    missing = _row("missing")
    missing.pop("swapped_logits")
    affected = _summary([_row("observed"), missing])["affected"]
    assert affected["measurement_status"] == "PARTIAL_UNKNOWN"
    assert affected["desired_flip_per_all_affected"]["denominator"] == 2
    assert affected["desired_flip_per_all_affected"]["rate"] is None
    assert affected["desired_flip_per_all_affected"]["bounds"] == [0.5, 1.0]
    conditional = affected["desired_flip_per_intact_correct"]
    assert conditional["denominator"] == 2
    assert conditional["unknown_outcomes"] == 1
    assert conditional["rate"] is None
    assert affected["desired_flip_per_observed_pairs"]["rate"] == 1.0
    assert affected["donor_gain"]["mean"] == 4.0
    assert affected["donor_gain"]["unknown_count"] == 1


def test_fp32_rounding_created_tie_is_unknown() -> None:
    row = _row(intact_logits=[1.0, 1.0 + 1e-10])
    result = metrics.summarize_pairs([row])
    assert result["groups"][0]["per_case"][0]["unknown_reasons"] == ["intact:TIE_FP32"]
    assert result["groups"][0]["affected"]["donor_gain"]["values"] == [2.0]


def test_fp32_subtraction_overflow_is_not_a_finite_donor_effect() -> None:
    result = metrics.summarize_pairs([_row(intact_logits=[3e38, -3e38])])
    affected = result["groups"][0]["affected"]
    assert affected["unknown_pair_count"] == 0
    assert affected["observed_pair_count"] == 1
    assert affected["continuous_unknown_pair_count"] == 1
    assert affected["donor_gain"]["values"] == []
    assert affected["desired_flip_per_all_affected"]["rate"] == 1.0
    assert result["groups"][0]["per_case"][0]["unknown_reasons"] == []
    assert result["groups"][0]["per_case"][0]["continuous_unknown_reasons"] == [
        "pair:NONFINITE_FP32_ARITHMETIC"
    ]
    json.dumps(result, allow_nan=False)


def test_affected_and_unaffected_remain_separate_with_family_denominators() -> None:
    rows = [
        _row("q0"),
        _row("q0", pair_id="alternate-edit", donor_label=0),
        _row("q1"),
        _row("q2", original_world_family_id="family-b"),
    ]
    result = metrics.summarize_pairs(rows)
    group = result["groups"][0]
    assert result["family_count"] == group["family_count"] == 2
    assert result["uncertainty_unit"] == "ORIGINAL_WORLD_FAMILY_CLUSTER"
    assert group["affected"]["row_count"] == 3
    assert group["affected"]["family_count"] == 2
    assert group["unaffected"]["row_count"] == group["unaffected"]["family_count"] == 1
    assert [family["row_count"] for family in group["families"]] == [3, 1]


def test_variants_and_controls_are_not_pooled_or_counted_as_new_families() -> None:
    result = metrics.summarize_pairs(
        [
            _row(control_id="identity", swapped_logits=[2.0, 0.0]),
            _row(control="twin"),
            _row(control="twin", variant="renamed"),
        ]
    )
    assert result["group_count"] == 3
    assert result["family_count"] == 1
    assert result["cross_group_effects_pooled"] is False
    assert "affected" not in result
    assert all(group["row_count"] == 1 for group in result["groups"])


@pytest.mark.parametrize("rows", [[], (), None, {}, "[]", [True]])
def test_empty_or_malformed_input_is_an_error(rows: object) -> None:
    with pytest.raises(ValueError):
        metrics.summarize_pairs(rows)


def test_duplicate_observation_identity_is_rejected_even_if_values_differ() -> None:
    with pytest.raises(ValueError, match="duplicate observation identity"):
        metrics.summarize_pairs([_row(), _row(swapped_logits=[2.0, 0.0])])
    with pytest.raises(ValueError, match="duplicate observation identity"):
        metrics.summarize_pairs([_row(query_id=1), _row(query_id="1")])


@pytest.mark.parametrize(
    "field,value",
    [
        ("query_id", ""),
        ("pair_id", "  "),
        ("original_world_family_id", None),
        ("query_id", True),
        ("variant_id", ""),
        ("control_id", False),
        ("original_label", True),
        ("donor_label", "1"),
        ("donor_label", 2),
    ],
)
def test_structural_identity_and_label_errors_are_not_measurement_unknown(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValueError):
        metrics.summarize_pairs([_row(**{field: value})])


def test_conflicting_optional_identity_aliases_are_rejected() -> None:
    with pytest.raises(ValueError, match="conflicting control"):
        metrics.summarize_pairs([_row(control="a", control_id="b")])


def test_empty_subgroup_is_explicit_not_zero_accuracy() -> None:
    unaffected = _summary([_row()])["unaffected"]
    assert unaffected["measurement_status"] == "EMPTY"
    assert unaffected["prediction_agreement"]["rate"] is None
    assert unaffected["intact_original_accuracy"]["rate"] is None


@pytest.mark.parametrize(
    "payload,code",
    [
        (json.dumps([_row()]), 0),
        (json.dumps([_row(intact_logits=[math.nan, 1.0])]), 0),
        ("[]", 1),
        ('[{"query_id":"a","query_id":"b"}]', 1),
        ("{", 1),
    ],
)
def test_stdlib_cli_outputs_finite_json_and_clean_errors(payload: str, code: int) -> None:
    completed = subprocess.run(
        [sys.executable, "-I", "-S", str(SCRIPT)],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == code
    assert "Traceback" not in completed.stderr
    result = json.loads(completed.stdout, parse_constant=lambda value: pytest.fail(value))
    assert result["execution_ready"] is False
    assert result["status"] == ("DESCRIPTIVE_ONLY" if code == 0 else "INPUT_ERROR")
