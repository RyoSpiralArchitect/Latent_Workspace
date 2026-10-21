#!/usr/bin/env python3
"""Finite W x Q x R diagnosis of frozen V22; zero training/generation/judges."""

from __future__ import annotations

import gc
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import run_native_7b_canary as common  # noqa: E402
import run_v22_causality as causal  # noqa: E402
import run_v22_comparison as previous  # noqa: E402
import run_v22_diagnostics as prior_diag  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402

PLAN = "configs/v23/STATE_FACTORIAL_01.json"
ENTRY = "scripts/run_v23_state_factorial.py"
ROLES = ("base", "v22", "base_cross")
STATUS = "V23_STATE_FACTORIAL_ARM_COMPLETE"


def validate(plan):
    ex.require(plan["schema"] == "ltws-v23-state-factorial-01" and plan["no_retry"], "Plan")
    ex.require(
        ex.digest(ROOT / plan["comparison_plan"]) == plan["comparison_plan_sha256"], "Prior plan"
    )
    ex.require(
        plan["planned"]
        == dict(
            world_rows=96,
            world_positions=623,
            nonempty_positions=559,
            world_cells=4728,
            mmlu_rows=570,
            mmlu_cells=2280,
            recorded_world_cells=5351,
            recorded_mmlu_cells=2850,
            new_sequences=0,
            native_weight_updates=0,
            checkpoint_saves=0,
            judge_calls=0,
            weight_deletions=0,
        ),
        "Finite factorial scope",
    )
    ex.require(plan["prefix_policy"] == "cropped_identical_gold_prefix_no_future", "Prefix extent")


def cases(data):
    """Every exposed world gold position and all 570 exposed benchmark rows."""
    twin = causal.twins(data["worlds"])
    for row in data["worlds"]:
        other = twin.get(row["row_id"])
        divergence = None
        # The donor target is read only at the common oracle-prefix boundary.
        if other is not None and row["mode"] == "affected":
            divergence = next(
                i for i, (a, b) in enumerate(zip(row["answer_ids"], other["answer_ids"])) if a != b
            )
        for j, token in enumerate(row["answer_ids"]):
            yield dict(
                kind="world",
                id=row["row_id"],
                index=j,
                target=token,
                query=row["prefixes"]["latent"] + row["answer_ids"][:j],
                memory=row["memory_ids"],
                family=row["family"],
                mode=row["mode"],
                group_id=row["group_id"],
                side=row["side"],
                split=row["split"],
                donor_token=other["answer_ids"][j] if j == divergence else None,
                donor_id=None if other is None else other["row_id"],
            )
    for row in data["mmlu"]:
        yield dict(
            kind="mmlu",
            id=row["id"],
            index=0,
            target=row["target"],
            query=row["input_ids"],
            memory=[],
            choice_ids=row["choice_ids"],
            subject=row["subject"],
        )


def bank_inputs(items):
    inputs = {}
    for item in items:
        for tokens in (item["query"], item["memory"]):
            if tokens:
                key = ex.plan_hash(tokens)
                ex.require(key not in inputs or inputs[key] == tokens, "Token hash collision")
                inputs[key] = tokens
    return inputs


def encode_bank(graph, items, output, guard):
    import torch
    from safetensors.torch import save_file

    from latent_workspace.native_causality import tensor_digest

    device = next(graph.parameters()).device
    tensors, index = {}, {}
    inputs = bank_inputs(items)
    path = output / "cut_states.safetensors"
    ex.require(not path.exists() and not (output / "CUT_BANK.json").exists(), "Exclusive cut bank")
    with torch.no_grad():
        for i, (key, tokens) in enumerate(inputs.items()):
            guard(f"encode:{i}")
            ids = torch.tensor([tokens], dtype=torch.long, device=device)
            value = (
                graph.host.to_cut(ids, torch.ones_like(ids), graph.cut).detach().cpu().contiguous()
            )
            tensors[key] = value
            index[key] = dict(
                tokens=len(tokens),
                shape=list(value.shape),
                dtype=str(value.dtype),
                sha256=tensor_digest(value),
            )
            if (i + 1) % 200 == 0:
                print(f"bank {i + 1}/{len(inputs)}", flush=True)
    save_file(tensors, str(path))
    receipt = dict(
        schema="ltws-fixed-prefix-cut-bank-v1",
        tensors=index,
        cut=graph.cut,
        bytes=path.stat().st_size,
        sha256=ex.digest(path),
        token_inputs_sha256=ex.plan_hash(inputs),
        tensor_bytes=sum(t.numel() * t.element_size() for t in tensors.values()),
    )
    ex.write_new(output / "CUT_BANK.json", receipt)
    del tensors
    gc.collect()
    return receipt


