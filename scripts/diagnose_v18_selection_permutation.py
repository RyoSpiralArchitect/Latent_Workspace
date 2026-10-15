#!/usr/bin/env python3
"""Bounded saved-state V18 permutation diagnosis; default is NO FORWARDS.

No optimizer, backward, writer call, fitted update, or gate repair is performed.
Production forwards are authoritative. Hooks observe the unchanged production
path; reconstructed centering/cap stages are observational, not interventions.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import signal
import subprocess
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "scripts/diagnose_v18_selection_permutation.py"
INPUT_COMMIT = "dd10b20a8fbb0e32e5ac89bcec939802e6940f8b"
PLAN = {
    "schema": "v18-saved-selection-permutation-plan-v1",
    "input_commit": INPUT_COMMIT,
    "model_seeds": [17, 29, 43],
    "factors": ["centered_final", "centered_ordered", "centered_symmetric", "raw_ordered"],
    "fits_per_device": 12,
    "held_out_rows_per_fit": 1152,
    "chunk_size": 256,
    "slot_permutation": [2, 0, 1],
    "primary_repetitions_per_order": 2,
    "native_dtype": "torch.float32",
    "reader_mode": "eval",
    "control_atol": 1e-6,
    "resources": {"wall_seconds": 900, "peak_bytes": 4 * 1024**3, "cpu_threads": 2},
    "training_updates": 0,
    "optimizer_instances": 0,
    "trace_scope": "observational only; exact unhooked production parity required",
    "fp64_shadow": "NOT_PERFORMED",
    "old_gate": {"status": "FAIL", "winner": "none", "non_regression": "NOT_ESTABLISHED"},
}
OFFLINE_ENV = {
    "HF_HUB_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
    "TOKENIZERS_PARALLELISM": "false",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
}


def sealed_guard(seal_path):
    """Validate the new caller seal before third-party/project imports."""
    if not sys.flags.isolated or not sys.dont_write_bytecode or not sys.pycache_prefix:
        raise ValueError("Use run_source_sealed.py with isolated Python and fresh bytecode cache")
    cache = Path(sys.pycache_prefix)
    if (
        not cache.is_absolute()
        or not cache.is_dir()
        or cache.is_symlink()
        or cache.resolve().is_relative_to(ROOT)
        or any(cache.iterdir())
    ):
        raise ValueError("Fresh empty bytecode directory outside source is required")
    spec = importlib.util.spec_from_file_location(
        "permutation_source_guard", ROOT / "scripts/run_source_sealed.py"
    )
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    seal = json.loads(Path(seal_path).read_text())
    return seal, guard.verify(ROOT, seal, ENTRY)


if __name__ == "__main__" and "--execute" in sys.argv:
    bootstrap = argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument("--source-seal", required=True, type=Path)
    boot, _ = bootstrap.parse_known_args()
    sealed_guard(boot.source_seal)
    os.environ.update(OFFLINE_ENV)

import torch  # noqa: E402
from torch.nn import functional as F  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
import assay_v18_operand_selection as assay  # noqa: E402
import audit_v18_operand_selection_terminal as audit  # noqa: E402


def require(condition, message):
    if not condition:
        raise ValueError(message)


def save_tensor(path, value):
    with Path(path).open("xb") as stream:
        torch.save(value, stream)


def input_hashes(directory):
    directory = Path(directory)
    require(not directory.is_symlink() and directory.is_dir(), "Input directory is not regular")
    files = {}
    for path in sorted(directory.rglob("*")):
        require(not path.is_symlink(), "Input symlink is forbidden")
        if path.is_file():
            relative = path.relative_to(directory).as_posix()
            files[relative] = audit.sha(audit.safe_file(directory, relative))
    require(bool(files), "Empty input bundle")
    return files


def population_from_saved(payload):
    return assay.Population(
        assay.Inputs(payload["states"], payload["memory"], payload["mask"]),
        assay.Inputs(payload["states"], payload["twin_memory"], payload["mask"]),
        payload["labels"],
        payload["twin_labels"],
        tuple(payload["rows"]),
        payload["frames"],
    )


def tensor_summary(original, changed):
    require(
        original.shape == changed.shape and original.dtype == changed.dtype,
        "Compared trace geometry/dtype differs",
    )
    require(
        bool(torch.isfinite(original).all() & torch.isfinite(changed).all()),
        "Nonfinite diagnostic tensor",
    )
    difference = (original.double() - changed.double()).abs()
    return {
        "exact": torch.equal(original, changed),
        "max_abs_error": float(difference.max()),
        "changed_elements": int(original.ne(changed).sum()),
        "elements": original.numel(),
    }


@contextmanager
def capture_production(bridge):
    """Observe actual module and SDPA outputs, restoring every hook/function.

    SDPA is wrapped without replacing its computation. Bias-free MHA uses the
    functional path in the sealed reader; fail closed if that path changes.
    The single-process/two-thread study is not a concurrent model service.
    """
    records, handles, active = {}, [], {"branch": None, "memory_calls": 0}

    def record(name, value):
        require(name not in records, f"Repeated trace event: {name}")
        records[name] = value.detach().clone()

    def simple(name):
        def hook(_module, _args, result):
            record(name, result)

        return hook

    def memory_hook(_module, _args, result):
        index = active["memory_calls"]
        require(index < 2, "Unexpected memory normalization call")
        record(("common" if index == 0 else "interaction") + ".memory_normalized", result)
        active["memory_calls"] += 1

    def attention_pre(branch):
        def hook(_module, args):
            require(active["branch"] is None, "Nested attention trace")
            active["branch"] = branch
            record(branch + ".attention_query", args[0])
            record(branch + ".attention_memory", args[1])

        return hook

    def attention_post(branch):
        def hook(_module, _args, result):
            record(branch + ".attention_output", result[0])
            active["branch"] = None

        return hook

    original_sdpa = F.scaled_dot_product_attention

    def observed_sdpa(query, key, value, *args, **kwargs):
        branch = active["branch"]
        require(branch in ("common", "interaction"), "Unidentified SDPA trace")
        record(branch + ".projected_q", query)
        record(branch + ".projected_k", key)
        record(branch + ".projected_v", value)
        result = original_sdpa(query, key, value, *args, **kwargs)
        record(branch + ".sdpa_output", result)
        return result

    try:
        handles.append(bridge.common.memory_norm.register_forward_hook(memory_hook))
        for branch, reader in (("common", bridge.common), ("interaction", bridge)):
            for name in ("query_projection", "query_norm", "up"):
                handles.append(
                    getattr(reader, name).register_forward_hook(simple(branch + "." + name))
                )
            handles.append(reader.attention.register_forward_pre_hook(attention_pre(branch)))
            handles.append(reader.attention.register_forward_hook(attention_post(branch)))
        F.scaled_dot_product_attention = observed_sdpa
        yield records
        require(
            active["memory_calls"] == 2 and active["branch"] is None, "Incomplete production trace"
        )
        require(
            all(branch + ".sdpa_output" in records for branch in ("common", "interaction")),
            "Unsupported attention path: no production SDPA observation",
        )
    finally:
        F.scaled_dot_product_attention = original_sdpa
        for handle in handles:
            handle.remove()


def centering_observation(values, mask, centered):
    """Same arithmetic as the frozen reader, checked against its observed input.

    Anchor/offset/mean are gauge-dependent and excluded from first-difference
    comparisons. The aligned centered values are the invariant comparison.
    """
    if not centered:
        return {"centered_memory": values}
    first = mask.bool().long().argmax(dim=1)
    anchor = values.gather(1, first[:, None, None].expand(-1, 1, values.shape[-1]))
    offsets = (values - anchor).masked_fill(~mask.bool().unsqueeze(-1), 0)
    summed = offsets.sum(dim=1, keepdim=True)
    mean = summed / mask.sum(dim=1)[:, None, None]
    result = (offsets - mean).masked_fill(~mask.bool().unsqueeze(-1), 0)
    return {
        "anchor_gauge": anchor,
        "offsets_gauge": offsets,
        "offset_sum_gauge": summed,
        "offset_mean_gauge": mean,
        "centered_memory": result,
    }


@torch.no_grad()
def traced_forward(bridge, inputs, factor):
    require(not bridge.training and not bridge.common.training, "Saved control requires eval mode")
    with capture_production(bridge) as trace:
        logits, delta = assay.forward(bridge, inputs, factor)
    trace["common_query"] = inputs.states[:, -1:].float().detach().clone()
    trace["interaction_query"] = assay.query(inputs.states, factor).detach().clone()
    centered = centering_observation(
        trace["interaction.memory_normalized"], inputs.mask, factor != "raw_ordered"
    )
    require(
        torch.equal(centered["centered_memory"], trace["interaction.attention_memory"]),
        "Reconstructed centering does not match production attention input",
    )
    trace.update({"interaction." + name: value for name, value in centered.items()})
    cap = bridge.max_delta_norm
    raw_common = trace["common.up"]
    common = raw_common * (cap / torch.sqrt(cap**2 + raw_common.square().sum(-1, keepdim=True)))
    raw = trace["interaction.up"]
    bounded = raw * (cap / torch.sqrt(cap**2 + raw.square().sum(-1, keepdim=True)))
    remaining = (1 - common.norm(dim=-1, keepdim=True) / cap).clamp(0, 1)
    interaction = bridge.interaction_fraction * remaining * bounded
    require(
        torch.equal(common + interaction, delta), "Reconstructed cap path differs from production"
    )
    require(
        torch.equal(assay.full_vocab_head(inputs.states, delta), logits),
        "Native full-vocabulary head differs from production",
    )
    trace.update(
        {
            "common.delta_reconstructed": common,
            "interaction.bounded_reconstructed": bounded,
            "interaction.remaining_fraction_reconstructed": remaining,
            "interaction.delta_reconstructed": interaction,
            "delta": delta,
            "native_logits": logits,
        }
    )
    return {key: value.detach().cpu().clone() for key, value in trace.items()}


def trace_measured(bridge, inputs, factor, device, guard):
    chunks = []
    for start in range(0, len(inputs.states), PLAN["chunk_size"]):
        guard()
        chunks.append(
            traced_forward(bridge, inputs.take(slice(start, start + 256)).to(device), factor)
        )
    require(all(set(chunk) == set(chunks[0]) for chunk in chunks), "Trace events differ by chunk")
    return {key: torch.cat([chunk[key] for chunk in chunks]) for key in chunks[0]}


BRANCH_STAGES = (
    "memory_normalized",
    "centered_memory",
    "query_projection",
    "query_norm",
    "projected_q",
    "projected_k",
    "projected_v",
    "sdpa_output",
    "attention_output",
    "up",
)


def compare_traces(original, permuted):
    inverse = torch.tensor(PLAN["slot_permutation"]).argsort()
    require(set(original) == set(permuted), "Trace populations differ")
    comparisons = {}
    for key, first in original.items():
        second = permuted[key]
        if key.endswith(("anchor_gauge", "offsets_gauge", "offset_sum_gauge", "offset_mean_gauge")):
            continue
        if key.endswith(("memory_normalized", "attention_memory", "centered_memory")):
            second = second.index_select(1, inverse)
        elif key.endswith(("projected_k", "projected_v")):
            second = second.index_select(2, inverse)
        comparisons[key] = tensor_summary(first, second)
    first_changed = {}
    for branch in ("common", "interaction"):
        stages = [
            branch + "." + item for item in BRANCH_STAGES if branch + "." + item in comparisons
        ]
        first_changed[branch] = next(
            (stage for stage in stages if not comparisons[stage]["exact"]), None
        )
    return {
        "aligned": comparisons,
        "first_changed_observed_stage": first_changed,
        "excluded_gauge_stages": [key for key in original if key.endswith("_gauge")],
        "interpretation": "Numerical localization only; neither mediation nor causal attribution",
    }


@torch.no_grad()
def diagnose_cell(bridge, pop, factor, device, guard, historical_controls, historical_logits=None):
    require(factor in PLAN["factors"], "Unknown frozen factor")
    require(not bridge.training and not bridge.common.training, "Saved control requires eval mode")
    before = assay.state_fingerprint(bridge)
    data = pop.inputs
    input_before = {
        name: assay.tensor_fingerprint(getattr(data, name)) for name in ("states", "memory", "mask")
    }
    permutation = PLAN["slot_permutation"]
    permuted = assay.Inputs(data.states, data.memory[:, permutation], data.mask[:, permutation])
    raw = {}
    for name, inputs in (("original", data), ("permuted", permuted)):
        for repeat in range(2):
            logits, delta = assay.measured(bridge, inputs, factor, device, torch.float32, guard)
            raw[f"{name}_{repeat}_logits"] = logits
            raw[f"{name}_{repeat}_delta"] = delta
    traces = {
        "original": trace_measured(bridge, data, factor, device, guard),
        "permuted": trace_measured(bridge, permuted, factor, device, guard),
    }
    for name in traces:
        require(
            torch.equal(traces[name]["native_logits"], raw[f"{name}_0_logits"])
            and torch.equal(traces[name]["delta"], raw[f"{name}_0_delta"]),
            "Hooks changed production output; no trace interpretation permitted",
        )
    current = assay.controls(bridge, factor, pop, device, guard, PLAN["control_atol"])
    require(
        current["permutation_max_logit_error"]
        == float((raw["permuted_0_logits"] - raw["original_0_logits"]).abs().max()),
        "Primary permutation observation and control call disagree",
    )
    require(before == assay.state_fingerprint(bridge), "Reader state changed during diagnosis")
    require(
        input_before
        == {name: assay.tensor_fingerprint(getattr(data, name)) for name in input_before},
        "Diagnostic mutated original inputs",
    )
    if historical_logits is not None:
        raw["historical_original_logits"] = historical_logits.detach().cpu().clone()
    summary = summarize_cell(raw, traces, current, historical_controls)
    summary.update(
        {
            "state_unchanged": True,
            "input_tensors_unchanged": True,
            "state_fingerprint": before,
            "rows": len(data.states),
            "training_updates": 0,
            "optimizer_instances": 0,
            "forward_calls": 12 * ((len(data.states) + 255) // 256),
        }
    )
    return {"raw": raw, "traces": traces}, summary


def summarize_cell(raw, traces, current, historical):
    repetition = {
        name: tensor_summary(raw[f"{name}_0_logits"], raw[f"{name}_1_logits"])
        for name in ("original", "permuted")
    }
    difference = tensor_summary(raw["original_0_logits"], raw["permuted_0_logits"])
    delta_repetition = {
        name: tensor_summary(raw[f"{name}_0_delta"], raw[f"{name}_1_delta"])
        for name in ("original", "permuted")
    }
    historical_native = (
        tensor_summary(raw["original_0_logits"], raw["historical_original_logits"])
        if "historical_original_logits" in raw
        else None
    )
    reproduced = current == historical
    repeatable = all(item["exact"] for item in (*repetition.values(), *delta_repetition.values()))
    primary_reproduced = reproduced and (historical_native is None or historical_native["exact"])
    return {
        "native_permutation": difference,
        "native_permutation_pass": difference["max_abs_error"] <= PLAN["control_atol"],
        "same_input_repeats": repetition,
        "same_input_delta_repeats": delta_repetition,
        "historical_original_logits": historical_native,
        "trace": compare_traces(traces["original"], traces["permuted"]),
        "hook_native_parity": all(
            torch.equal(traces[name]["native_logits"], raw[f"{name}_0_logits"])
            and torch.equal(traces[name]["delta"], raw[f"{name}_0_delta"])
            for name in traces
        ),
        "historical_controls": historical,
        "reobserved_controls": current,
        "historical_control_reproduction_exact": reproduced,
        "historical_mismatches": {
            key: {"historical": historical.get(key), "current": current.get(key)}
            for key in set(current) | set(historical)
            if current.get(key) != historical.get(key)
        },
        "promotion": (
            "NONE_DIAGNOSTIC_ONLY"
            if primary_reproduced and repeatable
            else "BLOCKED_CONTROL_REPRODUCTION_MISMATCH"
        ),
    }


def verify_trace_schema(trace, rows, factor):
    shapes = {}
    for branch in ("common", "interaction"):
        for stage in (
            "query_projection",
            "query_norm",
            "attention_query",
            "attention_output",
            "up",
        ):
            shapes[f"{branch}.{stage}"] = (rows, 1, 32)
        for stage in ("memory_normalized", "attention_memory"):
            shapes[f"{branch}.{stage}"] = (rows, 3, 32)
        for stage in ("projected_q", "sdpa_output"):
            shapes[f"{branch}.{stage}"] = (rows, 2, 1, 16)
        for stage in ("projected_k", "projected_v"):
            shapes[f"{branch}.{stage}"] = (rows, 2, 3, 16)
    shapes["interaction.centered_memory"] = (rows, 3, 32)
    if factor != "raw_ordered":
        shapes["interaction.offsets_gauge"] = (rows, 3, 32)
        for stage in ("anchor_gauge", "offset_sum_gauge", "offset_mean_gauge"):
            shapes[f"interaction.{stage}"] = (rows, 1, 32)
    for stage in (
        "common_query",
        "interaction_query",
        "common.delta_reconstructed",
        "interaction.bounded_reconstructed",
        "interaction.delta_reconstructed",
        "delta",
    ):
        shapes[stage] = (rows, 1, 32)
    shapes["interaction.remaining_fraction_reconstructed"] = (rows, 1, 1)
    shapes["native_logits"] = (rows, 7)
    require(set(trace) == set(shapes), "Incomplete or unexpected trace event population")
    for key, shape in shapes.items():
        require(
            isinstance(trace[key], torch.Tensor)
            and tuple(trace[key].shape) == shape
            and trace[key].dtype == torch.float32
            and bool(torch.isfinite(trace[key]).all()),
            "Trace tensor geometry/dtype/finiteness changed",
        )


def verify_cell_files(directory, name, saved):
    raw_path = audit.safe_file(directory, name + ".pt")
    require(audit.sha(raw_path) == saved["raw_sha256"], "Raw diagnostic artifact hash mismatch")
    payload = torch.load(raw_path, map_location="cpu", weights_only=True)
    require(set(payload) == {"raw", "traces"}, "Raw diagnostic schema")
    require(set(payload["traces"]) == {"original", "permuted"}, "Trace order population")
    factor = name.partition("_")[2]
    require(factor in PLAN["factors"], "Unknown saved-cell factor")
    for trace in payload["traces"].values():
        verify_trace_schema(trace, saved["rows"], factor)
    expected = {
        f"{order}_{repeat}_{kind}"
        for order in ("original", "permuted")
        for repeat in range(2)
        for kind in ("logits", "delta")
    }
    if saved["historical_original_logits"] is not None:
        expected.add("historical_original_logits")
    require(set(payload["raw"]) == expected, "Raw repeat population")
    for key, value in payload["raw"].items():
        shape = (saved["rows"], 7) if key.endswith("logits") else (saved["rows"], 1, 32)
        require(
            tuple(value.shape) == shape
            and value.dtype == torch.float32
            and bool(torch.isfinite(value).all()),
            "Raw diagnostic geometry/dtype/finiteness",
        )
    replayed = summarize_cell(
        payload["raw"],
        payload["traces"],
        saved["reobserved_controls"],
        saved["historical_controls"],
    )
    require(
        all(saved[key] == value for key, value in replayed.items()),
        "Raw diagnostic summary mismatch",
    )
    require(saved["hook_native_parity"], "Production hook parity missing")
    current = saved["reobserved_controls"]
    audit.verify_controls(current, factor, assay.load_plan())
    require(
        current["permutation_max_logit_error"]
        == float(
            (payload["raw"]["permuted_0_logits"] - payload["raw"]["original_0_logits"]).abs().max()
        ),
        "Control permutation scalar differs from raw logits",
    )
    require(
        current["same_memory_exact"] == replayed["same_input_repeats"]["original"]["exact"],
        "Control repeat scalar differs from raw logits",
    )
    require(
        current["max_delta_norm"] == float(payload["raw"]["original_0_delta"].norm(dim=-1).max()),
        "Control norm scalar differs from raw delta",
    )
    return replayed


def historical_logit_groups(bundle):
    groups = {f"{seed}_{factor}": [] for seed in PLAN["model_seeds"] for factor in PLAN["factors"]}
    with audit.safe_file(Path(bundle), "CASES.jsonl").open() as stream:
        for line in stream:
            row = audit.strict_json(line)
            if (
                row["factor"] == "common_only"
                or row["split"] != "held_out"
                or row["native_dtype"] != "torch.float32"
            ):
                continue
            key = f"{row['seed']}_{row['factor']}"
            require(
                key in groups and row["case"] == len(groups[key]), "Historical case order mismatch"
            )
            groups[key].append(row["logits"])
    require(
        all(len(rows) == PLAN["held_out_rows_per_fit"] for rows in groups.values()),
        "Historical logit denominator mismatch",
    )
    return {key: torch.tensor(rows, dtype=torch.float32) for key, rows in groups.items()}


def verify_caller_source(source, seal):
    require(set(source) == {"commit", "files", "aggregate_sha256"}, "Caller source schema")
    require(set(seal) == {"source_commit", "source_hashes"}, "Caller seal schema")
    require(source["commit"] == seal["source_commit"], "Caller seal commit mismatch")
    require(
        source["aggregate_sha256"] == assay.digest(source["files"]), "Caller source digest mismatch"
    )
    tracked = audit.git("ls-tree", "-r", "--name-only", source["commit"], "--", *audit.SOURCE_SCOPE)
    require(
        set(tracked.decode().splitlines()) == set(source["files"]), "Caller source scope mismatch"
    )
    all_tracked = set(
        audit.git("ls-tree", "-r", "--name-only", source["commit"]).decode().splitlines()
    )
    for name, expected in seal["source_hashes"].items():
        require(name in all_tracked, "Untracked caller source in seal")
        current = audit.sha(audit.safe_file(ROOT, name))
        committed = hashlib.sha256(audit.git("show", f"{source['commit']}:{name}")).hexdigest()
        require(current == committed == expected, "Caller sealed source bytes differ")
    require(
        all(seal["source_hashes"].get(name) == value for name, value in source["files"].items()),
        "Caller source seal incomplete",
    )
    require(
        ENTRY in source["files"] and "scripts/run_source_sealed.py" in source["files"],
        "Caller/launcher absent from source map",
    )


def verify_provenance(directory, bundle, source_seal, input_source_seal, result):
    source = audit.strict_json(audit.safe_file(directory, "SOURCE.json").read_text())
    seal = audit.strict_json(Path(source_seal).read_text())
    verify_caller_source(source, seal)
    preimport = audit.strict_json(audit.safe_file(directory, "PREIMPORT.json").read_text())
    require(
        preimport
        == {
            "schema": "pre-import-source-check-v1",
            "source_commit": source["commit"],
            "entry": ENTRY,
            "source_files": len(seal["source_hashes"]),
            "untracked_check": "all",
            "isolated_python": True,
            "fresh_bytecode_cache": True,
        },
        "Caller preimport identity mismatch",
    )
    started = audit.strict_json(audit.safe_file(directory, "STARTED.json").read_text())
    require(
        started["source_commit"] == source["commit"] == result["source_commit"]
        and started["source_sha256"] == source["aggregate_sha256"]
        and started["plan_sha256"] == assay.digest(PLAN)
        and started["external_seal_sha256"] == audit.sha(source_seal)
        and started["input_source_seal_sha256"] == audit.sha(input_source_seal)
        and started["offline_environment"] == OFFLINE_ENV,
        "Caller source/plan/offline/seal identity mismatch",
    )
    require(
        audit.strict_json(audit.safe_file(directory, "PLAN.json").read_text()) == PLAN,
        "Standalone plan differs",
    )
    previous_imports = {}
    for name in ("IMPORTS_BEFORE.json", "IMPORTS_AFTER.json"):
        imports = audit.strict_json(audit.safe_file(directory, name).read_text())
        require(
            type(imports) is dict
            and all(
                type(key) is str and value in source["files"] for key, value in imports.items()
            ),
            "Caller imports escaped sealed source",
        )
        require(
            {
                ENTRY,
                "scripts/assay_v18_operand_selection.py",
                "src/latent_workspace_ft_v10/v18_selection_reader.py",
                "src/latent_workspace_ft_v10/precision_bridge.py",
            }
            <= set(imports.values()),
            "Critical caller imports missing",
        )
        require(
            all(imports.get(key) == value for key, value in previous_imports.items()),
            "Caller imports changed during execution",
        )
        previous_imports = imports
    input_map = audit.strict_json(audit.safe_file(directory, "INPUT_HASHES.json").read_text())
    require(input_map == input_hashes(bundle), "Original input artifact fingerprints differ")
    original = audit.audit(bundle, input_source_seal)
    saved_audit = audit.strict_json(audit.safe_file(directory, "INPUT_AUDIT.json").read_text())
    require(
        set(original) == set(saved_audit)
        and all(original[key] == saved_audit[key] for key in original if key != "populations"),
        "Original input audit differs",
    )
    # Both observations obey the old, predeclared QR recipe bound. The scalar
    # error itself can differ when the offline verifier changes host/runtime.
    require(
        set(original["populations"]) == set(saved_audit["populations"]),
        "Original population audit split set differs",
    )
    for split, observation in original["populations"].items():
        saved_observation = saved_audit["populations"][split]
        require(
            set(observation) == set(saved_observation)
            and all(
                observation[key] == saved_observation[key]
                for key in observation
                if key != "recipe_identity_max_abs_error"
            )
            and 0 <= saved_observation["recipe_identity_max_abs_error"] <= audit.IDENTITY_ATOL,
            "Original population audit scope/count/recipe bound differs",
        )
    old_started = audit.strict_json(audit.safe_file(Path(bundle), "STARTED.json").read_text())
    require(
        started["device"] == result["device"] == old_started["device"]
        and started["python"] == old_started["python"]
        and started["torch"] == old_started["torch"],
        "Historical runtime identity mismatch",
    )
    require(
        result["input_commit"] == INPUT_COMMIT
        and result["input_hashes_unchanged"] is True
        and result["training_updates"] == 0
        and result["optimizer_instances"] == 0,
        "Diagnostic ownership/zero-learning claim mismatch",
    )


def verify(directory, bundle=None, source_seal=None, input_source_seal=None):
    directory = Path(directory)
    finished = audit.strict_json(audit.safe_file(directory, "FINISHED.json").read_text())
    require(
        finished["status"] == "COMPLETED" and not (directory / "FAILED.json").exists(),
        "Diagnostic is not complete",
    )
    actual = input_hashes(directory)
    actual.pop("FINISHED.json")
    require(actual == finished["artifact_hashes"], "Diagnostic terminal artifact inventory differs")
    result = audit.strict_json((directory / "RESULTS.json").read_text())
    require(
        result["plan"] == PLAN and result["old_gate"] == PLAN["old_gate"],
        "Diagnostic plan/gate changed",
    )
    expected = {f"{seed}_{factor}" for seed in PLAN["model_seeds"] for factor in PLAN["factors"]}
    require(set(result["cells"]) == expected, "Diagnostic cell denominator changed")
    require(
        all(value is not None for value in (bundle, source_seal, input_source_seal)),
        "Offline verification requires original input bundle and both source seals",
    )
    verify_provenance(directory, Path(bundle), source_seal, input_source_seal, result)
    historical = audit.strict_json(audit.safe_file(Path(bundle), "RESULTS.json").read_text())
    logits = historical_logit_groups(bundle)
    for name, saved in result["cells"].items():
        require(
            saved["rows"] == PLAN["held_out_rows_per_fit"], "Diagnostic row denominator changed"
        )
        verify_cell_files(directory, name, saved)
        require(
            saved == audit.strict_json(audit.safe_file(directory, name + ".json").read_text()),
            "Per-cell diagnostic summary differs",
        )
        seed, factor = name.split("_", 1)
        old = historical["results"][f"{seed}:{factor}"]
        require(
            saved["historical_controls"] == old["controls"]
            and saved["state_fingerprint"] == old["final_state_sha256"],
            "Historical controls/state identity differs",
        )
        raw = torch.load(directory / (name + ".pt"), map_location="cpu", weights_only=True)["raw"]
        require(
            torch.equal(raw["historical_original_logits"], logits[name]),
            "Historical original logits are not the sealed original rows",
        )
        require(
            saved["state_unchanged"] is True
            and saved["input_tensors_unchanged"] is True
            and saved["training_updates"] == 0
            and saved["optimizer_instances"] == 0
            and saved["forward_calls"] == 60,
            "Cell ownership/count claim mismatch",
        )
    for resources in (result["resources"], finished["resources"]):
        require(
            0 < resources["elapsed_seconds"] <= 900
            and 0 < resources["peak_rss_bytes"] <= 4 * 1024**3
            and 0 <= resources["peak_cuda_allocated_bytes"] <= 4 * 1024**3,
            "Recorded diagnostic resource bound exceeded",
        )
    return {
        "status": "OFFLINE_DIAGNOSTIC_RAW_REPLAY_PASS",
        "device": result["device"],
        "cells": len(expected),
        "forward_calls": 0,
        "training_updates": 0,
        "old_gate": PLAN["old_gate"],
    }


def configure_runtime(device):
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.set_float32_matmul_precision("highest")
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    if device == "cuda":
        require(torch.cuda.is_available(), "CUDA unavailable")
        clients = subprocess.check_output(
            ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
            text=True,
        )
        require(
            not any(
                line.strip() and line.strip() != str(os.getpid()) for line in clients.splitlines()
            ),
            "GPU has another compute client; no automatic retry",
        )
        total = torch.cuda.get_device_properties(0).total_memory
        torch.cuda.set_per_process_memory_fraction(min(1, PLAN["resources"]["peak_bytes"] / total))
        torch.cuda.reset_peak_memory_stats()


def run(output, bundle, device, expected_commit, source_seal, input_source_seal):
    output, bundle = Path(output), Path(bundle)
    require(device in ("cpu", "cuda"), "Only the original CPU/CUDA runtimes are admitted")
    seal, preimport = sealed_guard(source_seal)
    external_seal_hash = audit.sha(source_seal)
    input_seal_hash = audit.sha(input_source_seal)
    source = assay.source_receipt(expected_commit)
    require(
        all(seal["source_hashes"].get(key) == value for key, value in source["files"].items()),
        "Caller source seal does not cover complete source",
    )
    require(
        not output.resolve().is_relative_to(ROOT)
        and not output.resolve().is_relative_to(bundle.resolve()),
        "Output must be outside source and original bundle",
    )
    require(
        all(os.environ.get(key) == value for key, value in OFFLINE_ENV.items()),
        "Offline flags absent",
    )
    output.mkdir(parents=True, exist_ok=False)
    guard = assay.ResourceGuard(PLAN, device)
    previous = signal.getsignal(signal.SIGALRM)

    def timeout(_signum, _frame):
        raise TimeoutError("Frozen diagnostic wall-clock alarm expired")

    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(PLAN["resources"]["wall_seconds"])
    try:
        assay.write_json(output / "PLAN.json", PLAN)
        assay.write_json(output / "SOURCE.json", source)
        assay.write_json(output / "PREIMPORT.json", preimport)
        assay.write_json(
            output / "STARTED.json",
            {
                "pid": os.getpid(),
                "device": device,
                "source_commit": expected_commit,
                "source_sha256": source["aggregate_sha256"],
                "plan_sha256": assay.digest(PLAN),
                "python": platform.python_version(),
                "torch": torch.__version__,
                "hostname": platform.node(),
                "external_seal_sha256": external_seal_hash,
                "input_source_seal_sha256": input_seal_hash,
                "offline_environment": OFFLINE_ENV,
            },
        )
        configure_runtime(device)
        guard()
        inputs_before = input_hashes(bundle)
        assay.write_json(output / "INPUT_HASHES.json", inputs_before)
        audit_result = audit.audit(bundle, input_source_seal)
        assay.write_json(output / "INPUT_AUDIT.json", audit_result)
        historical = audit.strict_json((bundle / "RESULTS.json").read_text())
        historical_logits = historical_logit_groups(bundle)
        started = audit.strict_json((bundle / "STARTED.json").read_text())
        require(
            started["device"] == device and historical["device"] == device,
            "Saved runtime device mismatch",
        )
        require(
            started["python"] == platform.python_version()
            and started["torch"] == torch.__version__,
            "Saved Python/Torch runtime version mismatch",
        )
        require(audit_result["source_commit"] == INPUT_COMMIT, "Unexpected historical source")
        payload = torch.load(bundle / "POPULATIONS.pt", map_location="cpu", weights_only=True)[
            "held_out"
        ]
        pop = population_from_saved(payload)
        require(
            len(pop.inputs.states) == PLAN["held_out_rows_per_fit"], "Held-out denominator changed"
        )
        save_tensor(
            output / "CONTROL_INPUTS.pt",
            {
                "states": pop.inputs.states,
                "memory": pop.inputs.memory,
                "mask": pop.inputs.mask,
                "permutation": torch.tensor(PLAN["slot_permutation"]),
                "rows": payload["rows"],
            },
        )
        assay.write_json(output / "IMPORTS_BEFORE.json", assay.imported_sources(seal))
        cells = {}
        for seed in PLAN["model_seeds"]:
            for factor in PLAN["factors"]:
                guard()
                name, key = f"{seed}_{factor}", f"{seed}:{factor}"
                state = torch.load(
                    audit.safe_file(bundle, historical["results"][key]["state_file"]),
                    map_location="cpu",
                    weights_only=True,
                )
                bridge = assay.make_reader(seed, factor, device)
                bridge.load_state_dict(state, strict=True)
                bridge.eval()
                bridge.requires_grad_(False)
                require(
                    assay.state_fingerprint(bridge)
                    == historical["results"][key]["final_state_sha256"],
                    "Loaded state differs from historical fit",
                )
                raw, summary = diagnose_cell(
                    bridge,
                    pop,
                    factor,
                    device,
                    guard,
                    historical["results"][key]["controls"],
                    historical_logits[name],
                )
                raw_path = output / (name + ".pt")
                save_tensor(raw_path, raw)
                summary["raw_sha256"] = audit.sha(raw_path)
                assay.write_json(output / (name + ".json"), summary)
                verify_cell_files(output, name, summary)
                cells[name] = summary
                del bridge, state, raw
                guard()
        require(
            input_hashes(bundle) == inputs_before,
            "Historical input artifacts changed during diagnosis",
        )
        require(
            assay.source_receipt(expected_commit) == source,
            "Caller source changed during diagnosis",
        )
        require(
            audit.sha(source_seal) == external_seal_hash
            and audit.sha(input_source_seal) == input_seal_hash,
            "External source seal files changed during diagnosis",
        )
        sealed_guard(source_seal)
        assay.write_json(output / "IMPORTS_AFTER.json", assay.imported_sources(seal))
        result = {
            "schema": "v18-saved-selection-permutation-result-v1",
            "device": device,
            "plan": PLAN,
            "source_commit": expected_commit,
            "input_commit": INPUT_COMMIT,
            "input_hashes_unchanged": True,
            "cells": cells,
            "training_updates": 0,
            "optimizer_instances": 0,
            "resources": guard.snapshot(),
            "old_gate": PLAN["old_gate"],
            "claim_ceiling": (
                "Saved toy-state numerical localization only; no fit or scientific promotion"
            ),
        }
        guard()
        assay.write_json(output / "RESULTS.json", result)
        assay.write_json(
            output / "FINISHED.json",
            {
                "status": "COMPLETED",
                "resources": guard.snapshot(),
                "artifact_hashes": input_hashes(output),
            },
        )
        return result
    except BaseException as error:
        assay.write_json(
            output / "FAILED.json",
            {
                "type": type(error).__name__,
                "error": str(error),
                "traceback": traceback.format_exc(),
                "resources": guard.snapshot(),
            },
        )
        if not (output / "FINISHED.json").exists():
            assay.write_json(
                output / "FINISHED.json", {"status": "FAILED", "resources": guard.snapshot()}
            )
        raise
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--execute", action="store_true")
    modes.add_argument("--verify", action="store_true")
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda"))
    parser.add_argument("--source-commit")
    parser.add_argument("--source-seal", type=Path)
    parser.add_argument("--input-source-seal", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.execute:
        if any(
            getattr(args, key) is None
            for key in (
                "bundle",
                "device",
                "source_commit",
                "source_seal",
                "input_source_seal",
                "output",
            )
        ):
            parser.error(
                "Execute requires bundle, device, source commit, both seals, and exclusive output"
            )
        result = run(
            args.output,
            args.bundle,
            args.device,
            args.source_commit,
            args.source_seal,
            args.input_source_seal,
        )
        print(
            json.dumps(
                {
                    "status": "COMPLETED",
                    "cells": len(result["cells"]),
                    "old_gate": PLAN["old_gate"],
                },
                sort_keys=True,
            )
        )
    elif args.verify:
        if any(
            value is None
            for value in (args.output, args.bundle, args.source_seal, args.input_source_seal)
        ):
            parser.error("Verify requires output, original bundle, and both source seals")
        print(
            json.dumps(
                verify(args.output, args.bundle, args.source_seal, args.input_source_seal),
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(
            json.dumps(
                {"status": "DRY_RUN_NO_FORWARDS", "plan": PLAN, "plan_sha256": assay.digest(PLAN)},
                indent=2,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
