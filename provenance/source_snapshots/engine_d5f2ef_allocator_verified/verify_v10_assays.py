#!/usr/bin/env python3
"""Create a fail-closed post-training assay receipt for one verified v10 run.

This command does not run an assay.  It verifies the inline final-evaluation
records and any enabled, separately produced assay results.  Dry-run is the
default; ``--execute`` atomically creates ``ASSAY_VERIFICATION.json`` and never
overwrites an existing receipt.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import prune_v10_verified_run as pruning
import run_v10_resume_equivalence as resume_equivalence

RECEIPT_FORMAT = "latent-workspace-v10-assay-verification-v1"
RUN_VERIFICATION_FORMAT = "latent-workspace-v10-run-verification-v1"
RECEIPT_NAME = "ASSAY_VERIFICATION.json"
RUN_VERIFICATION_NAME = "RUN_VERIFICATION.json"
LAUNCHED_CONFIG_NAME = "LAUNCHED_CONFIG.json"
METRICS_NAME = "metrics.jsonl"
AMPUTATION_REPORT_NAME = "amputation_report.json"

EXTERNAL_RESULTS = {
    "necessity": "necessity_result.json",
    "choice_eval": "choice_eval_result.json",
    "recruitment": "recruitment_result.json",
}
EXTERNAL_FORMATS = {
    "necessity": {
        "latent-workspace-v8-semantic-necessity-v2",
        "latent-workspace-v9-functional-necessity-v1",
    },
    "choice_eval": {"latent-workspace-v8-semantic-choice-eval-v2"},
    "recruitment": {"latent-workspace-v8-recruitability-v2"},
}


class AssayVerificationError(RuntimeError):
    """A baseline or required assay artifact failed verification."""


@dataclass(frozen=True)
class Baseline:
    repo_root: Path
    run_dir: Path
    verification: Mapping[str, Any]
    provenance: Mapping[str, Any]
    config: Mapping[str, Any]
    manifest: Mapping[str, Any]
    engine_run_id: str
    global_step: int


def _mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AssayVerificationError(f"{label} must be a JSON object.")
    return value


def _string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise AssayVerificationError(f"{label} must be a non-empty string.")
    return value


def _integer(value: Any, *, label: str, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AssayVerificationError(f"{label} must be an integer.")
    if minimum is not None and value < minimum:
        raise AssayVerificationError(f"{label} must be at least {minimum}.")
    return value


def _boolean(value: Any, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise AssayVerificationError(f"{label} must be a boolean.")
    return value


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise AssayVerificationError(f"Could not read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AssayVerificationError(f"{label} must contain a JSON object: {path}")
    _finite_tree(value, label=label)
    return value


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value}")


def _finite_tree(value: Any, *, label: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise AssayVerificationError(f"{label} contains a non-finite number.")
    if isinstance(value, Mapping):
        for key, child in value.items():
            _finite_tree(child, label=f"{label}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _finite_tree(child, label=f"{label}[{index}]")


def _inside(root: Path, path: Path, *, label: str) -> Path:
    root = root.resolve()
    path = path.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise AssayVerificationError(f"{label} escapes repository root: {path}") from exc
    return path


def _artifact(run_dir: Path, relative: str) -> dict[str, Any]:
    try:
        return pruning._regular_file_record(run_dir / relative, relative=relative)
    except pruning.PruneError as exc:
        raise AssayVerificationError(str(exc)) from exc


def validate_baseline(repo_root: Path, run_dir: Path) -> Baseline:
    """Revalidate the durable run, provenance, and exact launched config bytes."""

    repo_root = repo_root.expanduser().resolve()
    run_dir = _inside(repo_root, run_dir.expanduser(), label="run directory")
    if (run_dir / RECEIPT_NAME).exists() or (run_dir / RECEIPT_NAME).is_symlink():
        raise AssayVerificationError(f"Refusing to overwrite existing {RECEIPT_NAME}.")
    try:
        verification, _final_inventory, _base_inventory = pruning._validate_run_verification(
            run_dir
        )
    except pruning.PruneError as exc:
        raise AssayVerificationError(f"Baseline is not currently verified: {exc}") from exc
    if verification.get("format") != RUN_VERIFICATION_FORMAT:
        raise AssayVerificationError("RUN_VERIFICATION.json has an unsupported format.")
    try:
        resume_equivalence.validate_current_hash_bindings(
            repo_root, run_dir, verification
        )
    except resume_equivalence.EquivalenceError as exc:
        raise AssayVerificationError(
            f"Baseline provenance is stale against the current repository: {exc}"
        ) from exc

    provenance = _mapping(verification.get("provenance"), label="provenance")
    run_id = _string(provenance.get("run_id"), label="provenance.run_id")
    try:
        pruning._safe_relative(run_id, label="provenance.run_id")
    except pruning.PruneError as exc:
        raise AssayVerificationError(str(exc)) from exc
    output_relative = _string(provenance.get("output_dir"), label="provenance.output_dir")
    if _inside(repo_root, repo_root / output_relative, label="provenance.output_dir") != run_dir:
        raise AssayVerificationError("RUN_VERIFICATION provenance does not name this run root.")
    condition = _string(provenance.get("condition"), label="provenance.condition")
    seed = _integer(provenance.get("seed"), label="provenance.seed")
    max_steps = _integer(provenance.get("max_steps"), label="provenance.max_steps", minimum=1)
    profile = _string(provenance.get("profile"), label="provenance.profile")
    if run_id != f"{condition}/seed_{seed}":
        raise AssayVerificationError("Provenance condition/seed do not exactly derive run_id.")
    if output_relative != f"runs/v10/{profile}/{run_id}":
        raise AssayVerificationError("Provenance profile/run_id do not exactly derive output_dir.")

    launched_path = run_dir / LAUNCHED_CONFIG_NAME
    launched_record = _artifact(run_dir, LAUNCHED_CONFIG_NAME)
    config = _read_json(launched_path, label=LAUNCHED_CONFIG_NAME)
    hashes = _mapping(provenance.get("hashes"), label="provenance.hashes")
    if hashes.get("materialized_config_sha256") != launched_record["sha256"]:
        raise AssayVerificationError("LAUNCHED_CONFIG hash disagrees with provenance.")
    train = _mapping(config.get("train"), label="LAUNCHED_CONFIG.train")
    if train.get("seed") != seed or train.get("max_steps") != max_steps:
        raise AssayVerificationError("LAUNCHED_CONFIG seed/max_steps disagree with provenance.")
    configured_output = Path(
        _string(train.get("output_dir"), label="LAUNCHED_CONFIG.train.output_dir")
    )
    configured_output = (
        configured_output.resolve()
        if configured_output.is_absolute()
        else (launched_path.parent / configured_output).resolve()
    )
    if configured_output != run_dir:
        raise AssayVerificationError("LAUNCHED_CONFIG output_dir disagrees with run root.")

    manifest = _read_json(run_dir / "final/manifest.json", label="final manifest")
    receipt_manifest = _mapping(
        verification.get("final_manifest"), label="RUN_VERIFICATION.final_manifest"
    )
    if dict(receipt_manifest) != manifest:
        raise AssayVerificationError("RUN_VERIFICATION final_manifest is not exact.")
    engine_run_id = _string(manifest.get("run_id"), label="final manifest run_id")
    global_step = _integer(manifest.get("global_step"), label="final global_step", minimum=1)
    if global_step != max_steps:
        raise AssayVerificationError("Final global_step disagrees with contracted max_steps.")
    return Baseline(
        repo_root=repo_root,
        run_dir=run_dir,
        verification=verification,
        provenance=provenance,
        config=config,
        manifest=manifest,
        engine_run_id=engine_run_id,
        global_step=global_step,
    )


def derive_required_assays(config: Mapping[str, Any]) -> list[str]:
    assays = _mapping(config.get("assays"), label="LAUNCHED_CONFIG.assays")
    required = ["heldout_eval"]
    if _boolean(assays.get("amputation_eval"), label="assays.amputation_eval"):
        required.append("amputation")
    for section, name in (
        ("necessity", "necessity"),
        ("choice_eval", "choice_eval"),
        ("recruitment", "recruitment"),
    ):
        settings = _mapping(assays.get(section), label=f"assays.{section}")
        if _boolean(settings.get("enabled"), label=f"assays.{section}.enabled"):
            required.append(name)
    return required


def _metric_records(
    baseline: Baseline,
) -> tuple[dict[str, tuple[int, dict[str, Any]]], dict[str, Any]]:
    path = baseline.run_dir / METRICS_NAME
    _artifact(baseline.run_dir, METRICS_NAME)
    selected: dict[str, list[tuple[int, dict[str, Any]]]] = {
        "eval-final": [],
        "eval-final-amputated": [],
    }
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise AssayVerificationError(f"Could not read {METRICS_NAME}: {exc}") from exc
    if not lines:
        raise AssayVerificationError("metrics.jsonl is empty.")
    for line_number, line in enumerate(lines, start=1):
        if not line:
            raise AssayVerificationError(f"Blank metrics.jsonl line {line_number}.")
        try:
            value = json.loads(line, parse_constant=_reject_constant)
        except (json.JSONDecodeError, ValueError) as exc:
            raise AssayVerificationError(
                f"Malformed metrics.jsonl line {line_number}: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise AssayVerificationError(f"metrics.jsonl line {line_number} is not an object.")
        _finite_tree(value, label=f"metrics line {line_number}")
        split = value.get("split")
        if split in selected:
            selected[str(split)].append((line_number, value))
    exact: dict[str, tuple[int, dict[str, Any]]] = {}
    for split, matches in selected.items():
        if len(matches) > 1:
            raise AssayVerificationError(
                f"Expected at most one {split} record; found {len(matches)}."
            )
        if matches:
            line_number, record = matches[0]
            if record.get("run_id") != baseline.engine_run_id:
                raise AssayVerificationError(f"{split} run_id disagrees with final manifest.")
            if record.get("step") != baseline.global_step:
                raise AssayVerificationError(f"{split} step disagrees with final manifest.")
            task_loss = record.get("task_loss")
            if isinstance(task_loss, bool) or not isinstance(task_loss, (int, float)):
                raise AssayVerificationError(f"{split} has no finite numeric task_loss.")
            heldout_accuracy = record.get("functional_heldout_query_accuracy")
            if (
                isinstance(heldout_accuracy, bool)
                or not isinstance(heldout_accuracy, (int, float))
                or not math.isfinite(float(heldout_accuracy))
            ):
                raise AssayVerificationError(
                    f"{split} has no finite functional_heldout_query_accuracy."
                )
            exact[split] = (line_number, record)
    return exact, _artifact(baseline.run_dir, METRICS_NAME)


def _metric_evidence(line: int, record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact": METRICS_NAME,
        "jsonl_line": line,
        "record_sha256": pruning.sha256_bytes(pruning.canonical_json_bytes(dict(record))),
        "step": record["step"],
        "task_loss": float(record["task_loss"]),
        "functional_heldout_query_accuracy": float(
            record["functional_heldout_query_accuracy"]
        ),
    }


def _validate_amputation_report(
    baseline: Baseline,
    heldout: Mapping[str, Any],
    amputated: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    report = _read_json(
        baseline.run_dir / AMPUTATION_REPORT_NAME,
        label=AMPUTATION_REPORT_NAME,
    )
    artifact = _artifact(baseline.run_dir, AMPUTATION_REPORT_NAME)
    if report.get("step") != baseline.global_step:
        raise AssayVerificationError(
            "amputation_report.json step disagrees with final manifest."
        )
    full = _mapping(report.get("full"), label="amputation_report.full")
    cut = _mapping(report.get("amputated"), label="amputation_report.amputated")
    for label, observed, metric in (
        ("full", full, heldout),
        ("amputated", cut, amputated),
    ):
        for key in ("task_loss", "functional_heldout_query_accuracy"):
            if observed.get(key) != metric.get(key):
                raise AssayVerificationError(
                    f"amputation_report.{label}.{key} disagrees with metrics.jsonl."
                )
    expected_delta = float(heldout["task_loss"]) - float(amputated["task_loss"])
    if report.get("task_loss_delta_full_minus_amputated") != expected_delta:
        raise AssayVerificationError(
            "amputation_report task-loss delta disagrees with metrics.jsonl."
        )
    return report, artifact


def _validate_execution_marker(result: Mapping[str, Any], *, label: str) -> None:
    marker = result.get("execution_integrity")
    if marker is not None:
        status = marker.get("status") if isinstance(marker, Mapping) else marker
        if status != "PASS":
            raise AssayVerificationError(f"{label} execution_integrity is not PASS.")
    if "integrity_passed" in result and result.get("integrity_passed") is not True:
        raise AssayVerificationError(f"{label} integrity_passed is not true.")


def _validate_external(
    baseline: Baseline,
    assay: str,
    config: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], str]:
    relative = EXTERNAL_RESULTS[assay]
    result = _read_json(baseline.run_dir / relative, label=relative)
    record = _artifact(baseline.run_dir, relative)
    if result.get("format") not in EXTERNAL_FORMATS[assay]:
        raise AssayVerificationError(f"{relative} has an unsupported assay format.")
    _validate_execution_marker(result, label=relative)
    checkpoint = Path(_string(result.get("checkpoint"), label=f"{relative}.checkpoint"))
    checkpoint = (
        checkpoint.resolve()
        if checkpoint.is_absolute()
        else (baseline.run_dir / checkpoint).resolve()
    )
    if checkpoint != (baseline.run_dir / "final").resolve():
        raise AssayVerificationError(f"{relative} is not bound to this final checkpoint.")
    if result.get("source_sha256") != baseline.manifest.get("source_sha256"):
        raise AssayVerificationError(f"{relative} source_sha256 disagrees with final manifest.")
    if "provenance" in result and result.get("provenance") != baseline.provenance:
        raise AssayVerificationError(f"{relative} provenance is not exact.")
    if "run_id" in result and result.get("run_id") != baseline.provenance.get("run_id"):
        raise AssayVerificationError(f"{relative} run_id is not exact.")

    scientific = result.get("scientific_direction")
    direction = scientific if isinstance(scientific, str) and scientific else "reported"
    if assay == "necessity":
        metrics = _mapping(result.get("metrics"), label=f"{relative}.metrics")
        _mapping(result.get("effects"), label=f"{relative}.effects")
        _mapping(result.get("evidence_ladder"), label=f"{relative}.evidence_ladder")
        modes = config.get("modes")
        if not isinstance(modes, list) or not modes or any(not isinstance(x, str) for x in modes):
            raise AssayVerificationError("assays.necessity.modes must be a non-empty list.")
        if any(mode not in metrics for mode in modes):
            raise AssayVerificationError("Necessity result does not cover every configured mode.")
        if "primary_gate_passed" in result:
            gate = _boolean(result["primary_gate_passed"], label="necessity primary gate")
            direction = "supports_preregistered_gate" if gate else "does_not_support_gate"
    elif assay == "choice_eval":
        choice = _mapping(result.get("choice"), label=f"{relative}.choice")
        records = _integer(choice.get("records"), label="choice records", minimum=1)
        modes = _mapping(choice.get("modes"), label="choice modes")
        if records < 1 or "intact" not in modes:
            raise AssayVerificationError("Choice result has no completed intact evaluation.")
    else:
        if result.get("base_only") is not True or result.get("workspace_evaluated") is not False:
            raise AssayVerificationError("Recruitment result has unsupported evaluation scope.")
        identity = _mapping(result.get("identifiability"), label="recruitment identifiability")
        identifiable = _boolean(identity.get("passed"), label="identifiability.passed")
        ranks = result.get("ranks")
        if not isinstance(ranks, list) or not ranks:
            raise AssayVerificationError("Recruitment result has no completed ranks.")
        configured = config.get("ranks")
        observed = [item.get("rank") for item in ranks if isinstance(item, Mapping)]
        if observed != configured:
            raise AssayVerificationError("Recruitment result ranks differ from config.")
        if (
            result.get("scope") != config.get("scope")
            or result.get("target") != config.get("target")
        ):
            raise AssayVerificationError("Recruitment scope/target differ from config.")
        direction = "identifiable" if identifiable else "nonidentifying"
    # Engine-native necessity and choice outputs carry their own claim boundary.
    # Recruitment v2 does not; the enclosing verification receipt supplies the
    # non-authoritative scientific boundary for that artifact.
    if assay != "recruitment":
        _string(result.get("claim_boundary"), label=f"{relative}.claim_boundary")
    return result, record, direction


def build_receipt(repo_root: Path, run_dir: Path) -> dict[str, Any]:
    baseline = validate_baseline(repo_root, run_dir)
    required = derive_required_assays(baseline.config)
    metrics, metrics_artifact = _metric_records(baseline)
    if "eval-final" not in metrics:
        raise AssayVerificationError("Required eval-final metric is missing.")

    completed: list[str] = []
    results: dict[str, Any] = {}
    directions: dict[str, str] = {}
    artifacts = [
        _artifact(baseline.run_dir, RUN_VERIFICATION_NAME),
        _artifact(baseline.run_dir, LAUNCHED_CONFIG_NAME),
        metrics_artifact,
    ]

    line, heldout = metrics["eval-final"]
    results["heldout_eval"] = {
        "execution_integrity": "PASS",
        "evidence": _metric_evidence(line, heldout),
    }
    directions["heldout_eval"] = "reported_without_preregistered_threshold"
    completed.append("heldout_eval")

    if "amputation" in required:
        if "eval-final-amputated" not in metrics:
            raise AssayVerificationError("Required eval-final-amputated metric is missing.")
        amputated_line, amputated = metrics["eval-final-amputated"]
        _amputation_report, amputation_artifact = _validate_amputation_report(
            baseline, heldout, amputated
        )
        artifacts.append(amputation_artifact)
        delta = float(amputated["task_loss"]) - float(heldout["task_loss"])
        direction = (
            "supports_load_bearing"
            if delta > 0
            else ("opposes_load_bearing" if delta < 0 else "neutral")
        )
        results["amputation"] = {
            "execution_integrity": "PASS",
            "evidence": _metric_evidence(amputated_line, amputated),
            "task_loss_delta_amputated_minus_full": delta,
        }
        directions["amputation"] = direction
        completed.append("amputation")

    assays = _mapping(baseline.config.get("assays"), label="LAUNCHED_CONFIG.assays")
    for assay in ("necessity", "choice_eval", "recruitment"):
        if assay not in required:
            continue
        external, artifact, direction = _validate_external(
            baseline, assay, _mapping(assays.get(assay), label=f"assays.{assay}")
        )
        artifacts.append(artifact)
        results[assay] = {
            "execution_integrity": "PASS",
            "artifact": artifact["path"],
            "format": external["format"],
        }
        directions[assay] = direction
        completed.append(assay)

    if completed != required:
        raise AssayVerificationError(
            f"Required/completed assay mismatch: required={required}, completed={completed}."
        )
    artifacts.sort(key=lambda item: str(item["path"]))
    return {
        "format": RECEIPT_FORMAT,
        "verified": True,
        "verified_utc": datetime.now(UTC).isoformat(),
        "run_id": baseline.provenance["run_id"],
        "provenance": baseline.provenance,
        "required_assays": required,
        "completed_assays": completed,
        "execution_integrity": {
            "status": "PASS",
            "required_equals_completed": True,
            "assays": results,
        },
        "scientific_direction": {
            "authoritative": False,
            "not_an_integrity_gate": True,
            "by_assay": directions,
        },
        "input_bindings": {
            "run_verification_sha256": pruning.sha256_file(
                baseline.run_dir / RUN_VERIFICATION_NAME
            ),
            "launched_config_sha256": pruning.sha256_file(
                baseline.run_dir / LAUNCHED_CONFIG_NAME
            ),
            "metrics_sha256": metrics_artifact["sha256"],
            "engine_run_id": baseline.engine_run_id,
            "global_step": baseline.global_step,
        },
        "artifacts": artifacts,
        "claim_boundary": (
            "PASS verifies only that this exact verified run has all assays required by "
            "its launched config, with structurally valid, provenance-bound artifacts. "
            "Scientific direction is recorded separately and is never an integrity gate. "
            "This receipt does not establish positive effect direction, model quality, "
            "causal memory, generalization beyond the recorded held-out data, or consciousness."
        ),
    }


def _atomic_create(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise AssayVerificationError(f"Refusing to overwrite existing {path.name}.")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(pruning.canonical_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise AssayVerificationError(f"Refusing to overwrite existing {path.name}.") from exc
        temporary.unlink()
        pruning._fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def execute(repo_root: Path, run_dir: Path) -> Path:
    receipt = build_receipt(repo_root, run_dir)
    resolved_run = _inside(repo_root.expanduser().resolve(), run_dir.expanduser(), label="run")
    destination = resolved_run / RECEIPT_NAME
    _atomic_create(destination, receipt)
    return destination


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify v10 post-training assay artifacts.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument(
        "--execute",
        action="store_true",
        help=f"Atomically create {RECEIPT_NAME}; dry-run is the default.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    repo_root = Path(args.repo_root)
    run_dir = Path(args.run_dir)
    try:
        if args.execute:
            path = execute(repo_root, run_dir)
            print(json.dumps({"mode": "execute", "verified": True, "receipt": str(path)}))
        else:
            receipt = build_receipt(repo_root, run_dir)
            print(
                json.dumps(
                    {
                        "mode": "dry_run",
                        "would_write": RECEIPT_NAME,
                        "verified_inputs": True,
                        "required_assays": receipt["required_assays"],
                        "completed_assays": receipt["completed_assays"],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    except AssayVerificationError as exc:
        raise SystemExit(f"assay-verification: {exc}") from exc


if __name__ == "__main__":
    main()