def verify_bank(folder, items, *, terminal=True):
    from safetensors import safe_open

    from latent_workspace.native_causality import tensor_digest

    if terminal:
        end = ex.read(folder / "FINISHED.json")
        actual = ex.manifest(folder)
        actual.pop("FINISHED.json")
        ex.require(end["status"] == STATUS and end["files"] == actual, "Complete bank role seal")
    receipt = ex.read(folder / "CUT_BANK.json")
    path = folder / "cut_states.safetensors"
    ex.require(
        path.stat().st_size == receipt["bytes"] and ex.digest(path) == receipt["sha256"],
        "Cut bank bytes",
    )
    inputs = bank_inputs(items)
    ex.require(
        receipt["token_inputs_sha256"] == ex.plan_hash(inputs), "Exact cut bank token inputs"
    )
    with safe_open(path, framework="pt", device="cpu") as handle:
        ex.require(
            set(handle.keys()) == set(inputs) == set(receipt["tensors"]), "Cut bank coverage"
        )
        for key, entry in receipt["tensors"].items():
            value = handle.get_tensor(key)
            ex.require(
                list(value.shape) == entry["shape"]
                and str(value.dtype) == entry["dtype"]
                and tensor_digest(value) == entry["sha256"],
                "Cut tensor identity",
            )
    return receipt


def historical(plan, role):
    """Original cropped-prefix hashes, and original MMLU choice scores."""
    name = "base" if role == "base_cross" else role
    root = ROOT / "provenance/pilots/v22_memory_causality01_20261021/furnace/raw" / name
    # These tracked bytes are included indirectly by their explicit frozen hash.
    prefix = root / "prefix.jsonl"
    ex.require(
        ex.digest(prefix) == plan["historical_prefix_sha256"][name], "Historical prefix journal"
    )
    world = {
        (r["id"], r["index"]): r["variants"]["cropped"]["sha256"]
        for r in prior_diag.journal(prefix)
        if r["route"] == "latent"
    }
    mmlu = {
        r["id"]: r
        for r in prior_diag.journal(Path(plan["comparison_bundle"]) / "raw" / name / "mmlu.jsonl")
    }
    return world, mmlu


def score_cells(graph, items, handles, reader, output, guard, history, replay=None):
    import torch

    from latent_workspace import native_diagnostics as diag
    from latent_workspace import native_evaluation as ev
    from latent_workspace.native_causality import tensor_digest
    from latent_workspace.state_factorial import cut_state_logits

    device = next(graph.parameters()).device
    counts = dict(world_cells=0, mmlu_cells=0, full_self_parity=0, repeated_self_parity=0)
    with (output / "cells.jsonl").open("x") as stream, torch.no_grad():
        for n, item in enumerate(items):
            states = {
                label: handle.get_tensor(ex.plan_hash(item["query"])).to(device)
                for label, handle in handles.items()
            }
            memories = (
                {
                    label: handle.get_tensor(ex.plan_hash(item["memory"])).to(device)
                    for label, handle in handles.items()
                }
                if item["memory"]
                else {"none": None}
            )
            for writer, memory in memories.items():
                for query_encoder, query in states.items():
                    guard(f"{item['kind']}:{n}:{writer}:{query_encoder}")
                    logits = cut_state_logits(graph, query, memory)
                    last = logits[0, -1]
                    sha = tensor_digest(last)
                    self_cell = query_encoder == reader and writer in (reader, "none")
                    if self_cell:
                        if replay is None:
                            native = graph(
                                **ev.tensor_batch(item["query"], item["memory"], device)
                            ).logits
                            ex.require(
                                torch.equal(logits, native),
                                "Exact full-logit native/split self parity",
                            )
                            counts["full_self_parity"] += 1
                            del native
                        else:
                            key = (item["kind"], item["id"], item["index"])
                            ex.require(sha == replay[key], "Exact repeated base self cell")
                            counts["repeated_self_parity"] += 1
                    if item["kind"] == "world":
                        score = diag.token_score(last, item["target"])
                        if item["donor_token"] is not None:
                            score["donor_minus_original"] = float(
                                last[item["donor_token"]].float() - last[item["target"]].float()
                            )
                        if self_cell:
                            ex.require(
                                sha == history[0][(item["id"], item["index"])],
                                "Historical cropped full-vocabulary replay",
                            )
                    else:
                        score = ev.score_choices(last, item["choice_ids"], item["target"])
                        if self_cell:
                            ex.require(
                                score == {k: history[1][item["id"]][k] for k in score},
                                "Historical MMLU replay",
                            )
                    record = {
                        k: v for k, v in item.items() if k not in ("query", "memory", "choice_ids")
                    }
                    record.update(
                        writer=writer,
                        query_encoder=query_encoder,
                        reader=reader,
                        query_key=ex.plan_hash(item["query"]),
                        memory_key=ex.plan_hash(item["memory"]) if item["memory"] else None,
                        query_tokens=len(item["query"]),
                        memory_tokens=len(item["memory"]),
                        logits_sha256=sha,
                        score=score,
                        self_cell=self_cell,
                    )
                    previous.append(stream, record)
                    counts[f"{item['kind']}_cells"] += 1
                    del logits, last
            if (n + 1) % 100 == 0:
                print(f"factorial {n + 1}/{len(items)} {counts}", flush=True)
    return counts


