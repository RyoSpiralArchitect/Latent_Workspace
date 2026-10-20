"""Bounded native owner engineering tests; CPU by default, explicit CUDA opt-in."""

import copy
import os
import subprocess
import sys
from pathlib import Path

import pytest
import torch
from test_native_memory import setup as graph_setup

from latent_workspace.native_owner import NativeFullUpdateOwner, NativeOptimizerConfig
from latent_workspace.optimizer_state import rng_state, snapshot, tree_hash


@pytest.fixture(autouse=True)
def threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(previous)


def setup(kind="mistral", dtype=torch.float32, lr=1e-3):
    device = os.environ.get("LTWS_TEST_DEVICE", "cpu")
    assert device in ("cpu", "cuda")
    if device == "cuda":
        assert torch.cuda.is_available(), "CUDA qualification cannot silently skip"
        _, total = torch.cuda.mem_get_info()
        torch.cuda.set_per_process_memory_fraction(4 * 2**30 / total)
    graph, batch = graph_setup(kind)
    graph.to(device=device, dtype=dtype).train()
    if kind != "scratch":
        graph.model.gradient_checkpointing_enable(
            gradient_checkpointing_kwargs={"use_reentrant": False}
        )
    batch = {key: value.to(device) for key, value in batch.items()}
    config = NativeOptimizerConfig(learning_rate=lr, weight_decay=0.01, max_grad_norm=0.1)
    contract = dict(
        source_commit="1" * 40,
        original_base_sha256=tree_hash(graph.model.state_dict()),
        data_sha256=tree_hash(batch),
        objective="query_only_token_weighted_causal_nll",
    )
    owner = NativeFullUpdateOwner(graph, config=config, run_contract=contract)
    return owner, batch


def update(owner, batch):
    owner.begin_window([("a", 3), ("b", 1)])
    receipts = []
    for row, key in enumerate(("a", "b")):
        receipts.append(owner.accumulate(key, {n: v[row : row + 1] for n, v in batch.items()}))
    return receipts, owner.step()


@pytest.mark.parametrize("kind", ["mistral", "olmo2", "gpt2", "scratch"])
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_native_owner_updates_every_partition_with_cpu_state(kind, dtype):
    owner, batch = setup(kind, dtype)
    before = tree_hash(owner.model.state_dict())
    rows, step = update(owner, batch)
    assert step["completed_steps"] == 1 and step["tokens_seen"] == 4
    assert tree_hash(owner.model.state_dict()) != before
    assert all(p.device.type == "cpu" and p.dtype == torch.float32 for p in owner.masters.values())
    assert all(p.grad is None for p in owner.graph.parameters())
    assert len(step["changes"]) == len(list(owner.model.parameters()))
    assert sum(r["transfer"]["current_gradient_count"] for r in rows) == 2 * len(step["changes"])
    assert all(r["master_changed"] for r in step["changes"])
    assert all(
        torch.equal(p.detach().cpu(), owner.masters[n].detach().to(p.dtype)) for n, p in owner.named
    )
    saved = owner.payload()
    assert saved["history"] == [[("a", 3), ("b", 1)]]
    if kind == "gpt2":
        assert len(owner.aliases) > len(owner.masters)  # tied embedding/head counted once


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_native_update_is_bitwise_historical_family_arithmetic(dtype):
    from latent_workspace_ft_v10.precision_bridge import PrecisionAwareWorkspaceBridge
    from latent_workspace_ft_v10.v15_native_learner import V15NativeLearner

    owner, batch = setup(dtype=dtype)
    reference_graph = copy.deepcopy(owner.graph)
    bridge = PrecisionAwareWorkspaceBridge(16, workspace_dim=8, heads=2, slots=3, max_delta_norm=1)
    bridge.to(next(reference_graph.parameters()).device)
    config = dict(
        bridge_lr=1e-4,
        base_lr=owner.config.learning_rate,
        max_grad_norm_per_family=owner.config.max_grad_norm,
        bridge_weight_decay=0.0,
        base_weight_decay=owner.config.weight_decay,
    )
    old = V15NativeLearner(
        reference_graph.model, bridge, full_update=True, optimizer_config=config, boundary=1
    )
    for _ in range(2):
        owner.begin_window([("a", 3), ("b", 1)])
        old.begin_window(["a", "b"])
        for row, key in enumerate(("a", "b")):
            mini = {n: v[row : row + 1] for n, v in batch.items()}
            torch.manual_seed(73 + row)
            owner.accumulate(key, mini)
            torch.manual_seed(73 + row)
            loss = reference_graph(**mini).loss_sum / 4
            loss = loss + sum(p.sum() * 0 for p in bridge.parameters())
            old.backward_pair(key, loss)
        actual, expected = owner.step(), old.step()
        assert actual["preclip_native_l2"] == expected["preclip_base_l2"]
        assert all(torch.equal(owner.masters[n], old.masters[n]) for n in owner.masters)
        assert tree_hash(owner.model.state_dict()) == tree_hash(reference_graph.model.state_dict())
        assert tree_hash(owner.optimizer.state_dict()) == tree_hash(old.base_optimizer.state_dict())


