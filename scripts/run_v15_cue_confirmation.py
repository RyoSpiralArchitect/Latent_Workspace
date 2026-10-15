#!/usr/bin/env python3
"""Bounded no-training cue/envelope assay; no automatic learner launch on pass."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import torch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts"), str(REPO / "src")]
import run_v15_completion_mass as completion  # noqa: E402
from v15_assay_summary import parse_functional_answer  # noqa: E402
from v15_cue_contract import (  # noqa: E402
    CUES,
    INFORMATION,
    META,
    REGIME,
    RENDERERS,
    make_cases,
    render_case,
    summarize,
)

previous = completion.previous
engine, prior, write_new = previous.engine, previous.prior, previous.write_new
PLAN = REPO / "configs/v15/CUE_CONFIRMATION_PLAN.json"
CORPUS = REPO / "configs/v15/CUE_CONFIRMATION_INPUTS.json"
ADDITIONS = (
    "configs/v15/CUE_CONFIRMATION_PLAN.json",
    "configs/v15/CUE_CONFIRMATION_INPUTS.json",
    "docs/v15/CUE_CONFIRMATION_PLAN.md",
    "scripts/v15_cue_contract.py",
    "scripts/v15_cue_span.py",
    "scripts/run_v15_cue_confirmation.py",
    "scripts/verify_v15_cue_confirmation.py",
    "tests/test_v15_cue_confirmation.py",
    "provenance/pilots/v15_completion_mass_20261010/ARTIFACT_INDEX.json",
    "provenance/pilots/v15_completion_mass_20261010/VALIDATION.json",
)
PLAN_SHA256 = "1b5f73ea52f3876db7dcbcd0e8020973ebe08e5961eabb0632c0c28104278a0d"


def validate():
    if prior.digest(PLAN) != PLAN_SHA256:
        raise ValueError("Frozen cue confirmation plan changed")
    plan = json.loads(PLAN.read_text())
    _, parent, _ = completion.validate()
    # Verify sealed bytes and recorded execution-host receipt, without waiving
    # the predecessor's separately recorded Mac exact-summary failure.
    from verify_v15_completion_mass import index_for

    old_bundle = REPO / plan["completion_bundle"]
    if (
        prior.digest(old_bundle / "ARTIFACT_INDEX.json")
        != "cf9d317676287c1ab958ab52a42e297763eaf8137fe149c4ee768f0e9cbbf548"
        or prior.digest(old_bundle / "VALIDATION.json")
        != "14605aae64391450391bcbaa2b438e2a815956a4eb7c6c08ef7de410e7e70393"
        or index_for(old_bundle) != json.loads((old_bundle / "ARTIFACT_INDEX.json").read_text())
        or completion.sources(parent)
        != json.loads((old_bundle / "raw/REPORT.json").read_text())["source_manifest_before"]
    ):
        raise RuntimeError("Sealed predecessor identity changed")
    corpus = json.loads(CORPUS.read_text())
    if corpus != make_cases(REPO):
        raise RuntimeError("Frozen corpus regeneration changed")
    return plan, parent, corpus


def sources(parent):
    result = completion.sources(parent)
    result.update({name: prior.digest(REPO / name) for name in ADDITIONS})
    return result


def prepare(tokenizer, corpus):
    result = []
    for case in corpus["cases"]:
        for renderer in RENDERERS:
            for cue in CUES:
                for information in INFORMATION:
                    row = render_case(
                        tokenizer,
                        query=case["query"],
                        context=case["context"],
                        renderer=renderer,
                        cue=cue,
                        information=information,
                    )
                    result.append({"case_id": case["case_id"], **row})
    if len(result) != 512:
        raise RuntimeError("Rendering denominator changed")
    return result


@torch.no_grad()
def score(base, readout, renderings, cases, guard):
    backend = previous.BaseBackend(base, readout)
    indexed = {c["case_id"]: c for c in cases}
    rows = []
    for i, row in enumerate(renderings):
        guard(f"scoring:{i}")
        ids = torch.tensor([row["prompt_ids"]], device=base.device)
        actual = base(ids, attention_mask=torch.ones_like(ids), use_cache=False).logits
        hidden = backend.encode(tuple(row["prompt_ids"]))
        out = backend.readout(hidden, torch.zeros_like(hidden[:, -1:]).float())
        if not torch.equal(actual.float(), out.logits.float()):
            raise RuntimeError("Ordinary/shared full-native logits mismatch")
        native = previous.previous.scores(out.choice_scores(row["candidate_ids"]))
        logits = out.last_logits[0].double()
        logp = logits.log_softmax(-1)
        probabilities = logits.softmax(-1)
        top1 = int(logits.argmax())
        head = {
            "old_lowercase_native": native,
            "candidate_probabilities": probabilities[row["candidate_ids"]].tolist(),
            "top1_token_id": top1,
            "top1_probability": float(probabilities[top1]),
            "ordinary_shared_full_logits_exact": True,
        }
        first = {a["token_id"]: float(logp[a["token_id"]]) for a in row["aliases"]}
        del ids, actual, hidden, out, logits, logp, probabilities
        aliases = []
        for binding in row["aliases"]:
            guard(f"alias:{i}")
            hidden = backend.encode(tuple(row["prompt_ids"] + [binding["token_id"]]))
            out = backend.readout(hidden, torch.zeros_like(hidden[:, -1:]).float())
            eos = float(out.last_logits[0].double().log_softmax(-1)[2])
            initial = first[binding["token_id"]]
            aliases.append(
                {
                    **binding,
                    "first_log_probability": initial,
                    "eos_log_probability": eos,
                    "complete_log_probability": initial + eos,
                    "first_probability": math.exp(initial),
                    "eos_probability": math.exp(eos),
                    "complete_probability": math.exp(initial + eos),
                }
            )
            del hidden, out
        rows.append(
            {
                **{k: indexed[row["case_id"]][k] for k in META},
                **{k: row[k] for k in ("renderer", "cue", "information", "candidate_ids")},
                "prefix_ids": row["prompt_ids"],
                "prefix_sha256": completion.prefix_digest(row["prompt_ids"]),
                **head,
                "aliases": aliases,
            }
        )
        if (i + 1) % 64 == 0:
            print(f"scored {i + 1}/512 prefixes", flush=True)
    return rows, backend.parity_checks


@torch.no_grad()
def generate(base, readout, tokenizer, cases, renderings, guard):
    index = {(r["case_id"], r["renderer"], r["cue"], r["information"]): r for r in renderings}
    rows, receipts = [], []
    for i, case in enumerate(cases):
        for renderer in RENDERERS:
            for cue in CUES:
                backend = previous.BaseBackend(base, readout)
                prompts = {
                    condition: index[case["case_id"], renderer, cue, info]["prompt_ids"]
                    for condition, info in (("base", "query_only"), ("base_inline", "inline"))
                }
                generated, receipt = previous.generate_matched(
                    case_id=case["case_id"],
                    prompts=prompts,
                    regime=REGIME,
                    max_new_tokens=64,
                    eos_token_ids={2},
                    backend=backend,
                    decode=lambda ids: tokenizer.decode(ids, skip_special_tokens=True),
                    zero_pairs=(),
                    guard=lambda: guard(f"generation:{i}:{renderer}:{cue}"),
                )
                for row in generated:
                    parsed = parse_functional_answer(row["answer"])
                    valid = parsed is not None and row["finish_reason"] == "eos"
                    row.update({k: case[k] for k in META})
                    row.update(
                        renderer=renderer,
                        cue=cue,
                        information="inline" if row["condition"] == "base_inline" else "query_only",
                        parsed_answer=parsed,
                        valid_eos=valid,
                        strict_correct=valid and parsed == case["target_label"],
                        lowercase_compliant=row["answer"].strip() in ("no", "yes"),
                    )
                    row["id"] += f"__{renderer}__{cue}"
                    rows.append(row)
                receipts.append(
                    {
                        "case_id": case["case_id"],
                        "renderer": renderer,
                        "cue": cue,
                        **receipt,
                        "shared_historical_native_checks": backend.parity_checks,
                    }
                )
        print(f"generated case {i + 1}/64", flush=True)
    return {"rows": rows, "receipts": receipts, "eos_token_ids": [2]}


def execute(output):
    import transformers

    plan, parent, corpus = validate()
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
    guard = previous.previous.previous.ResourceGuard(plan["resources"], output)
    calls = 0

    def poll(phase):
        nonlocal calls
        calls += 1
        if calls == 1 or calls % 16 == 0:
            guard(phase)

    start = time.monotonic()
    try:
        admission = guard("admission", admission=True)
        hashes = sources(parent)
        identity = previous.tokenizer_identity()
        write_new(
            output / "STARTED.json",
            {
                "source_commit": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
                ).strip(),
                "source_hashes": hashes,
                "runtime": runtime,
                "plan": plan,
                "plan_sha256": prior.digest(PLAN),
                "admission": admission,
                "tokenizer_identity": identity,
            },
        )
        write_new(output / "CORPUS.json", corpus)
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        torch.set_float32_matmul_precision("highest")
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        if torch.cuda.device_count() != 1:
            raise RuntimeError("One CUDA device required")
        torch.cuda.set_per_process_memory_fraction(
            18 * 2**30 / torch.cuda.get_device_properties(0).total_memory
        )
        torch.cuda.reset_peak_memory_stats()
        config = engine.ModelConfig(**parent["model"])
        tokenizer = engine.load_tokenizer(config)
        if (
            hashlib.sha256(tokenizer.get_chat_template().encode()).hexdigest()
            != identity["chat_template_sha256"]
        ):
            raise RuntimeError("Active chat template mismatch")
        renderings = prepare(tokenizer, corpus)
        write_new(output / "RENDERINGS.json", renderings)
        print("loading pinned base for fresh cue confirmation", flush=True)
        base = engine._load_hf_model(config).eval().requires_grad_(False).to("cuda")
        before = prior.state_hash(base)
        if (
            before != completion.BASE_HASH
            or base.generation_config.eos_token_id != 2
            or tokenizer.eos_token_id != 2
        ):
            raise RuntimeError("Pinned base/EOS identity mismatch")
        guard("loaded")
        readout = previous.NativeWorkspaceReadout(base.lm_head)
        scores, score_checks = score(base, readout, renderings, corpus["cases"], poll)
        write_new(output / "SCORES.json", scores)
        generated = generate(base, readout, tokenizer, corpus["cases"], renderings, poll)
        write_new(output / "GENERATION.json", generated)
        summary = summarize(corpus["cases"], scores, generated["rows"], plan)
        after = prior.state_hash(base)
        if before != after or any(p.grad is not None for p in base.parameters()):
            raise RuntimeError("Base changed")
        if sources(parent) != hashes or previous.tokenizer_identity() != identity:
            raise RuntimeError("Source/tokenizer changed")
        guard("completed")
        report = {
            "status": "COMPLETED_CUE_CONFIRMATION",
            "optimizer_steps": 0,
            "workspace_loaded": False,
            "base_sha256_before": before,
            "base_sha256_after": after,
            "source_unchanged": True,
            "tokenizer_identity_unchanged": True,
            "prefixes": len(scores),
            "generation_sequences": len(generated["rows"]),
            "initial_native_parity_checks": len(scores),
            "scoring_readout_parity_checks": score_checks,
            "generation_readout_parity_checks": sum(
                r["shared_historical_native_checks"] for r in generated["receipts"]
            ),
            "summary": summary,
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
            "status": report["status"],
            "elapsed_seconds": report["elapsed_seconds"],
            "primary_expression_gate": summary["primary_expression_gate"],
        }
    except Exception as exc:
        write_new(
            output / "FAILED.json",
            {"status": "INCOMPLETE", "exception_type": type(exc).__name__, "message": str(exc)},
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-inputs", action="store_true")
    parser.add_argument("--tokenizer-preflight", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.freeze_inputs:
        write_new(CORPUS, make_cases(REPO))
        print("INPUTS_FROZEN_NO_MODEL")
    elif args.tokenizer_preflight:
        _, parent, corpus = validate()
        previous.tokenizer_identity()
        rows = prepare(engine.load_tokenizer(engine.ModelConfig(**parent["model"])), corpus)
        print(
            json.dumps(
                {
                    "status": "TOKENIZATION_ONLY",
                    "prefixes": len(rows),
                    "alias_paths": sum(len(r["aliases"]) for r in rows),
                    "max_tokens": max(len(r["prompt_ids"]) for r in rows),
                }
            )
        )
    elif args.dry_run:
        validate()
        print("PREPARED_NOT_RUN")
    elif args.output is None:
        parser.error("--output required")
    else:
        print(json.dumps(execute(args.output.resolve())))
