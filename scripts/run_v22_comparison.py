#!/usr/bin/env python3
"""One sealed, no-retry base/step32 comparison. No optimizer steps or saves."""

from __future__ import annotations

import gc
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import run_native_7b_canary as common  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402

ENTRY = "scripts/run_v22_comparison.py"
PLAN = "configs/v22/BASE_COMPARISON_01.json"
ROLES = ("base", "v22")


def validate(plan):
    ex.require(plan["schema"] == "ltws-v22-base-comparison-01" and plan["no_retry"], "Plan")
    ex.require(
        plan["planned"]
        == dict(
            arms=2,
            mmlu_scores=1140,
            world_teacher_forced_rows=384,
            world_generations=384,
            free_generations=48,
            total_new_sequences=432,
            native_weight_updates=0,
            checkpoint_saves=0,
            judge_calls=0,
            weight_deletions=0,
        ),
        "Finite comparison scope",
    )
    ex.require(plan["world_routes"] == ["latent", "inline"], "Fixed routes")


def inputs(plan):
    folder = Path(plan["input_bundle"])
    frozen = ROOT / "configs/v22/comparison_20261021/MANIFEST.json"
    ex.require(ex.digest(folder / "MANIFEST.json") == ex.digest(frozen), "Committed input seal")
    receipt = ex.read(folder / "MANIFEST.json")
    actual = ex.manifest(folder)
    actual.pop("MANIFEST.json")
    ex.require(actual == receipt["files"], "Frozen input bytes")
    ex.require(receipt["plan_sha256"] == ex.plan_hash(plan), "Input plan")
    for name, digest in receipt["source"].items():
        ex.require(ex.digest(ROOT / name) == digest, "Input preparation source")
    data = ex.read_gz(folder / "INPUTS.json.gz")
    ex.require(data["plan_sha256"] == ex.plan_hash(plan), "Tokenized plan identity")
    ex.require(
        data["audit"]["world_groups"] == 16
        and data["audit"]["unique_world_rows"] == 96
        and data["audit"]["raw_world_rows"] == 128
        and data["audit"]["training_group_overlap"] == 0,
        "Held-out input audit",
    )
    return data, receipt


def append(stream, record):
    stream.write(ex.canonical(record) + "\n")
    stream.flush()
    os.fsync(stream.fileno())


