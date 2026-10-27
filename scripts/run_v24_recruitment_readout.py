#!/usr/bin/env python3
"""Bounded crossed-route readout on unused dev groups, with no training/retry."""

from __future__ import annotations

import gc
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
from qualification_isolation import isolate_cli_before_imports  # noqa: E402

isolate_cli_before_imports()
import run_native_7b_canary as common  # noqa: E402
import run_v22_comparison as evaluation  # noqa: E402
import run_v23_comparison as restoration  # noqa: E402
from qualification_isolation_v2 import IsolatedQualificationMixin  # noqa: E402
from v23_generation_cache import GenerationBoundaryGuard  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402
from latent_workspace import native_evaluation as ev  # noqa: E402
from latent_workspace import readout_audit as audit  # noqa: E402
from latent_workspace import recruitment_readout as meter  # noqa: E402

ENTRY = "scripts/run_v24_recruitment_readout.py"
PLAN = "configs/v24/RECRUITMENT_READOUT_01.json"
INPUT_DIR = "configs/v24/recruitment_readout01"
BANK = "provenance/engineering/v24_recruitment_preparation01_20261023/furnace/raw/data/bank"
HISTORY = "provenance/engineering/v24_recruitment_ft04_20261023/furnace"
TRAIN_SOURCE = "4b69c6b0d604f4947b7075e40430b9b8f113f4ad"
ROLES = ("base", "inline", "workspace")


def make_inputs(tokenizer, plan):
    folder = ROOT / BANK
    manifest = ex.read(folder / "MANIFEST.json")
    for name in ("PUBLIC_SYNTHETIC.json.gz", "SCHEDULE.json"):
        ex.require(
            ex.digest(folder / name) == manifest["files"][name]["sha256"], "Original bank bytes"
        )
    for path, sha in manifest["source"].items():
        ex.require(ex.digest(ROOT / path) == sha, "Original data source unchanged")
    selection = meter.select_development(
        ex.read_gz(folder / "PUBLIC_SYNTHETIC.json.gz"),
        seed=plan["selection_seed"],
        groups_per_family=plan["groups_per_family"],
        exposed_keys=ex.read(folder / "SCHEDULE.json")["development"],
    )
    cases = meter.cases(tokenizer, selection, generation_cap=plan["generation"]["max_new_tokens"])
    return dict(
        schema="ltws-v24-recruitment-readout-inputs-v1",
        selection={k: v for k, v in selection.items() if k != "rows"},
        cases=cases,
        bank_manifest_sha256=ex.digest(folder / "MANIFEST.json"),
        tokenizer=manifest["tokenizer"],
        references_per_arm=sum(len(c["references"]) for c in cases),
        fixed_forwards_per_arm=sum(len(r["token_ids"]) for c in cases for r in c["references"]),
        generations_per_arm=len(cases),
    )


def load_inputs(plan):
    value = ex.read_gz(ROOT / INPUT_DIR / "INPUTS.json.gz")
    ex.require(ex.plan_hash(value) == plan["inputs_sha256"], "Frozen input identity")
    ex.require(
        value["selection"]["groups"] == 6 and value["selection"]["unique_rows"] == 36,
        "Whole-group denominator",
    )
    ex.require(
        len(value["cases"]) == value["generations_per_arm"] == 72, "Crossed route denominator"
    )
    ex.require(value["references_per_arm"] == 144, "Reference-order/control denominator")
    ex.require(
        value["fixed_forwards_per_arm"] == plan["fixed_forwards_per_arm"], "Fixed forward bound"
    )
    return value


def frozen_training(plan):
    path = ROOT / INPUT_DIR / "TRAINING_RECEIPTS.json"
    ex.require(ex.digest(path) == plan["training_receipts_sha256"], "Original training receipts")
    value = ex.read(path)
    ex.require(value["SOURCE_SEAL.json"]["source_commit"] == TRAIN_SOURCE, "Frozen FT04 source")
    return value


