#!/usr/bin/env python3
"""Sealed no-update audit: bounded base canary/targets, then frozen-V22 gradients."""

from __future__ import annotations

import gc
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import run_native_7b_canary as common  # noqa: E402
import run_v22_comparison as previous  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402

ENTRY = "scripts/run_v23_gradient_audit.py"
PLAN = "configs/v23/GRADIENT_AUDIT_01.json"
STATUS = "V23_GRADIENT_AUDIT_ARM_COMPLETE"
PASS = "V23_TRAIN_ONLY_GRADIENT_AUDIT_COMPLETE_NOT_TRAINING"


def validate(plan):
    ex.require(plan["schema"] == "ltws-v23-gradient-audit-01" and plan["no_retry"], "Plan")
    ex.require(plan["pass_status"] == PASS, "Explicit final status")
    ex.require(
        (
            plan["vocabulary"],
            plan["teacher_target_dtype"],
            plan["teacher_temperature"],
            plan["preservation_targets"],
        )
        == (32768, "float32", 1.0, 932),
        "Frozen full-vocabulary teacher",
    )
    ex.require(
        (plan["world_rows"], plan["world_groups"], plan["preservation_rows"]) == (84, 14, 12),
        "Frozen panel size",
    )
    ex.require(
        plan["world_terms"] == ["total", "identity", "copy", "format", "mixed"]
        and plan["preservation_terms"] == ["ce", "kl"],
        "Frozen objectives",
    )
    ex.require(
        all(
            plan[k] == 0
            for k in (
                "native_weight_updates",
                "checkpoint_saves",
                "new_sequences",
                "judge_calls",
                "weight_deletions",
            )
        ),
        "No update/generation/judge/weight deletion",
    )


def inputs(plan):
    root = Path(plan["preparation_bundle"]) / "raw/data"
    public = ROOT / "provenance/engineering/v23_preparation01_20261022/furnace/raw/data"
    for name in ("AUDIT_SELECTION.json", "PREPARATION.json", "FINISHED.json"):
        ex.require(ex.digest(root / name) == ex.digest(public / name), "Fixed preparation receipt")
    path = root / "PRIVATE_AUDIT_INPUTS.json.gz"
    ex.require(ex.digest(path) == plan["private_inputs_sha256"], "Frozen private train inputs")
    data, select = ex.read_gz(path), ex.read(root / "AUDIT_SELECTION.json")
    worlds, preservation = data["worlds"], data["preservation"]
    ex.require([r["key"] for r in worlds] == select["world_keys"], "Exact world selection/order")
    ex.require(
        len(worlds) == plan["world_rows"]
        and len({r["group_id"] for r in worlds}) == plan["world_groups"],
        "World census",
    )
    ex.require(len(preservation) == plan["preservation_rows"], "Preservation census")
    for row, expected in zip(preservation, select["preservation"], strict=True):
        ex.require(ex.plan_hash(row) == expected["row_sha256"], "Exact preservation row")
        ex.require(not row["memory_ids"], "No-memory preservation")
    ex.require(
        all(r["split"] == "train" and r["language"] == "en" for r in worlds + preservation),
        "English train-only",
    )
    ex.require(
        sum(r["supervised_tokens"] for r in preservation) == plan["preservation_targets"],
        "Target positions",
    )
    ex.require(
        max(len(r["memory_ids"]) for r in worlds) == 105
        and max(len(r["input_ids"]) for r in worlds + preservation) == 128,
        "Untruncated resource envelope",
    )
    return data


def batch(row, device):
    import torch

    ids = torch.tensor([row["input_ids"]], dtype=torch.long, device=device)
    memory = torch.tensor([row["memory_ids"]], dtype=torch.long, device=device)
    return dict(
        input_ids=ids,
        attention_mask=torch.ones_like(ids),
        memory_ids=memory,
        memory_mask=torch.ones_like(memory),
        labels=torch.tensor([row["labels"]], dtype=torch.long, device=device),
    )


def objective(output, row, term, denominator, teacher=None):
    import torch

    from latent_workspace import objective_audit as obj

    labels = torch.tensor([row["labels"]], dtype=torch.long, device=output.logits.device)
    if term == "ce":
        return output.loss_sum / denominator
    if term == "kl":
        active = labels[:, 1:] != -100
        pred = output.logits[:, :-1][active][None]
        target = teacher.to(device=pred.device)[None]
        return (
            obj.full_vocab_kl_sum(pred, target, torch.ones_like(pred[..., 0], dtype=torch.bool))
            / denominator
        )
    parts = torch.tensor([row["parts"]], dtype=torch.long, device=labels.device)
    value = obj.partitioned_ce(output.logits, labels, parts, denominator=denominator)
    return value["total"] if term == "total" else value["components"][term]


