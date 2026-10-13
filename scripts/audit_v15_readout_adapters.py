#!/usr/bin/env python3
"""Exclusive read-only retained-state audit; no optimizer, generation or API calls."""

from __future__ import annotations

import argparse
import gc
import os
import platform
import subprocess
import sys
import time
import traceback
from contextlib import nullcontext
from pathlib import Path

import torch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "src"), str(REPO / "scripts")]
import run_v15_native_learner as parent  # noqa: E402

from latent_workspace_ft_v10.adapted_workspace import AdaptedWorkspacePipeline  # noqa: E402
from latent_workspace_ft_v10.hf_readout_adapter import HFNativeReadoutAdapter  # noqa: E402
from latent_workspace_ft_v10.model_binding import FunctionalBoundaryAdapter  # noqa: E402
from latent_workspace_ft_v10.readout_transport import compare_transport  # noqa: E402
from latent_workspace_ft_v10.v15_native_learner import (  # noqa: E402
    create_reader,
    reader_descriptor,
    tree_hash,
)

old, require, read = parent.old, parent.require, parent.read
PRIOR = REPO / "provenance/pilots/v15_native_learner_20261010"
PLAN = REPO / "configs/v15/READOUT_ADAPTER_PLAN.json"
ADDITIONS = (
    "configs/v15/READOUT_ADAPTER_PLAN.json",
    "docs/v15/READOUT_ADAPTERS.md",
    "src/latent_workspace_ft_v10/readout_transport.py",
    "src/latent_workspace_ft_v10/hf_readout_adapter.py",
    "src/latent_workspace_ft_v10/adapted_workspace.py",
    "scripts/audit_v15_readout_adapters.py",
    "tests/test_readout_adapters.py",
)


def identity():
    paths = set(parent.identity()) | set(ADDITIONS)
    paths |= {
        str((PRIOR / n).relative_to(REPO)) for n in ("SOURCE_SEAL.json", "ARTIFACT_INDEX.json")
    }
    return {name: old.prior.digest(REPO / name) for name in sorted(paths)}


def validate():
    _, _, architecture, records = parent.validate()
    plan = read(PLAN)
    require(
        plan["states"]
        == [
            ["reader", "legacy", 8],
            ["reader", "query_modulated", 8],
            ["full", "frozen", 2],
            ["full", "full", 2],
        ],
        "State scope",
    )
    require(plan["worlds"] == [0, 1] and plan["queries"] == list(range(8)), "Exposed input scope")
    require(plan["conditions"] == ["intact", "twin", "zero"], "Control scope")
    require(
        plan["optimizer_steps"] == plan["new_sequences"] == plan["judge_calls"] == 0,
        "Read-only scope",
    )
    require(plan["context_boundary"] == 16 and plan["reader_mode"] == "final", "Reader scope")
    require(
        plan["no_retry"] is True
        and plan["old_expression_gate"] == "FAIL"
        and plan["winner"] == "none",
        "Claims/retry contract",
    )
    for name, sha in read(PRIOR / "SOURCE_SEAL.json")["source_hashes"].items():
        require(old.prior.digest(REPO / name) == sha, f"Historical source changed: {name}")
    for name, receipt in read(PRIOR / "ARTIFACT_INDEX.json").items():
        path = PRIOR / name
        require(
            path.stat().st_size == receipt["bytes"] and old.prior.digest(path) == receipt["sha256"],
            f"Historical artifact changed: {name}",
        )
    return plan, architecture, records


