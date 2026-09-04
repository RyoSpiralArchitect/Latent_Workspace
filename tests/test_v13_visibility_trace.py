from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
import torch
import torch.nn.functional as F
from test_engine_mistral import tiny_functional_sidecar_kwargs, tiny_inline_sidecar_model

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
trace_module = importlib.import_module("v13_visibility_trace")


def make_batch() -> dict[str, torch.Tensor]:
    batch = {
        key: value
        for key, value in tiny_functional_sidecar_kwargs().items()
        if key.startswith("functional_")
    }
    batch["sample_indices"] = torch.tensor([0])
    return batch


def test_same_tensor_bf16_recomposition_exposes_invisible_residual() -> None:
    base = torch.tensor([[20.0, 19.0]], dtype=torch.bfloat16)
    residual = torch.tensor([[0.01, -0.01]], dtype=torch.float32)
    result = trace_module.recompose_candidates(base, residual, gains=(1.0, 4.0))
    assert torch.equal(result["native"], base)
    assert torch.count_nonzero(result["residual_postcast"]) == 2
    assert not torch.equal(result["fp32"], base.float())
    torch.testing.assert_close(result["fp32"], base.float() + residual)
    torch.testing.assert_close(result["bf16_ulp_up"], torch.full((1, 2), 0.125))
    assert set(result["fp32_diagnostic_gains"]) == {"1", "4"}


def test_candidate_selection_uses_supervised_source_not_last_padding() -> None:
    labels = torch.tensor([[-100, -100, 2, -100], [-100, 1, -100, -100]])
    logits = torch.arange(24).reshape(2, 4, 3).float()
    positions = trace_module.answer_positions(labels)
    assert positions.tolist() == [1, 0]
    selected = trace_module.candidates(logits, positions, torch.tensor([[2, 1], [1, 2]]))
    assert selected.tolist() == [[5, 4], [13, 14]]


def test_tensor_hash_binds_dtype_shape_and_signed_zero() -> None:
    assert trace_module.tensor_hash(torch.tensor(0.0)) != trace_module.tensor_hash(
        torch.tensor(-0.0)
    )
    assert trace_module.tensor_hash(torch.tensor([0.0])) != trace_module.tensor_hash(
        torch.tensor(0.0)
    )


def test_trace_is_passthrough_and_captures_actual_sdpa() -> None:
    torch.manual_seed(43)
    torch.set_num_threads(1)
    model = tiny_inline_sidecar_model().eval()
    with torch.no_grad():
        model.functional_sidecar_adapter.up.weight.normal_(std=0.01)
    batch = make_batch()
    original_sdpa = F.scaled_dot_product_attention
    states = {key: tensor.clone() for key, tensor in model.state_dict().items()}
    result = trace_module.capture_loaded_batch(model, batch, modes=("intact",), raw_query_limit=1)
    captured = result["captures"]["intact"]
    assert F.scaled_dot_product_attention is original_sdpa
    assert captured["metadata"]["counts"]["reader_sdpa"] == 1
    assert all(captured["metadata"]["checks"].values())
    tensors = captured["tensors"]
    assert tensors["reader.actual_sdpa_k"].ndim == 4
    assert tensors["reader.actual_sdpa_v"].ndim == 4
    assert tensors["reader.query_input.raw_prefix"].shape[0] == 1
    assert tensors["reader.query_input.answer"].shape[0] == 4
    kwargs = {key: value for key, value in tiny_functional_sidecar_kwargs().items()}
    with torch.no_grad():
        plain = model._forward_functional_workspace(**kwargs, bypass_workspace=False)
    plain_candidates = trace_module.candidates(
        plain["logits"], result["positions"], result["flat"]["candidate_ids"]
    )
    assert trace_module.bitwise_equal(plain_candidates, tensors["wrapper.actual_candidates"])
    for name, tensor in model.state_dict().items():
        assert torch.equal(states[name], tensor)


