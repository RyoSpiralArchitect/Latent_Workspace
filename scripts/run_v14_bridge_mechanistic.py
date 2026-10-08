#!/usr/bin/env python3
"""Frozen failed-checkpoint MI on training worlds only, prior to any repair."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import torch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))
import run_v14_precision_bridge as prior  # noqa: E402
from run_v14_boundary_training import atomic_write, digest  # noqa: E402

from latent_workspace_ft_v10 import engine  # noqa: E402
from latent_workspace_ft_v10.bridge_mechanistic import (  # noqa: E402
    intervention_delta,
    parameter_norms,
    summarize_trace,
    trace_reader,
)
from latent_workspace_ft_v10.model_binding import FunctionalBoundaryAdapter  # noqa: E402
from latent_workspace_ft_v10.precision_bridge import (  # noqa: E402
    MistralPrecisionBridgeAdapter,
    PrecisionAwareWorkspaceBridge,
)

PLAN_PATH = REPO / "configs/v14/BRIDGE_MECHANISTIC_PLAN.json"
STATES = ("initial", "task128", "task256", "semantic128", "semantic256")


def scalar(x):
    return float(x.detach().float().item())


def contrast(a, b):
    a, b = a.float(), b.float()
    return {
        "l2": scalar((a - b).norm()),
        "relative_l2": scalar((a - b).norm() / a.norm().clamp_min(1e-12)),
        "max_abs": scalar((a - b).abs().max()),
    }


def describe(values):
    if not values:
        return {"count": 0, "mean": None, "min": None, "max": None}
    return {
        "count": len(values),
        "mean": sum(values) / len(values),
        "min": min(values),
        "max": max(values),
    }


def summarize(rows, pairs):
    result = {}
    for state in STATES:
        selected, comparisons = (
            [r for r in rows if r["state"] == state],
            [r for r in pairs if r["state"] == state],
        )
        metrics = {
            key: describe([r["metrics"][key] for r in selected])
            for key, value in selected[0]["metrics"].items()
            if isinstance(value, (float, int)) and not isinstance(value, bool)
        }
        interventions = {}
        for mode in selected[0]["interventions"]:
            interventions[mode] = {
                "delta_change_l2": describe(
                    [r["interventions"][mode]["contrast"]["l2"] for r in selected]
                ),
                "gap_change_abs": describe(
                    [abs(r["interventions"][mode]["gap_change"]) for r in selected]
                ),
            }
        stages = {
            key: {
                kind: describe([r["stages"][key][kind] for r in comparisons])
                for kind in ("l2", "relative_l2", "max_abs")
            }
            for key in comparisons[0]["stages"]
        }
        result[state] = {
            "trace_count": len(selected),
            "reverse_pair_count": len(comparisons),
            "metrics": metrics,
            "interventions": interventions,
            "reverse_stages": stages,
            "reverse_gap_difference_abs": describe([abs(r["gap_difference"]) for r in comparisons]),
        }
    return result


@torch.no_grad()
def execute():
    import transformers

    plan = json.loads(PLAN_PATH.read_text())
    old_plan = json.loads(prior.PLAN.read_text())
    prior.validate_plan(old_plan)
    previous = json.loads((REPO / plan["predecessor"]["path"]).read_text())
    if digest(REPO / plan["predecessor"]["path"]) != plan["predecessor"]["sha256"]:
        raise ValueError("Predecessor changed")
    for name, expected in plan["source_identity"].items():
        if digest(REPO / name) != expected:
            raise ValueError(f"Source changed: {name}")
    if (
        not plan["source_identity"]
        or plan["world_indices"] != list(range(16))
        or plan["states"] != list(STATES)
    ):
        raise ValueError("Unfrozen mechanistic grid")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True).strip():
        raise RuntimeError("Formal source tree must be clean")
    runtime = {
        "python": ".".join(map(str, sys.version_info[:3])),
        "torch": str(torch.__version__),
        "transformers": transformers.__version__,
        "cuda": torch.version.cuda,
    }
    if runtime != old_plan["expected_runtime"]:
        raise RuntimeError(f"Runtime changed: {runtime}")
    if subprocess.check_output(
        ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"], text=True
    ).strip():
        raise RuntimeError("GPU not idle")
    checkpoint_specs = {}
    for cell, receipt in previous["training"].items():
        for item in receipt["checkpoints"]:
            step = int(Path(item["path"]).stem.split("step")[1])
            checkpoint_specs[f"{cell}{step}"] = item
            if digest(REPO / item["path"]) != item["sha256"]:
                raise ValueError("Checkpoint changed")
    output = REPO / plan["output"]
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    atomic_write(
        output / "STARTED.json",
        {
            "plan_sha256": digest(PLAN_PATH),
            "source_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
            ).strip(),
        },
    )
    torch.set_num_threads(2)
    torch.set_float32_matmul_precision("highest")
    torch.backends.cuda.matmul.allow_tf32 = False
    device = torch.device("cuda")
    config = engine.ModelConfig(**old_plan["model"])
    tokenizer = engine.load_tokenizer(config)
    base = engine._load_hf_model(config).eval().requires_grad_(False).to(device)
    base_before = prior.state_hash(base)
    if base_before != previous["base_state_sha256_before"]:
        raise ValueError("Original model state changed")
    boundary = FunctionalBoundaryAdapter(base)
    adapter = MistralPrecisionBridgeAdapter(boundary)
    data_config = engine.DataConfig(
        **json.loads((REPO / old_plan["data_config_parent"]).read_text())["data"]
    )
    dataset = engine.JsonlFineTuningDataset(
        [str(REPO / old_plan["data"]["train"]["path"])], tokenizer, data_config
    )
    records = prior.load_records(REPO / old_plan["data"]["train"]["path"])[:16]
    store = prior.FeatureStore(records, dataset, tokenizer, boundary, adapter, device)
    store.prepare("MI training worlds only")
    axis_weights = base.lm_head.weight[list(store.candidate_ids)].float()
    axis = axis_weights[1] - axis_weights[0]

    def gap(delta):
        return scalar((delta.float() * axis).sum(-1))

    rows, pairs, identities = [], [], {}
    for state in STATES:
        torch.manual_seed(old_plan["training"]["seed"])
        bridge = (
            PrecisionAwareWorkspaceBridge(base.config.hidden_size, **old_plan["bridge"])
            .to(device)
            .float()
            .eval()
        )
        if state != "initial":
            payload = torch.load(
                REPO / checkpoint_specs[state]["path"], map_location=device, weights_only=True
            )
            bridge.load_state_dict(payload["state_dict"], strict=True)
        bridge.requires_grad_(False)
        before = prior.state_hash(bridge)
        if (
            state == "initial"
            and before != previous["training"]["semantic"]["initial_state_sha256"]
        ):
            raise ValueError("Initial state reproduction failed")
        identities[state] = {"state_sha256": before, "parameter_norms": parameter_norms(bridge)}
        for world in range(16):
            for side in (0, 1):
                context = store.context(world, side).to(device)
                memory, mask = bridge.write_memory(
                    context, torch.ones(context.shape[:2], device=device, dtype=torch.long)
                )
                traces = [
                    trace_reader(
                        bridge, store.query(world, q)[:, -1:].to(device).float(), memory, mask
                    )
                    for q in range(8)
                ]
                for q, trace in enumerate(traces):
                    metrics = summarize_trace(trace, candidate_head_weight=axis_weights)
                    interventions = {}
                    for mode in plan["interventions"]:
                        changed = intervention_delta(bridge, trace, mode, donor_trace=traces[q ^ 1])
                        interventions[mode] = {
                            "contrast": contrast(trace["delta"], changed),
                            "gap_change": gap(changed) - gap(trace["delta"]),
                            "delta_l2": scalar(changed.norm()),
                        }
                    # Manual reconstruction must reproduce the actual unchanged production module.
                    error = scalar((trace["delta"] - trace["manual_delta"]).abs().max())
                    if error > plan["manual_replication_atol"]:
                        raise ValueError(f"Manual intervention reconstruction failed: {error}")
                    rows.append(
                        {
                            "state": state,
                            "world_index": world,
                            "side": side,
                            "query_index": q,
                            "pair_id": records[world]["metadata"]["pair_id"],
                            "query_text": records[world]["queries"][q],
                            "metrics": metrics,
                            "delta_gap": gap(trace["delta"]),
                            "manual_delta_max_error": error,
                            "interventions": interventions,
                        }
                    )
                for q in (0, 2, 4, 6):
                    first, second = traces[q], traces[q + 1]
                    stages = {key: contrast(first[key], second[key]) for key in plan["stages"]}
                    pairs.append(
                        {
                            "state": state,
                            "world_index": world,
                            "side": side,
                            "query_indices": [q, q + 1],
                            "stages": stages,
                            "gap_difference": gap(second["delta"]) - gap(first["delta"]),
                        }
                    )
        if prior.state_hash(bridge) != before:
            raise ValueError("Frozen checkpoint changed during MI")
        print(f"traced {state}: {len(rows)} rows", flush=True)
        del bridge
    for spec in checkpoint_specs.values():
        if digest(REPO / spec["path"]) != spec["sha256"]:
            raise ValueError("Checkpoint body changed")
    if base_before != prior.state_hash(base):
        raise ValueError("Frozen original changed")
    if (len(rows), len(pairs)) != (1280, 640):
        raise ValueError("Trace grid did not close")
    report = {
        "format": "latent-workspace-v14-bridge-mechanistic-v1",
        "status": "QUALIFIED_EXECUTION",
        "winner": "none",
        "training": False,
        "eval_data_used": False,
        "plan_sha256": digest(PLAN_PATH),
        "source_identity": plan["source_identity"],
        "runtime": runtime,
        "rows": rows,
        "pairs": pairs,
        "summary": summarize(rows, pairs),
        "identities": identities,
        "checkpoint_inventory": checkpoint_specs,
        "frozen_weights_unchanged": True,
        "elapsed_seconds": time.monotonic() - started,
        "peak_cuda_bytes": torch.cuda.max_memory_allocated(),
        "claim_boundary": (
            "Training-world finite interventions on fixed compact reader, "
            "not full-model circuit proof or semantic improvement."
        ),
    }
    atomic_write(output / "report.json", report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "seconds": report["elapsed_seconds"],
                "output": str(output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    execute()
