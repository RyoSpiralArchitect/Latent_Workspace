#!/usr/bin/env python3
"""Frozen prefix-causality qualification, content ablations and writer factorial."""

from __future__ import annotations

import gc
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import run_native_7b_canary as common  # noqa: E402
import run_v22_comparison as previous  # noqa: E402
import run_v22_diagnostics as prior_diag  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402

PLAN = "configs/v22/MEMORY_CAUSALITY_01.json"
ENTRY = "scripts/run_v22_causality.py"
ROLES = ("base", "v22", "base_cross")
STATUS = "V22_CAUSALITY_ARM_COMPLETE"


def validate(plan):
    ex.require(plan["schema"] == "ltws-v22-memory-causality-01" and plan["no_retry"], "Plan")
    ex.require(
        ex.digest(ROOT / plan["comparison_plan"]) == plan["comparison_plan_sha256"], "Prior plan"
    )
    ex.require(plan["conditions"] == ["identity", "empty", "zero", "reverse", "twin"], "Conditions")
    ex.require(
        plan["generation"]
        == dict(seed=20261021, max_new_tokens=24, temperature=0, top_p=1),
        "Frozen full-vocabulary generation policy",
    )
    ex.require(
        plan["planned"]
        == dict(
            original_world_rows=96,
            nonempty_rows=80,
            twin_directed_rows=64,
            prefix_positions=2492,
            new_sequences=928,
            native_weight_updates=0,
            checkpoint_saves=0,
            judge_calls=0,
            weight_deletions=0,
        ),
        "Finite scope",
    )


def twins(rows):
    result = {}
    for row in rows:
        if row["mode"] not in ("affected", "unaffected"):
            continue
        candidates = [
            r
            for r in rows
            if r["group_id"] == row["group_id"]
            and r["mode"] == row["mode"]
            and r["side"] != row["side"]
        ]
        ex.require(len(candidates) == 1, "Unique reciprocal twin")
        donor = candidates[0]
        ex.require(row["prefixes"]["latent"] == donor["prefixes"]["latent"], "Identical query")
        ex.require(bool(row["memory_ids"] and donor["memory_ids"]), "Live twin memory")
        ex.require(
            (row["answer_ids"] != donor["answer_ids"]) == (row["mode"] == "affected"),
            "Oracle direction/control",
        )
        result[row["row_id"]] = donor
    return result


def instrument(graph, rows, output, guard):
    import torch

    from latent_workspace import native_causality as ca
    from latent_workspace import native_diagnostics as diag
    from latent_workspace import native_evaluation as ev

    device = next(graph.parameters()).device
    count, disagreements = 0, 0
    with (output / "prefix.jsonl").open("x") as stream, torch.no_grad():
        for row in rows:
            for route in ("latent", "inline"):
                memory = row["memory_ids"] if route == "latent" else []
                prefix, gold = row["prefixes"][route], row["answer_ids"]
                guard("prefix:full")
                full = graph(**ev.tensor_batch(prefix + gold, memory, device)).logits
                for index, token in enumerate(gold):
                    pos = len(prefix) + index - 1
                    reference = full[0, pos]
                    record = dict(
                        id=row["row_id"],
                        route=route,
                        index=index,
                        target=token,
                        position=pos,
                        full_extent=len(prefix) + len(gold),
                        full=diag.token_score(reference, token),
                        full_sha256=ca.tensor_digest(reference),
                        variants={},
                    )
                    for name, batch in ca.prefix_variants(
                        prefix, gold, index, memory, device, graph.host.head.out_features
                    ).items():
                        guard(f"prefix:{name}:{count}")
                        changed = graph(**batch).logits[0, pos]
                        delta = ca.difference(reference, changed)
                        record["variants"][name] = dict(
                            score=diag.token_score(changed, token),
                            delta=delta,
                            sha256=ca.tensor_digest(changed),
                        )
                        if name == "changed_future" and not delta["exact"]:
                            disagreements += 1
                        del changed
                    previous.append(stream, record)
                    count += 1
                del full
            print(f"prefix {row['row_id']} positions={count}", flush=True)
    receipt = dict(
        positions=count,
        fixed_extent_future_disagreements=disagreements,
        gate="PASS" if disagreements == 0 else "FAIL",
    )
    ex.write_new(output / "PREFIX_GATE.json", receipt)
    ex.require(disagreements == 0, "Fixed-extent future content affects earlier logits; STOP")
    return count


