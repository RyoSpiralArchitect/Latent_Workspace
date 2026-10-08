import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_v14_centered_bridge as run  # noqa: E402


def _previous():
    return json.loads(
        (ROOT / "provenance/pilots/v14_precision_bridge_20261009/raw/report.json").read_text()
    )


def _plan():
    plan = json.loads(run.prior.PLAN.read_text())
    plan["format"] = "latent-workspace-v14-centered-bridge-plan-v1"
    plan["output"] = "runs/v14/centered_bridge_20261009"
    paths = {
        "predecessor": "provenance/pilots/v14_precision_bridge_20261009/raw/report.json",
        "predecessor_trace": "provenance/pilots/v14_mech_repair_20261009/mechanistic/report.json",
        "fresh_preparation": "data/v14_mech_repair/PREPARATION.json",
    }
    for key, path in paths.items():
        plan[key] = {"path": path, "sha256": run.digest(ROOT / path)}
    path = "data/v14_mech_repair/fresh_eval.jsonl"
    plan["data"]["eval"] = {"path": path, "sha256": run.digest(ROOT / path)}
    plan["source_identity"].update({path: run.digest(ROOT / path) for path in run.NEW_SOURCES})
    return plan


def test_schedule_exactly_matches_archived_training():
    old = json.loads(run.prior.PLAN.read_text())
    schedule = run.training_schedule(256, old["training"])
    assert len(schedule) == 4096
    assert set(schedule) == {(world, query) for world in range(256) for query in range(8)}
    for receipt in _previous()["training"].values():
        assert run._stable_hash(schedule) == receipt["schedule_sha256"]


def test_archived_and_centered_initialization_exact():
    states = []
    for cls in (run.PrecisionAwareWorkspaceBridge, run.CenteredValueWorkspaceBridge):
        torch.manual_seed(47)
        bridge = cls(4096, workspace_dim=256, heads=8, slots=4, max_delta_norm=1.0)
        states.append(run.prior.state_hash(bridge))
        assert sum(p.numel() for p in bridge.parameters()) == 4200192
    assert states[0] == states[1]
    old = json.loads(run.prior.PLAN.read_text())
    if str(torch.__version__) == old["expected_runtime"]["torch"]:
        assert states[0] == _previous()["training"]["task"]["initial_state_sha256"]


def test_fresh_plan_passes_without_model_or_weight_loading():
    plan = _plan()
    train, fresh, audit, previous = run.validate_plan(plan)
    assert (len(train), len(fresh)) == (256, 64)
    assert not any(audit["prior_overlaps"].values())
    assert previous["base_unchanged"]
    assert run.execute(plan, dry_run=True)["status"] == "PREPARED_NOT_RUN"


@pytest.mark.parametrize("field", ["training", "bridge", "model", "scenarios"])
def test_unmatched_plan_rejected(field):
    plan = _plan()
    if field == "scenarios":
        plan[field] = plan[field][:-1]
    else:
        plan[field]["unexpected_extra_change"] = True
    with pytest.raises(ValueError, match="Matched"):
        run.validate_plan(plan)


def test_changed_predecessor_or_fresh_identity_rejected():
    for field in ("predecessor", "predecessor_trace", "fresh_preparation"):
        plan = _plan()
        plan[field]["sha256"] = "0" * 64
        with pytest.raises(ValueError, match="identity changed"):
            run.validate_plan(plan)
    plan = _plan()
    plan["data"]["eval"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="Fresh preparation"):
        run.validate_plan(plan)


def test_new_source_identity_coverage_is_required():
    plan = _plan()
    del plan["source_identity"][run.NEW_SOURCES[0]]
    with pytest.raises(ValueError, match="coverage is incomplete"):
        run.validate_plan(plan)


def test_training_receipt_mismatch_fails_closed():
    expected = _previous()["training"]["task"]
    run.match_training_receipt(expected, expected)
    for key in ("initial_state_sha256", "schedule_sha256", "trainable_parameters"):
        changed = {**expected, key: None}
        with pytest.raises(ValueError, match=key):
            run.match_training_receipt(changed, expected)


def test_checkpoint_inventory_has_two_states_per_condition_without_loading():
    inventory = run.checkpoint_inventory(_previous(), verify_bodies=False)
    assert set(inventory) == {"task128", "task256", "semantic128", "semantic256"}
    incomplete = _previous()
    incomplete["training"]["semantic"]["checkpoints"].pop()
    with pytest.raises(ValueError, match="incomplete"):
        run.checkpoint_inventory(incomplete, verify_bodies=False)


