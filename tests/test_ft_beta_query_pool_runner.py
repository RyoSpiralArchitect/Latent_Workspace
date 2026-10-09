"""CPU-only contracts for the additive tiny query-pooling runner."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
import torch
from torch.nn import functional as F

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_ft_beta_query_pool as runner  # noqa: E402

CONTRACT = {
    "donor_margin": 0.25,
    "direction_weight": 0.7,
    "stability_weight": 0.3,
    "unrelated_weight": 0.2,
    "residual_penalty": 0.01,
    "seed": 123,
    "learning_rate": 1e-3,
    "weight_decay": 0.0,
    "max_grad_norm": 1.0,
}


class ToyStore:
    features = [{}, {}]

    def __init__(self):
        self.records = [
            {"answers": [[1, 0, 1, 0, 1, 0, 1, 0], [0, 1, 1, 0, 1, 0, 1, 0]]} for _ in range(2)
        ]
        generator = torch.Generator().manual_seed(54)
        self.hidden = {
            (world, query): torch.randn(1, 4, 8, generator=generator)
            for world in range(2)
            for query in range(8)
        }
        self.contexts = {
            (world, side): torch.randn(1, 2 + world, 8, generator=generator)
            for world in range(2)
            for side in (0, 1, "unrelated")
        }
        for hidden in self.hidden.values():
            hidden[:, :2] += 10

    def query(self, world, query):
        return self.hidden[world, query]

    def reader_query(self, world, query, mode):
        hidden = self.query(world, query)
        return hidden[:, -1:] if mode == "final" else hidden[:, :2].mean(1, keepdim=True)

    def context(self, world, side):
        return self.contexts[world, side]


def fixture():
    with torch.random.fork_rng():
        torch.manual_seed(17)
        bridge = runner.PrecisionAwareWorkspaceBridge(8, workspace_dim=4, heads=2, slots=2)
        torch.nn.init.normal_(bridge.up.weight, std=0.03)
        head = torch.randn(2, 8)
    return bridge, ToyStore(), head


@pytest.mark.parametrize("mode", ["final", "mean_span"])
def test_batch_and_objective_keep_original_final_base_readout(monkeypatch, mode):
    bridge, store, head = fixture()
    batch = runner.batch_tensors(store, head, "cpu", mode)
    expected_base = torch.cat([store.query(w, q)[:, -1:] for w, q in batch["order"]])
    expected_query = torch.cat([store.reader_query(w, q, mode) for w, q in batch["order"]])
    assert torch.equal(batch["base"], expected_base)
    assert torch.equal(batch["query"], expected_query)
    if mode == "mean_span":
        assert not torch.equal(batch["base"], batch["query"])
    captured = {}
    original_reader = bridge.read_delta
    original_objective = runner.prior.objective

    def reader(query, memory, mask):
        captured["reader_query"] = query.detach().clone()
        captured["delta"] = original_reader(query, memory, mask)
        return captured["delta"]

    def objective(scores0, scores1, unrelated, base_scores, *args):
        captured["scores"] = (scores0, scores1, unrelated)
        captured["base_scores"] = base_scores
        return original_objective(scores0, scores1, unrelated, base_scores, *args)

    monkeypatch.setattr(bridge, "read_delta", reader)
    monkeypatch.setattr(runner.prior, "objective", objective)
    loss, components, donor = runner.objective_graph(bridge, batch, CONTRACT)
    assert torch.equal(captured["reader_query"], expected_query.repeat(3, 1, 1))
    scores = F.linear(expected_base.repeat(3, 1, 1) + captured["delta"], head).squeeze(1)
    torch.testing.assert_close(torch.cat(captured["scores"]), scores, rtol=0, atol=0)
    torch.testing.assert_close(
        captured["base_scores"],
        F.linear(expected_base + torch.zeros_like(expected_base), head).squeeze(1),
        rtol=0,
        atol=0,
    )
    assert loss is components["loss"] and donor.shape == (16,)
    loss.backward()
    assert any(p.grad is not None and p.grad.any() for p in bridge.writer.parameters())
    assert all(batch[key].grad is None for key in ("base", "query", "context", "head"))


def test_gradient_diagnostic_reconstructs_objective_without_updates_or_grad_writes():
    bridge, store, head = fixture()
    batch = runner.batch_tensors(store, head, "cpu", "mean_span")
    before = runner.prior.state_hash(bridge)
    report = runner.gradient_diagnostic(bridge, batch, CONTRACT)
    assert report["reconstruction"]["passed"] is True
    assert report["frozen_input_names"] == ["base", "context", "head", "query"]
    assert len(report["donor_margins"]) == 16
    assert report["terms"]["donor_even_hinge"]["included_in_objective"] is False
    assert report["terms"]["donor_odd_hinge"]["included_in_objective"] is False
    assert before == runner.prior.state_hash(bridge)
    assert all(parameter.grad is None for parameter in bridge.parameters())


def test_gradient_diagnostic_fails_closed_when_reconstruction_fails(monkeypatch):
    bridge, store, head = fixture()
    monkeypatch.setattr(
        runner, "audit_loss_gradients", lambda *a, **kw: {"reconstruction": {"passed": False}}
    )
    with pytest.raises(RuntimeError, match="no tolerance relaxation"):
        runner.gradient_diagnostic(
            bridge, runner.batch_tensors(store, head, "cpu", "final"), CONTRACT
        )


def test_train_diagnostic_supplies_complete_reader_panel_wrapper(monkeypatch, tmp_path):
    _, store, head = fixture()
    real_capture = runner.capture_reverse_panel

    class PanelChecked(Exception):
        pass

    def capture(bridge, wrapper, candidate_head, device, world_count):
        assert wrapper.features is store.features
        assert wrapper.records is store.records
        assert torch.equal(wrapper.query(0, 0), store.reader_query(0, 0, "mean_span"))
        panel = real_capture(bridge, wrapper, candidate_head, device, world_count=world_count)
        assert panel["summary"]["row_count"] == 32
        assert panel["summary"]["pair_count"] == 16
        # These head-axis statistics project delta, not a pooled-state baseline.
        assert panel["rows"][0]["head_axis_gap"] == 0
        raise PanelChecked

    monkeypatch.setattr(runner, "capture_reverse_panel", capture)
    monkeypatch.setattr(runner, "gradient_diagnostic", lambda *a: {"toy": True})
    parent = {"training": CONTRACT, "bridge": {"workspace_dim": 4, "heads": 2, "slots": 2}}
    with pytest.raises(PanelChecked):
        runner.train_mode("mean_span", store, None, head, parent, {}, tmp_path, lambda phase: None)


def test_real_dry_run_reads_only_and_preserves_source():
    sources = [runner.PLAN, Path(runner.__file__)]
    before = {str(path): runner.prior.digest(path) for path in sources}
    result = subprocess.run(
        [sys.executable, str(Path(runner.__file__)), "--dry-run"],
        cwd=runner.REPO,
        text=True,
        capture_output=True,
        check=True,
    )
    receipt = json.loads(result.stdout)
    assert receipt["status"] == "PREPARED_NOT_RUN" and receipt["worlds"] == 2
    assert {str(path): runner.prior.digest(path) for path in sources} == before


@pytest.mark.parametrize(
    ("key", "replacement"),
    [
        ("modes", ["mean_span", "final"]),
        ("world_indices", [1, 2]),
        ("query_indices", [0, 1]),
        ("primary_step", 128),
        ("checkpoint_steps", [256]),
        ("diagnostic_steps", [0, 256]),
    ],
)
def test_changed_fixed_contract_fails_without_model_load(monkeypatch, tmp_path, key, replacement):
    plan = json.loads(runner.PLAN.read_text())
    plan[key] = replacement
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(plan))
    monkeypatch.setattr(runner, "PLAN", changed)
    monkeypatch.setattr(
        runner.engine, "_load_hf_model", lambda *a: pytest.fail("No model load allowed")
    )
    with pytest.raises(ValueError, match="protocol changed"):
        runner.validate_contract()


def snapshot(free_gib, uuid="toy", *, other_pid=2222):
    return {
        "uuid": uuid,
        "free_bytes": free_gib * runner.GIB,
        "processes": [{"pid": other_pid, "bytes": runner.GIB}],
        "own_pid": 1111,
    }


@pytest.mark.parametrize("admission, free_gib", [(True, 19), (False, 3)])
def test_low_free_resource_guard_logs_and_aborts_only_own_run(
    monkeypatch, tmp_path, admission, free_gib
):
    state = snapshot(free_gib)
    before = copy.deepcopy(state["processes"])
    monkeypatch.setattr(runner, "resource_snapshot", lambda: copy.deepcopy(state))
    monkeypatch.setattr(torch.cuda, "is_initialized", lambda: False)
    monkeypatch.setattr(runner.os, "kill", lambda *a: pytest.fail("Other-job mutation"))
    guard = runner.ResourceGuard({"admission_free_gib": 20, "abort_free_gib": 4}, tmp_path)
    with pytest.raises(runner.ResourceAbort, match="stop own run only"):
        guard("toy_phase", admission=admission)
    saved = [json.loads(line) for line in (tmp_path / "RESOURCES.jsonl").read_text().splitlines()]
    assert len(saved) == 1 and saved[0]["phase"] == "toy_phase"
    assert state["processes"] == before == saved[0]["processes"]


def test_resource_guard_boundary_and_identity(monkeypatch, tmp_path):
    states = iter([snapshot(20), snapshot(4), snapshot(10, uuid="other")])
    monkeypatch.setattr(runner, "resource_snapshot", lambda: next(states))
    monkeypatch.setattr(torch.cuda, "is_initialized", lambda: False)
    guard = runner.ResourceGuard({"admission_free_gib": 20, "abort_free_gib": 4}, tmp_path)
    assert guard("admission", admission=True)["free_bytes"] == 20 * runner.GIB
    assert guard("step16")["free_bytes"] == 4 * runner.GIB
    with pytest.raises(runner.ResourceAbort, match="identity changed"):
        guard("step32")


def test_resource_snapshot_uses_only_read_queries(monkeypatch):
    commands = []

    def check_output(command, *, text):
        assert text is True and command[0] == "nvidia-smi"
        commands.append(command)
        if "--query-gpu=" in command[1]:
            return "GPU-toy, Toy GPU, 49152, 1024, 48128, 5\n"
        assert command[1] == "--query-compute-apps=pid,process_name,used_memory"
        return "9999, python, 1024\n"

    monkeypatch.setattr(runner.subprocess, "check_output", check_output)
    row = runner.resource_snapshot()
    assert len(commands) == 2
    assert row["free_bytes"] == 48128 * 1024**2
    assert row["processes"] == [{"pid": 9999, "process": "python", "bytes": runner.GIB}]


class OffsetTokenizer:
    """Character prompts with each binary answer suffix encoded as one token."""

    is_fast = True
    bos_token_id = None
    eos_token_id = None

    def convert_ids_to_tokens(self, ids):
        return [chr(value) if value < 1000 else str(value) for value in ids]

    def encode(self, text, add_special_tokens=False):
        for suffix, token in ((" no", 1000), (" yes", 1001)):
            if text.endswith(suffix):
                return [ord(c) for c in text[: -len(suffix)]] + [token]
        return [ord(c) for c in text]

    def __call__(self, text, **kwargs):
        return {
            "input_ids": self.encode(text),
            "offset_mapping": [(i, i + 1) for i in range(len(text))],
        }


def test_cuda_store_binding_is_cpu_testable_and_metadata_independent(monkeypatch):
    tokenizer = OffsetTokenizer()
    config = runner.engine.DataConfig(
        use_chat_template=False,
        add_bos=False,
        add_eos=False,
        functional_elicitation="symmetric_instruction",
        functional_query_max_length=512,
        functional_context_max_length=512,
        functional_inline_max_length=1024,
    )
    records = [
        {
            "queries": [f"Is A{q} above B{q}? Answer:" for q in range(8)],
            "contexts": ["Facts\n- A above B.", "Facts\n- B above A."],
            "answers": [[1, 0, 1, 0, 1, 0, 1, 0], [0, 1, 1, 0, 1, 0, 1, 0]],
            "affected": [True, True, False, False, False, False, False, False],
            "hop_distances": [1] * 8,
            "heldout_queries": [False] * 8,
            "choices": [" no", " yes"],
            "metadata": {"pair_id": str(world)},
        }
        for world in range(2)
    ]
    features = [runner.engine._encode_functional_world_pair(r, tokenizer, config) for r in records]
    store = runner.CUDAStore(
        records,
        features,
        tokenizer,
        None,
        None,
        torch.device("cpu"),
        data_config=config,
        guard=lambda *a: pytest.fail("No model feature capture allowed"),
    )
    assert len(store.span_receipts) == 16
    assert all(
        row["metadata_permutations_prefix_equal"] == ["answers", "side", "query_order", "metadata"]
        for row in store.span_receipts
    )
    prefix = store.prefix(store.features[0], 0)
    store.prefix_cache[prefix] = torch.randn(1, len(prefix), 8)
    selected = store.reader_query(0, 0, "mean_span").clone()
    records[0]["metadata"] = {"question_start": -1000, "gold_answer": "poison"}
    records[0]["answers"] = [[0] * 8, [1] * 8]
    assert torch.equal(selected, store.reader_query(0, 0, "mean_span"))
    # A same-length runtime prefix corruption must fail, even with a cache hit.
    store.features[0]["functional_query_ids"][0][0][0] += 1
    corrupt_prefix = store.prefix(store.features[0], 0)
    store.prefix_cache[corrupt_prefix] = store.prefix_cache[prefix]
    with pytest.raises(ValueError, match="Runtime prefix IDs"):
        store.reader_query(0, 0, "mean_span")
