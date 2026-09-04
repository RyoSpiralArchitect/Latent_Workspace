from __future__ import annotations

import copy
import importlib.util
import json
import math
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/v14_screen_metrics.py"
SPEC = importlib.util.spec_from_file_location("v14_screen_metrics", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
metrics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metrics)


def _cases(families: int = 2) -> list[dict]:
    rows = []
    for family in range(families):
        for template in ("ranked_above", "outrank"):
            records = [
                ("primary", orientation, affected)
                for orientation in ("original", "reversed")
                for affected in (False, True)
            ]
            records.append(("easy", "original_to_reversed", True))
            for role, orientation, affected in records:
                record = f"f{family}:{template}:{role}:{orientation}:{affected}"
                for side in (0, 1):
                    for query in (0, 1):
                        target = query ^ int(orientation == "reversed") ^ (side * int(affected))
                        rows.append(
                            {
                                "record_id": record,
                                "family_id": f"f{family}",
                                "role": role,
                                "hop": 1 if role == "easy" else 2 + family % 3,
                                "template": template,
                                "orientation": orientation,
                                "edit_type": "internal_transposition"
                                if role == "primary"
                                else "reversal",
                                "side": side,
                                "query_index": query,
                                "target_index": target,
                                "affected": affected,
                                "f0_logits": [2.0, 0.0],
                                "f1_logits": [0.0, 2.0] if target else [2.0, 0.0],
                            }
                        )
    return rows


def _summary(rows: list[dict], families: int = 2) -> dict:
    return metrics.summarize(rows, expected_records=10 * families, expected_families=families)


def _donor(result: dict, role: str = "primary", route: str = "f1", affected: bool = True) -> dict:
    group = next(
        group
        for group in result["donor_pairs"]["groups"]
        if group["variant_id"] == role and group["control_id"] == route
    )
    return group["affected" if affected else "unaffected"]


def test_default_full_screen_has_12_not_480_independent_units_and_fixed_gates() -> None:
    rows = _cases(12)
    original = copy.deepcopy(rows)
    result = metrics.summarize(rows)
    assert result["coverage"]["expected_cases"] == 480
    assert result["coverage"]["observed_cases"] == 480
    assert result["coverage"]["ok"] is True
    assert result["screen_complete"] is True
    assert result["bootstrap"]["draws"] == 4096
    assert result["bootstrap"]["seed"] == 1404
    assert result["bootstrap"][
        "all_sides_queries_templates_orientations_alternate_edits_resampled_together"
    ]
    for role, cases in (("easy", 96), ("primary", 384)):
        group = result["roles"][role]
        assert group["observed_case_count"] == cases
        assert group["f1"]["accuracy"]["value"] == 1.0
        assert group["f0"]["accuracy"]["value"] == 0.5
        assert group["family_cluster"]["f1_accuracy"]["independent_families"] == 12
        assert group["family_cluster"]["context_accuracy_delta"]["ci95"] == [0.5, 0.5]
        assert group["gate"]["qualified"] is True
        assert group["gate"]["is_mistral_return_prerequisite"] is False
        assert set(group["strata"]["template"]) == {"outrank", "ranked_above"}
    assert result["roles"]["easy"]["gate"]["thresholds"]["accuracy"] == 0.75
    assert result["roles"]["primary"]["gate"]["thresholds"]["accuracy"] == 0.60
    assert set(result["roles"]["primary"]["strata"]["hop"]) == {"2", "3", "4"}
    assert result["donor_pairs"]["expected_pairs_per_route"] == 240
    assert result["donor_pairs"]["identified_pairs_per_route"] == 240
    assert rows == original
    json.dumps(result, allow_nan=False)


