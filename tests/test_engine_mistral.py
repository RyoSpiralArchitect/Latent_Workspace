from __future__ import annotations

import copy
import gc
import hashlib
import json
import os
import weakref
from pathlib import Path

import pytest
import torch
import torch.nn.functional as F
from transformers import GPT2Config, GPT2LMHeadModel, MistralConfig, MistralForCausalLM
from transformers.optimization import Adafactor

from latent_workspace_ft_v10.engine import (
    DataConfig,
    DistributedContext,
    ExperimentConfig,
    FunctionalBoundaryAdapter,
    FunctionalWorkspaceConfig,
    LatentWorkspaceCausalLM,
    LatentWorkspaceLoss,
    TrainConfig,
    WorkspaceConfig,
    _clear_parameter_family_gradients,
    _continue_gradient_accumulation_offload_receipt,
    _CPUGradientAccumulator,
    _cuda_base_activation_offload,
    _finish_gradient_accumulation_offload_window,
    _functional_elicitation_query,
    _functional_split_equivalence_check,
    _mark_gradient_accumulation_offload_terminal,
    _new_gradient_accumulation_offload_receipt,
    _optimizer_family_state_entries,
    _record_gradient_accumulation_offload_spill,
    _release_unconsumed_training_logits,
    _require_exact_gradient_offload_resume_signature,
    _require_gradient_accumulation_offload_context,
    _require_resume_optimizer_mapping,
    _restore_optimizer_state_exact,
    _set_optimizer_family_learning_rate,
    _start_gradient_accumulation_offload_window,
    _write_gradient_accumulation_offload_receipt,
    base_update_coverage_report,
    build_optimizer,
    configure_trainability,
    optimizer_coverage_report,
    optimizer_step_with_base_sentinel,
    require_base_update_coverage,
    require_cuda_allocator_policy,
    require_effective_cuda_allocator_policy,
    require_exact_optimizer_coverage,
    resume_signature,
    runtime_environment,
    stable_hash,
)


def _functional_objective_probe(
    mode: str,
    *,
    full_vocab_loss_weight: float = 0.0,
) -> tuple[LatentWorkspaceCausalLM, torch.Tensor, dict[str, torch.Tensor]]:
    model = tiny_workspace_model()
    model.functional_config = FunctionalWorkspaceConfig(
        task_objective=mode,
        full_vocab_loss_weight=full_vocab_loss_weight,
    )
    logits = torch.zeros((2, 3, 97), dtype=torch.float32, requires_grad=True)
    with torch.no_grad():
        logits[0, 1, 10] = 1.5
        logits[0, 1, 20] = -0.5
        logits[1, 1, 10] = 0.25
        logits[1, 1, 20] = 0.75
    labels = torch.full((2, 3), -100, dtype=torch.long)
    labels[0, 2] = 10
    labels[1, 2] = 20
    result = model._functional_task_result(
        logits,
        labels,
        torch.tensor([[10, 20], [10, 20]], dtype=torch.long),
        torch.tensor([0, 1], dtype=torch.long),
        batch_size=1,
        side_indices=torch.tensor([0, 1], dtype=torch.long),
        world_indices=torch.tensor([0, 0], dtype=torch.long),
        query_indices=torch.tensor([0, 0], dtype=torch.long),
        affected=torch.tensor([[True]]),
        heldout=torch.tensor([[False]]),
        hop_distances=torch.tensor([[1]], dtype=torch.long),
    )
    return model, logits, result


def test_v11_choice_objective_is_normalized_over_declared_choices() -> None:
    _model, logits, result = _functional_objective_probe("choice_normalized")
    source = logits[:, 1, :]
    expected_choice = F.cross_entropy(
        source[:, [10, 20]],
        torch.tensor([0, 1]),
    )
    expected_full_vocab = F.cross_entropy(
        source,
        torch.tensor([10, 20]),
    )

    torch.testing.assert_close(result["task_loss"], expected_choice)
    torch.testing.assert_close(result["functional_choice_loss"], expected_choice)
    torch.testing.assert_close(result["functional_full_vocab_loss"], expected_full_vocab)
    assert result["functional_label_0_recall"].item() == 1.0
    assert result["functional_label_1_recall"].item() == 1.0
    assert result["functional_prediction_entropy_nats"].item() == pytest.approx(0.6931471805599453)

    result["task_loss"].backward()
    assert logits.grad is not None
    non_choice = torch.ones(97, dtype=torch.bool)
    non_choice[[10, 20]] = False
    assert torch.count_nonzero(logits.grad[:, 1, non_choice]).item() == 0
    assert torch.count_nonzero(logits.grad[:, 1, [10, 20]]).item() == 4


def test_v11_full_vocab_default_and_hybrid_objectives_remain_explicit() -> None:
    _full_model, _full_logits, full = _functional_objective_probe("full_vocab")
    _hybrid_model, _hybrid_logits, hybrid = _functional_objective_probe(
        "hybrid",
        full_vocab_loss_weight=0.125,
    )

    torch.testing.assert_close(
        full["task_loss"],
        full["functional_full_vocab_loss"],
    )
    torch.testing.assert_close(
        hybrid["task_loss"],
        hybrid["functional_choice_loss"] + 0.125 * hybrid["functional_full_vocab_loss"],
    )


def test_v11_functional_objective_config_validation_fails_closed() -> None:
    config = ExperimentConfig()
    config.functional.task_objective = "unbounded"
    with pytest.raises(ValueError, match="functional.task_objective"):
        config.validate()

    config.functional.task_objective = "hybrid"
    config.functional.full_vocab_loss_weight = 0.0
    with pytest.raises(ValueError, match="positive full_vocab_loss_weight"):
        config.validate()


def test_v12_inline_sidecar_and_base_release_validation_fail_closed() -> None:
    config = ExperimentConfig()
    config.functional.route_mode = "inline_sidecar"
    config.validate()

    invalid_route = copy.deepcopy(config)
    invalid_route.functional.route_mode = "sidecar-ish"
    with pytest.raises(ValueError, match="inline_sidecar"):
        invalid_route.validate()

    invalid_release = copy.deepcopy(config)
    invalid_release.model.train_mode = "workspace_only"
    invalid_release.train.base_release_step = 1
    with pytest.raises(ValueError, match="supported only"):
        invalid_release.validate()

    beyond_horizon = copy.deepcopy(config)
    beyond_horizon.train.max_steps = 4
    beyond_horizon.train.base_release_step = 5
    with pytest.raises(ValueError, match="cannot exceed"):
        beyond_horizon.validate()


@pytest.mark.parametrize(
    ("style", "expected"),
    [
        ("legacy", "Is Aster ranked above Beryl? Answer:"),
        ("explicit_labels", "Is Aster ranked above Beryl? Answer no or yes:"),
    ],
)
def test_v11_functional_elicitation_preserves_dataset_bytes(
    style: str,
    expected: str,
) -> None:
    config = DataConfig(functional_elicitation=style)
    query = "Is Aster ranked above Beryl? Answer:"
    assert _functional_elicitation_query(query, config) == expected
    assert query == "Is Aster ranked above Beryl? Answer:"


def test_v11_symmetric_elicitation_defines_both_labels() -> None:
    config = DataConfig(functional_elicitation="symmetric_instruction")
    rendered = _functional_elicitation_query(
        "Is Aster ranked above Beryl? Answer:",
        config,
    )
    assert "If it is false, answer no" in rendered
    assert "if it is true, answer yes" in rendered
    assert rendered.endswith("Is Aster ranked above Beryl? Answer:")


def test_releasing_unconsumed_logits_preserves_indexed_loss_gradients() -> None:
    torch.manual_seed(20260822)
    reference = torch.nn.Linear(7, 11, bias=False)
    candidate = copy.deepcopy(reference)
    inputs = torch.randn(2, 3, 7)
    targets = torch.tensor([2, 8], dtype=torch.long)

    reference_logits = reference(inputs)
    reference_loss = F.cross_entropy(reference_logits[:, 1, :], targets)
    reference_loss.backward()

    candidate_logits = candidate(inputs)
    candidate_loss = F.cross_entropy(candidate_logits[:, 1, :], targets)
    output: dict[str, object] = {"logits": candidate_logits}
    logits_ref = weakref.ref(candidate_logits)
    expected_bytes = candidate_logits.numel() * candidate_logits.element_size()
    del candidate_logits

    assert _release_unconsumed_training_logits(output) == expected_bytes
    gc.collect()
    assert "logits" not in output
    assert logits_ref() is None

    candidate_loss.backward()
    torch.testing.assert_close(candidate_loss, reference_loss, rtol=0.0, atol=0.0)
    torch.testing.assert_close(
        candidate.weight.grad,
        reference.weight.grad,
        rtol=0.0,
        atol=0.0,
    )


