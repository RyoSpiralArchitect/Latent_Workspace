from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest
import torch

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
TESTS = REPO / "tests"
for directory in (SCRIPTS, TESTS):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

prune = importlib.import_module("prune_v10_verified_run")
runner = importlib.import_module("run_v10_matrix")
runner_fixtures = importlib.import_module("test_v10_runner")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(prune.canonical_json_bytes(value))


def artifact(path: Path, *, relative: str) -> dict[str, object]:
    return prune._regular_file_record(path, relative=relative)


def complete_assay_config() -> dict[str, object]:
    return {
        "amputation_eval": True,
        "necessity": {"enabled": False},
        "choice_eval": {"enabled": False},
        "recruitment": {"enabled": False},
    }


def _resume_comparisons(split_step: int) -> dict[str, object]:
    def base() -> dict[str, object]:
        return {
            "bitwise_exact": True,
            "tensor_count": 1,
            "total_numel": 1,
            "tensor_schema_sha256": "1" * 64,
            "changed_tensor_count": 0,
            "changed_element_count": 0,
            "performance": {"maximum_estimated_working_set_bytes": 1024},
        }

    def state() -> dict[str, object]:
        return {
            "exact": True,
            "left_sha256": "2" * 64,
            "right_sha256": "2" * 64,
            "excluded_paths": [],
        }

    def trainer(independent: bool) -> dict[str, object]:
        return {
            "exact": True,
            "independent_runs": independent,
            "excluded_paths": ["$.run_state.run_id"] if independent else [],
            "run_id_preserved": None if independent else True,
            "left_sha256": "3" * 64,
            "right_sha256": "3" * 64,
        }

    def metrics(count: int) -> dict[str, object]:
        return {"exact": True, "record_count": count, "ignored_fields": ["time"]}

    return {
        "passed": True,
        "base": {
            "save_non_perturbation_A_B": base(),
            "resume_B_C": base(),
        },
        "workspace": {
            "save_non_perturbation_A_B": state(),
            "resume_B_C": state(),
        },
        "trainer": {
            "save_non_perturbation_A_B": trainer(True),
            "resume_B_C": trainer(False),
        },
        "metrics": {
            "train_A_B": metrics(8),
            "train_B_C": metrics(4),
            "final_A_B": metrics(2),
            "final_B_C": metrics(2),
        },
        "resume_event": {"step": split_step, "run_id_preserved": True},
        "elapsed_seconds": 1.0,
    }


