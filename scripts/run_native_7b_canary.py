#!/usr/bin/env python3
"""Bounded native-memory updates and exact fresh-process replay; no quality claim."""

from __future__ import annotations

import gc
import importlib.util
import inspect
import os
import random
import resource
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from latent_workspace import execution as ex  # noqa: E402

ENTRY = "scripts/run_native_7b_canary.py"
PLAN = "configs/v1_0/NATIVE_7B_CANARY_RECOVERY_01.json"
PLAN_SHA256 = "6f692b785185c60f294925a25fa22e3ee2774a86c85e0372240cc159a8657526"
TINY_PASS = "TINY_NATIVE_CANARY_HARNESS_PASS_NOT_7B"
ROLES = ("primary", "replay")
STATUSES = {"primary": "TWO_NATIVE_UPDATES_SAVED", "replay": "EXACT_NATIVE_STEP2_REPLAY"}


def load(name):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def validate(plan):
    ex.require(ex.plan_hash(plan) == PLAN_SHA256, "Frozen 7B canary plan changed")
    ex.require(plan["no_retry"] and plan["planned_backward_rows"] == 6, "Bounded no-retry scope")
    reference = plan["identity_reference"]
    path = ROOT / reference["path"]
    ex.require(ex.digest(path) == reference["sha256"], "Historical identity reference changed")
    contract = ex.read(path)["contract"]
    ex.require(
        plan["backbone"]["identity"]
        == {
            "legacy_state_v1_sha256": contract["original_legacy_identity_sha256"],
            "state_tree_v1_sha256": contract["original_base_sha256"],
        },
        "Named identity schemes differ from historical reference",
    )
    recovery = plan["recovery_of"]
    ex.require(
        ex.digest(ROOT / recovery["terminal"]) == recovery["terminal_sha256"],
        "Previous terminal changed",
    )


def original_identity(model, expected, output, *, legacy_hash):
    """Persist both named measurements before failing; never compare across schemes."""
    from latent_workspace.optimizer_state import tree_hash

    keys = {"legacy_state_v1_sha256", "state_tree_v1_sha256"}
    ex.require(set(expected) == keys, "Named identity scheme keys")
    observed = {
        "legacy_state_v1_sha256": legacy_hash(model),
        "state_tree_v1_sha256": tree_hash(model.state_dict()),
    }
    matches = {key: observed[key] == expected[key] for key in sorted(keys)}
    ex.write_new(
        output / "ORIGINAL_IDENTITY.json",
        dict(
            schema="named-native-model-identity-v1",
            expected=expected,
            observed=observed,
            matches=matches,
        ),
    )
    ex.require(all(matches.values()), "Pinned original model identity differs (named schemes)")
    return observed


def encode_rows(tokenizer, plan):
    """No hidden features; exact IDs, masks and answer labels are retained."""
    ex.require(tokenizer.eos_token_id == 2, "Pinned EOS")
    result = []
    for row in plan["rows"]:
        prefix = tokenizer.apply_chat_template(
            [{"role": "user", "content": row["query"]}],
            tokenize=True,
            add_generation_prompt=True,
            return_dict=False,
        )
        answer = tokenizer.encode(" " + row["answer"], add_special_tokens=False) + [2]
        memory = tokenizer.encode(row["memory"], add_special_tokens=False) if row["memory"] else []
        ids = list(prefix) + answer
        ex.require(
            all(type(t) is int and t >= 0 for t in [*ids, *memory]),
            "Tokenizer must return integer IDs",
        )
        limits = plan["bounds"]
        ex.require(
            0 < len(prefix) and 0 < len(answer) <= limits["answer_tokens_including_eos"],
            "Answer/prefix token bounds",
        )
        ex.require(
            len(memory) <= limits["memory_tokens"]
            and len(ids) <= limits["query_tokens_including_answer"],
            "Sequence token bounds",
        )
        result.append(
            dict(
                **row,
                input_ids=ids,
                labels=[-100] * len(prefix) + answer,
                memory_ids=memory,
                supervised_tokens=len(answer),
            )
        )
    validate_rows(result, plan["windows"])
    return result