def test_cpu_base_activation_offload_is_a_noop() -> None:
    value = torch.tensor([1.0], requires_grad=True)
    with _cuda_base_activation_offload(value.device):
        objective = value.square().sum()
    objective.backward()
    torch.testing.assert_close(value.grad, torch.tensor([2.0]), rtol=0.0, atol=0.0)


def test_runtime_environment_records_cuda_allocator_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTORCH_ALLOC_CONF", "backend:native,expandable_segments:True")
    monkeypatch.delenv("PYTORCH_CUDA_ALLOC_CONF", raising=False)
    monkeypatch.delenv("PYTORCH_HIP_ALLOC_CONF", raising=False)
    monkeypatch.delenv("PYTORCH_NO_CUDA_MEMORY_CACHING", raising=False)
    environment = runtime_environment()
    assert environment["pytorch_alloc_conf"] == ("backend:native,expandable_segments:True")
    assert environment["pytorch_cuda_alloc_conf_legacy"] is None


def test_cuda_allocator_policy_rejects_missing_or_legacy_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = TrainConfig(cuda_allocator_conf="backend:native,expandable_segments:True")
    monkeypatch.delenv("PYTORCH_ALLOC_CONF", raising=False)
    monkeypatch.delenv("PYTORCH_CUDA_ALLOC_CONF", raising=False)
    monkeypatch.delenv("PYTORCH_HIP_ALLOC_CONF", raising=False)
    monkeypatch.delenv("PYTORCH_NO_CUDA_MEMORY_CACHING", raising=False)
    with pytest.raises(RuntimeError, match="policy mismatch"):
        require_cuda_allocator_policy(config)

    monkeypatch.setenv("PYTORCH_ALLOC_CONF", "backend:native,expandable_segments:True")
    monkeypatch.setenv("PYTORCH_CUDA_ALLOC_CONF", "backend:cudaMallocAsync")
    with pytest.raises(RuntimeError, match="forbids compatibility"):
        require_cuda_allocator_policy(config)

    monkeypatch.delenv("PYTORCH_CUDA_ALLOC_CONF")
    monkeypatch.setenv("PYTORCH_HIP_ALLOC_CONF", "backend:cudaMallocAsync")
    with pytest.raises(RuntimeError, match="PYTORCH_HIP_ALLOC_CONF"):
        require_cuda_allocator_policy(config)

    monkeypatch.delenv("PYTORCH_HIP_ALLOC_CONF")
    monkeypatch.setenv("PYTORCH_NO_CUDA_MEMORY_CACHING", "1")
    with pytest.raises(RuntimeError, match="PYTORCH_NO_CUDA_MEMORY_CACHING"):
        require_cuda_allocator_policy(config)

    monkeypatch.delenv("PYTORCH_NO_CUDA_MEMORY_CACHING")
    require_cuda_allocator_policy(config)


def test_effective_cuda_allocator_policy_requires_snapshot_and_live_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = TrainConfig(cuda_allocator_conf="backend:native,expandable_segments:True")
    observation = {
        "pytorch_alloc_conf": config.cuda_allocator_conf,
        "pytorch_cuda_alloc_conf_legacy": None,
        "pytorch_hip_alloc_conf_legacy": None,
        "pytorch_no_cuda_memory_caching": None,
        "allocator_backend": "native",
        "allocator_settings": config.cuda_allocator_conf,
        "allocator_initialized": True,
        "allocator_snapshot_settings": {"expandable_segments": True},
        "cuda_memory_allocated_bytes": 1,
    }
    monkeypatch.setattr(
        "latent_workspace_ft_v10.engine.allocator_runtime_environment",
        lambda: observation,
    )
    assert require_effective_cuda_allocator_policy(config, torch.device("cuda")) == observation

    broken = {**observation, "allocator_snapshot_settings": {"expandable_segments": False}}
    monkeypatch.setattr(
        "latent_workspace_ft_v10.engine.allocator_runtime_environment",
        lambda: broken,
    )
    with pytest.raises(RuntimeError, match="snapshot_expandable_segments"):
        require_effective_cuda_allocator_policy(config, torch.device("cuda"))


def test_gradient_accumulation_offload_is_validated_and_resume_bound() -> None:
    invalid = ExperimentConfig()
    invalid.train.gradient_accumulation_offload = "disk"
    with pytest.raises(ValueError, match="gradient_accumulation_offload"):
        invalid.validate()

    native = ExperimentConfig()
    offloaded = copy.deepcopy(native)
    offloaded.train.gradient_accumulation_offload = "cpu"
    assert resume_signature(native) != resume_signature(offloaded)

    cpu_accumulated = copy.deepcopy(native)
    cpu_accumulated.train.gradient_accumulation_offload = "cpu_accumulate"
    assert resume_signature(native) != resume_signature(cpu_accumulated)
    assert resume_signature(offloaded) != resume_signature(cpu_accumulated)

    activation_offloaded = copy.deepcopy(native)
    activation_offloaded.train.base_activation_offload = "all_base"
    assert resume_signature(native) != resume_signature(activation_offloaded)

    invalid_activation = copy.deepcopy(native)
    invalid_activation.train.base_activation_offload = "everything"
    with pytest.raises(ValueError, match="base_activation_offload"):
        invalid_activation.validate()

    cpu_offload = TrainConfig(gradient_accumulation_offload="cpu")
    with pytest.raises(RuntimeError, match="single-process only"):
        _require_gradient_accumulation_offload_context(
            cpu_offload,
            DistributedContext(
                enabled=True,
                rank=0,
                local_rank=0,
                world_size=2,
                backend="nccl",
                device=torch.device("cuda:0"),
            ),
        )
    with pytest.raises(RuntimeError, match="requires a CUDA device"):
        _require_gradient_accumulation_offload_context(
            cpu_offload,
            DistributedContext(
                enabled=False,
                rank=0,
                local_rank=0,
                world_size=1,
                backend="none",
                device=torch.device("cpu"),
            ),
        )


def test_cpu_gradient_accumulator_preserves_order_and_receipt(
    tmp_path: Path,
) -> None:
    initial_weight = torch.tensor(
        [[0.5, -0.25, 0.125], [-0.75, 0.375, 0.625]],
        dtype=torch.bfloat16,
    )
    initial_bias = torch.tensor([0.25, -0.5], dtype=torch.bfloat16)
    reference_weight = torch.nn.Parameter(initial_weight.clone())
    reference_bias = torch.nn.Parameter(initial_bias.clone())
    candidate_weight = torch.nn.Parameter(initial_weight.clone())
    candidate_bias = torch.nn.Parameter(initial_bias.clone())
    candidate_parameters = (
        ("weight", candidate_weight),
        ("bias", candidate_bias),
    )
    accumulator = _CPUGradientAccumulator(candidate_parameters)
    schema_records = accumulator.schema_records()
    receipt = _new_gradient_accumulation_offload_receipt(
        schema_records,
        run_id="run-gradient-offload-test",
        source_digest="a" * 64,
        resume_digest="b" * 64,
        initial_global_step=7,
        configured_accumulation_steps=3,
    )
    _start_gradient_accumulation_offload_window(
        receipt,
        global_step=7,
        batch_start=21,
        microbatch_count=3,
    )

    microbatch_gradients = (
        (
            torch.tensor(
                [[0.125, -0.5, 0.25], [0.75, -0.125, 0.375]],
                dtype=torch.bfloat16,
            ),
            torch.tensor([0.5, -0.25], dtype=torch.bfloat16),
        ),
        (
            torch.tensor(
                [[-0.375, 0.25, 0.5], [0.125, 0.25, -0.75]],
                dtype=torch.bfloat16,
            ),
            None,
        ),
        (
            None,
            torch.tensor([-0.125, 0.75], dtype=torch.bfloat16),
        ),
    )
    for microbatch_index, (weight_gradient, bias_gradient) in enumerate(microbatch_gradients):
        for reference, candidate, gradient in (
            (reference_weight, candidate_weight, weight_gradient),
            (reference_bias, candidate_bias, bias_gradient),
        ):
            if gradient is None:
                candidate.grad = None
                continue
            if reference.grad is None:
                reference.grad = gradient.clone()
            else:
                reference.grad.add_(gradient)
            candidate.grad = gradient.clone()
        spill = accumulator.spill()
        _record_gradient_accumulation_offload_spill(
            receipt,
            global_step=7,
            microbatch_index=microbatch_index,
            statistics=spill,
        )
        assert candidate_weight.grad is None
        assert candidate_bias.grad is None
        assert spill["cpu_accumulator_bytes"] > 0
        assert all(buffer.device.type == "cpu" for buffer in accumulator._buffers.values())
        assert all(buffer.dtype == torch.bfloat16 for buffer in accumulator._buffers.values())

    restored = accumulator.restore()
    assert restored["spill_count"] == 3
    assert restored["merge_count"] == 2
    assert restored["live_cpu_buffer_count"] == 0
    assert torch.equal(candidate_weight.grad, reference_weight.grad)
    assert torch.equal(candidate_bias.grad, reference_bias.grad)
    statistics = accumulator.statistics()
    _finish_gradient_accumulation_offload_window(
        receipt,
        global_step=7,
        statistics=statistics,
        restored=True,
    )
    _mark_gradient_accumulation_offload_terminal(
        receipt,
        status="completed",
        global_step=8,
    )
    receipt_path = tmp_path / "gradient_accumulation_offload.json"
    _write_gradient_accumulation_offload_receipt(receipt_path, receipt)

    stored = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert stored["mode"] == "cpu"
    assert stored["trainable_parameter_count"] == 2
    assert stored["windows_restored"] == 1
    assert stored["microbatch_spills"] == 3
    assert stored["parameter_merges"] == 2
    assert stored["peak_cpu_accumulator_bytes"] > 0
    assert stored["live_cpu_buffer_count"] == 0
    assert stored["live_cpu_buffer_bytes"] == 0
    receipt_digest = stored["receipt_sha256"]
    stored["receipt_sha256"] = None
    assert stable_hash(stored) == receipt_digest


