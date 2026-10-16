#!/usr/bin/env python3
"""Sealed V20 A2: the flip through v4's logit route, with the facts only in memory.

With pinned Mistral-7B-Instruct-v0.3 frozen and the world facts given only as a
separately encoded memory (V19's context encoding: the host's residual stream
at cut 16 of the canonical facts, never in the prompt), does a v5 lattice over
the [memory; question] states feeding v4's gated logit residual answer from the
memory, so that the twin's facts flip the affected held-out answers? Lane A's
flip endpoint is read unchanged (engine ``availability``).

One GPU role writes the host features. Six CPU roles train the route with the
engine's trainer: the memory arm and a query-only control, three seeds each,
both sides of every training world. A fresh process replays one update; the
endpoint role writes the verdict. No generation, judge call, native update or
deletion.
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

ENTRY = "scripts/run_v20_a2_flip.py"
PLAN = "configs/v20/A2_FLIP_PLAN.json"
PLAN_CANONICAL_SHA256 = "0" * 64
SPLITS = ("train", "dev", "final")
ARMS = ("memory", "query_only")
SEEDS = 3
ARM_ROLES = tuple(f"{arm}_s{i}" for arm in ARMS for i in range(1, SEEDS + 1))
ROLES = ("extract", *ARM_ROLES, "replay", "endpoints")
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
    "reverse_intact",
    "reverse_twin",
    "unrelated",
    "random_intact",
    "random_twin",
    "none",
)
TRAIN_CONDITIONS = ("intact", "twin", "random_intact", "random_twin")
TRAIN_FACTORS = ("actual", "random_pair")
VERDICTS = ("CONTENT_REACHES_ANSWERS", "DIRECTIONAL_ONLY", "NOT_ESTABLISHED", "NOT_LEARNED")
TINY_PASS = "TINY_V20_A2_HARNESS_PASS_NOT_7B"
EXTRACT_PASS = "V20_A2_DEFERRED_FEATURES_EXTRACTED"
ARM_PASS = "V20_A2_ARM_COMPLETE"
REPLAY_PASS = "V20_A2_FRESH_PROCESS_EXACT_REPLAY"
ENDPOINT_PASS = "V20_A2_ENDPOINTS_COMPLETE"
QUALIFICATION_CASES = 0
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
    """V19's runner: data loading and its symbolic-oracle data checks."""
    return load("run_v19_frozen_diagnostic")


def validate_plan(plan):
    ex.require(ex.plan_hash(plan) == PLAN_CANONICAL_SHA256, "Frozen V20 A2 plan changed")
    ex.require(
        tuple(plan["arms"]) == ARMS
        and len(plan["seeds"]) == SEEDS
        and tuple(plan["conditions"]) == CONDITIONS
        and plan["qualification_cases"] == QUALIFICATION_CASES
        and plan["endpoints"]["rule"]["chance_control"] == "random_pair"
        and all(plan[k] == v for k, v in ex.CEILING.items()),
        "Frozen V20 A2 plan semantics changed",
    )


def parse_role(plan, role):
    arm, index = role.rsplit("_s", 1)
    ex.require(arm in ARMS and role in ARM_ROLES, f"Unknown arm role {role}")
    return arm, plan["seeds"][int(index) - 1]


def wording(query):
    return "outrank" if query.startswith("Does ") else "ranked_above"


# ---- rendering and host features (GPU) -------------------------------------------


def render(old, tokenizer, records, plan):
    """Question rows (world, query) and memory rows (world, key), as V15's LiveStore."""
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
            ids = list(tokenizer.encode(text, add_special_tokens=False))
            memories.append(dict(world=w, key=name, ids=ids))
    return questions, memories


def extract_split(torch, host, readout, questions, memories, boundary, candidates, guard):
    """Cut-``boundary`` states of every question and memory, with native parity per row."""
    device = host.head.weight.device
    states, offsets, base_rows = [], [0], []
    for index, row in enumerate(questions):
        guard(f"question:{index}")
        ids = torch.tensor([row["prompt_ids"]], device=device)
        mask = torch.ones_like(ids)
        logits = host.logits(ids, mask)
        final = host.final_states(ids, mask)
        shared = readout(final, torch.zeros_like(final[:, -1:]).float())
        ex.require(torch.equal(logits, shared.logits), "Native head parity failed")
        cut = host.to_cut(ids, mask, boundary)
        ex.require(torch.equal(host.from_cut(cut, mask, boundary), logits), "Cut parity failed")
        states.append(cut[0].detach().cpu())
        offsets.append(offsets[-1] + cut.shape[1])
        base_rows.append(logits[0, -1, list(candidates)].float().cpu())
    memory_states, memory_offsets = [], [0]
    for index, row in enumerate(memories):
        guard(f"memory:{index}")
        ids = torch.tensor([row["ids"]], device=device)
        cut = host.to_cut(ids, torch.ones_like(ids), boundary)
        memory_states.append(cut[0].detach().cpu())
        memory_offsets.append(memory_offsets[-1] + cut.shape[1])
    return {
        "question_states": torch.cat(states),
        "question_offsets": torch.tensor(offsets, dtype=torch.long),
        "base_logits": torch.stack(base_rows),
        "memory_states": torch.cat(memory_states),
        "memory_offsets": torch.tensor(memory_offsets, dtype=torch.long),
    }