def validate(plan):
    ex.require(plan["schema"] == "ltws-v24-recruitment-readout-01" and plan["no_retry"], "Protocol")
    ex.require(
        plan["roles"] == list(ROLES) and plan["runtime_routes"] == ["inline", "workspace"],
        "Six cells",
    )
    ex.require(
        plan["groups_per_family"] == 2 and plan["selection_seed"] == "v24-readout-20261027",
        "Selection",
    )
    ex.require(
        plan["generation"] == dict(seed=20261027, temperature=0.0, top_p=1.0, max_new_tokens=128),
        "Single fixed greedy policy",
    )
    ex.require(
        plan["planned_new_sequences"] == 216
        and plan["checkpoint_saves"] == 0
        and plan["native_weight_updates"] == plan["judge_calls"] == plan["weight_deletions"] == 0,
        "Finite non-training scope",
    )
    parent = ex.read(ROOT / evaluation.PLAN)
    ex.require(
        plan["resources"] == parent["resources"]
        and plan["expected_runtime"] == parent["expected_runtime"],
        "Unchanged numerical/resource conditions",
    )
    ex.require(plan["training_plan"] == parent["training_plan"], "Original base graph")
    ex.require(
        all(plan[k] == v for k, v in ex.CEILING.items() if k != "new_sequences"),
        "Historical claim ceiling unchanged",
    )
    ex.require(plan["training_source"] == TRAIN_SOURCE, "Original FT04 identity")
    frozen_training(plan)
    load_inputs(plan)


def restore(graph, args, plan):
    from latent_workspace.native_owner import NativeOptimizerConfig

    original = frozen_training(plan)
    bundle = Path(plan["training_bundle"])
    ex.require(bundle.is_absolute() and bundle.resolve() == bundle, "Exact training bundle")
    ex.require(
        ex.read(bundle / "SOURCE_SEAL.json") == original["SOURCE_SEAL.json"],
        "Training seal unchanged",
    )
    role = args.role
    folder = bundle / "raw" / role
    for name, value in original["roles"][role].items():
        ex.require(ex.read(folder / name) == value, f"Original role receipt {name}")
    terminal = ex.read(folder / "FINISHED.json")
    actual_files = ex.manifest(folder)
    actual_files.pop("FINISHED.json")
    ex.require(actual_files == terminal["files"], "Complete original closed role file set")
    ex.require(terminal["status"] == f"V24_RECRUITMENT_{role.upper()}_COMPLETE", "Completed arm")
    context = ex.read(folder / "CONTEXT.json")
    ex.require(context["contract"]["source_commit"] == TRAIN_SOURCE, "Original restore contract")
    receipt = ex.read(folder / f"CHECKPOINT_{role}_step32.pt.json")
    ex.require(receipt["completed_steps"] == 32, "Final checkpoint")
    owner, actual = restoration.restore_checkpoint(
        graph,
        bundle / "checkpoints" / receipt["path"],
        receipt,
        NativeOptimizerConfig(**context["optimizer"]),
        context["contract"],
        ex.read(folder / f"STATE_{role}_step32.pt.json"),
    )
    ex.write_new(
        args.output / "RESTORE.json",
        dict(
            exact=True,
            checkpoint=receipt,
            fingerprint=actual,
            training_contract=context["contract"],
        ),
    )
    del owner
    gc.collect()


def prepare(core, args, plan):
    return evaluation.prepare(core, args, plan, restore=None if args.role == "base" else restore)


