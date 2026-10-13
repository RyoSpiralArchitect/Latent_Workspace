#!/usr/bin/env python3
"""No-step, fixed-checkpoint reader comparison; never calls a model API or optimizer."""

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
import probe_v15_full_update_backward as previous  # noqa: E402
import run_v15_5_native_answer as old  # noqa: E402

from latent_workspace_ft_v10.bridge_reader_panel import _capture  # noqa: E402
from latent_workspace_ft_v10.query_modulated_bridge import (  # noqa: E402
    QueryModulatedWorkspaceBridge,
)

PLAN = REPO / "configs/v15/READER_MODULATION_PLAN.json"
CONTROLS = [
    "intact",
    "twin",
    "zero",
    "unrelated",
    "carrier",
    "random",
    "permuted_intact",
    "common_intact",
]
ADDITIONS = (
    "configs/v15/READER_MODULATION_PLAN.json",
    "docs/v15/READER_MODULATION.md",
    "src/latent_workspace_ft_v10/query_modulated_bridge.py",
    "scripts/probe_v15_reader_modulation.py",
    "scripts/summarize_v15_reader_modulation.py",
    "tests/test_v15_reader_modulation.py",
)
require, read = previous.require, previous.read


def validate():
    plan = read(PLAN)
    _, parent, architecture, records, prior_report = previous.validate()
    require(plan["states"] == ["initial_seed47", "retained_answer_step8"], "State scope")
    require(plan["arms"] == ["legacy", "query_modulated"], "Arm scope")
    require(plan["modulation_strength"] == 0.25, "No modulation sweep")
    require(plan["worlds"] == [0, 1] and plan["queries"] == list(range(8)), "Exposed scope")
    require(plan["controls"] == CONTROLS and plan["random_seed"] == 470015, "Control scope")
    require(plan["reader"] == "final" and plan["eos_weight"] == 0, "Reader/loss scope")
    require(
        plan["optimizer_steps"] == plan["new_generations"] == plan["new_judge_calls"] == 0
        and plan["optimizer_constructed"] is False
        and plan["no_retry"] is True,
        "No-update scope",
    )
    return plan, parent, architecture, records, prior_report


def identity():
    names = set(previous.identity()) | set(ADDITIONS)
    return {name: old.prior.digest(REPO / name) for name in sorted(names)}


def norm(value):
    return float(value.detach().double().norm())


def geometry(first, second):
    a, b = first.detach().double(), second.detach().double()
    na, nb = norm(a), norm(b)
    common, diff = (a + b) / 2, b - a
    nc = norm(common)
    radial = (diff * common).sum() / nc if nc else None
    tangential = norm(diff - radial * common / nc) if nc else None
    return {
        "difference_l2": norm(diff),
        "relative_l2": norm(diff) / (0.5 * (na + nb) + 1e-12),
        "unit_direction_difference_l2": norm(a / na - b / nb) if na and nb else None,
        "equal_norm_difference_l2": (norm(a / na - b / nb) * (na + nb) / 2 if na and nb else None),
        "radial_difference": float(radial) if radial is not None else None,
        "tangential_difference_l2": tangential,
    }


def control_memories(bridge, store, world, seed):
    intact, mask = store.write(bridge, world, 0)
    twin = store.write(bridge, world, 1)
    unrelated = store.write(bridge, world, "unrelated")
    active = mask.unsqueeze(-1).to(intact.dtype)
    mean = (intact * active).sum(1, keepdim=True) / active.sum(1, keepdim=True)
    positions = torch.arange(intact.numel(), dtype=torch.float32).reshape(intact.shape)
    carrier = ((positions + 1).sin() + (0.37 * positions).cos()).to(intact.device)
    random = torch.randn(intact.shape, generator=torch.Generator().manual_seed(seed + world)).to(
        intact.device
    )

    def matched(value):
        value = value * active
        return value * (intact.norm() / value.norm())

    return {
        "intact": (intact, mask),
        "twin": twin,
        "zero": (torch.zeros_like(intact), mask),
        "unrelated": unrelated,
        "carrier": (matched(carrier), mask),
        "random": (matched(random), mask),
        "permuted_intact": (intact.flip(1), mask.flip(1)),
        "common_intact": (mean.expand_as(intact).clone(), mask),
    }