def validate_rows(rows, windows):
    keys = [r["key"] for r in rows]
    ex.require(len(keys) == len(set(keys)) == 4, "Four unique input rows")
    ex.require([k for window in windows for k in window] == keys, "Fixed ordered windows")
    for row in rows:
        ids, labels = row["input_ids"], row["labels"]
        ex.require(len(ids) == len(labels) and labels[0] == -100, "Causal labels")
        ex.require(
            sum(x != -100 for x in labels[1:]) == row["supervised_tokens"] > 0,
            "Supervised denominator",
        )
    ex.require(all(len(w) == 2 for w in windows), "Two rows per window")


def batch(row, device):
    import torch

    result = {
        "input_ids": torch.tensor([row["input_ids"]], dtype=torch.long, device=device),
        "labels": torch.tensor([row["labels"]], dtype=torch.long, device=device),
    }
    result["attention_mask"] = torch.ones_like(result["input_ids"])
    if row["memory_ids"]:
        result["memory_ids"] = torch.tensor([row["memory_ids"]], dtype=torch.long, device=device)
        result["memory_mask"] = torch.ones_like(result["memory_ids"])
    return result


def fingerprint(owner):
    from latent_workspace.optimizer_state import rng_state, tree_hash

    return dict(
        native=tree_hash(owner.model.state_dict()),
        masters=tree_hash(owner.masters),
        optimizer=tree_hash(owner.optimizer.state_dict()),
        rng=tree_hash(rng_state()),
        buffers=tree_hash(dict(owner.model.named_buffers(remove_duplicate=False))),
        execution=tree_hash(owner.execution),
        history=owner.history,
        completed_steps=owner.completed_steps,
        tokens_seen=owner.tokens_seen,
    )


def update(owner, rows, keys, guard, output, step, *, after_spill=None):
    from latent_workspace.optimizer_state import tree_hash

    selected = {row["key"]: row for row in rows}
    owner.begin_window([(key, selected[key]["supervised_tokens"]) for key in keys])
    receipts = []
    for index, key in enumerate(keys):
        guard(f"step{step}:row{index}:before")
        values = owner.accumulate(key, batch(selected[key], next(owner.model.parameters()).device))
        if after_spill is not None:
            after_spill(owner, "spill", output / f"CACHE_step{step}_row{index}.json")
        # Read-only hash of the accumulated native-dtype CPU gradients.
        values["accumulated_gradient_sha256"] = tree_hash(
            {spec.name: owner.window._buffers[id(spec.parameter)] for spec in owner.window._specs}
        )
        receipts.append(values)
        ex.write_new(output / f"step{step}_row{index}.json", values)
        guard(f"step{step}:row{index}:spilled")
    guard(f"step{step}:before_update")
    result = owner.step()
    ex.require(owner.completed_steps == step, "Completed step mismatch")
    ex.require(any(r["master_changed"] for r in result["changes"]), "No CPU master changed")
    ex.require(
        sum(r["native_changed_elements"] for r in result["changes"]) > 0,
        "All native BF16 updates were invisible",
    )
    measured = dict(rows=receipts, update=result, state=fingerprint(owner))
    ex.write_new(output / f"step{step}.json", measured)
    guard(f"step{step}:complete")
    return measured


def exact(left, right, label):
    ex.require(ex.canonical(left) == ex.canonical(right), f"Exact replay mismatch: {label}")


def engine_imports(seal):
    imported = {}
    for name, module in list(sys.modules.items()):
        if name == "latent_workspace" or name.startswith("latent_workspace."):
            path = Path(module.__file__).resolve()
            relative = path.relative_to(ROOT).as_posix()
            ex.require(
                seal["source_hashes"].get(relative) == ex.digest(path),
                f"Engine import outside seal: {name}",
            )
            imported[name] = relative
    return imported


