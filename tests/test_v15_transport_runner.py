"""CPU-only integration checks for the no-update V15 transport assay."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_v15_readout_transport as runner  # noqa: E402

from latent_workspace_ft_v10.precision_bridge import PrecisionAwareWorkspaceBridge  # noqa: E402
from latent_workspace_ft_v10.reader_query import QuestionSpan  # noqa: E402
from latent_workspace_ft_v10.v15_pipeline import NativeWorkspacePipeline  # noqa: E402
from latent_workspace_ft_v10.v15_readout import NativeWorkspaceReadout  # noqa: E402


class ToyStore:
    device = torch.device("cpu")
    candidate_ids = (2, 11)
    features = [0, 1]

    def __init__(self, dtype):
        self.records = [
            {
                "answers": [[1, 0, 1, 0, 1, 0, 1, 0], [0, 1, 1, 0, 1, 0, 1, 0]],
                "affected": [True, True, False, False, False, False, False, False],
            }
            for _ in range(2)
        ]
        generator = torch.Generator().manual_seed(127)
        self.hidden = {
            (world, query): torch.randn(1, 5, 8, generator=generator).to(dtype)
            for world in range(2)
            for query in range(8)
        }
        self.contexts = {
            (world, side): torch.randn(1, 4, 8, generator=generator).to(dtype)
            for world in range(2)
            for side in (0, 1, "unrelated", "different_schema")
        }
        self.spans = {
            (world, query): QuestionSpan(
                question="Toy question?",
                character_start=0,
                character_end=13,
                token_indices=(1, 2),
                prefix_ids=self.prefix(world, query),
                rendered_prefix_sha256="a" * 64,
            )
            for world in range(2)
            for query in range(8)
        }

    @staticmethod
    def prefix(feature, query):
        return (1, 3, 4, feature + 5, query + 7)

    def query(self, world, query):
        return self.hidden[world, query]

    def context(self, world, side):
        return self.contexts[world, side]

    def ordered_context(self, world, side, order):
        # Distinct frozen features stand in for each independently encoded text.
        offsets = {"original": 0, "canonical": 0.1, "canonical_reverse": -0.1}
        return self.context(world, side) + offsets[order]


def fixture(dtype=torch.float32):
    with torch.random.fork_rng():
        torch.manual_seed(31)
        head = torch.nn.Linear(8, 17, bias=False).to(dtype).requires_grad_(False)
        readout = NativeWorkspaceReadout(head)
        pipelines = {}
        for mode in runner.MODES:
            bridge = PrecisionAwareWorkspaceBridge(8, workspace_dim=4, heads=2, slots=3)
            torch.nn.init.normal_(bridge.up.weight, std=0.1)
            pipelines[mode] = NativeWorkspacePipeline(bridge.eval(), readout, mode)
    return ToyStore(dtype), readout, pipelines


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_actual_native_gradient_gate_preserves_bridge_and_frozen_head(monkeypatch, dtype):
    store, readout, pipelines = fixture(dtype)
    before = {name: runner.prior.state_hash(pipe.bridge) for name, pipe in pipelines.items()}
    head_before = runner.prior.state_hash(readout.head)
    monkeypatch.setattr(
        readout, "legacy_fp32_choices", lambda *a: pytest.fail("Legacy diagnostic used as loss")
    )
    report = runner.gradient_gate(pipelines, store, readout)
    assert set(report) == set(runner.MODES)
    for mode, data in report.items():
        assert data["optimizer_steps"] == 0 and data["unchanged"] is True
        assert len(data["rows"]) == 2
        assert all(row["native_train_eval_logits_exact"] for row in data["rows"])
        for row in data["rows"]:
            assert set(row["losses"]) == {"native_two_choice_ce", "native_full_vocab_ce"}
            for value in row["losses"].values():
                norms = value["parameter_gradient_l2"]
                assert norms["up.weight"] > 0
                assert norms["query_projection.weight"] > 0
                assert norms["writer.context_projection.weight"] > 0
        assert not pipelines[mode].bridge.training
        assert before[mode] == runner.prior.state_hash(pipelines[mode].bridge)
        assert all(parameter.grad is None for parameter in pipelines[mode].bridge.parameters())
    assert head_before == runner.prior.state_hash(readout.head)
    assert all(parameter.grad is None for parameter in readout.head.parameters())


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_complete_384_row_crossover_with_real_bridge_native_head_and_summary(dtype):
    store, readout, pipelines = fixture(dtype)
    before = {name: runner.prior.state_hash(pipe.bridge) for name, pipe in pipelines.items()}
    phases = []
    report = runner.evaluate(pipelines, store, readout, phases.append)
    assert len(report["rows"]) == 384
    assert report["shared_historical_native_full_logit_exact_checks"] == 384
    assert report["zero_checks"] == 32
    assert report["summary"]["row_count"] == 384
    assert len(phases) == 32 and len(set(phases)) == 32
    zero = [row for row in report["rows"] if row["memory_key"] == "zero"]
    assert len(zero) == 32
    assert all(row["native"] == row["base_native"] for row in zero)
    assert all(row["fp32"] == row["base_fp32"] for row in zero)
    assert all(row["delta_l2"] == row["native_applied_delta_l2"] == 0 for row in zero)
    assert all(row["transport"]["max_abs_logit_change"] == 0 for row in zero)
    assert before == {
        name: runner.prior.state_hash(pipe.bridge) for name, pipe in pipelines.items()
    }


def test_historical_native_mismatch_fails_closed(monkeypatch):
    store, readout, pipelines = fixture()
    original = runner.native_full_readout

    def corrupted(*args):
        logits, trace = original(*args)
        return logits + 1, trace

    monkeypatch.setattr(runner, "native_full_readout", corrupted)
    with pytest.raises(RuntimeError, match="Shared/historical"):
        runner.evaluate(pipelines, store, readout, lambda phase: None)


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@torch.no_grad()
def test_generation_backend_uses_current_final_and_bound_original_mean(dtype):
    store, readout, pipelines = fixture(dtype)
    banks = {
        mode: runner.memories(pipe.bridge, store, 0, store.device)
        for mode, pipe in pipelines.items()
    }
    span = store.spans[0, 0]
    initial = store.query(0, 0)
    extended = torch.cat((initial, torch.full((1, 2, 8), 10, dtype=dtype)), dim=1)
    prefix = (*span.prefix_ids, 15, 16)
    captured = {}
    for mode, pipe in pipelines.items():
        original = pipe.bridge.read_delta

        def capture(query, memory, mask, *, name=mode, call=original):
            captured[name] = query.detach().clone()
            return call(query, memory, mask)

        pipe.bridge.read_delta = capture
    backend = runner.GenerationBackend(None, readout, pipelines, banks, span)
    final_delta = backend.delta("final_intact", extended, prefix)
    mean_delta = backend.delta("mean_intact", extended, prefix)
    assert torch.equal(captured["final"], extended[:, -1:].float())
    assert torch.equal(captured["mean_span"], initial[:, [1, 2]].float().mean(1, keepdim=True))
    assert not torch.equal(captured["final"], captured["mean_span"])
    assert torch.equal(
        backend.readout(extended, final_delta).logits, readout(extended, final_delta).logits
    )
    assert torch.equal(
        backend.readout(extended, mean_delta).logits, readout(extended, mean_delta).logits
    )
    assert backend.parity_checks == 2
    for condition in ("final_zero", "mean_zero"):
        delta = backend.delta(condition, extended, prefix)
        assert torch.count_nonzero(delta) == 0
        assert torch.equal(backend.readout(extended, delta).logits, readout.head(extended))


def test_generation_encoder_disables_cache_and_retains_full_prefix():
    calls = []

    def encode(ids, **kwargs):
        calls.append((ids.tolist(), kwargs))
        return SimpleNamespace(last_hidden_state=torch.ones(1, ids.shape[1], 8))

    base = SimpleNamespace(device=torch.device("cpu"), model=encode)
    backend = runner.GenerationBackend(base, None, None, None, None)
    assert backend.encode((1, 2, 3)).shape == (1, 3, 8)
    assert calls[0][0] == [[1, 2, 3]]
    assert calls[0][1]["use_cache"] is False
    assert torch.equal(calls[0][1]["attention_mask"], torch.ones(1, 3, dtype=torch.long))


def test_real_predecessor_verified_dry_run_never_loads_model_or_initializes_cuda(monkeypatch):
    monkeypatch.setattr(runner.engine, "_load_hf_model", lambda *a: pytest.fail("Model load"))
    monkeypatch.setattr(torch.cuda, "get_device_properties", lambda *a: pytest.fail("CUDA use"))
    plan, _, records, _ = runner.validate()
    assert plan["optimizer_steps"] == 0
    assert len(records) == 2
    before = {path: runner.prior.digest(path) for path in (runner.PLAN, Path(runner.__file__))}
    result = subprocess.run(
        [sys.executable, str(Path(runner.__file__)), "--dry-run"],
        cwd=runner.REPO,
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(result.stdout) == {"status": "PREPARED_NOT_RUN"}
    assert before == {path: runner.prior.digest(path) for path in before}


@pytest.mark.parametrize(
    "path,replacement",
    [
        (("generation", "worlds"), [1, 2]),
        (("generation", "queries"), [2, 3]),
        (("generation", "side"), 1),
        (("generation", "max_new_tokens"), 128),
        (("generation", "conditions"), ["base", "final_intact"]),
        (("generation", "regimes"), [{"id": "other", "seed": 9, "temperature": 1.0}]),
        (("resources", "allocator_cap_gib"), 24),
        (("model_parent",), "other.json"),
        (("mean_reduction",), "CUDA FP32"),
    ],
)
def test_bounded_contract_rejects_changed_generation_or_resources(
    monkeypatch, tmp_path, path, replacement
):
    plan = json.loads(runner.PLAN.read_text())
    modified = copy.deepcopy(plan)
    node = modified
    for part in path[:-1]:
        node = node[part]
    node[path[-1]] = replacement
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(modified))
    monkeypatch.setattr(runner, "PLAN", changed)
    with pytest.raises(ValueError, match="contract"):
        runner.validate()
