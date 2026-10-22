"""Bind frozen preservation-target metadata to complete causal training rows.

Preparation only: this module does not load tensors, evaluate a model, change
the native owner's objective, or authorize training. The caller must obtain
the expected receipt digest from its frozen plan, not from untrusted metadata.
Target-file integrity, tensor normalization and execution-source replay remain
separate mandatory checks before a future owner may consume any target.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .execution import plan_hash, require

SCHEMA = "ltws-preservation-target-binding-v1"
_RECEIPT_KEYS = {
    "bytes",
    "input_sha256",
    "native_sha256",
    "rows",
    "sha256",
    "source_commit",
    "target_dtype",
    "teacher_policy",
    "temperature",
    "tensor_bytes",
    "vocabulary",
}
_ROW_KEYS = {"index", "key", "row_sha256", "shape", "supervised_tokens"}


def _digest(value, length=64):
    require(
        isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{length}}}", value),
        "Expected lowercase content digest",
    )


def _positive_int(value):
    require(type(value) is int and value > 0, "Positive integer required")


def _positions(row, vocabulary):
    require(isinstance(row, dict), "Complete row object required")
    required = {
        "key",
        "split",
        "language",
        "memory_ids",
        "input_ids",
        "labels",
        "supervised_tokens",
    }
    require(required <= row.keys(), "Missing complete-row fields")
    require(isinstance(row["key"], str) and row["key"], "Nonempty row key")
    require(row["split"] == "train" and row["language"] == "en", "English train-only targets")
    require(type(row["memory_ids"]) is list and row["memory_ids"] == [], "No-memory targets")
    require(row.get("memory_mask", []) == [], "No memory mask for empty memory")
    ids, labels = row["input_ids"], row["labels"]
    require(type(ids) is list and len(ids) >= 2, "Complete untruncated query")
    require(all(type(t) is int and 0 <= t < vocabulary for t in ids), "Token outside vocabulary")
    require(type(labels) is list and len(labels) == len(ids), "Causal label extent")
    require(all(type(t) is int for t in labels), "Integer causal labels")
    require(labels[0] == -100, "First token cannot have a causal target")
    require(all(y == -100 or y == x for x, y in zip(ids, labels)), "Target/input token mismatch")
    if "attention_mask" in row:
        mask = row["attention_mask"]
        require(
            type(mask) is list
            and len(mask) == len(ids)
            and all(type(v) is int and v == 1 for v in mask),
            "This target contract has no padded/cropped query positions",
        )
    positions = tuple(j - 1 for j, label in enumerate(labels) if label != -100)
    _positive_int(row["supervised_tokens"])
    require(len(positions) == row["supervised_tokens"], "Supervised target count mismatch")
    return positions


@dataclass(frozen=True)
class PreservationRowBinding:
    key: str
    row_sha256: str
    tensor_key: str
    query_tokens: int
    supervised_tokens: int
    causal_logit_positions: tuple[int, ...]
    shape: tuple[int, int]


@dataclass(frozen=True)
class PreservationBinding:
    """Immutable metadata, deliberately not proof that a target body was read."""

    receipt_plan_sha256: str
    source_commit: str
    native_sha256: str
    input_sha256: str
    target_file_sha256: str
    target_file_bytes: int
    tensor_bytes: int
    vocabulary: int
    teacher_policy: str
    rows: tuple[PreservationRowBinding, ...]

    def require_row(self, row):
        """Reject mutated inputs before the future owner constructs its batch."""
        positions = _positions(row, self.vocabulary)
        matches = [r for r in self.rows if r.key == row["key"]]
        require(len(matches) == 1, "Row absent from frozen target binding")
        bound = matches[0]
        require(plan_hash(row) == bound.row_sha256, "Complete row content changed")
        require(positions == bound.causal_logit_positions, "Causal target positions changed")
        return bound

    def manifest(self):
        """A detached JSON-compatible descriptor containing no input token arrays."""
        result = asdict(self)
        result["rows"] = [
            {
                **asdict(row),
                "causal_logit_positions": list(row.causal_logit_positions),
                "shape": list(row.shape),
            }
            for row in self.rows
        ]
        return dict(
            schema=SCHEMA,
            receipt_digest_scheme="canonical_json_plan_hash_v1",
            target_dtype="float32",
            temperature=1.0,
            direction="teacher_to_student",
            target_body_validation="NOT_PERFORMED_METADATA_ONLY",
            owner_integration="NOT_IMPLEMENTED",
            **result,
        )


def bind_preservation_targets(receipt, rows, *, expected_receipt_plan_sha256):
    """Verify a pinned audit-format receipt and bind ALL of its ordered rows.

    Each stored tensor is [supervised positions, full vocabulary], using
    logits[j - 1] for label[j]. Complete row hashes include prompt, continuation,
    labels, memory, split, language and any source metadata. No selected-prefix,
    top-k, missing-row, reordered-row or silent truncation fallback is allowed.
    The expected digest is execution.plan_hash(receipt), NOT the raw JSON file
    hash. The raw target body uses its separately recorded byte SHA256.
    This accepts the existing teacher *metadata format*, not its scientific
    adequacy as the target bank for a future full-FT recipe.
    """
    _digest(expected_receipt_plan_sha256)
    require(type(receipt) is dict and set(receipt) == _RECEIPT_KEYS, "Target receipt schema")
    require(plan_hash(receipt) == expected_receipt_plan_sha256, "Pinned target receipt mismatch")
    for key in ("native_sha256", "input_sha256", "sha256"):
        _digest(receipt[key])
    _digest(receipt["source_commit"], 40)
    _positive_int(receipt["vocabulary"])
    require(receipt["vocabulary"] >= 2, "Full vocabulary required")
    require(receipt["target_dtype"] == "float32", "Uncompressed FP32 targets required")
    require(
        type(receipt["temperature"]) in (int, float) and receipt["temperature"] == 1,
        "Fixed temperature one required",
    )
    require(
        isinstance(receipt["teacher_policy"], str) and receipt["teacher_policy"].strip(),
        "Pinned teacher execution policy required",
    )
    require(type(rows) in (list, tuple) and rows, "Complete ordered training rows required")
    index = receipt["rows"]
    require(type(index) is list and len(index) == len(rows), "Exact target row coverage")
    bindings, keys = [], set()
    for i, (target, row) in enumerate(zip(index, rows, strict=True)):
        require(type(target) is dict and set(target) == _ROW_KEYS, "Target row schema")
        positions = _positions(row, receipt["vocabulary"])
        require(row["key"] not in keys, "Duplicate training row key")
        keys.add(row["key"])
        require(target["index"] == str(i), "Contiguous canonical tensor index")
        require(target["key"] == row["key"], "Frozen target row order/key mismatch")
        _digest(target["row_sha256"])
        require(target["row_sha256"] == plan_hash(row), "Complete row content mismatch")
        _positive_int(target["supervised_tokens"])
        shape = target["shape"]
        require(
            type(shape) is list
            and len(shape) == 2
            and all(type(n) is int for n in shape)
            and shape == [len(positions), receipt["vocabulary"]]
            and target["supervised_tokens"] == len(positions),
            "Full-vocabulary causal target shape/count",
        )
        bindings.append(
            PreservationRowBinding(
                key=row["key"],
                row_sha256=target["row_sha256"],
                tensor_key=target["index"],
                query_tokens=len(row["input_ids"]),
                supervised_tokens=len(positions),
                causal_logit_positions=positions,
                shape=tuple(shape),
            )
        )
    _positive_int(receipt["tensor_bytes"])
    _positive_int(receipt["bytes"])
    tensor_bytes = sum(r.supervised_tokens for r in bindings) * receipt["vocabulary"] * 4
    require(receipt["tensor_bytes"] == tensor_bytes, "FP32 target payload byte census")
    require(receipt["bytes"] > tensor_bytes, "Target file must also contain its tensor header")
    return PreservationBinding(
        receipt_plan_sha256=expected_receipt_plan_sha256,
        source_commit=receipt["source_commit"],
        native_sha256=receipt["native_sha256"],
        input_sha256=receipt["input_sha256"],
        target_file_sha256=receipt["sha256"],
        target_file_bytes=receipt["bytes"],
        tensor_bytes=tensor_bytes,
        vocabulary=receipt["vocabulary"],
        teacher_policy=receipt["teacher_policy"],
        rows=tuple(bindings),
    )