def add_required_evidence(run_dir: Path, provenance: dict[str, object]) -> None:
    manifest = json.loads((run_dir / "final/manifest.json").read_text(encoding="utf-8"))
    global_step = manifest["global_step"]
    engine_run_id = manifest["run_id"]
    metrics_records = [
        {
            "split": "eval-final",
            "run_id": engine_run_id,
            "step": global_step,
            "task_loss": 2.0,
            "functional_heldout_query_accuracy": 0.5,
        },
        {
            "split": "eval-final-amputated",
            "run_id": engine_run_id,
            "step": global_step,
            "task_loss": 2.0,
            "functional_heldout_query_accuracy": 0.5,
        },
    ]
    (run_dir / prune.METRICS_NAME).write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in metrics_records),
        encoding="utf-8",
    )
    write_json(
        run_dir / prune.AMPUTATION_REPORT_NAME,
        {
            "step": global_step,
            "full": {
                "task_loss": 2.0,
                "functional_heldout_query_accuracy": 0.5,
            },
            "amputated": {
                "task_loss": 2.0,
                "functional_heldout_query_accuracy": 0.5,
            },
            "task_loss_delta_full_minus_amputated": 0.0,
        },
    )
    launched = json.loads(
        (run_dir / prune.LAUNCHED_CONFIG_NAME).read_text(encoding="utf-8")
    )
    required_assays = prune._derive_required_assays(launched)
    assert required_assays == ["heldout_eval", "amputation"]
    assay_artifact_paths = [
        prune.RUN_VERIFICATION_NAME,
        prune.LAUNCHED_CONFIG_NAME,
        prune.METRICS_NAME,
        prune.AMPUTATION_REPORT_NAME,
    ]

    def metric_evidence(line: int, record: dict[str, object]) -> dict[str, object]:
        return {
            "artifact": prune.METRICS_NAME,
            "jsonl_line": line,
            "record_sha256": prune.sha256_bytes(prune.canonical_json_bytes(record)),
            "step": global_step,
            "task_loss": record["task_loss"],
            "functional_heldout_query_accuracy": record[
                "functional_heldout_query_accuracy"
            ],
        }

    assay_receipt = {
        "format": prune.ASSAY_VERIFICATION_FORMAT,
        "verified": True,
        "verified_utc": "2026-08-22T00:00:00+00:00",
        "run_id": provenance["run_id"],
        "provenance": provenance,
        "required_assays": required_assays,
        "completed_assays": required_assays,
        "execution_integrity": {
            "status": "PASS",
            "required_equals_completed": True,
            "assays": {
                "heldout_eval": {
                    "execution_integrity": "PASS",
                    "evidence": metric_evidence(1, metrics_records[0]),
                },
                "amputation": {
                    "execution_integrity": "PASS",
                    "evidence": metric_evidence(2, metrics_records[1]),
                    "task_loss_delta_amputated_minus_full": 0.0,
                },
            },
        },
        "scientific_direction": {
            "authoritative": False,
            "not_an_integrity_gate": True,
            "by_assay": {
                "heldout_eval": "reported_without_preregistered_threshold",
                "amputation": "neutral",
            },
        },
        "input_bindings": {
            "run_verification_sha256": prune.sha256_file(
                run_dir / prune.RUN_VERIFICATION_NAME
            ),
            "launched_config_sha256": prune.sha256_file(
                run_dir / prune.LAUNCHED_CONFIG_NAME
            ),
            "metrics_sha256": prune.sha256_file(run_dir / prune.METRICS_NAME),
            "engine_run_id": engine_run_id,
            "global_step": global_step,
        },
        "artifacts": [
            artifact(run_dir / relative, relative=relative)
            for relative in assay_artifact_paths
        ],
        "claim_boundary": "Synthetic producer-shaped assay integrity receipt.",
    }
    write_json(run_dir / prune.ASSAY_VERIFICATION_NAME, assay_receipt)

    verification_sha256 = prune.sha256_file(run_dir / prune.RUN_VERIFICATION_NAME)
    verification = json.loads(
        (run_dir / prune.RUN_VERIFICATION_NAME).read_text(encoding="utf-8")
    )
    final_inventory = verification["final_inventory"]
    split_step = max(1, int(global_step) // 2)
    provenance_hashes = provenance["hashes"]
    source_hashes = provenance_hashes.get("source_files_sha256", {})
    engine_sha256 = source_hashes.get(
        "src/latent_workspace_ft_v10/engine.py", "6" * 64
    )
    baseline_allocator = verification["allocator_environment"]
    control_allocator = {
        **baseline_allocator,
        "path": "runs/v10/resume_equivalence/control_uninterrupted/environment.json",
    }
    resumed_allocator = {
        **baseline_allocator,
        "path": "runs/v10/resume_equivalence/resumed_from_split/environment.json",
    }
    for name in (
        prune.RESUME_CONTROL_ENVIRONMENT_NAME,
        prune.RESUME_RESUMED_ENVIRONMENT_NAME,
    ):
        (run_dir / name).write_bytes((run_dir / prune.ENVIRONMENT_NAME).read_bytes())
    control_output = "runs/v10/resume_equivalence/control_uninterrupted"
    resumed_output = "runs/v10/resume_equivalence/resumed_from_split"
    baseline_gradient_offload = verification["gradient_accumulation_offload"]
    resume_signature = baseline_gradient_offload["resume_signature"]
    checkpoint_inventory = final_inventory
    checkpoint_manifest_record = next(
        item for item in checkpoint_inventory if item["path"] == "manifest.json"
    )
    resumed_checkpoint = {
        "scope": "external",
        "basename": f"checkpoint-{split_step}",
        "manifest_sha256": checkpoint_manifest_record["sha256"],
        "manifest_identity": {
            "run_id": "synthetic-resume-engine-run",
            "global_step": split_step,
            "source_sha256": engine_sha256,
            "resume_signature": resume_signature,
        },
        "bundle_inventory_sha256": prune.sha256_bytes(
            json.dumps(
                checkpoint_inventory,
                sort_keys=True,
                ensure_ascii=False,
            ).encode("utf-8")
        ),
        "file_count": len(checkpoint_inventory),
        "logical_bytes": sum(int(item["bytes"]) for item in checkpoint_inventory),
    }
    parameter_count = baseline_gradient_offload["trainable_parameter_count"]
    parameter_numel = baseline_gradient_offload[
        "trainable_parameter_total_numel"
    ]
    gradient_capacity_bytes = baseline_gradient_offload[
        "trainable_gradient_capacity_bytes"
    ]
    runner_fixtures.write_synthetic_gradient_offload_receipt(
        run_dir / prune.RESUME_CONTROL_GRADIENT_OFFLOAD_NAME,
        run_id="synthetic-resume-engine-run",
        source_sha256=engine_sha256,
        resume_signature=resume_signature,
        initial_step=0,
        final_step=global_step,
        accumulation_steps=8,
        parameter_count=parameter_count,
        parameter_numel=parameter_numel,
        gradient_capacity_bytes=gradient_capacity_bytes,
    )
    runner_fixtures.write_synthetic_gradient_offload_receipt(
        run_dir / prune.RESUME_RESUMED_GRADIENT_OFFLOAD_NAME,
        run_id="synthetic-resume-engine-run",
        source_sha256=engine_sha256,
        resume_signature=resume_signature,
        initial_step=split_step,
        final_step=global_step,
        accumulation_steps=8,
        parameter_count=parameter_count,
        parameter_numel=parameter_numel,
        gradient_capacity_bytes=gradient_capacity_bytes,
        initial_checkpoint=resumed_checkpoint,
    )
    control_gradient_offload = (
        prune.validate_gradient_accumulation_offload_receipt_file(
            run_dir / prune.RESUME_CONTROL_GRADIENT_OFFLOAD_NAME,
            receipt_path=(
                f"{control_output}/{prune.GRADIENT_ACCUMULATION_OFFLOAD_RECEIPT_NAME}"
            ),
            expected_run_id="synthetic-resume-engine-run",
            expected_source_sha256=engine_sha256,
            expected_resume_signature=resume_signature,
            expected_initial_global_step=0,
            expected_final_global_step=global_step,
            expected_configured_accumulation_steps=8,
            expected_initial_resume_checkpoint=None,
            expected_trainable_parameter_count=parameter_count,
            expected_trainable_parameter_total_numel=parameter_numel,
        )
    )
    resumed_gradient_offload = (
        prune.validate_gradient_accumulation_offload_receipt_file(
            run_dir / prune.RESUME_RESUMED_GRADIENT_OFFLOAD_NAME,
            receipt_path=(
                f"{resumed_output}/{prune.GRADIENT_ACCUMULATION_OFFLOAD_RECEIPT_NAME}"
            ),
            expected_run_id="synthetic-resume-engine-run",
            expected_source_sha256=engine_sha256,
            expected_resume_signature=resume_signature,
            expected_initial_global_step=split_step,
            expected_final_global_step=global_step,
            expected_configured_accumulation_steps=8,
            expected_initial_resume_checkpoint=resumed_checkpoint,
            expected_trainable_parameter_count=parameter_count,
            expected_trainable_parameter_total_numel=parameter_numel,
        )
    )
    gradient_receipts = {
        "baseline": baseline_gradient_offload,
        "control": control_gradient_offload,
        "resumed": resumed_gradient_offload,
    }
    gradient_semantic_identities = {
        name: {
            field: binding[field]
            for field in prune.GRADIENT_OFFLOAD_SEMANTIC_FIELDS
        }
        for name, binding in gradient_receipts.items()
    }
    baseline_bundle_identity = dict(verification["bundle_identity"])
    baseline_bundle_identity["bundle_path"] = (
        f"{provenance['output_dir']}/final"
    )
    control_bundle_identity = dict(baseline_bundle_identity)
    control_bundle_identity["bundle_path"] = f"{control_output}/final"
    control_bundle_identity["run_id"] = "synthetic-resume-engine-run"
    resumed_bundle_identity = dict(control_bundle_identity)
    resumed_bundle_identity["bundle_path"] = f"{resumed_output}/final"
    bundle_identities = {
        "baseline": baseline_bundle_identity,
        "control": control_bundle_identity,
        "resumed": resumed_bundle_identity,
    }
    bundle_cross_run_fields = (
        "resume_signature",
        "structural_resume_signature",
        "world_size",
        "data_fingerprint_sha256",
    )
    bundle_semantic_identities = {
        name: {
            field: binding[field]
            for field in bundle_cross_run_fields
        }
        for name, binding in bundle_identities.items()
    }
    identity_keys = (
        "configured",
        "observed_primary",
        "observed_legacy_alias",
        "observed_hip_legacy_alias",
        "observed_caching_allocator_disable",
        "active_backend",
        "parsed_settings",
        "snapshot_settings",
        "runtime_identity",
    )
    allocator_identity = {
        key: baseline_allocator.get(key) for key in identity_keys
    }
    resume_output = run_dir / prune.RESUME_EQUIVALENCE_NAME
    write_json(
        resume_output,
        {
            "format": prune.RESUME_EQUIVALENCE_FORMAT,
            "passed": True,
            "created_utc": "2026-08-22T00:00:00+00:00",
            "design": {
                "baseline_A": provenance["output_dir"],
                "control_B": control_output,
                "resumed_C": resumed_output,
                "split_step": split_step,
                "total_steps": global_step,
                "scheduler_horizon_held_fixed": True,
                "comparison": "bitwise_exact_zero_tolerance",
            },
            "input_bindings": {
                "baseline_RUN_VERIFICATION_sha256": verification_sha256,
                "baseline_LAUNCHED_CONFIG_sha256": prune.sha256_file(
                    run_dir / prune.LAUNCHED_CONFIG_NAME
                ),
                "control_config_sha256": "4" * 64,
                "resumed_config_sha256": "5" * 64,
                "checkpoint_resume_signature": resume_signature,
                "validated_baseline_provenance_hashes": provenance["hashes"],
            },
            "environment": {
                "engine_sha256": engine_sha256,
                "matrix_runner_sha256": provenance_hashes["runner_sha256"],
                "resume_harness_sha256": "7" * 64,
                "cuda_available": True,
            },
            "allocator_environment_bindings": {
                "control": control_allocator,
                "resumed": resumed_allocator,
            },
            "allocator_runtime_equivalence": {
                "passed": True,
                "comparison": "selected_runtime_fields_exact",
                "all_equal": True,
                "identities": {
                    "baseline": allocator_identity,
                    "control": allocator_identity,
                    "resumed": allocator_identity,
                },
                "excluded_dynamic_fields": [
                    "path",
                    "sha256",
                    "cuda_memory_allocated_bytes",
                    "cuda_memory_reserved_bytes",
                ],
            },
            "gradient_accumulation_offload_binding": {
                "passed": True,
                "required": prune.GRADIENT_ACCUMULATION_OFFLOAD,
                "all_equal": True,
                "observed": {
                    "baseline": prune.GRADIENT_ACCUMULATION_OFFLOAD,
                    "control": prune.GRADIENT_ACCUMULATION_OFFLOAD,
                    "resumed": prune.GRADIENT_ACCUMULATION_OFFLOAD,
                },
            },
            "bundle_identity_bindings": {
                "passed": True,
                "bundles": bundle_identities,
                "exact_cross_run_fields": list(bundle_cross_run_fields),
                "semantic_identities": bundle_semantic_identities,
                "all_semantic_identities_equal": True,
                "control_resume_run_id_preserved": True,
            },
            "gradient_accumulation_offload_receipt_bindings": {
                "passed": True,
                "receipts": gradient_receipts,
                "expected_step_ranges": {
                    "baseline": {
                        "initial_global_step": 0,
                        "final_global_step": global_step,
                    },
                    "control": {
                        "initial_global_step": 0,
                        "final_global_step": global_step,
                    },
                    "resumed": {
                        "initial_global_step": split_step,
                        "final_global_step": global_step,
                    },
                },
                "exact_semantic_fields": list(
                    prune.GRADIENT_OFFLOAD_SEMANTIC_FIELDS
                ),
                "semantic_identities": gradient_semantic_identities,
                "all_semantic_identities_equal": True,
                "control_resume_run_id_preserved": True,
            },
            "preflight": {"world_size": 1, "cuda_device": "synthetic-cuda"},
            "launches": {
                "control": {"returncode": 0},
                "resumed": {"returncode": 0},
            },
            "artifact_inventories": {
                "checkpoint_B_split": final_inventory,
                "final_A": final_inventory,
                "final_B": final_inventory,
                "final_C": final_inventory,
            },
            "comparisons": _resume_comparisons(split_step),
            "performance_boundary": {
                "max_estimated_comparison_working_set_bytes": 1024,
                "training_optimizer_steps_executed": global_step + global_step - split_step,
                "comparison_scope": "same_host_same_single_gpu_same_source_and_runtime",
            },
            "claim_boundary": "Synthetic producer-shaped exact resume evidence.",
        },
    )
    write_json(
        run_dir / prune.RESUME_VERIFICATION_NAME,
        {
            "format": prune.RESUME_VERIFICATION_FORMAT,
            "verified": True,
            "run_id": provenance["run_id"],
            "provenance": provenance,
            "comparison": {
                "mode": "bitwise_exact_zero_tolerance",
                "passed": True,
                "equivalence_format": prune.RESUME_EQUIVALENCE_FORMAT,
                "equivalence_artifact": prune.RESUME_EQUIVALENCE_NAME,
                "equivalence_sha256": prune.sha256_file(resume_output),
                "baseline_run_verification_sha256": verification_sha256,
            },
            "artifacts": [
                artifact(resume_output, relative=prune.RESUME_EQUIVALENCE_NAME),
                artifact(
                    run_dir / prune.RESUME_CONTROL_ENVIRONMENT_NAME,
                    relative=prune.RESUME_CONTROL_ENVIRONMENT_NAME,
                ),
                artifact(
                    run_dir / prune.RESUME_RESUMED_ENVIRONMENT_NAME,
                    relative=prune.RESUME_RESUMED_ENVIRONMENT_NAME,
                ),
                artifact(
                    run_dir / prune.RESUME_CONTROL_GRADIENT_OFFLOAD_NAME,
                    relative=prune.RESUME_CONTROL_GRADIENT_OFFLOAD_NAME,
                ),
                artifact(
                    run_dir / prune.RESUME_RESUMED_GRADIENT_OFFLOAD_NAME,
                    relative=prune.RESUME_RESUMED_GRADIENT_OFFLOAD_NAME,
                ),
            ],
        },
    )


def add_checkpoint(run_dir: Path, step: int) -> Path:
    checkpoint = run_dir / f"checkpoint-{step}"
    base = checkpoint / "base_model"
    base.mkdir(parents=True)
    (base / "model.safetensors").write_bytes(b"checkpoint-weights-" + bytes([step]))
    write_json(base / "config.json", {"model_type": "synthetic"})
    (checkpoint / "COMPLETED").write_text("ok\n", encoding="utf-8")
    write_json(
        checkpoint / "manifest.json",
        {"format": "latent-workspace-ft-bundle-v4", "complete": True, "global_step": step},
    )
    write_json(checkpoint / "experiment_config.json", {"train": {"max_steps": 8}})
    (checkpoint / "workspace_state.pt").write_bytes(b"checkpoint-workspace")
    (checkpoint / "trainer_state.pt").write_bytes(b"checkpoint-trainer")
    return checkpoint


def make_verified_run(
    tmp_path: Path,
    *,
    with_checkpoint: bool = True,
) -> tuple[Path, dict[str, object], Path]:
    repo = tmp_path / "repo"
    run_dir = repo / "runs/v10/smoke/F0_query_only/seed_42"
    final = run_dir / "final"
    base = final / "base_model"
    base.mkdir(parents=True)
    (base / "model.safetensors").write_bytes(b"verified-final-weights")
    write_json(base / "config.json", {"model_type": "synthetic"})
    write_json(
        base / "model.safetensors.index.json",
        {"weight_map": {"weight": "model.safetensors"}},
    )
    (final / "COMPLETED").write_text("ok\n", encoding="utf-8")
    experiment_config = {"train": {"max_steps": 8}}
    resume_signature = "e" * 64
    structural_resume_signature = "f" * 64
    data_fingerprint = {"files": [{"sha256": "9" * 64}]}
    write_json(
        final / "manifest.json",
        {
            "format": "latent-workspace-ft-bundle-v4",
            "complete": True,
            "global_step": 8,
            "run_id": "synthetic-engine-run",
            "source_sha256": "6" * 64,
            "resume_signature": resume_signature,
            "structural_resume_signature": structural_resume_signature,
            "config_sha256": prune._stable_json_sha256(experiment_config),
            "world_size": 1,
            "data_fingerprint": data_fingerprint,
        },
    )
    write_json(final / "experiment_config.json", experiment_config)
    write_json(
        final / "optimizer_coverage.json",
        {
            "passed": True,
            "model_trainable_unique_physical_parameters": 1,
            "model_trainable_numel": 1,
        },
    )
    write_json(final / "base_update_coverage.json", {"passed": True})
    (final / "workspace_state.pt").write_bytes(b"workspace-retained")
    torch.save(
        {
            "run_state": {
                "run_id": "synthetic-engine-run",
                "global_step": 8,
            },
            "global_step": 8,
            "resume_signature": resume_signature,
            "structural_resume_signature": structural_resume_signature,
            "world_size": 1,
            "data_fingerprint": data_fingerprint,
        },
        final / "trainer_state.pt",
    )

    launched = {
        "train": {
            "seed": 42,
            "max_steps": 8,
            "gradient_accumulation_steps": 8,
            "output_dir": "runs/v10/smoke/F0_query_only/seed_42",
            "cuda_allocator_conf": runner.CUDA_ALLOCATOR_CONF,
            "gradient_accumulation_offload": (
                runner.GRADIENT_ACCUMULATION_OFFLOAD
            ),
        },
        "assays": complete_assay_config(),
    }
    write_json(run_dir / prune.LAUNCHED_CONFIG_NAME, launched)
    provenance: dict[str, object] = {
        "profile": "smoke",
        "run_id": "F0_query_only/seed_42",
        "condition": "F0_query_only",
        "seed": 42,
        "max_steps": 8,
        "output_dir": "runs/v10/smoke/F0_query_only/seed_42",
        "runtime_policy": {
            "gradient_accumulation_offload": (
                runner.GRADIENT_ACCUMULATION_OFFLOAD
            )
        },
        "hashes": {
            "contract_sha256": "a" * 64,
            "source_tree_sha256": "b" * 64,
            "runner_sha256": "c" * 64,
            "source_files_sha256": {
                "src/latent_workspace_ft_v10/engine.py": "6" * 64
            },
            "contract_data_sha256": {"eval": "d" * 64},
            "materialized_config_sha256": prune.sha256_file(
                run_dir / prune.LAUNCHED_CONFIG_NAME
            ),
        },
    }
    delta_path = run_dir / prune.FULL_UPDATE_DELTA_NAME
    write_json(delta_path, {"format": "synthetic-delta", "passed": True})
    final_inventory, _directories = prune._directory_layout(final)
    bundle_identity = prune.validate_bundle_identity(
        final,
        bundle_path="final",
        expected_global_step=8,
    )
    environment = {
        "harness_version": "synthetic-harness",
        "python": "synthetic-python",
        "platform": "synthetic-platform",
        "hostname": "synthetic-host",
        "torch": "synthetic-torch",
        "cuda_runtime": "synthetic-cuda",
        "cudnn": 1,
        "source_sha256": "6" * 64,
        "cuda_devices": [{"index": 0, "name": "synthetic-gpu"}],
        "transformers": "synthetic-transformers",
        "peft": None,
        "safetensors": "synthetic-safetensors",
        "pytorch_alloc_conf": runner.CUDA_ALLOCATOR_CONF,
        "pytorch_cuda_alloc_conf_legacy": None,
        "pytorch_hip_alloc_conf_legacy": None,
        "pytorch_no_cuda_memory_caching": None,
        "allocator_backend": "native",
        "allocator_settings": runner.CUDA_ALLOCATOR_CONF,
        "allocator_initialized": True,
        "allocator_snapshot_settings": {"expandable_segments": True},
        "cuda_memory_allocated_bytes": 1,
        "cuda_memory_reserved_bytes": 1,
    }
    write_json(run_dir / prune.ENVIRONMENT_NAME, environment)
    allocator_binding = runner.validate_allocator_environment_file(
        run_dir / prune.ENVIRONMENT_NAME,
        configured=runner.CUDA_ALLOCATOR_CONF,
        expected_source_sha256="6" * 64,
        label="synthetic prune baseline",
        receipt_path=prune.ENVIRONMENT_NAME,
    )
    runner_fixtures.write_synthetic_gradient_offload_receipt(
        run_dir / prune.GRADIENT_ACCUMULATION_OFFLOAD_RECEIPT_NAME,
        run_id="synthetic-engine-run",
        source_sha256="6" * 64,
        resume_signature="e" * 64,
        initial_step=0,
        final_step=8,
        accumulation_steps=8,
        parameter_count=1,
        parameter_numel=1,
        gradient_capacity_bytes=4,
    )
    gradient_offload_binding = (
        prune.validate_gradient_accumulation_offload_receipt_file(
            run_dir / prune.GRADIENT_ACCUMULATION_OFFLOAD_RECEIPT_NAME,
            receipt_path=prune.GRADIENT_ACCUMULATION_OFFLOAD_RECEIPT_NAME,
            expected_run_id="synthetic-engine-run",
            expected_source_sha256="6" * 64,
            expected_resume_signature="e" * 64,
            expected_initial_global_step=0,
            expected_final_global_step=8,
            expected_configured_accumulation_steps=8,
            expected_initial_resume_checkpoint=None,
            expected_trainable_parameter_count=1,
            expected_trainable_parameter_total_numel=1,
        )
    )
    write_json(
        run_dir / prune.RUN_VERIFICATION_NAME,
        {
            "format": prune.RUN_VERIFICATION_FORMAT,
            "verified": True,
            "provenance": provenance,
            "final_manifest": json.loads(
                (final / "manifest.json").read_text(encoding="utf-8")
            ),
            "full_update_delta": {
                "path": prune.FULL_UPDATE_DELTA_NAME,
                "sha256": prune.sha256_file(delta_path),
                "passed": True,
            },
            "allocator_environment": allocator_binding,
            "gradient_accumulation_offload": gradient_offload_binding,
            "bundle_identity": bundle_identity,
            "final_inventory": final_inventory,
        },
    )
    add_required_evidence(run_dir, provenance)
    (run_dir / "keep_me.txt").write_text("unrelated sibling\n", encoding="utf-8")

    if with_checkpoint:
        add_checkpoint(run_dir, 4)
        write_json(
            run_dir / "latest_checkpoint.json",
            {"path": "checkpoint-4", "global_step": 4},
        )
        write_json(
            run_dir / "best_checkpoint.json",
            {"path": "checkpoint-4", "step": 4, "metric": "task_loss"},
        )
        write_json(
            run_dir / "phase-boundary-step-4.json",
            {"checkpoint": "checkpoint-4", "step": 4, "from": "a", "to": "b"},
        )
    return run_dir, provenance, tmp_path / "compact-export"


def test_dry_run_default_is_byte_for_byte_read_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir, _provenance, export_root = make_verified_run(tmp_path)
    before, before_directories = prune._directory_layout(run_dir)

    assert prune.main(["--run-dir", str(run_dir)]) == 0

    after, after_directories = prune._directory_layout(run_dir)
    assert after == before
    assert after_directories == before_directories
    assert not export_root.exists()
    assert not (run_dir / prune.PRUNE_INTENT_NAME).exists()
    assert not (run_dir / prune.PRUNE_RECEIPT_NAME).exists()
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "dry_run"
    assert output["would_execute"] is False
    assert {item["source"] for item in output["targets"]} == {
        "final/base_model",
        "checkpoint-4",
        "latest_checkpoint.json",
        "best_checkpoint.json",
        "phase-boundary-step-4.json",
    }


@pytest.mark.parametrize(
    "missing",
    [prune.ASSAY_VERIFICATION_NAME, prune.RESUME_VERIFICATION_NAME],
)
def test_missing_assay_or_resume_blocks_before_intent(
    tmp_path: Path,
    missing: str,
) -> None:
    run_dir, _provenance, export_root = make_verified_run(tmp_path)
    (run_dir / missing).unlink()

    with pytest.raises(prune.PruneError):
        prune.execute_prune(
            run_dir,
            reason="capacity qualification",
            compact_export_root=export_root,
        )

    assert (run_dir / "final/base_model/model.safetensors").is_file()
    assert (run_dir / "checkpoint-4/base_model/model.safetensors").is_file()
    assert not (run_dir / prune.PRUNE_INTENT_NAME).exists()
    assert not export_root.exists()


@pytest.mark.parametrize(
    "missing",
    [
        prune.RESUME_CONTROL_ENVIRONMENT_NAME,
        prune.RESUME_RESUMED_ENVIRONMENT_NAME,
    ],
)
def test_missing_published_resume_environment_blocks_before_intent(
    tmp_path: Path,
    missing: str,
) -> None:
    run_dir, _provenance, export_root = make_verified_run(tmp_path)
    (run_dir / missing).unlink()

    with pytest.raises(prune.PruneError):
        prune.execute_prune(
            run_dir,
            reason="missing resume child environment",
            compact_export_root=export_root,
        )

    assert (run_dir / "final/base_model/model.safetensors").is_file()
    assert not (run_dir / prune.PRUNE_INTENT_NAME).exists()
    assert not export_root.exists()


@pytest.mark.parametrize("mutation", ["launched", "provenance"])
def test_root_accumulation_offload_binding_fails_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    run_dir, _provenance, _export_root = make_verified_run(tmp_path)
    verification = json.loads(
        (run_dir / prune.RUN_VERIFICATION_NAME).read_text(encoding="utf-8")
    )
    provenance = verification["provenance"]
    if mutation == "launched":
        launched_path = run_dir / prune.LAUNCHED_CONFIG_NAME
        launched = json.loads(launched_path.read_text(encoding="utf-8"))
        launched["train"]["gradient_accumulation_offload"] = "none"
        write_json(launched_path, launched)
    else:
        provenance["runtime_policy"]["gradient_accumulation_offload"] = "none"

    with pytest.raises(prune.PruneError, match="offload binding is not exact"):
        prune._validate_allocator_environment_binding(
            run_dir,
            verification,
            provenance,
        )


def test_producer_shaped_evidence_builds_a_prune_plan(tmp_path: Path) -> None:
    run_dir, provenance, _export_root = make_verified_run(tmp_path)

    plan = prune.build_prune_plan(run_dir)

    assert plan["provenance"] == provenance
    assert plan["preconditions"]["assay_required"] == [
        "amputation",
        "heldout_eval",
    ]
    assert plan["preconditions"]["resume_comparison_passed"] is True
    compact_paths = {
        item["path"] for item in plan["compact_evidence_inventory"]
    }
    assert prune.RESUME_CONTROL_ENVIRONMENT_NAME in compact_paths
    assert prune.RESUME_RESUMED_ENVIRONMENT_NAME in compact_paths
    assert prune.GRADIENT_ACCUMULATION_OFFLOAD_RECEIPT_NAME in compact_paths
    assert prune.RESUME_CONTROL_GRADIENT_OFFLOAD_NAME in compact_paths
    assert prune.RESUME_RESUMED_GRADIENT_OFFLOAD_NAME in compact_paths


def test_assay_required_set_is_recomputed_from_launched_config(tmp_path: Path) -> None:
    run_dir, _provenance, _export_root = make_verified_run(tmp_path)
    receipt_path = run_dir / prune.ASSAY_VERIFICATION_NAME
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["required_assays"] = ["heldout_eval"]
    receipt["completed_assays"] = ["heldout_eval"]
    receipt["execution_integrity"]["assays"] = {
        "heldout_eval": receipt["execution_integrity"]["assays"]["heldout_eval"]
    }
    receipt["scientific_direction"]["by_assay"] = {
        "heldout_eval": receipt["scientific_direction"]["by_assay"]["heldout_eval"]
    }
    receipt["artifacts"] = [
        item
        for item in receipt["artifacts"]
        if item["path"] != prune.AMPUTATION_REPORT_NAME
    ]
    write_json(receipt_path, receipt)

    with pytest.raises(prune.PruneError, match="differ from LAUNCHED_CONFIG"):
        prune.build_prune_plan(run_dir)
    assert not (run_dir / prune.PRUNE_INTENT_NAME).exists()


@pytest.mark.parametrize("mutation", ["status", "assay_keys", "input", "artifact"])
def test_assay_integrity_bindings_fail_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    run_dir, _provenance, _export_root = make_verified_run(tmp_path)
    receipt_path = run_dir / prune.ASSAY_VERIFICATION_NAME
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if mutation == "status":
        receipt["execution_integrity"]["status"] = "FAIL"
    elif mutation == "assay_keys":
        receipt["execution_integrity"]["assays"].pop("amputation")
    elif mutation == "input":
        receipt["input_bindings"]["metrics_sha256"] = "f" * 64
    else:
        metrics = next(
            item for item in receipt["artifacts"] if item["path"] == prune.METRICS_NAME
        )
        metrics["sha256"] = "f" * 64
    write_json(receipt_path, receipt)

    with pytest.raises(prune.PruneError):
        prune.build_prune_plan(run_dir)
    assert not (run_dir / prune.PRUNE_INTENT_NAME).exists()


def rewrite_resume_equivalence(run_dir: Path, receipt: dict[str, object]) -> None:
    result_path = run_dir / prune.RESUME_EQUIVALENCE_NAME
    write_json(result_path, receipt)
    wrapper_path = run_dir / prune.RESUME_VERIFICATION_NAME
    wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
    wrapper["comparison"]["equivalence_sha256"] = prune.sha256_file(result_path)
    wrapper["artifacts"] = [
        artifact(result_path, relative=prune.RESUME_EQUIVALENCE_NAME),
        artifact(
            run_dir / prune.RESUME_CONTROL_ENVIRONMENT_NAME,
            relative=prune.RESUME_CONTROL_ENVIRONMENT_NAME,
        ),
        artifact(
            run_dir / prune.RESUME_RESUMED_ENVIRONMENT_NAME,
            relative=prune.RESUME_RESUMED_ENVIRONMENT_NAME,
        ),
        artifact(
            run_dir / prune.RESUME_CONTROL_GRADIENT_OFFLOAD_NAME,
            relative=prune.RESUME_CONTROL_GRADIENT_OFFLOAD_NAME,
        ),
        artifact(
            run_dir / prune.RESUME_RESUMED_GRADIENT_OFFLOAD_NAME,
            relative=prune.RESUME_RESUMED_GRADIENT_OFFLOAD_NAME,
        ),
    ]
    write_json(wrapper_path, wrapper)


def test_minimal_handwritten_resume_receipt_is_rejected(tmp_path: Path) -> None:
    run_dir, _provenance, _export_root = make_verified_run(tmp_path)
    verification_sha256 = prune.sha256_file(run_dir / prune.RUN_VERIFICATION_NAME)
    minimal = {
        "format": prune.RESUME_EQUIVALENCE_FORMAT,
        "passed": True,
        "design": {"comparison": "bitwise_exact_zero_tolerance"},
        "input_bindings": {
            "baseline_RUN_VERIFICATION_sha256": verification_sha256
        },
    }
    rewrite_resume_equivalence(run_dir, minimal)

    with pytest.raises(prune.PruneError, match="design keys are not exact"):
        prune.build_prune_plan(run_dir)
    assert not (run_dir / prune.PRUNE_INTENT_NAME).exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "comparison_group",
        "comparison_pass",
        "provenance_hashes",
        "final_a",
        "accumulation_offload",
    ],
)
def test_resume_detail_and_provenance_bindings_fail_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    run_dir, _provenance, _export_root = make_verified_run(tmp_path)
    result_path = run_dir / prune.RESUME_EQUIVALENCE_NAME
    receipt = json.loads(result_path.read_text(encoding="utf-8"))
    if mutation == "comparison_group":
        receipt["comparisons"].pop("trainer")
    elif mutation == "comparison_pass":
        receipt["comparisons"]["base"]["resume_B_C"]["bitwise_exact"] = False
    elif mutation == "provenance_hashes":
        receipt["input_bindings"]["validated_baseline_provenance_hashes"] = {
            "runner_sha256": "f" * 64
        }
    elif mutation == "final_a":
        receipt["artifact_inventories"]["final_A"] = receipt["artifact_inventories"][
            "final_A"
        ][1:]
    else:
        receipt["gradient_accumulation_offload_binding"]["observed"]["control"] = (
            "none"
        )
    rewrite_resume_equivalence(run_dir, receipt)

    with pytest.raises(prune.PruneError):
        prune.build_prune_plan(run_dir)
    assert not (run_dir / prune.PRUNE_INTENT_NAME).exists()


