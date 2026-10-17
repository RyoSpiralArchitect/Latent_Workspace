#!/usr/bin/env python3
"""Sealed V20 A5: the gated cut-4 route with a stable end of training, toward the LTWS β.

A4's content-gated route met lane A's endpoint in two seeds of three. The third was scored
at update 512 under a constant learning rate, right after a loss spike. A5 changes only the
end of training: the learning rate stays at 3e-4 to update 256, then falls linearly (engine
``TrainConfig.decay_from``). Everything else is A4's, read from sealed records pinned by
hash: the depth ladder's cut-4 features and A4's mismatch rows. Lane A's endpoint is read,
unchanged, and compared with A4's gated route and the ladder's ungated one.

A CPU role first reproduces A4's gated route of seed 1 bitwise. One CPU role per seed trains
the stable route, a fresh process replays the first decayed update, and the endpoint role
writes the verdicts. No GPU role, generation, judge call, native update or deletion.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
from latent_workspace import execution as ex  # noqa: E402


def _a4():
    """A4's runner (and through it the ladder's), whose module cache this runner shares."""
    name = "run_v20_a4_gated_route"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


A4 = _a4()
LADDER = A4.LADDER
load = LADDER.load
ENTRY = "scripts/run_v20_a5_stable_route.py"
PLAN = "configs/v20/A5_STABLE_ROUTE_PLAN.json"
PLAN_CANONICAL_SHA256 = "b8357d51670ec92ae74d39bb4edf78833d6ac79a7b05196a32b24591a70686bd"
CUT = 4
SEEDS = 3
ARM = "stable"
ARM_ROLES = tuple(f"stable_s{i}" for i in range(1, SEEDS + 1))
ROLES = ("reproduce", *ARM_ROLES, "replay", "endpoints")
TINY_PASS = "TINY_V20_A5_STABLE_ROUTE_HARNESS_PASS_NOT_7B"
ARM_PASS = "V20_A5_STABLE_ROUTE_COMPLETE"
REPRODUCE_PASS = "V20_A5_A4_GATED_ROUTE_REPRODUCED_EXACTLY"
REPLAY_PASS = "V20_A5_FRESH_PROCESS_EXACT_REPLAY"
ENDPOINT_PASS = "V20_A5_ENDPOINTS_COMPLETE"
QUALIFICATION_CASES = 59


def validate_plan(plan):
    ex.require(ex.plan_hash(plan) == PLAN_CANONICAL_SHA256, "Frozen V20 A5 plan changed")
    training = plan["training"]
    ex.require(
        plan["cut"] == CUT
        and len(plan["seeds"]) == SEEDS
        and tuple(plan["conditions"]) == LADDER.CONDITIONS
        and tuple(plan["arms"]) == (ARM,)
        and plan["gating"]["weight"] > 0
        and 0 < training["decay_from"] < training["updates"]
        and plan["beta_candidate"]["seed"] in plan["seeds"]
        and math.gcd(plan["mismatch"]["stride"], plan["data"]["train"]["world_pairs"]) == 1
        and plan["qualification_cases"] == QUALIFICATION_CASES
        and plan["endpoints"]["rule"]["chance_control"] == "random_pair"
        and all(plan[k] == v for k, v in ex.CEILING.items()),
        "Frozen V20 A5 plan semantics changed",
    )


def seed_of(plan, role):
    ex.require(role in ARM_ROLES, f"Unknown arm role {role}")
    return plan["seeds"][int(role.removeprefix("stable_s")) - 1]


# ---- the sealed records this run reads ------------------------------------------------


def record_raw(args, plan, name):
    """A sealed run's raw folder (``ladder`` or ``a4``), beside this run's task root."""
    return (args.output.parent / plan["sources"][name]["raw"]).resolve()


def verify_pinned(raw, pinned, label):
    """Every pinned file (path relative to its raw folder) must match exactly."""
    for name, entry in sorted(pinned.items()):
        path = raw / name
        ex.require(
            path.is_file()
            and path.stat().st_size == entry["bytes"]
            and ex.digest(path) == entry["sha256"],
            f"{label} record changed: {name}",
        )


def verify_records(ladder, a4, plan, features=True):
    """Every pinned file of both sealed runs must match."""
    for name, raw in (("ladder", ladder), ("a4", a4)):
        label = {"ladder": "Ladder", "a4": "A4"}[name]
        if features:
            verify_pinned(raw, plan["sources"][name]["features"], label)
        verify_pinned(raw, plan["sources"][name]["receipts"], label)
    status = ex.read(ladder / f"extract_cut{CUT}" / "FINISHED.json")["status"]
    ex.require(status == LADDER.EXTRACT_PASS, "Ladder features incomplete")
    status = ex.read(a4 / "extract_mismatch" / "FINISHED.json")["status"]
    ex.require(status == A4.EXTRACT_PASS, "A4 mismatch rows incomplete")


def banks(torch, args, plan):
    """The ladder's train and final rows and A4's mismatch rows aligned with train."""
    ladder, a4 = record_raw(args, plan, "ladder"), record_raw(args, plan, "a4")
    verify_records(ladder, a4, plan)
    source, folder = ladder / f"extract_cut{CUT}", a4 / "extract_mismatch"
    data = {
        "train": LADDER.load_bank(torch, source, "train"),
        "final": LADDER.load_bank(torch, source, "final"),
        "mismatch": LADDER.load_bank(torch, folder, "mismatch"),
    }
    own = ex.read_gz(source / "ROWS_train.json.gz")
    other = ex.read_gz(folder / "ROWS_mismatch.json.gz")
    ex.require(
        [(m["question"], m["side"]) for m in own] == [(m["question"], m["side"]) for m in other]
        and torch.equal(data["train"].offsets, data["mismatch"].offsets),
        "Mismatch rows are not aligned with the train rows",
    )
    return data


def build(plan, seed, stable=True):
    """A4's gated route; ``stable`` adds the decaying learning rate."""
    route, optimizer, config, named = LADDER.build(plan, seed, plan["route"]["steps"])
    decay = plan["training"]["decay_from"] if stable else 0
    config = dataclasses.replace(config, mismatch_weight=plan["gating"]["weight"], decay_from=decay)
    return route, optimizer, config, named