def encode_bank(graph, rows, output, guard):
    import torch
    from safetensors.torch import save_file

    from latent_workspace import native_causality as ca
    from latent_workspace import native_evaluation as ev

    bank, index = {}, {}
    device = next(graph.parameters()).device
    with torch.no_grad():
        for row in rows:
            if not row["memory_ids"]:
                continue
            key = ex.plan_hash(row["memory_ids"])
            if key not in bank:
                guard("encode-bank")
                batch = ev.tensor_batch([1], row["memory_ids"], device)
                value = graph.host.to_cut(batch["memory_ids"], batch["memory_mask"], graph.cut)
                bank[key] = value.detach().cpu().contiguous()
            index[row["row_id"]] = dict(
                key=key, shape=list(bank[key].shape), sha256=ca.tensor_digest(bank[key])
            )
    path = output / "memory_states.safetensors"
    ex.require(not path.exists(), "Exclusive activation bank")
    save_file(bank, str(path))
    ex.write_new(
        output / "MEMORY_BANK.json",
        dict(rows=index, tensors=len(bank), file_sha256=ex.digest(path)),
    )
    return bank, index


def foreign_bank(folder):
    from safetensors.torch import load_file

    from latent_workspace.native_causality import tensor_digest

    terminal = ex.read(folder / "FINISHED.json")
    files = ex.manifest(folder)
    files.pop("FINISHED.json")
    ex.require(terminal["status"] == STATUS and terminal["files"] == files, "Foreign writer seal")
    receipt = ex.read(folder / "MEMORY_BANK.json")
    path = folder / "memory_states.safetensors"
    ex.require(ex.digest(path) == receipt["file_sha256"], "Foreign activation body")
    bank = load_file(str(path), device="cpu")
    for entry in receipt["rows"].values():
        value = bank[entry["key"]]
        ex.require(
            list(value.shape) == entry["shape"] and tensor_digest(value) == entry["sha256"],
            "Foreign tensor identity",
        )
    return bank, receipt["rows"]


def causal_rows(
    graph, tokenizer, rows, twin, prior, bank, index, foreign, output, guard, plan, cross_only=False
):
    import torch

    from latent_workspace import native_causality as ca
    from latent_workspace import native_diagnostics as diag
    from latent_workspace import native_evaluation as ev

    device = next(graph.parameters()).device
    count = generated = 0
    with (output / "interventions.jsonl").open("x") as stream, torch.no_grad():
        for row in rows:
            if not row["memory_ids"]:
                continue
            donor = twin.get(row["row_id"])
            conditions = ["foreign_writer"] if cross_only else list(plan["conditions"])
            if foreign is not None and not cross_only:
                conditions.append("foreign_writer")
            for condition in conditions:
                if condition == "twin" and donor is None:
                    continue
                memory = (
                    []
                    if condition == "empty"
                    else (donor["memory_ids"] if condition == "twin" else row["memory_ids"])
                )
                replacement = None
                if condition == "twin":
                    replacement = bank[index[donor["row_id"]]["key"]].to(device)
                elif condition == "foreign_writer":
                    fb, fi = foreign
                    ex.require(
                        fi[row["row_id"]]["key"] == index[row["row_id"]]["key"],
                        "Cross-writer identical memory tokens",
                    )
                    replacement = fb[fi[row["row_id"]]["key"]].to(device)
                probe = (
                    graph
                    if condition == "empty"
                    else ca.MemoryProbe(
                        graph,
                        mode="replacement" if replacement is not None else condition,
                        replacement=replacement,
                    )
                )
                # Gold/donor common prefix is specified by the oracle, never by generation.
                fork = (
                    diag.first_difference(row["answer_ids"], donor["answer_ids"]) if donor else None
                )
                j = 0 if fork is None else fork
                prefix = row["prefixes"]["latent"]
                batch = ev.tensor_batch(prefix + row["answer_ids"][:j], memory, device)
                guard("intervention:decision")
                logits = probe(**batch).logits
                if condition == "identity":
                    original = graph(**batch).logits
                    ex.require(torch.equal(logits, original), "Exact no-op state-path parity")
                    del original
                decision = dict(
                    index=j, original=diag.token_score(logits[0, -1], row["answer_ids"][j])
                )
                if donor and fork is not None:
                    a, b = row["answer_ids"][j], donor["answer_ids"][j]
                    decision.update(
                        donor=diag.token_score(logits[0, -1], b),
                        donor_minus_original=float(
                            logits[0, -1, b].float() - logits[0, -1, a].float()
                        ),
                    )
                del logits
                policy = plan["generation"]
                result = ev.generate(
                    probe,
                    prefix,
                    memory,
                    seed=policy["seed"],
                    cap=policy["max_new_tokens"],
                    eos=2,
                    temperature=0,
                    top_p=1,
                    guard=guard,
                )
                text = tokenizer.decode(result["token_ids"], skip_special_tokens=True)
                replay_id = (
                    row["row_id"]
                    if condition == "identity"
                    else (donor["row_id"] if condition == "twin" else None)
                )
                if replay_id:
                    ex.require(
                        result["token_ids"] == prior[replay_id]["token_ids"],
                        "Exact identity/twin historical generation replay",
                    )
                previous.append(
                    stream,
                    dict(
                        id=row["row_id"],
                        group_id=row["group_id"],
                        family=row["family"],
                        split=row["split"],
                        side=row["side"],
                        mode=row["mode"],
                        condition=condition,
                        donor_id=None if donor is None else donor["row_id"],
                        memory_tokens=len(memory),
                        original_memory_tokens=len(row["memory_ids"]),
                        target=row["answer"],
                        donor_target=None if donor is None else donor["answer"],
                        text=text,
                        exact_match=ev.normalized_answer(text)
                        == ev.normalized_answer(row["answer"]),
                        donor_match=None
                        if donor is None
                        else ev.normalized_answer(text) == ev.normalized_answer(donor["answer"]),
                        abstained=ev.normalized_answer(text) == "not specified",
                        decision=decision,
                        historical_replay_id=replay_id,
                        **result,
                    ),
                )
                count += 1
                generated += result["generated_tokens"]
                del probe, replacement
            print(f"interventions {row['row_id']} sequences={count}", flush=True)
    return count, generated


