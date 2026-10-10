#!/usr/bin/env python3
"""One sealed no-autograd factor audit. No optimizer, generation or model API."""

from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

import torch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "src"), str(REPO / "scripts")]
import probe_v15_reader_modulation as parent  # noqa: E402

from latent_workspace_ft_v10 import reader_factor_audit as audit  # noqa: E402

old, read, require = parent.old, parent.read, parent.require
PLAN = REPO / "configs/v15/READER_FACTOR_PLAN.json"
PRIOR = REPO / "provenance/pilots/v15_reader_modulation_20261010"
ADDITIONS = (
    "configs/v15/READER_FACTOR_PLAN.json",
    "docs/v15/READER_FACTOR_AUDIT.md",
    "src/latent_workspace_ft_v10/reader_factor_audit.py",
    "scripts/probe_v15_reader_factors.py",
    "scripts/summarize_v15_reader_factors.py",
    "tests/test_v15_reader_factors.py",
)


def validate():
    plan = read(PLAN)
    _, training, architecture, records, previous = parent.validate()
    require(plan["states"] == ["retained_answer_step8"], "Retained state only")
    require(plan["arms"] == ["legacy", "query_modulated"], "Reader scope")
    require(plan["worlds"] == [0, 1] and plan["even_queries"] == [0, 2, 4, 6], "Exposed scope")
    require(
        plan["memory_pairs"] == ["actual", "common_slots", "same_memory", "random_pair"], "Controls"
    )
    require(plan["random_seed"] == 470016 and plan["modulation_strength"] == 0.25, "No sweep")
    require(plan["query_mode"] == "final" and plan["no_retry"] is True, "Read/dispatch scope")
    require(plan["factor_order"] == list(audit.NAMES), "Factor order")
    require(plan["factor_signs"] == [list(s) for s in audit.SIGNS], "Factor signs")
    require(
        plan["optimizer_steps"] == plan["new_generations"] == plan["new_judge_calls"] == 0,
        "No updates",
    )
    require(plan["old_expression_gate"] == "FAIL" and plan["winner"] == "none", "Old gates")
    index = read(PRIOR / "ARTIFACT_INDEX.json")
    require(len(index) == 13, "Prior raw denominator")
    for name, r in index.items():
        p = PRIOR / "raw" / name
        require(
            old.prior.digest(p) == r["sha256"] and p.stat().st_size == r["bytes"], "Prior raw seal"
        )
    for name, expected in read(PRIOR / "SOURCE_SEAL.json")["source_hashes"].items():
        require(old.prior.digest(REPO / name) == expected, f"Prior source seal: {name}")
    return plan, training, architecture, records, previous


def identity():
    names = set(parent.identity()) | set(ADDITIONS)
    names |= {str(p.relative_to(REPO)) for p in (PRIOR / "raw").iterdir() if p.is_file()}
    names |= {
        str((PRIOR / name).relative_to(REPO))
        for name in ("SOURCE_SEAL.json", "ARTIFACT_INDEX.json")
    }
    return {name: old.prior.digest(REPO / name) for name in sorted(names)}


@torch.no_grad()
def capture(bridge, question, memory, mask):
    values = {}

    def save(name, value):
        require(name not in values, "Duplicate trace hook")
        values[name] = value.detach().clone()

    def query_hook(_module, _inputs, output):
        save("q", output)

    def attention_hook(_module, _inputs, output):
        save("r", output[0])

    def up_pre(_module, inputs):
        save("z", inputs[0])

    def up_post(_module, _inputs, output):
        save("x", output)

    handles = [
        bridge.query_norm.register_forward_hook(query_hook),
        bridge.attention.register_forward_hook(attention_hook),
        bridge.up.register_forward_pre_hook(up_pre),
        bridge.up.register_forward_hook(up_post),
    ]
    try:
        delta = bridge.read_delta(question, memory, mask)
    finally:
        for handle in handles:
            handle.remove()
    strength = getattr(bridge, "modulation_strength", 0.0)
    values["gate"] = strength * values["q"].tanh()
    values["d"] = delta
    expected = values["r"] * (1 + values["gate"]) if strength else values["r"]
    require(torch.equal(expected, values["z"]), "Production modulation formula")
    require(all(not v.requires_grad and v.grad_fn is None for v in values.values()), "No autograd")
    hashes = {key: old.tensor_hash(v) for key, v in values.items()}
    return delta, {key: v.cpu().double().reshape(-1) for key, v in values.items()}, hashes


