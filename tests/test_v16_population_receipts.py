"""Offline descriptive uncertainty; no model, API or qualification promotion."""

import pytest

from scripts.verify_v16_population_eval import bootstrap


@pytest.mark.parametrize("value", [-1, 0, 1])
def test_constant_paired_bootstrap_is_exact(value):
    result = bootstrap([[value] * 10, [value] * 10], repetitions=100)
    assert result["estimate"] == value and result["interval_95"] == [value, value]
    assert result["units"] == 20 and result["strata"] == 2


def test_strata_and_seed_are_reproducible_not_query_replication():
    strata = [[-0.125, 0.25], [0, 0.125]]
    result = bootstrap(strata, repetitions=100)
    assert result == bootstrap(strata, repetitions=100)
    assert result["units"] == 4 and result["estimate"] == 0.0625
    assert "not_training_seed" in result["method"]


@pytest.mark.parametrize("strata", [[], [[]], [[1], []]])
def test_empty_bootstrap_is_not_zero_evidence(strata):
    with pytest.raises(ValueError):
        bootstrap(strata, repetitions=100)
