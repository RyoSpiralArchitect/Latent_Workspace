#!/usr/bin/env python3
"""Sealed V20 A1: the Availability ladder on the V19 checkpoints.

Where is memory content (intact against twin facts) lost in V19's frozen
dual-budget pipeline: in the written memory, in the read output, or on the way
to the native head? Three GPU roles read V19's ``ordered_cap025`` state at
initialization and after updates 256 and 512 with the frozen V19 code (rule 6
of docs/ARCHITECTURE.md). They record memory slots, both route outputs and both
reader queries for every train and held-out world, memory condition and query.
One CPU role fits the engine's ladder probes and writes the verdict per state.
No training of the workspace, generation, judge call, native update or deletion.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
from latent_workspace import execution as ex  # noqa: E402

ENTRY = "scripts/run_v20_a1_ladder.py"
PLAN = "configs/v20/A1_LADDER_PLAN.json"
PLAN_CANONICAL_SHA256 = "67b465aa1e712e750ad37c59be36329af3e6d52ceb1ac4cefc3888dc3aedef71"
STATES = ("initial", "step256", "step512")
ROLES = (*(f"extract_{state}" for state in STATES), "probe")
CONDITIONS = ("intact", "twin", "reverse_intact", "unrelated", "random_intact")
SPLITS = ("train", "final")
TINY_PASS = "TINY_V20_A1_HARNESS_PASS_NOT_7B"
EXTRACT_PASS = "V20_A1_STATE_EXTRACTED"
PROBE_PASS = "V20_A1_LADDER_COMPLETE"
QUALIFICATION_CASES = 18
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
    """The frozen V19 runner: data, arm, schedule, stores and fingerprints."""
    return load("run_v19_frozen_diagnostic")


def validate_plan(plan):
    ex.require(ex.plan_hash(plan) == PLAN_CANONICAL_SHA256, "Frozen V20 A1 plan changed")
    ex.require(
        tuple(plan["states"]) == STATES
        and tuple(plan["conditions"]) == CONDITIONS
        and plan["qualification_cases"] == QUALIFICATION_CASES
        and plan["endpoints"]["alpha"] > 0
        and all(plan[k] == v for k, v in ex.CEILING.items()),
        "Frozen V20 A1 plan semantics changed",
    )


# ---- extraction (frozen V19 code reads V19 artifacts) ---------------------------


def receipts_dir(plan):
    folder = Path(plan["v19"]["receipts"])
    for name, digest in plan["v19"]["receipt_sha256"].items():
        ex.require(ex.digest(folder / name) == digest, f"V19 receipt changed: {name}")
    return folder


def restore(core, plan19, parent, objective, architecture, records, guard, plan, state):
    """Rebuild the V19 learner for ``state`` against V19's own contract and receipts."""
    from latent_workspace_ft_v10.v19_dual_budget_window_learner import V19DualBudgetWindowLearner

    folder = receipts_dir(plan)
    context = ex.read(folder / "CONTEXT.json")
    arm = v19().arm_spec(plan19, plan["v19"]["arm"])
    base, bridge, tokenizer = v19().fresh(core, parent, architecture, guard, plan19, arm)
    windows = v19().schedule(plan19, records["train"])
    if state == "initial":
        learner = v19().build_learner(
            core, plan19, parent, objective, base, bridge, context["contract"], windows, arm
        )
        return learner, tokenizer, context, ex.read(folder / "INITIAL.json")["light"]
    step = int(state.removeprefix("step"))
    receipt = ex.read(folder / f"CHECKPOINT_step{step}.json")
    path = Path(plan["v19"]["checkpoints"]) / receipt["path"]
    ex.require(
        path.stat().st_size == receipt["bytes"] and ex.digest(path) == receipt["sha256"],
        "V19 checkpoint bytes",
    )
    payload = core.torch.load(path, map_location="cpu", weights_only=True)
    learner = V19DualBudgetWindowLearner.restore(
        core.MistralTrainingBinding(base, plan19["context_boundary"]),
        bridge,
        payload,
        expected_workspace_policy=v19().workspace_policy(arm["workspace_query"]),
        expected_metadata=context["metadata"],
        expected_run_contract=context["contract"],
        expected_schedule=windows,
        expected_state_sha256=receipt["state_sha256"],
        expected_reference_bank=None,
        eos_weight=plan19["eos_weight"],
        eos_token_id=plan19["eos_token_id"],
    )
    ex.require(learner.completed_steps == step, "Restored step")
    return learner, tokenizer, context, None


