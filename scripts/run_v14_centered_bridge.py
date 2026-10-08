#!/usr/bin/env python3
"""Train one MI-selected value-centering change, then score one fresh heldout set."""

from __future__ import annotations

import argparse
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
import prepare_v14_mech_corpus as corpus  # noqa: E402
import run_v14_precision_bridge as prior  # noqa: E402
from run_v14_boundary_training import atomic_write, digest, resolve_inside  # noqa: E402
from run_v14_multiturn_choice import _project_scenarios, _stable_hash  # noqa: E402

from latent_workspace_ft_v10 import engine  # noqa: E402
from latent_workspace_ft_v10.bridge_mechanistic import (  # noqa: E402
    intervention_delta,
    trace_reader,
)
from latent_workspace_ft_v10.bridge_reader_panel import capture_reverse_panel  # noqa: E402
from latent_workspace_ft_v10.contrastive_read_bridge import (  # noqa: E402
    CenteredValueWorkspaceBridge,
)
from latent_workspace_ft_v10.model_binding import FunctionalBoundaryAdapter  # noqa: E402
from latent_workspace_ft_v10.precision_bridge import (  # noqa: E402
    MistralPrecisionBridgeAdapter,
    PrecisionAwareWorkspaceBridge,
)

PLAN = REPO / "configs/v14/CENTERED_BRIDGE_PLAN.json"
CELLS = ("task", "semantic")
FAMILIES = ("legacy", "centered")
NEW_SOURCES = (
    "scripts/run_v14_centered_bridge.py",
    "scripts/prepare_v14_mech_corpus.py",
    "src/latent_workspace_ft_v10/contrastive_read_bridge.py",
    "src/latent_workspace_ft_v10/bridge_reader_panel.py",
    "src/latent_workspace_ft_v10/bridge_mechanistic.py",
)


def training_schedule(world_count, training):
    """The old seed, epoch shuffle, truncation, and world/query order unchanged."""
    examples = [(world, query) for world in range(world_count) for query in range(8)]
    rng = random.Random(training["seed"])
    schedule = []
    while len(schedule) < training["steps"] * training["batch_size"]:
        epoch = list(examples)
        rng.shuffle(epoch)
        schedule.extend(epoch)
    return schedule[: training["steps"] * training["batch_size"]]


