import copy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "tests")]
import run_v24_recruitment_ft as run  # noqa: E402
from test_recruitment_bank import Tokenizer  # noqa: E402
from test_v24_recruitment_preparation import inputs  # noqa: E402


def test_exact_numerical_reference_and_new_data_budget():
    plan = run.ex.read(ROOT / run.PLAN)
    run.validate(plan)
    old = run.ex.read(ROOT / plan["reference_plan"])
    setup = run.numerical_plan(plan)
    assert {k: v for k, v in setup.items() if k != "checkpoint_names"} == {
        k: v for k, v in old.items() if k != "checkpoint_names"
    }
    assert plan["training_rows_per_arm"] == 538 and plan["training_tokens_per_arm"] == 21112
    assert setup["optimizer"]["learning_rate"] == 2e-7 and setup["seed"] == 47
    assert plan["preservation_coefficient"] == 0
    assert plan["resources"]["disk_free_gib"] == 50


@pytest.mark.parametrize(
    "field,value",
    [
        ("preservation_coefficient", 1),
        ("training_updates_per_arm", 64),
        ("routes", ["workspace"]),
        ("new_sequences", 1),
        ("weight_deletions", 1),
        ("no_retry", False),
    ],
)
def test_protocol_expansion_rejected(field, value):
    plan = run.ex.read(ROOT / run.PLAN)
    plan[field] = value
    with pytest.raises(ValueError):
        run.validate(plan)


def data_fixture(tmp_path, monkeypatch):
    import prepare_v24_recruitment as prep
    from test_recruitment_bank import PLAN

    pres, raw = inputs()
    routes, canary, schedule, summary = prep.assemble(pres, raw, Tokenizer(), PLAN)
    folder = tmp_path / "data/bank"
    folder.mkdir(parents=True)
    for route, rows in routes.items():
        run.ex.write_gz(folder / f"PRIVATE_{route}.json.gz", rows)
    run.ex.write_gz(folder / "PRIVATE_CANARY.json.gz", canary)
    for name, value in (("PLAN", PLAN), ("SCHEDULE", schedule), ("SUMMARY", summary)):
        run.ex.write_new(folder / f"{name}.json", value)
    run.ex.write_new(tmp_path / "recipe.json", PLAN)
    run.ex.write_new(
        folder / "MANIFEST.json",
        dict(
            files=run.ex.manifest(folder),
            source_commit="a" * 40,
            source={"recipe.json": run.ex.digest(tmp_path / "recipe.json")},
        ),
    )
    end = folder.parent / "FINISHED.json"
    run.ex.write_new(end, dict(status=prep.PASS))
    plan = dict(
        data_bundle=str(folder),
        data_manifest_sha256=run.ex.digest(folder / "MANIFEST.json"),
        preparation_terminal_sha256=run.ex.digest(end),
        preparation_source_commit="a" * 40,
        recipe="recipe.json",
        **{
            k: summary[k]
            for k in (
                "training_updates_per_arm",
                "training_rows_per_arm",
                "training_tokens_per_arm",
            )
        },
    )
    monkeypatch.setattr(run, "ROOT", tmp_path)
    return plan, routes, canary, schedule


def test_data_contract_replayed_before_any_model_import(tmp_path, monkeypatch):
    plan, routes, canary, schedule = data_fixture(tmp_path, monkeypatch)
    for stream in ("canary", "inline", "workspace"):
        actual, observed, _, _ = run.load_data(plan, stream)
        assert actual == (canary if stream == "canary" else routes[stream])
        assert observed == schedule