def test_checkpoint_snapshot_is_independent_and_file_is_exclusive(tmp_path):
    owner, batch = setup()
    update(owner, batch)
    payload = owner.payload()
    before = tree_hash(payload)
    update(owner, batch)
    assert tree_hash(payload) == before
    current = tree_hash(owner.payload())
    next(iter(payload["masters"].values())).fill_(99)
    assert tree_hash(owner.payload()) == current
    receipt = owner.save(tmp_path / "step.pt")
    assert receipt["completed_steps"] == 2 and receipt["bytes"] > 0
    with pytest.raises(ValueError, match="exists"):
        owner.save(tmp_path / "step.pt")


def test_incomplete_or_duplicate_window_never_updates_weights(tmp_path):
    owner, batch = setup()
    before = tree_hash(owner.model.state_dict())
    owner.begin_window([("a", 3), ("b", 1)])
    with pytest.raises(ValueError, match="Incomplete"):
        owner.step()
    with pytest.raises(ValueError, match="Active window"):
        owner.save(tmp_path / "partial.pt")
    assert not (tmp_path / "partial.pt").exists()
    owner.accumulate("a", {n: v[:1] for n, v in batch.items()})
    with pytest.raises(ValueError, match="ordering"):
        owner.accumulate("a", {n: v[:1] for n, v in batch.items()})
    assert tree_hash(owner.model.state_dict()) == before and owner.completed_steps == 0


def test_token_mismatch_poison_requires_fresh_restore():
    owner, batch = setup()
    owner.begin_window([("a", 99)])
    with pytest.raises(ValueError, match="Token count"):
        owner.accumulate("a", batch)
    assert owner.failed and all(p.grad is None for p in owner.graph.parameters())
    with pytest.raises(ValueError, match="Failed owner"):
        owner.begin_window([("a", 4)])


@pytest.mark.parametrize(
    "change", ["mode", "cut", "native", "optimizer", "contract", "execution", "cursor", "buffers"]
)
def test_live_policy_drift_is_rejected(change):
    owner, _ = setup()
    if change == "mode":
        owner.graph.eval()
    elif change == "cut":
        owner.graph.cut = 0
    elif change == "native":
        with torch.no_grad():
            next(owner.model.parameters()).add_(1)
    elif change == "optimizer":
        owner.optimizer.param_groups[0]["lr"] *= 2
    elif change == "contract":
        owner.run_contract["source_commit"] = "2" * 40
    elif change == "execution":
        owner.execution["threads"] += 1
    elif change == "cursor":
        owner.tokens_seen += 1
    elif change == "buffers":
        next(iter(owner.buffers.values())).zero_()
    with pytest.raises(ValueError):
        owner.begin_window([("a", 4)])


@pytest.mark.parametrize(
    "damage",
    [
        "extra_key",
        "format",
        "master_shape",
        "master_dtype",
        "master_value",
        "nan",
        "alias",
        "cursor",
        "token_cursor",
        "history",
        "optimizer_lr",
        "optimizer_step",
        "negative_moment",
        "rng",
        "execution",
        "provenance",
        "native_hash",
    ],
)
def test_bad_restore_is_rejected_before_target_or_rng_mutation(damage):
    owner, batch = setup()
    update(owner, batch)
    payload = owner.payload()
    fresh, _ = setup()
    name = next(iter(payload["masters"]))
    opt_state = next(iter(payload["optimizer"]["state"].values()))
    if damage == "extra_key":
        payload["unexpected"] = 1
    elif damage == "format":
        payload["format"] = "wrong"
    elif damage == "master_shape":
        payload["masters"][name] = torch.zeros(1)
    elif damage == "master_dtype":
        payload["masters"][name] = payload["masters"][name].double()
    elif damage == "master_value":
        payload["masters"][name].add_(1)
    elif damage == "nan":
        payload["masters"][name].fill_(float("nan"))
    elif damage == "alias":
        payload["aliases"][name] = "wrong"
    elif damage == "cursor":
        payload["completed_steps"] += 1
    elif damage == "token_cursor":
        payload["tokens_seen"] += 1
    elif damage == "history":
        payload["history"][0][0] = ("a", 0)
    elif damage == "optimizer_lr":
        payload["optimizer"]["param_groups"][0]["lr"] *= 2
    elif damage == "optimizer_step":
        opt_state["step"] += 1
    elif damage == "negative_moment":
        opt_state["RMS"].fill_(-1)
    elif damage == "rng":
        payload["rng"]["torch_cpu"] = torch.zeros(2, dtype=torch.uint8)
    elif damage == "execution":
        payload["execution"]["graph"]["boundary"]["boundary_layer"] = 0
    elif damage == "provenance":
        payload["run_contract"]["data_sha256"] = "0" * 64
    elif damage == "native_hash":
        payload["native_sha256"] = "0" * 64
    before, rng_before = tree_hash(fresh.model.state_dict()), tree_hash(rng_state())
    # Rehash deliberately: exercise schema/policy guards, not only a receipt mismatch.
    with pytest.raises(ValueError):
        NativeFullUpdateOwner.restore(
            fresh.graph,
            payload,
            config=fresh.config,
            expected_run_contract=fresh.run_contract,
            expected_state_sha256=tree_hash(payload),
        )
    assert tree_hash(fresh.model.state_dict()) == before
    assert tree_hash(rng_state()) == rng_before


