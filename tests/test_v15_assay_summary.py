from __future__ import annotations

import copy
import itertools

import pytest
from v15_assay_summary import (
    MEMORY_KEYS,
    MODES,
    canonical_facts,
    parse_functional_answer,
    summarize_crossover,
)


def scores(gap):
    return {
        "scores": [0.0, float(gap)],
        "gap": float(gap),
        "prediction": None if gap == 0 else int(gap > 0),
    }


@pytest.fixture
def rows():
    output = []
    for mode, world, query, memory_key in itertools.product(MODES, range(2), range(8), MEMORY_KEYS):
        original = int(query % 2 == 0)
        affected = query < 2
        labels = [original, 1 - original if affected else original]
        gap = 0.25
        if memory_key.endswith(("_0", "_1")) and not memory_key.startswith("norm_"):
            side = int(memory_key[-1])
            gap = 2 * labels[side] - 1
            if memory_key.startswith("canonical_reverse"):
                gap *= -1
            elif memory_key.startswith("canonical"):
                gap += 0.5
        zero = memory_key == "zero"
        if zero:
            gap = 0
        output.append(
            {
                "mode": mode,
                "world": world,
                "query": query,
                "memory_key": memory_key,
                "labels": labels,
                "affected": affected,
                "native": scores(gap),
                "fp32": scores(gap),
                "base_native": scores(0),
                "base_fp32": scores(0),
                "transport": {
                    "kl_base_to_candidate": 0 if zero else 0.01,
                    "total_variation": 0 if zero else 0.02,
                    "max_abs_logit_change": 0 if zero else 1.5,
                    "base_top1": 4,
                    "candidate_top1": 4 if zero else 5,
                    "base_top1_probability": 0.1,
                    "candidate_top1_probability": 0.1 if zero else 0.11,
                },
                "delta_l2": 0 if zero else 0.99,
                "native_applied_delta_l2": 0 if zero else 0.25,
            }
        )
    return output


def test_canonical_facts_preserves_literal_header_facts_and_newline():
    text = "World facts. The ranking is transitive.\n- Z is above A.\n- A is above B.\n"
    expected = "World facts. The ranking is transitive.\n- A is above B.\n- Z is above A.\n"
    assert canonical_facts(text) == expected
    assert canonical_facts(expected, reverse=True) == text
    assert canonical_facts(text.rstrip("\n")) == expected.rstrip("\n")
    assert canonical_facts(expected) == expected
    assert canonical_facts("Header\n- One fact.") == "Header\n- One fact."


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Header",
        "\n- Fact",
        " Header\n- Fact",
        "Header \n- Fact",
        "- Header\n- Fact",
        "Header\nFact",
        "Header\n- ",
        "Header\n-  Fact",
        "Header\n- Fact ",
        "Header\n- Fact\n- Fact",
        "Header\n- Fact\n\n",
        "Header\r\n- Fact",
        None,
    ],
)
def test_canonical_facts_rejects_malformed(text):
    with pytest.raises(ValueError):
        canonical_facts(text)


def test_canonical_reverse_must_be_boolean():
    with pytest.raises(ValueError):
        canonical_facts("Header\n- Fact", reverse=1)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("yes", 1),
        (" NO \n", 0),
        ("YeS", 1),
        ("yes.", None),
        ("no, because", None),
        ("yes no", None),
        ("Answer: yes", None),
        ("", None),
        ("YES\nYES", None),
    ],
)
def test_functional_parser_only_accepts_entire_exact_answer(text, expected):
    assert parse_functional_answer(text) == expected


def test_functional_parser_rejects_nontext():
    with pytest.raises(ValueError):
        parse_functional_answer(None)


def test_complete_matched_content_and_serialization_summary(rows):
    original = copy.deepcopy(rows)
    result = summarize_crossover(rows)
    assert rows == original
    assert summarize_crossover(list(reversed(rows))) == result
    assert result["row_count"] == 384
    assert result["denominators"] == {
        "worlds": 2,
        "unique_world_query_pairs": 16,
        "affected_pairs": 4,
        "unaffected_pairs": 12,
        "side_query_rows_per_order": 32,
    }
    for mode in MODES:
        view = result["modes"][mode]
        assert view["base"]["native"] == {
            "correct": 0,
            "total": 32,
            "ties": 32,
            "incorrect_nonties": 0,
        }
        for arithmetic in ("native", "fp32"):
            intact = view["orders"]["original"][arithmetic]
            assert (intact["correct"], intact["total"], intact["ties"]) == (32, 32, 0)
            affected = intact["affected_content"]
            assert affected["count"] == affected["correct_flips"] == 4
            assert affected["positive_donor_changes"] == 4
            assert affected["donor_signed_change"]["min"] == 2
            assert intact["unaffected_content"]["count"] == 12
            assert intact["unaffected_content"]["absolute_gap_change"]["max"] == 0
            canonical = view["orders"]["canonical"][arithmetic]
            assert canonical["correct"] == 32
            assert canonical["affected_content"]["donor_signed_change"]["min"] == 2
            reverse = view["orders"]["canonical_reverse"][arithmetic]
            assert reverse["correct"] == reverse["affected_content"]["correct_flips"] == 0
            assert reverse["affected_content"]["donor_signed_change"]["max"] == -2
            serialization = view["serialization"]["canonical"][arithmetic]
            assert serialization["count"] == 32
            assert serialization["absolute_gap_change"]["min"] == 0.5
            assert serialization["prediction_changes_including_ties"] == 0
            reverse_serial = view["serialization"]["canonical_reverse"][arithmetic]
            assert reverse_serial["regressions_from_original"] == 32
            assert reverse_serial["improvements_from_original"] == 0
        zero = view["controls"]["zero"]
        assert zero["count"] == 16
        assert zero["delta_l2"]["max"] == zero["native_applied_delta_l2"]["max"] == 0
        assert zero["native"]["absolute_gap_drift_from_base"]["max"] == 0
        assert zero["transport"]["top1_changes"] == 0
        assert view["controls"]["fixed_carrier"]["transport"]["top1_changes"] == 16