def extract_rows(learner, store, spans, seed, guard=lambda *_a, **_k: None):
    """Memory, both route outputs and both queries for every world, condition and query.

    Mirrors V19's evaluator: the pipeline's residual must equal the recomputed
    parts exactly, and zero memory must reproduce the frozen direct base.
    """
    import torch

    from latent_workspace_ft_v10.v16_comparison_eval import memory_bank

    memory, mask, common, interaction, rows = [], [], [], [], []
    query_common, query_interaction = [], []
    with torch.no_grad():
        for world, record in enumerate(store.records):
            bank = memory_bank(learner, store, world, seed)
            memory.append(torch.stack([bank[c][0][0].float().cpu() for c in CONDITIONS]))
            mask.append(torch.stack([bank[c][1][0].cpu() for c in CONDITIONS]))
            world_common, world_interaction, world_qc, world_qi = [], [], [], []
            for query in range(len(record["queries"])):
                guard(f"extract:{world}:{query}")
                row = store.renderings[world, query]
                ids = tuple(row["prompt_ids"])
                tokens = torch.tensor([ids], device=next(learner.base.parameters()).device)
                direct = learner.base(
                    input_ids=tokens, attention_mask=torch.ones_like(tokens), use_cache=False
                ).logits
                outputs = {}
                for condition in (*CONDITIONS, "zero"):
                    memory_c, mask_c = bank[condition]
                    output = learner.pipeline(ids, memory_c, mask_c, span=spans[world, query])
                    parts = learner.bridge.parts(
                        output.common_query, output.interaction_query, memory_c, mask_c
                    )
                    ex.require(torch.equal(parts["delta"], output.delta), "Parts reproduce delta")
                    if condition == "zero":
                        ex.require(
                            torch.equal(direct, output.readout.logits), "Zero memory is native"
                        )
                    outputs[condition] = (output, parts)
                first = outputs[CONDITIONS[0]][0]
                ex.require(
                    all(
                        torch.equal(o.common_query, first.common_query)
                        and torch.equal(o.interaction_query, first.interaction_query)
                        for o, _ in outputs.values()
                    ),
                    "Reader queries must not depend on memory",
                )
                world_common.append(
                    torch.stack(
                        [outputs[c][1]["common"].reshape(-1).float().cpu() for c in CONDITIONS]
                    )
                )
                world_interaction.append(
                    torch.stack(
                        [outputs[c][1]["interaction"].reshape(-1).float().cpu() for c in CONDITIONS]
                    )
                )
                world_qc.append(first.common_query.reshape(-1).float().cpu())
                world_qi.append(first.interaction_query.reshape(-1).float().cpu())
                rows.append(
                    dict(
                        world=world,
                        query=query,
                        labels=[int(record["answers"][side][query]) for side in (0, 1)],
                        affected=record["answers"][0][query] != record["answers"][1][query],
                        hop=int(record["hop_distances"][query]),
                    )
                )
            common.append(torch.stack(world_common))
            interaction.append(torch.stack(world_interaction))
            query_common.append(torch.stack(world_qc))
            query_interaction.append(torch.stack(world_qi))
    tensors = {
        "memory": torch.stack(memory),
        "mask": torch.stack(mask),
        "common": torch.stack(common),
        "interaction": torch.stack(interaction),
        "query_common": torch.stack(query_common),
        "query_interaction": torch.stack(query_interaction),
    }
    return tensors, rows


