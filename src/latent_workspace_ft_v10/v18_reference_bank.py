"""Immutable, supplied original-reference logits; no capture or preservation loss.

This additive contract owns full-vocabulary last-prompt-position values as
primitive immutable tuples, not tensors or callbacks. It validates declared
provenance but cannot establish that a caller really captured an original model
or that a declared train family is empirically disjoint from evaluation. The
synthetic qualification uses ``synthetic_ownership_fixture`` provenance. Real
capture, independent split verification and any preservation loss remain separate
work. No model execution, filesystem access or RNG operation occurs here.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from collections import namedtuple

SCHEMA = "v18-original-reference-bank-v1"
ROLE = "reference_only_no_preservation_loss"
SPLIT = "train_only"
_DTYPES = ("float16", "bfloat16", "float32", "float64")
_PROVENANCE = ("synthetic_ownership_fixture", "declared_original_native_capture")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value, name):
    _require(
        type(value) is str
        and 0 < len(value) <= 256
        and value.strip() == value
        and not any(ord(char) < 32 or ord(char) == 127 for char in value),
        f"Invalid {name}",
    )


def _sha(value, name):
    _require(
        type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
        f"Invalid {name}: expected lowercase SHA256",
    )


def _positive_integer(value, name, minimum=1):
    _require(type(value) is int and value >= minimum, f"Invalid {name}")


def _mapping(value, keys, name):
    _require(
        type(value) is dict and all(type(key) is str for key in value) and set(value) == set(keys),
        f"Invalid {name} schema",
    )


def _literal(value, expected, message):
    _require(type(value) is str and value == expected, message)


def _array(value, name):
    _require(type(value) is list, f"Invalid {name}: expected JSON array")


def _json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _native_float(value, dtype):
    """Reject a rounded projection falsely labelled as exact native capture."""
    _require(type(value) is float and math.isfinite(value), "Logits must be finite floats")
    if dtype == "float64":
        return
    try:
        packed = struct.pack("!e" if dtype == "float16" else "!f", value)
    except (OverflowError, struct.error) as error:
        raise ValueError("Logit is outside native dtype range") from error
    restored = struct.unpack("!e" if dtype == "float16" else "!f", packed)[0]
    _require(restored == value, "Logit is not exactly representable in native dtype")
    if dtype == "bfloat16":
        _require(int.from_bytes(packed, "big") & 0xFFFF == 0, "Logit is not native BF16")


class _ValidatedTuple:
    """Route the standard namedtuple copy helpers through strict constructors."""

    __slots__ = ()

    @classmethod
    def _make(cls, iterable):
        return cls(*tuple(iterable))

    def _replace(self, **kwargs):
        fields = self._asdict()
        _require(not (set(kwargs) - set(fields)), "Unknown replacement fields")
        fields.update(kwargs)
        return type(self)(**fields)


class ReferenceSource(
    _ValidatedTuple,
    namedtuple(
        "ReferenceSourceTuple",
        "model_repo model_revision model_content_sha256 tokenizer_sha256 execution_policy_sha256",
    ),
):
    """Pinned identity declaration; a revision label such as main is forbidden."""

    __slots__ = ()

    def __new__(
        cls,
        model_repo,
        model_revision,
        model_content_sha256,
        tokenizer_sha256,
        execution_policy_sha256,
    ):
        _text(model_repo, "model repository")
        _require(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", model_repo)
            is not None,
            "Expected an exact owner/model repository",
        )
        _require(
            type(model_revision) is str
            and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", model_revision) is not None,
            "Model revision must be a pinned content revision",
        )
        for name, value in (
            ("model content hash", model_content_sha256),
            ("tokenizer hash", tokenizer_sha256),
            ("execution policy hash", execution_policy_sha256),
        ):
            _sha(value, name)
        return super().__new__(
            cls,
            model_repo,
            model_revision,
            model_content_sha256,
            tokenizer_sha256,
            execution_policy_sha256,
        )


class CapturePolicy(_ValidatedTuple, namedtuple("CapturePolicyTuple", "native_dtype provenance")):
    """Native captured logits are widened losslessly to Python float storage."""

    __slots__ = ()

    def __new__(cls, native_dtype, provenance="synthetic_ownership_fixture"):
        _require(type(native_dtype) is str and native_dtype in _DTYPES, "Invalid native dtype")
        _require(type(provenance) is str and provenance in _PROVENANCE, "Invalid provenance")
        return super().__new__(cls, native_dtype, provenance)


class ReferenceRow(
    _ValidatedTuple,
    namedtuple(
        "ReferenceRowTuple",
        "row_id family_id family_sha256 source_sha256 prompt_token_ids logits",
    ),
):
    """One exact prefix and its full-vocabulary final-position logit vector."""

    __slots__ = ()

    def __new__(cls, row_id, family_id, family_sha256, source_sha256, prompt_token_ids, logits):
        _text(row_id, "row ID")
        _text(family_id, "family ID")
        _sha(family_sha256, "family hash")
        _sha(source_sha256, "row source hash")
        _require(type(prompt_token_ids) is tuple and prompt_token_ids, "Expected a nonempty prefix")
        _require(
            all(type(token) is int and token >= 0 for token in prompt_token_ids),
            "Prefix token IDs must be nonnegative integers",
        )
        _require(type(logits) is tuple and logits, "Expected a nonempty full-vocabulary tuple")
        _require(
            all(type(value) is float and math.isfinite(value) for value in logits),
            "Logits must be finite primitive floats",
        )
        return super().__new__(
            cls,
            row_id,
            family_id,
            family_sha256,
            source_sha256,
            prompt_token_ids,
            logits,
        )


class ReferenceBank(
    _ValidatedTuple,
    namedtuple(
        "ReferenceBankTuple",
        "source capture vocab_size max_prefix_tokens split_manifest_sha256 rows",
    ),
):
    """Immutable supplied-logit owner. Construction and every export validate.

    ``descriptor`` is a recursively primitive tuple suitable for a separate
    learner resume contract. A bank hash binds order, all identities, each exact
    prefix and each full-vocabulary value. It does not confer provenance trust.
    """

    __slots__ = ()

    def __new__(cls, source, capture, vocab_size, max_prefix_tokens, split_manifest_sha256, rows):
        bank = super().__new__(
            cls,
            source,
            capture,
            vocab_size,
            max_prefix_tokens,
            split_manifest_sha256,
            rows,
        )
        bank.validate()
        return bank

    def validate(self):
        _require(type(self) is ReferenceBank, "Unknown bank class")
        _require(type(self.source) is ReferenceSource, "Unknown reference source class")
        _require(type(self.capture) is CapturePolicy, "Unknown capture policy class")
        # Recreate records too: direct low-level tuple construction can bypass
        # a subclass constructor, although standard copy helpers validate.
        ReferenceSource(*self.source)
        CapturePolicy(*self.capture)
        _positive_integer(self.vocab_size, "vocabulary size", minimum=2)
        _positive_integer(self.max_prefix_tokens, "prefix limit")
        _sha(self.split_manifest_sha256, "train-only split manifest hash")
        _require(type(self.rows) is tuple and self.rows, "Expected nonempty immutable rows")
        ids, prefixes, families, family_hashes = set(), set(), {}, {}
        for row in self.rows:
            _require(type(row) is ReferenceRow, "Unknown reference row class")
            ReferenceRow(*row)
            _require(row.row_id not in ids, "Duplicate reference row ID")
            _require(row.prompt_token_ids not in prefixes, "Duplicate reference prefix")
            ids.add(row.row_id)
            prefixes.add(row.prompt_token_ids)
            _require(len(row.prompt_token_ids) <= self.max_prefix_tokens, "Prefix exceeds limit")
            _require(max(row.prompt_token_ids) < self.vocab_size, "Prefix token outside vocabulary")
            _require(len(row.logits) == self.vocab_size, "Expected full-vocabulary logit shape")
            _require(
                families.get(row.family_id, row.family_sha256) == row.family_sha256,
                "Inconsistent family identity hash",
            )
            _require(
                family_hashes.get(row.family_sha256, row.family_id) == row.family_id,
                "One family hash has multiple IDs",
            )
            families[row.family_id] = row.family_sha256
            family_hashes[row.family_sha256] = row.family_id
            for value in row.logits:
                _native_float(value, self.capture.native_dtype)

    def _body(self):
        return {
            "schema": SCHEMA,
            "role": ROLE,
            "split": SPLIT,
            "source": dict(self.source._asdict()),
            "capture": {
                **self.capture._asdict(),
                "origin": "pinned_original_model",
                "position": "last_prompt_position",
                "projection": "full_vocabulary",
                "storage_dtype": "python_float64_lossless_native_values",
            },
            "vocab_size": self.vocab_size,
            "max_prefix_tokens": self.max_prefix_tokens,
            "split_manifest_sha256": self.split_manifest_sha256,
            "rows": [
                {
                    **row._asdict(),
                    "prompt_token_ids": list(row.prompt_token_ids),
                    "logits": list(row.logits),
                }
                for row in self.rows
            ],
        }

    @property
    def content_sha256(self):
        self.validate()
        return hashlib.sha256(_json_bytes(self._body())).hexdigest()

    def snapshot(self):
        """Fresh mutable JSON containers: editing them never edits bank state."""
        self.validate()
        body = self._body()
        return {**body, "content_sha256": hashlib.sha256(_json_bytes(body)).hexdigest()}

    def to_json(self):
        return _json_bytes(self.snapshot()).decode()

    @classmethod
    def from_payload(cls, payload):
        """Strict schema validation, independent ownership and content rehash."""
        _require(cls is ReferenceBank, "Unknown bank class")
        _mapping(
            payload,
            (
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
            ),
            "bank",
        )
        _literal(payload["schema"], SCHEMA, "Unknown bank schema")
        _literal(payload["role"], ROLE, "Bank cannot enable a preservation loss")
        _literal(payload["split"], SPLIT, "Reference bank is train-only")
        _sha(payload["content_sha256"], "content hash")
        _mapping(payload["source"], ReferenceSource._fields, "source")
        _mapping(
            payload["capture"],
            (
                "native_dtype",
                "provenance",
                "origin",
                "position",
                "projection",
                "storage_dtype",
            ),
            "capture",
        )
        capture = payload["capture"]
        _literal(capture["origin"], "pinned_original_model", "Expected original reference")
        _literal(capture["position"], "last_prompt_position", "Unknown capture position")
        _literal(capture["projection"], "full_vocabulary", "Restricted projections forbidden")
        _literal(
            capture["storage_dtype"],
            "python_float64_lossless_native_values",
            "Unknown storage representation",
        )
        _array(payload["rows"], "rows")
        rows = []
        for row in payload["rows"]:
            _mapping(row, ReferenceRow._fields, "row")
            _array(row["prompt_token_ids"], "prefix")
            _array(row["logits"], "logits")
            rows.append(
                ReferenceRow(
                    row["row_id"],
                    row["family_id"],
                    row["family_sha256"],
                    row["source_sha256"],
                    tuple(row["prompt_token_ids"]),
                    tuple(row["logits"]),
                )
            )
        bank = cls(
            ReferenceSource(**payload["source"]),
            CapturePolicy(capture["native_dtype"], capture["provenance"]),
            payload["vocab_size"],
            payload["max_prefix_tokens"],
            payload["split_manifest_sha256"],
            tuple(rows),
        )
        _require(
            bank.content_sha256 == payload["content_sha256"], "Reference content hash mismatch"
        )
        return bank

    @classmethod
    def from_json(cls, serialized):
        _require(type(serialized) is str, "Expected a JSON string")

        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                _require(key not in result, "Duplicate JSON object field")
                result[key] = value
            return result

        try:
            payload = json.loads(serialized, object_pairs_hook=unique_object)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("Invalid reference bank JSON") from error
        return cls.from_payload(payload)

    def descriptor(self):
        """Pure immutable resume-binding data; contains no live tensor aliases."""
        self.validate()
        return (
            ("schema", SCHEMA),
            ("role", ROLE),
            ("split", SPLIT),
            ("content_sha256", self.content_sha256),
            ("source", tuple(zip(self.source._fields, tuple(self.source), strict=True))),
            ("capture", tuple(zip(self.capture._fields, tuple(self.capture), strict=True))),
            ("vocab_size", self.vocab_size),
            ("max_prefix_tokens", self.max_prefix_tokens),
            ("split_manifest_sha256", self.split_manifest_sha256),
            ("row_ids", tuple(row.row_id for row in self.rows)),
            ("families", tuple(sorted({(row.family_id, row.family_sha256) for row in self.rows}))),
            ("source_hashes", tuple(sorted({row.source_sha256 for row in self.rows}))),
        )

    def descriptor_payload(self):
        """Fresh JSON-compatible binding metadata for an outer run contract."""
        descriptor = dict(self.descriptor())
        descriptor["source"] = dict(descriptor["source"])
        descriptor["capture"] = dict(descriptor["capture"])
        descriptor["row_ids"] = list(descriptor["row_ids"])
        descriptor["families"] = [list(item) for item in descriptor["families"]]
        descriptor["source_hashes"] = list(descriptor["source_hashes"])
        return descriptor

    @property
    def capture_policy(self):
        return self.capture

    def tensor(self, row_id):
        """Fresh CPU tensor only; caller owns its storage and cannot edit bank."""
        self.validate()
        _text(row_id, "requested row ID")
        matches = [row for row in self.rows if row.row_id == row_id]
        _require(len(matches) == 1, "Unknown reference row ID")
        import torch

        return torch.tensor(
            matches[0].logits,
            dtype=getattr(torch, self.capture.native_dtype),
            device="cpu",
            requires_grad=False,
        )
