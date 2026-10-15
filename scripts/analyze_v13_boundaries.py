#!/usr/bin/env python3
"""Analyze exactly twelve retained S1 tensor payloads on CPU, without a model.

Two branches, two world-pair records, three modes. Payload bytes are checked
against their COMPLETE VISIBILITY_TRACE receipts before torch.load. No base
checkpoint is opened and no inference, training, or GPU operation is executed.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import torch

FORMAT = "latent-workspace-v13-cpu-boundary-summary-v1"
TRACE_FORMAT = "latent-workspace-v13-retained-inline-visibility-v1"
BRANCHES = ("task_seed43_step16", "semantic_seed43_step16")
WORLDS = ("world_0000", "world_0001")
MODES = ("intact", "counterfactual_twin", "hard_bypass")
MAX_PAYLOAD_BYTES = 256 * 1024 * 1024
BOUNDARIES = (
    "writer.raw_memory",
    "reader.memory_input",
    "reader.actual_learned_memory_norm",
    "reader.actual_sdpa_k",
    "reader.actual_sdpa_v",
    "reader.actual_read.answer",
    "reader.gated_update_replayed.answer",
    "adapter.actual_recovered_delta.answer",
    "adapter.actual_learned_norm.answer",
    "adapter.candidates_precast",
    "wrapper.actual_candidates",
)
EXTRA_TENSORS = ("reader.query_input.answer", "reader.actual_return.answer")


class BoundaryError(RuntimeError):
    """Missing, changed, unbounded, or incompatible diagnostic evidence."""


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finite_tensor(value: Any, name: str) -> torch.Tensor:
    if not isinstance(value, torch.Tensor) or value.device.type != "cpu" or not value.numel():
        raise BoundaryError(f"{name}: expected a nonempty CPU tensor.")
    if not bool(torch.isfinite(value).all()):
        raise BoundaryError(f"{name}: non-finite values.")
    return value


def boundary_stats(before: torch.Tensor, after: torch.Tensor) -> dict[str, Any]:
    """Float64 comparison of already-quantized saved values, not new inference."""
    finite_tensor(before, "before")
    finite_tensor(after, "after")
    if before.shape != after.shape or before.dtype != after.dtype or before.ndim < 2:
        raise BoundaryError("Boundary comparison requires matched shapes/dtypes and row axis.")
    left = before.double().reshape(len(before), -1)
    right = after.double().reshape(len(after), -1)
    difference = right - left
    denominator = float(left.norm())
    return {
        "shape": list(before.shape),
        "captured_dtype": str(before.dtype),
        "rows": len(before),
        "changed_rows": int(difference.ne(0).any(1).sum()),
        "changed_elements": int(difference.ne(0).sum()),
        "elements": before.numel(),
        "changed_element_fraction": int(difference.ne(0).sum()) / before.numel(),
        "relative_l2": float(difference.norm()) / denominator if denominator else None,
        "relative_l2_defined": bool(denominator),
        "mean_row_l2_before": float(left.norm(dim=1).mean()),
        "mean_row_l2_after": float(right.norm(dim=1).mean()),
        "mean_row_l2_difference": float(difference.norm(dim=1).mean()),
        "max_abs_difference": float(difference.abs().max()),
    }


def roundtrip_summary(
    update: torch.Tensor,
    recovered: torch.Tensor,
    query: torch.Tensor,
    actual_return: torch.Tensor,
) -> dict[str, Any]:
    report = boundary_stats(update, recovered)
    for name, tensor in (("query", query), ("actual_return", actual_return)):
        finite_tensor(tensor, name)
        if tensor.shape != update.shape or tensor.dtype != update.dtype:
            raise BoundaryError("Reader roundtrip tensors must match exactly in shape and dtype.")
    u = update.double().reshape(len(update), -1)
    d = recovered.double().reshape(len(recovered), -1)
    q = query.double().reshape(len(query), -1)
    nonzero = update.ne(0)
    erased = nonzero & recovered.eq(0)
    cosine_eligible = u.norm(dim=1).gt(0) & d.norm(dim=1).gt(0)
    cosine = torch.nn.functional.cosine_similarity(u[cosine_eligible], d[cosine_eligible], dim=1)
    report.update(
        update_zero_fraction=int(update.eq(0).sum()) / update.numel(),
        delta_zero_fraction=int(recovered.eq(0).sum()) / recovered.numel(),
        erased_nonzero_elements=int(erased.sum()),
        erased_nonzero_fraction_all=int(erased.sum()) / update.numel(),
        erased_fraction_among_nonzero=(int(erased.sum()) / int(nonzero.sum()))
        if bool(nonzero.any())
        else None,
        fully_erased_query_rows=int((u.norm(dim=1).gt(0) & d.norm(dim=1).eq(0)).sum()),
        query_norm_mean=float(q.norm(dim=1).mean()),
        actual_return_minus_query_numeric_exact=bool(torch.equal(actual_return - query, recovered)),
        raw_update_to_query_relative_l2=float(u.norm() / q.norm()) if bool(q.norm()) else None,
        mean_cosine=float(cosine.mean()) if cosine.numel() else None,
        cosine_eligible_rows=int(cosine_eligible.sum()),
    )
    return report


def checked_payload(path: Path, expected_sha256: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise BoundaryError(f"Expected regular payload file: {path}")
    if not 0 < path.stat().st_size <= MAX_PAYLOAD_BYTES:
        raise BoundaryError(f"Payload outside fixed size bound: {path}")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise BoundaryError(f"Payload SHA-256 mismatch before deserialization: {path}")
    loaded = torch.load(io.BytesIO(raw), weights_only=True, map_location="cpu")
    if not isinstance(loaded, dict) or not isinstance(loaded.get("tensors"), dict):
        raise BoundaryError(f"Unexpected payload structure: {path}")
    selected = {
        key: finite_tensor(value, key)
        for key, value in loaded["tensors"].items()
        if key in (*BOUNDARIES, *EXTRA_TENSORS)
    }
    return {
        "tensors": selected,
        "direct_base": finite_tensor(loaded.get("direct_base"), "direct_base"),
    }


def load_branch(run_root: Path, branch: str) -> tuple[dict[str, Any], dict[str, Any]]:
    branch_root = run_root / branch
    receipt_path = branch_root / "VISIBILITY_TRACE.json"
    raw_receipt = receipt_path.read_bytes()
    receipt = json.loads(raw_receipt)
    expected_receipt_hash = receipt.get("receipt_sha256")
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if not expected_receipt_hash or canonical_hash(unsigned) != expected_receipt_hash:
        raise BoundaryError(f"Visibility receipt checksum mismatch: {branch}")
    if (
        receipt.get("format") != TRACE_FORMAT
        or receipt.get("status") != "COMPLETE"
        or receipt.get("checkpoint_bytes_unchanged") is not True
        or receipt.get("parameters_unmodified") is not True
        or receipt.get("max_worlds") != 2
        or receipt.get("training_performed") is not False
    ):
        raise BoundaryError(f"Unqualified source visibility receipt: {branch}")
    entries = receipt.get("worlds", [])
    if len(entries) != 2 or [entry.get("sample_index") for entry in entries] != [0, 1]:
        raise BoundaryError("Expected exactly first two complete paired-world records.")
    data: dict[str, Any] = {}
    provenance: dict[str, Any] = {
        "visibility_receipt_path": str(receipt_path),
        "visibility_receipt_file_sha256": hashlib.sha256(raw_receipt).hexdigest(),
        "visibility_receipt_internal_sha256": expected_receipt_hash,
        "checkpoint_inventory_sha256": receipt.get("checkpoint_inventory_sha256"),
        "engine_source_sha256": receipt.get("engine_source_sha256"),
        "trace_source_sha256": receipt.get("trace_source_sha256"),
        "payloads": [],
        "case_ids": [],
    }
    for world, entry in zip(WORLDS, entries, strict=True):
        data[world] = {}
        for mode in MODES:
            mode_entry = entry.get("modes", {}).get(mode, {})
            relative = f"{world}/{mode}.pt"
            if mode_entry.get("tensor_path") != relative:
                raise BoundaryError("Receipt does not bind the exact requested world/mode payload.")
            path = branch_root / relative
            if not path.resolve().is_relative_to(branch_root.resolve()):
                raise BoundaryError("Payload escapes retained diagnostic branch.")
            expected = mode_entry.get("tensor_file_sha256")
            if not isinstance(expected, str):
                raise BoundaryError("Missing payload hash in visibility receipt.")
            loaded = checked_payload(path, expected)
            needed = (
                BOUNDARIES
                if mode != "hard_bypass"
                else (
                    "adapter.actual_recovered_delta.answer",
                    "adapter.actual_learned_norm.answer",
                    "adapter.candidates_precast",
                    "wrapper.actual_candidates",
                )
            )
            if any(key not in loaded["tensors"] for key in needed):
                raise BoundaryError(f"Required captured boundary missing: {branch}/{relative}")
            row_count = len(loaded["tensors"]["wrapper.actual_candidates"])
            if not 1 <= row_count <= 16 or row_count % 2:
                raise BoundaryError("Expected at most sixteen paired query rows per world record.")
            matching_rows = [
                row
                for row in receipt.get("rows", [])
                if row.get("mode") == mode and row.get("sample_index") == entry["sample_index"]
            ]
            if len(matching_rows) != row_count:
                raise BoundaryError("Tensor row count differs from per-case visibility records.")
            data[world][mode] = loaded
            provenance["payloads"].append(
                {"path": str(path), "sha256": expected, "bytes": path.stat().st_size}
            )
            if mode == "intact":
                provenance["case_ids"].extend(row["case_id"] for row in matching_rows)
    if len(provenance["case_ids"]) != len(set(provenance["case_ids"])):
        raise BoundaryError("Duplicate case identity in paired-world diagnostic slice.")
    return data, provenance


def summarize_branch(data: dict[str, Any]) -> dict[str, Any]:
    def concat(mode: str, key: str) -> torch.Tensor:
        return torch.cat([data[world][mode]["tensors"][key] for world in WORLDS], dim=0)

    result: dict[str, Any] = {"roundtrip": {}, "twin_minus_intact": {}}
    for mode in ("intact", "counterfactual_twin"):
        result["roundtrip"][mode] = roundtrip_summary(
            concat(mode, "reader.gated_update_replayed.answer"),
            concat(mode, "adapter.actual_recovered_delta.answer"),
            concat(mode, "reader.query_input.answer"),
            concat(mode, "reader.actual_return.answer"),
        )
    for key in BOUNDARIES:
        result["twin_minus_intact"][key] = boundary_stats(
            concat("intact", key), concat("counterfactual_twin", key)
        )
    delta = concat("hard_bypass", "adapter.actual_recovered_delta.answer")
    residual = concat("hard_bypass", "adapter.candidates_precast")
    norm = concat("hard_bypass", "adapter.actual_learned_norm.answer")
    native = concat("hard_bypass", "wrapper.actual_candidates")
    direct = torch.cat([data[world]["hard_bypass"]["direct_base"] for world in WORLDS])
    result["legacy_hard_bypass"] = {
        "delta_all_zero": bool(delta.eq(0).all()),
        "adapter_norm_nonzero_rows": int(norm.ne(0).any(1).sum()),
        "candidate_residual_nonzero_rows": int(residual.ne(0).any(1).sum()),
        "candidate_residual_max": float(residual.double().abs().max()),
        "native_equals_direct_numeric": bool(torch.equal(native, direct)),
    }
    result["twin_memory_expected_side_swap_numeric_exact"] = []
    for world in WORLDS:
        intact = data[world]["intact"]["tensors"]["reader.memory_input"]
        twin = data[world]["counterfactual_twin"]["tensors"]["reader.memory_input"]
        expected = torch.cat([intact[len(intact) // 2 :], intact[: len(intact) // 2]])
        result["twin_memory_expected_side_swap_numeric_exact"].append(
            bool(torch.equal(twin, expected))
        )
    return result


def analyze(run_root: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "format": FORMAT,
        "status": "COMPLETE",
        "run_root": str(run_root),
        "analysis_source_sha256": sha256_file(Path(__file__)),
        "analyzed_at": datetime.now(UTC).isoformat(),
        "torch_version": torch.__version__,
        "device": "cpu",
        "torch_threads": torch.get_num_threads(),
        "torch_interop_threads": torch.get_num_interop_threads(),
        "comparison_dtype": "float64 after exact widening of saved BF16/FP32 values",
        "model_loaded": False,
        "training_performed": False,
        "payload_file_count": 12,
        "max_payload_bytes_each": MAX_PAYLOAD_BYTES,
        "max_answer_rows_each_branch": 32,
        "formulas": {
            "relative_l2": (
                "norm(after-before) / norm(before), flattened over all rows/features; "
                "null when denominator is zero"
            ),
            "mean_row_l2_difference": "mean_rows(norm(after[row]-before[row]))",
            "erased_fraction_among_nonzero": (
                "count(update != 0 and recovered == 0) / count(update != 0)"
            ),
            "roundtrip": (
                "before=replayed gated update; after=actual adapter input from (q+update)-q"
            ),
            "twin_minus_intact": (
                "before=intact; after=counterfactual_twin at identical captured boundary"
            ),
            "numeric_exact": (
                "torch.equal in captured dtype; signed-zero bit distinctions not tested"
            ),
        },
        "caveats": [
            "This compares saved values, not a new FP64/FP32 model forward.",
            "Relative L2 contrasts across representations are not representation-quality scores.",
            "32 query rows, when present, derive from only two paired-world families per branch.",
            "Memory/KV rows repeat world-side memory across queries; not independent samples.",
            "writer.raw_memory is pre-intervention and should not differ across control modes.",
            "Legacy hard_bypass still evaluates adapter(0); it is not true route amputation.",
            "No general semantic failure, necessity, V14 bridge, or recurrence claim follows.",
        ],
        "branches": {},
    }
    for branch in BRANCHES:
        data, provenance = load_branch(run_root, branch)
        report["branches"][branch] = {"provenance": provenance, **summarize_branch(data)}
        del data
    identities = [report["branches"][branch]["provenance"]["case_ids"] for branch in BRANCHES]
    if identities[0] != identities[1]:
        raise BoundaryError("Task/semantic diagnostic case identities differ.")
    report["report_sha256"] = canonical_hash(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists():
        raise BoundaryError("Refusing to overwrite an existing analysis artifact.")
    torch.set_num_threads(2)
    torch.set_num_interop_threads(2)
    report = analyze(args.run_root.expanduser().resolve())
    if sha256_file(Path(__file__)) != report["analysis_source_sha256"]:
        raise BoundaryError("Analysis source changed during execution.")
    serialized = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        handle.write(serialized)
    compact = {"status": "COMPLETE", "output": str(output), "branches": {}}
    for branch in BRANCHES:
        item = report["branches"][branch]
        compact["branches"][branch] = {
            "roundtrip_intact_relative_l2": item["roundtrip"]["intact"]["relative_l2"],
            "roundtrip_intact_erased_fraction": item["roundtrip"]["intact"][
                "erased_fraction_among_nonzero"
            ],
            "twin_candidate_precast_changed_rows": item["twin_minus_intact"][
                "adapter.candidates_precast"
            ]["changed_rows"],
            "twin_native_candidate_changed_rows": item["twin_minus_intact"][
                "wrapper.actual_candidates"
            ]["changed_rows"],
        }
    print(json.dumps(compact, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
