"""Exact legacy-default parity against a sealed Git blob, never current-source fallback.

These tiny CPU tests certify bounded numerical compatibility, not model capability.
The reference engine is compiled in memory; no historical engine file is copied.
"""

from __future__ import annotations

import dataclasses
import subprocess
import sys
import types
from pathlib import Path

import pytest
import torch
from torch import nn

from latent_workspace_ft_v10 import engine, workspace_core

REFERENCE_COMMIT = "ed5ce398e08b55d3118a316cfda61e36b8cc4b54"
ENGINE_PATH = "src/latent_workspace_ft_v10/engine.py"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module", autouse=True)
def bounded_cpu_threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    with torch.random.fork_rng(devices=[]):
        yield
    torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def legacy():
    try:
        result = subprocess.run(
            ["git", "show", f"{REFERENCE_COMMIT}:{ENGINE_PATH}"],
            cwd=ROOT,
            capture_output=True,
            check=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"Sealed legacy Git reference unavailable: {REFERENCE_COMMIT}: {exc}")
    name = "_v14_sealed_legacy_engine_parity"
    module = types.ModuleType(name)
    module.__file__ = f"git:{REFERENCE_COMMIT}:{ENGINE_PATH}"
    sys.modules[name] = module  # Required by dataclass annotation processing.
    try:
        exec(compile(result.stdout, module.__file__, "exec"), module.__dict__)
        yield module
    finally:
        sys.modules.pop(name, None)


def _exact(actual, expected, label="value"):
    if isinstance(expected, torch.Tensor):
        assert isinstance(actual, torch.Tensor), label
        assert actual.dtype == expected.dtype, label
        assert actual.shape == expected.shape, label
        assert torch.equal(actual, expected), label
    elif isinstance(expected, dict):
        assert actual.keys() == expected.keys(), label
        for key in expected:
            _exact(actual[key], expected[key], f"{label}.{key}")
    elif isinstance(expected, (tuple, list)):
        assert len(actual) == len(expected), label
        for index, (left, right) in enumerate(zip(actual, expected, strict=True)):
            _exact(left, right, f"{label}[{index}]")
    else:
        assert actual == expected, label


def _pair(legacy, name, *args, **kwargs):
    torch.manual_seed(20260904)
    reference = getattr(legacy, name)(*args, **kwargs)
    reference_rng = torch.random.get_rng_state().clone()
    torch.manual_seed(20260904)
    candidate = getattr(workspace_core, name)(*args, **kwargs)
    _exact(torch.random.get_rng_state(), reference_rng, "initialization RNG")
    _exact(candidate.state_dict(), reference.state_dict(), "seeded state_dict")
    return reference, candidate


def _run(module, values, *, autocast):
    inputs = [x.detach().clone().requires_grad_(x.is_floating_point()) for x in values]
    calls = []
    handles = []
    for name, child in module.named_modules():
        if isinstance(child, (nn.LayerNorm, nn.MultiheadAttention)) or name == "gate":

            def capture(_module, args, name=name):
                calls.append((name, tuple(x.detach().clone() for x in args)))

            handles.append(child.register_forward_pre_hook(capture))
    try:
        torch.manual_seed(817)
        with torch.autocast("cpu", dtype=torch.bfloat16, enabled=autocast):
            output = module(*inputs)
            tensors = output if isinstance(output, tuple) else (output,)
            terms = []
            for tensor in tensors:
                if tensor.is_floating_point() and tensor.requires_grad:
                    weights = torch.linspace(0.1, 0.9, tensor.numel()).reshape(tensor.shape)
                    terms.append((tensor.float() * weights).mean() + tensor.float().square().mean())
            objective = sum(terms) if terms else None
        if objective is not None:
            objective.backward()
        return (
            output,
            [x.grad for x in inputs],
            {name: p.grad for name, p in module.named_parameters()},
            calls,
            torch.random.get_rng_state().clone(),
        )
    finally:
        for handle in handles:
            handle.remove()


def _compare_runs(reference, candidate, values, *, autocast):
    try:
        expected = _run(reference, values, autocast=autocast)
    except RuntimeError as exc:
        # Only an explicitly unavailable legacy CPU BF16 kernel permits a skip.
        unavailable = ("not implemented for 'BFloat16'", "not implemented for BFloat16")
        if autocast and any(marker in str(exc) for marker in unavailable):
            pytest.skip(f"Legacy CPU BF16 operation unavailable: {exc}")
        raise
    actual = _run(candidate, values, autocast=autocast)
    for label, left, right in zip(
        ("outputs", "input gradients", "parameter gradients", "norm/gate call trace", "RNG"),
        actual,
        expected,
        strict=True,
    ):
        _exact(left, right, label)
    _exact(candidate.state_dict(), reference.state_dict(), "post-forward state_dict")


