#!/usr/bin/env python3
"""Sealed V20 A2: the depth ladder. How deep can a separately encoded memory enter the host?

With pinned Mistral-7B-Instruct-v0.3 frozen, the world facts (V19's memory text) and
the question (V15's query-only prompt) are each run alone through the layers below
cut k. The memory's states enter the host at cut k as positions before the
question's (engine ``CutPrefixRoute``), and the host's own remaining layers read
them; at cut 0 this is the facts as a text prefix. For k in 0, 4, 8 and 16, lane A's
flip endpoint is read, unchanged, for the frozen host alone and with v4's route:
D1's lattice over the host's final states at the question positions, into the
gated logit residual, trained on the train split (both sides). D1's readout control
is trained alongside, as a descriptive arm.

One GPU role per cut writes the features; one CPU role per cut and seed trains both
routes; a fresh process replays one update; the endpoint role writes the verdicts.
No generation, judge call, native update or deletion.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
from latent_workspace import execution as ex  # noqa: E402

ENTRY = "scripts/run_v20_a2_depth_ladder.py"
PLAN = "configs/v20/A2_DEPTH_LADDER_PLAN.json"
PLAN_CANONICAL_SHA256 = "295392251ca596e55997bf8ada4ec530ce6ac6ac46af5bfc7eb6db1d4231ecd1"
SPLITS = ("train", "final")
CUTS = (0, 4, 8, 16)
SEEDS = 3
ARMS = ("route", "readout")
ARM_ROLES = tuple(f"route_cut{k}_s{i}" for k in CUTS for i in range(1, SEEDS + 1))
ROLES = (*(f"extract_cut{k}" for k in CUTS), *ARM_ROLES, "replay", "endpoints")
MEMORY_KEYS = (
    ("intact", 0),
    ("twin", 1),
    ("reverse_intact", "reverse_0"),
    ("reverse_twin", "reverse_1"),
    ("unrelated", "unrelated"),
)
CONDITIONS = (
    "intact",
    "twin",
    "random_intact",
    "random_twin",
    "reverse_intact",
    "reverse_twin",
    "unrelated",
    "none",
)
VERDICTS = ("CONTENT_REACHES_ANSWERS", "DIRECTIONAL_ONLY", "NOT_ESTABLISHED")
TINY_PASS = "TINY_V20_A2_DEPTH_LADDER_HARNESS_PASS_NOT_7B"
EXTRACT_PASS = "V20_A2_DEPTH_FEATURES_EXTRACTED"
ARM_PASS = "V20_A2_DEPTH_ROUTES_COMPLETE"
REPLAY_PASS = "V20_A2_DEPTH_FRESH_PROCESS_EXACT_REPLAY"
ENDPOINT_PASS = "V20_A2_DEPTH_ENDPOINTS_COMPLETE"
QUALIFICATION_CASES = 58
_MODULES = {}


def load(name):
    if name not in _MODULES:
        spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        _MODULES[name] = module
    return _MODULES[name]


def v19():
    """V19's runner: data loading, its symbolic-oracle data checks and throttling."""
    return load("run_v19_frozen_diagnostic")


def validate_plan(plan):
    ex.require(ex.plan_hash(plan) == PLAN_CANONICAL_SHA256, "Frozen V20 A2 plan changed")
    ex.require(
        tuple(plan["cuts"]) == CUTS
        and len(plan["seeds"]) == SEEDS
        and tuple(plan["conditions"]) == CONDITIONS
        and tuple(plan["arms"]) == ARMS
        and plan["qualification_cases"] == QUALIFICATION_CASES
        and plan["endpoints"]["rule"]["chance_control"] == "random_pair"
        and all(plan[k] == v for k, v in ex.CEILING.items()),
        "Frozen V20 A2 plan semantics changed",
    )


def parse_role(plan, role):
    ex.require(role in ARM_ROLES, f"Unknown arm role {role}")
    cut, index = role.removeprefix("route_cut").split("_s")
    return int(cut), plan["seeds"][int(index) - 1]


def wording(query):
    return "outrank" if query.startswith("Does ") else "ranked_above"


def key_index(name):
    return [name for name, _ in MEMORY_KEYS].index(name)


# ---- rendering (as V15's LiveStore) -----------------------------------------------


