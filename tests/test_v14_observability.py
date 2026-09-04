"""Tiny CPU tests of observation passthrough and bounded accounting."""

import copy
import hashlib
import json

import pytest
import torch
from torch import nn

from latent_workspace_ft_v10.observability import NamedNormRecorder


@pytest.fixture(autouse=True)
def bounded_cpu_threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(previous)


@pytest.mark.parametrize("norm_type", [nn.LayerNorm, nn.RMSNorm])
def test_exact_output_and_gradient_passthrough(norm_type) -> None:
    torch.manual_seed(271)
    native = norm_type(4)
    observed = copy.deepcopy(native)
    x = torch.randn(2, 3, 4, requires_grad=True)
    y = x.detach().clone().requires_grad_(True)
    expected = native(x)
    expected.square().sum().backward()
    with NamedNormRecorder({"explicit.norm": observed}) as recorder:
        actual = observed(input=y) if norm_type is nn.LayerNorm else observed(y)
        actual.square().sum().backward()
    assert torch.equal(actual, expected)
    assert torch.equal(x.grad, y.grad)
    for expected_parameter, actual_parameter in zip(
        native.parameters(), observed.parameters(), strict=True
    ):
        assert torch.equal(expected_parameter.grad, actual_parameter.grad)
    report = recorder.to_dict()
    assert report["counts"] == {"explicit.norm": {"invoked": 1, "recorded": 1, "dropped": 0}}
    record = report["records"][0]
    assert record["status"] == "COMPLETE"
    assert record["pre"]["shape"] == [2, 3, 4]
    assert record["post"]["dtype"] == "torch.float32"
    assert record["pre"]["hash_scope"] == "full_tensor"
    assert not observed._forward_hooks and not observed._forward_pre_hooks
    json.dumps(report, allow_nan=False)


def test_record_and_element_caps_are_explicit_and_hash_only_sample() -> None:
    norm = nn.LayerNorm(4)
    x = torch.arange(8, dtype=torch.bfloat16).reshape(2, 4)
    with NamedNormRecorder(
        {"workspace.norm": norm}, max_records=2, max_tensor_elements=3
    ) as recorder:
        for _ in range(5):
            norm(x)
    report = recorder.to_dict()
    assert report["counts"]["workspace.norm"] == {"invoked": 5, "recorded": 2, "dropped": 3}
    assert len(report["records"]) == 2
    summary = report["records"][0]["pre"]
    assert summary["sampled_elements"] == 3 and summary["omitted_elements"] == 5
    assert summary["hash_scope"] == "flat_prefix"
    assert (
        summary["sha256"]
        == hashlib.sha256(x.flatten()[:3].view(torch.uint8).numpy().tobytes()).hexdigest()
    )


def test_zero_record_cap_still_counts_every_named_call() -> None:
    first, second = nn.LayerNorm(4), nn.RMSNorm(4)
    with NamedNormRecorder({"a": first, "b": second}, max_records=0) as recorder:
        second(first(torch.randn(2, 4)))
    assert recorder.records == []
    assert recorder.counts == {
        name: {"invoked": 1, "recorded": 0, "dropped": 1} for name in ("a", "b")
    }


def test_nested_rejection_preserves_outer_and_reentry_resets() -> None:
    norm = nn.LayerNorm(4)
    recorder = NamedNormRecorder({"norm": norm})
    with recorder:
        with pytest.raises(RuntimeError, match="Nested"):
            with recorder:
                pass
        norm(torch.randn(2, 4))
    assert recorder.counts["norm"]["invoked"] == 1
    with recorder:
        pass
    assert recorder.counts["norm"]["invoked"] == 0
    assert recorder.records == []


class UnknownOutput(nn.Module):
    def __init__(self, mode):
        super().__init__()
        self.mode = mode

    def forward(self, value):
        if self.mode == "raise":
            raise RuntimeError("forward failed")
        if self.mode == "tuple":
            return (value,)
        return value[:, :1]


@pytest.mark.parametrize("mode", ["tuple", "shape"])
def test_unsupported_output_is_not_zero_or_replaced(mode) -> None:
    norm = UnknownOutput(mode)
    value = torch.randn(2, 4)
    with NamedNormRecorder({"unknown": norm}) as recorder:
        output = norm(value)
    assert recorder.records[0]["status"] == "UNSUPPORTED"
    if mode == "tuple":
        assert output[0] is value
        assert recorder.records[0]["post"]["status"] == "UNSUPPORTED"
    else:
        assert torch.equal(output, value[:, :1])
        assert recorder.records[0]["reason"] == "normalization_input_output_shape_mismatch"


def test_forward_exception_cleans_hooks_and_preserves_interrupted_record() -> None:
    module = UnknownOutput("raise")
    recorder = NamedNormRecorder({"raises": module})
    with pytest.raises(RuntimeError, match="forward failed"):
        with recorder:
            module(torch.randn(2, 4))
    assert not module._forward_hooks and not module._forward_pre_hooks
    assert recorder.records[0]["status"] == "INTERRUPTED"
    assert recorder.records[0]["post"] is None
    assert not recorder.to_dict()["active"]


def test_context_body_exception_also_cleans_hooks() -> None:
    module = nn.LayerNorm(4)
    with pytest.raises(ValueError, match="body failed"):
        with NamedNormRecorder({"norm": module}):
            raise ValueError("body failed")
    assert not module._forward_hooks and not module._forward_pre_hooks


def test_constructor_rejects_invalid_caps_and_duplicate_modules() -> None:
    module = nn.LayerNorm(4)
    with pytest.raises(ValueError):
        NamedNormRecorder({"norm": module}, max_records=-1)
    with pytest.raises(ValueError):
        NamedNormRecorder({"norm": module}, max_tensor_elements=0)
    with pytest.raises(ValueError, match="exactly one"):
        NamedNormRecorder({"first": module, "alias": module})
    with pytest.raises(TypeError):
        NamedNormRecorder({"norm": object()})


def test_meta_tensor_is_unsupported_without_changing_forward() -> None:
    module = nn.Identity()
    value = torch.empty(2, 4, device="meta")
    with NamedNormRecorder({"unmaterialized": module}) as recorder:
        actual = module(value)
    assert actual is value
    assert recorder.records[0]["status"] == "UNSUPPORTED"
