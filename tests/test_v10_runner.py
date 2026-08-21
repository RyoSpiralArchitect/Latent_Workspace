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

prefetch = importlib.import_module("prefetch_v10_model")
runner = importlib.import_module("run_v10_matrix")
pruning = importlib.import_module("prune_v10_verified_run")

MODEL = "mistralai/Mistral-7B-Instruct-v0.3"
REVISION = "c170c708c41dac9275d15a8fff4eca08d52bab71"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(runner.canonical_json_bytes(value))


def write_synthetic_gradient_offload_receipt(
    path: Path,
    *,
    run_id: str,
    source_sha256: str,
    resume_signature: str,
    initial_step: int,
    final_step: int,
    accumulation_steps: int,
    parameter_count: int,
    parameter_numel: int,
    gradient_capacity_bytes: int,
    initial_checkpoint: dict[str, object] | None = None,
) -> dict[str, object]:
    windows = final_step - initial_step
    counters = {
        "windows_started": windows,
        "windows_restored": windows,
        "windows_discarded": 0,
        "single_microbatch_windows": 0,
        "microbatch_spills": accumulation_steps * windows,
        "parameter_first_spills": parameter_count * windows,
        "parameter_merges": parameter_count * windows * (accumulation_steps - 1),
        "cumulative_current_gradient_bytes": (
            gradient_capacity_bytes * accumulation_steps * windows
        ),
        "peak_cpu_accumulator_bytes": gradient_capacity_bytes,
    }
    receipt: dict[str, object] = {
        "schema_version": pruning.GRADIENT_OFFLOAD_SCHEMA_VERSION,
        "mode": runner.GRADIENT_ACCUMULATION_OFFLOAD,
        "algorithm": pruning.GRADIENT_OFFLOAD_ALGORITHM,
        "claim_boundary": {
            "execution_proof": "synthetic execution proof",
            "numerical_proof": "synthetic numerical boundary",
            "unsupported": "synthetic unsupported boundary",
        },
        "run_id": run_id,
        "source_sha256": source_sha256,
        "resume_signature": resume_signature,
        "configured_gradient_accumulation_steps": accumulation_steps,
        "initial_global_step": initial_step,
        "last_observed_global_step": final_step,
        "last_restored_global_step": final_step - 1,
        "final_global_step": final_step,
        "trainable_parameter_count": parameter_count,
        "trainable_parameter_total_numel": parameter_numel,
        "trainable_gradient_capacity_bytes": gradient_capacity_bytes,
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


def replace_json_field(
    path: Path,
    section: str,
    key: str,
    value: object,
) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    document[section][key] = value
    write_json(path, document)


def initial_tensors() -> dict[str, torch.Tensor]:
    return {
        "lm_head.weight": torch.arange(12, 24, dtype=torch.float32).reshape(4, 3),
        "model.embed_tokens.weight": torch.arange(
            12, dtype=torch.float32
        ).reshape(4, 3),
    }


def write_weight_tree(path: Path, tensors: dict[str, torch.Tensor]) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    items = sorted(tensors.items())
    if len(items) != 2:
        raise ValueError("Synthetic runner fixtures require exactly two tensors.")
    weight_map: dict[str, str] = {}
    for index, (name, tensor) in enumerate(items, start=1):
        shard_name = f"model-{index:05d}-of-00002.safetensors"
        save_file({name: tensor.contiguous()}, str(path / shard_name))
        weight_map[name] = shard_name
    write_json(
        path / "model.safetensors.index.json",
        {
            "metadata": {
                "total_size": sum(
                    tensor.numel() * tensor.element_size() for tensor in tensors.values()
                )
            },
            "weight_map": weight_map,
        },
    )
    return path


def make_snapshot(path: Path) -> Path:
    path.mkdir(parents=True)
    write_json(path / "config.json", {"model_type": "mistral"})
    write_json(path / "tokenizer.json", {"version": "synthetic"})
    write_weight_tree(path, initial_tensors())
    return path


def make_prefetch_receipt(snapshot: Path, path: Path) -> Path:
    receipt = prefetch.build_receipt(
        snapshot=snapshot,
        model_id=MODEL,
        requested_revision=REVISION,
        resolved_revision=REVISION,
        validation={
            "config_loaded": True,
            "tokenizer_loaded": True,
            "model_type": "mistral",
            "tokenizer_class": "SyntheticTokenizer",
            "trust_remote_code": False,
        },
    )
    prefetch.atomic_write_json(path, receipt)
    return path


def make_repo(tmp_path: Path, *, profile: str = "smoke") -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    condition_dir = repo / "configs" / "v10" / "conditions"
    data_dir = repo / "data" / "v10"
    source_dir = repo / "src" / "latent_workspace_ft_v10"
    script_dir = repo / "scripts"
    reference_dir = repo / "configs" / "v9_reference"
    for directory in (condition_dir, data_dir, source_dir, script_dir, reference_dir):
        directory.mkdir(parents=True, exist_ok=True)

    train = data_dir / "functional_train.jsonl"
    evaluation = data_dir / "functional_eval.jsonl"
    train.write_text('{"split":"train"}\n', encoding="utf-8")
    evaluation.write_text('{"split":"eval"}\n', encoding="utf-8")
    data_manifest = data_dir / "MANIFEST.json"
    write_json(data_manifest, {"format": "synthetic-data-v1"})

    engine = source_dir / "engine.py"
    engine.write_text("# synthetic engine source\n", encoding="utf-8")
    (source_dir / "__init__.py").write_text("\n", encoding="utf-8")
    (source_dir / "__main__.py").write_text("\n", encoding="utf-8")
    write_json(
        source_dir / "source_manifest.json",
        {
            "patched_engine": {
                "path": "src/latent_workspace_ft_v10/engine.py",
                "sha256": runner.sha256_file(engine),
            }
        },
    )

    preparer = script_dir / "prepare.py"
    reference = reference_dir / "MATRIX.json"
    preparer.write_text("# synthetic preparer\n", encoding="utf-8")
    write_json(reference, {"legacy": True})

    condition = condition_dir / "config_F0_query_only.json"
    write_json(
        condition,
        {
            "model": {
                "attn_implementation": "sdpa",
                "name_or_path": MODEL,
                "revision": REVISION,
                "train_mode": "full",
                "local_files_only": False,
                "trust_remote_code": False,
            },
            "train": {
                "seed": 999,
                "max_steps": 999,
                "output_dir": "../../../runs/placeholder",
                "resume_from": "auto",
                "device": "cuda",
                "mixed_precision": "bf16",
                "optimizer": "adafactor",
                "gradient_accumulation_steps": 8,
                "cuda_allocator_conf": runner.CUDA_ALLOCATOR_CONF,
                "gradient_accumulation_offload": (
                    runner.GRADIENT_ACCUMULATION_OFFLOAD
                ),
            },
            "data": {
                "train_files": ["../../../data/v10/functional_train.jsonl"],
                "eval_files": ["../../../data/v10/functional_eval.jsonl"],
            },
            "assays": {"recruitment": {"train_files": [], "eval_files": []}},
        },
    )

    matrix_path = repo / "configs" / "v10" / "profiles" / profile / "MATRIX.json"
    matrix = {
        "format": runner.MATRIX_FORMAT,
        "profile": profile,
        "path_base": "repository_root",
        "expected_run_count": 1,
        "max_steps": 8,
        "model": {"name_or_path": MODEL, "revision": REVISION},
        "runtime": {
            "cuda_allocator_conf": runner.CUDA_ALLOCATOR_CONF,
            "gradient_accumulation_offload": (
                runner.GRADIENT_ACCUMULATION_OFFLOAD
            ),
        },
        "runs": [
            {
                "run_id": "F0_query_only/seed_42",
                "condition": "F0_query_only",
                "condition_config": "configs/v10/conditions/config_F0_query_only.json",
                "seed": 42,
                "max_steps": 8,
                "output_dir": f"runs/v10/{profile}/F0_query_only/seed_42",
            }
        ],
    }
    write_json(matrix_path, matrix)
    if profile != "smoke":
        smoke_matrix = dict(matrix)
        smoke_matrix["profile"] = "smoke"
        smoke_matrix["runs"] = [dict(matrix["runs"][0])]
        smoke_matrix["runs"][0]["output_dir"] = "runs/v10/smoke/F0_query_only/seed_42"
        write_json(repo / "configs/v10/profiles/smoke/MATRIX.json", smoke_matrix)

    contract = {
        "format": runner.CONTRACT_FORMAT,
        "model": {
            "attention_implementation": "sdpa",
            "dtype": "bfloat16",
            "name_or_path": MODEL,
            "revision": REVISION,
            "train_mode": "full",
        },
        "runtime": {
            "backend": "cuda",
            "optimizer": "adafactor",
            "cuda_allocator_conf": runner.CUDA_ALLOCATOR_CONF,
            "gradient_accumulation_offload": (
                runner.GRADIENT_ACCUMULATION_OFFLOAD
            ),
        },
        "matrix": {
            "profiles": {
                profile: {"run_count": 1, "max_steps": 8},
                "smoke": {"run_count": 1, "max_steps": 8},
            }
        },
        "source": {
            "preparation_scripts": {
                "scripts/prepare.py": runner.sha256_file(preparer),
            },
            "runtime_sources": {
                "src/latent_workspace_ft_v10/engine.py": runner.sha256_file(engine),
                "src/latent_workspace_ft_v10/source_manifest.json": runner.sha256_file(
                    source_dir / "source_manifest.json"
                ),
            },
            "v9_reference_files": {
                "configs/v9_reference/MATRIX.json": runner.sha256_file(reference),
            },
        },
        "data": {
            "manifest": "data/v10/MANIFEST.json",
            "manifest_sha256": runner.sha256_file(data_manifest),
            "remapped_output_sha256": {
                "train": runner.sha256_file(train),
                "eval": runner.sha256_file(evaluation),
            },
        },
    }
    write_json(repo / "configs/v10/CONTRACT.json", contract)

    snapshot = make_snapshot(repo / "runs" / "v10" / "model_cache" / "snapshot")
    receipt = make_prefetch_receipt(
        snapshot,
        repo / "runs" / "v10" / "model_cache" / "MODEL_PREFETCH_RECEIPT.json",
    )
    return repo, snapshot, receipt


def options(
    repo: Path,
    snapshot: Path,
    receipt: Path,
    *,
    profile: str = "smoke",
) -> runner.RunnerOptions:
    return runner.RunnerOptions(
        repo_root=repo,
        profile=profile,
        matrix_path=Path(f"configs/v10/profiles/{profile}/MATRIX.json"),
        contract_path=Path("configs/v10/CONTRACT.json"),
        model_receipt=receipt.relative_to(repo),
        model_snapshot=snapshot,
        minimum_free_disk_gib=0,
        minimum_free_vram_gib=0,
    )


def make_stub(
    path: Path,
    *,
    unchanged_tensor: str | None = None,
    dynamic_evidence: str = "valid",
) -> Path:
    if dynamic_evidence not in {"valid", "zero", "missing"}:
        raise ValueError(f"Unsupported synthetic dynamic evidence: {dynamic_evidence}")
    source = """
import json
import os
import sys
import hashlib
from pathlib import Path

import torch
from safetensors.torch import save_file

UNCHANGED_TENSOR = __UNCHANGED_TENSOR__
DYNAMIC_EVIDENCE = __DYNAMIC_EVIDENCE__

config_path = Path(sys.argv[1]).resolve()
config = json.loads(config_path.read_text(encoding="utf-8"))
output = config_path.parent
(output / "offline_env.json").write_text(json.dumps({
    "HF_HUB_OFFLINE": os.environ.get("HF_HUB_OFFLINE"),
    "HF_HUB_CACHE": os.environ.get("HF_HUB_CACHE"),
    "PYTORCH_ALLOC_CONF": os.environ.get("PYTORCH_ALLOC_CONF"),
    "PYTORCH_CUDA_ALLOC_CONF": os.environ.get("PYTORCH_CUDA_ALLOC_CONF"),
    "TRANSFORMERS_OFFLINE": os.environ.get("TRANSFORMERS_OFFLINE"),
    "HF_DATASETS_OFFLINE": os.environ.get("HF_DATASETS_OFFLINE"),
}), encoding="utf-8")
(output / "environment.json").write_text(json.dumps({
    "harness_version": "synthetic-harness",
    "python": "synthetic-python",
    "platform": "synthetic-platform",
    "hostname": "synthetic-host",
    "torch": "synthetic-torch",
    "cuda_runtime": "synthetic-cuda",
    "cudnn": 1,
    "source_sha256": hashlib.sha256(
        (Path.cwd() / "src/latent_workspace_ft_v10/engine.py").read_bytes()
    ).hexdigest(),
    "cuda_devices": [{"index": 0, "name": "synthetic-gpu"}],
    "transformers": "synthetic-transformers",
    "peft": None,
    "safetensors": "synthetic-safetensors",
    "pytorch_alloc_conf": os.environ.get("PYTORCH_ALLOC_CONF"),
    "pytorch_cuda_alloc_conf_legacy": os.environ.get("PYTORCH_CUDA_ALLOC_CONF"),
    "pytorch_hip_alloc_conf_legacy": os.environ.get("PYTORCH_HIP_ALLOC_CONF"),
    "pytorch_no_cuda_memory_caching": os.environ.get("PYTORCH_NO_CUDA_MEMORY_CACHING"),
    "allocator_backend": "native",
    "allocator_settings": os.environ.get("PYTORCH_ALLOC_CONF"),
    "allocator_initialized": True,
    "allocator_snapshot_settings": {"expandable_segments": True},
    "cuda_memory_allocated_bytes": 1,
    "cuda_memory_reserved_bytes": 1,
}), encoding="utf-8")
final = output / "final"
base = final / "base_model"
base.mkdir(parents=True)
(final / "COMPLETED").write_text("ok\\n", encoding="utf-8")
(final / "workspace_state.pt").write_bytes(b"workspace")
(final / "experiment_config.json").write_text(
    json.dumps(config, sort_keys=True), encoding="utf-8"
)
engine_run_id = "synthetic-engine-run"
resume_signature = "b" * 64
structural_resume_signature = "e" * 64
data_fingerprint = {"files": [{"sha256": "a" * 64}]}
config_sha256 = hashlib.sha256(
    json.dumps(config, sort_keys=True, ensure_ascii=False).encode("utf-8")
).hexdigest()
torch.save(
    {
        "run_state": {
            "run_id": engine_run_id,
            "global_step": config["train"]["max_steps"],
        },
        "global_step": config["train"]["max_steps"],
        "resume_signature": resume_signature,
        "structural_resume_signature": structural_resume_signature,
        "world_size": 1,
        "data_fingerprint": data_fingerprint,
    },
    final / "trainer_state.pt",
)
coverage = {
    "format": "latent-workspace-ft-optimizer-coverage-v1",
    "train_mode": "full",
    "passed": True,
    "checks": {
        "unique_membership_exact": True,
        "duplicate_membership_free": True,
        "full_mode_base_all_trainable": True,
    },
    "base_all_trainable": True,
    "optimizer_duplicate_memberships": 0,
    "model_trainable_unique_physical_parameters": 2,
    "model_trainable_numel": 24,
    "missing_parameters": [],
    "unexpected_parameters": [],
    "duplicate_parameters": [],
    "frozen_base_parameters": [],
    "report_sha256": "c" * 64,
}
(final / "optimizer_coverage.json").write_text(
    json.dumps(coverage, sort_keys=True), encoding="utf-8"
)
(base / "config.json").write_text("{}", encoding="utf-8")
head = torch.arange(12, 24, dtype=torch.float32).reshape(4, 3)
embed = torch.arange(12, dtype=torch.float32).reshape(4, 3)
final_head = head if UNCHANGED_TENSOR in {"lm_head.weight", "all"} else head + 1
final_embed = embed if UNCHANGED_TENSOR in {"model.embed_tokens.weight", "all"} else embed + 1
save_file(
    {"lm_head.weight": final_head.contiguous()},
    str(base / "model-00001-of-00002.safetensors"),
)
save_file(
    {"model.embed_tokens.weight": final_embed.contiguous()},
    str(base / "model-00002-of-00002.safetensors"),
)
(base / "model.safetensors.index.json").write_text(json.dumps({
    "weight_map": {
        "lm_head.weight": "model-00001-of-00002.safetensors",
        "model.embed_tokens.weight": "model-00002-of-00002.safetensors",
    }
}), encoding="utf-8")
parameter_specs = [
    ("lm_head.weight", list(head.shape), head.numel()),
    ("model.embed_tokens.weight", list(embed.shape), embed.numel()),
]
dynamic_parameters = []
for parameter_index, (name, shape, numel) in enumerate(parameter_specs):
    if DYNAMIC_EVIDENCE == "missing" and name == "lm_head.weight":
        continue
    nonzero = not (DYNAMIC_EVIDENCE == "zero" and name == "lm_head.weight")
    dynamic_parameters.append({
        "name": name,
        "aliases": [name],
        "shape": shape,
        "dtype": "F32",
        "numel": numel,
        "optimizer_group_index": 0,
        "optimizer_parameter_index": parameter_index,
        "optimizer_family": "base",
        "learning_rate": 0.001,
        "weight_decay": 0.0,
        "gradient_present": True,
        "gradient_finite": True,
        "gradient_nonzero": nonzero,
        "gradient_nonzero_elements": numel if nonzero else 0,
        "state_step": 1,
        "update_attempted": True,
    })
dynamic = {
    "format": "latent-workspace-ft-base-update-coverage-v1",
    "train_mode": "full",
    # Aggregate fields deliberately claim PASS even in negative fixtures. The
    # runner must recompute exact coverage from the parameter records.
    "passed": True,
    "base_parameter_count": len(parameter_specs),
    "base_parameter_numel": sum(item[2] for item in parameter_specs),
    "checks": {
        "all_base_parameters_trainable": True,
        "optimizer_membership_exact": True,
        "all_gradients_present": True,
        "all_gradients_finite": True,
        "all_gradients_nonzero": True,
        "positive_base_learning_rate": True,
        "optimizer_step_performed": True,
        "optimizer_step_not_skipped": True,
        "all_optimizer_states_advanced": True,
    },
    "parameters": dynamic_parameters,
}
dynamic["report_sha256"] = hashlib.sha256(
    json.dumps(dynamic, sort_keys=True, ensure_ascii=False).encode("utf-8")
).hexdigest()
(final / "base_update_coverage.json").write_text(
    json.dumps(dynamic, sort_keys=True), encoding="utf-8"
)
(final / "manifest.json").write_text(json.dumps({
    "format": "latent-workspace-ft-bundle-v4",
    "complete": True,
    "global_step": config["train"]["max_steps"],
    "run_id": engine_run_id,
    "source_sha256": hashlib.sha256(
        (Path.cwd() / "src/latent_workspace_ft_v10/engine.py").read_bytes()
    ).hexdigest(),
    "resume_signature": resume_signature,
    "structural_resume_signature": structural_resume_signature,
    "config_sha256": config_sha256,
    "world_size": 1,
    "data_fingerprint": data_fingerprint,
    "optimizer_coverage_passed": True,
    "optimizer_coverage_sha256": coverage["report_sha256"],
    "base_update_coverage_passed": True,
    "base_update_coverage_sha256": dynamic["report_sha256"],
}), encoding="utf-8")
steps = config["train"]["max_steps"]
accumulation_steps = config["train"]["gradient_accumulation_steps"]
counters = {
    "windows_started": steps,
    "windows_restored": steps,
    "windows_discarded": 0,
    "single_microbatch_windows": 0,
    "microbatch_spills": steps * accumulation_steps,
    "parameter_first_spills": 2 * steps,
    "parameter_merges": 2 * steps * (accumulation_steps - 1),
    "cumulative_current_gradient_bytes": 96 * steps * accumulation_steps,
    "peak_cpu_accumulator_bytes": 96,
}
gradient_offload_receipt = {
    "schema_version": 2,
    "mode": "cpu",
    "algorithm": "pageable_cpu_storage_cuda_native_order_add_v1",
    "claim_boundary": {
        "execution_proof": "synthetic execution proof",
        "numerical_proof": "synthetic numerical boundary",
        "unsupported": "synthetic unsupported boundary",
    },
    "run_id": engine_run_id,
    "source_sha256": hashlib.sha256(
        (Path.cwd() / "src/latent_workspace_ft_v10/engine.py").read_bytes()
    ).hexdigest(),
    "resume_signature": resume_signature,
    "configured_gradient_accumulation_steps": accumulation_steps,
    "initial_global_step": 0,
    "last_observed_global_step": steps,
    "last_restored_global_step": steps - 1,
    "final_global_step": steps,
    "trainable_parameter_count": 2,
    "trainable_parameter_total_numel": 24,
    "trainable_gradient_capacity_bytes": 96,
    "trainable_parameter_schema_sha256": "d" * 64,
    "trainable_parameter_schema_fields": [
        "name", "shape", "stride", "dtype", "device", "numel", "logical_bytes"
    ],
    **counters,
    "live_cpu_buffer_count": 0,
    "live_cpu_buffer_bytes": 0,
    "active_window": None,
    "continuations": [],
    "segments": [{
        "segment_index": 0,
        "previous_receipt_sha256": None,
        "resume_checkpoint": None,
        "initial_global_step": 0,
        "last_observed_global_step": steps,
        "final_global_step": steps,
        "initial_cumulative_counters": {key: 0 for key in counters},
        "latest_cumulative_counters": counters,
        "final_cumulative_counters": counters,
        "status": "completed",
    }],
    "status": "completed",
    "updated_at": 1.0,
    "receipt_sha256": None,
}
gradient_offload_receipt["receipt_sha256"] = hashlib.sha256(
    json.dumps(
        gradient_offload_receipt,
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
).hexdigest()
(output / "gradient_accumulation_offload.json").write_text(
    json.dumps(gradient_offload_receipt, sort_keys=True),
    encoding="utf-8",
)
""".lstrip().replace("__UNCHANGED_TENSOR__", repr(unchanged_tensor)).replace(
        "__DYNAMIC_EVIDENCE__", repr(dynamic_evidence)
    )
    path.write_text(
        source,
        encoding="utf-8",
    )
    return path


def test_sharded_prefetch_receipt_detects_mutation(tmp_path: Path) -> None:
    snapshot = make_snapshot(tmp_path / "snapshot")
    receipt = make_prefetch_receipt(snapshot, tmp_path / "receipt.json")
    verified = prefetch.verify_prefetch_receipt(
        receipt,
        expected_model=MODEL,
        expected_revision=REVISION,
        snapshot_path=snapshot,
    )
    assert verified["receipt"]["weights"]["weight_file_count"] == 2
    assert len(verified["receipt"]["weights"]["index_files"]) == 1

    (snapshot / "model-00002-of-00002.safetensors").write_bytes(b"mutated")
    with pytest.raises(prefetch.PrefetchError, match="inventory/hash differs"):
        prefetch.verify_prefetch_receipt(receipt, snapshot_path=snapshot)


def test_full_update_delta_positive_with_real_indexed_safetensors(
    tmp_path: Path,
) -> None:
    initial = make_snapshot(tmp_path / "initial")
    final_tensors = {
        name: tensor + 1 for name, tensor in initial_tensors().items()
    }
    final = write_weight_tree(tmp_path / "final", final_tensors)

    compared = runner.compare_full_update_safetensors(initial, final)

    assert compared["passed"] is True
    assert compared["tensor_count"] == 2
    assert compared["changed_tensor_count"] == 2
    assert compared["unchanged_tensor_count"] == 0
    assert all(item["changed_elements"] == item["numel"] for item in compared["tensors"])


def test_semantic_safetensors_accepts_snapshot_symlinks_to_blobs(
    tmp_path: Path,
) -> None:
    blobs = write_weight_tree(tmp_path / "blobs", initial_tensors())
    snapshot = tmp_path / "snapshots" / REVISION
    snapshot.mkdir(parents=True)
    index = json.loads(
        (blobs / "model.safetensors.index.json").read_text(encoding="utf-8")
    )
    for shard_name in sorted(set(index["weight_map"].values())):
        (snapshot / shard_name).symlink_to(blobs / shard_name)
    write_json(snapshot / "model.safetensors.index.json", index)

    entries, semantic = runner.inspect_semantic_safetensors(snapshot)

    assert set(entries) == set(initial_tensors())
    assert semantic["tensor_count"] == 2
    assert semantic["index_files"][0]["shards"] == sorted(
        set(index["weight_map"].values())
    )
    assert all(Path(entry.path).parent == snapshot for entry in entries.values())

    final = write_weight_tree(
        tmp_path / "final",
        {name: tensor + 1 for name, tensor in initial_tensors().items()},
    )
    compared = runner.compare_full_update_safetensors(snapshot, final)
    assert compared["passed"] is True
    assert compared["changed_tensor_count"] == 2


def test_semantic_safetensors_rejects_index_parent_traversal(tmp_path: Path) -> None:
    root = tmp_path / "snapshot"
    root.mkdir()
    write_json(
        root / "model.safetensors.index.json",
        {"weight_map": {"model.weight": "../outside.safetensors"}},
    )
    save_file({"inside.weight": torch.ones(1)}, str(root / "inside.safetensors"))
    save_file({"model.weight": torch.ones(1)}, str(tmp_path / "outside.safetensors"))

    with pytest.raises(runner.RunnerError, match="Unsafe safetensors index path"):
        runner.inspect_semantic_safetensors(root)


def test_full_update_delta_supports_real_standalone_safetensors(
    tmp_path: Path,
) -> None:
    initial = tmp_path / "initial"
    final = tmp_path / "final"
    initial.mkdir()
    final.mkdir()
    tensors = initial_tensors()
    save_file(tensors, str(initial / "model.safetensors"))
    save_file(
        {name: tensor + 1 for name, tensor in tensors.items()},
        str(final / "model.safetensors"),
    )

    compared = runner.compare_full_update_safetensors(initial, final)

    assert compared["passed"] is True
    assert compared["initial_semantic"]["index_files"] == []
    assert compared["final_semantic"]["index_files"] == []


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("key", "key set mismatch"),
        ("shape", "shape mismatch"),
        ("dtype", "dtype mismatch"),
    ],
)
def test_full_update_delta_schema_mismatch_fails_closed(
    tmp_path: Path,
    case: str,
    message: str,
) -> None:
    initial = make_snapshot(tmp_path / "initial")
    tensors = {name: tensor + 1 for name, tensor in initial_tensors().items()}
    if case == "key":
        tensors["renamed_lm_head.weight"] = tensors.pop("lm_head.weight")
    elif case == "shape":
        tensors["lm_head.weight"] = torch.arange(
            16, dtype=torch.float32
        ).reshape(4, 4)
    else:
        tensors["lm_head.weight"] = tensors["lm_head.weight"].to(torch.float64)
    final = write_weight_tree(tmp_path / "final", tensors)

    with pytest.raises(runner.RunnerError, match=message):
        runner.compare_full_update_safetensors(initial, final)


