"""Offline selection/dispatch/receipt checks. Stub routing does not run a model."""

import ast
import copy
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import continue_v16_adapter_full as run


def test_original_proof_preserves_incomplete_and_never_started_full():
    result = run.verify_original()
    assert result["run_status"] == "INCOMPLETE_NO_RETRY"
    assert result["matched_modes"] == result["replayed_modes"] == ["frozen"]
    assert result["journaled_backward_pairs"] == 80
    assert result["file_count"] == 26


@pytest.mark.parametrize("mutation", ["edit", "add_full", "remove", "symlink"])
def test_original_bundle_change_rejected(tmp_path, mutation):
    bundle = tmp_path / "original"
    shutil.copytree(run.ROOT / run.ORIGINAL, bundle)
    if mutation == "edit":
        (bundle / "README.md").write_text("changed")
    elif mutation == "add_full":
        (bundle / "raw/full_legacy_step1_pairs.jsonl").write_text("{}\n")
    elif mutation == "remove":
        (bundle / "raw/FINISHED.json").unlink()
    else:
        (bundle / "extra").symlink_to(bundle / "README.md")
    with pytest.raises(ValueError):
        run.verify_original(bundle)


@pytest.mark.parametrize(
    "key,value",
    [
        ("selected_modes", ["frozen", "full"]),
        ("selected_modes", ["frozen"]),
        ("planned_backward_pairs", 160),
        ("planned_unique_windows", 2),
        ("planned_replay_windows", 0),
        ("no_retry", False),
        ("judge_calls", 1),
        ("new_sequences", 1),
        ("weight_deletions", 1),
        ("old_expression_gate", "PASS"),
        ("original_source_commit", "0" * 40),
        ("original_bundle_sha256", "0" * 64),
    ],
)
def test_selection_rejects_scope_drift(key, value):
    plan = run.read(run.ROOT / run.PLAN)
    run.validate_selection(plan)
    plan[key] = value
    with pytest.raises(ValueError, match="authorization/selection"):
        run.validate_selection(plan)


@pytest.mark.parametrize("failure", [None, "legacy", "adapter_v2", "replay"])
def test_dispatch_full_once_and_never_retry(tmp_path, failure):
    calls, writes, guards = [], [], []

    def arm(*args):
        mode, impl = args[1:3]
        calls.append((mode, impl))
        if impl == failure:
            raise RuntimeError("stop without retry")
        return dict(initial={}, windows=[], features={}, contract={})

    def replay(*args):
        calls.append((args[1], "replay"))
        if failure == "replay":
            raise RuntimeError("stop without retry")
        return {"exact": True}

    core = SimpleNamespace(
        arm=arm,
        replay=replay,
        clean_between_arms=lambda: None,
        write_new=lambda p, v: writes.append(p.name),
    )
    args = SimpleNamespace(output=tmp_path)
    plan = run.read(run.ROOT / "configs/v16/ADAPTER_MIGRATION_PLAN.json")

    def invoke():
        return run.full_work(
            core, args, plan, {}, {}, {}, [], lambda *a, **kw: guards.append((a, kw)), {}
        )

    if failure:
        with pytest.raises(RuntimeError, match="without retry"):
            invoke()
    else:
        invoke()
        assert writes == ["full_EQUIVALENCE.json", "full_REPLAY.json"]
    expected = [("full", "legacy"), ("full", "adapter_v2"), ("full", "replay")]
    limit = {None: 3, "legacy": 1, "adapter_v2": 2, "replay": 3}[failure]
    assert calls == expected[:limit]
    assert guards == [
        (
            ("full:admission",),
            {
                "admission": True,
                "forecast_bytes": plan["storage_forecast_bytes"],
            },
        )
    ]


def test_entry_top_level_uses_only_standard_library():
    tree = ast.parse(Path(run.__file__).read_text())
    imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not any("torch" in ast.unparse(n) or "scripts" in ast.unparse(n) for n in imports)


@pytest.fixture
def terminal(tmp_path):
    """Synthetic publication fixture, not new 7B observations."""
    original = run.ROOT / run.ORIGINAL / "raw"
    raw = tmp_path / "raw"
    raw.mkdir()
    for path in original.iterdir():
        if path.name == "FINISHED.json":
            continue
        target = raw / path.name.replace("frozen_", "full_")
        shutil.copyfile(path, target)
        if path.name.endswith("CONTEXT.json"):
            row = run.read(target)
            row["contract"]["full_update"] = True
            target.write_text(json.dumps(row))
    started = run.read(raw / "STARTED.json")
    # Extend the parent seal with the additive execution files for this fixture.
    for name in (run.ENTRY, run.PLAN):
        started["seal"]["source_hashes"][name] = run.digest(run.ROOT / name)
    started["source_check"].update(
        entry=run.ENTRY, source_files=len(started["seal"]["source_hashes"])
    )
    started.update(selection=run.read(run.ROOT / run.PLAN), original=run.verify_original())
    (raw / "STARTED.json").write_text(json.dumps(started))
    (tmp_path / "SOURCE_SEAL.json").write_text(json.dumps(started["seal"]))
    finished = {
        "status": run.PASS,
        "completed_modes": ["full"],
        "complete_unique_windows": 4,
        "complete_replay_windows": 1,
        "complete_backward_pairs": 80,
        **run.CEILING,
    }
    finished["files"] = run.manifest(raw)
    (raw / "FINISHED.json").write_text(json.dumps(finished))
    return raw


def test_offline_pass_keeps_original_incomplete_and_scientific_fail(terminal):
    result = run.verify(terminal)
    assert result["combined_backward_pairs"] == 160
    assert result["complete_unique_windows"] == 4
    assert result["original_status"] == "INCOMPLETE_NO_RETRY"
    assert result["old_expression_gate"] == "FAIL"
    assert result["checkpoint_bytes_reloaded_offline"] is False


@pytest.mark.parametrize("mutation", ["pair", "window", "missing", "count", "frozen", "seal"])
def test_offline_rejects_mutations_even_with_rehashed_terminal(terminal, mutation):
    if mutation == "pair":
        p = terminal / "full_replay_step2_pairs.jsonl"
        p.write_text("\n".join(p.read_text().splitlines()[:-1]) + "\n")
    elif mutation == "window":
        p = terminal / "full_adapter_v2_step1.json"
        row = run.read(p)
        row["pairs"][0]["components"]["loss"] += 0.001
        p.write_text(json.dumps(row))
    elif mutation == "missing":
        (terminal / "full_adapter_v2_step1_CHECKPOINT.json").unlink()
    elif mutation == "frozen":
        (terminal / "frozen_replay_step2_pairs.jsonl").write_text("{}\n")
    elif mutation == "seal":
        p = terminal / "STARTED.json"
        row = run.read(p)
        row["seal"]["source_hashes"] = {}
        p.write_text(json.dumps(row))
    p = terminal / "FINISHED.json"
    finished = copy.deepcopy(run.read(p))
    finished["files"] = run.manifest(terminal)
    finished["files"].pop("FINISHED.json")
    if mutation == "count":
        finished["complete_backward_pairs"] = 64
    p.write_text(json.dumps(finished))
    with pytest.raises(ValueError):
        run.verify(terminal)
