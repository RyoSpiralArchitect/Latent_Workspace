"""Owned CE/KL arithmetic, admission, and exact replay; no quality assertions."""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import torch
from safetensors.torch import load_file, save_file
from test_native_owner import setup as old_setup
from torch.nn import functional as F

from latent_workspace.execution import digest, plan_hash
from latent_workspace.native_owner import NativeFullUpdateOwner, native_optimizer
from latent_workspace.offload import CompleteCPUWindow
from latent_workspace.optimizer_state import restore_rng, rng_state, tree_hash
from latent_workspace.preservation_objective import PreservationTargets, objective


@pytest.fixture(autouse=True)
def threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(previous)


def batch(row, device):
    result = {
        k: torch.tensor([row[k]], device=device, dtype=torch.long)
        for k in ("input_ids", "labels", "memory_ids")
    }
    result["attention_mask"] = torch.ones_like(result["input_ids"])
    result["memory_mask"] = torch.ones_like(result["memory_ids"])
    return result


def fixture(path, kind="mistral", dtype=torch.float32):
    legacy, _ = old_setup(kind, dtype)
    rows = [
        dict(
            key="a",
            input_ids=[1, 11, 12, 13, 2],
            labels=[-100, -100, 12, -100, 2],
            memory_ids=[],
            supervised_tokens=2,
        ),
        dict(
            key="b",
            input_ids=[1, 16, 2],
            labels=[-100, -100, 2],
            memory_ids=[],
            supervised_tokens=1,
        ),
        dict(
            key="w",
            input_ids=[1, 11, 12, 13, 2],
            labels=[-100, -100, 12, 13, 2],
            memory_ids=[2, 3, 4],
            supervised_tokens=3,
        ),
    ]
    rows = [dict(r, split="train", language="en") for r in rows]
    # Synthetic, deliberately nonzero KL fixture; not an original-host teacher claim.
    tensors = {
        str(i): (
            torch.arange(r["supervised_tokens"] * 43, dtype=torch.float32).reshape(-1, 43) / 43
        ).log_softmax(-1)
        for i, r in enumerate(rows[:2])
    }
    path = Path(path)
    receipt_path = path.with_suffix(".json")
    if not path.exists():
        save_file(tensors, path)
        receipt = dict(
            bytes=path.stat().st_size,
            sha256=digest(path),
            input_sha256=plan_hash(rows),
            native_sha256=legacy.run_contract["original_base_sha256"],
            source_commit=legacy.run_contract["source_commit"],
            target_dtype="float32",
            temperature=1.0,
            vocabulary=43,
            tensor_bytes=sum(v.numel() * 4 for v in tensors.values()),
            teacher_policy="synthetic full-vocabulary fixture, not a real teacher",
            rows=[
                dict(
                    index=str(i),
                    key=r["key"],
                    row_sha256=plan_hash(r),
                    shape=list(tensors[str(i)].shape),
                    supervised_tokens=r["supervised_tokens"],
                )
                for i, r in enumerate(rows[:2])
            ],
        )
        receipt_path.write_text(json.dumps(receipt))
    receipt = json.loads(receipt_path.read_text())
    targets = PreservationTargets.load(
        path, receipt, rows, ["a", "b"], expected_receipt_plan_sha256=plan_hash(receipt)
    )
    contract = dict(
        legacy.run_contract, data_sha256=plan_hash(rows), objective=objective(1, targets)
    )
    owner = NativeFullUpdateOwner(
        legacy.graph, config=legacy.config, run_contract=contract, preservation=targets
    )
    return owner, rows, tensors


def update(owner, rows):
    owner.begin_window([(r["key"], r["supervised_tokens"]) for r in rows])
    receipts = [
        owner.accumulate(r["key"], batch(r, next(owner.graph.parameters()).device)) for r in rows
    ]
    return receipts, owner.step()