def split_receipt(questions, memories, base_logits, dtype):
    base = [b[1] > b[0] for b in base_logits.tolist()]
    return dict(
        questions=len(questions),
        memories=len(memories),
        question_tokens=sum(len(r["prompt_ids"]) for r in questions),
        memory_tokens=sum(len(r["ids"]) for r in memories),
        max_question_length=max(len(r["prompt_ids"]) for r in questions),
        max_memory_length=max(len(r["ids"]) for r in memories),
        base_correct_intact=sum(p == bool(r["labels"][0]) for p, r in zip(base, questions)),
        base_correct_twin=sum(p == bool(r["labels"][1]) for p, r in zip(base, questions)),
        state_dtype=dtype,
    )


def extract_body(core, args, plan, seal):
    from safetensors.torch import save_file

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
    ex.require(base.lm_head.weight.shape[0] == plan["route"]["vocab_size"], "Vocabulary size")
    host = DecoderHost(base)
    ex.require(host.hidden_size == plan["route"]["hidden_dim"], "Hidden size")
    readout = host.readout()
    records = v19().load_records(plan)
    audit = v19().validate_data(old, records)
    throttle = v19().throttled(guard, 64)
    outcome = dict(splits={}, data_audit=audit, model_config=architecture["model"])
    for split in SPLITS:
        questions, memories = render(old, tokenizer, records[split], plan)
        with torch.no_grad():
            tensors = extract_split(
                torch,
                host,
                readout,
                questions,
                memories,
                plan["memory_boundary"],
                plan["candidate_ids"],
                lambda phase, split=split: throttle(f"extract:{split}:{phase}"),
            )
        save_file(
            {k: v.contiguous() for k, v in tensors.items()},
            str(args.output / f"FEATURES_{split}.safetensors"),
        )
        ex.write_gz(
            args.output / f"ROWS_{split}.json.gz", dict(questions=questions, memories=memories)
        )
        outcome["splits"][split] = split_receipt(
            questions, memories, tensors["base_logits"], str(tensors["question_states"].dtype)
        )
    guard("finished")
    outcome["peak_cuda_allocated_bytes"] = torch.cuda.max_memory_allocated()
    return outcome


# ---- banks (CPU) -----------------------------------------------------------------


def load_split(folder, split):
    from safetensors.torch import load_file

    return load_file(str(folder / f"FEATURES_{split}.safetensors")), ex.read_gz(
        folder / f"ROWS_{split}.json.gz"
    )


def key_index(name):
    return [name for name, _ in MEMORY_KEYS].index(name)


def own_side_bank(torch, tensors, rows, with_memory):
    """Rows (world, side, query): each side's question, with its own facts as memory."""
    from latent_workspace import training

    questions = rows["questions"]
    by_world = {}
    for index, row in enumerate(questions):
        by_world.setdefault(row["world"], []).append(index)
    segments, targets, worlds, memory = [], [], [], []
    for world in sorted(by_world):
        for side in (0, 1):
            for index in by_world[world]:
                segments.append(index)
                targets.append(questions[index]["labels"][side])
                worlds.append(world)
                memory.append(world * len(MEMORY_KEYS) + side)
    segments = torch.tensor(segments)
    bank = training.FeatureBank(
        tensors["question_states"],
        tensors["question_offsets"],
        tensors["base_logits"][segments],
        torch.tensor(targets),
        torch.tensor(worlds),
        segments=segments,
    )
    if not with_memory:
        return bank
    return bank.with_memory(
        (tensors["memory_states"], tensors["memory_offsets"], torch.tensor(memory))
    )


