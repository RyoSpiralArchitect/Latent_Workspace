"""Tiny V18 state/reduction integration, not preservation or semantic training.

All logits in the optional bank are explicitly synthetic ownership fixtures.
The inherited learner implementations and historical test files stay unchanged.
"""

import copy
import os
import random

import numpy as np
import pytest
import torch
from test_adapter_native_learner_v2 import corrupt, mutate_tensors, versions
from test_v15_native_learner import CONTRACT, META, OPT, SPAN, owner
from transformers.optimization import Adafactor

from latent_workspace_ft_v10.adapted_pair_objective import adapted_pair_objective
from latent_workspace_ft_v10.adapter_native_learner_v2 import AdapterNativeLearnerV2
from latent_workspace_ft_v10.native_training_preparation import (
    prepare_native_gradient_checkpointing,
)
from latent_workspace_ft_v10.slot_contrast_learner import SlotContrastNativeLearner
from latent_workspace_ft_v10.training_binding import MistralTrainingBinding
from latent_workspace_ft_v10.v15_native_learner import rng_state, tree_hash
from latent_workspace_ft_v10.v16_slot_contrast import SlotContrastWorkspaceBridge
from latent_workspace_ft_v10.v18_reference_bank import (
    CapturePolicy,
    ReferenceBank,
    ReferenceRow,
    ReferenceSource,
)
from latent_workspace_ft_v10.v18_window_learner import V18WindowLearner
from latent_workspace_ft_v10.v18_window_objective import WindowReductionSpec, reduced_pair_objective

MODES = ("common", "slot_contrast", "raw_matched_control")
DEVICE = os.environ.get("LATENT_SLOT_STATE_TEST_DEVICE", "cpu")


@pytest.fixture(autouse=True)
def threads():
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


def schedule():
    return (
        WindowReductionSpec("window-1", (("w1-q0", 0, 1), ("w1-q1", 1, 1)), "a" * 64),
        WindowReductionSpec(
            "window-2",
            (("w2-q0", 1, 0), ("w2-q1", 0, 0), ("w2-q2", 1, 1)),
            "b" * 64,
        ),
    )


def synthetic_bank(original_sha, execution_sha, dtype, vocab=43):
    return ReferenceBank(
        ReferenceSource("synthetic/tiny-mistral", "a" * 40, original_sha, "c" * 64, execution_sha),
        CapturePolicy(str(dtype).removeprefix("torch."), "synthetic_ownership_fixture"),
        vocab,
        8,
        "e" * 64,
        (
            ReferenceRow(
                "synthetic-row",
                "train-only-fixture",
                "f" * 64,
                "0" * 64,
                (1, 2, 3),
                tuple(float(index % 4) / 4 for index in range(vocab)),
            ),
        ),
    )


def build(
    mode="slot_contrast",
    dtype=torch.float32,
    full=True,
    checkpointing=False,
    *,
    windows=None,
    with_bank=True,
    nested_objective=False,
):
    parts = owner(dtype, full)
    parts.base.to(DEVICE)
    bridge = (
        parts.bridge if mode == "common" else SlotContrastWorkspaceBridge(parts.bridge, mode=mode)
    ).to(DEVICE)
    preparation = prepare_native_gradient_checkpointing(parts.base) if checkpointing else None
    original_sha = tree_hash(parts.base.state_dict())
    contract = {
        "original_base_sha256": original_sha,
        "objective": copy.deepcopy(CONTRACT),
        "preparation": preparation,
        "data": "synthetic tiny state/reduction fixture; not a semantic qualification",
    }
    binding = MistralTrainingBinding(parts.base, 1)
    bank = synthetic_bank(original_sha, tree_hash(binding.describe()), dtype) if with_bank else None
    if bank is not None:
        contract["reference_source"] = dict(bank.source._asdict())
    if nested_objective:
        contract["objective"] = {
            "terms": contract["objective"],
            "eos_weight": 0.0,
            "query_mode": "final",
        }
    before = tree_hash(rng_state())
    learner = V18WindowLearner(
        binding,
        bridge,
        full_update=full,
        optimizer_config=OPT,
        run_contract=contract,
        schedule=schedule() if windows is None else windows,
        reference_bank=bank,
    )
    assert tree_hash(rng_state()) == before
    assert contract == learner.base_run_contract
    assert "v18_window_reference" not in contract
    return learner, bank