@pytest.mark.parametrize("kind", ["mistral", "olmo2", "gpt2", "scratch"])
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_positive_update_matches_independent_composition(kind, dtype, tmp_path):
    owner, rows, tensors = fixture(tmp_path / "targets.safetensors", kind, dtype)
    graph = copy.deepcopy(owner.graph)
    masters = {
        n: torch.nn.Parameter(p.detach().cpu().float().clone())
        for n, p in graph.model.named_parameters()
    }
    optimizer = native_optimizer(masters.values(), owner.config)
    for _ in range(2):
        start_rng = rng_state()
        actual, step = update(owner, rows)
        restore_rng(start_rng)
        window = CompleteCPUWindow(graph.model.named_parameters(), merge_device="cpu")
        for i, row in enumerate(rows):
            value = graph(**batch(row, next(graph.parameters()).device))
            loss = value.loss_sum / 6
            if i < 2:
                positions = [j - 1 for j, v in enumerate(row["labels"]) if v != -100]
                pred = value.logits[:, positions].float().log_softmax(-1)
                target = tensors[str(i)].to(pred.device)[None]
                kl = F.kl_div(pred, target, reduction="none", log_target=True).sum(-1).sum()
                loss = loss + kl / 3
                assert actual[i]["kl_sum"] == float(kl.detach())
            assert actual[i]["scaled_loss"] == float(loss.detach())
            loss.backward()
            window.spill()
        grads, _ = window.take(3)
        for n, p in masters.items():
            p.grad = grads[n].float()
        norm = torch.nn.utils.clip_grad_norm_(list(masters.values()), owner.config.max_grad_norm)
        optimizer.step()
        optimizer.zero_grad(set_to_none=True)
        with torch.no_grad():
            for n, p in graph.model.named_parameters():
                p.copy_(masters[n].to(device=p.device, dtype=p.dtype))
        assert step["preclip_native_l2"] == float(norm)
        assert tree_hash(owner.masters) == tree_hash(masters)
        assert tree_hash(owner.optimizer.state_dict()) == tree_hash(optimizer.state_dict())
        assert tree_hash(owner.model.state_dict()) == tree_hash(graph.model.state_dict())
        assert actual[-1]["kl_sum"] is None  # a declared world row, NOT missing targets
    assert owner.tokens_seen == 12 and owner.preservation_tokens_seen == 6


@pytest.mark.parametrize("kind", ["mistral", "olmo2", "gpt2", "scratch"])
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_disabled_objective_is_exact_legacy_without_targets(kind, dtype):
    from test_native_owner import update as old_update

    left, data = old_setup(kind, dtype)
    right = NativeFullUpdateOwner(
        copy.deepcopy(left.graph),
        config=left.config,
        run_contract=dict(left.run_contract, objective=objective(0)),
    )
    for _ in range(2):
        start_rng = rng_state()
        expected = old_update(left, data)
        restore_rng(start_rng)
        assert expected == old_update(right, data)
        assert tree_hash(left.payload()) == tree_hash(right.payload())
    assert left.payload()["format"] == "ltws-native-owner-v1"
    assert "preservation_tokens_seen" not in left.payload()


@pytest.mark.parametrize("kind", ["mistral", "gpt2"])
@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_positive_resume_exact(kind, dtype, tmp_path):
    path = tmp_path / "targets.safetensors"
    owner, rows, _ = fixture(path, kind, dtype)
    update(owner, rows)
    saved = owner.payload()
    expected = update(owner, rows)
    state = tree_hash(owner.payload())
    fresh, _, _ = fixture(path, kind, dtype)
    restored = NativeFullUpdateOwner.restore(
        fresh.graph,
        saved,
        config=fresh.config,
        expected_run_contract=fresh.run_contract,
        expected_state_sha256=tree_hash(saved),
        preservation=fresh.preservation,
    )
    assert update(restored, rows) == expected
    assert tree_hash(restored.payload()) == state


