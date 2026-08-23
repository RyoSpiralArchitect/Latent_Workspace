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

oracle = importlib.import_module("compare_v10_full_model_oracle")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(oracle.canonical_json_bytes(value))


def base_tensors() -> dict[str, torch.Tensor]:
    return {
        "lm_head.weight": torch.arange(12, dtype=torch.float16).reshape(3, 4),
        "model.embed_tokens.weight": torch.arange(32, dtype=torch.float32).reshape(8, 4),
        "model.norm.weight": torch.arange(4, dtype=torch.bfloat16),
    }


def write_indexed_model(
    root: Path,
    tensors: dict[str, torch.Tensor],
    *,
    reverse_assignment: bool = False,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    names = sorted(tensors)
    if len(names) < 2:
        raise AssertionError("Tiny sharded fixture requires at least two tensors.")
    split = max(1, len(names) // 2)
    groups = [names[:split], names[split:]]
    if reverse_assignment:
        groups.reverse()
    weight_map: dict[str, str] = {}
    for index, group in enumerate(groups, start=1):
        shard_name = f"model-{index:05d}-of-00002.safetensors"
        save_file(
            {name: tensors[name].detach().clone().contiguous() for name in group},
            str(root / shard_name),
        )
        for name in group:
            weight_map[name] = shard_name
    write_json(
        root / "model.safetensors.index.json",
        {
            "metadata": {
                "total_size": sum(
                    tensor.numel() * tensor.element_size() for tensor in tensors.values()
                )
            },
            "weight_map": weight_map,
        },
    )
    write_json(root / "config.json", {"architectures": ["TinyOracleModel"]})


def make_fixture(tmp_path: Path) -> tuple[Path, list[str]]:
    repo = tmp_path / "repo"
    candidate = repo / "models/candidate"
    reference = repo / "models/oracle"
    write_indexed_model(candidate, base_tensors())
    write_indexed_model(reference, base_tensors(), reverse_assignment=True)

    evidence = repo / "evidence"
    records = {
        "candidate_config.json": {"gradient_accumulation_offload": "cpu_spill"},
        "oracle_config.json": {"gradient_accumulation_offload": "native"},
        "candidate_source.json": {"source_sha256": "a" * 64},
        "oracle_source.json": {"source_sha256": "b" * 64},
        "candidate_run.json": {"verified": True, "run_id": "spill-run"},
        "oracle_run.json": {"passed": True, "run_id": "native-run"},
    }
    for name, value in records.items():
        write_json(evidence / name, value)

    arguments = [
        "--repo-root",
        str(repo),
        "--candidate-model",
        "models/candidate",
        "--oracle-model",
        "models/oracle",
        "--candidate-config-evidence",
        "evidence/candidate_config.json",
        "--oracle-config-evidence",
        "evidence/oracle_config.json",
        "--candidate-source-evidence",
        "evidence/candidate_source.json",
        "--oracle-source-evidence",
        "evidence/oracle_source.json",
        "--candidate-run-evidence",
        "evidence/candidate_run.json",
        "--oracle-run-evidence",
        "evidence/oracle_run.json",
        "--output",
        "receipts/FULL_MODEL_ORACLE.json",
        "--max-working-set-bytes",
        "128",
    ]
    return repo, arguments


def trainer_state(
    run_id: str,
    *,
    resume_signature: str,
    structural_resume_signature: str,
    optimizer_offset: float = 0.0,
) -> dict[str, object]:
    return {
        "optimizer": {
            "state": {
                0: {
                    "step": torch.tensor(8.0),
                    "exp_avg_sq_row": torch.tensor([1.0 + optimizer_offset, 2.0]),
                }
            },
            "param_groups": [
                {
                    "params": [0],
                    "lr": 0.0,
                    "relative_step": False,
                    "scale_parameter": False,
                }
            ],
        },
        "scheduler": {"last_epoch": 8, "_step_count": 9},
        "scaler": {},
        "sampler_state": {"epoch": 0, "start_batch": 64},
        "rng_by_rank": [
            {
                "python": (3, (1, 2, 3), None),
                "torch_cpu": torch.tensor([1, 2, 3], dtype=torch.uint8),
                "torch_cuda": torch.tensor([4, 5, 6], dtype=torch.uint8),
            }
        ],
        "data_fingerprint": {"files": [{"sha256": "c" * 64}]},
        "run_state": {"run_id": run_id, "global_step": 8, "epoch": 0},
        "global_step": 8,
        "world_size": 1,
        "resume_signature": resume_signature,
        "structural_resume_signature": structural_resume_signature,
    }


def write_bundle(
    run: Path,
    *,
    run_id: str,
    reverse_assignment: bool,
    dynamic_offset: float,
    optimizer_offset: float = 0.0,
    stable_loss: float = 8.5,
    gradient_accumulation_offload: str = "none",
    include_gradient_accumulation_offload: bool = True,
    base_activation_offload: str | None = None,
    output_dir: str = "runs/shared",
    resume_from: str | None = None,
    config_extra: dict[str, object] | None = None,
    source_sha256: str = "a" * 64,
) -> None:
    final = run / "final"
    write_indexed_model(
        final / "base_model",
        base_tensors(),
        reverse_assignment=reverse_assignment,
    )
    (final / "COMPLETED").write_text("ok\n", encoding="utf-8")
    train_config: dict[str, object] = {
        "output_dir": output_dir,
        "resume_from": resume_from,
    }
    if include_gradient_accumulation_offload:
        train_config["gradient_accumulation_offload"] = gradient_accumulation_offload
    if base_activation_offload is not None:
        train_config["base_activation_offload"] = base_activation_offload
    train_config.update({"max_steps": 8, "epochs": 1})
    experiment_config: dict[str, object] = {
        "model": {},
        "data": {},
        "workspace": {},
        "functional": {},
        "train": train_config,
        "attribution": {},
        "induction": {},
        "transition": {},
        "assays": {},
    }
    if config_extra:
        experiment_config.update(config_extra)
    write_json(final / "experiment_config.json", experiment_config)
    resume_signature = oracle.engine_resume_signature(
        experiment_config, ignore_schedule_horizon=False
    )
    structural_resume_signature = oracle.engine_resume_signature(
        experiment_config, ignore_schedule_horizon=True
    )
    write_json(
        final / "manifest.json",
        {
            "format": "latent-workspace-ft-bundle-v4",
            "complete": True,
            "global_step": 8,
            "run_id": run_id,
            "world_size": 1,
            "data_fingerprint": {"files": [{"sha256": "c" * 64}]},
            "source_sha256": source_sha256,
            "config_sha256": oracle.engine_stable_hash(experiment_config),
            "resume_signature": resume_signature,
            "structural_resume_signature": structural_resume_signature,
        },
    )
    torch.save(
        {"workspace.weight": torch.tensor([1.0, -0.0], dtype=torch.float32)},
        final / "workspace_state.pt",
    )
    torch.save(
        trainer_state(
            run_id,
            optimizer_offset=optimizer_offset,
            resume_signature=resume_signature,
            structural_resume_signature=structural_resume_signature,
        ),
        final / "trainer_state.pt",
    )
    metric_records = [
        {"event": "start", "run_id": run_id, "time": dynamic_offset},
        {
            "split": "train",
            "step": 8,
            "run_id": run_id,
            "task_loss": stable_loss,
            "time": dynamic_offset,
            "tokens_per_second": 100.0 + dynamic_offset,
            "cuda_allocated_gb": dynamic_offset,
            "checkpoint": f"/dynamic/{run_id}",
        },
        {
            "split": "eval-final",
            "step": 8,
            "run_id": run_id,
            "task_loss": 8.5,
            "time": dynamic_offset + 1,
        },
    ]
    run.mkdir(parents=True, exist_ok=True)
    (run / "metrics.jsonl").write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in metric_records),
        encoding="utf-8",
    )