def train_cell(cell, store, base, plan, output, device):
    """Old training algorithm with only the bridge forward implementation changed."""
    t = plan["training"]
    torch.manual_seed(t["seed"])
    bridge = CenteredValueWorkspaceBridge(base.config.hidden_size, **plan["bridge"])
    bridge = bridge.to(device).float().train()
    initial = prior.state_hash(bridge)
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
    schedule = training_schedule(len(store.records), t)
    rows, saves = [], []
    upstream_nonzero = False
    for step in range(1, t["steps"] + 1):
        batch = schedule[(step - 1) * t["batch_size"] : step * t["batch_size"]]
        query = torch.cat([store.query(w, q)[:, -1:] for w, q in batch]).to(device).float()
        contexts = [store.context(w, side) for side in (0, 1, "unrelated") for w, q in batch]
        context, mask = prior.pad_contexts(contexts, device)
        memory, memory_mask = bridge.write_memory(context, mask)
        delta = bridge.read_delta(query.repeat(3, 1, 1), memory, memory_mask)
        scores = F.linear(query.repeat(3, 1, 1) + delta, weight, bias).squeeze(1)
        scores0, scores1, unrelated = scores.chunk(3)
        base_scores = F.linear(query, weight, bias).squeeze(1)
        labels = torch.tensor(
            [[store.records[w]["answers"][side][q] for side in (0, 1)] for w, q in batch],
            device=device,
        )
        affected = labels[:, 0] != labels[:, 1]
        loss, components = prior.objective(
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
            for name, p in bridge.named_parameters()
            if name.startswith("writer.") and p.grad is not None
        )
        query_gradient = bridge.query_projection.weight.grad
        attention_gradient = bridge.attention.in_proj_weight.grad
        query_gradient_norm = float(query_gradient.norm()) if query_gradient is not None else 0.0
        attention_q_gradient_norm = (
            float(attention_gradient[: bridge.workspace_dim].norm())
            if attention_gradient is not None
            else 0.0
        )
        upstream_nonzero |= step > 1 and writer_grad > 0
        norm = torch.nn.utils.clip_grad_norm_(bridge.parameters(), t["max_grad_norm"])
        optimizer.step()
        rows.append(
            {
                "step": step,
                "loss_parameter_step": step - 1,
                "world_query_count": len(batch),
                "affected_count": int(affected.sum()),
                **{key: float(value.detach()) for key, value in components.items()},
                "writer_gradient_norm_sum": writer_grad,
                "query_projection_gradient_l2": query_gradient_norm,
                "attention_q_projection_gradient_l2": attention_q_gradient_norm,
                "gradient_observation_before_clipping": True,
                "unclipped_grad_norm": float(norm),
            }
        )
        if step == 1 or step % 32 == 0:
            print(
                f"training centered {cell} {step}/{t['steps']} loss={float(loss.detach()):.6f}",
                flush=True,
            )
        if step in t["save_steps"]:
            path = output / f"{cell}_step{step}.pt"
            if path.exists():
                raise FileExistsError(path)
            torch.save(
                {
                    "state_dict": bridge.state_dict(),
                    "step": step,
                    "cell": cell,
                    "bridge_kind": "centered_values",
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
    if not upstream_nonzero or prior.state_hash(bridge) == initial:
        raise RuntimeError("Centered bridge upstream learning not observed")
    bridge.eval()
    reloaded = CenteredValueWorkspaceBridge(base.config.hidden_size, **plan["bridge"])
    reloaded = reloaded.to(device).float()
    payload = torch.load(
        output / f"{cell}_step{t['steps']}.pt", map_location=device, weights_only=True
    )
    reloaded.load_state_dict(payload["state_dict"], strict=True)
    if prior.state_hash(reloaded) != prior.state_hash(bridge):
        raise RuntimeError("Saved centered bridge reload mismatch")
    return bridge, {
        "initial_state_sha256": initial,
        "final_state_sha256": prior.state_hash(bridge),
        "schedule_sha256": _stable_hash(schedule),
        "rows": rows,
        "checkpoints": saves,
        "writer_gradient_nonzero_after_step1": upstream_nonzero,
        "final_checkpoint_reload_exact": True,
        "trainable_parameters": sum(p.numel() for p in bridge.parameters()),
        "resumed_from_old_weights": False,
    }


def _read_bound(spec, label):
    path = resolve_inside(REPO, spec["path"], label=label)
    if digest(path) != spec["sha256"]:
        raise ValueError(f"{label} identity changed")
    return json.loads(path.read_text())


def validate_plan(plan):
    if (
        plan["format"] != "latent-workspace-v14-centered-bridge-plan-v1"
        or plan["semantic_promotion"] is not False
    ):
        raise ValueError("Frozen centered pilot plan changed")
    old_plan = json.loads(prior.PLAN.read_text())
    old_train, old_eval, _ = prior.validate_plan(old_plan)
    for name in (
        "model",
        "bridge",
        "training",
        "data_config_parent",
        "scenarios",
        "expected_runtime",
    ):
        if plan[name] != old_plan[name]:
            raise ValueError(f"Matched {name} contract changed")
    if plan["data"]["train"] != old_plan["data"]["train"]:
        raise ValueError("Matched training data changed")
    if plan["output"] != "runs/v14/centered_bridge_20261009":
        raise ValueError("Unexpected centered output location")
    if not plan["source_identity"]:
        raise ValueError("Source identity must be frozen before execution")
    if not set(NEW_SOURCES) <= plan["source_identity"].keys():
        raise ValueError("New source identity coverage is incomplete")
    for path, sha in plan["source_identity"].items():
        if digest(resolve_inside(REPO, path, label="source")) != sha:
            raise ValueError(f"Source identity changed: {path}")
    previous = _read_bound(plan["predecessor"], "Prior bridge report")
    trace = _read_bound(plan["predecessor_trace"], "Mechanistic predecessor")
    preparation = _read_bound(plan["fresh_preparation"], "Fresh preparation")
    if (
        previous["status"] != "QUALIFIED_EXECUTION"
        or previous["plan_sha256"] != digest(prior.PLAN)
        or previous["base_unchanged"] is not True
        or previous["base_state_sha256_before"] != previous["base_state_sha256_after"]
    ):
        raise ValueError("Prior bridge execution is not qualified")
    if (
        trace["status"] != "QUALIFIED_EXECUTION"
        or trace["eval_data_used"] is not False
        or trace["training"] is not False
        or trace["frozen_weights_unchanged"] is not True
        or trace["identities"]["initial"]["state_sha256"]
        != previous["training"]["task"]["initial_state_sha256"]
    ):
        raise ValueError("Mechanistic predecessor is not a frozen train-only trace")
    for cell in CELLS:
        for spec in previous["training"][cell]["checkpoints"]:
            step = int(Path(spec["path"]).stem.split("step")[1])
            if trace["checkpoint_inventory"][f"{cell}{step}"] != spec:
                raise ValueError("Mechanistic predecessor checkpoint inventory changed")
    if (
        preparation["status"] != "PREPARED_NOT_EVALUATED"
        or preparation["seed"] != corpus.SEED
        or preparation["candidate_pool_world_pairs"] != 128
        or preparation["accepted_world_pairs"] != 64
        or preparation["fresh_corpus"]["sha256"] != plan["data"]["eval"]["sha256"]
    ):
        raise ValueError("Fresh preparation contract changed")
    eval_path = resolve_inside(REPO, plan["data"]["eval"]["path"], label="fresh data")
    prepared_path = (
        resolve_inside(REPO, plan["fresh_preparation"]["path"], label="preparation").parent
        / preparation["fresh_corpus"]["path"]
    ).resolve()
    if eval_path != prepared_path or digest(eval_path) != preparation["fresh_corpus"]["sha256"]:
        raise ValueError("Fresh dataset identity changed")
    fresh = prior.load_records(eval_path)
    if len(fresh) != 64 or len(old_train) != 256 or len(old_eval) != 64:
        raise ValueError("Dataset denominator changed")
    audit = corpus.audit_disjoint(old_train + old_eval, fresh)
    if audit != preparation["split_audit"]:
        raise ValueError("Fresh split audit drifted")
    for record in old_train + fresh:
        prior.unrelated_context(record)
        if record["choices"] != [" no", " yes"]:
            raise ValueError("Choice mapping changed")
    return old_train, fresh, audit, previous


def match_training_receipt(actual, expected):
    for key in ("initial_state_sha256", "schedule_sha256", "trainable_parameters"):
        if actual[key] != expected[key]:
            raise ValueError(f"Matched training receipt changed: {key}")


def checkpoint_inventory(previous, verify_bodies=True):
    inventory = {}
    for cell in CELLS:
        for spec in previous["training"][cell]["checkpoints"]:
            path = resolve_inside(REPO, spec["path"], label="legacy checkpoint")
            step = int(path.stem.split("step")[1])
            if verify_bodies and (
                path.stat().st_size != spec["bytes"] or digest(path) != spec["sha256"]
            ):
                raise ValueError(f"Legacy checkpoint changed: {cell}{step}")
            inventory[f"{cell}{step}"] = spec
    if set(inventory) != {f"{cell}{step}" for cell in CELLS for step in (128, 256)}:
        raise ValueError("Legacy checkpoint inventory is incomplete")
    return inventory


def verify_denominators(single, multi):
    if set(single) != {f"{family}_{cell}" for family in FAMILIES for cell in CELLS}:
        raise ValueError("Single-turn condition grid changed")
    if set(multi) != set(FAMILIES):
        raise ValueError("Four-turn family grid changed")
    if any(item["row_count"] != 6144 or len(item["rows"]) != 6144 for item in single.values()):
        raise ValueError("Single-turn denominator did not close")
    if any(
        item["trajectory_count"] != 896
        or item["turn_count"] != 3584
        or len(item["rows"]) != 896
        or any(len(row["turns"]) != 4 for row in item["rows"])
        for item in multi.values()
    ):
        raise ValueError("Four-turn denominator did not close")
    return {"single_rows": 24576, "trajectories": 1792, "turns": 7168}


@torch.no_grad()
def initial_identity_gate(plan, previous, base, store, adapter, device):
    prefix = prior.FeatureStore.prefix(store.features[0], 0)
    ids = torch.tensor([prefix], device=device)
    with torch.autocast("cuda", dtype=torch.bfloat16):
        native = base(ids, attention_mask=torch.ones_like(ids), use_cache=False).logits
        normalized = store.get_prefix(prefix).to(device)
        baseline = adapter.decode(
            normalized, torch.zeros_like(normalized[:, -1:]).float(), store.candidate_ids
        )
    if not torch.equal(native.float(), baseline.native_logits.float()):
        raise RuntimeError("Original base / split-native identity failed")
    checks = {}
    for family, cls in (
        ("legacy", PrecisionAwareWorkspaceBridge),
        ("centered", CenteredValueWorkspaceBridge),
    ):
        torch.manual_seed(plan["training"]["seed"])
        bridge = cls(base.config.hidden_size, **plan["bridge"]).to(device).float().eval()
        state = prior.state_hash(bridge)
        if any(state != previous["training"][cell]["initial_state_sha256"] for cell in CELLS):
            raise RuntimeError("Archived initial bridge state did not reproduce")
        context = store.context(0, 0).to(device)
        memory, mask = bridge.write_memory(
            context, torch.ones(context.shape[:2], device=device, dtype=torch.long)
        )
        delta = bridge.read_delta(normalized[:, -1:].float(), memory, mask)
        decoded = adapter.decode(normalized, delta, store.candidate_ids)
        if (
            bool(delta.count_nonzero())
            or not torch.equal(decoded.native_logits, baseline.native_logits)
            or not torch.equal(decoded.fp32_choice_scores, baseline.fp32_choice_scores)
        ):
            raise RuntimeError("Initial bridge does not exactly reproduce original base")
        checks[family] = {"initial_state_sha256": state, "zero_delta_native_fp32_exact": True}
    return {
        "base_native_split_exact": True,
        "sample": "training world0 side0 query0",
        "families": checks,
    }


@torch.no_grad()
def centered_intervention_identity_gate(legacy, store, plan, device):
    """Real-width gate: new production class versus intervention on OLD class only."""
    clone = CenteredValueWorkspaceBridge(legacy.hidden_dim, **plan["bridge"])
    clone.load_state_dict(legacy.state_dict(), strict=True)
    clone = clone.to(device).float().eval().requires_grad_(False)
    if prior.state_hash(clone) != prior.state_hash(legacy):
        raise ValueError("Centered intervention clone weights differ")
    context = store.context(0, 0).to(device)
    memory, mask = legacy.write_memory(
        context, torch.ones(context.shape[:2], device=device, dtype=torch.long)
    )
    query = store.query(0, 0)[:, -1:].to(device).float()
    # The old trace reconstructs only the unchanged legacy class; never the centered one.
    trace = trace_reader(legacy, query, memory, mask)
    expected = intervention_delta(legacy, trace, "centered_values")
    actual = clone.read_delta(query, memory, mask)
    error = float((actual - expected).abs().max())
    if not torch.isfinite(actual).all() or error > 1e-5:
        raise ValueError(f"Actual centered/intervention equivalence failed: {error}")
    return {
        "sample": "training world0 side0 query0; archived semantic256 weights",
        "max_absolute_error": error,
        "absolute_tolerance": 1e-5,
        "passed": True,
        "clone_saved": False,
        "legacy_trace_used_only_on_legacy_class": True,
    }


def execute(plan, dry_run=False):
    train, evaluation, audit, previous = validate_plan(plan)
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
    inventory = checkpoint_inventory(previous)
    output = resolve_inside(REPO, plan["output"], label="output")
    output.mkdir(parents=True, exist_ok=False)
    source_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
    ).strip()
    atomic_write(
        output / "STARTED.json",
        {"plan_sha256": digest(PLAN), "runtime": runtime, "source_commit": source_commit},
    )
    started = time.monotonic()
    device = torch.device("cuda")
    torch.set_num_threads(2)
    torch.set_float32_matmul_precision("highest")
    torch.backends.cuda.matmul.allow_tf32 = False
    config = engine.ModelConfig(**plan["model"])
    tokenizer = engine.load_tokenizer(config)
    base = engine._load_hf_model(config).eval().requires_grad_(False).to(device)
    base_before = prior.state_hash(base)
    if base_before != previous["base_state_sha256_before"]:
        raise ValueError("Pinned original base state differs from previous experiment")
    versions = {name: param._version for name, param in base.named_parameters()}
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
        stores.append(prior.FeatureStore(records, dataset, tokenizer, boundary, adapter, device))
    train_store, eval_store = stores
    initial = initial_identity_gate(plan, previous, base, train_store, adapter, device)
    atomic_write(output / "INITIAL_IDENTITY.json", initial)
    train_store.prepare("train")
    # No evaluation forward or scoring is performed before both training cells finish.
    bridges = {family: {} for family in FAMILIES}
    training = {}
    for cell in CELLS:
        bridges["centered"][cell], training[cell] = train_cell(
            cell, train_store, base, plan, output, device
        )
        match_training_receipt(training[cell], previous["training"][cell])
        atomic_write(output / f"training_{cell}.json", training[cell])
    legacy_states_before = {}
    for cell in CELLS:
        bridge = PrecisionAwareWorkspaceBridge(base.config.hidden_size, **plan["bridge"])
        payload = torch.load(
            REPO / inventory[f"{cell}256"]["path"], map_location=device, weights_only=True
        )
        if (
            payload["step"] != 256
            or payload["cell"] != cell
            or payload["plan_sha256"] != digest(prior.PLAN)
            or payload["base_revision"] != plan["model"]["revision"]
        ):
            raise ValueError("Legacy checkpoint payload metadata changed")
        bridge.load_state_dict(payload["state_dict"], strict=True)
        bridge = bridge.to(device).float().eval().requires_grad_(False)
        before = prior.state_hash(bridge)
        if before != previous["training"][cell]["final_state_sha256"]:
            raise ValueError("Legacy checkpoint state identity changed")
        legacy_states_before[cell] = before
        bridges["legacy"][cell] = bridge
        del payload
    intervention_identity = centered_intervention_identity_gate(
        bridges["legacy"]["semantic"], train_store, plan, device
    )
    atomic_write(output / "CENTERED_INTERVENTION_IDENTITY.json", intervention_identity)
    panels = {}
    candidate_weights = base.lm_head.weight[list(train_store.candidate_ids)].detach().float()
    for family in FAMILIES:
        for cell in CELLS:
            name = f"{family}_{cell}"
            print(f"reader panel training worlds only {name}", flush=True)
            panels[name] = capture_reverse_panel(
                bridges[family][cell], train_store, candidate_weights, device, world_count=16
            )
    atomic_write(output / "reader_panels.json", panels)
    eval_store.prepare("fresh evaluation; training is complete")
    single = {}
    for family in FAMILIES:
        for cell in CELLS:
            name = f"{family}_{cell}"
            print(f"evaluation single {name}", flush=True)
            single[name] = evaluate_single(
                bridges[family][cell], eval_store, adapter, eval_store.candidate_ids, device
            )
            atomic_write(output / f"single_{name}.json", single[name])
    scenarios = _project_scenarios(eval_store.dataset, tokenizer, plan)
    multi = {}
    for family in FAMILIES:
        print(f"evaluation four-turn {family}", flush=True)
        multi[family] = evaluate_multiturn(
            bridges[family],
            eval_store,
            adapter,
            tokenizer,
            scenarios,
            eval_store.candidate_ids,
            device,
        )
        atomic_write(output / f"multiturn_{family}.json", multi[family])
    denominators = verify_denominators(single, multi)
    base_after = prior.state_hash(base)
    if (
        base_before != base_after
        or versions != {name: param._version for name, param in base.named_parameters()}
        or any(param.grad is not None for param in base.parameters())
    ):
        raise RuntimeError("Frozen original base mutated")
    legacy_states_after = {cell: prior.state_hash(bridges["legacy"][cell]) for cell in CELLS}
    if legacy_states_after != legacy_states_before or checkpoint_inventory(previous) != inventory:
        raise RuntimeError("Frozen legacy bridge or checkpoint changed")
    for cell in CELLS:
        if prior.state_hash(bridges["centered"][cell]) != training[cell]["final_state_sha256"]:
            raise RuntimeError("Centered bridge mutated during evaluation")
    validate_plan(plan)
    report = {
        "format": "latent-workspace-v14-centered-bridge-result-v1",
        "status": "QUALIFIED_EXECUTION",
        "winner": "none",
        "semantic_promotion": False,
        "runtime": runtime,
        "gpu": torch.cuda.get_device_name(),
        "source_commit": source_commit,
        "plan_sha256": digest(PLAN),
        "source_identity": plan["source_identity"],
        "predecessor": plan["predecessor"],
        "predecessor_trace": plan["predecessor_trace"],
        "fresh_preparation": plan["fresh_preparation"],
        "split_audit": audit,
        "base_state_sha256_before": base_before,
        "base_state_sha256_after": base_after,
        "base_unchanged": True,
        "base_native_split_exact": True,
        "initial_identity": initial,
        "centered_intervention_identity": intervention_identity,
        "panel_summary": {name: panel["summary"] for name, panel in panels.items()},
        "panel_uses_training_worlds_only": True,
        "base_control": "independently_loaded_pinned_original",
        "training": training,
        "training_matches_archived_initialization_schedule_and_parameter_count": True,
        "legacy_checkpoint_inventory": inventory,
        "legacy_states_before": legacy_states_before,
        "legacy_states_after": legacy_states_after,
        "legacy_checkpoint_bodies_unchanged": True,
        "single_summary": {name: result["summary"] for name, result in single.items()},
        "multiturn_summary": {name: result["summary"] for name, result in multi.items()},
        "denominators": denominators,
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
