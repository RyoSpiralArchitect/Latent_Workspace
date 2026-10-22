"""Device-aware BF16/FP32 causal controls and actual three-role runner coverage."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch
from test_latent_workspace_stack import host_model

from latent_workspace import execution as ex
from latent_workspace import native_causality as ca
from latent_workspace import native_evaluation as ev
from latent_workspace.native_memory import NativeMemoryCausalLM
from latent_workspace.optimizer_state import tree_hash

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_v22_causality as runner  # noqa: E402


@pytest.fixture(autouse=True)
def threads():
    old = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(old)


@pytest.fixture
def device():
    return os.environ.get("LTWS_TEST_DEVICE", "cpu")


@pytest.mark.parametrize("kind", ["mistral", "olmo2", "gpt2", "scratch"])
@pytest.mark.parametrize("dtype", [torch.bfloat16, torch.float32])
@pytest.mark.parametrize("memory", [[], [8, 9, 10]])
def test_fixed_extent_future_causality_and_prefix_layout(kind, dtype, memory, device):
    graph = NativeMemoryCausalLM(host_model(kind).to(device=device, dtype=dtype), cut=1).eval()
    prefix, gold = [1, 5, 6], [7, 8, 2]
    with torch.no_grad():
        full = graph(**ev.tensor_batch(prefix + gold, memory, device)).logits
        for j in range(len(gold)):
            variants = ca.prefix_variants(prefix, gold, j, memory, device, 43)
            for name, batch in variants.items():
                value = graph(**batch).logits[0, len(prefix) + j - 1]
                delta = ca.difference(full[0, len(prefix) + j - 1], value)
                if name == "changed_future":
                    assert delta["exact"]
                    assert torch.equal(
                        batch["input_ids"][:, : len(prefix) + j],
                        torch.tensor([prefix + gold[:j]], device=device),
                    )
                else:
                    assert delta["max_abs"] >= 0  # Extent is measured, never forced equal.


@pytest.mark.parametrize("kind", ["mistral", "olmo2", "gpt2", "scratch"])
@pytest.mark.parametrize("dtype", [torch.bfloat16, torch.float32])
def test_identity_and_same_writer_replacement_are_exact(kind, dtype, device):
    graph = NativeMemoryCausalLM(host_model(kind).to(device=device, dtype=dtype), cut=1).eval()
    before = tree_hash(graph.model.state_dict())
    batch = ev.tensor_batch([1, 5, 6, 7], [8, 9, 10], device)
    with torch.no_grad():
        value = graph(**batch).logits
        states = graph.host.to_cut(batch["memory_ids"], batch["memory_mask"], graph.cut)
        for mode, replacement in (("identity", None), ("replacement", states)):
            probe = ca.MemoryProbe(graph, mode=mode, replacement=replacement)
            assert torch.equal(probe(**batch).logits, value)
        for mode in ("zero", "reverse"):
            changed = ca.MemoryProbe(graph, mode=mode)(**batch).logits
            assert changed.shape == value.shape and torch.isfinite(changed).all()
        assert torch.equal(graph(**batch).logits, value)
    assert all(p.grad is None for p in graph.parameters())
    assert tree_hash(graph.model.state_dict()) == before


def test_probe_rejects_training_grad_and_bad_replacement(device):
    graph = NativeMemoryCausalLM(host_model("mistral").to(device), cut=1)
    batch = ev.tensor_batch([1, 5], [8, 9], device)
    with torch.no_grad(), pytest.raises(ValueError, match="Read-only"):
        ca.MemoryProbe(graph)(**batch)
    graph.eval()
    with pytest.raises(ValueError, match="Read-only"):
        ca.MemoryProbe(graph)(**batch)
    with torch.no_grad(), pytest.raises(ValueError, match="replacement"):
        ca.MemoryProbe(graph, mode="replacement", replacement=torch.ones(1, 1, 1, device=device))(
            **batch
        )
    with pytest.raises(ValueError, match="Replacement"):
        ca.MemoryProbe(graph, replacement=torch.ones(1))


def fixture_rows():
    return [
        dict(
            row_id=f"g/s{side}/{mode}",
            group_id="g",
            side=side,
            mode=mode,
            family="location",
            split="test",
            memory_ids=[8, 9 + side],
            prefixes=dict(latent=[1, 5], inline=[1, 8, 9 + side, 5]),
            answer_ids=[6 + side if mode == "affected" else 7, 2],
            answer=str(6 + side if mode == "affected" else 7),
        )
        for side in (0, 1)
        for mode in ("affected", "unaffected")
    ]


def test_twin_requires_identical_question_and_reciprocal_oracle():
    rows = fixture_rows()
    assert len(runner.twins(rows)) == 4
    rows[2]["prefixes"]["latent"] = [1, 6]
    with pytest.raises(ValueError, match="Identical query"):
        runner.twins(rows)


def test_frozen_input_denominators():
    runner.validate(ex.read(ROOT / runner.PLAN))
    rows = ex.read_gz(
        ROOT / "provenance/pilots/v22_base_comparison01_20261021/furnace/inputs/INPUTS.json.gz"
    )["worlds"]
    paired = runner.twins(rows)
    assert len(rows) == 96 and sum(bool(r["memory_ids"]) for r in rows) == 80
    assert len(paired) == 64
    assert sum(len(r["answer_ids"]) for r in rows) * 4 == 2492
    matched = {
        r["group_id"]
        for r in rows
        if r["mode"] == "affected"
        and len(r["memory_ids"]) == len(paired[r["row_id"]]["memory_ids"])
    }
    assert len(matched) == 10


def test_actual_three_role_runner_and_exclusive_bank(tmp_path, monkeypatch, device):
    graph = NativeMemoryCausalLM(
        host_model("mistral").to(device=device, dtype=torch.bfloat16), cut=1
    ).eval()
    rows = fixture_rows()
    data, old = dict(worlds=rows), {}
    prior = tmp_path / "prior"
    for role in ("base", "v22"):
        folder = prior / "raw" / role
        folder.mkdir(parents=True)
        with (folder / "worlds.jsonl").open("x") as stream:
            for row in rows:
                generated = ev.generate(
                    graph,
                    row["prefixes"]["latent"],
                    row["memory_ids"],
                    seed=7,
                    cap=3,
                    eos=2,
                    temperature=0,
                    top_p=1,
                    guard=lambda _: None,
                )
                runner.previous.append(stream, dict(id=row["row_id"], route="latent", **generated))
    monkeypatch.setattr(runner.prior_diag, "load_inputs", lambda p: (old, data, {}, {}))
    monkeypatch.setattr(
        runner.previous,
        "prepare",
        lambda *a: (
            graph,
            SimpleNamespace(decode=lambda ids, **kw: str(ids)),
            lambda _: None,
            tree_hash(graph.model.state_dict()),
        ),
    )
    monkeypatch.setattr(runner.common, "engine_imports", lambda s: {})
    monkeypatch.setattr(runner.common, "peak", lambda: {})

    def forbidden(*a, **kw):
        raise AssertionError("Causality probe attempted weight save/backprop")

    monkeypatch.setattr(torch, "save", forbidden)
    monkeypatch.setattr(torch.Tensor, "backward", forbidden)
    plan = dict(
        comparison_bundle=str(prior),
        conditions=["identity", "empty", "zero", "reverse", "twin"],
        generation=dict(seed=7, max_new_tokens=3),
    )
    counts = []
    for role in runner.ROLES:
        output = tmp_path / role
        output.mkdir()
        result = runner.run(None, SimpleNamespace(role=role, output=output), plan, {})
        counts.append(result["new_sequences"])
        ex.write_new(
            output / "FINISHED.json", dict(status=runner.STATUS, files=ex.manifest(output))
        )
    assert counts == [20, 24, 4]
    with pytest.raises(ValueError, match="Exclusive"):
        runner.encode_bank(graph, rows, tmp_path / "base", lambda _: None)
    assert len(runner.foreign_bank(tmp_path / "v22")[1]) == 4


def test_future_gate_stops_before_generation(tmp_path, device):
    class Leaky(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.anchor = torch.nn.Parameter(torch.zeros(1, device=device))
            self.host = SimpleNamespace(head=SimpleNamespace(out_features=43))

        def forward(self, input_ids, **kw):
            values = torch.arange(43, device=device).float()
            # Deliberate dependence on the final future token.
            logits = values[None, None].expand(1, input_ids.shape[1], -1) * input_ids[0, -1]
            return SimpleNamespace(logits=logits)

    with pytest.raises(ValueError, match="future content"):
        runner.instrument(Leaky(), fixture_rows()[:1], tmp_path, lambda _: None)
    assert ex.read(tmp_path / "PREFIX_GATE.json")["gate"] == "FAIL"
    assert not (tmp_path / "interventions.jsonl").exists()