def writer(learner):
    def write(side):
        assert side in (0, 1, "unrelated")
        ids = (1, 8, 9) if side == 0 else (1, 9, 8) if side == 1 else (1, 10, 11)
        hidden = learner.inner.context(ids)
        return learner.bridge.write_memory(
            hidden, torch.ones(hidden.shape[:2], dtype=torch.long, device=hidden.device)
        )

    return write


def pair_kwargs(learner):
    return {
        "write_memory": writer(learner),
        "prefix_ids": SPAN.prefix_ids,
        "span": SPAN,
        "candidate_ids": (6, 7),
    }


def scalar_components(components):
    return {
        name: float(value.detach()) if torch.is_tensor(value) else value
        for name, value in components.items()
    }


def update(learner):
    spec = learner.current_spec
    learner.begin_window()
    rows = []
    for occurrence_id in spec.ids:
        components, spill = learner.backward_pair(occurrence_id, **pair_kwargs(learner))
        assert spill["current_gradient_count"] == len(learner.inner.named)
        rows.append((occurrence_id, scalar_components(components), spill))
    return rows, learner.step()


def restore(target, payload, contract, windows, bank, receipt=None, **kwargs):
    return V18WindowLearner.restore(
        target.binding,
        target.bridge,
        payload,
        expected_metadata=META,
        expected_run_contract=contract,
        expected_schedule=windows,
        expected_reference_bank=bank,
        expected_state_sha256=tree_hash(payload) if receipt is None else receipt,
        **kwargs,
    )


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("checkpointing", [False, True])
def test_variable_windows_serialized_replay_snapshot_and_rng(
    tmp_path,
    mode,
    dtype,
    full,
    checkpointing,
):
    learner, bank = build(mode, dtype, full, checkpointing)
    expected_type = AdapterNativeLearnerV2 if mode == "common" else SlotContrastNativeLearner
    assert type(learner.inner) is expected_type
    assert len(update(learner)[0]) == 2
    receipt = learner.save(tmp_path / "step1.pt", META)
    payload = torch.load(tmp_path / "step1.pt", map_location="cpu", weights_only=True)
    assert tree_hash(payload) == receipt["state_sha256"]
    retained = learner.payload(META)
    retained_hash, bank_hash = tree_hash(retained), bank.content_sha256
    expected = update(learner)
    assert len(expected[0]) == 3
    expected_state = tree_hash(learner.payload(META))
    expected_random = random.random(), np.random.rand(), torch.rand(3, device=DEVICE)
    assert tree_hash(retained) == retained_hash
    assert bank.content_sha256 == bank_hash
    fresh, fresh_bank = build(mode, dtype, full, checkpointing)
    resumed = restore(
        fresh,
        payload,
        learner.base_run_contract,
        schedule(),
        fresh_bank,
        receipt["state_sha256"],
    )
    assert tree_hash(update(resumed)) == tree_hash(expected)
    assert tree_hash(resumed.payload(META)) == expected_state
    assert (random.random(), np.random.rand()) == expected_random[:2]
    assert torch.equal(torch.rand(3, device=DEVICE), expected_random[2])
    assert tree_hash(payload) == receipt["state_sha256"]
    with pytest.raises(FileExistsError):
        resumed.save(tmp_path / "step1.pt", META)
    with pytest.raises(ValueError):
        resumed.begin_window()


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("full", [False, True])
def test_historical_16_pair_loss_gradients_and_update_are_exact(mode, dtype, full):
    labels = [(0, 1), (1, 0)] + [(0, 0), (1, 1)] * 3
    rows = tuple((f"w{world}-q{query}", *labels[query]) for world in range(2) for query in range(8))
    windows = (WindowReductionSpec("legacy-16", rows, "c" * 64),)
    actual, _ = build(mode, dtype, full, windows=windows, with_bank=False)
    reference, _ = build(mode, dtype, full, windows=windows, with_bank=False)
    actual.begin_window()
    reference.inner.begin_window(windows[0].ids)
    for occurrence_id, label0, label1 in rows:
        loss, expected_components = adapted_pair_objective(
            reference.pipeline,
            writer(reference),
            prefix_ids=SPAN.prefix_ids,
            span=SPAN,
            candidate_ids=(6, 7),
            labels=(label0, label1),
            contract=CONTRACT,
        )
        expected_scalars = scalar_components(expected_components)
        expected_spill = reference.inner.backward_pair(occurrence_id, loss)
        actual_components, actual_spill = actual.backward_pair(
            occurrence_id,
            **pair_kwargs(actual),
        )
        assert scalar_components(actual_components) == expected_scalars
        assert tree_hash(actual_spill) == tree_hash(expected_spill)
        # Accumulator buffers retain native-dtype per-pair addition, including BF16 rounding.
        actual_gradients = {
            name: actual.inner.window._buffers[id(parameter)]
            for name, parameter in actual.inner.named
        }
        reference_gradients = {
            name: reference.inner.window._buffers[id(parameter)]
            for name, parameter in reference.inner.named
        }
        assert tree_hash(actual_gradients) == tree_hash(reference_gradients)
    actual.step()
    reference.inner.step()
    assert tree_hash(actual.inner.payload(META)) == tree_hash(reference.inner.payload(META))


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("full", [False, True])
def test_variable_windows_match_independent_native_cpu_accumulation_and_optimizers(
    mode,
    dtype,
    full,
):
    actual, _ = build(mode, dtype, full)
    reference, _ = build(mode, dtype, full)
    bridge_optimizer = torch.optim.AdamW(
        reference.bridge.parameters(),
        lr=OPT["bridge_lr"],
        weight_decay=OPT["bridge_weight_decay"],
    )
    masters = (
        {
            name: torch.nn.Parameter(parameter.detach().float().cpu().clone())
            for name, parameter in reference.inner.base_named
        }
        if full
        else {}
    )
    base_optimizer = (
        Adafactor(
            list(masters.values()),
            lr=OPT["base_lr"],
            eps=(1e-30, 1e-3),
            clip_threshold=1.0,
            decay_rate=-0.8,
            beta1=None,
            weight_decay=OPT["base_weight_decay"],
            scale_parameter=False,
            relative_step=False,
            warmup_init=False,
        )
        if full
        else None
    )
    for spec in schedule():
        gradients = {}
        for occurrence_id in spec.ids:
            loss, _ = reduced_pair_objective(
                reference.pipeline,
                writer(reference),
                spec=spec,
                occurrence_id=occurrence_id,
                prefix_ids=SPAN.prefix_ids,
                span=SPAN,
                candidate_ids=(6, 7),
                contract=CONTRACT,
            )
            loss.backward()
            for name, parameter in reference.inner.named:
                assert parameter.grad is not None
                # Deliberately independent of CompleteCPUWindow and inner.backward_pair.
                value = parameter.grad.detach().cpu()
                if name in gradients:
                    gradients[name].add_(value)
                else:
                    gradients[name] = value.clone()
                parameter.grad = None
        for name, parameter in reference.inner.bridge_named:
            parameter.grad = gradients.pop(f"bridge.{name}").to(parameter.device)
        for name, parameter in masters.items():
            parameter.grad = gradients.pop(f"base.{name}").float()
        assert not gradients
        torch.nn.utils.clip_grad_norm_(
            reference.bridge.parameters(),
            OPT["max_grad_norm_per_family"],
            error_if_nonfinite=True,
        )
        if full:
            torch.nn.utils.clip_grad_norm_(
                list(masters.values()),
                OPT["max_grad_norm_per_family"],
                error_if_nonfinite=True,
            )
            base_optimizer.step()
            base_optimizer.zero_grad(set_to_none=True)
        bridge_optimizer.step()
        bridge_optimizer.zero_grad(set_to_none=True)
        if full:
            with torch.no_grad():
                for name, parameter in reference.inner.base_named:
                    parameter.copy_(masters[name].to(parameter.dtype), non_blocking=False)
        rows, receipt = update(actual)
        assert len(rows) == len(spec.ids)
        assert receipt["transfer"]["spill_count"] == len(spec.ids)
        assert tree_hash(actual.base.state_dict()) == tree_hash(reference.base.state_dict())
        assert tree_hash(actual.bridge.state_dict()) == tree_hash(reference.bridge.state_dict())
        assert tree_hash(actual.inner.bridge_optimizer.state_dict()) == tree_hash(
            bridge_optimizer.state_dict(),
        )
        if full:
            assert tree_hash(actual.inner.masters) == tree_hash(masters)
            assert tree_hash(actual.inner.base_optimizer.state_dict()) == tree_hash(
                base_optimizer.state_dict(),
            )


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("full", [False, True])
def test_snapshots_own_all_containers_and_do_not_alias_reference_bank(mode, full):
    learner, bank = build(mode, full=full)
    update(learner)
    metadata = {"nested": [{"tensor": torch.ones(2), "names": ["original"]}]}
    original_meta, original_bank = tree_hash(metadata), bank.snapshot()
    original_state = tree_hash(learner.payload(metadata))
    saved = learner.payload(metadata)
    mutate_tensors(saved)
    saved["inner"]["metadata"]["nested"][0]["names"].append("snapshot-only")
    saved["reference_bank"]["rows"][0]["logits"][0] = 99.0
    saved["schedule"][0]["occurrences"][0][0] = "snapshot-only"
    assert tree_hash(learner.payload(metadata)) == original_state
    assert tree_hash(metadata) == original_meta
    assert bank.snapshot() == original_bank
    saved = learner.payload(metadata)
    saved_hash = tree_hash(saved)
    metadata["nested"][0]["names"].append("caller-only")
    update(learner)
    assert tree_hash(saved) == saved_hash


