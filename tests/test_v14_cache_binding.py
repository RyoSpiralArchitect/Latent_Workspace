"""CPU-only mechanics for the strict Mistral cache trajectory adapter."""

from __future__ import annotations

import dataclasses

import pytest
import torch

transformers = pytest.importorskip("transformers")
from transformers import MistralConfig, MistralForCausalLM  # noqa: E402

from latent_workspace_ft_v10.cache_binding import (  # noqa: E402
    ActivationPulse,
    MistralDynamicCacheAdapter,
)


@pytest.fixture(autouse=True)
def bounded_cpu_threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(previous)


def tiny_mistral(*, sliding_window=None) -> MistralForCausalLM:
    torch.manual_seed(1491)
    config = MistralConfig(
        vocab_size=43,
        hidden_size=16,
        intermediate_size=32,
        num_hidden_layers=2,
        num_attention_heads=4,
        num_key_value_heads=2,
        max_position_embeddings=32,
        attention_dropout=0.0,
        pad_token_id=0,
        sliding_window=sliding_window,
        use_cache=True,
    )
    config._attn_implementation = "eager"
    return MistralForCausalLM(config).eval()


def prefix() -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    ids = torch.tensor([[1, 4, 5]], dtype=torch.long)
    positions = torch.arange(ids.shape[1]).unsqueeze(0)
    mask = torch.ones_like(ids)
    return ids, positions, mask


def advance(
    adapter: MistralDynamicCacheAdapter,
    cache,
    token: int,
    position: int,
    *,
    pulse: ActivationPulse | None = None,
):
    return adapter.step(
        torch.tensor([[token]], dtype=torch.long),
        cache,
        torch.ones((1, position + 1), dtype=torch.long),
        torch.tensor([[position]], dtype=torch.long),
        pulse=pulse,
    )


def history_snapshot(adapter, cache, ids: torch.Tensor):
    return adapter.snapshot(
        cache,
        token_ids=ids,
        position_ids=torch.arange(ids.shape[1]).unsqueeze(0),
        attention_mask=torch.ones_like(ids),
    )


def test_cached_fixed_continuation_matches_full_history_recomputation() -> None:
    model = tiny_mistral()
    adapter = MistralDynamicCacheAdapter(model)
    all_ids = torch.tensor([[1, 4, 5, 6, 7, 8]], dtype=torch.long)
    initial_ids, positions, mask = prefix()
    initial = adapter.prefill(initial_ids, mask, positions)
    cache = initial.cache

    for position in range(initial_ids.shape[1], all_ids.shape[1]):
        before = adapter.snapshot(cache)
        result = advance(adapter, cache, int(all_ids[0, position]), position)
        assert adapter.snapshot(cache).integrity_sha256 == before.integrity_sha256
        cache = result.cache
        with torch.no_grad():
            expected = model(
                input_ids=all_ids[:, : position + 1],
                attention_mask=torch.ones((1, position + 1), dtype=torch.long),
                position_ids=torch.arange(position + 1).unsqueeze(0),
                use_cache=False,
            ).logits[:, -1:]
        torch.testing.assert_close(result.logits, expected, rtol=1e-6, atol=1e-6)
        assert result.receipt["cache_length_before"] == position
        assert result.receipt["cache_length_after"] == position + 1
        assert result.receipt["cache_prefix_exact"] is True
        assert result.receipt["pulse"] == {"applied": False, "call_count": 0}


