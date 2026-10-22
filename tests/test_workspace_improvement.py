"""No model calls: planted effects, confounds and explicit missingness."""

import copy

import pytest

from latent_workspace import workspace_improvement as wi


def panel():
    units = [
        dict(
            id=f"u{i}",
            group_id="a" if i < 3 else "b",
            domain="reasoning" if i < 3 else "code",
            condition="relevant" if i < 3 else "irrelevant",
            route_sha256={r: str(j) * 64 for j, r in enumerate(wi.ROUTES)},
        )
        for i in range(4)
    ]
    rows = [
        dict(
            id=u["id"],
            model=m,
            route=r,
            route_sha256=u["route_sha256"][r],
            status="valid",
            correct=False,
            reason=None,
        )
        for u in units
        for m in wi.MODELS
        for r in wi.ROUTES
    ]
    return units, rows


def test_improvement_requires_original_route_controls_and_equal_group_weight():
    units, rows = panel()
    for r in rows:
        if r["model"] == "candidate" and r["route"] == "workspace" and r["id"] != "u3":
            r["correct"] = True
    result = wi.summarize(units, rows)
    interaction = result["overall"]["workspace_interaction"]
    assert interaction["paired_units"] == 4 and interaction["paired_groups"] == 2
    assert interaction["unit_mean"] == 0.75 and interaction["group_macro_mean"] == 0.5
    assert result["overall"]["candidate_minus_original"]["workspace"]["repairs"] == 3
    assert result["status"] == "COMPLETE_NOT_NON_REGRESSION"
    assert result["strata"]["domain"]["code"]["planned_units"] == 1


def test_generic_ft_gain_is_not_a_workspace_interaction():
    units, rows = panel()
    for r in rows:
        r["correct"] = r["model"] == "candidate"
    result = wi.summarize(units, rows)
    assert result["overall"]["workspace_interaction"]["group_macro_mean"] == 0
    assert result["overall"]["candidate_minus_original"]["no_memory"]["repairs"] == 4


def test_invalid_and_missing_never_shrink_the_planned_denominator():
    units, rows = panel()
    rows.pop()
    rows[0].update(status="invalid", correct=None, reason="transport interruption")
    result = wi.summarize(units, rows)
    cells = result["overall"]["cells"]
    assert cells["original/no_memory"] == dict(
        planned=4, observed=4, valid=3, invalid=1, missing=0, correct=0, accuracy_valid=0.0
    )
    assert cells["candidate/workspace"]["missing"] == 1
    assert len(result["invalidities"]) == len(result["missing"]) == 1
    assert result["overall"]["workspace_interaction"]["unpaired_units"] == 1
    assert result["status"] == "INCOMPLETE_NOT_NON_REGRESSION"


def test_no_observations_remains_missing_not_zero_accuracy():
    units, _ = panel()
    result = wi.summarize(units, [])
    assert len(result["missing"]) == 24
    assert all(c["accuracy_valid"] is None for c in result["overall"]["cells"].values())
    assert result["overall"]["workspace_interaction"]["group_macro_mean"] is None


@pytest.mark.parametrize(
    "damage",
    [
        "duplicate_unit",
        "duplicate_row",
        "extra_row",
        "hash",
        "integer_bool",
        "invalid_false",
        "missing_reason",
        "extra_field",
    ],
)
def test_changed_or_ambiguous_inputs_fail_closed(damage):
    units, rows = panel()
    if damage == "duplicate_unit":
        units.append(copy.deepcopy(units[0]))
    elif damage == "duplicate_row":
        rows.append(copy.deepcopy(rows[0]))
    elif damage == "extra_row":
        rows[0]["id"] = "unplanned"
    elif damage == "hash":
        rows[0]["route_sha256"] = "9" * 64
    elif damage == "integer_bool":
        rows[0]["correct"] = 1
    elif damage == "invalid_false":
        rows[0].update(status="invalid", reason="bad evidence")
    elif damage == "missing_reason":
        rows[0].update(status="invalid", correct=None)
    else:
        rows[0]["adjusted_score"] = True
    with pytest.raises(ValueError):
        wi.summarize(units, rows)


def test_order_independent_but_hash_bound():
    units, rows = panel()
    assert wi.summarize(units, rows) == wi.summarize(list(reversed(units)), list(reversed(rows)))