def test_family_bootstrap_keeps_all_correlated_views_together() -> None:
    rows = _cases()
    for row in rows:
        if row["family_id"] == "f1":
            row["f1_logits"] = list(reversed(row["f1_logits"]))
    result = _summary(rows)
    group = result["roles"]["primary"]
    assert group["f1"]["accuracy"]["value"] == 0.5
    assert group["family_cluster"]["f1_accuracy"]["ci95"] == [0.0, 1.0]
    assert group["family_cluster"]["context_accuracy_delta"]["ci95"] == [-0.5, 0.5]
    assert group["gate"]["qualified"] is False


def test_row_order_does_not_change_seeded_bootstrap_or_pairing() -> None:
    rows = _cases()
    assert _summary(rows) == _summary(list(reversed(rows)))


def test_missing_single_side_keeps_expected_denominators_and_donor_unknown() -> None:
    rows = _cases()
    removed = rows.pop(0)
    result = _summary(rows)
    assert result["coverage"]["missing_cases"] == 1
    assert result["coverage"]["missing_cases_in_unidentified_records"] == 0
    assert result["overall_accuracy_expected_denominator"]["f1"]["bounds"] == [79 / 80, 1.0]
    group = result["roles"][removed["role"]]
    assert group["f1"]["accuracy"]["denominator"] == 64
    assert group["f1"]["accuracy"]["unknown_count"] == 1
    assert group["family_cluster"]["f1_accuracy"]["ci95"] == [0.0, 1.0]
    assert group["family_cluster"]["context_accuracy_delta"]["ci95"] == [-1.0, 1.0]
    assert result["donor_pairs"]["missing_side_labels_derived_from_other_side_and_affected"] == 1
    assert _donor(result, affected=False)["unknown_pair_count"] == 1
    assert all(not group["gate"]["qualified"] for group in result["roles"].values())


def test_wholly_missing_record_is_not_invented_or_excluded_from_global_denominator() -> None:
    rows = _cases()
    removed_id = rows[0]["record_id"]
    result = _summary([row for row in rows if row["record_id"] != removed_id])
    assert result["coverage"]["observed_records"] == 19
    assert result["coverage"]["missing_cases_in_unidentified_records"] == 4
    assert result["overall_accuracy_expected_denominator"]["f1"]["denominator"] == 80
    assert result["overall_accuracy_expected_denominator"]["f1"]["unknown_count"] == 4
    assert result["donor_pairs"]["unidentified_pairs_per_route"] == 2
    assert result["roles"]["primary"]["family_cluster"]["f1_accuracy"]["status"].startswith(
        "UNKNOWN"
    )


def test_absent_query_has_explicit_unidentified_pair_denominator() -> None:
    rows = _cases()
    record = rows[0]["record_id"]
    result = _summary([r for r in rows if r["record_id"] != record or r["query_index"] != 0])
    assert result["donor_pairs"]["identified_pairs_per_route"] == 39
    assert result["donor_pairs"]["unidentified_pairs_per_route"] == 1
    assert result["coverage"]["missing_cases"] == 2


def test_empty_measurements_are_incomplete_not_zero_accuracy_or_pass() -> None:
    result = metrics.summarize([])
    assert result["screen_complete"] is False
    assert result["coverage"]["missing_cases"] == 480
    assert result["overall_accuracy_expected_denominator"]["f1"]["value"] is None
    assert result["overall_accuracy_expected_denominator"]["f1"]["bounds"] == [0.0, 1.0]
    assert result["donor_pairs"]["groups"] == []
    assert result["roles"]["easy"]["gate"]["status"] == "UNKNOWN"


def test_tie_is_categorical_unknown_but_margin_and_screen_completion_remain_observed() -> None:
    rows = _cases()
    row = next(
        r
        for r in rows
        if r["role"] == "primary" and r["affected"] and r["side"] == 0 and r["query_index"] == 0
    )
    row["f1_logits"] = [0.0, 0.0]
    result = _summary(rows)
    assert result["coverage"]["ok"] is True
    assert result["screen_complete"] is True
    group = result["roles"]["primary"]
    assert group["f1"]["accuracy"]["value"] is None
    assert group["f1"]["accuracy"]["bounds"] == [63 / 64, 1.0]
    assert group["f1"]["target_margin"]["unknown_count"] == 0
    assert group["gate"]["status"] == "UNKNOWN"
    paired = _donor(result)
    assert paired["unknown_pair_count"] == 1
    assert paired["continuous_unknown_pair_count"] == 0
    assert 2.0 in paired["donor_gain"]["values"]


