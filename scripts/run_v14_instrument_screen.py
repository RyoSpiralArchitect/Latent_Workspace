#!/usr/bin/env python3
"""One frozen, offline calibration screen; no training or held-out scoring."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from contextlib import nullcontext
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import torch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from run_v11_gate0 import flatten_functional_batch  # noqa: E402
from run_v14_portability_canary import (  # noqa: E402
    _cuda_peak_memory,
    _digest,
    _observed_runtime,
    _snapshot_files,
    _stat,
    check_inventory,
)
from v14_screen_metrics import return_decision, summarize  # noqa: E402
from v14_workspace_instrument import run_instrument  # noqa: E402

from latent_workspace_ft_v10 import engine as api  # noqa: E402
from latent_workspace_ft_v10.implementation_identity import implementation_fingerprint  # noqa: E402

PLAN_PATH = REPO / "configs/v14/INSTRUMENT_RETURN_PLAN.json"
DATA_PATH = REPO / "data/v14/instrument_calibration.jsonl"


def data_config():
    return api.DataConfig(
        functional_elicitation="symmetric_instruction",
        use_chat_template=False,
        add_bos=False,
        add_eos=False,
        prompt_separator="\n\n",
        functional_require_one_token_answer=True,
        functional_context_max_length=192,
        functional_query_max_length=96,
        functional_inline_max_length=256,
        functional_max_queries=2,
    )


def make_wrapper(base, mode="inline_sidecar"):
    """Fresh FP32 workspace around a BF16 base; never cast the whole wrapper."""
    workspace = api.WorkspaceConfig(
        steps=1,
        workspace_dim=64,
        ff_multiplier=1.0,
        architecture="token_local",
        attention_heads=4,
        bridge_heads=4,
        logit_rank=8,
        dropout=0.0,
        route_topology="functional_workspace",
        loss_weight=0.0,
    )
    functional = api.FunctionalWorkspaceConfig(
        enabled=True,
        route_mode=mode,
        boundary_layer=base.config.num_hidden_layers // 2,
        memory_mode="slots",
        slot_count=2,
        writer_steps=1,
        reader_steps=1,
        writer_heads=4,
        reader_heads=4,
        dropout=0.0,
        task_objective="choice_normalized",
        counterfactual_weight=0.0,
        stability_weight=0.0,
        minimum_queries_per_world=2,
        workspace_norm_kind="layer_norm",
        workspace_norm_eps=1e-5,
        logit_composition="fp32_accumulate" if mode == "inline_sidecar" else "legacy_native",
    )
    return (
        api.LatentWorkspaceCausalLM(
            base,
            hidden_dim=base.config.hidden_size,
            vocab_size=base.config.vocab_size,
            config=workspace,
            functional_config=functional,
        )
        .to(next(base.parameters()).device)
        .eval()
    )


def strict_tokenization(records, tokenizer):
    """Candidate concatenation must preserve the entire exact prefix, not only LCP."""
    config = data_config()
    features, candidates, prefix_count = [], set(), 0
    maxima = {"context": 0, "query": 0, "inline": 0}
    for record in records:
        for query in record["queries"]:
            elicited = api._functional_elicitation_query(query, config)
            prefixes = [elicited] + [
                c + config.prompt_separator + elicited for c in record["contexts"]
            ]
            for prefix in prefixes:
                prefix_ids = tokenizer.encode(prefix, add_special_tokens=False)
                suffix_ids = []
                for choice in record["choices"]:
                    full = tokenizer.encode(prefix + choice, add_special_tokens=False)
                    if full[:-1] != prefix_ids or len(full) != len(prefix_ids) + 1:
                        raise ValueError("Candidate changes prefix or is not exactly one token")
                    suffix_ids.append(full[-1])
                if len(set(suffix_ids)) != 2:
                    raise ValueError("Candidates are not distinct")
                candidates.add(tuple(suffix_ids))
                prefix_count += 1
        feature = api._encode_functional_world_pair(record, tokenizer, config)
        feature["sample_index"] = len(features)
        features.append(feature)
        maxima["context"] = max(
            maxima["context"], *(len(x) for x in feature["functional_context_ids"])
        )
        for kind in ("query", "inline"):
            maxima[kind] = max(
                maxima[kind], *(len(q) for s in feature[f"functional_{kind}_ids"] for q in s)
            )
    if len(candidates) != 1:
        raise ValueError("Candidate token identity differs across prefixes")
    return features, {
        "status": "PASS",
        "prefix_count": prefix_count,
        "candidate_ids": list(next(iter(candidates))),
        "max_unpadded_tokens": maxima,
        "unchanged_entire_prefix": True,
        "chat_template": False,
    }


def snapshot_inventory(path, byte_limit):
    files = _snapshot_files(path)
    if not files or len(files) > 128 or not any(p.suffix == ".safetensors" for p in files):
        raise ValueError("Expected bounded safetensors snapshot")
    if sum(p.stat().st_size for p in files) > byte_limit:
        raise ValueError("Snapshot exceeds model-specific byte cap")
    result = []
    for p in files:
        before = _stat(p)
        digest = _digest(p)
        if _stat(p) != before:
            raise ValueError("Snapshot changed during inventory")
        result.append({"path": str(p.relative_to(path)), **before, "sha256": digest})
    return result


def source_identity():
    paths = sorted((REPO / "scripts").glob("*.py"))
    return {
        "package": implementation_fingerprint(),
        "scripts": {str(p.relative_to(REPO)): _digest(p) for p in paths},
    }


def check_plan(plan, model_key):
    if source_identity() != plan["source_identity"]:
        raise ValueError("Frozen source identity mismatch")
    if _digest(DATA_PATH) != plan["calibration_sha256"]:
        raise ValueError("Frozen calibration digest mismatch")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True).strip():
        raise ValueError("Run requires clean isolated worktree")
    return plan["models"][model_key]


def check_predecessor(path, report):
    predecessor = json.loads(path.read_text())
    required = (
        predecessor.get("model_key") == "olmo",
        predecessor.get("status") == "COMPLETE",
        predecessor.get("return_to_mistral") is True,
        predecessor.get("instrument", {}).get("instrument_checks_passed") is True,
        predecessor.get("coverage_ok") is True,
        predecessor.get("integrity_ok") is True,
        predecessor.get("completed_cases") == 480,
        predecessor.get("base_parameter_identity_versions_unchanged") is True,
        predecessor.get("plan_sha256") == report["plan_sha256"],
        predecessor.get("source_identity") == report["source_identity"],
        predecessor.get("commit") == report["commit"],
    )
    if not all(required):
        raise ValueError("Predecessor does not admit Mistral re-entry under this plan/source")
    for name in ("cases.jsonl", "input_parity.jsonl"):
        if _digest(path.parent / name) != predecessor.get("artifact_sha256", {}).get(name):
            raise ValueError("Predecessor artifact identity mismatch")
    return _digest(path)


def _autocast(device):
    return torch.autocast("cuda", dtype=torch.bfloat16) if device == "cuda" else nullcontext()


def score_route(wrapper, batch, route, *, device, check_suffix=False):
    flat = flatten_functional_batch(batch, route)
    with torch.no_grad(), _autocast(device):
        direct = wrapper.base_model(
            input_ids=flat["input_ids"],
            attention_mask=flat["attention_mask"],
            use_cache=False,
            return_dict=True,
        ).logits
        _, choices, target_tokens, positions = wrapper._functional_answer_rows(
            direct, flat["labels"], flat["candidate_ids"]
        )
        raw = choices.float().cpu().tolist()
        direct_cpu = direct.detach().cpu()
        del direct
        actual = wrapper(
            input_ids=batch["input_ids"],
            attention_mask=batch["attention_mask"],
            **api.functional_batch_kwargs(batch),
            compute_workspace_loss=False,
            return_full_logits=True,
        )["logits"]
        exact = torch.equal(actual.detach().cpu(), direct_cpu)
        finite = bool(torch.isfinite(actual).all())
        del actual, direct_cpu
        suffix_check = None
        if check_suffix:
            altered = flat["input_ids"].clone()
            rows = torch.arange(len(positions), device=positions.device)
            # Change only the future supervised answer, keeping prefix/mask/shape unchanged.
            other_ids = (
                flat["candidate_ids"].gather(1, (1 - flat["answer_classes"])[:, None]).flatten()
            )
            if not torch.equal(altered[rows, positions + 1], target_tokens):
                raise ValueError("Answer-position alignment drift")
            altered[rows, positions + 1] = other_ids
            output = wrapper.base_model(
                input_ids=altered,
                attention_mask=flat["attention_mask"],
                use_cache=False,
                return_dict=True,
            ).logits
            changed_choices = (
                output[rows, positions].gather(1, flat["candidate_ids"]).float().cpu().tolist()
            )
            suffix_check = changed_choices == raw
            del output
    if not exact or not finite or suffix_check is False:
        raise ValueError("Base-route parity, finiteness or causal-suffix check failed")
    return raw, {
        "route": route,
        "full_logits_numeric_exact": exact,
        "finite": finite,
        "future_answer_blindness": suffix_check,
        "input_ids": flat["input_ids"].cpu().tolist(),
        "attention_mask": flat["attention_mask"].cpu().tolist(),
        "candidate_ids": flat["candidate_ids"].cpu().tolist(),
        "source_positions": positions.cpu().tolist(),
    }


def run(args):
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "format": "v14-instrument-screen-v1",
        "status": "RUNNING",
        "model_key": args.model,
        "started_utc": datetime.now(UTC).isoformat(),
        "training_performed": False,
        "heldout_model_scored": False,
        "scientific_success": False,
        "claim_boundary": (
            "Calibration-only frozen-base elicitation and artificial sidecar wiring. "
            "No R-D bridge or generalization qualification."
        ),
    }
    started, before, snapshot, cuda_started = time.monotonic(), None, None, False
    rows = []
    try:
        plan = json.loads(PLAN_PATH.read_text())
        model_plan = check_plan(plan, args.model)
        report.update(
            plan_sha256=_digest(PLAN_PATH),
            source_identity=source_identity(),
            commit=subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
            ).strip(),
        )
        if args.model == "mistral":
            if args.return_receipt is None:
                raise ValueError("Mistral requires completed OLMo return receipt")
            report["predecessor_receipt_sha256"] = check_predecessor(args.return_receipt, report)
        for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
            if os.environ.get(key) != "1":
                raise ValueError("Offline environment required")
        if not torch.cuda.is_available():
            raise ValueError("Frozen real-model screen requires CUDA")
        actual_runtime = {
            "torch": str(torch.__version__),
            "transformers": version("transformers"),
            "python": sys.version.split()[0],
            "cuda": torch.version.cuda,
        }
        if actual_runtime != plan["expected_runtime"]:
            raise ValueError(f"Runtime differs from frozen environment: {actual_runtime}")
        torch.set_num_threads(2)
        torch.set_num_interop_threads(2)
        torch.manual_seed(1401)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.set_float32_matmul_precision("highest")
        torch.cuda.set_per_process_memory_fraction(plan["cuda_allocator_fraction"])
        torch.cuda.reset_peak_memory_stats()
        cuda_started = True
        snapshot = Path(model_plan["snapshot"])
        if (
            snapshot.name != model_plan["revision"]
            or _digest(snapshot / "config.json") != model_plan["config_sha256"]
        ):
            raise ValueError("Pinned snapshot config identity mismatch")
        before = snapshot_inventory(snapshot, model_plan["max_snapshot_bytes"])
        report["snapshot_before"] = before
        content_anchor = [{k: row[k] for k in ("path", "bytes", "sha256")} for row in before]
        if content_anchor != model_plan["snapshot_content_anchor"]:
            raise ValueError("Snapshot payload differs from prelaunch content anchor")
        records = [json.loads(line) for line in DATA_PATH.read_text().splitlines()]
        if len(records) != 120 or any(r["metadata"]["split"] != "calibration" for r in records):
            raise ValueError("Only exact fixed calibration set allowed")
        from transformers import AutoModelForCausalLM, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            str(snapshot), local_files_only=True, trust_remote_code=False
        )
        features, report["tokenization"] = strict_tokenization(records, tokenizer)
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token_id = tokenizer.eos_token_id
        if tokenizer.pad_token_id is None:
            raise ValueError("No existing padding/EOS token")
        report["pad_token_id"] = tokenizer.pad_token_id
        model = (
            AutoModelForCausalLM.from_pretrained(
                str(snapshot),
                local_files_only=True,
                trust_remote_code=False,
                dtype=torch.bfloat16,
                attn_implementation="sdpa",
            )
            .to("cuda")
            .eval()
        )
        if model.config.model_type != model_plan["model_type"]:
            raise ValueError("Pinned architecture mismatch")
        identities = {
            n: (id(p), p._version, p.dtype, p.requires_grad) for n, p in model.named_parameters()
        }
        report["runtime"] = _observed_runtime("cuda", "sdpa")
        report["parameter_elements"] = sum(p.numel() for p in model.parameters())
        collator = api.CausalFineTuningCollator(tokenizer.pad_token_id, pad_to_multiple_of=8)

        def batch_at(i):
            return {k: v.to("cuda") for k, v in collator([features[i]]).items()}

        instrument_wrapper = make_wrapper(model)
        report["instrument"] = run_instrument(
            instrument_wrapper, batch_at(0), device="cuda", precision="bf16"
        )
        del instrument_wrapper
        torch.cuda.empty_cache()
        # Require explicit qualification; never infer it from status text.
        if report["instrument"].get("instrument_checks_passed") is not True:
            raise ValueError("Mechanical instrument did not qualify")
        wrappers = {
            "query_only": make_wrapper(model, "query_only"),
            "inline": make_wrapper(model, "inline"),
        }
        with (
            (output / "cases.jsonl").open("x") as stream,
            (output / "input_parity.jsonl").open("x") as inputs,
        ):
            for index, record in enumerate(records):
                if time.monotonic() - started > plan["max_elapsed_seconds"]:
                    raise TimeoutError("Predeclared elapsed-time bound reached; no retry")
                batch = batch_at(index)
                scores = {}
                for route, wrapper in wrappers.items():
                    scores[route], parity = score_route(
                        wrapper, batch, route, device="cuda", check_suffix=index == 0
                    )
                    inputs.write(json.dumps({"record_id": record["id"], **parity}) + "\n")
                meta = record["metadata"]
                for side in range(2):
                    for query in range(2):
                        row = {
                            "record_id": record["id"],
                            "family_id": meta["family_id"],
                            "role": meta["role"],
                            "hop": record["hop_distances"][query],
                            "template": meta["template"],
                            "orientation": meta["orientation"],
                            "edit_type": meta["edit_type"],
                            "side": side,
                            "query_index": query,
                            "target_index": record["answers"][side][query],
                            "affected": record["affected"][query],
                            "f0_logits": scores["query_only"][side * 2 + query],
                            "f1_logits": scores["inline"][side * 2 + query],
                        }
                        rows.append(row)
                        stream.write(json.dumps(row, allow_nan=False) + "\n")
                stream.flush()
                inputs.flush()
                if (index + 1) % 10 == 0:
                    print(
                        json.dumps({"model": args.model, "records_complete": index + 1, "of": 120}),
                        flush=True,
                    )
        report["metrics"] = summarize(rows)
        report["coverage_ok"] = (
            len(rows) == 480
            and report["metrics"]["coverage"]["ok"] is True
            and report["metrics"]["screen_complete"] is True
        )
        if not report["coverage_ok"]:
            raise ValueError("Fixed calibration coverage did not qualify")
        report["base_parameter_identity_versions_unchanged"] = identities == {
            n: (id(p), p._version, p.dtype, p.requires_grad) for n, p in model.named_parameters()
        }
        if not report["base_parameter_identity_versions_unchanged"]:
            raise ValueError("Base parameter identity/version changed")
        report["status"] = "COMPLETE"
    except Exception as exc:
        report.update(status="FAILED", error_type=type(exc).__name__, error=str(exc))
        import traceback

        report["traceback"] = traceback.format_exc()
    finally:
        report["completed_cases"] = len(rows)
        if before is not None:
            try:
                report["snapshot_after"] = check_inventory(snapshot, before)
                report["integrity_ok"] = report.get(
                    "source_identity"
                ) == source_identity() and report.get("plan_sha256") == _digest(PLAN_PATH)
                report["integrity_ok"] &= (
                    _digest(DATA_PATH) == json.loads(PLAN_PATH.read_text())["calibration_sha256"]
                )
                if not report["integrity_ok"]:
                    report.update(
                        status="FAILED", integrity_error="Post-run source/plan/data drift"
                    )
            except Exception as exc:
                report.update(status="FAILED", integrity_ok=False, integrity_error=str(exc))
        if cuda_started:
            report["cuda_memory"] = _cuda_peak_memory()
        report["elapsed_seconds"] = time.monotonic() - started
        report["artifact_sha256"] = {
            name: _digest(output / name)
            for name in ("cases.jsonl", "input_parity.jsonl")
            if (output / name).is_file()
        }
        report["return_decision"] = return_decision(
            instrument_ok=report.get("instrument", {}).get("instrument_checks_passed") is True,
            coverage_ok=report.get("coverage_ok") is True,
            integrity_ok=report.get("integrity_ok") is True,
            screen_complete=report["status"] == "COMPLETE",
        )
        report["return_to_mistral"] = report["return_decision"]["return_to_mistral"]
        (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "model": args.model,
                    "return_to_mistral": report["return_to_mistral"],
                    "error": report.get("error"),
                    "output": str(output),
                }
            ),
            flush=True,
        )
    return 0 if report["status"] == "COMPLETE" and report["return_to_mistral"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=("olmo", "mistral"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--return-receipt", type=Path)
    sys.exit(run(parser.parse_args()))