@pytest.mark.parametrize("mutation", ["run_id", "artifact_hash"])
def test_resume_bundle_identity_chain_fails_closed_before_prune(
    tmp_path: Path,
    mutation: str,
) -> None:
    run_dir, _provenance, _export_root = make_verified_run(tmp_path)
    result_path = run_dir / prune.RESUME_EQUIVALENCE_NAME
    receipt = json.loads(result_path.read_text(encoding="utf-8"))
    resumed = receipt["bundle_identity_bindings"]["bundles"]["resumed"]
    if mutation == "run_id":
        resumed["run_id"] = "split-run-id"
    else:
        resumed["artifacts"]["trainer_state.pt"]["sha256"] = "0" * 64
    rewrite_resume_equivalence(run_dir, receipt)

    with pytest.raises(prune.PruneError, match="[Bb]undle identity"):
        prune.build_prune_plan(run_dir)
    assert not (run_dir / prune.PRUNE_INTENT_NAME).exists()


@pytest.mark.parametrize(
    "mutation",
    ["published_content", "recorded_check", "binding_path", "published_source"],
)
def test_published_resume_environment_content_is_recomputed_fail_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    run_dir, _provenance, _export_root = make_verified_run(tmp_path)
    result_path = run_dir / prune.RESUME_EQUIVALENCE_NAME
    receipt = json.loads(result_path.read_text(encoding="utf-8"))
    binding = receipt["allocator_environment_bindings"]["control"]
    environment_path = run_dir / prune.RESUME_CONTROL_ENVIRONMENT_NAME

    if mutation in {"published_content", "published_source"}:
        environment = json.loads(environment_path.read_text(encoding="utf-8"))
        if mutation == "published_content":
            environment["pytorch_alloc_conf"] = "backend:native"
        else:
            environment["source_sha256"] = "f" * 64
        write_json(environment_path, environment)
        # Keep the wrapper inventory and binding hash self-consistent so the
        # pruner must inspect the retained JSON content, not only its digest.
        binding["sha256"] = prune.sha256_file(environment_path)
    elif mutation == "recorded_check":
        binding["checks"]["primary_environment_exact"] = False
    else:
        binding["path"] = (
            "runs/v10/resume_equivalence/resumed_from_split/environment.json"
        )
    rewrite_resume_equivalence(run_dir, receipt)

    with pytest.raises(prune.PruneError):
        prune.build_prune_plan(run_dir)
    assert not (run_dir / prune.PRUNE_INTENT_NAME).exists()