def extract_body(state):
    def body(core, args, plan, seal):
        from safetensors.torch import save_file

        core.load_runtime()
        plan19 = ex.read(ROOT / plan["v19"]["plan"])
        v19().validate_plan(plan19)
        # V19's roles fixed threads, TF32 and matmul precision before loading the model;
        # the checkpoints' execution policy records them, so a restore needs the same.
        runtime = load("run_v16_adapter_full_recovery_02").runtime(core, plan19)
        torch = core.torch
        guard = core.legacy.Guard(plan["resources"], args.output)
        guard("admission", admission=True, forecast_bytes=plan["storage_forecast_bytes"])
        ex.require(torch.cuda.device_count() == 1, "One CUDA device")
        torch.cuda.set_per_process_memory_fraction(
            plan["resources"]["allocator_cap_gib"]
            * ex.GIB
            / torch.cuda.get_device_properties(0).total_memory
        )
        parent, objective, architecture, _ = core.legacy.validate()
        records = v19().load_records(plan19)
        v19().validate_data(core.legacy.old, records)
        learner, tokenizer, context, initial = restore(
            core, plan19, parent, objective, architecture, records, guard, plan, state
        )
        stores, spans, receipts = v19().stores_for(core, learner, tokenizer, records, guard, SPLITS)
        for split in SPLITS:
            ex.require(receipts[split] == context["stores"][split], f"V19 inputs differ: {split}")
        if initial is not None:
            light = v19().light_fingerprint(core, learner.inner)
            ex.require(light == initial, "Rebuilt initial state differs from V19's")
        outcome = dict(
            state=state, completed_steps=learner.completed_steps, runtime=runtime, splits={}
        )
        for split in SPLITS:
            tensors, rows = extract_rows(
                learner,
                stores[split],
                spans[split],
                plan19["random_memory_seed"],
                v19().throttled(guard, 64),
            )
            save_file(
                {k: v.contiguous() for k, v in tensors.items()},
                str(args.output / f"FEATURES_{split}.safetensors"),
            )
            ex.write_gz(args.output / f"ROWS_{split}.json.gz", rows)
            outcome["splits"][split] = {k: list(v.shape) for k, v in tensors.items()}
        guard("finished")
        outcome["peak_cuda_allocated_bytes"] = torch.cuda.max_memory_allocated()
        return outcome

    return body


# ---- probes (engine instrument) --------------------------------------------------


def probe_sets(tensors, rows, kind, shuffle=False):
    """Rows (world, side, query) for the memory probe; ``kind``: memory, zero or shuffled."""
    import torch

    worlds = tensors["memory"].shape[0]
    query, memory, mask, label, index = [], [], [], [], {}
    for row in rows:
        for side in (0, 1):
            source = (row["world"] + 1) % worlds if shuffle else row["world"]
            index[row["world"], side, row["query"]] = len(label)
            query.append(tensors["query_common"][row["world"], row["query"]])
            memory.append(tensors["memory"][source, side])
            mask.append(tensors["mask"][source, side])
            label.append(row["labels"][side])
    memory = torch.stack(memory)
    if kind == "zero":
        memory = torch.zeros_like(memory)
    data = dict(
        query=torch.stack(query),
        memory=memory,
        mask=torch.stack(mask),
        label=torch.tensor(label),
    )
    return data, index


def contrast_sets(tensors, rows, route, right=1):
    """Affected (world, query): ``v(intact) - v(condition right)`` and the intact answer."""
    import torch

    x, y, worlds = [], [], []
    for row in rows:
        if row["affected"]:
            values = tensors[route][row["world"], row["query"]]
            x.append(values[0] - values[right])
            y.append(row["labels"][0])
            worlds.append(row["world"])
    return torch.stack(x), torch.tensor(y), worlds


def route_values(tensors, route):
    if route == "delta":
        return {**tensors, "delta": tensors["common"] + tensors["interaction"]}
    return tensors


