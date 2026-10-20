"""V22 protocol/long mixed-window qualification on tiny hosts, never pretrained."""

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_v22_full_ft as run  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402
from latent_workspace import v22_data
from latent_workspace.native_owner import NativeFullUpdateOwner  # noqa: E402
from latent_workspace.optimizer_state import tree_hash  # noqa: E402


def no_guard(*args, **kwargs):
    pass


def test_frozen_v22_plan_retains_native_arithmetic_and_claim_ceiling():
    plan = ex.read(run.ROOT / run.PLAN)
    run.validate(plan)
    assert plan["planned_training_rows"] == 723 and plan["planned_training_tokens"] == 20860
    assert plan["planned_training_updates"] == 32
    assert plan["weight_deletions"] == plan["new_sequences"] == plan["judge_calls"] == 0
    assert plan["old_expression_gate"] == "FAIL" and plan["non_regression"] == "NOT_ESTABLISHED"
    assert plan["resources"]["disk_free_gib"] == 50
    assert len(plan["checkpoint_names"]) == 3
    assert run.ROLES == ("canary", "replay", "train_a", "train_b")


@pytest.mark.parametrize("field", ["seed", "optimizer", "data_manifest_sha256", "no_retry"])
def test_plan_drift_rejected(field):
    plan = ex.read(run.ROOT / run.PLAN)
    plan[field] = "changed"
    with pytest.raises(ValueError, match="Frozen"):
        run.validate(plan)


def data_fixture(tmp_path):
    from test_v22_data import fixture

    recipe, rows, excluded, *_ = fixture()
    folder = tmp_path / "data"
    folder.mkdir()
    schedule = dict(
        training=v22_data.schedule(rows, recipe),
        canary=v22_data.select_canary(rows, recipe),
        development=v22_data.select_dev(rows, recipe),
    )
    summary = v22_data.summarize(
        rows, schedule["training"], schedule["canary"], schedule["development"], excluded, recipe
    )
    # The config file's declared role order is source-byte-pinned. Production
    # reloads this config, not the sorted-key metadata projection PLAN.json.
    (tmp_path / "recipe.json").write_text(json.dumps(recipe))
    ex.write_new(folder / "PLAN.json", recipe)
    ex.write_new(folder / "SCHEDULE.json", schedule)
    ex.write_new(folder / "SUMMARY.json", summary)
    ex.write_gz(folder / "rows.json.gz", rows)
    ex.write_new(
        folder / "MANIFEST.json",
        dict(
            files=ex.manifest(folder), source={"recipe.json": ex.digest(tmp_path / "recipe.json")}
        ),
    )
    plan = dict(
        data_bundle=str(folder),
        data_manifest_sha256=ex.digest(folder / "MANIFEST.json"),
        data_recipe="recipe.json",
        planned_training_rows=summary["training_rows"],
        planned_training_tokens=summary["training_tokens"],
    )
    return plan, rows, schedule


def test_pre_model_data_regeneration(tmp_path):
    plan, rows, schedule = data_fixture(tmp_path)
    loaded, actual, _, _ = run.load_data(plan, root=tmp_path)
    assert loaded == rows and actual == schedule


@pytest.mark.parametrize("fault", ["file", "extra", "manifest", "source", "denominator"])
def test_changed_data_never_reaches_model_loading(tmp_path, fault):
    plan, _, _ = data_fixture(tmp_path)
    folder = Path(plan["data_bundle"])
    if fault == "file":
        (folder / "rows.json.gz").write_bytes(b"broken")
    elif fault == "extra":
        (folder / "extra.json").write_text("{}")
    elif fault == "manifest":
        plan["data_manifest_sha256"] = "0" * 64
    elif fault == "source":
        (tmp_path / "recipe.json").write_text("{}")
    else:
        plan["planned_training_tokens"] += 1
    with pytest.raises(ValueError):
        run.load_data(plan, root=tmp_path)


def tiny_rows():
    result = []
    for key, length, memory, role in (
        ("instruction", 1024, 0, "instruction"),
        ("memory", 128, 128, "world"),
        ("code", 993, 0, "code"),
        ("prose", 128, 0, "prose"),
    ):
        ids = [3 + i % 37 for i in range(length)]
        labels = [-100] * 4 + ids[4:]
        result.append(
            dict(
                key=key,
                split="train",
                role=role,
                mode="affected",
                input_ids=ids,
                labels=labels,
                memory_ids=[3 + i % 31 for i in range(memory)],
                supervised_tokens=length - 4,
            )
        )
    return result


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_long_mixed_update_save_restore_and_exact_replay(tmp_path, dtype):
    from test_native_owner import setup

    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    try:
        owner, _ = setup(dtype=dtype)
        original = copy.deepcopy(owner.graph)
        rows = tiny_rows()
        first, second, repeated = (tmp_path / n for n in ("first", "second", "replay"))
        for path in (first, second, repeated):
            path.mkdir()
        run.common.update(owner, rows, ["instruction", "memory"], no_guard, first, 1)
        receipt = owner.save(tmp_path / "one.pt")
        payload = torch.load(tmp_path / "one.pt", weights_only=False)
        expected = run.common.update(owner, rows, ["code", "prose"], no_guard, second, 2)
        restored = NativeFullUpdateOwner.restore(
            original,
            payload,
            config=owner.config,
            expected_run_contract=owner.run_contract,
            expected_state_sha256=receipt["state_sha256"],
        )
        actual = run.common.update(restored, rows, ["code", "prose"], no_guard, repeated, 2)
        run.common.exact(expected, actual, "long mixed replay")
        assert tree_hash(owner.payload()) == tree_hash(restored.payload())
    finally:
        torch.set_num_threads(previous)


