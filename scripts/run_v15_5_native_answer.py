#!/usr/bin/env python3
"""Eight-update native answer/completion engineering comparison; no model API calls."""

from __future__ import annotations

import argparse
import gc
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import torch
from torch.nn import functional as F

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "src"), str(REPO / "scripts")]
import run_v14_precision_bridge as prior  # noqa: E402
from run_ft_beta_learner_audit import write_new  # noqa: E402
from run_ft_beta_query_pool import GIB, ResourceGuard, tensor_hash  # noqa: E402
from run_v15_readout_transport import transport  # noqa: E402
from v13_task_fixture import symbolic_oracle  # noqa: E402
from v15_assay_summary import canonical_facts, parse_functional_answer  # noqa: E402
from v15_cue_contract import render_case  # noqa: E402

from latent_workspace_ft_v10 import engine  # noqa: E402
from latent_workspace_ft_v10.model_binding import FunctionalBoundaryAdapter  # noqa: E402
from latent_workspace_ft_v10.precision_bridge import PrecisionAwareWorkspaceBridge  # noqa: E402
from latent_workspace_ft_v10.reader_query import QuestionSpan  # noqa: E402
from latent_workspace_ft_v10.v15_5_learner import (  # noqa: E402
    native_answer_terms,
    validate_optimizer_ownership,
)
from latent_workspace_ft_v10.v15_generation import generate_matched  # noqa: E402
from latent_workspace_ft_v10.v15_pipeline import NativeWorkspacePipeline  # noqa: E402
from latent_workspace_ft_v10.v15_readout import NativeWorkspaceReadout  # noqa: E402

PLAN = REPO / "configs/v15_5/NATIVE_ANSWER_PLAN.json"
BASE_HASH = "54d161755862ebf00d8acbca083d5f290a5de44d33af82ca885f3bd8f9c94312"


def validate():
    plan = json.loads(PLAN.read_text())
    parent = json.loads((REPO / plan["parent_plan"]).read_text())
    train, _, _ = prior.validate_plan(parent)
    if (
        plan["arms"]
        != [
            {"id": "native_answer", "eos_weight": 0.0},
            {"id": "native_answer_eos", "eos_weight": 1.0},
        ]
        or plan["world_indices"] != [0, 1]
        or plan["query_indices"] != list(range(8))
        or plan["reader"] != "final"
        or (plan["renderer"], plan["cue"]) != ("native_chat", "present")
        or plan["training"]["steps"] != 8
        or plan["checkpoint_steps"] != [4, 8]
        or plan["evaluation_steps"] != [0, 1, 8]
        or plan["generation"]["steps"] != [0, 8]
        or plan["generation"]["max_new_tokens"] != 16
        or plan["generation"]["eos_token_id"] != 2
        or plan["old_expression_gate"] != "FAIL"
    ):
        raise ValueError("Bounded native learner contract changed")
    for key in (
        "seed",
        "learning_rate",
        "weight_decay",
        "max_grad_norm",
        "donor_margin",
        "direction_weight",
        "stability_weight",
        "unrelated_weight",
        "residual_penalty",
    ):
        if plan["training"][key] != parent["training"][key]:
            raise ValueError(f"Unmatched parent optimizer/regularizer: {key}")
    if plan["resources"] != {
        "admission_free_gib": 20,
        "allocator_cap_gib": 18,
        "abort_free_gib": 4,
        "cpu_threads": 2,
    }:
        raise ValueError("Resource policy changed")
    if prior.digest(REPO / plan["judge_summary"]["path"]) != plan["judge_summary"]["sha256"]:
        raise ValueError("Motivating diagnostic evidence changed")
    records = train[:2]
    for record in records:
        for side, context in enumerate(record["contexts"]):
            for q, query in enumerate(record["queries"]):
                expected = symbolic_oracle(context, query)
                if expected != record["answers"][side][q]:
                    raise ValueError("Training label fails independent symbolic oracle")
                for reverse in (False, True):
                    if symbolic_oracle(canonical_facts(context, reverse), query) != expected:
                        raise ValueError("Fact serialization changed graph truth")
        if [a != b for a, b in zip(*record["answers"], strict=True)] != [True, True] + [False] * 6:
            raise ValueError("Affected-pair denominator changed")
        for labels in record["answers"]:
            if labels.count(0) != 4 or labels.count(1) != 4:
                raise ValueError("Reciprocal label balance changed")
    return plan, parent, records