# ---- the stable route per seed, the reproduction and the replay (CPU) -----------------


def arm_body(core, args, plan, seal):
    torch = LADDER.cpu_runtime(plan)
    core.load_runtime()
    ex.require(not torch.cuda.is_available(), "Route roles must not see a GPU")
    return train_stable(torch, args, plan)


def train_stable(torch, args, plan):
    """The stable route of one seed: A4's gated training with the decaying learning rate."""
    from latent_workspace import training

    seed = seed_of(plan, args.role)
    data = banks(torch, args, plan)
    checkpoints = args.checkpoints / args.role
    checkpoints.mkdir(parents=True, exist_ok=False)
    route, optimizer, config, named = build(plan, seed)
    fingerprints = {0: training.fingerprint(named)}

    def evaluation(split, step):
        adapted = training.evaluate(route, data[split])
        ex.write_gz(
            args.output / f"eval_{ARM}_{split}_step{step}.json.gz",
            {"adapted_logits": adapted.tolist()},
        )
        return adapted

    ex.require(torch.equal(evaluation("final", 0), data["final"].base_logits), "Step 0 is the host")
    replayed = seed == plan["replay"]["seed"]
    with (args.output / f"updates_{ARM}.jsonl").open("x") as log:
        for step in range(1, config.updates + 1):
            receipt = training.update(
                route, None, optimizer, data["train"], config, step, data["mismatch"]
            )
            receipt["learning_rate"] = training.learning_rate_at(config, step)
            log.write(json.dumps(receipt) + "\n")
            if replayed and (
                step in plan["checkpoint_steps"] or step == plan["replay"]["execute_step"]
            ):
                fingerprints[step] = training.fingerprint(named)
            if replayed and step in plan["checkpoint_steps"]:
                path = checkpoints / f"{ARM}_step{step}.pt"
                torch.save(
                    dict(
                        route=route.state_dict(),
                        optimizer=optimizer.state_dict(),
                        completed_steps=step,
                    ),
                    path,
                )
                ex.write_new(
                    args.output / f"CHECKPOINT_{ARM}_step{step}.json",
                    dict(
                        path=path.name,
                        bytes=path.stat().st_size,
                        sha256=ex.digest(path),
                        fingerprint=fingerprints[step],
                        completed_steps=step,
                    ),
                )
    fingerprints[config.updates] = training.fingerprint(named)
    for split in ("final", "train", "mismatch"):
        evaluation(split, config.updates)
    fingerprints = {str(k): v for k, v in fingerprints.items()}
    ex.write_new(args.output / "FINGERPRINTS.json", {ARM: fingerprints})
    return dict(seed=seed, fingerprints=fingerprints)