@pytest.mark.parametrize(
    "field",
    [
        "manifest_sha256",
        "bundle_inventory_sha256",
        "file_count",
        "logical_bytes",
    ],
)
def test_published_resumed_checkpoint_descriptor_is_cross_bound_to_inventory(
    tmp_path: Path,
    field: str,
) -> None:
    run_dir, _provenance, _export_root = make_verified_run(tmp_path)
    result_path = run_dir / prune.RESUME_EQUIVALENCE_NAME
    receipt = json.loads(result_path.read_text(encoding="utf-8"))
    recorded = receipt["gradient_accumulation_offload_receipt_bindings"][
        "receipts"
    ]["resumed"]
    child_path = run_dir / prune.RESUME_RESUMED_GRADIENT_OFFLOAD_NAME
    child = json.loads(child_path.read_text(encoding="utf-8"))
    descriptor = child["segments"][0]["resume_checkpoint"]
    descriptor[field] = (
        "0" * 64
        if field in {"manifest_sha256", "bundle_inventory_sha256"}
        else int(descriptor[field]) + 1
    )
    child["receipt_sha256"] = (
        prune.gradient_accumulation_offload_receipt_self_hash(child)
    )
    write_json(child_path, child)
    recomputed = prune.validate_gradient_accumulation_offload_receipt_file(
        child_path,
        receipt_path=recorded["path"],
        expected_run_id=recorded["run_id"],
        expected_source_sha256=recorded["source_sha256"],
        expected_resume_signature=recorded["resume_signature"],
        expected_initial_global_step=recorded["initial_global_step"],
        expected_final_global_step=recorded["final_global_step"],
        expected_configured_accumulation_steps=recorded[
            "configured_gradient_accumulation_steps"
        ],
        expected_initial_resume_checkpoint=descriptor,
        expected_trainable_parameter_count=recorded["trainable_parameter_count"],
        expected_trainable_parameter_total_numel=recorded[
            "trainable_parameter_total_numel"
        ],
    )
    receipt["gradient_accumulation_offload_receipt_bindings"]["receipts"][
        "resumed"
    ] = recomputed
    rewrite_resume_equivalence(run_dir, receipt)

    with pytest.raises(prune.PruneError, match="exact split inventory"):
        prune.build_prune_plan(run_dir)
    assert not (run_dir / prune.PRUNE_INTENT_NAME).exists()


