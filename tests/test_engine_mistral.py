from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import torch
import torch.nn.functional as F
from transformers import GPT2Config, GPT2LMHeadModel, MistralConfig, MistralForCausalLM
from transformers.optimization import Adafactor

from latent_workspace_ft_v10.engine import (
    ExperimentConfig,
    FunctionalBoundaryAdapter,
    LatentWorkspaceCausalLM,
    LatentWorkspaceLoss,
    TrainConfig,
    WorkspaceConfig,
    _functional_split_equivalence_check,
    _require_resume_optimizer_mapping,
    _restore_optimizer_state_exact,
    base_update_coverage_report,
    build_optimizer,
    configure_trainability,
    optimizer_coverage_report,
    optimizer_step_with_base_sentinel,
    require_base_update_coverage,
    require_exact_optimizer_coverage,
    resume_signature,
    stable_hash,
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
    assert resumed_optimizer.state[resumed_parameter]["exp_avg_sq_row"].dtype == (
        torch.bfloat16
    )

    _restore_optimizer_state_exact(resumed_optimizer, saved)
    restored_state = resumed_optimizer.state[resumed_parameter]
    for name, expected in saved_state.items():
        actual = restored_state[name]
        if isinstance(expected, torch.Tensor):
            assert actual.dtype == expected.dtype
            assert torch.equal(actual.cpu(), expected)
        else:
            assert actual == expected

    next_gradient = torch.tensor(
        [[0.125, -0.375], [0.5, -0.625]], dtype=torch.bfloat16
    )
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
    (checkpoint / "optimizer_coverage.json").write_text(
        json.dumps(report), encoding="utf-8"
    )
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
