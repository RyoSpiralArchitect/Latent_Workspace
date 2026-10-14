"""Synthetic reference ownership only: no original model capture or training."""

import copy
import hashlib
import json
import math
import random

import numpy as np
import pytest
import torch

from latent_workspace_ft_v10.v18_reference_bank import (
    ROLE,
    CapturePolicy,
    ReferenceBank,
    ReferenceRow,
    ReferenceSource,
)


def source():
    return ReferenceSource("synthetic/model", "a" * 40, "b" * 64, "c" * 64, "d" * 64)


def row(row_id="row-1", prefix=(0, 1), logits=(0.0, -0.5, 0.25, 1.0)):
    return ReferenceRow(row_id, "train-family", "e" * 64, "f" * 64, prefix, logits)


def bank(dtype="float32"):
    return ReferenceBank(source(), CapturePolicy(dtype), 4, 8, "0" * 64, (row(),))


def rehash(payload):
    body = {key: value for key, value in payload.items() if key != "content_sha256"}
    payload["content_sha256"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def primitive_tree(value):
    if type(value) is tuple:
        return all(primitive_tree(item) for item in value)
    return type(value) in (str, int, float)


@pytest.mark.parametrize("dtype", ["float16", "bfloat16", "float32", "float64"])
def test_strict_serialization_round_trip(dtype):
    original = bank(dtype)
    assert ReferenceBank.from_payload(original.snapshot()) == original
    restored = ReferenceBank.from_json(original.to_json())
    assert restored == original
    assert restored is not original and restored.rows is not original.rows
    assert restored.rows[0] is not original.rows[0]
    assert restored.rows[0].logits is not original.rows[0].logits
    assert restored.content_sha256 == original.content_sha256
    assert restored.to_json() == original.to_json()
    assert original.capture_policy.native_dtype == dtype
    assert dict(original.descriptor())["role"] == ROLE
    assert primitive_tree(original.descriptor())


def test_snapshot_and_descriptors_do_not_share_mutable_ownership():
    original = bank()
    expected = original.snapshot()
    snapshot = original.snapshot()
    restored = ReferenceBank.from_payload(snapshot)
    snapshot["rows"][0]["logits"][0] = 7.0
    snapshot["rows"][0]["prompt_token_ids"][0] = 3
    snapshot["source"]["model_repo"] = "other/model"
    snapshot["capture"]["native_dtype"] = "float64"
    assert original.snapshot() == expected
    assert restored.snapshot() == expected
    descriptor = original.descriptor_payload()
    descriptor["source"]["model_repo"] = "other/model"
    descriptor["families"][0][1] = "9" * 64
    descriptor["row_ids"].append("unowned")
    assert original.descriptor_payload()["source"]["model_repo"] == "synthetic/model"
    assert original.descriptor_payload()["row_ids"] == ["row-1"]
    assert original.snapshot() == expected


def test_canonical_records_are_immutable_and_own_no_tensor_or_dict():
    original = bank()
    for obj, name, value in (
        (original, "vocab_size", 99),
        (original.source, "model_repo", "new/model"),
        (original.capture, "native_dtype", "float64"),
        (original.rows[0], "logits", (0.0,)),
    ):
        with pytest.raises(AttributeError):
            setattr(obj, name, value)
        with pytest.raises(AttributeError):
            obj.unowned = torch.ones(1)
    assert primitive_tree(tuple(original.rows[0]))
    assert primitive_tree(tuple(original.source))
    with pytest.raises(TypeError):
        original.rows[0].logits[0] = 3.0


def test_runtime_tensors_are_fresh_detached_cpu_copies():
    original = bank("bfloat16")
    first = original.tensor("row-1")
    second = original.tensor("row-1")
    assert first.device.type == "cpu" and first.dtype == torch.bfloat16
    assert not first.requires_grad and first.grad_fn is None
    assert first.data_ptr() != second.data_ptr()
    first.fill_(9)
    assert second.tolist() == [0.0, -0.5, 0.25, 1.0]
    assert original.rows[0].logits == (0.0, -0.5, 0.25, 1.0)
    with pytest.raises(ValueError, match="Unknown reference row ID"):
        original.tensor("missing")


def test_tensor_ignores_default_device_without_changing_it():
    original = bank()
    with torch.device("meta"):
        assert original.tensor("row-1").device.type == "cpu"
        assert torch.empty(1).device.type == "meta"


def test_construction_serialization_and_tensor_creation_leave_global_rng_untouched():
    python_state = random.getstate()
    numpy_state = copy.deepcopy(np.random.get_state())
    torch_state = torch.get_rng_state().clone()
    original = bank()
    restored = ReferenceBank.from_json(original.to_json())
    restored.tensor("row-1")
    assert random.getstate() == python_state
    actual_numpy = np.random.get_state()
    assert actual_numpy[0] == numpy_state[0]
    assert np.array_equal(actual_numpy[1], numpy_state[1])
    assert actual_numpy[2:] == numpy_state[2:]
    assert torch.equal(torch.get_rng_state(), torch_state)


@pytest.mark.parametrize(
    "field",
    [
        "schema",
        "role",
        "split",
        "source",
        "capture",
        "vocab_size",
        "max_prefix_tokens",
        "split_manifest_sha256",
        "rows",
        "content_sha256",
    ],
)
def test_missing_top_level_fields_are_rejected(field):
    payload = bank().snapshot()
    payload.pop(field)
    with pytest.raises(ValueError, match="schema"):
        ReferenceBank.from_payload(payload)


@pytest.mark.parametrize("scope", ["bank", "source", "capture", "row"])
def test_extra_fields_are_rejected_even_if_rehashed(scope):
    payload = bank().snapshot()
    target = {
        "bank": payload,
        "source": payload["source"],
        "capture": payload["capture"],
        "row": payload["rows"][0],
    }[scope]
    target["unused"] = "silently ignored metadata is forbidden"
    rehash(payload)
    with pytest.raises(ValueError, match="schema"):
        ReferenceBank.from_payload(payload)


@pytest.mark.parametrize(
    ("scope", "field", "value"),
    [
        ("bank", "schema", "future-v2"),
        ("bank", "role", "preservation_enabled"),
        ("bank", "split", "test"),
        ("bank", "vocab_size", True),
        ("bank", "vocab_size", 1),
        ("bank", "vocab_size", 5),
        ("bank", "max_prefix_tokens", True),
        ("bank", "max_prefix_tokens", 0),
        ("bank", "max_prefix_tokens", 1),
        ("bank", "split_manifest_sha256", "unverified"),
        ("source", "model_repo", "unqualified-model"),
        ("source", "model_revision", "main"),
        ("source", "model_revision", "G" * 40),
        ("source", "model_content_sha256", "A" * 64),
        ("source", "tokenizer_sha256", "b" * 63),
        ("source", "execution_policy_sha256", ""),
        ("capture", "native_dtype", "int64"),
        ("capture", "native_dtype", "torch.float32"),
        ("capture", "provenance", "verified_original"),
        ("capture", "origin", "current_updated_model"),
        ("capture", "position", "first_prompt_position"),
        ("capture", "projection", "two_choice"),
        ("capture", "storage_dtype", "float16_lossy"),
        ("row", "row_id", ""),
        ("row", "family_id", "evaluation\nfamily"),
        ("row", "family_sha256", "g" * 64),
        ("row", "source_sha256", "e" * 40),
        ("row", "prompt_token_ids", []),
        ("row", "prompt_token_ids", [True, 1]),
        ("row", "prompt_token_ids", [-1, 1]),
        ("row", "prompt_token_ids", [4, 1]),
        ("row", "logits", [[0.0, -0.5, 0.25, 1.0]]),
        ("row", "logits", [0.0, -0.5, 0.25]),
        ("row", "logits", [False, -0.5, 0.25, 1.0]),
        ("row", "logits", [0, -0.5, 0.25, 1.0]),
        ("row", "logits", [0.1, -0.5, 0.25, 1.0]),
    ],
)
def test_invalid_payload_rejected_even_if_rehashed(scope, field, value):
    payload = bank().snapshot()
    target = {
        "bank": payload,
        "source": payload["source"],
        "capture": payload["capture"],
        "row": payload["rows"][0],
    }[scope]
    target[field] = value
    rehash(payload)
    with pytest.raises(ValueError):
        ReferenceBank.from_payload(payload)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_values_are_rejected_before_hashing(value):
    payload = bank().snapshot()
    payload["rows"][0]["logits"][0] = value
    with pytest.raises(ValueError, match="finite"):
        ReferenceBank.from_payload(payload)


@pytest.mark.parametrize(
    ("dtype", "value"),
    [
        ("float16", 65536.0),
        ("float16", 1.00001),
        ("bfloat16", 1.00390625),
        ("float32", 1e300),
        ("float32", 1.00000000001),
    ],
)
def test_native_dtype_provenance_rejects_nonrepresentable_values(dtype, value):
    with pytest.raises(ValueError):
        ReferenceBank(
            source(), CapturePolicy(dtype), 4, 8, "0" * 64, (row(logits=(value, -0.5, 0.25, 1.0)),)
        )


def test_preserves_signed_zero_and_changes_identity():
    positive = bank()
    negative = ReferenceBank(
        source(), CapturePolicy("float32"), 4, 8, "0" * 64, (row(logits=(-0.0, -0.5, 0.25, 1.0)),)
    )
    assert positive.content_sha256 != negative.content_sha256
    restored = ReferenceBank.from_json(negative.to_json())
    assert math.copysign(1, restored.rows[0].logits[0]) == -1


@pytest.mark.parametrize("case", ["row_id", "prefix", "family_hash", "family_id"])
def test_duplicate_or_inconsistent_rows_fail(case):
    first = row()
    second = row("row-2", (1, 2))
    if case == "row_id":
        second = second._replace(row_id=first.row_id)
    elif case == "prefix":
        second = second._replace(prompt_token_ids=first.prompt_token_ids)
    elif case == "family_hash":
        second = second._replace(family_sha256="9" * 64)
    else:
        second = second._replace(family_id="alias-for-same-family")
    with pytest.raises(ValueError):
        ReferenceBank(source(), CapturePolicy("float32"), 4, 8, "0" * 64, (first, second))


def test_row_order_and_every_identity_are_bound_to_content():
    first, second = row(), row("row-2", (1, 2))
    original = ReferenceBank(source(), CapturePolicy("float32"), 4, 8, "0" * 64, (first, second))
    reversed_bank = ReferenceBank(
        source(), CapturePolicy("float32"), 4, 8, "0" * 64, (second, first)
    )
    assert original.content_sha256 != reversed_bank.content_sha256
    payload = original.snapshot()
    payload["source"]["execution_policy_sha256"] = "9" * 64
    with pytest.raises(ValueError, match="hash mismatch"):
        ReferenceBank.from_payload(payload)
    rehash(payload)
    changed = ReferenceBank.from_payload(payload)
    assert changed.content_sha256 != original.content_sha256
    assert changed.descriptor() != original.descriptor()


@pytest.mark.parametrize("case", ["rows", "prefix", "logits", "source", "policy"])
def test_mutable_or_unknown_canonical_records_are_rejected(case):
    original = bank()
    fields = dict(original._asdict())
    if case == "rows":
        fields["rows"] = list(fields["rows"])
    elif case in ("prefix", "logits"):
        key = "prompt_token_ids" if case == "prefix" else "logits"
        row_fields = dict(row()._asdict())
        row_fields[key] = list(row_fields[key])
        fields["rows"] = (tuple.__new__(ReferenceRow, tuple(row_fields.values())),)
    elif case == "source":
        fields["source"] = tuple(source())
    else:
        fields["capture"] = ("float32", "synthetic_ownership_fixture")
    with pytest.raises(ValueError):
        ReferenceBank(**fields)


def test_bypassed_namedtuple_constructors_are_revalidated_before_export():
    original = bank()
    fields = dict(original._asdict())
    fields["vocab_size"] = True
    invalid = tuple.__new__(ReferenceBank, tuple(fields.values()))
    for operation in (
        invalid.validate,
        invalid.snapshot,
        invalid.to_json,
        invalid.descriptor,
        invalid.descriptor_payload,
        lambda: invalid.tensor("row-1"),
    ):
        with pytest.raises(ValueError):
            operation()
    fields = dict(original.source._asdict())
    fields["model_revision"] = "main"
    invalid_source = tuple.__new__(ReferenceSource, tuple(fields.values()))
    with pytest.raises(ValueError):
        original._replace(source=invalid_source).snapshot()


@pytest.mark.parametrize("case", ["bank", "source", "capture", "row"])
def test_standard_tuple_copy_helpers_cannot_bypass_validation(case):
    original = bank()
    obj, field, bad = {
        "bank": (original, "rows", list(original.rows)),
        "source": (original.source, "model_revision", "main"),
        "capture": (original.capture, "native_dtype", "int32"),
        "row": (original.rows[0], "logits", list(original.rows[0].logits)),
    }[case]
    assert type(obj)._make(tuple(obj)) == obj
    assert obj._replace() == obj
    with pytest.raises(ValueError):
        obj._replace(**{field: bad})
    fields = dict(obj._asdict())
    fields[field] = bad
    with pytest.raises(ValueError):
        type(obj)._make(tuple(fields.values()))
    with pytest.raises(ValueError):
        obj._replace(unowned="ignored")


def test_json_duplicate_keys_and_non_json_shapes_are_rejected():
    with pytest.raises(ValueError, match="Duplicate JSON"):
        ReferenceBank.from_json('{"schema":"first","schema":"second"}')
    with pytest.raises(ValueError):
        ReferenceBank.from_json("not JSON")
    with pytest.raises(ValueError):
        ReferenceBank.from_json("[]")
    payload = bank().snapshot()
    payload["rows"] = tuple(payload["rows"])
    with pytest.raises(ValueError, match="JSON array"):
        ReferenceBank.from_payload(payload)


def test_attested_capture_remains_a_declaration_not_a_verified_original_claim():
    original = ReferenceBank(
        source(),
        CapturePolicy("float32", "declared_original_native_capture"),
        4,
        8,
        "0" * 64,
        (row(),),
    )
    payload = original.snapshot()
    assert payload["capture"]["provenance"] == "declared_original_native_capture"
    assert payload["role"] == ROLE
    assert "verified" not in payload["capture"]
    assert ReferenceBank.from_payload(payload) == original