def test_execute_requires_nonempty_reason_and_export(tmp_path: Path) -> None:
    run_dir, _provenance, export_root = make_verified_run(tmp_path)
    with pytest.raises(prune.PruneError, match="non-empty"):
        prune.execute_prune(run_dir, reason="  ", compact_export_root=export_root)
    assert prune.main(["--run-dir", str(run_dir), "--execute", "--reason", "x"]) == 2
    assert (run_dir / "final/base_model").is_dir()


def test_success_reverifies_and_preserves_unrelated_siblings(tmp_path: Path) -> None:
    run_dir, provenance, export_root = make_verified_run(tmp_path)

    receipt = prune.execute_prune(
        run_dir,
        reason="n10 capacity qualification",
        compact_export_root=export_root,
    )

    assert receipt["state"] == "verified_pruned"
    assert not (run_dir / "final/base_model").exists()
    assert not (run_dir / "checkpoint-4").exists()
    assert not (run_dir / "latest_checkpoint.json").exists()
    assert not (run_dir / "best_checkpoint.json").exists()
    assert not (run_dir / "phase-boundary-step-4.json").exists()
    assert (run_dir / "keep_me.txt").read_text(encoding="utf-8") == "unrelated sibling\n"
    assert (run_dir / "final/workspace_state.pt").is_file()
    assert (run_dir / "final/trainer_state.pt").is_file()
    verified = prune.verify_pruned(run_dir, expected_provenance=provenance)
    assert verified["state"] == "verified_pruned"
    state, reason = prune.classify_prune_state(run_dir, expected_provenance=provenance)
    assert state == "verified_pruned"
    assert "target absence" in reason
    export_destination = Path(receipt["compact_export"]["destination"])
    assert (export_destination / prune.EXPORT_RECEIPT_NAME).is_file()
    assert (export_destination / prune.RUN_VERIFICATION_NAME).is_file()
    for name in (
        prune.RESUME_CONTROL_ENVIRONMENT_NAME,
        prune.RESUME_RESUMED_ENVIRONMENT_NAME,
    ):
        retained = run_dir / name
        exported = export_destination / name
        assert retained.is_file()
        assert exported.read_bytes() == retained.read_bytes()
    exported_paths = {
        item["path"] for item in receipt["compact_export"]["inventory"]
    }
    assert prune.RESUME_CONTROL_ENVIRONMENT_NAME in exported_paths
    assert prune.RESUME_RESUMED_ENVIRONMENT_NAME in exported_paths