def prepare(core, args, plan, *, restore=None):
    core.load_runtime()
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    from latent_workspace.native_memory import NativeMemoryCausalLM
    from latent_workspace.native_owner import NativeFullUpdateOwner, NativeOptimizerConfig
    from latent_workspace.optimizer_state import tree_hash

    common.load("run_v16_adapter_full_recovery_02").runtime(core, plan)
    ex.qualification_backend_policy(torch, plan)
    train = ex.read(ROOT / plan["training_plan"])
    guard = core.legacy.Guard(plan["resources"], args.output)
    guard("admission", admission=True, forecast_bytes=0)
    torch.cuda.set_per_process_memory_fraction(
        plan["resources"]["allocator_cap_gib"]
        * ex.GIB
        / torch.cuda.get_device_properties(0).total_memory
    )
    torch.cuda.reset_peak_memory_stats()
    b = train["backbone"]
    tokenizer = AutoTokenizer.from_pretrained(
        b["repository"],
        revision=b["revision"],
        local_files_only=True,
        trust_remote_code=False,
    )
    print(f"{args.role}: load original BF16/eager host", flush=True)
    model = AutoModelForCausalLM.from_pretrained(
        b["repository"],
        revision=b["revision"],
        local_files_only=True,
        trust_remote_code=False,
        dtype=torch.bfloat16,
        attn_implementation=b["attention"],
    ).to("cuda")
    model.config.use_cache = False
    common.original_identity(
        model, b["identity"], args.output, legacy_hash=core.legacy.old.prior.state_hash
    )
    model.requires_grad_(True).train()
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    graph = NativeMemoryCausalLM(model, cut=b["cut"])
    if restore is not None:
        # Later objective versions supply their strict owner restore, before
        # the same explicit inference transition below. The V22 default stays
        # unchanged; this is not a bypass around its historical contract.
        restore(graph, args, plan)
    elif args.role == "v22":
        bundle = Path(plan["training_bundle"])
        reference = bundle / "raw/train_b"
        historical = ROOT / "provenance/pilots/v22_full_ft_recovery01_20261021/furnace/raw/train_b"
        for name in (
            "CONTEXT.json",
            "CHECKPOINT_training_step32.pt.json",
            "STATE_training_step32.pt.json",
            "FINISHED.json",
        ):
            ex.require(
                ex.digest(reference / name) == ex.digest(historical / name),
                f"Historical training receipt: {name}",
            )
        receipt = ex.read(reference / "CHECKPOINT_training_step32.pt.json")
        expected = plan["checkpoint"]
        ex.require(
            all(receipt[k] == expected[k] for k in ("bytes", "sha256", "state_sha256"))
            and receipt["path"] == expected["name"]
            and receipt["completed_steps"] == 32,
            "Pinned step32 receipt",
        )
        path = bundle / "checkpoints" / expected["name"]
        ex.require(
            not path.is_symlink()
            and path.stat().st_size == receipt["bytes"]
            and ex.digest(path) == receipt["sha256"],
            "Step32 checkpoint body",
        )
        contract = ex.read(reference / "CONTEXT.json")["contract"]
        ex.require(contract["source_commit"] == plan["training_source"], "Training source")
        print("v22: strict owner restore before inference-policy transition", flush=True)
        payload = torch.load(path, map_location="cpu", weights_only=False)
        owner = NativeFullUpdateOwner.restore(
            graph,
            payload,
            config=NativeOptimizerConfig(**train["optimizer"]),
            expected_run_contract=contract,
            expected_state_sha256=receipt["state_sha256"],
        )
        del payload
        gc.collect()
        actual = common.fingerprint(owner)
        common.exact(
            actual,
            ex.read(reference / "STATE_training_step32.pt.json"),
            "Full step32 owner state before inference",
        )
        ex.write_new(
            args.output / "RESTORE.json",
            dict(
                exact=True,
                checkpoint=receipt,
                fingerprint=actual,
                training_contract=contract,
            ),
        )
        del owner
        gc.collect()
    # This is an explicit *post-restore* inference transition, not a relaxation
    # of the training restore contract.
    model.gradient_checkpointing_disable()
    graph.eval().requires_grad_(False)
    torch.cuda.empty_cache()
    guard("ready_for_inference")
    state = tree_hash(model.state_dict())
    ex.write_new(
        args.output / "INFERENCE_POLICY.json",
        dict(
            native_sha256=state,
            graph=graph.contract(),
            dtype="bfloat16",
            attention="eager",
            training=False,
            requires_grad=False,
            use_cache=False,
            gradient_checkpointing=False,
            memory_reencoded_every_token=True,
            sampling="fresh per-answer CPU FP32 full-vocabulary generator",
        ),
    )
    return graph, tokenizer, guard, state


