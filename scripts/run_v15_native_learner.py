#!/usr/bin/env python3
"""Sealed, exclusive V15 reader comparison / full-update qualification. No API calls."""

from __future__ import annotations

import argparse
import gc
import hashlib
import inspect
import json
import os
import platform
import random
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import torch
import transformers
from transformers.optimization import Adafactor

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "src"), str(REPO / "scripts")]
import probe_v15_full_update_backward as backward  # noqa: E402
import probe_v15_reader_factors as factors  # noqa: E402
import run_v15_5_native_answer as old  # noqa: E402

from latent_workspace_ft_v10 import reader_factor_audit as audit  # noqa: E402
from latent_workspace_ft_v10.v15_native_learner import (  # noqa: E402
    V15NativeLearner,
    create_reader,
    require,
    rng_state,
    tree_hash,
)

PLAN = REPO / "configs/v15/NATIVE_LEARNER_PLAN.json"
ADDITIONS = (
    "configs/v15/NATIVE_LEARNER_PLAN.json",
    "docs/v15/NATIVE_LEARNER.md",
    "src/latent_workspace_ft_v10/v15_native_learner.py",
    "scripts/run_v15_native_learner.py",
    "scripts/verify_v15_native_learner.py",
    "tests/test_v15_native_learner.py",
    "tests/test_v15_native_runner.py",
)
GIB = 2**30


def read(path):
    return json.loads(path.read_text())


def identity():
    return {
        name: old.prior.digest(REPO / name) for name in sorted(set(old.sources()) | set(ADDITIONS))
    }


def validate():
    plan = read(PLAN)
    objective, architecture, records = old.validate()
    require(plan["worlds"] == [0, 1] and plan["queries"] == list(range(8)), "Exposed data scope")
    require(
        plan["reader_phase"]
        == dict(
            arms=["legacy", "query_modulated"],
            steps=8,
            evaluation_steps=[0, 1, 8],
            factor_steps=[0, 8],
            generation_steps=[0, 8],
            checkpoint_steps=[4, 8],
        ),
        "Reader budget changed",
    )
    require(
        plan["full_phase"]
        == dict(
            arms=["frozen", "full"],
            reader="query_modulated",
            steps=2,
            evaluation_steps=[0, 1, 2],
            factor_steps=[0, 2],
            generation_steps=[0, 2],
            checkpoint_steps=[1, 2],
            resume_replay_step=2,
            resume_from_step=1,
        ),
        "Full budget changed",
    )
    require(
        plan["seed"] == 47
        and plan["context_boundary"] == 16
        and plan["query_mode"] == "final"
        and plan["modulation_strength"] == 0.25
        and plan["eos_weight"] == 0.0,
        "Mechanism scope",
    )
    require(plan["new_judge_calls"] == 0 and plan["no_retry"] is True, "No API or retries")
    require(
        plan["old_expression_gate"] == "FAIL"
        and plan["winner"] == "none"
        and plan["non_regression"] == "NOT_ESTABLISHED",
        "Historical claim ceiling",
    )
    require(
        plan["generation"] == {k: v for k, v in objective["generation"].items() if k != "steps"},
        "Generation protocol changed",
    )
    require(
        plan["factor_variants"] == ["actual", "common_slots", "same_memory", "random_pair"]
        and plan["factor_random_seed"] == 470016,
        "Factor controls",
    )
    require(
        plan["gradient_accumulation"] == "cpu_native_dtype_same_pair_order", "Accumulation policy"
    )
    expected_opt = dict(
        bridge_lr=objective["training"]["learning_rate"],
        bridge_weight_decay=objective["training"]["weight_decay"],
        base_lr=2e-7,
        base_weight_decay=0.0,
        max_grad_norm_per_family=objective["training"]["max_grad_norm"],
        base_optimizer="cpu_fp32_master_adafactor",
        bridge_optimizer="adamw",
        base_adafactor_step_sha256="b30d8fbb89724cc185720895fade90f5b1c844b1c6804f68315cea76395e4cfc",
    )
    require(plan["optimizer"] == expected_opt, "Optimizer policy")
    prior_seal = read(REPO / "provenance/pilots/v15_reader_factors_20261010/SOURCE_SEAL.json")
    for name, sha in prior_seal["source_hashes"].items():
        require(old.prior.digest(REPO / name) == sha, f"Historical source changed: {name}")
    return plan, objective, architecture, records