def test_dry_run_is_read_only_and_materializes_offline_config(tmp_path: Path) -> None:
    repo, snapshot, receipt = make_repo(tmp_path)
    result = runner.run_matrix(
        runner.RunnerOptions(**{**options(repo, snapshot, receipt).__dict__, "dry_run": True})
    )
    assert result["dry_run"] is True
    assert result["states"] == {"F0_query_only/seed_42": "pending"}
    assert not (repo / "runs/v10/_control").exists()
    matrix, specs = runner.load_matrix(
        repo, repo / "configs/v10/profiles/smoke/MATRIX.json", "smoke"
    )
    materialized, _payload = runner.materialize_config(repo, matrix, specs[0])
    assert materialized["model"]["train_mode"] == "full"
    assert materialized["model"]["attn_implementation"] == "sdpa"
    assert materialized["train"]["optimizer"] == "adafactor"
    assert materialized["train"]["device"] == "cuda"
    assert materialized["train"]["mixed_precision"] == "bf16"
    assert (
        materialized["train"]["gradient_accumulation_offload"]
        == runner.GRADIENT_ACCUMULATION_OFFLOAD
    )
    assert materialized["model"]["local_files_only"] is True
    assert materialized["train"]["resume_from"] == "none"
    assert materialized["train"]["seed"] == 42
    assert materialized["train"]["max_steps"] == 8