def test_historically_dangling_phase_pointer_is_recorded_and_pruned(
    tmp_path: Path,
) -> None:
    run_dir, _provenance, _export_root = make_verified_run(tmp_path)
    (run_dir / "phase-boundary-step-4.json").unlink()
    write_json(
        run_dir / "phase-boundary-step-2.json",
        {"checkpoint": "checkpoint-2", "step": 2, "from": "a", "to": "b"},
    )

    plan = prune.build_prune_plan(run_dir)

    pointer = next(
        item
        for item in plan["targets"]
        if item["source"] == "phase-boundary-step-2.json"
    )
    assert pointer["pointer_target_state"] == "historically_dangling"


@pytest.mark.parametrize("tamper", ["retained", "export", "export_symlink"])
def test_retained_or_export_tamper_is_invalid(
    tmp_path: Path,
    tamper: str,
) -> None:
    run_dir, provenance, export_root = make_verified_run(tmp_path)
    receipt = prune.execute_prune(
        run_dir,
        reason="tamper test",
        compact_export_root=export_root,
    )
    if tamper == "retained":
        (run_dir / "keep_me.txt").write_text("tampered\n", encoding="utf-8")
    elif tamper == "export":
        destination = Path(receipt["compact_export"]["destination"])
        (destination / prune.RUN_VERIFICATION_NAME).write_text("tampered\n", encoding="utf-8")
    else:
        destination = Path(receipt["compact_export"]["destination"])
        real_destination = destination.with_name(destination.name + "-real")
        destination.rename(real_destination)
        destination.symlink_to(real_destination, target_is_directory=True)

    state, _reason = prune.classify_prune_state(run_dir, expected_provenance=provenance)
    assert state == "invalid_prune_receipt"


