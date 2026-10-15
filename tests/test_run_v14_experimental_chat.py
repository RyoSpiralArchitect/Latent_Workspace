"""Model-free contracts for the frozen V14 free-form diagnostic."""

from __future__ import annotations

import copy
import importlib
import sys
from pathlib import Path

import pytest
import torch

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

chat = importlib.import_module("run_v14_experimental_chat")


def test_plan_binds_no_winner_and_full_generation_grid() -> None:
    plan = chat.load_json(chat.PLAN_PATH)
    paths = chat.validate_plan(
        REPO,
        plan,
        require_fresh=False,
        verify_bundles=False,
    )
    assert paths["comparison_path"].is_file()
    assert chat.load_json(paths["comparison_path"])["winner"] == "none"
    assert len(plan["cases"]) == 8
    assert len(plan["regimes"]) == 4
    assert sum(len(model["lanes"]) for model in plan["models"]) * 8 * 4 == 192


def test_prompt_prefix_removes_exactly_one_terminal_answer() -> None:
    assert chat._prompt_prefix([11, 12, 13], [-100, -100, 13]) == [11, 12]
    with pytest.raises(chat.ChatHarnessError, match="one terminal answer"):
        chat._prompt_prefix([11, 12, 13], [-100, 12, -100])
    with pytest.raises(chat.ChatHarnessError, match="one terminal answer"):
        chat._prompt_prefix([11, 12, 13], [-100, 12, 13])


def test_sampling_contract_keeps_greedy_argmax() -> None:
    logits = torch.tensor([-1.0, 3.0, 2.0])
    assert chat._sample_token(
        logits,
        temperature=0.0,
        top_p=1.0,
        generator=None,
    ) == 1


def test_summary_keeps_direction_and_stability_separate() -> None:
    rows = []
    for affected, intact_choice, twin_choice, donor in (
        (True, 0, 1, 1),
        (False, 0, 0, 0),
    ):
        common = {
            "model": "task",
            "case_id": "affected" if affected else "unaffected",
            "regime": "greedy",
            "affected": affected,
            "target_correct": True,
            "original_correct": True,
            "donor_correct": True,
            "donor_answer": donor,
        }
        intact = copy.deepcopy(common)
        intact.update(
            {
                "lane": "deferred_intact",
                "first_token_choice": intact_choice,
            }
        )
        twin = copy.deepcopy(common)
        twin.update(
            {
                "lane": "deferred_twin",
                "first_token_choice": twin_choice,
            }
        )
        rows.extend((intact, twin))
    report = chat._summary(rows)["intact_twin_pairs"]["task"]
    assert report["affected_changed_fraction"] == 1.0
    assert report["affected_changed_to_donor_fraction"] == 1.0
    assert report["unaffected_same_fraction"] == 1.0
