"""Pure fixed-alias binding and posthoc probability-accounting contracts."""

from __future__ import annotations

import copy
import itertools
import math

import pytest
import v15_completion_mass as mass
from v15_elicitation_inputs import make_cases


class AliasTokenizer:
    tokens = {" no": 10, " No": 11, " yes": 20, " Yes": 21}

    def encode(self, text, *, add_special_tokens):
        assert add_special_tokens is False
        if text == "prefix":
            return [30, 31]
        return [30, 31, self.tokens[text.removeprefix("prefix")]]


def alias(label, token, suffixes, first, eos):
    first_log, eos_log = math.log(first), math.log(eos)
    complete_log = first_log + eos_log
    return {
        "target_label": label,
        "token_id": token,
        "suffixes": suffixes,
        "first_log_probability": first_log,
        "eos_log_probability": eos_log,
        "complete_log_probability": complete_log,
        "first_probability": math.exp(first_log),
        "eos_probability": math.exp(eos_log),
        "complete_probability": math.exp(complete_log),
    }


def row_for(case, renderer="raw", information="inline"):
    target = case["target_label"]
    gap = 1.0 if target else -1.0
    return {
        **{name: case[name] for name in mass.METADATA if name not in ("renderer", "information")},
        "renderer": renderer,
        "information": information,
        "old_lowercase_native": {"scores": [0.0, gap], "gap": gap, "prediction": target},
        "aliases": [
            alias(
                label,
                token,
                [suffix],
                0.2 if label == target else 0.1,
                0.8 if label == target else 0.2,
            )
            for (label, suffix), token in zip(mass.ALIASES, (10, 11, 20, 21), strict=True)
        ],
    }


@pytest.fixture
def panel():
    return [
        row_for(case, renderer, information)
        for case, renderer, information in itertools.product(
            make_cases(), mass.RENDERERS, mass.INFORMATION
        )
    ]


def test_bind_aliases_preserves_fixed_classes_capitalization_and_order():
    result = mass.bind_aliases(AliasTokenizer(), "prefix", [30, 31])
    assert result == [
        {"target_label": label, "token_id": token, "suffixes": [suffix]}
        for (label, suffix), token in zip(mass.ALIASES, (10, 11, 20, 21), strict=True)
    ]


def test_token_equivalent_aliases_are_deduplicated_within_each_class():
    tokenizer = AliasTokenizer()
    tokenizer.tokens = {" no": 10, " No": 10, " yes": 20, " Yes": 20}
    assert mass.bind_aliases(tokenizer, "prefix", [30, 31]) == [
        {"target_label": 0, "token_id": 10, "suffixes": [" no", " No"]},
        {"target_label": 1, "token_id": 20, "suffixes": [" yes", " Yes"]},
    ]


def test_cross_class_token_collision_fails():
    tokenizer = AliasTokenizer()
    tokenizer.tokens = {" no": 10, " No": 11, " yes": 10, " Yes": 21}
    with pytest.raises(ValueError, match="Cross-class"):
        mass.bind_aliases(tokenizer, "prefix", [30, 31])


@pytest.mark.parametrize("mutation", ["prefix", "retokenization", "multitoken", "empty", "bool"])
def test_binding_does_not_silently_retokenize_or_truncate(mutation):
    class BrokenTokenizer(AliasTokenizer):
        def encode(self, text, **kwargs):
            result = super().encode(text, **kwargs)
            if mutation == "prefix" and text == "prefix":
                result[-1] += 1
            elif text != "prefix":
                if mutation == "retokenization":
                    result[0] += 1
                elif mutation == "multitoken":
                    result.append(99)
                elif mutation == "empty":
                    result = []
                elif mutation == "bool":
                    result[-1] = True
            return result

    with pytest.raises(ValueError):
        mass.bind_aliases(BrokenTokenizer(), "prefix", [30, 31])


