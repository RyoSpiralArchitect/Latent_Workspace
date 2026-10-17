"""Tiny harness for V20 A5, the gated cut-4 route with a stable end (not a real-model receipt)."""

import copy
import json
from argparse import Namespace

import pytest
import torch
from test_v20_a2_depth_ladder import RULE
from test_v20_a2_depth_ladder import tiny_plan as ladder_plan
from test_v20_a4_gated_route import UPDATES, pin, plant_scores, write_ladder, write_mismatch
from test_v20_a4_gated_route import a4_plan as a4_tiny_plan

from latent_workspace import training
from scripts import run_v16_adapter_migration as core
from scripts import run_v20_a5_stable_route as run

A4 = run.A4
PLAN = run.ex.read(run.ROOT / run.PLAN)


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
    changed["training"]["decay_from"] = 0
    with pytest.raises(ValueError, match="plan"):
        run.validate_plan(changed)
    assert run.ROLES == ("reproduce", "stable_s1", "stable_s2", "stable_s3", "replay", "endpoints")
    assert run.seed_of(PLAN, "stable_s3") == PLAN["seeds"][2]
    a4 = run.ex.read(run.ROOT / A4.PLAN)
    assert all(PLAN[k] == a4[k] for k in ("route", "gating", "mismatch", "seeds", "conditions"))
    assert PLAN["sources"]["ladder"]["features"] == a4["source"]["features"]
    assert PLAN["beta_candidate"]["seed"] == PLAN["seeds"][0]
    assert run.ex.qualification_devices(PLAN) == ("cpu",)


def role_args(root, role):
    return Namespace(
        role=role,
        output=root / "raw" / role,
        checkpoints=root / "checkpoints",
        seal=None,
        qualification=None,
    )


def write_a4(tmp_path, pattern=None):
    """A synthetic ladder and A4 in their sealed layouts, A4's gated routes trained."""
    ladder, questions = write_ladder(tmp_path, pattern=pattern)
    a4plan = a4_tiny_plan(ladder)
    root = tmp_path / "a4"
    write_mismatch(root, ladder)
    for index in range(1, run.SEEDS + 1):
        args = role_args(root, f"gated_s{index}")
        args.output.mkdir(parents=True)
        A4.train_gated(torch, args, a4plan)
        run.ex.write_new(args.output / "FINISHED.json", dict(status=A4.ARM_PASS))
    (root / "raw" / "endpoints").mkdir()
    run.ex.write_new(root / "raw" / "endpoints" / "ENDPOINTS.json", dict(a4="synthetic"))
    run.ex.write_new(root / "raw" / "FINISHED.json", dict(status="synthetic"))
    return ladder, root / "raw", questions


def a5_plan(ladder, a4):
    plan = copy.deepcopy(PLAN)
    tiny = ladder_plan()
    for key in ("route", "candidate_ids", "checkpoint_steps", "parity_every"):
        plan[key] = copy.deepcopy(tiny[key])
    plan["training"] = dict(tiny["training"], decay_from=3)
    plan["replay"].update(from_step=3, execute_step=4)
    plan["endpoints"]["rule"] = RULE

    def rename(names):
        return [name.replace("step512", f"step{UPDATES}") for name in names]

    for name, raw in (("ladder", ladder), ("a4", a4)):
        source = plan["sources"][name]
        source["raw"] = f"../../{name}/raw"
        source["features"] = pin(raw, source["features"])
        source["receipts"] = pin(raw, rename(source["receipts"]))
    plan["reproduce"].update(
        scores=plan["reproduce"]["scores"].replace("step512", f"step{UPDATES}"),
        fingerprint=run.ex.read(a4 / "gated_s1" / "FINGERPRINTS.json")["gated"][str(UPDATES)],
    )
    return plan