@torch.no_grad()
def evaluation(pipe, off_bridge, store, plan, state, historical):
    rows, reciprocal, interactions, permutations = [], [], [], []
    for world in plan["worlds"]:
        memories = control_memories(pipe.bridge, store, world, plan["random_seed"])
        prior_traces = None
        for query in plan["queries"]:
            row = store.renderings[world, query]
            prefix, candidates = tuple(row["prompt_ids"]), row["candidate_ids"]
            hidden, span = store.get(prefix), old.bound_span(row)
            question = pipe.query(hidden, prefix_ids=prefix, span=span)
            baseline = pipe.readout(hidden, torch.zeros_like(hidden[:, -1:]).float())
            traces = {}
            for control, (memory, mask) in memories.items():
                trace = _capture(pipe.bridge, question, memory, mask)
                traces[control] = trace
                out = pipe.readout(hidden, trace["delta"])
                scores = out.choice_scores(candidates)[0].tolist()
                fp32 = pipe.readout.legacy_fp32_choices(hidden, trace["delta"], candidates)[0]
                exact = torch.equal(out.logits, baseline.logits)
                if control == "zero" or state == "initial_seed47":
                    require(exact and norm(trace["delta"]) == 0, "Native zero/initial identity")
                if off_bridge is not None:
                    require(
                        torch.equal(off_bridge.read_delta(question, memory, mask), trace["delta"]),
                        "Strength-zero candidate differs from historical delta",
                    )
                    if control in ("intact", "twin"):
                        before = next(
                            r
                            for r in historical
                            if (r["world"], r["query"], r["control"]) == (world, query, control)
                        )
                        require(scores == before["native_scores"], "Legacy native parity")
                side = 0 if control == "intact" else 1 if control == "twin" else None
                label = store.records[world]["answers"][side][query] if side is not None else None
                prediction = None if scores[0] == scores[1] else int(scores[1] > scores[0])
                rows.append(
                    {
                        "world": world,
                        "query": query,
                        "control": control,
                        "label": label,
                        "native_scores": scores,
                        "fp32_scores": fp32.tolist(),
                        "base_native_scores": baseline.choice_scores(candidates)[0].tolist(),
                        "prediction": prediction,
                        "correct": prediction == label if label is not None else None,
                        "delta_l2": norm(trace["delta"]),
                        "raw_delta_l2": norm(trace["raw_delta"]),
                        "memory_l2": norm(memory),
                        "attention_output_l2": norm(trace["attention_output"]),
                        "applied_native_delta_l2": norm(out.applied_delta),
                        "full_logits_equal_base": exact,
                        "legacy_source_score_exact": off_bridge is not None and side is not None,
                        "strength_zero_delta_exact": off_bridge is not None,
                    }
                )
                if query % 2:
                    reciprocal.append(
                        {
                            "world": world,
                            "even_query": query - 1,
                            "control": control,
                            **{
                                key: geometry(prior_traces[control][key], trace[key])
                                for key in ("query", "attention_output", "raw_delta", "delta")
                            },
                        }
                    )
            require(
                torch.allclose(
                    traces["intact"]["delta"], traces["permuted_intact"]["delta"], atol=1e-5, rtol=0
                ),
                "Joint slot permutation differs beyond declared numerical tolerance",
            )
            permutations.append(
                {
                    "world": world,
                    "query": query,
                    "delta_max_abs_error": float(
                        (traces["intact"]["delta"] - traces["permuted_intact"]["delta"]).abs().max()
                    ),
                }
            )
            if query % 2:
                mixed = (
                    traces["twin"]["delta"]
                    - traces["intact"]["delta"]
                    - prior_traces["twin"]["delta"]
                    + prior_traces["intact"]["delta"]
                )
                interactions.append(
                    {
                        "world": world,
                        "even_query": query - 1,
                        "mixed_delta_difference_l2": norm(mixed),
                    }
                )
            prior_traces = traces
    return {
        "rows": rows,
        "reciprocal": reciprocal,
        "interactions": interactions,
        "permutations": permutations,
    }


class QueryCutPipeline(old.NativeWorkspacePipeline):
    """Diagnostic only: cut the frozen query at a separate FP32 leaf per read."""

    def query(self, normalized, *, prefix_ids, span):
        result = super().query(normalized, prefix_ids=prefix_ids, span=span)
        return result.detach().requires_grad_(torch.is_grad_enabled())


