from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
gate = importlib.import_module("run_v14_mistral_atomic_instrument_gate")


def _easy_record() -> dict:
    return {
        "contexts": [
            (
                "World facts. The ranking is transitive.\n"
                "- A is ranked above B.\n- C is ranked above D."
            ),
            (
                "World facts. The ranking is transitive.\n"
                "- B is ranked above A.\n- D is ranked above C."
            ),
        ],
        "queries": ["Is A ranked above B? Answer:", "Is B ranked above A? Answer:"],
        "answers": [[1, 0], [0, 1]],
        "metadata": {"role": "easy", "query_entities": ["A", "B"]},
    }


def test_atomic_view_keeps_only_the_matched_edge_without_mutating_source() -> None:
    source = _easy_record()
    result = gate.atomic_easy_view([source])[0]
    assert source["contexts"][0].count("\n-") == 2
    assert result["contexts"] == [
        "World facts. The ranking is transitive.\n- A is ranked above B.",
        "World facts. The ranking is transitive.\n- B is ranked above A.",
    ]
    assert result["metadata"]["instrument_view"] == "isolated_direct_evidence_edge"


def test_atomic_view_rejects_missing_or_inconsistent_evidence() -> None:
    missing = _easy_record()
    missing["contexts"][0] = "World facts. The ranking is transitive.\n- C is ranked above D."
    with pytest.raises(ValueError, match="exactly one"):
        gate.atomic_easy_view([missing])

    inconsistent = _easy_record()
    inconsistent["answers"][0] = [0, 1]
    with pytest.raises(ValueError, match="disagrees"):
        gate.atomic_easy_view([inconsistent])


def test_real_calibration_atomic_view_preserves_count_and_primary_records() -> None:
    repo = Path(__file__).resolve().parents[1]
    records = [
        json.loads(line)
        for line in (repo / "data/v14/instrument_calibration.jsonl").read_text().splitlines()
    ]
    transformed = gate.atomic_easy_view(records)
    assert len(transformed) == len(records)
    assert sum(row["metadata"]["role"] == "easy" for row in transformed) == 24
    for before, after in zip(records, transformed, strict=True):
        if before["metadata"]["role"] == "primary":
            assert before == after