def test_cpu_gradient_accumulator_fails_closed_on_duplicate_and_missing_state() -> None:
    parameter = torch.nn.Parameter(torch.ones((2, 3), dtype=torch.bfloat16))
    with pytest.raises(RuntimeError, match="duplicate physical"):
        _CPUGradientAccumulator((("left", parameter), ("right", parameter)))
    with pytest.raises(RuntimeError, match="requires every trainable parameter on CUDA"):
        _CPUGradientAccumulator((("weight", parameter),), require_cuda=True)

    accumulator = _CPUGradientAccumulator((("weight", parameter),))
    parameter.grad = torch.full_like(parameter, 0.25)
    accumulator.spill()
    accumulator._buffers.pop(id(parameter))
    with pytest.raises(RuntimeError, match="buffer accounting mismatch"):
        accumulator.restore()
    assert parameter.grad is None
    assert accumulator.statistics()["live_cpu_buffer_count"] == 0

    accumulator = _CPUGradientAccumulator((("weight", parameter),))
    parameter.grad = torch.full_like(parameter, 0.25)
    accumulator.spill()
    accumulator._buffers[id(parameter)] = accumulator._buffers[id(parameter)].float()
    with pytest.raises(RuntimeError, match="buffer schema mismatch.*dtype"):
        accumulator.restore()
    assert parameter.grad is None
    assert accumulator.statistics()["live_cpu_buffer_count"] == 0


def test_cpu_gradient_accumulator_cpu_merge_preserves_dtype_order() -> None:
    reference = torch.nn.Parameter(torch.tensor([0.0, 1.0, -1.0, 3.0], dtype=torch.bfloat16))
    candidate = torch.nn.Parameter(reference.detach().clone())
    gradients = [
        torch.tensor(values, dtype=torch.bfloat16)
        for values in (
            [0.125, -0.5, 0.25, 0.75],
            [-0.375, 0.25, 0.5, 0.125],
            [0.5, -0.125, -0.75, 0.25],
        )
    ]
    accumulator = _CPUGradientAccumulator(
        (("weight", candidate),),
        merge_device="cpu",
    )
    for gradient in gradients:
        if reference.grad is None:
            reference.grad = gradient.clone()
        else:
            reference.grad.add_(gradient)
        candidate.grad = gradient.clone()
        spill = accumulator.spill()
        assert spill["live_cpu_buffer_count"] >= 1
        assert candidate.grad is None

    restored = accumulator.restore()
    assert restored["live_cpu_buffer_count"] == 0
    assert torch.equal(candidate.grad, reference.grad)

    receipt = _new_gradient_accumulation_offload_receipt(
        accumulator.schema_records(),
        run_id="cpu-accumulate-receipt",
        source_digest="c" * 64,
        resume_digest="d" * 64,
        initial_global_step=0,
        configured_accumulation_steps=3,
        offload_mode="cpu_accumulate",
    )
    assert receipt["schema_version"] == 3
    assert receipt["mode"] == "cpu_accumulate"
    assert receipt["algorithm"] == "pinned_cpu_staging_cpu_dtype_ordered_add_v1"


def gradient_offload_test_schema() -> list[dict[str, object]]:
    return [
        {
            "name": "weight",
            "shape": [2],
            "stride": [1],
            "dtype": "torch.bfloat16",
            "device": "cuda:0",
            "numel": 2,
            "logical_bytes": 4,
        }
    ]


def record_gradient_offload_test_window(
    receipt: dict[str, object],
    *,
    global_step: int,
    microbatch_count: int = 2,
) -> None:
    _start_gradient_accumulation_offload_window(
        receipt,
        global_step=global_step,
        batch_start=global_step * microbatch_count,
        microbatch_count=microbatch_count,
    )
    for microbatch_index in range(microbatch_count):
        _record_gradient_accumulation_offload_spill(
            receipt,
            global_step=global_step,
            microbatch_index=microbatch_index,
            statistics={
                "spill_count": microbatch_index + 1,
                "accumulated_parameter_count": 1,
                "cpu_accumulator_bytes": 4,
                "peak_cpu_accumulator_bytes": 4,
                "cumulative_merge_count": microbatch_index,
                "cumulative_current_gradient_bytes": 4 * (microbatch_index + 1),
            },
        )
    _finish_gradient_accumulation_offload_window(
        receipt,
        global_step=global_step,
        statistics={
            "spill_count": microbatch_count,
            "merge_count": microbatch_count - 1,
            "first_spill_count": 1,
            "cumulative_current_gradient_bytes": 4 * microbatch_count,
            "peak_cpu_accumulator_bytes": 4,
            "live_cpu_buffer_count": 0,
            "live_cpu_buffer_bytes": 0,
        },
        restored=True,
    )


