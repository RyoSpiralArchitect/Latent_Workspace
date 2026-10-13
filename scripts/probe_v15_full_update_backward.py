#!/usr/bin/env python3
"""Bounded full-7B native backward/CPU-accumulation probe. No optimizer or decoding."""

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
from torch.nn import functional as F

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "src"), str(REPO / "scripts")]
import run_v15_5_native_answer as old  # noqa: E402

from latent_workspace_ft_v10.v15_full_update import (  # noqa: E402
    MistralLiveFeatures,
    TrainableNativeWorkspaceReadout,
    full_native_answer_terms,
    full_parameter_ownership,
)

PLAN = REPO / "configs/v15/FULL_UPDATE_BACKWARD_PLAN.json"
ADDITIONS = (
    "configs/v15/FULL_UPDATE_BACKWARD_PLAN.json",
    "docs/v15/FULL_UPDATE_BACKWARD.md",
    "src/latent_workspace_ft_v10/v15_full_update.py",
    "scripts/probe_v15_full_update_backward.py",
    "tests/test_v15_full_update.py",
)


def require(value, message):
    if not value:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text())


def validate():
    plan = read(PLAN)
    parent, architecture, records = old.validate()
    require(plan["states"] == ["initial_seed47", "retained_answer_step8"], "State scope")
    require(plan["pairs"] == [[0, 0], [0, 1], [0, 2]], "Pair scope")
    require(plan["eos_weight"] == 0 and plan["context_boundary"] == 16, "Objective scope")
    require(plan["reader"] == "final", "Reader scope")
    require(plan["gradient_checkpointing"] == "non_reentrant", "Checkpointing scope")
    require(plan["gradient_accumulation"] == "cpu_accumulate", "Transport scope")
    require(
        plan["optimizer_steps"] == plan["new_generations"] == plan["new_judge_calls"] == 0,
        "No-step scope",
    )
    require(plan["optimizer_constructed"] is False and plan["no_retry"] is True, "No retry")
    prior = REPO / plan["prior_bundle"] / "raw"
    require(old.prior.digest(prior / "REPORT.json") == plan["prior_report_sha256"], "Prior report")
    for name, expected in read(prior / "STARTED.json")["source_hashes"].items():
        require(old.prior.digest(REPO / name) == expected, f"Historical source changed: {name}")
    return plan, parent, architecture, records, read(prior / "REPORT.json")


def identity():
    names = set(old.sources()) | set(ADDITIONS)
    return {name: old.prior.digest(REPO / name) for name in sorted(names)}


class LiveStore:
    """Token-only inputs; every current-parameter feature is recomputed."""

    def __init__(self, base, tokenizer, records, observer=None, boundary=16):
        self.base, self.records = base, records
        self.features = MistralLiveFeatures(base, boundary, observer)
        self.renderings, self.context_ids = {}, {}
        for world, record in enumerate(records):
            for query, text in enumerate(record["queries"]):
                row = old.render_case(
                    tokenizer,
                    query=text,
                    context=record["contexts"][0],
                    renderer="native_chat",
                    cue="present",
                    information="query_only",
                )
                other = old.render_case(
                    tokenizer,
                    query=text,
                    context=record["contexts"][1],
                    renderer="native_chat",
                    cue="present",
                    information="query_only",
                )
                require(row == other, "Factual side leaked into query-only prompt")
                self.renderings[world, query] = row
            for key in (0, 1, "unrelated"):
                text = (
                    old.prior.unrelated_context(record)
                    if key == "unrelated"
                    else old.canonical_facts(record["contexts"][key])
                )
                self.context_ids[world, key] = tuple(
                    tokenizer.encode(text, add_special_tokens=False)
                )

    def get(self, prefix):
        return self.features.prefix(prefix)

    def write(self, bridge, world, key):
        hidden = self.features.context(self.context_ids[world, key])
        mask = torch.ones(hidden.shape[:2], dtype=torch.long, device=hidden.device)
        return bridge.write_memory(hidden, mask)


