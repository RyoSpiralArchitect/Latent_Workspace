import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import prepare_v14_mech_corpus as corpus  # noqa: E402


def _records(seed=corpus.SEED, worlds=4):
    return corpus.make_functional_relation_pair_records(worlds=worlds, seed=seed)


def test_canonical_fresh_corpus_is_deterministic_disjoint_and_choices_only(tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    receipt = corpus.prepare(left)
    assert corpus.prepare(right) == receipt
    assert (left / "fresh_eval.jsonl").read_bytes() == (right / "fresh_eval.jsonl").read_bytes()
    assert receipt["fresh_corpus"]["sha256"] == corpus.sha256(left / "fresh_eval.jsonl")
    assert receipt["accepted_generator_indices"] == list(range(64))
    audit = receipt["split_audit"]
    assert (audit["prior_world_pairs"], audit["fresh_world_pairs"]) == (320, 64)
    assert not any(audit["prior_overlaps"].values())
    assert not any(audit["internal_overlaps"].values())
    expected = corpus.make_functional_relation_pair_records(
        worlds=128,
        seed=corpus.SEED,
        heldout_template="Does {left} outrank {right}? Answer:",
        heldout_fraction=0.5,
    )[:64]
    for record in expected:
        record["choices"] = [" no", " yes"]
    actual = [json.loads(line) for line in (left / "fresh_eval.jsonl").read_text().splitlines()]
    assert actual == expected
    assert json.loads((left / "PREPARATION.json").read_text()) == receipt


@pytest.mark.parametrize("overlap_kind", ["pair_ids", "orders", "unordered_twins", "contexts"])
def test_overlap_is_filtered_even_when_other_identity_fields_differ(overlap_kind):
    old = _records(seed=37, worlds=1)[0]
    candidate, safe = _records(worlds=2)
    if overlap_kind == "pair_ids":
        candidate["metadata"]["pair_id"] = old["metadata"]["pair_id"]
    elif overlap_kind == "orders":
        candidate["metadata"]["orders"][0] = old["metadata"]["orders"][0]
    elif overlap_kind == "unordered_twins":
        candidate["metadata"]["orders"] = old["metadata"]["orders"][::-1]
    else:
        candidate["contexts"][0] = old["contexts"][0]
    accepted, rejected = corpus.select_disjoint([candidate, safe], [old], count=1)
    assert accepted == [safe]
    assert rejected[0]["overlaps"][overlap_kind] > 0
    with pytest.raises(ValueError, match="overlap"):
        corpus.audit_disjoint([old], [candidate])


def test_within_fresh_duplicates_rejected_and_exhaustion_fails_closed():
    first, second = _records(worlds=2)
    accepted, rejected = corpus.select_disjoint([first, copy.deepcopy(first), second], [], count=2)
    assert accepted == [first, second] and len(rejected) == 1
    with pytest.raises(ValueError, match="overlap"):
        corpus.audit_disjoint([], [first, first])
    with pytest.raises(ValueError, match="Insufficient"):
        corpus.select_disjoint([first, first], [], count=2)


def test_existing_output_is_never_replaced(tmp_path):
    output = tmp_path / "output"
    corpus.prepare(output)
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    with pytest.raises(FileExistsError):
        corpus.prepare(output)
    assert before == {path.name: path.read_bytes() for path in output.iterdir()}


def test_changed_prior_corpus_fails_before_creating_output(tmp_path):
    fake_repo = tmp_path / "repo"
    prior = fake_repo / corpus.PRIOR_FILES[0][0]
    prior.parent.mkdir(parents=True)
    prior.write_text("changed\n")
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="identity changed"):
        corpus.prepare(output, repo=fake_repo)
    assert not output.exists()