def test_engine_reexports_extracted_legacy_classes():
    for name in (
        "FunctionalMemoryWriter",
        "FunctionalMemoryReader",
        "LowRankWorkspaceLogitAdapter",
    ):
        assert getattr(engine, name) is getattr(workspace_core, name)


@pytest.mark.parametrize("mode", ["raw_sequence", "projected_sequence", "fixed_carrier", "slots"])
@pytest.mark.parametrize("steps", [1, 2])
@pytest.mark.parametrize("autocast", [False, True], ids=["fp32", "bf16_cpu_autocast"])
def test_writer_defaults_match_sealed_initialization_outputs_and_all_gradients(
    legacy,
    mode,
    steps,
    autocast,
):
    reference, candidate = _pair(
        legacy,
        "FunctionalMemoryWriter",
        12,
        8,
        mode=mode,
        slot_count=3,
        steps=steps,
        heads=2,
        dropout=0.2,
    )
    values = [torch.randn(2, 5, 12), torch.tensor([[1, 1, 1, 0, 0], [1, 1, 1, 1, 0]])]
    _compare_runs(reference, candidate, values, autocast=autocast)


@pytest.mark.parametrize("steps", [1, 2])
@pytest.mark.parametrize("opened", [False, True], ids=["zero_initialized", "opened"])
@pytest.mark.parametrize("autocast", [False, True], ids=["fp32", "bf16_cpu_autocast"])
def test_reader_defaults_match_sealed_initialization_outputs_and_all_gradients(
    legacy,
    steps,
    opened,
    autocast,
):
    reference, candidate = _pair(
        legacy,
        "FunctionalMemoryReader",
        12,
        8,
        heads=2,
        steps=steps,
        dropout=0.2,
        injection_scale=0.7,
        gate_init_bias=-2.0,
    )
    assert torch.count_nonzero(candidate.attention.out_proj.weight) == 0
    assert torch.count_nonzero(candidate.gate.weight) == 0
    if opened:
        with torch.no_grad():
            reference.attention.out_proj.weight.normal_(std=0.07)
            reference.gate.weight.normal_(std=0.04)
        candidate.load_state_dict(reference.state_dict(), strict=True)
    values = [
        torch.randn(2, 4, 12),
        torch.tensor([[1, 1, 0, 0], [1, 1, 1, 0]]),
        torch.randn(2, 3, 8),
        torch.tensor([[1, 1, 0], [1, 1, 1]]),
    ]
    _compare_runs(reference, candidate, values, autocast=autocast)


@pytest.mark.parametrize("opened", [False, True], ids=["zero_initialized", "opened"])
@pytest.mark.parametrize("autocast", [False, True], ids=["fp32", "bf16_cpu_autocast"])
def test_logit_adapter_defaults_match_sealed_outputs_and_all_gradients(legacy, opened, autocast):
    reference, candidate = _pair(legacy, "LowRankWorkspaceLogitAdapter", 8, 19, 3)
    assert torch.count_nonzero(candidate.up.weight) == 0
    if opened:
        with torch.no_grad():
            reference.up.weight.normal_(std=0.03)
        candidate.load_state_dict(reference.state_dict(), strict=True)
    _compare_runs(reference, candidate, [torch.randn(2, 4, 8)], autocast=autocast)


def _tiny_wrapper(api, mode):
    from transformers import MistralConfig, MistralForCausalLM

    config = MistralConfig(
        vocab_size=41,
        hidden_size=16,
        intermediate_size=32,
        num_hidden_layers=2,
        num_attention_heads=4,
        num_key_value_heads=2,
        max_position_embeddings=32,
        attention_dropout=0.0,
        pad_token_id=0,
        bos_token_id=1,
        eos_token_id=2,
    )
    config._attn_implementation = "eager"
    base = MistralForCausalLM(config)
    workspace = api.WorkspaceConfig(
        steps=1,
        workspace_dim=8,
        ff_multiplier=1.0,
        architecture="token_local",
        attention_heads=2,
        bridge_heads=2,
        logit_rank=3,
        dropout=0.0,
        route_topology="functional_workspace",
    )
    functional = api.FunctionalWorkspaceConfig(
        enabled=True,
        route_mode=mode,
        boundary_layer=1,
        memory_mode="slots",
        slot_count=2,
        writer_steps=2,
        reader_steps=2,
        writer_heads=2,
        reader_heads=2,
        dropout=0.0,
        task_objective="choice_normalized",
        counterfactual_weight=0.3,
        stability_weight=0.2,
    )
    return api.LatentWorkspaceCausalLM(
        base,
        hidden_dim=16,
        vocab_size=41,
        config=workspace,
        functional_config=functional,
    ).train()