def run(core, args, plan, seal, *, inputs_fn=None, prepare_fn=None, sequences_per_arm=None):
    from latent_workspace import native_evaluation as ev
    from latent_workspace.optimizer_state import tree_hash

    data, input_receipt = (inputs_fn or inputs)(plan)
    ex.write_new(args.output / "INPUT_MANIFEST.json", input_receipt)
    graph, tokenizer, guard, before = (prepare_fn or prepare)(core, args, plan)
    import torch

    device = next(graph.parameters()).device
    # Direct/empty-memory parity on fixed benchmark prefixes, before scoring.
    with torch.no_grad():
        parity = []
        for row in data["mmlu"][:2]:
            batch = ev.tensor_batch(row["input_ids"][:32], [], device)
            a = graph(**batch).logits
            b = graph.model(**batch, use_cache=False).logits
            ex.require(torch.equal(a, b), "Empty-memory native bypass parity")
            parity.append(dict(id=row["id"], tokens=32, bitwise_equal=True))
            del a, b
    ex.write_new(args.output / "PARITY.json", parity)
    with (args.output / "mmlu.jsonl").open("x") as stream, torch.no_grad():
        for i, row in enumerate(data["mmlu"]):
            guard(f"mmlu:{i}")
            output = graph(**ev.tensor_batch(row["input_ids"], [], device))
            score = ev.score_choices(output.logits[0, -1], row["choice_ids"], row["target"])
            append(
                stream,
                dict(
                    id=row["id"],
                    subject=row["subject"],
                    prompt_tokens=len(row["input_ids"]),
                    **score,
                ),
            )
            del output
            if (i + 1) % 50 == 0:
                print(f"{args.role}: MMLU {i + 1}/{len(data['mmlu'])}", flush=True)
    sequences, generated = 0, 0
    with (args.output / "worlds.jsonl").open("x") as stream:
        for i, row in enumerate(data["worlds"]):
            for route in plan["world_routes"]:
                prefix = row["prefixes"][route]
                memory = row["memory_ids"] if route == "latent" else []
                guard(f"world:{i}:{route}:teacher")
                with torch.no_grad():
                    output = graph(**ev.tensor_batch(prefix, memory, device, row["answer_ids"]))
                    ex.require(bool(torch.isfinite(output.loss_sum)), "Finite world NLL")
                    teacher = dict(
                        nll_sum=float(output.loss_sum), supervised_tokens=output.supervised_tokens
                    )
                    del output
                policy = plan["world_generation"]
                result = ev.generate(
                    graph,
                    prefix,
                    memory,
                    seed=policy["seed"],
                    cap=policy["max_new_tokens"],
                    eos=2,
                    temperature=policy["temperature"],
                    top_p=policy["top_p"],
                    guard=guard,
                )
                text = tokenizer.decode(result["token_ids"], skip_special_tokens=True)
                correct = ev.normalized_answer(text) == ev.normalized_answer(row["answer"])
                append(
                    stream,
                    dict(
                        id=row["row_id"],
                        group_id=row["group_id"],
                        family=row["family"],
                        split=row["split"],
                        side=row["side"],
                        mode=row["mode"],
                        route=route,
                        aliases=row["aliases"],
                        target=row["answer"],
                        text=text,
                        exact_match=correct,
                        teacher=teacher,
                        **result,
                    ),
                )
                sequences += 1
                generated += result["generated_tokens"]
            print(f"{args.role}: worlds {i + 1}/{len(data['worlds'])}", flush=True)
    with (args.output / "free.jsonl").open("x") as stream:
        policy = plan["generation"]
        for row in data["free"]:
            for seed in policy["seeds"]:
                result = ev.generate(
                    graph,
                    row["input_ids"],
                    [],
                    seed=seed,
                    cap=policy["max_new_tokens"],
                    eos=2,
                    temperature=policy["temperature"],
                    top_p=policy["top_p"],
                    guard=guard,
                )
                text = tokenizer.decode(result["token_ids"], skip_special_tokens=True)
                append(
                    stream,
                    dict(
                        id=row["id"],
                        category=row["category"],
                        prompt=row["prompt"],
                        text=text,
                        **result,
                    ),
                )
                sequences += 1
                generated += result["generated_tokens"]
            print(f"{args.role}: free {row['id']}", flush=True)
    expected_sequences = (
        plan["planned"]["total_new_sequences"] // 2
        if sequences_per_arm is None
        else sequences_per_arm
    )
    ex.require(sequences == expected_sequences, "Generation count")
    after = tree_hash(graph.model.state_dict())
    ex.require(before == after, "Inference mutated native weights")
    ex.write_new(args.output / "WEIGHT_IDENTITY.json", dict(before=before, after=after, equal=True))
    imports = common.engine_imports(seal)
    guard("complete")
    return dict(
        new_sequences=sequences,
        generated_tokens=generated,
        native_weight_updates=0,
        checkpoint_saves=0,
        engine_imports=imports,
        mmlu_rows=len(data["mmlu"]),
        world_rows=len(data["worlds"]) * 2,
        free_rows=len(data["free"]) * 2,
        **common.peak(),
    )


class EvaluationRun(ex.SealedRun):
    def activity(self, result, outcome=None):
        # Base skeleton's default zero-sequence ceiling is for training probes.
        # A failed generation role has UNKNOWN activity, never a false zero.
        result["new_sequences"] = None if outcome is None else outcome["new_sequences"]
        result["native_weight_updates"] = 0


def summary(folder, plan):
    ends = [ex.read(folder / role / "FINISHED.json")["outcome"] for role in ROLES]
    sequences = sum(e["new_sequences"] for e in ends)
    ex.require(sequences == plan["planned"]["total_new_sequences"], "Planned total")
    return dict(
        new_sequences=sequences,
        generated_tokens=sum(e["generated_tokens"] for e in ends),
        native_weight_updates=0,
        checkpoint_saves=0,
        completed_arms=list(ROLES),
    )


RUN = EvaluationRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass="TINY_V22_EVALUATION_PASS_NOT_7B",
    roles=ROLES,
    role_status={r: "V22_EVALUATION_ARM_COMPLETE" for r in ROLES},
    validate=validate,
    load=common.load,
)

if __name__ == "__main__":
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    os.environ["LTWS_CPU_SDPA_BACKEND"] = "math"
    raise SystemExit(RUN.main({r: run for r in ROLES}, summary))
