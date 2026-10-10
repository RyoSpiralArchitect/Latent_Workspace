from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "scripts"))
import summarize_v15_reader_modulation as audit  # noqa: E402


def test_complete_replay():
    result = audit.build(HERE)
    assert result == audit.read(HERE / "SUMMARY.json")
    assert result["evaluation_rows"] == 512 and result["query_routes"] == 320
    for name, row in audit.read(HERE / "ARTIFACT_INDEX.json").items():
        assert audit.digest(HERE / "raw" / name) == row["sha256"]
        assert (HERE / "raw" / name).stat().st_size == row["bytes"]


@pytest.mark.parametrize(
    "mutation",
    ["duplicate", "missing", "truth", "cap", "parity", "eos", "route", "parameter", "permutation"],
)
def test_corrupt_cell_rejected(mutation):
    evaluation = copy.deepcopy(
        audit.read(HERE / "raw/retained_answer_step8_query_modulated_EVAL.json")
    )
    gradient = copy.deepcopy(
        audit.read(HERE / "raw/retained_answer_step8_query_modulated_GRAD.json")
    )
    if mutation == "duplicate":
        evaluation["rows"][1] = evaluation["rows"][0]
    elif mutation == "missing":
        evaluation["rows"].pop()
    elif mutation == "truth":
        evaluation["rows"][0]["correct"] = not evaluation["rows"][0]["correct"]
    elif mutation == "cap":
        evaluation["rows"][0]["delta_l2"] = 2
    elif mutation == "parity":
        evaluation["rows"][0]["strength_zero_delta_exact"] = True
    elif mutation == "eos":
        gradient["pairs"][0]["routes"][1]["l2"] = 1
    elif mutation == "route":
        gradient["pairs"][0]["routes"].pop()
    elif mutation == "parameter":
        gradient["pairs"][0]["parameters"].pop()
    else:
        evaluation["permutations"][0]["delta_max_abs_error"] = 0.01
    with pytest.raises(ValueError):
        audit.cell(evaluation, gradient, "retained_answer_step8", "query_modulated")
