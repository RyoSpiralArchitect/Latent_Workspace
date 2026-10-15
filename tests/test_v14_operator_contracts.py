from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest
import torch
from torch import nn
from transformers import MistralConfig, MistralForCausalLM

from latent_workspace_ft_v10.engine import (
    ExperimentConfig,
    LatentWorkspaceCausalLM,
    generate_text,
    resume_signature,
    runtime_environment,
)
from latent_workspace_ft_v10.implementation_identity import implementation_fingerprint
from latent_workspace_ft_v10.normalization import (
    NormalizationSpec,
    describe_normalizer,
    inventory_normalizers,
)
from latent_workspace_ft_v10.numerics import NumericsPolicy
from latent_workspace_ft_v10.workspace_core import FunctionalMemoryReader, ReaderState


def test_ln_and_rms_are_distinct_declared_algorithms() -> None:
    x = torch.tensor([[1.0, 2.0, 5.0]])
    ln = NormalizationSpec().build(3)
    rms = NormalizationSpec("rms_norm").build(3)
    torch.testing.assert_close(ln(x), ln(x + 10.0), rtol=0, atol=2e-6)
    assert not torch.allclose(rms(x), rms(x + 10.0))
    assert NormalizationSpec().fingerprint()["centers"]
    assert not NormalizationSpec("rms_norm").fingerprint()["centers"]
    assert set(ln.state_dict()) == {"weight", "bias"}
    assert set(rms.state_dict()) == {"weight"}


@pytest.mark.parametrize(
    "kind,eps",
    [("unknown", 1e-5), ("layer_norm", 0), ("rms_norm", float("nan")), ("rms_norm", True)],
)
def test_invalid_norm_contract_fails(kind, eps) -> None:
    with pytest.raises(ValueError):
        NormalizationSpec(kind, eps)


def test_native_norm_inventory_includes_backbone_and_preserves_state() -> None:
    cfg = MistralConfig(
        hidden_size=16,
        intermediate_size=32,
        num_hidden_layers=1,
        num_attention_heads=2,
        num_key_value_heads=1,
        vocab_size=23,
    )
    model = nn.Module()
    model.base_model = MistralForCausalLM(cfg)
    model.functional_norm = nn.LayerNorm(16)
    before = {k: v.clone() for k, v in model.state_dict().items()}
    report = inventory_normalizers(model)
    assert any(v["owner"] == "base_model" and v["kind"] == "rms_norm" for v in report.values())
    assert report["functional_norm"]["kind"] == "layer_norm"
    json.dumps(report, allow_nan=False)
    for key, value in model.state_dict().items():
        assert torch.equal(before[key], value)


def test_unrecognized_norm_is_unknown_not_layernorm() -> None:
    class ExoticNorm(nn.Module):
        def forward(self, x):
            return x

    report = describe_normalizer(ExoticNorm())
    assert report["status"] == "UNSUPPORTED_UNKNOWN"
    assert report["centers"] is None


def test_reader_separates_each_update_from_recovered_delta() -> None:
    torch.manual_seed(41)
    reader = FunctionalMemoryReader(
        8,
        8,
        heads=2,
        steps=2,
        dropout=0,
        injection_scale=1,
        gate_init_bias=-2,
        zero_initialize_output=False,
    )
    q, m = torch.randn(2, 3, 8), torch.randn(2, 4, 8)
    qm, mm = torch.ones(2, 3, dtype=torch.long), torch.ones(2, 4, dtype=torch.long)
    result = reader.read_state(q, qm, m, mm)
    assert isinstance(result, ReaderState)
    assert len(result.per_step_updates) == 2
    torch.testing.assert_close(result.recovered_delta, result.final_state - q, rtol=0, atol=0)
    torch.testing.assert_close(
        result.cumulative_update,
        result.per_step_updates[0] + result.per_step_updates[1],
        rtol=0,
        atol=0,
    )
    assert not torch.equal(result.cumulative_update, result.per_step_updates[-1])
    torch.testing.assert_close(reader(q, qm, m, mm)[0], result.final_state, rtol=0, atol=0)


def test_config_serializes_operator_and_numerics_choices() -> None:
    cfg = ExperimentConfig()
    cfg.functional.enabled = True
    cfg.functional.route_mode = "inline_sidecar"
    cfg.workspace.route_topology = "functional_workspace"
    old = resume_signature(cfg)
    cfg.functional.logit_composition = "fp32_accumulate"
    cfg.functional.workspace_norm_kind = "rms_norm"
    assert resume_signature(cfg) != old
    restored = ExperimentConfig.from_dict(dataclasses.asdict(cfg))
    assert restored.functional.logit_composition == "fp32_accumulate"
    assert restored.functional.workspace_norm_kind == "rms_norm"


def test_numerics_profile_cannot_be_silently_ignored_by_other_routes() -> None:
    cfg = ExperimentConfig()
    cfg.functional.logit_composition = "fp32_accumulate"
    with pytest.raises(ValueError, match="inline_sidecar"):
        cfg.validate()


def test_implementation_digest_covers_sibling_modules(tmp_path) -> None:
    (tmp_path / "engine.py").write_text("engine")
    (tmp_path / "numerics.py").write_text("legacy")
    first = implementation_fingerprint(tmp_path)
    (tmp_path / "numerics.py").write_text("fp32")
    second = implementation_fingerprint(tmp_path)
    assert first["files"]["engine.py"] == second["files"]["engine.py"]
    assert first["sha256"] != second["sha256"]
    assert implementation_fingerprint()["files"]["workspace_core.py"]


