"""Engineering fixtures only: no optimizer steps, study populations or fitting."""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest
import torch
from torch.nn import functional as F

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import assay_v18_operand_selection as assay  # noqa: E402
import v18_controlled_writer as writer  # noqa: E402


@pytest.fixture(autouse=True)
def threads():
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


def fixture_inputs():
    # Previously used analytic witness, explicitly not a future study split.
    pop = assay.population(9109, 1)
    data = pop.inputs
    return writer.WriterInputs(data.states, data.memory, data.mask), pop.labels


def nonzero_reader(factor="centered_ordered"):
    bridge = writer.make_writer_reader(17, factor)
    with torch.no_grad():
        bridge.up.weight.normal_(std=0.1)
    return bridge


@pytest.mark.parametrize("factor", assay.FACTORS)
def test_matching_initial_state_rng_and_explicit_parameter_partition(factor):
    original = assay.make_reader(17, factor)
    rng = torch.get_rng_state()
    candidate = writer.make_writer_reader(17, factor)
    assert torch.equal(rng, torch.get_rng_state())
    assert all(
        torch.equal(value, candidate.state_dict()[name])
        for name, value in original.state_dict().items()
    )
    manifest = writer.partition_manifest(candidate)
    assert manifest["trainable_parameter_tensors"] == 26
    assert manifest["trainable_parameter_elements"] == 20160
    assert manifest["frozen_parameter_tensors"] == 6
    assert manifest["frozen_parameter_elements"] == 6208
    assert manifest["checkpoint_qualification"] == "NOT_ADMITTED_BY_V18_OWNER"
    assert {name: len(values) for name, values in manifest["partitions"].items()} == {
        "writer": 20, "common_reader": 6, "interaction": 6,
    }


def test_container_has_no_label_or_side_metadata_and_field_bindings_are_frozen():
    inputs, _ = fixture_inputs()
    assert [field.name for field in dataclasses.fields(inputs)] == [
        "states", "context", "context_mask",
    ]
    with pytest.raises(dataclasses.FrozenInstanceError):
        inputs.context = inputs.context.clone()
    with pytest.raises(TypeError):
        writer.WriterInputs(inputs.states, inputs.context, inputs.context_mask, labels=0)
    taken = inputs.take(torch.tensor([1, 2])).to("cpu")
    assert torch.equal(taken.context, inputs.context[[1, 2]])


def test_writer_receives_facts_only_and_actual_output_mask_is_used(monkeypatch):
    inputs, _ = fixture_inputs()
    bridge = writer.make_writer_reader(17, "centered_ordered")
    seen = []
    original = bridge.write_memory

    def record(*args, **kwargs):
        seen.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(bridge, "write_memory", record)
    padded = writer.WriterInputs(
        inputs.states,
        torch.cat((inputs.context, torch.full_like(inputs.context[:, :1], 17)), 1),
        torch.cat((inputs.context_mask, torch.zeros_like(inputs.context_mask[:, :1])), 1),
    )
    written = writer.write_inputs(bridge, padded)
    assert len(seen) == 1 and seen[0][1] == {}
    assert len(seen[0][0]) == 2
    assert seen[0][0][0] is padded.context and seen[0][0][1] is padded.context_mask
    assert written.mask.shape == (36, 3) and written.mask.eq(1).all()
    assert written.states is inputs.states


def test_six_questions_of_same_world_write_identical_memory():
    inputs, _ = fixture_inputs()
    bridge = nonzero_reader()
    written = writer.write_inputs(bridge, inputs)
    for begin in range(0, len(inputs.states), 6):
        assert torch.equal(
            written.memory[begin:begin + 6], written.memory[begin:begin + 1].expand(6, -1, -1)
        )
    changed_question = writer.WriterInputs(
        inputs.states.flip(0), inputs.context, inputs.context_mask
    )
    other = writer.write_inputs(bridge, changed_question)
    assert torch.equal(written.memory, other.memory)


@pytest.mark.parametrize("factor", assay.FACTORS)
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_actual_writer_then_unchanged_complete_head_with_exact_zero_common(factor, dtype):
    inputs, _ = fixture_inputs()
    bridge = nonzero_reader(factor)
    written = writer.write_inputs(bridge, inputs)
    expected = assay.forward(bridge, written, factor, native_dtype=dtype)
    actual = writer.writer_forward(bridge, inputs, factor, native_dtype=dtype)
    assert all(torch.equal(a, b) for a, b in zip(actual, expected, strict=True))
    assert actual[0].shape == (36, 7)
    parts = bridge.parts(
        inputs.states[:, -1:], assay.query(inputs.states, factor), written.memory, written.mask
    )
    assert parts["common"].eq(0).all()
    assert parts["delta"].norm(dim=-1).max() <= 0.25 + 1e-6