def finish_model(graph, before, output):
    import torch

    from latent_workspace.optimizer_state import tree_hash

    ex.require(all(p.grad is None for p in graph.parameters()), "No retained gradients")
    after = tree_hash(graph.model.state_dict())
    ex.require(after == before, "No native weight change")
    ex.write_new(
        output / "UNCHANGED.json",
        dict(
            native_before=before,
            native_after=after,
            peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(),
            **ex.CEILING,
        ),
    )


def prepare(core, args, plan):
    setup = ex.read(ROOT / plan["comparison_plan"])
    setup["resources"] = plan["resources"]
    graph, tokenizer, guard, before = previous.prepare(core, args, setup)
    graph.eval().requires_grad_(True)
    ex.write_new(
        args.output / "AUDIT_POLICY.json",
        dict(
            training=False,
            requires_grad=True,
            activation_checkpointing=False,
            optimizer=False,
            gradient_aggregation=plan["gradient_aggregation"],
            path_scope=plan["path_scope"],
            native_sha256=before,
            source_inputs_sha256=plan["private_inputs_sha256"],
        ),
    )
    return graph, tokenizer, guard, before


def canary(graph, row, output, guard, plan):
    import torch
    from torch.nn import functional as F

    from latent_workspace import objective_audit as obj
    from latent_workspace.gradient_spill import GradientSpill, tensor_pair_stats, upper_replay

    device = next(graph.parameters()).device
    data = batch(row, device)
    result = graph(**data, capture_cut_trace=True)
    with torch.no_grad():
        plain = graph(**data)
        ex.require(
            torch.equal(plain.logits, result.logits) and torch.equal(plain.loss, result.loss),
            "Trace/no-trace bitwise canary",
        )
    del plain
    parts = torch.tensor([row["parts"]], dtype=torch.long, device=device)
    state = obj.state_gradient_audit(result, data["labels"], parts)
    trace = result.cut_trace
    dm, dq = torch.autograd.grad(result.loss, (trace.memory, trace.query), retain_graph=True)
    logits = upper_replay(graph, trace)
    ex.require(torch.equal(logits, result.logits), "Bitwise direct reader replay")
    direct = F.cross_entropy(
        logits[:, :-1].float().reshape(-1, logits.shape[-1]),
        data["labels"][:, 1:].reshape(-1),
        ignore_index=-100,
    )
    full = GradientSpill(graph.model.named_parameters())
    guard("canary_full_before")
    with full.capture():
        result.loss.backward(retain_graph=True)
    guard("canary_full_after")
    paths = GradientSpill(graph.model.named_parameters())
    visits = {}
    for name, value, grad in (("W", trace.memory, dm), ("Q", trace.query, dq), ("R", direct, None)):
        old = dict(paths.events)
        with paths.capture(require_all=False):
            torch.autograd.backward(value, grad, retain_graph=name == "W")
        visits[name] = sorted(n for n, v in paths.events.items() if v > old.get(n, 0))
        guard(f"canary_path_{name}")
    del result, trace, logits, direct, dm, dq
    rows = []
    for name, expected in full.buffers.items():
        stats = tensor_pair_stats(expected, paths.buffers.get(name))
        stats["within_frozen_numeric_bound"] = stats["max_abs_residual"] <= (
            plan["canary_path_atol"] + plan["canary_path_rtol"] * stats["left_max_abs"]
        )
        rows.append(dict(name=name, **stats))
    record = dict(
        key=row["key"],
        memory_tokens=len(row["memory_ids"]),
        query_tokens=len(row["input_ids"]),
        full=full.receipt(),
        paths=paths.receipt(),
        path_visits=visits,
        parameter_residuals=rows,
        state=state,
        pass_count=sum(r["within_frozen_numeric_bound"] for r in rows),
        parameter_count=len(rows),
        atol=plan["canary_path_atol"],
        rtol=plan["canary_path_rtol"],
        **ex.CEILING,
    )
    ex.write_new(output / "CANARY.json", record)
    ex.require(record["pass_count"] == len(rows), "7B W/Q/R sum numeric qualification")
    del full, paths
    gc.collect()
    torch.cuda.empty_cache()
    guard("canary_complete")
    return record