def render(old, tokenizer, records, plan):
    """Question rows (world, query) and memory rows (world, key), in fixed order."""
    spec = plan["rendering"]
    questions, memories = [], []
    for w, record in enumerate(records):
        for q, query in enumerate(record["queries"]):
            sides = [
                old.render_case(
                    tokenizer,
                    query=query,
                    context=context,
                    renderer=spec["renderer"],
                    cue=spec["cue"],
                    information=spec["information"],
                )
                for context in record["contexts"]
            ]
            ex.require(sides[0] == sides[1], "Factual side leaked into the query prompt")
            ex.require(list(sides[0]["candidate_ids"]) == plan["candidate_ids"], "Candidate ids")
            labels = [int(record["answers"][0][q]), int(record["answers"][1][q])]
            questions.append(
                dict(
                    world=w,
                    query=q,
                    labels=labels,
                    affected=labels[0] != labels[1],
                    hop=int(record["hop_distances"][q]),
                    wording=wording(query),
                    prompt_ids=list(sides[0]["prompt_ids"]),
                )
            )
        for name, key in MEMORY_KEYS:
            if key == "unrelated":
                text = old.prior.unrelated_context(record)
            else:
                side = int(key[-1]) if isinstance(key, str) else key
                text = old.canonical_facts(record["contexts"][side], reverse=isinstance(key, str))
            memories.append(
                dict(world=w, key=name, ids=list(tokenizer.encode(text, add_special_tokens=False)))
            )
    return questions, memories


def split_rows(questions, split):
    """Feature rows: train reads each side's own facts; final reads every condition."""
    rows = []
    if split == "train":
        by_world = {}
        for index, row in enumerate(questions):
            by_world.setdefault(row["world"], []).append(index)
        for world in sorted(by_world):
            for side in (0, 1):
                for index in by_world[world]:
                    rows.append((index, ("intact", "twin")[side], side))
        return rows
    for condition in CONDITIONS:
        side = 1 if condition.endswith("twin") else 0
        rows.extend((index, condition, side) for index in range(len(questions)))
    return rows


# ---- host features per cut (GPU) --------------------------------------------------


def random_memories(torch, memory_states, worlds, seed):
    """V16's control per world, intact then twin: norm-matched Gaussian states."""
    from latent_workspace import availability

    out = {}
    for world in worlds:
        generator = torch.Generator().manual_seed(seed + world)
        for side in (0, 1):
            values = memory_states[world * len(MEMORY_KEYS) + side]
            mask = torch.ones(1, values.shape[0], dtype=torch.long)
            random = availability.norm_matched_random(values[None].float().cpu(), mask, generator)
            out[world, side] = random[0].to(values.device, values.dtype)
    return out


def extract_split(torch, host, cut, questions, memories, plan, split, guard):
    """Question-position final states and host candidate logits for every feature row."""
    from latent_workspace import composition

    device = host.head.weight.device
    prefix = composition.CutPrefixRoute(host, cut)

    def encode(ids):
        x = torch.tensor([ids], device=device)
        return host.to_cut(x, torch.ones_like(x), cut)[0]

    memory_states = [encode(row["ids"]) for row in memories]
    worlds = sorted({row["world"] for row in questions})
    randoms = random_memories(torch, memory_states, worlds, plan["random_memory_seed"])
    cands = list(plan["candidate_ids"])
    states, offsets, scores, meta, checked = [], [0], [], [], 0
    cache = {}
    for n, (index, condition, side) in enumerate(split_rows(questions, split)):
        guard(f"{split}:{n}")
        row = questions[index]
        if index not in cache:
            cache.clear()
            cache[index] = encode(row["prompt_ids"])
        query = cache[index]
        if condition == "none":
            memory = query[:0]
        elif condition.startswith("random_"):
            memory = randoms[row["world"], side]
        else:
            memory = memory_states[row["world"] * len(MEMORY_KEYS) + key_index(condition)]
        ones = torch.ones(1, query.shape[0], dtype=torch.long, device=device)
        final, logits, packed_mask = prefix(
            query[None],
            ones,
            memory[None],
            torch.ones(1, memory.shape[0], dtype=torch.long, device=device),
        )
        if n % plan["parity_every"] == 0:
            packed = torch.cat([memory, query])[None]
            ex.require(
                torch.equal(host.from_cut(packed, packed_mask, cut), logits), "Prefix head parity"
            )
            if cut == 0 and condition not in ("none",) and not condition.startswith("random_"):
                ids = memories[row["world"] * len(MEMORY_KEYS) + key_index(condition)]["ids"]
                inline = torch.tensor([ids + row["prompt_ids"]], device=device)
                ex.require(
                    torch.equal(host.logits(inline, torch.ones_like(inline)), logits),
                    "Cut-0 memory differs from the inline text",
                )
            checked += 1
        states.append(final[0, memory.shape[0] :].detach().cpu())
        offsets.append(offsets[-1] + query.shape[0])
        scores.append(logits[0, -1, cands].float().cpu())
        meta.append(
            dict(
                question=index,
                world=row["world"],
                query=row["query"],
                condition=condition,
                side=side,
                label=row["labels"][side],
                labels=row["labels"],
                affected=row["affected"],
                hop=row["hop"],
                wording=row["wording"],
                memory_length=int(memory.shape[0]),
            )
        )
    tensors = {
        "question_states": torch.cat(states),
        "offsets": torch.tensor(offsets, dtype=torch.long),
        "host_logits": torch.stack(scores),
    }
    return tensors, meta, checked