@pytest.mark.parametrize(
    "value",
    [None, [float("nan"), 1], [1, float("inf")], [1e100, 0], [], [1, 2, 3], [True, 1], ["0", 1]],
)
def test_invalid_missing_nonfinite_measurements_remain_unknown_and_json_finite(
    value: object,
) -> None:
    rows = _cases()
    rows[0]["f1_logits"] = value
    result = _summary(rows)
    group = result["roles"]["primary"]
    assert group["f1"]["accuracy"]["unknown_count"] == 1
    assert group["f1"]["target_margin"]["unknown_count"] == 1
    assert result["screen_complete"] is False
    assert group["gate"]["qualified"] is False
    json.dumps(result, allow_nan=False)


def test_finite_fp32_arithmetic_overflow_does_not_erase_categorical_prediction() -> None:
    rows = _cases()
    rows[0]["f1_logits"] = [3e38, -3e38]
    result = _summary(rows)
    assert result["roles"]["primary"]["f1"]["accuracy"]["unknown_count"] == 0
    assert result["roles"]["primary"]["f1"]["target_margin"]["unknown_count"] == 1
    assert result["screen_complete"] is False
    json.dumps(result, allow_nan=False)


def test_operands_are_fp32_before_margin_subtraction() -> None:
    rows = _cases()
    rows[0]["f1_logits"] = [16777217.0, 16777216.0]
    result = _summary(rows)
    # Python doubles would predict no with margin1; FP32 operands are tied.
    assert result["roles"]["primary"]["f1"]["unknown_reason_counts"] == {"TIE_FP32": 1}
    assert 0.0 in result["roles"]["primary"]["f1"]["target_margin"]["values"]


def test_donor_directed_pairs_are_distinct_from_same_target_context_benefit() -> None:
    result = _summary(_cases())
    directed = _donor(result)
    assert directed["desired_flip_per_all_affected"]["rate"] == 1.0
    assert directed["donor_gain"]["values"] == [4.0] * directed["row_count"]
    # F0 is blind to which context side it receives: half its starts already predict donor.
    blind = _donor(result, route="f0")
    assert blind["transition_table"]["donor_to_donor"] > 0
    assert blind["desired_flip_per_all_affected"]["rate"] == 0.0
    assert blind["donor_gain"]["mean"] == 0.0
    assert (
        result["roles"]["primary"]["same_target_f0_to_f1_transitions"]["counts"]["wrong_to_correct"]
        == 32
    )
    unaffected = _donor(result, route="f0", affected=False)
    assert unaffected["prediction_agreement"]["rate"] == 1.0
    assert unaffected["intact_original_accuracy"]["rate"] == 0.5
    assert unaffected["transition_table"]["wrong_to_wrong"] > 0


def test_unknown_accuracy_bootstrap_is_bounded_not_zero_filled() -> None:
    rows = _cases()
    for row in rows:
        if row["family_id"] == "f1":
            row["f1_logits"] = None
    result = _summary(rows)
    interval = result["roles"]["primary"]["family_cluster"]["f1_accuracy"]
    assert interval["value"] is None
    assert interval["bounds"] == [0.5, 1.0]
    assert interval["ci95"] == [0.0, 1.0]
    assert interval["status"] == "UNKNOWN_BOUNDED"


def test_role_cannot_hide_missing_independent_family_behind_total_count() -> None:
    rows = _cases()
    for row in rows:
        if row["role"] == "easy" and row["family_id"] == "f1":
            row["family_id"] = "f0"
    result = _summary(rows)
    assert result["coverage"]["observed_cases"] == 80
    assert result["coverage"]["observed_independent_families"] == 2
    assert result["coverage"]["ok"] is False
    assert result["coverage"]["observed_independent_families_by_role"]["easy"] == 1