def sources():
    names = subprocess.check_output(
        ["git", "ls-files", "src", "scripts", "tests"], cwd=REPO, text=True
    ).splitlines()
    names = [name for name in names if name.endswith(".py")]
    names += [
        "configs/v15_5/NATIVE_ANSWER_PLAN.json",
        "docs/v15_5/NATIVE_ANSWER_LEARNER.md",
        "configs/v14/PRECISION_BRIDGE_PLAN.json",
        "pyproject.toml",
        "data/v10/functional_train.jsonl",
        "data/v10/functional_eval.jsonl",
    ]
    return {name: prior.digest(REPO / name) for name in sorted(set(names))}


def bound_span(rendering):
    values = dict(rendering["span"])
    values["token_indices"] = tuple(values["token_indices"])
    values["prefix_ids"] = tuple(values["prefix_ids"])
    return QuestionSpan(**values)


class Store:
    def __init__(self, base, tokenizer, readout, records, guard):
        self.base, self.tokenizer, self.readout = base, tokenizer, readout
        self.records, self.guard = records, guard
        self.boundary = FunctionalBoundaryAdapter(base)
        self.prefixes, self.contexts, self.renderings = {}, {}, {}
        self.parity = []
        self.context_receipts = {}
        for w, record in enumerate(records):
            for q, query in enumerate(record["queries"]):
                rendered = render_case(
                    tokenizer,
                    query=query,
                    context=record["contexts"][0],
                    renderer="native_chat",
                    cue="present",
                    information="query_only",
                )
                other = render_case(
                    tokenizer,
                    query=query,
                    context=record["contexts"][1],
                    renderer="native_chat",
                    cue="present",
                    information="query_only",
                )
                if rendered != other:
                    raise RuntimeError("Factual side leaked into query-only rendering")
                self.renderings[w, q] = rendered
                self.get(tuple(rendered["prompt_ids"]))
                for token in rendered["candidate_ids"]:
                    self.get(tuple(rendered["prompt_ids"]) + (token,))
            for key in (0, 1, "reverse_0", "reverse_1", "unrelated"):
                self.context(w, key)

    @torch.no_grad()
    def encode(self, prefix):
        self.guard("prefix_capture")
        ids = torch.tensor([prefix], device=self.base.device)
        mask = torch.ones_like(ids)
        actual = self.base(ids, attention_mask=mask, use_cache=False).logits
        hidden = self.base.model(ids, attention_mask=mask, use_cache=False).last_hidden_state
        shared = self.readout(hidden, torch.zeros_like(hidden[:, -1:]).float())
        if not torch.equal(actual, shared.logits):
            raise RuntimeError("Ordinary/shared full-sequence native parity failed")
        self.parity.append(
            {
                "prefix_sha256": prior._stable_hash(prefix),
                "length": len(prefix),
                "full_logits_exact": True,
            }
        )
        return hidden

    @torch.no_grad()
    def get(self, prefix):
        if prefix not in self.prefixes:
            self.prefixes[prefix] = self.encode(prefix).detach().cpu()
        return self.prefixes[prefix].to(self.base.device)

    @torch.no_grad()
    def context(self, world, key):
        coordinate = world, key
        if coordinate not in self.contexts:
            self.guard("context_capture")
            if key == "unrelated":
                text = prior.unrelated_context(self.records[world])
            else:
                side = int(key[-1]) if isinstance(key, str) else key
                text = canonical_facts(
                    self.records[world]["contexts"][side], reverse=isinstance(key, str)
                )
            tokens = self.tokenizer.encode(text, add_special_tokens=False)
            ids = torch.tensor([tokens], device=self.base.device)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                hidden = self.boundary.encode(ids, torch.ones_like(ids), 16)
            self.contexts[coordinate] = hidden.detach().cpu()
            self.context_receipts[str(coordinate)] = {
                "text": text,
                "ids": tokens,
                "tensor_sha256": tensor_hash(hidden),
            }
        return self.contexts[coordinate].to(self.base.device)

    def write(self, bridge, world, key):
        context = self.context(world, key)
        return bridge.write_memory(
            context, torch.ones(context.shape[:2], device=context.device, dtype=torch.long)
        )

    def feature_receipt(self):
        return {
            "renderings": [{"world": w, "query": q, **r} for (w, q), r in self.renderings.items()],
            "contexts": self.context_receipts,
            "native_parity": self.parity,
            "prefix_tensor_sha256": {
                prior._stable_hash(k): tensor_hash(v) for k, v in self.prefixes.items()
            },
            "cached_tensor_bytes": sum(
                t.numel() * t.element_size()
                for t in (*self.prefixes.values(), *self.contexts.values())
            ),
            "tokenizer_vocabulary_sha256": prior._stable_hash(self.tokenizer.get_vocab()),
            "tokenizer_special_tokens": self.tokenizer.special_tokens_map,
        }


