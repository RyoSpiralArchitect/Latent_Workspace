#!/usr/bin/env python3
"""One frozen reader-query intervention; bounded CUDA train-only comparison."""

from __future__ import annotations

import argparse
import copy
import gc
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import torch
from torch.nn import functional as F

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "src"), str(REPO / "scripts")]
import run_v14_precision_bridge as prior  # noqa: E402
from run_ft_beta_learner_audit import DIFFERENT_SCHEMA, reserialize, write_new  # noqa: E402

from latent_workspace_ft_v10 import engine  # noqa: E402
from latent_workspace_ft_v10.bridge_reader_panel import capture_reverse_panel  # noqa: E402
from latent_workspace_ft_v10.learner_gradient_audit import audit_loss_gradients  # noqa: E402
from latent_workspace_ft_v10.model_binding import FunctionalBoundaryAdapter  # noqa: E402
from latent_workspace_ft_v10.precision_bridge import (  # noqa: E402
    MistralPrecisionBridgeAdapter,
    PrecisionAwareWorkspaceBridge,
)
from latent_workspace_ft_v10.reader_query import (  # noqa: E402
    base_readout_hidden,
    bind_question_span,
    reader_query_hidden,
)

PLAN = REPO / "configs/v14/FT_BETA_QUERY_POOL_PLAN.json"
GIB = 1024**3


class ResourceAbort(RuntimeError):
    pass


def resource_snapshot():
    fields = "uuid,name,memory.total,memory.used,memory.free,utilization.gpu"
    rows = (
        subprocess.check_output(
            ["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"], text=True
        )
        .strip()
        .splitlines()
    )
    if len(rows) != 1:
        raise RuntimeError("This contract requires one physical GPU")
    uuid, name, total, used, free, utilization = [v.strip() for v in rows[0].split(",")]
    clients = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,process_name,used_memory",
            "--format=csv,noheader,nounits",
        ],
        text=True,
    ).strip()
    processes = []
    for line in clients.splitlines():
        pid, process, mib = [v.strip() for v in line.split(",", 2)]
        processes.append({"pid": int(pid), "process": process, "bytes": int(mib) * 1024**2})
    return {
        "uuid": uuid,
        "name": name,
        "total_bytes": int(total) * 1024**2,
        "used_bytes": int(used) * 1024**2,
        "free_bytes": int(free) * 1024**2,
        "utilization_percent": int(utilization),
        "processes": processes,
        "own_pid": os.getpid(),
        "monotonic_seconds": time.monotonic(),
    }