@pytest.mark.parametrize(
    ("section", "key", "bad_value", "canonical"),
    [
        ("model", "train_mode", "lora", "model.train_mode"),
        ("train", "optimizer", "adamw", "train.optimizer"),
        ("train", "device", "cpu", "train.device"),
        ("train", "mixed_precision", "fp16", "train.mixed_precision"),
        (
            "train",
            "gradient_accumulation_offload",
            "none",
            "train.gradient_accumulation_offload",
        ),
        (
            "model",
            "attn_implementation",
            "eager",
            "model.attn_implementation",
        ),
    ],
)
def test_condition_full_update_drift_fails_closed_before_launch(
    tmp_path: Path,
    section: str,
    key: str,
    bad_value: str,
    canonical: str,
) -> None:
    repo, snapshot, receipt = make_repo(tmp_path)
    condition = repo / "configs/v10/conditions/config_F0_query_only.json"
    replace_json_field(condition, section, key, bad_value)
    run_options = runner.RunnerOptions(
        **{**options(repo, snapshot, receipt).__dict__, "dry_run": True}
    )

    with pytest.raises(runner.RunnerError) as caught:
        runner.run_matrix(run_options)
    assert canonical in str(caught.value)


@pytest.mark.parametrize(
    ("section", "key", "bad_value", "canonical"),
    [
        ("model", "train_mode", "lora", "model.train_mode"),
        ("runtime", "optimizer", "adamw", "train.optimizer"),
        ("runtime", "backend", "cpu", "train.device"),
        (
            "runtime",
            "cuda_allocator_conf",
            "backend:cudaMallocAsync",
            "allocator",
        ),
        (
            "runtime",
            "gradient_accumulation_offload",
            "none",
            "train.gradient_accumulation_offload",
        ),
        ("model", "dtype", "float16", "train.mixed_precision"),
        (
            "model",
            "attention_implementation",
            "eager",
            "model.attn_implementation",
        ),
    ],
)
def test_contract_full_update_drift_fails_closed_before_launch(
    tmp_path: Path,
    section: str,
    key: str,
    bad_value: str,
    canonical: str,
) -> None:
    repo, snapshot, receipt = make_repo(tmp_path)
    contract = repo / "configs/v10/CONTRACT.json"
    replace_json_field(contract, section, key, bad_value)
    run_options = runner.RunnerOptions(
        **{**options(repo, snapshot, receipt).__dict__, "dry_run": True}
    )

    with pytest.raises(runner.RunnerError) as caught:
        runner.run_matrix(run_options)
    assert canonical in str(caught.value)


