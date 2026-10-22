#!/usr/bin/env python3
"""One native MMLU-Pro evaluation; strict original v1/v2 restore, no retries."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import run_v23_comparison as previous  # noqa: E402
import v23_mmlu_pro as data_module  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402
from latent_workspace import native_evaluation as ev  # noqa: E402

ENTRY = "scripts/run_v23_mmlu_pro.py"
PLAN = data_module.PLAN
ROLES = ("base", "off", "on")


def runtime_plan(plan):
    parent = ex.read(ROOT / plan["reference_comparison_plan"])
    ex.require(
        ex.plan_hash(parent) == plan["reference_comparison_plan_sha256"], "Pinned owner loader"
    )
    previous.validate(parent)
    return dict(parent, **plan)


def validate(plan):
    parent = runtime_plan(plan)
    ex.require(plan["schema"] == "ltws-v23-mmlu-pro-01" and plan["no_retry"], "Plan")
    ex.require(
        plan["roles"] == list(ROLES)
        and plan["per_category"] == 20
        and plan["generation_per_category"] == 2
        and plan["shots"] == 5,
        "Frozen sampling",
    )
    ex.require(
        plan["planned"]
        == dict(
            arms=3,
            direct_scores=840,
            reasoning_sequences=84,
            native_weight_updates=0,
            checkpoint_saves=0,
            judge_calls=0,
            weight_deletions=0,
        ),
        "Scope",
    )
    ex.require(
        parent["resources"] == previous.reference(parent)["resources"], "Same resource limits"
    )
    data_module.load_panel(plan)


def inputs(plan):
    folder = Path(plan["input_bundle"])
    receipt = ex.read(folder / "MANIFEST.json")
    files = ex.manifest(folder)
    files.pop("MANIFEST.json")
    ex.require(
        files == receipt["files"] and receipt["plan_sha256"] == ex.plan_hash(plan), "Input seal"
    )
    for n, digest in receipt["source"].items():
        ex.require(ex.digest(ROOT / n) == digest, "Input implementation")
    _, panel_manifest = data_module.load_panel(plan)
    ex.require(receipt["panel_manifest"] == panel_manifest, "Pinned selected IDs")
    data = ex.read_gz(folder / "INPUTS.json.gz")
    ex.require(
        data["plan_sha256"] == ex.plan_hash(plan)
        and len(data["rows"]) == 280
        and len(data["generation_ids"]) == 28,
        "Complete panel",
    )
    return data, receipt


def predecessor(plan):
    folder = Path(plan["predecessor_bundle"])
    seal = ex.read(folder / "SOURCE_SEAL.json")
    end = ex.read(folder / "raw/FINISHED.json")
    ex.require(
        seal["source_commit"] == plan["predecessor_source"]
        and end["status"] == "V23_BASE_OFF_ON_COMPARISON_COMPLETE_NOT_RELEASE",
        "Prior comparison must finish successfully first",
    )
    files = ex.manifest(folder / "raw")
    files.pop("FINISHED.json")
    ex.require(files == end["files"], "Prior comparison bytes")
    return dict(
        terminal_sha256=ex.digest(folder / "raw/FINISHED.json"), source=seal["source_commit"]
    )


def run(core, args, plan, seal, *, predecessor_fn=None, generation_fn=None):
    from latent_workspace.optimizer_state import tree_hash

    parent = runtime_plan(plan)
    # The original default still requires the original successful dispatcher.
    # A separately sealed follow-up may supply an explicit dual-origin receipt.
    receipt_fn = predecessor if predecessor_fn is None else predecessor_fn
    ex.write_new(args.output / "PREDECESSOR.json", receipt_fn(plan))
    data, receipt = inputs(plan)
    ex.write_new(args.output / "INPUT_MANIFEST.json", receipt)
    graph, tokenizer, guard, before = previous.prepare(core, args, parent)
    import torch

    device = next(graph.parameters()).device
    with torch.no_grad():
        for row in data["rows"][:2]:
            batch = ev.tensor_batch(row["input_ids"][:32], [], device)
            a, b = graph(**batch).logits, graph.model(**batch, use_cache=False).logits
            ex.require(torch.equal(a, b), "Empty-memory bypass parity")
            del a, b
    ex.write_new(args.output / "PARITY.json", dict(bitwise_equal=True, fixed_prefixes=2, tokens=32))
    with (args.output / "direct.jsonl").open("x") as stream, torch.no_grad():
        for i, row in enumerate(data["rows"]):
            guard(f"direct:{i}")
            output = graph(**ev.tensor_batch(row["input_ids"], [], device))
            score = ev.score_choices(output.logits[0, -1], row["choice_ids"], row["target"])
            gold = score["logits"][row["target"]]
            margin = gold - max(v for j, v in enumerate(score["logits"]) if j != row["target"])
            previous.previous.append(
                stream,
                dict(
                    id=row["id"],
                    category=row["category"],
                    prompt_tokens=len(row["input_ids"]),
                    option_count=len(row["choice_ids"]),
                    gold_margin=margin,
                    **score,
                ),
            )
            del output
            if (i + 1) % 20 == 0:
                print(f"{args.role}: MMLU-Pro direct {i + 1}/280", flush=True)
    count, tokens = 0, 0
    policy = plan["generation"]
    with (args.output / "reasoning.jsonl").open("x") as stream:
        for row in data["rows"]:
            if row["id"] not in data["generation_ids"]:
                continue
            result = (ev.generate if generation_fn is None else generation_fn)(
                graph,
                row["reasoning_ids"],
                [],
                seed=policy["seed"],
                cap=policy["max_new_tokens"],
                eos=2,
                temperature=policy["temperature"],
                top_p=policy["top_p"],
                guard=guard,
            )
            text = tokenizer.decode(result["token_ids"], skip_special_tokens=True)
            parsed = data_module.extract(text, len(row["options"]))
            correct = parsed["parsed"] and parsed["prediction"] == row["target"]
            previous.previous.append(
                stream,
                dict(
                    id=row["id"],
                    category=row["category"],
                    target=row["target"],
                    text=text,
                    prompt_tokens=len(row["reasoning_ids"]),
                    correct=correct,
                    completed_correct=correct and result["stop_reason"] == "eos",
                    **parsed,
                    **result,
                ),
            )
            count += 1
            tokens += result["generated_tokens"]
            print(f"{args.role}: MMLU-Pro reasoning {count}/28", flush=True)
    ex.require(count == 28, "Generation denominator")
    after = tree_hash(graph.model.state_dict())
    ex.require(after == before, "Read-only native identity")
    ex.write_new(args.output / "WEIGHT_IDENTITY.json", dict(before=before, after=after, equal=True))
    guard("complete")
    return dict(
        new_sequences=count,
        generated_tokens=tokens,
        direct_rows=280,
        native_weight_updates=0,
        checkpoint_saves=0,
        engine_imports=previous.common.engine_imports(seal),
        **previous.common.peak(),
    )


def summary(folder, plan):
    ends = [ex.read(folder / role / "FINISHED.json")["outcome"] for role in ROLES]
    ex.require(all(e["direct_rows"] == 280 and e["new_sequences"] == 28 for e in ends), "All arms")
    return dict(
        new_sequences=84,
        direct_rows=840,
        native_weight_updates=0,
        checkpoint_saves=0,
        generated_tokens=sum(e["generated_tokens"] for e in ends),
        completed_arms=list(ROLES),
    )


RUN = previous.previous.EvaluationRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass="TINY_V23_MMLU_PRO_PASS_NOT_7B",
    roles=ROLES,
    role_status={r: "V23_MMLU_PRO_ARM_COMPLETE" for r in ROLES},
    validate=validate,
    load=previous.common.load,
)

if __name__ == "__main__":
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    os.environ["LTWS_CPU_SDPA_BACKEND"] = "math"
    raise SystemExit(RUN.main({r: run for r in ROLES}, summary))