def test_roles_reproduce_a4_then_train_stable_and_replay_exactly(tmp_path):
    ladder, a4, _ = write_a4(tmp_path)
    plan = a5_plan(ladder, a4)
    root = tmp_path / "a5"
    args = role_args(root, "reproduce")
    args.output.mkdir(parents=True)
    report = run.reproduce_run(torch, args, plan)
    assert report["exact"] and report["receipts_equal"] and report["scores_equal"]
    args = role_args(root, "stable_s1")
    args.output.mkdir(parents=True)
    run.ex.write_new(args.output / "STARTED.json", dict(pid=1))
    outcome = run.train_stable(torch, args, plan)
    assert set(outcome["fingerprints"]) == {"0", "3", "4", str(UPDATES)}
    receipts = [json.loads(line) for line in (args.output / "updates_stable.jsonl").open()]
    _, _, config, _ = run.build(plan, plan["seeds"][0])
    assert config.decay_from == 3 and config.mismatch_weight == plan["gating"]["weight"]
    rates = [r["learning_rate"] for r in receipts]
    assert rates == [training.learning_rate_at(config, s) for s in range(1, UPDATES + 1)]
    assert rates[:3] == [config.learning_rate] * 3 and rates[-1] == config.learning_rate / 4
    stable = run.ex.read_gz(args.output / f"eval_stable_final_step{UPDATES}.json.gz")
    gated = run.ex.read_gz(a4 / "gated_s1" / f"eval_gated_final_step{UPDATES}.json.gz")
    assert stable != gated
    replay = role_args(root, "replay")
    replay.output.mkdir(parents=True)
    report = run.replay_run(torch, replay, plan)
    assert report["exact"] and report["update"]["learning_rate"] < config.learning_rate
    changed = copy.deepcopy(plan)
    changed["reproduce"]["fingerprint"] = "0" * 64
    args = role_args(root, "reproduce_again")
    args.output.mkdir(parents=True)
    with pytest.raises(ValueError, match="did not reproduce"):
        run.reproduce_run(torch, args, changed)
    (a4 / "extract_mismatch" / "ROWS_mismatch.json.gz").write_bytes(b"changed")
    with pytest.raises(ValueError, match="A4 record changed"):
        run.verify_records(ladder, a4, plan, features=False)


def plant_arms(tmp_path, patterns):
    """Planted final scores for the stable, gated and ungated arms (one pattern each)."""
    ladder, a4, questions = write_a4(tmp_path, pattern="blind")
    meta = run.ex.read_gz(ladder / "extract_cut4" / "ROWS_final.json.gz")
    raw = tmp_path / "a5" / "raw"
    for index in range(1, run.SEEDS + 1):
        paths = {
            "stable": raw / f"stable_s{index}" / f"eval_stable_final_step{UPDATES}.json.gz",
            "gated": a4 / f"gated_s{index}" / f"eval_gated_final_step{UPDATES}.json.gz",
            "ungated": ladder / f"route_cut4_s{index}" / f"eval_route_final_step{UPDATES}.json.gz",
        }
        for arm, path in paths.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.unlink(missing_ok=True)
            plant_scores(path, questions, meta, patterns[arm])
    return ladder, a4, raw, questions, meta


def test_endpoints_compare_stable_gated_and_ungated(tmp_path):
    patterns = {"stable": "content", "gated": "directional", "ungated": "blind"}
    ladder, a4, raw, _, _ = plant_arms(tmp_path, patterns)
    plan = a5_plan(ladder, a4)
    result = run.endpoints_for(raw, ladder, a4, plan)
    outcome = run.outcome_of(result, plan)
    assert outcome == dict(
        stable="CONTENT_REACHES_ANSWERS",
        stable_per_seed=["CONTENT_REACHES_ANSWERS"] * 3,
        gated="DIRECTIONAL_ONLY",
        gated_per_seed=["DIRECTIONAL_ONLY"] * 3,
        ungated="NOT_ESTABLISHED",
        ungated_per_seed=["NOT_ESTABLISHED"] * 3,
        host="NOT_ESTABLISHED",
        ensemble="CONTENT_REACHES_ANSWERS",
        beta_candidate_seed=plan["seeds"][0],
        beta_candidate_eligible=True,
    )
    assert result["ensemble"]["accuracy"]["intact"] == 1.0
    with pytest.raises(ValueError, match="comparator"):
        run.check_comparators(outcome, plan)
    plan["comparators"] = dict(
        gated=dict(verdict="DIRECTIONAL_ONLY", per_seed=["DIRECTIONAL_ONLY"] * 3),
        ungated=dict(verdict="NOT_ESTABLISHED", per_seed=["NOT_ESTABLISHED"] * 3),
        host="NOT_ESTABLISHED",
    )
    run.check_comparators(outcome, plan)