def _paired_batch():
    context = torch.tensor([[[1, 3, 4], [1, 5, 6]]])
    query = torch.tensor([[[[1, 7, 8, 9], [1, 10, 11, 9]]] * 2])
    inline = torch.cat((context[:, :, None, :].expand(-1, -1, 2, -1), query), dim=-1)
    answers = torch.tensor([[[0, 1], [1, 1]]])
    choices = torch.tensor([20, 21]).expand(1, 2, 2, 2).clone()
    batch = {}
    for name, ids in (("context", context), ("query", query), ("inline", inline)):
        batch[f"functional_{name}_input_ids"] = ids
        batch[f"functional_{name}_attention_mask"] = torch.ones_like(ids)
        if name != "context":
            labels = torch.full_like(ids, -100)
            labels[..., -1] = 20 + answers
            batch[f"functional_{name}_labels"] = labels
            batch[f"functional_{name}_choice_ids"] = choices.clone()
    return {
        **batch,
        "functional_answer_classes": answers,
        "functional_query_valid_mask": torch.tensor([[True, True]]),
        "functional_affected_mask": torch.tensor([[True, False]]),
        "functional_heldout_mask": torch.tensor([[False, True]]),
        "functional_hop_distances": torch.tensor([[2, 3]]),
        "functional_pair_ids": torch.tensor([17]),
        "compute_workspace_loss": False,
        "compute_spectral": False,
        "bypass_workspace": False,
        "rng_streams": None,
        "memory_intervention": "intact",
        "memory_intervention_seed": 3,
    }


@pytest.mark.parametrize("mode", ["inline", "inline_sidecar", "deferred"])
@pytest.mark.parametrize("autocast", [False, True], ids=["fp32", "bf16_cpu_autocast"])
def test_tiny_functional_wrapper_and_counterfactual_gradients_match_sealed(legacy, mode, autocast):
    torch.manual_seed(43)
    reference = _tiny_wrapper(legacy, mode)
    torch.manual_seed(43)
    candidate = _tiny_wrapper(engine, mode)
    _exact(candidate.state_dict(), reference.state_dict(), "wrapper seeded state")
    # Open the old zero heads to avoid a vacuous route-gradient comparison.
    with torch.no_grad():
        reference.functional_reader.attention.out_proj.weight.normal_(std=0.05)
        if reference.functional_sidecar_adapter is not None:
            reference.functional_sidecar_adapter.up.weight.normal_(std=0.03)
    candidate.load_state_dict(reference.state_dict(), strict=True)
    outputs, gradients = [], []
    for model in (reference, candidate):
        torch.manual_seed(19)
        with torch.autocast("cpu", dtype=torch.bfloat16, enabled=autocast):
            result = model._forward_functional_workspace(**_paired_batch())
            loss = result["task_loss"]
            loss = loss + 0.3 * result["counterfactual_nll_sum"] / result[
                "counterfactual_tokens"
            ].clamp_min(1)
            loss = loss + 0.2 * result["stability_kl_sum"] / result["stability_items"].clamp_min(1)
        loss.backward()
        outputs.append(result)
        gradients.append({name: p.grad for name, p in model.named_parameters()})
    _exact(outputs[1], outputs[0], "wrapper outputs including counterfactual/stability")
    _exact(gradients[1], gradients[0], "wrapper all-parameter gradients")
    if mode != "inline":
        assert outputs[1]["counterfactual_tokens"] == 2
        assert outputs[1]["stability_items"] == 2
        assert torch.count_nonzero(gradients[1]["functional_reader.attention.out_proj.weight"]) > 0


def test_new_default_config_identity_is_not_a_legacy_resume_identity(legacy):
    current = engine.ExperimentConfig()
    previous = legacy.ExperimentConfig()
    before = dataclasses.asdict(previous.functional)
    after = dataclasses.asdict(current.functional)
    for key, value in before.items():
        assert after[key] == value, key
    assert engine.__version__ != legacy.__version__
    assert engine.resume_signature(current) != legacy.resume_signature(previous)