CORRUPTIONS = (
    "outer_format",
    "outer_extra",
    "inner_extra",
    "inner_format",
    "window_count",
    "schedule_order",
    "reference_role",
    "reference_value",
    "policy_extra",
    "metadata",
    "run_contract",
    "bridge_policy",
    "bridge_moment",
    "base_policy",
    "base_masters",
    "completed_steps",
    "current_base_sha",
    "rng_cpu",
    "receipt",
)


def corrupt_outer(payload, failure, full):
    if failure == "outer_format":
        payload["format"] = "legacy-is-not-v18"
    elif failure == "outer_extra":
        payload["unowned"] = 1
    elif failure == "inner_extra":
        payload["inner"]["unowned"] = 1
    elif failure == "inner_format":
        payload["inner"]["format"] = "v15-native-resume-v1"
    elif failure == "window_count":
        payload["schedule"][0]["counts"]["answer_terms"] += 1
    elif failure == "schedule_order":
        payload["schedule"].reverse()
    elif failure == "reference_role":
        payload["reference_bank"]["role"] = "preservation_loss_enabled"
    elif failure == "reference_value":
        payload["reference_bank"]["rows"][0]["logits"][0] += 1.0
    elif failure == "policy_extra":
        payload["policy"]["unowned"] = 1
    elif failure != "receipt":
        corrupt(payload["inner"], failure, full)