def score_result(tokenizer, result, expected, policy):
    ids, eos = result["token_ids"], tokenizer.eos_token_id
    ex.require(
        result["generated_tokens"] == len(ids) > 0
        and len(ids) <= policy["max_new_tokens"]
        and all(type(t) is int and t >= 0 for t in ids),
        "Complete bounded generated token sequence",
    )
    ex.require(
        result["seed"] == policy["seed"]
        and result["max_new_tokens"] == policy["max_new_tokens"]
        and result["temperature"] == policy["temperature"]
        and result["top_p"] == policy["top_p"],
        "Identical free-generation policy",
    )
    stop = result["stop_reason"]
    ex.require(
        (stop == "eos" and ids[-1] == eos and eos not in ids[:-1])
        or (stop == "length" and len(ids) == policy["max_new_tokens"] and eos not in ids),
        "Exact EOS/cap stopping receipt",
    )
    text = tokenizer.decode(
        ids[:-1] if stop == "eos" else ids,
        skip_special_tokens=False,
        clean_up_tokenization_spaces=False,
    )
    return dict(
        generation=result,
        scoring_text=text,
        raw_decoded=tokenizer.decode(
            ids, skip_special_tokens=False, clean_up_tokenization_spaces=False
        ),
        terminal_eos_only_removed=stop == "eos",
        score=meter.score_generation(text, expected),
    )


def run(core, args, plan, seal):
    from latent_workspace.optimizer_state import tree_hash

    common.engine_imports(seal)
    data = load_inputs(plan)
    graph, tokenizer, guard, before = prepare(core, args, plan)
    ex.require(make_inputs(tokenizer, plan) == data, "Exact pinned-tokenizer input replay")
    ex.write_new(args.output / "INPUTS.json", data)
    counts = dict(
        native_forward_calls=0,
        fixed_forwards=0,
        generated_tokens=0,
        new_sequences=0,
        reference_traces=0,
        native_weight_updates=0,
        checkpoint_saves=0,
    )
    with (
        (args.output / "FIXED.jsonl").open("x") as fixed,
        (args.output / "GENERATIONS.jsonl").open("x") as free,
        (args.output / "CACHE.jsonl").open("x") as cache,
    ):
        boundary = GenerationBoundaryGuard(guard, next(graph.parameters()).device, cache)
        for case in data["cases"]:
            for ref in case["references"]:
                spec = meter.specification(case["prefix_ids"], ref, tokenizer.eos_token_id)
                trace = audit.trace_continuation(
                    graph,
                    spec,
                    tuple(case["memory_ids"]),
                    guard=lambda phase: boundary(
                        f"generation:fixed:{case['id']}:{ref['id']}:{phase}"
                    ),
                )
                evaluation.append(
                    fixed,
                    dict(
                        id=case["id"],
                        reference=ref["id"],
                        trace=trace,
                        measurements=meter.summarize_fixed(trace, ref),
                    ),
                )
                counts["fixed_forwards"] += trace["native_forward_calls"]
                counts["reference_traces"] += 1
            policy = plan["generation"]
            result = ev.generate(
                graph,
                case["prefix_ids"],
                case["memory_ids"],
                seed=policy["seed"],
                cap=policy["max_new_tokens"],
                eos=tokenizer.eos_token_id,
                temperature=policy["temperature"],
                top_p=policy["top_p"],
                guard=lambda phase: boundary(f"generation:free:{case['id']}:{phase}"),
            )
            evaluation.append(
                free,
                dict(
                    id=case["id"],
                    **score_result(tokenizer, result, case["expected"], policy),
                ),
            )
            counts["new_sequences"] += 1
            counts["generated_tokens"] += result["generated_tokens"]
            print(f"{args.role}: {counts['new_sequences']}/72 crossed-route rows", flush=True)
    counts["native_forward_calls"] = counts["fixed_forwards"] + counts["generated_tokens"]
    after = tree_hash(graph.model.state_dict())
    ex.write_new(args.output / "WEIGHT_IDENTITY.json", dict(before=before, after=after))
    ex.require(
        before == after
        and counts["new_sequences"] == data["generations_per_arm"]
        and counts["reference_traces"] == data["references_per_arm"]
        and counts["fixed_forwards"] == data["fixed_forwards_per_arm"],
        "Complete read-only arm",
    )
    ex.require(
        counts["generated_tokens"]
        <= data["generations_per_arm"] * plan["generation"]["max_new_tokens"],
        "Bounded free-generation denominator",
    )
    return dict(**counts, **common.peak(), engine_imports=common.engine_imports(seal))


