from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

prepare = importlib.import_module("prepare_v12_calibrated_route")


def _parent() -> dict[str, object]:
    return json.loads(
        (
            REPO / "configs/v11/conditions/config_O0_slots4_k1_symmetric_choice_repair.json"
        ).read_text(encoding="utf-8")
    )


def test_v12_sidecar_freezes_transport_and_update_ownership() -> None:
    step1 = prepare.make_config(
        _parent(),
        workspace_learning_rate=3e-5,
        seed=43,
        max_steps=1,
        branch="task",
    )
    assert step1["functional"]["route_mode"] == "inline_sidecar"
    assert step1["functional"]["memory_mode"] == "slots"
    assert step1["functional"]["slot_count"] == 4
    assert step1["functional"]["counterfactual_weight"] == 0.0
    assert step1["functional"]["stability_weight"] == 0.0
    assert step1["train"]["learning_rate"] == 1e-7
    assert step1["train"]["workspace_learning_rate"] == 3e-5
    assert step1["train"]["base_release_step"] == 1
    assert step1["train"]["max_steps"] == 1
    assert step1["train"]["gradient_accumulation_offload"] == "cpu_accumulate"
    assert step1["attribution"]["clip_mode"] == "per_family"
    assert step1["attribution"]["base_max_grad_norm"] == 1.0
    assert step1["attribution"]["workspace_max_grad_norm"] == 0.25


def test_semantic_branch_changes_only_frozen_semantic_pressure() -> None:
    task = prepare.make_config(
        _parent(),
        workspace_learning_rate=1e-4,
        seed=44,
        max_steps=4,
        branch="task",
    )
    semantic = prepare.make_config(
        _parent(),
        workspace_learning_rate=1e-4,
        seed=44,
        max_steps=4,
        branch="semantic",
    )
    task["functional"].pop("counterfactual_weight")
    task["functional"].pop("stability_weight")
    semantic["functional"].pop("counterfactual_weight")
    semantic["functional"].pop("stability_weight")
    task["train"]["output_dir"] = "<normalized>"
    semantic["train"]["output_dir"] = "<normalized>"
    assert task == semantic


def test_refinement_releases_base_only_after_four_frozen_updates() -> None:
    candidate = prepare.make_config(
        _parent(),
        workspace_learning_rate=1e-5,
        seed=45,
        max_steps=16,
        branch="semantic",
    )
    assert candidate["train"]["resume_from"] == "none"
    assert candidate["train"]["max_steps"] == 16
    assert candidate["train"]["base_release_step"] == 4
    assert candidate["train"]["eval_every"] == 4
    assert candidate["assays"]["necessity"]["enabled"] is True


def test_contract_covers_exact_predeclared_matrix() -> None:
    contract = json.loads((REPO / "configs/v12/CONTRACT.json").read_text(encoding="utf-8"))
    assert contract["frozen_before_execution"] is True
    assert len(contract["v12_1_step1_response"]["artifacts"]) == 3
    assert len(contract["v12_2_stage4"]["artifacts"]) == 18
    assert len(contract["v12_3_refinement16"]["artifacts"]) == 18
    assert contract["v12_1_step1_response"]["condition_order"] == [
        "1e_5",
        "3e_5",
        "1e_4",
    ]
    assert contract["execution_boundaries"]["run_only_selected_lr_after_step1"]
    assert contract["execution_boundaries"]["no_14b_scale_up_authorized"]