def test_one_layer_input_pulse_writes_native_kv_without_mutating_inputs() -> None:
    model = tiny_mistral()
    adapter = MistralDynamicCacheAdapter(model)
    ids, positions, mask = prefix()
    base_cache = adapter.prefill(ids, mask, positions).cache
    inputs = (
        torch.tensor([[6]], dtype=torch.long),
        torch.ones((1, 4), dtype=torch.long),
        torch.tensor([[3]], dtype=torch.long),
    )
    copies = tuple(value.clone() for value in inputs)
    direction = torch.arange(1, 17, dtype=torch.float32)
    positive = adapter.step(
        inputs[0],
        base_cache,
        inputs[1],
        inputs[2],
        pulse=ActivationPulse(layer_index=1, direction=direction, scale=0.5),
    )
    negative = adapter.step(
        inputs[0],
        base_cache,
        inputs[1],
        inputs[2],
        pulse=ActivationPulse(layer_index=1, direction=direction, scale=-0.5),
    )
    no_pulse = adapter.step(inputs[0], base_cache, inputs[1], inputs[2])

    for actual, expected in zip(inputs, copies, strict=True):
        assert torch.equal(actual, expected)
    assert adapter.stats(base_cache)["seq_length"] == 3
    assert len(model.model.layers[1]._forward_pre_hooks) == 0
    for result, sign in ((positive, 1.0), (negative, -1.0)):
        receipt = result.receipt["pulse"]
        assert receipt["applied"] is True
        assert receipt["call_count"] == 1
        assert receipt["layer_index"] == 1
        assert receipt["boundary"] == "decoder_layer_input_pre_rmsnorm"
        assert receipt["composition_dtype"] == "fp32_add_then_cast_to_hidden"
        assert receipt["normalized_direction_rms"] == 1.0
        assert receipt["requested_delta_rms"] == 0.5
        assert receipt["requested_delta_l2"] == 2.0
        assert receipt["actual_delta_rms"] == pytest.approx(0.5, abs=1e-6)
        assert receipt["actual_delta_l2"] == pytest.approx(2.0, abs=1e-6)
        assert receipt["actual_signed_projection"] == pytest.approx(sign * 2.0, abs=1e-6)
        assert receipt["signed_projection_basis"] == ("provided_direction_normalized_to_unit_l2")

    positive_delta = adapter.difference(positive.cache, no_pulse.cache)
    negative_delta = adapter.difference(negative.cache, no_pulse.cache)
    assert positive_delta["aggregate_l2"] > 0.0
    assert negative_delta["aggregate_l2"] > 0.0
    assert positive_delta["per_layer"][0]["key_nonzero"] == 0
    assert positive_delta["per_layer"][0]["value_nonzero"] == 0
    assert positive_delta["per_layer"][1]["key_last_position_l2"] > 0.0
    assert positive_delta["per_layer"][1]["value_last_position_l2"] > 0.0
    pulse_position_before = adapter.position_fingerprints(positive.cache, 3)
    carried = advance(adapter, positive.cache, 7, 4)
    pulse_position_after = adapter.position_fingerprints(carried.cache, 3)
    assert pulse_position_after["layers"] == pulse_position_before["layers"]


def test_history_bound_replacement_and_five_cells_erase_and_restore_pulse() -> None:
    model = tiny_mistral()
    adapter = MistralDynamicCacheAdapter(model)
    ids, positions, mask = prefix()
    prefix_cache = adapter.prefill(ids, mask, positions).cache
    direction = torch.arange(1, 17, dtype=torch.float32)
    base = advance(adapter, prefix_cache, 6, 3)
    intact = advance(
        adapter,
        prefix_cache,
        6,
        3,
        pulse=ActivationPulse(layer_index=1, direction=direction, scale=0.5),
    )
    twin = advance(
        adapter,
        prefix_cache,
        6,
        3,
        pulse=ActivationPulse(layer_index=1, direction=direction, scale=-0.5),
    )
    full_ids = torch.tensor([[1, 4, 5, 6]], dtype=torch.long)
    base_snapshot = history_snapshot(adapter, base.cache, full_ids)
    intact_snapshot = history_snapshot(adapter, intact.cache, full_ids)
    twin_snapshot = history_snapshot(adapter, twin.cache, full_ids)
    cells = adapter.five_cells(base_snapshot, intact_snapshot, twin_snapshot).as_dict()

    assert adapter.difference(cells["A"], base.cache)["exact_equal"] is True
    assert adapter.difference(cells["B"], intact.cache)["exact_equal"] is True
    assert adapter.difference(cells["C"], twin.cache)["exact_equal"] is True
    assert adapter.difference(cells["D"], base.cache)["exact_equal"] is True
    assert adapter.difference(cells["E"], base.cache)["exact_equal"] is True
    assert adapter.difference(cells["A"], cells["D"])["exact_equal"] is True
    assert adapter.difference(cells["A"], cells["E"])["exact_equal"] is True

    horizon = {name: advance(adapter, cache, 7, 4) for name, cache in cells.items()}
    torch.testing.assert_close(horizon["D"].logits, horizon["A"].logits, rtol=0.0, atol=0.0)
    torch.testing.assert_close(horizon["E"].logits, horizon["A"].logits, rtol=0.0, atol=0.0)
    assert not torch.equal(horizon["B"].logits, horizon["A"].logits)
    assert not torch.equal(horizon["C"].logits, horizon["A"].logits)

    transplanted = adapter.replace(base_snapshot, intact_snapshot)
    transplanted_horizon = advance(adapter, transplanted, 7, 4)
    torch.testing.assert_close(
        transplanted_horizon.logits,
        horizon["B"].logits,
        rtol=0.0,
        atol=0.0,
    )


