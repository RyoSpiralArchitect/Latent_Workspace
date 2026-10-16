"""The engine's Availability endpoint reproduces V16's contrasts and V19's diagnosis."""

import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

from latent_workspace import availability
from latent_workspace_ft_v10 import v16_comparison_eval
from scripts import run_v19_frozen_diagnostic as v19

ROOT = Path(__file__).resolve().parents[1]
V19 = ROOT / "provenance/pilots/v19_frozen_dual_budget_20261015/furnace/raw/ordered_cap025"
RULE = json.loads((ROOT / "configs/v19/FROZEN_DIAGNOSTIC_PLAN.json").read_text())["endpoints"]
V16_FACTORS = {**availability.FACTORS, "common_slots": ("common_intact", "common_twin")}


def test_availability_reproduces_v19():
    """From V19's saved scores alone: every contrast, then the recorded diagnosis."""
    report = json.loads(gzip.open(V19 / "eval_final_step512.json.gz").read())
    rows = {(r["world"], r["query"], r["condition"]): r for r in report["rows"]}
    assert set(V16_FACTORS) == set(v16_comparison_eval.FACTORS)
    rebuilt = []
    for stored in report["contrasts"]:
        left, right = V16_FACTORS[stored["factor"]]
        key = stored["world"], stored["query"]
        new = availability.contrast(
            *key,
            stored["factor"],
            stored["labels"],
            availability.choice(rows[(*key, left)]["scores"]),
            availability.choice(rows[(*key, right)]["scores"]),
        )
        for field in ("affected", "labels", "donor_directed_gap_change"):
            assert new[field] == stored[field], (stored, field)
        assert new["left_prediction"] == stored["left_prediction"]
        assert new["right_prediction"] == stored["right_prediction"]
        rebuilt.append(new)
    recorded = json.loads((V19 / "DIAGNOSIS.json").read_text())
    diagnosis = availability.diagnose(rebuilt, RULE)
    assert diagnosis == {k: recorded[k] for k in diagnosis}
    assert diagnosis["verdict"] == "NOT_ESTABLISHED" and diagnosis["flips"]["actual"] == 0


def planted(worlds, flips, donor_worlds, random_flips):
    """Contrasts with chosen flip counts and a chosen donor-directed world majority."""
    contrasts = []
    for w in range(worlds):
        for q, labels in enumerate(([1, 0], [0, 1], [1, 1])):
            for factor in ("actual", "random_pair", "reversed"):
                index = 2 * w + q
                if q == 2:
                    left = right = labels[0]
                elif factor == "actual":
                    left, right = labels if index < flips else (labels[0], labels[0])
                elif factor == "random_pair":
                    left, right = labels if index < random_flips else (labels[0], labels[0])
                else:
                    left = right = labels[0]
                change = (1.0 if w < donor_worlds else -1.0) if q < 2 else 0.0
                contrasts.append(
                    dict(
                        world=w,
                        query=q,
                        factor=factor,
                        affected=q < 2,
                        labels=labels,
                        donor_directed_gap_change=change if q < 2 else None,
                        left_prediction=left,
                        right_prediction=right,
                    )
                )
    return contrasts


@pytest.mark.parametrize(
    "flips,donor_worlds,random_flips,verdict",
    [
        (60, 30, 4, "CONTENT_REACHES_ANSWERS"),
        (20, 30, 0, "DIRECTIONAL_ONLY"),
        (60, 30, 50, "DIRECTIONAL_ONLY"),
        (60, 18, 4, "NOT_ESTABLISHED"),
    ],
)
def test_diagnose_is_v19s_rule_on_every_branch(flips, donor_worlds, random_flips, verdict):
    contrasts = planted(32, flips, donor_worlds, random_flips)
    records = [{"queries": ["Is A ranked above B?"] * 3} for _ in range(32)]
    report = dict(contrasts=contrasts, rows=[], direct_base=[])
    expected = v19.diagnose(report, records, RULE)
    got = availability.diagnose(contrasts, RULE)
    assert got == {k: expected[k] for k in got} and got["verdict"] == verdict


def test_random_memory_is_v16s_control():
    memory = torch.randn(1, 4, 6)
    mask = torch.tensor([[1, 1, 1, 0]])
    calls = iter(
        [(memory, mask), (2 * memory, mask), (memory, mask), (memory, mask), (memory, mask)]
    )
    store = SimpleNamespace(write=lambda bridge, world, key: next(calls))
    source = v16_comparison_eval.memory_bank(SimpleNamespace(bridge=None), store, 3, seed=40)
    generator = torch.Generator().manual_seed(43)
    for name, values in (("intact", memory), ("twin", 2 * memory)):
        random = availability.norm_matched_random(values, mask, generator)
        assert torch.equal(random, source[f"random_{name}"][0])
    assert torch.allclose(random.norm(), (2 * memory)[:, :3].norm())
