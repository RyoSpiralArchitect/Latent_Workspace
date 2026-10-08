import copy
import sys
from pathlib import Path

import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_v14_precision_bridge as run  # noqa: E402


def test_actual_split_disjoint_and_unrelated_entity_complement():
    train = run.load_records(ROOT / "data/v10/functional_train.jsonl")
    evaluation = run.load_records(ROOT / "data/v10/functional_eval.jsonl")
    audit = run.split_audit(train, evaluation)
    assert audit["train_world_pairs"] == 256 and not any(audit["overlaps"].values())
    for row in train + evaluation:
        context = run.unrelated_context(row)
        assert all(name not in context for name in row["metadata"]["orders"][0])
        changed = copy.deepcopy(row)
        changed["answers"] = [[0] * 8, [0] * 8]
        changed["queries"] = ["not seen by control"] * 8
        assert run.unrelated_context(changed) == context
    with pytest.raises(ValueError, match="overlap"):
        run.split_audit(train, train[:1])


def test_paired_direction_and_empty_subgroups_are_finite():
    cfg = {
        "donor_margin": 0.25,
        "direction_weight": 0.25,
        "stability_weight": 0.25,
        "unrelated_weight": 0.25,
        "residual_penalty": 0.001,
    }
    labels = torch.tensor([[1, 0], [0, 1]])
    left = torch.tensor([[0.0, 1.0], [1.0, 0.0]], requires_grad=True)
    right = left.flip(-1)
    base = torch.zeros_like(left)
    delta = torch.zeros(6, 1, 4)
    loss, parts = run.objective(
        left, right, base, base, labels, torch.ones(2, dtype=torch.bool), delta, "semantic", cfg
    )
    assert parts["donor_hinge"].item() == 0 and parts["unaffected_gap_square"].item() == 0
    loss.backward()
    assert torch.isfinite(left.grad).all()
    _, wrong = run.objective(
        right, left, base, base, labels, torch.ones(2, dtype=torch.bool), delta, "semantic", cfg
    )
    assert wrong["donor_hinge"] > 0
    _, unaffected = run.objective(
        left, left, base, base, labels, torch.zeros(2, dtype=torch.bool), delta, "task", cfg
    )
    assert unaffected["donor_hinge"].item() == 0


def test_padding_masks_not_query_or_label_dependent():
    hidden, mask = run.pad_contexts([torch.ones(1, 2, 4), torch.ones(1, 3, 4)], torch.device("cpu"))
    assert hidden.shape == (2, 3, 4)
    assert mask.tolist() == [[1, 1, 0], [1, 1, 1]]
    assert hidden[0, 2].eq(0).all()