def reproduce_body(core, args, plan, seal):
    torch = LADDER.cpu_runtime(plan)
    core.load_runtime()
    ex.require(not torch.cuda.is_available(), "Route roles must not see a GPU")
    return reproduce_run(torch, args, plan)


def reproduce_run(torch, args, plan):
    """A4's gated route of one seed, retrained here from the pinned records: every update
    receipt, the final fingerprint and the final scores must be A4's."""
    from latent_workspace import training

    rule = plan["reproduce"]
    data = banks(torch, args, plan)
    a4 = record_raw(args, plan, "a4")
    route, optimizer, config, named = build(plan, rule["seed"], stable=False)
    receipts = [
        training.update(route, None, optimizer, data["train"], config, step, data["mismatch"])
        for step in range(1, config.updates + 1)
    ]
    fingerprint = training.fingerprint(named)
    adapted = training.evaluate(route, data["final"]).tolist()
    recorded = [json.loads(line) for line in (a4 / rule["updates"]).read_text().splitlines()]
    report = dict(
        seed=rule["seed"],
        updates=config.updates,
        fingerprint=fingerprint,
        expected_fingerprint=rule["fingerprint"],
        receipts_equal=receipts == recorded,
        scores_equal=adapted == ex.read_gz(a4 / rule["scores"])["adapted_logits"],
    )
    report["exact"] = (
        fingerprint == rule["fingerprint"] and report["receipts_equal"] and report["scores_equal"]
    )
    ex.require(report["exact"], "A4's gated route did not reproduce")
    ex.write_new(args.output / "REPRODUCE.json", report)
    return report


def replay_body(core, args, plan, seal):
    torch = LADDER.cpu_runtime(plan)
    core.load_runtime()
    return replay_run(torch, args, plan)


def replay_run(torch, args, plan):
    from latent_workspace import training

    rule = plan["replay"]
    role = f"stable_s{plan['seeds'].index(rule['seed']) + 1}"
    source = args.output.parent / role
    data = banks(torch, args, plan)
    route, optimizer, config, named = build(plan, rule["seed"])
    receipt = ex.read(source / f"CHECKPOINT_{ARM}_step{rule['from_step']}.json")
    path = args.checkpoints / role / receipt["path"]
    ex.require(ex.digest(path) == receipt["sha256"], "Replay checkpoint bytes")
    state = torch.load(path, map_location="cpu", weights_only=True)
    route.load_state_dict(state["route"])
    optimizer.load_state_dict(state["optimizer"])
    ex.require(state["completed_steps"] == rule["from_step"], "Checkpoint step")
    restored = training.fingerprint(named)
    ex.require(restored == receipt["fingerprint"], "Restored state differs")
    update = training.update(
        route, None, optimizer, data["train"], config, rule["execute_step"], data["mismatch"]
    )
    update["learning_rate"] = training.learning_rate_at(config, rule["execute_step"])
    replayed = training.fingerprint(named)
    expected = ex.read(source / "FINGERPRINTS.json")[ARM][str(rule["execute_step"])]
    lines = (source / f"updates_{ARM}.jsonl").read_text().splitlines()
    original = json.loads(lines[rule["execute_step"] - 1])
    report = dict(
        role=role,
        arm=ARM,
        from_step=rule["from_step"],
        execute_step=rule["execute_step"],
        restored_fingerprint=restored,
        replayed_fingerprint=replayed,
        original_fingerprint=expected,
        update=update,
        original_update=original,
        exact=replayed == expected and update == original,
        replay_pid=os.getpid(),
        arm_pid=ex.read(source / "STARTED.json")["pid"],
    )
    ex.require(report["exact"], "Fresh-process replay differs")
    ex.require(report["arm_pid"] != report["replay_pid"], "Replay must be a fresh process")
    ex.write_new(args.output / "REPLAY.json", report)
    return report


# ---- endpoints (CPU) ----------------------------------------------------------------