@pytest.mark.parametrize("mode", ["common", "slot_contrast"])
@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("failure", CORRUPTIONS)
def test_malformed_envelope_rejects_before_target_or_rng_write(mode, full, failure):
    source, _ = build(mode, torch.bfloat16, full)
    update(source)
    payload = source.payload(META)
    corrupt_outer(payload, failure, full)
    target, bank = build(mode, torch.bfloat16, full)
    before = tree_hash(target.payload(META)), versions(target.inner), tree_hash(rng_state())
    guard = target.binding.readout._execution_key()
    saved_hash = tree_hash(payload)
    with pytest.raises(ValueError):
        restore(
            target,
            payload,
            source.base_run_contract,
            schedule(),
            bank,
            "0" * 64 if failure == "receipt" else None,
        )
    assert (
        tree_hash(target.payload(META)),
        versions(target.inner),
        tree_hash(rng_state()),
    ) == before
    assert target.binding.readout._execution_key() == guard
    assert tree_hash(payload) == saved_hash
    # Failed restore leaves a usable original target, without rebuilding its guards.
    update(target)


@pytest.mark.parametrize("mismatch", ["schedule", "bank", "missing_bank", "eos", "run"])
def test_expected_contract_mismatch_rejects_before_target_write(mismatch):
    source, _ = build()
    payload = source.payload(META)
    target, bank = build()
    windows, contract, kwargs = schedule(), source.base_run_contract, {}
    if mismatch == "schedule":
        windows = tuple(reversed(windows))
    elif mismatch == "bank":
        bank = bank._replace(split_manifest_sha256="7" * 64)
    elif mismatch == "missing_bank":
        bank = None
    elif mismatch == "eos":
        kwargs["eos_weight"] = 0.25
    else:
        contract = copy.deepcopy(contract)
        contract["objective"]["donor_margin"] += 0.1
    before = tree_hash(target.payload(META)), versions(target.inner), tree_hash(rng_state())
    with pytest.raises(ValueError):
        restore(target, payload, contract, windows, bank, **kwargs)
    assert (
        tree_hash(target.payload(META)),
        versions(target.inner),
        tree_hash(rng_state()),
    ) == before