@pytest.mark.parametrize(
    "damage",
    [
        "tokens",
        "history",
        "coefficient",
        "target",
        "denominator",
        "source",
        "base",
        "format",
        "missing_bank",
    ],
)
def test_restore_rejects_before_model_and_rng_mutation(damage, tmp_path):
    owner, rows, _ = fixture(tmp_path / "targets.safetensors")
    update(owner, rows)
    saved = owner.payload()
    fresh, _, _ = fixture(tmp_path / "targets.safetensors")
    if damage == "tokens":
        saved["preservation_tokens_seen"] += 1
    elif damage == "history":
        saved["preservation_history"][0].reverse()
    elif damage == "format":
        saved["format"] = "ltws-native-owner-v1"
    elif damage == "missing_bank":
        fresh.preservation = None
    else:
        value = saved["run_contract"]["objective"]
        if damage == "coefficient":
            value["coefficient"] = 0.5
        elif damage == "denominator":
            value["kl_normalization"] = "per_row"
        else:
            field = {
                "target": "target_file_sha256",
                "source": "source_commit",
                "base": "original_base_sha256",
            }[damage]
            value["bank"][field] = "0" * len(value["bank"][field])
    before, rng = tree_hash(fresh.model.state_dict()), tree_hash(rng_state())
    with pytest.raises(ValueError):
        NativeFullUpdateOwner.restore(
            fresh.graph,
            saved,
            config=fresh.config,
            expected_run_contract=fresh.run_contract,
            expected_state_sha256=tree_hash(saved),
            preservation=fresh.preservation,
        )
    assert tree_hash(fresh.model.state_dict()) == before and tree_hash(rng_state()) == rng


@pytest.mark.parametrize("damage", ["ids", "labels", "mask", "crop", "memory", "extra"])
def test_actual_forwarded_batch_is_checked(damage, tmp_path):
    owner, rows, _ = fixture(tmp_path / "targets.safetensors")
    data = batch(rows[0], next(owner.model.parameters()).device)
    if damage == "ids":
        data["input_ids"][0, 1] += 1
    elif damage == "labels":
        data["labels"][0, 2] = -100
    elif damage == "mask":
        data["attention_mask"][0, 0] = 0
    elif damage == "crop":
        data["input_ids"] = data["input_ids"][:, :-1]
    elif damage == "memory":
        data["memory_ids"] = torch.ones((1, 1), dtype=torch.long)
    else:
        data["position_ids"] = torch.arange(5)[None]
    before, rng = tree_hash(owner.model.state_dict()), tree_hash(rng_state())
    owner.begin_window([("a", 2)])
    with pytest.raises(ValueError):
        owner.accumulate("a", data)
    assert owner.failed
    assert tree_hash(owner.model.state_dict()) == before and tree_hash(rng_state()) == rng


@pytest.mark.parametrize("rows", [[("missing", 2)], [("w", 3)], [("a", 3)]])
def test_missing_eligibility_or_wrong_denominator_is_not_zero(rows, tmp_path):
    owner, _, _ = fixture(tmp_path / "targets.safetensors")
    with pytest.raises(ValueError):
        owner.begin_window(rows)
    assert owner.window is None


@pytest.mark.parametrize("damage", ["file", "registry", "index", "cursor", "binding"])
def test_live_target_drift_is_detected(damage, tmp_path):
    path = tmp_path / "targets.safetensors"
    owner, rows, _ = fixture(path)
    if damage == "file":
        with path.open("r+b") as stream:
            stream.seek(-4, 2)
            stream.write(b"xxxx")
    elif damage == "registry":
        owner.preservation._contexts["a"]["tokens"] += 1
    elif damage == "index":
        owner.preservation._bound.pop("a")
    elif damage == "cursor":
        owner.preservation_tokens_seen += 1
    else:
        owner.preservation._manifest["temperature"] = 2
    with pytest.raises(ValueError):
        update(owner, rows)