def endpoints_for(raw, ladder, a4, plan):
    """Lane A's verdicts for the stable route, A4's gated route and the ladder's ungated
    route, from saved scores alone (shared with the offline verifier). The mean of the
    stable seeds' logits is read too (descriptive)."""
    rule = plan["endpoints"]["rule"]
    step = plan["training"]["updates"]
    folder = ladder / f"extract_cut{CUT}"
    questions = ex.read_gz(folder / "QUESTIONS_final.json.gz")
    meta = ex.read_gz(folder / "ROWS_final.json.gz")
    host_scores = ex.read_gz(folder / "HOST_SCORES_final.json.gz")

    def read(scores):
        result = LADDER.diagnose_scores(questions, LADDER.condition_scores(meta, scores), rule)
        result["gap_moved"] = A4.gap_moved(meta, scores, host_scores)
        return result

    host = LADDER.diagnose_scores(questions, LADDER.condition_scores(meta, host_scores), rule)
    sources = {
        ARM: lambda i: raw / f"stable_s{i}" / f"eval_{ARM}_final_step{step}.json.gz",
        "gated": lambda i: a4 / f"gated_s{i}" / f"eval_gated_final_step{step}.json.gz",
        "ungated": lambda i: (
            ladder / f"route_cut{CUT}_s{i}" / f"eval_route_final_step{step}.json.gz"
        ),
    }
    result, stable_scores = dict(host=host), []
    for arm, path in sources.items():
        per_seed = []
        for index in range(1, SEEDS + 1):
            scores = ex.read_gz(path(index))["adapted_logits"]
            if arm == ARM:
                stable_scores.append(scores)
            per_seed.append(read(scores))
        result[arm] = dict(
            verdict=LADDER.seeds_verdict([s["verdict"] for s in per_seed]), per_seed=per_seed
        )
    mean = [
        [sum(s[n][k] for s in stable_scores) / SEEDS for k in range(2)] for n in range(len(meta))
    ]
    result["ensemble"] = read(mean)
    result["rule"] = rule
    return result


def outcome_of(result, plan):
    stable = result[ARM]
    return dict(
        stable=stable["verdict"],
        stable_per_seed=[s["verdict"] for s in stable["per_seed"]],
        gated=result["gated"]["verdict"],
        gated_per_seed=[s["verdict"] for s in result["gated"]["per_seed"]],
        ungated=result["ungated"]["verdict"],
        ungated_per_seed=[s["verdict"] for s in result["ungated"]["per_seed"]],
        host=result["host"]["verdict"],
        ensemble=result["ensemble"]["verdict"],
        beta_candidate_seed=plan["beta_candidate"]["seed"],
        beta_candidate_eligible=stable["verdict"] == LADDER.VERDICTS[0],
    )


def check_comparators(outcome, plan):
    """A4's and the ladder's verdicts, recomputed from their pinned scores, must be the
    ones they recorded."""
    expected = plan["comparators"]
    ex.require(
        (outcome["gated"], outcome["gated_per_seed"])
        == (expected["gated"]["verdict"], expected["gated"]["per_seed"])
        and (outcome["ungated"], outcome["ungated_per_seed"])
        == (expected["ungated"]["verdict"], expected["ungated"]["per_seed"])
        and outcome["host"] == expected["host"],
        "The recorded comparator verdicts differ",
    )


def endpoints_body(core, args, plan, seal):
    LADDER.cpu_runtime(plan)
    ladder, a4 = record_raw(args, plan, "ladder"), record_raw(args, plan, "a4")
    verify_records(ladder, a4, plan, features=False)
    result = endpoints_for(args.output.parent, ladder, a4, plan)
    outcome = outcome_of(result, plan)
    check_comparators(outcome, plan)
    ex.write_new(args.output / "ENDPOINTS.json", result)
    return outcome


def summary(out, plan):
    return ex.read(out / "endpoints" / "FINISHED.json")["outcome"]


RUN = ex.SealedRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass=TINY_PASS,
    roles=ROLES,
    role_status={
        "reproduce": REPRODUCE_PASS,
        **dict.fromkeys(ARM_ROLES, ARM_PASS),
        "replay": REPLAY_PASS,
        "endpoints": ENDPOINT_PASS,
    },
    validate=validate_plan,
    load=load,
)
BODIES = {
    "reproduce": reproduce_body,
    **dict.fromkeys(ARM_ROLES, arm_body),
    "replay": replay_body,
    "endpoints": endpoints_body,
}


if __name__ == "__main__":
    raise SystemExit(RUN.main(BODIES, summary))
