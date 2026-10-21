"""Device-aware read-only observation and actual runner tests, with BF16 kept."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch
from test_latent_workspace_stack import host_model

from latent_workspace import execution as ex
from latent_workspace import native_diagnostics as diag
from latent_workspace import native_evaluation as ev
from latent_workspace.native_memory import NativeMemoryCausalLM
from latent_workspace.optimizer_state import tree_hash

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_v22_diagnostics as runner  # noqa: E402


@pytest.fixture(autouse=True)
def threads():
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


@pytest.fixture
def device():
    return os.environ.get("LTWS_TEST_DEVICE", "cpu")


@pytest.mark.parametrize("kind", ["mistral", "olmo2", "gpt2", "scratch"])
@pytest.mark.parametrize("memory", [[], [5, 6]])
def test_observe_exact_forward_and_fp32_no_mutation(kind, memory, device):
    graph = NativeMemoryCausalLM(host_model(kind).to(device=device, dtype=torch.bfloat16), cut=1)
    before = tree_hash(graph.model.state_dict())
    batch = ev.tensor_batch([1, 8, 9], memory, device, [3, 2])
    with torch.no_grad():
        reference = graph(**batch)
    head = graph.host.head.weight.detach().float()
    output, hidden, native, fp32 = diag.observe(graph, batch, [2, 3], head)
    assert torch.equal(output.logits, reference.logits)
    assert torch.equal(output.loss_sum, reference.loss_sum)
    assert torch.equal(native, reference.logits[:, [2, 3]])
    bias = graph.host.head.bias
    expected = torch.nn.functional.linear(
        hidden.float(), head, None if bias is None else bias.float()
    )
    assert torch.equal(fp32, expected)
    assert hidden.dtype == native.dtype == torch.bfloat16 and fp32.dtype == torch.float32
    assert hidden.device.type == device
    assert not graph.host.head._forward_pre_hooks
    assert all(p.grad is None for p in graph.parameters())
    assert tree_hash(graph.model.state_dict()) == before


def test_hook_cleanup_on_failure(device, monkeypatch):
    graph = NativeMemoryCausalLM(host_model("mistral").to(device), cut=1)

    def fail(**kwargs):
        raise RuntimeError("deliberate")

    monkeypatch.setattr(graph, "forward", fail)
    with pytest.raises(RuntimeError, match="deliberate"):
        diag.observe(graph, ev.tensor_batch([1], [], device), [0], graph.host.head.weight.float())
    assert not graph.host.head._forward_pre_hooks


@pytest.mark.parametrize("positions", [[], [-1], [2]])
def test_positions_reject_invalid(positions, device):
    graph = NativeMemoryCausalLM(host_model("mistral").to(device), cut=1)
    with pytest.raises(ValueError, match="positions"):
        diag.observe(
            graph, ev.tensor_batch([1, 2], [], device), positions, graph.host.head.weight.float()
        )


def test_token_rank_ties_and_finite(device):
    result = diag.token_score(torch.tensor([2.0, 2.0, 0.0], device=device), 1)
    assert result["top1"] == 0 and result["gold_rank"] == 1 and result["top_ties"] == 2
    assert not result["correct"] and result["gold_margin"] == 0
    with pytest.raises(ValueError, match="Finite"):
        diag.token_score(torch.tensor([float("nan")], device=device), 0)


def test_subulp_change_and_reduction_chunking():
    a = torch.tensor([1.0, 2.0, 0.0], dtype=torch.bfloat16)
    master = a.float() + torch.tensor([0.0001, 0.1, 0.25])
    native = master.bfloat16()
    x = diag.weight_delta(a, native, master, chunk=1)
    y = diag.weight_delta(a, native, master, chunk=3)
    assert x["native_changed"] == 2 and x["master_changed"] == 3
    assert x["master_changed_native_unchanged"] == 1
    for key in ("original_sq", "native_delta_sq", "master_delta_sq", "cast_error_sq"):
        assert x[key] == pytest.approx(y[key])
    with pytest.raises(ValueError, match="cast census"):
        diag.weight_delta(a, a, master)


@pytest.mark.parametrize(
    "gold,observed,index",
    [([1, 2], [1, 2], None), ([1, 2], [1, 3], 1), ([1, 2], [1], 1), ([1], [1, 2], 1)],
)
def test_first_difference_retains_caps_and_eos(gold, observed, index):
    assert diag.first_difference(gold, observed) == index


def test_frozen_plan_and_real_runner_two_roles(tmp_path, monkeypatch, device):
    runner.validate(ex.read(ROOT / runner.PLAN))
    graph = NativeMemoryCausalLM(
        host_model("mistral").to(device=device, dtype=torch.bfloat16), cut=1
    )
    tokenizer = SimpleNamespace(decode=lambda ids: str(ids))
    old = {"world_routes": ["latent", "inline"]}
    data = dict(
        mmlu=[dict(id="m", subject="tiny", input_ids=[1, 3, 4], choice_ids=[2, 3, 4, 5], target=0)],
        worlds=[
            dict(
                row_id="w",
                group_id="g",
                family="location",
                split="test",
                mode="affected",
                prefixes=dict(latent=[1, 3], inline=[1, 4, 5]),
                memory_ids=[8, 9],
                answer_ids=[4, 2],
                answer="x",
            )
        ],
    )
    prior = tmp_path / "prior"
    for role in runner.ROLES:
        folder = prior / "raw" / role
        folder.mkdir(parents=True)
        with (folder / "mmlu.jsonl").open("x") as stream, torch.no_grad():
            for row in data["mmlu"]:
                logits = graph(**ev.tensor_batch(row["input_ids"], [], device)).logits[0, -1]
                runner.previous.append(
                    stream,
                    dict(
                        id=row["id"], **ev.score_choices(logits, row["choice_ids"], row["target"])
                    ),
                )
        with (folder / "worlds.jsonl").open("x") as stream, torch.no_grad():
            for row in data["worlds"]:
                for route in old["world_routes"]:
                    memory = row["memory_ids"] if route == "latent" else []
                    output = graph(
                        **ev.tensor_batch(row["prefixes"][route], memory, device, row["answer_ids"])
                    )
                    generated = ev.generate(
                        graph,
                        row["prefixes"][route],
                        memory,
                        seed=7,
                        cap=3,
                        eos=2,
                        temperature=0,
                        top_p=1,
                        guard=lambda _: None,
                    )
                    runner.previous.append(
                        stream,
                        dict(
                            id=row["row_id"],
                            route=route,
                            teacher=dict(
                                nll_sum=float(output.loss_sum),
                                supervised_tokens=output.supervised_tokens,
                            ),
                            text="tiny",
                            exact_match=False,
                            **generated,
                        ),
                    )
    monkeypatch.setattr(runner, "load_inputs", lambda plan: (old, data, {}, {}))
    monkeypatch.setattr(
        runner.previous,
        "prepare",
        lambda *args: (graph, tokenizer, lambda _: None, tree_hash(graph.model.state_dict())),
    )
    monkeypatch.setattr(
        runner, "original_tensor", lambda *args: graph.host.head.weight.detach().cpu()
    )
    monkeypatch.setattr(runner, "census", lambda *args: 291)
    monkeypatch.setattr(runner.common, "engine_imports", lambda seal: {})
    monkeypatch.setattr(runner.common, "peak", lambda: {})

    # Real-run body must never generate a continuation, save weights or backpropagate.
    def forbidden(*args, **kwargs):
        raise AssertionError("diagnostics attempted mutation/generation")

    monkeypatch.setattr(ev, "generate", forbidden)
    monkeypatch.setattr(torch, "save", forbidden)
    monkeypatch.setattr(torch.Tensor, "backward", forbidden)
    for role in runner.ROLES:
        output = tmp_path / role
        output.mkdir()
        outcome = runner.run(
            None, SimpleNamespace(role=role, output=output), dict(comparison_bundle=str(prior)), {}
        )
        assert outcome["mmlu_rows"] == 1 and outcome["world_rows"] == 2
        assert outcome["replay_disagreements"] == 0 and outcome["new_sequences"] == 0
        ex.write_new(
            output / "FINISHED.json",
            dict(status="V22_DIAGNOSTIC_ARM_COMPLETE", files=ex.manifest(output)),
        )
    mmlu = runner.journal(tmp_path / "v22/mmlu.jsonl")[0]
    assert len(mmlu["head_factorial"]) == 4
    for cell in mmlu["head_factorial"].values():
        assert cell["logits"] == mmlu["fp32_head"]["logits"] or all(
            abs(a - b) < 1e-5 for a, b in zip(cell["logits"], mmlu["fp32_head"]["logits"])
        )


def test_census_uses_exact_original_master_projection(tmp_path, monkeypatch):
    graph = NativeMemoryCausalLM(host_model("mistral").to(dtype=torch.bfloat16), cut=1)
    named = dict(graph.model.named_parameters())
    checkpoint = tmp_path / "checkpoints"
    checkpoint.mkdir()
    torch.save(dict(masters={n: p.float() for n, p in named.items()}), checkpoint / "tiny.pt")
    monkeypatch.setattr(runner, "original_tensor", lambda plan, name: named[name].detach().clone())
    count = runner.census(
        graph,
        {},
        dict(training_bundle=str(tmp_path), checkpoint=dict(name="tiny.pt")),
        tmp_path,
        lambda _: None,
    )
    assert count == len(named)
    assert all(
        r["native_changed"] == r["master_changed"] == 0
        for r in runner.journal(tmp_path / "weights.jsonl")
    )
