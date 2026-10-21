"""Portable state interventions, fail-closed banks and actual finite runner."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch
from test_latent_workspace_stack import host_model
from test_native_causality import fixture_rows

from latent_workspace import execution as ex
from latent_workspace import native_causality as ca
from latent_workspace import native_evaluation as ev
from latent_workspace.native_memory import NativeMemoryCausalLM
from latent_workspace.optimizer_state import tree_hash
from latent_workspace.state_factorial import cut_state_logits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_v23_state_factorial as runner  # noqa: E402


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
def test_full_logits_self_parity_and_read_only(kind, dtype, memory, device):
    graph = NativeMemoryCausalLM(host_model(kind).to(device=device, dtype=dtype), cut=1).eval()
    before = tree_hash(graph.model.state_dict())
    batch = ev.tensor_batch([1, 5, 6, 7], memory, device)
    with torch.no_grad():
        query = graph.host.to_cut(batch["input_ids"], batch["attention_mask"], graph.cut)
        states = (
            graph.host.to_cut(batch["memory_ids"], batch["memory_mask"], graph.cut)
            if memory
            else None
        )
        expected = graph(**batch).logits
        assert torch.equal(cut_state_logits(graph, query, states), expected)
        assert torch.equal(graph(**batch).logits, expected)
    assert tree_hash(graph.model.state_dict()) == before
    assert all(p.grad is None for p in graph.parameters())


@pytest.mark.parametrize("kind", ["mistral", "olmo2", "gpt2", "scratch"])
def test_query_and_memory_replacements_are_independent(kind, device):
    graph = NativeMemoryCausalLM(host_model(kind).to(device), cut=1).eval()
    with torch.no_grad():
        batches = [ev.tensor_batch([1, 5 + i, 7], [8, 9 + i], device) for i in (0, 1)]
        query = [graph.host.to_cut(b["input_ids"], b["attention_mask"], 1) for b in batches]
        mem = [graph.host.to_cut(b["memory_ids"], b["memory_mask"], 1) for b in batches]
        cells = {(w, q): cut_state_logits(graph, query[q], mem[w]) for w in (0, 1) for q in (0, 1)}
        assert torch.equal(cells[0, 0], graph(**batches[0]).logits)
        assert torch.equal(cells[1, 1], graph(**batches[1]).logits)
        assert not torch.equal(cells[0, 0], cells[0, 1])
        assert not torch.equal(cells[0, 0], cells[1, 0])
        # Query alone is never secretly re-encoded by the current reader.
        assert not torch.equal(cut_state_logits(graph, query[0]), cut_state_logits(graph, query[1]))


@pytest.mark.parametrize("bad", ["shape", "dtype", "nan", "grad", "empty", "batch"])
def test_invalid_state_rejected(bad, device):
    graph = NativeMemoryCausalLM(host_model("mistral").to(device), cut=1).eval()
    states = torch.zeros(1, 2, graph.host.hidden_size, device=device)
    if bad == "shape":
        states = states[..., :1]
    elif bad == "dtype":
        states = states.double()
    elif bad == "nan":
        states[0, 0, 0] = float("nan")
    elif bad == "grad":
        states.requires_grad_(True)
    elif bad == "empty":
        states = states[:, :0]
    elif bad == "batch":
        states = states.expand(2, -1, -1)
    with torch.no_grad(), pytest.raises(ValueError, match="Invalid query"):
        cut_state_logits(graph, states)


def test_no_training_or_enabled_grad(device):
    graph = NativeMemoryCausalLM(host_model("mistral").to(device), cut=1)
    states = torch.zeros(1, 2, graph.host.hidden_size, device=device)
    with torch.no_grad(), pytest.raises(ValueError, match="Read-only"):
        cut_state_logits(graph, states)
    graph.eval()
    with pytest.raises(ValueError, match="Read-only"):
        cut_state_logits(graph, states)


def test_frozen_denominators_and_answer_blind_extents():
    runner.validate(ex.read(ROOT / runner.PLAN))
    data = ex.read_gz(
        ROOT / "provenance/pilots/v22_base_comparison01_20261021/furnace/inputs/INPUTS.json.gz"
    )
    items = list(runner.cases(data))
    world = [i for i in items if i["kind"] == "world"]
    assert len(items) == 1193 and len(world) == 623
    assert sum(bool(i["memory"]) for i in world) == 559
    rows = {r["row_id"]: r for r in data["worlds"]}
    for item in world:
        row = rows[item["id"]]
        assert item["query"] == row["prefixes"]["latent"] + row["answer_ids"][: item["index"]]
    # Conservative raw, non-deduplicated bank allocation stays below 7 GiB.
    assert 2 * sum(len(v) * 4096 * 2 for v in runner.bank_inputs(items).values()) < 7 * 2**30


def test_actual_three_role_runner_no_generation_update_or_save(tmp_path, monkeypatch, device):
    graph = NativeMemoryCausalLM(
        host_model("mistral").to(device=device, dtype=torch.bfloat16), cut=1
    ).eval()
    data = dict(
        worlds=fixture_rows(),
        mmlu=[
            dict(id="m1", input_ids=[1, 5, 6], choice_ids=[7, 8, 9, 10], target=0, subject="tiny")
        ],
    )
    items = list(runner.cases(data))
    history = ({}, {})
    with torch.no_grad():
        for item in items:
            last = graph(**ev.tensor_batch(item["query"], item["memory"], device)).logits[0, -1]
            if item["kind"] == "world":
                history[0][item["id"], item["index"]] = ca.tensor_digest(last)
            else:
                history[1][item["id"]] = ev.score_choices(last, item["choice_ids"], item["target"])
    monkeypatch.setattr(runner.prior_diag, "load_inputs", lambda p: ({}, data, {}, {}))
    monkeypatch.setattr(
        runner.previous,
        "prepare",
        lambda *a: (graph, None, lambda _: None, tree_hash(graph.model.state_dict())),
    )
    monkeypatch.setattr(runner, "historical", lambda *a: history)
    monkeypatch.setattr(runner.common, "engine_imports", lambda s: {})
    monkeypatch.setattr(runner.common, "peak", lambda: {})

    def forbidden(*a, **kw):
        raise AssertionError("Forbidden generation, backprop or checkpoint")

    monkeypatch.setattr(torch, "save", forbidden)
    monkeypatch.setattr(torch.Tensor, "backward", forbidden)
    monkeypatch.setattr(ev, "generate", forbidden)
    outcomes = []
    for role in runner.ROLES:
        output = tmp_path / role
        output.mkdir()
        outcomes.append(runner.run(None, SimpleNamespace(role=role, output=output), {}, {}))
        ex.write_new(
            output / "FINISHED.json", dict(status=runner.STATUS, files=ex.manifest(output))
        )
    assert [r["world_cells"] for r in outcomes] == [8, 32, 32]
    assert [r["mmlu_cells"] for r in outcomes] == [1, 2, 2]
    assert [r["full_self_parity"] for r in outcomes] == [9, 9, 0]
    assert outcomes[-1]["repeated_self_parity"] == 9
    assert all(
        r["new_sequences"] == r["native_weight_updates"] == r["checkpoint_saves"] == 0
        for r in outcomes
    )
    changed = [dict(i) for i in items]
    changed[0]["query"] = [1, 2, 3]
    with pytest.raises(ValueError, match="token inputs"):
        runner.verify_bank(tmp_path / "base", changed)
    with pytest.raises(ValueError, match="Exclusive"):
        runner.encode_bank(graph, items, tmp_path / "base", lambda _: None)
    # A modified body is detected before any intervention is used.
    path = tmp_path / "base/cut_states.safetensors"
    with path.open("ab") as stream:
        stream.write(b"corruption")
    with pytest.raises(ValueError, match="role seal"):
        runner.verify_bank(tmp_path / "base", items)