@torch.no_grad()
def memories(bridge, store, world, seed):
    actual = [store.write(bridge, world, side) for side in (0, 1)]
    means, random = [], []
    for side, (value, mask) in enumerate(actual):
        active = mask.unsqueeze(-1).to(value.dtype)
        mean = (value * active).sum(1, keepdim=True) / active.sum(1, keepdim=True)
        means.append((mean.expand_as(value).clone(), mask))
        random_value = torch.randn(
            value.shape, generator=torch.Generator().manual_seed(seed + 2 * world + side)
        )
        random_value = random_value.to(value.device) * active
        random_value *= value.norm() / random_value.norm()
        random.append((random_value, mask))
    return {
        "actual": actual,
        "common_slots": means,
        "same_memory": [actual[0], actual[0]],
        "random_pair": random,
    }


@torch.no_grad()
def panel(bridge, store, readout, plan, arm, operator, axis, left, right, check):
    pipe = old.NativeWorkspacePipeline(bridge, readout, "final")
    historical = read(PRIOR / "raw" / f"retained_answer_step8_{arm}_EVAL.json")["rows"]
    before = {(r["world"], r["query"], r["control"]): r for r in historical}
    rows, blocks, zero = [], [], []
    for world in plan["worlds"]:
        bank = memories(bridge, store, world, plan["random_seed"])
        for even in plan["even_queries"]:
            check(f"{arm}:{world}:{even}")
            features = []
            for query in (even, even + 1):
                row = store.renderings[world, query]
                require(row["candidate_ids"] == [1476, 5849], "Fixed no/yes axis")
                prefix = tuple(row["prompt_ids"])
                hidden = store.get(prefix)
                question = pipe.query(hidden, prefix_ids=prefix, span=old.bound_span(row))
                baseline = readout(hidden, torch.zeros_like(hidden[:, -1:]).float())
                memory, mask = bank["actual"][0]
                written_zero = bridge.read_delta(question, torch.zeros_like(memory), mask)
                out_zero = readout(hidden, written_zero)
                require(
                    written_zero.count_nonzero() == 0
                    and torch.equal(baseline.logits, out_zero.logits),
                    "Zero identity",
                )
                zero.append({"world": world, "query": query, "full_logits_exact": True})
                features.append((hidden, question, row["candidate_ids"]))
            for variant in plan["memory_pairs"]:
                traces = []
                for offset, (hidden, question, candidates) in enumerate(features):
                    query = even + offset
                    for side, (memory, mask) in enumerate(bank[variant]):
                        delta, trace, hashes = capture(bridge, question, memory, mask)
                        traces.append(trace)
                        out = readout(hidden, delta)
                        scores = out.choice_scores(candidates)[0].tolist()
                        label = (
                            store.records[world]["answers"][side][query]
                            if variant == "actual"
                            else None
                        )
                        prediction = None if scores[0] == scores[1] else int(scores[1] > scores[0])
                        if variant == "actual":
                            control = "intact" if side == 0 else "twin"
                            require(
                                scores == before[world, query, control]["native_scores"],
                                "Prior native choices",
                            )
                        rows.append(
                            {
                                "world": world,
                                "query": query,
                                "variant": variant,
                                "side": side,
                                "native_scores": scores,
                                "label": label,
                                "prediction": prediction,
                                "correct": prediction == label if label is not None else None,
                                "prior_native_exact": variant == "actual",
                                "trace_sha256": hashes,
                                "memory_sha256": old.tensor_hash(memory),
                                "mask_sha256": old.tensor_hash(mask),
                                "memory_l2": audit.norm(memory),
                                "delta_l2": audit.norm(delta),
                            }
                        )
                require(
                    torch.equal(traces[0]["gate"], traces[1]["gate"])
                    and torch.equal(traces[2]["gate"], traces[3]["gate"]),
                    "Memory-independent gate",
                )
                odd_sign = 2 * store.records[world]["answers"][1][even + 1] - 1
                result = audit.audit_block(
                    traces,
                    operator,
                    axis,
                    left,
                    right,
                    bridge.max_delta_norm,
                    arm == "query_modulated",
                    odd_sign,
                )
                result.update(
                    world=world,
                    even_query=even,
                    variant=variant,
                    binding_label_interpretation=variant == "actual" and even == 0,
                    odd_donor_sign=odd_sign,
                )
                if variant == "same_memory":
                    require(
                        all(
                            result["factors"][stage][name]["l2"] == 0
                            for stage in ("r", "z", "x", "d")
                            for name in ("memory", "interaction")
                        ),
                        "Same-memory null",
                    )
                blocks.append(result)
    return {"rows": rows, "blocks": blocks, "written_zero": zero}