@pytest.mark.parametrize("coefficient", [-1, float("nan"), float("inf"), True])
def test_invalid_coefficient(coefficient):
    with pytest.raises(ValueError):
        objective(coefficient)


@pytest.mark.parametrize("damage", ["missing", "extra", "dtype", "shape", "nan", "normalization"])
def test_target_body_must_validate_not_only_metadata(damage, tmp_path):
    path = tmp_path / "targets.safetensors"
    _, rows, _ = fixture(path)
    tensors = load_file(path)
    receipt = json.loads(path.with_suffix(".json").read_text())
    if damage == "missing":
        tensors.pop("1")
    elif damage == "extra":
        tensors["extra"] = tensors["1"].clone()
    elif damage == "dtype":
        tensors["0"] = tensors["0"].bfloat16()
    elif damage == "shape":
        tensors["0"] = tensors["0"][:, :-1].contiguous()
    elif damage == "nan":
        tensors["0"][0, 0] = float("nan")
    else:
        tensors["0"] += 1
    other = tmp_path / "bad.safetensors"
    save_file(tensors, other)
    receipt.update(sha256=digest(other), bytes=other.stat().st_size)
    with pytest.raises(ValueError):
        PreservationTargets.load(
            other, receipt, rows, ["a", "b"], expected_receipt_plan_sha256=plan_hash(receipt)
        )


def test_file_changed_before_restore_never_publishes(tmp_path):
    path = tmp_path / "targets.safetensors"
    owner, rows, _ = fixture(path)
    update(owner, rows)
    saved = owner.payload()
    fresh, _, _ = fixture(path)
    before, rng = tree_hash(fresh.model.state_dict()), tree_hash(rng_state())
    with path.open("r+b") as stream:
        stream.seek(-4, 2)
        stream.write(b"xxxx")
    with pytest.raises(ValueError, match="Target file changed"):
        NativeFullUpdateOwner.restore(
            fresh.graph,
            saved,
            config=fresh.config,
            expected_run_contract=fresh.run_contract,
            expected_state_sha256=tree_hash(saved),
            preservation=fresh.preservation,
        )
    assert tree_hash(fresh.model.state_dict()) == before and tree_hash(rng_state()) == rng


@pytest.mark.parametrize("dtype", ["float32", "bfloat16"])
def test_fresh_process_preservation_replay(dtype, tmp_path):
    command = """
import json, sys
from pathlib import Path
root, path = Path(sys.argv[1]), Path(sys.argv[2])
sys.path[:0] = [str(root / 'src'), str(root / 'tests')]
import torch
from test_preservation_owner import fixture, update
from latent_workspace.native_owner import NativeFullUpdateOwner
from latent_workspace.optimizer_state import tree_hash
torch.set_num_threads(2)
torch.use_deterministic_algorithms(True)
owner, rows, _ = fixture(path / 'targets.safetensors', dtype=getattr(torch, sys.argv[3]))
mode = sys.argv[4]
if mode == 'primary':
    update(owner, rows)
    receipt = owner.save(path / 'step1.pt')
    (path / 'receipt.json').write_text(json.dumps(receipt))
else:
    saved = torch.load(path / 'step1.pt', weights_only=True)
    receipt = json.loads((path / 'receipt.json').read_text())
    owner = NativeFullUpdateOwner.restore(owner.graph, saved, config=owner.config,
        expected_run_contract=owner.run_contract, expected_state_sha256=receipt['state_sha256'],
        preservation=owner.preservation)
result = update(owner, rows)
(path / (mode + '.json')).write_text(json.dumps(dict(result=result,
    state_sha256=tree_hash(owner.payload()))))
"""
    root = Path(__file__).resolve().parents[1]
    for mode in ("primary", "replay"):
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", command, str(root), str(tmp_path), dtype, mode],
            env=dict(os.environ),
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stderr
    assert (tmp_path / "primary.json").read_bytes() == (tmp_path / "replay.json").read_bytes()
