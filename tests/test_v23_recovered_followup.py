"""Offline provenance/recipe guards. No model loading or paid requests."""

import copy
from types import SimpleNamespace

import pytest
import run_v23_recovered_mmlu_pro as pro
import v23_recovered_bank as bank
import v23_recovered_judge as judge


def arms():
    p = bank.ex.read(bank.ROOT / "configs/v22/BASE_COMPARISON_01.json")
    rows = [
        dict(
            id=r["id"],
            seed=s,
            prompt=r["prompt"],
            text="Same mock-only answer.",
            max_new_tokens=256,
            temperature=0.7,
            top_p=0.9,
            stop_reason="length",
        )
        for r in p["free_prompts"]
        for s in p["generation"]["seeds"]
    ]
    return {a: {"free": copy.deepcopy(rows)} for a in ("base", "off", "on")}


def test_all_answers_and_fixed_controls_no_changed_only_selection():
    cases = bank.cases_from_arms(arms(), bank.judge.plan())
    assert len(cases) == 75
    assert sum("expected" not in c for c in cases) == 72
    assert len({tuple(c["unit"]) for c in cases}) == 24
    requests = judge.requests_for(cases)
    assert len(requests) == len({r["id"] for r in requests}) == 174
    assert sum(r["repeat"] == 1 for r in requests) == 24
    assert all(set(r["shown"]) == {"task", "A", "B"} for r in requests)
    for r in requests:
        if r["repeat"]:
            first = next(
                x
                for x in requests
                if x["case_id"] == r["case_id"] and x["order"] == r["order"] and x["repeat"] == 0
            )
            assert first["body"] == r["body"] and first["id"] != r["id"]


@pytest.mark.parametrize("damage", ["missing", "duplicate", "seed", "prompt", "cap", "temperature"])
def test_missing_or_changed_answers_block_judge(damage):
    data = arms()
    rows = data["on"]["free"]
    if damage == "missing":
        rows.pop()
    elif damage == "duplicate":
        rows.append(rows[0])
    else:
        key = "max_new_tokens" if damage == "cap" else damage
        rows[0][key] = "changed"
    with pytest.raises(ValueError):
        bank.cases_from_arms(data, bank.judge.plan())


def test_request_construction_matches_legacy_selection_on_mock_complete_bank(tmp_path):
    data = arms()
    p = bank.judge.plan()
    (tmp_path / "raw").mkdir()
    bank.ex.write_new(tmp_path / "SOURCE_SEAL.json", {"source_commit": p["generation_source"]})
    for a in data:
        folder = tmp_path / "raw" / a
        folder.mkdir()
        with (folder / "free.jsonl").open("x") as stream:
            for row in data[a]["free"]:
                stream.write(bank.ex.canonical(row) + "\n")
        bank.ex.write_new(
            folder / "FINISHED.json",
            dict(
                status="V23_EVALUATION_ARM_COMPLETE",
                files=bank.ex.manifest(folder),
            ),
        )
    bank.ex.write_new(
        tmp_path / "raw/FINISHED.json",
        dict(
            status=p["generation_status"],
            files=bank.ex.manifest(tmp_path / "raw"),
        ),
    )
    legacy, _ = bank.judge.study_cases(tmp_path, p)
    assert bank.cases_from_arms(data, p) == legacy
    assert judge.requests_for(legacy) == judge.requests_for(bank.cases_from_arms(data, p))


@pytest.mark.parametrize("damage", ["incomplete", "tampered"])
def test_terminal_rejects_incomplete_or_changed_bytes(tmp_path, damage):
    bank.ex.write_new(tmp_path / "ROW.json", {"mock_only": True})
    files = bank.ex.manifest(tmp_path)
    bank.ex.write_new(
        tmp_path / "FINISHED.json",
        dict(
            status="INCOMPLETE_NO_RETRY" if damage == "incomplete" else "COMPLETE",
            files=files,
        ),
    )
    if damage == "tampered":
        bank.ex.write_new(tmp_path / "UNEXPECTED.json", {"extra": True})
    with pytest.raises(ValueError):
        bank.terminal(tmp_path, "COMPLETE")


def test_benchmark_dispatch_passes_original_plan_and_explicit_origins(monkeypatch):
    p = bank.ex.read(bank.ROOT / pro.PLAN)
    pro.validate(p)
    origins = {"mock_only": True, "schema": "explicit-not-original-success"}
    monkeypatch.setattr(bank, "verify", lambda: ({}, origins))

    def run(core, args, plan, seal, *, predecessor_fn):
        assert plan == bank.ex.read(bank.ROOT / pro.original.PLAN)
        assert predecessor_fn(plan) == origins
        return {"no_model": True}

    monkeypatch.setattr(pro.original, "run", run)
    assert pro.run(None, None, p, {}) == {"no_model": True}


def test_explicit_predecessor_failure_precedes_model_preparation(tmp_path, monkeypatch):
    def blocked(_):
        raise ValueError("mock incomplete recovered bank")

    def forbidden(*args):
        raise AssertionError("Must not prepare a model")

    monkeypatch.setattr(pro.original.previous, "prepare", forbidden)
    with pytest.raises(ValueError, match="mock incomplete"):
        pro.original.run(
            None,
            SimpleNamespace(output=tmp_path),
            bank.ex.read(bank.ROOT / pro.original.PLAN),
            {},
            predecessor_fn=blocked,
        )


def test_legacy_calibration_source_still_exact():
    folder = bank.ROOT / "provenance/pilots/v23_behavior_judge01_20261022/calibration"
    seal, _, _ = bank.judge.verify(folder)
    assert seal["source"] == bank.judge.source()
    assert bank.judge.replay(folder)["calibration_gate"] == "PASS"


def test_original_source_still_verifies_from_git_without_loading_model():
    folder = bank.ROOT / "provenance/pilots/v23_comparison01_20261022/furnace"
    seal = bank.source_seal(folder, bank.plan()["original_source"])
    assert len(seal["source_hashes"]) == 774


@pytest.mark.parametrize("published", [False, True])
def test_checkpoint_inventory_never_allows_saved_files(tmp_path, published):
    (tmp_path / "checkpoints").mkdir()
    bank.no_saved_checkpoints(tmp_path, published_copy=published)
    (tmp_path / "checkpoints/forbidden.pt").write_bytes(b"not a model")
    with pytest.raises(ValueError, match="No saved"):
        bank.no_saved_checkpoints(tmp_path, published_copy=published)


def test_missing_empty_directory_only_allowed_for_published_copy(tmp_path):
    with pytest.raises(ValueError, match="No saved"):
        bank.no_saved_checkpoints(tmp_path)
    bank.no_saved_checkpoints(tmp_path, published_copy=True)
