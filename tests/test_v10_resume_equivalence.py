from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest
import torch
from safetensors.torch import save_file

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

resume = importlib.import_module("run_v10_resume_equivalence")
runner = importlib.import_module("run_v10_matrix")
pruning = importlib.import_module("prune_v10_verified_run")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(runner.canonical_json_bytes(value))


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def write_base(path: Path, *, offset: float = 0.0) -> None:
    path.mkdir(parents=True, exist_ok=True)
    save_file(
        {
            "model.embed_tokens.weight": (
                torch.arange(12, dtype=torch.float32).reshape(4, 3) + offset
            ),
            "model.norm.weight": torch.arange(3, dtype=torch.bfloat16) + offset,
        },
        str(path / "model.safetensors"),
    )


def write_gradient_offload_receipt(
    path: Path,
    *,
    run_id: str,
    source_sha256: str,
    initial_step: int,
    final_step: int,
    initial_checkpoint: dict[str, object] | None = None,
    accumulation_steps: int = 2,
) -> dict[str, object]:
    windows = final_step - initial_step
    counters = {
        "windows_started": windows,
        "windows_restored": windows,
        "windows_discarded": 0,
        "single_microbatch_windows": 0,
        "microbatch_spills": windows * accumulation_steps,
        "parameter_first_spills": 2 * windows,
        "parameter_merges": 2 * windows * (accumulation_steps - 1),
        "cumulative_current_gradient_bytes": 60 * windows * accumulation_steps,
        "peak_cpu_accumulator_bytes": 60,
    }
    receipt: dict[str, object] = {
        "schema_version": 2,
        "mode": "cpu",
        "algorithm": "pageable_cpu_storage_cuda_native_order_add_v1",
        "claim_boundary": {
            "execution_proof": "synthetic execution proof",
            "numerical_proof": "synthetic numerical boundary",
            "unsupported": "synthetic unsupported boundary",
        },
        "run_id": run_id,
        "source_sha256": source_sha256,
        "resume_signature": "b" * 64,
        "configured_gradient_accumulation_steps": accumulation_steps,
        "initial_global_step": initial_step,
        "last_observed_global_step": final_step,
        "last_restored_global_step": final_step - 1,
        "final_global_step": final_step,
        "trainable_parameter_count": 2,
        "trainable_parameter_total_numel": 15,
        "trainable_gradient_capacity_bytes": 60,
        "trainable_parameter_schema_sha256": "d" * 64,
        "trainable_parameter_schema_fields": list(
            pruning.GRADIENT_OFFLOAD_SCHEMA_FIELDS
        ),
        **counters,
        "live_cpu_buffer_count": 0,
        "live_cpu_buffer_bytes": 0,
        "active_window": None,
        "continuations": [],
        "segments": [
            {
                "segment_index": 0,
                "previous_receipt_sha256": None,
                "resume_checkpoint": initial_checkpoint,
                "initial_global_step": initial_step,
                "last_observed_global_step": final_step,
                "final_global_step": final_step,
                "initial_cumulative_counters": {key: 0 for key in counters},
                "latest_cumulative_counters": counters,
                "final_cumulative_counters": counters,
                "status": "completed",
            }
        ],
        "status": "completed",
        "updated_at": 1.0,
        "receipt_sha256": None,
    }
    receipt["receipt_sha256"] = (
        pruning.gradient_accumulation_offload_receipt_self_hash(receipt)
    )
    write_json(path, receipt)
    return receipt


def trainer_state(run_id: str, *, rng_offset: int = 0, step: int = 2) -> dict[str, object]:
    return {
        "optimizer": {
            "state": {0: {"step": torch.tensor(2.0), "variance": torch.tensor([1.0])}},
            "param_groups": [{"params": [0], "lr": 0.0}],
        },
        "scheduler": {"last_epoch": step, "_step_count": step + 1},
        "scaler": {},
        "sampler_state": {"epoch": 0, "start_batch": step * 8},
        "rng_by_rank": [
            {
                "python": (3, (1, 2, 3 + rng_offset), None),
                "torch_cpu": torch.tensor([1, 2, 3 + rng_offset], dtype=torch.uint8),
                "torch_cuda": torch.tensor([4, 5, 6 + rng_offset], dtype=torch.uint8),
            }
        ],
        "data_fingerprint": {"files": [{"sha256": "a" * 64}]},
        "run_state": {"run_id": run_id, "global_step": step, "epoch": 0},
        "global_step": step,
        "world_size": 1,
        "resume_signature": "b" * 64,
        "structural_resume_signature": "c" * 64,
    }