def pair_objective(
    pipe, store, world, query, contract, eos_weight, terms_fn=full_native_answer_terms
):
    """Same V14.5 reductions; a three-pair probe is not a complete objective."""
    row = store.renderings[world, query]
    prefix, candidates, span = tuple(row["prompt_ids"]), row["candidate_ids"], old.bound_span(row)
    hidden = store.get(prefix)
    labels = [store.records[world]["answers"][side][query] for side in (0, 1)]
    terms = []
    for side, label in enumerate(labels):
        memory, mask = store.write(pipe.bridge, world, side)
        token = candidates[label]
        terms.append(
            terms_fn(
                pipe,
                memory,
                mask,
                normalized_prefix=hidden,
                normalized_completion=store.get(prefix + (token,)),
                prefix_ids=prefix,
                completion_prefix_ids=prefix + (token,),
                span=span,
                answer_token_id=token,
                eos_token_id=2,
            )
        )
    memory, mask = store.write(pipe.bridge, world, "unrelated")
    unrelated = pipe(hidden, memory, mask, prefix_ids=prefix, span=span)
    with torch.no_grad():
        baseline = pipe.readout(hidden, torch.zeros_like(hidden[:, -1:]).float())
    scores = [t.answer_output.readout.choice_scores(candidates)[0] for t in terms]
    gap = [v[1] - v[0] for v in scores]
    difference = gap[1] - gap[0]
    donor = (2 * labels[1] - 1) * difference
    other = unrelated.readout.choice_scores(candidates)[0]
    base = baseline.choice_scores(candidates)[0]
    affected, zero = labels[0] != labels[1], difference * 0
    components = {
        "answer_ce": (terms[0].answer_ce + terms[1].answer_ce) / 32,
        "eos_ce": (terms[0].eos_ce + terms[1].eos_ce) / 32,
        "donor_hinge": F.relu(contract["donor_margin"] - donor) / 4 if affected else zero,
        "unaffected_gap_square": difference.square() / 12 if not affected else zero,
        "unrelated_gap_square": ((other[1] - other[0]) - (base[1] - base[0])).square() / 16,
        "residual_norm_square": sum(
            out.delta.square().sum()
            for out in (terms[0].answer_output, terms[1].answer_output, unrelated)
        )
        / 48,
    }
    total = (
        components["answer_ce"]
        + eos_weight * components["eos_ce"]
        + contract["direction_weight"] * components["donor_hinge"]
        + contract["stability_weight"] * components["unaffected_gap_square"]
        + contract["unrelated_weight"] * components["unrelated_gap_square"]
        + contract["residual_penalty"] * components["residual_norm_square"]
    )
    return total, components


class RouteGradients:
    def __init__(self):
        self.rows = []

    def observe(self, route, value):
        if torch.is_grad_enabled() and value.requires_grad:
            index = len(self.rows)
            self.rows.append({"route": route, "shape": list(value.shape), "backward_calls": 0})

            def capture(gradient):
                require(bool(torch.isfinite(gradient).all()), f"Nonfinite route gradient: {route}")
                self.rows[index].update(
                    backward_calls=self.rows[index]["backward_calls"] + 1,
                    l2=float(torch.linalg.vector_norm(gradient, dtype=torch.float32)),
                    nonzero_elements=int(torch.count_nonzero(gradient)),
                )

            value.register_hook(capture)


@torch.no_grad()
def gradient_inventory(named):
    rows = []
    for name, parameter in named:
        gradient = parameter.grad
        row = {"name": name, "elements": parameter.numel(), "present": gradient is not None}
        if gradient is not None:
            require(bool(torch.isfinite(gradient).all()), f"Nonfinite gradient: {name}")
            row.update(
                l2=float(torch.linalg.vector_norm(gradient, dtype=torch.float32)),
                nonzero_elements=int(torch.count_nonzero(gradient)),
            )
        rows.append(row)
    return rows


@torch.no_grad()
def add_cpu_reference(expected, named):
    for name, parameter in named:
        if parameter.grad is not None:
            current = parameter.grad.detach().to("cpu", copy=True)
            if name in expected:
                expected[name].add_(current)
            else:
                expected[name] = current