def test_matrix_accumulation_offload_drift_fails_closed_before_launch(
    tmp_path: Path,
) -> None:
    repo, snapshot, receipt = make_repo(tmp_path)
    matrix_path = repo / "configs/v10/profiles/smoke/MATRIX.json"
    replace_json_field(
        matrix_path,
        "runtime",
        "gradient_accumulation_offload",
        "none",
    )
    run_options = runner.RunnerOptions(
        **{**options(repo, snapshot, receipt).__dict__, "dry_run": True}
    )

    with pytest.raises(runner.RunnerError, match="Matrix gradient-accumulation offload"):
        runner.run_matrix(run_options)


def test_allocator_environment_file_fails_closed_on_alias_or_tamper(
    tmp_path: Path,
) -> None:
    path = tmp_path / "environment.json"
    valid = {
        "harness_version": "synthetic-harness",
        "python": "synthetic-python",
        "platform": "synthetic-platform",
        "hostname": "synthetic-host",
        "torch": "synthetic-torch",
        "cuda_runtime": "synthetic-cuda",
        "cudnn": 1,
        "source_sha256": "a" * 64,
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
    write_json(path, valid)
    binding = runner.validate_allocator_environment_file(
        path,
        configured=runner.CUDA_ALLOCATOR_CONF,
        expected_source_sha256="a" * 64,
        label="synthetic child",
        receipt_path="environment.json",
    )
    assert binding["passed"] is True

    write_json(
        path,
        {**valid, "pytorch_cuda_alloc_conf_legacy": "backend:cudaMallocAsync"},
    )
    with pytest.raises(runner.RunnerError, match="legacy_alias_absent"):
        runner.validate_allocator_environment_file(
            path,
            configured=runner.CUDA_ALLOCATOR_CONF,
            expected_source_sha256="a" * 64,
            label="synthetic child",
            receipt_path="environment.json",
        )

    path.unlink()
    with pytest.raises(runner.RunnerError, match="Missing environment.json"):
        runner.validate_allocator_environment_file(
            path,
            configured=runner.CUDA_ALLOCATOR_CONF,
            expected_source_sha256="a" * 64,
            label="synthetic child",
            receipt_path="environment.json",
        )


def test_n3_requires_exact_smoke_qualification(tmp_path: Path) -> None:
    repo, snapshot, receipt = make_repo(tmp_path, profile="n3")
    run_options = runner.RunnerOptions(
        **{**options(repo, snapshot, receipt, profile="n3").__dict__, "dry_run": True}
    )
    with pytest.raises(runner.RunnerError, match="missing smoke qualification"):
        runner.run_matrix(run_options)

    source_files, source_tree = runner.source_hashes(repo)
    assert source_files
    contract = runner.read_json(repo / "configs/v10/CONTRACT.json")
    matrix = runner.read_json(repo / "configs/v10/profiles/n3/MATRIX.json")
    data_hashes = runner.validate_contract(
        repo, repo / "configs/v10/CONTRACT.json", contract, matrix, "n3"
    )
    expected = runner.qualification_requirements(
        repo_root=repo,
        gate_profile="smoke",
        contract_sha256=runner.sha256_file(repo / "configs/v10/CONTRACT.json"),
        model_receipt_sha256=runner.sha256_file(receipt),
        source_tree_sha256=source_tree,
        data_hashes=data_hashes,
        runner_sha256=runner.sha256_file(Path(runner.__file__).resolve()),
    )
    write_json(repo / "runs/v10/qualifications/smoke/QUALIFICATION.json", expected)
    result = runner.run_matrix(run_options)
    assert result["profile"] == "n3"


def test_stale_output_archived_fresh_stub_run_then_verified_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTORCH_CUDA_ALLOC_CONF", "backend:cudaMallocAsync")
    monkeypatch.setenv("PYTORCH_HIP_ALLOC_CONF", "backend:cudaMallocAsync")
    monkeypatch.setenv("PYTORCH_NO_CUDA_MEMORY_CACHING", "1")
    repo, snapshot, receipt = make_repo(tmp_path)
    run_options = runner.RunnerOptions(
        **{
            **options(repo, snapshot, receipt).__dict__,
            "cache_dir": Path("runs/v10/model_cache/hf-child"),
        }
    )
    output = repo / "runs/v10/smoke/F0_query_only/seed_42"
    output.mkdir(parents=True)
    (output / "stale.txt").write_text("preserve me", encoding="utf-8")
    stub = make_stub(repo / "stub_engine.py")

    def command(_options: runner.RunnerOptions, config: Path) -> list[str]:
        return [sys.executable, str(stub), str(config)]

    first = runner.run_matrix(
        run_options,
        child_command_factory=command,
        preflight_fn=lambda _options: {"synthetic": True},
    )
    assert first["launched"] == 1
    assert first["states"]["F0_query_only/seed_42"] == "verified_completed"
    archives = list(
        (repo / "runs/v10/_archived_incomplete/smoke/F0_query_only/seed_42").glob("*")
    )
    assert len(archives) == 1
    assert (archives[0] / "stale.txt").read_text(encoding="utf-8") == "preserve me"
    offline = json.loads((output / "offline_env.json").read_text(encoding="utf-8"))
    assert offline == {
        "HF_HUB_OFFLINE": "1",
        "HF_HUB_CACHE": str(
            (repo / "runs/v10/model_cache/hf-child").resolve()
        ),
        "PYTORCH_ALLOC_CONF": runner.CUDA_ALLOCATOR_CONF,
        "PYTORCH_CUDA_ALLOC_CONF": None,
        "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
    }
    delta_path = output / "FULL_UPDATE_DELTA.json"
    delta = json.loads(delta_path.read_text(encoding="utf-8"))
    assert delta["passed"] is True
    assert delta["format"] == runner.FULL_UPDATE_DELTA_FORMAT
    assert delta["comparison"]["all_base_weight_tensors_changed"] is True
    assert delta["comparison"]["changed_tensor_count"] == 2
    assert delta["evaluation"]["full_scope_optimization_attempts_verified"] is True
    assert delta["evaluation"]["at_least_one_persisted_element_changed"] is True
    assert delta["optimizer_coverage"]["file_sha256"] == runner.sha256_file(
        output / "final/optimizer_coverage.json"
    )
    assert delta["base_update_coverage"]["file_sha256"] == runner.sha256_file(
        output / "final/base_update_coverage.json"
    )
    verification = json.loads(
        (output / "RUN_VERIFICATION.json").read_text(encoding="utf-8")
    )
    assert verification["full_update_delta"]["sha256"] == runner.sha256_file(
        delta_path
    )
    assert verification["allocator_environment"]["passed"] is True
    assert verification["allocator_environment"]["sha256"] == runner.sha256_file(
        output / "environment.json"
    )
    assert verification["provenance"]["runtime_policy"][
        "gradient_accumulation_offload"
    ] == runner.GRADIENT_ACCUMULATION_OFFLOAD

    final_config_path = output / "final/experiment_config.json"
    original_final_config = final_config_path.read_bytes()
    final_config = json.loads(final_config_path.read_text(encoding="utf-8"))
    final_config["train"]["gradient_accumulation_offload"] = "none"
    write_json(final_config_path, final_config)
    drift = runner.run_matrix(
        runner.RunnerOptions(**{**run_options.__dict__, "dry_run": True})
    )
    assert drift["states"]["F0_query_only/seed_42"] == "stale_incomplete"
    assert "manifest/experiment_config hash binding" in drift["reasons"][
        "F0_query_only/seed_42"
    ]
    final_config_path.write_bytes(original_final_config)

    second = runner.run_matrix(
        run_options,
        child_command_factory=command,
        preflight_fn=lambda _options: {"synthetic": True},
    )
    assert second["launched"] == 0
    assert len(list((repo / "runs/v10/_archived_incomplete").rglob("stale.txt"))) == 1

    shard = output / "final/base_model/model-00001-of-00002.safetensors"
    shard.write_bytes(b"corrupted")
    third = runner.run_matrix(
        runner.RunnerOptions(**{**run_options.__dict__, "max_runs": 1}),
        child_command_factory=command,
        preflight_fn=lambda _options: {"synthetic": True},
    )
    assert third["launched"] == 1
    assert len(list((repo / "runs/v10/_archived_incomplete").rglob("RUN_VERIFICATION.json"))) == 1


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("run_id", "manifest/trainer run_id binding"),
        ("global_step", "manifest/trainer global_step binding"),
        ("resume_signature", "manifest/trainer resume_signature binding"),
        (
            "structural_resume_signature",
            "manifest/trainer structural_resume_signature binding",
        ),
        ("config", "manifest/experiment_config hash binding"),
        ("world_size", "manifest/trainer world_size binding"),
        ("data_fingerprint", "manifest/trainer data_fingerprint binding"),
    ],
)
def test_bundle_manifest_trainer_config_split_fails_closed(
    tmp_path: Path,
    mutation: str,
    reason: str,
) -> None:
    repo, snapshot, receipt = make_repo(tmp_path)
    run_options = options(repo, snapshot, receipt)
    stub = make_stub(repo / "stub_engine.py")

    def command(_options: runner.RunnerOptions, config: Path) -> list[str]:
        return [sys.executable, str(stub), str(config)]

    first = runner.run_matrix(
        run_options,
        child_command_factory=command,
        preflight_fn=lambda _options: {"synthetic": True},
    )
    run_id = "F0_query_only/seed_42"
    assert first["states"][run_id] == "verified_completed"
    final = repo / "runs/v10/smoke/F0_query_only/seed_42/final"
    if mutation == "config":
        config_path = final / "experiment_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["synthetic_unbound_tamper"] = True
        write_json(config_path, config)
    else:
        trainer_path = final / "trainer_state.pt"
        trainer = torch.load(trainer_path, map_location="cpu", weights_only=False)
        if mutation == "run_id":
            trainer["run_state"]["run_id"] = "split-run-id"
        elif mutation == "global_step":
            trainer["run_state"]["global_step"] -= 1
        elif mutation == "resume_signature":
            trainer["resume_signature"] = "0" * 64
        elif mutation == "structural_resume_signature":
            trainer["structural_resume_signature"] = "0" * 64
        elif mutation == "world_size":
            trainer["world_size"] = 2
        else:
            trainer["data_fingerprint"] = {"files": [{"sha256": "0" * 64}]}
        torch.save(trainer, trainer_path)

    result = runner.run_matrix(
        runner.RunnerOptions(**{**run_options.__dict__, "dry_run": True})
    )
    assert result["states"][run_id] == "stale_incomplete"
    assert reason in result["reasons"][run_id]


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("missing", "Missing artifact"),
        ("self_hash", "self-hash mismatch"),
        ("status", "terminal status"),
        ("counter", "skip-free"),
        ("source", "run/source/resume binding"),
        ("signature", "run/source/resume binding"),
        ("step", "terminal status/step"),
        ("binding_path", "receipt/hash mismatch"),
        ("binding_hash", "receipt/hash mismatch"),
    ],
)
def test_gradient_offload_receipt_tamper_fails_closed(
    tmp_path: Path,
    mutation: str,
    reason: str,
) -> None:
    repo, snapshot, receipt = make_repo(tmp_path)
    run_options = options(repo, snapshot, receipt)
    stub = make_stub(repo / "stub_engine.py")

    def command(_options: runner.RunnerOptions, config: Path) -> list[str]:
        return [sys.executable, str(stub), str(config)]

    first = runner.run_matrix(
        run_options,
        child_command_factory=command,
        preflight_fn=lambda _options: {"synthetic": True},
    )
    assert first["states"]["F0_query_only/seed_42"] == "verified_completed"
    output = repo / "runs/v10/smoke/F0_query_only/seed_42"
    receipt_path = output / runner.GRADIENT_ACCUMULATION_OFFLOAD_RECEIPT
    verification_path = output / "RUN_VERIFICATION.json"
    if mutation == "missing":
        receipt_path.unlink()
    elif mutation in {"binding_path", "binding_hash"}:
        verification = json.loads(verification_path.read_text(encoding="utf-8"))
        field = "path" if mutation == "binding_path" else "sha256"
        verification["gradient_accumulation_offload"][field] = (
            "wrong.json" if field == "path" else "0" * 64
        )
        write_json(verification_path, verification)
    else:
        offload = json.loads(receipt_path.read_text(encoding="utf-8"))
        if mutation == "self_hash":
            offload["receipt_sha256"] = "0" * 64
        elif mutation == "status":
            offload["status"] = "failed"
        elif mutation == "counter":
            offload["windows_discarded"] = 1
            offload["windows_restored"] = 7
        elif mutation == "source":
            offload["source_sha256"] = "0" * 64
        elif mutation == "signature":
            offload["resume_signature"] = "0" * 64
        elif mutation == "step":
            offload["final_global_step"] = 7
        if mutation != "self_hash":
            offload["receipt_sha256"] = (
                pruning.gradient_accumulation_offload_receipt_self_hash(offload)
            )
        write_json(receipt_path, offload)

    result = runner.run_matrix(
        runner.RunnerOptions(**{**run_options.__dict__, "dry_run": True})
    )
    run_id = "F0_query_only/seed_42"
    assert result["states"][run_id] == "stale_incomplete"
    assert reason in result["reasons"][run_id]