def gradients(bridge, readout, store, contract, plan, check):
    pipe = QueryCutPipeline(bridge, readout, "final")
    named = list(bridge.named_parameters())
    roles = ["intact_answer", "intact_eos", "twin_answer", "twin_eos", "unrelated"]
    rows, donor_sum, donor_norm_sum, captured = [], torch.zeros_like(bridge.up.weight), 0.0, []
    handle = bridge.query_projection.register_forward_pre_hook(
        lambda _module, inputs: captured.append(inputs[0])
    )
    try:
        for world in plan["worlds"]:
            for query in plan["queries"]:
                captured.clear()
                loss, terms = old.pair_objective(pipe, store, world, query, contract, 0.0)
                require(len(captured) == 5, "Expected five reader calls per objective pair")
                grad = torch.autograd.grad(
                    loss, [p for _, p in named] + captured, retain_graph=True
                )
                donor = torch.autograd.grad(terms["donor_hinge"], bridge.up.weight)[0]
                require(
                    all(bool(torch.isfinite(g).all()) for g in (*grad, donor)), "Finite gradients"
                )
                donor_sum += donor
                donor_norm_sum += norm(donor)
                routes = [
                    {"role": role, "l2": norm(g), "nonzero_elements": int(g.count_nonzero())}
                    for role, g in zip(roles, grad[len(named) :], strict=True)
                ]
                require(
                    all(r["l2"] == 0 for r in routes if r["role"].endswith("eos")),
                    "Zero-weight EOS gradient differs",
                )
                rows.append(
                    {
                        "world": world,
                        "query": query,
                        "loss": float(loss.detach()),
                        "components": {key: float(value.detach()) for key, value in terms.items()},
                        "routes": routes,
                        "parameters": [
                            {
                                "name": name,
                                "l2": norm(g),
                                "nonzero_elements": int(g.count_nonzero()),
                            }
                            for (name, _), g in zip(named, grad[: len(named)], strict=True)
                        ],
                        "donor_up_gradient_l2": norm(donor),
                    }
                )
                del loss, terms, grad, donor
                captured.clear()
                check(f"gradient:w{world}q{query}")
    finally:
        handle.remove()
    require(all(p.grad is None for _, p in named), "Probe populated parameter .grad")
    return {
        "pairs": rows,
        "donor_up_sum_l2": norm(donor_sum),
        "donor_up_sum_of_pair_l2": donor_norm_sum,
        "donor_up_cancellation_ratio": norm(donor_sum) / donor_norm_sum if donor_norm_sum else None,
    }


