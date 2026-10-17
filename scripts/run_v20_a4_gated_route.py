#!/usr/bin/env python3
"""Sealed V20 A4: the content-gated cut-4 route. Does gating meet lane A in every seed?

The depth ladder (A2) wrote each world's facts into pinned Mistral-7B at cut 4 and trained
D1's route over the host's final states at the question positions. Two seeds of three met
lane A's endpoint; the third fell short because random memory also moved its answers. A4
reuses the ladder's sealed cut-4 features, pinned by hash, and adds content gating. Each
training row is also read with a memory that does not answer its question: another
training world's facts that do not name both of its entities. The route's residual on
those rows is pushed to zero (engine ``training.update(mismatch=...)``). Lane A's
endpoint is read, unchanged, on the ladder's final rows, and compared with the ladder's
ungated route.

A CPU role first reproduces the ladder's ungated route bitwise. One GPU role writes the
mismatch rows, one CPU role per seed trains the gated route, a fresh process replays one
update, and the endpoint role writes the verdicts. No generation, judge call, native update
or deletion.
"""

from __future__ import annotations

import collections
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


def _ladder():
    """The depth ladder's runner, whose module cache this runner shares."""
    name = "run_v20_a2_depth_ladder"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


LADDER = _ladder()
load = LADDER.load
ENTRY = "scripts/run_v20_a4_gated_route.py"
PLAN = "configs/v20/A4_GATED_ROUTE_PLAN.json"
PLAN_CANONICAL_SHA256 = "1f4de6c04e83389671c65e0928c80bf89d0d08363c41e82c325e34bd4daa6ddc"
CUT = 4
SEEDS = 3
ARM = "gated"
ARM_ROLES = tuple(f"gated_s{i}" for i in range(1, SEEDS + 1))
ROLES = ("reproduce", "extract_mismatch", *ARM_ROLES, "replay", "endpoints")
VERDICTS = LADDER.VERDICTS
TINY_PASS = "TINY_V20_A4_GATED_ROUTE_HARNESS_PASS_NOT_7B"
EXTRACT_PASS = "V20_A4_MISMATCH_ROWS_EXTRACTED"
ARM_PASS = "V20_A4_GATED_ROUTE_COMPLETE"
REPRODUCE_PASS = "V20_A4_UNGATED_ROUTE_REPRODUCED_EXACTLY"
REPLAY_PASS = "V20_A4_FRESH_PROCESS_EXACT_REPLAY"
ENDPOINT_PASS = "V20_A4_ENDPOINTS_COMPLETE"
QUALIFICATION_CASES = 59


def validate_plan(plan):
    ex.require(ex.plan_hash(plan) == PLAN_CANONICAL_SHA256, "Frozen V20 A4 plan changed")
    ex.require(
        plan["cut"] == CUT
        and plan["source"]["cut"] == CUT
        and len(plan["seeds"]) == SEEDS
        and tuple(plan["conditions"]) == LADDER.CONDITIONS
        and tuple(plan["arms"]) == (ARM,)
        and plan["gating"]["weight"] > 0
        and math.gcd(plan["mismatch"]["stride"], plan["data"]["train"]["world_pairs"]) == 1
        and plan["qualification_cases"] == QUALIFICATION_CASES
        and plan["endpoints"]["rule"]["chance_control"] == "random_pair"
        and all(plan[k] == v for k, v in ex.CEILING.items()),
        "Frozen V20 A4 plan semantics changed",
    )


def seed_of(plan, role):
    ex.require(role in ARM_ROLES, f"Unknown arm role {role}")
    return plan["seeds"][int(role.removeprefix("gated_s")) - 1]


# ---- the ladder's sealed files ----------------------------------------------------


def ladder_raw(args, plan):
    """The depth ladder's raw folder, beside this run's task root on Furnace."""
    return (args.output.parent / plan["source"]["raw"]).resolve()


def verify_pinned(raw, pinned):
    """Every pinned ladder file (path relative to its raw folder) must match exactly."""
    for name, entry in sorted(pinned.items()):
        path = raw / name
        ex.require(
            path.is_file()
            and path.stat().st_size == entry["bytes"]
            and ex.digest(path) == entry["sha256"],
            f"Ladder file changed: {name}",
        )


def verify_ladder(raw, plan, features=True):
    if features:
        verify_pinned(raw, plan["source"]["features"])
    verify_pinned(raw, plan["source"]["receipts"])
    status = ex.read(raw / f"extract_cut{CUT}" / "FINISHED.json")["status"]
    ex.require(status == LADDER.EXTRACT_PASS, "Ladder features incomplete")


# ---- mismatch memory ----------------------------------------------------------------