def test_run_accepts_evidence_backed_unchanged_tensor_with_strict_diagnostic_false(
    tmp_path: Path,
) -> None:
    repo, snapshot, receipt = make_repo(tmp_path)
    run_options = options(repo, snapshot, receipt)
    output = repo / "runs/v10/smoke/F0_query_only/seed_42"
    stub = make_stub(repo / "stub_engine.py", unchanged_tensor="lm_head.weight")

    def command(_options: runner.RunnerOptions, config: Path) -> list[str]:
        return [sys.executable, str(stub), str(config)]

    result = runner.run_matrix(
        run_options,
        child_command_factory=command,
        preflight_fn=lambda _options: {"synthetic": True},
    )
    assert result["states"]["F0_query_only/seed_42"] == "verified_completed"

    delta = json.loads(
        (output / "FULL_UPDATE_DELTA.json").read_text(encoding="utf-8")
    )
    assert delta["passed"] is True
    assert delta["comparison"]["passed"] is False
    assert delta["comparison"]["all_base_weight_tensors_changed"] is False
    assert delta["comparison"]["changed_tensor_count"] == 1
    assert delta["comparison"]["unchanged_tensor_count"] == 1
    unchanged = [
        item for item in delta["comparison"]["tensors"] if not item["changed"]
    ]
    assert [item["name"] for item in unchanged] == ["lm_head.weight"]
    assert unchanged[0]["update_evidence_class"] == (
        runner.UNCHANGED_UPDATE_EVIDENCE_CLASS
    )
    assert delta["evaluation"]["verified_zero_net_delta_tensor_count"] == 1

    unchanged[0].pop("update_evidence_class")
    write_json(output / "FULL_UPDATE_DELTA.json", delta)
    dry = runner.run_matrix(
        runner.RunnerOptions(**{**run_options.__dict__, "dry_run": True})
    )
    assert dry["states"]["F0_query_only/seed_42"] == "stale_incomplete"
    assert "exact update evidence" in dry["reasons"][
        "F0_query_only/seed_42"
    ]