def run(core, args, plan, seal):
    from contextlib import ExitStack

    import torch
    from safetensors import safe_open

    from latent_workspace.optimizer_state import tree_hash

    old, data, receipt, _ = prior_diag.load_inputs(plan)
    items = list(cases(data))
    ex.write_new(args.output / "INPUT_MANIFEST.json", receipt)
    graph, _, guard, before = previous.prepare(core, args, {**old, **plan})
    cross = args.role == "base_cross"
    reader = "base" if cross else args.role
    if not cross:
        encode_bank(graph, items, args.output, guard)
    names = ("base",) if args.role == "base" else ("base", "v22")
    receipts = {}
    for name in names:
        receipts[name] = verify_bank(args.output.parent / name, items, terminal=name != args.role)
        ex.require(receipts[name]["cut"] == graph.cut, "Bank cut matches reader")
    ex.write_new(args.output / "BANK_INPUTS.json", receipts)
    replay = None
    if cross:
        ex.require(
            before == ex.read(args.output.parent / "base/WEIGHT_IDENTITY.json")["before"],
            "Reloaded base identity",
        )
        replay = {
            (r["kind"], r["id"], r["index"]): r["logits_sha256"]
            for r in prior_diag.journal(args.output.parent / "base/cells.jsonl")
        }
    with ExitStack() as stack:
        handles = {
            name: stack.enter_context(
                safe_open(
                    args.output.parent / name / "cut_states.safetensors",
                    framework="pt",
                    device="cpu",
                )
            )
            for name in names
        }
        counts = score_cells(
            graph, items, handles, reader, args.output, guard, historical(plan, args.role), replay
        )
    gc.collect()
    torch.cuda.empty_cache()
    after = tree_hash(graph.model.state_dict())
    ex.require(before == after, "State factorial mutated model")
    ex.write_new(args.output / "WEIGHT_IDENTITY.json", dict(before=before, after=after, equal=True))
    guard("complete")
    return dict(
        **counts,
        new_sequences=0,
        native_weight_updates=0,
        checkpoint_saves=0,
        engine_imports=common.engine_imports(seal),
        **common.peak(),
    )


def summary(folder, plan):
    ends = [ex.read(folder / r / "FINISHED.json")["outcome"] for r in ROLES]
    result = {
        k: sum(e[k] for e in ends)
        for k in ("world_cells", "mmlu_cells", "full_self_parity", "repeated_self_parity")
    }
    for kind in ("world", "mmlu"):
        ex.require(
            result[f"{kind}_cells"] == plan["planned"][f"recorded_{kind}_cells"],
            f"Recorded {kind} denominator",
        )
    ex.require(
        result["full_self_parity"] == 2386 and result["repeated_self_parity"] == 1193,
        "Complete parity coverage",
    )
    return dict(**result, new_sequences=0, native_weight_updates=0, checkpoint_saves=0)


RUN = ex.SealedRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass="TINY_V23_STATE_FACTORIAL_PASS_NOT_7B",
    roles=ROLES,
    role_status={r: STATUS for r in ROLES},
    validate=validate,
    load=common.load,
)

if __name__ == "__main__":
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    os.environ["LTWS_CPU_SDPA_BACKEND"] = "math"
    raise SystemExit(RUN.main({r: run for r in ROLES}, summary))
