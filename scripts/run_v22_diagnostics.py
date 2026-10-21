#!/usr/bin/env python3
"""Frozen V22 weight/readout/trajectory analysis, no new generated sequences."""

from __future__ import annotations

import gc
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import run_native_7b_canary as common  # noqa: E402
import run_v22_comparison as previous  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402

PLAN = "configs/v22/WEIGHT_DIAGNOSTICS_01.json"
ENTRY = "scripts/run_v22_diagnostics.py"
ROLES = ("base", "v22")


def validate(plan):
    ex.require(plan["schema"] == "ltws-v22-weight-diagnostics-01" and plan["no_retry"], "Plan")
    ex.require(
        ex.digest(ROOT / plan["comparison_plan"]) == plan["comparison_plan_sha256"], "Prior plan"
    )
    ex.require(
        plan["planned"]
        == dict(
            arms=2,
            mmlu_rows=1140,
            world_rows=384,
            new_sequences=0,
            native_weight_updates=0,
            checkpoint_saves=0,
            judge_calls=0,
            weight_deletions=0,
            tensor_census=291,
            head_factorial_rows=570,
        ),
        "Finite diagnostic scope",
    )


def load_inputs(plan):
    old = ex.read(ROOT / plan["comparison_plan"])
    data, receipt = previous.inputs(old)
    prior = Path(plan["comparison_bundle"])
    ends = {}
    for role in ROLES:
        folder = prior / "raw" / role
        terminal = ex.read(folder / "FINISHED.json")
        files = ex.manifest(folder)
        files.pop("FINISHED.json")
        ex.require(files == terminal["files"], "Previous complete arm byte seal")
        ex.require(terminal["status"] == "V22_EVALUATION_ARM_COMPLETE", "Previous arm status")
        historical = ROOT / "provenance/pilots/v22_base_comparison01_20261021/furnace/raw" / role
        ex.require(
            ex.digest(folder / "FINISHED.json") == ex.digest(historical / "FINISHED.json"),
            "Prior terminal identity",
        )
        ends[role] = terminal
    return old, data, receipt, ends