def extract_body(cut):
    def body(core, args, plan, seal):
        from safetensors.torch import save_file

        from latent_workspace import DecoderHost

        core.load_runtime()
        torch = core.torch
        guard = core.legacy.Guard(plan["resources"], args.output)
        guard("admission", admission=True, forecast_bytes=plan["storage_forecast_bytes_per_cut"])
        ex.require(torch.cuda.device_count() == 1, "One CUDA device")
        torch.cuda.set_per_process_memory_fraction(
            plan["resources"]["allocator_cap_gib"]
            * ex.GIB
            / torch.cuda.get_device_properties(0).total_memory
        )
        for split, entry in plan["data"].items():
            ex.require(ex.digest(ROOT / entry["path"]) == entry["sha256"], f"Data changed: {split}")
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
        records = v19().load_records(plan)
        audit = v19().validate_data(old, records)
        throttle = v19().throttled(guard, 256)
        outcome = dict(cut=cut, splits={}, data_audit=audit)
        for split in SPLITS:
            questions, memories = render(old, tokenizer, records[split], plan)
            with torch.no_grad():
                tensors, meta, checked = extract_split(
                    torch,
                    host,
                    cut,
                    questions,
                    memories,
                    plan,
                    split,
                    lambda phase: throttle(f"extract:cut{cut}:{phase}"),
                )
            save_file(
                {k: v.contiguous() for k, v in tensors.items()},
                str(args.output / f"FEATURES_{split}.safetensors"),
            )
            ex.write_gz(args.output / f"ROWS_{split}.json.gz", meta)
            ex.write_gz(
                args.output / f"HOST_SCORES_{split}.json.gz", tensors["host_logits"].tolist()
            )
            if split == "final":
                ex.write_gz(args.output / "QUESTIONS_final.json.gz", questions)
            outcome["splits"][split] = dict(
                rows=len(meta),
                question_tokens=int(tensors["offsets"][-1]),
                parity_checked_rows=checked,
            )
        guard("finished")
        outcome["peak_cuda_allocated_bytes"] = torch.cuda.max_memory_allocated()
        return outcome

    return body


# ---- routes per cut and seed (CPU) ------------------------------------------------


def cpu_runtime(plan):
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    import torch

    torch.set_num_threads(plan["training"]["threads"])
    torch.use_deterministic_algorithms(True)
    return torch


def load_bank(torch, folder, split):
    from safetensors.torch import load_file

    from latent_workspace import training

    tensors = load_file(str(folder / f"FEATURES_{split}.safetensors"))
    meta = ex.read_gz(folder / f"ROWS_{split}.json.gz")
    return training.FeatureBank(
        tensors["question_states"],
        tensors["offsets"],
        tensors["host_logits"],
        torch.tensor([m["label"] for m in meta]),
        torch.tensor([m["world"] for m in meta]),
    )


def build(plan, seed, steps):
    from latent_workspace import composition, training

    spec, settings = plan["route"], plan["training"]
    route = composition.DeliberationRoute(
        spec["hidden_dim"],
        spec["vocab_size"],
        tuple(plan["candidate_ids"]),
        steps=steps,
        seed=seed,
        workspace_dim=spec["workspace_dim"],
        heads=spec["attention_heads"],
        ff_multiplier=spec["ff_multiplier"],
        dropout=spec["dropout"],
        rank=spec["rank"],
        gate_init_bias=spec["gate_init_bias"],
    )
    config = training.TrainConfig(
        seed=seed,
        updates=settings["updates"],
        batch_size=settings["batch_size"],
        learning_rate=settings["learning_rate"],
        weight_decay=settings["weight_decay"],
        max_grad_norm=settings["max_grad_norm"],
        workspace_loss_weight=0.0,
        loss_tokens_per_row=0,
        loss_tokens_per_batch=0,
        spectral_every=1,
    )
    named = training.trainable(route)
    optimizer = training.optimizer_for(named, config.learning_rate, config.weight_decay)
    return route, optimizer, config, named