def test_duplicate_record_side_query_rejected() -> None:
    rows = _cases()
    with pytest.raises(ValueError, match="duplicate answer"):
        _summary([*rows, dict(rows[0])])


@pytest.mark.parametrize(
    "field,value",
    [
        ("family_id", "other"),
        ("template", "other"),
        ("orientation", "other"),
        ("edit_type", "other"),
    ],
)
def test_inconsistent_record_metadata_rejected(field: str, value: object) -> None:
    rows = _cases()
    rows[0][field] = value
    with pytest.raises(ValueError, match="inconsistent record metadata"):
        _summary(rows)


@pytest.mark.parametrize(
    "field,value",
    [
        ("record_id", ""),
        ("family_id", False),
        ("side", True),
        ("query_index", 2),
        ("target_index", "1"),
        ("affected", "false"),
        ("role", "heldout"),
        ("hop", True),
    ],
)
def test_invalid_schema_rejected(field: str, value: object) -> None:
    rows = _cases()
    rows[0][field] = value
    with pytest.raises(ValueError):
        _summary(rows)


def test_twin_target_mismatch_rejected() -> None:
    rows = _cases()
    rows[2]["target_index"] = 1 - rows[2]["target_index"]
    with pytest.raises(ValueError, match="twin labels"):
        _summary(rows)


def test_reverse_query_target_mismatch_rejected() -> None:
    rows = _cases()
    rows[1]["target_index"] = rows[0]["target_index"]
    rows[3]["target_index"] = rows[2]["target_index"]
    with pytest.raises(ValueError, match="reverse-query labels"):
        _summary(rows)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"expected_records": True},
        {"expected_records": 0},
        {"expected_families": -1},
        {"expected_families": "12"},
    ],
)
def test_bad_expected_denominators_rejected(kwargs: dict) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        metrics.summarize([], **kwargs)


def test_excess_observed_records_or_families_rejected() -> None:
    with pytest.raises(ValueError, match="exceed"):
        metrics.summarize(_cases(), expected_records=10, expected_families=1)


def test_no_context_benefit_does_not_qualify_even_if_f1_is_perfect() -> None:
    rows = _cases()
    for row in rows:
        row["f0_logits"] = row["f1_logits"][:]
    result = _summary(rows)
    for role in result["roles"].values():
        assert role["f1"]["accuracy"]["value"] == 1.0
        assert role["gate"]["qualified"] is False
        assert role["family_cluster"]["context_accuracy_delta"]["ci95"] == [0.0, 0.0]


def test_negative_task_accuracy_does_not_block_mechanically_ready_mistral_return() -> None:
    rows = _cases()
    for row in rows:
        row["f1_logits"] = list(reversed(row["f1_logits"]))
    result = _summary(rows)
    assert result["roles"]["primary"]["f1"]["accuracy"]["value"] == 0.0
    assert result["roles"]["primary"]["gate"]["qualified"] is False
    decision = metrics.return_decision(
        True, result["coverage"]["ok"], True, result["screen_complete"]
    )
    assert decision["return_to_mistral"] is True
    assert decision["task_accuracy_is_prerequisite"] is False
    assert decision["execution_authorization_granted_here"] is False


@pytest.mark.parametrize("index", range(4))
def test_each_mechanical_check_is_required(index: int) -> None:
    checks = [True] * 4
    checks[index] = False
    result = metrics.return_decision(*checks)
    assert result["return_to_mistral"] is False
    assert len(result["blocking_checks"]) == 1


@pytest.mark.parametrize("bad", ["true", "false", 1, 0, None, [], math.nan])
def test_return_checks_are_strict_booleans(bad: object) -> None:
    with pytest.raises(ValueError, match="explicit booleans"):
        metrics.return_decision(bad, True, True, True)
