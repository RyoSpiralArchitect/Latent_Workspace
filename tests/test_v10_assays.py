from __future__ import annotations

import importlib
import json
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

assays = importlib.import_module("verify_v10_assays")
prune = importlib.import_module("prune_v10_verified_run")
runner = importlib.import_module("run_v10_matrix")
runner_fixtures = importlib.import_module("test_v10_runner")

SOURCE_SHA = "a" * 64
ENGINE_RUN_ID = "engine-run-123"


@pytest.fixture(autouse=True)
def current_hash_bindings_are_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    """The hash-binding implementation has dedicated resume-harness tests."""

    monkeypatch.setattr(
        assays.resume_equivalence,
        "validate_current_hash_bindings",
        lambda _repo, _run, _verification: {},
    )


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(prune.canonical_json_bytes(value))


def write_metrics(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def default_assays() -> dict[str, object]:
    return {
        "amputation_eval": True,
        "necessity": {
            "enabled": False,
            "modes": ["intact", "hard_bypass"],
        },
        "choice_eval": {"enabled": False},
        "recruitment": {
            "enabled": False,
            "ranks": [4, 16],
            "scope": "query_end",
            "target": "answer_class",
        },
    }


def make_run(
    tmp_path: Path,
    *,
    assay_config: dict[str, object] | None = None,
    full_loss: float = 2.0,
    amputated_loss: float = 2.0,
) -> tuple[Path, Path, dict[str, object]]:
    repo = tmp_path / "repo"
    run = repo / "runs/v10/smoke/F0_query_only/seed_42"
    final = run / "final"
    base = final / "base_model"
    base.mkdir(parents=True)
    (base / "model.safetensors").write_bytes(b"tiny verified weights")
    write_json(base / "config.json", {"model_type": "synthetic"})
    (final / "COMPLETED").write_text("ok\n", encoding="utf-8")
    experiment_config = {"train": {"max_steps": 8}}
    resume_signature = "e" * 64
    structural_resume_signature = "f" * 64
    data_fingerprint = {"files": [{"sha256": "9" * 64}]}
    manifest: dict[str, object] = {
        "format": "latent-workspace-ft-bundle-v4",
        "complete": True,
        "global_step": 8,
        "run_id": ENGINE_RUN_ID,
        "source_sha256": SOURCE_SHA,
        "resume_signature": resume_signature,
        "structural_resume_signature": structural_resume_signature,
        "config_sha256": prune._stable_json_sha256(experiment_config),
        "world_size": 1,
        "data_fingerprint": data_fingerprint,
    }
    write_json(final / "manifest.json", manifest)
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
    (final / "workspace_state.pt").write_bytes(b"workspace")
    torch.save(
        {
            "run_state": {"run_id": ENGINE_RUN_ID, "global_step": 8},
            "global_step": 8,
            "resume_signature": resume_signature,
            "structural_resume_signature": structural_resume_signature,
            "world_size": 1,
            "data_fingerprint": data_fingerprint,
        },
        final / "trainer_state.pt",
    )

    config = {
        "train": {
            "seed": 42,
            "max_steps": 8,
            "gradient_accumulation_steps": 8,
            "cuda_allocator_conf": runner.CUDA_ALLOCATOR_CONF,
            "gradient_accumulation_offload": (
                runner.GRADIENT_ACCUMULATION_OFFLOAD
            ),
            # ExperimentConfig.from_json resolves relative paths from the
            # launched config's parent, which is the run directory.
            "output_dir": ".",
        },
        "assays": assay_config or default_assays(),
    }
    write_json(run / assays.LAUNCHED_CONFIG_NAME, config)
    provenance: dict[str, object] = {
        "profile": "smoke",
        "run_id": "F0_query_only/seed_42",
        "condition": "F0_query_only",
        "seed": 42,
        "max_steps": 8,
        "output_dir": "runs/v10/smoke/F0_query_only/seed_42",
        "runtime_policy": {
            "environment_variable": runner.CUDA_ALLOCATOR_ENV,
            "pytorch_alloc_conf": runner.CUDA_ALLOCATOR_CONF,
            "gradient_accumulation_offload": (
                runner.GRADIENT_ACCUMULATION_OFFLOAD
            ),
            "forbidden_environment_variables": [
                runner.CUDA_ALLOCATOR_LEGACY_ENV,
                runner.CUDA_ALLOCATOR_HIP_LEGACY_ENV,
                runner.CUDA_ALLOCATOR_DISABLE_ENV,
            ],
        },
        "hashes": {
            "source_files_sha256": {
                "src/latent_workspace_ft_v10/engine.py": SOURCE_SHA,
            },
            "materialized_config_sha256": prune.sha256_file(
                run / assays.LAUNCHED_CONFIG_NAME
            )
        },
    }
    write_json(run / prune.FULL_UPDATE_DELTA_NAME, {"format": "synthetic", "passed": True})
    environment = {
        "harness_version": "synthetic-harness",
        "python": "synthetic-python",
        "platform": "synthetic-platform",
        "hostname": "synthetic-host",
        "torch": "synthetic-torch",
        "cuda_runtime": "synthetic-cuda",
        "cudnn": 1,
        "source_sha256": SOURCE_SHA,
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
    write_json(run / prune.ENVIRONMENT_NAME, environment)
    allocator_binding = runner.validate_allocator_environment_file(
        run / prune.ENVIRONMENT_NAME,
        configured=runner.CUDA_ALLOCATOR_CONF,
        expected_source_sha256=SOURCE_SHA,
        label="synthetic assay baseline",
        receipt_path=prune.ENVIRONMENT_NAME,
    )
    runner_fixtures.write_synthetic_gradient_offload_receipt(
        run / prune.GRADIENT_ACCUMULATION_OFFLOAD_RECEIPT_NAME,
        run_id=ENGINE_RUN_ID,
        source_sha256=SOURCE_SHA,
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
            run / prune.GRADIENT_ACCUMULATION_OFFLOAD_RECEIPT_NAME,
            receipt_path=prune.GRADIENT_ACCUMULATION_OFFLOAD_RECEIPT_NAME,
            expected_run_id=ENGINE_RUN_ID,
            expected_source_sha256=SOURCE_SHA,
            expected_resume_signature="e" * 64,
            expected_initial_global_step=0,
            expected_final_global_step=8,
            expected_configured_accumulation_steps=8,
            expected_initial_resume_checkpoint=None,
            expected_trainable_parameter_count=1,
            expected_trainable_parameter_total_numel=1,
        )
    )
    inventory, _directories = prune._directory_layout(final)
    bundle_identity = prune.validate_bundle_identity(
        final,
        bundle_path="final",
        expected_global_step=8,
    )
    write_json(
        run / prune.RUN_VERIFICATION_NAME,
        {
            "format": prune.RUN_VERIFICATION_FORMAT,
            "verified": True,
            "provenance": provenance,
            "final_manifest": manifest,
            "full_update_delta": {
                "path": prune.FULL_UPDATE_DELTA_NAME,
                "sha256": prune.sha256_file(run / prune.FULL_UPDATE_DELTA_NAME),
                "passed": True,
            },
            "allocator_environment": allocator_binding,
            "gradient_accumulation_offload": gradient_offload_binding,
            "bundle_identity": bundle_identity,
            "final_inventory": inventory,
        },
    )
    write_metrics(
        run / assays.METRICS_NAME,
        [
            {
                "split": "eval-final",
                "run_id": ENGINE_RUN_ID,
                "step": 8,
                "task_loss": full_loss,
                "functional_heldout_query_accuracy": 0.5,
            },
            {
                "split": "eval-final-amputated",
                "run_id": ENGINE_RUN_ID,
                "step": 8,
                "task_loss": amputated_loss,
                "functional_heldout_query_accuracy": 0.5,
            },
        ],
    )
    write_json(
        run / assays.AMPUTATION_REPORT_NAME,
        {
            "step": 8,
            "full": {
                "task_loss": full_loss,
                "functional_heldout_query_accuracy": 0.5,
            },
            "amputated": {
                "task_loss": amputated_loss,
                "functional_heldout_query_accuracy": 0.5,
            },
            "task_loss_delta_full_minus_amputated": full_loss - amputated_loss,
        },
    )
    return repo, run, provenance


def necessity_result(run: Path, *, direction: str | None = None) -> dict[str, object]:
    result: dict[str, object] = {
        "format": "latent-workspace-v9-functional-necessity-v1",
        "checkpoint": str((run / "final").resolve()),
        "source_sha256": SOURCE_SHA,
        "modes": ["intact", "hard_bypass"],
        "metrics": {
            "intact": {"task_loss": 2.0},
            "hard_bypass": {"task_loss": 1.5},
        },
        "effects": {"hard_bypass": {"task_loss_increase_vs_intact": -0.5}},
        "evidence_ladder": {"F1": {"passed": False}},
        "primary_gate_passed": False,
        "claim_boundary": "Synthetic scientific direction is not an integrity gate.",
    }
    if direction is not None:
        result["scientific_direction"] = direction
    return result


def test_f0_inline_assays_succeed_and_default_cli_is_dry_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, run, provenance = make_run(tmp_path)

    assert assays.main(["--repo-root", str(repo), "--run-dir", str(run)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "dry_run"
    assert output["required_assays"] == ["heldout_eval", "amputation"]
    assert not (run / assays.RECEIPT_NAME).exists()

    receipt = assays.build_receipt(repo, run)
    assert receipt["verified"] is True
    assert receipt["run_id"] == provenance["run_id"]
    assert receipt["provenance"] == provenance
    assert receipt["required_assays"] == receipt["completed_assays"]
    assert receipt["execution_integrity"]["status"] == "PASS"
    assert receipt["scientific_direction"]["authoritative"] is False
    for artifact in receipt["artifacts"]:
        prune._artifact_matches(run / artifact["path"], artifact)


def test_o3_missing_necessity_blocks_receipt(tmp_path: Path) -> None:
    config = default_assays()
    config["necessity"] = {"enabled": True, "modes": ["intact", "hard_bypass"]}
    repo, run, _ = make_run(tmp_path, assay_config=config)

    with pytest.raises(assays.AssayVerificationError, match="necessity_result.json"):
        assays.build_receipt(repo, run)
    assert not (run / assays.RECEIPT_NAME).exists()


def test_external_necessity_success_even_when_scientific_gate_is_negative(
    tmp_path: Path,
) -> None:
    config = default_assays()
    config["necessity"] = {"enabled": True, "modes": ["intact", "hard_bypass"]}
    repo, run, _ = make_run(tmp_path, assay_config=config)
    write_json(run / assays.EXTERNAL_RESULTS["necessity"], necessity_result(run))

    receipt = assays.build_receipt(repo, run)

    assert receipt["required_assays"] == ["heldout_eval", "amputation", "necessity"]
    assert receipt["completed_assays"] == receipt["required_assays"]
    assert receipt["execution_integrity"]["assays"]["necessity"][
        "execution_integrity"
    ] == "PASS"
    assert (
        receipt["scientific_direction"]["by_assay"]["necessity"]
        == "does_not_support_gate"
    )


@pytest.mark.parametrize("mutation", ["missing", "wrong_run", "duplicate"])
def test_metric_missing_or_tamper_fails_closed(tmp_path: Path, mutation: str) -> None:
    repo, run, _ = make_run(tmp_path)
    records = [
        {
            "split": "eval-final",
            "run_id": ENGINE_RUN_ID,
            "step": 8,
            "task_loss": 2.0,
        }
    ]
    if mutation == "wrong_run":
        records[0]["run_id"] = "tampered"
        records.append(
            {
                "split": "eval-final-amputated",
                "run_id": ENGINE_RUN_ID,
                "step": 8,
                "task_loss": 2.0,
                "functional_heldout_query_accuracy": 0.5,
            }
        )
    elif mutation == "duplicate":
        records.extend(
            [
                {
                    "split": "eval-final",
                    "run_id": ENGINE_RUN_ID,
                    "step": 8,
                    "task_loss": 2.0,
                    "functional_heldout_query_accuracy": 0.5,
                },
                {
                    "split": "eval-final-amputated",
                    "run_id": ENGINE_RUN_ID,
                    "step": 8,
                    "task_loss": 2.0,
                    "functional_heldout_query_accuracy": 0.5,
                },
            ]
        )
    write_metrics(run / assays.METRICS_NAME, records)

    with pytest.raises(assays.AssayVerificationError):
        assays.build_receipt(repo, run)


def test_provenance_mismatch_fails_closed(tmp_path: Path) -> None:
    repo, run, _ = make_run(tmp_path)
    verification = json.loads((run / prune.RUN_VERIFICATION_NAME).read_text(encoding="utf-8"))
    verification["provenance"]["run_id"] = "different/seed_42"
    write_json(run / prune.RUN_VERIFICATION_NAME, verification)

    with pytest.raises(assays.AssayVerificationError, match="condition/seed"):
        assays.build_receipt(repo, run)


def test_launched_output_dir_mismatch_fails_closed(tmp_path: Path) -> None:
    repo, run, _ = make_run(tmp_path)
    config = json.loads((run / assays.LAUNCHED_CONFIG_NAME).read_text(encoding="utf-8"))
    config["train"]["output_dir"] = ".."
    write_json(run / assays.LAUNCHED_CONFIG_NAME, config)
    verification = json.loads(
        (run / prune.RUN_VERIFICATION_NAME).read_text(encoding="utf-8")
    )
    verification["provenance"]["hashes"]["materialized_config_sha256"] = (
        prune.sha256_file(run / assays.LAUNCHED_CONFIG_NAME)
    )
    write_json(run / prune.RUN_VERIFICATION_NAME, verification)

    with pytest.raises(
        assays.AssayVerificationError,
        match="LAUNCHED_CONFIG output_dir disagrees with run root",
    ):
        assays.build_receipt(repo, run)


def test_current_repository_hash_mismatch_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, run, _ = make_run(tmp_path)

    def reject_stale(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise assays.resume_equivalence.EquivalenceError("runner hash mismatch")

    monkeypatch.setattr(
        assays.resume_equivalence, "validate_current_hash_bindings", reject_stale
    )

    with pytest.raises(assays.AssayVerificationError, match="stale.*runner hash mismatch"):
        assays.build_receipt(repo, run)


@pytest.mark.parametrize("mutation", ["missing", "tampered"])
def test_allocator_environment_evidence_fails_closed(
    tmp_path: Path, mutation: str
) -> None:
    repo, run, _ = make_run(tmp_path)
    environment_path = run / prune.ENVIRONMENT_NAME
    if mutation == "missing":
        environment_path.unlink()
    else:
        environment = json.loads(environment_path.read_text(encoding="utf-8"))
        environment["allocator_snapshot_settings"]["expandable_segments"] = False
        write_json(environment_path, environment)

    with pytest.raises(
        assays.AssayVerificationError,
        match="Baseline is not currently verified",
    ):
        assays.build_receipt(repo, run)


def test_execute_is_atomic_and_never_overwrites(tmp_path: Path) -> None:
    repo, run, _ = make_run(tmp_path)

    destination = assays.execute(repo, run)
    before = destination.read_bytes()
    receipt = json.loads(before)
    assert receipt["format"] == assays.RECEIPT_FORMAT
    assert receipt["verified"] is True
    with pytest.raises(assays.AssayVerificationError, match="overwrite"):
        assays.execute(repo, run)
    assert destination.read_bytes() == before


@pytest.mark.parametrize(
    ("amputated_loss", "expected_direction"),
    [(2.0, "neutral"), (1.5, "opposes_load_bearing")],
)
def test_neutral_or_negative_science_remains_integrity_pass(
    tmp_path: Path, amputated_loss: float, expected_direction: str
) -> None:
    repo, run, _ = make_run(tmp_path, full_loss=2.0, amputated_loss=amputated_loss)

    receipt = assays.build_receipt(repo, run)

    assert receipt["execution_integrity"]["status"] == "PASS"
    assert receipt["scientific_direction"]["by_assay"]["amputation"] == expected_direction
