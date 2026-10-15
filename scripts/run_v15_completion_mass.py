#!/usr/bin/env python3
"""Post-result, base-only fixed alias plus immediate-EOS probability diagnostic."""

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
import run_v15_elicitation as previous  # noqa: E402
from v15_completion_mass import METADATA, bind_aliases, summarize  # noqa: E402
from verify_v15_elicitation import verify_bundle as verify_predecessor  # noqa: E402

PLAN = REPO / "configs/v15/COMPLETION_MASS_PLAN.json"
PREDECESSOR = REPO / "provenance/pilots/v15_base_elicitation_20261010"
BASE_HASH = "54d161755862ebf00d8acbca083d5f290a5de44d33af82ca885f3bd8f9c94312"
PLAN_HASH = "492dbfbaf9f1d6082132d9c322a622a53d3eee118f344b4604c54b827f680abf"
engine, prior, write_new = previous.engine, previous.prior, previous.write_new
ADDITIONS = (
    "configs/v15/COMPLETION_MASS_PLAN.json",
    "docs/v15/COMPLETION_MASS_PLAN.md",
    "scripts/run_v15_completion_mass.py",
    "scripts/v15_completion_mass.py",
    "scripts/verify_v15_completion_mass.py",
    "tests/test_run_v15_completion_mass.py",
    "tests/test_v15_completion_mass.py",
    "tests/test_verify_v15_completion_mass.py",
)


def load(path):
    return json.loads(path.read_text())


def prefix_digest(ids):
    return hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()


def validate():
    if prior.digest(PLAN) != PLAN_HASH:
        raise ValueError("Frozen completion-mass plan changed")
    plan = load(PLAN)
    _, parent, cases = previous.validate()
    if verify_predecessor(PREDECESSOR)["status"] != "VERIFIED_RECEIPTS":
        raise RuntimeError("Predecessor verification failed")
    if plan["predecessor_artifact_index_sha256"] != prior.digest(
        PREDECESSOR / "ARTIFACT_INDEX.json"
    ):
        raise RuntimeError("Frozen predecessor artifact changed")
    if load(PREDECESSOR / "raw/CASES.json") != cases:
        raise RuntimeError("Predecessor cases changed")
    started, report = load(PREDECESSOR / "raw/STARTED.json"), load(PREDECESSOR / "raw/REPORT.json")
    if started["source_commit"] != plan["predecessor_source_commit"]:
        raise RuntimeError("Predecessor source commit changed")
    if report["summary"]["primary_expression_gate"] != "FAIL":
        raise RuntimeError("Predecessor expression gate changed")
    if report["base_state_sha256_after"] != BASE_HASH:
        raise RuntimeError("Predecessor model identity mismatch")
    return plan, parent, cases


def sources(parent):
    result = previous.sources(parent)
    result.update({name: prior.digest(REPO / name) for name in ADDITIONS})
    result["provenance/pilots/v15_base_elicitation_20261010/ARTIFACT_INDEX.json"] = prior.digest(
        PREDECESSOR / "ARTIFACT_INDEX.json"
    )
    return result


def prepare(tokenizer):
    renderings = load(PREDECESSOR / "raw/RENDERINGS.json")
    prepared = []
    for row in renderings:
        prepared.append(
            {**row, "bindings": bind_aliases(tokenizer, row["text"], row["prompt_ids"])}
        )
    if len(prepared) != 144:
        raise RuntimeError("Prefix denominator changed")
    return prepared