class Guard:
    def __init__(self, resources, output):
        self.resources, self.output = resources, output
        self.start = time.monotonic()
        self.gpu = old.ResourceGuard(resources, output)
        self.host_rows = []

    def __call__(self, phase, admission=False, forecast_bytes=0):
        row = self.gpu(phase, admission=admission)
        require(
            not [p for p in row["processes"] if p["pid"] != os.getpid()],
            "Another GPU client; stop own job only",
        )
        available, disk = backward.host_available(), shutil.disk_usage(self.output).free
        elapsed = time.monotonic() - self.start
        receipt = dict(
            phase=phase,
            available_bytes=available,
            disk_free_bytes=disk,
            forecast_bytes=forecast_bytes,
            elapsed_seconds=elapsed,
        )
        self.host_rows.append(receipt)
        with (self.output / "HOST_RESOURCES.jsonl").open("a") as stream:
            stream.write(json.dumps(receipt) + "\n")
        key = "host_admission_available_gib" if admission else "host_abort_available_gib"
        require(available >= self.resources[key] * GIB, "Host memory envelope")
        require(
            disk - forecast_bytes >= self.resources["disk_free_gib"] * GIB, "Forecast disk envelope"
        )
        require(elapsed <= self.resources["max_elapsed_seconds"], "Time envelope")
        return row


class LiveStore:
    """Only immutable token inputs; features always use current learner parameters."""

    def __init__(self, learner, tokenizer, records, guard):
        self.learner, self.base, self.tokenizer = learner, learner.base, tokenizer
        self.records, self.guard = records, guard
        self.renderings, self.contexts, self.parity = {}, {}, []
        for w, record in enumerate(records):
            for q, query in enumerate(record["queries"]):
                rows = [
                    old.render_case(
                        tokenizer,
                        query=query,
                        context=context,
                        renderer="native_chat",
                        cue="present",
                        information="query_only",
                    )
                    for context in record["contexts"]
                ]
                require(rows[0] == rows[1], "Factual side leaked into query prompt")
                self.renderings[w, q] = rows[0]
            for key in (0, 1, "reverse_0", "reverse_1", "unrelated"):
                if key == "unrelated":
                    text = old.prior.unrelated_context(record)
                else:
                    side = int(key[-1]) if isinstance(key, str) else key
                    text = old.canonical_facts(
                        record["contexts"][side], reverse=isinstance(key, str)
                    )
                self.contexts[w, key] = dict(
                    text=text, ids=tuple(tokenizer.encode(text, add_special_tokens=False))
                )

    def get(self, prefix):
        return self.learner.prefix(tuple(prefix))

    def write(self, bridge, world, key):
        hidden = self.learner.context(self.contexts[world, key]["ids"])
        return bridge.write_memory(
            hidden, torch.ones(hidden.shape[:2], dtype=torch.long, device=hidden.device)
        )

    @torch.no_grad()
    def encode(self, prefix):
        self.guard("live_prefix_parity")
        ids = torch.tensor([prefix], device=self.base.device)
        actual = self.base(ids, attention_mask=torch.ones_like(ids), use_cache=False).logits
        hidden = self.get(prefix)
        shared = self.learner.pipeline.readout(hidden, torch.zeros_like(hidden[:, -1:]).float())
        require(torch.equal(actual, shared.logits), "Current-base full-logit parity")
        self.parity.append(
            dict(
                prefix_sha256=old.prior._stable_hash(prefix),
                length=len(prefix),
                completed_step=self.learner.completed_steps,
                full_logits_exact=True,
            )
        )
        return hidden

    def feature_receipt(self):
        return dict(
            cache="tokens_only_no_hidden_or_KV_cache",
            renderings=[dict(world=w, query=q, **r) for (w, q), r in self.renderings.items()],
            contexts=[dict(world=w, key=key, **r) for (w, key), r in self.contexts.items()],
            native_parity=self.parity,
            tokenizer_vocabulary_sha256=old.prior._stable_hash(self.tokenizer.get_vocab()),
        )