def random_memory(torch, tensors, rows, seed):
    """V16's control per world: norm-matched Gaussian states for intact, then twin."""
    from latent_workspace import availability

    worlds = sorted({row["world"] for row in rows["questions"]})
    offsets = tensors["memory_offsets"]
    states, bounds = [], [0]
    for world in worlds:
        generator = torch.Generator().manual_seed(seed + world)
        for side in (0, 1):
            segment = world * len(MEMORY_KEYS) + side
            values = tensors["memory_states"][offsets[segment] : offsets[segment + 1]].float()
            mask = torch.ones(1, values.shape[0], dtype=torch.long)
            states.append(availability.norm_matched_random(values[None], mask, generator)[0])
            bounds.append(bounds[-1] + values.shape[0])
    return torch.cat(states), torch.tensor(bounds), {w: i for i, w in enumerate(worlds)}


def condition_bank(torch, tensors, rows, condition, randoms):
    """Rows (world, query) in order, every question read with the ``condition`` memory."""
    from latent_workspace import training

    questions = rows["questions"]
    segments = torch.arange(len(questions))
    bank = training.FeatureBank(
        tensors["question_states"],
        tensors["question_offsets"],
        tensors["base_logits"],
        torch.tensor([row["labels"][0] for row in questions]),
        torch.tensor([row["world"] for row in questions]),
        segments=segments,
    )
    if condition == "none":
        return bank
    if condition.startswith("random_"):
        states, bounds, position = randoms
        side = 0 if condition == "random_intact" else 1
        chosen = [2 * position[row["world"]] + side for row in questions]
        return bank.with_memory((states, bounds, torch.tensor(chosen)))
    chosen = [row["world"] * len(MEMORY_KEYS) + key_index(condition) for row in questions]
    return bank.with_memory(
        (tensors["memory_states"], tensors["memory_offsets"], torch.tensor(chosen))
    )


# ---- training roles (CPU) --------------------------------------------------------


def cpu_runtime(plan):
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    import torch

    torch.set_num_threads(plan["training"]["threads"])
    torch.use_deterministic_algorithms(True)
    return torch


