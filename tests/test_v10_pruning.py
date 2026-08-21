from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

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
    resume_output = run_dir / prune.RESUME_EQUIVALENCE_NAME
    write_json(
        resume_output,
        {
            "format": prune.RESUME_EQUIVALENCE_FORMAT,
            "passed": True,
            "created_utc": "2026-08-22T00:00:00+00:00",
            "design": {
                "baseline_A": provenance["output_dir"],
                "control_B": "runs/v10/resume_equivalence/control_uninterrupted",
                "resumed_C": "runs/v10/resume_equivalence/resumed_from_split",
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
                "checkpoint_resume_signature": "synthetic-resume-signature",
                "validated_baseline_provenance_hashes": provenance["hashes"],
            },
            "environment": {
                "engine_sha256": engine_sha256,
                "matrix_runner_sha256": provenance_hashes["runner_sha256"],
                "resume_harness_sha256": "7" * 64,
                "cuda_available": True,
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
                artifact(resume_output, relative=prune.RESUME_EQUIVALENCE_NAME)
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
    write_json(
        final / "manifest.json",
        {
            "format": "latent-workspace-ft-bundle-v4",
            "complete": True,
            "global_step": 8,
            "run_id": "synthetic-engine-run",
        },
    )
    write_json(final / "experiment_config.json", {"train": {"max_steps": 8}})
    write_json(final / "optimizer_coverage.json", {"passed": True})
    write_json(final / "base_update_coverage.json", {"passed": True})
    (final / "workspace_state.pt").write_bytes(b"workspace-retained")
    (final / "trainer_state.pt").write_bytes(b"trainer-retained")

    launched = {
        "train": {
            "seed": 42,
            "max_steps": 8,
            "output_dir": "runs/v10/smoke/F0_query_only/seed_42",
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


def test_producer_shaped_evidence_builds_a_prune_plan(tmp_path: Path) -> None:
    run_dir, provenance, _export_root = make_verified_run(tmp_path)

    plan = prune.build_prune_plan(run_dir)

    assert plan["provenance"] == provenance
    assert plan["preconditions"]["assay_required"] == [
        "amputation",
        "heldout_eval",
    ]
    assert plan["preconditions"]["resume_comparison_passed"] is True


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
        artifact(result_path, relative=prune.RESUME_EQUIVALENCE_NAME)
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
    ["comparison_group", "comparison_pass", "provenance_hashes", "final_a"],
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
    else:
        receipt["artifact_inventories"]["final_A"] = receipt["artifact_inventories"][
            "final_A"
        ][1:]
    rewrite_resume_equivalence(run_dir, receipt)

    with pytest.raises(prune.PruneError):
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
    manifest_path = run_dir / "final/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["run_id"] = "synthetic-engine-run"
    write_json(manifest_path, manifest)
    verification = json.loads((run_dir / prune.RUN_VERIFICATION_NAME).read_text(encoding="utf-8"))
    verification["final_manifest"] = manifest
    verification["final_inventory"], _directories = prune._directory_layout(run_dir / "final")
    write_json(run_dir / prune.RUN_VERIFICATION_NAME, verification)
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
