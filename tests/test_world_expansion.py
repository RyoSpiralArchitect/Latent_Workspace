import copy
from pathlib import Path

import pytest

from latent_workspace import execution as ex
from latent_workspace import world_expansion as wb

ROOT = Path(__file__).resolve().parents[1]


def plan():
    result = ex.read(ROOT / "configs/v23/WORLD_BANK_02.json")
    result["groups_per_family"] = dict(train=2, dev=2, confirmation=2)
    result["heldout_groups"] = 2
    return result


def test_deterministic_new_groups_and_exact_denominators():
    p = plan()
    rows = wb.build(p)
    assert rows == wb.build(p)
    summary = wb.audit(rows, [], p)
    assert summary["rows"] == 352 and summary["groups"] == 44
    assert summary["unique_sequences"] == 264
    assert summary["rows_by_style"] == dict(independent=176, shared_prefix=176)
    assert summary["new_ood_family"] == "owner_chain_location"
    assert summary["promoted_former_ood_family"] == "linked_location"
    assert any(r["family"] == "linked_location" and r["split"] == "train" for r in rows)
    assert not any(r["family"] == "owner_chain_location" and r["split"] != "ood" for r in rows)


@pytest.mark.parametrize("field", ["answer", "facts", "split", "group_id", "evidence_ids"])
def test_no_corrupted_or_relabelled_rows(field):
    p = plan()
    rows = wb.build(p)
    rows[0][field] = "tampered"
    with pytest.raises(ValueError, match="regeneration"):
        wb.audit(rows, [], p)


@pytest.mark.parametrize("kind", ["group", "text", "identifier"])
def test_prior_bank_is_exclusion_only(kind):
    p = plan()
    rows = wb.build(p)
    old = copy.deepcopy(rows[0])
    if kind != "group":
        old["group_id"] = "different-old-group"
    if kind == "identifier":
        old["query"] = "different question"
    with pytest.raises(ValueError, match="Historical"):
        wb.audit(rows, [old], p)


def test_near_names_share_eight_letters_and_distractors_are_not_evidence():
    rows = wb.group_rows("test-near", "linked_location", "train", 3, "shared_prefix")
    symbols = wb.names_in(rows)
    assert len({n[:-1] for n in symbols}) == 1
    for row in rows:
        assert not any(i.startswith("d") for i in row["evidence_ids"])
    assert rows[0]["query"] == rows[4]["query"]
    assert rows[0]["memory"] == rows[1]["memory"]
    assert rows[0]["answer"] != rows[4]["answer"]


def test_three_hop_missing_and_ambiguous_facts_are_unknown():
    row = wb.group_rows("test-depth", "owner_chain_location", "ood", 4, "independent")[0]
    assert len(row["evidence_ids"]) == 3
    for id_ in row["evidence_ids"]:
        facts = [f for f in row["facts"] if f["id"] != id_]
        assert wb.solve(facts, row["query_spec"]) == (wb.wb.UNKNOWN, [])
    facts = row["facts"] + [next(f for f in row["facts"] if f["id"] == row["evidence_ids"][0])]
    assert wb.solve(facts, row["query_spec"]) == (wb.wb.UNKNOWN, [])


def test_fixed_full_expansion_excludes_all_original_groups_and_identifiers():
    p = ex.read(ROOT / "configs/v23/WORLD_BANK_02.json")
    assert ex.digest(ROOT / p["prior_rows"]) == p["prior_rows_sha256"]
    result = wb.audit(wb.build(p), ex.read_gz(ROOT / p["prior_rows"]), p)
    assert result["groups"] == 512 and result["rows"] == 4096
    assert result["unique_sequences"] == 3072
    assert result["historical_groups_excluded"] == 1024
