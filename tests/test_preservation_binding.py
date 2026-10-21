"""Offline metadata/causal-layout qualification; no model or target generation."""

import copy
import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest

from latent_workspace.execution import plan_hash
from latent_workspace.preservation_binding import bind_preservation_targets


def fixture():
    rows = [
        dict(
            key="train/a",
            split="train",
            language="en",
            memory_ids=[],
            input_ids=[1, 4, 6, 8, 2],
            labels=[-100, -100, 6, -100, 2],
            supervised_tokens=2,
        ),
        dict(
            key="train/b",
            split="train",
            language="en",
            memory_ids=[],
            input_ids=[1, 7, 2],
            labels=[-100, 7, 2],
            supervised_tokens=2,
        ),
    ]
    receipt = dict(
        bytes=256,
        input_sha256="1" * 64,
        native_sha256="2" * 64,
        sha256="3" * 64,
        source_commit="4" * 40,
        target_dtype="float32",
        temperature=1.0,
        tensor_bytes=160,
        vocabulary=10,
        teacher_policy="synthetic metadata fixture, no real teacher",
        rows=[
            dict(
                index=str(i),
                key=r["key"],
                row_sha256=plan_hash(r),
                shape=[2, 10],
                supervised_tokens=2,
            )
            for i, r in enumerate(rows)
        ],
    )
    return receipt, rows


def bind(receipt, rows):
    return bind_preservation_targets(receipt, rows, expected_receipt_plan_sha256=plan_hash(receipt))


def test_exact_coverage_causal_shift_and_detached_manifest():
    receipt, rows = fixture()
    bound = bind(receipt, rows)
    assert bound.rows[0].causal_logit_positions == (1, 3)
    assert bound.rows[1].causal_logit_positions == (0, 1)
    assert bound.require_row(rows[0]) == bound.rows[0]
    manifest = bound.manifest()
    assert json.loads(json.dumps(manifest)) == manifest
    assert manifest["target_body_validation"] == "NOT_PERFORMED_METADATA_ONLY"
    assert manifest["owner_integration"] == "NOT_IMPLEMENTED"
    assert all("input_ids" not in r and "labels" not in r for r in manifest["rows"])
    manifest["rows"][0]["causal_logit_positions"][0] = 99
    receipt["rows"][0]["index"] = "99"
    assert bound.rows[0].tensor_key == "0" and bound.rows[0].causal_logit_positions == (1, 3)
    with pytest.raises(FrozenInstanceError):
        bound.vocabulary = 3


def test_expected_digest_is_external_not_trusted_from_receipt():
    receipt, rows = fixture()
    expected = plan_hash(receipt)
    receipt["teacher_policy"] = "changed execution"
    with pytest.raises(ValueError, match="Pinned"):
        bind_preservation_targets(receipt, rows, expected_receipt_plan_sha256=expected)


def test_receipt_plan_identity_is_distinct_from_raw_json_byte_hash():
    receipt, rows = fixture()
    raw_json = json.dumps(receipt, indent=2) + "\n"
    raw_sha = hashlib.sha256(raw_json.encode()).hexdigest()
    with pytest.raises(ValueError, match="Pinned"):
        bind_preservation_targets(receipt, rows, expected_receipt_plan_sha256=raw_sha)
    actual = bind_preservation_targets(
        json.loads(raw_json), rows, expected_receipt_plan_sha256=plan_hash(receipt)
    )
    assert actual.manifest()["receipt_digest_scheme"] == "canonical_json_plan_hash_v1"