class ResourceGuard:
    def __init__(self, contract, output):
        self.contract, self.output, self.rows = contract, output, []
        self.uuid = None

    def __call__(self, phase, admission=False):
        row = resource_snapshot()
        row["phase"] = phase
        if self.uuid is not None and row["uuid"] != self.uuid:
            raise ResourceAbort("GPU identity changed")
        self.uuid = row["uuid"]
        if torch.cuda.is_initialized():
            row.update(
                allocated=torch.cuda.memory_allocated(),
                reserved=torch.cuda.memory_reserved(),
                peak_allocated=torch.cuda.max_memory_allocated(),
                peak_reserved=torch.cuda.max_memory_reserved(),
            )
        self.rows.append(row)
        # Append-only resource log survives an interrupted run.
        with (self.output / "RESOURCES.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, allow_nan=False) + "\n")
        threshold = self.contract["admission_free_gib" if admission else "abort_free_gib"] * GIB
        if row["free_bytes"] < threshold:
            raise ResourceAbort(f"Insufficient free memory at {phase}; stop own run only")
        return row


def validate_contract():
    plan = json.loads(PLAN.read_text())
    parent = json.loads((REPO / plan["parent_plan"]).read_text())
    train, _, split = prior.validate_plan(parent)
    if plan["resources"] != {
        "admission_free_gib": 20,
        "allocator_cap_gib": 18,
        "abort_free_gib": 4,
        "poll_steps": 16,
        "cpu_threads": 2,
    }:
        raise ValueError("Frozen resource contract changed")
    if (
        plan["modes"] != ["final", "mean_span"]
        or plan["world_indices"] != [0, 1]
        or plan["query_indices"] != list(range(8))
        or plan["primary_step"] != 256
        or plan["checkpoint_steps"] != [128, 256]
        or plan["diagnostic_steps"] != [0, 1, 128, 256]
        or parent["training"]["batch_size"] != 16
    ):
        raise ValueError("Frozen tiny protocol changed")
    for record in train[:2]:
        affected = [a != b for a, b in zip(*record["answers"], strict=True)]
        if affected != [True, True, False, False, False, False, False, False]:
            raise ValueError("Reciprocal affected denominator changed")
    return plan, parent, train[:2], split


def source_identity(parent):
    names = set(parent["source_identity"]) | {
        str(PLAN.relative_to(REPO)),
        "configs/v14/PRECISION_BRIDGE_PLAN.json",
        "scripts/run_ft_beta_query_pool.py",
        "scripts/ft_beta_query_pool_eval.py",
        "scripts/run_ft_beta_learner_audit.py",
        "src/latent_workspace_ft_v10/reader_query.py",
        "src/latent_workspace_ft_v10/learner_gradient_audit.py",
        "src/latent_workspace_ft_v10/bridge_reader_panel.py",
    }
    return {name: prior.digest(REPO / name) for name in sorted(names)}


def tensor_hash(tensor):
    value = tensor.detach().cpu().contiguous()
    return hashlib.sha256(value.view(torch.uint8).numpy().tobytes()).hexdigest()


class CUDAStore(prior.FeatureStore):
    def __init__(self, *args, data_config, guard):
        self.data_config, self.guard = data_config, guard
        self.native_gates, self.spans, self.span_receipts = [], {}, []
        super().__init__(*args)
        # Re-encode adversarial metadata variations. Scoring metadata cannot
        # select the question span or change any query-only prefix.
        for w, record in enumerate(self.records):
            variants = []
            for kind in ("answers", "side", "query_order", "metadata"):
                altered = copy.deepcopy(record)
                if kind == "answers":
                    altered["answers"] = [[1 - x for x in side] for side in altered["answers"]]
                elif kind == "side":
                    altered["answers"].reverse()
                    altered["contexts"].reverse()
                elif kind == "query_order":
                    for key in ("queries", "affected", "hop_distances", "heldout_queries"):
                        altered[key].reverse()
                    altered["answers"] = [side[::-1] for side in altered["answers"]]
                else:
                    altered["metadata"] = {"untrusted_scoring_metadata": "changed"}
                variants.append(
                    (
                        kind,
                        engine._encode_functional_world_pair(altered, self.tokenizer, data_config),
                    )
                )
            for q, raw in enumerate(record["queries"]):
                prefix = self.prefix(self.features[w], q)
                rendered = engine._functional_elicitation_query(raw, data_config)
                span = bind_question_span(
                    self.tokenizer,
                    raw_query=raw,
                    rendered_prefix=rendered,
                    expected_prefix_ids=prefix,
                )
                self.spans[w, q] = span
                for kind, feature in variants:
                    for side in (0, 1):
                        index = 7 - q if kind == "query_order" else q
                        if self.prefix(feature, index, side) != prefix:
                            raise RuntimeError("Scoring metadata changed inference prefix")
                self.span_receipts.append(
                    {
                        "world": w,
                        "query": q,
                        "raw_query": raw,
                        "rendered_prefix": rendered,
                        "span": asdict(span),
                        "selected_tokens": self.tokenizer.convert_ids_to_tokens(
                            [prefix[index] for index in span.token_indices]
                        ),
                        "metadata_permutations_prefix_equal": [v[0] for v in variants],
                    }
                )

    @torch.no_grad()
    def get_prefix(self, prefix):
        key = tuple(prefix)
        if key not in self.prefix_cache:
            self.guard("capture_query")
            ids = torch.tensor([key], device=self.device)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                hidden = self.adapter.encode_prefix(ids, torch.ones_like(ids), boundary_layer=16)
                actual = self.adapter.base_model(
                    ids, attention_mask=torch.ones_like(ids), use_cache=False
                ).logits
                decoded = self.adapter.decode(
                    hidden, torch.zeros_like(hidden[:, -1:]).float(), self.candidate_ids
                )
            if not torch.equal(actual.float(), decoded.native_logits.float()):
                raise RuntimeError("Ordinary/split full native logits differ; no tolerance retry")
            self.native_gates.append(
                {"prefix_sha256": prior._stable_hash(key), "full_logits_exact": True}
            )
            self.prefix_cache[key] = hidden.detach().cpu()
            self.prefix_forwards += 1
        return self.prefix_cache[key]

    @torch.no_grad()
    def context(self, world, side):
        key = world, side
        if key not in self.context_cache:
            self.guard("capture_context")
            if side == "unrelated":
                text = prior.unrelated_context(self.records[world])
            elif side == "different_schema":
                text = DIFFERENT_SCHEMA
            elif isinstance(side, str) and side.startswith("reserialized_"):
                text = reserialize(self.records[world]["contexts"][int(side[-1])])
            else:
                text = None
            tokens = (
                self.tokenizer.encode(text, add_special_tokens=False)
                if text is not None
                else self.features[world]["functional_context_ids"][side]
            )
            ids = torch.tensor([tokens], device=self.device)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                hidden = self.boundary.encode(ids, torch.ones_like(ids), 16)
            self.context_cache[key] = hidden.detach().cpu()
        return self.context_cache[key]

    def reader_query(self, world, q, mode):
        return reader_query_hidden(
            self.query(world, q),
            self.spans[world, q],
            prefix_ids=self.prefix(self.features[world], q),
            mode=mode,
        )


def batch_tensors(store, head, device, mode):
    order = [(w, q) for w in range(2) for q in range(8)]
    base = torch.cat([base_readout_hidden(store.query(w, q)) for w, q in order]).to(device).float()
    query = torch.cat([store.reader_query(w, q, mode) for w, q in order]).to(device)
    context, mask = prior.pad_contexts(
        [store.context(w, s) for s in (0, 1, "unrelated") for w, q in order], device
    )
    labels = torch.tensor(
        [[store.records[w]["answers"][s][q] for s in (0, 1)] for w, q in order], device=device
    )
    return dict(
        base=base,
        query=query,
        context=context,
        mask=mask,
        labels=labels,
        affected=labels[:, 0] != labels[:, 1],
        head=head,
        order=order,
    )


def objective_graph(bridge, batch, contract):
    memory, mask = bridge.write_memory(batch["context"], batch["mask"])
    delta = bridge.read_delta(batch["query"].repeat(3, 1, 1), memory, mask)
    scores0, scores1, unrelated = (
        F.linear(batch["base"].repeat(3, 1, 1) + delta, batch["head"]).squeeze(1).chunk(3)
    )
    base_scores = F.linear(batch["base"] + torch.zeros_like(batch["base"]), batch["head"]).squeeze(
        1
    )
    loss, components = prior.objective(
        scores0,
        scores1,
        unrelated,
        base_scores,
        batch["labels"],
        batch["affected"],
        delta,
        "semantic",
        contract,
    )
    donor = (2 * batch["labels"][:, 1] - 1) * (
        scores1[:, 1] - scores1[:, 0] - scores0[:, 1] + scores0[:, 0]
    )
    return loss, components, donor


def gradient_diagnostic(bridge, batch, contract):
    loss, components, donor = objective_graph(bridge, batch, contract)
    components.pop("loss")
    weights = {
        "paired_ce": 1.0,
        "donor_hinge": contract["direction_weight"],
        "unaffected_gap_square": contract["stability_weight"],
        "unrelated_gap_square": contract["unrelated_weight"],
        "residual_norm_square": contract["residual_penalty"],
    }
    even = torch.tensor([q % 2 == 0 for w, q in batch["order"]], device=donor.device)
    diagnostics = {
        name: F.relu(contract["donor_margin"] - donor[mask & batch["affected"]]).mean()
        for name, mask in (("donor_even_hinge", even), ("donor_odd_hinge", ~even))
    }
    result = audit_loss_gradients(
        bridge,
        components,
        weights,
        total_loss=loss,
        diagnostic_components=diagnostics,
        frozen_tensors={k: batch[k] for k in ("base", "query", "context", "head")},
    )
    result["donor_margins"] = donor.detach().tolist()
    if not result["reconstruction"]["passed"]:
        raise RuntimeError("Gradient reconstruction failed; no tolerance relaxation")
    return result


def train_mode(mode, store, adapter, head, parent, plan, output, guard):
    from ft_beta_query_pool_eval import evaluate

    device, contract = head.device, parent["training"]
    torch.manual_seed(contract["seed"])
    bridge = PrecisionAwareWorkspaceBridge(head.shape[-1], **parent["bridge"]).to(device).float()
    initial = prior.state_hash(bridge)
    optimizer = torch.optim.AdamW(
        bridge.parameters(), lr=contract["learning_rate"], weight_decay=contract["weight_decay"]
    )
    batch = batch_tensors(store, head, device, mode)
    rows, checkpoints, summaries, gates = [], [], {}, {}

    def diagnostic(step, bridge, batch):
        guard(f"{mode}_diagnostic_{step}")
        bridge.eval()
        write_new(
            output / f"{mode}_{step}_gradients.json", gradient_diagnostic(bridge, batch, contract)
        )
        wrapper = SimpleNamespace(
            query=lambda w, q: store.reader_query(w, q, mode),
            context=store.context,
            records=store.records,
            features=store.features,
        )
        panel = capture_reverse_panel(bridge, wrapper, head, device, world_count=2)
        panel["query_representation"] = mode
        panel["head_projection_scope"] = "FP32 residual-axis diagnostic, not native score or flip"
        write_new(output / f"{mode}_{step}_reader.json", panel)
        result = evaluate(
            bridge, store, adapter, mode, device, guard=guard, expect_initial_zero=step == 0
        )
        write_new(output / f"{mode}_{step}_evaluation.json", result)
        summaries[str(step)] = result["summary"]
        gates[str(step)] = result["gates"]
        bridge.train()

    diagnostic(0, bridge, batch)
    for step in range(1, 257):
        if step == 1 or step % plan["resources"]["poll_steps"] == 0:
            guard(f"{mode}_train_{step}")
        optimizer.zero_grad(set_to_none=True)
        loss, components, donor = objective_graph(bridge, batch, contract)
        if not bool(torch.isfinite(loss)):
            raise RuntimeError("Nonfinite training loss")
        loss.backward()
        norm = torch.nn.utils.clip_grad_norm_(
            bridge.parameters(), contract["max_grad_norm"], error_if_nonfinite=True
        )
        optimizer.step()
        if any(not bool(torch.isfinite(p).all()) for p in bridge.parameters()):
            raise RuntimeError("Nonfinite updated parameter")
        row = {
            "step": step,
            "preclip_gradient_l2": float(norm),
            "components": {k: float(v.detach()) for k, v in components.items()},
            "donor_margins_before_update": donor.detach().tolist(),
        }
        rows.append(row)
        with (output / f"{mode}_training.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, allow_nan=False) + "\n")
        del loss, components, donor
        optimizer.zero_grad(set_to_none=True)
        if step in plan["checkpoint_steps"]:
            path = output / f"{mode}_step{step}.pt"
            payload = {
                "state_dict": {k: v.detach().cpu() for k, v in bridge.state_dict().items()},
                "step": step,
                "mode": mode,
                "base_revision": parent["model"]["revision"],
                "plan_sha256": prior.digest(PLAN),
            }
            with path.open("xb") as handle:
                torch.save(payload, handle)
            loaded = torch.load(path, map_location="cpu", weights_only=True)
            if any(
                not torch.equal(v.detach().cpu(), loaded["state_dict"][k])
                for k, v in bridge.state_dict().items()
            ):
                raise RuntimeError("Checkpoint roundtrip mismatch")
            checkpoints.append(
                {
                    "path": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": prior.digest(path),
                    "roundtrip_exact": True,
                }
            )
            del payload, loaded
        if step in plan["diagnostic_steps"]:
            diagnostic(step, bridge, batch)
        if step % 32 == 0:
            print(f"{mode} step {step}/256 loss {row['components']['loss']:.6f}", flush=True)
    result = {
        "initial_state_sha256": initial,
        "final_state_sha256": prior.state_hash(bridge),
        "parameters": sum(p.numel() for p in bridge.parameters()),
        "steps": 256,
        "checkpoints": checkpoints,
        "summaries": summaries,
        "gates": gates,
        "batch_order_sha256": prior._stable_hash(batch["order"]),
        "query_mode": mode,
    }
    write_new(output / f"{mode}_REPORT.json", result)
    del bridge, optimizer, batch
    gc.collect()
    return result


def execute(output):
    import transformers

    plan, parent, records, split = validate_contract()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True).strip():
        raise RuntimeError("Formal source must be committed and clean")
    runtime = {
        "python": sys.version.split()[0],
        "torch": str(torch.__version__),
        "transformers": transformers.__version__,
        "cuda": torch.version.cuda,
    }
    if runtime != parent["expected_runtime"]:
        raise RuntimeError(f"Runtime mismatch: {runtime}")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    guard = ResourceGuard(plan["resources"], output)
    try:
        admission = guard("admission", admission=True)
        sources = source_identity(parent)
        receipt = {
            "runtime": runtime,
            "source_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
            ).strip(),
            "source_hashes": sources,
            "plan": plan,
            "split_audit": split,
            "admission": admission,
        }
        write_new(output / "STARTED.json", receipt)
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        torch.set_float32_matmul_precision("highest")
        torch.backends.cuda.matmul.allow_tf32 = False
        if torch.cuda.device_count() != 1:
            raise RuntimeError("Exactly one visible CUDA device required")
        torch.cuda.set_per_process_memory_fraction(
            float(18 * GIB / torch.cuda.get_device_properties(0).total_memory), 0
        )
        torch.cuda.reset_peak_memory_stats()
        config = engine.ModelConfig(**parent["model"])
        tokenizer = engine.load_tokenizer(config)
        print("loading pinned original; frozen CUDA BF16 backbone", flush=True)
        base = engine._load_hf_model(config).eval().requires_grad_(False).to("cuda")
        guard("base_loaded")
        before = prior.state_hash(base)
        if before != "54d161755862ebf00d8acbca083d5f290a5de44d33af82ca885f3bd8f9c94312":
            raise RuntimeError("Pinned original model identity mismatch")
        versions = {n: p._version for n, p in base.named_parameters()}
        boundary = FunctionalBoundaryAdapter(base)
        adapter = MistralPrecisionBridgeAdapter(boundary)
        data_config = engine.DataConfig(
            **json.loads((REPO / parent["data_config_parent"]).read_text())["data"]
        )
        dataset = engine.JsonlFineTuningDataset(
            [str(REPO / parent["data"]["train"]["path"])], tokenizer, data_config
        )
        store = CUDAStore(
            records,
            dataset,
            tokenizer,
            boundary,
            adapter,
            torch.device("cuda"),
            data_config=data_config,
            guard=guard,
        )
        store.prepare("tiny matched CUDA")
        for w in range(2):
            for side in ("different_schema", "reserialized_0", "reserialized_1"):
                store.context(w, side)
        if base.lm_head.bias is not None:
            raise RuntimeError("Expected bias-free pinned head")
        head = base.lm_head.weight.detach()[list(store.candidate_ids)].float()
        write_new(
            output / "FEATURES.json",
            {
                "spans": store.span_receipts,
                "native_gates": store.native_gates,
                "candidate_ids": store.candidate_ids,
                "prefix_tensor_hashes": {
                    prior._stable_hash(key): tensor_hash(value)
                    for key, value in store.prefix_cache.items()
                },
                "context_tensor_hashes": {
                    str(key): tensor_hash(value) for key, value in store.context_cache.items()
                },
                "cache_tensor_bytes": sum(
                    t.numel() * t.element_size()
                    for t in (*store.prefix_cache.values(), *store.context_cache.values())
                ),
                "use_chat_template": data_config.use_chat_template,
                "different_schema_text": DIFFERENT_SCHEMA,
            },
        )
        results = {
            mode: train_mode(mode, store, adapter, head, parent, plan, output, guard)
            for mode in plan["modes"]
        }
        for key in ("initial_state_sha256", "batch_order_sha256", "parameters", "steps"):
            if results["final"][key] != results["mean_span"][key]:
                raise RuntimeError(f"Matched contract mismatch: {key}")
        after = prior.state_hash(base)
        if (
            before != after
            or versions != {n: p._version for n, p in base.named_parameters()}
            or any(p.grad is not None for p in base.parameters())
        ):
            raise RuntimeError("Frozen original changed")
        if sources != source_identity(parent):
            raise RuntimeError("Source changed during run")
        validate_contract()
        guard("completed")
        report = {
            "status": "COMPLETED_TINY_TRAIN_ONLY",
            "results": results,
            "base_state_sha256_before": before,
            "base_state_sha256_after": after,
            "base_unchanged": True,
            "source_unchanged": True,
            "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated(),
            "peak_cuda_reserved_bytes": torch.cuda.max_memory_reserved(),
            "sampled_own_process_peak_bytes": max(
                (p["bytes"] for r in guard.rows for p in r["processes"] if p["pid"] == os.getpid()),
                default=0,
            ),
            "minimum_sampled_device_free_bytes": min(r["free_bytes"] for r in guard.rows),
            "elapsed_seconds": time.monotonic() - started,
            "winner": "none",
            "semantic_promotion": False,
            "heldout_nonregression": "NOT_RUN",
            "free_text_generation": "NOT_RUN",
        }
        write_new(output / "REPORT.json", report)
        return {
            k: report[k]
            for k in (
                "status",
                "elapsed_seconds",
                "peak_cuda_allocated_bytes",
                "peak_cuda_reserved_bytes",
            )
        }
    except Exception as exc:
        write_new(
            output / "FAILED.json",
            {
                "status": "INCOMPLETE_RESOURCE_ABORT"
                if isinstance(exc, (ResourceAbort, torch.cuda.OutOfMemoryError))
                else "FAILED_EXECUTION",
                "exception_type": type(exc).__name__,
                "message": str(exc),
                "elapsed_seconds": time.monotonic() - started,
            },
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.dry_run:
        plan, parent, records, split = validate_contract()
        print(json.dumps({"status": "PREPARED_NOT_RUN", "worlds": len(records), "split": split}))
    elif args.output is None:
        parser.error("--output required")
    else:
        print(json.dumps(execute(args.output.resolve())))
