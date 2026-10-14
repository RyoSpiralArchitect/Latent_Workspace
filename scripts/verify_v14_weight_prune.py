#!/usr/bin/env python3
"""Offline accounting/metadata verifier; never contacts Furnace or deletes files."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def verify(bundle, repo):
    inv_path = bundle / "INVENTORY.json"
    inv = json.loads(inv_path.read_bytes())
    require(inv["target_count"] == len(inv["weights"]) == 44, "target count")
    weights = {e["relative_path"]: e for e in inv["weights"]}
    require(len(weights) == 44, "duplicate targets")
    require(sum(e["size_bytes"] for e in weights.values()) == inv["target_logical_bytes"]
            == 88_946_458_314, "target bytes")
    backups = {e["backup_relative_path"]: e for e in inv["metadata"]}
    require(len(backups) == inv["metadata_count"] == 502, "metadata count")
    require(set(backups) == {p.relative_to(bundle).as_posix()
                            for p in (bundle / "metadata").rglob("*") if p.is_file()},
            "metadata file set")
    for path, entry in backups.items():
        local = bundle / path
        require(not local.is_symlink() and local.resolve().is_relative_to(bundle.resolve()),
                "unsafe metadata copy")
        require(local.stat().st_size == entry["size_bytes"] and digest(local) == entry["sha256"],
                f"metadata bytes: {path}")
    require(digest(repo / "scripts/prune_v14_recorded_weights.py") == inv["script_sha256"],
            "pruner source mismatch")
    require(digest(repo / "scripts/prune_v12_recorded_weights.py") == inv["helper_sha256"],
            "historical helper mismatch")
    seal = json.loads((repo / "provenance/pilots/v16_slot_state_owner_20261014/SOURCE_SEAL.json")
                      .read_bytes())["source_hashes"]
    require(len(seal) == 526 and all(digest(repo / p) == h for p, h in seal.items()),
            "historical source seal mismatch")
    result = {"status": "PRE_DELETION_RECORD_VERIFIED", "inventory_sha256": digest(inv_path),
              "metadata_copies_verified": 502, "sealed_sources_unchanged": 526,
              "target_count": 44, "target_logical_bytes": inv["target_logical_bytes"],
              "weight_backups_created": False}
    terminal_path = bundle / "DELETE_FINISHED.json"
    if not terminal_path.exists():
        require(not any((bundle / name).exists() for name in
                        ("DELETE_STARTED.json", "DELETE_FAILED.json", "DELETIONS.jsonl")),
                "incomplete deletion; do not call it a pre-deletion record")
        return result
    require(not (bundle / "DELETE_FAILED.json").exists(), "failure receipt present")
    start = json.loads((bundle / "DELETE_STARTED.json").read_bytes())
    terminal = json.loads(terminal_path.read_bytes())
    deleted = [json.loads(line) for line in (bundle / "DELETIONS.jsonl").read_text().splitlines()]
    require(terminal["status"] == "COMPLETE", "terminal status")
    require(len(deleted) == terminal["deleted_count"] == 44, "deletion count")
    require({e["relative_path"] for e in deleted} == set(weights), "deletion path set")
    for entry in deleted:
        source = weights[entry["relative_path"]]
        require(entry["sha256"] == source["sha256"] and entry["bytes"] == source["size_bytes"],
                "deletion payload identity")
    require(sum(e["bytes"] for e in deleted) == terminal["deleted_logical_bytes"]
            == inv["target_logical_bytes"], "deletion byte accounting")
    require(start["inventory_sha256"] == terminal["inventory_sha256"] == digest(inv_path),
            "inventory seal")
    require(start["published_record_commit"] == terminal["published_record_commit"],
            "publication identity")
    require(start["published_metadata_hashes_verified"] == terminal["metadata_hashes_preserved"]
            == 502, "metadata preservation count")
    require(terminal["other_experiment_weights_stat_unchanged"]
            == len(inv["protected_other_weights"]) == 98, "protected weight count")
    require(start["available_bytes_before"] == terminal["available_bytes_before"],
            "before-capacity mismatch")
    require(terminal["no_weight_backups"] and not start["weight_backups_created"],
            "recoverability mismatch")
    available = terminal["available_bytes_after"]
    forecast, floor = 3 * 64 * 1024**3, 50 * 1024**3
    result.update(status="TERMINAL_RECORD_VERIFIED",
                  published_record_commit=start["published_record_commit"],
                  deleted_count=44, available_bytes_before=terminal["available_bytes_before"],
                  available_bytes_after=available,
                  observed_available_delta_bytes=available - terminal["available_bytes_before"],
                  prospective_three_arm_retained_forecast_bytes=forecast,
                  remaining_floor_bytes=floor,
                  surplus_above_forecast_and_floor_bytes=available - forecast - floor,
                  capacity_screen_pass=available >= forecast + floor,
                  not_a_gpu_host_or_frozen_run_admission=True,
                  old_gate="FAIL", winner="none", non_regression="NOT_ESTABLISHED")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.bundle.resolve(), Path(__file__).resolve().parents[1]),
                     indent=2, sort_keys=True))