def journal(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def original_tensor(plan, name):
    from safetensors import safe_open

    snapshot = Path(plan["original_snapshot"])
    index = ex.read(snapshot / "model.safetensors.index.json")["weight_map"]
    with safe_open(snapshot / index[name], framework="pt", device="cpu") as f:
        return f.get_tensor(name)


def census(graph, plan, old, output, guard):
    import torch

    from latent_workspace.native_diagnostics import weight_delta

    checkpoint = Path(old["training_bundle"]) / "checkpoints" / old["checkpoint"]["name"]
    # The complete body/payload/fingerprint were already verified by prepare().
    payload = torch.load(checkpoint, map_location="cpu", weights_only=False, mmap=True)
    named = list(graph.model.named_parameters())
    ex.require(set(payload["masters"]) == {n for n, _ in named}, "Census master coverage")
    with (output / "weights.jsonl").open("x") as stream:
        for i, (name, param) in enumerate(named):
            guard(f"census:{i}")
            base = original_tensor(plan, name)
            current = param.detach().cpu()
            result = weight_delta(base, current, payload["masters"][name])
            previous.append(stream, dict(name=name, **result))
            del base, current
            if (i + 1) % 32 == 0:
                print(f"census {i + 1}/{len(named)}", flush=True)
    del payload
    gc.collect()
    return len(named)


def run(core, args, plan, seal):
    import torch
    from torch.nn import functional as F

    from latent_workspace import native_diagnostics as diag
    from latent_workspace import native_evaluation as ev
    from latent_workspace.optimizer_state import tree_hash

    old, data, receipt, _ = load_inputs(plan)
    ex.write_new(args.output / "INPUT_MANIFEST.json", receipt)
    graph, tokenizer, guard, before = previous.prepare(core, args, {**old, **plan})
    device = next(graph.parameters()).device
    head_fp32 = graph.host.head.weight.detach().float()
    ex.require(graph.host.head.bias is None, "This factorial pins a bias-free native head")
    prior = Path(plan["comparison_bundle"]) / "raw" / args.role
    old_mmlu = {r["id"]: r for r in journal(prior / "mmlu.jsonl")}
    old_world = {(r["id"], r["route"]): r for r in journal(prior / "worlds.jsonl")}
    base_states = None
    if args.role == "v22":
        base_folder = args.output.parent / "base"
        terminal = ex.read(base_folder / "FINISHED.json")
        files = ex.manifest(base_folder)
        files.pop("FINISHED.json")
        ex.require(
            files == terminal["files"] and terminal["status"] == "V22_DIAGNOSTIC_ARM_COMPLETE",
            "Base activation seal",
        )
        base_states = ex.read_gz(base_folder / "mmlu_head_inputs.json.gz")
        base_scores = {r["id"]: r for r in journal(base_folder / "mmlu.jsonl")}
        ex.require(len(base_states) == len(data["mmlu"]), "Base activation count")
        original_head = original_tensor(plan, "lm_head.weight").float().to(device)
    saved_states = []
    with (args.output / "mmlu.jsonl").open("x") as stream, torch.no_grad():
        for i, row in enumerate(data["mmlu"]):
            guard(f"mmlu:{i}")
            batch = ev.tensor_batch(row["input_ids"], [], device)
            output, states, native, fp32 = diag.observe(
                graph, batch, [len(row["input_ids"]) - 1], head_fp32
            )
            score = ev.score_choices(native[0, 0], row["choice_ids"], row["target"])
            ex.require(
                score == {k: old_mmlu[row["id"]][k] for k in score}, "Exact historical MMLU replay"
            )
            record = dict(
                id=row["id"],
                subject=row["subject"],
                native=score,
                selected_fp32_self=ev.score_choices(
                    F.linear(states[0, 0].float(), head_fp32[row["choice_ids"]]),
                    list(range(4)),
                    row["target"],
                ),
                fp32_head=ev.score_choices(fp32[0, 0], row["choice_ids"], row["target"]),
                fp32_rounded=ev.score_choices(
                    fp32[0, 0].to(native.dtype), row["choice_ids"], row["target"]
                ),
                native_vs_fp32_rounded_max_abs=float((native - fp32.to(native.dtype)).abs().max()),
            )
            saved_states.append(dict(id=row["id"], values=states[0, 0].float().cpu().tolist()))
            if base_states is not None:
                ex.require(base_states[i]["id"] == row["id"], "Paired activation order")
                h0 = torch.tensor(base_states[i]["values"], device=device, dtype=torch.float32)
                ids = row["choice_ids"]
                # Every factorial cell uses the same four-row FP32 GEMV shape.
                heads = {"base": original_head[ids], "v22": head_fp32[ids]}
                hidden = {"base": h0, "v22": states[0, 0].float()}
                record["head_factorial"] = {
                    f"hidden_{h}_head_{w}": ev.score_choices(
                        F.linear(v, heads[w]), list(range(4)), row["target"]
                    )
                    for h, v in hidden.items()
                    for w in heads
                }
                ex.require(
                    record["head_factorial"]["hidden_base_head_base"]
                    == base_scores[row["id"]]["selected_fp32_self"]
                    and record["head_factorial"]["hidden_v22_head_v22"]
                    == record["selected_fp32_self"],
                    "Exact same-shape factorial self-cell replay",
                )
            previous.append(stream, record)
            del output, states, native, fp32, batch
            if (i + 1) % 50 == 0:
                print(f"{args.role}: MMLU {i + 1}/{len(data['mmlu'])}", flush=True)
    ex.write_gz(args.output / "mmlu_head_inputs.json.gz", saved_states)
    del saved_states, base_states
    if args.role == "v22":
        del original_head
    world_count, prefix_steps, replay_disagreements = 0, 0, 0
    with (args.output / "worlds.jsonl").open("x") as stream, torch.no_grad():
        for row in data["worlds"]:
            for route in old["world_routes"]:
                prior_row = old_world[row["row_id"], route]
                prefix = row["prefixes"][route]
                memory = row["memory_ids"] if route == "latent" else []
                gold = row["answer_ids"]
                observed = prior_row["token_ids"]
                fork = diag.first_difference(gold, observed)
                guard(f"teacher:{row['row_id']}:{route}")
                batch = ev.tensor_batch(prefix, memory, device, gold)
                positions = list(range(len(prefix) - 1, len(prefix) + len(gold) - 1))
                output, states, native, fp32 = diag.observe(graph, batch, positions, head_fp32)
                teacher = dict(
                    nll_sum=float(output.loss_sum), supervised_tokens=output.supervised_tokens
                )
                ex.require(teacher == prior_row["teacher"], "Exact historical teacher replay")
                token_scores = [
                    dict(
                        index=j,
                        token=tokenizer.decode([token]),
                        native=diag.token_score(native[0, j], token),
                        fp32_head=diag.token_score(fp32[0, j], token),
                    )
                    for j, token in enumerate(gold)
                ]
                del output, states, native, fp32, batch
                path = []
                # Predetermined recorded tokens, NEVER feed a newly computed argmax back.
                for j, token in enumerate(observed):
                    guard(f"fixed-prefix:{world_count}:{j}")
                    batch = ev.tensor_batch(prefix + observed[:j], memory, device)
                    output, states, native, fp32 = diag.observe(
                        graph, batch, [len(prefix) + j - 1], head_fp32
                    )
                    native_score = diag.token_score(native[0, 0], token)
                    record = dict(
                        index=j,
                        recorded_token=token,
                        token=tokenizer.decode([token]),
                        native=native_score,
                        fp32_head=diag.token_score(fp32[0, 0], token),
                    )
                    if fork is not None and j == fork and j < len(gold):
                        record["gold_at_first_fork"] = dict(
                            token=tokenizer.decode([gold[j]]),
                            native=diag.token_score(native[0, 0], gold[j]),
                            fp32_head=diag.token_score(fp32[0, 0], gold[j]),
                        )
                    replay_disagreements += int(not native_score["correct"])
                    path.append(record)
                    prefix_steps += 1
                    del output, states, native, fp32, batch
                previous.append(
                    stream,
                    dict(
                        id=row["row_id"],
                        group_id=row["group_id"],
                        family=row["family"],
                        split=row["split"],
                        mode=row["mode"],
                        route=route,
                        target=row["answer"],
                        recorded_text=prior_row["text"],
                        exact_match=prior_row["exact_match"],
                        gold_ids=gold,
                        recorded_ids=observed,
                        first_token_difference=fork,
                        teacher=teacher,
                        teacher_tokens=token_scores,
                        fixed_prefix_tokens=path,
                    ),
                )
                world_count += 1
            print(f"{args.role}: world conditions {world_count}/192", flush=True)
    del head_fp32
    torch.cuda.empty_cache()
    tensors = census(graph, plan, old, args.output, guard) if args.role == "v22" else 0
    after = tree_hash(graph.model.state_dict())
    ex.require(before == after, "Diagnostic mutated native weights")
    ex.write_new(args.output / "WEIGHT_IDENTITY.json", dict(before=before, after=after, equal=True))
    guard("complete")
    return dict(
        mmlu_rows=len(data["mmlu"]),
        world_rows=world_count,
        fixed_prefix_steps=prefix_steps,
        replay_disagreements=replay_disagreements,
        tensor_census=tensors,
        new_sequences=0,
        native_weight_updates=0,
        checkpoint_saves=0,
        engine_imports=common.engine_imports(seal),
        **common.peak(),
    )


def summary(folder, plan):
    ends = [ex.read(folder / role / "FINISHED.json")["outcome"] for role in ROLES]
    result = {
        key: sum(e[key] for e in ends)
        for key in (
            "mmlu_rows",
            "world_rows",
            "tensor_census",
            "fixed_prefix_steps",
            "replay_disagreements",
        )
    }
    for key in ("mmlu_rows", "world_rows", "tensor_census"):
        ex.require(result[key] == plan["planned"][key], f"Diagnostic denominator {key}")
    return dict(**result, new_sequences=0, native_weight_updates=0, checkpoint_saves=0)


RUN = ex.SealedRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass="TINY_V22_DIAGNOSTICS_PASS_NOT_7B",
    roles=ROLES,
    role_status={r: "V22_DIAGNOSTIC_ARM_COMPLETE" for r in ROLES},
    validate=validate,
    load=common.load,
)

if __name__ == "__main__":
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    os.environ["LTWS_CPU_SDPA_BACKEND"] = "math"
    raise SystemExit(RUN.main({r: run for r in ROLES}, summary))