def rebind_bundle_provenance(run: Path, *, source_sha256: str | None = None) -> None:
    final = run / "final"
    config = json.loads((final / "experiment_config.json").read_text(encoding="utf-8"))
    manifest = json.loads((final / "manifest.json").read_text(encoding="utf-8"))
    resume_signature = oracle.engine_resume_signature(config, ignore_schedule_horizon=False)
    structural_resume_signature = oracle.engine_resume_signature(
        config, ignore_schedule_horizon=True
    )
    manifest["config_sha256"] = oracle.engine_stable_hash(config)
    manifest["resume_signature"] = resume_signature
    manifest["structural_resume_signature"] = structural_resume_signature
    if source_sha256 is not None:
        manifest["source_sha256"] = source_sha256
    write_json(final / "manifest.json", manifest)
    trainer = torch.load(final / "trainer_state.pt", map_location="cpu", weights_only=False)
    trainer["resume_signature"] = resume_signature
    trainer["structural_resume_signature"] = structural_resume_signature
    torch.save(trainer, final / "trainer_state.pt")


def make_bundle_fixture(tmp_path: Path) -> tuple[Path, list[str]]:
    repo, arguments = make_fixture(tmp_path)
    candidate_run = repo / "runs/candidate"
    oracle_run = repo / "runs/oracle"
    write_bundle(
        candidate_run,
        run_id="spill-run",
        reverse_assignment=False,
        dynamic_offset=1.0,
    )
    write_bundle(
        oracle_run,
        run_id="native-run",
        reverse_assignment=True,
        dynamic_offset=99.0,
        source_sha256="b" * 64,
    )
    arguments[arguments.index("--candidate-model") + 1] = "runs/candidate/final/base_model"
    arguments[arguments.index("--oracle-model") + 1] = "runs/oracle/final/base_model"
    arguments.extend(
        [
            "--candidate-run",
            "runs/candidate",
            "--oracle-run",
            "runs/oracle",
        ]
    )
    return repo, arguments


def make_cross_offload_bundle_fixture(tmp_path: Path) -> tuple[Path, list[str]]:
    repo, arguments = make_fixture(tmp_path)
    candidate_run = repo / "runs/candidate"
    oracle_run = repo / "runs/oracle"
    write_bundle(
        candidate_run,
        run_id="spill-run",
        reverse_assignment=False,
        dynamic_offset=1.0,
        gradient_accumulation_offload="cpu",
        output_dir="/remote/private/candidate-output",
        resume_from="/remote/private/candidate-checkpoint",
    )
    write_bundle(
        oracle_run,
        run_id="native-run",
        reverse_assignment=True,
        dynamic_offset=99.0,
        gradient_accumulation_offload="none",
        output_dir="/remote/private/oracle-output",
        resume_from=None,
        source_sha256="b" * 64,
    )
    arguments[arguments.index("--candidate-model") + 1] = "runs/candidate/final/base_model"
    arguments[arguments.index("--oracle-model") + 1] = "runs/oracle/final/base_model"
    arguments.extend(
        [
            "--candidate-run",
            "runs/candidate",
            "--oracle-run",
            "runs/oracle",
            "--cross-offload-parity",
        ]
    )
    return repo, arguments