@pytest.mark.parametrize("dynamic_evidence", ["zero", "missing"])
def test_unchanged_tensor_with_zero_or_missing_dynamic_evidence_fails_closed(
    tmp_path: Path,
    dynamic_evidence: str,
) -> None:
    repo, snapshot, receipt = make_repo(tmp_path)
    output = repo / "runs/v10/smoke/F0_query_only/seed_42"
    stub = make_stub(
        repo / "stub_engine.py",
        unchanged_tensor="lm_head.weight",
        dynamic_evidence=dynamic_evidence,
    )

    def command(_options: runner.RunnerOptions, config: Path) -> list[str]:
        return [sys.executable, str(stub), str(config)]

    with pytest.raises(runner.RunnerError, match="[Bb]ase update coverage"):
        runner.run_matrix(
            options(repo, snapshot, receipt),
            child_command_factory=command,
            preflight_fn=lambda _options: {"synthetic": True},
        )
    assert not (output / "FULL_UPDATE_DELTA.json").exists()


def test_changed_bytes_without_dynamic_evidence_fail_closed(tmp_path: Path) -> None:
    repo, snapshot, receipt = make_repo(tmp_path)
    output = repo / "runs/v10/smoke/F0_query_only/seed_42"
    stub = make_stub(repo / "stub_engine.py", dynamic_evidence="missing")

    def command(_options: runner.RunnerOptions, config: Path) -> list[str]:
        return [sys.executable, str(stub), str(config)]

    with pytest.raises(runner.RunnerError, match="[Bb]ase update coverage"):
        runner.run_matrix(
            options(repo, snapshot, receipt),
            child_command_factory=command,
            preflight_fn=lambda _options: {"synthetic": True},
        )
    assert not (output / "FULL_UPDATE_DELTA.json").exists()