@pytest.mark.parametrize(
    "mismatch",
    ["policy_eos_boolean", "policy_eos_integer", "inner_eos_boolean", "inner_weight_boolean"],
)
def test_numerically_equal_but_differently_typed_contracts_are_not_resume_equivalent(mismatch):
    source, _ = build()
    payload = source.payload(META)
    if mismatch == "policy_eos_boolean":
        payload["policy"]["eos_weight"] = False
    elif mismatch == "policy_eos_integer":
        payload["policy"]["eos_weight"] = 0
    elif mismatch == "inner_eos_boolean":
        payload["inner"]["run_contract"]["v18_window_reference"]["eos_weight"] = False
    else:
        # Config's original 0.0 must not silently become False under Python equality.
        payload["inner"]["optimizer_config"]["base_weight_decay"] = False
    target, bank = build()
    before = tree_hash(target.payload(META)), versions(target.inner), tree_hash(rng_state())
    with pytest.raises(ValueError):
        restore(target, payload, source.base_run_contract, schedule(), bank)
    assert (
        tree_hash(target.payload(META)),
        versions(target.inner),
        tree_hash(rng_state()),
    ) == before


@pytest.mark.parametrize("mode", MODES)
def test_partial_and_misordered_windows_never_publish_updates_or_checkpoints(mode):
    learner, _ = build(mode)
    before = tree_hash(learner.base.state_dict()), tree_hash(learner.bridge.state_dict())
    learner.begin_window()
    with pytest.raises(ValueError):
        learner.step()
    with pytest.raises(ValueError):
        learner.backward_pair("w1-q1", **pair_kwargs(learner))
    assert learner.inner.cursor == 0
    learner.backward_pair("w1-q0", **pair_kwargs(learner))
    with pytest.raises(ValueError):
        learner.backward_pair("w1-q0", **pair_kwargs(learner))
    with pytest.raises(ValueError):
        learner.payload(META)
    with pytest.raises(ValueError):
        learner.step()
    assert learner.inner.cursor == 1
    assert (tree_hash(learner.base.state_dict()), tree_hash(learner.bridge.state_dict())) == before
    learner.backward_pair("w1-q1", **pair_kwargs(learner))
    learner.step()
    assert learner.completed_steps == 1