def entities(record, query):
    a, b = record["metadata"]["query_pairs"][query]
    text = record["queries"][query]
    ex.require(a != b and a in text and b in text, "Query entities")
    return a, b


def mismatch_world(records, world, query, stride):
    """The first other training world, stepping by ``stride``, whose six names do not
    include both of the question's entities, so its facts do not answer the question."""
    pair = set(entities(records[world], query))
    count = len(records)
    for steps in range(1, count):
        other = (world + stride * steps) % count
        if not pair <= set(records[other]["metadata"]["orders"][0]):
            return other, steps
    raise ValueError("No mismatch world")


def check_entities(records):
    for record in records:
        orders = record["metadata"]["orders"]
        ex.require(len(orders) == 2 and set(orders[0]) == set(orders[1]), "World entities")


# ---- mismatch rows (GPU) ------------------------------------------------------------


def extract_mismatch(torch, host, cut, records, questions, memories, stored, plan, guard):
    """Final states at the question positions and host logits for every training row read
    with its mismatch memory, in the ladder's train row order. Every ``parity_every``-th
    row also checks the head against the decoder continued from the cut, and re-reads the
    row with its own memory against the ladder's stored features, bitwise."""
    from latent_workspace import composition

    device = host.head.weight.device
    prefix = composition.CutPrefixRoute(host, cut)
    keys = len(LADDER.MEMORY_KEYS)
    cands = list(plan["candidate_ids"])
    cache = {}

    def encode(ids):
        x = torch.tensor([ids], device=device)
        return host.to_cut(x, torch.ones_like(x), cut)[0]

    def memory(world, side):
        if (world, side) not in cache:
            cache[world, side] = encode(memories[world * keys + side]["ids"])
        return cache[world, side]

    def read(query, values):
        ones = torch.ones(1, query.shape[0], dtype=torch.long, device=device)
        mask = torch.ones(1, values.shape[0], dtype=torch.long, device=device)
        return prefix(query[None], ones, values[None], mask)

    states, offsets, scores, meta, checked = [], [0], [], [], 0
    encoded = None
    for n, (index, _condition, side) in enumerate(LADDER.split_rows(questions, "train")):
        guard(f"mismatch:{n}")
        row = questions[index]
        if encoded is None or encoded[0] != index:
            encoded = (index, encode(row["prompt_ids"]))
        query = encoded[1]
        other, steps = mismatch_world(
            records, row["world"], row["query"], plan["mismatch"]["stride"]
        )
        values = memory(other, side)
        final, logits, packed_mask = read(query, values)
        if n % plan["parity_every"] == 0:
            packed = torch.cat([values, query])[None]
            ex.require(
                torch.equal(host.from_cut(packed, packed_mask, cut), logits), "Prefix head parity"
            )
            own = memory(row["world"], side)
            own_final, own_logits, _ = read(query, own)
            start, end = stored["offsets"][n : n + 2].tolist()
            ex.require(
                torch.equal(
                    own_final[0, own.shape[0] :].cpu(), stored["question_states"][start:end]
                )
                and torch.equal(own_logits[0, -1, cands].float().cpu(), stored["host_logits"][n]),
                "Own row differs from the ladder's stored features",
            )
            checked += 1
        states.append(final[0, values.shape[0] :].detach().cpu())
        offsets.append(offsets[-1] + query.shape[0])
        scores.append(logits[0, -1, cands].float().cpu())
        meta.append(
            dict(
                question=index,
                world=row["world"],
                query=row["query"],
                side=side,
                label=row["labels"][side],
                mismatch_world=other,
                stride_steps=steps,
                memory_length=int(values.shape[0]),
            )
        )
    tensors = {
        "question_states": torch.cat(states),
        "offsets": torch.tensor(offsets, dtype=torch.long),
        "host_logits": torch.stack(scores),
    }
    return tensors, meta, checked


def check_alignment(questions, ladder_rows):
    """The rendered train rows are the ladder's, row for row."""
    rows = LADDER.split_rows(questions, "train")
    ex.require(len(rows) == len(ladder_rows), "Train row count differs from the ladder")
    for (index, condition, side), stored in zip(rows, ladder_rows, strict=True):
        q = questions[index]
        ex.require(
            (stored["question"], stored["condition"], stored["side"], stored["world"])
            == (index, condition, side, q["world"])
            and (stored["query"], stored["label"]) == (q["query"], q["labels"][side]),
            "Train rows differ from the ladder's",
        )