def test_functional_free_generation_is_explicitly_unsupported() -> None:
    class Model:
        functional_config = type("Config", (), {"enabled": True})()

    with pytest.raises(ValueError, match="context/query"):
        generate_text(Model(), None, "prompt", device=torch.device("cpu"))


def _sidecar_with_profile(profile):
    from test_engine_mistral import tiny_inline_sidecar_model

    template = tiny_inline_sidecar_model()
    functional = dataclasses.replace(
        template.functional_config,
        logit_composition=profile,
        counterfactual_weight=0.3,
        stability_weight=0.2,
    )
    model = LatentWorkspaceCausalLM(
        template.base_model,
        template.hidden_dim,
        template.vocab_size,
        template.workspace_config,
        functional_config=functional,
    ).eval()
    with torch.no_grad():
        model.functional_sidecar_adapter.up.weight.normal_(std=0.001)
    return model.to(torch.bfloat16)


@pytest.mark.parametrize("profile", ["legacy_native", "fp32_accumulate"])
def test_main_and_counterfactual_use_same_profile_without_changing_detach(monkeypatch, profile):
    from test_engine_mistral import tiny_functional_sidecar_kwargs

    model = _sidecar_with_profile(profile)
    calls = []
    original = NumericsPolicy.compose_logits

    def observed(self, base, residual, **kwargs):
        result = original(self, base, residual, **kwargs)
        calls.append((self.profile, base.requires_grad, base.dtype, result.dtype))
        expected = (
            base + residual.to(base.dtype)
            if profile == "legacy_native"
            else base.float() + residual.float()
        )
        assert torch.equal(result, expected)
        return result

    monkeypatch.setattr(NumericsPolicy, "compose_logits", observed)
    result = model._forward_functional_workspace(
        **tiny_functional_sidecar_kwargs(), bypass_workspace=False
    )
    output_dtype = torch.bfloat16 if profile == "legacy_native" else torch.float32
    assert calls == [
        (profile, True, torch.bfloat16, output_dtype),
        (profile, False, torch.bfloat16, output_dtype),
    ]
    assert result["logits"].dtype == output_dtype
    result["task_loss"].backward()
    grad = model.functional_sidecar_adapter.up.weight.grad
    assert grad is not None and bool(torch.isfinite(grad).all())
    assert torch.count_nonzero(grad) > 0


@pytest.mark.parametrize("profile", ["legacy_native", "fp32_accumulate"])
def test_wrapper_true_bypass_skips_reader_adapter_and_numerics(monkeypatch, profile):
    from test_engine_mistral import tiny_functional_sidecar_kwargs

    model = _sidecar_with_profile(profile)
    native_outputs = []

    def forbidden(*args, **kwargs):
        raise AssertionError("True bypass must not evaluate a workspace route or composition")

    monkeypatch.setattr(model.functional_writer, "forward", forbidden)
    monkeypatch.setattr(model.functional_reader, "forward", forbidden)
    monkeypatch.setattr(model.functional_sidecar_adapter, "forward", forbidden)
    monkeypatch.setattr(NumericsPolicy, "compose_logits", forbidden)
    handle = model.base_model.register_forward_hook(
        lambda _module, _args, output: native_outputs.append(output.logits)
    )
    try:
        with torch.no_grad():
            result = model._forward_functional_workspace(
                **tiny_functional_sidecar_kwargs(), bypass_workspace=True
            )
    finally:
        handle.remove()
    assert len(native_outputs) == 1
    assert result["logits"] is native_outputs[0]
    assert result["logits"].dtype == torch.bfloat16


@pytest.mark.parametrize(
    "field,value",
    [
        ("workspace_norm_kind", "rms_norm"),
        ("workspace_norm_eps", 1e-3),
        ("logit_composition", "fp32_accumulate"),
    ],
)
def test_mutating_operator_config_cannot_relabel_resolved_modules(field, value):
    from test_engine_mistral import tiny_functional_sidecar_kwargs

    model = _sidecar_with_profile("legacy_native")
    model.functional_operator_contract()
    setattr(model.functional_config, field, value)
    with pytest.raises(RuntimeError, match="rebuild the model"):
        model.functional_operator_contract()
    with pytest.raises(RuntimeError, match="rebuild the model"):
        model._forward_functional_workspace(
            **tiny_functional_sidecar_kwargs(), bypass_workspace=False
        )


def test_runtime_names_the_whole_package_hash_scope():
    report = runtime_environment()
    assert report["source_sha256"] == report["implementation_identity"]["sha256"]
    assert report["implementation_identity"]["files"]["model_binding.py"]


def test_source_manifest_matches_engine_and_all_extracted_modules():
    package = Path(__file__).resolve().parents[1] / "src/latent_workspace_ft_v10"
    manifest = json.loads((package / "source_manifest.json").read_text())
    payload = (package / "engine.py").read_bytes()
    assert manifest["package_version"] == "14.0.0"
    assert manifest["patched_engine"]["sha256"] == hashlib.sha256(payload).hexdigest()
    assert manifest["patched_engine"]["line_count"] == len(payload.splitlines())
    assert manifest["implementation_identity"] == implementation_fingerprint()