def test_verified_attempts_without_any_persisted_change_fail_closed(
    tmp_path: Path,
) -> None:
    repo, snapshot, receipt = make_repo(tmp_path)
    output = repo / "runs/v10/smoke/F0_query_only/seed_42"
    stub = make_stub(repo / "stub_engine.py", unchanged_tensor="all")

    def command(_options: runner.RunnerOptions, config: Path) -> list[str]:
        return [sys.executable, str(stub), str(config)]

    with pytest.raises(runner.RunnerError, match="incomplete/failed"):
        runner.run_matrix(
            options(repo, snapshot, receipt),
            child_command_factory=command,
            preflight_fn=lambda _options: {"synthetic": True},
        )
    delta = json.loads(
        (output / "FULL_UPDATE_DELTA.json").read_text(encoding="utf-8")
    )
    assert delta["passed"] is False
    assert delta["comparison"]["all_base_weight_tensors_changed"] is False
    assert delta["evaluation"]["at_least_one_persisted_element_changed"] is False
    assert delta["evaluation"]["verified_zero_net_delta_tensor_count"] == 2


def test_full_update_delta_receipt_tamper_marks_run_stale(tmp_path: Path) -> None:
    repo, snapshot, receipt = make_repo(tmp_path)
    run_options = options(repo, snapshot, receipt)
    output = repo / "runs/v10/smoke/F0_query_only/seed_42"
    stub = make_stub(repo / "stub_engine.py")

    def command(_options: runner.RunnerOptions, config: Path) -> list[str]:
        return [sys.executable, str(stub), str(config)]

    runner.run_matrix(
        run_options,
        child_command_factory=command,
        preflight_fn=lambda _options: {"synthetic": True},
    )
    delta_path = output / "FULL_UPDATE_DELTA.json"
    delta = json.loads(delta_path.read_text(encoding="utf-8"))
    delta["comparison"]["total_changed_elements"] += 1
    write_json(delta_path, delta)

    dry = runner.run_matrix(
        runner.RunnerOptions(**{**run_options.__dict__, "dry_run": True})
    )

    assert dry["states"]["F0_query_only/seed_42"] == "stale_incomplete"
    assert "aggregate fields are inconsistent" in dry["reasons"][
        "F0_query_only/seed_42"
    ]


