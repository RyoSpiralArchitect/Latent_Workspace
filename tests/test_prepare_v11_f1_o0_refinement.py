from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

prepare = importlib.import_module("prepare_v11_f1_o0_refinement")


def test_o0_stage4_preserves_active_route_and_freezes_transport() -> None:
    parent = json.loads(
        (
            REPO / "configs/v11/conditions/config_O0_slots4_k1_symmetric_choice_repair.json"
        ).read_text(encoding="utf-8")
    )
    candidate = prepare.make_o0(parent, seed=44, max_steps=4)
    assert candidate["functional"]["route_mode"] == "deferred"
    assert candidate["functional"]["memory_mode"] == "slots"
    assert candidate["functional"]["slot_count"] == 4
    assert candidate["functional"]["injection_scale"] == 1.0
    assert candidate["train"]["learning_rate"] == 1e-7
    assert candidate["train"]["workspace_learning_rate"] == 3e-4
    assert candidate["train"]["gradient_accumulation_offload"] == "cpu_accumulate"
    assert candidate["train"]["gradient_accumulation_steps"] == 8
    assert candidate["train"]["max_steps"] == 4
    assert candidate["train"]["eval_every"] == 1
    assert candidate["train"]["resume_from"] == "none"
    assert candidate["train"]["allow_schedule_extension"] is False
    assert candidate["assays"]["amputation_eval"] is True
    assert candidate["assays"]["necessity"]["enabled"] is True


def test_refinement_is_fresh_shared_horizon_not_resume_extension() -> None:
    f1_parent = json.loads(
        (
            REPO / "configs/v11/conditions/config_F1_seed_robustness_lr_1e_7_seed43_step4.json"
        ).read_text(encoding="utf-8")
    )
    o0_parent = json.loads(
        (
            REPO / "configs/v11/conditions/config_O0_slots4_k1_symmetric_choice_repair.json"
        ).read_text(encoding="utf-8")
    )
    f1 = prepare.make_f1(f1_parent, seed=43)
    o0 = prepare.make_o0(o0_parent, seed=43, max_steps=16)
    for config in (f1, o0):
        assert config["train"]["max_steps"] == 16
        assert config["train"]["eval_every"] == 4
        assert config["train"]["resume_from"] == "none"
        assert config["train"]["allow_schedule_extension"] is False
        assert config["train"]["learning_rate"] == 1e-7
        assert config["train"]["workspace_learning_rate"] == 3e-4
    assert f1["functional"]["route_mode"] == "inline"
    assert o0["functional"]["route_mode"] == "deferred"


def test_execution_orders_cover_every_seed_without_duplicates() -> None:
    assert prepare.STAGE4_ORDER == ("O0_seed43", "O0_seed44", "O0_seed45")
    assert len(prepare.REFINEMENT_ORDER) == 6
    assert len(set(prepare.REFINEMENT_ORDER)) == 6
    for seed in prepare.SEEDS:
        assert {f"F1_seed{seed}", f"O0_seed{seed}"}.issubset(set(prepare.REFINEMENT_ORDER))