@pytest.mark.parametrize("kind", ["mistral", "gpt2"])
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_valid_restore_next_window_exact(kind, dtype):
    owner, batch = setup(kind, dtype)
    update(owner, batch)
    saved = owner.payload()
    expected_rows, expected_step = update(owner, batch)
    expected = owner.payload()
    fresh, _ = setup(kind, dtype)
    restored = NativeFullUpdateOwner.restore(
        fresh.graph,
        saved,
        config=fresh.config,
        expected_run_contract=fresh.run_contract,
        expected_state_sha256=tree_hash(saved),
    )
    # Mutating the source payload after publication must not affect the owner.
    next(iter(saved["masters"].values())).zero_()
    rows, step = update(restored, batch)
    assert rows == expected_rows and step == expected_step
    assert tree_hash(restored.payload()) == tree_hash(expected)


@pytest.mark.parametrize("dtype", ["float32", "bfloat16"])
def test_fresh_process_owner_replay(dtype, tmp_path):
    root = Path(__file__).resolve().parents[1]
    command = """
import json, sys
from pathlib import Path
root = Path(sys.argv[4]).resolve()
sys.path[:0] = [str(root / 'src'), str(root / 'tests')]
import torch
from test_native_owner import setup, update
from latent_workspace.native_owner import NativeFullUpdateOwner
from latent_workspace.optimizer_state import tree_hash
torch.set_num_threads(2)
torch.use_deterministic_algorithms(True)
owner, batch = setup(dtype=getattr(torch, sys.argv[1]))
path, mode = Path(sys.argv[2]), sys.argv[3]
if mode == 'replay':
    saved = torch.load(path / 'step1.pt', weights_only=True)
    receipt = json.loads((path / 'receipt.json').read_text())
    owner = NativeFullUpdateOwner.restore(owner.graph, saved, config=owner.config,
        expected_run_contract=owner.run_contract, expected_state_sha256=receipt['state_sha256'])
else:
    update(owner, batch)
    receipt = owner.save(path / 'step1.pt')
    (path / 'receipt.json').write_text(json.dumps(receipt))
rows, step = update(owner, batch)
(path / (mode + '.json')).write_text(json.dumps(dict(rows=rows, step=step,
    state_sha256=tree_hash(owner.payload()))))
"""
    env = dict(os.environ)
    for mode in ("primary", "replay"):
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                "-X",
                f"pycache_prefix={tmp_path / (mode + '-cache')}",
                "-c",
                command,
                dtype,
                str(tmp_path),
                mode,
                str(root),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stderr
    assert (tmp_path / "primary.json").read_bytes() == (tmp_path / "replay.json").read_bytes()


def test_unweighted_microbatch_means_are_not_the_objective():
    owner, batch = setup()
    owner.begin_window([("a", 3), ("b", 1)])
    rows = [
        owner.accumulate(key, {n: v[i : i + 1] for n, v in batch.items()})
        for i, key in enumerate(("a", "b"))
    ]
    for row in rows:
        assert row["scaled_loss"] == row["loss_sum"] / 4


def test_receipt_hash_mismatch_rejected():
    owner, batch = setup()
    update(owner, batch)
    saved = snapshot(owner.payload())
    fresh, _ = setup()
    with pytest.raises(ValueError, match="receipt"):
        NativeFullUpdateOwner.restore(
            fresh.graph,
            saved,
            config=fresh.config,
            expected_run_contract=fresh.run_contract,
            expected_state_sha256="0" * 64,
        )


def test_living_engine_imports_are_from_this_checkout():
    root = Path(__file__).resolve().parents[1] / "src"
    for name, module in list(sys.modules.items()):
        if name == "latent_workspace" or name.startswith("latent_workspace."):
            assert Path(module.__file__).resolve().is_relative_to(root), name