def test_base_update_coverage_tamper_marks_run_stale(tmp_path: Path) -> None:
    repo, snapshot, receipt = make_repo(tmp_path)
    run_options = options(repo, snapshot, receipt)
    output = repo / "runs/v10/smoke/F0_query_only/seed_42"
    stub = make_stub(repo / "stub_engine.py")

    def command(_options: runner.RunnerOptions, config: Path) -> list[str]:
        return [sys.executable, str(stub), str(config)]

    runner.run_matrix(
        run_options,
        child_command_factory=command,
        preflight_fn=lambda _options: {"synthetic": True},
    )
    coverage_path = output / "final/base_update_coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage["parameters"][0]["state_step"] = 0
    write_json(coverage_path, coverage)

    dry = runner.run_matrix(
        runner.RunnerOptions(**{**run_options.__dict__, "dry_run": True})
    )

    assert dry["states"]["F0_query_only/seed_42"] == "stale_incomplete"
    assert "incomplete dynamic evidence" in dry["reasons"][
        "F0_query_only/seed_42"
    ]


def test_lock_is_exclusive(tmp_path: Path) -> None:
    lock = tmp_path / "RUNNER.lock"
    with runner.exclusive_lock(lock):
        with pytest.raises(runner.RunnerError, match="lock is held"):
            with runner.exclusive_lock(lock):
                pass


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_lock_rejects_links_without_truncating_target(tmp_path: Path, kind: str) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("must remain intact", encoding="utf-8")
    lock = tmp_path / "RUNNER.lock"
    if kind == "symlink":
        lock.symlink_to(victim)
    else:
        lock.hardlink_to(victim)

    with pytest.raises(runner.RunnerError, match="[Uu]nsafe|single-link"):
        with runner.exclusive_lock(lock):
            pass

    assert victim.read_text(encoding="utf-8") == "must remain intact"


def test_actual_run_reclassifies_prune_state_after_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, snapshot, receipt = make_repo(tmp_path)
    run_options = options(repo, snapshot, receipt)
    output = repo / "runs/v10/smoke/F0_query_only/seed_42"
    output.mkdir(parents=True)
    (output / "stale.txt").write_text("preserve", encoding="utf-8")
    classifications = iter(
        [
            ("stale_incomplete", "pre-lock snapshot"),
            ("prune_incomplete", "intent appeared before lock"),
        ]
    )
    monkeypatch.setattr(runner, "classify_prepared_run", lambda _prepared: next(classifications))

    with pytest.raises(runner.RunnerError, match="protected prune state"):
        runner.run_matrix(
            run_options,
            child_command_factory=lambda _options, _config: (_ for _ in ()).throw(
                AssertionError("protected run must not launch")
            ),
            preflight_fn=lambda _options: (_ for _ in ()).throw(
                AssertionError("protected run must block before preflight")
            ),
        )

    assert (output / "stale.txt").read_text(encoding="utf-8") == "preserve"
    assert not (repo / "runs/v10/_archived_incomplete").exists()
