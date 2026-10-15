#!/usr/bin/env python3
"""Frozen-weight V15 native readout, content/order and generation transport assay."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import torch
from torch.nn import functional as F

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts"), str(REPO / "src")]
import run_ft_beta_query_pool as previous  # noqa: E402
from run_ft_beta_learner_audit import write_new  # noqa: E402
from v14_precision_bridge_eval import _memories  # noqa: E402
from v15_assay_summary import (  # noqa: E402
    canonical_facts,
    parse_functional_answer,
    summarize_crossover,
)
from verify_ft_beta_query_pool import verify_bundle  # noqa: E402

from latent_workspace_ft_v10.answer_bank_generation import native_full_readout  # noqa: E402
from latent_workspace_ft_v10.v15_generation import generate_matched  # noqa: E402
from latent_workspace_ft_v10.v15_pipeline import NativeWorkspacePipeline  # noqa: E402
from latent_workspace_ft_v10.v15_readout import NativeWorkspaceReadout  # noqa: E402

prior, engine = previous.prior, previous.engine
PLAN = REPO / "configs/v15/READOUT_TRANSPORT_PLAN.json"
MODES = ("final", "mean_span")
ORDERS = ("original", "canonical", "canonical_reverse")


def validate():
    plan = json.loads(PLAN.read_text())
    expected_generation = {
        "worlds": [0, 1],
        "queries": [0, 1],
        "side": 0,
        "regimes": [
            {"id": "greedy", "seed": 0, "temperature": 0.0},
            {"id": "sample211", "seed": 211, "temperature": 0.7},
        ],
        "conditions": [
            "base",
            "base_inline",
            "final_intact",
            "final_twin",
            "final_zero",
            "mean_intact",
            "mean_twin",
            "mean_zero",
        ],
        "max_new_tokens": 64,
        "expected_sequences": 64,
        "parser": (
            "whole stripped answer yes/no, casefolded; lowercase compliance separate; "
            "length-truncated is incorrect"
        ),
        "history": "full-prefix recomputation; no KV cache or continuous state carry",
    }
    if plan["generation"] != expected_generation:
        raise ValueError("Frozen generation contract changed")
    if (
        plan["model_parent"] != "configs/v14/PRECISION_BRIDGE_PLAN.json"
        or plan["mean_reduction"] != "CPU FP32, matching retained checkpoint training"
        or plan["claims"]
        != {
            "winner": "none",
            "semantic_promotion": False,
            "non_regression": "NOT_ESTABLISHED",
            "quality_judging": "NOT_RUN",
        }
    ):
        raise ValueError("Model/readout/claim contract changed")
    _, parent, records, split = previous.validate_contract()
    if (
        plan["format"] != "v15-native-readout-transport-v1"
        or plan["worlds"] != [0, 1]
        or plan["queries"] != list(range(8))
        or plan["modes"] != list(MODES)
        or plan["orders"] != list(ORDERS)
        or plan["optimizer_steps"] != 0
        or plan["checkpoint_step"] != 256
        or plan["max_delta_norm"] != parent["bridge"]["max_delta_norm"]
        or plan["generation"]["expected_sequences"] != 64
    ):
        raise ValueError("V15 bounded contract changed")
    if plan["resources"] != json.loads(previous.PLAN.read_text())["resources"]:
        raise ValueError("Resource contract drift")
    old = verify_bundle(REPO / plan["predecessor_bundle"])
    if old["status"] != "VERIFIED_RECEIPTS":
        raise RuntimeError("Predecessor verification failed")
    return plan, parent, records, split


def sources(parent):
    identities = previous.source_identity(parent)
    identities.update(
        {
            str(path.relative_to(REPO)): prior.digest(path)
            for path in [
                PLAN,
                REPO / "scripts/run_v15_readout_transport.py",
                REPO / "scripts/v15_assay_summary.py",
                REPO / "scripts/verify_ft_beta_query_pool.py",
                REPO / "scripts/verify_ft_beta_learner_audit.py",
                REPO / "docs/v15/PLAN.md",
                *[
                    REPO / f"src/latent_workspace_ft_v10/{name}.py"
                    for name in (
                        "v15_readout",
                        "v15_pipeline",
                        "v15_generation",
                        "answer_bank_generation",
                    )
                ],
            ]
        }
    )
    return identities


def scores(tensor):
    values = tensor.detach().double().reshape(-1).tolist()
    if len(values) != 2:
        raise ValueError("Expected two scores")
    gap = values[1] - values[0]
    return {"scores": values, "gap": gap, "prediction": None if gap == 0 else int(gap > 0)}


@torch.no_grad()
def transport(base, candidate):
    # Native logits, probabilities diagnosed in FP64. Exact zeros remain zeros.
    b, c = base.last_logits[0].double(), candidate.last_logits[0].double()
    lb, lc = b.log_softmax(-1), c.log_softmax(-1)
    pb, pc = lb.exp(), lc.exp()
    top_b, top_c = int(b.argmax()), int(c.argmax())
    return {
        "kl_base_to_candidate": float((pb * (lb - lc)).sum()),
        "total_variation": float((pb - pc).abs().sum() / 2),
        "max_abs_logit_change": float((b - c).abs().max()),
        "logit_change_l2": float((b - c).norm()),
        "base_top1": top_b,
        "candidate_top1": top_c,
        "base_top1_probability": float(pb[top_b]),
        "candidate_top1_probability": float(pc[top_c]),
        "base_top1_candidate_probability": float(pc[top_b]),
    }


class AssayStore(previous.CUDAStore):
    @torch.no_grad()
    def ordered_context(self, world, side, order):
        if order == "original":
            return self.context(world, side)
        text = canonical_facts(
            self.records[world]["contexts"][side], reverse=order == "canonical_reverse"
        )
        key = world, f"{order}_{side}"
        if key not in self.context_cache:
            self.guard(f"capture:{world}:{order}:{side}")
            ids = torch.tensor(
                [self.tokenizer.encode(text, add_special_tokens=False)], device=self.device
            )
            with torch.autocast("cuda", dtype=torch.bfloat16):
                hidden = self.boundary.encode(ids, torch.ones_like(ids), 16)
            self.context_cache[key] = hidden.detach().cpu()
        return self.context_cache[key]


@torch.no_grad()
def memories(bridge, store, world, device):
    old = _memories(bridge, store, world, device)
    result = {
        "zero": old["zero"],
        "fixed_carrier": old["fixed_carrier"],
        "unrelated": old["unrelated"],
        **{f"norm_matched_random_{s}": old[("norm_matched_random", s)] for s in (0, 1)},
    }
    for order in ORDERS:
        for side in (0, 1):
            context = store.ordered_context(world, side, order).to(device).float()
            result[f"{order}_{side}"] = bridge.write_memory(
                context, torch.ones(context.shape[:2], device=device)
            )
    context = store.context(world, "different_schema").to(device).float()
    result["different_schema"] = bridge.write_memory(
        context, torch.ones(context.shape[:2], device=device)
    )
    return result


@torch.no_grad()
def evaluate(pipelines, store, readout, guard):
    rows, exact = [], 0
    for mode, pipe in pipelines.items():
        for world in range(2):
            bank = memories(pipe.bridge, store, world, store.device)
            for q in range(8):
                guard(f"crossover:{mode}:{world}:{q}")
                hidden = store.query(world, q).to(store.device)
                prefix = store.prefix(store.features[world], q)
                zero = torch.zeros_like(hidden[:, -1:]).float()
                base = readout(hidden, zero)
                base_native = scores(base.choice_scores(store.candidate_ids))
                base_fp32 = scores(readout.legacy_fp32_choices(hidden, zero, store.candidate_ids))
                for key, (memory, mask) in bank.items():
                    out = pipe(hidden, memory, mask, prefix_ids=prefix, span=store.spans[world, q])
                    old_logits, _ = native_full_readout(hidden, out.delta, readout.head)
                    if not torch.equal(old_logits, out.readout.logits):
                        raise RuntimeError("Shared/historical native full-logit mismatch")
                    exact += 1
                    if key == "zero" and (
                        torch.count_nonzero(out.delta)
                        or not torch.equal(base.logits, out.readout.logits)
                    ):
                        raise RuntimeError("Written-zero parity failed")
                    rows.append(
                        {
                            "mode": mode,
                            "world": world,
                            "query": q,
                            "memory_key": key,
                            "labels": [store.records[world]["answers"][s][q] for s in (0, 1)],
                            "affected": store.records[world]["affected"][q],
                            "native": scores(out.readout.choice_scores(store.candidate_ids)),
                            "fp32": scores(
                                readout.legacy_fp32_choices(hidden, out.delta, store.candidate_ids)
                            ),
                            "base_native": base_native,
                            "base_fp32": base_fp32,
                            "transport": transport(base, out.readout),
                            "delta_l2": float(out.delta.norm()),
                            "native_applied_delta_l2": float(out.readout.applied_delta.norm()),
                        }
                    )
    return {
        "rows": rows,
        "summary": summarize_crossover(rows),
        "shared_historical_native_full_logit_exact_checks": exact,
        "zero_checks": 32,
    }


def gradient_gate(pipelines, store, readout):
    result = {}
    for mode, pipe in pipelines.items():
        before = prior.state_hash(pipe.bridge)
        pipe.bridge.train()
        mode_rows = []
        for q in (0, 1):
            context = store.context(0, 0).to(store.device).float()
            memory, mask = pipe.bridge.write_memory(
                context, torch.ones(context.shape[:2], device=store.device)
            )
            hidden = store.query(0, q).to(store.device)
            out = pipe(
                hidden,
                memory,
                mask,
                prefix_ids=store.prefix(store.features[0], q),
                span=store.spans[0, q],
            )
            label = store.records[0]["answers"][0][q]
            losses = {
                "native_two_choice_ce": F.cross_entropy(
                    out.readout.choice_scores(store.candidate_ids),
                    torch.tensor([label], device=store.device),
                ),
                "native_full_vocab_ce": out.readout.cross_entropy(
                    torch.tensor([store.candidate_ids[label]], device=store.device)
                ),
            }
            parameters = list(pipe.bridge.named_parameters())
            norms = {}
            for name, loss in losses.items():
                gradients = torch.autograd.grad(
                    loss, [p for _, p in parameters], retain_graph=True, allow_unused=False
                )
                if not all(bool(torch.isfinite(g).all()) for g in gradients) or not any(
                    bool(torch.count_nonzero(g)) for g in gradients
                ):
                    raise RuntimeError("Native surrogate gradient path disconnected/nonfinite")
                norms[name] = {
                    "loss": float(loss.detach()),
                    "parameter_gradient_l2": {
                        n: float(g.double().norm())
                        for (n, _), g in zip(parameters, gradients, strict=True)
                    },
                }
            with torch.no_grad():
                pipe.bridge.eval()
                repeated = pipe(
                    hidden,
                    memory.detach(),
                    mask,
                    prefix_ids=store.prefix(store.features[0], q),
                    span=store.spans[0, q],
                )
                if not torch.equal(out.readout.logits, repeated.readout.logits):
                    raise RuntimeError("Training/evaluation shared forward mismatch")
            mode_rows.append(
                {"world": 0, "query": q, "losses": norms, "native_train_eval_logits_exact": True}
            )
            pipe.bridge.train()
        pipe.bridge.eval()
        if prior.state_hash(pipe.bridge) != before or any(
            p.grad is not None for p in pipe.bridge.parameters()
        ):
            raise RuntimeError("No-update gradient diagnostic mutated bridge")
        result[mode] = {
            "rows": mode_rows,
            "unchanged": True,
            "optimizer_steps": 0,
            "scope": "PyTorch BF16 cast surrogate-gradient connectivity; not finite-step learning",
        }
    return result


class GenerationBackend:
    def __init__(self, base, readout, pipelines, banks, span):
        self.base, self.shared, self.pipelines, self.banks, self.span = (
            base,
            readout,
            pipelines,
            banks,
            span,
        )
        self.parity_checks = 0

    @torch.no_grad()
    def encode(self, prefix):
        ids = torch.tensor([prefix], device=self.base.device)
        return self.base.model(
            ids, attention_mask=torch.ones_like(ids), use_cache=False
        ).last_hidden_state

    def delta(self, condition, hidden, prefix):
        family, control = condition.split("_", 1)
        mode = "final" if family == "final" else "mean_span"
        key = {"intact": "original_0", "twin": "original_1", "zero": "zero"}[control]
        memory, mask = self.banks[mode][key]
        delta, _ = self.pipelines[mode].delta(
            hidden, memory, mask, prefix_ids=prefix, span=self.span
        )
        return delta

    def readout(self, hidden, delta):
        result = self.shared(hidden, delta)
        old, _ = native_full_readout(hidden, delta, self.shared.head)
        if not torch.equal(result.logits, old):
            raise RuntimeError("Generation shared/historical native parity failed")
        self.parity_checks += 1
        return result


@torch.no_grad()
def generation_probe(base, readout, pipelines, store, plan, guard):
    rows, receipts = [], []
    spec = plan["generation"]
    eos = base.generation_config.eos_token_id
    eos = {eos} if isinstance(eos, int) else set(eos)
    for world in spec["worlds"]:
        banks = {m: memories(p.bridge, store, world, store.device) for m, p in pipelines.items()}
        for q in spec["queries"]:
            prefix = list(store.prefix(store.features[world], q))
            rendered = engine._functional_elicitation_query(
                store.records[world]["queries"][q], store.data_config
            )
            inline = store.tokenizer.encode(
                store.records[world]["contexts"][0] + store.data_config.prompt_separator + rendered,
                add_special_tokens=False,
            )
            prompts = {c: inline if c == "base_inline" else prefix for c in spec["conditions"]}
            for regime in spec["regimes"]:
                backend = GenerationBackend(base, readout, pipelines, banks, store.spans[world, q])
                group, receipt = generate_matched(
                    case_id=f"w{world}_q{q}",
                    prompts=prompts,
                    regime=regime,
                    max_new_tokens=spec["max_new_tokens"],
                    eos_token_ids=eos,
                    backend=backend,
                    decode=lambda ids: store.tokenizer.decode(ids, skip_special_tokens=True),
                    guard=lambda: guard(f"generation:{world}:{q}:{regime['id']}"),
                )
                for row in group:
                    target_side = 1 if row["condition"].endswith("_twin") else 0
                    target = store.records[world]["answers"][target_side][q]
                    parsed = parse_functional_answer(row["answer"])
                    row.update(
                        world=world,
                        query=q,
                        target_label=target,
                        parsed_answer=parsed,
                        lowercase_compliant=row["answer"].strip() in ("yes", "no"),
                        strict_correct=parsed == target and row["finish_reason"] == "eos",
                    )
                    rows.append(row)
                receipts.append(
                    {
                        "world": world,
                        "query": q,
                        "regime": regime["id"],
                        "shared_historical_native_checks": backend.parity_checks,
                        **receipt,
                    }
                )
                print(f"generation w{world} q{q} {regime['id']} complete", flush=True)
    if len(rows) != spec["expected_sequences"]:
        raise RuntimeError("Generation denominator mismatch")
    summary = {
        c: {
            "sequences": len(selected := [r for r in rows if r["condition"] == c]),
            "strict_correct": sum(r["strict_correct"] for r in selected),
            "unparseable": sum(r["parsed_answer"] is None for r in selected),
            "length_truncated": sum(r["finish_reason"] == "length" for r in selected),
            "lowercase_compliant": sum(r["lowercase_compliant"] for r in selected),
        }
        for c in spec["conditions"]
    }
    return {
        "rows": rows,
        "receipts": receipts,
        "summary": summary,
        "quality_claim": False,
        "kv_cache_used": False,
        "scope": "exposed functional transport probe",
    }


def execute(checkpoint_root, output):
    import transformers

    plan, parent, records, split = validate()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True).strip():
        raise RuntimeError("Formal source must be clean")
    runtime = {
        "python": sys.version.split()[0],
        "torch": str(torch.__version__),
        "transformers": transformers.__version__,
        "cuda": torch.version.cuda,
    }
    if runtime != parent["expected_runtime"]:
        raise RuntimeError("Pinned runtime mismatch")
    output.mkdir(parents=True, exist_ok=False)
    guard = previous.ResourceGuard(plan["resources"], output)
    start = time.monotonic()
    try:
        admission = guard("admission", admission=True)
        source_hashes = sources(parent)
        write_new(
            output / "STARTED.json",
            {
                "source_commit": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
                ).strip(),
                "source_hashes": source_hashes,
                "runtime": runtime,
                "plan": plan,
                "split": split,
                "admission": admission,
            },
        )
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        torch.set_float32_matmul_precision("highest")
        torch.backends.cuda.matmul.allow_tf32 = False
        if torch.cuda.device_count() != 1:
            raise RuntimeError("One CUDA device required")
        torch.cuda.set_per_process_memory_fraction(
            float(
                plan["resources"]["allocator_cap_gib"]
                * previous.GIB
                / torch.cuda.get_device_properties(0).total_memory
            )
        )
        torch.cuda.reset_peak_memory_stats()
        config = engine.ModelConfig(**parent["model"])
        tokenizer = engine.load_tokenizer(config)
        print("loading frozen pinned original for V15 native transport", flush=True)
        base = engine._load_hf_model(config).eval().requires_grad_(False).to("cuda")
        base_before = prior.state_hash(base)
        old_report = json.loads((REPO / plan["predecessor_bundle"] / "raw/REPORT.json").read_text())
        if base_before != old_report["base_state_sha256_after"]:
            raise RuntimeError("Base identity mismatch")
        boundary = previous.FunctionalBoundaryAdapter(base)
        adapter = previous.MistralPrecisionBridgeAdapter(boundary)
        data_config = engine.DataConfig(
            **json.loads((REPO / parent["data_config_parent"]).read_text())["data"]
        )
        dataset = engine.JsonlFineTuningDataset(
            [str(REPO / parent["data"]["train"]["path"])], tokenizer, data_config
        )
        store = AssayStore(
            records,
            dataset,
            tokenizer,
            boundary,
            adapter,
            torch.device("cuda"),
            data_config=data_config,
            guard=guard,
        )
        store.prepare("V15 matched prefixes")
        fact_receipts = []
        for w in range(2):
            for order in ORDERS:
                for side in (0, 1):
                    store.ordered_context(w, side, order)
                    text = (
                        records[w]["contexts"][side]
                        if order == "original"
                        else canonical_facts(
                            records[w]["contexts"][side], reverse=order == "canonical_reverse"
                        )
                    )
                    fact_receipts.append(
                        {
                            "world": w,
                            "side": side,
                            "order": order,
                            "text": text,
                            "token_ids": tokenizer.encode(text, add_special_tokens=False),
                        }
                    )
        write_new(
            output / "FEATURES.json",
            {
                "native_gates": store.native_gates,
                "spans": store.span_receipts,
                "facts": fact_receipts,
                "candidate_ids": store.candidate_ids,
                "mean_reduction": plan["mean_reduction"],
            },
        )
        readout = NativeWorkspaceReadout(base.lm_head)
        pipelines, checkpoint_receipts = {}, {}
        for mode in MODES:
            receipt = next(
                x
                for x in old_report["results"][mode]["checkpoints"]
                if x["path"] == f"{mode}_step256.pt"
            )
            path = checkpoint_root / receipt["path"]
            if path.stat().st_size != receipt["bytes"] or prior.digest(path) != receipt["sha256"]:
                raise RuntimeError("Retained checkpoint bytes changed")
            payload = torch.load(path, map_location="cpu", weights_only=True)
            if (
                payload["mode"] != mode
                or payload["step"] != 256
                or payload["base_revision"] != parent["model"]["revision"]
            ):
                raise RuntimeError("Checkpoint metadata mismatch")
            bridge = (
                previous.PrecisionAwareWorkspaceBridge(base.config.hidden_size, **parent["bridge"])
                .to("cuda")
                .float()
                .eval()
            )
            bridge.load_state_dict(payload["state_dict"], strict=True)
            if prior.state_hash(bridge) != old_report["results"][mode]["final_state_sha256"]:
                raise RuntimeError("Bridge state identity mismatch")
            pipelines[mode] = NativeWorkspacePipeline(bridge, readout, mode)
            checkpoint_receipts[mode] = receipt
        guard("loaded")
        gradients = gradient_gate(pipelines, store, readout)
        write_new(output / "GRADIENTS.json", gradients)
        crossover = evaluate(pipelines, store, readout, guard)
        write_new(output / "CROSSOVER.json", crossover)
        print("crossover complete; beginning functional native generation", flush=True)
        generated = generation_probe(base, readout, pipelines, store, plan, guard)
        write_new(output / "GENERATION.json", generated)
        after = prior.state_hash(base)
        if after != base_before or any(p.grad is not None for p in base.parameters()):
            raise RuntimeError("Frozen base changed")
        for mode, pipe in pipelines.items():
            if (
                prior.state_hash(pipe.bridge) != old_report["results"][mode]["final_state_sha256"]
                or prior.digest(checkpoint_root / checkpoint_receipts[mode]["path"])
                != checkpoint_receipts[mode]["sha256"]
            ):
                raise RuntimeError("Bridge/checkpoint changed")
        if source_hashes != sources(parent):
            raise RuntimeError("Source identity changed")
        guard("completed")
        report = {
            "status": "COMPLETED_V15_ENGINEERING_ASSAY",
            "optimizer_steps": 0,
            "base_state_sha256_before": base_before,
            "base_state_sha256_after": after,
            "base_unchanged": True,
            "checkpoints": checkpoint_receipts,
            "bridges_unchanged": True,
            "source_unchanged": True,
            "crossover_rows": len(crossover["rows"]),
            "generation_sequences": len(generated["rows"]),
            "generation_summary": generated["summary"],
            "elapsed_seconds": time.monotonic() - start,
            "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated(),
            "peak_cuda_reserved_bytes": torch.cuda.max_memory_reserved(),
            "sampled_own_process_peak_bytes": max(
                p["bytes"] for r in guard.rows for p in r["processes"] if p["pid"] == r["own_pid"]
            ),
            "minimum_sampled_device_free_bytes": min(r["free_bytes"] for r in guard.rows),
            **plan["claims"],
        }
        write_new(output / "REPORT.json", report)
        return {
            k: report[k]
            for k in (
                "status",
                "elapsed_seconds",
                "crossover_rows",
                "generation_sequences",
                "peak_cuda_allocated_bytes",
            )
        }
    except Exception as exc:
        write_new(
            output / "FAILED.json",
            {"status": "INCOMPLETE", "exception_type": type(exc).__name__, "message": str(exc)},
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.dry_run:
        validate()
        print(json.dumps({"status": "PREPARED_NOT_RUN"}))
    elif args.output is None or args.checkpoint_root is None:
        parser.error("--output and --checkpoint-root required")
    else:
        print(json.dumps(execute(args.checkpoint_root.resolve(), args.output.resolve())))
