"""Offline-only publication checks; not additional GPU qualification evidence."""

import copy
import gzip
import json
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import verify_v22_full_ft as verify  # noqa: E402

DATA = ROOT / "provenance/data/v22_english_mixture01_20261021/furnace"


def test_frozen_data_projection_source_and_file_hashes():
    manifest = verify.read(DATA / "MANIFEST.json")
    for name, expected in manifest["source"].items():
        assert verify.digest(ROOT / name) == expected
    for name, expected in manifest["files"].items():
        if name == "rows.json.gz":
            assert not (DATA / name).exists()
        else:
            assert verify.digest(DATA / name) == expected["sha256"]
            assert (DATA / name).stat().st_size == expected["bytes"]


def test_recount_population_and_training_schedule_from_text_free_index():
    plan = verify.read(ROOT / "configs/v22/FULL_FT_01.json")
    index, schedule = verify.data_index(DATA, plan)
    summary = verify.read(DATA / "SUMMARY.json")
    counts, tokens, groups = Counter(), Counter(), {}
    for row in index.values():
        assert not {"input_ids", "labels", "memory_ids", "text", "messages"} & row.keys()
        assert row["language"] == "en"
        assert groups.setdefault(row["group_id"], row["split"]) == row["split"]
        key = f"{row['split']}/{row['role']}"
        counts[key] += 1
        tokens[key] += row["supervised_tokens"]
    assert dict(counts) == summary["counts"] and dict(tokens) == summary["supervised_tokens"]
    selected = [index[k] for w in schedule["training"] for k in w]
    assert len({r["key"] for r in selected}) == len(selected) == 723
    assert sum(r["supervised_tokens"] for r in selected) == 20860
    assert all(index[k]["split"] == "dev" for k in schedule["development"])
    assert len(schedule["development"]) == 40
    old_path = ROOT / "provenance/data/native_preservation_bank01_20261021/furnace/index.json.gz"
    old = json.loads(gzip.decompress(old_path.read_bytes()))
    assert len([r for r in old if r["language"] == "ja"]) == 38
    preserved = [r for r in index.values() if r["role"] != "world"]
    assert len(preserved) == 1900


@pytest.mark.parametrize("fault", [None, "bytes", "ceiling"])
def test_terminal_requires_exact_manifest_and_unchanged_claims(tmp_path, fault):
    (tmp_path / "STARTED.json").write_text("{}")
    end = dict(
        files=verify.manifest(tmp_path),
        new_sequences=0,
        judge_calls=0,
        weight_deletions=0,
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
    )
    if fault == "ceiling":
        end["old_expression_gate"] = "PASS"
    (tmp_path / "FINISHED.json").write_text(json.dumps(end))
    if fault == "bytes":
        (tmp_path / "STARTED.json").write_text('{"changed":true}')
    if fault is None:
        assert verify.terminal(tmp_path)[1] == end
    else:
        with pytest.raises(ValueError):
            verify.terminal(tmp_path)


@pytest.mark.parametrize("tamper", [False, True])
def test_runner_checkpoint_helpers_bind_bytes_and_exact_restored_state(tmp_path, tamper):
    import run_v22_full_ft as run
    from test_native_owner import setup, update

    owner, batch = setup()
    original = copy.deepcopy(owner.graph)
    update(owner, batch)
    first, second, weights = (tmp_path / n for n in ("first", "second", "weights"))
    for path in (first, second, weights):
        path.mkdir()
    core = SimpleNamespace(snapshot_admission=lambda *args: None)
    guard = lambda *args, **kwargs: None  # noqa: E731
    plan = dict(checkpoint_names=["canary_step1.pt"], checkpoint_max_bytes=2**20)
    args = SimpleNamespace(output=first, checkpoints=weights)
    run.checkpoint(owner, core, args, plan, guard, "canary_step1.pt")
    args.output = second
    if tamper:
        (weights / "canary_step1.pt").write_bytes(b"corrupted")
        with pytest.raises(ValueError, match="file receipt"):
            run.restore(
                original,
                owner.config,
                owner.run_contract,
                core,
                args,
                plan,
                guard,
                first,
                "canary_step1.pt",
            )
    else:
        restored = run.restore(
            original,
            owner.config,
            owner.run_contract,
            core,
            args,
            plan,
            guard,
            first,
            "canary_step1.pt",
        )
        run.common.exact(
            run.common.fingerprint(owner), run.common.fingerprint(restored), "actual runner helper"
        )


def test_retained_failure_keeps_null_activity_and_undispatched_training():
    bundle = ROOT / "provenance/pilots/v22_full_ft01_20261021"
    raw = bundle / "furnace/raw"
    _, dispatch = verify.terminal(raw)
    _, canary = verify.terminal(raw / "canary")
    _, replay = verify.terminal(raw / "replay")
    assert dispatch["status"] == replay["status"] == "INCOMPLETE_NO_RETRY"
    assert dispatch["native_weight_updates"] is replay["native_weight_updates"] is None
    assert canary["native_weight_updates"] == 2
    assert dispatch["completed_roles"] == ["canary"]
    assert not (raw / "DISPATCH_train_a.json").exists()
    assert not (raw / "DISPATCH_train_b.json").exists()
    assert verify.read(raw / "replay/RESTORE.json")["exact"] is True
    assert verify.read(raw / "canary/step2_row0.json") == verify.read(
        raw / "replay/step2_row0.json"
    )
    assert not (raw / "replay/step2.json").exists()
    sample = json.loads((raw / "replay/RESOURCES.jsonl").read_text().splitlines()[-1])
    assert sample["free_bytes"] == 440 * 2**20 < 0.75 * 2**30
    assert sample["reserved"] - sample["allocated"] == 17883978752
    assert len(sample["processes"]) == 1 and sample["processes"][0]["pid"] == sample["own_pid"]