def extract_body(core, args, plan, seal):
    from safetensors.torch import load_file, save_file

    from latent_workspace import DecoderHost

    core.load_runtime()
    torch = core.torch
    guard = core.legacy.Guard(plan["resources"], args.output)
    guard("admission", admission=True, forecast_bytes=plan["storage_forecast_bytes"])
    ex.require(torch.cuda.device_count() == 1, "One CUDA device")
    torch.cuda.set_per_process_memory_fraction(
        plan["resources"]["allocator_cap_gib"]
        * ex.GIB
        / torch.cuda.get_device_properties(0).total_memory
    )
    for split, entry in plan["data"].items():
        ex.require(ex.digest(ROOT / entry["path"]) == entry["sha256"], f"Data changed: {split}")
    raw = ladder_raw(args, plan)
    verify_ladder(raw, plan)
    source = raw / f"extract_cut{CUT}"
    old = core.legacy.old
    _, _, architecture, _ = core.legacy.validate()
    config = old.engine.ModelConfig(**architecture["model"])
    tokenizer = old.engine.load_tokenizer(config)
    ex.require(tokenizer.eos_token_id == plan["eos_token_id"], "Pinned EOS")
    base = old.engine._load_hf_model(config).eval().requires_grad_(False).to("cuda")
    ex.require(
        core.tree_hash(base.state_dict()) == plan["backbone"]["original_base_sha256"],
        "Pinned base identity",
    )
    host = DecoderHost(base)
    ex.require(host.hidden_size == plan["route"]["hidden_dim"], "Hidden size")
    ex.require(host.layer_count == plan["backbone"]["layers"], "Layer count")
    records = LADDER.v19().load_records(plan)
    audit = LADDER.v19().validate_data(old, records)
    check_entities(records["train"])
    questions, memories = LADDER.render(old, tokenizer, records["train"], plan)
    check_alignment(questions, ex.read_gz(source / "ROWS_train.json.gz"))
    stored = load_file(str(source / "FEATURES_train.safetensors"))
    throttle = LADDER.v19().throttled(guard, 256)
    with torch.no_grad():
        tensors, meta, checked = extract_mismatch(
            torch,
            host,
            plan["cut"],
            records["train"],
            questions,
            memories,
            stored,
            plan,
            lambda phase: throttle(f"extract:{phase}"),
        )
    save_file(
        {k: v.contiguous() for k, v in tensors.items()},
        str(args.output / "FEATURES_mismatch.safetensors"),
    )
    ex.write_gz(args.output / "ROWS_mismatch.json.gz", meta)
    ex.write_gz(args.output / "HOST_SCORES_mismatch.json.gz", tensors["host_logits"].tolist())
    guard("finished")
    steps = collections.Counter(m["stride_steps"] for m in meta)
    return dict(
        rows=len(meta),
        question_tokens=int(tensors["offsets"][-1]),
        parity_checked_rows=checked,
        stride_steps={str(k): steps[k] for k in sorted(steps)},
        data_audit=audit,
        peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(),
    )


# ---- the gated route per seed, the reproduction and the replay (CPU) -----------------


def banks(torch, args, plan):
    """The ladder's train and final rows, and this run's mismatch rows aligned with train."""
    raw = ladder_raw(args, plan)
    verify_ladder(raw, plan)
    source = raw / f"extract_cut{CUT}"
    folder = args.output.parent / "extract_mismatch"
    ex.require(ex.read(folder / "FINISHED.json")["status"] == EXTRACT_PASS, "Mismatch rows missing")
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


def build(plan, seed):
    route, optimizer, config, named = LADDER.build(plan, seed, plan["route"]["steps"])
    return (
        route,
        optimizer,
        dataclasses.replace(config, mismatch_weight=plan["gating"]["weight"]),
        named,
    )


def arm_body(core, args, plan, seal):
    torch = LADDER.cpu_runtime(plan)
    core.load_runtime()
    ex.require(not torch.cuda.is_available(), "Route roles must not see a GPU")
    return train_gated(torch, args, plan)


def train_gated(torch, args, plan):
    """The gated route of one seed; every update also reads the mismatch rows."""
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
    """The ladder's ungated route of one seed, retrained here from the pinned features:
    every update receipt, the final fingerprint and the final scores must be the ladder's."""
    from latent_workspace import training

    rule = plan["reproduce"]
    raw = ladder_raw(args, plan)
    verify_ladder(raw, plan)
    source = raw / f"extract_cut{CUT}"
    bank = LADDER.load_bank(torch, source, "train")
    final = LADDER.load_bank(torch, source, "final")
    route, optimizer, config, named = LADDER.build(plan, rule["seed"], plan["route"]["steps"])
    receipts = [
        training.update(route, None, optimizer, bank, config, step)
        for step in range(1, config.updates + 1)
    ]
    fingerprint = training.fingerprint(named)
    adapted = training.evaluate(route, final).tolist()
    recorded = [json.loads(line) for line in (raw / rule["updates"]).read_text().splitlines()]
    report = dict(
        seed=rule["seed"],
        updates=config.updates,
        fingerprint=fingerprint,
        expected_fingerprint=rule["fingerprint"],
        receipts_equal=receipts == recorded,
        scores_equal=adapted == ex.read_gz(raw / rule["scores"])["adapted_logits"],
    )
    report["exact"] = (
        fingerprint == rule["fingerprint"] and report["receipts_equal"] and report["scores_equal"]
    )
    ex.require(report["exact"], "The ladder's ungated route did not reproduce")
    ex.write_new(args.output / "REPRODUCE.json", report)
    return report