def arm_body(core, args, plan, seal):
    torch = cpu_runtime(plan)
    core.load_runtime()
    ex.require(not torch.cuda.is_available(), "Route roles must not see a GPU")
    return train_arms(torch, args, plan)


def train_arms(torch, args, plan):
    """Both routes of one (cut, seed) on that cut's features; the role's arithmetic is set."""
    from latent_workspace import training

    cut, seed = parse_role(plan, args.role)
    folder = args.output.parent / f"extract_cut{cut}"
    ex.require(ex.read(folder / "FINISHED.json")["status"] == EXTRACT_PASS, "Features missing")
    banks = {split: load_bank(torch, folder, split) for split in SPLITS}
    checkpoints = args.checkpoints / args.role
    checkpoints.mkdir(parents=True, exist_ok=False)
    outcome = dict(cut=cut, seed=seed, arms={})
    for arm in ARMS:
        steps = plan["route"]["steps"] if arm == "route" else 0
        route, optimizer, config, named = build(plan, seed, steps)
        fingerprints = {0: training.fingerprint(named)}

        def evaluation(split, step, arm=arm, route=route):
            adapted = training.evaluate(route, banks[split])
            ex.write_gz(
                args.output / f"eval_{arm}_{split}_step{step}.json.gz",
                {"adapted_logits": adapted.tolist()},
            )
            return adapted

        adapted = evaluation("final", 0)
        ex.require(torch.equal(adapted, banks["final"].base_logits), f"{arm}: step 0 is the host")
        with (args.output / f"updates_{arm}.jsonl").open("x") as log:
            for step in range(1, config.updates + 1):
                receipt = training.update(route, None, optimizer, banks["train"], config, step)
                log.write(json.dumps(receipt) + "\n")
                replayed = arm == plan["replay"]["arm"]
                if replayed and (
                    step in plan["checkpoint_steps"] or step == plan["replay"]["execute_step"]
                ):
                    fingerprints[step] = training.fingerprint(named)
                if replayed and step in plan["checkpoint_steps"]:
                    path = checkpoints / f"{arm}_step{step}.pt"
                    torch.save(
                        dict(
                            route=route.state_dict(),
                            optimizer=optimizer.state_dict(),
                            completed_steps=step,
                        ),
                        path,
                    )
                    ex.write_new(
                        args.output / f"CHECKPOINT_{arm}_step{step}.json",
                        dict(
                            path=path.name,
                            bytes=path.stat().st_size,
                            sha256=ex.digest(path),
                            fingerprint=fingerprints[step],
                            completed_steps=step,
                        ),
                    )
        fingerprints[config.updates] = training.fingerprint(named)
        for split in ("train", "final"):
            evaluation(split, config.updates)
        outcome["arms"][arm] = {str(k): v for k, v in fingerprints.items()}
    ex.write_new(args.output / "FINGERPRINTS.json", outcome["arms"])
    return outcome


def replay_body(core, args, plan, seal):
    torch = cpu_runtime(plan)
    core.load_runtime()
    return replay_run(torch, args, plan)