def write_gradient_offload_test_checkpoint(
    checkpoint: Path,
    *,
    run_id: str,
    global_step: int,
    source_digest: str,
    resume_digest: str,
) -> None:
    checkpoint.mkdir(parents=True)
    (checkpoint / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "global_step": global_step,
                "source_sha256": source_digest,
                "resume_signature": resume_digest,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (checkpoint / "COMPLETED").write_text("ok\n", encoding="utf-8")
    (checkpoint / "workspace_state.pt").write_bytes(b"workspace-state")
    (checkpoint / "trainer_state.pt").write_bytes(b"trainer-state")
    base_model = checkpoint / "base_model"
    base_model.mkdir()
    (base_model / "model.safetensors").write_bytes(b"base-model-shard")


def expected_gradient_offload_test_inventory(checkpoint: Path) -> dict[str, object]:
    records = []
    for path in sorted(
        (candidate for candidate in checkpoint.rglob("*") if candidate.is_file()),
        key=lambda candidate: candidate.relative_to(checkpoint).as_posix(),
    ):
        payload = path.read_bytes()
        records.append(
            {
                "path": path.relative_to(checkpoint).as_posix(),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return {
        "bundle_inventory_sha256": stable_hash(records),
        "file_count": len(records),
        "logical_bytes": sum(int(record["bytes"]) for record in records),
    }


def make_preempted_gradient_offload_test_receipt(
    tmp_path: Path,
) -> tuple[list[dict[str, object]], Path, Path, dict[str, object]]:
    schema = gradient_offload_test_schema()
    output_dir = tmp_path / "run"
    output_dir.mkdir()
    checkpoint = output_dir / "checkpoint-1"
    write_gradient_offload_test_checkpoint(
        checkpoint,
        run_id="run-chain-test",
        global_step=1,
        source_digest="c" * 64,
        resume_digest="d" * 64,
    )
    receipt = _new_gradient_accumulation_offload_receipt(
        schema,
        run_id="run-chain-test",
        source_digest="c" * 64,
        resume_digest="d" * 64,
        initial_global_step=0,
        configured_accumulation_steps=2,
    )
    record_gradient_offload_test_window(receipt, global_step=0)
    _mark_gradient_accumulation_offload_terminal(
        receipt,
        status="preempted",
        global_step=1,
        checkpoint=checkpoint,
        output_dir=output_dir,
    )
    receipt_path = output_dir / "gradient_accumulation_offload.json"
    _write_gradient_accumulation_offload_receipt(receipt_path, receipt)
    return schema, receipt_path, checkpoint, receipt


def test_gradient_offload_receipt_hash_chains_same_output_resume(
    tmp_path: Path,
) -> None:
    schema, receipt_path, checkpoint, preempted = make_preempted_gradient_offload_test_receipt(
        tmp_path
    )
    previous_digest = preempted["receipt_sha256"]
    previous_counters = preempted["segments"][0]["final_cumulative_counters"]

    continued = _continue_gradient_accumulation_offload_receipt(
        receipt_path,
        schema,
        run_id="run-chain-test",
        source_digest="c" * 64,
        resume_digest="d" * 64,
        resume_checkpoint=checkpoint,
        resume_step=1,
        configured_accumulation_steps=2,
    )
    assert continued["initial_global_step"] == 0
    assert continued["final_global_step"] is None
    assert continued["windows_restored"] == 1
    assert len(continued["segments"]) == 2
    assert len(continued["continuations"]) == 1
    continuation = continued["continuations"][0]
    assert continuation["previous_receipt_sha256"] == previous_digest
    assert continuation["previous_cumulative_counters"] == previous_counters
    assert continued["segments"][1]["previous_receipt_sha256"] == previous_digest
    assert continuation["checkpoint"]["scope"] == "output_dir"
    assert continuation["checkpoint"]["relative_path"] == "checkpoint-1"
    assert {
        field_name: continuation["checkpoint"][field_name]
        for field_name in (
            "bundle_inventory_sha256",
            "file_count",
            "logical_bytes",
        )
    } == expected_gradient_offload_test_inventory(checkpoint)
    assert "records" not in continuation["checkpoint"]
    assert "files" not in continuation["checkpoint"]
    assert continuation["checkpoint"]["manifest_identity"] == {
        "run_id": "run-chain-test",
        "global_step": 1,
        "source_sha256": "c" * 64,
        "resume_signature": "d" * 64,
    }
    _write_gradient_accumulation_offload_receipt(receipt_path, continued)

    record_gradient_offload_test_window(continued, global_step=1)
    _mark_gradient_accumulation_offload_terminal(
        continued,
        status="completed",
        global_step=2,
    )
    _write_gradient_accumulation_offload_receipt(receipt_path, continued)
    stored = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert stored["status"] == "completed"
    assert stored["initial_global_step"] == 0
    assert stored["final_global_step"] == 2
    assert stored["windows_started"] == 2
    assert stored["windows_restored"] == 2
    assert stored["microbatch_spills"] == 4
    assert stored["parameter_merges"] == 2
    assert [segment["status"] for segment in stored["segments"]] == [
        "preempted",
        "completed",
    ]
    assert stored["segments"][0]["initial_global_step"] == 0
    assert stored["segments"][0]["final_global_step"] == 1
    assert stored["segments"][1]["initial_global_step"] == 1
    assert stored["segments"][1]["final_global_step"] == 2
    assert str(tmp_path) not in json.dumps(stored)
    stored_digest = stored["receipt_sha256"]
    stored["receipt_sha256"] = None
    assert stable_hash(stored) == stored_digest


@pytest.mark.parametrize(
    "relative_payload",
    ["trainer_state.pt", "base_model/model.safetensors"],
)
def test_gradient_offload_same_output_resume_rejects_bundle_payload_substitution(
    tmp_path: Path,
    relative_payload: str,
) -> None:
    schema, receipt_path, checkpoint, preempted = make_preempted_gradient_offload_test_receipt(
        tmp_path
    )
    manifest_before = (checkpoint / "manifest.json").read_bytes()
    stored_descriptor = preempted["preempted_checkpoint"]
    assert isinstance(stored_descriptor, dict)
    stored_inventory = stored_descriptor["bundle_inventory_sha256"]

    payload = checkpoint / relative_payload
    payload.write_bytes(b"payload-substitution-with-unchanged-manifest")
    assert (checkpoint / "manifest.json").read_bytes() == manifest_before

    with pytest.raises(RuntimeError, match="preempted_checkpoint"):
        _continue_gradient_accumulation_offload_receipt(
            receipt_path,
            schema,
            run_id="run-chain-test",
            source_digest="c" * 64,
            resume_digest="d" * 64,
            resume_checkpoint=checkpoint,
            resume_step=1,
            configured_accumulation_steps=2,
        )
    assert preempted["preempted_checkpoint"]["bundle_inventory_sha256"] == (stored_inventory)


def test_gradient_offload_same_output_resume_rejects_tamper_stale_and_wrong_checkpoint(
    tmp_path: Path,
) -> None:
    schema, receipt_path, checkpoint, preempted = make_preempted_gradient_offload_test_receipt(
        tmp_path
    )
    arguments = {
        "run_id": "run-chain-test",
        "source_digest": "c" * 64,
        "resume_digest": "d" * 64,
        "resume_step": 1,
        "configured_accumulation_steps": 2,
    }

    tampered = copy.deepcopy(preempted)
    tampered["windows_restored"] = 99
    receipt_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(RuntimeError, match="self-hash mismatch"):
        _continue_gradient_accumulation_offload_receipt(
            receipt_path,
            schema,
            resume_checkpoint=checkpoint,
            **arguments,
        )

    stale = copy.deepcopy(preempted)
    stale["last_observed_global_step"] = 0
    _write_gradient_accumulation_offload_receipt(receipt_path, stale)
    with pytest.raises(RuntimeError, match="last_observed_global_step"):
        _continue_gradient_accumulation_offload_receipt(
            receipt_path,
            schema,
            resume_checkpoint=checkpoint,
            **arguments,
        )

    _write_gradient_accumulation_offload_receipt(receipt_path, preempted)
    wrong_checkpoint = checkpoint.parent / "checkpoint-wrong"
    write_gradient_offload_test_checkpoint(
        wrong_checkpoint,
        run_id="run-chain-test",
        global_step=1,
        source_digest="c" * 64,
        resume_digest="d" * 64,
    )
    with pytest.raises(RuntimeError, match="preempted_checkpoint"):
        _continue_gradient_accumulation_offload_receipt(
            receipt_path,
            schema,
            resume_checkpoint=wrong_checkpoint,
            **arguments,
        )

    external_checkpoint = tmp_path / "external" / "checkpoint-1"
    write_gradient_offload_test_checkpoint(
        external_checkpoint,
        run_id="run-chain-test",
        global_step=1,
        source_digest="c" * 64,
        resume_digest="d" * 64,
    )
    with pytest.raises(RuntimeError, match="checkpoint_output_containment"):
        _continue_gradient_accumulation_offload_receipt(
            receipt_path,
            schema,
            resume_checkpoint=external_checkpoint,
            **arguments,
        )


def test_gradient_offload_external_resume_descriptor_is_portable(
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "external" / "checkpoint-4"
    write_gradient_offload_test_checkpoint(
        checkpoint,
        run_id="external-run",
        global_step=4,
        source_digest="e" * 64,
        resume_digest="f" * 64,
    )
    receipt = _new_gradient_accumulation_offload_receipt(
        gradient_offload_test_schema(),
        run_id="external-run",
        source_digest="e" * 64,
        resume_digest="f" * 64,
        initial_global_step=4,
        configured_accumulation_steps=2,
        resume_checkpoint=checkpoint,
        output_dir=tmp_path / "new-output",
    )
    descriptor = receipt["segments"][0]["resume_checkpoint"]
    assert descriptor["scope"] == "external"
    assert descriptor["basename"] == "checkpoint-4"
    assert {
        field_name: descriptor[field_name]
        for field_name in (
            "bundle_inventory_sha256",
            "file_count",
            "logical_bytes",
        )
    } == expected_gradient_offload_test_inventory(checkpoint)
    assert descriptor["manifest_identity"] == {
        "run_id": "external-run",
        "global_step": 4,
        "source_sha256": "e" * 64,
        "resume_signature": "f" * 64,
    }
    assert str(tmp_path) not in json.dumps(receipt)


@pytest.mark.parametrize(
    ("unsafe_kind", "message"),
    [
        ("symlink", "symbolic links"),
        ("hardlink", "hard-linked regular files"),
        ("fifo", "special files"),
    ],
)
def test_gradient_offload_checkpoint_inventory_rejects_unsafe_entries(
    tmp_path: Path,
    unsafe_kind: str,
    message: str,
) -> None:
    checkpoint = tmp_path / "external" / "checkpoint-unsafe"
    write_gradient_offload_test_checkpoint(
        checkpoint,
        run_id="unsafe-run",
        global_step=3,
        source_digest="1" * 64,
        resume_digest="2" * 64,
    )
    unsafe_path = checkpoint / "unsafe-entry"
    try:
        if unsafe_kind == "symlink":
            unsafe_path.symlink_to("trainer_state.pt")
        elif unsafe_kind == "hardlink":
            os.link(checkpoint / "trainer_state.pt", unsafe_path)
        else:
            os.mkfifo(unsafe_path)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"{unsafe_kind} is unavailable on this filesystem: {exc}")

    with pytest.raises(RuntimeError, match=message):
        _new_gradient_accumulation_offload_receipt(
            gradient_offload_test_schema(),
            run_id="unsafe-run",
            source_digest="1" * 64,
            resume_digest="2" * 64,
            initial_global_step=3,
            configured_accumulation_steps=2,
            resume_checkpoint=checkpoint,
            output_dir=tmp_path / "new-output",
        )


def test_gradient_offload_resume_requires_exact_schedule(tmp_path: Path) -> None:
    config = ExperimentConfig()
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "manifest.json").write_text(
        json.dumps({"resume_signature": resume_signature(config)}),
        encoding="utf-8",
    )
    _require_exact_gradient_offload_resume_signature(checkpoint, config)

    extension = copy.deepcopy(config)
    extension.train.allow_schedule_extension = True
    with pytest.raises(RuntimeError, match="does not support schedule extension"):
        _require_exact_gradient_offload_resume_signature(checkpoint, extension)

    changed_schedule = copy.deepcopy(config)
    changed_schedule.train.max_steps = 12
    with pytest.raises(RuntimeError, match="exact checkpoint resume_signature"):
        _require_exact_gradient_offload_resume_signature(checkpoint, changed_schedule)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is required")
@pytest.mark.parametrize("merge_device", ["cuda", "cpu"])
def test_cuda_gradient_accumulation_offload_is_bitwise_native(
    merge_device: str,
) -> None:
    class Probe(torch.nn.Module):
        def __init__(self, weight: torch.Tensor, bias: torch.Tensor) -> None:
            super().__init__()
            self.weight = torch.nn.Parameter(weight.clone())
            self.bias = torch.nn.Parameter(bias.clone())

        def forward(self, inputs: torch.Tensor) -> torch.Tensor:
            return ((self.weight * inputs + self.bias).float().square()).sum()

    torch.manual_seed(20260824)
    device = torch.device("cuda")
    initial_weight = torch.randn(32, 64, dtype=torch.bfloat16).to(device)
    initial_bias = torch.randn(32, 64, dtype=torch.bfloat16).to(device)
    reference = Probe(initial_weight, initial_bias).to(device)
    candidate = copy.deepcopy(reference)
    microbatches = [torch.randn(32, 64, dtype=torch.bfloat16).to(device) for _ in range(4)]

    for inputs in microbatches:
        reference(inputs).backward()

    accumulator = _CPUGradientAccumulator(
        tuple(candidate.named_parameters()),
        require_cuda=True,
        merge_device=merge_device,
    )
    for inputs in microbatches:
        candidate(inputs).backward()
        accumulator.spill()
        assert all(parameter.grad is None for parameter in candidate.parameters())
    accumulator.restore()

    reference_parameters = dict(reference.named_parameters())
    candidate_parameters = dict(candidate.named_parameters())
    assert reference_parameters.keys() == candidate_parameters.keys()
    for name, expected in reference_parameters.items():
        actual = candidate_parameters[name]
        assert expected.grad is not None, name
        assert actual.grad is not None, name
        assert torch.equal(actual.grad, expected.grad), name

    reference_optimizer = torch.optim.SGD(reference.parameters(), lr=0.03125)
    candidate_optimizer = torch.optim.SGD(candidate.parameters(), lr=0.03125)
    reference_optimizer.step()
    candidate_optimizer.step()
    for name, expected in reference_parameters.items():
        actual = candidate_parameters[name]
        assert torch.equal(actual, expected), name


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is required")
def test_cuda_base_offload_preserves_accumulated_gradients() -> None:
    torch.manual_seed(20260823)
    device = torch.device("cuda")
    reference = torch.nn.Sequential(
        torch.nn.Linear(32, 64, bias=False),
        torch.nn.GELU(),
        torch.nn.Linear(64, 32, bias=False),
    ).to(device=device, dtype=torch.bfloat16)
    candidate = copy.deepcopy(reference)
    microbatches = [torch.randn(4, 8, 32, device=device, dtype=torch.bfloat16) for _ in range(3)]

    for inputs in microbatches:
        expected = reference(inputs)
        with _cuda_base_activation_offload(device):
            actual = candidate(inputs)
        torch.testing.assert_close(actual, expected, rtol=0.0, atol=0.0)
        expected.float().square().mean().backward()
        actual.float().square().mean().backward()

    for expected_parameter, actual_parameter in zip(
        reference.parameters(), candidate.parameters(), strict=True
    ):
        assert expected_parameter.grad is not None
        assert actual_parameter.grad is not None
        torch.testing.assert_close(
            actual_parameter.grad,
            expected_parameter.grad,
            rtol=0.0,
            atol=0.0,
        )


class MixedDtypeSplitProbe(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.projection = torch.nn.Linear(4, 5, bias=False, dtype=torch.float32)

    def forward(
        self, input_ids: torch.Tensor, *, bypass_workspace: bool, **_: object
    ) -> dict[str, torch.Tensor]:
        logits = self.projection(input_ids)
        if not bypass_workspace:
            logits = logits + torch.zeros((), device=logits.device, dtype=logits.dtype)
        return {"logits": logits}


class TinyCoverageModel(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.base_model = torch.nn.Linear(3, 2)


def stepped_tiny_coverage_model(
    *,
    zero_gradient_name: str | None = None,
    missing_gradient_name: str | None = None,
) -> tuple[TinyCoverageModel, Adafactor, torch.Tensor]:
    torch.manual_seed(8080)
    model = TinyCoverageModel()
    optimizer = Adafactor(
        [
            {
                "params": list(model.base_model.parameters()),
                "lr": 1e-3,
                "weight_decay": 0.01,
                "family": "base",
            }
        ],
        lr=1e-3,
        relative_step=False,
        scale_parameter=False,
        warmup_init=False,
    )
    for name, parameter in model.base_model.named_parameters():
        if name == missing_gradient_name:
            parameter.grad = None
        elif name == zero_gradient_name:
            parameter.grad = torch.zeros_like(parameter)
        else:
            parameter.grad = torch.full_like(parameter, 0.25)
    grad_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    optimizer.step()
    return model, optimizer, grad_norm


def tiny_mistral() -> MistralForCausalLM:
    torch.manual_seed(1729)
    config = MistralConfig(
        vocab_size=97,
        hidden_size=32,
        intermediate_size=64,
        num_hidden_layers=4,
        num_attention_heads=4,
        num_key_value_heads=2,
        max_position_embeddings=64,
        sliding_window=None,
        attention_dropout=0.0,
        pad_token_id=0,
        bos_token_id=1,
        eos_token_id=2,
        use_cache=False,
    )
    config._attn_implementation = "eager"
    return MistralForCausalLM(config)


def test_functional_split_equivalence_uses_training_autocast() -> None:
    model = MixedDtypeSplitProbe().train()
    report = _functional_split_equivalence_check(
        model,
        {"input_ids": torch.ones((2, 4), dtype=torch.bfloat16)},
        device=torch.device("cpu"),
        precision="bf16",
    )

    assert report["passed"] is True
    assert report["max_abs_logit_difference"] == 0.0
    assert model.training is True


def test_spectral_rank_stays_fp32_inside_bf16_autocast() -> None:
    regularizer = LatentWorkspaceLoss(hidden_dim=8, projection_dim=4)
    centered = torch.randn(4, 2, 8, dtype=torch.bfloat16)

    with torch.autocast(device_type="cpu", dtype=torch.bfloat16):
        rank_loss, effective_rank, relative_rank = regularizer._spectral_rank(centered)

    for tensor in (rank_loss, effective_rank, relative_rank):
        assert tensor.dtype == torch.float32
        assert torch.isfinite(tensor).all()


def tiny_workspace_model() -> LatentWorkspaceCausalLM:
    base_model = tiny_mistral()
    workspace = WorkspaceConfig(
        steps=1,
        workspace_dim=16,
        ff_multiplier=1.0,
        architecture="token_local",
        attention_heads=4,
        bridge_heads=4,
        logit_rank=4,
        dropout=0.0,
    )
    model = LatentWorkspaceCausalLM(
        base_model,
        hidden_dim=base_model.config.hidden_size,
        vocab_size=base_model.config.vocab_size,
        config=workspace,
    )
    configure_trainability(model, "full")
    return model


def tiny_inline_sidecar_model() -> LatentWorkspaceCausalLM:
    base_model = tiny_mistral()
    workspace = WorkspaceConfig(
        steps=1,
        workspace_dim=16,
        ff_multiplier=1.0,
        architecture="token_local",
        attention_heads=4,
        bridge_heads=4,
        logit_rank=4,
        dropout=0.0,
        route_topology="functional_workspace",
    )
    functional = FunctionalWorkspaceConfig(
        enabled=True,
        route_mode="inline_sidecar",
        boundary_layer=2,
        memory_mode="slots",
        slot_count=2,
        writer_steps=1,
        reader_steps=1,
        writer_heads=4,
        reader_heads=4,
        dropout=0.0,
        task_objective="choice_normalized",
    )
    model = LatentWorkspaceCausalLM(
        base_model,
        hidden_dim=base_model.config.hidden_size,
        vocab_size=base_model.config.vocab_size,
        config=workspace,
        functional_config=functional,
    )
    configure_trainability(model, "full")
    return model


def tiny_functional_sidecar_kwargs() -> dict[str, object]:
    batch_size, sides, queries = 1, 2, 2
    context_ids = torch.tensor([[[1, 4, 5, 6], [1, 7, 8, 9]]], dtype=torch.long)
    query_ids = torch.tensor(
        [
            [
                [[1, 30, 31, 10, 11], [1, 32, 33, 10, 11]],
                [[1, 30, 31, 10, 11], [1, 32, 33, 10, 11]],
            ]
        ],
        dtype=torch.long,
    )
    inline_ids = torch.tensor(
        [
            [
                [
                    [1, 4, 5, 6, 30, 31, 10, 11],
                    [1, 4, 5, 6, 32, 33, 10, 11],
                ],
                [
                    [1, 7, 8, 9, 30, 31, 10, 11],
                    [1, 7, 8, 9, 32, 33, 10, 11],
                ],
            ]
        ],
        dtype=torch.long,
    )
    answers = torch.tensor([[[0, 1], [1, 0]]], dtype=torch.long)
    choice_ids = torch.tensor(
        [[[[20, 21], [20, 21]], [[20, 21], [20, 21]]]],
        dtype=torch.long,
    )

    query_labels = torch.full_like(query_ids, -100)
    inline_labels = torch.full_like(inline_ids, -100)
    for side in range(sides):
        for query in range(queries):
            target = int(choice_ids[0, side, query, answers[0, side, query]].item())
            query_labels[0, side, query, -1] = target
            inline_labels[0, side, query, -1] = target

    return {
        "functional_context_input_ids": context_ids,
        "functional_context_attention_mask": torch.ones_like(context_ids),
        "functional_query_input_ids": query_ids,
        "functional_query_attention_mask": torch.ones_like(query_ids),
        "functional_query_labels": query_labels,
        "functional_inline_input_ids": inline_ids,
        "functional_inline_attention_mask": torch.ones_like(inline_ids),
        "functional_inline_labels": inline_labels,
        "functional_query_choice_ids": choice_ids,
        "functional_inline_choice_ids": choice_ids.clone(),
        "functional_answer_classes": answers,
        "functional_query_valid_mask": torch.ones((batch_size, queries), dtype=torch.bool),
        "functional_affected_mask": torch.tensor([[True, False]]),
        "functional_heldout_mask": torch.tensor([[False, True]]),
        "functional_hop_distances": torch.tensor([[1, 2]], dtype=torch.long),
        "functional_pair_ids": torch.tensor([17], dtype=torch.long),
        "compute_workspace_loss": False,
        "compute_spectral": False,
        "rng_streams": None,
        "memory_intervention": "intact",
        "memory_intervention_seed": 123,
    }


def test_v12_inline_sidecar_is_exact_noop_and_opens_at_adapter() -> None:
    model = tiny_inline_sidecar_model().eval()
    kwargs = tiny_functional_sidecar_kwargs()
    with torch.no_grad():
        routed = model._forward_functional_workspace(
            **kwargs,
            bypass_workspace=False,
        )
        amputated = model._forward_functional_workspace(
            **kwargs,
            bypass_workspace=True,
        )
    assert torch.equal(routed["logits"], amputated["logits"])
    assert float(routed["delta_logit_norm"].item()) == 0.0

    model.train()
    model.zero_grad(set_to_none=True)
    output = model._forward_functional_workspace(
        **kwargs,
        bypass_workspace=False,
    )
    output["task_loss"].backward()
    assert model.functional_sidecar_adapter is not None
    adapter_gradient = model.functional_sidecar_adapter.up.weight.grad
    assert adapter_gradient is not None
    assert torch.count_nonzero(adapter_gradient).item() > 0


def test_v12_inline_sidecar_hard_bypass_ignores_affine_adapter_residual() -> None:
    model = tiny_inline_sidecar_model().eval()
    assert model.functional_sidecar_adapter is not None
    with torch.no_grad():
        model.functional_sidecar_adapter.norm.bias.add_(0.5)
        model.functional_sidecar_adapter.up.weight.normal_(mean=0.0, std=0.02)
        adapter_residual = model.functional_sidecar_adapter(
            torch.zeros(1, model.functional_sidecar_adapter.norm.normalized_shape[0])
        )
    assert float(adapter_residual.abs().max().item()) > 0.0

    kwargs = tiny_functional_sidecar_kwargs()
    kwargs["memory_intervention"] = "hard_bypass"
    with torch.no_grad():
        bypassed = model._forward_functional_workspace(
            **kwargs,
            bypass_workspace=False,
        )
        amputated = model._forward_functional_workspace(
            **kwargs,
            bypass_workspace=True,
        )
    assert torch.equal(bypassed["logits"], amputated["logits"])
    assert float(bypassed["delta_logit_norm"].item()) == 0.0


def test_v12_frozen_base_step_drops_gradients_and_optimizer_state() -> None:
    model = tiny_workspace_model()
    optimizer = build_optimizer(
        model,
        TrainConfig(
            optimizer="adafactor",
            fused_adamw="false",
            learning_rate=1e-3,
            workspace_learning_rate=2e-3,
        ),
        torch.device("cpu"),
    )
    base_parameters = [
        parameter for name, parameter in model.named_parameters() if name.startswith("base_model.")
    ]
    workspace_parameters = [
        parameter
        for name, parameter in model.named_parameters()
        if not name.startswith("base_model.")
    ]
    base_before = [parameter.detach().clone() for parameter in base_parameters]
    workspace_before = [parameter.detach().clone() for parameter in workspace_parameters]
    for parameter in [*base_parameters, *workspace_parameters]:
        parameter.grad = torch.ones_like(parameter)

    assert _clear_parameter_family_gradients(model, "base") == len(base_parameters)
    _set_optimizer_family_learning_rate(optimizer, "base", 0.0)
    optimizer.step()

    assert all(
        torch.equal(before, after)
        for before, after in zip(base_before, base_parameters, strict=True)
    )
    assert any(
        not torch.equal(before, after)
        for before, after in zip(workspace_before, workspace_parameters, strict=True)
    )
    assert all(parameter not in optimizer.state for parameter in base_parameters)
    assert _optimizer_family_state_entries(optimizer)["base"] == 0
    assert _optimizer_family_state_entries(optimizer)["workspace"] > 0


@pytest.fixture(params=["unpadded", "right_padded"])
def token_batch(request: pytest.FixtureRequest) -> tuple[torch.Tensor, torch.Tensor]:
    if request.param == "unpadded":
        input_ids = torch.tensor([[1, 4, 5, 6, 7, 8], [1, 9, 10, 11, 12, 13]], dtype=torch.long)
        attention_mask = torch.ones_like(input_ids)
    else:
        input_ids = torch.tensor([[1, 4, 5, 6, 7, 8], [1, 9, 10, 11, 0, 0]], dtype=torch.long)
        attention_mask = torch.tensor([[1, 1, 1, 1, 1, 1], [1, 1, 1, 1, 0, 0]], dtype=torch.long)
    return input_ids, attention_mask


@pytest.mark.parametrize("boundary", [0, 2, 4])
def test_mistral_full_and_split_logits_match(
    token_batch: tuple[torch.Tensor, torch.Tensor], boundary: int
) -> None:
    model = tiny_mistral().eval()
    adapter = FunctionalBoundaryAdapter(model)
    input_ids, attention_mask = token_batch

    with torch.no_grad():
        expected = model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            use_cache=False,
            return_dict=True,
        ).logits
        hidden = adapter.encode(input_ids, attention_mask, boundary)
        actual = adapter.decode(hidden, attention_mask, boundary)

    torch.testing.assert_close(actual, expected, rtol=1e-6, atol=1e-6)


def test_mistral_split_gradient_parity_with_checkpointing() -> None:
    full_model = tiny_mistral().train()
    split_model = copy.deepcopy(full_model).train()
    full_model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    split_model.gradient_checkpointing_enable(
        gradient_checkpointing_kwargs={"use_reentrant": False}
    )
    assert all(layer.gradient_checkpointing for layer in split_model.model.layers)

    input_ids = torch.tensor([[1, 7, 8, 9, 10, 11], [1, 12, 13, 14, 0, 0]], dtype=torch.long)
    attention_mask = torch.tensor([[1, 1, 1, 1, 1, 1], [1, 1, 1, 1, 0, 0]], dtype=torch.long)

    expected_logits = full_model(
        input_ids=input_ids,
        attention_mask=attention_mask,
        use_cache=False,
        return_dict=True,
    ).logits
    torch.manual_seed(314159)
    cotangent = torch.randn_like(expected_logits)
    (expected_logits * cotangent).sum().backward()

    adapter = FunctionalBoundaryAdapter(split_model)
    hidden = adapter.encode(input_ids, attention_mask, boundary_layer=2)
    actual_logits = adapter.decode(hidden, attention_mask, boundary_layer=2)
    (actual_logits * cotangent).sum().backward()

    torch.testing.assert_close(actual_logits, expected_logits, rtol=1e-6, atol=1e-6)
    full_parameters = dict(full_model.named_parameters())
    split_parameters = dict(split_model.named_parameters())
    assert full_parameters.keys() == split_parameters.keys()
    for name, expected_parameter in full_parameters.items():
        actual_parameter = split_parameters[name]
        assert (expected_parameter.grad is None) == (actual_parameter.grad is None), name
        if expected_parameter.grad is not None:
            torch.testing.assert_close(
                actual_parameter.grad,
                expected_parameter.grad,
                rtol=2e-5,
                atol=2e-5,
                msg=lambda message, name=name: f"{name}: {message}",
            )


def test_mistral_layer_count_and_boundaries() -> None:
    model = tiny_mistral()
    adapter = FunctionalBoundaryAdapter(model)
    input_ids = torch.tensor([[1, 3, 4, 5]], dtype=torch.long)
    attention_mask = torch.ones_like(input_ids)

    assert adapter.layer_count() == model.config.num_hidden_layers == 4
    for boundary in (0, adapter.layer_count()):
        hidden = adapter.encode(input_ids, attention_mask, boundary)
        logits = adapter.decode(hidden, attention_mask, boundary)
        assert logits.shape == (1, 4, model.config.vocab_size)
    with pytest.raises(ValueError, match=r"outside \[0, 4\]"):
        adapter.encode(input_ids, attention_mask, -1)
    with pytest.raises(ValueError, match=r"outside \[0, 4\]"):
        adapter.decode(model.model.embed_tokens(input_ids), attention_mask, 5)


def test_gpt2_split_regression_with_right_padding() -> None:
    torch.manual_seed(2718)
    config = GPT2Config(
        vocab_size=97,
        n_embd=32,
        n_layer=2,
        n_head=4,
        n_positions=16,
        n_ctx=16,
        resid_pdrop=0.0,
        embd_pdrop=0.0,
        attn_pdrop=0.0,
        pad_token_id=0,
        use_cache=False,
    )
    config._attn_implementation = "eager"
    model = GPT2LMHeadModel(config).eval()
    adapter = FunctionalBoundaryAdapter(model)
    input_ids = torch.tensor([[1, 4, 5, 6, 7], [1, 8, 9, 0, 0]], dtype=torch.long)
    attention_mask = input_ids.ne(0).long()

    with torch.no_grad():
        expected = model(input_ids=input_ids, attention_mask=attention_mask, use_cache=False).logits
        for boundary in range(adapter.layer_count() + 1):
            hidden = adapter.encode(input_ids, attention_mask, boundary)
            actual = adapter.decode(hidden, attention_mask, boundary)
            torch.testing.assert_close(actual, expected, rtol=0.0, atol=0.0)


def test_adafactor_keeps_full_model_trainable_and_in_resume_identity() -> None:
    model = tiny_workspace_model()
    base_model = model.base_model
    assert all(parameter.requires_grad for parameter in model.base_model.parameters())

    train = TrainConfig(
        optimizer="adafactor",
        learning_rate=1e-3,
        workspace_learning_rate=2e-3,
        fused_adamw="false",
    )
    optimizer = build_optimizer(model, train, torch.device("cpu"))
    assert isinstance(optimizer, Adafactor)
    coverage = optimizer_coverage_report(model, optimizer, train_mode="full")
    require_exact_optimizer_coverage(coverage)
    assert coverage["passed"] is True
    assert coverage["checks"] == {
        "unique_membership_exact": True,
        "duplicate_membership_free": True,
        "full_mode_base_all_trainable": True,
    }
    assert coverage["optimizer_duplicate_memberships"] == 0
    assert (
        coverage["model_trainable_unique_physical_parameters"]
        == coverage["optimizer_unique_physical_parameters"]
    )
    assert coverage["expected_membership_sha256"] == coverage["optimizer_membership_sha256"]
    assert (
        coverage["report_sha256"]
        == optimizer_coverage_report(model, optimizer, train_mode="full")["report_sha256"]
    )
    replica = tiny_workspace_model()
    replica_optimizer = build_optimizer(replica, train, torch.device("cpu"))
    replica_coverage = optimizer_coverage_report(replica, replica_optimizer, train_mode="full")
    assert coverage["report_sha256"] == replica_coverage["report_sha256"]
    bindings = coverage["base_optimizer_bindings"]
    assert bindings
    assert all(name == binding["artifact_name"] for name, binding in bindings.items())
    assert all(not name.startswith("base_model.") for name in bindings)
    assert all(binding["optimizer_family"] == "base" for binding in bindings.values())
    assert all(
        isinstance(binding["optimizer_group_index"], int)
        and isinstance(binding["optimizer_parameter_index"], int)
        for binding in bindings.values()
    )
    assert {group["family"] for group in optimizer.param_groups} == {
        "base",
        "workspace",
    }
    assert {group["family"]: group["lr"] for group in optimizer.param_groups} == {
        "base": pytest.approx(1e-3),
        "workspace": pytest.approx(2e-3),
    }

    optimized_ids = {
        id(parameter) for group in optimizer.param_groups for parameter in group["params"]
    }
    base_ids = {id(parameter) for parameter in model.base_model.parameters()}
    assert base_ids <= optimized_ids

    before = base_model.model.layers[0].self_attn.q_proj.weight.detach().clone()
    input_ids = torch.tensor([[1, 4, 5, 6]], dtype=torch.long)
    attention_mask = torch.ones_like(input_ids)
    logits = base_model(
        input_ids=input_ids,
        attention_mask=attention_mask,
        use_cache=False,
        return_dict=True,
    ).logits[:, -1]
    target = torch.tensor([7], dtype=torch.long)
    loss = F.cross_entropy(logits, target)
    loss.backward()
    sentinel = optimizer_step_with_base_sentinel(
        model,
        optimizer,
        preferred_output_rows=[int(target.item())],
    )
    after = base_model.model.layers[0].self_attn.q_proj.weight.detach()
    assert not torch.equal(before, after)
    assert sentinel["parameter_name"].endswith("lm_head.weight")
    assert sentinel["selection"] == "supervised_output_row_max_abs_gradient"
    assert sentinel["gradient_nonzero"] is True
    assert sentinel["optimizer_step_skipped"] is False
    assert sentinel["updated"] is True
    assert sentinel["sample_max_abs_delta"] > 0.0
    assert sentinel["sample_nonzero_delta_elements"] > 0

    adamw_config = ExperimentConfig()
    adafactor_config = copy.deepcopy(adamw_config)
    adafactor_config.train.optimizer = "adafactor"
    assert resume_signature(adamw_config) != resume_signature(adafactor_config)


def test_exact_optimizer_restore_preserves_fp32_adafactor_state_for_bf16() -> None:
    parameter = torch.nn.Parameter(
        torch.tensor([[0.5, -0.25], [0.125, -0.75]], dtype=torch.bfloat16)
    )
    optimizer = Adafactor(
        [parameter],
        lr=1e-3,
        relative_step=False,
        scale_parameter=False,
        warmup_init=False,
    )
    parameter.grad = torch.full_like(parameter, 0.25)
    optimizer.step()
    saved = copy.deepcopy(optimizer.state_dict())
    saved_state = next(iter(saved["state"].values()))
    assert saved_state["exp_avg_sq_row"].dtype == torch.float32

    resumed_parameter = torch.nn.Parameter(parameter.detach().clone())
    resumed_optimizer = Adafactor(
        [resumed_parameter],
        lr=1e-3,
        relative_step=False,
        scale_parameter=False,
        warmup_init=False,
    )
    resumed_optimizer.load_state_dict(saved)
    assert resumed_optimizer.state[resumed_parameter]["exp_avg_sq_row"].dtype == (torch.bfloat16)

    _restore_optimizer_state_exact(resumed_optimizer, saved)
    restored_state = resumed_optimizer.state[resumed_parameter]
    for name, expected in saved_state.items():
        actual = restored_state[name]
        if isinstance(expected, torch.Tensor):
            assert actual.dtype == expected.dtype
            assert torch.equal(actual.cpu(), expected)
        else:
            assert actual == expected

    next_gradient = torch.tensor([[0.125, -0.375], [0.5, -0.625]], dtype=torch.bfloat16)
    parameter.grad = next_gradient.clone()
    resumed_parameter.grad = next_gradient.clone()
    optimizer.step()
    resumed_optimizer.step()

    assert torch.equal(parameter, resumed_parameter)
    expected_state = optimizer.state[parameter]
    actual_state = resumed_optimizer.state[resumed_parameter]
    assert expected_state.keys() == actual_state.keys()
    for name, expected in expected_state.items():
        actual = actual_state[name]
        if isinstance(expected, torch.Tensor):
            assert actual.dtype == expected.dtype
            assert torch.equal(actual, expected)
        else:
            assert actual == expected


def test_optimizer_coverage_rejects_missing_duplicate_and_frozen_full_base() -> None:
    train = TrainConfig(optimizer="adafactor", fused_adamw="false")

    missing_model = tiny_workspace_model()
    missing_optimizer = build_optimizer(missing_model, train, torch.device("cpu"))
    removed = missing_optimizer.param_groups[0]["params"].pop()
    assert isinstance(removed, torch.nn.Parameter)
    missing = optimizer_coverage_report(missing_model, missing_optimizer, train_mode="full")
    assert missing["passed"] is False
    assert missing["checks"]["unique_membership_exact"] is False
    assert len(missing["missing_parameters"]) == 1
    with pytest.raises(RuntimeError, match="not exact"):
        require_exact_optimizer_coverage(missing)

    duplicate_model = tiny_workspace_model()
    duplicate_optimizer = build_optimizer(duplicate_model, train, torch.device("cpu"))
    duplicated = duplicate_optimizer.param_groups[0]["params"][0]
    duplicate_optimizer.param_groups[0]["params"].append(duplicated)
    duplicate = optimizer_coverage_report(duplicate_model, duplicate_optimizer, train_mode="full")
    assert duplicate["passed"] is False
    assert duplicate["checks"]["unique_membership_exact"] is True
    assert duplicate["checks"]["duplicate_membership_free"] is False
    assert duplicate["optimizer_duplicate_memberships"] == 1
    assert len(duplicate["duplicate_parameters"]) == 1

    frozen_model = tiny_workspace_model()
    frozen_parameter = next(frozen_model.base_model.parameters())
    frozen_parameter.requires_grad_(False)
    frozen_optimizer = build_optimizer(frozen_model, train, torch.device("cpu"))
    frozen = optimizer_coverage_report(frozen_model, frozen_optimizer, train_mode="full")
    assert frozen["checks"]["unique_membership_exact"] is True
    assert frozen["checks"]["full_mode_base_all_trainable"] is False
    assert frozen["passed"] is False
    assert frozen["frozen_base_parameters"]


def test_optimizer_coverage_hash_and_resume_mapping_are_fail_closed(
    tmp_path: Path,
) -> None:
    model = tiny_workspace_model()
    optimizer = build_optimizer(
        model,
        TrainConfig(optimizer="adafactor", fused_adamw="false"),
        torch.device("cpu"),
    )
    report = optimizer_coverage_report(model, optimizer, train_mode="full")
    checkpoint = tmp_path / "checkpoint-1"
    checkpoint.mkdir()
    (checkpoint / "optimizer_coverage.json").write_text(json.dumps(report), encoding="utf-8")
    _require_resume_optimizer_mapping(checkpoint, report)

    tampered = copy.deepcopy(report)
    first = next(iter(tampered["base_optimizer_bindings"].values()))
    first["optimizer_parameter_index"] += 1
    with pytest.raises(RuntimeError, match="sha256_valid=False"):
        require_exact_optimizer_coverage(tampered)

    tampered["report_sha256"] = stable_hash(
        {key: value for key, value in tampered.items() if key != "report_sha256"}
    )
    with pytest.raises(RuntimeError, match="mapping differs"):
        _require_resume_optimizer_mapping(checkpoint, tampered)


def test_base_update_coverage_accepts_complete_adafactor_step() -> None:
    model, optimizer, grad_norm = stepped_tiny_coverage_model()
    report = base_update_coverage_report(
        model,
        optimizer,
        train_mode="full",
        global_clip_grad_norm=grad_norm,
        optimizer_step_performed=True,
        optimizer_step_skipped=False,
    )

    require_base_update_coverage(report)
    assert report["format"] == "latent-workspace-ft-base-update-coverage-v1"
    assert report["passed"] is True
    assert report["base_parameter_count"] == 2
    assert report["base_parameter_numel"] == 8
    assert report["checks"] == {
        "all_base_parameters_trainable": True,
        "optimizer_membership_exact": True,
        "all_gradients_present": True,
        "all_gradients_finite": True,
        "all_gradients_nonzero": True,
        "positive_base_learning_rate": True,
        "optimizer_step_performed": True,
        "optimizer_step_not_skipped": True,
        "all_optimizer_states_advanced": True,
    }
    assert [parameter["name"] for parameter in report["parameters"]] == [
        "bias",
        "weight",
    ]
    for parameter in report["parameters"]:
        assert parameter["aliases"] == [parameter["name"]]
        assert parameter["optimizer_family"] == "base"
        assert parameter["learning_rate"] == pytest.approx(1e-3)
        assert parameter["weight_decay"] == pytest.approx(0.01)
        assert parameter["gradient_present"] is True
        assert parameter["gradient_finite"] is True
        assert parameter["gradient_nonzero"] is True
        assert parameter["gradient_nonzero_elements"] == parameter["numel"]
        assert parameter["state_step"] == 1
        assert parameter["update_attempted"] is True


def test_base_update_coverage_rejects_zero_gradient() -> None:
    model, optimizer, grad_norm = stepped_tiny_coverage_model(zero_gradient_name="bias")
    report = base_update_coverage_report(
        model,
        optimizer,
        train_mode="full",
        global_clip_grad_norm=grad_norm,
        optimizer_step_performed=True,
        optimizer_step_skipped=False,
    )

    assert report["passed"] is False
    assert report["checks"]["all_gradients_nonzero"] is False
    bias = next(parameter for parameter in report["parameters"] if parameter["name"] == "bias")
    assert bias["gradient_nonzero_elements"] == 0
    assert bias["gradient_nonzero"] is False
    with pytest.raises(RuntimeError, match="all_gradients_nonzero"):
        require_base_update_coverage(report)


def test_base_update_coverage_rejects_missing_gradient() -> None:
    model, optimizer, grad_norm = stepped_tiny_coverage_model(missing_gradient_name="bias")
    report = base_update_coverage_report(
        model,
        optimizer,
        train_mode="full",
        global_clip_grad_norm=grad_norm,
        optimizer_step_performed=True,
        optimizer_step_skipped=False,
    )

    assert report["passed"] is False
    assert report["checks"]["all_gradients_present"] is False
    assert report["checks"]["all_optimizer_states_advanced"] is False
    bias = next(parameter for parameter in report["parameters"] if parameter["name"] == "bias")
    assert bias["gradient_present"] is False
    assert bias["state_step"] is None
    assert bias["update_attempted"] is False


def test_base_update_coverage_rejects_missing_optimizer_state() -> None:
    model, optimizer, grad_norm = stepped_tiny_coverage_model()
    optimizer.state.pop(model.base_model.bias)
    report = base_update_coverage_report(
        model,
        optimizer,
        train_mode="full",
        global_clip_grad_norm=grad_norm,
        optimizer_step_performed=True,
        optimizer_step_skipped=False,
    )

    assert report["passed"] is False
    assert report["checks"]["all_optimizer_states_advanced"] is False
    bias = next(parameter for parameter in report["parameters"] if parameter["name"] == "bias")
    assert bias["state_step"] is None


def test_base_update_coverage_is_deterministic_and_tamper_evident() -> None:
    left_model, left_optimizer, left_norm = stepped_tiny_coverage_model()
    right_model, right_optimizer, right_norm = stepped_tiny_coverage_model()
    left = base_update_coverage_report(
        left_model,
        left_optimizer,
        train_mode="full",
        global_clip_grad_norm=left_norm,
        optimizer_step_performed=True,
        optimizer_step_skipped=False,
    )
    right = base_update_coverage_report(
        right_model,
        right_optimizer,
        train_mode="full",
        global_clip_grad_norm=right_norm,
        optimizer_step_performed=True,
        optimizer_step_skipped=False,
    )

    assert left == right
    assert left["report_sha256"] == right["report_sha256"]
    tampered = copy.deepcopy(left)
    tampered["parameters"][0]["gradient_nonzero_elements"] = 0
    with pytest.raises(RuntimeError, match="sha256_valid=False"):
        require_base_update_coverage(tampered)


def test_adafactor_rejects_explicit_fused_adamw() -> None:
    config = ExperimentConfig()
    config.train.optimizer = "adafactor"
    config.train.fused_adamw = "true"
    with pytest.raises(ValueError, match="valid only"):
        config.validate()