def build(plan, seed):
    from latent_workspace import composition, training

    spec, settings = plan["route"], plan["training"]
    route = composition.DeliberationRoute(
        spec["hidden_dim"],
        spec["vocab_size"],
        tuple(plan["candidate_ids"]),
        steps=spec["steps"],
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


def banks_for(torch, plan, folder, arm):
    """Own-side banks for every split, and condition banks for train and final."""
    memory = arm == "memory"
    features = {split: load_split(folder, split) for split in SPLITS}
    own = {split: own_side_bank(torch, *features[split], memory) for split in SPLITS}
    conditions = {}
    for split, names in (("train", TRAIN_CONDITIONS), ("final", CONDITIONS)):
        tensors, rows = features[split]
        if not memory:
            names = ("none",)
        randoms = (
            random_memory(torch, tensors, rows, plan["random_memory_seed"]) if memory else None
        )
        conditions[split] = {
            name: condition_bank(torch, tensors, rows, name, randoms) for name in names
        }
    return own, conditions


def arm_body(core, args, plan, seal):
    torch = cpu_runtime(plan)
    core.load_runtime()
    ex.require(not torch.cuda.is_available(), "Arm roles must not see a GPU")
    from safetensors.torch import save_file

    from latent_workspace import training

    arm, seed = parse_role(plan, args.role)
    own, conditions = banks_for(torch, plan, args.output.parent / "extract", arm)
    route, optimizer, config, named = build(plan, seed)
    checkpoints = args.checkpoints / args.role
    checkpoints.mkdir(parents=True, exist_ok=False)
    fingerprints = {0: training.fingerprint(named)}

    def evaluation(name, bank, step, steps=None, final=False):
        result = training.evaluate(route, bank, steps=steps, final=final)
        adapted, latents = result if final else (result, None)
        suffix = "" if steps is None else f"_k{steps}"
        ex.write_gz(
            args.output / f"eval_{name}_step{step}{suffix}.json.gz",
            {"adapted_logits": adapted.tolist()},
        )
        return adapted, latents

    for name, bank in [("dev_own", own["dev"])] + [
        (f"final_{c}", b) for c, b in conditions["final"].items()
    ]:
        adapted, _ = evaluation(name, bank, 0)
        ex.require(torch.equal(adapted, bank.base_logits), f"Step 0 must equal base: {name}")
    with (args.output / "updates.jsonl").open("x") as log:
        for step in range(1, config.updates + 1):
            receipt = training.update(route, None, optimizer, own["train"], config, step)
            log.write(json.dumps(receipt) + "\n")
            if step in plan["checkpoint_steps"] or step == plan["replay"]["execute_step"]:
                fingerprints[step] = training.fingerprint(named)
            if step in plan["checkpoint_steps"]:
                path = checkpoints / f"step{step}.pt"
                torch.save(
                    dict(
                        route=route.state_dict(),
                        optimizer=optimizer.state_dict(),
                        completed_steps=step,
                    ),
                    path,
                )
                ex.write_new(
                    args.output / f"CHECKPOINT_step{step}.json",
                    dict(
                        path=path.name,
                        bytes=path.stat().st_size,
                        sha256=ex.digest(path),
                        fingerprint=fingerprints[step],
                        completed_steps=step,
                    ),
                )
            if step in plan["dev_evaluation_steps"]:
                evaluation("dev_own", own["dev"], step)
    last = config.updates
    fingerprints[last] = training.fingerprint(named)
    latents = {}
    for split in ("train", "final"):
        for name, bank in conditions[split].items():
            keep = name in ("intact", "twin", "none")
            _, states = evaluation(f"{split}_{name}", bank, last, final=keep)
            if keep:
                latents[f"{split}_{name}"] = states.contiguous()
    save_file(latents, str(args.output / f"LATENTS_step{last}.safetensors"))
    if arm == "memory":
        for steps in plan["truncation_steps"]:
            for name in ("intact", "twin"):
                evaluation(f"final_{name}", conditions["final"][name], last, steps=steps)
    ex.write_new(args.output / "FINGERPRINTS.json", {str(k): v for k, v in fingerprints.items()})
    return dict(arm=arm, seed=seed, fingerprints=fingerprints)


def replay_body(core, args, plan, seal):
    torch = cpu_runtime(plan)
    core.load_runtime()
    from latent_workspace import training

    rule = plan["replay"]
    role = f"{rule['arm']}_s{plan['seeds'].index(rule['seed']) + 1}"
    source = args.output.parent / role
    arm, seed = parse_role(plan, role)
    tensors, rows = load_split(args.output.parent / "extract", "train")
    bank = own_side_bank(torch, tensors, rows, arm == "memory")
    route, optimizer, config, named = build(plan, seed)
    receipt = ex.read(source / f"CHECKPOINT_step{rule['from_step']}.json")
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
    expected = ex.read(source / "FINGERPRINTS.json")[str(rule["execute_step"])]
    lines = (source / "updates.jsonl").read_text().splitlines()
    original = json.loads(lines[rule["execute_step"] - 1])
    report = dict(
        role=role,
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


# ---- endpoints (CPU) -------------------------------------------------------------


def scores(folder, split, condition, step, steps=None):
    suffix = "" if steps is None else f"_k{steps}"
    return ex.read_gz(folder / f"eval_{split}_{condition}_step{step}{suffix}.json.gz")[
        "adapted_logits"
    ]


def contrasts_for(questions, read, factors):
    """Lane A's contrast records; ``read(condition)`` gives that condition's scores."""
    from latent_workspace import availability

    cache = {}
    records = []
    for factor in factors:
        left, right = availability.FACTORS[factor]
        for name in (left, right):
            if name not in cache:
                cache[name] = [availability.choice(s) for s in read(name)]
        for index, row in enumerate(questions):
            records.append(
                availability.contrast(
                    row["world"],
                    row["query"],
                    factor,
                    row["labels"],
                    cache[left][index],
                    cache[right][index],
                )
            )
    return records


def accuracy(predicted, labels):
    return sum(p == bool(y) for p, y in zip(predicted, labels, strict=True)) / len(labels)


def seed_verdict(final, train):
    return VERDICTS[3] if train["verdict"] != VERDICTS[0] else final["verdict"]


def overall_verdict(seeds):
    if all(v == VERDICTS[0] for v in seeds):
        return VERDICTS[0]
    if all(v in VERDICTS[:2] for v in seeds):
        return VERDICTS[1]
    if all(v == VERDICTS[3] for v in seeds):
        return VERDICTS[3]
    return VERDICTS[2]


def ladder_probe(torch, folder, rows, step, plan):
    """Descriptive rung: a contrast probe on latent(intact) - latent(twin), train to final."""
    from safetensors.torch import load_file

    from latent_workspace import ladder

    latents = load_file(str(folder / f"LATENTS_step{step}.safetensors"))
    sets = {}
    for split in ("train", "final"):
        questions = rows[split]["questions"]
        chosen = [i for i, r in enumerate(questions) if r["affected"]]
        x = latents[f"{split}_intact"][chosen] - latents[f"{split}_twin"][chosen]
        y = torch.tensor([questions[i]["labels"][0] for i in chosen])
        sets[split] = (x, y, [questions[i]["world"] for i in chosen])
    settings = plan["descriptive_probe"]
    predictions = ladder.fit_contrast_probe(
        sets["train"][0],
        sets["train"][1],
        sets["final"][0],
        l2=settings["l2"],
        iterations=settings["iterations"],
    )
    correct = [p == bool(y) for p, y in zip(predictions, sets["final"][1].tolist(), strict=True)]
    counts = ladder.world_counts(correct, sets["final"][2])
    return dict(
        correct=sum(correct),
        rows=len(correct),
        world_test=ladder.chance_sign_test(counts, 2),
    )


def endpoints_body(core, args, plan, seal):
    torch = cpu_runtime(plan)
    core.load_runtime()
    from latent_workspace import availability

    raw = args.output.parent
    step = plan["endpoints"]["step"]
    rule = plan["endpoints"]["rule"]
    rows = {split: ex.read_gz(raw / "extract" / f"ROWS_{split}.json.gz") for split in SPLITS}
    final_q, train_q = rows["final"]["questions"], rows["train"]["questions"]
    per_seed, verdicts = [], []
    for index, seed in enumerate(plan["seeds"], start=1):
        folder = raw / f"memory_s{index}"
        final = availability.diagnose(
            contrasts_for(
                final_q, lambda c, f=folder: scores(f, "final", c, step), availability.FACTORS
            ),
            rule,
        )
        train = availability.diagnose(
            contrasts_for(train_q, lambda c, f=folder: scores(f, "train", c, step), TRAIN_FACTORS),
            rule,
        )
        verdict = seed_verdict(final, train)
        verdicts.append(verdict)
        choices = {
            c: [availability.choice(s)["prediction"] for s in scores(folder, "final", c, step)]
            for c in CONDITIONS
        }
        side = {c: 1 if c in ("twin", "reverse_twin", "random_twin") else 0 for c in CONDITIONS}
        query_only = [
            availability.choice(s)["prediction"]
            for s in scores(raw / f"query_only_s{index}", "final", "none", step)
        ]
        truncated = {}
        for steps in plan["truncation_steps"]:
            truncated[str(steps)] = availability.diagnose(
                contrasts_for(
                    final_q,
                    lambda c, f=folder, k=steps: (
                        scores(f, "final", c, step, k)
                        if c in ("intact", "twin")
                        else scores(f, "final", c, step)
                    ),
                    ("actual", "random_pair"),
                ),
                rule,
            )["flips"]
        per_seed.append(
            dict(
                seed=seed,
                verdict=verdict,
                final=final,
                train=train,
                accuracy={
                    c: accuracy(choices[c], [r["labels"][side[c]] for r in final_q])
                    for c in CONDITIONS
                },
                query_only_accuracy={
                    "intact": accuracy(query_only, [r["labels"][0] for r in final_q]),
                    "twin": accuracy(query_only, [r["labels"][1] for r in final_q]),
                },
                truncated_flips=truncated,
                ladder_probe=ladder_probe(torch, folder, rows, step, plan),
            )
        )
    base = [b[1] > b[0] for b in scores(raw / "memory_s1", "final", "intact", 0)]
    result = dict(
        verdict=overall_verdict(verdicts),
        per_seed=per_seed,
        base_accuracy={
            "intact": accuracy(base, [r["labels"][0] for r in final_q]),
            "twin": accuracy(base, [r["labels"][1] for r in final_q]),
        },
        rule=rule,
    )
    ex.write_new(args.output / "ENDPOINTS.json", result)
    return dict(verdict=result["verdict"], seeds=verdicts)


def summary(out, plan):
    return ex.read(out / "endpoints" / "FINISHED.json")["outcome"]


RUN = ex.SealedRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass=TINY_PASS,
    roles=ROLES,
    role_status={
        "extract": EXTRACT_PASS,
        **dict.fromkeys(ARM_ROLES, ARM_PASS),
        "replay": REPLAY_PASS,
        "endpoints": ENDPOINT_PASS,
    },
    validate=validate_plan,
    load=load,
)
BODIES = {
    "extract": extract_body,
    **dict.fromkeys(ARM_ROLES, arm_body),
    "replay": replay_body,
    "endpoints": endpoints_body,
}


if __name__ == "__main__":
    raise SystemExit(RUN.main(BODIES, summary))