@pytest.mark.parametrize("mutation", ["norm", "dropout", "training", "hook", "run"])
def test_common_policy_mutation_is_rejected_before_window_allocation(mutation):
    learner, _ = build("common")
    if mutation == "norm":
        learner.bridge.memory_norm.eps *= 10
    elif mutation == "dropout":
        learner.bridge.attention.dropout = 0.1
    elif mutation == "training":
        learner.bridge.writer.eval()
    elif mutation == "hook":
        learner.bridge.attention.register_forward_hook(lambda _module, _args, output: output)
    else:
        learner.inner.run_contract["objective"]["donor_margin"] += 1
    before = tree_hash(rng_state()), versions(learner.inner)
    with pytest.raises(ValueError):
        learner.begin_window()
    assert learner.inner.window is None
    assert (tree_hash(rng_state()), versions(learner.inner)) == before


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("full", [False, True])
def test_step_zero_without_bank_has_exact_new_envelope_roundtrip(mode, full):
    source, _ = build(mode, full=full, with_bank=False)
    payload = source.payload(META)
    target, _ = build(mode, full=full, with_bank=False)
    restored = restore(target, payload, source.base_run_contract, schedule(), None)
    assert payload["reference_bank"] is None
    assert tree_hash(restored.payload(META)) == tree_hash(payload)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("full", [False, True])
def test_nested_qualified_objective_and_flat_fixture_have_identical_updates(mode, full):
    flat, _ = build(mode, full=full)
    nested, _ = build(mode, full=full, nested_objective=True)
    for _ in schedule():
        assert tree_hash(update(flat)) == tree_hash(update(nested))
        for left, right in (
            (flat.base.state_dict(), nested.base.state_dict()),
            (flat.bridge.state_dict(), nested.bridge.state_dict()),
            (flat.inner.masters, nested.inner.masters),
            (flat.inner.bridge_optimizer.state_dict(), nested.inner.bridge_optimizer.state_dict()),
        ):
            assert tree_hash(left) == tree_hash(right)
        if full:
            assert tree_hash(flat.inner.base_optimizer.state_dict()) == tree_hash(
                nested.inner.base_optimizer.state_dict(),
            )


@pytest.mark.parametrize("mismatch", ["tokenizer", "missing_source"])
def test_reference_requires_independently_declared_exact_source_before_construction(mismatch):
    target, bank = build("common")
    contract = target.base_run_contract
    if mismatch == "tokenizer":
        contract["reference_source"]["tokenizer_sha256"] = "8" * 64
    else:
        contract.pop("reference_source")
    before = tree_hash(target.payload(META)), versions(target.inner), tree_hash(rng_state())
    with pytest.raises(ValueError):
        V18WindowLearner(
            target.binding,
            target.bridge,
            full_update=target.full_update,
            optimizer_config=OPT,
            run_contract=contract,
            schedule=schedule(),
            reference_bank=bank,
        )
    assert (
        tree_hash(target.payload(META)),
        versions(target.inner),
        tree_hash(rng_state()),
    ) == before


@pytest.mark.parametrize("mismatch", ["missing_terms", "extra", "query", "eos", "weight"])
def test_invalid_nested_objective_is_rejected_before_constructor_writes(mismatch):
    target, bank = build("common", nested_objective=True)
    contract = target.base_run_contract
    objective = contract["objective"]
    if mismatch == "missing_terms":
        objective.pop("terms")
    elif mismatch == "extra":
        objective["unowned"] = 1
    elif mismatch == "query":
        objective["query_mode"] = "mean_span"
    elif mismatch == "eos":
        objective["eos_weight"] = 0.5
    else:
        objective["terms"]["direction_weight"] = False
    before = tree_hash(target.payload(META)), versions(target.inner), tree_hash(rng_state())
    with pytest.raises(ValueError):
        V18WindowLearner(
            target.binding,
            target.bridge,
            full_update=target.full_update,
            optimizer_config=OPT,
            run_contract=contract,
            schedule=schedule(),
            reference_bank=bank,
        )
    assert (
        tree_hash(target.payload(META)),
        versions(target.inner),
        tree_hash(rng_state()),
    ) == before
