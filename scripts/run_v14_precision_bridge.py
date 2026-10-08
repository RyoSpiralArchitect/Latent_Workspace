#!/usr/bin/env python3
"""Frozen-original, post-finalnorm bridge pilot; never rewrites old V14 evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
import time
from pathlib import Path

import torch
from torch.nn import functional as F

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
from run_v14_boundary_training import atomic_write, digest, resolve_inside  # noqa: E402
from run_v14_experimental_chat import _prompt_prefix  # noqa: E402
from run_v14_multiturn_choice import _project_scenarios, _stable_hash  # noqa: E402

from latent_workspace_ft_v10 import engine  # noqa: E402
from latent_workspace_ft_v10.model_binding import FunctionalBoundaryAdapter  # noqa: E402
from latent_workspace_ft_v10.precision_bridge import (  # noqa: E402
    MistralPrecisionBridgeAdapter,
    PrecisionAwareWorkspaceBridge,
)

PLAN = REPO / "configs/v14/PRECISION_BRIDGE_PLAN.json"
ENTITIES = (
    "Aster",
    "Beryl",
    "Cyra",
    "Doran",
    "Eris",
    "Fenn",
    "Galen",
    "Hira",
    "Ione",
    "Joren",
    "Kestrel",
    "Luma",
)


def load_records(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def split_audit(train, evaluation):
    def keys(rows):
        return {
            "pair_ids": {r["metadata"]["pair_id"] for r in rows},
            "orders": {tuple(o) for r in rows for o in r["metadata"]["orders"]},
            "unordered_twins": {
                tuple(sorted(tuple(o) for o in r["metadata"]["orders"])) for r in rows
            },
            "contexts": {c for r in rows for c in r["contexts"]},
        }

    left, right = keys(train), keys(evaluation)
    overlaps = {k: len(left[k] & right[k]) for k in left}
    if any(overlaps.values()):
        raise ValueError(f"Train/eval overlap: {overlaps}")
    return {
        "train_world_pairs": len(train),
        "eval_world_pairs": len(evaluation),
        "overlaps": overlaps,
        "entity_heldout": False,
    }


def unrelated_context(record):
    """Complement entities, order determined without consulting answers or queries."""
    present = set(record["metadata"]["orders"][0])
    if not present <= set(ENTITIES) or len(present) != 6:
        raise ValueError("Unexpected world entity inventory")
    complement = sorted(
        set(ENTITIES) - present,
        key=lambda name: _stable_hash([record["metadata"]["pair_id"], name]),
    )
    assert len(complement) == 6 and not present.intersection(complement)
    return "World facts. The ranking is transitive.\n" + "\n".join(
        f"- {a} is ranked above {b}." for a, b in zip(complement, complement[1:])
    )


def state_hash(module):
    h = hashlib.sha256()
    for name, value in module.state_dict().items():
        value = value.detach().cpu().contiguous()
        h.update(name.encode())
        h.update(str(value.dtype).encode())
        h.update(str(tuple(value.shape)).encode())
        h.update(value.view(torch.uint8).numpy().tobytes())
    return h.hexdigest()


class FeatureStore:
    """CPU cache of immutable frozen-backbone outputs, keyed by exact token prefix."""

    def __init__(self, records, dataset, tokenizer, boundary, adapter, device):
        self.records, self.dataset = records, dataset
        self.features = [dataset[i] for i in range(len(records))]
        self.tokenizer, self.boundary, self.adapter, self.device = (
            tokenizer,
            boundary,
            adapter,
            device,
        )
        self.prefix_cache, self.context_cache = {}, {}
        self.prefix_forwards = 0
        self.candidate_ids = tuple(
            x[0] for x in self.features[0]["functional_query_choice_ids"][0][0]
        )
        for feature in self.features:
            for side in (0, 1):
                for q in range(8):
                    choices = feature["functional_query_choice_ids"][side][q]
                    if (
                        any(len(x) != 1 for x in choices)
                        or tuple(x[0] for x in choices) != self.candidate_ids
                    ):
                        raise ValueError("Choice token identity drift")
                    if self.prefix(feature, q, 0) != self.prefix(feature, q, 1):
                        raise ValueError("Query-only prefix exposes world side")

    @staticmethod
    def prefix(feature, q, side=0):
        return tuple(
            _prompt_prefix(
                feature["functional_query_ids"][side][q],
                feature["functional_query_labels"][side][q],
            )
        )

    @torch.no_grad()
    def get_prefix(self, prefix):
        key = tuple(prefix)
        if key not in self.prefix_cache:
            ids = torch.tensor([key], device=self.device, dtype=torch.long)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                hidden = self.adapter.encode_prefix(ids, torch.ones_like(ids), boundary_layer=16)
            self.prefix_cache[key] = hidden.detach().cpu()
            self.prefix_forwards += 1
        return self.prefix_cache[key]

    def query(self, world, q):
        return self.get_prefix(self.prefix(self.features[world], q))

    @torch.no_grad()
    def context(self, world, side):
        key = (world, side)
        if key not in self.context_cache:
            tokens = (
                self.tokenizer.encode(
                    unrelated_context(self.records[world]), add_special_tokens=False
                )
                if side == "unrelated"
                else self.features[world]["functional_context_ids"][side]
            )
            ids = torch.tensor([tokens], device=self.device, dtype=torch.long)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                hidden = self.boundary.encode(ids, torch.ones_like(ids), 16)
            self.context_cache[key] = hidden.detach().cpu()
        return self.context_cache[key]

    def prepare(self, label):
        for world in range(len(self.records)):
            for side in (0, 1, "unrelated"):
                self.context(world, side)
            for q in range(8):
                self.query(world, q)
            if world % 16 == 0:
                print(f"features {label} {world + 1}/{len(self.records)}", flush=True)


def pad_contexts(tensors, device):
    length = max(t.shape[1] for t in tensors)
    hidden = torch.zeros(len(tensors), length, tensors[0].shape[-1], device=device)
    mask = torch.zeros(len(tensors), length, device=device, dtype=torch.long)
    for i, tensor in enumerate(tensors):
        hidden[i, : tensor.shape[1]] = tensor[0].to(device=device, dtype=torch.float32)
        mask[i, : tensor.shape[1]] = 1
    return hidden, mask


def objective(scores0, scores1, unrelated, base_scores, labels, affected, deltas, cell, contract):
    """One paired directional term per world/query, no side duplication."""
    ce = (F.cross_entropy(scores0, labels[:, 0]) + F.cross_entropy(scores1, labels[:, 1])) / 2
    gap0, gap1 = scores0[:, 1] - scores0[:, 0], scores1[:, 1] - scores1[:, 0]
    difference = gap1 - gap0
    donor = (2 * labels[:, 1] - 1) * difference
    zero = difference.sum() * 0.0
    margin = F.relu(contract["donor_margin"] - donor[affected]).mean() if affected.any() else zero
    stability = difference[~affected].square().mean() if (~affected).any() else zero
    unrelated_gap = unrelated[:, 1] - unrelated[:, 0] - (base_scores[:, 1] - base_scores[:, 0])
    unrelated_loss = unrelated_gap.square().mean()
    penalty = deltas.square().sum(-1).mean()
    loss = ce + contract["residual_penalty"] * penalty
    if cell == "semantic":
        loss = (
            loss
            + contract["direction_weight"] * margin
            + contract["stability_weight"] * stability
            + contract["unrelated_weight"] * unrelated_loss
        )
    elif cell != "task":
        raise ValueError("Unknown training cell")
    return loss, {
        "loss": loss,
        "paired_ce": ce,
        "donor_hinge": margin,
        "unaffected_gap_square": stability,
        "unrelated_gap_square": unrelated_loss,
        "residual_norm_square": penalty,
    }


def train_cell(cell, store, base, plan, output, device):
    t = plan["training"]
    torch.manual_seed(t["seed"])
    bridge = (
        PrecisionAwareWorkspaceBridge(base.config.hidden_size, **plan["bridge"]).to(device).float()
    )
    bridge.train()
    initial = state_hash(bridge)
    optimizer = torch.optim.AdamW(
        bridge.parameters(), lr=t["learning_rate"], weight_decay=t["weight_decay"]
    )
    candidates = torch.tensor(store.candidate_ids, device=device)
    weight = base.lm_head.weight.detach().index_select(0, candidates).float()
    bias = (
        None
        if base.lm_head.bias is None
        else base.lm_head.bias.detach().index_select(0, candidates).float()
    )
    examples = [(w, q) for w in range(len(store.records)) for q in range(8)]
    rng = random.Random(t["seed"])
    schedule = []
    while len(schedule) < t["steps"] * t["batch_size"]:
        epoch = list(examples)
        rng.shuffle(epoch)
        schedule.extend(epoch)
    schedule = schedule[: t["steps"] * t["batch_size"]]
    rows, saves = [], []
    upstream_nonzero = False
    for step in range(1, t["steps"] + 1):
        batch = schedule[(step - 1) * t["batch_size"] : step * t["batch_size"]]
        query = torch.cat([store.query(w, q)[:, -1:] for w, q in batch]).to(device).float()
        contexts = [store.context(w, side) for side in (0, 1, "unrelated") for w, q in batch]
        context, mask = pad_contexts(contexts, device)
        memory, memory_mask = bridge.write_memory(context, mask)
        delta = bridge.read_delta(query.repeat(3, 1, 1), memory, memory_mask)
        # Exactly the FP32 selected tied-head computation used at evaluation.
        scores = F.linear(query.repeat(3, 1, 1) + delta, weight, bias).squeeze(1)
        scores0, scores1, unrelated = scores.chunk(3)
        base_scores = F.linear(query, weight, bias).squeeze(1)
        labels = torch.tensor(
            [[store.records[w]["answers"][s][q] for s in (0, 1)] for w, q in batch], device=device
        )
        affected = labels[:, 0] != labels[:, 1]
        loss, components = objective(
            scores0, scores1, unrelated, base_scores, labels, affected, delta, cell, t
        )
        if not torch.isfinite(loss):
            raise RuntimeError("Nonfinite training loss")
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        for name, param in bridge.named_parameters():
            if param.grad is not None and not bool(torch.isfinite(param.grad).all()):
                raise RuntimeError(f"Nonfinite gradient: {name}")
        writer_grad = sum(
            float(p.grad.float().norm())
            for n, p in bridge.named_parameters()
            if n.startswith("writer.") and p.grad is not None
        )
        upstream_nonzero |= step > 1 and writer_grad > 0
        norm = torch.nn.utils.clip_grad_norm_(bridge.parameters(), t["max_grad_norm"])
        optimizer.step()
        row = {
            "step": step,
            "loss_parameter_step": step - 1,
            "world_query_count": len(batch),
            "affected_count": int(affected.sum()),
            **{key: float(value.detach()) for key, value in components.items()},
            "writer_gradient_norm_sum": writer_grad,
            "unclipped_grad_norm": float(norm),
        }
        rows.append(row)
        if step == 1 or step % 32 == 0:
            print(f"training {cell} {step}/{t['steps']} loss={row['loss']:.6f}", flush=True)
        if step in t["save_steps"]:
            path = output / f"{cell}_step{step}.pt"
            if path.exists():
                raise FileExistsError(path)
            torch.save(
                {
                    "state_dict": bridge.state_dict(),
                    "step": step,
                    "cell": cell,
                    "plan_sha256": digest(PLAN),
                    "base_revision": plan["model"]["revision"],
                },
                path,
            )
            saves.append(
                {
                    "path": str(path.relative_to(REPO)),
                    "sha256": digest(path),
                    "bytes": path.stat().st_size,
                }
            )
    if not upstream_nonzero or state_hash(bridge) == initial:
        raise RuntimeError("Bridge upstream learning not observed")
    bridge.eval()
    reloaded = (
        PrecisionAwareWorkspaceBridge(base.config.hidden_size, **plan["bridge"]).to(device).float()
    )
    payload = torch.load(
        output / f"{cell}_step{t['steps']}.pt", map_location=device, weights_only=True
    )
    reloaded.load_state_dict(payload["state_dict"], strict=True)
    if state_hash(reloaded) != state_hash(bridge):
        raise RuntimeError("Saved bridge reload mismatch")
    del reloaded, payload
    return bridge, {
        "initial_state_sha256": initial,
        "final_state_sha256": state_hash(bridge),
        "schedule_sha256": _stable_hash(schedule),
        "rows": rows,
        "checkpoints": saves,
        "writer_gradient_nonzero_after_step1": upstream_nonzero,
        "final_checkpoint_reload_exact": True,
        "trainable_parameters": sum(p.numel() for p in bridge.parameters()),
    }


def validate_plan(plan):
    if (
        plan["format"] != "latent-workspace-v14-precision-bridge-plan-v1"
        or plan["semantic_promotion"] is not False
    ):
        raise ValueError("Frozen pilot plan changed")
    if plan["training"]["save_steps"] != [128, 256] or plan["training"]["steps"] != 256:
        raise ValueError("Budget/retention changed")
    if not plan["source_identity"]:
        raise ValueError("Source identity must be frozen before execution")
    for path, sha in plan["source_identity"].items():
        if digest(REPO / path) != sha:
            raise ValueError(f"Source identity changed: {path}")
    for spec in plan["data"].values():
        if digest(REPO / spec["path"]) != spec["sha256"]:
            raise ValueError("Dataset identity changed")
    train = load_records(REPO / plan["data"]["train"]["path"])
    evaluation = load_records(REPO / plan["data"]["eval"]["path"])
    audit = split_audit(train, evaluation)
    if (len(train), len(evaluation)) != (256, 64):
        raise ValueError("Dataset denominator changed")
    for record in train + evaluation:
        unrelated_context(record)
    return train, evaluation, audit


def execute(plan, dry_run=False):
    train, evaluation, audit = validate_plan(plan)
    if dry_run:
        return {"status": "PREPARED_NOT_RUN", "split_audit": audit}
    import transformers
    from v14_precision_bridge_eval import evaluate_multiturn, evaluate_single

    if subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True).strip():
        raise RuntimeError("Formal source tree must be clean")
    runtime = {
        "python": ".".join(map(str, sys.version_info[:3])),
        "torch": str(torch.__version__),
        "transformers": transformers.__version__,
        "cuda": torch.version.cuda,
    }
    if runtime != plan["expected_runtime"]:
        raise RuntimeError(f"Runtime mismatch: {runtime}")
    if subprocess.check_output(
        ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"], text=True
    ).strip():
        raise RuntimeError("GPU already has compute clients")
    output = resolve_inside(REPO, plan["output"], label="output")
    output.mkdir(parents=True, exist_ok=False)
    atomic_write(
        output / "STARTED.json",
        {
            "plan_sha256": digest(PLAN),
            "runtime": runtime,
            "source_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
            ).strip(),
        },
    )
    started = time.monotonic()
    device = torch.device("cuda")
    torch.set_num_threads(2)
    torch.set_float32_matmul_precision("highest")
    torch.backends.cuda.matmul.allow_tf32 = False
    config = engine.ModelConfig(**plan["model"])
    tokenizer = engine.load_tokenizer(config)
    base = engine._load_hf_model(config).eval().requires_grad_(False).to(device)
    base_before = state_hash(base)
    versions = {n: p._version for n, p in base.named_parameters()}
    boundary = FunctionalBoundaryAdapter(base)
    adapter = MistralPrecisionBridgeAdapter(boundary)
    data_config = engine.DataConfig(
        **json.loads((REPO / plan["data_config_parent"]).read_text())["data"]
    )
    stores = []
    for label, records in (("train", train), ("eval", evaluation)):
        dataset = engine.JsonlFineTuningDataset(
            [str(REPO / plan["data"][label]["path"])], tokenizer, data_config
        )
        stores.append(FeatureStore(records, dataset, tokenizer, boundary, adapter, device))
    train_store, eval_store = stores
    # Exact original-model and split-adapter identity gate before any optimization.
    prefix = FeatureStore.prefix(train_store.features[0], 0)
    ids = torch.tensor([prefix], device=device)
    with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
        native = base(ids, attention_mask=torch.ones_like(ids), use_cache=False).logits
        normalized = train_store.get_prefix(prefix).to(device)
        decoded = adapter.decode(
            normalized, torch.zeros_like(normalized[:, -1:]).float(), train_store.candidate_ids
        )
    if not torch.equal(native.float(), decoded.native_logits.float()):
        raise RuntimeError("Pinned base / split-native zero-delta identity failed")
    train_store.prepare("train")
    eval_store.prepare("eval")
    torch.manual_seed(plan["training"]["seed"])
    initial_bridge = (
        PrecisionAwareWorkspaceBridge(base.config.hidden_size, **plan["bridge"])
        .to(device)
        .float()
        .eval()
    )
    print("evaluation step-zero (frozen protocol; not used for tuning)", flush=True)
    step0 = evaluate_single(initial_bridge, eval_store, adapter, eval_store.candidate_ids, device)
    atomic_write(output / "single_step0.json", step0)
    del initial_bridge
    bridges, training = {}, {}
    for cell in ("task", "semantic"):
        bridges[cell], training[cell] = train_cell(cell, train_store, base, plan, output, device)
        atomic_write(output / f"training_{cell}.json", training[cell])
    if (
        training["task"]["initial_state_sha256"] != training["semantic"]["initial_state_sha256"]
        or training["task"]["schedule_sha256"] != training["semantic"]["schedule_sha256"]
    ):
        raise RuntimeError("Matched training initialization/schedule drift")
    single = {}
    for cell in bridges:
        print(f"evaluation single {cell}", flush=True)
        single[cell] = evaluate_single(
            bridges[cell], eval_store, adapter, eval_store.candidate_ids, device
        )
        atomic_write(output / f"single_{cell}.json", single[cell])
    scenarios = _project_scenarios(eval_store.dataset, tokenizer, plan)
    print("evaluation four-turn", flush=True)
    multi = evaluate_multiturn(
        bridges, eval_store, adapter, tokenizer, scenarios, eval_store.candidate_ids, device
    )
    atomic_write(output / "multiturn.json", multi)
    base_after = state_hash(base)
    if (
        base_before != base_after
        or versions != {n: p._version for n, p in base.named_parameters()}
        or any(p.grad is not None for p in base.parameters())
    ):
        raise RuntimeError("Frozen original base mutated")
    validate_plan(plan)
    report = {
        "format": "latent-workspace-v14-precision-bridge-result-v1",
        "status": "QUALIFIED_EXECUTION",
        "winner": "none",
        "semantic_promotion": False,
        "runtime": runtime,
        "gpu": torch.cuda.get_device_name(),
        "plan_sha256": digest(PLAN),
        "source_identity": plan["source_identity"],
        "split_audit": audit,
        "base_state_sha256_before": base_before,
        "base_state_sha256_after": base_after,
        "base_unchanged": True,
        "base_native_split_exact": True,
        "base_control": "independently_loaded_pinned_original_not_old_task_checkpoint",
        "training": training,
        "step0_summary": step0["summary"],
        "single_summary": {k: v["summary"] for k, v in single.items()},
        "multiturn_summary": multi["summary"],
        "elapsed_seconds": time.monotonic() - started,
        "peak_cuda_bytes": torch.cuda.max_memory_allocated(),
        "feature_cache": {
            "train_prefix_forwards": train_store.prefix_forwards,
            "eval_prefix_forwards": eval_store.prefix_forwards,
            "storage": "CPU memory, not checkpointed",
        },
        "claim_boundary": plan["claim_boundary"],
    }
    atomic_write(output / "report.json", report)
    return {"status": report["status"], "output": str(output), "seconds": report["elapsed_seconds"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    plan = json.loads(PLAN.read_text())
    print(json.dumps(execute(plan, args.dry_run), indent=2))


if __name__ == "__main__":
    main()
