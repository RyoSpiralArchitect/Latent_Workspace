#!/usr/bin/env python3
"""Separate, bounded requires-grad flag intervention on retained V18 states.

This is not a retry or repair of either completed study. All calls remain eval
and no_grad. A single loaded reader/storage is reused in an ABBA flag sequence;
there is no optimization, writer call, backward, precision change or new data.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import signal
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "scripts/diagnose_v18_replay_flags.py"
ORIGINAL_COMMIT = "dd10b20a8fbb0e32e5ac89bcec939802e6940f8b"
PRIOR_COMMIT = "57af47858088d67247cbb5c3f77c4724a16db624"
INTERACTION_NAMES = {
    "query_projection.weight",
    "query_norm.weight",
    "query_norm.bias",
    "attention.in_proj_weight",
    "attention.out_proj.weight",
    "up.weight",
}
POLICIES = ("historical_interaction_trainable", "all_frozen")
PLAN = {
    "schema": "v18-saved-reader-flag-intervention-plan-v1",
    "original_commit": ORIGINAL_COMMIT,
    "prior_diagnostic_commit": PRIOR_COMMIT,
    "model_seeds": [17, 29, 43],
    "factors": ["centered_final", "centered_ordered", "centered_symmetric", "raw_ordered"],
    "policies": list(POLICIES),
    "policy_visit_order": [POLICIES[0], POLICIES[1], POLICIES[1], POLICIES[0]],
    "storage_policy": "same reader and parameter storage reused across all four visits",
    "fits_per_device": 12,
    "policy_cells_per_device": 24,
    "held_out_rows_per_fit": 1152,
    "chunk_size": 256,
    "slot_permutation": [2, 0, 1],
    "repetitions_per_policy_order": 2,
    "native_dtype": "torch.float32",
    "reader_mode": "eval",
    "autograd": "no_grad",
    "parameter_entries": 32,
    "historical_trainable_entries": 6,
    "common_frozen_entries": 26,
    "gradient_buffers": (
        "fresh reconstruction: absent under both policies; historical buffers unarchived"
    ),
    "control_atol": 1e-6,
    "resources": {"wall_seconds": 900, "peak_bytes": 4 * 1024**3, "cpu_threads": 2},
    "training_updates": 0,
    "optimizer_instances": 0,
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


def verify_ancestor_seals(guard, caller_seal, original_seal, prior_seal):
    """Stdlib-only checks before any project or third-party execution import."""
    for seal_path, expected_commit in (
        (original_seal, ORIGINAL_COMMIT),
        (prior_seal, PRIOR_COMMIT),
    ):
        if seal_path is None:
            raise ValueError("Both historical source seals are required before imports")
        ancestor = json.loads(Path(seal_path).read_text())
        if (
            set(ancestor) != {"source_commit", "source_hashes"}
            or ancestor["source_commit"] != expected_commit
            or not isinstance(ancestor["source_hashes"], dict)
            or not ancestor["source_hashes"]
        ):
            raise ValueError("Historical preimport seal identity differs")
        for name, expected in ancestor["source_hashes"].items():
            path = guard.safe_source(ROOT, name)
            if (
                caller_seal["source_hashes"].get(name) != expected
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected
            ):
                raise ValueError("Historical preimport source bytes differ")


def sealed_guard(seal_path, original_seal=None, prior_seal=None):
    if not sys.flags.isolated or not sys.dont_write_bytecode or not sys.pycache_prefix:
        raise ValueError("Use isolated run_source_sealed.py with fresh bytecode cache")
    cache = Path(sys.pycache_prefix)
    if (
        not cache.is_absolute()
        or not cache.is_dir()
        or cache.is_symlink()
        or cache.resolve().is_relative_to(ROOT)
        or any(cache.iterdir())
    ):
        raise ValueError("Fresh empty bytecode cache outside source required")
    spec = importlib.util.spec_from_file_location(
        "flag_source_guard", ROOT / "scripts/run_source_sealed.py"
    )
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    seal = json.loads(Path(seal_path).read_text())
    receipt = guard.verify(ROOT, seal, ENTRY)
    verify_ancestor_seals(guard, seal, original_seal, prior_seal)
    return seal, receipt


if __name__ == "__main__" and "--execute" in sys.argv:
    bootstrap = argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument("--source-seal", type=Path, required=True)
    bootstrap.add_argument("--original-source-seal", type=Path, required=True)
    bootstrap.add_argument("--prior-source-seal", type=Path, required=True)
    boot, _ = bootstrap.parse_known_args()
    sealed_guard(boot.source_seal, boot.original_source_seal, boot.prior_source_seal)
    os.environ.update(OFFLINE_ENV)

import torch  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
import assay_v18_operand_selection as assay  # noqa: E402
import audit_v18_operand_selection_terminal as audit  # noqa: E402
import diagnose_v18_selection_permutation as prior  # noqa: E402

require = prior.require


def parameter_metadata(bridge):
    result = {}
    for name, parameter in bridge.named_parameters():
        result[name] = {
            "shape": list(parameter.shape),
            "stride": list(parameter.stride()),
            "storage_offset": parameter.storage_offset(),
            "contiguous": parameter.is_contiguous(),
            "dtype": str(parameter.dtype),
            "device": str(parameter.device),
            "requires_grad": parameter.requires_grad,
            "gradient_present": parameter.grad is not None,
            "is_leaf": parameter.is_leaf,
            "storage_pointer": parameter.untyped_storage().data_ptr(),
            "storage_bytes": parameter.untyped_storage().nbytes(),
        }
    return result


def apply_policy(bridge, policy):
    require(type(bridge) is assay.SelectionWorkspaceBridge, "Exact saved reader class required")
    require(policy in POLICIES, "Unknown parameter flag policy")
    names = set(dict(bridge.named_parameters()))
    require(
        len(names) == 32
        and {name for name in names if not name.startswith("common.")} == INTERACTION_NAMES,
        "Saved parameter ownership population changed",
    )
    for name, parameter in bridge.named_parameters():
        parameter.requires_grad_(policy == POLICIES[0] and name in INTERACTION_NAMES)
    bridge.eval()
    return parameter_metadata(bridge)


def check_metadata(metadata, policy, reference=None):
    require(
        len(metadata) == 32
        and {name for name in metadata if not name.startswith("common.")} == INTERACTION_NAMES,
        "Parameter metadata population changed",
    )
    for name, item in metadata.items():
        require(
            set(item)
            == {
                "shape",
                "stride",
                "storage_offset",
                "contiguous",
                "dtype",
                "device",
                "requires_grad",
                "gradient_present",
                "is_leaf",
                "storage_pointer",
                "storage_bytes",
            },
            "Parameter metadata schema",
        )
        require(
            type(item["requires_grad"]) is bool
            and item["requires_grad"] == (policy == POLICIES[0] and name in INTERACTION_NAMES),
            "Policy flags differ",
        )
        require(
            item["gradient_present"] is False
            and item["is_leaf"] is True
            and item["dtype"] == "torch.float32",
            "Unexpected parameter gradient/dtype state",
        )
        if reference is not None:
            require(
                all(item[key] == reference[name][key] for key in item if key != "requires_grad"),
                "Parameter storage/layout changed during flag intervention",
            )


def input_references(original_bundle, prior_bundle):
    historical = prior.historical_logit_groups(original_bundle)
    result = {}
    for name, logits in historical.items():
        saved = torch.load(
            audit.safe_file(Path(prior_bundle), name + ".pt"), map_location="cpu", weights_only=True
        )["raw"]
        result[name] = {
            "historical_logits": logits,
            **{
                "prior_" + key: saved[key]
                for key in (
                    "original_0_logits",
                    "original_0_delta",
                    "permuted_0_logits",
                    "permuted_0_delta",
                )
            },
        }
    return result


def summary(raw, controls, references, historical_controls, prior_controls):
    policy_results = {}
    for policy in POLICIES:
        rows = raw[policy]
        repeat = {
            order + "_" + kind: prior.tensor_summary(
                rows[f"{order}_0_{kind}"], rows[f"{order}_1_{kind}"]
            )
            for order in ("original", "permuted")
            for kind in ("logits", "delta")
        }
        historical = prior.tensor_summary(
            rows["original_0_logits"], references["historical_logits"]
        )
        previous = {
            key: prior.tensor_summary(rows[key], references["prior_" + key])
            for key in (
                "original_0_logits",
                "original_0_delta",
                "permuted_0_logits",
                "permuted_0_delta",
            )
        }
        permutation = prior.tensor_summary(rows["original_0_logits"], rows["permuted_0_logits"])
        policy_results[policy] = {
            "repeats": repeat,
            "historical_original_logits": historical,
            "prior_outputs": previous,
            "native_permutation": permutation,
            "native_permutation_pass": permutation["max_abs_error"] <= PLAN["control_atol"],
            "reobserved_controls": controls[policy],
            "historical_controls": historical_controls,
            "prior_controls": prior_controls,
            "historical_control_reproduction_exact": controls[policy] == historical_controls,
            "prior_control_reproduction_exact": controls[policy] == prior_controls,
            "historical_prediction_disagreements": int(
                rows["original_0_logits"]
                .argmax(-1)
                .ne(references["historical_logits"].argmax(-1))
                .sum()
            ),
            "prior_prediction_disagreements": int(
                rows["original_0_logits"]
                .argmax(-1)
                .ne(references["prior_original_0_logits"].argmax(-1))
                .sum()
            ),
        }
    contrast = {
        key: prior.tensor_summary(raw[POLICIES[0]][key], raw[POLICIES[1]][key])
        for key in (
            "original_0_logits",
            "original_0_delta",
            "permuted_0_logits",
            "permuted_0_delta",
        )
    }
    repeatable = all(
        row["exact"] for item in policy_results.values() for row in item["repeats"].values()
    )
    unchanged = all(row["exact"] for row in contrast.values())
    outcome = (
        "UNRESOLVED_REPEATABILITY"
        if not repeatable
        else "NO_FLAG_EFFECT_IN_THIS_DIAGNOSTIC"
        if unchanged
        else "POLICY_DEPENDENT_OUTPUT_WITH_REPEATABILITY"
    )
    return {
        "policies": policy_results,
        "cross_policy": contrast,
        "outcome": outcome,
        "promotion": "NONE_DIAGNOSTIC_ONLY",
        "old_gate": PLAN["old_gate"],
    }


@torch.no_grad()
def diagnose_fit(
    bridge, pop, factor, device, guard, references, historical_controls, prior_controls
):
    before = assay.state_fingerprint(bridge)
    data = pop.inputs
    tensor_before = {
        key: assay.tensor_fingerprint(getattr(data, key)) for key in ("states", "memory", "mask")
    }
    permutation = PLAN["slot_permutation"]
    permuted = assay.Inputs(data.states, data.memory[:, permutation], data.mask[:, permutation])
    raw, visits, metadata = {policy: {} for policy in POLICIES}, [], None
    counts = dict.fromkeys(POLICIES, 0)
    for visit, policy in enumerate(PLAN["policy_visit_order"]):
        current = apply_policy(bridge, policy)
        check_metadata(current, policy, metadata)
        metadata = current
        require(
            not torch.is_grad_enabled() and not any(m.training for m in bridge.modules()),
            "Every flag visit must remain eval/no_grad",
        )
        repetition = counts[policy]
        for name, inputs in (("original", data), ("permuted", permuted)):
            logits, delta = assay.measured(bridge, inputs, factor, device, torch.float32, guard)
            raw[policy][f"{name}_{repetition}_logits"] = logits
            raw[policy][f"{name}_{repetition}_delta"] = delta
        require(before == assay.state_fingerprint(bridge), "Parameter values changed during visit")
        require(parameter_metadata(bridge) == current, "Parameter metadata changed during visit")
        visits.append(
            {
                "visit": visit,
                "policy": policy,
                "repetition": repetition,
                "metadata": current,
                "state_fingerprint": before,
                "grad_enabled": False,
                "all_eval": True,
            }
        )
        counts[policy] += 1
    controls, control_metadata = {}, {}
    for policy in POLICIES:
        current = apply_policy(bridge, policy)
        check_metadata(current, policy, metadata)
        controls[policy] = assay.controls(bridge, factor, pop, device, guard, PLAN["control_atol"])
        control_metadata[policy] = current
        require(before == assay.state_fingerprint(bridge), "Control changed parameter values")
        require(parameter_metadata(bridge) == current, "Control changed parameter metadata")
    require(
        tensor_before
        == {key: assay.tensor_fingerprint(getattr(data, key)) for key in tensor_before},
        "Intervention mutated population tensors",
    )
    result = summary(raw, controls, references, historical_controls, prior_controls)
    result.update(
        {
            "rows": len(data.states),
            "state_fingerprint": before,
            "visits": visits,
            "control_metadata": control_metadata,
            "input_tensors_unchanged": True,
            "state_values_unchanged": True,
            "training_updates": 0,
            "optimizer_instances": 0,
            "forward_calls": 20 * ((len(data.states) + 255) // 256),
        }
    )
    return raw, result


def verify_fit(raw, saved, references, factor):
    require(
        set(raw) == set(POLICIES) and set(saved["policies"]) == set(POLICIES),
        "Policy population mismatch",
    )
    keys = {
        f"{order}_{rep}_{kind}"
        for order in ("original", "permuted")
        for rep in range(2)
        for kind in ("logits", "delta")
    }
    for policy, tensors in raw.items():
        require(set(tensors) == keys, "Raw flag repeat population mismatch")
        for key, value in tensors.items():
            shape = (saved["rows"], 7) if key.endswith("logits") else (saved["rows"], 1, 32)
            require(
                value.dtype == torch.float32
                and tuple(value.shape) == shape
                and bool(torch.isfinite(value).all()),
                "Raw flag geometry/finiteness mismatch",
            )
        control = saved["policies"][policy]["reobserved_controls"]
        audit.verify_controls(control, factor, assay.load_plan())
        require(
            control["permutation_max_logit_error"]
            == float((tensors["original_0_logits"] - tensors["permuted_0_logits"]).abs().max())
            and control["same_memory_exact"]
            == torch.equal(tensors["original_0_logits"], tensors["original_1_logits"])
            and control["max_delta_norm"] == float(tensors["original_0_delta"].norm(dim=-1).max()),
            "Reobserved controls disagree with raw flag outputs",
        )
    require(len(saved["visits"]) == 4, "Flag visit denominator changed")
    counts, reference = dict.fromkeys(POLICIES, 0), None
    for index, visit in enumerate(saved["visits"]):
        policy = PLAN["policy_visit_order"][index]
        require(
            visit["visit"] == index
            and visit["policy"] == policy
            and visit["repetition"] == counts[policy]
            and visit["grad_enabled"] is False
            and visit["all_eval"] is True
            and visit["state_fingerprint"] == saved["state_fingerprint"],
            "Flag visit identity changed",
        )
        check_metadata(visit["metadata"], policy, reference)
        reference = visit["metadata"]
        counts[policy] += 1
    for policy in POLICIES:
        check_metadata(saved["control_metadata"][policy], policy, reference)
    first = saved["policies"][POLICIES[0]]
    require(
        all(
            saved["policies"][p][k] == first[k]
            for p in POLICIES
            for k in ("historical_controls", "prior_controls")
        ),
        "Reference controls changed by policy",
    )
    replayed = summary(
        raw,
        {p: saved["policies"][p]["reobserved_controls"] for p in POLICIES},
        references,
        first["historical_controls"],
        first["prior_controls"],
    )
    require(all(saved[key] == value for key, value in replayed.items()), "Raw flag summary differs")
    require(
        saved["state_values_unchanged"] is True
        and saved["input_tensors_unchanged"] is True
        and saved["training_updates"] == saved["optimizer_instances"] == 0
        and saved["forward_calls"] == 20 * ((saved["rows"] + 255) // 256),
        "Zero-learning/ownership/count claim differs",
    )
    return replayed


def read_json(directory, name):
    return audit.strict_json(audit.safe_file(Path(directory), name).read_text())


def verify(
    directory, original_bundle, prior_bundle, source_seal, original_source_seal, prior_source_seal
):
    directory = Path(directory)
    terminal = read_json(directory, "FINISHED.json")
    require(
        terminal["status"] == "COMPLETED" and not (directory / "FAILED.json").exists(),
        "Flag diagnostic did not complete",
    )
    files = prior.input_hashes(directory)
    files.pop("FINISHED.json")
    require(files == terminal["artifact_hashes"], "Flag terminal artifact inventory changed")
    result, started, source = (
        read_json(directory, name) for name in ("RESULTS.json", "STARTED.json", "SOURCE.json")
    )
    seal = audit.strict_json(Path(source_seal).read_text())
    prior.verify_caller_source(source, seal)
    require(
        ENTRY in source["files"]
        and read_json(directory, "PLAN.json") == PLAN
        and result["plan"] == PLAN,
        "Flag source/plan missing or changed",
    )
    require(
        read_json(directory, "PREIMPORT.json")
        == {
            "schema": "pre-import-source-check-v1",
            "source_commit": source["commit"],
            "entry": ENTRY,
            "source_files": len(seal["source_hashes"]),
            "untracked_check": "all",
            "isolated_python": True,
            "fresh_bytecode_cache": True,
        },
        "Flag preimport receipt changed",
    )
    seals = {"source": source_seal, "original": original_source_seal, "prior": prior_source_seal}
    require(
        started["seal_hashes"] == {name: audit.sha(path) for name, path in seals.items()}
        and started["source_commit"] == result["source_commit"] == source["commit"]
        and started["source_sha256"] == source["aggregate_sha256"]
        and started["plan_sha256"] == assay.digest(PLAN)
        and started["offline_environment"] == OFFLINE_ENV,
        "Flag source/seal/runtime identity changed",
    )
    expected_inputs = {
        "original": prior.input_hashes(original_bundle),
        "prior": prior.input_hashes(prior_bundle),
    }
    require(
        read_json(directory, "INPUT_HASHES.json") == expected_inputs,
        "Historical input artifacts changed",
    )
    input_audit = prior.verify(
        prior_bundle, original_bundle, prior_source_seal, original_source_seal
    )
    require(
        input_audit == read_json(directory, "PRIOR_AUDIT.json"), "Prior diagnostic audit differs"
    )
    prior_result, original_result = (
        read_json(prior_bundle, "RESULTS.json"),
        read_json(original_bundle, "RESULTS.json"),
    )
    require(prior_result["source_commit"] == PRIOR_COMMIT, "Unexpected prior diagnostic commit")
    for bundle in (original_bundle, prior_bundle):
        old = read_json(bundle, "STARTED.json")
        require(
            started["device"] == old["device"] == result["device"]
            and started["python"] == old["python"]
            and started["torch"] == old["torch"],
            "Historical runtime identity mismatch",
        )
    previous = {}
    for filename in ("IMPORTS_BEFORE.json", "IMPORTS_AFTER.json"):
        imports = read_json(directory, filename)
        require(
            all(value in source["files"] for value in imports.values())
            and {
                ENTRY,
                prior.ENTRY,
                "scripts/assay_v18_operand_selection.py",
                "src/latent_workspace_ft_v10/v18_selection_reader.py",
            }
            <= set(imports.values())
            and all(imports.get(key) == value for key, value in previous.items()),
            "Flag import closure mismatch",
        )
        previous = imports
    references = torch.load(
        audit.safe_file(directory, "REFERENCES.pt"), map_location="cpu", weights_only=True
    )
    expected = input_references(original_bundle, prior_bundle)
    require(
        set(references) == set(expected) == set(result["fits"]),
        "Flag fit/reference denominator changed",
    )
    for name, ref in references.items():
        require(
            set(ref) == set(expected[name])
            and all(torch.equal(value, expected[name][key]) for key, value in ref.items()),
            "Raw reference tensors differ from sealed prior artifacts",
        )
        saved = result["fits"][name]
        require(
            saved == read_json(directory, name + ".json") and saved["rows"] == 1152,
            "Flag per-fit receipt or denominator differs",
        )
        path = audit.safe_file(directory, name + ".pt")
        require(audit.sha(path) == saved["raw_sha256"], "Flag raw artifact hash mismatch")
        seed, factor = name.split("_", 1)
        old = original_result["results"][f"{seed}:{factor}"]
        require(
            saved["state_fingerprint"] == old["final_state_sha256"]
            and saved["policies"][POLICIES[0]]["historical_controls"] == old["controls"]
            and saved["policies"][POLICIES[0]]["prior_controls"]
            == prior_result["cells"][name]["reobserved_controls"],
            "Historical state/control references differ",
        )
        original_state = torch.load(
            audit.safe_file(Path(original_bundle), old["state_file"]),
            map_location="cpu",
            weights_only=True,
        )
        metadata = saved["visits"][0]["metadata"]
        require(set(metadata) == set(original_state), "Saved parameter layout population differs")
        for parameter, tensor in original_state.items():
            item = metadata[parameter]
            require(
                item["shape"] == list(tensor.shape)
                and item["stride"] == list(tensor.stride())
                and item["storage_offset"] == tensor.storage_offset()
                and item["contiguous"] == tensor.is_contiguous()
                and item["dtype"] == str(tensor.dtype)
                and item["storage_bytes"] == tensor.untyped_storage().nbytes(),
                "Observed parameter layout differs from saved state",
            )
        raw = torch.load(path, map_location="cpu", weights_only=True)
        verify_fit(raw, saved, ref, factor)
    require(
        result["old_gate"] == PLAN["old_gate"]
        and result["training_updates"] == result["optimizer_instances"] == 0
        and result["input_hashes_unchanged"] is True,
        "Scientific gate/zero-learning claim changed",
    )
    for usage in (result["resources"], terminal["resources"]):
        require(
            0 < usage["elapsed_seconds"] <= 900
            and 0 < usage["peak_rss_bytes"] <= 4 * 1024**3
            and 0 <= usage["peak_cuda_allocated_bytes"] <= 4 * 1024**3,
            "Resource bound exceeded",
        )
    return {
        "status": "OFFLINE_FLAG_INTERVENTION_REPLAY_PASS",
        "device": result["device"],
        "fits": len(result["fits"]),
        "policy_cells": len(result["fits"]) * 2,
        "forward_calls": 0,
        "training_updates": 0,
        "old_gate": PLAN["old_gate"],
    }


def run(
    output,
    original_bundle,
    prior_bundle,
    device,
    expected_commit,
    source_seal,
    original_source_seal,
    prior_source_seal,
):
    output = Path(output)
    seal, preimport = sealed_guard(source_seal, original_source_seal, prior_source_seal)
    source = assay.source_receipt(expected_commit)
    require(
        all(seal["source_hashes"].get(key) == value for key, value in source["files"].items()),
        "Flag source seal incomplete",
    )
    require(
        device in ("cpu", "cuda")
        and not any(
            output.resolve().is_relative_to(Path(path).resolve())
            for path in (ROOT, original_bundle, prior_bundle)
        ),
        "Invalid device/output location",
    )
    require(
        all(os.environ.get(key) == value for key, value in OFFLINE_ENV.items()),
        "Offline flags absent",
    )
    seals = {"source": source_seal, "original": original_source_seal, "prior": prior_source_seal}
    seal_hashes = {name: audit.sha(path) for name, path in seals.items()}
    output.mkdir(parents=True, exist_ok=False)
    guard = assay.ResourceGuard(PLAN, device)
    previous = signal.getsignal(signal.SIGALRM)

    def timeout(_signum, _frame):
        raise TimeoutError("Frozen flag diagnostic wall-clock alarm expired")

    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(900)
    try:
        for filename, value in (
            ("PLAN.json", PLAN),
            ("SOURCE.json", source),
            ("PREIMPORT.json", preimport),
        ):
            assay.write_json(output / filename, value)
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
                "seal_hashes": seal_hashes,
                "offline_environment": OFFLINE_ENV,
            },
        )
        prior.configure_runtime(device)
        guard()
        inputs_before = {
            "original": prior.input_hashes(original_bundle),
            "prior": prior.input_hashes(prior_bundle),
        }
        assay.write_json(output / "INPUT_HASHES.json", inputs_before)
        verification = prior.verify(
            prior_bundle, original_bundle, prior_source_seal, original_source_seal
        )
        assay.write_json(output / "PRIOR_AUDIT.json", verification)
        historical, old_diagnostic = (
            read_json(original_bundle, "RESULTS.json"),
            read_json(prior_bundle, "RESULTS.json"),
        )
        require(old_diagnostic["source_commit"] == PRIOR_COMMIT, "Unexpected prior source")
        for bundle in (original_bundle, prior_bundle):
            started = read_json(bundle, "STARTED.json")
            require(
                started["device"] == device
                and started["python"] == platform.python_version()
                and started["torch"] == torch.__version__,
                "Saved runtime identity mismatch",
            )
        references = input_references(original_bundle, prior_bundle)
        prior.save_tensor(output / "REFERENCES.pt", references)
        payload = torch.load(
            audit.safe_file(Path(original_bundle), "POPULATIONS.pt"),
            map_location="cpu",
            weights_only=True,
        )["held_out"]
        pop = prior.population_from_saved(payload)
        require(len(pop.inputs.states) == 1152, "Held-out denominator changed")
        assay.write_json(output / "IMPORTS_BEFORE.json", assay.imported_sources(seal))
        fits = {}
        for seed in PLAN["model_seeds"]:
            for factor in PLAN["factors"]:
                guard()
                name, key = f"{seed}_{factor}", f"{seed}:{factor}"
                saved = historical["results"][key]
                state = torch.load(
                    audit.safe_file(Path(original_bundle), saved["state_file"]),
                    map_location="cpu",
                    weights_only=True,
                )
                bridge = assay.make_reader(seed, factor, device)
                bridge.load_state_dict(state, strict=True)
                require(
                    assay.state_fingerprint(bridge) == saved["final_state_sha256"],
                    "Loaded state differs",
                )
                raw, fit = diagnose_fit(
                    bridge,
                    pop,
                    factor,
                    device,
                    guard,
                    references[name],
                    saved["controls"],
                    old_diagnostic["cells"][name]["reobserved_controls"],
                )
                raw_path = output / (name + ".pt")
                prior.save_tensor(raw_path, raw)
                fit["raw_sha256"] = audit.sha(raw_path)
                assay.write_json(output / (name + ".json"), fit)
                # Preserve observed bytes even if strict replay rejects the cell.
                verify_fit(raw, fit, references[name], factor)
                fits[name] = fit
                del bridge, state, raw
                guard()
        require(
            inputs_before
            == {
                "original": prior.input_hashes(original_bundle),
                "prior": prior.input_hashes(prior_bundle),
            },
            "Historical artifacts changed during flag intervention",
        )
        require(
            seal_hashes == {name: audit.sha(path) for name, path in seals.items()},
            "External seals changed",
        )
        require(assay.source_receipt(expected_commit) == source, "Flag execution source changed")
        sealed_guard(source_seal, original_source_seal, prior_source_seal)
        assay.write_json(output / "IMPORTS_AFTER.json", assay.imported_sources(seal))
        result = {
            "schema": "v18-saved-reader-flag-intervention-result-v1",
            "device": device,
            "source_commit": expected_commit,
            "plan": PLAN,
            "fits": fits,
            "input_hashes_unchanged": True,
            "training_updates": 0,
            "optimizer_instances": 0,
            "resources": guard.snapshot(),
            "old_gate": PLAN["old_gate"],
            "claim_ceiling": (
                "Only the specified flag intervention; no historical repair or learner promotion"
            ),
        }
        guard()
        assay.write_json(output / "RESULTS.json", result)
        assay.write_json(
            output / "FINISHED.json",
            {
                "status": "COMPLETED",
                "resources": guard.snapshot(),
                "artifact_hashes": prior.input_hashes(output),
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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--verify", action="store_true")
    for name in (
        "output",
        "original-bundle",
        "prior-bundle",
        "source-seal",
        "original-source-seal",
        "prior-source-seal",
    ):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda"))
    parser.add_argument("--source-commit")
    args = parser.parse_args()
    if not (args.execute or args.verify):
        print(
            json.dumps(
                {"status": "DRY_RUN_NO_FORWARDS", "plan": PLAN, "plan_sha256": assay.digest(PLAN)},
                indent=2,
                sort_keys=True,
            )
        )
        return
    paths = (
        args.output,
        args.original_bundle,
        args.prior_bundle,
        args.source_seal,
        args.original_source_seal,
        args.prior_source_seal,
    )
    if any(value is None for value in paths):
        parser.error(
            "Execution/replay requires output, both historical bundles, and all three source seals"
        )
    if args.execute:
        if args.device is None or args.source_commit is None:
            parser.error("Execution additionally requires device and exact source commit")
        result = run(
            args.output,
            args.original_bundle,
            args.prior_bundle,
            args.device,
            args.source_commit,
            args.source_seal,
            args.original_source_seal,
            args.prior_source_seal,
        )
        print(
            json.dumps(
                {"status": "COMPLETED", "fits": len(result["fits"]), "old_gate": PLAN["old_gate"]}
            )
        )
    else:
        print(json.dumps(verify(*paths), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
