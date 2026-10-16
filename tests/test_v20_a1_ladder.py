"""Tiny harness for V20 A1, the Availability ladder on V19 (not a real-model receipt)."""

import copy
import os

import pytest
import torch
from test_v19_frozen_diagnostic import build, records, store, tiny_plan

from scripts import run_v16_adapter_migration as core
from scripts import run_v20_a1_ladder as run

DEVICE = os.environ.get("LATENT_V20_TEST_DEVICE", "cpu")
PLAN = run.ex.read(run.ROOT / run.PLAN)
SMALL = {
    "threads": 2,
    "attention": {"width": 8, "steps": 250, "lr": 0.01, "weight_decay": 0.0001, "seeds": [1, 2]},
    "contrast": {"l2": 0.001, "iterations": 100},
    "routes": ["interaction", "common", "delta"],
    "primary_route": "interaction",
}


@pytest.fixture(autouse=True)
def setup():
    core.load_runtime()
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


def test_plan_hash_and_semantics():
    run.validate_plan(PLAN)
    changed = copy.deepcopy(PLAN)
    changed["endpoints"]["alpha"] = 0.05
    with pytest.raises(ValueError, match="plan"):
        run.validate_plan(changed)
    assert run.ROLES == ("extract_initial", "extract_step256", "extract_step512", "probe")


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_extraction_reads_every_condition_with_v19_invariants(monkeypatch, dtype):
    plan = tiny_plan()
    data = records()
    learner, _, _ = build(dtype, "ordered_cap025", plan, data["train"][:4])
    rows = data["final"][:2]
    store_obj, spans, _ = store(monkeypatch, learner, rows)
    tensors, meta = run.extract_rows(learner, store_obj, spans, seed=7)
    worlds, queries, conditions = 2, 8, len(run.CONDITIONS)
    assert tensors["memory"].shape[:2] == (worlds, conditions)
    assert tensors["common"].shape[:3] == (worlds, queries, conditions)
    assert tensors["interaction"].shape == tensors["common"].shape
    assert tensors["query_common"].shape[:2] == (worlds, queries)
    assert len(meta) == worlds * queries
    assert [m["labels"] for m in meta[:8]] == [
        [rows[0]["answers"][0][q], rows[0]["answers"][1][q]] for q in range(8)
    ]
    assert [m["affected"] for m in meta[:8]] == [True, True] + [False] * 6
    assert all(t.dtype == torch.float32 for k, t in tensors.items() if k != "mask")


def planted(worlds, seed, memory_signal=True, read_signal=True, hidden=16, slots=4, width=8):
    """Two reciprocal affected questions per world; content optionally planted per rung."""
    generator = torch.Generator().manual_seed(seed)
    conditions = len(run.CONDITIONS)
    memory = 0.3 * torch.randn(worlds, conditions, slots, width, generator=generator)
    memory[..., 2:6] += torch.eye(slots)[None, None, :, :4]
    common = 0.1 * torch.randn(worlds, 8, conditions, hidden, generator=generator)
    interaction = 0.1 * torch.randn(worlds, 8, conditions, hidden, generator=generator)
    query = torch.zeros(worlds, 8, hidden)
    for q in range(8):
        query[:, q, q % slots] = 1.0
    direction = torch.randn(hidden, generator=torch.Generator().manual_seed(99))  # shared
    meta = []
    for w in range(worlds):
        intact = int(torch.randint(0, 2, (1,), generator=generator))
        for q in range(8):
            if q < 2:
                labels = [intact, 1 - intact] if q == 0 else [1 - intact, intact]
            else:
                value = int(torch.randint(0, 2, (1,), generator=generator))
                labels = [value, value]
            meta.append(
                dict(world=w, query=q, labels=labels, affected=q < 2, hop=1 if q < 2 else 3)
            )
            if q < 2 and read_signal:
                for c in range(conditions):
                    side = 1 if c == 1 else 0
                    interaction[w, q, c] += 2.0 * (2 * labels[side] - 1) * direction
        if memory_signal:
            for c in range(conditions):
                sign = -1.0 if c == 1 else 1.0
                memory[w, c, 0, 0] += 2.0 * sign * (2 * intact - 1)
                memory[w, c, 1, 0] -= 2.0 * sign * (2 * intact - 1)
    tensors = dict(
        memory=memory,
        mask=torch.ones(worlds, conditions, slots),
        common=common,
        interaction=interaction,
        query_common=query,
        query_interaction=query.clone(),
    )
    return tensors, meta


@pytest.mark.parametrize(
    "memory_signal,read_signal,verdict",
    [
        (True, True, "LOST_IN_TRANSPORT"),
        (True, False, "LOST_IN_READING"),
        (False, False, "CONTENT_ABSENT_IN_MEMORY"),
    ],
)
def test_ladder_names_the_rung_where_planted_content_stops(memory_signal, read_signal, verdict):
    train, train_rows = planted(48, 1, memory_signal, read_signal)
    final, final_rows = planted(40, 2, memory_signal, read_signal)
    result = run.ladder_for_state(
        {"train": train, "final": final}, {"train": train_rows, "final": final_rows}, SMALL, 0.01
    )
    assert result["verdict"] == verdict
    assert result["memory_pass"] == memory_signal
    if read_signal:
        assert result["reading"]["interaction"]["accuracy"] > 0.9
    assert set(result["memory"]) == {"memory", "zero", "shuffled"}


def test_offline_verifier_accepts_what_the_runner_writes(tmp_path):
    from safetensors.torch import save_file

    from scripts import verify_v20_a1_ladder as verifier

    plan = copy.deepcopy(PLAN)
    plan["probes"] = SMALL
    features = {"train": planted(256, 1), "final": planted(128, 2)}
    raw = tmp_path / "raw"
    roles = {}
    for pid, state in enumerate(run.STATES, start=100):
        folder = raw / f"extract_{state}"
        folder.mkdir(parents=True)
        shapes = {}
        for split, (tensors, rows) in features.items():
            save_file(
                {k: v.contiguous() for k, v in tensors.items()},
                str(folder / f"FEATURES_{split}.safetensors"),
            )
            run.ex.write_gz(folder / f"ROWS_{split}.json.gz", rows)
            shapes[split] = {k: list(v.shape) for k, v in tensors.items()}
        roles[f"extract_{state}"] = (
            {"pid": pid},
            {"outcome": {"state": state, "splits": shapes}},
            True,
        )
    loaded = {s: run.load_features(raw / f"extract_{s}") for s in run.STATES}
    ladder_json = {
        s: run.ladder_for_state(*loaded[s], SMALL, plan["endpoints"]["alpha"]) for s in run.STATES
    }
    (raw / "probe").mkdir()
    run.ex.write_new(raw / "probe" / "LADDER.json", ladder_json)
    roles["probe"] = (
        {"pid": 200},
        {"outcome": {s: ladder_json[s]["verdict"] for s in run.STATES}},
        True,
    )
    result = verifier.verify_results(raw, plan, roles, refit=True)
    assert result["probes_refitted"] and set(result["verdicts"].values()) == {"LOST_IN_TRANSPORT"}
    stored = run.ex.read(raw / "probe" / "LADDER.json")
    first = stored["initial"]["memory"]["memory"][0]["world_counts"]
    key = next(iter(first))
    first[key] = 2 - first[key]
    (raw / "probe" / "LADDER.json").unlink()
    run.ex.write_new(raw / "probe" / "LADDER.json", stored)
    with pytest.raises(ValueError):
        verifier.verify_results(raw, plan, roles, refit=False)
