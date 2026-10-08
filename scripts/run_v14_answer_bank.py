#!/usr/bin/env python3
"""Generate one frozen, paired V14 answer bank; no training or external API."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import torch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
import run_v14_precision_bridge as prior  # noqa: E402
from run_v14_boundary_training import atomic_write, digest, resolve_inside  # noqa: E402

from latent_workspace_ft_v10 import engine  # noqa: E402
from latent_workspace_ft_v10.answer_bank_generation import (  # noqa: E402
    CONDITIONS,
    generate_group,
    native_full_readout,
)
from latent_workspace_ft_v10.contrastive_read_bridge import (  # noqa: E402
    CenteredValueWorkspaceBridge,
)
from latent_workspace_ft_v10.model_binding import FunctionalBoundaryAdapter  # noqa: E402
from latent_workspace_ft_v10.precision_bridge import PrecisionAwareWorkspaceBridge  # noqa: E402

PLAN = REPO / "configs/v14/ANSWER_BANK_PLAN.json"
REGIMES = [
    {"id": "greedy", "seed": 0, "temperature": 0.0},
    {"id": "sample211", "seed": 211, "temperature": 0.7},
    {"id": "sample212", "seed": 212, "temperature": 0.7},
]


def read_bound(spec, label):
    path = resolve_inside(REPO, spec["path"], label=label)
    if not path.is_file() or path.is_symlink() or digest(path) != spec["sha256"]:
        raise ValueError(f"{label} file identity changed")
    return json.loads(path.read_text())


def validate_cases(envelope):
    cases = envelope["cases"]
    if len(cases) != 16 or Counter(case["lane"] for case in cases) != {"relation": 8, "general": 8}:
        raise ValueError("Frozen case/lane denominators changed")
    ids = [case["id"] for case in cases]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r"[A-Za-z0-9_-]+", key) for key in ids):
        raise ValueError("Case IDs must be unique safe artifact names")
    for case in cases:
        for field in ("user_prompt", "memory_text", "twin_memory_text", "unrelated_memory_text"):
            if not isinstance(case[field], str) or not case[field].strip():
                raise ValueError(f"Missing case text: {field}")
        if (
            len({case[key] for key in ("memory_text", "twin_memory_text", "unrelated_memory_text")})
            != 3
        ):
            raise ValueError("Memory controls must be textually distinct")
        if "reference" not in case or "rubric" not in case:
            raise ValueError("Human/judge reference metadata is missing")
    return cases


def validate_plan(plan):
    if (
        plan["format"] != "latent-workspace-v14-answer-bank-plan-v1"
        or plan["semantic_promotion"] is not False
    ):
        raise ValueError("Unexpected answer-bank plan contract")
    if plan["conditions"] != list(CONDITIONS) or plan["regimes"] != REGIMES:
        raise ValueError("Frozen conditions or sampling regimes changed")
    generation = plan["generation"]
    if generation != {
        "max_new_tokens": 128,
        "top_p": 1.0,
        "boundary_layer": 16,
        "max_prompt_tokens": 1024,
        "max_memory_tokens": 1024,
    }:
        raise ValueError("Frozen generation geometry changed")
    if not plan["source_identity"]:
        raise ValueError("Source identity must be frozen")
    required = {
        "scripts/run_v14_answer_bank.py",
        "scripts/run_v14_precision_bridge.py",
        "scripts/run_v14_boundary_training.py",
        "src/latent_workspace_ft_v10/answer_bank_generation.py",
        "src/latent_workspace_ft_v10/engine.py",
        "src/latent_workspace_ft_v10/precision_bridge.py",
        "src/latent_workspace_ft_v10/contrastive_read_bridge.py",
        "src/latent_workspace_ft_v10/model_binding.py",
        "src/latent_workspace_ft_v10/workspace_core.py",
    }
    if not required <= set(plan["source_identity"]):
        raise ValueError("Required generation sources are not bound")
    for name, expected in plan["source_identity"].items():
        path = resolve_inside(REPO, name, label="source")
        if digest(path) != expected:
            raise ValueError(f"Frozen source changed: {name}")
    reports = {}
    for family in ("legacy", "centered"):
        reports[family] = read_bound(plan["predecessors"][family], f"{family} report")
        checkpoint_plan = read_bound(plan["checkpoint_plans"][family], f"{family} checkpoint plan")
        if reports[family]["status"] != "QUALIFIED_EXECUTION":
            raise ValueError("Predecessor execution is not qualified")
        if reports[family]["plan_sha256"] != plan["checkpoint_plans"][family]["sha256"]:
            raise ValueError("Predecessor report is not bound to checkpoint plan")
        for key in ("model", "bridge", "expected_runtime"):
            if plan[key] != checkpoint_plan[key]:
                raise ValueError(f"Predecessor {key} differs")
    if (
        reports["legacy"]["base_state_sha256_before"]
        != reports["centered"]["base_state_sha256_before"]
    ):
        raise ValueError("Predecessors disagree about original base identity")
    cases = validate_cases(read_bound(plan["cases"], "cases"))
    output = resolve_inside(REPO, plan["output"], label="output")
    if not str(output.relative_to(REPO)).startswith("runs/v14/"):
        raise ValueError("Output must be a dedicated V14 run directory")
    return cases, reports


def checkpoint_inventory(reports):
    inventory = {}
    for family, report in reports.items():
        candidates = [
            entry
            for entry in report["training"]["semantic"]["checkpoints"]
            if entry["path"].endswith("/semantic_step256.pt")
        ]
        if len(candidates) != 1:
            raise ValueError("Expected one semantic step256 checkpoint per family")
        entry = candidates[0]
        path = resolve_inside(REPO, entry["path"], label="checkpoint")
        if (
            not path.is_file()
            or path.is_symlink()
            or path.stat().st_size != entry["bytes"]
            or digest(path) != entry["sha256"]
        ):
            raise ValueError(f"Retained checkpoint identity changed: {family}")
        inventory[family] = dict(entry)
    return inventory


def prepare_prompts(case, tokenizer, max_tokens):
    prompts = {}
    for condition in CONDITIONS:
        # References/rubrics/expected answers never enter any model prompt.
        text = case["user_prompt"]
        if condition == "base_inline":
            text = case["memory_text"] + "\n\n" + text
        messages = [{"role": "user", "content": text}]
        ids = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True)
        if not isinstance(ids, list) or not ids or len(ids) > max_tokens:
            raise ValueError(
                "Chat prompt is empty, malformed or over budget; no truncation allowed"
            )
        prompts[condition] = {
            "ids": ids,
            "messages": messages,
            "rendered_prompt": tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            ),
        }
    return prompts


class FrozenBackend:
    """The independently loaded original decoder and two immutable bridge cells."""

    def __init__(self, base, bridges, memories, device):
        self.base, self.bridges, self.memories, self.device = base, bridges, memories, device
        self.head = base.lm_head

    @torch.no_grad()
    def encode(self, prefix):
        ids = torch.tensor([prefix], dtype=torch.long, device=self.device)
        return self.base.model(
            input_ids=ids, attention_mask=torch.ones_like(ids), use_cache=False, return_dict=True
        ).last_hidden_state

    @torch.no_grad()
    def delta(self, condition, hidden):
        family = "legacy" if condition == "legacy_semantic" else "centered"
        memory_key = {
            "legacy_semantic": "intact",
            "centered_semantic": "intact",
            "centered_zero": "zero",
            "centered_unrelated": "unrelated",
            "centered_twin": "twin",
        }[condition]
        memory, mask = self.memories[family][memory_key]
        return self.bridges[family].read_delta(hidden[:, -1:], memory, mask)


@torch.no_grad()
def prepare_memories(case, tokenizer, boundary, bridges, generation, device):
    memories = {family: {} for family in bridges}
    receipt = {}
    for key, field in (
        ("intact", "memory_text"),
        ("twin", "twin_memory_text"),
        ("unrelated", "unrelated_memory_text"),
    ):
        tokens = tokenizer.encode(case[field], add_special_tokens=False)
        if not tokens or len(tokens) > generation["max_memory_tokens"]:
            raise ValueError("Memory is empty or over budget; no truncation allowed")
        ids = torch.tensor([tokens], dtype=torch.long, device=device)
        context = boundary.encode(ids, torch.ones_like(ids), generation["boundary_layer"])
        for family, bridge in bridges.items():
            memory, mask = bridge.write_memory(
                context, torch.ones(context.shape[:2], dtype=torch.long, device=device)
            )
            memories[family][key] = (memory, mask)
        receipt[key] = {
            "text_sha256": hashlib.sha256(case[field].encode()).hexdigest(),
            "token_ids": tokens,
            "boundary_layer": generation["boundary_layer"],
            "query_independent_encoding": True,
        }
    for family in bridges:
        memory, mask = memories[family]["intact"]
        memories[family]["zero"] = (torch.zeros_like(memory), mask)
    return memories, receipt


@torch.no_grad()
def ordinary_base_gate(backend, prefix):
    ids = torch.tensor([prefix], dtype=torch.long, device=backend.device)
    ordinary = backend.base(
        input_ids=ids, attention_mask=torch.ones_like(ids), use_cache=False, return_dict=True
    ).logits
    hidden = backend.encode(prefix)
    manual, _ = native_full_readout(
        hidden, torch.zeros_like(hidden[:, -1:], dtype=torch.float32), backend.head
    )
    if not torch.equal(ordinary, manual):
        raise RuntimeError(
            "Full-sequence manual readout differs from ordinary original base forward"
        )
    return {
        "full_logits_exact": True,
        "positions": len(prefix),
        "vocabulary_size": ordinary.shape[-1],
        "ordinary_logits_dtype": str(ordinary.dtype),
        "manual_logits_dtype": str(manual.dtype),
        "kv_cache_used": False,
    }


def write_new(path, value):
    if path.exists():
        raise FileExistsError(f"Refusing answer artifact overwrite: {path}")
    atomic_write(path, value)


@torch.no_grad()
def execute(plan, dry_run=False):
    cases, reports = validate_plan(plan)
    if dry_run:
        return {
            "status": "PREPARED_NOT_RUN",
            "cases": len(cases),
            "answers": len(cases) * len(REGIMES) * len(CONDITIONS),
            "checkpoint_bodies_checked": False,
        }
    import transformers

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
    inventory = checkpoint_inventory(reports)
    output = resolve_inside(REPO, plan["output"], label="output")
    output.mkdir(parents=True, exist_ok=False)
    source_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
    ).strip()
    write_new(
        output / "STARTED.json",
        {
            "plan_sha256": digest(PLAN),
            "source_commit": source_commit,
            "runtime": runtime,
            "checkpoint_inventory": inventory,
            "expected_answers": 336,
        },
    )
    started = time.monotonic()
    try:
        device = torch.device("cuda")
        torch.set_num_threads(2)
        torch.set_float32_matmul_precision("highest")
        torch.backends.cuda.matmul.allow_tf32 = False
        config = engine.ModelConfig(**plan["model"])
        tokenizer = engine.load_tokenizer(config)
        if not tokenizer.chat_template:
            raise ValueError("Pinned tokenizer has no chat template")
        base = engine._load_hf_model(config).eval().requires_grad_(False).to(device)
        base_before = prior.state_hash(base)
        if base_before != reports["legacy"]["base_state_sha256_before"]:
            raise ValueError("Independently loaded original base identity changed")
        versions = {name: p._version for name, p in base.named_parameters()}
        bridges = {}
        bridge_before = {}
        for family, cls in (
            ("legacy", PrecisionAwareWorkspaceBridge),
            ("centered", CenteredValueWorkspaceBridge),
        ):
            payload = torch.load(
                REPO / inventory[family]["path"], map_location="cpu", weights_only=True
            )
            if (
                payload["step"] != 256
                or payload["cell"] != "semantic"
                or payload["base_revision"] != plan["model"]["revision"]
                or payload["plan_sha256"] != plan["checkpoint_plans"][family]["sha256"]
            ):
                raise ValueError("Retained checkpoint metadata changed")
            if family == "centered" and payload["bridge_kind"] != "centered_values":
                raise ValueError("Centered checkpoint architecture changed")
            bridge = cls(base.config.hidden_size, **plan["bridge"])
            bridge.load_state_dict(payload["state_dict"], strict=True)
            bridge = bridge.to(device).float().eval().requires_grad_(False)
            bridge_before[family] = prior.state_hash(bridge)
            if (
                bridge_before[family]
                != reports[family]["training"]["semantic"]["final_state_sha256"]
            ):
                raise ValueError("Retained bridge tensor-state identity changed")
            bridges[family] = bridge
            del payload
        eos = getattr(base.generation_config, "eos_token_id", None)
        if eos is None:
            eos = tokenizer.eos_token_id
        eos = {int(value) for value in (eos if isinstance(eos, (tuple, list)) else [eos])}
        boundary = FunctionalBoundaryAdapter(base)
        rows, group_receipts, memory_receipts, base_gates = [], [], {}, {}
        for case in cases:
            prompts = prepare_prompts(case, tokenizer, plan["generation"]["max_prompt_tokens"])
            memories, memory_receipts[case["id"]] = prepare_memories(
                case, tokenizer, boundary, bridges, plan["generation"], device
            )
            backend = FrozenBackend(base, bridges, memories, device)
            # Every case validates the ordinary native forward, including inline geometry.
            base_gates[case["id"]] = {
                key: ordinary_base_gate(backend, prompts[key]["ids"])
                for key in ("base", "base_inline")
            }
            for regime in REGIMES:
                print(
                    f"generate {case['id']} {regime['id']} ({len(rows)}/336 answers complete)",
                    flush=True,
                )
                generated, receipt = generate_group(
                    case_id=case["id"],
                    lane=case["lane"],
                    regime=regime,
                    prompts=prompts,
                    backend=backend,
                    max_new_tokens=plan["generation"]["max_new_tokens"],
                    eos_token_ids=eos,
                    decode=lambda ids: tokenizer.decode(ids, skip_special_tokens=True),
                    on_answer=lambda row: write_new(output / "answers" / f"{row['id']}.json", row),
                )
                rows.extend(generated)
                group_receipts.append({"case_id": case["id"], "regime": regime["id"], **receipt})
                write_new(
                    output / "groups" / f"{case['id']}__{regime['id']}.json", group_receipts[-1]
                )
            del backend, memories
        if len(rows) != 336 or len({row["id"] for row in rows}) != 336:
            raise RuntimeError("Answer bank denominator mismatch")
        base_after = prior.state_hash(base)
        bridge_after = {family: prior.state_hash(bridge) for family, bridge in bridges.items()}
        if (
            base_before != base_after
            or versions != {name: p._version for name, p in base.named_parameters()}
            or any(p.grad is not None for p in base.parameters())
        ):
            raise RuntimeError("Frozen original base mutated")
        if bridge_before != bridge_after or checkpoint_inventory(reports) != inventory:
            raise RuntimeError("Frozen bridge state/checkpoint mutated")
        validate_plan(plan)
        bank = {
            "format": "latent-workspace-v14-answer-bank-v1",
            "plan_sha256": digest(PLAN),
            "rows": rows,
        }
        write_new(output / "bank.json", bank)
        write_new(output / "memory_receipts.json", memory_receipts)
        report = {
            "format": "latent-workspace-v14-answer-bank-result-v1",
            "status": "QUALIFIED_EXECUTION",
            "semantic_promotion": False,
            "winner": "none",
            "plan_sha256": digest(PLAN),
            "source_commit": source_commit,
            "source_identity": plan["source_identity"],
            "runtime": runtime,
            "gpu": torch.cuda.get_device_name(),
            "checkpoint_inventory": inventory,
            "base_state_sha256_before": base_before,
            "base_state_sha256_after": base_after,
            "bridge_state_sha256_before": bridge_before,
            "bridge_state_sha256_after": bridge_after,
            "base_unchanged": True,
            "bridges_unchanged": True,
            "checkpoint_bodies_unchanged": True,
            "ordinary_base_gates": base_gates,
            "group_receipts": group_receipts,
            "denominators": {
                "cases": len(cases),
                "regimes": 3,
                "conditions": 7,
                "answers": len(rows),
                "generated_tokens": sum(row["token_count"] for row in rows),
            },
            "finish_counts": dict(Counter(row["finish_reason"] for row in rows)),
            "finish_counts_by_condition": {
                condition: dict(
                    Counter(row["finish_reason"] for row in rows if row["condition"] == condition)
                )
                for condition in CONDITIONS
            },
            "eos_token_ids": sorted(eos),
            "bank_sha256": digest(output / "bank.json"),
            "chat_template_sha256": hashlib.sha256(
                str(tokenizer.chat_template).encode()
            ).hexdigest(),
            "memory_receipts_sha256": digest(output / "memory_receipts.json"),
            "elapsed_seconds": time.monotonic() - started,
            "peak_cuda_bytes": torch.cuda.max_memory_allocated(),
            "claim_boundary": plan["claim_boundary"],
        }
        write_new(output / "report.json", report)
        return {
            "status": report["status"],
            "output": str(output),
            "answers": len(rows),
            "seconds": report["elapsed_seconds"],
        }
    except Exception as error:
        write_new(
            output / "FAILED.json",
            {
                "status": "FAILED_NOT_QUALIFIED",
                "error_type": type(error).__name__,
                "message": str(error),
                "elapsed_seconds": time.monotonic() - started,
                "resume_supported": False,
            },
        )
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(execute(json.loads(PLAN.read_text()), args.dry_run), indent=2))


if __name__ == "__main__":
    main()
