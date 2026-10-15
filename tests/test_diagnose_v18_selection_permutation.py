"""Tiny fixtures only: no saved fit is executed, fitted, or overwritten."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
import torch
from torch.nn import functional as F

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import assay_v18_operand_selection as assay  # noqa: E402
import diagnose_v18_selection_permutation as diagnostic  # noqa: E402


@pytest.fixture(autouse=True)
def bounded_threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(previous)


@pytest.fixture
def population():
    # Separate deterministic analytic fixture; no original study populations.
    return assay.population(seed=9127, frames=1)


def nonzero_reader(factor="centered_ordered"):
    bridge = assay.make_reader(9127, factor)
    with torch.no_grad():
        bridge.up.weight.copy_(torch.eye(32))
    bridge.eval()
    bridge.requires_grad_(False)
    return bridge


@pytest.mark.parametrize("factor", diagnostic.PLAN["factors"])
def test_observational_trace_native_parity_and_read_only(factor, population):
    bridge = nonzero_reader(factor)
    before = assay.state_fingerprint(bridge)
    inputs = {key: value.clone() for key, value in vars(population.inputs).items()}
    original_sdpa = F.scaled_dot_product_attention
    with torch.no_grad():
        expected_logits, expected_delta = assay.forward(bridge, population.inputs, factor)
    traced = diagnostic.traced_forward(bridge, population.inputs, factor)
    assert torch.equal(traced["native_logits"], expected_logits)
    assert torch.equal(traced["delta"], expected_delta)
    assert torch.equal(traced["common.delta_reconstructed"], torch.zeros_like(expected_delta))
    assert F.scaled_dot_product_attention is original_sdpa
    assert assay.state_fingerprint(bridge) == before
    assert all(torch.equal(inputs[key], value) for key, value in vars(population.inputs).items())
    assert not any(
        module._forward_hooks or module._forward_pre_hooks for module in bridge.modules()
    )
    assert not bridge.training


def test_trace_requires_historical_eval(population):
    bridge = nonzero_reader()
    bridge.train()
    with pytest.raises(ValueError, match="eval"):
        diagnostic.traced_forward(bridge, population.inputs, "centered_ordered")


def test_trace_restores_hooks_and_sdpa_after_exception(population, monkeypatch):
    bridge = nonzero_reader()
    original_sdpa = F.scaled_dot_product_attention

    def fail(*_args, **_kwargs):
        raise RuntimeError("Test interruption")

    monkeypatch.setattr(bridge.attention, "forward", fail)
    with pytest.raises(RuntimeError, match="Test interruption"):
        diagnostic.traced_forward(bridge, population.inputs, "centered_ordered")
    assert F.scaled_dot_product_attention is original_sdpa
    assert not any(
        module._forward_hooks or module._forward_pre_hooks for module in bridge.modules()
    )


def test_aligned_slot_stages_not_gauge(population):
    bridge = nonzero_reader()
    data = population.inputs
    permutation = diagnostic.PLAN["slot_permutation"]
    permuted = assay.Inputs(data.states, data.memory[:, permutation], data.mask[:, permutation])
    first = diagnostic.traced_forward(bridge, data, "centered_ordered")
    second = diagnostic.traced_forward(bridge, permuted, "centered_ordered")
    result = diagnostic.compare_traces(first, second)
    assert result["aligned"]["interaction.memory_normalized"]["exact"]
    assert result["aligned"]["common.memory_normalized"]["exact"]
    assert result["aligned"]["common_query"]["exact"]
    assert result["aligned"]["interaction_query"]["exact"]
    assert not torch.equal(first["interaction.anchor_gauge"], second["interaction.anchor_gauge"])
    assert "interaction.anchor_gauge" not in result["aligned"]
    assert all(
        "gauge" not in (value or "") for value in result["first_changed_observed_stage"].values()
    )


def test_projected_slot_alignment_axis_is_head_sequence():
    original = {"interaction.projected_k": torch.arange(2 * 2 * 3 * 4).reshape(2, 2, 3, 4).float()}
    permuted = {
        key: value[:, :, diagnostic.PLAN["slot_permutation"]] for key, value in original.items()
    }
    assert diagnostic.compare_traces(original, permuted)["aligned"]["interaction.projected_k"][
        "exact"
    ]


def test_synthetic_first_difference_localization():
    original = {
        "interaction.memory_normalized": torch.zeros(1, 3, 2),
        "interaction.centered_memory": torch.zeros(1, 3, 2),
        "interaction.projected_k": torch.zeros(1, 2, 3, 1),
    }
    permuted = copy.deepcopy(original)
    permuted["interaction.centered_memory"][0, 0, 0] = 1e-7
    result = diagnostic.compare_traces(original, permuted)
    assert result["first_changed_observed_stage"]["interaction"] == "interaction.centered_memory"


def test_centering_reconstruction_masked_slots():
    values = torch.tensor([[[9.0, -9], [1.0, -1], [3.0, -3]]])
    mask = torch.tensor([[0, 1, 1]])
    result = diagnostic.centering_observation(values, mask, True)
    assert torch.equal(result["anchor_gauge"], values[:, 1:2])
    assert torch.equal(result["centered_memory"], torch.tensor([[[0.0, 0], [-1.0, 1], [1.0, -1]]]))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_traces_rejected(bad):
    with pytest.raises(ValueError, match="Nonfinite"):
        diagnostic.tensor_summary(torch.tensor([0.0]), torch.tensor([bad]))


def test_batching_matches_frozen_256(population, monkeypatch):
    data = population.inputs
    indices = torch.arange(513) % len(data.states)
    inputs = data.take(indices)
    calls = []

    def fake(_bridge, chunk, _factor):
        calls.append(len(chunk.states))
        return {"test": chunk.states[:, :1]}

    monkeypatch.setattr(diagnostic, "traced_forward", fake)
    result = diagnostic.trace_measured(None, inputs, "centered_ordered", "cpu", lambda: None)
    assert calls == [256, 256, 1]
    assert len(result["test"]) == 513


@pytest.fixture
def cell(population, monkeypatch):
    bridge = nonzero_reader()

    def prohibited(*_args, **_kwargs):
        pytest.fail("No optimizer, backward, update, or writer invocation is permitted")

    monkeypatch.setattr(torch.optim, "AdamW", prohibited)
    monkeypatch.setattr(torch.Tensor, "backward", prohibited)
    monkeypatch.setattr(assay, "update", prohibited)
    monkeypatch.setattr(bridge, "write_memory", prohibited)
    historical = assay.controls(bridge, "centered_ordered", population, "cpu", lambda: None, 1e-6)
    return diagnostic.diagnose_cell(
        bridge,
        population,
        "centered_ordered",
        "cpu",
        lambda: None,
        historical,
    )


def test_cell_replays_historical_controls_without_learning(cell):
    raw, summary = cell
    assert summary["historical_control_reproduction_exact"]
    assert summary["hook_native_parity"]
    assert summary["same_input_repeats"]["original"]["exact"]
    assert summary["same_input_repeats"]["permuted"]["exact"]
    assert summary["state_unchanged"] and summary["input_tensors_unchanged"]
    assert summary["forward_calls"] == 12
    assert summary["training_updates"] == summary["optimizer_instances"] == 0
    assert len(raw["raw"]) == 8


def test_historical_mismatch_recorded_not_silently_repaired(cell):
    raw, summary = cell
    historical = copy.deepcopy(summary["historical_controls"])
    historical["permutation_max_logit_error"] = 10.0
    result = diagnostic.summarize_cell(
        raw["raw"], raw["traces"], summary["reobserved_controls"], historical
    )
    assert not result["historical_control_reproduction_exact"]
    assert result["promotion"] == "BLOCKED_CONTROL_REPRODUCTION_MISMATCH"
    assert result["historical_controls"]["permutation_max_logit_error"] == 10.0


def test_raw_receipt_replay_and_tamper_rejection(cell, tmp_path):
    raw, summary = cell
    path = tmp_path / "9127_centered_ordered.pt"
    diagnostic.save_tensor(path, raw)
    summary["raw_sha256"] = diagnostic.audit.sha(path)
    result = diagnostic.verify_cell_files(tmp_path, "9127_centered_ordered", summary)
    assert result["hook_native_parity"]
    tampered = copy.deepcopy(summary)
    tampered["native_permutation"]["max_abs_error"] += 0.01
    with pytest.raises(ValueError, match="summary mismatch"):
        diagnostic.verify_cell_files(tmp_path, "9127_centered_ordered", tampered)
    tampered = copy.deepcopy(summary)
    tampered["raw_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash mismatch"):
        diagnostic.verify_cell_files(tmp_path, "9127_centered_ordered", tampered)


def test_missing_trace_event_fails_closed(cell):
    raw, _ = cell
    trace = copy.deepcopy(raw["traces"]["original"])
    del trace["interaction.centered_memory"]
    with pytest.raises(ValueError, match="trace event population"):
        diagnostic.verify_trace_schema(trace, 36, "centered_ordered")


@pytest.mark.parametrize(
    "field", ["permutation_max_logit_error", "same_memory_exact", "max_delta_norm"]
)
def test_contradictory_scalar_controls_not_accepted(cell, tmp_path, field):
    raw, summary = cell
    current = copy.deepcopy(summary["reobserved_controls"])
    if field == "same_memory_exact":
        current[field] = False
    else:
        current[field] = 0.125
    current["pass"] = False if field != "max_delta_norm" else current["pass"]
    summary.update(
        diagnostic.summarize_cell(
            raw["raw"], raw["traces"], current, summary["historical_controls"]
        )
    )
    path = tmp_path / "9127_centered_ordered.pt"
    diagnostic.save_tensor(path, raw)
    summary["raw_sha256"] = diagnostic.audit.sha(path)
    with pytest.raises(ValueError, match="scalar differs"):
        diagnostic.verify_cell_files(tmp_path, "9127_centered_ordered", summary)


def test_historical_native_logits_mismatch_prevents_promotion(cell):
    raw, summary = cell
    raw["raw"]["historical_original_logits"] = raw["raw"]["original_0_logits"].clone()
    raw["raw"]["historical_original_logits"][0, 0] += 0.01
    result = diagnostic.summarize_cell(
        raw["raw"], raw["traces"], summary["reobserved_controls"], summary["historical_controls"]
    )
    assert not result["historical_original_logits"]["exact"]
    assert result["historical_control_reproduction_exact"]
    assert result["promotion"] == "BLOCKED_CONTROL_REPRODUCTION_MISMATCH"


def test_repeat_delta_change_is_visible_even_if_head_same(cell):
    raw, summary = cell
    raw["raw"]["original_1_delta"][0, 0, 0] += 0.01
    result = diagnostic.summarize_cell(
        raw["raw"], raw["traces"], summary["reobserved_controls"], summary["historical_controls"]
    )
    assert result["same_input_repeats"]["original"]["exact"]
    assert not result["same_input_delta_repeats"]["original"]["exact"]
    assert result["promotion"] == "BLOCKED_CONTROL_REPRODUCTION_MISMATCH"


def test_caller_source_bound_to_commit_and_current_bytes(tmp_path, monkeypatch):
    names = [diagnostic.ENTRY, "scripts/run_source_sealed.py"]
    for name in names:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("pass\n")
    hashes = {name: diagnostic.audit.sha(tmp_path / name) for name in names}
    source = {"commit": "1" * 40, "files": hashes, "aggregate_sha256": assay.digest(hashes)}
    seal = {"source_commit": "1" * 40, "source_hashes": hashes}

    def fake_git(*args):
        if args[0] == "ls-tree":
            return ("\n".join(names) + "\n").encode()
        if args[0] == "show":
            return b"pass\n"
        raise AssertionError(args)

    monkeypatch.setattr(diagnostic, "ROOT", tmp_path)
    monkeypatch.setattr(diagnostic.audit, "git", fake_git)
    diagnostic.verify_caller_source(source, seal)
    (tmp_path / names[0]).write_text("changed\n")
    with pytest.raises(ValueError, match="sealed source bytes differ"):
        diagnostic.verify_caller_source(source, seal)


def test_exclusive_tensor_artifact(tmp_path):
    path = tmp_path / "tensor.pt"
    diagnostic.save_tensor(path, {"x": torch.tensor([1])})
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        diagnostic.save_tensor(path, {"x": torch.tensor([2])})
    assert path.read_bytes() == before


def test_input_seal_records_every_file_and_rejects_symlinks(tmp_path):
    path = tmp_path / "one.json"
    path.write_text("{}")
    assert diagnostic.input_hashes(tmp_path) == {"one.json": diagnostic.audit.sha(path)}
    (tmp_path / "link.json").symlink_to(path)
    with pytest.raises(ValueError, match="symlink"):
        diagnostic.input_hashes(tmp_path)


@pytest.mark.parametrize(
    ("field", "value", "exception"),
    [
        ("elapsed_seconds", 900.1, TimeoutError),
        ("peak_rss_bytes", 4 * 1024**3 + 1, MemoryError),
        ("peak_cuda_allocated_bytes", 4 * 1024**3 + 1, MemoryError),
    ],
)
def test_original_fail_closed_resource_guard(field, value, exception, monkeypatch):
    guard = assay.ResourceGuard(diagnostic.PLAN, "cpu")
    snapshot = {"elapsed_seconds": 1.0, "peak_rss_bytes": 1024, "peak_cuda_allocated_bytes": 0}
    snapshot[field] = value
    monkeypatch.setattr(guard, "snapshot", lambda: snapshot)
    with pytest.raises(exception):
        guard()


def test_dry_run_does_not_forward_or_write(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [diagnostic.ENTRY])
    monkeypatch.setattr(diagnostic, "run", lambda *args: pytest.fail("Dry run must not execute"))
    diagnostic.main()
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "DRY_RUN_NO_FORWARDS"
    assert result["plan"]["fits_per_device"] == 12
    assert result["plan"]["control_atol"] == 1e-6
    assert result["plan"]["old_gate"] == {
        "status": "FAIL",
        "winner": "none",
        "non_regression": "NOT_ESTABLISHED",
    }


def test_sealed_execute_refuses_unisolated_python(tmp_path):
    with pytest.raises(ValueError, match="isolated"):
        diagnostic.sealed_guard(tmp_path / "missing.json")


def test_partial_terminal_not_replayed(tmp_path):
    (tmp_path / "FINISHED.json").write_text('{"status":"FAILED"}')
    with pytest.raises(ValueError, match="not complete"):
        diagnostic.verify(tmp_path)