def test_training_observation_reduction_does_not_change_update_arithmetic(tmp_path):
    from test_native_owner import setup

    owner, _ = setup(dtype=torch.bfloat16)
    original, payload = copy.deepcopy(owner.graph), owner.payload()
    rows = tiny_rows()[1:2]
    (tmp_path / "reference").mkdir()
    (tmp_path / "training").mkdir()
    expected = run.common.update(owner, rows, ["memory"], no_guard, tmp_path / "reference", 1)
    restored = NativeFullUpdateOwner.restore(
        original,
        payload,
        config=owner.config,
        expected_run_contract=owner.run_contract,
        expected_state_sha256=tree_hash(payload),
    )
    actual = run.train_update(restored, rows, ["memory"], no_guard, tmp_path / "training", 1)
    for row in expected["rows"]:
        row.pop("accumulated_gradient_sha256")
    run.common.exact(expected, actual, "receipt-only difference")


def test_fixed_development_nll_preserves_owner_weights_rng_and_policy(tmp_path):
    from test_native_owner import setup

    owner, _ = setup()
    rows = [{**r, "split": "dev"} for r in tiny_rows()[1:]]
    before = run.common.fingerprint(owner)
    result = run.evaluate_dev(
        owner.graph, rows, [r["key"] for r in rows], no_guard, tmp_path / "DEV.json"
    )
    run.common.exact(before, run.common.fingerprint(owner), "read-only dev state")
    assert len(result["rows"]) == 3 and result["new_sequences"] == 0
    assert result["interpretation"] == "FIXED_DEV_NLL_ONLY_NOT_NON_REGRESSION"


def test_dev_rejects_training_rows(tmp_path):
    from test_native_owner import setup

    owner, _ = setup()
    with pytest.raises(ValueError, match="development"):
        run.evaluate_dev(owner.graph, tiny_rows(), ["prose"], no_guard, tmp_path / "DEV.json")


@pytest.mark.parametrize("fault", [None, "step", "tokens", "history"])
def test_resume_cursor_binds_entire_schedule_prefix(fault):
    row = tiny_rows()[-1]
    owner = SimpleNamespace(
        history=[[(row["key"], row["supervised_tokens"])]],
        completed_steps=1,
        tokens_seen=row["supervised_tokens"],
    )
    if fault == "step":
        owner.completed_steps = 2
    elif fault == "tokens":
        owner.tokens_seen += 1
    elif fault == "history":
        owner.history[0][0] = ("wrong", row["supervised_tokens"])
    if fault is None:
        run.assert_cursor(owner, [row], [[row["key"]]], 1)
    else:
        with pytest.raises(ValueError):
            run.assert_cursor(owner, [row], [[row["key"]]], 1)


@pytest.mark.parametrize("fault", [None, "status", "source", "artifact"])
def test_training_gate_requires_successful_same_source_predecessor(tmp_path, fault):
    folder = tmp_path / "replay"
    folder.mkdir()
    seal = dict(source_commit="1" * 40)
    ex.write_new(folder / "STARTED.json", dict(seal=seal if fault != "source" else {}))
    ex.write_new(
        folder / "FINISHED.json",
        dict(
            files=ex.manifest(folder),
            status=run.STATUSES["replay"] if fault != "status" else ex.INCOMPLETE,
        ),
    )
    if fault == "artifact":
        (folder / "extra").write_text("changed")
    args = SimpleNamespace(output=tmp_path / "train_a")
    if fault is None:
        assert run.predecessor(args, "replay", seal) == folder
    else:
        with pytest.raises(ValueError):
            run.predecessor(args, "replay", seal)


@pytest.mark.parametrize("fault", [None, "updates", "tokens", "status"])
def test_training_terminal_denominators_not_canary_or_replay_quality(tmp_path, fault):
    plan = dict(planned_training_tokens=20860)
    for role, updates in (("canary", 2), ("replay", 1), ("train_a", 16), ("train_b", 16)):
        path = tmp_path / role
        path.mkdir()
        record = dict(
            status=run.STATUSES[role],
            native_weight_updates=updates,
            outcome=dict(completed_training_steps=32, training_tokens_seen=20860),
        )
        if role == "train_b":
            if fault == "updates":
                record["native_weight_updates"] = 15
            elif fault == "tokens":
                record["outcome"]["training_tokens_seen"] = 20859
            elif fault == "status":
                record["status"] = ex.INCOMPLETE
        ex.write_new(path / "FINISHED.json", record)
    if fault is None:
        result = run.summary(tmp_path, plan)
        assert result["native_weight_updates"] == 35 and result["training_updates"] == 32
        assert (
            result["old_expression_gate"] == "FAIL"
            and result["non_regression"] == "NOT_ESTABLISHED"
        )
    else:
        with pytest.raises(ValueError):
            run.summary(tmp_path, plan)