@pytest.mark.parametrize("damage", ["body", "source", "extra", "denominator", "terminal"])
def test_modified_data_rejected_before_model_loading(tmp_path, monkeypatch, damage):
    plan, _, _, _ = data_fixture(tmp_path, monkeypatch)
    folder = Path(plan["data_bundle"])
    if damage == "body":
        (folder / "PRIVATE_inline.json.gz").write_bytes(b"bad")
    elif damage == "source":
        (tmp_path / "recipe.json").write_text("{}")
    elif damage == "extra":
        (folder / "extra.json").write_text("{}")
    elif damage == "terminal":
        (folder.parent / "FINISHED.json").write_text("{}")
    else:
        plan["training_tokens_per_arm"] += 1
    with pytest.raises(ValueError):
        run.load_data(plan, "inline")


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_mixed_route_canary_and_runner_replay_use_exact_owner(tmp_path, monkeypatch, dtype):
    from test_native_owner import setup

    from latent_workspace.optimizer_state import tree_hash

    threads = torch.get_num_threads()
    torch.set_num_threads(2)
    try:
        owner, _ = setup(dtype=dtype)
        original = copy.deepcopy(owner.graph)
        contract, config = owner.run_contract, owner.config
        rows = [
            dict(
                key="i",
                role="reasoning",
                split="train",
                input_ids=[3, 4, 5, 6, 7],
                labels=[-100, -100, -100, 6, 7],
                memory_ids=[],
                supervised_tokens=2,
            ),
            dict(
                key="w",
                role="reasoning",
                split="train",
                input_ids=[5, 6, 7],
                labels=[-100, 6, 7],
                memory_ids=[3, 4],
                supervised_tokens=2,
            ),
        ]
        schedule = dict(canary=[["i", "w"], ["w", "i"]])
        settings = dict(checkpoint_names=["canary_step1.pt"], checkpoint_max_bytes=2**30)
        plan = dict(checkpoint_max_bytes=2**30)
        checkpoints = tmp_path / "checkpoints"
        checkpoints.mkdir()
        first, second = tmp_path / "canary", tmp_path / "replay"
        first.mkdir()
        second.mkdir()
        core = SimpleNamespace(snapshot_admission=lambda *a: None)
        monkeypatch.setattr(run.common, "peak", lambda: {})
        monkeypatch.setattr(run, "boundary", lambda *a: None)
        monkeypatch.setattr(run, "predecessor", lambda *a: first)

        def prepare(*args):
            # A fresh graph/RNG for both runs; this test never uses a pretrained model.
            from latent_workspace.optimizer_state import restore_rng

            restore_rng(owner.initial_rng)
            return (
                copy.deepcopy(original),
                rows,
                schedule,
                config,
                contract,
                lambda *a, **k: None,
                settings,
            )

        # Save the known original RNG independently of owner implementation fields.
        from latent_workspace.optimizer_state import rng_state

        initial_rng = rng_state()
        owner.initial_rng = initial_rng
        monkeypatch.setattr(run, "prepare", prepare)
        args = SimpleNamespace(output=first, checkpoints=checkpoints)
        outcome = run.canary(core, args, plan, {})
        assert outcome["native_weight_updates"] == 2 and outcome["backward_rows"] == 4
        expected = run.ex.read(first / "STEP2_PAYLOAD.json")["state_sha256"]
        args.output = second
        assert run.replay(core, args, plan, {})["exact_replay"]
        assert run.ex.read(second / "REPLAY.json")["state_sha256"] == expected
        assert tree_hash(original.model.state_dict()) == contract["original_base_sha256"]
    finally:
        torch.set_num_threads(threads)


@pytest.mark.parametrize("damage", [None, "body", "source", "receipt", "replay", "commit"])
def test_training_requires_separate_exact_canary_retirement(tmp_path, damage):
    raw, ckpt = tmp_path / "raw", tmp_path / "checkpoints"
    (raw / "canary").mkdir(parents=True)
    (raw / "replay").mkdir()
    ckpt.mkdir()
    checkpoint = dict(bytes=10, sha256="1" * 64, state_sha256="2" * 64)
    run.ex.write_new(raw / "canary/CHECKPOINT_canary_step1.pt.json", checkpoint)
    run.ex.write_new(raw / "replay/REPLAY.json", dict(exact=True))
    ledger = dict(
        status="SPENT_CANARY_RETIRED_AFTER_EXACT_REPLAY",
        source_commit="a" * 40,
        checkpoint=checkpoint,
        path=str(ckpt / "canary_step1.pt"),
        files_deleted=1,
        replay_receipt_sha256=run.ex.digest(raw / "replay/REPLAY.json"),
        published_ledger_commit="b" * 40,
    )
    if damage == "body":
        (ckpt / "canary_step1.pt").write_bytes(b"still present")
    elif damage == "source":
        ledger["source_commit"] = "c" * 40
    elif damage == "receipt":
        ledger["checkpoint"] = {}
    elif damage == "replay":
        ledger["replay_receipt_sha256"] = "d" * 64
    elif damage == "commit":
        ledger["published_ledger_commit"] = ""
    run.ex.write_new(tmp_path / "CANARY_RETIREMENT.json", ledger)
    if damage is None:
        assert run.validate_retirement(raw, ckpt, dict(source_commit="a" * 40), {})["sha256"]
    else:
        with pytest.raises(ValueError):
            run.validate_retirement(raw, ckpt, dict(source_commit="a" * 40), {})