def replay_run(torch, args, plan):
    from latent_workspace import training

    rule = plan["replay"]
    role = f"route_cut{rule['cut']}_s{plan['seeds'].index(rule['seed']) + 1}"
    source = args.output.parent / role
    cut, seed = parse_role(plan, role)
    bank = load_bank(torch, args.output.parent / f"extract_cut{cut}", "train")
    steps = plan["route"]["steps"] if rule["arm"] == "route" else 0
    route, optimizer, config, named = build(plan, seed, steps)
    receipt = ex.read(source / f"CHECKPOINT_{rule['arm']}_step{rule['from_step']}.json")
    path = args.checkpoints / role / receipt["path"]
    ex.require(ex.digest(path) == receipt["sha256"], "Replay checkpoint bytes")
    state = torch.load(path, map_location="cpu", weights_only=True)
    route.load_state_dict(state["route"])
    optimizer.load_state_dict(state["optimizer"])
    ex.require(state["completed_steps"] == rule["from_step"], "Checkpoint step")
    restored = training.fingerprint(named)
    ex.require(restored == receipt["fingerprint"], "Restored state differs")
    update = training.update(route, None, optimizer, bank, config, rule["execute_step"])
    replayed = training.fingerprint(named)
    expected = ex.read(source / "FINGERPRINTS.json")[rule["arm"]][str(rule["execute_step"])]
    lines = (source / f"updates_{rule['arm']}.jsonl").read_text().splitlines()
    original = json.loads(lines[rule["execute_step"] - 1])
    report = dict(
        role=role,
        arm=rule["arm"],
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


# ---- endpoints (CPU) --------------------------------------------------------------


def condition_scores(meta, scores):
    """Scores per condition, each in question order."""
    out = {}
    for row, value in zip(meta, scores, strict=True):
        out.setdefault(row["condition"], {})[row["question"]] = value
    return {c: [values[i] for i in sorted(values)] for c, values in out.items()}


def diagnose_scores(questions, by_condition, rule):
    from latent_workspace import availability

    contrasts = availability.contrasts(questions, lambda c: by_condition[c], availability.FACTORS)
    result = availability.diagnose(contrasts, rule)
    accuracy = {}
    for condition, values in by_condition.items():
        side = 1 if condition.endswith("twin") else 0
        correct = [
            (v[1] > v[0]) == bool(q["labels"][side]) for v, q in zip(values, questions, strict=True)
        ]
        accuracy[condition] = sum(correct) / len(correct)
    result["accuracy"] = accuracy
    return result


def seeds_verdict(verdicts):
    if all(v == VERDICTS[0] for v in verdicts):
        return VERDICTS[0]
    if all(v in VERDICTS[:2] for v in verdicts):
        return VERDICTS[1]
    return VERDICTS[2]


def read_depth(cuts, verdicts):
    """The deepest cut at which the verdict is at least directional, or None."""
    reached = [cut for cut, verdict in zip(cuts, verdicts, strict=True) if verdict in VERDICTS[:2]]
    return max(reached) if reached else None


def endpoints_body(core, args, plan, seal):
    cpu_runtime(plan)
    result = endpoints_for(args.output.parent, plan)
    ex.write_new(args.output / "ENDPOINTS.json", result)
    return outcome_of(result)


def outcome_of(result):
    ladder = result["ladder"]
    return dict(
        host={str(c): ladder[str(c)]["host"]["verdict"] for c in CUTS},
        route={str(c): ladder[str(c)]["route"]["verdict"] for c in CUTS},
        read_depth_host=result["read_depth_host"],
        read_depth_route=result["read_depth_route"],
    )


def endpoints_for(raw, plan):
    """Every cut's verdicts from the saved scores alone (shared with the offline verifier)."""
    rule = plan["endpoints"]["rule"]
    step = plan["training"]["updates"]
    ladder = {}
    for cut in CUTS:
        folder = raw / f"extract_cut{cut}"
        questions = ex.read_gz(folder / "QUESTIONS_final.json.gz")
        meta = ex.read_gz(folder / "ROWS_final.json.gz")
        host = diagnose_scores(
            questions,
            condition_scores(meta, ex.read_gz(folder / "HOST_SCORES_final.json.gz")),
            rule,
        )
        arms = {}
        for arm in ARMS:
            per_seed = []
            for index in range(1, SEEDS + 1):
                scores = ex.read_gz(
                    raw / f"route_cut{cut}_s{index}" / f"eval_{arm}_final_step{step}.json.gz"
                )
                per_seed.append(
                    diagnose_scores(
                        questions, condition_scores(meta, scores["adapted_logits"]), rule
                    )
                )
            arms[arm] = dict(
                verdict=seeds_verdict([s["verdict"] for s in per_seed]), per_seed=per_seed
            )
        ladder[str(cut)] = dict(host=host, **arms)
    return dict(
        ladder=ladder,
        read_depth_host=read_depth(CUTS, [ladder[str(c)]["host"]["verdict"] for c in CUTS]),
        read_depth_route=read_depth(CUTS, [ladder[str(c)]["route"]["verdict"] for c in CUTS]),
        rule=rule,
    )


def summary(out, plan):
    return ex.read(out / "endpoints" / "FINISHED.json")["outcome"]


RUN = ex.SealedRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass=TINY_PASS,
    roles=ROLES,
    role_status={
        **{f"extract_cut{k}": EXTRACT_PASS for k in CUTS},
        **dict.fromkeys(ARM_ROLES, ARM_PASS),
        "replay": REPLAY_PASS,
        "endpoints": ENDPOINT_PASS,
    },
    validate=validate_plan,
    load=load,
)
BODIES = {
    **{f"extract_cut{k}": extract_body(k) for k in CUTS},
    **dict.fromkeys(ARM_ROLES, arm_body),
    "replay": replay_body,
    "endpoints": endpoints_body,
}


if __name__ == "__main__":
    raise SystemExit(RUN.main(BODIES, summary))
