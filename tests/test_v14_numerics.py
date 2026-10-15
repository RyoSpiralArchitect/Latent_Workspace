from __future__ import annotations

import dataclasses
import json

import pytest
import torch

from latent_workspace_ft_v10.numerics import NumericsPolicy, compose_logits


@pytest.mark.parametrize("profile", ["legacy_native", "fp32_accumulate"])
@pytest.mark.parametrize(
    "base_dtype", [torch.float16, torch.bfloat16, torch.float32, torch.float64]
)
@pytest.mark.parametrize("residual_dtype", [torch.bfloat16, torch.float32, torch.float64])
def test_outputs_and_gradients_match_direct_formula(
    profile: str, base_dtype: torch.dtype, residual_dtype: torch.dtype
) -> None:
    base = torch.tensor([[2.0, -3.0], [1.0, 4.0]], dtype=base_dtype, requires_grad=True)
    residual = torch.tensor([[0.01, 0.2], [-0.25, 0.03]], dtype=residual_dtype, requires_grad=True)
    reference_base = base.detach().clone().requires_grad_()
    reference_residual = residual.detach().clone().requires_grad_()
    before_base, before_residual = base.detach().clone(), residual.detach().clone()
    actual = compose_logits(base, residual, policy=NumericsPolicy(profile))
    expected = (
        reference_base + reference_residual.to(reference_base.dtype)
        if profile == "legacy_native"
        else reference_base.float() + reference_residual.float()
    )
    assert torch.equal(actual, expected)
    assert actual.dtype == (base_dtype if profile == "legacy_native" else torch.float32)
    weights = torch.tensor([[0.5, -1.0], [2.0, 0.25]], dtype=actual.dtype)
    (actual * weights).sum().backward()
    (expected * weights).sum().backward()
    assert torch.equal(base.grad, reference_base.grad)
    assert torch.equal(residual.grad, reference_residual.grad)
    assert torch.equal(base.detach(), before_base)
    assert torch.equal(residual.detach(), before_residual)


def test_bf16_absorption_is_visible_in_fp32_accumulation() -> None:
    base = torch.tensor([[20.0, 19.0]], dtype=torch.bfloat16)
    residual = torch.tensor([[0.01, -0.01]], dtype=torch.bfloat16, requires_grad=True)
    native = compose_logits(base, residual)
    promoted = NumericsPolicy("fp32_accumulate").compose_logits(base, residual)
    assert torch.count_nonzero(residual) == 2
    assert torch.equal(native, base)
    assert not torch.equal(promoted, base.float())
    assert torch.equal(promoted, base.float() + residual.float())
    promoted.sum().backward()
    assert torch.equal(residual.grad, torch.ones_like(residual))


@pytest.mark.parametrize("profile", ["legacy_native", "fp32_accumulate"])
def test_composition_under_cpu_autocast_matches_explicit_formula(profile: str) -> None:
    base = torch.tensor([[20.0, 19.0]], dtype=torch.bfloat16, requires_grad=True)
    residual = torch.tensor([[0.01, -0.01]], dtype=torch.float32, requires_grad=True)
    with torch.autocast("cpu", dtype=torch.bfloat16):
        actual = compose_logits(base, residual, policy=NumericsPolicy(profile))
        expected = (
            base + residual.to(base.dtype)
            if profile == "legacy_native"
            else base.float() + residual.float()
        )
    assert torch.equal(actual, expected)
    assert actual.dtype == (torch.bfloat16 if profile == "legacy_native" else torch.float32)
    actual.sum().backward()
    assert base.grad is not None and residual.grad is not None


@pytest.mark.parametrize("profile", ["legacy_native", "fp32_accumulate"])
def test_true_bypass_returns_exact_base_object_dtype_and_gradient(profile: str) -> None:
    base = torch.tensor([1.0, 2.0], dtype=torch.bfloat16, requires_grad=True)
    policy = NumericsPolicy(profile)
    assert policy.compose_logits(base, None, true_bypass=True) is base
    unused_residual = torch.ones(3, dtype=torch.float32, requires_grad=True)
    output = compose_logits(base, unused_residual, policy=policy, true_bypass=True)
    assert output is base
    assert output.dtype == torch.bfloat16
    output.sum().backward()
    assert torch.equal(base.grad, torch.ones_like(base))
    assert unused_residual.grad is None


@pytest.mark.parametrize("profile", ["", "fp32", "bf16", None, True, 1])
def test_invalid_profile_rejected(profile: object) -> None:
    with pytest.raises(ValueError, match="Numerics profile"):
        NumericsPolicy(profile)


def test_policy_is_immutable_and_fingerprint_is_json_serializable() -> None:
    legacy = NumericsPolicy()
    promoted = NumericsPolicy("fp32_accumulate")
    with pytest.raises(dataclasses.FrozenInstanceError):
        legacy.profile = "fp32_accumulate"
    assert json.loads(json.dumps(legacy.fingerprint())) == legacy.fingerprint()
    assert legacy.fingerprint() != promoted.fingerprint()
    assert legacy.fingerprint()["output_dtype"] == "base.dtype"
    assert promoted.fingerprint()["output_dtype"] == "torch.float32"
    assert promoted.fingerprint()["whole_forward_fp32"] is False
    detached_fingerprint = promoted.fingerprint()
    detached_fingerprint["profile"] = "mutated"
    assert promoted.profile == "fp32_accumulate"


@pytest.mark.parametrize("profile", ["legacy_native", "fp32_accumulate"])
def test_broadcastable_but_different_shapes_rejected(profile: str) -> None:
    with pytest.raises(ValueError, match="identical shapes"):
        compose_logits(torch.ones(2, 3), torch.ones(3), policy=NumericsPolicy(profile))


@pytest.mark.parametrize("profile", ["legacy_native", "fp32_accumulate"])
def test_device_mismatch_rejected_before_arithmetic(profile: str) -> None:
    with pytest.raises(ValueError, match="same device"):
        compose_logits(torch.ones(2), torch.ones(2, device="meta"), policy=NumericsPolicy(profile))


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [1.0, 2.0],
        torch.ones(2, dtype=torch.int64),
        torch.ones(2, dtype=torch.bool),
        torch.ones(2, dtype=torch.complex64),
    ],
)
@pytest.mark.parametrize("side", ["base", "residual"])
def test_nonfloating_or_nontensor_values_rejected(bad: object, side: str) -> None:
    values = {"base": torch.ones(2), "residual": torch.ones(2)}
    values[side] = bad
    with pytest.raises(ValueError, match=f"{side} must be a floating-point tensor"):
        compose_logits(**values)


def test_true_bypass_still_requires_valid_base_and_boolean_flag() -> None:
    with pytest.raises(ValueError, match="base must be a floating-point tensor"):
        compose_logits(torch.ones(2, dtype=torch.int64), None, true_bypass=True)
    with pytest.raises(ValueError, match="true_bypass must be a boolean"):
        compose_logits(torch.ones(2), torch.ones(2), true_bypass="false")


def test_helper_requires_explicit_policy_object_not_string_profile() -> None:
    with pytest.raises(ValueError, match="policy must be a NumericsPolicy"):
        compose_logits(torch.ones(2), torch.ones(2), policy="fp32_accumulate")
