#!/usr/bin/env python3
"""Bounded CPU-only, no-update audit of retained V14 learners on train worlds.

This is a new CPU arithmetic diagnostic, not a replay of CUDA results or a
qualification of offload, free generation, held-out quality, or FT-beta.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path

import torch
from torch.nn import functional as F

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
import run_v14_precision_bridge as prior  # noqa: E402
from v14_precision_bridge_eval import CONTROLS, _memories, _memory_key  # noqa: E402

from latent_workspace_ft_v10 import engine  # noqa: E402
from latent_workspace_ft_v10.bridge_reader_panel import capture_reverse_panel  # noqa: E402
from latent_workspace_ft_v10.contrastive_read_bridge import (  # noqa: E402
    CenteredValueWorkspaceBridge,
)
from latent_workspace_ft_v10.learner_gradient_audit import audit_loss_gradients  # noqa: E402
from latent_workspace_ft_v10.model_binding import FunctionalBoundaryAdapter  # noqa: E402
from latent_workspace_ft_v10.precision_bridge import (  # noqa: E402
    MistralPrecisionBridgeAdapter,
    PrecisionAwareWorkspaceBridge,
)


def write_new(path, value):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def reserialize(text):
    """Same facts and header; reverse only the order of already written sentences."""
    lines = text.splitlines()
    if not lines or not all(line.startswith("- ") for line in lines[1:]):
        raise ValueError("Unexpected fact serialization")
    return "\n".join([lines[0], *reversed(lines[1:])])


DIFFERENT_SCHEMA = (
    "Inventory facts. These describe cabinet contents, not a ranking.\n"
    "- The blue cabinet contains two copper cups.\n"
    "- The green cabinet contains three paper boxes.\n"
    "- The white cabinet is empty."
)


class CPUStore(prior.FeatureStore):
    """Keep original token renderer, split boundary, and final-position query.

    Explicit CPU BF16 execution replaces CUDA autocast. Every collected query
    prefix gets its own ordinary/full-head parity check on this CPU runtime.
    """

    def __init__(self, *args):
        self.native_gates = []
        super().__init__(*args)

    @torch.no_grad()
    def get_prefix(self, prefix):
        key = tuple(prefix)
        if key not in self.prefix_cache:
            ids = torch.tensor([key], dtype=torch.long)
            mask = torch.ones_like(ids)
            with torch.autocast("cpu", dtype=torch.bfloat16):
                hidden = self.adapter.encode_prefix(ids, mask, boundary_layer=16)
                actual = self.adapter.base_model(ids, attention_mask=mask, use_cache=False).logits
                decoded = self.adapter.decode(
                    hidden, torch.zeros_like(hidden[:, -1:]).float(), self.candidate_ids
                )
            exact = torch.equal(actual.float(), decoded.native_logits.float())
            if not exact:
                raise RuntimeError("CPU ordinary/split native parity failed; no tolerance retry")
            self.native_gates.append(
                {
                    "prefix_sha256": prior._stable_hash(key),
                    "token_count": len(key),
                    "full_logits_exact": exact,
                    "vocabulary_size": actual.shape[-1],
                }
            )
            self.prefix_cache[key] = hidden.detach().cpu()
            self.prefix_forwards += 1
        return self.prefix_cache[key]

    @torch.no_grad()
    def context(self, world, side):
        key = (world, side)
        if key not in self.context_cache:
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
            ids = torch.tensor([tokens], dtype=torch.long)
            with torch.autocast("cpu", dtype=torch.bfloat16):
                hidden = self.boundary.encode(ids, torch.ones_like(ids), 16)
            self.context_cache[key] = hidden.detach().cpu()
        return self.context_cache[key]


def gradient_batch(bridge, store, weight, contract, cell):
    """Rebuild the existing objective, without optimizer construction or steps."""
    batch = [(world, q) for world in range(len(store.records)) for q in range(8)]
    query = torch.cat([store.query(w, q)[:, -1:] for w, q in batch]).float()
    contexts = [store.context(w, side) for side in (0, 1, "unrelated") for w, q in batch]
    context, mask = prior.pad_contexts(contexts, torch.device("cpu"))
    memory, memory_mask = bridge.write_memory(context, mask)
    delta = bridge.read_delta(query.repeat(3, 1, 1), memory, memory_mask)
    scores0, scores1, unrelated = (
        F.linear(query.repeat(3, 1, 1) + delta, weight).squeeze(1).chunk(3)
    )
    base_scores = F.linear(query, weight).squeeze(1)
    labels = torch.tensor([[store.records[w]["answers"][s][q] for s in (0, 1)] for w, q in batch])
    affected = labels[:, 0] != labels[:, 1]
    total, components = prior.objective(
        scores0, scores1, unrelated, base_scores, labels, affected, delta, cell, contract
    )
    components.pop("loss")
    weights = {
        "paired_ce": 1.0,
        "donor_hinge": contract["direction_weight"] if cell == "semantic" else 0.0,
        "unaffected_gap_square": contract["stability_weight"] if cell == "semantic" else 0.0,
        "unrelated_gap_square": contract["unrelated_weight"] if cell == "semantic" else 0.0,
        "residual_norm_square": contract["residual_penalty"],
    }
    donor = (2 * labels[:, 1] - 1) * (scores1[:, 1] - scores1[:, 0] - scores0[:, 1] + scores0[:, 0])
    even = torch.tensor([q % 2 == 0 for _, q in batch]) & affected
    odd = ~torch.tensor([q % 2 == 0 for _, q in batch]) & affected
    if not even.any() or not odd.any():
        raise ValueError("Reciprocal donor diagnostic requires both affected directions")
    diagnostics = {
        "donor_even_hinge": F.relu(contract["donor_margin"] - donor[even]).mean(),
        "donor_odd_hinge": F.relu(contract["donor_margin"] - donor[odd]).mean(),
    }
    result = audit_loss_gradients(
        bridge,
        components,
        weights,
        total_loss=total,
        diagnostic_components=diagnostics,
        frozen_tensors={"query": query, "context": context, "head_rows": weight},
    )
    result["batch"] = {
        "world_query_order": batch,
        "affected_count": int(affected.sum()),
        "unaffected_count": int((~affected).sum()),
        "objective_cell": cell,
        "donor_margins": donor.detach().tolist(),
        "query_representation": "original_final_normalized_last_prefix_position",
        "not_a_training_schedule_replay": True,
    }
    return result


@torch.no_grad()
def controls(bridge, store, weight, adapter):
    rows, zero_checks = [], 0
    for world in range(len(store.records)):
        memories = _memories(bridge, store, world, "cpu")
        for key in ("different_schema", "reserialized_0", "reserialized_1"):
            context = store.context(world, key).float()
            memories[key] = bridge.write_memory(
                context, torch.ones(context.shape[:2], dtype=torch.long)
            )
        for q in range(8):
            hidden = store.query(world, q)
            query = hidden[:, -1:].float()
            # Preserve the same materialized FP32 composition geometry as the
            # intervention and historical adapter.decode(delta=0). A final-row
            # view can have different strides/alignment despite being contiguous.
            baseline = F.linear(query + torch.zeros_like(query), weight).squeeze()
            zero, zero_mask = memories["zero"]
            actual_zero = bridge.read_delta(query, zero, zero_mask)
            if torch.count_nonzero(actual_zero):
                raise RuntimeError("Written-zero intervention produced a residual")
            with torch.autocast("cpu", dtype=torch.bfloat16):
                a = adapter.decode(hidden, actual_zero, store.candidate_ids).native_logits
                b = adapter.decode(
                    hidden, torch.zeros_like(actual_zero), store.candidate_ids
                ).native_logits
            if not torch.equal(a, b):
                raise RuntimeError("Written-zero full-vocabulary parity failed")
            zero_checks += 1
            for side in (0, 1):
                for control in (*CONTROLS, "different_schema", "same_world_reserialization"):
                    key = (
                        f"reserialized_{side}"
                        if control == "same_world_reserialization"
                        else "different_schema"
                        if control == "different_schema"
                        else _memory_key(control, side)
                    )
                    memory, mask = memories[key]
                    delta = bridge.read_delta(query, memory, mask)
                    scores = F.linear(query + delta, weight).squeeze()
                    rows.append(
                        {
                            "world": world,
                            "query": q,
                            "side": side,
                            "control": control,
                            "scores": scores.tolist(),
                            "base_scores": baseline.tolist(),
                            "yes_minus_no": float(scores[1] - scores[0]),
                            "delta_l2": float(delta.norm()),
                            "memory_l2": float(memory.norm()),
                            "slot_l2": memory.norm(dim=-1).tolist(),
                            "original_label": store.records[world]["answers"][side][q],
                            "twin_label": store.records[world]["answers"][1 - side][q],
                        }
                    )
    return {
        "rows": rows,
        "zero_full_logit_checks": zero_checks,
        "scope": "CPU_train_only_two_candidate_no_generation",
        "different_schema_amplitude_matched": False,
        "random_matching": "historical_global_raw_memory_L2",
    }


def execute(checkpoint_root, output, world_count):
    import transformers

    if world_count != 2:
        raise ValueError("This bounded diagnostic is frozen to first two train worlds")
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "":
        raise RuntimeError("Launch with CUDA_VISIBLE_DEVICES='' to enforce CPU-only execution")
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.set_float32_matmul_precision("highest")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    plan = json.loads(prior.PLAN.read_text())
    train, _, split = prior.validate_plan(plan)
    reports = {
        "legacy": json.loads(
            (REPO / "provenance/pilots/v14_precision_bridge_20261009/raw/report.json").read_text()
        ),
        "centered": json.loads(
            (REPO / "provenance/pilots/v14_mech_repair_20261009/repair/report.json").read_text()
        ),
    }
    receipt = {
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip(),
        "source_hashes": {
            name: prior.digest(REPO / name)
            for name in (
                "scripts/run_ft_beta_learner_audit.py",
                "src/latent_workspace_ft_v10/learner_gradient_audit.py",
            )
        },
        "python": sys.version.split()[0],
        "torch": str(torch.__version__),
        "transformers": transformers.__version__,
        "device": "cpu",
        "torch_threads": 2,
        "cuda_visible_devices": "",
        "optimizer_steps": 0,
        "world_indices": [0, 1],
        "dataset_split": "train_only_exposed",
        "split_audit": split,
    }
    write_new(output / "STARTED.json", receipt)
    print("loading pinned frozen base on CPU; CUDA disabled", flush=True)
    config = engine.ModelConfig(**plan["model"])
    tokenizer = engine.load_tokenizer(config)
    base = engine._load_hf_model(config).eval().requires_grad_(False)
    if any(p.device.type != "cpu" for p in base.parameters()):
        raise RuntimeError("Non-CPU base parameter")
    base_hash = prior.state_hash(base)
    if base_hash != reports["legacy"]["base_state_sha256_before"]:
        raise RuntimeError("Pinned base identity mismatch")
    versions = {n: p._version for n, p in base.named_parameters()}
    boundary = FunctionalBoundaryAdapter(base)
    adapter = MistralPrecisionBridgeAdapter(boundary)
    data_config = engine.DataConfig(
        **json.loads((REPO / plan["data_config_parent"]).read_text())["data"]
    )
    dataset = engine.JsonlFineTuningDataset(
        [str(REPO / plan["data"]["train"]["path"])], tokenizer, data_config
    )
    store = CPUStore(
        train[:world_count], dataset, tokenizer, boundary, adapter, torch.device("cpu")
    )
    store.prepare("bounded CPU train-only")
    for world in range(world_count):
        for key in ("different_schema", "reserialized_0", "reserialized_1"):
            store.context(world, key)
    head = base.lm_head.weight.detach()[list(store.candidate_ids)].float()
    if base.lm_head.bias is not None:
        raise RuntimeError("Diagnostic contract requires bias-free pinned head")
    write_new(
        output / "FEATURES.json",
        {
            "native_gates": store.native_gates,
            "candidate_ids": store.candidate_ids,
            "prefix_forwards": store.prefix_forwards,
            "cache_tensor_bytes": sum(
                t.numel() * t.element_size()
                for t in (*store.prefix_cache.values(), *store.context_cache.values())
            ),
            "query_token_ids": [
                [list(store.prefix(store.features[w], q)) for q in range(8)]
                for w in range(world_count)
            ],
            "different_schema_text": DIFFERENT_SCHEMA,
            "feature_dtype": str(next(iter(store.prefix_cache.values())).dtype),
            "CPU_CUDA_numerical_equivalence": "NOT_TESTED",
        },
    )
    summaries = {}
    for name, family, cell in (
        ("initial", "legacy", "semantic"),
        ("legacy_task256", "legacy", "task"),
        ("legacy_semantic256", "legacy", "semantic"),
        ("centered_semantic256", "centered", "semantic"),
    ):
        print(f"auditing {name}: no optimizer", flush=True)
        torch.manual_seed(plan["training"]["seed"])
        cls = PrecisionAwareWorkspaceBridge if family == "legacy" else CenteredValueWorkspaceBridge
        bridge = cls(base.config.hidden_size, **plan["bridge"]).float().eval()
        checkpoint = None
        if name != "initial":
            checkpoint = next(
                x
                for x in reports[family]["training"][cell]["checkpoints"]
                if x["path"].endswith(f"/{cell}_step256.pt")
            )
            path = checkpoint_root / checkpoint["path"]
            if (
                path.stat().st_size != checkpoint["bytes"]
                or prior.digest(path) != checkpoint["sha256"]
            ):
                raise RuntimeError("Checkpoint bytes changed")
            payload = torch.load(path, map_location="cpu", weights_only=True)
            if (
                payload["base_revision"] != plan["model"]["revision"]
                or payload["step"] != 256
                or payload["cell"] != cell
            ):
                raise RuntimeError("Checkpoint metadata mismatch")
            bridge.load_state_dict(payload["state_dict"], strict=True)
            del payload
        before = prior.state_hash(bridge)
        expected = reports[family]["training"][cell][
            "initial_state_sha256" if name == "initial" else "final_state_sha256"
        ]
        if before != expected:
            raise RuntimeError("Bridge state identity mismatch")
        gradients = gradient_batch(bridge, store, head, plan["training"], cell)
        if not gradients["reconstruction"]["passed"]:
            write_new(output / f"{name}_gradients_failed.json", gradients)
            raise RuntimeError("Gradient reconstruction failed; no tolerance relaxation")
        panel = capture_reverse_panel(bridge, store, head, "cpu", world_count=world_count)
        control = controls(bridge, store, head, adapter)
        if prior.state_hash(bridge) != before or any(
            p.grad is not None for p in bridge.parameters()
        ):
            raise RuntimeError("Diagnostic mutated bridge state or accumulated gradients")
        for suffix, value in (("gradients", gradients), ("reader", panel), ("controls", control)):
            write_new(output / f"{name}_{suffix}.json", value)
        summaries[name] = {
            "state_sha256": before,
            "checkpoint": checkpoint,
            "parameters": sum(p.numel() for p in bridge.parameters()),
            "unchanged": True,
            "zero_checks": control["zero_full_logit_checks"],
            "reader_summary": panel["summary"],
        }
        del bridge, gradients, panel, control
        gc.collect()
    if versions != {n: p._version for n, p in base.named_parameters()} or any(
        p.grad is not None for p in base.parameters()
    ):
        raise RuntimeError("Frozen base mutation")
    base_after = prior.state_hash(base)
    if base_after != base_hash:
        raise RuntimeError("Frozen base state changed")
    parameter_bytes = sum(p.numel() * p.element_size() for p in base.parameters())
    layer_bytes = [
        sum(p.numel() * p.element_size() for p in layer.parameters()) for layer in base.model.layers
    ]
    result = {
        "status": "COMPLETED_CPU_TRAIN_ONLY_DIAGNOSTIC",
        "receipt": receipt,
        "base_state_sha256_before": base_hash,
        "base_state_sha256_after": base_after,
        "states": summaries,
        "elapsed_seconds": time.monotonic() - started,
        "peak_process_rss_bytes_linux": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "cuda_initialized": torch.cuda.is_initialized(),
        "cuda_allocated_bytes": 0,
        "base_parameter_count": sum(p.numel() for p in base.parameters()),
        "base_parameter_bytes": parameter_bytes,
        "decoder_layer_parameter_bytes": layer_bytes,
        "historical_cuda_peak_allocated_bytes": reports["legacy"]["peak_cuda_bytes"],
        "free_text_legacy_controls": "NOT_RUN",
        "new_offload_parity": "NOT_TESTED",
        "statistical_or_quality_qualification": False,
        "winner": "none",
    }
    if result["cuda_initialized"]:
        raise RuntimeError("CPU-only contract violated")
    write_new(output / "REPORT.json", result)
    return {
        k: result[k]
        for k in ("status", "elapsed_seconds", "cuda_initialized", "peak_process_rss_bytes_linux")
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--world-count", type=int, default=2)
    args = parser.parse_args()
    print(
        json.dumps(execute(args.checkpoint_root.resolve(), args.output.resolve(), args.world_count))
    )
