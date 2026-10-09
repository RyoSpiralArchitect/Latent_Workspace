#!/usr/bin/env python3
"""Pinned-base, no-training raw versus native-chat generation instrument assay."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import torch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts"), str(REPO / "src")]
import run_v15_readout_transport as previous  # noqa: E402
from v15_assay_summary import parse_functional_answer  # noqa: E402
from v15_elicitation_inputs import make_cases, render_case  # noqa: E402
from verify_v15_elicitation import summarize  # noqa: E402
from verify_v15_readout_transport import verify_bundle as verify_previous  # noqa: E402

from latent_workspace_ft_v10.answer_bank_generation import native_full_readout  # noqa: E402
from latent_workspace_ft_v10.v15_generation import generate_matched  # noqa: E402
from latent_workspace_ft_v10.v15_readout import NativeWorkspaceReadout  # noqa: E402

PLAN = REPO / "configs/v15/ELICITATION_PLAN.json"
engine, prior, write_new = previous.engine, previous.prior, previous.write_new


def validate():
    plan = json.loads(PLAN.read_text())
    _, parent, _, _ = previous.validate()
    expected = {
        "format": "v15-base-elicitation-v1",
        "predecessor_bundle": "provenance/pilots/v15_readout_transport_20261010",
        "model_parent": "configs/v14/PRECISION_BRIDGE_PLAN.json",
        "corpus_seed": 15001,
        "exposed_cases": 4,
        "confirmation_families": 8,
        "confirmation_cases": 32,
        "renderers": ["raw", "native_chat"],
        "information": ["query_only", "inline"],
        "regimes": [
            {"id": "greedy", "seed": 0, "temperature": 0.0},
            {"id": "sample211", "seed": 211, "temperature": 0.7},
        ],
        "maximum_prompt_tokens": 512,
        "max_new_tokens": 64,
        "expected_unique_prefixes": 144,
        "expected_generation_sequences": 288,
        "stop_rule": "model EOS only; otherwise length at 64 new tokens",
        "parser": (
            "whole stripped answer yes/no, casefolded; lowercase compliance separate; "
            "length-truncated is incorrect"
        ),
        "choice_suffixes": [" no", " yes"],
        "history": "full-prefix recomputation; no KV cache",
        "optimizer_steps": 0,
        "workspace_loaded": False,
        "primary_renderer": "native_chat",
        "gate": {
            "scope": (
                "finite-panel expression qualification, not causal fact-use "
                "or model-quality qualification"
            ),
            "split": "confirmation",
            "information": "inline",
            "regime": "greedy",
            "valid_eos_required": 32,
            "correct_per_view_required": 12,
            "per_view_denominator": 16,
            "correct_per_view_wording_required": 6,
            "per_view_wording_denominator": 8,
        },
        "resources": {
            "admission_free_gib": 20,
            "allocator_cap_gib": 18,
            "abort_free_gib": 4,
            "poll_steps": 16,
            "cpu_threads": 2,
        },
        "claims": {
            "training_performed": False,
            "semantic_promotion": False,
            "non_regression": "NOT_ESTABLISHED",
            "quality_judging": "NOT_RUN",
        },
    }
    if plan != expected:
        raise ValueError("Frozen elicitation contract changed")
    if verify_previous(REPO / plan["predecessor_bundle"])["status"] != "VERIFIED_RECEIPTS":
        raise RuntimeError("Previous assay verification failed")
    cases = make_cases(REPO)
    if len(cases) != 36 or len({c["case_id"] for c in cases}) != 36:
        raise RuntimeError("Case inventory mismatch")
    return plan, parent, cases


def sources(parent):
    result = previous.sources(parent)
    names = [
        "configs/v15/ELICITATION_PLAN.json",
        "docs/v15/ELICITATION_PLAN.md",
        "scripts/run_v15_elicitation.py",
        "scripts/v15_elicitation_inputs.py",
        "scripts/verify_v15_elicitation.py",
        "scripts/verify_v15_readout_transport.py",
        "scripts/v13_task_fixture.py",
        "configs/v14/MISTRAL_PROMPT_GATE_PLAN.json",
    ]
    result.update({name: prior.digest(REPO / name) for name in names})
    return result


def tokenizer_identity():
    """Verify pinned tokenizer/template and model metadata before using cached files."""
    old = json.loads((REPO / "configs/v14/MISTRAL_PROMPT_GATE_PLAN.json").read_text())["model"]
    snapshot = Path(old["snapshot"])
    names = {
        "config.json",
        "generation_config.json",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer.model",
        "tokenizer.model.v3",
        "tokenizer_config.json",
    }
    receipts = [r for r in old["snapshot_content_anchor"] if r["path"] in names]
    if {r["path"] for r in receipts} != names:
        raise RuntimeError("Tokenizer anchor coverage changed")
    if (snapshot / "chat_template.jinja").exists() or (snapshot / "chat_templates").exists():
        raise RuntimeError("Unanchored external chat template overrides pinned config")
    for row in receipts:
        file = snapshot / row["path"]
        if file.stat().st_size != row["bytes"] or prior.digest(file) != row["sha256"]:
            raise RuntimeError(f"Pinned metadata mismatch: {row['path']}")
    template = json.loads((snapshot / "tokenizer_config.json").read_text())["chat_template"]
    if not isinstance(template, str):
        raise RuntimeError("Expected pinned single chat template")
    return {
        "snapshot": str(snapshot),
        "files": receipts,
        "chat_template_sha256": hashlib.sha256(template.encode()).hexdigest(),
    }


def render_inputs(tokenizer, cases, plan):
    renderings = []
    for case in cases:
        for renderer in plan["renderers"]:
            for information in plan["information"]:
                row = render_case(
                    tokenizer,
                    query=case["query"],
                    context=case["context"],
                    renderer=renderer,
                    information=information,
                )
                if len(row["prompt_ids"]) > plan["maximum_prompt_tokens"]:
                    raise RuntimeError("Prompt exceeds frozen bound; no truncation")
                renderings.append(
                    {
                        "case_id": case["case_id"],
                        "renderer": renderer,
                        "information": information,
                        **row,
                    }
                )
    if len(renderings) != plan["expected_unique_prefixes"]:
        raise RuntimeError("Rendering denominator mismatch")
    return renderings


class BaseBackend:
    def __init__(self, base, shared):
        self.base, self.shared, self.parity_checks = base, shared, 0

    @torch.no_grad()
    def encode(self, prefix):
        ids = torch.tensor([prefix], device=self.base.device)
        return self.base.model(
            ids, attention_mask=torch.ones_like(ids), use_cache=False
        ).last_hidden_state

    def delta(self, condition, hidden, prefix):
        raise RuntimeError("This base-only assay must not invoke a workspace")

    def readout(self, hidden, delta):
        if bool(torch.count_nonzero(delta)):
            raise RuntimeError("Nonzero residual in base-only assay")
        out = self.shared(hidden, delta)
        old, _ = native_full_readout(hidden, delta, self.shared.head)
        if not torch.equal(out.logits, old) or bool(torch.count_nonzero(out.applied_delta)):
            raise RuntimeError("Base native readout parity failed")
        self.parity_checks += 1
        return out


@torch.no_grad()
def initial_choices(base, readout, renderings, guard):
    result = []
    backend = BaseBackend(base, readout)
    for index, row in enumerate(renderings):
        guard(f"initial:{index}")
        ids = torch.tensor([row["prompt_ids"]], device=base.device)
        actual = base(ids, attention_mask=torch.ones_like(ids), use_cache=False).logits
        hidden = backend.encode(tuple(row["prompt_ids"]))
        out = backend.readout(hidden, torch.zeros_like(hidden[:, -1:]).float())
        if not torch.equal(actual.float(), out.logits.float()):
            raise RuntimeError("Ordinary/shared native full-logit mismatch")
        logits = out.last_logits[0].double()
        top = int(logits.argmax())
        result.append(
            {
                "case_id": row["case_id"],
                "renderer": row["renderer"],
                "information": row["information"],
                "candidate_ids": row["candidate_ids"],
                "native": previous.scores(out.choice_scores(row["candidate_ids"])),
                "candidate_probabilities": logits.softmax(-1)[row["candidate_ids"]].tolist(),
                "top1_token_id": top,
                "top1_probability": float(logits.softmax(-1)[top]),
                "ordinary_shared_full_logits_exact": True,
                "shared_historical_full_logits_exact": True,
                "zero_delta_exact": True,
            }
        )
        del actual, hidden, out, logits
    return result


def replay_exposed(rows, old_rows):
    checks = 0
    for row in rows:
        if row["split"] != "exposed" or row["renderer"] != "raw":
            continue
        old = next(
            r
            for r in old_rows
            if r["case_id"] == row["case_id"]
            and r["regime"] == row["regime"]
            and r["condition"] == row["condition"]
        )
        for key in ("prompt_ids", "generated_ids", "answer", "finish_reason", "token_trace"):
            if row[key] != old[key]:
                raise RuntimeError(f"Historical exposed raw replay mismatch: {key}")
        checks += 1
    if checks != 16:
        raise RuntimeError("Historical replay denominator mismatch")
    return checks


@torch.no_grad()
def generate(base, readout, tokenizer, cases, renderings, plan, guard):
    indexed = {(r["case_id"], r["renderer"], r["information"]): r for r in renderings}
    eos = base.generation_config.eos_token_id
    eos = {eos} if isinstance(eos, int) else set(eos)
    if eos != {tokenizer.eos_token_id}:
        raise RuntimeError("Model/tokenizer EOS disagreement")
    rows, receipts = [], []
    for case_index, case in enumerate(cases):
        for renderer in plan["renderers"]:
            prompts = {
                condition: indexed[case["case_id"], renderer, information]["prompt_ids"]
                for condition, information in (("base", "query_only"), ("base_inline", "inline"))
            }
            for regime in plan["regimes"]:
                backend = BaseBackend(base, readout)
                group, receipt = generate_matched(
                    case_id=case["case_id"],
                    prompts=prompts,
                    regime=regime,
                    max_new_tokens=plan["max_new_tokens"],
                    eos_token_ids=eos,
                    backend=backend,
                    decode=lambda ids: tokenizer.decode(ids, skip_special_tokens=True),
                    zero_pairs=(),
                    guard=lambda: guard(f"generation:{case_index}:{renderer}:{regime['id']}"),
                )
                for row in group:
                    parsed = parse_functional_answer(row["answer"])
                    valid = parsed is not None and row["finish_reason"] == "eos"
                    row.update(
                        renderer=renderer,
                        information="inline" if row["condition"] == "base_inline" else "query_only",
                        split=case["split"],
                        family_id=case["family_id"],
                        view=case["view"],
                        wording=case["wording"],
                        target_label=case["target_label"],
                        parsed_answer=parsed,
                        valid_eos=valid,
                        lowercase_compliant=row["answer"].strip() in ("no", "yes"),
                        strict_correct=valid and parsed == case["target_label"],
                    )
                    # The historical generator ID omits renderer; this new run has both.
                    row["id"] = f"{row['id']}__{renderer}"
                    rows.append(row)
                receipts.append(
                    {
                        "case_id": case["case_id"],
                        "renderer": renderer,
                        "regime": regime["id"],
                        **receipt,
                        "shared_historical_native_checks": backend.parity_checks,
                    }
                )
        print(f"case {case_index + 1}/{len(cases)} {case['split']} complete", flush=True)
    if len(rows) != plan["expected_generation_sequences"]:
        raise RuntimeError("Generation grid mismatch")
    return {"rows": rows, "receipts": receipts, "eos_token_ids": sorted(eos)}


def execute(output):
    import transformers

    plan, parent, cases = validate()
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
    guard = previous.previous.ResourceGuard(plan["resources"], output)
    start = time.monotonic()
    try:
        admission = guard("admission", admission=True)
        hashes = sources(parent)
        tokenizer_before = tokenizer_identity()
        write_new(
            output / "STARTED.json",
            {
                "source_commit": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
                ).strip(),
                "source_hashes": hashes,
                "runtime": runtime,
                "plan": plan,
                "admission": admission,
                "tokenizer_identity": tokenizer_before,
            },
        )
        write_new(output / "CASES.json", cases)
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        torch.set_float32_matmul_precision("highest")
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        if torch.cuda.device_count() != 1:
            raise RuntimeError("One CUDA device required")
        torch.cuda.set_per_process_memory_fraction(
            plan["resources"]["allocator_cap_gib"]
            * 2**30
            / torch.cuda.get_device_properties(0).total_memory
        )
        torch.cuda.reset_peak_memory_stats()
        config = engine.ModelConfig(**parent["model"])
        tokenizer = engine.load_tokenizer(config)
        if (
            hashlib.sha256(tokenizer.get_chat_template().encode()).hexdigest()
            != tokenizer_before["chat_template_sha256"]
        ):
            raise RuntimeError("Active chat template differs from pinned snapshot")
        renderings = render_inputs(tokenizer, cases, plan)
        write_new(output / "RENDERINGS.json", renderings)
        print("loading pinned original for base-only elicitation", flush=True)
        base = engine._load_hf_model(config).eval().requires_grad_(False).to("cuda")
        before = prior.state_hash(base)
        old_report = json.loads((REPO / plan["predecessor_bundle"] / "raw/REPORT.json").read_text())
        if before != old_report["base_state_sha256_after"]:
            raise RuntimeError("Base state mismatch")
        guard("loaded")
        readout = NativeWorkspaceReadout(base.lm_head)
        choices = initial_choices(base, readout, renderings, guard)
        write_new(output / "CHOICES.json", choices)
        generated = generate(base, readout, tokenizer, cases, renderings, plan, guard)
        old_rows = json.loads(
            (REPO / plan["predecessor_bundle"] / "raw/GENERATION.json").read_text()
        )["rows"]
        replay = replay_exposed(generated["rows"], old_rows)
        summary = summarize(cases, choices, generated["rows"], plan)
        generated["summary"] = summary
        write_new(output / "GENERATION.json", generated)
        after = prior.state_hash(base)
        if before != after or any(p.grad is not None for p in base.parameters()):
            raise RuntimeError("Frozen base mutated")
        if sources(parent) != hashes:
            raise RuntimeError("Source changed during run")
        if tokenizer_identity() != tokenizer_before:
            raise RuntimeError("Tokenizer metadata changed during run")
        guard("completed")
        report = {
            "status": "COMPLETED_BASE_ELICITATION_ASSAY",
            "optimizer_steps": 0,
            "workspace_loaded": False,
            "base_state_sha256_before": before,
            "base_state_sha256_after": after,
            "base_unchanged": True,
            "source_unchanged": True,
            "tokenizer_identity_unchanged": True,
            "unique_prefixes": len(renderings),
            "generation_sequences": len(generated["rows"]),
            "raw_replay_exact_sequences": replay,
            "eos_token_ids": generated["eos_token_ids"],
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
            k: report[k]
            for k in ("status", "elapsed_seconds", "unique_prefixes", "generation_sequences")
        }
    except Exception as exc:
        write_new(
            output / "FAILED.json",
            {
                "status": "INCOMPLETE",
                "exception_type": type(exc).__name__,
                "message": str(exc),
            },
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--tokenizer-preflight", action="store_true")
    args = parser.parse_args()
    if args.tokenizer_preflight:
        plan, parent, cases = validate()
        identity = tokenizer_identity()
        tokenizer = engine.load_tokenizer(engine.ModelConfig(**parent["model"]))
        if (
            hashlib.sha256(tokenizer.get_chat_template().encode()).hexdigest()
            != identity["chat_template_sha256"]
        ):
            raise RuntimeError("Active chat template mismatch")
        rows = render_inputs(tokenizer, cases, plan)
        print(
            json.dumps(
                {
                    "status": "TOKENIZATION_ONLY",
                    "prefixes": len(rows),
                    "max_tokens": max(len(r["prompt_ids"]) for r in rows),
                }
            )
        )
    elif args.dry_run:
        validate()
        print(json.dumps({"status": "PREPARED_NOT_RUN"}))
    elif args.output is None:
        parser.error("--output required")
    else:
        print(json.dumps(execute(args.output.resolve())))