def make_cross_transport_bundle_fixture(
    tmp_path: Path,
    *,
    oracle_gradient_accumulation_offload: str = "none",
) -> tuple[Path, list[str]]:
    repo, arguments = make_fixture(tmp_path)
    candidate_run = repo / "runs/candidate"
    oracle_run = repo / "runs/oracle"
    write_bundle(
        candidate_run,
        run_id="activation-offload-run",
        reverse_assignment=False,
        dynamic_offset=1.0,
        gradient_accumulation_offload="none",
        base_activation_offload="all_base",
        output_dir="/remote/private/candidate-output",
    )
    write_bundle(
        oracle_run,
        run_id="reference-run",
        reverse_assignment=True,
        dynamic_offset=99.0,
        gradient_accumulation_offload=oracle_gradient_accumulation_offload,
        base_activation_offload="legacy_functional",
        output_dir="/remote/private/oracle-output",
        source_sha256="b" * 64,
    )
    arguments[arguments.index("--candidate-model") + 1] = (
        "runs/candidate/final/base_model"
    )
    arguments[arguments.index("--oracle-model") + 1] = "runs/oracle/final/base_model"
    arguments.extend(
        [
            "--candidate-run",
            "runs/candidate",
            "--oracle-run",
            "runs/oracle",
            "--cross-transport-parity",
        ]
    )
    return repo, arguments


def read_receipt(repo: Path) -> dict[str, object]:
    return json.loads((repo / "receipts/FULL_MODEL_ORACLE.json").read_text(encoding="utf-8"))


def test_tiny_sharded_models_pass_and_bind_all_evidence(tmp_path: Path) -> None:
    repo, arguments = make_fixture(tmp_path)

    assert oracle.main(arguments) == 0
    receipt = read_receipt(repo)
    assert receipt["format"] == oracle.RECEIPT_FORMAT
    assert receipt["status"] == "PASS"
    assert receipt["result"]["passed"] is True
    assert receipt["result"]["run_bundle"] == {
        "enabled": False,
        "passed": None,
        "reason": "not_requested_base_model_only",
    }
    counts = receipt["result"]["base_model"]["counts"]
    assert counts["candidate_tensor_count"] == 3
    assert counts["oracle_tensor_count"] == 3
    assert counts["byte_compared_tensor_count"] == 3
    assert counts["byte_compared_element_count"] == 48
    assert counts["byte_exact_tensor_count"] == 3
    assert counts["total_mismatch_tensor_count"] == 0
    assert receipt["result"]["base_model"]["first_mismatch"] is None
    assert receipt["result"]["first_mismatch"] is None

    candidate = receipt["inputs"]["candidate"]
    reference = receipt["inputs"]["oracle"]
    assert candidate["model_root"] == "models/candidate"
    assert reference["model_root"] == "models/oracle"
    assert len(candidate["tree_inventory"]["inventory_sha256"]) == 64
    assert len(reference["tree_inventory"]["inventory_sha256"]) == 64
    assert (
        candidate["indexed_safetensors"]["tensor_schema_sha256"]
        == (reference["indexed_safetensors"]["tensor_schema_sha256"])
    )
    assert (
        candidate["indexed_safetensors"]["weight_map_sha256"]
        != (reference["indexed_safetensors"]["weight_map_sha256"])
    )
    for side in ("candidate", "oracle"):
        assert set(receipt["inputs"][side]["evidence"]) == {"config", "source", "run"}
        assert all(
            len(receipt["inputs"][side]["evidence"][category][0]["sha256"]) == 64
            for category in ("config", "source", "run")
        )
    assert receipt["stability"] == {
        "candidate_tree_pre_post_inventory_equal": True,
        "oracle_tree_pre_post_inventory_equal": True,
        "all_config_source_run_evidence_pre_post_hashes_equal": True,
        "run_bundle_artifact_inventories_equal": None,
    }
    assert not list((repo / "receipts").glob(".*.tmp"))


def test_byte_difference_writes_bounded_fail_receipt(tmp_path: Path) -> None:
    repo, arguments = make_fixture(tmp_path)
    tensors = base_tensors()
    changed = tensors["model.embed_tokens.weight"].clone()
    changed.reshape(-1)[5] += 1
    tensors["model.embed_tokens.weight"] = changed
    write_indexed_model(repo / "models/candidate", tensors)

    assert oracle.main(arguments) == 1
    receipt = read_receipt(repo)
    assert receipt["status"] == "FAIL"
    assert receipt["result"]["passed"] is False
    assert receipt["result"]["base_model"]["first_mismatch"] == {
        "kind": "tensor_bytes",
        "tensor": "model.embed_tokens.weight",
        "first_flat_element_index": 5,
    }
    assert receipt["result"]["first_mismatch"]["scope"] == "base_model"
    counts = receipt["result"]["base_model"]["counts"]
    assert counts["byte_mismatch_tensor_count"] == 1
    assert counts["byte_mismatch_element_count"] == 1
    assert counts["total_mismatch_tensor_count"] == 1
    encoded = json.dumps(receipt["result"]["base_model"], sort_keys=True)
    assert "candidate_value" not in encoded
    assert "oracle_value" not in encoded
    assert "tensor_records" not in encoded


@pytest.mark.parametrize(
    ("replacement", "shape_count", "dtype_count"),
    [
        (torch.arange(5, dtype=torch.bfloat16), 1, 0),
        (torch.arange(4, dtype=torch.float32), 0, 1),
    ],
)
def test_schema_difference_is_fail_closed(
    tmp_path: Path,
    replacement: torch.Tensor,
    shape_count: int,
    dtype_count: int,
) -> None:
    repo, arguments = make_fixture(tmp_path)
    tensors = base_tensors()
    tensors["model.norm.weight"] = replacement
    write_indexed_model(repo / "models/candidate", tensors)

    assert oracle.main(arguments) == 1
    receipt = read_receipt(repo)
    mismatch = receipt["result"]["base_model"]["first_mismatch"]
    assert mismatch["kind"] == "tensor_schema"
    assert mismatch["tensor"] == "model.norm.weight"
    counts = receipt["result"]["base_model"]["counts"]
    assert counts["schema_mismatch_tensor_count"] == 1
    assert counts["shape_mismatch_tensor_count"] == shape_count
    assert counts["dtype_mismatch_tensor_count"] == dtype_count
    assert counts["total_mismatch_tensor_count"] == 1