@torch.no_grad()
def score(base, readout, prepared, cases, old_choices, eos_id, guard):
    """Gold labels are metadata only, never passed into a forward or candidate ordering."""
    indexed = {(r["case_id"], r["renderer"], r["information"]): r for r in old_choices}
    case_index = {r["case_id"]: r for r in cases}
    backend = previous.BaseBackend(base, readout)
    result, alias_forwards = [], 0
    for index, row in enumerate(prepared):
        guard(f"prefix:{index}")
        prefix = row["prompt_ids"]
        old = indexed[row["case_id"], row["renderer"], row["information"]]
        ids = torch.tensor([prefix], device=base.device)
        actual = base(ids, attention_mask=torch.ones_like(ids), use_cache=False).logits
        hidden = backend.encode(tuple(prefix))
        out = backend.readout(hidden, torch.zeros_like(hidden[:, -1:]).float())
        if not torch.equal(actual.float(), out.logits.float()):
            raise RuntimeError("Ordinary/shared native full-logit mismatch")
        native = previous.previous.scores(out.choice_scores(row["candidate_ids"]))
        if native != old["native"]:
            raise RuntimeError("Frozen initial lowercase native scores did not replay exactly")
        initial_logits = out.last_logits[0].double()
        initial_logp = initial_logits.log_softmax(-1)
        initial_probability = initial_logits.softmax(-1)
        if (
            int(initial_logits.argmax()) != old["top1_token_id"]
            or float(initial_probability[old["top1_token_id"]]) != old["top1_probability"]
            or initial_probability[row["candidate_ids"]].tolist() != old["candidate_probabilities"]
        ):
            raise RuntimeError("Frozen initial full-vocabulary probability replay changed")
        first_values = {b["token_id"]: float(initial_logp[b["token_id"]]) for b in row["bindings"]}
        del actual, hidden, out, initial_logits, initial_logp, initial_probability, ids
        aliases = []
        for binding in row["bindings"]:
            hidden = backend.encode(tuple(prefix + [binding["token_id"]]))
            out = backend.readout(hidden, torch.zeros_like(hidden[:, -1:]).float())
            eos = float(out.last_logits[0].double().log_softmax(-1)[eos_id])
            first = first_values[binding["token_id"]]
            aliases.append(
                {
                    **binding,
                    "first_log_probability": first,
                    "eos_log_probability": eos,
                    "complete_log_probability": first + eos,
                    "first_probability": math.exp(first),
                    "eos_probability": math.exp(eos),
                    "complete_probability": math.exp(first + eos),
                }
            )
            alias_forwards += 1
            del hidden, out
        metadata = {**case_index[row["case_id"]], **row}
        result.append(
            {
                **{key: metadata[key] for key in METADATA},
                "prefix_ids": prefix,
                "prefix_sha256": prefix_digest(prefix),
                "old_lowercase_native": native,
                "initial_choice_replay_exact": True,
                "ordinary_shared_full_logits_exact": True,
                "aliases": aliases,
            }
        )
        if (index + 1) % 16 == 0:
            print(f"scored {index + 1}/{len(prepared)} prefixes", flush=True)
    return result, alias_forwards, backend.parity_checks


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
    guard = previous.previous.previous.ResourceGuard(plan["resources"], output)
    start = time.monotonic()
    try:
        admission = guard("admission", admission=True)
        hashes = sources(parent)
        tokenizer_before = previous.tokenizer_identity()
        write_new(
            output / "STARTED.json",
            {
                "source_commit": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
                ).strip(),
                "source_manifest_before": hashes,
                "runtime": runtime,
                "plan": plan,
                "plan_sha256": prior.digest(PLAN),
                "admission": admission,
                "tokenizer_identity_before": tokenizer_before,
                "predecessor_artifact_index_sha256": prior.digest(
                    PREDECESSOR / "ARTIFACT_INDEX.json"
                ),
            },
        )
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
            raise RuntimeError("Active pinned chat template mismatch")
        prepared = prepare(tokenizer)
        print("loading pinned original for fixed completion-path scoring", flush=True)
        base = engine._load_hf_model(config).eval().requires_grad_(False).to("cuda")
        before = prior.state_hash(base)
        if before != BASE_HASH:
            raise RuntimeError("Pinned base identity mismatch")
        eos = base.generation_config.eos_token_id
        if eos != tokenizer.eos_token_id or eos != 2:
            raise RuntimeError("Pinned single EOS changed")
        guard("loaded")
        rows, alias_forwards, parity = score(
            base,
            previous.NativeWorkspaceReadout(base.lm_head),
            prepared,
            cases,
            load(PREDECESSOR / "raw/CHOICES.json"),
            eos,
            guard,
        )
        summary = summarize(rows)
        write_new(output / "SCORES.json", rows)
        after = prior.state_hash(base)
        if before != after or any(p.grad is not None for p in base.parameters()):
            raise RuntimeError("Frozen base mutated")
        hashes_after, tokenizer_after = sources(parent), previous.tokenizer_identity()
        if hashes != hashes_after or tokenizer_before != tokenizer_after:
            raise RuntimeError("Source/tokenizer identity changed")
        guard("completed")
        report = {
            "status": "COMPLETED_COMPLETION_MASS_ASSAY",
            "optimizer_steps": 0,
            "workspace_loaded": False,
            "generation_sequences": 0,
            "base_sha256_before": before,
            "base_sha256_after": after,
            "source_manifest_before": hashes,
            "source_manifest_after": hashes_after,
            "tokenizer_identity_before": tokenizer_before,
            "tokenizer_identity_after": tokenizer_after,
            "plan_sha256": prior.digest(PLAN),
            "predecessor_artifact_index_sha256": prior.digest(PREDECESSOR / "ARTIFACT_INDEX.json"),
            "rows": len(rows),
            "alias_forwards": alias_forwards,
            "initial_choice_replay_matches": len(rows),
            "readout_parity_checks": parity,
            "eos_token_ids": [eos],
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
        return {k: report[k] for k in ("status", "rows", "alias_forwards", "elapsed_seconds")}
    except Exception as exc:
        write_new(
            output / "FAILED.json",
            {"status": "INCOMPLETE", "exception_type": type(exc).__name__, "message": str(exc)},
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--tokenizer-preflight", action="store_true")
    args = parser.parse_args()
    if args.tokenizer_preflight:
        _, parent, _ = validate()
        previous.tokenizer_identity()
        rows = prepare(engine.load_tokenizer(engine.ModelConfig(**parent["model"])))
        print(
            json.dumps(
                {
                    "status": "TOKENIZATION_ONLY",
                    "prefixes": len(rows),
                    "alias_paths": sum(len(r["bindings"]) for r in rows),
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