def pair_objective(pipe, store, w, q, contract, eos_weight):
    row = store.renderings[w, q]
    prefix, candidates, span = tuple(row["prompt_ids"]), row["candidate_ids"], bound_span(row)
    hidden = store.get(prefix)
    labels = [store.records[w]["answers"][side][q] for side in (0, 1)]
    terms = []
    for side, label in enumerate(labels):
        memory, mask = store.write(pipe.bridge, w, side)
        token = candidates[label]
        terms.append(
            native_answer_terms(
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
    memory, mask = store.write(pipe.bridge, w, "unrelated")
    unrelated = pipe(hidden, memory, mask, prefix_ids=prefix, span=span)
    with torch.no_grad():
        base = pipe.readout(hidden, torch.zeros_like(hidden[:, -1:]).float())
    scores = [t.answer_output.readout.choice_scores(candidates)[0] for t in terms]
    gap = [v[1] - v[0] for v in scores]
    difference = gap[1] - gap[0]
    donor = (2 * labels[1] - 1) * difference
    other = unrelated.readout.choice_scores(candidates)[0]
    baseline = base.choice_scores(candidates)[0]
    affected = labels[0] != labels[1]
    zero = difference * 0
    # Accumulate one world/query pair at a time; each term retains its own
    # complete-batch denominator, including the affected/unaffected subsets.
    components = {
        "answer_ce": (terms[0].answer_ce + terms[1].answer_ce) / 32,
        "eos_ce": (terms[0].eos_ce + terms[1].eos_ce) / 32,
        "donor_hinge": F.relu(contract["donor_margin"] - donor) / 4 if affected else zero,
        "unaffected_gap_square": difference.square() / 12 if not affected else zero,
        "unrelated_gap_square": ((other[1] - other[0]) - (baseline[1] - baseline[0])).square() / 16,
        "residual_norm_square": sum(
            out.delta.square().sum()
            for out in (terms[0].answer_output, terms[1].answer_output, unrelated)
        )
        / 48,
    }
    loss = (
        components["answer_ce"]
        + eos_weight * components["eos_ce"]
        + contract["direction_weight"] * components["donor_hinge"]
        + contract["stability_weight"] * components["unaffected_gap_square"]
        + contract["unrelated_weight"] * components["unrelated_gap_square"]
        + contract["residual_penalty"] * components["residual_norm_square"]
    )
    return loss, components


@torch.no_grad()
def evaluate(pipe, store, step):
    rows = []
    mapping = {
        "intact": 0,
        "twin": 1,
        "reverse_intact": "reverse_0",
        "reverse_twin": "reverse_1",
        "unrelated": "unrelated",
        "zero": 0,
    }
    for w in range(2):
        memories = {name: store.write(pipe.bridge, w, key) for name, key in mapping.items()}
        memories["zero"] = (torch.zeros_like(memories["zero"][0]), memories["zero"][1])
        for q in range(8):
            row = store.renderings[w, q]
            prefix, candidates, span = (
                tuple(row["prompt_ids"]),
                row["candidate_ids"],
                bound_span(row),
            )
            hidden = store.get(prefix)
            baseline = pipe.readout(hidden, torch.zeros_like(hidden[:, -1:]).float())
            selected = baseline.choice_scores(candidates)[0]
            fp32 = pipe.readout.legacy_fp32_choices(
                hidden, torch.zeros_like(hidden[:, -1:]).float(), candidates
            )[0]
            axis = pipe.readout.head.weight[candidates[1]].double() - (
                pipe.readout.head.weight[candidates[0]].double()
            )
            reach = float(axis.norm()) * pipe.bridge.max_delta_norm
            for name, (memory, mask) in memories.items():
                out = pipe(hidden, memory, mask, prefix_ids=prefix, span=span)
                scores = out.readout.choice_scores(candidates)[0]
                exact = torch.equal(out.readout.logits, baseline.logits)
                if name == "zero" or step == 0:
                    if not exact or bool(torch.count_nonzero(out.delta)):
                        raise RuntimeError("Initial/written-zero path is not an exact native noop")
                side = (
                    mapping[name]
                    if name in ("intact", "twin")
                    else (int(mapping[name][-1]) if name.startswith("reverse_") else None)
                )
                label = store.records[w]["answers"][side][q] if side is not None else None
                prediction = None if scores[0] == scores[1] else int(scores[1] > scores[0])
                rows.append(
                    {
                        "world": w,
                        "query": q,
                        "control": name,
                        "target_label": label,
                        "native_scores": scores.tolist(),
                        "base_native_scores": selected.tolist(),
                        "native_prediction": prediction,
                        "correct": prediction is not None and prediction == label
                        if label is not None
                        else None,
                        "base_correct": bool(selected[0] != selected[1])
                        and bool((selected[1] > selected[0]) == label)
                        if label is not None
                        else None,
                        "base_fp32_gap": float(fp32[1] - fp32[0]),
                        "fp32_cap_gap_bound": reach,
                        "bound_is_not_native": True,
                        "delta_l2": float(out.delta.norm()),
                        "applied_native_delta_l2": float(out.readout.applied_delta.norm()),
                        "full_logits_equal_base": exact,
                        **transport(baseline, out.readout),
                    }
                )
    return {"step": step, "rows": rows, "planned_rows": 96}


class GenerationBackend:
    def __init__(self, pipe, store, world, query):
        self.pipe, self.store = pipe, store
        self.span = bound_span(store.renderings[world, query])
        self.memories = {
            name: store.write(pipe.bridge, world, side)
            for name, side in (("workspace", 0), ("twin", 1), ("zero", 0))
        }
        memory, mask = self.memories["zero"]
        self.memories["zero"] = torch.zeros_like(memory), mask

    def encode(self, prefix):
        # Training uses immutable frozen features; generation instead recomputes
        # every complete prefix, matching the generator's no-persistent-cache contract.
        return self.store.encode(prefix)

    def delta(self, condition, hidden, prefix):
        memory, mask = self.memories[condition]
        return self.pipe.delta(hidden, memory, mask, prefix_ids=prefix, span=self.span)[0]

    def readout(self, hidden, delta):
        return self.pipe.readout(hidden, delta)


@torch.no_grad()
def generate(pipe, store, plan, step):
    rows, receipts = [], []
    contract = plan["generation"]
    for w in contract["world_indices"]:
        for q in contract["query_indices"]:
            record = store.records[w]
            prefix = store.renderings[w, q]["prompt_ids"]
            inline = render_case(
                store.tokenizer,
                query=record["queries"][q],
                context=canonical_facts(record["contexts"][0]),
                renderer="native_chat",
                cue="present",
                information="inline",
            )["prompt_ids"]
            backend = GenerationBackend(pipe, store, w, q)
            prompts = {
                name: inline if name == "base_inline" else prefix for name in contract["conditions"]
            }
            generated, receipt = generate_matched(
                case_id=f"w{w}_q{q}",
                prompts=prompts,
                regime=contract["regime"],
                max_new_tokens=contract["max_new_tokens"],
                eos_token_ids={2},
                backend=backend,
                decode=lambda ids: store.tokenizer.decode(ids, skip_special_tokens=True),
                zero_pairs=(("base", "zero"),),
                guard=lambda: store.guard("bounded_generation"),
            )
            for row in generated:
                label = record["answers"][int(row["condition"] == "twin")][q]
                parsed = parse_functional_answer(row["answer"])
                valid = parsed is not None and row["finish_reason"] == "eos"
                row.update(
                    world=w,
                    query=q,
                    step=step,
                    target_label=label,
                    parsed_answer=parsed,
                    valid_eos=valid,
                    strict_correct=valid and parsed == label,
                )
                rows.append(row)
            receipts.append({"world": w, "query": q, **receipt})
    return {"step": step, "rows": rows, "receipts": receipts, "planned_rows": 20}


def train_arm(arm, store, readout, plan, parent, output):
    contract, device = plan["training"], store.base.device
    torch.manual_seed(contract["seed"])
    bridge = PrecisionAwareWorkspaceBridge(store.base.config.hidden_size, **parent["bridge"])
    bridge = bridge.to(device).float()
    pipe = NativeWorkspacePipeline(bridge, readout, plan["reader"])
    optimizer = torch.optim.AdamW(
        bridge.parameters(), lr=contract["learning_rate"], weight_decay=contract["weight_decay"]
    )
    membership = validate_optimizer_ownership(bridge, optimizer)
    initial = prior.state_hash(bridge)
    checkpoints = []

    def inspect(step, bridge, pipe):
        store.guard(f"{arm['id']}_diagnostic_{step}")
        bridge.eval()
        write_new(output / f"{arm['id']}_{step}_evaluation.json", evaluate(pipe, store, step))
        if step in plan["generation"]["steps"]:
            write_new(
                output / f"{arm['id']}_{step}_generation.json", generate(pipe, store, plan, step)
            )
        bridge.train()

    inspect(0, bridge, pipe)
    for step in range(1, contract["steps"] + 1):
        store.guard(f"{arm['id']}_update_{step}")
        optimizer.zero_grad(set_to_none=True)
        totals = {}
        for w in range(2):
            for q in range(8):
                loss, components = pair_objective(pipe, store, w, q, contract, arm["eos_weight"])
                if not bool(torch.isfinite(loss)):
                    raise RuntimeError("Nonfinite native loss")
                loss.backward()
                for key, value in {"loss": loss, **components}.items():
                    totals[key] = totals.get(key, 0.0) + float(value.detach())
                del loss, components
        gradients = {
            name: {
                "present": p.grad is not None,
                "l2": float(p.grad.norm()) if p.grad is not None else None,
            }
            for name, p in bridge.named_parameters()
        }
        norm = torch.nn.utils.clip_grad_norm_(
            bridge.parameters(), contract["max_grad_norm"], error_if_nonfinite=True
        )
        optimizer.step()
        if any(not bool(torch.isfinite(p).all()) for p in bridge.parameters()):
            raise RuntimeError("Nonfinite updated workspace")
        row = {
            "step": step,
            "components": totals,
            "preclip_gradient_l2": float(norm),
            "gradients": gradients,
            "pairs": 16,
            "answer_rows": 32,
            "eos_feature_rows": 32,
            "eos_weight": arm["eos_weight"],
        }
        with (output / f"{arm['id']}_training.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
        optimizer.zero_grad(set_to_none=True)
        if step in plan["checkpoint_steps"]:
            path = output / f"{arm['id']}_step{step}.pt"
            payload = {
                "state_dict": {k: v.detach().cpu() for k, v in bridge.state_dict().items()},
                "step": step,
                "arm": arm["id"],
                "mode": plan["reader"],
                "base_revision": parent["model"]["revision"],
                "plan_sha256": prior.digest(PLAN),
            }
            with path.open("xb") as stream:
                torch.save(payload, stream)
            loaded = torch.load(path, map_location="cpu", weights_only=True)
            if any(
                not torch.equal(v, loaded["state_dict"][k])
                for k, v in payload["state_dict"].items()
            ):
                raise RuntimeError("Checkpoint roundtrip differs")
            checkpoints.append(
                {
                    "path": path.name,
                    "sha256": prior.digest(path),
                    "bytes": path.stat().st_size,
                    "roundtrip_exact": True,
                }
            )
        if step in plan["evaluation_steps"]:
            inspect(step, bridge, pipe)
        print(f"{arm['id']} update {step}/8 loss={totals['loss']:.6f}", flush=True)
    result = {
        "arm": arm,
        "steps": 8,
        "initial_state_sha256": initial,
        "final_state_sha256": prior.state_hash(bridge),
        "optimizer_membership": membership,
        "checkpoints": checkpoints,
    }
    write_new(output / f"{arm['id']}_REPORT.json", result)
    del pipe, bridge, optimizer
    gc.collect()
    return result


def execute(output, expected_commit):
    import transformers

    plan, parent, records = validate()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    if (
        head != expected_commit
        or subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True).strip()
    ):
        raise RuntimeError("Source must match the explicitly committed clean revision")
    runtime = {
        "python": sys.version.split()[0],
        "torch": str(torch.__version__),
        "transformers": transformers.__version__,
        "cuda": torch.version.cuda,
    }
    if runtime != parent["expected_runtime"]:
        raise RuntimeError(f"Runtime mismatch: {runtime}")
    output.mkdir(parents=True, exist_ok=False)
    started, manifest = time.monotonic(), sources()
    guard = ResourceGuard(plan["resources"], output)
    try:
        admission = guard("admission", admission=True)
        write_new(
            output / "STARTED.json",
            {
                "source_commit": head,
                "source_hashes": manifest,
                "plan": plan,
                "runtime": runtime,
                "admission": admission,
                "pid": os.getpid(),
            },
        )
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        torch.set_float32_matmul_precision("highest")
        torch.backends.cuda.matmul.allow_tf32 = False
        if torch.cuda.device_count() != 1:
            raise RuntimeError("Exactly one visible CUDA device required")
        torch.cuda.set_per_process_memory_fraction(
            18 * GIB / torch.cuda.get_device_properties(0).total_memory, 0
        )
        torch.cuda.reset_peak_memory_stats()
        config = engine.ModelConfig(**parent["model"])
        tokenizer = engine.load_tokenizer(config)
        if tokenizer.eos_token_id != 2:
            raise RuntimeError("Pinned EOS token changed")
        print("loading frozen pinned Mistral; native answer learner", flush=True)
        base = engine._load_hf_model(config).eval().requires_grad_(False).to("cuda")
        guard("base_loaded")
        before = prior.state_hash(base)
        if before != BASE_HASH:
            raise RuntimeError("Pinned base identity mismatch")
        versions = {name: p._version for name, p in base.named_parameters()}
        readout = NativeWorkspaceReadout(base.lm_head)
        store = Store(base, tokenizer, readout, records, guard)
        results = [train_arm(arm, store, readout, plan, parent, output) for arm in plan["arms"]]
        if results[0]["initial_state_sha256"] != results[1]["initial_state_sha256"]:
            raise RuntimeError("Matched initialization differs")
        after = prior.state_hash(base)
        if (
            before != after
            or any(p.grad is not None for p in base.parameters())
            or versions != {name: p._version for name, p in base.named_parameters()}
        ):
            raise RuntimeError("Frozen backbone changed")
        if sources() != manifest:
            raise RuntimeError("Source changed during execution")
        validate()
        write_new(output / "FEATURES.json", store.feature_receipt())
        guard("completed")
        report = {
            "status": "COMPLETED_ENGINEERING_PILOT",
            "results": results,
            "source_commit": head,
            "base_state_sha256_before": before,
            "base_state_sha256_after": after,
            "base_unchanged": True,
            "source_unchanged": True,
            "native_parity_forward_checks": len(store.parity),
            "native_parity_unique_prefixes": len({r["prefix_sha256"] for r in store.parity}),
            "elapsed_seconds": time.monotonic() - started,
            "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated(),
            "peak_cuda_reserved_bytes": torch.cuda.max_memory_reserved(),
            "sampled_own_process_peak_bytes": max(
                (p["bytes"] for r in guard.rows for p in r["processes"] if p["pid"] == os.getpid()),
                default=0,
            ),
            "minimum_sampled_device_free_bytes": min(r["free_bytes"] for r in guard.rows),
            "old_expression_gate": "FAIL",
            "winner": "none",
            "semantic_promotion": False,
            "non_regression": "NOT_ESTABLISHED",
            "judge_calls": 0,
        }
        write_new(output / "REPORT.json", report)
        return {k: report[k] for k in ("status", "elapsed_seconds", "peak_cuda_allocated_bytes")}
    except Exception as exc:
        write_new(
            output / "FAILED.json",
            {
                "status": "INCOMPLETE_NO_RETRY",
                "exception_type": type(exc).__name__,
                "message": str(exc),
                "elapsed_seconds": time.monotonic() - started,
            },
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-commit")
    args = parser.parse_args()
    if args.dry_run:
        plan, _, records = validate()
        print(
            json.dumps(
                {
                    "status": "PREPARED_NOT_RUN",
                    "worlds": len(records),
                    "arms": plan["arms"],
                    "updates_per_arm": 8,
                    "evaluation_rows": 576,
                    "generated_sequences": 80,
                }
            )
        )
    elif args.output is None or args.expected_commit is None:
        parser.error("--output and --expected-commit required for the one bounded run")
    else:
        print(json.dumps(execute(args.output.resolve(), args.expected_commit)))