def summary(folder, plan):
    outcomes = [ex.read(folder / r / "FINISHED.json")["outcome"] for r in ROLES]
    ex.require(
        all(
            e["new_sequences"] == 72
            and e["reference_traces"] == 144
            and e["fixed_forwards"] == plan["fixed_forwards_per_arm"]
            for e in outcomes
        ),
        "All six model/route cells complete",
    )
    ex.require(not list((folder.parent / "checkpoints").iterdir()), "No new tensor files")
    return {
        k: sum(e[k] for e in outcomes)
        for k in (
            "native_forward_calls",
            "fixed_forwards",
            "generated_tokens",
            "new_sequences",
            "reference_traces",
            "native_weight_updates",
            "checkpoint_saves",
        )
    }


class ReadoutRun(IsolatedQualificationMixin, evaluation.EvaluationRun):
    def activity(self, result, outcome=None):
        super().activity(result, outcome)
        result["native_forward_calls"] = (
            None if outcome is None else outcome["native_forward_calls"]
        )


RUN = ReadoutRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass="TINY_V24_RECRUITMENT_READOUT_PASS_NOT_7B",
    roles=ROLES,
    role_status={r: "V24_RECRUITMENT_READOUT_ARM_COMPLETE_NOT_QUALITY" for r in ROLES},
    validate=validate,
    load=common.load,
)


if __name__ == "__main__":
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    os.environ["LTWS_CPU_SDPA_BACKEND"] = "math"
    if len(sys.argv) == 4 and sys.argv[1] in ("prepare-inputs", "verify-inputs"):
        import platform

        import transformers
        from transformers import AutoTokenizer

        ex.offline_environment()
        ex.require(os.environ.get("CUDA_VISIBLE_DEVICES") == "", "Tokenizer-only CPU isolation")
        tok = AutoTokenizer.from_pretrained(
            sys.argv[2], local_files_only=True, trust_remote_code=False
        )
        path = Path(sys.argv[3])
        plan = ex.read(ROOT / PLAN)
        data = make_inputs(tok, plan)
        manifest = ex.read(ROOT / BANK / "MANIFEST.json")
        for name, sha in manifest["tokenizer"]["files"].items():
            ex.require(ex.digest(Path(sys.argv[2]) / name) == sha, "Tokenizer file identity")
        if sys.argv[1] == "verify-inputs":
            validate(plan)
            ex.require(data == load_inputs(plan), "Exact tokenizer/input replay before model load")
            ex.write_new(
                path,
                dict(
                    status="EXACT_INPUT_REPLAY_NO_MODEL_CALL",
                    inputs_sha256=ex.plan_hash(data),
                    python=platform.python_version(),
                    transformers=transformers.__version__,
                    new_sequences=0,
                    native_weight_updates=0,
                ),
            )
            raise SystemExit(0)
        path.mkdir(parents=True, exist_ok=False)
        ex.write_gz(path / "INPUTS.json.gz", data)
        original = {"SOURCE_SEAL.json": ex.read(ROOT / HISTORY / "SOURCE_SEAL.json"), "roles": {}}
        for role in ROLES[1:]:
            original["roles"][role] = {
                name: ex.read(ROOT / HISTORY / "raw" / role / name)
                for name in (
                    "STARTED.json",
                    "CONTEXT.json",
                    "FINISHED.json",
                    f"CHECKPOINT_{role}_step32.pt.json",
                    f"STATE_{role}_step32.pt.json",
                )
            }
        ex.write_new(path / "TRAINING_RECEIPTS.json", original)
        print(
            ex.canonical(
                dict(
                    inputs_sha256=ex.plan_hash(data),
                    training_receipts_sha256=ex.digest(path / "TRAINING_RECEIPTS.json"),
                    fixed_forwards_per_arm=data["fixed_forwards_per_arm"],
                    references_per_arm=data["references_per_arm"],
                    selected_groups=data["selection"]["selected_groups"],
                    generations_per_arm=data["generations_per_arm"],
                )
            )
        )
    else:
        raise SystemExit(RUN.main({r: run for r in ROLES}, summary))