def run(core, args, plan, seal):
    import torch

    from latent_workspace.optimizer_state import tree_hash

    old, data, receipt, _ = prior_diag.load_inputs(plan)
    rows = data["worlds"]
    ex.write_new(args.output / "INPUT_MANIFEST.json", receipt)
    twin = twins(rows)
    graph, tokenizer, guard, before = previous.prepare(core, args, {**old, **plan})
    cross = args.role == "base_cross"
    positions = 0 if cross else instrument(graph, rows, args.output, guard)
    bank, index = encode_bank(graph, rows, args.output, guard)
    if cross:
        base = args.output.parent / "base"
        ex.require(index == ex.read(base / "MEMORY_BANK.json")["rows"], "Base writer reload parity")
        ex.require(before == ex.read(base / "WEIGHT_IDENTITY.json")["before"], "Base reader reload")
    foreign = (
        None
        if args.role == "base"
        else foreign_bank(args.output.parent / ("v22" if cross else "base"))
    )
    prior = {
        r["id"]: r
        for r in prior_diag.journal(
            Path(plan["comparison_bundle"])
            / "raw"
            / ("base" if cross else args.role)
            / "worlds.jsonl"
        )
        if r["route"] == "latent"
    }
    sequences, tokens = causal_rows(
        graph,
        tokenizer,
        rows,
        twin,
        prior,
        bank,
        index,
        foreign,
        args.output,
        guard,
        plan,
        cross_only=cross,
    )
    del bank, foreign
    gc.collect()
    torch.cuda.empty_cache()
    after = tree_hash(graph.model.state_dict())
    ex.require(before == after, "Interventions mutated native weights")
    ex.write_new(args.output / "WEIGHT_IDENTITY.json", dict(before=before, after=after, equal=True))
    guard("complete")
    return dict(
        prefix_positions=positions,
        new_sequences=sequences,
        generated_tokens=tokens,
        native_weight_updates=0,
        checkpoint_saves=0,
        engine_imports=common.engine_imports(seal),
        **common.peak(),
    )


def summary(folder, plan):
    ends = [ex.read(folder / r / "FINISHED.json")["outcome"] for r in ROLES]
    result = {
        k: sum(e[k] for e in ends)
        for k in ("prefix_positions", "new_sequences", "generated_tokens")
    }
    for k in ("prefix_positions", "new_sequences"):
        ex.require(result[k] == plan["planned"][k], f"Causal denominator {k}")
    return dict(**result, native_weight_updates=0, checkpoint_saves=0)


RUN = previous.EvaluationRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass="TINY_V22_CAUSALITY_PASS_NOT_7B",
    roles=ROLES,
    role_status={r: STATUS for r in ROLES},
    validate=validate,
    load=common.load,
)

if __name__ == "__main__":
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    os.environ["LTWS_CPU_SDPA_BACKEND"] = "math"
    raise SystemExit(RUN.main({r: run for r in ROLES}, summary))