def metric_records(
    run_id: str,
    *,
    start_step: int,
    total_steps: int,
    resumed: bool = False,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    if resumed:
        records.append(
            {
                "event": "resume",
                "run_id": run_id,
                "step": start_step - 1,
                "checkpoint": "/synthetic/checkpoint",
                "time": 99.0,
            }
        )
    else:
        records.append(
            {"event": "start", "run_id": run_id, "step": 0, "checkpoint": None, "time": 1.0}
        )
    for step in range(start_step, total_steps + 1):
        records.append(
            {
                "split": "train",
                "run_id": run_id,
                "step": step,
                "task_loss": float(10 - step),
                "lr_base": float(total_steps - step),
                "tokens_per_second": float(100 + step),
                "cuda_allocated_gb": float(step),
                "cuda_reserved_gb": float(step + 1),
                "cuda_peak_allocated_gb": float(step + 2),
            }
        )
    for split in ("eval-final", "eval-final-amputated"):
        records.append(
            {
                "split": split,
                "run_id": run_id,
                "step": total_steps,
                "task_loss": 8.5,
                "functional_query_accuracy": 0.5,
            }
        )
    return records


def make_comparison_tree(tmp_path: Path) -> resume.PilotPlan:
    repo = tmp_path / "repo"
    baseline_run = repo / "runs/v10/smoke/F0_query_only/seed_42"
    output = repo / "runs/v10/resume_equivalence/test"
    control = output / "control_uninterrupted"
    resumed = output / "resumed_from_split"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts/run_v10_matrix.py").write_text("# synthetic runner\n", encoding="utf-8")
    (repo / "src/latent_workspace_ft_v10").mkdir(parents=True)
    (repo / "src/latent_workspace_ft_v10/engine.py").write_text(
        "# synthetic engine\n", encoding="utf-8"
    )
    engine_sha256 = runner.sha256_file(
        repo / "src/latent_workspace_ft_v10/engine.py"
    )
    final_specs = (
        (baseline_run / "final", "baseline"),
        (control / "final", "continued"),
        (resumed / "final", "continued"),
    )
    for final, run_id in final_specs:
        write_base(final / "base_model")
        torch.save({"workspace.weight": torch.tensor([1.0, -0.0])}, final / "workspace_state.pt")
        (final / "COMPLETED").write_text("ok\n", encoding="utf-8")
        experiment_config = {"train": {"max_steps": 2}}
        write_json(final / "experiment_config.json", experiment_config)
        write_json(
            final / "optimizer_coverage.json",
            {
                "model_trainable_unique_physical_parameters": 2,
                "model_trainable_numel": 15,
            },
        )
        write_json(
            final / "manifest.json",
            {
                "format": "latent-workspace-ft-bundle-v4",
                "complete": True,
                "global_step": 2,
                "run_id": run_id,
                "source_sha256": engine_sha256,
                "resume_signature": "b" * 64,
                "structural_resume_signature": "c" * 64,
                "config_sha256": pruning._stable_json_sha256(experiment_config),
                "world_size": 1,
                "data_fingerprint": {"files": [{"sha256": "a" * 64}]},
                "optimizer_saved": True,
            },
        )
    torch.save(trainer_state("baseline"), baseline_run / "final/trainer_state.pt")
    torch.save(trainer_state("continued"), control / "final/trainer_state.pt")
    torch.save(trainer_state("continued"), resumed / "final/trainer_state.pt")
    write_jsonl(
        baseline_run / "metrics.jsonl", metric_records("baseline", start_step=1, total_steps=2)
    )
    write_jsonl(control / "metrics.jsonl", metric_records("continued", start_step=1, total_steps=2))
    write_jsonl(
        resumed / "metrics.jsonl",
        metric_records("continued", start_step=2, total_steps=2, resumed=True),
    )
    launched = baseline_run / "LAUNCHED_CONFIG.json"
    baseline_train = {
        "seed": 42,
        "max_steps": 2,
        "gradient_accumulation_steps": 2,
        "gradient_accumulation_offload": runner.GRADIENT_ACCUMULATION_OFFLOAD,
    }
    write_json(launched, {"train": baseline_train})
    verification = baseline_run / "RUN_VERIFICATION.json"
    verification_payload = {
        "verified": True,
        "provenance": {
            "condition": "F0_query_only",
            "run_id": "F0_query_only/seed_42",
            "seed": 42,
            "max_steps": 2,
            "output_dir": "runs/v10/smoke/F0_query_only/seed_42",
            "hashes": {},
        },
    }
    write_json(verification, verification_payload)
    baseline = resume.Baseline(
        run_dir=baseline_run,
        launched_config_path=launched,
        launched_config={"train": baseline_train},
        verification_path=verification,
        verification=verification_payload,
        final_dir=baseline_run / "final",
    )
    plan = resume.PilotPlan(
        repo_root=repo,
        baseline=baseline,
        output_root=output,
        control_output=control,
        resumed_output=resumed,
        control_config_path=output / "CONTROL_CONFIG.json",
        resumed_config_path=output / "RESUME_CONFIG.json",
        split_step=1,
        total_steps=2,
        python=sys.executable,
        engine_module="synthetic",
        max_working_set_bytes=1024 * 1024,
    )
    write_json(
        plan.control_config_path,
        {
            "kind": "control",
            "train": {
                "cuda_allocator_conf": runner.CUDA_ALLOCATOR_CONF,
                "gradient_accumulation_steps": 2,
                "gradient_accumulation_offload": (
                    runner.GRADIENT_ACCUMULATION_OFFLOAD
                ),
            },
        },
    )
    write_json(
        plan.resumed_config_path,
        {
            "kind": "resumed",
            "train": {
                "cuda_allocator_conf": runner.CUDA_ALLOCATOR_CONF,
                "gradient_accumulation_steps": 2,
                "gradient_accumulation_offload": (
                    runner.GRADIENT_ACCUMULATION_OFFLOAD
                ),
            },
        },
    )
    allocator_environment = {
        "harness_version": "synthetic-harness",
        "python": "synthetic-python",
        "platform": "synthetic-platform",
        "hostname": "synthetic-host",
        "torch": "synthetic-torch",
        "cuda_runtime": "synthetic-cuda",
        "cudnn": 1,
        "source_sha256": runner.sha256_file(
            repo / "src/latent_workspace_ft_v10/engine.py"
        ),
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
    write_json(control / "environment.json", allocator_environment)
    write_json(resumed / "environment.json", allocator_environment)
    write_json(baseline_run / "environment.json", allocator_environment)
    verification_payload["allocator_environment"] = (
        runner.validate_allocator_environment_file(
            baseline_run / "environment.json",
            configured=runner.CUDA_ALLOCATOR_CONF,
            expected_source_sha256=runner.sha256_file(
                repo / "src/latent_workspace_ft_v10/engine.py"
            ),
            label="synthetic baseline",
            receipt_path="environment.json",
        )
    )
    write_json(verification, verification_payload)
    checkpoint = plan.control_output / "checkpoint-1"
    checkpoint.mkdir(parents=True)
    (checkpoint / "state.bin").write_bytes(b"synthetic checkpoint")
    (checkpoint / "COMPLETED").write_text("ok\n", encoding="utf-8")
    (checkpoint / "workspace_state.pt").write_bytes(b"synthetic workspace")
    write_json(
        checkpoint / "manifest.json",
        {
            "run_id": "continued",
            "global_step": 1,
            "source_sha256": engine_sha256,
            "resume_signature": "b" * 64,
        },
    )
    write_gradient_offload_receipt(
        baseline_run / runner.GRADIENT_ACCUMULATION_OFFLOAD_RECEIPT,
        run_id="baseline",
        source_sha256=engine_sha256,
        initial_step=0,
        final_step=2,
    )
    write_gradient_offload_receipt(
        control / runner.GRADIENT_ACCUMULATION_OFFLOAD_RECEIPT,
        run_id="continued",
        source_sha256=engine_sha256,
        initial_step=0,
        final_step=2,
    )
    resumed_descriptor = runner.gradient_accumulation_offload_checkpoint_descriptor(
        checkpoint,
        output_dir=resumed,
    )
    write_gradient_offload_receipt(
        resumed / runner.GRADIENT_ACCUMULATION_OFFLOAD_RECEIPT,
        run_id="continued",
        source_sha256=engine_sha256,
        initial_step=1,
        final_step=2,
        initial_checkpoint=resumed_descriptor,
    )
    verification_payload["gradient_accumulation_offload"] = (
        runner.validate_gradient_accumulation_offload_file(
            baseline_run / runner.GRADIENT_ACCUMULATION_OFFLOAD_RECEIPT,
            receipt_path=runner.GRADIENT_ACCUMULATION_OFFLOAD_RECEIPT,
            expected_run_id="baseline",
            expected_source_sha256=engine_sha256,
            expected_resume_signature="b" * 64,
            expected_initial_global_step=0,
            expected_final_global_step=2,
            expected_configured_accumulation_steps=2,
            expected_initial_resume_checkpoint=None,
            expected_trainable_parameter_count=2,
            expected_trainable_parameter_total_numel=15,
        )
    )
    write_json(verification, verification_payload)
    return plan


def valid_publish_receipt(plan: resume.PilotPlan) -> dict[str, object]:
    environment = resume._runtime_environment(plan.repo_root)
    environment["cuda_available"] = True
    return {
        "format": resume.RECEIPT_FORMAT,
        "passed": True,
        "created_utc": "2026-08-22T00:00:00+00:00",
        "design": {
            "baseline_A": resume._relative(plan.repo_root, plan.baseline.run_dir),
            "control_B": resume._relative(plan.repo_root, plan.control_output),
            "resumed_C": resume._relative(plan.repo_root, plan.resumed_output),
            "split_step": plan.split_step,
            "total_steps": plan.total_steps,
            "scheduler_horizon_held_fixed": True,
            "comparison": "bitwise_exact_zero_tolerance",
        },
        "input_bindings": {
            "baseline_RUN_VERIFICATION_sha256": runner.sha256_file(
                plan.baseline.verification_path
            ),
            "baseline_LAUNCHED_CONFIG_sha256": runner.sha256_file(
                plan.baseline.launched_config_path
            ),
            "control_config_sha256": runner.sha256_file(plan.control_config_path),
            "resumed_config_sha256": runner.sha256_file(plan.resumed_config_path),
            "checkpoint_resume_signature": "b" * 64,
            "validated_baseline_provenance_hashes": plan.baseline.verification[
                "provenance"
            ]["hashes"],
        },
        "environment": environment,
        "allocator_environment_bindings": {
            "control": resume._child_allocator_environment_binding(
                plan,
                output_dir=plan.control_output,
                config_path=plan.control_config_path,
                label="resume control child",
            ),
            "resumed": resume._child_allocator_environment_binding(
                plan,
                output_dir=plan.resumed_output,
                config_path=plan.resumed_config_path,
                label="resume resumed child",
            ),
        },
        "allocator_runtime_equivalence": resume._allocator_runtime_equivalence(
            plan,
            {
                "control": resume._child_allocator_environment_binding(
                    plan,
                    output_dir=plan.control_output,
                    config_path=plan.control_config_path,
                    label="resume control child",
                ),
                "resumed": resume._child_allocator_environment_binding(
                    plan,
                    output_dir=plan.resumed_output,
                    config_path=plan.resumed_config_path,
                    label="resume resumed child",
                ),
            },
        ),
        "gradient_accumulation_offload_binding": (
            resume._gradient_accumulation_offload_binding(plan)
        ),
        "bundle_identity_bindings": resume._bundle_identity_bindings(plan),
        "gradient_accumulation_offload_receipt_bindings": (
            resume._gradient_accumulation_offload_receipt_bindings(plan)
        ),
        "launches": {
            "control": {"returncode": 0},
            "resumed": {"returncode": 0},
        },
        "artifact_inventories": {
            "checkpoint_B_split": resume._inventory(
                plan.control_output / f"checkpoint-{plan.split_step}"
            ),
            "final_A": resume._inventory(plan.baseline.final_dir),
            "final_B": resume._inventory(plan.control_output / "final"),
            "final_C": resume._inventory(plan.resumed_output / "final"),
        },
        "comparisons": resume.compare_all_artifacts(plan),
        "performance_boundary": {
            "max_estimated_comparison_working_set_bytes": plan.max_working_set_bytes,
            "training_optimizer_steps_executed": plan.total_steps
            + (plan.total_steps - plan.split_step),
            "comparison_scope": "same_host_same_single_gpu_same_source_and_runtime",
        },
        "claim_boundary": "Synthetic exact resume evidence only.",
    }


def test_checkpoint_descriptor_uses_engine_compact_inventory_identity(
    tmp_path: Path,
) -> None:
    plan = make_comparison_tree(tmp_path)
    checkpoint = plan.control_output / f"checkpoint-{plan.split_step}"

    descriptor = runner.gradient_accumulation_offload_checkpoint_descriptor(
        checkpoint,
        output_dir=plan.resumed_output,
    )
    inventory, _directories = pruning._directory_layout(checkpoint)
    expected_identity = pruning.gradient_offload_inventory_identity(inventory)

    assert descriptor["scope"] == "external"
    assert descriptor["basename"] == checkpoint.name
    assert {
        field: descriptor[field] for field in expected_identity
    } == expected_identity
    manifest_record = next(
        item for item in inventory if item["path"] == "manifest.json"
    )
    assert descriptor["manifest_sha256"] == manifest_record["sha256"]


def make_config_baseline(tmp_path: Path, *, max_steps: int = 8) -> tuple[Path, resume.Baseline]:
    repo = tmp_path / "repo"
    run = repo / "runs/v10/smoke/F0_query_only/seed_42"
    train_file = repo / "data/v10/train.jsonl"
    eval_file = repo / "data/v10/eval.jsonl"
    train_file.parent.mkdir(parents=True)
    train_file.write_text('{"split":"train"}\n', encoding="utf-8")
    eval_file.write_text('{"split":"eval"}\n', encoding="utf-8")
    launched = run / "LAUNCHED_CONFIG.json"
    config = {
        "model": {
            "name_or_path": "example/model",
            "revision": "a" * 40,
            "local_files_only": True,
            "trust_remote_code": False,
            "train_mode": "full",
        },
        "data": {
            "train_files": [str(train_file)],
            "eval_files": [str(eval_file)],
        },
        "train": {
            "max_steps": max_steps,
            "device": "cuda",
            "strict_resume": True,
            "strict_source_resume": True,
            "strict_torch_resume": True,
            "save_optimizer": True,
            "allow_schedule_extension": False,
            "output_dir": ".",
            "resume_from": "none",
            "save_every": 64,
            "save_every_minutes": 20.0,
            "keep_last_checkpoints": 2,
            "gradient_accumulation_offload": runner.GRADIENT_ACCUMULATION_OFFLOAD,
        },
    }
    write_json(launched, config)
    baseline = resume.Baseline(
        run_dir=run,
        launched_config_path=launched,
        launched_config=config,
        verification_path=run / "RUN_VERIFICATION.json",
        verification={},
        final_dir=run / "final",
    )
    return repo, baseline


def test_small_artifact_set_passes_all_exact_gates(tmp_path: Path) -> None:
    plan = make_comparison_tree(tmp_path)
    result = resume.compare_all_artifacts(plan)
    assert result["passed"] is True
    assert result["base"]["save_non_perturbation_A_B"]["changed_element_count"] == 0
    assert result["trainer"]["resume_B_C"]["run_id_preserved"] is True
    assert result["resume_event"] == {"step": 1, "run_id_preserved": True}


def test_scheduler_horizon_mismatch_is_rejected(tmp_path: Path) -> None:
    repo, baseline = make_config_baseline(tmp_path, max_steps=8)
    with pytest.raises(resume.EquivalenceError, match="Scheduler horizon mismatch"):
        resume.derive_pilot_configs(
            baseline,
            repo,
            repo / "runs/v10/resume_equivalence/test",
            split_step=2,
            total_steps=4,
        )


def test_resume_derivation_requires_cpu_accumulation_offload(tmp_path: Path) -> None:
    repo, baseline = make_config_baseline(tmp_path, max_steps=8)
    baseline.launched_config["train"]["gradient_accumulation_offload"] = "none"

    with pytest.raises(resume.EquivalenceError, match="offload='cpu'"):
        resume.derive_pilot_configs(
            baseline,
            repo,
            repo / "runs/v10/resume_equivalence/test",
            split_step=4,
            total_steps=8,
        )


def test_offline_environment_pins_repository_model_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTORCH_CUDA_ALLOC_CONF", "backend:cudaMallocAsync")
    monkeypatch.setenv("PYTORCH_HIP_ALLOC_CONF", "backend:cudaMallocAsync")
    monkeypatch.setenv("PYTORCH_NO_CUDA_MEMORY_CACHING", "1")
    repo = tmp_path / "repo"
    environment = resume._offline_environment(repo)

    assert environment["HF_HUB_CACHE"] == str(
        (repo / "runs/v10/model_cache/hf").resolve()
    )
    assert environment["HF_HUB_OFFLINE"] == "1"
    assert environment["PYTORCH_ALLOC_CONF"] == runner.CUDA_ALLOCATOR_CONF
    assert "PYTORCH_CUDA_ALLOC_CONF" not in environment
    assert "PYTORCH_HIP_ALLOC_CONF" not in environment
    assert "PYTORCH_NO_CUDA_MEMORY_CACHING" not in environment


def test_pinned_model_cache_is_bound_to_baseline_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, baseline = make_config_baseline(tmp_path)
    plan = resume.PilotPlan(
        repo_root=repo,
        baseline=baseline,
        output_root=repo / "runs/v10/resume_equivalence/test",
        control_output=repo / "runs/v10/resume_equivalence/test/control",
        resumed_output=repo / "runs/v10/resume_equivalence/test/resumed",
        control_config_path=repo / "runs/v10/resume_equivalence/test/CONTROL.json",
        resumed_config_path=repo / "runs/v10/resume_equivalence/test/RESUME.json",
        split_step=4,
        total_steps=8,
        python=sys.executable,
        engine_module="synthetic",
        max_working_set_bytes=1024,
    )
    cache_dir = repo / "runs/v10/model_cache/hf"
    snapshot = cache_dir / "models--example--model/snapshots" / ("a" * 40)
    snapshot.mkdir(parents=True)
    receipt_path = repo / "runs/v10/model_cache/MODEL_PREFETCH_RECEIPT.json"
    write_json(receipt_path, {"synthetic": True})
    files = [{"path": "model.safetensors", "bytes": 7, "sha256": "b" * 64}]
    inventory_sha256 = runner.sha256_bytes(runner.canonical_json_bytes(files))
    baseline.verification["provenance"] = {
        "hashes": {"model_snapshot_inventory_sha256": inventory_sha256}
    }

    def verified_cache(
        path: Path,
        *,
        expected_model: str,
        expected_revision: str,
        cache_dir: Path,
    ) -> dict[str, object]:
        assert path == receipt_path
        assert expected_model == "example/model"
        assert expected_revision == "a" * 40
        assert cache_dir == repo / "runs/v10/model_cache/hf"
        return {
            "snapshot_path": snapshot,
            "receipt": {"snapshot": {"files": files}},
        }

    monkeypatch.setattr(resume.model_cache, "verify_prefetch_receipt", verified_cache)

    result = resume._verify_pinned_model_cache(plan)

    assert result["snapshot_inventory_sha256"] == inventory_sha256
    assert result["snapshot_file_count"] == 1
    assert result["snapshot_total_bytes"] == 7


def make_hash_bound_repo(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    repo = tmp_path / "repo"
    run = repo / "runs/v10/smoke/F0_query_only/seed_42"
    launched = run / "LAUNCHED_CONFIG.json"
    condition = repo / "configs/v10/conditions/config_F0_query_only.json"
    matrix = repo / "configs/v10/profiles/smoke/MATRIX.json"
    contract = repo / "configs/v10/CONTRACT.json"
    model_receipt = repo / "runs/v10/model_cache/MODEL_PREFETCH_RECEIPT.json"
    matrix_runner_path = repo / "scripts/run_v10_matrix.py"
    source = repo / "src/latent_workspace_ft_v10"
    engine = source / "engine.py"
    init = source / "__init__.py"
    main = source / "__main__.py"
    train = repo / "data/v10/train.jsonl"
    evaluation = repo / "data/v10/eval.jsonl"
    for path, content in (
        (launched, "{}\n"),
        (condition, "{}\n"),
        (matrix, "{}\n"),
        (contract, "{}\n"),
        (model_receipt, "{}\n"),
        (matrix_runner_path, "# runner\n"),
        (engine, "# engine\n"),
        (init, "\n"),
        (main, "\n"),
        (train, '{"split":"train"}\n'),
        (evaluation, '{"split":"eval"}\n'),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    write_json(
        source / "source_manifest.json",
        {
            "patched_engine": {
                "path": "src/latent_workspace_ft_v10/engine.py",
                "sha256": runner.sha256_file(engine),
            }
        },
    )
    sources, source_tree = runner.source_hashes(repo)
    hashes = {
        "materialized_config_sha256": runner.sha256_file(launched),
        "condition_config_sha256": runner.sha256_file(condition),
        "runner_sha256": runner.sha256_file(matrix_runner_path),
        "source_files_sha256": sources,
        "source_tree_sha256": source_tree,
        "run_data_sha256": {
            "data/v10/train.jsonl": runner.sha256_file(train),
            "data/v10/eval.jsonl": runner.sha256_file(evaluation),
        },
        "contract_data_sha256": {
            "data/v10/train.jsonl": runner.sha256_file(train),
            "data/v10/eval.jsonl": runner.sha256_file(evaluation),
        },
        "contract_sha256": runner.sha256_file(contract),
        "matrix_sha256": runner.sha256_file(matrix),
        "model_receipt_sha256": runner.sha256_file(model_receipt),
    }
    verification: dict[str, object] = {
        "provenance": {
            "profile": "smoke",
            "condition_config": "configs/v10/conditions/config_F0_query_only.json",
            "hashes": hashes,
        }
    }
    return repo, run, verification


def test_current_hash_validation_rejects_tampered_data(tmp_path: Path) -> None:
    repo, run, verification = make_hash_bound_repo(tmp_path)
    resume.validate_current_hash_bindings(repo, run, verification)
    (repo / "data/v10/train.jsonl").write_text('{"tampered":true}\n', encoding="utf-8")
    with pytest.raises(resume.EquivalenceError, match="hash mismatch"):
        resume.validate_current_hash_bindings(repo, run, verification)


def test_existing_output_root_is_rejected(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    output = repo / "runs/v10/resume_equivalence/existing"
    output.mkdir(parents=True)
    with pytest.raises(resume.EquivalenceError, match="refusing overwrite"):
        resume.require_new_output_root(repo, output)


def test_base_tensor_mismatch_fails_closed(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    write_base(left)
    write_base(right, offset=1.0)
    with pytest.raises(resume.EquivalenceError, match="not bitwise identical"):
        resume.compare_base_models(
            left,
            right,
            max_working_set_bytes=1024 * 1024,
            label="synthetic",
        )


def test_trainer_rng_mismatch_fails_closed(tmp_path: Path) -> None:
    left = tmp_path / "left.pt"
    right = tmp_path / "right.pt"
    torch.save(trainer_state("continued"), left)
    torch.save(trainer_state("continued", rng_offset=1), right)
    with pytest.raises(resume.EquivalenceError, match="trainer.*mismatch"):
        resume.compare_trainer_states(
            left,
            right,
            expected_step=2,
            independent_runs=False,
            label="trainer",
        )


def test_metric_exclusions_are_explicit_and_run_id_is_pair_scoped() -> None:
    left = {
        "split": "train",
        "step": 2,
        "run_id": "A",
        "task_loss": 1.0,
        "tokens_per_second": 10.0,
        "cuda_allocated_gb": 2.0,
    }
    right = {
        **left,
        "run_id": "B",
        "tokens_per_second": 999.0,
        "cuda_allocated_gb": 9.0,
    }
    result = resume.compare_metric_records(
        [left],
        [right],
        keys=[("train", 2)],
        ignore_run_id=True,
        label="A/B",
    )
    assert result["exact"] is True
    with pytest.raises(resume.EquivalenceError, match="stable metrics differ"):
        resume.compare_metric_records(
            [left],
            [right],
            keys=[("train", 2)],
            ignore_run_id=False,
            label="B/C",
        )
    changed_loss = {**right, "run_id": "A", "task_loss": 1.5}
    with pytest.raises(resume.EquivalenceError, match="task_loss"):
        resume.compare_metric_records(
            [left],
            [changed_loss],
            keys=[("train", 2)],
            ignore_run_id=False,
            label="stable",
        )
    unknown_resource = {**left, "gpu_temperature": 80}
    with pytest.raises(resume.EquivalenceError, match="gpu_temperature"):
        resume.compare_metric_records(
            [left],
            [unknown_resource],
            keys=[("train", 2)],
            ignore_run_id=False,
            label="scope",
        )


def test_prune_resume_wrapper_is_exactly_bound_to_equivalence(
    tmp_path: Path,
) -> None:
    plan = make_comparison_tree(tmp_path)
    receipt = valid_publish_receipt(plan)

    wrapper_path = resume._publish_prune_resume_verification(plan, receipt)

    wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
    artifact = plan.baseline.run_dir / resume.PUBLISHED_EQUIVALENCE_NAME
    assert wrapper["format"] == resume.PRUNE_RESUME_VERIFICATION_FORMAT
    assert wrapper["verified"] is True
    assert wrapper["comparison"]["equivalence_sha256"] == runner.sha256_file(
        artifact
    )
    assert [item["path"] for item in wrapper["artifacts"]] == [
        resume.PUBLISHED_EQUIVALENCE_NAME,
        resume.PUBLISHED_CONTROL_ENVIRONMENT_NAME,
        resume.PUBLISHED_RESUMED_ENVIRONMENT_NAME,
        resume.PUBLISHED_CONTROL_GRADIENT_OFFLOAD_NAME,
        resume.PUBLISHED_RESUMED_GRADIENT_OFFLOAD_NAME,
    ]
    for name in (
        resume.PUBLISHED_CONTROL_GRADIENT_OFFLOAD_NAME,
        resume.PUBLISHED_RESUMED_GRADIENT_OFFLOAD_NAME,
    ):
        assert (plan.baseline.run_dir / name).is_file()
    ranges = receipt["gradient_accumulation_offload_receipt_bindings"][
        "expected_step_ranges"
    ]
    assert ranges == {
        "baseline": {"initial_global_step": 0, "final_global_step": 2},
        "control": {"initial_global_step": 0, "final_global_step": 2},
        "resumed": {"initial_global_step": 1, "final_global_step": 2},
    }
    with pytest.raises(resume.EquivalenceError, match="Refusing to overwrite"):
        resume._publish_prune_resume_verification(plan, receipt)


@pytest.mark.parametrize(
    "name",
    [
        resume.PUBLISHED_CONTROL_GRADIENT_OFFLOAD_NAME,
        resume.PUBLISHED_RESUMED_GRADIENT_OFFLOAD_NAME,
    ],
)
def test_execute_preflight_rejects_existing_published_gradient_receipt(
    tmp_path: Path,
    name: str,
) -> None:
    plan = make_comparison_tree(tmp_path)
    (plan.baseline.run_dir / name).write_text("occupied\n", encoding="utf-8")

    with pytest.raises(resume.EquivalenceError, match="Refusing to overwrite"):
        resume._require_new_baseline_evidence_paths(plan)


def test_publish_recovery_completes_missing_wrapper_without_overwrite(
    tmp_path: Path,
) -> None:
    plan = make_comparison_tree(tmp_path)
    receipt = valid_publish_receipt(plan)
    write_json(plan.output_root / "RESUME_EQUIVALENCE.json", receipt)
    resume._publish_prune_resume_verification(plan, receipt)
    wrapper = plan.baseline.run_dir / resume.PRUNE_RESUME_VERIFICATION_NAME
    wrapper.unlink()

    recovered = resume.recover_publication(plan)

    assert recovered == wrapper
    assert wrapper.is_file()
    assert json.loads(wrapper.read_text(encoding="utf-8"))["verified"] is True


def test_b_condition_claim_wording_is_bound_and_not_f0_specific(
    tmp_path: Path,
) -> None:
    plan = make_comparison_tree(tmp_path)
    provenance = plan.baseline.verification["provenance"]
    provenance.update(
        {
            "condition": "B_local_invariance",
            "run_id": "B_local_invariance/seed_17",
            "seed": 17,
        }
    )
    plan.baseline.launched_config["train"]["seed"] = 17

    receipt_claim = resume._resume_equivalence_claim_boundary(plan)
    wrapper_claim = resume._resume_wrapper_claim_boundary(plan)

    for claim in (receipt_claim, wrapper_claim):
        assert "B_local_invariance" in claim
        assert "B_local_invariance/seed_17" in claim
        assert "seed=17" in claim
        assert "F0" not in claim
        assert "eight-step" not in claim
    assert "2-step" in receipt_claim
    assert "total_steps=2" in wrapper_claim

    plan.baseline.launched_config["train"]["seed"] = 18
    with pytest.raises(resume.EquivalenceError, match="seed binding"):
        resume._resume_equivalence_claim_boundary(plan)


def test_recovery_rejects_manifest_trainer_bundle_identity_split(
    tmp_path: Path,
) -> None:
    plan = make_comparison_tree(tmp_path)
    receipt = valid_publish_receipt(plan)
    for output in (plan.control_output, plan.resumed_output):
        trainer_path = output / "final/trainer_state.pt"
        trainer = torch.load(trainer_path, map_location="cpu", weights_only=False)
        trainer["run_state"]["run_id"] = "split-run-id"
        torch.save(trainer, trainer_path)
        metrics_path = output / "metrics.jsonl"
        records = resume._read_metrics(metrics_path)
        for record in records:
            record["run_id"] = "split-run-id"
        write_jsonl(metrics_path, records)
    receipt["comparisons"] = resume.compare_all_artifacts(plan)
    write_json(plan.output_root / "RESUME_EQUIVALENCE.json", receipt)

    with pytest.raises(resume.EquivalenceError, match="bundle identity"):
        resume.recover_publication(plan)

    assert not (
        plan.baseline.run_dir / resume.PUBLISHED_EQUIVALENCE_NAME
    ).exists()


def test_publisher_rejects_minimal_or_false_comparison_receipt(tmp_path: Path) -> None:
    plan = make_comparison_tree(tmp_path)
    receipt = valid_publish_receipt(plan)
    receipt["comparisons"]["metrics"]["final_B_C"]["exact"] = False

    with pytest.raises(resume.EquivalenceError, match="not exact"):
        resume._publish_prune_resume_verification(plan, receipt)

    assert not (
        plan.baseline.run_dir / resume.PUBLISHED_EQUIVALENCE_NAME
    ).exists()


def test_publisher_rejects_tampered_resumed_allocator_environment(
    tmp_path: Path,
) -> None:
    plan = make_comparison_tree(tmp_path)
    receipt = valid_publish_receipt(plan)
    environment_path = plan.resumed_output / "environment.json"
    environment = json.loads(environment_path.read_text(encoding="utf-8"))
    environment["allocator_backend"] = "cudaMallocAsync"
    write_json(environment_path, environment)

    with pytest.raises(resume.EquivalenceError, match="native_backend_reported"):
        resume._publish_prune_resume_verification(plan, receipt)


def test_publisher_rejects_tampered_accumulation_offload_binding(
    tmp_path: Path,
) -> None:
    plan = make_comparison_tree(tmp_path)
    receipt = valid_publish_receipt(plan)
    receipt["gradient_accumulation_offload_binding"]["observed"]["resumed"] = (
        "none"
    )

    with pytest.raises(resume.EquivalenceError, match="offload binding differs"):
        resume._publish_prune_resume_verification(plan, receipt)


@pytest.mark.parametrize(
    "mutation",
    ["missing", "status", "binding_path", "binding_hash"],
)
def test_publisher_rejects_missing_or_tampered_child_gradient_offload_receipt(
    tmp_path: Path,
    mutation: str,
) -> None:
    plan = make_comparison_tree(tmp_path)
    receipt = valid_publish_receipt(plan)
    child_path = (
        plan.resumed_output / runner.GRADIENT_ACCUMULATION_OFFLOAD_RECEIPT
    )
    if mutation == "missing":
        child_path.unlink()
    elif mutation == "status":
        child = json.loads(child_path.read_text(encoding="utf-8"))
        child["status"] = "failed"
        child["receipt_sha256"] = (
            pruning.gradient_accumulation_offload_receipt_self_hash(child)
        )
        write_json(child_path, child)
    else:
        field = "path" if mutation == "binding_path" else "sha256"
        receipt["gradient_accumulation_offload_receipt_bindings"]["receipts"][
            "resumed"
        ][field] = "wrong.json" if field == "path" else "0" * 64

    with pytest.raises(resume.EquivalenceError):
        resume._publish_prune_resume_verification(plan, receipt)