@torch.no_grad()
def factor_panel(learner, store, plan, original_axis):
    bridge, pipe = learner.bridge, learner.pipeline
    operator = bridge.up.weight.detach().cpu().double()
    axis = (
        learner.base.lm_head.weight[5849].double() - learner.base.lm_head.weight[1476].double()
    ).cpu()
    left, right, spectrum = audit.spectral(operator, axis)
    rows, blocks = [], []
    for w in plan["worlds"]:
        bank = factors.memories(bridge, store, w, plan["factor_random_seed"])
        for even in (0, 2, 4, 6):
            store.guard(f"factor:{w}:{even}")
            features = []
            for q in (even, even + 1):
                rendered = store.renderings[w, q]
                require(rendered["candidate_ids"] == [1476, 5849], "Pinned no/yes head axis")
                ids = tuple(rendered["prompt_ids"])
                hidden = store.get(ids)
                question = pipe.query(hidden, prefix_ids=ids, span=old.bound_span(rendered))
                features.append((hidden, question))
            for variant in plan["factor_variants"]:
                traces = []
                for offset, (hidden, question) in enumerate(features):
                    for side, (memory, mask) in enumerate(bank[variant]):
                        delta, trace, hashes = factors.capture(bridge, question, memory, mask)
                        traces.append(trace)
                        scores = pipe.readout(hidden, delta).choice_scores([1476, 5849])[0].tolist()
                        rows.append(
                            dict(
                                world=w,
                                query=even + offset,
                                variant=variant,
                                side=side,
                                native_scores=scores,
                                trace_sha256=hashes,
                                memory_sha256=old.tensor_hash(memory),
                                memory_l2=audit.norm(memory),
                            )
                        )
                require(
                    torch.equal(traces[0]["gate"], traces[1]["gate"])
                    and torch.equal(traces[2]["gate"], traces[3]["gate"]),
                    "Question gate depends on memory",
                )
                odd_sign = 2 * store.records[w]["answers"][1][even + 1] - 1
                result = audit.audit_block(
                    traces,
                    operator,
                    axis,
                    left,
                    right,
                    bridge.max_delta_norm,
                    hasattr(bridge, "modulation_strength"),
                    odd_sign,
                )
                parts = audit.factors(torch.stack([t["d"] for t in traces]))
                result["original_head_axis_binding"] = audit.binding_condition(
                    float(parts["memory"] @ original_axis),
                    float(parts["interaction"] @ original_axis),
                    odd_sign,
                )
                result.update(
                    world=w,
                    even_query=even,
                    variant=variant,
                    binding_label_interpretation=variant == "actual" and even == 0,
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
    return dict(
        rows=rows,
        blocks=blocks,
        spectrum=spectrum,
        axis="current_native_head_promoted_to_FP64_not_native_logits",
        current_head_axis_sha256=tree_hash(axis),
        original_head_axis_sha256=tree_hash(original_axis),
        operator_sha256=tree_hash(operator),
    )


@torch.no_grad()
def inspect_step(learner, store, plan, contract, arm, step, output, original_axis):
    before_rng = tree_hash(rng_state())
    learner.bridge.eval()
    if step in contract["evaluation_steps"]:
        # Recompute ordinary outputs at every inspection, including the frozen control.
        for row in store.renderings.values():
            store.encode(tuple(row["prompt_ids"]))
        old.write_new(
            output / f"{arm}_{step}_evaluation.json", old.evaluate(learner.pipeline, store, step)
        )
    if step in contract["factor_steps"]:
        old.write_new(
            output / f"{arm}_{step}_factors.json", factor_panel(learner, store, plan, original_axis)
        )
    if step in contract["generation_steps"]:
        old.write_new(
            output / f"{arm}_{step}_generation.json",
            old.generate(learner.pipeline, store, plan, step),
        )
    learner.bridge.train()
    require(tree_hash(rng_state()) == before_rng, "Diagnostics must not change training RNG")
    # Diagnostics use many prefix shapes. Release their inactive allocation
    # cache before the next full backward; no tensors or numeric state change.
    gc.collect()
    torch.cuda.empty_cache()


def update_window(learner, store, routes, objective, arm, step, output, guard, replay=False):
    pairs = [(w, q) for w in range(2) for q in range(8)]
    learner.begin_window(pairs)
    rows, totals = [], {}
    terms_fn = backward.full_native_answer_terms if learner.full_update else old.native_answer_terms
    for w, q in pairs:
        guard(f"{arm}:{step}:{w}:{q}:before_backward")
        routes.rows = []
        loss, components = backward.pair_objective(
            learner.pipeline, store, w, q, objective["training"], 0.0, terms_fn
        )
        values = {
            key: float(value.detach()) for key, value in dict(loss=loss, **components).items()
        }
        receipt = learner.backward_pair((w, q), loss)
        rows.append(dict(world=w, query=q, components=values, routes=routes.rows, spill=receipt))
        for key, value in values.items():
            totals[key] = totals.get(key, 0.0) + value
        del loss, components
        guard(f"{arm}:{step}:{w}:{q}:spilled")
    guard(f"{arm}:{step}:before_update")
    receipt = learner.step()
    guard(f"{arm}:{step}:after_update")
    require(receipt["completed_step"] == step, "Progression step mismatch")
    result = dict(
        arm=arm,
        step=step,
        replay=replay,
        expected_pairs=16,
        pairs=rows,
        totals=totals,
        update=receipt,
    )
    name = f"{arm}_{step}_{'replay_' if replay else ''}update.json"
    old.write_new(output / name, result)
    print(
        json.dumps(
            dict(
                arm=arm,
                step=step,
                replay=replay,
                totals=totals,
                native_changed=sum(r["native_changed_elements"] for r in receipt["base_changes"]),
            )
        ),
        flush=True,
    )
    return result


def run_arm(
    base,
    tokenizer,
    records,
    plan,
    objective,
    architecture,
    phase,
    arm,
    output,
    checkpoints,
    guard,
    commit,
    manifest,
    cached_store=None,
):
    full = phase == "full" and arm == "full"
    name = arm if phase == "reader" else "query_modulated"
    contract = plan[f"{phase}_phase"]
    base.requires_grad_(full)
    base.train(full)
    if full:
        old.engine.enable_gradient_checkpointing(base)
    random.seed(plan["seed"])
    np.random.seed(plan["seed"])
    torch.manual_seed(plan["seed"])
    bridge = (
        create_reader(base.config.hidden_size, architecture["bridge"], name).to(base.device).float()
    )
    initial = old.prior.state_hash(bridge)
    require(
        initial == "97cb24a0bec75d9b00fa0c8b8e6056d27a21ee739fd0564752b6734e9b148fe4",
        "Fresh matched bridge initialization",
    )
    routes = backward.RouteGradients()
    learner = V15NativeLearner(
        base,
        bridge,
        full_update=full,
        optimizer_config=plan["optimizer"],
        boundary=16,
        observer=routes.observe,
    )
    handle = bridge.query_projection.register_forward_pre_hook(
        lambda _module, inputs: routes.observe("query_to_reader", inputs[0])
    )
    store = (
        cached_store if cached_store is not None else LiveStore(learner, tokenizer, records, guard)
    )
    metadata = dict(
        source_commit=commit,
        source_manifest_sha256=tree_hash(manifest),
        plan_sha256=old.prior.digest(PLAN),
        original_base_sha256=old.BASE_HASH,
        phase=phase,
        arm=arm,
    )
    checkpoints.mkdir(exist_ok=False)
    original_axis = (
        base.lm_head.weight[5849].detach().double() - base.lm_head.weight[1476].detach().double()
    ).cpu()
    inspect_step(learner, store, plan, contract, arm, 0, output, original_axis)
    saved, step_fingerprints = [], {}
    for step in range(1, contract["steps"] + 1):
        update_window(learner, store, routes, objective, arm, step, output, guard)
        if step in contract["checkpoint_steps"]:
            forecast = (
                (sum(p.numel() * 4 for p in learner.masters.values()) + GIB // 2)
                if full
                else GIB // 8
            )
            guard(f"{arm}:{step}:before_checkpoint", forecast_bytes=forecast)
            receipt = learner.save(checkpoints / f"step{step}.pt", metadata)
            receipt["sha256"] = old.prior.digest(checkpoints / receipt["path"])
            saved.append(receipt)
            step_fingerprints[step] = receipt["state_sha256"]
            old.write_new(output / f"{arm}_{step}_checkpoint.json", receipt)
            guard(f"{arm}:{step}:after_checkpoint")
        inspect_step(learner, store, plan, contract, arm, step, output, original_axis)
    final_base_hash = old.prior.state_hash(base)
    if not full:
        require(
            final_base_hash == old.BASE_HASH and all(p.grad is None for p in base.parameters()),
            "Frozen base changed",
        )
    old.write_new(output / f"{arm}_FEATURES.json", store.feature_receipt())
    resume = None
    handle.remove()
    if phase == "full":
        checkpoint = checkpoints / "step1.pt"
        receipt = saved[0]
        require(
            checkpoint.stat().st_size == receipt["bytes"]
            and old.prior.digest(checkpoint) == receipt["sha256"],
            "Resume file receipt mismatch",
        )
        # Drop the old owner before loading a 27-GiB master payload. Keep only the
        # same physical native model and bridge; restore validates and overwrites.
        del store, learner
        gc.collect()
        torch.cuda.empty_cache()
        guard(f"{arm}:before_resume_load")
        payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
        require(tree_hash(payload) == receipt["state_sha256"], "Resume state hash mismatch")
        learner = V15NativeLearner.restore(
            base, bridge, payload, expected_metadata=metadata, observer=routes.observe
        )
        del payload
        store = LiveStore(learner, tokenizer, records, guard)
        handle = bridge.query_projection.register_forward_pre_hook(
            lambda _module, inputs: routes.observe("query_to_reader", inputs[0])
        )
        guard(f"{arm}:after_resume_load")
        update_window(learner, store, routes, objective, arm, 2, output, guard, replay=True)
        actual = tree_hash(learner.payload(metadata))
        resumed_base = old.prior.state_hash(base)
        resume = dict(
            from_step=1,
            replay_step=2,
            state_sha256=actual,
            expected_state_sha256=step_fingerprints[2],
            native_base_sha256=resumed_base,
            expected_native_base_sha256=final_base_hash,
            exact=actual == step_fingerprints[2] and resumed_base == final_base_hash,
        )
        old.write_new(output / f"{arm}_RESUME.json", resume)
        require(resume["exact"], "Exact next-update replay failed; no tolerance relaxation")
        handle.remove()
    result = dict(
        arm=arm,
        reader=name,
        full_update=full,
        unique_updates=contract["steps"],
        executed_windows=contract["steps"] + int(phase == "full"),
        initial_bridge_sha256=initial,
        final_base_sha256=final_base_hash,
        final_bridge_sha256=old.prior.state_hash(bridge),
        checkpoints=saved,
        resume=resume,
        physical_base_parameters=len(learner.base_named),
        physical_bridge_parameters=len(learner.bridge_named),
    )
    del store, learner, bridge
    gc.collect()
    torch.cuda.empty_cache()
    return result


def execute(args):
    plan, objective, architecture, records = validate()
    seal, manifest = read(args.seal), identity()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    require(
        seal["source_commit"] == commit and seal["source_hashes"] == manifest,
        "Execution source seal",
    )
    require(
        not subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO, text=True
        ).strip(),
        "Tracked tree must be clean",
    )
    runtime = dict(
        python=platform.python_version(),
        torch=str(torch.__version__),
        transformers=transformers.__version__,
        cuda=torch.version.cuda,
    )
    require(runtime == architecture["expected_runtime"], "Pinned runtime changed")
    require(
        hashlib.sha256(inspect.getsource(Adafactor.step).encode()).hexdigest()
        == plan["optimizer"]["base_adafactor_step_sha256"],
        "Adafactor implementation changed",
    )
    require(
        args.output.resolve() != args.checkpoints.resolve()
        and not args.output.resolve().is_relative_to(args.checkpoints.resolve())
        and not args.checkpoints.resolve().is_relative_to(args.output.resolve()),
        "Checkpoints must be separate from publication outputs",
    )
    args.output.mkdir(parents=True, exist_ok=False)
    args.checkpoints.mkdir(parents=True, exist_ok=False)
    resources = plan[f"{args.phase}_resources"]
    guard = Guard(resources, args.output)
    try:
        forecast = 2 * 7_248_023_552 * 4 + GIB if args.phase == "full" else GIB
        guard("admission", admission=True, forecast_bytes=forecast)
        require(torch.cuda.device_count() == 1, "One visible CUDA device required")
        torch.set_num_threads(resources["cpu_threads"])
        torch.set_num_interop_threads(1)
        torch.set_float32_matmul_precision("highest")
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.cuda.set_per_process_memory_fraction(
            resources["allocator_cap_gib"] * GIB / torch.cuda.get_device_properties(0).total_memory
        )
        torch.cuda.reset_peak_memory_stats()
        old.write_new(
            args.output / "STARTED.json",
            dict(
                source_commit=commit,
                source_hashes=manifest,
                plan=plan,
                phase=args.phase,
                runtime=runtime,
                pid=os.getpid(),
                checkpoint_directory=str(args.checkpoints),
                seal_sha256=old.prior.digest(args.seal),
            ),
        )
        print(f"loading pinned Mistral: {args.phase}", flush=True)
        config = old.engine.ModelConfig(**architecture["model"])
        tokenizer = old.engine.load_tokenizer(config)
        require(tokenizer.eos_token_id == 2, "Pinned EOS")
        base = old.engine._load_hf_model(config).eval().requires_grad_(False).to("cuda")
        guard("base_loaded")
        require(old.prior.state_hash(base) == old.BASE_HASH, "Original base identity")
        cached = (
            old.Store(base, tokenizer, old.NativeWorkspaceReadout(base.lm_head), records, guard)
            if args.phase == "reader"
            else None
        )
        results = []
        for arm in plan[f"{args.phase}_phase"]["arms"]:
            require(
                old.prior.state_hash(base) == old.BASE_HASH, "Arm must begin from original base"
            )
            results.append(
                run_arm(
                    base,
                    tokenizer,
                    records,
                    plan,
                    objective,
                    architecture,
                    args.phase,
                    arm,
                    args.output,
                    args.checkpoints / arm,
                    guard,
                    commit,
                    manifest,
                    cached,
                )
            )
        require(identity() == manifest, "Source changed during execution")
        validate()
        guard("completed")
        report = dict(
            status="COMPLETED_ENGINEERING_PILOT",
            phase=args.phase,
            source_commit=commit,
            results=results,
            source_unchanged=True,
            elapsed_seconds=time.monotonic() - guard.start,
            peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(),
            peak_cuda_reserved_bytes=torch.cuda.max_memory_reserved(),
            minimum_sampled_device_free_bytes=min(r["free_bytes"] for r in guard.gpu.rows),
            minimum_sampled_host_available_bytes=min(r["available_bytes"] for r in guard.host_rows),
            old_expression_gate="FAIL",
            winner="none",
            semantic_promotion=False,
            non_regression="NOT_ESTABLISHED",
            judge_calls=0,
        )
        old.write_new(args.output / "REPORT.json", report)
        old.write_new(
            args.output / "FINISHED.json",
            dict(
                status=report["status"], report_sha256=old.prior.digest(args.output / "REPORT.json")
            ),
        )
        print(
            json.dumps(
                {
                    k: report[k]
                    for k in ("status", "phase", "elapsed_seconds", "peak_cuda_allocated_bytes")
                }
            ),
            flush=True,
        )
    except Exception as exc:
        old.write_new(
            args.output / "FAILED.json",
            dict(
                status="INCOMPLETE_NO_RETRY",
                type=type(exc).__name__,
                message=str(exc),
                traceback=traceback.format_exc(),
                elapsed_seconds=time.monotonic() - guard.start,
            ),
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--seal-output", type=Path)
    parser.add_argument("--phase", choices=("reader", "full"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--checkpoints", type=Path)
    parser.add_argument("--seal", type=Path)
    args = parser.parse_args()
    if args.dry_run:
        validate()
        print(
            json.dumps(
                dict(
                    status="PREPARED_NOT_RUN",
                    unique_windows=20,
                    executed_windows_with_replay=22,
                    generated_sequences=160,
                    judge_calls=0,
                )
            )
        )
    elif args.seal_output:
        validate()
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
        require(
            not subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO, text=True
            ).strip(),
            "Commit source before sealing",
        )
        old.write_new(
            args.seal_output, dict(source_commit=commit, source_hashes=identity(), plan=read(PLAN))
        )
    else:
        require(
            all((args.phase, args.output, args.checkpoints, args.seal)),
            "Explicit phase/output/checkpoints/seal required",
        )
        execute(args)


if __name__ == "__main__":
    main()
