"""CPU FP32 wrapper checks; no BF16 backend failures hidden or reconfigured."""

import dataclasses
import json
import sys
from pathlib import Path

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import v14_workspace_instrument as instrument  # noqa: E402
from test_engine_mistral import (  # noqa: E402
    tiny_functional_sidecar_kwargs,
    tiny_inline_sidecar_model,
)

from latent_workspace_ft_v10.engine import LatentWorkspaceCausalLM  # noqa: E402


@pytest.fixture(autouse=True)
def bounded_cpu_threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(previous)


def fixture():
    template = tiny_inline_sidecar_model()
    config = dataclasses.replace(template.functional_config, logit_composition="fp32_accumulate")
    wrapper = LatentWorkspaceCausalLM(
        template.base_model,
        template.hidden_dim,
        template.vocab_size,
        template.workspace_config,
        functional_config=config,
    )
    batch = tiny_functional_sidecar_kwargs()
    batch["sample_indices"] = torch.tensor([0])  # Production collator bookkeeping.
    return wrapper, batch


def run(wrapper, batch):
    return instrument.run_instrument(wrapper, batch, device="cpu", precision="fp32")


def assert_clean(wrapper, before):
    for name, value in wrapper.state_dict().items():
        assert torch.equal(value, before[name]), name
    assert all(p.grad is None for p in wrapper.parameters())
    assert all(
        not module._forward_hooks and not module._forward_pre_hooks for module in wrapper.modules()
    )


def test_full_instrument_and_zero_open_gradient_contracts():
    wrapper, batch = fixture()
    before = {name: value.clone() for name, value in wrapper.state_dict().items()}
    sdpa = torch.nn.functional.scaled_dot_product_attention
    report = run(wrapper, batch)
    assert report["status"] == "COMPLETE", report.get("error", report["checks"])
    assert report["instrument_checks_passed"] and all(report["checks"].values())
    assert report["scientific_success"] is False and report["training_performed"] is False
    assert report["cases"]["true_bypass"]["counts"] == dict(base=1, writer=0, reader=0, adapter=0)
    assert report["cases"]["zero_up"]["sidecar_full"]["nonzero_elements"] == 0
    assert report["cases"]["opened_hard_bypass"]["counts"] == dict(
        base=1, writer=1, reader=0, adapter=1
    )
    for family in ("writer", "reader", "adapter_upstream"):
        assert report["gradients"]["zero_up"]["groups"][family]["nonzero_parameters"] == 0
        assert report["gradients"]["opened"]["groups"][family]["nonzero_parameters"] > 0
    assert report["gradients"]["opened"]["groups"]["base"]["present"] == 0
    assert report["norm_observation"]["counts"]["writer.slot_norm"]["invoked"] == 4
    assert report["norm_observation"]["counts"]["reader.query_norm"]["invoked"] == 2
    assert report["probe"]["seed"] == 1403 and report["probe"]["std"] == 0.01
    assert report["restoration"]["base_weight_bytes_rehashed"] is False
    assert torch.nn.functional.scaled_dot_product_attention is sdpa
    assert_clean(wrapper, before)
    json.dumps(report, allow_nan=False)


def test_original_up_training_and_gradient_flags_are_restored():
    wrapper, batch = fixture()
    wrapper.train()
    wrapper.functional_reader.eval()
    next(wrapper.base_model.parameters()).requires_grad_(False)
    with torch.no_grad():
        wrapper.functional_sidecar_adapter.up.weight.fill_(0.003)
    before = {name: value.clone() for name, value in wrapper.state_dict().items()}
    training = {name: module.training for name, module in wrapper.named_modules()}
    flags = {name: p.requires_grad for name, p in wrapper.named_parameters()}
    report = run(wrapper, batch)
    assert report["status"] == "COMPLETE", report.get("error", report["checks"])
    assert report["probe"]["original_up_was_zero"] is False
    assert {name: p.requires_grad for name, p in wrapper.named_parameters()} == flags
    assert {name: module.training for name, module in wrapper.named_modules()} == training
    assert_clean(wrapper, before)


def test_wrong_twin_assignment_is_reported_as_mismatch(monkeypatch):
    wrapper, batch = fixture()
    original = wrapper._intervene_memory

    def wrong_twin(*args, mode, seed):
        return original(*args, mode="intact" if mode == "counterfactual_twin" else mode, seed=seed)

    monkeypatch.setattr(wrapper, "_intervene_memory", wrong_twin)
    report = run(wrapper, batch)
    assert report["status"] == "MISMATCH"
    assert report["checks"]["opened_counterfactual_twin.memory_assignment"] is False
    assert report["restoration"]["workspace_state_bytes_restored"]


def test_opened_forward_exception_restores_temporary_probe_and_hooks(monkeypatch):
    wrapper, batch = fixture()
    before = {name: value.clone() for name, value in wrapper.state_dict().items()}
    adapter = wrapper.functional_sidecar_adapter
    original = adapter.forward

    def broken(value):
        if bool(adapter.up.weight.detach().ne(0).any()):
            raise RuntimeError("injected opened-head failure")
        return original(value)

    monkeypatch.setattr(adapter, "forward", broken)
    report = run(wrapper, batch)
    assert report["status"] == "FAILED"
    assert "injected opened-head failure" in report["error"]
    assert report["checks"]["restoration"]
    assert_clean(wrapper, before)


def test_injected_sidecar_gradient_leak_to_base_is_detected(monkeypatch):
    wrapper, batch = fixture()
    adapter = wrapper.functional_sidecar_adapter
    original = adapter.forward
    base_parameter = next(wrapper.base_model.parameters())

    def leaking(value):
        result = original(value)
        if torch.is_grad_enabled() and bool(adapter.up.weight.detach().ne(0).any()):
            result = result + base_parameter.flatten()[0]
        return result

    monkeypatch.setattr(adapter, "forward", leaking)
    report = run(wrapper, batch)
    assert report["status"] == "MISMATCH"
    assert report["checks"]["opened.ownership"] is False
    assert report["gradients"]["opened"]["groups"]["base"]["present"] > 0
    assert report["checks"]["restoration"]


def test_unsupported_norm_observation_cannot_pass(monkeypatch):
    class Unsupported(instrument.NamedNormRecorder):
        def _snapshot(self, value):
            return {"status": "UNSUPPORTED", "reason": "injected unsupported output"}

    wrapper, batch = fixture()
    monkeypatch.setattr(instrument, "NamedNormRecorder", Unsupported)
    report = run(wrapper, batch)
    assert report["status"] == "MISMATCH"
    assert report["checks"]["observer.records"] is False
    assert report["checks"]["observer.passthrough"] is True


def test_batch_bound_violation_fails_before_any_forward():
    wrapper, batch = fixture()
    batch["functional_inline_input_ids"] = torch.ones(1, 2, 2, 257, dtype=torch.long)
    report = run(wrapper, batch)
    assert report["status"] == "FAILED"
    assert report["cases"] == {}
    assert "bounded" in report["error"]
    assert report["checks"]["restoration"]