def replay_body(core, args, plan, seal):
    torch = LADDER.cpu_runtime(plan)
    core.load_runtime()
    return replay_run(torch, args, plan)


def replay_run(torch, args, plan):
    from latent_workspace import training

    rule = plan["replay"]
    role = f"gated_s{plan['seeds'].index(rule['seed']) + 1}"
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


def gap_moved(meta, scores, host):
    """Per condition, the mean |change| of the candidate gap from the host's (descriptive)."""
    moved = {}
    for row, value, base in zip(meta, scores, host, strict=True):
        moved.setdefault(row["condition"], []).append(
            abs((value[1] - value[0]) - (base[1] - base[0]))
        )
    return {c: sum(v) / len(v) for c, v in moved.items()}


def endpoints_for(raw, ladder, plan):
    """Lane A's verdicts for the gated route and the ladder's ungated route, from saved
    scores alone (shared with the offline verifier)."""
    rule = plan["endpoints"]["rule"]
    step = plan["training"]["updates"]
    folder = ladder / f"extract_cut{CUT}"
    questions = ex.read_gz(folder / "QUESTIONS_final.json.gz")
    meta = ex.read_gz(folder / "ROWS_final.json.gz")
    host_scores = ex.read_gz(folder / "HOST_SCORES_final.json.gz")
    host = LADDER.diagnose_scores(questions, LADDER.condition_scores(meta, host_scores), rule)
    sources = {
        ARM: lambda i: raw / f"gated_s{i}" / f"eval_{ARM}_final_step{step}.json.gz",
        "ungated": lambda i: (
            ladder / f"route_cut{CUT}_s{i}" / f"eval_route_final_step{step}.json.gz"
        ),
    }
    arms = {}
    for arm, path in sources.items():
        per_seed = []
        for index in range(1, SEEDS + 1):
            scores = ex.read_gz(path(index))["adapted_logits"]
            result = LADDER.diagnose_scores(questions, LADDER.condition_scores(meta, scores), rule)
            result["gap_moved"] = gap_moved(meta, scores, host_scores)
            per_seed.append(result)
        arms[arm] = dict(
            verdict=LADDER.seeds_verdict([s["verdict"] for s in per_seed]), per_seed=per_seed
        )
    return dict(host=host, **arms, rule=rule)


def outcome_of(result):
    return dict(
        gated=result[ARM]["verdict"],
        gated_per_seed=[s["verdict"] for s in result[ARM]["per_seed"]],
        ungated=result["ungated"]["verdict"],
        ungated_per_seed=[s["verdict"] for s in result["ungated"]["per_seed"]],
        host=result["host"]["verdict"],
    )


def check_comparator(outcome, plan):
    """The ladder's verdicts, recomputed from its pinned scores, must be the ones it recorded."""
    comparator = plan["comparator"]
    ex.require(
        outcome["ungated"] == comparator["verdict"]
        and outcome["ungated_per_seed"] == comparator["per_seed"]
        and outcome["host"] == comparator["host"],
        "The ladder's recorded cut-4 verdicts differ",
    )


def endpoints_body(core, args, plan, seal):
    LADDER.cpu_runtime(plan)
    raw = ladder_raw(args, plan)
    verify_ladder(raw, plan, features=False)
    result = endpoints_for(args.output.parent, raw, plan)
    outcome = outcome_of(result)
    check_comparator(outcome, plan)
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
        "extract_mismatch": EXTRACT_PASS,
        **dict.fromkeys(ARM_ROLES, ARM_PASS),
        "reproduce": REPRODUCE_PASS,
        "replay": REPLAY_PASS,
        "endpoints": ENDPOINT_PASS,
    },
    validate=validate_plan,
    load=load,
)
BODIES = {
    "extract_mismatch": extract_body,
    **dict.fromkeys(ARM_ROLES, arm_body),
    "reproduce": reproduce_body,
    "replay": replay_body,
    "endpoints": endpoints_body,
}


if __name__ == "__main__":
    raise SystemExit(RUN.main(BODIES, summary))
