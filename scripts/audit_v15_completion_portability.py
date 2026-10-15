#!/usr/bin/env python3
"""Describe exact completion-summary replay differences; never qualify a run.

This diagnostic does not change the sealed verifier, replace its failure with a
tolerance pass, edit raw artifacts, or reproduce the remote validation locally.
"""

from __future__ import annotations

import argparse
import math
import platform
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts"), str(REPO / "src")]
from v15_completion_mass import summarize  # noqa: E402
from verify_ft_beta_query_pool import digest, load, write_new  # noqa: E402
from verify_v15_completion_mass import verify_bundle  # noqa: E402


def float64_bits(value):
    if type(value) is not float or not math.isfinite(value):
        raise ValueError("Expected a finite Python float")
    return struct.unpack(">Q", struct.pack(">d", value))[0]


def float64_ulp_distance(left, right):
    """Distance in ordered finite binary64 encodings, with signed zero distinct."""

    def ordered(value):
        bits = float64_bits(value)
        return (~bits & ((1 << 64) - 1)) if bits >> 63 else bits | (1 << 63)

    return abs(ordered(left) - ordered(right))


def compare_exact(expected, observed):
    """List all structural/type/scalar differences, never apply a tolerance."""
    differences = []
    counts = {
        "scalar_pairs": 0,
        "exact_scalar_matches": 0,
        "float64_pairs": 0,
        "exact_float64_matches": 0,
        "non_float_scalar_pairs": 0,
        "exact_non_float_scalar_matches": 0,
    }

    def pointer(path, key):
        return path + "/" + str(key).replace("~", "~0").replace("/", "~1")

    def visit(left, right, path):
        if type(left) is not type(right):
            differences.append(
                {
                    "path": path or "/",
                    "kind": "type_mismatch",
                    "expected_type": type(left).__name__,
                    "observed_type": type(right).__name__,
                    "expected": left,
                    "observed": right,
                }
            )
            return
        if isinstance(left, dict):
            if set(left) != set(right):
                differences.append(
                    {
                        "path": path or "/",
                        "kind": "mapping_keys",
                        "missing_keys": sorted(set(left) - set(right)),
                        "extra_keys": sorted(set(right) - set(left)),
                    }
                )
            for key in sorted(set(left) & set(right)):
                visit(left[key], right[key], pointer(path, key))
            return
        if isinstance(left, list):
            if len(left) != len(right):
                differences.append(
                    {
                        "path": path or "/",
                        "kind": "list_length",
                        "expected": len(left),
                        "observed": len(right),
                    }
                )
            for index, (a, b) in enumerate(zip(left, right)):
                visit(a, b, pointer(path, index))
            return
        if type(left) not in (str, int, float, bool, type(None)):
            raise ValueError(f"Unsupported JSON scalar at {path}: {type(left).__name__}")
        counts["scalar_pairs"] += 1
        if type(left) is float:
            counts["float64_pairs"] += 1
            left_bits, right_bits = float64_bits(left), float64_bits(right)
            equal = left_bits == right_bits
            if equal:
                counts["exact_float64_matches"] += 1
            else:
                differences.append(
                    {
                        "path": path or "/",
                        "kind": "float64_value",
                        "expected": left,
                        "observed": right,
                        "expected_bits_hex": f"{left_bits:016x}",
                        "observed_bits_hex": f"{right_bits:016x}",
                        "observed_minus_expected": right - left,
                        "ulp_distance": float64_ulp_distance(left, right),
                    }
                )
        else:
            counts["non_float_scalar_pairs"] += 1
            equal = left == right
            if equal:
                counts["exact_non_float_scalar_matches"] += 1
            else:
                differences.append(
                    {
                        "path": path or "/",
                        "kind": "scalar_value",
                        "scalar_type": type(left).__name__,
                        "expected": left,
                        "observed": right,
                    }
                )
        if equal:
            counts["exact_scalar_matches"] += 1

    visit(expected, observed, "")
    floating = [d for d in differences if d["kind"] == "float64_value"]
    nonfloating = [d for d in differences if d["kind"] != "float64_value"]
    return {
        "status": "EXACT_REPLAY_MISMATCH" if differences else "EXACT_REPLAY_MATCH",
        "comparison": "exact JSON types/structure and binary64 bits; no tolerance acceptance",
        "counts": {
            **counts,
            "differences": len(differences),
            "float64_differences": len(floating),
            "other_differences": len(nonfloating),
        },
        "structure_types_and_non_float_values_exact": not nonfloating,
        "differences": differences,
    }


def audit_bundle(bundle, remote_validation=None):
    bundle = Path(bundle)
    report = load(bundle / "raw/REPORT.json")
    started = load(bundle / "raw/STARTED.json")
    expected = report["summary"]
    observed = summarize(load(bundle / "raw/SCORES.json"))
    comparison = compare_exact(expected, observed)
    # Retain the sealed verifier's actual result verbatim as a separate receipt.
    # A failure remains FAILED regardless of difference kind or ULP distance.
    try:
        validation = verify_bundle(bundle)
    except ValueError as exc:
        local_verifier = {
            "status": "FAILED",
            "exception_type": type(exc).__name__,
            "message": str(exc),
        }
    else:
        local_verifier = {"status": "RETURNED_RESULT", "returned_status": validation["status"]}
    remote = {"status": "NOT_PROVIDED"}
    if remote_validation is not None:
        path = Path(remote_validation)
        receipt = load(path)
        remote = {
            "status": "SEPARATE_RECORDED_RECEIPT_NOT_REEXECUTED_HERE",
            "path": str(path.resolve()),
            "sha256": digest(path),
            "recorded_status": receipt.get("status"),
            "origin_runtime": started["runtime"],
        }
    libc_name, libc_version = platform.libc_ver()
    return {
        "format": "v15-completion-portability-diagnostic-v1",
        **comparison,
        "diagnostic_only": True,
        "replacement_validation": False,
        "tolerance_acceptance_performed": False,
        "local_strict_verifier": local_verifier,
        "remote_validation": remote,
        "origin": {"runtime": started["runtime"], "source_commit": started["source_commit"]},
        "local": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "system": platform.system(),
            "libc_name": libc_name or "UNKNOWN",
            "libc_version": libc_version or "UNKNOWN",
            "math_library_identity": "UNKNOWN",
        },
        "inputs": {
            "report_sha256": digest(bundle / "raw/REPORT.json"),
            "scores_sha256": digest(bundle / "raw/SCORES.json"),
            "artifact_index_sha256": digest(bundle / "ARTIFACT_INDEX.json"),
        },
        "interpretation": (
            "This lists observed exact replay differences without assigning their cause. "
            "ULP distances describe mismatches; they do not waive the sealed exact-equality gate. "
            "The recorded remote validation is distinct from local strict verification."
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--remote-validation", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_new(args.output, audit_bundle(args.bundle.resolve(), args.remote_validation))