@torch.no_grad()
def execute(args):
    plan, _, architecture, records, previous = validate()
    seal = read(args.seal)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    require(commit == seal["source_commit"] and identity() == seal["source_hashes"], "Source seal")
    require(
        not subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO, text=True
        ).strip(),
        "Dirty source",
    )
    checkpoint = args.checkpoint_root / "native_answer_step8.pt"
    retained = previous["results"][0]
    receipt = next(r for r in retained["checkpoints"] if r["path"] == checkpoint.name)
    require(
        old.prior.digest(checkpoint) == receipt["sha256"]
        and checkpoint.stat().st_size == receipt["bytes"],
        "Checkpoint identity",
    )
    args.output.mkdir(parents=True, exist_ok=False)
    start, results = time.monotonic(), []
    guard = old.ResourceGuard(plan["resources"], args.output)

    def check(phase, admission=False):
        row = guard(phase, admission=admission)
        require(not [p for p in row["processes"] if p["pid"] != os.getpid()], "Other GPU client")
        require(time.monotonic() - start < plan["resources"]["max_elapsed_seconds"], "Wall limit")
        require(
            shutil.disk_usage(args.output).free >= plan["resources"]["disk_free_gib"] * 2**30,
            "Disk floor",
        )

    try:
        check("admission", True)
        torch.set_num_threads(plan["resources"]["cpu_threads"])
        torch.set_num_interop_threads(1)
        torch.set_float32_matmul_precision("highest")
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.cuda.set_per_process_memory_fraction(
            plan["resources"]["allocator_cap_gib"]
            * 2**30
            / torch.cuda.get_device_properties(0).total_memory
        )
        torch.cuda.reset_peak_memory_stats()
        old.write_new(
            args.output / "STARTED.json",
            {
                **seal,
                "plan": plan,
                "pid": os.getpid(),
                "checkpoint": receipt,
                "python": platform.python_version(),
                "torch": str(torch.__version__),
                "transformers": __import__("transformers").__version__,
                "cuda": torch.version.cuda,
            },
        )
        config = old.engine.ModelConfig(**architecture["model"])
        tokenizer = old.engine.load_tokenizer(config)
        base = old.engine._load_hf_model(config).to("cuda").eval().requires_grad_(False)
        require(old.prior.state_hash(base) == old.BASE_HASH, "Pinned base")
        old.write_new(args.output / "BASE_IDENTITY.json", {"before_sha256": old.BASE_HASH})
        readout = old.NativeWorkspaceReadout(base.lm_head)
        store = old.Store(base, tokenizer, readout, records, check)
        old.write_new(args.output / "FEATURES.json", store.feature_receipt())
        state = torch.load(checkpoint, weights_only=True, map_location="cpu")["state_dict"]
        operator = state["up.weight"].double()
        axis = (
            base.lm_head.weight[5849].detach().cpu().double()
            - base.lm_head.weight[1476].detach().cpu().double()
        )
        left, right, spectrum = audit.spectral(operator, axis)
        old.write_new(
            args.output / "SPECTRUM.json",
            {
                **spectrum,
                "up_sha256": old.tensor_hash(state["up.weight"]),
                "axis_sha256": old.tensor_hash(axis),
                "candidate_ids": [1476, 5849],
            },
        )
        for arm in plan["arms"]:
            cls = (
                old.PrecisionAwareWorkspaceBridge
                if arm == "legacy"
                else parent.QueryModulatedWorkspaceBridge
            )
            bridge = (
                cls(base.config.hidden_size, **architecture["bridge"])
                .to("cuda")
                .float()
                .eval()
                .requires_grad_(False)
            )
            bridge.load_state_dict(state, strict=True)
            expected = retained["final_state_sha256"]
            require(old.prior.state_hash(bridge) == expected, "Bridge before identity")
            observed = panel(bridge, store, readout, plan, arm, operator, axis, left, right, check)
            old.write_new(args.output / f"{arm}_FACTORS.json", observed)
            after = old.prior.state_hash(bridge)
            require(
                after == expected and all(p.grad is None for p in bridge.parameters()),
                "Bridge mutation",
            )
            results.append(
                {
                    "arm": arm,
                    "before_sha256": expected,
                    "after_sha256": after,
                    "parameter_grad_fields_none": True,
                    "rows": len(observed["rows"]),
                    "blocks": len(observed["blocks"]),
                }
            )
            del observed, bridge
            gc.collect()
            torch.cuda.empty_cache()
            check(f"{arm}:complete")
            print(json.dumps(results[-1]), flush=True)
        after = old.prior.state_hash(base)
        require(
            after == old.BASE_HASH and all(p.grad is None for p in base.parameters()),
            "Base mutation",
        )
        require(identity() == seal["source_hashes"], "Source changed")
        check("terminal")
        report = {
            "status": "COMPLETED_READER_FACTOR_AUDIT_NO_UPDATE",
            "results": results,
            "base_sha256_before": old.BASE_HASH,
            "base_sha256_after": after,
            "parameter_grad_fields_none": True,
            "optimizer_steps": 0,
            "optimizer_constructed": False,
            "autograd_enabled": False,
            "new_generations": 0,
            "new_judge_calls": 0,
            "elapsed_seconds": time.monotonic() - start,
            "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated(),
            "peak_cuda_reserved_bytes": torch.cuda.max_memory_reserved(),
            "old_expression_gate": "FAIL",
            "winner": "none",
            "non_regression": "NOT_ESTABLISHED",
        }
        old.write_new(args.output / "REPORT.json", report)
        print(json.dumps(report), flush=True)
    except Exception as error:
        old.write_new(
            args.output / "FAILED.json",
            {
                "status": "FAILED_NO_RETRY",
                "error": str(error),
                "traceback": traceback.format_exc(),
                "completed": results,
                "optimizer_steps": 0,
                "new_generations": 0,
                "new_judge_calls": 0,
            },
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("seal", "run"))
    parser.add_argument("--seal", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--checkpoint-root", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    validate()
    if args.action == "seal":
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
        old.write_new(args.seal, {"source_commit": commit, "source_hashes": identity()})
        print(json.dumps({"source_commit": commit, "source_files": len(identity())}))
    else:
        require(
            args.execute and args.output is not None and args.checkpoint_root is not None,
            "Explicit bounded execution required",
        )
        execute(args)


if __name__ == "__main__":
    main()