@pytest.mark.parametrize("factor", assay.FACTORS)
def test_zero_equal_interventions_are_after_writing_not_context(factor):
    inputs, _ = fixture_inputs()
    bridge = nonzero_reader(factor)
    written = writer.write_inputs(bridge, inputs)
    zero = assay.Inputs(written.states, torch.zeros_like(written.memory), written.mask)
    equal = assay.Inputs(
        written.states, written.memory[:, :1].expand_as(written.memory).clone(), written.mask
    )
    assert assay.forward(bridge, zero, factor)[1].eq(0).all()
    if factor != "raw_ordered":
        assert assay.forward(bridge, equal, factor)[1].eq(0).all()
    zero_context = writer.WriterInputs(
        inputs.states, torch.zeros_like(inputs.context), inputs.context_mask
    )
    assert writer.write_inputs(bridge, zero_context).memory.count_nonzero() > 0


@pytest.mark.parametrize("factor", assay.FACTORS)
@pytest.mark.parametrize("open_output", [False, True])
def test_physical_finite_gradients_owned_but_initial_upstream_zero_is_valid(factor, open_output):
    inputs, labels = fixture_inputs()
    bridge = nonzero_reader(factor) if open_output else writer.make_writer_reader(17, factor)
    before = {name: value.clone() for name, value in bridge.state_dict().items()}
    logits, delta = writer.writer_forward(bridge, inputs, factor)
    loss = F.cross_entropy(logits, labels) + 0.001 * delta.square().sum(-1).mean()
    loss.backward()
    for name, parameter in bridge.named_parameters():
        if parameter.requires_grad:
            assert parameter.grad is not None, name
            assert torch.isfinite(parameter.grad).all(), name
            if not open_output and name != "up.weight":
                assert parameter.grad.eq(0).all(), name
        else:
            assert parameter.grad is None, name
        # Backward is not a parameter update or an optimizer step.
        assert torch.equal(parameter, before[name]), name


def test_masked_context_content_is_ignored_without_claiming_permutation_exactness():
    inputs, _ = fixture_inputs()
    bridge = nonzero_reader()
    mask = torch.cat((inputs.context_mask, torch.zeros_like(inputs.context_mask[:, :1])), 1)
    a = writer.WriterInputs(
        inputs.states, torch.cat((inputs.context, torch.zeros_like(inputs.context[:, :1])), 1), mask
    )
    b = writer.WriterInputs(
        inputs.states, torch.cat((inputs.context, torch.full_like(inputs.context[:, :1], 999)), 1),
        mask,
    )
    assert torch.equal(writer.write_inputs(bridge, a).memory, writer.write_inputs(bridge, b).memory)


@pytest.mark.parametrize("kind", ["all_masked", "nonbinary", "nonfinite", "dtype", "geometry"])
def test_invalid_inputs_and_mutated_caller_tensors_are_rejected(kind):
    inputs, _ = fixture_inputs()
    if kind == "all_masked":
        inputs.context_mask[0].zero_()
    elif kind == "nonbinary":
        inputs.context_mask[0, 0] = 2
    elif kind == "nonfinite":
        inputs.context[0, 0, 0] = float("nan")
    elif kind == "dtype":
        with pytest.raises(ValueError, match="FP32"):
            writer.WriterInputs(inputs.states.half(), inputs.context, inputs.context_mask)
        return
    else:
        with pytest.raises(ValueError, match="controlled"):
            writer.WriterInputs(inputs.states[:, :2], inputs.context, inputs.context_mask)
        return
    with pytest.raises(ValueError):
        writer.write_inputs(writer.make_writer_reader(17, "centered_ordered"), inputs)


@pytest.mark.parametrize("mutation", ["freeze_writer", "unfreeze_common", "nonzero_common"])
def test_partition_or_common_zero_mutations_are_rejected(mutation):
    bridge = writer.make_writer_reader(17, "centered_ordered")
    if mutation == "freeze_writer":
        bridge.common.writer.requires_grad_(False)
    elif mutation == "unfreeze_common":
        bridge.common.up.requires_grad_(True)
    else:
        with torch.no_grad():
            bridge.common.up.weight.fill_(1)
    with pytest.raises(ValueError):
        writer.partition_manifest(bridge)


@pytest.mark.parametrize("common_only", [False, True])
@pytest.mark.parametrize(
    "factory_factor,forward_factor",
    [
        ("raw_ordered", "centered_ordered"),
        ("centered_final", "raw_ordered"),
        ("centered_ordered", "unknown"),
    ],
)
def test_forward_rejects_unknown_or_mismatched_factor_before_writer(
    factory_factor, forward_factor, common_only, monkeypatch
):
    inputs, _ = fixture_inputs()
    bridge = writer.make_writer_reader(17, factory_factor)
    monkeypatch.setattr(
        bridge, "write_memory", lambda *_args: pytest.fail("Invalid factor reached writer")
    )
    with pytest.raises(ValueError, match="factor"):
        writer.writer_forward(bridge, inputs, forward_factor, common_only=common_only)
