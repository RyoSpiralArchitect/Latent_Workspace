#!/usr/bin/env python3
"""Finalize the frozen V11 F1 pilot without turning integrity into a win."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FORMAT = "latent-workspace-ft-v11-f1-pilot-receipt-v1"


class FinalizeError(RuntimeError):
    """The run cannot be finalized from complete, contract-bound evidence."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FinalizeError(f"Unreadable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FinalizeError(f"Expected a JSON object: {path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise FinalizeError(
                        f"Metrics line {line_number} is not a JSON object."
                    )
                rows.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FinalizeError(f"Unreadable metrics JSONL: {path}") from exc
    if not rows:
        raise FinalizeError("Metrics JSONL is empty.")
    return rows


def inside(root: Path, path: Path, *, label: str) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise FinalizeError(f"{label} must stay inside --repo-root.") from exc
    return resolved


def regular_file(path: Path, *, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise FinalizeError(f"{label} must be a regular non-symlink file.")
    return path


def plain_directory(path: Path, *, label: str) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise FinalizeError(f"{label} must be a non-symlink directory.")
    return path


def relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def one_row(rows: list[dict[str, Any]], *, split: str, step: int) -> dict[str, Any]:
    matches = [
        row
        for row in rows
        if row.get("split") == split and int(row.get("step", -1)) == step
    ]
    if len(matches) != 1:
        raise FinalizeError(f"Expected exactly one {split} row at step {step}.")
    return matches[0]


def metric_view(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "functional_choice_loss",
        "functional_full_vocab_loss",
        "functional_query_accuracy",
        "functional_label_0_recall",
        "functional_label_1_recall",
        "functional_distinct_predicted_classes",
        "functional_prediction_entropy_nats",
        "functional_yes_minus_no_gap",
        "functional_hop_1_accuracy",
    )
    return {key: row.get(key) for key in keys}


def evaluate_f1_gates(
    step0: dict[str, Any],
    final: dict[str, Any],
    gates: dict[str, Any],
) -> list[dict[str, Any]]:
    choice_loss = float(final["functional_choice_loss"])
    accuracy = float(final["functional_query_accuracy"])
    recalls = [
        float(final["functional_label_0_recall"]),
        float(final["functional_label_1_recall"]),
    ]
    distinct = int(final["functional_distinct_predicted_classes"])
    finite = all(
        math.isfinite(float(value))
        for value in (
            choice_loss,
            accuracy,
            *recalls,
            final["functional_prediction_entropy_nats"],
            final["functional_yes_minus_no_gap"],
        )
    )
    minimum_distinct = int(gates["minimum_distinct_predicted_classes"])
    minimum_accuracy = float(gates["minimum_final_accuracy"])
    minimum_recall = float(gates["minimum_final_label_recall"])
    return [
        {
            "id": "final_choice_loss_below_step0",
            "criterion": f"< {float(step0['functional_choice_loss'])}",
            "observed": choice_loss,
            "passed": choice_loss < float(step0["functional_choice_loss"]),
        },
        {
            "id": "minimum_final_accuracy",
            "criterion": f">= {minimum_accuracy}",
            "observed": accuracy,
            "passed": accuracy >= minimum_accuracy,
        },
        {
            "id": "minimum_final_label_recall",
            "criterion": f">= {minimum_recall} for each label",
            "observed": recalls,
            "passed": min(recalls) >= minimum_recall,
        },
        {
            "id": "minimum_distinct_predicted_classes",
            "criterion": f">= {minimum_distinct}",
            "observed": distinct,
            "passed": distinct >= minimum_distinct,
        },
        {
            "id": "forbid_nonfinite_or_constant_choice",
            "criterion": "all decision diagnostics finite and choice non-constant",
            "observed": {"finite": finite, "distinct_predicted_classes": distinct},
            "passed": finite and distinct >= minimum_distinct,
        },
    ]


def atomic_write(path: Path, value: dict[str, Any], *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists() and not overwrite:
            raise FinalizeError("Output exists; pass --overwrite to replace it.")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def finalize(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = plain_directory(args.repo_root.expanduser().resolve(), label="repo root")
    run_dir = plain_directory(
        inside(repo_root, args.run_dir, label="run directory"),
        label="run directory",
    )
    contract_path = regular_file(
        inside(repo_root, args.contract, label="V11 contract"),
        label="V11 contract",
    )
    continuation_path = regular_file(
        inside(repo_root, args.continuation_contract, label="continuation contract"),
        label="continuation contract",
    )
    gate_receipt_path = regular_file(
        inside(repo_root, args.gate_receipt, label="Gate-0 receipt"),
        label="Gate-0 receipt",
    )

    contract = load_json(contract_path)
    continuation = load_json(continuation_path)
    gate_receipt = load_json(gate_receipt_path)
    expected_config = continuation["artifacts"]["F1_inline"]
    config_path = regular_file(
        (continuation_path.parent / str(expected_config["path"])).resolve(),
        label="frozen F1 config",
    )
    observed_config_sha = sha256_file(config_path)
    tracked_config = load_json(config_path)

    artifact_paths = {
        "metrics": regular_file(run_dir / "metrics.jsonl", label="metrics"),
        "resolved_config": regular_file(
            run_dir / "resolved_config.json", label="resolved config"
        ),
        "environment": regular_file(run_dir / "environment.json", label="environment"),
        "data_fingerprint": regular_file(
            run_dir / "data_fingerprint.json", label="data fingerprint"
        ),
        "optimizer_coverage": regular_file(
            run_dir / "optimizer_coverage.json", label="optimizer coverage"
        ),
        "base_update_coverage": regular_file(
            run_dir / "base_update_coverage.json", label="base update coverage"
        ),
        "offload": regular_file(
            run_dir / "gradient_accumulation_offload.json", label="offload receipt"
        ),
        "manifest": regular_file(run_dir / "final" / "manifest.json", label="manifest"),
        "experiment_config": regular_file(
            run_dir / "final" / "experiment_config.json",
            label="final experiment config",
        ),
        "completed": regular_file(run_dir / "final" / "COMPLETED", label="COMPLETED"),
    }
    metrics = load_jsonl(artifact_paths["metrics"])
    resolved_config = load_json(artifact_paths["resolved_config"])
    final_config = load_json(artifact_paths["experiment_config"])
    environment = load_json(artifact_paths["environment"])
    manifest = load_json(artifact_paths["manifest"])
    optimizer_coverage = load_json(artifact_paths["optimizer_coverage"])
    base_update_coverage = load_json(artifact_paths["base_update_coverage"])
    offload = load_json(artifact_paths["offload"])

    expected_steps = int(tracked_config["train"]["max_steps"])
    step0 = one_row(metrics, split="eval-step0", step=0)
    final = one_row(metrics, split="eval-final", step=expected_steps)
    train_steps = sorted(
        int(row["step"]) for row in metrics if row.get("split") == "train"
    )
    eval_curve = [
        {"split": str(row["split"]), "step": int(row["step"]), **metric_view(row)}
        for row in metrics
        if row.get("split") in {"eval-step0", "eval", "eval-final"}
    ]
    critical_finite = all(
        math.isfinite(float(value))
        for row in metrics
        if row.get("split") in {"train", "eval", "eval-step0", "eval-final"}
        for key in ("functional_choice_loss", "functional_query_accuracy")
        if (value := row.get(key)) is not None
    )

    selected_match = all(
        (
            resolved_config[section][field]
            == tracked_config[section][field]
        )
        for section, field in (
            ("model", "name_or_path"),
            ("model", "revision"),
            ("model", "train_mode"),
            ("data", "functional_elicitation"),
            ("data", "prompt_separator"),
            ("functional", "route_mode"),
            ("functional", "task_objective"),
            ("functional", "full_vocab_loss_weight"),
            ("train", "max_steps"),
            ("train", "gradient_accumulation_offload"),
            ("train", "gradient_accumulation_steps"),
            ("train", "learning_rate"),
            ("train", "optimizer"),
        )
    )
    base_checks = base_update_coverage.get("checks", {})
    integrity_checks = [
        {
            "id": "frozen_config_sha256",
            "passed": observed_config_sha == str(expected_config["sha256"]),
            "observed": observed_config_sha,
            "expected": str(expected_config["sha256"]),
        },
        {
            "id": "selected_runtime_config_matches_frozen_config",
            "passed": selected_match and resolved_config == final_config,
            "observed": {
                "selected_fields_match": selected_match,
                "resolved_equals_final": resolved_config == final_config,
            },
        },
        {
            "id": "manifest_config_binding",
            "passed": stable_hash(final_config) == manifest.get("config_sha256"),
            "observed": stable_hash(final_config),
            "expected": manifest.get("config_sha256"),
        },
        {
            "id": "complete_final_bundle",
            "passed": (
                manifest.get("complete") is True
                and int(manifest.get("global_step", -1)) == expected_steps
                and artifact_paths["completed"].read_text(encoding="utf-8") == "ok\n"
            ),
            "observed": {
                "complete": manifest.get("complete"),
                "global_step": manifest.get("global_step"),
            },
        },
        {
            "id": "exact_optimizer_step_sequence",
            "passed": train_steps == list(range(1, expected_steps + 1)),
            "observed": train_steps,
        },
        {
            "id": "optimizer_coverage",
            "passed": (
                optimizer_coverage.get("passed") is True
                and manifest.get("optimizer_coverage_passed") is True
            ),
            "observed": optimizer_coverage.get("checks"),
        },
        {
            "id": "base_update_coverage",
            "passed": bool(base_checks) and all(value is True for value in base_checks.values()),
            "observed": base_checks,
        },
        {
            "id": "cpu_accumulate_completed",
            "passed": (
                offload.get("status") == "completed"
                and int(offload.get("windows_started", -1)) == expected_steps
                and int(offload.get("windows_restored", -1)) == expected_steps
                and int(offload.get("live_cpu_buffer_count", -1)) == 0
                and offload.get("active_window") is None
            ),
            "observed": {
                "status": offload.get("status"),
                "windows_started": offload.get("windows_started"),
                "windows_restored": offload.get("windows_restored"),
                "microbatch_spills": offload.get("microbatch_spills"),
                "live_cpu_buffer_count": offload.get("live_cpu_buffer_count"),
            },
        },
        {
            "id": "source_digest_consistent",
            "passed": len(
                {
                    str(manifest.get("source_sha256")),
                    str(environment.get("source_sha256")),
                    str(offload.get("source_sha256")),
                }
            )
            == 1,
            "observed": {
                "manifest": manifest.get("source_sha256"),
                "environment": environment.get("source_sha256"),
                "offload": offload.get("source_sha256"),
            },
        },
        {
            "id": "finite_decision_curve",
            "passed": critical_finite,
            "observed": critical_finite,
        },
        {
            "id": "qualified_parent_gate0",
            "passed": gate_receipt.get("passed") is True
            and gate_receipt.get("status") == "qualified",
            "observed": {
                "passed": gate_receipt.get("passed"),
                "status": gate_receipt.get("status"),
            },
        },
    ]
    if not all(bool(check["passed"]) for check in integrity_checks):
        failed = [check["id"] for check in integrity_checks if not check["passed"]]
        raise FinalizeError(f"Integrity checks failed: {failed}")

    scientific_checks = evaluate_f1_gates(
        step0,
        final,
        contract["f1_positive_control_gates"],
    )
    scientific_passed = all(bool(check["passed"]) for check in scientific_checks)
    return {
        "format": FORMAT,
        "schema_version": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "condition": "F1_inline_symmetric_choice_repair",
        "integrity_status": "PASS",
        "scientific_status": "PASS" if scientific_passed else "BLOCKED",
        "o0_launch_authorized": scientific_passed,
        "question": str(contract["question"]),
        "contracts": {
            "v11": {
                "path": relative(repo_root, contract_path),
                "sha256": sha256_file(contract_path),
            },
            "symmetric_continuation": {
                "path": relative(repo_root, continuation_path),
                "sha256": sha256_file(continuation_path),
            },
            "gate0_receipt": {
                "path": relative(repo_root, gate_receipt_path),
                "sha256": sha256_file(gate_receipt_path),
            },
            "frozen_config": {
                "path": relative(repo_root, config_path),
                "sha256": observed_config_sha,
            },
        },
        "run": {
            "path": relative(repo_root, run_dir),
            "run_id": manifest.get("run_id"),
            "global_step": manifest.get("global_step"),
            "harness_version": manifest.get("harness_version"),
            "source_sha256": manifest.get("source_sha256"),
            "source_commit_at_launch": gate_receipt.get("source", {}).get("commit"),
            "optimizer": tracked_config["train"]["optimizer"],
            "gradient_accumulation_offload": offload.get("mode"),
            "peak_cpu_accumulator_bytes": offload.get("peak_cpu_accumulator_bytes"),
        },
        "artifact_hashes": {
            name: {"path": relative(repo_root, path), "sha256": sha256_file(path)}
            for name, path in artifact_paths.items()
        },
        "integrity_checks": integrity_checks,
        "scientific_checks": scientific_checks,
        "eval_curve": eval_curve,
        "step0": metric_view(step0),
        "final": metric_view(final),
        "failed_hypothesis": (
            "Changing only the functional objective from full-vocabulary CE to "
            "choice-normalized CE was sufficient to preserve or improve the "
            "qualified F1 decision boundary under the frozen full-update schedule."
        ),
        "claim_boundary": (
            "Integrity PASS proves that the frozen F1 pilot completed with bound "
            "config, source, optimizer coverage, all-base update coverage, CPU "
            "accumulation accounting, and finite recorded diagnostics. Scientific "
            "BLOCKED is a negative result: it does not authorize O0, the 57-run "
            "matrix, or 14B scaling, and it does not identify the optimizer or "
            "learning rate as the unique cause."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=Path("configs/v11/CONTRACT.json"))
    parser.add_argument(
        "--continuation-contract",
        type=Path,
        default=Path("configs/v11/CONTINUATION_AFTER_GATE0_BLOCK.json"),
    )
    parser.add_argument(
        "--gate-receipt",
        type=Path,
        default=Path("provenance/pilots/v11_gate0_symmetric/GATE0_RECEIPT.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.repo_root.expanduser().resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    try:
        output = inside(root, output, label="output")
        receipt = finalize(args)
        atomic_write(output, receipt, overwrite=args.overwrite)
    except Exception as exc:
        message = str(exc) if isinstance(exc, FinalizeError) else type(exc).__name__
        print(f"ERROR: {message}", file=os.sys.stderr)
        return 2
    print(f"WROTE {relative(root, output)}")
    print(f"scientific_status={receipt['scientific_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
