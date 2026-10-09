"""CPU toy contracts for the no-update runner; no model loading or network."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch
from torch.nn import functional as F

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_ft_beta_learner_audit as runner  # noqa: E402

from latent_workspace_ft_v10.precision_bridge import PrecisionAwareWorkspaceBridge  # noqa: E402


class ToyStore:
    candidate_ids = (0, 1)

    def __init__(self):
        self.records = [
            {
                "answers": [[1, 0, 1, 0, 1, 0, 1, 0], [0, 1, 1, 0, 1, 0, 1, 0]],
                "contexts": ["Facts\n- A above B\n- B above C", "Facts\n- B above A\n- A above C"],
            }
            for _ in range(2)
        ]
        self.contexts = {}
        generator = torch.Generator().manual_seed(908)
        for world in range(2):
            for side in (0, 1, "unrelated", "different_schema", "reserialized_0", "reserialized_1"):
                self.contexts[world, side] = torch.randn(1, 2 + world, 8, generator=generator)

    def query(self, world, query):
        # Large earlier positions make accidentally pooling/using the first token visible.
        hidden = torch.full((1, 3, 8), 100.0 + world + query)
        hidden[:, -1] = torch.arange(8).float() * (0.01 + query * 0.03) + world * 0.2
        return hidden

    def context(self, world, side):
        return self.contexts[world, side]


class ToyAdapter:
    def __init__(self):
        self.calls = 0

    def decode(self, hidden, delta, candidate_ids):
        assert not torch.is_grad_enabled()
        assert candidate_ids == (0, 1)
        self.calls += 1
        value = hidden.clone()
        value[:, -1:] += delta
        return SimpleNamespace(native_logits=value[..., :5])


def fixture():
    with torch.random.fork_rng():
        torch.manual_seed(203)
        bridge = PrecisionAwareWorkspaceBridge(8, workspace_dim=4, heads=2, slots=2).eval()
        torch.nn.init.normal_(bridge.up.weight, std=0.1)
        weight = torch.randn(2, 8)
    return bridge, ToyStore(), weight


@pytest.mark.parametrize("cell", ["task", "semantic"])
def test_gradient_batch_rebuilds_existing_terms_and_uses_only_final_position(monkeypatch, cell):
    bridge, store, weight = fixture()
    contract = {
        "donor_margin": 0.25,
        "direction_weight": 0.7,
        "stability_weight": 0.3,
        "unrelated_weight": 0.2,
        "residual_penalty": 0.01,
    }
    captured = {}
    original = bridge.read_delta

    def read(query, memory, mask):
        captured["query"] = query.detach().clone()
        captured["delta"] = original(query, memory, mask)
        return captured["delta"]

    def audit(_bridge, components, weights, **kwargs):
        captured.update(components=components, weights=weights, **kwargs)
        return {}

    monkeypatch.setattr(bridge, "read_delta", read)
    monkeypatch.setattr(runner, "audit_loss_gradients", audit)
    result = runner.gradient_batch(bridge, store, weight, contract, cell)
    order = [(world, q) for world in range(2) for q in range(8)]
    query = torch.cat([store.query(w, q)[:, -1:] for w, q in order])
    torch.testing.assert_close(captured["query"], query.repeat(3, 1, 1), rtol=0, atol=0)
    scores = F.linear(query.repeat(3, 1, 1) + captured["delta"], weight).squeeze(1)
    first, second, unrelated = scores.chunk(3)
    labels = torch.tensor([[store.records[w]["answers"][s][q] for s in (0, 1)] for w, q in order])
    affected = labels[:, 0] != labels[:, 1]
    gap = second[:, 1] - second[:, 0] - first[:, 1] + first[:, 0]
    donor = (2 * labels[:, 1] - 1) * gap
    base = F.linear(query, weight).squeeze(1)
    expected = {
        "paired_ce": (F.cross_entropy(first, labels[:, 0]) + F.cross_entropy(second, labels[:, 1]))
        / 2,
        "donor_hinge": F.relu(0.25 - donor[affected]).mean(),
        "unaffected_gap_square": gap[~affected].square().mean(),
        "unrelated_gap_square": (unrelated[:, 1] - unrelated[:, 0] - base[:, 1] + base[:, 0])
        .square()
        .mean(),
        "residual_norm_square": captured["delta"].square().sum(-1).mean(),
    }
    for name, value in expected.items():
        torch.testing.assert_close(captured["components"][name], value)
    torch.testing.assert_close(
        captured["total_loss"],
        sum(value * captured["weights"][name] for name, value in expected.items()),
    )
    assert result["batch"]["world_query_order"] == order
    assert result["batch"]["affected_count"] == 4
    assert result["batch"]["unaffected_count"] == 12
    assert captured["weights"]["donor_hinge"] == (0.7 if cell == "semantic" else 0.0)
    assert all(not value.requires_grad for value in captured["frozen_tensors"].values())


def test_gradient_batch_production_autograd_does_not_update_state_or_grads():
    bridge, store, weight = fixture()
    state = {name: value.clone() for name, value in bridge.state_dict().items()}
    result = runner.gradient_batch(
        bridge,
        store,
        weight,
        {
            "donor_margin": 0.25,
            "direction_weight": 1.0,
            "stability_weight": 1.0,
            "unrelated_weight": 1.0,
            "residual_penalty": 0.01,
        },
        "semantic",
    )
    assert result["optimizer_steps"] == 0
    assert result["reconstruction"]["passed"]
    assert all(torch.equal(value, bridge.state_dict()[name]) for name, value in state.items())
    assert all(parameter.grad is None for parameter in bridge.parameters())
    assert all(not module.training for module in bridge.modules())


def test_reserialization_preserves_header_and_fact_multiset():
    text = "World facts.\n- A is above B.\n- B is above C.\n- A is above B.\n- C is above D."
    changed = runner.reserialize(text)
    assert changed != text
    assert changed.splitlines()[0] == text.splitlines()[0]
    assert Counter(changed.splitlines()[1:]) == Counter(text.splitlines()[1:])
    assert changed.splitlines()[1:] == list(reversed(text.splitlines()[1:]))
    assert runner.reserialize(changed) == text
    with pytest.raises(ValueError, match="serialization"):
        runner.reserialize("World facts.\nUnmarked assertion")


def test_controls_close_denominators_and_do_not_mutate_parameters_or_inputs():
    bridge, store, weight = fixture()
    adapter = ToyAdapter()
    state = {name: value.clone() for name, value in bridge.state_dict().items()}
    contexts = {key: value.clone() for key, value in store.contexts.items()}
    result = runner.controls(bridge, store, weight, adapter)
    assert len(result["rows"]) == 2 * 8 * 2 * 8
    assert result["zero_full_logit_checks"] == 16
    assert adapter.calls == 32
    assert result["random_matching"] == "historical_global_raw_memory_L2"
    assert not result["different_schema_amplitude_matched"]
    for row in result["rows"]:
        if row["control"] == "zero":
            assert row["delta_l2"] == 0
            assert row["scores"] == row["base_scores"]
    assert all(torch.equal(value, bridge.state_dict()[name]) for name, value in state.items())
    assert all(torch.equal(value, store.contexts[key]) for key, value in contexts.items())
    assert all(parameter.grad is None for parameter in bridge.parameters())


@pytest.mark.parametrize("setting", [None, "0", "-1"])
def test_cpu_guard_fails_before_model_load_or_output_write(monkeypatch, tmp_path, setting):
    if setting is None:
        monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    else:
        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", setting)

    def forbidden_load(*_args, **_kwargs):
        pytest.fail("CPU guard must run before model loading")

    monkeypatch.setattr(runner.engine, "_load_hf_model", forbidden_load)
    output = tmp_path / "output"
    with pytest.raises(RuntimeError, match="CPU-only"):
        runner.execute(tmp_path, output, 2)
    assert not output.exists()
