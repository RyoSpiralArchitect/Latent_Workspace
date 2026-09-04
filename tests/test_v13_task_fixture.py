from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/v13_task_fixture.py"
SPEC = importlib.util.spec_from_file_location("v13_task_fixture", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)


def test_deterministic_serializable_fixture_is_not_a_qualified_corpus() -> None:
    records = fixture.generate_fixture(seed=13, families=4)
    assert records == fixture.generate_fixture(seed=13, families=4)
    assert records != fixture.generate_fixture(seed=14, families=4)
    assert json.loads(json.dumps(records)) == records
    before = copy.deepcopy(records)
    report = fixture.validate_fixture(records)
    assert report["passed"] and not report["errors"]
    assert (report["records"], report["families"], report["cases"]) == (8, 4, 32)
    assert report["qualified_corpus"] is False
    assert report["model_capability_assessed"] is False
    assert report["training_or_split_freeze"] is False
    assert records == before


@pytest.mark.parametrize("seed", [0, 1, 13, 42, 999, -7])
def test_same_original_query_has_both_statuses_and_exactly_matched_hops(seed: int) -> None:
    records = fixture.generate_fixture(seed, families=12)
    assert fixture.validate_fixture(records)["passed"]
    for family_id in {record["family_id"] for record in records}:
        family = [record for record in records if record["family_id"] == family_id]
        assert {record["variant"] for record in family} == {"affected", "unaffected"}
        assert family[0]["contexts"][0] == family[1]["contexts"][0]
        assert family[0]["queries"] == family[1]["queries"]
        assert family[0]["hop_distances"] == family[1]["hop_distances"]
        assert family[0]["metadata"]["edit_distance"] == family[1]["metadata"]["edit_distance"]
        for record in family:
            assert record["hop_distances"][0] == record["hop_distances"][1]
            assert all(hop >= 2 for side in record["hop_distances"] for hop in side)
            assert record["answers"][0] in ([0, 1], [1, 0])
            for side, context in enumerate(record["contexts"]):
                assert [fixture.symbolic_oracle(context, q) for q in record["queries"]] == (
                    record["answers"][side]
                )


def test_shortcuts_preserve_abstention_and_in_sample_lookup_warning() -> None:
    report = fixture.validate_fixture(fixture.generate_fixture(13, 1))
    probes = report["shortcut_probes"]
    direct = probes["direct_edge_endpoint_abstaining"]
    assert direct["answered"] == 0 and direct["abstentions"] == report["cases"]
    assert direct["accuracy_answered"] is None
    assert probes["query_only_constant_no"]["accuracy_answered"] == 0.5
    assert probes["query_only_constant_yes"]["accuracy_answered"] == 0.5
    assert probes["symbolic_path_oracle"]["accuracy_answered"] == 1.0
    assert probes["memory_blind_internal_inversion_fallback_no"]["accuracy_answered"] == 0.5
    assert probes["query_text_in_sample_majority"]["accuracy_answered"] == 0.75
    assert "SAME fixture" in probes["interpretation"]
    assert "does not rule out other shortcuts" in probes["interpretation"]


@pytest.mark.parametrize("seed,families", [(True, 1), (1.5, 1), (1, True), (1, 0), (1, 65)])
def test_invalid_generation_requests_fail(seed: object, families: object) -> None:
    with pytest.raises(fixture.FixtureError):
        fixture.generate_fixture(seed, families)


@pytest.mark.parametrize("field", ["answers", "affected", "hop_distances"])
def test_false_answer_or_intervention_metadata_rejected(field: str) -> None:
    records = fixture.generate_fixture(13, 2)
    if field == "answers":
        records[0][field][0][0] = 1 - records[0][field][0][0]
    elif field == "affected":
        records[0][field][0] = not records[0][field][0]
    else:
        records[0][field][0][0] += 1
    assert not fixture.validate_fixture(records)["passed"]


def test_true_is_not_a_valid_integer_answer() -> None:
    records = fixture.generate_fixture(13, 1)
    records[0]["answers"][0][0] = bool(records[0]["answers"][0][0])
    assert not fixture.validate_fixture(records)["passed"]


def test_presentation_only_shuffle_is_not_a_semantic_twin() -> None:
    records = fixture.generate_fixture(13, 1)
    record = next(record for record in records if record["variant"] == "affected")
    lines = record["contexts"][0].splitlines()
    record["contexts"][1] = "\n".join([lines[0], *reversed(lines[1:])])
    assert not fixture.validate_fixture(records)["passed"]


def test_independent_twin_presentation_shuffle_rejected() -> None:
    records = fixture.generate_fixture(13, 1)
    lines = records[0]["contexts"][1].splitlines()
    records[0]["contexts"][1] = "\n".join([lines[0], *reversed(lines[1:])])
    assert not fixture.validate_fixture(records)["passed"]


def test_single_variant_or_duplicate_variant_rejected() -> None:
    records = fixture.generate_fixture(13, 1)
    assert not fixture.validate_fixture(records[:1])["passed"]
    assert not fixture.validate_fixture([records[0], copy.deepcopy(records[0])])["passed"]


def test_duplicate_original_world_cannot_masquerade_as_independent_family() -> None:
    records = fixture.generate_fixture(13, 1)
    copies = copy.deepcopy(records)
    for record in copies:
        record["metadata"]["family_index"] = 1
        record["family_id"] = "v13-s0-seed13-family0001"
        record["pair_id"] = record["family_id"] + ":" + record["variant"]
    report = fixture.validate_fixture(records + copies)
    assert not report["passed"]
    assert any("different uncertainty families" in error for error in report["errors"])


@pytest.mark.parametrize("positions", [(0, 3), (2, 3)])
def test_endpoint_and_adjacent_primary_queries_rejected(positions: tuple[int, int]) -> None:
    records = fixture.generate_fixture(13, 1)
    record = records[0]
    order = record["metadata"]["original_order"]
    left, right = [order[i] for i in positions]
    template = fixture.TEMPLATES[record["metadata"]["template"]]
    record["queries"] = [
        template.format(left=left, right=right),
        template.format(left=right, right=left),
    ]
    report = fixture.validate_fixture(records)
    assert not report["passed"]
    assert any("endpoint query" in error or "adjacent query" in error for error in report["errors"])


@pytest.mark.parametrize("records", [None, [], "records", [None], [{}]])
def test_malformed_fixture_returns_failure(records: object) -> None:
    report = fixture.validate_fixture(records)
    assert not report["passed"]
    assert report["errors"]
    assert report["shortcut_probes"] is None


def test_cycle_or_unknown_query_entity_rejected_by_text_oracle() -> None:
    context = fixture.HEADER + "\n- A is ranked above B.\n- B is ranked above A."
    with pytest.raises(fixture.FixtureError):
        fixture.symbolic_oracle(context, "Is A ranked above B? Answer:")
    context = fixture.HEADER + "\n- A is ranked above B.\n- B is ranked above C."
    with pytest.raises(fixture.FixtureError):
        fixture.symbolic_oracle(context, "Is A ranked above Missing? Answer:")
    assert fixture.symbolic_oracle(context, "Is A ranked above C? Answer:") == 1
    assert fixture.symbolic_oracle(context, "Does C outrank A? Answer:") == 0


def test_cli_runs_without_site_packages_and_does_not_write_files(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(SCRIPT),
            "--seed",
            "13",
            "--families",
            "2",
            "--include-records",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["passed"] and len(report["fixture_records"]) == 4
    assert list(tmp_path.iterdir()) == []
