import copy
import json
from pathlib import Path

import pytest

from latent_workspace import world_bank as wb

ROOT = Path(__file__).resolve().parents[1]


def plan():
    value = json.loads((ROOT / "configs/v1_0/WORLD_BANK_01.json").read_text())
    value["groups_per_family"] = dict(train=4, dev=1, test=1)
    value["heldout_groups"] = 2
    return value


@pytest.mark.parametrize("family", [*wb.FAMILIES, "linked_location"])
def test_twins_and_controls_are_solved_from_visible_facts(family):
    split = "ood" if family == "linked_location" else "train"
    rows = wb.group_rows(f"test-{family}", family, split, 3)
    result = wb.audit(rows, [])
    assert result["world_rows"] == 8 and result["world_groups"] == 1
    left, right = rows[0], rows[4]
    assert left["answer"] != right["answer"]
    assert wb.solve([], left["query_spec"]) == (wb.UNKNOWN, [])


def test_reproducible_bank_and_group_level_splits():
    rows, instructions = wb.build(plan())
    assert (rows, instructions) == wb.build(plan())
    summary = wb.audit(rows, instructions)
    assert summary["world_groups"] == 38
    assert summary["world_rows"] == 304
    assert summary["instruction_rows"] == 128
    items = wb.teacher_inputs(rows, instructions, plan())
    assert len(items) == 64
    assert all(x["row"]["split"] == "train" for x in items)
    instruction_items = [x for x in items if x["kind"] == "instruction"]
    assert len(instruction_items) == 16
    assert len({x["row"]["family"] for x in instruction_items}) == 8


@pytest.mark.parametrize(
    "field,value",
    [
        ("answer_value", "wrong"),
        ("answer", "wrong"),
        ("evidence_ids", []),
        ("memory", "invented"),
        ("query", "invented"),
        ("memory_sha256", "bad"),
    ],
)
def test_corrupted_answer_rendering_or_evidence_fails(field, value):
    rows = wb.group_rows("test-location", "location", "train", 3)
    rows[0][field] = value
    with pytest.raises(ValueError):
        wb.audit(rows, [])


def test_split_leak_and_missing_sibling_rejected():
    rows = wb.group_rows("test-location", "location", "train", 3)
    corrupted = copy.deepcopy(rows)
    corrupted[-1]["split"] = "test"
    with pytest.raises(ValueError, match="leakage"):
        wb.audit(corrupted, [])
    with pytest.raises(ValueError, match="Incomplete"):
        wb.audit(rows[:-1], [])


def test_transitive_solver_handles_cycles_and_unknowns():
    facts = [
        dict(id="a", relation="above", subject="A", value="B"),
        dict(id="b", relation="above", subject="B", value="C"),
    ]
    query = dict(op="higher", left="A", right="C")
    assert wb.solve(facts, query) == ("A", ["a", "b"])
    facts.append(dict(id="c", relation="above", subject="C", value="A"))
    assert wb.solve(facts, query) == (wb.UNKNOWN, [])


def test_latest_version_ambiguity_is_unknown():
    facts = [
        dict(id="a", relation="at_version", subject="A", value="X", version=2),
        dict(id="b", relation="at_version", subject="A", value="Y", version=2),
    ]
    assert wb.solve(facts, dict(op="latest", subject="A")) == (wb.UNKNOWN, [])


def test_structural_teacher_checks_do_not_certify_semantic_equivalence():
    row = wb.group_rows("teacher-location", "location", "train", 2)[0]
    candidate = dict(
        question="An entirely different question.",
        answer=f"{row['answer_value']} plus an invented detail.",
        answer_value=row["answer_value"],
        evidence_ids=row["evidence_ids"],
    )
    result = wb.inspect_candidate(candidate, dict(kind="world", row=row))
    assert result["structural_pass"]
    assert result["semantic_equivalence"] == "UNREVIEWED"
    assert result["training_approved"] is False
    candidate["answer_value"] = "wrong"
    assert not wb.inspect_candidate(candidate, dict(kind="world", row=row))["structural_pass"]


@pytest.mark.parametrize("candidate", [None, [], {}, {"question": "x"}])
def test_malformed_teacher_candidates_are_not_admitted(candidate):
    result = wb.inspect_candidate(candidate, dict(kind="world", row={}))
    assert not result["structural_pass"] and not result["training_approved"]


def test_heldout_family_cannot_enter_training():
    rows = wb.group_rows("test-composed", "linked_location", "train", 3)
    with pytest.raises(ValueError, match="Held-out"):
        wb.audit(rows, [])