def ladder_for_state(features, rows, settings, alpha):
    """Rungs R1 (memory) and R2 (read output) for one state; pure CPU arithmetic."""
    from latent_workspace import ladder

    train, test = features["train"], features["final"]
    affected = [r for r in rows["final"] if r["affected"]]
    memory = {}
    for kind, shuffle in (("memory", False), ("zero", False), ("shuffled", True)):
        fit, _ = probe_sets(train, rows["train"], kind, shuffle)
        held, index = probe_sets(test, rows["final"], kind, shuffle)
        labels = held["label"].tolist()
        runs = []
        for seed in settings["attention"]["seeds"]:
            predictions, loss = ladder.fit_attention_probe(
                fit,
                held,
                seed=seed,
                width=settings["attention"]["width"],
                steps=settings["attention"]["steps"],
                lr=settings["attention"]["lr"],
                weight_decay=settings["attention"]["weight_decay"],
            )
            correct = [p == bool(y) for p, y in zip(predictions, labels, strict=True)]
            pairs = {
                (r["world"], r["query"]): (
                    index[r["world"], 0, r["query"]],
                    index[r["world"], 1, r["query"]],
                )
                for r in affected
            }
            following = ladder.pair_following(correct, pairs)
            runs.append(
                dict(
                    seed=seed,
                    final_loss=loss,
                    accuracy=sum(correct) / len(correct),
                    content_following=sum(following.values()),
                    world_counts=ladder.world_counts(
                        list(following.values()), [k[0] for k in following]
                    ),
                )
            )
        memory[kind] = runs
    tests = []
    for probe, zero, shuffled in zip(
        memory["memory"], memory["zero"], memory["shuffled"], strict=True
    ):
        tests.append(
            dict(
                seed=probe["seed"],
                against_zero=ladder.sign_test(probe["world_counts"], zero["world_counts"]),
                against_shuffled=ladder.sign_test(probe["world_counts"], shuffled["world_counts"]),
            )
        )
    memory_pass = all(
        t["against_zero"]["p_one_sided"] <= alpha and t["against_shuffled"]["p_one_sided"] <= alpha
        for t in tests
    )
    reading = {}
    for route in settings["routes"]:
        fit_x, fit_y, _ = contrast_sets(route_values(train, route), rows["train"], route)
        held_x, held_y, worlds = contrast_sets(route_values(test, route), rows["final"], route)
        predictions = ladder.fit_contrast_probe(
            fit_x,
            fit_y,
            held_x,
            l2=settings["contrast"]["l2"],
            iterations=settings["contrast"]["iterations"],
        )
        correct = [p == bool(y) for p, y in zip(predictions, held_y.tolist(), strict=True)]
        form_x, _, _ = contrast_sets(route_values(test, route), rows["final"], route, right=2)
        fit_form, _, _ = contrast_sets(route_values(train, route), rows["train"], route, right=2)
        form_predictions = ladder.fit_contrast_probe(
            fit_form,
            fit_y,
            form_x,
            l2=settings["contrast"]["l2"],
            iterations=settings["contrast"]["iterations"],
        )
        counts = ladder.world_counts(correct, worlds)
        reading[route] = dict(
            accuracy=sum(correct) / len(correct),
            world_counts=counts,
            world_test=ladder.chance_sign_test(counts, 2),
            form_control_accuracy=sum(
                p == bool(y) for p, y in zip(form_predictions, held_y.tolist(), strict=True)
            )
            / len(form_predictions),
            distinguishability=route_distinguishability(route_values(test, route)[route]),
        )
    reading_pass = reading[settings["primary_route"]]["world_test"]["p_one_sided"] <= alpha
    flat = test["memory"].flatten(2)
    return dict(
        memory=memory,
        memory_tests=tests,
        memory_pass=memory_pass,
        memory_distinguishability=ladder.distinguishability(
            [m[0] - m[1] for m in flat], [m[0] - m[2] for m in flat]
        ),
        reading=reading,
        reading_pass=reading_pass,
        verdict=ladder.ladder_verdict(memory_pass, reading_pass),
    )


def route_distinguishability(values):
    """Median over (world, query) of |intact - twin| / |intact - reverse_intact|."""
    from latent_workspace import ladder

    flat = values.reshape(-1, *values.shape[2:])
    return ladder.distinguishability([v[0] - v[1] for v in flat], [v[0] - v[2] for v in flat])


def load_features(folder):
    from safetensors.torch import load_file

    features = {s: load_file(str(folder / f"FEATURES_{s}.safetensors")) for s in SPLITS}
    rows = {s: ex.read_gz(folder / f"ROWS_{s}.json.gz") for s in SPLITS}
    return features, rows


def probe_body(core, args, plan, seal):
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    import torch

    torch.set_num_threads(plan["probes"]["threads"])
    torch.use_deterministic_algorithms(True)
    core.load_runtime()
    ex.require(not torch.cuda.is_available(), "Probe role must not see a GPU")
    results = {}
    for state in STATES:
        folder = args.output.parent / f"extract_{state}"
        ex.require(ex.read(folder / "FINISHED.json")["status"] == EXTRACT_PASS, f"{state} missing")
        features, rows = load_features(folder)
        results[state] = ladder_for_state(
            features, rows, plan["probes"], plan["endpoints"]["alpha"]
        )
    ex.write_new(args.output / "LADDER.json", results)
    return {state: results[state]["verdict"] for state in STATES}


def summary(out, plan):
    return ex.read(out / "probe" / "FINISHED.json")["outcome"]


RUN = ex.SealedRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass=TINY_PASS,
    roles=ROLES,
    role_status={**{f"extract_{s}": EXTRACT_PASS for s in STATES}, "probe": PROBE_PASS},
    validate=validate_plan,
    load=load,
)
BODIES = {**{f"extract_{s}": extract_body(s) for s in STATES}, "probe": probe_body}


if __name__ == "__main__":
    raise SystemExit(RUN.main(BODIES, summary))