def test_new_empty_checkpoint_directory_invalidates_retained_layout(
    tmp_path: Path,
) -> None:
    run_dir, provenance, export_root = make_verified_run(tmp_path)
    prune.execute_prune(
        run_dir,
        reason="directory layout tamper",
        compact_export_root=export_root,
    )
    (run_dir / "checkpoint-999").mkdir()

    state, reason = prune.classify_prune_state(
        run_dir, expected_provenance=provenance
    )

    assert state == "invalid_prune_receipt"
    assert "directory layout" in reason


def test_deleted_target_reappearance_is_invalid(tmp_path: Path) -> None:
    run_dir, provenance, export_root = make_verified_run(tmp_path)
    prune.execute_prune(
        run_dir,
        reason="reappearance test",
        compact_export_root=export_root,
    )
    (run_dir / "final/base_model").mkdir()

    state, reason = prune.classify_prune_state(run_dir, expected_provenance=provenance)
    assert state == "invalid_prune_receipt"
    assert "present again" in reason


def test_future_or_current_provenance_mismatch_is_invalid_not_stale(
    tmp_path: Path,
) -> None:
    run_dir, provenance, export_root = make_verified_run(tmp_path)
    prune.execute_prune(
        run_dir,
        reason="provenance test",
        compact_export_root=export_root,
    )
    future = json.loads(json.dumps(provenance))
    future["hashes"]["runner_sha256"] = "f" * 64

    state, reason = prune.classify_prune_state(run_dir, expected_provenance=future)
    assert state == "invalid_prune_receipt"
    assert "provenance" in reason.lower()


@pytest.mark.parametrize(
    "phase",
    [
        "after_intent",
        "after_first_quarantine",
        "after_quarantine",
        "after_first_delete",
        "after_delete",
    ],
)
def test_faults_after_intent_are_protected_incomplete(
    tmp_path: Path,
    phase: str,
) -> None:
    run_dir, provenance, export_root = make_verified_run(tmp_path)

    with pytest.raises(prune.PruneError, match="Injected failure"):
        prune.execute_prune(
            run_dir,
            reason=f"fault {phase}",
            compact_export_root=export_root,
            fault_phase=phase,
        )

    state, reason = prune.classify_prune_state(run_dir, expected_provenance=provenance)
    assert state == "prune_incomplete"
    assert "recovery" in reason
    assert not (run_dir / prune.PRUNE_RECEIPT_NAME).exists()
    assert (run_dir / "keep_me.txt").is_file()


@pytest.mark.parametrize(
    "phase",
    [
        "after_intent",
        "after_first_quarantine",
        "after_quarantine",
        "after_first_delete",
        "after_delete",
    ],
)
def test_explicit_recovery_continues_every_transaction_boundary(
    tmp_path: Path,
    phase: str,
) -> None:
    run_dir, provenance, export_root = make_verified_run(tmp_path)
    with pytest.raises(prune.PruneError, match="Injected failure"):
        prune.execute_prune(
            run_dir,
            reason=f"recover {phase}",
            compact_export_root=export_root,
            fault_phase=phase,
        )

    receipt = prune.recover_prune(run_dir)

    assert receipt["state"] == "verified_pruned"
    assert receipt["recovery"]["mode"] == "explicit_continue_and_finalize"
    assert receipt["recovery"]["automatic_recovery"] is False
    assert prune.verify_pruned(run_dir, expected_provenance=provenance)[
        "state"
    ] == "verified_pruned"
    assert not (run_dir / "final/base_model").exists()
    assert not (run_dir / "checkpoint-4").exists()


def test_recovery_accepts_only_exact_remaining_subset_after_partial_unlink(
    tmp_path: Path,
) -> None:
    run_dir, provenance, export_root = make_verified_run(tmp_path)
    with pytest.raises(prune.PruneError, match="Injected failure"):
        prune.execute_prune(
            run_dir,
            reason="partial directory recovery",
            compact_export_root=export_root,
            fault_phase="after_quarantine",
        )
    intent = json.loads((run_dir / prune.PRUNE_INTENT_NAME).read_text(encoding="utf-8"))
    quarantine = run_dir.parent / intent["quarantine"]
    base_target = next(
        target for target in intent["targets"] if target["source"] == "final/base_model"
    )
    base_quarantine = quarantine / base_target["quarantine"]
    (base_quarantine / "model.safetensors").unlink()

    receipt = prune.recover_prune(run_dir)

    assert (
        receipt["recovery"]["initial_target_states"]["final/base_model"]
        == "quarantine_partial"
    )
    assert prune.verify_pruned(run_dir, expected_provenance=provenance)[
        "state"
    ] == "verified_pruned"


