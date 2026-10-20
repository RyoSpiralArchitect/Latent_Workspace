"""Validate the Git-ready projection without copying raw prose/tokens into Git."""

import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "provenance/data/native_preservation_bank01_20261021"


def read(name):
    return json.loads((BUNDLE / "furnace" / name).read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_source_and_public_payloads_match_frozen_manifest():
    manifest = read("MANIFEST.json")
    for name, expected in manifest["source"].items():
        assert digest(ROOT / name) == expected
    for name, item in manifest["files"].items():
        path = BUNDLE / "furnace" / name
        if name == "rows.json.gz":
            assert not path.exists()  # raw candidate content stays on Furnace
        else:
            assert path.stat().st_size == item["bytes"]
            assert digest(path) == item["sha256"]


def test_index_recounts_all_rows_groups_masks_and_lengths():
    summary = read("SUMMARY.json")
    rows = json.loads(gzip.decompress((BUNDLE / "furnace/index.json.gz").read_bytes()))
    counts, tokens, long_rows = Counter(), Counter(), Counter()
    groups = {}
    for r in rows:
        assert not {"text", "messages", "input_ids", "labels"} & r.keys()
        assert r["training_approved"] is False and r["memory"] == []
        assert groups.setdefault(r["group_id"], r["split"]) == r["split"]
        key = f"{r['split']}/{r['role']}/{r['language']}"
        counts[key] += 1
        tokens[key] += r["supervised_tokens"]
        if r["input_tokens"] > 128:
            long_rows[key] += 1
    assert dict(counts) == summary["rows_by_bucket"]
    assert dict(tokens) == summary["supervised_tokens_by_bucket"]
    assert dict(long_rows) == summary["outside_tested_128_query_axis"]
    assert len(rows) == summary["rows"] == 1938
    assert len(groups) == summary["groups"] == 1050
    assert sum(v for k, v in tokens.items() if k.startswith("train/")) == 324616
    assert sum(v for k, v in tokens.items() if k.startswith("dev/")) == 39761
    assert sum(long_rows.values()) == 635


def test_download_receipts_rights_and_unknowns_are_not_promoted():
    s = read("SUMMARY.json")
    assert sum(x["bytes"] for x in s["hf_source_files"].values()) == 41617955
    for name in ["README.md", "LICENSE"]:
        assert digest(BUNDLE / "source_cards" / name) == s["hf_source_files"][name]["sha256"]
    assert s["qspace"]["training_rows"] == 0
    assert s["qspace"]["upstream_revision"] is None
    assert s["oasst"]["official_validation_used_for_training"] == 0
    assert s["oasst"]["quota_shortfalls"]["train/code/ja"] == 16
    assert s["functional_code_correctness"] == "UNTESTED"
    assert s["non_regression"] == "NOT_ESTABLISHED" and s["old_expression_gate"] == "FAIL"
    assert s["training_admissions"] == s["native_weight_updates"] == s["new_sequences"] == 0