@torch.no_grad()
def verify_cpu_reference(expected, named):
    checked = []
    for name, parameter in named:
        require((name in expected) == (parameter.grad is not None), f"Gradient missing: {name}")
        if name in expected:
            actual = parameter.grad.detach().cpu()
            require(torch.equal(actual, expected[name]), f"CPU accumulation differs: {name}")
            checked.append(
                {
                    "name": name,
                    "elements": parameter.numel(),
                    "exact": True,
                    "sha256": old.tensor_hash(actual),
                }
            )
    return checked


@torch.no_grad()
def native_parity(base, pipe, store, pairs, prior_rows):
    rows = []
    for world, query in pairs:
        row = store.renderings[world, query]
        prefix, candidates = tuple(row["prompt_ids"]), row["candidate_ids"]
        ids = torch.tensor([prefix], device=base.device)
        actual = base(ids, attention_mask=torch.ones_like(ids), use_cache=False).logits
        hidden = store.get(prefix)
        native = pipe.readout(hidden, torch.zeros_like(hidden[:, -1:]).float())
        require(torch.equal(native.logits, actual), "Ordinary/shared full-logit parity")
        span = old.bound_span(row)
        memory, mask = store.write(pipe.bridge, world, 0)
        zero = pipe(hidden, torch.zeros_like(memory), mask, prefix_ids=prefix, span=span)
        require(torch.equal(zero.readout.logits, actual), "Written-zero native parity")
        scores = []
        for side, control in ((0, "intact"), (1, "twin")):
            memory, mask = store.write(pipe.bridge, world, side)
            output = pipe(hidden, memory, mask, prefix_ids=prefix, span=span)
            observed = output.readout.choice_scores(candidates)[0].tolist()
            old_row = next(
                r
                for r in prior_rows
                if (r["world"], r["query"], r["control"]) == (world, query, control)
            )
            require(observed == old_row["native_scores"], "Historical native scores differ")
            scores.append(observed)
        rows.append(
            {
                "world": world,
                "query": query,
                "ordinary_zero_full_logits_exact": True,
                "written_zero_full_logits_exact": True,
                "historical_scores_exact": True,
                "native_scores": scores,
            }
        )
    return rows


def host_available():
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("Missing host memory availability")