def base_role(core, args, plan, seal):
    import torch
    from safetensors.torch import save_file

    from latent_workspace.gradient_spill import GradientSpill

    data = inputs(plan)
    graph, tokenizer, guard, before = prepare(core, args, plan)
    row = sorted(
        data["worlds"], key=lambda r: (-len(r["memory_ids"]), -len(r["input_ids"]), r["key"])
    )[0]
    canary(graph, row, args.output, guard, plan)
    # Longest complete no-memory row is a separate resource sentinel, not a truncation.
    longest = sorted(data["preservation"], key=lambda r: (-len(r["input_ids"]), r["key"]))[0]
    output = graph(**batch(longest, "cuda"))
    bank = GradientSpill(graph.model.named_parameters())
    with bank.capture():
        output.loss.backward()
    ex.write_new(
        args.output / "PRESERVATION_CANARY.json",
        dict(key=longest["key"], tokens=len(longest["input_ids"]), spill=bank.receipt()),
    )
    del output, bank
    gc.collect()
    torch.cuda.empty_cache()
    guard("longest_preservation_canary_complete")
    tensors, index = {}, []
    with torch.no_grad():
        for i, row in enumerate(data["preservation"]):
            guard(f"teacher:{i}")
            values = batch(row, "cuda")
            output = graph(**values)
            active = values["labels"][:, 1:] != -100
            targets = output.logits[:, :-1][active].float().log_softmax(-1).cpu().contiguous()
            ex.require(
                targets.shape == (row["supervised_tokens"], plan["vocabulary"]), "Full targets"
            )
            tensors[str(i)] = targets
            index.append(
                dict(
                    index=str(i),
                    key=row["key"],
                    row_sha256=ex.plan_hash(row),
                    supervised_tokens=row["supervised_tokens"],
                    shape=list(targets.shape),
                )
            )
            del output, values, targets
    path = args.output / "PRIVATE_TEACHER_TARGETS.safetensors"
    ex.require(not path.exists(), "Fresh teacher targets")
    save_file(tensors, str(path))
    receipt = dict(
        native_sha256=before,
        source_commit=seal["source_commit"],
        input_sha256=plan["private_inputs_sha256"],
        rows=index,
        bytes=path.stat().st_size,
        sha256=ex.digest(path),
        tensor_bytes=sum(t.numel() * t.element_size() for t in tensors.values()),
        teacher_policy=plan["teacher_policy"],
        vocabulary=plan["vocabulary"],
        target_dtype=plan["teacher_target_dtype"],
        temperature=1.0,
    )
    ex.require(receipt["tensor_bytes"] == 122159104, "Frozen target byte budget")
    ex.write_new(args.output / "TEACHER_TARGETS.json", receipt)
    del tensors
    finish_model(graph, before, args.output)
    return dict(
        teacher_rows=12,
        target_positions=932,
        target_tensor_bytes=122159104,
        world_canary_rows=1,
        preservation_canary_rows=1,
        **ex.CEILING,
    )


def summarize_pairs(records):
    dot = sum(r["dot"] for r in records)
    aa, bb = (sum(r[key] for r in records) for key in ("left_sq", "right_sq"))
    return dict(
        dot=dot,
        left_l2=aa**0.5,
        right_l2=bb**0.5,
        cosine=dot / (aa * bb) ** 0.5 if aa and bb else None,
        negative_dot_tensors=sum(r["dot"] < 0 for r in records),
        parameter_tensors=len(records),
    )


