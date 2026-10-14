"""Offline diagnostic arithmetic rejection tests, not model quality evidence."""

import copy

import pytest
import torch
from test_v15_native_runner import make_store
from test_v16_full_comparison import build

from scripts import run_v16_adapter_migration as core
from scripts import run_v16_full_comparison as run
from scripts import verify_v16_full_comparison as verify


@pytest.fixture
def report(monkeypatch):
    core.load_runtime()
    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    learner = build("common", torch.float32)
    plan = run.read(run.ROOT / run.PLAN)
    value = run.evaluate(
        core, learner, make_store(monkeypatch, learner), None, lambda *a: None, plan
    )
    yield value, plan
    torch.set_num_threads(previous)


def test_offline_replays_evaluation(report):
    value, plan = report
    assert verify.verify_evaluation(value, plan, 0) == value["summary"]


@pytest.mark.parametrize(
    "fault", ["missing", "duplicate", "control_label", "donor_sign", "summary", "reference_order"]
)
def test_offline_rejects_diagnostic_corruption(report, fault):
    value, plan = report
    bad = copy.deepcopy(value)
    if fault == "missing":
        bad["rows"].pop()
    elif fault == "duplicate":
        bad["rows"][1] = bad["rows"][0]
    elif fault == "control_label":
        bad["rows"][6]["target"] = 1
    elif fault == "donor_sign":
        bad["contrasts"][0]["donor_directed_gap_change"] = 1
    elif fault == "summary":
        bad["summary"]["factors"]["actual"]["positive"] += 1
    else:
        bad["original_base"].reverse()
    with pytest.raises(ValueError):
        verify.verify_evaluation(bad, plan, 0)