def test_recovery_rejects_mutated_remaining_quarantine_file(tmp_path: Path) -> None:
    run_dir, provenance, export_root = make_verified_run(tmp_path)
    with pytest.raises(prune.PruneError, match="Injected failure"):
        prune.execute_prune(
            run_dir,
            reason="mutated recovery",
            compact_export_root=export_root,
            fault_phase="after_quarantine",
        )
    intent = json.loads((run_dir / prune.PRUNE_INTENT_NAME).read_text(encoding="utf-8"))
    quarantine = run_dir.parent / intent["quarantine"]
    base_target = next(
        target for target in intent["targets"] if target["source"] == "final/base_model"
    )
    (quarantine / base_target["quarantine"] / "config.json").write_text(
        "tampered\n", encoding="utf-8"
    )

    with pytest.raises(prune.PruneError, match="mutated"):
        prune.recover_prune(run_dir)

    state, _reason = prune.classify_prune_state(
        run_dir, expected_provenance=provenance
    )
    assert state == "prune_incomplete"
    assert not (run_dir / prune.PRUNE_RECEIPT_NAME).exists()


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_pruner_lock_rejects_links_without_truncation(tmp_path: Path, kind: str) -> None:
    run_dir, provenance, export_root = make_verified_run(tmp_path)
    lock = prune._runner_lock_path(run_dir, provenance)
    lock.parent.mkdir(parents=True)
    victim = tmp_path / "lock-victim.txt"
    victim.write_text("must remain intact", encoding="utf-8")
    if kind == "symlink":
        lock.symlink_to(victim)
    else:
        lock.hardlink_to(victim)

    with pytest.raises(prune.PruneError, match="[Uu]nsafe|single-link"):
        prune.execute_prune(
            run_dir,
            reason="unsafe lock",
            compact_export_root=export_root,
        )

    assert victim.read_text(encoding="utf-8") == "must remain intact"
    assert not (run_dir / prune.PRUNE_INTENT_NAME).exists()


@pytest.mark.parametrize("case", ["symlink", "hardlink", "incomplete", "unexpected_weight"])
def test_unsafe_or_unexpected_targets_fail_before_intent(
    tmp_path: Path,
    case: str,
) -> None:
    run_dir, _provenance, export_root = make_verified_run(tmp_path)
    outside = tmp_path / "outside-sentinel"
    outside.write_text("do not touch\n", encoding="utf-8")
    if case == "symlink":
        (run_dir / "evil-link").symlink_to(outside)
    elif case == "hardlink":
        os.link(run_dir / "keep_me.txt", run_dir / "hard-link")
    elif case == "incomplete":
        (run_dir / "checkpoint-9").mkdir()
    else:
        (run_dir / "unexpected.safetensors").write_bytes(b"unexpected")

    with pytest.raises(prune.PruneError):
        prune.execute_prune(
            run_dir,
            reason="unsafe target test",
            compact_export_root=export_root,
        )

    assert outside.read_text(encoding="utf-8") == "do not touch\n"
    assert (run_dir / "final/base_model").is_dir()
    assert not (run_dir / prune.PRUNE_INTENT_NAME).exists()


def test_pointer_traversal_fails_before_intent(tmp_path: Path) -> None:
    run_dir, _provenance, export_root = make_verified_run(tmp_path)
    write_json(
        run_dir / "latest_checkpoint.json",
        {"path": "../checkpoint-4", "global_step": 4},
    )
    with pytest.raises(prune.PruneError, match="non-local"):
        prune.execute_prune(
            run_dir,
            reason="pointer traversal",
            compact_export_root=export_root,
        )
    assert (run_dir / "checkpoint-4").is_dir()
    assert not (run_dir / prune.PRUNE_INTENT_NAME).exists()


def test_pruner_uses_the_matrix_runner_lock(tmp_path: Path) -> None:
    run_dir, _provenance, export_root = make_verified_run(tmp_path)
    lock_path = tmp_path / "repo/runs/v10/_control/RUNNER.lock"
    with runner.exclusive_lock(lock_path):
        with pytest.raises(prune.PruneError, match="lock is held"):
            prune.execute_prune(
                run_dir,
                reason="lock test",
                compact_export_root=export_root,
            )
    assert (run_dir / "final/base_model").is_dir()
    assert not (run_dir / prune.PRUNE_INTENT_NAME).exists()


def _run_stub_to_verified(tmp_path: Path) -> tuple[Path, object, object, object, object]:
    repo, snapshot, model_receipt = runner_fixtures.make_repo(tmp_path)
    condition_path = repo / "configs/v10/conditions/config_F0_query_only.json"
    condition = json.loads(condition_path.read_text(encoding="utf-8"))
    condition["assays"] = complete_assay_config()
    write_json(condition_path, condition)
    run_options = runner_fixtures.options(repo, snapshot, model_receipt)
    stub = runner_fixtures.make_stub(repo / "stub_engine.py")

    def command(_options: runner.RunnerOptions, config: Path) -> list[str]:
        return [sys.executable, str(stub), str(config)]

    first = runner.run_matrix(
        run_options,
        child_command_factory=command,
        preflight_fn=lambda _options: {"synthetic": True},
    )
    assert first["states"]["F0_query_only/seed_42"] == "verified_completed"
    run_dir = repo / "runs/v10/smoke/F0_query_only/seed_42"
    verification = json.loads((run_dir / prune.RUN_VERIFICATION_NAME).read_text(encoding="utf-8"))
    add_required_evidence(run_dir, verification["provenance"])
    return run_dir, run_options, command, repo, verification["provenance"]


def test_runner_skips_verified_pruned_without_launch_or_archive(tmp_path: Path) -> None:
    run_dir, run_options, _command, repo, provenance = _run_stub_to_verified(tmp_path)
    prune.execute_prune(
        run_dir,
        reason="runner skip test",
        compact_export_root=tmp_path / "runner-export",
    )

    def forbidden_command(_options: runner.RunnerOptions, _config: Path) -> list[str]:
        raise AssertionError("verified_pruned must never launch a child")

    result = runner.run_matrix(
        run_options,
        child_command_factory=forbidden_command,
        preflight_fn=lambda _options: {"synthetic": True},
    )
    assert result["launched"] == 0
    assert result["states"]["F0_query_only/seed_42"] == "verified_pruned"
    assert not (repo / "runs/v10/_archived_incomplete").exists()
    state, _reason = prune.classify_prune_state(run_dir, expected_provenance=provenance)
    assert state == "verified_pruned"


def test_runner_blocks_incomplete_prune_before_preflight_or_archive(tmp_path: Path) -> None:
    run_dir, run_options, _command, repo, _provenance = _run_stub_to_verified(tmp_path)
    with pytest.raises(prune.PruneError, match="Injected failure"):
        prune.execute_prune(
            run_dir,
            reason="runner incomplete protection",
            compact_export_root=tmp_path / "incomplete-export",
            fault_phase="after_intent",
        )

    with pytest.raises(runner.RunnerError, match="protected prune state"):
        runner.run_matrix(
            run_options,
            child_command_factory=lambda _options, _config: (_ for _ in ()).throw(
                AssertionError("incomplete prune must never launch")
            ),
            preflight_fn=lambda _options: (_ for _ in ()).throw(
                AssertionError("incomplete prune must block before preflight")
            ),
        )
    assert run_dir.exists()
    assert not (repo / "runs/v10/_archived_incomplete").exists()