def prepare(core, args, plan, seal):
    core.load_runtime()
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from transformers.optimization import Adafactor

    from latent_workspace.native_memory import NativeMemoryCausalLM
    from latent_workspace.native_owner import NativeOptimizerConfig

    runtime = load("run_v16_adapter_full_recovery_02").runtime(core, plan)
    ex.qualification_backend_policy(torch, plan)
    ex.require(
        ex.hashlib.sha256(inspect.getsource(Adafactor.step).encode()).hexdigest()
        == plan["adafactor_step_sha256"],
        "Adafactor implementation changed",
    )
    ex.require(torch.cuda.device_count() == 1, "One visible CUDA device")
    guard = core.legacy.Guard(plan["resources"], args.output)
    forecast = plan["storage_forecast_bytes"] if args.role == "primary" else 0
    guard("admission", admission=True, forecast_bytes=forecast)
    torch.cuda.set_per_process_memory_fraction(
        plan["resources"]["allocator_cap_gib"]
        * ex.GIB
        / torch.cuda.get_device_properties(0).total_memory
    )
    torch.cuda.reset_peak_memory_stats()
    backbone = plan["backbone"]
    model_args = dict(revision=backbone["revision"], local_files_only=True, trust_remote_code=False)
    tokenizer = AutoTokenizer.from_pretrained(backbone["repository"], **model_args)
    rows = encode_rows(tokenizer, plan)
    ex.write_new(args.output / "INPUTS.json", rows)
    print(f"{args.role}: loading pinned original 7B", flush=True)
    model = AutoModelForCausalLM.from_pretrained(
        backbone["repository"],
        **model_args,
        dtype=torch.bfloat16,
        attn_implementation=backbone["attention"],
    ).to("cuda")
    model.config.use_cache = False
    identity = original_identity(
        model, backbone["identity"], args.output, legacy_hash=core.legacy.old.prior.state_hash
    )
    model.requires_grad_(True).train()
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    graph = NativeMemoryCausalLM(model, cut=backbone["cut"])
    ex.require(graph.require_full_update() == backbone["parameters"], "Full-parameter denominator")
    random.seed(plan["seed"])
    core.np.random.seed(plan["seed"])
    torch.manual_seed(plan["seed"])
    contract = dict(
        source_commit=seal["source_commit"],
        original_base_sha256=identity["state_tree_v1_sha256"],
        data_sha256=ex.plan_hash(rows),
        objective=plan["objective"],
    )
    config = NativeOptimizerConfig(**plan["optimizer"])
    ex.write_new(
        args.output / "CONTEXT.json",
        dict(
            contract=contract,
            graph=graph.contract(),
            optimizer=plan["optimizer"],
            runtime=runtime,
            physical_parameters=len(list(model.parameters())),
            parameter_elements=graph.require_full_update(),
            imports=engine_imports(seal),
            plan_sha256=ex.plan_hash(plan),
        ),
    )
    guard("original_loaded")
    return graph, rows, config, contract, guard


def peak():
    import torch

    return dict(
        peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(),
        peak_cuda_reserved_bytes=torch.cuda.max_memory_reserved(),
        peak_host_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
    )