def test_offline_verifier_accepts_what_the_runner_writes(tmp_path):
    from scripts import verify_v20_a5_stable_route as verifier

    patterns = {"stable": "content", "gated": "directional", "ungated": "blind"}
    ladder, a4, raw, _, _ = plant_arms(tmp_path, patterns)
    plan = a5_plan(ladder, a4)
    host = run.ex.read_gz(ladder / "extract_cut4" / "HOST_SCORES_final.json.gz")
    _, _, config, _ = run.build(plan, plan["seeds"][0])
    for index in range(1, run.SEEDS + 1):
        folder = raw / f"stable_s{index}"
        run.ex.write_gz(folder / "eval_stable_final_step0.json.gz", {"adapted_logits": host})
        with (folder / "updates_stable.jsonl").open("x") as log:
            for step in range(1, UPDATES + 1):
                rate = training.learning_rate_at(config, step)
                log.write(json.dumps(dict(step=step, learning_rate=rate)) + "\n")
    run.ex.write_new(raw / "stable_s1" / "FINGERPRINTS.json", {"stable": {"3": "a", "4": "b"}})
    run.ex.write_new(raw / "stable_s1" / "CHECKPOINT_stable_step3.json", {"fingerprint": "a"})
    (raw / "reproduce").mkdir()
    fingerprint = plan["reproduce"]["fingerprint"]
    run.ex.write_new(
        raw / "reproduce" / "REPRODUCE.json",
        dict(
            exact=True,
            receipts_equal=True,
            scores_equal=True,
            fingerprint=fingerprint,
            expected_fingerprint=fingerprint,
        ),
    )
    (raw / "replay").mkdir()
    update = {"step": 4, "task_loss": 0.5, "learning_rate": training.learning_rate_at(config, 4)}
    run.ex.write_new(
        raw / "replay" / "REPLAY.json",
        dict(
            exact=True,
            role="stable_s1",
            replayed_fingerprint="b",
            restored_fingerprint="a",
            update=update,
            original_update=update,
        ),
    )
    (raw / "endpoints").mkdir()
    result = run.endpoints_for(raw, ladder, a4, plan)
    run.ex.write_new(raw / "endpoints" / "ENDPOINTS.json", result)
    outcome = run.outcome_of(result, plan)
    plan["comparators"] = dict(
        gated=dict(verdict=outcome["gated"], per_seed=outcome["gated_per_seed"]),
        ungated=dict(verdict=outcome["ungated"], per_seed=outcome["ungated_per_seed"]),
        host=outcome["host"],
    )
    roles = {"endpoints": ({}, {"outcome": outcome}, True)}
    verified = verifier.verify_results(raw, ladder, a4, plan, roles)
    assert verified["verdicts"]["stable"] == "CONTENT_REACHES_ANSWERS"
    assert verified["records_features_rehashed"]
    path = raw / "stable_s2" / "updates_stable.jsonl"
    lines = path.read_text().splitlines()
    lines[4] = json.dumps(dict(step=5, learning_rate=config.learning_rate))
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(ValueError, match="learning rate"):
        verifier.verify_results(raw, ladder, a4, plan, roles)