def execute(args):
    plan, parent, architecture, records, prior_report = validate()
    seal = read(args.seal)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    require(commit == seal["source_commit"] and identity() == seal["source_hashes"], "Source seal")
    require(
        not subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO, text=True
        ).strip(),
        "Dirty tracked source",
    )
    checkpoint = args.checkpoint_root / "native_answer_step8.pt"
    retained = prior_report["results"][0]
    receipt = next(r for r in retained["checkpoints"] if r["path"] == checkpoint.name)
    require(
        old.prior.digest(checkpoint) == receipt["sha256"]
        and checkpoint.stat().st_size == receipt["bytes"],
        "Retained checkpoint differs",
    )
    args.output.mkdir(parents=True, exist_ok=False)
    started, base, bridge, results = time.monotonic(), None, None, []
    guard = old.ResourceGuard(plan["resources"], args.output)

    def check(phase, admission=False):
        row = guard(phase, admission=admission)
        require(not [r for r in row["processes"] if r["pid"] != os.getpid()], "Other GPU client")
        require(time.monotonic() - started < plan["resources"]["max_elapsed_seconds"], "Wall limit")
        require(
            shutil.disk_usage(args.output).free >= plan["resources"]["disk_free_gib"] * 2**30,
            "Disk envelope",
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
        require(old.prior.state_hash(base) == old.BASE_HASH, "Pinned base changed")
        old.write_new(args.output / "BASE_IDENTITY.json", {"before_sha256": old.BASE_HASH})
        readout = old.NativeWorkspaceReadout(base.lm_head)
        store = old.Store(base, tokenizer, readout, records, check)
        old.write_new(args.output / "FEATURES.json", store.feature_receipt())
        for state in plan["states"]:
            torch.manual_seed(parent["training"]["seed"])
            original = (
                old.PrecisionAwareWorkspaceBridge(base.config.hidden_size, **architecture["bridge"])
                .float()
                .eval()
            )
            if state == "retained_answer_step8":
                original.load_state_dict(
                    torch.load(checkpoint, weights_only=True, map_location="cpu")["state_dict"]
                )
            expected = retained[
                "initial_state_sha256" if state == "initial_seed47" else "final_state_sha256"
            ]
            require(old.prior.state_hash(original) == expected, "Bridge source hash")
            step = 0 if state == "initial_seed47" else 8
            historical = read(
                REPO
                / "provenance/pilots/v15_5_native_answer_20261010/raw"
                / f"native_answer_{step}_evaluation.json"
            )["rows"]
            for arm in plan["arms"]:
                cls = (
                    old.PrecisionAwareWorkspaceBridge
                    if arm == "legacy"
                    else QueryModulatedWorkspaceBridge
                )
                bridge = (
                    cls(base.config.hidden_size, **architecture["bridge"]).to("cuda").float().eval()
                )
                bridge.load_state_dict(original.state_dict(), strict=True)
                require(list(bridge.state_dict()) == list(original.state_dict()), "Parameter keys")
                require(sum(p.numel() for p in bridge.parameters()) == 4200192, "Parameter count")
                off = None
                if arm == "legacy":
                    off = (
                        QueryModulatedWorkspaceBridge(
                            base.config.hidden_size, **architecture["bridge"], modulation_strength=0
                        )
                        .to("cuda")
                        .eval()
                    )
                    off.load_state_dict(original.state_dict(), strict=True)
                check(f"{state}:{arm}:before")
                panel = evaluation(
                    old.NativeWorkspacePipeline(bridge, readout, "final"),
                    off,
                    store,
                    plan,
                    state,
                    historical,
                )
                old.write_new(args.output / f"{state}_{arm}_EVAL.json", panel)
                del panel, off
                gradient = gradients(bridge, readout, store, parent["training"], plan, check)
                old.write_new(args.output / f"{state}_{arm}_GRAD.json", gradient)
                after = old.prior.state_hash(bridge)
                require(after == expected, "Bridge changed during no-step probe")
                results.append(
                    {
                        "state": state,
                        "arm": arm,
                        "before_sha256": expected,
                        "after_sha256": after,
                        "parameter_tensors": len(list(bridge.parameters())),
                        "parameter_elements": sum(p.numel() for p in bridge.parameters()),
                    }
                )
                del gradient, bridge
                bridge = None
                gc.collect()
                torch.cuda.empty_cache()
                check(f"{state}:{arm}:done")
                print(json.dumps(results[-1]), flush=True)
            del original
        after = old.prior.state_hash(base)
        require(
            after == old.BASE_HASH and all(p.grad is None for p in base.parameters()),
            "Base state/grad changed",
        )
        require(identity() == seal["source_hashes"], "Source changed during run")
        report = {
            "status": "COMPLETED_READER_INTERVENTION_NO_STEP",
            "results": results,
            "base_sha256_before": old.BASE_HASH,
            "base_sha256_after": after,
            "optimizer_steps": 0,
            "optimizer_constructed": False,
            "new_generations": 0,
            "new_judge_calls": 0,
            "elapsed_seconds": time.monotonic() - started,
            "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated(),
            "peak_cuda_reserved_bytes": torch.cuda.max_memory_reserved(),
            "old_expression_gate": "FAIL",
            "winner": "none",
            "non_regression": "NOT_ESTABLISHED",
        }
        old.write_new(args.output / "REPORT.json", report)
        print(json.dumps(report), flush=True)
    except Exception as error:
        failure = {
            "status": "FAILED_NO_RETRY",
            "error": str(error),
            "traceback": traceback.format_exc(),
            "completed": results,
            "optimizer_steps": 0,
            "new_generations": 0,
            "new_judge_calls": 0,
        }
        try:
            failure["base_sha256_after"] = old.prior.state_hash(base) if base else None
            failure["bridge_sha256_after"] = old.prior.state_hash(bridge) if bridge else None
        except Exception as identity_error:
            failure["identity_check_error"] = str(identity_error)
        old.write_new(args.output / "FAILED.json", failure)
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
        print(json.dumps({"source_commit": commit, "sealed_files": len(identity())}))
    else:
        require(
            args.execute and args.output is not None and args.checkpoint_root is not None,
            "Explicit bounded execution and output required",
        )
        execute(args)


if __name__ == "__main__":
    main()