def student_role(core, args, plan, seal):
    import torch
    from safetensors import safe_open
    from safetensors.torch import save_file

    from latent_workspace import objective_audit as obj
    from latent_workspace.gradient_spill import GradientSpill, tensor_pair_stats

    data = inputs(plan)
    reference = args.output.parent / "base"
    terminal = ex.read(reference / "FINISHED.json")
    ex.require(terminal["status"] == STATUS, "Completed canary/teacher prerequisite")
    actual = ex.manifest(reference)
    actual.pop("FINISHED.json")
    ex.require(actual == terminal["files"], "Frozen teacher role")
    targets = ex.read(reference / "TEACHER_TARGETS.json")
    target_path = reference / "PRIVATE_TEACHER_TARGETS.safetensors"
    ex.require(
        ex.digest(target_path) == targets["sha256"]
        and targets["input_sha256"] == plan["private_inputs_sha256"],
        "Exact targets",
    )
    graph, _, guard, before = prepare(core, args, plan)
    # Use the same predetermined maximum-memory canary at the actual student point.
    row = sorted(
        data["worlds"], key=lambda r: (-len(r["memory_ids"]), -len(r["input_ids"]), r["key"])
    )[0]
    canary(graph, row, args.output, guard, plan)
    references, summaries, scratch = {}, {}, []
    pden = sum(r["supervised_tokens"] for r in data["preservation"])
    wden = sum(r["supervised_tokens"] for r in data["worlds"])
    jobs = [("preservation", t) for t in plan["preservation_terms"]]
    jobs += [("worlds", t) for t in plan["world_terms"]]
    with safe_open(str(target_path), framework="pt", device="cpu") as teacher:
        for group, term in jobs:
            key = f"{group}_{term}"
            bank = GradientSpill(graph.model.named_parameters())
            denom = pden if group == "preservation" else wden
            value, skipped = 0.0, []
            with (args.output / f"{key}.jsonl").open("x") as stream:
                for i, row in enumerate(data[group]):
                    guard(f"{key}:{i}:before")
                    # An absent component is exactly zero; preserve its denominator/census.
                    if (
                        group == "worlds"
                        and term != "total"
                        and obj.PARTS.index(term) not in row["parts"]
                    ):
                        skipped.append(row["key"])
                        previous.append(stream, dict(key=row["key"], zero_component=True, loss=0.0))
                        continue
                    output = graph(
                        **batch(row, "cuda"),
                        capture_cut_trace=group == "worlds" and term == "total",
                    )
                    target = teacher.get_tensor(str(i)) if term == "kl" else None
                    loss = objective(output, row, term, denom, target)
                    info = dict(key=row["key"], loss=float(loss.detach()), denominator=denom)
                    if group == "worlds" and term == "total" and output.cut_trace is not None:
                        labels = torch.tensor([row["labels"]], device="cuda", dtype=torch.long)
                        parts = torch.tensor([row["parts"]], device="cuda", dtype=torch.long)
                        info["state"] = obj.state_gradient_audit(output, labels, parts)
                    with bank.capture():
                        loss.backward()
                    value += info["loss"]
                    previous.append(stream, info)
                    del output, loss, target
                    guard(f"{key}:{i}:after")
                    if (i + 1) % 12 == 0:
                        print(f"{key}: {i + 1}/{len(data[group])}", flush=True)
            receipt = bank.receipt()
            # No mixed tokens is explicit zero, not a missing or successful backward.
            norms = [dict(name=n, **tensor_pair_stats(v, None)) for n, v in bank.buffers.items()]
            summary = dict(
                loss=value,
                denominator=denom,
                rows=len(data[group]),
                zero_component_rows=skipped,
                spill=receipt,
                l2=sum(r["left_sq"] for r in norms) ** 0.5,
            )
            ex.write_new(args.output / f"{key}_NORMS.json", norms)
            if group == "preservation":
                path = args.output / f"SCRATCH_{term}.safetensors"
                ex.require(not path.exists(), "Exclusive temporary gradient sum")
                save_file(bank.buffers, str(path))
                references[term] = path
                scratch.append(
                    dict(path=str(path), bytes=path.stat().st_size, sha256=ex.digest(path))
                )
            else:
                for name, path in references.items():
                    records = []
                    with safe_open(str(path), framework="pt", device="cpu") as other:
                        for n in other.keys():
                            records.append(
                                dict(
                                    name=n,
                                    **tensor_pair_stats(bank.buffers.get(n), other.get_tensor(n)),
                                )
                            )
                    ex.write_new(args.output / f"{key}_VS_{name}.json", records)
                    summary[f"vs_{name}"] = summarize_pairs(records)
            summaries[key] = summary
            ex.write_new(args.output / f"{key}_SUMMARY.json", summary)
            del bank, norms
            gc.collect()
            torch.cuda.empty_cache()
            guard(f"{key}:complete")
    finish_model(graph, before, args.output)
    ex.write_new(
        args.output / "SCRATCH_RETIREMENT.json",
        dict(
            files=scratch,
            reason=(
                "Owned temporary gradient sums, not model weights; all scalar reductions recorded"
            ),
        ),
    )
    for entry in scratch:
        path = Path(entry["path"])
        ex.require(
            path.parent == args.output
            and not path.is_symlink()
            and ex.digest(path) == entry["sha256"],
            "Exact temporary body",
        )
        path.unlink()
    ex.write_new(
        args.output / "SCRATCH_RETIRED.json",
        dict(files=len(scratch), bytes=sum(r["bytes"] for r in scratch)),
    )
    outcome = dict(
        world_rows=84,
        world_groups=14,
        preservation_rows=12,
        world_supervised_tokens=wden,
        preservation_supervised_tokens=pden,
        summaries=summaries,
        checkpoint_saves=0,
        path_scope=plan["path_scope"],
        **ex.CEILING,
    )
    ex.write_new(args.output / "AUDIT.json", outcome)
    return outcome


RUN = ex.SealedRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass="TINY_V23_GRADIENT_SPILL_PASS_NOT_7B",
    roles=("base", "v22"),
    role_status={"base": STATUS, "v22": STATUS},
    validate=validate,
    load=common.load,
)

if __name__ == "__main__":
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    os.environ["LTWS_CPU_SDPA_BACKEND"] = "math"
    raise SystemExit(
        RUN.main(
            {"base": base_role, "v22": student_role},
            lambda out, plan: ex.read(out / "v22/AUDIT.json"),
        )
    )