def primary(core, args, plan, seal):
    graph, rows, config, contract, guard = prepare(core, args, plan, seal)
    from latent_workspace.native_owner import NativeFullUpdateOwner

    owner = NativeFullUpdateOwner(graph, config=config, run_contract=contract)
    ex.write_new(args.output / "INITIAL.json", fingerprint(owner))
    for step, keys in enumerate(plan["windows"], 1):
        print(f"primary: update {step}/2", flush=True)
        update(owner, rows, keys, guard, args.output, step)
        core.snapshot_admission(plan, guard, True)
        receipt = owner.save(args.checkpoints / f"step{step}.pt")
        ex.require(
            receipt["bytes"] <= plan["storage_forecast_bytes"] // 2, "Checkpoint exceeds forecast"
        )
        ex.write_new(args.output / f"CHECKPOINT_step{step}.json", receipt)
        guard(f"step{step}:saved", forecast_bytes=(2 - step) * plan["storage_forecast_bytes"] // 2)
        print(f"primary: saved step {step}", flush=True)
    ex.write_new(args.output / "PEAK.json", peak())
    return dict(
        native_weight_updates=2,
        unique_updates=2,
        backward_rows=4,
        engine_imports=engine_imports(seal),
        **peak(),
    )


def replay(core, args, plan, seal):
    graph, rows, config, contract, guard = prepare(core, args, plan, seal)
    import torch

    from latent_workspace.native_owner import NativeFullUpdateOwner
    from latent_workspace.optimizer_state import tree_hash

    reference = args.output.parent / "primary"
    exact(rows, ex.read(reference / "INPUTS.json"), "token inputs")
    exact(contract, ex.read(reference / "CONTEXT.json")["contract"], "source/base/data/objective")
    checkpoint = args.checkpoints / "step1.pt"
    receipt = ex.read(reference / "CHECKPOINT_step1.json")
    ex.require(
        checkpoint.stat().st_size == receipt["bytes"]
        and ex.digest(checkpoint) == receipt["sha256"],
        "Step1 checkpoint file receipt",
    )
    core.snapshot_admission(plan, guard, True)
    payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
    owner = NativeFullUpdateOwner.restore(
        graph,
        payload,
        config=config,
        expected_run_contract=contract,
        expected_state_sha256=receipt["state_sha256"],
    )
    del payload
    gc.collect()
    exact(fingerprint(owner), ex.read(reference / "step1.json")["state"], "restored step1")
    ex.write_new(args.output / "RESTORE.json", dict(exact_step1=True, receipt=receipt))
    measured = update(owner, rows, plan["windows"][1], guard, args.output, 2)
    exact(measured, ex.read(reference / "step2.json"), "step2 losses/gradients/update/state/RNG")
    core.snapshot_admission(plan, guard, True)
    replay_state_hash = tree_hash(owner.payload())
    expected = ex.read(reference / "CHECKPOINT_step2.json")["state_sha256"]
    ex.require(replay_state_hash == expected, "Exact serialized step2 state mismatch")
    ex.write_new(
        args.output / "REPLAY.json",
        dict(
            exact=True,
            state_sha256=replay_state_hash,
            replay_weight_file_written=False,
        ),
    )
    ex.write_new(args.output / "PEAK.json", peak())
    return dict(
        native_weight_updates=1,
        replay_updates=1,
        backward_rows=2,
        exact_replay=True,
        engine_imports=engine_imports(seal),
        **peak(),
    )


def summary(out, plan):
    a = ex.read(out / "primary/FINISHED.json")
    b = ex.read(out / "replay/FINISHED.json")
    ex.require(
        a["status"] == STATUSES["primary"] and b["status"] == STATUSES["replay"],
        "Both roles complete",
    )
    ex.require(
        a["native_weight_updates"] == 2 and b["native_weight_updates"] == 1,
        "Measured update denominator",
    )
    ex.require(b["outcome"]["exact_replay"] is True, "Replay is not exact")
    return dict(
        native_weight_updates=3,
        unique_updates=2,
        replay_updates=1,
        backward_rows=6,
        retained_checkpoints=2,
        exact_replay=True,
        old_expression_gate="FAIL",
        non_regression="NOT_ESTABLISHED",
    )


RUN = ex.SealedRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass=TINY_PASS,
    roles=ROLES,
    role_status=STATUSES,
    validate=validate,
    load=load,
    updates_native=True,
)

if __name__ == "__main__":
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    os.environ["LTWS_CPU_SDPA_BACKEND"] = "math"
    raise SystemExit(RUN.main({"primary": primary, "replay": replay}, summary))
