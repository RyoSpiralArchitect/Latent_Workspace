#!/usr/bin/env python3
"""Deterministically remap the v9 binary choice surface for Mistral.

The source corpus is preserved byte-for-byte except for the single JSON member
value ``[" 0", " 1"]``, which becomes ``[" no", " yes"]`` on every line.
Parsing before and after the lexical replacement makes that narrow mutation a
checked contract rather than an assumption.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

FORMAT = "latent-workspace-functional-choice-remap-v1"
SOURCE_CHOICES = [" 0", " 1"]
TARGET_CHOICES = [" no", " yes"]
SOURCE_FRAGMENT = b'"choices": [" 0", " 1"]'
TARGET_FRAGMENT = b'"choices": [" no", " yes"]'
SPLITS = {"train": 256, "eval": 64}


class ContractError(RuntimeError):
    """Raised when the corpus does not satisfy the immutable v9 contract."""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_record(record: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _validate_record(record: Mapping[str, Any], *, split: str, line: int) -> None:
    where = f"{split} line {line}"
    if record.get("format") != "functional_world_pair_v9":
        raise ContractError(f"{where}: unexpected record format")

    contexts = record.get("contexts")
    queries = record.get("queries")
    answers = record.get("answers")
    affected = record.get("affected")
    heldout = record.get("heldout_queries")
    metadata = record.get("metadata")
    if not isinstance(contexts, list) or len(contexts) != 2:
        raise ContractError(f"{where}: contexts must contain exactly two worlds")
    if not isinstance(queries, list) or len(queries) != 8:
        raise ContractError(f"{where}: queries must contain exactly eight items")
    if (
        not isinstance(answers, list)
        or len(answers) != 2
        or any(not isinstance(row, list) or len(row) != len(queries) for row in answers)
        or any(value not in (0, 1) for row in answers for value in row)
    ):
        raise ContractError(f"{where}: answers must be a 2x8 binary matrix")
    if (
        not isinstance(affected, list)
        or len(affected) != len(queries)
        or sum(value is True for value in affected) != 2
        or any(not isinstance(value, bool) for value in affected)
    ):
        raise ContractError(f"{where}: affected mask must contain exactly two true values")
    if (
        not isinstance(heldout, list)
        or len(heldout) != len(queries)
        or any(not isinstance(value, bool) for value in heldout)
    ):
        raise ContractError(f"{where}: heldout_queries must be an eight-item bool mask")
    expected_heldout = 0 if split == "train" else 4
    if sum(value is True for value in heldout) != expected_heldout:
        raise ContractError(
            f"{where}: expected {expected_heldout} held-out queries for {split}"
        )
    if not isinstance(metadata, dict):
        raise ContractError(f"{where}: metadata must be an object")
    pair_id = metadata.get("pair_id")
    if not isinstance(pair_id, str) or not pair_id:
        raise ContractError(f"{where}: metadata.pair_id must be non-empty")
    if metadata.get("world_pair_id") != pair_id:
        raise ContractError(f"{where}: pair_id and world_pair_id must match")


def transform_split(source: Path, *, split: str) -> tuple[bytes, dict[str, Any]]:
    if split not in SPLITS:
        raise ContractError(f"unknown split: {split}")
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise ContractError(f"cannot read {source}: {exc}") from exc
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError(f"{source}: input is not UTF-8") from exc
    if not raw or not raw.endswith(b"\n") or b"\r" in raw:
        raise ContractError(f"{source}: input must be non-empty LF-terminated JSONL")

    output_lines: list[bytes] = []
    pair_ids: set[str] = set()
    before_semantic = hashlib.sha256()
    after_semantic = hashlib.sha256()
    lexical_replacements = 0

    for line_number, raw_line in enumerate(raw.splitlines(keepends=True), start=1):
        if raw_line == b"\n" or not raw_line.endswith(b"\n"):
            raise ContractError(f"{source}:{line_number}: blank or unterminated line")
        body = raw_line[:-1]
        if body.count(SOURCE_FRAGMENT) != 1 or TARGET_FRAGMENT in body:
            raise ContractError(
                f"{source}:{line_number}: expected one exact v9 choices fragment"
            )
        try:
            before = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ContractError(f"{source}:{line_number}: invalid JSON: {exc}") from exc
        if not isinstance(before, dict) or before.get("choices") != SOURCE_CHOICES:
            raise ContractError(f"{source}:{line_number}: choices contract mismatch")
        _validate_record(before, split=split, line=line_number)

        output_line = body.replace(SOURCE_FRAGMENT, TARGET_FRAGMENT, 1) + b"\n"
        try:
            after = json.loads(output_line)
        except json.JSONDecodeError as exc:  # pragma: no cover - replacement is fixed
            raise ContractError(f"internal replacement emitted invalid JSON: {exc}") from exc
        expected = copy.deepcopy(before)
        expected["choices"] = TARGET_CHOICES
        if after != expected:
            raise ContractError(
                f"{source}:{line_number}: a field other than choices would change"
            )

        pair_id = str(before["metadata"]["pair_id"])
        if pair_id in pair_ids:
            raise ContractError(f"{source}:{line_number}: duplicate pair_id {pair_id}")
        pair_ids.add(pair_id)

        before_without_choices = copy.deepcopy(before)
        after_without_choices = copy.deepcopy(after)
        del before_without_choices["choices"]
        del after_without_choices["choices"]
        before_semantic.update(_canonical_record(before_without_choices))
        after_semantic.update(_canonical_record(after_without_choices))
        output_lines.append(output_line)
        lexical_replacements += 1

    expected_records = SPLITS[split]
    if len(output_lines) != expected_records:
        raise ContractError(
            f"{source}: expected {expected_records} {split} records, got {len(output_lines)}"
        )
    if before_semantic.digest() != after_semantic.digest():
        raise ContractError(f"{source}: semantic digest changed outside choices")

    output = b"".join(output_lines)
    checks = {
        "all_records_have_two_worlds": True,
        "all_records_have_eight_queries": True,
        "all_records_have_two_affected_queries": True,
        "all_pair_ids_unique": len(pair_ids) == expected_records,
        "exact_choice_fragment_replacements": lexical_replacements,
        "expected_record_count": expected_records,
        "record_count": len(output_lines),
        "unchanged_without_choices_sha256": before_semantic.hexdigest(),
    }
    return output, {
        "input_bytes": len(raw),
        "input_sha256": _sha256(raw),
        "output_bytes": len(output),
        "output_sha256": _sha256(output),
        "structural_checks": checks,
    }


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def build_outputs(
    source_dir: Path,
    output_dir: Path,
    *,
    overwrite: bool = False,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    source_dir = source_dir.resolve()
    output_dir = output_dir.resolve()
    repository = (repo_root or _default_root()).resolve()
    try:
        source_dir.relative_to(repository)
        output_dir.relative_to(repository)
    except ValueError as exc:
        raise ContractError("source and output directories must be inside repository root") from exc
    targets = {
        split: output_dir / f"functional_{split}.jsonl" for split in SPLITS
    }
    manifest_path = output_dir / "MANIFEST.json"
    all_targets = [*targets.values(), manifest_path]
    existing = [path for path in all_targets if path.exists()]
    if existing and not overwrite:
        joined = ", ".join(path.name for path in existing)
        raise ContractError(f"refusing to overwrite existing output(s): {joined}")

    transformed: dict[str, bytes] = {}
    file_entries: dict[str, Any] = {}
    for split in SPLITS:
        source = source_dir / f"functional_{split}.jsonl"
        output, details = transform_split(source, split=split)
        transformed[split] = output
        file_entries[split] = {
            "source": source.relative_to(repository).as_posix(),
            "output": targets[split].relative_to(repository).as_posix(),
            **details,
        }

    manifest = {
        "format": FORMAT,
        "files": file_entries,
        "transformation": {
            "changed_field": "choices",
            "source_choices": SOURCE_CHOICES,
            "target_choices": TARGET_CHOICES,
            "all_other_json_values_unchanged": True,
            "byte_preservation": "per-line exact lexical fragment replacement",
        },
    }
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    # All parsing and validation finishes before the first destination mutation.
    output_dir.mkdir(parents=True, exist_ok=True)
    for split in SPLITS:
        _atomic_write(targets[split], transformed[split])
    _atomic_write(manifest_path, manifest_bytes)
    return manifest


def _default_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    root = _default_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=root / "data",
        help="directory containing the canonical copied v9 functional_train/eval.jsonl",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=root / "data" / "v10",
        help="destination for remapped JSONL and MANIFEST.json",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace existing outputs after all inputs pass validation",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        manifest = build_outputs(args.source_dir, args.output_dir, overwrite=args.overwrite)
    except ContractError as exc:
        raise SystemExit(f"choice remap blocked: {exc}") from exc
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