def test_class_masses_add_probabilities_not_logits_and_keep_contrasts_distinct():
    row = row_for(make_cases()[0])
    row["target_label"] = 1
    row["old_lowercase_native"] = {"scores": [0.0, 1.0], "gap": 1.0, "prediction": 1}
    row["aliases"] = [
        alias(0, 10, [" no"], 0.1, 0.1),
        alias(0, 11, [" No"], 0.3, 0.1),
        alias(1, 20, [" yes"], 0.2, 1.0),
        alias(1, 21, [" Yes"], 0.1, 1.0),
    ]
    result = mass.analyze_row(row)
    assert result["lowercase"]["prediction"] == 1
    assert result["alias_start"]["prediction"] == 0
    assert result["completion"]["prediction"] == 1
    assert result["alias_start"]["probabilities"] == pytest.approx([0.4, 0.3])
    assert result["completion"]["probabilities"] == pytest.approx([0.04, 0.3])
    assert result["completion"]["total_probability"] == pytest.approx(0.34)
    assert result["completion"]["conditional_probabilities"] == pytest.approx([2 / 17, 15 / 17])
    assert result["completion"]["gap"] == pytest.approx(math.log(0.3 / 0.04))


def test_deduplicated_alias_does_not_double_count_one_token_path():
    row = row_for(make_cases()[0])
    row["aliases"] = [
        alias(0, 10, [" no", " No"], 0.2, 0.5),
        alias(1, 20, [" yes", " Yes"], 0.3, 0.5),
    ]
    result = mass.analyze_row(row)
    assert result["alias_token_paths"] == 2
    assert result["alias_start"]["total_probability"] == pytest.approx(0.5)
    assert result["completion"]["total_probability"] == pytest.approx(0.25)


def test_ties_remain_null_not_correct():
    row = row_for(make_cases()[0])
    row["old_lowercase_native"] = {"scores": [1.0, 1.0], "gap": 0.0, "prediction": None}
    row["aliases"] = [
        alias(label, token, [suffix], 0.2, 0.4)
        for (label, suffix), token in zip(mass.ALIASES, (10, 11, 20, 21), strict=True)
    ]
    result = mass.analyze_row(row)
    for stage in mass.STAGES:
        assert result[stage]["prediction"] is None
        assert result[stage]["correct"] is False


def test_log_domain_retains_conditional_result_after_probability_underflow():
    row = row_for(make_cases()[0])
    for entry in row["aliases"]:
        entry.update(
            first_log_probability=-1000.0,
            eos_log_probability=-100.0,
            complete_log_probability=-1100.0,
            first_probability=0.0,
            eos_probability=math.exp(-100.0),
            complete_probability=0.0,
        )
    result = mass.analyze_row(row)
    assert result["completion"]["total_probability"] == 0.0
    assert result["completion"]["conditional_probabilities"] == pytest.approx([0.5, 0.5])
    assert result["completion"]["prediction"] is None


@pytest.mark.parametrize(
    "name,value",
    [
        ("first_log_probability", float("nan")),
        ("eos_log_probability", float("inf")),
        ("first_log_probability", 1.0),
        ("eos_log_probability", True),
        ("complete_log_probability", -100.0),
        ("first_probability", 0.999),
        ("eos_probability", -1.0),
        ("complete_probability", 2.0),
    ],
)
def test_invalid_or_inconsistent_probability_receipts_fail(name, value):
    row = row_for(make_cases()[0])
    row["aliases"][0][name] = value
    with pytest.raises(ValueError):
        mass.analyze_row(row)


@pytest.mark.parametrize(
    "mutation",
    ["duplicate_token", "missing", "extra", "spelling", "reorder", "reorder_dedup", "wrong_class"],
)
def test_alias_inventory_cannot_change(mutation):
    row = row_for(make_cases()[0])
    if mutation == "duplicate_token":
        row["aliases"][1]["token_id"] = row["aliases"][0]["token_id"]
    elif mutation == "missing":
        row["aliases"].pop()
    elif mutation == "extra":
        row["aliases"].append(copy.deepcopy(row["aliases"][0]))
    elif mutation == "spelling":
        row["aliases"][0]["suffixes"] = [" NO"]
    elif mutation == "reorder":
        row["aliases"].reverse()
    elif mutation == "wrong_class":
        row["aliases"][0]["target_label"] = 1
    else:
        row["aliases"] = [
            alias(0, 10, [" No", " no"], 0.2, 0.5),
            alias(1, 20, [" yes", " Yes"], 0.3, 0.5),
        ]
    with pytest.raises(ValueError):
        mass.analyze_row(row)