def test_auxiliary_reader_does_not_replace_primary_capture() -> None:
    torch.manual_seed(44)
    model = tiny_inline_sidecar_model().eval()
    model.functional_config.counterfactual_weight = 1.0
    model.functional_config.stability_weight = 0.25
    result = trace_module.capture_loaded_batch(model, make_batch(), modes=("intact",))
    counts = result["captures"]["intact"]["metadata"]["counts"]
    assert counts["reader"] == 2
    assert counts["adapter"] == 2
    assert counts["reader_sdpa"] == 1


def test_bf16_cpu_autocast_trace_preserves_actual_rounding_boundaries() -> None:
    torch.manual_seed(46)
    model = tiny_inline_sidecar_model().eval()
    model.base_model.to(torch.bfloat16)
    with torch.no_grad():
        model.functional_sidecar_adapter.up.weight.normal_(std=0.0001)
    result = trace_module.capture_loaded_batch(
        model, make_batch(), modes=("intact",), precision="bf16", raw_query_limit=0
    )
    captured = result["captures"]["intact"]
    assert captured["tensors"]["base.candidates"].dtype == torch.bfloat16
    assert all(captured["metadata"]["checks"].values())
    assert trace_module.bitwise_equal(
        captured["recomposed"]["native"], captured["tensors"]["wrapper.actual_candidates"]
    )


def test_all_controls_and_legacy_hard_bypass_remain_distinct() -> None:
    torch.manual_seed(45)
    model = tiny_inline_sidecar_model().eval()
    with torch.no_grad():
        model.functional_sidecar_adapter.up.weight.normal_(std=0.01)
        model.functional_sidecar_adapter.norm.bias.fill_(0.02)
    result = trace_module.capture_loaded_batch(
        model, make_batch(), modes=(*trace_module.MODES, "hard_bypass"), raw_query_limit=0
    )
    assert trace_module.bitwise_equal(result["direct_base"], result["true_bypass"])
    legacy = result["captures"]["hard_bypass"]
    assert legacy["metadata"]["counts"]["reader_sdpa"] == 0
    assert legacy["metadata"]["legacy_hard_bypass_is_not_true_amputation"]
    assert torch.count_nonzero(legacy["tensors"]["adapter.candidates_precast"]) > 0
    assert "reader.actual_sdpa_k" not in legacy["tensors"]
    assert not any("raw_prefix" in name for name in legacy["tensors"])
    intact = result["captures"]["intact"]["tensors"]["reader.memory_input"]
    zero = result["captures"]["zero"]["tensors"]["reader.memory_input"]
    assert torch.count_nonzero(intact) > 0
    assert torch.count_nonzero(zero) == 0


def test_hooks_restore_after_exception_and_nested_capture_rejected() -> None:
    model = tiny_inline_sidecar_model().eval()
    positions = torch.tensor([1])
    choices = torch.tensor([[1, 2]])
    original_sdpa = F.scaled_dot_product_attention
    with pytest.raises(RuntimeError, match="intentional"):
        with trace_module.VisibilityTrace(model, positions, choices):
            with pytest.raises(trace_module.VisibilityError, match="Nested"):
                with trace_module.VisibilityTrace(model, positions, choices):
                    pass
            raise RuntimeError("intentional")
    assert F.scaled_dot_product_attention is original_sdpa
    assert not model.functional_reader._forward_hooks
    assert not model.functional_sidecar_adapter._forward_pre_hooks


@pytest.mark.parametrize("gains", [(), (0.0,), (float("nan"),), (-1.0,)])
def test_invalid_gain_grid_fails_closed(gains: tuple[float, ...]) -> None:
    with pytest.raises(trace_module.VisibilityError):
        trace_module.recompose_candidates(torch.zeros(1, 2), torch.zeros(1, 2), gains=gains)


def test_multi_step_reader_is_not_silently_mislabelled() -> None:
    model = tiny_inline_sidecar_model().eval()
    model.functional_config.reader_steps = 2
    with pytest.raises(trace_module.VisibilityError, match="one reader step"):
        trace_module.VisibilityTrace(model, torch.tensor([1]), torch.tensor([[1, 2]]))