def test_unsafe_index_path_writes_error_receipt(tmp_path: Path) -> None:
    repo, arguments = make_fixture(tmp_path)
    index_path = repo / "models/candidate/model.safetensors.index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    first_name = sorted(index["weight_map"])[0]
    index["weight_map"][first_name] = "../outside.safetensors"
    write_json(index_path, index)

    assert oracle.main(arguments) == 2
    receipt = read_receipt(repo)
    assert receipt["status"] == "ERROR"
    assert receipt["result"]["passed"] is False
    assert receipt["result"]["error"]["type"] == "OracleVerificationError"
    assert "Unsafe shard path" in receipt["result"]["error"]["message"]


def test_existing_output_requires_overwrite_and_is_atomically_replaced(tmp_path: Path) -> None:
    repo, arguments = make_fixture(tmp_path)
    assert oracle.main(arguments) == 0
    output = repo / "receipts/FULL_MODEL_ORACLE.json"
    original = output.read_bytes()

    tensors = base_tensors()
    tensors["lm_head.weight"] = tensors["lm_head.weight"].clone()
    tensors["lm_head.weight"].reshape(-1)[0] += 1
    write_indexed_model(repo / "models/candidate", tensors)

    assert oracle.main(arguments) == 2
    assert output.read_bytes() == original
    assert oracle.main([*arguments, "--overwrite"]) == 1
    assert output.read_bytes() != original
    assert read_receipt(repo)["status"] == "FAIL"
    assert not list(output.parent.glob(f".{output.name}.*.tmp"))


def test_receipt_output_inside_model_tree_is_rejected_without_writing(tmp_path: Path) -> None:
    repo, arguments = make_fixture(tmp_path)
    output_index = arguments.index("--output") + 1
    arguments[output_index] = "models/candidate/receipt.json"

    assert oracle.main(arguments) == 2
    assert not (repo / "models/candidate/receipt.json").exists()


def test_receipt_output_cannot_replace_verifier_implementation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, arguments = make_fixture(tmp_path)
    implementation = repo / "scripts/verifier.py"
    implementation.parent.mkdir(parents=True)
    implementation.write_text("# frozen verifier\n", encoding="utf-8")
    original = implementation.read_bytes()
    monkeypatch.setattr(oracle, "__file__", str(implementation))
    arguments[arguments.index("--output") + 1] = "scripts/verifier.py"

    assert oracle.main([*arguments, "--overwrite"]) == 2
    assert implementation.read_bytes() == original


