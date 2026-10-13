"""Post-result offline replay and malformed-publication tests; no model calls."""

import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import summarize_v15_readout_adapters as summary  # noqa: E402

BUNDLE = REPO / "provenance/pilots/v15_readout_adapters_20261010"


def test_exact_replay_inventory_and_publication_table():
    result = summary.analyze(BUNDLE)
    assert result == summary.read(BUNDLE / "SUMMARY.json")
    assert summary.inventory(BUNDLE) == summary.read(BUNDLE / "ARTIFACT_INDEX.json")
    assert summary.publication_table(result) in (BUNDLE / "README.md").read_text()
    assert len(result["results"]) == 4
    assert sum(r["all_pair_changed_full_vocab"] for r in result["results"]) == 64
    assert sum(r["affected_nonzero_applied_hidden"] for r in result["results"]) == 16
    assert sum(r["stages"][-1]["positive_donor"] for r in result["results"]) == 0
    assert result["old_expression_gate"] == "FAIL"


def test_claim_denominators_exact_examples_resources_and_links():
    readme = (BUNDLE / "README.md").read_text()
    changed_gap, pairs, affected = [], [], []
    for phase, arm, _step in summary.STATES:
        panel = summary.read(BUNDLE / "raw" / f"{phase}_{arm}.json")
        rows = {(r["world"], r["query"], r["condition"]): r for r in panel["rows"]}
        pairs.extend(panel["pairs"])
        for pair in panel["pairs"]:
            key = pair["world"], pair["query"]
            if pair["affected"]:
                affected.append(pair)
                assert rows[*key, "intact"]["native_scores"] == rows[*key, "twin"]["native_scores"]
            if pair["transport"]["native_published_gap_change"][0]:
                changed_gap.append((phase, arm, *key, pair))
    assert len(pairs) == 64 and len(affected) == 16
    assert all(not p["transport"]["greedy_token_changed"][0] for p in pairs)
    assert len(changed_gap) == 1
    phase, arm, world, query, row = changed_gap[0]
    assert (phase, arm, world, query, row["affected"]) == ("full", "full", 1, 5, False)
    assert row["transport"]["native_published_gap_change"] == [-0.125]
    for key in summary.STAGES[:2]:
        assert str(row["transport"][key][0]) in readme
    native = summary.read(BUNDLE / "raw/full_full.json")
    expected = [p for p in native["pairs"] if p["query"] == 0]
    table = [line.split(" | ") for line in readme.splitlines() if line.startswith("| world ")]
    assert len(table) == 2
    for raw, fields in zip(expected, table):
        assert float(fields[2]) == raw["transport"][summary.STAGES[0]][0]
        assert float(fields[3]) == raw["transport"][summary.STAGES[1]][0]
        assert float(fields[4]) == raw["transport"][summary.STAGES[2]][0]
        assert int(fields[5].strip(" |")) == raw["transport"]["changed_last_vocab_elements"][0]
    finish = summary.read(BUNDLE / "raw/FINISHED.json")
    assert str(finish["elapsed_seconds"]) in readme
    for key in ("peak_cuda_allocated_bytes", "peak_cuda_reserved_bytes"):
        assert str(finish[key] / 2**30) in readme
    import re

    for link in re.findall(r"\]\(([^)]+)\)", readme):
        assert (BUNDLE / link).exists(), link


@pytest.fixture
def copied(tmp_path):
    target = tmp_path / "bundle"
    shutil.copytree(BUNDLE, target)
    return target


@pytest.mark.parametrize(
    "mutation",
    ("duplicate_pair", "missing_row", "wrong_gap", "nan", "zero", "changed_weights", "wrong_label"),
)
def test_malformed_panel_fails_closed(copied, mutation):
    path = copied / "raw/reader_legacy.json"
    data = summary.read(path)
    if mutation == "duplicate_pair":
        data["pairs"][-1] = data["pairs"][0]
    elif mutation == "missing_row":
        data["rows"].pop()
    elif mutation == "wrong_gap":
        data["pairs"][0]["transport"]["native_published_gap_change"] = [0.125]
    elif mutation == "nan":
        data["pairs"][0]["transport"]["intended_linear_gap_change_fp64"] = [float("nan")]
    elif mutation == "zero":
        data["rows"][2]["zero_exact"] = False
    elif mutation == "changed_weights":
        data["weights_unchanged"] = False
    else:
        data["pairs"][0]["donor_sign"] *= -1
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        summary.analyze(copied)


def test_missing_terminal_is_not_completion(copied):
    (copied / "raw/FINISHED.json").unlink()
    with pytest.raises(FileNotFoundError):
        summary.analyze(copied)


def test_error_receipt_cannot_be_hidden_by_finished(copied):
    (copied / "raw/ERROR.json").write_text("{}")
    with pytest.raises(ValueError, match="error receipt"):
        summary.analyze(copied)


def test_mismatched_source_rejected(copied):
    path = copied / "SOURCE_SEAL.json"
    data = summary.read(path)
    data["source_commit"] = "wrong"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Source commit"):
        summary.analyze(copied)