@torch.no_grad()
def execute(args):
    plan, architecture, records = validate()
    seal = read(args.seal)
    runtime = dict(
        python=platform.python_version(),
        torch=str(torch.__version__),
        transformers=parent.transformers.__version__,
        cuda=torch.version.cuda,
    )
    require(runtime == architecture["expected_runtime"], "Pinned CUDA runtime changed")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    require(seal == {"source_commit": commit, "source_hashes": identity()}, "Source seal")
    require(
        not subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO, text=True
        ).strip(),
        "Dirty execution source",
    )
    args.output.mkdir(parents=True, exist_ok=False)
    guard = parent.Guard(plan["resources"], args.output)
    start = time.monotonic()
    try:
        guard("admission", admission=True)
        old.write_new(
            args.output / "STARTED.json",
            {**seal, "plan": plan, "pid": os.getpid(), "runtime": runtime},
        )
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        torch.set_float32_matmul_precision("highest")
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.cuda.set_per_process_memory_fraction(
            18 * 2**30 / torch.cuda.get_device_properties(0).total_memory
        )
        base = old.engine._load_hf_model(old.engine.ModelConfig(**architecture["model"]))
        base = base.eval().requires_grad_(False).to("cuda")
        require(old.prior.state_hash(base) == old.BASE_HASH, "Pinned original model")
        boundary = FunctionalBoundaryAdapter(base)
        panels = []
        for phase, arm, step in plan["states"]:
            guard(f"{phase}:{arm}:load")
            checkpoint = (
                args.checkpoint_root
                / f"checkpoints_v15_native_{phase}_20261010"
                / arm
                / f"step{step}.pt"
            )
            receipt = read(PRIOR / "raw" / phase / f"{arm}_{step}_checkpoint.json")
            require(
                checkpoint.stat().st_size == receipt["bytes"]
                and old.prior.digest(checkpoint) == receipt["sha256"],
                "Retained file identity",
            )
            payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
            require(tree_hash(payload) == receipt["state_sha256"], "Retained payload identity")
            expected = next(
                r for r in read(PRIOR / "raw" / phase / "REPORT.json")["results"] if r["arm"] == arm
            )
            if payload["full_update"]:
                require((phase, arm) == ("full", "full"), "Only the final arm may update base")
                for name, param in base.named_parameters():
                    param.copy_(payload["base_masters"][name].to(param.dtype))
                for name, buffer in payload["native_buffers"].items():
                    base.state_dict()[name].copy_(buffer)
            require(
                old.prior.state_hash(base) == expected["final_base_sha256"], "Current base hash"
            )
            reader = create_reader(
                base.config.hidden_size, architecture["bridge"], expected["reader"]
            ).to("cuda")
            reader.load_state_dict(payload["bridge"], strict=True)
            require(reader_descriptor(reader) == payload["reader"], "Retained reader contract")
            reader.eval().requires_grad_(False)
            require(old.prior.state_hash(reader) == expected["final_bridge_sha256"], "Reader hash")
            del payload
            gc.collect()
            adapter = HFNativeReadoutAdapter(base)
            pipeline = AdaptedWorkspacePipeline(reader, adapter)
            legacy = old.NativeWorkspacePipeline(
                reader, old.NativeWorkspaceReadout(base.lm_head), "final"
            )
            features = read(PRIOR / "raw" / phase / f"{arm}_FEATURES.json")
            renderings = {(r["world"], r["query"]): r for r in features["renderings"]}
            contexts = features["contexts"]
            if isinstance(contexts, list):
                contexts = {str((r["world"], r["key"])): r for r in contexts}
            historical = {
                (r["world"], r["query"], r["control"]): r
                for r in read(PRIOR / "raw" / phase / f"{arm}_{step}_evaluation.json")["rows"]
            }
            rows, pairs = [], []
            for w in plan["worlds"]:
                memories = []
                for side in (0, 1):
                    ids = torch.tensor([contexts[str((w, side))]["ids"]], device="cuda")
                    # Preserve the two historical context execution contracts.
                    with (
                        torch.autocast("cuda", dtype=torch.bfloat16)
                        if phase == "reader"
                        else nullcontext()
                    ):
                        hidden = boundary.encode(ids, torch.ones_like(ids), 16)
                    memories.append(reader.write_memory(hidden, torch.ones_like(ids)))
                for q in plan["queries"]:
                    guard(f"{phase}:{arm}:{w}:{q}")
                    row = renderings[w, q]
                    prefix, span = tuple(row["prompt_ids"]), old.bound_span(row)
                    tokens = torch.tensor([prefix], device="cuda")
                    hidden = base.model(
                        tokens, attention_mask=torch.ones_like(tokens), use_cache=False
                    ).last_hidden_state
                    current = base(
                        tokens, attention_mask=torch.ones_like(tokens), use_cache=False
                    ).logits
                    outputs = []
                    for c, (mem, mask) in zip(
                        plan["conditions"],
                        [*memories, (torch.zeros_like(memories[0][0]), memories[0][1])],
                    ):
                        before = legacy(hidden, mem, mask, prefix_ids=prefix, span=span)
                        after = pipeline(prefix, mem, mask, span=span)
                        exact = torch.equal(before.readout.logits, after.readout.logits)
                        require(
                            exact and torch.equal(before.delta, after.delta),
                            "Old/new native parity",
                        )
                        scores = after.readout.choice_scores(row["candidate_ids"])[0].tolist()
                        require(
                            scores == historical[w, q, c]["native_scores"],
                            "Historical choice replay",
                        )
                        if c == "zero":
                            require(
                                torch.equal(after.readout.logits, current)
                                and after.delta.count_nonzero() == 0,
                                "Written zero identity",
                            )
                        rows.append(
                            dict(
                                world=w,
                                query=q,
                                condition=c,
                                native_scores=scores,
                                full_logits_exact=exact,
                                historical_choices_exact=True,
                                zero_exact=c == "zero",
                                logits_sha256=old.tensor_hash(after.readout.logits),
                            )
                        )
                        if c != "zero":
                            outputs.append(after.transport)
                    probe = compare_transport(
                        *outputs, row["candidate_ids"], linear_weight=adapter.head.weight
                    )
                    labels = [records[w]["answers"][s][q] for s in (0, 1)]
                    pairs.append(
                        dict(
                            world=w,
                            query=q,
                            affected=labels[0] != labels[1],
                            donor_sign=2 * labels[1] - 1,
                            transport=probe,
                        )
                    )
                    del outputs, after, before, current, hidden
            require(
                old.prior.state_hash(base) == expected["final_base_sha256"]
                and old.prior.state_hash(reader) == expected["final_bridge_sha256"],
                "No weight changes",
            )
            panel = dict(
                phase=phase,
                arm=arm,
                step=step,
                checkpoint=receipt,
                base_sha256=expected["final_base_sha256"],
                adapter=adapter.describe(),
                rows=rows,
                pairs=pairs,
                weights_unchanged=True,
            )
            old.write_new(args.output / f"{phase}_{arm}.json", panel)
            panels.append(panel)
        counts = dict(
            adapter_forwards=sum(len(p["rows"]) for p in panels),
            memory_pairs=sum(len(p["pairs"]) for p in panels),
            affected_pairs=sum(r["affected"] for p in panels for r in p["pairs"]),
        )
        require(
            counts == dict(adapter_forwards=192, memory_pairs=64, affected_pairs=16), "Denominators"
        )
        require(identity() == seal["source_hashes"], "Source changed during execution")
        old.write_new(
            args.output / "FINISHED.json",
            dict(
                status="COMPLETED_READ_ONLY_ADAPTER_AUDIT",
                **counts,
                source_commit=commit,
                elapsed_seconds=time.monotonic() - start,
                old_expression_gate="FAIL",
                winner="none",
                optimizer_steps=0,
                new_sequences=0,
                judge_calls=0,
                peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(),
                peak_cuda_reserved_bytes=torch.cuda.max_memory_reserved(),
            ),
        )
    except Exception:
        old.write_new(args.output / "ERROR.json", {"traceback": traceback.format_exc()})
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seal", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--checkpoint-root", type=Path)
    parser.add_argument("--write-seal", type=Path)
    args = parser.parse_args()
    if args.write_seal:
        validate()
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
        old.write_new(args.write_seal, dict(source_commit=commit, source_hashes=identity()))
    else:
        require(all((args.seal, args.output, args.checkpoint_root)), "Explicit paths required")
        execute(args)


if __name__ == "__main__":
    main()