@pytest.mark.parametrize(
    "change",
    [
        "missing_row",
        "reorder",
        "duplicate",
        "input",
        "continuation",
        "labels",
        "metadata",
        "memory",
        "split",
        "language",
        "first_target",
        "wrong_label",
        "all_masked",
        "tokens_bool",
        "input_bool",
        "label_bool",
        "vocab_oob",
        "pad",
        "crop",
        "memory_mask",
        "missing_field",
    ],
)
def test_wrong_rows_are_rejected_even_with_rehashed_target_entry(change):
    receipt, rows = fixture()
    if change == "missing_row":
        rows.pop()
    elif change == "reorder":
        rows.reverse()
    elif change == "duplicate":
        rows[1] = copy.deepcopy(rows[0])
        receipt["rows"][1] = {**receipt["rows"][0], "index": "1"}
    else:
        row = rows[0]
        if change == "input":
            row["input_ids"][1] = 3
        elif change == "continuation":
            row["input_ids"][2] = row["labels"][2] = 9
        elif change == "labels":
            row["labels"] = [-100, 4, 6, -100, -100]
        elif change == "metadata":
            row["source"] = "another document"
        elif change == "memory":
            row["memory_ids"] = [1]
        elif change == "split":
            row["split"] = "confirmation"
        elif change == "language":
            row["language"] = "ja"
        elif change == "first_target":
            row["labels"][0] = 1
        elif change == "wrong_label":
            row["labels"][2] = 7
        elif change == "all_masked":
            row["labels"] = [-100] * 5
            row["supervised_tokens"] = 0
        elif change == "tokens_bool":
            row["supervised_tokens"] = True
        elif change == "input_bool":
            row["input_ids"][0] = True
        elif change == "label_bool":
            row["labels"][2] = True
        elif change == "vocab_oob":
            row["input_ids"][0] = 10
        elif change == "pad":
            row["attention_mask"] = [1, 1, 1, 1, 0]
        elif change == "crop":
            row["input_ids"].pop()
        elif change == "memory_mask":
            row["memory_mask"] = [1]
        elif change == "missing_field":
            del row["language"]
        # Plausible content edits must fail against the original row fingerprint.
        # For malformed rows, rehash to ensure the semantic guard also rejects them.
        if change not in {"input", "continuation", "labels", "metadata"}:
            receipt["rows"][0]["row_sha256"] = plan_hash(row)
    with pytest.raises(ValueError):
        bind(receipt, rows)


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "native_hash",
        "source_commit",
        "target_hash",
        "input_hash",
        "dtype",
        "temperature",
        "temperature_bool",
        "vocabulary_bool",
        "policy",
        "row_extra",
        "index",
        "row_hash",
        "shape",
        "shape_bool",
        "count",
        "count_bool",
        "tensor_bytes",
        "file_bytes",
        "file_bytes_bool",
    ],
)
def test_malformed_receipt_is_rejected_even_with_recomputed_pin(change):
    receipt, rows = fixture()
    changes = {
        "extra": ("unexpected", 1),
        "native_hash": ("native_sha256", "wrong"),
        "source_commit": ("source_commit", "4" * 39),
        "target_hash": ("sha256", "3" * 63),
        "input_hash": ("input_sha256", "A" * 64),
        "dtype": ("target_dtype", "bfloat16"),
        "temperature": ("temperature", 2.0),
        "temperature_bool": ("temperature", True),
        "vocabulary_bool": ("vocabulary", True),
        "policy": ("teacher_policy", " "),
        "tensor_bytes": ("tensor_bytes", 159),
        "file_bytes": ("bytes", 160),
        "file_bytes_bool": ("bytes", True),
    }
    if change in changes:
        key, value = changes[change]
        receipt[key] = value
    else:
        key, value = {
            "row_extra": ("unexpected", 1),
            "index": ("index", "1"),
            "row_hash": ("row_sha256", "z" * 64),
            "shape": ("shape", [2, 9]),
            "shape_bool": ("shape", [True, 10]),
            "count": ("supervised_tokens", 3),
            "count_bool": ("supervised_tokens", True),
        }[change]
        receipt["rows"][0][key] = value
    with pytest.raises(ValueError):
        bind(receipt, rows)


def test_bound_row_is_rechecked_at_use_not_only_at_admission():
    receipt, rows = fixture()
    bound = bind(receipt, rows)
    changed = copy.deepcopy(rows[0])
    changed["input_ids"][1] = 3
    with pytest.raises(ValueError, match="content changed"):
        bound.require_row(changed)
    changed = copy.deepcopy(rows[0])
    changed["key"] = "unknown"
    with pytest.raises(ValueError, match="absent"):
        bound.require_row(changed)


@pytest.mark.parametrize("vocabulary", [17, 32768, 64000])
def test_binding_is_not_locked_to_mistral_vocabulary(vocabulary):
    receipt, rows = fixture()
    receipt["vocabulary"] = vocabulary
    for row in receipt["rows"]:
        row["shape"][1] = vocabulary
    receipt["tensor_bytes"] = 4 * vocabulary * 4
    receipt["bytes"] = receipt["tensor_bytes"] + 256
    assert bind(receipt, rows).vocabulary == vocabulary


@pytest.mark.parametrize(
    "objective",
    [
        "query_token_ce_plus_train_preservation_forward_kl_v1",
        {"type": "preservation_kl", "coefficient": 1.0},
    ],
)
def test_current_owner_does_not_silently_admit_a_new_objective(objective):
    from latent_workspace.native_owner import _validate_contract

    contract = dict(
        source_commit="1" * 40,
        original_base_sha256="2" * 64,
        data_sha256="3" * 64,
        objective="query_only_token_weighted_causal_nll",
    )
    _validate_contract(contract)
    contract["objective"] = objective
    with pytest.raises(ValueError, match="Unknown objective"):
        _validate_contract(contract)