def test_impossible_total_first_mass_is_rejected():
    row = row_for(make_cases()[0])
    row["aliases"] = [
        alias(label, token, [suffix], 0.5, 0.4)
        for (label, suffix), token in zip(mass.ALIASES, (10, 11, 20, 21), strict=True)
    ]
    with pytest.raises(ValueError, match="exceed one"):
        mass.analyze_row(row)


@pytest.mark.parametrize(
    "field,value",
    [("gap", 0.0), ("prediction", None), ("prediction", True), ("scores", [float("nan"), 1.0])],
)
def test_original_lowercase_receipt_is_validated_not_repaired(field, value):
    row = row_for(make_cases()[0])
    row["old_lowercase_native"][field] = value
    with pytest.raises(ValueError):
        mass.analyze_row(row)


def test_summary_has_144_cells_and_explicit_posthoc_scope_without_gate(panel):
    before = copy.deepcopy(panel)
    result = mass.summarize(panel)
    assert panel == before
    assert result["denominators"] == {
        "cases": 36,
        "prompt_rows": 144,
        "unique_answer_token_paths": 576,
    }
    assert result["panel_status"] == "all_cases_exposed_before_this_posthoc_diagnostic"
    assert "gate" not in result and "winner" not in result
    assert len(result["cells"]) == 20
    assert len(result["by_renderer_information_split_view"]) == 12
    assert len(result["by_renderer_information_split"]) == 8
    for stage in mass.STAGES:
        overall = result["overall"]["stages"][stage]
        assert overall["correct"] == 144 and overall["ties"] == 0
        assert overall["reciprocal_pairs"] == {"total": 72, "both_correct": 72}
        assert overall["label_correct"]["no"] == {"correct": 72, "total": 72, "recall": 1.0}


def test_rescue_regression_are_both_recorded_when_net_is_zero(panel):
    first, second = panel[0], panel[4]
    target = first["target_label"]
    gap = -1.0 if target else 1.0
    first["old_lowercase_native"] = {"scores": [0.0, gap], "gap": gap, "prediction": 1 - target}
    for entry in second["aliases"]:
        replacement = alias(
            entry["target_label"],
            entry["token_id"],
            entry["suffixes"],
            0.05 if entry["target_label"] == second["target_label"] else 0.3,
            0.5,
        )
        entry.update(replacement)
    transition = mass.summarize(panel)["overall"]["transitions"]["alias_start_vs_lowercase"]
    assert transition == {
        "rescued": 1,
        "regressed": 1,
        "net_correct_change": 0,
        "prediction_changed": 2,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "renderer",
        "information",
        "label_drift",
        "family_drift",
        "split_drift",
        "unbalanced",
    ],
)
def test_summary_rejects_incomplete_or_changed_panel(panel, mutation):
    if mutation == "missing":
        panel.pop()
    elif mutation == "duplicate":
        panel[-1] = copy.deepcopy(panel[0])
    elif mutation == "renderer":
        panel[0]["renderer"] = "new"
    elif mutation == "information":
        panel[0]["information"] = "context"
    elif mutation == "label_drift":
        panel[0]["target_label"] = 1 - panel[0]["target_label"]
    elif mutation == "family_drift":
        panel[0]["family_id"] = "other"
    elif mutation == "split_drift":
        panel[0]["split"] = "confirmation"
    else:
        selected = panel[16]["case_id"]
        for row in panel:
            if row["case_id"] == selected:
                row["target_label"] = 1 - row["target_label"]
    with pytest.raises(ValueError):
        mass.summarize(panel)
