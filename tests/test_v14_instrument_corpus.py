from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/v14_instrument_corpus.py"
SPEC = importlib.util.spec_from_file_location("v14_corpus_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
corpus_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(corpus_module)


@pytest.fixture(scope="module")
def corpus():
    return corpus_module.generate_corpus()


def test_fixed_sampling_shape_and_claim_boundaries(corpus) -> None:
    assert corpus == corpus_module.generate_corpus()
    assert json.loads(json.dumps(corpus)) == corpus
    before = copy.deepcopy(corpus)
    audit = corpus_module.validate_corpus(corpus)
    assert audit["passed"] and audit["errors"] == []
    assert audit["seed"] == 1402
    assert all(audit["checks"].values())
    for name in (
        "task_qualified",
        "model_capability_assessed",
        "holdout_model_scored",
        "training_authorized",
        "wording_generalization_qualified",
    ):
        assert audit[name] is False
    for split in ("calibration", "holdout"):
        summary = audit["splits"][split]
        assert summary["families"] == 12
        assert summary["primary_families_by_hop"] == {2: 4, 3: 4, 4: 4}
        assert summary["primary_records"] == 96 and summary["primary_cases"] == 384
        assert summary["easy_records"] == 24 and summary["easy_cases"] == 96
        assert summary["primary_case_counts_by_hop_and_affected"] == {
            str(h): {"false": 64, "true": 64} for h in (2, 3, 4)
        }
    assert corpus == before


def test_text_oracle_query_balance_and_direct_edge_separation(corpus) -> None:
    for records in corpus.values():
        counts = defaultdict(Counter)
        for record in records:
            meta = record["metadata"]
            assert record["heldout_queries"] == [False, False]
            assert meta["wording_held_out_from_training"] is False
            for side, context in enumerate(record["contexts"]):
                for i, query in enumerate(record["queries"]):
                    answer = corpus_module.symbolic_oracle(context, query)
                    assert answer == record["answers"][side][i]
                    counts[meta["family_id"], meta["role"], query][answer] += 1
                    direct = corpus_module._HELPER._direct_edge_endpoint(context, query)
                    assert direct is None if meta["role"] == "primary" else direct == answer
        assert all(c[0] == c[1] for c in counts.values())


def test_split_worlds_and_uncertainty_families_are_disjoint(corpus) -> None:
    worlds, families = {}, {}
    for split, records in corpus.items():
        families[split] = {r["metadata"]["family_id"] for r in records}
        worlds[split] = {tuple(order) for r in records for order in r["metadata"]["world_orders"]}
        for family in families[split]:
            group = [r for r in records if r["metadata"]["family_id"] == family]
            assert len(group) == 10
            assert {r["metadata"]["template"] for r in group} == {"ranked_above", "outrank"}
    assert not families["calibration"] & families["holdout"]
    assert not worlds["calibration"] & worlds["holdout"]


def test_shortcut_audit_is_not_model_or_unseen_wording_qualification(corpus) -> None:
    audit = corpus_module.validate_corpus(corpus)
    for summary in audit["splits"].values():
        primary, easy = [summary["shortcut_probes"][role] for role in ("primary", "easy")]
        assert primary["direct_edge_endpoint_abstaining"]["abstentions"] == 384
        assert primary["direct_edge_endpoint_abstaining"]["accuracy_answered"] is None
        assert primary["symbolic_path_oracle"]["accuracy_answered"] == 1.0
        assert easy["direct_edge_endpoint_abstaining"]["accuracy_answered"] == 1.0
        for role in (primary, easy):
            for probe in (
                "query_text_in_sample_majority",
                "query_position_in_sample_majority",
                "query_only_constant_no",
                "query_only_constant_yes",
            ):
                assert role[probe]["accuracy_answered"] == 0.5
            assert "do not rule out other shortcuts" in role["interpretation"]
            assert "not learned held-out" in role["interpretation"]


@pytest.mark.parametrize("field", ["answers", "affected", "hop_distances", "heldout_queries"])
def test_engine_fields_tampering_fails(corpus, field) -> None:
    altered = copy.deepcopy(corpus)
    record = altered["calibration"][0]
    if field == "answers":
        record[field][0][0] = 1 - record[field][0][0]
    elif field in ("affected", "heldout_queries"):
        record[field][0] = not record[field][0]
    else:
        record[field] = [[2, 2], [2, 2]]
    assert not corpus_module.validate_corpus(altered)["passed"]


@pytest.mark.parametrize(
    "field",
    [
        "seed",
        "split",
        "family_id",
        "family_index",
        "primary_hop",
        "template",
        "orientation",
        "variant",
        "causal_edit_claim",
        "edit_distance",
        "base_swapped_positions",
        "swapped_positions",
        "base_original_order",
        "base_primary_query_entities",
        "query_entities",
        "world_orders",
        "side_hop_distances",
        "fact_position_order",
        "alternate_wording",
        "wording_held_out_from_training",
    ],
)
def test_every_binding_metadata_field_tampering_fails(corpus, field) -> None:
    altered = copy.deepcopy(corpus)
    record = next(r for r in altered["calibration"] if r["metadata"]["role"] == "primary")
    record["metadata"][field] = "tampered"
    assert not corpus_module.validate_corpus(altered)["passed"]


def test_family_or_mirror_loss_and_cross_split_copy_fail(corpus) -> None:
    altered = copy.deepcopy(corpus)
    altered["holdout"][0] = copy.deepcopy(altered["calibration"][0])
    assert not corpus_module.validate_corpus(altered)["passed"]
    altered = copy.deepcopy(corpus)
    altered["calibration"][0] = copy.deepcopy(altered["calibration"][1])
    assert not corpus_module.validate_corpus(altered)["passed"]


def test_false_text_and_independent_fact_shuffle_fail(corpus) -> None:
    for replacement in ("cycle", "shuffle"):
        altered = copy.deepcopy(corpus)
        record = altered["calibration"][0]
        if replacement == "cycle":
            record["contexts"][1] = (
                "World facts. The ranking is transitive.\n- A is ranked above A."
            )
        else:
            lines = record["contexts"][1].splitlines()
            record["contexts"][1] = "\n".join([lines[0], *reversed(lines[1:])])
        assert not corpus_module.validate_corpus(altered)["passed"]


@pytest.mark.parametrize(
    "malformed", [None, [], {}, {"calibration": []}, {"calibration": None, "holdout": []}]
)
def test_malformed_input_returns_failure(malformed) -> None:
    audit = corpus_module.validate_corpus(malformed)
    assert not audit["passed"] and audit["errors"]
    assert audit["splits"] == {}


def test_engine_encoder_accepts_flat_hops_and_unique_pair_ids(corpus, monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(REPO / "src"))
    from latent_workspace_ft_v10.engine import DataConfig, _encode_functional_world_pair

    class Tokenizer:
        bos_token_id = None
        eos_token_id = None

        def __init__(self):
            self.vocabulary = {}

        def encode(self, text, add_special_tokens=False):
            return [
                self.vocabulary.setdefault(token, len(self.vocabulary) + 1)
                for token in text.split()
            ]

    config = DataConfig(
        functional_context_max_length=256,
        functional_query_max_length=256,
        functional_inline_max_length=512,
    )
    tokenizer = Tokenizer()
    pair_ids = []
    for records in corpus.values():
        for record in records:
            encoded = _encode_functional_world_pair(record, tokenizer, config)
            assert encoded["functional_hop_distances"] == record["hop_distances"]
            assert encoded["functional_heldout_queries"] == [False, False]
            assert encoded["functional_answers"] == record["answers"]
            pair_ids.append(encoded["functional_pair_id"])
    assert len(pair_ids) == len(set(pair_ids)) == 240


def test_cli_is_stdlib_only_fresh_and_hash_bound(tmp_path) -> None:
    output = tmp_path / "fresh"
    command = [sys.executable, "-I", "-S", str(SCRIPT), "--output-dir", str(output)]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    audit = json.loads((output / "INSTRUMENT_CORPUS_AUDIT.json").read_text())
    assert audit["passed"] and audit["holdout_model_scored"] is False
    assert set(p.name for p in output.iterdir()) == {
        "instrument_calibration.jsonl",
        "instrument_holdout.jsonl",
        "INSTRUMENT_CORPUS_AUDIT.json",
    }
    for name, binding in audit["artifacts"].items():
        payload = (output / name).read_bytes()
        assert binding == {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
    assert (
        audit["generator_sources"][SCRIPT.name] == hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    )
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    assert completed.returncode != 0
    assert {p.name: p.read_bytes() for p in output.iterdir()} == before


def test_committed_artifacts_match_frozen_generation(corpus) -> None:
    data = REPO / "data/v14"
    parsed = {
        split: [
            json.loads(line)
            for line in (data / f"instrument_{split}.jsonl").read_text().splitlines()
        ]
        for split in corpus
    }
    assert parsed == corpus
    audit = json.loads((data / "INSTRUMENT_CORPUS_AUDIT.json").read_text())
    assert audit["passed"]
    for path in (SCRIPT, corpus_module.HELPER_PATH):
        assert (
            audit["generator_sources"][path.name] == hashlib.sha256(path.read_bytes()).hexdigest()
        )
    for name, binding in audit["artifacts"].items():
        payload = (data / name).read_bytes()
        assert len(payload) == binding["bytes"]
        assert hashlib.sha256(payload).hexdigest() == binding["sha256"]