def test_complete_and_incomplete_evaluation_denominators():
    single = {
        f"{family}_{cell}": {"row_count": 6144, "rows": [None] * 6144}
        for family in run.FAMILIES
        for cell in run.CELLS
    }
    multi = {
        family: {"trajectory_count": 896, "turn_count": 3584, "rows": [{"turns": [None] * 4}] * 896}
        for family in run.FAMILIES
    }
    assert run.verify_denominators(single, multi) == {
        "single_rows": 24576,
        "trajectories": 1792,
        "turns": 7168,
    }
    bad = copy.deepcopy(single)
    bad["centered_task"]["rows"].pop()
    with pytest.raises(ValueError, match="Single-turn denominator"):
        run.verify_denominators(bad, multi)
    bad = copy.deepcopy(multi)
    bad["centered"]["turn_count"] -= 1
    with pytest.raises(ValueError, match="Four-turn denominator"):
        run.verify_denominators(single, bad)


def test_small_training_uses_new_class_and_roundtrips_two_small_checkpoints(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "REPO", tmp_path)
    path = tmp_path / "plan.json"
    path.write_text("{}")
    monkeypatch.setattr(run, "PLAN", path)
    torch.manual_seed(101)
    hidden = torch.randn(2, 3, 5, 8)
    query = torch.randn(2, 8, 1, 8)

    class Store:
        candidate_ids = (0, 1)
        records = [
            {"answers": [[1, 0, 1, 0, 1, 0, 1, 0], [0, 1, 1, 0, 1, 0, 1, 0]]} for _ in range(2)
        ]

        def context(self, world, side):
            return hidden[world, 2 if side == "unrelated" else side].unsqueeze(0)

        def query(self, world, question):
            return query[world, question].unsqueeze(0)

    base = SimpleNamespace(config=SimpleNamespace(hidden_size=8), lm_head=torch.nn.Linear(8, 2))
    base.lm_head.requires_grad_(False)
    plan = {
        "model": {"revision": "unit-test"},
        "bridge": {"workspace_dim": 4, "heads": 2, "slots": 3, "max_delta_norm": 1.0},
        "training": {
            **json.loads(run.prior.PLAN.read_text())["training"],
            "steps": 2,
            "save_steps": [1, 2],
            "batch_size": 4,
        },
    }
    output = tmp_path / "weights"
    output.mkdir()
    bridge, receipt = run.train_cell("semantic", Store(), base, plan, output, torch.device("cpu"))
    assert isinstance(bridge, run.CenteredValueWorkspaceBridge)
    assert not bridge.training and receipt["final_checkpoint_reload_exact"]
    assert receipt["writer_gradient_nonzero_after_step1"]
    assert receipt["rows"][0]["query_projection_gradient_l2"] == 0
    assert receipt["rows"][1]["query_projection_gradient_l2"] > 0
    assert receipt["rows"][1]["attention_q_projection_gradient_l2"] > 0
    assert [row["loss_parameter_step"] for row in receipt["rows"]] == [0, 1]
    assert len(receipt["checkpoints"]) == 2
    assert receipt["resumed_from_old_weights"] is False
    for checkpoint in receipt["checkpoints"]:
        payload = torch.load(tmp_path / checkpoint["path"], weights_only=True)
        assert payload["bridge_kind"] == "centered_values"
        assert payload["plan_sha256"] == run.digest(path)
        assert checkpoint["sha256"] == run.digest(tmp_path / checkpoint["path"])


def test_production_centering_matches_old_intervention_and_fails_on_mismatch(monkeypatch):
    torch.manual_seed(99)
    config = {"workspace_dim": 4, "heads": 2, "slots": 3, "max_delta_norm": 1.0}
    legacy = run.PrecisionAwareWorkspaceBridge(8, **config).eval()
    with torch.no_grad():
        legacy.up.weight.normal_(std=0.1)
    context, query = torch.randn(1, 5, 8), torch.randn(1, 1, 8)
    store = SimpleNamespace(context=lambda _w, _s: context, query=lambda _w, _q: query)
    before = run.prior.state_hash(legacy)
    result = run.centered_intervention_identity_gate(
        legacy, store, {"bridge": config}, torch.device("cpu")
    )
    assert result["passed"] and result["max_absolute_error"] < 1e-5
    assert run.prior.state_hash(legacy) == before
    original = run.intervention_delta

    def changed(*args, **kwargs):
        return original(*args, **kwargs) + 0.1

    monkeypatch.setattr(run, "intervention_delta", changed)
    with pytest.raises(ValueError, match="equivalence failed"):
        run.centered_intervention_identity_gate(
            legacy, store, {"bridge": config}, torch.device("cpu")
        )