def test_snapshot_integrity_history_and_layout_corruption_fail_closed() -> None:
    adapter = MistralDynamicCacheAdapter(tiny_mistral())
    ids, positions, mask = prefix()
    cache = adapter.prefill(ids, mask, positions).cache
    snapshot = history_snapshot(adapter, cache, ids)
    restored = adapter.restore(snapshot)
    assert adapter.difference(cache, restored)["exact_equal"] is True

    bad_digest = dataclasses.replace(snapshot, integrity_sha256="0" * 64)
    with pytest.raises(ValueError, match="integrity digest mismatch"):
        adapter.restore(bad_digest)

    bad_layers = tuple((key.clone(), value.clone()) for key, value in snapshot.layers)
    bad_layers[0][0][0, 0, 0, 0] = torch.nan
    bad_values = dataclasses.replace(snapshot, layers=bad_layers)
    with pytest.raises(ValueError, match="non-finite"):
        adapter.restore(bad_values)

    alternate_ids = ids.clone()
    alternate_ids[0, 1] = 9
    alternate = history_snapshot(adapter, cache, alternate_ids)
    with pytest.raises(ValueError, match="token_ids"):
        adapter.replace(snapshot, alternate)

    no_history = adapter.snapshot(cache)
    with pytest.raises(ValueError, match="exact history identity"):
        adapter.replace(no_history, snapshot)


def test_invalid_model_cache_and_pulse_contracts_are_rejected() -> None:
    with pytest.raises(ValueError, match="full attention"):
        MistralDynamicCacheAdapter(tiny_mistral(sliding_window=8))

    model = tiny_mistral()
    adapter = MistralDynamicCacheAdapter(model)
    ids, positions, mask = prefix()
    cache = adapter.prefill(ids, mask, positions).cache
    with pytest.raises(TypeError, match="exact Transformers DynamicCache"):
        adapter.clone(object())
    with pytest.raises(ValueError, match="outside model layer range"):
        advance(
            adapter,
            cache,
            6,
            3,
            pulse=ActivationPulse(2, torch.ones(16), 0.5),
        )
    with pytest.raises(ValueError, match="width"):
        advance(
            adapter,
            cache,
            6,
            3,
            pulse=ActivationPulse(1, torch.ones(15), 0.5),
        )
    with pytest.raises(ValueError, match="exactly one input token"):
        adapter.step(
            torch.tensor([[6, 7]], dtype=torch.long),
            cache,
            torch.ones((1, 5), dtype=torch.long),
            torch.tensor([[3, 4]], dtype=torch.long),
        )
    with pytest.raises(ValueError, match="contiguous zero-based"):
        adapter.step(
            torch.tensor([[6]], dtype=torch.long),
            cache,
            torch.ones((1, 4), dtype=torch.long),
            torch.tensor([[4]], dtype=torch.long),
        )


def test_adapter_descriptor_and_snapshot_are_metadata_only_views() -> None:
    adapter = MistralDynamicCacheAdapter(tiny_mistral())
    assert adapter.descriptor["model_type"] == "mistral"
    assert adapter.descriptor["pulse_boundary"] == "decoder_layer_input_pre_rmsnorm"
    assert len(adapter.adapter_fingerprint) == 64
    ids, positions, mask = prefix()
    cache = adapter.prefill(ids, mask, positions).cache
    snapshot = history_snapshot(adapter, cache, ids)
    metadata = snapshot.to_dict()
    assert metadata["has_history"] is True
    assert metadata["seq_length"] == 3
    assert metadata["layer_count"] == 2
    assert metadata["integrity_sha256"] == snapshot.integrity_sha256
    assert "layers" not in metadata and "token_ids" not in metadata
