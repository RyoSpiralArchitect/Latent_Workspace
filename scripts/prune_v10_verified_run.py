#!/usr/bin/env python3
"""Fail-closed retention transition for one verified v10 run.

Dry-run is the default.  Execution requires ``--execute``, a non-empty reason,
and a compact-evidence export root.  Deletion targets are derived exclusively
from the verified run artifacts; callers cannot supply target paths or globs.

The resulting state is intentionally named ``verified_pruned`` rather than
``verified_completed``.  Its receipts preserve a historical verification
chain, but the trained weights are no longer loadable or reconstructible.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

RUN_VERIFICATION_FORMAT = "latent-workspace-v10-run-verification-v1"
ASSAY_VERIFICATION_FORMAT = "latent-workspace-v10-assay-verification-v1"
RESUME_VERIFICATION_FORMAT = "latent-workspace-v10-resume-verification-v1"
RESUME_EQUIVALENCE_FORMAT = "latent-workspace-v10-resume-equivalence-v1"
COMPACT_EXPORT_FORMAT = "latent-workspace-v10-compact-evidence-export-v1"
PRUNE_INTENT_FORMAT = "latent-workspace-v10-prune-intent-v1"
PRUNE_RECEIPT_FORMAT = "latent-workspace-v10-verified-run-prune-v1"

RUN_VERIFICATION_NAME = "RUN_VERIFICATION.json"
FULL_UPDATE_DELTA_NAME = "FULL_UPDATE_DELTA.json"
ASSAY_VERIFICATION_NAME = "ASSAY_VERIFICATION.json"
RESUME_VERIFICATION_NAME = "RESUME_VERIFICATION.json"
LAUNCHED_CONFIG_NAME = "LAUNCHED_CONFIG.json"
METRICS_NAME = "metrics.jsonl"
AMPUTATION_REPORT_NAME = "amputation_report.json"
RESUME_EQUIVALENCE_NAME = "resume_equivalence_result.json"
PRUNE_INTENT_NAME = "PRUNE_INTENT.json"
PRUNE_RECEIPT_NAME = "PRUNE_RECEIPT.json"
EXPORT_RECEIPT_NAME = "EXPORT_RECEIPT.json"

EXTERNAL_ASSAY_RESULTS = {
    "necessity": "necessity_result.json",
    "choice_eval": "choice_eval_result.json",
    "recruitment": "recruitment_result.json",
}
EXTERNAL_ASSAY_FORMATS = {
    "necessity": {
        "latent-workspace-v8-semantic-necessity-v2",
        "latent-workspace-v9-functional-necessity-v1",
    },
    "choice_eval": {"latent-workspace-v8-semantic-choice-eval-v2"},
    "recruitment": {"latent-workspace-v8-recruitability-v2"},
}

SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
CHECKPOINT_RE = re.compile(r"^checkpoint-([0-9]+)$")
PHASE_POINTER_RE = re.compile(r"^phase-boundary-step-([0-9]+)\.json$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
POINTER_NAMES = ("latest_checkpoint.json", "best_checkpoint.json")


class PruneError(RuntimeError):
    """A retention validation or transaction error."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PruneError(f"Could not read JSON receipt {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PruneError(f"JSON receipt must contain an object: {path}")
    return value


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_create_json(path: Path, value: Any) -> None:
    """Create a durable JSON file without ever replacing an existing path."""

    if path.exists() or path.is_symlink():
        raise PruneError(f"Refusing to overwrite existing evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise PruneError(f"Refusing to overwrite existing evidence: {path}") from exc
        temporary.unlink()
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _safe_relative(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise PruneError(f"{label} must be a non-empty POSIX relative path.")
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise PruneError(f"Unsafe {label}: {value!r}")
    if relative.as_posix() != value:
        raise PruneError(f"Non-canonical {label}: {value!r}")
    return value


def _safe_join(root: Path, relative: str, *, label: str) -> Path:
    relative = _safe_relative(relative, label=label)
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    try:
        candidate.resolve(strict=False).relative_to(root.resolve())
    except ValueError as exc:
        raise PruneError(f"{label} escapes its run root: {relative!r}") from exc
    return candidate


def _validate_sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise PruneError(f"{label} must be a lowercase SHA-256 digest.")
    return value


def _require_plain_directory(path: Path, *, label: str) -> None:
    try:
        observed = path.lstat()
    except FileNotFoundError as exc:
        raise PruneError(f"Missing {label}: {path}") from exc
    if stat.S_ISLNK(observed.st_mode) or not stat.S_ISDIR(observed.st_mode):
        raise PruneError(f"{label} must be a non-symlink directory: {path}")


def _resolve_run_dir(path: Path, *, label: str) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise PruneError(f"{label} must not be a symlink: {expanded}")
    resolved = expanded.resolve()
    _require_plain_directory(resolved, label=label)
    return resolved


def _regular_file_record(path: Path, *, relative: str) -> dict[str, Any]:
    relative = _safe_relative(relative, label="artifact path")
    try:
        observed = path.lstat()
    except FileNotFoundError as exc:
        raise PruneError(f"Missing artifact: {path}") from exc
    if stat.S_ISLNK(observed.st_mode) or not stat.S_ISREG(observed.st_mode):
        raise PruneError(f"Artifact must be a regular non-symlink file: {path}")
    if observed.st_nlink != 1:
        raise PruneError(f"Hard-linked artifacts are forbidden: {path}")
    return {
        "path": relative,
        "bytes": int(observed.st_size),
        "sha256": sha256_file(path),
    }


def _directory_layout(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Return a hash inventory and exact directory list without following links."""

    _require_plain_directory(root, label="artifact directory")
    inventory: list[dict[str, Any]] = []
    directories: list[str] = []
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        directory_names.sort()
        file_names.sort()
        for name in directory_names:
            path = current_path / name
            observed = path.lstat()
            if stat.S_ISLNK(observed.st_mode) or not stat.S_ISDIR(observed.st_mode):
                raise PruneError(f"Symlink or non-directory found in artifact tree: {path}")
            directories.append(path.relative_to(root).as_posix())
        for name in file_names:
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            inventory.append(_regular_file_record(path, relative=relative))
    inventory.sort(key=lambda item: str(item["path"]))
    directories.sort()
    return inventory, directories


def _inventory_sha256(inventory: Sequence[Mapping[str, Any]]) -> str:
    return sha256_bytes(canonical_json_bytes(list(inventory)))


def _validate_inventory_records(
    raw: Any,
    *,
    label: str,
) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise PruneError(f"{label} must be a non-empty inventory list.")
    records: list[dict[str, Any]] = []
    names: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise PruneError(f"Malformed record in {label}.")
        relative = _safe_relative(item.get("path"), label=f"{label} path")
        size = item.get("bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise PruneError(f"Invalid byte count for {relative!r} in {label}.")
        digest = _validate_sha256(item.get("sha256"), label=f"{label} sha256")
        if relative in names:
            raise PruneError(f"Duplicate path in {label}: {relative!r}")
        names.add(relative)
        records.append({"path": relative, "bytes": size, "sha256": digest})
    return sorted(records, key=lambda item: str(item["path"]))


def _artifact_matches(path: Path, expected: Mapping[str, Any]) -> None:
    actual = _regular_file_record(path, relative=str(expected["path"]))
    if actual != dict(expected):
        raise PruneError(f"Artifact inventory/hash mismatch: {path}")


def _require_mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PruneError(f"{label} must be a JSON object.")
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    *,
    label: str,
) -> None:
    observed = set(value)
    if observed != expected:
        raise PruneError(
            f"{label} keys are not exact: missing={sorted(expected - observed)}, "
            f"unexpected={sorted(observed - expected)}."
        )


def _require_nonnegative_number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise PruneError(f"{label} must be a non-negative finite number.")
    observed = float(value)
    if observed != observed or observed in {float("inf"), float("-inf")}:
        raise PruneError(f"{label} must be a non-negative finite number.")
    return observed


def _records_by_path(
    records: Sequence[Mapping[str, Any]],
    *,
    label: str,
) -> dict[str, Mapping[str, Any]]:
    result = {str(record["path"]): record for record in records}
    if len(result) != len(records):
        raise PruneError(f"{label} contains duplicate artifact paths.")
    return result


def _derive_required_assays(launched: Mapping[str, Any]) -> list[str]:
    assays = _require_mapping(launched.get("assays"), label="LAUNCHED_CONFIG.assays")
    amputation = assays.get("amputation_eval")
    if not isinstance(amputation, bool):
        raise PruneError("LAUNCHED_CONFIG assays.amputation_eval must be a boolean.")
    required = ["heldout_eval"]
    if amputation:
        required.append("amputation")
    for section in ("necessity", "choice_eval", "recruitment"):
        settings = _require_mapping(
            assays.get(section), label=f"LAUNCHED_CONFIG.assays.{section}"
        )
        enabled = settings.get("enabled")
        if not isinstance(enabled, bool):
            raise PruneError(
                f"LAUNCHED_CONFIG assays.{section}.enabled must be a boolean."
            )
        if enabled:
            required.append(section)
    return required


def _validate_assay_receipt(
    run_dir: Path,
    assay: Mapping[str, Any],
    *,
    provenance: Mapping[str, Any],
) -> list[dict[str, Any]]:
    run_id = provenance.get("run_id")
    if (
        assay.get("format") != ASSAY_VERIFICATION_FORMAT
        or assay.get("verified") is not True
        or assay.get("run_id") != run_id
        or assay.get("provenance") != provenance
    ):
        raise PruneError("ASSAY_VERIFICATION.json is incomplete or provenance-mismatched.")

    artifacts = _validate_receipt_artifacts(
        run_dir, assay, receipt_name=ASSAY_VERIFICATION_NAME
    )
    artifacts_by_path = _records_by_path(
        artifacts, label=f"{ASSAY_VERIFICATION_NAME} artifacts"
    )
    launched_path = run_dir / LAUNCHED_CONFIG_NAME
    launched_record = _regular_file_record(
        launched_path, relative=LAUNCHED_CONFIG_NAME
    )
    launched = read_json(launched_path)
    hashes = _require_mapping(provenance.get("hashes"), label="provenance.hashes")
    if hashes.get("materialized_config_sha256") != launched_record["sha256"]:
        raise PruneError("LAUNCHED_CONFIG hash disagrees with RUN_VERIFICATION provenance.")
    expected_assays = _derive_required_assays(launched)
    if assay.get("required_assays") != expected_assays:
        raise PruneError("ASSAY_VERIFICATION required assays differ from LAUNCHED_CONFIG.")
    if assay.get("completed_assays") != expected_assays:
        raise PruneError("ASSAY_VERIFICATION completed assays are not exact and ordered.")

    expected_artifact_paths = {
        RUN_VERIFICATION_NAME,
        LAUNCHED_CONFIG_NAME,
        METRICS_NAME,
    }
    if "amputation" in expected_assays:
        expected_artifact_paths.add(AMPUTATION_REPORT_NAME)
    expected_artifact_paths.update(
        EXTERNAL_ASSAY_RESULTS[name]
        for name in expected_assays
        if name in EXTERNAL_ASSAY_RESULTS
    )
    if set(artifacts_by_path) != expected_artifact_paths:
        raise PruneError(
            "ASSAY_VERIFICATION artifact paths do not exactly cover the configured assays."
        )
    if artifacts_by_path[LAUNCHED_CONFIG_NAME] != launched_record:
        raise PruneError("ASSAY_VERIFICATION does not exactly bind LAUNCHED_CONFIG.json.")

    verification_sha256 = sha256_file(run_dir / RUN_VERIFICATION_NAME)
    metrics_sha256 = sha256_file(run_dir / METRICS_NAME)
    manifest = read_json(run_dir / "final" / "manifest.json")
    engine_run_id = manifest.get("run_id")
    global_step = manifest.get("global_step")
    if not isinstance(engine_run_id, str) or not engine_run_id:
        raise PruneError("Final manifest has no engine run_id for assay binding.")
    if (
        isinstance(global_step, bool)
        or not isinstance(global_step, int)
        or global_step < 1
        or global_step != provenance.get("max_steps")
    ):
        raise PruneError("Final manifest global_step is not exact for assay binding.")
    expected_inputs = {
        "run_verification_sha256": verification_sha256,
        "launched_config_sha256": launched_record["sha256"],
        "metrics_sha256": metrics_sha256,
        "engine_run_id": engine_run_id,
        "global_step": global_step,
    }
    if assay.get("input_bindings") != expected_inputs:
        raise PruneError("ASSAY_VERIFICATION input bindings are not exact.")
    if artifacts_by_path[RUN_VERIFICATION_NAME]["sha256"] != verification_sha256:
        raise PruneError("ASSAY_VERIFICATION RUN_VERIFICATION artifact hash is not exact.")
    if artifacts_by_path[METRICS_NAME]["sha256"] != metrics_sha256:
        raise PruneError("ASSAY_VERIFICATION metrics artifact hash is not exact.")

    integrity = _require_mapping(
        assay.get("execution_integrity"), label="ASSAY_VERIFICATION execution_integrity"
    )
    _require_exact_keys(
        integrity,
        {"status", "required_equals_completed", "assays"},
        label="ASSAY_VERIFICATION execution_integrity",
    )
    results = _require_mapping(
        integrity.get("assays"), label="ASSAY_VERIFICATION execution assays"
    )
    if (
        integrity.get("status") != "PASS"
        or integrity.get("required_equals_completed") is not True
        or set(results) != set(expected_assays)
    ):
        raise PruneError("ASSAY_VERIFICATION execution-integrity gates are not exact.")
    for name in expected_assays:
        result = _require_mapping(results.get(name), label=f"assay result {name}")
        if result.get("execution_integrity") != "PASS":
            raise PruneError(f"Assay {name} has no exact execution-integrity PASS.")
        if name in EXTERNAL_ASSAY_RESULTS:
            if (
                result.get("artifact") != EXTERNAL_ASSAY_RESULTS[name]
                or result.get("format") not in EXTERNAL_ASSAY_FORMATS[name]
            ):
                raise PruneError(f"Assay {name} external artifact binding is unsupported.")
        else:
            evidence = _require_mapping(
                result.get("evidence"), label=f"assay result {name}.evidence"
            )
            if (
                evidence.get("artifact") != METRICS_NAME
                or evidence.get("step") != global_step
            ):
                raise PruneError(f"Assay {name} metric evidence is not exact.")
            _validate_sha256(
                evidence.get("record_sha256"), label=f"assay result {name} record sha256"
            )
            line = evidence.get("jsonl_line")
            if isinstance(line, bool) or not isinstance(line, int) or line < 1:
                raise PruneError(f"Assay {name} has no positive metrics line number.")
            _require_nonnegative_number(
                evidence.get("task_loss"), label=f"assay result {name} task_loss"
            )

    scientific = _require_mapping(
        assay.get("scientific_direction"), label="ASSAY_VERIFICATION scientific_direction"
    )
    _require_exact_keys(
        scientific,
        {"authoritative", "not_an_integrity_gate", "by_assay"},
        label="ASSAY_VERIFICATION scientific_direction",
    )
    directions = _require_mapping(
        scientific.get("by_assay"), label="ASSAY_VERIFICATION scientific directions"
    )
    if (
        scientific.get("authoritative") is not False
        or scientific.get("not_an_integrity_gate") is not True
        or set(directions) != set(expected_assays)
        or any(not isinstance(value, str) or not value for value in directions.values())
    ):
        raise PruneError("ASSAY_VERIFICATION scientific-direction boundary is malformed.")
    return artifacts


def _validate_exact_resume_comparisons(
    comparisons: Mapping[str, Any],
    *,
    split_step: int,
) -> None:
    _require_exact_keys(
        comparisons,
        {"passed", "base", "workspace", "trainer", "metrics", "resume_event", "elapsed_seconds"},
        label="resume equivalence comparisons",
    )
    if comparisons.get("passed") is not True:
        raise PruneError("Resume equivalence detailed comparisons did not pass.")
    _require_nonnegative_number(
        comparisons.get("elapsed_seconds"), label="resume comparison elapsed_seconds"
    )

    pair_keys = {"save_non_perturbation_A_B", "resume_B_C"}
    base = _require_mapping(comparisons.get("base"), label="resume base comparisons")
    workspace = _require_mapping(
        comparisons.get("workspace"), label="resume workspace comparisons"
    )
    trainer = _require_mapping(
        comparisons.get("trainer"), label="resume trainer comparisons"
    )
    for group_name, group in (
        ("base", base),
        ("workspace", workspace),
        ("trainer", trainer),
    ):
        if set(group) != pair_keys:
            raise PruneError(f"Resume {group_name} comparison keys are not exact.")

    for name, result_raw in base.items():
        result = _require_mapping(result_raw, label=f"resume base comparison {name}")
        for key in ("tensor_count", "total_numel"):
            value = result.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise PruneError(f"Resume base comparison {name} has invalid {key}.")
        if (
            result.get("bitwise_exact") is not True
            or result.get("changed_tensor_count") != 0
            or result.get("changed_element_count") != 0
        ):
            raise PruneError(f"Resume base comparison {name} is not bitwise exact.")
        _validate_sha256(
            result.get("tensor_schema_sha256"),
            label=f"resume base comparison {name} tensor schema sha256",
        )

    for name, result_raw in workspace.items():
        result = _require_mapping(result_raw, label=f"resume workspace comparison {name}")
        if result.get("exact") is not True:
            raise PruneError(f"Resume workspace comparison {name} is not exact.")
        for side in ("left_sha256", "right_sha256"):
            _validate_sha256(result.get(side), label=f"resume workspace {name} {side}")

    trainer_expectations = {
        "save_non_perturbation_A_B": (True, None),
        "resume_B_C": (False, True),
    }
    for name, result_raw in trainer.items():
        result = _require_mapping(result_raw, label=f"resume trainer comparison {name}")
        independent, run_id_preserved = trainer_expectations[name]
        if (
            result.get("exact") is not True
            or result.get("independent_runs") is not independent
            or result.get("run_id_preserved") is not run_id_preserved
        ):
            raise PruneError(f"Resume trainer comparison {name} is not exact.")
        for side in ("left_sha256", "right_sha256"):
            _validate_sha256(result.get(side), label=f"resume trainer {name} {side}")

    metrics = _require_mapping(comparisons.get("metrics"), label="resume metric comparisons")
    expected_metrics = {"train_A_B", "train_B_C", "final_A_B", "final_B_C"}
    if set(metrics) != expected_metrics:
        raise PruneError("Resume metric comparison keys are not exact.")
    for name, result_raw in metrics.items():
        result = _require_mapping(result_raw, label=f"resume metric comparison {name}")
        record_count = result.get("record_count")
        if (
            result.get("exact") is not True
            or isinstance(record_count, bool)
            or not isinstance(record_count, int)
            or record_count < 1
        ):
            raise PruneError(f"Resume metric comparison {name} is not exact.")

    resume_event = _require_mapping(
        comparisons.get("resume_event"), label="resume event comparison"
    )
    if (
        resume_event.get("step") != split_step
        or resume_event.get("run_id_preserved") is not True
    ):
        raise PruneError("Resume event does not prove exact checkpoint continuity.")


def _validate_resume_equivalence(
    run_dir: Path,
    equivalence: Mapping[str, Any],
    *,
    provenance: Mapping[str, Any],
    verification_sha256: str,
) -> None:
    if (
        equivalence.get("format") != RESUME_EQUIVALENCE_FORMAT
        or equivalence.get("passed") is not True
    ):
        raise PruneError("Resume equivalence artifact is unsupported or did not pass.")
    design = _require_mapping(equivalence.get("design"), label="resume equivalence design")
    _require_exact_keys(
        design,
        {
            "baseline_A",
            "control_B",
            "resumed_C",
            "split_step",
            "total_steps",
            "scheduler_horizon_held_fixed",
            "comparison",
        },
        label="resume equivalence design",
    )
    split_step = design.get("split_step")
    total_steps = design.get("total_steps")
    if (
        design.get("baseline_A") != provenance.get("output_dir")
        or design.get("comparison") != "bitwise_exact_zero_tolerance"
        or design.get("scheduler_horizon_held_fixed") is not True
        or isinstance(split_step, bool)
        or not isinstance(split_step, int)
        or isinstance(total_steps, bool)
        or not isinstance(total_steps, int)
        or total_steps != provenance.get("max_steps")
        or not 0 < split_step < total_steps
    ):
        raise PruneError("Resume equivalence design is not exact for this run.")
    _safe_relative(design.get("control_B"), label="resume control output")
    _safe_relative(design.get("resumed_C"), label="resume resumed output")

    input_bindings = _require_mapping(
        equivalence.get("input_bindings"), label="resume equivalence input_bindings"
    )
    _require_exact_keys(
        input_bindings,
        {
            "baseline_RUN_VERIFICATION_sha256",
            "baseline_LAUNCHED_CONFIG_sha256",
            "control_config_sha256",
            "resumed_config_sha256",
            "checkpoint_resume_signature",
            "validated_baseline_provenance_hashes",
        },
        label="resume equivalence input_bindings",
    )
    launched_sha256 = sha256_file(run_dir / LAUNCHED_CONFIG_NAME)
    hashes = _require_mapping(provenance.get("hashes"), label="provenance.hashes")
    checkpoint_signature = input_bindings.get("checkpoint_resume_signature")
    if (
        input_bindings.get("baseline_RUN_VERIFICATION_sha256") != verification_sha256
        or input_bindings.get("baseline_LAUNCHED_CONFIG_sha256") != launched_sha256
        or input_bindings.get("validated_baseline_provenance_hashes") != hashes
        or not isinstance(checkpoint_signature, str)
        or not checkpoint_signature
    ):
        raise PruneError("Resume equivalence input bindings are not exact for this run.")
    _validate_sha256(input_bindings.get("control_config_sha256"), label="control config sha256")
    _validate_sha256(input_bindings.get("resumed_config_sha256"), label="resumed config sha256")

    inventories = _require_mapping(
        equivalence.get("artifact_inventories"), label="resume artifact inventories"
    )
    inventory_keys = {"checkpoint_B_split", "final_A", "final_B", "final_C"}
    _require_exact_keys(inventories, inventory_keys, label="resume artifact inventories")
    normalized_inventories = {
        name: _validate_inventory_records(raw, label=f"resume inventory {name}")
        for name, raw in inventories.items()
    }
    verification = read_json(run_dir / RUN_VERIFICATION_NAME)
    expected_final = _validate_inventory_records(
        verification.get("final_inventory"), label="RUN_VERIFICATION final_inventory"
    )
    if normalized_inventories["final_A"] != expected_final:
        raise PruneError("Resume equivalence final_A inventory is not this verified run.")

    comparisons = _require_mapping(
        equivalence.get("comparisons"), label="resume equivalence comparisons"
    )
    _validate_exact_resume_comparisons(comparisons, split_step=split_step)

    environment = _require_mapping(
        equivalence.get("environment"), label="resume equivalence environment"
    )
    source_files = _require_mapping(
        hashes.get("source_files_sha256"), label="provenance source_files_sha256"
    )
    if (
        environment.get("engine_sha256")
        != source_files.get("src/latent_workspace_ft_v10/engine.py")
        or environment.get("matrix_runner_sha256") != hashes.get("runner_sha256")
        or environment.get("cuda_available") is not True
    ):
        raise PruneError("Resume equivalence runtime is not provenance-bound CUDA.")
    _validate_sha256(
        environment.get("resume_harness_sha256"), label="resume harness sha256"
    )
    launches = _require_mapping(
        equivalence.get("launches"), label="resume equivalence launches"
    )
    for name in ("control", "resumed"):
        launch = _require_mapping(launches.get(name), label=f"resume launch {name}")
        if launch.get("returncode") != 0:
            raise PruneError(f"Resume launch {name} did not complete successfully.")
    performance = _require_mapping(
        equivalence.get("performance_boundary"), label="resume performance boundary"
    )
    if (
        performance.get("training_optimizer_steps_executed")
        != total_steps + (total_steps - split_step)
        or performance.get("comparison_scope")
        != "same_host_same_single_gpu_same_source_and_runtime"
    ):
        raise PruneError("Resume equivalence performance boundary is not exact.")
    boundary = equivalence.get("claim_boundary")
    if not isinstance(boundary, str) or not boundary:
        raise PruneError("Resume equivalence claim boundary is missing.")


def _validate_receipt_artifacts(
    run_dir: Path,
    receipt: Mapping[str, Any],
    *,
    receipt_name: str,
) -> list[dict[str, Any]]:
    records = _validate_inventory_records(
        receipt.get("artifacts"), label=f"{receipt_name} artifacts"
    )
    for record in records:
        relative = str(record["path"])
        if (
            relative == PRUNE_RECEIPT_NAME
            or relative == PRUNE_INTENT_NAME
            or relative.startswith("final/base_model/")
            or CHECKPOINT_RE.fullmatch(PurePosixPath(relative).parts[0]) is not None
        ):
            raise PruneError(
                f"{receipt_name} references a non-compact or prune-controlled artifact: {relative}"
            )
        _artifact_matches(
            _safe_join(run_dir, relative, label=f"{receipt_name} artifact"),
            record,
        )
    return records


def _validate_evidence_receipts(
    run_dir: Path,
    *,
    provenance: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    run_id = provenance.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise PruneError("RUN_VERIFICATION provenance has no run_id.")

    assay_path = run_dir / ASSAY_VERIFICATION_NAME
    assay = read_json(assay_path)
    assay_artifacts = _validate_assay_receipt(
        run_dir, assay, provenance=provenance
    )

    resume_path = run_dir / RESUME_VERIFICATION_NAME
    resume = read_json(resume_path)
    comparison = resume.get("comparison")
    if (
        resume.get("format") != RESUME_VERIFICATION_FORMAT
        or resume.get("verified") is not True
        or resume.get("run_id") != run_id
        or resume.get("provenance") != provenance
        or not isinstance(comparison, dict)
        or comparison.get("passed") is not True
    ):
        raise PruneError("RESUME_VERIFICATION.json is incomplete or provenance-mismatched.")
    resume_artifacts = _validate_receipt_artifacts(
        run_dir, resume, receipt_name=RESUME_VERIFICATION_NAME
    )
    if (
        comparison.get("mode") != "bitwise_exact_zero_tolerance"
        or comparison.get("equivalence_format") != RESUME_EQUIVALENCE_FORMAT
        or comparison.get("equivalence_artifact") != RESUME_EQUIVALENCE_NAME
    ):
        raise PruneError("RESUME_VERIFICATION comparison scope is unsupported.")
    equivalence_path = _safe_relative(
        comparison["equivalence_artifact"],
        label="resume equivalence artifact",
    )
    matching_artifacts = [
        item for item in resume_artifacts if item["path"] == equivalence_path
    ]
    if len(matching_artifacts) != 1:
        raise PruneError("RESUME_VERIFICATION has no unique equivalence artifact.")
    equivalence = read_json(
        _safe_join(run_dir, equivalence_path, label="resume equivalence artifact")
    )
    verification_sha256 = sha256_file(run_dir / RUN_VERIFICATION_NAME)
    if (
        comparison.get("equivalence_sha256") != matching_artifacts[0]["sha256"]
        or comparison.get("baseline_run_verification_sha256")
        != verification_sha256
    ):
        raise PruneError("Resume equivalence artifact is not exactly bound to this run.")
    _validate_resume_equivalence(
        run_dir,
        equivalence,
        provenance=provenance,
        verification_sha256=verification_sha256,
    )
    return assay, resume, assay_artifacts + resume_artifacts


def _validate_run_verification(
    run_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    verification_path = run_dir / RUN_VERIFICATION_NAME
    verification = read_json(verification_path)
    if (
        verification.get("format") != RUN_VERIFICATION_FORMAT
        or verification.get("verified") is not True
    ):
        raise PruneError("RUN_VERIFICATION.json is unsupported or not verified.")
    provenance = verification.get("provenance")
    if not isinstance(provenance, dict):
        raise PruneError("RUN_VERIFICATION.json has no provenance object.")
    _safe_relative(provenance.get("run_id"), label="provenance run_id")

    expected_final = _validate_inventory_records(
        verification.get("final_inventory"), label="RUN_VERIFICATION final_inventory"
    )
    final_dir = run_dir / "final"
    actual_final, _directories = _directory_layout(final_dir)
    if actual_final != expected_final:
        raise PruneError("RUN_VERIFICATION final inventory/hash differs from final/.")
    completed = final_dir / "COMPLETED"
    if completed.read_text(encoding="utf-8").strip() != "ok":
        raise PruneError("Final COMPLETED marker is invalid.")
    manifest = read_json(final_dir / "manifest.json")
    if manifest.get("complete") is not True:
        raise PruneError("Final manifest is not complete.")

    delta = verification.get("full_update_delta")
    if not isinstance(delta, dict) or delta.get("passed") is not True:
        raise PruneError("RUN_VERIFICATION has no passing full-update delta binding.")
    if delta.get("path") != FULL_UPDATE_DELTA_NAME:
        raise PruneError("RUN_VERIFICATION full-update delta path is not canonical.")
    delta_record = _regular_file_record(
        run_dir / FULL_UPDATE_DELTA_NAME, relative=FULL_UPDATE_DELTA_NAME
    )
    if delta_record["sha256"] != delta.get("sha256"):
        raise PruneError("FULL_UPDATE_DELTA.json hash disagrees with RUN_VERIFICATION.")

    base_prefix = "base_model/"
    base_inventory = [
        {**item, "path": str(item["path"])[len(base_prefix) :]}
        for item in expected_final
        if str(item["path"]).startswith(base_prefix)
    ]
    if not base_inventory:
        raise PruneError("RUN_VERIFICATION final inventory has no base_model payload.")
    base_dir = final_dir / "base_model"
    actual_base, _base_directories = _directory_layout(base_dir)
    if actual_base != base_inventory:
        raise PruneError("Exact final/base_model inventory differs from RUN_VERIFICATION.")
    if not any(str(item["path"]).endswith(".safetensors") for item in base_inventory):
        raise PruneError("Verified final/base_model contains no safetensors weights.")
    return verification, expected_final, base_inventory


def _validate_checkpoint(run_dir: Path, checkpoint: Path) -> dict[str, Any]:
    match = CHECKPOINT_RE.fullmatch(checkpoint.name)
    if match is None:
        raise PruneError(f"Unexpected checkpoint-like path: {checkpoint.name}")
    _require_plain_directory(checkpoint, label="checkpoint")
    for relative in (
        "COMPLETED",
        "manifest.json",
        "experiment_config.json",
        "workspace_state.pt",
        "trainer_state.pt",
    ):
        _regular_file_record(checkpoint / relative, relative=relative)
    if (checkpoint / "COMPLETED").read_text(encoding="utf-8").strip() != "ok":
        raise PruneError(f"Incomplete checkpoint marker: {checkpoint.name}")
    manifest = read_json(checkpoint / "manifest.json")
    step = int(match.group(1))
    if manifest.get("complete") is not True or int(manifest.get("global_step", -1)) != step:
        raise PruneError(f"Checkpoint manifest/step mismatch: {checkpoint.name}")
    base_dir = checkpoint / "base_model"
    base_inventory, _base_directories = _directory_layout(base_dir)
    if not any(str(item["path"]).endswith(".safetensors") for item in base_inventory):
        raise PruneError(f"Checkpoint has no safetensors base weights: {checkpoint.name}")
    inventory, directories = _directory_layout(checkpoint)
    return {
        "source": checkpoint.name,
        "kind": "directory",
        "checkpoint_step": step,
        "inventory": inventory,
        "inventory_sha256": _inventory_sha256(inventory),
        "directories": directories,
        "logical_bytes": sum(int(item["bytes"]) for item in inventory),
    }


def _pointer_target(raw: Mapping[str, Any], *, name: str) -> tuple[str, int | None]:
    phase_match = PHASE_POINTER_RE.fullmatch(name)
    key = "checkpoint" if phase_match is not None else "path"
    value = raw.get(key)
    if not isinstance(value, str) or PurePosixPath(value).name != value:
        raise PruneError(f"Checkpoint pointer {name} has a non-local target.")
    match = CHECKPOINT_RE.fullmatch(value)
    if match is None:
        raise PruneError(f"Checkpoint pointer {name} has an invalid target: {value!r}")
    target_step = int(match.group(1))
    declared = raw.get("step", raw.get("global_step"))
    declared_step: int | None = None
    if declared is not None:
        if isinstance(declared, bool) or not isinstance(declared, int):
            raise PruneError(f"Checkpoint pointer {name} has an invalid step.")
        declared_step = declared
        if declared_step != target_step:
            raise PruneError(f"Checkpoint pointer {name} step disagrees with its target.")
    if phase_match is not None and int(phase_match.group(1)) != target_step:
        raise PruneError(f"Phase-boundary pointer name/target step mismatch: {name}")
    return value, declared_step


def _discover_targets(
    run_dir: Path,
    *,
    base_inventory: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    base_dir = run_dir / "final" / "base_model"
    _actual_base, base_directories = _directory_layout(base_dir)
    targets: list[dict[str, Any]] = [
        {
            "source": "final/base_model",
            "kind": "directory",
            "inventory": list(base_inventory),
            "inventory_sha256": _inventory_sha256(base_inventory),
            "directories": base_directories,
            "logical_bytes": sum(int(item["bytes"]) for item in base_inventory),
        }
    ]

    checkpoints: dict[str, dict[str, Any]] = {}
    for entry in sorted(run_dir.iterdir(), key=lambda path: path.name):
        if entry.name.startswith("checkpoint-"):
            if CHECKPOINT_RE.fullmatch(entry.name) is None:
                raise PruneError(f"Unexpected checkpoint-like path: {entry.name}")
            checkpoint = _validate_checkpoint(run_dir, entry)
            checkpoints[entry.name] = checkpoint
            targets.append(checkpoint)

    pointer_paths: list[Path] = []
    for name in POINTER_NAMES:
        path = run_dir / name
        if path.exists() or path.is_symlink():
            pointer_paths.append(path)
    pointer_paths.extend(sorted(run_dir.glob("phase-boundary-step-*.json")))
    seen_pointers: set[str] = set()
    for path in pointer_paths:
        if path.name in seen_pointers:
            continue
        seen_pointers.add(path.name)
        record = _regular_file_record(path, relative=path.name)
        target, declared_step = _pointer_target(read_json(path), name=path.name)
        target_is_live = target in checkpoints
        if not target_is_live and PHASE_POINTER_RE.fullmatch(path.name) is None:
            raise PruneError(
                f"Checkpoint pointer {path.name} refers to absent/incomplete {target}."
            )
        targets.append(
            {
                "source": path.name,
                "kind": "file",
                "pointer_target": target,
                "pointer_step": declared_step,
                "pointer_target_state": (
                    "live" if target_is_live else "historically_dangling"
                ),
                "inventory": [record],
                "inventory_sha256": _inventory_sha256([record]),
                "directories": [],
                "logical_bytes": int(record["bytes"]),
            }
        )

    allowed_roots = {"final/base_model", *checkpoints}
    for current, directory_names, file_names in os.walk(run_dir, followlinks=False):
        current_path = Path(current)
        directory_names.sort()
        file_names.sort()
        for name in directory_names:
            path = current_path / name
            observed = path.lstat()
            if stat.S_ISLNK(observed.st_mode):
                raise PruneError(f"Symlink directories are forbidden in a prune candidate: {path}")
        for name in file_names:
            path = current_path / name
            observed = path.lstat()
            if stat.S_ISLNK(observed.st_mode):
                raise PruneError(f"Symlink files are forbidden in a prune candidate: {path}")
            if not stat.S_ISREG(observed.st_mode):
                raise PruneError(f"Non-regular file found in prune candidate: {path}")
            if observed.st_nlink != 1:
                raise PruneError(f"Hard-linked files are forbidden in a prune candidate: {path}")
            relative = path.relative_to(run_dir).as_posix()
            if name.endswith(".safetensors") and not any(
                relative == root or relative.startswith(root + "/") for root in allowed_roots
            ):
                raise PruneError(f"Unexpected safetensors file outside derived targets: {relative}")
    return targets


def _receipt_record(run_dir: Path, name: str) -> dict[str, Any]:
    return _regular_file_record(run_dir / name, relative=name)


def build_prune_plan(run_dir: Path) -> dict[str, Any]:
    """Validate an unpruned run and return an immutable, internally-derived plan."""

    run_dir = _resolve_run_dir(run_dir, label="run directory")
    if (run_dir / PRUNE_RECEIPT_NAME).exists() or (run_dir / PRUNE_INTENT_NAME).exists():
        raise PruneError("Run already has a prune receipt or incomplete prune intent.")

    verification, final_inventory, base_inventory = _validate_run_verification(run_dir)
    provenance = verification["provenance"]
    assay, resume, referenced_evidence = _validate_evidence_receipts(run_dir, provenance=provenance)
    targets = _discover_targets(run_dir, base_inventory=base_inventory)

    evidence_paths: set[str] = {
        RUN_VERIFICATION_NAME,
        FULL_UPDATE_DELTA_NAME,
        ASSAY_VERIFICATION_NAME,
        RESUME_VERIFICATION_NAME,
        "final/COMPLETED",
        "final/manifest.json",
        "final/experiment_config.json",
        "final/optimizer_coverage.json",
        "final/base_update_coverage.json",
    }
    evidence_paths.update(str(item["path"]) for item in referenced_evidence)
    for item in base_inventory:
        relative = str(item["path"])
        if not relative.endswith(".safetensors"):
            evidence_paths.add(f"final/base_model/{relative}")
    evidence_inventory = [
        _regular_file_record(
            _safe_join(run_dir, relative, label="compact evidence path"),
            relative=relative,
        )
        for relative in sorted(evidence_paths)
    ]

    preconditions = {
        "run_verification": _receipt_record(run_dir, RUN_VERIFICATION_NAME),
        "full_update_delta": _receipt_record(run_dir, FULL_UPDATE_DELTA_NAME),
        "assay_verification": _receipt_record(run_dir, ASSAY_VERIFICATION_NAME),
        "resume_verification": _receipt_record(run_dir, RESUME_VERIFICATION_NAME),
        "assay_required": sorted(assay["required_assays"]),
        "assay_completed": sorted(assay["completed_assays"]),
        "resume_comparison_passed": bool(resume["comparison"]["passed"]),
    }
    return {
        "format": "latent-workspace-v10-prune-plan-v1",
        "created_utc": utc_now(),
        "provenance": provenance,
        "preconditions": preconditions,
        "pre_prune_final_inventory": final_inventory,
        "pre_prune_final_inventory_sha256": _inventory_sha256(final_inventory),
        "targets": targets,
        "target_count": len(targets),
        "total_logical_bytes": sum(int(item["logical_bytes"]) for item in targets),
        "compact_evidence_inventory": evidence_inventory,
        "compact_evidence_inventory_sha256": _inventory_sha256(evidence_inventory),
    }


def _safe_export_destination(export_root: Path, provenance: Mapping[str, Any]) -> Path:
    parts: list[str] = []
    for label, value in (
        ("profile", provenance.get("profile")),
        ("condition", provenance.get("condition")),
        ("seed", f"seed_{provenance.get('seed')}"),
    ):
        if not isinstance(value, str) or SAFE_COMPONENT_RE.fullmatch(value) is None:
            raise PruneError(f"Provenance {label} is unsafe for an export destination.")
        parts.append(value)
    return export_root.joinpath(*parts)


def _export_compact_evidence(
    run_dir: Path,
    *,
    export_root: Path,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    expanded_export_root = export_root.expanduser()
    if expanded_export_root.is_symlink():
        raise PruneError("Compact export root must not be a symlink.")
    export_root = expanded_export_root.resolve()
    if export_root == run_dir or run_dir in export_root.parents or export_root in run_dir.parents:
        raise PruneError("Compact export root must be outside the run directory tree.")
    destination = _safe_export_destination(export_root, plan["provenance"])
    if destination.exists() or destination.is_symlink():
        raise PruneError(f"Compact export destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.incomplete-{uuid.uuid4().hex}"
    temporary.mkdir(parents=False, exist_ok=False)
    try:
        expected = _validate_inventory_records(
            plan["compact_evidence_inventory"], label="compact evidence plan"
        )
        for item in expected:
            relative = str(item["path"])
            source = _safe_join(run_dir, relative, label="compact evidence source")
            _artifact_matches(source, item)
            target = _safe_join(temporary, relative, label="compact evidence destination")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            _artifact_matches(target, item)
        actual, _directories = _directory_layout(temporary)
        if actual != expected:
            raise PruneError("Compact export inventory differs after copy.")
        receipt = {
            "format": COMPACT_EXPORT_FORMAT,
            "created_utc": utc_now(),
            "provenance": plan["provenance"],
            "inventory": actual,
            "inventory_sha256": _inventory_sha256(actual),
            "file_count": len(actual),
            "total_bytes": sum(int(item["bytes"]) for item in actual),
        }
        atomic_write_json(temporary / EXPORT_RECEIPT_NAME, receipt)
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    export_receipt = _regular_file_record(
        destination / EXPORT_RECEIPT_NAME,
        relative=EXPORT_RECEIPT_NAME,
    )
    return {
        "destination": str(destination),
        "receipt": export_receipt,
        "inventory": plan["compact_evidence_inventory"],
        "inventory_sha256": plan["compact_evidence_inventory_sha256"],
        "reverified": True,
    }


def _quarantine_relative(index: int, target: Mapping[str, Any]) -> str:
    source_name = str(target["source"]).replace("/", "__")
    return f"targets/{index:04d}-{source_name}"


def _verify_target_at(path: Path, target: Mapping[str, Any]) -> None:
    expected = _validate_inventory_records(target.get("inventory"), label="prune target")
    if target.get("kind") == "directory":
        actual, directories = _directory_layout(path)
        if actual != expected or directories != target.get("directories"):
            raise PruneError(f"Prune target mutated: {path}")
    elif target.get("kind") == "file":
        if len(expected) != 1:
            raise PruneError("File prune target must have exactly one inventory record.")
        _artifact_matches(path, expected[0])
    else:
        raise PruneError("Unsupported prune target kind.")
    if _inventory_sha256(expected) != target.get("inventory_sha256"):
        raise PruneError(f"Prune target inventory digest mismatch: {path}")


def _delete_exact_target(path: Path, target: Mapping[str, Any]) -> None:
    _verify_target_at(path, target)
    expected = _validate_inventory_records(target["inventory"], label="delete target")
    if target["kind"] == "file":
        path.unlink()
        _fsync_directory(path.parent)
        return
    for item in expected:
        child = _safe_join(path, str(item["path"]), label="quarantined target file")
        child.unlink()
    directories = target.get("directories")
    if not isinstance(directories, list):
        raise PruneError("Directory target has no exact directory list.")
    for relative in sorted(
        directories,
        key=lambda value: (len(PurePosixPath(str(value)).parts), str(value)),
        reverse=True,
    ):
        child = _safe_join(path, str(relative), label="quarantined target directory")
        child.rmdir()
    path.rmdir()
    _fsync_directory(path.parent)


def _inventory_run_after_prune(run_dir: Path) -> list[dict[str, Any]]:
    inventory, _directories = _directory_layout(run_dir)
    return [item for item in inventory if item["path"] != PRUNE_RECEIPT_NAME]


def _directories_run_after_prune(run_dir: Path) -> list[str]:
    _inventory, directories = _directory_layout(run_dir)
    return directories


def _receipt_with_report_hash(payload: Mapping[str, Any]) -> dict[str, Any]:
    receipt = dict(payload)
    receipt["report_sha256"] = sha256_bytes(canonical_json_bytes(receipt))
    return receipt


def _runner_lock_path(run_dir: Path, provenance: Mapping[str, Any]) -> Path:
    output_relative = _safe_relative(provenance.get("output_dir"), label="provenance output_dir")
    relative_parts = PurePosixPath(output_relative).parts
    repo_root = run_dir
    for _part in relative_parts:
        repo_root = repo_root.parent
    if (repo_root / output_relative).resolve() != run_dir:
        raise PruneError(
            "Run directory does not match provenance.output_dir; runner lock scope "
            "cannot be established safely."
        )
    return repo_root / "runs/v10/_control/RUNNER.lock"


@contextlib.contextmanager
def _exclusive_runner_lock(path: Path) -> Any:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise PruneError(f"Unsafe or inaccessible runner/pruner lock {path}: {exc}") from exc
    try:
        path_stat = path.lstat()
        descriptor_stat = os.fstat(descriptor)
        if (
            stat.S_ISLNK(path_stat.st_mode)
            or not stat.S_ISREG(path_stat.st_mode)
            or not stat.S_ISREG(descriptor_stat.st_mode)
            or path_stat.st_nlink != 1
            or descriptor_stat.st_nlink != 1
            or (path_stat.st_dev, path_stat.st_ino)
            != (descriptor_stat.st_dev, descriptor_stat.st_ino)
        ):
            raise PruneError(
                "Runner/pruner lock must be a regular, non-symlink, "
                f"single-link file: {path}"
            )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PruneError(f"Runner/pruner lock is held: {path}") from exc
        metadata = canonical_json_bytes(
            {
                "operation": "verified_run_prune",
                "pid": os.getpid(),
                "acquired_utc": utc_now(),
            }
        )
        os.ftruncate(descriptor, 0)
        os.write(descriptor, metadata)
        os.fsync(descriptor)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def execute_prune(
    run_dir: Path,
    *,
    reason: str,
    compact_export_root: Path,
    fault_phase: str | None = None,
) -> dict[str, Any]:
    """Acquire the matrix-wide lock and execute one retention transition."""

    resolved_run_dir = _resolve_run_dir(run_dir, label="run directory")
    verification = read_json(resolved_run_dir / RUN_VERIFICATION_NAME)
    provenance = verification.get("provenance")
    if not isinstance(provenance, dict):
        raise PruneError("RUN_VERIFICATION.json has no provenance object.")
    lock_path = _runner_lock_path(resolved_run_dir, provenance)
    with _exclusive_runner_lock(lock_path):
        return _execute_prune_locked(
            resolved_run_dir,
            reason=reason,
            compact_export_root=compact_export_root,
            fault_phase=fault_phase,
        )


def _finalize_prune_receipt(
    run_dir: Path,
    *,
    intent: Mapping[str, Any],
    intent_record: Mapping[str, Any],
    disk_before_delete: int,
    recovery: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    provenance = _require_mapping(intent.get("provenance"), label="prune intent provenance")
    targets_raw = intent.get("targets")
    if not isinstance(targets_raw, list) or not targets_raw:
        raise PruneError("Prune intent has no targets for finalization.")
    targets = [dict(_require_mapping(item, label="prune target")) for item in targets_raw]
    for target in targets:
        source = _safe_join(run_dir, str(target["source"]), label="deleted target")
        if source.exists() or source.is_symlink():
            raise PruneError(f"Derived prune target reappeared after deletion: {source}")
    quarantine_name = intent.get("quarantine")
    if (
        not isinstance(quarantine_name, str)
        or PurePosixPath(quarantine_name).name != quarantine_name
    ):
        raise PruneError("Prune intent has an unsafe quarantine name.")
    quarantine = run_dir.parent / quarantine_name
    if quarantine.exists() or quarantine.is_symlink():
        raise PruneError("Prune quarantine remains before receipt finalization.")
    export = _require_mapping(intent.get("compact_export"), label="compact export")
    _verify_export(export, provenance=provenance)

    retained = _inventory_run_after_prune(run_dir)
    retained_directories = _directories_run_after_prune(run_dir)
    disk_after_delete = shutil.disk_usage(run_dir).free
    receipt_payload: dict[str, Any] = {
        "format": PRUNE_RECEIPT_FORMAT,
        "transaction_id": intent["transaction_id"],
        "completed": True,
        "started_utc": intent["created_utc"],
        "completed_utc": utc_now(),
        "explicit_opt_in": True,
        "reason": intent["reason"],
        "provenance": provenance,
        "intent": dict(intent_record),
        "preconditions": intent["preconditions"],
        "pre_prune_final_inventory_sha256": intent[
            "pre_prune_final_inventory_sha256"
        ],
        "deleted_targets": targets,
        "deleted_target_count": len(targets),
        "logical_bytes_removed": intent["total_logical_bytes"],
        "observed_free_disk_bytes_before_delete": disk_before_delete,
        "observed_free_disk_bytes_after_delete": disk_after_delete,
        "observed_free_disk_delta_bytes": disk_after_delete - disk_before_delete,
        "compact_export": export,
        "retained_inventory": retained,
        "retained_inventory_sha256": _inventory_sha256(retained),
        "retained_directories": retained_directories,
        "post_prune_checks": {
            "all_derived_targets_absent": True,
            "quarantine_absent": True,
            "retained_inventory_rehashed": True,
            "retained_directories_rehashed": True,
            "compact_export_rehashed": True,
        },
        "recoverability": {
            "pinned_initial_model": "recoverable_from_pinned_model_revision",
            "trained_final_weights": "not_recoverable_without_external_weight_backup",
            "completed_checkpoints": "not_recoverable_without_external_weight_backup",
            "integrity_evidence_is_a_backup": False,
        },
        "state": "verified_pruned",
        "claim_boundary": (
            "This receipt preserves the hash-bound history of a previously verified "
            "run and proves the recorded local targets are absent after an explicit "
            "retention transition. It does not make the trained weights loadable or "
            "reconstructible and does not prove training quality or scientific success."
        ),
    }
    if recovery is not None:
        receipt_payload["recovery"] = dict(recovery)
    receipt = _receipt_with_report_hash(receipt_payload)
    atomic_create_json(run_dir / PRUNE_RECEIPT_NAME, receipt)
    verify_pruned(run_dir, expected_provenance=provenance)
    return receipt


def _execute_prune_locked(
    run_dir: Path,
    *,
    reason: str,
    compact_export_root: Path,
    fault_phase: str | None = None,
) -> dict[str, Any]:
    """Execute one exact verified-run retention transition.

    ``fault_phase`` exists solely for deterministic local fault-injection tests.
    An injected or real failure after intent creation deliberately leaves a
    protected ``prune_incomplete`` state. It is never finalized implicitly;
    ``--execute --recover`` must explicitly continue the intent-bound deletion.
    """

    reason = reason.strip()
    if not reason:
        raise PruneError("Execution requires a non-empty pruning reason.")
    run_dir = _resolve_run_dir(run_dir, label="run directory")
    plan = build_prune_plan(run_dir)
    export = _export_compact_evidence(
        run_dir,
        export_root=compact_export_root,
        plan=plan,
    )
    transaction_id = uuid.uuid4().hex
    quarantine = run_dir.parent / f".{run_dir.name}.prune-quarantine-{transaction_id}"
    if quarantine.exists() or quarantine.is_symlink():
        raise PruneError(f"Quarantine path already exists: {quarantine}")
    if run_dir.stat().st_dev != quarantine.parent.stat().st_dev:
        raise PruneError("Prune quarantine must be on the run directory filesystem.")

    targets: list[dict[str, Any]] = []
    for index, raw in enumerate(plan["targets"]):
        target = dict(raw)
        target["quarantine"] = _quarantine_relative(index, target)
        targets.append(target)
    intent = {
        "format": PRUNE_INTENT_FORMAT,
        "transaction_id": transaction_id,
        "created_utc": utc_now(),
        "state": "prepared",
        "explicit_opt_in": True,
        "reason": reason,
        "provenance": plan["provenance"],
        "preconditions": plan["preconditions"],
        "pre_prune_final_inventory_sha256": plan["pre_prune_final_inventory_sha256"],
        "targets": targets,
        "target_count": len(targets),
        "total_logical_bytes": plan["total_logical_bytes"],
        "compact_export": export,
        "quarantine": quarantine.name,
    }
    intent_path = run_dir / PRUNE_INTENT_NAME
    atomic_create_json(intent_path, intent)
    intent_record = _regular_file_record(intent_path, relative=PRUNE_INTENT_NAME)
    if fault_phase == "after_intent":
        raise PruneError("Injected failure after intent creation.")

    quarantine.mkdir(parents=False, exist_ok=False)
    moved = 0
    for target in targets:
        source = _safe_join(run_dir, str(target["source"]), label="derived prune target")
        _verify_target_at(source, target)
        destination = _safe_join(
            quarantine,
            str(target["quarantine"]),
            label="quarantine target",
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)
        _fsync_directory(source.parent)
        _fsync_directory(destination.parent)
        moved += 1
        if fault_phase == "after_first_quarantine" and moved == 1:
            raise PruneError("Injected failure after first quarantine move.")
    if fault_phase == "after_quarantine":
        raise PruneError("Injected failure after quarantine completion.")

    for target in targets:
        destination = _safe_join(
            quarantine,
            str(target["quarantine"]),
            label="quarantined target",
        )
        _verify_target_at(destination, target)

    disk_before_delete = shutil.disk_usage(run_dir).free
    deleted = 0
    for target in targets:
        destination = _safe_join(
            quarantine,
            str(target["quarantine"]),
            label="quarantined target",
        )
        _delete_exact_target(destination, target)
        deleted += 1
        if fault_phase == "after_first_delete" and deleted == 1:
            raise PruneError("Injected failure after first exact deletion.")
    targets_dir = quarantine / "targets"
    if targets_dir.exists():
        targets_dir.rmdir()
    quarantine.rmdir()
    _fsync_directory(quarantine.parent)
    if fault_phase == "after_delete":
        raise PruneError("Injected failure after deletion before final receipt.")

    return _finalize_prune_receipt(
        run_dir,
        intent=intent,
        intent_record=intent_record,
        disk_before_delete=disk_before_delete,
    )


def _validate_remaining_target(path: Path, target: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a crash-partially-deleted quarantine target as an exact subset."""

    expected = _validate_inventory_records(target.get("inventory"), label="prune target")
    if _inventory_sha256(expected) != target.get("inventory_sha256"):
        raise PruneError(f"Prune target inventory digest mismatch: {path}")
    kind = target.get("kind")
    if kind == "file":
        if len(expected) != 1:
            raise PruneError("File prune target must have exactly one inventory record.")
        _artifact_matches(path, expected[0])
        return {"remaining_files": 1, "partial": False}
    if kind != "directory":
        raise PruneError("Unsupported prune target kind.")
    actual, actual_directories = _directory_layout(path)
    expected_by_path = {str(item["path"]): item for item in expected}
    for item in actual:
        if expected_by_path.get(str(item["path"])) != item:
            raise PruneError(f"Unexpected or mutated remaining quarantine file: {path}")
    expected_directories = target.get("directories")
    if (
        not isinstance(expected_directories, list)
        or any(not isinstance(item, str) for item in expected_directories)
        or not set(actual_directories) <= set(expected_directories)
    ):
        raise PruneError(f"Unexpected remaining quarantine directory: {path}")
    return {
        "remaining_files": len(actual),
        "partial": actual != expected or actual_directories != expected_directories,
    }


def _delete_remaining_target(path: Path, target: Mapping[str, Any]) -> None:
    if not path.exists() and not path.is_symlink():
        return
    _validate_remaining_target(path, target)
    if target["kind"] == "file":
        path.unlink()
        _fsync_directory(path.parent)
        return
    actual, directories = _directory_layout(path)
    for item in actual:
        child = _safe_join(path, str(item["path"]), label="remaining quarantine file")
        child.unlink()
    for relative in sorted(
        directories,
        key=lambda value: (len(PurePosixPath(value).parts), value),
        reverse=True,
    ):
        _safe_join(path, relative, label="remaining quarantine directory").rmdir()
    path.rmdir()
    _fsync_directory(path.parent)


def _require_plain_parent_chain(root: Path, relative_parent: PurePosixPath) -> Path:
    current = root
    for part in relative_parent.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            _require_plain_directory(current, label="quarantine parent")
        else:
            current.mkdir()
            _fsync_directory(current.parent)
    return current


def _remove_empty_quarantine(quarantine: Path) -> None:
    if not quarantine.exists() and not quarantine.is_symlink():
        return
    _require_plain_directory(quarantine, label="prune quarantine")
    inventory, directories = _directory_layout(quarantine)
    if inventory:
        raise PruneError("Unexpected files remain outside validated quarantine targets.")
    for relative in sorted(
        directories,
        key=lambda value: (len(PurePosixPath(value).parts), value),
        reverse=True,
    ):
        _safe_join(quarantine, relative, label="empty quarantine directory").rmdir()
    quarantine.rmdir()
    _fsync_directory(quarantine.parent)


def _validate_recovery_intent(
    run_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], Path]:
    if (run_dir / PRUNE_RECEIPT_NAME).exists() or (run_dir / PRUNE_RECEIPT_NAME).is_symlink():
        raise PruneError("A prune receipt already exists; recovery cannot replace it.")
    intent_path = run_dir / PRUNE_INTENT_NAME
    intent_record = _regular_file_record(intent_path, relative=PRUNE_INTENT_NAME)
    intent = read_json(intent_path)
    transaction_id = intent.get("transaction_id")
    if (
        intent.get("format") != PRUNE_INTENT_FORMAT
        or intent.get("state") != "prepared"
        or intent.get("explicit_opt_in") is not True
        or not isinstance(transaction_id, str)
        or re.fullmatch(r"[0-9a-f]{32}", transaction_id) is None
        or not isinstance(intent.get("reason"), str)
        or not str(intent["reason"]).strip()
    ):
        raise PruneError("PRUNE_INTENT.json is unsupported or incomplete.")
    provenance = _require_mapping(intent.get("provenance"), label="intent provenance")
    verification = read_json(run_dir / RUN_VERIFICATION_NAME)
    if (
        verification.get("format") != RUN_VERIFICATION_FORMAT
        or verification.get("verified") is not True
        or verification.get("provenance") != provenance
    ):
        raise PruneError("Recovery intent does not bind the retained verified run.")
    preconditions = _require_mapping(intent.get("preconditions"), label="intent preconditions")
    for key in (
        "run_verification",
        "full_update_delta",
        "assay_verification",
        "resume_verification",
    ):
        record = _require_mapping(preconditions.get(key), label=f"precondition {key}")
        relative = _safe_relative(record.get("path"), label=f"precondition {key} path")
        _artifact_matches(_safe_join(run_dir, relative, label=f"precondition {key}"), record)
    _validate_evidence_receipts(run_dir, provenance=provenance)
    expected_final = _validate_inventory_records(
        verification.get("final_inventory"), label="RUN_VERIFICATION final inventory"
    )
    if intent.get("pre_prune_final_inventory_sha256") != _inventory_sha256(expected_final):
        raise PruneError("Recovery intent pre-prune final inventory binding is invalid.")
    export = _require_mapping(intent.get("compact_export"), label="intent compact export")
    _verify_export(export, provenance=provenance)

    raw_targets = intent.get("targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise PruneError("Recovery intent has no target list.")
    targets: list[dict[str, Any]] = []
    sources: set[str] = set()
    quarantines: set[str] = set()
    base_count = 0
    logical_bytes = 0
    for index, raw in enumerate(raw_targets):
        target = dict(_require_mapping(raw, label="recovery target"))
        source = _safe_relative(target.get("source"), label="recovery target source")
        if source in sources:
            raise PruneError(f"Duplicate recovery target source: {source}")
        sources.add(source)
        if source == "final/base_model":
            base_count += 1
        elif CHECKPOINT_RE.fullmatch(source) is None and (
            source not in POINTER_NAMES and PHASE_POINTER_RE.fullmatch(source) is None
        ):
            raise PruneError(f"Recovery target is outside the closed scope: {source}")
        quarantine_relative = _safe_relative(
            target.get("quarantine"), label="recovery quarantine target"
        )
        if quarantine_relative != _quarantine_relative(index, target):
            raise PruneError("Recovery quarantine target does not match its deterministic path.")
        if quarantine_relative in quarantines:
            raise PruneError(f"Duplicate recovery quarantine path: {quarantine_relative}")
        quarantines.add(quarantine_relative)
        inventory = _validate_inventory_records(
            target.get("inventory"), label=f"recovery target {source}"
        )
        if target.get("inventory_sha256") != _inventory_sha256(inventory):
            raise PruneError(f"Recovery target inventory hash is invalid: {source}")
        target_bytes = sum(int(item["bytes"]) for item in inventory)
        if target.get("logical_bytes") != target_bytes:
            raise PruneError(f"Recovery target byte count is invalid: {source}")
        logical_bytes += target_bytes
        kind = target.get("kind")
        directories = target.get("directories")
        if kind not in {"file", "directory"} or not isinstance(directories, list):
            raise PruneError(f"Recovery target kind/directory list is invalid: {source}")
        targets.append(target)
    if (
        base_count != 1
        or intent.get("target_count") != len(targets)
        or intent.get("total_logical_bytes") != logical_bytes
    ):
        raise PruneError("Recovery target aggregate counts are invalid.")
    quarantine_name = intent.get("quarantine")
    expected_quarantine_name = f".{run_dir.name}.prune-quarantine-{transaction_id}"
    if quarantine_name != expected_quarantine_name:
        raise PruneError("Recovery quarantine name is not transaction-derived.")
    quarantine = run_dir.parent / expected_quarantine_name
    if quarantine.exists() or quarantine.is_symlink():
        _require_plain_directory(quarantine, label="prune quarantine")
    if run_dir.stat().st_dev != quarantine.parent.stat().st_dev:
        raise PruneError("Recovery quarantine is not on the run filesystem.")
    return intent, intent_record, targets, quarantine


def recover_prune(run_dir: Path) -> dict[str, Any]:
    """Explicitly continue and finalize one interrupted prune transaction."""

    resolved_run_dir = _resolve_run_dir(run_dir, label="run directory")
    verification = read_json(resolved_run_dir / RUN_VERIFICATION_NAME)
    provenance = _require_mapping(
        verification.get("provenance"), label="RUN_VERIFICATION provenance"
    )
    lock_path = _runner_lock_path(resolved_run_dir, provenance)
    with _exclusive_runner_lock(lock_path):
        return _recover_prune_locked(resolved_run_dir)


def _recover_prune_locked(run_dir: Path) -> dict[str, Any]:
    intent, intent_record, targets, quarantine = _validate_recovery_intent(run_dir)
    disk_before_delete = shutil.disk_usage(run_dir).free
    initial_states: dict[str, str] = {}
    if not quarantine.exists():
        quarantine.mkdir(parents=False, exist_ok=False)
        _fsync_directory(quarantine.parent)

    for target in targets:
        source = _safe_join(run_dir, str(target["source"]), label="recovery source")
        destination = _safe_join(
            quarantine,
            str(target["quarantine"]),
            label="recovery quarantine target",
        )
        source_exists = source.exists() or source.is_symlink()
        destination_exists = destination.exists() or destination.is_symlink()
        if source_exists and destination_exists:
            raise PruneError(f"Recovery target exists in source and quarantine: {source}")
        if source_exists:
            _verify_target_at(source, target)
            initial_states[str(target["source"])] = "source"
            relative_parent = PurePosixPath(str(target["quarantine"])).parent
            _require_plain_parent_chain(quarantine, relative_parent)
            os.replace(source, destination)
            _fsync_directory(source.parent)
            _fsync_directory(destination.parent)
            _verify_target_at(destination, target)
        elif destination_exists:
            remaining = _validate_remaining_target(destination, target)
            initial_states[str(target["source"])] = (
                "quarantine_partial" if remaining["partial"] else "quarantine_complete"
            )
        else:
            initial_states[str(target["source"])] = "already_deleted"

    for target in targets:
        destination = _safe_join(
            quarantine,
            str(target["quarantine"]),
            label="recovery quarantine target",
        )
        _delete_remaining_target(destination, target)
    _remove_empty_quarantine(quarantine)
    return _finalize_prune_receipt(
        run_dir,
        intent=intent,
        intent_record=intent_record,
        disk_before_delete=disk_before_delete,
        recovery={
            "mode": "explicit_continue_and_finalize",
            "recovered_utc": utc_now(),
            "initial_target_states": initial_states,
            "automatic_recovery": False,
            "claim_boundary": (
                "Recovery revalidated exact live or remaining target subsets and explicitly "
                "continued the already-authorized deletion. Already absent bytes cannot be "
                "rehash-verified after deletion; their pre-delete hashes remain intent-bound."
            ),
        },
    )


def _verify_export(export: Mapping[str, Any], *, provenance: Mapping[str, Any]) -> None:
    destination_raw = export.get("destination")
    if not isinstance(destination_raw, str) or not destination_raw:
        raise PruneError("Prune receipt has no compact export destination.")
    expanded_destination = Path(destination_raw).expanduser()
    if expanded_destination.is_symlink():
        raise PruneError("Compact export destination must not be a symlink.")
    destination = expanded_destination.resolve()
    _require_plain_directory(destination, label="compact export destination")
    receipt_record = export.get("receipt")
    if not isinstance(receipt_record, dict):
        raise PruneError("Prune receipt has no compact export receipt binding.")
    _artifact_matches(destination / EXPORT_RECEIPT_NAME, receipt_record)
    export_receipt = read_json(destination / EXPORT_RECEIPT_NAME)
    expected_inventory = _validate_inventory_records(
        export.get("inventory"), label="prune compact export inventory"
    )
    actual_inventory, _directories = _directory_layout(destination)
    actual_without_receipt = [
        item for item in actual_inventory if item["path"] != EXPORT_RECEIPT_NAME
    ]
    if (
        export_receipt.get("format") != COMPACT_EXPORT_FORMAT
        or export_receipt.get("provenance") != provenance
        or export_receipt.get("inventory") != expected_inventory
        or export_receipt.get("inventory_sha256") != _inventory_sha256(expected_inventory)
        or export.get("inventory_sha256") != _inventory_sha256(expected_inventory)
        or actual_without_receipt != expected_inventory
    ):
        raise PruneError("Compact evidence export failed exact re-verification.")


def verify_pruned(
    run_dir: Path,
    *,
    expected_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    run_dir = _resolve_run_dir(run_dir, label="pruned run directory")
    receipt_path = run_dir / PRUNE_RECEIPT_NAME
    _regular_file_record(receipt_path, relative=PRUNE_RECEIPT_NAME)
    receipt = read_json(receipt_path)
    unsigned = dict(receipt)
    report_sha256 = unsigned.pop("report_sha256", None)
    if (
        receipt.get("format") != PRUNE_RECEIPT_FORMAT
        or receipt.get("completed") is not True
        or receipt.get("explicit_opt_in") is not True
        or receipt.get("state") != "verified_pruned"
        or not isinstance(receipt.get("reason"), str)
        or not str(receipt["reason"]).strip()
        or report_sha256 != sha256_bytes(canonical_json_bytes(unsigned))
    ):
        raise PruneError("PRUNE_RECEIPT.json is incomplete or has a bad report hash.")
    provenance = receipt.get("provenance")
    if not isinstance(provenance, dict):
        raise PruneError("PRUNE_RECEIPT.json has no provenance object.")
    if expected_provenance is not None and provenance != dict(expected_provenance):
        raise PruneError(
            "Prune provenance does not match the current prepared run; "
            "historical/future provenance is never treated as stale output."
        )

    intent_record = receipt.get("intent")
    if not isinstance(intent_record, dict):
        raise PruneError("PRUNE_RECEIPT.json has no intent binding.")
    _artifact_matches(run_dir / PRUNE_INTENT_NAME, intent_record)
    intent = read_json(run_dir / PRUNE_INTENT_NAME)
    if (
        intent.get("format") != PRUNE_INTENT_FORMAT
        or intent.get("transaction_id") != receipt.get("transaction_id")
        or intent.get("provenance") != provenance
        or intent.get("targets") != receipt.get("deleted_targets")
    ):
        raise PruneError("Prune intent/final receipt binding mismatch.")

    preconditions = receipt.get("preconditions")
    if not isinstance(preconditions, dict) or preconditions != intent.get("preconditions"):
        raise PruneError("Prune preconditions do not match the immutable intent.")
    for key in (
        "run_verification",
        "full_update_delta",
        "assay_verification",
        "resume_verification",
    ):
        record = preconditions.get(key)
        if not isinstance(record, dict):
            raise PruneError(f"Prune precondition {key} is missing.")
        relative = _safe_relative(record.get("path"), label=f"{key} receipt path")
        _artifact_matches(_safe_join(run_dir, relative, label=key), record)
    run_verification = read_json(run_dir / RUN_VERIFICATION_NAME)
    if (
        run_verification.get("format") != RUN_VERIFICATION_FORMAT
        or run_verification.get("verified") is not True
        or run_verification.get("provenance") != provenance
    ):
        raise PruneError("Retained RUN_VERIFICATION.json is no longer exact.")
    _validate_evidence_receipts(run_dir, provenance=provenance)

    targets = receipt.get("deleted_targets")
    if not isinstance(targets, list) or not targets:
        raise PruneError("Prune receipt has no deleted target list.")
    target_sources: set[str] = set()
    target_logical_bytes = 0
    base_target_count = 0
    for target in targets:
        if not isinstance(target, dict):
            raise PruneError("Malformed deleted target record.")
        relative = _safe_relative(target.get("source"), label="deleted target")
        if relative in target_sources:
            raise PruneError(f"Duplicate deleted target path: {relative}")
        target_sources.add(relative)
        if relative == "final/base_model":
            base_target_count += 1
        elif CHECKPOINT_RE.fullmatch(relative) is None and (
            relative not in POINTER_NAMES and PHASE_POINTER_RE.fullmatch(relative) is None
        ):
            raise PruneError(f"Deleted target is outside the closed retention scope: {relative}")
        source = _safe_join(run_dir, relative, label="deleted target")
        if source.exists() or source.is_symlink():
            raise PruneError(f"Deleted target is present again: {relative}")
        target_inventory = _validate_inventory_records(
            target.get("inventory"), label="deleted target inventory"
        )
        if target.get("inventory_sha256") != _inventory_sha256(target_inventory):
            raise PruneError(f"Deleted target inventory hash is inconsistent: {relative}")
        logical_bytes = sum(int(item["bytes"]) for item in target_inventory)
        if target.get("logical_bytes") != logical_bytes:
            raise PruneError(f"Deleted target byte count is inconsistent: {relative}")
        target_logical_bytes += logical_bytes
    if base_target_count != 1:
        raise PruneError("Prune receipt must contain exactly one final/base_model target.")
    if (
        receipt.get("deleted_target_count") != len(targets)
        or receipt.get("logical_bytes_removed") != target_logical_bytes
    ):
        raise PruneError("Prune target aggregate counts are inconsistent.")
    final_inventory = _validate_inventory_records(
        run_verification.get("final_inventory"),
        label="retained RUN_VERIFICATION final inventory",
    )
    if receipt.get("pre_prune_final_inventory_sha256") != _inventory_sha256(
        final_inventory
    ) or intent.get("pre_prune_final_inventory_sha256") != _inventory_sha256(final_inventory):
        raise PruneError("Pre-prune final inventory binding is inconsistent.")
    quarantine_name = intent.get("quarantine")
    if (
        not isinstance(quarantine_name, str)
        or PurePosixPath(quarantine_name).name != quarantine_name
    ):
        raise PruneError("Prune intent has an unsafe quarantine name.")
    quarantine = run_dir.parent / quarantine_name
    if quarantine.exists() or quarantine.is_symlink():
        raise PruneError("Prune quarantine remains after a completed receipt.")

    expected_retained = _validate_inventory_records(
        receipt.get("retained_inventory"), label="retained inventory"
    )
    actual_retained = _inventory_run_after_prune(run_dir)
    if actual_retained != expected_retained or receipt.get(
        "retained_inventory_sha256"
    ) != _inventory_sha256(expected_retained):
        raise PruneError("Retained run inventory/hash mismatch after pruning.")
    expected_directories = receipt.get("retained_directories")
    if (
        not isinstance(expected_directories, list)
        or any(not isinstance(item, str) for item in expected_directories)
        or expected_directories != sorted(set(expected_directories))
        or _directories_run_after_prune(run_dir) != expected_directories
    ):
        raise PruneError("Retained run directory layout mismatch after pruning.")
    export = receipt.get("compact_export")
    if not isinstance(export, dict):
        raise PruneError("Prune receipt has no compact export binding.")
    _verify_export(export, provenance=provenance)
    recoverability = receipt.get("recoverability")
    if (
        not isinstance(recoverability, dict)
        or recoverability.get("trained_final_weights")
        != "not_recoverable_without_external_weight_backup"
        or recoverability.get("completed_checkpoints")
        != "not_recoverable_without_external_weight_backup"
        or recoverability.get("integrity_evidence_is_a_backup") is not False
    ):
        raise PruneError("Prune recoverability boundary is missing or weakened.")
    return {
        "state": "verified_pruned",
        "reason": "Verified prune receipt, retained evidence, export, and target absence.",
        "receipt_sha256": sha256_file(receipt_path),
        "report_sha256": report_sha256,
        "logical_bytes_removed": receipt.get("logical_bytes_removed"),
    }


def classify_prune_state(
    run_dir: Path,
    *,
    expected_provenance: Mapping[str, Any] | None = None,
) -> tuple[str | None, str]:
    """Classify only retention states; return ``None`` for ordinary runs."""

    expanded = run_dir.expanduser()
    if expanded.is_symlink():
        return "invalid_prune_receipt", f"Run directory is a symlink: {expanded}"
    run_dir = expanded.resolve()
    receipt = run_dir / PRUNE_RECEIPT_NAME
    intent = run_dir / PRUNE_INTENT_NAME
    if receipt.exists() or receipt.is_symlink():
        try:
            result = verify_pruned(run_dir, expected_provenance=expected_provenance)
        except (PruneError, OSError, ValueError, TypeError) as exc:
            return "invalid_prune_receipt", str(exc)
        return "verified_pruned", str(result["reason"])
    if intent.exists() or intent.is_symlink():
        return (
            "prune_incomplete",
            "PRUNE_INTENT.json exists without a completed, valid PRUNE_RECEIPT.json; "
            "explicit recovery is required.",
        )
    return None, "no prune state"


def _plan_summary(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "mode": "dry_run",
        "would_execute": False,
        "provenance": plan["provenance"],
        "preconditions": plan["preconditions"],
        "targets": [
            {
                "source": item["source"],
                "kind": item["kind"],
                "file_count": len(item["inventory"]),
                "logical_bytes": item["logical_bytes"],
                "inventory_sha256": item["inventory_sha256"],
            }
            for item in plan["targets"]
        ],
        "target_count": plan["target_count"],
        "total_logical_bytes": plan["total_logical_bytes"],
        "compact_evidence_file_count": len(plan["compact_evidence_inventory"]),
        "compact_evidence_inventory_sha256": plan["compact_evidence_inventory_sha256"],
        "claim_boundary": (
            "Dry-run validates and reports internally-derived targets only. It creates "
            "no export, intent, quarantine, deletion, or prune receipt."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate or explicitly prune one verified v10 run."
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--compact-export-root", type=Path, default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--recover",
        action="store_true",
        help="With --execute, explicitly continue and finalize an existing prune intent.",
    )
    parser.add_argument("--reason", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.recover:
            if not args.execute:
                raise PruneError("--recover requires --execute.")
            if args.compact_export_root is not None or args.reason:
                raise PruneError(
                    "Recovery uses the intent-bound export and reason; do not resupply them."
                )
            receipt = recover_prune(args.run_dir)
            print(json.dumps(receipt, indent=2, sort_keys=True))
        elif args.execute:
            if args.compact_export_root is None:
                raise PruneError("--execute requires --compact-export-root.")
            receipt = execute_prune(
                args.run_dir,
                reason=args.reason,
                compact_export_root=args.compact_export_root,
            )
            print(json.dumps(receipt, indent=2, sort_keys=True))
        else:
            state, reason = classify_prune_state(args.run_dir)
            if state is not None:
                print(json.dumps({"state": state, "reason": reason}, indent=2, sort_keys=True))
            else:
                print(
                    json.dumps(
                        _plan_summary(build_prune_plan(args.run_dir)), indent=2, sort_keys=True
                    )
                )
    except PruneError as exc:
        print(f"prune blocked: {exc}", file=os.sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