def test_ties_not_counted_correct_and_native_fp32_not_merged(rows):
    row = next(
        row
        for row in rows
        if (row["mode"], row["world"], row["query"], row["memory_key"])
        == ("final", 0, 2, "original_0")
    )
    row["native"] = scores(0)
    view = summarize_crossover(rows)["modes"]["final"]["orders"]["original"]
    assert view["native"]["correct"] == 31
    assert view["native"]["ties"] == 1
    assert view["fp32"]["correct"] == 32
    assert view["fp32"]["ties"] == 0


@pytest.mark.parametrize(
    "mutation",
    [
        lambda rows: rows.pop(),
        lambda rows: rows.append(copy.deepcopy(rows[0])),
        lambda rows: rows.__setitem__(1, copy.deepcopy(rows[0])),
        lambda rows: rows[0].update(mode="unknown"),
        lambda rows: rows[0].update(world=True),
        lambda rows: rows[0].update(query=8),
        lambda rows: rows[0].update(memory_key="empty"),
        lambda rows: rows[0].update(labels=[True, 0]),
        lambda rows: rows[0].update(labels=[1, 1]),
        lambda rows: rows[0].update(labels=[0, 1]),
        lambda rows: rows[0].update(affected=1),
        lambda rows: rows[0]["native"].update(gap=2),
        lambda rows: rows[0]["native"].update(prediction=0),
        lambda rows: rows[0]["native"].update(prediction=True),
        lambda rows: rows[0]["native"].update(scores=[0, float("nan")]),
        lambda rows: rows[0].update(base_native=scores(1)),
        lambda rows: rows[0]["transport"].update(total_variation=1.1),
        lambda rows: rows[0]["transport"].update(kl_base_to_candidate=-0.1),
        lambda rows: rows[0]["transport"].update(candidate_top1=True),
        lambda rows: rows[0]["transport"].update(base_top1=8),
        lambda rows: rows[0]["transport"].update(base_top1_probability=0.2),
        lambda rows: rows[0]["transport"].pop("max_abs_logit_change"),
        lambda rows: rows[0].update(delta_l2=-1),
        lambda rows: rows[0].update(native_applied_delta_l2=float("inf")),
    ],
)
def test_invalid_grid_scores_metadata_or_transport_fail_closed(rows, mutation):
    mutation(rows)
    with pytest.raises(ValueError):
        summarize_crossover(rows)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row.update(native=scores(1)),
        lambda row: row.update(fp32=scores(1)),
        lambda row: row.update(delta_l2=0.01),
        lambda row: row.update(native_applied_delta_l2=0.01),
        lambda row: row["transport"].update(total_variation=0.01),
        lambda row: row["transport"].update(candidate_top1=5),
        lambda row: row["transport"].update(candidate_top1_probability=0.2),
    ],
)
def test_zero_control_must_be_exact_noop(rows, mutation):
    mutation(next(row for row in rows if row["memory_key"] == "zero"))
    with pytest.raises(ValueError):
        summarize_crossover(rows)


def test_wrong_affected_denominator_rejected_even_with_consistent_metadata(rows):
    for row in rows:
        if row["world"] == 0 and row["query"] == 2:
            row["labels"] = [1, 0]
            row["affected"] = True
    with pytest.raises(ValueError, match="four affected"):
        summarize_crossover(rows)


def test_small_negative_kl_roundoff_preserved_not_clipped(rows):
    row = next(row for row in rows if row["memory_key"] == "fixed_carrier")
    row["transport"]["kl_base_to_candidate"] = -1e-14
    value = summarize_crossover(rows)["modes"]["final"]["controls"]["fixed_carrier"]
    assert value["transport"]["kl_base_to_candidate"]["min"] == -1e-14