def execute(args):
    plan, parent, architecture, records, previous = validate()
    seal = read(args.seal)
    require(seal["source_hashes"] == identity(), "Sealed source bytes differ")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    require(commit == seal["source_commit"], "Execution source commit differs")
    require(
        not subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO, text=True
        ).strip(),
        "Tracked execution tree dirty",
    )
    checkpoint = args.checkpoint_root / "native_answer_step8.pt"
    parent_arm = previous["results"][0]
    receipt = next(r for r in parent_arm["checkpoints"] if r["path"] == checkpoint.name)
    require(
        checkpoint.stat().st_size == receipt["bytes"]
        and old.prior.digest(checkpoint) == receipt["sha256"],
        "Retained checkpoint identity",
    )
    args.output.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    resources = plan["resources"]
    guard = old.ResourceGuard(resources, args.output)
    base, bridge, accumulator, expected = None, None, None, {}
    loss, terms = None, None
    completed = []

    def check(phase, admission=False):
        row = guard(phase, admission=admission)
        require(not [p for p in row["processes"] if p["pid"] != os.getpid()], "Another GPU client")
        available = host_available()
        minimum = (
            resources["host_admission_available_gib" if admission else "host_abort_available_gib"]
            * 2**30
        )
        require(available >= minimum, "Host memory envelope")
        require(
            shutil.disk_usage(args.output).free >= resources["disk_free_gib"] * 2**30,
            "Disk envelope",
        )
        require(time.monotonic() - start <= resources["max_elapsed_seconds"], "Time envelope")
        with (args.output / "HOST_RESOURCES.jsonl").open("a") as handle:
            handle.write(
                json.dumps(
                    {
                        "phase": phase,
                        "available_bytes": available,
                        "elapsed_seconds": time.monotonic() - start,
                    }
                )
                + "\n"
            )

    try:
        check("admission", admission=True)
        torch.set_num_threads(resources["cpu_threads"])
        torch.set_num_interop_threads(1)
        torch.set_float32_matmul_precision("highest")
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.cuda.set_per_process_memory_fraction(
            resources["allocator_cap_gib"]
            * 2**30
            / torch.cuda.get_device_properties(0).total_memory
        )
        torch.cuda.reset_peak_memory_stats()
        old.write_new(
            args.output / "STARTED.json",
            {
                "source_commit": commit,
                "source_hashes": seal["source_hashes"],
                "seal_sha256": old.prior.digest(args.seal),
                "plan": plan,
                "pid": os.getpid(),
                "python": platform.python_version(),
                "torch": str(torch.__version__),
                "transformers": __import__("transformers").__version__,
                "cuda": torch.version.cuda,
                "checkpoint_receipt": receipt,
            },
        )
        tokenizer = old.engine.load_tokenizer(old.engine.ModelConfig(**architecture["model"]))
        base = old.engine._load_hf_model(old.engine.ModelConfig(**architecture["model"]))
        base = base.to("cuda").train().requires_grad_(True)
        old.engine.enable_gradient_checkpointing(base)
        require(old.prior.state_hash(base) == old.BASE_HASH, "Pinned base differs")
        old.write_new(args.output / "BASE_IDENTITY.json", {"before_sha256": old.BASE_HASH})
        readout = TrainableNativeWorkspaceReadout(base.lm_head)
        for state in plan["states"]:
            torch.manual_seed(parent["training"]["seed"])
            bridge = (
                old.PrecisionAwareWorkspaceBridge(base.config.hidden_size, **architecture["bridge"])
                .to("cuda")
                .float()
            )
            if state == "retained_answer_step8":
                bridge.load_state_dict(
                    torch.load(checkpoint, map_location="cpu", weights_only=True)["state_dict"]
                )
            expected_hash = parent_arm[
                "initial_state_sha256" if state == "initial_seed47" else "final_state_sha256"
            ]
            require(old.prior.state_hash(bridge) == expected_hash, "Bridge start differs")
            routes = RouteGradients()
            store = LiveStore(base, tokenizer, records, routes.observe)
            pipe = old.NativeWorkspacePipeline(bridge, readout, "final")
            handle = bridge.query_projection.register_forward_pre_hook(
                lambda _module, values, observer=routes: observer.observe(
                    "query_to_reader", values[0]
                )
            )
            named = full_parameter_ownership(base, bridge)
            require(
                sum(p.numel() for name, p in named if name.startswith("base.")) == 7248023552,
                "Full 7B element count",
            )
            step = 0 if state == "initial_seed47" else 8
            prior_rows = read(
                REPO / plan["prior_bundle"] / "raw" / f"native_answer_{step}_evaluation.json"
            )["rows"]
            parity = native_parity(base, pipe, store, plan["pairs"], prior_rows)
            old.write_new(args.output / f"{state}_PARITY.json", {"state": state, "rows": parity})
            check(f"{state}:parity")
            accumulator = old.engine._CPUGradientAccumulator(
                named, require_cuda=True, merge_device="cpu"
            )
            expected, pairs = {}, []
            for world, query in plan["pairs"]:
                check(f"{state}:w{world}q{query}:before")
                routes.rows = []
                loss, terms = pair_objective(pipe, store, world, query, parent["training"], 0.0)
                require(bool(torch.isfinite(loss)), "Nonfinite partial loss")
                values = {key: float(value.detach()) for key, value in terms.items()}
                partial = float(loss.detach())
                old.write_new(
                    args.output / f"{state}_w{world}q{query}_FORWARD.json",
                    {
                        "world": world,
                        "query": query,
                        "loss": partial,
                        "components": values,
                        "status": "FORWARD_COMPLETE_BACKWARD_NOT_YET_OBSERVED",
                    },
                )
                loss.backward()
                loss, terms = None, None
                check(f"{state}:w{world}q{query}:backward")
                gradients = gradient_inventory(named)
                require(
                    all(
                        r["present"] and r["nonzero_elements"] > 0
                        for r in gradients
                        if r["name"].startswith("base.")
                    ),
                    "Base gradient coverage failed",
                )
                add_cpu_reference(expected, named)
                spill = accumulator.spill()
                pairs.append(
                    {
                        "world": world,
                        "query": query,
                        "loss": partial,
                        "components": values,
                        "gradients": gradients,
                        "route_gradients": routes.rows,
                        "spill": spill,
                    }
                )
                old.write_new(args.output / f"{state}_w{world}q{query}.json", pairs[-1])
                check(f"{state}:w{world}q{query}:spilled")
            restore = accumulator.restore()
            checks = verify_cpu_reference(expected, named)
            gradients = gradient_inventory(named)
            expected.clear()
            for _, parameter in named:
                parameter.grad = None
            handle.remove()
            bridge_after = old.prior.state_hash(bridge)
            require(bridge_after == expected_hash, "Bridge changed")
            result = {
                "state": state,
                "before_sha256": expected_hash,
                "after_sha256": bridge_after,
                "parity": parity,
                "pairs": plan["pairs"],
                "restore": restore,
                "cpu_reference_exact": checks,
                "accumulated_gradients": gradients,
            }
            old.write_new(args.output / f"{state}.json", result)
            completed.append(state)
            del named, pipe, store, bridge, accumulator, routes, pairs
            bridge, accumulator = None, None
            gc.collect()
            torch.cuda.empty_cache()
            check(f"{state}:complete")
            print(json.dumps({"completed_state": state}), flush=True)
        after = old.prior.state_hash(base)
        require(after == old.BASE_HASH, "Base changed")
        require(identity() == seal["source_hashes"], "Source changed during run")
        result = {
            "status": "COMPLETED_FULL_BACKWARD_NO_STEP",
            "states": completed,
            "base_sha256_before": old.BASE_HASH,
            "base_sha256_after": after,
            "optimizer_steps": 0,
            "optimizer_constructed": False,
            "new_generations": 0,
            "new_judge_calls": 0,
            "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated(),
            "peak_cuda_reserved_bytes": torch.cuda.max_memory_reserved(),
            "elapsed_seconds": time.monotonic() - start,
            "old_expression_gate": "FAIL",
            "non_regression": "NOT_ESTABLISHED",
            "winner": "none",
            "full_16_pair_window": "NOT_TESTED",
            "gpu_add_gradient_oracle": "NOT_TESTED",
        }
        old.write_new(args.output / "REPORT.json", result)
        print(json.dumps(result), flush=True)
    except Exception as error:
        trace = traceback.format_exc()
        loss, terms = None, None
        if accumulator is not None:
            accumulator.discard()
        expected.clear()
        if base is not None:
            base.zero_grad(set_to_none=True)
        if bridge is not None:
            bridge.zero_grad(set_to_none=True)
        gc.collect()
        torch.cuda.empty_cache()
        failure = {
            "status": "FAILED_NO_RETRY",
            "error_type": type(error).__name__,
            "error": str(error),
            "completed_states": completed,
            "optimizer_steps": 0,
            "new_generations": 0,
            "new_judge_calls": 0,
            "elapsed_seconds": time.monotonic() - start,
            "last_guard_phase": guard.rows[-1]["phase"] if guard.rows else None,
            "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated(),
            "peak_cuda_reserved_bytes": torch.cuda.max_memory_reserved(),
            "traceback": trace,
        }
        try:
            failure["base_sha256_after"] = old.prior.state_hash(base) if base is not None else None
            failure["bridge_sha256_after"] = (
                old.prior.state_hash(bridge) if bridge is not None else None
            )
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
        print(json.dumps({"sealed": str(args.seal), "source_commit": commit}))
    else:
        require(
            args.execute and args.output is not None and args.checkpoint_root is not None,
            "Execution requires explicit scope and output",
        )
        execute(args)


if __name__ == "__main__":
    main()