def test_verifier_implementation_hash_must_remain_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, arguments = make_fixture(tmp_path)
    implementation = Path(oracle.__file__).resolve()
    original_sha256_file = oracle.sha256_file
    implementation_hash_calls = 0

    def unstable_implementation_hash(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
        nonlocal implementation_hash_calls
        if Path(path).resolve() == implementation:
            implementation_hash_calls += 1
            return ("a" if implementation_hash_calls == 1 else "b") * 64
        return original_sha256_file(path, chunk_size=chunk_size)

    monkeypatch.setattr(oracle, "sha256_file", unstable_implementation_hash)
    assert oracle.main(arguments) == 2
    receipt = read_receipt(repo)
    assert receipt["status"] == "ERROR"
    assert "implementation changed during comparison" in receipt["result"]["error"]["message"]
    assert implementation_hash_calls == 2


def test_optional_run_bundle_passes_stable_state_and_metrics_rules(tmp_path: Path) -> None:
    repo, arguments = make_bundle_fixture(tmp_path)

    assert oracle.main(arguments) == 0
    receipt = read_receipt(repo)
    assert receipt["status"] == "PASS"
    bundle = receipt["result"]["run_bundle"]
    assert bundle["enabled"] is True
    assert bundle["passed"] is True
    assert bundle["candidate_run_root"] == "runs/candidate"
    assert bundle["oracle_run_root"] == "runs/oracle"
    assert bundle["artifact_inventories_stable"] is True
    assert bundle["comparisons"]["workspace_state"]["passed"] is True
    trainer = bundle["comparisons"]["trainer_state"]
    assert trainer["passed"] is True
    assert trainer["excluded_paths"] == ["$.run_state.run_id"]
    assert "optimizer" in trainer["required_stable_fields"]
    assert "rng_by_rank" in trainer["required_stable_fields"]
    metrics = bundle["comparisons"]["stable_metrics"]
    assert metrics["passed"] is True
    assert "time" in metrics["ignored_dynamic_fields"]
    assert "checkpoint" in metrics["ignored_dynamic_fields"]
    assert metrics["counts"]["candidate_raw_record_count"] == 3
    assert metrics["counts"]["candidate_stable_record_count"] == 2
    assert receipt["stability"]["run_bundle_artifact_inventories_equal"] is True
    provenance = bundle["bundle_provenance"]
    assert provenance["intended_global_step"] == {
        "source": "each_final_manifest.global_step",
        "candidate": 8,
        "oracle": 8,
        "equal": True,
    }
    for side in ("candidate", "oracle"):
        assert provenance[side]["manifest"]["complete"] is True
        assert provenance[side]["experiment_config"]["manifest_config_sha256_exact"] is True
        assert provenance[side]["experiment_config"]["manifest_resume_signature_exact"] is True
        assert provenance[side]["trainer_manifest_binding"]["passed"] is True
        assert provenance[side]["trainer_manifest_binding"]["checks"]["world_size_exact"] is True
        assert (
            provenance[side]["trainer_manifest_binding"]["checks"][
                "data_fingerprint_exact"
            ]
            is True
        )
        assert "data_fingerprint" not in provenance[side]["manifest"]
        assert len(provenance[side]["manifest"]["data_fingerprint_sha256"]) == 64


def test_optional_run_bundle_trainer_difference_is_bounded_fail(tmp_path: Path) -> None:
    repo, arguments = make_bundle_fixture(tmp_path)
    trainer_path = repo / "runs/candidate/final/trainer_state.pt"
    state = torch.load(trainer_path, map_location="cpu", weights_only=False)
    state["optimizer"]["state"][0]["exp_avg_sq_row"][0] += 1
    torch.save(state, trainer_path)

    assert oracle.main(arguments) == 1
    receipt = read_receipt(repo)
    assert receipt["result"]["base_model"]["passed"] is True
    bundle = receipt["result"]["run_bundle"]
    assert bundle["passed"] is False
    assert bundle["comparisons"]["trainer_state"]["passed"] is False
    assert bundle["comparisons"]["trainer_state"]["first_mismatch"] == {
        "path": "$.optimizer.state.0.exp_avg_sq_row",
        "kind": "tensor_bytes",
    }
    assert receipt["result"]["first_mismatch"]["scope"] == "run_bundle"
    encoded = json.dumps(bundle["comparisons"]["trainer_state"], sort_keys=True)
    assert "candidate_value" not in encoded
    assert "oracle_value" not in encoded


def test_optional_run_bundle_stable_metric_difference_is_fail(tmp_path: Path) -> None:
    repo, arguments = make_bundle_fixture(tmp_path)
    candidate_run = repo / "runs/candidate"
    write_bundle(
        candidate_run,
        run_id="spill-run",
        reverse_assignment=False,
        dynamic_offset=1.0,
        stable_loss=9.0,
    )

    assert oracle.main(arguments) == 1
    receipt = read_receipt(repo)
    metrics = receipt["result"]["run_bundle"]["comparisons"]["stable_metrics"]
    assert metrics["passed"] is False
    assert metrics["counts"]["value_mismatch_record_count"] == 1
    assert metrics["first_mismatch"] == {
        "kind": "stable_record_values",
        "key": ["train", 8],
        "mismatched_field_count": 1,
        "first_mismatched_field": "task_loss",
    }


def test_cross_offload_parity_binds_allowed_config_and_signature_differences(
    tmp_path: Path,
) -> None:
    repo, arguments = make_cross_offload_bundle_fixture(tmp_path)

    assert oracle.main(arguments) == 0
    receipt = read_receipt(repo)
    assert receipt["status"] == "PASS"
    assert receipt["claims"]["comparison_mode"] == "cross_offload_parity"
    source_claim = receipt["claims"]["source_evidence"]
    assert source_claim["source_identity_verified"] is True
    assert source_claim["current_source_matched"] is False
    assert source_claim["source_comparison_mode"] == "cross_source_identity"
    assert source_claim["candidate_validated_source_sha256"] == "a" * 64
    assert source_claim["oracle_validated_source_sha256"] == "b" * 64
    assert source_claim["source_evidence_documents_sha256_matched"] is False

    bundle = receipt["result"]["run_bundle"]
    assert bundle["mode"] == "cross_offload_parity"
    config = bundle["cross_offload_config_comparison"]
    assert config["passed"] is True
    assert [item["path"] for item in config["observed_differences"]] == [
        "train.gradient_accumulation_offload",
        "train.output_dir",
        "train.resume_from",
    ]
    assert config["candidate_offload"] == "cpu"
    assert config["oracle_effective_offload"] == "none"
    assert config["oracle_legacy_d5_missing_field_default_applied"] is False
    assert config["observed_differences"][0]["candidate"]["value"] == "cpu"
    assert config["observed_differences"][0]["oracle"]["value"] == "none"

    trainer = bundle["comparisons"]["trainer_state"]
    assert trainer["passed"] is True
    assert trainer["excluded_paths"] == [
        "$.resume_signature",
        "$.run_state.run_id",
        "$.structural_resume_signature",
    ]
    signatures = bundle["cross_offload_trainer_signature_bindings"]
    resume = signatures["resume_signature"]
    provenance = bundle["bundle_provenance"]
    assert resume["candidate_value"] == provenance["candidate"]["manifest"]["resume_signature"]
    assert resume["oracle_value"] == provenance["oracle"]["manifest"]["resume_signature"]
    assert resume["values_equal"] is False
    assert resume["candidate_value_utf8_sha256"] == oracle.sha256_bytes(
        resume["candidate_value"].encode("utf-8")
    )
    encoded = json.dumps(receipt, sort_keys=True)
    assert "/remote/private/candidate-output" not in encoded
    assert "/remote/private/oracle-output" not in encoded
    assert "/remote/private/candidate-checkpoint" not in encoded


@pytest.mark.parametrize("oracle_gradient_offload", ["none", "cpu"])
def test_cross_transport_parity_binds_activation_and_gradient_modes(
    tmp_path: Path,
    oracle_gradient_offload: str,
) -> None:
    repo, arguments = make_cross_transport_bundle_fixture(
        tmp_path,
        oracle_gradient_accumulation_offload=oracle_gradient_offload,
    )

    assert oracle.main(arguments) == 0
    receipt = read_receipt(repo)
    assert receipt["status"] == "PASS"
    assert receipt["claims"]["comparison_mode"] == "cross_transport_parity"

    bundle = receipt["result"]["run_bundle"]
    assert bundle["mode"] == "cross_transport_parity"
    assert bundle["cross_offload_config_comparison"] is None
    assert bundle["cross_offload_trainer_signature_bindings"] is None
    config = bundle["transport_config_comparison"]
    assert config["passed"] is True
    assert config["candidate_base_activation_offload"] == "all_base"
    assert config["oracle_base_activation_offload"] == "legacy_functional"
    assert config["candidate_gradient_accumulation_offload"] == "none"
    assert config["oracle_gradient_accumulation_offload"] == oracle_gradient_offload
    observed = {
        item["path"]: item for item in config["observed_differences"]
    }
    assert observed["train.base_activation_offload"]["candidate"]["value"] == "all_base"
    assert observed["train.base_activation_offload"]["oracle"]["value"] == (
        "legacy_functional"
    )
    if oracle_gradient_offload == "cpu":
        assert observed["train.gradient_accumulation_offload"]["candidate"]["value"] == (
            "none"
        )
        assert observed["train.gradient_accumulation_offload"]["oracle"]["value"] == "cpu"
    else:
        assert "train.gradient_accumulation_offload" not in observed

    trainer = bundle["comparisons"]["trainer_state"]
    assert trainer["passed"] is True
    assert trainer["excluded_paths"] == [
        "$.resume_signature",
        "$.run_state.run_id",
        "$.structural_resume_signature",
    ]
    signatures = bundle["transport_trainer_signature_bindings"]
    assert signatures["resume_signature"]["values_equal"] is False
    encoded = json.dumps(receipt, sort_keys=True)
    assert "/remote/private/candidate-output" not in encoded
    assert "/remote/private/oracle-output" not in encoded


def test_cross_transport_parity_accepts_cpu_accumulate_against_cuda_merge(
    tmp_path: Path,
) -> None:
    repo, arguments = make_cross_transport_bundle_fixture(
        tmp_path,
        oracle_gradient_accumulation_offload="cpu",
    )
    candidate_config_path = repo / "runs/candidate/final/experiment_config.json"
    candidate_config = json.loads(candidate_config_path.read_text(encoding="utf-8"))
    candidate_config["train"]["base_activation_offload"] = "legacy_functional"
    candidate_config["train"]["gradient_accumulation_offload"] = "cpu_accumulate"
    write_json(candidate_config_path, candidate_config)
    rebind_bundle_provenance(repo / "runs/candidate")

    assert oracle.main(arguments) == 0
    receipt = read_receipt(repo)
    config = receipt["result"]["run_bundle"]["transport_config_comparison"]
    assert config["candidate_base_activation_offload"] == "legacy_functional"
    assert config["oracle_base_activation_offload"] == "legacy_functional"
    assert config["candidate_gradient_accumulation_offload"] == "cpu_accumulate"
    assert config["oracle_gradient_accumulation_offload"] == "cpu"
    paths = [item["path"] for item in config["observed_differences"]]
    assert "train.base_activation_offload" not in paths
    assert "train.gradient_accumulation_offload" in paths


def test_cross_transport_parity_rejects_non_allowlisted_config_difference(
    tmp_path: Path,
) -> None:
    repo, arguments = make_cross_transport_bundle_fixture(tmp_path)
    candidate_config_path = repo / "runs/candidate/final/experiment_config.json"
    candidate_config = json.loads(candidate_config_path.read_text(encoding="utf-8"))
    candidate_config["train"]["micro_batch_size"] = 2
    write_json(candidate_config_path, candidate_config)
    rebind_bundle_provenance(repo / "runs/candidate")

    assert oracle.main(arguments) == 2
    receipt = read_receipt(repo)
    assert receipt["status"] == "ERROR"
    message = receipt["result"]["error"]["message"]
    assert "non-allowlisted semantic difference" in message
    assert "train.micro_batch_size" in message


def test_transport_parity_flags_are_mutually_exclusive(tmp_path: Path) -> None:
    _repo, arguments = make_cross_transport_bundle_fixture(tmp_path)
    arguments.append("--cross-offload-parity")

    with pytest.raises(SystemExit) as exc_info:
        oracle.build_parser().parse_args(arguments)

    assert exc_info.value.code == 2


def test_default_bundle_does_not_exclude_cross_offload_signatures(tmp_path: Path) -> None:
    repo, arguments = make_cross_offload_bundle_fixture(tmp_path)
    arguments.remove("--cross-offload-parity")

    assert oracle.main(arguments) == 1
    receipt = read_receipt(repo)
    bundle = receipt["result"]["run_bundle"]
    assert bundle["mode"] == "strict_general"
    trainer = bundle["comparisons"]["trainer_state"]
    assert trainer["passed"] is False
    assert trainer["excluded_paths"] == ["$.run_state.run_id"]
    assert trainer["first_mismatch"] == {
        "path": "$.resume_signature",
        "kind": "scalar",
    }
    assert bundle["cross_offload_config_comparison"] is None
    assert bundle["cross_offload_trainer_signature_bindings"] is None


def test_cross_offload_parity_rejects_non_allowlisted_config_difference(
    tmp_path: Path,
) -> None:
    repo, arguments = make_cross_offload_bundle_fixture(tmp_path)
    candidate_config_path = repo / "runs/candidate/final/experiment_config.json"
    candidate_config = json.loads(candidate_config_path.read_text(encoding="utf-8"))
    candidate_config["train"]["micro_batch_size"] = 2
    write_json(candidate_config_path, candidate_config)
    rebind_bundle_provenance(repo / "runs/candidate")

    assert oracle.main(arguments) == 2
    receipt = read_receipt(repo)
    assert receipt["status"] == "ERROR"
    message = receipt["result"]["error"]["message"]
    assert "non-allowlisted semantic difference" in message
    assert "train.micro_batch_size" in message


def test_cross_offload_parity_rejects_wrong_candidate_mode(tmp_path: Path) -> None:
    repo, arguments = make_cross_offload_bundle_fixture(tmp_path)
    candidate_config_path = repo / "runs/candidate/final/experiment_config.json"
    candidate_config = json.loads(candidate_config_path.read_text(encoding="utf-8"))
    candidate_config["train"]["gradient_accumulation_offload"] = "none"
    write_json(candidate_config_path, candidate_config)
    rebind_bundle_provenance(repo / "runs/candidate")

    assert oracle.main(arguments) == 2
    receipt = read_receipt(repo)
    assert "requires candidate" in receipt["result"]["error"]["message"]


def test_missing_oracle_offload_requires_bound_legacy_d5_identity(tmp_path: Path) -> None:
    repo, arguments = make_cross_offload_bundle_fixture(tmp_path)
    oracle_config_path = repo / "runs/oracle/final/experiment_config.json"
    oracle_config = json.loads(oracle_config_path.read_text(encoding="utf-8"))
    del oracle_config["train"]["gradient_accumulation_offload"]
    write_json(oracle_config_path, oracle_config)
    rebind_bundle_provenance(repo / "runs/oracle")

    assert oracle.main(arguments) == 2
    receipt = read_receipt(repo)
    assert "legacy d5 engine" in receipt["result"]["error"]["message"]


def test_missing_oracle_offload_passes_only_with_bound_legacy_d5_identity(
    tmp_path: Path,
) -> None:
    repo, arguments = make_cross_offload_bundle_fixture(tmp_path)
    oracle_config_path = repo / "runs/oracle/final/experiment_config.json"
    oracle_config = json.loads(oracle_config_path.read_text(encoding="utf-8"))
    del oracle_config["train"]["gradient_accumulation_offload"]
    write_json(oracle_config_path, oracle_config)
    rebind_bundle_provenance(repo / "runs/oracle", source_sha256=oracle.OLD_D5_ENGINE_SHA256)
    write_json(
        repo / "evidence/oracle_source.json",
        {"engine_sha256": oracle.OLD_D5_ENGINE_SHA256},
    )

    assert oracle.main(arguments) == 0
    receipt = read_receipt(repo)
    config = receipt["result"]["run_bundle"]["cross_offload_config_comparison"]
    assert config["oracle_offload_field_present"] is False
    assert config["oracle_legacy_d5_missing_field_default_applied"] is True
    assert config["oracle_legacy_d5_missing_field_authorized"] is True
    assert config["oracle_final_manifest_is_legacy_d5"] is True
    bindings = config["oracle_legacy_d5_engine_evidence_bindings"]
    assert bindings == [
        {
            "evidence_path": "evidence/oracle_source.json",
            "json_path": "$.engine_sha256",
            "engine_sha256": oracle.OLD_D5_ENGINE_SHA256,
        }
    ]
    gradient = config["observed_differences"][0]
    assert gradient["oracle"]["present"] is False
    assert gradient["oracle_effective"]["value"] == "none"


def test_unrelated_d5_evidence_cannot_authorize_legacy_missing_offload(
    tmp_path: Path,
) -> None:
    repo, arguments = make_cross_offload_bundle_fixture(tmp_path)
    oracle_config_path = repo / "runs/oracle/final/experiment_config.json"
    oracle_config = json.loads(oracle_config_path.read_text(encoding="utf-8"))
    del oracle_config["train"]["gradient_accumulation_offload"]
    write_json(oracle_config_path, oracle_config)
    rebind_bundle_provenance(repo / "runs/oracle")
    write_json(
        repo / "evidence/oracle_run.json",
        {"engine_sha256": oracle.OLD_D5_ENGINE_SHA256, "run_id": "native-run"},
    )

    assert oracle.main(arguments) == 2
    receipt = read_receipt(repo)
    assert "oracle final manifest.source_sha256" in receipt["result"]["error"]["message"]


def test_run_evidence_cannot_rescue_missing_source_identity_binding(tmp_path: Path) -> None:
    repo, arguments = make_cross_offload_bundle_fixture(tmp_path)
    oracle_config_path = repo / "runs/oracle/final/experiment_config.json"
    oracle_config = json.loads(oracle_config_path.read_text(encoding="utf-8"))
    del oracle_config["train"]["gradient_accumulation_offload"]
    write_json(oracle_config_path, oracle_config)
    rebind_bundle_provenance(
        repo / "runs/oracle", source_sha256=oracle.OLD_D5_ENGINE_SHA256
    )
    write_json(
        repo / "evidence/oracle_run.json",
        {"engine_sha256": oracle.OLD_D5_ENGINE_SHA256, "run_id": "native-run"},
    )

    assert oracle.main(arguments) == 2
    receipt = read_receipt(repo)
    assert receipt["status"] == "ERROR"
    assert "absent from its bound source evidence" in receipt["result"]["error"]["message"]


def test_shared_multi_identity_source_document_is_rejected(tmp_path: Path) -> None:
    repo, arguments = make_cross_offload_bundle_fixture(tmp_path)
    write_json(
        repo / "evidence/shared_source.json",
        {"engine_sha256": "a" * 64, "source_sha256": "b" * 64},
    )
    arguments[arguments.index("--candidate-source-evidence") + 1] = (
        "evidence/shared_source.json"
    )
    arguments[arguments.index("--oracle-source-evidence") + 1] = (
        "evidence/shared_source.json"
    )

    assert oracle.main(arguments) == 2
    receipt = read_receipt(repo)
    assert receipt["status"] == "ERROR"
    assert "multiple recognized engine identities" in receipt["result"]["error"]["message"]


@pytest.mark.parametrize(
    ("scope", "expected_message"),
    [
        ("config", "config_sha256 does not bind"),
        ("source", "source_sha256 is absent"),
        ("trainer_run_id", "run_state_run_id_exact"),
        ("global_step", "same intended global_step"),
        ("world_size", "world_size_exact"),
        ("data_fingerprint", "data_fingerprint_exact"),
    ],
)
def test_bundle_provenance_tamper_fails_closed(
    tmp_path: Path,
    scope: str,
    expected_message: str,
) -> None:
    repo, arguments = make_bundle_fixture(tmp_path)
    candidate_final = repo / "runs/candidate/final"
    oracle_final = repo / "runs/oracle/final"
    if scope == "config":
        config_path = candidate_final / "experiment_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["train"]["max_steps"] = 9
        write_json(config_path, config)
    elif scope == "source":
        manifest_path = candidate_final / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["source_sha256"] = "9" * 64
        write_json(manifest_path, manifest)
    elif scope == "trainer_run_id":
        trainer_path = candidate_final / "trainer_state.pt"
        trainer = torch.load(trainer_path, map_location="cpu", weights_only=False)
        trainer["run_state"]["run_id"] = "tampered-run"
        torch.save(trainer, trainer_path)
    elif scope == "global_step":
        manifest_path = oracle_final / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["global_step"] = 7
        write_json(manifest_path, manifest)
    elif scope == "world_size":
        manifest_path = candidate_final / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["world_size"] = 2
        write_json(manifest_path, manifest)
    elif scope == "data_fingerprint":
        manifest_path = candidate_final / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["data_fingerprint"] = {"files": [{"sha256": "d" * 64}]}
        write_json(manifest_path, manifest)
    else:  # pragma: no cover - parameterization guard
        raise AssertionError(scope)

    assert oracle.main(arguments) == 2
    receipt = read_receipt(repo)
    assert receipt["status"] == "ERROR"
    assert expected_message in receipt["result"]["error"]["message"]


def make_large_mismatch_fixture(tmp_path: Path) -> tuple[Path, list[str]]:
    repo, arguments = make_fixture(tmp_path)
    reference_tensors = base_tensors()
    reference_tensors["model.embed_tokens.weight"] = torch.arange(
        8192, dtype=torch.float32
    ).reshape(2048, 4)
    candidate_tensors = {
        name: tensor.detach().clone() for name, tensor in reference_tensors.items()
    }
    candidate_tensors["model.embed_tokens.weight"].add_(1)
    write_indexed_model(repo / "models/candidate", candidate_tensors)
    write_indexed_model(repo / "models/oracle", reference_tensors, reverse_assignment=True)
    return repo, arguments


def test_large_mismatch_is_counted_within_declared_buffer_budget_without_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, arguments = make_large_mismatch_fixture(tmp_path)

    def forbidden_nonzero(*args: object, **kwargs: object) -> object:
        raise AssertionError("torch.nonzero must not be used for first mismatch")

    monkeypatch.setattr(torch, "nonzero", forbidden_nonzero)
    assert oracle.main(arguments) == 1
    receipt = read_receipt(repo)
    base = receipt["result"]["base_model"]
    assert base["counts"]["byte_mismatch_element_count"] == 8192
    assert base["first_mismatch"] == {
        "kind": "tensor_bytes",
        "tensor": "model.embed_tokens.weight",
        "first_flat_element_index": 0,
    }
    budget = base["tensor_buffer_budget"]
    assert budget["max_working_set_bytes"] == 128
    assert budget["max_estimated_tensor_buffer_bytes"] == 96
    assert budget["within_budget"] is True
    assert "2 * element_bytes input_slices" in budget["worst_case_equation"]
    assert budget["first_mismatch_search"].endswith("no_index_vector")


def test_single_row_budget_is_fail_closed_before_comparison(tmp_path: Path) -> None:
    repo, arguments = make_large_mismatch_fixture(tmp_path)
    budget_index = arguments.index("--max-working-set-bytes") + 1
    arguments[budget_index] = "91"

    assert oracle.main(arguments) == 2
    receipt = read_receipt(repo)
    message = receipt["result"]["error"]["message"]
    assert "single tensor row exceeds" in message
    assert "92 > 91" in message


def test_base_only_document_match_does_not_claim_current_source_identity(
    tmp_path: Path,
) -> None:
    repo, arguments = make_fixture(tmp_path)
    candidate_source = json.loads(
        (repo / "evidence/candidate_source.json").read_text(encoding="utf-8")
    )
    write_json(repo / "evidence/oracle_source.json", candidate_source)

    assert oracle.main(arguments) == 0
    source_claim = read_receipt(repo)["claims"]["source_evidence"]
    assert source_claim["source_identity_verified"] is False
    assert source_claim["current_source_matched"] is None
    assert (
        source_claim["source_comparison_mode"]
        == "base_model_only_source_identity_unverified"
    )
    assert source_claim["source_evidence_documents_sha256_matched"] is True
    assert source_claim["candidate_validated_source_sha256"] is None
    assert source_claim["oracle_validated_source_sha256"] is None


def test_bundle_current_source_claim_requires_equal_validated_manifest_identities(
    tmp_path: Path,
) -> None:
    repo, arguments = make_cross_offload_bundle_fixture(tmp_path)
    rebind_bundle_provenance(repo / "runs/oracle", source_sha256="a" * 64)
    arguments[arguments.index("--oracle-source-evidence") + 1] = (
        "evidence/candidate_source.json"
    )

    assert oracle.main(arguments) == 0
    source_claim = read_receipt(repo)["claims"]["source_evidence"]
    assert source_claim["source_identity_verified"] is True
    assert source_claim["current_source_matched"] is True
    assert source_claim["source_comparison_mode"] == "current_source_matched"
    assert source_claim["candidate_validated_source_sha256"] == "a" * 64
    assert source_claim["oracle_validated_source_sha256"] == "a" * 64
    assert source_claim["source_evidence_documents_sha256_matched"] is True


def test_each_safetensors_index_is_parsed_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, arguments = make_fixture(tmp_path)
    original = oracle.read_json_object
    index_labels: list[str] = []

    def counted_read(path: Path, *, label: str) -> dict[str, object]:
        if label == "safetensors index":
            index_labels.append(path.name)
        return original(path, label=label)

    monkeypatch.setattr(oracle, "read_json_object", counted_read)
    assert oracle.main(arguments) == 0
    assert index_labels == ["model.safetensors.index.json", "model.safetensors.index.json"]
